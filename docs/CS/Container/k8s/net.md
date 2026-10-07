## Introduction

[Kubernetes 网络模型](/docs/CS/Container/k8s/K8s.md) 设计的一个基本原则是：每个 Pod 都拥有一个独立的 IP 地址，并假定所有的 Pod 都在一个可以直接联通、扁平的网络空间中。这个模型由四条基本约束构成：

1. Pod 内所有容器共享同一个 IP，容器间通过 loopback 通信；
2. 集群内任意两个 Pod 可以直接通信（无需 NAT）；
3. Node 上的 agent（如 kubelet、系统守护进程）可以与该 Node 上的所有 Pod 直接通信；
4. Service 的 ClusterIP 只在集群内有效（ExternalIP 除外）。

这个"IP-per-Pod"模型与 [Docker](/docs/CS/Container/Docker/net.md) 默认的 bridge 模式有本质区别：Docker 中跨主机容器通信需要额外配置，而 K8s 把"跨主机 Pod 互通"作为网络方案的强制前提，交给 CNI 插件实现。

本文把这条链路自上而下串起来：**API 对象 → kubelet → CRI 运行时 → CNI 插件 → 内核 netfilter/ipvs → conntrack**，并说明 kube-proxy 三种数据面模式在 v1.36 的真实状态。单个组件的细节在 [kube-proxy](/docs/CS/Container/k8s/kube-proxy.md) 与 [Service](/docs/CS/Container/k8s/Service.md) 里，本文负责把它们接起来。

## Three-layer Responsibility Separation

K8s 网络有三层职责，容易混淆但实现路径完全不同：

| 职责 | 负责组件 | 解决的问题 | 典型实现 |
|------|---------|-----------|---------|
| Pod 网络 | CNI 插件 | Pod IP 分配、跨主机 Pod 互通 | Calico、Flannel、Cilium |
| Service 网络 | kube-proxy | ClusterIP → Pod IP 的虚拟转发 | iptables、IPVS、nftables |
| 网络策略 | CNI 插件 | Pod 级 ACL | Calico、Cilium（Flannel 不支持） |

一个容易被忽略的事实：**kube-proxy 名字里有 "proxy"，但它不转发任何流量**。它只把 Service/EndpointSlice 的变化翻译成内核规则，转发全部发生在内核的 netfilter 或 ipvs 子系统中。这也解释了为什么它能被 eBPF 方案整体替换——被替换的是"规则的生产者"，不是"流量的转发者"。

## Pod Network: From API Object to veth

### kubelet No Longer Touches CNI

这是理解 K8s 网络最重要的边界：**kubelet 不调用 CNI，容器运行时才调用**。

证据在源码结构里：`pkg/kubelet/network/` 目录在 v1.36 下只剩 `dns/` 和 `OWNERS`，没有任何 CNI 二进制调用代码。全仓库搜索 CNI 配置目录的痕迹，只有 `test/e2e_node/remote/utils.go:33` 的 `cniConfDirectory = "cni/net.d"`——那是 e2e 测试机的脚手架，不在 kubelet 运行路径上。

所以 `/etc/cni/net.d/*.conflist` 和 `/opt/cni/bin/*` 归 **containerd / CRI-O** 读取与执行，K8s 主仓库对"CNI 是什么、怎么被调用"只字不提。这带来一个直接的排障结论：**CNI 装错了，日志要去运行时侧看，不在 kubelet 日志里**。

### Network Contract on CRI

既然网络交给了运行时，kubelet 与运行时之间就必须有一个接口约定，这个约定就是 CRI 的 `PodSandboxConfig`（`staging/src/k8s.io/cri-api/pkg/apis/runtime/v1/api.proto:560-580`）：

| 字段 | 行号 | 作用 |
|------|------|------|
| `metadata` | `:560` | uid / name / namespace / attempt，沙箱身份 |
| `hostname` | `:563` | 写入容器 hostname |
| `log_directory` | `:574` | 日志目录 |
| `dns_config` | `:576` | `DNSConfig`（servers / searches / options） |
| `port_mappings` | `:578` | hostPort → containerPort 映射 |
| `linux.security_context.namespace_options` | `:465` | 命名空间模式 |

`NamespaceMode` 枚举有四个取值（`:374`）：`POD` / `CONTAINER` / `NODE` / `TARGET`。**普通 Pod 用 `POD`（新建独立网络命名空间），hostNetwork Pod 用 `NODE`（共享节点网络命名空间）**。

