## Introduction

kube-apiserver 是 kubernetes 中唯一与 etcd 直接交互的一个组件，在k8s中所有组件都通过kube-apiserver操作资源对象

它主要提供了以下几个功能：

- 将 Kubernetes 中的所有资源对象封装成RESTful风格的API接口进行管理
- 进行集群状态管理与元数据管理 是唯一与etcd交互的组件
- 具有丰富的安全访问机制 提供认证、授权以及准入控制器
- 提供集群中各组件的通信与交互功能




kube-apiserver 共由 3 个组件构成（Aggregator、KubeAPIServer、APIExtensionServer），这些组件依次通过 Delegation 处理请求：
- Aggregator：暴露的功能类似于一个七层负载均衡，将来自用户的请求拦截转发给其他服务器，并且负责整个 APIServer 的 Discovery 功能；
- KubeAPIServer ：负责对请求的一些通用处理，认证、鉴权等，以及处理各个内建资源的 REST 服务；
- APIExtensionServer：主要处理 CustomResourceDefinition（CRD）和 CustomResource（CR）的 REST 请求，也是 Delegation 的最后一环，如果对应 CR 不能被处理的话则会返回 404

当请求到达 kube-apiserver 时，kube-apiserver 首先会执行在 http filter chain 中注册的过滤器链，该过滤器对其执行一系列过滤操作，主要有认证、鉴权等检查操作。当 filter chain 处理完成后，请求会通过 route 进入到对应的 handler 中，handler 中的操作主要是与 etcd 的交互



## init

kube-apiserver组件启动后的第一件事情是将Kubernetes所支持的资源注册到Scheme资源注册表中，这样后面启动的逻辑才能够从Scheme资源注册表中拿到资源信息并启动和运行APIExtensionsServer、KubeAPIServer、AggregatorServer这3种服务

资源的注册过程并不是通过函数调用触发的，而是通过Go语言的导入（import）和初始化（init）机制触发的

```go

import (
	"k8s.io/kubernetes/pkg/api/legacyscheme"
	"k8s.io/kubernetes/pkg/master"
  // ...
  }
```

kube-apiserver导入了legacyscheme和master包 kube-apiserver资源注册分为两步：第1步，初始化Scheme资源注册表；第2步，注册Kubernetes所支持的资源

在legacyscheme包中，定义了Scheme资源注册表、Codec编解码器及ParameterCodec参数编解码器。它们被定义为全局变量，这些全局变量在kube-apiserver的任何地方都可以被调用，服务于KubeAPIServer

kube-apiserver启动时导入了master包，master包中的import_known_versions.go文件调用了Kubernetes资源下的install包，通过导入包的机制触发初始化函数

```go
func init() {
	if missingVersions := legacyscheme.Registry.ValidateEnvRequestedVersions(); len(missingVersions) != 0 {
		panic(fmt.Sprintf("KUBE_API_VERSIONS contains versions that are not installed: %q.", missingVersions))
	}
}
```








## Run

启动入口cmd/kube-apiserver/app/server.go

```c
func Run(runOptions *options.ServerRunOptions, stopCh <-chan struct{}) error {
	// To help debugging, immediately log version
	glog.Infof("Version: %+v", version.Get())

	server, err := CreateServerChain(runOptions, stopCh)
	if err != nil {
		return err
	}

	return server.PrepareRun().Run(stopCh)
}
```

### CreateServerChain

> [!WARNING]
> 本节引用的是 Kubernetes 早期版本（约 1.9~1.13）的源码摘录。其中的 `createAPIExtensionsServer`、`CreateKubeAPIServer`、`createAggregatorServer` 三个函数在 **v1.36 中均已不存在**，`insecureServingOptions` 与 `KUBE_API_VERSIONS` 也早已移除。下方代码仅用于对照演进脉络，实际实现请以 v1.36 的写法为准。

三层 delegation 的方向一直没变，但构造方式改成了各层 config 自带 `New` 方法：

