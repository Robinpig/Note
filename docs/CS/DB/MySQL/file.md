## Server

## Config File

```shell
mysql --help | grep my.cnf
```

## Log Files

MySQL 实现了多种类型的日志，各自承担不同的职责

- [Error Log](/docs/CS/DB/MySQL/serverlog.md?id=error-log)
- [slow query Log](/docs/CS/DB/MySQL/serverlog.md?id=slow-query-log)
- [General Query Log](/docs/CS/DB/MySQL/serverlog.md?id=General-Query-Log)
- [binlog](/docs/CS/DB/MySQL/serverlog.md?id=binary-log)

Only InnoDB:

- [Redo Log](/docs/CS/DB/MySQL/redolog.md)
- [undo Log](/docs/CS/DB/MySQL/undolog.md)

二进制日志只在事务提交时记录，对于每个事务，只包含对应事务的一条日志。
而对于 InnoDB 存储引擎的 redo 日志，由于它们的记录是物理操作日志，每个事务对应多条日志条目，
并且事务的 redo 日志写入是并发的，不是在事务提交时写入，它们在文件中记录的顺序也不是事务开始的顺序。

InnoDB 在事务期间生成 redo log，并且即使在事务尚未提交时也可能同步到磁盘。

## Table file

.frm

## InnoDB

tablespace file : `ibdata`

从 MySQL 8 开始，frm 文件合并到 ibd 文件中。

```shell
/usr/local/mysql/bin/ibd2sdi --dump-file=a.txt a.ibd
```

```sql
SHOW VARIABLES LIKE 'datadir';
-- /usr/local/mysql/data
```

## Links

- [MySQL](/docs/CS/DB/MySQL/MySQL.md)
