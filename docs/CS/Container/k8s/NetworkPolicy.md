## Introduction

[NetworkPolicy](https://kubernetes.io/docs/concepts/services-networking/network-policy/) 是 Kubernetes 原生的 **L3/L4 网络策略**对象，用来声明"哪些 Pod 之间、以及 Pod 与哪些网段之间可以收发流量"。它是 namespace 作用域（namespaced）的资源，基于**标签选择器**而非 IP 来圈定目标——这正是它和防火墙规则最大的区别：Pod 会漂移、IP 会变，但标签稳定。

一句话定性：**NetworkPolicy 只"加白"，不"加黑"**。它是一条条累加的允许规则，不存在"拒绝某条"的显式语句；要实现"默认拒绝"，必须显式写一条匹配全部、但没有任何 `from`/`ports` 的策略。

> [!WARNING]
> NetworkPolicy 是**声明**，不是实现。它的生效完全依赖底层 CNI 插件是否支持：
> - 支持：Calico、Cilium、Weave Net、Antrea、kube-router
> - 不支持 / 仅部分支持：kindnet、某些云厂商默认的 `azure-vnet`/`aws-vpc-cni`（早期版本）会在未配策略时放行全部
>
> 若集群 CNI 不支持，写了 NetworkPolicy 也不会报错，只是**完全不生效**——这是最常见的"策略配了却不拦"陷阱。

## Default Allow vs Default Deny

Kubernetes 的网络模型默认是 **allow-all**：只要没有 NetworkPolicy 选中某个 Pod，它进出都不受限（具体能否互通还取决于 CNI 的默认行为，但标准语义是放开）。

NetworkPolicy 一旦"选中"某个 Pod（`podSelector` 匹配到），该 Pod 的对应方向就进入**默认拒绝**状态：只有策略里显式 `allow` 的流量能通过。注意方向是独立的——一条只写了 `ingress` 的策略，不会限制该 Pod 的 `egress`。

实现"默认拒绝某命名空间全部入向"的标准写法：

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: default-deny-ingress
  namespace: prod
spec:
  podSelector: {}        # 空选择器 = 选中该 ns 下所有 Pod
  policyTypes:
    - Ingress           # 只声明 ingress → 仅入向变默认拒绝
```

要点：`podSelector: {}` 是"全部"，不是"无"。若 `policyTypes` 显式列出 `Ingress` 却没有任何 `ingress` 规则，含义就是"拒绝全部入向"。`egress` 同理。

## Anatomy of a Policy

一个 NetworkPolicy 由四部分组成：

| 字段 | 作用 |
| :--- | :--- |
| `podSelector` | 本策略**作用到**哪些 Pod（被保护方），空 `{}` 表示 ns 内全部 |
| `policyTypes` | 包含 `Ingress`、/或 `Egress`，决定策略管哪个方向 |
| `ingress` | 入向允许列表：`from`（对等体）+ `ports` |
| `egress` | 出向允许列表：`to`（对等体）+ `ports` |

对等体（`from` / `to` 的元素）有三种，可混用、取并集：

- `podSelector`：同一 ns 内按标签选 Pod
- `namespaceSelector`：按**命名空间标签**选整个 ns 的 Pod
- `ipBlock`：按 CIDR 选，可配 `except` 开洞（如放通集群网段、排除外部）

端口用 `ports: [{protocol, port}]`，`protocol` 默认 `TCP`，仅支持 `TCP`/`UDP`/`SCTP`（**没有** `ICMP`、没有 L7 方法/路径/域名）。

## Worked Examples

**放行：frontend 允许访问同 ns 的 backend:6379**

```yaml
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: backend-allow-frontend
  namespace: prod
spec:
  podSelector:
    matchLabels: { app: backend }
  policyTypes: [Ingress]
  ingress:
    - from:
        - podSelector:
            matchLabels: { app: frontend }
      ports:
        - protocol: TCP
          port: 6379
```

**放行：跨命名空间访问（用 namespace 标签）**

`namespaceSelector` 默认匹配的是**命名空间对象自身的标签**。从 v1.21 起推荐用 `kubernetes.io/metadata.name` 这个由 API server 自动维护的命名空间名标签：

```yaml
ingress:
  - from:
      - namespaceSelector:
          matchLabels:
            kubernetes.io/metadata.name: trusted-ns
        podSelector:
          matchLabels: { app: metrics-agent }   # 两个选择器是 AND
```

**放行出向到 DNS（否则默认拒绝 egress 后 Pod 无法解析域名）**

```yaml
egress:
  - to:
      - namespaceSelector: {}          # 所有 ns 的 kube-system 内 DNS
        podSelector:
          matchLabels: { k8s-app: kube-dns }
    ports:
      - protocol: UDP
        port: 53
      - protocol: TCP
        port: 53
```

## How It Interacts With Service / Ingress

| 概念 | 层次 | 职责 | 是否受 NetworkPolicy 约束 |
| :--- | :--- | :--- | :--- |
| Service | L4 虚拟 IP | 稳定的访问入口 + 负载均衡到 Endpoint | 否（策略作用在后端的 Pod 上，不作用在 ClusterIP 上） |
| Ingress | L7 路由 | 把外部 HTTP 流量按路径/host 引入集群 | 否（作用在 Ingress Controller 的 Pod 上） |
| NetworkPolicy | L3/L4 | 限制 Pod 间流量 | 是（直接作用在 Pod 上） |

关键点：**NetworkPolicy 管的是"Pod 到 Pod"的流量，不是 Service 的 ClusterIP，也不是 Ingress 的南北向规则**。想限制"谁能访问 Ingress Controller"，要在 Ingress Controller 所在 Pod 上挂策略；想做基于域名/路径/HTTP 方法的细粒度控制，NetworkPolicy 做不到，需要 Cilium 的 L7 NetworkPolicy 或服务网格（如 [Istio](/docs/CS/Framework/Istio/Istio.md)）。

## Common Pitfalls

- **`policyTypes` 与规则不一致**：若只写了 `ingress` 规则却没在 `policyTypes` 列出 `Egress`，egress 不受影响（仍是 allow-all）；反之若 `policyTypes` 列了 `Egress` 却没有 `egress` 规则，则 egress 默认全拒。始终显式写 `policyTypes`。
- **`hostNetwork: true` 的 Pod 不受 NetworkPolicy 约束**：它直接用宿主机网络栈，策略对它是透明的。
- **Node / 宿主机 IP 不在策略范围内**：NetworkPolicy 不限制 Pod 访问节点本地进程或 `169.254.169.254` 这类元数据地址，需要 `ipBlock` 显式处理。
- **`namespaceSelector` 忘记 AND 语义**：`namespaceSelector` + `podSelector` 在同一 `from` 条目里是 AND（跨 ns 的某标签 Pod），不是 OR。要"或"，拆成两个 `from` 条目。
- **CNI 不支持导致静默失效**：写完先用 `kubectl describe networkpolicy` 确认，再用 `netshoot` 之类容器实测连通性，不要只信 YAML 通过校验。
- **L7 限制缺位**：需要按 HTTP 方法/路径/域名限制时，NetworkPolicy 无能为力，转向 Cilium 或服务网格。

## Links

- [Pod 网络建立与数据面](/docs/CS/Container/k8s/net.md)
- [Service 服务发现](/docs/CS/Container/k8s/Service.md)
- [Ingress 七层入口](/docs/CS/Container/k8s/Ingress.md)
- [Pod 最小调度单元](/docs/CS/Container/k8s/Pod.md)
- [K8s 集群主笔记](/docs/CS/Container/k8s/K8s.md)

## References

1. [Kubernetes NetworkPolicy](https://kubernetes.io/docs/concepts/services-networking/network-policy/)
2. [NetworkPolicy API (networking.k8s.io/v1)](https://kubernetes.io/docs/reference/kubernetes-api/policy-resources/network-policy-v1/)
3. [Cilium L3/L4 and L7 NetworkPolicy](https://docs.cilium.io/en/stable/security/policy/)
