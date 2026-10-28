## Introduction

SchedulerX 的"接入"不是一个动作，而是一组按业务载体分叉的选择：**Java 应用**引 SDK 或 Starter；**Go 应用**引 Go SDK；**不想改代码**的用脚本任务、HTTP 任务或 K8s 任务；**存量开源客户端**靠兼容插件迁移。本页给出四条路径的最小接入骨架，以及一份 `SchedulerxWorker` 配置参数表。父级见 [ScheduleX](/docs/CS/Framework/Job/ScheduleX.md)。

## Java SDK

Maven 依赖（版本号取最新，当前基线 **1.14.2**）：

```xml
<dependency>
    <groupId>com.aliyun.schedulerx</groupId>
    <artifactId>schedulerx2-worker</artifactId>
    <version>${schedulerx2.version}</version>
    <exclusions>
        <!-- 官方要求排除，避免与业务日志实现冲突 -->
        <exclusion>
            <groupId>org.apache.logging.log4j</groupId>
            <artifactId>log4j-api</artifactId>
        </exclusion>
        <exclusion>
            <groupId>org.apache.logging.log4j</groupId>
            <artifactId>log4j-core</artifactId>
        </exclusion>
        <exclusion>
            <groupId>log4j</groupId>
            <artifactId>log4j</artifactId>
        </exclusion>
    </exclusions>
</dependency>
```

非 Spring 应用在 `main` 里初始化：

```java
public void initSchedulerxWorker() throws Exception {
    SchedulerxWorker schedulerxWorker = new SchedulerxWorker();
    schedulerxWorker.setEndpoint("xxxx");      // 地域对应的地址服务器地址
    schedulerxWorker.setNamespace("xxxx");     // 命名空间 ID
    schedulerxWorker.setGroupId("xxxx");       // 应用 ID（多个分组用逗号分隔）
    schedulerxWorker.setAppKey("xxxx");        // 1.2.1 及以上必须设置
    schedulerxWorker.init();
}
```

Spring / Spring Boot 应用改用 `com.aliyun.schedulerx:schedulerx2-spring-boot-starter`（与 worker 同版本），在配置文件里填 endpoint / namespace / groupId / appKey 即可。

接入成功的判定只有一条硬标准：**应用管理页面里实例总数不为 0**。为 0 说明接入失败，去查 worker 上的 `${user.home}/logs/schedulerx/worker.log`。

## SchedulerxWorker Parameters

| 参数 | 说明 | 默认值 |
| :--- | :--- | :--- |
| `setEndpoint(String)` | 每个 Region 的地址服务器地址 | 无 |
| `setNamespace(String)` | 命名空间 ID | 无 |
| `setGroupId(String)` | 应用 ID（多分组逗号分隔） | 无 |
| `setAppKey(String)` | 控制台创建应用时返回的应用 Key | 无 |
| `setAliyunAccessKey/SecretKey` | 阿里云账号 AK；用了 appKey 后可不用 | 无 |
| `setEnableBatchWork(boolean)` | 是否启用网格计算。**不用的话不要配；用了必须开**，否则每台机器第一次触发至少延迟 20 秒 | `true` |
| `setHost(String)` | 多网卡 / VPN 环境下手工指定本机 IP | 无 |
| `setPort(int)` | 客户端监听端口 | 无（自动） |
| `setClassLoader(ClassLoader)` | 非 Spring 应用或用了特殊框架时指定 | 无 |
| `setBlockAppStart(boolean)` | 初始化失败是否阻断应用进程启动 | 无 |
| `setSlsCollectorEnable(boolean)` | 是否启用 SLS 日志采集 | `true` |
| `setShareContainerPool(boolean)` | 客户端所有任务是否共享线程池（大量任务高并发调度场景推荐开） | `false` |
| `setSharePoolSize(int)` | 共享线程池大小 | `64` |
| `setLabel(String)` | 客户端标签，用于灰度 / 压测时指定机器执行 | 无 |
| `setMapMasterStatusCheckInterval(int)` | Map 模型检查子任务是否全部完成的间隔（ms），秒级任务可调小 | `3000` |
| `setEnableSecondDelayCycleIntervalMs(boolean)` | `second_delay` 单位由秒改为毫秒 | `false` |
| `setEnableUnits/setEnableSites` | 单元化 / 机房白名单（逗号分隔，无空格） | 无 |
| `setDisableUnits/setDisableSites` | 黑名单；**白名单存在时黑名单被忽略** | 无 |

## JobProcessor 注入

Processor 必须是 Spring bean：

```java
@Component
public class MyHelloJob extends JavaProcessor {
    @Override
    public ProcessResult process(JobContext context) throws Exception {
        System.out.println("hello schedulerx2.0");
        return new ProcessResult(true);
    }
}
```

报 `jobProcessor is null` / `ClassNotFoundException` 时的排查顺序（官方口径）：

1. 确认启动方式是 Spring / Spring Boot；
2. Processor 是否加了 `@Component`；
3. 排除 `spring-boot-devtools`（它会导致 ClassLoader 不一致）；
4. Processor 或 `process` 方法上有 AOP 注解时，需要较新版本客户端——低版本不支持 AOP；
5. 多加一层代理导致 bean 类型不匹配：在 `DefaultListableBeanFactory.beanDefinitionNames` 上看 bean 被哪个切面代理了；
6. 仍不行则调试 `ThreadContainer.start`，若 `Class.forName` 报类不存在但类确实在，就是 ClassLoader 问题，用 `SchedulerxWorker.setClassLoader()` 解决。

className 配置必须是**类的全路径**；报 `ClassNotFoundException` 时先确认是不是发错包，或者这个应用连了别人的机器（登录 worker 机器反编译确认）。

