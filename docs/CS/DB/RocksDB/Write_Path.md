## Introduction

RocksDB 的写路径是它全部性能故事的起点：**顺序追加 WAL + 内存有序结构 + 后台压实**。这条路上同时挂着持久性保证、崩溃恢复、group commit 的吞吐优化，以及最著名的运维陷阱——写停顿（write stall）。本页全部符号与默认值取 v11.8.1 源码。

## Write Path Step by Step

一次 `DB::Write` 在 `DBImpl::WriteImpl`（`db/db_impl/db_impl_write.cc:867`）里按如下顺序走完：

1. **`PreprocessWrite`**（:2101）：处理 WAL 轮转（`SwitchWAL`）、`WriteBufferManager` 触发的 flush、`flush_scheduler` 里排队的列族 flush，以及最关键的 `DelayWrite`（:2813）——写停顿的等待就发生在这里，**在写 WAL 之前**，所以被限速的写不会污染日志。
2. **`WriteThread::JoinBatchGroup`**（:1099）：进入 writer 队列。
3. **`EnterAsBatchGroupLeader`**（:1195）：抢到 leader 身份的线程把队列后面的 writer 吸收成一个 batch group。
4. **先写 WAL**（`ConcurrentWriteGroupToWAL`，:1374）：整个 group 的 batch 合并成一次（或少数几次）日志写入。
5. **再写 memtable**（`WriteBatchInternal::InsertInto`，:1451）：把 group 内每个 batch 逐条插入各自列族的 memtable。
6. **`ExitAsBatchGroupLeader`**：leader 替 follower 完成回调并唤醒等待者。

**WAL 先于 memtable** 这个顺序不是可选项：memtable 是可丢的内存结构，WAL 是不可丢的磁盘记录。反过来写会在「日志未落地但数据已可见」的瞬间崩溃时留下无法恢复的状态。

序号（sequence number）在同一条路径上分配：batch 内所有记录共享一个递增序号区间。恢复与读可见性用的是 **`GetLastPublishedSequence()`** 而不是「最后写入的序号」——区别在没有提交的 batch 与被拆开的 prepared transaction（见 [Transactions](/docs/CS/DB/RocksDB/Transactions.md)）。

## Group Commit and WriteOptions

group commit 的合并规模有上限：`max_write_batch_group_size_bytes` 默认 **1 MB**（`options.h:1449`）；并且当 leader 自身小于该值的 1/8 时，只允许再吸收约 1/8 的量——这个细节决定了「小写高并发」能攒批、而「单条大写」不会把别人的写拖成一坨。

`WriteOptions` 的六个字段决定了单次写的持久性与延迟契约：

| 字段 | 默认 | 语义与代价 |
| :--- | :--- | :--- |
| `sync` | `false` | 不做 `WritableFile::Sync`。**进程崩溃不丢数据，整机/掉电崩溃会丢**未刷盘的日志尾部 |
| `disableWAL` | `false` | 关掉日志换吞吐。注释明确警告：Backup 依赖 WAL 备份未 flush 的 memtable，关 WAL 就必须 `flush_before_backup=true` |
| `no_slowdown` | `false` | 置 true 时，遇到写停顿**立即返回** `Status::Incomplete("Write stall")`（:2820, :2861）而不等待 |
| `low_pri` | `false` | 走低优先级限速通道（默认 1 MB/s 的独立 limiter，`write_controller.h:25`；wiki 记为 5.6 起），适合后台批量导入别挤占前台 |
| `ignore_missing_column_families` | `false` | batch 里含不存在 CF 时是否报错 |
| `memtable_insert_hint_per_batch` | `false` | 每个 batch 取一次 skiplist 插入提示，顺序写同一段 key 空间时省开销 |

`FlushOptions` 则是 `wait=true, allow_write_stall=false, force_atomic_flush=false, listener_wait=false`（`options.h:2600`）。`allow_write_stall=false` 意味着手动 flush 会先等 compaction 追上，避免把用户推入停顿。

## MemTable and Flush

memtable 是 `class MemTable final : public ReadOnlyMemTable`（`memtable.h:579`），底层 `MemTableRep` 默认由 **SkipListFactory** 提供（wiki/MemTable；`options.h:1430` 注明**只有 skiplist 支持并发写**，换成别的实现等于放弃这条路径的并行性）。内存来自 `ConcurrentArena`（:914）。

一个命名陷阱值得单独写：**v11 里没有 `ImmutableMemTable` 这个类**（只有 `ImmutableMemTableOptions`，`memtable.h:50`）。所谓「immutable memtable」指的是已经封存、挂进 `MemTableListVersion` 等待 flush 的 `MemTable` 对象。旧文章按类名去找会找不到。

