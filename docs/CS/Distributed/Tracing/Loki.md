## Introduction

[Grafana Loki](https://grafana.com/oss/loki/) 是一个水平可扩展、高可用、多租户的**日志聚合系统**（log aggregation system），由 Grafana Labs 开源，设计灵感来自 [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md)。它是 LGTM 栈中的 **L**（Logs），与 [Grafana](/docs/CS/Distributed/Tracing/Grafana.md)、[Tempo](/docs/CS/Distributed/Tracing/Tempo.md)、Mimir 分别对应可视化、追踪与指标。

Loki 的核心取舍一句话可以概括：**只索引标签，不索引日志内容**。

传统日志系统（Elasticsearch 为代表）会对日志全文建立倒排索引，写入昂贵、存储膨胀；Loki 反其道而行——日志正文被压缩成 chunk 直接扔进对象存储（S3/GCS/Azure Blob），索引里只保留一组 Prometheus 风格的标签。代价是全文检索慢，收益是索引极小、成本极低、运维极简。

> [!NOTE]
> 版本事实截至 2026-10：Loki 当前主线为 **3.7.x**（最新 3.7.9，2026-10-20）。3.8.0 尚未打 tag，CHANGELOG 中已列出移除 BoltDB / Cassandra / DynamoDB / BigTable 等旧存储后端的条目，属「即将发生」。下文涉及新架构的部分 Grafana Labs 已在 GrafanaCON 2026 公布，正处于向 Loki 4.0 演进的过程中，落地状态请以官方 release notes 为准。

## Design: 用索引换成本

| 维度 | Elasticsearch / EFK | Loki |
| --- | --- | --- |
| 索引对象 | 日志**全文**（分词倒排） | 仅**标签**（label set） |
| 写入成本 | 高（分词、建索引） | 低（压缩后直接写对象存储） |
| 存储占用 | 索引常与数据同量级 | 索引比数据小两三个数量级 |
| 全文检索 | 快，开箱即用 | 慢，需要在标签圈定的流内做暴力扫描 |
| 高基数标签 | 无所谓 | **致命**，直接决定成本 |
| 查询语言 | DSL / Lucene | LogQL |
| 与指标的关联 | 需额外打通 | 天然同构（都是 Prometheus 标签模型） |

Loki 的性价比来自「小索引 + 高压缩 chunk」。但这个取舍有一个明确的反面：**大海捞针式查询**（needle in the haystack，例如「在所有日志里搜某个 user_id」）在 Loki 上很慢——因为没有任何索引能直接指向它。Loki 3.x 用 bloom filter 缓解，GrafanaCON 2026 又宣布通过收购 Logline 引入定向二级索引（targeted secondary index）来解决，后者先在 Grafana Cloud 私有预览，开源侧随后。

## Data Model

Loki 的数据模型几乎是 Prometheus 标签模型的翻版：

- **Stream（流）**：一组唯一的标签集合（`{app="api", env="prod", namespace="default"}`）标识一条日志流。标签组合的数量就是流的数量，**标签基数直接决定索引大小和查询性能**。
- **Chunk（块）**：流在一段时间内累积的日志条目，压缩（默认 snappy）后写入对象存储。ingester 在内存中攒 chunk，满足条件（大小/空闲时长/最大年龄）后 flush。
- **Entry（条目）**：单条日志，含时间戳与正文。
- **Structured metadata（结构化元数据）**：3.x 起支持给单条日志行附加键值结构（如 `trace_id`、`user_id`），它比把值塞进标签便宜得多——不产生新的流，但可被 LogQL 过滤。这是「想按某个高基数字段查日志」时的正确做法，而不是把它做成标签。

一条流在 Loki 里的形态：

```
{app="api", env="prod"}  ──▶  chunk(ts 10:00-10:15)  ──▶  对象存储
                          ──▶  chunk(ts 10:15-10:30)  ──▶  对象存储
```

标签选择是本系统最重要的设计决策，几条实用经验：

- 标签只放**低基数、常用于筛选**的维度：`namespace`、`app`、`env`、`cluster`、`level`、主机名。
- 绝不放高基数或无限域的值：`user_id`、`request_id`、`trace_id`、`pod_uid`、URL 路径。这些应走 structured metadata 或日志正文 + 过滤器。
- 想按 trace_id 跳到链路？用 `trace_id` 作为 structured metadata 或直接在日志里输出，配合 [Tempo](/docs/CS/Distributed/Tracing/Tempo.md) 的数据源关联，而不是把它做成标签。

## Architecture

### Components

Loki 3.x 在分布式模式下由以下组件构成（单体模式全部塞进一个进程）：

| 组件 | 职责 |
| --- | --- |
| Distributor | 接收写请求，校验、规范化标签、按一致性哈希分发给 ingester |
| Ingester | 在内存中按流攒日志、构建 chunk，flush 到对象存储；同时服务近期数据的查询 |
| Querier | 执行 LogQL：向 ingester 查内存中的近期数据，向对象存储查历史数据 |
| Query Frontend | 查询入口，做拆分（split by interval）、缓存、排队，把大查询切成小查询 |
| Query Scheduler | 维护每租户的查询队列，保证租户间公平 |
| Index Gateway | 为 TSDB 索引提供查询服务，避免每个 querier 都去扫索引桶 |
| Compactor | 合并索引文件、执行保留策略（retention）与删除请求 |
| Ruler | 评估告警规则与 recording rule（与 Prometheus 的 rule 概念一致） |
| Pattern Ingester | 为 `pattern` 过滤器维护日志行的模式（把变量部分抽象成 `<_>`） |
| Bloom Planner / Builder / Gateway | 构建与查询 bloom filter，用于在扫描前快速排除不含目标字符串的 chunk |

### Write and Read Paths

```
                    写路径
  Promtail / Alloy / OTel Collector
                │  POST /loki/api/v1/push
                ▼
          Distributor ──(hash by label set)──▶ Ingester
                                                  │ flush
                                                  ▼
                                           Chunks + Index
                                          （对象存储，single store）

                    读路径
  Grafana / LogCLI ──▶ Query Frontend ──▶ Query Scheduler ──▶ Querier
                                                                │
                                    ┌───────────────────────────┴──────────────┐
                                    ▼                                          ▼
                             Ingester（近期、未 flush）               Index Gateway + 对象存储（历史）
```

### Deployment Modes

| 模式 | 适用规模 | 说明 |
| --- | --- | --- |
| Monolithic（`-target=all`） | 评估 / 小规模（约 20GB/天以内） | 单进程跑全部组件，本地开发最省事 |
| Simple Scalable（SSD） | **多数生产场景的推荐起点** | 拆成 `write`（distributor+ingester）、`read`（query-frontend+querier）、`backend`（compactor+index-gateway+query-scheduler+ruler）三类 |
| Distributed（microservices） | 大规模，需分组件独立扩缩 | 每个组件独立部署，ingester 建议开启 `zoneAwareReplication` |

## Storage

Loki 采用 **single store**：索引与 chunk 都放同一个对象存储，只需维护一套后端。

- **TSDB（推荐）**：Loki 2.8 引入，查询性能更好、TCO 更低，功能上对标 boltdb-shipper，是目前推荐的索引存储。配置上对应 `store: tsdb` + `schema: v13`。
- **BoltDB（boltdb-shipper，已弃用）**：Loki 2.0 引入，曾用于 2.0.0–2.7.x。3.8 起计划移除。
- **已弃用、即将移除**：Cassandra、BigTable、DynamoDB 作为 chunk/index 后端，以及 gRPC store。

```yaml
loki:
  schemaConfig:
    configs:
      - from: "2024-04-01"
        store: tsdb
        object_store: s3        # 或 gcs / azure / filesystem
        schema: v13
        index:
          prefix: loki_index_
          period: 24h
  ingester:
    chunk_encoding: snappy
  limits_config:
    allow_structured_metadata: true
  storage:
    type: s3
    bucketNames:
      chunks: loki-chunks
      ruler: loki-ruler
```

Schema 配置支持随时间分段演进（`from` 日期），Loki 能透明地跨 schema 查询，这是平滑升级的关键机制。注意 **schema 一旦写入就不可回退**，变更前务必确认。

保留（retention）由 compactor 执行，需要在 `limits_config` 设置 `retention_period` 并在 compactor 侧开启 `retention_enabled`。

## LogQL

LogQL 的语法刻意做成 PromQL 的镜像，分两段：**流选择器**（缩小到哪些流）+ **过滤管道**（在这些流里找什么行）。

```logql
# 流选择器 + 行过滤
{app="api", env="prod"} |= "timeout" != "healthz"

# 正则与结构化解析
{app="nginx"} | regexp `(?P<status>\d{3}) (?P<latency>[\d.]+)` | status >= 500

# JSON 解析后按字段过滤
{app="api"} | json | level="error" | line_format "{{.msg}}"

# 按 structured metadata 过滤（无需做成标签）
{app="api"} | trace_id="4bf92f3577b34da6a3ce929d0e0e4736"

# 模式匹配（变量部分抽象为 <_>）
{app="api"} | pattern `<ip> - - <_> "<method> <path> <_>" <status> <_>`

# 指标查询：把日志流聚合成时间序列
sum by (app) (rate({env="prod"} |= "error" [5m]))

# 分位数
quantile_over_time(0.95, {app="api"} | json | unwrap latency [5m]) by (namespace)
```

常用的聚合函数与 PromQL 同源：`rate`、`count_over_time`、`sum_over_time`、`avg_over_time`、`bytes_over_time`、`topk` 等。unwrap 用于把解析出来的数值字段作为样本值参与计算。

## 新一代架构（GrafanaCON 2026，向 Loki 4.0 演进）

Grafana Labs 在 GrafanaCON 2026 公布了 Loki 的一次重大架构演进，动机是结构化日志与 OpenTelemetry 让日志用法从「简单搜索」转向「高基数分析型查询」，旧设计出现性能瓶颈。

三处主要变化：

1. **Kafka 支撑的摄取层**。旧架构靠 ingester 三副本（RF3）保证持久性，去重依赖文件名一致——但分布式环境下 ingester 时钟漂移会导致去重失效。Grafana 内部实测实际存了 **2.3 倍**副本。新架构把 Kafka 作为持久化缓冲，日志只落一次，有效副本降为 1，直接砍掉 CPU、内存、网络与对象存储的重复开销。
2. **重新设计的查询引擎与调度器**。新的 query planner 把工作分配到各 partition 并并行执行，优化数据局部性，目标是用更少的数据扫描量返回更快的结果。官方口径是**扫描数据量最多减少 20 倍、聚合查询快 10 倍**（来自 Grafana Cloud 自有集群的初步数据）。
3. **列式（columnar）存储格式**。原 chunk 格式面向「快速 flush + 查询时全量扫描」，在百万行级别筛选部分字段时成为瓶颈。新格式让每个字段独占一列且**无 schema**（不需要预先定义列），查询只读取需要的列。

两点务实的提醒：

- **单二进制部署不受影响**。本地或单节点场景没有复制要编排，不会被强加 Kafka 依赖；分布式部署则需要把 Kafka 纳入运维面——这打破了 Loki「只依赖对象存储」的原始设计原则。
- **精确搜索仍待解决**。列式格式不天然解决前面提到的 needle in the haystack 问题，这是收购 Logline 的动因（定向二级索引，宣称最多可减少 99% 的字节扫描），先在 Grafana Cloud 私有预览，开源侧后续提供。迁移期官方提供了开源组件 Querity，可在新旧引擎间选择或对比结果。

## Operations Notes

- **Helm chart 归属变更**：`loki` chart 自 2026-03-16 起 fork 到社区仓库 `grafana-community/helm-charts`，Grafana Labs 侧的旧副本停止更新。安装前确认仓库地址。
- **限制（limits）必须配**。多租户下 `limits_config` 是防失控的闸门：`ingestion_rate_mb`、`ingestion_burst_size_mb`、`max_streams_per_user`、`max_global_streams_per_user`、`retention_period`、`max_query_length`。没有它，一个写错的标签就能打爆集群。
- **标签基数是第一运维指标**。监控 `loki_streams`（流数量）与 `loki_ingester_memory_chunks`，基数爆炸远比数据量增长更危险。
- **多租户**靠 `X-Scope-OrgID` 头区分，`auth_enabled: true` 时强制校验。
- 日志管道上游的采集 agent，见 [Promtail](/docs/CS/Distributed/Tracing/Promtail.md) 与其继任者 [Grafana Alloy](/docs/CS/Distributed/Tracing/Alloy.md)。

## Links

- [Tracing](/docs/CS/Distributed/Tracing/Tracing.md)
- [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md)
- [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md)
- [Micrometer](/docs/CS/log/Micrometer.md)

## References

1. [Grafana Loki documentation](https://grafana.com/docs/loki/latest/)
2. [Loki storage](https://grafana.com/docs/loki/latest/configure/storage/)
3. [LogQL: Log query language](https://grafana.com/docs/loki/latest/query/)
4. [GrafanaCON 2026 announcements](https://grafana.com/blog/grafanacon-2026-announcements/)
5. [Grafana Rearchitects Loki with Kafka (InfoQ)](https://www.infoq.com/news/2026/04/grafana-loki-ai-agents)
6. [grafana/loki Releases](https://github.com/grafana/loki/releases)
