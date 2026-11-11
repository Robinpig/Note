## Introduction

本笔记以**默认的 AT 模式**为例，做 Seata 一次全局事务的**全链路（源码级）拆解**：从 `@GlobalTransactional` 拦截，到 TM 开全局事务、RM 注册分支并本地提交、TC 二阶段提交/回滚下发。传输层、TC 内部状态机与 RM/AT 资源侧的源码细节分别由 RPC Transport、TC Coordinator、AT and Undo Log 各册展开。基座：apache/seata @ v2.7.0。

## End-to-End Sequence (AT)

```sequence
Title: Seata AT 全局事务链路
App->TM: TransactionalTemplate.execute
TM->TC: GlobalBeginRequest
TC-->TM: XID（由 TC 生成）
TM->App: RootContext.bind(XID)
App->RM: 执行业务 SQL（携带 XID）
RM->RM: before-image / 业务 SQL / after-image / 组装 undo_log
RM->TC: BranchRegisterRequest（lockKeys 为表名与主键值）
TC->TC: 获取全局锁（LockManager）
TC-->RM: branchId
RM->RM: flushUndoLogs + 本地提交（业务数据与 undo_log 同事务）
RM->TC: BranchReport（PhaseOne_Done）
App->TM: 业务返回，commit
TM->TC: GlobalCommitRequest
TC->TC: close session + 释放全局锁 + asyncCommit
TC->RM: BranchCommitRequest（删 undo_log）
RM->RM: AsyncWorker 批量删 undo_log
TC-->TM: GlobalStatus.Committed
```

## Phase 1 Begin (TM)

1. Spring 把 `@GlobalTransactional` 织成 Advisor；调用进入 `TransactionalTemplate.execute()`。
2. `GlobalTransactionContext.getCurrent()`：当前线程没有 XID → 创建 `Launcher` 角色的 `DefaultGlobalTransaction`。
3. `tx.begin(timeout, name)` → `TransactionManager.begin()` → 构造 `GlobalBeginRequest`，经 `TmNettyRemotingClient` 发往 TC。
4. **XID 由 TC 生成**（`DefaultCore.begin` 里 `XID.generateXID(transactionId)`），TM 端从不拼装 XID。
5. 返回后 `RootContext.bind(xid)`：XID 进入线程级上下文，后续同一线程的 RM 调用都能取到。

> 嵌套 `@GlobalTransactional` 不会新开事务：有 XID 时 `getCurrent()` 返回 `Participant`，其 begin/commit/rollback 均为 no-op，只有最外层 `Launcher` 真正驱动 TC。

## Phase 1 Branch Execute (RM / AT)

在 XID 绑定的线程里执行业务 SQL 时：

1. `DataSourceProxy` → `ConnectionProxy` → `StatementProxy` 把 SQL 路由到 `ExecuteTemplate.execute()`。
2. 仅当 `RootContext.getBranchType()==AT` 或要求全局锁时才拦截；否则原样执行，不参与 AT。
3. `BaseTransactionalExecutor` 从 `RootContext` 取 XID 绑到连接；`AbstractDMLBaseExecutor` 执行 `beforeImage → 业务SQL → afterImage → prepareUndoLog`。
4. 提交时 `ConnectionProxy.processGlobalTransactionCommit()`：
   - `register()`：构造 `BranchRegisterRequest`（携带 `lockKeys = 表名:主键值`），经 `RmNettyRemotingClient` 发往 TC。**TC 在此获取全局锁**。
   - `flushUndoLogs()`：把 `BranchUndoLog` 写入**当前物理连接**。
   - `targetConnection.commit()`：业务数据 + undo_log + （已通过 RPC 注册的）分支状态，**在同一个本地事务提交**。
5. 成功后 `report(true)` 上报 `BranchReportRequest(PhaseOne_Done)`。

**写隔离**：全局锁保护的是**主键值**（`表:pk`），不是任意行条件；提交前拿不到全局锁不能本地提交。
**读隔离**：只有 `SELECT ... FOR UPDATE` 会在本地执行后向 TC 校验全局锁（`checkLock`）；普通 `SELECT` 不查全局锁，会读到其它全局事务未提交的中间态——这是 AT 读隔离的固有边界。

## Phase 2 Commit (TC to RM)

1. TM 调 `GlobalCommitRequest` → TC `DefaultCore.commit()`。
2. TC 先 `globalSession.close()`（禁止再注册分支），`changeGlobalStatus(Committing/AsyncCommitting)`，**立即 `clean()` 释放全局锁**，给 TM 返回 `Committed`。
3. 真正的 branch commit 由 `handleAsyncCommitting` 调度线程异步推进：对每个分支发 `BranchCommitRequest`。
4. RM 收到 `BranchCommitRequest` → `DataSourceManager.branchCommit()` 仅把 `Phase2Context` 入队，**立即返回 `PhaseTwo_Committed`**；`AsyncWorker` 后台批量删 undo_log。

> 设计要点：AT 一阶段已本地提交真实数据，二阶段 commit **不需要回退任何数据，只是删 undo_log**，故可 fire-and-forget + 重试。所以「TM 收到 Committed」≠「undo_log 已删除」。

## Phase 2 Rollback (TC to RM)

1. TM 调 `GlobalRollbackRequest` → TC `DefaultCore.rollback()`：`close()` → `Rollbacking` → `doGlobalRollback()`。
2. 逆序遍历分支，发 `BranchRollbackRequest` 给每个 RM。
3. RM `DataSourceManager.branchRollback()` → `UndoLogManager.undo()`：
   - 用 `xid+branchId` 查 `undo_log FOR UPDATE`，解码 `BranchUndoLog`。
   - 逆序逐条用 `afterImage/beforeImage` **反向补偿**（INSERT 的 undo=DELETE，DELETE 的 undo=INSERT，UPDATE 的 undo=反向 UPDATE）。
   - **幂等校验**：当前数据 == `afterImage`（已被正确回滚）或 == `beforeImage`（原本没变）则跳过；既不等 after 也不等 before → 抛 `SQLUndoDirtyException`（脏数据）。
   - 若 `undo_log` 不存在（一阶段超时但本地已提交），插入一条 `GlobalFinished` 占位，防止其它进程的一阶段提交成功——关键正确性兜底。
4. 失败/超时进入 `RollbackRetrying`，由 `handleRetryRollbacking` 调度线程重试，直至终态或 `isRetryTimeout` 转 `RollbackFailed`（需人工介入）。

## Links
- [Seata](/docs/CS/Framework/Seata/Seata.md)
- [Architecture](/docs/CS/Framework/Seata/Architecture.md)
- [RPC Transport](/docs/CS/Framework/Seata/RPC_Transport.md)
- [TC Coordinator](/docs/CS/Framework/Seata/TC_Coordinator.md)
- [AT and Undo Log](/docs/CS/Framework/Seata/AT_UndoLog.md)

## References
- Apache Seata source (v2.7.0): https://github.com/apache/seata/tree/v2.7.0
