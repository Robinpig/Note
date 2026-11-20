# AT and Undo Log

## Introduction

本笔记拆解 Seata **RM 侧 AT 模式**的资源实现：JDBC 数据源如何被代理、前后镜像与 `undo_log` 如何生成、二阶段如何用 `undo_log` 反向补偿。AT 是 Seata 默认模式，核心是"一阶段本地提交业务数据 + undo_log，二阶段靠 undo_log 补偿"，从而把两阶段拆成两个独立本地事务。

> 版本基线：apache/seata **v2.7.0**。以下片段均取自该 tag。链路总览见 [Transaction Flow](/docs/CS/Framework/Seata/Transaction_Flow.md)，全局锁见 [Global Lock](/docs/CS/Framework/Seata/Global_Lock.md)。

## Proxy Chain and Interception

`DataSourceProxy` → `ConnectionProxy` → `StatementProxy`/`PreparedStatementProxy` → `ExecuteTemplate.execute()`。`BaseTransactionalExecutor` 从 `RootContext` 取 XID 绑到连接，`AbstractDMLBaseExecutor` 执行 `beforeImage → 业务SQL → afterImage → prepareUndoLog`。

代理链在 `DataSourceProxy` 构造时完成 `registerResource` + 校验 `undo_log` 表 + 设置默认 `BranchType.AT`。只有全局事务线程（绑定了 XID）或显式要求全局锁时，SQL 才被 AT 拦截；否则原样执行。

## Before and After Image

| DML | before-image | after-image |
| :--- | :--- | :--- |
| UPDATE | `SELECT … FOR UPDATE`（持本地锁做快照） | 按 PK 反查（前像已持锁，不再 `FOR UPDATE`） |
| DELETE | 全列 `SELECT … FOR UPDATE` | 空 |
| INSERT | 空 | 解析 SQL/自增键得 PK 后反查 `SELECT …` |
| SELECT FOR UPDATE | 本地执行后 `checkLock` 向 TC 校验全局锁 | — |

`prepareUndoLog` 用命中行调 `buildLockKey()` 生成 `表名:主键值`，append 到 `ConnectionContext` 缓冲（按 savepoint 分段），与 undo_log 一起在 commit 时刻落地。

## Commit: Register, Flush, Local Commit

分支注册、undo_log 落盘、本地业务提交三者顺序在 `ConnectionProxy.processGlobalTransactionCommit()` 里被钉死——**先 register 占全局锁，再 flush undo_log 到当前物理连接，最后本地 commit**：

```java
private void processGlobalTransactionCommit() throws SQLException {
    try {
        register();
    } catch (TransactionException e) {
        recognizeLockKeyConflictException(e, context.buildLockKeys());
    }
    try {
        UndoLogManagerFactory.getUndoLogManager(this.getDbType()).flushUndoLogs(this);
        targetConnection.commit();
    } catch (Throwable ex) {
        LOGGER.error("process connectionProxy commit error: {}", ex.getMessage(), ex);
        report(false);
        throw new SQLException(ex);
    }
    if (IS_REPORT_SUCCESS_ENABLE) {
        report(true);
    }
    context.reset();
}
```

`register()` 有早退保护：只有同时存在 undo_log 和 lockKey 才注册分支（纯读事务不产生分支）：

```java
private void register() throws TransactionException {
    if (!context.hasUndoLog() || !context.hasLockKey()) {
        return;
    }
    Long branchId = DefaultResourceManager.get()
            .branchRegister(
                    BranchType.AT,
                    getDataSourceProxy().getResourceId(),
                    null,
                    context.getXid(),
                    context.getApplicationData(),
                    context.buildLockKeys());
    context.setBranchId(branchId);
}
```

**undo_log 结构**：`BranchUndoLog`（`xid + branchId + List<SQLUndoLog>`）是整条分支的回滚日志；`SQLUndoLog` 是单条 SQL 的 `sqlType + tableName + beforeImage + afterImage`。`ONLY_CARE_UPDATE_COLUMNS` 开启时只记录被更新列 + 主键。

## Phase 2 Commit: Async Delete

`branchCommit` 不删数据、只把 `Phase2Context` 入队，`AsyncWorker` 后台定时批量 `batchDeleteUndoLog`。即 AT 提交 = 异步清 undo_log，这是 `GlobalStatus.AsyncCommitting` 的由来。

## Phase 2 Rollback: Compensation

`AbstractUndoLogManager.undo()` 在一个**新开本地事务**里完成：查 `undo_log FOR UPDATE` → 解码 `BranchUndoLog` → 逆序遍历 `sqlUndoLogs` 调 `UndoExecutorFactory.getUndoExecutor(...).executeOn(...)` → 删 undo_log + 提交。

关键片段（逆序补偿 + 逐条执行）：

