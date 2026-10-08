## Introduction

[LevelDB](/docs/CS/DB/LevelDB/LevelDB.md) 里最难读的部分不是 memtable 也不是 SSTable，而是**「谁在什么时候被合并、元数据怎么原子地换掉」**这一整套机制：`VersionSet` 负责「当前哪批文件有效」，`Version` 是一个不可变的文件集合快照，`VersionEdit` 是两次状态之间的那一步差分，而 MANIFEST 文件把这些差分顺序记下来，成为崩溃后重建世界的唯一依据。压实（compaction）则是这套元数据变更的**主要生产者**。

本文全部事实锚定 **LevelDB 1.23**（2021-02 发布的最新 tag），符号与行号取自该版本源码。

> [!WARNING]
> **1.23 已经重组了源码目录**，网上大量文章仍在引用旧路径：读侧从 `db/table.cc` 迁到 `table/table.cc` 与 `include/leveldb/table.h`，写侧迁到 `table/table_builder.cc`，`db/block.{h,cc}`、`db/format.{h,cc}`、`db/filter_block.{h,cc}` 全部进了 `table/`；而 **`db/internal_stats.{h,cc}` 已被整个删除**——1.23 里没有 properties block、没有 `SSTABLE_PROPERTIES` 宏、也没有 `TableBuilder::AddProperty`。本文只描述这些新路径下真实存在的符号。

## Version and VersionEdit

`Version`（`db/version_set.h:148-165`）持有一个列族——LevelDB 没有列族概念，即整个库——在某一时刻的全部文件：

```
std::vector<FileMetaData*> files_[config::kNumLevels];   // :154，kNumLevels = 7
Version* next_; Version* prev_;   // 侵入式双向链表，把所有历史版本串起来
int refs_;                        // 引用计数，归零即 delete this（:453-463）
FileMetaData* file_to_compact_;   // 由 seek 计数驱动的压实候选
double compaction_score_; int compaction_level_;   // Finalize() 算出的「本轮该压谁」
```

`FileMetaData`（`db/version_edit.h:18-27`）是 `{refs, allowed_seeks, number, file_size, smallest, largest}`，其中 `allowed_seeks` 初值 `1 << 30`。注意**这里没有 RocksDB 的 `VersionStorageInfo`**：LevelDB 把「文件集合」与「统计信息」混在同一个 `Version` 里，历史版本靠 `dummy_versions_` 链表保命。

`VersionEdit` 是「一次状态变更」的载体，tag 的实测数值（`db/version_edit.cc:14-24`）：

| tag | 值 | 含义 |
| :--- | :--- | :--- |
| `kComparator` | 1 | length-prefixed slice |
| `kLogNumber` | 2 | 当前 WAL 编号 |
| `kNextFileNumber` | 3 | 下一个可用文件号 |
| `kLastSequence` | 4 | 全局序号 |
| `kCompactPointer` | 5 | 该层轮转指针（level + 一个 InternalKey） |
| `kDeletedFile` | 6 | level + file number |
| `kNewFile` | 7 | level + number + file_size + smallest + largest |
| `kPrevLogNumber` | 9 | 见下 |

注释里明确写着「8 was used for large value refs」。编码是 `PutVarint32(tag)` 后接 payload，字段由各自的 `has_*_` bool 门控，**顺序不固定**。`kPrevLogNumber` 值得单独说：1.23 仍然编码并解码它（`LogAndApply` 每次都无条件写 tag 9），但新写路径恒置 0（`edit.SetPrevLogNumber(0)`，`db_impl.cc:566`、`:1508`），且有断言 `assert(versions_->PrevLogNumber() == 0)`（`:1362`）；源码注释是「PrevLogNumber() is no longer used, but we pay attention to it in case we are recovering a database produced by an older version of leveldb」（`:332-333`）。**它是兼容性残留，不是活跃机制**——描述成「双 log 号用于安全回收」就错了。

