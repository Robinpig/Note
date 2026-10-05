## Introduction

Istio 的 sidecar、gateway、waypoint 都是 **Envoy**。理解 Istio 的行为边界，绕不开 Envoy 自身的扩展点与匹配引擎——尤其是「Istio 的 CRD 翻译成 Envoy 的哪一层配置」这条链。本篇聚焦 Envoy 内核 + Gateway API 网关生态，并把版本事实全部现场核实。

> [!NOTE]
> 版本基线（2026-10 核实）：**Envoy v1.39.2**（2026-10-01 发布）。注意两个易错点：① GitHub `releases/latest` 指针**滞后**，仍返回 v1.39.1（2026-08-27），v1.39.2 虽已正式发布但 `latest` 未更新；② Envoy 官方文档站 `latest` 对应的是 **1.40.0-dev 开发分支快照**，引用具体默认值应改用版本化 URL 避免漂移。Envoy 仍在并行维护多个 minor 分支（2026-10-01 同日发布 v1.39.2 / v1.38.5 / v1.37.7 / v1.36.11），不是单线。

## Envoy 在网格中的位置

Istio 使用**扩展版 Envoy**（C++）作为**唯一与数据面流量交互的组件**。sidecar、ingress gateway、waypoint 是同一内核的三种部署形态——这也是为什么 waypoint 能直接复用 sidecar 的全部 L7 能力。

Envoy 自身提供的能力：动态服务发现、负载均衡、TLS 终止、HTTP/2 与 gRPC 代理、断路器、健康检查、按百分比切流的渐进发布、故障注入与丰富指标。

## xDS 与配置层级

### 8 种资源类型

官方 xDS 协议完整枚举是 8 种（常被误认为 5 种）：

| 服务 | 资源 |
| :-- | :-- |
| LDS | `Listener` |
| RDS | `RouteConfiguration` |
| SRDS | `ScopedRouteConfiguration` |
| VHDS | `VirtualHost` |
| CDS | `Cluster` |
| EDS | `ClusterLoadAssignment` |
| SDS | `Secret` |
| RTDS | `Runtime` |

两个关键区分：

- **Delta xDS 不是资源类型，而是更新方式；ADS 不是资源类型，而是传输聚合方式**（ADS 无独立 type URL）。`A single ADS stream is available per Envoy instance.`
- **EDS 的粒度限制**：xDS 以整个命名资源为单位更新，**目前不能只对某个 EDS 资源中的单个 endpoint 做增量更新**。
- **Delta xDS 只支持 gRPC 双向流**（`There is no REST version of Incremental xDS yet.`）；SotW 则支持 gRPC、REST-JSON。

### ADS 的 make-before-break 顺序

官方推荐的更新顺序（也是 Istio 推送顺序的依据）：

```text
CDS（先加新 Cluster）→ EDS（提供端点）→ LDS（加引用它们的 Listener）
→ RDS（把路由切到新）→ VHDS（最后更新 VirtualHost）→ 删除旧 Cluster 及 EDS
```

目的是「确保路由开始引用新资源之前，新资源已经可用」，减少更新期间的流量黑洞。

### 处理链层级

```text
Listener（配置树根，Envoy 启动时获取全部 Listener）
  └─ FilterChain
       └─ HCM / HttpConnectionManager（网络层过滤器，持有该 listener 的 route table）
            └─ HTTP filters（按序执行，共享 HCM 的 route table）
                 └─ envoy.filters.http.router（终端：匹配上游 cluster、取连接池、转发）
                      └─ Cluster（CDS）→ ClusterLoadAssignment（EDS）
```

容易忽略的一点：**route table 归 HCM 所有，被所有 HTTP filter 共享**，不只是 router 用。官方举例：内置限流过滤器会查询 route table 决定是否调用全局限流服务，router 只是「主要消费者」。

## 匹配语义（两处高频误解）

### vhost 匹配：4 级优先级

官方明确顺序：

1. 精确域名 `www.foo.com`
2. 后缀通配 `*.foo.com` / `*-bar.foo.com`
3. 前缀通配 `foo.*` / `foo-*`
4. 特殊通配 `*` 匹配任意域名

约束：`The longest wildcards match first`；**整个 route configuration 中只能有一个 vhost 用 `*`**；**域名跨 vhost 重复会导致配置加载失败**。

### route 匹配：没有「精确优先」

这是最容易写错的一处。`RouteMatch` 的路径匹配器是**互斥 oneof**：

