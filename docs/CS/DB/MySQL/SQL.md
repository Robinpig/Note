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


## NULL 


- sum IFNULL(SUM(column), 0)
- count(column) not contain NULL row, please use count(*)
- IS NULL or IS NOT NULL in where clause

 



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

If multiple rows have identical values in the ORDER BY columns, the server is free to return those rows in any order, and may do so differently depending on the overall execution plan. 
In other words, the sort order of those rows is nondeterministic with respect to the nonordered columns.
**One factor that affects the execution plan is LIMIT, so an ORDER BY query with and without LIMIT may return rows in different orders.**

If it is important to ensure the same row order with and without LIMIT, include additional columns in the ORDER BY clause to make the order deterministic.
For a query with an ORDER BY or GROUP BY and a LIMIT clause, the optimizer tries to choose an ordered index by default when it appears doing so would speed up query execution.
Prior to MySQL 8.0.21, there was no way to override this behavior, even in cases where using some other optimization might be faster. 
Beginning with MySQL 8.0.21, it is possible to turn off this optimization by setting the optimizer_switch system variable's prefer_ordering_index flag to off.


## Tuning

Explain sql 查看执行计划
- id：表的执行顺序，id越大，越早被执行
- select_type：查询类型，如普通查询simple、衍生表查询DERIVED、子查询等
- type：访问类型，主要有七种，system>const>eq_ref>ref>range>index>ALL
- system：表只有一行记录，相当于系统表
- const：通过索引一次就找到了需要的数据
- eq_ref：唯一性索引扫描，对于每个索引键，表中只有一条记录与之匹配。常见于主键索引或唯一索引
- ref：非唯一性索引扫描，对于每个索引值，可能会找到多个符合条件的行（比如wmpoiId）
- range：索引范围扫描，一般是在where语句中出现了between、<、>、in等的索引范围查询
- index：全索引扫描，需要遍历索引树
- all：全表扫描，需要遍历全表以找到匹配的行
- possible_keys、keys、key_len、ref：可能会用到的索引、实际用到的索引、用到的索引的长度、使用哪些值进行索引查询
- rows：执行该SQL命令扫描的行数
- Extra
- Using where：在MySQL server层 基于where条件对结果进行了过滤
- Using index：使用了覆盖索引，索引树已包含所有需要的数据，无需回表查询
- Using index condition：使用了索引下推，在索引遍历过程中，innodb层 就对索引包含的字段进行条件判断，减少回表次数（没有索引下推的话，先回表扫描拿到完整行记录后，再进行条件判断）
- Using temporary：使用了临时表保存中间结果。MySQL在对查询结果进行排序，且数据量较大时便会使用临时表
- Using filesort：MySQL需要对结果集进行排序操作，但无法使用索引排序（比如查询中包含了表达式、函数、JOIN等操作），MySQL会将结果集写入磁盘临时文件，然后进行排序操作。
- Using join buffer：使用了连接缓存，当两张表做关联查询时，被驱动表上无索引可用，便会出现using join buffer


排查与优化建议：
- 条件字段是否存在合适的索引
-  如果没有，根据具体业务分析如何更好地建立索引
- 唯一索引 Vs 普通索引
- 对于写多读少的业务，比如账单类、日志类系统，普通索引可以将每次更新先记录在change buffer中，等真正『读需求』带来时才会将对应的数据页从磁盘读取到内存中，再根据change buffer中该数据页的修改记录进行修改。这大大减少了磁盘的随机访问，数据库性能也随之提示
- 在使用机械硬盘这种IO性能较差的设备时，基于change buffer机制的普通索引带来的性能改进可能是显著的。
-  联合索引的字段顺序
- 调整顺序是否少维护一个索引？如果可以，按这个顺序来。将查找频繁的数据靠左创建索引
- 如果既要有联合查询，也要有各自的查询，比如(name，age)，从空间角度来看，name字段大于age字段，因此建立(name，age)联合索引和(age)单独的索引
- 索引是否失效
- 联合索引，不符合最左匹配原则：select * from test1 where age > 5 在存在  KEY 'index_price_age' ('id', 'price', 'age') 的背景下走了全表扫描
联合索引，存在范围查询，范围查询后的字段无法再使用联合索引
- <、>会使索引失效，但>=、<=、between and、like 、in并不会。in和or同时使用可能会失效

- 对索引字段进行了函数操作，会导致索引失效
- 显式函数操作： SELECT * FROM test1 WHERE YEAR(create_time) = 2022;
- 隐式字符类型转换：SELECT * FROM test1 WHERE age > '30' AND price > 100;（test1表中，age是int类型）
- 隐式字符编码转换：上面的查询，price列使用utf8b4数据集，age列使用utf8数据集  -->utf8b4
- 减少表扫描次数
- 只查询需要的列，并尽量缩小查询的结果集，避免select *
- 避免使用子查询
- 子查询通常会导致查询执行速度变慢。如果必须使用子查询，请使用 EXISTS 或 IN 等优化的子查询。
- 避免多表关联查询
- SQL查询中非索引关联查询优化比较差，占CPU较高
- 分库分表后关联查询语句需要重构
- 分解复杂的关联查询
如果必须多表关联查询，必须确保关联字段存在索引，并选择合适的join类型
- left join : 左连接，返回左表中所有的记录以及右表中符合on条件的记录
- right join : 右连接，返回右表中所有的记录以及左表中连接字段相等的记录
- inner join/join : 内连接，又叫等值连接，只返回两个表中连接字段相等的行记录
- full join : 外连接，返回两个表中的行：left join + right join
- cross join : 结果是笛卡尔积，第一个表的行数乘以第二个表的行数
- 避免数据库大表
问题：大表查询和修改，非常耗费IO和CPU资源
- 
解决方案：
i.
分库分表
ii.
及时清理表空洞
- delete删除数据时，其实是逻辑删除，这些数据被标记为“可复用”，下次插入数据时直接复用这部分空间。
- 数据页可能比较分散，利用率不高，同时占有大量磁盘空间，因此推荐alter table A engine=InnoDB 重建表，清理表空洞

- MySQL 5.6 版本开始引入Online DDL，alter table A engine=InnoDB重建表的过程中，允许对表A进行增删改操作
- （1）扫描表A 的所有数据页，存储到一个临时文件中；（2）拷贝数据到临时文件的过程中，将所有对表A的操作记录在一个日志文件(row log)中；（3）临时文件生成后，将日志文件中操作 应用到临时文件，得到一个逻辑数据上与表A相同的数据文件（4）用临时文件替换表A的数据

（7）避免大事务

## Reference

1. [MySQL 8.0 Reference Manual - Aggregate Function Descriptions](https://dev.mysql.com/doc/refman/8.0/en/aggregate-functions.html)
2. [LIMIT Query Optimization](https://dev.mysql.com/doc/refman/8.0/en/limit-optimization.html)