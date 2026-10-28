## Introduction

本篇展开 [SkyWalking](/docs/CS/Distributed/Tracing/SkyWalking.md) 的**采集与传输层**：各类探针如何采集数据、数据经哪些通道送达 OAP（gRPC 11800 / HTTP 12800 / Kafka），以及贯穿其中的 **sw8 跨进程传播协议**——它是 SkyWalking 还原服务拓扑的基石。

## Probes

SkyWalking 的探针按来源分三类：

| 类型 | 实现 | 说明 |
| --- | --- | --- |
| **语言原生 agent** | Java（字节码增强）、C#、Node.js、Go、PHP、Python | 自动埋点，无需改业务代码 |
| **手动 SDK** | C++、Rust、Nginx LUA | 需显式调用 API |
| **Service Mesh 探针** | Istio / Envoy access log（gRPC） | 从数据面 / 控制面接收遥测，无需注入 sidecar 埋点 |
| **第三方格式接入** | Zipkin v1/v2、OpenTelemetry、Prometheus、Zabbix、Telegraf | 由对应 receiver 直接接纳 |

此外，SkyWalking 基于 **eBPF** 栈提供 Kubernetes 监控，能在内核态采集网络与性能数据；Java 探针通过 [Java Agent](/docs/CS/Java/JDK/Agent.md) 做字节码增强，是生产环境最常用的接入方式。

## Reporting Channels

探针把 Segment / 指标 / 日志发往 OAP 的主要通道：

| 通道 | 端口 | 说明 |
| --- | --- | --- |
| **gRPC** | `11800` | 默认通道，Java / .NET / Node.js / Istio 等原生与 mesh 探针都走它 |
| **HTTP / REST** | `12800` | JSON 格式上报，也承载 UI 的 GraphQL 查询、PromQL、LogQL |
| **Kafka** | broker 地址 | 经 topic（如 `skywalking-segments` / `skywalking-meters` / `skywalking-logs`）异步削峰，OAP 消费 |

通道地址在 agent 配置里设置，例如 Java agent 的 `SW_AGENT_COLLECTOR_BACKEND_SERVICES=oap:11800`。OAP 侧对应 `core/default/gRPC*` 与 `core/default/rest*` 配置项。

## sw8 Propagation Header

SkyWalking 更像 APM 而非通用追踪系统，因此它的传播头比 B3 / W3C 复杂——目的是让 OAP 直接获得还原拓扑所需的信息，省去额外 join。跨进程上下文传播协议 **v3 即 sw8**：

- **标准头** `sw8`：由 `-` 分隔的 **8 个字段**，值总长度默认 < 2k。所有字符串类型字段均为 **BASE64 编码**。

```
sw8: 1-TRACEID-SEGMENTID-3-PARENT_SERVICE-PARENT_INSTANCE-PARENT_ENDPOINT-IPPORT
```

| # | 字段 | 类型 | 说明 |
| --- | --- | --- | --- |
| 1 | **Sample** | 0 / 1 | 0 = 上下文存在但大概率被忽略；1 = 需采样并上报后端 |
| 2 | **Trace ID** | BASE64 | 全局唯一 |
| 3 | **Parent trace segment ID** | BASE64 | 全局唯一 |
| 4 | **Parent span ID** | 整数（从 0 起） | 指向父 Segment 中的父 Span |
| 5 | **Parent service** | BASE64 | ≤ 50 UTF-8 字符 |
| 6 | **Parent service instance** | BASE64 | ≤ 50 UTF-8 字符 |
| 7 | **Parent endpoint** | BASE64 | 父 Segment 首个 entry span 的操作名，< 150 UTF-8 |
| 8 | **Target address** | BASE64 | 客户端访问目标服务的网络地址（未必是 IP+port） |

- **扩展头** `sw8-x`：字段可扩展，当前含 **Tracing Mode**（空 / 0 / 1；1 = 该上下文所有 Span 跳过分析 `skipAnalysis=true`）与**客户端发送时间戳**（用于 MQ 等异步场景，消费端据此算出 `transmission.latency`）。

注意 sw8 携带了「父服务 / 父实例 / 父端点 / 目标地址」，这是 SkyWalking 能**仅凭传播头就直接构建服务依赖拓扑**的原因，也是它与只传 trace/span ID 的 B3 / W3C 的本质差异（详见 [Zipkin Transport](/docs/CS/Distributed/Tracing/Zipkin/Transport.md) 的 B3 对照）。

## Relationship to OpenTelemetry

[OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md) 默认用 **W3C Trace Context**（`traceparent` / `tracestate`）传播；SkyWalking 用 sw8。混部时，OTel Collector 通过 `receiver-otel` 把 OTLP 接入 SkyWalking，OTel 侧无需改用 sw8——上下文转换在 OAP 内完成。新项目通常以 OTel 为起点、SkyWalking 作后端。

## Links

- [SkyWalking](/docs/CS/Distributed/Tracing/SkyWalking.md) — 枢纽页
- [SkyWalking Data Model](/docs/CS/Distributed/Tracing/SkyWalking/Data_Model.md) — ContextCarrier / ContextSnapshot
- [SkyWalking Internals](/docs/CS/Distributed/Tracing/SkyWalking/Internals.md) — sw8 的 inject / extract 实现与两级采样
- [SkyWalking OAP Backend and Storage](/docs/CS/Distributed/Tracing/SkyWalking/Collector_and_Storage.md) — receiver 模块与 Kafka 通道
- [Java Agent](/docs/CS/Java/JDK/Agent.md) — Java 探针字节码增强
- [Zipkin Transport](/docs/CS/Distributed/Tracing/Zipkin/Transport.md) — B3 传播对照

## References

1. [Cross Process Propagation Headers (sw8)](https://skywalking.apache.org/docs/main/next/en/api/x-process-propagation-headers-v3/) — sw8 协议规范
2. [Backend setup](https://skywalking.apache.org/docs/main/next/en/setup/backend/backend-setup/) — 端口与上报通道
3. [SkyAPM-dotnet config](https://skyapm.github.io/SkyAPM-dotnet/docs/guides/skyapm_config) — Agent 上报地址与 Kafka topic
