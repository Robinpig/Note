## Introduction

云原生的可观测性不是"装一个监控面板"，而是三条独立管线加一类事件流：

| 管线 | 回答的问题 | 数据形态 | 典型组件 |
|---|---|---|---|
| Metrics | 现在/趋势怎么样？ | 数值 + 标签 + 时间戳 | cAdvisor、kubelet、metrics-server、Prometheus |
| Logs | 当时发生了什么？ | 按时间追加的文本 | 容器运行时、日志采集 DaemonSet、Loki/ES |
| Traces | 一次请求慢在哪一段？ | 跨服务的 span 树 | OpenTelemetry SDK/Collector、Jaeger/Tempo |
| Events | 集群对象经历了什么？ | 结构化事件对象 | apiserver、controller、kubelet |

四条线的采集点、存储位置、保留策略完全不同。把它们混在一起排查，是云原生故障定位最常见的误区——例如"Pod 内存高"应该看 metrics，"Pod 为什么重启"应该看 events + previous logs，"请求为什么慢"才需要 traces。

> [!NOTE]
> 本文的 K8s 侧事实基于 **v1.36.4** 源码；metrics-server 侧基于当前主线（`/metrics/resource` 抓取路径），OTLP 端口来自 OpenTelemetry 规范。K8s 自身只提供"原料"，完整栈由 Prometheus、OTel Collector、日志后端等外部组件拼装。

## Metrics: From cAdvisor to HPA

### What kubelet Exposes

kubelet 是节点上最大的指标源，但它的 HTTP 端点不止一个，语义完全不同：

| 端点 | 内容 | 主要消费者 | 源码 |
|---|---|---|---|
| `/metrics` | kubelet 组件自身指标（PLEG、runtime、volume、API 调用） | Prometheus | `pkg/kubelet/server/server.go:109` |
| `/metrics/cadvisor` | 容器 CPU/内存/磁盘/网络/PSI 等资源指标 | Prometheus | `server.go:110` |
| `/metrics/resource` | 面向资源核算的 Pod/容器指标（CPU、内存、启动时间） | metrics-server | `server.go:111` |
| `/metrics/probes` | 探针执行结果 | Prometheus | `server.go:112` |
| `/stats/summary` | JSON 格式的节点/Pod/容器汇总 | 旧版 metrics-server、调试 | `server.go:113`、`stats/handler.go:122` |

cAdvisor 以库的形式嵌在 kubelet 里（`github.com/google/cadvisor`），不是独立进程；因此节点上找不到 `cadvisor` 服务，指标直接从 kubelet 的 `/metrics/cadvisor` 取。PSI（Pressure Stall Information）指标在 v1.36 已 GA 并锁定（`pkg/features/kube_features.go:1602-1605`），能反映 CPU/内存/IO 的**等待压力**，比单纯利用率更接近"卡不卡"。

> [!WARNING]
> kubelet 的这些端点默认走 **kubelet 的认证/授权**，不是匿名可抓的。Prometheus 需要配置 bearer token + CA，或通过 apiserver 代理 `/api/v1/nodes/<node>/proxy/metrics`。直接把 kubelet 端口暴露到公网是严重安全问题。

### metrics-server Is Not Prometheus

metrics-server 只解决一件事：给 HPA 和 `kubectl top` 提供**近实时资源用量**。它不存储历史、不做查询语言、不报警。

当前 metrics-server 对每个节点请求的是：

```
GET https://<node>:10250/metrics/resource
```

（`pkg/scraper/client/resource/client.go:86-107`，可通过节点注解覆盖路径）。拿到后聚合成 `metrics.k8s.io/v1beta1` 的 `NodeMetrics` / `PodMetrics`，再通过 **APIService** 注册为聚合 API：

```bash
kubectl get --raw /apis/metrics.k8s.io/v1beta1/nodes
kubectl top node
kubectl top pod -A --sort-by=memory
```

这也解释了两个常见问题：

