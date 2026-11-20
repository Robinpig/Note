# Raft HA

## Introduction

Seata 2.x 把 TC 从"依赖外部注册中心的单点协调者"演进为**内嵌 Raft 的 CP 系统**：多个 TC 组成 Raft 组，全局/分支会话与全局锁的变更作为 Raft 日志复制到多数派，使 TC 在节点宕机、leader 切换后仍保持一致。它解决 TC 自身的**高可用与强一致**，与事务模式（AT/TCC/Saga/XA）正交。

> 版本基线：apache/seata **v2.7.0**。以下片段均取自该 tag。Raft 用 **SOFA JRaft**（`com.alipay.sofa.jraft`），不是自研，也不是 etcd/Ratis。

## Raft Integration Architecture

`RaftCoordinator` **extends `DefaultCoordinator`**——Raft 不是另起一套协调者，而是在 `DefaultCoordinator` 之外叠加"复制层"：它额外 `implements ApplicationListener<ClusterChangeEvent>`，通过 `GROUP_PREVENT` + `isPass()` 拦截非 leader 的写请求。

```java
public class RaftCoordinator extends DefaultCoordinator implements ApplicationListener<ClusterChangeEvent> {

    protected static final Map<String, Boolean> GROUP_PREVENT = new ConcurrentHashMap<>();
```

```java
@Override
public <T extends AbstractTransactionRequest, S extends AbstractTransactionResponse> void exceptionHandleTemplate(
        Callback<T, S> callback, T request, S response) {
    String group = SeataClusterContext.bindGroup();
    try {
        if (!isPass(group)) {
            throw new TransactionException(
                    TransactionExceptionCode.NotRaftLeader,
                    " The current TC is not a leader node, interrupt processing !");
        }
        super.exceptionHandleTemplate(callback, request, response);
    } catch (TransactionException tex) {
        LOGGER.error("Catch TransactionException while do RPC, request: {}", request, tex);
        callback.onTransactionException(request, response, tex);
    } finally {
        SeataClusterContext.unbindGroup();
    }
}

private boolean isPass(String group) {
    // Non-raft mode always allows requests
    return Optional.ofNullable(GROUP_PREVENT.get(group)).orElse(false);
}

@Override
public void onApplicationEvent(ClusterChangeEvent event) {
    setPrevent(event.getGroup(), event.isLeader());
}
```

> 命名陷阱：`GROUP_PREVENT` 字面像"阻止"，但 `setPrevent(group, event.isLeader())` 写入的是"是否 leader"，`isPass` 返回该值，`true` 代表**允许通过**；从未收到 `ClusterChangeEvent` 的 group 默认 `false`（拒绝）。以代码为准，别被名字带偏。

## Write Path and State Machine Apply

`RaftStateMachine extends StateMachineAdapter`（jraft 的），是真正的 apply 点。leader 上的写经 `RaftTaskUtil.createTask(...)` 提交 jraft `Node`。

`onApply` 的 leader/follower 分支**不是用 `isLeader()` 判断，而是看 `iterator.done()` 是否为 null**：leader 本地提交带 callback（`done != null`）→ 直接 `done.run(Status.OK())` 执行任务，不走序列化；follower 重放日志（`done == null`）→ 解码成 `RaftBaseMsg` 再分派：

```java
@Override
public void onApply(Iterator iterator) {
    while (iterator.hasNext()) {
        Closure done = iterator.done();
        if (done != null) {
            // leader does not need to be serialized, just execute the task directly
            done.run(Status.OK());
        } else {
            ByteBuffer byteBuffer = iterator.getData();
            // if data is empty, it is only a heartbeat event and can be ignored
            if (byteBuffer != null && byteBuffer.hasRemaining()) {
                RaftBaseMsg msg = (RaftBaseMsg)
                        RaftSyncMessageSerializer.decode(byteBuffer.array()).getBody();
                onExecuteRaft(msg);
            }
        }
        iterator.next();
    }
}
```

根因在 `RaftTaskUtil.createTask`：`task.setDone(...)` 把调用方 Closure 设为 Task.done，只有 leader 本地 apply 时它非 null。

## Replicated Operations (EXECUTES Table)

`RaftStateMachine` 构造时按 `StoreMode.RAFT` 注册 `EXECUTES`，即 Raft 模式下"可被复制的状态变更"全貌：

```java
if (StoreMode.RAFT.getName().equalsIgnoreCase(mode)) {
    registryStoreSnapshotFile(new SessionSnapshotFile(group));
    registryStoreSnapshotFile(new VGroupSnapshotFile(group));
    EXECUTES.put(ADD_GLOBAL_SESSION, new AddGlobalSessionExecute());
    EXECUTES.put(ADD_BRANCH_SESSION, new AddBranchSessionExecute());
    EXECUTES.put(REMOVE_BRANCH_SESSION, new RemoveBranchSessionExecute());
    EXECUTES.put(UPDATE_GLOBAL_SESSION_STATUS, new UpdateGlobalSessionExecute());
    EXECUTES.put(RELEASE_GLOBAL_SESSION_LOCK, new GlobalReleaseLockExecute());
    EXECUTES.put(REMOVE_GLOBAL_SESSION, new RemoveGlobalSessionExecute());
    EXECUTES.put(UPDATE_BRANCH_SESSION_STATUS, new UpdateBranchSessionExecute());
    EXECUTES.put(RELEASE_BRANCH_SESSION_LOCK, new BranchReleaseLockExecute());
    EXECUTES.put(REMOVE_VGROUP_MAPPING, new VGroupRemoveExecute());
    EXECUTES.put(ADD_VGROUP_MAPPING, new VGroupAddExecute());
}
```

