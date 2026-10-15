## Introduction

SSTable 只增不减，随着写入与删除累积，同一行的多版本、墓碑、过期数据会散布在大量文件中。**Compaction（压缩/合并）** 把这些 SSTable 读进来、合并去重、清掉过期墓碑，再写出新的更少文件。它是 Cassandra 读放大、写放大、空间放大与节点负载的**最大调节杠杆**。

> 基线：Cassandra 5.0。5.0 新增 **Unified Compaction Strategy (UCS, CEP-26)**，统一了 STCS/LCS/TWCS 的调参模型。

## Why Compaction

- 合并同 key 的多版本，只保留 LWW 最新值；
- 清除超过 `gc_grace_seconds` 的墓碑与过期 TTL；
- 减少「一个读要查的 SSTable 数量」（降低读放大）；
- 回收被删除/覆盖数据占用的磁盘（降低空间放大）。

代价：compaction 本身消耗 CPU/IO/磁盘带宽，且会产生「写放大」（数据被反复读改写）。

## Strategies

### Size-Tiered Compaction Strategy (STCS, 默认)

- 把**大小相近**的 SSTable 合并成更大的一个。写放大最低，适合**写密集、少删除、少更新**的工作负载（如时序原始写入）。
- 缺点：读放大随时间增长（同 key 可能分散在多个大小档的文件），空间放大高（需约 50% 空闲空间容纳合并中间态）。

### Leveled Compaction Strategy (LCS)

- 分层（L0~Lk）：L0 小文件，每层容量是上一层的 10 倍，层内**无重叠**。读放大最低（一个 key 至多落在每层一个文件），适合**读密集、更新频繁**的表。
- 代价：写放大最高（数据在层间反复下沉），磁盘 IO 与 compaction 压力更大。

### Time-Window Compaction Strategy (TWCS)

- 按**时间窗口**（如按天）把 SSTable 分组，窗口内用 STCS，窗口间互不合并。专为 **TTL / 时序** 设计：过期窗口整窗直接丢弃，几乎零 compaction 成本。
- 是时间序列表（指标、日志、事件）的事实标准。**DTCS（DateTiered）已被 TWCS 取代并弃用。**

### Unified Compaction Strategy (UCS, 5.0)

- CEP-26 提出的统一框架，用一组**缩放参数（scaling parameters）**同时表达 STCS/LCS/TWCS 的行为，可按工作负载在一个策略内调出接近三者的效果，并改善它们在「大分区」「空间放大」上的短板。新集群与时序场景的可选默认演进方向。

### 选择指南

| 负载特征 | 推荐 |
| --- | --- |
| 写多、少更新删除 | STCS |
| 读多、更新频繁 | LCS |
| TTL / 时序（按时间过期） | TWCS（或 UCS） |
| 想统一调参、新集群 | UCS（5.0+） |

## Operational Impact

- **Compaction 吞吐**：`compaction_throughput_mb_per_sec`（默认 16，调大可加快但抢业务 IO）。
- **并发**：`concurrent_compactors`（默认 min(磁盘数, 核心数)）。
- **积压**：`nodetool compactionstats` 看 pending 任务；长期积压 = 读延迟升高的前兆。
- **大分区告警**：超大分区会让单个 compaction 任务极重甚至 OOM，5.0 提供 `sstablepartitions` 工具定位大分区。

## vs HBase Compaction

HBase 的 major compaction 是「整 region 全量重写」，代价集中、可控性差；Cassandra 的策略更细粒度、可按表（甚至按 workload）选择，但也要求使用者**按表显式选策略**——这是「灵活但要懂」的典型体现。

## Source-Level Classes

- **抽象与策略**：`db.compaction.AbstractCompactionStrategy` 基类，`SizeTieredCompactionStrategy` / `LeveledCompactionStrategy` / `TimeWindowCompactionStrategy` / `UnifiedCompactionStrategy`（CEP-26）四种实现；`CompactionStrategyFactory` 按表配置实例化。`AbstractCompactionTask` / `CompactionTask` 执行单次合并。
- **触发与调度**：`db.compaction.CompactionManager` 管理 `concurrent_compactors` 个并发任务与 `compaction_throughput_mb_per_sec` 限速；`ColumnFamilyStore.getCompactionStrategy` 在 flush / 阈值到达时提交任务。`nodetool compactionstats` / `tblestats` 看 pending。
- **UCS 缩放语法（CEP-26）**：`scaling_parameters` 用 `T<n>`（tiered，偏写，n≈合并触发的小文件数）、`L<n>`（leveled，偏读，n≈层容量倍数）、`N`（中性，fanout 2）表达从 STCS→LCS 的连续谱；`target_sstable_size`（默认 1 GiB）、`base_shard_count`（默认 4，最小并发度）、`sstable_growth`（0~1，控制密度增长分给「shard 数」还是「单 sstable 大小」）。UCS 按 token range **分片**，不同 shard 的 compaction 可并行，不像 LCS 会相互阻塞。旧格式切到 UCS 容易（如 `T4`≈默认 STCS），但 **UCS→旧策略需大量重压缩**，且 legacy LCS/STCS 至少保留一个大版本。
- **墓碑清除**：compaction 在 `gc_grace_seconds` 后才物理删墓碑；`only_purge_repaired_tombstone`（默认 false）可在 repair 后才清，避免未 repair 时复活。

## Links

- [Cassandra](/docs/CS/DB/Cassandra.md)
- [Storage Engine](/docs/CS/DB/Cassandra/StorageEngine.md)
- [Operations](/docs/CS/DB/Cassandra/Operations.md)
- [Distributed](/docs/CS/DB/Cassandra/Distributed.md)

## References

- [Cassandra Compaction (官方文档)](https://cassandra.apache.org/doc/latest/cassandra/operations/compaction.html)
- [CEP-26 Unified Compaction Strategy](https://cassandra.apache.org/doc/latest/cassandra/architecture/compaction.html)
