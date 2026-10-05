## Introduction

服务网格在 2026 年已经明显分化：Istio 占据「事实标准」位置，Linkerd 守着轻量安全路线，Cilium 走 eBPF 路线，而云厂商托管网格则普遍**落后上游若干个 minor**。更值得注意的是几件事已经发生但认知还停在旧状态：Open Service Mesh 已被 CNCF 归档、AWS App Mesh 已终止支持、agentgateway 归属已变更。

> [!NOTE]
> 核实时间 2026-10。版本号均取自 GitHub API `/releases/latest` 现场请求。**托管网格普遍落后上游**：上游 Istio 已到 1.31.1，而 Google Cloud Service Mesh 到 1.30.4、阿里云 ASM 到 1.29、Azure AppNet 到 1.30.3、AKS add-on 到 1.29。

## 竞品横评

| 项目 | 归属 | 最新版本 | 状态 |
| :-- | :-- | :-- | :-- |
| **Istio** | CNCF **Graduated** | 1.31.1（2026-09-21） | 事实标准，生态最完整 |
| **Linkerd** | CNCF **Graduated** | 稳定版 `version-2.20`（2026-06-22）；edge `edge-26.9.3`（2026-09-16） | 活跃 |
| **Cilium Service Mesh** | CNCF **Graduation level** | v1.20.2（2026-09-16） | 非常活跃，**但 mTLS 仍 Beta** |
| **Consul Connect** | **IBM**（2025-02 完成收购） | v2.0.4（2026-09-10） | 活跃，版本策略已改 |
| **Open Service Mesh** | CNCF | v1.2.4（2023-04-20） | ⚠️ **已归档** |
| **AWS App Mesh** | AWS | — | ⚠️ **已终止支持** |

### Linkerd

CNCF **毕业项目**（2017-01 进入，2018-04 Incubating，**2021-07-28 Graduated**）。定位「Ultralight, security-first service mesh for Kubernetes」，核心卖点是轻量与安全优先。

维护活跃度：GitHub `pushed_at` 2026-10-02，未归档，11.5k stars。CNCF LFX 健康度 **Healthy (76)**，但贡献者 1,008（同比 **-12%**）、贡献组织 295（**-13%**）、GitHub stars 619（**-28%**）——社区增速在放缓。

> [!NOTE]
> CNCF 项目页的 star 数（619）与 GitHub 仓库 star 数（11,507）**口径不同**，写笔记时不要混用。

**未查到**：Linkerd 的 Istio ambient 模式兼容能力、Service Mesh Performance 证书状态、与 Istio 的互操作方案。

### Cilium Service Mesh（eBPF 路线）

Cilium **1.12（2022-07-20）整体 GA**，其中包含「完全无 sidecar」的 Cilium Service Mesh，同时保留既有基于 sidecar 的 Istio 集成；1.12 引入 `CiliumEnvoyConfig`（CEC）CRD 直接编程 Envoy 做高级 L7。当前版本 v1.20.2，`pushed_at` 2026-10-04（核实时当天），25.6k stars，CNCF Graduation level。

> [!WARNING]
> **「Cilium Service Mesh 是否 GA」需要分层回答**：Cilium 整体（含 sidecar 模式 + CEC）自 **1.12（2022-07）GA**；但**sidecarless 的互认证 mTLS 截至 1.20.2 仍为 Beta**——官方文档明确标注「Mutual Authentication (**Beta**) ... This feature is still incomplete」，跟踪 Issue **#28986**。

mTLS 的四条硬限制：

1. 仅支持 **SPIFFE API** 管理证书；
2. **仅在 Cilium 管理的集群内有效，与外部 mTLS 方案不兼容**；
3. **无跨集群单一 trust domain 方案**——「clusters connected in a Cluster Mesh are not currently compatible with Mutual Authentication」；
4. 仅用自带 SPIRE 安装验证过，其他 SPIFFE 实现不支持。

Roadmap 中 SPIFFE/SPIRE 集成、agent 认证 API、agent 间 mTLS 握手、per-identity 握手 auth cache、CiliumNetworkPolicy 支持**均为 Beta**；与 WireGuard 集成、per-connection 握手、ipcache 同步、渗透测试等仍为 TODO。

