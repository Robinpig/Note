## Introduction

The binary log contains “events” that describe database changes such as table creation operations or changes to table data.
It also contains events for statements that potentially could have made changes (for example, a DELETE which matched no rows), unless row-based logging is used.
The binary log also contains information about how long each statement took that updated data.
**The binary log is not used for statements such as SELECT or SHOW that do not modify data.**

The binary log has two important purposes:

- **For replication**, the binary log on a replication source server provides a record of the data changes to be sent to replicas.
  The source sends the information contained in its binary log to its replicas, which reproduce those transactions to make the same data changes that were made on the source.
- **Certain data recovery operations** require use of the binary log.
  After a backup has been restored, the events in the binary log that were recorded after the backup was made are re-executed.
  These events bring databases up to date from the point of the backup.


## Binary Logging Formats

The server uses several logging formats to record information in the binary log:

- Replication capabilities in MySQL originally were based on propagation of SQL statements from source to replica. 
  This is called statement-based logging. You can cause this format to be used by starting the server with --binlog-format=STATEMENT.
- In row-based logging (the default), the source writes events to the binary log that indicate how individual table rows are affected. 
  You can cause the server to use row-based logging by starting it with --binlog-format=ROW.
- A third option is also available: mixed logging. 
  With mixed logging, statement-based logging is used by default, but the logging mode switches automatically to row-based in certain cases as described below. 
  You can cause MySQL to use mixed logging explicitly by starting mysqld with the option --binlog-format=MIXED.

With statement-based replication, there may be issues with replicating nondeterministic statements. 
In deciding whether or not a given statement is safe for statement-based replication, MySQL determines whether it can guarantee that the statement can be replicated using statement-based logging. 
If MySQL cannot make this guarantee, it marks the statement as potentially unreliable and issues the warning, Statement may not be safe to log in statement format.
You can avoid these issues by using MySQL's row-based replication instead.


## file sync

By default, the binary log is synchronized to disk at each write (sync_binlog=1).
If sync_binlog was not enabled, and the operating system or machine (not only the MySQL server) crashed, there is a chance that the last statements of the binary log could be lost.
To prevent this, enable the sync_binlog system variable to synchronize the binary log to disk after every N commit groups.


In earlier MySQL releases, there was a chance of inconsistency between the table content and binary log content if a crash occurred, even with sync_binlog set to 1. 
For example, if you are using InnoDB tables and the MySQL server processes a COMMIT statement, it writes many prepared transactions to the binary log in sequence, synchronizes the binary log, and then commits the transaction into InnoDB. 
If the server unexpectedly exited between those two operations, the transaction would be rolled back by InnoDB at restart but still exist in the binary log. 
Such an issue was resolved in previous releases by enabling InnoDB support for two-phase commit in XA transactions. 
In 8.0.0 and higher, the InnoDB support for two-phase commit in XA transactions is always enabled.

InnoDB support for two-phase commit in XA transactions ensures that the binary log and InnoDB data files are synchronized. 
However, the MySQL server should also be configured to synchronize the binary log and the InnoDB logs to disk before committing the transaction. 
The InnoDB logs are synchronized by default, and sync_binlog=1 ensures the binary log is synchronized. 
The effect of implicit InnoDB support for two-phase commit in XA transactions and sync_binlog=1 is that at restart after a crash, after doing a rollback of transactions,
the MySQL server scans the latest binary log file to collect transaction xid values and calculate the last valid position in the binary log file. 
The MySQL server then tells InnoDB to complete any prepared transactions that were successfully written to the to the binary log, and truncates the binary log to the last valid position. 
This ensures that the binary log reflects the exact data of InnoDB tables, and therefore the replica remains in synchrony with the source because it does not receive a statement which has been rolled back.

If the MySQL server discovers at crash recovery that the binary log is shorter than it should have been, it lacks at least one successfully committed InnoDB transaction. 
This should not happen if sync_binlog=1 and the disk/file system do an actual sync when they are requested to (some do not), so the server prints an error message The binary log file_name is shorter than its expected size. 
In this case, this binary log is not correct and replication should be restarted from a fresh snapshot of the source's data.


