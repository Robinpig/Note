## Introduction

Kafka Streams 是 Kafka 官方提供的**客户端流处理库**（Java 库，不是独立集群）：把流处理拓扑作为普通 Java 应用运行，数据在 Kafka 主题之间消费、变换、再写回，依赖 Kafka 本身做容错（状态写 changelog 主题）与负载均衡。定位介于「自己写 Consumer 循环」与重型流计算框架（[Flink](/docs/CS/Framework/Flink/Flink.md)）之间。

> 版本基线：**4.3.1**（`gradle.properties:17`）。

## Core Abstraction

- **KStream**：记录流，每条消息是一次独立事实（如点击事件），语义近似无限表的 INSERT。
- **KTable**：变更日志流，同 key 后写覆盖先写，逻辑上是一张持续更新的表（物化视图）。
- **GlobalKTable**：每个实例持有全量副本的表，用于小维表与大流做非分片 join。
- 二者可互相转换：`KStream.toTable()`、`KTable.toStream()`。

```java
StreamsBuilder builder = new StreamsBuilder();
KStream<String, String> clicks = builder.stream("clicks");
KTable<String, Long> counts = clicks
        .mapValues(v -> 1)
        .groupByKey()
        .count();                              // 有状态算子，状态进 RocksDB + changelog
counts.toStream().to("click-counts");
KafkaStreams streams = new KafkaStreams(builder.build(), props);
streams.start();
```

## Key Configuration Defaults

`streams/src/main/java/org/apache/kafka/streams/StreamsConfig.java`：

| 配置名 | 默认值 | 行号 |
| ------ | ------ | ---- |
| `num.stream.threads` | 1 | 1010-1012 |
| `state.dir` | `${java.io.tmpdir}/kafka-streams`（Linux 即 `/tmp/kafka-streams`）| 906-911 |
| `cache.max.bytes.buffering` | 10 MB | 926-928 |
| `statestore.cache.max.bytes` | 10 MB | 932-934 |
| `commit.interval.ms` | **30000（30s）**；EOS 下**自动改为 100** | 常量 :167，EOS :168 |
| **`topology.optimization`** | **`none`**（不是 `all`）| 常量 :260，注册 :1053 |
| **`default.key.serde`** | **null**（未设抛 `ConfigException`）| 949-951，异常 :2113 |
| **`default.value.serde`** | **null** | 984-986，异常 :2137 |
| `processing.guarantee` | `at_least_once` | 常量 :403,411 |
| `max.task.idle.ms` | 0L（0 = 关闭）| 999-1001；`MAX_TASK_IDLE_MS_DISABLED = -1` :175 |
| **`replication.factor`** | **-1**（不是 1）| 1036-1038 |
| `num.standby.replicas` | 0 | 896-898 |
| `group.protocol` | `classic` | 常量 :581-583 |
| `errors.dead.letter.queue.topic.name` | `null`（DLQ 默认关闭）| 588 |

> [!WARNING]
> **`default.key.serde` / `default.value.serde` 默认是 `null`，不是 `StringSerde`** —— 未设置会抛 `ConfigException`。很多示例代码能跑是因为显式传了 Serde。
>
> **`topology.optimization` 默认 `none` 不是 `all`**（`StreamsConfig.java:260` `NO_OPTIMIZATION`）。
>
> **`replication.factor` 默认 `-1`**（不是 1）。`-1` 表示「沿用 broker 默认」，生产环境通常显式设 3。

> [!NOTE]
> **`cache.max.wait.ms` 在 4.3.1 中不存在**（全文件零匹配）—— 已随 record cache 弃用移除，缓存改为纯 size-based（`statestore.cache.max.bytes`）。

### consumer Internal Override Values

`StreamsConfig.java:1322-1328` 的 `CONSUMER_DEFAULT_OVERRIDES`：

