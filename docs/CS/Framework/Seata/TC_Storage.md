# TC Storage (Seata v2.7.0)

> 源码驱动笔记。基座：apache/seata @ v2.7.0（tag `v2.7.0`，blobless + sparse-checkout 落盘 `server` / `core`）。类名可在 `server/src/main/java/org/apache/seata/server/store/`、`server/src/main/java/org/apache/seata/server/storage/`、`core/src/main/java/org/apache/seata/core/store/` 下核对。

## Introduction

TC 是「有状态」协调者：全局事务、分支事务、全局锁都需要在内存 + 持久化两层存在，才能在内重启 / 故障切换后恢复。Seata 把会话持久化抽象为 `TransactionStoreManager` 接口，并提供 **db / file / redis** 三套后端（**无 raft 后端**——Raft 模式下会话通过 Raft 复制，apply 后落到本地 db/file，见 [Raft HA](/docs/CS/Framework/Seata/Raft_HA.md)）。

## 抽象与转换

- `TransactionStoreManager`（`server/store/TransactionStoreManager.java`）是持久化接口，定义 `writeSession` / `readSession` / `removeSession` / `readGlobalStatus` 等操作；`AbstractTransactionStoreManager`（`server/store/AbstractTransactionStoreManager.java:30`）提供公共骨架。
- 内存中的 `GlobalSession` / `BranchSession` 与落盘对象 `GlobalTransactionDO` / `BranchTransactionDO` / `LockDO`（`core/store/`）之间的互转由 `SessionConverter`（`server/storage/SessionConverter.java`）完成——这是「内存对象 ↔ 存储行」的统一边界。

## 三套后端对比

| 后端 | 类（包 `server/storage/<mode>/store`） | 写入语义 | 原子性 / 恢复 |
| :--- | :--- | :--- | :--- |
| **db** | `DataBaseTransactionStoreManager`（`:52`，`storage/db/store`） | 写 `global_table` / `branch_table` / `lock_table`，随本地事务提交 | 依赖数据库事务，强一致；恢复即 `SELECT` 未终态的会话重放 |
| **file** | `FileTransactionStoreManager`（`:60`，`storage/file/store`） | 追加写事务日志文件（含写队列 + 刷盘） | 崩溃后重放日志重建内存会话；吞吐高但需管理文件轮转 |
| **redis** | `RedisTransactionStoreManager`（`:75`）+ `RedisLuaTransactionStoreManager`（`:51`，继承前者） | 用 Redis 结构存会话（key 含 xid/branchId），`RedisLuaTransactionStoreManager` 用 Lua 保证多键原子 | 依赖 Redis 持久化（AOF/RDB）；`RedisLua*` 是带 Lua 原子化的增强版 |

`RedisTransactionStoreManagerFactory`（`storage/redis/store`）按配置构造对应实例。

## 写与会话生命周期

TC 的 `DefaultCore`（`server/coordinator/DefaultCore`）在关键节点调用 storeManager：

1. `begin` → `writeGlobalSession`（新增全局事务行）
2. `branchRegister` → `writeBranchSession`（新增分支行）
3. `globalCommit` / `globalRollback` → 更新 `GlobalSession` 状态 / 写入终态
4. 二阶段分支完成 → `removeSession`（清理分支 / 全局行）

读恢复：TC 启动时（或 Raft follower 追平后）`readSession` 拉取所有未终态会话，重建 `GlobalSession` / `BranchSession` 内存树。

## 源码打假 / 设计点

- **没有 `RaftTransactionStoreManager`**：storage 后端只有 db / file / redis 三套。Raft 模式并不引入新的「存储后端」，而是把 `DefaultCore` 的写操作作为 Raft 日志条目复制，状态机 apply 时再调用**本地**的 db/file storeManager 落盘（详见 [Raft HA](/docs/CS/Framework/Seata/Raft_HA.md)）。
- **SessionConverter 是唯一转换点**：无论后端如何切换，`GlobalSession` ↔ `DO` 的映射只在 `SessionConverter` 发生，后端只需关心 `DO` 的行存，职责清晰、易扩展新后端。
- **file 后端是「日志追加」而非「随机写」**：file 模式通过顺序追加 + 定期刷盘获得高吞吐，重启走日志重放；这与 db 后端的「按主键 UPDATE」语义不同，选型时需在一致性与吞吐间权衡。
- **redis 后端的一致性边界**：redis 自身的持久化策略（AOF everysec / RDB）决定崩溃时可能丢少量最近会话；`RedisLuaTransactionStoreManager` 用 Lua 把「多键写」包成原子，但不能跨越 Redis 的持久化边界。

## Links

- [Seata](/docs/CS/Framework/Seata/Seata.md)
- [Architecture](/docs/CS/Framework/Seata/Architecture.md)
- [TC Coordinator](/docs/CS/Framework/Seata/TC_Coordinator.md)
- [Global Lock](/docs/CS/Framework/Seata/Global_Lock.md)
- [Raft HA](/docs/CS/Framework/Seata/Raft_HA.md)
- [Transaction Flow](/docs/CS/Framework/Seata/Transaction_Flow.md)
