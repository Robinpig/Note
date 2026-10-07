## Introduction

The doublewrite buffer is a storage area where `InnoDB` writes pages flushed from the buffer pool before writing the pages to their proper positions in the `InnoDB` data files. InnoDB writes a page to its final data-file location only after it is safely flushed to the doublewrite area. When recovering after a crash, InnoDB scans the doublewrite files and, for each valid page there, checks whether the corresponding page in the data file is valid and repairs torn pages.

| 项 | 值 |
| :--- | :--- |
| 正文默认版本 | MySQL 9.7.x LTS（最新 9.7.3，2026-08-18） |
| 源码核实基线 | tag `mysql-9.7.2` |
| 次要兼容目标 | 8.4.x LTS |
| 已停止支持 | 8.0（EOL 2026-04-30）、5.7（EOL 2023-10） |
| 核实日期 | 2026-10-07 |

Although data is written twice, the doublewrite buffer does not require twice as much I/O overhead or twice as many I/O operations. Data is written to the doublewrite area in a large sequential chunk, with a single `fsync()` call to the operating system (except in the case that `innodb_flush_method` is set to `O_DIRECT_NO_FSYNC`).

> [!NOTE]
> Prior to MySQL 8.0.20, the doublewrite buffer storage area is located in the `InnoDB` system tablespace. As of MySQL 8.0.20, it is located in dedicated doublewrite files.

## Configuration Variables

The following variables are provided for doublewrite buffer configuration:

- The `innodb_doublewrite` variable controls whether the doublewrite buffer is enabled.
- The `innodb_doublewrite_dir` variable (introduced in MySQL 8.0.20) defines the directory where `InnoDB` creates the doublewrite files.
- The `innodb_doublewrite_files` variable defines the number of doublewrite files (default `2`, range `1` to `256`). By default, two doublewrite files are created for each buffer pool instance: a flush list doublewrite file and an LRU list doublewrite file.
- The `innodb_doublewrite_pages` variable sets the number of doublewrite pages (default `128`, range `1` to `512`).
- The `innodb_doublewrite_batch_size` variable sets the number of doublewrite pages written in a batch; the default `0` means InnoDB determines the batch size automatically (range `0` to `256`).

## Implementation

In the 9.7 source tree the doublewrite implementation lives in `storage/innobase/buf/buf0dblwr.cc`, inside `namespace dblwr` (declared in `storage/innobase/include/buf0dblwr.h`).

> [!WARNING]
> Production servers should never have the doublewrite buffer disabled. If you do so to load data faster (during maintenance), enable it again immediately after reloading the database.

## Links

- [InnoDB 存储引擎](/docs/CS/DB/MySQL/InnoDB.md)
- [memory Buffer Pool](/docs/CS/DB/MySQL/memory.md)
- [redo log](/docs/CS/DB/MySQL/redolog.md)
- [tablespace](/docs/CS/DB/MySQL/tablespace.md)

## References

- [MySQL 8.4 Reference Manual: The InnoDB Doublewrite Buffer](https://dev.mysql.com/doc/refman/8.4/en/innodb-doublewrite-buffer.html)
