## Introduction

DolphinScheduler 的**注册中心**承担节点注册、心跳、分布式锁与 failover 感知；**容错**则通过一套系统事件（`SystemEventBus`）驱动。3.4.3 把注册中心抽象为可插拔插件（ZooKeeper / JDBC / etcd），生产默认 ZooKeeper，standalone 演示默认 JDBC+H2。本文拆解 Registry 抽象、三类节点路径、三种实现与三类 failover 事件。

## Registry Abstraction

API 在 `dolphinscheduler-registry/dolphinscheduler-registry-api`。核心接口 `RegistryClient`（`registry/api/RegistryClient`），提供：`getChildren` / `persistEphemeral` / `persistPersistent` / `remove` / `subscribe` / `acquireLock`（`RegistryLock`）/ 心跳等；事件用 `SubscribeListener`，连接状态 `RegistryConnectionState`，节点类型枚举 `RegistryNodeType`。

### RegistryNodeType

`registry/api/enums/RegistryNodeType.java:25` 完整路径：

| 节点类型 | registryPath | 用途 |
|---------|--------------|------|
| MASTER | `/nodes/master` | Master 注册节点 |
| WORKER | `/nodes/worker` | Worker 注册节点 |
| MASTER_COORDINATOR | `/nodes/master-coordinator` | 选主 Coordinator |
| ALERT_SERVER | `/nodes/alert-server` | Alert Server 注册 |
| ALERT_HA_LEADER | `/nodes/alert-server-ha-leader` | Alert HA 选主 |
| FAILOVER_FINISH_NODES | `/nodes/failover-finish-nodes` | failover 完成标记 |
| GLOBAL_MASTER_FAILOVER_LOCK | `/lock/global-master-failover` | 全局 failover 锁 |
| MASTER_FAILOVER_LOCK | `/lock/master-failover` | Master failover 锁 |
| MASTER_TASK_GROUP_COORDINATOR_LOCK | `/lock/master-task-group-coordinator` | TaskGroup 协调锁 |
| MASTER_SERIAL_COORDINATOR_LOCK | `/lock/master-serial-workflow-coordinator` | 串行工作流协调锁 |

> 锁语义：failover / TaskGroup / 串行工作流都依赖对应的 `RegistryLock`，由健康 Master 抢锁后独占执行，避免重复处理。

## Three Implementations

`dolphinscheduler-registry/dolphinscheduler-registry-plugins/`：

- **ZooKeeper（默认，生产）**：`dolphinscheduler-registry-zookeeper`，基于 Curator（`curator-framework` 5.5.0，ZooKeeper 3.8.3，见 BOM）。API 模块的 `application.yaml` 默认 `registry.type: zookeeper`（`dolphinscheduler-api/.../application.yaml:126`）。
- **JDBC（standalone 默认）**：`dolphinscheduler-registry-jdbc`，用数据库表轮询 + 变更事件实现注册/锁/心跳。schema 提供 `t_ds_jdbc_registry_data` / `t_ds_jdbc_registry_lock` / `t_ds_jdbc_registry_client_heartbeat` / `t_ds_jdbc_registry_data_change_event`（`dolphinscheduler_mysql.sql:1350+`）。standalone 的 `application.yaml` 默认 `registry.type: jdbc` + H2。
- **etcd**：`dolphinscheduler-registry-etcd`，基于 etcd 客户端实现同款接口。

## Failover

failover 由 `SystemEventBus`（`engine/system/SystemEventBus.java:36`，继承 `AbstractDelayEventBus<AbstractSystemEvent>`）驱动，三类事件位于 `engine/system/event/`：

| 事件 | Handler | 触发与处理 |
|------|---------|-----------|
| `GlobalMasterFailoverEvent` | `GlobalMasterFailoverEventHandler` | Master 启动即 `publish`（见 [Master](/docs/CS/Framework/Job/DolphinScheduler/Master.md) 启动序列），对**所有**尚在 `needFailover` 状态（非终态且 `needFailover=true`）的工作流实例做全局恢复。 |
| `MasterFailoverEvent` (`MASTER_FAILOVER`) | `MasterFailoverEventHandler` | 某 Master 失联时触发；`handle()` 委托 `FailoverCoordinator.failoverMaster()`（`MasterFailoverEventHandler.java:35`），恢复归属该死 Master 的工作流实例。 |
| `WorkerFailoverEvent` (`WORKER_FAILOVER`) | `WorkerFailoverEventHandler` | 某 Worker 失联时触发，恢复其上正在运行的物理任务（重新派发 / 标记 `NEED_FAULT_TOLERANCE`）。 |

### FailoverCoordinator

`server/master/failover/FailoverCoordinator.java:55`（`@Component implements IFailoverCoordinator`）依赖：`RegistryClient`、`ClusterManager`、`IWorkflowRepository`、`TaskFailover`、`WorkflowInstanceDao`。它持有 `RegistryLock` 保证同一时刻只有一个 Master 执行 failover，扫描 DB 中 `WorkflowExecutionStatus.NEED_FAILOVER_STATES` 的实例并重建 `IWorkflowExecution` 重新纳入事件总线。

### Task Failover / Retry

- 任务级容错：`TaskExecutionStatus.shouldFailover()` = {SUBMITTED_SUCCESS, DISPATCH, RUNNING_EXECUTION, DELAY_EXECUTION}（`TaskExecutionStatus.java:93`）；Worker 失联时这些状态的任务会被 `WorkerFailoverEvent` 重新派发。
- 重试：`TaskRetryLifecycleEvent` / `TaskFatalLifecycleEvent` 由对应 handler 处理；超时由 `TaskTimeoutLifecycleEvent` 处理。重试次数 / 间隔由任务定义参数决定（`Flag.YES` 控制超时告警等）。
- `MasterConfig.killApplicationWhenTaskFailover`（默认 `true`，`MasterConfig.java:61`）：任务 failover 前先 kill Yarn/K8s 应用，避免孤儿作业。

## Links
- [DolphinScheduler](/docs/CS/Framework/Job/DolphinScheduler)
- [DolphinScheduler Master Engine](/docs/CS/Framework/Job/DolphinScheduler/Master.md)
- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)

## References

- [apache/dolphinscheduler @ 3.4.3](https://github.com/apache/dolphinscheduler/releases/tag/3.4.3)
- 源码模块：`dolphinscheduler-registry/`、`dolphinscheduler-master/.../engine/system/event/`、`dolphinscheduler-master/.../failover/`
