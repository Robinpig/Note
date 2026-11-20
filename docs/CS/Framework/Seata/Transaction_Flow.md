# Transaction Flow

## Introduction

以默认 AT 模式拆解一次全局事务的全链路：从 `@GlobalTransactional` 拦截，到 TM 开全局事务、RM 注册分支并本地提交、TC 二阶段下发。传输层、TC 状态机与 RM/AT 资源细节分别见 [RPC Transport](/docs/CS/Framework/Seata/RPC_Transport.md)、[TC Coordinator](/docs/CS/Framework/Seata/TC_Coordinator.md)、[AT and Undo Log](/docs/CS/Framework/Seata/AT_UndoLog.md)。

> 版本基线：apache/seata **v2.7.0**。以下片段均取自该 tag。

## End-to-End Sequence (AT)

```sequence
Title: Seata AT 全局事务链路
App->TM: TransactionalTemplate.execute
TM->TC: GlobalBeginRequest
TC-->TM: XID（TC 端 GlobalSession 构造时生成）
TM->App: RootContext.bind(XID)
App->RM: 执行业务 SQL（携带 XID）
RM->RM: before-image / 业务 SQL / after-image / 组装 undo_log
RM->TC: BranchRegisterRequest（lockKeys = 表名:主键值）
TC->TC: 获取全局锁（LockManager）
TC-->RM: branchId
RM->RM: flushUndoLogs + 本地提交（业务数据与 undo_log 同事务）
App->TM: 业务返回，commit
TM->TC: GlobalCommitRequest
TC->TC: close + 释放全局锁 + asyncCommit
TC->RM: BranchCommitRequest（删 undo_log）
RM->RM: AsyncWorker 批量删 undo_log
TC-->TM: GlobalStatus.Committed
```

## Phase 1 Begin (TM)

Spring 把 `@GlobalTransactional` 织成 Advisor；调用进入 `TransactionalTemplate.execute()`，只有 `Launcher` 角色真正向 TC 发 begin：

```java
// 2. If the tx role is 'GlobalTransactionRole.Launcher', send the request of beginTransaction to TC,
//    else do nothing. Of course, the hooks will still be triggered.
beginTransaction(txInfo, tx);
```

TC 侧 `DefaultCoordinator.doGlobalBegin` 收到请求后调 `core.begin`，把返回的 XID 塞进 response：

```java
protected void doGlobalBegin(GlobalBeginRequest request, GlobalBeginResponse response, RpcContext rpcContext)
        throws TransactionException {
    response.setXid(core.begin(
            rpcContext.getApplicationId(),
            rpcContext.getTransactionServiceGroup(),
            request.getTransactionName(),
            request.getTimeout()));
}
```

返回后 TM 侧 `RootContext.bind(xid)`，后续同一线程的 RM 调用都能取到。嵌套 `@GlobalTransactional` 的场景由 `Propagation.REQUIRED` + `getCurrentOrCreate()` 处理：已有 XID 时返回 `Participant`，其 begin/commit/rollback 均为 no-op。

## Phase 1 Branch Execute (RM / AT)

在 XID 绑定的线程里执行业务 SQL，经 `DataSourceProxy → ConnectionProxy → StatementProxy → ExecuteTemplate.execute()` 拦截。关键在于**分支注册与落 undo_log 都在 `commit()` 时刻**，`doCommit()` 按上下文分三路：

```java
private void doCommit() throws SQLException {
    if (context.inGlobalTransaction()) {
        processGlobalTransactionCommit();
    } else if (context.isGlobalLockRequire()) {
        processLocalCommitWithGlobalLocks();
    } else {
        targetConnection.commit();
    }
}
```

全局事务分支走 `processGlobalTransactionCommit`：**先 register（占全局锁），再 flush undo_log，最后本地 commit**——三者顺序是理解 AT 一致性的关键：

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

`register()` 把 `lockKeys`（`表名:主键值`）发给 TC，TC 在此刻获取全局锁；且只有存在 undo_log 且存在 lockKey 时才注册（纯 SELECT 不注册分支）：

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

**写隔离**：提交前拿不到全局锁不能本地提交，冲突抛 `LockConflictException` 由 RM 重试。**读隔离**：只有 `SELECT ... FOR UPDATE` 在本地执行后向 TC 校验全局锁，普通 `SELECT` 不查全局锁。

## Phase 2 Commit (TC to RM)

