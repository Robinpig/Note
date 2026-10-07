## Introduction

Istio 的安装、升级与 sidecar 注入是运维最高频也最容易踩坑的环节。这一篇把**版本对齐规则、两条注入路径、revision 升级、流量捕获端口**逐条核实清楚，重点标注那些「文档没写但源码里写着」的事实——它们才是排障时真正用得上的。

> [!NOTE]
> 版本基线：Istio **1.31.1**（2026-09-21），1.31.0 于 2026-08-31 发布，官方支持 Kubernetes **1.32 ~ 1.36**。本文所有默认值来自 `release-1.31` 分支源码与官方 install/upgrade/canary 文档，未使用记忆值。

## Installation Method Selection

官方给出三种安装路径，FAQ 明确排序：

| 方式 | 官方定位 | 优点 | 缺点 |
| :-- | :-- | :-- | :-- |
| **`istioctl install`** | 「**社区对多数场景的推荐方式**」 | 配置校验与健康检查最全面 | 每个 minor 需各自管理二进制；`istioctl` 会按运行环境自动设 values，**不同 K8s 环境可能产生不同安装结果** |
| Helm | 契合 Helm 工作流，升级时自动 prune | 与既有 Helm 流程一致 | 「相比 `istioctl install` 更少的检查与校验」 |
| 预生成 manifest | 严格审计场景 | 完全可复现 | **无安装期检查、无环境探测、无校验、无升级能力** |

`manifest generate` 有 6 条官方注意事项，其中三条最容易踩：

- **默认不创建 `istiod-default-validator`**（不像 `istioctl install`），除非 `--set values.defaultRevision=default`。
- **无自动 prune**——变更后应删除的资源不会被清理。
- 官方原话：「**This method is not tested as part of Istio releases.**」

```bash
istioctl manifest generate > $HOME/generated-manifest.yaml   # 1.31 新增 -o 可直接写文件
```

### Istio Operator Deprecated (A Legacy Trap to Avoid)

- **集群内 Operator 控制器在 Istio 1.23 即弃用，1.24 随发布移除**。官方原话：Operator 方式安装「**可以无限期继续运行，但无法升级超过 1.23.x**」。
- 判定方法：`kubectl get deploy -n istio-system istio-operator` 与 `kubectl get IstioOperator` **两者都非空**即受影响。
- 官方估计受影响用户「fewer than 10%」，且早在 1.12（2021）文档就不再鼓励新装。
- **关键区分**：`IstioOperator` 这个 **CRD / API 本身没有废弃**——`istioctl install` 至今仍通过它接收配置。废弃的只是**集群内运行的 operator 控制器**。
- 迁移：`istioctl manifest translate -f istio.yaml` 转 Helm values；社区的 Classic Operator Controller / Sail Operator **均不受 Istio 项目支持**。

### Installation Practice Key Points

- **`--set` 与 `-f` 等价，但生产强烈建议用 `-f`**。
- **Helm values 路径必须加 `values.` 前缀**：`--set` 语义与 Helm 一致，legacy 路径要加前缀。
- **revision 名不能含 `.`**：1.31.1 必须写 `revision=1-31-1`。
- 外部 charts：1.31.1 的 compiled-in charts 就在 release tar 的 `manifests` 目录，`istioctl install --manifests=manifests/` 与直接 `istioctl install` 结果相同，**官方建议优先用 compiled-in**。
- 卸载：`istioctl uninstall --purge`（含 cluster-scoped 资源）；只卸单个控制面用 `istioctl uninstall <原安装参数>`。

## Component Composition and Naming Traps

`release-1.31` 分支的实际二进制入口：

| 组件 | 源码路径 | 部署形态 |
| :-- | :-- | :-- |
| **istiod** | `pilot/cmd/pilot-discovery/main.go` | Deployment / Service 名均为 `istiod`；`istioctl` 侧历史称 `pilot-discovery` |
| **pilot-agent** | `pilot/cmd/pilot-agent/main.go`（内部库 `pkg/istio-agent`） | 注入后容器名 `istio-proxy` |
| **CA** | `pilot/pkg/bootstrap/server.go` 中 `Server` 直接持有 `CA *ca.IstioCA` | **内嵌 istiod，非独立组件** |

三个易混点：

