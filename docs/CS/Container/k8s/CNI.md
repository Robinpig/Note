## Introduction

CNI (Container Network Interface) 是 CNCF 旗下的**容器网络插件标准接口**，定义了一组"给容器配置网络"的约定（ADD / DEL / CHECK / VERSION）。Kubernetes 本身**不实现网络**——它只定义网络模型，再通过一个独立的 **CNI 插件** 把 Pod 真正接上网。调用方是 kubelet（经由容器运行时间接触发）或运行时自身。

Kubernetes 网络模型的四定律（由 CNI 插件保证）：

1. 每个 Pod 拥有独立的集群内 IP；
2. 任意节点上的 Pod 之间，不经 NAT 直接互通（Pod IP ↔ Pod IP）；
3. Node 与 Pod 之间不经 NAT 互通；
4. Pod 看到自己的 IP 与别人看到它的 IP 一致。

CNI 插件负责：IPAM（IP 分配）、创建 veth/桥、路由/overlay 封装、网络策略下发。

> [!TIP]
> **CNI ≠ kube-proxy**。CNI 管"Pod 层 L2/L3 连通"（Pod 怎么拿到 IP、怎么互通）；kube-proxy 管"Service 的 ClusterIP 怎么 DNAT 到后端 Pod"，通常跑 iptables/IPVS/nftables。Cilium 这类 eBPF 数据面能**同时吞掉这两件事**（见下文）。

## The Big Three (and Others)

| 插件 | 数据面 | 网络策略 | 路由 / Overlay | 适用 |
| :--- | :--- | :--- | :--- | :--- |
| **Flannel** | VXLAN / host-gw | ❌（需 Canal 叠加） | overlay（VXLAN）或直连（host-gw） | 小集群、学习、简单优先 |
| **Calico** | iptables / eBPF / VPP | ✅ 强（GlobalNetworkPolicy） | BGP（无 overlay）或 VXLAN | 企业、混合云、需要 BGP |
| **Cilium** | eBPF（原生） | ✅ 强（L3-L7 身份策略） | eBPF 路由 / VXLAN，可替 kube-proxy | 大规模、可观测、性能 |
| Antrea | OVS (OVN) | ✅ | Geneve / VLAN | vSphere / VMware 栈 |
| Weave Net | 自组 mesh overlay | ✅ | 全互联 overlay | 早期流行，现少新部署 |
| kube-router | BGP + iptables | ✅ | BGP | 轻量、纯 BGP |

### Flannel

最轻量：用 VXLAN 把 Pod 网包封进宿主机 UDP 隧道，或用 `host-gw` 在二层可达时直接走路由（性能更好但要求节点同二层）。**本身不实现 NetworkPolicy**——要策略得叠加 Calico 的 policy 引擎（Canal 发行版）。逻辑简单、依赖少，适合开发/中小集群，但规模大时 overlay 封装开销与缺乏策略是短板。

### Calico

Tigera 维护、最成熟的策略型 CNI。两套典型部署：

- **BGP 模式**：节点间用 BGP 把 Pod 路由广播给物理网络，Pod IP 就是可路由的真实 IP，**无 overlay**，性能接近原生；需要底层网络支持 BGP（或与 ToR 交换机 peer）。
- **VXLAN / eBPF 模式**：不支持 BGP 时用 overlay；eBPF 数据面还能替掉 kube-proxy。

网络策略用 `NetworkPolicy` + Calico 自有的 `GlobalNetworkPolicy`（集群级、可排序），粒度细。Windows 节点支持好。

### Cilium

基于 **eBPF**，把网络、策略、负载均衡都放进内核钩子，不用长 iptables 链。特性：

- 可完全**替代 kube-proxy**（`kubeProxyReplacement`），Service 负载均衡走 eBPF map，规模大时尾延时更稳；
- 网络策略支持 **L3-L7**（HTTP/gRPC/Kafka/DNS 方法/路径/域名），且基于**身份**而非 IP——Pod 重建换 IP 不影响策略；
- 内置 **Hubble** 做流级可观测性（Pod/ns/策略 verdict 维度），无需 sidecar；
- 由 Isovalent（现 Cisco）创建，CNCF 已毕业。

代价：需要较新内核（实践 ≥5.10），排障从 `iptables -L` 转到 `bpftool`/Hubble，团队需具备 eBPF 技能。

## Selection Guide

| 诉求 | 选 |
| :--- | :--- |
| 简单、少依赖、学习 | Flannel（+ 需要策略时 Canal） |
| 企业稳定、要 BGP、混合云、Windows | Calico |
| 大规模 Service、尾延时、L7 策略、可观测 | Cilium |
| vSphere / VMware 环境 | Antrea |

> [!WARNING]
> 一个集群**只能有一个 CNI**（不能同时装 Calico 和 Cilium）。换 CNI 等于逐节点滚动重启、重分配 Pod IP，是高风险操作，常在平台大版本刷新时做。选错再迁移成本很高，规划期就要定。

## Relationship With NetworkPolicy

`NetworkPolicy` 是 K8s 的 API 对象（声明"允许谁访问谁"），见 [NetworkPolicy](/docs/CS/Container/k8s/NetworkPolicy.md)；**CNI 是它的实现者**。只有支持策略的 CNI（Calico/Cilium/Antrea/Weave）才会真正执行——Flannel 写了 NetworkPolicy 也不生效。这也是 NetworkPolicy 最常见的"配了不拦"根因。

## Links

- [NetworkPolicy](/docs/CS/Container/k8s/NetworkPolicy.md)
- [Pod 网络与数据面](/docs/CS/Container/k8s/net.md)
- [Service 服务发现](/docs/CS/Container/k8s/Service.md)
- [容器运行时 containerd](/docs/CS/Container/k8s/containerd.md)
- [K8s 主笔记](/docs/CS/Container/k8s/K8s.md)

## References

1. [CNI Specification](https://github.com/containernetworking/cni)
2. [Cilium Documentation](https://docs.cilium.io/)
3. [Calico Documentation](https://docs.tigera.io/calico/latest/about)
4. [Flannel](https://github.com/flannel-io/flannel)
