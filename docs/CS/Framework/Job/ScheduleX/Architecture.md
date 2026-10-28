## Introduction

SchedulerX 的架构是典型的 **Server/Worker 中心化拓扑**，但用户只见其半：Server 侧是阿里云托管的多租户集群（不对用户开放、不可自建、无源码可读），用户持有的是嵌入业务进程的 Worker Agent。本页把可见与不可见的两半拼起来，并说明它们之间靠什么协议、按什么语义通信。父级见 [ScheduleX](/docs/CS/Framework/Job/ScheduleX.md)。

读这一页要注意区分两类来源：**架构原理**（来自阿里云官方技术文章与专有云白皮书，稳定），**产品现状**（来自现行帮助中心文档，随版本变化）。凡涉及版本、能力有无的判断，以后者为准。

## Concept Model

官方概念自顶向下共五级，理解它们的边界比记住名字重要：

| 概念 | 定义 | 关键说明 |
| :--- | :--- | :--- |
| Namespace（命名空间） | 租户内的环境隔离单位 | 用于区分测试/预发/生产；OpenAPI 与控制台操作均需指定 |
| AppGroup（应用分组） | 应用隔离单位，创建后生成唯一 `groupId` 与 `appKey` | 一个应用可按业务拆多个分组，`groupId` 支持逗号分隔多分组接入 |
| Job | 最小调度单元 | 任务类型（语言）× 执行模式共同决定它怎么跑 |
| Job Instance | Job 的一次执行 | 每次触发生成一个实例；失败重试、停止、重跑的操作对象都是实例 |
| Task | 分布式模型下由 `Map` 产生的**子任务** | 只在并行计算 / MapReduce / 分片模型下存在 |
| Workflow | 编排 Job 的 DAG | 工作流中的 Job 没有独立调度时间，跟随工作流的时间触发 |

两个时间语义必须分清：

- **schedule time**：`jobInstance` 的预定执行时刻，业务侧通过 `context.getScheduleTime()` 获取。
- **data time**：数据时间。任务本身带数据状态，创建时可填数据偏移；例如每天 00:30 运行但处理前一天的数据，向前偏移一小时→运行时刻不变，而 `context.getDataTime()` 返回前一天 23:30。

「数据时间」的直接衍生能力是**重刷数据（backfill）**：当业务变更或历史数据出错时，可重刷某些任务/工作流过去一段时间的数据，**只支持天级别**，每次生成的实例携带不同的数据时间。

## Server Side

Server 侧的全部设计目标可以概括成一句官方表述：**通过分布式架构与 Akka 的异步特性，支撑海量任务与秒级别调度**。三个子系统值得单独说：

### Scheduling and Dispatch

调度器负责按 cron / fixed_rate / second_delay 计算下次触发时刻并在到期时触发；分发引擎决定这一次落到哪台（或哪几台）机器：

- **指定机器**：任务可指定在特定机器上执行；机器下线则无法调度（对应报错 `No worker available for`）。
- **标签路由**：客户端启动时 `setLabel()` 打标签，任务管理可指定标签执行，用于灰度、压测等场景（专业版能力）。
- **单元化围栏**：`setEnableUnits()` / `setEnableSites()` 设白名单，`setDisableUnits()` / `setDisableSites()` 设黑名单，白名单优先。

### State Machine on Actors

海量实例并发上报状态时，"简单地扔进线程池"会产生乱序：`instance=100` 的 `running` 与 `failed` 若被不同线程处理，可能出现"先变 failed 再变 running"的状态机倒退。SchedulerX 的解法是把状态收敛到 actor 上：

- 所有实例状态消息先发给 `JobInstanceRoutingActor`；
- 路由 actor 按 `instanceId` 把消息转发给固定的 `JobInstanceActor`；
- **Akka 保证单个 actor 按消息接收顺序处理**，因此同一实例的消息天然有序，且不同实例之间互不阻塞。

同一"路由 actor + 业务 actor"的模型被用于 job / workflow / instance 等各类消息，模块间通信经 Akka eventbus 做 Pub-Sub（而非共享线程池）——这样高频任务不会把线程池占满导致其他任务饿死。

### High Availability and Security

官方给出的高可靠手段有四项，都是"服务端承诺"而非用户可配置项：

- **主备机制**（Server 无状态、可水平扩展）+ **数据三备份**；
- **消息 At-least-once delivery**——注意这是**至少一次**，与子任务"不保证绝对执行一次"是同一件事的两面，业务需自行幂等；
- **failover**；
- **定期轮检**（补偿因进程重启、网络抖动丢失的触发）。

安全防护同样是平台能力：支持 HTTPS 与 VPC 访问；支持**用户隔离、命名空间隔离、应用隔离**三层多租户隔离；支持 RAM 用户与临时 AccessKey；专业版另有**链路加密**（加密 Server-Client 通信中的敏感数据）。

## Worker Side

Worker 是用户进程内的 Agent（Java 侧即 `schedulerx2-worker`），内部结构分三层，自顶向下：

| 层 | 职责 | 默认实现 / 取值 |
| :--- | :--- | :--- |
| TaskMaster | 类似 YARN 的 AppMaster：管理整个 `jobInstance` 的生命周期、Container 资源管理、failover | `StandaloneTaskMaster`（单机）、`BroadcastTaskMaster`（广播）、`MapTaskMaster`（并行计算/内存网格）、`MapReduceTaskMaster`（网格计算） |
| Container | 执行业务逻辑的容器框架 | 支持线程 / 进程 / docker / actor |
| Processor | 业务代码本身 | `JavaProcessor`、`MapJobProcessor`、`MapReduceJobProcessor` 等 |