一个值得记的细节：`PodSandboxStatus` 里回传的网络信息（`PodSandboxNetworkStatus`，`:648-653`）**只有 `ip` 和 `additional_ips` 两个字段，没有 MAC**。注释还特意写明 "Currently ignored for pods sharing the host networking namespace"（`:647`）——hostNetwork Pod 的这条状态是空的。

### How Pod IP Is Written into Status

链路很短，但每一步都在不同文件里：

1. kubelet 调 `PodSandboxStatus()` 拿到 sandbox 的网络状态（`pkg/kubelet/kuberuntime/kuberuntime_manager.go:1670`）；
2. `determinePodSandboxIPs` 从中提取 IP 列表（`kuberuntime_sandbox.go:282-312`）；
3. 存入 `kubecontainer.PodStatus.IPs`（`kuberuntime_manager.go:2128`）；
4. `convertStatusToAPIStatus` 写进 `Pod.Status.PodIP` / `PodIPs`（`pkg/kubelet/kubelet_pods.go:2093-2097`）；
5. 经 status manager `SetPodStatus` 落盘到 apiserver（`status_manager.go:464`）。

**hostNetwork Pod 是个例外**：它的 IP 根本不来自 sandbox，而是直接继承节点 IP（`kubelet_pods.go:2024-2035`）。所以一个 hostNetwork Pod 的 `PodIP` 等于它所在节点的 `NodeIP`。

### Establishing, Rebuilding, and Recycling the sandbox

沙箱（pause 容器）是网络命名空间的载体。kubelet 侧只做三件事：决定要不要重建、发 `RunPodSandbox`、发 `StopPodSandbox`。

首次创建走 `createPodSandbox` → `RunPodSandbox`（`pkg/kubelet/kuberuntime/kuberuntime_sandbox.go:67`）。重建判定在 `PodSandboxChanged`（`pkg/kubelet/kuberuntime/util.go:30`）：如果没有就绪沙箱、或网络命名空间变了、或拿不到 IP，就返回 `attempt+1`，`attempt` 被写进 `metadata.Attempt`（`kuberuntime_sandbox.go:88`）。**沙箱 ID 不复用**——重建会生成新 ID，旧 ID 只用于 kill。

删除是两阶段的：`killPodWithSyncResult` 先调 `StopPodSandbox` 停掉网络（`kuberuntime_manager.go:1991`），而 `RemovePodSandbox` 由 GC 异步执行（`kuberuntime_gc.go:185`）。CNI 的 DEL 调用发生在运行时侧，**不在 kubelet**。

### hostNetwork: No Independent Network Namespace

`NetworkNamespaceForPod` 对 hostNetwork Pod 返回 `NODE`（`util.go:82-87`），同时 `hostname` 字段不再设置（`kuberuntime_sandbox.go:100-111`）。它仍然是一个"沙箱"，但共享节点的 netns，因此：

- 它的 `PodIP` 是节点 IP；
- 端口直接落在节点上，两个 hostNetwork Pod 抢同一端口必然失败；
- 它不需要 CNI 为它分配地址。

### DNS and /etc/hosts: The Only Network Responsibility Left for kubelet

网络建立虽然交出去了，**DNS 配置的构造权仍在 kubelet 手里**：`pkg/kubelet/network/dns/dns.go` 的 `Configurer` 负责把 Pod 的 `dnsPolicy` 翻译成 `runtimeapi.DNSConfig`（`dns.go:386`），再经 `generatePodSandboxConfig` 塞进 `podSandboxConfig.DnsConfig`（`kuberuntime_sandbox.go:98`）。四个 dnsPolicy 的分支在 `getPodDNSType`（`dns.go:304`）：

| dnsPolicy | 行为 |
|-----------|------|
| `ClusterFirst` | 非 hostNetwork → 用 clusterDNS；hostNetwork → 退回 `Default` |
| `ClusterFirstWithHostNet` | 强制用 clusterDNS |
| `Default` | 继承节点 `/etc/resolv.conf` |
| `None` | 空配置，完全由用户 `dnsConfig` 指定 |

search 域由 `generateSearchesForDNSClusterFirst` 派生（`dns.go:165-175`），默认 options 只有一个 `ndots:5`（`dns.go:44`）。`/etc/hosts` 也是 kubelet 生成的（`kubelet_pods.go:417,460`），与 CNI 无关。

## CNI Plugin

CNI（Container Network Interface）是 CNCF 的网络插件规范：运行时在创建 Pod sandbox 时，通过执行 CNI 二进制并传入 JSON 配置，由插件完成网络设备创建、IP 分配、路由写入。K8s 本身不实现任何网络功能，只定义"Pod 必须能被直接访问"这个约束。

CNI 插件的核心工作可以拆成两件事：

