## Introduction

大数据最早按**计算模式**分类，这个划分至今有效，因为它对应的不是产品而是四类本质不同的问题：数据是有界还是无界、结果是一次性给出还是持续更新、人在不在查询回路里、访问模式是扫描还是沿边跳转。选错范式，再怎么调优引擎都补不回来——用流式引擎做全量历史重算会被状态规模拖死，用批处理引擎做实时风控则永远达不到延迟预算。

四种模式落在两个正交的维度上：**数据是否有界**（bounded / unbounded）与**执行是否终止**（一次算出结果 / 持续运行）。批 = 有界 + 终止，流 = 无界 + 持续，交互 = 有界 + 终止但人在等，图 = 有界 + 迭代到收敛。

## Batch and Stream

| 维度 | Batch | Streaming |
| :--- | :--- | :--- |
| 数据边界 | 有界数据集，开始前已完整 | 无界流，持续到达 |
| 延迟 | 高，分钟到小时 | 低，毫秒到秒 |
| 数据体积 | 一次处理大块（Large chunks） | 逐条或小批，持续流入 |
| 任务生命周期 | 跑完即结束 | 常驻不停止 |
| 容错单位 | 重算失败的那一段（lineage / 重跑 task） | 从 checkpoint 恢复状态并继续 |
| 复杂度 | 低 | 高（要处理乱序、迟到、状态、精确一次） |
| 典型场景 | 报表、离线特征、全量回溯 | 实时监控、风控、在线推荐特征 |

两者的关系是理解现代引擎的关键。**批是流的特例**：把数据流截断在某一刻，它就是一份有界数据；批处理任务就是"数据有界、跑完终止"的流任务。这个方向的子集关系没有争议，争议在于**用哪个方向做统一**：

- **流是本质，批是有界的流**（Flink 路线）：引擎内核只处理无界流，批只是把结束条件设为"数据读完"。好处是批流语义完全一致，同一份代码在两种模式下结果相同；代价是批场景下要额外处理"有序终止"与状态收敛。
- **流是微批的重复**（Spark 路线）：把无界流切成一系列极小的批，用批引擎反复跑。好处是复用成熟的批执行与容错；代价是延迟被批间隔锁死，且"批次边界"会渗透到语义里（比如窗口是按批推进而非按事件推进）。

当代引擎在向对方的地盘靠拢：[Flink](/docs/CS/Framework/Flink/Flink.md) 的批执行模式在 TPC-DS 上已经是可用方案，[Spark](/docs/CS/Framework/Spark/Spark.md) 4.x 则为 Structured Streaming 加了 Real-Time Mode 以降低微批延迟。但**默认路径仍未变**：要秒级以内选 Flink，要分钟级且与离线 SQL 共用一份代码选 Spark。

## Interactive

交互式查询的约束与前两者都不同：查询形状完全不可预测，且**人等在屏幕前**。因此它的设计目标是"没有查询计划的前提下也能快"，手段是：

- **不落盘、流水线执行**：中间结果在内存里经网络直接流向下游算子，不做 stage 间物化。
- **向量化**：一批列值一起运算，摊薄解释开销。
- **牺牲容错换延迟**：查询失败就重跑，不做细粒度 checkpoint。这是 Trino / [Presto](/docs/CS/DB/Presto.md) 与 Spark 的根本分歧点——Spark 靠 lineage 重算换取了批处理下极好的容错，代价是不适合交互式；Trino 反过来。

典型实现是 Coordinator + Worker 的 MPP 拓扑，通过 connector 把异构数据源接成一张虚拟的联邦表。它**不存数据**，这是它与 [Doris](/docs/CS/DB/Doris.md)、[ClickHouse](/docs/CS/DB/ClickHouse.md) 这类自带存储的 OLAP 引擎的分界。

## Graph

图计算的访问模式与前三类相反：不是"扫一大块连续数据"，而是"沿边随机跳转到邻居"。这带来两个后果：

- 分区极其困难——无论怎么切分，跨机器的边都很多，且切分质量取决于图结构本身。
- 计算是**迭代到收敛**的（PageRank、最短路、社区发现），每一轮都要全图同步，适合 BSP（Bulk Synchronous Parallel）模型：超步 + 全局屏障 + 消息传递。

因此图计算通常是独立的引擎（Giraph、GraphX、Gelly），而不是批处理引擎的一个算子。现实中图计算需求相对小众，且多数场景可以用"图算法退化成若干轮 join"在 Spark 上凑合实现，所以这一格是四种模式里生态最薄、演进最慢的。

## Delivery Semantics

流处理绕不开的一个问题是**一条数据被处理几次**。三种语义的区别不是"好不好"而是"代价多大"：

| 语义 | 含义 | 实现代价 |
| :--- | :--- | :--- |
| At-most-once | 最多一次，可能丢 | 最低，失败不重放 |
| At-least-once | 至少一次，可能重复 | 中等，失败重放即可 |
| Exactly-once | 恰好一次，不丢不重 | 高，需要 checkpoint + 幂等 sink 或两阶段提交 |

Exactly-once 常被误解成"每条数据只被算一次"，实际上准确含义是**结果等价于每条数据只影响状态一次**。它靠两件事合成：引擎侧的一致快照（[Checkpoint](/docs/CS/Framework/Flink/Checkpoint.md)）保证状态与位点一致，输出侧要么幂等（覆盖写、upsert），要么参与事务（两阶段提交），否则重放时下游仍会看到重复。这也解释了为什么"端到端精确一次"必须连 sink 一起设计，而不只是引擎开关。

## Time and Window

流处理与批处理的另一个本质差异是**时间**。批处理里时间是数据的一个字段，流处理里时间决定正确性：

- **Event Time**：事件真正发生的时刻，嵌在数据里。乱序与迟到是常态。
- **Processing Time**：数据被处理的时刻。简单但不确定的——重放会得到不同结果。

用 event time 就必须回答"什么时候可以认为某段时间的数据到齐了"，答案是**watermark**（水位线）：一个随数据流动的"时间进度"断言，声明"早于 T 的数据应该都到了"。迟到数据则要靠 allowed lateness 或侧输出兜底。窗口是把无界流切成有限块做聚合的机制，滚动 / 滑动 / 会话三类与水位线的配合详见 [Time](/docs/CS/Framework/Flink/Time.md) 与 [Window](/docs/CS/Framework/Flink/Window.md)。

## Links

- [BigData](/docs/CS/BigData/BigData.md)
- [Lambda and Kappa Architecture](/docs/CS/BigData/Lambda_Kappa.md)
- [Flink](/docs/CS/Framework/Flink/Flink.md)
- [Spark](/docs/CS/Framework/Spark/Spark.md)
- [Presto](/docs/CS/DB/Presto.md)

## References

1. [Apache Flink - Streaming Analytics](https://flink.apache.org/what-is-flink/flink-applications/)
2. [Apache Spark Structured Streaming Programming Guide](https://spark.apache.org/docs/latest/structured-streaming-programming-guide.html)
3. [Google Cloud - Comparing batch and stream processing](https://cloud.google.com/learn/what-is-batch-processing)
4. [The Log: What every software engineer should know (Jay Kreps)](https://engineering.linkedin.com/distributed-systems/log-what-every-software-engineer-should-know-about-real-time-datas-unifying)