Cilium 官方有与 **Istio ambient 模式**及 sidecar 模式的集成文档——两者可共存。

### Consul Connect（IBM）

**IBM 于 2025-02-27 完成对 HashiCorp 的收购**，2025-09-01 起业务运营转移。Connect **仍在维护，未废弃**：Consul server agent 默认启用 service mesh，内置 CA 强制 sidecar 间 mTLS，内置 Envoy，支持 K8s/VM/ECS/Lambda/Nomad。

**版本策略在 2.0.0 改变**：从语义化版本（X.Y.Z）改为 IBM 的 **V.M.F 模型**——V=版本里程碑（开启新支持周期）、M=修改里程碑（加功能不开启新周期）、F=月度修复。2.0.x 计划 EOL **2028-04-30**（Extended Support 2029-04，Ongoing 2032-04）；1.22.x EOL 2026-10-31；**1.21.x 是最后一个 LTS**。

2.0.x 的 mesh 相关能力：Enterprise 多端口服务网格路由（`proxy.local_service_ports`、`proxy.upstreams[].destination_port`，透明代理下可用 `<>.<virtual>.consul` 虚拟地址）、**Cyber Ark Workload Identity Manager (Venafi Firefly) 作为 mesh CA provider**、新增 mesh/agent TLS 证书过期与续期遥测（经 `/agent/metrics`）。

升级硬门槛：升到 Enterprise 2.0.x 须先到 **1.21.7+** 且已应用 **IBM Consul Enterprise 许可**；用 HashiCorp 签发的许可直接升 2.0.x 或从 1.21.7 之前直升会**导致 agent 无法启动**。API Gateway 用户须把 Gateway/HTTPRoute/TCPRoute/ReferenceGrant 迁移到 `consul.hashicorp.com` 资源类型。

2.0.1 值得记的修复：Envoy 升级至 1.37.4/1.36.8/1.35.12；**connect 转发到本地服务实例前剥离入站 HTTP 请求的 `x-forwarded-client-cert` 头**（防止身份信息泄漏给非网格侧）。

**未查到**：Connect 是否有明确 EOL 时间表、L7 能力是否被标记限制或弃用、与 Istio/Linkerd 的互操作方案。

### Open Service Mesh：已归档

> [!WARNING]
> **OSM 已被 CNCF 正式归档**（不是仅 Microsoft 停更）。仓库 README 顶部横幅：「**⚠️ The OSM project has been officially archived by the CNCF. There will be no more new development on any repo under the OpenServiceMesh organization.⚠️**」；「There are no more community meetings for this project」。

证据边界：GitHub API 返回 `archived: true`；最后 release `v1.2.4`（**2023-04-20**）；最后代码活动 `pushed_at` **2023-07-11**（约 3 年前）。

**未查到**：精确归档日期（仅有上述边界证据，**不建议在笔记中写具体归档日期**）；**README 归档公告未列出官方推荐的迁移去向**（第三方提及 Kuma 等，非官方）。

## 微软：两条并行产品线

当前微软有**两条并行的 Istio 托管线**，容易混淆：

**(a) AKS Istio-based add-on**（长期存在，revision 命名 `asm-1-XX`）

| revision | 上游 Istio | AKS 发布 | EOL | 兼容 AKS |
| :-- | :-- | :-- | :-- | :-- |
| `asm-1-27` | 1.27 | 2025-09 | ~2026-05 | 1.29~1.35 |
| `asm-1-28` | 1.28 | 2026-01 | ~2026-08 | 1.30~1.35 |
| `asm-1-29` | 1.29 | 2026-04 | ~2026-09 | 1.31~1.35 |

**当前最高为 `asm-1-29`（Istio 1.29），尚未支持 Istio 1.30/1.31。**

**(b) Azure Kubernetes Application Network（AppNet）—— 全新产品线，public preview**

| AppNet | 内置 Istio | 兼容 AKS |
| :-- | :-- | :-- |
| 1.3 | 1.28 | 1.30~1.35 |
| 1.4 | 1.29 | 1.31~1.35 |
| **1.5** | **1.30**（1.30.3） | — |

差异化能力：**`AppLink`**（跨集群/跨订阅 mesh 连接）、Managed Gateway API、**Entra（AAD）托管身份认证**。注意 **AppNet 资源不支持跨资源组/跨订阅移动**。AppNet 1.0/1.1/1.2 已退役。