- **IPAM**（IP Address Management）：为 Pod 分配 IP，常见有 host-local（每节点预分配网段）、Whereabouts 等；
- **数据面**：把 Pod 的流量送到正确的地方，主要有三种流派。

### Comparison of Mainstream Solutions

| 方案 | 隧道/路由方式 | 数据面 | 特点 |
|------|--------------|--------|------|
| Flannel | VXLAN 隧道 | 内核 overlay | 简单稳定，性能有隧道开销，不支持 NetworkPolicy |
| Calico | BGP 路由三层直连 | 内核路由（可用 IPIP/VXLAN 兜底） | 无 overlay 性能好，支持 NetworkPolicy |
| Cilium | 可选隧道/BGP | eBPF | 数据面在内核 eBPF 中完成，可替代 kube-proxy，性能最优，支持 L7 策略 |

以 Flannel 的 VXLAN 模式为例：每个 Node 被分配一个子网（如 `10.244.1.0/24`），Node 间通过 VTEP 设备（`flannel.1`）封装/解封装 VXLAN 报文，Pod 的原始报文被套上 UDP 头后在主机网络中传输。这与 [Linux 网络虚拟化](/docs/CS/OS/Linux/net/network.md) 中的 veth pair + bridge 是同一套底座。

典型的单节点侧落脚点是：Pod netns 里一张 `eth0`，对应宿主机侧的一对 veth，宿主机侧 veth 接入网桥或直接挂在路由表上，IP 由 IPAM 从节点子网里切出来。这些设备在 `ip link` 里可见，也是排障时最先看的地方。

## Service Data Plane: From Virtual IP to Kernel Rules

### Status of the Three Modes

`ProxyMode` 常量只有四个取值（`pkg/proxy/apis/config/types.go:253-256`）：

| 模式 | 常量 | 状态 |
|------|------|------|
| `iptables` | `ProxyModeIPTables` | Linux 默认 |
| `ipvs` | `ProxyModeIPVS` | 可用，但有弃用倾向（KEP-5495） |
| `nftables` | `ProxyModeNFTables` | v1.33 GA，需显式开启 |
| `kernelspace` | `ProxyModeKernelspace` | Windows 专用 |

**`userspace` 模式已经在 v1.26 从代码树中移除**，只剩几处注释的考古痕迹。

这里有一个极容易搞错的组合：**`NFTablesProxyMode` feature gate 在 v1.33 就已 GA 并 `LockToDefault`（`pkg/features/kube_features.go:1709-1713`），但 v1.36 的默认模式仍然是 iptables**（`cmd/kube-proxy/app/server_linux.go:48-51` 里 `Mode == ""` 时直接赋 `ProxyModeIPTables`）。

gate GA 的含义是"这个实现被认可、可以用"，不等于"它是默认"。把 nftables 设为默认是另一个 KEP（KEP-5343，计划从 v1.37 起步）。要真正用上它必须显式写 `--proxy-mode=nftables`。

顺带一提，nftables 模式在默认值上有自己的特殊处理：它会把 `NodePortAddresses` 默认设为 `NodePortAddressesPrimary`（`server_linux.go:53-55`）。

### iptables: Where the Rules Hang

所有挂载关系集中在 `iptablesJumpChains` 这一个切片里（`pkg/proxy/iptables/proxier.go:377-390`），共 12 条：

| 目标链 | 表 | 挂载内建链 | 条件 |
|--------|----|-----------|------|
| KUBE-EXTERNAL-SERVICES | filter | INPUT, FORWARD | `--ctstate NEW` |
| KUBE-NODEPORTS | filter | INPUT | — |
| KUBE-SERVICES | filter | **FORWARD, OUTPUT** | `--ctstate NEW` |
| KUBE-FORWARD | filter | FORWARD | — |
| KUBE-PROXY-FIREWALL | filter | **INPUT, OUTPUT, FORWARD** | `--ctstate NEW` |
| KUBE-SERVICES | nat | OUTPUT, PREROUTING | — |
| KUBE-POSTROUTING | nat | POSTROUTING | — |

两处值得停一下：

**filter 表的 `KUBE-SERVICES` 不挂 INPUT**。它的职责不是转发，而是"兜底可达性"：Service 完全没有端点时在这里 `-j REJECT`（`proxier.go:910-913`）。ClusterIP 的流量要么来自 Pod（走 FORWARD），要么来自本机进程（走 OUTPUT），不存在从外部直连 INPUT 的场景，所以不需要 INPUT。

**`KUBE-PROXY-FIREWALL` 三个方向全挂**。它是 `loadBalancerSourceRanges` 的实现载体——LB VIP 既可能从外部进 INPUT、也可能跨节点走 FORWARD、还可能被本机进程访问走 OUTPUT，三个方向都得过滤。

