## Introduction

Lambda 与 Kappa 是大数据领域少数有名字的**架构范式**，它们回答的是同一个问题：**既要实时、又要准确，系统该怎么搭**。这个问题之所以难，是因为在早期技术条件下这两个目标是冲突的——低延迟的流式计算会丢数据、算不准；准确的批计算要等数据攒够，出不了实时结果。

理解这两种范式及其后的"流批一体"，价值不在照搬架构图，而在于看懂**每一次更替都是在消除上一代的什么代价**。今天的湖仓架构里仍然能看到它们的影子。

## Lambda Architecture

Lambda 的思路非常直接：既然一套系统做不到，那就**上两套**。

- **Batch Layer**：保存完整的主数据集，周期性重算全量结果（批处理视图）。它慢，但**准确且可重算**——任何错误都能靠重跑修正。
- **Speed Layer**：只处理最近增量数据，用流式计算补上批层还没算出来的那一段（实时视图）。它快，但**近似**——用的是增量算法，可能有误差或不完整。
- **Serving Layer**：查询时把两个视图**合并**返回，用实时视图覆盖批视图的最新一段。

它成立的关键洞见是：批层提供了"最终正确"的保证，流层只是填空，因此流层的错误会被下一轮批计算自动修正。这个性质让系统可以放心地用不那么严谨的流式算法——代价是可接受的。

Lambda 的代价在工程量上，而且极其具体：

- **同一份业务逻辑要写两遍**（一套批、一套流），还要保证两者语义等价。这是最重的一项。
- 两套技术栈、两套运维、两套监控。
- **合并逻辑本身是 bug 温床**：两个视图的数据口径、时间点、去重规则必须严格对齐，否则查询结果在批层刷新前后会跳变。
- 最终结果在新一轮批计算完成前是**不一致的**，这个窗口就是批周期。

在 2010 年代中后期，Lambda 几乎是实时数仓的默认答案，大量生产系统至今仍是这个结构。

## Kappa Architecture

Jay Kreps 在 2014 年提出质疑时，切中的正是"两套代码"这个痛点。他的主张是：**去掉批层，只留流层**。

可行性建立在两个前提上：

1. **流处理引擎已经能做到精确一次语义**，不再需要批层来"兜底修正"。
2. **输入是一个可重放、可长期保留的日志**（Kafka 这类），因此"重算历史"就等于"把流作业从头再跑一遍"。

于是架构收敛成一条链路：所有数据进日志 → 一个流作业处理 → 结果直接可查。需要修正逻辑或补历史时，起一个新版本作业从更早的位点重放，算出一份新结果，再把流量切过去，最后停掉旧作业。

Kappa 把"两套代码"变成"一套代码 + 重放"，代价转移到了别处：

| 代价 | 说明 |
| :--- | :--- |
| 消息队列必须长期存全量历史 | 重算要能回溯。Kafka 靠分层存储 / tiered storage 缓解，但成本与保留策略仍是硬约束 |
| 重放吞吐要够 | 重算全量历史时，流引擎必须能以远高于实时的速度处理积压 |
| 结果存储必须支持版本切换 | 新旧两份结果并存、切换、回滚要有机制 |
| 迭代式 / 全量型算法不适用 | 需要"看到全部数据才能算"的逻辑（如某些全局去重、图算法）在纯流模型下很别扭 |

换句话说，Kappa 不是"Lambda 的简化版"，而是**把复杂度从代码层面搬到了基础设施层面**：要么你有能存全量历史的日志系统，要么 Kappa 就落不了地。

## Stream-Batch Unification

第三阶段的收敛发生在**引擎内部**，不再靠架构模式打补丁。核心主张是前面 [Processing Model](/docs/CS/BigData/Processing_Model.md) 提过的：批是有界的流。既然如此，就不需要两套系统，也不需要"重放历史"这个特殊操作——同一份代码，跑在历史有界数据上就是批，跑在持续到达的数据上就是流，语义完全一致。

两条实现路线：

