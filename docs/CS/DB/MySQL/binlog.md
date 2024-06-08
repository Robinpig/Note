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
The effect of implicit InnoDB support for two-phase commit in XA transactions and sync_binlog=1 is that at restart after a crash, after doing a rollback of transactions, the MySQL server scans the latest binary log file to collect transaction xid values and calculate the last valid position in the binary log file. 
The MySQL server then tells InnoDB to complete any prepared transactions that were successfully written to the to the binary log, and truncates the binary log to the last valid position. 
This ensures that the binary log reflects the exact data of InnoDB tables, and therefore the replica remains in synchrony with the source because it does not receive a statement which has been rolled back.

If the MySQL server discovers at crash recovery that the binary log is shorter than it should have been, it lacks at least one successfully committed InnoDB transaction. 
This should not happen if sync_binlog=1 and the disk/file system do an actual sync when they are requested to (some do not), so the server prints an error message The binary log file_name is shorter than its expected size. 
In this case, this binary log is not correct and replication should be restarted from a fresh snapshot of the source's data.


## sync


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