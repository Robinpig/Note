## Introduction

表空间（tablespace）是 InnoDB 逻辑存储结构的最高一层：一页一页的数据装在区（extent）里，区属于段（segment），段落在表空间中。这一页先分清 9.7 有哪几类表空间、各自落在哪个文件上，再讲页 / 区 / 段的分配规则与行格式。下面几段先说系统表空间，它是最容易被误解的一类——今天它已经不再装数据字典和 doublewrite。

The system tablespace is the storage area for the change buffer.


It may also contain table and index data if tables are created in the system tablespace rather than file-per-table or general tablespaces.
In previous MySQL versions, the system tablespace contained the `InnoDB` data dictionary. 
In MySQL 8.0, `InnoDB`  stores metadata in the MySQL data dictionary.
In previous MySQL releases, the system tablespace also contained the doublewrite buffer storage area. This storage area resides in separate doublewrite files as of MySQL 8.0.20.

The system tablespace can have one or more data files. 
By default, a single system tablespace data file, named  `ibdata1`, is created in the data directory. The size and number of system tablespace data files is defined by the  `innodb_data_file_path`  startup option.

| 项 | 值 |
| :--- | :--- |
| 正文默认版本 | MySQL 9.7.x LTS（最新 9.7.3，2026-08-18） |
| 源码核实基线 | tag `mysql-9.7.2` |
| 次要兼容目标 | 8.4.x LTS |
| 已停止支持 | 8.0（EOL 2026-04-30）、5.7（EOL 2023-10） |
| 核实日期 | 2026-10-07 |

## Tablespace Types

InnoDB 的逻辑存储层次是 tablespace → segment → extent → page → row；物理上「一张表的字节到底落在哪个文件」由表空间类型决定。9.7 的表空间家族如下（`innodb_data_file_path` 默认 `ibdata1:12M:autoextend`，`innodb_temp_data_file_path` 默认 `ibtmp1:12M:autoextend`，均取自 9.7 手册）：

| 类型 | 装什么 | 物理文件 | 怎么建 / 开关 |
| :--- | :--- | :--- | :--- |
| system tablespace | change buffer；旧版本里还有数据字典与 doublewrite buffer；显式建在其中的表与索引 | `ibdata1`（可多文件） | `innodb_data_file_path` |
| file-per-table | 单表的数据与索引 | 每个数据库目录下的 `表名.ibd` | `innodb_file_per_table`，9.7 默认 **ON** |
| general tablespace | 多张表共享的表空间 | 用户指定的 `xxx.ibd` | `CREATE TABLESPACE ... ADD DATAFILE` |
| undo tablespace | undo 日志与回滚段 | `undo_001` / `undo_002`，或自定义 `.ibu` | 见 [Undo Log](/docs/CS/DB/MySQL/undolog.md) |
| temporary tablespace | 会话级内部临时表 | `ibtmp1` + `#innodb_temp/` 目录 | `innodb_temp_data_file_path` / `innodb_temp_tablespaces_dir` |
| data dictionary tablespace | MySQL 数据字典表自身 | `mysql.ibd` | 不直接操作 |

两点与旧版本的断裂，值得单独记住：

- **`.frm` 自 8.0 起不再是 InnoDB 表的一部分**。表定义搬进事务型数据字典（落在 `mysql.ibd`），同时每个持久表空间文件内部保存一份 SDI（serialized dictionary information）；9.7 手册的 `ibd2sdi` 一节明确说 SDI 存在于 file-per-table 与 general tablespace 的 `.ibd`、系统表空间的 `ibdata*` 以及 `mysql.ibd` 中，**临时表空间与 undo 表空间没有 SDI**，因此 `ibd2sdi` 也不支持它们。
- **doublewrite buffer 自 8.0.20 起不再占用系统表空间**，改用独立的 doublewrite 文件（默认 2 个文件）。细节见 [Double-Buffer](/docs/CS/DB/MySQL/Double-Buffer.md)。

## Tablespaces

Pages, Extents, Segments, and Tablespaces

Each tablespace consists of database pages. Every tablespace in a MySQL instance has the same page size.
By default, all tablespaces have a page size of 16KB; you can reduce the page size to 8KB or 4KB by specifying the innodb_page_size option when you create the MySQL instance.
You can also increase the page size to 32KB or 64KB. For more information, refer to the innodb_page_size documentation.

The pages are grouped into extents of size 1MB for pages up to 16KB in size (64 consecutive 16KB pages, or 128 8KB pages, or 256 4KB pages).
For a page size of 32KB, extent size is 2MB.
For page size of 64KB, extent size is 4MB.
The “files” inside a tablespace are called segments in InnoDB.
(These segments are different from the rollback segment, which actually contains many tablespace segments.)

