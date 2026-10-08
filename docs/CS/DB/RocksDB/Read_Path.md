## Introduction

RocksDB 的读路径要解决的是 LSM 的固有问题：**一个 key 的多个版本散落在内存与多层不可变文件里，还要按快照判定可见性**。因此一次点查的成本 = 查了几个结构 + 每个结构里跳过了多少无用 KV。读放大与它的缓解手段是本页主线，符号与默认值取 v11.8.1。

## The Get Lookup Order

`DBImpl::GetImpl` 声明在 `db_impl.h:734`，实现体在 **`db/db_impl/db_impl_sync_and_async.h:70`**——v11 把同步与协程两个版本用同一个头文件生成，按旧路径 `db_impl.cc` 去找会找不到（这条适用于多个读函数）。查找顺序严格从新到旧：

1. `sv->mem->Get`（:240）——活跃 memtable；
2. `sv->imm->Get`（:257）——已封存待 flush 的 memtable；
3. `sv->current->Get`（:301）——SST 层，由 `FilePicker` 逐层挑文件（`db/version_set.cc:313`，注释「level by level」）：L0 **必须全扫**且从新到旧（:465-478），L1 及以上按 key 范围二分 + `FileIndexer` 收窄边界。

每个候选文件在进入块读取之前先过 Bloom filter：`TableCache::Get` → `BlockBasedTable::Get`，其中 `FullFilterKeyMayMatch`（:533）**排在 `NewIndexIterator`（:545）之前**——filter 的意义就是省掉索引与数据块的 IO。命中与有效性分别记在 `BLOOM_FILTER_FULL_POSITIVE` 与 `BLOOM_FILTER_USEFUL` 两个 ticker 上（`block_based_table_reader.cc:2671/2674`）。

两个工程细节值得单独记：

- **可见序号必须在 ref 住 SuperVersion 之后再取**。取快照序号或用 `GetLastPublishedSequence()`，都发生在拿到视图之后（:148-182 的注释解释了原因）——反序会读到比视图更新的序号，出现「视图里没有但序号认为应该可见」的错乱。
- **SuperVersion 的取用在命中时是无锁的**：`ColumnFamilyData::GetThreadLocalSuperVersion`（`column_family.cc:1385`）对 `ThreadLocalPtr` 做一次 `Swap(kSVInUse)`，只有被 `InstallSuperVersion` 标记为 `kSVObsolete` 时才走 mutex + 引用计数（:1407），归还用 `CompareAndSwap`（:1419）。这是高频点查路径能扛住并发的关键。

还有一条提前退出：一旦发现有范围墓碑覆盖（`max_covering_tombstone_seq > 0`）就 break 文件遍历（`version_set_sync_and_async.h:65`），因为更旧的文件不可能改变结论。

## Internal Key and Sequence Number

用户键之上叠一层内部键（`db/dbformat.h`）：

```
PackSequenceAndType(sequence, type) = (sequence << 8) | type   // :185
ParsedInternalKey { user_key, sequence, type }                  // :141
kNumInternalBytes = 8                                           // :134
kMaxSequenceNumber = (1ull << 56) - 1                           // :129 = 72057594037927935
```

`ValueType` 是 `unsigned char`（:41），实测取值：`kTypeDeletion = 0x0`、`kTypeValue = 0x1`、`kTypeMerge = 0x2`、`kTypeSingleDeletion = 0x7`、`kTypeColumnFamilyRangeDeletion = 0xE`（仅存在于 WAL）、`kTypeRangeDeletion = 0xF`（只进 meta block）、`kTypeBlobIndex = 0x11`、`kTypeDeletionWithTimestamp = 0x14`、`kTypeWideColumnEntity = 0x16`、`kTypeValuePreferredSeqno = 0x18`。

一个容易踩的版本差异：**`kValueTypeForSeek` 现在是 `kTypeValuePreferredSeqno`，不再是 `kTypeValue`**（`dbformat.cc:28-29`；`kValueTypeForSeekForPrev` 仍是 `kTypeDeletion`）。Seek 时拼出的那个「哨兵内部键」决定了能否落到该 user key 的最新版本上。

