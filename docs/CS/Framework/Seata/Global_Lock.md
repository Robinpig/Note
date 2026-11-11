# Global Lock (Seata v2.7.0)

> 源码驱动笔记。基座：apache/seata @ v2.7.0（tag `v2.7.0`，blobless + sparse-checkout 落盘 `server` / `core`）。类名可在 `server/src/main/java/org/apache/seata/server/lock/`、`server/src/main/java/org/apache/seata/server/storage/<mode>/lock/`、`core/src/main/java/org/apache/seata/core/store/LockDO.java` 下核对。

## Introduction

全局锁是 **AT 模式写隔离**的基石：一阶段本地事务提交**之前**，RM 必须先在 TC 处抢到分支涉及数据行的全局锁，抢不到就回滚本地事务、释放本地锁。它保护的是**主键值**（不是整行、更不是整表），因此冲突粒度细、并发友好。全局锁与本地数据库行锁协作：本地锁保证单库内 ACID，全局锁保证跨分支「同一主键在全局事务提交前不被其它全局事务修改」。XA / TCC / Saga 不依赖全局锁——XA 用数据库原生锁、TCC/Saga 由业务自行控制。

## 锁抽象与工厂

- `LockManager`（`server/lock/LockManager.java:31`）是锁管理接口，定义 `acquireLock` / `releaseLock` / `isLockable` / `cleanAllLocks`。
- `AbstractLockManager`（`server/lock/AbstractLockManager.java:38`）提供公共骨架：它的 `acquireLock(BranchSession)`（`AbstractLockManager.java:46`）把 `BranchSession` 解析成 `RowLock` 列表，再交给 `getLocker(branchSession).acquireLock(locks)`（`AbstractLockManager.java:67`）；`getLocker(BranchSession)`（`AbstractLockManager.java:119`）是**抽象工厂方法**，由子类按 store mode 返回具体 `Locker`。
- `LockerManagerFactory`（`server/lock/LockerManagerFactory.java:32`）按 **`LockMode`** 用 SPI 加载：`EnhancedServiceLoader.load(LockManager.class, lockMode.getName())`（`LockerManagerFactory.java:70`）。注意 `LockMode` 与 session 的 `StoreMode` **解耦**——锁后端可独立配置（`StoreConfig.getLockMode()`）。

## 锁结构：保护主键值

`LockDO`（`core/store/LockDO.java:27`）三个关键字段揭示锁的语义：

| 字段 | `LockDO.java` 行 | 含义 |
| :--- | :--- | :--- |
| `tableName` | `:37` | 被锁的表 |
| `pk` | `:39` | 被锁的**主键值** |
| `rowKey` | `:43` | 组合键，格式即 `表名:主键值`，是锁表的唯一约束列 |

换言之，**全局锁的粒度是「一张表的某一个主键值」**。两个分支事务只要不碰同一主键，就不会互相等锁——这正是 AT 写隔离能做到较高并发的原因。

## 四套 Locker 后端

具体 `Locker` 实现与 session 存储后端同构，分散在 `server/storage/<mode>/lock/`：

| 后端（LockMode） | 类 | 原子性保证 |
| :--- | :--- | :--- |
| **db** | `DataBaseLocker`（`storage/db/lock/DataBaseLocker.java:53`） | 锁存 `lock_table`，靠 `row_key` 唯一约束 + 事务内 INSERT；插入冲突即获取失败 |
| **file** | `FileLocker`（`storage/file/lock/FileLocker.java`） | 内存 + 文件持久化，随会话一并落盘 |
| **redis** | `RedisLocker` / `RedisLuaLocker`（`storage/redis/lock/`） | `RedisLocker` 走 pipeline；`RedisLuaLocker`（`RedisLuaLocker.java:48`）用 Lua 脚本把「多键加锁」包成原子（`RedisLockerFactory` 按 `storeRedisType` 选路） |
| **raft** | `RaftLockManager`（`storage/raft/lock/RaftLockManager.java:40`，`extends FileLockManager`） | 复用文件锁实现，外层用 jraft `Closure` 把锁状态经 Raft 日志复制 |

`DataBaseLocker.acquireLock`（`DataBaseLocker.java:64`）把 `RowLock` 转成 `LockDO` 后委托给 `lockStore.acquireLock(...)`——实际的加锁原子性落在 `LockStore`（与 session 的 `TransactionStoreManager` **相互独立**的两套持久化系统）。

## 获取失败与隔离语义

- 获取失败返回 `false`：RM 侧分支注册失败 → 本地事务回滚 + 释放本地锁，并按超时不断重试直到全局锁超时（`AbstractLockManager.acquireLock` 的 `skipCheckLock` 仅在回滚释放等内部路径使用）。
- `isLockable`（`AbstractLockManager.java:92`）用于 `SELECT FOR UPDATE` 等读隔离路径：RM 在执行这类 SQL 前先向 TC 查全局锁，若已被其它全局事务持有则等待，从而避免「脏读」（详见 [AT and Undo Log](/docs/CS/Framework/Seata/AT_UndoLog.md) 的隔离讨论）。
- 全局锁与本地锁协作：**本地锁**在分支本地事务提交后即释放；**全局锁**要等到全局事务二阶段提交（异步删 undo_log）或回滚后才由 TC 释放。一阶段 commit 前持全局锁、commit 后释本地锁，是 AT「高并发 + 写隔离」的关键时间窗。

## 源码打假 / 设计点

- **全局锁保护的是主键值，不是行或表**：`LockDO.rowKey = 表名:主键`，冲突判定精确到主键，这是 AT 写隔离粒度细的根本原因，也是「不同主键的分支互不阻塞」的源码依据。
- **锁系统与 session 存储是两套独立持久化**：`Locker` 委托给 `LockStore`（db 后端即 `LockStoreDataBaseDAO`），而非 `TransactionStoreManager`。两者可分别按 `StoreMode` / `LockMode` 选型，互不干扰。
- **`LockMode` 可独立于 `StoreMode`**：`LockerManagerFactory` 用 SPI 按 `LockMode` 加载，不绑定 session 存储后端——例如 session 用 db、锁用 redis 是合法的混合部署。
- **raft 模式的锁不是「第四套 Locker 实现」而是复制层**：`RaftLockManager extends FileLockManager`，在文件锁之上用 jraft `Closure` 把锁变更复制给 follower，follower apply 后本地仍是 FileLocker 语义（详见 [Raft HA](/docs/CS/Framework/Seata/Raft_HA.md)）。

## Links

- [Seata](/docs/CS/Framework/Seata/Seata.md)
- [Architecture](/docs/CS/Framework/Seata/Architecture.md)
- [AT and Undo Log](/docs/CS/Framework/Seata/AT_UndoLog.md)
- [TC Coordinator](/docs/CS/Framework/Seata/TC_Coordinator.md)
- [TC Storage](/docs/CS/Framework/Seata/TC_Storage.md)
- [Raft HA](/docs/CS/Framework/Seata/Raft_HA.md)
