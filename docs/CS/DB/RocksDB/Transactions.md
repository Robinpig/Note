## Introduction

RocksDB 本体只保证两件事：**一个 `WriteBatch` 内的写入原子**，以及**快照下的一致性读**（见 [Read_Path](/docs/CS/DB/RocksDB/Read_Path.md)）。多个 key 上的 ACID 事务由 `utilities/` 层的 **`TransactionDB`（悲观锁）** 与 **`OptimisticTransactionDB`（提交时校验）** 提供。它们的共同点是：并发控制做在 RocksDB 之上，数据仍落在同一份 LSM 里，因此**事务开销最终都会变成写放大与锁等待**。

本页符号与默认值取 v11.8.1 的 `include/rocksdb/utilities/transaction_db.h`。

## Three Write Policies

枚举实名是 **`TxnDBWritePolicy`**（不是 `TransactionDBWritePolicy`），定义在 `transaction_db.h:26-37`：

| 策略 | 值 | 写入时机 | 代价与用途 |
| :--- | :--- | :--- | :--- |
| `WRITE_COMMITTED` | 0（默认，:214） | 事务数据暂存在批缓冲里，**Commit 时一次性写入** | 简单；但长事务会在提交瞬间产生一次大写入，且未提交数据不可被其他事务读 |
| `WRITE_PREPARED` | EXPERIMENTAL | 像 2PC 的 prepare 那样**提前写 WAL 与 memtable**，commit 只写一条标记 | 大事务提交不再抖动、可恢复 prepared 状态；代价是 prepare 的数据要额外维护 |
| `WRITE_UNPREPARED` | EXPERIMENTAL | 事务内分批 flush 自己的 batch | 内存占用最低（适合超大数据量导入式事务）；恢复路径最复杂 |

写策略影响一个隐蔽的正确性细节：`WRITE_PREPARED` / `WRITE_UNPREPARED` 会写入**尚未提交**的记录，所以可见性判断必须用 **`GetLastPublishedSequence()`** 而不是「最后写入的序号」——这正是 [Write_Path](/docs/CS/DB/RocksDB/Write_Path.md) 里强调的那条序号语义的由来之一。

## Locking and Deadlock Detection

`TransactionDBOptions` 的实测默认值：

| 选项 | 默认 | 行号 | 说明 |
| :--- | :--- | :--- | :--- |
| `num_stripes` | 16 | `:179` | 锁表分片数。**实名是 `num_stripes`，不是 `num_lock_buckets`** |
| `max_num_locks` | -1 | `:171` | 锁内存上限，-1 为不限 |
| `max_num_deadlocks` | 5 | `:174` | 保留的死锁日志条数 |
| `default_lock_timeout` | 1000 ms | `:203` | 未显式指定时 `BeginTransaction` 用这个值 |
| `transaction_lock_timeout` | 1000 ms | `:189` | `TransactionOptions.lock_timeout` 的兜底值 |
| `rollback_merge_operands` | `false` | `:222` | 回滚时是否撤销 merge operand |
| `use_per_key_point_lock_mgr` | `false` | `:231` | 另一种更细的锁管理实现 |
| `default_write_batch_flush_threshold` | 0 | `:243` | 事务内批缓冲的落盘阈值 |
| `wp_snapshot_cache_bits` / `wp_commit_cache_bits` | 7 / 23 | `:286/:290` | `WRITE_PREPARED` 的两个缓存规模（**没有 `wp_batch_cnt`**） |
| `write_policy` | `WRITE_COMMITTED` | `:214` | 见上表 |

死锁检测在 `TransactionOptions` 里：`deadlock_detect = false`、`deadlock_timeout_us = 500`、`deadlock_detect_depth = 50`（默认**不做**死锁检测，靠 `lock_timeout = -1` 落到 `default_lock_timeout` 超时退出）。也就是说，默认配置下相互等待的两个事务不是被检测打断，而是**超时后返回 `TimedOut`**——排查锁竞争时要找的是这个错误码，而不是死锁日志。

## Transaction API and Lifecycle

打开：`TransactionDB::Open` 有两个重载（:532 用 `Options`、:536 用 `DBOptions` + 列族描述符列表）；已有裸 `DB` 想套上事务层用 `TransactionDB::WrapDB` / `WrapStackableDB`。**`GetTransactionDBWithOptions` 这个函数不存在**。

