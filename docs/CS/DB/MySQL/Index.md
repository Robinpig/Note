## Introduction



## 理论

A data structure that provides a fast lookup capability for **rows** of a **table**, typically by forming a tree structure (**B-tree)** representing all the values of a particular **column** or set of columns.

InnoDB tables always have a **clustered index** representing the **primary key**. 
They can also have one or more **secondary indexes** defined on one or more columns. 
Depending on their structure, secondary indexes can be classified as **partial**, **column**, or **composite** indexes.

Indexes are a crucial aspect of **query** performance. Database architects design tables, queries, and indexes to allow fast lookups for data needed by applications. 
The ideal database design uses a **covering index** where practical; the query results are computed entirely from the index, without reading the actual table data. 
Each **foreign key** constraint also requires an index, to efficiently check whether values exist in both the **parent** and **child** tables.

Although a B-tree index is the most common, a different kind of data structure is used for **hash indexes**, as in the `MEMORY` storage engine and the InnoDB **adaptive hash index**. 
**R-tree** indexes are used for spatial indexing of multi-dimensional information.

> [!NOTE]
> 
> Most MySQL indexes (`PRIMARY KEY`, `UNIQUE`, `INDEX`, and `FULLTEXT`) are stored in `B-trees`. 
> 
> Exceptions: Indexes on spatial data types use `R-trees`; `MEMORY` tables also support `hash indexes`; InnoDB uses inverted lists for `FULLTEXT` indexes.


### covering index

An **index** that includes all the columns retrieved by a query.
Instead of using the index values as pointers to find the full table rows, the query returns values from the index structure, saving disk I/O.
InnoDB can apply this optimization technique to more indexes than MyISAM can, because InnoDB **secondary indexes** also include the **primary key** columns.
InnoDB cannot apply this technique for queries against tables modified by a transaction, until that transaction ends.

Any **column index** or **composite index** could act as a covering index, given the right query. 
Design your indexes and queries to take advantage of this optimization technique wherever possible.


### 联合索引


当遇到>或者<时 当前column走索引 下个column不再使用索引 此时会根据查询回表代价估计是否全表还是使用index condition

is null, is not null和 != 会根据查询回表代价估计 在大多数情况下会回表 当前column不走索引


between >=, =< 和 LIKE 'XX%' 索引都可在下个column继续

LIKE '%XX' 无法使用索引


MySQL can also optimize the combination col_name = expr OR col_name IS NULL, a form that is common in resolved subqueries. EXPLAIN shows ref_or_null when this optimization is used.


### Clustered and Secondary Indexes

Each InnoDB table has a special index called the clustered index that stores row data. 
Typically, the clustered index is synonymous with the primary key. 
To get the best performance from queries, inserts, and other database operations, it is important to understand how InnoDB uses the clustered index to optimize the common lookup and DML operations.

- When you define a `PRIMARY KEY` on a table, InnoDB uses it as the clustered index. A primary key should be defined for each table. 
  If there is no logical unique and non-null column or set of columns to use a the primary key, add an auto-increment column. Auto-increment column values are unique and are added automatically as new rows are inserted.
- If you do not define a `PRIMARY KEY` for a table, InnoDB uses the first `UNIQUE` index with all key columns defined as `NOT NULL` as the clustered index.
- If a table has no `PRIMARY KEY` or suitable `UNIQUE` index, InnoDB generates a hidden clustered index named `GEN_CLUST_INDEX` on a synthetic column that contains row ID values. 
  The rows are ordered by the row ID that InnoDB assigns. 
  The row ID is a 6-byte field that increases monotonically as new rows are inserted. Thus, the rows ordered by the row ID are physically in order of insertion.

##### How the Clustered Index Speeds Up Queries

Accessing a row through the clustered index is fast because the index search leads directly to the page that contains the row data. 
If a table is large, the clustered index architecture often saves a disk I/O operation when compared to storage organizations that store row data using a different page from the index record.

##### How Secondary Indexes Relate to the Clustered Index

Indexes other than the clustered index are known as secondary indexes. In InnoDB, each record in a secondary index contains the primary key columns for the row, as well as the columns specified for the secondary index. 
InnoDB uses this primary key value to search for the row in the clustered index.

If the primary key is long, the secondary indexes use more space, so **it is advantageous to have a short primary key**.



## Physical Structure

