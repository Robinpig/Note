## Introduction

Higress 的观测配置分散在三个地方——Helm values、ConfigMap `higress-config`、以及数据面端口本身——这是它经常被写错的根本原因。通用三支柱在这一页；AI 流量的 token 计量与成本核算跟着 `ai-statistics` 写在 [AI Gateway](/docs/CS/Framework/Higress/AI_Gateway.md)，因为那组指标与限流、配额是共生关系，拆开就看不出"缓存命中绕过配额"这类后果。

## Metrics

**指标端口是 15020，路径是 `/stats/prometheus`。** Helm 默认给 Gateway Pod 打的注解是：

| 注解 | 默认值 |
| --- | --- |
| `prometheus.io/scrape` | `true` |
| `prometheus.io/port` | **15020** |
| `prometheus.io/path` | `/stats/prometheus` |

15020 有三处交叉印证：`higress-core.gateway.podAnnotations.prometheus.io/port`、`hgctl` 安装 values 里的 `metricsPort: 15020 # gateway 指标输出监听端口`、以及独立部署脚本的 `--gateway-metrics-port` 默认 15020。

> [!WARNING]
> 两条**流传很广但没有一手出处**的说法，本页不写：① 指标端口"15020 与 15090"——本次取到正文的全部 Higress 文档里 15090 **零命中**（不能排除它出现在未抓取的页面或企业版文档里，但至少文档口径只支持 15020）；② "可通过某个开关启用精简指标（LITE_METRICS）以降低基数"——`user/configurations`、`user/configmap`、`user/prometheus`、`ops/*` 正文里既无"精简"也无对应字段。文档里唯一与"指标瘦身"字面近似的是 `higress-core.meshConfig.enablePrometheusMerge`（默认 true），但它的语义是**多代理指标合并聚合**，不是瘦身开关，两者不能混用。

接入方式两条路。装内置套件：`--set global.o11y.enabled=true`，会一并安装 **Grafana、Prometheus、Loki、PromTail**，装完在 Console 左侧"监控面板"直接看；控制台侧的资源规格由 `higress-console.o11y.grafana.*` 与 `higress-console.o11y.prometheus.*` 决定（replicas 默认 1、storage 默认 1Gi、Prometheus 限额 500m / 2Gi）。用外部套件：数据面与控制面都通过 API 暴露 Metrics，**在未安装内置套件时，Console 的"监控面板"页面会展示外置监控面板 URL 配置页与对接方法**——按页面下方方法更新 Prometheus / Grafana 配置后，把 Grafana 看板 URL 填回输入框保存即可自动刷新（要改 URL 点页面左上角"重新配置"）。

## Access Log

访问日志格式改的是 ConfigMap `higress-config` 里 **`mesh` 字段下的 `accessLogFormat`**：

```bash
kubectl edit cm -n higress-system higress-config          # 改格式
kubectl logs -n higress-system -l app=higress-gateway --since=5m   # 查看
```

默认格式是 **JSON**，共 23 个字段（括号内是 Envoy 变量原文，可据此自定义）：`authority`（`:AUTHORITY`）、`bytes_received`、`bytes_sent`、`downstream_local_address`（网关 Pod 地址）、`downstream_remote_address`（客户端地址）、`duration`（整体耗时）、`method`、`path`（`X-ENVOY-ORIGINAL-PATH?:PATH`）、`protocol`、`request_id`（`X-REQUEST-ID`）、`requested_server_name`（SSL 连接时使用的 Server Name，可用于按域名核对 SNI 命中）、`response_code`、`response_flags`（响应失败原因）、`route_name`、`start_time`、`trace_id`（`X-B3-TRACEID`）、`upstream_cluster`、`upstream_host`、`upstream_local_address`、`upstream_service_time`（`X-ENVOY-UPSTREAM-SERVICE-TIME`）、`upstream_transport_failure_reason`、`user_agent`、`x_forwarded_for`。

`request_id` 值得单独强调：**网关为每次请求生成并放入 `x-request-id`，后端可据此串联排查**——这是没有启用分布式追踪时唯一可用的关联键。另一条容易误读的是 `trace_id` 取的是 `X-B3-TRACEID`，即 **B3 单头格式**；使用 OpenTelemetry 上下文传播时该字段是否会命中需自行核实，不要照抄成"自动就是 W3C traceparent"。

