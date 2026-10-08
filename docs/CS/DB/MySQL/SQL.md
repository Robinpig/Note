## Introduction

这页沿着「一条语句在服务器里走完的阶段」组织：连接与解析、优化与执行、锁与 MVCC 的分界，
再落到 `count` / `NULL` / `LIMIT` 这几个反复被问的行为语义，最后是 `EXPLAIN` 的读法与索引失效清单。
代价模型公式与 Access Path 的枚举不在这里，见 Optimizer；本篇只给阶段划分与行为坐标。

| 项 | 值 |
| :--- | :--- |
| 正文默认版本 | MySQL 9.7.x LTS（最新 9.7.3，2026-08-18） |
| 源码核实基线 | tag `mysql-9.7.2` |
| 次要兼容目标 | 8.4.x LTS |
| 已停止支持 | 8.0（EOL 2026-04-30）、5.7（EOL 2023-10） |
| 核实日期 | 2026-10-07 |

版本相关的移除与改名统一记在 [Version_Migration](/docs/CS/DB/MySQL/Version_Migration.md)，
本篇正文里只在具体条目上标注版本坐标。

## How a SQL execute

一条语句依次经过这些阶段：

- **connector**：建立连接、认证账号、加载权限（连接复用见下）
- **Cache**：8.0 之前查询缓存所在的位置，现在已不存在
- **Analysis**：解析器做词法与语法分析，构造解析树
- **Preprocessor**：预处理器，校验表名列名、展开 `*`、补全歧义
- **Optimizer**：优化器按代价选择访问路径与连接顺序
- **Executor**：执行器按 handler 接口协议驱动引擎
- **Engine**：存储引擎（InnoDB 等）负责真正的读写

### Connection Timeout and Reset

`wait_timeout` 默认 28800 秒，即 8 小时，空闲超过这个时长的连接会被服务端关掉；
交互客户端另走 `interactive_timeout`。连接池里的长连接复用对应服务端的 `COM_RESET_CONNECTION`
（`mysql_reset_connection`）：清掉会话变量、临时表、事务状态等，但保留连接本身，
代价远低于重新握手与认证。

### Query Cache

`query_cache_type DEMAND` 这类配置只存在于 5.7 及更早。**MySQL 8.0 已整体移除查询缓存**，
`query_cache_type`、`query_cache_size` 等变量随之消失，语句解析后直接进入优化阶段。
残留的写法要分清三种状态：`SQL_CACHE` 已随缓存一起移除；`SQL_NO_CACHE` 仍可解析但被标记为
deprecated 且**完全无效**；`SQL_CALC_FOUND_ROWS` 与 `FOUND_ROWS()` 自 8.0.17 起废弃（见下文 Limit 小节）。
移除的原因是失效粒度太粗——任一写操作会清掉同一张表的全部缓存，并发写入下反而成为瓶颈。
现在 server 层与引擎层之间只剩表定义缓存（table definition cache），它缓存的是表结构而非结果集。

### Rows Examined

慢日志里的 `rows_examined` 统计的是 server 层看到的扫描行数，与引擎内部真正执行的行数不是一回事：
覆盖索引、索引下推、change buffer 合并都会让两者偏离，不能拿它直接反推成本。

### Read View and MVCC

「一致性读」由 MVCC 实现：事务在需要时建立 read-view，按可见性判断决定读哪个版本，
被修改过的旧版本从 undo log 里还原出来（机制见 [Transaction](/docs/CS/DB/MySQL/Transaction.md)
与 [undolog](/docs/CS/DB/MySQL/undolog.md)）。这也是同一个 `count(*)` 在不同事务里结果可能不同的原因。

### Lock

全局锁主要用在逻辑备份过程中。对于全部是 InnoDB 引擎的库，建议你选择使用 `--single-transaction` 参数，对应用会更友好。

表锁一般是在数据库引擎不支持行锁的时候才会被用到的。如果你发现你的应用程序里有 lock tables 这样的语句，你需要追查一下，比较可能的情况是：

