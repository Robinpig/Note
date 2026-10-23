## Introduction

**RDD（Resilient Distributed Dataset，弹性分布式数据集）** 是 Spark 最底层的编程抽象：一个**只读的、被分区到多台机器上的对象集合**，并且分区丢失后可以被重建。论文里的关键表述是——RDD 的元素不必真的存在于物理存储中，RDD 的"句柄"只需包含足够的信息（血统 lineage），就能从可靠存储中的数据重新算出来；因此节点失败时总能重建。

"弹性（Resilient）"就来自这一点：**容错不靠复制，靠重算**。这与 [MapReduce](/docs/CS/Distributed/MapReduce.md) 靠落盘换容错不同，Spark 把中间结果尽量留在内存里，用 lineage 换可靠性。

## RDD 的五个内部属性

| 属性 | 含义 | 作用 |
| ---- | ---- | ---- |
| `partitions()` | 分区列表 | 决定并行度，一个分区一个 Task（见 [Scheduler](/docs/CS/Framework/Spark/Scheduler.md)） |
| `compute(split)` | 对单个分区的计算函数 | 迭代式地算出该分区的数据 |
| `dependencies()` | 依赖的父 RDD 列表 | 构成 lineage，用于容错与 Stage 划分 |
| `partitioner` | 分区器（仅 KV RDD） | HashPartitioner / RangePartitioner，决定 shuffle 后的数据落点 |
| `preferredLocations(split)` | 数据本地性提示 | 调度时把 Task 送到数据所在节点（延迟调度） |

论文里给出的接口就是这三件事：`getPartitions`、`getIterator(partition)`、`getPreferredLocations(partition)`。

## 依赖：窄依赖与宽依赖

这是理解 Spark 执行的关键分类：

| 类型 | 定义 | 是否触发 shuffle | 典型算子 |
| ---- | ---- | ---- | ---- |
| 窄依赖（narrow） | 父 RDD 的每个分区**至多**被子 RDD 的一个分区使用 | 否，可流水线执行 | `map`、`filter`、`mapPartitions`、`union`（部分） |
| 宽依赖（wide / shuffle） | 父 RDD 的一个分区被**多个**子 RDD 分区使用 | 是 | `groupByKey`、`reduceByKey`、`join`、`repartition` |

两个推论：

1. **Stage 在宽依赖处切分**：DAGScheduler 沿依赖图回溯，遇到宽依赖就断开成一个新 Stage（见 [Scheduler](/docs/CS/Framework/Spark/Scheduler.md)）；
2. **容错的粒度不同**：窄依赖失败只需重算父分区（代价小）；宽依赖失败可能需要重算多个父分区，代价大——这也是 checkpoint / 持久化的意义所在。

## 构造 RDD 的四种方式

沿用论文的分类：

- 从**共享文件系统**中的文件（如 HDFS）创建；
- 在 driver 程序里 **parallelize** 一个集合（如数组），即切分成若干 slice 发到各节点；
- 通过**变换（transformation）**已有 RDD；
- 通过改变已有 RDD 的**持久化（persistence）**设置。

```scala
val rdd  = sc.textFile("hdfs://...")            // 从文件
val rdd2 = sc.parallelize(1 to 1000, 10)        // 并行化集合，10 个分区
val errs = rdd.filter(_.startsWith("ERROR"))    // 变换
errs.persist(StorageLevel.MEMORY_AND_DISK)      // 改变持久化
```

## 惰性求值与算子分类

- **Transformation**（`map`、`filter`、`groupByKey`、`join` …）：惰性，只记录 lineage，返回一个新 RDD；
- **Action**（`reduce`、`collect`、`count`、`foreach`、`saveAsTextFile` …）：触发真正的计算，把结果返回 driver 或写到外部系统。

```scala
val counts = rdd.flatMap(_.split(" "))
                .map((_, 1))
                .reduceByKey(_ + _)     // 到这里一行都没执行
counts.collect()                        // action：才真正提交 Job
```