- `kubectl top` 报 `Metrics API not available` → 先看 `kubectl get apiservice v1beta1.metrics.k8s.io` 的 `Available`，聚合层探测逻辑见 [扩展机制](/docs/CS/Container/k8s/Extension.md?id=availability-is-probed-not-assumed)；
- metrics-server 只保留最近约一分钟的数据点，**历史趋势和告警必须用 Prometheus**，不能拿 `kubectl top` 当监控。

### The Three Metrics APIs

HPA 可以消费三类指标，分别由不同 APIService 提供：

| API group | 内容 | 提供方 | HPA 用法 |
|---|---|---|---|
| `metrics.k8s.io` | Pod/Node 的 CPU、内存 | metrics-server | `type: Resource` |
| `custom.metrics.k8s.io` | 任意对象关联的指标（QPS、队列长度） | Prometheus Adapter / KEDA | `type: Pods` / `Object` |
| `external.metrics.k8s.io` | 集群外指标（云队列、LB） | 云厂商 adapter | `type: External` |

`type: Resource` 的利用率是**相对 requests** 算的：没有设置 requests 的容器不会参与平均利用率，HPA 会显示 `<unknown>`。这也是"HPA 不扩容"最常见的原因，细节见 [扩缩容](/docs/CS/Container/k8s/Scaling.md)。

### Full Prometheus Stack

生产级指标栈通常是分层拼装：

```
node-exporter（主机 CPU/内存/磁盘/网络）
      │
cAdvisor / kubelet（容器与 Pod 资源）
      │                         ┌── Prometheus ──► 长期存储（Thanos/Mimir）
kube-state-metrics（对象状态）──┤
      │                         └── Alertmanager ──► 通知
apiserver / scheduler / controller-manager（控制面自身指标）
```

- **kube-state-metrics** 监听 apiserver，把 Deployment 副本数、Pod phase、PVC 状态这类**对象状态**转成指标；它不采集资源用量，和 cAdvisor 是互补关系。
- **Prometheus Operator** 用 CRD 管理抓取配置：`ServiceMonitor` / `PodMonitor` 通过 label selector 选中 Service/Pod，`PrometheusRule` 定义告警规则，`Alertmanager` 管理告警路由（CRD 清单见 Prometheus Operator 文档）。
- **Prometheus 的拉模型**要求目标可被 Prometheus 访问；跨集群/跨网络时通常用 `federate`、remote write 或 Prometheus Agent。

一个 `ServiceMonitor` 的核心就是"选谁 + 抓哪个端口 + 多久一次"：

```yaml
apiVersion: monitoring.coreos.com/v1
kind: ServiceMonitor
metadata:
  name: my-app
  labels: {release: kube-prometheus-stack}
spec:
  selector:
    matchLabels: {app: my-app}
  endpoints:
  - port: metrics
    interval: 30s
    path: /metrics
```

`selector` 选的是 **Service 的 label**，不是 Pod 的 label；Service 的 `ports[].name` 必须与 `endpoints[].port` 对上，否则 target 不会出现。这是 ServiceMonitor "创建成功但没数据"的首要原因。

### Metrics Stability

K8s 组件指标有稳定性分级（ALPHA/BETA/STABLE），废弃指标默认隐藏；排查"升级后看板空了"时，先用 `--show-hidden-metrics-for-version=<old-version>` 把旧指标放出来，再按官方迁移表改名。不要依赖未声明稳定性的指标做长期告警。

## Logs: Files, Rotation, Collection

### Where Container Logs Live

K8s 不实现日志驱动协议，容器日志由**容器运行时**写到节点文件系统。kubelet 只负责约定目录与轮转。路径规则：

```
/var/log/pods/<namespace>_<pod-name>_<pod-uid>/<container-name>/<restart-count>.log
```

目录构造见 `pkg/kubelet/kuberuntime/helpers.go:217-226`，根目录默认 `/var/log/pods`（`cmd/kubelet/app/options/options.go:42`）。每个容器每次重启对应一个递增编号的文件，这就是 `kubectl logs --previous` 能拿到"上一次崩溃日志"的原因。

