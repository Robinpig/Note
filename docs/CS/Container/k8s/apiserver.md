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




## Config Construction

`CreateServerChain` 只展示了"用" Config 的那一瞬间，而 Config 本身的构建链更长。完整链路从 `app.NewConfig(opts)` 开始（`cmd/kube-apiserver/app/config.go:74`）：

```
NewConfig(opts CompletedOptions) *Config
│
├── controlplaneapiserver.BuildGenericConfig(opts, schemes, resourceConfig, openAPIDefinitions, informerName)
│   ├── genericConfig = genericapiserver.NewConfig(codecs)
│   ├── opts.GenericServerRunOptions.ApplyTo(genericConfig)      // FeatureGate, EffectiveVersion, RequestTimeout...
│   ├── opts.SecureServing.ApplyToConfig(genericConfig)          // TLS, ListenAddr
│   ├── versionedInformers = clientgoinformers.NewSharedInformerFactoryWithOptions(...)
│   ├── opts.Features.ApplyTo(...)                               // APF, CBOR, CoordinatedLeaderElection...
│   ├── opts.APIEnablement.ApplyTo(...)                         // MergedResourceConfig
│   ├── opts.EgressSelector.ApplyTo(...)                        // 出口流量代理
│   ├── storageFactoryConfig.New()                              // DefaultStorageFactory（etcd3 + 加密转换）
│   ├── opts.Etcd.ApplyWithStorageFactoryTo(...)                 // etcd 连接、Transport
│   ├── opts.Authentication.ApplyTo(...)                         // 📌 JWT/OIDC/X509/ServiceAccount/Webhook
│   ├── BuildAuthorizer(...)                                     // 📌 RBAC/Node/Webhook 联合鉴权
│   └── opts.Audit.ApplyTo(...)                                  // 审计后端 + 策略
│
├── CreateKubeAPIServerConfig(opts, genericConfig, versionedInformers, storageFactory)
│   ├── capabilities.Setup()                                     // Privileged, MaxConnectionBytesPerSec
│   ├── CreateProxyTransport()                                   // 连接 kubelet 的 Transport
│   ├── CreatePeerEndpointLeaseReconciler() + BuildPeerProxy()   // 跨 apiserver 版本互操作
│   └── controlplaneapiserver.CreateConfig(...)
│       ├── NewStorageFactoryConfigEffectiveVersion().Complete().New()   // 每资源 etcd prefix / 编码策略
│       ├── opts.Admission.ApplyTo(...)                          // 📌 Admission Chain 组装（见下）
│       └── ServiceAccountIssuer / ClusterAuthenticationInfo
│
├── CreateAPIExtensionsConfig(...)    // 复用 genericConfig + 注入 apiextensions specific informers
│
└── CreateAggregatorConfig(...)       // 复用 genericConfig + 注入 apiregistration informers
```

这套设计的关键是 **三份 Config 共享同一个 `genericapiserver.Config`**。StorageFactory、Serializer、LoopbackClientConfig、Authentication/Authorization 全部只构建一次，然后三份子 Config 各自 `.Complete().New()` 出独立的 `GenericAPIServer` 实例。

### Admission Assembly

Admission chain 的组装发生在 `controlplaneapiserver.CreateConfig` → `opts.Admission.ApplyTo()`（`pkg/admission/config.go`）。内部流程：

```
1. plugins.RegisterAll(plugins.NewPluginInitializer(...)) — 注册 30+ 内置插件到 registry
2. 从 kubeadm 风格配置或命令行 --admission-control-list 确定启用集
3. 对每个启用插件：
   ├── 构造 pluginInitializer 参数（Informers, LoopbackClientConfig, ServiceResolver）
   └── plugin.New(initializers...)  // 传入运行时依赖
4. admission.NewChainHandler(plugins...) → chainAdmissionHandler
```

