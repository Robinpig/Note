# Istio Ambient Mode

## Introduction

Ambient 模式把「每 Pod 一个 sidecar」换成「**每节点一个 ztunnel + 按需共享的 waypoint**」，动机很直接：sidecar 的资源开销是**按 Pod 数**线性增长的，大集群里光 sidecar 就能吃掉可观的 CPU 与内存。

但换代理架构不是换个部署参数那么简单。有一批关于 ambient 的流传说法在 1.31.1 里**完全不成立**，且其中好几处会导致「配了没效果」：`istio.io/waypoint` 注解不存在、`istioctl waypoint edit` 子命令不存在、`istio-ztunnel-config` ConfigMap 不存在、ambient 默认不是 STRICT 而是 `PERMISSIVE`、`waypoint` 单实例比 sidecar 更省资源（恰恰相反）。

版本基线：**Istio 1.31.1**（2026-09-21 发布，1.31.0 于 2026-08-31），官方支持 Kubernetes **1.32 ~ 1.36**。本文所有命令、注解/标签名、默认值逐条核实自 istio 1.31.1 源码 tarball 与 `istio/api` 对应 commit（`d60a532be69a`）、istio.io 官方文档与 1.31 change-notes。

## Three-Layer Data Plane: mesh / waypoint / ztunnel

理解 ambient 的关键是分清三个角色：

| 角色 | 形态 | 能力 | 是否解析业务 HTTP |
| :-- | :-- | :-- | :-- |
| **ztunnel** | **每节点一个** DaemonSet，Rust 编写 | mTLS、身份、L4 授权、L4 遥测 | **否**（刻意不解析） |
| **waypoint** | **Pod 外的 Envoy**，按 ns/服务共享 | L7 全部能力：路由、LB、熔断、限流、故障注入、**重试与超时** | 是 |
| **mesh** | 概念层 | 网格内所有 ztunnel + waypoint | — |

官方原文解释 ztunnel 的设计意图：

> "Ztunnel is written in Rust and is intentionally scoped to handle **L3 and L4 functions** such as mTLS, authentication, L4 authorization and telemetry. **Ztunnel does not terminate workload HTTP traffic or parse workload HTTP headers.**"

传输层用 **HBONE**（HTTP CONNECT 隧道，HTTP/2 + CONNECT + mTLS 三标准合成），监听端口约定为 TCP **15008**。

> [!TIP]
> **省的是「代理数量」，不是「单实例开销」。** 官方性能数据：单个 sidecar 约 0.20 vCPU / 60 MB，单个 waypoint 约 **0.25 vCPU** / 60 MB，**waypoint 单实例比 sidecar 更贵**。N 个 sidecar 换成 1 个共享 waypoint 才省。

## Installation

### ambient is a Real Profile

`manifests/profiles/ambient.yaml` 全文：

```yaml
apiVersion: install.istio.io/v1alpha1
kind: IstioOperator
spec:
  components:
    cni:
      enabled: true
    ztunnel:
      enabled: true
    ingressGateways:
    - name: istio-ingressgateway
      enabled: false
  values:
    profile: ambient
```

三个要点：**启用 CNI**、**启用 ztunnel**、**禁用默认 ingress gateway**（需要时自行启用）。

官方安装命令：

```bash
istioctl install --set profile=ambient --skip-confirmation
```

预期输出是四行：`Istio core installed` / `Istiod installed` / `CNI installed` / `Ztunnel installed` / `Installation complete`。

> [!NOTE]
> **ambient 不是默认 profile。** `manifests/profiles/` 下共 10 个：`ambient` / `default` / `demo` / `empty` / `minimal` / `openshift-ambient` / `openshift` / `preview` / `remote` / `stable`。必须显式 `--set profile=ambient`。
>
> 用 Gateway API 还需要先装 CRD：`kubectl apply --server-side -f https://github.com/kubernetes-sigs/gateway-api/releases/download/v1.6.0/experimental-install.yaml`

### Key: `ISTIO_META_ENABLE_HBONE` Is Brought by ambient

真正控制数据面行为的是 Helm values 层的 `manifests/helm-profiles/ambient.yaml`：

```yaml
meshConfig:
  defaultConfig:
    proxyMetadata:
      ISTIO_META_ENABLE_HBONE: "true"
pilot:
  env:
    PILOT_ENABLE_AMBIENT: "true"
cni:
  ambient:
    enabled: true
```

`ISTIO_META_ENABLE_HBONE=true` 这条全局 proxyMetadata 默认值**是 ambient profile 独有的**，也是「必须用 ambient profile 安装」的硬理由之一（见「与 sidecar 互操作」小节）。

## waypoint Deployment Practice

### `istioctl waypoint` Has Only 5 Subcommands

| 子命令 | 用途 |
| :-- | :-- |
| `generate` | 生成 Gateway YAML（不创建） |
| `apply` | 创建/更新 waypoint |
| `delete` | 删除（`--all` 删全 ns） |
| `list` | 列出（`-A` 全 ns） |
| `status` | 看状态（**`--wait` 默认 true**） |

> [!WARNING]
> **`istioctl waypoint edit` 在 1.31.1 中不存在。** 源码注册列表只有上述 5 个。改 waypoint 需 `kubectl edit gateway` 或 `kubectl apply`。