- 要么是你的系统现在还在用 MyISAM 这类不支持事务的引擎，那要安排升级换引擎
- 要么是你的引擎升级了，但是代码还没升级。我见过这样的情况，最后业务开发就是把 lock tables 和 unlock tables 改成 begin 和 commit，问题就解决了。

MDL 会直到事务提交才释放，在做表结构变更的时候，你一定要小心不要导致锁住线上查询和更新。

### Deadlock

两种避免锁等待堆积的策略，默认值分别是：

1. `innodb_lock_wait_timeout` 默认 50 秒，超时只回滚当前这条语句而不是整个事务
2. `innodb_deadlock_detect` 默认为 on，主动检测死锁并回滚代价最小的那个事务

正常情况下我们还是要采用第二种策略，即：主动死锁检测，而且 `innodb_deadlock_detect` 的默认值本身就是 on。主动死锁检测在发生死锁的时候，是能够快速发现并进行处理的，但是它也是有额外负担的。

你可以想象一下这个过程：每当一个事务被锁的时候，就要看看它所依赖的线程有没有被别人锁住，如此循环，最后判断是否出现了循环等待，也就是死锁。这套「沿等待关系找环」的思路在 9.7 仍然成立，实现细节已换成 CATS 调度加快照式死锁检测，见 [lock](/docs/CS/DB/MySQL/lock.md)。

那如果是我们上面说到的所有事务都要更新同一行的场景呢？

每个新来的被堵住的线程，都要判断会不会由于自己的加入导致了死锁，这是一个时间复杂度是 O(n) 的操作。假设有 1000 个并发线程要同时更新同一行，那么死锁检测操作就是 100 万这个量级的。虽然最终检测的结果是没有死锁，但是这期间要消耗大量的 CPU 资源。因此，你就会看到 CPU 利用率很高，但是每秒却执行不了几个事务。

**怎么解决由这种热点行更新导致的性能问题呢？**

1. 头痛医头的方法：如果你能确保这个业务一定不会出现死锁，可以临时把死锁检测关掉
2. 在中间件或服务端做限流（limiter），把打到同一行的并发压到检测成本可接受的规模
3. 拆热点：把一行改成多行（分段库存），更新时随机落到某一段，读的时候再汇总

### Auto-Increment Overflow

自增 ID 到达上限后不会回到 0 重新分配，而是在最大值上反复撞主键。`INT UNSIGNED` 的上限是 4294967295，
建表时要按预估写入量选类型（详见 [Type](/docs/CS/DB/MySQL/Type.md) 的整型小节）。


## count

### count(*)

MyISAM 把总行数记在表元数据里，所以不带 WHERE 的 `count(*)` 可以直接返回；InnoDB 不行——
并发事务各自「看到」的行数不同，官方口径是 `SELECT COUNT(*)` **只统计当前事务可见的行**，
这也是它必须连着 read-view / MVCC 一起理解的原因。

InnoDB 处理 `count(*)` 的方式是**遍历最小的那棵可用二级索引**，没有二级索引时才退化成扫聚簇索引。
针对「不带 WHERE、GROUP BY 等额外子句的全表行数统计」的性能改进出现在 **MySQL 8.0.13**（WL #10398），
9.7 手册仍按同一口径描述这条行为。显式用 `FORCE INDEX` 之类的提示可以覆盖索引选择。

`InnoDB` handles `SELECT COUNT(*)` and `SELECT COUNT(1)` operations in the same way. There is no performance difference.
即 `count(1)` 与 `count(*)` 没有性能差别，但推荐写 `count(*)`：它明确表示「数行」，与取哪一列无关、与 NULL 无关。

### count(column)

`count(column)` 与前两者不同：它要**取列值**，因此无法走「最小索引」这条优化路径；
并且**不统计该列为 NULL 的行**，所以 `count(column)` 小于等于 `count(*)`。


