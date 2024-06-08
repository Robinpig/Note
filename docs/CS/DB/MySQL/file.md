## Server

## Config File

```shell
mysql --help | grep my.cnf
```

## Log Files

- [Error Log](/docs/CS/DB/MySQL/serverlog.md?id=error-log)
- [slow query Log](/docs/CS/DB/MySQL/serverlog.md?id=slow-query-log)
- [General Query Log](/docs/CS/DB/MySQL/serverlog.md?id=General-Query-Log)
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


## Table file

.frm

## InnoDB

tablespace file : `ibdata`

Since MySQL8, the frm file merge into ibd file.

```shell
/usr/local/mysql/bin/ibd2sdi --dump-file=a.txt a.ibd
```

```sql
SHOW VARIABLES LIKE 'datadir';
-- /usr/local/mysql/data
```

## Links

- [MySQL](/docs/CS/DB/MySQL/MySQL.md)
