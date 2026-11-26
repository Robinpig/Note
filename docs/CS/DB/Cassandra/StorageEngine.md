## Introduction

Cassandra 的存储引擎属于 **LSM-tree 谱系**（与 LevelDB / RocksDB / HBase 同源），核心权衡是用**顺序写 + 后台合并**换随机写的性能。理解写路径、SSTable 格式与读路径，是调优与排障的基础。

> 基线：Cassandra 5.0.9。5.0 引入 **Trie Memtable / BTI SSTable**（CEP-19/25），但标准 `cassandra.yaml` 默认仍是 **SkipList + BIG**；Trie 由 memtable profile/表配置选择，BTI 由全局 `sstable.selected_format` 选择。

## Write Path

一次写（INSERT/UPDATE/DELETE）在单节点上的流程：

1. **构造 Mutation**：CQL 层把语句编译为 `Mutation`，其中包含一个或多个 `PartitionUpdate`；普通单分区写只触及一个分区。
2. **CommitLog（WAL）**：durable write 在 replica 端先追加 CommitLog。`CassandraKeyspaceWriteHandler.beginWrite`（`:42`）在 `makeDurable=true` 时调用 `addToCommitLog`，随后才返回写上下文。
3. **Memtable**：`ColumnFamilyStore.apply`（`:1467`）按 operation order / CommitLog position 选择 memtable，再调用 `Memtable.put`；因此重启重放与正常写入能落在正确的 memtable 代次。
4. **Flush**：memtable 达到清理阈值或内存压力时，写入屏障先等待屏障之前的写完成，再切换 memtable、flush 旧 memtable 成不可变 SSTable。
5. **CommitLog 回收**：只有 flush 成功且得到连续的 CommitLog upper bound，`PostFlush` 才调用 `discardCompletedSegments`；flush 失败时保留日志，避免数据只剩内存却丢失恢复依据。
6. **Compaction**：SSTable 只增不减，后台 compaction 合并（见 [Compaction](/docs/CS/DB/Cassandra/Compaction.md)）。

### CommitLog Sync and Acknowledgment

`commitlog_sync` 决定「写何时可以对客户端确认」，而不只是「日志多久刷一次」：

| 模式 | 5.0.9 行为 | crash 风险 |
| --- | --- | --- |
| `periodic`（默认） | 写可立即确认；后台每 `commitlog_sync_period`（默认 10s）fsync；滞后超过阈值时写线程阻塞等待 | 确认后、fsync 前宕机可能丢最近写入 |
| `batch` | 每个写等待 CommitLog flush 完成 | 延迟与 fsync 次数最高 |
| `group` | 多个写共享一次 flush，在 `commitlog_sync_group_window` 内聚合后确认 | 以有限等待换批量持久化 |

`periodic` 的背压不是每次写都等待：`PeriodicCommitLogService.maybeWaitForSync`（`:36`）只在 `lastSyncedAt` 落后于 `now - blockWhenSyncLagsNanos` 时等待；未配置 `periodic_commitlog_sync_lag_block` 时，阈值默认为 sync period 的 **1.5 倍**（`DatabaseDescriptor.java:3423`）。

```java
long expectedSyncTime = nanoTime() - blockWhenSyncLagsNanos;
if (lastSyncedAt < expectedSyncTime)
{
    pending.incrementAndGet();
    awaitSyncAt(expectedSyncTime, commitLog.metrics.waitingOnCommit.time());
    pending.decrementAndGet();
}
```

因此「CommitLog 保证宕机不丢已确认写入」只在 `batch` / `group` 或已实际 fsync 的 `periodic` 窗口内成立；`durable_writes=false` 还会绕过正常 CommitLog 要求。生产评估 RPO 时必须把 sync 模式、磁盘缓存与掉电语义一起算进去。

## Flush Boundary

flush 的正确性依赖一个不可拆分的边界：

- `Keyspace.writeOrder.newBarrier()` 建立写顺序屏障；
- 新写进入新 memtable，屏障之前的写进入被切出的旧 memtable；
- `writeBarrier.issue()` 放行旧 memtable 的 flush，同时确保旧 memtable 不再接收新写；
- 每张被切出的 memtable 记录 CommitLog lower/upper bound，多张表共享的 CommitLog 只有连续区间全部 flush 成功才能回收。

这也是「某个表 flush 成功」不等于「整个 CommitLog segment 可以删除」的原因：一个 segment 可能混有其他表尚未 flush 的记录。

## SSTable File Components

