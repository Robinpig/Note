## Introduction

kube-controller-manager是一个守护进程，内嵌随 Kubernetes 一起发布的核心控制回路。 
在 Kubernetes 中，每个控制器是一个控制回路，通过 API 服务器监视集群的共享状态， 并尝试进行更改以将当前状态转为期望状态
Controller Manager由负责不同资源的多个 Controller 构成，共同负责集群内的 Node、Pod、Endpoint、Namespace、ServiceAccount、ResourceQuota 等所有资源的管理

kube-controller-manager负责确保k8s的实际状态收敛到所需状态



几乎每种特定资源都有特定的 Controller 维护管理以保持预期状态，而 Controller Manager 的职责便是把所有的 Controller 聚合起来：

- 提供基础设施降低 Controller 的实现复杂度
- 启动和维持 Controller 的正常运行


Controller Manager具备高可用性（即多实例同时运行），即基于Etcd集群上的分布式锁实现领导者选举机制，多实例同时运行，通过kube-apiserver提供的资源锁进行选举竞争
抢先获取锁的实例被称为Leader节点（即领导者节点），并运行kube-controller-manager组件的主逻辑；而未获取锁的实例被称为Candidate节点（即候选节点），运行时处于阻塞状态
在Leader节点因某些原因退出后，Candidate节点则通过领导者选举机制参与竞选，成为Leader节点后接替kube-controller-manager的工作




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

## 

Controller Manager 在 `cmd/kube-controller-manager/app/controllermanager.go` 的 `NewControllerInitializers` 函数中初始化了所有的 Controller

## Links

- [K8s](/docs/CS/Container/k8s/K8s.md)