### Two-level Distribution and Lottery-based Load Balancing

每个 Service 端口被翻译成两级自定义链：

1. `KUBE-SERVICES` 匹配 ClusterIP:Port 后跳到该 Service 的 `KUBE-SVC-XXXX` 链；
2. `KUBE-SVC-XXXX` 按概率分发到各后端的 `KUBE-SEP-XXXX` 链；
3. `KUBE-SEP-XXXX` 执行 DNAT，改写成 Pod IP:targetPort。

链名里的哈希是 `sha256` → `base32` → 截断 16 字符（`portProtoHash`，`proxier.go:546-550`），前缀常量在 `proxier.go:552-558`：`KUBE-SVC-`（Cluster 策略）、`KUBE-SVL-`（Local 策略）、`KUBE-FW-`（LoadBalancer 防火墙）、`KUBE-EXT-`（外部流量）、`KUBE-SEP-`（单个后端）。

概率值来自 `computeProbability(n) = 1/n`，保留 10 位小数（`proxier.go:403-405`）：

```shell
$ iptables-save | grep KUBE-SVC
-A KUBE-SVC-XXXXXXXX -m statistic --mode random --probability 0.3333333333 -j KUBE-SEP-AAAAAAAA
-A KUBE-SVC-XXXXXXXX -m statistic --mode random --probability 0.5000000000 -j KUBE-SEP-BBBBBBBB
-A KUBE-SVC-XXXXXXXX                                                       -j KUBE-SEP-CCCCCCCC
```

注意第二条是 `1/2` 而不是 `1/3`——**这是条件概率**：走到第二条时说明第一条没中，剩余流量是 2/3，从中再抽 1/2 才等于绝对 1/3。最后一条不设概率，兜底承接。

这套机制是**概率抽签，不是精确轮询**（`writeServiceToEndpointRules`，`proxier.go:1480-1488`）。它有两个规模问题：iptables 规则更新是全量刷入，报文匹配是线性遍历，规则数随 Service × Endpoint 增长。源码里甚至有个 `largeClusterEndpointsThreshold = 1000`（`proxier.go:86`）的阈值，超过就进入"大集群模式"省略注释文本。这正是 nftables / IPVS 要解决的问题。

`externalTrafficPolicy: Local` 且有外部流量时，还会用 `KUBE-SVL-` 链只放本节点后端；而 ClientIP 亲和则用 `-m recent` 模块实现——先写 `--rcheck --seconds <超时>` 命中已知来源，到达 SEP 链时再 `--set` 记录（`proxier.go:1448-1467`、`proxier.go:1253-1254`）。后端被摘除时对应 SEP 链被删，recent 列表随之失效。

### IPVS: Hash Table and kube-ipvs0

IPVS 基于内核 LVS，把 Service 规则放进哈希表，查找复杂度 O(1)，并支持多种调度算法（`rr` 轮询是默认值）。但它**不是纯 IPVS**——节点上仍要写一批 iptables 规则和 ipset。

`pkg/proxy/ipvs/ipset.go:31-85` 定义了 20 多个 ipset，按用途分成几类：

| ipset | 类型 | 用途 |
|-------|------|------|
| `KUBE-CLUSTER-IP` | hash:ip,port | ClusterIP + port，供 masquerade 判断 |
| `KUBE-LOOP-BACK` | hash:ip,port,ip | 解决 hairpin（回环） |
| `KUBE-EXTERNAL-IP` / `-LOCAL` | hash:ip,port | ExternalIP |
| `KUBE-LOAD-BALANCER` / `-LOCAL` / `-FW` | hash:ip,port | LoadBalancer 各策略 |
| `KUBE-LOAD-BALANCER-SOURCE-CIDR` | hash:ip,port,net | `loadBalancerSourceRanges` |
| `KUBE-NODE-PORT-{TCP,UDP}` | **bitmap:port** | NodePort |
| `KUBE-IPVS-IPS` | hash:ip | 挂在 kube-ipvs0 上的地址 |

链名常量与挂载关系仍在 `pkg/proxy/ipvs/proxier.go:58-80`、`:428-444`——`KUBE-SERVICES`、`KUBE-POSTROUTING`、`KUBE-MARK-MASQ`、`KUBE-NODE-PORT`、`KUBE-LOAD-BALANCER`、`KUBE-PROXY-FIREWALL` 一个不少。**"用 IPVS 就不用 iptables"是错的**。