## sync



同一个事务产生的 binlog event，在 binlog 日志文件中是连续的
每个事务都有两个 binlog cache：
stmt_cache：改变（插入、更新、删除）不支持事务的表，产生的 binlog event，临时存放在这里。
trx_cache：改变（插入、更新、删除）支持事务的表，产生的 binlog event，临时存放在这里。

事务执行过程中，产生的所有 binlog event，都会先写入 trx_cache。trx_cache 分为两级：
第一级：内存，也称为 buffer，它的大小用 buffer_length 表示，由系统变量 binlog_cache_size 控制，默认为 32K。
第二级：临时文件，位于操作系统的 tmp 目录下，文件名以 ML 开头。
buffer_length 加上临时文件中已经写入的 binlog 占用的字节数，也有一个上限，由系统变量 max_binlog_cache_size 控制
如果一条 SQL 语句改变了（插入、更新、删除）表中的数据，server 层会为这条 SQL 语句产生一个包含表名和表 ID 的 Table_map_log_event。
每次调用存储引擎的方法写入一条记录到表中之后，server 层都会为这条记录产生 binlog。
这里没有写成 binlog event，是因为记录中各字段内容都很少的时候，多条记录可以共享同一个 binlog event ，并不需要为每条记录都产生一个新的 binlog event。
多条记录产生的 binlog 共享同一个 binlog event 时，这个 binlog event 最多可以存放多少字节的内容，由系统变量 binlog_row_event_max_size 控制，默认为 8192 字节。
如果一条记录产生的 binlog 超过了 8192 字节，它的 binlog 会独享一个 binlog event，这个 binlog event 的大小就不受系统变量 binlog_row_event_max_size 控制了。
在 binlog 日志文件中，Table_map_log_event 位于 SQL 语句改变表中数据产生的 binlog event 之前


如果没有开启 binlog，SQL 语句改变表中数据，不产生 binlog，不用保证 binlog 和表中数据的一致性，用户事务也就不需要使用二阶段提交了。
InnoDB 内部事务是个特例，不管是否开启了 binlog，改变表中数据都不会产生 binlog 日志，所以内部事务不需要使用二阶段提交


调用 ha_prepare_low () 之前，用户线程对象的 durability_property 属性值会被设置为 HA_IGNORE_DURABILITY 为了不让 redo log 在prepare阶段刷盘 可以在binlog commit的时候一起刷盘

Set HA_IGNORE_DURABILITY to not flush the prepared record of the  transaction to the log of storage engine (for example, InnoDB redo log) during the prepare phase.
So that we can flush prepared  records of transactions to the log of storage engine in a group right before flushing them to binary log during binlog group  commit flush stage.
Reset to HA_REGULAR_DURABILITY at the beginning of parsing next command.


```c++
/*
  Prepare the transaction in the transaction coordinator.

  This function will prepare the transaction in the storage engines
  (by calling @c ha_prepare_low) what will write a prepare record
  to the log buffers.
*/
int MYSQL_BIN_LOG::prepare(THD *thd, bool all) {
  DBUG_TRACE;

  thd->durability_property = HA_IGNORE_DURABILITY;

  CONDITIONAL_SYNC_POINT_FOR_TIMESTAMP("before_prepare_in_engines");
  int error = ha_prepare_low(thd, all);

  CONDITIONAL_SYNC_POINT_FOR_TIMESTAMP("after_ha_prepare_low");
  // Invoke `commit` if we're dealing with `XA PREPARE` in order to use BCG
  // to write the event to file.
  if (!error && all && is_xa_prepare(thd)) return this->commit(thd, true);

  return error;
}
```



