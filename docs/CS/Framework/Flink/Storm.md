## Introduction

Apache Storm 是早期最具代表性的**分布式实时流计算框架**，在 Flink / Spark Streaming 成熟之前，它是低延迟流式处理的事实标准之一。理解 Storm 的拓扑模型与一致性短板，有助于理解 Flink 为什么会成为主流。

Storm 把无界数据抽象为持续到来的 **Tuple 流**，作业一旦提交就常驻运行，逐条处理记录，主打**亚秒级低延迟**和高吞吐的事件流处理。它由 BackType/Nathan Marz 提出，后进入 Apache 顶级项目。

## Topology

Storm 的作业称为 **Topology（拓扑）**，是一个由两种节点组成的 DAG，与 MapReduce 的“跑完即止”不同，拓扑会一直运行直到被手动 kill：

- **Spout**：数据源节点，对接外部系统（Kafka、消息队列、API）持续发出 tuple，是流的源头。
- **Bolt**：处理节点，消费上游 tuple 并执行过滤、聚合、join、写库等逻辑，可再向下游发射新的 tuple。

边定义了 tuple 如何在 Spout/Bolt 之间流动，每条边可指定 **Stream Grouping（流分组）**，即数据按什么方式分区到 Bolt 的并行实例（task）：

| Grouping | 语义 |
| ---- | ---- |
| Shuffle grouping | 轮询随机分发，负载均衡 |
| Fields grouping | 按指定字段 hash，相同字段值总到同一 task（类似 Flink `keyBy`，保证按 key 聚合正确） |
| All grouping | 广播给所有 task |
| Global grouping | 全部发到一个 task |
| Direct grouping | 由发射方显式指定下游 task |

## Architecture

- **Nimbus**：主节点，负责接收拓扑、分发代码、分配任务、故障调度（角色类似 Flink 的 JobManager）。
- **Supervisor**：工作节点守护进程，按 Nimbus 分配在本机启动/停止 **Worker** 进程（类似 TaskManager）。
- **Worker**：JVM 进程，内部跑若干 **Executor（线程）**，每个 Executor 跑一个或多个 **Task**（Spout/Bolt 的实例）。
- Nimbus 与 Supervisor 都是**无状态、快速失败**的，协调状态（任务分配、心跳）存放在 ZooKeeper，因此一个进程挂掉重启不影响正在运行的拓扑（早期版本 Worker 失败的消息重放保证则依赖下游机制）。

## Reliability

Storm 的可靠性模型是它和 Flink 的关键差异点：

- 核心机制是为每条进拓扑的“树根 tuple”维护一棵 **tuple 树**（基于 message id + ack/fail 的 `acker` 机制）：Spout 发出的根 tuple 派生出的所有下游 tuple 都被处理并 ack，才认为这条数据“处理成功”；超时或任意环节失败则通知 Spout **重放**。
- 这天然提供的是 **at-least-once（至少一次）**语义：失败会重放，可能导致重复处理。
- **exactly-once 不是内建能力**：Trident（Storm 之上的高层微批/状态抽象）才能在特定条件下做到有且一次，代价是退化为小批处理、延迟上升、API 复杂。
- 相比之下，Flink 依靠 [Checkpoint + barrier 对齐](/docs/CS/Framework/Flink/JobManager.md)与状态快照，在**流式模型内部**原生提供 exactly-once，这是 Flink 的核心优势之一。

## Storm vs Flink

| 维度 | Apache Storm | Apache Flink |
| ---- | ---- | ---- |
| 数据模型 | 逐条 Tuple 流 | 数据流 / 事件序列（DataStream），批是有界流 |
| 一致性语义 | 默认 at-least-once；Trident 才有 exactly-once（微批） | 原生 exactly-once（checkpoint barrier） |
| 状态管理 | 弱，状态需用户自行维护或借 Trident | 一等公民：keyed/operator state、state backend、savepoint |
| 时间语义 | 弱，事件时间/乱序/watermark 支持不足 | 完善的 event time、watermark、window、乱序处理 |
| 批流一体 | 主要面向流，批支持弱 | 同一运行时支持批与流 |
| 延迟 / 吞吐 | 极低延迟 | 低延迟且高吞吐，综合更优 |
| 主节点 | Nimbus（无状态 + ZK） | JobManager（Dispatcher/RM/JobMaster） |
| 工作节点 | Supervisor/Worker/Executor/Task | TaskManager/Slot/Task |
| 现状 | 社区活跃度下降，逐步被取代 | 流计算主流，社区活跃 |

总体上 Storm 开创了“常驻拓扑 + 逐条流处理”的范式（Spout/Bolt、fields grouping、acker 可靠性），但在状态一致性、事件时间与批流一体上的局限，使 Flink、Spark Structured Streaming 等成为后来主流；Storm 的概念仍能在 Flink 的 Source/算子、`keyBy` 分区、checkpoint 容错中看到对应影子。

## Links

- [Flink](/docs/CS/Framework/Flink/Flink.md)
- [Dataflow](/docs/CS/Framework/Flink/Dataflow.md)
- [JobManager](/docs/CS/Framework/Flink/JobManager.md)
- [Spark](/docs/CS/Framework/Spark/Spark.md)
- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)

## References

1. [Apache Storm Documentation](https://storm.apache.org/releases/current/index.html)
2. [Storm - Guaranteeing Message Processing](https://storm.apache.org/releases/current/Guaranteeing-message-processing.html)
3. [Apache Storm Tutorial - Concepts](https://storm.apache.org/releases/current/Concepts.html)
