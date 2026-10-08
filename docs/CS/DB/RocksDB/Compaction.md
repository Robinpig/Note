## Introduction

Compaction 是 RocksDB 里唯一同时决定**写放大、读放大、空间放大**的机制：它把上层 SST 与下层重叠的文件归并重写，顺带清理被覆盖的版本、过期数据与删除标记。RocksDB 的绝大部分可调项，最终都是在给「压实来得多快、多宽、多省」这三个问题让路。本页符号与默认值取 v11.8.1 源码。

## Level Structure and Size Targets

不变式是：**L0 内文件 key 区间可以重叠，L1 及以下每层内部不重叠**。承载它的是 `VersionStorageInfo::level0_non_overlapping_`（`db/version_set.cc:2689`）——L0 只有在已排干净时才参与某些优化，例如 `Compaction::IsTrivialMove()` 显式要求 `input_vstorage_->level0_non_overlapping()` 才允许 L0→L1 直接移动（`compaction.cc:562-567`）。

| 选项 | 默认 | 出处 | 含义 |
| :--- | :--- | :--- | :--- |
| `num_levels` | 7 | `advanced_options.h:538` | 层级数 |
| `target_file_size_base` | 64 MB | `:568` | 输出文件目标大小，公式 `base × multiplier^(L-1)` |
| `target_file_size_multiplier` | 1 | `:574` | 逐层不变，即各层单文件目标同为 64 MB |
| `target_file_size_is_upper_bound` | `false` | `:585` | 目标值不是硬上限 |
| `max_bytes_for_level_base` | 256 MB | `options.h:303` | 基准层容量 |
| `max_bytes_for_level_multiplier` | 10 | `:671` | 每层约 10 倍——写放大的直接来源 |
| `max_bytes_for_level_multiplier_additional` | 每层 1 | `:682` | **dynamic level bytes 开启时被忽略** |
| `max_compaction_bytes` | 0 → 实际 `target_file_size_base × 25` = 1.6 GB | `:689-701` | 单次压实的输入上限 |

`level_compaction_dynamic_level_bytes` 在 v11.8.1 **默认已是 `true`**（`advanced_options.h:666`，翻转记录见 `HISTORY.md:940`）。开启后 Ln ≈ L(n-1) × multiplier、L0 可以直接并进 base level，副作用是 `compression_per_level[i]` 的索引会随层偏移（`advanced_options.h:514-525`）——旧资料按「逐层递增容量」写的调优建议需要重新核对。

## Compaction Styles

枚举实测取值是 `kCompactionStyleLevel = 0x0`、`kCompactionStyleUniversal = 0x1`、`kCompactionStyleFIFO = 0x2`、`kCompactionStyleNone = 0x3`（`advanced_options.h:29-36`），默认 Level（:720）。**没有 `kCompactionStyleFixed`**（那是其他项目的命名）。文件挑选优先级由 `compaction_pri` 决定，默认 `kMinOverlappingRatio`（:725，另有 `kRoundRobin = 0x4`）——挑「与下一层重叠最小」的文件，直接压低写放大。

三者在放大三角上的位置：

| 风格 | 写放大 | 读放大 | 空间放大 | 适用 |
| :--- | :--- | :--- | :--- | :--- |
| Leveled | 高 | 低 | 低 | 读多、要稳定延迟 |
| Universal（size-tiered） | 低 | 高 | 高 | 写多、读少、可接受偶尔大压实 |
| FIFO | 极低 | 高 | 有界 | 时序/TTL 型数据，按大小或温度淘汰 |

Universal 的参数集中在 **`CompactionOptionsUniversal`**（定义在独立头 `include/rocksdb/universal_compaction.h:24`）：`size_ratio = 1`、`min_merge_width = 2`、`max_merge_width = UINT_MAX`、`max_size_amplification_percent = 200`（100 B 有效数据最多占 300 B）、`compression_size_percent = -1`、`max_read_amp = -1`（0 表示自动调优，且只支持 TotalSize；若 `0 < max_read_amp < level0_file_num_compaction_trigger`，DB open 直接返回 `NotSupported`）、`stop_style = kCompactionStopStyleTotalSize`、`allow_trivial_move = false`、`incremental = false`、`reduce_file_locking = true`（注释声明该开关将来会移除）。

FIFO 的结构体名**仍是 `CompactionOptionsFIFO`**、字段仍是 `compaction_options_fifo`（`advanced_options.h:71/739`，没被改名）。`max_table_files_size = 1 GB`（:75/177）、`allow_compaction = false`（:83）、`max_data_files_size = 0`（SST + blob 合计，非 0 时压过 `max_table_files_size`，:149-160）、`use_kv_ratio_compaction = false`（:175）。⚠️ `age_for_warm` **已 DEPRECATED**（:88），替代品是 `file_temperature_age_thresholds`（:115）。FIFO 的 `ttl` 需要 `max_open_files = -1`（:870），而 `periodic_compaction_seconds` 对 FIFO 已无效（`HISTORY.md:911`）。**`TtlOptions` / `MaxCountOptions` 在 RocksDB 中不存在。**

