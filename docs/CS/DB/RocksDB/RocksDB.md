## Introduction

RocksDB 是一个**嵌入式的持久化 KV 存储库**，以库的形式链接进应用进程，没有独立的服务器进程与网络协议栈。它由 Facebook 在 Google [LevelDB](/docs/CS/DB/LevelDB/LevelDB.md)（Sanjay Ghemawat 与 Jeff Dean）的代码基础上大规模改造而来，保留 LSM-tree 的基本形态，把 LevelDB 当成「能跑就行」的部分几乎全部重写或参数化。公开案例里它是 MyRocks、TiDB/TiKV、CockroachDB、Kafka Streams 这类系统的本地存储底座——共同诉求都是**写多、机器本地 SSD、要可控的延迟而非花哨的查询能力**。

本套笔记的**版本锚点是 v11.8.1**（2026 年 8 月发布）。这个选择不是装饰：RocksDB 的默认值与符号名在这几年变化极剧烈，`level_compaction_dynamic_level_bytes` 的默认值已经翻转为 true、`block_cache` 为空时的默认实现已从 LRU 换成 HyperClockCache、`format_version` 默认到了 7、`filter_policy` 的默认值**其实是 `nullptr`（即默认不建 Bloom filter）**，而 `CompactionFilterV2`、`OverwriteKeyStatus`、`kZSTDNotFinalCompression`、`block_cache_compressed` 这些在旧文章里频繁出现的名字**已经被删除**。凭印象写 RocksDB 一定会写错，所以以下每个符号与数字都取该 tag 的源码，标出所在文件。

## Design Tension: Three Amplifications

理解 RocksDB 的全部配置，只需要先抓住一条因果链：**LSM 用「顺序写换随机写」，代价是把混乱推给了读和空间**（原理见 [LSM-Tree](/docs/CS/Algorithms/tree/LSM.md)）。三种放大互相拉扯，几乎所有调优都是在选边站：

- **写放大（WAF）**：一份数据被真实写到磁盘几次。flush 一次、compaction 每轮一次，逐层下沉就会被反复重写。
- **读放大（RAF）**：一次点查要查几个文件。同一个 key 的旧版本散在 memtable 与多层 SST 里，读的时候必须逐层归并、还可能被删除标记挡住。
- **空间放大（SA）**：磁盘上占了多少字节 vs 有效数据多少字节。旧版本与 tombstone 在被 compaction 清掉之前一直占地方。

LevelDB 把这条曲线钉死成一层不变的策略，RocksDB 的价值就在于**把三轴分别做成可配置的**：Compaction 风格与触发阈值管写放大，Bloom filter / 分区索引 / 缓存管读放大，TTL、`bottommost_level_compaction`、BlobDB 的 GC 管空间放大。三个方向的实现分别拆在 [Write_Path](/docs/CS/DB/RocksDB/Write_Path.md)、[Read_Path](/docs/CS/DB/RocksDB/Read_Path.md)、[Compaction](/docs/CS/DB/RocksDB/Compaction.md)、[Table_Format](/docs/CS/DB/RocksDB/Table_Format.md) 四篇里；在此之上，多 key 的 ACID 怎么靠 [Transactions](/docs/CS/DB/RocksDB/Transactions.md) 实现、以及没有 DBA 的情况下如何备份与灌数据见 [Operations](/docs/CS/DB/RocksDB/Operations.md)。

## Architecture

进程内的角色划分如下（左到右大致是写请求经过的顺序）：

```
Put/Write → WriteThread(batch group) → WAL(.log) → MemTable(skiplist)
                                                    │ flush
                                       ImmutableMemTable(MemTableList)
                                                    │
        SuperVersion { mem, imm, current }  ←──────┴── Version(SST 文件集)
                                                    │            ↑
   Get/NewIterator ────────────────────────────────┘        VersionEdit
                                                    │            ↑
                            L0..Ln SST (BlockBasedTable) ── MANIFEST + CURRENT
                                                    ↑
                                    background: flush / compaction (WriteController 限速)
```

四个关键结构值得先记住名字，后面几篇都围绕它们展开：

