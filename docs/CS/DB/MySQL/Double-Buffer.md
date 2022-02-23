## Introduction



The doublewrite buffer is a storage area where `InnoDB` writes pages flushed from the buffer pool before writing the pages to their proper positions in the `InnoDB` data files. 
If there is an operating system, storage subsystem, or unexpected `mysqld` process exit in the middle of a page write, `InnoDB` can find a good copy of the page from the doublewrite buffer during crash recovery.

Although data is written twice, the doublewrite buffer does not require twice as much I/O overhead or twice as many I/O operations. 
Data is written to the doublewrite buffer in a large sequential chunk, with a single `fsync()` call to the operating system (except in the case that `innodb_flush_method` is set to `O_DIRECT_NO_FSYNC`).

Prior to MySQL 8.0.20, the doublewrite buffer storage area is located in the `InnoDB` system tablespace. 
As of MySQL 8.0.20, the doublewrite buffer storage area is located in doublewrite files.



The following variables are provided for doublewrite buffer configuration:

- The `innodb_doublewrite` variable controls whether the doublwrite buffer is enabled. 
- The `innodb_doublewrite_dir` variable (introduced in MySQL 8.0.20) defines the directory where `InnoDB` creates doublewrite files.
- The `innodb_doublewrite_files` variable defines the number of doublewrite files. 
  By default, two doublewrite files are created for each buffer pool instance: A flush list doublewrite file and an LRU list doublewrite file.

## Links

- [InnoDB Storage Engine](/docs/CS/DB/MySQL/InnoDB.md)