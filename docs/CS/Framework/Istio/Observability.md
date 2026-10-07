# Istio Observability

## Introduction

Istio 的可观测性建立在「**每个代理自带完整指标与日志**」这个前提上——不需要业务代码埋点，sidecar 或 waypoint 就能导出全套 RED 指标、分布式追踪与访问日志。但也正因如此，它有两个容易踩的认知误区：**一是以为指标要自己配 Telemetry 才会出现**（默认就有），**二是把 `Telemetry` 当成叠加式配置来写**（实际是完全覆盖）。

版本基线：**Istio 1.31.1**（2026-09-21 发布，1.31.0 于 2026-08-31），官方支持 Kubernetes **1.32 ~ 1.36**。以下默认值与字段名逐条核实自 `istio/istio` 与 `istio/api` 的 `release-1.31` 分支源码、1.31 change-notes 及 istio.io 版本化文档；凡官方未给出的一律标注「未查到」，不凭印象填充。

## Core Mechanism: Three Signals and One Chain

Istio 的可观测性由三个独立信号组成，各自由 `Telemetry` CRD 的一个字段承载：

| 信号 | `Telemetry` 字段 | 内置 provider | 落地形态 |
| :-- | :-- | :-- | :-- |
| 指标 | `metrics` | `prometheus` | 代理 `/stats/prometheus` 端点 |
| 追踪 | `tracing` | **默认无**（需配 Zipkin / OTel 等） | 代理采样后上报 collector |
| 访问日志 | `accessLogging` | `envoy`（file，`/dev/stdout`） | 代理标准输出 |

数据面（Envoy）在请求路径上顺带产出这三类信号，控制面（istiod）只负责**下发采集配置**（哪个 provider、什么采样率、什么日志格式），不中转业务流量。

> [!TIP]
> 装完 Istio 后 `istio_requests_total` 立刻就有了，不需要写任何 `Telemetry` 资源——默认 metrics provider 就是 `prometheus`。`Telemetry` 资源是用来**改**这个默认的，不是用来**开启**它的。

## `Telemetry` Override Semantics (The Easiest Place to Get Wrong)

**`Telemetry` 是完全覆盖（override），不是叠加（additive）。**

官方原文：「Any configuration in a `Telemetry` resource completely overrides configuration of its parent resource in the configuration hierarchy. **This includes provider selection.**」

层级顺序是：root configuration namespace（通常 `istio-system`）→ local namespace（无 selector）→ workload（有 selector）。下层只要写了某个字段，上层同字段就**整个被丢弃**——包括 provider 选择本身。

这带来两个反直觉后果：

- **namespace 级 `customTags` 会让 mesh 级的 `customTags` 整块失效**，而不是合并。官方文档专门举例说明：mesh 级配了 `foo: bar`，namespace 级配了 `userId`，mesh 级的 `foo` 就没了。
- **唯一带「按序叠加」语义的是 `metrics.overrides`**。proto 明确其应用顺序为 1) mesh 级 2) namespace 级 3) workload 级，并建议「从最不具体到最具体排列」。

三条硬约束：

- root configuration namespace 里**任何带 workload selector 的 `Telemetry` 都会被忽略/拒绝**。
- root namespace 里**只能有一个**无 selector 的 mesh 级 `Telemetry`（`It is not valid to define multiple mesh-wide Telemetry API resources`）。
- **selector 不能重复命中**：两个 `Telemetry` 用同一 selector 选到同一 workload 是非法的；同一 namespace 内也不能有两个都省略 selector 的资源。

```yaml
# mesh 级：放在 istio-system，只此一个
apiVersion: telemetry.istio.io/v1
kind: Telemetry
metadata:
  name: mesh-default
  namespace: istio-system
spec:
  tracing:
  - providers:
    - name: otel
    randomSamplingPercentage: 10.0
```

> [!NOTE]
> 官方 task 页的 YAML 里混用了 `telemetry.istio.io/v1` 与 `v1alpha1` 两种 apiVersion。两者**都 served 且 schema 相同**——`v1` 只是 `v1alpha1` 的类型别名（`istio/api` 的 `telemetry/v1/` 目录下唯一文件就是 `telemetry_alias.gen.go`，内容为 `type Telemetry = v1alpha1.Telemetry`）。但 **CRD 的 storage version 是 `v1alpha1`**，落盘与 Go 类型均为 v1alpha1。写 `v1` 没问题，知道这一点即可。

