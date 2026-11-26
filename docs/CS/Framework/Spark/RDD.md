## Introduction

**RDD（Resilient Distributed Dataset，弹性分布式数据集）** 是 Spark 最底层的编程抽象：一个**只读的、被分区到多台机器上的对象集合**，并且分区丢失后可以被重建。论文里的关键表述是——RDD 的元素不必真的存在于物理存储中，RDD 的"句柄"只需包含足够的信息（血统 lineage），就能从可靠存储中的数据重新算出来；因此节点失败时总能重建。

"弹性（Resilient）"就来自这一点：**容错不靠复制，靠重算**。这与 [MapReduce](/docs/CS/Distributed/MapReduce.md) 靠落盘换容错不同，Spark 把中间结果尽量留在内存里，用 lineage 换可靠性。

> [!NOTE]
> 本页源码基线：**Spark 4.3.0**（tag `v4.3.0`，commit `98bc0212`，2026-10-27）。以下片段均取自该 tag，不混用其它版本。

## RDD 的五个内部属性

| 属性 | 含义 | 作用 |
| ---- | ---- | ---- |
| `partitions()` | 分区列表 | 决定并行度，一个分区一个 Task（见 [Scheduler](/docs/CS/Framework/Spark/Scheduler.md)） |
| `compute(split)` | 对单个分区的计算函数 | 迭代式地算出该分区的数据 |
| `dependencies()` | 依赖的父 RDD 列表 | 构成 lineage，用于容错与 Stage 划分 |
| `partitioner` | 分区器（仅 KV RDD） | HashPartitioner / RangePartitioner，决定 shuffle 后的数据落点 |
| `preferredLocations(split)` | 数据本地性提示 | 调度时把 Task 送到数据所在节点（延迟调度） |

论文里给出的接口就是这三件事：`getPartitions`、`getIterator(partition)`、`getPreferredLocations(partition)`。

### Source: The Five Members on `RDD`

论文里的"五个属性"在 4.3.0 源码里对应 `RDD.scala` 抽象类的成员。注意它们不全是纯抽象方法：`compute` 是唯一的抽象方法并标注 `@DeveloperApi`，其余都有默认实现。

```scala
  /**
   * :: DeveloperApi ::
   * Implemented by subclasses to compute a given partition.
   */
  @DeveloperApi
  def compute(split: Partition, context: TaskContext): Iterator[T]

  /**
   * Implemented by subclasses to return the set of partitions in this RDD. This method will only
   * be called once, so it is safe to implement a time-consuming computation in it.
   *
   * The partitions in this array must satisfy the following property:
   *   `rdd.partitions.zipWithIndex.forall { case (partition, index) => partition.index == index }`
   */
  protected def getPartitions: Array[Partition]

  /**
   * Implemented by subclasses to return how this RDD depends on parent RDDs. This method will only
   * be called once, so it is safe to implement a time-consuming computation in it.
   */
  protected def getDependencies: Seq[Dependency[_]] = deps

  /**
   * Optionally overridden by subclasses to specify placement preferences.
   */
  protected def getPreferredLocations(split: Partition): Seq[String] = Nil

  /** Optionally overridden by subclasses to specify how they are partitioned. */
  @transient val partitioner: Option[Partitioner] = None
```

注释里有两处容易忽略的约束：`partition.index` 必须等于它在数组里的下标；`getPartitions` / `getDependencies` 只会被调用一次，因此实现里可以做耗时计算。`partitioner` 是 `@transient val Option[Partitioner]` 且默认 `None`，只有 KV RDD 才会覆盖它——这正是"带 schema 的 RDD 才能进 Catalyst 优化"的底层根据之一。

### Source: `iterator` Is the Single Entry Point

分区计算只有一个入口——`final def iterator`，它不可被子类覆盖。持久化判断在这个基类入口处统一完成，而不是散落在各子类内部。

```scala
  final def iterator(split: Partition, context: TaskContext): Iterator[T] = {
    if (storageLevel != StorageLevel.NONE) {
      getOrCompute(split, context)
    } else {
      computeOrReadCheckpoint(split, context)
    }
  }
```

分支条件是 `storageLevel != StorageLevel.NONE`：命中持久化走 `getOrCompute`（读缓存块，缺失才算并落盘），否则走 `computeOrReadCheckpoint`。这把 `persist()` 与 lineage 重算两条路径在入口处就分开了。

