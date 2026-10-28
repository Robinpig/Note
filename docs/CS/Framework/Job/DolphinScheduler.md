## Introduction

[Apache DolphinScheduler](https://dolphinscheduler.apache.org/)（海豚调度）是一个分布式、易扩展的**可视化 DAG 工作流任务调度系统**。3.x 主线在 3.4.3（2026-09-08 发布）做了一次**引擎级重构**：调度内核从「线程轮询 + 硬编码 Command 命令码 + XXXProcessor 反射分发」演进为**事件总线（EventBus）驱动的状态机引擎**，进程间通信从自研二进制 `Command` 协议升级为**基于 Netty 的注解式 RPC 框架（`@RpcService` / `@RpcMethod`，JSON 序列化）**。

技术栈：各角色均为 Spring Boot 应用（Spring Boot 2.7.11，编译目标 Java 8），Netty 4.1.53 承载 RPC，Quartz 2.3.2 负责定时触发，注册中心可插拔 ZooKeeper（默认）／JDBC／etcd，元数据存储支持 MySQL / PostgreSQL / H2 三套 schema。

> 版本基线：本文所有事实以 **tag 3.4.3** 源码为准（`apache/dolphinscheduler@3.4.3`）。3.4.0 已移除 PYTORCH 任务类型；3.4.3 引入 `ScheduleMissedFirePolicy`（DSIP-107）。

## Architecture

DolphinScheduler 由一组**去中心化、可水平扩展**的角色构成，按职责划分为接入层、调度层（Master）、执行层（Worker）、协调/存储层、辅助服务五类。

```
                          ┌────────────┐         ┌────────────┐
        Browser ─────────► │  API Server │ ◄─────►│  Web UI    │  (Vue3 + Vite)
          :12345           │  (Spring)  │         │  :12345    │
                          └─────┬──────┘         └────────────┘
                                │  写 Command / 直接 RPC 触发
                                ▼
   ╔═════════════════════════════════════════════════════════════════════════╗
   ║  Master  (:5678)  —— 调度大脑                                          ║
   ║   CommandEngine  →  slot 分片拉取 t_ds_command（fetchSize=10）            ║
   ║   WorkflowEngine →  WorkflowEventBus（状态机驱动）                        ║
   ║      ├─ LogicTaskExecutor    本地执行  CONDITIONS/DEPENDENT/             ║
   ║      │                        SUB_WORKFLOW/SWITCH                       ║
   ║      └─ WorkerGroupDispatcher → 经 RPC 把 PhysicalTask 派发到 Worker      ║
   ╚═════════════════════════════════════════════════════════════════════════╝
                                │  Netty RPC（@RpcService/@RpcMethod, JSON）
                                ▼
   ╔═════════════════════════════════════════════════════════════════════════╗
   ║  Worker  (:1234)  —— 执行手脚                                          ║
   ║   PhysicalTaskExecutor → AbstractTask 插件（SPI, 37 种任务类型）         ║
   ║       → 本地进程 / Yarn / K8s / 远程 Shell                              ║
   ╚═════════════════════════════════════════════════════════════════════════╝

   Registry    : ZooKeeper(默认)/JDBC/etcd  —— /nodes/master, /nodes/worker, /lock/*
   Quartz(DB)  : QRTZ_* 表作为定时器 → 触发时经 RPC 发 WorkflowScheduleTriggerRequest
   AlertServer (:50052) : 告警插件（email/dingtalk/feishu/wechat/slack/...）
```

### Role Summary

| 角色 | 默认端口 | 进程 | 核心职责 |
|------|---------|------|---------|
| API Server | 12345 | `dolphinscheduler-api` | 接收 UI 请求、鉴权、写 Command、项目/资源/数据源管理 |
| Master | 5678 | `dolphinscheduler-master` | slot 分片消费 Command、WorkflowEngine、事件总线、任务派发 |
| Worker | 1234 | `dolphinscheduler-worker` | PhysicalTaskExecutor 执行具体任务插件 |
| Alert Server | 50052(RPC) / 50053(HTTP) | `dolphinscheduler-alert` | 告警实例分发到告警插件 |
| Registry | — | 插件 | 节点注册、分布式锁、心跳、failover 感知 |
| Quartz | — | 内嵌 Master | 定时触发（`QRTZ_*` 表持久化） |

### Engine Paradigm Shift (3.4.x)

1. **事件总线取代轮询处理器**：工作流/任务生命周期由 `WorkflowEventBus` / `TaskLifecycleEvent` / `SystemEventBus` 三类事件总线驱动，每个事件对应一个 `ILifecycleEventHandler`（如 `WorkflowStartLifecycleEventHandler`），不再有老式的 `StateEventHandle` 大分支。
2. **RPC 框架取代 Command+Processor**：Master↔Worker、Master↔Master 之间的通信统一走 `dolphinscheduler-extract`（`NettyRemotingServer`/`NettyRemotingClient` + `@RpcService`/`@RpcMethod`，`JsonSerializer`）。老式 `org.apache.dolphinscheduler.common.command.Command` 命令码枚举已不再用于节点间通信。
3. **slot 分片消费 Command**：`IdSlotBasedCommandFetcher` 按 `command.id % totalSlots == currentSlot` 分片拉取，多 Master 之间天然负载均衡，无需 ZK 抢锁。
4. **LogicTask 与 PhysicalTask 分离**：CONDITIONS/DEPENDENT/SUB_WORKFLOW/SWITCH 四类「逻辑任务」在 Master 本地经 `ILogicTask` 执行；其余 33 类「物理任务」经 RPC 下发 Worker，由 `AbstractTask` 插件执行。

## Workflow

一次工作流从触发到结束的链路：

1. **触发**：UI/API 运行 → 写一条 `Command` 进 `t_ds_command`（`CommandType` 如 `START_PROCESS`）；定时任务由 Quartz 触发后**直接经 RPC** 发 `WorkflowScheduleTriggerRequest` 到 Master（不再写 Command）。
2. **Master 拉取**：`CommandEngine` 循环调用 `IdSlotBasedCommandFetcher.fetchCommands()`，按 slot 取回本 Master 负责的 Command；无命令时 sleep 1s。
3. **实例化**：`WorkflowExecutionFactory.createWorkflowExecuteRunnable(command)` 建工作流实例，注册 `WorkflowEventBus` 并 `publish(WorkflowStartLifecycleEvent)`，状态置 `SUBMITTED_SUCCESS→RUNNING_EXECUTION`。
4. **拓扑推进**：`WorkflowGraph`（predecessor/successor 邻接表）从 `WorkflowTaskRelation` + `TaskDefinition` 构建；`WorkflowTopologyLogicalTransitionWithTaskFinishLifecycleEvent` 在任务完成后计算后继节点。
5. **任务派发**：根节点/可运行节点 → 若为逻辑任务在 Master 本地 `LogicTaskExecutor` 执行；若为物理任务入 `WorkerGroupDispatcher` 的 `TaskDispatchableEventBus`，按 worker group + 负载均衡（`WorkerLoadBalancerType`，默认 `ROUND_ROBIN`）经 RPC `dispatch`。
6. **Worker 执行**：`PhysicalTaskExecutor` 加载对应 `AbstractTask` 插件，fork 子进程/提交 Yarn/K8s，运行时事件经 RPC 回传 Master 驱动状态机。
7. **终结**：所有叶子完成 → `WorkflowSucceedLifecycleEvent` / `WorkflowFailedLifecycleEvent` → `WorkflowFinalizeLifecycleEvent` 落库并触发告警。

## Links
- [DolphinScheduler Master Engine](/docs/CS/Framework/Job/DolphinScheduler/Master.md)
- [DolphinScheduler Worker and RPC](/docs/CS/Framework/Job/DolphinScheduler/Worker_RPC.md)
- [DolphinScheduler Task Plugin](/docs/CS/Framework/Job/DolphinScheduler/Task_Plugin.md)
- [DolphinScheduler Registry and Failover](/docs/CS/Framework/Job/DolphinScheduler/Registry_Failover.md)
- [DolphinScheduler Scheduler and Deploy](/docs/CS/Framework/Job/DolphinScheduler/Scheduler_Deploy.md)
- [Job](/docs/CS/Framework/Job/Job.md)
- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)

## References

- [Apache DolphinScheduler](https://dolphinscheduler.apache.org/)
- [apache/dolphinscheduler @ 3.4.3](https://github.com/apache/dolphinscheduler/releases/tag/3.4.3)
