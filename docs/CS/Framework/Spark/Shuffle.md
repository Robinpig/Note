## Introduction

Shuffle 是 Spark 里**跨 Stage 重新分布数据**的过程：宽依赖算子（`groupByKey`、`join`、`repartition` 等）要求同 key 的数据落到同一分区，于是每个 map task 必须把自己产出的数据按目标分区切分、落盘，再由下游 task 跨网络拉取。它同时涉及磁盘 I/O、网络传输、序列化与排序，是 Spark 作业最主要的性能瓶颈来源。

与之配套的 Stage 划分逻辑见 [Scheduler](/docs/CS/Framework/Spark/Scheduler.md)，内存侧的缓冲与记账见 [Memory](/docs/CS/Framework/Spark/Memory.md)。

## 演进：三代 Shuffle

| 阶段 | 做法 | 问题 / 改进 |
| ---- | ---- | ---- |
| Hash Shuffle（1.1 之前） | 每个 map task 为每个 reduce task 各写一个文件，共 $M \times R$ 个 | 文件数爆炸、随机 I/O 与内存开销大；0.8.1 引入文件合并（consolidate）缓解 |
| Sort Shuffle（1.1 引入，1.2 起默认） | 每个 map task 只写**一个 data 文件 + 一个 index 文件**，共 $2M$ 个 | 文件数可控；代价是引入排序开销 |
| Tungsten / Unsafe Sort Shuffle（1.4 引入，1.6 并入 SortShuffleManager） | 用堆外内存 + 二进制行格式，按分区排序后 spill | 降低 GC 压力、减少内存占用；成为事实标准 |
| —— | Spark 2.0 起 hash shuffle 被移除 | 只剩一条路径 |

现在的 `SortShuffleManager` 会根据情况选择 writer：

- `BypassMergeSortShuffleWriter`：分区数较少且**不需要 map 端聚合**时，绕过排序直接按分区写再合并，省掉排序成本；
- `SortShuffleWriter`：通用路径，需要排序或 map 端聚合；
- `UnsafeShuffleWriter`：Tungsten 序列化路径，堆外内存管理。

## Map 端发生了什么

```
ShuffleMapTask 执行
  → 每条记录经 partitioner 计算目标分区
  → 写入内存缓冲区（AppendOnlyMap / ExternalAppendOnlyMap，走 Tungsten 内存页）
  → 需要 map 端聚合时（reduceByKey / aggregateByKey）先本地 combine
  → 缓冲区达到阈值 → 按 (partitionId, key) 排序 → spill 到磁盘
  → task 结束时把所有 spill 文件 + 内存残留 merge 成一个 data 文件 + index 文件
```

要点：

- **有 map 端聚合（combine）的算子会大幅减少落盘与网络数据量**，这就是 `reduceByKey` 优于 `groupByKey` 的根本原因；
- spill 次数过多说明 shuffle 内存不足或分区数不合理；
- map 端输出**保留在本地磁盘**，由 BlockManager 管理，因此 executor 挂掉会丢失 shuffle 数据——这是外部 shuffle service 存在的理由。

## Reduce 端发生了什么

```
ShuffleMapStage 结束 → 下游 Stage 启动
  → 每个 reduce task 向各节点的 BlockManager / ExternalShuffleService 拉取属于自己的分区
  → 边拉边聚合（或先落盘再归并排序）
  → 交给下游算子计算
```

- 拉取失败（`FetchFailedException`）会触发 **Stage 重算**：DAGScheduler 把对应 map stage 重新调度，这也是 Spark 容错的典型路径；
- 拉取端的 `spark.reducer.maxSizeInFlight` 控制并发拉取量，`spark.shuffle.io.*` 控制超时与重试；
- 启用 **External Shuffle Service** 后，shuffle 数据的生命周期与 executor 解耦，配合动态资源伸缩（executor 被回收仍能提供数据）。Spark 4.0 起默认让 shuffle service 在不再需要时删除 shuffle block（`spark.shuffle.service.removeShuffle`）。

## 分区数：最常被调错的旋钮

- `spark.sql.shuffle.partitions` 默认 **200**（SQL / DataFrame 侧），RDD 侧由 `spark.default.parallelism` 或算子参数决定；
- 太少 → 单分区数据量大、容易 OOM 与倾斜；太多 → 小文件与小任务过多，调度与 I/O 开销暴增；
- 有了 **AQE（Adaptive Query Execution，Spark 3.2 起默认开启）** 后，Spark 会按 map 输出的真实统计**合并相邻小分区**（`spark.sql.adaptive.coalescePartitions.enabled`），因此可以把初始分区数设得偏大一些，交给运行时收缩（见 [SQL](/docs/CS/Framework/Spark/SQL.md)）。

## Push-based Shuffle

Spark 3.2 引入（SPARK-30602）：map task 写完数据后**主动把分区数据推送**到外部 shuffle service 做合并（shuffle merge），reduce 端只需拉合并后的大块数据。收益是减少小文件与随机 I/O、提高大 shuffle 的稳定性；代价是需要部署外部 shuffle service，且更适配 YARN 这类形态。

## 常见问题与定位

| 症状 | 常见原因 | 方向 |
| ---- | ---- | ---- |
| 某个 task 特别慢 / OOM | **数据倾斜**：热点 key 集中到一个分区 | AQE 倾斜 join 处理、加盐打散、改 join 策略 |
| spill 次数巨大 | shuffle 内存不足或分区过多 | 调 `spark.memory.fraction`、分区数、开启 map 端聚合 |
| `FetchFailedException` 频发 | executor 被回收 / 网络超时 / 磁盘故障 | 开 external shuffle service、调超时、查节点健康 |
| 磁盘写满 | shuffle 数据未清理 | 检查 shuffle service 清理配置与 executor 生命周期 |
| 上游数据量远大于输出 | 缺 map 端聚合 | 用 `reduceByKey` / `aggregateByKey` 替代 `groupByKey` |

看 UI 的关键指标：Shuffle Read / Write 量、spill（memory/disk）、task 时长分布（是否长尾）。

## Links

- [RDD](/docs/CS/Framework/Spark/RDD.md)
- [Scheduler](/docs/CS/Framework/Spark/Scheduler.md)
- [Memory](/docs/CS/Framework/Spark/Memory.md)
- [SQL](/docs/CS/Framework/Spark/SQL.md)
- [Spark](/docs/CS/Framework/Spark/Spark.md)

## References

1. [Spark Docs - Shuffle Behavior / Configuration](https://spark.apache.org/docs/latest/configuration.html#shuffle-behavior)
2. [Spark Release 3.2.0（push-based shuffle SPARK-30602）](https://spark.apache.org/releases/spark-release-3-2-0.html)
3. [Spark Docs - Migration Guide: Spark Core 4.0（shuffle service 相关默认值变化）](https://spark.apache.org/docs/4.0.0/core-migration-guide.html)