### Source: How Checkpoint Truncates Lineage

`computeOrReadCheckpoint` 是"checkpoint 截断血统"这一说法的代码级证据——它并不调用本 RDD 的 `compute`，而是委托给 `firstParent.iterator`，把计算链直接跳到 checkpoint 点。

```scala
  private[spark] def computeOrReadCheckpoint(split: Partition, context: TaskContext): Iterator[T] =
  {
    if (isCheckpointedAndMaterialized) {
      firstParent[T].iterator(split, context)
    } else {
      compute(split, context)
    }
  }
```

判定条件是 `isCheckpointedAndMaterialized = checkpointData.exists(_.isCheckpointed)`，同时覆盖 reliable 与 local 两种 checkpoint；另一个方法 `isReliablyCheckpointed` 才严格匹配 `ReliableRDDCheckpointData`。一个反直觉点：无论可靠还是本地 checkpoint，这里都统一走 `firstParent.iterator`，没有分叉。

> [!TIP]
> 4.3.0 在 `RDD.scala` 里新增了 `verifyCheckpointChecksums` 与 "sealed checksum" 机制（checkpoint 落盘时算校验和、读取时自检并将块封印为单一一致版本），属于 checkpoint 可靠性的增量加固，与 lineage 截断的主逻辑无关。


## 依赖：窄依赖与宽依赖

这是理解 Spark 执行的关键分类：

| 类型 | 定义 | 是否触发 shuffle | 典型算子 |
| ---- | ---- | ---- | ---- |
| 窄依赖（narrow） | 父 RDD 的每个分区**至多**被子 RDD 的一个分区使用 | 否，可流水线执行 | `map`、`filter`、`mapPartitions`、`union`（部分） |
| 宽依赖（wide / shuffle） | 父 RDD 的一个分区被**多个**子 RDD 分区使用 | 是 | `groupByKey`、`reduceByKey`、`join`、`repartition` |

两个推论：

1. **Stage 在宽依赖处切分**：DAGScheduler 沿依赖图回溯，遇到宽依赖就断开成一个新 Stage（见 [Scheduler](/docs/CS/Framework/Spark/Scheduler.md)）；
2. **容错的粒度不同**：窄依赖失败只需重算父分区（代价小）；宽依赖失败可能需要重算多个父分区，代价大——这也是 checkpoint / 持久化的意义所在。

### Source: Dependencies Are Serializeable Edges

`Dependency.scala` 把依赖体系的形式化契约压缩得很小：根类只有一个 `def rdd`，窄依赖的契约是"子分区依赖哪些父分区下标"，注释明确窄依赖 `allow for pipelined execution`。

```scala
@DeveloperApi
abstract class Dependency[T] extends Serializable {
  def rdd: RDD[T]
}

@DeveloperApi
abstract class NarrowDependency[T](_rdd: RDD[T]) extends Dependency[T] {
  def getParents(partitionId: Int): Seq[Int]
  override def rdd: RDD[T] = _rdd
}
```

`map` / `filter` 这类一一对应对应 `OneToOneDependency.getParents = List(partitionId)`，`union` / `cartesian` 对应 `RangeDependency` 的区间偏移映射。窄依赖在源码里就是"父分区下标列表"，可流水线执行的前提是子分区只需少量确定的父分区。

`ShuffleDependency` 则携带了 shuffle 的全部语义字段，`_rdd` 标 `@transient`（executor 侧不需要父 RDD）：

```scala
class ShuffleDependency[K: ClassTag, V: ClassTag, C: ClassTag](
    @transient private val _rdd: RDD[_ <: Product2[K, V]],
    val partitioner: Partitioner,
    val serializer: Serializer = SparkEnv.get.serializer,
    val keyOrdering: Option[Ordering[K]] = None,
    val aggregator: Option[Aggregator[K, V, C]] = None,
    val mapSideCombine: Boolean = false,
    val shuffleWriterProcessor: ShuffleWriteProcessor = new ShuffleWriteProcessor,
    val rowBasedChecksums: Array[RowBasedChecksum] = ShuffleDependency.EMPTY_ROW_BASED_CHECKSUMS,
    private val _checksumMismatchFullRetryEnabled: Boolean = false,
    val checksumMismatchQueryLevelRollbackEnabled: Boolean = false)
  extends Dependency[Product2[K, V]] with Logging {
```

