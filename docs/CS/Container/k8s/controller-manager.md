## Introduction

kube-controller-manager是一个守护进程，内嵌随 Kubernetes 一起发布的核心控制回路。 
在 Kubernetes 中，每个控制器是一个控制回路，通过 API 服务器监视集群的共享状态， 并尝试进行更改以将当前状态转为期望状态
Controller Manager由负责不同资源的多个 Controller 构成，共同负责集群内的 Node、Pod、Endpoint、Namespace、ServiceAccount、ResourceQuota 等所有资源的管理

几乎每种特定资源都有特定的 Controller 维护管理以保持预期状态，而 Controller Manager 的职责便是把所有的 Controller 聚合起来：

- 提供基础设施降低 Controller 的实现复杂度
- 启动和维持 Controller 的正常运行


Controller Manager 具备高可用性（即多实例同时运行），即基于 Etcd 集群上的分布式锁实现领导者选举机制，多实例同时运行，通过 kube-apiserver 提供的资源锁进行选举竞争
抢先获取锁的实例被称为 Leader 节点（即领导者节点），并运行 kube-controller-manager 组件的主逻辑；而未获取锁的实例被称为 Candidate 节点（即候选节点），运行时处于阻塞状态
在 Leader 节点因某些原因退出后，Candidate 节点则通过领导者选举机制参与竞选，成为 Leader 节点后接替 kube-controller-manager 的工作

kube-controller-manager负责确保k8s的实际状态收敛到所需状态
kube-controller-manager 中运行了多个控制器 控制器通过 Informer 机制监听资源对象的 Add、Update、Delete 事件 并且通过 Reconcile 调谐机制更新资源对象的状态

辅助 Controller Manager 完成事件分发的是 client-go

在 Controller Manager 启动时，便会创建一个名为 SharedInformerFactory 的单例工厂，因为每个 Informer 都会与 Api Server 维持一个 watch 长连接，所以这个单例工厂通过为所有 Controller 提供了唯一获取 Informer 的入口，来保证每种类型的 Informer 只被实例化一次


sharedInformerFactory 中最重要的是名为 informers 的 map，其中 key 为资源类型，而 value 便是关注该资源类型的 Informer。每种类型的 Informer 只会被实例化一次，并存储在 map 中，不同 Controller 需要相同资源的 Informer 时只会拿到同一个 Informer 实例。

对于 Controller Manager 来说，维护所有的 Informer 使其正常工作，是保证所有 Controller 正常工作的基础条件。sharedInformerFactory 通过该 map 维护了所有的 informer 实例


### leaderElectAndRun

```go
// leaderElectAndRun runs the leader election, and runs the callbacks once the leader lease is acquired.

// TODO: extract this function into staging/controller-manager

func leaderElectAndRun(ctx context.Context, c *config.CompletedConfig, lockIdentity string, electionChecker *leaderelection.HealthzAdaptor, resourceLock string, leaseName string, callbacks leaderelection.LeaderCallbacks) {

logger := klog.FromContext(ctx)

rl, err := resourcelock.NewFromKubeconfig(resourceLock,

c.ComponentConfig.Generic.LeaderElection.ResourceNamespace,

leaseName,

resourcelock.ResourceLockConfig{

Identity: lockIdentity,

EventRecorder: c.EventRecorder,

},

c.Kubeconfig,

c.ComponentConfig.Generic.LeaderElection.RenewDeadline.Duration)

if err != nil {

logger.Error(err, "Error creating lock")

klog.FlushAndExit(klog.ExitFlushTimeout, 1)

}

  

leaderelection.RunOrDie(ctx, leaderelection.LeaderElectionConfig{

Lock: rl,

LeaseDuration: c.ComponentConfig.Generic.LeaderElection.LeaseDuration.Duration,

RenewDeadline: c.ComponentConfig.Generic.LeaderElection.RenewDeadline.Duration,

RetryPeriod: c.ComponentConfig.Generic.LeaderElection.RetryPeriod.Duration,

Callbacks: callbacks,

WatchDog: electionChecker,

Name: leaseName,

Coordinated: utilfeature.DefaultFeatureGate.Enabled(kubefeatures.CoordinatedLeaderElection),

})

  

panic("unreachable")

}
```