常用参数：

| 参数 | 适用子命令 | 默认 |
| :-- | :-- | :-- |
| `--name` | **persistent，全部子命令生效** | `waypoint` |
| `--for` | `generate` / `apply` | `""` → `service` |
| `-r/--revision` | `apply` / `generate` / `delete` | `""` |
| `-w/--wait` | `apply` | **`false`** |
| `-w/--wait` | `status` | **`true`** |
| `--waypoint-timeout` | `apply` / `status` | `waitTimeout` |
| `--enroll-namespace` | `apply` | `false` |
| `--overwrite` | `apply` | `false` |

> [!WARNING]
> **`--wait` 在 `apply` 与 `status` 上默认值相反**（apply 默认不等、status 默认等）。这是最容易写错的一处。

`--for` 的合法取值（即 `istio.io/waypoint-for` 的值）：`service` / `workload` / `all` / `none`，默认 `service`。

`generate` 产出的 Gateway：

```yaml
apiVersion: gateway.networking.k8s.io/v1
kind: Gateway
metadata:
  labels:
    istio.io/waypoint-for: service
  name: waypoint
  namespace: default
spec:
  gatewayClassName: istio-waypoint
  listeners:
  - name: mesh
    port: 15008
    protocol: HBONE
```

「自动创建」指的是：**Gateway 资源 apply 后，istiod 自动监视它并创建/管理对应的 waypoint Deployment 与 Service**，而不是靠某种注解自动创建 Gateway。

常用命令序列：

```bash
istioctl waypoint generate --for service -n default          # 只看 YAML
istioctl waypoint apply -n default                           # 建 ns 级 waypoint
istioctl waypoint apply -n default --enroll-namespace        # 顺便给 ns 打标签
istioctl waypoint apply -n default --name reviews-svc-waypoint
istioctl waypoint apply -n default --name reviews-v2-pod-waypoint --for workload
istioctl waypoint delete --all -n default
istioctl waypoint list -A
```

### 7 Actually Effective Labels/Annotations

| 名称 | 种类 | 语义 | 可挂载 | 稳定性 |
| :-- | :-- | :-- | :-- | :-- |
| `istio.io/dataplane-mode` | label | `ambient` / `none`，加入或退出网格 | Pod、Namespace | Stable |
| `istio.io/use-waypoint` | label | 指定 waypoint 名（同 ns） | Pod、WorkloadEntry、Service、ServiceEntry、Namespace | Stable |
| `istio.io/use-waypoint-namespace` | label | 跨 ns 指定，**必须与上者同设** | 同上 | Beta |
| `istio.io/waypoint-for` | label | waypoint 可处理的流量类型 | Gateway（GatewayClass 亦可） | Stable |
| `istio.io/ingress-use-waypoint` | label | 让 ingress 流量也走 waypoint | Service、ServiceEntry、Namespace | Beta |
| `istio.io/use-waypoint-canary` | label | 金丝雀 waypoint 名 | Service、ServiceEntry、Namespace | Alpha |
| `istio.io/use-waypoint-canary-namespace` | label | 金丝雀 waypoint 所在 ns | 同上 | Alpha |
| `istio.io/use-waypoint-canary-weight` | **annotation** | 金丝雀权重 **0–100，默认 0** | 同上 | Alpha |

> [!WARNING]
> **`istio.io/waypoint` 这个注解/标签不存在。** 在 `istio/api` 的 `labels.gen.go` 中精确搜索零命中，`istio/istio` 全仓库搜索 `istio.io/waypoint"` 亦零命中。网上流传的「用 `istio.io/waypoint` 注解触发 waypoint 自动创建」在 1.31.1 不成立。
>
> **`gateway.networking.k8s.io/gateway-name` 也不是 ambient 的触发机制。** 在 `pilot/pkg/serviceregistry/ambient/` 全目录搜索该字符串与 `GatewayNameLabel`，零命中。ambient 挂接完全靠 `istio.io/use-waypoint*` 系列。
>
> **`istio.io/use-waypoint-weight` 也是错的**——1.31 change-notes 页把它写错了，源码常量是 `istio.io/use-waypoint-canary-weight`（announcing 博客页写的是对的）。**以源码为准。**

### waypoint Selection Logic

- **严格基于流量的原始目的地**（original destination），与最终解析到的 Pod 无关。若流量最初寻址 service 而该 service 未挂 waypoint，则**不经过 waypoint**，即便最终落到的 Pod 挂了 waypoint。
- Pod 标签优先级高于 Namespace 标签；Service 上的 `use-waypoint` 会被同 ns 的 Namespace 同名标签覆盖（前提是该 waypoint 能处理 `service` 或 `all`）。
- 「waypoint must allow the type」——Pod 挂了 workload 型 waypoint 但 Gateway 只标 `service` → 不生效。

> [!WARNING]
> **挂 waypoint 标签不等于流量一定过 waypoint。** waypoint 不存在、无地址，或流量类型不匹配时，**ztunnel 会直接路由到目标而非失败**。若 L7 策略是安全要求，须用 ztunnel 执行的 L4 `AuthorizationPolicy` 只允许 waypoint 身份兜底。