## Metrics: On by Default, But Guard Against Cardinality Explosion

### Four Core HTTP Metrics

`istio-proxy` 默认导出（类型为 Istio 术语，对应 Envoy 的 counter 与 histogram）：

| 指标 | 类型 | 说明 |
| :-- | :-- | :-- |
| `istio_requests_total` | COUNTER | 请求数，**HTTP / HTTP2 / gRPC 共用** |
| `istio_request_duration_milliseconds` | DISTRIBUTION | 耗时（**单位毫秒**），是 histogram 而非 gauge |
| `istio_request_bytes` | DISTRIBUTION | 请求体大小 |
| `istio_response_bytes` | DISTRIBUTION | 响应体大小 |

四者中**没有 gauge**；后三个都是 histogram，**延迟单位是毫秒**（Mixer 时代是秒，迁 Envoy 后变了）。

> [!WARNING]
> 官方 FAQ 明确：**Istio in-proxy telemetry 没有自定义 histogram bucket 的机制**。需要自定义分桶只能在外层（Prometheus recording rules）做。

TCP 与 gRPC 另有独立指标：

- TCP（COUNTER）：`istio_tcp_sent_bytes_total`、`istio_tcp_received_bytes_total`、`istio_tcp_connections_opened_total`、`istio_tcp_connections_closed_total`
- gRPC（COUNTER）：`istio_request_messages_total`（client 发出）、`istio_response_messages_total`（server 发出）

### `reporter` Label: source or destination

这是最高频的查询错误。官方原文：

> "This identifies the reporter of the request. It is set to **`destination`** if report is from a **server** Istio proxy and **`source`** if report is from a client Istio proxy **or a gateway**."

即**网关的 `reporter` 是 `source`，不是 destination**。查「服务端到底处理了多少请求」时若误用 `reporter="source"`，会把网关侧的数字也算进来。

其余关键标签语义：

- `connection_security_policy`：**仅在 destination 侧**上报时为 `mutual_tls`；source 侧上报时因为无法正确填充安全策略，取值 `unknown`。想统计 mTLS 命中率必须用 `reporter="destination"`。
- `response_code`：**仅 HTTP 指标**有。
- `grpc_response_status`：**仅 gRPC 指标**有。它是 HTTP `response_code` 的**替代性**标签而非叠加——gRPC 请求在 `istio_requests_total` 里带的是 `grpc_response_status` 而非 `response_code`。
- `source_principal` / `destination_principal`：启用 PeerAuthentication 后才有值。
- 大量标签在缺失时取**字面量 `unknown`**（如 `source_workload`、`source_app`），不是空串。

### Control Plane Metrics

`pilot_xds_push_time`、`pilot_proxy_convergence_time` 这类来自 `pilot/pkg/xds/monitoring.go`，是判断「配置下发慢」还是「代理收敛慢」的关键：

| 指标 | 类型 | 含义 |
| :-- | :-- | :-- |
| `pilot_xds_push_time` | Distribution | pilot 构建并发送 lds/rds/cds/eds 的总耗时（秒） |
| `pilot_proxy_convergence_time` | Distribution | **配置变更到代理收到全部配置之间的延迟**（秒） |
| `pilot_proxy_queue_time` | Distribution | 配置在代理侧排队时间 |
| `pilot_xds` | Gauge | 当前连到本 pilot 的 xDS 端点数 |
| `pilot_services` | Gauge | pilot 已知的 service 总数 |
| `pilot_xds_pushes` | Sum | 按 `type`（lds/eds/cds/rds_senderr）分组的推送错误数 |
| `pilot_xds_config_size_bytes` | Distribution | 单次推送的配置大小，buckets 上限 40MB |
| `pilot_sds_certificate_errors_total` | Sum | SDS 拉取证书失败的次数 |
| `pilot_debounce_time` | Distribution | 变更去抖延迟 |

> [!TIP]
> 排查「配置改了但没生效」时，`pilot_proxy_convergence_time` 是最有判别力的指标：它大说明控制面下发慢，它小而用户仍看到旧行为，则大概率是 Envoy 侧没应用（如 `PILOT_ENABLE` 相关开关或代理未 ready）。

### High-Cardinality Label: Only `destination_service` Is Named by Officials

FAQ「How can I manage short-lived metrics?」给出的四条途径：

