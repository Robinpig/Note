## Introduction

The redo log is a disk-based data structure used during crash recovery to correct data written by incomplete transactions.
During normal operations, the redo log encodes requests to **change table data**(except SELECT/SHOW) that result from SQL statements or low-level API calls.
Modifications that did not finish updating the data files before an unexpected shutdown are replayed automatically during initialization, and before connections are accepted.

| 项 | 值 |
| :--- | :--- |
| 正文默认版本 | MySQL 9.7.x LTS（最新 9.7.3，2026-08-18） |
| 源码核实基线 | tag `mysql-9.7.2` |
| 次要兼容目标 | 8.4.x LTS |
| 已停止支持 | 8.0（EOL 2026-04-30）、5.7（EOL 2023-10） |
| 核实日期 | 2026-10-07 |

## Physical Layout

「环形复用固定文件组」这件事没变，变的是文件族本身：

- 9.7 的 redo log 文件位于 data directory 下的 `#innodb_redo/` 目录，命名规则是 `#ib_redo N`（N 为 redo log 文件序号），尚未投入使用的备用文件带 `_tmp` 后缀。
- 总容量由 `innodb_redo_log_capacity`（单位字节）决定，默认 **100MB**——源码里就写成 `100 * 1024 * 1024`（`handler/ha_innodb.cc:22842-22847`），手册范围 8MB–512GB。InnoDB 尽量维持 **32 个** redo log 文件、每个约为 `capacity / 32`，所以「单个 redo 文件多大」在 9.7 已不是可配置项。
- 用 `--innodb-dedicated-server` 启动时，`innodb_redo_log_capacity`（连同 `innodb_buffer_pool_size`）由 InnoDB 自动计算并改写默认值（`innodb_redo_log_capacity_init()`，`ha_innodb.cc:4605-4634`），`SET GLOBAL` 修改后的值也会体现在该变量的 `Default Value` 上。
- **`innodb_log_file_size` 与 `innodb_log_files_in_group` 在 9.7 已不存在**：两者在 8.0 与 8.4 手册里仍以 Deprecated 身份出现（8.4 的 `innodb_log_file_size` 默认 50331648 = 48MB），到 9.7.2 源码与 9.7 的 InnoDB 参数清单中都已消失。旧笔记里「两个 5MB 的 `ib_logfile0` / `ib_logfile1`」是 5.7 及更早的形态。
- 活动的 redo log 文件可查 `performance_schema.innodb_redo_log_files`（列：`FILE_ID` / `FILE_NAME` / `START_LSN` / `END_LSN` / `SIZE_IN_BYTES` / `IS_FULL` / `CONSUMER_LEVEL`）。

```sql
mysql> show variables like 'innodb_redo_log_capacity';
+--------------------------+-----------+
| Variable_name            | Value     |
+--------------------------+-----------+
| innodb_redo_log_capacity | 104857600 |
+--------------------------+-----------+

mysql> SELECT FILE_ID, FILE_NAME, START_LSN, END_LSN
    -> FROM performance_schema.innodb_redo_log_files;
```

Data in the redo log is encoded in terms of records affected; this data is collectively referred to as redo.
The passage of data through the redo log is represented by an ever-increasing `LSN` value.

Redo log write into [Log Buffer](/docs/CS/DB/MySQL/memory.md?id=log-buffer), then flush to disk.

### LSN

Acronym for “`log sequence number`”. This arbitrary, ever-increasing value represents a point in time corresponding to operations recorded in the `redo log`.
(This point in time is regardless of **transaction** boundaries; it can fall in the middle of one or more transactions.)
It is used internally by `InnoDB` during **crash recovery** and for managing the **buffer pool**.

The LSN became an **8-byte unsigned integer** in MySQL 5.6.3 when the redo log file size limit increased from 4GB to 512GB.

9.7 把 redo log 的几个关键位置直接暴露成状态变量，排查刷盘滞后与恢复起点时，看的就是它们之间的差值：

| 状态变量 | 9.7 手册定义 |
| :--- | :--- |
| `Innodb_redo_log_current_lsn` | 当前 LSN，即 **redo log buffer 里最后写入的位置**（InnoDB 先写进程内的 log buffer，再要求 OS 写入当前 redo log 文件） |
| `Innodb_redo_log_flushed_to_disk_lsn` | InnoDB 已知**已刷到磁盘**的最后一个位置 |
| `Innodb_redo_log_checkpoint_lsn` | redo log 的检查点 LSN，即崩溃恢复的起点 |
| `Innodb_redo_log_enabled` | redo logging 是否处于开启状态（见「Disabling Redo Logging」） |

## Format

<div style="text-align: center;">

```dot
digraph g {
  node [shape = record,height=.1];
  node0[label = "<f0> type |<f1> space ID|<f2> page number|<f3> data "];
} 
```

</div>

<p style="text-align: center;">
Fig.1. Redo log structure.
</p>

### Group Commit for Redo Log Flushing

`InnoDB`, like any other ACID-compliant database engine, flushes the `redo log` of a transaction before it is committed.

`InnoDB` uses `group commit` functionality to group multiple flush requests together to avoid one flush for each commit. With group commit,
`InnoDB` issues a single write to the log file to perform the commit action for multiple user transactions that commit at about the same time, significantly improving throughput.

> [!NOTE]
>
> **Group Commit**:
>
> An InnoDB optimization that performs some low-level I/O operations (log write) once for a set of `commit` operations, rather than flushing and syncing separately for each commit.

`innodb_flush_log_at_trx_commit` 决定每次提交时对 log buffer 做哪一步（默认 **1**，取值 0/1/2），9.7 手册的口径如下：

