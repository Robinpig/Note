## Introduction

这一页回答 InnoDB 内存结构的问题：表和索引页在内存里如何组织、什么时候被淘汰、脏页什么时候落盘，以及寄生在 buffer pool 上的辅助结构（Change Buffer、Adaptive Hash Index、Log Buffer）各自解决什么随机 I/O。主线是 Buffer Pool 的三条链表（LRU / Free / Flush）：LRU 决定谁被淘汰，Free 决定谁可以被立刻复用，Flush 决定检查点能推进到哪里；Read-Ahead 决定预取，Checkpoint 与自适应刷脏决定落盘节奏，Page 结构决定一次 I/O 的粒度。

这些机制的默认水位在版本之间反复变动（脏页比例默认值由 75 上调到 90、Adaptive Hash Index 的开关默认值由 ON 翻转为 OFF、change buffer 上限由 25% 降到 5%、log buffer 由 16MB 涨到 64MB），凭旧资料写必然过时。正文各节标注 MySQL 9.7.2 源码出处，汇总见「Verified Defaults In MySQL 9.7」。

| 项 | 值 |
| :--- | :--- |
| 正文默认版本 | MySQL 9.7.x LTS（最新 9.7.3，2026-08-18） |
| 源码核实基线 | tag `mysql-9.7.2` |
| 次要兼容目标 | 8.4.x LTS |
| 已停止支持 | 8.0（EOL 2026-04-30）、5.7（EOL 2023-10） |
| 核实日期 | 2026-10-07 |

## Buffer Pool

The buffer pool is an area in main memory where InnoDB caches table and index data as it is accessed.
The buffer pool permits frequently used data to be accessed directly from memory, which speeds up processing.
On dedicated servers, up to 80% of physical memory is often assigned to the buffer pool.

For efficiency of high-volume read operations, the buffer pool is divided into pages that can potentially hold multiple rows.
For efficiency of cache management, the buffer pool is implemented as a linked list of pages;
data that is rarely used is aged out of the cache using a variation of the least recently used (LRU) algorithm.

Knowing how to take advantage of the buffer pool to keep frequently accessed data in memory is an important aspect of MySQL tuning.

```sql
mysql>SHOW VARIABLES LIKE 'innodb_buffer%';
-- innodb_buffer_pool_chunk_size,134217728
-- innodb_buffer_pool_dump_at_shutdown,ON
-- innodb_buffer_pool_dump_now,OFF
-- innodb_buffer_pool_dump_pct,25
-- innodb_buffer_pool_filename,ib_buffer_pool
-- innodb_buffer_pool_in_core_file,ON
-- innodb_buffer_pool_instances,1
-- innodb_buffer_pool_load_abort,OFF
-- innodb_buffer_pool_load_at_startup,ON
-- innodb_buffer_pool_load_now,OFF
-- innodb_buffer_pool_size,134217728

information_schema> SELECT * FROM INNODB_BUFFER_POOL_STATS;
```

### Logical list

#### LRU Algorithm

The buffer pool is managed as a list using a variation of the LRU algorithm. 
When room is needed to add a new page to the buffer pool, the least recently used page is evicted and a new page is added to the middle of the list. 
This midpoint insertion strategy treats the list as two sublists:

- At the head, a sublist of new (“young”) pages that were accessed recently
- At the tail, a sublist of old pages that were accessed less recently

**Buffer Pool LRU List**