### Canary Waypoint (Alpha)

1.31 新增，**客户端零改动**即可渐进发布 waypoint 配置变更：

```yaml
metadata:
  labels:
    istio.io/use-waypoint-canary: reviews-v2-waypoint
    istio.io/use-waypoint-canary-namespace: default
  annotations:
    istio.io/use-waypoint-canary-weight: "20"    # 整数 0-100，默认 0
```

- 权重**按新连接**切分（mesh 内路径），连接建立后固定在选中 waypoint 不迁移；ingress 路径则**按请求**切分。
- **仅支持 `Service` / `ServiceEntry` / `Namespace`，不支持 Pod / WorkloadEntry**。
- 权重缺失 / 非法（`strconv.Atoi` 失败或不在 0–100）/ 与主 waypoint 相同 → 忽略金丝雀留在 primary，并在 service 的 `istio.io/WaypointBound` 条件里反映（已知状态码 `CanaryInvalidWeight`、`CanarySameAsPrimary`）。
- Namespace 级金丝雀仅对「同时继承该 ns primary waypoint」的 service 生效。
- 整体特性状态为 **Alpha**。

### ztunnel Deployment Forms

DaemonSet（`manifests/charts/ztunnel/templates/daemonset.yaml` 首个模板即 `kind: DaemonSet`），默认资源：

```yaml
resources:
  requests:
    cpu: 200m      # 超过 2 核时同时决定最小 worker 线程数
    memory: 512Mi  # 官方注释：足够 ~200k pod 集群或 100k 并发连接
```

> [!NOTE]
> **默认只设 `requests`、不设 `limits`。** 1.31 新增 `ZTUNNEL_RESOURCE_CPU_LIMIT` / `ZTUNNEL_RESOURCE_CPU_REQUEST` 环境变量，从 `resources.limits.cpu` / `requests.cpu` 注入，用于推导 CPU-aware worker 线程数。

ztunnel 配置通过**环境变量**注入 DaemonSet：`CA_ADDRESS`、`XDS_ADDRESS`、`LOG_FORMAT`、`NETWORK`、`RUST_LOG`、`RUST_BACKTRACE`、`ISTIO_META_CLUSTER_ID`、`INPOD_ENABLED`、`TERMINATION_GRACE_PERIOD_SECONDS`、`POD_NAME`、`POD_NAMESPACE`、`NODE_NAME` 等。

> [!WARNING]
> **`istio-ztunnel-config` ConfigMap 在 1.31.1 中不存在。** 全仓库（`*.yaml`/`*.go`/`*.tpl`）搜索零命中，ztunnel chart 模板里没有任何 ConfigMap。若笔记或教程提到它，可以判定为过时信息。

## L4 / L7 Tiered Authorization

### ztunnel-side Supported Matching Dimensions (Source Level)

ztunnel 的 `AuthorizationPolicy` 转换在 `pilot/pkg/serviceregistry/ambient/authorization.go` 的 `handleRule()`，逐字段映射。**实际只有这些**：

| 类别 | ztunnel 支持（L4） |
| :-- | :-- |
| `from.source` | `principals` / `notPrincipals`、`namespaces` / `notNamespaces`、`ipBlocks` / `notIpBlocks`、`serviceAccounts` / `notServiceAccounts` |
| `to.operation` | `ports` / `notPorts` |
| `when` | `source.ip`、`source.namespace`、`source.principal`、`destination.ip`、`destination.port` |

**不支持（会被判为 L7 规则）**：

- `to.operation`：`hosts` / `notHosts`、`methods` / `notMethods`、`paths` / `notPaths`
- `from.source`：`remoteIpBlocks` / `notRemoteIpBlocks`、`requestPrincipals` / `notRequestPrincipals`

> [!WARNING]
> **`SNI` 在 ztunnel 侧完全不支持**——`authorization.go` 中 `Sni`/`sniHosts`/`TlsHosts` 出现次数为 **0**，转换时既不映射也不报错（因为不在 L7 名单里）。**它不会给你任何提示，只是静默无效。**
>
> 同样，`remoteNetworks` 字段在 istio 1.31.1 全仓库 Go 代码中**零命中**。
>
> 1.31 新增的 `trustDomains` / `notTrustDomains` 在 `authorization.go` 中出现次数也是 **0**——既未映射也未列入 L7 不支持名单，因此**在 ztunnel 上被静默忽略**（不报错、不生效）。这是一个真实的静默失效陷阱。

### L7 Rules Become Fail-Safe Rejections When Applied to ztunnel

不是「静默不生效」，而是**更严格**：

- `ALLOW` 策略含 L7 属性 → `rules = nil`，**整策略全部拒绝**（比请求更严）
- `DENY` 策略含 L7 属性 → 保留规则但去掉 HTTP 部分，**也比请求更严**

源码里的告警文案常量：

```
ztunnel does not support HTTP attributes (found: %s). In ambient mode you must
use a waypoint proxy to enforce HTTP rules. %s

DENY policy with HTTP attributes is enforced without the HTTP rules. This will
be more restrictive than requested.

Within an ALLOW policy, rules matching HTTP attributes are omitted. This will
be more restrictive than requested.
```