> `Precisely one of prefix, path, safe_regex, connect_matcher, path_separated_prefix, path_match_policy must be set.`

**这些匹配器之间不存在「精确路径自动优先于前缀」「前缀自动最长优先」的全局优先级**，规则纯顺序优先：`The first route that matches will be used.` 因此 catch-all 路由（`prefix: /`）必须放在具体路由之后。

### Generic Matching 引擎

Envoy 新增的替代方案（在 vhost 上挂 `matcher`，动作为 `Route`/`RouteList`）：

- `exact_match_map` 是 HashMap，**O(1)**。
- `prefix_match_map` 是前缀树，复杂度 `O(min{输入键长度, 最长前缀匹配})`，而非传统线性搜索的 `O(# routes × 平均长度)`。
- 注意 `prefix_match_map` 的 trie **不支持通配符**，按字面量逐字符匹配。

> [!WARNING]
> **「CEL/RE2 已取代部分 lua」这个说法不成立**，官方文档无支撑。CEL 在 Envoy 中的定位是 **matcher**，不是 lua 替代品：
> - **`RouteMatch` 中没有 CEL 字段**（逐条核对确认不存在 `cel` / `cel_matcher` / 通用 `matcher` 字段）；名为 `matcher` 的字段只存在于 **`VirtualHost`**。
> - CEL 出现在 Generic Matching 的 custom matcher（`CelMatcher` + `HttpAttributesCelMatchInput`）与 RBAC/访问日志等**策略表达式**场景。
> - `safe_regex` 的类型是 `type.matcher.v3.RegexMatcher`，仅在 `RouteAction.regex_rewrite` 示例中见到「Google's RE2 engine」措辞；**「google_re2 是唯一支持引擎」未找到原文依据**。另外 Generic Matching 页提到的 regex matcher 官方措辞是 **Hyperscan**，两者不要混用。
> - CEL 当前主要落点是 **RBAC/授权与访问日志策略表达式**及 External API。

## 扩展机制

### Wasm

- 推荐 **Proxy-Wasm ABI 0.2.1**。
- 5 个扩展点：HTTP filter、network(L4) filter、StatsSink、AccessLogger、后台服务。
- **Wasm 过滤器在官方文档中仍标注 experimental，且不支持 Windows。**
- 运行时可选 V8 / WAMR / Wasmtime，另有 "Null VM"（编译为原生代码静态链接进 Envoy 二进制）。
- **执行模型**：Wasm 模块在配置时于**主线程加载**，主实例克隆到各 worker 线程；**worker 线程不共享 Wasm 执行实例和运行时内存**。异步/阻塞操作委托给 Envoy，完成后回调插件。
- 通过 `proxy_call_foreign_function` 暴露 CEL 能力：`expr_create` / `expr_evalute`（官方拼写如此）/ `expr_delete`。

### 内置扩展点过滤器

`ext_authz`、`ext_proc`、`lua`、`wasm`、`rate_limit`、`router`（均已确认存在于官方文档）。

### EnvoyFilter 是 Istio CRD，不是 Envoy 特性

Istio 1.31 新增 `MERGE_AND_REPLACE_LIST` 补丁操作（行为像 MERGE，但 list 字段**整体替换**而非追加），适用于 `CLUSTER` / `LISTENER` / `FILTER_CHAIN` / `ROUTE_CONFIGURATION` / `VIRTUAL_HOST` / `HTTP_ROUTE` 六类 patch target；**嵌套在 Any 类型 filter 配置内部的 list 仍为 MERGE 语义**。

## 自适应并发（Adaptive Concurrency Filter）

Envoy 内置过滤器，**在 Envoy 侧默认启用**：

```yaml
enabled:
  default_value: true
  runtime_key: "adaptive_concurrency.enabled"
```

> [!WARNING]
> 必须区分两个「默认」：这是 **Envoy 侧过滤器自身启用默认**，**与 Istio 是否为 sidecar/waypoint 下发该过滤器是两回事**——Istio 1.31 官方文档**无** Istio 默认启用 adaptive concurrency 的证据。

### 算法（两个易错公式）

```text
gradient = minRTT + B × sampleRTT      B = minRTT × buffer_pct
limit_new = gradient × limit_old + headroom
```

