# Saga

## Introduction

Saga 面向**长事务**：把业务流程拆成一组有序的本地服务调用，正向执行，任一环节失败则按**反向顺序**调用补偿服务，最终一致。与 AT/TCC 的最大区别：Saga 的"分支"不注册为独立 `BranchSession`，而是内化为**状态机（StateMachine）内部步骤**；TC 侧通常只看到一个 `GlobalSession`，Saga 通过 `GlobalReportRequest` 把终态上报 TC。

> 版本基线：apache/seata **v2.7.0**。以下片段均取自该 tag。

## State Machine Definition

状态机以 **JSON** 描述（状态、转移、服务调用、补偿），由 `StateMachineRepositoryImpl`（implements `StateMachineRepository`）加载与缓存。每个 `State` 可挂 `ServiceTask`（正向服务）与 `CompensationTrigger`（失败触发补偿），正向 State 通过 `compensateState` 属性指向其补偿 State。

## Execution Engine

`StateMachineEngine`（`ProcessCtrlStateMachineEngine` 为默认实现）是入口，提供 `start` / `startAsync` / `startWithBusinessKey` / `forward` / `compensate` / `skipAndForward` / `reloadStateMachineInstance`。

正向执行由 `ServiceTaskStateHandler.process` 调 `serviceInvoker.invoke(state, input)`：

```java
StateInstruction instruction = context.getInstruction(StateInstruction.class);
ServiceTaskStateImpl state = (ServiceTaskStateImpl) instruction.getState(context);
String serviceName = state.getServiceName();
String methodName = state.getServiceMethod();
StateInstance stateInstance = (StateInstance) context.getVariable(DomainConstants.VAR_NAME_STATE_INST);

// Set the current task execution status to RU (Running)
stateInstance.setStatus(ExecutionStatus.RU);
ServiceInvoker serviceInvoker =
        stateMachineConfig.getServiceInvokerManager().getServiceInvoker(state.getServiceType());
result = serviceInvoker.invoke(state, input.toArray());
```

## Compensation Is Definition-Driven

**补偿由状态机 JSON 的 `compensateState` 驱动，不是代码硬编码**。`CompensationHolder.findStateInstListToBeCompensated` 只把配了 `compensateState` 的 State 纳入补偿：

```java
if (taskState != null && StringUtils.isNotBlank(taskState.getCompensateState())) {
    stateListToBeCompensated.add(stateInstance);
}
```

`CompensationTriggerStateHandler.process` 把待补偿实例压栈并把状态机标记为"补偿中"（`compensationStatus = RU`）：

```java
Stack<StateInstance> stateStackToBeCompensated =
        CompensationHolder.getCurrent(context, true).getStateStackNeedCompensation();
stateStackToBeCompensated.addAll(stateListToBeCompensated);
// 记录状态机为"补偿中"，后续路由到补偿状态
stateMachineInstance.setCompensationStatus(ExecutionStatus.RU);
```

`TaskStateRouter.compensateRoute` 从栈里 `pop()` 出待补偿实例，按 `compensateStateName` 从 `StateMachine` 取补偿 State 并 `instruction.setStateName(...)`——**栈保证反向补偿顺序**：

```java
Stack<StateInstance> stateStackToBeCompensated =
        CompensationHolder.getCurrent(context, true).getStateStackNeedCompensation();
if (!stateStackToBeCompensated.isEmpty()) {
    StateInstance stateToBeCompensated = stateStackToBeCompensated.pop();
    StateMachine stateMachine = (StateMachine) context.getVariable(DomainConstants.VAR_NAME_STATEMACHINE);
    State state = stateMachine.getState(EngineUtils.getOriginStateName(stateToBeCompensated));
    if (state instanceof AbstractTaskState) {
        AbstractTaskState taskState = (AbstractTaskState) state;
        State compensateState = null;
        String compensateStateName = taskState.getCompensateState();
        if (StringUtils.hasLength(compensateStateName)) {
            compensateState = stateMachine.getState(compensateStateName);
        }
        if (compensateState == null) {
            EngineUtils.endStateMachine(context);
            return null;
        }
        instruction.setStateName(compensateState.getName());
        // ...
        return instruction;
    }
}
```

