## Introduction

Kafka Streams 是 Kafka 官方提供的**客户端流处理库**（Java 库，不是独立集群）：把流处理拓扑作为普通 Java 应用运行，数据在 Kafka 主题之间消费、变换、再写回，依赖 Kafka 本身做容错（状态写 changelog 主题）与负载均衡。它的定位介于"自己写 Consumer 循环"与重型流计算框架（[Flink](/docs/CS/Framework/Flink/Flink.md)）之间。

## 核心抽象

- **KStream**：记录流，每条消息是一次独立事实（如点击事件），语义近似无限表的 INSERT；
- **KTable**：变更日志流，同 key 后写覆盖先写，逻辑上是一张持续更新的表（物化视图）；
- **GlobalKTable**：每个实例持有全量副本的表，用于小维表与大流做非分片 join；
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

## 状态与容错

- 本地状态默认存在 **RocksDB**（可落盘，超内存也能跑），每个分片的状态变更同时写入 **changelog 主题**（compact 主题）；
- 实例宕机或 rebalance 后，新 owner 从 changelog 回放重建状态；changelog 是其唯一事实来源，本地 RocksDB 只是缓存；
- 一次处理的进度靠消费 offset（consumer group）记录，与普通 [Consumer](/docs/CS/MQ/Kafka/Consumer.md) 同一套机制。

## 时间语义

- 事件时间（event time，从记录里的 timestamp 提取）、摄入时间、处理时间三选一（TimestampExtractor）；
- 窗口：tumbling（不重叠）、hopping（重叠）、session（按活动间隔合并）；
- **流时间驱动**：算子根据观察到的最大事件时间推进，基于 per-partition watermark（取该 task 各输入分区最小值），迟到记录落到下一个窗口或被 grace 宽限接收——概念与 Flink watermark 同源但实现更简单。

## exactly-once 与重试

- 开启 `processing.guarantee=exactly_once_v2` 后，消费 offset、状态变更、产出通过 Kafka 事务一并提交（read-process-write 全链路幂等）；
- 异常默认重试 `retries` 次后进 dead-letter 或炸掉应用，配合 `DeserializationExceptionHandler` 处理毒消息。

## 与 Flink / Consumer 自写的取舍

| 方案 | 部署形态 | 状态管理 | 适合 |
|------|---------|---------|------|
| 手写 Consumer | 应用内嵌 | 无/自建 | 简单 ETL、转发、落库 |
| **Kafka Streams** | 普通 JAR，无独立集群 | RocksDB + changelog，开箱即用 | 团队已在 Kafka 生态、中等复杂度的实时聚合/join |
| Flink | 独立 JobManager/TaskManager 集群 | keyed state + checkpoint（Chandy-Lamport） | 复杂窗口、事件时间严格、批流一体、多源多汇 |
| ksqlDB | Streams 之上的 SQL 接口 | 同 Streams | 非 Java、声明式实时查询 |

注意 Streams 按 topic 分区数决定最大并行度（一个分区同一时刻只能被一个 task 处理），扩并行度前要先扩分区。

## Links

- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)
- [Producer](/docs/CS/MQ/Kafka/Producer.md)
- [Consumer](/docs/CS/MQ/Kafka/Consumer.md)
- [Flink](/docs/CS/Framework/Flink/Flink.md)
- [Connect](/docs/CS/MQ/Kafka/Connect.md)

## References

1. [Kafka Streams Documentation](https://kafka.apache.org/documentation/streams/)
2. [Kafka Streams Developer Guide](https://docs.confluent.io/platform/current/streams/overview.html)