```go
// cmd/kube-apiserver/app/server.go:176 —— v1.36.4
func CreateServerChain(config CompletedConfig) (*aggregatorapiserver.APIAggregator, error) {
	notFoundHandler := notfoundhandler.New(config.KubeAPIs.ControlPlane.Generic.Serializer,
		genericapifilters.NoMuxAndDiscoveryIncompleteKey)
	apiExtensionsServer, err := config.ApiExtensions.New(genericapiserver.NewEmptyDelegateWithCustomHandler(notFoundHandler))
	if err != nil {
		return nil, err
	}
	crdAPIEnabled := config.ApiExtensions.GenericConfig.MergedResourceConfig.ResourceEnabled(
		apiextensionsv1.SchemeGroupVersion.WithResource("customresourcedefinitions"))

	kubeAPIServer, err := config.KubeAPIs.New(apiExtensionsServer.GenericAPIServer)
	if err != nil {
		return nil, err
	}

	// aggregator comes last in the chain
	aggregatorServer, err := controlplaneapiserver.CreateAggregatorServer(config.Aggregator,
		kubeAPIServer.ControlPlane.GenericAPIServer,
		apiExtensionsServer.Informers.Apiextensions().V1().CustomResourceDefinitions(),
		crdAPIEnabled, apiVersionPriorities)
	if err != nil {
		return nil, err
	}

	return aggregatorServer, nil
}
```

aggregator 在最外层对外服务，匹配不到路由就往下抛给 kubeAPIServer，再往下抛给 apiextensions。每层都会各自完整跑一遍 filter chain——一个请求最多穿过三次链，这是灵活性换来的代价。

以下为早期版本摘录：

1. createAPIExtensionsServer

2. CreateKubeAPIServer

3. createAggregatorServer

   

```c
func CreateServerChain(runOptions *options.ServerRunOptions, stopCh <-chan struct{}) (*genericapiserver.GenericAPIServer, error) {
	nodeTunneler, proxyTransport, err := CreateNodeDialer(runOptions)
	if err != nil {
		return nil, err
	}
	kubeAPIServerConfig, sharedInformers, versionedInformers, insecureServingOptions, serviceResolver, pluginInitializer, err := CreateKubeAPIServerConfig(runOptions, nodeTunneler, proxyTransport)
	if err != nil {
		return nil, err
	}

	// TPRs are enabled and not yet beta, since this these are the successor, they fall under the same enablement rule
	// If additional API servers are added, they should be gated.
	apiExtensionsConfig, err := createAPIExtensionsConfig(*kubeAPIServerConfig.GenericConfig, versionedInformers, pluginInitializer, runOptions)
	if err != nil {
		return nil, err
	}
	apiExtensionsServer, err := createAPIExtensionsServer(apiExtensionsConfig, genericapiserver.EmptyDelegate)
	if err != nil {
		return nil, err
	}

	kubeAPIServer, err := CreateKubeAPIServer(kubeAPIServerConfig, apiExtensionsServer.GenericAPIServer, sharedInformers, versionedInformers)
	if err != nil {
		return nil, err
	}

	// if we're starting up a hacked up version of this API server for a weird test case,
	// just start the API server as is because clients don't get built correctly when you do this
	if len(os.Getenv("KUBE_API_VERSIONS")) > 0 {
		if insecureServingOptions != nil {
			insecureHandlerChain := kubeserver.BuildInsecureHandlerChain(kubeAPIServer.GenericAPIServer.UnprotectedHandler(), kubeAPIServerConfig.GenericConfig)
			if err := kubeserver.NonBlockingRun(insecureServingOptions, insecureHandlerChain, kubeAPIServerConfig.GenericConfig.RequestTimeout, stopCh); err != nil {
				return nil, err
			}
		}

		return kubeAPIServer.GenericAPIServer, nil
	}

	// otherwise go down the normal path of standing the aggregator up in front of the API server
	// this wires up openapi
	kubeAPIServer.GenericAPIServer.PrepareRun()

	// This will wire up openapi for extension api server
	apiExtensionsServer.GenericAPIServer.PrepareRun()

	// aggregator comes last in the chain
	aggregatorConfig, err := createAggregatorConfig(*kubeAPIServerConfig.GenericConfig, runOptions, versionedInformers, serviceResolver, proxyTransport, pluginInitializer)
	if err != nil {
		return nil, err
	}
	aggregatorConfig.ExtraConfig.ProxyTransport = proxyTransport
	aggregatorConfig.ExtraConfig.ServiceResolver = serviceResolver
	aggregatorServer, err := createAggregatorServer(aggregatorConfig, kubeAPIServer.GenericAPIServer, apiExtensionsServer.Informers)
	if err != nil {
		// we don't need special handling for innerStopCh because the aggregator server doesn't create any go routines
		return nil, err
	}

	if insecureServingOptions != nil {
		insecureHandlerChain := kubeserver.BuildInsecureHandlerChain(aggregatorServer.GenericAPIServer.UnprotectedHandler(), kubeAPIServerConfig.GenericConfig)
		if err := kubeserver.NonBlockingRun(insecureServingOptions, insecureHandlerChain, kubeAPIServerConfig.GenericConfig.RequestTimeout, stopCh); err != nil {
			return nil, err
		}
	}

	return aggregatorServer.GenericAPIServer, nil
}
```



