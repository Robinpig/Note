## Introduction

Optimization involves configuring, tuning, and measuring performance, at several levels.
Depending on your job role (developer, DBA, or a combination of both), you might optimize at the level of individual SQL statements, entire applications,
a single database server, or multiple networked database servers.
Sometimes you can be proactive and plan in advance for performance, while other times you might troubleshoot a configuration or code issue after a problem occurs.
Optimizing CPU and memory usage can also improve scalability, allowing the database to handle more load without slowing down.

## Optimizing SQL Statements

### Optimizing SELECT Statements

The most basic reason a query doesn’t perform well is because it’s working with too much data.
Some queries just have to sift through a lot of data, which can’t be helped.
That’s unusual, though; most bad queries can be changed to access less data. We’ve found it useful to analyze a poorly performing query in two steps:

1. Find out whether your application is retrieving more data than you need. That usually means it’s accessing too many rows, but it might also be accessing too many columns.
2. Find out whether the MySQL server is analyzing more rows than it needs.

The optimizer might not always choose the best plan, for many reasons:

- The statistics could be inaccurate. The server relies on storage engines to provide statistics, and they can range from exactly correct to wildly inaccurate.
  For example, the InnoDB storage engine doesn’t maintain accurate statistics about the number of rows in a table because of its MVCC architecture.
- The cost metric is not exactly equivalent to the true cost of running the query, so even when the statistics are accurate, the query might be more or less expensive than MySQL’s approximation.
  A plan that reads more pages might actually be cheaper in some cases, such as when the reads are sequential so the disk I/O is faster or when the pages are already cached in memory.
  MySQL also doesn’t understand which pages are in memory and which pages are on disk, so it doesn’t really know how much I/O the query will cause.
- MySQL’s idea of “optimal” might not match yours.
  You probably want the fastest execution time, but MySQL doesn’t really try to make queries fast; it tries to minimize their cost, and as we’ve seen, determining cost is not an exact science.
- MySQL doesn’t consider other queries that are running concurrently, which can affect how quickly the query runs.
- MySQL doesn’t always do cost-based optimization. Sometimes it just follows the rules, such as “if there’s a full-text MATCH() clause, use a FULLTEXT index if one exists.”
  It will do this even when it would be faster to use a different index and a non-FULLTEXT query with a WHERE clause.
- The optimizer doesn’t take into account the cost of operations not under its con‐ trol, such as executing stored functions or user-defined functions.
- As we’ll see later, the optimizer can’t always estimate every possible execution plan, so it might miss an optimal plan.

```sql
SHOW VARIABLES LIKE 'optimizer_switch';


index_merge=on,index_merge_union=on,index_merge_sort_union=on,index_merge_intersection=on,
index_merge_sort_intersection=off,engine_condition_pushdown=off,
index_condition_pushdown=on,derived_merge=on,derived_with_keys=on,firstmatch=on,loosescan=on,materialization=on,in_to_exists=on,semijoin=on,
partial_match_rowid_merge=on,partial_match_table_scan=on,subquery_cache=on,mrr=off,mrr_cost_based=off,mrr_sort_keys=off,outer_join_with_cache=on,
semijoin_with_cache=on,join_cache_incremental=on,join_cache_hashed=on,join_cache_bka=on,optimize_join_buffer_size=off,
table_elimination=on,extended_keys=on,exists_to_in=on,orderby_uses_equalities=on,condition_pushdown_for_derived=on,split_materialized=on
```

#### Index Condition Pushdown Optimization

**Index Condition Pushdown (ICP) is an optimization for the case where MySQL retrieves rows from a table using an index.**
Index Condition Pushdown is enabled by default.
It can be controlled with the `optimizer_switch` system variable by setting the `index_condition_pushdown` flag:

```sql
SET optimizer_switch = 'index_condition_pushdown=off';
SET optimizer_switch = 'index_condition_pushdown=on';
```

