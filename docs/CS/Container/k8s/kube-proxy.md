## Introduction

kube-proxy 用于节点上的网络代理 运行在 k8s 的每个节点上。它监听 kube-apiserver 的 Service 与 EndpointSlice 资源变化，并通过 iptables、ipvs、nftables 等模式在节点上生成负载均衡规则，为一组 Pod 提供统一的TCP/UDP流量转发和负载均衡功能。

kube-proxy是管理Pod-to-Service和Extend-to-Service 网络的非常重要的组件之一。kube-proxy相当于代理模型，负责将某个IP:Port的请求转发给专用网络上的相应服务或应用。但是kube-proxy与其它负载均衡服务的区别在于，kube-proxy 只向 Kubernetes Service 及其后端 Pod 资源对象发出请求。

入口函数在 cmd/kube-proxy/proxy.go

```c
func main() {
    command := app.NewProxyCommand()
    code := cli.Run(command)
    os.Exit(code)
}
```

执行 opts.Run()

```c
// NewProxyCommand creates a *cobra.Command object with default parameters
func NewProxyCommand() *cobra.Command {
    opts := NewOptions()

    cmd := &cobra.Command{
        Use: "kube-proxy",
        Long: `The Kubernetes network proxy runs on each node. This
reflects services as defined in the Kubernetes API on each node and can do simple
TCP, UDP, and SCTP stream forwarding or round robin TCP, UDP, and SCTP forwarding across a set of backends.
Service cluster IPs and ports are currently found through Docker-links-compatible
environment variables specifying ports opened by the service proxy. There is an optional
addon that provides cluster DNS for these cluster IPs. The user must create a service
with the apiserver API to configure the proxy.`,
        RunE: func(cmd *cobra.Command, args []string) error {
            verflag.PrintAndExitIfRequested()

            if err := initForOS(opts.config.Windows.RunAsService); err != nil {
                return fmt.Errorf("failed os init: %w", err)
            }

            if err := opts.Complete(cmd.Flags()); err != nil {
                return fmt.Errorf("failed complete: %w", err)
            }

            logs.InitLogs()
            if err := logsapi.ValidateAndApplyAsField(&opts.config.Logging, utilfeature.DefaultFeatureGate, field.NewPath("logging")); err != nil {
                return fmt.Errorf("initialize logging: %w", err)
            }

            cliflag.PrintFlags(cmd.Flags())

            if err := opts.Validate(); err != nil {
                return fmt.Errorf("failed validate: %w", err)
            }
            // add feature enablement metrics
            utilfeature.DefaultMutableFeatureGate.AddMetrics()
            if err := opts.Run(context.Background()); err != nil {
                opts.logger.Error(err, "Error running ProxyServer")
                return err
            }

            return nil
        },
        Args: func(cmd *cobra.Command, args []string) error {
            for _, arg := range args {
                if len(arg) > 0 {
                    return fmt.Errorf("%q does not take any arguments, got %q", cmd.CommandPath(), args)
                }
            }
            return nil
        },
    }

    fs := cmd.Flags()
    opts.AddFlags(fs)
    fs.AddGoFlagSet(goflag.CommandLine) // for --boot-id-file and --machine-id-file

    _ = cmd.MarkFlagFilename("config", "yaml", "yml", "json")

    return cmd
}
```

opts.Run() 是启动 kube-proxy 的入口，跟随 NewOptions() 构造函数，我们看到它返回的是 Options 结构体。
Options 实现了 Run 接口

```c
// Run runs the specified ProxyServer.
func (o *Options) Run(ctx context.Context) error {
    defer close(o.errCh)
    if len(o.WriteConfigTo) > 0 {
        return o.writeConfigFile()
    }

    err := platformCleanup(ctx, o.config.Mode, o.CleanupAndExit)
    if o.CleanupAndExit {
        return err
    }
    // We ignore err otherwise; the cleanup is best-effort, and the backends will have
    // logged messages if they failed in interesting ways.

    proxyServer, err := newProxyServer(ctx, o.config, o.master, o.InitAndExit)
    if err != nil {
        return err
    }
    if o.InitAndExit {
        return nil
    }

    o.proxyServer = proxyServer
    return o.runLoop(ctx)
}
```


```c
func (o *Options) runLoop(ctx context.Context) error {
    if o.watcher != nil {
        o.watcher.Run()
    }

    // run the proxy in goroutine
    go func() {
        err := o.proxyServer.Run(ctx)
        o.errCh <- err
    }()

    for {
        err := <-o.errCh
        if err != nil {
            return err
        }
    }
}
```

