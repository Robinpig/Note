## Introduction

RocksDB 是嵌入式的：没有 DBA、没有 `pg_dump`、没有主从复制面板。**备份、恢复、灌数据、过期回收、观测，全都发生在你自己的进程里**。这一页把这些「运维能力」按官方接口的真实语义整理出来（v11.8.1），并给出按症状排查的入口。

## Checkpoint: Second-Scale Snapshots on One Filesystem

```
Checkpoint::Create(db, &ptr);                              // utilities/checkpoint.h:129
ckpt->CreateCheckpoint(dir, log_size_for_flush = 0,
                       sequence_number_ptr = nullptr);     // :152
```

核心机制是**硬链接**：与数据库同文件系统时，SST 与 blob 文件只是被链接到新目录，不复制数据，因此创建几乎瞬时、也不额外占盘（:135）。这也解释了它的两个边界条件：跨文件系统就退化成真复制；而 checkpoint 是**一致性**的——正在进行的 flush/compaction 不会污染它。

一个必须知道的特例：**存在 2PC prepared 事务时，创建 checkpoint 必定触发一次 flush**（:145），因为不能只链接「一半已提交」的日志状态。

v11 正在把 checkpoint 与 backup 收敛到同一套新接口：`CheckpointOrBackupEngineOptions`、`CreateCheckpointOptions`（:77）以及返回 `IOStatus` 的新签名 `CreateCheckpoint(..., sequence_number_ptr, options)`（:105）。旧签名仍并存，但新代码走新的。

## BackupEngine: Durable Backups Across Filesystems

`BackupEngine::Open`（`utilities/backup_engine.h:684`）→ `CreateNewBackup(CreateBackupOptions, db, &backup_id)`（:577）或 `CreateNewBackupWithMetadata`（:557/562），保留策略用 **`PurgeOldBackups(num_backups_to_keep)`**（:695，注意大小写，不是小写下划线的 `purge_old_backups`）。

它的价值在**跨设备**：备份目录可以和 DB 不同文件系统，内部按「shared / exclusive」两类文件组织去重。关键选项 `BackupEngineOptions::share_files_with_checksum(true)`（:228）配合 `share_files_with_checksum_naming`（:186）——按校验和共享文件，去重率高，但要求 SST 不被原地改动；恢复侧另有 `restore_rate_limiter`（:88）限制读带宽。

**Checkpoint 与 Backup 的取舍**：前者是同盘、硬链接、瞬时、不能跨设备；后者可跨设备、可增量去重、要真复制数据。二者都依赖 WAL 备份尚未 flush 的 memtable 内容——所以**用了 `disableWAL` 就必须 `flush_before_backup = true`**（见 [Write_Path](/docs/CS/DB/RocksDB/Write_Path.md)），否则备份里就是缺的数据。

## External File Ingestion

`SstFileWriter` 在库外生成合法 SST，再用 `DB::IngestExternalFile` 原子挂进某列族的某一层的元数据里，绕开 memtable 与 WAL，也避免灌数据把 L0 打满触发写停顿。

`SstFileWriter` 支持 `Put` / `PutEntity` / `Merge` / `Delete` / `DeleteRange` / `Finish`。两个版本断点：**`Add()` 与构造参数 `skip_filters` 已在 11.0.0 移除**（`HISTORY.md:170`）；要把 blob 内嵌进 SST 需要 `format_version >= 7`（`sst_file_writer.h:30-37`）。

`IngestExternalFileOptions` 的实测默认值（`options.h`）：

| 选项 | 默认 | 行号 | 含义 |
| :--- | :--- | :--- | :--- |
| `move_files` | `false` | `:2840` | 是否移动而非复制文件；为 true 后源文件不能再被使用 |
| `link_files` | `false` | `:2843` | 10.x 新增，硬链接方式摄取（比 move 更保守） |
| `failed_move_fall_back_to_copy` | `true` | `:2846` | move 失败自动退回复制 |
| `snapshot_consistency` | `true` | `:2849` | 为 true 时会 flush memtable，保证已有快照仍能读到旧状态 |
| `allow_global_seqno` | `true` | `:2864` | 允许把文件内序号改成全局序号（跨列族原子性的代价开关） |
| `allow_blocking_flush` | `true` | `:2870` | 允许为摄取而 flush |
| `ingest_behind` | `false` | `:2878` | 专门给历史数据回填：插到所有已有 key 之后，配合 `allow_ingest_behind` 打开库 |
| `write_global_seqno` | `false` | `:2888` 区 | 是否写全局序号标记 |
| `fail_if_not_bottommost_level` | `false` | `:2928` | 要求只能落在最底层 |
| `allow_db_generated_files` | `false` | `:2976` | 是否接受非外部生成的文件 |