1. **`pilot-discovery` 与 `istiod` 是同一个二进制**。
2. **`pilot-agent` 与 `istio-agent` 是同一组件**——进程名 `pilot-agent`，库包名 `istio-agent`，容器名 `istio-proxy`。**不存在名为 `istio-agent` 的独立容器**。
3. **不存在独立的 CA 组件**：官方架构页 Components 一节只列 Envoy 与 Istiod 两项，并明确「Istiod acts as a Certificate Authority (CA)」。Citadel 只作为**代码库**（`pkg/security`）存在。

### istiod Ports (Source Flag Defaults)

官方文档站当前**没有** istiod 端口参考页（`/docs/ops/reference/ports/` 等均 404），下表全部来自 `pilot/cmd/pilot-discovery/app/cmd.go`：

| Flag | 默认值 | 作用 |
| :-- | :-- | :-- |
| `--httpAddr` | `:8080` | HTTP / debug（含 `/debug`） |
| `--httpsAddr` | `:15017` | HTTPS |
| `--grpcAddr` | `:15010` | xDS gRPC（明文） |
| `--secureGRPCAddr` | `:15012` | xDS gRPC over mTLS |
| `--monitoringAddr` | `:15014` | monitoring / metrics |

Service 里另有 `443/TCP`（webhook）。`15017` 兼具健康检查，`istioctl` 排障时常用。

## xDS Push Mechanism

### Long Connection and ADS

- Envoy bootstrap 中 CDS/LDS 均配 `"ads": {}`，**聚合为单一 ADS 流**（`A single ADS stream is available per Envoy instance`）。
- istio-agent 同时实现 SotW 与 Delta 两套代理（`xds_proxy.go` / `xds_proxy_delta.go`），源码注释：「**Depending on how Envoy connects we will use one or the other.**」

### Delta xDS is Default (Correcting a Common Misconception)

`pilot/pkg/features/experimental.go:169`：

```go
DeltaXds = env.Register("ISTIO_DELTA_XDS", true, ...)
```

- **默认 `true`**，即 **Delta xDS 是默认行为**。SotW 需显式设 `ISTIO_DELTA_XDS=false`。
- Waypoint（`waypoint~` 前缀节点）**强制** `DELTA_GRPC`；MDS（metadata discovery）在 SotW 下会被主动关闭并打 warning。
- 官方注明：即使启用 delta，**仍可能偶尔发送未变更的配置**，并非严格只发增量。
- Delta xDS **只支持 gRPC 双向流**（无 REST 版本）；SotW 则支持 gRPC、REST-JSON 等。

### 8 xDS Resource Types

常被误认为只有 5 种，官方完整枚举是 8 种：**LDS**（Listener）、**RDS**（RouteConfiguration）、**SRDS**（ScopedRouteConfiguration）、**VHDS**（VirtualHost）、**CDS**（Cluster）、**EDS**（ClusterLoadAssignment）、**SDS**（Secret）、**RTDS**（Runtime）。

两个关键区分：

- **Delta xDS 不是资源类型，是更新方式；ADS 不是资源类型，是传输聚合方式**（ADS 无独立 type URL）。
- **SDS 在 Istio 语境下不由 istiod 下发**——证书由 istiod 内嵌 CA 经 Envoy **本地 SDS 管道**提供。

`istioctl proxy-status` 的输出列正是 `CDS / LDS / EDS / RDS / ECDS`：

```
NAME      CLUSTER     CDS     LDS     EDS     RDS     ECDS      ISTIOD             VERSION
curl-...  Kubernetes  SYNCED  SYNCED  SYNCED  SYNCED  NOT SENT  istiod-1-31-1-...  1.31.1
```

## Sidecar Injection

### Two Paths

官方推荐**自动注入**（namespace 级 mutating webhook），原话：「If you are not sure which one to use, automatic injection is recommended.」

标签语义（1.31 现行）：

| 资源 | 启用 | 禁用 |
| :-- | :-- | :-- |
| Namespace | `istio-injection=enabled` | `istio-injection=disabled` |
| Pod | `sidecar.istio.io/inject="true"` | `sidecar.istio.io/inject="false"` |
| Namespace（revision） | `istio.io/rev=canary` | — |
| Pod（revision） | `istio.io/rev=canary` | — |

