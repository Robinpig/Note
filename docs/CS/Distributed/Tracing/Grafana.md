## Introduction

[Grafana](https://grafana.com/oss/grafana/) 是 Grafana Labs 开源的**统一可观测性可视化层**。它本身不存储任何遥测数据，而是把各种后端接成**数据源**（data source），在同一个界面里查询、绘图、告警。

在 LGTM 栈里，Grafana 是那个 **G**：

| 字母 | 组件 | 信号 | 角色 |
| --- | --- | --- | --- |
| **L** | [Loki](/docs/CS/Distributed/Tracing/Loki.md) | Logs | 日志聚合，只索引标签 |
| **G** | Grafana | — | 统一可视化与告警 |
| **T** | [Tempo](/docs/CS/Distributed/Tracing/Tempo.md) | Traces | 追踪后端，Parquet + 对象存储 |
| **M** | Mimir（或 [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md)） | Metrics | 指标时序库 |

Grafana 之所以是这套栈的枢纽，不在于它画图画得好，而在于它**把三支柱放进了同一块屏幕**：你可以在一条时间线上看到指标拐点，从拐点处下钻到那几秒钟的 trace，再从 trace 跳到对应服务的日志原文——三者的关联靠 trace id 与标签一致来维系。

> [!NOTE]
> 版本事实截至 2026-10：Grafana 当前主线为 **13.x**（13.0.0 发布于 2026-04-14，13.1.x 于 2026-06-22，近期补丁线 13.2.x）。支持策略：每个 minor 自发布起获 9 个月支持，major 的最后一个 minor 获 15 个月——12.4.x 作为 12 的收尾版本支持到 2027-05-24。

## Data Sources

数据源是 Grafana 的核心抽象：一个数据源 = 一种后端 + 一种查询语言。官方与社区提供 **170 多个数据源**、**120 多个可视化面板**。

可观测性栈里最常用的几个：

| 数据源 | 查询语言 | 对应信号 |
| --- | --- | --- |
| Prometheus / Mimir | PromQL | Metrics |
| Loki | LogQL | Logs |
| Tempo | TraceQL | Traces |
| Jaeger / Zipkin | 自有 | Traces |
| Pyroscope | 自有 | Profiles（第四支柱） |
| Elasticsearch | Lucene / DSL | Logs |
| MySQL / PostgreSQL / ClickHouse | SQL | 业务数据 |

关系型数据库作为数据源常被忽略，但它很有用——把业务指标和基础设施指标画在同一张图上，是排查「到底是系统慢还是订单结构变了」这类问题的最快方式。

## Dashboards

### 面板与可视化

Grafana 的面板类型覆盖时序折线图、柱状图、仪表盘（gauge）、状态热力图（stat）、表格、日志面板、追踪面板、节点图（node graph，画服务拓扑）、直方图/热力图等。

面板与查询的组合是最基本的技能，几条经验：

- **变量（variables）驱动复用**：把 `instance`、`namespace`、`service` 做成下拉变量，一张仪表盘覆盖全集群，而不是为每个服务复制一份。
- **Recording rules 预聚合**：高频查询的仪表盘应该在 [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md) 侧用 recording rule 预计算，别让每次刷新都扫原始序列。
- **布局模板**：13 提供了 DORA、USE / RED 等标准方法论的布局模板，直接套用比从空白页开始省心。USE（Utilization/Saturation/Errors）看资源，RED（Rate/Errors/Duration）看服务，是两套最值得先掌握的骨架。

### 常用官方仪表盘 ID

Grafana 官方市场按 ID 分享仪表盘，导入时填 ID 即可（`Dashboards → Import`）。下面几个是生产里最常见的：

| 组件 | Exporter | Dashboard ID |
| --- | --- | --- |
| MySQL | `prom/mysqld-exporter` | 14057 |
| Redis | `oliver006/redis_exporter` | 11835 |
| Kafka | `rfvbkm/kafka-exporter` | 25462 |

导入前注意：官方仪表盘的指标名依赖特定 exporter 版本，版本不匹配会出现空面板，需要手动调整查询。

### 13 的仪表盘改进

- **Suggested dashboards（推荐仪表盘）**：根据已连接的数据源自动推荐现成仪表盘，解决「空白页综合征」。
- **Dynamic dashboards GA**：仪表盘可根据变量、上下文与用户需求自适应，不必再为每个组合复制一份静态副本。
- **Git Sync GA**：基于重新设计的仪表盘 schema 与版本化 API 的双向 Git 工作流（GitHub / GitLab / Bitbucket / 原生 git），把仪表盘纳入 observability as code。
- **Grafana Advisor**：定期对 Grafana 服务器做健康检查，给出可执行的优化建议。
- **Graphviz panel**（实验性）：用 DOT 语言定义交互图，把实时数据映射到节点颜色、边宽度上，适合画服务拓扑与依赖关系。

## Explore: 三支柱的关联点

Explore 是 Grafana 里做**临时调查**（ad-hoc investigation）的地方，也是三支柱真正咬合的位置。典型排查路径：

```
1. 指标发现异常（Prometheus / Mimir）
   rate(http_requests_total{status=~"5.."}[5m]) 出现尖峰
        │
        ▼ 同一时间窗
2. 下钻到 trace（Tempo）
   { resource.service.name = "checkout" && status = error }
        │
        ▼ 选中一条 trace，取其 trace_id
3. 跳到日志原文（Loki）
   {app="checkout"} | trace_id="4bf92f..." 
        │
        ▼ 看具体报错堆栈
4. 回到指标确认影响面，修复后验证曲线回落
```

让这条链路跑通有两个前提：

1. **日志里带 trace id**。应用输出日志时必须把 `trace_id`（以及 `span_id`）写进去。在 [Loki](/docs/CS/Distributed/Tracing/Loki.md) 中应把它作为 structured metadata 而不是标签——标签会让流数量爆炸。
2. **配置数据源关联**（correlations）。在 Grafana 里为数据源配置关联规则，指定从哪个字段跳转到哪个数据源，点击即可跳转，而不是手工复制 trace id。

这三步走完，才谈得上「不重新发版就能定位未知故障」。任何一根支柱单独存在，都只是监控，不是可观测性。

## Alerting

Grafana 使用 **Unified Alerting**：告警规则可以在 Grafana 侧定义并直接查询各数据源，而不必全部下沉到 Prometheus 的 alerting rules。

两种告警来源的分工：

| 来源 | 适用 |
| --- | --- |
| Prometheus alerting rules + Alertmanager | 纯指标告警、规模大、需要复杂路由与抑制 |
| Grafana Unified Alerting | 跨数据源告警、查询结果告警、无后端告警能力的数据源（如 Loki、SQL） |

Grafana 侧的流程是：查询 → 条件（threshold / 无数据 / 异常）→ 评估周期（`for`）→ 通知策略（label 匹配路由）→ 联系点（Slack / Webhook / 邮件 / 企业微信 / PagerDuty）。

实践上常见的坑是**告警风暴**：一个指标抖动触发几十条通知。Unified Alerting 靠分组（group by）与通知策略的静默、抑制来控制，规则设计时应按「影响用户」而不是「资源阈值」来定级。

## Provisioning

生产环境的 Grafana 应该**配置即代码**，而不是有人在 UI 上点。Provisioning 通过目录里的 YAML 文件在启动时自动加载数据源与仪表盘：

```yaml
# /etc/grafana/provisioning/datasources/lgtm.yaml
apiVersion: 1
datasources:
  - name: Prometheus
    type: prometheus
    url: http://prometheus:9090
    isDefault: true

  - name: Loki
    type: loki
    url: http://loki:3100
    jsonData:
      derivedFields:                        # 从日志中提取 trace_id 并跳转到 Tempo
        - datasourceUid: tempo
          matcherRegex: '"trace_id":"(\w+)"'
          name: TraceID
          url: '$${__value.raw}'

  - name: Tempo
    type: tempo
    uid: tempo
    url: http://tempo:3200
```

上例中的 `derivedFields` 就是把日志与 trace 联动起来的具体配置：正则从日志行里抓出 trace id，渲染成跳转到 Tempo 数据源的链接。

仪表盘同理，用 `provisioning/dashboards/` 下的 provider 指向存 JSON 的目录，配合 Git 管理（13 起另有 Git Sync 做双向同步）。

## Deployment Notes

- **数据库**：默认 SQLite 只适合单机。HA 部署应改用 MySQL 或 PostgreSQL 存 dashboard、用户、session 与告警状态，多个 Grafana 实例共享同一库，前面挂负载均衡。
- **高可用告警**：开启 `[unified_alerting]` 的 HA，实例间通过 `ha_listen_address` / `ha_peers` 互相感知，避免重复发通知。
- **无状态化**：session 与 remote_cache 都应落到共享数据库，这样任意实例都能服务任意请求。
- **插件**：通过 `GF_INSTALL_PLUGINS` 环境变量或 `grafana-cli plugins install` 安装，注意插件不自动更新。
- 完整的高可用部署示例（双 Prometheus + 三节点 Alertmanager + 双 Grafana + 外部 MySQL）见 [部署实践](/docs/CS/Distributed/Tracing/Prometheus/Deploy.md)。

## AI 相关能力（2026）

Grafana Labs 近一年把 AI 能力推进得很快，但大多带预览属性，采用前需确认可用性：

- **Grafana Assistant**：面向可观测性的 LLM 助手，可分析遥测数据、改仪表盘、简化 SQL 表达式。自 13 起 OSS 与 Enterprise 用户也能通过连接 Grafana Cloud 账号使用；另有 skills、automations，以及 Slack / Teams / API / CLI 的接入方式。
- **GCX CLI**（public preview）：把 Grafana Cloud 数据拉进编码 agent（如 Claude Code、Cursor）的命令行工具，用于「合成监测发现故障 → Assistant 根因分析 → 在编辑器里改代码 → 回查指标确认恢复」的闭环。同时也在开发 hosted remote MCP server。
- **AI Observability**（Grafana Cloud，public preview）：面向 LLM 应用与 agent 工作负载的监控评估。

## Links

- [Loki](/docs/CS/Distributed/Tracing/Loki.md)
- [Tempo](/docs/CS/Distributed/Tracing/Tempo.md)
- [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md)
- [Tracing](/docs/CS/Distributed/Tracing/Tracing.md)
- [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md)
- [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md)

## References

1. [Grafana documentation](https://grafana.com/docs/grafana/latest/)
2. [Grafana 13 release: GrafanaCON 2026 announcements](https://grafana.com/blog/grafanacon-2026-announcements/)
3. [Provisioning Grafana data sources](https://grafana.com/docs/grafana/latest/administration/provisioning/)
4. [Grafana dashboards](https://grafana.com/grafana/dashboards/)
5. [Grafana download and version support](https://grafana.com/grafana/download/)