## Controller Descriptor Model

Controller Manager 在启动时把一组控制器**描述**（descriptor）注册进注册表。早期版本是 `cmd/kube-controller-manager/app/controllermanager.go` 里的 `NewControllerInitializers()` 函数，**v1.36 已改为 `controller_descriptor.go` 中的 `NewControllerDescriptors()`**：

```go
// cmd/kube-controller-manager/app/controller_descriptor.go:45
type ControllerDescriptor struct {
	name                      string
	constructor               ControllerConstructor
	requiredFeatureGates      []featuregate.Feature
	aliases                   []string
	isDisabledByDefault       bool
	isCloudProviderController bool
	requiresSpecialHandling   bool
}

// :34 —— 控制器本体只需要实现两个方法
type Controller interface {
	Name() string
	// Run blocks until the context is cancelled.
	// Run must ensure all goroutines are terminated before returning.
	Run(context.Context)
}
```

三个字段决定了启动期的调度：

| 字段 | 作用 |
|---|---|
| `requiredFeatureGates` | 声明门槛，gate 未开则构造出的 Controller 为 nil，直接跳过而不报错 |
| `aliases` | 历史名兼容（如 `nodelifecycle`、`endpoint`），**只许加不许删** |
| `requiresSpecialHandling` | 不进主循环，单独处理 |

`NewControllerDescriptors()`（`:148`）用一个 `register` 闭包做四项 **panic 级**校验：nil descriptor、空名字、重名、无构造函数；最后还检查别名不能与任何正式名冲突（`:242`）。也就是说，控制器注册表的错误是**启动即崩**，不会退化成运行时静默失效。

`requiresSpecialHandling` 当前唯一实例是 `service-account-token-controller`。源码注释写得很直接：它**必须最先启动**，且必须用 `rootClientBuilder` 提供的全权 client——因为它负责铸造其余控制器所用的 token，晚一步其它控制器就取不到凭证。

## Startup Chain

启动链路（`controllermanager.go:275` 起的 `run` 闭包）只有五步，顺序有严格要求：

```
CreateControllerContext   建 informer 工厂与 RESTMapper
  → BuildControllers      逐个构造，注册 healthz / debug handler
    → InformerFactory.Start
      → close(InformersStarted)   放行依赖 sync 的控制器
        → RunControllers          每个控制器一个 goroutine
```

### CreateControllerContext

`controllermanager.go:530`。除了 informer 工厂，还有三件容易被忽略的事：

1. **两个工厂并存**：typed 的 `sharedInformers` 之外还有 metadata-only 的 `metadataInformers`，合成 `ObjectOrMetadataInformerFactory`。GC 这类只需要 metadata 的控制器走后者，能省下大量内存。
2. **`WaitForAPIServer(versionedClient, 10*time.Second)`**：显式等 apiserver 健康，注释说明是为了"apiserver 与 controller manager 同时启动"的场景，不是无限重试。
3. **`DeferredDiscoveryRESTMapper` + memcache discovery**，外加一个 goroutine 每 30s `restMapper.Reset()`——CRD 可以随时增删，RESTMapper 必须能跟进。namespace 删除能否清干净 CR，就取决于这条刷新。

GC 是唯一在 context 阶段就预建内部件的控制器：`GraphBuilder` 在这里用 `InformersStarted` channel 构造（`controllermanager.go:602`），从而让它的启动严格晚于 informer。

### BuildControllers

`controllermanager.go:626`。逐个构造之外做两件挂载：

- 实现 `controller.Debuggable` 的控制器，其 handler 挂到 `/debug/controllers/<name>`；
- 实现 `controller.HealthCheckable` 的控制器，用它自己的 checker 替换默认的 `NamedPingChecker`。

