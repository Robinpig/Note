## Introduction

可观测性（Observability）有三大支柱：**Metrics**（指标）、**Tracing**（追踪）、**Logging**（日志）。单独看每一类或用不同工具各管一类，都不等于可观测性；只有把三者关联进同一视图，才能在未知故障发生时「不重新发版就能定位」。本目录聚焦分布式追踪及其周边：从概念与数据模型，到 OpenTracing → OpenTelemetry 的标准演进，再到具体后端。

特别要分清两层：**生成与采集层**由 OpenTelemetry 统一（vendor-agnostic 的 API/SDK/Collector/OTLP），**存储与展示层**才交给 Jaeger、Zipkin、Prometheus、Grafana 等后端——OTel 不替代它们，只把遥测数据的产生标准化。

## 成员导航

- [Tracing](/docs/CS/Distributed/Tracing/Tracing.md) — 可观测性三支柱、trace/span 数据模型、OpenTracing 规范。
- [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md) — vendor-agnostic 的遥测框架（API/SDK、Collector、OTLP、信号关联、instrumentation）。
- [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md) — CNCF 分布式追踪后端，兼容 OpenTelemetry。
- [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md) — 起源于 Twitter 的轻量追踪系统，Dapper 思路的早期实现。
- [SkyWalking](/docs/CS/Distributed/Tracing/SkyWalking.md) — 国产 APM 平台，涵盖追踪、拓扑与告警。
- [Grafana](/docs/CS/Distributed/Tracing/Grafana.md) — 统一可视化层，可对接 Prometheus、Tempo 等数据源。
- [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md) — 指标（Metrics）支柱的事实标准；[部署实践](/docs/CS/Distributed/Tracing/Prometheus/Deploy.md)单独成篇。

## 关系轴

一条分布式请求流过多个服务，Tracing 用 DAG 化的 Span 还原其因果路径，定位瓶颈与失败；Metrics 用聚合数值判断「是否正常」；Logging 用离散事件解释「为何到这个状态」。三者通过 trace id 关联。标准侧，OpenTracing 已停止演进、并入 OpenTelemetry——新项目直接以 OTel 为起点，再选后端。

## Links

- [Distributed Systems](/docs/CS/Distributed/Distributed.md) — 追踪在「分布式请求、故障定位」全局中的位置
- [Micrometer](/docs/CS/log/Micrometer.md) — JVM 侧的指标埋点门面