```java
Map.of(
    ConsumerConfig.MAX_POLL_RECORDS_CONFIG, "1000",
    ConsumerConfig.AUTO_OFFSET_RESET_CONFIG, "earliest",
    ConsumerConfig.ENABLE_AUTO_COMMIT_CONFIG, "false",
    ConsumerConfig.GROUP_PROTOCOL_CONFIG, "classic",
    ConsumerConfig.ALLOW_AUTO_CREATE_TOPICS_CONFIG, "false")
```

EOS 时额外加 `ISOLATION_LEVEL_CONFIG = read_committed`（`:1333`）。

> [!TIP]
> **Streams 内部把 `consumer.auto.offset.reset` 覆盖为 `earliest`**（不是 `latest`）。另在 `:1944` 与 `:1978` 内部设为 `none` —— Streams 自行管理位点，不依赖客户端重置。
>
> 这意味着 standalone 调试时不会自动跳到末尾，**从头消费**，容易误判。

## group.protocol: Two Enums with the Same Name (Easy to Confuse)

> [!WARNING]
> Streams 与 clients 各有一个 `GroupProtocol` 枚举，**取值不同**：
>
> | 位置 | 枚举 | 取值 |
> | ---- | ---- | ---- |
> | `org.apache.kafka.streams.GroupProtocol` | Streams 侧 | **`CLASSIC` / `STREAMS`** |
> | `org.apache.kafka.clients.consumer.GroupProtocol` | clients 侧 | `CLASSIC` / `CONSUMER` |
>
> 两者默认值都是 `classic`（`StreamsConfig.java:582-583`）。
>
> 常见误解是「`group.protocol` 取 `classic`/`consumer`」—— 那是 **clients 侧**的取值。Streams 侧是 `classic`/`streams`。文档 `StreamsConfig.java:584-586` 明确：*"We currently support `classic` or `streams`"*。

约束：`group.instance.id`（静态成员）与 warmup replicas **仅在 `group.protocol=classic` 下可用**（`StreamsConfig.java:1565`、`:1569`）。

## exactly_once_v2: GA

> [!IMPORTANT]
> **`exactly_once_v2` 是 `processing.guarantee` 的正式合法值，不是 experimental/beta。**
>
> `StreamsConfig.java:411` 定义常量，`:1023` 的 validator 是 `in(AT_LEAST_ONCE, EXACTLY_ONCE_V2)` —— 与 `at_least_once` 平级。
>
> 文档 `docs/streams/developer-guide/config-streams.md:1620` 把它列为当前正式选项。`docs/streams/upgrade-guide.md:416` 记载 KIP-732 在 3.0 已将 `exactly_once_beta` 改名 `exactly_once_v2` 并强调"highlight the **production-readiness** of EOS version 2"。
>
> 4.3.1 的 `StreamsConfig` 中**已无** `exactly_once`（EOS v1）与 `exactly_once_beta` 常量 → **已完成移除**。

启用副作用：
- `commit.interval.ms` 默认自动变 **100ms**（`:478-479`、`:1654-1655`）—— 因为事务协调开销大，需高频提交
- 消费者 `isolation.level = read_committed`
- 生产者强制 `enable.idempotence = true`
- `replication.factor` 实际要求 ≥3（可用 `transaction.state.log.replication.factor` / `transaction.state.log.min.isr` 调整）

EOS 事务实现（`streams/.../processor/internals/StreamsProducer.java:249`）：

```java
producer.sendOffsetsToTransaction(offsets, consumerGroupMetadata);
```

## DLQ（KIP-1030，4.2 GA）

> [!WARNING]
> **配置名是 `errors.dead.letter.queue.topic.name`，默认 `null`，无 enable 开关** —— **配了 topic 名即启用**。
>
> 不是 `dead.letter.queue.enable`。
>
> `StreamsConfig.java:588` 定义，`:590-592` 说明两个限制：
> - 仅对**常规 stream processing task** 生效，**不适用于 global state store 更新（global threads）**
> - 若自定义了 deserialization/production/processing exception handler，对该 handler 忽略此参数
>
> 处理类（均检查该配置非 null 后构建 DLQ 记录）：`LogAndFailProcessingExceptionHandler.java:56`、`LogAndContinueExceptionHandler.java:55`、`LogAndFailExceptionHandler.java:55`、`DefaultProductionExceptionHandler.java:56`；校验 `errors/internals/ExceptionHandlerUtils.java:84`。

