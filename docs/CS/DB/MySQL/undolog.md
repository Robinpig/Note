## Introduction

An undo log is a collection of undo log records associated with a single read-write transaction. 
An undo log record contains information about how to undo the latest change by a transaction to a [clustered index](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_clustered_index) record. 
If another transaction needs to see the original data as part of a consistent read operation, the unmodified data is retrieved from undo log records. 
Undo logs exist within [undo log segments](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_undo_log_segment), which are contained within [rollback segments](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_rollback_segment). 
Rollback segments reside in [undo tablespaces](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_undo_tablespace) and in the [global temporary tablespace](https://dev.mysql.com/doc/refman/8.0/en/glossary.html#glos_global_temporary_tablespace).


What is undo log for:

1. [Atomicity](/docs/CS/DB/MySQL/Transaction.md?id=Atomicity)
2. [MVCC](/docs/CS/DB/MySQL/Transaction.md?id=MVCC)




Undo logs that reside in the global temporary tablespace are used for transactions that modify data in user-defined temporary tables. These undo logs are not redo-logged, as they are not required for crash recovery. 
They are used only for rollback while the server is running. This type of undo log benefits performance by avoiding redo logging I/O.


Each undo tablespace and the global temporary tablespace individually support a maximum of 128(InnoDB Page Size 4KB/16)) rollback segments.


A transaction is assigned up to four undo logs, one for each of the following operation types:

1. `INSERT` operations on user-defined tables
2. `UPDATE` and `DELETE` operations on user-defined tables
3. `INSERT` operations on user-defined temporary tables
4. `UPDATE` and `DELETE` operations on user-defined temporary tables

Undo logs are assigned as needed.  
For example, a transaction that performs `INSERT`, `UPDATE`, and `DELETE` operations on regular and temporary tables requires a full assignment of four undo logs.
A transaction that performs only INSERT operations on regular tables requires a single undo log.

A transaction that performs operations on regular tables is assigned undo logs from an assigned undo tablespace rollback segment. 
A transaction that performs operations on temporary tables is assigned undo logs from an assigned global temporary tablespace rollback segment.
An undo log assigned to a transaction remains attached to the transaction for its duration.

> [!NOTE]
>
> It is possible to encounter a concurrent transaction limit error before reaching the number of concurrent read-write transactions that InnoDB is capable of supporting. 
> This occurs when a rollback segment assigned to a transaction runs out of undo slots. In such cases, try rerunning the transaction.
>
> When transactions perform operations on temporary tables, the number of concurrent read-write transactions that InnoDB is capable of supporting is constrained by the number of rollback segments allocated to the global temporary tablespace, which is 128 by default.



## Undo Tablespaces

As of MySQL 5.6, rollback segments can reside in undo tablespaces. In MySQL 5.6 and MySQL 5.7, the number of undo tablespaces is controlled by the `innodb_undo_tablespaces` configuration option. In MySQL 8.0, two default undo tablespaces are created when the MySQL instance is initialized, and additional undo tablespaces can be created using `CREATE UNDO TABLESPACE` syntax.

Two default undo tablespaces are created when the MySQL instance is initialized. Default undo tablespaces are created at initialization time to provide a location for rollback segments that must exist before SQL statements can be accepted. A minimum of two undo tablespaces is required to support automated truncation of undo tablespaces.

Prior to MySQL 8.0.23, the initial size of an undo tablespace depends on the `innodb_page_size` value.
As of MySQL 8.0.23, the initial undo tablespace size is normally 16MiB.


### Init Undo Tablespaces

srv_start() -> srv_undo_tablespaces_init() -> srv_undo_tablespaces_create() -> srv_undo_tablespace_create()


