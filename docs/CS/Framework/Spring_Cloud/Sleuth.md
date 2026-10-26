## Introduction

**Spring Cloud Sleuth** 曾是 Spring Cloud 的分布式链路追踪自动装配组件，负责自动打标、传播 trace 上下文、对接 [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md)。它在 **Spring Cloud 2022.0（对应 Spring Boot 3.0）一档被移除**，能力由 **Micrometer Tracing** 承接（现行做法见 [Spring Boot 链路追踪](/docs/CS/Framework/Spring_Boot/tracing.md)）。

本篇只记录 **Sleuth 本身（Boot 2.x 一代）** 的事实：它的自动埋点范围、配置、API 与日志关联。新项目不要再引入 Sleuth；存量 Boot 2.x 系统仍在用它。trace / span / baggage 这套数据模型与现行做法一致，概念见 [Tracing](/docs/CS/Distributed/Tracing/Tracing.md)。

## Architecture and Automatic Instrumentation

Sleuth 的核心是一个基于 [Brave](/docs/CS/Distributed/Tracing/Zipkin/Transport.md) 的 `Tracer`，由 `TraceAutoConfiguration` 装配；应用内的 span 经 `CompositeReporter` 串起若干 `SpanAdjuster` 后再交给底层 reporter 异步上报。Web 侧通过 servlet 的 `TracingFilter`（WebFlux 下是响应式等价物）拦截入/出口。

它**开箱即用地埋点**了 Spring 应用的常见入/出口点，无需手写：

- **HTTP**：servlet filter / WebFlux 过滤器，自动注入与提取 B3 头。
- **客户端**：`RestTemplate`（须用自动配置的 `RestTemplateBuilder`）、`WebClient`、Feign（`TraceFeignClientAutoConfiguration`）。
- **异步**：`@Async`、`@Scheduled`、`Executor` / `ExecutorService`（提供 `TraceRunnable` / `TraceCallable` 包装）。
- **消息**：Spring Integration / Spring Cloud Stream 通道、Kafka、RabbitMQ、JMS（按 `spring.sleuth.messaging.*` 开关）。
- **其它**：Zuul / Gateway 过滤器、Redis、gRPC、CircuitBreaker、Reactor（`spring.sleuth.reactor.enabled`）、RxJava 调度钩子。

> [!WARNING]
> 自己 `new RestTemplate()` 出来的客户端**不带传播逻辑**，trace 到这一跳就断且毫无报错。链路下游会出现"孤零零的新 trace"。务必使用框架自动配置的 Builder。

## Dependency

```xml
<dependency>
    <groupId>org.springframework.cloud</groupId>
    <artifactId>spring-cloud-starter-sleuth</artifactId>
</dependency>
```

接入 Zipkin 上报通常再加 `spring-cloud-sleuth-zipkin`；走消息中间件的旧路径是 `spring-cloud-sleuth-stream`（Spring Cloud Stream + Kafka/Rabbit）。

## Configuration

主要配置项（前缀 `spring.sleuth.*`；上报地址在 `spring.zipkin.baseUrl`）：

| 配置项 | 默认 | 作用 |
| :-- | :-- | :-- |
| `spring.sleuth.enabled` | `true` | 总开关 |
| `spring.sleuth.sampler.probability` | `0.1` | 采样比例（10%）；旧版属性名为 `spring.sleuth.sampler.percentage` |
| `spring.sleuth.propagation.type` | `B3` | 传播格式，`B3` / `W3C` / `AWS`（Brave 支持）可列多个 |
| `spring.sleuth.web.enabled` / `reactor.enabled` | `true` | Web / 响应式埋点开关 |
| `spring.sleuth.async.enabled` | `true` | 异步组件（线程池、`@Async`）透传追踪上下文 |
| `spring.sleuth.integration.enabled` | `true` | Spring Integration 埋点 |
| `spring.sleuth.feign.enabled` | `true` | Feign 透传 |
| `spring.sleuth.messaging.kafka.enabled` / `rabbit.enabled` / `jms.enabled` | `true` | 消息中间件埋点 |
| `spring.sleuth.redis.enabled` / `grpc.enabled` / `circuitbreaker.enabled` | `true` | 各自埋点开关 |
| `spring.sleuth.baggage.remote-fields` | — | 要向下游请求头传播的 baggage 字段名 |
| `spring.sleuth.baggage.correlation-fields` | — | 要写进 SLF4J MDC 的 baggage 字段名 |
| `spring.sleuth.baggage.tag-fields` | — | 要作为 span tag 的 baggage 字段名 |
| `spring.sleuth.log.json` | `false` | 以 JSON 形式输出含追踪字段的日志 |
| `spring.zipkin.baseUrl` | `http://localhost:9411` | Zipkin collector 地址 |

