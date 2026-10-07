## Introduction

MVCC（Multi-Version Concurrency Control）让 InnoDB 的读写互不阻塞：读者拿自己开始时刻的快照读旧版本，写者改新版本，
两边都不等对方。它是 `READ COMMITTED` 与 `REPEATABLE READ` 的实现基础，也解释了为什么「长事务」会从
一个语义问题变成性能与空间问题——旧版本要靠 undo log 一直留着，留得越久，回滚段越大、purge 越落后。


| 项 | 值 |
| :--- | :--- |
| 正文默认版本 | MySQL 9.7.x LTS（最新 9.7.3，2026-08-18） |
| 源码核实基线 | tag `mysql-9.7.2` |
| 次要兼容目标 | 8.4.x LTS |
| 已停止支持 | 8.0（EOL 2026-04-30）、5.7（EOL 2023-10） |
| 核实日期 | 2026-10-07 |

本页回答三件事：一个事务凭什么判定某一行哪个版本对自己可见（ReadView），这条判定在聚簇索引与二级索引上
分别怎么走（一致性读），以及什么时候必须放弃 MVCC 改用锁读（locking reads）。
事务生命周期与两阶段提交见 [Transaction](/docs/CS/DB/MySQL/Transaction.md)，
版本链的载体 undo log 与 purge 见 [Undo Log](/docs/CS/DB/MySQL/undolog.md)。

## MVCC

In Concurrency Control theory, there are two ways you can deal with conflicts:

- You can avoid them, by employing a pessimistic locking mechanism (e.g. Read/Write locks, Two-Phase Locking)
- You can allow conflicts to occur, but you need to detect them using an optimistic locking mechanism (e.g. logical clock, MVCC)