同时会向控制面上报 `UnsupportedValue` 状态。客户端侧表现通常是连接被拒（`command terminated with exit code 56`）。

还有一条范围规则：**有 `targetRefs` 的策略不由 ztunnel 处理**（源码注释「TargetRef is not intended for ztunnel」，直接 `return nil, nil`）；只有 `ALLOW` / `DENY` 两种 action 被支持，其他 action 返回 `ztunnel does not support the %s action`。

### L7 Policy Routing to Waypoint via `targetRefs`

> [!NOTE]
> **L7 策略靠 `targetRefs` 而非 `istio.io/waypoint-for` 挂到 waypoint。** 后者只管「本 waypoint 处理哪类目的地」，不参与策略路由。

```yaml
# 挂到整个 waypoint
spec:
  targetRefs:
  - kind: Gateway
    group: gateway.networking.k8s.io
    name: default
---
# 挂到具体 service
spec:
  targetRefs:
  - kind: Service
    name: reviews
```

**waypoint 不冒充源工作负载身份——这是 ambient 最反直觉的语义变化。** 官方原文：

> "Waypoint proxies do not impersonate the identity of the source workload. Once you have introduced a waypoint to the traffic path, the destination ztunnel will see traffic with the *waypoint's* identity, not the source identity."

因此叠加顺序是：

**源侧 ztunnel（L4 路由）→ waypoint（L7 策略执行）→ 目的侧 ztunnel（此时看到的是 waypoint 身份）→ 业务 Pod**

官方由此给出的建议很明确：装了 waypoint 之后，**理想的策略执行点会转移**——即使你只想用 L4 属性做策略，只要依赖源身份，就应把策略挂到 waypoint 上；再用一条挂到 workload 的策略让 ztunnel 强制「必须来自我的 waypoint」。

```yaml
spec:
  selector:
    matchLabels:
      app: reviews
  action: ALLOW
  rules:
  - from:
    - source:
        principals:
        - cluster.local/ns/default/sa/reviews-svc-waypoint
```

这里刻意用 `selector` 而非 `targetRef`，让 ztunnel 在 L4 执行——**waypoint 不可用时仍能阻断**。

### waypoint Supported Resources and Stability

| 资源 | 稳定性 | 挂接方式 |
| :-- | :-- | :-- |
| `HTTPRoute` | Beta | `parentRefs` |
| `TLSRoute` / `TCPRoute` | Alpha / Alpha | `parentRefs` |
| `AuthorizationPolicy`（含 L7） | Beta | `targetRefs` |
| `RequestAuthentication` | Beta | `targetRefs` |
| `TrafficExtension`（Lua） | Alpha | `targetRefs` |
| `WasmPlugin` | Alpha | `targetRefs` |
| `VirtualService`（整体） | **Alpha** | 与 Gateway API **不可混用** |
| `EnvoyFilter` | **明确不支持** | — |

`EnvoyFilter` 的原文措辞很强硬：*"not currently supported for any existing Istio version with waypoint proxies… its use is **not supported, and is actively discouraged by the maintainers**."*

## mTLS and HBONE

### ambient Defaults to PERMISSIVE

官方原文：「The default policy for ambient mode is `PERMISSIVE`, which allows pods to accept both mTLS-encrypted traffic (from within the mesh) and plain text traffic (from without).」

### DISABLE Mode Ignored, Cannot Disable mTLS

官方两处明示：

- 「As ztunnel and HBONE implies the use of mTLS, it is **not possible to use the `DISABLE` mode** in a policy. Such policies will be ignored.」
- 迁移页把它列为 **hard blocker**：「Ambient always enforces mTLS between mesh workloads. Policies with `DISABLE` mode will be ignored and cannot be migrated.」

> [!IMPORTANT]
> **ambient 下有两层不同的加密，不能混为一谈：**
> 1. **HBONE 隧道层**（ztunnel↔ztunnel、ztunnel↔waypoint）：恒为 mTLS，**不可关闭**，端口 15008。
> 2. **端到端业务 mTLS**（`PeerAuthentication` 的 STRICT/PERMISSIVE，控制「应用 Pod 是否要求来自网格内的 mTLS」）：由 ztunnel 代 sidecar 执行；`DISABLE` 无意义被忽略。

源码印证 `PeerAuthentication` 在 ambient 下是被**转换**成 ztunnel L4 授权策略：`convertPeerAuthentication()` 把 STRICT 转成 `NotPrincipals: [Presence]` 的 DENY 规则（`staticStrictPolicyName = "istio_converted_static_strict"`），端口级例外 `portLevelMtls` 也被转成 `DestinationPorts` 规则。

## Interoperability with sidecar

**可以混用，且是官方支持的渐进迁移路径**——「ambient mesh」这个词的定义就是「以支持 ambient 的方式安装的网格，可以同时容纳两种数据面的 Pod」。

### Hard Prerequisites for HBONE Signaling

sidecar 与 ambient Pod 之间东西向互通时，sidecar 知道要用 HBONE 协议——**但有前提**：

