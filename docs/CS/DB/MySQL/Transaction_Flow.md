## Introduction

事务从开启到落盘要穿过哪些函数，是 [Transaction](/docs/CS/DB/MySQL/Transaction.md) 那篇讲语义时略过的部分。
本页走源码：事务对象如何初始化、undo 与 redo 如何参与、prepare 与 commit 两阶段在 InnoDB 与 Server 之间
怎么分工，以及崩溃恢复时为什么能仅凭 redo 与 binlog 的状态组合判定一个事务的最终去向。


| 项 | 值 |
| :--- | :--- |
| 正文默认版本 | MySQL 9.7.x LTS（最新 9.7.3，2026-08-18） |
| 源码核实基线 | tag `mysql-9.7.2` |
| 次要兼容目标 | 8.4.x LTS |
| 已停止支持 | 8.0（EOL 2026-04-30）、5.7（EOL 2023-10） |
| 核实日期 | 2026-10-07 |

读本页前建议先看两篇：redo log 的格式与 checkpoint 在 [Redo Log](/docs/CS/DB/MySQL/redolog.md)，
binlog 的写入与刷盘在 [Binlog](/docs/CS/DB/MySQL/binlog.md)——两阶段提交正是夹在这两者之间的那道协议。
可见性判定用的 ReadView 属于 MVCC，已挪到 [MVCC](/docs/CS/DB/MySQL/Mvcc.md)。

## Transaction flow



When the transaction is first started:
1. A transaction ID (TRX_ID) is assigned and may be written to the highest transaction ID field in the TRX_SYS page. A record of the TRX_SYS page modification is redo logged if the field
2. A read view is created based on the assigned TRX_ID.


Record modification
Each time the UPDATE modifies a record:

Undo log space is allocated.
Previous values from record are copied to undo log.
Record of undo log modifications are written to redo log.
Page is modified in buffer pool; rollback pointer is pointed to previous version written in undo log.
Record of page modifications are written to redo log.
Page is marked as “dirty” (needs to be flushed to disk). Therefore the answer is yes.
Transaction commit
When the transaction is committed (implicitly or explicitly):

Undo log page state is set to “purge” (meaning it can be cleaned up when it’s no longer needed).
Record of undo log modifications are written to redo log.
Redo log buffer is flushed to disk (depending on the setting of innodb_flush_log_at_trx_commit).



System Columns

1. DATA_ROW_ID
2. DATA_TRX_ID
3. DATA_ROLL_PTR

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
3. [Rsegs](/docs/CS/DB/MySQL/Transaction.md)

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

If transaction involves insert then [truncate undo logs](/docs/CS/DB/MySQL/undolog.md?id=truncate).

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

  if (trx->rsegs.m_noredo.insert_undo != nullptr) {
    trx_undo_set_state_at_finish(trx->rsegs.m_noredo.insert_undo, &temp_mtr);
  }

  bool serialised = false;
  
  
  /* If transaction involves update then add rollback segments
  to purge queue. */

   /* Will set trx->no and will add rseg to purge queue. */
    serialised = trx_serialisation_number_get(trx, redo_rseg_undo_ptr,
                                              temp_rseg_undo_ptr)
  

  /* Update the latest MySQL binlog name and offset information
  in trx sys header only if MySQL binary logging is on and clone
  is has ensured commit order at final stage. */
  if (Clone_handler::need_commit_order()) {
    trx_sys_update_mysql_binlog_offset(trx, mtr);
  }

}



/** Set the transaction serialisation number.
 @return true if the transaction number was added to the serialisation_list. */
static bool trx_serialisation_number_get(
    trx_t *trx,                         /*!< in/out: transaction */
    trx_undo_ptr_t *redo_rseg_undo_ptr, /*!< in/out: Set trx
                                        serialisation number in
                                        referred undo rseg. */
    trx_undo_ptr_t *temp_rseg_undo_ptr) /*!< in/out: Set trx
                                        serialisation number in
                                        referred undo rseg. */
{
  bool added_trx_no;
  trx_rseg_t *redo_rseg = nullptr;
  trx_rseg_t *temp_rseg = nullptr;

  // ...

  /* If the rollack segment is not empty then the
  new trx_t::no can't be less than any trx_t::no
  already in the rollback segment. User threads only
  produce events when a rollback segment is empty. */
  if ((redo_rseg != nullptr && redo_rseg->last_page_no == FIL_NULL) ||
      (temp_rseg != nullptr && temp_rseg->last_page_no == FIL_NULL)) {
    TrxUndoRsegs elem;

    if (redo_rseg != nullptr && redo_rseg->last_page_no == FIL_NULL) {
      elem.insert(redo_rseg);
    }

    if (temp_rseg != nullptr && temp_rseg->last_page_no == FIL_NULL) {
      elem.insert(temp_rseg);
    }

    // ...

    purge_sys->purge_queue->push(std::move(elem));

    mutex_exit(&purge_sys->pq_mutex);

  } else {
    added_trx_no = trx_add_to_serialisation_list(trx);
  }

  return (added_trx_no);
}

```

## Links

- [Transaction](/docs/CS/DB/MySQL/Transaction.md)
- [Redo Log](/docs/CS/DB/MySQL/redolog.md)
- [Binlog](/docs/CS/DB/MySQL/binlog.md)
- [Undo Log](/docs/CS/DB/MySQL/undolog.md)
- [Mvcc](/docs/CS/DB/MySQL/Mvcc.md)
- [InnoDB](/docs/CS/DB/MySQL/InnoDB.md)

## References

1. [MySQL 9.7 Reference Manual: InnoDB and the ACID Model](https://dev.mysql.com/doc/refman/9.7/en/innodb-acid-model.html)
2. [MySQL Source Code Documentation: trx0trx.h](https://dev.mysql.com/doc/dev/mysql-server/latest/pages.html)
3. [MySQL 9.7 Reference Manual: Atomic Database DDL Statements](https://dev.mysql.com/doc/refman/9.7/en/ddl-atomic.html)
