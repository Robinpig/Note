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


## Table file

.frm

## InnoDB

tablespace file : `ibdata`


```sql
SHOW VARIABLES LIKE 'datadir';
-- /usr/local/mysql/data
```

## Links

- [MySQL](/docs/CS/DB/MySQL/MySQL.md)