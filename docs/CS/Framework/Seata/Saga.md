# Saga (Seata v2.7.0)

> 源码驱动笔记。基座：apache/seata @ v2.7.0（tag `v2.7.0`，blobless + sparse-checkout 落盘 `saga` / `tm` / `core` / `server`）。类名可在 `saga/seata-saga-engine/src/main/java/org/apache/seata/saga/engine/`、`saga/seata-saga-annotation/`、`tm/src/main/java/org/apache/seata/tm/`、`core/src/main/java/org/apache/seata/core/protocol/transaction/` 下核对。

## Introduction

Saga 面向**长事务**：把业务流程拆成一组有序的本地服务调用， forward 执行，任一环节失败则按**反向顺序**调用补偿服务，最终达到一致。与 AT/TCC 的最大区别是：Saga 的「分支」不向 TC 注册为独立 `BranchSession`，而是内化为**状态机（StateMachine）内部步骤**；TC 侧通常只看到一个全局事务（一个 `GlobalSession`），Saga 通过 `GlobalReportRequest` 把最终状态（成功 / 失败 / 补偿中）上报给 TC。

## 状态机定义与加载

状态机以 **JSON** 描述（状态、转移、服务调用、补偿），由仓库加载：

- `StateMachineRepositoryImpl`（`saga/seata-saga-engine/.../repo/impl/StateMachineRepositoryImpl.java:45`，`implements StateMachineRepository`）负责加载与缓存状态机定义；其内部 `jsonParserName`（`:65`）指定 JSON 解析器（`DomainConstants.DEFAULT_JSON_PARSER`）。
- 一个状态机由若干 `State` 组成，每个 `State` 可挂 `ServiceTask`（正向服务调用）与 `CompensationTrigger`（失败时触发补偿）。

## 执行引擎

`StateMachineEngine`（`saga/seata-saga-engine/.../engine/StateMachineEngine.java:29`）是入口接口，`ProcessCtrlStateMachineEngine` 为默认实现：

| 方法（`:40`–`:172`） | 语义 |
| :--- | :--- |
| `start(name, tenantId, startParams)` | 同步启动状态机 |
| `startAsync(...)` / `startWithBusinessKeyAsync(...)` | 异步启动 |
| `startWithBusinessKey(...)` | 带业务键启动（幂等/去重用） |
| `forward(instId, replaceParams)` | 从指定节点继续向前 |
| `compensate(instId, replaceParams)` | 反向补偿 |
| `skipAndForward(instId, ...)` | 跳过当前节点继续 |
| `reloadStateMachineInstance(instId)` | 重载状态机实例快照 |

执行流：`StateMachineEngine.start` → 驱动状态逐个 `ServiceTaskHandler` 调用正向服务 → 任一步骤抛异常 → 沿反向路径调用各步骤的补偿服务 → 全程记录 `StateMachineInstance`（状态、上下文、补偿进度）。

## 与 TC 的边界：GlobalReportRequest

Saga 的全局事务注册走标准 `DefaultTransactionManager.begin`（与 AT/TCC 共用 TM 入口），但状态机执行与补偿是独立的引擎逻辑。其特有交互是**状态上报**：

- `GlobalReportRequest`（`core/protocol/transaction/GlobalReportRequest`）由 `DefaultTransactionManager.globalReport` 构造并发送（`tm/src/main/java/org/apache/seata/tm/DefaultTransactionManager.java:122`）。
- TC 侧由 `AbstractTCInboundHandler.handle(GlobalReportRequest)` 处理（`server/src/main/java/org/apache/seata/server/AbstractTCInboundHandler.java:361`），根据上报状态（`GlobalStatus`）推进全局事务——成功则直接完结，失败/补偿中则 TC 标记相应终态。

这意味着 Saga 的「二阶段」不是 TC 下发 `BranchCommit/Rollback` 驱动各 RM，而是 **Saga 引擎自己完成补偿后，用一条 GlobalReport 告知 TC 最终结果**。

## 接入：注解拦截

`SagaAnnotationActionInterceptorHandler`（`saga/seata-saga-annotation/.../interceptor/`）与 TCC 的 `TccActionInterceptorHandler` 平行，负责把 `@CompensationBusinessAction` 等 Saga 注解织入拦截，触发 `StateMachineEngine.start`。

> 注：本仓库 sparse-checkout **未落盘 `SagaTransactionalTemplate` 类**（Grep 全仓无匹配）。Saga 的全局事务发起在源码中复用标准 `TransactionalTemplate` / `DefaultGlobalTransaction` 路径，状态机执行则完全在 `StateMachineEngine` 内部。若后续补拉 `tm` 模块全量源码，需回查是否另有 Saga 专用的事务模板封装。

## 源码打假 / 设计点

- **Saga 在 TC 侧是「单全局事务 + 无分支」**：AT/TCC 的每个参与者是一个 `BranchSession`，TC 二阶段逐分支下发；Saga 只有顶层 `GlobalSession`，分支编排发生在 Saga 引擎内，TC 不感知中间步骤。这是 Saga 能跑长事务、且不强依赖全局锁的根本原因。
- **补偿由业务驱动，不是 TC 驱动**：Saga 的回滚（补偿）是引擎按状态机反向调用业务补偿服务，与 AT 的 `undo_log` 自动补偿、TCC 的 `rollbackMethod` 反射调用都不同——Saga 的补偿逻辑写在状态机 JSON 里，最灵活也最重。
- **最终一致、弱隔离**：Saga 不持全局锁，forward 过程中其他事务可看到中间状态（无写隔离），只保证最终一致。需要业务容忍「已部分完成」的可见性，或靠业务层加状态机状态机幂等/补偿。
- **GlobalReport 是 Saga 与 TC 的唯一契约点**：除了标准的 begin/commit/rollback，Saga 额外用 `GlobalReportRequest` 把状态机结果回灌 TC，使 TC 的 `GlobalSession` 能正确进入终态并释放资源。

## Links

- [Seata](/docs/CS/Framework/Seata/Seata.md)
- [Architecture](/docs/CS/Framework/Seata/Architecture.md)
- [Transaction Flow](/docs/CS/Framework/Seata/Transaction_Flow.md)
- [TC Coordinator](/docs/CS/Framework/Seata/TC_Coordinator.md)
- [AT and Undo Log](/docs/CS/Framework/Seata/AT_UndoLog.md)
- [TCC](/docs/CS/Framework/Seata/TCC.md)