`chainAdmissionHandler`（`staging/src/k8s.io/apiserver/pkg/admission/chain.go:23`）是最核心的类型：它实现 `admission.Interface`，内部是 `[]Interface`，对 `Admit()` 和 `Validate()` 分别遍历链，遇到首个 error 即返回。Webhook plugin 是其中一环——它内部再调 `WebhookClient.Dispatch()` 去打外部 HTTP endpoint。

### GenericAPIServer Internals

`completedConfig.New(name, delegationTarget)`（`staging/src/k8s.io/apiserver/pkg/server/config.go:787`）是三个 GenericAPIServer 的工厂：

```go
apiServerHandler := NewAPIServerHandler(name, c.Serializer, handlerChainBuilder, delegationTarget.UnprotectedHandler())

s := &GenericAPIServer{
    Handler:            apiServerHandler,
    delegationTarget:   delegationTarget,
    admissionControl:   c.AdmissionControl,
    Authorizer:         c.Authorization.Authorizer,
    LoopbackClientConfig: c.LoopbackClientConfig,
    // ... healthz/openapi/storageVersion/lifecycleSignals/postStartHooks/preShutdownHooks ...
}
```

`handlerChainBuilder` 是一个闭包，把 `DefaultBuildHandlerChain` 绑定到当前 Config 上——所以每个 server 实例都得到**自己的一套完整 filter chain**。

#### APIServerHandler 结构

`APIServerHandler`（`staging/src/k8s.io/apiserver/pkg/server/handler.go:42`）是请求真正进来的地方：

```
APIServerHandler.ServeHTTP(w, r)
  └── FullHandlerChain.ServeHTTP(w, r)   // handlerChainBuilder(director) 产出的完整链
        └── Director.ServeHTTP(w, r)     // 路由分发器
              ├── GoRestfulContainer.Dispatch(w, r)   // 已注册的 /api, /apis/apps/v1 等 REST 路由
              └── NonGoRestfulMux.ServeHTTP(w, r)    // 未匹配 → 可能是 delegation 下一跳 or 404
```

`Director` 的核心逻辑：遍历 `GoRestfulContainer` 的已注册 WebService，按路径前缀匹配（`strings.HasPrefix(path, ws.RootPath())`）。匹配到 → gorestful 处理；**没匹配到的 → NonGoRestfulMux**——这是 delegation 能工作的关键：上层 server 注册了 `/apis` 但没注册 `/apis/mycompany.com/v1`，所以请求自然"漏"到 NonGoRestfulMux，那里挂着下层 delegation target 的 handler。

> [!TIP]
> 代码注释里写了 **"Hopefully no API consumers will ever have to deal with this level of detail. I think we should consider completely removing gorestful."** —— gorestful 因为 openapi-swagger 生成的历史原因还在用，社区长期想换成纯 net/http 路由。

#### API Installation

API 安装分两层：Server 层的 `InstallAPIs`（Kube-specific，`pkg/controlplane/apiserver/apis.go:88`）和 GenericAPIServer 层的 `InstallAPIGroups` / `InstallLegacyAPIGroup`。

```
Server.InstallAPIs(restStorageProviders...)
│
├── GenericStorageProviders(...)          // 返回 StorageProvider 列表：core, authentication,
│                                        // authorization, certificates, coordination, rbac,
│                                        // flowcontrol, admissionregistration, events, ...
│
└── 遍历 providers:
    ├── NewRESTStorage(resourceConfig, restOptionsGetter) → APIGroupInfo
    │     每个 Provider.GroupName() + Scheme + VersionedResourcesStorageMap{version: {resource: rest.Storage}}
    │
    ├── 空 group ("") → GenericAPIServer.InstallLegacyAPIGroup("/api", apiGroupInfo)
    │     // core/v1 Pod/Service/Node 走这里
    │
    └── 非空 group → 收集到 nonLegacy 列表，最后 InstallAPIGroups(nonLegacy...)
          │
          └── GenericAPIServer.InstallAPIGroups → InstallAPIGroup (逐个 GroupVersion)
                │
                └── newAPIGroupVersion → APIInstaller.Install()
                      │
                      └── GoRestfulContainer.Add(WebService{
                            /apis/apps/v1/deployments → GET → handlers.GetResource
                            /apis/apps/v1/deployments → POST → handlers.CreateResource
                            /apis/apps/v1/deployments/{name} → PUT → handlers.UpdateResource
                            /apis/apps/v1/deployments/{name} → DELETE → handlers.DeleteResource
                            /apis/apps/v1/deployments/{name} → WATCH → handlers.WatchResource
                            ...
                        })
```