#### createAPIExtensionsServer

```go
func createAPIExtensionsServer(apiextensionsConfig *apiextensionsapiserver.Config, delegateAPIServer genericapiserver.DelegationTarget) (*apiextensionsapiserver.CustomResourceDefinitions, error) {
	apiextensionsServer, err := apiextensionsConfig.Complete().New(delegateAPIServer)
	if err != nil {
		return nil, err
	}

	return apiextensionsServer, nil
}
```



#### CreateKubeAPIServer

```go
func CreateKubeAPIServer(kubeAPIServerConfig *master.Config, delegateAPIServer genericapiserver.DelegationTarget, sharedInformers informers.SharedInformerFactory, versionedInformers clientgoinformers.SharedInformerFactory) (*master.Master, error) {
	kubeAPIServer, err := kubeAPIServerConfig.Complete(versionedInformers).New(delegateAPIServer)
	if err != nil {
		return nil, err
	}
	kubeAPIServer.GenericAPIServer.AddPostStartHook("start-kube-apiserver-informers", func(context genericapiserver.PostStartHookContext) error {
		sharedInformers.Start(context.StopCh)
		return nil
	})

	return kubeAPIServer, nil
}
```







#### CreateAggregatorServer


```c
// pkg/controlplane/apiserver/aggregator.go
func createAggregatorServer(aggregatorConfig *aggregatorapiserver.Config, delegateAPIServer genericapiserver.DelegationTarget, apiExtensionInformers apiextensionsinformers.SharedInformerFactory) (*aggregatorapiserver.APIAggregator, error) {
	aggregatorServer, err := aggregatorConfig.Complete().NewWithDelegate(delegateAPIServer)
	if err != nil {
		return nil, err
	}

	// create controllers for auto-registration
	apiRegistrationClient, err := apiregistrationclient.NewForConfig(aggregatorConfig.GenericConfig.LoopbackClientConfig)
	if err != nil {
		return nil, err
	}
	autoRegistrationController := autoregister.NewAutoRegisterController(aggregatorServer.APIRegistrationInformers.Apiregistration().InternalVersion().APIServices(), apiRegistrationClient)
	apiServices := apiServicesToRegister(delegateAPIServer, autoRegistrationController)
	crdRegistrationController := crdregistration.NewAutoRegistrationController(
		apiExtensionInformers.Apiextensions().InternalVersion().CustomResourceDefinitions(),
		autoRegistrationController)

	aggregatorServer.GenericAPIServer.AddPostStartHook("kube-apiserver-autoregistration", func(context genericapiserver.PostStartHookContext) error {
		go crdRegistrationController.Run(5, context.StopCh)
		go func() {
			// let the CRD controller process the initial set of CRDs before starting the autoregistration controller.
			// this prevents the autoregistration controller's initial sync from deleting APIServices for CRDs that still exist.
			crdRegistrationController.WaitForInitialSync()
			autoRegistrationController.Run(5, context.StopCh)
		}()
		return nil
	})

	aggregatorServer.GenericAPIServer.AddHealthzChecks(
		makeAPIServiceAvailableHealthzCheck(
			"autoregister-completion",
			apiServices,
			aggregatorServer.APIRegistrationInformers.Apiregistration().InternalVersion().APIServices(),
		),
	)

	return aggregatorServer, nil
}
```