通过 client-go 从 apiserver 获取 services 和 endpoints/endpointSlice 配置

创建相应的 informer 并注册事件函数

```c
func (s *ProxyServer) Run(ctx context.Context) error {
    logger := klog.FromContext(ctx)
    // To help debugging, immediately log version
    logger.Info("Version info", "version", version.Get())

    logger.Info("Golang settings", "GOGC", os.Getenv("GOGC"), "GOMAXPROCS", os.Getenv("GOMAXPROCS"), "GOTRACEBACK", os.Getenv("GOTRACEBACK"))

    proxymetrics.RegisterMetrics(s.Config.Mode)

    // TODO(vmarmol): Use container config for this.
    var oomAdjuster *oom.OOMAdjuster
    if s.Config.Linux.OOMScoreAdj != nil {
        oomAdjuster = oom.NewOOMAdjuster()
        if err := oomAdjuster.ApplyOOMScoreAdj(0, int(*s.Config.Linux.OOMScoreAdj)); err != nil {
            logger.V(2).Info("Failed to apply OOMScore", "err", err)
        }
    }

    if s.Broadcaster != nil {
        stopCh := make(chan struct{})
        s.Broadcaster.StartRecordingToSink(stopCh)
    }

    // TODO(thockin): make it possible for healthz and metrics to be on the same port.

    var healthzErrCh, metricsErrCh chan error
    if s.Config.BindAddressHardFail {
        healthzErrCh = make(chan error)
        metricsErrCh = make(chan error)
    }

    // Start up a healthz server if requested
    serveHealthz(ctx, s.HealthzServer, healthzErrCh)

    // Start up a metrics server if requested
    serveMetrics(s.Config.MetricsBindAddress, s.Config.Mode, s.Config.EnableProfiling, metricsErrCh)

    noProxyName, err := labels.NewRequirement(apis.LabelServiceProxyName, selection.DoesNotExist, nil)
    if err != nil {
        return err
    }

    noHeadlessEndpoints, err := labels.NewRequirement(v1.IsHeadlessService, selection.DoesNotExist, nil)
    if err != nil {
        return err
    }

    labelSelector := labels.NewSelector()
    labelSelector = labelSelector.Add(*noProxyName, *noHeadlessEndpoints)

    // Make informers that filter out objects that want a non-default service proxy.
    informerFactory := informers.NewSharedInformerFactoryWithOptions(s.Client, s.Config.ConfigSyncPeriod.Duration,
        informers.WithTweakListOptions(func(options *metav1.ListOptions) {
            options.LabelSelector = labelSelector.String()
        }))

    // Create configs (i.e. Watches for Services, EndpointSlices and ServiceCIDRs)
    // Note: RegisterHandler() calls need to happen before creation of Sources because sources
    // only notify on changes, and the initial update (on process start) may be lost if no handlers
    // are registered yet.
    serviceConfig := config.NewServiceConfig(ctx, informerFactory.Core().V1().Services(), s.Config.ConfigSyncPeriod.Duration)
    serviceConfig.RegisterEventHandler(s.Proxier)
    go serviceConfig.Run(ctx.Done())

    endpointSliceConfig := config.NewEndpointSliceConfig(ctx, informerFactory.Discovery().V1().EndpointSlices(), s.Config.ConfigSyncPeriod.Duration)
    endpointSliceConfig.RegisterEventHandler(s.Proxier)
    go endpointSliceConfig.Run(ctx.Done())

    if utilfeature.DefaultFeatureGate.Enabled(features.MultiCIDRServiceAllocator) {
        serviceCIDRConfig := config.NewServiceCIDRConfig(ctx, informerFactory.Networking().V1beta1().ServiceCIDRs(), s.Config.ConfigSyncPeriod.Duration)
        serviceCIDRConfig.RegisterEventHandler(s.Proxier)
        go serviceCIDRConfig.Run(wait.NeverStop)
    }
    // This has to start after the calls to NewServiceConfig because that
    // function must configure its shared informer event handlers first.
    informerFactory.Start(wait.NeverStop)

    // Make an informer that selects for our nodename.
    currentNodeInformerFactory := informers.NewSharedInformerFactoryWithOptions(s.Client, s.Config.ConfigSyncPeriod.Duration,
        informers.WithTweakListOptions(func(options *metav1.ListOptions) {
            options.FieldSelector = fields.OneTermEqualSelector("metadata.name", s.NodeRef.Name).String()
        }))
    nodeConfig := config.NewNodeConfig(ctx, currentNodeInformerFactory.Core().V1().Nodes(), s.Config.ConfigSyncPeriod.Duration)
    // https://issues.k8s.io/111321
    if s.Config.DetectLocalMode == kubeproxyconfig.LocalModeNodeCIDR {
        nodeConfig.RegisterEventHandler(proxy.NewNodePodCIDRHandler(ctx, s.podCIDRs))
    }
    if utilfeature.DefaultFeatureGate.Enabled(features.KubeProxyDrainingTerminatingNodes) {
        nodeConfig.RegisterEventHandler(&proxy.NodeEligibleHandler{
            HealthServer: s.HealthzServer,
        })
    }
    nodeConfig.RegisterEventHandler(s.Proxier)

    go nodeConfig.Run(wait.NeverStop)

    // This has to start after the calls to NewNodeConfig because that must
    // configure the shared informer event handler first.
    currentNodeInformerFactory.Start(wait.NeverStop)

    // Birth Cry after the birth is successful
    s.birthCry()

    go s.Proxier.SyncLoop()

    select {
    case err = <-healthzErrCh:
        s.Recorder.Eventf(s.NodeRef, nil, api.EventTypeWarning, "FailedToStartProxierHealthcheck", "StartKubeProxy", err.Error())
    case err = <-metricsErrCh:
        s.Recorder.Eventf(s.NodeRef, nil, api.EventTypeWarning, "FailedToStartMetricServer", "StartKubeProxy", err.Error())
    }
    return err
}
```


