## Introduction

Master 是 DolphinScheduler 的**调度大脑**。3.4.3 的 Master 内核是一个**事件总线驱动的状态机引擎**：它不再用「一个大循环 + 一堆 if 分支」处理工作流状态，而是把工作流/任务/系统三类生命周期抽象成事件（`AbstractLifecycleEvent`），由各自的 `ILifecycleEventHandler` 消费。本文以源码（`apache/dolphinscheduler@3.4.3`，模块 `dolphinscheduler-master`）逐层拆解。

源码入口：`MasterServer.main` → `@PostConstruct initialized()`（`dolphinscheduler-master/.../MasterServer.java:117`）。

## Startup Sequence

`MasterServer.initialized()` 的启动顺序（`MasterServer.java:117-144`）：

1. `masterRPCServer.start()` —— 启动 Netty RPC Server（监听 `master.listen-port`，默认 **5678**，`MasterConfig.java:47`）。
2. `TaskPluginManager.loadTaskPlugin()` + `DataSourcePluginManager.loadDataSourcePlugin()` —— 加载任务/数据源插件（SPI）。
3. `masterRegistryClient.start()` —— 向 Registry 注册 `/nodes/master/<ip:port>`，开始心跳（间隔 `max-heartbeat-interval`，默认 **10s**，`MasterConfig.java:56`）。
4. `masterCoordinator.start()` —— 选主 Master-Coordinator 节点。
5. `clusterManager.start()` + `clusterStateMonitors.start()` —— 维护健康 Master/Worker 列表。
6. `workflowEngine.start()` —— 拉起 `WorkflowEventBusCoordinator` + `CommandEngine` + `WorkerGroupDispatcherCoordinator` + `LogicTaskEngineDelegator`（`WorkflowEngine.java:53-64`）。
7. `schedulerApi.start()` —— Quartz 调度器启动。
8. `publish(GlobalMasterFailoverEvent)` + `systemEventBusFireWorker.start()` —— 发布全局 failover 事件，启动系统事件消费线程。

## CommandEngine and Slot

`CommandEngine`（`engine/command/CommandEngine.java:64`）是一个 `BaseDaemonThread`（`MasterCommandLoopThread`），`@Service` 单例：

- 线程池：`commandHandleThreadPool = newDaemonFixedThreadExecutor("MasterCommandHandleThreadPool", CPUs)`（`CommandEngine.java:107-108`）。
- 主循环（`run()`，`CommandEngine.java:122`）：先做 `masterServerLoadProtection.isOverload` 过载保护；否则 `commandFetcher.fetchCommands()`，空则 `sleep(SLEEP_TIME_MILLIS=1s)`；非空则对每个 Command 走 `supplyAsync → bootstrapCommand → bootstrapWorkflowExecution → bootstrapSuccess`，全部 `join()`。
- 失败处理（`bootstrapError`，`CommandEngine.java:195`）：`transactionTemplate` 内把工作流实例强制置 `FAILURE`，并把 Command 移入 `t_ds_error_command`（`commandService.moveToErrorCommand`）。

### Slot-based Fetch

`CommandFetcherConfiguration`（`engine/command/CommandFetcherConfiguration.java:39`）目前只支持 `ID_SLOT_BASED` 一种策略。`IdSlotBasedCommandFetcher.fetchCommands()`（`engine/command/IdSlotBasedCommandFetcher.java:57`）：

```java
commandDao.queryCommandByIdSlot(currentSlotIndex, totalSlot, idStep, fetchSize);
```

- `currentSlot` / `totalSlots` 来自 `MasterSlotManager`（`cluster/MasterSlotManager.java`）。`doReBalance()` 把健康 Master 按 `address` 排序后，当前 Master 的下标即 `currentSlot`，健康 Master 总数即 `totalSlots`；初始值均为 `-1 / 0`（`MasterSlotManager.java:38-44`）。
- 分片 SQL 语义等价于 `command.id % totalSlots == currentSlot`，多个 Master 无锁分摊 Command 拉取。
- 配置（`config/CommandFetchStrategy.java`）：`IdSlotBasedFetchConfig.idStep = 1`、`fetchSize = 10`。

> 与老版本差异：老版是「所有 Master 抢同一批 Command + ZK 分布式锁」，3.4.x 改为**静态 slot 分片**，彻底消除抢锁竞争。

## WorkflowEngine and EventBus

`WorkflowEngine`（`engine/WorkflowEngine.java:36`）组合四个引擎组件：`WorkflowEventBusCoordinator`、`CommandEngine`、`WorkerGroupDispatcherCoordinator`、`LogicTaskEngineDelegator`。

事件总线是 3.4 内核的核心抽象，分三类（均继承 `AbstractDelayEventBus<AbstractLifecycleEvent>`）：