`kubectl logs` 的链路是：

```
kubectl → apiserver → kubelet /containerLogs/... → CRI 运行时读取日志文件 → 流式返回
```

所以 `kubectl logs` 看不到日志通常不是"日志没打"，而是：Pod 不在该节点、容器还没启动、日志已被轮转、或 kubelet 与运行时通信异常。

### Rotation Defaults

kubelet 负责轮转（`pkg/kubelet/apis/config/v1beta1/defaults.go:258-262`）：

| 参数 | 默认 | 含义 |
|---|---|---|
| `containerLogMaxSize` | `10Mi` | 单个日志文件上限 |
| `containerLogMaxFiles` | `5` | 每个容器保留的文件数 |
| `containerLogMaxWorkers` | 1 | 并发轮转 worker 数 |
| `containerLogMonitorInterval` | 10s | 检查文件大小的周期 |

默认配置下，一个容器最多占约 **50Mi** 日志空间。突发大量日志时，旧文件会被删掉——这正是"故障发生后日志刚好缺失"的常见原因。对关键服务应同时做**集中采集**，不要依赖节点本地文件。

`kubectl logs` 读的是 kubelet 路径，**不会**自动去日志后端查历史；Pod 被删除后，`kubectl logs` 就永久失效，历史只能在 Loki/ES 里找。

### Cluster-Level Collection

集中采集的标准形态是 DaemonSet：

```
容器 stdout/stderr
   → 运行时写 /var/log/pods/...
   → 采集 agent（Fluent Bit / Vector / Promtail）tail 文件
   → 富化（namespace/pod/labels/node）
   → 后端（Loki / Elasticsearch / ClickHouse）
```

三种采集位置各有取舍：

| 方式 | 优点 | 缺点 |
|---|---|---|
| DaemonSet tail 节点文件 | 不依赖应用，能收所有容器 | 需要 hostPath 权限；轮转窗口内必须追上 |
| 应用直接推送到后端 | 低延迟、可带结构化字段 | 每语言接 SDK；网络故障可能丢日志 |
| Sidecar 采集 | 隔离性好、可按 Pod 配置 | 资源开销翻倍、Pod 生命周期耦合 |

生产建议：**DaemonSet 兜底 + 应用结构化日志**。DaemonSet 保证不丢系统组件日志，应用侧用 JSON 输出关键字段，避免后端用正则硬解析。

### Logs vs Events

Events 不是日志：

- 它们由 apiserver 存储（`events.k8s.io/v1`），有保留时限与数量限制；
- 记录的是**对象状态变更**（调度、拉镜像、探针失败、驱逐），不是应用输出；
- `kubectl describe` 展示的是 Events，`kubectl logs` 展示的是容器 stdout/stderr。

排障顺序通常是 **describe（看 Events）→ logs（看应用）→ 组件日志（看 kubelet/controller）**，完整案例见 [常见问题排查](/docs/CS/Container/k8s/Issues.md)。

## Traces: Request-Level Visibility

Metrics 告诉你"P99 变高了"，traces 告诉你"这 800ms 花在哪个下游"。K8s 本身不产生业务 trace，但提供了两层基础能力。

### Application Instrumentation

应用通过 OpenTelemetry SDK 埋点，将 span 以 OTLP 导出：

| 协议 | 默认端口 |
|---|---|
| OTLP/gRPC | 4317 |
| OTLP/HTTP | 4318 |

Collector 通常以两种形态部署：

- **Agent（DaemonSet）**：每节点一个，应用发到 localhost/节点 IP，减少跨节点流量；
- **Gateway（Deployment）**：集中做采样、批处理、脱敏、路由到多个后端。

采样要在源头做（head sampling）或由 Collector 做尾部采样（tail sampling）；全量采集在高 QPS 下成本不可接受。跨服务传播使用 W3C Trace Context（`traceparent` / `tracestate`），网关、服务网格、消息队列都要透传，否则 trace 会在中间断开。