RESTStorageProvider 接口极简——只有 `GroupName()` 和 `NewRESTStorage()`。每个内置组（core、apps、batch...）都有对应的 `rest` 子包提供实现，内部用 `genericregistry.Store` + 特定 Strategy 组装。

### PostStartHooks

GenericAPIServer 的 `Run` 不会阻塞一切启动——`PrepareRun()` 装完 OpenAPI/healthz/readyz/statusz 后，`RunWithContext` 会启一个 goroutine 跑 `PostStartHook`（`server.PrepareRun → prepared.Run → 启动 hookContext.Done() 关闭时执行`）。`pkg/controlplane/apiserver/server.go:93` 中 Kube Server `New()` 注册了 8 个 hook：

| Hook 名 | 何时跑 | 作用 |
|---|---|---|
| `start-system-namespaces-controller` | 可选（`--system-namespaces`） | 创建 kube-system 等系统 namespace |
| `start-kube-apiserver-coordinated-leader-election-controller` | feature gate | 新版协调式 leader election，用 Lease/LeaseCandidate |
| `peer-endpoint-reconciler-controller` | UnknownVersionInteroperabilityProxy | 跨 apiserver 版本互操作的 endpoint lease |
| `mixed-version-proxy-handler` | 同上 | 缓存同步完成信号 |
| `local-discovery-cache-sync` | 同上 | 本地 peer 发现循环 |
| `peer-discovery-workers` | 同上 | peer 发现 + active GV tracker + refilter |
| `start-cluster-authentication-info-controller` | 必选 | ClientCA / RequestHeaderCA 变更时刷新 |
| `start-kube-apiserver-identity-lease-controller` | APIServerIdentity feature | 身份 lease（标记此 apiserver 正在运行） |
| `storage-readiness` | WatchCacheInit feature | watch cache ready hook |
| `start-legacy-token-tracking-controller` | 必选 | 跟踪 legacy token 使用 |

这些 hook **在 HTTP server 开始接请求之后才执行**。`MuxAndDiscoveryComplete` signal 就是为了让在 hook 期间进来的请求返回 503——等待 informers 和 hooks 初始化完才能接正常流量。

## Write Path

一个 `POST /api/v1/namespaces/default/pods` 从进来到落盘，要穿过两道结构：外层是上文的三层 delegation，内层是 GenericAPIServer 的 filter chain 加上 handler 到存储的路径。

### Complete Handler Chain

`DefaultBuildHandlerChain` 位于 `staging/src/k8s.io/apiserver/pkg/server/config.go:1036`。它的写法是**自内向外**层层包裹（`handler = filter(handler)` 然后 return），因此实际执行顺序从 return 处反向推。以下表格按**请求进入时先遇到的 filter** 排序（即最外层 → 最内层 → 最终到达 Director）：