`Version::Builder`（`version_set.cc:569-731`）负责「base 版本 + 一批编辑 → 新版本」：内部 `LevelState{std::set<uint64_t> deleted_files; FileSet* added_files}`，方法只有 `Apply` / `SaveTo` / `MaybeAddFile`（**`SaveCurrent`、`SaveTable`、`ApplyDeletedFile` 都不存在**）。`Apply` 会顺带写回 `compact_pointer_`、把 `allowed_seeks` 重算成 `file_size / 16384`（下限 100），并把刚加入的文件从 deleted 集合里抹掉；`SaveTo` 用 `upper_bound` 归并 base 与新增文件，且在 NDEBUG 下**若发现 level > 0 出现重叠就直接 `abort()`**——层内不重叠这个不变式是被代码强制的。

## MANIFEST and CURRENT

descriptor 就是一个 `log::Writer` 写的 WAL 格式文件（复用同一套记录分片格式），文件名 `MANIFEST-%06llu`（`util/filename.cc:43-49`）。库目录下另有一个 `CURRENT` 文件，内容只有一行：当前 MANIFEST 的名字。

`VersionSet::Recover(bool* save_manifest)`（`version_set.cc:862`）读它：CURRENT 内容**必须以 `\n` 结尾**否则直接判 Corruption（:876-878）；然后用 `log::Reader(checksum=true, initial_offset=0)` 逐条 `VersionEdit::DecodeFrom` 并喂给 Builder。这里有个容易踩空的地方：**1.23 的 MANIFEST 与 CURRENT 里没有任何 magic/前缀校验串**（对 descriptor 路径 grep `magic` 零命中——注意 SSTable 的 footer 另有 `kTableMagicNumber`，两者不要混），合法性完全靠「comparator 名字必须匹配」加上「必须见到 next_file / log_number / last_sequence 三项」（:952-957）来保证。

`SetCurrentFile`（`filename.cc:123-139`）是切换的原子性来源：把新 MANIFEST 名写进 `%06llu.dbtmp`，`WriteStringToFileSync` 落盘后 **`RenameFile(tmp, CURRENT)`**，失败再删临时文件。靠文件系统的 rename 原子性完成指针翻转。

`LogAndApply`（`version_set.cc:777-860`）是所有元数据变更的入口，它的两阶段设计要留意：

1. 补齐 edit 的 log / prevlog / next_file / last_sequence；
2. `new Version` + Builder 合并 + `Finalize()` 算 score；
3. 若是新 MANIFEST，先 `WriteSnapshot`（**一个 VersionEdit 装下 comparator、非空的 compact_pointer、以及每层每个文件**，:1070-1098）把全量状态灌进新 descriptor；
4. **释放 `mu`**，写 `AddRecord` + `Sync()`，新 MANIFEST 情况下才 `SetCurrentFile`；
5. 重新加锁，成功则 `AppendVersion` 并更新 `log_number_/prev_log_number_`，失败则删掉 Version 并 `RemoveFile`。

头文件注释明确要求**不得并发调用**（`version_set.h:180`），因为第 4 步放开了锁。另一个要点：**MANIFEST 运行期只追加、永不重写**；新 MANIFEST 是在 `descriptor_log_ == nullptr` 时由首次 `LogAndApply` 懒创建的，其文件号直接取 `next_file`（最后一次 `kNextFileNumber` 的值）而不是 `NewFileNumber()`。`ReuseManifest`（:995-1024）只在 `options.reuse_logs`（默认 false、标 EXPERIMENTAL）且它是 descriptor 类型且大小未超目标时才会以 `NewAppendableFile` 续写。

`Finalize()`（:1032-1068）的 score 公式两套并存，这是「LevelDB 什么时候会去压实」的真正答案：

```
L0:  score = files_[0].size() / kL0_CompactionTrigger        // 按文件数，kL0_CompactionTrigger = 4
L≥1: score = TotalFileSize(level) / MaxBytesForLevel(level)  // 按字节
```

循环上界是 `level < kNumLevels - 1`，取 score 最大者写入 `compaction_level_/compaction_score_`——**所以 L6 永远不会成为压实的源层**。`MaxBytesForLevel`（`dbformat.h:41-52`）是 L0 与 L1 都 10 MB、此后每级 ×10，且完全不可调。`NeedsCompaction()` = `score >= 1 || file_to_compact_ != nullptr`（`version_set.h:252`）。

