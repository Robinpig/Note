## How a SQL execute



connector

Cache

Analysis

Improver

Executor 

Engine



wait_timeout 8h

mysql_reset_connection



query_cache_type DEMAND



rows_examined not same as engine execute rows








read-view

MVCC



lock

全局锁主要用在逻辑备份过程中。对于全部是 InnoDB 引擎的库，建议你选择使用–single-transaction 参数，对应用会更友好。

表锁一般是在数据库引擎不支持行锁的时候才会被用到的。如果你发现你的应用程序里有 lock tables 这样的语句，你需要追查一下，比较可能的情况是：

- 要么是你的系统现在还在用 MyISAM 这类不支持事务的引擎，那要安排升级换引擎
- 要么是你的引擎升级了，但是代码还没升级。我见过这样的情况，最后业务开发就是把 lock tables 和 unlock tables 改成 begin 和 commit，问题就解决了。

MDL 会直到事务提交才释放，在做表结构变更的时候，你一定要小心不要导致锁住线上查询和更新。



Dead lock



1. innodb_lock_wait_timeout default 50s
2. nnodb_deadlock_detect = on

正常情况下我们还是要采用第二种策略，即：主动死锁检测，而且 innodb_deadlock_detect 的默认值本身就是 on。主动死锁检测在发生死锁的时候，是能够快速发现并进行处理的，但是它也是有额外负担的。

你可以想象一下这个过程：每当一个事务被锁的时候，就要看看它所依赖的线程有没有被别人锁住，如此循环，最后判断是否出现了循环等待，也就是死锁。

那如果是我们上面说到的所有事务都要更新同一行的场景呢？

每个新来的被堵住的线程，都要判断会不会由于自己的加入导致了死锁，这是一个时间复杂度是 O(n) 的操作。假设有 1000 个并发线程要同时更新同一行，那么死锁检测操作就是 100 万这个量级的。虽然最终检测的结果是没有死锁，但是这期间要消耗大量的 CPU 资源。因此，你就会看到 CPU 利用率很高，但是每秒却执行不了几个事务。

**怎么解决由这种热点行更新导致的性能问题呢？**

1. 一种头痛医头的方法，就是如果你能确保这个业务一定不会出现死锁，可以临时把死锁检测关掉。
2. limiter
3. 分段锁, multiple rows



自增ID用完后会溢出回到0, 主键重复



## count

### count(*) 

MyISAM have a cache of all rows

InnoDB 

from MySQL 8.0.13, count(*) all rows 

choose a least index





`InnoDB` handles `SELECT COUNT(*)` and `SELECT COUNT(1)` operations in the same way. There is no performance difference.

Like count(*), but suggest `count(*)`




 count(column)




### limit

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
- LIMIT 0 quickly returns an empty set. This can be useful for checking the validity of a query.
  It can also be employed to obtain the types of the result columns within applications that use a MySQL API that makes result set metadata available. 
  With the mysql client program, you can use the —column-type-info option to display result column types.
- If the server uses temporary tables to resolve a query, it uses the LIMIT row_count clause to calculate how much space is required.
- If an index is not used for ORDER BY but a LIMIT clause is also present, the optimizer may be able to avoid using a merge file and sort the rows in memory using an in-memory filesort operation.

If multiple rows have identical values in the ORDER BY columns, the server is free to return those rows in any order, and may do so differently depending on the overall execution plan. In other words, the sort order of those rows is nondeterministic with respect to the nonordered columns.

One factor that affects the execution plan is LIMIT, so an ORDER BY query with and without LIMIT may return rows in different orders.


If it is important to ensure the same row order with and without LIMIT, include additional columns in the ORDER BY clause to make the order deterministic.

For a query with an ORDER BY or GROUP BY and a LIMIT clause, the optimizer tries to choose an ordered index by default when it appears doing so would speed up query execution. Prior to MySQL 8.0.21, there was no way to override this behavior, even in cases where using some other optimization might be faster. Beginning with MySQL 8.0.21, it is possible to turn off this optimization by setting the optimizer_switch system variable's prefer_ordering_index flag to off.


## Reference

1. [MySQL 8.0 Reference Manual - Aggregate Function Descriptions](https://dev.mysql.com/doc/refman/8.0/en/aggregate-functions.html)
2. [LIMIT Query Optimization](https://dev.mysql.com/doc/refman/8.0/en/limit-optimization.html)