Because MVCC (Multi-Version Concurrency Control) is such a prevalent Concurrency Control technique (not only in relational database systems, in this article, I’m going to explain how it works.

When the [ACID transaction properties](/docs/CS/SE/Transaction.md?id=acid) were first defined, Serializability was assumed. And to provide a Strict Serializable transaction outcome, the [2PL (Two-Phase Locking)](https://vladmihalcea.com/2pl-two-phase-locking/) mechanism was employed. When using 2PL, every read requires a shared lock acquisition, while a write operation requires taking an exclusive lock.

- a shared lock blocks Writers, but it allows other Readers to acquire the same shared lock
- an exclusive lock blocks both Readers and Writers concurring for the same lock

However, locking incurs contention, and contention affects scalability. The [Amdhal’s Law](https://en.wikipedia.org/wiki/Amdahl's_law) or the [Universal Scalability Law](http://www.perfdynamics.com/Manifesto/USLscalability.html) demonstrate how contention can affect response Time speedup.

For this reason, database researchers have come up with a different Concurrency Control model which tries to reduce locking to a bare minimum so that:

- Readers don’t block Writers
- Writers don’t block Readers

The only use case that can still generate contention is when two concurrent transactions try to modify the same record since, once modified, a row is always locked until the transaction that modified this record either commits or rolls back.

In order to specify the aforementioned Reader/Writer non-locking behavior, the Concurrency Control mechanism must operate on multiple versions of the same record, hence this mechanism is called Multi-Version Concurrency Control (MVCC).

While 2PL is pretty much standard, there’s no standard MVCC implementation, each database taking a slightly different approach. In this article, we are going to use PostgreSQL since its MVCC implementation is the easiest one to visualize.

While Oracle and MySQL use the [undo log](/docs/CS/DB/MySQL/undolog.md) to capture uncommitted changes so that rows can be reconstructed to their previously committed version, PostgreSQL stores all row versions in the table data structure.

### InnoDB Multi-Versioning

InnoDB implements MVCC by assigning a transaction ID for each transaction that starts.
That ID is assigned the first time the transaction reads any data.
When a record is modified within that transaction, an undo record that explains how to revert that change is written to the undo log,
and the rollback pointer of the transaction is pointed at that undo log record.
This is how the transaction can find the way to roll back if needed.

When a different session reads a cluster key index record, InnoDB compares the record’s transaction ID versus the read view of that session.
If the record in its current state should not be visible (the transaction that altered it has not yet committed),
the undo log record is followed and applied until the session reaches a transaction ID that is eligible to be visible.
This process can loop all the way to an undo record that deletes this row entirely, signaling to the read view that this row does not exist.

Records in a transaction are deleted by setting a “deleted” bit in the “info flags” of the record.
This is also tracked in the undo log as a “remove delete mark.”

It is also worth noting that all undo log writes are also redo logged because the undo log writes are part of the server crash recovery process and are transactional.
The size of these redo and undo logs also plays a large part in how transactions at high concurrency perform.

The result of all this extra record keeping is that most read queries never acquire locks.
They simply read data as fast as they can, making sure to select only rows that meet the criteria.
The drawbacks are that the storage engine has to store more data with each row, do more work when examining rows, and handle some additional housekeeping operations.

MVCC works only with the REPEATABLE READ and READ COMMITTED isolation levels.
READ UNCOMMITTED isn’t MVCC compatible because queries don’t read the row version that’s appropriate for their transaction version; they read the newest version, no matter what.
SERIALIZABLE isn’t MVCC compatible because reads lock every row they return.

`InnoDB` is a multi-version storage engine.
It keeps information about old versions of changed rows to support transactional features such as concurrency and rollback.
**This information is stored in undo tablespaces in a data structure called a rollback segment.**
`InnoDB` uses the information in the rollback segment to perform the undo operations needed in a transaction rollback.
It also uses the information to build earlier versions of a row for a consistent read.

Internally, `InnoDB` adds three fields to each row stored in the database:

- A 6-byte `DB_TRX_ID` field indicates the transaction identifier for the last transaction that inserted or updated the row.
  Also, a deletion is treated internally as an update where a special bit in the row is set to mark it as deleted.
- A 7-byte `DB_ROLL_PTR` field called the roll pointer. The roll pointer points to an **undo log** record written to the rollback segment.
  If the row was updated, the undo log record contains the information necessary to rebuild the content of the row before it was updated.
- A 6-byte `DB_ROW_ID` field contains a row ID that increases monotonically as new rows are inserted.
  If `InnoDB` generates a clustered index automatically, the index contains row ID values. Otherwise, the `DB_ROW_ID` column does not appear in any index.

Undo logs in the rollback segment are divided into insert and update undo logs.
Insert undo logs are needed only in transaction rollback and can be discarded as soon as the transaction commits.
Update undo logs are used also in consistent reads, but they can be discarded only after there is no transaction present for
which `InnoDB` has assigned a snapshot that in a consistent read could require the information in the update undo log to build an earlier version of a database row.

It is recommend that you commit transactions regularly, including transactions that issue only consistent reads. Otherwise,
`InnoDB` cannot discard data from the update undo logs, and the rollback segment may grow too big, filling up the undo tablespace in which it resides.

The physical size of an undo log record in the rollback segment is typically smaller than the corresponding inserted or updated row.
You can use this information to calculate the space needed for your rollback segment.

In the `InnoDB` multi-versioning scheme, a row is not physically removed from the database immediately when you delete it with an SQL statement.
`InnoDB` only physically removes the corresponding row and its index records when it discards the update undo log record written for the deletion.
This removal operation is called a purge, and it is quite fast, usually taking the same order of time as the SQL statement that did the deletion.

If you insert and delete rows in smallish batches at about the same rate in the table,
the purge thread can start to lag behind and the table can grow bigger and bigger because of all the “dead” rows, making everything disk-bound and very slow.
In such cases, throttle new row operations, and allocate more resources to the purge thread by tuning the `innodb_max_purge_lag` system variable.

### Multi-Versioning and Secondary Indexes

`InnoDB` multiversion concurrency control (MVCC) treats secondary indexes differently than clustered indexes.
Records in a clustered index are updated in-place, and their hidden system columns point undo log entries from which earlier versions of records can be reconstructed.
Unlike clustered index records, secondary index records do not contain hidden system columns nor are they updated in-place.

When a secondary index column is updated, old secondary index records are delete-marked, new records are inserted, and delete-marked records are eventually purged.
**When a secondary index record is delete-marked or the secondary index page is updated by a newer transaction, `InnoDB` looks up the database record in the clustered index.**
In the clustered index, the record's `DB_TRX_ID` is checked, and the correct version of the record is retrieved from the undo log if the record was modified after the reading transaction was initiated.

- If a secondary index record is marked for deletion or the secondary index page is updated by a newer transaction, the [covering index](/docs/CS/DB/MySQL/Transaction.md) technique is not used.
  Instead of returning values from the index structure, `InnoDB` looks up the record in the clustered index.
- If the [index condition pushdown (ICP)](/docs/CS/DB/MySQL/Optimization.md?id=index-condition-pushdown-optimization) optimization is enabled, and parts of the `WHERE` condition can be evaluated using only fields from the index,
  the MySQL server still pushes this part of the `WHERE` condition down to the storage engine where it is evaluated using the index.
  - If no matching records are found, the clustered index lookup is avoided.
  - If matching records are found, even among delete-marked records, `InnoDB` looks up the record in the clustered index.

### Locking Reads

A `SELECT` statement that also performs a **locking** operation on an `InnoDB` table. Either `SELECT ... FOR UPDATE` or `SELECT ... LOCK IN SHARE MODE`. It has the potential to produce a **deadlock**, depending on the **isolation level** of the transaction. The opposite of a **non-locking read**. Not allowed for global tables in a **read-only transaction**.

`SELECT ... FOR SHARE` replaces `SELECT ... LOCK IN SHARE MODE` in MySQL 8.0.1, but `LOCK IN SHARE MODE` remains available for backward compatibility.

### Consistent Reads

A `consistent read` means that `InnoDB` uses multi-versioning to present to a query a snapshot of the database at a point in time. The query sees the changes made by transactions that committed before that point in time, and no changes made by later or uncommitted transactions. The exception to this rule is that the query sees the changes made by earlier statements within the same transaction. This exception causes the following anomaly:
If you update some rows in a table, a `SELECT` sees the latest version of the updated rows, but it might also see older versions of any rows. If other sessions simultaneously update the same table, the anomaly means that you might see the table in a state that never existed in the database.

- If the transaction isolation level is `REPEATABLE READ` (the default level), all consistent reads within the same transaction read the snapshot established by the first such read in that transaction. You can get a fresher snapshot for your queries by committing the current transaction and after that issuing new queries.
- With `READ COMMITTED` isolation level, each consistent read within a transaction sets and reads its own fresh snapshot.

Consistent read is the default mode in which `InnoDB` processes `SELECT` statements in `READ COMMITTED` and `REPEATABLE READ` isolation levels. A consistent read does not set any locks on the tables it accesses, and therefore other sessions are free to modify those tables at the same time a consistent read is being performed on the table.

Suppose that you are running in the default `REPEATABLE READ` isolation level. When you issue a consistent read (that is, an ordinary `SELECT` statement), `InnoDB` gives your transaction a timepoint according to which your query sees the database. **If another transaction deletes a row and commits after your timepoint was assigned, you do not see the row as having been deleted. Inserts and updates are treated similarly.**

**The snapshot of the database state applies to `SELECT` statements within a transaction, not necessarily to `DML` statements`**.

If you insert or modify some rows and then commit that transaction, a `DELETE`or `UPDATE`statement issued from another concurrent `REPEATABLE READ` transaction **could affect those just-committed rows, even though the session could not query them**. If a transaction does update or delete rows committed by a different transaction, those changes do become visible to the current transaction.



RR 为何不能解决 Photom Read?

在其它事务中新增的record, 若本次事务中有其它事务更新, 则会重新生成快照读 形成幻读



#### ReadView

`mysqldump` use `START TRANSACTION WITH CONSISTENT SNAPSHOT` get a read view

row_search_mvcc -> lock_clust_rec_cons_read_sees

call changes_visible

```c

/** Checks that a record is seen in a consistent read.
 @return true if sees, or false if an earlier version of the record
 should be retrieved */
bool lock_clust_rec_cons_read_sees(
    const rec_t *rec,     /*!< in: user record which should be read or
                          passed over by a read cursor */
    dict_index_t *index,  /*!< in: clustered index */
    const ulint *offsets, /*!< in: rec_get_offsets(rec, index) */
    ReadView *view)       /*!< in: consistent read view */
{
  ut_ad(index->is_clustered());
  ut_ad(page_rec_is_user_rec(rec));
  ut_ad(rec_offs_validate(rec, index, offsets));

  /* Temp-tables are not shared across connections and multiple
  transactions from different connections cannot simultaneously
  operate on same temp-table and so read of temp-table is
  always consistent read. */
  if (srv_read_only_mode || index->table->is_temporary()) {
    ut_ad(view == nullptr || index->table->is_temporary());
    return (true);
  }

  /* NOTE that we call this function while holding the search
  system latch. */

  trx_id_t trx_id = row_get_rec_trx_id(rec, index, offsets);

  return (view->changes_visible(trx_id, index->table->name));
}
```

row_search_mvcc -> trx_assign_read_view -> MVCC::view_open -> ReadView::prepare

```cpp

/**
Opens a read view where exactly the transactions serialized before this
point in time are seen in the view.
@param id		Creator transaction id */

void ReadView::prepare(trx_id_t id) {
  ut_ad(trx_sys_mutex_own());

  m_creator_trx_id = id;

  m_low_limit_no = trx_get_serialisation_min_trx_no();

  m_low_limit_id = trx_sys_get_next_trx_id_or_no();

  ut_a(m_low_limit_no <= m_low_limit_id);

  if (!trx_sys->rw_trx_ids.empty()) {
    copy_trx_ids(trx_sys->rw_trx_ids);
  } else {
    m_ids.clear();
  }

  /* The first active transaction has the smallest id. */
  m_up_limit_id = !m_ids.empty() ? m_ids.front() : m_low_limit_id;

  ut_a(m_up_limit_id <= m_low_limit_id);

  ut_d(m_view_low_limit_no = m_low_limit_no);
  m_closed = false;
}
```

changes_visible

```c

  /** Check whether the changes by id are visible.
  @param[in]	id	transaction id to check against the view
  @param[in]	name	table name
  @return whether the view sees the modifications of id. */
  bool changes_visible(trx_id_t id, const table_name_t &name) const
      MY_ATTRIBUTE((warn_unused_result)) {
    ut_ad(id > 0);

    if (id < m_up_limit_id || id == m_creator_trx_id) {
      return (true);
    }

    check_trx_id_sanity(id, name);

    if (id >= m_low_limit_id) {
      return (false);

    } else if (m_ids.empty()) {
      return (true);
    }

    const ids_t::value_type *p = m_ids.data();

    return (!std::binary_search(p, p + m_ids.size(), id));
  }
```

```c

/** Updates a record when the update causes no size changes in its fields.  */
dberr_t btr_cur_update_in_place(ulint flags, btr_cur_t *cursor, ulint *offsets,
                                const upd_t *update, ulint cmpl_info,
                                que_thr_t *thr, trx_id_t trx_id, mtr_t *mtr) {
 
  rec = btr_cur_get_rec(cursor);
  
  // ...
  /* The insert buffer tree should never be updated in place. */
  // ...
  
  /* Check that enough space is available on the compressed page. */
 // ...

  /* Do lock checking and undo logging */
  err = btr_cur_upd_lock_and_undo(flags, cursor, offsets, update, cmpl_info,
                                  thr, mtr, &roll_ptr);

  if (!(flags & BTR_KEEP_SYS_FLAG) && !index->table->is_intrinsic()) {
    // update trx_id, roll_ptr
    row_upd_rec_sys_fields(rec, nullptr, index, offsets, thr_get_trx(thr),
                           roll_ptr);
  }

  // ...
  row_upd_rec_in_place(rec, index, offsets, update, page_zip);

 // ...
  
  // write redo log
  btr_cur_update_in_place_log(flags, rec, index, update, trx_id, roll_ptr, mtr);

  return (err);
}
```

## Links

- [Transaction](/docs/CS/DB/MySQL/Transaction.md)
- [Undo Log](/docs/CS/DB/MySQL/undolog.md)
- [Locks](/docs/CS/DB/MySQL/lock.md)
- [Index](/docs/CS/DB/MySQL/Index.md)
- [InnoDB](/docs/CS/DB/MySQL/InnoDB.md)
- [Version Migration](/docs/CS/DB/MySQL/Version_Migration.md)

## References

1. [MySQL 9.7 Reference Manual: InnoDB Multi-Versioning](https://dev.mysql.com/doc/refman/9.7/en/innodb-multi-versioning.html)
2. [MySQL 9.7 Reference Manual: Consistent Read and Locking Reads](https://dev.mysql.com/doc/refman/9.7/en/innodb-locking-reads.html)
3. [MySQL 9.7 Reference Manual: Transaction Isolation Levels](https://dev.mysql.com/doc/refman/9.7/en/innodb-transaction-isolation-levels.html)
