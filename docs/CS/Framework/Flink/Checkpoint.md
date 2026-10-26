## Introduction

Checkpoint（检查点）是 Flink 容错的基石：**周期性地对整条流做一次全局一致快照**，把每个算子的 [State](/docs/CS/Framework/Flink/State.md) 与 Source 的读取位置一起持久化到远端存储。作业失败后，从最近一次成功的 checkpoint 恢复状态、从对应位置重放数据，从而做到"像没发生过一样"。

它与 [JobManager](/docs/CS/Framework/Flink/JobManager.md) 的 CheckpointCoordinator 协同工作：协调器在 Source 注入 barrier、收集各 Task 的 ack、全部成功后标记该 checkpoint 为 complete。

## 快照怎么做的：Barrier 对齐

Flink 用的是 Chandy-Lamport 分布式快照算法的变体，靠插入数据流的特殊记录 **checkpoint barrier** 来划分"属于本次快照"与"属于下次快照"的数据：

1. **注入**：CheckpointCoordinator 要求各 Source 在各自的 offset 处插入带编号的 barrier，并把自己的 offset 记入快照；
2. **广播与传递**：barrier 随数据往下流，每个算子收到 barrier 时对自己的状态做快照，然后向下游转发；
3. **对齐（alignment）**：多输入算子（如 `join`、`union`）必须等**所有**输入通道的 barrier 都到齐才做快照。先到的通道被**阻塞**，其后续数据缓存在缓冲区，避免污染本次快照；
4. **确认**：所有算子快照完成（异步上传到远端存储）后向协调器 ack，协调器收到全部 ack 才认为该 checkpoint 成功。

对齐保证了"快照里不含跨边界的脏数据"，代价是：

> 对齐期间被阻塞的通道不处理数据，**反压严重时对齐时间可能长到 checkpoint 超时**。

## 对齐 vs 非对齐

| 维度 | Aligned（对齐，默认） | Unaligned（非对齐） |
| ---- | ---- | ---- |
| 做法 | 等所有输入 barrier 到齐，阻塞快通道 | 首个 barrier 到达即"超越"排队数据并立即向下转发，被超越的在途数据一并写进快照 |
| 快照体积 | 只含算子状态 | 额外含在途数据（in-flight），**快照更大** |
| 适用场景 | 常态、无严重反压 | 存在慢通道、对齐超时（日志里出现 alignment timeout） |
| 恢复 | 直接装载状态 | 先恢复在途数据再处理上游数据 |
| 开启方式 | 默认 | `execution.checkpointing.unaligned.enabled=true`（Flink 1.11 起提供，也支持按对齐超时自动切换） |

配套的两个优化：

- **Buffer Debloating**（Flink 1.14 起）：根据当前吞吐动态调节网络缓冲区大小，减少对齐阶段需排队的数据量，降低对齐耗时；
- **Changelog / 日志化增量检查点**（Flink 1.15 起）：状态变更持续写入 changelog（DSTL）并立即持久化，算子在 log 落盘后即可 ack，快照文件在后台周期性物化。它把"checkpoint 时长"与"状态大小"解耦，让 checkpoint 时长更稳定。

```java
env.enableCheckpointing(30_000);                                  // 30s 一次
env.getCheckpointConfig().setCheckpointingMode(CheckpointingMode.EXACTLY_ONCE);
env.getCheckpointConfig().setMinPauseBetweenCheckpoints(10_000);  // 两次之间至少间隔 10s
env.getCheckpointConfig().setCheckpointTimeout(120_000);
env.getCheckpointConfig().setExternalizedCheckpointCleanup(
        ExternalizedCheckpointCleanup.RETAIN_ON_CANCELLATION);    // 取消作业后保留快照
env.getCheckpointConfig().enableUnalignedCheckpoints();           // 反压严重时可开
```

## 三种一致性语义

| 语义 | 含义 | 代价 |
| ---- | ---- | ---- |
| At-most-once | 失败即丢，不重放 | 最快，不保证正确性 |
| At-least-once | 重放保证不丢，可能重复 | 无需 barrier 对齐，开销低 |
| Exactly-once | 不丢不重，结果如同只处理过一次 | 需要对齐开销 + sink 侧配合 |

**Flink 内部的 exactly-once 不等于端到端 exactly-once**。内部状态靠 checkpoint 保证；而"输出到外部系统"还需要两件事之一：