ClusterIP 不在任何真实网卡上，那 Pod 发出的包为什么能路由到它？IPVS 模式下 kube-proxy 会在每个节点创建一块 dummy 网卡 **`kube-ipvs0`**（`pkg/proxy/ipvs/netlink_linux.go:83-93` 的 `EnsureDummyDevice`），把所有 ClusterIP 以 `/32` 绑上去。于是路由判定认为"这些 VIP 就在本机"，包进入协议栈后被 IPVS 截获并 DNAT 到后端。

```shell
$ ip addr show kube-ipvs0
7: kube-ipvs0: <BROADCAST,NOARP,UP,LOWER_UP> mtu 1500 qdisc noqueue
    inet 10.96.0.168/32 brd 10.96.0.168 scope host kube-ipvs0
```

源码里只 `netlink.LinkAdd(&netlink.Dummy{...})`，**没有显式设置 NOARP**——`NOARP` 是内核 dummy 设备的默认属性。这个"不显式声明"的细节值得记，因为很多资料把它写成 kube-proxy 主动设置的。Service 删除时地址会被摘掉（`UnbindAddress`，`proxier.go:1228`）。

IPVS 启动时还会写一批 sysctl（`proxier.go:281-320`），其中 `conn_reuse_mode` 的逻辑是三路分支，容易被简化误传：

| 内核版本 | 行为 |
|----------|------|
| < 4.1 | 报错，不支持 |
| ≥ 5.9（`IPVSConnReuseModeFixedKernelVersion`） | **保持原值不动**（内核已修复） |
| 介于 4.1 ~ 5.9 之间 | 设为 `0` |

其余设置：`net/ipv4/vs/conntrack=1`、`expire_nodest_conn=1`、`expire_quiescent_template=1`、`ip_forward=1`，另有 `strictARP` 时的 `arp_ignore`。**iptables 与 nftables 模式不设置 `ip_forward`**——只有 IPVS 这么做。

### nftables: verdict map Replaces Per-Service Chain Creation

nftables 模式建一张自己的表 `kube-proxy`（`pkg/proxy/nftables/proxier.go:58`），表里既有 nat 型 base chain 也有 filter 型，分别挂在 prerouting / output / postrouting（`:60-68`）。这与 iptables 只借用内核保留表（`nat` / `filter`）的做法根本不同——nftables 没有保留表，各家组件各建各的表，互不干扰。

结构上的关键差异是**用 verdict map 做分发**：

```
map serviceIPsMap { type ipv4_addr . inet_proto . inet_service : verdict }
```

定义在 `proxier.go:624-628`，用法是一条规则 `vmap @serviceIPsMap`（`:661-667`）。也就是说，**不再为每个 Service 建一条跳转链**，而是把"地址 + 协议 + 端口 → 跳转目标"塞进一张哈希表，一次查表完成分发。这直接解决了 iptables 线性遍历的规模问题。

但它仍为每个 endpoint 建链（`epInfo.chainName`），也仍然走 conntrack + DNAT——所以**"nftables 更快"的准确说法是"控制面同步更快、数据面跳转更少"，而不是"完全不走 netfilter"**。

内核门槛是硬要求：nftables 模式要求内核 **≥ 5.13**（`pkg/util/kernel/constants.go:52` 的 `NFTablesKubeProxyKernelVersion`），不满足直接启动失败。源码里留了个逃生门——环境变量 `KUBE_PROXY_NFTABLES_SKIP_KERNEL_VERSION_CHECK` 非空即跳过检查（`pkg/proxy/nftables/supported.go:64-71`），理由是"发行版应该有和内核特性匹配的 nft 二进制"，检查内核只是代理指标。

### Affinity and Topology Routing

两个容易混淆的概念在这里分道扬镳。

**流量亲和（traffic policy）** 决定"要不要只用本地后端"。`externalTrafficPolicy` 与 `internalTrafficPolicy` 都默认 `Cluster`（`pkg/apis/core/v1/defaults.go:135-144`）。改成 `Local` 的语义是：**只路由到本节点后端，本节点没有就丢弃，不回退**（`CategorizeEndpoints`，`pkg/proxy/topology.go:48`；无端点时的 filter 表 DROP 规则见 `proxier.go:915-931`）。`externalTrafficPolicy: Local` 的额外好处是保留客户端源 IP，代价是丢包风险。

**拓扑感知路由（topology aware routing）** 决定"在多个 zone 之间优先选哪个"。机制是 EndpointSlice 控制器给每个 endpoint 打 `hints`（`staging/src/k8s.io/endpointslice/topologycache/topologycache.go:90` 的 `AddHints`，写入点 `:130`），kube-proxy 读取 hints 后过滤候选后端（`topology.go:164-234` 的 `topologyModeFromHints` 与 `availableForTopology`）。

