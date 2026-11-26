# Global Lock

## Introduction

全局锁是 **AT 模式写隔离**的基石：一阶段本地事务提交**之前**，RM 必须先在 TC 处抢到分支涉及数据行的全局锁，抢不到就回滚本地事务、释放本地锁。它保护的是**主键值**（`表名:主键值`），不是整行、更不是整表，因此冲突粒度细、并发友好。XA / TCC / Saga 不依赖全局锁——XA 用数据库原生锁，TCC/Saga 由业务自行控制。

> 版本基线：apache/seata **v2.7.0**。以下片段均取自该 tag。

## Lock Abstraction and Factory

`LockManager` 定义 `acquireLock` / `releaseLock` / `isLockable` / `cleanAllLocks`；`AbstractLockManager` 提供公共骨架，把 `BranchSession` 解析成 `RowLock` 列表再交给具体 `Locker`：

```java
@Override
public boolean acquireLock(BranchSession branchSession, boolean autoCommit, boolean skipCheckLock)
        throws TransactionException {
    if (branchSession == null) {
        throw new IllegalArgumentException("branchSession can't be null for memory/file locker.");
    }
    String lockKey = branchSession.getLockKey();
    if (StringUtils.isNullOrEmpty(lockKey)) {
        // no lock
        return true;
    }
    // get locks of branch
    List<RowLock> locks = collectRowLocks(branchSession);
    if (CollectionUtils.isEmpty(locks)) {
        // no lock
        return true;
    }
    return getLocker(branchSession).acquireLock(locks, autoCommit, skipCheckLock);
}
```

`getLocker(BranchSession)` 是抽象工厂方法，由子类按 store mode 返回具体 Locker。`LockerManagerFactory` 按 **`LockMode`** 用 SPI 加载——注意 `LockMode` 与 session 的 `StoreMode` **解耦**，锁后端可独立配置：

```java
public static void init(LockMode lockMode) {
    // ...
    if (lockMode == null) {
        lockMode = StoreConfig.getLockMode();
    }
    LOCK_MANAGER = EnhancedServiceLoader.load(LockManager.class, lockMode.getName());
    // ...
}
```

## Lock Structure: Primary Key Value

`LockDO` 的关键字段揭示锁语义：`tableName`（被锁表）、`pk`（被锁主键值）、`rowKey`（组合键，格式 `表名:主键值`，是锁表唯一约束列）。换言之，**全局锁粒度是"一张表的某一个主键值"**——两个分支只要不碰同一主键就不互相等锁，这是 AT 写隔离高并发的根本原因。

## Four Locker Backends

| 后端（LockMode） | 类 | 原子性保证 |
| :--- | :--- | :--- |
| **db** | `DataBaseLocker` | 锁存 `lock_table`，靠 `row_key` 唯一约束 + 事务内 INSERT；插入冲突即获取失败 |
| **file** | `FileLocker` | 内存 + 文件持久化，随会话一并落盘 |
| **redis** | `RedisLocker` / `RedisLuaLocker` | 前者走 pipeline；后者用 Lua 把"多键加锁"包成原子（`RedisLockerFactory` 按 `storeRedisType` 选路） |
| **raft** | `RaftLockManager` | `extends FileLockManager`，复用文件锁，外层用 jraft `Closure` 把锁状态经 Raft 日志复制 |

`DataBaseLocker.acquireLock` 把 `RowLock` 转成 `LockDO` 后委托 `lockStore.acquireLock(...)`——实际加锁原子性落在 `LockStore`，与 session 的 `TransactionStoreManager` 是相互独立的两套持久化系统。

## Acquisition Failure and Isolation Semantics

- 获取失败返回 `false`：RM 侧分支注册失败 → 本地事务回滚 + 释放本地锁，并按超时不断重试直到全局锁超时（`skipCheckLock` 仅在回滚释放等内部路径使用）。
- `isLockable` 用于 `SELECT FOR UPDATE` 等读隔离路径：RM 在这类 SQL 前先向 TC 查全局锁，若已被其它全局事务持有则等待，避免脏读：

```java
@Override
public boolean isLockable(String xid, String resourceId, String lockKey) throws TransactionException {
    if (StringUtils.isBlank(lockKey)) {
        return true;
    }
    List<RowLock> locks = collectRowLocks(lockKey, resourceId, xid);
    try {
        return getLocker().isLockable(locks);
    } catch (Exception t) {
        LOGGER.error("isLockable error, xid:{} resourceId:{}, lockKey:{}", xid, resourceId, lockKey, t);
        return false;
    }
}
```

- 全局锁与本地锁协作：**本地锁**在分支本地事务提交后即释放；**全局锁**要等全局事务二阶段提交（异步删 undo_log）或回滚后才由 TC 释放。"commit 前持全局锁、commit 后释本地锁"是 AT 高并发 + 写隔离的关键时间窗。

## Corrections

- **全局锁保护主键值，不是行或表**：`LockDO.rowKey = 表名:主键`，冲突判定精确到主键，这是 AT 写隔离粒度细的根本原因。
- **锁系统与 session 存储是两套独立持久化**：Locker 委托 `LockStore`（db 后端即 `LockStoreDataBaseDAO`），而非 `TransactionStoreManager`；两者可按 `StoreMode`/`LockMode` 分别选型。
- **`LockMode` 独立于 `StoreMode`**：`LockerManagerFactory` 用 SPI 按 `LockMode` 加载，session 用 db、锁用 redis 是合法混合部署。
- **raft 模式的锁不是"第四套 Locker"而是复制层**：`RaftLockManager extends FileLockManager`，在文件锁之上用 jraft `Closure` 把锁变更复制给 follower，follower apply 后本地仍是 FileLocker 语义（详见 [Raft HA](/docs/CS/Framework/Seata/Raft_HA.md)）。

## Links
- [Seata](/docs/CS/Framework/Seata/Seata.md)
- [Architecture](/docs/CS/Framework/Seata/Architecture.md)
- [AT and Undo Log](/docs/CS/Framework/Seata/AT_UndoLog.md)
- [TC Coordinator](/docs/CS/Framework/Seata/TC_Coordinator.md)
- [TC Storage](/docs/CS/Framework/Seata/TC_Storage.md)
- [Raft HA](/docs/CS/Framework/Seata/Raft_HA.md)

## References
- Apache Seata source (v2.7.0): https://github.com/apache/seata/tree/v2.7.0