![Buffer Pool LRU List](https://dev.mysql.com/doc/refman/9.7/en/images/innodb-buffer-pool-list.png)

The algorithm keeps frequently used pages in the new sublist. The old sublist contains less frequently used pages; these pages are candidates for eviction.

By default, the algorithm operates as follows:

- 3/8 of the buffer pool is devoted to the old sublist.
- The midpoint of the list is the boundary where the tail of the new sublist meets the head of the old sublist.
- When InnoDB reads a page into the buffer pool, it initially inserts it at the midpoint (the head of the old sublist).
  A page can be read because it is required for a user-initiated operation such as an SQL query, or as part of a `read-ahead` operation performed automatically by InnoDB.
- Accessing a page in the old sublist makes it “young”, moving it to the head of the new sublist. 
  If the page was read because it was required by a user-initiated operation, the first access occurs immediately and the page is made young. 
  If the page was read due to a read-ahead operation, the first access does not occur immediately and might not occur at all before the page is evicted.
- As the database operates, pages in the buffer pool that are not accessed “age” by moving toward the tail of the list.
  Pages in both the new and old sublists age as other pages are made new. Pages in the old sublist also age as pages are inserted at the midpoint. 
  Eventually, a page that remains unused reaches the tail of the old sublist and is evicted.

By default, pages read by queries are immediately moved into the new sublist, meaning they stay in the buffer pool longer. 
A table scan, performed for a **mysqldump** operation or a `SELECT` statement with no `WHERE` clause, 
for example, can bring a large amount of data into the buffer pool and evict an equivalent amount of older data, even if the new data is never used again. 
Similarly, pages that are loaded by the read-ahead background thread and accessed only once are moved to the head of the new list. 
These situations can push frequently used pages to the old sublist where they become subject to eviction.

You can control the insertion point in the LRU list and choose whether `InnoDB` applies the same optimization to blocks brought into the buffer pool by table or index scans. 
The configuration parameter `innodb_old_blocks_pct` controls the percentage of “old” blocks in the LRU list.
The default value of `innodb_old_blocks_pct` is `37`, corresponding to the original fixed ratio of 3/8. 
The value range is `5` (new pages in the buffer pool age out very quickly) to `95` (only 5% of the buffer pool is reserved for hot pages, making the algorithm close to the familiar LRU strategy).

The optimization that keeps the buffer pool from being churned by read-ahead can avoid similar problems due to table or index scans. 
In these scans, a data page is typically accessed a few times in quick succession and is never touched again. 
The configuration parameter `innodb_old_blocks_time` specifies the time window (in milliseconds) after the first access to a page during which it can be accessed 
without being moved to the front (most-recently used end) of the LRU list. 
The default value of `innodb_old_blocks_time` is `1000`. 
Increasing this value makes more and more blocks likely to age out faster from the buffer pool.

**源码口径**（MySQL 9.7.2）：`innodb_old_blocks_pct` 的默认值在源码里就写成 `100 * 3 / 8`（等于 37），范围 5–95，见 `storage/innobase/handler/ha_innodb.cc:23111-23114`；`innodb_old_blocks_time` 默认 1000，范围 0–`UINT32_MAX`，取 0 表示禁用该时间窗（`ha_innodb.cc:23116-23121`）。

内部实现并不使用百分比：`include/buf0lru.h:217` 定义 `BUF_LRU_OLD_RATIO_DIV = 1024`，`LRU_old_ratio` 保存的是这个分母的**分子**，`innodb_old_blocks_pct` 只是对外的换算入口；另有 `BUF_LRU_OLD_TOLERANCE = 20`（`buf/buf0lru.cc:67`）允许 old 子表长度偏离目标值，避免每次插入都重算边界。

LRU list

```sql
mysql> SELECT TABLE_NAME,PAGE_NUMBER,PAGE_TYPE,INDEX_NAME,SPACE FROM information_schema.INNODB_BUFFER_PAGE_LRU WHERE SPACE = 1;
```

#### Free List

#### Flush List

Checkpoint

dirty pages

```sql
mysql> SELECT COUNT(*) FROM information_schema.INNODB_BUFFER_PAGE_LRU  WHERE OLDEST_MODIFICATION > 0;
```

```text
// using SHOW ENGINE INNODB STATUS;
Modified db pages
```

```c
// buf0buf.h
/** The buffer control block structure */
class buf_page_t 
 /** This is set to TRUE when fsp frees a page in buffer pool;
  protected by buf_pool->zip_mutex or buf_block_t::mutex. */
  bool file_page_was_freed;

  /** TRUE if in buf_pool->flush_list; when buf_pool->flush_list_mutex
  is free, the following should hold:
    in_flush_list == (state == BUF_BLOCK_FILE_PAGE ||
                      state == BUF_BLOCK_ZIP_DIRTY)
  Writes to this field must be covered by both buf_pool->flush_list_mutex
  and block->mutex. Hence reads can happen while holding any one of the
  two mutexes */
  bool in_flush_list;

  /** true if in buf_pool->free; when buf_pool->free_list_mutex is free, the
  following should hold: in_free_list == (state == BUF_BLOCK_NOT_USED) */
  bool in_free_list;

  /** true if the page is in the LRU list; used in debugging */
  bool in_LRU_list;

  /** true if in buf_pool->page_hash */
  bool in_page_hash;

  /** true if in buf_pool->zip_hash */
  bool in_zip_hash;
#endif /* UNIV_DEBUG */

#endif /* !UNIV_HOTBACKUP */
};
```

A page on the FLU List must be on the LRU List, but not the other way around.
A data page may be modified multiple times at different times, and the oldest (i.e., first) LSN of the first modification is recorded on the data page, i.e., the oldest_modification.
Different data pages have different oldest_modification, the nodes in the FLU List are sorted according to the oldest_modification,
the linked list tail is the smallest, that is, the earliest data page that has been modified, and when the page needs to be eliminated from the FLU List,
it will be eliminated from the end of the linked list.
To join the FLU List, you need to use flush_list_mutex protection, so the order of the nodes in the FLU List can be ensured.

### Page Hash

### Read-Ahead

A read-ahead request is an I/O request to prefetch multiple pages in the buffer pool asynchronously, in anticipation of impending need for these pages.
The requests bring in all the pages in one extent. InnoDB uses two read-ahead algorithms to improve I/O performance:

Linear read-ahead is a technique that predicts what pages might be needed soon based on pages in the buffer pool being accessed sequentially.
You control when InnoDB performs a read-ahead operation by adjusting the number of sequential page accesses required to trigger an asynchronous read request, using the configuration parameter innodb_read_ahead_threshold.
Before this parameter was added, InnoDB would only calculate whether to issue an asynchronous prefetch request for the entire next extent when it read the last page of the current extent.

The configuration parameter _innodb_read_ahead_threshold_ controls how sensitive InnoDB is in detecting patterns of sequential page access.
If the number of pages read sequentially from an extent is greater than or equal to innodb_read_ahead_threshold,
InnoDB initiates an asynchronous read-ahead operation of the entire following extent. innodb_read_ahead_threshold can be set to any value from 0-64.
The default value is 56. The higher the value, the more strict the access pattern check.
For example, if you set the value to 48, InnoDB triggers a linear read-ahead request only when 48 pages in the current extent have been accessed sequentially.
If the value is 8, InnoDB triggers an asynchronous read-ahead even if as few as 8 pages in the extent are accessed sequentially.
You can set the value of this parameter in the MySQL configuration file, or change it dynamically with the SET GLOBAL statement, which requires privileges sufficient to set global system variables.

Random read-ahead is a technique that predicts when pages might be needed soon based on pages already in the buffer pool, regardless of the order in which those pages were read.
If 13 consecutive pages from the same extent are found in the buffer pool, InnoDB asynchronously issues a request to prefetch the remaining pages of the extent.
To enable this feature, set the configuration variable _innodb_random_read_ahead_ to ON.

## Checkpoints

### Fuzzy Checkpoint

InnoDB implements a checkpoint mechanism known as fuzzy checkpointing.
InnoDB flushes modified database pages from the buffer pool in small batches.
There is no need to flush the buffer pool in one single batch, which would disrupt processing of user SQL statements during the checkpointing process.

- Master
- Flush_lru_list
- Async/Sync Flush
- Dirty Page too much

Page Cleaner Thread

Flush_lru_list

```text
innodb_lru_scan_depth	1024
```

`innodb_lru_scan_depth` 默认 1024，最小 100（`ha_innodb.cc:22697-22700`），它是 page cleaner 每轮为每条 LRU 链表清理出的空闲页目标深度；实际每秒工作量约为 `innodb_lru_scan_depth * innodb_buffer_pool_instances`。

Dirty Page too much

```text
innodb_max_dirty_pages_pct	90.000000
innodb_max_dirty_pages_pct_lwm	0.000000
```

⚠️ **默认值已漂移**：`innodb_max_dirty_pages_pct` 在 MySQL 8.0.13 起由 75 改为 **90**，9.7 源码沿用该默认值（`ha_innodb.cc:22394-22397`，`MYSQL_SYSVAR_DOUBLE(max_dirty_pages_pct, srv_max_buf_pool_modified_pct, ..., 90.0, 0, 99.999, 0)`）。旧资料里写 75 的随处可见，照抄会得到错误的水位判断。该参数设定的是脏页**比例目标**，不影响刷脏速率；速率由 `innodb_io_capacity` 与 adaptive flushing 决定。

adaptive flushing

```text
innodb_adaptive_flushing	ON
innodb_adaptive_flushing_lwm	10.000000
```

innodb_flush_neighbors default 0 only itself

better for HHD
worse for SSD

### Sharp Checkpoint

During crash recovery, InnoDB looks for a checkpoint label written to the log files.
It knows that all modifications to the database before the label are present in the disk image of the database.
Then InnoDB scans the log files forward from the checkpoint, applying the logged modifications to the database.

Configuring InnoDB Buffer Pool Prefetching (Read-Ahead)


A `read-ahead` request is an I/O request to prefetch multiple pages in the `buffer pool` asynchronously, in anticipation of impending need for these pages.
The requests bring in all the pages in one [extent](/docs/CS/DB/MySQL/memory.md?id=extent). `InnoDB` uses two read-ahead algorithms to improve I/O performance:

**Linear** read-ahead is a technique that predicts what pages might be needed soon based on pages in the buffer pool being accessed sequentially.
You control when `InnoDB` performs a read-ahead operation by adjusting the number of sequential page accesses required to trigger an asynchronous read request, using the configuration parameter `innodb_read_ahead_threshold`.
Before this parameter was added, `InnoDB` would only calculate whether to issue an asynchronous prefetch request for the entire next extent when it read the last page of the current extent.

The configuration parameter `innodb_read_ahead_threshold` controls how sensitive `InnoDB` is in detecting patterns of sequential page access.
If the number of pages read sequentially from an extent is greater than or equal to `innodb_read_ahead_threshold`, `InnoDB` initiates an asynchronous read-ahead operation of the entire following extent.
`innodb_read_ahead_threshold` can be set to any value from 0-64. The default value is 56. The higher the value, the more strict the access pattern check.
For example, if you set the value to 48, `InnoDB` triggers a linear read-ahead request only when 48 pages in the current extent have been accessed sequentially.
If the value is 8, `InnoDB` triggers an asynchronous read-ahead even if as few as 8 pages in the extent are accessed sequentially.

**Random** read-ahead is a technique that predicts when pages might be needed soon based on pages already in the buffer pool, regardless of the order in which those pages were read.
If 13 consecutive pages from the same extent are found in the buffer pool, `InnoDB` asynchronously issues a request to prefetch the remaining pages of the extent.
To enable this feature, set the configuration variable `innodb_random_read_ahead` to `ON`.

The `SHOW ENGINE INNODB STATUS` command displays statistics to help you evaluate the effectiveness of the read-ahead algorithm. 
Statistics include counter information for the following global status variables:

- `Innodb_buffer_pool_read_ahead`
- `Innodb_buffer_pool_read_ahead_evicted`
- `Innodb_buffer_pool_read_ahead_rnd`

This information can be useful when fine-tuning the `innodb_random_read_ahead` setting.

#### extent

A group of **pages** within a **tablespace**. For the default **page size** of 16KB, an extent contains 64 pages.
In MySQL 5.6, the page size for an `InnoDB` instance can be 4KB, 8KB, or 16KB, controlled by the `innodb_page_size` configuration option.
For 4KB, 8KB, and 16KB pages sizes, the extent size is always 1MB (or 1048576 bytes).

Support for 32KB and 64KB `InnoDB` page sizes was added in MySQL 5.7.6. For a 32KB page size, the extent size is 2MB. For a 64KB page size, the extent size is 4MB.

`InnoDB` features such as **segments**, **read-ahead** requests and the **doublewrite buffer** use I/O operations that read, write, allocate, or free data one extent at a time.

## Change Buffer

The change buffer is a special data structure that caches changes to [secondary index](/docs/CS/DB/MySQL/Index.md?id=clustered-and-secondary-indexes) pages when those pages are not in the **buffer pool**.
The buffered changes, which may result from `INSERT`, `UPDATE`, or `DELETE` operations (DML), are merged later when the pages are loaded into the buffer pool by other read operations.
The set of features involving the change buffer is known collectively as *change buffering*, consisting of *insert buffering*, *delete buffering*, and *purge buffering*.

> [!NOTE]
>
> **9.7 现状**：change buffer 既没有废弃也没有移除——`storage/innobase/include/ibuf0ibuf.h`、`ibuf0types.h` 与 `innodb_change_buffering` 的取值表（`handler/ha_innodb.cc:582-595`）在 9.7.2 源码中齐备，全树 grep `deprecat` 在该模块无命中，`innodb_change_buffering` 的 sysvar 默认参数是 `IBUF_USE_ALL`（`ha_innodb.cc:23293-23297`），即**默认仍启用**；9.7 手册仍写「On disk, the change buffer is part of the system tablespace」。
>
> 两个坑：① 该 sysvar 的**注释文本**仍是 `"Buffer changes to reduce random access: OFF (default), ON, inserting, deleting, changing, or purging."`，取值名与实际枚举名（`none/inserts/deletes/changes/purges/all`）完全对不上，是陈旧文案；② 9.7 手册在同一个条目里既写 `Default Value all` 又写「Before MySQL 8.4, the default value was all」，8.4 手册的 `Default Value` 又标为 `none`——三处互相矛盾，**结论以 9.7.2 源码的 sysvar 默认参数为准**。

The change buffer only supports `secondary indexes`. Clustered indexes, full-text indexes, and spatial indexes are not supported. 
Full-text indexes have their own caching mechanism.
Change buffering is not supported for a secondary index if the index contains a descending index column or if the primary key includes a descending index column.

When the relevant index page is brought into the buffer pool while associated changes are still in the change buffer,
the changes for that page are applied in the buffer pool (merged) using the data from the change buffer.
Periodically, the purge operation that runs during times when the system is mostly idle, or during a slow shutdown, writes the new index pages to disk. 
The purge operation can write the disk blocks for a series of index values more efficiently than if each value were written to disk immediately.

Physically, the change buffer is part of the system tablespace, so that the index changes remain buffered across database restarts. 
The changes are only applied (merged) when the pages are brought into the buffer pool due to some other read operation.

Insert buffering is not used if the secondary index is unique, because the uniqueness of new values cannot be verified before the new entries are written out. 
Other kinds of change buffering do work for unique indexes.

![Content is described in the surrounding text.](https://dev.mysql.com/doc/refman/9.7/en/images/innodb-change-buffer.png)

Unlike [clustered indexes](/docs/CS/DB/MySQL/Index.md?id=clustered-and-secondary-indexes), secondary indexes are usually nonunique, and inserts into secondary indexes happen in a relatively random order.
Similarly, deletes and updates may affect secondary index pages that are not adjacently located in an index tree.
Merging cached changes at a later time, when affected pages are read into the buffer pool by other operations,
avoids substantial random access I/O that would be required to read secondary index pages into the buffer pool from disk.

Periodically, the purge operation that runs when the system is mostly idle, or during a slow shutdown, writes the updated index pages to disk.
The purge operation can write disk blocks for a series of index values more efficiently than if each value were written to disk immediately.

Change buffer merging may take several hours when there are many affected rows and numerous secondary indexes to update.
During this time, disk I/O is increased, which can cause a significant slowdown for disk-bound queries.
Change buffer merging may also continue to occur after a transaction is committed, and even after a server shutdown and restart.

In memory, the change buffer occupies part of the buffer pool.
On disk, the change buffer is part of the system tablespace, where index changes are buffered when the database server is shut down.
The type of data cached in the change buffer is governed by the `innodb_change_buffering` variable.

```text
// using SHOW ENGINE INNODB STATUS;
Ibuf: size 1, free list len 0, seg size 2, 0 merges
merged operations:
insert 0, delete mark 0, delete 0
discarded operations:
insert 0, delete mark 0, delete 0
```

```cpp
// include/ibuf0ibuf.h:45-47
/** Default value for maximum on-disk size of change buffer in terms
of percentage of the buffer pool. */
constexpr uint32_t CHANGE_BUFFER_DEFAULT_SIZE = 5;

// srv/srv0srv.cc:469
uint srv_change_buffer_max_size = CHANGE_BUFFER_DEFAULT_SIZE;
```

常量与变量分在两处：默认值 `5` 是 `ibuf0ibuf.h` 里的 `constexpr uint32_t`，`srv_change_buffer_max_size` 只是拿它做初值；对外生效的入口是 `ha_innodb.cc:23299-23304` 的 `MYSQL_SYSVAR_UINT(change_buffer_max_size, ...)`，范围 0–50，变更走 `innodb_change_buffer_max_size_update()`。

How much space does InnoDB use for the change buffer?

Prior to the introduction of the innodb_change_buffer_max_size configuration option in MySQL 5.6, the maximum size of the on-disk change buffer in the system tablespace was 1/3 of the InnoDB buffer pool size.

In MySQL 5.6 and later, the innodb_change_buffer_max_size configuration option defines the maximum size of the change buffer as a percentage of the total buffer pool size.
By default, innodb_change_buffer_max_size is set to 5 in MySQL 9.7 (25 in 8.0 / 8.4). The maximum setting is 50.

⚠️ 默认上限从 25% 降到 **5%**：这条 8.0 时代的口径在 9.7 已经不成立，9.7 手册与 9.7.2 源码（`CHANGE_BUFFER_DEFAULT_SIZE = 5`）一致。

InnoDB does not buffer an operation if it would cause the on-disk change buffer to exceed the defined limit.

Change buffer pages are not required to persist in the buffer pool and may be evicted by LRU operations.

How do I determine the current size of the change buffer?

The current size of the change buffer is reported by SHOW ENGINE INNODB STATUS \G, under the INSERT BUFFER AND ADAPTIVE HASH INDEX heading.

For example:

```text
-------------------------------------
INSERT BUFFER AND ADAPTIVE HASH INDEX
-------------------------------------
Ibuf: size 1, free list len 0, seg size 2, 0 merges
```

Relevant data points include:

size: The number of pages used within the change buffer.
Change buffer size is equal to seg size - (1 + free list len). 
The 1 + value represents the change buffer header page.

seg size: The size of the change buffer, in pages.

When does change buffer merging occur?

- When a page is read into the buffer pool, buffered changes are merged upon completion of the read, before the page is made available.
- Change buffer merging is performed as a background task.
  The `innodb_io_capacity` parameter sets an upper limit on the I/O activity performed by InnoDB background tasks such as merging data from the change buffer.
- A change buffer merge is performed during crash recovery.
  Changes are applied from the change buffer (in the system tablespace) to leaf pages of secondary indexes as index pages are read into the buffer pool.
- The change buffer is fully durable and can survive a system crash. Upon restart, change buffer merge operations resume as part of normal operations.
- A full merge of the change buffer can be forced as part of a slow server shutdown using --innodb-fast-shutdown=0.

When is the change buffer flushed?

Updated pages are flushed by the same flushing mechanism that flushes the other pages that occupy the buffer pool.

## Adaptive Hash Index

An optimization for InnoDB tables that can speed up lookups using `=` and `IN` operators, by constructing a **hash index** in memory.
MySQL monitors index searches for InnoDB tables, and if queries could benefit from a hash index, it builds one automatically for index **pages** that are frequently accessed.
In a sense, the adaptive hash index configures MySQL at runtime to take advantage of ample main memory, coming closer to the architecture of main-memory databases.
This feature is controlled by the `innodb_adaptive_hash_index` configuration option.
Because this feature benefits some workloads and not others, and the memory used for the hash index is reserved in the **buffer pool**, 
typically you should benchmark with this feature both enabled and disabled.

The hash index is always built based on an existing **B-tree** index on the table.
MySQL can build a hash index on a prefix of any length of the key defined for the B-tree, depending on the pattern of searches against the index.
A hash index can be partial; the whole B-tree index does not need to be cached in the buffer pool.

### Default Value Reversal

`innodb_adaptive_hash_index` 的默认值在 **MySQL 8.4 由 ON 翻转为 OFF**，9.7 延续 OFF。9.7.2 源码同一处存在三条互相矛盾的线索，只有第一条是默认值：

| 线索 | 内容 | 能否当默认值 |
| :--- | :--- | :--- |
| sysvar 宏的默认参数 | `handler/ha_innodb.cc:22484-22488`，`MYSQL_SYSVAR_BOOL(adaptive_hash_index, srv_btr_search_enabled, ..., nullptr, innodb_adaptive_hash_index_update, false)` 末参 `false` | ✅ 这才是真相 |
| 同一处的注释文案 | `"Enable InnoDB adaptive hash index (enabled by default). Disable with --skip-innodb-adaptive-hash-index."` | ❌ 陈旧文案 |
| C++ 全局初值 | `bool srv_btr_search_enabled = true;`（`btr/btr0sea.cc:67`） | ❌ 只是被 sysvar 覆盖前的进程初值 |

9.7 手册与 sysvar 参数一致：`Default Value OFF`，并注明 "Before MySQL 8.4, this option was enabled by default."

关闭时哈希表被立即清空，清空期间正常操作可继续，原本走哈希访问路径的查询直接回落到索引的 B-tree；重新开启后哈希表在正常负载中重新填充。该变量是动态的，用 `SET GLOBAL` 修改即可，**无需重启**（运行时修改需要设置全局变量的权限）。官方口径仍是：按真实负载分别开、关做 benchmark。

> [!TIP]
>
> **教训比结论更值钱**：sysvar 存在 ≠ 注释还成立。判断默认值只认 `MYSQL_SYSVAR_*` 宏的默认参数（参数序 `name, var, flags, comment, check, update, default, min, max, blksize` 里的第 7 个）与手册的 `Default Value` 字段；**注释文案和 C++ 全局初值都会骗人**，本页的 Change Buffer 一节是同一个坑的第二例。

```cpp
// btr/btr0sea.cc:87-94
/** If the number of records on the page divided by this parameter
would have been successfully accessed using a hash index, the index
is then built on the page, assuming the global limit has been reached */
constexpr uint32_t BTR_SEARCH_PAGE_BUILD_LIMIT = 16;

/** The global limit for consecutive potentially successful hash searches,
before hash index building is started */
constexpr uint32_t BTR_SEARCH_BUILD_LIMIT = 100;

// include/btr0sea.h:45-66  The search info struct in an index
struct btr_search_t {
  /** Number of blocks in this index tree that have search index built i.e.
  block->ahi.index points to this index. */
  std::atomic<size_t> ref_count;
  ...
  /** when this exceeds BTR_SEARCH_HASH_ANALYSIS, the hash analysis starts; this
  is reset if no success noticed. */
  std::atomic<uint64_t> hash_analysis;
  /** true if the last search would have succeeded, or did succeed, using the
  hash index; NOTE that the value here is not exact: it is not calculated for
  every search, and the calculation itself is not always accurate! */
  bool last_hash_succ;
  /** number of consecutive searches which would have succeeded, or did succeed,
  using the hash index; the range is 0 .. BTR_SEARCH_BUILD_LIMIT + 5. */
  std::atomic<uint64_t> n_hash_potential;
  ...
};
```

与 5.x/8.0 时代摘录的三处差异：`BTR_SEARCH_BUILD_LIMIT` 不再是头文件里的 `#define`，而是 `btr/btr0sea.cc:94` 的 `constexpr uint32_t`；`struct btr_search_t`（`include/btr0sea.h:46`）的计数字段已全部原子化，`n_hash_potential` 是 `std::atomic<uint64_t>`（`:66`）而非 `ulint`；`BTR_SEARCH_HASH_ANALYSIS = 17` 同样是 `constexpr uint32_t`（`include/btr0sea.h:340`）。

分区数由 `innodb_adaptive_hash_index_parts` 控制，默认 **8**、范围 1–512、只读（`ha_innodb.cc:22493-22497`），每个分区用各自的 latch 保护，目的是降低 AHI 自身 latch 的争用。

## Log Buffer

The log buffer is the memory area that holds data to be written to the log files on disk.

A large log buffer enables large transactions to run without the need to write [redo log](/docs/CS/DB/MySQL/redolog.md) data to disk before the transactions commit.
Thus, if you have transactions that update, insert, or delete many rows, increasing the size of the log buffer saves disk I/O.

Log buffer size is defined by the `innodb_log_buffer_size` variable.
The contents of the log buffer are periodically flushed to disk.

⚠️ 默认值已变大：8.0 手册的默认值是 **16MB**，8.4 与 9.7 手册均为 **64MB**（`Default Value 67108864`，min 1MB）。9.7 源码里默认值不是字面量而是常量 `INNODB_LOG_BUFFER_SIZE_DEFAULT`（`ha_innodb.cc:22835-22840`），另外该值必须是 `OS_FILE_LOG_BLOCK_SIZE`（512）的倍数，32KB/64KB 页大小时手册要求至少 16MB。

```sql
mysql> show variables like 'innodb_log_buffer_size'; -- 67108864 (9.7)
```

The `innodb_flush_log_at_trx_commit` variable controls how the contents of the log buffer are written and flushed to disk.
默认值 1（严格 ACID），取值 0/1/2 的语义见 [redo log](/docs/CS/DB/MySQL/redolog.md) 一页。

```sql
mysql> show variables like 'innodb_flush_log_at_trx_commit'; -- 1
```

The `innodb_flush_log_at_timeout` variable controls log flushing frequency.
9.7 手册给出范围 1–2700 秒，默认 1 秒；取 0 表示每次提交都刷。

```sql
mysql> show variables like 'innodb_flush_log_at_timeout'; -- 1
```

Buffer Chunks

## Verified Defaults In MySQL 9.7

下表逐项对照 9.7.2 源码与本页正文，`ha_innodb.cc` 指 `storage/innobase/handler/ha_innodb.cc`。sysvar 宏的参数序是 `name, var, flags, comment, check, update, default, min, max, blksize`——**默认值是第 7 个参数**，不要拿 C++ 全局初值当默认值。

| sysvar | 9.7 默认值 | 范围 | 源码位置 | 版本坐标 |
| :--- | :--- | :--- | :--- | :--- |
| `innodb_buffer_pool_size` | 134217728（128MB） | — | 9.7 手册 | 与 8.0 相同 |
| `innodb_buffer_pool_instances` | 1 | 1–64 | 9.7 手册（Default Value 标注为 see description） | 仅当 buffer pool > 1GiB 时默认值才可能大于 1（按 chunk 数推算） |
| `innodb_buffer_pool_chunk_size` | 134217728（128MB） | 1MB 起 | 9.7 手册 | buffer pool 大小必须是 `chunk_size * instances` 的整数倍 |
| `innodb_buffer_pool_dump_pct` | 25 | 1–100 | `ha_innodb.cc:22663-22666` | — |
| `innodb_old_blocks_pct` | 37（源码写作 `100 * 3 / 8`） | 5–95 | `ha_innodb.cc:23111-23114` | 内部按 `BUF_LRU_OLD_RATIO_DIV = 1024` 的分子存储 |
| `innodb_old_blocks_time` | 1000 | 0–`UINT32_MAX` | `ha_innodb.cc:23116-23121` | 0 表示禁用 |
| `innodb_lru_scan_depth` | 1024 | 100–`UINT32_MAX` | `ha_innodb.cc:22697-22700` | — |
| `innodb_read_ahead_threshold` | 56 | 0–64 | `ha_innodb.cc:23338-23342` | 0 表示关闭线性预读 |
| `innodb_max_dirty_pages_pct` | **90.0** | 0–99.999 | `ha_innodb.cc:22394-22397` | **8.0.13 起由 75 改为 90** |
| `innodb_adaptive_hash_index` | **OFF** | bool | `ha_innodb.cc:22484-22488` | **8.4 起默认 OFF**（此前 ON） |
| `innodb_adaptive_hash_index_parts` | 8 | 1–512，只读 | `ha_innodb.cc:22493-22497` | — |
| `innodb_change_buffering` | `all` | none/inserts/deletes/changes/purges/all | `ha_innodb.cc:23293-23297` | 9.7 手册注释与 8.4 手册 `Default Value` 与之矛盾，见 Change Buffer 一节 |
| `innodb_change_buffer_max_size` | **5** | 0–50 | `ha_innodb.cc:23299-23304`，常量在 `include/ibuf0ibuf.h:47` | 8.0/8.4 为 25 |
| `innodb_log_buffer_size` | **64MB** | 1MB–`UINT32_MAX` | `ha_innodb.cc:22835-22840` | 8.0 为 16MB |
| `innodb_flush_log_at_trx_commit` | 1 | 0–2 | 9.7 手册（Enumeration） | — |
| `innodb_page_size` | 16384 | 4096/8192/16384/32768/65536，只读 | 9.7 手册 | 实例初始化后不可改 |

## Page

In InnoDB, the minimum unit of data management is a page, which is 16 KB by default, and the page can store data with control information in addition to user data.
The smallest unit of read and write in the InnoDB IO subsystem is also a page.
If you want to read data from the compressed page, the compressed page needs to be decompressed first to form a decompressed page, and the decompressed page is 16KB.
The size of the compressed page is specified when creating a table, and currently supports 16K, 8K, 4K, 2K, and 1K.
Even if the compressed page size is set to 16K, there is some benefit in the blob/varchar/text type.
For example, if the size of the compressed page is 4K, if a data page cannot be compressed to less than 4K,
you need to perform a B-tree splitting operation, which is a time-consuming operation.
Under normal circumstances, the buffer pool will cache both compressed and decompressed pages,
and when the free list is insufficient,
the elimination policy will be determined according to the actual load of the system.
If the system bottleneck is on the I/O, only the decompressed pages are evicted,
and the compressed pages remain in the buffer pool, otherwise both the decompressed and compressed pages are evicted.

row format:

- Compact
- Redundant
- Dynamic default
- Compressed

数据页结构如下表


| Name                | Size   | Description |
| ------------------- | ------ | ----------- |
| File Header         | 38Byte |             |
| Page Header         | 56Byte |             |
| Infimum + superemum | 26Byte |             |
| User Records        |        |             |
| Free Spaces         |        |             |
| Page Directory      |        |             |
| File Tailer         | 8Byte  |             |



Infimum记录 和 Supremum记录 是 InnoDB 给我们自动生成的两个伪记录，并且规定：

- Infimum记录 作为本页面中最小的记录
- Supremum记录 作为本页面中最大的记录

各条记录之间按照主键值大小组成了一个单向链表 由于链表无法实现快速搜索 引入了一个页目录 通过将记录进行分组 把每个组最大的那条记录在页面中的地址取出组成一个指针数组 用于二分搜索



And since these two Records are not our own defined Records, they are not stored in the User Records section of the page,
they are placed separately in a section called Infimum + Supremum.

Both Infimum and Supremum consist of a 5-byte record header and an 8-byte fixed part.
The fixed part of the smallest record is the word Infimum, and the fixed part of the largest record is the word Supremum.
Since there are no variable-length fields or nullable fields, there are naturally no variable-length field lists and no NULL value lists.

The structure of the Infimum and Supremum records is shown below.
Note that the Infimum record header record_type=2 indicates the minimum record.
Supremum Record header record_type=3, which indicates the maximum record.

After adding the Infimum and Supremum records, the records on the page look like the following figure.
The next_record of the Infimum record header points to the record with the smallest primary key on the page,
and the next_record of the record with the largest primary key on the page points to the Supremum.
The Infimum and Supremum form the record boundary.
Note also that Infimum and Supremum are the first in the heAP_NO order in the record header.

User Records is the part that actually stores row Records, and Free Space is obviously Free Space.
At the beginning of page generation, there is no User Records part.
Every time a record is inserted, a Space of record size will be applied from the Free Space part to the User Records part.
When the Space of the Free Space part is used up, the page will also be used up.

First of all, InnoDB's data is organized by index.
The B+ tree index itself cannot find a specific record, but only the page where the record is located.
The page is the smallest basic unit of data storage.


| col1         | col2 | col3 |
| ------------ | ---- | ---- |
| record_type  | 1bit |      |
| next_record  |      |      |
| delete_mask  | 1bit | 0/1  |
| min_rec_mask |      |      |
| n_owned      |      |      |
| heap_no      |      |      |
| next_record  |      |      |
| next_record  |      |      |
| next_record  |      |      |
| next_record  |      |      |
| next_record  |      |      |

next_record a single linked list from infimum to superemum

#### Page Directory

start 2 slots, number in `n_owned`, slot number is the biggest one of all records

1. min slot always 1 record
2. max slot 1~8 records
3. inner slot 4~8 records

spilt 2slots(4 and 5) when overlimit 8, add a bigger slot

Find Record:

1. find the lowest primary value though binary search
2. Iterate records in slot by `next_record`

#### Page Header

slots numner

offset

#### File Header

- checksum
- page offset
- page lsn
- page prev
- page next
- page type
- flush lsn(only for system tablespace)
- belong tablespace

#### File Trailer

- checksum
- LSN

spilt page will new two pages first, then the old page will be directory page

### Tablespace

const > ref > ref_or_null > range > index > all



## Thread



MySQL 会给每个线程分配一块内存用于排序，称为 sort_buffer



## Shard

Thread Memory：Thread level

- Sharing: Server layer
- InnoDB Buffer Pool: InnoDB layer

Shard when single table szie > InnoDB Buffer Pool size(`innodb_buffer_pool_size`)

## Links

- [InnoDB Storage Engine](/docs/CS/DB/MySQL/InnoDB.md)
- [Redo Log](/docs/CS/DB/MySQL/redolog.md)
- [Undo Log](/docs/CS/DB/MySQL/undolog.md)
- [Tablespace](/docs/CS/DB/MySQL/tablespace.md)
- [Doublewrite Buffer](/docs/CS/DB/MySQL/Double-Buffer.md)

## References

- [MySQL 9.7 Reference Manual: Buffer Pool](https://dev.mysql.com/doc/refman/9.7/en/innodb-buffer-pool.html)
- [MySQL 9.7 Reference Manual: Adaptive Hash Index](https://dev.mysql.com/doc/refman/9.7/en/innodb-adaptive-hash.html)
- [MySQL 9.7 Reference Manual: Change Buffer](https://dev.mysql.com/doc/refman/9.7/en/innodb-change-buffer.html)
- [MySQL 9.7 Reference Manual: InnoDB Checkpoints](https://dev.mysql.com/doc/refman/9.7/en/innodb-checkpoints.html)
- [MySQL 9.7 Reference Manual: InnoDB Startup Configuration](https://dev.mysql.com/doc/refman/9.7/en/innodb-configuration.html)
- [MySQL 9.7 Reference Manual: InnoDB System Variables](https://dev.mysql.com/doc/refman/9.7/en/innodb-parameters.html)