| 取值 | 每次 commit 时的行为 | 崩溃后果 |
| :--- | :--- | :--- |
| `0` | 提交时什么都不做，由后台线程**每秒**把 log buffer 写入并刷盘 | 最多丢 1 秒事务 |
| `1` | 每次提交都 write + flush 到磁盘 | **完整 ACID**，不丢已提交事务 |
| `2` | 每次提交只 write（交给 OS），由后台线程每秒 flush 到磁盘 | 未 flush 的事务可能丢失，手册口径同样是最多约 1 秒 |

取 0 或 2 时「每秒一次」并不保证——DDL 与其他 InnoDB 内部活动会独立触发刷日志，调度问题也可能让它更晚；刷盘频率由 `innodb_flush_log_at_timeout` 控制（默认 1 秒，范围 1–2700）。**无论取值多少，InnoDB 崩溃恢复都照常工作**，事务要么全部生效要么全部撤销。

配合 binlog 的**两阶段提交**顺序是 `redo log prepare --> write binlog --> redo log commit`：redo 先记下 prepare 状态，崩溃恢复时再以 binlog 中该事务是否完整来决定它提交还是回滚，两侧因此不会长期背离。


## Configuration

Configure the `innodb_log_write_ahead_size` configuration option to avoid “`read-on-write`”. This option defines the write-ahead block size for the redo log.
Valid values for innodb_log_write_ahead_size are multiples of the InnoDB log file block size (2n). The minimum value is the InnoDB log file block size (512).

9.7 手册补齐了这里的取值边界：默认 **8192** 字节，最小 512（即 log file block size），最大等于 `innodb_page_size`；填超过页大小会被截断到 `innodb_page_size`。目标是匹配 OS / 文件系统的 cache block size——太小会触发 read-on-write，太大则每次覆盖写入的未改动数据变多。取最小值 512 时不发生 write-ahead。

## Archiving

Backup utilities that copy redo log records may sometimes fail to keep pace with redo log generation while a backup operation is in progress, resulting in lost redo log records due to those records being overwritten.
This issue most often occurs when there is significant MySQL server activity during the backup operation, and the redo log file storage media operates at a faster speed than the backup storage media.
The redo log archiving feature, introduced in MySQL 8.0.17, addresses this issue by sequentially writing redo log records to an archive file in addition to the redo log files.
Backup utilities can copy redo log records from the archive file as necessary, thereby avoiding the potential loss of data.

Activating redo log archiving typically has a minor performance cost due to the additional write activity.

Writing to the redo log archive file does not impede normal transactional logging except in the case that the redo log archive file storage media operates at a much slower rate than the redo log file storage media, and there is a large backlog of persisted redo log blocks waiting to be written to the redo log archive file. In this case, the transactional logging rate is reduced to a level that can be managed by the slower storage media where the redo log archive file resides.

## Optimization

Consider the following guidelines for optimizing redo logging:

* Make your redo log files big, even as big as the [buffer pool](/docs/CS/DB/MySQL/memory.md?id=buffer-pool).
  When `InnoDB` has written the redo log files full, it must write the modified contents of the buffer pool to disk in a `checkpoint`.
  Small redo log files cause many unnecessary disk writes.
  Although historically big redo log files caused lengthy recovery times, recovery is now much faster and you can confidently use large redo log files.
* Consider increasing the size of the [log buffer](/docs/CS/DB/MySQL/memory.md?id=log-buffer).
  A large log buffer enables large transactions to run without a need to write the log to disk before the transactions `commit`.
  Thus, if you have transactions that update, insert, or delete many rows, making the log buffer larger saves disk I/O.
* Configure the innodb_log_write_ahead_size configuration option to avoid “read-on-write”.
* Optimize the use of spin delay by user threads waiting for flushed redo. Spin delay helps reduce latency.
  During periods of low concurrency, reducing latency may be less of a priority, and avoiding the use of spin delay during these periods may reduce energy consumption.
  During periods of high concurrency, you may want to avoid expending processing power on spin delay so that it can be used for other work.
* MySQL 8.0.11 introduced dedicated log writer threads for writing redo log records from the log buffer to the system buffers and flushing the system buffers to the redo log files.
  Previously, individual user threads were responsible those tasks.
  Dedicated log writer threads can improve performance on high-concurrency systems, but for low-concurrency systems, disabling dedicated log writer threads provides better performance.
  对应的开关 `innodb_log_writer_threads` 在 9.7 仍然存在。

* 9.7 里「把 redo log 调大」意味着调 `innodb_redo_log_capacity` 这个**总容量**（最大 512GB），而不是单个文件大小；文件数与单文件大小由 InnoDB 自己按 32 份切分并在 resize 时增删（备用文件带 `_tmp` 后缀，进度可看 `Innodb_redo_log_resize_status`）。

## Summary

> [!WARNING]
>
> ***Do not disable redo logging on a production system.***

## Links

- [InnoDB Storage Engine](/docs/CS/DB/MySQL/InnoDB.md?id=innodb-on-disk-structures)
- [Undo Log](/docs/CS/DB/MySQL/undolog.md)
- [binlog 二进制日志](/docs/CS/DB/MySQL/binlog.md)
- [Buffer Pool](/docs/CS/DB/MySQL/memory.md)
- [Doublewrite Buffer](/docs/CS/DB/MySQL/Double-Buffer.md)

## References

- [MySQL 9.7 Reference Manual: Redo Log](https://dev.mysql.com/doc/refman/9.7/en/innodb-redo-log.html)
- [MySQL 9.7 Reference Manual: Optimizing InnoDB Redo Logging](https://dev.mysql.com/doc/refman/9.7/en/optimizing-innodb-logging.html)
- [MySQL 8.4 Reference Manual: Optimizing InnoDB Redo Logging](https://dev.mysql.com/doc/refman/8.4/en/optimizing-innodb-logging.html)
