## Introduction

Dataflow（数据流 / 数据传递模型）描述 Flink 作业中算子之间数据是如何流动的。Flink 的基本数据模型是**数据流与事件序列**，这与把数据看作一个个小批 RDD 的 Spark Streaming、以及把中间结果落盘的 MapReduce 有本质区别。

两条最直观的特征（沿用原笔记的观察）：

- **算子之间是 push（推）模型**：数据从上一个 operator 处理完后直接 push 给下一个 operator，事件驱动、流水式地在算子链里流动，而不是等上一阶段全部算完。
- **Shuffle 仍是推**：即便存在 shuffle（如 `keyBy`），Flink 也是由上游通过网络**主动推**给下游；这不同于 [MapReduce](/docs/CS/Framework/Hadoop/MapReduce.md) 模型里 Reduce 端主动从 Map 端**拉取（pull）**数据的方式。

正是这种原生的流式 push 执行，让同一个运行时既能处理无界流（streaming），也能处理有界流（batch，批被视为“有界的流”），实现批流一体。

## Graph Evolution

一个 Flink 作业从代码到物理执行要经过四层图的转换，前三步发生在 [Client](/docs/CS/Framework/Flink/Client.md) 与 [JobManager](/docs/CS/Framework/Flink/JobManager.md)：

1. **StreamGraph**：在 Client 端由用户 API 生成，是 DAG 的最初形态，节点对应每个算子 Transformation（`map`、`keyBy`、`window` 等），一一对应、不做合并。
2. **JobGraph**：Client 对 StreamGraph 做优化，把可以 chain 在一起的算子合并成一个 **JobVertex**，并加上中间数据集（IntermediateDataSet），是提交给集群的统一抽象（流/批都转成 JobGraph）。
3. **ExecutionGraph**：JobMaster 收到 JobGraph 后按**并行度**把每个 JobVertex 展开成多个 `ExecutionVertex`（每个就是一个可调度的子任务），是并行化后的“执行视图”。
4. **物理执行**：ExecutionVertex 以 Task 形式部署到 [TaskManager](/docs/CS/Framework/Flink/TaskManager.md) 的 Slot 中，Task 内部通过算子链真正处理数据。

```
API 调用 -> StreamGraph -> JobGraph(chain 优化) -> ExecutionGraph(按并行度展开) -> Task/Slot 物理执行
 Client                Client          JobManager                    TaskManager
```

## Operator Chaining

Flink 会把满足条件的多个算子**链（chain）**在一起，放进同一个 Task、由同一个线程执行，称为 operator chain。条件包括：上下游并行度相同、forward 分区（一对一）、同一 SlotSharingGroup 等。

链化的好处：

- 算子之间变成方法调用 / 线程内传递，**避免线程切换、序列化与网络开销**；
- 减少线程数与缓冲，降低延迟。

可以用 `disableChaining()`、`startNewChain()` 调整。链内数据直接对象引用传递；链之间（跨 Task、跨 TaskManager）才走网络栈与序列化。链化策略对应 Transformation 上的 `ChainingStrategy`：`ALWAYS / NEVER / HEAD / HEAD_WITH_SOURCES`。

## Data Exchange

跨算子链 / 跨 Task 的数据交换由网络层承担，核心组件：

- 上游 `RecordWriter` 把记录写进 **ResultPartition**（按下游子任务切成多个 ResultSubpartition）；
- 下游 Task 的 **InputGate**（含多个 InputChannel）消费对应分区；
- 传输基于 Netty，使用**基于信用（credit-based）的流控**：下游为每个 channel 声明可用 credit，上游只有拿到 credit 才发送，避免把下游压垮，这是 Flink 背压机制的基础。

### Partitioning / Shuffle

上下游之间的数据分区方式决定记录如何路由到并行子任务：

| 分区策略 | 语义 | 典型算子 |
| ---- | ---- | ---- |
| Forward | 一对一，记录原样到同编号子任务（可 chain） | map/filter 之后 |
| Rebalance | 轮询（round-robin）均匀打散 | `rebalance()`，解决数据倾斜 |
| Hash / KeyGroupStream | 按 key 的 hash 路由，保证同 key 进同一子任务 | `keyBy()` |
| Broadcast | 每条记录广播给所有下游子任务 | `broadcast()`、广播状态 |
| Rescale | 本地局部轮询（不跨全集群） | `rescale()` |
| Global | 全部发往下游第一个子任务 | 慎用，易成瓶颈 |

### Backpressure

当下游处理不过来时，credit 耗尽 → 上游停止网络发送 → 输入端缓冲被占满 → 反压一路传导回 Source，从而让整条链路按最慢算子的速度运行。Flink Web UI 可直接查看各任务的背压比例，定位慢算子。

## Stream vs Batch on Same Runtime

尽管 DataSet API（批）已逐步被 DataStream API 的批执行模式取代，但底层是**同一个流式运行时**：处理有界数据时，调度与 shuffle 可以采用更批式的优化（如阻塞式 shuffle、sort-merge shuffle、算子间流水线断开），处理无界数据时则全流水线常驻。这与 Spark “微批 RDD”、[Storm](/docs/CS/Framework/Flink/Storm.md) “至少一次为主”的执行模型形成对比。

## Links

- [Flink](/docs/CS/Framework/Flink/Flink.md)
- [Storm](/docs/CS/Framework/Flink/Storm.md)
- [Client](/docs/CS/Framework/Flink/Client.md)
- [JobManager](/docs/CS/Framework/Flink/JobManager.md)
- [TaskManager](/docs/CS/Framework/Flink/TaskManager.md)
- [Spark](/docs/CS/Framework/Spark/Spark.md)
- [MapReduce](/docs/CS/Framework/Hadoop/MapReduce.md)

## References

1. [Flink Docs - Dataflow Programming Model](https://nightlies.apache.org/flink/flink-docs-stable/docs/concepts/flink-architecture/)
2. [Flink Docs - Network Shuffle / Task Lifecycle](https://nightlies.apache.org/flink/flink-docs-stable/docs/internals/job_scheduling/)
3. [Flink Docs - Credit-based Flow Control](https://nightlies.apache.org/flink/flink-docs-stable/docs/ops/monitoring/back_pressure/)