v1.36 的状态有两个变化，都容易踩：

其一，**`TopologyAwareHints` feature gate 已经不存在了**。现在控制它的入口是 Service 的注解 `service.kubernetes.io/topology-mode`（`pkg/apis/core/annotation_key_constants.go:157`）或新增的 `trafficDistribution` 字段。

其二，**`trafficDistribution` 的取值改名了**：

| 取值 | 状态 |
|------|------|
| `PreferSameZone` | 推荐（原 `PreferClose`） |
| `PreferSameNode` | 推荐，v1.35 起由 `PreferSameTrafficDistribution` gate 提供（该 gate 已 GA + `LockToDefault`，`pkg/features/kube_features.go:1832-1836`） |
| `PreferClose` | **已 Deprecated**，语义等同 `PreferSameZone`（`staging/src/k8s.io/api/core/v1/types.go:5865-5869`） |

顺带一个源码内部不一致：`TrafficDistribution` 字段的注释（`types.go:6223`）仍然写着 "If set to 'PreferClose'"，而常量定义区已经把它标成 deprecated 并推荐 `PreferSameZone`。**注释没跟上改名**。

还有一条硬约束来自官方文档：**`internalTrafficPolicy: Local` 的 Service 不会使用拓扑感知 hints**，两者互斥。

EndpointSlice 的分片上限也不是 API 常量：`MaxEndpointsPerSlice` 默认 **100**，定义在控制器的默认值函数里（`pkg/controller/endpointslice/config/v1alpha1/defaults.go:38-39`），属于可配置项而非协议上限。

## A Packet’s Complete Journey

把上面几节串起来。假设 Pod A（`10.244.1.5`）访问 `nginx-service` 的 ClusterIP `10.96.0.168:80`，后端是 Pod B（`10.244.2.7`）：

1. **发包**：Pod A 的 netns 里只有一条默认路由，包出 `eth0`，目的地址是 `10.96.0.168`——它并不知道这个地址不存在实体；
2. **出 netns**：包经 veth pair 进入宿主机的网络命名空间；
3. **命中规则**：宿主机上 kube-proxy 写的规则早已就位。iptables 模式下是 `nat/PREROUTING` → `KUBE-SERVICES` → `KUBE-SVC-XXXX`；nftables 模式下是 `nat-prerouting` 链里一次 `vmap @serviceIPsMap` 查表；IPVS 模式下是路由判定认为 VIP 在本机、包进协议栈后被 IPVS 截获；
4. **选后端**：iptables 是概率抽签，IPVS 是按调度算法，nftables 是查表；选中的后端由 `KUBE-SEP-XXXX`（或等价结构）执行 DNAT；
5. **改写目的地址**：包的目的地址变成 `10.244.2.7:80`，同时 conntrack 表里记下一条 `orig=10.244.1.5:xxxxx → 10.96.0.168:80`、`reply=10.244.2.7:80 → 10.244.1.5:xxxxx` 的映射；
6. **转发**：包经宿主机的路由表送到 Pod B 所在的节点，再进入 Pod B 的 netns；
7. **回包**：Pod B 回包的源地址是 `10.244.2.7`，到达 Pod A 所在节点时 conntrack 命中，**反向还原**成 `10.96.0.168:80` 的源地址，Pod A 认为自己一直在和 ClusterIP 通信。

第 7 步是整个设计的支点：**DNAT 只在包出去时做一次，回包的"反 DNAT"完全由 conntrack 完成**。这也意味着 kube-proxy 写的规则本身是无状态的——状态机的工作全部托付给 conntrack。

## conntrack: Turning Stateless Rules into Stateful

理解了上一个环节，就能理解为什么 conntrack 是 K8s 网络里最容易被忽视、又最容易出故障的部分。

**它带来的好处**：同一条 TCP 连接的所有报文始终命中同一个后端（DNAT 结果被缓存进 conntrack 条目），这就是所谓的"天然会话保持"。规则里的概率抽签只在连接建立时生效一次。

**它带来的麻烦**：conntrack 条目有生命周期，而后端会消失。

TCP 的失效相对温和——旧连接会走完自己的超时，期间如果后端已死，客户端表现为连接超时或重置。UDP 就麻烦了：UDP 没有连接概念，一个"连接"只是 conntrack 里的条目，如果条目指向的后端已经不 serving，后续报文会持续被送到一个死地址，表现为间歇性丢包（有时好有时坏，取决于负载均衡又抽到了哪个后端）。

所以 kube-proxy 专门写了清理逻辑，而且**只针对 UDP**：

