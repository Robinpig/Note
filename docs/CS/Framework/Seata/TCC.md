# TCC

## Introduction

TCC 是**业务编码型**两阶段：Try（资源检查/锁定）→ Confirm（确认）/ Cancel（补偿）。与 AT（自动 undo_log）、XA（数据库 XA）不同，TCC 不依赖 undo_log、不占全局锁，补偿逻辑完全由业务提供，性能与一致性上限最高，但侵入性最强（需手写三个方法）。Seata 的 TCC 由 `tcc` 模块负责拦截与二阶段反射调用，**防悬挂 / 空回滚 / 幂等**由 Common Fence 机制保障。

> 版本基线：apache/seata **v2.7.0**。以下片段均取自该 tag。

## Annotation and Interception

`@TwoPhaseBusinessAction` 声明一个 TCC 动作，关键属性：

| 属性 | 默认值 | 含义 |
| :--- | :--- | :--- |
| `name()` | — | 动作名（actionName），TC 侧分支标识 |
| `commitMethod()` | `"commit"` | 二阶段 Confirm 方法名 |
| `rollbackMethod()` | `"rollback"` | 二阶段 Cancel 方法名 |
| `useTCCFence()` | **`false`** | 是否启用 Fence（幂等/空回滚/防悬挂）——**默认关闭** |

```java
/**
 * whether to use TCC fence (idempotent,non_rollback,suspend)
 */
boolean useTCCFence() default false;
```

`TccActionInterceptorHandler` 在 Try 调用前从注解提取参数并向 TC 注册 `BranchType.TCC` 分支，并把开关写进上下文：`businessActionContextMap.put(Constants.USE_COMMON_FENCE, businessAction.useTCCFence())`。

## Phase 2: Reflective Invocation

TC 决策后 `RMHandlerTCC` 收 `BranchCommitRequest`/`BranchRollbackRequest` → `DefaultResourceManager.branchCommit(BranchType.TCC, ...)` → `TCCResourceManager.branchCommit/branchRollback`。未开启 Fence 时直接反射调用业务方法；开启时改由 Fence 在同本地事务内调用：

```java
// add idempotent and anti hanging
if (Boolean.TRUE.equals(businessActionContext.getActionContext(Constants.USE_COMMON_FENCE))) {
    try {
        result = DefaultCommonFenceHandler.get()
                .commitFence(commitMethod, targetTCCBean, xid, branchId, args);
    } catch (SkipCallbackWrapperException | UndeclaredThrowableException e) {
        throw e.getCause();
    }
} else {
    ret = commitMethod.invoke(targetTCCBean, args);
    // ... 解析 TwoPhaseResult / boolean
}
return result ? BranchStatus.PhaseTwo_Committed : BranchStatus.PhaseTwo_CommitFailed_Retryable;
```

## Common Fence: Anti-Hanging / Empty Rollback / Idempotency

**纠偏**：v2.7.0 已没有 `TCCFenceHandler` 类和 `prepareTCCFenceMethod` 等旧命名。真实实现是 `SpringFenceHandler implements FenceHandler`（在 `spring` 模块），由 `DefaultCommonFenceHandler`（在 `integration-tx-api` 模块）单例代理。表名是 **`tcc_fence_log`**，4 个状态：

```java
public static final int STATUS_TRIED = 1;
public static final int STATUS_COMMITTED = 2;
public static final int STATUS_ROLLBACKED = 3;
public static final int STATUS_SUSPENDED = 4;
```

DDL 的 `PRIMARY KEY (xid, branch_id)` 提供唯一约束，查询用 `for update`：

```sql
CREATE TABLE IF NOT EXISTS `tcc_fence_log`
(
    `xid`           VARCHAR(128)  NOT NULL COMMENT 'global id',
    `branch_id`     BIGINT        NOT NULL COMMENT 'branch id',
    `action_name`   VARCHAR(64)   NOT NULL COMMENT 'action name',
    `status`        TINYINT       NOT NULL COMMENT 'status(tried:1;committed:2;rollbacked:3;suspended:4)',
    ...
    PRIMARY KEY (`xid`, `branch_id`),
    ...
) ENGINE = InnoDB
```

