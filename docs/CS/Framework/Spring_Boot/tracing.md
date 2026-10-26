## Introduction

从 **Spring Boot 3.0（Spring Cloud 2022.0）** 起，Spring 生态的分布式链路追踪统一到 **Micrometer Tracing** + **Observation API**，底层可桥接 **Brave**（对接 [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md)）或 **OpenTelemetry**（对接 OTLP 后端）。[Spring Cloud Sleuth](/docs/CS/Framework/Spring_Cloud/Sleuth.md)（Boot 2.x 的追踪组件）在这一档被移除，能力由 Micrometer Tracing 承接。

本篇只讲**现行做法**（Boot 3.x / 4.x）。trace / span / baggage 这套数据模型在两代之间几乎没变，概念对照见 [Tracing](/docs/CS/Distributed/Tracing/Tracing.md)；遗留 Sleuth 的配置与 API 见其 [专属页](/docs/CS/Framework/Spring_Cloud/Sleuth.md)。

## Core Concepts

- **Trace**：一次完整分布式请求链路，由唯一 **Trace ID** 贯穿所有参与服务。
- **Span**：链路中的一个工作单元（一次调用、一次 DB 查询、一次消息消费），有自己的 **Span ID**、起止时间与标签；span 之间靠 parent span id 构成树形因果。
- **Tag / Event**：tag 是键值属性（`http.method`、`http.status_code`、`error`）；event 是带时间戳的点事件。老一辈 Zipkin 资料里的 [`cs`/`sr`/`ss`/`cr` annotation](/docs/CS/Distributed/Tracing/Zipkin/Data_Model.md) 在现代实现里已归入 server/client span 的边界划分。
- **Baggage**：随调用链一路透传的业务键值（`tenant-id`、`user-tier`）。与 tag 的区别：**baggage 跨进程传播，tag 只留在当前 span**。

Boot 默认把 `traceId` / `spanId` 写入 SLF4J 的 **MDC**，日志里直接打印关联 ID（见「日志关联」）。

## Context Propagation

追踪成立的关键是上下文能跨进程传播。常见入口/出口（servlet filter、`WebClient`、`RestClient`、`RestTemplate`、Feign、消息通道、调度任务）由框架埋点自动注入与提取请求头。

主流传播格式：

| 格式 | Header | 出自 |
| :-- | :-- | :-- |
| **W3C TraceContext**（现代默认） | `traceparent`、`tracestate` | W3C 标准，OTel 与多数新系统使用 |
| **B3** | `X-B3-TraceId`、`X-B3-SpanId`、`X-B3-ParentSpanId`、`X-B3-Sampled` | Zipkin 体系，Sleuth 时代的默认 |

> [!WARNING]
> **必须**使用框架自动装配的 Builder 构造 HTTP 客户端——`RestTemplateBuilder`、`RestClient.Builder`、`WebClient.Builder`。自己 `new RestTemplate()` 出来的客户端**不带传播逻辑**，trace 到这一跳就断，且毫无报错。下游会出现"孤零零的新 trace"，极易误判为"上游没接进来"。

## Tracer Implementations and Starters

Boot 为两类 tracer 提供依赖管理与自动装配，选型基本等于选"后端是 Zipkin 还是通用 OTLP"。

### Brave + Zipkin

最省心的一条路：

```xml
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-zipkin</artifactId>
</dependency>
```

```yaml
management:
  tracing:
    sampling:
      probability: 1.0        # 默认只采 10%，调试时调到 1.0
    export:
      zipkin:
        endpoint: http://zipkin:9411/api/v2/spans
```

### OpenTelemetry + OTLP

后端支持 OTLP（Jaeger、Tempo、SkyWalking、云厂商托管服务）时选这条：

```xml
<dependency>
    <groupId>org.springframework.boot</groupId>
    <artifactId>spring-boot-starter-opentelemetry</artifactId>
</dependency>
```

```yaml
management:
  opentelemetry:
    tracing:
      export:
        otlp:
          endpoint: http://collector:4318/v1/traces
```