## Reporting Final State to TC

Saga 的全局事务注册走标准 TM 入口，但终态由 Saga 引擎**主动上报**。`DbAndReportTcStateLogStore.reportTransactionFinished` 把状态机 `ExecutionStatus` 映射成 `GlobalStatus`：

```java
if (ExecutionStatus.SU.equals(machineInstance.getStatus())
        && machineInstance.getCompensationStatus() == null) {
    globalStatus = GlobalStatus.Committed;
} else if (ExecutionStatus.SU.equals(machineInstance.getCompensationStatus())) {
    globalStatus = GlobalStatus.Rollbacked;
} else if (ExecutionStatus.FA.equals(machineInstance.getCompensationStatus())
        || ExecutionStatus.UN.equals(machineInstance.getCompensationStatus())) {
    globalStatus = GlobalStatus.RollbackRetrying;
} else if (ExecutionStatus.FA.equals(machineInstance.getStatus())
        && machineInstance.getCompensationStatus() == null) {
    globalStatus = GlobalStatus.Finished;
}
sagaTransactionalTemplate.reportTransaction(globalTransaction, globalStatus);
```

`DefaultSagaTransactionalTemplate.reportTransaction` → `tx.globalReport` → `DefaultTransactionManager.globalReport` 构造 `GlobalReportRequest` 同步发 TC；TC 侧 `doGlobalReport` 处理。这意味着 Saga 的"二阶段"不是 TC 下发 `BranchCommit/Rollback` 驱动各 RM，而是 **Saga 引擎自己完成补偿后用一条 GlobalReport 告知 TC 终态**。

## Access: Annotation Interception

`SagaAnnotationActionInterceptorHandler`（在 `saga` 模块）与 TCC 的拦截器平行，把 `@CompensationBusinessAction` 等 Saga 注解织入拦截，触发 `StateMachineEngine.start`。Saga 复用标准 TM（`GlobalTransactionContext.reload` / `DefaultTransactionManager`），终态也走同一 `GlobalReportRequest` 到 TC——不是另一套 RM。分支注册可由 `DbStateMachineConfig.isSagaBranchRegisterEnable()` 关闭。

## Corrections

- **Saga 在 TC 侧是"单全局事务 + 无独立分支"**：AT/TCC 的每个参与者是 `BranchSession`，TC 二阶段逐分支下发；Saga 只有顶层 `GlobalSession`，分支编排在引擎内，TC 不感知中间步骤——这是 Saga 能跑长事务、不依赖全局锁的根本原因。
- **补偿由状态机定义驱动**：由 JSON 的 `compensateState` + `Stack` 反向保证，不是硬编码；无 compensateState 的数据更新 State 会直接报错退出。
- **最终一致、弱隔离**：Saga 不持全局锁，正向过程其他事务可看到中间状态，只保证最终一致，需业务容忍并做幂等/补偿。
- **GlobalReport 是 Saga 与 TC 的唯一契约点**：除标准 begin/commit/rollback 外，Saga 额外用 `GlobalReportRequest` 把结果回灌 TC，使其进入终态并释放资源。
- **确有 `DefaultSagaTransactionalTemplate`**：旧笔记称"未落盘"，实际 v2.7.0 的 `saga/seata-saga-spring` 模块有此类，承担终态上报封装。

## Links
- [Seata](/docs/CS/Framework/Seata/Seata.md)
- [Architecture](/docs/CS/Framework/Seata/Architecture.md)
- [Transaction Flow](/docs/CS/Framework/Seata/Transaction_Flow.md)
- [TC Coordinator](/docs/CS/Framework/Seata/TC_Coordinator.md)
- [AT and Undo Log](/docs/CS/Framework/Seata/AT_UndoLog.md)
- [TCC](/docs/CS/Framework/Seata/TCC.md)

## References
- Apache Seata source (v2.7.0): https://github.com/apache/seata/tree/v2.7.0
- Seata Saga docs: https://seata.io/en-us/docs/user/saga/saga_core.html