1. **幂等写入**：sink 侧按主键覆盖（Redis、HBase、带主键的 Upsert Kafka / 湖表），重复写无害；
2. **两阶段提交（2PC）**：`TwoPhaseCommitSinkFunction` 在预提交阶段把数据写进外部事务（如 Kafka 事务），只有当 JobManager 确认全局 checkpoint 完成后才正式提交；失败则回滚。代价是输出的可见性被推迟到 checkpoint 完成，因此**checkpoint 间隔直接决定端到端延迟**。

## Savepoint vs Checkpoint

| 维度 | Checkpoint | Savepoint |
| ---- | ---- | ---- |
| 触发 | Flink 自动、周期性 | 用户手动触发（CLI / REST / 停止作业时） |
| 目的 | 故障自动恢复 | 计划性运维：版本升级、改并行度、迁移集群、A/B 双跑 |
| 格式 | 高度优化、可能依赖具体实现 | 更规范（canonical），跨版本兼容性更好 |
| 生命周期 | 默认由 Flink 管理（作业取消时可配置保留或清理） | 完全由用户管理 |
| 是否对齐 | 可非对齐 | **始终对齐** |

使用 savepoint 的两个硬约束：

- 算子必须**显式设置 uid**（`uid("my-source")`），否则作业拓扑改变后 Flink 无法把状态映射回算子；
- 拓扑变化过大时用 `--allow-non-restored-state` 允许丢弃无法匹配的状态，但要清楚这意味着那部分状态从零开始。

1.x → 2.x 的升级不能依赖 savepoint 直接恢复（状态不兼容），这是 [State](/docs/CS/Framework/Flink/State.md) 里已经标注的风险。

## 恢复流程

```
作业失败 / 手动从快照启动
  → JobMaster 选择最近一次 completed checkpoint
  → 按并行度把 key-group 重新分配到 TaskManager 的 Slot
  → 各 Task 从远端存储装载本地状态（RocksDB 后端需先重建本地实例）
  → Source 从快照记录的 offset（operator state）开始重放
  → 非对齐快照还需先重放在途数据
  → 作业进入 RUNNING
```

恢复时间 ≈ 状态下载/重建时间 + 重放时间。大状态作业的优化方向：增量 checkpoint（RocksDB）、分离式状态后端（2.x，无需搬运本地状态）、合理设置 checkpoint 间隔以控制重放量。

## 调优要点

- **间隔**：太短则快照开销大，太长则恢复时重放多；事务 sink 场景下间隔 = 端到端延迟下限；
- **超时**：反压下容易超时，先看对齐时间再决定是否开非对齐；
- **并发 checkpoint**：允许多个同时进行可提升恢复点密度，但增加运行时开销；
- **Checkpoint 存储**：与状态后端分离（1.15 起两个概念解耦），生产一般用 HDFS / S3 等分布式存储，而非 JobManager 内存；
- **Web UI 指标**：关注 `Checkpoint Duration`（同步 + 异步阶段）、`Alignment Duration`、`Persisted Data Size`，三者分别对应对齐、上传、状态规模问题。

## Links

- [State](/docs/CS/Framework/Flink/State.md)
- [JobManager](/docs/CS/Framework/Flink/JobManager.md)
- [Connector](/docs/CS/Framework/Flink/Connector.md)
- [Time](/docs/CS/Framework/Flink/Time.md)
- [Flink](/docs/CS/Framework/Flink/Flink.md)

## References

1. [Flink Docs - Checkpoints](https://nightlies.apache.org/flink/flink-docs-stable/docs/dev/datastream/fault-tolerance/checkpointing/)
2. [Flink Docs - Checkpointing under Backpressure（非对齐检查点与 buffer debloating）](https://nightlies.apache.org/flink/flink-docs-stable/docs/ops/state/checkpoints_vs_savepoints/)
3. [Flink Blog - Improving speed and stability of checkpointing with generic log-based incremental checkpoints](https://flink.apache.org/2022/05/30/improving-speed-and-stability-of-checkpointing-with-generic-log-based-incremental-checkpoints)
4. [Flink Blog - Getting into Low-Latency Gears with Apache Flink, Part Two](https://flink.apache.org/2022/05/23/latency-part2.html)