## Triggers

- **按 L0 文件数**：`level0_file_num_compaction_trigger = 4`（`options.h:255`；设负值即关闭该触发）。
- **按积压字节**：`soft/hard_pending_compaction_bytes_limit`（见 [Write_Path](/docs/CS/DB/RocksDB/Write_Path.md)）。
- **手工**：`DB::CompactRange`（`db.h:1728`）与 `DB::CompactFiles(const CompactionOptions&, ...)`（`db.h:1808`）。注意**没有 `CompactFilesOptions` 这个类型**，`CompactRangeOptions` 里也**没有 `best_efforts`、`unwrap_timestamps`、`allow_trivial_move`**（`allow_trivial_move` 属于 `CompactionOptions`，`options.h:2697`，用于 `CompactFiles`）。`CompactRangeOptions` 的真实字段包括 `exclusive_manual_compaction = false`（:2742，**`ManualCompaction::exclusive` 这个名字不存在**）、`change_level`、`target_level = -1`、`target_path_id`、`allow_write_stall`、`canceled`（`DisableManualCompaction()` 会覆写它）。
- **按时间**：`ttl` 与 `periodic_compaction_seconds` 的默认都是哨兵值 `0xfffffffffffffffe`（auto，`advanced_options.h:894/942`），单位为秒，auto 解析为 **30 天**，两者取较严者；**设 0 才是关闭**。
- **关闭自动压实**：`disable_auto_compactions`（`options.h:309`）或 `DB::EnableAutoCompaction(cfds)`（`db.h:1843`）。**v11.8.1 没有 `DB::DisableAutoCompaction()`**，另有 `PauseBackgroundWork()`（:1831）。

**Subcompaction** 的开关是 `DBOptions::max_subcompactions = 1`（即默认不切，`options.h:926`；`CompactRangeOptions::max_subcompactions = 0` 表示继承，:2761）。能否切由 `Compaction::ShouldFormSubcompactions()` 决定（`compaction.cc:915-942`）：PlainTable 一律不切；`max_subcompactions <= 1` 不切；leveled 需要 `(start_level == 0 ‖ manual) && output_level > 0`；universal 需要 `number_levels > 1 && output_level > 0`；**FIFO 恒不切**。切分点是 `CompactionJob::GenSubcompactionBoundaries()`（`compaction_job.cc:542-567`）：从每个输入文件的 index block 估约 128 个锚点，合并排序后按字节均分——所以锚点区间重叠时输出尺寸会低估。

## Compaction Filter

`include/rocksdb/compaction_filter.h` 的现状和旧文档差别很大：**没有 `CompactionFilterV2` 类、也没有 `ShouldFilter()`**（`FilterV2` 只是 `CompactionFilter` 的一个虚函数；`CompactionFilterV2` 接口 3.13 弃用、后续版本已从该头文件移除，见 `HISTORY.md:3066/3041`）。当前的重载链是：`Filter`（:274）、`FilterMergeOperand`（:294）、`FilterV2`（:311）、`FilterV3`（宽列，:361）、`FilterV4`（带 `WideColumnBlobResolver` 惰性取 blob，:409，**v11.8 新增**）、`FilterBlobByKey`（:509）。

`Decision` 的取值：`kKeep` / `kRemove` / `kChangeValue` / `kRemoveAndSkipUntil` / `kUndetermined`，另有把值转成 **SingleDelete 型 tombstone** 的选项（:201-204）。`kRemoveAndSkipUntil` 的注释明确警告：可能连尚未写入的版本一起消失（:181-189）。

两个必须知道的约束：

1. **`IgnoreSnapshots()` 已废弃且必须返回 true**——覆写成 false 会让 table file creation 直接失败（:438-443）。含义是 filter 不再能阻止快照相关版本被删。
2. `CompactionFilterFactory` 存在的理由是线程安全：每个线程按 `ShouldFilterTableFileCreation(reason)` 决定是否 `CreateCompactionFilter(context)`，从而让 filter 实现无需可重入（:474-476）；默认只对 `TableFileCreationReason::kCompaction` 生效（:495）。

