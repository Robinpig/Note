## Introduction

Cassandra 的存储引擎属于 **LSM-tree 谱系**（与 LevelDB / RocksDB / HBase 同源），核心权衡是用**顺序写 + 后台合并**换随机写的性能。理解写路径、SSTable 格式与读路径，是调优与排障的基础。

> 基线：Cassandra 5.0。5.0 引入 **Trie Memtable / Trie SSTable**（CEP-19/25），与经典结构并存；下文先讲经典路径。

## Write Path

一次写（INSERT/UPDATE/DELETE）在单节点上的流程：

1. **CommitLog（WAL）**：先顺序追加到 CommitLog（可分组/group 刷盘），保证宕机后可重放已确认写入。4.0+ 支持 `commitlog_compression` 与 `periodic` / `group` / `batch` 模式在持久性与延迟间权衡。
2. **Memtable**：写入内存中的有序结构（按 partition key + clustering 排序）。
3. **Flush**：Memtable 达到 `memtable_flush_writers` / 大小阈值或内存压力时，刷成不可变的 **SSTable**，并回收对应 CommitLog 段（`commitlog_total_space` 与 replay 位置联动）。
4. **Compaction**：SSTable 只增不减，后台 compaction 合并（见 [Compaction](/docs/CS/DB/Cassandra/Compaction.md)）。

## SSTable File Components

一个 SSTable 由多个文件组成（5.0 前经典布局）：

| 文件 | 作用 |
| --- | --- |
| `Data.db` | 实际行数据（按 partition 分块） |
| `Index.db` | Data.db 内 partition 偏移索引 |
| `Summary.db` | Index.db 的稀疏采样，加速定位 |
| `Filter.db` | **Bloom Filter**，判断某 partition 是否「可能在」本 SSTable |
| `CompressionInfo.db` | 压缩块信息（偏移/长度/压缩算法） |
| `Statistics.db` | 统计（min/max token、timestamp、TTL 等），用于读剪枝 |
| `Digest.crc` / `CRC.db` | 校验和，防静默损坏 |

**Bloom Filter** 是读路径的关键：先用它排除肯定不含目标 partition 的 SSTable，只对「可能命中」的文件做进一步查找，把随机读从「扫所有 SSTable」降到「扫少数几个」。

## Read Path

1. coordinator 把读发到 replica（按 CL），replica 本地做：
2. 查 **row cache**（若命中直接返回，仅适合读多写少且行稳定）；
3. 否则合并 **Memtable + 所有候选 SSTable**：对同一个 cell，按 **timestamp 最后写入胜出（LWW）** 合并；用 Bloom Filter / Key Cache 跳过无关 SSTable。
4. 处理 **tombstone**（删除标记）：墓碑在 `gc_grace_seconds`（默认 10 天）内参与合并，过期后才被 compaction 真正物理清除——这也是「删除也占空间、且必须按时 repair」的根源（见 [Distributed](/docs/CS/DB/Cassandra/Distributed.md)）。
5. 返回给 coordinator，coordinator 再做跨 replica 的 LWW 合并与 read-repair。

## Caches

- **Key Cache**：缓存 partition key → SSTable 偏移，默认开启，对读放大友好。
- **Row Cache**：缓存整行，仅适合极热点且行更新少的场景；误用会吃内存并放大 GC。
- **Counter Cache**：计数器类型专用。
- 4.0+ 支持 off-heap 缓存，减少 JVM 堆压力。

## Tombstones and GC Grace

删除不是原地擦除，而是写一条带 `deletion_time` 的墓碑。墓碑必须存活过 `gc_grace_seconds`（默认 864000s=10d）才能被 compaction 清除，目的是让所有 replica 都能看到删除（否则 repair 会把「已删数据」从没收到删除的 replica 复活）。**后果**：若超过 gc_grace 没跑 repair，删除的数据会被「复活」（zombie）。TTL 数据同理走墓碑。

## Trie Memtable / SSTable (5.0)

5.0 引入基于 **trie（前缀树）** 的 Memtable 与 SSTable（`memtable_allocator: trie`、`cassandra.yaml` 可切）。优势：更紧凑的内存表示、更少的对象分配（降低 GC）、SSTable 层也能做前缀压缩。对写密集与大分区场景收益明显。

## Source-Level Classes

核心存储类（5.0，`org.apache.cassandra` 包）：