## NULL

NULL 不是 0，也不是空串，它表示「未知」。任何与 NULL 的算术或比较运算结果都是 NULL（既不是真也不是假），
因此这几处最容易出错：

- `SUM(column)` 在全为 NULL 或零行时返回 NULL 而不是 0，接口层要兜住：`IFNULL(SUM(column), 0)` 或 `COALESCE(...)`。
- `count(column)` 不统计该列为 NULL 的行，要总行数就写 `count(*)`。
- 判空只能用 `IS NULL` / `IS NOT NULL`，写成 `column = NULL` 永远不成立。
- `NOT IN` 子查询里只要有一个 NULL，整个条件就不成立（结果为 UNKNOWN），外层查询会返回空集；
  这也是 `NOT IN` 常不如 `NOT EXISTS` 可靠的原因。
- `DISTINCT`、`GROUP BY` 与索引都把 NULL 当成一个可区分的值处理，多个 NULL 在 `UNIQUE` 索引里不互相冲突。

## Limit

If you need only a specified number of rows from a result set, use a LIMIT clause in the query, rather than fetching the whole result set and throwing away the extra data.

MySQL sometimes optimizes a query that has a LIMIT row_count clause and no HAVING clause:

- If you select only a few rows with LIMIT, MySQL uses indexes in some cases when normally it would prefer to do a full table scan.
- If you combine LIMIT row_count with ORDER BY, MySQL stops sorting as soon as it has found the first row_count rows of the sorted result, rather than sorting the entire result. 
  If ordering is done by using an index, this is very fast. 
  If a filesort must be done, all rows that match the query without the LIMIT clause are selected, and most or all of them are sorted, before the first row_count are found. 
  After the initial rows have been found, MySQL does not sort any remainder of the result set.
  One manifestation of this behavior is that an ORDER BY query with and without LIMIT may return rows in different order, as described later in this section.
- If you combine LIMIT row_count with DISTINCT, MySQL stops as soon as it finds row_count unique rows.
- In some cases, a GROUP BY can be resolved by reading the index in order (or doing a sort on the index), then calculating summaries until the index value changes. In this case, LIMIT row_count does not calculate any unnecessary GROUP BY values.
- As soon as MySQL has sent the required number of rows to the client, it aborts the query unless you are using SQL_CALC_FOUND_ROWS. 
  In that case, the number of rows can be retrieved with SELECT FOUND_ROWS().

  ⚠️ `SQL_CALC_FOUND_ROWS` 与 `FOUND_ROWS()` 自 MySQL 8.0.17 起废弃，9.7 仍能解析但已预告移除。
  手册给的替代方案是两步查询：先按 `LIMIT` 取本页，再用同样的 WHERE 条件、不带 `LIMIT` 的
  `SELECT COUNT(*)` 求总数。

```mysql
-- 已废弃的写法
SELECT SQL_CALC_FOUND_ROWS * FROM t WHERE id > 100 LIMIT 10;
SELECT FOUND_ROWS();

-- 手册推荐的等价写法
SELECT * FROM t WHERE id > 100 LIMIT 10;
SELECT COUNT(*) FROM t WHERE id > 100;
```

- LIMIT 0 quickly returns an empty set. This can be useful for checking the validity of a query.
  It can also be employed to obtain the types of the result columns within applications that use a MySQL API that makes result set metadata available. 
  With the mysql client program, you can use the —column-type-info option to display result column types.
- If the server uses temporary tables to resolve a query, it uses the LIMIT row_count clause to calculate how much space is required.
- If an index is not used for ORDER BY but a LIMIT clause is also present, the optimizer may be able to avoid using a merge file and sort the rows in memory using an in-memory filesort operation.

If multiple rows have identical values in the ORDER BY columns, the server is free to return those rows in any order, and may do so differently depending on the overall execution plan. 
In other words, the sort order of those rows is nondeterministic with respect to the nonordered columns.
**One factor that affects the execution plan is LIMIT, so an ORDER BY query with and without LIMIT may return rows in different orders.**

