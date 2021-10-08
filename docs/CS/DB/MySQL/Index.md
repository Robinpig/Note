## Introduction

A data structure that provides a fast lookup capability for **rows** of a **table**, typically by forming a tree structure (**B-tree)** representing all the values of a particular **column** or set of columns.

`InnoDB` tables always have a **clustered index** representing the **primary key**. They can also have one or more **secondary indexes** defined on one or more columns. Depending on their structure, secondary indexes can be classified as **partial**, **column**, or **composite** indexes.

Indexes are a crucial aspect of **query** performance. Database architects design tables, queries, and indexes to allow fast lookups for data needed by applications. The ideal database design uses a **covering index** where practical; the query results are computed entirely from the index, without reading the actual table data. Each **foreign key** constraint also requires an index, to efficiently check whether values exist in both the **parent** and **child** tables.

Although a B-tree index is the most common, a different kind of data structure is used for **hash indexes**, as in the `MEMORY` storage engine and the `InnoDB` **adaptive hash index**. **R-tree** indexes are used for spatial indexing of multi-dimensional information.

See Also [adaptive hash index](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_adaptive_hash_index), [B-tree](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_b_tree), [child table](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_child_table), [clustered index](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_clustered_index), [column index](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_column_index), [composite index](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_composite_index), [covering index](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_covering_index), [foreign key](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_foreign_key), [hash index](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_hash_index), [parent table](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_parent_table), [partial index](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_partial_index), [primary key](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_primary_key), [query](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_query), [R-tree](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_r_tree), [row](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_row), [secondary index](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_secondary_index), [table](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_table).

Most MySQL indexes (`PRIMARY KEY`, `UNIQUE`, `INDEX`, and `FULLTEXT`) are stored in [B-trees](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_b_tree). Exceptions: Indexes on spatial data types use R-trees; `MEMORY` tables also support [hash indexes](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_hash_index); `InnoDB` uses inverted lists for `FULLTEXT` indexes.

### Clustered and Secondary Indexes

Each `InnoDB` table has a special index called the clustered index that stores row data. Typically, the clustered index is synonymous with the primary key. To get the best performance from queries, inserts, and other database operations, it is important to understand how `InnoDB` uses the clustered index to optimize the common lookup and DML operations.

- When you define a `PRIMARY KEY` on a table, `InnoDB` uses it as the clustered index. A primary key should be defined for each table. If there is no logical unique and non-null column or set of columns to use a the primary key, add an auto-increment column. Auto-increment column values are unique and are added automatically as new rows are inserted.
- If you do not define a `PRIMARY KEY` for a table, `InnoDB` uses the first `UNIQUE` index with all key columns defined as `NOT NULL` as the clustered index.
- If a table has no `PRIMARY KEY` or suitable `UNIQUE` index, `InnoDB` generates a hidden clustered index named `GEN_CLUST_INDEX` on a synthetic column that contains row ID values. The rows are ordered by the row ID that `InnoDB` assigns. The row ID is a 6-byte field that increases monotonically as new rows are inserted. Thus, the rows ordered by the row ID are physically in order of insertion.

##### How the Clustered Index Speeds Up Queries

Accessing a row through the clustered index is fast because the index search leads directly to the page that contains the row data. If a table is large, the clustered index architecture often saves a disk I/O operation when compared to storage organizations that store row data using a different page from the index record.

##### How Secondary Indexes Relate to the Clustered Index

Indexes other than the clustered index are known as secondary indexes. In `InnoDB`, each record in a secondary index contains the primary key columns for the row, as well as the columns specified for the secondary index. `InnoDB` uses this primary key value to search for the row in the clustered index.

If the primary key is long, the secondary indexes use more space, so it is advantageous to have a short primary key.