## Sequence Numbers and Snapshots

内部键打包在 `db/dbformat.{h,cc}`：`PackSequenceAndType = (seq << 8) | type`（`dbformat.cc:15-19`，序号占高 56 位），`kMaxSequenceNumber = (1ull << 56) - 1`（`dbformat.h:67`），`kTypeDeletion = 0x0`、`kTypeValue = 0x1`、`kValueTypeForSeek = kTypeValue`。一个 InternalKey 尾部固定 8 字节 Fixed64。

快照的实现载体**不是 vector**：`SnapshotList snapshots_`（`db_impl.h:189`），类型定义在 `db/snapshot.h`（该文件无 .cc），是一个带哑元 `head_` 的**循环双向链表**，`SnapshotImpl` 带 `prev_/next_/sequence_number_`，接口只有 `New/Delete/oldest/newest/empty`。`GetSnapshot()` 即 `snapshots_.New(versions_->LastSequence())`（`db_impl.cc:1181-1184`），`ReleaseSnapshot()` 即 `Delete`。

要特别注意命名：`NewSnapshot`、`DeleteSnapshot`、`OldestSnapshotSequence`、`first_snapshot_`、`has_snapshots_` 这些在 LevelDB 全库**零命中**，它们是 RocksDB 的名字。

快照如何影响数据回收发生在压实里（`db_impl.cc:904-907` 先算出 `smallest_snapshot`）：某 key 的旧版本只有在 `last_sequence_for_key <= smallest_snapshot` 时才可丢；删除标记更严，还要 `IsBaseLevelForKey()` 成立（即更低的层里不会再有同 key 的东西）。**长期持有快照会同时推高空间放大与读放大**，机制与 RocksDB 相同，只是 LevelDB 没有对应的可观测属性来暴露它。

## Compaction

### Scheduling

`MaybeScheduleCompaction()`（`db_impl.cc:662-677`）的早退链依次是：`background_compaction_scheduled_` → `shutting_down_` → `!bg_error_.ok()` → `imm_ == nullptr && manual_compaction_ == nullptr && !versions_->NeedsCompaction()`，都不成立才置位并 `env_->Schedule(&DBImpl::BGWork, this)`。

并发度是这里最容易被误写的一点：LevelDB **只有一个 bool 和一个后台线程**——`PosixEnv` 首次 `Schedule` 时才 detach 唯一后台线程、队列串行取任务，因此**同一时刻最多一个在途压实**。`options.max_background_compactions`、线程池、高优先级队列这些都是 RocksDB 的东西，LevelDB 不存在，`bghalt_` 也不存在。

`BackgroundCall`（:683-700）复位 flag、再调度一次、最后 `SignalAll` 唤醒前台写者。触发调度的四处调用点是 `MakeRoomForWrite`、`Get`、`RecordReadSample`、`TEST_CompactRange`。`RecordBackgroundError`（:654-660）记录 sticky error 并 `SignalAll`——一旦有后台错误，`RemoveObsoleteFiles` 会**直接 return 不再删任何文件**（:228-232）。

`BackgroundCompaction`（:702 起）的分支判据是 **`imm_ != nullptr` 就先 `CompactMemTable(); return;`**：flush 无条件优先，不是「flush 与层间压实二选一」。`CompactMemTable`（:549-580）顺序为 `WriteLevel0Table(imm_, &edit, base)` → 检查 `shutting_down_` → `SetPrevLogNumber(0) + SetLogNumber(logfile_number_)` → `LogAndApply` → 成功才 `imm_ = nullptr; has_imm_ = false; RemoveObsoleteFiles()`，失败则 `RecordBackgroundError`。

这里要破除两个来自 RocksDB 的口头禅：**LevelDB 没有 `SwitchMemtable()`**（mem→imm 的切换发生在前台写者线程的 `MakeRoomForWrite` 里，:1360-1382），也**没有多个 immutable memtable 的列表**，只有单个 `imm_` 指针与一个 `std::atomic_bool has_imm_`。

### Picking Files

`VersionSet::PickCompaction()`（`version_set.cc:1253-1305`）：

