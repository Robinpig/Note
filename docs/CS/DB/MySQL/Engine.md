## Introduction



```shell
mysql> select version();
10.3.27-MariaDB
```

| Engine             | Support | Comment                                                      | Transactions | XA       | Savepoints |
| ------------------ | ------- | ------------------------------------------------------------ | ------------ | -------- | ---------- |
| MEMORY             | YES     | Hash based, stored in memory, useful for temporary tables    | NO           | NO       | NO         |
| MRG_MyISAM         | YES     | Collection of identical MyISAM tables                        | NO           | NO       | NO         |
| CSV                | YES     | Stores tables as CSV files                                   | NO           | NO       | NO         |
| BLACKHOLE          | YES     | /dev/null storage engine (anything you write to it disappears) | NO           | NO       | NO         |
| MyISAM             | YES     | Non-transactional engine with good performance and small data footprint | NO           | NO       | NO         |
| ARCHIVE            | YES     | gzip-compresses tables for a low storage footprint           | NO           | NO       | NO         |
| FEDERATED          | YES     | Allows to access tables on other MariaDB servers, supports transactions and more | YES          | NO       | YES        |
| PERFORMANCE_SCHEMA | YES     | Performance Schema                                           | NO           | NO	NO |            |
| SEQUENCE           | YES     | Generated tables filled with sequential values               | YES	NO    | YES      |            |
| InnoDB             | DEFAULT | Supports transactions, row-level locking, foreign keys and encryption for tables | YES          | YES      | YES        |
| Aria               | YES     | Crash-safe tables with MyISAM heritage                       | NO           | NO       | NO         |



```shell
mysql> select version();
5.7.34
```

| Engine             | Support | Comment                                                      | Transactions | XA   | Savepoints |
| ------------------ | ------- | ------------------------------------------------------------ | ------------ | ---- | ---------- |
| InnoDB             | DEFAULT | Supports transactions, row-level locking, and foreign keys   | YES          | YES  | YES        |
| MRG_MYISAM         | YES     | Collection of identical MyISAM tables                        | NO           | NO   | NO         |
| MEMORY             | YES     | Hash based, stored in memory, useful for temporary tables    | NO           | NO   | NO         |
| BLACKHOLE          | YES     | /dev/null storage engine (anything you write to it disappears) | NO           | NO   | NO         |
| MyISAM             | YES     | MyISAM storage engine                                        | NO           | NO   | NO         |
| CSV                | YES     | CSV storage engine                                           | NO           | NO   | NO         |
| ARCHIVE            | YES     | Archive storage engine                                       | NO           | NO   | NO         |
| PERFORMANCE_SCHEMA | YES     | Performance Schema                                           | NO           | NO   | NO         |
| FEDERATED          | NO      | Federated MySQL storage engine                               | NULL         | NULL | NULL       |



###  

## References
