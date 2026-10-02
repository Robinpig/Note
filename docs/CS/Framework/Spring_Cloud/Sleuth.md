## Introduction

Spring Cloud Sleuth 是 Spring Cloud 的**分布式链路追踪（distributed tracing）**自动装配组件。它为一次跨越多个微服务的请求自动打标、传播 trace 上下文，并把追踪数据对接给 Zipkin 等后端。
Sleuth 提供了一种几乎无感知的集成方案：只需引入依赖、做少量配置即可开启，整个过程不需要业务代码改动。

> 版本注意：Sleuth 从 **Spring Cloud 2022.0（对应 Spring Boot 3.0）起被移除**，其能力由 **Micrometer Tracing**（配合 Micrometer 门面 + OpenTelemetry / Brave 桥接）取代。Sleuth 的概念与自动埋点思想在 Micrometer Tracing 中延续，存量 Boot 2.x 系统仍广泛使用 Sleuth。

## Core Concepts

- **Trace**：一次完整分布式请求链路，由唯一的 **Trace ID** 标识，贯穿所有参与服务。
- **Span**：链路中的一个工作单元（一次服务调用、一次 DB 查询、一次消息消费），有自己的 **Span ID**、开始/结束时间与标签；span 之间通过 parent span id 构成树形因果。
- **Annotation / Tag**：`cs`（client send）、`sr`（server received）、`ss`（server send）、`cr`（client received）这类时序事件用来计算网络与处理耗时；tag 是附加的键值信息（http.method、http.status_code、error 等）。

Sleuth 自动把 traceId / spanId 放进 SLF4J 的 **MDC**，于是日志里可以直接打印 `[app-name,traceId,spanId,exportable]` 前缀，在日志聚合系统里按 traceId 捞出一次请求经过的所有服务日志。

## Context Propagation

追踪成立的关键是 trace 上下文能跨进程传播。Sleuth 在常见的入口/出口埋点（servlet filter、`RestTemplate`、Feign client、消息通道、调度任务、WebClient）自动注入/提取请求头。

以 OpenFeign 为例：Sleuth 用一个包装过的 client（Brave 时代是 `TracingFeignClient` 一类的织入），在构造发往下游的 HTTP 请求时，把一系列追踪标记塞进 Header。默认采用 **B3 传播格式**（Zipkin 体系）：

- `X-B3-TraceId`
- `X-B3-SpanId`
- `X-B3-ParentSpanId`
- `X-B3-Sampled`

下游服务的入口 filter 解析这些头，于是 Customer 服务产生的 Trace ID、Span ID 得以传递到 Template 服务，多个服务的 span 才能在后端拼成同一条完整调用链。换成 OpenTelemetry 时对应的是 W3C `traceparent` 头。

## Sampling

全量采集每条链路代价很高，因此有**采样（sampling）**：

- 概率采样：`spring.sleuth.sampler.probability`（0.0–1.0）决定保留多少比例的 trace，错误请求通常倾向优先保留。
- 未被采样的 span 仍有 ID（保证日志可关联），但不会被导出到后端。
- 采样决策要在链路入口尽量一致地传播（B3 sampled / OTel sampled flag），避免一条链路只采到半截。

## Zipkin Integration

Sleuth 只负责“埋点 + 传播 + 建模”，存储与可视化交给追踪后端。引入 `spring-cloud-sleuth-zipkin` 后会自动把 span 以 Zipkin 兼容格式上报（默认 HTTP 发到 `http://localhost:9411`）：

```yaml
spring:
  sleuth:
    sampler:
      probability: 0.1
  zipkin:
    base-url: http://zipkin:9411
```

Zipkin 聚合 span，还原服务依赖图与每个 span 的耗时，用于定位跨服务的延迟瓶颈。其他可选后端还有 [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md)、SkyWalking；统一概念与 Dapper 起源见 [分布式追踪](/docs/CS/Distributed/Tracing/Tracing.md)。

## Sleuth vs Micrometer Tracing

| 维度 | Spring Cloud Sleuth（Boot 2.x） | Micrometer Tracing（Boot 3.x） |
| ---- | ---- | ---- |
| 定位 | Spring Cloud 子项目，自动装配 | Micrometer 体系下的 tracing 门面 |
| 底层实现 | 主要是 Brave | Brave 或 OpenTelemetry 桥接，可切换 |
| 观测统一 | tracing 与 metrics 分开 | tracing/metrics/logging 统一在 Micrometer + Observation API |
| 上下文传播 | B3 为主 | 支持 W3C TraceContext、B3 等多种 propagator |

迁移到 Boot 3 时，通常把 `spring-cloud-starter-sleuth` 换成 `micrometer-tracing-bridge-brave`（或 `-otel`）+ `zipkin-reporter-brave`，埋点 API 改为 `ObservationRegistry` / `@Observed`。

## Links

- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md?id=tracing)
- [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md)
- [分布式追踪 Tracing](/docs/CS/Distributed/Tracing/Tracing.md)
- [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md)
- [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md)
- [Micrometer](/docs/CS/log/Micrometer.md)
- [Spring Cloud OpenFeign](/docs/CS/Framework/Spring_Cloud/Feign.md)

## References

1. [Spring Cloud Sleuth Reference](https://docs.spring.io/spring-cloud-sleuth/docs/current/reference/html/)
2. [Micrometer Tracing Reference](https://docs.micrometer.io/tracing/reference/)
3. [Zipkin - B3 Propagation](https://github.com/openzipkin/b3-propagation)
