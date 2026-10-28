## Introduction

Worker 是 DolphinScheduler 的**执行手脚**，负责真正跑任务插件。3.4.3 的 Worker 与 Master 之间的通信已统一到 `dolphinscheduler-extract` 这套**注解式 Netty RPC 框架**：不再有老式的 `Command` 命令码 + `XXXTaskProcessor.handle` 反射分发，取而代之的是 `@RpcService` / `@RpcMethod` 接口 + JSON 序列化。本文拆解 Worker 启动、物理任务执行、RPC 协议与任务运行时回传。

## WorkerServer

`WorkerServer`（`dolphinscheduler-worker/.../WorkerServer.java:51`）是 `@SpringBootApplication`，`@PostConstruct run()`（`WorkerServer.java:77`）启动顺序：

1. `workerRpcServer.start()` —— 启动 Netty RPC Server（监听 `worker.listen-port`，默认 **1234**，`WorkerConfig.java:43`）。
2. `TaskPluginManager.loadTaskPlugin()` + `DataSourcePluginManager.loadDataSourcePlugin()` —— 加载 SPI 插件。
3. `workerRegistryClient.start()` —— 注册 `/nodes/worker/<ip:port>`，心跳间隔 `max-heartbeatInterval` 默认 **10s**（`WorkerConfig.java:44`）。
4. `physicalTaskEngineDelegator.start()` —— 拉起物理任务执行引擎。

### WorkerConfig

`config/WorkerConfig.java:41`（prefix=`worker`）：

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `listen-port` | 1234 | RPC 监听端口 |
| `max-heartbeat-interval` | 10s | 心跳间隔 |
| `host-weight` | 100 | 静态权重 |
| `group` | `default` | worker group 名（`WorkerConfig.java:78`） |
| `tenantConfig.autoCreateTenantEnabled` | `true` | 自动创建租户 Linux 用户 |
| `tenantConfig.defaultTenantEnabled` | `false` | 是否启用默认租户 |
| `physicalTaskConfig.taskExecutorThreadSize` | `CPUs*2+1` | 物理任务执行线程池（`PhysicalTaskConfig.java:25`） |

## PhysicalTaskExecutor

`executor/PhysicalTaskExecutor.java:44` 继承公共模块 `AbstractTaskExecutor`。执行步骤：

1. `initializeTaskPlugin()`（`PhysicalTaskExecutor.java:64`）：`physicalTaskPluginFactory.createPhysicalTask(this)` 创建具体 `AbstractTask`，调 `physicalTask.init()`，初始化 `varPool`。
2. `doTriggerTaskPlugin()`：启动物理任务（fork 子进程 / 提交 Yarn / K8s / 远程 Shell，视任务类型而定）。
3. 运行时状态经 `TaskExecutorStateMappings.mapState` 把 `AbstractTask` 的状态映射到 `TaskExecutionStatus`，并通过本地 `TaskExecutorEventBus` 上报；Master 侧由对应的 `TaskLifecycleEventHandler` 消费（见 [Master](/docs/CS/Framework/Job/DolphinScheduler/Master.md)）。

### Task Executor Container

公共模块 `dolphinscheduler-task-executor` 提供两种容器：`ExclusiveThreadTaskExecutorContainer`（每任务独占线程）与 `SharedThreadTaskExecutorContainer`（共享线程池），由 `TaskExecutorContainerConfig` 装配；`AbstractTaskExecutor` 的 `TaskExecutorState`（`INITIALIZED/RUNNING/PAUSED/KILLED/FAILED/SUCCEEDED`）是运行期轻量状态。

## RPC Framework (dolphinscheduler-extract)

这是 3.4.x 通信层的**核心重构**。关键类（`dolphinscheduler-extract/dolphinscheduler-extract-base/.../extract/base/`）：

