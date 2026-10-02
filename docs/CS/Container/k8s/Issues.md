## Introduction

K8s 的所有故障最终都会表现为某种资源状态异常。排查的核心方法是：**先看 Events（describe），再看容器日志，最后看组件日志（kubelet / controller-manager）**。本文按"Pod 状态异常、Node 异常、网络不通、组件失联、身份与证书"五类整理常见症状与根因。

## Pod 状态异常

| 现象 | 常见根因 | 定位方式 |
|------|---------|---------|
| Pending | 集群资源不足 / 无节点满足亲和性 / PVC 未绑定 | `kubectl describe pod` 看 FailedScheduling 事件 |
| ImagePullBackOff / ErrImagePull | 镜像名或 tag 错误、私有仓库未配 secret、国内拉不到 gcr 镜像 | describe 看拉取报错；`kubectl create secret docker-registry` |
| CrashLoopBackOff | 应用自身崩溃、健康检查过严、OOMKilled | `logs --previous`；退出码 137 = OOM/被 SIGKILL |
| OOMKilled | 内存 limit 过小或泄漏 | describe 看 `Last State`；结合监控确认内存曲线 |
| Evicted | 节点资源压力（磁盘/内存）触发驱逐 | 看 Node 事件与 kubelet 驱逐阈值 |
| Init:Error / Init:CrashLoopBackOff | Init 容器失败，业务容器不会启动 | 逐个排查 InitContainers 日志 |
| Completed | Job/一次性任务正常退出，非故障 | 确认 restartPolicy 与预期一致 |
| Terminating（长时间不消失） | finalizer 未清空 / foreground 级联未完 / 容器停不下来 | 见下方专节 |
| ContainerCreating（长时间） | 卷未就绪 / 镜像拉取中 / CNI 未就绪 | 按卷的异步往返逐层查，见下方专节 |

### 案例：健康检查超时导致 CrashLoopBackOff

Pod 出现 CrashLoopBackOff 状态，就想到大概率是 Pod 内服务自身的原因。使用 kubectl describe 命令查看：从 Event 日志可以看出，是 calico 的健康检查没通过导致的重启，出错原因也比较明显：`net/http: request canceled while waiting for connection (Client.Timeout exceeded while awaiting headers)`——建立连接超时，手动在控制台执行健康检查命令，发现确实响应慢（正常环境是毫秒级别）。考虑到错误原因是建立连接超时，并且业务量比较大，先观察一下 TCP 连接的状态情况（大量 `SYN_RECV` 意味着握手排队），最终指向健康检查超时阈值设置过小 + 高负载下端口接受队列溢出。

细节见 [Pod 故障排查](/docs/CS/Container/k8s/Pod.md?id=故障排查)。

### 案例：Pod 卡在 Terminating

这是删除链路专属的故障，`delete` 返回成功但对象不消失（详见 [删除与级联](/docs/CS/Container/k8s/Deletion.md)）。按三问定位：

```bash
kubectl get pod <name> -o json | jq '{ts: .metadata.deletionTimestamp, grace: .metadata.deletionGracePeriodSeconds, finalizers: .metadata.finalizers}'
```

1. **`finalizers` 非空** → 某个控制器或 admission 没处理完。最后的解决办法是手动摘除，但**空数组的 PUT 本身就是最终的删除请求**，摘完立刻消失。
2. **finalizers 为空但仍 Terminating** → 看节点。节点 Ready 时只有 kubelet 能解锁（v1.36 里 PodGC 已经不再对普通 Terminating Pod 兜底），所以去节点上：`crictl ps` 看容器是否还在、`journalctl -u kubelet` 搜 `SyncTerminatingPod`。
3. **节点已 NotReady** → kubelet 不可能再回包，没人会替它完成收尾。此时可用 `--force --grace-period=0`，但要清楚 force **不等于立即**：`minimumGracePeriodInSeconds = 2` 保证容器至少拿到 2 秒，且 preStop hook 仍会执行。

namespace 卡 Terminating 是同类问题的放大版，且Apiserver 会把 `kubernetes` finalizer 放在 `spec.finalizers` 里让用户改不掉。最快的诊断是看 condition：`kubectl get ns <name> -o yaml` 里的 `NamespaceFinalizersRemaining` 会**直接点名是哪个 finalizer 卡住**。

### 案例：Pod 卡在 ContainerCreating

绝大多数长期 ContainerCreating 指向**卷没准备好**。这条链路要经由 etcd 做两次异步交接（kubelet 上报意图 → controller attach → kubelet 才挂载），所以要**按层往上查，而不是先翻 kubelet 日志**：