一次执行的链路是：Server 触发调度 → 分发引擎提交实例 → Worker 的 `JobInstanceActor` 收到 `ServerSubmitJobInstanceRequest` → 交给对应 TaskMaster → 由 Container 拉起 Processor → 状态与日志回流。

Worker 侧另有两条常配的运行参数直接影响行为：

- `setShareContainerPool(boolean)`：**默认 false**。开启后客户端所有任务共享一个线程池（推荐大量任务高并发调度场景），默认池大小 64（`setSharePoolSize`）。不开时每个任务各自起线程。
- `setMapMasterStatusCheckInterval(int)`：Map 模型检查子任务是否全部完成的间隔，**默认 3000 ms**。做秒级任务时可调小以提高调度频率。
- `setEnableSecondDelayCycleIntervalMs(boolean)`：**默认 false**。置 true 后控制台上 `second_delay` 的单位由秒变为**毫秒**级延迟。

## Communication

Server↔Worker 与 Worker↔Worker 都基于 **Akka**：Java SDK 通过 **akka-remoting** 做 peer-to-peer 通信——每个节点暴露一个远程地址，其他节点知道地址即可通信，远程 actor 与本地 actor 用法一致，只是地址不同。

依赖形态上有一点容易误判：`schedulerx2-worker` 是 **shade 打包**的胖 jar，1.8.0 构件的依赖清单里可以看到 `com.typesafe.akka:*`、`io.netty:netty`、`com.google.protobuf:protobuf-java`、`com.zaxxer:HikariCP`、`com.h2database:h2`、`com.google.guava:guava` 等被 relocate 到 `com.alibaba.schedulerx.shade.*`；而 1.14.2 的 `pom` 只剩 spring-core/context/beans/aop（5.3.31）、logback 1.2.13、log4j 2.17.2、joda-time、lombok 等少量直接依赖。**不要因为 `dependency:tree` 里看不到 Akka 就断言它不用 Akka**——Akka 在 shaded 产物内部，且 1.12.2 的 release note 明确写着"修复部分 Akka 接口的安全漏洞"。

两点需要说明清楚，避免被二手资料误导：

1. **Akka 不等于"Worker 也用 Scala 写业务"**。Akka 只出现在 Agent 与通信层，业务 Processor 是纯 Java/Go。
2. **Go SDK 不是 Akka 实现，但要解析 Akka 帧格式**。`alibaba/schedulerx-worker-go` 的 `internal/remoting` 以「4 字节长度头 + payload」的二进制帧收包，再按 Akka 消息格式解码出真实消息与 sender path——因为服务端协议帧格式没变。其配置项里出现 `WithGrpcPort`（actor system 的 gRPC 端口），说明 Go 侧 actor 通信走 gRPC 而非 akka-remoting。（该结论来自对 Go SDK 仓库的结构化分析，未逐行阅读源码，如有变化以仓库为准。）

心跳是 Worker 存活判定的基础：心跳上报异常会触发容错重试，也会直接体现为控制台上的"No worker available"、"all workers are busy"。1.13.1 修复过"Spring 父子容器场景下心跳注册过早上报"的问题，1.11.5 修复过"多应用分组配置读取错误影响心跳上报"——**心跳异常多数不是网络问题，而是接入配置问题**。

## Isolation and Network

- **命名空间**做环境隔离，**应用分组**做业务隔离；二者加上用户隔离构成多租户三层。
- 地域与接入地址（endpoint）一一对应，客户端 `setEndpoint()` 填所属地域的地址服务器地址；公网应用只能选 SchedulerX 版（XXL-JOB 版不支持公网）。
- 客户端监听端口可自定义（`setPort`），多网卡或 VPN 环境下自动获取的 IP 可能不对，用 `setHost()` 手工指定。
- 非 Spring 应用或使用特殊框架时可能需要 `setClassLoader()`；初始化失败是否阻断应用启动由 `setBlockAppStart()` 决定。

## Links

- [ScheduleX](/docs/CS/Framework/Job/ScheduleX.md)
- [Job Types](/docs/CS/Framework/Job/ScheduleX/Job_Types.md)
- [Client Access](/docs/CS/Framework/Job/ScheduleX/Client_Access.md)
- [Operations](/docs/CS/Framework/Job/ScheduleX/Operations.md)
- [Job](/docs/CS/Framework/Job/Job.md)

## References

- [Akka in SchedulerX 2.0（阿里云开发者社区）](https://developer.aliyun.com/article/709946)
- [产品优势（高可靠 / 高性能 / 安全防护）](https://help.aliyun.com/document_detail/303859.htm)
- [阿里云专有云 EDAS SchedulerX 技术白皮书（概念定义 / 产品优势 / 应用场景）](http://apsara-doc.oss-cn-hangzhou.aliyuncs.com/apsara-pdf/enterprise/v_3_10_0_20200506/edas/zh/schedulerx-apsarastack-technical-whitepaper.pdf)
- [SchedulerxWorker 配置参数说明](https://help.aliyun.com/zh/mse/user-guide/schedulerxworker-parameters)
- [schedulerx-worker-go（Go SDK）](https://github.com/alibaba/schedulerx-worker-go)