每个控制器在 healthz 上都有一条独立条目，所以 `/healthz` 退化时可以直接看出是哪一个没起来。

### RunControllers

`controllermanager.go:710`。每个控制器一个 goroutine，启动前套 `wait.Jitter(ControllerStartInterval, 1.0)`（`ControllerStartJitter = 1.0`，`:100`）——注意 jitter factor 是 1.0，即实际启动时刻在 `[interval, 2*interval)` 均匀铺开，避免所有控制器同时打 apiserver。

关闭阶段另有一个 goroutine：ctx 取消后每 `shutdownTimeout/3` 打印一次**尚未退出**的控制器名，超时则 `Run` 返回 `errors.New("controller shutdown timeout reached")`。

> [!TIP]
> `Controller.Run` 的契约是"阻塞到 ctx 取消，且返回前必须终止自己所有 goroutine"。这不是风格约定——上面的超时日志正是靠这个契约才能准确报出是谁卡住了。

## Controller Inventory

卷相关有三个同源但目录不同的控制器：`persistentvolume-binder`（PV/PVC 绑定与供给，`pkg/controller/volume/persistentvolume/`）、`attachdetach`（把卷挂到节点，`pkg/controller/volume/attachdetach/`）、`volume-expander`（扩容，代码里已自述 deprecated，`pkg/controller/volume/expand/expand_controller.go:71`）。前两个是 [持久化存储](/docs/CS/Container/k8s/Storage.md) 链路的主干；另有三个只守护 finalizer 的小控制器（`pvprotection` / `pvcprotection` / `vacprotection`），它们的角色在 [删除与级联](/docs/CS/Container/k8s/Deletion.md) 里有完整说明。

证书与身份相关的是另一组：`csrsigning`（**四个**独立签发放：kubelet-serving / kubelet-client / kube-apiserver-client / legacy-unknown，`pkg/controller/certificates/signer/`）、`csrapproving`（审批，走 SAR）、`csrcleaner`（清理）、`root-ca-cert-publisher`（往每个 namespace 发 `kube-root-ca.crt`）、`kube-apiserver-serving-clustertrustbundle-publisher`（Beta 默认关闭），另有两个**默认禁用**的 `bootstrapsigner` 与 `tokencleaner`。这条链路见 [身份与证书](/docs/CS/Container/k8s/Identity.md)。

## reconcile Template

每个控制器都跑同一个模板：**从 Informer 拿到事件 → 只把对象 key 放进 WorkQueue → worker 取出 key → 从本地缓存读最新状态 → 对比期望与实际 → 写回 apiserver**。

关键在于队列里只有 key 而非对象，这使得丢事件、重复事件、崩溃重启都不致命。完整的去重机制（`dirty` / `processing` 双集合）与限速参数见 [client-go](/docs/CS/Container/k8s/client-go.md?id=workqueue)，控制器实现可对照 [ReplicaSet Controller](/docs/CS/Container/k8s/ReplicaSetController.md)。

> [!NOTE]
> 一个容易忽略的内存优化：`CreateControllerContext` 会为 SharedInformerFactory 注入一个 transform，把每个对象的 `ManagedFields` 直接丢弃。这个字段只用于 server-side apply 的字段归属追踪，控制器用不上，但在大规模集群里能省下可观的内存。

## Expectations: The Anti-overshoot Latch

reconcile 模板有一个没有写进上图的零件：**expectations**。

问题很具体——控制器刚写完 5 个 Pod，informer 缓存还没看到这 5 个 Pod，下一个事件又触发 sync，控制器读缓存发现"还是 0 个"，于是又写 5 个。ReplicaSet / DaemonSet / Job 都面临这个超发风险。

解法是给每个 controllerKey 记一组 add/del 计数（`pkg/controller/controller_utils.go:155`）：

```go
// pkg/controller/daemon/daemon_controller.go:1032
// We need to set expectations before creating/deleting pods to avoid race conditions.
dsc.expectations.SetExpectations(logger, dsKey, createDiff, deleteDiff)
```