> [!NOTE]
> **Connect 侧 DLQ 前缀不同**：`errors.deadletterqueue.`（`SinkConnectorConfig.java:54`），且**有** enable 开关。两者不要混。

## 4.3.0 Important Changes

### KAFKA-20616: RocksDB Native Memory Leak

官方升级指南 `docs/streams/upgrade-guide.md:70` 原文：

> "**Note:** Kafka Streams 4.3.0 contains a **critical native memory leak** in the RocksDB state store layer ([KAFKA-20616]). The `ColumnFamilyOptions` for the **offsets column family is not closed**, and column family handles can leak on close-path exceptions, which under **cascading task closes (e.g., rebalances or error-triggered recoveries)** leads to **unbounded off-heap memory growth and eventual OOM**. Users running Kafka Streams should consider upgrading directly to 4.3.1, which includes the fix for it."

要点：

1. **泄漏源**：offsets column family 的 `ColumnFamilyOptions` 未关闭。
2. **触发路径**：close-path 抛异常时 column family handle 泄漏。
3. **放大条件**：**级联 task 关闭** —— rebalance 或错误触发的恢复。
4. **后果**：堆外内存无界增长直至 OOM。
5. **结论**：**4.3.0 有此 bug，应直接升到 4.3.1**。

> [!TIP]
> 「级联 task 关闭」是关键：单次关闭泄漏有限，但 rebalance 会同时关闭大量 task，把小泄漏放大成 OOM。所以**用了 Streams 且发生频繁 rebalance 的场景，4.3.0 风险很高**。

### KIP-1270: Exception Handling for Global Store

同一份文档记载：4.3.0 起可通过 KIP-1270 为 global store/KTable 配置 `ProcessingExceptionHandler`。

新配置 **`processing.exception.handler.global.enabled`**，默认 `false`，**推荐设为 `true`**。

> [!IMPORTANT]
> 限制：**DLQ 支持尚不适用于 global store/KTable**，需等后续版本。
>
> 此前 `ProcessingExceptionHandler` 只作用于常规 stream task。

### Other 4.3.0 KIPs

| KIP | 内容 |
| --- | ---- |
| KIP-1244 | 弃用 streams-scala |
| KIP-1259 | `state.cleanup.dir.max.age.ms` |
| KIP-1271 / KIP-1285 | State Store 存 Headers |

## State and Fault Tolerance

- 本地状态默认存在 **RocksDB**（可落盘，超内存也能跑），每个分片的状态变更同时写入 **changelog 主题**（compact 主题）；
- 实例宕机或 rebalance 后，新 owner 从 changelog 回放重建状态；changelog 是其唯一事实来源，本地 RocksDB 只是缓存；
- 一次处理的进度靠消费 offset（consumer group）记录，与普通 [Consumer](/docs/CS/MQ/Kafka/Consumer.md) 同一套机制；
- `RocksDBConfigSetter`（`streams/.../state/RocksDBConfigSetter.java`）用于调优 —— Window Store 与 State Store **共用 RocksDB 引擎**，差异通过此 setter 表达。

## Time Semantics

- 事件时间（event time，从记录里的 timestamp 提取）、摄入时间、处理时间三选一（`TimestampExtractor`）；
- 窗口：tumbling（不重叠）、hopping（重叠）、session（按活动间隔合并）；
- **流时间驱动**：算子根据观察到的最大事件时间推进，基于 per-partition watermark（取该 task 各输入分区最小值），迟到记录落到下一个窗口或被 grace 宽限接收 —— 概念与 Flink watermark 同源但实现更简单。

## Trade-offs with Flink / Hand-written Consumer

