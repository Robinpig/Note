## Introduction

Druid 的摄取面回答一个问题：**外部数据怎么变成深存储里的分片**。所有摄取最终都收敛到同一份「摄取规格」（ingestion spec），区别只在谁执行：批摄取是一次性任务（native batch 或 MSQ/SQL），流摄取是常驻 supervisor（Kafka/Kinesis）。37.0.0 是一次大断代——Hadoop 摄取整体移除、流摄取的 `parser` 被 `inputSource`/`inputFormat` 取代。本页按规格结构、批、流、输入矩阵四条线展开；摄取产生的分片长什么样在 [Storage_Format](/docs/CS/DB/Druid/Storage_Format.md)，之后的管理在 [Data_Management](/docs/CS/DB/Druid/Data_Management.md)。

## The Ingestion Spec

一份摄取规格（JSON）由五段组成，批任务与流 supervisor 共用骨架：

```
dataSchema      数据Source、timestampSpec（时间列）、dimensionsSpec、metricsSpec、
                transformSpec（行级转换）、granularitySpec（queryGranularity / rollup / segmentGranularity）
ioConfig        任务类型参数 + inputSource（数据从哪来）+ inputFormat（怎么解析）
tuningConfig    分片参数：targetRowsPerSegment、maxRowsInMemory、numShards、partitionsSpec……
task locks /    （MSQ 摄取特有）PARTITIONED BY / CLUSTERED BY / OVERWRITE 等子句
SQL 上下文
```

- **`timestampSpec` 决定 `__time`**：没解析出时间的行会被丢弃（或按配置落到别的列），这是「数据量少了」最常见的根因。
- **`transformSpec` 是行级表达式转换**：过滤、派生列、类型转换都在摄取时完成，落段即最终形态——摄取期转换比查询期转换便宜一个量级。
- **schema 自动发现**：不显式声明列时，Druid 从采样数据推断列名与类型；混合类型列默认按 `auto` 处理（31.0.0 起数组摄入默认走 `array` 模式）。

## Batch Ingestion

### Native Batch

`index_parallel` 是默认的批任务类型：多 Peon 并行读取输入、各自产中间结果，再由合并阶段拼分片。适合文件/S3/HTTP 等静态输入。老参数 `druid.indexer.task.allowHadoopTaskExecution` 在 34.0.0 起控制 Hadoop 任务开关，37.0.0 随 Hadoop 摄取一起消失。

### SQL-Based Ingestion（MSQ）

长在 MSQ 任务引擎上的 SQL 摄取，形态是 `INSERT INTO` / `REPLACE INTO ... SELECT`：

```sql
REPLACE INTO events_enriched OVERWRITE ALL
SELECT __time, channel, COUNT(*) AS cnt
FROM events
WHERE channel IS NOT NULL
GROUP BY 1, 2
PARTITIONED BY DAY
CLUSTERED BY channel
```

- **`PARTITIONED BY`** 指定新段的时间粒度；**`CLUSTERED BY`** 指定段内排序键（配合 31.0.0 起的灵活段排序，可显著优化特定过滤模式）。
- **`OVERWRITE ALL` / `OVERWRITE WHERE`** 精确控制覆盖范围；`REPLACE` 的墓碑段生成遵循查询指定的段粒度（29.0.0 行为修正）。
- **外部数据直接入湖**：`EXTERN()` 函数读取 S3/GCS/HTTP 上的 CSV/JSON/Parquet，配合 `INSERT` 完成「文件 → Druid」一步到位；读外部数据需要 `EXTERNAL READ` 权限（24.0.0 起）。
- **可靠性与回看**：`EXPLAIN PLAN FOR` 预览计划；支持 durable storage 存中间文件；38.0.0 起控制台可把流 supervisor 一键转成 SQL 摄取。

### Hadoop 之死

34.0.0 起 Hadoop 摄取需 opt-in，**37.0.0 整体移除**。替代路径：SQL-based ingestion 直接读 Parquet/ORC，或外部 Spark/Flink 预写对象存储再由 Druid 拉取。

## Streaming Ingestion

### Supervisors

流摄取由 **supervisor** 常驻管理：它是一个逻辑任务，持续在 Overlord 上运行，按需拉起/重启摄取任务，维护 Kafka/Kinesis 的 offset 与 checkpoint。