If it is important to ensure the same row order with and without LIMIT, include additional columns in the ORDER BY clause to make the order deterministic.
For a query with an ORDER BY or GROUP BY and a LIMIT clause, the optimizer tries to choose an ordered index by default when it appears doing so would speed up query execution.
Prior to MySQL 8.0.21, there was no way to override this behavior, even in cases where using some other optimization might be faster. 
Beginning with MySQL 8.0.21, it is possible to turn off this optimization by setting the optimizer_switch system variable's prefer_ordering_index flag to off.


## Tuning

### Explain

`EXPLAIN` 查看执行计划；新版本另有 `EXPLAIN ANALYZE`，会真的执行语句并输出实际耗时与实际行数，
和这里的估算值对照着看才能判断统计信息是否失真。

- `id`：表的执行顺序，id 越大越早被执行
- `select_type`：查询类型，如普通查询 `SIMPLE`、衍生表查询 `DERIVED`、子查询等
- `type`：访问类型，主要有七种，`system` > `const` > `eq_ref` > `ref` > `range` > `index` > `ALL`
  - `system`：表只有一行记录，相当于系统表
  - `const`：通过索引一次就找到了需要的数据
  - `eq_ref`：唯一性索引扫描，对于每个索引键，表中只有一条记录与之匹配。常见于主键索引或唯一索引
  - `ref`：非唯一性索引扫描，对于每个索引值，可能会找到多个符合条件的行
  - `range`：索引范围扫描，一般是 WHERE 中出现 `BETWEEN`、`<`、`>`、`IN` 等范围条件
  - `index`：全索引扫描，需要遍历整棵索引树
  - `ALL`：全表扫描，需要遍历全表以找到匹配的行
- `possible_keys`、`key`、`key_len`、`ref`：可能用到的索引、实际用到的索引、用到多长的索引前缀、用哪些值做索引查找
- `rows`：优化器估算的扫描行数（估算值，来自统计信息与代价模型，不是实际执行行数）
- `Extra`：
  - `Using where`：在 server 层基于 WHERE 条件对结果再过滤
  - `Using index`：使用了覆盖索引，索引里已有所需全部列，无需回表
  - `Using index condition`：索引下推，遍历索引时就用索引列做条件判断，减少回表次数
  - `Using temporary`：需要临时表保存中间结果，常见于无法用索引完成的 GROUP BY / DISTINCT
  - `Using filesort`：无法靠索引顺序完成排序，需要额外排序（可能落盘）
  - `Using join buffer`：被驱动表连接列无可用索引，退化成扫描加缓冲，代价最高

排查与优化建议：

- 条件字段是否存在合适的索引
  - 如果没有，根据具体业务分析如何更好地建立索引
- 唯一索引 Vs 普通索引
  - 对于写多读少的业务，比如账单类、日志类系统，普通索引可以把每次更新先记在 change buffer 中，
    等真正的读需求到来时，才把对应数据页从磁盘读到内存并按 change buffer 里的记录修改，
    这大大减少了随机 IO（change buffer 本身仍受 merge 条件与缓冲池水位约束）
  - 在使用机械硬盘这种 IO 性能较差的设备时，基于 change buffer 的普通索引带来的改进可能很明显
- 联合索引的字段顺序
  - 调整顺序是否能少维护一个索引？如果可以，就按这个顺序来；把查找频繁且区分度高的列靠左
  - 如果联合查询与各列独立查询都存在，考虑 `(name, age)` 联合索引 + `(age)` 单列索引，
    而不是把 `(name)` 也单独建一遍
- 索引是否失效
  - 不符合最左匹配原则：`KEY idx (id, price, age)` 存在时，`WHERE age > 5` 仍走全表扫描
  - 范围查询之后的列用不上联合索引：`BETWEEN`、`>`、`<` 右侧的索引列不再参与缩小范围
  - 对索引列做函数运算会导致失效，显式与隐式都算
  - 隐式字符类型转换、隐式字符编码转换同理，转换发生在索引列那一侧时索引就用不上了

