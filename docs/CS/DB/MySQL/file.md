## Introduction

这页回答一个问题：**一个 MySQL 实例在磁盘上到底有哪些文件、各归谁管**。同一个 data directory 里混着两套体系——Server 层的配置文件与日志族（error log、slow query log、general query log、binlog），以及 InnoDB 自己的物理文件族（表空间、redo、undo、doublewrite、临时表空间）。分不清归属层，就会把「binlog 是不是 InnoDB 的日志」这类问题问错。

| 项 | 值 |
| :--- | :--- |
| 正文默认版本 | MySQL 9.7.x LTS（最新 9.7.3，2026-08-18） |
| 源码核实基线 | tag `mysql-9.7.2` |
| 次要兼容目标 | 8.4.x LTS |
| 已停止支持 | 8.0（EOL 2026-04-30）、5.7（EOL 2023-10） |
| 核实日期 | 2026-10-07 |

## Config File

```shell
mysql --help | grep my.cnf
```

`mysqld` 与客户端按固定顺序读取若干 option file，后者覆盖前者；确切顺序见 References 的 Option File Usage 一节。

## Log Files

MySQL 实现了多种类型的日志，各自承担不同的职责

Server 层：

- [Error Log](/docs/CS/DB/MySQL/serverlog.md?id=error-log)
- [slow query Log](/docs/CS/DB/MySQL/serverlog.md?id=slow-query-log)
- [General Query Log](/docs/CS/DB/MySQL/serverlog.md?id=general-query-log)
- [binlog](/docs/CS/DB/MySQL/serverlog.md?id=binary-log)

Only InnoDB:

- [Redo Log](/docs/CS/DB/MySQL/redolog.md)
- [undo Log](/docs/CS/DB/MySQL/undolog.md)

The binary log is only logged when the transaction commits, and for each transaction, it is only logged when the transaction commits,
and for each transaction, only one log of the corresponding transaction is included. 
For the redo logs of the InnoDB storage engine,
because their records are physical operations logs, each transaction corresponds to multiple log entries, 
and the redo log writes for the transaction are concurrent, 
not written at transaction commits, and the order in which they are recorded in the file is not the order in which the transaction begins.

innodb produce redo log during transaction and may sync to disk even if the transaction has not committed.

## Data Directory

```sql
SHOW VARIABLES LIKE 'datadir';
-- /usr/local/mysql/data
```

InnoDB 文件族（9.7 默认值均取自 9.7 手册与 9.7.2 源码）：

| 文件 / 目录 | 归属与内容 | 由什么控制 |
| :--- | :--- | :--- |
| `ibdata1`（可多文件） | 系统表空间，change buffer 的落盘位置 | `innodb_data_file_path`，默认 `ibdata1:12M:autoextend` |
| `数据库目录/表名.ibd` | file-per-table 表空间，内含该表的 B-tree 与一份 SDI | `innodb_file_per_table`，默认 ON |
| `mysql.ibd` | 数据字典表空间；8.0 起承载原先 `.frm` 里的表定义 | 不直接操作 |
| `#innodb_redo/#ib_redo N` | redo log 文件族，环形复用，备用文件带 `_tmp` 后缀 | `innodb_redo_log_capacity`，默认 100MB |
| `undo_001` / `undo_002`（或自定义 `.ibu`） | undo 表空间，回滚段与 undo 日志 | 9.7 只能走 `CREATE UNDO TABLESPACE`；`innodb_undo_directory` 决定位置 |
| doublewrite 文件（默认 2 个） | 双写缓冲的落盘区，8.0.20 起独立于系统表空间 | `innodb_doublewrite_files`，默认 2、范围 1–256 |
| `ibtmp1` 与 `#innodb_temp/` | 临时表空间，会话级内部临时表 | `innodb_temp_data_file_path` / `innodb_temp_tablespaces_dir` |
| `ib_buffer_pool` | 关机时 dump、启动时装回的热点页清单 | `innodb_buffer_pool_filename` |

## Table File

MySQL 8.0 之前，每张表在数据库目录下还有一个 `.frm` 文件，由 Server 层用来存表定义；InnoDB 只负责数据与索引。

8.0 起 **`.frm` 被取消**：表定义进入**事务型数据字典**（落在 `mysql.ibd`），因此 DDL 可以与所影响的表数据在同一事务里原子提交。此外每个**持久**表空间文件内部还保存一份 SDI（serialized dictionary information）：9.7 手册明确 SDI 存在于 file-per-table 与 general tablespace 的 `.ibd`、系统表空间的 `ibdata*` 以及 `mysql.ibd` 中，而临时表空间与 undo 表空间没有 SDI。

所以「frm 合并进 ibd 文件」这种说法并不准确——定义本体在数据字典表里，`.ibd` 内的 SDI 是一份便于表空间离线识别的副本。

```shell
ibd2sdi --dump-file=a.txt a.ibd
```

`ibd2sdi` 是提取 SDI 的官方工具，可在实例运行时或离线使用；它不支持临时表空间与 undo 表空间文件。

## Links

- [MySQL](/docs/CS/DB/MySQL/MySQL.md)
- [Tablespace](/docs/CS/DB/MySQL/tablespace.md)
- [InnoDB Storage Engine](/docs/CS/DB/MySQL/InnoDB.md)
- [Double-Buffer](/docs/CS/DB/MySQL/Double-Buffer.md)
- [Server Log](/docs/CS/DB/MySQL/serverlog.md)

## References

- [MySQL 9.7 Reference Manual: Data Directory](https://dev.mysql.com/doc/refman/9.7/en/data-directory.html)
- [MySQL 9.7 Reference Manual: Using Option Files](https://dev.mysql.com/doc/refman/9.7/en/option-files.html)
- [MySQL 9.7 Reference Manual: ibd2sdi — InnoDB Tablespace SDI Extraction Utility](https://dev.mysql.com/doc/refman/9.7/en/ibd2sdi.html)
- [MySQL 9.7 Reference Manual: The MySQL Data Dictionary](https://dev.mysql.com/doc/refman/9.7/en/data-dictionary.html)