> "For sidecar proxies to use the HBONE/mTLS signaling option when communicating with ambient destinations, they need to be configured with `ISTIO_META_ENABLE_HBONE` set to `true` in the proxy metadata. This is the default in `MeshConfig` when using the `ambient` profile."

推论：若网格用**非 ambient profile** 安装后再手工混入 ambient，`ISTIO_META_ENABLE_HBONE` 不会自动为 true，sidecar→ambient 方向可能不通。

### Three Conditions for a Pod to Be Classified as Ambient

必须同时满足：**不在** `cni.values.excludeNamespaces` 排除列表；namespace 或 pod 有 `istio.io/dataplane-mode=ambient`；pod 无 `istio.io/dataplane-mode=none`；且 pod 上**不存在**注解 `sidecar.istio.io/status`。

冲突时**sidecar 优先**（官方原文「the sidecar mode currently takes precedence for such a pod or namespace」），因此建议同一 namespace 不要混用两种标签。

> [!WARNING]
> **sidecar 工作负载调用带 waypoint 的 ambient 工作负载时，流量会完全绕过 waypoint。** 官方原文：「Traffic from sidecar mode workloads bypasses waypoint proxies… L7 policies on the waypoint are not enforced for that traffic until the source workload is also migrated to ambient mode.」
>
> 这与「双重代理冲突」不同——不是冲突，而是 **waypoint 被绕过**的语义问题。

### Migration Hard Blockers (4 Listed Officially)

1. **VM workload 不能加入 ambient**
2. **不支持 SPIRE**
3. `PeerAuthentication` 的 `mode: DISABLE` 被忽略
4. **primary-remote 多集群不支持**，仅支持多 primary

其他已知限制：存在 L7 策略时**无法零停机迁移**（存在策略不生效窗口）。

## Mesh Boundary and External Services

ambient 下一个便利特性：**waypoint 天然充当 egress gateway**。官方原文「In ambient mode, a waypoint proxy naturally acts as an egress gateway. Ztunnel automatically routes traffic to a service's waypoint before forwarding it to the destination. If you place a `ServiceEntry` in a namespace enrolled to use a waypoint, all mesh traffic to that external host passes through the waypoint automatically, **with no extra routing rules required**.」（sidecar 模式需协调 5 个对象。）

```bash
# 1. 建 egress ns 并打标签
#    istio.io/dataplane-mode=ambient
# 2. 建 waypoint 并给 ns 打 use-waypoint
istioctl waypoint apply --for service --enroll-namespace --namespace istio-egress
# 4. L7 策略用 targetRefs 指向 kind: ServiceEntry
# 4. L7 Policy Uses targetRefs Pointing to kind: ServiceEntry
# 5. TLS origination：ServiceEntry.targetPort: 443 + DestinationRule.tls.mode: SIMPLE
```

「ztunnel provides mTLS between the application pod and the egress waypoint automatically.」

**网格外（非网格）Pod** 的流量不经源节点 ztunnel，直接到目的 Pod，由**目的侧 ztunnel**执行 L4 策略——所以 ambient ns 上设 `STRICT` 会拒绝来自网格外的流量。

## Ingress and Waypoint

**Ingress Gateway 本身不需要 waypoint。** ambient profile 默认反而**禁用**了 `istio-ingressgateway`，需要时自行启用。Ingress gateway 可以跑在非 ambient namespace，并暴露 ambient / sidecar / 非网格 Pod 的服务。

**Ingress 流量默认不走 waypoint**，即使 Service/Namespace 设了 `istio.io/use-waypoint`。开启方式：

```bash
kubectl label service reviews istio.io/ingress-use-waypoint=true
```

效果是**两跳 L7**（先 ingress gateway，再 destination waypoint）。控制面需启用 `ENABLE_INGRESS_WAYPOINT_ROUTING`，**默认 `false`**（此默认值只见于官方文档，1.31.1 源码中未找到注册点，若要用于生产建议实测确认）。该行为自 Istio 1.25 起支持。

> [!NOTE]
> ztunnel 的负载均衡是**内部固定的 L4 Round Robin，用户不可配置**，且**独立于 `VirtualService.TrafficPolicy`**。这是官方 troubleshoot 页明确列出的「代理行为不符合预期但无报错」的原因之一。

## Troubleshooting

### `istioctl ztunnel-config` (Alias `zc`)

> [!WARNING]
> **主命令名是单数**（`service` / `policy` / `certificate`），复数形式是别名。这是很容易写错的地方。

| 子命令 | 别名 |
| :-- | :-- |
| `workload [<type>/]<name>[.<namespace>]` | `w`、`workloads` |
| `service` | `services`、`s`、`svc` |
| `certificate` | `certificates`、`certs`、`cert` |
| `policy` | `policies`、`p`、`pol` |
| `connections [<type>/]<name>[.<namespace>]` | `cons` |
| `log [<type>/]<name>[.<namespace>]` | `o` |
| `all` | — |

常用 flag：`-o/--output`（默认 `summary`，可选 `json|yaml|short`）、`--proxy-admin-port`、`--node`、`-f/--file`、`--direction`（inbound/outbound）、`--raw`、`--service-namespace`、`--policy-namespace`、`--workload-namespace`、`--workload-node`、`--address`、`-r/--reset`、`--level`。

