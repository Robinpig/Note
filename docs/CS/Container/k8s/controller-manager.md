## Introduction

kube-controller-manager是一个守护进程，内嵌随 Kubernetes 一起发布的核心控制回路。 
在 Kubernetes 中，每个控制器是一个控制回路，通过 API 服务器监视集群的共享状态， 并尝试进行更改以将当前状态转为期望状态
Controller Manager由负责不同资源的多个 Controller 构成，共同负责集群内的 Node、Pod、Endpoint、Namespace、ServiceAccount、ResourceQuota 等所有资源的管理

几乎每种特定资源都有特定的 Controller 维护管理以保持预期状态，而 Controller Manager 的职责便是把所有的 Controller 聚合起来：

- 提供基础设施降低 Controller 的实现复杂度
- 启动和维持 Controller 的正常运行


Controller Manager具备高可用性（即多实例同时运行），即基于Etcd集群上的分布式锁实现领导者选举机制，多实例同时运行，通过kube-apiserver提供的资源锁进行选举竞争
抢先获取锁的实例被称为Leader节点（即领导者节点），并运行kube-controller-manager组件的主逻辑；而未获取锁的实例被称为Candidate节点（即候选节点），运行时处于阻塞状态
在Leader节点因某些原因退出后，Candidate节点则通过领导者选举机制参与竞选，成为Leader节点后接替kube-controller-manager的工作

kube-controller-manager负责确保k8s的实际状态收敛到所需状态
kube-controller-manager中运行了多个控制器 控制器通过Informer机制监听资源对象的Add、Update、Delete事件 并且通过Reconcile调谐机制更新资源对象的状态

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

## 控制器注册表与启动链路

Controller Manager 在启动时把一组控制器**描述**（descriptor）注册进注册表。早期版本是 `cmd/kube-controller-manager/app/controllermanager.go` 里的 `NewControllerInitializers()` 函数，**v1.36 已改为 `controller_descriptor.go` 中的 `KnownControllers()`**：

```go
// cmd/kube-controller-manager/app/controller_descriptor.go:116
func KnownControllers() []string { ... }
func ControllersDisabledByDefault() []string { ... }
```

启动链路（`controllermanager.go:148` 起）依次是：`s.Config(...)` 读取配置 → `CreateControllerContext` 建 Informer 工厂 → `BuildControllers` 构造各控制器 → `InformerFactory.Start` → `close(InformersStarted)` → `RunControllers` 逐个起 goroutine。

控制器之间并非同时起来，`RunControllers` 会给每个控制器套一层随机抖动 `wait.Jitter(ControllerStartInterval, ControllerStartJitterMaxFactor)`，避免同时启动的雷同效应。

卷相关有三个同源但目录不同的控制器：`persistentvolume-binder`（PV/PVC 绑定与供给，`pkg/controller/volume/persistentvolume/`）、`attachdetach`（把卷挂到节点，`pkg/controller/volume/attachdetach/`）、`volume-expander`（扩容，代码里已自述 deprecated，`pkg/controller/volume/expand/expand_controller.go:71`）。前两个是 [持久化存储](/docs/CS/Container/k8s/Storage.md) 链路的主干；另有三个只守护 finalizer 的小控制器（`pvprotection` / `pvcprotection` / `vacprotection`），它们的角色在 [删除与级联](/docs/CS/Container/k8s/Deletion.md) 里有完整说明。

证书与身份相关的是另一组：`csrsigning`（**四个**独立签发放：kubelet-serving / kubelet-client / kube-apiserver-client / legacy-unknown，`pkg/controller/certificates/signer/`）、`csrapproving`（审批，走 SAR）、`csrcleaner`（清理）、`root-ca-cert-publisher`（往每个 namespace 发 `kube-root-ca.crt`）、`kube-apiserver-serving-clustertrustbundle-publisher`（Beta 默认关闭），另有两个**默认禁用**的 `bootstrapsigner` 与 `tokencleaner`。这条链路见 [身份与证书](/docs/CS/Container/k8s/Identity.md)。

## reconcile 模板

每个控制器都跑同一个模板：**从 Informer 拿到事件 → 只把对象 key 放进 WorkQueue → worker 取出 key → 从本地缓存读最新状态 → 对比期望与实际 → 写回 apiserver**。

关键在于队列里只有 key 而非对象，这使得丢事件、重复事件、崩溃重启都不致命。完整的去重机制（`dirty` / `processing` 双集合）与限速参数见 [client-go](/docs/CS/Container/k8s/client-go.md?id=workqueue)，控制器实现可对照 [ReplicaSet Controller](/docs/CS/Container/k8s/ReplicaSetController.md)。

> [!NOTE]
> 一个容易忽略的内存优化：`CreateControllerContext` 会为 SharedInformerFactory 注入一个 transform，把每个对象的 `ManagedFields` 直接丢弃。这个字段只用于 server-side apply 的字段归属追踪，控制器用不上，但在大规模集群里能省下可观的内存。

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

## v1.36 变更要点

| 项 | 变化 |
|---|---|
| 控制器注册表 | `NewControllerInitializers()` → `KnownControllers()` |
| Leader election 锁 | 仅 `leases`，其余返回 error |
| 调度/缓存相关目录 | `pkg/scheduler/internal/` → `pkg/scheduler/backend/` |
| resync 周期 | `MinResyncPeriod` 默认 **12h**，乘 `rand.Float64()+1` → 实际区间 **[12h, 24h)**，刻意错开避免多个控制器 lock-step（`cmd/kube-controller-manager/app/controllermanager.go:191`） |
| 驱逐职责拆分 | `taint-eviction-controller` 独立成控制器（`SeparateTaintEvictionController` 1.34 起 GA 锁定），nodelifecycle 只负责判活与打污点 |

## Links

- [K8s](/docs/CS/Container/k8s/K8s.md)
- [K8s 架构与四条主链路](/docs/CS/Container/k8s/Architecture.md)
- [client-go](/docs/CS/Container/k8s/client-go.md)
- [ReplicaSet Controller](/docs/CS/Container/k8s/ReplicaSetController.md)
- [scheduler](/docs/CS/Container/k8s/scheduler.md)
- [容器知识地图](/docs/CS/Container/README.md)

## References

1. [kube-controller-manager v1.36.4 source](https://github.com/kubernetes/kubernetes/tree/v1.36.4/cmd/kube-controller-manager)
2. [Kubernetes Controllers](https://kubernetes.io/docs/concepts/architecture/controller/)
3. [Leader Election](https://kubernetes.io/docs/concepts/architecture/leases/)
