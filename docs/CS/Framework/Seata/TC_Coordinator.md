# TC Coordinator

## Introduction

本笔记拆解 Seata **TC（事务协调者，server 端）**的内部实现：入站分发、会话状态机、全局锁与二阶段提交/回滚，以及驱动重试的调度线程。会话持久化见 [TC Storage](/docs/CS/Framework/Seata/TC_Storage.md)，高可用见 [Raft HA](/docs/CS/Framework/Seata/Raft_HA.md)，传输层见 [RPC Transport](/docs/CS/Framework/Seata/RPC_Transport.md)。

> 版本基线：apache/seata **v2.7.0**。以下片段均取自该 tag。

## Inbound Dispatch

server 侧没有"一个 Handler 对应一种消息"的体系：所有事务类请求汇聚到 `ServerOnRequestProcessor` → `TransactionMessageHandler.onRequest()` → `request.handle()` → `AbstractTCInboundHandler` 的模板方法 → `DefaultCoordinator` 的 `doXxx`。

`DefaultCoordinator` 的 `doGlobalBegin` / `doGlobalCommit` / `doGlobalRollback` / `doBranchRegister` 都只是薄薄一层，把请求字段转给 `core`（`DefaultCore`）：

```java
protected void doGlobalBegin(GlobalBeginRequest request, GlobalBeginResponse response, RpcContext rpcContext)
        throws TransactionException {
    response.setXid(core.begin(
            rpcContext.getApplicationId(),
            rpcContext.getTransactionServiceGroup(),
            request.getTransactionName(),
            request.getTimeout()));
}

@Override
protected void doGlobalCommit(GlobalCommitRequest request, GlobalCommitResponse response, RpcContext rpcContext)
        throws TransactionException {
    MDC.put(RootContext.MDC_KEY_XID, request.getXid());
    response.setGlobalStatus(core.commit(request.getXid()));
}
```

```java
@Override
protected void doBranchRegister(
        BranchRegisterRequest request, BranchRegisterResponse response, RpcContext rpcContext)
        throws TransactionException {
    MDC.put(RootContext.MDC_KEY_XID, request.getXid());
    response.setBranchId(core.branchRegister(
            request.getBranchType(),
            request.getResourceId(),
            rpcContext.getClientId(),
            request.getXid(),
            request.getApplicationData(),
            request.getLockKey()));
}
```

入站消息与 `doXxx` 的映射：

| 消息 | `doXxx` | 说明 |
| :--- | :--- | :--- |
| `GlobalBeginRequest` | `doGlobalBegin` | 开全局事务、返回 XID |
| `GlobalCommitRequest` | `doGlobalCommit` | 全局提交 |
| `GlobalRollbackRequest` | `doGlobalRollback` | 全局回滚 |
| `GlobalStatusRequest` | `doGlobalStatus` | 查全局状态 |
| `GlobalReportRequest` | `doGlobalReport` | Saga 上报状态 |
| `BranchRegisterRequest` | `doBranchRegister` | 分支注册（含锁） |
| `BranchReportRequest` | `doBranchReport` | 分支状态上报 |
| `GlobalLockQueryRequest` | `doLockCheck` | 全局锁冲突查询 |

## Core Classes

| 类 | 职责 |
| :--- | :--- |
| `DefaultCoordinator` | 入站入口 + `doXxx` + 调度线程 |
| `DefaultCore` / `AbstractCore` / `ATCore` | 按 `BranchType` 分派的二阶段总控 |
| `GlobalSession` / `BranchSession` | 全局/分支会话，可持久化、可加锁 |
| `SessionManager` / `AbstractSessionManager` | 生命周期事件映射成 `LogOperation` 写 store |
| `LockManager` / `LockerManagerFactory` | 全局锁，后端 db/file/redis/raft |
| `TransactionStoreManager` + `SessionConverter` | 会话持久化（global/branch/lock DO） |

## Two-Phase Commit (AT)