- **`istio-injection` 优先级高于 `istio.io/rev`**（向后兼容保留）。canary 升级时必须先 `kubectl label namespace test-ns istio-injection- istio.io/rev=canary`。
- 三条判定：任一标签禁用 → 不注入；任一启用 → 注入；**都未设置** → 仅当 `sidecarInjectorWebhook.enableNamespacesByDefault` 开启才注入，**该值默认未开启**。
- 自动注入是 **pod 级**的，Deployment 本身不变，注入后 Pod 从 `1/1` 变 `2/2`。
- in-place 注入 `istioctl kube-inject` 仍受支持，是次选路径。离线注入需先从集群导出三份配置：`istio-sidecar-injector` 的 `config` 与 `values`、configmap `istio` 的 `mesh`。

### Containers and iptables Ports After Injection

`istio-init` 容器**确实存在**，以 **init container** 形式运行。端口常量来自 `tools/common/config/config.go` 与 `tools/istio-iptables/pkg/constants/constants.go`：

| 端口 | 常量 | 作用 |
| :-- | :-- | :-- |
| **15001** | `ProxyPort` | 出向 TCP 重定向目标（`nat` 表 `ISTIO_REDIRECT`） |
| **15006** | `InboundCapturePort` | 入向明文重定向目标 |
| **15008** | `InboundTunnelPort` | **HBONE** 隧道入向端口 |
| 15002 | `DefaultIptablesProbePortUint` | iptables 失败探测 |
| **15053** | `IstioAgentDNSListenerPort` | istio-agent DNS 代理；TCP/UDP 53 被重定向至此 |
| 1338 | `OutboundMark` | 出向流量 mark |
| 15021 / 15090 | 静态保留监听 | 与虚拟监听端口（15001/15006）冲突检查 |

> [!WARNING]
> **15004 在 1.31 源码与官方文档中均检索不到**（已查 `tools/istio-iptables/` 全部文件、`pilot/pkg/networking/core/`、`pilot/pkg/model/context.go`）。网上流传的 15004 端口表不可信，排查时不要以它为依据。

端口保留链：`ISTIO_OUTPUT`、`ISTIO_OUTPUT_DNS`、`ISTIO_INBOUND`、`ISTIO_DIVERT`、`ISTIO_TPROXY`、`ISTIO_REDIRECT`、`ISTIO_IN_REDIRECT`、`ISTIO_DROP`。

### Two Inbound Capture Modes

`tools/istio-iptables/pkg/capture/run.go` 实际逻辑：

- **REDIRECT（默认）**：`nat` 表按 `--dport` 逐端口分流，命中 `ISTIO_IN_REDIRECT`。
- **TPROXY**：`mangle` 表 `TPROXY` target，链 `ISTIO_TPROXY`，所有入向包打上 `INBOUND_TPROXY_MARK`，可保留源地址。
- 对应注解 `sidecar.istio.io/interceptionModes`（Alpha）。

**HBONE 端口语义**（官方明文）：「ztunnel and other proxies that understand the HBONE protocol expose listeners on TCP port **15008**」。HBONE = **HTTP/2 + HTTP CONNECT + mTLS** 三标准组合。流量重定向规则：目的端口 == 15008 → HBONE 监听端口；否则 → 明文端口 15006；出向一律 → 15001。

### Traffic Capture Annotations (All Alpha, Pod-Level)

| 注解 | 语义要点 |
| :-- | :-- |
| `includeInboundPorts` | 通配 `*` = 全部端口重定向；**空列表 = 禁用全部入向重定向** |
| `excludeInboundPorts` | **仅当全部入向（`*`）被重定向时才生效** |
| `includeOutboundPorts` | 无论目标 IP 均重定向 |
| `excludeOutboundPorts` | 排除的出向端口 |
| `includeOutboundIPRanges` | CIDR；通配 `*` = 全部；**空列表 = 禁用全部出向重定向** |
| `excludeOutboundIPRanges` | **仅当全部出向（`*`）被重定向时才生效** |
| `excludeInterfaces` | 排除被捕获的接口 |
| `kubevirtInterfaces` | **已弃用**，改用 `istio.io/reroute-virtual-interfaces` |

「仅当全部被重定向时才生效」是常见误解来源：设了 `excludeInboundPorts` 但没设 `includeInboundPorts: "*"`，该注解**不起作用**。

### Resource Annotation Traps

