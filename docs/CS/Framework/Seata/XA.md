# XA (Seata v2.7.0)

> 源码驱动笔记。基座：apache/seata @ v2.7.0（tag `v2.7.0`，blobless + sparse-checkout 落盘 `rm` / `rm-datasource` / `core` / `server` 等关键模块）。类名可在 `rm-datasource/src/main/java/org/apache/seata/rm/datasource/xa/`、`rm/src/main/java/org/apache/seata/rm/`、`core/src/main/java/org/apache/seata/core/protocol/transaction/` 下核对。

## Introduction

XA 模式直接复用数据库原生的 **XA 协议**实现两阶段提交：一阶段对资源做 `XA PREPARE`（预提交并持有数据库锁），二阶段由 TC 统一下发 `XA COMMIT` / `XA ROLLBACK`。与 AT（一阶段本地提交 + `undo_log`）相反，XA 的资源锁一直持有到二阶段才释放，因此一致性最强但并发最差。XA 与 AT 共享同一套 TC/TM/RM 角色与 Netty 通道，差别只在 RM 侧 `BranchType` 与一/二阶段的本地语义。

## 数据源代理

XA 模式的数据源代理体系位于 `rm-datasource/.../datasource/xa/`：

| 类 | 职责 |
| :--- | :--- |
| `DataSourceProxyXA`（`xa/DataSourceProxyXA.java:43`） | 标准 XA 数据源代理，包装物理 `XADataSource` |
| `DataSourceProxyXANative`（`xa/DataSourceProxyXANative.java:33`） | 原生 XA 数据源代理（直连 `XADataSource`，不经普通 `DataSource` 适配） |
| `AbstractDataSourceProxyXA`（`xa/AbstractDataSourceProxyXA.java:29`） | 公共基类，继承 `BaseDataSourceResource<ConnectionProxyXA>`，把连接包成 XA 连接代理 |
| `ConnectionProxyXA` | XA 连接代理，持有 `XAResource`，驱动 `XA START/END/PREPARE/COMMIT/ROLLBACK` |

代理入口与 AT 的 `DataSourceProxy` 平行，`DefaultResourceManager` 按 `BranchType` 选择对应的资源管理器（`DefaultResourceManager.java:43` 的 `resourceManagers` 映射、`DefaultResourceManager.java:146` 的 `getResourceManager`）。

## 一阶段：XA 预提交

1. 业务方法在 `@GlobalTransactional` 下执行 SQL，SQL 经 `ConnectionProxyXA` 走 XA 分支。
2. 本地事务以 XA 方式开启：`XAResource.start`（`XA START`）→ 执行业务 SQL → `XAResource.end`（`XA END`）。
3. 预提交：`XAResource.prepare`（`XA PREPARE`）——此时数据库已持久化事务的 redo/undo，并**持有该资源的数据库锁**，但事务仍未提交。
4. RM 向 TC 注册 XA 分支：`DefaultResourceManager.branchRegister(BranchType.XA, ...)`（`DefaultResourceManager.java:80` 的 `branchRegister` → `getResourceManager(branchType).branchRegister`）。

注意：XA 一阶段结束于 `PREPARE`，**不调用本地 commit**——这与 AT 一阶段就本地提交业务数据 + `undo_log` 截然不同。

## 二阶段：统一提交 / 回滚

TC 决策后下发 `BranchCommitRequest` / `BranchRollbackRequest`，RM 侧走标准分派链：

```
TC --BranchCommitRequest--> RMHandlerXA
  --> DefaultResourceManager.branchCommit(BranchType.XA, ...)   // DefaultResourceManager.java:82
  --> ResourceManagerXA.branchCommit(BranchType.XA, xid, branchId, resourceId, ...)
  --> XAResource.commit(xid, false)   // XA COMMIT（一阶段已 PREPARE）
TC --BranchRollbackRequest--> ... --> XAResource.rollback(xid)  // XA ROLLBACK
```

`ResourceManagerXA.branchCommit/branchRollback(BranchType.XA, ...)` 由 `ResourceManagerXATest`（`rm-datasource/.../xa/ResourceManagerXATest.java:88` / `:119`）验证存在。

回滚比 AT 重：AT 回滚靠 `undo_log` 反向补偿（业务数据已提交、锁已释放），而 XA 回滚是数据库原生的 `XA ROLLBACK`，需要回退一阶段 `PREPARE` 持有的资源，且**这把数据库锁从一阶段一直持有到二阶段**，期间阻塞其他对该资源的访问。

## 与 AT 的共存与差异

| 维度 | AT | XA |
| :--- | :--- | :--- |
| 一阶段本地事务 | 直接 commit（业务数据 + `undo_log` 同事务） | `XA PREPARE`，**不 commit**，持数据库锁 |
| 二阶段提交 | 异步删 `undo_log` | `XA COMMIT` |
| 二阶段回滚 | 用 `undo_log` 反向补偿 | `XA ROLLBACK` |
| 资源锁持有 | 一阶段 commit 后即释放，只持全局锁 | 一阶段到二阶段全程持有数据库锁 |
| 数据库要求 | 支持本地 ACID 的关系型库 + `undo_log` 表 | 需驱动支持 XA（`XADataSource`） |
| 性能 | 高（一阶段即释放本地锁） | 差（锁到二阶段才释放） |
| 侵入性 | 无（自动代理） | 无（自动代理） |

两者通过 `DefaultResourceManager` 的 `BranchType` → `ResourceManager` 映射共存于同一 RM 进程；一个应用可同时接入 AT 数据源与 XA 数据源，各自注册对应 `BranchType` 的分支。

## 源码打假 / 设计点

- **XA 不是「Seata 自己实现两阶段」，而是把两阶段委托给数据库 XA**：Seata 只负责 TC 侧的全局协调与分支注册，真正的 prepare/commit/rollback 由 `XAResource` 交给数据库。`RMHandlerXA` 仅是协调入口，不在 RM 侧保存补偿日志。
- **「XA 性能极差」的源码根因**：资源锁从一阶段 `PREPARE` 持有到二阶段 `COMMIT/ROLLBACK`，长事务会长时间阻塞并发访问该资源——这是数据库 XA 协议的固有代价，不是 Seata 的实现问题。
- **XA 一阶段失败/超时**：若 TC 长时间不决策（如 TC 宕机），RM 侧 `PREPARE` 的资源锁一直不释放，需要数据库侧的 `xa_recover` / 事务超时机制介入，Seata RM 本身不主动回滚已 `PREPARE` 的分支。
- **`RMHandlerXA` 在 `org.apache.seata.rm`（不是 `rm-datasource`）**：XA 的 handler 与 AT 的 `RMHandlerAT`（`rm-datasource`）分属不同包，注册由 `DefaultRMHandler` 按 `BranchType` 分派。

## Links

- [Seata](/docs/CS/Framework/Seata/Seata.md)
- [Architecture](/docs/CS/Framework/Seata/Architecture.md)
- [Transaction Flow](/docs/CS/Framework/Seata/Transaction_Flow.md)
- [TC Coordinator](/docs/CS/Framework/Seata/TC_Coordinator.md)
- [AT and Undo Log](/docs/CS/Framework/Seata/AT_UndoLog.md)
- [TCC](/docs/CS/Framework/Seata/TCC.md)