「Open Service Mesh for Azure」这一产品名**未查到**任何官方资料——OSM 归档后微软未以该名延续。

## 云厂商托管网格

### AWS App Mesh：已终止支持

官方公告（页面顶部 Important 框重复两次）：

> 「**End of support notice: On September 30, 2026, AWS will discontinue support for AWS App Mesh. After September 30, 2026, you will no longer be able to access the AWS App Mesh console or AWS App Mesh resources.**」

> [!WARNING]
> **迁移目标需纠正：不是 EKS Service Mesh，而是 Amazon ECS Service Connect。** 官方文档指向的迁移路径是 "Migrating from AWS App Mesh to Amazon ECS Service Connect"——ECS 原生服务连接，不是网格。App Mesh 既未被 EKS Service Mesh 取代，也未被 K8s SIG Mesh 取代。

**EKS Service Mesh 未查到官方文档**：`https://docs.aws.amazon.com/eks/latest/userguide/eks-service-mesh.html` **被重定向到 "What is Amazon EKS?"**，无法确认存在性与状态。第三方提到的 "Tetrate Curated Instance of Istio for EKS"、"VPC Lattice 替代 App Mesh" 等均非 AWS 官方 EKS 文档，不予采信。

AWS 当前实际布局：① **ECS Service Connect**（App Mesh 官方后继）；② **VPC Lattice**（应用层网络服务，未在 AWS 官方文档核实其定位）；③ AWS 官方**推荐开源 Istio Ambient** 与 EKS Auto Mode 组合（有官方博客论证）。

### Google Cloud Service Mesh

**已从 GKE Service Mesh / Anthos Service Mesh 改名**为 Cloud Service Mesh。完全基于开源 Istio，Google 托管，版本号形如 `<istio-version>-asm.<n>`。

- **in-cluster 最新 `1.30.4-asm.1`**（2026-08-31，使用 **Envoy v1.38.4-dev**）；managed 版另有 `1.21.6-asm.71`(rapid) / `1.20.8-asm.119`(regular) / `1.19.10-asm.109`(stable) 于 2026-08-27 推送。
- 1.27 已不再支持。
- **明确不支持项**（1.30.4-asm.1）：DNS cluster 的 Failover Priority、`ENABLE_WILDCARD_HOST_SERVICE_ENTRIES_FOR_TLS`、**每 workload 多个 CUSTOM 外部授权 provider**、`DEBUG_ENDPOINT_AUTH_ALLOWED_NAMESPACES`。
- 两种实现模式：支持 **`TRAFFIC_DIRECTOR`**（Google 自己的 xDS 实现，非 Envoy/Istio 数据面），该实现的直连集群默认使用 distroless proxy 镜像。
- 未托管的后果：「Istio 组件仍可运行，但 Google 不再管理 Istio 安装，你将不再收到自动更新，也不保证安装随 K8s 版本升级而工作」。

### 阿里云 ASM

「基于原生的 Istio 提供以多语言流量管理为核心的解决方案」。**当前最高支持 Istio 1.29**（2026-06 发布，**2027-04 过期**）；1.28（2027-01）、1.27（2026-11）、1.26（2026-09）；**1.25 及以下已过期**（1.25 于 2026-05 过期）。

节奏：「原则上保持**每三个月**更新一次 Istio 大版本」；补丁版本 `v1.18.x.y` **可能在不通知的情况下自动热更新**（热更新时数据面网关与 sidecar 版本不变）。

版本增强：1.29 支持 **ztunnel 证书吊销列表（CRL）校验**、ServiceEntry 实验性支持 DYNAMIC_DNS 下 TLS 通配符 hosts、`/stats/prometheus` 默认支持 HTTP 压缩（brotli/gzip/zstd）；1.28 全面支持 Gateway API v1.4、ztunnel 支持 L7 访问日志（默认关闭）、支持 InferencePool v1。特有 CRD：`ASMMeshConfig`、`ASMReconcileNSLabels`。

## 多集群与多网格

### Istio 多集群

四种拓扑：Multi-Primary、Primary-Remote、Multi-Primary on different networks、Primary-Remote on different networks。