`LookupKey` 已独立到 `db/lookup_key.h:20`（布局 `klength | userkey | tag`，自带 `space_[200]` 避免小键分配）；`LookupContext` 这个类**不存在**，读上下文类是 `table/get_context.{h,cc}`（已不在 `db/` 下）。

## ReadOptions

`ReadOptions` 的字段（`include/rocksdb/options.h:2137-2506`）比多数文章写的多，实测默认值如下：

| 字段 | 默认 | 说明 |
| :--- | :--- | :--- |
| `snapshot` | `nullptr` | 为 null 时用最后发布序号，即读最新已提交状态 |
| `verify_checksums` | **`true`** | 关它能省 CRC，但等于放弃静默损坏检测 |
| `fill_cache` | `true` | 全表扫描类读应设 false，避免冲掉 block cache |
| `read_tier` | `kReadAllTier` | 枚举见 `options.h:1934` |
| `iterate_upper_bound` / `iterate_lower_bound` | `nullptr` | 半开区间上/下界 |
| `total_order_seek` | `false` | 见迭代器一节 |
| `auto_prefix_mode` | `false` | 前缀语义的另一开关 |
| `prefix_same_as_start` | `false` | 只在配了 `prefix_extractor` 时生效 |
| `pin_data` | `false` | pin 住数据块（配合 `kBlockCacheTier` 可做「只读缓存」探针） |
| `readahead_size` | `0` | 顺序读预读 |
| `auto_readahead_size` | **`true`** | 自动决定预读大小 |
| `adaptive_readahead` | `false` | 跨文件自适应预读 |
| `max_skippable_internal_keys` | `0` | 超限返回 `Incomplete("Too many internal keys skipped.")` |
| `tailing` | `false` | 尾随迭代器 |
| `async_io` | `false` | 异步读 |
| `optimize_multiget_for_io` | `true` | MultiGet 的 IO 合并优化 |
| `value_size_soft_limit` | `UINT64_MAX` | 累计读到的 value 字节软上限 |
| `merge_operand_count_threshold` | `nullopt` | Merge operand 数量阈值 |
| `allow_unprepared_value` | `false` | 只对 BlobDB 大值与多列族迭代有意义（:2403-2414） |
| `table_filter` | 空 | 按表属性跳过 SST |
| `auto_refresh_iterator_with_snapshot` | `false` | 10.0 起 |
| `rate_limiter_priority` | `Env::IO_TOTAL` | 走哪条限速通道 |
| `deadline` / `io_timeout` | `0` | 超时 |
| `ignore_range_deletions` | `false` | **已标 DEPRECATED** |

**不存在的字段**（旧文章里常出现，别写）：`read_tailing_mode`、`background_error_on_iter_creation`、`read_user_time`、`io_budget`、`auto_stop_updates`、`allow_unprepared_value_read`（实名 `allow_unprepared_value`）、`max_snapshot_requests`。

## Iterator

内部迭代器类名是 **`DBIter`**（`db/db_iter.cc:65`），不是 `DBIterator`。构造链在 `DBImpl::NewInternalIterator`（`db_impl.cc:2558`）：`MergeIteratorBuilder`（以 `prefix_seek_mode = !total_order_seek && prefix_extractor != nullptr` 决定前缀模式，:2568）→ mem 的点迭代器 + 每个文件的 `TruncatedRangeDelIterator`（:2583-2598）→ `imm->AddIterators`（:2611）→ 当 `read_tier != kMemtableTier` 时 `current->AddIterators`（:2621）→ `Finish`（:2625）。

归并器有个省开销的细节：`NewMergingIterator`（`table/merging_iterator.cc:1655`）在子迭代器数为 0 时返回空、**为 1 时直接返回那一个子迭代器**，只有 ≥2 才真的建 `MergingIterator`（:1691）。

Seek 语义有四种，代价差别很大：