### Kubernetes Control-Plane Tracing

K8s 组件自己也能导出 trace：

- `APIServerTracing` 在 v1.34 GA 并锁定（`staging/src/k8s.io/apiserver/pkg/features/kube_features.go:345-349`）；
- `KubeletTracing` 同样在 v1.34 GA（`pkg/features/kube_features.go:1640-1644`）。

apiserver 通过 `--tracing-config-file` 指定 endpoint、采样率与 span 属性；kubelet 也支持 OTLP 导出。它们能回答"这个 LIST 请求在 apiserver 内部花了多久、在 etcd 上花了多久"，但不能替代业务埋点。

### Metrics, Logs, Traces Together

三者的关联靠**共享标识**：

- 在日志里输出 `trace_id` / `span_id`，从日志跳 trace；
- 在 trace 上挂 exemplar 指向指标时间点（Prometheus 支持 exemplar）；
- 统一的 `service.name`、`k8s.namespace.name`、`k8s.pod.name` 资源属性，保证后端能按同一维度聚合。

没有统一资源属性的可观测性栈，最后会退化成三个互不相干的后台。

## Practical Topology

一个可落地的自建栈：

```
┌─ 节点 ─────────────────────────────────────────────┐
│ kubelet (/metrics, /metrics/cadvisor)              │
│ node-exporter                                      │
│ otel-collector-agent (DaemonSet, 4317/4318)        │
│ fluent-bit (DaemonSet, /var/log/pods)              │
└──────────────┬─────────────────────────────────────┘
               │ scrape / OTLP / push
┌──────────────▼─────────────────────────────────────┐
│ Prometheus / Mimir + Alertmanager                  │
│ Loki / Elasticsearch                               │
│ Tempo / Jaeger                                     │
│ Grafana（统一查询与关联）                           │
└────────────────────────────────────────────────────┘
```

部署顺序建议：先 metrics-server（让 HPA/`kubectl top` 可用）→ 再 Prometheus + kube-state-metrics（建立历史与告警）→ 再日志采集 → 最后 traces。顺序反了会出现"有 trace 但没有告警"的倒挂。

## Anti-Patterns

- **只看平均 CPU**：平均利用率掩盖长尾，HPA 也会因平均值达标而不扩容；看 P95/P99 与 throttling。
- **把 events 当日志长期存储**：events 会过期，且不适合全文检索。
- **日志里打全量请求体**：成本高且泄露敏感信息；结构化字段 + 采样。
- **trace 全量采样**：高 QPS 下存储成本爆炸，且大部分正常请求没有诊断价值。
- **指标基数失控**：把 `user_id`、`request_id` 放进 label 会把 Prometheus 打爆；高基数维度放日志/trace。
- **依赖节点本地日志做审计**：轮转 + Pod 删除后不可恢复，审计必须集中采集。

## Links

- [Scaling](/docs/CS/Container/k8s/Scaling.md)
- [Issues](/docs/CS/Container/k8s/Issues.md)
- [kubelet](/docs/CS/Container/k8s/kubelet.md)
- [apiserver](/docs/CS/Container/k8s/apiserver.md)
- [扩展机制](/docs/CS/Container/k8s/Extension.md)
- [Kubernetes](/docs/CS/Container/k8s/K8s.md)

## References

1. [Metrics for Kubernetes System Components](https://kubernetes.io/docs/concepts/cluster-administration/system-metrics/)
2. [Logging Architecture](https://kubernetes.io/docs/concepts/cluster-administration/logging/)
3. [Traces](https://kubernetes.io/docs/concepts/cluster-administration/system-traces/)
4. [OpenTelemetry Protocol Specification](https://opentelemetry.io/docs/specs/otlp/)
5. [Prometheus Operator: Getting Started](https://prometheus-operator.dev/docs/getting-started/introduction/)
6. [OpenTelemetry Operator for Kubernetes](https://opentelemetry.io/docs/platforms/kubernetes/operator/)