注意顺序：**先登记，再写**。写完由 Pod 的 Add/Delete 回调递减（`CreationObserved` / `DeletionObserved`，daemon 分别在 `:606` 与 `:723`）。sync 入口先问一句：

```go
// pkg/controller/daemon/daemon_controller.go:975
if dsc.expectations.SatisfiedExpectations(klog.FromContext(ctx), key) {
	if err = dsc.rollingUpdate(ctx, ds, nodeList, hash); err != nil { ... }
}
```

`SatisfiedExpectations`（`controller_utils.go:195`）返回 true 的条件有**三个**，而不只是"计数归零"：

| 条件 | 含义 |
|---|---|
| `Fulfilled()` | 计数器归零，正常路径 |
| `isExpired()` | 超过 `ExpectationsTimeout = 5 * time.Minute`（`:72`） |
| 该 key 没有记录 | 控制器刚创建，或过期后被清理 |

第二、三条是兜底：**watch 事件全丢了也不会永久卡死**，最多阻塞 5 分钟。这与整套系统"宁可慢收敛也不能不收敛"的取向一致。

## Deployment Controller

Deployment 控制器**只操作 ReplicaSet，从不直接操作 Pod**（`pkg/controller/deployment/deployment_controller.go:104`）。它监听 Pod 只是为了算 status 里的 available 数量与清理孤儿。

一次 sync 的主干（`sync.go:57`）先做 revision 对齐：`getAllReplicaSetsAndSyncRevision` → `getNewReplicaSet` 用 `controller.ComputeHash(&newRSTemplate, d.Status.CollisionCount)` 算出 `pod-template-hash`（`sync.go:198`）。hash 撞车时递增 `status.collisionCount` 重算——RS 名字里的那串哈希就是这么来的。

`spec.paused` 且没有 rollback 时只做清理（`sync.go:69`），否则按策略分发到 `rolloutRecreate` / `rolloutRolling`。滚动更新的核心在 `rolling.go:31`：

```go
scaledUp, err := dc.reconcileNewReplicaSet(ctx, allRSs, newRS, d)
if scaledUp {
	return dc.syncRolloutStatus(ctx, allRSs, newRS, d)   // 扩过就收工
}
scaledDown, err := dc.reconcileOldReplicaSets(...)
if scaledDown {
	return dc.syncRolloutStatus(...)                     // 缩过也收工
}
```

**一次 sync 只做一个方向的动作**，绝不同时扩与缩。这保证任何时刻被打断，状态都是可解释的。

缩容额度是滚动更新最容易被讲错的地方（`rolling.go:86`）：

```
maxScaledDown = allPodsCount - minAvailable - newRSUnavailablePodCount
minAvailable  = spec.replicas - maxUnavailable
```

减掉 `newRSUnavailablePodCount` 是关键：如果新 RS 的 Pod 一直 crashloop，**不算这些 Pod 的不可用**，就会得出"还能再拆几台旧的"的错误结论。源码注释里给了完整算例（10 副本、maxUnavailable=2、maxSurge=3，新 RS 全部 crashloop 时 `13 - 8 - 5 = 0`，一台都不许拆）。

另外缩容前先跑 `cleanupUnhealthyReplicas`（`rolling.go:155`），否则旧 RS 里已经不健康的副本会一直占着额度直到 rollout 超时（issue 16737）。

收尾是 `cleanupDeployment`（`sync.go:442`）：按 revision 排序，保留最近 `spec.revisionHistoryLimit` 个旧 RS（**默认 10**，`pkg/apis/apps/v1/defaults.go:65`），其余删除。status 也不是增量维护，而是每次 `syncRolloutStatus` 从当前所有 RS 重新算出来（`calculateStatus`，`sync.go:494`）。

## StatefulSet Controller

StatefulSet 的"有序"不是调度器给的，是控制器自己算出来的序（`pkg/controller/statefulset/stateful_set_control.go:560`）。

先把 Pod 切成两组：ordinal < `spec.replicas` 的进 `replicas`，其余进 `condemned`；然后按顺序跑三段：