- **headroom 不可配置**，官方原文「the headroom value is unconfigurable and pinned to the square-root of the concurrency limit」。它必须在公式中，否则 sampleRTT 接近 minRTT 时并发上限会停在一个不必要的低值。
- gradient 值域 500~2000（统计时乘了 1000）。
- `min_concurrency_limit`（下界）与 `min_concurrency`（测 minRTT 时钉住的并发）已解耦——较新行为，官方说明为「preserve the historical behavior」。

官方示例默认值（**是示例而非产品默认**）：`sample_aggregate_percentile: 90`、`concurrency_update_interval: 0.1s`、`min_concurrency_limit: 25`、`min_concurrency: 50`、`jitter: 10`（0~6s 随机延迟）、`interval: 60s`、`request_count: 50`。

### 两个运维陷阱

1. **minRTT 测量窗口内 503 可能明显增加**，官方称 `This is expected`，建议开 reset/503 重试，可用 `min_concurrency_limit` 降低影响；官方推荐 **`previous_hosts` retry predicate**。
2. **过滤器必须位于 healthcheck 过滤器之后**，否则健康检查流量被采样会污染 minRTT 精度。

架构性限制（决定用不了的地方）：① 只在 local cluster 的 filter chain 中按预期工作；② 必须能对该 cluster 的并发做限制，即不存在「未被该 adaptive concurrency filter 解码却发往该 cluster」的请求。

## Gateway API

### 版本与通道

**当前最新稳定版 v1.6.2（2026-09-03）**——注意不是 v1.2/v1.3。近期序列：v1.6.2 (2026-09-03) → v1.6.1 (2026-07-16) → v1.6.0 (2026-06-29)，上一 minor 线 v1.5.1 (2026-03-14)。

**graduation 状态**：

- **Gateway / GatewayClass / HTTPRoute**：自 v0.5.0 起属 Standard channel，三者在 **v1.0.0 时已获得 GA 的 v1 API 版本**。
- **GAMMA（Service Mesh 支持）**：自 **v1.1.0 起进入 Standard channel，已 GA**。Mesh 场景**不使用** Gateway/GatewayClass，route 资源通过 `parentRefs` 直接关联 Service。
- **ReferenceGrant 仍是 v1beta1**（特例，正推进迁移进上游 K8s API，KEP-3766）；官方正在淘汰 beta——`All future resources that graduate to Standard Channel will include a v1 API version`。
- `ListenerSet` 自 Gateway API **v1.5.0** 起不再是 experimental（由 Istio 1.31 change notes 交叉印证）。

**Standard vs Experimental**：

| | Standard | Experimental |
| :-- | :-- | :-- |
| 内容 | 已毕业资源 + 已毕业字段 | Standard 全部 **+** alpha 资源 **+** 未毕业新字段 |
| 节奏 | **约 4 个月一版**，日期预定不延期，内容浮动 | **月度**（tag 形如 `monthly-2026-05`），main 分支快照 |
| 兼容保证 | v1beta1→v1 变更可转换 | **无任何兼容保证**，破坏性变更随时发布 |
| backport | — | **不接收 bugfix backport**，不遵循 SemVer |

通道边界由 Validating Admission Policies 强制：*Upgrade VAP* 阻止用实验通道 CRD 覆盖标准通道；*Guardrails VAP* 阻止不写 annotation 就设实验字段。CRD 通道标识为 `gateway.networking.k8s.io/bundle-version` 与 `gateway.networking.k8s.io/channel` 两个 annotation。

毕业门槛（6 项全满足）：完整 conformance 测试覆盖；多个 conformant 实现；广泛实现与使用；**作为 alpha API 至少 6 个月 soak**；至少 1 个 minor + 3 个月无重大变更；subproject owner + KEP reviewer 批准。承诺支持最近 5 个 K8s minor。

### Istio Gateway CRD vs Gateway API

两者**可以共存**——`networking.istio.io/v1` 的 Gateway 与 `gateway.networking.k8s.io/v1` 的 Gateway 是同名不同 group 的两个 CRD。

关键语义差异：

- **Istio Gateway 只是「配置」一个已存在的 gateway Deployment/Service；Gateway API 的 Gateway 同时「配置并部署」gateway**。这是最本质的差异。
- Istio `VirtualService` 在单个资源内配置所有协议；Gateway API 每个协议有独立资源（`HTTPRoute`/`TCPRoute` 等）。
- Gateway API **尚未覆盖 Istio 全部特性集**（官方原话：`does not yet cover 100% of Istio's feature set`）。
- 挂载方式：Gateway API 用 `parentRefs`；Istio API 靠 `exportTo` 与 namespace 可见性。