- **CommitLog**：`db.commitlog.CommitLog` / `CommitLogSegmentManager` / `CommitLogSegment`；支持 `periodic` / `group` / `batch` 三种 sync 模式与 `commitlog_compression`。4.0 的 `GroupCommitLogService` 把多个写合并成一次 fsync，降低高并发下的 fsync 次数。
- **Memtable（pluggable，CEP-11）**：`db.Memtable` 抽象基类，具体实现经 memtable API 选择——`db.memtable.SkipListMemtable`（经典默认，分区为并发跳表）、`db.memtable.TrieMemtable`（CEP-19，5.0 推荐）、`db.memtable.ArrayBackedMemtable`（测试）。`memtable: {configurations: {...}, default: trie}` 在 yaml 切换，`ALTER TABLE ... WITH memtable = 'trie'` 按表覆盖。
- **分区 / 行表示**：`db.partitions.AtomicBTreePartition`（分区内修改以 BTree 保证原子可见）、`db.rows.{Row, BTreeRow, Cell, ComplexCell}`（行/单元格内存表示）、`db.partitions.PartitionUpdate`（单分区变更）。
- **ColumnFamilyStore**：`db.ColumnFamilyStore` 是「每张表」的存储容器，掌管该表的 memtable 列表、`SSTableReader` 集合、缓存与 compaction 调度。写路径 `Keyspace.apply → ColumnFamilyStore.apply → Memtable.put`；flush 由 `ColumnFamilyStore.switchMemtable` / `Memtable.flush` 触发，产出 `SSTableWriter`。
- **SSTable 格式（两套并存，CEP-17 API）**：
  - *Big* 格式（`io.sstable.format.big.BigTableReader/Writer`）：经典 `Data.db` / `Index.db` / `Summary.db` / `Filter.db` / `CompressionInfo.db` / `Statistics.db` 多文件，前缀形如 `-lb-`。`SSTableReader` 持有 bloom、index summary、key cache。
  - *BTI* 格式（`io.sstable.format.trie.TrieSSTableReader/Writer`，CEP-25，`sstable: {selected_format: bti}`）：用 **trie 前缀树** 组织 partition / row 索引，**去掉 Summary.db 且不再依赖 key cache**（故 `cassandra_latest.yaml` 默认 `key_cache_size_in_mb: 0`）。更紧凑、对大分区/百万行分区查找更优。旧格式仍可读，新格式由 compaction 或 `nodetool upgradesstables` 重写；**旧版本无法读 BTI，切 BTI 是不可逆回滚点**。
- **Bloom / 缓存**：`utils.BloomFilter` / `FilterFactory`；`cache.{KeyCache, RowCache, CounterCache}` 与 `KeyCacheKey` / `RowCacheKey`。
- **读路径**：`ReadCommand.execute → ColumnFamilyStore.getRow/getPartition → 对各候选 SSTableReader 用 SSTableRowIterator 拉数据`，与 memtable 在 `DataResolver` 中按 cell timestamp 做 LWW 合并。

### Memtable Internals: Skip-List vs Trie

经典 `SkipListMemtable` 把每个分区存成独立并发跳表、分区内再嵌套小对象——高写入下产生大量长生命周期小对象，正是 GC 最怕的模式。Trie memtable 把分区索引结构放进**可 off-heap 的 buffer**（trie），官方称其带来更优的 GC 行为、内存效率与查找速度；宽分区（百万行级）收益尤其明显。代价是内存布局更复杂，需 5.0 的 trie 实现成熟后才推荐默认开启。

## vs HBase / RocksDB

| 维度 | Cassandra | HBase | RocksDB |
| --- | --- | --- | --- |
| 写入 | CommitLog + MemTable + SSTable | WAL + MemStore + HFile | WAL + MemTable + SSTable |
| 合并 | 多种 compaction 策略 | major/minor compaction | Leveled compaction |
| 读合并 | LWW + Bloom | LWW + Bloom | LWW + Bloom |
| 部署 | 自带，无外部依赖 | 依赖 HDFS + ZK | 嵌入式库 |
| 多 DC | 内建 | 外部 | 无 |

## Links

- [Cassandra](/docs/CS/DB/Cassandra.md)
- [Compaction](/docs/CS/DB/Cassandra/Compaction.md)
- [Data Model](/docs/CS/DB/Cassandra/DataModel.md)
- [Distributed](/docs/CS/DB/Cassandra/Distributed.md)

## References

- [Cassandra Storage Engine (官方文档)](https://cassandra.apache.org/doc/latest/cassandra/architecture/storage_engine.html)
- [CEP-19 Trie Memtable](https://cassandra.apache.org/doc/latest/cassandra/architecture/memtable.html)
