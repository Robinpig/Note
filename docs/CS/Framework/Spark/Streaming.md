## Introduction

> [!NOTE]
> 本页源码基线：**Spark 4.3.0**（tag `v4.3.0`，commit `98bc0212`，2026-10-27）。以下片段均取自该 tag，不混用其它版本。

Spark 的流处理有两条世代不同的路线：

| 路线 | 抽象 | 状态 | 说明 |
| ---- | ---- | ---- | ---- |
| Spark Streaming（DStream） | 一串小批 **RDD** | **自 Spark 3.4.0 起弃用**（官方标注为 legacy，不再更新） | 微批模型，延迟较高但语义成熟 |
| Structured Streaming（micro-batch） | 无限增长的**表** + 增量查询 | 主推、默认 | 与 Spark SQL 同一套引擎，能用 Catalyst 与 Tungsten |
| Real-Time Mode（4.3.0） | 同一套 API，长驻 task 持续处理 | **4.3 起 GA**（SPARK-57281 移除 `@Experimental`） | 毫秒级延迟，4.3 起支持有状态查询，详见下文 |

> [!WARNING]
> 新作业不要用 DStream。官方建议迁移到 Structured Streaming；`StreamingContext` / `JavaStreamingContext` 已在 3.4 标注弃用。

两条路线的共同点都是**微批（micro-batch）**：把流按固定间隔切成小批，每批当成一个小批作业跑。这与 [Flink](/docs/CS/Framework/Flink/Flink.md) 的"逐事件流水式处理"是模型层面的差别——Flink 是事件驱动、数据在算子链里持续流动；Spark 是"攒一小批 → 调度 → 算完 → 攒下一批"（见 [Dataflow](/docs/CS/Framework/Flink/Dataflow.md)）。

## Structured Streaming 的核心模型

- **输入** = 一张不断追加行的**无限表**；
- **查询** = 在这张表上做增量化的 SQL / DataFrame 变换；
- **结果** = 一张结果表，按输出模式写往 sink。

因为跑在 Spark SQL 引擎上，谓词下推、列裁剪、codegen、AQE（部分能力）都可以复用，这是它相对 DStream 最大的工程优势。

## 触发模式（Trigger）

| 模式 | 语义 | 延迟 | 适用 |
| ---- | ---- | ---- | ---- |
| 默认（不指定） | 上一批完成后立刻起下一批 | 百毫秒级 | 通用 |
| `Trigger.ProcessingTime(interval)` | 固定间隔起批 | = 间隔 | 控制资源与下游写入节奏 |
| `Trigger.Once()` | 只跑一批（把可用数据算完就停） | —— | 批处理式补数、低成本增量同步 |
| `Trigger.Continuous(interval)` | 连续处理模式，长驻任务持续处理 | 毫秒级 | 低延迟诉求，能力受限 |
| `Trigger.RealTime()`（4.3.0） | 长驻 task + pipelined shuffle，每 `batchDurationMs` 提交一次进度 | 毫秒级 | Real-Time Mode 的触发器，4.3 起支持有状态查询 |

## Real-Time Mode (4.3.0)

这是 4.3.0 最重磅的流处理变化。它复用了 Structured Streaming 的 API 与 `MicroBatchExecution` 执行器，但换掉了"每批重新调度 task"的模式——启动**长驻 task（long-running tasks）**持续读取与处理输入，从而消除每批的调度开销。官方文档给出的数据：微批端到端延迟下限约 100ms，Real-Time Mode 降到"处理与传输一条记录所需的时间（通常几毫秒）"。

> [!WARNING]
> 4.3 之前 Continuous Mode 常被拿来与 Flink 的逐事件模型类比，但它能力受限且带 `@Experimental`；4.3 的 Real-Time Mode 才是正式的毫秒级方案。别再写"Spark 只有微批、延迟必然秒级"——准确说法是**默认微批（秒级/百毫秒级），可选 Real-Time Mode（毫秒级）**。

### Source: The Trigger and the Execution Reuse

`RealTimeTrigger` 存在于触发器定义中，携带批次时长（默认由 `Duration(5, MINUTES)` 构造，用于控制进度提交的频率，而非处理延迟）：