- 设 `sidecar.istio.io/proxyCPU` 而不设 `proxyCPULimit` → **CPU limit 变为 unlimited**；内存同理（`proxyMemory` 无 `proxyMemoryLimit` → unlimited）。
- **TPROXY 模式下 `securityContext.RunAsUser`/`RunAsGroup` 可能不被尊重**（TPROXY 要求 sidecar 以 uid 0 运行），配置不当会**导致流量丢失**。
- `kube-system`、`kube-public` 命名空间**豁免**自动注入；`hostNetwork: true` 的 Pod 也会被跳过（sidecar 模型假设 iptables 改在 Pod 内）。

## Upgrade

### in-place vs revision Rule Differences

| 维度 | in-place（`istioctl upgrade`） | revision（canary） |
| :-- | :-- | :-- |
| 跨 minor | **必须逐个 minor 升级**（已装版本距目标 ≤ 1 个 minor） | **可跨 2 个 minor**（如 1.15 → 1.17） |
| 官方评价 | — | 「比 in-place 安全得多，**是推荐的升级方法**」 |
| 数据面重启 | 需手动 `kubectl rollout restart` | 改 `istio.io/rev` 标签 + 重启 Pod |

in-place 前置条件与步骤：

```bash
kubectl config view
istioctl x precheck
istioctl upgrade
kubectl rollout restart deployment   # 必须手动重启数据面
```

- **必须用新版本的 istioctl**；**必须复用原安装参数**——用 `--set` 装的**必须传相同的 `--set`，否则自定义会被回退**。
- 中断风险：官方原文「Traffic disruption may occur」，建议 istiod ≥2 副本 + PDB `minAvailable: 1`。
- 降级规则对称，且必须用对应目标版本的 istioctl。

### revision Mechanism Two Key Points

- 每个 revision 是**完整的独立控制面**（自己的 Deployment、Service、MutatingWebhookConfiguration）。
- **`default` tag 有额外语义**：为 `istio-injection=enabled` / `sidecar.istio.io/inject=true` / `istio.io/rev=default` 注入 sidecar、执行 Istio 资源校验、并从非 default revision 抢 leader lock 执行单例网格职责（如更新资源 status）。
- tag 机制可避免反复改命名空间标签：`istioctl tag set prod-stable --revision 1-31-1 --overwrite`。
- 若在已有非 revision 安装旁使用 default tag，官方建议删除旧的 `MutatingWebhookConfiguration`（通常名为 `istio-sidecar-injector`），避免新旧控制面同时注入。

### Compatibility Versions

```bash
istioctl install --set values.compatibilityVersion=1.30
```

「装 1.31，但行为像 1.30」。仅应作为临时措施；被引用的 release 到达 EOL 后该 compatibility version 即被移除。检测：`istioctl x precheck --from-version 1.30`。

## 1.31 Upgrade Breaking Changes

官方 upgrade-notes 共 6 条，其中三条会造成实际故障：

### ① Sends Unhealthy Endpoints by Default

> 「By default, Istio now **sends unhealthy endpoints** unless `OutlierDetection.minHealthPercent` is configured on a Service.」

这是**行为变更**而非新功能。关闭：`PILOT_AUTO_SEND_UNHEALTHY_ENDPOINTS=false` 或用 compatibility profile。

### ② HBONE Tunnel Label Requires Re-Registration

HBONE tunnel label **仅在 WorkloadEntry 自动创建时应用**。**升级前自动注册的 workload 将持续以明文被访问**，直到重连新实例或手动给现有 WorkloadEntry 加 `networking.istio.io/tunnel=http`。

### ③ WDS Reconnect Requests Grow in Large ambient Meshes

ztunnel 重连时会报告其持有的**每个 workload 的 name 与 version**，该请求可超过 istiod 默认 **4MiB** gRPC 接收上限，ztunnel 陷入 `ResourceExhausted: grpc: received message larger than max` 重连循环。**触发点从约 55,000 workload 降至约 40,000**（本次多报 version，约增长 1/3）。

```bash
istioctl install --set pilot.env.ISTIO_GPRC_MAXRECVMSGSIZE=33554432   # 32MiB，可覆盖 30 万+ 资源
```

官方预算参考：每 10,000 workload/service 约 1MiB。

### ④ The Other Three

- **`PILOT_SPAWN_UPSTREAM_SPAN_FOR_GATEWAY` 已被移除**：其行为（gateway 用 Telemetry API 时为每个 upstream 请求生成独立 span）**现已总是启用**，曾显式设 `false` 的用户失去该退出选项。
- **GCP 制品渠道退役**（详见 Istio.md 的 1.31 变更节）。
- **XDS API generator 现需控制面身份**：来自非系统命名空间的自定义 MCP consumer 会被拒绝；标准 sidecar/gateway/ztunnel 流量不受影响。恢复旧行为设 `ENABLE_XDS_API_GENERATOR_AUTH=false`。

