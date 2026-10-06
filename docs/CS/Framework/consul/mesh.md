## Introduction

**Consul service mesh**（早期叫 Connect）是 Consul 相对 etcd / ZooKeeper / Nacos 的差异化王牌：把"服务间 mTLS + 授权"做成开箱能力，业务代码零改造。开启网格后，每个服务旁部署一个 **Envoy sidecar**，由 Consul 通过 gRPC（端口 `8502`，xDS 协议）下发配置；服务间流量不再直连，而是经 sidecar 强制双向 TLS + 意图校验。

> [!NOTE]
> Consul 2.0.x 中服务网格是主力方向：Envoy 升级到 1.37.x（2.0.0 起），并引入 multi-port（命名端口）服务（Enterprise）、passive health check（outlier detection）等增强。

## Sidecar 与 xDS

- 每个服务实例旁运行 Envoy，通过 **gRPC xDS（8502）** 从 Consul 拉取监听器 / 集群 / 路由 / 端点配置；
- 业务无需改代码：只要把出站流量指到本地 sidecar（透明代理 transparent proxy 模式下连改代码都不用）；
- sidecar 自动从 Consul CA 获取并轮转证书，服务身份由 SPIFFE 风格的 `spiffe://<trust-domain>/ns/<ns>/svc/<svc>` URI 表示。

## mTLS 与 Connect CA

Consul 内置 CA，自动为服务签发、轮转证书。CA provider 可插拔：

| provider | 说明 |
| :--- | :--- |
| `consul`（内置） | 默认，Consul 自管根 CA + 中间 CA |
| `vault` | 用 HashiCorp Vault 作为 PKI 后端 |
| `aws-pca` | AWS Private CA 签发 |
| `gcp` | Google Cloud CA |
| `azure` | Azure Key Vault CA |
| `external` | SPIFFE 联合 / 外部 issuer（如 CyberArk WIM，Enterprise） |

> [!TIP]
> `primary_datacenter` 是 connect CA 的根——它持有根 CA，其他 DC 通过 CA 复制获得中间 CA。跨 DC 服务网格的 mTLS 信任链由此收敛到主 DC。

## Intentions（意图）：服务间授权

intentions 控制"哪个服务能调哪个服务"，**默认 deny**——未显式放行即拒绝：

- **L4 粒度**：服务到服务是否允许（最常用）；
- **L7 粒度**：按 HTTP 路径 / 方法 / 头进一步放行（需 sidecar 支持 L7 路由）；
- 配置方式：旧 `intentions` API 已被 **`service-intentions` 配置项**（config entry）取代（1.18+ 推荐），支持前缀匹配、L7 规则、与 `service-router` / `service-splitter` 联动。

> [!WARNING]
> 2.0.4 起，给 Envoy 附加"可执行代码的 EnvoyExtension"或 proxy escape-hatch 键，需要同时具备 `mesh:write` 与 `service:write`（CVE 修复）。配置 ACL 时别漏 `mesh:write`。

## 流量治理配置项（config entries）

服务网格的路由 / 切分 / 默认值由一组 config entry 声明：

| 配置项 | 作用 |
| :--- | :--- |
| `proxy-defaults` | 全局 sidecar 默认（协议、透明代理、上游连接池） |
| `service-defaults` | 单服务的协议（http/grpc/tcp）、transparent proxy |
| `service-resolver` | 服务发现 + 故障转移（failover 到邻近 DC） |
| `service-router` | L7 路由规则（按路径/头分流） |
| `service-splitter` | 流量百分比切分（金丝雀 / 灰度） |
| `service-intentions` | 服务间访问授权（L4/L7） |

这套能力与 Istio 的 VirtualService/DestinationRule 同源思路，但 Consul 的卖点是**同一套控制面同时管 VM 与 K8s 上的工作负载**（Istio 仅 K8s）。

## 透明代理（Transparent Proxy）

开启后，服务出站流量被 iptables 重定向到本地 sidecar，应用**完全无感**即可获得 mTLS + 意图校验——这是 Consul 在"混合云（VM + K8s + 多云）"场景相对 Istio 的关键易用性优势。

## 与 etcd / Nacos 对照

| 维度 | Consul mesh | etcd | Nacos |
| :--- | :--- | :--- | :--- |
| 服务网格 | 原生（Envoy mTLS + intentions） | 无（需自拼） | 无 |
| mTLS | connect CA 自动签发轮转 | 需显式配 TLS | 无原生 |
| L7 授权 | service-intentions | 无 | 无 |
| 工作负载 | VM + K8s 统一 | — | — |

Consul 的不可替代点正是"注册发现 + mTLS 零信任 + 跨机房"一条龙；etcd 只做 KV，网格要自己拿 Envoy 拼（见 [etcd security](/docs/CS/Framework/etcd/security.md)）。代价是引入了 sidecar 资源开销与 xDS 配置复杂度。

## Links

- [Consul（架构与启动流程）](/docs/CS/Framework/consul/Consul.md)
- [Gateway（网关与联邦）](/docs/CS/Framework/consul/gateway.md)
- [Security（安全）](/docs/CS/Framework/consul/security.md)
- [Discovery（服务发现）](/docs/CS/Framework/consul/discovery.md)
- [Troubleshooting（故障排查）](/docs/CS/Framework/consul/troubleshooting.md)
- [etcd security](/docs/CS/Framework/etcd/security.md)

## References

1. [Consul Service Mesh](https://developer.hashicorp.com/consul/docs/connect)
2. [Consul Config Entries](https://developer.hashicorp.com/consul/docs/reference/config-entries)
3. [Consul Connect CA](https://developer.hashicorp.com/consul/docs/connect/ca)
4. [Consul Service Intentions](https://developer.hashicorp.com/consul/docs/connect/intentions)