```scala
case class RealTimeTrigger(batchDurationMs: Long) extends Trigger {
  require(batchDurationMs > 0, "the batch duration should not be negative")

  implicit val defaultFormats: DefaultFormats = DefaultFormats
}
```

一个关键的**反直觉事实**：4.3.0 源码里**没有独立的 `RealTimeExecution` 类**。`StreamExecution` 只有 `MicroBatchExecution` 与 `ContinuousExecution` 两个子类；Real-Time Mode 走的是 `AsyncProgressTrackingMicroBatchExecution extends MicroBatchExecution`——一个为异步进度跟踪与 `RealTimeTrigger` 定制的子类。差别在于 task 的生命周期——普通微批每批结束 task 就退出、下批重新调度；Real-Time Mode 的 input task 是长驻的，一批接着一批地持续读，进度日志（offset commit）由单线程后台线程池异步串行写。延迟差异来自调度开销的消除，而非"逐事件 vs 微批"的模型切换。

```scala
class AsyncProgressTrackingMicroBatchExecution(
    sparkSession: SparkSession,
    trigger: Trigger,
    triggerClock: Clock,
    extraOptions: Map[String, String],
    plan: WriteToStream)
  extends MicroBatchExecution(sparkSession, trigger, triggerClock, extraOptions, plan) {
```

`StreamExecution` 里对 `RealTimeTrigger` 有专门分派，把执行器指向这个子类。

### Source: Stateful Queries Run on Pipelined Shuffles

4.3.0 让 Real-Time Mode 支持有状态查询（聚合、`dropDuplicates`、`transformWithState`），靠的正是 [Shuffle](/docs/CS/Framework/Spark/Shuffle.md) 页讲的 pipelined shuffle。官方发布说明写得很直接：

> SPARK-58508 Support stateful queries in Real-Time Mode, including `dropDuplicates`, by running them on pipelined shuffles

普通 shuffle 会让长驻 task 死锁——有状态聚合需要 shuffle，而 shuffle 必须等 producer 把输出全部写完才能被 consumer 读，但 Real-Time 的 producer task 永不结束（它在等下一条输入）。解法就是 `PipelinedShuffleDependency`：consumer 边读 producer 正在产出的部分输出，两者作为 pipelined group 并发调度。SQL 层的注入点就是 `ShuffleExchangeExec` 的那个 `pipelined` 布尔位（见 [Shuffle](/docs/CS/Framework/Spark/Shuffle.md) 的源码片段）。

### Constraints and Positioning

Real-Time Mode 继承 pipelined shuffle 的全部约束（见 [Scheduler](/docs/CS/Framework/Spark/Scheduler.md)）：不支持推测执行、不支持动态资源分配、作业不能混用普通与 pipelined shuffle。这些限制解释了为什么它是一条"可选路线"而非默认——它用适用面换延迟。

延迟与语义的横向定位（4.3.0 官方文档）：

| 模式 | 端到端延迟 | 语义 | 能力覆盖 |
| ---- | ---- | ---- | ---- |
| Micro-batch（默认） | ~100ms | Exactly-once | 全部流操作，含所有有状态操作 |
| Real-Time Mode | 几毫秒 | Exactly-once（长驻 task 每批提交进度） | 4.3 起含有状态聚合、去重、`transformWithState` |

选型上，Real-Time Mode 把 Spark 在"准且延迟敏感"这一格的竞争力补上了——但它仍是"长驻 task + 微批进度提交"，与 [Flink](/docs/CS/Framework/Flink/Flink.md) 真正的逐事件流水线在故障恢复粒度上仍有差别。

## 时间语义与迟到数据

- 事件时间通过 `withWatermark(eventTimeCol, delayThreshold)` 声明；
- watermark 的语义与 [Flink](/docs/CS/Framework/Flink/Time.md) 一致：表示"不会再有比这个时间更晚的数据"，用于**界定状态何时可以清理**（而不是触发窗口计算那么直接）；
- 超时数据按输出模式处理：状态聚合会丢弃超出 watermark 的记录（可用 `dropDuplicatesWithinWatermark` 等带 watermark 的算子做去重）。

## 输出模式（Output Mode）

| 模式 | 语义 | 适用 |
| ---- | ---- | ---- |
| Append | 只输出**不会再变**的新行 | 纯追加的聚合/窗口、无 late update |
| Update | 只输出**本批发生变化**的行 | 有状态更新、下游支持 upsert |
| Complete | 每批输出**整张结果表** | 结果集可容纳在内存里（如全局 top-N） |

