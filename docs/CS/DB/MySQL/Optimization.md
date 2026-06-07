## 简介

MySQL 优化涉及多个方面，包括查询优化、索引优化、表结构优化和配置优化。

### 执行计划

使用 `EXPLAIN` 查看查询的执行计划：

```sql
EXPLAIN SELECT * FROM users WHERE id = 1;
```

关键字段：

- `select_type`：查询类型（SIMPLE、PRIMARY、SUBQUERY、UNION 等）。
- `type`：访问类型（system、const、eq_ref、ref、range、index、ALL）。
- `possible_keys`：可用的索引。
- `key`：实际使用的索引。
- `key_len`：使用的索引长度。
- `rows`：扫描的行数估计值。
- `Extra`：附加信息（Using index、Using where、Using filesort 等）。

### 索引优化

#### 索引设计原则

SELECT 操作时使用索引需要遵循最左前缀法则。

建立索引：

1. 提高查询速度。
2. 降低写入速度。
3. 占用磁盘空间。

#### 索引选择

- **高选择性列**：选择性越高的列，索引效果越好。
  选择性 = 不同值的数量 / 总行数。
- **短索引**：使用较短的值作为索引。
- **前缀索引**：对字符串列使用前缀索引。
- **复合索引**：多列组合索引，遵循最左前缀原则。
- **覆盖索引**：索引包含所有需要查询的列，避免回表。
- **索引下推（Index Condition Pushdown，ICP）**：在 MySQL 5.6 中引入，将部分 WHERE 条件下推到存储引擎层过滤。

#### 索引失效场景

- 使用了 `!=` 或 `<>` 操作符。
- 对索引列使用了函数或计算。
- 使用了 `LIKE` 且通配符在开头（如 `LIKE '%abc'`）。
- 数据类型不一致。
- 使用了 OR 且部分列没有索引。
- 索引列参与了函数运算。
- 隐式类型转换。

### 查询优化

#### 慢查询分析

使用 `slow_query_log` 记录慢查询：

```ini
slow_query_log = 1
slow_query_log_file = /var/log/mysql/slow.log
long_query_time = 2
```

#### 常见优化技巧

- **减少数据访问量**：使用 `LIMIT`，只查询需要的列。
- **避免全表扫描**：为 WHERE 和 ORDER BY 列建立索引。
- **使用连接（JOIN）替代子查询**。
- **避免在 WHERE 子句中使用函数**。
- **使用 EXPLAIN 分析查询计划**。
- **优化分页查询**：使用索引定位代替 `OFFSET`。

> **SQL 语句的执行顺序**：
> FROM -> ON -> JOIN -> WHERE -> GROUP BY -> HAVING -> SELECT -> DISTINCT -> ORDER BY -> LIMIT

### 表结构优化

- **选择合适的数据类型**：使用最小的数据类型。
- **使用 NOT NULL**：避免 NULL 值的特殊处理。
- **垂直分表**：将不常用的列拆分到单独的表中。
- **水平分表**：将数据分散到多个表中。
- **反范式化**：适当冗余以减少 JOIN 操作。
- **使用合适的存储引擎**。

### 配置优化

#### InnoDB 配置

- `innodb_buffer_pool_size`：缓冲池大小，通常设置为可用内存的 70%-80%。
- `innodb_log_file_size`：重做日志文件大小，影响写入性能。
- `innodb_flush_log_at_trx_commit`：控制日志刷新策略（1=最安全，2=性能更好）。
- `innodb_io_capacity`：InnoDB 在刷新脏页时可用的 I/O 容量。

#### 连接配置

- `max_connections`：最大连接数（默认 151）。
- `thread_cache_size`：线程缓存大小。
- `wait_timeout`：连接超时时间。

#### 查询缓存

MySQL 8.0 已移除查询缓存。

### 分库分表

#### 垂直拆分

按业务将表拆分到不同数据库。

#### 水平拆分

按行将数据分散到多个表或多个数据库。
常用分片策略：

- 哈希分片：通过哈希函数计算数据所在分片。
- 范围分片：按时间或 ID 范围分片。
- 列表分片：按枚举值列表分片。
- 一致性哈希分片：通过一致性哈希算法计算数据所在分片。

### 读写分离

主库处理写操作，从库处理读操作。

### 缓存

使用 Redis 或 Memcached 缓存热点数据，减少数据库压力。

## 性能监控

```sql
-- 查看当前连接状态
SHOW PROCESSLIST;

-- 查看 InnoDB 状态
SHOW ENGINE INNODB STATUS;

-- 查看全局状态变量
SHOW GLOBAL STATUS;

-- 查看配置变量
SHOW VARIABLES;

-- 查看表信息
SHOW TABLE STATUS;
```

### Buffer Pool 命中率

```sql
-- 缓冲池命中率应高于 99%
SHOW GLOBAL STATUS LIKE 'Innodb_buffer_pool_read_%';
-- 命中率 = Innodb_buffer_pool_read_requests / (Innodb_buffer_pool_read_requests + Innodb_buffer_pool_reads)
```

## 参考

1. [MySQL 官方文档 - 优化](https://dev.mysql.com/doc/refman/8.0/en/optimization.html)
