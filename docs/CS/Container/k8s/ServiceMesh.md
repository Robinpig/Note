## Introduction

服务网格（Service Mesh）是在应用之外独立出来的一层「基础设施中间件」：它把服务间通信的横切关注点——**mTLS 强身份、流量治理（路由/重试/熔断/灰度）、统一可观测、策略**——从业务代码里抽出来，交给一组被注入的代理去处理。Kubernetes 把「容器跑起来并连通」这件事做完了，但**不负责「服务之间如何安全、可观测、可控地通信」**——这恰恰是网格要补的层。

Istio 是 K8s 上最主流的服务网格（CNCF 顶级项目）。**它的架构、流量治理、安全、可观测、Ambient 形态等全部细节在 [Framework/Istio](/docs/CS/Framework/Istio/Istio.md) 子树**；本页只讲一件事：**Istio 如何「长在 K8s 之上」，以及在 K8s 网络栈里它处在哪一层**。搞清这层关系，才不会把 K8s 原生能力与网格能力搞混。

## Why K8s Alone Is Not Enough

Kubernetes 原生给的是**四层（L3/L4）**基座，它不懂「服务身份」「HTTP 路由」「熔断重试」「跨服务 trace」：

| 维度 | K8s 原生能给的 | K8s 原生给不了的 | 谁补 |
|------|--------------|----------------|------|
| 连通 | Pod 网络（CNI）、Service 四层负载 | —— | —— |
| 服务发现 | EndpointSlice 自动维护后端名单 | 跨语言统一、可路由的外部服务 | 网格复用 K8s 发现 |
| 隔离 | NetworkPolicy（L3/L4 强制） | 按 HTTP 方法/路径/域名的 L7 限制 | 网格 L7 策略 |
| 身份 | K8s 自签证书（kubelet/SA） | 工作负载级、短生命周期的强身份 | 网格 SPIFFE ID |
| 治理 | 无 | 重试/超时/熔断/灰度/故障注入 | 网格 |
| 可观测 | kubelet 指标、节点日志 | 跨服务 golden metrics、端到端 trace | 网格 |

没有网格时，这些要么靠改业务代码（Spring Cloud 系的 Gateway/Sentinel/Nacos），要么干脆缺失。**网格的价值是把治理与语言、框架解耦**——无论 Java、Go、Python，只要流量经过代理，就能获得同一套零信任网络。

## How Istio Rides on K8s

Istio 不是另起炉灶，而是**复用 K8s 的扩展点**把自己叠加上去。五个耦合机制：

1. **Admission Webhook（sidecar 自动注入）**：Istio 通过 `MutatingWebhookConfiguration` 在 Pod 创建时注入 Envoy sidecar 容器 + init 容器（init 容器用 `iptables` 把进出 Pod 的流量重定向到 sidecar）。这正是 [acl](/docs/CS/Container/k8s/acl.md) 讲的「准入扩展点」——Istio、OPA Gatekeeper 都靠它。Ambient 模式改用 **Istio CNI 插件**做重定向，**去掉了 init 容器**，应用 Pod 不再被改写。

2. **Service / EndpointSlice 作为服务发现源**：`istiod` 直接 watch K8s 的 Service 与 EndpointSlice，合成 Envoy 能消费的统一格式下发。**不需要独立的注册中心**（对比 [Nacos](/docs/CS/Framework/nacos/Nacos.md) / Eureka 那种应用主动上报）。

3. **CRD 扩展机制**：Istio 的所有 API——`VirtualService` / `DestinationRule` / `Gateway` / `AuthorizationPolicy` / `Telemetry`——全是 CRD，挂在 K8s API Server 上，复用其鉴权、RBAC、etcd 存储与版本管理。网格的「控制面」本质上就是 K8s 的一个 operator + 一组 CRD。

4. **Gateway API 实现**：Istio 是 [Gateway API](/docs/CS/Container/k8s/Gateway_API.md) 的一种实现（`gatewayClassName: istio`），南北向入口（IngressGateway）与东西向（GAMMA 把同一套 API 用于网格内流量）统一到一套可移植 API。

5. **Namespace / Label / RBAC 原语**：网格级与命名空间级策略的作用域靠 `metadata.namespace` 与标签表达（`istio.io/dataplane-mode=ambient`  enroll 一个命名空间进 ambient），完全复用 K8s 原语，无需自建作用域模型。

> 一句话：**Istio 把 K8s 当「底座操作系统」用**——拿它的注入点装代理、拿它的 Service 做发现、拿它的 CRD 做 API、拿它的标签做作用域。

## Where Istio Sits in the K8s Network Stack

数据面自底向上分四层，Istio 是叠加在最上面的覆盖层：

```text
应用容器
   │  (Pod 内/节点上被拦截)
   ▼
① CNI            Pod 网络连通（Flannel/Calico/Cilium）—— 见 net.md / CNI.md
   ▼
② kube-proxy     ClusterIP 四层转发（iptables/IPVS/nftables）—— 见 Service.md
   ▼
③ NetworkPolicy  L3/L4 强制隔离（依赖 CNI 实现）—— 见 NetworkPolicy.md
   ▼
④ Istio 覆盖层   sidecar(Envoy) 或 ztunnel 拦截，做 mTLS + L4/L7 治理
```

两种形态对 K8s 工作负载的影响截然不同：

