## Introduction

连接器（connector）是 Flink 与外部世界之间的边界：**Source** 把外部数据读进流，**Sink** 把结果写出去。它决定了作业的**端到端一致性**上限——即使 Flink 内部做到 exactly-once，若 Source 不可重放或 Sink 不支持幂等/事务，最终仍只能是 at-least-once。

一致性链路上，连接器与 [Checkpoint](/docs/CS/Framework/Flink/Checkpoint.md)、[State](/docs/CS/Framework/Flink/State.md) 是同一套机制的三段：Source 的读取位置存在 operator state 里，随 checkpoint 一起快照。

## Source：从 SourceFunction 到 FLIP-27

### 老接口的问题

早期的 `SourceFunction`（`addSource()`）把"发现数据分片"和"读取数据"混在一个接口里，还要求用户在 checkpoint lock 下自己处理并发，导致：

- 批、流两套实现要各写一遍；
- 分片（split / partition / shard）不是一等公民，难以实现按分片水位、事件时间对齐、动态分片分配、work stealing；
- 线程模型每个 source 各自造轮子，质量参差；
- checkpoint 锁由 source 持有，容易与数据处理抢锁。

### 新架构：SplitEnumerator + SourceReader

FLIP-27 把两者拆开：

| 组件 | 位置 | 职责 |
| ---- | ---- | ---- |
| `Source` | 工厂 | 创建 enumerator 与 reader 的入口 |
| `SplitEnumerator` | 通常运行在 JobManager | 发现分片（Kafka 分区、文件块、shard），分配给 reader；可周期性再发现（动态分区发现） |
| `SourceReader` | 运行在 TaskManager | 读已分配分片的数据，产出记录；把分片进度写入 checkpoint |

带来的能力：

- **批流统一**：同一份 source 实现，有界/无界只在于 enumerator 是否继续产出新分片；
- **原生水位**：`TimestampAssigner` / `WatermarkGenerator` 作为框架能力内置在 reader 里，天然支持按分片水位与空闲检测、水位对齐（见 [Time](/docs/CS/Framework/Flink/Time.md)）；
- **标准化指标**：跨 source 统一的吞吐、延迟、lag 指标；
- **可协调**：enumerator 在 JobManager 侧，便于做全局协调（如 Kafka 分区分配、文件枚举去重）。

> [!WARNING]
> Flink 2.x 已**移除** `SourceFunction`。新写连接器一律基于 FLIP-27 的 `Source` 接口；仍在用 `FlinkKafkaConsumer` 等老实现的作业，需要在升级到 2.x 前迁移到新实现（如 `KafkaSource`）。

### Kafka Source 示例

```java
KafkaSource<Event> source = KafkaSource.<Event>builder()
        .setBootstrapServers("broker:9092")
        .setTopics("clicks")
        .setGroupId("flink-group")
        .setStartingOffsets(OffsetsInitializer.committedOffsets(OffsetResetStrategy.EARLIEST))
        .setValueOnlyDeserializer(new EventDeserializer())
        .setProperty("partition.discovery.interval.ms", "60000")   // 动态发现新分区
        .build();

DataStream<Event> stream = env.fromSource(
        source,
        WatermarkStrategy.<Event>forBoundedOutOfOrderness(Duration.ofSeconds(5))
                .withTimestampAssigner((e, ts) -> e.getEventTimeMs()),
        "kafka-source");
```

注意 `KafkaSource` 现在与 [Kafka](/docs/CS/MQ/Kafka/Kafka.md) 的事务、消费者组语义直接相关：offset 由 Flink 托管在状态里（而非提交给 Kafka），恢复时以 Flink 状态为准。

## Sink：三种一致性级别

| 保证 | 实现方式 | 代价 |
| ---- | ---- | ---- |
| At-least-once | 普通 `SinkFunction` / `Sink` V2 直写 | 可能重复，最快 |
| Exactly-once（幂等） | Sink 侧按主键覆盖：Upsert Kafka、HBase、Redis、JDBC（带主键 upsert）、湖表（Paimon / Iceberg） | 要求下游支持幂等；不依赖事务 |
| Exactly-once（事务） | 两阶段提交（2PC）：预提交 → checkpoint 完成后提交 | 输出可见性被推迟到 checkpoint 完成，等于给端到端延迟加了一个 checkpoint 间隔 |