```mysql
-- 联合索引 (id, price, age)：只给 age 条件，用不到索引（不满足最左匹配）
SELECT * FROM t1 WHERE age > 5;

-- 范围条件之后的索引列不再参与缩小范围：这里只用到 id、price
SELECT * FROM t1 WHERE id = 1 AND price BETWEEN 10 AND 20 AND age = 30;

-- 显式函数运算：索引列被包了一层函数
SELECT * FROM t1 WHERE YEAR(create_time) = 2022;

-- 隐式类型转换：age 是 int，比较右侧写成字符串
SELECT * FROM t1 WHERE age > '30';
```
- 减少表扫描次数
  - 只查询需要的列，尽量缩小结果集，避免 `SELECT *`
  - 避免子查询，能改写成 JOIN 就改写；必须保留时优先 `EXISTS`
- 避免多表关联查询
  - 非索引关联列的查询优化能力有限，CPU 占用高；分库分表后关联语句必须重构
  - 必须多表关联时，确保关联字段有索引，并选对 join 类型
    - `LEFT JOIN`：返回左表全部记录，右表按 ON 条件匹配，匹配不上补 NULL
    - `RIGHT JOIN`：与 `LEFT JOIN` 反向
    - `INNER JOIN` / `JOIN`：只返回两表关联字段相等的行
    - `CROSS JOIN`：笛卡尔积，行数是两表行数相乘
    - MySQL 不支持 `FULL OUTER JOIN` 关键字，需要 `LEFT JOIN UNION RIGHT JOIN` 拼出等价结果
- 避免数据库大表
  - 大表的查询与修改同时消耗 IO 和 CPU，且 DDL 窗口难以安排
  - 对策一是分库分表；对策二是及时清理表空洞
    - `DELETE` 是逻辑删除，行被标记为可复用，空间要等后续插入复用，数据页因此可能很分散
    - 空间利用率低时推荐 `ALTER TABLE A ENGINE=InnoDB` 重建表来回收空洞
    - Online DDL 让重建过程中仍允许增删改；过程可拆成四步：扫描原表数据页写入临时文件 →
      期间的并发修改记入 row log → 临时文件生成后把 row log 回放上去 → 用新文件替换旧表数据
- 避免大事务
  - 大事务会长时间持有 undo 与锁，拉长 purge 落后与主从延迟，回滚代价也随时长线性增长

## Links

- [MySQL](/docs/CS/DB/MySQL/MySQL.md)
- [InnoDB](/docs/CS/DB/MySQL/InnoDB.md)
- [Index](/docs/CS/DB/MySQL/Index.md)
- [B-Tree](/docs/CS/DB/MySQL/B-Tree.md)
- [Optimizer](/docs/CS/DB/MySQL/Optimizer.md)
- [Experiences](/docs/CS/DB/MySQL/Experiences.md)

## References

1. [Aggregate Function Descriptions](https://dev.mysql.com/doc/refman/9.7/en/aggregate-functions.html)
2. [LIMIT Query Optimization](https://dev.mysql.com/doc/refman/9.7/en/limit-optimization.html)
3. [EXPLAIN Output Format](https://dev.mysql.com/doc/refman/9.7/en/explain-output.html)
4. [Optimizing InnoDB DDL Operations](https://dev.mysql.com/doc/refman/9.7/en/innodb-online-ddl-performance.html)
5. [Using Optimizer Hints](https://dev.mysql.com/doc/refman/9.7/en/optimizer-hints.html)
6. [Null Values in MySQL](https://dev.mysql.com/doc/refman/9.7/en/null-values.html)
7. [InnoDB Deadlock Detection](https://dev.mysql.com/doc/refman/9.7/en/innodb-deadlock-detection.html)