```bash
# 1. kubelet 说了要用这个卷吗
kubectl get node <node> -o jsonpath='{.status.volumesInUse}'
# 2. controller 把它挂到节点上了吗
kubectl get node <node> -o jsonpath='{.status.volumesAttached}'
# 3. CSI 侧应答了吗
kubectl get volumeattachment | grep <pv-name>
kubectl describe volumeattachment <va-name>     # 看 Status.AttachError
```

顺序是关键：**`VolumesInUse` 里有、`VolumesAttached` 里没有 ⇒ 卡在 controller / external-attacher 这一环**，此时看 kubelet 日志毫无意义（它还在等）。反过来才是 kubelet 侧的 stage/publish 问题。

- 卡在第一跳：看 `VolumeAttachment` 的 `Status.AttachError`、external-attacher 日志、云厂商侧的挂载配额。
- 卡在第二跳：kubelet 日志搜 `MountVolume` / `NodeStageVolume` / `NodePublishVolume`。常见是 CSI node 插件未就绪，或 `/var/lib/kubelet` 所在分区空间不足。
- **耗时正好在 2 分钟出头**：这是 kubelet 的 `podAttachAndMountTimeout`（2m3s）到期放弃本轮 sync 的特征。所以「时好时坏」往往不是抖动，而是每次都在超时边缘。

完整链路见 [持久化存储](/docs/CS/Container/k8s/Storage.md)。

## Node 异常

- **NotReady**：kubelet 与 apiserver 心跳丢失。排查链路：kubelet 是否存活（`systemctl status kubelet`）→ 容器运行时是否正常（crictl info）→ 节点资源是否触发驱逐。
- **MemoryPressure / DiskPressure**：condition 由 kubelet 汇报，会触发 Pod [驱逐](/docs/CS/Container/k8s/Eviction.md)。注意有两套完全不同的机制：kubelet 本地杀 Pod（node-pressure eviction）与控制器按 NoExecute 污点删 Pod（taint eviction），现象相似但排查方向完全不同。
- **Pod 被驱逐但不知是谁干的**：看 Pod 的 `DisruptionTarget` condition 的 `Reason`。`DeletionByTaintManager` = 控制器按污点删的；`TerminationByKubelet` = kubelet 本地压力驱逐；`DeletionByDeviceTaintManager` = DRA 设备污点。
- **部分节点无法启动 Pod**：常见于节点 label 污染了调度（taint/toleration 不匹配）、节点镜像缓存损坏、或 CNI 网络插件在该节点未就绪——`kubectl get pod -n kube-system | grep <node>` 先看系统 Pod。

## 网络不通

按路径逐跳排查：

```
Pod A → Pod B:  检查 NetworkPolicy 是否拦截 → CNI 插件状态 → MTU 不匹配（隧道场景）
Pod → Service:  kube-proxy 规则是否存在（iptables-save | grep <svc>) → endpoint 是否 Ready
集群 → 外网:    SNAT 规则 / DNS（CoreDNS Pod 状态、/etc/resolv.conf）
```

DNS 类故障占比极高：`nslookup kubernetes.default` 从业务 Pod 内先测 CoreDNS。网络模型细节见 [K8s 网络](/docs/CS/Container/k8s/net.md)。

| 症状 | 先查什么 | 常见根因 |
|---|---|---|
| Service 不通但 Pod IP 直连正常 | `iptables-save \| grep <ClusterIP>` 或 `ipvsadm -ln` | 规则没生成（kube-proxy 未运行 / 无权限）；或 EndpointSlice 里没有 Ready 后端 |
| ClusterIP 直接返回 connection refused | `iptables-save \| grep KUBE-SERVICES` | Service 无端点时 filter 表里是**显式 REJECT**——这是设计行为，先确认后端 Ready |
| UDP 服务间歇性丢包 | `conntrack -L -p udp` 看是否有指向已摘除后端的条目 | conntrack 清理在每次 sync 触发，且**只清 UDP**；可 `conntrack -D -p udp --dport <port>` 手动清 |
| 只有跨节点访问失败 | 节点路由表、CNI 隧道/路由状态、`ip link` 看 veth 与隧道设备 | overlay 隧道 MTU 不匹配、BGP 邻居掉线 |
| 配了 NetworkPolicy 之后全断 | `kubectl get networkpolicy -n <ns>` 看是否选中了该 Pod | 被策略选中即该方向默认拒绝，必须逐条显式放行；且需要 CNI 支持策略 |
| NodePort 拿到的源 IP 是节点 IP | Service 的 `externalTrafficPolicy` | `Cluster` 模式会 SNAT；要保源 IP 需改 `Local`，代价是本节点无后端即丢包 |
| 部分客户端不通、部分正常 | `externalTrafficPolicy` / `internalTrafficPolicy` | `Local` 在本节点无后端时**直接丢包、不回退**，属设计行为 |
| kube-proxy 启动失败提示内核版本不足 | `uname -r` | nftables 模式要求内核 ≥ 5.13 |

