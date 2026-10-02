## Introduction

[Micrometer](https://micrometer.io/) 是 JVM 应用的**可观测性门面（facade）**：在代码里只依赖一套中立的 meter API，运行时再绑定到具体后端——[Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md)、[OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md)、Datadog、StatsD、JMX 等。官方定位是 **"SLF4J, but for metrics"**：正如 SLF4J 让日志 API 与 logback/log4j2 实现解耦，Micrometer 让指标埋点与监控后端解耦。

需要注意定位差异：Micrometer 最初是 **metrics** 门面；Micrometer Tracing（前身 Spring Cloud Sleuth）补上 **tracing** 桥接，底层委托给 OpenTelemetry 或 Brave/Zipkin  reporter；日志仍走 SLF4J/[logback](/docs/CS/log/logback.md)。三者通过 trace id 相互关联（见 [三大信号关联](/docs/CS/Distributed/Tracing/Otel.md?id=correlating-the-three-signals)）。

## Modules

| 模块 | 作用 |
| --- | --- |
| `micrometer-commons` / `micrometer-observation` | 通用抽象；Observation API 用统一模型表达 metrics + tracing |
| `micrometer-core` | 核心 meter 实现、JVM/进程 binder、简单 registry |
| `micrometer-registry-prometheus` | 导出 Prometheus 文本格式（供 `/actuator/prometheus` 拉取） |
| `micrometer-registry-otlp` | 以 OTLP 推送 metrics 到 OTel Collector |
| `micrometer-tracing` | tracing 门面，适配 OTel / Brave 两种 tracer |
| `micrometer-tracing-bridge-otel` | 桥接到 OpenTelemetry SDK |

Spring Boot Actuator 通过 [actuator](/docs/CS/Framework/Spring_Boot/actuator.md) 自动装配 `MeterRegistry` 与各 binder，业务代码通常只需注入 registry，无需手工 new。

## Meter Types

Micrometer 的 meter 类型与 Prometheus 指标类型对应，但做了跨后端抽象：

| Meter | 语义 | 典型用途 |
| --- | --- | --- |
| **Counter** | 单调递增计数器 | 请求总数、错误数 |
| **Gauge** | 瞬时可上下波动的值 | 队列长度、内存使用、连接数 |
| **Timer** | 记录耗时分布与次数 | 接口延迟（自动产出 count/sum/histogram） |
| **DistributionSummary** | 记录值的分布（不含时间单位） | 响应体大小、payload 分布 |
| **LongTaskTimer** | 进行中任务的持续时间 | 长任务、批处理占用 |
| **TimeGauge** | 自定义可映射为时间的 gauge | 线程池活跃时长等 |

Timer/Summary 支持**服务端直方图**与客户端分位（percentiles）：

```java
Timer timer = Timer.builder("http.server.requests")
        .tag("uri", "/orders/{id}")
        .publishPercentiles(0.5, 0.95, 0.99)
        .register(registry);
timer.record(() -> handle(req));      // 包裹业务调用
```

## MeterRegistry

`MeterRegistry` 是所有 meter 的注册中心与后端适配点：

- **SimpleMeterRegistry**：内存实现，测试/默认兜底，不导出。
- **PrometheusMeterRegistry**：维护可抓取文本，配合 actuator 暴露端点。
- **OtlpMeterRegistry**：按 OTLP 周期 push 到 Collector。
- **CompositeMeterRegistry**：聚合多个 registry，同一份埋点同时发往多个后端。

命名约定：Micrometer 在 API 层用**点分小写**命名（`http.server.requests`），由 registry 负责映射到后端风格——Prometheus 转下划线并补单位后缀（`http_server_requests_seconds_*`），OTLP 则遵循 [Semantic Conventions](/docs/CS/Distributed/Tracing/Otel.md)。维度通过 **tag/label** 表达。

## Observation API

`Observation` 是新一代统一埋点抽象，同一段代码同时产生 metrics 与 tracing span：

```java
Observation.createNotStarted("user.lookup", observationRegistry)
        .lowCardinalityKeyValue("country", "CN")
        .observe(() -> userService.findById(id));
```

- 高基数（high cardinality）KV 只进 tracing，低基数（low cardinality）KV 才进 metrics，避免把 user_id 这类标签打爆 Prometheus 时间序列。
- 这与 OTel 的「一个观测点、多种 signal」理念一致，也是 Micrometer 向 OpenTelemetry 模型对齐的关键。

## Integration with Spring Boot

1. 引入 `spring-boot-starter-actuator` + `micrometer-registry-prometheus`。
2. 暴露端点：`management.endpoints.web.exposure.include=prometheus,health,metrics`。
3. 访问 `/actuator/prometheus` 即可被 Prometheus 抓取；Boot 自动注册 JVM（GC、内存、线程）、HTTP 请求、日志事件等 binder。
4. 启用 tracing：加 `micrometer-tracing-bridge-otel` + OTLP exporter，trace id 会自动写入 MDC，日志中可打印 `%X{traceId}`，实现日志↔链路关联。

## Links

- [logback](/docs/CS/log/logback.md)
- [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md)
- [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md)
- [Tracing](/docs/CS/Distributed/Tracing/Tracing.md)
- [actuator](/docs/CS/Framework/Spring_Boot/actuator.md)

## References

1. [Micrometer Reference Documentation](https://docs.micrometer.io/)
2. [Micrometer Concepts](https://docs.micrometer.io/micrometer/reference/concepts.html)
3. [Micrometer Tracing](https://docs.micrometer.io/tracing/reference/)
4. [Spring Boot Metrics](https://docs.spring.io/spring-boot/reference/actuator/metrics.html)