## Go SDK

`alibaba/schedulerx-worker-go` 是 Go 版 Worker SDK（由高德贡献），**没有 release tag**，按官方文档用 `go get github.com/alibaba/schedulerx-worker-go@{最新的tag}` 拉取（仓库最新提交在 `develop` 分支）。

```go
cfg := &schedulerx.Config{
    Endpoint:  "acm.aliyun.com",
    Namespace: "433d8b23-06e9-408c-aaaa-90d4d1b9a4af",
    GroupId:   "gojob-test",
    AppKey:    "xxxxxxx",
}
client, _ := schedulerx.GetClient(cfg)
client.RegisterTask("HelloWorld", &HelloWorld{})
// 等待 SIGINT/SIGTERM 后再退出
```

四种 Processor 对应四种执行模式：`Processor`（单机）、`BroadcastProcessor`（广播，`PreProcess` / `Process` / `PostProcess` 三段）、`MapJobProcessor`（`Process` + `Map` + `Kill`）、`MapReduceJobProcessor`（再加 `Reduce` 与 `RunReduceIfFail`）。控制台创建任务时**任务类型选 `golang`，任务名必须与 `RegisterTask` 注册的名字一致**。

Go 侧可配项与 Java 不完全对齐（如 `WithSharePoolSize` 默认 200、`WithWorkerParallelTaskMaxSize` 默认 5、`WithGrpcPort`、`WithLabel`、`WithIface`）。近年新增：多分组（2026-03）、OpenTelemetry 链路追踪（2026-07）、秒级任务 goroutine 泄漏修复（2026-05）、`JobContext` 暴露 `triggerType`（2026-08）。

## Script, HTTP, and K8s Tasks

不想改业务代码时有三条路：

- **脚本任务**：控制台直接写 shell / python / go 脚本，Worker 机器需具备对应运行环境。2025-04 起支持 PHP 脚本与脚本模板、脚本版本历史对比；1.14.x 起支持**子进程强制终止**；1.13.5 起支持工作流上下游数据传递；1.14.2 起 `clientInfo.log` 打印完整脚本输出（便于 SLS 采集）。
- **HTTP 任务（Serverless）**：GET / POST 两种，**不依赖 Client**，控制台配完即生效。返回值非 JSON 会报 `the response is not json object`；与自定义结果不符报 `The returned value is different from the expected value`；响应码不符报 `A service call error occurred`。
- **K8s 任务**：面向容器化执行，支持脚本版本管理；1.13.4 起 CPU 采集支持 cgroup v2。

## Compatibility Plugins

从开源客户端迁移时不用重写业务代码，靠插件：

| 来源 | artifact | 最新（2026-10 核实） |
| :--- | :--- | :--- |
| XXL-JOB | `schedulerx2-plugin-xxljob` | 2.3.5 |
| XXL-JOB（新版） | `schedulerx3-plugin-xxljob` | 2.2.2 |
| ElasticJob | `schedulerx2-plugin-elasticjob` | 3.0.2.1 |
| Spring `@Scheduled` | `@SchedulerX` 注解（1.12.1+） | — |
| 链路追踪 | `schedulerx-plugin-trace-opentelemetry` | 1.0.8 |

两条使用注意：`schedulerx2-plugin-elasticjob` 的版本号（3.0.2.1）是**对齐 ElasticJob 自身版本**的，不要误以为是 SchedulerX SDK 版本；`@SchedulerX` 注解是"接管部分 Spring 定时任务"而不是全量接管——1.12.5 起还兼容了其他组件也实现 `TaskScheduler` 的场景。

## Lifecycle and Logs

- **优雅下线**：1.10.14 起支持，应用关闭时等待运行中的任务执行完再退出，保证发布/重启零业务影响；`second_delay` 任务的优雅下线到 1.13.5 才支持。
- **日志目录**：默认 `${user.home}/logs/schedulerx`，核心日志是 `worker.log`；1.12.3 起可用 `-Dschedulerx.log.path=` 指定根路径（最终落在 `{schedulerx.log.path}/logs/schedulerx`），并支持覆盖默认 logback 配置、把 SDK 日志导出到 SLS Logstore。
- **日志打不出来的根因**：几乎是日志组件冲突。Log4j2 与 Logback 混用时若存在 `log4j-to-slf4j`，日志会失踪——要么排除 `log4j-to-slf4j`，要么只保留一个日志组件；纯 log4j1 场景下则排查 `log4j-over-slf4j`。
- **应用隔离**与**从环境变量读取任务参数**都是 1.11.1 起的能力。

## Links

- [ScheduleX](/docs/CS/Framework/Job/ScheduleX.md)
- [Architecture](/docs/CS/Framework/Job/ScheduleX/Architecture.md)
- [Job Types](/docs/CS/Framework/Job/ScheduleX/Job_Types.md)
- [Operations](/docs/CS/Framework/Job/ScheduleX/Operations.md)

## References

- [客户端快速接入 SchedulerX](https://help.aliyun.com/zh/schedulerx/schedulerx-serverless/getting-started/connect-an-agent-to-schedulerx/)
- [连接 Spring 应用到 SchedulerX](https://www.alibabacloud.com/help/en/doc-detail/2848961.html)
- [SchedulerxWorker 配置参数说明](https://help.aliyun.com/zh/mse/user-guide/schedulerxworker-parameters)
- [Java SDK release notes](https://www.alibabacloud.com/help/en/schedulerx/product-overview/java-sdk-release-notes)
- [schedulerx-worker-go（Go SDK）](https://github.com/alibaba/schedulerx-worker-go)
