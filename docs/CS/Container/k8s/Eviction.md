## Introduction

Kubernetes 里 **"eviction" 这个词指两套完全无关的机制**，它们共享一个名字、都能让 Pod 消失，但触发条件、执行者、走的代码路径毫无交集。混淆这两套是排查"节点出问题 Pod 就没了"这类故障时的第一块绊脚石：

| | 污点驱逐（taint-based eviction） | 节点压力驱逐（node-pressure eviction） |
|---|---|---|
| 触发者 | **kube-controller-manager** | **kubelet 自己** |
| 触发条件 | 节点 `spec.taints` 里出现 Pod 不容忍的 `NoExecute` | 节点 memory / disk / inode / PID 越过阈值 |
| 执行位置 | 向 apiserver `DELETE` Pod 对象 | 本地 kill 容器，不经过 apiserver 删除 |
| 目的 | 节点不健康时把 Pod 挪走 | 节点快撑不住时自我减负 |
| 代码 | `pkg/controller/tainteviction/` | `pkg/kubelet/eviction/` |

前者的完整链路是：**kubelet 停止上报 → controller 判定超时 → 打 NoExecute 污点 → 另一个 controller 读到污点 → 删 Pod**。注意这里有**两次跨组件交接**，而且交接介质是 etcd 里的 Node 对象，不是任何 RPC。

后者则是纯粹的本地行为：kubelet 每 10s 看一眼自己的资源水位，越线就挑一个 Pod 本地杀掉，然后把压力写成 Node condition 上报。**它不会去 apiserver 删 Pod 对象**——Pod 对象的终态由 [kubelet](/docs/CS/Container/k8s/kubelet.md) 的 status manager 走 [删除链路](/docs/CS/Container/k8s/Deletion.md) 收尾。

> [!NOTE]
> 本文全部结论基于 **Kubernetes v1.36.4** 源码实读，各处标注文件路径与行号。v1.36 有几处推翻常见认知的改动，统一收在文末「v1.36 反直觉清单」。

---

## Segment 1: Is the Node Still Alive — Heartbeat and Liveness

### Two Sets of Heartbeats Are OR Relationship

节点心跳有两路，很多人以为 Lease 取代了 Node status，其实**两者并存，任意一路到达即视为存活**：

```go
// pkg/controller/nodelifecycle/node_lifecycle_controller.go:915
observedLease, _ := nc.leaseLister.Leases(v1.NamespaceNodeLease).Get(node.Name)
if observedLease != nil && (savedLease == nil || savedLease.Spec.RenewTime.Before(observedLease.Spec.RenewTime)) {
    nodeHealth.lease = observedLease
    nodeHealth.probeTimestamp = nc.now()
}
```

| 心跳源 | 周期 | 常量位置 |
|---|---|---|
| Node status | 10s | `NodeStatusUpdateFrequency`，`pkg/kubelet/apis/config/v1beta1/defaults.go:148` |
| Lease renew | 10s（= 40s × 0.25） | `NodeLeaseDurationSeconds=40`，`defaults.go:151`；`nodeLeaseRenewIntervalFraction=0.25`，`pkg/kubelet/kubelet.go:238` |

Lease 对象放在 `kube-node-lease` 命名空间（`v1.NamespaceNodeLease`，`staging/src/k8s.io/api/core/v1/types.go:31`），名字与 Node 同名。它的存在意义是让心跳更新**只写一个几十字节的小对象**，而不是每次都 patch 整个 Node status——大规模集群下这个差异非常可观。

`NodeLease` 这个 feature gate 在 v1.36 **已经彻底移除**，没有任何开关，Lease 心跳无条件启用。

### Liveness: 50s, Not 40s

`monitorNodeHealth`（`node_lifecycle_controller.go:653`）每 **5s** 跑一轮（`nodeMonitorPeriod`），对每个节点调 `tryUpdateNodeHealth`（`:813`）。判定只有一行：

```go
// :921
if nc.now().After(nodeHealth.probeTimestamp.Add(gracePeriod)) {
```

`gracePeriod` 取哪个值分两种情况：