| 执行序 | Filter | 源码行 | 要点 |
|---|---|---|---|
| 1 | `WithAuditInit` | `:1114` | 最外层，向 context 注入 audit sink，保证连 panic 的请求也能留下审计记录 |
| 2 | `WithPanicRecovery` | `:1113` | 捕获 handler 内部 panic，写错误响应 |
| 3 | `WithMuxAndDiscoveryComplete` | `:1112` | 等待所有 delegation server 的路由注册信号，返回 503 |
| 4 | `WithRequestReceivedTimestamp` | `:1111` | 记录收到时刻，后面的 deadline 以它为起点算 |
| 5 | `WithRequestInfo` | `:1110` | 🔑 核心 filter：从 URL path 解析出 verb / namespace / resource / subresource / GVR → 写入 context。后续一切 filter 和 handler 都依赖它 |
| 6 | `WithLatencyTrackers` | `:1103` | 延迟追踪器，记录各段耗时 |
| 7 | `WithHTTPLogging` | `:1102` | HTTP 访问日志 |
| 8 | `WithRetryAfter` | `:1100` | 优雅关闭期间给新请求返回 `Retry-After` header |
| 9 | `WithHSTS` | `:1098` | 加 `Strict-Transport-Security` header |
| 10 | `WithCacheControl` | `:1097` | 加 `Cache-Control: no-store` |
| 11 | `WithProbabilisticGoaway` | `:1094` | 概率性 HTTP2 GOAWAY，驱动客户端重连做负载均衡 |
| 12 | `WithWatchTerminationDuringShutdown` | `:1091` | 关闭时优雅终止 watch 请求 |
| 13 | `WithWaitGroup` | `:1090` | 用 WaitGroup 追踪 in-flight 请求，优雅关闭时等待 drain |
| 14 | `WithRequestDeadline` | `:1088` | 非长跑请求的 hard deadline（默认 `--request-timeout`），超时返回 504 |
| 15 | `WithTimeoutForNonLongRunningRequests` | `:1086` | 把非长跑请求丢到单独 goroutine，主 goroutine 守超时（长跑请求 watch/exec/log/portforward 豁免） |
| 16 | `WithWarningRecorder` | `:1082` | 让后续 handler 可以往 response 写 Warning header |
| 17 | `WithCORS` | `:1078` | CORS 预检处理 |
| 18 | `WithAuthentication` | `:1075` | 🔐 认证，失败走 `failedHandler` 返回 401（不再往下走） |
| 19 | `WithTracing` | `:1072` | OpenTelemetry tracing（放在认证之后，因为需要 authenticated user 信息做采样决策） |
| 20 | `WithAudit` | `:1064` | 请求级三段审计（Request / Response / Panic），有独立的 audit sink |
| 21 | `WithConstrainedImpersonation` | `:1056` | 用户伪装，默认开启（否则回落 `WithImpersonation`） |
| 22 | `WithPriorityAndFairness` | `:1048` | ⚖️ APF：按 FlowSchema + PriorityLevel 分类排队；没有 APF 时降级为 `WithMaxInFlightLimit` |
| 23 | `WithAuthorization` | `:1040` | 🔑 鉴权，RBAC / Node / Webhook 联合判定，**链的最内层** |
| → | `Director` | `handler.go:121` | 根据 path 前缀分发：匹配 gorestful registered webservice 则走 GoRestfulContainer，否则走 NonGoRestfulMux（委托链） |

> [!TIP]
> **APF 排在 Authorization 之前**。给请求分流只需要 user（来自认证）和 RequestInfo（来自第 5 步），完全不需要鉴权结果，所以先排队再鉴权。这意味着 APF 的排队是所有请求的入口级保护，不依赖 RBAC。

**认证器本身是一条 union 链**（`pkg/authentication/authenticatorfactory/delegating.go`），按序尝试 requestheader → x509 client cert → static token file → ServiceAccount JWT → Bootstrap Token → OIDC webhook token。第一个成功认证的就返回，不再往下尝试。

delegation chain 中的**每个 server 都有自己的完整 handler chain**。一个请求最多穿过 3 次（aggregator → kube → apiextensions），每层都独立跑认证、鉴权、APF——这是灵活性（各层可以独立配置认证方式）换来的代价。

### Create Handler Deep Dive