1. **`sidecar.istio.io/statsEvictionInterval` 注解**（1.28.0+）驱逐非活跃 peer 的指标。官方明确其局限：「**will not prevent** Prometheus TSDB index bloat and label churn because Prometheus must still record all the unique values.」
2. **禁用 host header fallback**——`destination_service` 的值在无法确定目标 service 时**默认回落到 host 头**。官方原文警告：「If clients are using a variety of host headers, this could result in a large number of values.」
3. 用 `Telemetry.metricsOverrides` **删掉**无用标签或整条 series。
4. 用 **federation 或 recording rules 归一化**标签值。

> [!WARNING]
> 官方**明确不建议**在 Prometheus 抓取时改写标签来降基数：「Prometheus does not perform aggregation during label rewriting, so dropping labels may create **conflicting series**」。正确做法是用 `Telemetry` 抑制掉不想要的维度。
>
> 另：网络流传的「`request_protocol` 是高基数来源」在官方 FAQ 的高基数讨论中**未被点名**，无官方依据。

生产级方案官方推荐 **hierarchical federation + recording rules**，并给出把 `istio_*` 聚合为 `workload:istio_*` 的现成规则（`sum without(instance, kubernetes_namespace, kubernetes_pod_name)`）。注意 quick-start 安装的 Prometheus **只保留 6 小时**数据。

## Tracing: Off by Default, But Sampling Rate Is 1%

### No Tracing Provider by Default

默认安装**不设** `defaultProviders.tracing`，所以**不会主动上报 span**。但 `meshConfig.enableTracing` 默认为 `true`，采样率配置也在（1%），只是没有 provider 去消费。

内建的三个默认 provider（`DefaultMeshConfig()`）分别是：`prometheus`（metrics）、`stackdriver`（legacy 且有限）、`envoy`（access logging，path `/dev/stdout`）。

### provider Exact Name

`ExtensionProvider.provider` 是 oneof，各类型对应不同字段，**名称容易记错**：

- 追踪：`zipkin` / `datadog` / `stackdriver` / `skywalking` / **`opentelemetry`**（**不是 `otel`**），另有已废弃的 `lightstep` 与 `opencensus`
- 指标：`prometheus`
- 日志：`envoy_file_access_log`（friendly name `envoy`）/ `envoy_http_als` / `envoy_tcp_als` / `envoy_otel_als`

官方支持的追踪后端列表：「OpenTelemetry, Zipkin, SkyWalking, Datadog and Stackdriver」。OTel 是主推协议，Zipkin/SkyWalking 属 legacy。

> [!NOTE]
> **OTel Collector 不能作为 metrics provider**。源码 `pilot/pkg/networking/core/tracing.go` 明确把 `Prometheus` 等归入「不支持 tracing 的 provider」并返回 `provider %T does not support tracing`——它只能出现在 `tracing` 里，不能出现在 `metrics` 里。

### Sampling Rate Defaults to 1%, But Has Two Pitfalls

**坑一：`randomSamplingPercentage` 的 proto 注释写「Defaults to 0%」，而实际生效默认是 1%。** 两者不矛盾，语义层级不同：0% 是「该字段未设置」的 proto 语义，实际值由 pilot 的优先级链决定（`tracing.go`）：

```
provider.sampler > Telemetry.randomSamplingPercentage > defaultConfig.tracing.sampling > PILOT_TRACE_SAMPLING
```

`PILOT_TRACE_SAMPLING` 默认 `1.0`，`ProxyConfig.Tracing.sampling` 的注释也写「Default is 1.0.」，Helm `values.yaml` 的 `traceSampling: 1.0`——三处独立佐证。

**坑二：配了自定义 sampler 时，Istio 侧采样率被强制设为 100。** 源码注释：「so all spans arrive at the sampler for its decision」——全部 span 发给 sampler 由它决策。由此可推：若要用 Collector 做 tail-based sampling，Istio 侧必须设 100%，代价是 Envoy→Collector 流量显著上升。（官方未给出量化的性能影响数据。）

### B3 Still Default, W3C Requires Explicit Enablement

`ZipkinTracingProvider` 的 `traceContextOption`：

- `USE_B3`（**默认**）——proto 注释：「The default value is USE_B3 to maintain backward compatibility」
- `USE_B3_WITH_W3C_PROPAGATION`——**1.31 新增**。下游优先提取 B3、回退 W3C `traceparent`；上游同时注入 B3 与 W3C 头