`mapSideCombine` 默认 `false`，且开启时强制要求 `aggregator`（源码里 `require(aggregator.isDefined, "Map-side combine without Aggregator specified!")`）——这是 `reduceByKey` 能在 map 端先合并、从而优于 `groupByKey` 的形式化约束。值得注意的是 4.3.0 新增的 `shuffleHandle` 字段在依赖**构造期**就通过 `shuffleManagerFor(this).registerShuffle(shuffleId, this)` 决定用哪个 ShuffleManager，为下一节的第三类依赖埋下伏笔。

### A Third Dependency Kind in 4.3.0

经典教材把依赖分成窄依赖与宽依赖两类。**Spark 4.3.0 出现了第三类**：`PipelinedShuffleDependency`，它是 `ShuffleDependency` 的子类，输出可增量读取——consumer 在 producer 仍在运行时就能开始读，不必等材料完全物化。

```scala
@DeveloperApi
class PipelinedShuffleDependency[K: ClassTag, V: ClassTag, C: ClassTag](
    _rdd: RDD[_ <: Product2[K, V]],
    partitioner: Partitioner,
    serializer: Serializer = SparkEnv.get.serializer,
    keyOrdering: Option[Ordering[K]] = None,
    aggregator: Option[Aggregator[K, V, C]] = None,
    mapSideCombine: Boolean = false,
    shuffleWriterProcessor: ShuffleWriteProcessor = new ShuffleWriteProcessor,
    rowBasedChecksums: Array[RowBasedChecksum] = ShuffleDependency.EMPTY_ROW_BASED_CHECKSUMS)
  extends ShuffleDependency[K, V, C](
    _rdd, partitioner, serializer, keyOrdering, aggregator, mapSideCombine,
    shuffleWriterProcessor, rowBasedChecksums) {
  setShuffleMergeAllowed(false)
}
```

类体只有一句 `setShuffleMergeAllowed(false)`：push-based shuffle merge 要等全局 finalize 才暴露输出，与"边产边读"直接冲突。名字用 *pipelined* 而非 *streaming* 是刻意的——它是通用的执行能力（依赖 Stage 的软件流水），流处理只是第一个用户。这个类型担任两件事：给 DAGScheduler 当"producer / consumer 可并发"的 marker，以及在选择 shuffle manager 时作为类型路由键（见 [Shuffle](/docs/CS/Framework/Spark/Shuffle.md)）。

> [!WARNING]
> 别把"窄依赖 allow pipelined execution"与 4.3 的"pipelined shuffle"混为一谈：前者指**同一个 Stage 内**分区流水线（无需落盘），后者指**跨 Stage** 的 shuffle 边产边读，靠 `PipelinedShuffleDependency` 类型标识，由 DAGScheduler 并发调度。名字相同，层次不同。

### Why This Shape

- `iterator` 做成 `final` 且把持久化判断放在基类，是为了让所有 RDD 子类的缓存/重算语义统一，避免每个变换算子各自处理存储级别。
- 依赖被设计成可序列化的轻量边（根类只有 `def rdd`），才能让 driver 把依赖关系随 task 序列化到 executor，同时支撑 lineage 重算——这是"容错靠重算而非复制"的最小信息载体。
- 4.3 选择"新增一个 `ShuffleDependency` 子类"而非给宽依赖加布尔开关，是为了让"能否增量读"成为**类型级别**的静态契约：driver 与 executor 各自对依赖这个序列化字段做模式匹配即可一致的路由，不需要共享 `shuffleId → 行为` 的可变状态。代价是老代码里只匹配父类型 `ShuffleDependency` 的地方仍按"完全物化"看待它。

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
3. [Spark Docs - RDD Programming Guide](https://spark.apache.org/docs/4.3.0/rdd-programming-guide.html)
4. [RDD.scala @ v4.3.0](https://github.com/apache/spark/blob/v4.3.0/core/src/main/scala/org/apache/spark/rdd/RDD.scala)
5. [Dependency.scala @ v4.3.0](https://github.com/apache/spark/blob/v4.3.0/core/src/main/scala/org/apache/spark/Dependency.scala)
