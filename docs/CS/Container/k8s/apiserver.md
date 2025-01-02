## Introduction



kube-apiserver 是 kubernetes 中与 etcd 直接交互的一个组件，其控制着 kubernetes 中核心资源的变化。它主要提供了以下几个功能：

- 提供 Kubernetes API，包括认证授权、数据校验以及集群状态变更等，供客户端及其他组件调用；
- 代理集群中的一些附加组件组件，如 Kubernetes UI、metrics-server、npd 等；
- 创建 kubernetes 服务，即提供 apiserver 的 Service，kubernetes Service；
- 资源在不同版本之间的转换




kube-apiserver 共由 3 个组件构成（Aggregator、KubeAPIServer、APIExtensionServer），这些组件依次通过 Delegation 处理请求：
- Aggregator：暴露的功能类似于一个七层负载均衡，将来自用户的请求拦截转发给其他服务器，并且负责整个 APIServer 的 Discovery 功能；
- KubeAPIServer ：负责对请求的一些通用处理，认证、鉴权等，以及处理各个内建资源的 REST 服务；
- APIExtensionServer：主要处理 CustomResourceDefinition（CRD）和 CustomResource（CR）的 REST 请求，也是 Delegation 的最后一环，如果对应 CR 不能被处理的话则会返回 404

当请求到达 kube-apiserver 时，kube-apiserver 首先会执行在 http filter chain 中注册的过滤器链，该过滤器对其执行一系列过滤操作，主要有认证、鉴权等检查操作。当 filter chain 处理完成后，请求会通过 route 进入到对应的 handler 中，handler 中的操作主要是与 etcd 的交互


## Run

启动入口cmd/kube-apiserver/app/server.go

```c
func Run(ctx context.Context, opts options.CompletedOptions) error {
    // To help debugging, immediately log version
    klog.Infof("Version: %+v", version.Get())

    klog.InfoS("Golang settings", "GOGC", os.Getenv("GOGC"), "GOMAXPROCS", os.Getenv("GOMAXPROCS"), "GOTRACEBACK", os.Getenv("GOTRACEBACK"))

    config, err := NewConfig(opts)
    if err != nil {
        return err
    }
    completed, err := config.Complete()
    if err != nil {
        return err
    }
    server, err := CreateServerChain(completed)
    if err != nil {
        return err
    }

    prepared, err := server.PrepareRun()
    if err != nil {
        return err
    }

    return prepared.Run(ctx)
}
```

```c
func CreateServerChain(config CompletedConfig) (*aggregatorapiserver.APIAggregator, error) {
    notFoundHandler := notfoundhandler.New(config.KubeAPIs.ControlPlane.Generic.Serializer, genericapifilters.NoMuxAndDiscoveryIncompleteKey)
    apiExtensionsServer, err := config.ApiExtensions.New(genericapiserver.NewEmptyDelegateWithCustomHandler(notFoundHandler))
    if err != nil {
        return nil, err
    }
    crdAPIEnabled := config.ApiExtensions.GenericConfig.MergedResourceConfig.ResourceEnabled(apiextensionsv1.SchemeGroupVersion.WithResource("customresourcedefinitions"))

    kubeAPIServer, err := config.KubeAPIs.New(apiExtensionsServer.GenericAPIServer)
    if err != nil {
        return nil, err
    }

    // aggregator comes last in the chain
    aggregatorServer, err := controlplaneapiserver.CreateAggregatorServer(config.Aggregator, kubeAPIServer.ControlPlane.GenericAPIServer, apiExtensionsServer.Informers.Apiextensions().V1().CustomResourceDefinitions(), crdAPIEnabled, apiVersionPriorities)
    if err != nil {
        // we don't need special handling for innerStopCh because the aggregator server doesn't create any go routines
        return nil, err
    }

    return aggregatorServer, nil
}
```


```c
// pkg/controlplane/apiserver/aggregator.go
func CreateAggregatorServer(aggregatorConfig aggregatorapiserver.CompletedConfig, delegateAPIServer genericapiserver.DelegationTarget, crds apiextensionsinformers.CustomResourceDefinitionInformer, crdAPIEnabled bool, apiVersionPriorities map[schema.GroupVersion]APIServicePriority) (*aggregatorapiserver.APIAggregator, error) {
    aggregatorServer, err := aggregatorConfig.NewWithDelegate(delegateAPIServer)
    if err != nil {
        return nil, err
    }

    // create controllers for auto-registration
    apiRegistrationClient, err := apiregistrationclient.NewForConfig(aggregatorConfig.GenericConfig.LoopbackClientConfig)
    if err != nil {
        return nil, err
    }
    autoRegistrationController := autoregister.NewAutoRegisterController(aggregatorServer.APIRegistrationInformers.Apiregistration().V1().APIServices(), apiRegistrationClient)
    apiServices := apiServicesToRegister(delegateAPIServer, autoRegistrationController, apiVersionPriorities)

    type controller interface {
        Run(workers int, stopCh <-chan struct{})
        WaitForInitialSync()
    }
    var crdRegistrationController controller
    if crdAPIEnabled {
        crdRegistrationController = crdregistration.NewCRDRegistrationController(
            crds,
            autoRegistrationController)
    }

    // Imbue all builtin group-priorities onto the aggregated discovery
    if aggregatorConfig.GenericConfig.AggregatedDiscoveryGroupManager != nil {
        for gv, entry := range apiVersionPriorities {
            aggregatorConfig.GenericConfig.AggregatedDiscoveryGroupManager.SetGroupVersionPriority(metav1.GroupVersion(gv), int(entry.Group), int(entry.Version))
        }
    }

    err = aggregatorServer.GenericAPIServer.AddPostStartHook("kube-apiserver-autoregistration", func(context genericapiserver.PostStartHookContext) error {
        if crdAPIEnabled {
            go crdRegistrationController.Run(5, context.Done())
        }
        go func() {
            // let the CRD controller process the initial set of CRDs before starting the autoregistration controller.
            // this prevents the autoregistration controller's initial sync from deleting APIServices for CRDs that still exist.
            // we only need to do this if CRDs are enabled on this server.  We can't use discovery because we are the source for discovery.
            if crdAPIEnabled {
                klog.Infof("waiting for initial CRD sync...")
                crdRegistrationController.WaitForInitialSync()
                klog.Infof("initial CRD sync complete...")
            } else {
                klog.Infof("CRD API not enabled, starting APIService registration without waiting for initial CRD sync")
            }
            autoRegistrationController.Run(5, context.Done())
        }()
        return nil
    })
    if err != nil {
        return nil, err
    }

    err = aggregatorServer.GenericAPIServer.AddBootSequenceHealthChecks(
        makeAPIServiceAvailableHealthCheck(
            "autoregister-completion",
            apiServices,
            aggregatorServer.APIRegistrationInformers.Apiregistration().V1().APIServices(),
        ),
    )
    if err != nil {
        return nil, err
    }

    return aggregatorServer, nil
}
```



```c

```




## Links

- [K8s](/docs/CS/Container/k8s/K8s.md)