| 情况 | gracePeriod | 默认值 | 源码 |
|---|---|---|---|
| kubelet 从未上报过 Ready condition | `nodeStartupGracePeriod` | **60s** | `:832`，`config/v1alpha1/defaults.go:48` |
| 正常运行的节点 | `nodeMonitorGracePeriod` | **50s** | `:845`，`config/v1alpha1/defaults.go:46` |

> [!WARNING]
> **`nodeMonitorGracePeriod` 默认 50s，不是流传甚广的 40s。** 40s 是 kubelet 侧 `NodeLeaseDurationSeconds` 的默认值，两者被混为一谈很久了。源码注释（`defaults.go:40-45`）解释了 50s 的来历：它必须大于 HTTP2_PING_TIMEOUT(30s) + HTTP2_READ_IDLE_TIMEOUT(15s) 之和。

### After Timeout: Writes Unknown, Not False

这是最容易搞错的一处。controller **永远不会把 Ready 写成 `False`**——`False` 只能由 kubelet 自己上报（比如 kubelet 主动发现 containerd 挂了）。controller 在超时后写的是 **`Unknown`**，对应污点 `node.kubernetes.io/unreachable`：

```go
// :950-955  已有 condition → 改写
condition.Status = v1.ConditionUnknown
condition.Reason = "NodeStatusUnknown"
condition.Message = "Kubelet stopped posting node status."
```

同时被改写的还有 `NodeMemoryPressure`、`NodeDiskPressure`、`NodePIDPressure` 三个（`:925-932`），**不含** `NodeNetworkUnavailable`——那个由网络插件管理。

所以 `Ready=False` 和 `Ready=Unknown` 语义完全不同：

| 状态 | 谁写的 | 含义 | 对应污点 |
|---|---|---|---|
| `False` | kubelet | 节点在，但自己报告不健康 | `node.kubernetes.io/not-ready` |
| `Unknown` | controller | controller 收不到心跳，猜的 | `node.kubernetes.io/unreachable` |

> [!TIP]
> 排查时看 `Reason` 字段就能分清是谁下的结论：`NodeStatusUnknown` / `NodeStatusNeverUpdated`（`:939`）是 controller 写的，其它 reason 基本都是 kubelet 写的。

---

## Segment 2: Setting Taints — Two Paths, Two Rate Limits

### NoSchedule: Synchronous, Fast

`doNoScheduleTaintingPass`（`:523`）由 8 个 worker 消费 `nodeUpdateQueue`，由 Node informer 事件驱动。它按一张映射表把 condition 翻译成污点：

```go
// :87-104
nodeConditionToTaintKeyStatusMap = map[v1.NodeConditionType]map[v1.ConditionStatus]string{
    v1.NodeReady: {
        v1.ConditionFalse:  v1.TaintNodeNotReady,       // node.kubernetes.io/not-ready
        v1.ConditionUnknown: v1.TaintNodeUnreachable,   // node.kubernetes.io/unreachable
    },
    v1.NodeMemoryPressure: { v1.ConditionTrue: v1.TaintNodeMemoryPressure },
    v1.NodeDiskPressure:   { v1.ConditionTrue: v1.TaintNodeDiskPressure },
    v1.NodePIDPressure:    { v1.ConditionTrue: v1.TaintNodePIDPressure },
    ...
}
```

生成的污点 effect 一律是 **`NoSchedule`**（`:538`），只影响新 Pod 调度，不动存量 Pod。`spec.unschedulable=true` 会额外追加 `node.kubernetes.io/unschedulable:NoSchedule`（`:545`）。

**这一步是 kubelet 驱逐与调度器之间的唯一桥梁**：kubelet 上报 `MemoryPressure=True` → 这里转成 `node.kubernetes.io/memory-pressure:NoSchedule` → 调度器的 `TaintToleration` 插件拦住新 Pod。kubelet 自己从不写压力污点（见第四段）。

### NoExecute: Asynchronous, Rate-limited