**网络模型**：

- **single network**：工作负载可直接互达，**多集群时服务与 endpoint IP 不得重叠**。
- **multi-network**：可重叠 IP/VIP、跨管理边界、容灾、扩展地址、满足网络分段合规。此时不同网络的工作负载**只能通过一个或多个 Istio gateway 互达**，Istio 用 **partitioned service discovery** 为消费者提供按其所在网络区分的 endpoint 视图。

**控制面模型**：primary 集群（有本地控制面）/ remote 集群（无本地控制面）。remote 集群需生成 **`remote secret`** 并部署到每个 primary 集群，其中含访问该集群 K8s API server 的凭证。多 primary 时每个 primary 从**各自集群内**的 API server 取配置，因此配置需额外工具（CI/CD）同步。

也可由**完全在网格外**的外部控制面管理全 remote 集群组成的网格——「A cloud vendor's managed control plane is a typical example of an external control plane」。

1.31 的多集群稳定性提升：ambient 模式**凭据轮换不再导致 stale snapshot 或丢失 endpoint shards**；修复多集群内存与 goroutine 泄漏；CNI node agent 修复并发 map 写 panic、fd 泄漏、Pod 删除死锁；1.31.1 修复远程集群凭据轮换泄漏整个集群缓存状态（#60033）。

### 跨网格互联的现状

> [!WARNING]
> **Istio 不提供任何跨 mesh 信任 bundle 交换工具**（官方原话）。可用 **SPIFFE Trust Domain Federation** 协议自行交换。
>
> **跨 Istio mesh ↔ Linkerd 等异构网格：未查到任何标准方案或官方支持声明。** 不要断言存在标准互联路径。

## 选型视角

| 场景 | 建议 | 理由 |
| :-- | :-- | :-- |
| 已有 K8s 微服务、Java 栈为主 | **Istio** | 生态最完整；与 Spring Cloud / Higress 集成路径最短 |
| 想要开箱即用的数据面、无控制面 | **Higress** | 见 [Higress](/docs/CS/Framework/Higress/Higress.md)，可作 Istio Gateway 形态 |
| 已在 AWS 且要托管 | **ECS Service Connect** | App Mesh 已终止支持 |
| 已在 GCP 且要托管 | **Cloud Service Mesh** | 注意落后上游约 1~2 个 minor |
| 已在 Azure 且要托管 | **AppNet**（preview）或 AKS add-on | AppNet 是新线但仍是 preview |
| 强 eBPF 偏好、集群由 Cilium 管理 | **Cilium Service Mesh** | 但 mTLS 仍 Beta，跨集群不支持 |
| 轻量 + 安全优先、不需要复杂流量治理 | **Linkerd** | CNCF Graduated，2.20 稳定版 |
| Windows / VM / Nomad 混合环境 | **Consul Connect** | 支持面最广，但需评估 IBM 许可与 V.M.F 版本策略 |
| 已被 App Mesh 拖累 | 迁 **ECS Service Connect** 或开源 Istio | App Mesh 2026-09-30 终止支持 |

## Links

- [Istio](/docs/CS/Framework/Istio/Istio.md)
- [Envoy](/docs/CS/Framework/Istio/Envoy.md)
- [Security](/docs/CS/Framework/Istio/Security.md)
- [Install](/docs/CS/Framework/Istio/Install.md)
- [Kubernetes](/docs/CS/Container/k8s/K8s.md)
- [Higress](/docs/CS/Framework/Higress/Higress.md)

## References

- <https://www.cncf.io/projects/linkerd/>
- <https://docs.cilium.io/en/stable/network/servicemesh/mutual-authentication/mutual-authentication/>
- <https://docs.aws.amazon.com/app-mesh/latest/userguide/what-is-app-mesh.html>
- <https://docs.cloud.google.com/service-mesh/v1.20/docs/migrate-service-mesh>
- <https://www.alibabacloud.com/help/zh/doc-detail/479216.html>
- <https://learn.microsoft.com/azure/aks/istio-support-policy>
- <https://docs.hashicorp.com/consul/docs/release-notes/consul/v2_0_x>
- <https://istio.io/latest/docs/ops/deployment/deployment-models/>
- <https://github.com/openservicemesh/osm>
