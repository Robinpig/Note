## Introduction

可观测性的圣杯，是拥有一套系统，让你无需为诊断而额外部署代码，就能发现任何此前未知的状态。
监控（Monitoring）与可观测性（Observability）彼此独立却又相互依赖：一个系统若可被观测，它就能被监控。

可观测性的三大支柱是 **Metrics（指标）**、**Tracing（追踪）** 与 **Logging（日志）**。
每一根支柱在基础设施与应用监控中都扮演独特角色，对于洞察容器化或无服务器应用至关重要。

单独使用某一根支柱、或为每个支柱各用一套工具，并不能保证可观测性。
但将 metrics（指标）、traces（追踪）与 logs（日志）整合进同一套方案，你才能构建出真正有效的可观测性实践。

[OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md) 定义了一套统一的方式来生成并关联这三个信号——
详见其 [Signals](/docs/CS/Distributed/Tracing/Otel.md?id=signals) 与 [Correlating the Three Signals](/docs/CS/Distributed/Tracing/Otel.md?id=correlating-the-three-signals) 章节。

### 指标

Metrics 是用数值表示、并描述某个服务或组件随时间变化整体行为的度量。
它们通常带有时间戳、名称和取值等特征。
与 logs 不同，metrics 默认就是结构化的，
因此易于查询和为存储做优化，可以将其长期保留。