- **`MemTable`**：内存中的有序可变结构，默认 skiplist（`memtable.h:579`，`ConcurrentArena` 分配）。写请求在 WAL 之后进这里。
- **`Version` / `VersionEdit` / `MANIFEST`**：一个 `Version` 是「某一刻该列族拥有哪些 SST 与 blob 文件」的不可变快照；每次 flush/compaction 产出一条 `VersionEdit` 追加进 `MANIFEST` 文件，`CURRENT` 单文件记录当前生效的 MANIFEST 名（见 [WAL](/docs/CS/DB/WAL.md) 里对元数据快照的同类处理）。
- **`SuperVersion`**：把 `{mem, imm, current, mutable_cf_options, version_number}` 打包成一个原子可读视图（`column_family.h:207`），读路径靠它一次拿全、避免逐把加锁；线程本地缓存命中时**连引用计数都不做**。
- **`WriteController`**：全 DB 共享的写限速/停写仲裁者。一个列族触发停顿会波及整个实例，这是 RocksDB 最著名的运维陷阱（详见 [Write_Path](/docs/CS/DB/RocksDB/Write_Path.md)）。

## Data Model

RocksDB 只认**字节序的 key → 字节序的 value**，没有类型、没有 schema、没有 SQL。有序性由 `Comparator` 决定，内部键再叠一层序号：

```
InternalKey = user_key + (sequence << 8 | ValueType)      // dbformat.h:185
kMaxSequenceNumber = (1 << 56) - 1                        // dbformat.h:129
```

`ValueType` 低 8 位表达操作类型，实测取值包括 `kTypeValue=0x1`、`kTypeDeletion=0x0`、`kTypeMerge=0x2`、`kTypeSingleDeletion=0x7`、`kTypeRangeDeletion=0xF`（只进 meta block）、`kTypeBlobIndex=0x11`、`kTypeWideColumnEntity=0x16`、`kTypeValuePreferredSeqno=0x18`（`dbformat.h:41`）。同一 user key 下**序号大的排前面**，于是「取最新可见版本」退化成一次顺序读；可见性由快照序号决定。

值侧有三个超出「字节串」的东西：**MergeOperator**（把「读-改-写」下推成 append 一个 operand，见 [Read_Path](/docs/CS/DB/RocksDB/Read_Path.md)）、**wide columns**（`PutEntity`/`GetEntity`，一个 key 带多个命名列）、以及 **BlobDB 的键值分离**（大 value 落到独立 blob 文件，SST 里只留 `kTypeBlobIndex`，见 [Table_Format](/docs/CS/DB/RocksDB/Table_Format.md)）。

## Column Families

列族是 RocksDB 相对 LevelDB 最重要的结构性增量：**一个 DB 实例、多个列族，共享一个 WAL 与各 CF 独立的 memtable / SST / compaction**。这样跨 CF 的原子写只需一次 WAL 追加，而 compaction 又能按 CF 分别调参。默认存在名为 `default` 的列族（`db.h:64`）。

代价要提前知道：内存上限按 `CF 数 × write_buffer_size × max_write_buffer_number` 线性放大；CF 越多，老 WAL 越难被判定为「所有 CF 都已 flush」而迟迟不能删；写停顿的判定虽然按 CF 计算，限速却由全局 `WriteController` 统一执行——**一个 CF 积压会拖慢整个实例**。细节见 [Column_Families](/docs/CS/DB/RocksDB/Column_Families.md)。

## Default Values Worth Memorizing

以下均为 v11.8.1 源码实测值。列在这里是因为 RocksDB 的行为几乎完全由这几个数字决定，而且**旧资料上的数字很多已经不对**：

| 选项 | 默认值 | 出处 | 为什么关键 |
| :--- | :--- | :--- | :--- |
| `write_buffer_size` | 64 MB | `options.h:191` | 单个 memtable 上限，直接决定 flush 频率 |
| `max_write_buffer_number` | 2 | `advanced_options.h:271` | 超过即停写；给 compaction 留多少缓冲 |
| `level0_file_num_compaction_trigger` | 4 | `options.h:255` | L0 攒够几个文件开始压实 |
| `level0_slowdown_writes_trigger` | 20 | `advanced_options.h:547` | 慢写阈值 |
| `level0_stop_writes_trigger` | 36 | `advanced_options.h:554` | 停写阈值 |
| `soft/hard_pending_compaction_bytes_limit` | 64 GiB / 256 GiB | `advanced_options.h:709,717` | 积压字节触发的软/硬停 |
| `num_levels` | 7 | `advanced_options.h:538` | 层级数 |
| `target_file_size_base` | 64 MB | `advanced_options.h:568` | SST 目标大小 |
| `max_bytes_for_level_base` | 256 MB | `options.h:303` | L1 容量基准 |
| `max_bytes_for_level_multiplier` | 10 | `options.h:671` | 逐层 10 倍，写放大的来源 |
| `level_compaction_dynamic_level_bytes` | **true** | `advanced_options.h:666` | 默认已翻转，旧文档写 false 已过时 |
| `compaction_pri` | `kMinOverlappingRatio` | `advanced_options.h:725` | 优先挑重叠最小的文件压实 |
| `compression` | `kLZ4Compression`（编译期决定，退化 Snappy/None） | `options.h:195` | 别当常量事实写 |
| `max_background_jobs` | 2 | `options.h:900` | 后台线程预算；`max_background_compactions/flushes` 已 DEPRECATED |
| `delayed_write_rate` | 0 → 实际 16 MB/s | `options.h:1383` | 慢写限速 |
| `max_subcompactions` | 1（不切分） | `options.h:926` | 压实并行度 |
| `ttl` / `periodic_compaction_seconds` | auto（解析为 30 天） | `advanced_options.h:894,942` | 特殊哨兵值，0 才是关闭 |
| `block_size` | 4 KiB | `table.h:400` | 数据块粒度，读放大与解压成本的折中 |
| `filter_policy` | **`nullptr`（默认无 Bloom）** | `table.h:590` | 反直觉但极其重要 |
| `format_version` | 7 | `table.h:739` | 10.11.0 起默认；决定可用特性与旧 reader 兼容性 |
| `block_cache` | `nullptr` → 内部建 32 MB **HyperClockCache** | `table.h:390`、HISTORY `10.7.0` | 默认实现已不是 LRU |