```c
// SyncLoop runs periodic work.  This is expected to run as a
// goroutine or as the main loop of the app.  It does not return.
func (proxier *metaProxier) SyncLoop() {
    go proxier.ipv6Proxier.SyncLoop() // Use go-routine here!
    proxier.ipv4Proxier.SyncLoop()    // never returns
}
```


## Data Plane: Three Modes

控制面上 kube-proxy 通过 informer watch Service / EndpointSlice / Node，真正干活的数据面在 v1.36 有四种实现（`pkg/proxy/apis/config/types.go:253-256`）：

| 模式 | 状态（v1.36 视角） | 数据面结构 |
|------|------|-----------|
| `iptables` | **Linux 默认**；成熟稳定 | nat 表两级自定义链 |
| `ipvs` | **v1.35 deprecated**，计划 v1.40 默认禁用、v1.43 移除 | 内核 LVS 哈希表 + 辅助 iptables 链 |
| `nftables` | **v1.33 GA**，需显式 `--proxy-mode=nftables` | 自有 `kube-proxy` 表 + verdict map |
| `kernelspace` | Windows 专用（winkernel） | HNS |

`userspace` 模式已在 v1.26 从代码树中移除。这里有个容易搞错的组合：**`NFTablesProxyMode` gate 虽已 GA 并锁定为默认开启，但默认模式仍然是 iptables**——gate 决定"这个实现可用"，`--proxy-mode` 才决定用哪个（`cmd/kube-proxy/app/server_linux.go:48-51`）。

注意 kube-proxy 名字里有 "proxy"，但它自己**不转发任何流量**——只负责把负载均衡翻译成内核规则，转发全部在内核 netfilter / ipvs 中完成。

### iptables Mode

kube-proxy 把每个 Service 翻译成节点 `nat` 表里的两级自定义链：

1. `KUBE-SERVICES` 是总入口，匹配 ClusterIP:Port 后跳到该 Service 的 `KUBE-SVC-XXXXXXXX` 链；
2. `KUBE-SVC-XXXXXXXX` 链用 `statistic` 模块按概率把流量分发到每个后端的 `KUBE-SEP-XXXXXXXX` 链；
3. `KUBE-SEP-XXXXXXXX` 链执行 DNAT，把目的地址改写成具体 Pod IP:targetPort。

```shell
$ iptables-save | grep KUBE-SVC
-A KUBE-SVC-XXXXXXXX -m statistic --mode random --probability 0.33333 -j KUBE-SEP-AAAAAAAA
-A KUBE-SVC-XXXXXXXX -m statistic --mode random --probability 0.50000 -j KUBE-SEP-BBBBBBBB
-A KUBE-SVC-XXXXXXXX                                        -j KUBE-SEP-CCCCCCCC
```

