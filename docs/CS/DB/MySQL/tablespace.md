## 





## Undo Tablespace


Undo tablespaces contain [undo logs](/docs/CS/DB/MySQL/undolog.md), which are collections of records containing information about how to undo the latest change by a transaction to a clustered index record.

Two default undo tablespaces are created when the MySQL instance is initialized. 
Default undo tablespaces are created at initialization time to provide a location for rollback segments that must exist before SQL statements can be accepted. 

A MySQL instance supports up to 127 undo tablespaces including the two default undo tablespaces created when the MySQL instance is initialized.


## Links

- [InnoDB Storage Engine](/docs/CS/DB/MySQL/InnoDB.md)