`ingest_behind` 值得单独记：数仓/回溯场景里「补一年前的数据但不覆盖现有值」正是它的语义，开启要在建库时用 `DBOptions::allow_ingest_behind`。

## TTL and Expiry Reclamation

```
DBWithTTL : public StackableDB              // utilities/db_ttl.h:46
Status OpenTtlDB(options, name, dbptr, ttl, ...);   // :53 单列族 / :59 多列族
```

实现方式很朴素：**每个 value 后面追加 4 字节过期时间戳**（:41），过期数据在 **compaction 时才被删除**（:28 的注释），可用 `SetTtl()`（:62/64）改周期、`GetTtl()`（:66）读回。

这带来一个常见误解要破除：**TTL 到期不等于空间释放**。没被压实到的数据仍在 SST 里占盘、仍参与读路径的跳过；要立刻回收就得安排一次压实（`CompactRange` 或调低 `ttl` / `periodic_compaction_seconds`，见 [Compaction](/docs/CS/DB/RocksDB/Compaction.md)）。FIFO 的 `age_for_warm` 已 DEPRECATED，同类需求改用 `file_temperature_age_thresholds`。

## Secondary Instance: Read-Only Follower

`DB::OpenAsSecondary`（`db.h:257`，列族版 :287 区）打开一个**只读副本实例**，通过 `TryCatchUpWithPrimary()` 追主实例的新版本。用途是「不干扰主写入的前提下做备份扫描、分析、校验」。特性边界：secondary **不会做 flush/compaction**（自动关闭），多个 secondary 可以共存（:236），但**主实例之后新建的列族会被 secondary 忽略**（:268-272）。

## Observability

**属性**：`DB::GetProperty` / `GetMapProperty` / `GetIntProperty`（`db.h:1574/1582/1635`），键名统一 `rocksdb.` 前缀（`db/internal_stats.cc:247`）。高频项：`num-files-at-level<N>`、`cfstats` / `defaultcf.stats`、`mem-table-flush-pending`、`compaction-pending`、`num-running-compactions`、`estimate-num-keys`、`estimate-live-data-size`、`estimate-pending-compaction-bytes`、`estimate-oldest-key-time`、`live-sst-files-size`、`background-errors`、`num-snapshots`。

**计数器与直方图**：`CreateDBStatistics()`（`statistics.h:974`）配 `histogram_type`。实测存在的 ticker 名（别照旧文章抄错）：`BLOCK_CACHE_HIT`（:41）、`BLOCK_CACHE_BYTES_READ`（:71）、`SIM_BLOCK_CACHE_HIT`（:135）、`NUMBER_KEYS_WRITTEN`（:169）、`BYTES_READ`（:181）、`STALL_MICROS`（:205，写停顿的直接指标）、`NUMBER_MULTIGET_BYTES_READ`（:213）、`WAL_FILE_SYNCED`（:224）、`COMPACT_READ_BYTES`（:242）、`FLUSH_WRITE_BYTES`（:244），以及读放大估算对 `READ_AMP_ESTIMATE_USEFUL_BYTES` / `READ_AMP_TOTAL_READ_BYTES`（:309/310）。**`NUMBER_DELETION_SKIPPED` 不存在**，对应的「跳过多少删除标记」在 PerfContext 里。

**线程级细粒度**：载体类型是 `PerfContext`，头文件 **`include/rocksdb/perf_context.h`（不是 `perf_event.h`）**：`user_key_comparison_count`（:75）、`block_cache_hit_count`（:76）、`block_read_count`（:77）、`block_cache_index_hit_count`（:83）、`index_block_read_count`（:89）、`filter_block_read_count`（:91）、`compression_dict_block_read_count`（:92）、`internal_key_skipped_count`（:143）、`internal_delete_skipped_count`（:151），还能按层看（`PerfContextByLevel`，:61）。开关是 `SetPerfLevel()`（`perf_level.h:54`），默认级别 `kEnableCount = 2`（:34）——**级别不够时这些计数全为 0，是最常见的「查不到数据」**。

