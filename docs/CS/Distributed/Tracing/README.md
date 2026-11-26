## Introduction

可观测性（Observability）有三大支柱：**Metrics**（指标）、**Tracing**（追踪）、**Logging**（日志）。单独看每一类或用不同工具各管一类，都不等于可观测性；只有把三者关联进同一视图，才能在未知故障发生时「不重新发版就能定位」。本目录聚焦分布式追踪及其周边：从概念与数据模型，到 OpenTracing → OpenTelemetry 的标准演进，再到具体后端。

特别要分清三层：**生成与采集层**由 OpenTelemetry 统一（vendor-agnostic 的 API/SDK/Collector/OTLP），**传输与主机侧采集**交给 [Grafana Alloy](/docs/CS/Distributed/Tracing/Alloy.md) 这类 agent，**存储与展示层**才交给 Jaeger、Zipkin、Prometheus、Loki、Tempo、Grafana 等后端——OTel 不替代它们，只把遥测数据的产生标准化。

其中 Loki / Grafana / Tempo / Mimir 组成 Grafana Labs 的 **LGTM 栈**，是「一套后端覆盖三支柱」的代表方案：[Grafana](/docs/CS/Distributed/Tracing/Grafana.md) 是把三者关联进同一视图的枢纽，也是本目录里唯一起「串联」作用的页面。

## Membership Navigation

### 概念与标准

- [Tracing](/docs/CS/Distributed/Tracing/Tracing.md) — 可观测性三支柱、trace/span 数据模型、OpenTracing 规范。
- [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md) — vendor-agnostic 的遥测框架（API/SDK、Collector、OTLP、信号关联、instrumentation）。

### 追踪后端

- [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md) — CNCF 分布式追踪后端，兼容 OpenTelemetry。
- [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md) — 起源于 Twitter 的轻量追踪系统，Dapper 思路的早期实现；架构 / 数据模型 / 传输(B3) / 存储 / 查询已拆为子分册。
- [SkyWalking](/docs/CS/Distributed/Tracing/SkyWalking.md) — 国产 APM 平台，覆盖追踪/拓扑/告警；数据模型 / 传输(sw8) / OAP 后端与存储 / 查询与 UI 拆为子分册，架构并入枢纽页，并附实现机理分册（两级采样、拓扑推导、BanyanDB 存储模型）。
- [Tempo](/docs/CS/Distributed/Tracing/Tempo.md) — v3.1.1 源码基线，覆盖 Kafka 写入、vParquet5、块生命周期与 TraceQL 查询。

### 指标与日志

- [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md) — 指标（Metrics）支柱的事实标准；原理与机制以 **v3.16.0** 源码为基线，[部署实践](/docs/CS/Distributed/Tracing/Prometheus/Deploy.md)单独成篇。
- [Loki](/docs/CS/Distributed/Tracing/Loki.md) — 日志聚合系统，LogQL；以 **v3.7.10** 源码为基线，[写入](/docs/CS/Distributed/Tracing/Loki/Write_Path.md)、[存储与 TSDB](/docs/CS/Distributed/Tracing/Loki/Storage.md)、[查询](/docs/CS/Distributed/Tracing/Loki/Query_Path.md)、[一致性与生命周期](/docs/CS/Distributed/Tracing/Loki/Consistency.md)拆为源码级分册。
- [Pinpoint](/docs/CS/Distributed/Tracing/Pinpoint.md) — NAVER 开源全栈 APM，字节码插桩 + HBase/Pinot 存储，ServerMap 自动拓扑；**非 OTel 后端**。
- [CAT](/docs/CS/Distributed/Tracing/CAT.md) — 美团点评开源实时监控，Message Tree 模型 + 全量指标/采样链路，cat-client/consumer/home 三段。
- [Tempo](/docs/CS/Distributed/Tracing/Tempo.md) — Grafana 的追踪后端，Parquet 块 + 对象存储，TraceQL。
- [SigNoz](/docs/CS/Distributed/Tracing/SigNoz.md) — OpenTelemetry-native 全栈 APM，单一 ClickHouse 库覆盖 traces/metrics/logs。
- [Uptrace](/docs/CS/Distributed/Tracing/Uptrace.md) — 极简 OpenTelemetry-native APM（单一 Go 二进制 + ClickHouse + PostgreSQL），AGPL-3.0。
- [Elastic APM](/docs/CS/Distributed/Tracing/ElasticAPM.md) — Elastic Observability 的 APM 能力，原生说 OpenTelemetry，落 Elasticsearch（LogsDB + TSDS）。

### 指标与日志

- [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md) — 指标（Metrics）支柱的事实标准；[部署实践](/docs/CS/Distributed/Tracing/Prometheus/Deploy.md)单独成篇。
- [Mimir](/docs/CS/Distributed/Tracing/Mimir.md) — Grafana 的 Prometheus 长期存储（LGTM 的 M），对象存储里的 TSDB block。
- [Loki](/docs/CS/Distributed/Tracing/Loki.md) — 只索引标签的日志聚合系统，LogQL。

### 采集层

- [Grafana Alloy](/docs/CS/Distributed/Tracing/Alloy.md) — 统一的遥测采集器，一个进程覆盖 metrics/logs/traces/profiles。
- [Promtail](/docs/CS/Distributed/Tracing/Promtail.md) — Loki 的日志采集 agent，**已于 2026-03-02 EOL**，仅作存量对照与迁移参考。

### 可视化

- [Grafana](/docs/CS/Distributed/Tracing/Grafana.md) — 统一可视化层，LGTM 栈的枢纽；数据源、仪表盘、告警、provisioning。

## Relationship Axes

一条分布式请求流过多个服务，Tracing 用 DAG 化的 Span 还原其因果路径，定位瓶颈与失败；Metrics 用聚合数值判断「是否正常」；Logging 用离散事件解释「为何到这个状态」。三者通过 trace id 关联——关联动作实际发生在 Grafana 里：指标发现异常 → 下钻到 [Tempo](/docs/CS/Distributed/Tracing/Tempo.md) 的 trace → 用 trace id 跳到 [Loki](/docs/CS/Distributed/Tracing/Loki.md) 的日志原文。

标准侧，OpenTracing 已停止演进、并入 OpenTelemetry——新项目直接以 OTel 为起点，再选后端。采集侧同理，[Promtail](/docs/CS/Distributed/Tracing/Promtail.md) 已 EOL，新部署应直接上 [Alloy](/docs/CS/Distributed/Tracing/Alloy.md)。

## Links

- [Distributed Systems](/docs/CS/Distributed/Distributed.md) — 追踪在「分布式请求、故障定位」全局中的位置
- [Micrometer](/docs/CS/log/Micrometer.md) — JVM 侧的指标埋点门面