`doNoExecuteTaintingPass`（`:578`）每 **100ms** 轮询（`scheduler.NodeEvictionPeriod`，`scheduler/rate_limited_queue.go:35`），从 `zoneNoExecuteTainter[zone]` 出队。但真正的节流在令牌桶里：

```go
// :1144-1155  setLimiterInZone
switch zoneStates[zone] {
case stateNormal:            newQPS = nc.evictionLimiterQPS          // 0.1
case statePartialDisruption: newQPS = nc.enterPartialDisruptionFunc(zoneSize)
case stateFullDisruption:    newQPS = nc.enterFullDisruptionFunc(zoneSize)  // 恢复 0.1
}
```

| 参数 | 默认值 | 源码 |
|---|---|---|
| `evictionLimiterQPS` | **0.1** | `cmd/kube-controller-manager/app/options/nodelifecyclecontroller.go:46` |
| `secondaryEvictionLimiterQPS` | **0.01** | 同上 `:47` |
| `EvictionRateLimiterBurst` | **1** | `scheduler/rate_limited_queue.go:38` |
| `largeClusterThreshold` | **50** | options `:48` |
| `unhealthyZoneThreshold` | **0.55** | options `:49` |

0.1 QPS + burst 1 意味着 **Normal 状态下大约 10 秒才能污点化一个节点**。这是刻意的：节点故障时要给运维留出反应时间，不能一瞬间把整个集群的 Pod 全删了。

### Partition Three-state

`ComputeZoneState`（`:1264`）把每个 zone 归入三态之一：

```go
case readyNodes == 0 && notReadyNodes > 0:
    return notReadyNodes, stateFullDisruption                     // 该 zone 全军覆没
case notReadyNodes > 2 && float32(notReadyNodes)/float32(notReadyNodes+readyNodes) >= nc.unhealthyZoneThreshold:
    return notReadyNodes, statePartialDisruption                  // 超过 2 个且不健康占比 ≥ 55%
default:
    return notReadyNodes, stateNormal
```

注意 `notReadyNodes > 2` 是**严格大于**，即最少 3 个节点才可能进入 PartialDisruption。

进入 PartialDisruption 后限速降到 `ReducedQPSFunc`（`:1199`）：集群规模 > 50 时 0.01 QPS，否则**直接归零**——小集群部分故障时干脆停止驱逐，因为此时大概率是网络抖动而非节点真挂了。

> [!WARNING]
> 反直觉的一点：进入 **FullDisruption**（全集群无 Ready 节点）时，controller 反而会**移除所有节点的污点**（`:1020-1037`），打印 "Entering master disruption mode"。逻辑是：如果所有节点都不健康，那故障很可能在控制面一侧（apiserver 不可达），此时驱逐 Pod 只会造成二次伤害。

---

## Segment 3: Taint Eviction — Who Actually Deleted the Pod

### It Is No Longer node controller's

这是 v1.36 最重要的一处结构性变化。网上几乎所有教程都说"node controller 负责驱逐 Pod"，但在 v1.36：

```go
// pkg/features/kube_features.go:1954-1957
SeparateTaintEvictionController: {
    {Version: "1.29", Default: true, PreRelease: Beta},
    {Version: "1.34", Default: true, PreRelease: GA, LockToDefault: true}, // remove in 1.37
},
```

**GA 且 LockToDefault**，无法关闭。因此 `node_lifecycle_controller.go:393` 的 `if !Enabled(...)` 分支默认不走，`nc.taintManager` 保持 nil，**驱逐由独立控制器 `taint-eviction-controller` 承担**（注册点 `cmd/kube-controller-manager/app/core.go:217`）。

两个控制器的耦合只剩三行：字段声明 `:219`、条件构造 `:395`、条件启动 `:461`。**nodelifecycle 从不调用 tainteviction 的任何方法**——它们的真实衔接是：

> nodelifecycle 写 `node.spec.taints` → tainteviction 自己的 Node informer 观测到变更 → 驱逐

完全通过 etcd 里的对象解耦。

### Decision Core: processPodOnNode

`pkg/controller/tainteviction/taint_eviction.go:451` 是全部的判定逻辑：

