## Introduction

SSTable 只增不减。随着写入与删除累积，同一行的多版本、墓碑和过期数据会散布在多个文件中，读请求必须合并这些文件才能得到逻辑结果。**Compaction** 在后台选择一组 SSTable，按 partition key 与 clustering key 有序归并，丢弃被覆盖的数据和可安全清除的墓碑，再写出更少、更规整的文件。

Compaction 不是单一算法，而是对 **read amplification、write amplification、space amplification** 三者的持续权衡：合并越激进，读越便宜、写与磁盘 IO 越贵；合并越保守，写入越省，但读要触碰更多 SSTable。

> 基线：Cassandra 5.0.9。标准 `cassandra.yaml` 的默认策略仍是 **STCS**；5.0 引入了 **Unified Compaction Strategy (UCS)**，但只有在显式选择 UCS，或采用 `cassandra_latest.yaml` 的实验性 profile 时才启用。

## Why Compaction

- 合并同一 cell 的多版本，只保留 LWW 胜出的值；
- 让墓碑覆盖旧数据，并在满足 GC 条件后清除二者；
- 减少点读需要打开的 SSTable 数量，降低读放大；
- 回收被覆盖、删除和过期数据占用的磁盘，降低空间放大；
- 控制 SSTable 数量与大小，避免元数据、内存和 streaming 开销持续膨胀。

代价是真实的二次 IO：输入 SSTable 要被读取，输出还要写盘并更新索引。Compaction 与前台读写共享磁盘、CPU 和网络，因此“compaction 越快越好”并不成立。

## Execution Model

一次后台 compaction 的骨架如下：

1. **选择输入**：策略根据大小、层级、时间窗口或 density/overlap 选出 SSTable；
2. **锁定生命周期**：`LifecycleTransaction.tryModify` 标记输入文件，避免同一文件被并发任务重复选择；
3. **有序归并**：`CompactionIterator` 合并多个 scanner，按时间戳解决冲突，处理 partition/row/range/cell tombstone；
4. **写出与建索引**：compaction-aware writer 生成新 SSTable，并构建相应的二级索引；
5. **提交与清理**：新文件加入 `SSTableSet` 后，旧文件才进入 obsolete 状态，最终删除；失败则回滚，不能提前删输入。

`CompactionManager` 统一持有执行器和限速器。`compaction_throughput` 控制 compaction 的 IO 速率，`concurrent_compactors` 控制并发任务数；二者不是同一个调节旋钮。

## Default Parameters

以下默认值均以 5.0.9 源码为准，并区分“策略自身默认值”和“latest profile 显式配置”。

| 策略 | 关键默认值 | 源码落点 |
| --- | --- | --- |
| STCS | `min_threshold=4`、`max_threshold=32`、`min_sstable_size=50MiB`、bucket `[0.5, 1.5]` | `schema/CompactionParams.java:79-99`、`SizeTieredCompactionStrategyOptions.java:26-44` |
| LCS | `sstable_size_in_mb=160`、`fanout_size=10` | `LeveledCompactionStrategy.java:52-101` |
| TWCS | `compaction_window_unit=DAYS`、`compaction_window_size=1`、`timestamp_resolution=MICROSECONDS` | `TimeWindowCompactionStrategyOptions.java:37-45` |
| UCS | `scaling_parameters=T4`、`target_sstable_size=1GiB`、`min_sstable_size=100MiB`、`base_shard_count=4`、`sstable_growth=0.333` | `CassandraRelevantProperties.java:608-615` |
| 节点级 | `compaction_throughput=64MiB/s`；compactor 数默认为 `min(8, max(2, min(CPU, 数据目录数)))` | `Config.java:335-337`、`DatabaseDescriptor.java:777-778` |

`cassandra_latest.yaml:1190-1197` 进一步把 UCS 的 `max_sstables_to_compact` 设为 **64**。这是该 profile 的显式配置，不应写成所有 UCS 部署的固定默认值。

## Size-Tiered Compaction Strategy

### Bucketing and Trigger

STCS 按 SSTable 大小分桶：以桶内平均大小为基准，`bucket_low=0.5`、`bucket_high=1.5` 决定可加入的大小区间；小于 `min_sstable_size` 的文件进入小文件桶。当某个桶至少有 **4** 个 SSTable 时触发 minor compaction，一次最多选择 **32** 个。

