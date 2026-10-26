## Introduction

InfluxDB 是 Rust 重写的时序数据库，**3.x 版本**（2024 GA）标志着四年半的架构重构完成，底层全部基于 FDAP 栈：Apache **Flight**（数据传输）+ Apache **DataFusion**（向量化查询引擎）+ Apache **Arrow**（内存列式）+ Apache **Parquet**（持久化列式）。

InfluxDB 3.x 的定位是**实时观测数据缓冲 + 对象存储落盘**：摄入侧支持 metrics、logs、traces 三种信号（OTLP / Prometheus Remote Write / Influx Line Protocol / Loki / Elasticsearch Bulk），查询侧同时提供 SQL（DataFusion 引擎，完整）和 InfluxQL（3.x 保留，向后兼容）两种接口，持久化侧以 Parquet 文件落到对象存储（diskless 架构，本地只做缓存和可选 WAL）。

1.x/2.x 是 Go 写的旧版本——已停止新功能迭代，推荐全部迁移到 3.x。2.x 到 3.x 的迁移路径通过 `influxdb3-upgrade` 工具完成。

## Architecture

InfluxDB 3.x 有两种部署形态：

| 形态 | 组件 | 适用 |
| :-- | :-- | :-- |
| **Core（单机）** | 一个 `influxdb3` 进程，内置 Router + Ingester + Querier | 开发测试、小规模 |
| **Clustered（分布式）** | 三个独立服务：**Router**、**Ingester**、**Querier** | 大规模生产、对象存储、多副本 |

### 组件职责

| 组件 | 职责 |
| :-- | :-- |
| **Router** | 接收摄入和查询请求，路由到对应的 Ingester / Querier。写入侧做标签过滤、路由表选择，查询侧拆分并分发 |
| **Ingester** | 写入侧核心。把收到的数据放进内存 Arrow 内存表（buffer），同时**可选地写 WAL**。Buffer 满或时间窗口到，flush 成不可变 Parquet 文件 |
| **Querier** | 查询侧核心。从 Ingester 拉实时数据 + 从对象存储拉历史 Parquet 文件，用 DataFusion 执行向量化查询、合并结果 |

### 数据流

```
  摄入协议                Router                Ingester                  对象存储
  (ILP / OTLP /           │                    │                        │
   Prom RW / Loki)   ───▶ │   ────写入─────▶   │   flush ───▶ Parquet   │
                          │                    │                          │
                     路由表                WAL (可选)                    S3/GCS/Azure

  查询 ──────▶ Router ─────────────────▶ Querier ◀── DataFusion 向量化执行 ◀── Parquet
                                                     │
                                                     ▼
                                                   结果返回
```

关键设计：

- **Diskless 架构**：Ingester 的持久化数据**只放对象存储**，本地磁盘用来缓存远端 Parquet 文件 + 可选 WAL。Ingester 进程挂了重启后数据还在对象存储——Ingester 本身是无状态的。
- **WAL 可选**：关闭 WAL 时 Ingester crash 会丢 buffer 里的未 flush 数据；开启 WAL 则用本地磁盘保护——代价是本地磁盘 IO。对监控场景这通常可接受（下一个采集周期会覆盖）。
- **Arrow 内存 + Parquet 持久化**：内存里存 Arrow 列式格式、落盘时直接序列化成 Parquet。这保证了"持久化格式 = 内存格式的序列化"，无格式转换开销。

## Data Model

InfluxDB 的数据模型基于 **measurement + tags + fields + timestamp**：

```
measurement_name,tag_k1=tag_v1,tag_k2=tag_v2 field_k1=field_v1,field_k2=field_v2 timestamp_ns
```

四者的角色：

