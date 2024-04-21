## Introduction

The system tablespace is the storage area for the change buffer.


It may also contain table and index data if tables are created in the system tablespace rather than file-per-table or general tablespaces. In previous MySQL versions, the system tablespace contained the `InnoDB` data dictionary. In MySQL 8.0, `InnoDB` stores metadata in the MySQL data dictionary.
In previous MySQL releases, the system tablespace also contained the doublewrite buffer storage area. This storage area resides in separate doublewrite files as of MySQL 8.0.20.

The system tablespace can have one or more data files. By default, a single system tablespace data file, named `ibdata1`, is created in the data directory. The size and number of system tablespace data files is defined by the [`innodb_data_file_path`](https://dev.mysql.com/doc/refman/8.0/en/innodb-parameters.html#sysvar_innodb_data_file_path) startup option.



- COMPACT
- REDUNDANT
- DYNAMIC
- COMPRESSED

```sql
CREATE TABLE XXX ROW_FORMAT=FORMAT;
```

system tablespace

ibdata1



## Undo Tablespace

see [Undo Tablespace](/docs/CS/DB/MySQL/undolog.md?id=undo-tablespaces)

## Links

- [InnoDB Storage Engine](/docs/CS/DB/MySQL/InnoDB.md?id=innodb-on-disk-structures)