路由装在 `endpoints/installer.go`，落入 `handlers.CreateResource` 之后（`endpoints/handlers/create.go`）。以 v1.37.2 源码为准，调用链比上面那段简化图要密：

```
createHandler(r rest.NamedCreater, scope *RequestScope, admit admission.Interface)
  │
  ├── Namer.Name(req)                  // 从 path /apis/v1/namespaces/{ns}/{resource}/{name} 提取 namespace + name
  ├── NegotiateOutputMediaType / NegotiateInputSerializer
  ├── limitedReadBodyWithRecordMetric  // 读 body（带 MaxRequestBodyBytes 限制）
  ├── Decode(body → scope.HubGroupVersion)   // JSON/YAML/Protobuf → runtime.Object；HubGroupVersion 转换
  │     strict decoding 错误在 FieldValidationWarn 下退化为 warning
  ├── WipeObjectMetaSystemFields       // 清空 UID/ResourceVersion/CreationTimestamp 等系统字段
  ├── EnsureObjectNamespaceMatchesRequestNamespace
  │
  ├── admissionAttributes := admission.NewAttributesRecord(obj, nil, ..., admission.Create, ...)
  │
  └── finisher.FinishRequest(ctx, func() {   // 外层包装：统一错误处理 + DryRun 支持
        ├── FieldManager.UpdateNoErrors(liveObj, obj, managerOrUserAgent(options.FieldManager, req.UserAgent()))
        │     // 🔑 Server-Side Apply 的核心：把请求字段合并进 liveObj，更新 managedFields
        │
        ├── fieldmanager.NewManagedFieldsValidatingAdmissionController(admit)
        │     // 再包一层 admission，专门管 managedFields 的合法性
        │
        ├── mutatingAdmission.Admit(ctx, admissionAttributes, scope)
        │     // 按 AllOrderedPlugins 顺序修改对象（字段默认、自动注入、Webhook 回调）
        │
        ├── dedupOwnerReferencesAndAddWarning  // Webhook 改完对象后再去重 ownerReferences
        │
        └── r.Create(ctx, name, obj, rest.AdmissionToValidateObjectFunc(admit, admissionAttributes, scope), options)
              │
              └── genericregistry.Store.Create(ctx, key, obj, createValidation, options)
                    ├── CreateStrategy.PrepareForCreate(ctx, obj)    // 业务层默认值/预处理（Pod 填充 HostIP 等）
                    ├── obj = strategy.Validate(ctx, obj)            // 业务层校验
                    ├── CreateStrategy.Warnings(ctx, obj)            // 1.37 新增：校验时产生 warning 写入 response header
                    ├── admission.Validate(ctx, admissionAttr)       // ✅ validating admission（链中插件遍历，首个 error 返回）
                    ├── DryRun 判断 → 直接返回 obj 不落库
                    ├── storage.Create(ctx, key, obj, out, ttl)       // CacheDelegator → etcd3 Store
                    ├── AfterCreate(ctx, obj, ...)                    // 可选 hook（BeginCreate/AfterCreate）
                    └── return obj 或 409 Conflict
    })
```

注意三个关键设计点：

1. **mutating admission 发生在 FieldManager 之后**——这样 Webhook 看到的对象已经是 SSA 合并后的版本，Webhook 改完再做一遍 ownerReferences 去重；
2. **Validate 不是单一调用**——Create handler 自己调 `CreateStrategy.Validate()` + admission 链里的 validating plugin 遍历，两层独立校验；
3. **UID/ResourceVersion 由 apiserver 本地生成**，写入对象后再交给 etcd 存储。

### genericregistry.Store 结构

所有内置资源的 REST 实现最终都指向 `staging/src/k8s.io/apiserver/pkg/registry/generic/registry/store.go` 的 `Store` 类型。它是一个嵌入结构：