借助监控工具，你可以可视化关心的指标并配置告警（尤其是像 [Prometheus](https://prometheus.io/) 这样的工具）。
大多数基于指标的监控方案允许你组合少量标签（label）的数据，从而看出是哪个服务出了问题、或问题发生在哪些机器上。
Metrics 让你能够定义什么是正常、什么是不正常。

假设你收到一条来自 [PagerDuty](https://www.pagerduty.com/) 的告警，提示某个服务（我们称之为 "Order service"）的数据库连接数超过了最大阈值。
新的连接可能正在超时，或请求正在排队、推高了延迟——你还无从得知。
触发告警的那个指标，并不会告诉你客户正经历着什么，也不会说明系统为什么会变成当前这个状态。
你需要可观测性的其它支柱才能了解更多。

### 追踪

Tracing 用于理解一个应用的不同服务之间如何连接、资源如何在它们之间流动。
Traces 帮助工程师分析请求流转，并理解一条请求在分布式应用中的完整生命周期。
对请求执行的每一个操作（也称作一个 "span"），在流经宿主系统的过程中，都会携带与执行该操作微服务相关的关键数据。
追踪一条 trace 在分布式系统中的路径，有助于你定位瓶颈或故障的根因。

借助 tracing 工具，例如 [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md) 和 [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md)，
你可以深入每一次系统调用，弄清底层组件到底发生了什么
（哪些最耗时、哪些最省时、特定底层进程是否产生了错误，等等）。
Traces 也是深入剖析一次 metrics 告警的绝佳手段。

分布式追踪（distributed tracing，又称分布式请求追踪）是一种用于剖析和监控应用的方法，尤其适用于基于微服务架构构建的应用。
分布式追踪能帮助 pinpoint（定位）故障发生的位置以及性能低下的成因。

1. 快速定位请求失败原因
2. 优化系统瓶颈
2. 优化链路调用
3. 生成网络拓扑
4. 透明传输数据 比如A/B测试开关逻辑可以通过该数据传递


一个服务追踪系统可以分为三层
- 数据采集层，负责数据埋点并上报。
- 数据处理层，负责数据的存储与计算。
- 数据展示层，负责数据的图形化展示



### 日志

仅有 metrics 与 tracing，很难理解系统是如何走到当前状态的。
这正是 logging 发挥作用的地方。Logs 是应用在某个时间段内发生的离散事件的不可变记录。
它们帮助揭示微服务架构中每个组件表现出的突发且不可预测的行为。
Logs 也可以看作是一条带时间戳、标明事件发生时刻、并附带提供上下文的负载（payload）的文本记录。

日志有三类：纯文本、结构化与二进制。
虽然纯文本格式的日志很常见，但最好让日志结构化、带上上下文数据，并且更易获取。
经验法则是：日志应当既能让人阅读，也能被机器解析。
当系统出问题时，日志是首先需要查看的地方。

由于云原生应用的每个组件都会输出日志，日志应当被集中化，以便你充分发挥其价值。
[Elasticsearch](https://www.elastic.co/)、[Fluentd](https://www.fluentd.org/) 与 [Kibana](https://www.elastic.co/kibana)
（二者同属 EFK 技术栈，支持全文与结构化检索）常被用于日志集中化。

## OpenTracing

或许从"OpenTracing 不是什么"说起会更简单。

- OpenTracing 不是一次下载或一个程序。
- 分布式追踪要求软件开发者为应用代码、或应用中使用的框架添加 instrumentation（埋点）。
- OpenTracing 并非标准。Cloud Native Computing Foundation（CNCF）并非官方标准机构。
  OpenTracing API 项目正致力于为分布式追踪创建更加标准化的 API 与 instrumentation。

OpenTracing 由一个 API 规范、已实现该规范的框架与库，以及项目文档共同组成。
OpenTracing 让开发者能够用不绑定任何特定产品或厂商的 API，为应用代码添加 instrumentation。

## OpenTracing 数据模型

在 OpenTracing 中，Traces 是由其 Spans 隐式定义的。
具体来说，一条 Trace 可以看作是一张由 Spans 构成的有向无环图（DAG），Span 之间的边称为 References。

例如，下面是一个由 8 个 Span 组成的 Trace 示例：

```
Causal relationships between Spans in a single Trace

        [Span A]  ←←←(the root span)
            |
     +------+------+
     |             |
 [Span B]      [Span C] ←←←(Span C is a `ChildOf` Span A)
     |             |
 [Span D]      +---+-------+
               |           |
           [Span E]    [Span F] >>> [Span G] >>> [Span H]
                                       ↑
                                       ↑
                                       ↑
                         (Span G `FollowsFrom` Span F)
```

每个 Span 封装了如下状态：

- 一个操作名（operation name）
- 起始时间戳
- 结束时间戳
- 零个或多个 key:value 形式的 Span Tags。键必须是字符串。值可以是字符串、布尔或数值类型。
- 零个或多个 Span Logs，每一个本身都是一个与时间戳配对的 key:value 映射。
  键必须是字符串，但值可以是任意类型。并非所有 OpenTracing 实现都必须支持每种值类型。
- 一个 SpanContext（见下文）
- 对零个或多个存在因果关联 Span 的引用（经由那些相关 Span 的 SpanContext）

每个 SpanContext 封装了如下状态：

- 任何 OpenTracing 实现相关的状态（例如 trace id 与 span id），用于在跨进程边界时引用某个独立的 Span
- Baggage Items，即那些跨越进程边界的 key:value 键值对


## OpenTelemetry

OpenTelemetry 是一个 `Observability`（可观测性）框架与工具集，旨在创建并管理诸如 `traces`、`metrics` 与 `logs` 之类的_遥测数据_。
关键在于，OpenTelemetry 与厂商及工具无关（vendor- and tool-agnostic），这意味着它可与种类广泛的 Observability 后端配合使用，
包括 [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md)、[Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md) 等开源工具，以及商业产品。
OpenTelemetry 是 Cloud Native Computing Foundation（CNCF）的项目。

OpenTelemetry 不是像 Jaeger、Prometheus 或商业厂商那样的 Observability 后端。
OpenTelemetry 聚焦于遥测数据的生成、采集、管理与导出。
该数据的存储与可视化被刻意留给其它工具完成。

详见 [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md)（API/SDK、Collector、OTLP、signals、instrumentation），
以及它与 OpenTracing 和 Jaeger/Zipkin/SkyWalking 等追踪后端的关系。




## Links

- [Distributed Systems](/docs/CS/Distributed/Distributed.md)
- [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md)
- [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md)
- [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md)
- [SkyWalking](/docs/CS/Distributed/Tracing/SkyWalking.md)
- [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md)
- [Grafana](/docs/CS/Distributed/Tracing/Grafana.md)
- [Micrometer](/docs/CS/log/Micrometer.md)


## References

1. [OpenTelemetry](https://opentelemetry.io/)
2. [OpenTracing specification](https://opentracing.io/specification/)