With the exception of spatial indexes, InnoDB indexes are `B-tree` data structures. 
Spatial indexes use `R-trees`, which are specialized data structures for indexing multi-dimensional data. 
Index records are stored in the leaf pages of their B-tree or R-tree data structure. 
The default size of an index page is 16KB. The page size is determined by the `innodb_page_size` setting when when the MySQL instance is initialized.

When new records are inserted into an InnoDB clustered index, InnoDB tries to leave 1/16 of the page free for future insertions and updates of the index records. 
> If index records are inserted in a sequential order (ascending or descending), the resulting index pages are about 15/16 full. If records are inserted in a random order, the pages are from 1/2 to 15/16 full.

InnoDB performs a bulk load when creating or rebuilding B-tree indexes. This method of index creation is known as a sorted index build. 
The `innodb_fill_factor` variable defines the percentage of space on each B-tree page that is filled during a sorted index build, with the remaining space reserved for future index growth. 
Sorted index builds are not supported for spatial indexes.
An `innodb_fill_factor` setting of 100 leaves 1/16 of the space in clustered index pages free for future index growth.

If the fill factor of an InnoDB index page drops below the `MERGE_THRESHOLD`, which is 50% by default if not specified, InnoDB tries to contract the index tree to free the page. 
The `MERGE_THRESHOLD` setting applies to both B-tree and R-tree indexes. 

#### Sorted Index Builds

InnoDB performs a bulk load instead of inserting one index record at a time when creating or rebuilding indexes. 
This method of index creation is also known as a sorted index build. **Sorted index builds are not supported for spatial indexes**.

There are three phases to an index build. 
In the first phase, the clustered index is scanned, and index entries are generated and added to the sort buffer. 
When the `sort buffer` becomes full, entries are sorted and written out to a temporary intermediate file. 
This process is also known as a “run”. 
In the second phase, with one or more runs written to the temporary intermediate file, a merge sort is performed on all entries in the file. 
In the third and final phase, the sorted entries are inserted into the `B-tree`.

Prior to the introduction of sorted index builds, index entries were inserted into the B-tree one record at a time using insert APIs. 
This method involved opening a B-tree cursor to find the insert position and then inserting entries into a B-tree page using an optimistic insert. 
If an insert failed due to a page being full, a pessimistic insert would be performed, which involves opening a B-tree cursor and splitting and merging B-tree nodes as necessary to find space for the entry. 
The drawbacks of this “top-down” method of building an index are the cost of searching for an insert position and the constant splitting and merging of B-tree nodes.

Sorted index builds use a “**bottom-up**” approach to building an index. With this approach, a reference to the right-most leaf page is held at all levels of the B-tree. 
The right-most leaf page at the necessary B-tree depth is allocated and entries are inserted according to their sorted order. 
Once a leaf page is full, a node pointer is appended to the parent page and a sibling leaf page is allocated for the next insert. 
This process continues until all entries are inserted, which may result in inserts up to the root level. 
When a sibling page is allocated, the reference to the previously pinned leaf page is released, and the newly allocated leaf page becomes the right-most leaf page and new default insert location.

### Comparison of B-Tree and Hash Indexes

#### B-Tree Index Characteristics

Any index that does not span all `AND` levels in the `WHERE` clause is not used to optimize the query. 
In other words, to be able to use an index, a prefix of the index must be used in every `AND` group.

Sometimes MySQL does not use an index, even if one is available. 
One circumstance under which this occurs is when the optimizer estimates that using the index would require MySQL to access a very large percentage of the rows in the table. 
(In this case, a table scan is likely to be much faster because it requires fewer seeks.) 
However, if such a query uses `LIMIT` to retrieve only some of the rows, MySQL uses an index anyway, because it can much more quickly find the few rows to return in the result.

#### Hash Index Characteristics

Hash indexes have somewhat different characteristics from those just discussed:

- They are used only for equality comparisons that use the `=` or `<=>` operators (but are *very* fast). 
  They are not used for comparison operators such as `<` that find a range of values. 
  Systems that rely on this type of single-value lookup are known as “key-value stores”; to use MySQL for such applications, use hash indexes wherever possible.
- The optimizer cannot use a hash index to speed up `ORDER BY` operations. (This type of index cannot be used to search for the next entry in order.)
- MySQL cannot determine approximately how many rows there are between two values (this is used by the range optimizer to decide which index to use). 
  This may affect some queries if you change a `MyISAM` or InnoDB table to a hash-indexed `MEMORY` table.
- Only whole keys can be used to search for a row. (With a B-tree index, any leftmost prefix of the key can be used to find rows.)