> [!WARNING]
> **`PILOT_ENABLE_W3C_TRACE_CONTEXT` 这个环境变量在 1.31 已不存在。** 对 `pilot/pkg/features/telemetry.go` 全量扫描确认，telemetry 相关 flag 只有 `PILOT_TRACE_SAMPLING`、`PILOT_ENABLE_TELEMETRY_LABEL`、`PILOT_ENDPOINT_TELEMETRY_LABEL`、`PILOT_ENABLE_METADATA_EXCHANGE`、`PILOT_MX_ADDITIONAL_LABELS`、`ISTIO_ENABLE_CONTROLLER_QUEUE_METRICS`、`PILOT_AGENT_MERGE_ENVOY_STATS`。想开 W3C 得用 `TraceContextOption` 字段。

**应用需要转发的头**（官方明确列出）：所有应用都应转发 `x-request-id`、`traceparent`、`tracestate`；Zipkin 额外需 `x-b3-traceid`、`x-b3-spanid`、`x-b3-parentspanid`、`x-b3-sampled`、`x-b3-flags`。

采样决策会随头传播：`randomSamplingPercentage` 的注释说，若上游已有采样决策则尊重之，只有在没有决策时才重新采样。

1.31 新增 `Tracing.disableContextPropagation`（默认 false）：置 true 后不再向上游注入 `traceparent`/`tracestate`/`X-B3-*`，**用于 egress gateway 防信息泄漏**，不影响 span 上报。

### OpenTelemetry Integration

支持 **OTLP over gRPC 或 HTTP**，由 `OpenTelemetryTracingProvider.grpc` / `.http` 配置，**两者只能配一个**（proto 与官方 task 页都明确「Only one exporter can be configured at a time」），未设时走 gRPC。

1.31 还新增了 **Dynatrace 自适应采样器**（`dynatraceSampler`，`rootSpansPerMinute` 未设或为 0 时默认 1000）。

## Access Log

### meshConfig Two Fields with Two Different Defaults

字段在 **`MeshConfig`**（不是 `ProxyConfig`）上，1.31 中**均无 `[deprecated = true]` 标记**，官方参考页也未标 DEPRECATED——所以「已废弃」在 1.31 查不到官方依据，只是实践上已被 Telemetry/provider 机制取代。

| 字段 | 实际默认值 | 含义 |
| :-- | :-- | :-- |
| `accessLogFile` | **`""`（空）** | 空值**禁用**访问日志 |
| `accessLogFormat` | `""` | 空值=用代理默认格式 |
| `accessLogEncoding` | `TEXT` | 枚举 `TEXT=0` / `JSON=1` |
| `disableEnvoyListenerLog` | `false` | Istio 仅在 `NoRoute` 响应标志时开 listener log |

> [!WARNING]
> **`accessLogFile` 默认是空串，不是 `/dev/stdout`。** `/dev/stdout` 是内置 `envoy` **provider** 的 `path` 默认值（`EnvoyFileAccessLogProvider.path`）。两者是**不同层级的默认值**，混为一谈会导致「我配了 accessLogFile 为什么没生效」这类误判——因为默认安装时日志是由 provider 输出的，`accessLogFile` 那条路径根本没启用。

> [!NOTE]
> **`ProxyConfig` 里不存在 `accessLogFile` / `accessLogFormat`**。`ProxyConfig` 中与日志/追踪相关的字段只有 `Tracing tracing`、`RemoteService envoy_access_log_service`、`RemoteService envoy_metrics_service`。

默认 text 格式串（`EnvoyTextLogFormat` 常量）为：

```
[%START_TIME%] "%REQ(:METHOD)% %REQ(X-ENVOY-ORIGINAL-PATH?:PATH)% %PROTOCOL%" %RESPONSE_CODE%
%RESPONSE_FLAGS% %RESPONSE_CODE_DETAILS% %CONNECTION_TERMINATION_DETAILS%
"%UPSTREAM_TRANSPORT_FAILURE_REASON%" %BYTES_RECEIVED% %BYTES_SENT% %DURATION%
%RESP(X-ENVOY-UPSTREAM-SERVICE-TIME)% "%REQ(X-FORWARDED-FOR)%" "%REQ(USER-AGENT)%"
"%REQ(X-REQUEST-ID)%" "%REQ(:AUTHORITY)%" "%UPSTREAM_HOST%" %UPSTREAM_CLUSTER_RAW%
%UPSTREAM_LOCAL_ADDRESS% %DOWNSTREAM_LOCAL_ADDRESS% %DOWNSTREAM_REMOTE_ADDRESS%
%REQUESTED_SERVER_NAME% %ROUTE_NAME%
```