- `CleanStaleEntries` 先按 `svc.Protocol() != v1.ProtocolUDP` 过滤（`pkg/proxy/conntrack/cleanup.go:69`），再按 `entry.Forward.Protocol != unix.IPPROTO_UDP` 二次过滤（`:118`）；
- 它把 Service IP/NodePort → 可用后端集合建成映射，然后删掉那些 reply 源不在集合里的条目；
- 三种模式都在自己的 sync 里调用它：iptables `proxier.go:1441`、ipvs `proxier.go:1267`、nftables `proxier.go:1763`。

源码注释专门解释了为什么不考虑 traffic policy 和 topology：**规则变化不应该影响已有连接，这是为了保持 UDP 与 TCP 行为一致**。

conntrack 自身的容量与超时也由 kube-proxy 调优（`pkg/proxy/conntrack/sysctls.go:60-107`），默认值定义在 `pkg/proxy/apis/config/v1alpha1/defaults.go`：`nf_conntrack_max` 按每核 32k 起算、下限 128k；`tcp_timeout_established` 设为 1 天；`tcp_timeout_close_wait` 1 小时。这些值在节点承载大量短连接时是常见调优对象。

排障时的手动工具：`conntrack -L` 看条目、`conntrack -D -p udp --dport <port>` 手动清理。

## NetworkPolicy: Defined in K8s, Enforced in CNI

`NetworkPolicy` 是本仓库里"存在感最弱"的 API 之一：`pkg/apis/networking/types.go:28` 定义了类型，`pkg/registry/networking/networkpolicy/` 只有 REST 存储与校验——**没有任何执行实现**。策略的落地完全在 CNI 插件侧（Calico、Cilium 等），所以 Flannel 用户会发现自己写的 NetworkPolicy 完全没生效。

默认语义是排障时最容易搞错的部分：

- **未被任何 NetworkPolicy 选中的 Pod，默认全通**（`networking/types.go:62-68` 的注释明确写了这一点）；
- **一旦被选中，该方向立刻变成默认拒绝**，必须逐条显式放行；
- `policyTypes` 留空时会自动推导：至少有 `Ingress`，如果写了 `egress` 规则则追加 `Egress`（`pkg/apis/networking/v1/defaults.go:39-45`）。

所以"配了策略反而全断了"是预期行为，不是 bug——加一条策略就把该方向的白名单模式打开了。

## eBPF: Another Path Around netfilter

Cilium 这类 eBPF 方案走的是完全不同的路径：它不生成 iptables/ipvs 规则，而是把 Service 的 DNAT 逻辑编译成 eBPF 程序，挂在网卡的 tc/XDP 钩子上，在包进入 netfilter **之前**就完成改写，连 conntrack 也不用内核的（自己维护一个 map）。

这带来三个实际差别：

- **性能**：跳过整条 netfilter 链，且 Map 查找是 O(1)；
- **可观测性**：能看到 L7 语义（HTTP 方法、gRPC 状态码），iptables 只能看到 L3/L4；
- **替换了整个 kube-proxy**：`kube-proxy` 可以被停掉，Service 语义由 Cilium 自己实现。

关键澄清：**替代 kube-proxy 只需要替代"规则生产者"，数据面本来就在内核里**。所以 `kubectl get svc` 在停掉 kube-proxy 后依然正常——它读的是 apiserver 里的对象，与数据面无关。真正需要替代方对齐的是语义细节：`externalTrafficPolicy: Local` 的丢包行为、HealthCheckNodePort、`loadBalancerSourceRanges` 这些。

K8s 主仓库里没有任何 eBPF 数据面实现，`ProxyMode` 也只有那四个取值。

## Relationship with Docker Networking

Docker 自带一套网络实现（CNM 模型 + docker0 网桥），但 K8s 不使用它：kubelet 启动 Pod 时会以 `POD` 命名空间模式创建 sandbox，由运行时调用 CNI 插件接管网络。原因有两点：

1. Docker 的网络方案以单机为边界，跨主机能力弱；
2. CNI 规范让网络实现与容器运行时解耦，containerd/CRI-O 生态下 Docker 网络更是无从挂靠。

单机层面的机制是共享的：veth pair、Linux bridge、iptables NAT 这些 [Linux 网络](/docs/CS/OS/Linux/net/network.md) 基础设施，在 Docker 和 CNI 插件里扮演同样的角色，区别只在于组网拓扑。

## Counterintuitive List

