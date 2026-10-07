## Introduction

Istio 是 CNCF 顶级项目服务网格，在不改业务代码的前提下，把 mTLS 强身份、流量治理（路由/重试/熔断/灰度）、可观测性与策略扩展以「Sidecar 代理」的形式注入到既有微服务。Spring Cloud 体系里它不是替代品而是**网格层**：Spring Cloud Gateway / Nacos / Sentinel 解决应用层入口与治理，Istio 解决的是「所有服务之间、跨语言跨框架的零信任网络」。

> [!NOTE]
> 版本基线（2026-10 核实）：最新稳定版 **1.31.1**（2026-09-21 发布），1.31.0 于 2026-08-31 发布，**官方支持 Kubernetes 1.32 ~ 1.36**。1.31 的 Release Managers 分别来自 Red Hat、Microsoft、Tetrate。资源 API 版本为 `networking.istio.io/v1`（`VirtualService` / `DestinationRule` / `Gateway` / `ServiceEntry` / `Sidecar` / `WorkloadEntry`）、`security.istio.io/v1`（`PeerAuthentication` / `AuthorizationPolicy`）、`telemetry.istio.io/v1`（`Telemetry`）。

Istio 有两种数据面模式：**Sidecar**（每个 Pod 注入 Envoy）与 **Ambient**（无 sidecar，节点级 ztunnel + 可选 waypoint）。二者可在同一网格内混用，可以按命名空间逐步从 L4 覆盖层升级到 L7 策略。

## Architecture: Control Plane and Data Plane

网格在逻辑上分为两层，**数据面**由一组 Envoy 代理组成，拦截并控制服务间所有网络通信，同时采集上报遥测；**控制面**负责服务发现、配置下发与证书管理，把高层路由规则翻译成 Envoy 配置并运行时推给代理。

### Data Plane: Envoy

Istio 使用**扩展版 Envoy**（C++）作为唯一与数据面流量交互的组件。Envoy 本身提供动态服务发现、负载均衡、TLS 终止、HTTP/2 与 gRPC 代理、断路器、健康检查、按百分比切流的渐进发布、故障注入与丰富指标。

关键点：**只有 Envoy 代理接触业务流量**，控制面从不碰数据包。sidecar 部署模式的价值在于无需重构或重写应用即可获得网格能力。

### Control Plane: istiod

istiod 提供三件事：

- **服务发现**：抽象掉 Kubernetes / VM 等不同平台的服务发现机制，合成任何符合 Envoy API 的 sidecar 都能消费的统一格式。
- **配置下发**：把 Traffic Management API 等高层规则细化为 Envoy 原生配置，运行时经 xDS 推送（CDS / LDS / EDS / RDS / SDS），规则变更秒级生效、**无需重启代理**。
- **证书与身份**：istiod 自身充当 CA，为数据面签发证书以支撑 mTLS，使策略可以基于**服务身份**（而非不稳定的 L3/L4 网络标识）来实施。

## Two Data Plane Modes

| 维度 | Sidecar 模式 | Ambient 模式 |
| :-- | :-- | :-- |
| 代理形态 | 每 Pod 一个 Envoy sidecar | 节点级 **ztunnel**（Rust）+ 可选 **waypoint**（Envoy） |
| 层级 | 直接覆盖 L4 + L7 | ztunnel 做 L3/L4，waypoint 补 L7 |
| 是否改 Pod | 需注入（sidecar injector / CNI） | 不改业务 Pod |
| 覆盖能力 | mTLS、L7 路由、L7 授权、完整遥测 | 默认仅零信任 L4；需 waypoint 才有 L7 策略 |
| 升级粒度 | 单服务（重建 Pod） | **按命名空间**从 L4 覆盖层渐进到 L7 |

### ztunnel

ztunnel（Zero Trust tunnel）是**每节点**的专用代理，用 **Rust** 编写，职责被刻意限制在 L3/L4：mTLS、认证、L4 授权与遥测。**它不终止业务 HTTP 流量、也不解析业务 HTTP 头**。ztunnel 把流量直接送到目标 Pod、其他 ztunnel 或 waypoint。官方称之为「secure overlay」。

### waypoint proxy

