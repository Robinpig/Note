## Introduction

[Jaeger](https://www.jaegertracing.io/) 是受 [Dapper](/docs/CS/Distributed/Tracing/Tracing.md) 与 OpenZipkin 启发、由 Uber 开源后捐赠给 CNCF（2019 年毕业）的**分布式链路追踪后端**。它接收、存储、检索并可视化由 [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md) 等探针上报的 trace，用于微服务环境下的分布式上下文传播、延迟定位与故障根因分析。

要区分两个层面：OTel 负责**埋点、传播上下文、生成 span 并通过 OTLP 上报**（厂商中立），Jaeger 负责**作为后端存储与展示这些 span**。自 Jaeger v1.35 起官方推荐用 OTel SDK 取代已废弃的 Jaeger client；自 v1.41/v2 起 collector 基于 OpenTelemetry Collector 构建。

## Architecture

Jaeger 的经典组件划分：

| 组件 | 职责 |
| --- | --- |
| **jaeger-client / OTel SDK** | 进程内埋点，构造 span、注入/提取 trace context（W3C TraceContext 或 B3） |
| **jaeger-agent**（sidecar / daemonset） | 接收 span，批量转发给 collector；新版可被 OTel Collector agent 取代 |
| **jaeger-collector** | 校验、tail 采样、处理 span 并写入存储，无状态可水平扩展 |
| **storage** | 可插拔后端：Cassandra、Elasticsearch/OpenSearch、[Kafka](/docs/CS/MQ/Kafka/Kafka.md)（缓冲）、Badger（单机）、v2 OTLP 存储 |
| **query** | 从存储检索 trace，提供 API 供 UI 调用 |
| **jaeger-ui** | 展示 trace 时间轴、依赖拓扑、trace 对比 |

典型数据流：

```
Instrumented Service
   │  OTLP / Jaeger thrift
   ▼
agent ──► collector ──► Kafka(可选削峰) ──► ingester ──► Elasticsearch/Cassandra
                                                    ▲
                                query + UI ─────────┘
```

## Data Model

Jaeger 模型与 OpenTelemetry trace 模型基本一一对应：

- **Trace**：一次完整请求的 span 集合，由 `trace_id` 标识（推荐 128-bit，兼容 64-bit）。
- **Span**：一个工作单元，含 `span_id`、`parent_span_id`、operation name、起止时间、tags、logs、process。
- **SpanContext**：跨进程传播的载体，携带 trace/span id、sampling flags、baggage。
- **References**：除 `ChildOf` 外支持 `FollowsFrom`（异步、非因果关键路径），与 OTel 的 Link 概念呼应。
- **Process**：产生 span 的服务元数据（service name + host、版本等 tags）。

上下文传播默认采用 [W3C Trace Context](https://www.w3.org/TR/trace-context/)（`traceparent` / `tracestate`），早期默认 B3。

## Sampling

采样在两处发生：

1. **Head-based（客户端）**：入口决定整条 trace 是否采样，决策随上下文传播以保证完整性。策略有 `const`（全采/全不采）、`probabilistic`（概率，默认）、`ratelimiting`（每秒 N 条，漏桶）、`remote`（从 collector 拉取按 service/endpoint 的集中式策略，可动态调整）。
2. **Tail-based（collector 端）**：先缓冲完整 trace，再依据延迟、错误码、命中服务等规则决定保留，可在低采样率下保住异常链路，代价是需要缓冲资源；v2 借助 OTel Collector 的 Tail Sampling Processor。详见 [Otel 采样章节](/docs/CS/Distributed/Tracing/Otel.md?id=sampling)。

## Storage

存储是 Jaeger 运维成本的核心：

| 后端 | 定位 |
| --- | --- |
| **Cassandra** | 早期默认，写入扩展性强，运维较重 |
| **Elasticsearch / OpenSearch** | 最常用，检索能力强、生态成熟 |
| **Badger** | 本地文件存储，all-in-one 与小规模场景 |
| **Kafka + ingester** | collector 与存储之间的削峰缓冲 |
| **v2 OTLP storage** | Jaeger v2 直接以 OTLP 落盘，统一数据通路 |

span 是典型的**时序追加写**，查询按 trace_id 点查、按 service/operation/tag/时间范围过滤，这解释了为何选用宽表/搜索引擎型存储而非关系库。

## Deployment

- **all-in-one**：单二进制 + 内存/Badger，适合本地开发演示。
- **生产**：agent 以 DaemonSet/sidecar 部署，collector/query 无状态多副本 + 独立 ES/Cassandra，常用 Helm Chart。
- **Jaeger v2**：基于 OpenTelemetry Collector 重写，单一二进制以 pipeline 配置接收（OTLP）→处理→导出，弱化独立 agent。

快速本地启动（all-in-one，OTLP 4317/4318，UI 16686）：

```bash
docker run --rm -d -p 16686:16686 -p 4317:4317 -p 4318:4318 \
  jaegertracing/all-in-one:latest
# UI: http://localhost:16686
```

应用侧只需把 OTel exporter 指向 `http://localhost:4318`（OTLP/HTTP）或 `4317`（OTLP/gRPC）即可，无需引入 Jaeger 专有客户端。

## Jaeger vs Zipkin

| 维度 | Jaeger | [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md) |
| --- | --- | --- |
| 起源 | Uber（Dapper 论文） | Twitter |
| 客户端 | 已弃用，推荐 OTel SDK | 多语言 reporter，也可接 OTel |
| 模型 | trace/span + FollowsFrom | span 树 + annotation |
| 传播 | W3C TraceContext / B3 | B3（多/单 header） |
| 存储 | ES/Cassandra/Kafka/Badger | MySQL/ES/Cassandra/内存 |
| 采样 | probabilistic + remote + tail | 多在客户端，生态较小 |

两者模型高度相似，OTel Collector 都能桥接；选型更多取决于存储与运维栈（ES 生态偏 Jaeger，轻量简单偏 Zipkin）。

## Use Cases

- 微服务延迟瓶颈定位（trace 时间轴上定位慢 span）。
- 错误/重试链路串联，配合应用日志与 metrics exemplar，见[三大信号关联](/docs/CS/Distributed/Tracing/Otel.md?id=correlating-the-three-signals)。
- 基于 span 父子关系自动聚合服务依赖拓扑。
- 正常/异常请求 trace diff，辅助分布式事务与一致性问题分析。

## Links

- [Tracing](/docs/CS/Distributed/Tracing/Tracing.md)
- [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md)
- [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md)
- [SkyWalking](/docs/CS/Distributed/Tracing/SkyWalking.md)
- [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md)
- [Grafana](/docs/CS/Distributed/Tracing/Grafana.md)
- [Micrometer](/docs/CS/log/Micrometer.md)

## References

1. [Jaeger Documentation](https://www.jaegertracing.io/docs/)
2. [Jaeger GitHub](https://github.com/jaegertracing/jaeger)
3. [Jaeger v2 Documentation](https://www.jaegertracing.io/docs/2.0/)
4. [Dapper, a Large-Scale Distributed Systems Tracing Infrastructure](https://research.google/pubs/pub36356/)
5. [W3C Trace Context](https://www.w3.org/TR/trace-context/)
