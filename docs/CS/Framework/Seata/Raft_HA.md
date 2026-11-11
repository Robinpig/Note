# Raft HA (Seata v2.7.0)

> 源码驱动笔记。基座：apache/seata @ v2.7.0（tag `v2.7.0`，blobless + sparse-checkout 落盘 `server` / `core`）。类名可在 `server/src/main/java/org/apache/seata/server/coordinator/RaftCoordinator.java`、`server/src/main/java/org/apache/seata/server/cluster/raft/`（RaftServer / RaftStateMachine）、`server/src/main/java/org/apache/seata/server/storage/raft/` 下核对。

## Introduction

Seata 2.x 把 TC 从「依赖外部注册中心的单点协调者」演进为**内嵌 Raft 的 CP 系统**：多个 TC 节点组成 Raft 组，全局/分支会话与全局锁的变更作为 Raft 日志条目复制到多数派，使 TC 在节点宕机、leader 切换后仍保持状态一致。它解决的是 TC 自身的**高可用与强一致**，与事务模式（AT/TCC/Saga/XA）正交——任何模式在 Raft 模式下都走同一套复制路径。Raft 之前，TC 会话只能靠 file/db/redis 单机持久化，failover 需外部手段；Raft 之后，TC 集群本身即具备自动选主与状态重建。

## Raft 集成架构

Seata 使用 **SOFA JRaft**（`com.alipay.sofa.jraft`，蚂蚁开源 Raft 库），而非自研：

- `RaftCoordinator`（`server/coordinator/RaftCoordinator.java:37`）**`extends DefaultCoordinator`**——Raft 不是另起一套协调者，而是在 `DefaultCoordinator` 之外叠加「复制层」：leader 上的核心操作（begin / branchRegister / commit / rollback）被包装成 Raft 任务提交给 jraft `Node`，复制成功后在所有节点 apply。
- `RaftServer`（`server/cluster/raft/RaftServer.java:54`）封装 jraft 的 `RaftGroupService` / `Node`：构造时传入 `RaftStateMachine` 作 FSM（`RaftServer.java:76`），`start()` 设置 log / raft_meta / snapshot 三个 URI 并 `raftGroupService.start(false)`（`RaftServer.java:97`）。
- `RaftStateMachine`（`server/cluster/raft/RaftStateMachine.java:107`）**`extends StateMachineAdapter`**（jraft 的），是真正的「状态机 apply 点」。

## 写路径与状态机 apply

leader 上的写操作经 `RaftTaskUtil.createTask(...)` 提交到 jraft；jraft 复制日志到多数派后回调 `RaftStateMachine.onApply(iterator)`（`RaftStateMachine.java:170`）：

```
leader: core op → RaftTaskUtil.createTask(msg) → jraft Node.appendEntries
        → 多数派确认 → onApply: iterator.done() != null → 直接执行（leader 不串行化）
follower: 收到日志 → onApply: done == null → 解码 RaftBaseMsg
        → onExecuteRaft(msg) → EXECUTES.get(msgType).execute(msg)
        → AddGlobalSessionExecute / AddBranchSessionExecute / ... 应用到本地 SessionHolder
```

`onApply` 的关键分支（`RaftStateMachine.java:173-188`）：`done != null` 表示 leader 本地提交，直接 `done.run(Status.OK())` 执行任务；`done == null` 表示 follower 通过日志回放，需把字节流解码成 `RaftBaseMsg` 再分派。**leader 与 follower 最终都执行同一组 `RaftMsgExecute`，保证各节点会话状态收敛**。

## 复制的操作集合（EXECUTES 表）

`RaftStateMachine` 构造时按 `RaftSyncMsgType` 注册执行器（`RaftStateMachine.java:155-164`），即 Raft 模式下「可被复制的状态变更」全貌：

| 消息类型 | 执行器 | 语义 |
| :--- | :--- | :--- |
| `ADD_GLOBAL_SESSION` | `AddGlobalSessionExecute` | 新增全局会话 |
| `ADD_BRANCH_SESSION` | `AddBranchSessionExecute` | 新增分支会话 |
| `UPDATE_GLOBAL_SESSION_STATUS` | `UpdateGlobalSessionExecute` | 推进全局状态 |
| `UPDATE_BRANCH_SESSION_STATUS` | `UpdateBranchSessionExecute` | 推进分支状态 |
| `REMOVE_GLOBAL_SESSION` | `RemoveGlobalSessionExecute` | 清理全局会话 |
| `REMOVE_BRANCH_SESSION` | `RemoveBranchSessionExecute` | 清理分支会话 |
| `RELEASE_GLOBAL_SESSION_LOCK` | `GlobalReleaseLockExecute` | 释放全局锁 |
| `RELEASE_BRANCH_SESSION_LOCK` | `BranchReleaseLockExecute` | 释放分支锁 |
| `ADD_VGROUP_MAPPING` / `REMOVE_VGROUP_MAPPING` | `VGroupAddExecute` / `VGroupRemoveExecute` | vgroup→cluster 映射复制 |
| `REFRESH_CLUSTER_METADATA` | 内联 lambda | 刷新集群元数据 |