- **按大小压实优先于按 seek 压实**（`size_compaction = compaction_score_ >= 1` 先判，:1257-1260）；源层直接取 `Finalize()` 选好的 `compaction_level_`，不是「遍历所有层比 score」。
- 起点文件由该层的轮转指针决定：取第一个 `largest > compact_pointer_[level]` 的文件，找不到就回绕到 `files_[level][0]`。`compact_pointer_` 是 `VersionSet` 的 `std::string[kNumLevels]`，在 `SetupOtherInputs` 末尾**立即推进**（:1443-1444，注释说明即使这次压实失败也要换一段 key range 试），并经 VersionEdit 持久化。
- L0 需要特判：因为层内可重叠，选出文件后用 `GetRange` + `GetOverlappingInputs(0, ...)` 重建整个输入集；`GetOverlappingInputs` 在 L0 遇到范围扩大时会 clear 后重启扫描（:525-535）。
- `SetupOtherInputs`（:1386-1445）：`AddBoundaryInputs` 补齐边界 → 取 level+1 的重叠文件 → **仅当「不新增 L+1 文件数」且扩展后总大小 < `25 × target_file_size`（50 MB）**才继续扩大 → 再算 grandparents（level+2 的重叠）。**1.23 不存在 `ExpandInputsToCleanCut` 与 `SetupLevel`**。

`IsTrivialMove()`（:1498-1506）的条件很干净：

```
num_input_files(0) == 1 && num_input_files(1) == 0
&& TotalFileSize(grandparents_) <= MaxGrandParentOverlapBytes(= 20 MB)
```

满足就只改元数据不重写文件（`db_impl.cc:732-747`），且**只有非手工压实才允许 trivial move**。

### Merge and Rewrite

`DoCompactionWork`（:892 起）先 `MakeInputIterator`（`version_set.cc:1220-1251`）：`fill_cache = false`（压实读不该污染块缓存）、L0 逐文件建 `table_cache_->NewIterator`、L≥1 用 `NewTwoLevelIterator(Version::LevelFileNumIterator, &GetFileIterator, ...)`、最后 `NewMergingIterator`。**memtable 与 imm 不参与归并**——所以手工压实前会先强制 flush 一次（`TEST_CompactMemTable`）。

同 key 多版本的折叠规则（:944-978）是这段代码的精华，确切写法是：解析失败则重置 `has_current_user_key = false` 并把 `last_sequence_for_key = kMaxSequenceNumber`；遇到新 user key 时同样重置 `last_sequence_for_key`；然后

```
rule(A)  last_sequence_for_key <= smallest_snapshot   → 丢弃该条目
rule(B)  kTypeDeletion && ikey.sequence <= smallest_snapshot
         && IsBaseLevelForKey(user_key)               → 丢弃删除标记本身
```

每处理完一条就 `last_sequence_for_key = ikey.sequence`。**注意：被丢弃就是整条丢掉，LevelDB 不会把 value 写成「type 0 占位」**（那是某些 LSM 实现的做法）。保留下来的条目原样 `builder->Add(key, input->value())`。

切新文件由 `ShouldStopBefore`（:1537-1559）决定，而它**只有一个条件**：跨过 grandparents 边界后累计 `overlapped_bytes_ > MaxGrandParentOverlapBytes` 就切，并在 `seen_key_` 之后才累加、切完清零。**snapshot 边界不参与这个判断**（RocksDB 的 `ShouldStopBefore` 里才有那条）。

统计只有 `CompactionStats{micros, bytes_read, bytes_written}`（`db_impl.h:90-102`），记进 `stats_[level + 1]`。取消机制就是 `while (input->Valid() && !shutting_down_)`；出错或退出时 `CleanupCompaction`（:783-798）对 builder 调 `Abandon()`，**只有全程 OK 才 `InstallCompactionResults`**（一次性把所有输入标删、输出标加进 `edit_`）。收尾顺序是 `DoCompactionWork → CleanupCompaction → ReleaseInputs → RemoveObsoleteFiles`（:750-756），其中 `ReleaseInputs`（:1561-1566）**只 Unref version，不删文件**——真正删除只发生在 `RemoveObsoleteFiles`。