```java
List<SQLUndoLog> sqlUndoLogs = branchUndoLog.getSqlUndoLogs();
if (sqlUndoLogs.size() > 1) {
    Collections.reverse(sqlUndoLogs);
}
for (SQLUndoLog sqlUndoLog : sqlUndoLogs) {
    TableMeta tableMeta = TableMetaCacheFactory.getTableMetaCache(dataSourceProxy.getDbType())
            .getTableMeta(conn, sqlUndoLog.getTableName(), dataSourceProxy.getResourceId());
    sqlUndoLog.setTableMeta(tableMeta);
    AbstractUndoExecutor undoExecutor =
            UndoExecutorFactory.getUndoExecutor(dataSourceProxy.getDbType(), sqlUndoLog);
    undoExecutor.executeOn(connectionProxy);
}
```

反向 SQL 由 `buildUndoSQL()` 生成（PK 永远在 WHERE 末尾）：INSERT 的 undo = DELETE（用 afterImage），DELETE 的 undo = INSERT（用 beforeImage），UPDATE 的 undo = 反向 UPDATE（用 beforeImage 还原非主键列）。

### Idempotency and Dirty Check

`AbstractUndoExecutor.dataValidationAndGoOn()` 是幂等与脏数据校验的核心，三种判定：前后像相等→跳过；当前数据等于 beforeImage→跳过（可能已回滚）；当前既不等于 after 也不等于 before→抛 `SQLUndoDirtyException`：

```java
Result<Boolean> beforeEqualsAfterResult = DataCompareUtils.isRecordsEquals(beforeRecords, afterRecords);
if (beforeEqualsAfterResult.getResult()) {
    // no need continue undo.
    return false;
}

TableRecords currentRecords = queryCurrentRecords(conn);
Result<Boolean> afterEqualsCurrentResult = DataCompareUtils.isRecordsEquals(afterRecords, currentRecords);
if (!afterEqualsCurrentResult.getResult()) {
    Result<Boolean> beforeEqualsCurrentResult = DataCompareUtils.isRecordsEquals(beforeRecords, currentRecords);
    if (beforeEqualsCurrentResult.getResult()) {
        // no need continue undo.
        return false;
    } else {
        throw new SQLUndoDirtyException("Has dirty records when undo.");
    }
}
return true;
```

### GlobalFinished Fallback

`undo()` 末尾有一个关键兜底：若 `undo_log` 不存在（一阶段本地已提交但 undo_log 未写入，如业务超时），插入一条 `GlobalFinished` 状态的 undo_log 占位，防止其它进程的一阶段提交成功（对应 issue #489）：

```java
// If undo_log exists, it means that the branch transaction has completed the first phase,
// we can directly roll back and clean the undo_log.
// ... To ensure data consistency, we can insert an undo_log with GlobalFinished state
// to prevent the local transaction of the first phase of other programs from being correctly submitted.
if (exists) {
    deleteUndoLog(xid, branchId, conn);
    conn.commit();
} else {
    insertUndoLogWithGlobalFinished(xid, branchId, UndoLogParserFactory.getInstance(), conn);
    conn.commit();
}
```

`undo()` 循环还有一个 `SQLIntegrityConstraintViolationException` 重试分支：其它进程抢先插入 undo_log 时，重试回滚。

## Isolation

- **写隔离**：全局锁保护主键值（`表:pk`）；提交前 `branchRegister` 经 TC 占锁，冲突由 `ConnectionProxy.LockRetryPolicy` 重试。
- **读隔离**：只有 `SELECT ... FOR UPDATE` 在本地执行后向 TC 校验全局锁（`checkLock`）；普通 `SELECT` 不查全局锁，会读到其它全局事务未提交的中间态。需强读隔离用 `@GlobalLock` 或 `SELECT FOR UPDATE`。
- **`@GlobalLock` 独立路径**：`GlobalLockTemplate` 绑全局锁标记 → `ConnectionProxy.commit` 走 `processLocalCommitWithGlobalLocks`（checkLock 后本地提交），不参与全局事务但不绕过全局锁校验：

```java
private void processLocalCommitWithGlobalLocks() throws SQLException {
    checkLock(context.buildLockKeys());
    try {
        targetConnection.commit();
    } catch (Throwable ex) {
        throw new SQLException(ex);
    }
    context.reset();
}
```

## Links
- [Seata](/docs/CS/Framework/Seata/Seata.md)
- [Architecture](/docs/CS/Framework/Seata/Architecture.md)
- [Transaction Flow](/docs/CS/Framework/Seata/Transaction_Flow.md)
- [TC Coordinator](/docs/CS/Framework/Seata/TC_Coordinator.md)
- [Global Lock](/docs/CS/Framework/Seata/Global_Lock.md)
- [XA](/docs/CS/Framework/Seata/XA.md)

## References
- Apache Seata source (v2.7.0): https://github.com/apache/seata/tree/v2.7.0
- Seata issue #489 (undo_log GlobalFinished): https://github.com/apache/seata/issues/489