这是**概率抽签，不是精确轮询**：3 个后端时前两条各抽 1/3、1/2，剩余流量兜底给第三条；概率值在每次后端变更时全量重算。它有两个规模问题：iptables 规则更新是整表刷入、报文匹配是线性遍历，规则数随 Service × Endpoint 线性增长，大集群下规则同步延迟和 CPU 开销都会放大——这正是 IPVS 模式要解决的问题。

DNAT 依赖 conntrack 保证连接粒度的一致性：同一个 TCP 连接的所有报文始终 DNAT 到同一个 Pod，天然实现会话保持。Pod 被摘除时旧 conntrack 条目不清理会造成连接黑洞，kube-proxy 在同步规则时会主动删除失效条目，排障时也可手动 `conntrack -D`。

### IPVS Mode

IPVS 基于内核 LVS，Service 规则存在哈希表中，查找复杂度 O(1)，且支持多种调度算法：

```shell
$ ipvsadm -ln
Prot LocalAddress:Port Scheduler Flags
  -> RemoteAddress:Port    Forward Weight ActiveConn InActConn
TCP  10.96.0.168:80 rr
  -> 10.244.1.3:80         Masq    1      0          0
  -> 10.244.2.7:80         Masq    1      0          0
  -> 10.244.3.9:80         Masq    1      0          0
```

`rr`（轮询）是默认值，此外还有 `wrr`（加权轮询）、`lc`（最少连接）、`sh`（源地址哈希）、`dh`（目标地址哈希）等，通过 kube-proxy 配置 `ipvs.scheduler` 指定；Forward 列的 `Masq` 表示同样走 DNAT（MASQUERADE）改写。

#### Why ClusterIP Can Be Pinged: kube-ipvs0

ClusterIP 没有绑在任何真实网卡上，Pod 发出的包为什么能路由到它？IPVS 模式下，kube-proxy 在每个节点创建了一块 **dummy 网卡 `kube-ipvs0`**，把集群中所有 ClusterIP 以 `/32` 地址绑到这块网卡上（源码里只做 `LinkAdd(&netlink.Dummy{...})`，`NOARP` 是内核 dummy 设备的默认属性，并非 kube-proxy 显式设置）：

```shell
$ ip addr show kube-ipvs0
7: kube-ipvs0: <BROADCAST,NOARP,UP,LOWER_UP> mtu 1500 qdisc noqueue
    inet 10.96.0.1/32 brd 10.96.0.1 scope host kube-ipvs0
    inet 10.96.0.168/32 brd 10.96.0.168 scope host kube-ipvs0
```

这样本机协议栈认为这些 VIP "就在本地"，流量进入协议栈后由 ipvs 规则截获并 DNAT 到后端 Pod；dummy 网卡本身不收发包，只负责让路由判定成立。iptables 模式不需要这块网卡——它靠 `KUBE-SERVICES` 链挂在 PREROUTING/OUTPUT 钩子上、在路由判定之前就完成改写。NodePort 与 `externalTrafficPolicy`（Cluster/Local）同样由各自的链或 ipvs 规则实现，Local 模式只转发给本节点 Pod，可保留客户端源 IP。

### nftables Mode

v1.33 起 GA 的第三种后端（KEP-3866）。它不借用内核保留表，而是自建一张 `ip kube-proxy` 表，把 nat / filter 型 base chain 分别挂在 prerouting / output / postrouting 上。

结构上最大的变化是**用 verdict map 取代逐 Service 建链**：

```shell
map serviceIPsMap { type ipv4_addr . inet_proto . inet_service : verdict }
```

iptables 里的 `KUBE-SVC-XXXX` 那一层被一张哈希表替掉，一条 `vmap @serviceIPsMap` 规则完成分发。但每个 endpoint 仍会建链，DNAT 与 conntrack 的角色不变——所以它解决的是**规则规模增长带来的控制面同步与数据面遍历开销**，而不是"绕开 netfilter"。

硬性前置条件是内核 ≥ 5.13，不满足直接启动失败；环境变量 `KUBE_PROXY_NFTABLES_SKIP_KERNEL_VERSION_CHECK` 可绕过该检查。把 nftables 设为默认模式是后续 KEP（KEP-5343）的事，v1.36 仍需显式 `--proxy-mode=nftables`。

