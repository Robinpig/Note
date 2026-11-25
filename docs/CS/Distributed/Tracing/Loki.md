## Introduction

[Grafana Loki](https://grafana.com/oss/loki/) 是一个水平可扩展、高可用、多租户的**日志聚合系统**（log aggregation system），由 Grafana Labs 开源，设计灵感来自 [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md)。它是 LGTM 栈中的 **L**（Logs），与 [Grafana](/docs/CS/Distributed/Tracing/Grafana.md)、[Tempo](/docs/CS/Distributed/Tracing/Tempo.md)、Mimir 分别对应可视化、追踪与指标。

Loki 的核心取舍一句话可以概括：**默认为标签建立主索引，不对日志正文建立全文倒排索引**。

传统日志系统（Elasticsearch 为代表）会对日志全文建立倒排索引，写入昂贵、存储膨胀；Loki 反其道而行——日志正文被压缩成 chunk 写入对象存储（S3/GCS/Azure Blob），主索引只保留一组 Prometheus 风格的标签。3.x 的 structured metadata 可提供另一层字段过滤能力，实验性 bloom filter 也可减少部分候选 chunk 的扫描，但它们都不等于正文全文索引。代价是缺少标签约束的正文搜索慢，收益是索引极小、成本较低、对象存储路径简单。

> [!NOTE]
> 版本事实截至 2026-11-25：本文以 **Loki v3.7.10**（2026-11-13）为基线，tag `v3.7.10` 指向 commit `c792f58577a46c64b0a8e808d7c643ed0e8c5e83`。下文将默认生产路径与 GrafanaCON 2026 公布的 Loki 4.0 演进方向分开讨论；v3.7.10 已包含部分默认关闭的实验代码，但这不等于新架构已经成为默认生产能力，落地状态以对应版本 release notes 为准。

源码级分册按链路展开：[总览](/docs/CS/Distributed/Tracing/Loki/README.md)、[写入路径](/docs/CS/Distributed/Tracing/Loki/Write_Path.md)、[存储与 TSDB](/docs/CS/Distributed/Tracing/Loki/Storage.md)、[查询路径](/docs/CS/Distributed/Tracing/Loki/Query_Path.md)、[一致性与生命周期](/docs/CS/Distributed/Tracing/Loki/Consistency.md)。

## Design: Index for Cost

| 维度 | Elasticsearch / EFK | Loki |
| --- | --- | --- |
| 索引对象 | 日志**全文**（分词倒排） | 默认以**标签**（label set）为主索引；structured metadata 与 bloom 是补充 |
| 写入成本 | 高（分词、建索引） | 低（压缩后直接写对象存储） |
| 存储占用 | 索引常与数据同量级 | 索引比数据小两三个数量级 |
| 全文检索 | 快，开箱即用 | 慢，需要在标签圈定的流内做暴力扫描 |
| 高基数标签 | 无所谓 | **致命**，直接决定成本 |
| 查询语言 | DSL / Lucene | LogQL |
| 与指标的关联 | 需额外打通 | 天然同构（都是 Prometheus 标签模型） |

Loki 的性价比来自「小索引 + 高压缩 chunk」。但这个取舍有一个明确的反面：**大海捞针式查询**（needle in the haystack，例如「在所有日志里搜某个 user_id」）在 Loki 上很慢，因为标签主索引不能直接指向正文。v3.7.10 的实验性 bloom filter 主要索引 structured metadata，而不是任意正文 substring。Logline 的定向二级索引已在 Grafana Cloud Logs 有限私有预览，OSS 计划在下一个大版本提供；这不是 v3.7.10 的现有能力。

## Data Model

Loki 的数据模型几乎是 Prometheus 标签模型的翻版：

- **Stream（流）**：一组唯一的标签集合（`{app="api", env="prod", namespace="default"}`）标识一条日志流。标签组合的数量就是流的数量，**标签基数直接决定索引大小和查询性能**。
- **Chunk（块）**：流在一段时间内累积的日志条目，内层 block 默认用 gzip 压缩后写入对象存储。chunk envelope 的 metadata 另用 Snappy，两层编码不是同一个概念。ingester 在内存中攒 chunk，满足条件（大小/空闲时长/最大年龄）后 flush。
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

Loki 3.x 在分布式模式下由以下组件构成；单体模式把主体组件放进一个进程，但 bloom 的构建与查询按设计不支持 single-binary 部署：

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
| Bloom Planner / Builder / Gateway | 实验特性；构建与查询 bloom filter，主要排除不可能含目标 structured metadata 的 chunk |

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
| HA monolithic | 中等规模、希望减少组件编排 | 至少 3 个 `-target=all` 实例、RF=3、memberlist 与共享对象存储；同一时间只能有一个 main compactor，其余为 worker |
| Simple Scalable（SSD） | **已弃用，计划在 Loki 4.0 移除** | 拆成 `write`（distributor+ingester）、`read`（query-frontend+querier）、`backend`（compactor+index-gateway+query-scheduler+ruler）三类；仅作存量迁移对照 |
| Distributed（microservices） | 大规模，需分组件独立扩缩 | 每个组件独立部署，ingester 建议开启 `zoneAwareReplication` |

## Storage

Loki 采用 **single store**：索引与 chunk 都放同一个对象存储，只需维护一套后端。

- **TSDB（推荐）**：Loki 2.8 引入，查询性能更好、TCO 更低，功能上对标 boltdb-shipper，是目前推荐的索引存储。配置上对应 `store: tsdb` + `schema: v13`。
- **BoltDB（boltdb-shipper，已弃用）**：Loki 2.0 引入，曾用于 2.0.0–2.7.x。仍接受存量 3.x 安装，但禁止新安装使用，计划在 Loki 4.0 移除。
- **已弃用、即将移除**：Cassandra、BigTable、DynamoDB 作为 chunk/index 后端，以及 gRPC store。

以下是 **Helm values 片段**，不是可直接加载的 `loki.yaml`；`schemaConfig`、`bucketNames` 等键名属于 chart values，直接作为 Loki 配置会因键名与 TSDB 存储路径不匹配而失败。

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
    chunk_encoding: gzip
  compactor:
    working_directory: /var/loki/compactor
    retention_enabled: true
    delete_request_store: s3
  limits_config:
    allow_structured_metadata: true
    retention_period: 744h
  storage:
    type: s3
    bucketNames:
      chunks: loki-chunks
      ruler: loki-ruler
```

Schema 配置支持随时间分段演进（`from` 日期），Loki 能透明地跨 schema 查询，这是平滑升级的关键机制。注意 **schema 一旦写入就不可回退**，变更前务必确认。

保留（retention）由 compactor 执行，需要同时设置 `limits_config.retention_period`、`compactor.retention_enabled=true` 与 `compactor.delete_request_store`；v13/TSDB 还要求 24 小时 index period。缺少 delete-request store 时配置校验失败。`processed` 只表示删除请求的索引处理完成，对象物理删除仍有 marker delay 与 sweeper 阶段，详见 [Consistency](/docs/CS/Distributed/Tracing/Loki/Consistency.md)。

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

## Loki 4.0 Direction

Grafana Labs 在 GrafanaCON 2026 公布了 Loki 的重大架构演进，动机是结构化日志与 OpenTelemetry 让用法从「简单搜索」转向「高基数分析型查询」，旧设计在扫描量、复制开销和查询局部性上遇到瓶颈。**以下是已公布方向，不是 v3.7.10 的默认生产路径；该版本已有部分实验实现，但默认关闭或能力不完整。**

主要变化有三类：

1. **Kafka 支撑的摄取层**。Kafka 作为持久化缓冲承接写入，新路径以单副本持久性为目标，减少 ingester 多副本带来的 CPU、内存、网络与对象存储重复开销。它改变的是写入与故障边界，不是简单地把 Kafka 插到现有 distributor 后面。
2. **重新设计的查询引擎与调度器**。新引擎把执行粒度下沉到 log-line 以下；v3.7.10 的实验实现中，planner 会把扫描与聚合拆成可并行、可分片的工作图。这里的 partition 是执行计划分片，不等于 Kafka topic partition。目标是减少无效扫描和中间结果放大，但具体性能数字属于官方公布的特定环境结果，不能直接当作任意集群的承诺。
3. **DataObjects 列式存储**。新格式按字段组织列，查询可以只投影所需字段，避免为了少量字段读取和解码整块日志。v3.7.10 实验实现会为 structured metadata key 动态生成 metadata 列，因此无需用户预先声明每个日志字段；但 DataObject 仍有 section、version 与 column 元数据，并非「格式本身无 schema」。

精确搜索仍待解决：列式格式不天然解决 needle in the haystack 问题。Logline 的定向二级索引已在 Grafana Cloud Logs 有限私有预览，计划在下一个大版本进入 OSS；迁移与可用能力应以对应版本的 release notes 为准。新架构还会把 Kafka 纳入分布式写入的运维面，不能继续用「只依赖对象存储」概括整个部署。

## Operations Notes

- **Helm chart 归属变更**：`loki` chart 自 2026-03-16 起 fork 到社区仓库 `grafana-community/helm-charts`；Loki 仓库中的旧 chart 仍为 Grafana Enterprise Logs 用户维护，并非停止更新。安装前确认仓库地址与支持范围。
- **限制（limits）必须配**。多租户下 `limits_config` 是防失控的闸门：`ingestion_rate_mb`、`ingestion_burst_size_mb`、`max_streams_per_user`、`max_global_streams_per_user`、`retention_period`、`max_query_length`。没有它，一个写错的标签就能打爆集群。
- **标签基数是第一运维指标**。监控 `loki_ingester_memory_streams`（流数量）与 `loki_ingester_memory_chunks`，基数爆炸远比数据量增长更危险。
- **多租户**靠 `X-Scope-OrgID` 头区分；`auth_enabled: true` 只强制该头存在且格式合法，不验证身份。生产代理必须认证身份，并用认证结果覆盖客户端提交的 tenant 头，避免跨租户访问。
- 日志管道上游的采集 agent，见 [Promtail](/docs/CS/Distributed/Tracing/Promtail.md) 与其继任者 [Grafana Alloy](/docs/CS/Distributed/Tracing/Alloy.md)。

## Links

- [Tracing](/docs/CS/Distributed/Tracing/Tracing.md)
- [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md)
- [Micrometer](/docs/CS/log/Micrometer.md)
- [Distributed Systems](/docs/CS/Distributed/Distributed.md)

## References

1. [Grafana Loki documentation](https://grafana.com/docs/loki/latest/)
2. [Loki storage](https://grafana.com/docs/loki/latest/configure/storage/)
3. [LogQL: Log query language](https://grafana.com/docs/loki/latest/query/)
4. [GrafanaCON 2026 announcements](https://grafana.com/blog/grafanacon-2026-announcements/)
5. [Grafana Rearchitects Loki with Kafka and Ships a CLI to Bring Observability into Coding Agent (InfoQ)](https://www.infoq.com/news/2026/04/grafana-loki-ai-agents/)
6. [Grafana Labs acquires Logline](https://grafana.com/blog/grafana-labs-acquires-logline/)
7. [Inside Loki's new architecture for faster logging at petabyte](https://grafana.com/blog/grafanacon-2026-on-demand-sessions-are-now-available#inside-lokis-new-architecture-for-faster-logging-at-petabyte)
8. [Loki v3.7.10 source](https://github.com/grafana/loki/tree/v3.7.10)
9. [grafana/loki Releases](https://github.com/grafana/loki/releases)