**Istio 是否推荐迁移到 Gateway API：是**，官方明确表态「intends to make it the default API for traffic management in the future」。

**1.31 的 Gateway API 支持已对齐 v1.6**——有实打实的 conformance 证据：修复了 Gateway API v1.6.0 引入的 `HTTPRouteNoBackendRefs`（空 backendRefs 返回 404 而非 500）与 `GatewayInvalidParametersRef` 等测试所要求的行为。Istio 1.31 安装指令用 `ref=v1.6.0`。

> [!WARNING]
> **Gateway API CRD 不由 Istio 安装，必须自行单独安装与升级。** Istio 1.30 曾要求 CRD 升到 v1.5.x，否则 `TLSRoute` 与 `ReferenceGrant` 对 istiod **不可见**，已有 TLS passthrough listener 会**静默**报 `attachedRoutes: 0` 且 Envoy listener 不下发。1.31 延续 v1.6.0。

1.31 还新增 `PILOT_ENABLE_STRICT_GATEWAY_MERGING`（**默认开启**）阻止 Istio `Gateway` CRD 与托管 Gateway API `Gateway` 跨 namespace 合并——两套 Gateway 混用时的隔离机制。

## 网关实现横评

版本全部现场取自 GitHub API（2026-10）：

| 项目 | 最新版本 | 发布日期 | 关键事实 |
| :-- | :-- | :-- | :-- |
| **Envoy Gateway** | v1.9.2 | 2026-09-28 | Envoy 项目托管控制面，动态置备配置 Envoy Proxy；**不是 service mesh**，管南北向 |
| **agentgateway** | v1.6.0 | 2026-10-02 | **Rust** 编写；Gateway API conformant；AI-first 代理 |
| **Istio** | 1.31.1 | 2026-09-21 | 见 [Istio](/docs/CS/Framework/Istio/Istio.md) |
| **NGINX Gateway Fabric** | v2.7.2 | 2026-09-16 | NGINX 作数据面，Gateway API + NGINX 双栈，控制面/数据面分离 |
| **Traefik Proxy** | v3.7.13 | 2026-09-04 | 3.7「Langres」GA；ingress-nginx provider 转正，**80+ NGINX annotation**（官方口径 85+、覆盖 >90% 实际用法，含 snippets 白名单解析） |
| **Apache APISIX** | 3.19.0 | 2026-09-28 | 新增原生 WebSocket、TLS 流透传、**OpenAPI→MCP 转换**、上游慢启动 |
| **Kong KIC** | v3.5.13 | 2026-08-07 | 仓库已迁移至 **`Kong/kubernetes-ingress-controller`**（旧 `kong/kubernetes-ingress` 已 Not Found） |

> [!NOTE]
> **Envoy Gateway 兼容性矩阵**（官方，务必遵守）：v1.9 → Envoy `distroless-v1.39.x` + Gateway API v1.6.1 + K8s 1.33~1.36，EOL 2027-02-14。两条官方警告：① **每个 minor 只绑定并测试一个 Envoy Proxy minor**，跨 minor 组合未测试；② 若在 `EnvoyProxy` 资源上用 `image` 钉住数据面镜像且 minor 不匹配，Envoy Gateway 可能生成**被 proxy 静默拒绝**的配置——proxy 继续用 last-known-good 运行，故障要到**重启才暴露**，届时无配置可回退。检测手段：监控 `xdsNACKTotal` 指标（v1.9 新增）。若只是要私有 registry，用 `imageRepository` 而非 `image`。

Envoy Gateway v1.9 破坏性变更中与生态最相关：TCPRoute/UDPRoute 改用 `gateway.networking.k8s.io/v1`，**必须把 Gateway API CRD 升到 v1.6**，否则 **TCP/UDP route 会被静默跳过**；Lua `EnvoyExtensionPolicy` 默认禁用需显式 `enableLua`。

### ingress-nginx 退役的生态影响

Kubernetes SIG Network 与安全响应委员会宣布 ingress-nginx 退役，**维护于 2026-03 终止**，此后不再有 release、bugfix 或安全更新；仓库转只读，**已有部署不会被破坏**（Helm chart 与镜像仍可获取）。

两大退役原因：`snippets` 注解允许注入任意 NGINX 配置指令，被视为重大安全风险；以及**长期只有 1~2 人利用业余时间维护**。替代方案 InGate 从未成熟即被一同退役——**不存在一对一原地替换路径**。注意 **Ingress API 本身未被弃用**，只是 feature-frozen。