一个 BIG SSTable 由多个文件组成：

| 文件 | 作用 |
| --- | --- |
| `Data.db` | 实际行数据（按 partition 分块） |
| `Index.db` | Data.db 内 partition 偏移索引 |
| `Summary.db` | Index.db 的稀疏采样，加速定位 |
| `Filter.db` | **Bloom Filter**，判断某 partition 是否「可能在」本 SSTable |
| `CompressionInfo.db` | 压缩块信息（偏移/长度/压缩算法） |
| `Statistics.db` | 统计（min/max token、timestamp、TTL 等），用于读剪枝 |
| `Digest.crc` / `CRC.db` | 校验和，防静默损坏 |

**Bloom Filter** 是读路径的关键：先用它排除肯定不含目标 partition 的 SSTable，只对「可能命中」的文件做进一步查找，把随机读从「扫所有 SSTable」降到「扫少数几个」。Bloom 只会误判「可能存在」，不会把真正存在的 partition 误判为不存在。

## BIG and BTI

| 维度 | BIG（标准默认） | BTI（5.0 opt-in） |
| --- | --- | --- |
| 索引组织 | partition index + summary + row index | trie 结构定位 partition / row |
| Key cache | 使用 | **不使用**，`BtiFormat` 明确关闭 key cache |
| 点查找 | Bloom → key cache / index → data | key bounds → Bloom → trie lookup → data |
| 大分区 | row index 与缓存压力更明显 | trie 前缀定位更适合大分区 |
| 兼容性 | 旧版本可读 | 旧版本不能读，升级前必须评估回滚边界 |

BTI 的实际包是 `io.sstable.format.bti`，不是旧笔记中的 `io.sstable.format.trie`。`cassandra_latest.yaml:1165` 设置 `selected_format: bti`；标准配置没有该覆盖，`Config.java:373` 的默认格式为 `big`。BTI 不是「BIG 上加一个前缀压缩开关」，而是不同的 SSTable 读写实现。

## Read Path

replica 本地的一次分区读大致分为五步：

1. **缓存**：先查 row cache；启用时返回缓存行。BIG 还可使用 key cache 直接定位 partition 偏移。
2. **候选剪枝**：按 token range、统计信息与 Bloom filter 排除无关 SSTable；memtable 始终是候选来源。
3. **本地合并**：读取 memtable 与候选 SSTable，对同一 cell 按 timestamp 做 LWW；删除标记、TTL 与复杂 cell 也参与合并。
4. **Tombstone purge**：`ReadCommand`（`:865`）在合并后按 `gcBefore`、最老未修复墓碑时间与 `only_purge_repaired_tombstones` 决定哪些墓碑可对查询隐藏。
5. **过滤与限额**：执行 row filter、limit，返回 `ReadResponse`；coordinator 再按 CL 做跨副本 digest 比对、LWW 与 read repair（见 [Consistency](/docs/CS/DB/Cassandra/Consistency.md)）。

读延迟通常来自「候选 SSTable 数量 × 每个文件读取的 data block」，而不是单纯由 Bloom filter 决定。墓碑很多时，即使 Bloom 命中很少，也可能为证明「没有更新值」扫描大量旧版本。

## Caches

- **Key Cache**：缓存 partition key → SSTable 偏移，标准 BIG 默认开启，对读放大友好；BTI 不使用。
- **Row Cache**：缓存整行，仅适合极热点且行更新少的场景；误用会吃内存并放大 GC，且必须关注缓存与源数据一致性。
- **Counter Cache**：计数器类型专用。
- 4.0+ 支持 off-heap 缓存，减少 JVM 堆压力；缓存不是持久层，重启后需要重新 warming。

## Tombstones and GC Grace

删除不是原地擦除，而是写一条带 `deletion_time` 的墓碑。墓碑通常要存活过 `gc_grace_seconds`（默认 864000s=10d）才允许被 compaction 清除，目的是让 repair / hint 有机会把删除传播到所有 replica。

需要避免两个误解：

- **不是「10 天后自动复活」**：超过 grace 只意味着清除保护窗口结束；是否清除还受 repaired 状态与 compaction 策略影响。
- **不是「只要不 repair 就一定复活」**：真正的风险是部分副本已清除墓碑，另一副本仍保留数据，后续 repair 又把旧数据当成分歧传播。`only_purge_repaired_tombstones=true` 可要求先 repair 再清除未修复墓碑。

