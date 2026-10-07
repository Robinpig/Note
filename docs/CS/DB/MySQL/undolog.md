## Introduction

An undo log is a collection of undo log records associated with a **single read-write transaction**. 
An undo log record contains information about how to undo the latest change by a transaction to a [clustered index](/docs/CS/DB/MySQL/Index.md?id=clustered-and-secondary-indexes) record. 
If another transaction needs to see the original data as part of a consistent read operation, the unmodified data is retrieved from undo log records. 
Undo logs exist within `undo log segments`, which are contained within `rollback segments`. 
Rollback segments reside in `undo tablespaces` and in the `global temporary tablespace`.

These undo logs are not redo-logged, as they are not required for crash recovery. 
They are used only for rollback while the server is running. This type of undo log benefits performance by avoiding redo logging I/O.

What is undo log for:

1. [Atomicity](/docs/CS/DB/MySQL/Transaction.md?id=innodb-and-the-acid-model)
2. [MVCC](/docs/CS/DB/MySQL/Transaction.md?id=mvcc)

| 项 | 值 |
| :--- | :--- |
| 正文默认版本 | MySQL 9.7.x LTS（最新 9.7.3，2026-08-18） |
| 源码核实基线 | tag `mysql-9.7.2` |
| 次要兼容目标 | 8.4.x LTS |
| 已停止支持 | 8.0（EOL 2026-04-30）、5.7（EOL 2023-10） |
| 核实日期 | 2026-10-07 |

Each undo tablespace and the global temporary tablespace individually support a maximum of **128** rollback segments.
The number of transactions that a rollback segment supports depends on the number of undo slots in the rollback segment and the number of undo logs required by each transaction.((InnoDB Page Size / 16))

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

```c
struct trx_undo_t {
  ulint id;        /*!< undo log slot number within the
                   rollback segment */
  ulint type;      /*!< TRX_UNDO_INSERT or
                   TRX_UNDO_UPDATE */
  ulint state;     /*!< state of the corresponding undo log
                   segment */
  bool del_marks;  /*!< relevant only in an update undo
                    log: this is true if the transaction may
                    have delete marked records, because of
                    a delete of a row or an update of an
                    indexed field; purge is then
                    necessary; also true if the transaction
                    has updated an externally stored
                    field */
  trx_id_t trx_id; /*!< id of the trx assigned to the undo
                   log */
  XID xid;         /*!< X/Open XA transaction
                   identification */
  ulint flag;      /*!< flag for current transaction XID and GTID.
                   Persisted in TRX_UNDO_FLAGS flag of undo header. */
};
```

## Undo Tablespaces

Undo tablespaces contain undo logs, which are collections of records containing information about how to undo the latest change by a transaction to a clustered index record.

Two default undo tablespaces are created when the MySQL instance is initialized.
Default undo tablespaces are created at initialization time to provide a location for rollback segments that must exist before SQL statements can be accepted.

A MySQL instance supports up to **127** undo tablespaces including the two default undo tablespaces created when the MySQL instance is initialized.

### Version Coordinates

undo 表空间「数量由谁决定」在四条版本线上都不一样，是最容易写错的一处：

| 版本线 | 数量由什么决定 |
| :--- | :--- |
| 5.6 / 5.7 | `innodb_undo_tablespaces`（5.6 起 rollback segment 才可放进独立 undo 表空间） |
| 8.0 | 初始化时固定创建 2 个默认 undo 表空间，追加改用 `CREATE UNDO TABLESPACE`；`innodb_undo_tablespaces` 已标记 Deprecated |
| 8.4 LTS | 同 8.0；`innodb_undo_tablespaces` 仍存在（默认 2、最小 2、最大 127）且仍标记 Deprecated |
| 9.7 LTS | **`innodb_undo_tablespaces` 不再是配置项**——9.7.2 源码 `handler/ha_innodb.cc` 里没有该 sysvar，只剩 `innodb_undo_tablespaces_total` / `_implicit` / `_explicit` 三个状态计数器；数量只能用 DDL 管理 |

上限与默认个数在 9.7 是编译期常量：`constexpr size_t FSP_MAX_UNDO_TABLESPACES = 127;`（`include/fsp0types.h:408`）、`constexpr size_t FSP_IMPLICIT_UNDO_TABLESPACES = 2;`（`:413`，注释直接点名这 2 个是 `undo_001` 与 `undo_002`，并说明它们计入 127 的上限）。

9.7 的默认 undo 表空间数据文件名为 `undo_001` 与 `undo_002`，数据字典中的表空间名是 `innodb_undo_001` 与 `innodb_undo_002`；创建位置由 `innodb_undo_directory` 决定，未设置时落在 data directory。额外表空间在运行时用 `CREATE UNDO TABLESPACE tablespace_name ADD DATAFILE 'file_name.ibu'` 创建——**扩展名必须是 `.ibu`**，且不允许相对路径；不再需要时用 `DROP UNDO TABLESPACE` 删除。undo 表空间初始大小通常为 16MiB（自 8.0.23 起），由 truncate 生成的新表空间可能不同。

### Init Undo Tablespaces

srv_start() -> srv_undo_tablespaces_init() -> srv_undo_tablespaces_create() -> srv_undo_tablespace_create()