> [!NOTE]
> v1.37 的演进：nftables 后端改用 **netlink 直写**（不再 `exec` 调用 `nft` CLI），规则更新走内核 netlink 接口，减少进程间开销；同时 resync 性能被重新优化，大规则集下的周期性全量对账耗时显著下降。行为上有两个与 iptables 的差异值得记：
> - **NodePort 暴露范围**：iptables 模式默认在所有本地地址（含 `127.0.0.1`）上暴露 NodePort；nftables 模式默认只绑节点的 **primary** 地址（`NodePortAddressesPrimary`），v1.37 才提供 opt-in 的 loopback 用户态代理以恢复 `127.0.0.1` 上的 NodePort。
> - **conntrack 前 6.1 内核 bug 的 workaround**：iptables 模式会安装一段针对 pre-6.1 内核 conntrack 缺陷的规避规则，nftables 模式**按设计不安装**该 workaround（其 DNAT 路径不触发该缺陷）。

### EndpointSlice: Data Structure for the Backend List

早期一个 Service 的全部后端放在单个 Endpoints 对象里，后端一多每次变更都要全量推送。新版本默认拆成 EndpointSlice：每个 slice 默认最多装 100 个端点（控制器可配置，不是 API 协议上限），按协议/地址族分片，kube-proxy watch 时只收自己关心的增量：

```shell
$ kubectl get endpointslices -l kubernetes.io/service-name=nginx-service
NAME                  ADDRESSTYPE   PORTS   ENDPOINTS                 AGE
nginx-service-abc12   IPv4          80      10.244.1.3,10.244.2.7,... 30s
```

上文源码中 `NewEndpointSliceConfig(...).RegisterEventHandler(s.Proxier)` 注册的回调就是在等这些事件：收到 Service/EndpointSlice 变化后，proxier 合并变更并在 SyncLoop 中调用 `syncProxyRules()` 全量重刷本节点的 iptables/ipvs 规则。

kube-proxy 只是"规则生产者"这一角色，要理解它在整条链路中的位置，见 [K8s 网络](/docs/CS/Container/k8s/net.md)：Pod 网络如何由 CNI 建立、一个报文如何穿过 netfilter 被 DNAT、conntrack 如何还原回包，以及三种模式的规则挂载差异。

### IPVS Deprecation Timeline

IPVS 后端并非因"有缺陷"被弃用，而是内核 IPVS API 与 K8s Service 语义（会话亲和边界、EndpointSlice、双栈）始终不完全契合，官方把维护重心收敛到 nftables。关键时间线：

| 版本 | 事件 |
|------|------|
| v1.11 | IPVS 模式 GA（当初为替代 iptables 规模问题） |
| v1.29 | nftables 模式 alpha（KEP-3866） |
| v1.31 | nftables 模式 beta |
| **v1.33** | **nftables 模式 GA**（`NFTablesProxyMode` gate `LockToDefault`） |
| **v1.35** | **IPVS 模式 deprecated**，启动即打印弃用警告（PR #134539） |
| v1.37 | nftables 默认化推进（KEP-5343 起步） |
| v1.40（计划） | IPVS 默认禁用 |
| v1.43（计划） | IPVS 移除 |

> [!WARNING]
> 迁移 IPVS → nftables 时，一个常被忽视的旋钮丢失：**nftables 模式负载均衡算法固定为随机分发，没有 IPVS 的 `rr`/`wrr`/`lc`/`sh`/`dh` 等调度器字段**。若现网依赖某调度算法做调优（如 `lc` 打散长连接、`sh` 做会话粘滞），需在 nftables 下改用其他手段补偿：`trafficDistribution`（同区/同节点）、拓扑感知路由 hints，或干脆上 eBPF/Cilium 以拿到更精细的 L3-L7 策略。

### 2026 Mode Selection

一句话：**新集群直接上 nftables；还在跑 iptables 的中小集群不急着动；IPVS 集群尽快规划迁移**。

| 场景 | 推荐模式 | 理由 |
|------|---------|------|
| 新集群（节点内核 ≥ 5.13） | `nftables` | v1.33 GA、官方推荐方向、增量更新毫秒级 |
| 中小集群（< ~1000 Service） | `iptables` | 仍是上游默认、成熟、无切换理由 |
| 老内核（< 5.13）无法用 nftables | `iptables` | 不要降级到已弃用的 IPVS |
| 仍在跑 IPVS 且生产正常 | 暂留，但**规划迁 nftables** | 已 deprecated，v1.40 默认禁用 |
| 要 L7 策略 / 极致性能 / 可观测性 | eBPF（Cilium 替 kube-proxy） | 见 [K8s 网络](/docs/CS/Container/k8s/net.md) |