```go
463  allTolerated, usedTolerations := v1helper.GetMatchingTolerations(logger, taints, tolerations)
464  if !allTolerated {
468      tc.taintEvictionQueue.AddWork(ctx, ..., now, now)   // 立即
469      return
470  }
471  minTolerationTime := getMinTolerationTime(usedTolerations)
473  if minTolerationTime < 0 {                             // -1：无限容忍
476      return
477  }
480  triggerTime := startTime.Add(minTolerationTime)        // 延时
489  tc.taintEvictionQueue.AddWork(ctx, ..., startTime, triggerTime)
```

`getMinTolerationTime`（`:161`）的返回值决定了三种命运：

| 情况 | 返回值 | 结果 |
|---|---|---|
| 有污点但不被任何 toleration 匹配 | 不参与 | **立即驱逐** |
| 匹配上了，但那些 toleration 都没写 `TolerationSeconds` | **-1** | **永不驱逐** |
| 匹配上了且 `TolerationSeconds = N > 0` | N 秒 | **延时 N 秒** |

> [!WARNING]
> **"没写 tolerationSeconds 就立刻驱逐"是错的，恰恰相反——没写意味着无限容忍。** 默认那 300 秒是 `DefaultTolerationSeconds` admission 插件注入的（`plugin/pkg/admission/defaulttolerationseconds/admission.go:44`，not-ready 与 unreachable 各 300），**不是内建行为**。自己写 toleration 时漏掉 `tolerationSeconds`，Pod 会永远赖在故障节点上。

### Starting Point of Timing: controller's In-process Clock

`tolerationSeconds` 从哪一刻开始数？三种流传说法全都不准确：

- ❌ Pod 创建时间
- ❌ 污点的 `TimeAdded`（tainteviction 包内 grep `TimeAdded` **零命中**）
- ❌ 污点被加到 Node 上的时刻

真实答案是 **taint manager 第一次处理到该 (Pod, 污点) 组合时的 `time.Now()`**：

```go
// :479-489
startTime := now                                    // now 来自 handleNodeUpdate:583 或 handlePodUpdate:530
triggerTime := startTime.Add(minTolerationTime)
scheduledEviction := tc.taintEvictionQueue.GetWorkerUnsafe(podNamespacedName.String())
if scheduledEviction != nil {
    startTime = scheduledEviction.CreatedAt         // ★ 沿用首次排程时刻
    if startTime.Add(minTolerationTime).Before(triggerTime) {
        return                                      // 保持更早的排程，不重置
    }
    ...
}
```

两个推论：

1. 实际起点比污点 `TimeAdded` 晚一个 informer 延迟 + 队列延迟，**所以 Pod 实际存活时间略长于 `tolerationSeconds`**。
2. `:481-487` 保证了后续任何 Pod/Node 更新事件都**不会重置计时器**——否则一次无关紧要的 Pod 更新就能无限续命。

有意思的是，**device taint eviction（DRA）用的是另一套**：它真的读 `TimeAdded`（`pkg/controller/devicetainteviction/device_taint_eviction.go:1231`）。同一份语义，两个控制器两种实现。

### Execution: Direct DELETE, No Eviction subresource

```go
// taint_eviction.go:147
return c.CoreV1().Pods(ns).Delete(ctx, name, metav1.DeleteOptions{})
```

老版本用的 `policy/v1beta1.Eviction` subresource 在 v1.36 **已完全消失**——全仓 `pkg/` 与 `cmd/` 下 `.Evict(` 零命中。删除前会先给 Pod 打一个 `DisruptionTarget` condition（`:135-141`，`Reason: "DeletionByTaintManager"`），这是给 PodDisruptionBudget 用的，让 PDB 知道这次中断不是自愿的。

`DeleteOptions` 是**完全空的**：不覆盖 gracePeriod、不带 UID precondition。对比 device 侧就严谨得多（`device_taint_eviction.go:497` 带了 `Preconditions{UID}`，防止同名 Pod 复用的竞态）。

失败重试也很粗糙——5 次 × 10ms 的紧循环（`:116-124`），失败后就不再回队列，只能等下一次事件。总窗口只有 50ms。