- **服务端**：`NettyRemotingServer`（`server/NettyRemotingServer.java`）+ `RpcServer`；通过 `SpringServerMethodInvokerDiscovery` 扫描 `@RpcService`，把方法登记到 `ServerMethodInvokerRegistry`，由 `JdkDynamicServerHandler` 分发。
- **客户端**：`NettyRemotingClient`（`client/NettyRemotingClient.java`）+ `Clients`（`client/Clients.java`）；`JdkDynamicRpcClientProxyFactory` 用 JDK 动态代理生成 RPC 客户端，`ClientInvocationHandler` 把调用封装成 `StandardRpcRequest`。
- **注解**：`@RpcService`（`base/RpcService.java`）、`@RpcMethod`（`base/RpcMethod.java`，含 `RpcMethodRetryStrategy`）。
- **传输协议**：`protocal/Transporter`（含 `TransporterHeader` + body），`TransporterEncoder` / `TransporterDecoder` 编解码；**序列化用 `JsonSerializer`（JSON，非 protobuf）**。`TransporterHeader`（`protocal/TransporterHeader.java:28`）字段：`methodIdentifier`（被调方法标识）+ `opaque`（请求序号，自增 `AtomicLong`）。
- **连接配置**：`NettyServerConfig` / `NettyClientConfig`。

### Master ↔ Worker Interfaces

- `dolphinscheduler-extract-worker`：`IPhysicalTaskExecutorOperator`（dispatch / kill / pause / query 等）、`IStreamingTaskInstanceOperator`、`ITaskExecutorQueryClient`。
- `dolphinscheduler-extract-master`：`IWorkflowControlClient`（含 `workflowScheduleTrigger`，Quartz 定时触发即走此 RPC）、`ITaskInstanceController`（TaskGroup 槽位回执等）。

### Old Command Protocol is Gone

老版本节点间通信用的 `org.apache.dolphinscheduler.common.command.Command` 命令码枚举 + `TASK_EXECUTE_REQUEST` 之类常量在 3.4.3 内核中**已不再用于 Master/Worker 通信**；节点内 Master 仍用 `t_ds_command` 表做「触发 → 消费」的持久化队列，但那是对 DB 的读写，不是网络协议。

## Tenant and Execution User

`config/TenantConfig.java` + `utils/TenantUtils`：Worker 按租户把任务映射到 Linux 用户。`autoCreateTenantEnabled=true` 时若系统无对应用户则自动创建；任务以该租户用户身份 fork 子进程执行，实现多租户隔离。

## Python Gateway

PYTHON 任务通过 Py4J Gateway 执行。配置项（`application.yaml`）：`python-gateway.gateway-server-port=25333`（gateway 服务端）、`python-gateway.python-port=25334`（Python 解释器侧，`dolphinscheduler-api/.../api/python/PythonGateway.java` 提供 gateway server）。Master/Worker 通过 gateway 与 Python 进程互调，Python 任务本身仍作为物理任务下发到 Worker。

## Log Collection

Worker 侧任务日志由 `WorkerLogServiceImpl` 落本地，`dolphinscheduler-extract-common` 的 log transporter 把日志按 `taskInstanceId` 上传到存储（HDFS/S3/MinIO 等，由 `StorageOperator` 抽象，见 [Scheduler and Deploy](/docs/CS/Framework/Job/DolphinScheduler/Scheduler_Deploy.md)）。

## Links
- [DolphinScheduler](/docs/CS/Framework/Job/DolphinScheduler)
- [DolphinScheduler Master Engine](/docs/CS/Framework/Job/DolphinScheduler/Master.md)
- [DolphinScheduler Task Plugin](/docs/CS/Framework/Job/DolphinScheduler/Task_Plugin.md)
- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)

## References

- [apache/dolphinscheduler @ 3.4.3](https://github.com/apache/dolphinscheduler/releases/tag/3.4.3)
- 源码模块：`dolphinscheduler-worker/`、`dolphinscheduler-extract/`、`dolphinscheduler-task-executor/`