```c

```




## Write Path

一个 `POST /api/v1/namespaces/default/pods` 从进来到落盘，要穿过两道结构：外层是上文的三层 delegation，内层是 GenericAPIServer 的 filter chain 加上 handler 到存储的路径。

### filter chain Order

`DefaultBuildHandlerChain` 位于 `staging/src/k8s.io/apiserver/pkg/server/config.go:1036`。它的写法是**自内向外**层层包裹，因此实际执行顺序与代码阅读顺序相反——从最后一个 return 往回推，才是请求真正流过的次序：

| 执行序 | Filter | 源码行 | 要点 |
|---|---|---|---|
| 1 | `WithAuditInit` | `:1116` | 最外层，保证连 panic 的请求也能留下审计记录 |
| 2 | `WithPanicRecovery` | `:1115` | 必须在 RequestInfo 之外，才能拿到 ns/resource 去写日志 |
| 3 | `WithRequestInfo` | `:1112` | 解析出 verb / namespace / resource，后续一切依赖它 |
| 4 | `WithRequestReceivedTimestamp` | `:1113` | 记录收到时刻，后面的 deadline 以它为起点算 |
| 5 | `WithRequestDeadline` / `WithTimeoutForNonLongRunningRequests` | `:1090` `:1088` | 长跑请求（watch / exec）豁免超时，非长跑超时返回 504 |
| 6 | `WithAuthentication` | `:1077` | 失败走 `failedHandler` 返回 401，不再往下走 |
| 7 | `WithAudit` | `:1064` | 请求级三段审计（Request / Response / Panic） |
| 8 | `WithConstrainedImpersonation` | `:1056` | 1.36 起默认开启，否则回落到旧 `WithImpersonation` |
| 9 | `WithPriorityAndFairness` | `:1048` | 默认 APF；`FlowControl == nil` 时降级为 `WithMaxInFlightLimit` |
| 10 | `WithAuthorization` | `:1040` | **最内层**，RBAC / Node / Webhook 联合判定 |

> [!TIP]
> **APF 排在 Authorization 之前**。给请求分流只需要 user（来自认证）和 RequestInfo（来自上一层），完全不需要鉴权结果，所以先排队再鉴权。

认证器本身是一条 union 链，按序尝试 requestheader、x509、token file、ServiceAccount、Bootstrap Token、JWT/OIDC、webhook。

### From handler to etcd

路由装在 `endpoints/installer.go`，落入 `handlers.CreateResource` 之后：

```
CreateResource      解码 → 清系统字段 → managedFields 合并
  mutating admission   按 AllOrderedPlugins 顺序修改对象
    Store.Create       FillObjectMetaSystemFields（UID 在本地生成）
      BeforeCreate     PrepareForCreate → Validate → validating admission
        DryRunnableStorage → CacheDelegator → etcd3 store
```

注意两个容易含糊的点：

1. **UID 不由 etcd 决定**，而是 apiserver 本地 `uuid.NewUUID()` 生成后再写入对象；
2. **写请求完全绕过 watchCache**，`CacheDelegator.Create` 直接透传给底层 etcd3 store。watchCache 只服务于读和 watch。

最终落库是一次 etcd 事务：

```go
// staging/src/k8s.io/apiserver/pkg/storage/etcd3/store.go:317
txnResp, err := s.client.Kubernetes.OptimisticPut(ctx, preparedKey, newData, 0,
	kubernetes.PutOptions{LeaseID: lease})
...
err = s.decoder.Decode(data, out, txnResp.Revision)
```

创建时 `expectedRevision` 为 0，等价于 `Compare(ModRevision == 0)`，天然实现"key 不存在才写"，这就是 409 Conflict 的来源。

### The Origin of resourceVersion

这是很多人含糊的地方，直接给结论：**RV 就是 etcd 事务响应的 `Header.Revision`**，不是独立维护的版本计数器。链路是：

```
OptimisticPut → txnResp.Revision (= txnResp.Header.Revision)
  → decoder.Decode(data, out, revision)
    → versioner.UpdateObject → SetResourceVersion
```