```
processReplica    正序：创建 / 更新
fixPodClaim       PVC retention policy
processCondemned  逆序：删除
```

是否串行由 `monotonic := !allowsBurst(set)`（`:649`）决定，落实到 `runForAll`（`:536`）：

```go
func runForAll(pods []*v1.Pod, fn func(i int) (bool, error), monotonic bool) (bool, error) {
	if monotonic {
		for i := range pods {                                  // 严格串行，遇阻塞立即返回
			if shouldExit, err := fn(i); shouldExit || err != nil { return true, err }
		}
	} else {
		if _, err := slowStartBatch(1, len(pods), fn); err != nil { return true, err }  // 慢启动批量
	}
	return false, nil
}
```

`processReplica` 里的四处 `monotonic` 分支（`:445` `:463` `:472` `:481`）就是"前一个 Pod 没 Ready 就不动后一个"的全部实现：terminating、!RunningAndReady、!RunningAndAvailable（含 `minReadySeconds`）都会直接 return 阻塞后续 ordinal。

`OnDelete` 策略在 status 更新后直接短路返回（`:694` 注释：*for the OnDelete strategy we short circuit*）——控制器自己绝不主动删 Pod，等用户删了再按模板重建。

版本历史用 `ControllerRevision` 对象保存，`truncateHistory`（`:178`）按 `revisionHistoryLimit` 清理。

## DaemonSet Controller

DaemonSet 与 Deployment 的形状差别很大：**中间没有任何层级**，控制器直接对每个 Node 判断该不该有 Pod（`podsShouldBeOnNode`，`daemon_controller.go:846`），靠 `getNodesToDaemonPods`（`:793`）建的映射做差。

`manage`（`:998`）一次算出三类动作，然后交给 `syncNodes`：应删的 Pod、需要新建 Pod 的节点、以及"节点已消失但 Pod 还在"的孤儿。三个约束值得记住：

| 约束 | 值 / 位置 | 原因 |
|---|---|---|
| 单轮变更上限 | `BurstReplicas = 250`（`:66`） | createDiff / deleteDiff 都被 clamp（`:1042`） |
| expectations | 写之前登记（`:1032`） | 见上文 |
| 版本历史 | `ControllerRevision`（`update.go:293` `:522`） | 与 Deployment 走 RS 不同，DS 直接用 revision |

滚动更新在 `update.go:44`。`updatedDesiredNodeCounts`（`:584`）算出 maxSurge / maxUnavailable 之后有一条**强制修正**（`:612`）：

```go
if desiredNumberScheduled > 0 && maxUnavailable == 0 && maxSurge == 0 {
	maxUnavailable = 1
}
```

用户把两个值都显式设成 0 时，如果不做这一步，DaemonSet 会永远卡在"一个都不能动"的状态推不动更新。

## Namespace Controller

namespace 删除是控制器里少见的**有状态多阶段**流程，主体在 `pkg/controller/namespace/deletion/namespaced_resources_deleter.go:98`：

| 步骤 | 动作 | 幂等保证 |
|---|---|---|
| 1 | Get 最新 ns，`DeletionTimestamp == nil` 直接返回 | 重复入队无害 |
| 2 | `retryOnConflictError(updateNamespaceStatusFunc)` 刷 status | 冲突重试，不是无条件覆盖 |
| 3 | `deleteAllContent` 枚举所有 namespaced 资源逐个 DeleteCollection | 剩余 >0 抛 `ResourcesRemainingError{estimate}`，退避重来 |
| 4 | `finalizeNamespace` 从 `spec.finalizers` 摘掉本 token | 已 finalized 直接返回 |

两个降级设计撑住了这套流程在真实集群里的可用性：

- `operationNotSupportedCache`（`:229`）缓存不支持 `deletecollection` 的 GVR，命中后不再重试该动词；
- 不支持时回落 `deleteEachItem`（`:380`）逐个删。