- 默认 `Seek` 走**前缀 Seek**（若配了 `prefix_extractor`），可以只查落在该前缀内的文件；
- `total_order_seek = true` 关闭前缀假设，保证不漏 key，但要扫更多文件；`expect_total_order_inner_iter_` 的条件是「无 prefix_extractor ‖ total_order_seek ‖ auto_prefix_mode」（`db_iter.cc:115`）；
- `prefix_same_as_start = true` 需要 `prefix_extractor` 才生效，迭代越出起始前缀即停（:112/:543）；
- `SeekForPrev` 反向定位，内部键类型用 `kTypeDeletion` 作哨兵。

DB 层还有一个全局开关 `DBOptions::prefix_seek_opt_in_only = false`（`options.h:1631`）：置 true 时**所有迭代器视同 total order seek**，只有显式开了 `auto_prefix_mode` 或 `prefix_same_as_start` 的才享受前缀优化——这是给「忘了配 prefix_extractor 却依赖前缀语义」的历史行为准备的收紧开关。

`tailing = true` 的迭代器由 `ForwardIterator`（`db/forward_iterator.cc`，在 `db_impl.cc:4159` 挂载）实现：序号取 `kMaxSequenceNumber`、内部 `allow_unprepared_value = true`，可持续观察新写入；普通无快照迭代则取 `versions_->LastSequence()`（:4189-4199）。`iterate_lower_bound` 只管反向下界，与前缀模式无耦合（注释要求它和 seek key 同前缀，:2263-2274）。

## Snapshots and MVCC

`GetSnapshot()` → `GetSnapshotImpl(false)`（`db_impl.cc:4404`）拿的是 **`GetLastPublishedSequence()`**（:4472），节点挂进 `SnapshotList snapshots_`（`db_impl.h:3376`，实现是 `db/snapshot_impl.h:54` 的双向循环链表，提供 `count()` / `oldest()`）。

快照真正的影响体现在 compaction 侧：压实通过 `SnapshotChecker`（`db/snapshot_checker.h:18`，返回 `kInSnapshot / kNotInSnapshot / kSnapshotReleased`）与 `earliest_snapshot_` 判断某个旧版本是否还被引用，被引用就保留——**长期不释放的快照 = 空间放大与读放大的共同来源**。

反过来也有个容易被忽略的动作：`ReleaseSnapshot`（:4602）会用新的 oldest 序号调 `UpdateOldestSnapshot` 并 `BottommostFilesMarkedForCompaction`，再 `EnqueuePendingCompaction`（:4615-4640）——**释放快照会主动触发底部压实去回收那些之前不能删的版本**。

可见性判定本身很朴素：`DBIter::IsVisible` 即 `sequence <= sequence_`，事务另走 `ReadCallback`（`db_iter.cc:1812`）。观测用属性：`rocksdb.num-snapshots`、`rocksdb.oldest-snapshot-time`、`rocksdb.oldest-snapshot-sequence`（`db.h:1428-1436`）。注意 `GetSnapshotListSize` 这个符号在本版本**不存在**。

## MergeOperator

`MergeOperator` 的读侧合并有三个演进中的接口：`FullMerge`（`merge_operator.h:79`）、`FullMergeV2`（:161）、`FullMergeV3(const MergeOperationInputV3&, MergeOperationOutputV3*)`（:209）。V3 的 `existing_value` 是 `variant<monostate, Slice, WideColumns>`（:165）、`new_value` 是 `variant<string, NewColumns, Slice>`（:191），以支持宽列。部分合并是 `PartialMerge`（:243）与 `PartialMergeMulti`（:271）。

一个语义要点：**合并发生在读取或压实的时候，而不是写入的时候**。`kTypeMerge` 只是往 LSM 里追加一个 operand，`DBIter::MergeValuesNewToOld`（`db_iter.cc:773`）在迭代时把它和已有值交给 `MergeHelper::TimedFullMerge`（:1556/1569/1625）算出结果。所以 merge 用得越多，读放大越明显。

