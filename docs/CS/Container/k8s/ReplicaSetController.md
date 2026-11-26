## Introduction

> [!NOTE]
> 本文源码片段基于 **Kubernetes v1.37.2**（`pkg/controller/replicaset/replica_set.go`）逐字核对。ReplicaSet 控制器与 Job 控制器共享同一套骨架（informer + workqueue + ControllerExpectations），`NewBaseController` 同时服务 ReplicaSet 与 ReplicationController（历史上的 RC 控制器已被合并）。

```go
func newReplicaSetControllerDescriptor() *ControllerDescriptor {
    return &ControllerDescriptor{
        name:     names.ReplicaSetController,
        aliases:  []string{"replicaset"},
        initFunc: startReplicaSetController,
    }
}
```


```go
func startReplicaSetController(ctx context.Context, controllerContext ControllerContext, controllerName string) (controller.Interface, bool, error) {
    go replicaset.NewReplicaSetController(
        ctx,
        controllerContext.InformerFactory.Apps().V1().ReplicaSets(),
        controllerContext.InformerFactory.Core().V1().Pods(),
        controllerContext.ClientBuilder.ClientOrDie("replicaset-controller"),
        replicaset.BurstReplicas,
    ).Run(ctx, int(controllerContext.ComponentConfig.ReplicaSetController.ConcurrentRSSyncs))
    return nil, true, nil
}
```


```go
func NewReplicaSetController(ctx context.Context, rsInformer appsinformers.ReplicaSetInformer, podInformer coreinformers.PodInformer, kubeClient clientset.Interface, burstReplicas int) *ReplicaSetController {
    logger := klog.FromContext(ctx)
    eventBroadcaster := record.NewBroadcaster(record.WithContext(ctx))
    if err := metrics.Register(legacyregistry.Register); err != nil {
        logger.Error(err, "unable to register metrics")
    }
    return NewBaseController(logger, rsInformer, podInformer, kubeClient, burstReplicas,
        apps.SchemeGroupVersion.WithKind("ReplicaSet"),
        "replicaset_controller",
        "replicaset",
        controller.RealPodControl{
            KubeClient: kubeClient,
            Recorder:   eventBroadcaster.NewRecorder(scheme.Scheme, v1.EventSource{Component: "replicaset-controller"}),
        },
        eventBroadcaster,
    )
}
```


```go
// NewBaseController is the implementation of NewReplicaSetController with additional injected
// parameters so that it can also serve as the implementation of NewReplicationController.
func NewBaseController(logger klog.Logger, rsInformer appsinformers.ReplicaSetInformer, podInformer coreinformers.PodInformer, kubeClient clientset.Interface, burstReplicas int,
    gvk schema.GroupVersionKind, metricOwnerName, queueName string, podControl controller.PodControlInterface, eventBroadcaster record.EventBroadcaster) *ReplicaSetController {

    rsc := &ReplicaSetController{
        GroupVersionKind: gvk,
        kubeClient:       kubeClient,
        podControl:       podControl,
        eventBroadcaster: eventBroadcaster,
        burstReplicas:    burstReplicas,
        expectations:     controller.NewUIDTrackingControllerExpectations(controller.NewControllerExpectations()),
        queue: workqueue.NewTypedRateLimitingQueueWithConfig(
            workqueue.DefaultTypedControllerRateLimiter[string](),
            workqueue.TypedRateLimitingQueueConfig[string]{Name: queueName},
        ),
    }

    rsInformer.Informer().AddEventHandler(cache.ResourceEventHandlerFuncs{
        AddFunc: func(obj interface{}) {
            rsc.addRS(logger, obj)
        },
        UpdateFunc: func(oldObj, newObj interface{}) {
            rsc.updateRS(logger, oldObj, newObj)
        },
        DeleteFunc: func(obj interface{}) {
            rsc.deleteRS(logger, obj)
        },
    })
    rsInformer.Informer().AddIndexers(cache.Indexers{
        controllerUIDIndex: func(obj interface{}) ([]string, error) {
            rs, ok := obj.(*apps.ReplicaSet)
            if !ok {
                return []string{}, nil
            }
            controllerRef := metav1.GetControllerOf(rs)
            if controllerRef == nil {
                return []string{}, nil
            }
            return []string{string(controllerRef.UID)}, nil
        },
    })
    rsc.rsIndexer = rsInformer.Informer().GetIndexer()
    rsc.rsLister = rsInformer.Lister()
    rsc.rsListerSynced = rsInformer.Informer().HasSynced

    podInformer.Informer().AddEventHandler(cache.ResourceEventHandlerFuncs{
        AddFunc: func(obj interface{}) {
            rsc.addPod(logger, obj)
        },
        // This invokes the ReplicaSet for every pod change, eg: host assignment. Though this might seem like
        // overkill the most frequent pod update is status, and the associated ReplicaSet will only list from
        // local storage, so it should be ok.
        UpdateFunc: func(oldObj, newObj interface{}) {
            rsc.updatePod(logger, oldObj, newObj)
        },
        DeleteFunc: func(obj interface{}) {
            rsc.deletePod(logger, obj)
        },
    })
    rsc.podLister = podInformer.Lister()
    rsc.podListerSynced = podInformer.Informer().HasSynced

    rsc.syncHandler = rsc.syncReplicaSet

    return rsc
}
```