第 3 步的资源清单来自 discovery，**不是编译期常量**。所以新装一个 CRD 之后，namespace 删除才会开始清理它的 CR；反过来，如果 CRD 的 apiservice 挂了导致 discovery 拿不到，namespace 会一直卡在 Terminating——这解释了绝大多数"namespace 删不掉"的现场。

## ResourceQuota Controller

`pkg/controller/resourcequota/resource_quota_controller.go`。它有**两条队列**：

| 队列 | 用途 |
|---|---|
| `queue` | 普通重算 |
| `missingUsageQueue`（名字 `resourcequota_priority`，`:118`） | 新建或缺失 usage 的 quota，优先算 |

分流的原因很直接：一个刚创建的 quota 如果 usage 一直没算出来，它会拦住该 namespace 里所有资源创建；让这类请求排在被大量重算堵住的普通队列后面，代价太高。

计量方式也值得注意——它不是事件驱动的增量加减。任何被监控资源的变化经 `replenishQuota`（`:418`）把该 namespace 的 quota 送进队列，出队时**全量重算**（`:446` 处留有 TODO 说明目前做不到按 kind 定向重算）。另有 `enqueueAll`（`:194`）按 `fullResyncPeriod` 周期性全量重算作为兜底，`resyncMonitors`（`:542`）周期性用 discovery 刷新被监控资源集合。

直接后果：**ResourceQuota 是最终一致的**。超额写入有可能在窗口期成功，直到下一次重算才被拦住。不要把它当成硬闸。

## EndpointSlice Controller

`pkg/controller/endpointslice/endpointslice_controller.go`。分片大小由 `--max-endpoints-per-slice` 控制，**默认 100，合法区间 [1, 1000]**（`cmd/kube-controller-manager/app/options/endpointslicecontroller.go:30` `:46`）——调大则 slice 少而单个对象大，调小则相反。

它同样有两条队列：`serviceQueue` 按 Service key 入队；`topologyQueue` 只有一个固定 key（`:81` `topologyQueueItemKey`），专门驱动 `topologyCache` 重新计算端点在 zone 间的分布，使 EndpointSlice 尽量按 zone 切分、减少跨区流量。

老的 `Endpoints` 对象仍由 `endpoints` 控制器维护，另有 `endpointslice-mirroring` 把用户自建的 Endpoints 镜像成 EndpointSlice。两者并存，详见 [Service 与负载均衡](/docs/CS/Container/k8s/Service.md)。

## Node Lifecycle and Taint Eviction

1.34 起 `SeparateTaintEvictionController` GA 锁定后，这条链路一分为二：**node lifecycle 只判活与打污点，真正的 NoExecute 驱逐由独立的 taint-eviction 控制器执行**。

condition 到 taint 的映射是一张静态表（`pkg/controller/nodelifecycle/node_lifecycle_controller.go:87`）：`Ready=False` → `node.kubernetes.io/not-ready`，`Ready=Unknown` → `node.kubernetes.io/unreachable`，MemoryPressure / DiskPressure / PIDPressure / NetworkUnavailable 各自对应一条。

判活在 `monitorNodeHealth`（`:653`）→ `tryUpdateNodeHealth`（`:813`）。节点转为 Unknown 时会调 `controllerutil.MarkPodsNotReady`（`:742`）把该节点上所有 Pod 的 Ready condition 批量刷成 False——**这是直接写 Pod，不是等 kubelet 上报**。

限速按 zone 分片：`zoneNoExecuteTainter map[string]*scheduler.RateLimitedTimedQueue`（`:240`）配合 `zoneStates`（`:244`），使单个可用区整体失联时逐出速率被压到 `SecondaryNodeEvictionRate`，而不是全集群统一的 `NodeEvictionRate`。避免"整区失联 → Pod 被瞬间驱逐到其它区 → 其它区被打爆"。

## Leader Election

多实例通过 apiserver 上的资源锁竞争 Leader，获取锁的实例运行主逻辑，其余阻塞等待。