> [!WARNING]
> **默认格式是 `text`，不是 json。** `EnvoyFileAccessLogProvider.LogFormat` 是 oneof（`text` / `labels`），`LogFormat == nil` 时走 `buildFileAccessTextLogFormat("")` 返回 text 常量。要 JSON 得显式写 `labels: {}`（表示用 Envoy 默认 JSON 结构，共 24 个 key）。Istio 会在缺失时补 `\n`。

`EnvoyFileAccessLogProvider` 字段：`path`（默认 `/dev/stdout`）、`log_format`（oneof）、`omit_empty_values`（text 模式下空值由 `-` 改为空串；json 模式下省略 null key）。当前支持的自定义 formatter 只有 3 个：`%CEL`、`%METADATA`、`%REQ_WITHOUT_QUERY`。

### Conditional Log Toggle via `filter` (CEL)

字段路径 `spec.accessLogging[].filter.expression`，官方给的表达式示例：

```yaml
# 只记 5xx
filter:
  expression: "response.code >= 500"

# 连接失败时没有 response.code，必须容错
filter:
  expression: "!has(response.code) || response.code >= 500"

# mesh 级：把黑洞与透传也记下来
filter:
  expression: "response.code >= 400 || xds.cluster_name == 'BlackHoleCluster' || xds.cluster_name == 'PassthroughCluster' "

# 过滤健康检查（request.useragent 仅 HTTP 有，需 has 保护以免破坏 TCP）
filter:
  expression: "!has(request.useragent) || !(request.useragent.startsWith(\"Amazon-Route53-Health-Check-Service\"))"
```

> [!TIP]
> `match.mode` 只能按 `CLIENT` / `SERVER` / `CLIENT_AND_SERVER` 粗粒度分流，**做不到按状态码分流**——那种需求必须用 `filter`。

## Peripheral Tools and 1.31 Changes

### Prometheus Scraping: Merged Endpoints and New Annotations

默认**指标合并是开启的**（`enablePrometheusMerge` 默认 `true`），合并端点为 **`:15020/stats/prometheus`**。单个 pod 可用 `prometheus.istio.io/merge-metrics: "false"` 关闭。

1.31 的新增能力：

- **`prometheus.istio.io/scrape-targets` 注解**——值为逗号分隔的 `port:path` 列表，pilot-agent 并发抓取并**按声明顺序合并**。与 agent status 端口或 Istio 保留数据面端口冲突的目标**在注入时报可读错误**。单目标 pod 走原有流式路径且逐字节不变；多目标时重写 OpenMetrics 响应以保证**恰好一个 `# EOF`**。
- **`ENVOY_SECURE_METRICS_PORT` / `ENVOY_SECURE_MERGED_METRICS_PORT`**——opt-in，为每个 sidecar 暴露 mTLS 保护的抓取端点（静态 bootstrap listener 要求 mTLS）。

> [!NOTE]
> 1.31 **没有**出现「Prometheus 抓取配置从 `kubernetes-pod-endpoints` 改为 `pod-scrape-configs`」这类改名——`samples/addons/prometheus.yaml` 全文不含这两个名称（该文件是 prometheus-community chart 的渲染产物，1.31 用的是 `kubernetes-pods` job）。istiod 的抓取 job 名为 `istiod`，Envoy 为 `envoy-stats`，靠 `__meta_kubernetes_endpoint_port_name` 匹配。全局默认 `scrape_interval: 15s`、`scrape_timeout: 10s`、`evaluation_interval: 1m`。

### Kiali and Grafana

`samples/addons` **未废弃**，1.31 仍在用，含 `grafana.yaml`、`jaeger.yaml`、`kiali.yaml`、`loki.yaml`、`prometheus.yaml`、`zipkin.yaml`、`skywalking.yaml`，以及 `extras/` 下的 `prometheus-operator.yaml` 与 1.31 新增的 `prometheus-secure-metrics.yaml`。

> [!WARNING]
> **Kiali 版本号三处不一致**（写笔记/部署时务必以实际 tag 为准）：change-notes 与 announcing 页都写「Updated Kiali addon to version **v2.26.0**」，但 `samples/addons/kiali.yaml` 在 **1.31.0 tag 是 `v2.27`**，**1.31.1 tag 是 `v2.31`**（`app.kubernetes.io/version: v2.31.0`）。**release note 落后于实际 manifest。**