需要深度定制 exporter 时注册 `OtlpHttpSpanExporterBuilderCustomizer` 或 `OtlpGrpcSpanExporterBuilderCustomizer`，其优先级高于自动配置。

> [!WARNING]
> **OpenTelemetry 已废弃自己的 Zipkin exporter**。Boot 侧的对应自动配置（`ZipkinWithOpenTelemetryTracingAutoConfiguration`）自 **4.0.4 起 `@Deprecated(forRemoval=true)`、计划 4.2 移除**；届时若既要 OTel SDK 又要落 Zipkin，推荐让 Zipkin 用 `zipkin-otel` 模块直接吃 OTLP，而不是再用 zipkin exporter 转换。具体依赖为 `spring-boot-micrometer-tracing-opentelemetry` + `micrometer-tracing-bridge-otel` + `spring-boot-zipkin` + `opentelemetry-exporter-zipkin`。

## Sampling

全量采集代价很高。默认**只采样 10%** 的请求（`management.tracing.sampling.probability` 默认 `0.1`），调试期常调到 `1.0`。

未被采样的 span **仍有 ID**（保证日志可关联），只是不导出到后端。日志里能看到 traceId、后端却查不到这条链，属正常现象而非故障。

使用 OpenTelemetry 时还能通过 `management.opentelemetry.tracing.sampler` 选采样器：

| 值 | 行为 |
| :-- | :-- |
| `always-on` | 全采 |
| `always-off` | 全丢 |
| `trace-id-ratio` | 按 `probability` 比例采 |
| `parent-based-always-on` / `-off` | 父 span 说了算，无父时按名字走 always-on/off |
| **`parent-based-trace-id-ratio`**（默认） | 父 span 说了算，无父时按 `probability` 采 |

> [!TIP]
> 默认的 parent-based 语义意味着**采样决策在链路入口做出并传播下去**，避免"一条链只采到半截"。各服务若各自配不同采样率又不传播决策，后端看到的是一条条断链。

## Log Correlation

使用 Micrometer Tracing 后 Boot **默认**在日志里输出关联 ID，格式是 `[traceId-spanId]`。想还原成 Sleuth 时代的 `[应用名,traceId,spanId]` 格式：

```properties
logging.pattern.correlation=[${spring.application.name:},%X{traceId:-},%X{spanId:-}]
logging.include-application-name=false
```

注意 `logging.pattern.correlation` 末尾带一个空格，用于和后面的 logger 名分隔；第二行是为了避免应用名重复出现两次。

> [!NOTE]
> `management.tracing.baggage.enabled` 设为 `false` 会阻止 Brave 把 trace/span ID 写入 MDC，从而直接禁用日志关联——依赖 Correlation ID 时不要关。
> 想换 MDC 键名可用 `management.tracing.mdc.trace-id-key` / `management.tracing.mdc.span-id-key`，默认 Correlation ID 格式会自动跟随新键名。

## Observation API

Boot 自动注册 `TracingAwareMeterObservationHandler` 到 `ObservationRegistry`，于是**每一个完成的 observation 都会产生对应 span**——这正是 Micrometer Tracing 的设计目标：metrics 与 tracing 同源，一次埋点两套数据。

自定义 span 通常意味着自定义 observation：

```java
@Component
class OrderObservation {

	private final ObservationRegistry registry;

	void place(Order order) {
		Observation observation = Observation.createNotStarted("order.place", registry);
		observation.lowCardinalityKeyValue("channel", order.channel());
		observation.observe(() -> {
			// 业务逻辑……
		});
	}
}
```

只想生成 span 而**不想**顺带产生 metric 时，降到 Micrometer 的 `Tracer` API 直接用。

## Baggage

```java
try (BaggageInScope scope = tracer.createBaggageInScope("tenant-id", "acme")) {
	// 该范围内的 span 以及下游调用都能读到这个值
}
```

两个配置项决定 baggage 的去向：