三个经典问题的源码落点：

- **Try（`prepareFence`）**：本地事务内插 `STATUS_TRIED` 再执行 Try 回调；唯一键冲突（已有记录）说明此前已 Cancel 过 → 抛 `SkipCallbackWrapperException` **跳过 Try**（防悬挂）：
```java
boolean result = insertCommonFenceLog(conn, xid, branchId, actionName, CommonFenceConstant.STATUS_TRIED);
if (result) {
    return targetCallback.execute();
} else {
    throw new CommonFenceException(... FrameworkErrorCode.InsertRecordError);
}
```
- **空回滚（`rollbackFence`）**：Cancel 先于 Try 到达、查记录为 `null` → 插 `STATUS_SUSPENDED` 占位并**直接返回成功**，不执行业务 Cancel，从而阻止迟到的 Try：
```java
if (commonFenceDO == null) {
    boolean result = insertCommonFenceLog(conn, xid, branchId, actionName, CommonFenceConstant.STATUS_SUSPENDED);
    if (!result) { throw new CommonFenceException(...); }
    return true;
}
```
- **幂等**：Confirm/Cancel 重复下发时，状态已是 `COMMITTED`/`ROLLBACKED`/`SUSPENDED` → 直接返回成功（`commitFence` 里 `STATUS_COMMITTED` return true，`STATUS_ROLLBACKED`/`SUSPENDED` return false 拒绝）。

状态 CAS 与业务方法在**同一本地事务**——`updateCommonFenceDO(..., oldStatus)` 成功后才 `method.invoke`，业务失败则 `setRollbackOnly`：

```java
boolean result = COMMON_FENCE_DAO.updateCommonFenceDO(conn, xid, branchId, status, CommonFenceConstant.STATUS_TRIED);
if (result) {
    Object ret = method.invoke(targetTCCBean, args);
    if (!result) { transactionStatus.setRollbackOnly(); }
}
```

## Corrections

- **TCC 没有 undo_log、没有全局锁**：Compensation 是业务手写的 `rollbackMethod`，RM 仅做反射分发；TCC 不依赖 lockKeys，隔离由业务在 Try 阶段自行实现（预扣、冻结）。
- **Fence 是"本地事务 + 唯一记录"的原子保证**：`prepareFence` 把插记录与执行 Try 放同一本地事务，`(xid, branchId)` 唯一约束天然防重。
- **Fence 默认关闭**：`useTCCFence() default false`，必须显式开启；不要以为 TCC 天然幂等。
- **类名/表名以 v2.7.0 为准**：`DefaultCommonFenceHandler` + `SpringFenceHandler` + `tcc_fence_log`，不是旧资料的 `TCCFenceHandler` / `common_fence_log`。
- **Common Fence 不局限 TCC**：`FenceHandler` 与 `CommonFenceDO` 是通用的，Saga 也可复用（由 `@CompensationBusinessAction` 等触发）。

## Links
- [Seata](/docs/CS/Framework/Seata/Seata.md)
- [Architecture](/docs/CS/Framework/Seata/Architecture.md)
- [Transaction Flow](/docs/CS/Framework/Seata/Transaction_Flow.md)
- [TC Coordinator](/docs/CS/Framework/Seata/TC_Coordinator.md)
- [AT and Undo Log](/docs/CS/Framework/Seata/AT_UndoLog.md)
- [XA](/docs/CS/Framework/Seata/XA.md)

## References
- Apache Seata source (v2.7.0): https://github.com/apache/seata/tree/v2.7.0
- Seata TCC docs: https://seata.io/en-us/docs/user/tcc/tcc_mode.html
