## Introduction

The redo log is a disk-based data structure used during crash recovery to correct data written by incomplete transactions.
During normal operations, the redo log encodes requests to **change table data**(except SELECT/SHOW) that result from SQL statements or low-level API calls.
Modifications that did not finish updating the data files before an unexpected shutdown are replayed automatically during initialization, and before connections are accepted.

By default, the redo log is physically represented on disk by two 5MB files named `ib_logfile0` and `ib_logfile1`.
MySQL writes to the redo log files in a **circular fashion**.
Data in the redo log is encoded in terms of records affected; this data is collectively referred to as redo. The passage of data through the redo log is represented by an ever-increasing `LSN` value.

```mysql
mysql> show variables like 'innodb_log_file_size';
innodb_log_file_size	50331648  -- 48M


mysql> show variables like 'innodb_log_files_in_group';
innodb_log_files_in_group	2
```

Redo log write into [Log Buffer](/docs/CS/DB/MySQL/memory.md?id=Log_buffer), then flush to disk.

### LSN

Acronym for “`log sequence number`”. This arbitrary, ever-increasing value represents a point in time corresponding to operations recorded in the `redo log`.
(This point in time is regardless of **transaction** boundaries; it can fall in the middle of one or more transactions.)
It is used internally by `InnoDB` during **crash recovery** and for managing the **buffer pool**.

The LSN became an **8-byte unsigned integer** in MySQL 5.6.3 when the redo log file size limit increased from 4GB to 512GB.

flushed_to_disk_lsn

write_lsn

checkpoint_lsn

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

innodb_flush_log_at_trx_commit

- 0  fsync everytime
- 1
- 2

prepare -->  write binlog  --> commit

## Configuration

Configure the `innodb_log_write_ahead_size` configuration option to avoid “`read-on-write`”. This option defines the write-ahead block size for the redo log.
Valid values for innodb_log_write_ahead_size are multiples of the InnoDB log file block size (2n). The minimum value is the InnoDB log file block size (512).

## Archiving

Backup utilities that copy redo log records may sometimes fail to keep pace with redo log generation while a backup operation is in progress, resulting in lost redo log records due to those records being overwritten.
This issue most often occurs when there is significant MySQL server activity during the backup operation, and the redo log file storage media operates at a faster speed than the backup storage media.
The redo log archiving feature, introduced in MySQL 8.0.17, addresses this issue by sequentially writing redo log records to an archive file in addition to the redo log files.
Backup utilities can copy redo log records from the archive file as necessary, thereby avoiding the potential loss of data.

Activating redo log archiving typically has a minor performance cost due to the additional write activity.

Writing to the redo log archive file does not impede normal transactional logging except in the case that the redo log archive file storage media operates at a much slower rate than the redo log file storage media, and there is a large backlog of persisted redo log blocks waiting to be written to the redo log archive file. In this case, the transactional logging rate is reduced to a level that can be managed by the slower storage media where the redo log archive file resides.

## Optimization

Consider the following guidelines for optimizing redo logging:

* Make your redo log files big, even as big as the [buffer pool](/docs/CS/DB/MySQL/memory.md?id=buffer_pool).
  When `InnoDB` has written the redo log files full, it must write the modified contents of the buffer pool to disk in a `checkpoint`.
  Small redo log files cause many unnecessary disk writes.
  Although historically big redo log files caused lengthy recovery times, recovery is now much faster and you can confidently use large redo log files.
* Consider increasing the size of the [log buffer](/docs/CS/DB/MySQL/memory.md?id=Log_buffer).
  A large log buffer enables large transactions to run without a need to write the log to disk before the transactions `commit`.
  Thus, if you have transactions that update, insert, or delete many rows, making the log buffer larger saves disk I/O.
* Configure the innodb_log_write_ahead_size configuration option to avoid “read-on-write”.
* Optimize the use of spin delay by user threads waiting for flushed redo. Spin delay helps reduce latency.
  During periods of low concurrency, reducing latency may be less of a priority, and avoiding the use of spin delay during these periods may reduce energy consumption.
  During periods of high concurrency, you may want to avoid expending processing power on spin delay so that it can be used for other work.
* MySQL 8.0.11 introduced dedicated log writer threads for writing redo log records from the log buffer to the system buffers and flushing the system buffers to the redo log files.
  Previously, individual user threads were responsible those tasks.
  Dedicated log writer threads can improve performance on high-concurrency systems, but for low-concurrency systems, disabling dedicated log writer threads provides better performance.

## Summary

> [!WARNING]
>
> ***Do not disable redo logging on a production system.***

## Links

- [InnoDB Storage Engine](/docs/CS/DB/MySQL/InnoDB.md?id=innodb-on-disk-structures)

## References

1. [Optimizing InnoDB Redo Logging](https://dev.mysql.com/doc/refman/8.0/en/optimizing-innodb-logging.html)