| 事件总线 | 类 | 事件类型枚举 |
|---------|----|------------|
| 工作流生命周期 | `WorkflowEventBus` | `WorkflowLifecycleEventType` |
| 任务生命周期 | `TaskDispatchableEventBus` / Task 级 EventBus | `TaskLifecycleEventType` |
| 系统事件（failover） | `SystemEventBus` | `SystemEventType`（MASTER_FAILOVER / WORKER_FAILOVER / GLOBAL_MASTER_FAILOVER） |

### Workflow Lifecycle Events

`WorkflowLifecycleEventType`（`engine/workflow/lifecycle/WorkflowLifecycleEventType.java:22`）涵盖：`WorkflowStart` / `WorkflowStop` / `WorkflowStopped` / `WorkflowTimeout` / `WorkflowPause` / `WorkflowPaused` / `WorkflowSucceed` / `WorkflowFailed` / `WorkflowFinalize` / `WorkflowTopologyLogicalTransitionWithTaskFinish`。每个事件有一个对应 `AbstractWorkflowLifecycleEventHandler`（位于 `engine/workflow/lifecycle/handler/`）。

### Task Lifecycle Events

`TaskLifecycleEventType`（`engine/task/lifecycle/TaskLifecycleEventType.java:22`）涵盖：`TaskDispatch` / `TaskDispatched` / `TaskStart` / `TaskRunning` / `TaskSuccess` / `TaskFailed` / `TaskFatal` / `TaskTimeout` / `TaskKilled` / `TaskKill` / `TaskPaused` / `TaskPause` / `TaskRetry` / `TaskFailover` / `TaskRuntimeContextChanged`，handler 位于 `engine/task/lifecycle/handler/`。

### Dispatching Pipeline

`bootstrapWorkflowExecution`（`CommandEngine.java:170`）把工作流实例 `put` 进 `IWorkflowRepository`，`registerWorkflowEventBus` 并 `publish(WorkflowStartLifecycleEvent)`。之后整条状态推进完全由 handler 发布/订阅事件驱动，形成「事件 → handler → 可能再发事件」的闭环。

## LogicTask vs PhysicalTask

`engine/executor/LogicTaskExecutor.java:31` 与 Worker 侧的 `PhysicalTaskExecutor` 都继承公共模块的 `AbstractTaskExecutor`（`dolphinscheduler-task-executor`）。

- **LogicTask**：CONDITIONS / DEPENDENT / SUB_WORKFLOW / SWITCH 四类。在 **Master 本地**经 `ILogicTask` 插件执行（`LogicTaskExecutor.initializeTaskPlugin` 通过 `LogicTaskPluginFactoryBuilder` 创建 `ILogicTask`，`LogicTaskExecutor.java:49-54`）；`doTriggerTaskPlugin` 调 `logicTask.start()`（`LogicTaskExecutor.java:58`）。插件位于 `engine/executor/plugin/{condition,dependent,subworkflow,switchtask}`。
- **PhysicalTask**：其余 33 类任务，下发 Worker 执行（见 [Worker and RPC](/docs/CS/Framework/Job/DolphinScheduler/Worker_RPC.md)）。

`LogicTaskConfig`（`MasterConfig.java:51`，默认线程池大小等由 `logicTaskConfig` 承载）控制逻辑任务并发。

## WorkflowGraph and Topology

`engine/graph/WorkflowGraph.java:33` 用两个邻接表表达 DAG：

- `predecessors: Map<String, List<String>>`、`successors: Map<String, List<String>>`，外加 `taskDefinitionMap` / `taskDefinitionCodeMap`。
- 构建（`addTaskEdge`，`WorkflowGraph.java:122`）：遍历 `WorkflowTaskRelation`，`pre>0 && post>0` 时建立双向边；同名任务 / 同 code 任务 / 重复边都会抛 `IllegalArgumentException`。
- `getStartNodes()`（`WorkflowGraph.java:67`）= 入度为 0（`predecessors` 为空）的节点，即无依赖的根节点。
- 环检测：在 `addTaskEdge` 阶段通过「边已存在即抛异常」间接防重边；整体 DAG 合法性由 `WorkflowTaskRelation` 全量加载后的邻接表保证（无显式 `addEdge` 环检测 API，靠数据约束 + 运行时拓扑推进收敛）。
- 后继推进：任务完成后由 `WorkflowTopologyLogicalTransitionWithTaskFinishLifecycleEventHandler` 调 `getSuccessors` 计算可运行后继节点。

## State Machines

### WorkflowExecutionStatus

`common/enums/WorkflowExecutionStatus.java:27`，每个枚举携带多维度布尔（code / canStop / canDirectStopInDB / canPause / canDirectPauseInDB / finalState / needFailover）：

