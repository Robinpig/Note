## Introduction

DolphinScheduler 的任务类型以**插件化 SPI** 形式承载在 `dolphinscheduler-task-plugin` 下。3.4.3 共 **37 种任务类型**：33 种「物理任务」插件（运行在 Worker）+ 4 种「逻辑任务」（CONDITIONS / DEPENDENT / SUB_WORKFLOW / SWITCH，运行在 Master，见 [Master](/docs/CS/Framework/Job/DolphinScheduler/Master.md)）。本文拆解 SPI 机制与完整类型清单。

> 版本差异：3.4.0 已**移除 PYTORCH** 任务类型，当前目录中已无对应模块。

## SPI Mechanism

核心抽象（`dolphinscheduler-task-plugin/dolphinscheduler-task-api/.../plugin/task/api/`）：

- `TaskChannel`（`TaskChannel.java:22`）：单个任务类型的通道，负责 `parseParameters`、`createTaskPlugin`、构建参数。
- `TaskChannelFactory extends PrioritySPI`（`TaskChannelFactory.java:23`）：工厂，`getName()` 返回任务类型字符串（如 `"SHELL"`），`create()` 返回 `TaskChannel`。
- `TaskPluginManager`（`TaskPluginManager.java:32`）：静态 `loadTaskPlugin()` 用 `PrioritySPIFactory<TaskChannelFactory>` 扫描所有 `TaskChannelFactory` 实现，以 `getName()` 为 key 注册进 `taskChannelMap`；`getTaskChannel(type)` / `parseTaskParameters(type, params)` 供运行时按类型取通道。

### 插件注册方式

每个插件用 Google `@AutoService(TaskChannelFactory.class)` 自动生成 `META-INF/services` 声明，例如 `ShellTaskChannelFactory`（`dolphinscheduler-task-shell/.../ShellTaskChannelFactory.java:25`）：

```java
@AutoService(TaskChannelFactory.class)
public class ShellTaskChannelFactory implements TaskChannelFactory {
    public static final String NAME = "SHELL";
    @Override public String getName() { return NAME; }
    @Override public TaskChannel create() { return new ShellTaskChannel(); }
}
```

加载在 `TaskPluginManager` 静态块与 Master/Worker 启动时各触发一次（`TaskPluginManager.java:38-40`），`loadedFlag` 保证只加载一次。

## Physical Task Types (33)

由 `dolphinscheduler-task-plugin/*` 各模块 `ChannelFactory.getName()` 提取（`dolphinscheduler-task-plugin/**/*ChannelFactory.java`）：

| 类型字符串 | 模块 | 类型字符串 | 模块 |
|-----------|------|-----------|------|
| SHELL | task-shell | HTTP | task-http |
| SQL | task-sql | JAVA | task-java |
| SPARK | task-spark | REMOTESHELL | task-remoteshell |
| FLINK | task-flink | HIVECLI | task-hivecli |
| FLINK_STREAM | task-flink-stream | PYTHON | task-python |
| MR | task-mr | DATAX | task-datax |
| SQOOP | task-sqoop | CHUNJUN | task-chunjun |
| SEATUNNEL | task-seatunnel | DINKY | task-dinky |
| ZEPPELIN | task-zeppelin | JUPYTER | task-jupyter |
| K8S | task-k8s | KUBEFLOW | task-kubeflow |
| LINKIS | task-linkis | MLFLOW | task-mlflow |
| SAGEMAKER | task-sagemaker | DVC | task-dvc |
| EMR | task-emr | EMR_SERVERLESS | task-emr-serverless |
| ALIYUN_SERVERLESS_SPARK | task-aliyunserverlessspark | DATASYNC | task-datasync |
| DATA_FACTORY | task-datafactory | OPENMLDB | task-openmldb |
| PROCEDURE | task-procedure | DMS | task-dms |
| GRPC | task-grpc | | |

> 这些类型在 Master 侧由 `WorkerGroupDispatcher` 派发到 Worker，由 `PhysicalTaskExecutor` 加载对应 `AbstractTask` 插件执行。

## Logic Task Types (4)

位于 `dolphinscheduler-task-api/.../plugin/task/api/task/`（`*LogicTaskChannelFactory.java`）：

| 类型字符串 | 说明 |
|-----------|------|
| CONDITIONS | 条件分支（根据上游变量/状态选择下游） |
| DEPENDENT | 跨工作流/任务依赖判断 |
| SUB_WORKFLOW | 子工作流（嵌套调用另一工作流） |
| SWITCH | Switch 分支 |

这四类**不派发到 Worker**，由 Master 本地 `LogicTaskExecutor` + `ILogicTask` 插件执行（见 [Master](/docs/CS/Framework/Job/DolphinScheduler/Master.md) 的 LogicTask 章节）。

## Task Plugin Anatomy

以 SHELL 为例，一个任务插件模块通常包含：

- `XxxParameters`：参数 POJO（JSON 反序列化，校验 `checkParameters()`）。
- `XxxTask extends AbstractTask`（`plugin/task/api/AbstractTask`）：`init()` / `handle()` / `cancel()`，是任务实际执行体。
- `XxxTaskChannel` / `XxxTaskChannelFactory`：SPI 注册。

`TaskExecutionContext`（`plugin/task/api/TaskExecutionContext`）承载下发到 Worker 的全部上下文：任务类型、参数、租户、环境变量、`dispatchFailTimes` 等。`TaskCallBack` 把运行结果/状态回传 Master。

## Links
- [DolphinScheduler](/docs/CS/Framework/Job/DolphinScheduler)
- [DolphinScheduler Master Engine](/docs/CS/Framework/Job/DolphinScheduler/Master.md)
- [DolphinScheduler Worker and RPC](/docs/CS/Framework/Job/DolphinScheduler/Worker_RPC.md)

## References

- [apache/dolphinscheduler @ 3.4.3](https://github.com/apache/dolphinscheduler/releases/tag/3.4.3)
- 源码模块：`dolphinscheduler-task-plugin/`
