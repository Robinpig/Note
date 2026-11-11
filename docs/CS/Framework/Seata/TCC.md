# TCC (Seata v2.7.0)

> 源码驱动笔记。基座：apache/seata @ v2.7.0（tag `v2.7.0`，blobless + sparse-checkout 落盘 `tcc` / `spring` / `rm` / `core` / `server`）。类名可在 `tcc/src/main/java/org/apache/seata/rm/tcc/`、`spring/seata-spring/src/main/java/org/apache/seata/rm/fence/`、`core/src/main/java/org/apache/seata/core/protocol/transaction/` 下核对。

## Introduction

TCC 是**业务编码型**两阶段：Try（资源检查/锁定）→ Confirm（确认）/ Cancel（补偿）。与 AT（自动 `undo_log`）、XA（数据库 XA）不同，TCC 不依赖 `undo_log`、不占全局锁，补偿逻辑完全由业务提供，因此性能与一致性上限最高，但侵入性最强（需手写三个方法）。Seata 的 TCC 接入由 `tcc` 模块负责拦截与二阶段反射调用，而**防悬挂 / 空回滚 / 幂等**由 `spring` 模块的 **Common Fence** 机制保障。

## 注解与拦截

`@TwoPhaseBusinessAction`（`tcc/.../api/TwoPhaseBusinessAction.java`）声明一个 TCC 动作：

| 属性 | 默认值 | 含义 |
| :--- | :--- | :--- |
| `name()`（`:54`） | — | 动作名（actionName），TC 侧分支标识 |
| `commitMethod()`（`:61`） | `"commit"` | 二阶段 Confirm 方法名 |
| `rollbackMethod()`（`:68`） | `"rollback"` | 二阶段 Cancel 方法名 |

拦截链路：

- `TccActionInterceptorParser`（`tcc/.../interceptor/parser/`）扫描 `@TwoPhaseBusinessAction` 方法，织入拦截器。
- `TccActionInterceptorHandler`（`tcc/.../interceptor/TccActionInterceptorHandler.java:48`，`extends AbstractProxyInvocationHandler`）在 Try 方法调用前 `createTwoPhaseBusinessActionParam(annotation)`（`:149`）从注解提取 `name/commitMethod/rollbackMethod`，并向 TC 注册 `BranchType.TCC` 分支。
- `TCCResourceManager`（`tcc/.../TCCResourceManager.java`）实现 `ResourceManager`，二阶段由 `RMHandlerTCC`（`tcc/.../rm/tcc/RMHandlerTCC.java`）接收 `BranchCommitRequest` / `BranchRollbackRequest`。

> 注：`TccActionInterceptorHandler` 引用的 `TwoPhaseBusinessActionParam` 来自 `org.apache.seata.integration.tx.api.interceptor`（**`integration-tx-api` 模块，本仓库未落盘**）。该模块是注解/参数/拦截 API 的归属层，补拉后可闭环「注解 → 拦截」的上游链路。

## 二阶段：反射调用业务方法

TC 决策后：

```
TC --BranchCommitRequest(BranchType.TCC)--> RMHandlerTCC
  --> DefaultResourceManager.branchCommit(BranchType.TCC, ...)   // DefaultResourceManager.java:82
  --> TCCResourceManager.branchCommit --> 反射调用 bean.commitMethod(args)
TC --BranchRollbackRequest--> ... --> 反射调用 bean.rollbackMethod(args)
```

Confirm/Cancel 方法名取自一阶段注册时缓存的 `TwoPhaseBusinessActionParam`，由 reflection 在业务 bean 上调用，参数回传原始 `args`。

## Common Fence：防悬挂 / 空回滚 / 幂等

这是 TCC 正确性的关键，实现在 **`spring` 模块**而非 `tcc` 模块：