- **Flink 路线**：内核只处理无界流，批是"读完就停"的流。批与流共用同一套算子、状态与容错机制，因此**结果必然一致**。2.x 起批执行模式在 TPC-DS 上已是可用方案，DataSet API 已移除，批作业统一走 DataStream API 的 BATCH 运行时模式。
- **Spark 路线**：以批为内核，流是微批的重复。4.x 的进展在缩小差距——4.1.0 引入 Spark Declarative Pipelines（声明式定义数据集与查询，由引擎负责执行图、依赖顺序、并行度、checkpoint 与重试）与 Structured Streaming 的 Real-Time Mode；4.2.0 加入 SQL `CHANGES` 子句，可在批与流两种模式下读取行级变更，并在声明式流水线里用 Auto CDC 直接做 SCD Type 1 的 upsert。

SQL 层面的统一同样重要：**同一段 SQL 既能跑批也能跑流**，意味着实时与离线不再需要两套口径。这是"流批一体"真正落地到业务侧的标志——此前即使引擎统一了，SQL 方言与语义差异仍会迫使团队维护两份逻辑。

## Comparison

| 维度 | Lambda | Kappa | 流批一体 |
| :--- | :--- | :--- | :--- |
| 系统套数 | 2（批 + 流） | 1（流） | 1（统一引擎） |
| 逻辑份数 | 2 份，需保证等价 | 1 份 | 1 份，批流语义一致 |
| 修正方式 | 下一轮批自动修正 | 起新作业重放 | 重跑或 replay，语义一致 |
| 基础设施要求 | 中等 | 高（日志存全量 + 重放吞吐） | 中等 |
| 一致性窗口 | 有（等于批周期） | 无 | 无 |
| 主要代价 | 双倍开发与运维 | 依赖可重放存储 | 引擎能力约束 |
| 当下适用性 | 存量系统多，新建不建议 | 日志基础设施强的团队 | 新建项目的默认选择 |

## How to Choose

- **新建实时链路**：直接上流批一体。选 [Flink](/docs/CS/Framework/Flink/Flink.md) 还是 [Spark](/docs/CS/Framework/Spark/Spark.md)，取决于延迟要求是秒级以内（Flink）还是分钟级且与离线 SQL 共用代码更重要（Spark）。
- **已有 Lambda 系统**：不要为了架构纯洁性做一次性重写。优先做的是**把批与流的逻辑收敛到同一份 SQL / 同一套声明式流水线**，等新旧逻辑验证等价后再下线批层。
- **重算需求极重、逻辑常变**：Kappa 的重放模型反而最合适——前提是消息系统的保留能力跟得上，这一层的能力差异见 [Future](/docs/CS/MQ/Future.md)。
- **全量型算法为主**（全局去重、图迭代、需要看到全部数据才能下结论）：纯流模型天生别扭，保留批层作为主路径反而更简单。

需要注意的是，"流批一体"作为术语常出现在厂商宣传里，判断是否真做到的标准只有一条：**同一份代码 / SQL 在批与流两种执行模式下，结果是否严格一致**。如果仍然要维护两套逻辑，那本质上还是 Lambda。

## Links

- [BigData](/docs/CS/BigData/BigData.md)
- [Processing Model](/docs/CS/BigData/Processing_Model.md)
- [Flink](/docs/CS/Framework/Flink/Flink.md)
- [Spark](/docs/CS/Framework/Spark/Spark.md)
- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)

## References

1. [How to beat the CAP theorem (Nathan Marz, 2011)](http://nathanmarz.com/blog/how-to-beat-the-cap-theorem.html)
2. [Questioning the Lambda Architecture (Jay Kreps, O'Reilly Radar 2014)](https://www.oreilly.com/radar/questioning-the-lambda-architecture/)
3. [Apache Flink - Batch as a special case of streaming](https://flink.apache.org/what-is-flink/flink-applications/)
4. [Apache Spark Declarative Pipelines](https://spark.apache.org/docs/latest/streaming-programming-guide.html)