```c
// trx0purge.h
/** An undo::Tablespace object is used to easily convert between
undo_space_id and undo_space_num and to create the automatic file_name
and space name.  In addition, it is used in undo::Tablespaces to track
the trx_rseg_t objects in an Rsegs vector. So we do not allocate the
Rsegs vector for each object, only when requested by the constructor. */
struct Tablespace {
 /** ... **/
 private:
  /** Undo Tablespace ID. */
  space_id_t m_id;

  /** Undo Tablespace number, from 1 to 127. This is the
  7-bit number that is used in a rollback pointer.
  Use id2num() to get this number from a space_id. */
  space_id_t m_num;

  /** The tablespace name, auto-generated when needed from
  the space number. */
  char *m_space_name;

  /** The tablespace file name, auto-generated when needed
  from the space number. */
  char *m_file_name;

  /** The tablespace log file name, auto-generated when needed
  from the space number. */
  char *m_log_file_name;

  /** List of rollback segments within this tablespace.
  This is not always used. Must call init_rsegs to use it. */
  Rsegs *m_rsegs;
};
```

### Rollback Segment


```
srv_start() -> trx_rseg_adjust_rollback_segments() -> trx_rseg_create() 

                                                   -> trx_rseg_mem_create()
```

rollback segment memory object

```c
/** The rollback segment memory object */
struct trx_rseg_t {
  /*--------------------------------------------------------*/
  /** rollback segment id == the index of its slot in the trx
  system file copy */
  ulint id;

  /** mutex protecting the fields in this struct except id,space,page_no
  which are constant */
  RsegMutex mutex;

  /** space ID where the rollback segment header is placed */
  space_id_t space_id;

  /** page number of the rollback segment header */
  page_no_t page_no;

  /** page size of the relevant tablespace */
  page_size_t page_size;

  /** maximum allowed size in pages */
  ulint max_size;

  /** current size in pages */
  ulint curr_size;

  /*--------------------------------------------------------*/
  /* Fields for update undo logs */
  /** List of update undo logs */
  UT_LIST_BASE_NODE_T(trx_undo_t) update_undo_list;

  /** List of update undo log segments cached for fast reuse */
  UT_LIST_BASE_NODE_T(trx_undo_t) update_undo_cached;

  /*--------------------------------------------------------*/
  /* Fields for insert undo logs */
  /** List of insert undo logs */
  UT_LIST_BASE_NODE_T(trx_undo_t) insert_undo_list;

  /** List of insert undo log segments cached for fast reuse */
  UT_LIST_BASE_NODE_T(trx_undo_t) insert_undo_cached;

  /*--------------------------------------------------------*/

  /** Page number of the last not yet purged log header in the history
  list; FIL_NULL if all list purged */
  page_no_t last_page_no;

  /** Byte offset of the last not yet purged log header */
  ulint last_offset;

  /** Transaction number of the last not yet purged log */
  trx_id_t last_trx_no;

  /** TRUE if the last not yet purged log needs purging */
  ibool last_del_marks;

  /** Reference counter to track rseg allocated transactions. */
  std::atomic<ulint> trx_ref_count;
};
```

### Truncate

trx_undo_truncate_tablespace() -> fil_truncate_tablespace()


## purge


/** Start purge threads. During upgrade we start
purge threads early to apply purge. */
void srv_start_purge_threads() -> srv_purge_coordinator_thread() -> srv_do_purge() -> trx_purge()


```c

/* the number of pages to purge in one batch */
ulong srv_purge_batch_size = 20

ulint trx_purge(){
    // ...
    trx_sys->mvcc->clone_oldest_view(&purge_sys->view);
    
    /* Fetch the UNDO recs that need to be purged. */
    n_pages_handled = trx_purge_attach_undo_recs(n_purge_threads, batch_size);
 
    /* Submit the tasks to the work queue if n_pages_handled > 1. */
    
 }

```


## References
1. [InnoDB 事务分析-Undo Log](https://www.leviathan.vip/2019/02/14/InnoDB%E7%9A%84%E4%BA%8B%E5%8A%A1%E5%88%86%E6%9E%90-Undo-Log/)
2. [MySQL · 引擎特性 · InnoDB undo log 漫游](http://mysql.taobao.org/monthly/2015/04/01/)