注意：**只有这些被注册的操作会经 Raft 复制**；若某消息类型不在 `EXECUTES` 中，`onExecuteRaft` 会直接抛异常（`RaftStateMachine.java:346`），这是一道安全闸，防止「不可复制的事件」混入状态机。

## Snapshot 与恢复

`RaftStateMachine` 注册了三类快照文件（`RaftStateMachine.java:151-154`）：`LeaderMetadataSnapshotFile`、`SessionSnapshotFile`、`VGroupSnapshotFile`。

- `onSnapshotSave`（`RaftStateMachine.java:195`）：遍历 `snapshotFiles` 落盘；仅当 `SessionMode.RAFT` 时真正写（否则空过）。
- `onSnapshotLoad`（`RaftStateMachine.java:213`）：follower 从快照恢复；**leader 不允许加载快照**（`RaftStateMachine.java:217` 直接返回 false）。
- jraft 自身还维护 `log`（`RaftServer.java:89`）与 `raft_meta`（`RaftServer.java:91`）URI，新节点或落后节点通过「追日志 + 必要时装快照」追上集群。

## Leader 选举与故障切换

- `onLeaderStart(term)`（`RaftStateMachine.java:234`）：新 leader 上任后 `syncMetadata()` 并异步 `SessionHolder.reload(...)`（`RaftStateMachine.java:249`）从根会话管理器重载全局会话——**leader 切换时把内存会话重新加载进状态机**，使新 leader 立即具备完整事务视图。
- 成员变更：`onConfigurationCommitted`（`RaftStateMachine.java:280`）与 `changePeers`（`RaftStateMachine.java:290`）在扩缩容后同步/裁剪 follower/learner 元数据。
- **in-flight 事务的连续性**：由于会话状态靠 Raft 日志复制、leader 切换后重新 `reload`，正在进行的全局事务不会因 leader 切换而丢失——新 leader 从已复制的会话状态继续驱动二阶段。但 leader 切换瞬间、尚未复制到多数派的本地写会回退到上一条已提交日志，需要 TM/RM 侧的重试补齐（这是 Raft 自身的线性一致语义，Seata 不额外补偿）。

## 与存储后端、锁的关系

- **Raft 模式不是 `TransactionStoreManager` 的「第四套后端」**：session 的 `TransactionStoreManager` 仍只有 db / file / redis 三套（见 [TC Storage](/docs/CS/Framework/Seata/TC_Storage.md)）。Raft 模式用 `RaftSessionManager`（`storage/raft/session`）接管会话的增删改，把变更作为 Raft 日志复制，apply 时落到**各节点本地**的 file/db 会话存储；jraft 的 `log` + `SessionSnapshotFile` 提供持久化与检查点。
- **Raft 模式的锁**：`RaftLockManager extends FileLockManager`（`storage/raft/lock/RaftLockManager.java:40`），复用文件锁实现，外层用 jraft `Closure`（`RaftLockManager.java:49` / `:73`）把锁变更经 Raft 复制。
- 一句话：**Raft 是「复制层」，session 存储与锁存储是被复制的对象**，三者通过 `RaftCoordinator` + `RaftStateMachine` 的 `EXECUTES` 表串起来。

## 源码打假 / 设计点

- **Seata 的 Raft 是 SOFA JRaft，不是自研也不是 etcd/Raft 库**：`com.alipay.sofa.jraft` 出现在 `RaftServer` / `RaftStateMachine` / `RaftLockManager` 的 import 中，依赖以 `com.alipay.sofa` 为 groupId。
- **`RaftCoordinator extends DefaultCoordinator`，Raft 是叠加而非替换**：不要把它当成「两套并行的 TC 协调者」——Raft 模式下的核心事务逻辑仍是 `DefaultCoordinator` 的那套，只是写路径被包了一层复制。
- **leader 与 follower 的 apply 分支不同但终态一致**：leader 走 `done != null` 直接执行，follower 走解码 + `EXECUTES` 分派；二者执行的是同一组 `RaftMsgExecute`，这是「写只在 leader、状态全节点收敛」的实现细节。
- **`EXECUTES` 未注册的操作会被拒绝**：`onExecuteRaft` 对未知 `msgType` 直接抛异常，是一道防止「非复制事件」污染状态机的安全闸，也是理解「哪些操作能进 Raft」的权威清单。
- **leader 切换靠 `SessionHolder.reload` 续命 in-flight 事务**：这是 Raft 模式下高可用的关键，但切换瞬间未复制到多数派的写会回退，需上游重试——不要误以为 Raft 模式「零丢失、零重试」。

## Links

- [Seata](/docs/CS/Framework/Seata/Seata.md)
- [Architecture](/docs/CS/Framework/Seata/Architecture.md)
- [TC Coordinator](/docs/CS/Framework/Seata/TC_Coordinator.md)
- [TC Storage](/docs/CS/Framework/Seata/TC_Storage.md)
- [Global Lock](/docs/CS/Framework/Seata/Global_Lock.md)
- [Transaction Flow](/docs/CS/Framework/Seata/Transaction_Flow.md)
