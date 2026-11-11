## Introduction

本笔记拆解 Seata **TC（事务协调者，server 端）** 的内部实现（apache/seata @ v2.7.0）：启动装配、入站分发、会话状态机、全局锁、事务日志存储与二阶段提交/回滚。链路总览与传输层分别见 Transaction Flow、RPC Transport 两册。

## Startup and Wiring

`Server.start()` → `new NettyRemotingServer()` + `DefaultCoordinator.getInstance()`（Raft 模式返回 `RaftCoordinator`）→ `SessionHolder.init()` + `LockerManagerFactory.init()` → `coordinator.init()`（启动调度线程）→ `nettyRemotingServer.setHandler(coordinator)` → `init()` 时 `registerProcessor()` 把全部事务消息类型注册到 `ServerOnRequestProcessor`。

## Inbound Dispatch

server 侧**没有**传统的「一个 Handler 类对应一种消息」体系；统一汇聚到 `ServerOnRequestProcessor` → `TransactionMessageHandler.onRequest()` → `request.handle()` → `AbstractTCInboundHandler` 的 8 个 `handle(...)` 模板方法（每个调一个 `doXxx`，由 `DefaultCoordinator` 实现）：

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
| `DefaultCoordinator` | 入站入口 + 各 `doXxx` 实现 + 全部调度线程 |
| `DefaultCore` / `AbstractCore` / `ATCore` | 按 `BranchType` 分派的二阶段总控；`branchRegister` 含锁获取，`branchCommit`/`branchRollback` 向 RM 同步发请求 |
| `GlobalSession` / `BranchSession` | 全局/分支事务会话，可持久化、可加锁 |
| `SessionManager` / `AbstractSessionManager` | 把生命周期事件映射成 `LogOperation` 写 `TransactionStoreManager` |
| `LockManager` / `AbstractLockManager` / `LockerManagerFactory` | 全局锁；后端 db/file/redis/raft |
| `TransactionStoreManager` + `SessionConverter` | 会话持久化（global/branch/lock DO） |

## Two-Phase Commit (AT)

1. `DefaultCore.commit(xid)`：`findGlobalSession`；若 `isTimeout()` 直接转 `TimeoutRollbacking`。
2. `globalSession.close()`（**先于状态变更**，禁止再注册分支）→ `changeGlobalStatus(Committing/AsyncCommitting)` → `clean()` **立即释放全局锁** → 给 TM 返回 `Committed`。
3. 真正的 branch commit 由 `handleAsyncCommitting` 调度线程推进：对每个分支发 `BranchCommitRequest`（RM 收到即删 `undo_log`）。
4. 全部完成 → `SessionHelper.endCommitted`；失败进 `RetryCommitting` 被 `handleRetryCommitting` 重试。

> **「Committed」≠「undo_log 已删除」**：AT 一阶段已本地提交真实数据，二阶段 commit 只是删 `undo_log`，可 fire-and-forget + 重试。

## Two-Phase Rollback

1. `DefaultCore.rollback(xid)`：`close()` → `Rollbacking` → `doGlobalRollback()`。
2. **逆序**遍历分支，发 `BranchRollbackRequest` 给每个 RM（RM 用 `undo_log` 反向补偿）。
3. 返回 `PhaseTwo_Rollbacked` → `removeBranch`；返回 `PhaseTwo_RollbackFailed_Unretryable` → `endRollbackFailed`（终态，需人工）；失败/超时 → `queueToRetryRollback()`（`RollbackRetrying`）。
4. 重试界限用 `beginTime` 而非「状态维持时长」：`isRetryTimeout` 超过 `MAX_COMMIT/ROLLBACK_RETRY_TIMEOUT` 才转 `Failed`。

## Global Lock

- lockKey 形如 `tableName:pk1,pk2;tableName2:pk3`（`AbstractLockManager.collectRowLocks`）；`RowLock` 再拼成 `resourceId⌐tableName⌐pk` 作为 `lock_table.row_key` 唯一键。
- **只有 `BranchType.AT` 才真正获取锁**（`BranchSession.lock`：`if branchType==AT → lockManager.acquireLock`）。
- 全局锁保护的是「资源+表+主键」**行级锁**，保证不同全局事务对同一行互斥（AT 写隔离核心）。
- 后端：`DataBaseLocker` / `FileLocker` / `RedisLocker` / `RaftLockManager`（经 `LockerManagerFactory` SPI 装配）。

## Session Persistence

- 存储后端 db/file/redis/raft，对应 `global_table` / `branch_table` / `lock_table`（DO：`GlobalTransactionDO` / `BranchTransactionDO` / `LockDO`）。
- `AbstractSessionManager` 把 `onBegin/onAddBranch/onStatusChange/...` 映射成 `LogOperation`（ADD/UPDATE/REMOVE）写 `TransactionStoreManager`。
- 锁与分支**解耦存储**：锁在 `lock_table`，会话在 `global/branch_table`，共享同一数据源但由 `LockerManagerFactory` 与 `SessionManager` 分别管理。

## High Availability (Raft)

- `RaftCoordinator` 是 `DefaultCoordinator` 子类，仅额外做 leader 校验（`isPass` / `GROUP_PREVENT`），阻止非 leader 处理写请求。
- **仅 `SessionManager`（RaftSessionManager）与锁（RaftLockManager）走 Raft 复制**；Netty 收发、定时调度在各节点本地跑。
- Raft 模式下 follower 不本地写 session，靠状态机复制；只有 leader apply 后回调才在本地内存 `addGlobalSession`。
- `SessionHolder.distributedLockAndExecute` 保证多 TC/多线程下扫描任务只跑一份。

## Scheduling Threads

`DefaultCoordinator.init()` 启动：`retryCommitting`、`retryRollbacking`、`asyncCommitting`、`timeoutCheck`、`undoLogDelete`（5 个 `scheduleAtFixedRate`），以及 `handleCommittingByScheduled` / `handleRollbackingByScheduled` / `handleEndStatesByScheduled`（自驱动链式调度，延迟由 `timeToDeadSession()` 动态计算）。`undoLogDelete` 是向**所有已注册 RM 的 resourceId** 发 `UndoLogDeleteRequest` 按 `saveDays` 清理过期日志——与「删当前事务 undo_log」是两件事。

## Links
- [Seata](/docs/CS/Framework/Seata/Seata.md)
- [Architecture](/docs/CS/Framework/Seata/Architecture.md)
- [Transaction Flow](/docs/CS/Framework/Seata/Transaction_Flow.md)
- [RPC Transport](/docs/CS/Framework/Seata/RPC_Transport.md)
- [AT and Undo Log](/docs/CS/Framework/Seata/AT_UndoLog.md)

## References
- Apache Seata source (v2.7.0): https://github.com/apache/seata/tree/v2.7.0