TM 调 `GlobalCommitRequest` → TC `DefaultCore.commit()`。先 `close()` 禁止再注册分支，再按 `canBeCommittedAsync()` 决定走异步提交（`AsyncCommitting`）还是同步 `Committing`；随后立即 `clean()` 释放全局锁，给 TM 返回：

```java
boolean shouldCommit = SessionHolder.lockAndExecute(globalSession, () -> {
    boolean shouldCommitNow = false;
    if (globalSession.getStatus() == GlobalStatus.Begin) {
        // Highlight: Firstly, close the session, then no more branch can be registered.
        globalSession.close();
        if (globalSession.canBeCommittedAsync()) {
            globalSession.asyncCommit();
            MetricsPublisher.postSessionDoneEvent(globalSession, GlobalStatus.Committed, false, false);
        } else {
            globalSession.changeGlobalStatus(GlobalStatus.Committing);
            shouldCommitNow = true;
        }
        // clean session after changing status successfully.
        globalSession.clean();
    }
    return shouldCommitNow;
});
```

异步提交由 `handleAsyncCommitting` 调度线程推进，对每个分支发 `BranchCommitRequest`；RM `branchCommit` 只把 `Phase2Context` 入队就返回，`AsyncWorker` 后台批量删 undo_log。

> 设计要点：AT 一阶段已本地提交真实数据，二阶段 commit **不需要回退任何数据，只是删 undo_log**，故可 fire-and-forget + 重试。所以「TM 收到 Committed」≠「undo_log 已删除」。

## Phase 2 Rollback (TC to RM)

TM 调 `GlobalRollbackRequest` → TC `DefaultCore.rollback()`：`close()` → `Rollbacking` → `doGlobalRollback()`：

```java
boolean shouldRollBack = SessionHolder.lockAndExecute(globalSession, () -> {
    globalSession.close(); // Highlight: Firstly, close the session, then no more branch can be registered.
    if (globalSession.getStatus() == GlobalStatus.Begin) {
        globalSession.changeGlobalStatus(GlobalStatus.Rollbacking);
        return true;
    }
    return false;
});
if (!shouldRollBack) {
    return globalSession.getStatus();
}
boolean rollbackSuccess = doGlobalRollback(globalSession, false);
```

`doGlobalRollback` **逆序遍历分支**（`getReverseSortedBranches()`）发 `BranchRollbackRequest`，跳过 `PhaseOne_Failed`/`PhaseOne_PrepareFailed` 的分支；Saga 走专属 Core：

```java
if (globalSession.isSaga()) {
    success = getCore(BranchType.SAGA).doGlobalRollback(globalSession, retrying);
} else {
    List<BranchSession> branchSessions = globalSession.getReverseSortedBranches();
    Boolean result = SessionHelper.forEach(
            branchSessions,
            branchSession -> {
                BranchStatus currentBranchStatus = branchSession.getStatus();
                if (currentBranchStatus == BranchStatus.PhaseOne_Failed
                        || currentBranchStatus == BranchStatus.PhaseOne_PrepareFailed) {
                    SessionHelper.removeBranch(globalSession, branchSession, !retrying);
                    return CONTINUE;
                }
                // ... branchRollback(globalSession, branchSession)
```

RM `UndoLogManager.undo()` 用 `undo_log` 反向补偿（INSERT↔DELETE、UPDATE 反向），并做幂等校验：当前数据等于 afterImage 或 beforeImage 则跳过，否则抛 `SQLUndoDirtyException`。失败/超时进入 `RollbackRetrying`，由 `handleRetryRollbacking` 重试，超过重试窗口转 `RollbackFailed`（需人工介入）。详见 [AT and Undo Log](/docs/CS/Framework/Seata/AT_UndoLog.md)。

## Links
- [Seata](/docs/CS/Framework/Seata/Seata.md)
- [Architecture](/docs/CS/Framework/Seata/Architecture.md)
- [RPC Transport](/docs/CS/Framework/Seata/RPC_Transport.md)
- [TC Coordinator](/docs/CS/Framework/Seata/TC_Coordinator.md)
- [AT and Undo Log](/docs/CS/Framework/Seata/AT_UndoLog.md)
- [Global Lock](/docs/CS/Framework/Seata/Global_Lock.md)

## References
- Apache Seata source (v2.7.0): https://github.com/apache/seata/tree/v2.7.0