- **Kafka indexing service**（`druid-kafka-indexing-service`，核心扩展）：原生 Kafka 消费，支持 exactly-once（消费-写入在同一事务里，配合 Kafka 事务与 Druid 任务事务）。
- **Kinesis indexing service**（`druid-kinesis-indexing-service`）：Amazon Kinesis 的对应物，30.0.0 起内存调优参数改名（`recordBufferSizeBytes` / `maxBytesPerPoll`）。
- **Multi-supervisor 37.0.0 GA**：多个 supervisor 可同时写入同一数据源（28.0.0 引入的降级陷阱：降回 28.0.0 前必须先停掉多 topic supervisor）。
- **自动扩缩**：`taskCountMin` / `taskCount` / `taskCountStart` 控制任务数（37.0.0 改了起手式的解析顺序：`taskCountStart` → `taskCount` → `taskCountMin`）；36.0.0 引入**基于成本的流摄取扩缩**，按「追 lag 的收益 vs 空转成本」动态算任务数。
- **37.0.0 的 parser 断代**：supervisor 规格必须在 `ioConfig` 上指定 `inputSource`/`inputFormat`，`dataSchema` 不能再带 `parser`；`ParseSpec` 与 `JavascriptParseSpec`/`JSONLowercaseParseSpec` 一并移除（后两者没有 InputFormat 等价物，自定义文本格式请用 regex 输入格式或写原生 InputFormat 扩展）。
- **Thrift 输入格式 37.0.0 落地**（contrib 的 `druid-thrift-extensions`），接替被移除的 Thrift parser。

### Realtime Segments and Publishing

流任务先在内存/本地盘累积行（`maxRowsInMemory` 控制），攒满一个段就发布：写深存储、进元数据库、通知 Historical 加载，之后实时任务不再持有这段数据。发布前的「实时段」也参与查询（38.0.0 起用 `realtimeSegmentsMode` 控制查不查它们）。**发布是查询可见性的边界**——这也是流摄取「数据到哪了」这类问题的排查点。

## Input Sources and Formats

摄取规格的 `ioConfig` 由「源 × 格式」组合而成，两侧都可插拔：

| 输入格式（inputFormat） | 说明 |
| :--- | :--- |
| `json` / `csv` / `tsv` | 文本系主力；支持自动 schema 发现 |
| `parquet` / `orc` | 列存文件直接读（`druid-parquet-extensions` / `druid-orc-extensions`） |
| `avro` / `protobuf` / `thrift` | 二进制 schema 系（thrift 在 contrib） |
| `regex` | 自定义文本格式的兜底 |

| 输入源（inputSource） | 说明 |
| :--- | :--- |
| `local` / `http` / `inline` | 本地文件、HTTP(S) 拉取、规格内联数据（调试用） |
| `s3` / `google` / `azure` / `hdfs` | 各深存储后端（对应扩展） |
| `combine` | 多源合并 |
| `sql` | 用 SQL 查另一个 Druid 数据源当输入（reindex 的常用形态） |
| `druid` | 直接读已有段（compaction / reindex） |

29.0.0 起输入源还能暴露**系统字段**（如 S3 对象 URI），供 `transformSpec` 当数据血缘列用。

## Ingestion-Time Semantics Worth Knowing

- **Rollup 是摄取期决定、事后难改**：见 [Storage_Format](/docs/CS/DB/Druid/Storage_Format.md)；关掉 rollup 或改粒度都要 reindex。
- **并发追加与替换（concurrent append and replace）31.0.0 GA**：允许追加与压实/替换对同一区间并发进行，`useConcurrentLocks` 或集群级默认开启；这是「流摄取不因例行压实而停顿」的关键。
- **空插入查询 29.0.0 起默认允许**（`failOnEmptyInsert: true` 可恢复旧行为），`numTotalRows` 报 0 而非 null。
- **Kill 任务 30.0.0 起只在显式指定时才把底层段标记为 unused**——「删了数据但磁盘没释放」先查这里。
- **段分配粒度**：`segmentGranularity` 常见取值 HOUR/DAY；29.0.0 起月粒度无法分配时跳过周直接到天。

## Links

- [Druid](/docs/CS/DB/Druid.md)
- [Storage Format](/docs/CS/DB/Druid/Storage_Format.md)
- [Query Engine](/docs/CS/DB/Druid/Query_Engine.md)
- [Data Management](/docs/CS/DB/Druid/Data_Management.md)
- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)
- [Ecosystem](/docs/CS/DB/Druid/Ecosystem.md)

## References

1. [Druid Ingestion Overview](https://druid.apache.org/docs/latest/ingestion/)
2. [Native Batch Ingestion](https://druid.apache.org/docs/latest/ingestion/native-batch/)
3. [Apache Kafka Ingestion](https://druid.apache.org/docs/latest/development/extensions-core/kafka-ingestion/)
4. [SQL-based Ingestion Reference](https://druid.apache.org/docs/latest/multi-stage-query/reference/)
5. [Druid 37.0.0 Release Notes](https://druid.apache.org/docs/37.0.0/release-info/release-notes)
