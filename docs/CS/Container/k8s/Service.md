## Introduction

[Pod](/docs/CS/Container/k8s/Pod.md) 的 IP 是**临时身份**：滚动更新、扩缩容、被驱逐重建，任何一次变动 IP 都会变。如果调用方直接写死 Pod IP，每次发布都要改配置——所以 K8s 需要一个"地址不变、后端可换"的稳定入口，这就是 Service。

Service 是一个**抽象的访问入口**：它持有固定的 ClusterIP（虚拟 IP）和一组 **selector 规则**，由 selector 决定"哪些 Pod 属于这个 Service"。Pod 来了走、IP 变了，调用方只认 Service 地址，不用关心后端是谁。

> 类比：Service 是公寓的快递收发站，Pod 是不断更换的快递员。发件人只记住收发站地址，包裹（流量）总能送到当班的快递员手上。

## Three Elements and Endpoints

```yaml
apiVersion: v1
kind: Service
metadata:
  name: nginx-service
spec:
  selector:
    app: nginx          # ① 选出标签 app=nginx 的 Pod，这是"配送契约"
  ports:
    - protocol: TCP
      port: 80          # ② Service 自己监听的端口（nginx-service:80）
      targetPort: 80    # ③ 转发到 Pod 容器的哪个端口
  type: ClusterIP
```

apply 之后可以直接看到服务发现的结果：

```shell
$ kubectl get svc nginx-service
NAME            TYPE        CLUSTER-IP     PORT(S)   AGE
nginx-service   ClusterIP   10.96.0.100    80/TCP    30s

$ kubectl get endpoints nginx-service
NAME            ENDPOINTS                                  AGE
nginx-service   10.244.1.3:80,10.244.2.7:80,10.244.3.9:80 30s
```

**Endpoints（新版本为 EndpointSlice）就是 Service 的"配送名单"**：Endpoints 控制器持续 watch Pod 的标签与就绪状态（`Ready` condition），Pod 挂了、重建、扩容时自动更新列表。EndpointSlice 把后端按每片默认最多 100 个端点分片（控制器可配置，不是 API 协议上限），避免大 Service 一次变更全量推送；查看命令为 `kubectl get endpointslices -l kubernetes.io/service-name=<svc>`。这意味着 K8s 内置了服务注册与发现，不需要额外的 Consul/etcd 注册中心——这是 Service 与 Spring Cloud 系服务发现（[Nacos](/docs/CS/Framework/nacos/Nacos.md)、[Eureka](/docs/CS/Framework/eureka/Eureka.md)）最本质的差异：注册信息直接来源于控制器对期望状态的调和，而不是应用主动上报。

注意 `targetPort` 与 `port` 的区别是高频踩坑点：`port` 是 Service 暴露的端口，`targetPort` 是容器实际监听的端口，二者可以不同（比如 Service 80 → 容器 8080）。

## Four Types

### ClusterIP (default)

集群内网虚拟 IP，只在集群内部可达。

- 场景：微服务之间的内部调用（A 服务调 B 服务）
- 局限：外部浏览器访问不了 `10.96.0.100`，需要更大的"门"

### NodePort

在每个 Node 上开一个固定端口（默认范围 30000-32767），流量从任意 Node 的该端口转入 Service。

```yaml
spec:
  type: NodePort
  ports:
    - port: 80
      targetPort: 80
      nodePort: 30080      # 所有 Node 都开这个端口
```

访问方式：`http://<任意 Node IP>:30080`。原理是 kube-proxy 在每个 Node 上监听 nodePort 并转发到 Service。

短板：端口范围受限、一个端口只能给一个 Service、裸 IP + 高端口对用户不友好。

### LoadBalancer

云环境首选。K8s 调用云平台 API 自动创建一个云负载均衡器（CLB/SLB/ELB）并分配公网 IP：

```yaml
spec:
  type: LoadBalancer
  ports:
    - port: 80
      targetPort: 80
```

流量路径是 **LoadBalancer → Node:nodePort → Service → Pod**，本质是在 NodePort 之上又包了一层。它补齐了 NodePort 的短板：标准端口（80/443）、公网 IP、健康检查、TLS 终结。

代价是**每个 LoadBalancer Service 都会创建一台独立的云 LB 实例**，业务一多成本就翻倍——这是引入 [Ingress](/docs/CS/Container/k8s/Ingress.md) 的直接动因：用一个入口代理几十个 Service。

### ExternalName

唯一不转发流量的类型，只提供 DNS 别名（CNAME 记录）：

```yaml
spec:
  type: ExternalName
  externalName: mysql.corp.example.com
```

Pod 访问 `mysql-external.default.svc.cluster.local` 会被解析成外部域名。特点：**没有 ClusterIP、没有 Endpoints、不转发流量，只做 DNS 别名**。

典型场景：依赖解耦（数据库、第三方 API 域名不硬编码进代码）；迁移过渡期让调用方无感切换。

### Type Comparison

