## Introduction

[Uptrace](https://uptrace.dev/) 是一个开源的 **OpenTelemetry-native APM** 平台（开源版 AGPL-3.0），主打「用 OpenTelemetry + ClickHouse 把 traces / metrics / logs 收进一个平台，成本只有 Datadog 的一小部分」。与 [SigNoz](/docs/CS/Distributed/Tracing/SigNoz.md) 类似，Uptrace 也是「OTel 采集 + ClickHouse 存储 + 一体化 UI」的路线，但工程上更极简：核心就是一个 Go 二进制加上 ClickHouse 与 PostgreSQL。

> [!WARNING]
> 常见混淆：Uptrace **基于 ClickHouse，与 VictoriaMetrics 无关**。二者都是 observability 领域知名项目，但 VictoriaMetrics 是自研时序数据库，Uptrace 选用的是 ClickHouse 列存。不要把二者混为一谈。

> [!NOTE]
> 本页为**源码级**笔记，关键结论已对照 **Uptrace v2.0.3 源码**（tag `v2.0.3`，浅克隆于 `uptrace-2.0.3/`）逐条核实，下面讲解直接贴真实源码，路径相对仓库根，不再标注行号。

Uptrace 的部署拓扑（Docker Compose 示意，五个容器是最常见的首次运行形态）：

```
OpenTelemetry SDK / 任意 OTel Collector
        │  OTLP (gRPC :14317 / HTTP :14318，DSN 在 URL 或 header)
        ▼
┌──────────────────────────────────────────────┐
│  Uptrace (单一 Go 二进制, cmd/uptrace)         │
│   接收 OTLP · 按 service/operation 分组 · 写库  │
└───────┬───────────────────────┬──────────────┘
        │                       │
        ▼                       ▼
  ClickHouse            PostgreSQL (元数据)
  (spans/metrics/logs)  (metric 名 / 告警 / 项目 / DSN)
        ▲
        │ 查询
   Vue.js frontend ◀── Uptrace API
```

compose 内通常还顺带拉起一个 OpenTelemetry Collector（固定版本 contrib）、AlertManager 与 Vector，但真正承载存储与查询的就是上面三个有状态系统。

## Single Binary & OTLP Endpoints (source)

Uptrace 是一个 Go 二进制（`cmd/uptrace`），同时充当 OTLP 接收端与后端 API/查询引擎。监听端口在配置里写死（注意**不是** OTel 默认的 4317/4318）：

```go
conf.Listen.Scheme = "http"
conf.Listen.GRPC.Addr = ":14317"
conf.Listen.HTTP.Addr = ":14318"
```

示例客户端也用同样的端口（`example/kvrocks/main.go`、`example/sentry-go/main.go`）。

gRPC 上的 OTLP 服务在初始化时由 `initOTLP` 注册，一个进程内同时挂 trace / logs 的 gRPC 服务，并通过 `bunrouter` 把 HTTP 入口绑到 `/v1/traces`、`/v1/logs`：

```go
func initOTLP(p OTLPParams, router bunapp.RouterParams) {
	collectortracepb.RegisterTraceServiceServer(p.GRPC, p.TraceServer)
	collectorlogspb.RegisterLogsServiceServer(p.GRPC, p.LogsServer)

	router.Router.POST("/v1/traces", p.TraceServer.ExportHTTP)
	router.Router.POST("/v1/logs", p.LogsServer.ExportHTTP)
}
```

metrics 同类由 `MetricsServiceServer` 提供，它持有一组注入的参数（`PG`、`Projects` 等），并把具体 gRPC 方法的实现留给内嵌的 `collectormetricspb.UnimplementedMetricsServiceServer`：

```go
type MetricsServiceServer struct {
	*MetricsServiceServerParams
	collectormetricspb.UnimplementedMetricsServiceServer
}

func NewMetricsServiceServer(p MetricsServiceServerParams) *MetricsServiceServer {
	return &MetricsServiceServer{MetricsServiceServerParams: &p}
}

var _ collectormetricspb.MetricsServiceServer = (*MetricsServiceServer)(nil)
```

OTLP trace 的摄入有两条入口，但都汇入同一个 `process`：

- **HTTP/JSON 与 protobuf**：`TraceServiceServer.ExportHTTP`（`pkg/tracing/otlp_trace.go`）按 `content-type` 解析 JSON 或 protobuf 的 `ExportTraceServiceRequest`，再调 `process`：
  ```go
  func (s *TraceServiceServer) ExportHTTP(w http.ResponseWriter, req bunrouter.Request) error {
  	ctx := req.Context()

  	dsn, err := org.DSNFromRequest(req)
  	if err != nil {
  		return err
  	}

  	project, err := s.Projects.SelectByDSN(ctx, dsn)
  	if err != nil {
  		return err
  	}

  	switch contentType := req.Header.Get("content-type"); contentType {
  	case jsonContentType:
  		// ... protojson.Unmarshal -> s.process(ctx, project, traceReq.ResourceSpans)
  	case xprotobufContentType, protobufContentType:
  		// ... proto.Unmarshal -> s.process(ctx, project, traceReq.ResourceSpans)
  	default:
  		return fmt.Errorf("unsupported content type: %q", contentType)
  	}
  }
  ```
- **gRPC**：`TraceServiceServer.Export`（`pkg/tracing/otlp_trace.go`）直接收 `ExportTraceServiceRequest`，同样先取 DSN、解析 project，再调 `process`：
  ```go
  func (s *TraceServiceServer) Export(
  	ctx context.Context, req *collectortrace.ExportTraceServiceRequest,
  ) (*collectortrace.ExportTraceServiceResponse, error) {
  	dsn, err := org.DSNFromMetadata(ctx)
  	if err != nil {
  		return nil, err
  	}

  	project, err := s.Projects.SelectByDSN(ctx, dsn)
  	if err != nil {
  		return nil, err
  	}

  	return s.process(ctx, project, req.ResourceSpans)
  }
  ```

两者都先取 DSN（`org.DSNFromRequest` 从 request header / URL 解析，`org.DSNFromMetadata` 从 gRPC metadata 解析），用 `ProjectGateway.SelectByDSN` 解析出 project：

```go
func DSNFromRequest(req bunrouter.Request, extraHeaders ...string) (string, error) {
	if dsn := dsnFromRequest(req, extraHeaders); dsn != "" {
		return dsn, nil
	}
	return "", errors.New("uptrace-dsn header is empty or missing")
}

func DSNFromMetadata(ctx context.Context) (string, error) {
	md, ok := metadata.FromIncomingContext(ctx)
	if !ok {
		return "", errors.New("metadata is empty")
	}
	// ...
}

func (g *ProjectGateway) SelectByDSN(ctx context.Context, dsnStr string) (*Project, error) {
	dsn, err := ParseDSN(dsnStr)
	if err != nil {
		return nil, err
	}

	if dsn.Token == "" {
		return nil, fmt.Errorf("dsn %q does not have a token", dsnStr)
	}
	// ...
}
```

再进入 `process` 把 `ResourceSpans` 转成内部 `Span` 并分发给 `SpanConsumer` / `LogConsumer` / `EventConsumer`。

DSN 既是多租户/多项目的隔离机制，也携带在 OTLP 请求的 URL 或 header 里——这与 [SigNoz](/docs/CS/Distributed/Tracing/SigNoz.md) 用单独 header、[Elastic APM](/docs/CS/Distributed/Tracing/ElasticAPM.md) 用 Managed OTLP Endpoint 的鉴权不同。

## OTLP → Span Model (source)

`initSpanFromOTLP`（`pkg/tracing/otlp.go`）把 OTLP 的 `tracepb.Span` 映射成内部 `Span`：trace/span/parent ID 经 `idgen` 还原，`Start/EndTimeUnixNano` 算 `Time`/`Duration`，`Status` 与 `Kind` 分别经 `otlpStatusCode` / `otlpSpanKind` 转换，资源属性与 span 属性合并进 `Attrs`，events / links 递归转换。也就是说，Uptrace 在摄入侧就把 OTel 语义约定「拍平」成自己的列模型，后续落库与查询都基于该模型：

```go
func initSpanFromOTLP(dest *Span, resource AttrMap, src *tracepb.Span) {
	dest.ID = idgen.SpanIDFromBytes(src.SpanId)
	dest.ParentID = idgen.SpanIDFromBytes(src.ParentSpanId)
	dest.TraceID = idgen.TraceIDFromBytes(src.TraceId)
	dest.Name = src.Name
	dest.Kind = otlpSpanKind(src.Kind)

	dest.Time = time.Unix(0, int64(src.StartTimeUnixNano))
	dest.Duration = time.Duration(src.EndTimeUnixNano - src.StartTimeUnixNano)

	if src.Status != nil {
		dest.StatusCode = otlpStatusCode(src.Status.Code)
		dest.StatusMessage = src.Status.Message
	}

	dest.Attrs = make(AttrMap, len(resource)+len(src.Attributes))
	for k, v := range resource {
		dest.Attrs[k] = v
	}
	otlpconv.ForEachKeyValue(src.Attributes, func(key string, value any) {
		dest.Attrs[key] = value
	})

	dest.Events = make([]*SpanEvent, len(src.Events))
	for i, event := range src.Events {
		dest.Events[i] = newSpanFromOTLPEvent(event)
	}

	dest.Links = make([]*SpanLink, len(src.Links))
	for i, link := range src.Links {
		dest.Links[i] = newSpanLink(link)
	}
}
```

## Storage: ClickHouse + PostgreSQL (source)

Uptrace = **两个有状态系统，不是一个**：

- **ClickHouse**（`pkg/clickhouse/ch`，`InsertQuery` 见 `pkg/clickhouse/ch/query_insert.go`）存遥测主数据。Span 走 `SpanConsumer`（`pkg/tracing/span_consumer.go`），它包的是 `BaseConsumer[SpanIndex, SpanData]`——即每个 span 同时写**两张 CH 表**：`SpanIndex`（索引/聚合列，含 `group_id` 等）与 `SpanData`（完整 span 负载）。`NewSpanConsumer` 的批大小/缓冲/并发全部来自 `p.Conf.Spans.*` 配置，用 `spanTransformer` 把内部 `Span` 投影成这两张表：

  ```go
  type InsertQuery struct {
  	baseQuery
  	selq  *SelectQuery
  	where whereQuery
  	block *Block
  }

  type SpanConsumer struct {
  	*BaseConsumer[SpanIndex, SpanData]
  }

  func NewSpanConsumer(p SpanConsumerParams) *SpanConsumer {
  	batchSize := p.Conf.Spans.BatchSize
  	bufferSize := p.Conf.Spans.BufferSize
  	maxWorkers := p.Conf.Spans.MaxWorkers

  	transformer := &spanTransformer{logger: p.Logger}

  	c := &SpanConsumer{
  		BaseConsumer: NewBaseConsumer[SpanIndex, SpanData](
  			p.Logger,
  			p.PG,
  			p.CH,
  			p.Projects,
  			p.MainQueue,
  			"uptrace.tracing.queue_length",
  			batchSize, bufferSize, maxWorkers,
  		// ...
  ```

  `SpanIndex` 的索引列里就包含 `SpanGroupID`（连同 `SpanSystem`、`SpanKind`、`ServiceName` 等高频过滤列一起常量化声明）：

  ```go
  func init() {
  	commonAttrs := listToSet([]string{
  		attrkey.SpanID,
  		attrkey.SpanTraceID,
  		attrkey.SpanParentID,
  		attrkey.SpanType,
  		attrkey.SpanSystem,
  		attrkey.SpanGroupID,
  		attrkey.SpanKind,
  		attrkey.SpanName,
  		// ...
  ```

  Log / Event 同理经 `LogConsumer` / `EventConsumer`。

- **PostgreSQL**（见 `pkg/org/project.go` 的 `ProjectGateway`）只存元数据：project（含 DSN）、metric 名称、告警定义、用户等。若 Postgres 挂了，ClickHouse 里的 span/metric 还在，但 UI 渲染所需的名称与告警配置会丢失。`ProjectGateway` 持有从配置加载的 projects 列表，并负责按 DSN / ID 解析：

  ```go
  type ProjectGateway struct {
  	*ProjectGatewayParams

  	projects []*Project
  }
  ```

> 这一点与 [SigNoz](/docs/CS/Distributed/Tracing/SigNoz.md)「三信号全落 ClickHouse 单库」不同：Uptrace 把**元数据**明确拆到 Postgres，ClickHouse 只背遥测主体。

## Span Grouping (source)

Uptrace 的「自动 span 分组」不是查询时算的，而是在摄入侧用 **xxhash 内容摘要**固化。`assignSpanSystemAndGroupID`（`pkg/tracing/span_attrs.go`）对每条 span 按类型分支，把系统标识 + 关键属性哈希成 `GroupID`（`uint64`，见 `pkg/tracing/span.go`）：

```go
func (p *consumerWorker[IT, DT]) assignSpanSystemAndGroupID(project *org.Project, span *Span) {
	if s := span.Attrs.Text(attrkey.RPCSystem); s != "" {
		span.Type = TypeSpanRPC
		span.System = TypeSpanRPC + ":" + span.Attrs.ServiceNameOrUnknown()
		span.GroupID = p.spanHash(func(digest *xxhash.Digest) {
			hashSpan(project, digest, span,
				attrkey.RPCSystem,
				attrkey.RPCService,
				attrkey.RPCMethod,
			)
		})
		return
	}

	if s := span.Attrs.Text(attrkey.MessagingSystem); s != "" {
		span.Type = TypeSpanMessaging
		span.System = TypeSpanMessaging + ":" + s
		span.GroupID = p.spanHash(func(digest *xxhash.Digest) {
			hashSpan(project, digest, span,
				attrkey.MessagingSystem,
				attrkey.MessagingOperation,
				attrkey.MessagingDestinationName,
				attrkey.MessagingDestinationKind,
			)
		})
		return
	}
	// ... DB / HTTP / Funcs 分支同理，各自 spanHash 出 GroupID
}

type Span struct {
	// ...
	GroupID uint64 `json:"groupId,string"`
	// ...
}
```

该 `group_id` 进入 `SpanIndex` 的索引列，查询时直接 `WHERE s.group_id = ?` 即可把相似 span/error 归并（`pkg/tracing/type_filter.go`）：

```go
func (f *TypeFilter) whereClause(q *ch.SelectQuery) *ch.SelectQuery {
	q = q.Where("s.project_id = ?", f.ProjectID).
		Where("s.time >= ?", f.TimeGTE).
		Where("s.time < ?", f.TimeLT)

	if f.GroupID != 0 {
		q = q.Where("s.group_id = ?", f.GroupID)
	}

	return f.systemFilter(q)
}
```

分组结果通过 API 暴露：`registerGroupHandler` 把 handler 挂在 `/tracing/:project_id/groups/:group_id`，`ShowSummary` 给单个 group 的聚合视图：

```go
func registerGroupHandler(h *GroupHandler, p bunapp.RouterParams, m *org.Middleware) {
	p.RouterInternalV1.Use(m.UserAndProject).
		WithGroup("/tracing/:project_id/groups/:group_id", func(g *bunrouter.Group) {
			g.GET("", h.ShowSummary)
		})
}
```

这正是 Uptrace 相对 [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md)（纯 trace 可视化）的增量价值：相似问题归并、降噪、突出最影响性能的 issue。

## Metrics Path (source)

指标走 `MetricsServiceServer.ExportHTTP`（`pkg/metrics/otlp.go`），落到 `DatapointProcessor`：

```go
func (s *MetricsServiceServer) ExportHTTP(w http.ResponseWriter, req bunrouter.Request) error {
	ctx := req.Context()

	dsn, err := org.DSNFromRequest(req)
	if err != nil {
		return err
	}

	project, err := s.Projects.SelectByDSN(ctx, dsn)
	if err != nil {
		// ...
	}
	// ... 解析 datapoints 后 s.MP.AddDatapoint(...)
}
```

- `AddDatapoint`（`pkg/metrics/datapoint_processor.go`）先入有界队列，满则丢弃并计数：
  ```go
  func (p *DatapointProcessor) AddDatapoint(ctx context.Context, datapoint *Datapoint) {
  	select {
  	case p.queue <- datapoint:
  	default:
  		p.Logger.Error("datapoint buffer is full (consider increasing metrics.buffer_size)",
  			zap.Int("len", len(p.queue)))
  		datapointCounter.Add(ctx, 1, /* ... type="dropped" */)
  	}
  }
  ```
- `processLoop` 按 `batchSize` 攒批，超时（5s）也刷：
  ```go
  func (p *DatapointProcessor) processLoop(ctx context.Context) {
  	const timeout = 5 * time.Second
  	timer := time.NewTimer(timeout)
  	defer timer.Stop()
  	datapoints := make([]*Datapoint, 0, p.batchSize)
  loop:
  	for {
  		select {
  		case datapoint := <-p.queue:
  			datapoints = append(datapoints, datapoint)
  			if len(datapoints) < p.batchSize {
  				break
  			}
  			p.processDatapoints(ctx, datapoints)
  			datapoints = datapoints[:0]
  		// ...
  ```
- `processDatapoints` → `_processDatapoints` 对每个 datapoint 做 `initDatapoint` + `cumToDelta`（累计→增量归一化）+ `upsertMetric`：
  ```go
  func (p *DatapointProcessor) _processDatapoints(ctx *datapointContext, datapoints []*Datapoint) {
  	for i := len(datapoints) - 1; i >= 0; i-- {
  		dp := datapoints[i]
  		p.initDatapoint(ctx, dp)

  		if !p.cumToDelta(ctx, dp) {
  			// ... 丢弃
  			continue
  		}
  		// ...
  		p.upsertMetric(ctx, dp)

  		if project.PromCompat {
  			dp.Time = dp.Time.Truncate(15 * time.Second)
  		} else {
  			dp.Time = dp.Time.Truncate(time.Minute)
  		}
  	}
  	// ...
  }
  ```
  时间戳按粒度截断：Prometheus 兼容模式 15s，否则 1 分钟。

> [!WARNING]
> 早期资料常说 Uptrace「用 ClickHouse 物化视图聚合指标」。在 v2.0.3 源码里**没有** `MATERIALIZED` 关键字——指标以 datapoint 形式批量写入 ClickHouse，聚合发生在**查询时**经 Uptrace 的 MQL（见 `pkg/metrics/mql`），而非写入时物化。不要照抄「materialized views」的说法。

## OpenTelemetry-native 取向

- **零专有 agent**：只用 OTel SDK / Collector，没有私有协议，迁移后端不必重新埋点。
- **多源摄入**：除 OTel 外，也能从 Prometheus、Vector、FluentBit、CloudWatch 等摄入。
- **自托管无功能阉割**：开源版无 per-host / per-seat 费用，合规场景可纯 on-prem。
- **MCP 接入**：可把 Uptrace 接到任意 MCP 兼容 AI 助手，用自然语言查 trace / 指标 / 告警。

## Uptrace vs SigNoz

| 维度 | Uptrace | [SigNoz](/docs/CS/Distributed/Tracing/SigNoz.md) |
| --- | --- | --- |
| 核心进程 | 单一 Go 二进制 + ClickHouse + Postgres | query-service + OTel Collector + ClickHouse + alertmanager |
| 许可 | AGPL-3.0（开源） | Apache 2.0（社区版） |
| 元数据存 | PostgreSQL（独立） | 同在 ClickHouse |
| OTLP 端口 | 14317(gRPC) / 14318(HTTP) | 4317(gRPC) / 4318(HTTP) |
| 指标聚合 | 查询时 MQL（datapoint 落 CH） | ClickHouse SQL / PromQL / Query Builder |
| 定位 | 极简、低成本 OTel APM | 一体化全功能可观测性（含 exceptions / dashboards） |

两者都证明「OTel + ClickHouse」足以替代商业 APM；差异在工程复杂度和功能广度。

## 关键源码文件（v2.0.3）

想继续深挖，按下面路径直接打开仓库即可（相对 `uptrace-2.0.3/` 根，不再标注行号）：

- **配置与端口**：`pkg/bunconf/config.go`
- **OTLP 接收与摄入**：`pkg/tracing/init.go`、`pkg/tracing/otlp_trace.go`、`pkg/tracing/otlp.go`
- **DSN 与项目解析**：`pkg/org/auth.go`、`pkg/org/project.go`
- **存储与消费**：`pkg/clickhouse/ch/query_insert.go`、`pkg/tracing/span_consumer.go`、`pkg/tracing/span_index.go`
- **Span 分组**：`pkg/tracing/span_attrs.go`、`pkg/tracing/span.go`、`pkg/tracing/type_filter.go`、`pkg/tracing/group_handler.go`
- **指标路径**：`pkg/metrics/otlp.go`、`pkg/metrics/datapoint_processor.go`

## Links

- [SigNoz](/docs/CS/Distributed/Tracing/SigNoz.md) — 同源路线（OTel + ClickHouse）的兄弟 APM（源码级）
- [Elastic APM](/docs/CS/Distributed/Tracing/ElasticAPM.md) — OTel-native 但走 Elasticsearch 的对照（源码级）
- [OpenTelemetry](/docs/CS/Distributed/Tracing/Otel.md) — Uptrace 的采集与数据模型基础
- [Jaeger](/docs/CS/Distributed/Tracing/Jaeger.md) — 纯 trace 后端对照（Uptrace 在其上加了 metrics/logs/alerting+分组）
- [Tempo](/docs/CS/Distributed/Tracing/Tempo.md) — 同为 OTel-native 但「四后端」路线
- [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md) — Uptrace 从 trace 派生 RED 指标的对照基准

## References

- Uptrace documentation：https://uptrace.dev/
- Uptrace — OpenTelemetry APM：https://uptrace.dev/opentelemetry/apm
- Uptrace GitHub（v2.0.3 tag）：https://github.com/uptrace/uptrace/releases/tag/v2.0.3