写之前 `PrepareObjectForStorage` 会把 RV 和 SelfLink 清空，所以 RV 只由 etcd 决定，客户端永远带不进来。

更新路径走 `GuaranteedUpdate` + 同样的 Compare-And-Put，冲突后重试——**全程无锁**。

> [!NOTE]
> 删除走的是同一套 `GuaranteedUpdate` 与同一套 etcd 事务（`OptimisticDelete`，`staging/src/k8s.io/apiserver/pkg/storage/etcd3/store.go:434`），但语义完全不同：**一次 DELETE 通常不删任何东西**，只写 `metadata.deletionTimestamp`，真正的删除由 GC 与 kubelet 接力完成。这条反向链路见 [删除与级联](/docs/CS/Container/k8s/Deletion.md)。

### etcd Client Generation Upgrade

v1.36 依赖 etcd **v3.6.8**，写操作从手写 `clientv3.Txn` 改为 kubernetes-mode client 的 `OptimisticPut`：

```go
// vendor/go.etcd.io/etcd/client/v3/kubernetes/client.go:83
txn := k.KV.Txn(ctx).If(
	clientv3.Compare(clientv3.ModRevision(key), "=", expectedRevision),
).Then(clientv3.OpPut(key, string(value), clientv3.WithLease(opts.LeaseID)))
if opts.GetOnFailure {
	txn = txn.Else(clientv3.OpGet(key))
}
```

新增的 `GetOnFailure` 把"冲突时的当前值"随事务一并返回，**更新失败重试时省掉一轮 Get**。

### Read Path: Who Reads After Writing

写路径的尽头是 etcd，但**读路径大多不碰 etcd**。apiserver 为每个 group-resource 维护一个 `Cacher`（`staging/src/k8s.io/apiserver/pkg/storage/cacher/cacher.go:263`）：它先从 etcd 拉一次全量填进内存 btree 与环形缓冲，之后持续 watch；所有客户端的 List / Watch 都由这份内存结构服务。于是"N 个 informer"被收敛成"1 条到 etcd 的 watch"。

读请求进来时先过 `CacheDelegator` 的分流决策（`cacher/delegator/interface.go:40`）：`resourceVersionMatch` 与 `continue` 的组合决定这次请求走缓存还是透传 etcd。缓存层内部的滑动窗口、`410` / `504` / `429` 三种错误的分野、以及流式 list 的合成都收在单独的笔记里，见 [watch cache 读路径底座](/docs/CS/Container/k8s/WatchCache.md)。

### Responsibility Boundary: apiserver Does Not Issue Certificates

写链路的另一端有一件事 apiserver 刻意不做：**签发证书**。客户端的 CSR 由 apiserver 收下并落库，但"批准"要走一次 `SubjectAccessReview`，真正签名的是 kube-controller-manager 里持有 CA 私钥的 `CertificateAuthority.Sign`；apiserver 只负责校验请求方有没有资格。同理 **ServiceAccount token 的签发与校验都用 apiserver 自己的密钥对，与集群 CA 完全无关**——`--client-ca-file` 与 `--service-account-key-file` 是两套互不背书的信任根。这条边界见 [身份与证书](/docs/CS/Container/k8s/Identity.md)。

## Links

- [K8s 架构与四条主链路](/docs/CS/Container/k8s/Architecture.md)
- [watch cache 读路径底座](/docs/CS/Container/k8s/WatchCache.md)
- [访问控制](/docs/CS/Container/k8s/acl.md)
- [etcd 存储](/docs/CS/Container/k8s/etcd.md)
- [client-go](/docs/CS/Container/k8s/client-go.md)
- [容器知识地图](/docs/CS/Container/README.md)

## References

1. [kube-apiserver v1.36.4 source](https://github.com/kubernetes/kubernetes/tree/v1.36.4/cmd/kube-apiserver)
2. [Kubernetes API Concepts](https://kubernetes.io/docs/reference/using-api/api-concepts/)
3. [API Access Control](https://kubernetes.io/docs/concepts/security/controlling-access/)
4. [Dynamic Admission Control](https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/)