**事件回调**：字段名是 `DBOptions::listeners` / `Options::listeners`（:1359 / :3148），**没有 `EventListeners` 这个类型**。监听 flush/compaction/stall 事件就实现 `EventListener`。

## IO and the File System

| 选项 | 默认 | 出处 | 说明 |
| :--- | :--- | :--- | :--- |
| `use_direct_reads` | `false` | `options.h:1153` | 读绕过 OS page cache（数据已有 block cache 时省双缓存） |
| `use_direct_io_for_flush_and_compaction` | `false` | `:1196` | 后台写走 direct IO |
| `allow_mmap_reads` | `false` | `:1136` | mmap 读（配 `readOnly` 场景收益明显） |
| `allow_mmap_writes` | `false` | `:1141` | mmap 写 |
| `use_adaptive_mutex` | `false` | `:1299` | 高争用下自旋 |
| `allow_fallocate` | `true` | `:1207` | 预分配；`EnvOptions` 里另有一项同名开关（env.h:97） |
| `bytes_per_sync` / `wal_bytes_per_sync` / `strict_bytes_per_sync` | 0 / 0 / `false` | `:1324/:1334/:1355` | 平滑大文件的 fsync 抖动 |

注意 `fallocate_with_keep_size_hint` 这个名字**不存在**，真实字段是 `EnvOptions::fallocate_with_keep_size = true`（`env.h:131`）。

架构上 `class Env : public Customizable`（`env.h:151`）**并不是 `FileSystem` 的子类**，而是持有一个 `file_system_`（:835）并通过 `GetFileSystem()`（:821）暴露出来；`Env::Name()` 已注明 "Deprecated. Will be removed in a major release."。至于「Env 将被 FileSystem 完全取代」这句话，在 v11.8.1 的头文件里找不到明文，属于社区讨论而非文档承诺。

## Troubleshooting by Symptom

- **写卡住 / `Incomplete("Write stall")`** → 先定归因（L0 文件数、pending compaction bytes、memtable 积压），再看是哪个列族：`STALL_MICROS` + `compaction-pending` + `num-files-at-level0`。细节见 [Write_Path](/docs/CS/DB/RocksDB/Write_Path.md)。
- **点查毛刺** → 确认 `filter_policy` 是否真的配了（默认是 `nullptr`！）、`internal_key_skipped_count` / `internal_delete_skipped_count` 是否高、`block_cache_hit_count` 比例。见 [Read_Path](/docs/CS/DB/RocksDB/Read_Path.md) 与 [Table_Format](/docs/CS/DB/RocksDB/Table_Format.md)。
- **盘占用远超有效数据** → 空间放大：未释放的快照/长事务钉住旧版本、TTL 未压实、底部压实被跳过、BlobDB GC 关闭。
- **打开很慢** → MANIFEST 重放与列族数量；考虑减少列族或拆实例（见 [Column_Families](/docs/CS/DB/RocksDB/Column_Families.md)）。
- **内存超预算** → `列族数 × write_buffer_size × max_write_buffer_number` 加上 block cache；用 `WriteBufferManager` 统一封顶。

## Links

- [RocksDB](/docs/CS/DB/RocksDB/RocksDB.md)
- [Write Path](/docs/CS/DB/RocksDB/Write_Path.md)
- [Compaction](/docs/CS/DB/RocksDB/Compaction.md)
- [Table Format](/docs/CS/DB/RocksDB/Table_Format.md)
- [Column Families](/docs/CS/DB/RocksDB/Column_Families.md)
- [Transactions](/docs/CS/DB/RocksDB/Transactions.md)

## References

1. [RocksDB Wiki: Checkpoints](https://github.com/facebook/rocksdb/wiki/Checkpoints)
2. [RocksDB Wiki: Statistics](https://github.com/facebook/rocksdb/wiki/Statistics)
3. [RocksDB Wiki: RocksDB Tuning Guide](https://github.com/facebook/rocksdb/wiki/RocksDB-Tuning-Guide)
4. [RocksDB source: utilities/backup_engine.h](https://github.com/facebook/rocksdb/blob/v11.8.1/include/rocksdb/utilities/backup_engine.h)
5. [RocksDB source: include/rocksdb/statistics.h](https://github.com/facebook/rocksdb/blob/v11.8.1/include/rocksdb/statistics.h)