| 元素 | 类型 | 语义 |
| :-- | :-- | :-- |
| **measurement** | string | 一类采集点的集合（例如 `cpu`, `disk`, `http_requests`），类似关系表名 |
| **tag** | string → string | 标签（维度），用于过滤和分组。**tag 集合决定了序列身份**——相同 measurement + 相同 tag 组合 = 同一条时序 |
| **field** | 任意类型 | 动态采集值（float / int / str / bool）。**一条采样可以同时有多个 field**（如 CPU 同时记录 user/system/idle） |
| **timestamp** | ns precision | 采样时间戳 |

Influx Line Protocol 是 InfluxDB 定义的文本摄入格式，也是 3.x 最常用的写入入口：

```
cpu,host=server01,region=us-east usage_user=12.5,usage_system=2.1 1713715200000000000
cpu,host=server02,region=us-west usage_user=8.3,usage_system=1.8  1713715200000000000
```

### 与其他时序库数据模型对比

| 产品 | 等价概念 | 差异 |
| :-- | :-- | :-- |
| GreptimeDB | PRIMARY KEY(tag, ...) + TIME INDEX(ts) + Field | 用关系表语法声明，底层机制一致 |
| TDengine | supertable + tag 列 + metric 列 | 一设备一表的物理边界是关键差异 |
| Prometheus / VictoriaMetrics | metric_name + labels | 一个序列只存一个 float，没有 field 多值的概念 |

InfluxDB 模型在"多值序列"上最灵活——一个 measurement 一次采样可以同时存多个 field，共享同一时间戳。Prometheus 模型更纯粹但需要多个序列来表达同一时间点的多指标。

## Storage Engine

### Arrow + Parquet

3.x 的内存列式是 Apache Arrow——每个 measurement 在内存里有一个 Arrow RecordBatch，按 `(tag, timestamp)` 排序。flush 时直接把 Arrow 序列化成 Parquet 文件并上传到对象存储。

Parquet 文件内部：
- 每个 tag 列、每个 field 列、timestamp 列各自独立存放。
- 行内按 `(tag set, timestamp)` 排序——相同 tag 组合的序列连续排列，利于时间范围查询和压缩。
- 文件级时间范围元数据让 Querier 在**读之前**就能确定跳过不匹配的 Parquet 文件。

### DataFusion Query Engine

所有查询最终交给 **DataFusion**（Rust 写的向量化查询引擎）执行：

- SQL：DataFusion 有完整的 SQL 解析器、优化器、向量化执行器——支持 JOIN、窗口函数、子查询、CTE、聚合、排序。
- InfluxQL：3.x 保留，语法兼容旧版本。在内部被翻译成 DataFusion SQL 再执行。
- 向量化执行：一次处理一整列（而不是一行），用 SIMD 指令在 CPU 上并行。

### Compaction

Querier 在扫描 Parquet 文件时会触发后台 compaction：把多个小时间窗口的 Parquet 文件合并成一个大文件，同时做去重、时间范围更新、压缩格式统一。compaction 输出的大文件直接覆盖原文件在对象存储上的路径。

### 时间范围剪枝

三层剪枝保证查询效率：

1. **文件级**：Parquet 文件的时间范围元数据让 Querier 跳过整个文件。
2. **Row group 级**：每个 Parquet row group 带 min/max 统计，跳过无法匹配的 row group。
3. **Predicate pushdown**：DataFusion 把 `WHERE` 条件推到 Arrow / Parquet 读取层，只拉需要的列和行。

## Continuous Queries and Downsampling

InfluxDB 用 **Continuous Query (CQ)** 预定义降采样策略：

```sql
CREATE CONTINUOUS QUERY cpu_5m_avg ON metrics
BEGIN
    SELECT mean(usage_user) AS user_avg,
           mean(usage_system) AS sys_avg
    INTO metrics.cpu_5m
    FROM metrics.cpu
    GROUP BY time(5m), host, region
END
```

CQ 引擎定期拉取最近 5 分钟的 raw data，按 `(host, region)` 聚合后写入降采样 measurement `cpu_5m`。长窗口查询时直接读 `cpu_5m`，避免每次重算 raw data。