### How MySQL Uses Indexes

MySQL uses indexes for these operations:

- To find the rows matching a `WHERE` clause quickly.
- To eliminate rows from consideration. If there is a choice between multiple indexes, MySQL normally uses the index that finds the smallest number of rows (the most selective index).
- If the table has a multiple-column index, any leftmost prefix of the index can be used by the optimizer to look up rows. 
  For example, if you have a three-column index on `(col1, col2, col3)`, you have indexed search capabilities on `(col1)`, `(col1, col2)`, and `(col1, col2, col3)`.
- To retrieve rows from other tables when performing joins. 
  MySQL can use indexes on columns more efficiently if they are declared as the same type and size. In this context, `VARCHAR` and `CHAR` are considered the same if they are declared as the same size. 
  For example, `VARCHAR(10)` and `CHAR(10)` are the same size, but `VARCHAR(10)` and `CHAR(15)` are not.
  **For comparisons between nonbinary string columns, both columns should use the same character set**.
  Comparison of dissimilar columns (comparing a string column to a temporal or numeric column, for example) may prevent use of indexes if values cannot be compared directly without conversion. 
  For a given value such as `1` in the numeric column, it might compare equal to any number of values in the string column such as `'1'`, `' 1'`, `'00001'`, or `'01.e1'`. 
  This rules out use of any indexes for the string column.
- To find the `MIN()` or `MAX()` value for a specific indexed column *`key_col`*. 
  This is optimized by a preprocessor that checks whether you are using `WHERE *`key_part_N`* = *`constant`*` on all key parts that occur before *`key_col`* in the index. 
  In this case, MySQL does a single key lookup for each `MIN()` or `MAX()` expression and replaces it with a constant. 
  If all expressions are replaced with constants, the query returns at once. For example:
- To sort or group a table if the sorting or grouping is done on a leftmost prefix of a usable index (for example, `ORDER BY *`key_part1`*, *`key_part2`*`). 
  If all key parts are followed by `DESC`, the key is read in reverse order. (Or, if the index is a descending index, the key is read in forward order.) 
- In some cases, a query can be optimized to retrieve values without consulting the data rows. (An index that provides all the necessary results for a query is called a covering index.) 
  If a query uses from a table only columns that are included in some index, the selected values can be retrieved from the index tree for greater speed:
- Indexes are less important for queries on small tables, or big tables where report queries process most or all of the rows. 
  When a query needs to access most of the rows, reading sequentially is faster than working through an index. 
  Sequential reads minimize disk seeks, even if not all the rows are needed for the query.

## dict


Data structure for an index.  Most fields will be
initialized to 0, NULL or false in dict_mem_index_create().


```c
struct dict_index_t {
  /** id of the index */
  space_index_t id;

  /** memory heap */
  mem_heap_t *heap;

  /** index name */
  id_name_t name;

  /** table name */
  const char *table_name;

  /** back pointer to table */
  dict_table_t *table;

  /** space where the index tree is placed */
  unsigned space : 32;

  /** index tree root page number */
  unsigned page : 32;

  /** In the pessimistic delete, if the page data size drops below this limit
  in percent, merging it to a neighbor is tried */
  unsigned merge_threshold : 6;

  /** index type (DICT_CLUSTERED, DICT_UNIQUE, DICT_IBUF, DICT_CORRUPT) */
  unsigned type : DICT_IT_BITS;

  /** position of the trx id column in a clustered index record, if the fields
  before it are known to be of a fixed size, 0 otherwise */
  unsigned trx_id_offset : MAX_KEY_LENGTH_BITS;

  // ...
}
```