## 1.31.1 Security Fixes

- **CVE `GHSA-qm8v-g4f9-qhjx`（CVSS 6.8, Moderate）**：`BackendTLSPolicy` 在 sidecar 上当 CA 引用无法解析时 **fail open 降级到明文**。
- `RequestAuthentication` 的 `jwksUri` 抓取存在 **SSRF 缺口**：现默认在 dial 层阻断 link-local 与已知云元数据地址（如 `169.254.169.254`），并拒绝非法 JWKS 响应；私有与回环段仍可达，可用 `BLOCKED_CIDRS_IN_JWKS_URIS` 阻断。
- Gateway API 跨 namespace `certificateRef`/`caCertificateRef` 在 `ReferenceGrant` 授权检查**之前**被解析，可通过 `ResolvedRefs` 状态区分 Secret/ConfigMap 是否存在（信息泄露）；现改为**先鉴权**，未授权一律返回 `RefNotPermitted`。
- `istio.io/use-waypoint-canary` 标签**绕过 `serviceEntryVisibility` 的 NAMESPACE 隔离**。
- 多个 `sidecar.istio.io/*` 注解（`proxyImage`、`bootstrapOverride`、`logLevel` 等）在注入模板中**未做输出转义**，可注入额外 Pod/Deployment 字段；现已统一转义。
- `istioctl analyze` 用 multicluster secret 构建 K8s client 时**未净化 kubeconfig**，可被构造的 secret 执行 `exec` credential plugin。
- 修复无法清空 CRL（指定空串或删除 `ca-crl.pem`）。
- 修复 JWKS resolver 被强制 HTTP/1.1（自定义 `TLSClientConfig` 使 Go 禁用自动 HTTP/2）导致经 HTTP CONNECT 代理的抓取失败。
- Kiali addon 升至 **v2.31.0**（1.31.0 时为 v2.26.0）。

## Troubleshooting Quick Reference

| 症状 | 优先检查 |
| :-- | :-- |
| sidecar 未注入 | namespace 的 `istio-injection` / `istio.io/rev`；`enableNamespacesByDefault` 是否开启 |
| 注入后 Pod 一直 `0/1` 或 CrashLoop | 代理容器 CPU/内存 limit 变 unlimited；`statsFlushInterval` 注解是否 ≥1 分钟（1.31.1 前会生成非法 bootstrap） |
| 流量不进 sidecar | `excludeInboundPorts` 是否漏了配套的 `includeInboundPorts: "*"` |
| 开了 TPROXY 后流量丢失 | `runAsUser` 是否非 0（TPROXY 要求 uid 0） |
| 升级后 ambient 大规模重连失败 | `ISTIO_GPRC_MAXRECVMSGSIZE` 是否够（4MiB 默认在 4 万 workload 即触发） |
| 升级后 mesh 内部分服务被明文访问 | 自动注册的 WorkloadEntry 缺 `networking.istio.io/tunnel=http` |
| `proxy-status` 某列 `NOT SENT` | 该资源类型对该 workload 不适用（如无路由则 RDS NOT SENT 属正常） |

## Links

- [Istio](/docs/CS/Framework/Istio/Istio.md)
- [Envoy](/docs/CS/Framework/Istio/Envoy.md)
- [Security](/docs/CS/Framework/Istio/Security.md)
- [Kubernetes](/docs/CS/Container/k8s/K8s.md)
- [Helm](/docs/CS/Container/k8s/Helm.md)
- [Pod](/docs/CS/Container/k8s/Pod.md)

## References

- <https://istio.io/latest/docs/setup/install/istioctl/>
- <https://istio.io/latest/docs/setup/additional-setup/sidecar-injection/>
- <https://istio.io/latest/docs/setup/upgrade/canary/>
- <https://istio.io/latest/docs/setup/upgrade/in-place/>
- <https://istio.io/latest/news/releases/1.31.x/announcing-1.31/upgrade-notes/>
- <https://istio.io/latest/news/releases/1.31.x/announcing-1.31.1/>
- <https://istio.io/latest/blog/2024/in-cluster-operator-deprecation-announcement/>
- <https://istio.io/latest/docs/reference/config/annotations/>