waypoint 是 **Envoy 的一种部署形态**（与 sidecar 同一引擎），但**跑在业务 Pod 之外**，可独立安装、升级与扩缩容。只要 mTLS + 加密隧道 + L4 授权 + L4 遥测的场景，**只装 ztunnel 即可、无需 waypoint**；需要高级流量治理、L7 授权与 VirtualService 路由时才引入。

### HBONE Tunnel

ztunnel 之上，传输层用的是基于 **HTTP CONNECT** 的隧道协议 **HBONE**，这是 ambient 模式在 L4 覆盖层上实现安全传输的方式。

## Core Resources and Request Chain

五个 `networking.istio.io/v1` 资源各管一段，最容易记混的是职责边界：

| 资源 | 管什么 | 不管什么 |
| :-- | :-- | :-- |
| `Gateway` | 监听端口、协议、对外 Host、TLS 终止（**L4~L6**） | 不做 L7 路径路由 |
| `VirtualService` | Host 匹配、路由目标与动作（**L7**）：路由/重定向/重试/超时/故障注入/镜像 | 不定义真实目标如何负载均衡 |
| `DestinationRule` | 为真实目标与 `subset` 定策略：负载均衡、连接池、上游 TLS、异常剔除 | 不决定「请求去哪里」 |
| `ServiceEntry` | 把外部服务/VM 注册进网格（`MESH_EXTERNAL` + `resolution: DNS`） | 不会自动打通 DNS 与网络连通 |
| `Sidecar` | 限定该 sidecar **能看到/访问**哪些服务（`egress.hosts`） | 不是 egress gateway，不做路由决策 |

核心口诀：**Gateway 决定「谁能进」，VirtualService 决定「去哪」，DestinationRule 决定「怎么去」，Sidecar 决定「能看多远」。**

入口请求的完整链路：

```text
客户端
  │  TLS 握手
  ▼
Gateway            监听 :443，校验 Host = ext-host.example.com
  ▼
VirtualService     hosts 匹配 + http[].match 逐条求值
  │  destination.host + destination.subset
  ▼
服务注册表          K8s Service / ServiceEntry（MESH_EXTERNAL）
  ▼
DestinationRule    subsets[].labels 筛出实例池，套 trafficPolicy
  ▼
Envoy              选健康实例并转发
```

`DestinationRule` 的策略**在 VirtualService 路由规则求值之后生效**，作用于流量的「真实目的地」——它不是一个额外的网络跳数，而是 Envoy 选定真实目标后套用的策略。

## Key Field Semantics

| 字段 | 含义 |
| :-- | :-- |
| `Gateway.servers[].hosts` | 网关接受哪些 Host |
| `VirtualService.spec.hosts` | 客户端使用的虚拟地址，**不必存在于注册表** |
| `VirtualService...destination.host` | 实际目标，**必须在注册表或经 ServiceEntry 注册** |
| `DestinationRule.spec.host` | 为哪个真实服务配策略 |
| `DestinationRule.subsets[].labels` | 用工作负载标签筛出该 subset 的实例 |
| `Sidecar.spec.egress[].hosts` | 格式为 `namespace/host` |

**`VirtualService.hosts` 与 `destination.host` 的区别是最高频的踩坑点**：前者是客户端手里的地址（可以是纯虚拟的 `bookinfo.com`），后者必须是真实可路由的服务。

## Traffic Management Semantics (Defaults and Pitfalls)

