## Introduction

[Elastic APM](https://www.elastic.co/observability/apm) 是 Elastic Observability 套件里的应用性能监控能力，后端是 [Elasticsearch](https://www.elastic.co/elasticsearch) + [Kibana](https://www.elastic.co/kibana)。它经历了一次关键转向：**从「自研 agent + APM Server + ECS 格式」演进到「原生说 OpenTelemetry」**。今天新项目走 Elastic OpenTelemetry 路线（OTel SDK / Collector → OTLP → Elasticsearch），旧项目仍可走经典 APM（Elastic 自研 agent → APM Server → ECS）。

理解 Elastic APM 最关键的一点是 **两种存储格式的并存与取舍**：

- **Classic APM（ECS，遗留）**：APM Server 把 OTLP 翻译成 ECS 文档，落到 `traces-apm*` / `metrics-apm*` / `logs-apm*` 数据流；自定义属性进 `labels.*`（点号被替换成下划线），不推荐新用户使用。
- **Elastic OpenTelemetry（otel-native，现行推荐）**：`mapping_mode: otel`（默认）下，日志与 trace 写 **LogsDB**、指标写 **TSDS**，自定义属性保留点号进 `attributes.*`；动态属性无需预先定义维度，避免 mapping explosion。

> [!NOTE]
> 本页为**源码级**笔记。OTel-native 关键路径（指标预聚合 connector 与 trace 富化 processor）已对照 **`elastic-otel-collector-components` v0.81.0**（tag `v0.81.0`，浅克隆于 `elastic-otel-collector-components-0.81.0/`）逐条核实，下面讲解直接贴真实源码，路径相对仓库根，不再标注行号。仓库相对路径统一为 `elastic-otel-collector-components-0.81.0/`。
>
> ⚠️ **范围透明声明**：经典 APM Server / ECS 摄入路径（自研 agent → `apm-server` → ECS）**未做源码级核实**——`elastic/apm-server` 仓库在本轮因代理 502 反复克隆失败，故该路径仅依据 Elastic 官方架构文档描述并以路径引用（不引代码、不标行号），不视为已核实源码结论。

## Ingestion Architecture

Elastic OpenTelemetry 的推荐架构分「边缘（edge）」与「后端（backend）」两层：

```
[ 边缘 / Edge ]                               [ 后端 / Backend ]
应用 + OTel SDK                               Elastic Cloud：
   │  OTLP                                      Managed OTLP Endpoint (全托管摄入)
   ▼                                            │  server-side 指标聚合
任意 OTel Collector 发行版 ──OTLP──┐            ▼
 (contrib / EDOT / Elastic Agent)  ├──►   Elasticsearch (LogsDB + TSDS)
   │  (可选 Elastic Agent 做          │            ▲
   │   host/K8s 元数据富化)           │            │ 查询
   └──► Elastic Agent (gateway 模式) ┘            Kibana (APM UI / 服务图 / 告警)
         (自托管/ECE/ECK 必需，OTLP 网关)
```

- **边缘（edge）**：应用所在的主机 / VM / K8s 节点。这里可以跑**任意** OTel Collector 发行版（contrib、自建、EDOT = Elastic Distribution of OpenTelemetry，或 Elastic Agent），唯一要求是向 Elastic 发送合法 OTLP。可选让 Elastic Agent 用 host / Kubernetes 接收器给遥测补资源元数据。
- **Managed OTLP Endpoint**（Elastic Cloud Serverless / Hosted）：全托管摄入服务，边缘 Collector 可直接发 OTLP 给它，**无需**自管网关；指标聚合在 server 端完成。
- **Elastic Agent（gateway 模式）**（自托管 / ECE / ECK **必需**）：作为后端摄入层，暴露 OTLP 端点，做关键预处理——trace / log 的指标聚合（降低 APM UI 延迟）、为 Elasticsearch 做格式转换。它位于边缘与 ES 之间，被视为后端一部分而非边缘。
- **elasticsearch OTLP/HTTP 端点**：仅自托管 / ECE / ECK 可用，允许 Collector 直连 ES 写 OTel-native 文档。

> [!WARNING]
> 不要把 EDOT SDK 或边缘 Collector 的数据**直接**发给 APM Server 的 OpenTelemetry intake 端点——该路径不被保证正确（属性对齐、富化、排障覆盖都不保证）。受支持的摄入路径只有：自管/ECE/ECK 用 Elastic Agent（gateway 模式），或 Cloud 用 Managed OTLP Endpoint。

## elasticapmconnector（指标预聚合）

`elasticapm` connector 是 OTel Collector 的一个 connector，从 trace 数据**预聚合 APM 指标**，让 APM UI（服务图、事务直方图、SLI）直接查预计算文档，而非实时扫百万级事务。源码层面，它本质是 contrib 仓库 `signaltometricsconnector` 的一个 **Elastic 特化薄包装**：

- 导入并复用 contrib 的 `signaltometricsconnector` 工厂来真正生成指标——`connector/elasticapmconnector/connector.go` 顶部即见两个工厂变量，三类信号（traces/logs/metrics）的消费器全部委托该工厂创建，聚合后的信号再导出到下游的 `lsmintervalprocessor`：

  ```go
  var (
  	lsmintervalFactory     = lsmintervalprocessor.NewFactory()
  	signaltometricsFactory = signaltometricsconnector.NewFactory()
  )

  func (c *elasticapmConnector) newLogsConsumer(ctx context.Context) (consumer.Logs, error) {
  	set := c.signaltometricsSettings()
  	return signaltometricsFactory.CreateLogsToMetrics(ctx, set, c.cfg.signaltometricsConfig(), c.lsminterval)
  }

  func (c *elasticapmConnector) newMetricsConsumer(ctx context.Context) (consumer.Metrics, error) {
  	set := c.signaltometricsSettings()
  	return signaltometricsFactory.CreateMetricsToMetrics(ctx, set, c.cfg.signaltometricsConfig(), c.lsminterval)
  }

  func (c *elasticapmConnector) newTracesToMetrics(ctx context.Context) (consumer.Traces, error) {
  	set := c.signaltometricsSettings()
  	baseConsumer, err := signaltometricsFactory.CreateTracesToMetrics(ctx, set, c.cfg.signaltometricsConfig(), c.lsminterval)
  	if err != nil {
  		return nil, err
  	}
  	// Wrap the base consumer to enrich spans
  	return &spanEnricher{next: baseConsumer}, nil
  }
  ```
- 它自己只负责提供 **Elastic 专属的指标定义与聚合配置**（见下），真正的信号→指标计算交给 `signaltometricsconnector`。

**聚合间隔**：默认三档 `time.Minute / 10*time.Minute / 60*time.Minute`（`connector/elasticapmconnector/config.go`，注释「1m, 10m and 60m」）：

```go
var defaultIntervals []time.Duration = []time.Duration{
	time.Minute,
	10 * time.Minute,
	60 * time.Minute,
}
```

可通过 `AggregationConfig.Intervals` 覆盖，覆盖逻辑在 `config.go` 的 `lsmConfig()`：

```go
type AggregationConfig struct {
	// Directory holds a path to the directory that is used for persisting
	// aggregation state to disk. If Directory is empty, in-memory storage
	// is used.
	Directory string `mapstructure:"directory"`
	// ...
	// NOTE: these intervals should only be overridden for testing purposes when
	// faster processor feedback is required. The default intervals should be preferred
	// in all other cases -- using this configuration may lead to invalid behavior,
	// and will not be supported.
	Intervals []time.Duration `mapstructure:"intervals"`

	// Limits holds optional cardinality limits for aggregated metrics
	Limits AggregationLimitConfig `mapstructure:"limits"`
	// ...
	// Storage holds tuning options for the embedded Pebble database
	// that stores aggregation state. ...
	Storage *lsmconfig.StorageConfig `mapstructure:"storage"`
}

func (cfg Config) lsmConfig() *lsmconfig.Config {
	intervals := defaultIntervals
	if cfg.Aggregation != nil && len(cfg.Aggregation.Intervals) != 0 {
		intervals = cfg.Aggregation.Intervals
	}
	// ...
}
```

注释明确「仅测试用途，默认间隔在生产受支持」。聚合状态默认存内存，可配 `Directory` 落盘（底层是嵌入式 Pebble/KV），并有 `AggregationLimitConfig` 做资源/作用域/指标/数据点四级基数限制：

```go
type AggregationLimitConfig struct {
	// ResourceLimit defines the max cardinality of resources
	ResourceLimit LimitConfig `mapstructure:"resource"`

	// ScopeLimit defines the max cardinality of scopes within a resource
	ScopeLimit LimitConfig `mapstructure:"scope"`

	// MetricLimit defines the max cardinality of metrics within a scope
	MetricLimit LimitConfig `mapstructure:"metric"`

	// DatapointLimit defines the max cardinality of datapoints within a metric
	DatapointLimit LimitConfig `mapstructure:"datapoint"`
}
```

**生成的指标类型**（在 `config.go` 的 `signaltometricsConfig()` 中定义，各指标的分组属性直接以 `signaltometricsconfig.Attribute` 常量化声明，如 `{Key: "transaction.root"}`、`{Key: "transaction.name", Optional: true}` 等）：

- `service_transaction`、`transaction`（吞吐 / 延迟分布 / 成功率；含 `transaction.root`、`transaction.name`、`transaction.type`、`transaction.result`、`event.outcome`）
- `span_destination`（服务间依赖，用于服务图；含 `service.target.type`、`service.target.name`、`span.destination.service.resource`）
- `service_summary`（错误率 / 吞吐 / 延迟汇总）

为让 APM UI 按时间间隔分面，connector 在 `lsmConfig()` 里为每个聚合间隔生成一组 OTTL 语句打标：

```go
intervalsConfig := make([]lsmconfig.IntervalConfig, 0, len(intervals))
for _, i := range intervals {
	statements := []string{
		fmt.Sprintf(`set(attributes["metricset.interval"], "%dm")`, int(i.Minutes())),
		fmt.Sprintf(`set(attributes["data_stream.dataset"], Concat([attributes["metricset.name"], "%dm"], "."))`, int(i.Minutes())),
		`set(attributes["processor.event"], "metric")`,
	}
	statements = append(statements, extraStatements...)
	intervalsConfig = append(intervalsConfig, lsmconfig.IntervalConfig{
		Duration:   i,
		Statements: statements,
	})
}
```

**span 前置富化**：进入聚合前，`spanEnricher` 遍历所有 span 注入两个必需属性——`transaction.root`（当 `ParentSpanID().IsEmpty()` 为真，即根 span）与 `span.name`（`connector/elasticapmconnector/connector.go`）。这两个属性是 `transaction` 与 `span_destination` 指标分组的键：

```go
// spanEnricher wraps a traces consumer to add the
// 'transaction.root' and `span.name` attributes.
// These attributes are needed for transaction and span destination metrics.
type spanEnricher struct {
	next consumer.Traces
}

// ConsumeTraces iterates through all spans to set attributes
// required to correctly generate metrics.
// Forwards the traces to the next consumer.
func (e *spanEnricher) ConsumeTraces(ctx context.Context, td ptrace.Traces) error {
	for i := 0; i < td.ResourceSpans().Len(); i++ {
		rs := td.ResourceSpans().At(i)
		for j := 0; j < rs.ScopeSpans().Len(); j++ {
			ss := rs.ScopeSpans().At(j)
			for k := 0; k < ss.Spans().Len(); k++ {
				span := ss.Spans().At(k)
				span.Attributes().PutBool("transaction.root", span.ParentSpanID().IsEmpty())
				span.Attributes().PutStr("span.name", span.Name())
			}
		}
	}
	return e.next.ConsumeTraces(ctx, td)
}
```

> [!NOTE]
> 部署位置：在 agent 模式与 gateway 模式里，`elasticapm` connector 都作为 traces pipeline 的 exporter 出现，并作为 metrics pipeline 的 receiver 把指标转发给 ES。**在 Managed OTLP Endpoint 上不需要它**——指标聚合在 server 端完成，重复部署会冲突或重复计算。

## elasticapmprocessor（trace 富化）

`elasticapm` processor 的职责如其包注释所述——`processor/elasticapmprocessor/doc.go` 开头一句：`// Package elasticapmprocessor enriches the traces with Elastic specific attributes.`，保证 APM UI 与告警的语义兼容。源码关键行为：

- **映射模式决定富化策略**：`isECSMappingMode(ctx)` 读取 client metadata 里的 `x-elastic-mapping-mode`，当且仅当等于 `"ecs"` 时为 ECS 模式（`processor/elasticapmprocessor/processor.go`）：

  ```go
  func isECSMappingMode(ctx context.Context) bool {
  	clientCtx := client.FromContext(ctx)
  	mappingMode := getMetadataValue(clientCtx)
  	return mappingMode == "ecs"
  }

  func getMetadataValue(info client.Info) string {
  	if values := info.Metadata.Get("x-elastic-mapping-mode"); len(values) > 0 {
  		return values[0]
  	}
  	return ""
  }
  ```

- **三套 enricher**：非 ecs 模式用 `defaultEnricher`；ecs 模式下再按数据源分——`telemetry.sdk.name == "ElasticAPM"` 的资源走 `apmEnricher`（经典 Elastic agent 数据），其余走 `otelEnricher`。`processor.go` 的 `isElasticAPMAgent` 注释说明 `elasticapmintakereceiver` 总会设置该值，OTLP 事件用自己的 SDK 名：

  ```go
  func (p *TraceProcessor) ConsumeTraces(ctx context.Context, td ptrace.Traces) error {
  	ecsMode := isECSMappingMode(ctx)
  	resourceSpans := td.ResourceSpans()
  	for i := 0; i < resourceSpans.Len(); i++ {
  		rs := resourceSpans.At(i)
  		enricher := p.defaultEnricher
  		if ecsMode {
  			if isElasticAPMAgent(rs.Resource()) {
  				enricher = p.apmEnricher
  			} else {
  				enricher = p.otelEnricher
  			}
  		}
  		enricher.EnrichResourceSpans(ctx, rs)
  	}
  	return p.next.ConsumeTraces(ctx, td)
  }

  // isElasticAPMAgent reports whether the data originated from an Elastic APM
  // agent by checking telemetry.sdk.name == "ElasticAPM" on the resource
  // attributes. The elasticapmintakereceiver always sets this value; OTLP
  // events use their own SDK name.
  func isElasticAPMAgent(resource pcommon.Resource) bool {
  	if v, ok := resource.Attributes().Get(string(semconv.TelemetrySDKNameKey)); ok {
  		return v.Str() == "ElasticAPM"
  	}
  	return false
  }
  ```

- **SkipEnrichment 门控**：`processor/elasticapmprocessor/config.go` 的 `SkipEnrichment` 只在「非 ecs 模式」下对 **logs / metrics** 生效——非 ecs 且 `SkipEnrichment=true` 时直接透传（见下面 `ConsumeMetrics` / `ConsumeLogs` 的开头判断）。**trace 恒被富化**，不受该开关影响（配注释 `Traces are always enriched regardless of this setting`）：

  ```go
  type Config struct {
  	config.Config `mapstructure:",squash"`

  	// SkipEnrichment controls whether enrichment should be skipped for logs and metrics
  	// when the mapping mode is not "ecs". When true, logs and metrics are only enriched when
  	// the x-elastic-mapping-mode metadata is set to "ecs". Traces are always enriched regardless
  	// of this setting. Defaults to false for backwards compatibility (always enrich).
  	SkipEnrichment bool `mapstructure:"skip_enrichment"`
  	// ...
  }

  func (p *MetricProcessor) ConsumeMetrics(ctx context.Context, md pmetric.Metrics) error {
  	ecsMode := isECSMappingMode(ctx)
  	if !ecsMode && p.cfg.SkipEnrichment {
  		return p.next.ConsumeMetrics(ctx, md)
  	}
  	// ...
  }

  func (p *LogProcessor) ConsumeLogs(ctx context.Context, ld plog.Logs) error {
  	ecsMode := isECSMappingMode(ctx)
  	if !ecsMode && p.cfg.SkipEnrichment {
  		return p.next.ConsumeLogs(ctx, ld)
  	}
  	// ...
  }
  ```

> [!NOTE]
> connector 与 processor 必须**配对**：processor 给 trace 补 Elastic 专属属性以保证 UI 兼容，connector 依据这些属性预聚合指标。两者一起才构成完整 Elastic APM 体验。

## Classic APM Server / ECS Path（文档级，未做源码引证）

> ⚠️ 该小节仅依据官方文档，非源码核实。以下描述供对照，`apm-server` 仓库克隆失败故仅保留路径引用：`apm-data` 摄入与 `traces-apm*` 等数据流的写入逻辑位于 `elastic/apm-server` 仓库（beats 框架之上）。

经典路径：Elastic 自研语言 agent（如 Java/.NET/Node/Python/RUM agent）通过私有协议发往 **APM Server**，后者把数据翻译为 **ECS** 文档写入 `traces-apm*` / `metrics-apm*` / `logs-apm*` 数据流，自定义属性进 `labels.*`（点号替换为下划线）。该路线仍可用，但 Elastic 不推荐新用户采用，新项目一律走上面的 OTel-native 路径。混合环境里 APM Server 可与 Elastic Agent（gateway 模式）并存，由 Fleet 统一治理。

## Hybrid Ingestion (Elastic 9.2+)

Elastic Agent 9.2 引入 **hybrid ingestion**：同一个 agent 内同时跑「Elastic 原生集成（日志、主机遥测，成熟 dashboard + ECS 映射）」与「OTel 接收器（上游 OTel Collector 组件，由 Fleet 托管）」。两者可并存、由 Fleet 统一治理——这是把成熟生产环境渐进式迁移到 OTel 的最务实路径：保留既有日志管道与 dashboard，仅在需要处增量接入 OTel receivers，不重埋点、不并跑多 agent。

## Kibana & Visualization

- **Discover / Dashboards / APM UI**：trace 瀑布、服务概览、事务组、服务图、依赖拓扑。
- **告警**：基于阈值 / 异常 / Apdex，落到 Kibana 告警与通知。
- **OTel-native 内容包**：走 OTel 路径时需从 Kibana Integrations UI 装 OTel 内容包（搜 "otel"）拿到兼容 dashboard；经典 ECS dashboard 与 OTel 语义不通用，切换格式要同步改查询与告警。

## Comparison with OTel-native APMs

| 维度 | Elastic APM (OTel 路线) | [SigNoz](/docs/CS/Distributed/Tracing/SigNoz.md) / [Uptrace](/docs/CS/Distributed/Tracing/Uptrace.md) |
| --- | --- | --- |
| 存储 | Elasticsearch（LogsDB + TSDS） | ClickHouse（单库） |
| 采集 | 任意 OTel Collector / EDOT / Elastic Agent 网关 | SigNoz/Uptrace 自带 OTel Collector 发行版 |
| 旧栈兼容 | 经典 APM agent + APM Server（ECS）仍可用 | 无旧私有协议 |
| 指标预聚合 | `elasticapm` connector 委托 `signaltometricsconnector`（见上文 connector 片段） | SigNoz query-service 内聚；Uptrace 查询时 MQL 聚合 |
| 可视化 | Kibana | 自带 UI |
| 许可 | Elastic License / SSPL（服务端）；OTel 路径用 Apache 2.0 Collector | Apache 2.0 / AGPL-3.0 |

Elastic 的独特点是「新旧两套摄入并存 + Kibana 生态 + 搜索基因」；代价是存储格式（ECS vs otel-native）的迁移心智与 ES 的运维重量。

## Links

- [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md) — Elastic OpenTelemetry 路线的采集基础
- [SigNoz](/docs/CS/Distributed/Tracing/SigNoz.md) — OTel-native 但走 ClickHouse 的对照
- [Uptrace](/docs/CS/Distributed/Tracing/Uptrace.md) — 同为 OTel-native ClickHouse APM 的对照
- [Tempo](/docs/CS/Distributed/Tracing/Tempo.md) — Grafana 栈里的 trace 后端（Elasticsearch 的另一类用法）
- [SkyWalking](/docs/CS/Distributed/Tracing/SkyWalking.md) — 自研 agent + 存储的 APM 对照
- [Pinpoint](/docs/CS/Distributed/Tracing/Pinpoint.md) — 字节码插桩 APM 对照

## References

- Elastic OpenTelemetry reference architecture：https://www.elastic.co/docs/reference/opentelemetry/architecture
- Elastic OpenTelemetry data streams (otel vs ECS)：https://www.elastic.co/docs/reference/opentelemetry/compatibility/data-streams
- Elastic APM connector（`elasticapmconnector`）：https://elastic.co/docs/reference/edot-collector/components/elasticapmconnector
- Elastic APM processor（`elasticapmprocessor`）：https://elastic.co/docs/reference/edot-collector/components/elasticapmprocessor
- Use OpenTelemetry with Elastic APM：https://www.elastic.co/guide/en/observability/current/apm-open-telemetry-with-elastic.html