性能量级（单节点、单 Service 吞吐，数字随内核/NIC/CPU 浮动，仅作数量级参考）：`iptables` ~30k pps、`IPVS` ~200k pps、`nftables` ~100k pps、eBPF/Cilium ~500k pps。三者**每包查找复杂度**都接近 O(1)（严格说 `iptables` 是 O(服务×端点) 的线性遍历，规模大时才显现），真正的差距在**规则同步耗时**：`iptables` 全量重写可达秒级，`nftables`/`IPVS` 增量更新在毫秒级——所以"iptables 慢、IPVS 快"是旧结论，今天选型逻辑是"默认 iptables 够用，新内核新集群上 nftables"。

### Configuration, Migration, and Operations

**启用 nftables**（改 kube-proxy ConfigMap 后滚动重启 DaemonSet）：

```yaml
# kubectl edit configmap kube-proxy -n kube-system
apiVersion: kubeproxy.config.k8s.io/v1alpha1
kind: KubeProxyConfiguration
mode: "nftables"
```

```shell
kubectl rollout restart daemonset kube-proxy -n kube-system
kubectl logs -n kube-system -l k8s-app=kube-proxy | grep "Using nftables"
nft list ruleset | grep kube        # 验证规则已写入 kube-proxy 表
```

前置：节点内核 ≥ 5.13 且 `nft` CLI ≥ 1.0.1；不满足时 kube-proxy 直接启动失败，可用 `KUBE_PROXY_NFTABLES_SKIP_KERNEL_VERSION_CHECK` 绕过内核版本检查（仅当发行版的 nft 二进制已与内核特性匹配时）。

**从 IPVS 迁移**：把 `mode` 从 `ipvs` 改为 `nftables` 并滚动重启，kube-proxy 的 `--cleanup` 会在重启时清理旧 IPVS 状态；先确认无强依赖 IPVS 调度器算法（见上节 WARNING）。

**监控指标**（kube-proxy 在 `:10249/metrics` 暴露）：

| 指标 | 含义 | 经验告警 |
|------|------|---------|
| `kubeproxy_sync_proxy_rules_duration_seconds` | 一次规则同步耗时 | 持续 > 1s 就该换模式 |
| `kubeproxy_sync_proxy_rules_iptables_total` | 当前 iptables 规则条数 | 随 Service 数增长 |
| `kubeproxy_sync_proxy_rules_last_timestamp_seconds` | 上次成功同步时间 | 长时间不更新 = 卡住 |

**排障：conntrack 表满**。三种模式都走 netfilter conntrack，高连接速率下 `nf_conntrack` 表可能写满导致丢包（`/proc/sys/net/netfilter/nf_conntrack_count` 逼近 `nf_conntrack_max`）。调大 `net.netfilter.nf_conntrack_max`；对"发出不求还原"的短连接（节点自身健康检查、监控采集）可考虑 `NOTRACK`，但**被 NAT 改写过的流量绝不能 `NOTRACK`**——否则回包查不到映射被丢弃，表现为连接超时。手动清理：`conntrack -D -p udp --dport <port>`。

## Links

- [K8s](/docs/CS/Container/k8s/K8s.md)
- [Service](/docs/CS/Container/k8s/Service.md)
- [K8s 网络](/docs/CS/Container/k8s/net.md)
- [Ingress](/docs/CS/Container/k8s/Ingress.md)
- [CNI 插件对比](/docs/CS/Container/k8s/CNI.md)
- [常见问题排查](/docs/CS/Container/k8s/Issues.md)

## References

- [Kubernetes v1.36.4 source](https://github.com/kubernetes/kubernetes/tree/v1.36.4)
- [Services, Load Balancing, and Networking](https://kubernetes.io/docs/concepts/services-networking/)
- [kube-proxy (component reference)](https://kubernetes.io/docs/reference/command-line-tools-reference/kube-proxy/)
- [KEP-3866: nftables-based kube-proxy backend](https://github.com/kubernetes/enhancements/tree/master/keps/sig-network/3866-nftables-proxy)
- [KEP-5343: make nftables the default kube-proxy backend](https://github.com/kubernetes/enhancements/tree/master/keps/sig-network/5343-nftables-to-default)
- [KEP-5495: deprecate and remove kube-proxy IPVS mode](https://github.com/kubernetes/enhancements/issues/5495)
- [K8s Service 底层原理：ClusterIP 与流量转发](https://mp.weixin.qq.com/s/-B8rs7vFRKciPlhNVECKFQ)
