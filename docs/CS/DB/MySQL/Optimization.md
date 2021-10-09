## Optimizing SQL Statements

### Optimizing SELECT Statements

#### Index Condition Pushdown Optimization

**Index Condition Pushdown (ICP) is an optimization for the case where MySQL retrieves rows from a table using an index.** 

Index Condition Pushdown is enabled by default. It can be controlled with the [`optimizer_switch`](https://dev.mysql.com/doc/refman/8.0/en/server-system-variables.html#sysvar_optimizer_switch) system variable by setting the [`index_condition_pushdown`](https://dev.mysql.com/doc/refman/8.0/en/switchable-optimizations.html#optflag_index-condition-pushdown) flag:

```sql
SET optimizer_switch = 'index_condition_pushdown=off';
SET optimizer_switch = 'index_condition_pushdown=on';
```

[`EXPLAIN`](https://dev.mysql.com/doc/refman/8.0/en/explain.html) output shows `Using index condition` in the `Extra` column when Index Condition Pushdown is used. It does not show `Using index` because that does not apply when full table rows must be read.



Applicability of the Index Condition Pushdown optimization is subject to these conditions:

- ICP is used for the [`range`](https://dev.mysql.com/doc/refman/8.0/en/explain-output.html#jointype_range), [`ref`](https://dev.mysql.com/doc/refman/8.0/en/explain-output.html#jointype_ref), [`eq_ref`](https://dev.mysql.com/doc/refman/8.0/en/explain-output.html#jointype_eq_ref), and [`ref_or_null`](https://dev.mysql.com/doc/refman/8.0/en/explain-output.html#jointype_ref_or_null) access methods when there is a need to access full table rows.
- ICP can be used for [`InnoDB`](https://dev.mysql.com/doc/refman/8.0/en/innodb-storage-engine.html) and [`MyISAM`](https://dev.mysql.com/doc/refman/8.0/en/myisam-storage-engine.html) tables, including partitioned `InnoDB` and `MyISAM` tables.
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