## Introduction

[Grafana Tempo](https://grafana.com/oss/tempo/) 是 Grafana Labs 开源的**分布式追踪后端**（distributed tracing backend），主打「海量 trace、极低成本」。它是 LGTM 栈中的 **T**（Traces），通常与 [Loki](/docs/CS/Distributed/Tracing/Loki.md)（日志）、Mimir（指标）、[Grafana](/docs/CS/Distributed/Tracing/Grafana.md)（可视化）一起构成完整方案。

Tempo 的设计哲学很直接：**trace 是很少被查、但必须被留一阵子的数据**。所以它放弃了传统追踪后端（Jaeger on Elasticsearch、Zipkin on Cassandra）那种「为 trace 建昂贵索引」的路线，改为——接收 OTLP/Jaeger/Zipkin 协议的数据，打包成 **Parquet 块**直接写对象存储，查询时用 **TraceQL** 扫。

代价是「按 trace id 查秒回，按条件搜索慢一些」；收益是存储成本量级下降，且不需要维护一个庞大的索引集群。

> [!NOTE]
> 版本事实截至 2026-10。Tempo **3.1.0** 于 2026-09-29/30 发布，是当前主线；**3.0.0** 于 2026-05-28 发布，带来了默认启用的全新架构。官方 recommended versions 页面当前标注 3.0.x 为 Recommended，2.10.x（2.x 最后一个 minor）为 Maintained，2.8 及更早已 EOL。支持策略：每个 minor 自发布起获 9 个月补丁，major 的最后一个 minor 获 15 个月。

## 与 Jaeger / Zipkin 的分工

| 维度 | Tempo | [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md) | [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md) |
| --- | --- | --- | --- |
| 存储 | 对象存储 + Parquet 块，无外部数据库 | Elasticsearch / OpenSearch / Cassandra / ClickHouse | [Cassandra / Elasticsearch / MySQL](/docs/CS/Distributed/Tracing/Zipkin/Collector_and_Storage.md) |
| 索引 | 轻索引（按 trace id 定位） | 依赖后端的索引能力 | 依赖后端的索引能力 |
| 查询语言 | TraceQL | 自有 UI + ES 查询 | 自有 UI |
| 成本 | 低（对象存储为主） | 中到高（取决于后端） | 中 |
| 运维面 | 3.x 起分布式模式需要 Kafka | 取决于存储后端 | 取决于存储后端 |
| UI | 主要依托 Grafana | 自带成熟 UI | 自带 UI |

Tempo 不自带重量级 UI，它的定位是「Grafana 的一个数据源」——这既是它的优势（与 metrics/logs 天然联动），也是选择它时必须接受的约束（可视化层绑定 Grafana）。

## Data Model

- **Span**：一次操作，含操作名、起止时间、attributes、status、parent span id。
- **Trace**：共享同一 trace id 的 span 集合，形成一棵（或 DAG）调用树。
- **Block**：Tempo 把一段时间内收到的 spans 聚合成 Parquet 块写入对象存储。当前默认写 **vParquet5**，仍可读 vParquet4 / vParquet3，无需数据迁移。
- **Tenant**：通过 `X-Scope-OrgID` 头做多租户隔离。

Tempo 与 [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md) 的分工清晰：OTel 负责**产生与采集** span，Tempo 负责**存与查**。Tempo 直接接收 OTLP，也兼容 Jaeger 与 Zipkin 协议，因此可以嵌进已有的 OTel Collector 管道。

## Architecture

### 3.0 之前：ingester 为中心

```
Distributor ──▶ Ingester(×3, RF3) ──flush──▶ 对象存储（Parquet blocks）
                      │                            ▲
                      └──▶ 近期 trace 查询           │
                                          Compactor（合并/保留/维护 blocklist）
                      Metrics-generator ──▶ 本地 blocks（第二份数据）
```

这套架构有三个硬伤，也是重构的动因：

1. **RF3 强制**：ingester 需要三副本保证持久性，加上 metrics-generator 的第二份数据，实际存储量是原始 trace 的 **3 到 3.5 倍**。
2. **读写路径耦合**：同一个组件既管写又管读，一个坏负载能同时拖垮两边。真实事故包括 Mimir 查询压垮摄取、慢查询饿死快查询、超大 trace 属性 OOM querier。
3. **TraceQL metrics 可用性受限**：指标数据绑在单个 generator 上，generator 挂了它手上那批数据就暂时不可用。

### 3.0 起：读写分离 + Kafka

```
                       ┌──────────── 写路径 ────────────┐
Distributor ──▶ Kafka（持久化缓冲，唯一副本）──▶ Block-builder ──▶ 对象存储（Parquet）
                    │                                                    ▲
                    ├──▶ Live-store（服务「刚写入」的近期 trace 查询）      │
                    └──▶ Metrics-generator（消费同一 topic）               │
                                                                          │
                       Backend Scheduler + Backend Worker ────────────────┘
                       （压缩、保留、blocklist 维护、redaction 作业）
```

关键变化：

- **读写路径彻底分离**。ingester 被 block-builder（写侧）与 live-store（读侧）取代，compactor 被 backend scheduler/worker 取代。坏负载不再跨路径传染。
- **Kafka 成为持久化层**，取代 ingester 复制，只存一份数据，直接降低对象存储成本。
- **新 trace 立即可查**：live-store 直接消费 Kafka 流，服务尚未成块的近期 trace，不再依赖 ingester 内存路径。
- **TraceQL metrics 转为 GA**，且不再依赖 metrics-generator 组件，默认启用。
- **单体模式（monolithic）不需要 Kafka**，仍是小规模部署的最简选择。

### Components

| 组件 | 职责 |
| --- | --- |
| Distributor | 接收 OTLP / Jaeger / Zipkin 数据，校验后写入 Kafka |
| Block-builder | 消费 Kafka，把 spans 写成 Parquet 块到对象存储 |
| Live-store | 消费同一 Kafka 流，服务「近期 trace」查询 |
| Backend Scheduler / Worker | 协调压缩、保留、blocklist 维护与 redaction 作业 |
| Metrics-generator | 从 span 派生 RED 指标（Rate/Error/Duration）与服务拓扑图 |
| Query Frontend | 拆分、缓存、排队查询 |
| Querier | 扫描对象存储中的块执行 TraceQL |

## TraceQL

TraceQL 是 Tempo 的查询语言，语法向 PromQL/LogQL 靠拢：`{}` 内是选择器，`|` 后接管道。

```traceql
# 基础筛选
{ resource.service.name = "checkout" && status = error }

# 按耗时筛选
{ resource.service.name = "api" && duration > 500ms }

# 嵌套结构查询
{ span.http.method = "POST" && span.http.status_code >= 500 }

# 结构化：按父子关系筛选（A 调用 B）
{ resource.service.name = "frontend" } >> { resource.service.name = "cart" }
```

**TraceQL metrics** 让你直接从 trace 数据算时间序列，不必先把指标导出到 Mimir：

```traceql
# 各服务的 span 速率
{} | rate() by (resource.service.name)

# p95 耗时（毫秒）
({} | quantile_over_time(duration, 0.95)) * 1000

# 错误率：3.1 起支持两个 metrics 查询做算术运算
({ status = error } | rate() by (resource.service.name))
  / ({} | rate() by (resource.service.name))
```

3.1 的算术规则：每个子查询要各自加括号，标量与标量可出现在任一侧，只有标签集完全一致的序列才会合并，末尾的 `with(extrapolate=true)` 提示对两侧子查询同时生效。

## 3.1 的重要更新

- **vParquet5 成为默认写入格式**，继续读 vParquet4 / vParquet3，无需迁移。注意：配置为写 vParquet3 时 Tempo 会拒绝启动。
- **span-only fetch 默认开启**（vParquet5 块）：不需要完整 trace 结构的查询只处理单个 span，实测约快一倍。
- **按查询做 trace redaction**：3.0 引入的脱敏只能用 trace id 枚举，3.1 起可直接提交 TraceQL 选择器批量脱敏，支持时间窗口，用于清除误入 span 属性的邮箱、token、账号等敏感数据。
- **Kafka 连接能力补齐**：TLS 与 mTLS、SASL 机制扩展到 SCRAM-SHA-256/512、OAUTHBEARER、AWS_MSK_IAM；rack-aware fetching（KIP-392，按 `client_rack` 从本可用区副本读取以省跨区流量费）；`producer_compression` 可选 none/gzip/snappy/lz4/zstd，其中 gzip 让 Azure Event Hubs 成为可用的 Kafka 后端。
- **服务图可诊断性**：过期边增加 `unmatched_span_kind` 标签，用于分辨「连接本就不存在」和「对端 span 没到齐」；同时接受 OTel 语义约定 v1.30.0 更名后的 `db.system.name`（两者并存时 `db.system` 优先）。
- **Redis 缓存重写**：Redis Cluster 成为默认，Sentinel 支持移除，配置键与 TLS 设置变更。
- **实验特性**：span pruning（裁剪 trace-by-ID 响应体）、trace diff 与摘要。

## Metrics-generator

metrics-generator 是可选组件，从摄入的 span 派生两类派生指标：

- **Span metrics**：RED 三件套（rate / error / duration），按服务、操作等维度聚合。
- **Service graph**：服务间调用拓扑的边与节点，用于在 Grafana 里画服务依赖图。

它是「用 trace 数据反哺 metrics」的通道，配合 Grafana 的服务图面板可以直观看到系统拓扑。3.1 通过复用池化 label buffer 把稳态 service-graph 的每操作分配降到零。

## Operations Notes

- **采样策略比后端选型更影响成本**。头部采样在 SDK 侧决定，尾部采样在 Collector 侧决定——后者能保留全部错误与慢 trace，性价比更高。
- **Kafka 只影响分布式模式**。小规模用 monolithic 模式可以完全绕开 Kafka；一旦走微服务模式，Kafka 就是必须纳入运维面的第二个依赖。
- **升级前必读 upgrade guide**。3.1 包含破坏性配置变更与新默认值，涉及 Redis 缓存、vParquet3 写入、自定义 query-frontend 配置的安装需要提前调整。
- **窗口化脱敏的版本一致性**：scheduler 与 worker 版本不一致时不要提交带时间窗口的脱敏作业——旧 worker 会忽略时间窗口，把块内所有匹配的 trace 全部脱敏。
- 与日志侧的关联：日志里带上 trace id（作为 Loki 的 structured metadata），就能从 [Loki](/docs/CS/Distributed/Tracing/Loki.md) 的日志行一键跳到 Tempo 的 trace，这是三支柱落地最常用的一个动作。

## Links

- [Tracing](/docs/CS/Distributed/Tracing/Tracing.md)
- [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md)
- [Loki](/docs/CS/Distributed/Tracing/Loki.md)
- [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md)
- [Zipkin](/docs/CS/Distributed/Tracing/Zipkin.md)
- [Zipkin Query and UI](/docs/CS/Distributed/Tracing/Zipkin/Query_and_UI.md) — 检索 API 与依赖图

## References

1. [Grafana Tempo documentation](https://grafana.com/docs/tempo/latest/)
2. [Tempo recommended versions](https://grafana.com/docs/tempo/latest/set-up-for-tracing/setup-tempo/recommended-versions/)
3. [Tempo 3.0 release blog](https://grafana.com/blog/tempo-3-0-release-all-the-latest-features/)
4. [Tempo 3.1 release blog](https://grafana.com/blog/tempo-3-1-release-all-the-latest-features/)
5. [TraceQL documentation](https://grafana.com/docs/tempo/latest/traceql/)
6. [grafana/tempo Releases](https://github.com/grafana/tempo/releases)