- **规则顺序匹配**：`http[]` 规则**从上到下逐条求值，第一条命中即生效**，并非「最具体优先」或「最长前缀优先」。无条件/权重规则应放最后兜底。
- **match 的 AND/OR**：同一 `match` 块内多条件是 **AND**，同一规则的多个 `match` 块之间是 **OR**。
- **默认负载均衡是 `least request`**（Envoy 从实例池随机取两个，选活动请求少的那个），不是轮询。另有 `ROUND_ROBIN` / `RANDOM` / `WEIGHTED` / `CONSISTENT_HASH`（Ketama）/ `MAGLEV`。一致性哈希用于按用户 ID、Session Cookie 把同一请求稳定打到同一后端。
- **默认重试 2 次**、间隔至少约 25ms 且由 Istio **动态调整**。`retries.attempts` / `perTryTimeout` / `retryOn` 可控。
- **Istio 默认禁用 Envoy 的 HTTP 请求超时**（须显式写 `timeout`）。应用层超时可能先于 Envoy 触发，导致重试与超时配置看起来「没生效」。
- **故障注入会「吃掉」超时与重试**：字段名是 `http[].fault`（**不是** `faultInjection`）。官方原文「timeouts or retries will not be enabled when faults are enabled on the client side」——这是**运行时行为**而非校验：1.31 的 webhook **不拦截** `fault` + `timeout` + `retries` 同时存在，但客户端侧启用 fault 时另两者不生效。所以故障注入测试要用独立的 VirtualService。
- **两处 TLS 不要混淆**：`Gateway.servers[].tls` 是**客户端 → 网关**；`DestinationRule.trafficPolicy.tls` 是**网关/sidecar → 上游**。后者常用 `ISTIO_MUTUAL`（网格内）、`SIMPLE` / `MUTUAL`（外部）。
- **未注册服务默认放行但不受控**：目标没有 `ServiceEntry` 时流量仍可能透传（走 `PassthroughCluster`），但**用不了 VirtualService 路由、超时重试、DestinationRule 熔断/连接池/异常剔除**。`ServiceEntry` 只是把服务纳入可管范围，不替代 DNS 与网络连通。
- **`connectionPool` 是上限**（`tcp.maxConnections`、`http.http1MaxPendingRequests`、连接池满时快速失败）；**`outlierDetection` 是剔除**（`consecutive5xxErrors`、`baseEjectionTime`、`maxEjectionPercent`、`minHealthPercent`）——一个管「最多允许多少」，一个管「哪些实例暂时不选」。注意 `maxConnections: 100` 是**每个工作负载实例** 100 连接，不是整个服务共享。
- **两种 weight 层次不同**：`VirtualService.route[].weight` 在目标/subset 之间分流；`DestinationRule` 的 locality 权重在实例池或地域之间分配。
- **`Sidecar.egress` 不是 egress gateway**：它只裁剪本地 sidecar 的配置与可达范围；出口流量治理要用 `Gateway` + 出口网关。`egress.hosts` 写 `./*` 表示本命名空间、`istio-system/*` 表示控制面服务。
- **`Sidecar` 收窄配置的价值**：减少 Envoy 配置数量、降低大网格内存占用；1.31 还支持 `~` 前缀从导入集里**减去**命名空间（`*/*` 加 `~ns1/*` = 全量除 ns1），避免长白名单。
- **生产优先 FQDN**：K8s 短名称仅在与目标服务同命名空间时可靠，跨命名空间建议写全 `reviews.default.svc.cluster.local`。

## 1.31 Key Changes

### Traffic Management

- **分区感知负载均衡**：`DestinationRule.trafficPolicy.loadBalancerSettings` 与 `MeshConfig` 新增 `zoneAwareLbSetting`，Envoy 自动把流量优先送到**与下游代理同可用区**的 endpoint，本区容量不足才溢出。与既有 `localityLbSetting` 的区别是：zone 级路由由 Envoy **自动**完成，而非靠静态百分比。
- **网格级默认流量策略**：`MeshConfig.defaultTrafficPolicy` 让管理员设定全局 `connectionPool` 与 `outlierDetection` 基线，被所有出站集群继承；`DestinationRule` 只需覆盖想改的块，**未设字段现在继承网格基线而非 Istio 内置默认**。基线也作用于入站集群与 `PassthroughCluster`。
- **未知主机的动态正向代理**：新增 `ALLOW_ANY_DYNAMIC_DNS` 出站策略模式，Envoy 用 Dynamic Forward Proxy 在**请求时**按 HTTP `Host` 头解析主机名，**不再需要为每个外部目标写 `ServiceEntry`**；非 HTTP 流量仍走 `PassthroughCluster`。
- 另有 `RetryBudget` 新增 `budget_interval`、`HTTPRedirect` 支持 `prefix_rewrite`、`DestinationRule` 可配上游 HTTP/2 keepalive PING、`ServiceEntry` 可见性由 `meshConfig.serviceEntryVisibility` 控制、`EnvoyFilter` 新增 `MERGE_AND_REPLACE_LIST` 补丁操作（替换而非追加列表字段）。

### Ambient