> [!WARNING]
> 网络流传的「App Mesh 被 EKS Service Mesh 取代」需纠正：**AWS App Mesh 官方后继是 Amazon ECS Service Connect**（非网格）。详见 [ecosystem](/docs/CS/Framework/Istio/ecosystem.md)。

## agentgateway

定位「**AI-first, open-source, cloud-native gateway control plane and proxy data plane**」，仓库描述为 `Next Generation Agentic Proxy for AI Agents and MCP servers`。它是**通用 HTTP/gRPC 全功能代理**，不是「AI sidecar」——用同一代理同时承载常规 API 与 LLM 推理、MCP 工具服务器、A2A agent 流量。

**不是基于 Envoy**：官方明确用 **Rust** 编写，理由是「有状态长连接与 fan-out 场景下性能和内存安全不可妥协」——语言选择本身是架构声明。

与传统 API 网关的差异（解释为何要新造一个）：

| 维度 | 传统 API 网关 | agentgateway |
| :-- | :-- | :-- |
| 会话模型 | 无状态请求/响应 | **有状态 JSON-RPC 会话**，长连接 |
| 分发 | 一个请求 → 一个后端 | **session fan-out** 到多个 MCP server |
| 方向 | 仅客户端发起 | **双向**，server 可经 SSE 推事件 |
| 路由 | 按 path/header 静态路由 | **协议感知**，理解 JSON-RPC 消息体 |
| 后端 | 静态映射 | **按客户端动态工具虚拟化** |

**治理归属易写错**：2025 年捐赠给 **Linux Foundation**，**2026 年被接受为 Agentic AI Foundation（AAIF）项目**。**不是 CNCF 项目**，也**不是 Envoy 子模块**——与 Envoy Gateway 分属不同组织，**两者无隶属关系，是并列的独立实现**。

**Istio 支持两代演进**：

- **1.30**：首次实验性支持，作为 **Gateway API gateway**，GatewayClass **`istio-agentgateway`**，需 `PILOT_ENABLE_AGENTGATEWAY=true`；启用后**在 gateway pod 里替换掉 Envoy**。1.30 时明确**不支持作为 sidecar 或 waypoint**。官方措辞：`This is early-access functionality. Expect rough edges.`
- **1.31**：新增 **`istio-agentgateway-waypoint`** GatewayClass，可作为 **waypoint** 部署；并修复 ListenerSet 处理与 agentgateway 后端 mTLS 连通性问题。

能力：MCP 工具联邦聚合（stdio / HTTP-SSE / Streamable HTTP 三种传输）、OpenAPI→MCP、MCP auth spec 兼容（OAuth/Auth0/Keycloak）、A2A agent 发现与能力协商、自托管 **Kubernetes Inference Gateway**（`gateway-api-inference-extension`，按 GPU/KV cache 利用率、prompt criticality、LoRA adapter、工作队列深度路由）、**CEL 策略引擎**授权、内置 OpenTelemetry。

1.31.1 修复：某 service 仅通过 `istio.io/use-waypoint-canary` 引用 agentgateway waypoint 时，该 waypoint **未下发**其前置 service 的 routes 与 policies，导致切到 canary 的连接被拒。

## Links

- [Istio](/docs/CS/Framework/Istio/Istio.md)
- [Install](/docs/CS/Framework/Istio/Install.md)
- [Security](/docs/CS/Framework/Istio/Security.md)
- [ecosystem](/docs/CS/Framework/Istio/ecosystem.md)
- [Higress](/docs/CS/Framework/Higress/Higress.md)
- [gateway](/docs/CS/Framework/Spring_Cloud/gateway.md)

## References

- <https://www.envoyproxy.io/docs/envoy/latest/api-docs/xds_protocol>
- <https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/http/http_routing>
- <https://www.envoyproxy.io/docs/envoy/latest/intro/arch_overview/advanced/matching/matching_api>
- <https://www.envoyproxy.io/docs/envoy/latest/configuration/http/http_filters/adaptive_concurrency_filter>
- <https://gateway-api.sigs.k8s.io/docs/concepts/versioning/>
- <https://gateway.envoyproxy.io/news/releases/matrix>
- <https://istio.io/latest/docs/tasks/traffic-management/ingress/gateway-api/>
- <https://agentgateway.dev/docs/kubernetes/latest/>
- <https://v1-34.docs.kubernetes.io/blog/2025/11/11/ingress-nginx-retirement>