### Manual Compaction

`DB::CompactRange(const Slice* begin, const Slice* end)`（`db.h:50`）**返回 void、没有任何 options 参数**。实现（`db_impl.cc:582-597`）先用 `OverlapInLevel` 找出 `max_level_with_files`，然后 `TEST_CompactMemTable()`，再 `for (level = 0; level < max_level_with_files; level++) TEST_CompactRange(level, begin, end)`——**逐层各跑一遍**。

独占靠 `ManualCompaction` 结构 + `manual_compaction_` 指针本身（全局同时只有一个）：持锁期间若空闲就占用并调度，否则在 `background_work_finished_signal_` 上 `Wait()`。续压靠把 `m->begin` 改成上一轮最后一个输入文件的 largest 再循环。**`RangeCompactionState`、`GetCompactRangeStats`、`ExclusiveManualCompaction`、`manual_garbage_limit_`、`CompactRangeOptions` 在 LevelDB 全都不存在**（RocksDB 专有）。手工压实也**不会暂停自动压实**，只是自己优先，并且禁掉 trivial move。

## Write Throttling

LevelDB 的前台限速集中在 `MakeRoomForWrite(bool force)`（`db_impl.cc:1330-1383`），六级判定：

| 顺序 | 条件 | 行为 |
| :--- | :--- | :--- |
| ① | `!bg_error_.ok()` | 直接返回旧的 sticky error |
| ② | `allow_delay && NumLevelFiles(0) >= kL0_SlowdownWritesTrigger`（8） | 放锁 `env_->SleepForMicroseconds(1000)`，并置 `allow_delay = false` |
| ③ | `!force && mem_->ApproximateMemoryUsage() <= write_buffer_size` | 跳出，无需换 memtable |
| ④ | `imm_ != nullptr` | `background_work_finished_signal_.Wait()` |
| ⑤ | `NumLevelFiles(0) >= kL0_StopWritesTrigger`（12） | 同一个条件变量 `Wait()` |
| ⑥ | 以上都不成立 | 关旧 log、新建 WAL 与 memtable，`imm_ = mem_`，`MaybeScheduleCompaction()` |

三个数要记准：**8 触发慢写、12 触发停写、4 只是 L0 score 的分母**（`kL0_CompactionTrigger` 不参与 flush 判定，flush 由 `write_buffer_size` 决定）。判据是 `>=` 而不是 `>`。②的「每次写最多睡 1 ms」也容易被忽略——`allow_delay = false` 保证一次 `MakeRoomForWrite` 里不会反复睡。

这三个阈值硬编码在 `db/dbformat.h:28/31/34` 的 `namespace config` 里，**`Options` 中没有任何对应字段**（1.23 可调项只有：comparator、create_if_missing、error_if_exists、paranoid_checks、env、info_log、write_buffer_size=4 MB、max_open_files=1000、block_cache、block_size=4 KB、block_restart_interval=16、max_file_size=2 MB、compression=kSnappy、reuse_logs、filter_policy）。也就是说**层数、各层容量、限速阈值在 LevelDB 里全部不可调**，这正是它与 RocksDB 最根本的定位差异。

唤醒等待者的四处：`BackgroundCall`、`DoCompactionWork` 的循环里、`RecordBackgroundError`、`TEST_CompactMemTable`。整个过程**永不返回「stall」错误码**——前台只会睡着或等条件变量，不像 RocksDB 有 `Status::Incomplete`。

## Obsolete File Removal

函数名是 **`RemoveObsoleteFiles()`**，不是 `DeleteObsoleteFiles`（后者是 RocksDB 的）。逻辑（`db_impl.cc:225-289`）：

```
live = pending_outputs_ ∪ VersionSet::AddLiveFiles()   // 后者遍历整条版本链表
log 文件保留条件：number >= versions_->LogNumber() || number == PrevLogNumber()
descriptor 保留条件：number >= ManifestFileNumber()
table / temp 文件：不在 live 集合里就删
CURRENT、LOCK、LOG 恒保留
```