至于「非底部层不能删 tombstone」这个常见说法，真实条件更细：`kTypeDeletion` 在**非 bottommost** 也可以被丢弃，但要同时满足 `!allow_ingest_behind`、`DefinitelyInSnapshot(seq, earliest_snapshot)`、`KeyNotExistsBeyondOutputLevel()`（`db/compaction/compaction_iterator.cc:1153-1160`）；bottommost 分支则要求同 key 之后确实没有更旧版本，否则保留这条 Delete（:1189-1234）。序号归零优化只在 `bottommost_level_` 且非 merge/range-del 时生效（:1910-1914）。快照如何卡住这一进程，见 [Read_Path](/docs/CS/DB/RocksDB/Read_Path.md) 的 Snapshot 一节。

## Compression and the Bottommost Level

`compression_per_level` 默认是**空 vector**（`advanced_options.h:535`），此时所有层都用 `ColumnFamilyOptions::compression`，其默认按编译开关取 `kLZ4Compression`（否则 Snappy，再否则 NoCompression，`options.h:195`）。

底部层是否值得重压缩，由 `BottommostLevelCompaction` 控制，实际枚举是 **`kSkip` / `kIfHaveCompactionFilter` / `kForce` / `kForceOptimized`**（`options.h:2730-2748`，**没有 `kEnabled`**），`CompactRangeOptions` 默认 `kIfHaveCompactionFilter`（:2755）；且 `HISTORY.md:942` 说明该值现在行为类似 `kForceOptimized`。带 filter 的手工压实**禁止 trivial move**（`compaction.cc:569-575`）。

Trivial move（只改元数据、不重写文件）的条件在 `compaction_picker_level.cc:655-672`：需要 `base_level() > 0`、`compression_per_level` 为空、输出层非空、`db_paths <= 1`，并从最旧文件向后扩展；跨层最多 4 个文件（`kMaxMultiTrivialMove = 4`，:737）。

顺带辟谣：`compact_on_deletion_collector` **不是列族选项**（源码 grep 零命中），只有 collector 工厂 `CompactOnDeletionCollectorFactory` 存在，且在 universal + `num_levels = 1` 下被禁用（`HISTORY.md:2138`）。

## Rate Limiting and Background Budget

后台压实的 IO 抖动由 rate limiter 收口：`NewGenericRateLimiter(rate_bytes_per_sec, refill_period_us = 100 × 1000, fairness = 10, mode = kWritesOnly, auto_tuned = false, single_burst_bytes = 0)`（`include/rocksdb/rate_limiter.h:166-170`），`auto_tuned` 在 `[rate/20, rate]` 区间动态调节（:160-162）；`DBOptions::rate_limiter` 默认 `nullptr`（`options.h:734`）。写侧的对应项是 `delayed_write_rate`（0 → 从 limiter 推断，否则 16 MB/s）与 `bytes_per_sync` / `wal_bytes_per_sync` / `strict_bytes_per_sync`。

线程预算：`max_background_jobs = 2`（`options.h:900`），而 `max_background_compactions = -1`、`max_background_flushes = -1` **均已 DEPRECATED**（:918/:948）。列族多、后台线程少时 flush 与 compaction 会互相排队，进而变成写停顿（见 [Column_Families](/docs/CS/DB/RocksDB/Column_Families.md)）。

## Observability

`rocksdb.` 前缀的属性里与压实相关的实测项（`db/internal_stats.cc:247` 起）：`num-files-at-level<N>`、`estimate-pending-compaction-bytes`、`compaction-pending`、`num-running-compactions`、`num-running-compaction-sorted-runs`、`estimate-live-data-size`、`estimate-oldest-key-time`、`mem-table-flush-pending`、`estimate-num-keys`、`live-sst-files-size`、`background-errors`。**没有 `rocksdb.estimate-levels`，也没有 `rocksdb.compact` 属性**（后者是 `db_bench` 的命令名，不是 property）。

## Links

- [RocksDB](/docs/CS/DB/RocksDB/RocksDB.md)
- [Write Path](/docs/CS/DB/RocksDB/Write_Path.md)
- [Read Path](/docs/CS/DB/RocksDB/Read_Path.md)
- [Table Format](/docs/CS/DB/RocksDB/Table_Format.md)
- [Column Families](/docs/CS/DB/RocksDB/Column_Families.md)
- [Operations](/docs/CS/DB/RocksDB/Operations.md)

## References

1. [RocksDB Wiki: Compaction](https://github.com/facebook/rocksdb/wiki/Compaction)
2. [RocksDB Wiki: Universal Compaction](https://github.com/facebook/rocksdb/wiki/Universal-Compaction)
3. [RocksDB Wiki: Compaction Filter](https://github.com/facebook/rocksdb/wiki/Compaction-Filter)
4. [RocksDB source: advanced_options.h](https://github.com/facebook/rocksdb/blob/v11.8.1/include/rocksdb/advanced_options.h)