When a segment grows inside the tablespace, InnoDB allocates the first 32 pages to it one at a time.
After that, InnoDB starts to allocate whole extents to the segment. InnoDB can add up to 4 extents at a time to a large segment to ensure good sequentiality of data.

Two segments are allocated for each index in InnoDB. One is for nonleaf nodes of the B-tree, the other is for the leaf nodes.
Keeping the leaf nodes contiguous on disk enables better sequential I/O operations, because these leaf nodes contain the actual table data.

Some pages in the tablespace contain bitmaps of other pages, and therefore a few extents in an InnoDB tablespace cannot be allocated to segments as a whole, but only as individual pages.

When you ask for available free space in the tablespace by issuing a SHOW TABLE STATUS statement, InnoDB reports the extents that are definitely free in the tablespace.
InnoDB always reserves some extents for cleanup and other internal purposes; these reserved extents are not included in the free space.

When you delete data from a table, InnoDB contracts the corresponding B-tree indexes.
Whether the freed space becomes available for other users depends on whether the pattern of deletes frees individual pages or extents to the tablespace.
Dropping a table or deleting all rows from it is guaranteed to release the space to other users, but remember that deleted rows are physically removed only by the purge operation,
which happens automatically some time after they are no longer needed for transaction rollbacks or consistent reads.

### Page Size and Extent Size

页大小对整个实例是**一次定死**的：`innodb_page_size` 默认 16384（16KB），可选 4096 / 8192 / 16384 / 32768 / 65536，只能在初始化实例前指定、之后不可更改；同一实例内所有表空间页大小相同。extent 的大小按 1MB 为基准折算（32KB 页 → 2MB extent，64KB 页 → 4MB extent），因此「一个 extent 64 页」只在 16KB 页时成立。

### Row Format

| 行格式 | 说明 |
| :--- | :--- |
| `REDUNDANT` | 最老的格式，行头里存列偏移量的方式低效 |
| `COMPACT` | 引入变长字段列表与 NULL 列表，行头记录 `record_type` / `next_record` / `delete_mask` / `min_rec_mask` / `n_owned` / `heap_no` |
| `DYNAMIC` | 9.7 的 `innodb_default_row_format` **默认值**，长列溢出方式比 COMPACT 更省页内空间 |
| `COMPRESSED` | 页内压缩，`innodb_page_size` 为 32KB 或 64KB 时不支持 |

```sql
CREATE TABLE t1 (...) ROW_FORMAT=DYNAMIC;
```

9.7 手册的 `innodb_default_row_format` 只列出 `REDUNDANT` / `COMPACT` / `DYNAMIC` 三个合法值，默认 `DYNAMIC`；`COMPRESSED` 要通过 `ROW_FORMAT=COMPRESSED` 或 `KEY_BLOCK_SIZE` 显式指定。

## Temporary Tablespace

临时表空间保存会话级的内部临时表，重启后不保留：`ibtmp1`（由 `innodb_temp_data_file_path` 定义，默认 `ibtmp1:12M:autoextend`）加上 `#innodb_temp/` 目录下的会话临时表空间文件（位置由 `innodb_temp_tablespaces_dir` 定义，默认 `#innodb_temp`）。它没有 SDI，`ibd2sdi` 也不支持它。

## Undo Tablespace

see [Undo Tablespace](/docs/CS/DB/MySQL/undolog.md?id=undo-tablespaces)

## Links

- [InnoDB Storage Engine](/docs/CS/DB/MySQL/InnoDB.md)
- [File](/docs/CS/DB/MySQL/file.md)
- [Buffer Pool](/docs/CS/DB/MySQL/memory.md)
- [B-Tree Index](/docs/CS/DB/MySQL/B-Tree.md)

## References

- [MySQL 9.7 Reference Manual: Tablespaces](https://dev.mysql.com/doc/refman/9.7/en/innodb-tablespace.html)
- [MySQL 9.7 Reference Manual: System Tablespace](https://dev.mysql.com/doc/refman/9.7/en/innodb-system-tablespace.html)
- [MySQL 9.7 Reference Manual: General Tablespaces](https://dev.mysql.com/doc/refman/9.7/en/general-tablespaces.html)
- [MySQL 9.7 Reference Manual: Temporary Tablespaces](https://dev.mysql.com/doc/refman/9.7/en/innodb-temporary-tablespace.html)
- [MySQL 9.7 Reference Manual: ibd2sdi — InnoDB Tablespace SDI Extraction Utility](https://dev.mysql.com/doc/refman/9.7/en/ibd2sdi.html)
