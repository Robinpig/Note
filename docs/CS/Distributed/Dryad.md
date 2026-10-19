# Dryad

Dryad 是 Microsoft Research 在 2007 年（EuroSys）提出的**分布式数据流系统**，把计算建模成**有向无环图（DAG）**：图的顶点（vertex）是计算任务，边（edge）是顶点之间的数据通道。它的出现比 MapReduce 更通用——MR 只是"map → reduce"这一特化的两阶段 DAG，而 Dryad 允许任意形状的 DAG（多阶段流水线、分支、聚合、递归），适合表达比"一对 map/reduce"更复杂的批处理作业（如数据库查询计划、机器学习特征流水线）。

Dryad 与 [MapReduce](/docs/CS/Distributed/MapReduce.md) 构成"受限两阶段 vs 通用 DAG"的演进对照，其思想后来直接影响了 [Spark](/docs/CS/Framework/Spark/Spark.md) 的 RDD 血缘 DAG 与 Tez。

## Architecture

- **作业管理器（Job Manager）**：接收一个 DAG 描述，把它调度到集群上——为每个 vertex 选择可用节点、处理依赖（上游 vertex 完成才激活下游）、监控进度与失败。
- **顶点与通道**：vertex 是计算单元；vertex 之间的数据通过 **channel** 传输，channel 有多种实现——落盘文件（跨机器）、TCP 流（同机器不同进程）、共享内存（同进程）。调度器据此把能就近通信的 vertex 放在同一节点，减少网络拷贝。
- **无中心数据层**：与 MapReduce 把中间结果一律落 HDFS 不同，Dryad 的中间数据走轻量 channel，只在需要容错时才落盘，因此多阶段流水线的开销显著低于"每个阶段都是一次 MR job"。

## Fault Tolerance

- vertex 失败时，作业管理器在另一节点**重新调度**该 vertex；其输入能从上游重算或重读 channel（channel 落盘部分可恢复）。
- 这使得"长 DAG"也能在节点故障下继续，而不必从头重跑整个作业——这是相对嵌套多次 MR 提交的关键优势。

## Evolution: DryadLINQ and Legacy

- **DryadLINQ**：用 .NET LINQ 表达查询，编译器把它翻译成 Dryad DAG 并提交执行，让开发者用熟悉的集合算子写出分布式作业（类似后来 Spark 的 DataFrame/Dataset API 思路）。
- Dryad 本身未成为主流开源产品，但其"通用数据流 DAG + 编译期优化"的范式被 [Spark](/docs/CS/Framework/Spark/Spark.md)（RDD 血缘）、Tez（Hive 的 DAG 执行引擎）继承；与 [Borg](/docs/CS/Distributed/Borg.md) 的资源调度、[MillWheel](/docs/CS/Distributed/MillWheel.md) 的流式 DAG、[Pregel](/docs/CS/Distributed/Pregel.md) 的图 DAG 一起，体现了"把计算表达成图、由调度器在集群上执行"这一贯穿分布式系统的主线。

## Links

- [MapReduce](/docs/CS/Distributed/MapReduce.md)
- [Spark](/docs/CS/Framework/Spark/Spark.md)
- [Borg](/docs/CS/Distributed/Borg.md)
- [MillWheel](/docs/CS/Distributed/MillWheel.md)

## References

- Dryad: Distributed Data-Parallel Programs from Sequential Building Blocks (Isard et al., EuroSys 2007)
- DryadLINQ: A System for General-Purpose Distributed Data-Parallel Computing Using a High-Level Language (Yu et al., SIGMOD 2008)