Grafana dashboards 由 jsonnet + helm template 生成到 `manifests/addons/dashboards/*.gen.json`，共 7 个：`pilot-dashboard`、`ztunnel-dashboard`、`istio-performance-dashboard`、`istio-workload-dashboard`、`istio-service-dashboard`、`istio-mesh-dashboard`、`istio-extension-dashboard`，并拆成两个 ConfigMap 以避开 K8s size 限制。

### 1.31 Observability Changes Overview

**新增**：多目标 Prometheus 抓取注解；两个安全指标端口环境变量；`istio_cni_plugin_requests_total{response_code}`（CNI add 事件计数）；`istio_agent_scrape_failures_total{type="application"}`；Zipkin `TraceContextOption`；Dynatrace sampler。

**改进**：pilot-agent `/stats/prometheus` 并发抓取多目标并按序合并；**单目标响应上限 10 MiB**，超限丢弃并计为抓取失败；单目标失败不阻塞其他目标。

**修复**：pilot-agent 在 Envoy 用 **protobuf content type** 上报时合并结果错误——现将允许的 content type 限制为 `text/plain` 与 `application/openmetrics-text`；跨 namespace 的 waypoint `Service` 未把 namespace 级 `Telemetry` 纳入配置。

**移除**：

- **`PILOT_SPAWN_UPSTREAM_SPAN_FOR_GATEWAY` 已移除**——gateway 请求生成 upstream span 现为**始终启用**，原设 `false` 的配置不再有任何作用。
- **`PILOT_ENABLE_ISTIO_TAGS` 已移除**——功能由 `Telemetry` 的 `enableIstioTags` 字段承载（默认 true）。

## Troubleshooting Quick Reference

| 现象 | 先查 |
| :-- | :-- |
| 指标没出现 | 默认就有，先查抓取端点是否可达（`:15020/stats/prometheus`）；确认是否被 `metricsOverrides` 误关 |
| 指标条数爆炸 | `destination_service` 是否回落到了 host 头；用 `Telemetry` 抑制维度，**不要**在 Prometheus 抓取时改标签 |
| 服务端请求数对不上 | `reporter` 该用 `destination`；网关的 `reporter` 是 `source` |
| mTLS 命中率算不对 | `connection_security_policy` 只在 `reporter="destination"` 时才有效，source 侧恒为 `unknown` |
| 没有 trace | 默认**就没有** tracing provider，须配 `Telemetry.tracing.providers` |
| 采样率设了不生效 | 检查是否配了自定义 sampler（会强制 100）；确认优先级链顺序 |
| W3C 传播没开 | 用 `TraceContextOption: USE_B3_WITH_W3C_PROPAGATION`，`PILOT_ENABLE_W3C_TRACE_CONTEXT` 已移除 |
| 日志是纯文本不是 JSON | 默认就是 `text`，要 JSON 得显式写 `log_format.labels: {}` |
| 配了 `accessLogFile` 无效 | 默认 `""`（禁用）；`/dev/stdout` 是 `envoy` provider 的 `path` 默认值，两者是不同层级 |
| 5xx 日志漏记 | 失败时可能没有 `response.code`，表达式要加 `!has(response.code) \|\|` |
| 配置改了不生效 | 看 `pilot_proxy_convergence_time`：大=控制面慢，小=代理侧未应用 |

## Links

- [Istio](/docs/CS/Framework/Istio/Istio.md)
- [Envoy](/docs/CS/Framework/Istio/Envoy.md)
- [Security](/docs/CS/Framework/Istio/Security.md)
- [TrafficManagement](/docs/CS/Framework/Istio/TrafficManagement.md)
- [Ambient](/docs/CS/Framework/Istio/Ambient.md)
- [Kubernetes](/docs/CS/Container/k8s/K8s.md)

## References

- <https://istio.io/v1.31/docs/tasks/observability/telemetry/>
- <https://istio.io/v1.31/docs/reference/config/metrics/>
- <https://istio.io/v1.31/docs/ops/best-practices/observability/>
- <https://istio.io/v1.31/docs/ops/integrations/prometheus/>
- <https://istio.io/v1.31/docs/tasks/observability/logs/telemetry-api/>
- <https://istio.io/v1.31/news/releases/1.31.x/announcing-1.31/change-notes/>
- <https://api.github.com/repos/istio/istio/releases/latest>