它不按 key 组织数据，只按文件大小组织，因此同一 key 的多个版本很容易散落在不同大小的桶中。

### Tradeoffs

- **写放大较低**：一个文件通常与少量相近文件合并；
- **读放大较高**：点读可能要查多个大小档；
- **空间回收不确定**：小文件长期凑不够阈值时，旧版本和墓碑可能滞留；
- **大文件风险**：最大的几个 SSTable 合并时，新旧文件需要同时占盘，容易放大临时空间需求。

适合写入密集、更新和删除较少、能够容忍较高读放大的负载。Major compaction 会把大量数据集中重写，通常不应作为常规清理手段。

## Leveled Compaction Strategy

### Level Invariant

LCS 维护 L0、L1、L2……层级：

- **L0 允许重叠**，flush 产生的 SSTable 首先进入 L0；
- **L1 及更高层保证同层不重叠**；
- 每层目标容量默认是上一层的 **10 倍**，单文件目标大小默认 **160 MiB**；
- L0→L1 时，需要合并所有与输入重叠的 L1 文件；结果超过层级容量后继续下沉。

因此 L1 及以上每个 key 至多落在一个 SSTable 中；L0 是例外，不能把“每层最多一个文件”无条件套到 L0。L0 文件过多时还有 STCS 兜底，官方文档给出的阈值是 **32**。

### Tradeoffs

- **读放大低**：适合点读和读密集表；
- **写放大高**：数据在层级间反复重写，L0→L1 还可能牵动大量 L1 文件；
- **临时空间较少**：相比 STCS 不需要长期堆积同样多的大文件；
- **级联阻塞**：不同层级间的 compaction 可能相互影响，不能假定所有任务完全并行；
- **墓碑下沉依赖**：低层 compaction 跟不上时，高层文件可能“饥饿”，墓碑也难以继续下沉。

`fanout_size` 越大，层级容量增长越快，但每次涉及的范围可能更大；`sstable_size_in_mb` 越小，单次任务越轻，文件数和元数据开销越高。

## Time-Window Compaction Strategy

### Window Lifecycle

TWCS 根据 SSTable 的最大写入时间把它放入时间桶：

1. **当前活跃窗口**：窗口内仍按 STCS 合并；
2. **窗口结束**：将该窗口的 SSTable 归并成少量文件；
3. **完全过期**：在定时检查且通过安全条件后，整文件丢弃，不必逐 cell 重写。

默认窗口是 **1 天**。官方建议让保留期内大约有 **20~30 个窗口**，例如 90 天 TTL 可考虑 3 天窗口，而不是机械地每天一个窗口。

### Failure Modes

TWCS 的整窗过期依赖时间局部性，以下写入会破坏这个前提：

- 用 `USING TIMESTAMP` 显式写入过去的时间；
- 新数据与旧数据在同一 memtable 中混合后 flush；
- read repair 把旧数据带入当前 memtable；
- 缩小已有窗口：旧 SSTable 不会自动拆到多个新窗口。

`unsafe_aggressive_sstable_expiration` 可以跳过过期文件与其他文件重叠关系的检查，可能造成数据丢失或已删除数据复活；它默认关闭，还需要对应 JVM property 才会生效。不能为了尽快回收空间而忽略这个风险。

## Unified Compaction Strategy

### Density and Sharding

UCS 不再只按物理文件大小或固定层级容量做决策，而是按 **density** 组织层级：

```tex
density = SSTable bytes / covered token range width
```

级数近似按 density 的对数增长。输出 SSTable 在 token range 的 shard 边界上切分，使不同 shard 的 compaction 可以独立并行；同层非重叠区域也能分别处理。

`target_sstable_size` 是目标而非硬上限，输出大小会随 density 与 shard 数变化。`base_shard_count` 控制低密度层级的初始切分；`min_sstable_size` 允许在数据量不足时减少 shard 数，避免生成大量过小文件。

### Scaling Parameters

`scaling_parameters` 的内部参数记为 `w`。解析规则如下：

| 配置 | 内部 `w` | fanout `f` | 触发阈值 `t` | 倾向 |
| --- | --- | --- | --- | --- |
| `N` | `0` | `2` | `2` | leveled 与 tiered 的对称中点 |
| `L<n>` | `2 - n` | `n` | `2` | leveled，偏读 |
| `T<n>` | `n - 2` | `n` | `n` | tiered，偏写 |
| 整数 `k` | `k` | `k < 0 ? 2-k : 2+k` | `k <= 0 ? 2 : 2+k` | 直接指定 `w` |

