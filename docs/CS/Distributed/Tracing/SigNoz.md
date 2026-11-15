## Introduction

[SigNoz](https://signoz.io/) 是一个开源的 **OpenTelemetry-native APM** 平台（Apache 2.0 社区版），定位是 Datadog / New Relic 的替代品：把 traces、metrics、logs、exceptions、alerts 收进同一个产品，且从设计之初就围绕 OpenTelemetry 语义约定构建。与 [SkyWalking](/docs/CS/Distributed/Tracing/SkyWalking.md) / [Pinpoint](/docs/CS/Distributed/Tracing/Pinpoint.md)「自研 agent + 自研存储」的路线不同，SigNoz 不造私有协议——采集侧完全交给 [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md) SDK / Collector，自身只做「存储 + 查询 + 可视化」。

SigNoz 最关键的架构选择是 **单一 ClickHouse 库同时存 traces / metrics / logs**。对照 [Grafana](/docs/CS/Distributed/Tracing/Grafana.md) 的 LGTM 栈（Tempo / Mimir / Loki 各管一类、各自存储），SigNoz 用一套列式引擎覆盖三支柱，因此跨信号查询（例如「这条慢 trace 对应的那条 log、那个指标」）天然可以 join，不必预先决定给哪些字段建索引。

> [!NOTE]
> 本页为**源码级**笔记，关键结论已对照 **SigNoz v0.150.0**（tag `v0.150.0`，稀疏克隆 `pkg/query-service` 于 `signoz-qs-0.150.0/`）与 **signoz-otel-collector v0.26.0**（tag `v0.26.0`，克隆于 `signoz-otel-collector-0.26.0/`）逐条核实，下面讲解直接贴真实源码，路径相对仓库根，不再标注行号。仓库相对路径统一为 `signoz-qs-0.150.0/`（query-service）与 `signoz-otel-collector-0.26.0/`（采集侧）。

各信号经由 OpenTelemetry 统一采集，落到同一 ClickHouse 实例：

```
OpenTelemetry SDK / 任意 OTel Collector
        │  OTLP (gRPC :4317 / HTTP :4318)
        ▼
signoz-otel-collector   (基于 contrib 的 OTel Collector 发行版：
        │                  receiver/otlpreceiver 收 OTLP，
        │                  exporter/kafkaexporter 落到 Kafka 缓冲)
        │  Kafka (spans / metrics / logs 主题)
        ▼
┌──────────────────────────────────────────────┐
│   query-service (Go)  ← ingestion 管线写 ClickHouse
│   ClickHouse  (signoz_traces / signoz_logs / 指标库)
└───────────────────────┬──────────────────────┘
                        │  查询
        ┌───────────────┴───────────────┐
        ▼                                ▼
 query-service API (Gin)           alertmanager (signoz 分支)
        │  REST                             │  alerts
        ▼                                  │
   frontend (React/Next.js)  ◀─────────────┘
```

## Components (source)

- **signoz-otel-collector**（`signoz-otel-collector-0.26.0/`）：SigNoz 在 upstream contrib Collector 基础上构建的发行版，作为统一摄入层。OTLP 经 `receiver/otlpreceiver` 接收，经批处理、日志解析等 processor 后，经 `exporter/kafkaexporter` 落到 Kafka 做缓冲（production 部署的默认管线；SDK 不直接写库）。v0.26.0 的该发行版**不含 ClickHouse exporter**——写入 ClickHouse 由后端 ingestion 管线完成。
- **query-service**（`signoz-qs-0.150.0/`，Go）：后端查询引擎。`pkg/query-service/app/server.go` 的 `NewServer` 构造 `Server`，其中 `clickhouseReader.NewReader(...)` 建立 ClickHouse 读取层，`NewAPIHandler` 挂载 traces / logs / metrics / service-map 等一系列 HTTP handler 并注册到 apiserver 路由：

  ```go
  func NewServer(config signoz.Config, signoz *signoz.SigNoz) (*Server, error) {
  	integrationsController, err := integrations.NewController(signoz.SQLStore, signoz.Modules.Dashboard)
  	// ...
  	reader := clickhouseReader.NewReader(
  		signoz.Instrumentation.Logger(),
  		signoz.SQLStore,
  		signoz.TelemetryStore,
  		signoz.Prometheus,
  		signoz.TelemetryStore.Cluster(),
  		signoz.Cache,
  		signoz.Flagger,
  		nil,
  	)
  	// ...
  	apiHandler, err := NewAPIHandler(APIHandlerOpts{
  		Reader:                        reader,
  		IntegrationsController:        integrationsController,
  		LogsParsingPipelineController: logParsingPipelineController,
  		FluxInterval:                  config.Querier.FluxInterval,
  		Signoz:                        signoz,
  		// ...
  	}, config)
  	// ...
  	r := signoz.APIServer.Router()
  	am := middleware.NewAuthZ(signoz.Instrumentation.Logger(), signoz.Modules.OrgGetter, signoz.Authz)

  	apiHandler.RegisterRoutes(r, am)
  	apiHandler.RegisterLogsRoutes(r, am)
  	// ... RegisterQueryRangeV3Routes / RegisterQueryRangeV4Routes /
  	//     RegisterMessagingQueuesRoutes / RegisterTraceFunnelsRoutes 等
  	// ...
  }
  ```
- **ClickHouse**：唯一存储引擎。traces / metrics / logs 三信号落进同一组库；高基数属性无需预先建索引即可过滤（见下 *ClickHouse Storage Model*）。历史版本曾用 Druid 存指标、用独立 `ingester` 做 trace 摄入，现已收敛到 ClickHouse 单库 + Kafka 缓冲。
- **alertmanager**：SigNoz 维护的 Prometheus Alertmanager 分支，负责阈值 / 异常 / Apdex 告警投递。
- **frontend**：React / Next.js 单页应用，渲染 APM 视图、火焰图、日志检索、仪表盘与告警。

## ClickHouse Storage Model (source)

query-service 里常量化的库/表名揭示了 ClickHouse 的存储划分（`pkg/query-service/app/clickhouseReader/options.go`，`reader.go` 的常量区另有重申）：

```go
const (
	defaultTraceDB                 string        = "signoz_traces"
	defaultOperationsTable         string        = "distributed_signoz_operations"
	defaultIndexTable              string        = "distributed_signoz_index_v2"
	defaultLocalIndexTable         string        = "signoz_index_v2"
	defaultErrorTable              string        = "distributed_signoz_error_index_v2"
	defaultDurationTable           string        = "distributed_durationSort"
	defaultUsageExplorerTable      string        = "distributed_usage_explorer"
	defaultSpansTable              string        = "distributed_signoz_spans"
	defaultDependencyGraphTable    string        = "distributed_dependency_graph_minutes_v2"
	defaultTopLevelOperationsTable string        = "distributed_top_level_operations"
	defaultSpanAttributeTableV2    string        = "distributed_tag_attributes_v2"
	defaultSpanAttributeKeysTable  string        = "distributed_span_attributes_keys"
	defaultLogsDB                  string        = "signoz_logs"
	defaultLogsTable               string        = "distributed_logs"
	// ...
	defaultLogsLocalTableV2         string = "logs_v2"
	defaultLogsTableV2              string = "distributed_logs_v2"
	// ...
	defaultTraceIndexTableV3    string = "distributed_signoz_index_v3"
	defaultTraceLocalTableName  string = "signoz_index_v3"
	defaultTraceResourceTableV3 string = "distributed_traces_v3_resource"
	defaultTraceSummaryTable    string = "distributed_trace_summary"

	defaultMetadataDB    string = "signoz_metadata"
	defaultMetadataTable string = "distributed_attributes_metadata"
)
```

- **Traces 库 `signoz_traces`** 被拆成多张表，核心是一对「索引表 + span 明细表」：
  - `distributed_signoz_index_v2`（`signoz_index_v2` 本地）——索引/可检索列，服务过滤与搜索；
  - `distributed_signoz_spans`——完整 span 明细；
  - `distributed_signoz_operations`——操作名（operation）聚合；
  - `distributed_signoz_error_index_v2`——错误索引；
  - v3 schema 对应 `distributed_signoz_index_v3` / `signoz_index_v3`（见上面常量块的 `defaultTraceIndexTableV3` / `defaultTraceLocalTableName`）。
- **Logs 库 `signoz_logs`**（`:31`）：日志行与 `distributed_tag_attributes_v2` 等标签属性表。
- 指标、异常、profiles 同样落在 ClickHouse 对应库。

这种「索引表 + 明细表」的二分与 [Uptrace](/docs/CS/Distributed/Tracing/Uptrace.md) 的 `SpanIndex`/`SpanData` 双表思路同源，都是为了把高频过滤列与大体量明细分开。查询时按属性类型动态拼列名，因此任意 `attributes.*` 无需预定义即可过滤。`pkg/query-service/app/traces/v3/query_builder.go` 与 `pkg/query-service/app/traces/v4/query_builder.go` 各有一组把属性 key 映射成 ClickHouse 列位置/数据类型的辅助函数：

```go
// pkg/query-service/app/traces/v3/query_builder.go
func getClickhouseTracesColumnDataTypeAndType(key v3.AttributeKey) (v3.AttributeKeyType, string) {
	filterType := key.Type
	filterDataType := "string"
	if key.DataType == v3.AttributeKeyDataTypeFloat64 || key.DataType == v3.AttributeKeyDataTypeInt64 {
		filterDataType = "number"
	} else if key.DataType == v3.AttributeKeyDataTypeBool {
		filterDataType = "bool"
	}
	if filterType == v3.AttributeKeyTypeTag {
		filterType = "TagMap"
	} else {
		filterType = "resourceTagsMap"
		filterDataType = ""
	}
	return filterType, filterDataType
}
```

```go
// pkg/query-service/app/traces/v4/query_builder.go
func getClickHouseTracesColumnType(columnType v3.AttributeKeyType) string {
	if columnType == v3.AttributeKeyTypeResource {
		return "resources"
	}
	return "attributes"
}
```

## Query & API Layer (source)

- `Server` 持有 ClickHouse reader（见上 `NewServer` 片段）；读路径由 `pkg/query-service/app/clickhouseReader` 承担，trace 查询经 `app/traces/v3` 与 `app/traces/v4` 两套查询构建器把 OTel 语义映射成 ClickHouse SQL（v3/v4 对应不同表结构）。
- HTTP API 集中在 `pkg/query-service/app/http_handler.go`：`NewAPIHandler` 初始化时把 querier 与 queryBuilder 一次装配好，`getLogs` / `getTraces` / `getServiceMap` / `getMetrics` 等 handler 提供查询端点，经 `app/querier`、`app/queryBuilder` 下推到 ClickHouse：

  ```go
  func NewAPIHandler(opts APIHandlerOpts, config signoz.Config) (*APIHandler, error) {
  	querierOpts := querier.QuerierOptions{
  		Reader:       opts.Reader,
  		Cache:        opts.Signoz.Cache,
  		KeyGenerator: queryBuilder.NewKeyGenerator(),
  		FluxInterval: opts.FluxInterval,
  	}
  	// ...
  	querier := querier.NewQuerier(querierOpts)
  	querierv2 := querierV2.NewQuerier(querierOptsV2)

  	aH := &APIHandler{
  		logger:     slog.Default(),
  		reader:     opts.Reader,
  		querier:    querier,
  		querierV2:  querierv2,
  		Signoz:     opts.Signoz,
  		// ...
  	}

  	logsQueryBuilder := logsv4.PrepareLogsQuery
  	tracesQueryBuilder := tracesV4.PrepareTracesQuery

  	builderOpts := queryBuilder.QueryBuilderOptions{
  		BuildMetricQuery: metricsv3.PrepareMetricQuery,
  		BuildTraceQuery:  tracesQueryBuilder,
  		BuildLogQuery:    logsQueryBuilder,
  	}
  	aH.queryBuilder = queryBuilder.NewQueryBuilder(builderOpts)
  	// ...
  }
  ```
- 查询入口有三：Query Builder（拖拽）、PromQL（指标类）、ClickHouse SQL（高基数 ad-hoc），与可视化层建立在 OTel 语义约定之上（APM、异常、消息队列监控直接消费 OTel attribute）。

## Alerting Engine (source)

告警是一个独立的规则引擎，位于 `pkg/query-service/rules`：

- `Manager`（`pkg/query-service/rules/manager.go`）管理全部规则，`NewManager` 构造、`Start` 启动规则评估循环：

  ```go
  // The Manager manages recording and alerting rules.
  type Manager struct {
  	opts  *ManagerOptions
  	tasks map[string]Task
  	rules map[string]Rule
  	mtx   sync.RWMutex
  	block chan struct{}
  	// ...
  }

  func NewManager(o *ManagerOptions) (*Manager, error) {
  	o = defaultOptions(o)

  	m := &Manager{
  		tasks:           map[string]Task{},
  		rules:           map[string]Rule{},
  		ruleStore:       o.RuleStore,
  		maintenanceStore: o.MaintenanceStore,
  		opts:            o,
  		block:           make(chan struct{}),
  		// ...
  	}
  	// ...
  }

  func (m *Manager) Start(ctx context.Context) {
  	if err := m.initiate(ctx); err != nil {
  		m.logger.ErrorContext(ctx, "failed to initialize alerting rules manager", errors.Attr(err))
  	}
  	m.run(ctx)
  }
  ```

- 规则分两类：`ThresholdRule`（`pkg/query-service/rules/threshold_rule.go`，基于阈值的评估）与 Prometheus 风格规则（`rules/prom_rule.go`，recording/alerting rule 直接对 ClickHouse 数据求值，复用 PromQL 表达式）。`Manager` 按 `RuleType` 分派，`manager.go` 的 `defaultPrepareTaskFunc` 里两条分支一目了然：

  ```go
  if opts.Rule.RuleType == ruletypes.RuleTypeThreshold {
  	// create a threshold rule
  	tr, err := NewThresholdRule(
  		ruleID,
  		opts.OrgID,
  		opts.Rule,
  		opts.Querier,
  		opts.Logger,
  		// ...
  	)
  	// ...
  	task = newTask(TaskTypeCh, opts.TaskName, taskNameSuffix, evaluation.GetFrequency().Duration(), rules, opts.ManagerOpts, opts.NotifyFunc)
  } else if opts.Rule.RuleType == ruletypes.RuleTypeProm {
  	// create promql rule
  	pr, err := NewPromRule(
  		ruleID,
  		opts.OrgID,
  		opts.Rule,
  		opts.Logger,
  		opts.ManagerOpts.Prometheus,
  		// ...
  	)
  	// ...
  }
  ```

  其中 `ThresholdRule` 本体很薄，就是 `BaseRule` 加一个 querier：

  ```go
  type ThresholdRule struct {
  	*BaseRule

  	querier querier.Querier
  }

  var _ Rule = (*ThresholdRule)(nil)
  ```
- 规则评估结果经 [SigNoz alertmanager](https://github.com/SigNoz/alertmanager) 分支投递到邮件 / Slack / Webhook / PagerDuty。

## OpenTelemetry-native 取向

- **instrument once**：应用只用 OTel SDK 埋点，可随时换后端，无 vendor lock-in。
- **OpAMP 支持**：`pkg/query-service/app/opamp` 包通过 Open Agent Management Protocol 集中管理 agent 配置与采集规则下发。`configure_ingestionRules.go` 的 `addIngestionControlToAgent` 把 ingestion control processor 注入 agent 的 Collector YAML 配置再回传：

  ```go
  // addIngestionControlToAgent adds ingestion contorl rules to agent config
  func addIngestionControlToAgent(agent *model.Agent, signal string, processors map[string]interface{}, withLB bool) (string, error) {
  	confHash := ""
  	config := agent.Config
  	c, err := yaml.Parser().Unmarshal([]byte(config))
  	if err != nil {
  		return confHash, err
  	}

  	agentConf := confmap.NewFromStringMap(c)

  	// add ingestion control spec
  	err = makeIngestionControlSpec(agentConf, Signal(signal), processors)
  	if err != nil {
  		slog.Error("failed to prepare ingestion control processors for agent", "agent_id", agent.AgentID, errors.Attr(err))
  		return confHash, err
  	}

  	// ------ complete adding processor
  	configR, err := yaml.Parser().Marshal(agentConf.ToStringMap())
  	// ...
  }
  ```
- **可观测性管道可编排**：signoz-otel-collector 支持可配置 pipelines，接入 50+ 数据源。
- **部署形态灵活**：纯自托管（Docker Compose / Helm）、SigNoz Cloud，或两者并存；数据可落在 US / EU / India 区域以满足合规。

## Comparison with Grafana LGTM

| 维度 | SigNoz | [Grafana LGTM](/docs/CS/Distributed/Tracing/Grafana.md) |
| --- | --- | --- |
| 存储 | 单一 ClickHouse 覆盖三信号 | Tempo / Mimir / Loki 各一后端、各自存储 |
| 采集 | 经 signoz-otel-collector（→Kafka 缓冲） | 经 [Alloy](/docs/CS/Distributed/Tracing/Alloy.md) / OTel Collector |
| 查询语言 | Query Builder / PromQL / ClickHouse SQL | PromQL / LogQL / TraceQL |
| 跨信号关联 | 同库 join，任意属性可过滤 | 经共享 label 与 trace id 关联 |
| 许可 | Apache 2.0（社区版） | 核心项目 AGPL |
| UI | 自带一体化 UI | 主要依托 Grafana |

代价：SigNoz 把所有负载压在 ClickHouse 一个引擎上，扩缩容不如 LGTM「每信号独立扩展」灵活；LGTM 则要运维多套分布式系统。选型本质是「一个数据库 vs 四个数据库」的取舍。

## Links

- [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md) — SigNoz 的采集与数据模型基础
- [Uptrace](/docs/CS/Distributed/Tracing/Uptrace.md) — 同为 ClickHouse 背书的 OTel-native APM（源码级），对照双表设计
- [Elastic APM](/docs/CS/Distributed/Tracing/ElasticAPM.md) — 另一条 OTel-native 后端路线（Elasticsearch）
- [Tempo](/docs/CS/Distributed/Tracing/Tempo.md) — 同为 OTel-native 但走「四后端」路线
- [SkyWalking](/docs/CS/Distributed/Tracing/SkyWalking.md) — 自研 agent + 存储路线的 APM 对照
- [Pinpoint](/docs/CS/Distributed/Tracing/Pinpoint.md) — 字节码插桩路线的 APM 对照

## References

- SigNoz documentation：https://signoz.io/docs/
- SigNoz GitHub（v0.150.0 tag）：https://github.com/SigNoz/signoz/releases/tag/v0.150.0
- SigNoz OpenTelemetry Collector（v0.26.0 tag）：https://github.com/SigNoz/opentelemetry-collector/releases/tag/v0.26.0
- Better Stack — Grafana Cloud vs SigNoz (2026)：https://betterstack.com/community/comparisons/grafana-cloud-vs-signoz