For guidelines to take advantage of `InnoDB` clustered and secondary indexes, see [Section 8.3, “Optimization and Indexes”](https://dev.mysql.com/doc/refman/8.0/en/optimization-indexes.html).



### The Physical Structure of an InnoDB Index



With the exception of spatial indexes, `InnoDB` indexes are [B-tree](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_b_tree) data structures. Spatial indexes use [R-trees](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_r_tree), which are specialized data structures for indexing multi-dimensional data. Index records are stored in the leaf pages of their B-tree or R-tree data structure. The default size of an index page is 16KB. The page size is determined by the [`innodb_page_size`](https://dev.mysql.com/doc/refman/8.0/en/innodb-parameters.html#sysvar_innodb_page_size) setting when when the MySQL instance is initialized. See [Section 15.8.1, “InnoDB Startup Configuration”](https://dev.mysql.com/doc/refman/8.0/en/innodb-init-startup-configuration.html).

When new records are inserted into an `InnoDB` [clustered index](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_clustered_index), `InnoDB` tries to leave 1/16 of the page free for future insertions and updates of the index records. If index records are inserted in a sequential order (ascending or descending), the resulting index pages are about 15/16 full. If records are inserted in a random order, the pages are from 1/2 to 15/16 full.

`InnoDB` performs a bulk load when creating or rebuilding B-tree indexes. This method of index creation is known as a sorted index build. The [`innodb_fill_factor`](https://dev.mysql.com/doc/refman/8.0/en/innodb-parameters.html#sysvar_innodb_fill_factor) variable defines the percentage of space on each B-tree page that is filled during a sorted index build, with the remaining space reserved for future index growth. Sorted index builds are not supported for spatial indexes. For more information, see [Section 15.6.2.3, “Sorted Index Builds”](https://dev.mysql.com/doc/refman/8.0/en/sorted-index-builds.html). An [`innodb_fill_factor`](https://dev.mysql.com/doc/refman/8.0/en/innodb-parameters.html#sysvar_innodb_fill_factor) setting of 100 leaves 1/16 of the space in clustered index pages free for future index growth.

If the fill factor of an `InnoDB` index page drops below the `MERGE_THRESHOLD`, which is 50% by default if not specified, `InnoDB` tries to contract the index tree to free the page. The `MERGE_THRESHOLD` setting applies to both B-tree and R-tree indexes. For more information, see [Section 15.8.11, “Configuring the Merge Threshold for Index Pages”](https://dev.mysql.com/doc/refman/8.0/en/index-page-merge-threshold.html).



## 数据结构

### Hash

精确单个查询 



### B+ Tree

只有在叶子节点才会真正的存储数据 叶子结点维护双向有序链表 适合范围查找

#### 存储引擎实现

**MyISAM** 中,辅助索引和主键索引的结构是一样的,叫非聚簇索引(UnClustered Index), 表可以没有主键:

其主键索引与普通索引没有本质差异：

（1）有连续聚集的区域单独存储行记录；

（2）主键索引的叶子节点，存储主键(**不可重复**)，与对应行记录的指针；

（3）普通索引的叶子结点，存储索引列(**可重复**)，与对应行记录的指针；





**InnoDB**表,主键索引**与**行记录是存储在一起的,故叫聚簇索引(Clustered Index) ，叶子节点存储行记录

**InnoDB的表必须要有且只有一个聚集索引**：

（1）如果表定义了PK，则PK就是聚集索引；

（2）如果表没有定义PK，则第一个非空unique列是聚集索引；

（3）否则，InnoDB会创建一个6 字节长整型的隐式字段row-id作为聚集索引；

普通索引叶子结点存储主键

**建议使用趋势递增主键**

InnoDB由于数据行与索引一体，如果使用趋势递增主键，插入记录时，不会索引分裂，不会大量行记录移动。



使用较长的值作为主键会很快占满MySQL有限的缓冲区，存储的索引与数据会减少，磁盘IO的概率会增加。



根据在辅助索引树中获取的主键id，到主键索引树检索数据的过程称为**回表**查询。

**Covering index**

描述: 只需要在一棵索引树上就能获取SQL所需的所有列数据，无需回表，速度更快。

实现: 将被查询的字段，建立到联合索引里去



### hash & tree

（1）**哈希**，例如HashMap，查询/插入/修改/删除的平均时间复杂度都是O(1)；

（2）**树**，例如平衡二叉搜索树，查询/插入/修改/删除的平均时间复杂度都是O(lg(n))；

索引设计成树形，和SQL的需求相关

1. **单行查询**的SQL需求：

*select \* from t where name=”shenjian”;*

确实是哈希索引更快，因为每次都只查询一条记录。

2. **排序查询**的SQL需求：

（1）分组：group by

（2）排序：order by

（3）比较：<、>

（4）…

**哈希**型的索引，时间复杂度会退化为O(n)，而**树型**的“有序”特性，依然能够保持O(log(n)) 的高效率。

 

 **InnoDB并不支持手动建立哈希索引, 自适应hash索引**。

 

**问题3. 数据库索引为什么使用B+树？**

 

**第一种：二叉搜索树**

![Image](https://mmbiz.qpic.cn/mmbiz_png/YrezxckhYOzI052ggBDKuzKSicOX3feReUWMbz5cQUgMCNFUeiaibB2x3lRuQJF5pVJf0nibG0PMGKQgVR1KYNNE7w/640?wx_fmt=png&tp=webp&wxfrom=5&wx_lazy=1&wx_co=1)

二叉搜索树，如上图，是最为大家所熟知的一种数据结构，就不展开介绍了，**它为什么不适合用作数据库索引？**

（1）当数据量大的时候，树的高度会比较高，数据量大的时候，查询会比较慢；

（2）每个节点只存储一个记录，可能导致一次查询有很多次磁盘IO；

*画外音：这个树经常出现在大学课本里，所以最为大家所熟知。*

 

**第二种：B树**

![Image](https://mmbiz.qpic.cn/mmbiz_png/YrezxckhYOzI052ggBDKuzKSicOX3feRepP4cQ9J2rrHoSRLM1rYtA9bekUMOwDpB86dMb2Pt1omIH3K4LyibCUw/640?wx_fmt=png&tp=webp&wxfrom=5&wx_lazy=1&wx_co=1)

B树，如上图，它的特点是：

（1）不再是二叉搜索，而是m叉搜索；

（2）叶子节点，非叶子节点，都存储数据；

（3）中序遍历，可以获得所有节点；

*画外音，实在不想介绍这个特性：非根节点包含的关键字个数j满足，**(┌m/2┐)-1 <= j <= m-1**，节点分裂时要满足这个条件。*

 

B树被作为实现索引的数据结构被创造出来，是因为它能够完美的利用“局部性原理”。

 

**什么是局部性原理？**

局部性原理的逻辑是这样的：

（1）内存读写块，磁盘读写慢，而且慢很多；



（2）**磁盘预读**：磁盘读写并不是按需读取，而是按页预读，一次会读一页的数据，每次加载更多的数据，如果未来要读取的数据就在这一页中，可以避免未来的磁盘IO，提高效率；

*画外音：通常，操作系统一页数据是4K，MySQL**的一页是16K。*



（3）**局部性原理**：软件设计要尽量遵循“数据读取集中”与“使用到一个数据，大概率会使用其附近的数据”，这样磁盘预读能充分提高磁盘IO；

 

**B树为何适合做索引？**

（1）由于是m分叉的，高度能够大大降低；

（2）每个节点可以存储j个记录，如果将节点大小设置为页大小，例如4K，能够充分的利用预读的特性，极大减少磁盘IO；

 

**第三种：B+树**

![Image](https://mmbiz.qpic.cn/mmbiz_png/YrezxckhYOzI052ggBDKuzKSicOX3feReibBXFlicV1dQ4TuLHcf399lHh9uOMaSIbsZZaWWYHXnqIWJ6gWOFsqMw/640?wx_fmt=png&tp=webp&wxfrom=5&wx_lazy=1&wx_co=1)

B+树，如上图，仍是m叉搜索树，在B树的基础上，做了**一些改进**：

（1）非叶子节点不再存储数据，数据只存储在同一层的叶子节点上；

*画外音：B+树中根到每一个节点的路径长度一样，而B树不是这样。*



（2）叶子之间，增加了链表，获取所有节点，不再需要中序遍历；

 

这些改进让B+树比B树有更优的特性：

（1）范围查找，定位min与max之后，中间叶子节点，就是结果集，不用中序回溯；

*画外音：范围查询在SQL中用得很多，这是B+树比B树最大的优势。*



（2）叶子节点存储实际记录行，记录行相对比较紧密的存储，适合大数据量磁盘存储；非叶子节点存储记录的PK，用于查询加速，适合内存存储；



（3）非叶子节点，不存储实际记录，而只存储记录的KEY的话，那么在相同内存的情况下，B+树能够存储更多索引；

 

最后，量化说下，**为什么m叉的B+树比二叉搜索树的高度大大大大降低？**

大概计算一下：

（1）局部性原理，将一个节点的大小设为一页，一页4K，假设一个KEY有8字节，一个节点可以存储500个KEY，即j=500；

（2）m叉树，大概m/2<= j <=m，即可以差不多是1000叉树；

（3）那么：

一层树：1个节点，1*500个KEY，大小4K

二层树：1000个节点，1000*500=50W个KEY，大小1000*4K=4M

三层树：1000*1000个节点，1000*1000*500=5亿个KEY，大小1000*1000*4K=4G

可以看到，存储大量的数据（5亿），并不需要太高树的深度（高度3），索引也不是太占内存（4G）。

##### B+树比B树优势

1. B+树非叶子结点只存储索引信息 一次能加载索引数量增加 减少IO
2. B+树依次遍历叶子结点可获得全部数据 B树没有叶子结点间的连接 做范围查询效率低
3. 所有数据都在叶子结点意味着所有结点查询效率几乎都是一样的



**总结**

（1）数据库索引用于加速查询；

（2）虽然哈希索引是O(1)，树索引是O(log(n))，但SQL有很多“有序”需求，故数据库使用树型索引；

（3）InnoDB不支持手动创建哈希索引；

**（4）数据预读**的思路是：磁盘读写并不是按需读取，而是按页预读，一次会读一页的数据，每次加载更多的数据，以便未来减少磁盘IO

**（5）局部性原理**：软件设计要尽量遵循“数据读取集中”与“使用到一个数据，大概率会使用其附近的数据”，这样磁盘预读能充分提高磁盘IO

（5）数据库的索引最常用B+树：

 \- 很适合磁盘存储，能够充分利用局部性原理，磁盘预读；

 \- 很低的树高度，能够存储大量数据；

 \- 索引本身占用的内存很小；

 \- 能够很好的支持单点查询，范围查询，有序性查询；



## 索引优化

覆盖索引

select的列都是索引项

## 索引失效

不满足最左前缀匹配

范围索引未放到最后:联合索引里的范围列

使用select *

索引列类型不相同(使用数字查varchar)

索引列上有计算

索引列上有函数

字符类型没加引号

字段允许为空情况下 使用对 null判断不走索引

like查询左边%

or对不同索引字段使用比单独select后union差

join表字符编码不一致



一页 16K









