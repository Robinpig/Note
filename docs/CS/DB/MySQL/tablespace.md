## Introduction

The system tablespace is the storage area for the change buffer.


It may also contain table and index data if tables are created in the system tablespace rather than file-per-table or general tablespaces.
In previous MySQL versions, the system tablespace contained the `InnoDB` data dictionary. 
In MySQL 8.0, `InnoDB`  stores metadata in the MySQL data dictionary.
In previous MySQL releases, the system tablespace also contained the doublewrite buffer storage area. This storage area resides in separate doublewrite files as of MySQL 8.0.20.

The system tablespace can have one or more data files. 
By default, a single system tablespace data file, named  `ibdata1`, is created in the data directory. The size and number of system tablespace data files is defined by the  `innodb_data_file_path`  startup option.

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

When you delete data from a table, contracts the corresponding B-tree indexes.
Whether the freed space becomes available for other users depends on whether the pattern of deletes frees individual pages or extents to the tablespace.
Dropping a table or deleting all rows from it is guaranteed to release the space to other users, but remember that deleted rows are physically removed only by the purge operation,
which happens automatically some time after they are no longer needed for transaction rollbacks or consistent reads.



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