惰性让 Spark 有机会看到整条依赖链，从而做流水线（pipeline）与优化——这也是后来 DataFrame / SQL 能用 Catalyst 做全局优化的前提（见 [SQL](/docs/CS/Framework/Spark/SQL.md)）。

## 持久化

| StorageLevel | 语义 | 适用 |
| ---- | ---- | ---- |
| `MEMORY_ONLY` | 只放堆内内存，放不下则丢弃、用时重算 | 默认 `cache()`，内存足够且重算便宜 |
| `MEMORY_AND_DISK` | 内存不够的分区溢写磁盘 | 稳妥的通用选择 |
| `MEMORY_ONLY_SER` / `MEMORY_AND_DISK_SER` | 序列化后存储，省空间、费 CPU | 对象大、内存紧张 |
| `DISK_ONLY` | 只落盘 | 极大数据集 |
| 带 `_2` 后缀 | 双副本 | 降低缓存丢失带来的重算 |
| `OFF_HEAP` | 堆外内存 | 减少 GC 压力 |

`persist()` 也是惰性的（第一次 action 时才真正缓存），`unpersist()` 释放。

## Checkpoint

`checkpoint()` 把 RDD 的**数据**写到可靠存储（HDFS 等），并**截断 lineage**。与持久化的区别：

| 维度 | persist / cache | checkpoint |
| ---- | ---- | ---- |
| 存储位置 | Executor 内存/本地磁盘 | 可靠分布式存储 |
| lineage | 保留 | **截断** |
| 生命周期 | Application 结束即失效 | 可跨 Application 复用（需显式清理） |
| 目的 | 复用中间结果、加速迭代 | 切断过长的依赖链，降低重算代价、driver 容错 |

迭代式算法（PageRank、机器学习迭代）和图计算必须 checkpoint，否则 lineage 会随迭代次数线性增长，重算代价与 driver 内存都撑不住。

## 共享变量

闭包默认会**把引用的变量复制一份到每个 task**。Spark 提供两种受限的共享变量来覆盖两类常见模式：

- **广播变量（Broadcast variables）**：大只读数据（如查找表）在多个并行操作中用到时，与其随每个闭包打包发送，不如只分发一次到每个 worker。用 `sc.broadcast(v)` 创建，executor 侧只读。
- **累加器（Accumulators）**：worker 只能用结合律操作"加"，只有 driver 能读。可实现 MapReduce 风格的计数器或并行求和。由于只支持"加"语义，天然容易做到容错（重试时配合 AccumulatorV2 的幂等处理）。

```scala
val table = sc.broadcast(loadDimTable())
val blank = sc.longAccumulator("blankLines")

rdd.map { line =>
  if (line.trim.isEmpty) blank.add(1)
  line -> table.value.getOrElse(line, 0)
}
```

## RDD 在今天的位置

Spark 4.x 里 RDD 仍是**执行底座**：DataFrame / Dataset / SQL 最终都编译成 RDD 上的计算。但用户侧推荐优先用 DataFrame / Dataset——它们带 schema，能进 Catalyst 优化器（谓词下推、列裁剪、join 选择）与 Tungsten（堆外内存、代码生成），性能通常显著优于手写 RDD（尤其是 Python/Scala 闭包无法被优化的场景）。

## Links

- [Scheduler](/docs/CS/Framework/Spark/Scheduler.md)
- [Shuffle](/docs/CS/Framework/Spark/Shuffle.md)
- [Memory](/docs/CS/Framework/Spark/Memory.md)
- [SQL](/docs/CS/Framework/Spark/SQL.md)
- [Spark](/docs/CS/Framework/Spark/Spark.md)

## References

1. [Spark: Cluster Computing with Working Sets（RDD 原始论文）](https://people.csail.mit.edu/matei/papers/2010/hotcloud_spark.pdf)
2. [Resilient Distributed Datasets: A Fault-Tolerant Abstraction for In-Memory Cluster Computing](https://www.usenix.org/system/files/conference/nsdi12/nsdi12-final138.pdf)
3. [Spark Docs - RDD Programming Guide](https://spark.apache.org/docs/latest/rdd-programming-guide.html)
