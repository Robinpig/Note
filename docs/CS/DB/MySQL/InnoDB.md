## Introduction

`InnoDB` is a general-purpose storage engine that balances high reliability and high performance. In MySQL 8.0, `InnoDB` is the default MySQL storage engine. Unless you have configured a different default storage engine, issuing a [`CREATE TABLE`](https://dev.mysql.com/doc/refman/8.0/en/create-table.html) statement without an `ENGINE` clause creates an `InnoDB` table.



### Key Advantages of InnoDB

- Its DML operations follow the ACID model, with transactions featuring commit, rollback, and crash-recovery capabilities to protect user data. See [Section 15.2, “InnoDB and the ACID Model”](https://dev.mysql.com/doc/refman/8.0/en/mysql-acid.html).
- Row-level locking and Oracle-style consistent reads increase multi-user concurrency and performance. See [Section 15.7, “InnoDB Locking and Transaction Model”](https://dev.mysql.com/doc/refman/8.0/en/innodb-locking-transaction-model.html).
- `InnoDB` tables arrange your data on disk to optimize queries based on primary keys. Each `InnoDB` table has a primary key index called the clustered index that organizes the data to minimize I/O for primary key lookups. See [Section 15.6.2.1, “Clustered and Secondary Indexes”](https://dev.mysql.com/doc/refman/8.0/en/innodb-index-types.html).
- To maintain data integrity, `InnoDB` supports `FOREIGN KEY` constraints. With foreign keys, inserts, updates, and deletes are checked to ensure they do not result in inconsistencies across related tables. 



**InnoDB Storage Engine Features**

| Feature                                                      | Support                                                      |
| :----------------------------------------------------------- | :----------------------------------------------------------- |
| **B-tree indexes**                                           | Yes                                                          |
| **Backup/point-in-time recovery** (Implemented in the server, rather than in the storage engine.) | Yes                                                          |
| **Cluster database support**                                 | No                                                           |
| **Clustered indexes**                                        | Yes                                                          |
| **Compressed data**                                          | Yes                                                          |
| **Data caches**                                              | Yes                                                          |
| **Encrypted data**                                           | Yes (Implemented in the server via encryption functions; In MySQL 5.7 and later, data-at-rest encryption is supported.) |
| **Foreign key support**                                      | Yes                                                          |
| **Full-text search indexes**                                 | Yes (Support for FULLTEXT indexes is available in MySQL 5.6 and later.) |
| **Geospatial data type support**                             | Yes                                                          |
| **Geospatial indexing support**                              | Yes (Support for geospatial indexing is available in MySQL 5.7 and later.) |
| **Hash indexes**                                             | No (InnoDB utilizes hash indexes internally for its Adaptive Hash Index feature.) |
| **Index caches**                                             | Yes                                                          |
| **Locking granularity**                                      | Row                                                          |
| **MVCC**                                                     | Yes                                                          |
| **Replication support** (Implemented in the server, rather than in the storage engine.) | Yes                                                          |
| **Storage limits**                                           | 64TB                                                         |
| **T-tree indexes**                                           | No                                                           |
| **Transactions**                                             | Yes                                                          |
| **Update statistics for data dictionary**                    | Yes                                                          |



## [InnoDB Locking and Transaction Model](/docs/CS/DB/MySQL/Transaction.md)

## InnoDB Architecture

The following diagram shows in-memory and on-disk structures that comprise the `InnoDB` storage engine architecture. For information about each structure.

![InnoDB architecture diagram showing in-memory and on-disk structures. In-memory structures include the buffer pool, adaptive hash index, change buffer, and log buffer. On-disk structures include tablespaces, redo logs, and doublewrite buffer files.](https://dev.mysql.com/doc/refman/8.0/en/images/innodb-architecture.png)

### InnoDB In-Memory Structures

- [15.5.1 Buffer Pool](https://dev.mysql.com/doc/refman/8.0/en/innodb-buffer-pool.html)
- [15.5.2 Change Buffer](https://dev.mysql.com/doc/refman/8.0/en/innodb-change-buffer.html)
- [15.5.3 Adaptive Hash Index](https://dev.mysql.com/doc/refman/8.0/en/innodb-adaptive-hash.html)
- [15.5.4 Log Buffer](https://dev.mysql.com/doc/refman/8.0/en/innodb-redo-log-buffer.html)

### InnoDB On-Disk Structures

- [15.6.1 Tables](https://dev.mysql.com/doc/refman/8.0/en/innodb-tables.html)
- [15.6.2 Indexes](https://dev.mysql.com/doc/refman/8.0/en/innodb-indexes.html)
- [15.6.3 Tablespaces](https://dev.mysql.com/doc/refman/8.0/en/innodb-tablespace.html)
- [15.6.4 Doublewrite Buffer](https://dev.mysql.com/doc/refman/8.0/en/innodb-doublewrite-buffer.html)
- [15.6.5 Redo Log](https://dev.mysql.com/doc/refman/8.0/en/innodb-redo-log.html)
- [15.6.6 Undo Logs](https://dev.mysql.com/doc/refman/8.0/en/innodb-undo-logs.html)





### Optimizing InnoDB Transaction Management

To optimize `InnoDB` transaction processing, find the ideal balance between the performance overhead of transactional features and the workload of your server. For example, an application might encounter performance issues if it commits thousands of times per second, and different performance issues if it commits only every 2-3 hours.

- The default MySQL setting `AUTOCOMMIT=1` can impose performance limitations on a busy database server. Where practical, wrap several related data change operations into a single transaction, by issuing `SET AUTOCOMMIT=0` or a `START TRANSACTION` statement, followed by a `COMMIT` statement after making all the changes.

  `InnoDB` must flush the log to disk at each transaction commit if that transaction made modifications to the database. When each change is followed by a commit (as with the default autocommit setting), the I/O throughput of the storage device puts a cap on the number of potential operations per second.

- Alternatively, for transactions that consist only of a single [`SELECT`](https://dev.mysql.com/doc/refman/8.0/en/select.html) statement, turning on `AUTOCOMMIT` helps `InnoDB` to recognize read-only transactions and optimize them. See [Section 8.5.3, “Optimizing InnoDB Read-Only Transactions”](https://dev.mysql.com/doc/refman/8.0/en/innodb-performance-ro-txn.html) for requirements.

- Avoid performing rollbacks after inserting, updating, or deleting huge numbers of rows. If a big transaction is slowing down server performance, rolling it back can make the problem worse, potentially taking several times as long to perform as the original data change operations. Killing the database process does not help, because the rollback starts again on server startup.

  To minimize the chance of this issue occurring:

  - Increase the size of the [buffer pool](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_buffer_pool) so that all the data change changes can be cached rather than immediately written to disk.
  - Set [`innodb_change_buffering=all`](https://dev.mysql.com/doc/refman/8.0/en/innodb-parameters.html#sysvar_innodb_change_buffering) so that update and delete operations are buffered in addition to inserts.
  - Consider issuing `COMMIT` statements periodically during the big data change operation, possibly breaking a single delete or update into multiple statements that operate on smaller numbers of rows.

  To get rid of a runaway rollback once it occurs, increase the buffer pool so that the rollback becomes CPU-bound and runs fast, or kill the server and restart with [`innodb_force_recovery=3`](https://dev.mysql.com/doc/refman/8.0/en/innodb-parameters.html#sysvar_innodb_force_recovery), as explained in [Section 15.18.2, “InnoDB Recovery”](https://dev.mysql.com/doc/refman/8.0/en/innodb-recovery.html).

  This issue is expected to be infrequent with the default setting [`innodb_change_buffering=all`](https://dev.mysql.com/doc/refman/8.0/en/innodb-parameters.html#sysvar_innodb_change_buffering), which allows update and delete operations to be cached in memory, making them faster to perform in the first place, and also faster to roll back if needed. Make sure to use this parameter setting on servers that process long-running transactions with many inserts, updates, or deletes.

- If you can afford the loss of some of the latest committed transactions if an unexpected exit occurs, you can set the [`innodb_flush_log_at_trx_commit`](https://dev.mysql.com/doc/refman/8.0/en/innodb-parameters.html#sysvar_innodb_flush_log_at_trx_commit) parameter to 0. `InnoDB` tries to flush the log once per second anyway, although the flush is not guaranteed.

- When rows are modified or deleted, the rows and associated [undo logs](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_undo_log) are not physically removed immediately, or even immediately after the transaction commits. The old data is preserved until transactions that started earlier or concurrently are finished, so that those transactions can access the previous state of modified or deleted rows. Thus, a long-running transaction can prevent `InnoDB` from purging data that was changed by a different transaction.

- When rows are modified or deleted within a long-running transaction, other transactions using the [`READ COMMITTED`](https://dev.mysql.com/doc/refman/8.0/en/innodb-transaction-isolation-levels.html#isolevel_read-committed) and [`REPEATABLE READ`](https://dev.mysql.com/doc/refman/8.0/en/innodb-transaction-isolation-levels.html#isolevel_repeatable-read) isolation levels have to do more work to reconstruct the older data if they read those same rows.

- When a long-running transaction modifies a table, queries against that table from other transactions do not make use of the [covering index](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_covering_index) technique. Queries that normally could retrieve all the result columns from a secondary index, instead look up the appropriate values from the table data.

  If secondary index pages are found to have a `PAGE_MAX_TRX_ID` that is too new, or if records in the secondary index are delete-marked, `InnoDB` may need to look up records using a clustered index.



## References

1. [Introduction to InnoDB](https://dev.mysql.com/doc/refman/8.0/en/innodb-introduction.html)