```go
type Store struct {
    RESTCreateStrategy  // 业务层策略：PrepareForCreate / Validate / Canonicalize
    RESTUpdateStrategy  // PrepareForUpdate / ValidateUpdate / Validate
    RESTDeleteStrategy  // ValidateDelete / PrepareForDelete / DeleteReturnsFinalState

    NewFunc            // 创建空对象
    NewListFunc        // 创建空 list
    CreateStrategy     // 同时持有 create/update/delete 三份 Strategy

    Storage            // 底层 storage.Storage（实际是 CacheDelegator 装饰过的 etcd3 Store）
    DefaultQualifiedResource schema.GroupResource
}
```

`Store.Create` 本身不关心 etcd 细节——它只负责调 Strategy 做业务处理、调 admission 做准入、调 `storage.Create` 做实际写入。`storage.Storage` 是接口，实现链是：

```
CacheDelegator (staging/.../storage/cacher/delegator.go)
  └── Cacher (staging/.../storage/cacher/cacher.go)        // 内存缓存 + watch buffer
        └── etcd3.Store (staging/.../storage/etcd3/store.go)  // 实际 etcd 客户端
```

写请求**完全绕过 Cacher**——`CacheDelegator.Create` 直接透传给底层 `etcd3.Store.Create`。Cacher 只服务于读和 watch。

### etcd 事务与 Conflict

最终落库是一次 etcd Compare-And-Swap 事务：

```go
// staging/src/k8s.io/apiserver/pkg/storage/etcd3/store.go:317
txnResp, err := s.client.Kubernetes.OptimisticPut(ctx, preparedKey, newData, 0,
    kubernetes.PutOptions{LeaseID: lease})
...
err = s.decoder.Decode(data, out, txnResp.Revision)
```

创建时 `expectedRevision` 为 0，等价于 `Compare(ModRevision == 0)`，天然实现"key 不存在才写"，这就是 409 Conflict 的来源。

更新路径走 `GuaranteedUpdate` + 同样的 Compare-And-Put，冲突后重试——**全程无锁**。每次重试会重新 Get 当前值、重新做 conversion/validation/strategy/prepare。

> [!NOTE]
> 删除走的是同一套 `GuaranteedUpdate` 与同一套 etcd 事务（`OptimisticDelete`，`staging/src/k8s.io/apiserver/pkg/storage/etcd3/store.go:434`），但语义完全不同：**一次 DELETE 通常不删任何东西**，只写 `metadata.deletionTimestamp`，真正的删除由 GC 与 kubelet 接力完成。这条反向链路见 [删除与级联](/docs/CS/Container/k8s/Deletion.md)。

### The Origin of resourceVersion

这是很多人含糊的地方，直接给结论：**RV 就是 etcd 事务响应的 `Header.Revision`**，不是独立维护的版本计数器。链路是：

```
OptimisticPut → txnResp.Revision (= txnResp.Header.Revision)
  → decoder.Decode(data, out, revision)
    → versioner.UpdateObject → SetResourceVersion
```

写之前 `PrepareObjectForStorage` 会把 RV 和 SelfLink 清空，所以 RV 只由 etcd 决定，客户端永远带不进来。

### etcd Client Generation Upgrade

v1.37.2 依赖 etcd **v3.6.8**，写操作从手写 `clientv3.Txn` 改为 kubernetes-mode client 的 `OptimisticPut`：

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

1. [kube-apiserver v1.37.2 source (本地仓库)](https://github.com/kubernetes/kubernetes/tree/v1.37.2/cmd/kube-apiserver)
2. [apiserver ARCHITECTURE.md (staging)](https://github.com/kubernetes/kubernetes/blob/v1.37.2/staging/src/k8s.io/apiserver/ARCHITECTURE.md)
3. [Kubernetes API Concepts](https://kubernetes.io/docs/reference/using-api/api-concepts/)
4. [API Access Control](https://kubernetes.io/docs/concepts/security/controlling-access/)
5. [Dynamic Admission Control](https://kubernetes.io/docs/reference/access-authn-authz/extensible-admission-controllers/)