## Tuning: Where to Look First

按「症状 → 先看什么」的路径排查，比背参数有效：

- **写入周期性卡住或返回 `Incomplete("Write stall")`** → 看 stall 归因（L0 文件数、pending compaction bytes、memtable 积压三者之一），再决定是加后台线程、提高 `max_write_buffer_number`，还是降低 `level0_file_num_compaction_trigger`。详见 [Write_Path](/docs/CS/DB/RocksDB/Write_Path.md)。
- **点查延迟毛刺、`internal_key_skipped_count` 高** → 大概率是没开 Bloom filter（默认关）、或删除标记/范围删除堆积。详见 [Read_Path](/docs/CS/DB/RocksDB/Read_Path.md)。
- **磁盘占用远大于有效数据** → 空间放大，检查是否底部压实被跳过、TTL 是否只在 compaction 时生效。详见 [Operations](/docs/CS/DB/RocksDB/Operations.md)。
- **大量小 value 更新导致 SST 膨胀** → 上 BlobDB 键值分离。详见 [Table_Format](/docs/CS/DB/RocksDB/Table_Format.md)。

## What RocksDB Adds over LevelDB

LevelDB 的代码骨架还在，但它刻意保持简单的每一处几乎都被扩了。值得单独记住的增量：

| 能力 | LevelDB | RocksDB（证据） |
| :--- | :--- | :--- |
| 表分组 | 无 | Column Families（`db.h` `CreateColumnFamily`） |
| Compaction 策略 | 仅 leveled | leveled / universal / FIFO / none + subcompaction、`compaction_pri` |
| 读侧结构 | 单层 index + 整表 filter | 分区索引与分区 filter、Ribbon filter、`kHashSearch` |
| 缓存 | 进程内 LRU | `LRUCache` / **HyperClockCache（默认）** / Secondary & Tiered Cache |
| 更新语义 | put/delete | 追加 MergeOperator、单删、范围删除、wide columns |
| 事务 | 无（仅原子 WriteBatch） | `TransactionDB` 悲观/乐观、三种 write policy、`WriteBatchWithIndex` |
| 大 value | 混在 SST | BlobDB 键值分离 |
| 运维 | `DestroyDB` 级别 | Checkpoint（硬链接）、BackupEngine、外部 SST 摄取、TTL DB、Secondary Instance |
| 可观测 | 几乎无 | `Statistics` ticker/histogram、`PerfContext`、50+ 个 `rocksdb.*` property |
| IO | 缓冲写 | direct IO、mmap、异步/协程读路径、rate limiter |

一句话概括取舍：**LevelDB 用「什么都不给你选」换来简单，RocksDB 用「什么都可以调」换来性能上限，代价是运维复杂度全部转嫁给使用者。**

## Links

- [LevelDB](/docs/CS/DB/LevelDB/LevelDB.md)
- [LSM-Tree](/docs/CS/Algorithms/tree/LSM.md)
- [H2](/docs/CS/DB/h2/H2.md)
- [DataBases](/docs/CS/DB/DB.md)

## References

1. [RocksDB official site](https://rocksdb.org/)
2. [RocksDB source (tag v11.8.1)](https://github.com/facebook/rocksdb)
3. [RocksDB Wiki: Column Families](https://github.com/facebook/rocksdb/wiki/Column-Families)
4. [RocksDB Wiki: Write Stalls](https://github.com/facebook/rocksdb/wiki/Write-Stalls)