> [!WARNING]
> 三个容易误判的点：**CNI 的日志不在 kubelet 里**——kubelet 已完全不调用 CNI，网络建立由 containerd/CRI-O 负责，`/etc/cni/net.d` 的配置错误要去运行时日志看；**`kube-ipvs0` 上出现 ClusterIP 只说明 kube-proxy 绑定了地址**，它只是让路由判定成立的 dummy 网卡，不代表后端可用；**iptables 模式的"负载均衡"是概率抽签**，小样本下流量分布不均属正常，别急着当故障处理。

进不去容器也算常态：镜像是 distroless（没有 shell）、`kubectl exec` 报错、或运行时/节点已经在报警。这时退到节点上按"Pod → 容器 ID → 宿主 PID → `/proc/PID` 这条链走——`nsenter` 不经过 daemon 也能观察容器的 namespace 与 rootfs，方法见 [容器定位](/docs/CS/Container/locate.md)。

## 组件失联

- apiserver 无响应：etcd 集群先看健康（`etcdctl endpoint health`），etcd 故障会导致整个控制面冻结，但存量 Pod 不受影响——这是"控制面与数据面解耦"的体现。
- controller-manager / scheduler 单点故障不直接影响存量流量，但新建副本不再被调度、删除的副本不再被重建。

## 身份与证书类故障

这类故障的共同特征是**报错信息里出现 401 / `x509: certificate` / `Unauthorized`**，而根因大多不在这条报错所在的组件上。完整链路见 [身份与证书](/docs/CS/Container/k8s/Identity.md)。

| 现象 | 先查什么 | 常见根因 |
|---|---|---|
| `kubeadm join` 报 `Unauthorized` | `kubectl get secret -n kube-system bootstrap-token-<id> -o yaml` | token 的 `usage-bootstrap-authentication` 不是 `"true"`、已过 `expiration`，或 Secret 已被删 |
| `kubectl get csr` 一直 Pending | `kubectl auth can-i create certificatesigningrequests/nodeclient --as=system:bootstrap:<id>` | RBAC 绑定缺失；组名与 kubeadm 预设不符 |
| CSR 有 Failed 条件但无证书 | `kubectl get csr <name> -o yaml` 的条件 message | CSR 的 usages 与 signerName 不匹配（如 `kube-apiserver-client` 要求含 `client auth`） |
| 服务端证书永不轮换 | kubelet 启动参数与 CSR 列表 | 未开 `--rotate-server-certificates`、CSR 无人批准，或节点**没有任何 IP 地址**导致根本不申请 |
| 集群大面积 401 / 节点 NotReady | 节点上 `openssl x509 -in kubelet-client-current.pem -noout -dates` | 轮换长期失败；配合 `kubelet_client_expiration_renew_errors` 指标确认 |
| `kubectl logs` 提示 `jws-kubeconfig-*` 校验失败 | `kubectl get cm cluster-info -n kube-public -o yaml` | `bootstrapsigner` **默认关闭**，`cluster-info` 从未被签名 |
| Pod 内 token 突然失效 | `kubectl get pod <p> -o jsonpath='{.metadata.uid}'` | token 绑定的 Pod 被重建导致 UID 变化，认证层立即判无效 |

> [!WARNING]
> 两个容易误判的点：**bootstrap token 过期后 Secret 不会自动消失**（`tokencleaner` 默认禁用），所以"Secret 还在"不等于"token 有效"；**Pod 里挂载的 token 默认不是 1 小时**，admission 注入的 `3607` 秒会被 extend-expiration 逻辑延长到 1 年，手写 `spec.expirationSeconds` 才会拿到短期 token。

## Links

- [Pod](/docs/CS/Container/k8s/Pod.md)
- [K8s 网络](/docs/CS/Container/k8s/net.md)
- [Service](/docs/CS/Container/k8s/Service.md)
- [kubelet](/docs/CS/Container/k8s/kubelet.md)
- [etcd](/docs/CS/Container/k8s/etcd.md)
- [kubectl](/docs/CS/Container/k8s/kubectl.md)
- [容器定位](/docs/CS/Container/locate.md)