### Concurrency Model

`tainteviction.Controller` 用 **8 个 sharded worker**（`UpdateWorkerSize = 8`，`:57`），Node 与 Pod 更新**按同一个 nodeName 做 FNV 哈希分到同一个 worker**（`:317`/`:338`），这样 node worker 写 `taintedNodes` 与 pod worker 读它就不会有竞态。worker 内部 Node 更新优先于 Pod 更新（`:370-380`）。

---

## Segment 4: kubelet Self-protection — Node Pressure Eviction

这套机制与前面三段**完全没有代码交集**。

### Main Loop

`Start`（`pkg/kubelet/eviction/eviction_manager.go:188`）里已经不是老版本的 `wait.Until`：

```go
// :209-222
go func() {
    for {
        evictedPods, err := m.synchronize(ctx, diskInfoProvider, podFunc)
        if evictedPods != nil && err == nil {
            m.waitForPodsCleanup(logger, podCleanedUpFunc, evictedPods)   // 阻塞等清理，不 sleep
        } else {
            time.Sleep(monitoringInterval)
        }
    }
}()
```

`monitoringInterval` = **10s**（`kubelet.go:197` `evictionMonitoringPeriod`）。但语义变了：驱逐成功后不 sleep，而是阻塞在 `waitForPodsCleanup`（最多 30s，1s 轮询，`:49-50`）。所以实际节奏是"空闲 10s / 清理完立即重试"。

`synchronize`（`:248`）的顺序值得记住：

1. `summaryProvider.Get()` 取统计（`:295`）
2. `makeSignalObservations` 算观测值（`:311`）
3. `thresholdsMet` 判定（`:315`）
4. `nodeConditions` + `PressureTransitionPeriod` 过滤（`:330-339`）
5. `localStorageEviction` —— emptyDir / ephemeral 超限，命中就返回（`:364`）
6. **`reclaimNodeLevelResources` —— 先 GC 试试**（`:387`）
7. 排序 + 逐个驱逐（`:421-443`）

**每轮最多只杀一个 Pod**（`:421-443` 的循环在成功一次后就 break）。这是刻意的保守设计：杀完一个立刻重新观测，很可能已经降压了。

### Default Threshold

```go
// pkg/kubelet/eviction/defaults_linux.go:22-28
var DefaultEvictionHard = map[string]string{
    "memory.available":   "100Mi",
    "nodefs.available":   "10%",
    "nodefs.inodesFree":  "5%",
    "imagefs.available":  "15%",
    "imagefs.inodesFree": "5%",
}
```

三个坑：

> [!WARNING]
> **1. `pid.available` 默认不在阈值里。** 全仓只有 `api/types.go:56` 一处定义它的 signal，`DefaultEvictionHard` 没有它。PID 驱逐是纯 opt-in，必须显式配 `evictionHard: {pid.available: "<N>"}`。相关的 rank 函数、condition 映射、观测代码全都就绪了，就差一个默认值。
>
> **2. 部分覆盖会丢掉其余默认值。** `cmd/kubelet/app/server.go:472` 只在 `EvictionHard == nil` 时整体注入默认表；一旦你显式给了任何一项，其余信号就**没有默认值**了，除非开 `mergeDefaultEvictionSettings`（默认 `false`，`defaults.go:240`）。
>
> **3. 软阈值 grace period 没有 1m30s 这个默认值。** 文档里的 1m30s 只是示例。`EvictionSoftGracePeriod` 默认 `nil`，而且 `helpers.go:147-154` **强制要求**每个软阈值都显式配 grace period，否则 kubelet 启动直接报错。

其余关键默认值：

| 参数 | 默认 | 位置 |
|---|---|---|
| `eviction-pressure-transition-period` | **5m** | `defaults.go:237` |
| `eviction-minimum-reclaim` | `nil`（不生效） | `types.go:606` |
| 硬阈值立即驱逐的 grace | **1s** | `immediateEvictionGracePeriodSeconds`，`eviction_manager.go:62` |
| `memory.available` 计算 | `capacity = AvailableBytes + WorkingSetBytes` | `helpers_others.go:28-33` |