- `management.tracing.baggage.remote-fields`：写进请求头向**下游传播**（如 `tenant-id` → 同名 HTTP header）。
- `management.tracing.baggage.correlation.fields`：写进 **MDC**，从而在日志里可见。

> [!NOTE]
> **W3C 传播自动带 baggage，B3 不会**。还在用 B3 的系统若发现 baggage 没传下去，先确认当前用的哪种传播格式，或直接把字段列进 `remote-fields` 手动传播。

## Span Limits

OTel 下可用 `management.opentelemetry.tracing.limits.*` 限制 span 规模（属性数、事件数、关联数、字符串长度），防止异常数据撑爆后端：

```properties
management.opentelemetry.tracing.limits.max-attributes=64
management.opentelemetry.tracing.limits.max-attribute-value-length=256
```

## Context Propagation Across Threads

关联 ID 默认靠 `ThreadLocal` 传播，跨线程或响应式管线下需显式开启：

- 响应式：`spring.reactor.context-propagation=auto` 让 Reactor 算子间自动恢复上下文。
- `@Async` / 线程池：`spring.task.execution.propagate-context=true` 让自动配置的 `AsyncTaskExecutor` 传递上下文。

## Tests

> [!WARNING]
> `@SpringBootTest` **不会自动装配上报组件**（reporter / exporter 那一层）。测试里不会因为没起 Zipkin 而报错，但也意味着不要在测试中假设"span 一定能被导出"。需要验证埋点本身时用 tracer 的 API 断言 span 结构，或用 `ObservationRegistry` 的 test-friendly 实现。

## Sleuth vs Micrometer Tracing

| 维度 | Spring Cloud Sleuth（Boot 2.x） | Micrometer Tracing（Boot 3.x 起，含 Boot 4） |
| ---- | ---- | ---- |
| 定位 | Spring Cloud 子项目，自动装配 | Micrometer 体系下的 tracing 门面 |
| 底层实现 | 主要是 Brave | Brave 或 OpenTelemetry 桥接，可切换 |
| 观测统一 | tracing 与 metrics 分开 | tracing/metrics/logging 统一在 Micrometer + Observation API |
| 上下文传播 | B3 为主 | 支持 W3C TraceContext、B3 等多种 propagator |
| 传播格式默认 | B3 | W3C TraceContext |
| 埋点入口 | 大量专有自动配置 | `ObservationRegistry` / `@Observed` 统一入口 |
| 采样默认值 | `spring.sleuth.sampler.probability`，默认 0.1 | `management.tracing.sampling.probability`，默认 0.1 |

迁移时把 `spring-cloud-starter-sleuth` 换成 `spring-boot-starter-zipkin` 或 `spring-boot-starter-opentelemetry`，配置项从 `spring.sleuth.*` / `spring.zipkin.*` 迁到 `management.tracing.*` / `management.tracing.export.zipkin.*`。遗留 Sleuth 的完整配置与 API 见 [Sleuth](/docs/CS/Framework/Spring_Cloud/Sleuth.md)。

## Links

- [Sleuth](/docs/CS/Framework/Spring_Cloud/Sleuth.md) — 遗留 Spring Cloud Sleuth（Boot 2.x，已 EOL）
- [Tracing](/docs/CS/Distributed/Tracing/Tracing.md) — 可观测性三支柱、trace/span 数据模型
- [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md) — Brave 对接的追踪后端
- [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md) — OTLP 上报与 vendor-agnostic 遥测
- [Micrometer](/docs/CS/log/Micrometer.md) — JVM 侧埋点门面，Micrometer Tracing 的母体
- [Spring Boot Actuator](/docs/CS/Framework/Spring_Boot/actuator.md)

## References

1. [Spring Boot Reference - Tracing](https://docs.spring.io/spring-boot/reference/actuator/tracing.html)
2. [Micrometer Tracing Reference](https://docs.micrometer.io/tracing/reference/)
3. [Zipkin - B3 Propagation](https://github.com/openzipkin/b3-propagation)
4. [W3C Trace Context](https://www.w3.org/TR/trace-context/)