```c
/** Builds a node pointer out of a physical record and a page number.
 @return own: node pointer */
dtuple_t *dict_index_build_node_ptr(const dict_index_t *index, /*!< in: index */
                                    const rec_t *rec,  /*!< in: record for which
                                                       to build node  pointer */
                                    page_no_t page_no, /*!< in: page number to
                                                       put in node pointer */
                                    mem_heap_t *heap, /*!< in: memory heap where
                                                      pointer created */
                                    ulint level) /*!< in: level of rec in tree:
                                                 0 means leaf level */
{
  dtuple_t *tuple;
  dfield_t *field;
  byte *buf;
  ulint n_unique;

  if (dict_index_is_ibuf(index)) {
    /* In a universal index tree, we take the whole record as
    the node pointer if the record is on the leaf level,
    on non-leaf levels we remove the last field, which
    contains the page number of the child page */

    ut_a(!dict_table_is_comp(index->table));
    n_unique = rec_get_n_fields_old_raw(rec);

    if (level > 0) {
      ut_a(n_unique > 1);
      n_unique--;
    }
  } else {
    n_unique = dict_index_get_n_unique_in_tree_nonleaf(index);
  }

  tuple = dtuple_create(heap, n_unique + 1);

  /* When searching in the tree for the node pointer, we must not do
  comparison on the last field, the page number field, as on upper
  levels in the tree there may be identical node pointers with a
  different page number; therefore, we set the n_fields_cmp to one
  less: */

  dtuple_set_n_fields_cmp(tuple, n_unique);

  dict_index_copy_types(tuple, index, n_unique);

  buf = static_cast<byte *>(mem_heap_alloc(heap, 4));

  mach_write_to_4(buf, page_no);

  field = dtuple_get_nth_field(tuple, n_unique);
  dfield_set_data(field, buf, 4);

  dtype_set(dfield_get_type(field), DATA_SYS_CHILD, DATA_NOT_NULL, 4);

  rec_copy_prefix_to_dtuple(tuple, rec, index, n_unique, heap);
  dtuple_set_info_bits(tuple,
                       dtuple_get_info_bits(tuple) | REC_STATUS_NODE_PTR);

  ut_ad(dtuple_check_typed(tuple));

  return (tuple);
}
```

secondary index

leaf node

non-leaf node


InnoDB 二级索引的 Key 是二级索引字段 + 不在其中的主键字段
为什么这么实现？一是支持非 unique 二级索引，二是支持 MVCC。两者的核心点其实都是：在二级索引 B+ 树上，二级索引字段不足以唯一标识一个 record，需要补充主键字段后才能唯一标识



对于索引结构并发访问的处理，可以将索引整体作为一个数据项，应用事务系统的并发控制机制，例如基于 2PL、时间戳、MVCC 等机制。但是由于索引访问频繁，将成为锁竞争的集中点，导致系统低并发度。
考虑到索引不必像其它数据项那样处理，对于事务而言，对一个索引查找两次，并在期间发现索引结构发生了变化，这是完全可以接受的，只要索引查找返回正确的数据项。因此只要维护索引的准确性，对索引进行非可串行化的并发调度是可接受的。



## Tuning


索引的结构

哈希存储 等值查询 不适用于范围查询
有序数组 适用范围查询 但是在中间插入比较麻烦 迁移数据成本较高
二叉树 树高较大会使得IO次数较多 同时若是维护平衡二叉树带来的成本也较高
B树 树高较低 匹配查询效率较高 但是因为节点的层次不一致 查询效率不稳定 同时对区间查询的支持也不够
B+树 非叶子结点不存储数据 降低树高 叶子结点支持范围查询
跳表 存放同样量级的数据，B+树的高度比跳表的要少，如果放在mysql数据库上来说，就是磁盘IO次数更少，因此B+树查询更快。 而针对写操作，B+树需要拆分合并索引数据页，跳表则独立插入，并根据随机函数确定层数，没有旋转和维持平衡的开销，因此跳表的写入性能会比B+树要好。
rocksDB的存储引擎


几点建议和忠告
-在数据量非常大的情况下，没有 WHERE 条件过滤是非常可怕的
-数据量很少的情况下（比如少于 1000 条），是没必要使用索引的
-数据重复度大（区分度小）的，也没必要使用索引。几千万条数据，deleted = 1 的一共没几条，并且几乎不会查（代码里面大部分默认 deleted = 0），所以创建(deleted) 索引出了让引擎误会，选错索引导致全表扫描外，起不到任何作用
-order by 不要乱用，尤其是对于分页表格，已经有了筛选项，就没必要按照分类排序了
-不要给每个字段都创建一个单独索引，好多是被联合索引覆盖了，另外一些可能没有区分度
-没有任何一条优化规则是可以解决所有问题的（否则就被引擎内置了），你能做的是了解原理，根据实际业务场景做出更优的选择




## Links

- [InnoDB Storage Engine](/docs/CS/DB/MySQL/InnoDB.md?id=innodb-on-disk-structures)

## References

1. [A Survey of B-Tree Locking Techniques](https://15721.courses.cs.cmu.edu/spring2019/papers/06-indexes/a16-graefe.pdf)
2. [Mysql索引(究极无敌细节版) - Cuzzz - 博客园 (cnblogs.com)](https://www.cnblogs.com/cuzzz/p/16812054.html)