### Sorting: QoS Not Considered

这是另一处常见误解。三个 rank 函数（`helpers.go:816-833`）的排序关键字里**没有 QoS 等级**：

```go
819  rankMemoryPressure:  orderedBy(exceedMemoryRequests, priority, memory).Sort(pods)
824  rankPIDPressure:     orderedBy(priority, process).Sort(pods)
829  rankDiskPressure:    orderedBy(exceedDiskRequests, priority, disk).Sort(pods)
```

实际规则：先按"是否超过自己的 request"，再按 `priority`（低的先走，`:679`），最后按绝对用量降序。QoS 只在 **Admit 阶段**起作用（`eviction_manager.go:163-178`），而且只在"**仅有 memory pressure 一个 condition**"时才放行非 BestEffort 的 Pod；DiskPressure / PIDPressure 下一律拒绝新 Pod。

### Execution: Local kill, Not Through apiserver

```go
// eviction_manager.go:623
err := m.killPodFunc(pod, true, &gracePeriodOverride, func(status *v1.PodStatus) {
    status.Phase = v1.PodFailed
    status.Reason = Reason          // "Evicted"
    status.Message = evictMsg
    ...
})
```

`killPodFunc` 是 kubelet 注入的 `killPodNow`（`kubelet.go:1074`），定义在 `pkg/kubelet/pod_workers.go:1697`，最终走：

> `podWorkers.UpdatePod(SyncPodKill)` → `SyncTerminatingPod` → CRI 停容器

**整条链路没有任何 kubeClient 调用。** apiserver 的 `POST .../pods/{name}/eviction` 是给 `kubectl drain`、descheduler 这类外部客户端用的，kubelet 自我保护从不碰它。

被驱逐的 Pod 会带 `DisruptionTarget` condition（`Reason: "TerminationByKubelet"`，`eviction_manager.go:432`）。但注意：**local storage 超限的那三种驱逐不设这个 condition**（`:546`/`:574`/`:600` 传 nil）。

### Who Set the Taint

kubelet **只写 condition，从不写压力污点**。它唯一写 `node.Spec.Taints` 的地方是注册时的 `--register-with-taints`（`kubelet_node_status.go:325-339`）。

压力污点由 **nodelifecycle controller** 依据 kubelet 上报的 condition 生成（第二段那张映射表）。完整的三方分工是：

```
kubelet        上报 MemoryPressure=True 条件 + 本地杀 Pod（治标）
     ↓ etcd
nodelifecycle  映射成 node.kubernetes.io/memory-pressure:NoSchedule 污点（防新增）
     ↓ etcd
scheduler      TaintToleration 插件读 spec.taints 拒绝新 Pod 落入
```

---

## v1.36 Counterintuitive List

按杀伤力排序，全部已回源码复验：

1. **`nodeMonitorGracePeriod` 是 50s，不是 40s。** 40s 是 kubelet 侧 `NodeLeaseDurationSeconds`。源码注释说明了 50s = HTTP2_PING(30s) + READ_IDLE(15s) 的余量。

2. **`PodEvictionTimeout` 是死配置。** 它只存在于 versioned v1alpha1 API，internal 类型 `NodeLifecycleControllerConfiguration` **根本没有这个字段**。那个著名的"节点挂了 5 分钟后 Pod 被驱逐"的 5 分钟，其实来自 admission 注入的 `tolerationSeconds: 300`。

3. **没写 `tolerationSeconds` = 无限容忍，不是立即驱逐。** `getMinTolerationTime` 此时返回 `-1`，走 `:476` 直接 return。默认的 300s 是 admission 插件给的。

4. **`tolerationSeconds` 的计时起点是 controller 进程内的 `time.Now()`**，不是 `TimeAdded` 也不是 Pod 创建时间。tainteviction 包内 `TimeAdded` 零命中。控制器重启会重置计时。

5. **进入 FullDisruption 时 controller 反而摘掉所有污点**。`handleDisruption:1020-1037`，理由是故障在控制面一侧，驱逐只会雪上加霜。