常用调用链：`BeginTransaction(txn_options, prep_options?)`（:578）→ `Get/Put/Merge/Delete` → 可选 `SetSavePoint()`（:282）/ `RollbackToSavePoint()`（:288）/ `PopSavePoint()`（:294）→ `Commit()`（:242）或 `Rollback()`。跨进程恢复用 `Prepare()`（:217）+ `Commit()`，配合 `TransactionDB` 的 WAL 能找回 in-doubt 事务。

`TransactionOptions` 的实测默认：`set_snapshot = false`、`lock_timeout = -1`、`expiration = -1`、`max_write_batch_size = 0`、`skip_concurrency_control = false`、**`skip_prepare = true`**（:375）。

> [!WARNING]
> v11.8.1 的 `TransactionOptions` **已经没有 `read_options` 与 `write_options` 字段**，也**没有** `snapshot` 或 `disable_wal` 字段（想读快照用 `Transaction::SetSnapshot()` / `GetSnapshot()`（:164/:198），想控制 WAL 请用 `WriteOptions`）。旧代码/旧文章里 `txn_options.read_options.snapshot = ...` 这类写法在当前版本编译不过。

`CommitAndCreateSnapshot()` 提供「提交并原子地拿到该提交点的快照」，是替代 `Commit(); GetSnapshot()` 这种有竞态写法为正解。

## Known Limitations

- **`TransactionDB` 上 `DeleteRange` 返回 `NotSupported`**（`transaction_db.h:525`）。范围删除与事务锁的粒度模型不兼容，需要范围清理时得走裸 DB 或自己拆点删。
- 事务读默认不加快照（`set_snapshot = false`），即读的是「自己写入 + 提交时点」的组合；要严格的重复读必须显式 `SetSnapshot()`。
- 乐观版本（`optimistic_transaction_db.h`）不做加锁，只在提交时校验冲突，冲突即 `TryAgain`，适合低冲突负载。
- 事务数据最终仍进 LSM，因此**长事务 = 老版本无法回收**：它会像未释放的快照一样推高空间与读放大（机制见 [Compaction](/docs/CS/DB/RocksDB/Compaction.md)）。
- 顺带一个出处：`transaction_db.h:383-386` 的注释里自证 MyRocks 依赖 `write_batch_track_timestamp_size` 这类事务侧选项，说明这一层确实被生产系统重度使用。

## WriteBatchWithIndex

`WriteBatch` 只有键的写入序列，没有批内索引；**`WriteBatchWithIndex`**（`include/rocksdb/utilities/write_batch_with_index.h`）额外维护一个批内 memtable 索引，用于「读自己刚写进 batch 的数据」和实现轻量乐观事务。

- 覆盖同名 key 的行为由构造参数 `bool overwrite_key = false`（:121）控制，配 `GetOverwriteKey()`（:384）。**`OverwriteKeyStatus` 枚举已不存在**。
- 读接口：`GetFromBatch`（:245/252）、`GetEntityFromBatch`（:267）、`GetFromBatchAndDB`（:280 起）、`GetEntityFromBatchAndDB`（:309）、`MultiGetFromBatchAndDB`（:319）、`MultiGetEntityFromBatchAndDB`（:339）——**实名大小写是 `MultiGet...`**，旧的小写下划线名已不存在。
- 迭代：`NewIteratorWithBase(读-options, base)`（:235/239）把批内索引与 DB 迭代器叠成一个游标。
- 一个行为变更要记住：同一 key 多次写入时，批内索引的更新顺序是**最新在前**（`HISTORY.md:411`）。

## Links

- [RocksDB](/docs/CS/DB/RocksDB/RocksDB.md)
- [Read Path](/docs/CS/DB/RocksDB/Read_Path.md)
- [Write Path](/docs/CS/DB/RocksDB/Write_Path.md)
- [Column Families](/docs/CS/DB/RocksDB/Column_Families.md)
- [Operations](/docs/CS/DB/RocksDB/Operations.md)
- [LevelDB](/docs/CS/DB/LevelDB/LevelDB.md)

## References

1. [RocksDB Wiki: Transactions](https://github.com/facebook/rocksdb/wiki/Transactions)
2. [RocksDB Wiki: Write Batch With Index](https://github.com/facebook/rocksdb/wiki/Write-Batch-With-Index)
3. [RocksDB source: utilities/transaction_db.h](https://github.com/facebook/rocksdb/blob/v11.8.1/include/rocksdb/utilities/transaction_db.h)
4. [RocksDB source: utilities/optimistic_transaction_db.h](https://github.com/facebook/rocksdb/blob/v11.8.1/include/rocksdb/utilities/optimistic_transaction_db.h)
