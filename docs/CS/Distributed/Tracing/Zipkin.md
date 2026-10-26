## Introduction

[Zipkin](https://zipkin.io/) 是 **OpenZipkin** 维护的分布式追踪系统，由 Twitter 于 2012 年开源，直接受 Google [Dapper](/docs/CS/Distributed/Tracing/Tracing.md) 论文启发，是 Dapper 思路最早的开源实现之一。它帮助收集排查服务架构中延迟问题所需的时序数据，功能涵盖这些追踪数据的**收集、存储、检索与可视化**。

Zipkin 的设计哲学是「轻量、低运维开销、低侵入」：Instrumentation（埋点）对业务代码透明，trace instrumentation 异步上报 span 以免追踪系统自身的延迟或故障拖慢用户代码，生产环境可安全使用。这是它与 [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md) 在架构取向上的核心差异——Zipkin 以**单进程**承载 collector、storage、query、UI 全部组件，部署简单，但 collector 与 query 不能独立水平扩展。

下面这张来自 Zipkin 官网的图描述了这一流程：

<div style="text-align: center;">

![Fig.1. Architecture](https://zipkin.io/public/img/architecture-1.png)

</div>

<p style="text-align: center;">
Fig.1. Architecture
</p>

## Architecture

一条请求的追踪数据从被埋点的应用出发，经过 Reporter → Collector → Storage → Query → Web UI 这五个逻辑环节。完整的组件划分、数据流图与「带内传播 ID」机制见 [Zipkin Architecture](/docs/CS/Distributed/Tracing/Zipkin/Architecture.md)。

| 逻辑组件 | 职责 |
| --- | --- |
| **Tracer / Instrumentation** | 运行在应用内，记录操作时间与元数据；对常见库做埋点，对用户透明 |
| **Reporter** | 应用内负责把 span 发给 Zipkin 的组件（HTTP / Kafka / RabbitMQ / Scribe 等传输） |
| **Collector** | 守护进程，接收 span、校验、建立索引并交由存储持久化 |
| **Storage** | 可插拔存储抽象，原生支持内存、Cassandra、Elasticsearch、MySQL |
| **Query Service** | 提供 REST API 检索 trace，主要消费者是 Web UI |
| **Web UI** | 单页应用，检索并以时间轴 / 依赖图可视化 trace |

## Data Model

Zipkin 使用 **v2 数据模型**：一条 Trace 由共享同一 `traceId` 的若干 Span 构成树状结构，Span 之间靠 `parentId` 串联。每个 Span 携带 `id`、`traceId`、`parentId`、`name`、`timestamp`（epoch 微秒）、`duration`（微秒）、`kind`（CLIENT/SERVER/PRODUCER/CONSUMER）、`annotations`、`tags`、`localEndpoint` / `remoteEndpoint` 等字段。RPC 场景下客户端（`cs`/`cr`）与服务端（`sr`/`ss`）共享同一 spanId，由 collector 合并成完整记录。

字段级细节、注解语义（`cs`/`sr`/`ss`/`cr`、`ws`/`wr`）、`kind` 与 `shared` 标志见 [Zipkin Data Model](/docs/CS/Distributed/Tracing/Zipkin/Data_Model.md)。

## Transport

被埋点的库发出的 span 必须经某种传输送达 Zipkin collector。主流方式有 **HTTP**（`POST /api/v2/spans`）、**Kafka**、**RabbitMQ** 与 **Scribe**；应用内的 **Reporter** 负责编码并发送，其中 `AsyncReporter` 通过有界队列缓冲、独立 flush 线程发送，并在队列满或发送失败时丢 span 并计入 metrics。

Java 侧最主要的 instrumentation 库是 **Brave**；Spring 生态历史上是 **Sleuth**（已 EOL，由 Micrometer Tracing 取代）。传输层、Reporter / Sender / AsyncReporter 实现与多语言客户端见 [Zipkin Transport](/docs/CS/Distributed/Tracing/Zipkin/Transport.md)。

## Collector and Storage

Collector 守护进程收到 span 后，先校验、建立索引，再交给 StorageComponent 持久化。存储是可插拔的：

- **内存**：默认，零配置，重启即丢，仅适合演示。
- **Cassandra**：Twitter 内部的原始选型，扩展性好、schema 灵活。
- **Elasticsearch**：检索能力强、生态成熟，是生产常用选择。
- **MySQL**：v1 组件，schema 简单易懂但不为性能设计，数据量大后查询会退化到秒级。

`SEARCH_ENABLED=false` 可关闭检索索引以降低存储成本 / 提升写入吞吐，代价是只能按 traceId 点查。完整后端对比、依赖聚合与 `StorageComponent` 见 [Zipkin Collector and Storage](/docs/CS/Distributed/Tracing/Zipkin/Collector_and_Storage.md)。

## Query Service and UI

数据落盘并建立索引后，**Query Service** 提供一组 REST API（基址 `localhost:9411/api/v2`）：`POST /spans` 接收、`GET /traces` 检索、`GET /trace/{traceId}` 点查、`GET /services`、`GET /spans`、`GET /dependencies` 等，主要消费者是 Web UI。

Web UI 提供 trace 列表检索、单条 trace 的**时间轴瀑布图**、以及汇总「各应用间被追踪请求量」的**依赖图**，可帮助识别错误路径或过时服务的调用。API 端点清单与 UI 能力见 [Zipkin Query and UI](/docs/CS/Distributed/Tracing/Zipkin/Query_and_UI.md)。

## Relationship to OpenTelemetry

Zipkin 与 [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md) 的分工是「生成 vs 后端」：OTel SDK 负责埋点、上下文传播（默认 W3C Trace Context）与通过 OTLP 上报；Zipkin 作为后端接收并存储这些 span。OTel Collector 内置 **zipkin exporter**，可直接把 OTLP 转成 Zipkin v2 格式写入；需要让 OTel 与既有 Zipkin 服务共存时，可在 OTel 侧启用 **B3 propagator**（多 / 单 header）来对齐 Zipkin 的上下文传播格式。新版项目通常以 OTel 为起点、Zipkin 作后端，而不再引入 Zipkin 专有客户端。

## Quickstart

运行一个全功能的 Zipkin 后端只需一条命令（内存存储，UI 端口 9411）：

```bash
docker run -d -p 9411:9411 openzipkin/zipkin
# UI: http://localhost:9411
```

切换到持久化存储通过环境变量完成，例如 `STORAGE_TYPE=elasticsearch` 并配套 `ES_HOSTS`；从源码运行需 **JDK 17+**。版本基线：**3.6.x（3.6.1，2026-04）**，镜像发布于 Docker Hub `openzipkin/zipkin` 与 GHCR `ghcr.io/openzipkin/zipkin`，另提供 `zipkin-slim` 精简镜像与 Helm Chart（`helm repo add zipkin https://zipkin.io/zipkin-helm`）。运维细节见 [Zipkin Collector and Storage](/docs/CS/Distributed/Tracing/Zipkin/Collector_and_Storage.md)。

## Links

- [Tracing](/docs/CS/Distributed/Tracing/Tracing.md) — 可观测性三支柱、trace/span 数据模型
- [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md) — CNCF 追踪后端，Zipkin 的主要对照
- [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md) — vendor-agnostic 遥测框架，可桥接 Zipkin
- [SkyWalking](/docs/CS/Distributed/Tracing/SkyWalking.md) — 国产 APM 平台
- [Spring Cloud Sleuth](/docs/CS/Framework/Spring_Cloud/Sleuth.md) — Spring 生态历史 Zipkin 客户端（已 EOL）
- [Micrometer](/docs/CS/log/Micrometer.md) — JVM 侧埋点门面，Sleuth 的继任者

## References

1. [Zipkin](https://zipkin.io/) — 官方网站
2. [Zipkin API v2](https://zipkin.io/zipkin-api/#/default/post_spans) — v2 REST API 规范
3. [Instrumenting a library](https://zipkin.io/pages/instrumenting) — 埋点与 B3 传播官方文档
4. [B3 Propagation](https://github.com/openzipkin/b3-propagation) — B3 传播格式规范
5. [Zipkin GitHub](https://github.com/openzipkin/zipkin) — 源码与发布
