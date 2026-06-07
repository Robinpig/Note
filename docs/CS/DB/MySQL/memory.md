## 简介

MySQL 在内存和磁盘上存储数据。
内存中的数据通过**缓冲区（Buffers）** 管理。

### 缓冲池

**缓冲池（Buffer Pool）** 是 InnoDB 在访问表和索引数据时缓存这些数据的主内存区域。
缓冲池允许直接从内存处理频繁使用的数据，从而加速处理。
在专用服务器上，通常将高达 80% 的物理内存分配给缓冲池。

为了高效管理大容量内存，缓冲池被组织为**页面（pages）** 的集合，页面是固定大小的块，通常为 16KB。
使用**变体 LRU（最近最少使用）** 算法的变体将页面作为列表管理。
当需要空间将新页面添加到缓冲池时，最近最少使用的页面被逐出，将新页面添加到列表的中间。

缓冲池的一些重要特性：

- **页面大小**：默认 16KB，可通过 `innodb_page_size` 配置。
- **预读（Read-Ahead）**：InnoDB 异步地将数据页预取到缓冲池中，预测哪些页面将很快被访问。
- **扫描抗性（Scan Resistance）**：使用 LRU 中点插入策略，防止大扫描操作冲掉缓冲池中的热数据。
- **缓冲池实例**：为减少并发竞争，可将缓冲池划分为多个实例，每个实例管理自己的 LRU 列表。
- **内存定位（Memory Locality）**：将缓冲池划分为多个实例时，每个实例可分配单独的物理内存区域，提高 CPU 缓存效率。
- **Change Buffer**：一种特殊的数据结构，当非唯一辅助索引页不在缓冲池中时，缓存对这些页的更改。
  当页面被读入缓冲池时，合并的更改被应用。

### 自适应哈希索引

**自适应哈希索引（Adaptive Hash Index，AHI）** 使 InnoDB 在系统负载适当时，在索引搜索频繁的索引上执行类似内存数据库的性能。
该特性由 `innodb_adaptive_hash_index` 选项启用，或在服务器启动时由 `--skip-innodb-adaptive-hash-index` 禁用。

### 日志缓冲区

**日志缓冲区（Log Buffer）** 是保存要写入磁盘日志文件的数据的内存区域。
日志缓冲区大小由 `innodb_log_buffer_size` 变量定义（默认 16MB）。
日志缓冲区内容定期刷入磁盘。
一个大的日志缓冲区可在事务提交前无需将重做日志数据写入磁盘的情况下运行大事务。

### 内存池

**内存池（Memory Pool）** 在 InnoDB 中用于分配内存。
如果操作系统允许，InnoDB 使用操作系统原生内存分配器。
如果原生内存分配器的性能不符合预期，可启用 `innodb_use_sys_malloc` 配置选项以使用自定义内存分配器。

### 自适应刷新哈希索引

自适应刷新哈希索引（Adaptive Flushing Hash Index）用于提高刷新效率。

### 表空间

请参考 [Tablespace](/docs/CS/DB/MySQL/tablespace.md)。

```c
// buf0buf.cc -- 缓冲池的核心实现
// buf0flu.cc -- 缓冲池刷新
// buf0lru.cc -- LRU 替换策略
// buf0rea.cc -- 预读
```

### 脏页

**脏页（Dirty Page）** 是缓冲池中已修改但尚未写入磁盘的页面。
缓存池中的脏页通过后台线程刷新到磁盘。

### 链式结构

```c
/** 缓冲池结构 */
struct buf_pool_t {
    /** LRU 链表 */
    UT_LIST_BASE_NODE_T(buf_page_t) LRU;
    /** flush 链表 */
    UT_LIST_BASE_NODE_T(buf_page_t) flush_list;
    /** free 链表 */
    UT_LIST_BASE_NODE_T(buf_page_t) free;
    /** 哈希表，用于通过 page_no 快速查找页 */
    hash_table_t *page_hash;
    /** 块大小 */
    ulint curr_size;
    /** 实例号 */
    ulint instance_no;
};
```

缓冲池中的每个控制块：

```c
/** 缓冲页控制块 */
struct buf_page_t {
    /** 页在表空间中的偏移 */
    page_no_t page_no;
    /** 表空间 ID */
    space_id_t space;
    /** 访问计数 */
    ulint access_time;
    /** flush 类型 */
    ulint flush_type;
    /** IO 固定计数 */
    ulint io_fix;
    /** 缓冲页状态 */
    buf_page_state_t state;
    /** LRU 位置 */
    buf_page_lru_t lru_position;
};
```

### 预读

InnoDB 使用两种预读算法来提高 I/O 性能：

1. **线性预读（Linear Read-Ahead）**：根据 LRU 列表中连续访问的页面模式进行预读。
2. **随机预读（Random Read-Ahead）**：当 LRU 列表中一个区域的所有页面都被访问时进行预读（在 MySQL 5.5 中已废弃）。

### 刷新

InnoDB 使用两种刷新策略：

1. **自适应刷新（Adaptive Flushing）**：根据重做日志生成速率动态调整刷新速率。
2. **空闲刷写（Idle Flushing）**：在系统空闲时进行刷新。

## 配置变量

| 变量名 | 默认值 | 描述 |
|--------|--------|------|
| `innodb_buffer_pool_size` | 134217728 | 缓冲池大小（字节） |
| `innodb_buffer_pool_instances` | 8 | 缓冲池实例数 |
| `innodb_log_buffer_size` | 16777216 | 日志缓冲区大小（字节） |
| `innodb_adaptive_hash_index` | ON | 是否启用自适应哈希索引 |
| `innodb_change_buffer_max_size` | 25 | Change Buffer 最大大小（占缓冲池百分比） |
| `innodb_flush_neighbors` | 1 | 刷新时是否刷新相邻页 |
| `innodb_old_blocks_time` | 1000 | LRU 列表中旧块区域的时间阈值 |
| `innodb_old_blocks_pct` | 37 | LRU 列表中旧块区域的百分比 |
| `innodb_read_ahead_threshold` | 56 | 线性预读阈值 |
| `innodb_random_read_ahead` | OFF | 是否启用随机预读 |

## 链接

- [InnoDB 存储引擎](/docs/CS/DB/MySQL/InnoDB.md?id=innodb-buffer-pool)