> [!NOTE]
> `spring.sleuth.baggage.local-fields` 与 `remote-fields` 类似但不向下游传播；`spring.sleuth.propagation.tag.enabled=false` 可关闭"baggage 自动变 tag"。

## Core API

绝大多数场景靠自动埋点即可，但手动打标要走 Brave 之上的 `Tracer`：

```java
@Service
class PaymentService {

	private final Tracer tracer;

	void pay(Order order) {
		// 在一个已存在的 span 内新建子 span
		Span span = tracer.nextSpan().name("payment.authorize").start();
		try (Tracer.SpanInScope ws = tracer.withSpanInScope(span)) {
			span.tag("order.id", order.id());
			span.event("authorized");
			// 业务逻辑……
		} finally {
			span.end();
		}
	}

	void attach(Order order) {
		Span current = tracer.currentSpan();   // 取当前 span，可能为 null
		if (current != null) {
			current.tag("order.channel", order.channel());
		}
	}
}
```

- `tracer.nextSpan()`：在当前上下文下新建一个子 span；`tracer.newTrace()` 才是新 trace 的根。
- `tracer.withSpanInScope(span)`：把 span 设为当前上下文，返回 `SpanInScope`，try-with-resources 结束即恢复。
- `tracer.currentSpan()`：取当前 span（无则返回 null）。
- `tracer.createBaggage(key)` / `createBaggageInScope(key, value)`：创建/挂入 baggage。

注解方式（包 `org.springframework.cloud.sleuth.annotation`）适用于**接口方法**（如 Spring Data / Feign 生成的实现），避免直接依赖 Tracer API：

```java
@Repository
public interface UserRepository extends JpaRepository<User, Long> {
	@NewSpan("find user by name")          // 围绕方法新建 span，名字可静态指定
	Optional<User> findByName(@SpanTag("user.name") String userName);  // 参数自动作为 tag
}

@Service
class AuditService {
	@ContinueSpan(log = "audit")           // 不新建，只在已有 span 上加 tag / event
	void record(@SpanTag("audit.actor") String actor) { /* ... */ }
}
```

- `@NewSpan`：围绕方法创建新 span；可配 `name`。
- `@ContinueSpan`：延续已有 span，可配 `log`（生成 `.before` / `.after` / `.afterFailure` 事件）。
- `@SpanTag`：把方法参数作为 tag；支持 `resolver`（TagValueResolver）/ `expression`（SpEL）。
- `@SpanName`：为部分 instrumentation 场景提供自定义 span 名。

## MDC and Log Correlation

Sleuth 把 trace 上下文写入 SLF4J **MDC**，默认日志 pattern 为：

```properties
logging.pattern.level=%5p [${spring.zipkin.service.name:${spring.application.name:-}},%X{X-B3-TraceId:-},%X{X-B3-SpanId:-},%X{X-Span-Export:-}]
```

即日志前缀是四元组 **`[appname, traceId, spanId, exportable]`**：

```
2019-08-28 16:16:10.187 INFO [sleuth-user-service,81bc3db3c143f1fb,c0cf0d53ce2a8047,false] 6356 --- [nio-8083-exec-1] c.c.e.controller.UserController: ...
```

- `appname`：`spring.application.name`（或 `spring.zipkin.service.name`）。
- `traceId` / `spanId`：对应 MDC 键 `X-B3-TraceId` / `X-B3-SpanId`。
- `exportable`：该 span 是否会被导出到 Zipkin（对应 MDC 键 `X-Span-Export`）。

MDC 始终会被设置，logback 用户立即能在日志里看到这些 ID；其它日志系统需自行配置 formatter 才能生效。

## Sampling

默认**只采样 10%**（`spring.sleuth.sampler.probability` 默认 `0.1`）。未被采样的 span **仍有 traceId / spanId**（保证日志可关联），只是不导出到 Zipkin——日志能看到、后端查不到属正常现象。

另有 `spring.sleuth.sampler.rate` 可启用 `RateLimitingSampler`（按每秒请求数限流采样），用于高吞吐下稳定控制上报量。

