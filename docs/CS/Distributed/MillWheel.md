# MillWheel

## Introduction

MillWheel 是 Google 在 2013 年（VLDB）公开的**流式数据处理框架**，解决"在无界、乱序、延迟到达的数据流上做有状态、exactly-once 的计算"这一难题。它是 Google Cloud Dataflow 的底层引擎，也是 **Apache Flink / Spark Structured Streaming 的 watermark 与 event-time 模型的思想源头之一**。与 [MapReduce](/docs/CS/Distributed/MapReduce.md)（有界批处理）相对，MillWheel 代表"批 → 流"的演进。

## Key Mechanisms

- **Persistent State**：每个算子的状态（如聚合中间值）持久化到可靠的分布式存储（Bigtable 系），使任务失败重启后能恢复，不丢不重。
- **Exactly-once**：通过 checkpoint + 幂等 sink 实现端到端精确一次；MillWheel 保证记录被处理恰好一次（对下游副作用需配合幂等）。
- **Watermark（低水位线）**：系统为每个 key / 算子维护 watermark，表示"某时间戳之前的数据已全部到达"；用于处理乱序与延迟数据、触发窗口计算。这是后来 Flink `watermark` 概念的直接来源。
- **Per-key 状态与定时器**：支持按 key 维护状态与设定 timer，处理 session / 滑动窗口等。
- **Record 路由与去重**：相同记录（因重试）由系统去重，保证幂等。

## Relation to Other Topics

- 与 MapReduce：MapReduce 是**批处理**（有界数据集），MillWheel 是**流处理**（无界数据流）——构成"批 → 流"的演进。
- 与 Framework 的 [Flink](/docs/CS/Framework/Flink/Flink.md) / [Spark](/docs/CS/Framework/Spark/Spark.md)：它们在 API 与 watermark / event-time 语义上直接继承 MillWheel 的思路（Dataflow 模型）。
- 与 [Time（时钟与同步）](/docs/CS/Distributed/Time.md)：watermark 本质是"事件时间的进度估计"，与处理时钟、乱序延迟紧密相关。

## Links

- [MapReduce](/docs/CS/Distributed/MapReduce.md)
- [Distributed Storage](/docs/CS/Distributed/Distributed_Storage.md)
- [Time（时钟与同步）](/docs/CS/Distributed/Time.md)
- [Flink](/docs/CS/Framework/Flink/Flink.md)

## References

- MillWheel: Fault-Tolerant Stream Processing at Internet Scale (Akidau et al., VLDB 2013)