### Official Troubleshooting Commands

```bash
# 看 ztunnel 追踪到的 workload（含 WAYPOINT / PROTOCOL 列）
istioctl ztunnel-config workloads

# 看证书
istioctl ztunnel-config certificates "$ZTUNNEL".istio-system

# 一次性看全部
istioctl ztunnel-config all -o json

# ztunnel 原始 config_dump（绕 istioctl）
kubectl debug -it $ZTUNNEL -n istio-system --image=curlimages/curl -- \
  curl localhost:15000/config_dump

# istiod 侧 ztunnel xDS 资源（端口 15014，按 proxyID）
export ISTIOD=$(kubectl get pods -n istio-system -l app=istiod -o=jsonpath='{.items[0].metadata.name}')
kubectl debug -it $ISTIOD -n istio-system --image=curlimages/curl -- \
  curl localhost:15014/debug/config_dump?proxyID="$ZTUNNEL".istio-system

# 确认走了 HBONE
kubectl -n istio-system logs -l app=ztunnel | grep -E "inbound|outbound"
```

日志关键字段：`dst.addr`、`dst.hbone_addr`、`dst.service`、`dst.workload`、`dst.identity`、`direction`、`bytes_sent`、`bytes_recv`、`duration`。典型现象是 `dst.addr="10.244.1.10:15008"` 而 `dst.hbone_addr="10.244.1.10:9080"`——先打 HBONE 端口再由 ztunnel 转到真实端口。

waypoint 侧排障（官方 5 步）：

```bash
istioctl analyze
istioctl ztunnel-config service      # 确认 service 实际用的哪个 waypoint
istioctl ztunnel-config workload     # 确认 pod 实际用的哪个 waypoint
istioctl proxy-status
kubectl logs deploy/waypoint
istioctl pc log deploy/waypoint --level debug
istioctl proxy-config all deploy/waypoint
```

> [!WARNING]
> **`istioctl x describe` 不支持 ambient。** 该命令实现在 `istioctl/pkg/describe/describe.go`，注册为 `istioctl experimental describe`，子命令只有 `pod` 与 `service`（标 `[kube-only]`），**全文搜索 `waypoint` / `ztunnel` 零命中**。ambient 排障必须用 `istioctl ztunnel-config`。

### Common Fault Modes

| 故障 | 判定 / 规避 |
| :-- | :-- |
| **命名空间没打 waypoint 标签 → 流量仍走 L4** | `istioctl ztunnel-config service` 看 WAYPOINT 列是否为空；核对 `use-waypoint` 与 Gateway 的 `waypoint-for` 是否匹配 |
| **waypoint 被静默绕过** | 「waypoint does not exist or has no address」「traffic type does not match」；用只允许 waypoint 身份的 L4 策略兜底 |
| ztunnel 未正确配置 | `ztunnel-config workloads` 缺预期 workload / `certificates` 缺证书 |
| 流量重定向失效 | ztunnel 日志无 inbound/outbound 记录 |
| **K8s NetworkPolicy 阻断 HBONE** | HBONE 需 TCP **15008**；查 NetworkPolicy |
| **HBONE 抓不到该端口** | `traffic.sidecar.istio.io/excludeInterfaces` / `excludeOutboundPorts` 是 **sidecar 注入专用，ambient 无效**；ambient 侧排除机制是 `cni.values.excludeNamespaces` 与 `istio.io/dataplane-mode=none` |
| IPv6 `network is unreachable` 告警 | 单栈 IPv4 集群上无 `spec.addresses` 的 Service 会拿到双 VIP，客户端偏好 IPv6 时先失败再回退；给 ztunnel 设 `IPV6_ENABLED=false`（**默认 `true`**） |
| 代理行为不符预期但无报错 | ztunnel LB 是固定 L4 Round Robin，不可配置，独立于 `VirtualService` |

### Observability Differences

**只有 ztunnel 时仅有 4 个 L4 TCP 指标**：`istio_tcp_sent_bytes_total`、`istio_tcp_received_bytes_total`、`istio_tcp_connections_opened_total`、`istio_tcp_connections_closed_total`。**用 waypoint 才有完整 Istio/Envoy 指标集。**

## Performance Reference

官方数据（**注意版本标注为 Istio 1.24**，非 1.31；条件 1000 req/s、1 KB payload、2 worker threads）：

| 组件 | vCPU | 内存 |
| :-- | :-- | :-- |
| 单个 sidecar | ~0.20 | 60 MB |
| 单个 waypoint | **~0.25** | 60 MB |
| 单个 ztunnel | ~0.06 | **12 MB** |

延迟测试环境：5 台 M3 Large 裸金属 + Flannel，http/1.1、1 KB payload、500–1500 req/s、4 连接、启用 mTLS，对比 `no mesh` / `ambient: L4` / `ambient: L4+L7` / `sidecar` 的 P90/P99。

> [!WARNING]
> 引用这组数字**必须标注 1.24**——1.31 没有独立的 ambient benchmark 章节。且 waypoint 单实例开销**高于** sidecar，与「waypoint 更省」的直觉相反。

基准工具：fortio.org、nighthawk、isotope。

