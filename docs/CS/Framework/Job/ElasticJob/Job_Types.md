# Job Types

## Introduction

ElasticJob 的作业类型在 `3.0.5` 已拆到 `ecosystem/executor/{simple,dataflow,script,http}` 四个独立模块，统一实现 `api` 模块的 `ElasticJob` 接口。本文给出各作业类型的接口契约、两种引导类、以及 `JobConfiguration` 配置全字段，全部以 `3.0.5` 源码为准。

## ElasticJob Interface

所有作业类型的根接口（`api/ElasticJob.java`）只声明一个语义契约，具体触发由框架注入 `ShardingContext`：

```java
public interface ElasticJob {
    // 由具体作业类型在子接口中定义 execute(ShardingContext)
}
```

## Built-in Job Types

| 类型 | 接口 / 实现 | 契约（已核实 `3.0.5`） | 适用 |
| :--- | :--- | :--- | :--- |
| Simple | `org.apache.shardingsphere.elasticjob.simple.job.SimpleJob` | `void execute(ShardingContext shardingContext)` | 一次性或无需分批拉取的业务逻辑 |
| Dataflow | `org.apache.shardingsphere.elasticjob.dataflow.job.DataflowJob<T>` | `List<T> fetchData(ShardingContext)` + `void processData(ShardingContext, List<T>)` | 流式处理：先抓数据再处理，可配置 `streamingProcess` 持续轮询 |
| Script | **无 Java 接口** | 由 `ScriptJobExecutor` 执行；配置 `jobType=SCRIPT` + 命令行（`scriptCommandLine`） | 调用 Shell / Python 等外部脚本 |
| Http | `HttpJobExecutor`（`ecosystem/executor/http`） | 3.x 新增；配置目标 URL 与请求方式，由执行器发起 HTTP 调用 | 触发远程 HTTP 端点 |

> [!WARNING]
>
> **Script 作业没有 Java 接口**——`ScriptJob.java` 在整个仓库里不存在（已对 `3.0.5` 全量文件树核实）。它不是"实现某个接口"，而是把 `jobType` 设为 `SCRIPT` 并提供脚本命令，框架经 `ScriptJobExecutor` 直接起子进程执行。老资料里"实现 ScriptJob 接口"的说法是错的。

Dataflow 的 `fetchData` 返回为空时，该分片项本轮不进入 `processData`；`streamingProcess=true` 时执行器会在数据处理完后不退出、持续以固定间隔轮询 `fetchData`，直到作业被停止——这是它与 Simple 最本质的区别。

## Bootstrap

作业通过 `bootstrap` 模块的引导类接入，二者决定"作业如何被触发"：

- **`ScheduleJobBootstrap`**：把作业注册进 `JobScheduler`，经内部 **Quartz** 按 `cron` 周期调度。这是最常见的用法。
- **`OneOffJobBootstrap`**：只注册作业、不挂 Quartz 周期触发，由调用方显式 `execute()` 一次——适合"被运维 API / 外部事件触发一次"的场景（3.0.5 修复了它在 Spring Boot Starter 下不可用的问题）。

二者都接收 `CoordinatorRegistryCenter` + `JobConfiguration` + 具体作业实例，构造后由 `JobScheduler` 完成与 ZK 的协调。

## JobConfiguration

作业的全部配置落在 `JobConfiguration`（`api/JobConfiguration.java`），并以 JSON 持久化到 ZK 的 `config` 节点（见 [Registry Center](/docs/CS/Framework/Job/ElasticJob/RegistryCenter.md)）。`3.0.5` 确认的核心字段与默认值：

| 字段 | 默认 | 含义 |
| :--- | :--- | :--- |
| `jobName` | — | 作业名（ZK 路径标识，必填） |
| `cron` | — | Quartz cron 表达式（调度型作业必填） |
| `timeZone` | — | cron 时区 |
| `shardingTotalCount` | — | 总分片数 |
| `shardingItemParameters` | `""` | 分片项参数，形如 `0=北京,1=上海` |
| `jobParameter` | `""` | 作业级共享参数 |
| `monitorExecution` | `true` | 是否写 `running` 节点（影响 misfire 探测与监控） |
| `failover` | `false` | 是否开启失效转移 |
| `misfire` | `true` | 是否开启错过执行重跑 |
| `maxTimeDiffSeconds` | `-1` | 作业服务器与注册中心的最大时间差容忍（-1 不检查） |
| `reconcileIntervalMinutes` | `10` | 自诊断修复周期（分钟） |
| `jobShardingStrategyType` | 平均分片 | 分片策略类型字符串（见 [Sharding](/docs/CS/Framework/Job/ElasticJob/Sharding.md)） |
| `jobExecutorThreadPoolSizeProviderType` | — | 执行线程池大小提供者类型 |
| `jobErrorHandlerType` | — | 作业错误处理 handler 类型 |
| `jobListenerTypes` | 空 | 作业监听器类型列表 |
| `staticSharding` | `false` | 静态分片（首次分片后固定绑定） |
| `disabled` | `false` | 作业级禁用 |
| `overwrite` | `false` | 本地配置是否覆盖 ZK 已有配置 |
| `label` | — | 作业标签（用于运维分组） |

`overwrite=true` 时，应用启动会用本地配置覆盖 ZK 上已存的 `config`；生产环境通常谨慎开启，避免本地改动误覆盖运行中的配置。

## Spring Boot Integration

`3.0.5` 的 Spring Boot starter artifact 为 **`elasticjob-spring-boot-starter`**（Cloud 移除后去掉了 `lite` 前缀）。通过注解 `@ElasticJobConfiguration`（`api/annotation`）声明作业类与配置，starter 自动装配 `CoordinatorRegistryCenter` 与 `ScheduleJobBootstrap`，无需手动写引导代码。

## Links

- [ElasticJob](/docs/CS/Framework/Job/ElasticJob.md) — 枢纽：执行链路中作业如何被调用
- [Sharding](/docs/CS/Framework/Job/ElasticJob/Sharding.md) — `ShardingContext` 与分片策略如何作用于作业
- [Failover](/docs/CS/Framework/Job/ElasticJob/Failover.md) — `failover` / `misfire` / `monitorExecution` 开关的运行时含义
- [Registry Center](/docs/CS/Framework/Job/ElasticJob/RegistryCenter.md) — `config` 节点如何持久化 `JobConfiguration`

## References

- [ElasticJob 源码 `SimpleJob.java` (3.0.5)](https://github.com/apache/shardingsphere-elasticjob/blob/3.0.5/ecosystem/executor/simple/src/main/java/org/apache/shardingsphere/elasticjob/simple/job/SimpleJob.java)
- [ElasticJob 源码 `DataflowJob.java` (3.0.5)](https://github.com/apache/shardingsphere-elasticjob/blob/3.0.5/ecosystem/executor/dataflow/src/main/java/org/apache/shardingsphere/elasticjob/dataflow/job/DataflowJob.java)
- [ElasticJob 源码 `JobConfiguration.java` (3.0.5)](https://github.com/apache/shardingsphere-elasticjob/blob/3.0.5/api/src/main/java/org/apache/shardingsphere/elasticjob/api/JobConfiguration.java)
