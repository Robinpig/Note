## Introduction

## 理论

一种为**表**的**行**提供快速查找能力的数据结构，通常通过构建树形结构（**B-tree**）来表示特定**列**或列集合的所有值。

InnoDB 表始终有一个代表**主键**的**聚簇索引**。
它们还可以在一个或多个列上定义一个或多个**二级索引**。
根据结构不同，二级索引可分为**部分索引**、**列索引**或**复合索引**。

索引是**查询**性能的关键方面。
数据库架构师设计表、查询和索引，以允许应用程序快速查找所需数据。
理想的数据库设计在可行时使用**覆盖索引**：查询结果完全从索引计算，无需读取实际的表数据。
每个**外键**约束也需要一个索引，以有效检查值是否同时存在于**父**表和**子**表中。

尽管 B-tree 索引最为常见，但**哈希索引**使用了不同的数据结构，如 `MEMORY` 存储引擎和 InnoDB 的**自适应哈希索引**。
**R-tree** 索引用于多维数据的空间索引。

> [!NOTE]
> 
> Most MySQL indexes (`PRIMARY KEY`, `UNIQUE`, `INDEX`, and `FULLTEXT`) are stored in `B-trees`. 
> 
> Exceptions: Indexes on spatial data types use `R-trees`; `MEMORY` tables also support `hash indexes`; InnoDB uses inverted lists for `FULLTEXT` indexes.

### covering index

一个包含查询所需所有列的**索引**。
查询不再使用索引值作为指针来查找完整的表行，而是直接从索引结构中返回值，从而节省磁盘 I/O。
InnoDB 可以将此优化技术应用于比 MyISAM 更多的索引，因为 InnoDB 的**二级索引**也包含**主键**列。
InnoDB 无法对事务修改的表应用此技术，直到该事务结束。

任何**列索引**或**复合索引**在合适的查询下都可以作为覆盖索引。
请尽可能设计你的索引和查询以利用此优化技术。

### 联合索引

当遇到>或者<时 当前column走索引 下个column不再使用索引 此时会根据查询回表代价估计是否全表还是使用index condition

is null, is not null和 != 会根据查询回表代价估计 在大多数情况下会回表 当前column不走索引

between >=, =< 和 LIKE 'XX%' 索引都可在下个column继续

LIKE '%XX' 无法使用索引

MySQL 还可以优化 `col_name = expr OR col_name IS NULL` 的组合，这种形式在已解析的子查询中很常见。
EXPLAIN 在使用此优化时会显示 `ref_or_null`。

### Clustered and Secondary Indexes

每个 InnoDB 表都有一个特殊的索引，称为聚簇索引，用于存储行数据。
通常，聚簇索引与主键是同义词。
为了从查询、插入和其他数据库操作中获得最佳性能，理解 InnoDB 如何使用聚簇索引来优化常见的查找和 DML 操作非常重要。

- 当你在表上定义 `PRIMARY KEY` 时，InnoDB 将其用作聚簇索引。
  每个表都应定义一个主键。
  如果没有逻辑上唯一且非空的列或列集可用作主键，请添加一个自增列。
  自增列值是唯一的，并在插入新行时自动添加。
- 如果没有为表定义 `PRIMARY KEY`，InnoDB 使用第一个所有键列都定义为 `NOT NULL` 的 `UNIQUE` 索引作为聚簇索引。
- 如果表没有 `PRIMARY KEY` 或合适的 `UNIQUE` 索引，InnoDB 会在包含行 ID 值的合成列上生成一个名为 `GEN_CLUST_INDEX` 的隐藏聚簇索引。
  行按 InnoDB 分配的行 ID 排序。
  行 ID 是一个 6 字节的字段，随着新行的插入而单调递增。
  因此，按行 ID 排序的行在物理上就是按插入顺序排列的。

##### 聚簇索引如何加速查询

通过聚簇索引访问行速度很快，因为索引搜索直接指向包含行数据的页面。
如果表很大，与将行数据存储在与索引记录不同的页面中的存储组织相比，聚簇索引架构通常可以节省一次磁盘 I/O 操作。