| code | 状态 | final? | needFailover? |
|------|------|--------|---------------|
| 0 | SUBMITTED_SUCCESS | — | — |
| 1 | RUNNING_EXECUTION | — | ✓ |
| 2 | READY_PAUSE | — | ✓ |
| 3 | PAUSE | ✓ | — |
| 4 | READY_STOP | — | — |
| 5 | STOP | ✓ | — |
| 6 | FAILURE | ✓ | — |
| 7 | SUCCESS | ✓ | — |
| 14 | SERIAL_WAIT | — | ✓ |
| 18 | FAILOVER | — | — |

`NEED_FAILOVER_STATES` / `NOT_TERMINAL_STATES`（`WorkflowExecutionStatus.java:99-107`）由这些布尔派生，供 failover 扫描与状态机判定使用。

### TaskExecutionStatus

`plugin/task/api/enums/TaskExecutionStatus.java:25`：SUBMITTED_SUCCESS(0)、RUNNING_EXECUTION(1)、PAUSE(3)、FAILURE(6)、SUCCESS(7)、NEED_FAULT_TOLERANCE(8)、KILL(9)、DELAY_EXECUTION(12)、FORCED_SUCCESS(13)、DISPATCH(17)。`shouldFailover()` = {SUBMITTED_SUCCESS, DISPATCH, RUNNING_EXECUTION, DELAY_EXECUTION}（`TaskExecutionStatus.java:93`）。

### TaskExecutorState (运行时)

公共模块 `task/executor/TaskExecutorState.java:22`：INITIALIZED / RUNNING / PAUSED(final) / KILLED(final) / FAILED(final) / SUCCEEDED(final)。这是 TaskExecutor 运行期的轻量状态，经 `TaskExecutorStateMappings.mapState` 映射到持久化的 `TaskExecutionStatus`。

## Task Dispatch and LoadBalancer

`engine/task/dispatcher/WorkerGroupDispatcher.java:47` 是一个 `BaseDaemonThread`，**每个 worker group 一个实例**，从 `TaskDispatchableEventBus` 取 `TaskDispatchableEvent` 并调用 `taskExecutorClient.dispatch(taskExecution)`（`doDispatchTask`，`WorkerGroupDispatcher.java:110`）。

- 重试退避：派发失败回队，等待时间随失败次数增长，夹在 **1s ~ 60s** 之间（`WorkerGroupDispatcher.java:134-135`）。
- 超时：若 `TaskDispatchPolicy.isDispatchTimeoutEnabled()`，超过 `maxTaskDispatchDuration` 则直接发 `TaskFailedLifecycleEvent` 永久失败（`WorkerGroupDispatcher.java:146`）。
- 负载均衡：`cluster/loadbalancer/` 下有 `RandomWorkerLoadBalancer` / `RoundRobinWorkerLoadBalancer` / `FixedWeightedRoundRobinWorkerLoadBalancer` / `DynamicWeightedRoundRobinWorkerLoadBalancer`，由 `WorkerLoadBalancerType`（`RANDOM/ROUND_ROBIN/FIXED_WEIGHTED_ROUND_ROBIN/DYNAMIC_WEIGHTED_ROUND_ROBIN`）选择。默认 **ROUND_ROBIN**（`WorkerLoadBalancerConfigurationProperties.java:27`）；standalone 演示环境默认 `DYNAMIC_WEIGHTED_ROUND_ROBIN`（`application.yaml:209`）。`DYNAMIC_WEIGHTED` 的权重默认 cpu=30 / memory=30 / taskThreadPool=40（`WorkerLoadBalancerConfigurationProperties.java:38-42`）。

## TaskGroup

`engine/TaskGroupCoordinator.java:63`（`@Component`，`BaseDaemonThread`）协调任务组槽位：它扫描 `t_ds_task_group` / `t_ds_task_group_queue`，按 `TaskGroupQueueStatus` 发放槽位，并通过 RPC（`TaskGroupSlotAcquireSuccessNotifyRequest` → Master `ITaskInstanceController`）通知 Master 某任务已获槽位可派发。`DEFAULT_LIMIT = 1000`（单批处理上限，`TaskGroupCoordinator.java:84`）。

## Links
- [DolphinScheduler](/docs/CS/Framework/Job/DolphinScheduler)
- [DolphinScheduler Worker and RPC](/docs/CS/Framework/Job/DolphinScheduler/Worker_RPC.md)
- [DolphinScheduler Registry and Failover](/docs/CS/Framework/Job/DolphinScheduler/Registry_Failover.md)
- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)

## References

- [apache/dolphinscheduler @ 3.4.3](https://github.com/apache/dolphinscheduler/releases/tag/3.4.3)
- 源码模块：`dolphinscheduler-master/src/main/java/org/apache/dolphinscheduler/server/master/engine/`