`pending_outputs_` 是 **DBImpl 的成员**（`std::set<uint64_t>`，`db_impl.h:193`），在 `BuildTable` 前登记、之后 erase，用来防止「正在写、还没进任何 Version」的文件被误删。先收集待删清单再放开锁去删；若 `bg_error_` 非 OK 则整体跳过不删。

## Recovery Order

`DB::Open`（:1483）里的顺序决定了崩溃语义：`CreateDir` → `env_->LockFile(LockFileName(dbname_))`（锁文件名就是 `LOCK`）→ 无 CURRENT 则按 `NewDB` 造 `MANIFEST-000001`（log=0 / next_file=2 / last_sequence=0）→ `versions_->Recover()` → 取 `min_log = LogNumber()`、`prev_log = PrevLogNumber()` → `GetChildren` 并把 `AddLiveFiles` 的结果逐个 `expected.erase(number)`，**剩余非空即报 "%d missing files"，这是数据完整性检查** → 收集所有 `kLogFile && (number >= min_log || number == prev_log)`，**按文件号升序**逐个 `RecoverLogFile` 并 `MarkFileNumberUsed` → `SetLastSequence(max_sequence)`。

`RecoverLogFile`（:385-503）把 WAL 重放进 memtable：`log::Reader` **无论 `paranoid_checks` 真假都校验 checksum**（:420-424，注释解释目的是让整笔未提交的 batch 被跳过）；`record.size() < 12`（WriteBatch 头 = 8 字节序号 + 4 字节计数）判为 "log record too small" 并 continue；memtable 用量超过 `write_buffer_size` 就落一个 L0 表并置 `*save_manifest = true`。

一个必须破除的说法：**LevelDB 的 `RecoverLogFile` 里没有 `prev` 指针去重那套机制**（`record_to_sequence`、`batch_seq`、`found_final_batch`、`prev` 在 `db_impl.cc` 全库零命中，那些是 RocksDB 的）。LevelDB 的幂等性靠的是**收集阶段的文件号过滤**（只回放 `number >= LogNumber()` 的 log，已落盘的 log 号必然更小）+ 升序回放 + 读路径按 sequence 取最新。`last_log` 参数唯一的用途是判定能否复用该 log（配合 `options.reuse_logs`）。

## Common Pitfalls

- **L6 永远不会作为压实的源层**：`Finalize` 循环上界 `kNumLevels - 1`，手工路径也有 `assert(level + 1 < kNumLevels)`。
- **`kL0_CompactionTrigger = 4` 不是「攒够 4 个文件就 flush」**，它只是 L0 score 的分母。
- 阈值判据是 `>=`（8 与 12），写成「大于」会与源码行为差一档。
- `allowed_seeks` 需要**同一内部键在 ≥2 个文件上命中**才会递减（`RecordReadSample`，:447），不是每次 seek 都记账。
- `compact_pointer_` 在压实**开始前**就推进，失败也不回退。
- 后台一旦 sticky error：不再 GC、新的压实直接返回，`MakeRoomForWrite` 也会把该错误回灌给前台写者——**LevelDB 遇到后台错误后是「逐步冻结」而非「继续降级运行」**。

## Links

- [LevelDB](/docs/CS/DB/LevelDB/LevelDB.md)
- [LSM-Tree](/docs/CS/Algorithms/tree/LSM.md)
- [RocksDB Compaction](/docs/CS/DB/RocksDB/Compaction.md)
- [RocksDB Write Path](/docs/CS/DB/RocksDB/Write_Path.md)
- [Bloom Filter](/docs/CS/DB/LevelDB/BloomFilter.md)
- [DataBases](/docs/CS/DB/DB.md)

## References

1. [LevelDB source at tag 1.23: db/version_set.cc](https://github.com/google/leveldb/blob/1.23/db/version_set.cc)
2. [LevelDB source at tag 1.23: db/db_impl.cc](https://github.com/google/leveldb/blob/1.23/db/db_impl.cc)
3. [LevelDB source at tag 1.23: db/dbformat.h](https://github.com/google/leveldb/blob/1.23/db/dbformat.h)
4. [LevelDB source at tag 1.23: db/snapshot.h](https://github.com/google/leveldb/blob/1.23/db/snapshot.h)