6. **taint eviction 已独立成控制器且无法关回去。** `SeparateTaintEvictionController` 自 1.34 起 GA + LockToDefault，nodelifecycle 里那条老路径默认不执行。包名也从 `nodelifecycle/scheduler/` 搬到了 `pkg/controller/tainteviction/`。

7. **kubelet 驱逐完全不经过 apiserver。** 走本地 `killPodNow` → `podWorkers.UpdatePod(SyncPodKill)`。

8. **kubelet 驱逐排序不看 QoS。** QoS 只在 Admit 阶段起作用，而且只在"仅有 memory pressure"时放行。

9. **`pid.available` 默认没阈值。** 代码全就绪，就缺一个默认值，属于纯 opt-in。

10. **`zonePodEvictor` 只剩一行注释。** 全仓唯一命中是 `node_lifecycle_controller.go:237` 的过时注释，字段早已只剩 `zoneNoExecuteTainter`。

11. **`eviction-manager` 的 `Start` 不再是 `wait.Until`。** 驱逐成功后改为阻塞等清理（最多 30s），这样能更快确认是否真的降压。

12. **`Start` 里有个 metrics 量纲 bug。** `taint_eviction.go:120` 写的是 `float64(time.Since(fireAt) * time.Second)`——两个 `Duration` 相乘得到 ns²，观测值被放大约 1e9 倍。正确写法是 `.Seconds()`。device 侧的对应代码是对的，可以对照。

13. **`Rank` 里 `UpdateWork` 是死代码。** 全仓非测试无调用点，tainteviction 只用 `AddWork`，而 `AddWork` 在 key 已存在时直接跳过。

14. **`--experimental-allocatable-ignore-eviction` 还在。** 注释说"1.25 移除"，v1.36 里依然健在（`options.go:318`），只是标了 deprecated。

---

## Troubleshooting Quick Reference

| 现象 | 该看什么 |
|---|---|
| 节点 NotReady 但 Pod 一直没被删 | 查 `node.spec.taints` 有没有 NoExecute；再看 Pod 的 toleration 是不是漏了 `tolerationSeconds`（→ 无限容忍） |
| Pod 被删得比预期快 | 查是否没装 `DefaultTolerationSeconds` admission 插件，或显式 toleration 没有 `tolerationSeconds` |
| 节点内存满但没驱逐 | 查 `evictionHard` 是否被部分覆盖导致其余信号失默认值（`mergeDefaultEvictionSettings`） |
| 驱逐一直不生效 | 看 `reclaimNodeLevelResources` 是否每轮都在 GC 后"刚好降压"，导致永远轮不到杀 Pod |
| 大规模集群驱逐过慢 | 正常：Normal 状态 0.1 QPS，约 10 秒一个节点。想加快要调 `node-eviction-rate` |
| 全集群节点都 NotReady 但没驱逐 | 这是**设计如此**：FullDisruption 下 controller 会摘污点并停止驱逐 |

## Links

- [K8s 架构与四条主链路](/docs/CS/Container/k8s/Architecture.md)
- [删除与级联链路](/docs/CS/Container/k8s/Deletion.md)
- [kubelet](/docs/CS/Container/k8s/kubelet.md)
- [controller-manager](/docs/CS/Container/k8s/controller-manager.md)
- [调度器](/docs/CS/Container/k8s/scheduler.md)
- [常见问题排查](/docs/CS/Container/k8s/Issues.md)

## References

1. [Kubernetes v1.36.4 source](https://github.com/kubernetes/kubernetes/tree/v1.36.4)
2. [Node-pressure Eviction](https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/)
3. [Taints and Tolerations](https://kubernetes.io/docs/concepts/scheduling-eviction/taint-and-toleration/)
4. [Node Lifecycle Controller KEP-3902](https://github.com/kubernetes/enhancements/tree/master/keps/sig-node/3902-decouple-taint-manager)
5. [Reclaiming Node Resources](https://kubernetes.io/docs/concepts/scheduling-eviction/node-pressure-eviction/#reclaim-node-resources)
