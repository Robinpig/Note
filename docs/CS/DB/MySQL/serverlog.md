## Error Log

The error log contains a record of **mysqld** startup and shutdown times.
It also contains diagnostic messages such as errors, warnings, and notes that occur during server startup and shutdown, and while the server is running.
For example, if **mysqld** notices that a table needs to be automatically checked or repaired, it writes a message to the error log.

## General Query Log

The general query log is a general record of what **mysqld** is doing.
The server writes information to this log when clients connect or disconnect, and it logs each SQL statement received from clients.
The general query log can be very useful when you suspect an error in a client and want to know exactly what the client sent to **mysqld**.

By default, the general query log is disabled.

```sql
mysql> SELECT * FROM mysql.general_log;
```

## Binary Log

A `binary log`(`binlog`) is a file containing *a record of all statements or row changes* that attempt to change table data.
The contents of the binary log can be replayed to bring replicas up to date in a replication scenario, or to bring a database up to date after restoring table data from a backup.

You can examine the contents of the binary log, or replay it during replication or recovery, by using the `mysqlbinlog` command.
For the MySQL Enterprise Backup product, the file name of the binary log and the current position within the file are important details. To record this information for the source when taking a backup in a replication context, you can specify the --slave-info option.

binlog cache for each threads but only one binlog file

write into page cache

fsync to disk

binlog_group_commit_sync_delay
binlog_group_commit_sync_no_delay_count

### Configurations

This system variable sets the binary logging format, and can be any one of `STATEMENT`, `ROW`, or `MIXED`. The default is `ROW`.

Binary logging is enabled by default (the `log_bin` system variable is set to ON).

**By default, the binary log is synchronized to disk at each write (`sync_binlog=1`)**.
If `sync_binlog` was not enabled, and the operating system or machine (not only the MySQL server) crashed, there is a chance that the last statements of the binary log could be lost.
To prevent this, enable the `sync_binlog` system variable to synchronize the binary log to disk after every *`N`* commit groups.
The safest value for `sync_binlog` is 1 (the default), but this is also the slowest.

In earlier MySQL releases, there was a chance of inconsistency between the table content and binary log content if a crash occurred, even with `sync_binlog` set to 1.
For example, if you are using `InnoDB` tables and the MySQL server processes a `COMMIT` statement, it writes many prepared transactions to the binary log in sequence, synchronizes the binary log, and then commits the transaction into `InnoDB`. If the server unexpectedly exited between those two operations, the transaction would be rolled back by `InnoDB` at restart but still exist in the binary log. Such an issue was resolved in previous releases by enabling `InnoDB` support for two-phase commit in XA transactions. In 8.0.0 and higher, the `InnoDB` support for two-phase commit in XA transactions is always enabled.

`InnoDB` support for two-phase commit in XA transactions ensures that the binary log and `InnoDB` data files are synchronized. However, the MySQL server should also be configured to synchronize the binary log and the `InnoDB` logs to disk before committing the transaction. The `InnoDB` logs are synchronized by default, and `sync_binlog=1` ensures the binary log is synchronized. The effect of implicit `InnoDB` support for two-phase commit in XA transactions and `sync_binlog=1` is that at restart after a crash, after doing a rollback of transactions, the MySQL server scans the latest binary log file to collect transaction *`xid`* values and calculate the last valid position in the binary log file. The MySQL server then tells `InnoDB` to complete any prepared transactions that were successfully written to the to the binary log, and truncates the binary log to the last valid position. This ensures that the binary log reflects the exact data of `InnoDB` tables, and therefore the replica remains in synchrony with the source because it does not receive a statement which has been rolled back.

## Slow Query Log

The slow query log consists of SQL statements that take more than `long_query_time` seconds to execute and require at least `min_examined_row_limit` rows to be examined.
The slow query log can be used to find queries that take a long time to execute and are therefore candidates for optimization.
However, examining a long slow query log can be a time-consuming task. To make this easier, you can use the **mysqldumpslow** command to process a slow query log file and summarize its contents.

```
long_query_time	10.000000
log_slow_admin_statements	ON
log_slow_disabled_statements	sp
log_slow_filter	admin,filesort,filesort_on_disk,filesort_priority_queue,full_join,full_scan,query_cache,query_cache_miss,tmp_table,tmp_table_on_disk
log_slow_rate_limit	1
log_slow_slave_statements	ON
log_slow_verbosity
slow_launch_time	2

slow_query_log	ON // must be ON
log_queries_not_using_indexes	ON

slow_query_log_file	demo-slow.log
```

```sql

mysql> SELECT * FROM mysql.slow_log;
```

```sql
set long_query_time=0;

```