## Baggage

Baggage 是随 trace **跨进程透传**的键值；与 tag 的关键区别是——**baggage 会随请求头传播到下游，tag 只留在当前 span**。

```java
try (BaggageInScope scope = tracer.createBaggage("tenant-id").set("acme")) {
	// 该范围内及下游调用都能读到 tenant-id
}
```

用属性声明字段（无需写代码）：

```yaml
spring:
  sleuth:
    baggage:
      remote-fields:        # 写入请求头向远端传播
        - tenant-id
        - x-vcap-request-id
      correlation-fields:   # 写入 MDC，使其出现在日志
        - tenant-id
      tag-fields:           # 同时作为 span tag，便于在 Zipkin 按 baggage 检索
        - tenant-id
```

> [!WARNING]
> 写入 MDC 会显著影响性能（尤其高吞吐）。baggage 数量与大小应克制，过多可能撑爆传输层 header 容量甚至拖垮应用。

## Context Propagation

Sleuth 默认用 **B3** 格式传播（`X-B3-TraceId` / `X-B3-SpanId` / `X-B3-ParentSpanId` / `X-B3-Sampled`）。切换到 W3C 只需：

```yaml
spring:
  sleuth:
    propagation:
      type: W3C
```

> [!NOTE]
> **W3C 传播自动携带 baggage，B3 不会**。用 B3 时若发现 baggage 没传下去，要么改用 W3C，要么把字段显式列进 `spring.sleuth.baggage.remote-fields` 手动传播。

## Reporting to Zipkin

默认通过 HTTP 把 span 上报到 `localhost:9411`（Zipkin 单机默认端口），用 `spring.zipkin.baseUrl` 改地址。span 经应用内 reporter 异步发送，队列满或发送失败时丢 span 并计入 metrics，不影响业务线程。

旧一代还提供 `spring-cloud-sleuth-stream`：经 Spring Cloud Stream（Kafka / RabbitMQ / Redis）把追踪消息发到 broker，由消费端统一落 Zipkin——这条路径已被直接对接消息中间件的埋点（`spring.sleuth.messaging.*`）取代。

## EOL and Migration

Sleuth 在 **Spring Cloud 2022.0（Boot 3.0）被移除**，由 Micrometer Tracing 承接。迁移步骤：

1. 把 `spring-cloud-starter-sleuth` 换成 `spring-boot-starter-zipkin`（Brave 后端）或 `spring-boot-starter-opentelemetry`（OTLP 后端）。
2. 配置项改名：`spring.sleuth.*` → `management.tracing.*`；`spring.zipkin.baseUrl` → `management.tracing.export.zipkin.endpoint`。
3. 手动埋点从 Sleuth 的 `Tracer` / `@NewSpan` 迁到 Micrometer `Tracer` / Observation API（见 [Spring Boot 链路追踪](/docs/CS/Framework/Spring_Boot/tracing.md)）。
4. 日志格式：现行默认 `[traceId-spanId]`；要还原 Sleuth 的 `[appname,traceId,spanId]` 用 `logging.pattern.correlation`。

## Links

- [Spring Boot 链路追踪](/docs/CS/Framework/Spring_Boot/tracing.md) — 现行 Micrometer Tracing 做法（Sleuth 的继任者）
- [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md) — Sleuth 默认对接的追踪后端
- [Zipkin Transport](/docs/CS/Distributed/Tracing/Zipkin/Transport.md) — Brave reporter / Sender 与 B3 传播
- [Tracing](/docs/CS/Distributed/Tracing/Tracing.md) — trace/span/baggage 数据模型
- [Micrometer](/docs/CS/log/Micrometer.md) — Micrometer Tracing 的母体门面
- [Spring Cloud](/docs/CS/Framework/Spring_Cloud/Spring_Cloud.md)

## References

1. [Spring Cloud Sleuth 3.0 Reference - Appendix A (common properties)](https://docs.spring.io/spring-cloud-sleuth/docs/3.0.0-M2/reference/html/appendix.html)
2. [Spring Cloud Sleuth Reference (3.1) - Features & Annotations](https://docs.spring.io/spring-cloud-sleuth/docs/3.1.0-SNAPSHOT/reference/pdf/index.pdf)
3. [Micrometer - Tracing (successor to Sleuth)](https://micrometer.io/)
4. [Zipkin - B3 Propagation](https://github.com/openzipkin/b3-propagation)
