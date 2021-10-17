## Introduction

To implement a large-scale, busy, or highly reliable database application, to port substantial code from a different database system, or to tune MySQL performance, it is important to understand `InnoDB` locking and the `InnoDB` transaction model.



## InnoDB and the ACID Model

The `InnoDB` transaction model aims combine the best properties of a multi-versioning database with traditional two-phase locking. `InnoDB` performs locking at the row level and runs queries as [nonlocking consistent reads](/docs/CS/DB/MySQL/Transaction.md?id=consistent-read) by default, in the style of Oracle. The lock information in `InnoDB` is stored space-efficiently so that lock escalation is not needed. Typically, several users are permitted to lock every row in `InnoDB` tables, or any random subset of the rows, without causing `InnoDB` memory exhaustion.

The following sections discuss how MySQL features, in particular the `InnoDB` storage engine, interact with the categories of the ACID model:

### Atomicity

The **atomicity** aspect of the ACID model mainly involves `InnoDB` transactions. Related MySQL features include:

- The `autocommit` setting.
- The `COMMIT` statement.
- The `ROLLBACK` statement.

### Consistency

The **consistency** aspect of the ACID model mainly involves internal `InnoDB` processing to protect data from crashes. Related MySQL features include:

- The `InnoDB` [doublewrite buffer](/docs/CS/DB/MySQL/disk.md?id=Doublewrite_Buffer).
- `InnoDB` crash recovery.

### Isolation

The **isolation** aspect of the ACID model mainly involves `InnoDB` transactions, in particular the isolation level that applies to each transaction. Related MySQL features include:

