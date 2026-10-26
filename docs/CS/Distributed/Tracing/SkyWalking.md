## Introduction

[Apache SkyWalking](https://skywalking.apache.org/) 是一款**开源可观测性平台（APM）**，面向云原生、容器化的分布式系统，统一采集、分析、聚合并可视化来自服务与云原生基础设施的遥测数据。与 [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md) / [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md) 这类「纯追踪后端」不同，SkyWalking 从设计上就是 APM——除了分布式追踪，还内置指标（Metrics）、日志（Logging）、拓扑（Topology）、告警（Alarm）与 profiling，并围绕「服务 / 实例 / 端点」的对象层级做聚合分析。

其架构遵循官方文档「逻辑四部分」划分：探针（Probes）、平台后端（OAP Server）、存储（Storage）、UI。与通用追踪系统最关键的差异在于两点——**对象层级模型**（Service → Service Instance → Endpoint）与 **sw8 跨进程传播协议**：探针在请求头里携带的不仅是 trace/span ID，还有父服务、父实例、父端点与目标地址，使 OAP 后端无需额外 join 即可直接还原服务拓扑。

> 版本基线：**v11.0.0（2026-08-28，最新）/ v10.4.0（2026-04-01）**；**10.2.0 起永久移除 H2 存储、默认存储改为 BanyanDB**；v11 起引入下一代 **Horizon UI**。OAP 运行需 Java 11/17/21/25（默认 Docker 镜像基于 Java 25）。

各分册展开：

- [SkyWalking Data Model](/docs/CS/Distributed/Tracing/SkyWalking/Data_Model.md) — Trace / Segment / Span（Entry/Exit/Local）、ContextCarrier / ContextSnapshot
- [SkyWalking Transport](/docs/CS/Distributed/Tracing/SkyWalking/Transport.md) — 探针类型、gRPC 11800 / HTTP 12800 / Kafka 上报、sw8 传播头
- [SkyWalking OAP Backend and Storage](/docs/CS/Distributed/Tracing/SkyWalking/Collector_and_Storage.md) — Receiver、OAL / MAL / LAL、存储选型、告警
- [SkyWalking Query and UI](/docs/CS/Distributed/Tracing/SkyWalking/Query_and_UI.md) — GraphQL 查询、拓扑 / 追踪 / 指标视图、booster-ui 与 Horizon UI
- [SkyWalking Internals](/docs/CS/Distributed/Tracing/SkyWalking/Internals.md) — 实现机理：agent 的 span 栈、两级采样、Segment→Source 派生链、拓扑推导、OAL 编译、BanyanDB 物理模型

## Architecture

SkyWalking 逻辑上分为四部分（探针 / OAP / 存储 / UI），组件交互如下：

```
Probes (agent / SDK / mesh / 3rd-party)
   │  gRPC :11800 / HTTP :12800 / Kafka
   ▼
┌──────────────────────────────────────────────┐
│              OAP Server (Platform backend)    │
│  Receiver → Analysis Core (L1/L2 agg, OAL)    │
│           → Query Core (GraphQL) → Alarm      │
└───────────────────────┬──────────────────────┘
                        │  pluggable
                        ▼
                   Storage (BanyanDB / ES / MySQL ...)
                        ▲
                        │  GraphQL :12800
                   UI (:8080)
```

- **Probes（探针）**：采集 trace / metric / log / event，格式覆盖 SkyWalking 原生、Zipkin、OTel、Prometheus、Zabbix、Telegraf。
- **OAP Server（Platform backend）**：聚合、分析与流式处理，同时扮演 Aggregator 与 Receiver 角色；模块体系与集群机制见 [SkyWalking OAP Backend and Storage](/docs/CS/Distributed/Tracing/SkyWalking/Collector_and_Storage.md)。
- **Storage（存储）**：开放可插拔接口，默认 `banyandb`。
- **UI**：Web 界面，端口 8080，通过 GraphQL 向 OAP 的 12800 发起查询。

对象层级（Layer / Service / Service Instance / Endpoint / Process）与 Service Hierarchy 的细节见 [SkyWalking Data Model](/docs/CS/Distributed/Tracing/SkyWalking/Data_Model.md)。

## Object Model

SkyWalking 的对象层级自上而下为 **Layer → Service → Service Instance → Endpoint**（外加 **Process**）：

- **Layer**：对计算机科学中某类抽象框架的归类，如 `OS_LINUX`、Kubernetes（`k8s`）、Service Mesh（`mesh` / `mesh-dp`）。一个 Service 通常只属于一个 Layer，但也可同时属于多个（如同时被 k8s 与 Istio mesh 探测到的服务）。
- **Service**：提供相同行为的一组工作负载（workloads）；服务名可由探针 / SDK 定义，也可沿用 Istio 等平台已有的名字。
- **Service Instance**：Service 组里单个的工作负载，如 Kubernetes 中的一个 `pod`；使用探针时，一个实例即一个真实 OS 进程。
- **Endpoint**：服务内一次入站请求的路径，如 HTTP URI 或 gRPC `service + method` 签名。
- **Process**：操作系统进程；某些场景下 Service Instance 并不等于一个进程（如一个 pod 内含多个进程）。

SkyWalking 还能建立 **Service Hierarchy Relationship**，把不同 Layer 中「逻辑上同一服务」连起来（如 k8s 层与 mesh 层里同一个服务）。字段级定义与 Segment / Span 细节见 [SkyWalking Data Model](/docs/CS/Distributed/Tracing/SkyWalking/Data_Model.md)。

## Observability Coverage

SkyWalking 不止于 tracing，它把五类遥测统一进同一套对象模型：

- **Tracing**：原生格式 + Zipkin v1/v2。
- **Metrics**：原生 meter 格式、OTEL metrics、Telegraf 格式；service mesh 接收器从 Istio / Envoy 数据面或控制面构建可观测性；原生 agent 还可运行在 metrics-only 模式以提升性能。
- **Logging**：从磁盘或网络收集日志；原生 agent 可自动把追踪上下文与日志绑定。
- **Profiling**：随语言 agent 与独立 eBPF agent 提供，从代码行级别定位性能问题。
- **Event**：记录版本升级、配置变更等关键时刻，与指标 / 追踪 / 日志联动辅助排障。

## Mechanics

上面讲的是 SkyWalking「长什么样」，这一节讲它「怎么跑起来」。三处最关键的实现选择：

**Agent 侧以 Segment 而非 Span 为单位。** 探针在一个线程内维护 ActiveSpanStack，EntrySpan / ExitSpan 在栈顶同类时会**复用**而非新建（否则 filter 链会造出伪端点）；只有栈顶 span 能被 stop，未弹栈的 span 不会被上报。Segment 完成后整体打包成 protobuf 一次性发出，代价是单段 span 数有上限（默认 300，超限降级为 NoopSpan 而非抛异常）。

**采样有两级，且互不知情。** agent 侧是「每 3 秒最多 N 个 Segment」的滑动窗口限流（CAS 抢占保证硬上界，非百分比）；OAP 侧再按 `traceId` 哈希取模做确定性采样——同一 trace 的所有 Segment 哈希相同，因此**整条 trace 同生共死**，不会断成半截。错误 Segment 可配置为强制保留。

**拓扑是分析器的副产品，不是配置项。** OAP 把收到的 Segment 拆成 Source，按 scope 路由给 OAL 编译生成的 dispatcher；调用关系被 **CLIENT / SERVER 双端各检测一次**，任一端 agent 存活即可维持拓扑边。边的聚合只存「出现过哪些组件」的集合、不存数值，所以拓扑图能零配置自动出现。

完整链路（含 TimeBucket 编码、OAL 编译成 Java 字节码、BanyanDB 的 Stream / Measure / Property 三模型与 Series 分片）见 [SkyWalking Internals](/docs/CS/Distributed/Tracing/SkyWalking/Internals.md)。

## Relationship to OpenTelemetry

SkyWalking 与 [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md) 是「后端 vs 生成框架」的关系：OTel SDK 负责埋点与上下文传播（默认 W3C Trace Context），SkyWalking OAP 通过 `receiver-otel` 模块直接接收 OTLP；Zipkin / Jaeger 格式则由各自 receiver 接纳。新项目通常以 OTel 为起点、SkyWalking 作后端，而不再引入 SkyWalking 专有客户端。跨进程传播上，SkyWalking 用自己的 **sw8** 协议而非 B3 / W3C，与 [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md) 的 B3 形成对照（见 [SkyWalking Transport](/docs/CS/Distributed/Tracing/SkyWalking/Transport.md)）。

## Quickstart

一条命令拉起 OAP + UI（默认存储 BanyanDB 需先就绪；UI 端口 8080）：

```bash
# 先起 BanyanDB（官方推荐存储）
docker run -d -p 17912:17912 -p 17913:17913 --name banyandb apache/skywalking-banyandb:${BYDB_VERSION} standalone
# 再起 SkyWalking（OAP 监听 gRPC 11800 / HTTP 12800，UI 8080）
docker run -d -p 11800:11800 -p 12800:12800 -p 8080:8080 apache/skywalking-oap-server
# UI: http://localhost:8080
```

更完整的部署（存储选型、Kafka 通道、集群、动态配置）见 [SkyWalking OAP Backend and Storage](/docs/CS/Distributed/Tracing/SkyWalking/Collector_and_Storage.md)。探针接入（Java agent、其它语言 SDK、Service Mesh、第三方格式）见 [SkyWalking Transport](/docs/CS/Distributed/Tracing/SkyWalking/Transport.md)。

## Links

- [Tracing](/docs/CS/Distributed/Tracing/Tracing.md) — 可观测性三支柱、trace/span 数据模型
- [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md) — CNCF 追踪后端，多进程架构对照
- [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md) — 轻量追踪系统，B3 传播对照
- [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md) — vendor-agnostic 遥测框架，可桥接 SkyWalking
- [Java Agent](/docs/CS/Java/JDK/Agent.md) — SkyWalking Java 探针的字节码增强实现
- [Elasticsearch](/docs/CS/Framework/ES/ES.md) — SkyWalking 的可选存储后端

## References

1. [Apache SkyWalking](https://skywalking.apache.org/) — 官方网站
2. [SkyWalking Overview](https://skywalking.apache.org/docs/main/next/en/concepts-and-designs/overview/) — 概念与对象模型
3. [Backend setup](https://skywalking.apache.org/docs/main/next/en/setup/backend/backend-setup/) — 端口、启动与模块化
4. [Backend storage](https://skywalking.apache.org/docs/main/next/en/setup/backend/backend-storage/) — 存储后端选型
5. [Cross Process Propagation Headers (sw8)](https://skywalking.apache.org/docs/main/next/en/api/x-process-propagation-headers-v3/) — sw8 协议规范