- `SpringFenceHandler`（`spring/seata-spring/.../rm/fence/SpringFenceHandler.java:61`，`implements FenceHandler`）是 Spring 环境下的 Fence 落地实现。
- 底层通用逻辑在 `org.apache.seata.integration.tx.api.fence.DefaultCommonFenceHandler`（`integration-tx-api`，未落盘），`SpringFenceHandler` 通过 `DefaultCommonFenceHandler.get().setFenceHandler(...)`（`:89`）注入自身。

核心方法：

| 方法 | 阶段 | 关键逻辑 |
| :--- | :--- | :--- |
| `prepareFence(xid, branchId, actionName, callback)`（`:117`） | Try | 在**本地事务**内插入 `common_fence_log` 记录，状态 `STATUS_TRIED`，再执行 Try 回调 |
| `commitFence(commitMethod, bean, xid, branchId, args)`（`:162`） | Confirm | 查 `CommonFenceDO`（`:168`）：`null` → 抛异常（空回滚保护）；`STATUS_COMMITTED` → 幂等返回；`STATUS_ROLLBACKED` / `STATUS_SUSPENDED` → 拒绝（防悬挂） |
| `rollbackFence(...)` | Cancel | 类似：查状态，已 `ROLLBACKED` 幂等；已 `COMMITTED` 冲突报错 |

`CommonFenceDO` 记录 `(xid, branchId, actionName, status)`；状态枚举 `CommonFenceConstant.STATUS_TRIED / COMMITTED / ROLLBACKED / SUSPENDED`。存储经 `CommonFenceStore` / `CommonFenceStoreDataBaseDAO`（`:31`）。

三个经典问题的源码落点：

- **空回滚**：Cancel 先于 Try 到达（Try 网络超时）。`commitFence/rollbackFence` 查 `CommonFenceDO` 为 `null` → 说明 Try 未执行 → 直接插入 `STATUS_SUSPENDED` 占位并返回成功，不再执行业务 Cancel。
- **防悬挂**：Try 在 Cancel 之后才到达。`prepareFence` 插入 `STATUS_TRIED` 前会校验是否已有 `SUSPENDED` 记录，若有则跳过 Try，避免资源被长期锁定。
- **幂等**：Confirm/Cancel 重复下发时，记录已是 `COMMITTED` / `ROLLBACKED` → 直接返回成功，不重复执行业务方法。

## 源码打假 / 设计点

- **TCC 没有 `undo_log`、没有全局锁**：AT 的 Compensation 靠 `undo_log` 自动生成，TCC 的 Compensation 是业务手写的 `rollbackMethod`，RM 仅做反射分发。这意味着 TCC 不依赖 `lockKeys`，隔离完全由业务在 Try 阶段自行实现（如预扣、冻结）。
- **Fence 是「本地事务 + 唯一记录」的原子保证**：`prepareFence` 把「插 fence 记录」与「执行业务 Try」放在同一本地事务，利用 `(xid, branchId)` 唯一约束天然防重，是空回滚/防悬挂/幂等的统一基石。
- **Common Fence 不局限 TCC**：`FenceHandler` 抽象与 `CommonFenceDO` 是通用的，SAGA 也可复用同一套防悬挂机制（由 `CompensationBusinessAction` 等注解触发）。
- **`integration-tx-api` 缺失**：本仓库当前 sparse-checkout 未包含该模块，Fence 的 `DefaultCommonFenceHandler` 与 `@GlobalTransactional` 注解本体需补拉后核对，本文的 Fence 调用链以 `SpringFenceHandler` 为可见边界。

## Links

- [Seata](/docs/CS/Framework/Seata/Seata.md)
- [Architecture](/docs/CS/Framework/Seata/Architecture.md)
- [Transaction Flow](/docs/CS/Framework/Seata/Transaction_Flow.md)
- [TC Coordinator](/docs/CS/Framework/Seata/TC_Coordinator.md)
- [AT and Undo Log](/docs/CS/Framework/Seata/AT_UndoLog.md)
- [XA](/docs/CS/Framework/Seata/XA.md)