##### 二级索引与聚簇索引的关系

聚簇索引之外的索引称为二级索引。
在 InnoDB 中，二级索引中的每条记录都包含该行的主键列以及为二级索引指定的列。
InnoDB 使用此主键值在聚簇索引中搜索该行。

如果主键很长，二级索引会使用更多空间，因此**短主键是有利的**。

## Physical Structure

除了空间索引之外，InnoDB 索引都是 `B-tree` 数据结构。
空间索引使用 `R-trees`，这是专门用于索引多维数据的数据结构。
索引记录存储在其 B-tree 或 R-tree 数据结构的叶子页面中。
索引页的默认大小为 16KB。
页面大小由 MySQL 实例初始化时的 `innodb_page_size` 设置决定。

当新记录插入 InnoDB 聚簇索引时，InnoDB 会尝试保留页面 1/16 的空间用于将来插入和更新索引记录。
> If index records are inserted in a sequential order (ascending or descending), the resulting index pages are about 15/16 full. If records are inserted in a random order, the pages are from 1/2 to 15/16 full.

InnoDB 在创建或重建 B-tree 索引时执行批量加载。
这种索引创建方法称为排序索引构建。
`innodb_fill_factor` 变量定义了在排序索引构建期间每个 B-tree 页面上填充的空间百分比，剩余空间保留给未来的索引增长。
空间索引不支持排序索引构建。
`innodb_fill_factor` 设置为 100 时，会在聚簇索引页面中保留 1/16 的空间用于未来索引增长。

如果 InnoDB 索引页面的填充因子低于 `MERGE_THRESHOLD`（默认情况下未指定时为 50%），InnoDB 会尝试收缩索引树以释放页面。
`MERGE_THRESHOLD` 设置适用于 B-tree 和 R-tree 索引。

#### Sorted Index Builds

InnoDB 在创建或重建索引时执行批量加载，而不是逐条插入索引记录。
这种索引创建方法也称为排序索引构建。**空间索引不支持排序索引构建**。

索引构建分为三个阶段。
在第一阶段，扫描聚簇索引，生成索引条目并添加到排序缓冲区。
当 `sort buffer` 满时，条目被排序并写入临时中间文件。
这个过程也称为"run"。
在第二阶段，将一次或多次 run 写入临时中间文件后，对文件中的所有条目执行归并排序。
在第三也是最后一个阶段，排序后的条目被插入到 `B-tree` 中。

在引入排序索引构建之前，索引条目是使用 insert APIs 一次一条地插入 B-tree 的。
这种方法涉及打开 B-tree 游标以找到插入位置，然后使用乐观插入将条目插入 B-tree 页面。
如果插入因页面已满而失败，则会执行悲观插入，这涉及打开 B-tree 游标并根据需要分割和合并 B-tree 节点以为条目找到空间。
这种"自上而下"构建索引的方法的缺点是搜索插入位置的成本以及不断分割和合并 B-tree 节点的开销。

排序索引构建采用"**自下而上**"的方法构建索引。
使用这种方法，在 B-tree 的所有层级上都持有对最右侧叶子页面的引用。
分配所需 B-tree 深度上的最右侧叶子页面，并根据排序顺序插入条目。
一旦叶子页面已满，就会在父页面上追加一个节点指针，并为下一次插入分配一个兄弟叶子页面。
此过程持续到所有条目插入完毕，可能导致插入直到根层级。
当分配兄弟页面时，之前固定的叶子页面的引用被释放，新分配的叶子页面成为最右侧叶子页面和新的默认插入位置。

### Comparison of B-Tree and Hash Indexes

#### B-Tree 索引特性

任何未涵盖 `WHERE` 子句中所有 `AND` 层级的索引都不会用于优化查询。
换句话说，要能够使用索引，必须在每个 `AND` 组中使用索引的前缀。

