## Introduction

RocksDB 的磁盘格式是 **SST（Sorted String Table）**：不可变、按键有序、分块存储，每块独立压缩并带校验。默认表实现是 `BlockBasedTable`（另有面向 flash 的 `PlainTable`，它不参与 subcompaction，见 [Compaction](/docs/CS/DB/RocksDB/Compaction.md)）。本页把「一个 SST 长什么样」以及读一次要付出什么拆开讲，默认值取 v11.8.1 的 `include/rocksdb/table.h` 与 `cache.h`。

## Block Layout and Indexing

| 选项 | 默认 | 出处 | 影响 |
| :--- | :--- | :--- | :--- |
| `block_size` | 4096 | `table.h:400` | 数据块目标大小：读粒度 vs 解压成本 |
| `block_size_deviation` | 10 | `:407` | 允许偏离百分比以对齐 key 边界 |
| `block_restart_interval` | 16 | `:413` | 前缀编码重启点，越小随机定位越快、空间越大 |
| `index_block_restart_interval` | 1 | `:416` | 索引块的重启间隔 |
| `index_type` | `kBinarySearch` | `:326` | 另有 `kHashSearch`（:325）可按前缀直接定位 |
| `data_block_index_type` | `kDataBlockBinarySearch` | `:362` | 设 `kDataBlockBinaryAndHash` 时块内按 hash 定位，比率 `data_block_hash_table_util_ratio = 0.75` |
| `index_block_search_type` | `kBinary` | — | v11 新增 `BlockSearchType{kBinary, kInterpolation, kAuto}` 与 `uniform_cv_threshold` |
| `checksum` | `kXXH3` | `:672` 区 | 校验算法 |
| `no_block_cache` | `false` | `:380` | 关掉块缓存 |
| `separate_key_value_in_data_block` | `false` | `:745` | 10.10 引入，键值在块内分离存放 |

`format_version` 默认已是 **7**（`table.h:739`，10.11.0 起，见 `HISTORY.md:188`）。版本号决定可读性与可用特性：v2 起支持压缩块内编码、v3 索引键存原始形式、v4 索引值增量、v5 新 Bloom schema、**v6 重写 footer 与校验以抵御块错位**（8.6.0）、**v7 支持自定义 `CompressionManager` / `compression_name`**（10.4.0）。11.0.0 起**拒绝读取 `format_version < 2`**。跨版本降级部署前必须核对这一项，因为它影响的是老 reader 能否打开新文件。

## Filters: The Default Is No Filter

`BlockBasedTableOptions::filter_policy` 默认值是 **`nullptr`**（`table.h:590`）——**开箱的 RocksDB 不生成任何 Bloom filter**。旧文章里「默认 `NewBloomFilterPolicy(10)`」在 v11.8.1 不成立，这直接解释了为什么很多系统默认点查延迟偏高（见 [Read_Path](/docs/CS/DB/RocksDB/Read_Path.md)）。

公共工厂只有两个：

```
NewBloomFilterPolicy(double bits_per_key,
                     bool IGNORED_use_block_based_builder = false)   // filter_policy.h:166
NewRibbonFilterPolicy(double bloom_equivalent_bits_per_key,
                      int bloom_before_level = 0)                     // :209
```

第二个参数名里的 `IGNORED` 是字面意思：`use_block_based_builder` 自 7.0 起被忽略。`bloom_before_level = 0` 表示 L0/flush 用 Bloom、其余层用 Ribbon（**Ribbon 需要 reader ≥ 6.15**；hybrid 方案与生产可用分别记在 `HISTORY.md:1757` 与 `:1806`）。Ribbon 在同等误判率下比经典 Bloom 更省空间，代价是构建更慢、不支持动态增删。

配套项：`partition_filters = false`（`:519`，开启需 `kTwoLevelIndexSearch`）、`metadata_block_size = 4096`（`:423`）、`whole_key_filtering = true`（`:662`，为 false 时只保留前缀 filter）、`optimize_filters_for_memory = true`。⚠️ `decouple_partitioned_filters` 默认 true 但**已 DEPRECATED**（`:547`）。另外 `NewFastLocalFilterPolicy`、`NewFullFilterPolicy`、`NewWholeKeyFilterPolicy` 这些名字**都不存在**，别照旧资料写。

## Caching

`block_cache` 默认为 `nullptr`，此时**内部自动创建一个 32 MB 缓存**（`table.h:390`，注释见 :382-389）。从 **10.7.0 起该默认实现是 HyperClockCache 而不是 LRU**（`HISTORY.md:254/259`）——旧的「默认 LRU」表述已全部过时。

创建方式也变了：`NewLRUCache(capacity, num_shard_bits, strict_capacity_limit, high_pri_pool_ratio, ...)` 在 `cache.h:277-292` 被明确标注为 **"DEPRECATED wrapper function"**，推荐 `LRUCacheOptions(...).MakeSharedCache()`（:270）。`num_shard_bits < 0` 时按容量自动选分片数（:134-138）。

HyperClockCache 侧：`HyperClockCacheOptions(capacity, estimated_entry_charge = 0, num_shard_bits = -1, strict_capacity_limit = false, ...)`（`cache.h:464`），`estimated_entry_charge = 0` 即自动变体（:408，已生产可用），`eviction_effort_cap = 30`（:483）。**没有 `NewHyperClockCache` 自由函数**；`NewClockCache(...)` 名字还在但**只返回 LRUCache**（旧的 ClockCache 实现已移除，:480-486）。更高层的组合缓存 `SecondaryCache` / `TieredCache` 也在 `cache.h`。