TTL 过期最终也表示为带过期时间的墓碑，因此 TTL 表同样需要 repair 与合理 compaction，不能把 TTL 当作物理空间立即回收。

## Trie Memtable (5.0)

标准 YAML 的 `memtable.configurations.default.inherits` 是 `skiplist`；`cassandra_latest.yaml:800` 才改为 `trie`。可按表通过 `memtable` 属性选择配置。

| 维度 | SkipListMemtable | TrieMemtable |
| --- | --- | --- |
| 组织 | 每分区并发跳表，分区内嵌套对象 | trie + 可 off-heap 的紧凑 buffer |
| GC | 长生命周期小对象较多 | 对象分配更少，GC 压力更低 |
| 查找 | 跳表定位 | trie 前缀定位 |
| 风险 | 大分区与 GC 压力 | sharded single-writer 在极度倾斜负载、热点分区或 legacy secondary index 下可能更差 |

Trie 的收益不是无条件放大：官方 YAML 明确提示，负载集中在少数 partition 时可能反而更慢。选择时应看分区大小分布、写入倾斜与索引类型，而不是只看「5.0 新特性」。

## Source-Level Classes

| 层 | 5.0.9 类与职责 |
| --- | --- |
| CommitLog | `db.commitlog.CommitLog` / `CommitLogSegment` / `PeriodicCommitLogService`：追加、fsync 调度、segment 回收 |
| Memtable API | `db.Memtable` 抽象；`db.memtable.SkipListMemtable`（标准默认）、`TrieMemtable`（opt-in）、`ArrayBackedMemtable`（测试） |
| 分区原子性 | `db.partitions.AtomicBTreePartition`：单分区内 `addAll` 等修改的线程安全与原子可见；不是分布式 ACID |
| 表存储 | `db.ColumnFamilyStore`：memtable 列表、SSTableReader 集合、缓存、flush 与 compaction 调度 |
| flush | `ColumnFamilyStore.Flush` / `PostFlush`：写屏障、memtable 切换、CommitLog upper bound 与失败保留 |
| SSTable | `io.sstable.format.big.BigTableReader/Writer`；`io.sstable.format.bti.BtiTableReader/Writer` |
| Bloom / cache | `utils.BloomFilter` / `FilterFactory`；`cache.KeyCache` / `RowCache` / `CounterCache` |
| 读 | `db.ReadCommand`：本地执行、合并后 tombstone purge、row filter 与 limit |

## Failure Signatures

| 现象 | 优先排查 |
| --- | --- |
| 写 p99 高、`WaitingOnCommit` 上升 | periodic sync 滞后、磁盘 fsync 慢、sync period / lag block 配置 |
| flush 后 CommitLog 不下降 | 共享 segment 中仍有其他表未 flush，或 flush 失败 |
| 点读扫描多个 SSTable | compaction 积压、Bloom 误判、时间/token 范围未剪枝 |
| `TombstoneScannedHistogram` 高 | 墓碑过多、repair 滞后、`gc_grace_seconds` 与 compaction 不匹配 |
| 启用 Trie 后热点更慢 | 分区写入倾斜、legacy secondary index、shard 竞争 |

## vs HBase / RocksDB

| 维度 | Cassandra | HBase | RocksDB |
| --- | --- | --- | --- |
| 写入 | CommitLog + MemTable + SSTable | WAL + MemStore + HFile | WAL + MemTable + SSTable |
| 合并 | 多种 compaction 策略 | major/minor compaction | Leveled compaction |
| 读合并 | LWW + Bloom | LWW + Bloom | LWW + Bloom |
| 部署 | 自带，无外部依赖 | 依赖 HDFS + ZK | 嵌入式库 |
| 多 DC | 内建 | 外部 | 无 |

## Links

- [Cassandra](/docs/CS/DB/Cassandra/Cassandra.md)
- [Data Model](/docs/CS/DB/Cassandra/DataModel.md)
- [Distributed](/docs/CS/DB/Cassandra/Distributed.md)
- [Operations](/docs/CS/DB/Cassandra/Operations.md)

## References

- [Cassandra Storage Engine](https://cassandra.apache.org/doc/5.0/cassandra/architecture/storage-engine.html)
- [PeriodicCommitLogService 5.0.9](https://github.com/apache/cassandra/blob/cassandra-5.0.9/src/java/org/apache/cassandra/db/commitlog/PeriodicCommitLogService.java)
- [cassandra_latest.yaml 5.0.9](https://github.com/apache/cassandra/blob/cassandra-5.0.9/conf/cassandra_latest.yaml)