| 维度 | Sidecar 模式 | Ambient 模式 |
|------|------------|-------------|
| 代理形态 | 每 Pod 一个 Envoy sidecar | 节点级 **ztunnel**（Rust）+ 可选 **waypoint**（Envoy） |
| 是否改业务 Pod | 是（注入容器，需重启 Pod 入网） | 否（标签驱动，应用无感入网） |
| 层级覆盖 | 直接 L4 + L7 | ztunnel 做 L4，waypoint 补 L7 |
| 升级粒度 | 单服务（重建 Pod） | 按节点（ztunnel）/ 独立部署（waypoint） |
| 重定向机制 | init 容器 + iptables | Istio CNI 插件（无 init 容器） |

**sidecar** 把流量重定向到 Pod 内的 Envoy（15001/15006 端口），每个 Pod 都吃一份代理资源；**ambient** 把 L4 处理移到节点级 ztunnel，业务 Pod 零改动即可获得零信任加密，需要 L7 策略时再按命名空间/服务部署 waypoint。ambient 在 Istio **1.24 进入 GA**（1.27 起 native sidecar 默认开启），是当前新集群的推荐默认形态。

### 与 NetworkPolicy 的关系（最易混）

二者**正交、互补，不是替代**：

- **NetworkPolicy** 是 K8s 原生的 **L3/L4 强制隔离**——它直接作用在 CNI 数据面，「默认拒绝 + 显式放行」由内核/数据面强制执行，是集群网络安全的底线。但它**管不到 HTTP 方法/路径/域名**。
- **Istio** 是 L4/L7 **覆盖层**——基于 mTLS 身份做策略，能补 NetworkPolicy 做不到的「按 HTTP 方法/路径/域名限制」「按服务身份而非 IP 授权」。但它是应用层代理，覆盖面取决于流量是否真的经过网格。

结论：用 NetworkPolicy 兜住「Pod 到 Pod 能不能通」的硬底线，用 Istio 做「通了之后怎么治理、怎么鉴权」的精细控制。

## Division of Responsibility（作用域划分）

| 能力 | K8s 原生（归属分册） | Istio 补的层（Framework/Istio） |
|------|-------------------|-------------------------------|
| 四层负载 / 服务发现 | [Service](/docs/CS/Container/k8s/Service.md)（EndpointSlice） | 叠加 L7 路由、跨服务发现 |
| 网络连通 | [net](/docs/CS/Container/k8s/net.md) / [CNI](/docs/CS/Container/k8s/CNI.md) | 不接管底层连通 |
| L3/L4 隔离 | [NetworkPolicy](/docs/CS/Container/k8s/NetworkPolicy.md) | L4 mTLS + L7 授权（正交互补） |
| 南北向入口 | [Ingress](/docs/CS/Container/k8s/Ingress.md) / [Gateway API](/docs/CS/Container/k8s/Gateway_API.md) | Istio `Gateway` / IngressGateway 实现 |
| 证书 / 身份 | [Identity](/docs/CS/Container/k8s/Identity.md)（K8s 自签） | SPIFFE ID + istiod 内嵌 CA，短生命周期 |
| 可观测 | [Observability](/docs/CS/Container/k8s/Observability.md)（kubelet/metrics） | 网格 golden metrics + 端到端 trace |

## When You Actually Need a Mesh

网格不是必选项，它的成本（代理资源、运维复杂度、调试链路变长）要能换来对应价值：

- **不一定需要**：服务数 < 20、单一语言、无跨服务零信任身份合规需求——单靠 Ingress/Gateway API + 客户端库（重试/超时）往往够用。
- **价值显著**：跨语言微服务、需要服务间 mTLS 强身份、需要细粒度 L7 治理（金丝雀/熔断/按路径限流）、需要统一跨服务遥测。
- **南辕北辙误区**：已有 Ingress/Gateway API 只解决了**南北向**（外部→集群）；**东西向**（服务→服务）治理仍需网格。不要把「装了网关」等同于「有了 mesh」。

> 版本基线（2026-09 核实）：Istio 最新稳定 **1.31.x**，官方支持 **Kubernetes 1.32 ~ 1.36**，与 K8s 版本基线对齐。详细版本、升级规则、破坏性变更见 [Framework/Istio](/docs/CS/Framework/Istio/Istio.md)。

## Links

- [K8s 网络（CNI/kube-proxy 数据面）](/docs/CS/Container/k8s/net.md)
- [Service 与 kube-proxy（四层基座）](/docs/CS/Container/k8s/Service.md)
- [NetworkPolicy（L3/L4 隔离）](/docs/CS/Container/k8s/NetworkPolicy.md)
- [Gateway API（南北向 + GAMMA 东西向）](/docs/CS/Container/k8s/Gateway_API.md)
- [acl（准入 Webhook 注入点）](/docs/CS/Container/k8s/acl.md)
- [Istio：服务网格与网关（详细归属分册）](/docs/CS/Framework/Istio/Istio.md)

## References

1. [Istio Documentation](https://istio.io/latest/docs/)
2. [Istio Ambient Mode](https://istio.io/latest/docs/ambient/)
3. [Gateway API](https://gateway-api.sigs.k8s.io/)
4. [Istio 目录索引（按层导航）](/docs/CS/Framework/Istio/README.md)
