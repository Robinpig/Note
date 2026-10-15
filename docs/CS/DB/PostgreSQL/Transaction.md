## Introduction

PostgreSQL 默认隔离级别为 Read Committed，提供完整的 ACID 与四级隔离。事务子系统由"日志管理器（CLOG/XLOG）+ 锁管理器（PGPROC）"两层构成，任何 SQL 都必须在事务中执行（单条语句即隐式事务）。本文覆盖隔离级别、子事务（SAVEPOINT）、双状态机、提交流程与 CLOG。

| 项 | 值 |
| :--- | :--- |
| 版本基线 | PostgreSQL 18 |
| 核实日期 | 2026-10-15 |

## Isolation Levels

| 隔离级别 | 现象 |
| :--- | :--- |
| Read Uncommitted | 等价 Read Committed（PG 不会读到未提交数据） |
| Read Committed | 语句级快照，可能不可重复读/幻读 |
| Repeatable Read | 事务级快照 |
| Serializable | 基于 SSI（Serializable Snapshot Isolation） |

## Subtransaction

> [!NOTE]
>
> 存储引擎只有 WAL 没有 undo log——子事务通过分配一个新的事务 ID 实现，子事务可继续创建子事务，构成树状结构。

`pg_subtrans`（共享子事务状态）与 Xact 嵌套栈维护父-子关系。SAVEPOINT、嵌套过程、PL/pgSQL 异常处理、JDBC 嵌套保存点都会创建子事务。

> [!WARNING]
>
> JDBC 驱动 `autosave` 需同时配置 `cleanup_savepoints`，否则每条语句前后插入 SAVEPOINT/RELEASE 会频繁落盘 `pg_subtrans` 引起性能问题；指定 `cleanup_savepoints` 让驱动在语句结束后一次性删除。

## Dual State Machine

PG 用两个独立状态机分别管理"语法块"与"底层事务状态"：

**上层 TBlockState**（`tcopprot.h`）：`TBLOCK_DEFAULT`/`TBLOCK_BEGIN`/`TBLOCK_INPROGRESS`/`TBLOCK_SUBBEGIN`/`TBLOCK_ABORT` 等。

**底层 TransState**（`xact.h`）：`TRANS_DEFAULT`/`TRANS_START`/`TRANS_INPROGRESS`/`TRANS_COMMIT`/`TRANS_ABORT`/`TRANS_PREPARE`。

## TransactionStateData

```c
typedef struct TransactionStateData {
    FullTransactionId fullTransactionId;  // 64bit: XID(32) + epoch(32)
    SubTransactionId  subTransactionId;
    TransState        state;
    TBlockState       blockState;
    int               nestingLevel;       // 嵌套深度（顶层=1）
    TransactionId    *childXids;          // 已提交子事务 XID 数组
    struct TransactionStateData *parent;
    ...
} TransactionStateData;
```

> [!NOTE]
>
> 事务"真正"开始并不是 `StartTransaction`，而是第一条 DML 执行时：`heap_update` 写入前调用 `GetCurrentTransactionId()` → `AssignTransactionId()` 才分配 XID。只读事务可能全程不分配 XID。

## CommitTransaction

调用链：`exec_simple_query → finish_xact_command → CommitTransactionCommand → CommitTransaction`。提交中以 `TRANS_INPROGRESS → TRANS_COMMIT` 切换，关键步骤：

1. `RecordTransactionCommit` → 写 WAL（`XactLogCommitRecord`）→ `XLogFlush` 刷盘
2. `TransactionIdSetTreeStatus` → 在 CLOG 写提交状态
3. `ProcArrayEndTransaction` → 更新全局共享结构
4. `AtEOXact_*` 系列收尾 → `CleanupTransaction` 重置状态

## CLOG

CLOG（`src/backend/access/transam/clog.c`）记录 xid 提交状态，每 XID 占 2 bit：

| 值 | 含义 |
| :--- | :--- |
| 0x00 | IN_PROGRESS |
| 0x01 | COMMITTED |
| 0x02 | ABORTED |
| 0x03 | SUB_COMMITTED |

文件在 `pg_xact/`，写状态需 `XactSLRULock`（页级 SLRU 锁，是热点）。CLOG 必须先于数据页 fsync——可见性判定依赖它。

## Two-Phase Commit

`twophase.c` 实现 `PREPARE TRANSACTION`：提交前把事务状态写入 `pg_twophase/`，崩溃后可从 WAL 恢复并继续提交/回滚。用于跨数据源的分布式事务协调（需应用层或外部事务管理器驱动）。

## Links

- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)
- [PostgreSQL Internals](/docs/CS/DB/PostgreSQL/Internals.md)
- [MVCC](/docs/CS/DB/PostgreSQL/MVCC.md)
- [WAL](/docs/CS/DB/PostgreSQL/WAL.md)
- [Lock](/docs/CS/DB/PostgreSQL/Lock.md)
- [MySQL Transaction](/docs/CS/DB/MySQL/Transaction.md)

## References

1. [PostgreSQL 官方文档: Transaction Isolation](https://www.postgresql.org/docs/current/transaction-iso.html)
2. [PostgreSQL 官方文档: Explicit Locking](https://www.postgresql.org/docs/current/explicit-locking.html)
3. [MySQL Transaction](/docs/CS/DB/MySQL/Transaction.md)