模式与 sink 能力必须匹配：Append 可以写普通 Parquet / Kafka；Update 需要能更新的 sink（Delta / Iceberg / Hudi / JDBC upsert / 幂等写入）。

## 状态与容错

- 状态（聚合中间结果、去重集合、join 缓冲）存在 **State Store** 里，随 checkpoint 持久化：
  - 默认 `HDFSStateStore`（基于分布式文件系统的版本化增量状态）；
  - `RocksDBStateStore`（Spark 3.2 引入，SPARK-34198）适合**超大状态**与高基数 key；
  - Spark 4.0 起提供 **State Store Data Source**，可以把状态当作表读出来做调试与观测。
- **Checkpoint 目录**记录：source 的 offset、算子状态、查询进度。重启时从 checkpoint 恢复，配合可重放的 source（Kafka）与幂等 sink，实现端到端 **exactly-once**；
- 与 [Flink](/docs/CS/Framework/Flink/Checkpoint.md) 的差别：Flink 用 barrier 做全局一致快照并支持两阶段提交事务 sink；Spark 通常走"重放 + 幂等/幂等 upsert"路线，吞吐高但端到端延迟受微批与 checkpoint 节奏影响。

自定义状态逻辑：早期用 `mapGroupsWithState` / `flatMapGroupsWithState`；Spark 4.0 引入新的 **Arbitrary State API v2（`transformWithState`）**，在 Scala / Java / Python 上提供更灵活、容错更好的有状态处理，并配套状态数据源便于调试。

## 与 Flink 的对照

| 维度 | Spark Structured Streaming | Flink |
| ---- | ---- | ---- |
| 执行模型 | 微批（Continuous 为实验性） | 逐事件流水式（批是有界流） |
| 时间推进 | watermark 主要用于状态清理 | watermark 驱动窗口触发与状态清理 |
| 延迟 | 通常秒级 | 可到亚秒级 |
| 吞吐 | 高（批式优化充分） | 高 |
| 一致性 | 重放 + 幂等 sink 为主 | checkpoint + 事务 sink（2PC） |
| 生态融合 | 与 Spark SQL / 数仓一体 | 与 CDC、湖存储（Paimon）结合紧密 |

判断标准很简单：**要"准"且延迟敏感**选 Flink；**已在 Spark 生态、作业以批与 SQL 为主、延迟容忍秒级**选 Structured Streaming。

## Links

- [SQL](/docs/CS/Framework/Spark/SQL.md)
- [RDD](/docs/CS/Framework/Spark/RDD.md)
- [Shuffle](/docs/CS/Framework/Spark/Shuffle.md)
- [Time](/docs/CS/Framework/Flink/Time.md)
- [Spark](/docs/CS/Framework/Spark/Spark.md)

## References

1. [Spark Docs - Structured Streaming Programming Guide](https://spark.apache.org/docs/latest/structured-streaming-programming-guide.html)
2. [Spark Release 3.2.0（RocksDB StateStore SPARK-34198、AQE 默认开启）](https://spark.apache.org/releases/spark-release-3-2-0.html)
3. [Spark Release 4.0.0（transformWithState、State Store Data Source）](https://spark.apache.org/releases/spark-release-4-0-0.html)
4. [Spark API Docs - StreamingContext（3.4.0 起弃用）](https://spark.apache.org/docs/4.0.0/api/java/org/apache/spark/streaming/StreamingContext.html)
5. [Spark Docs - Real-Time Mode @ 4.3.0（long-running tasks、延迟与能力矩阵）](https://spark.apache.org/docs/4.3.0/streaming/real-time-mode.html)
6. [Spark Release 4.3.0（SPARK-58508 有状态 Real-Time、SPARK-57281 移除 @Experimental）](https://spark.apache.org/releases/spark-release-4-3-0.html)
7. [AsyncProgressTrackingMicroBatchExecution.scala @ v4.3.0](https://github.com/apache/spark/blob/v4.3.0/sql/core/src/main/scala/org/apache/spark/sql/execution/streaming/runtime/AsyncProgressTrackingMicroBatchExecution.scala)