有时即使有可用的索引，MySQL 也不会使用它。
出现这种情况的一种情形是，优化器估计使用索引需要 MySQL 访问表中非常大比例的行。
（在这种情况下，全表扫描可能更快，因为它需要更少的寻道。）
但是，如果这样的查询使用 `LIMIT` 仅检索部分行，MySQL 仍然会使用索引，因为它可以更快地找到要返回的少数行。

#### 哈希索引特性

哈希索引与上述讨论的特性有所不同：

- 它们仅用于使用 `=` 或 `<=>` 操作符的等值比较（但速度**非常快**）。
  它们不用于诸如 `<` 之类的范围比较操作符。
  依赖这种单值查找的系统称为"key-value 存储"；要将 MySQL 用于此类应用程序，请尽可能使用哈希索引。
- 优化器无法使用哈希索引加速 `ORDER BY` 操作。
  （这种类型的索引不能用于按顺序搜索下一个条目。）
- MySQL 无法确定两个值之间大约有多少行（范围优化器使用此信息来决定使用哪个索引）。
  如果将 `MyISAM` 或 InnoDB 表更改为哈希索引的 `MEMORY` 表，可能会影响某些查询。
- 只能使用完整的键来搜索行。
  （使用 B-tree 索引，可以使用键的任何最左前缀来查找行。）

### MySQL 如何使用索引

MySQL 将索引用于以下操作：

- 快速找到匹配 `WHERE` 子句的行。
- 排除行。如果在多个索引之间选择，MySQL 通常使用找到行数最少（选择性最高）的索引。
- 如果表有多列索引，优化器可以使用索引的任何最左前缀来查找行。
  例如，如果在 `(col1, col2, col3)` 上有三列索引，则可以在 `(col1)`、`(col1, col2)` 和 `(col1, col2, col3)` 上进行索引搜索。
- 执行连接时从其他表检索行。
  如果列声明为相同的类型和大小，MySQL 可以更高效地使用索引。
  在这种情况下，如果 `VARCHAR` 和 `CHAR` 声明为相同大小，则视为等同。
  例如，`VARCHAR(10)` 和 `CHAR(10)` 大小相同，但 `VARCHAR(10)` 和 `CHAR(15)` 不同。
  **对于非二进制字符串列的比较，两个列应使用相同的字符集**。
  不同类型列的比较（例如将字符串列与时间或数字列比较）可能会阻止索引的使用，如果值无法在不转换的情况下直接比较。
  对于数字列中的给定值（如 `1`），它可能等于字符串列中的任意数量的值，如 `'1'`、`' 1'`、`'00001'` 或 `'01.e1'`。
  这排除了对字符串列使用任何索引的可能性。
- 查找特定索引列 *`key_col`* 的 `MIN()` 或 `MAX()` 值。
  预处理器会检查是否在索引中 *`key_col`* 之前的所有键部分上使用了 `WHERE *`key_part_N`* = *`constant`*`。
  在这种情况下，MySQL 对每个 `MIN()` 或 `MAX()` 表达式执行单次键查找并将其替换为常量。
  如果所有表达式都被替换为常量，查询立即返回。
- 如果排序或分组是在可用索引的最左前缀上进行的，则对表进行排序或分组（例如，`ORDER BY *`key_part1`*, *`key_part2`*`）。
  如果所有键部分后跟 `DESC`，则按键的逆序读取。
  （或者，如果索引是降序索引，则按键的正序读取。）
- 在某些情况下，可以优化查询以在不访问数据行的情况下检索值。
  （为查询提供所有必要结果的索引称为覆盖索引。）
  如果查询只使用表中包含在某个索引中的列，则可以从索引树中检索所选值以获得更快的速度。
- 对于小表或报表查询处理大部分或所有行的大表，索引不太重要。
  当查询需要访问大部分行时，顺序读取比通过索引工作更快。
  顺序读取最小化磁盘寻道，即使并非所有行都是查询所需的。

## dict

索引的数据结构。
大多数字段将在 `dict_mem_index_create()` 中初始化为 0、NULL 或 false。

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