[`EXPLAIN`](https://dev.mysql.com/doc/refman/8.0/en/explain.html) output shows `Using index condition` in the `Extra` column when Index Condition Pushdown is used. It does not show `Using index` because that does not apply when full table rows must be read.

Applicability of the Index Condition Pushdown optimization is subject to these conditions:

- ICP is used for the `range`, `ref`, `eq_ref`, and `ref_or_null` access methods when there is a need to access full table rows.
- ICP can be used for `InnoDB` and `MyISAM` tables, including partitioned `InnoDB` and `MyISAM` tables.
- For `InnoDB` tables, ICP is used **only for secondary indexes**. The goal of ICP is to reduce the number of full-row reads and thereby reduce I/O operations. For `InnoDB` clustered indexes, the complete record is already read into the `InnoDB` buffer. Using ICP in this case does not reduce I/O.
- ICP is **not supported with secondary indexes created on virtual generated columns**. `InnoDB` supports secondary indexes on virtual generated columns.
- Conditions that refer to subqueries cannot be pushed down.
- Conditions that refer to stored functions cannot be pushed down. Storage engines cannot invoke stored functions.
- Triggered conditions cannot be pushed down.

To understand how this optimization works, first consider how an index scan proceeds when Index Condition Pushdown is not used:

1. Get the next row, first by reading the index tuple, and then by using the index tuple to locate and read the full table row.
2. Test the part of the `WHERE` condition that applies to this table. Accept or reject the row based on the test result.

Using Index Condition Pushdown, the scan proceeds like this instead:

1. Get the next row's index tuple (but not the full table row).
2. Test the part of the `WHERE` condition that applies to this table and can be checked using only index columns. If the condition is not satisfied, proceed to the index tuple for the next row.
3. If the condition is satisfied, use the index tuple to locate and read the full table row.
4. Test the remaining part of the `WHERE` condition that applies to this table. Accept or reject the row based on the test result.

#### Multi-Range Read Optimization

Reading rows using a range scan on a secondary index can result in many random disk accesses to the base table when the table is large and not stored in the storage engine's cache. With the Disk-Sweep Multi-Range Read (**MRR**) optimization, MySQL tries to reduce the number of random disk access for range scans by first scanning the index only and collecting the keys for the relevant rows. Then the keys are sorted and finally the rows are retrieved from the base table using the order of the primary key. The motivation for Disk-sweep MRR is to reduce the number of random disk accesses and instead achieve a more sequential scan of the base table data.

The Multi-Range Read optimization provides these benefits:

- MRR enables data rows to be accessed sequentially rather than in random order, based on index tuples.
  The server obtains a set of index tuples that satisfy the query conditions, sorts them according to data row ID order, and uses the sorted tuples to retrieve data rows in order. This makes data access more efficient and less expensive.
- MRR enables batch processing of requests for key access for operations that require access to data rows through index tuples, such as range index scans and equi-joins that use an index for the join attribute. MRR iterates over a sequence of index ranges to obtain qualifying index tuples. As these results accumulate, they are used to access the corresponding data rows. It is not necessary to acquire all index tuples before starting to read data rows.

When MRR is used, the `Extra` column in [`EXPLAIN`](https://dev.mysql.com/doc/refman/8.0/en/explain.html) output shows Using `MRR`.

`InnoDB` and `MyISAM` do not use MRR if full table rows need not be accessed to produce the query result.
This is the case if results can be produced entirely on the basis on information in the index tuples (through a `covering index`); MRR provides no benefit.

Two `optimizer_switch` system variable flags provide an interface to the use of MRR optimization.
The `mrr` flag controls whether MRR is enabled.
If `mrr` is enabled (`on`), the `mrr_cost_based` flag controls whether the optimizer attempts to make a cost-based choice between using and not using MRR (`on`) or uses MRR whenever possible (`off`).
By default, `mrr` is `on` and `mrr_cost_based` is `on`.

For MRR, a storage engine uses the value of the `read_rnd_buffer_size` system variable as a guideline for how much memory it can allocate for its buffer.
The engine uses up to `read_rnd_buffer_size` bytes and determines the number of ranges to process in a single pass.

#### Batched Key Access Joins

BKA can be applied when there is an index access to the table produced by the second join operand.

For BKA to be used, the `batched_key_access` flag of the `optimizer_switch` system variable must be set to on. BKA uses MRR, so the `mrr` flag must also be `on`.

```mysql
SET optimizer_trace="enabled=on";
-- select SQL;
SELECT * FROM information_schema.OPTIMIZER_TRACE;
SET optimizer_trace="enabled=off";
```

### Execution Plan

Depending on the details of your tables, columns, indexes, and the conditions in your WHERE clause,
the MySQL optimizer considers many techniques to efficiently perform the lookups involved in an SQL query.
A query on a huge table can be performed without reading all the rows; a join involving several tables can be performed without comparing every combination of rows.
The set of operations that the optimizer chooses to perform the most efficient query is called the “query execution plan”, also known as the `EXPLAIN` plan.

The EXPLAIN statement provides information about how MySQL executes statements:

- EXPLAIN works with SELECT, DELETE, INSERT, REPLACE, and UPDATE statements.
- When EXPLAIN is used with an explainable statement, MySQL displays information from the optimizer about the statement execution plan.
  That is, MySQL explains how it would process the statement, including information about how tables are joined and in which order.
- When EXPLAIN is used with FOR CONNECTION connection_id rather than an explainable statement, it displays the execution plan for the statement executing in the named connection.
- For SELECT statements, EXPLAIN produces additional execution plan information that can be displayed using SHOW WARNINGS.
- EXPLAIN is useful for examining queries involving partitioned tables.
- The FORMAT option can be used to select the output format. TRADITIONAL presents the output in tabular format.
  This is the default if no FORMAT option is present. JSON format displays the information in JSON format.

With the help of EXPLAIN, you can see where you should add indexes to tables so that the statement executes faster by using indexes to find rows.
You can also use EXPLAIN to check whether the optimizer joins the tables in an optimal order.
To give a hint to the optimizer to use a join order corresponding to the order in which the tables are named in a SELECT statement, begin the statement with SELECT STRAIGHT_JOIN rather than just SELECT.
However, STRAIGHT_JOIN may prevent indexes from being used because it disables semijoin transformations.




**EXPLAIN Output Columns**



| Column    | JSON Name       | Meaning                                        |
|-----------| --------------- | ---------------------------------------------- |
| `id`      | `select_id`     | The`SELECT` identifier                         |
| `select_type` | None            | The`SELECT` type                               |
| `table`   | `table_name`    | The table for the output row                   |
| `partitions` | `partitions`    | The matching partitions                        |
| `type`    | `access_type`   | The join type                                  |
| `possible_keys` | `possible_keys` | The possible indexes to choose                 |
| `key`     | `key`           | The index actually chosen                      |
| `key_len` | `key_length`    | The length of the chosen key                   |
| `ref`     | `ref`           | The columns compared to the index              |
| `rows`    | `rows`          | Estimate of rows to be examined                |
| `filtered` | `filtered`      | Percentage of rows filtered by table condition |
| `Extra`   | None            | Additional information                         |


Each output row from EXPLAIN provides information about one table. 
Each row contains the values summarized in “EXPLAIN Output Columns”, and described in more detail following the table.

The type of SELECT, which can be any of those shown in the following table. A JSON-formatted EXPLAIN exposes the SELECT type as a property of a query_block, unless it is SIMPLE or PRIMARY. The JSON names (where applicable) are also shown in the table.

| select_type Value |	JSON Name |	Meaning |
| --- | --- | --- |
| SIMPLE |	None |	Simple SELECT (not using UNION or subqueries) |
| PRIMARY |	None |	Outermost SELECT |
| UNION |	None |	Second or later SELECT statement in a UNION |
| DEPENDENT | UNION |	dependent (true)	Second or later SELECT statement in a UNION, dependent on outer query |
| UNION | RESULT |	union_result	Result of a UNION. |
| SUBQUERY |	None |	First SELECT in subquery |
| DEPENDENT | SUBQUERY |	dependent (true)	First SELECT in subquery, dependent on outer query |
| DERIVED |	None |	Derived table |
| DEPENDENT | DERIVED |	dependent (true)	Derived table dependent on another table |
| MATERIALIZED |	materialized_from_subquery |	Materialized subquery |
| UNCACHEABLE | SUBQUERY |	cacheable (false)	A subquery for which the result cannot be cached and must be re-evaluated for each row of the outer query |
| UNCACHEABLE | UNION |	cacheable (false)	The second or later select in a UNION that belongs to an uncacheable subquery (see UNCACHEABLE SUBQUERY) |




The type column of EXPLAIN output describes how tables are joined. In JSON-formatted output, these are found as values of the access_type property. The following list describes the join types, ordered from the best type to the worst:

system

The table has only one row (= system table). This is a special case of the const join type.

const

The table has at most one matching row, which is read at the start of the query.
eq_ref

One row is read from this table for each combination of rows from the previous tables. Other than the system and const types, this is the best possible join type.
ref

All rows with matching index values are read from this table for each combination of rows from the previous tables. ref is used if the join uses only a leftmost prefix of the key or if the key is not a PRIMARY KEY or UNIQUE index (in other words, if the join cannot select a single row based on the key value). If the key that is used matches only a few rows, this is a good join type.
fulltext

The join is performed using a FULLTEXT index.

ref_or_null

This join type is like ref, but with the addition that MySQL does an extra search for rows that contain NULL values.

range

index

all


possible_keys (JSON name: possible_keys)

The possible_keys column indicates the indexes from which MySQL can choose to find the rows in this table. Note that this column is totally independent of the order of the tables as displayed in the output from EXPLAIN. 
That means that some of the keys in possible_keys might not be usable in practice with the generated table order.
If this column is NULL (or undefined in JSON-formatted output), there are no relevant indexes. 
In this case, you may be able to improve the performance of your query by examining the WHERE clause to check whether it refers to some column or columns that would be suitable for indexing.
If so, create an appropriate index and check the query with EXPLAIN again.



key (JSON name: key)

The key column indicates the key (index) that MySQL actually decided to use. If MySQL decides to use one of the possible_keys indexes to look up rows, that index is listed as the key value.
It is possible that key may name an index that is not present in the possible_keys value.
This can happen if none of the possible_keys indexes are suitable for looking up rows, but all the columns selected by the query are columns of some other index.
That is, the named index covers the selected columns, so although it is not used to determine which rows to retrieve, an index scan is more efficient than a data row scan.
For InnoDB, a secondary index might cover the selected columns even if the query also selects the primary key because InnoDB stores the primary key value with each secondary index.
If key is NULL, MySQL found no index to use for executing the query more efficiently.
To force MySQL to use or ignore an index listed in the possible_keys column, use FORCE INDEX, USE INDEX, or IGNORE INDEX in your query.


ref (JSON name: ref)

The ref column shows which columns or constants are compared to the index named in the key column to select rows from the table.
If the value is func, the value used is the result of some function. To see which function, use SHOW WARNINGS following EXPLAIN to see the extended EXPLAIN output. 
The function might actually be an operator such as an arithmetic operator.


Extra (JSON name: none)

This column contains additional information about how MySQL resolves the query. For descriptions of the different values, see EXPLAIN Extra Information.

There is no single JSON property corresponding to the Extra column; however, values that can occur in this column are exposed as JSON properties, or as the text of the message property.


## Optimizing for InnoDB Tables

### Optimizing InnoDB Transaction Management

To optimize `InnoDB` transaction processing, find the ideal balance between the performance overhead of transactional features and the workload of your server. For example, an application might encounter performance issues if it commits thousands of times per second, and different performance issues if it commits only every 2-3 hours.

- The default MySQL setting `AUTOCOMMIT=1` can impose performance limitations on a busy database server. Where practical, wrap several related data change operations into a single transaction, by issuing `SET AUTOCOMMIT=0` or a `START TRANSACTION` statement, followed by a `COMMIT` statement after making all the changes.
  `InnoDB` must flush the log to disk at each transaction commit if that transaction made modifications to the database. When each change is followed by a commit (as with the default autocommit setting), the I/O throughput of the storage device puts a cap on the number of potential operations per second.
- Alternatively, for transactions that consist only of a single `SELECT` statement, turning on `AUTOCOMMIT` helps `InnoDB` to recognize read-only transactions and optimize them.
- Avoid performing rollbacks after inserting, updating, or deleting huge numbers of rows. If a big transaction is slowing down server performance, rolling it back can make the problem worse, potentially taking several times as long to perform as the original data change operations. Killing the database process does not help, because the rollback starts again on server startup.

  To minimize the chance of this issue occurring:

  - Increase the size of the [buffer pool](/docs/CS/DB/MySQL/memory.md?id=buffer_pool) so that all the data change changes can be cached rather than immediately written to disk.
  - Set `innodb_change_buffering=all` so that update and delete operations are buffered in addition to inserts.
  - Consider issuing `COMMIT` statements periodically during the big data change operation, possibly breaking a single delete or update into multiple statements that operate on smaller numbers of rows.

  To get rid of a runaway rollback once it occurs, increase the buffer pool so that the rollback becomes CPU-bound and runs fast, or kill the server and restart with `innodb_force_recovery=3`.

  This issue is expected to be infrequent with the default setting `innodb_change_buffering=all`, which allows update and delete operations to be cached in memory, making them faster to perform in the first place, and also faster to roll back if needed. Make sure to use this parameter setting on servers that process long-running transactions with many inserts, updates, or deletes.
- If you can afford the loss of some of the latest committed transactions if an unexpected exit occurs, you can set the `innodb_flush_log_at_trx_commit` parameter to 0. `InnoDB` tries to flush the log once per second anyway, although the flush is not guaranteed.
- When rows are modified or deleted, the rows and associated [undo logs](/docs/CS/DB/MySQL/undolog.md) are not physically removed immediately, or even immediately after the transaction commits.
  The old data is preserved until transactions that started earlier or concurrently are finished, so that those transactions can access the previous state of modified or deleted rows.
  Thus, a long-running transaction can prevent `InnoDB` from purging data that was changed by a different transaction.
- When rows are modified or deleted within a long-running transaction, other transactions using the `READ COMMITTED` and `REPEATABLE READ` isolation levels have to do more work to reconstruct the older data if they read those same rows.
- When a long-running transaction modifies a table, queries against that table from other transactions do not make use of the `covering index` technique.
  Queries that normally could retrieve all the result columns from a secondary index, instead look up the appropriate values from the table data.

  If secondary index pages are found to have a `PAGE_MAX_TRX_ID` that is too new, or if records in the secondary index are delete-marked, `InnoDB` may need to look up records using a clustered index.