`L<n>` 与 `T<n>` 的 `n` 必须至少为 2。等价关系包括 `N = L2 = T2 = 0`；但 **`T4` 不等于整数 `4`**：前者是 `w=2, f=t=4`，后者是 `w=4, f=t=6`。

公式可直接对应 `UnifiedCompactionStrategy.java:106-147`：

```java
fanout = w < 0 ? 2 - w : 2 + w;
threshold = w <= 0 ? 2 : 2 + w;
```

`scaling_parameters` 可以是逗号分隔的逐层列表，例如 `T4,L10`；超出列表长度后，较高层级重复使用最后一个值。它允许底层偏写、高层偏读，而不是全表只能选一种性格。

### SSTable Growth

`sstable_growth` 的取值为 `0~1`，决定 density 增长如何分配到“文件变大”和“shard 变多”：

- `0`：SSTable 尽量维持目标大小，shard 数随 density 增长；
- `1`：几乎不增加 shard，数据增长集中到少量更大的 SSTable；
- 默认约 `1/3`：SSTable 大小约按 density 的 `1/3` 次方增长，是文件数与单文件大小之间的折中。

例如总数据 1 TiB、目标 1 GiB、`base_shard_count=1` 时，源码注释给出的近似结果是：growth `0` 产生约 1024 个 1 GiB 文件，`1/3` 产生约 128 个 8 GiB 文件，`1` 产生 1 个 1 TiB 文件。

### Differences from Legacy Strategies

- **T4 只是 STCS-like，不是完全等价**：STCS 按相近大小动态分桶；UCS 按预设 density band 和 overlap 决策，选择更稳定。
- **L10 只是 LCS-like，不是完全等价**：LCS 按固定文件大小切分，边界容易错位；UCS 用 shard 边界对齐 token range，减少部分重叠导致的重复合并。
- **可在线调参**：UCS 改变 scaling parameters 时按新目标渐进 compaction，不要求立即全量重写；传统策略之间切换通常需要 major compaction 整理存量。
- **按最高 overlap 选工作**：某一层级先处理对读放大贡献最大的重叠桶，而不是简单按文件数排队。
- **任务有上限设计**：积压时按最大 overlap 与 `max_sstables_to_compact` 选择输入，避免一次合并无限膨胀；即使设置上限，也会保留层级结构所需的输入。

## Tombstone and Expiration Safety

Compaction 不是“看到旧墓碑就删”。`CompactionIterator` 的 purge 逻辑同时考虑：

- 墓碑时间是否早于 `gcBefore`，即超过 `gc_grace_seconds`；
- 该 key 是否还存在于本次 compaction 输入之外、时间更早的 SSTable 中；
- 文件是否 repaired，以及 `only_purge_repaired_tombstones` 是否开启；
- 删除类型是 partition、row、range tombstone 还是 cell tombstone；
- 是否存在 Paxos 状态或 strict liveness 等特殊约束。

`getPurgeEvaluator` 会计算输入集合之外包含当前 key 的 SSTable 的最小时间戳；若旧数据仍可能被墓碑覆盖，就不能只凭本次合并结果删除墓碑。`only_purge_repaired_tombstones` 默认 **false**，开启后以 repair 进度约束清除，降低长期未 repair 导致数据复活的概率，但会牺牲空间回收速度。

通用墓碑触发参数为 `tombstone_threshold=0.2`、`tombstone_compaction_interval=86400s`。阈值用于提前触发单表清理，不代表可以绕过 GC 安全条件。

## Operational Impact

| 旋钮或指标 | 影响 | 调参方向 |
| --- | --- | --- |
| `compaction_throughput` | 所有 compaction 共享的 IO 预算 | 前台 IO 吃紧时降低；长期积压且磁盘有余量时提高 |
| `concurrent_compactors` | 同时运行的 compaction 任务数 | SSD 可增加，机械盘过多并发会恶化随机 IO |
| `nodetool compactionstats` | pending 任务、已完成字节、输入输出 | pending 持续增长说明产出速度低于数据产生速度 |
| `nodetool tablehistograms` | 点查延迟与 SSTable 命中分布 | 判断读放大是否已影响 p99 |
| `TombstoneScannedHistogram` | 查询仍需扫描的墓碑数量 | 高值提示墓碑堆积、repair 滞后或 GC 配置不合理 |
| `PendingCompactions` / 磁盘余量 | 调度压力与临时空间风险 | 同时观察，不能只看单一指标 |

