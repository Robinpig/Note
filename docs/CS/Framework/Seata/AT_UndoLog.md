## Introduction

本笔记拆解 Seata **RM 侧 AT 模式**的资源实现（apache/seata @ v2.7.0）：JDBC 数据源如何被代理、前后镜像与 `undo_log` 如何生成、二阶段如何用 `undo_log` 反向补偿。链路总览与全局锁 / TC 侧分别见 Transaction Flow、TC Coordinator 两册。

## Proxy Chain

`DataSourceProxy`（构造时 `registerResource` + 校验 `undo_log` 表 + `setDefaultBranchType(AT)`）→ `ConnectionProxy` → `StatementProxy` / `PreparedStatementProxy` → `ExecuteTemplate.execute()`。

- `ExecuteTemplate` 先判定：仅当 `RootContext.getBranchType()==AT` 或要求全局锁才拦截，否则原样执行。
- `BaseTransactionalExecutor` 从 `RootContext` 取 XID 绑到连接。
- `AbstractDMLBaseExecutor`：`beforeImage → 执行业务SQL → afterImage → prepareUndoLog`。

## Before and After Image

| DML | before-image | after-image |
| :--- | :--- | :--- |
| UPDATE | `SELECT … WHERE pk IN (…) FOR UPDATE`（持本地锁做快照） | 按 PK 反查 `SELECT …`（前像已持锁，不再 `FOR UPDATE`） |
| DELETE | 全列 `SELECT … FOR UPDATE` | 空 |
| INSERT | 空 | 解析 SQL/自增键得 PK，反查 `SELECT …` |
| SELECT FOR UPDATE | 本地执行后 `checkLock` 向 TC 校验全局锁 | — |

`prepareUndoLog`：用命中的行（DELETE 用 before，其余用 after）调 `buildLockKey()` 生成 `表名:主键值`，`appendLockKey` + `appendUndoLog` 写入 `ConnectionContext` 缓冲（按 savepoint 分段）。

## undo_log Structure

- `BranchUndoLog`：`xid + branchId + List<SQLUndoLog>`，整条分支的回滚日志。
- `SQLUndoLog`：单条 SQL 的 `sqlType + tableName + beforeImage(TableRecords) + afterImage(TableRecords)`。
- 一阶段 `flushUndoLogs()` 把 `BranchUndoLog` 编码后写入**当前物理连接**；与业务数据、分支注册所需本地状态在**同一个本地事务提交**。
- `ONLY_CARE_UPDATE_COLUMNS` 开启时，`undo_log` 仅记录被更新列 + 主键（+ `on update` 列），回滚 SQL 也只还原这些列。

## Phase 2 Commit

`branchCommit` 不删数据、只把 `Phase2Context` 入队，`AsyncWorker` 后台（1s 定时）批量 `batchDeleteUndoLog` 真正删除。即 AT 提交 = 异步清 `undo_log`。

## Phase 2 Rollback (Compensation)

`UndoLogManager.undo()`（一条新开本地事务）：
1. `SELECT * FROM undo_log WHERE branch_id=? AND xid=? FOR UPDATE`，解码 `BranchUndoLog`。
2. 逆序遍历 `sqlUndoLogs`，逐条 `UndoExecutorFactory.getUndoExecutor(...).executeOn(connectionProxy)`。
3. 反向 SQL（PK 永远在 WHERE 末尾）：INSERT 的 undo = **DELETE**（用 afterImage）；DELETE 的 undo = **INSERT**（用 beforeImage）；UPDATE 的 undo = **反向 UPDATE**（用 beforeImage 还原非主键列）。
4. 回滚成功 → 删 `undo_log` + 提交。

**幂等校验**（`AbstractUndoExecutor.dataValidationAndGoOn`）：当前数据 == `afterImage`（已被正确回滚）或 == `beforeImage`（原本没变）则跳过；既不等 after 也不等 before → 抛 `SQLUndoDirtyException`（脏数据）。

**兜底**：`undo_log` 不存在（一阶段超时但本地已提交）时，插入一条 `GlobalFinished` 状态占位，防止其它进程的一阶段提交成功（issue #489）。

## Isolation

- **写隔离**：全局锁保护主键值（`表:pk`）；提交前 `branchRegister` 经 TC 占锁，冲突抛 `LockConflictException`，由 `ConnectionProxy.LockRetryPolicy` 重试。
- **读隔离**：只有 `SELECT … FOR UPDATE` 在本地执行后向 TC 校验全局锁（`checkLock`）；**普通 `SELECT` 不查全局锁**，依赖本地 MVCC/快照——会读到其它全局事务未提交的中间态。需要强读隔离时用 `@GlobalLock` 或 `SELECT FOR UPDATE`。
- **`@GlobalLock` 独立路径**：`GlobalLockTemplate` 绑全局锁标记 → `ConnectionProxy.commit` 走 `processLocalCommitWithGlobalLocks`（checkLock 后本地提交），不参与全局事务但不绕过全局锁校验。

## Design Gotchas

- 全局锁保护的是**主键值**，不是任意行条件；非主键更新若不影响 PK，lockKey 仅含命中行的 PK。
- 分支注册发生在 `commit()` 时刻，而非 statement 执行时；undo_log 与 lockKey 先缓冲，提交时一次性注册 + 落盘。
- `branchRegister` 在 `targetConnection.commit()` **之前**通过 RPC 同步发送；TC 锁占用与本地提交之间若进程崩溃，存在「已注册但未落 undo_log」的极小窗口，由 TC 侧超时回滚兜住。

## Links
- [Seata](/docs/CS/Framework/Seata/Seata.md)
- [Architecture](/docs/CS/Framework/Seata/Architecture.md)
- [Transaction Flow](/docs/CS/Framework/Seata/Transaction_Flow.md)
- [TC Coordinator](/docs/CS/Framework/Seata/TC_Coordinator.md)

## References
- Apache Seata source (v2.7.0): https://github.com/apache/seata/tree/v2.7.0