```go
// Run begins watching and syncing.
func (rsc *ReplicaSetController) Run(ctx context.Context, workers int) {
    defer utilruntime.HandleCrash()

    // Start events processing pipeline.
    rsc.eventBroadcaster.StartStructuredLogging(3)
    rsc.eventBroadcaster.StartRecordingToSink(&v1core.EventSinkImpl{Interface: rsc.kubeClient.CoreV1().Events("")})
    defer rsc.eventBroadcaster.Shutdown()

    defer rsc.queue.ShutDown()

    controllerName := strings.ToLower(rsc.Kind)
    logger := klog.FromContext(ctx)
    logger.Info("Starting controller", "name", controllerName)
    defer logger.Info("Shutting down controller", "name", controllerName)

    if !cache.WaitForNamedCacheSync(rsc.Kind, ctx.Done(), rsc.podListerSynced, rsc.rsListerSynced) {
        return
    }

    for i := 0; i < workers; i++ {
        go wait.UntilWithContext(ctx, rsc.worker, time.Second)
    }

    <-ctx.Done()
}
```

读完全文可以提炼出五条机制要点：

1. **事件驱动而非轮询**：控制器监听 ReplicaSet 增删改事件，事件只做入队（更新事件会检查 spec 副本数与 uid 是否变化，删除事件记录删除期望），真正的工作在 worker 的 `syncReplicaSet` 里做。
2. **PodControl 是对 apiserver Pod 写接口的封装**：创建/删除/更新 Pod 的动作统一走 `podControl`（`controller_util` 里对 Clientset 的再封装），方便 mock 与事件记录。
3. **`NewUIDTrackingControllerExpectations` 是带 UID 集合的期望记账**：比 Job 侧的 `ControllerExpectations` 多一层 UID 集合，key 是 ReplicaSet 的 key，用「命名空间/Pod 名」做 uid——防止"Pod 还没从 informer 消失，新一轮 sync 又重复创建"的竞态。
4. **`manageReplicas` 是副本数控制点**：多则删、少则建；批量创建走 `slowStartBatch`（起步 `SlowStartInitialBatchSize = 1`，每轮翻倍），单轮总吞吐上限 `BurstReplicas = 500`——大规模扩容不是一次打满，而是慢启动。
5. **期望达成才进入下一步**：`syncReplicaSet` 开头检查 expectations 是否满足，未满足说明上一轮的 Pod 创建/删除还在路上，本轮直接跳过等事件驱动下一轮。语义层的展开（与 Deployment 的关系、滚动更新）见 [Workloads](/docs/CS/Container/k8s/Workloads.md) 与 [Deployment 一节](/docs/CS/Container/k8s/Workloads.md?id=deployment)。


## Links

- [K8s](/docs/CS/Container/k8s/K8s.md)
- [K8s 架构与四条主链路](/docs/CS/Container/k8s/Architecture.md)
- [controller-manager](/docs/CS/Container/k8s/controller-manager.md)
- [client-go](/docs/CS/Container/k8s/client-go.md)
- [Workloads](/docs/CS/Container/k8s/Workloads.md)
- [jobController](/docs/CS/Container/k8s/jobController.md)

## References

1. [Kubernetes v1.37.2 pkg/controller/replicaset](https://github.com/kubernetes/kubernetes/tree/v1.37.2/pkg/controller/replicaset)
2. [ReplicaSet - Kubernetes 文档](https://kubernetes.io/docs/concepts/workloads/controllers/replicaset/)
