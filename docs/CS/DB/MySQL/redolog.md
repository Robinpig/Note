

## Introduction

The redo log is a disk-based data structure used during crash recovery to correct data written by incomplete transactions. During normal operations, the redo log encodes requests to **change table data**(except SELECT/SHOW) that result from SQL statements or low-level API calls. Modifications that did not finish updating the data files before an unexpected shutdown are replayed automatically during initialization, and before connections are accepted. 

By default, the redo log is physically represented on disk by two 5MB files named `ib_logfile0` and `ib_logfile1`. MySQL writes to the redo log files in a **circular fashion**. Data in the redo log is encoded in terms of records affected; this data is collectively referred to as redo. The passage of data through the redo log is represented by an ever-increasing `LSN` value.





```mysql
mysql> show variables like 'innodb_log_file_size';
innodb_log_file_size	50331648  -- 48M


mysql> show variables like 'innodb_log_files_in_group';
innodb_log_files_in_group	2
```



### LSN

Acronym for “`log sequence number`”. This arbitrary, ever-increasing value represents a point in time corresponding to operations recorded in the `redo log`. (This point in time is regardless of **transaction** boundaries; it can fall in the middle of one or more transactions.) It is used internally by `InnoDB` during **crash recovery** and for managing the **buffer pool**.

The LSN became an **8-byte unsigned integer** in MySQL 5.6.3 when the redo log file size limit increased from 4GB to 512GB.

#### Group Commit for Redo Log Flushing



`InnoDB`, like any other ACID-compliant database engine, flushes the `redo log` of a transaction before it is committed. 

`InnoDB` uses `group commit` functionality to group multiple flush requests together to avoid one flush for each commit. With group commit, `InnoDB` issues a single write to the log file to perform the commit action for multiple user transactions that commit at about the same time, significantly improving throughput.

> group commit:  
> 
> An InnoDB optimization that performs some low-level I/O operations (log write) once for a set of `commit` operations, rather than flushing and syncing separately for each commit.


## [Log Buffer](/docs/CS/DB/MySQL/memory.md?id=Log_buffer)

## Configuration

Configure the `innodb_log_write_ahead_size` configuration option to avoid “`read-on-write`”. This option defines the write-ahead block size for the redo log.
Valid values for innodb_log_write_ahead_size are multiples of the InnoDB log file block size (2n). The minimum value is the InnoDB log file block size (512). 

## Archiving