| 方案 | 部署形态 | 状态管理 | 适合 |
| ---- | -------- | -------- | ---- |
| 手写 Consumer | 应用内嵌 | 无/自建 | 简单 ETL、转发、落库 |
| **Kafka Streams** | 普通 JAR，无独立集群 | RocksDB + changelog，开箱即用 | 团队已在 Kafka 生态、中等复杂度的实时聚合/join |
| Flink | 独立 JobManager/TaskManager 集群 | keyed state + checkpoint（Chandy-Lamport） | 复杂窗口、事件时间严格、批流一体、多源多汇 |
| ksqlDB | Streams 之上的 SQL 接口 | 同 Streams | 非 Java、声明式实时查询 |

> [!IMPORTANT]
> Streams 按 topic 分区数决定最大并行度（一个分区同一时刻只能被一个 task 处理），**扩并行度前要先扩分区**。这是与 Flink（可独立调整并行度与 key group 粒度）最实质的差异。

## Common Claims That Need Debunking

| 说法 | 4.3.1 实况 |
| ---- | --------- |
| 「`exactly_once_v2` 仍是 experimental / beta」 | ❌ **已 GA**，是正式合法值；`exactly_once`/`exactly_once_beta` 已在 4.x 移除 |
| 「`topology.optimization` 默认 `all`」 | ❌ 默认 **`none`** |
| 「`default.key.serde`/`default.value.serde` 默认 `StringSerde`」 | ❌ 默认 **`null`**，未设抛 `ConfigException` |
| 「`consumer.auto.offset.reset` 默认 `latest`」 | Streams 内部覆盖为 **`earliest`** |
| 「`replication.factor` 默认 1」 | ❌ 默认 **`-1`** |
| 「`group.protocol` 取 `classic`/`consumer`」 | Streams 侧是 **`classic`/`streams`**；`classic`/`consumer` 是 clients 侧枚举 |
| 「DLQ 开关是 `dead.letter.queue.enable`」 | ❌ 是 **`errors.dead.letter.queue.topic.name`**，**无 enable 开关** |
| 「有 `cache.max.wait.ms`」 | ❌ **已移除**（record cache 弃用），改为 `statestore.cache.max.bytes` |
| 「有 `BuiltInMetrics` 类」 | ❌ 4.3.1 只有 `StreamsMetrics` |
| 「4.3.0 的 RocksDB 泄漏是 Kafka 核心问题」 | ⚠️ 是 **Streams 的 state store 层**（KAFKA-20616），4.3.1 已修复 |

## List Not Found

- `max.warmup.replicas` 的默认值（`StreamsConfig.java:1004` 定义存在，未读取数值行）
- `group.share.assignment.interval.ms` 同上
- Streams 指标的完整清单（`BuiltInMetrics` 类不存在，只能从 `StreamsMetrics` 逐个字段读）

## Links

- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)
- [Connect](/docs/CS/MQ/Kafka/Connect.md)
- [MirrorMaker](/docs/CS/MQ/Kafka/MirrorMaker.md)
- [Consumer](/docs/CS/MQ/Kafka/Consumer.md)
- [Flink](/docs/CS/Framework/Flink/Flink.md)
- [RocketMQ（对比：另一种消费模型）](/docs/CS/MQ/RocketMQ/Consumer.md)

## References

1. [Apache Kafka 4.3.1 Download](https://kafka.apache.org/downloads)
2. [StreamsConfig.java (4.3.1)](https://github.com/apache/kafka/blob/4.3.1/streams/src/main/java/org/apache/kafka/streams/StreamsConfig.java)
3. [Streams 升级指南（含 KAFKA-20616 原文）](https://github.com/apache/kafka/blob/4.3.1/docs/streams/upgrade-guide.md)
4. [KIP-1030: Streams DLQ](https://cwiki.apache.org/confluence/display/KAFKA/KIP-1030%3A+Add+Dead+Letter+Queue+support+to+Kafka+Streams)