## 1.31 Change Overview

**控制面 / XDS**

- XDS `Address` 变更推送**限定到受影响的 waypoint**，不再全量推送；可用 `AMBIENT_SCOPED_ADDRESS_PUSHES=false` 回退（默认启用）
- 新增 `meshConfig.serviceEntryVisibility`：ambient 默认执行可见性，classic sidecar 需额外设 `applyToSidecars`

**waypoint 可扩展性修复**

- WDS 重连改为**增量**：istiod 为每个 WDS 资源分配内容版本，重连客户端通过 `initial_resource_versions` 报告已有版本，仅重发变更部分（旧版 ztunnel 不报告版本则仍收全量）
- IPv6 集群中 headless Service 导致 waypoint LDS 含空 `IPMatcher.RangeMatcher.ranges`，被 Envoy 1.38 严格校验拒绝 → LDS 推送失败（Issue #60310）
- `publishNotReadyAddresses: true` 与 `PreferSameZone`/`PreferSameNode` 组合会污染 ztunnel health policy 为 `AllowAll`，流量被路由到未就绪 endpoint（Issue #60422）
- 无 VirtualService 时 waypoint 上 `consistentHash` 失效（Issue #61045，workaround 是加空 VirtualService）
- 应用 ns 中经 `targetRefs` 指向 Service 的 `WasmPlugin` 导致 waypoint **crash-loop**：LDS 路径纳入了插件但 ECDS 查找判定为跨 namespace 而拒绝，Envoy 永远等不到资源（Issue #60530）
- 跨 ns waypoint 未包含 ns 级 `Telemetry`（Issue #60665）
- `meshConfig.defaultHttpRetryPolicy` 现在适用于 waypoint 本地服务（Issue #60682）
- 多网络 ambient ingress 跨网络调 service 时现在**会**路由到 waypoint——但仅当 Service 设了 `istio.io/ingress-use-waypoint`
- ingress gateway 对跨网络远端 workload 的服务绕过 waypoint 导致授权未强制（Issue #61092）

**ztunnel / CNI**

- 新增 `ZTUNNEL_RESOURCE_CPU_LIMIT` / `_REQUEST` 环境变量
- 启动时检测内置 `nft` 是否支持 JSON 输出，不支持则**回退 `iptables` 后端**（否则每次 pod 移除都报 `JSON support not compiled-in` 并无限重试）
- 修复同节点两 Pod 同时入网的 `concurrent map writes` panic、启动 deadlock、Pod 删除与重连并发导致 ZDS 永久阻塞、procfs 扫描 fd 泄漏、Pod 被错误配对到他人 netns 等
- **`hostNetwork` Pod 不再被视为符合 ambient 入网条件**（Issue #61168）
- 节点/kubelet 重启后 ambient Pod 丢失 health-probe ipset 成员导致探针被拒，现重新断言 ipset 成员资格
- `EXIT_ON_ZERO_ACTIVE_CONNECTIONS` 曾因 pilot-agent 把 Envoy HBONE 内部 listener 计入进程内连接数而永不触发，已修复（Issue #60728）

**跨模式变更（影响 ambient）**

- 默认发送不健康 endpoint，除非配 `minHealthPercent`；`PILOT_AUTO_SEND_UNHEALTHY_ENDPOINTS=false` 可关
- **zone-aware LB 明确不支持 ambient**（原文「It is supported in sidecar mode only, and is not supported in ambient mode.」）
- `ALLOW_ANY_DYNAMIC_DNS` 限定 sidecar，不支持 `Sidecar` CRD
- **取消固定 `nftables` 版本**（此前 pin 1.1.1）——官方建议升级节点 nftables 包，这是 1.31 的实际升级风险点

**新增 flag**：`PILOT_ENABLE_STRICT_GATEWAY_MERGING`（默认 `true`，禁止跨 ns 合并 Istio Gateway CRD 与受管 Gateway API proxy）、`PILOT_ENABLE_REMOTE_CREDENTIALS_CONTROLLER`（默认 `true`）。**均非 ambient 专属。**

## agentgateway as Waypoint

**1.31 中需要特殊 enable，默认关闭。**

```bash
istioctl install --set profile=ambient \
  --set values.pilot.env.PILOT_ENABLE_AGENTGATEWAY=true -y
```

`PILOT_ENABLE_AGENTGATEWAY` **默认 `false`**。启用后注册两个 GatewayClass：

| GatewayClass | 角色 |
| :-- | :-- |
| `istio-agentgateway` | ingress gateway |
| `istio-agentgateway-waypoint` | waypoint proxy |

（Envoy 原生 waypoint class 是 `istio-waypoint`。）

> [!NOTE]
> **`istioctl waypoint` 不支持 agentgateway。** 官方原文：子命令「currently only support the default Envoy-based `istio-waypoint` class. To deploy an agentgateway waypoint, **apply a `Gateway` resource directly**」。手写 Gateway 时唯一差别是 `gatewayClassName`，listener 仍须 `name: mesh` / `port: 15008` / `protocol: HBONE`，并保留 `istio.io/waypoint-for` label。