## Tracing

追踪配置在 ConfigMap `higress-config` 的 **`higress.tracing`** 段（注意：不是 Helm values 主路径）：

```yaml
tracing:
  enable: false        # 默认关闭
  sampling: 100        # 0.0 - 100.0，默认 100.0
  timeout: 500         # 链路跟踪中间件 gRPC 连接超时，毫秒
  skywalking: { service: <FQDN>, port: <p>, access_token: <t> }
  # 或 zipkin: { service, port }
  # 或 opentelemetry: { service, port }
```

后端支持 **Skywalking、Zipkin、OpenTelemetry** 三种，官方注意事项原文是"**不能同时设置，只有一个配置能生效**"。服务名的写法与服务列表 FQDN 一致（如 `my-server.dns`），也就是**追踪后端自己也要先注册成服务来源**（原因见 [Wasm Development](/docs/CS/Framework/Higress/Wasm_Development.md) 的 cluster 寻址）。另有 Helm 级参数 `higress-core.pilot.traceSampling`（默认 `1`，页面注释为 1.0 即 100%）——**两处都能碰采样，配置时要以 `higress-config` 的 `tracing.sampling` 为运行时准，Helm 值只在安装 / 升级时生效**。Skywalking 单独有一组 values：`higress-core.skywalking.enabled`（默认 false）、`service.address`、`service.port`（默认 11800）。

追踪的通用原理与 Envoy 侧配置在 [Observability](/docs/CS/Framework/Istio/Observability.md)（Istio 子树），本页只记 Higress 的入口与默认值。

## Observability-Adjacent Knobs

`higress-config` 里还有两个直接影响"你能看到什么"的开关：`addXRealIpHeader`（默认 false，追加 `x-real-ip`）与 `disableXEnvoyHeaders`（默认 false，关闭 `x-envoy-*` 附加头）。排查链路时这两个默认值意味着：**上游转发过来的 `x-forwarded-for` 之外的真实源信息，默认不会被补上**。

命令行侧有个便利入口：`hgctl dashboard` 可以直接打开 Higress Console、Higress Controller Debug 界面、Envoy 管理界面、Grafana 与 Prometheus 管理界面（子命令含 `envoy`、`prometheus`，`--browser` 默认 true）。它与"配置到底生效到哪一层"的四段排障链一起在 [Deployment and Ops](/docs/CS/Framework/Higress/Deployment_and_Ops.md)。

## Unverified

`llms.txt` 索引里**没有**独立的 metrics / tracing / observability / access-log 页面，三支柱的权威落点因此分别是 `user/configurations` + `user/prometheus`（指标）、`ops/log`（访问日志）、`user/configmap`（追踪）——若别处链向 `.../user/metrics/` 一类路径，那些 URL 本次取不到正文。此外未核实：是否存在高基数标签裁剪或精简指标开关（可能在源码或控制台里，不得写具体字段名）；15090 是否出现在未抓取的页面；内置 o11y 套件各组件的版本与看板内容清单；AI 监控面板的底层数据源是否就是 `ai-statistics` 指标（方向合理但文档未给明确语句）。

## Links

- [AI Gateway](/docs/CS/Framework/Higress/AI_Gateway.md)
- [Deployment and Ops](/docs/CS/Framework/Higress/Deployment_and_Ops.md)
- [Wasm Development](/docs/CS/Framework/Higress/Wasm_Development.md)
- [Observability](/docs/CS/Framework/Istio/Observability.md)
- [Envoy](/docs/CS/Framework/Istio/Envoy.md)
- [Higress](/docs/CS/Framework/Higress/Higress.md)
- [Config Pipeline](/docs/CS/Framework/Higress/Config_Pipeline.md)
- [Certificates and ACME](/docs/CS/Framework/Higress/Certificates_and_ACME.md)

## References

- [Higress 参数配置](https://higress.ai/docs/latest/user/configurations/)
- [全局配置说明](https://higress.ai/docs/latest/user/configmap/)
- [基于 Prometheus 实现入口流量观测](https://higress.ai/docs/latest/user/prometheus/)
- [日志说明](https://higress.ai/docs/latest/ops/log/)
- [使用 Helm 进行云原生部署](https://higress.ai/docs/latest/ops/deploy-by-helm/)
- [hgctl 工具使用说明](https://higress.ai/docs/latest/ops/hgctl/)