关键默认值：

| 选项 | 默认 | 含义 |
| :--- | :--- | :--- |
| `write_buffer_size` | 64 MB（`options.h:191`） | 单个 memtable 上限，到点封存并 flush |
| `max_write_buffer_number` | 2（`advanced_options.h:271`） | mem + imm 总数上限，撞上就停写 |
| `min_write_buffer_number_to_merge` | 1（:283） | flush 前先在内存里合并几个 memtable，换更少的 L0 文件 |
| `max_write_buffer_size_to_maintain` | 0（:330） | 保留旧 memtable 内存复用，减少分配抖动 |
| `db_write_buffer_size` | 0（`options.h:1255`） | 跨列族的 memtable 总量上限 |
| `write_buffer_manager` | `nullptr`（:1267） | 与上一项**二选一**，设置后优先生效，还能 `allow_stall`（`write_buffer_manager.h:50`） |

flush 的产物是一个 L0 的 SST 文件，同时产生一条 `VersionEdit` 落 MANIFEST，并安装新的 `SuperVersion`（见下一节）。L0 文件堆积会直接触发压实与写停顿，两者是同一件事的两端（见 [Compaction](/docs/CS/DB/RocksDB/Compaction.md)）。

## WAL

WAL 文件命名为 `<db>/%06llu.log`（`util/filename.cc:78`），被归档时搬到 `<db>/archive/%06llu.log`（:108）。物理格式是分块记录流：块大小 `kBlockSize = 32768`，普通记录头 7 字节、可回收记录头 11 字节（`db/log_format.h:51-57`）；记录类型里除了 `kRecyclable*`，还有 `kSetCompressionType = 9` 与 `kPredecessorWALInfoType = 130`。

参数上有三个坑：

- **`WAL_ttl_seconds = 0` 与 `WAL_size_limit_MB = 0`**（`options.h:1116-1117`）——注意字段名后缀是 **`_MB`** 不是 `_bytes`（很多文章写错）。而且这一对**只作用于归档（archived）的 WAL**；两者都为 0 时，作废的 WAL 直接删除，不做归档保留。
- **`max_total_wal_size = 0`** 时按动态值取 `Σ(write_buffer_size × max_write_buffer_number) × 4`，且**只在列族数 > 1 时生效**（`options.h:808-828`）。它的作用是：某个 CF 长期不写、memtable 不满，其 WAL 就无法释放，超过这个总量就强制 flush 那些「 stale 的 CF」来回收日志。
- `manual_wal_flush = false`（:1563）：置 true 时日志写入不立即下发到文件系统，由 `FlushWAL()` 控制，换吞吐换持久性窗口。

同步相关的三个字段是 `bytes_per_sync = 0`（**明确不适用于 WAL**）、`wal_bytes_per_sync = 0`、`strict_bytes_per_sync = false`（:1324/:1334/:1355）——想平滑大文件的 fsync 抖动，WAL 得单独用 `wal_bytes_per_sync`。日志压缩由 `wal_compression = kNoCompression`（:1570）控制。

**WAL 与元数据的一致性校验**：`track_and_verify_wals_in_manifest = false`（:671）仍在，功能是把每个 WAL 事件写进 `VersionEdit`、经 `VersionSet::LogAndApply` 落到 MANIFEST（wiki/Track-WAL-in-MANIFEST），从而检测日志丢失；v11 新增 EXPERIMENTAL 的 `track_and_verify_wals = false`（:691）自称是其替代者，但只跟踪**已关闭**的 WAL，`SyncWAL()`/`sync=true` 不计入，且不支持 Secondary Instance。另有两个文件复用的开关：`recycle_log_file_num = 0`（:978）与 EXPERIMENTAL 的 `async_wal_precreate = false`（:990，二者在 sanitize 时互斥）。

## SuperVersion and MANIFEST

写路径每次 flush/compaction 之后，元数据要落两件事：

- `VersionSet::LogAndApply`（`version_set.cc:1276`）把 `VersionEdit` 应用为新 `Version`、持久化到 MANIFEST、并安装新 `SuperVersion`。它**会中途释放 `mu`**，且要求无并发调用——这是「为什么 flush 与 compaction 必须串行化到同一个临界区」的根因。
- `SuperVersion`（`column_family.h:207`）= `{cfd, mem, imm, current, mutable_cf_options, version_number, write_stall_condition}`。读侧只要拿到它就不会看到半个新版本。