**关键限制**：Istio 只通过 Gateway API 配置 agentgateway——「Istio's own configuration APIs — such as `VirtualService`, `DestinationRule`, `Sidecar`, `AuthorizationPolicy`, `PeerAuthentication`, `RequestAuthentication`, `Telemetry`, `WasmPlugin`, and `EnvoyFilter` — are **not** applied to agentgateway proxies.」支持的只有 `Gateway`、`HTTPRoute`/`GRPCRoute`/`TCPRoute`/`TLSRoute`、`InferencePool`。整体状态为 **experimental**。

1.31 还修复了 agentgateway 连 sidecar 注入的 mesh backend 时用明文而非 Istio mTLS 的问题（影响 SMTP/MySQL 等 server-first 协议，`STRICT` backend 不可达）。

## Stability Status Overview

| 资源 / 名称 | 稳定性 |
| :-- | :-- |
| `istio.io/dataplane-mode`、`istio.io/use-waypoint`、`istio.io/waypoint-for`、`ISTIO_META_ENABLE_HBONE` | Stable（API 定义） |
| `istio.io/use-waypoint-namespace`、`istio.io/ingress-use-waypoint` | Beta |
| 金丝雀三件套（含整体特性） | Alpha |
| `HTTPRoute` / `AuthorizationPolicy` / `RequestAuthentication` @ waypoint | Beta |
| `TLSRoute` / `TCPRoute` / `TrafficExtension` / `WasmPlugin` @ waypoint | Alpha |
| `VirtualService` in ambient | Alpha |
| `EnvoyFilter` @ waypoint | **不支持** |
| agentgateway 集成 | experimental |

> [!NOTE]
> `istio.io/dataplane-mode` / `istio.io/use-waypoint` / `istio.io/waypoint-for` 三个在 **API 源码中是 Stable**，而 istio.io add-workloads 页的 Label reference 表里分别标为 Beta / Beta / **Alpha**。**以 API 源码定义为准**并注明差异。

## Troubleshooting Quick Reference

| 现象 | 先查 |
| :-- | :-- |
| 装了 profile 但流量不走 ambient | 是否显式 `--set profile=ambient`（非默认 profile）；`istio.io/dataplane-mode` 标签与 `sidecar.istio.io/status` 注解 |
| sidecar 调 ambient 不通 | 非 ambient profile 安装时 `ISTIO_META_ENABLE_HBONE` 不会自动为 true |
| L7 策略不生效 | 源工作负载还是 sidecar 模式会**完全绕过** waypoint；或策略是 `EnvoyFilter`（waypoint 不支持） |
| L7 策略被莫名全拒 | ALLOW 策略含 L7 属性落到 ztunnel 时 `rules = nil` → 全部拒绝；改用 `targetRefs` 挂到 waypoint |
| 策略里某些字段无效且无提示 | ztunnel 不支持 SNI；`trustDomains` / `notTrustDomains` 在 ztunnel 上静默忽略 |
| ztunnel 上按 SNI 授权不生效 | 源码确认不支持且不报错，只能靠 waypoint |
| waypoint 不生效 | `ztunnel-config service` 看 WAYPOINT 列；核对 `waypoint-for` 类型匹配 |
| 指标只有 TCP 四项 | 正常——没装 waypoint 就没有 L7 指标 |
| 代理行为不符预期 | ztunnel LB 固定 L4 Round Robin，不可配置 |
| IPv6 告警 | ztunnel 设 `IPV6_ENABLED=false`（默认 true） |
| HBONE 连不通 | 查 K8s NetworkPolicy 是否放行 TCP 15008；`excludeInterfaces` 是 sidecar 专用无效 |
| `waypoint edit` 报错 | 该子命令不存在，用 `kubectl edit gateway` |
| 升级后 CNI 报 `JSON support not compiled-in` | 升级节点 nftables 包（1.31 取消固定版本） |

## Links

- [Istio](/docs/CS/Framework/Istio/Istio.md)
- [Envoy](/docs/CS/Framework/Istio/Envoy.md)
- [Security](/docs/CS/Framework/Istio/Security.md)
- [Install](/docs/CS/Framework/Istio/Install.md)
- [Observability](/docs/CS/Framework/Istio/Observability.md)
- [Performance](/docs/CS/Framework/Istio/Performance.md)
- [WasmPlugin](/docs/CS/Framework/Istio/WasmPlugin.md)
- [Kubernetes Service](/docs/CS/Container/k8s/Service.md)

## References

- <https://istio.io/latest/docs/ambient/overview/>
- <https://istio.io/latest/docs/ambient/getting-started/>
- <https://istio.io/latest/docs/ambient/install/istioctl/>
- <https://istio.io/latest/docs/ambient/usage/waypoint/>
- <https://istio.io/latest/docs/ambient/usage/l4-policy/>
- <https://istio.io/latest/docs/ambient/usage/l7-features/>
- <https://istio.io/latest/docs/ambient/usage/troubleshoot-ztunnel/>
- <https://istio.io/latest/docs/ambient/usage/troubleshoot-waypoint/>
- <https://istio.io/latest/docs/ambient/migrate/>
- <https://istio.io/latest/docs/ops/deployment/performance-and-scalability/>
- <https://api.github.com/repos/istio/istio/releases/latest>