失败范围由 `OpFailureScope` 决定（`merge_operator.h:110-141`）：`kTryMerge` 下合并失败会把库置为只读，`kMustMerge` 允许 flush/compaction 原样搬运 operand。要只看 operand 不做合并，用 `DB::GetMergeOperands`（走 `GetImplOptions::get_value = false` 的同一实现，`db_impl_sync_and_async.h:276-289`），可传 `expected_max_number_of_operands` 与 `continue_cb`（`db.h:125-146`），容量不足返回 `Incomplete`；或用 `ReadOptions::merge_operand_count_threshold`，超阈值返回 OK + 子码 `kMergeOperandThresholdExceeded`（:328-332）。

## Range Tombstone

范围删除的实现位置换过：`struct RangeTombstone` 现在在 **`db/dbformat.h:1091`**（仓库里已没有 `db/range_tombstone.h`），碎片化在 `db/range_tombstone_fragmenter.{h,cc}`，读取时用 `TruncatedRangeDelIterator` 把覆盖当前区间的墓碑接进归并链；哨兵键 `kRangeTombstoneSentinel = PackSequenceAndType(kMaxSequenceNumber, kTypeRangeDeletion)`（`dbformat.h:201`）。

代价是双向的：点查每个文件要先算 `MaxCoveringTombstoneSeqnum`，迭代要维护一个 active 堆（约 `O(log K)`）。

**「范围墓碑必须手工 `CompactRange` 才能清掉」这句话已经过时**：8.4.0 起在安全前提下非底部压实也会丢弃范围墓碑（`HISTORY.md:943`，PR #11459），9.8.0 起只含范围墓碑的文件会被主动标记进压实（:485）。11.2.0 另给了 `min_tombstones_for_range_conversion`（`AdvancedColumnFamilyOptions`，:121，迭代侧 `db_iter.cc:124-129`），用于把点删积累转成范围删除，但它与 `table_filter`、非全前缀可见迭代互斥。

## Read Amplification: Causes and Knobs

按影响从大到小：

1. **没开 Bloom filter**。`filter_policy` 默认是 `nullptr`，即默认完全没有 filter（`table.h:590`），每个点查都要逐文件走索引。见 [Table_Format](/docs/CS/DB/RocksDB/Table_Format.md)。
2. **L0 文件太多**。L0 必须全扫，`level0_file_num_compaction_trigger` 与压实能力决定其稳态高度。
3. **未合并的 Merge operand** 与**未清理的删除标记**（版本堆积 + 墓碑跳过）。
4. **`optimize_filters_for_hits`**（默认 false，`advanced_options.h:816`）：为 true 时对**最底层**文件跳过 filter（判定式 `optimize_filters_for_hits && (level > 0 || is_last_in_level) && level == num_non_empty_levels - 1`，`version_set.cc:3147-3152`）——适合「数据基本都在最后一层、且读以不存在 key 为主」的场景，用省掉的 filter 空间换更小的底部文件。
5. **`cache_index_and_filter_blocks`**（默认 false，`table.h:238`）：为 true 时索引与过滤器进入 block cache、可被逐出，读放大上升换来内存可控；配套 `..._with_high_priority = true`（:244）与 `pin_l0_filter_and_index_blocks_in_cache = false`（:267）。

## Links

- [RocksDB](/docs/CS/DB/RocksDB/RocksDB.md)
- [Write Path](/docs/CS/DB/RocksDB/Write_Path.md)
- [Compaction](/docs/CS/DB/RocksDB/Compaction.md)
- [Table Format](/docs/CS/DB/RocksDB/Table_Format.md)
- [Bloom Filter](/docs/CS/Algorithms/struct/BloomFilter.md)
- [Transactions](/docs/CS/DB/RocksDB/Transactions.md)

## References

1. [RocksDB Wiki: Iterator](https://github.com/facebook/rocksdb/wiki/Iterator)
2. [RocksDB Wiki: Snapshot](https://github.com/facebook/rocksdb/wiki/Snapshot)
3. [RocksDB source: db/dbformat.h](https://github.com/facebook/rocksdb/blob/v11.8.1/db/dbformat.h)
4. [RocksDB source: include/rocksdb/options.h](https://github.com/facebook/rocksdb/blob/v11.8.1/include/rocksdb/options.h)