MANIFEST 自身的管理在 v11 有语义变化：`max_manifest_file_size` 名义默认 1 GB（`options.h:1015`），但已从「硬上限」改为**自动调优的下限**，实际滚动大小 = `max(该值, 压缩后估计大小 × (1 + max_manifest_space_amp_pct/100))`，新增项 `max_manifest_space_amp_pct = 500`（:1094）。文件名 `MANIFEST-%06llu`，`CURRENT` 文件只存当前 MANIFEST 名。`VersionEdit` 的 tag 里除了 `kNewFile4 = 103`、`kColumnFamily = 200`、`kColumnFamilyAdd/Drop = 201/202`、`kInAtomicGroup = 300`，还有 `kTagSafeIgnoreMask = 1 << 13`——带这个位标记的 tag 遇到不认识的版本会被安全忽略，是 RocksDB 前向兼容 MANIFEST 的机制。

## Write Stall

这是 RocksDB 最常见的故障形态，也是它的自保机制：**当后台跟不上前台时，宁可让写变慢或停住，也不让内存与 L0 无限膨胀**。判定条件与顺序（`column_family.cc:1048` 起）：

| 归因 | 条件 | 结果 |
| :--- | :--- | :--- |
| memtable 积压 | `imm 数 ≥ max_write_buffer_number` | **stop** |
| memtable 积压（缓冲较深时） | `max_write_buffer_number > 3` 且 `imm ≥ max-1` | delay |
| L0 文件数 | `L0 ≥ level0_stop_writes_trigger`（36） | **stop** |
| L0 文件数 | `L0 ≥ level0_slowdown_writes_trigger`（20） | delay |
| 压实积压 | `pending_bytes ≥ hard_pending_compaction_bytes_limit`（256 GiB） | **stop** |
| 压实积压 | `pending_bytes ≥ soft_pending_compaction_bytes_limit`（64 GiB） | delay |

其中后两组都以 `!disable_auto_compactions` 为前提（`column_family.cc:1016-1025`）——**关掉自动压实等于把停写风险从 L0 挪到别处，而不是消除它**。

delay 的执行者是 `WriteController`：默认限速 32 MB/s，每 1 ms 补充 credit、最小延迟 1 ms（`write_controller.cc:60-97`）；`delayed_write_rate = 0` 时取 rate limiter 的速率，没有 limiter 则落到 16 MB/s（`options.h:1373-1377` 注释）。还有一个「near stop」概念：`L0 ≥ stop - 2`，或超出 soft 的部分大于 `3/4 × (hard - soft)`，用于提前预警。

最需要记住的一点：**判定按列族做，限速却由全实例共享的 `WriteController` 执行**。所以一个冷列族的 compaction 积压会让所有热列族一起变慢。定位时先确认是哪个 CF 触发的（`rocksdb.stall-micros`、`WriteStallInfo` event listener），再决定给谁加后台资源。

## Pitfalls

- `disableWAL` 只适合「数据可从别处完整重建」的批量导入；配 Backup/Checkpoint 使用时必须先 flush。
- `sync = false` 给的是「进程级」持久性，不是掉电级。要掉电安全得 `sync = true`，或依赖上层复制。
- 前台延迟敏感的服务应当设 `no_slowdown = true`，让写失败快速返回、由业务侧决定重试或降级，而不是让请求线程卡在 `DelayWrite` 里。
- 列族很多时记得核算 `db_write_buffer_size` / `max_total_wal_size`，否则「某个 CF 长期不写」会长期占着 WAL。
- `Options::parallelism` 这个字段**不存在**；要调并发只有 `DBOptions::IncreaseParallelism(int total_threads = 16)`（`options.h:588`）与 `max_background_jobs`。

## Links

- [RocksDB](/docs/CS/DB/RocksDB/RocksDB.md)
- [Column Families](/docs/CS/DB/RocksDB/Column_Families.md)
- [Compaction](/docs/CS/DB/RocksDB/Compaction.md)
- [Read Path](/docs/CS/DB/RocksDB/Read_Path.md)
- [WAL](/docs/CS/DB/Concept/WAL.md)
- [Transactions](/docs/CS/DB/RocksDB/Transactions.md)

## References

1. [RocksDB Wiki: Write Stalls](https://github.com/facebook/rocksdb/wiki/Write-Stalls)
2. [RocksDB Wiki: MemTable](https://github.com/facebook/rocksdb/wiki/MemTable)
3. [RocksDB Wiki: MANIFEST](https://github.com/facebook/rocksdb/wiki/MANIFEST)
4. [RocksDB Wiki: Low Priority Write](https://github.com/facebook/rocksdb/wiki/Low-Priority-Write)
5. [RocksDB source: db_impl_write.cc](https://github.com/facebook/rocksdb/blob/v11.8.1/db/db_impl/db_impl_write.cc)