`DefaultCore.commit` 用 `SessionHolder.lockAndExecute` 对会话加锁后改状态：**先 `close()` 禁止再注册分支**，再按 `canBeCommittedAsync()` 分流——能异步提交（AT）就 `asyncCommit()` 转 `AsyncCommitting`，否则转 `Committing` 同步提交；最后 `clean()` 释放全局锁：

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

真正的 branch commit 由 `handleAsyncCommitting` 调度线程推进。"Committed" ≠ "undo_log 已删除"——AT 一阶段已本地提交，二阶段 commit 只是删 undo_log。

## Two-Phase Rollback

`rollback` 同样先锁会话、`close()`、转 `Rollbacking`，再调 `doGlobalRollback(false)`：

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
return rollbackSuccess ? GlobalStatus.Rollbacked : globalSession.getStatus();
```

`doGlobalRollback` **逆序**遍历分支，`PhaseOne_Failed`/`PhaseOne_PrepareFailed` 的分支直接移除；返回 `PhaseTwo_Rollbacked` 移除分支，`PhaseTwo_RollbackFailed_Unretryable` 走 `endRollbackFailed`（终态需人工），其余进重试队列。重试界限用 `beginTime` 而非"状态维持时长"：

```java
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
            if (retrying && BranchStatus.STOP_RETRY.equals(currentBranchStatus)) {
                return CONTINUE;
            }
            // ... branchRollback -> switch on BranchStatus
```

## Scheduling Threads

`DefaultCoordinator.init()` 起 5 组 `scheduleAtFixedRate`：`retryRollbacking`、`retryCommitting`、`asyncCommitting`、`timeoutCheck`、`undoLogDelete`，每组都套 `SessionHolder.distributedLockAndExecute(key, func)` 保证多 TC 节点下扫描任务只跑一份：

```java
public void init() {
    retryRollbacking.scheduleAtFixedRate(
            () -> SessionHolder.distributedLockAndExecute(RETRY_ROLLBACKING, this::handleRetryRollbacking),
            0, CONFIG.getScheduledAtFixedRate(), TimeUnit.MILLISECONDS);
    retryCommitting.scheduleAtFixedRate(
            () -> SessionHolder.distributedLockAndExecute(RETRY_COMMITTING, this::handleRetryCommitting),
            0, CONFIG.getScheduledAtFixedRate(), TimeUnit.MILLISECONDS);
    asyncCommitting.scheduleAtFixedRate(
            () -> SessionHolder.distributedLockAndExecute(ASYNC_COMMITTING, this::handleAsyncCommitting),
            0, CONFIG.getScheduledAtFixedRate(), TimeUnit.MILLISECONDS);
    timeoutCheck.scheduleAtFixedRate(
            () -> SessionHolder.distributedLockAndExecute(TX_TIMEOUT_CHECK, this::timeoutCheck),
            0, CONFIG.getScheduledAtFixedRate(), TimeUnit.MILLISECONDS);
    undoLogDelete.scheduleAtFixedRate(
            () -> SessionHolder.distributedLockAndExecute(UNDOLOG_DELETE, this::undoLogDelete),
            0, CONFIG.getScheduledAtFixedRate(), TimeUnit.MILLISECONDS);
}
```

`handleRetryRollbacking` / `handleRetryCommitting` / `handleAsyncCommitting` 都调 `core.doGlobalXxx(session, true)` 推进；`timeoutCheck` 扫描超时会话转 `TimeoutRollbacking`；`undoLogDelete` 是向所有已注册 RM 发 `UndoLogDeleteRequest` 按 `saveDays` 清理过期日志——与"删当前事务 undo_log"是两件事。

## Links
- [Seata](/docs/CS/Framework/Seata/Seata.md)
- [Architecture](/docs/CS/Framework/Seata/Architecture.md)
- [Transaction Flow](/docs/CS/Framework/Seata/Transaction_Flow.md)
- [RPC Transport](/docs/CS/Framework/Seata/RPC_Transport.md)
- [TC Storage](/docs/CS/Framework/Seata/TC_Storage.md)
- [Global Lock](/docs/CS/Framework/Seata/Global_Lock.md)

## References
- Apache Seata source (v2.7.0): https://github.com/apache/seata/tree/v2.7.0