`onExecuteRaft` 对未注册的消息类型**直接抛异常**（一道安全闸，防止不可复制事件混入状态机）：

```java
private void onExecuteRaft(RaftBaseMsg msg) {
    RaftMsgExecute<?> execute = EXECUTES.get(msg.getMsgType());
    if (execute == null) {
        throw new RuntimeException(
                "the state machine does not allow events that cannot be executed, please feedback the information to the Seata community !!! msg: "
                        + msg);
    }
    try {
        execute.execute(msg);
    } catch (Throwable e) {
        LOGGER.error("Message synchronization failure: {}, msgType: {}", e.getMessage(), msg.getMsgType(), e);
        throw new RuntimeException(e);
    }
}
```

会话侧 `RaftSessionManager extends FileSessionManager`，所有会话变更构造 `RaftXxxSyncMsg` 经 `RaftTaskUtil.createTask` 提交，leader 侧在 `Closure.isOk()` 后落本地内存；锁侧 `RaftLockManager extends FileLockManager`，用 jraft Closure 复制锁释放。

## Snapshot and Recovery

`RaftStateMachine` 注册三类快照：`LeaderMetadataSnapshotFile`、`SessionSnapshotFile`、`VGroupSnapshotFile`（后两类仅 `SessionMode.RAFT` 注册）。`onSnapshotLoad` 中 **leader 不允许加载快照**（直接返回 false），follower 才逐个 `snapshotFile.load(reader)`：

```java
@Override
public boolean onSnapshotLoad(final SnapshotReader reader) {
    if (!StringUtils.equals(SessionMode.RAFT.getName(), mode)) {
        return true;
    }
    if (isLeader()) {
        LOGGER.warn("Leader is not supposed to load snapshot");
        return false;
    }
    for (StoreSnapshotFile snapshotFile : snapshotFiles) {
        if (!snapshotFile.load(reader)) {
            return false;
        }
    }
    return true;
}
```

## Leader Election and Failover

`onLeaderStart(term)`：仅当"此前不是 leader、现在成为 leader"（`!leader && RaftServerManager.isRaftMode()`）才异步 `SessionHolder.reload(...)` 重载会话——**leader 切换时把内存会话重新加载进状态机**，使新 leader 立即具备完整事务视图；同一分支还会 `changePeers(conf)` 清理失效成员：

```java
@Override
public void onLeaderStart(final long term) {
    boolean leader = isLeader();
    this.leaderTerm.set(term);
    this.currentTerm.set(term);
    syncMetadata();
    if (!leader && RaftServerManager.isRaftMode()) {
        CompletableFuture.runAsync(() -> {
            SeataClusterContext.bindGroup(group);
            try {
                // become the leader again,reloading global session
                SessionHolder.reload(SessionHolder.getRootSessionManager().allSessions(), SessionMode.RAFT, false);
            } finally {
                SeataClusterContext.unbindGroup();
            }
        });
        Configuration conf = RouteTable.getInstance().getConfiguration(group);
        changePeers(conf);
    }
}
```

in-flight 事务靠 Raft 日志复制 + leader 切换后 reload 保持连续；但切换瞬间尚未复制到多数派的本地写会回退到上一条已提交日志，需 TM/RM 侧重试补齐——**不是"零丢失、零重试"**。

## Corrections

- **Raft 是复制层，不是第四套存储后端**：session 的 storeManager 仍只有 db/file/redis；Raft 把 `DefaultCore` 的写作为日志复制，apply 后调用各节点本地 db/file store 落盘。
- **`RaftCoordinator extends DefaultCoordinator`，Raft 是叠加而非替换**：核心事务逻辑仍是那套，只是写路径包了一层复制。
- **leader 与 follower 的 apply 分支不同但终态一致**：leader 走 `done != null` 直接执行，follower 走解码 + `EXECUTES` 分派，二者执行同一组 `RaftMsgExecute`。
- **底层还用到 Bolt**：jraft 之外，RPC 层 import `com.alipay.remoting.InvokeContext`。
- **`onApply` 判断依据是 `iterator.done()`，不是 `isLeader()`**：这是理解 leader/follower 分支的关键。

## Links
- [Seata](/docs/CS/Framework/Seata/Seata.md)
- [Architecture](/docs/CS/Framework/Seata/Architecture.md)
- [TC Coordinator](/docs/CS/Framework/Seata/TC_Coordinator.md)
- [TC Storage](/docs/CS/Framework/Seata/TC_Storage.md)
- [Global Lock](/docs/CS/Framework/Seata/Global_Lock.md)
- [Transaction Flow](/docs/CS/Framework/Seata/Transaction_Flow.md)

## References
- Apache Seata source (v2.7.0): https://github.com/apache/seata/tree/v2.7.0
- SOFA JRaft: https://github.com/sofastack/sofa-jraft
