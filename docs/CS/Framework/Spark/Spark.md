## Introduction

Apache Spark 是一个**统一的大规模数据分析引擎**：批处理、SQL 分析、流处理、机器学习（MLlib）与图计算（GraphX）共用同一套执行内核。它相对 [MapReduce](/docs/CS/Distributed/MapReduce.md) 的关键改进是——**支持工作集（working set）复用**，即把中间结果尽量留在内存中反复使用，同时保持与 MapReduce 相当的可扩展性与容错能力。

原始论文（Spark: Cluster Computing with Working Sets, 2010）的两条主张：

- Spark 面向"需要反复访问同一份数据"的应用（迭代算法、交互式查询），而无共享（share-nothing）模型对这类负载效率很低；
- 容错不靠复制，而靠 **RDD 的血统（lineage）重算**（见 [RDD](/docs/CS/Framework/Spark/RDD.md)）。

Spark supports applications with working sets while providing similar scalability and fault tolerance properties to MapReduce. Spark 用 Scala 实现，跑在 JVM 上，对外提供类似函数式集合操作的编程接口。

> [!NOTE]
> 本页是 Spark 子树的**枢纽页**，只做全貌与导航，各机制细节见子页。当前稳定版为 4.x 系列（4.2.0 于 2026-07 发布）；4.0 起要求 JDK 17、默认 Scala 2.13，并移除了 Mesos 支持，详见 [Deploy](/docs/CS/Framework/Spark/Deploy.md)。

## Programming Model

Spark 提供两层抽象：**弹性分布式数据集（RDD）** 与针对它的**并行操作**（把函数作用到数据集上）。此外支持两种受限的**共享变量**，供在集群上运行的函数使用（完整展开见 [RDD](/docs/CS/Framework/Spark/RDD.md)）。

### RDD

A resilient distributed dataset (RDD) is a read-only collection of objects partitioned across a set of machines that can be rebuilt if a partition is lost. RDD 的元素不必存在于物理存储中；RDD 的句柄只需包含"如何从可靠存储中的数据算出它"的足够信息，因此节点失败时总能重建。

构造 RDD 的四种方式：

- 从共享文件系统（如 HDFS）中的**文件**；
- 在 driver 程序中 **parallelize** 一个集合（如数组），把它切成若干 slice 发到多节点；
- 通过**变换（transformation）**已有 RDD；
- 通过改变已有 RDD 的**持久化（persistence）**设置。

算子分两类：**transformation**（惰性，只记录 lineage）与 **action**（触发计算）。依赖分**窄依赖 / 宽依赖**，宽依赖处切分 Stage 并触发 shuffle。

### Parallel Operations

RDD 上可执行的并行操作包括 `reduce`、`collect`、`foreach` 等；SQL / DataFrame 侧则是完整的 ANSI SQL 与 DataFrame API（见 [SQL](/docs/CS/Framework/Spark/SQL.md)）。

### Shared Variables

用户通过闭包（closure）调用 map/filter/reduce。按函数式编程惯例，闭包可以引用其定义作用域里的变量，Spark 默认会把这些变量**复制到每个 worker**。此外提供两种共享变量：

- **Broadcast variables（广播变量）**：大的只读数据（如查找表）被多个并行操作用到时，与其随每个闭包打包，不如只分发一次到每个 worker；
- **Accumulators（累加器）**：worker 只能用结合律操作"加"，只有 driver 能读；可实现 MapReduce 风格的计数器与并行求和。由于只支持"加"语义，容易做到容错。

## Architecture

论文时代的表述是"Spark 构建在 [Mesos](/docs/CS/Distributed/Mesos.md) 之上"——Mesos 让多个并行应用以细粒度方式共享集群，且大幅降低了 Spark 的实现成本。这是 2010 年的历史背景；**今天 Spark 支持多种集群管理器：Standalone / YARN / Kubernetes，Mesos 支持已在 Spark 4.0 移除**。

核心组件与职责：