```c++
int ha_prepare_low(THD *thd, bool all) {
  DBUG_TRACE;
  int error = 0;
  Transaction_ctx::enum_trx_scope trx_scope =
      all ? Transaction_ctx::SESSION : Transaction_ctx::STMT;
  auto ha_list = thd->get_transaction()->ha_trx_info(trx_scope);

  if (ha_list) {
    for (auto const &ha_info : ha_list) {
      if (!ha_info.is_trx_read_write() &&  // Do not call two-phase commit if
                                           // transaction is read-only
          !thd_holds_xa_transaction(thd))  // but only if is not an XA
                                           // transaction
        continue;

      auto ht = ha_info.ht();
      int err = ht->prepare(ht, thd, all);
      if (err) {
        if (!thd_holds_xa_transaction(
                thd)) {  // If XA PREPARE, let error be handled by caller
          char errbuf[MYSQL_ERRMSG_SIZE];
          my_error(ER_ERROR_DURING_COMMIT, MYF(0), err,
                   my_strerror(errbuf, MYSQL_ERRMSG_SIZE, err));
        }
        error = 1;
      }
      assert(!thd->status_var_aggregated);
      thd->status_var.ha_prepare_count++;

      if (error) break;
    }
    DBUG_EXECUTE_IF("crash_commit_after_prepare", DBUG_SUICIDE(););
  }

  return error;
}
```

InnoDB prepare 会把分配给事务的所有 undo 段的状态修改为 TRX_UNDO_PREPARED，把事务 Xid 写入 undo 日志组的头信息，把内存中事务对象的状态修改为 TRX_STATE_PREPARED



trx_flush_logs () 的作用是把事务产生的 redo 日志刷盘


```c++
static void trx_flush_logs(trx_t *trx, lsn_t lsn) {
  if (lsn == 0) {
    return;
  }
  switch (thd_requested_durability(trx->mysql_thd)) {
    case HA_IGNORE_DURABILITY:
      /* We set the HA_IGNORE_DURABILITY during prepare phase of
      binlog group commit to not flush redo log for every transaction
      here. So that we can flush prepared records of transactions to
      redo log in a group right before writing them to binary log
      during flush stage of binlog group commit. */
      break;
    case HA_REGULAR_DURABILITY:
      /* Depending on the my.cnf options, we may now write the log
      buffer to the log files, making the prepared state of the
      transaction durable if the OS does not crash. We may also
      flush the log files to disk, making the prepared state of the
      transaction durable also at an OS crash or a power outage.

      The idea in InnoDB's group prepare is that a group of
      transactions gather behind a trx doing a physical disk write
      to log files, and when that physical write has been completed,
      one of those transactions does a write which prepares the whole
      group. Note that this group prepare will only bring benefit if
      there are > 2 users in the database. Then at least 2 users can
      gather behind one doing the physical log write to disk.

      We must not be holding any mutexes or latches here. */

      /* We should trust trx->ddl_operation instead of
      ddl_must_flush here */
      trx->ddl_must_flush = false;
      trx_flush_log_if_needed(lsn, trx);
  }
}
```

二阶段提交的 commit 阶段，分为三个子阶段。
flush 子阶段，触发操作系统把 prepare 阶段及之前产生的 redo 日志刷盘。
把事务执行过程中产生的 binlog 日志写入 binlog 日志文件 即page cache

sync 子阶段，根据系统变量 sync_binlog 的值决定是否要触发操作系统马上把 page cache 中的 binlog 日志刷盘。
commit 子阶段，完成 InnoDB 的事务提交。

flush 子阶段会触发 redo 日志刷盘，sync 子阶段可能会触发 binlog 日志刷盘，都涉及到磁盘 IO。

flinkcdc

### ES

使用 canal 将 MySQL 增量数据同步到 ES 。

MySQL , 需要先开启 Binlog 写入功能，配置 binlog-format 为 ROW 模式

授权 canal 链接 MySQL 账号具有作为 MySQL slave

```mysql
CREATE USER canal IDENTIFIED BY 'canal';  
GRANT SELECT, REPLICATION SLAVE, REPLICATION CLIENT ON *.* TO 'canal'@'%';
-- GRANT ALL PRIVILEGES ON *.* TO 'canal'@'%' ;
FLUSH PRIVILEGES;
```




## Links

- [InnoDB Storage Engine](/docs/CS/DB/MySQL/InnoDB.md)