## Introduction



```c
func newReplicaSetControllerDescriptor() *ControllerDescriptor {
    return &ControllerDescriptor{
        name:     names.ReplicaSetController,
        aliases:  []string{"replicaset"},
        initFunc: startReplicaSetController,
    }
}
```


```c
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


```c
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


```c
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




```c
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

- 总体来看， ReplicaSet 的逻辑并不难，理解起来也很简单，跟 job 控制器差不多。
- ReplicaSet 控制器启动后监听 ReplicaSet 增删改事件，和其他控制器一样，它监听到事件后并没有直接做操作，而是加入到队列里面，通过队列来实现多线程操作。
- 在入列的时候，更新事件会检查 ReplicaSet 副本数和 uid 是否相同，删除事件会做一个删除期望记录的操作。
- ReplicaSet 控制器也引入了 pod 控制器，用来创建/删除/更新 pod 信息，这个 pod 控制器是再 controller_util 里面对 Clientset 操作 Pod 接口的再封装。
- 跟其他控制器一样，监听到 pod 事件时， 先判断 pod 是否处于删除状态，再判断 pod 是否属于 ReplicaSet 对象的，是的话，将 pod 的父对象加入队列，更新 ReplicaSet 对象的状态什么的。
- 我们注意到 NewUIDTrackingControllerExpectations 这个东西，这个在 job 控制的源码里面看到过 ControllerExpectations 的很类似，只不过多了一个集合用来记录 ReplicaSet 的 pod 集合，key 是 ReplicaSet 的 key ，用 pod 命名空间和 pod 名 来做 uid 。
- syncReplicaSet 期望达成才进入下一步的操作。
- manageReplicas 这里是控制 pod 数量的地方，多则删除，少则新增。


## Links