索引与过滤器是否进缓存由 `cache_index_and_filter_blocks`（默认 `false`，`table.h:238`）决定：为 true 时它们可被逐出、每次读重新取，用读放大换内存可控；配套 `..._with_high_priority = true`（:244）与 `pin_l0_filter_and_index_blocks_in_cache = false`（:267）、`pin_top_level_index_and_filter = true`（:289）。`block_cache_compressed` **已在 8.0.0 删除**（`HISTORY.md:1039`）。

## Compression and Dictionaries

`CompressionType` 的实测取值（`include/rocksdb/compression_type.h:21-67`）：`kNoCompression = 0x00`、`kSnappyCompression = 0x01`、`kZlibCompression = 0x02`、`kBZip2Compression = 0x03`、`kLZ4Compression = 0x04`、`kLZ4HCCompression = 0x05`、`kXpressCompression = 0x06`、`kZSTD = 0x07`（= `kLastBuiltinCompression`），自定义算法占 `0x80–0x9F`。⚠️ `kZSTDNotFinalCompression` **已在 10.0.0 删除**，ZSTD 最低要求 1.4.0（`HISTORY.md:407`）。

三处独立配置：`compression`（编译期决定，默认 LZ4，退化 Snappy、再退化 None）、`bottommost_compression = kDisableCompressionOption`（`options.h:224`，表示底部层沿用 `compression`）、`wal_compression = kNoCompression`（:1570）。层间差异靠 `compression_per_level`（见 [Compaction](/docs/CS/DB/RocksDB/Compaction.md)）。

**字典压缩**的真实入口是 `CompressionOptions`（`compression_type.h:238` 起）：`max_dict_bytes = 0`、`zstd_max_train_bytes = 0`、`max_dict_buffer_bytes = 0`、`use_zstd_dict_trainer = true`（:302）。`enable_dictionary_compaction` 与 `kDictCompress` **不存在**，`CompactionOptions` / `CompactFiles` 也没有字典专属字段（只有 `compression` 与 `compression_opts`）。字典对小块解压尤其关键：它把每块独立压缩变成「带共享训练字典」，代价是读时要先取字典块（对应 ticker `compression_dict_block_read_count`）。

## BlobDB: Key-Value Separation for Large Values

LSM 把 value 和 key 一起反复重写，大 value 因此代价极高。BlobDB 的做法是：**大 value 单独写进 blob 文件，SST 里只留一条 `kTypeBlobIndex`（0x11）指向它**，压实时不再重写 value。选项全部在 `ColumnFamilyOptions`（`advanced_options.h`）而非独立的 blob 头文件：

| 选项 | 默认 | 行号 | 含义 |
| :--- | :--- | :--- | :--- |
| `enable_blob_files` | `false` | `:1082` | 总开关 |
| `min_blob_size` | 0 | `:1094` | 超过该字节数的 value 才外置 |
| `blob_file_size` | 256 MB | `:1103` | 单个 blob 文件大小 |
| `blob_compression_type` | `kNoCompression` | `:1112` | blob 独立压缩 |
| `enable_blob_garbage_collection` | `false` | `:1134` | 是否重定位 blob 以回收空间 |
| `blob_garbage_collection_age_cutoff` | 0.25 | `:1145` | 只处理最老 25% 的 blob |
| `blob_garbage_collection_force_threshold` | 1.0 | `:1157` | 放大率超阈值时强制 GC |
| `blob_compaction_readahead_size` | 0 | `:1164` | 读 blob 的预读 |
| `blob_file_starting_level` | 0 | `:1179` | 从哪一层开始生成 blob |
| `prepopulate_blob_cache` | `kDisable` | — | 提前把 blob 装入缓存 |

v11 另有两个实验项 `enable_blob_direct_write = false` 与 `blob_direct_write_partitions = 1`，限制很硬：只支持有序的单 memtable 写路径，且 WAL 回放不支持处于活动状态的 direct-write blob 文件。

取舍要看清：键值分离显著降低写放大与 SST 体积，但一次点查可能变成「读 SST 索引 + 读 blob」两跳，读放大上升；而 blob 的 GC（`enable_blob_garbage_collection`）默认关闭，意味着**空间放大要靠自己安排压实来回收**。

## Links

- [RocksDB](/docs/CS/DB/RocksDB/RocksDB.md)
- [Read Path](/docs/CS/DB/RocksDB/Read_Path.md)
- [Compaction](/docs/CS/DB/RocksDB/Compaction.md)
- [LSM-Tree](/docs/CS/Algorithms/tree/LSM.md)
- [Bloom Filter](/docs/CS/DB/LevelDB/BloomFilter.md)
- [Write Path](/docs/CS/DB/RocksDB/Write_Path.md)

## References

1. [RocksDB Wiki: Block Cache](https://github.com/facebook/rocksdb/wiki/Block-Cache)
2. [RocksDB Wiki: BlobDB](https://github.com/facebook/rocksdb/wiki/BlobDB)
3. [RocksDB source: include/rocksdb/table.h](https://github.com/facebook/rocksdb/blob/v11.8.1/include/rocksdb/table.h)
4. [RocksDB source: include/rocksdb/cache.h](https://github.com/facebook/rocksdb/blob/v11.8.1/include/rocksdb/cache.h)
5. [RocksDB source: include/rocksdb/filter_policy.h](https://github.com/facebook/rocksdb/blob/v11.8.1/include/rocksdb/filter_policy.h)
