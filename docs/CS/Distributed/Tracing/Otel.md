## OpenTelemetry

## Introduction

[OpenTelemetry](https://opentelemetry.io/)（简称 OTel）是一个 `可观测性`（Observability）框架和工具集，用于创建和管理 `traces`、`metrics`、`logs` 等 _遥测数据_（telemetry data）。
它是 Cloud Native Computing Foundation（CNCF）项目，2019 年由 [OpenTracing](/docs/CS/Distributed/Tracing/Tracing.md?id=opentracing) 与 OpenCensus 两个项目合并而成。

关键在于，OpenTelemetry 与厂商和工具无关（vendor- and tool-agnostic），可以对接各种可观测性后端，
既包括 [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md)、[Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md) 这类开源工具，也包括各类商业产品。

OpenTelemetry **不是**什么：

- OpenTelemetry **不是**像 Jaeger、Prometheus 或商业厂商那样的可观测性后端。
- 它不是某个具体的监控产品——没有"OpenTelemetry UI"，也没有存储。
- 它专注于遥测数据的 **生成、采集、管理和导出**。
  数据的存储与可视化刻意留给其他工具完成。

> OTel 与分布式追踪的具体关系（OpenTracing 沿革、与 Jaeger/Zipkin 的角色分工）见 [OpenTelemetry vs. Tracing](#opentelemetry-vs-tracing)。

## OpenTelemetry vs. Tracing

OpenTelemetry **源自**分布式追踪，但如今已经 **超出**了追踪的范畴。这层关系常被误解，值得说清楚。

### Evolution: OpenTracing + OpenCensus → OpenTelemetry

在 OTel 出现之前，追踪插桩分散在两个相互竞争的 CNCF/Google 项目中：

- [OpenTracing](/docs/CS/Distributed/Tracing/Tracing.md?id=opentracing)：厂商中立的追踪 **API 规范**（Span、SpanContext、`ChildOf`/`FollowsFrom` 引用——数据模型见 [Tracing](/docs/CS/Distributed/Tracing/Tracing.md)）。
- OpenCensus：Google 出品，把追踪与指标插桩打进同一套库，并附带共享的 agent/Collector。

2019 年两个社区合并为 OpenTelemetry：吸收了 OpenTracing 的 API 规范思路，也继承了 OpenCensus 开箱即用的 SDK/Collector 路线。OpenTracing 与 OpenCensus 均已归档，OpenTelemetry 是它们的继任者。OpenTracing 的数据模型（span 树、tags → attributes、logs → events、baggage）几乎原样延续到了 OTel。

### Tracing as One of the Three Pillars

分布式追踪回答的是"这个请求在系统里是怎么流转的"。OTel 保留了这一点，但把同一套插桩/导出管道推广到了可观测性的三大支柱：

```
                    ┌── Traces   (spans, trace context)   ──▶ Jaeger / Zipkin / Tempo ...
OpenTelemetry  ──── ┼── Metrics  (counters, histograms)   ──▶ Prometheus / Mimir ...
(API/SDK/Collector) └── Logs     (records + trace ids)    ──▶ Loki / Elasticsearch ...
```

所以"tracing"只是 OTel 产出的 **一种信号**；API/SDK/Collector 这套机制为所有信号共享——这正是 OTel 是 *可观测性* 框架而非追踪库的原因。

### Role Division in the Tracing Stack

在一个具体的分布式追踪方案里，各层角色是这样划分的：

| 角色 | 由谁承担 |
|---|---|
| 插桩 / API 与 SDK（创建 span、传播上下文） | OpenTelemetry |
| 导出协议 | OTLP（或经 Collector 转换的 Jaeger/Zipkin 协议） |
| 存储 + 查询 + UI（真正的"追踪系统"） | [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md)、[Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md)、[SkyWalking](/docs/CS/Distributed/Tracing/SkyWalking.md)、Grafana Tempo、各商业厂商 |
| 跨信号的仪表盘 | [Grafana](/docs/CS/Distributed/Tracing/Grafana.md) |

OpenTelemetry 并不取代 Jaeger/Zipkin/SkyWalking——它取代的是它们底下的 **插桩层**。
如今典型的部署方式是：OTel SDK 或 agent → OTLP → OTel Collector → Jaeger/Tempo/Prometheus，追踪后端作为 OTLP 数据的接收方。

两点实践注记：

- **上下文传播被标准化**：OTel 采用 W3C Trace Context / Baggage 头（`traceparent`、`tracestate`），因此即使各服务用了不同的厂商/工具插桩，也能参与同一条 trace。以前各厂商传播自己的头格式（如 Zipkin 的 `b3`），跨系统追踪很脆弱。
- **SkyWalking** 既是 APM 后端，也有自己的插桩生态（SW agent、自有协议）；在混合环境中，常见做法是保留 OTel SDK 做插桩，数据经 SkyWalking 的 OTLP receiver 写入。

## Components

OpenTelemetry 由几个部分组成，共同构成一条遥测管道：

```
Applications / Frameworks                Collector                    Backends
┌──────────────────────────┐        ┌──────────────────┐       ┌─────────────┐
│  OTel API  →  OTel SDK   │  OTLP  │ Receivers → Proc │ OTLP  │   Jaeger    │
│  (instrumentation libs)  │──────▶ │   → Exporters    │─────▶ │  Prometheus │
└──────────────────────────┘        └──────────────────┘       │   Logs / ...│
                                                               └─────────────┘
```

### API and SDK

- **API**：生成遥测数据的编程接口。插桩库基于它实现，对任何后端都没有硬依赖。
- **SDK**：API 的参考实现——负责遥测数据的配置、采样、处理与导出。
- **插桩库（instrumentation libraries）**：即插即用的库（如 `opentelemetry-java-instrumentation`），自动对主流框架和库做插桩（HTTP 客户端/服务端、gRPC、JDBC、Kafka、Spring 等）。

### Collector

[OpenTelemetry Collector](https://opentelemetry.io/docs/collector/) 是一个与厂商无关的代理组件，负责接收、处理并导出遥测数据。

- **Receivers**——数据怎么进来（OTLP、Jaeger、Zipkin 协议、Prometheus 抓取等）。
- **Processors**——数据在途时做什么（批处理、tail/head [Sampling](#sampling)、增删 attributes、过滤、脱敏）。
- **Exporters**——数据发往哪里（Jaeger、Prometheus、Kafka、各厂商等）。

部署形态可以是 **agent**（紧挨应用的 sidecar / DaemonSet），也可以是 **gateway**（多个应用共享的独立服务）——各拓扑的取舍见 [Deployment Patterns](#deployment-patterns)。
收益：应用与后端选型解耦、集中化的重试/批量/采样、敏感数据过滤，以及协议转换。

一份完整的 Collector 配置（`config.yaml`）把三个构件接成有名字的管道：

```yaml
receivers:
  otlp:
    protocols:
      grpc:   # 默认端口 4317
      http:   # 默认端口 4318
  jaeger:
    protocols:
      thrift_http:   # 兼容旧的 Jaeger 客户端

processors:
  batch:
    timeout: 5s
    send_batch_size: 1024
  tail_sampling:
    decision_wait: 10s
    policies:
      - name: errors-always
        type: status_code
        status_code: { status_codes: [ERROR] }
      - name: slow-traces
        type: latency
        latency: { threshold_ms: 1000 }
      - name: baseline
        type: probabilistic
        probabilistic: { sampling_percentage: 10 }
  attributes/redact:
    actions:
      - key: http.request.header.authorization
        action: delete

exporters:
  otlp/jaeger:
    endpoint: jaeger-collector:4317
    tls: { insecure: true }
  prometheus:
    endpoint: 0.0.0.0:8889

service:
  pipelines:
    traces:
      receivers: [otlp, jaeger]
      processors: [attributes/redact, tail_sampling, batch]
      exporters: [otlp/jaeger]
    metrics:
      receivers: [otlp]
      processors: [batch]
      exporters: [prometheus]
```

注意 Collector 有两个发行版：**core**（精简，常用组件）和 **contrib**（完整组件库——覆盖大多数厂商和协议的 receivers/exporters/processors）。

### OTLP (OpenTelemetry Protocol)

OTLP（OpenTelemetry Protocol）是为 OpenTelemetry 数据原生设计的传输协议（gRPC 或 HTTP，通常以 Protobuf 编码）。
它是推荐的导出路径；不支持 OTLP 的后端可以通过 Collector 做桥接。

## Signals

### Traces

Trace 表示一个请求在分布式系统中的完整旅程。
它是一棵 **span 组成的 DAG**，每个 span 包含：

- 操作名（operation name）
- 开始 / 结束时间戳
- `Attributes`——key:value 元数据（字符串、布尔、数值）
- `Events`——带时间戳的注记，各自可带 attributes
- `SpanContext`——全局唯一的 `TraceId` + `SpanId`，外加 `TraceFlags` 与 `TraceState`（W3C Trace Context），跨进程传播
- 指向因果相关 span 的引用——`ChildOf`（一个 span 依赖另一个）或 `FollowsFrom`（一个 span 在另一个之后触发，如异步任务）

上下文传播（context propagation）借助受支持的协议在进程间传递 SpanContext（W3C `traceparent` 头、gRPC metadata、消息队列头）。
Baggage（随 trace 上下文一起传播的 key:value 对）可以携带非遥测数据，比如 A/B 测试开关。

span 的 `TraceId` 就是与日志做关联的 join key——见 [Logs ↔ Traces](#correlating-the-three-signals)；span 的 `SpanKind` 与 attributes 遵循 [Semantic Conventions](#baggage--semantic-conventions)。

### Metrics

Metrics 是按时间记录的数值采样。主要的度量Instrument（instrument）：

- **Counter**——只增不减的累计值（如请求数）。
- **UpDownCounter**——可增可减的累计值（如活跃连接数）。
- **Histogram**——值的分布（如请求延迟分位数）。
- **Gauge**——某一时刻的测量值（如 CPU 温度）。

Metric 序列与 span、日志共享同一套 resource attributes，并且可以携带 **exemplars**，指向产生某次测量的 trace——从"p99 飙高"跳到"具体是哪些请求慢"的链接见 [Metrics ↔ Traces (Exemplars)](#correlating-the-three-signals)。

OTel metrics 与 [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md) 的关系（导出路径、temporality、命名）详见 [OTel vs. Prometheus & Logging Frameworks](#otel-vs-prometheus--logging-frameworks)。

### Logs

日志是带时间戳的离散事件记录。OpenTelemetry 提供：

- **log bridge API**（桥接现有的日志框架，如 SLF4J / Log4j / java.util.logging）
- **SDK + Collector** 路径，为每条日志记录附上当前 `TraceId`/`SpanId`——这是三大支柱能够互相关联的关键。

`trace_id` 实际如何进入日志记录、span 与日志行之间如何互跳，见 [Logs ↔ Traces](#correlating-the-three-signals)。
OTel 日志如何与现有日志框架（Log4j/Logback/SLF4J）及采集器（Fluentd/Fluent Bit/Filebeat）共存，详见 [OTel vs. Prometheus & Logging Frameworks](#otel-vs-prometheus--logging-frameworks)。

### Baggage and Semantic Conventions

- **Baggage**：随 trace 上下文在带内传播的 key:value 对。
- **Semantic Conventions（语义约定）**：标准化的 attribute 名称和取值（如 `http.method`、`db.system`、`k8s.pod.name`），使后端和仪表盘可以统一处理遥测数据，而不管它由哪个库产生。这些属性的载体叫 resource，用于描述产生遥测数据的实体（服务名、版本、环境等）。

## OTel vs. Prometheus & Logging Frameworks

一个常见问题：OTel metrics 会 *取代* Prometheus 吗？OTel logs 会 *取代* Log4j/SLF4J 吗？都不会——两者是互补关系，但每个信号的细节不同。

### Metrics: OTel and Prometheus

Prometheus 是 **后端**：抓取（pull）、时序存储、PromQL、告警。OTel metrics 是 **插桩 API/SDK**——二者分管管道的不同半段，并且可以双向互通：

```
OTel SDK ──(prometheus exporter: /metrics endpoint)──▶ Prometheus scrape
OTel SDK ──(OTLP push)──▶ Collector ──(remote write)──▶ Prometheus
Prometheus ──(prometheus receiver: scrape existing /metrics)──▶ Collector ──OTLP──▶ anywhere
Prometheus ≥ 3.0 ──(native OTLP ingest)──▶ accepts OTLP directly
```

需要注意的关键差异：

| 维度 | OTel Metrics | Prometheus |
|---|---|---|
| 角色 | *产出* 指标的 API/SDK | 存储、PromQL、告警 |
| 传输 | Push（OTLP） | Pull（scrape） |
| Temporality | Cumulative **或 delta** | 仅 cumulative（delta 由 Collector 转换） |
| 直方图 | 原生（bucket counts + min/max/sum，支持 exponential buckets） | 经典 buckets；native histograms 较新 |
| 命名 | 语义约定驱动 | sanitize 后的名称、counter 加 `_total` 后缀、单位后缀 |

实践结论：已有 Prometheus 就继续把它当 metrics 后端；把 **插桩** 切换到 OTel，让三大信号共享同一套 API、resource 模型和管道。Collector 负责转换 temporality 和命名，PromQL 和既有仪表盘不受影响。

### Logs: OTel, Logging Frameworks, and Collectors

日志是"共存"最彻底的信号，因为日志框架负责的 **应用侧** 职责正是 OTel 不想重新发明的：

- **框架（产出）**：SLF4J/Log4j/Logback/java.util.logging 继续负责格式化、级别、文件滚动、异步 appender。OTel 是挂接而不是取代：
  - **log bridge API** 让框架的记录走 OTel SDK 输出（如 `opentelemetry-logback-appender-1.0` 把 Logback appender 变成 OTLP 日志导出器，并自动注入 `trace_id`/`span_id`）；
  - Java agent 即使日志仍写文件，也会注入 MDC 上下文。
- **采集（ship）**：Collector 的 `filelog`/`journald`/`k8sobjects` receiver 可以直接读取框架落盘的日志文件并做转换——这就是 OTel 对 Fluentd/Fluent Bit/Filebeat 的回答。`fluentforward` receiver 甚至能原样接收现有 Fluent Bit agent 的输出。
- **后端（存储/查询）**：Loki、Elasticsearch/ELK 等仍是目的地；Collector 只是把 OTLP 日志导出给它们（`loki` exporter、Elasticsearch exporter，或受支持处的 OTLP）。

所以分层是这样的：

| 层 | 传统技术栈 | 引入 OTel 后 |
|---|---|---|
| 代码内输出 | Log4j / Logback / SLF4J | 不变（经 appender 桥接或 MDC 注入） |
| 采集 / 解析 | Fluentd、Fluent Bit、Filebeat | OTel Collector（receiver 承担同样职责） |
| 存储与查询 | Elasticsearch、Loki | 不变 |

## Correlating the Three Signals

OTel 真正的价值在于：三大支柱不是三股互不相干的数据流——它们共享两个粘合点。（三个信号本身分别在 [Traces](#traces)、[Metrics](#metrics)、[Logs](#logs) 中描述。）

1. **Resource**——每种信号（span、metric 序列、日志记录）都携带相同的 resource attributes（`service.name`、`service.version`、`deployment.environment`），所以无论数据来自哪种信号，都能按服务聚合。
2. **TraceContext**——日志和指标可以附带当前 `trace_id`/`span_id`，形成信号之间的跳转链接。

```
   Metrics (Prometheus)          Traces (Tempo/Jaeger)         Logs (Loki/ES)
   ┌───────────────────┐         ┌──────────────────┐         ┌──────────────┐
   │ histogram bucket   │exemplar│     Trace         │trace_id│ Log records   │
   │ + error rate alert │───────▶│  (span timeline,  │───────▶│ with TraceId  │
   │                    │        │   service DAG)    │        │ in the fields │
   └───────────────────┘         └──────────────────┘         └──────────────┘
          alert ▶ which requests were slow? ▶ what exactly happened inside?
```

### Logs ↔ Traces

- 开启 **自动插桩** 后，Java agent 会自动把 `trace_id`/`span_id` 注入日志 MDC；你只需把它们加进日志 pattern（Log4j/Logback 用 `%X{trace_id}`）。log bridge / Collector 转换对以纯文本输出的记录同样有效。（配置方式见 [Java example](#example-java)。）
- 于是每条日志都带着 TraceId，从 Jaeger/Tempo 的任意 span 都能跳到这次请求的日志（Grafana 中的 "Trace to Logs" 关联），从任意日志行也能跳回它的 trace。
- Span **events** 和 `recordException(e)` 会把错误详情直接嵌入 span，与错误日志互为镜像。

### Metrics ↔ Traces (Exemplars)

- **Exemplar** 是从 metric 数据点指向代表性 trace 的指针：比如记录请求延迟的 histogram bucket，同时存下了那次请求的 `trace_id`。
- 在 Prometheus + Grafana Tempo 中，exemplar 在直方图上显示为小圆点；点开一个就打开产生该测量的 trace。这就是从"p99 飙高"一步到"实际慢的请求长这样"的方式。
- Exemplar 需要 metric 导出器支持（OTLP 原生支持；Prometheus exposition 格式需要 `Exemplar` 行）。

### Debugging Loop

串起来之后，故障排查就从三次独立检索变成一个闭环：

1. **Metric 告警** 触发：`order-service` 错误率 > 2%。
2. 仪表盘显示飙升发生在发布 2.4.1 之后 → 打开错误率序列上的一个 **exemplar**。
3. **Trace** 显示延迟集中在 `payment-service` 的 gRPC 调用上，某个 span 标记为 ERROR。
4. 用 span 的 **trace_id** 拉出匹配的 **日志**：连接池超时，附带下游 pod 名。

这条链路上的每一跳都来自 OTel 的约定（共享 resource、日志中的 trace context、metrics 中的 exemplars）——后端只需要支持按这些 key 跳转。

## Sampling

在规模化场景下 100% 采集 trace 几乎不可承受——追踪量随流量增长，而长尾 trace 恰恰是最占存储的部分。采样决定保留哪些 trace：

- **Head sampling（头部采样）**——在 trace 最开始（根 span 处）就做决定，并经由 trace flags 把决定传播给所有下游服务，从而保证整条 trace 一致地保留或丢弃。便宜且可预测，但它是盲的：无法专门留住"有意思"的 trace。
  - SDK `Sampler`：`always_on`、`always_off`、`traceidratio`（按比例概率采样）、`parentbased_*`（尊重父级的决定——通常作为默认值）。
- **Tail sampling（尾部采样）**——等一条 trace 的所有 span 到齐后再决定，通常在 Collector 上做（`tail_sampling` processor）。这样可以按策略保留：错误 trace 必留、慢 trace（> p99）必留、带特定属性的 trace 必留，其余按概率采样。
  - 代价：collector 必须缓冲整条 trace（`decision_wait`），且 collector 集群间需要一致性哈希。

常见的生产组合：SDK 侧设置一个较小的 **head** 比例控制总量 + 网关 collector 上的 **tail** 策略保证错误/慢 trace 永不丢失。这里提到的 tail 策略作为 Collector processor 配置，见 [Collector](#collector) 的配置示例。

## Deployment Patterns

从简单到健壮的典型拓扑：

```
1. Direct:           App (SDK) ──OTLP──▶ Backend
2. Agent:            App ──▶ sidecar/DaemonSet collector ──▶ Backend
3. Agent + Gateway:  App ──▶ agent collector ──▶ gateway collector ──▶ Backend(s)
```

- **Direct** 适合开发环境（Jaeger all-in-one 在 4317 端口直接收 OTLP）。
- **Agent** 从本机节点采集，做批量/重试，把应用与后端故障隔离开。
- **Agent + Gateway** 是生产标配：agent 快速上送原始数据；gateway 层做 tail [Sampling](#sampling)、脱敏和向多个后端的分发。SDK 只需要知道 `localhost:4317`。

在 Kubernetes 上，[OpenTelemetry Operator](https://opentelemetry.io/docs/kubernetes/operator/) 把这些自动化：通过 `OpenTelemetryCollector` CRD 管理 Collector 部署，通过 pod 注解注入自动插桩（`instrumentation.opentelemetry.io/inject-java: "true"`），并提供 `Instrumentation` CRD 设置 SDK 默认配置。

## Instrumentation

两种互补的方式：

1. **零代码（自动插桩）**——不改代码，挂 agent 或启用框架钩子：
   - Java：`-javaagent:opentelemetry-javaagent.jar`
   - Python/Node.js：`opentelemetry-instrument` 包装器
   - Kubernetes Operator 自动插桩
2. **代码级（手动插桩）**——在代码里用 API 创建自定义 span、添加 attributes、记录异常、构建业务指标。通常与框架层的自动插桩配合使用。

## Example (Java)

一个最小的手动 span（何时用手动、何时用零代码见 [Instrumentation](#instrumentation)）：

```java
// Tracer obtained from the SDK (or auto-instrumentation)
Tracer tracer = openTelemetry.getTracer("com.example.orders");

Span span = tracer.spanBuilder("processOrder")
        .setSpanKind(SpanKind.SERVER)
        .setAttribute("order.id", orderId)
        .startSpan();

try (Scope scope = span.makeCurrent()) {
    // business logic — downstream calls automatically become children
} catch (Exception e) {
    span.recordException(e);
    span.setStatus(StatusCode.ERROR);
    throw e;
} finally {
    span.end();
}
```

配置通常通过环境变量或 `otel` 属性完成：

```bash
export OTEL_SERVICE_NAME=order-service
export OTEL_EXPORTER_OTLP_ENDPOINT=http://localhost:4317
export OTEL_TRACES_EXPORTER=otlp
```

## Links

- [Tracing](/docs/CS/Distributed/Tracing/Tracing.md)
- [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md)
- [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md)
- [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md)
- [Grafana](/docs/CS/Distributed/Tracing/Grafana.md)

## References

1. [OpenTelemetry Documentation](https://opentelemetry.io/docs/)
2. [OpenTelemetry Specification](https://opentelemetry.io/docs/specs/otel/)
3. [OpenTelemetry Protocol (OTLP)](https://opentelemetry.io/docs/specs/otlp/)
4. [OpenTracing specification](https://opentracing.io/specification/)
5. [OpenTelemetry Collector](https://opentelemetry.io/docs/collector/)
6. [Tail Sampling Processor](https://github.com/open-telemetry/opentelemetry-collector-contrib/tree/main/processor/tailsamplingprocessor)
7. [OpenTelemetry Operator (Kubernetes)](https://opentelemetry.io/docs/kubernetes/operator/)