- **加权 waypoint 金丝雀**：服务或命名空间可用 `istio.io/use-waypoint-canary` 与 `istio.io/use-waypoint-canary-namespace` 标签同时引用主与金丝雀 waypoint，再由 `istio.io/use-waypoint-canary-weight` 注解把**可配置比例**的入网格连接导向金丝雀，**客户端无需改动**即可渐进发布 waypoint 配置变更。
- **多集群稳定性**：本版修复大量 ambient 问题——凭证轮换不再造成陈旧快照或丢失 endpoint shard，多集群模式的内存与 goroutine 泄漏已解决，CNI 节点代理修掉了 map 并发写 panic、fd 泄漏与 Pod 删除死锁。
- **agentgateway 作为 waypoint**：在 1.30 实验性 gateway-only 支持之上，新增 `istio-agentgateway-waypoint` GatewayClass 以把 [agentgateway](https://agentgateway.dev) 部署为 waypoint 代理。

### Security

- **FIPS 140-3 合规策略**：`COMPLIANCE_POLICY` 新增 `fips-140-3`，强制 TLS 1.2+ 与 FIPS 兼容密码套件及 P-256/P-384 曲线；Go 组件须用 Go 1.24+ 并以 `GOFIPS140=v1.0.0` 构建。
- **`AuthorizationPolicy` 信任域匹配**：`Source` 新增 `trustDomains` / `notTrustDomains`，可按对端证书推导出的信任域匹配或排除请求。
- **严格网关合并**：`PILOT_ENABLE_STRICT_GATEWAY_MERGING`（**默认开启**）禁止 Istio `Gateway` CRD 与受管 Gateway API `Gateway` 代理跨命名空间合并。
- **xDS 生成器鉴权**：MCP 配置下发端点要求已验证的控制面身份；标准 sidecar / gateway / ztunnel 流量不受影响。
- **Gateway API `AllowInsecureFallback`**：启用后网关会请求客户端证书并尝试验证，但未出示或验证失败仍放行，同时填充 `x-forwarded-client-cert` 交由后端自行校验。

### Installation and Observability

- Kiali 插件更新到 **v2.26.0**；ztunnel 支持 `ZTUNNEL_RESOURCE_CPU_LIMIT` / `ZTUNNEL_RESOURCE_CPU_REQUEST` 感知 CPU 的工作线程数。
- `istioctl manifest generate -o` 把生成的清单写文件而非 stdout；`global.readerServiceAccount` 可把 `istio-reader` ClusterRole 绑到自定义 ServiceAccount。
- **Prometheus 多目标抓取**：新增 `prometheus.istio.io/scrape-targets` Pod 注解，以逗号分隔的 `port:path` 列表声明多个应用指标端点，pilot-agent 并发抓取并合并输出。
- 新增 `ENVOY_SECURE_METRICS_PORT` / `ENVOY_SECURE_MERGED_METRICS_PORT`，可在每个 sidecar 上暴露 **mTLS 保护**的 Prometheus 端点；`PILOT_AGENT_MERGE_ENVOY_STATS=false` 可关闭 Envoy 指标合并。
- `ProxyConfig` 新增 `connectionSettings` 及面向网关代理的 `EDGE` 预设；`istioctl analyze` 新增 ServiceEntry 协议冲突与 Gateway API CRD 过期的告警。

### Artifact Channel Changes (Must-Read for Upgrade)

自 1.31 起，Istio **不再向 `gcr.io/istio-release`、`registry.istio.io`、`istio-release.storage.googleapis.com` 发布制品**：

- Docker 镜像仍在 **Docker Hub**；
- Helm charts 在 `blob.istio.io/istio-release/charts`；
- OCI Helm charts 在 `ghcr.io/istio/release/charts`；
- 其他制品在 `blob.istio.io/istio-release`。

官方会做「scream test」把 GCP 制品短暂下线以验证迁移：2026-09-15、10-13、11-17、12-08。**依赖原 GCP 拉取地址的 CI / 镜像加速配置需要改。**

## Relationship with Higress

Higress 复用 Istio 的 xDS 协议、CRD 存储与多注册中心服务发现，其控制面的 `pilot` 是 `istiod` pilot 模块的 **fork**（不是原样依赖）。因此 Higress 天然具备 Istio 的流量治理语义，但**不能依赖 Higress 拿到原生 Istio 服务网格能力**——需要原生 mesh 语义应单独安装 Istio。二者取舍见 [Higress](/docs/CS/Framework/Higress/Higress.md)。

## Security and Observability (Overview)

完整展开见 [Security](/docs/CS/Framework/Istio/Security.md) 与 [Observability](/docs/CS/Framework/Istio/Observability.md)，此处只列最容易踩的语义。

**mTLS 三模式**：`DISABLE`（不隧道）/ `PERMISSIVE`（明文或 mTLS 均可）/ `STRICT`（必须 mTLS）。**mesh 级默认 `PERMISSIVE`**，作用域由 `metadata.namespace` 决定（root namespace 即 `istio-system` 为 mesh 级），**优先级取最窄**：workload → namespace → mesh-wide，且全网格最多 1 条 mesh-wide、多条同时匹配 workload-specific 时**取最旧**。

> [!WARNING]
> `AuthorizationPolicy` 的 `source.principals` / `namespaces` **必须先开 mTLS 才生效**。官方明确警告：在 `PERMISSIVE` 下使用这些字段**等于可被绕过**（policy bypass），务必配合 `STRICT`。

**身份与证书**：Istio 用 **SPIFFE ID 格式**（`spiffe://<trust.domain>/ns/<ns>/sa/<sa>`），但签发者是 **istiod 内嵌的 CA（Citadel）**，**不是 SPIRE**——SPIRE 需独立安装，通过 SPIFFE CSI driver 挂 UDS socket 探测接入，且**没有 feature flag 开关**。证书默认 **TTL 24h**（上限 90 天），**轮转提前量比例默认 `SECRET_GRACE_PERIOD_RATIO=0.5`**（即约 12h 处开始轮转，叠加 ±0.01 抖动以错峰），**不是网上流传的 0.8**。

**AuthorizationPolicy 四种 action**：`ALLOW`（默认）/ `DENY` / `AUDIT` / `CUSTOM`。求值顺序：CUSTOM → DENY → 无 ALLOW 则放行 → ALLOW 匹配则放行 → 否则拒。**`rules` 不设 = 永不匹配 = 默认拒绝**，这是从「全放行」切到白名单时最常见的静默失效。`CUSTOM` 依赖 MeshConfig `extensionProviders` 声明的 **ext_authz**（**唯一支持的扩展类型**），且扩展**不能绕过** ALLOW/DENY 结论。waypoint 场景**必须用 `targetRefs`，`selector` 会被忽略**。

**已知限制**：授权策略**只支持入站**，不支持出站；**不支持 server-first TCP 协议**（MySQL/PostgreSQL 等首包未经检查直达客户端）。

**遥测**：`Telemetry` API（`telemetry.istio.io/v1`）统一 metrics/logs/tracing。三个最容易踩的点：**`Telemetry` 是完全覆盖不是叠加**（namespace 级配置会让 mesh 级同字段整块失效，含 provider 选择本身；唯一例外是 `metrics.overrides` 按序叠加）；**指标默认就有**（默认 provider 即 `prometheus`），`Telemetry` 是用来改的不是用来开启的；**默认没有 tracing provider**，须自行配置。Prometheus 抓取 sidecar 的 `:15020/stats/prometheus`（合并默认开启）；1.31 新增 `prometheus.istio.io/scrape-targets` 注解（逗号分隔 `port:path` 列表，pilot-agent 并发抓取并按序合并）、`ENVOY_SECURE_METRICS_PORT`（**mTLS 保护的指标端点**）、`PILOT_AGENT_MERGE_ENVOY_STATS=false`（关闭 Envoy 指标合并）。ztunnel 侧可用 `ZTUNNEL_RESOURCE_CPU_LIMIT`/`ZTUNNEL_RESOURCE_CPU_REQUEST` 做 CPU 感知线程数。

**Ambient 概览**：ztunnel 刻意只做 L3/L4（**不终止业务 HTTP、不解析业务头**），L7 能力全靠 waypoint。**默认 mTLS 模式是 `PERMISSIVE` 而非 STRICT**，且 `DISABLE` 被忽略——HBONE 恒加密不可关闭。策略在 ztunnel 上是 **fail-safe 拒绝**（ALLOW 含 L7 属性会整条不放行，DENY 则变得更严），L7 策略必须用 `targetRefs` 挂到 waypoint。详细实操见 [Ambient](/docs/CS/Framework/Istio/Ambient.md)。

## Topic Notes Navigation

| 笔记 | 内容 |
| :-- | :-- |
| **本文** | 架构、两种数据面模式、五个核心资源职责、流量治理语义默认值、1.31 变更 |
| [Install](/docs/CS/Framework/Istio/Install.md) | 安装方式选型、Operator 弃用、组件与端口、xDS 推送、sidecar 注入与 iptables 端口、升级规则与破坏性变更、排障速查 |
| [TrafficManagement](/docs/CS/Framework/Istio/TrafficManagement.md) | 金丝雀与 A/B 分割、熔断与连接池默认值、重试与超时语义、故障注入、流量镜像、限流、已废弃字段速查 |
| [Observability](/docs/CS/Framework/Istio/Observability.md) | `Telemetry` 覆盖语义、核心指标与 `reporter` 陷阱、基数治理、追踪传播、访问日志格式、Prometheus 集成 |
| [Ambient](/docs/CS/Framework/Istio/Ambient.md) | ambient profile 部署、waypoint 实操命令与标签、L4/L7 分级授权、sidecar 互操作、排障命令集、性能数据 |
| [VMWorkload](/docs/CS/Framework/Istio/VMWorkload.md) | WorkloadEntry/WorkloadGroup 字段、`istioctl x workload` 实操、身份签发、健康检查、ambient 不支持 VM |
| [Troubleshooting](/docs/CS/Framework/Istio/Troubleshooting.md) | 三层排障分层、istioctl 命令全清单与默认值、analyze 退出码坑、proxy-status 收敛读法、bug-report |
| [Performance](/docs/CS/Framework/Istio/Performance.md) | 官方数据版本陷阱、CPU limit 与 worker 线程数、熔断为何不应收紧、控制面推送节流、调优清单 |
| [WasmPlugin](/docs/CS/Framework/Istio/WasmPlugin.md) | `WasmPlugin` 字段速查、`TrafficExtension` 翻译机制、SDK 与仓库现状、Go 开发实操、安全边界 |
| [Envoy](/docs/CS/Framework/Istio/Envoy.md) | Envoy 内核、xDS 8 种资源与 ADS 更新顺序、匹配语义、扩展机制、自适应并发、Gateway API 与网关生态横评、agentgateway |
| [Security](/docs/CS/Framework/Istio/Security.md) | mTLS 模式、证书签发与轮转、SPIFFE/SPIRE、信任域、AuthorizationPolicy、JWT、TLS 套件与 FIPS、安全排障 |
| [ecosystem](/docs/CS/Framework/Istio/ecosystem.md) | Linkerd / Cilium / Consul Connect / OSM 现状，云厂商托管网格，多集群与跨网格互联，选型视角 |

## Links

- [Istio 目录索引（按层导航）](/docs/CS/Framework/Istio/README.md)
- [Install](/docs/CS/Framework/Istio/Install.md)
- [TrafficManagement](/docs/CS/Framework/Istio/TrafficManagement.md)
- [Observability](/docs/CS/Framework/Istio/Observability.md)
- [Ambient](/docs/CS/Framework/Istio/Ambient.md)
- [VMWorkload](/docs/CS/Framework/Istio/VMWorkload.md)
- [Troubleshooting](/docs/CS/Framework/Istio/Troubleshooting.md)
- [Performance](/docs/CS/Framework/Istio/Performance.md)
- [WasmPlugin](/docs/CS/Framework/Istio/WasmPlugin.md)
- [Envoy](/docs/CS/Framework/Istio/Envoy.md)
- [Security](/docs/CS/Framework/Istio/Security.md)
- [ecosystem](/docs/CS/Framework/Istio/ecosystem.md)
- [Higress](/docs/CS/Framework/Higress/Higress.md)
- [Kubernetes](/docs/CS/Container/k8s/K8s.md)

## References

- <https://istio.io/latest/docs/ops/deployment/architecture/>
- <https://istio.io/latest/docs/concepts/traffic-management/>
- <https://istio.io/latest/docs/ambient/overview/>
- <https://istio.io/latest/news/releases/1.31.x/announcing-1.31/>
- <https://istio.io/latest/blog/2026/retirement-of-gcp/>
- <https://github.com/istio/istio/releases>