Kafka Sink 的事务写法：

```java
KafkaSink<Event> sink = KafkaSink.<Event>builder()
        .setBootstrapServers("broker:9092")
        .setRecordSerializer(KafkaRecordSerializationSchema.builder()
                .setTopic("result")
                .setValueSerializationSchema(new EventSerializer())
                .build())
        .setDeliveryGuarantee(DeliveryGuarantee.EXACTLY_ONCE)
        .setTransactionalIdPrefix("flink-")      // 开启 Kafka 事务
        .build();

stream.sinkTo(sink);
```

生产上踩过的两个坑：

- **Kafka 事务超时必须大于 checkpoint 间隔**：`transaction.max.timeout.ms` 若小于 checkpoint 完成时间，事务会被 Kafka 主动中止，表现为 "transaction timed out"；
- **读取侧要跳过未提交事务**：消费方需设置 `isolation.level=read_committed`，否则会读到被回滚的事务数据。

## 常用连接器一览

| 类别 | 代表 | 说明 |
| ---- | ---- | ---- |
| 消息队列 | Kafka、Pulsar、RabbitMQ | Kafka 最成熟，支持 Source/Sink 双向 exactly-once |
| 文件系统 | FileSink（HDFS / S3 / OSS） | 流式写文件，靠滚动策略 + 分区提交（part file 状态机：in-progress → pending → finished）保证可见性 |
| 湖存储 | Paimon、Iceberg、Hudi | Flink 2.x 主推的 Streaming Lakehouse 方向，Paimon 与 Flink 集成最深（支持物化表、自适应批执行等） |
| 数据库 / KV | JDBC、HBase、Redis、MongoDB | 多为幂等写入；JDBC 也可用 XA 做 2PC |
| 数仓 / 表格式 | Hive（读写 Hive 表、HiveCatalog） | 批流统一读写 Hive，适合离线数仓实时化 |

选型时的判断顺序：

1. 下游是否支持幂等/upsert？支持就走幂等，成本最低；
2. 不支持但支持事务？走 2PC，但接受延迟增加；
3. 都不支持（如普通文件追加、普通 Kafka topic）？只能是 at-least-once，下游自行去重。

## 端到端 Exactly-once 的完整条件

```
Source 可重放（Kafka / 文件系统，能按 offset、位置回到过去）
  + Flink 内部状态快照（Checkpoint + 对齐/非对齐）
  + Sink 幂等 或 两阶段提交事务
  = 端到端 exactly-once
```

三者缺一不可。也正因如此，"Flink 宣称的 exactly-once"落到具体链路上，一定要回到这三个环节逐个确认，而不是只看框架名。

## Links

- [Checkpoint](/docs/CS/Framework/Flink/Checkpoint.md)
- [State](/docs/CS/Framework/Flink/State.md)
- [Time](/docs/CS/Framework/Flink/Time.md)
- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)
- [Flink](/docs/CS/Framework/Flink/Flink.md)

## References

1. [Flink Docs - DataStream Connectors](https://nightlies.apache.org/flink/flink-docs-stable/docs/connectors/datastream/overview/)
2. [FLIP-27: Refactor Source Interface](https://cwiki.apache.org/confluence/display/FLINK/FLIP-27%3A+Refactor+Source+Interface)
3. [Flink Docs - Kafka Connector](https://nightlies.apache.org/flink/flink-docs-stable/docs/connectors/datastream/kafka/)
4. [Flink Blog - Introducing the new Kinesis/DynamoDB Streams sources（说明 2.x 移除 SourceFunction）](https://flink.apache.org/2024/11/25/introducing-the-new-amazon-kinesis-data-stream-and-amazon-dynamodb-stream-sources)