```c
// include/trx0purge.h:308-312
/** An undo::Tablespace object is used to easily convert between
undo_space_id and undo_space_num and to create the automatic file_name
and space name.  In addition, it is used in undo::Tablespaces to track
the trx_rseg_t objects in an Rsegs vector. So we do not allocate the
Rsegs vector for each object, only when requested by the constructor. */
struct Tablespace {
  ...
 private:
  /** Undo Tablespace ID. */
  space_id_t m_id;

  /** True if this undo tablespace was implicitly created when
  this instance started up. False if it pre-existed. */
  bool m_new;

  /** The tablespace name, auto-generated when needed from
  the space number. */
  char *m_space_name;

  /** The tablespace file name, auto-generated when needed
  from the space number. */
  char *m_file_name;

  /** The truncation log file name, auto-generated when needed
  from the space number and the srv_undo_dir. */
  char *m_log_file_name;

  /** The old truncation log file name, auto-generated when needed
  from the space number and the srv_log_group_home_dir. */
  char *m_log_file_name_old;

  /** List of rollback segments within this tablespace.
  This is not always used. Must call init_rsegs to use it. */
  Rsegs *m_rsegs;
};
```

与 8.0 时代摘录的两处差异：

- **`m_num` 成员已不存在**。表空间号（回滚段指针里那个 1–127 的 7-bit 数）改为按需计算：`space_id_t num() { const auto n = undo::id2num(m_id); ... }`（`include/trx0purge.h:458-466`），`undo::id2num()` 在 `:226`。space_id 与 space_num 的映射是「从 `0xFFFFFFEF` 起按每组 127 个倒序分配」，`:205-220` 的注释给了换算表。
- 新增 `m_new`（区分启动时隐式创建与先前已存在）与 `m_log_file_name_old`（从旧的 `srv_log_group_home_dir` 找升级前的 truncate 日志文件），后者是就地升级路径的兼容痕迹。

### Rollback Segment

```text
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

purge 负责把不再被任何 ReadView 需要的 undo 记录真正清掉，并顺带回收 undo 表空间。9.7 的调用链：

```text
srv_start_purge_threads() -> srv_purge_coordinator_thread() -> srv_do_purge() -> trx_purge()
```

`srv_purge_coordinator_thread()` 在 `srv/srv0srv.cc:3032`，`srv_do_purge()` 在 `:2845`，实际提交点是 `trx_purge(n_use_threads, srv_purge_batch_size, do_truncate)`（`:2904`）。

```c
// srv/srv0srv.cc:502-503
/* the number of pages to purge in one batch */
ulong srv_purge_batch_size = 20;

// handler/ha_innodb.cc:22317-22322
static MYSQL_SYSVAR_ULONG(
    purge_batch_size, srv_purge_batch_size, PLUGIN_VAR_OPCMDARG,
    "Number of UNDO log pages to purge in one batch from the history list.",
    nullptr, nullptr, 300, /* Default setting */
    1,                     /* Minimum value */
    5000, 0);              /* Maximum value */
```

⚠️ 又一例「C++ 全局初值 ≠ 默认值」：`srv_purge_batch_size` 的进程初值是 20，而 `innodb_purge_batch_size` 的**生效默认值是 300**（范围 1–5000），取自 sysvar 宏的第 7 个参数。旧资料里「一次 purge 20 页」的说法已经过时。

```c
// trx/trx0purge.cc:2394-2400
/** This function runs a purge batch.
 @return number of undo log pages handled in the batch */
ulint trx_purge(ulint n_purge_threads, /*!< in: number of purge tasks
                                       to submit to the work queue */
                ulint batch_size,      /*!< in: the maximum number of records
                                       to purge in one batch */
                bool truncate)         /*!< in: truncate history if true */
```

旧版摘录把 `trx_sys->mvcc->clone_oldest_view(&purge_sys->view)` 直接写在 `trx_purge()` 体内，9.7 已把它收进 `trx_purge_update_oldest_needed()`（`trx/trx0purge.cc:252`，`clone_oldest_view` 调用在 `:254`）：purge view 的推进与「最低仍需保留的事务号」在同一个函数里一起更新，`trx_purge()` 只在取 undo 记录前调它一次，随后 `trx_purge_attach_undo_recs(n_purge_threads, batch_size)`（`:2421`）。

## Links

- [InnoDB Storage Engine](/docs/CS/DB/MySQL/InnoDB.md?id=innodb-on-disk-structures)
- [Transaction](/docs/CS/DB/MySQL/Transaction.md)
- [Redo Log](/docs/CS/DB/MySQL/redolog.md)
- [Tablespace](/docs/CS/DB/MySQL/tablespace.md)
- [Buffer Pool](/docs/CS/DB/MySQL/memory.md)

## References

- [MySQL 9.7 Reference Manual: Undo Logs](https://dev.mysql.com/doc/refman/9.7/en/innodb-undo-logs.html)
- [MySQL 9.7 Reference Manual: Undo Tablespaces](https://dev.mysql.com/doc/refman/9.7/en/innodb-undo-tablespaces.html)
- [InnoDB 事务分析-Undo Log](https://www.leviathan.vip/2019-02-14/InnoDB%E7%9A%84%E4%BA%8B%E5%8A%A1%E5%88%86%E6%9E%90-Undo-Log/)
- [MySQL · 引擎特性 · InnoDB undo log 漫游](http://mysql.taobao.org/monthly/2015-04-01/)
- [MySQL · 引擎特性· InnoDB之UNDO LOG介绍](http://mysql.taobao.org/monthly/2021-12-02/)
