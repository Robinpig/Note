## Introduction

Spark 的调度是把"一段用户代码"变成"成百上千个跑在 executor 上的 task"的全过程。理解它的关键是四层结构：

```
Application（一个 SparkContext）
  └── Job（每个 action 触发一个 Job）
        └── Stage（在宽依赖处切分；最后一个是 ResultStage，其余是 ShuffleMapStage）
              └── TaskSet → Task（一个分区一个 Task）
```

上游的图怎么来、怎么分层，见 [RDD](/docs/CS/Framework/Spark/RDD.md) 的依赖与 lineage；shuffle 边界为何成为 Stage 分界，见 [Shuffle](/docs/CS/Framework/Spark/Shuffle.md)。

## 核心组件

| 组件 | 位置 | 职责 |
| ---- | ---- | ---- |
| `DAGScheduler` | driver | 按 RDD 依赖图划分 Stage，提交 TaskSet；处理 shuffle 输出丢失、Stage 重试 |
| `TaskScheduler` | driver | 接收 TaskSet，按调度策略把 task 分给可用资源（含本地性、推测执行） |
| `SchedulerBackend` | driver | 与底层集群管理器打交道，申请/回收 executor（YARN / K8s / Standalone） |
| `MapOutputTracker` | driver + executor | 记录 shuffle map 输出的位置，供 reduce task 拉取 |
| `BlockManagerMaster` | driver | 维护数据块（RDD 缓存、广播、shuffle）的位置与状态 |

## Stage 怎么切

DAGScheduler 从触发 action 的 RDD **倒着**遍历依赖图：

- 遇到**窄依赖**就并入当前 Stage（可以流水线执行，不用落盘）；
- 遇到**宽依赖**（需要 shuffle）就断开：上游因此成为 `ShuffleMapStage`，下游开启新 Stage；
- 最终结果的那个 Stage 是 `ResultStage`。

因此一个 Job 的 Stage 数 = 宽依赖个数 + 1。这也解释了为什么 shuffle 越多、Stage 越多、落盘与网络开销越大。

## Task 调度与本地性

每个 Stage 生成一个 TaskSet（task 数 = 分区数），TaskScheduler 按**数据本地性**优先级投递：

| 级别 | 含义 | 理想程度 |
| ---- | ---- | ---- |
| PROCESS_LOCAL | 数据就在同一个 executor 的 JVM 里（如已缓存的 RDD 分区） | 最好 |
| NODE_LOCAL | 数据在同节点（本地磁盘 / 同节点其他 executor） | 次好 |
| RACK_LOCAL | 同机架 | 可接受 |
| ANY | 跨机架 | 最差 |

Spark 用**延迟调度（delay scheduling）**：优先等一小段时间看有没有更近的 slot，等不到才降级。这也是论文里 `getPreferredLocations` 的用途。

调度策略（同一 Application 内多个并行 Job 之间）：

- **FIFO**（默认）：先进先出；
- **FAIR**：按配置的 pool 公平共享资源，`spark.scheduler.mode=FAIR` + fairscheduler.xml。

## 容错

三层重试，粒度从细到粗：

1. **Task 失败重试**：默认最多 4 次（`spark.task.maxFailures`）。失败原因可能是代码异常、OOM、executor 丢失等；
2. **Stage 重算**：`FetchFailedException`（shuffle 数据拿不到，通常是 map 端 executor 挂了）会被上报给 DAGScheduler，触发**上游 ShuffleMapStage 重新计算**，而不是重算整个 Job——这正是 lineage 的价值；
3. **Application 失败**：重试次数用尽则作业失败。

配合机制：

- **排除机制**（老版本叫黑名单，4.x 起术语改为 exclude）：反复失败的 executor / 节点会被短期排除，避免坏节点拖垮作业；
- **推测执行（speculation）**：同一 task 跑得特别慢时另起一份，谁先完成用谁。Spark 4.0 起参数更保守（`spark.speculation.multiplier=3`、`spark.speculation.quantile=0.9`），减少无谓的重复计算；
- **动态资源分配**：按需申请与释放 executor，配合 external shuffle service 使用（否则 executor 被回收会丢 shuffle 数据）。

## 一次 action 的完整流程

```
rdd.collect()
  → SparkContext.runJob()
  → DAGScheduler: 建 ResultStage + 依赖的 ShuffleMapStage
  → 提交最上游 Stage 的 TaskSet
  → TaskScheduler 按本地性把 task 发给 executor
  → executor 反序列化 task，执行 compute(split, context)
  → ShuffleMapTask 写 data/index 文件并向 driver 汇报 map 输出位置
  → 后续 Stage 拉取数据 → 直到 ResultStage 完成
  → 结果返回 driver（collect）或写入外部系统
```

## 常见调度问题

| 症状 | 原因 | 方向 |
| ---- | ---- | ---- |
| Stage 里 task 数远超预期 | 分区数过多 | 调 `spark.sql.shuffle.partitions` / `spark.default.parallelism`，或交给 AQE 合并 |
| 少数 task 远超其他时长 | 数据倾斜或慢节点 | 倾斜见 [Shuffle](/docs/CS/Framework/Spark/Shuffle.md)；慢节点开推测执行 |
| 本地性全是 ANY | 资源紧张或数据与计算不在一处 | 增大 executor 数、检查 HDFS 与计算节点是否同置 |
| 反复 FetchFailed | executor 频繁回收 / 磁盘或网络问题 | 开 external shuffle service，关动态分配或调小释放速度 |

## Links

- [RDD](/docs/CS/Framework/Spark/RDD.md)
- [Shuffle](/docs/CS/Framework/Spark/Shuffle.md)
- [Memory](/docs/CS/Framework/Spark/Memory.md)
- [Deploy](/docs/CS/Framework/Spark/Deploy.md)
- [Spark](/docs/CS/Framework/Spark/Spark.md)

## References

1. [Spark Docs - Job Scheduling](https://spark.apache.org/docs/latest/job-scheduling.html)
2. [Spark Docs - Configuration: Scheduling](https://spark.apache.org/docs/latest/configuration.html#scheduling)
3. [Spark Docs - Migration Guide: Spark Core 4.0（推测执行参数变化）](https://spark.apache.org/docs/4.0.0/core-migration-guide.html)