| 组件 | 位置 | 职责 |
| ---- | ---- | ---- |
| Driver | 提交机或集群内 | 执行 `main()`，持有 SparkContext，划分 Stage 并调度（见 [Scheduler](/docs/CS/Framework/Spark/Scheduler.md)） |
| Executor | 集群节点 | 执行 task、存缓存与 shuffle 数据（内存布局见 [Memory](/docs/CS/Framework/Spark/Memory.md)） |
| Cluster Manager | 外部 | 分配/回收 executor 资源（见 [Deploy](/docs/CS/Framework/Spark/Deploy.md)） |

RDD 的实现是 Spark 的核心：每个 dataset 对象持有**指向父 RDD 的指针**以及"父 RDD 是如何被变换的"的信息。每个 RDD 内部实现同一套简单接口：

- `getPartitions`：返回分区 ID 列表；
- `getIterator(partition)`：迭代某个分区的数据；
- `getPreferredLocations(partition)`：用于调度，实现数据本地性。

在数据集上调用并行操作时，Spark 为**每个分区创建一个 task** 发到 worker 节点，并尽量用**延迟调度（delay scheduling）**把 task 送到它的 preferred location；task 启动后调用 `getIterator` 开始读取分区数据。

跨 Stage 的数据重分布就是 shuffle，是 Spark 主要的性能瓶颈（见 [Shuffle](/docs/CS/Framework/Spark/Shuffle.md)）。

## Streaming

Spark 的流处理走**微批（micro-batch）**：以固定时间间隔（几秒钟）处理一段段批处理作业，吞吐高、延迟相对较高，配合可重放 source 与 checkpoint 可保证 exactly-once。

- 旧 API（Spark Streaming / DStream）自 **3.4.0 起弃用**，官方标注为 legacy，不再更新；
- 现行方案是 **Structured Streaming**：把流看作无限增长的表，用 Spark SQL 引擎做增量查询（见 [Streaming](/docs/CS/Framework/Spark/Streaming.md)）。

与 [Flink](/docs/CS/Framework/Flink/Flink.md) 的模型差异：Flink 的基本数据模型是数据流与事件序列，逐事件流水式处理，可做到亚秒级延迟；Spark 是"攒一批 → 调度 → 算完 → 攒下一批"，吞吐优势明显而延迟更高。选型上，延迟敏感且要求事件时间正确性选 Flink；以批与 SQL 为主、能容忍秒级延迟选 Spark。

微批与"批是有界的流"是统一批流的两种相反路线，四种计算模式与三种投递语义的横向对比见 [Processing Model](/docs/CS/BigData/Processing_Model.md)，这套取舍在架构层的投射见 [Lambda and Kappa Architecture](/docs/CS/BigData/Lambda_Kappa.md)。

## Links

- [RDD](/docs/CS/Framework/Spark/RDD.md)
- [Shuffle](/docs/CS/Framework/Spark/Shuffle.md)
- [Memory](/docs/CS/Framework/Spark/Memory.md)
- [Scheduler](/docs/CS/Framework/Spark/Scheduler.md)
- [SQL](/docs/CS/Framework/Spark/SQL.md)
- [Streaming](/docs/CS/Framework/Spark/Streaming.md)
- [Deploy](/docs/CS/Framework/Spark/Deploy.md)
- [Flink](/docs/CS/Framework/Flink/Flink.md)
- [Hadoop](/docs/CS/Framework/Hadoop/Hadoop.md)
- [MapReduce](/docs/CS/Distributed/MapReduce.md)
- [Mesos](/docs/CS/Distributed/Mesos.md)

## References

1. [Spark: Cluster Computing with Working Sets](https://people.csail.mit.edu/matei/papers/2010/hotcloud_spark.pdf)
2. [Resilient Distributed Datasets: A Fault-Tolerant Abstraction for In-Memory Cluster Computing](https://www.usenix.org/system/files/conference/nsdi12/nsdi12-final138.pdf)
3. [Spark Documentation](https://spark.apache.org/docs/latest/)