> [!WARNING]
> **只有 `leases` 一种锁类型还可用**。endpoints、configmaps、endpointsleases、configmapsleases 在 v1.36 中已全部移除，传入这些值会直接返回 error 要求迁移到 leases。

默认参数：

| 参数 | 默认值 |
|---|---|
| ResourceNamespace | kube-system |
| ResourceName | kube-controller-manager |
| LeaseDuration | 30s |
| RenewDeadline | 15s |
| RetryPeriod | 5s |

选主失败或失去 Leader 身份时默认行为是**直接退出进程**（`klog.FlushAndExit(1)`），而不是降级继续运行。这是刻意的：避免两个实例同时认为自己有写权限。开启 `ControllerManagerReleaseLeaderElectionLockOnExit` 后改为主动释放租约，让接管更快。

## v1.36 Key Changes

| 项 | 变化 |
|---|---|
| 控制器注册表 | `NewControllerInitializers()` → `NewControllerDescriptors()`，返回值从 initializer 函数变成 `ControllerDescriptor`；控制器本体接口收窄成 `Name() + Run(ctx)` |
| 控制器命名 | `names.XxxController` 常量化，cloud provider 控制器另用 `cpnames`；旧名以 `aliases` 保留，注册时做重名/别名冲突 panic |
| 启动抖动 | `ControllerStartJitter = 1.0`（`controllermanager.go:100`），实际启动时刻落在 `[interval, 2*interval)` |
| Leader election 锁 | 仅 `leases`，其余返回 error |
| 调度/缓存相关目录 | `pkg/scheduler/internal/` → `pkg/scheduler/backend/` |
| resync 周期 | `MinResyncPeriod` 默认 **12h**，乘 `rand.Float64()+1` → 实际区间 **[12h, 24h)**，刻意错开避免多个控制器 lock-step（`cmd/kube-controller-manager/app/controllermanager.go:191`） |
| 驱逐职责拆分 | `taint-eviction-controller` 独立成控制器（`SeparateTaintEvictionController` 1.34 起 GA 锁定），nodelifecycle 只负责判活与打污点 |
| 新增控制器 | `podgroupprotection`、`podcertificaterequest-cleaner`、`resourcepoolstatusrequest`、`device-taint-eviction`、`validatingadmissionpolicy-status`、`servicecidrs`、`storageversion-migrator`、`selinux-warning` |
| endpoint 侧 | `endpoints`、`endpointslice`、`endpointslice-mirroring` 三个控制器并存，老 Endpoints 并未下线 |

## Links

- [K8s](/docs/CS/Container/k8s/K8s.md)
- [K8s 架构与四条主链路](/docs/CS/Container/k8s/Architecture.md)
- [工作负载总览](/docs/CS/Container/k8s/Workloads.md)
- [垃圾回收](/docs/CS/Container/k8s/GC.md)
- [驱逐](/docs/CS/Container/k8s/Eviction.md)
- [容器知识地图](/docs/CS/Container/README.md)

## References

1. [kube-controller-manager v1.36.4 source](https://github.com/kubernetes/kubernetes/tree/v1.36.4/cmd/kube-controller-manager)
2. [pkg/controller v1.36.4 source](https://github.com/kubernetes/kubernetes/tree/v1.36.4/pkg/controller)
3. [Kubernetes Controllers](https://kubernetes.io/docs/concepts/architecture/controller/)
4. [Leader Election](https://kubernetes.io/docs/concepts/architecture/leases/)
5. [Deployments](https://kubernetes.io/docs/concepts/workloads/controllers/deployment/)
6. [StatefulSets](https://kubernetes.io/docs/concepts/workloads/controllers/statefulset/)
7. [DaemonSet](https://kubernetes.io/docs/concepts/workloads/controllers/daemonset/)
8. [EndpointSlices](https://kubernetes.io/docs/concepts/services-networking/endpoint-slices/)
9. [Resource Quotas](https://kubernetes.io/docs/concepts/policy/resource-quotas/)
10. [Namespaces: deletion and finalizers](https://kubernetes.io/docs/concepts/overview/working-with-objects/namespaces/)
