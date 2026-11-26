# TC Storage

## Introduction

TC 是"有状态"协调者：全局事务、分支事务、全局锁都要在内存 + 持久化两层存在，才能在重启 / 故障切换后恢复。Seata 把会话持久化抽象为 `TransactionStoreManager`，提供 **db / file / redis** 三套后端。

> 版本基线：apache/seata **v2.7.0**。以下类名与片段均取自该 tag。

**注意**：会话存储**没有 raft 后端**。Raft 模式是通过 Raft 复制会话变更、apply 后落到各节点本地的 db/file store，见 [Raft HA](/docs/CS/Framework/Seata/Raft_HA.md)。全局锁是另一套独立持久化系统，见 [Global Lock](/docs/CS/Framework/Seata/Global_Lock.md)。

## Abstraction and Conversion

`TransactionStoreManager` 定义 `writeSession` / `readSession` / `removeSession` / `readGlobalStatus` 等操作；`AbstractTransactionStoreManager` 提供公共骨架。内存中的 `GlobalSession`/`BranchSession` 与落盘对象 `GlobalTransactionDO`/`BranchTransactionDO`/`LockDO`（在 `core.store`）之间的互转由 `SessionConverter` 完成——这是"内存对象 ↔ 存储行"的唯一边界。

## Three Backends

| 后端 | 类（包 `server.storage.<mode>.store`） | 写入语义 | 原子性 / 恢复 |
| :--- | :--- | :--- | :--- |
| **db** | `DataBaseTransactionStoreManager` | 写 `global_table` / `branch_table` / `lock_table`，随本地事务提交 | 依赖数据库事务，强一致；恢复即 `SELECT` 未终态会话重放 |
| **file** | `FileTransactionStoreManager` | 追加写事务日志文件（写队列 + 刷盘） | 崩溃后重放日志重建内存会话；吞吐高但需管理文件轮转 |
| **redis** | `RedisTransactionStoreManager` + `RedisLuaTransactionStoreManager`（继承前者） | 用 Redis 结构存会话（key 含 xid/branchId） | 依赖 Redis AOF/RDB；`RedisLua*` 用 Lua 保证多键原子 |

`RedisTransactionStoreManagerFactory` 按配置构造对应实例。三套后端由 `StoreMode` 经 SPI 装配。

## Write and Lifecycle

TC 的 `DefaultCore` 在关键节点调用 storeManager：`begin` → `writeGlobalSession`（新增全局行）；`branchRegister` → `writeBranchSession`（新增分支行）；`globalCommit`/`globalRollback` → 更新状态/写终态；二阶段分支完成 → `removeSession`（清理行）。读恢复时 TC 启动（或 Raft follower 追平后）`readSession` 拉取未终态会话重建内存树。

## Corrections

- **没有 `RaftTransactionStoreManager`**：storage 后端只有 db/file/redis 三套。Raft 模式不引入新存储后端，而是把 `DefaultCore` 的写操作作为 Raft 日志复制，apply 时调用本地 db/file storeManager 落盘。
- **`SessionConverter` 是唯一转换点**：无论后端如何切换，`GlobalSession` ↔ DO 的映射只在 `SessionConverter` 发生，后端只关心 DO 的行存，易扩展新后端。
- **file 后端是"日志追加"而非"随机写"**：顺序追加 + 定期刷盘获得高吞吐，重启走日志重放；与 db 后端"按主键 UPDATE"语义不同。
- **redis 后端的一致性边界**：Redis 自身 AOF everysec / RDB 决定崩溃时可能丢少量最近会话；`RedisLua*` 用 Lua 把多键写包成原子，但不能跨越 Redis 持久化边界。
- **锁与会话解耦存储**：锁走 `LockerManagerFactory` + `LockStore`（db 后端即 `LockStoreDataBaseDAO`），会话走 `TransactionStoreManager`，可按 `StoreMode`/`LockMode` 分别选型，合法混合部署（如 session 用 db、锁用 redis）。

## Links
- [Seata](/docs/CS/Framework/Seata/Seata.md)
- [Architecture](/docs/CS/Framework/Seata/Architecture.md)
- [TC Coordinator](/docs/CS/Framework/Seata/TC_Coordinator.md)
- [Global Lock](/docs/CS/Framework/Seata/Global_Lock.md)
- [Raft HA](/docs/CS/Framework/Seata/Raft_HA.md)
- [Transaction Flow](/docs/CS/Framework/Seata/Transaction_Flow.md)

## References
- Apache Seata source (v2.7.0): https://github.com/apache/seata/tree/v2.7.0