| 类型 | 可达范围 | 有无 ClusterIP | 典型场景 |
|------|---------|---------------|---------|
| ClusterIP | 集群内 | 有 | 微服务互调 |
| NodePort | 集群外（Node IP + 高端口） | 有 | 开发/测试环境临时暴露 |
| LoadBalancer | 公网 | 有 | 生产环境非 HTTP 业务 |
| ExternalName | — | 无 | 集群外依赖的稳定别名 |

## kube-proxy: Turning Virtual IP into Kernel Rules

ClusterIP 是一个**虚拟 IP**：没有网卡、没有实体设备，只是一条存在于内核里的转发规则。真正把它变现实的是每个 Node 上的 [kube-proxy](/docs/CS/Container/k8s/kube-proxy.md)：

- **iptables 模式**（默认）：watch Service/EndpointSlice，在 nat 表里为每个 Service 生成 `KUBE-SVC-XXX`（按 `--probability` 概率抽签分发）+ `KUBE-SEP-XXX`（DNAT 到 Pod）两级链。这是概率抽签而非精确轮询，规则随 Service × Endpoint 线性增长，大集群下整表刷入与线性匹配的开销显著。
- **IPVS 模式**：基于内核 LVS，规则存于哈希表、查找 O(1)，`ipvsadm -ln` 可看到 rr/wrr/lc/sh 等调度器；同时节点上会出现一块绑定了全部 ClusterIP（/32）的 dummy 网卡 `kube-ipvs0`——它让协议栈认为 VIP 在本机，流量随即被 ipvs 截获 DNAT。这解释了"没有任何真实设备的 ClusterIP 为什么能 ping 通"。注意 IPVS 并非纯 IPVS，节点上仍要写一批辅助 iptables 链与 ipset。
- **nftables 模式**：v1.33 起 GA，把两级自定义链换成一张 `verdict map`，一次查表完成分发；要求内核 ≥ 5.13，且必须显式 `--proxy-mode=nftables`——该 mode 的 gate 虽已 GA 锁定，但 Linux 默认模式仍是 iptables。

这三种之外，[Cilium](/docs/CS/Container/k8s/net.md) 等 eBPF 方案可以整体接管 Service 转发。它不属于 kube-proxy 的模式（`ProxyMode` 里没有 eBPF），做法是把 kube-proxy 停掉、由自己在内核 eBPF 程序里完成改写。

三种模式都依赖 conntrack 在连接粒度上固定 DNAT 目标（天然会话保持）；后端名单由 EndpointSlice 维护（单 slice 默认最多 100 个端点，该上限是控制器默认值而非 API 常量）。规则的真实形态、kube-ipvs0 与 SyncLoop 源码见 [kube-proxy](/docs/CS/Container/k8s/kube-proxy.md)，完整数据面链路见 [K8s 网络](/docs/CS/Container/k8s/net.md)。

一句话选型：**小集群 iptables 够用，大型集群选 nftables 或 IPVS，要 L7 策略与极致性能走 eBPF。**

## Selection Decision

```
集群内部通信                      → ClusterIP
需要外部访问（开发/测试临时用）      → NodePort
需要外部访问（生产、非 HTTP）        → LoadBalancer
需要外部访问（生产、HTTP/HTTPS）     → Ingress（前面挂一个 LoadBalancer）
访问集群外部服务，要稳定内部别名      → ExternalName
```

生产中最常见的组合是：**内部 ClusterIP + 对外 Ingress（挂单个 LoadBalancer）+ 外部依赖 ExternalName**，这样能把云 LB 的实例数压到最低。

## Others

- **Headless Service**（`clusterIP: None`）：不分配虚拟 IP，DNS 直接返回所有 Pod 的 A 记录，用于 StatefulSet 的有状态集群（客户端自己做拓扑感知）。相关：`PublishNotReadyAddresses` 字段控制是否在 Pod 未就绪时也发布 DNS。
- **Service 与 DNS**：CoreDNS 为每个 Service 生成 `<svc>.<ns>.svc.cluster.local` 记录，Service 名解析是集群内最主要的服务发现方式，排障入口见 [常见问题排查](/docs/CS/Container/k8s/Issues.md)。
- **trafficDistribution**：表达"优先把流量送到哪里"，取值 `PreferSameZone`（同可用区）与 `PreferSameNode`（同节点）。注意 `PreferClose` 是同名功能的**已废弃旧名**，写新配置应使用 `PreferSameZone`。它与 `internalTrafficPolicy: Local` 互斥。

## Links

- [K8s](/docs/CS/Container/k8s/K8s.md)
- [Pod](/docs/CS/Container/k8s/Pod.md)
- [kube-proxy](/docs/CS/Container/k8s/kube-proxy.md)
- [Ingress](/docs/CS/Container/k8s/Ingress.md)
- [K8s 网络](/docs/CS/Container/k8s/net.md)
- [Scaling](/docs/CS/Container/k8s/Scaling.md)

## References

1. [图解K8s · Service：流量的快递站](https://mp.weixin.qq.com/s/fSSPrgyTqKkUcSK7rVLPjA)
2. [K8s Service 底层原理：ClusterIP 与流量转发](https://mp.weixin.qq.com/s/-B8rs7vFRKciPlhNVECKFQ)