- The [`autocommit` setting.
- Transaction isolation levels and the `SET TRANSACTION` statement.
- The low-level details of `InnoDB` locking. Details can be viewed in the `INFORMATION_SCHEMA` tables.

### Durability

The **durability** aspect of the ACID model involves MySQL software features interacting with your particular hardware configuration. Because of the many possibilities depending on the capabilities of your CPU, network, and storage devices, this aspect is the most complicated to provide concrete guidelines for. (And those guidelines might take the form of “buy new hardware”.) Related MySQL features include:

- The `InnoDB` doublewrite buffer.
- The `innodb_flush_log_at_trx_commit` variable.
- The `sync_binlog` variable.
- The `innodb_file_per_table` variable.
- The write buffer in a storage device, such as a disk drive, SSD, or RAID array.
- A battery-backed cache in a storage device.
- The operating system used to run MySQL, in particular its support for the `fsync()` system call.
- An uninterruptible power supply (UPS) protecting the electrical power to all computer servers and storage devices that run MySQL servers and store MySQL data.
- Your backup strategy, such as frequency and types of backups, and backup retention periods.
- For distributed or hosted data applications, the particular characteristics of the data centers where the hardware for the MySQL servers is located, and network connections between the data centers.



### Transaction Isolation Levels

#### READ UNCOMMITTED
Transactions running at the `READ UNCOMMITTED` level **do not issue shared locks to prevent other transactions from modifying data read by the current transaction**. `READ UNCOMMITTED` transactions are also not blocked by exclusive locks that would prevent the current transaction from reading rows that have been modified but not committed by other transactions.  **This option has the same effect as setting NOLOCK on all tables in all SELECT statements in a transaction.** 

#### READ COMMITTED

Each consistent read, even within the same transaction, sets and reads its own **fresh snapshot.** 

**Because gap locking is disabled, `phantom row` problems may occur, as other sessions can insert new rows into the gaps**. 

Only row-based binary logging is supported with the `READ COMMITTED` isolation level. If you use `READ COMMITTED` with `binlog_format=MIXED`, the server automatically uses row-based logging.

Using `READ COMMITTED` has additional effects:

- For `UPDATE` or `DELETE` statements, `InnoDB` holds locks only for rows that it updates or deletes. Record locks for nonmatching rows are released after MySQL has evaluated the `WHERE` condition. This greatly reduces the probability of deadlocks, but they can still happen.
- For `UPDATE` statements, if a row is already locked, `InnoDB` performs a “semi-consistent” read, returning the latest committed version to MySQL so that MySQL can determine whether the row matches the `WHERE` condition of the `UPDATE`. If the row matches (must be updated), MySQL reads the row again and this time `InnoDB` either locks it or waits for a lock on it.

#### REPEATABLE READ

This is the default isolation level for InnoDB. Consistent reads within the same transaction **read the snapshot established by the first read**(any SELECT or UPDATE/INSERT/DELETE). This means that if you issue several plain (nonlocking) SELECT statements within the same transaction, these SELECT statements are consistent also with respect to each other.

For locking reads (SELECT with FOR UPDATE or LOCK IN SHARE MODE), UPDATE, and DELETE statements, locking depends on whether the statement uses a unique index with a unique search condition or a range-type search condition.
- For a unique index with a unique search condition, InnoDB locks only the index record found, not the gap before it.
- For other search conditions, InnoDB locks the index range scanned, using gap locks or next-key locks to block insertions by other sessions into the gaps covered by the range.

## Locking

### Locking Types

```mysql
mysql> select * from information_schema.innodb_locks;
```



#### Shared and Exclusive Locks

`InnoDB` implements standard **row-level locking** where there are two types of locks, shared (`S`) locks and exclusive (`X`) locks.

- A shared (`S`) lock permits the transaction that holds the lock to read a row.
- An exclusive (`X`) lock permits the transaction that holds the lock to update or delete a row.

If transaction `T1` holds a shared (`S`) lock on row `r`, then requests from some distinct transaction `T2` for a lock on row `r` are handled as follows:

- A request by `T2` for an `S` lock can be granted immediately. As a result, both `T1` and `T2` hold an `S` lock on `r`.
- A request by `T2` for an `X` lock cannot be granted immediately.

If a transaction `T1` holds an exclusive (`X`) lock on row `r`, a request from some distinct transaction `T2` for a lock of either type on `r` cannot be granted immediately. Instead, transaction `T2` has to wait for transaction `T1` to release its lock on row `r`.

#### Intention Locks

`InnoDB` supports *multiple granularity locking* which permits coexistence of row locks and table locks. For example, a statement such as `LOCK TABLES ... WRITE` takes an exclusive lock (an `X` lock) on the specified table. To make locking at multiple granularity levels practical, `InnoDB` uses intention locks. Intention locks are **table-level** locks that indicate which type of lock (shared or exclusive) a transaction requires later for a row in a table. There are two types of intention locks:

- An intention shared lock (`IS`) indicates that a transaction intends to set a *shared* lock on individual rows in a table.
- An intention exclusive lock (`IX`) indicates that a transaction intends to set an exclusive lock on individual rows in a table.

For example, `SELECT ... FOR SHARE` sets an `IS` lock, and `SELECT ... FOR UPDATE` sets an `IX` lock.

The intention locking protocol is as follows:

- Before a transaction can acquire a shared lock on a row in a table, it must first acquire an `IS` lock or stronger on the table.
- Before a transaction can acquire an exclusive lock on a row in a table, it must first acquire an `IX` lock on the table.

Table-level lock type compatibility is summarized in the following matrix.

|      | `X`      | `IX`       | `S`        | `IS`       |
| :--- | :------- | :--------- | :--------- | :--------- |
| `X`  | Conflict | Conflict   | Conflict   | Conflict   |
| `IX` | Conflict | Compatible | Conflict   | Compatible |
| `S`  | Conflict | Conflict   | Compatible | Compatible |
| `IS` | Conflict | Compatible | Compatible | Compatible |



#### Record Locks

A record lock is a lock on an index record. For example, `SELECT c1 FROM t WHERE c1 = 10 FOR UPDATE;` prevents any other transaction from inserting, updating, or deleting rows where the value of `t.c1` is `10`.

**Record locks always lock index records**, even if a table is defined with no indexes. For such cases, `InnoDB` creates a hidden clustered index and uses this index for record locking.

#### Gap Locks

**A gap lock is a lock on a gap between index records, or a lock on the gap before the first or after the last index record**. For example, `SELECT c1 FROM t WHERE c1 BETWEEN 10 and 20 FOR UPDATE;` prevents other transactions from inserting a value of `15` into column `t.c1`, whether or not there was already any such value in the column, because the gaps between all existing values in the range are locked.

**A gap might span a single index value, multiple index values, or even be empty.**

Gap locks are part of the tradeoff between performance and concurrency, and are used in some transaction isolation levels and not others.

Gap locking is not needed for statements that lock rows using a unique index to search for a unique row. (This does not include the case that the search condition includes only some columns of a multiple-column unique index; in that case, gap locking does occur.)

If `id` is not indexed or has a nonunique index, the statement does lock the preceding gap.

It is also worth noting here that conflicting locks can be held on a gap by different transactions. For example, transaction A can hold a shared gap lock (gap S-lock) on a gap while transaction B holds an exclusive gap lock (gap X-lock) on the same gap. The reason conflicting gap locks are allowed is that if a record is purged from an index, the gap locks held on the record by different transactions must be merged.

Gap locks in `InnoDB` are “purely inhibitive”, which means that their only purpose is to prevent other transactions from inserting to the gap. Gap locks can co-exist. A gap lock taken by one transaction does not prevent another transaction from taking a gap lock on the same gap. There is no difference between shared and exclusive gap locks. They do not conflict with each other, and they perform the same function.

Gap locking can be disabled explicitly. This occurs if you change the transaction isolation level to `READ COMMITTED`. In this case, gap locking is disabled for searches and index scans and is used only for foreign-key constraint checking and duplicate-key checking.

There are also other effects of using the `READ COMMITTED` isolation level. Record locks for nonmatching rows are released after MySQL has evaluated the `WHERE` condition. For `UPDATE` statements, `InnoDB` does a “semi-consistent” read, such that it returns the latest committed version to MySQL so that MySQL can determine whether the row matches the `WHERE` condition of the `UPDATE`.

#### Next-Key Locks

**A next-key lock is a combination of a record lock on the index record and a gap lock on the gap before the index record.**

`InnoDB` performs row-level locking in such a way that when it searches or scans a table index, it sets shared or exclusive locks on the index records it encounters. Thus, **the row-level locks are actually index-record locks**. A next-key lock on an index record also affects the “gap” before that index record. That is, a next-key lock is an index-record lock plus a gap lock on the gap preceding the index record. If one session has a shared or exclusive lock on record `R` in an index, another session cannot insert a new index record in the gap immediately before `R` in the index order.

For the last interval, the next-key lock locks the gap above the largest value in the index and the “supremum” pseudo-record having a value higher than any value actually in the index. The supremum is not a real index record, so, in effect, this next-key lock locks only the gap following the largest index value.

By default, `InnoDB` operates in `REPEATABLE READ` transaction isolation level. In this case, **`InnoDB` uses next-key locks for searches and index scans, which prevents `phantom rows`**.

#### Insert Intention Locks

**An insert intention lock is a type of gap lock set by `INSERT` operations prior to row insertion**. This lock signals the intent to insert in such a way that multiple transactions inserting into the same index gap need not wait for each other if they are not inserting at the same position within the gap. Suppose that there are index records with values of 4 and 7. Separate transactions that attempt to insert values of 5 and 6, respectively, each lock the gap between 4 and 7 with insert intention locks prior to obtaining the exclusive lock on the inserted row, but do not block each other because the rows are nonconflicting.

#### AUTO-INC Locks

An `AUTO-INC` lock is a special table-level lock taken by transactions inserting into tables with `AUTO_INCREMENT` columns. In the simplest case, if one transaction is inserting values into the table, any other transactions must wait to do their own inserts into that table, so that rows inserted by the first transaction receive consecutive primary key values.

The `innodb_autoinc_lock_mode` variable controls the algorithm used for auto-increment locking. It allows you to choose how to trade off between predictable sequences of auto-increment values and maximum concurrency for insert operations.


#### Source Code
```cpp

/** Lock modes and types */
/** @{ */
#define LOCK_MODE_MASK                          \
  0xFUL /*!< mask used to extract mode from the \
        type_mode field in a lock */
/** Lock types */
#define LOCK_TABLE 16 /*!< table lock */
#define LOCK_REC 32   /*!< record lock */
#define LOCK_TYPE_MASK                                \
  0xF0UL /*!< mask used to extract lock type from the \
         type_mode field in a lock */
#if LOCK_MODE_MASK & LOCK_TYPE_MASK
#error "LOCK_MODE_MASK & LOCK_TYPE_MASK"
#endif

#define LOCK_WAIT                          \
  256 /*!< Waiting lock flag; when set, it \
      means that the lock has not yet been \
      granted, it is just waiting for its  \
      turn in the wait queue */
/* Precise modes */
#define LOCK_ORDINARY                     \
  0 /*!< this flag denotes an ordinary    \
    next-key lock in contrast to LOCK_GAP \
    or LOCK_REC_NOT_GAP */
#define LOCK_GAP                                     \
  512 /*!< when this bit is set, it means that the   \
      lock holds only on the gap before the record;  \
      for instance, an x-lock on the gap does not    \
      give permission to modify the record on which  \
      the bit is set; locks of this type are created \
      when records are removed from the index chain  \
      of records */
#define LOCK_REC_NOT_GAP                            \
  1024 /*!< this bit means that the lock is only on \
       the index record and does NOT block inserts  \
       to the gap before the index record; this is  \
       used in the case when we retrieve a record   \
       with a unique key, and is also used in       \
       locking plain SELECTs (not part of UPDATE    \
       or DELETE) when the user has set the READ    \
       COMMITTED isolation level */
#define LOCK_INSERT_INTENTION                                             \
  2048                       /*!< this bit is set when we place a waiting \
                          gap type record lock request in order to let    \
                          an insert of an index record to wait until      \
                          there are no conflicting locks by other         \
                          transactions on the gap; note that this flag    \
                          remains set when the waiting lock is granted,   \
                          or if the lock is inherited to a neighboring    \
                          record */
#define LOCK_PREDICATE 8192  /*!< Predicate lock */
#define LOCK_PRDT_PAGE 16384 /*!< Page lock */
```


### Deadlocks

A deadlock is a situation where different transactions are unable to proceed because each holds a lock that the other needs. Because both transactions are waiting for a resource to become available, neither ever release the locks it holds.

#### Minimize and Handle Deadlocks

You can cope with deadlocks and reduce the likelihood of their occurrence with the following techniques:

- At any time, issue `SHOW ENGINE INNODB STATUS` to determine the cause of the most recent deadlock. That can help you to tune your application to avoid deadlocks.
- `SHOW FULL PROCESSLIST`
- table `INNODB_TRX`, `INNODB_LOCKS`, `INNODB_LOCK_WAITS` in information_schema
- If frequent deadlock warnings cause concern, collect more extensive debugging information by enabling the `innodb_print_all_deadlocks` variable. Information about each deadlock, not just the latest one, is recorded in the MySQL [error log](). Disable this option when you are finished debugging.

- Always be prepared to re-issue a transaction if it fails due to deadlock. Deadlocks are not dangerous. Just try again.

- Keep transactions small and short in duration to make them less prone to collision.

- Commit transactions immediately after making a set of related changes to make them less prone to collision. In particular, do not leave an interactive **mysql** session open for a long time with an uncommitted transaction.

- If you use *locking reads* (`SELECT ... FOR UPDATE` or `SELECT ... FOR SHARE`), try using a lower isolation level such as `READ COMMITTED`.

- When modifying multiple tables within a transaction, or different sets of rows in the same table, do those operations in a consistent order each time. Then transactions form well-defined queues and do not deadlock. For example, organize database operations into functions within your application, or call stored routines, rather than coding multiple similar sequences of `INSERT`, `UPDATE`, and `DELETE` statements in different places.

- Add well-chosen indexes to your tables so that your queries scan fewer index records and set fewer locks. Use `EXPLAIN SELECT` to determine which indexes the MySQL server regards as the most appropriate for your queries.

- Use less locking. If you can afford to permit a `SELECT` to return data from an old snapshot, do not add a `FOR UPDATE` or `FOR SHARE` clause to it. Using the `READ COMMITTED` isolation level is good here, because each consistent read within the same transaction reads from its own fresh snapshot.

- If nothing else helps, serialize your transactions with table-level locks. The correct way to use `LOCK TABLES` with transactional tables, such as `InnoDB` tables, is to begin a transaction with `SET autocommit = 0` (not `START TRANSACTION`) followed by `LOCK TABLES`, and to not call `UNLOCK TABLES` until you commit the transaction explicitly. For example, if you need to write to table `t1` and read from table `t2`, you can do this:

  Table-level locks prevent concurrent updates to the table, avoiding deadlocks at the expense of less responsiveness for a busy system.

- Another way to serialize transactions is to create an auxiliary “semaphore” table that contains just a single row. Have each transaction update that row before accessing other tables. In that way, all transactions happen in a serial fashion. Note that the `InnoDB` instant deadlock detection algorithm also works in this case, because the serializing lock is a row-level lock. With MySQL table-level locks, the timeout method must be used to resolve deadlocks.



#### Deadlock Detection

A mechanism that automatically detects when a **deadlock** occurs, and automatically **rolls back** one of the **transactions** involved (the **victim**). Deadlock detection can be disabled using the `innodb_deadlock_detect` configuration option.




## MVCC

In Concurrency Control theory, there are two ways you can deal with conflicts:

- You can avoid them, by employing a pessimistic locking mechanism (e.g. Read/Write locks, Two-Phase Locking)
- You can allow conflicts to occur, but you need to detect them using an optimistic locking mechanism (e.g. logical clock, MVCC)

Because MVCC (Multi-Version Concurrency Control) is such a prevalent Concurrency Control technique (not only in relational database systems, in this article, I’m going to explain how it works.

When the [ACID transaction properties](/docs/CS/Transaction.md?id=ACID) were first defined, Serializability was assumed. And to provide a Strict Serializable transaction outcome, the [2PL (Two-Phase Locking)](https://vladmihalcea.com/2pl-two-phase-locking/) mechanism was employed. When using 2PL, every read requires a shared lock acquisition, while a write operation requires taking an exclusive lock.

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

`InnoDB` is a multi-version storage engine. It keeps information about old versions of changed rows to support transactional features such as concurrency and rollback. **This information is stored in undo tablespaces in a data structure called a rollback segment.** `InnoDB` uses the information in the rollback segment to perform the undo operations needed in a transaction rollback. It also uses the information to build earlier versions of a row for a consistent read.

Internally, `InnoDB` adds three fields to each row stored in the database:

- A 6-byte `DB_TRX_ID` field indicates the transaction identifier for the last transaction that inserted or updated the row. Also, a deletion is treated internally as an update where a special bit in the row is set to mark it as deleted.
- A 7-byte `DB_ROLL_PTR` field called the roll pointer. The roll pointer points to an **undo log** record written to the rollback segment. If the row was updated, the undo log record contains the information necessary to rebuild the content of the row before it was updated.
- A 6-byte `DB_ROW_ID` field contains a row ID that increases monotonically as new rows are inserted. If `InnoDB` generates a clustered index automatically, the index contains row ID values. Otherwise, the `DB_ROW_ID` column does not appear in any index.

Undo logs in the rollback segment are divided into insert and update undo logs. Insert undo logs are needed only in transaction rollback and can be discarded as soon as the transaction commits. Update undo logs are used also in consistent reads, but they can be discarded only after there is no transaction present for which `InnoDB` has assigned a snapshot that in a consistent read could require the information in the update undo log to build an earlier version of a database row.

It is recommend that you commit transactions regularly, including transactions that issue only consistent reads. Otherwise, `InnoDB` cannot discard data from the update undo logs, and the rollback segment may grow too big, filling up the undo tablespace in which it resides.

The physical size of an undo log record in the rollback segment is typically smaller than the corresponding inserted or updated row. You can use this information to calculate the space needed for your rollback segment.

In the `InnoDB` multi-versioning scheme, a row is not physically removed from the database immediately when you delete it with an SQL statement. `InnoDB` only physically removes the corresponding row and its index records when it discards the update undo log record written for the deletion. This removal operation is called a purge, and it is quite fast, usually taking the same order of time as the SQL statement that did the deletion.

If you insert and delete rows in smallish batches at about the same rate in the table, the purge thread can start to lag behind and the table can grow bigger and bigger because of all the “dead” rows, making everything disk-bound and very slow. In such cases, throttle new row operations, and allocate more resources to the purge thread by tuning the [`innodb_max_purge_lag`](https://dev.mysql.com/doc/refman/8.0/en/innodb-parameters.html#sysvar_innodb_max_purge_lag) system variable.

### Locking Reads

A `SELECT` statement that also performs a **locking** operation on an `InnoDB` table. Either `SELECT ... FOR UPDATE` or `SELECT ... LOCK IN SHARE MODE`. It has the potential to produce a **deadlock**, depending on the **isolation level** of the transaction. The opposite of a **non-locking read**. Not allowed for global tables in a **read-only transaction**.

`SELECT ... FOR SHARE` replaces `SELECT ... LOCK IN SHARE MODE` in MySQL 8.0.1, but `LOCK IN SHARE MODE` remains available for backward compatibility.

### Consistent Nonlocking Reads

A `consistent read` means that `InnoDB` uses multi-versioning to present to a query a snapshot of the database at a point in time. The query sees the changes made by transactions that committed before that point in time, and no changes made by later or uncommitted transactions. The exception to this rule is that the query sees the changes made by earlier statements within the same transaction. This exception causes the following anomaly: 
If you update some rows in a table, a `SELECT` sees the latest version of the updated rows, but it might also see older versions of any rows. If other sessions simultaneously update the same table, the anomaly means that you might see the table in a state that never existed in the database.

- If the transaction isolation level is `REPEATABLE READ` (the default level), all consistent reads within the same transaction read the snapshot established by the first such read in that transaction. You can get a fresher snapshot for your queries by committing the current transaction and after that issuing new queries.
- With `READ COMMITTED` isolation level, each consistent read within a transaction sets and reads its own fresh snapshot.

Consistent read is the default mode in which `InnoDB` processes `SELECT` statements in `READ COMMITTED` and `REPEATABLE READ` isolation levels. A consistent read does not set any locks on the tables it accesses, and therefore other sessions are free to modify those tables at the same time a consistent read is being performed on the table.

Suppose that you are running in the default `REPEATABLE READ` isolation level. When you issue a consistent read (that is, an ordinary `SELECT` statement), `InnoDB` gives your transaction a timepoint according to which your query sees the database. **If another transaction deletes a row and commits after your timepoint was assigned, you do not see the row as having been deleted. Inserts and updates are treated similarly.**

**The snapshot of the database state applies to `SELECT` statements within a transaction, not necessarily to `DML` statements`**.

 If you insert or modify some rows and then commit that transaction, a `DELETE`or `UPDATE`statement issued from another concurrent `REPEATABLE READ` transaction **could affect those just-committed rows, even though the session could not query them**. If a transaction does update or delete rows committed by a different transaction, those changes do become visible to the current transaction. 



### Multi-Versioning and Secondary Indexes

`InnoDB` multiversion concurrency control (MVCC) treats secondary indexes differently than clustered indexes. Records in a clustered index are updated in-place, and their hidden system columns point undo log entries from which earlier versions of records can be reconstructed. Unlike clustered index records, secondary index records do not contain hidden system columns nor are they updated in-place.

When a secondary index column is updated, old secondary index records are delete-marked, new records are inserted, and delete-marked records are eventually purged. When a secondary index record is delete-marked or the secondary index page is updated by a newer transaction, `InnoDB` looks up the database record in the clustered index. In the clustered index, the record's `DB_TRX_ID` is checked, and the correct version of the record is retrieved from the undo log if the record was modified after the reading transaction was initiated.

If a secondary index record is marked for deletion or the secondary index page is updated by a newer transaction, the [covering index](/docs/CS/DB/MySQL/Transaction.md?id=covering_index) technique is not used. Instead of returning values from the index structure, `InnoDB` looks up the record in the clustered index.

However, if the [index condition pushdown (ICP)](/docs/CS/DB/MySQL/Optimization.md?id=Index_Condition_Pushdown_Optimization) optimization is enabled, and parts of the `WHERE` condition can be evaluated using only fields from the index, the MySQL server still pushes this part of the `WHERE` condition down to the storage engine where it is evaluated using the index. If no matching records are found, the clustered index lookup is avoided. If matching records are found, even among delete-marked records, `InnoDB` looks up the record in the clustered index.



### Source Code



```c
// dict0dict.cc
/** Adds system columns to a table object. */
void dict_table_add_system_columns(dict_table_t *table, mem_heap_t *heap) {
  ut_ad(table);
  ut_ad(table->n_def == (table->n_cols - table->get_n_sys_cols()));
  ut_ad(table->magic_n == DICT_TABLE_MAGIC_N);
  ut_ad(!table->cached);

  /* NOTE: the system columns MUST be added in the following order
  (so that they can be indexed by the numerical value of DATA_ROW_ID,
  etc.) and as the last columns of the table memory object.
  The clustered index will not always physically contain all system
  columns.
  Intrinsic table don't need DB_ROLL_PTR as UNDO logging is turned off
  for these tables. */

  dict_mem_table_add_col(table, heap, "DB_ROW_ID", DATA_SYS,
                         DATA_ROW_ID | DATA_NOT_NULL, DATA_ROW_ID_LEN, false);

  dict_mem_table_add_col(table, heap, "DB_TRX_ID", DATA_SYS,
                         DATA_TRX_ID | DATA_NOT_NULL, DATA_TRX_ID_LEN, false);

  if (!table->is_intrinsic()) {
    dict_mem_table_add_col(table, heap, "DB_ROLL_PTR", DATA_SYS,
                           DATA_ROLL_PTR | DATA_NOT_NULL, DATA_ROLL_PTR_LEN,
                           false);

    /* This check reminds that if a new system column is added to
    the program, it should be dealt with here */
  }
}
```





trx_sys_t:
1. MVCC
2. trx_id
3. [Rsegs](/docs/CS/DB/MySQL/Transaction.md?id=Rollback_Segment)

```c
// trx0sys.h
/** The transaction system central memory data structure. */
struct trx_sys_t {  
	TrxSysMutex mutex;
  
  MVCC *mvcc; /** Multi version concurrency control manager */
 
  /** Minimum trx->id of active RW transactions (minimum in the rw_trx_ids).
  Protected by the trx_sys_t::mutex but might be read without the mutex. */
  std::atomic<trx_id_t> min_active_trx_id;
  
  std::atomic<trx_id_t> rw_max_trx_id; /** Max trx id of read-write transactions which exist or existed. */
  
 /** Array of Read write transaction IDs for MVCC snapshot. A ReadView would
  take a snapshot of these transactions whose changes are not visible to it.
  We should remove transactions from the list before committing in memory and
  releasing locks to ensure right order of removal and consistent snapshot. */
  trx_ids_t rw_trx_ids;
  
  Rsegs rsegs; /** Vector of pointers to rollback segments. */
  
  Rsegs tmp_rsegs; /** Vector of pointers to rollback segments within the temp tablespace; */
  
  /** A list of undo tablespace IDs found in the TRX_SYS page.
  This cannot be part of the trx_sys_t object because it is initialized before
  that object is created. */
  extern Space_Ids *trx_sys_undo_spaces; 
  // ...
 };
```



MVCC read view

```c
// read0read.h
/** The MVCC read view manager */
class MVCC {
 
  public:
  void view_open(ReadView *&view, trx_t *trx);

  void view_close(ReadView *&view, bool own_mutex);

  void view_release(ReadView *&view);

  void clone_oldest_view(ReadView *view);

  static bool is_view_active(ReadView *view) {
    ut_a(view != reinterpret_cast<ReadView *>(0x1));
    return (view != nullptr && !(intptr_t(view) & 0x1));
  }
  
 private:
  typedef UT_LIST_BASE_NODE_T(ReadView, m_view_list) view_list_t;

  /** Free views ready for reuse. */
  view_list_t m_free;

  /** Active and closed views, the closed views will have the
  creator trx id set to TRX_ID_MAX */
  view_list_t m_views;
}
```



```c
// read0types.h
/** Read view lists the trx ids of those transactions for which a consistent
read should not see the modifications to the database. */
class ReadView {

 private:
  /** The read should not see any transaction with trx id >= this
  value. In other words, this is the "high water mark". */
  trx_id_t m_low_limit_id;

  /** The read should see all trx ids which are strictly
  smaller (<) than this value.  In other words, this is the
  low water mark". */
  trx_id_t m_up_limit_id;

  /** trx id of creating transaction, set to TRX_ID_MAX for free
  views. */
  trx_id_t m_creator_trx_id;

  /** Set of RW transactions that was active when this snapshot
  was taken */
  ids_t m_ids;

  /** The view does not need to see the undo logs for transactions
  whose transaction number is strictly smaller (<) than this value:
  they can be removed in purge if not needed by other views */
  trx_id_t m_low_limit_no;

#ifdef UNIV_DEBUG
  /** The low limit number up to which read views don't need to access
  undo log records for MVCC. This could be higher than m_low_limit_no
  if purge is blocked for GTID persistence. Currently used for debug
  variable INNODB_PURGE_VIEW_TRX_ID_AGE. */
  trx_id_t m_view_low_limit_no;
#endif /* UNIV_DEBUG */

  /** AC-NL-RO transaction view that has been "closed". */
  bool m_closed;
}
```

#### ReadView

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


#### prepare
1. set insert_undo & update_undo
2. redo log
```c
// trx0trx.cc
/** Prepares a transaction for given rollback segment.
 @return lsn_t: lsn assigned for commit of scheduled rollback segment */
static lsn_t trx_prepare_low(

    // ...
    
    /* Change the undo log segment states from TRX_UNDO_ACTIVE to
    TRX_UNDO_PREPARED: these modifications to the file data
    structure define the transaction as prepared in the file-based
    world, at the serialization point of lsn. */

    rseg->latch();

    if (undo_ptr->insert_undo != nullptr) {
      /* It is not necessary to obtain trx->undo_mutex here
      because only a single OS thread is allowed to do the
      transaction prepare for this transaction. */
      trx_undo_set_state_at_prepare(trx, undo_ptr->insert_undo, false, &mtr);
    }

    if (undo_ptr->update_undo != nullptr) {
      if (!noredo_logging) {
        trx_undo_gtid_set(trx, undo_ptr->update_undo, true);
      }
      trx_undo_set_state_at_prepare(trx, undo_ptr->update_undo, false, &mtr);
    }

    rseg->unlatch();
    
    
    /*--------------*/
    /* This mtr commit makes the transaction prepared in
    file-based world. */
    mtr_commit(&mtr);
    /*--------------*/

    if (!noredo_logging) {
      const lsn_t lsn = mtr.commit_lsn();
      ut_ad(lsn > 0 || !mtr_t::s_logging.is_enabled());
      return lsn;
    }
}    
```

#### commit
If transaction involves insert then truncate undo logs.

If transaction involves update then add rollback segments
to purge queue.

Update the latest MySQL binlog name and offset information
in trx sys header only if MySQL binary logging is on and clone
is has ensured commit order at final stage.

```c

/** Commits a transaction and a mini-transaction.
@param[in,out] trx Transaction
@param[in,out] mtr Mini-transaction (will be committed), or null if trx made no
modifications */
void trx_commit_low(trx_t *trx, mtr_t *mtr) {
    assert_trx_nonlocking_or_in_list(trx)
    
    
    
  bool serialised;

    serialised = trx_write_serialisation_history(trx, mtr);
    

}




/** Assign the transaction its history serialisation number and write the
 update UNDO log record to the assigned rollback segment.
 @return true if a serialisation log was written */
static bool trx_write_serialisation_history(
    trx_t *trx, /*!< in/out: transaction */
    mtr_t *mtr) /*!< in/out: mini-transaction */
{
  
  // ...
  
  
  /* If transaction involves insert then truncate undo logs. */
  if (trx->rsegs.m_redo.insert_undo != nullptr) {
    trx_undo_set_state_at_finish(trx->rsegs.m_redo.insert_undo, mtr);
  }

  
  /* If transaction involves update then add rollback segments
  to purge queue. */


  /* Update the latest MySQL binlog name and offset information
  in trx sys header only if MySQL binary logging is on and clone
  is has ensured commit order at final stage. */
  if (Clone_handler::need_commit_order()) {
    trx_sys_update_mysql_binlog_offset(trx, mtr);
  }

}

```


## Distributed Transaction
XA : isolation level must be `SERIALIZABLE`

- RM
- TM





## References

1. [How does a relational database work](https://vladmihalcea.com/how-does-a-relational-database-work/)
2. [Detailed explanation of MySQL mvcc mechanism](https://developpaper.com/detailed-explanation-of-mysql-mvcc-mechanism/)
3. [解决死锁之路 - 学习事务与隔离级别](https://www.aneasystone.com/archives/2017/10/solving-dead-locks-one.html)