5.0 的 `sstablepartitions` 可定位大分区。大分区会突破目标 SSTable 大小，使单次 compaction 的内存、耗时和失败代价显著上升；压缩、超大 collection 和不合理的 clustering key 都可能制造这种偏斜。

## Failure Signatures

| 现象 | 常见根因 | 优先动作 |
| --- | --- | --- |
| compaction pending 长期增长 | 吞吐过低、compactor 过少、写入过快、大分区 | 区分 IO 瓶颈与任务粒度，再调吞吐或并发 |
| 点读 p99 随运行时间上升 | STCS/UCS tiered 读放大、Bloom 误判、compaction 积压 | 检查每 key 的 SSTable overlap，考虑更偏 leveled 的参数 |
| 删除后旧数据复活 | 墓碑过早清除、repair 超过 grace、激进的 TWCS 过期 | 停止不安全清理，恢复副本并检查 `only_purge_repaired_tombstones` |
| TWCS 磁盘不回收 | 新旧时间混杂、窗口过大、过期检查频率过低 | 检查写入时间戳与 SSTable min/max timestamp |
| compaction 期间磁盘满 | 大文件同时保留新旧版本、空间放大失控 | 预留临时空间，避免大表 STCS major compaction |
| 写延迟周期性升高 | compaction 与前台争抢 IO | 降低吞吐或并发，观察磁盘队列而不是继续加资源 |

## vs HBase Compaction

HBase 的 major compaction 通常按 region 全量重写，代价集中；Cassandra 的后台 compaction 由表级策略持续触发，可以选择 STCS、LCS、TWCS 或 UCS。Cassandra 更灵活，也把选型和调参责任交给使用者：没有一种策略能同时最小化读写放大、空间放大和运维成本。

## Source Map

| 机制 | 5.0.9 源码落点 |
| --- | --- |
| 默认策略与阈值 | `schema/CompactionParams.java:79-105` |
| STCS 大小桶 | `db/compaction/SizeTieredCompactionStrategyOptions.java:26-44` |
| LCS 默认文件大小与 fanout | `db/compaction/LeveledCompactionStrategy.java:52-101` |
| TWCS 默认窗口 | `db/compaction/TimeWindowCompactionStrategyOptions.java:37-45` |
| UCS scaling 语法与公式 | `db/compaction/UnifiedCompactionStrategy.java:106-147` |
| UCS 默认值 | `config/CassandraRelevantProperties.java:608-615` |
| UCS density、shard 与 growth | `db/compaction/unified/Controller.java:85-108,248-285` |
| UCS 按 overlap 选任务 | `db/compaction/UnifiedCompactionStrategy.java:588-678` |
| UCS 积压时的输入选择 | `db/compaction/UnifiedCompactionStrategy.java:743-825` |
| compaction 合并与写出 | `db/compaction/CompactionTask.java:202-244` |
| 墓碑清除条件 | `db/compaction/CompactionIterator.java:341-405` |
| compaction 限速 | `db/compaction/CompactionManager.java:186-223` |
| latest profile 的 UCS 配置 | `conf/cassandra_latest.yaml:1183-1197` |

## Links

- [Cassandra](/docs/CS/DB/Cassandra/Cassandra.md)
- [Storage Engine](/docs/CS/DB/Cassandra/StorageEngine.md)
- [Distributed](/docs/CS/DB/Cassandra/Distributed.md)
- [Operations](/docs/CS/DB/Cassandra/Operations.md)

## References

- [Cassandra 5.0 Compaction](https://cassandra.apache.org/doc/5.0/cassandra/managing/operating/compaction/index.html)
- [Unified Compaction Strategy](https://cassandra.apache.org/doc/5.0/cassandra/managing/operating/compaction/ucs.html)
- [CEP-26 Unified Compaction Strategy](https://cwiki.apache.org/confluence/display/CASSANDRA/CEP-26%3A+Unified+Compaction+Strategy)
- [UnifiedCompactionStrategy.java 5.0.9](https://github.com/apache/cassandra/blob/cassandra-5.0.9/src/java/org/apache/cassandra/db/compaction/UnifiedCompactionStrategy.java)