> InfluxDB 3.x 的 CQ 引擎仍然可用，但新负载推荐直接用 SQL + DataFusion 的能力替代——更灵活、支持 JOIN 和复杂聚合。

## Multi-Signal Support

InfluxDB 3.x 原生支持 metrics + logs + traces 三种信号的一体化存储：

| 信号 | 摄入协议 | 典型 measurement | 查询 |
| :-- | :-- | :-- | :-- |
| **Metrics** | OTLP / Prometheus Remote Write / ILP | `cpu`, `http_requests` | SQL / InfluxQL |
| **Logs** | OTLP / Loki Push / ILP | 结构化 log entries | SQL（全文搜索可用 Parquet + DataFusion 表达式） |
| **Traces** | OTLP | spans + trace_id 关联 | SQL（关联查询 trace_id 跨 measurement） |

三种信号**共享同一套存储和查询引擎**——可以一条 SQL 里 JOIN metrics、logs、traces，用 trace_id 关联 span 和日志。这一点上 InfluxDB 3.x 和 GreptimeDB 方向一致。

## Comparison

| 维度 | InfluxDB 3.x | GreptimeDB | TimescaleDB | VictoriaMetrics | TDengine |
| :-- | :-- | :-- | :-- | :-- | :-- |
| 语言 | Rust | Rust | C（PG 扩展） | Go | C |
| FDAP 栈 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 存储引擎 | Arrow + Parquet + DataFusion | Mito LSM + Parquet SST | PG + 列式压缩 | 自研 LSM part | 自研列式 LSM |
| 对象存储原生 | ✅ | ✅ | ❌ | ❌ | ❌ |
| WAL | 可选 | 多模式 | PG 自带 | ❌ | ✅ |
| SQL | ✅ DataFusion | ✅ MySQL/PG wire | ✅ 完整 PG | ❌ | 类 MySQL（无 JOIN） |
| PromQL | ✅ 兼容层 | ✅ 原生 | ❌ | ✅ MetricsQL | ❌ |
| InfluxQL | ✅ 保留 | ❌ | ❌ | ❌ | ❌ |
| 多信号 | metrics + logs + traces | metrics + logs + traces | ❌ | metrics only | ❌ |
| 存算分离 | ✅ | ✅ | ❌ | ❌ | ❌ |
| 对比其他 | FDAP 是最现代的技术栈，但相对 InfluxDB 1.x/2.x 迁移路径重 | GreptimeDB 保留了自己的时序专用存储引擎和 Flow | TimescaleDB 绑定 PG 生态但无法独立伸缩 | VM 轻量但只有 metrics | TDengine 一设备一表在 IoT 场景最优 |

## Links

- [DataBases](/docs/CS/DB/DB.md)
- [Timeseries](/docs/CS/DB/Timeseries.md)
- [GreptimeDB](/docs/CS/DB/GreptimeDB.md)
- [VictoriaMetrics](/docs/CS/DB/VictoriaMetrics.md)
- [TimescaleDB](/docs/CS/DB/TimescaleDB.md)
- [TDengine](/docs/CS/DB/TDengine.md)
- [QuestDB](/docs/CS/DB/QuestDB.md)
- [IoTDB](/docs/CS/DB/IoTDB.md)
- [OpenTSDB](/docs/CS/DB/OpenTSDB.md)
- [LSM Tree](/docs/CS/Algorithms/tree/LSM.md)
- [WAL](/docs/CS/DB/WAL.md)

## References

1. [InfluxDB 3 官方文档](https://docs.influxdata.com/influxdb3/)
2. [InfluxDB 3 Clustered Storage Engine](https://docs.influxdata.com/influxdb3/clustered/reference/internals/storage-engine/)
3. [InfluxDB 3 Core & Enterprise GA](https://www.influxdata.com/blog/influxdb-3-oss-ga/)
4. [DataFusion Project](https://arrow.apache.org/datafusion/)
5. [Influx Line Protocol 规范](https://docs.influxdata.com/influxdb/v2.7/reference/syntax/line-protocol/)