1. **kubelet 不调用 CNI**。`pkg/kubelet/network/` 只剩 `dns/`，CNI 由 containerd/CRI-O 调用，容器网络故障的日志不在 kubelet 里。
2. **`NFTablesProxyMode` gate 已 GA 且锁定，但默认模式仍是 iptables**（`server_linux.go:48-51`）。gate GA 只说"能用"，不说"默认"。
3. **`userspace` 模式已删除**（v1.26 移除），不是"废弃但仍可用"。
4. **IPVS 模式下节点上仍有一堆 iptables 链**（`KUBE-SERVICES` / `KUBE-POSTROUTING` / `KUBE-MARK-MASQ` / `KUBE-PROXY-FIREWALL` …），"IPVS 不用 iptables"是错的。
5. **iptables 的负载均衡是概率抽签，不是轮询**。3 个后端时三条规则的 probability 是 `1/3`、`1/2`、无——后两条是条件概率。
6. **`kube-ipvs0` 的 NOARP 不是 kube-proxy 设的**，是内核 dummy 设备的默认属性；源码里没有 `SetNOARP`。
7. **filter 表的 `KUBE-SERVICES` 不挂 INPUT**，它只负责"无端点就 REJECT"这一件事。
8. **`KUBE-MARK-DROP` 链已经不再创建**，`proxier.go` 里直接写 `-j DROP` / `-j REJECT`。只有 `proxier_test.go:804/901` 还残留旧期望。同时 kubelet 配置里的 `IPTablesDropBit` 与 `IPTablesMasqueradeBit` 都已标注 "Deprecated: no longer has any effect"。
9. **kube-proxy 侧的 `masqueradeBit` 仍在使用**（默认 14，即 `1<<14` → mark `0x00004000`），别把 kubelet 侧废弃的那两个字段和它混为一谈。
10. **`--random-fully` 需要 iptables ≥ 1.6.2**（`pkg/util/iptables/iptables.go:174`），低版本会静默退化为非完全随机。
11. **conntrack 清理只针对 UDP**，TCP 不做（`cleanup.go:69`、`:118` 双重过滤）。
12. **`externalTrafficPolicy: Local` 在本节点无后端时直接丢包，不回退到其它节点**。它的卖点是保源 IP，不是"就近"。
13. **`TopologyAwareHints` gate 已被删除**，现在靠注解 `service.kubernetes.io/topology-mode` 或 `trafficDistribution` 控制。
14. **`trafficDistribution: PreferClose` 已 Deprecated**，应写 `PreferSameZone`；而字段注释里还留着旧名字（`types.go:6223`）。
15. **`internalTrafficPolicy: Local` 与拓扑感知 hints 互斥**，不能同时用在一个 Service 上。
16. **EndpointSlice 的 100 上限是控制器默认值，不是 API 协议常量**（`pkg/controller/endpointslice/config/v1alpha1/defaults.go:38-39`）。
17. **`ip_forward` 只有 IPVS 模式会设置**，iptables / nftables 模式不碰它，依赖节点自身配置。
18. **nftables 模式要求内核 ≥ 5.13**，不满足直接启动失败；`KUBE_PROXY_NFTABLES_SKIP_KERNEL_VERSION_CHECK` 可绕过。
19. **NetworkPolicy 在本仓库没有执行实现**，只有 API 与校验；没有支持策略的 CNI，"配了没反应"是预期而非故障。
20. **`PodSandboxNetworkStatus` 里没有 MAC 字段**（`api.proto:648-653`），只有 IP。

## Links

- [K8s 架构与四条主链路](/docs/CS/Container/k8s/Architecture.md)
- [kube-proxy](/docs/CS/Container/k8s/kube-proxy.md)
- [Service](/docs/CS/Container/k8s/Service.md)
- [Ingress](/docs/CS/Container/k8s/Ingress.md)
- [Docker 网络](/docs/CS/Container/Docker/net.md)
- [常见问题排查](/docs/CS/Container/k8s/Issues.md)

## References

1. [Kubernetes v1.36.4 source](https://github.com/kubernetes/kubernetes/tree/v1.36.4)
2. [Services, Load Balancing, and Networking](https://kubernetes.io/docs/concepts/services-networking/)
3. [KEP-3866: Add an nftables-based kube-proxy backend](https://github.com/kubernetes/enhancements/tree/master/keps/sig-network/3866-nftables-proxy)
4. [KEP-5343: Make nftables the default kube-proxy backend](https://github.com/kubernetes/enhancements/tree/master/keps/sig-network/5343-nftables-to-default)
5. [KEP-2433: Topology Aware Hints](https://github.com/kubernetes/enhancements/tree/master/keps/sig-network/2433-topology-aware-hints)
6. [KEP-4444: Service Traffic Distribution](https://github.com/kubernetes/enhancements/tree/master/keps/sig-network/4444-service-traffic-distribution)
