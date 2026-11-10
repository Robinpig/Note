## Introduction

这一页只讲**链路**：一条配置从进控制器到变成 xDS 资源，中间经过哪些函数、在哪一步变成什么对象。模块与目录清单在 [Source Map](/docs/CS/Framework/Higress/Source_Map.md)，服务来源那一层的内部实现在 [Service Registry Internals](/docs/CS/Framework/Higress/Service_Registry_Internals.md)。

基准是 higress 主仓 v2.2.5（HEAD `4deae1dd`）与 standalone aio-v2.2.5（`36882509`），取自本机的两份 v2.2.5 源码树。承载机制的关键源码直接抄在正文里，`路径:行号` 只用于回查，代码块里的 `// ...` 表示节选省略。有三条事实贯穿全篇：Higress 对 pilot 是只读的 pull 模型，配置产物不缓存、每次 `List` 全量重算；事件只作脏标记，Higress 侧没有生效的时间去抖；Higress 与 pilot fork 在同一进程里共享指针，并非两个服务。

跨文件的符号级关系（接口实现矩阵、十条 `ConfigUpdate` 入口、九个 EnvoyFilter 构造点）放在 [Call Graph Internals](/docs/CS/Framework/Higress/Call_Graph_Internals.md)，本页不重述。

## Process Assembly

`cmd/higress/main.go:28` 执行 `cmd.GetRootCommand().Execute()`，根命令（`pkg/cmd/root.go:21-31`）**只有 serve 与 version 两个子命令**——整个网关控制器就是一个 `higress serve`。`pkg/cmd/server.go:73` 构造、`:78` 启动，构造期与启动期是分开的。

注册顺序就是这份切片，循环里没有任何并发或容错（`bootstrap/server.go:170-184`）：

```go
	s.environment.Watcher = meshwatcher.NewTestWatcher(&v1alpha1.MeshConfig{})
	s.environment.Init()
	initFuncList := []func() error{
		s.initKubeClient,
		s.initXdsServer,
		s.initHttpServer,
		s.initConfigController,
		s.initRegistryEventHandlers,
		s.initAuthenticators,
		s.initAutomaticHttps,
	}

	for _, f := range initFuncList {
		if err := f(); err != nil {
			return nil, err
		}
	}
```

1. `initKubeClient`（`:454-472`，`:459` 取 rest config、`:466` 建 client、`:470` 开 CRD watcher）
2. `initXdsServer`（`:383-408`，见 fork 边界一节）
3. `initHttpServer`（`:474-485`）
4. `initConfigController`（`:221-263`）
5. `initRegistryEventHandlers`（`:199-219`）
6. `initAuthenticators`（`:422-432`，`features.XDSAuth` 为真才挂认证器）
7. `initAutomaticHttps`（`:434-452`）

`higresskube.EnableCrdWatcher` 与 `PodNamespace`（`:222`，系统命名空间来自环境变量而非编译期常量）都在这条链上。三个 component 的**注册顺序与 init 顺序不一致**：`"xds-server"`（`:402`）→ `"config-controller"`（`:258`）→ `"kube-client"`（`:186`），三者都等到 `Start` 里的 `:306` `s.server.Start(stop)` 才真正跑起来。

启动后有两道**串行就绪门**（`:548-568`）：先 `s.configController.HasSynced()`，再比对 `xdsServer.InboundUpdates` 与 `CommittedUpdates`（`:561-562`、`:571-578`）；任一不过则 `Start` 返回 `failed to sync cache`（`:310`）。往下钻一层，`IngressTranslation.HasSynced()`（`pkg/ingress/translation/translation.go:75-88`）= ingress 与 kingress 两侧之和，而 `IngressConfig.HasSynced()`（`pkg/ingress/config/ingress_config.go:2100-2127`）逐个检查 remoteIngress / remoteGateway / mcpbridge / wasmPlugin / http2rpc 五个控制器与 configmapMgr——**不含 registry watcher**，因为它是**懒创建**的：`RegistryReconciler` 只在第一次 McpBridge 事件时才被 new 出来（`ingress_config.go:1428-1488`）。这解释了一个运维现象：`/registry/watcherStatus` 在冷启动时必然 404。

监听面与限速的默认值（`pkg/cmd/server.go:89-138`）：

| 项 | 值 | 出处 |
| --- | --- | --- |
| xDS gRPC | `:15051` | server.go:94 |
| HTTP（debug + ready + watcherStatus） | `:8888` | server.go:93 |
| cert HTTP | `:8889` | server.go |
| K8s 客户端限速 | QPS **80.0** / Burst **160** | server.go:126-130 |
| 队列重试上限 | **5**（硬编码，非环境变量） | `ingressv1/controller.go:118` |
| informer 周期 resync | **0，即关闭** | `pkg/kube/client.go:73` |
| CRD 版本检查 | 30s 超时，**只告警不阻断启动** | `bootstrap/server.go:272`、`:285-301` |
| HTTP server | IdleTimeout 90s / ReadTimeout 30s | `bootstrap/server.go:478-479` |
| 优雅停机 | GracefulStop 后 2s 强停 | `bootstrap/server.go:367-373` |

两个 flag 值得单独记：`--gatewaySelectorKey=higress` / `--gatewaySelectorValue=higress-system-higress-gateway`（`:105-107`）就是最终写进 `Selector.MatchLabels` 的那对值（`ingress_config.go:1201-1205`）；`--enableAutomaticHttps` 默认 **false**（`:136`），而 cert 对象是**无条件创建**的，只是不 `Run`（`bootstrap/server.go:440`、`:447-450`）。

## Event Path

以 Ingress 为例（`pkg/ingress/kube/ingressv1/controller.go`）：`:119` 把 informer 的 EventHandler 直接接到 `controllers.ObjectHandler(c.queue.AddObject)`，队列是 pilot 的 `controllers.NewQueue("ingressv1", WithReconciler(c.onEvent), WithMaxAttempts(5))`（`:116-118`），key 就是 `namespace/name`，**没有自定义拼接**。该队列底层是 **`workqueue.NewRateLimitingQueue`**（`pkg/kube/controllers/queue.go:92-94`）：Higress 只传了 `WithMaxAttempts(5)` 而**没有传 `WithRateLimiter`**，因此走 pilot 默认的 `workqueue.DefaultControllerRateLimiter()`（per-item 指数退避 + 令牌桶）——⇒ **队列的退避与速率是 pilot 侧默认值，不是 Higress 自己配的**，`WithRateLimiter`（`:51-55`）是留给自定义的口子。Service / IngressClass 的 informer 在同一函数建立（`:95-102`）；CRD 侧走通用控制器 `pkg/ingress/kube/controller/model.go:67-70`，配置相同，只是内部 key 多带一个 ClusterId（`model.go:101-107`）。

真正的"合并"只有一处，且**不是时间窗**：`shouldProcessIngressUpdate`（`ingressv1/controller.go:1342-1387`）在对象已见过时用 `reflect.DeepEqual` 比较 **Annotations / Labels / Spec** 三项（`:1357-1372`，注释逐字为 "We only care about annotations, labels and spec."），三者全等就把事件丢掉。推论：**只改 status 或其它字段的更新不会触发下发**；而 `pkg/kube/client.go:73` 的 `resyncInterval = 0` 意味着**不存在周期性全量重推**——漏掉的事件不会靠 resync 自愈。所谓"合并"其实是这段比较（`ingressv1/controller.go:1353-1375`），既没有时间窗，也没有攒批：

```go
		// We only care about annotations, labels and spec.
		if exist {
			if !reflect.DeepEqual(preConfig.Annotations, ing.Annotations) {
				IngressLog.Debugf("Annotations of ingress %s changed, should process.", namespacedName)
				return true, nil
			}
			if !reflect.DeepEqual(preConfig.Labels, ing.Labels) {
				IngressLog.Debugf("Labels of ingress %s changed, should process.", namespacedName)
				return true, nil
			}
			if !reflect.DeepEqual(preConfig.Spec, ing.Spec) {
				IngressLog.Debugf("Spec of ingress %s changed, should process.", namespacedName)
				return true, nil
			}

			return false, nil
		}
```

状态回写是另一条独立链路（与配置下发无关）：`ingressv1/status.go` 的 `statusSyncer` 以 `common.DefaultStatusUpdateInterval`（`pkg/ingress/kube/common/model.go:66` = **10s**）为周期 ticker 轮询，回写前用 `reflect.DeepEqual` 比较 LB IP 去重（`:114`），不是事件驱动的即时写。

一次 Ingress 变更产生的是 **4 个合成 Meta**：`<name>-destinationrule` / `-virtualservice` / `-envoyfilter` / `-gateway`（`:191-212`），按 DR → VS → EnvoyFilter → Gateway 顺序向四组 handler 广播（`:219-233`），每个都带 `Labels{AlwaysPushLabel: "true"}`（注释："Set this label so that we do not compare configs and just push."）。所有下游 handler 汇流到 `bootstrap/server.go:199-216` 的 `configHandler`：构造 `PushRequest{Full: true, ConfigsUpdated: {...}, Reason: model.ConfigUpdate}` 后调 `s.xdsServer.ConfigUpdate`（`:212`）。合成名是全链路一致的约定，唯一例外是 Http2Rpc 用 CR 真名（`ingress_config.go:1528`）。四个 Meta 与四组广播是同一段代码（`ingressv1/controller.go:190-233`），`AlwaysPushLabel` 写在每一份 Meta 上：

```go
	drmetadata := config.Meta{
		Name:             ing.Name + "-" + "destinationrule",
		Namespace:        ing.Namespace,
		GroupVersionKind: gvk.DestinationRule,
		// Set this label so that we do not compare configs and just push.
		Labels: map[string]string{constants.AlwaysPushLabel: "true"},
	}
	vsmetadata := config.Meta{
		Name:             ing.Name + "-" + "virtualservice",
		Namespace:        ing.Namespace,
		GroupVersionKind: gvk.VirtualService,
		// Set this label so that we do not compare configs and just push.
		Labels: map[string]string{constants.AlwaysPushLabel: "true"},
	}
	efmetadata := config.Meta{
		Name:             ing.Name + "-" + "envoyfilter",
		Namespace:        ing.Namespace,
		GroupVersionKind: gvk.EnvoyFilter,
		// Set this label so that we do not compare configs and just push.
		Labels: map[string]string{constants.AlwaysPushLabel: "true"},
	}
	gatewaymetadata := config.Meta{
		Name:             ing.Name + "-" + "gateway",
		Namespace:        ing.Namespace,
		GroupVersionKind: gvk.Gateway,
		// Set this label so that we do not compare configs and just push.
		Labels: map[string]string{constants.AlwaysPushLabel: "true"},
	}

	for _, f := range c.destinationRuleHandlers {
		f(config.Config{Meta: drmetadata}, config.Config{Meta: drmetadata}, event)
	}
	for _, f := range c.virtualServiceHandlers {
		f(config.Config{Meta: vsmetadata}, config.Config{Meta: vsmetadata}, event)
	}
	for _, f := range c.envoyFilterHandlers {
		f(config.Config{Meta: efmetadata}, config.Config{Meta: efmetadata}, event)
	}
	for _, f := range c.gatewayHandlers {
		f(config.Config{Meta: gatewaymetadata}, config.Config{Meta: gatewaymetadata}, event)
	}
```

传给 handler 的两个 `config.Config` 都只有 Meta，没有 Spec。事件本身不携带任何配置内容，这是理解后面 pull 模型的关键。

> [!WARNING]
> 全仓非测试代码里 `ConfigUpdate(` 有 10 个调用点，分三类：上述合成 Meta handler 1 处；配置层经 `XDSUpdater` 接口间接推 8 处（`cert/certmgr.go:182`、`ingress_config.go:1524/1553/1578/2288`、`kingress_config.go:470`、`secret_config_mgr.go:153`、`kube/configmap/controller.go:212`）；Gateway API 移植层的 krt 泛型 `pushXds` 1 处（`kube/gateway/istio/controller.go:631`）。它们指向同一个对象：`bootstrap/server.go:240` 把 `s.xdsServer` 作为 `xdsUpdater` 注入 `NewIngressTranslation`，再由 `translation.go:50-53` 原样交给 Ingress / KIngress 两个配置存储，cert 与 gateway 控制器拿的也是同一指针。准确说法是十条入口、三类触发器、一个 `DiscoveryServer.ConfigUpdate`，十条一律 `Full: true`，"唯一汇流点"只在方法/对象层面成立。其中 `notifyXDSFullUpdate`（`:2279-2292`）全仓只有 `:496` 一个调用者且 `ConfigsUpdated` 恒为 nil，是一次不带任何 ConfigKey 的全量推送；`pushXds`（`gateway/istio/controller.go:614-636`）则是唯一先做 `ConfigKey` 集合去重、空集合直接 return 的入口。`AlwaysPushLabel` + `ProxyNeedsPush` 恒真的放大效应因此没法靠少发几次事件规避：直接推送路径绕过了 handler 广播。

> [!WARNING]
> Higress 侧**没有任何限流或去抖在生效**：`pkg/cmd/server.go:97-99` 把 pilot 的 `DebounceAfter` / `DebounceMax` / `EnableEDSDebounce` 读进 `ServerArgs.XdsOptions`，但全仓 Go 代码对这三个字段的引用只有赋值处与结构体声明，`bootstrap` 实际只消费 `KeepConfigLabels` / `KeepConfigAnnotations`（`:386`）——**它们是死字段**，真正的 debounce 在 pilot fork 内部（本机无工作树，默认值不可核）。同时 `ProxyNeedsPush` 被硬置恒真（`:399-401`），即 Higress 主动放弃了"哪些配置变化影响哪些 proxy"的精确判定，把成本换成"重算 + 全推"。

三个 debounce 字段只在构造 `ServerArgs` 时被赋值（`pkg/cmd/server.go:97-102`），而 `initXdsServer` 只取另外两个（`bootstrap/server.go:385`）：

```go
		XdsOptions: bootstrap.XdsOptions{
			DebounceAfter:         features.DebounceAfter,
			DebounceMax:           features.DebounceMax,
			EnableEDSDebounce:     features.EnableEDSDebounce,
			KeepConfigLabels:      keepConfigLabels,
			KeepConfigAnnotations: keepConfigAnnotations,
		},
```

```go
	generatorOptions := mcp.GeneratorOptions{KeepConfigLabels: s.XdsOptions.KeepConfigLabels, KeepConfigAnnotations: s.XdsOptions.KeepConfigAnnotations}
```

## Translation is Pull

`IngressConfig` 实现的接口是 `istiomodel.ConfigStoreController` + `istiomodel.IngressStore`（`ingress_config.go:80-82` 的编译期断言），且**写操作全部显式不支持**：`Create/Update/UpdateStatus/Patch/Delete` 一律返回 `ErrUnsupportedOp`（`:2166-2184`），`Get` 恒返回 nil（`:2162-2164`）。方向因此是反的：不是 Higress 把配置推给 pilot，而是 **pilot 反向 pull Higress**。写路径被整组封死（`ingress_config.go:2162-2184`）：

```go
func (m *IngressConfig) Get(config.GroupVersionKind, string, string) *config.Config {
	return nil
}

func (m *IngressConfig) Create(config.Config) (revision string, err error) {
	return "", common.ErrUnsupportedOp
}

func (m *IngressConfig) Update(config.Config) (newRevision string, err error) {
	return "", common.ErrUnsupportedOp
}

func (m *IngressConfig) UpdateStatus(config.Config) (newRevision string, err error) {
	return "", common.ErrUnsupportedOp
}

func (m *IngressConfig) Patch(config.Config, config.PatchFunc) (string, error) {
	return "", common.ErrUnsupportedOp
}

func (m *IngressConfig) Delete(config.GroupVersionKind, string, string, *string) error {
	return common.ErrUnsupportedOp
}
```

产物也不缓存。`List(typ, namespace)`（`:290-327`）先做 gvk 白名单，然后每次调用 `listFromIngressControllers`（`:329-380`）**把全部 Ingress 当场重算**：`:356-360` 从各集群子控制器取对象 → `:362` `SortIngressByCreationTime`（**排序是冲突路由归属的确定性来源**）→ `:363` `createWrapperConfigs` → `:366-377` 分派到 `convertGateways:502` / `convertVirtualService:555` / `convertDestinationRule:973` / `convertServiceEntry:931` / `convertWasmPlugin:907`；EnvoyFilter 在 `:336-353` 走独立分支提前 return，来源是 configmap 派生件加缓存。整个 `IngressConfig` 只有五处常驻状态：`wasmPlugins`、`http2rpcs`、`cachedEnvoyFilters`、`watchedSecretSet`、`mcpServerCache`。`List` 本身（`:290-327`）没有缓存，只有白名单、两次重算与两轮模板处理：

```go
func (m *IngressConfig) List(typ config.GroupVersionKind, namespace string) []config.Config {
	if typ != gvk.Gateway &&
		typ != gvk.VirtualService &&
		typ != gvk.DestinationRule &&
		typ != gvk.EnvoyFilter &&
		typ != gvk.ServiceEntry &&
		typ != gvk.WasmPlugin {
		return nil
	}
	configs := make([]config.Config, 0)

	if configsFromIngress := m.listFromIngressControllers(typ, namespace); configsFromIngress != nil {
		// Process templates for ingress configs
		for i := range configsFromIngress {
			if err := m.templateProcessor.ProcessConfig(&configsFromIngress[i]); err != nil {
				IngressLog.Errorf("Failed to process template for config %s/%s: %v",
					configsFromIngress[i].Namespace, configsFromIngress[i].Name, err)
			}
		}
		configs = append(configs, configsFromIngress...)
	}

	if configsFromGateway := m.listFromGatewayControllers(typ, namespace); configsFromGateway != nil {
		// Process templates for gateway configs. These are merged across namespaces and some of
		// them are re-stamped with the Higress system namespace, so the namespace of the object
		// a config was generated from cannot be recovered here. Their references are restricted
		// during the Gateway API conversion instead, while that namespace is still known.
		for i := range configsFromGateway {
			if err := m.templateProcessor.ProcessConfig(&configsFromGateway[i]); err != nil {
				IngressLog.Errorf("Failed to process template for config %s/%s: %v",
					configsFromGateway[i].Namespace, configsFromGateway[i].Name, err)
			}
		}
		configs = append(configs, configsFromGateway...)
	}

	return configs
}
```

Kingress（Gateway API）是同一机制的另一实现：`pkg/ingress/config/kingress_config.go`（562 行）具备同名同形的 `RegisterEventHandler` / `List` / `Run` / `HasSynced`，并复用同一个 `common.ConvertOptions.Route2Ingress` 结构（`:256` 与 `ingress_config.go:560` 逐字相同）；两者由 `translation/translation.go:50-53` 并联构造、`:163-192` 把两边结果 append 合并。Gateway API 资源本身又是第三个控制器，只在 `features.EnableGatewayAPI` 为真时注册（`ingress_config.go:285-287`）。

**注册中心写入的是 Higress 自有内存 store，不是 pilot。** 服务来源（McpBridge 背后的 nacos / consul / eureka / zookeeper / direct）由 `registry/` 下各 watcher 驱动，它们只调用 `registry/memory/cache.go` 的 `store.UpdateServiceWrapper` / `UpdateServiceEntryEndpointWrapper` 写进进程内 map（`sew` / `toBeUpdated`）；翻译层在 `List` 时经 `GetAllServiceWrapper()` 反向读取。⇒ 注册中心与 pilot 之间隔着一个 Higress 内存 store，watcher 产物不进入 pilot 的 `aggregate.Controller`——这正是"pilot 反向 pull"的最后一跳。

```
K8s API → informer(resync=0) → controllers.Queue(maxAttempts=5) → onEvent
   ├ DeepEqual(annotations/labels/spec) 不等才继续
   └ N 个合成 Meta(AlwaysPushLabel) → handler 数组
                     ↓
   bootstrap configHandler → xdsServer.ConfigUpdate(Full=true)
                     ↓   （debounce 在 pilot fork 内部）
   Generators[gvk].Generate → Environment.List(gvk, All)
                     ↓
   IngressConfig.List → 全量重算 convert* → templateProcessor
                     ↓
   mcp.generate() → mcp.Resource(field 100 = Extra) → discovery.Resource → Envoy
```

## Where Each CRD Lands

**McpBridge**。第一步就是身份门：`ingress_config.go:1419` 判 `name != "default"` 或命名空间不是控制器自身所在 ns 就直接 return（常量 `DefaultMcpBridgeName` 在 `:102-104`，而 `DeleteMcpBridge:1500` 重复写了字面量 `"default"` 而没用常量）。⇒ **改个名字、或放到别的命名空间，整份配置会被静默忽略，没有 Event、没有报错**。通过后在 `:1428-1488` 懒创建 `RegistryReconciler`，并把影响面硬编码成**五类资源全推**：`mcpbridge-serviceentry` / `-destinationrule` / `-virtualservice` / `-wasmplugin` / `-envoyfilter`（`:1430-1464`，广播顺序 `:1466-1485`）。删除时 `go reconciler.Reconcile(nil)` 后把 reconciler 置 nil（`:1503-1506`）。

**落地对象类型是 `ServiceEntry`，不是 `WorkloadEntry`。** `convertServiceEntry:931` 从 `RegistryReconciler.GetAllServiceWrapper()` 取服务，合成 `gvk.ServiceEntry`（namespace 固定 `mcp`）交给 xDS；`registry/memory/cache.go` 的内存 store 也只操作 `ServiceEntry`（`UpdateServiceWrapper` / `GetAllServiceEntry() []*v1alpha3.ServiceEntry`），全仓没有任何 `WorkloadEntry` 写入路径。⇒ 流传的"McpBridge 生成 WorkloadEntry"在源码层面不成立。

**WasmPlugin**。`convertIstioWasmPlugin` 精确在 `ingress_config.go:1199`。要点：`:1200-1216` 直拷 `Url/Sha256/ImagePullPolicy/ImagePullSecret/VerificationKey/PluginConfig/PluginName/Phase/FailStrategy/Priority` 并塞入 selector；**`:1227-1229`：`spec.pluginConfig` 非空就直接返回，`matchRules` 完全不看**（两者互斥、前者优先，这条文档没写）；`:1230-1232` 否则 `defaultConfigDisable != true` 时拿 `defaultConfig` 当 `PluginConfig`。四个下划线键 `_match_route_`（`:1276`）、`_match_service_`（`:1295`）、`_match_domain_`（`:1314`）、`_rules_`（`:1332`）**全是内联字符串字面量，本仓没有导出常量**。两处可疑实现值得记：`:1265-1267` 对非 HTTP 型规则做 `path.Join(rule.GetRouteType().String())`——**单参数 Join 等于只留路由类型，原始 ingress 值被丢弃**（是否构成实际缺陷需运行时验证，这里只记代码事实）；`:1322-1328` 一条规则的三个匹配条件全空会让**整份 CR 翻译失败**，而 `:1373-1375` 打 error 后保留旧缓存，即**旧配置继续生效**。另外 `AddOrUpdateWasmPlugin`（`:1351-1389`）是**先广播再写缓存**（`:1368` vs `:1386-1388`）。

调用图普查还给出三条结构性结论。其一，pilot 拿到的是三源并集：`convertWasmPlugin:907-927` 逐项输出 `m.wasmPlugins` 缓存（未排序），随后追加 `RegistryReconciler.GetAllConfigs(gvk.WasmPlugin)` 合成的 MCP 自动插件（`registry/memory/cache.go:93-131`，`Priority 999` / `FAIL_OPEN` / `ImagePullPolicy: Always` / Url 取 `MCP_SERVER_WASM_IMAGE_URL`）；`listFromGatewayControllers:381-388` 又对 WasmPlugin 特判，改走 `convertBuiltinInferenceEndpointPicker:403-441`，在 Gateway API `InferencePool` 的 builtin 模式下生成 `higress-internal-ai-endpoint-picker`（`_rules_` 只含 `_match_route_`，Url 取 `AI_ENDPOINT_PICKER_PLUGIN_URL`）。全仓 `pkg/` + `registry/` 非测试代码里 `extensions.WasmPlugin{` 共 3 处（`ingress_config.go:433` / `:1200` / `cache.go:115`），与三条来源对得上。其二，`List:290-327` 对合并结果还跑 `templateProcessor.ProcessConfig`，插件配置同样走模板注入。其三，事件语义另有两道门：`:1352` 非控制器自身 ns 的 WasmPlugin 静默忽略；`:1377-1383` 转换返回 nil 时删缓存却不广播删除事件；`DeleteWasmPlugin:1397` 则仅在缓存命中时广播。`WasmPluginGenerator.GenerateDeltas`（`mcp/generator.go:163-166`）恒返回 `false`，插件因此永远走全量 SotW。完整链路与失效矩阵见 [Plugin Loading Internals](/docs/CS/Framework/Higress/Plugin_Loading_Internals.md)。

**Http2Rpc**。产物是 **EnvoyFilter**，不是独立路由资源：`convertEnvoyFilter:821` → `constructHttp2RpcEnvoyFilter:836`（函数体 `:1652`，方法映射在 `constructHttp2RpcMethods:1762`，patch 载体由 `buildPatchStruct:1847` 从内联 JSON 构造）。方法名与参数来源的映射表是包级变量：`Http2RpcMethodMap`（`:83-91`，`GET→ALL_GET` 等 5 项）、`Http2RpcParamSourceMap`（`:92-99`，`QUERY→ALL_QUERY_PARAMETER` 等 4 项）——这就是文档里两张枚举表的源码对应物。路由侧靠注解 `higress.io/http2rpc-name` / `higress.io/rpc-destination-name`（`pkg/ingress/kube/annotations/http2rpc.go:22-23`）按名字引用它，`:1534-1535` 则连推 VirtualService 与 EnvoyFilter 两次。

`constructHttp2RpcEnvoyFilter:1652` 实际构造 **2~3 个 `EnvoyConfigObjectPatch`**（Context 一律 `GATEWAY`）：① `ApplyTo: HTTP_ROUTE` + `Operation: MERGE`，按 `RouteConfiguration.VirtualHost.Route.Name = 路由名` 精确匹配，把 `constructHttp2RpcMethods` 返回的 HTTP 方法与 Dubbo 方法映射 MERGE 进路由；② `ApplyTo: CLUSTER` + `MERGE`，按 `Service = 上游 Host` 匹配，给上游集群挂 `envoy.upstreams.http.dubbo_tcp` 连接池（`DubboTcpConnectionPoolProto`，`:1708-1716`）——即 Dubbo 走 **TCP 上游**而非 HTTP；③ `ApplyTo: HTTP_FILTER` + `INSERT_BEFORE envoy.filters.http.router`，注入 `envoy.filters.http.http_dubbo_transcoder`（`HttpDubboTranscoder`，`:1740-1746`）——**这条仅当 `initHttp2RpcGlobalConfig=true` 时追加**。`convertEnvoyFilter:825` 把该布尔初始化为 true，每成功构造一个 http2rpc 后于 `:842` 置 false ⇒ **transcoder filter 全网关只注入一次**（挂在第一个命中路由上），其余路由只生成各自的 route/cluster patch。EnvoyFilter 命名 `CreateConvertedName(gatewayName, "http2rpc", crName, "route", dnsRouteName)`（`:1753`）。⇒ Http2Rpc 的协议转换**不依赖任何 wasm 插件**，是 Envoy 原生 transcoder + dubbo_tcp 上游。

`constructHttp2RpcMethods:1762` 的方法映射模板逐字段展开如下。`httpRouterTemplate`（`:1763-1788`）是 `HTTP_ROUTE` 的 MERGE patch 值：`route.upgrade_configs[0]` 是 `upgrade_type: CONNECT` + `connect_config.allow_post: true`，把 HTTP 请求升级成可承载 Dubbo 的连接；`typed_per_filter_config` 只挂 `envoy.filters.http.http_dubbo_transcoder`，开 `reject_unknown_method: true` / `reject_unknown_query_parameters: true` 严格校验，配 `url_unescape_spec: ALL_CHARACTERS_EXCEPT_RESERVED`；`services_mapping` 的 `%s` 占位符在 `:1840-1841` 由 `json.Marshal` 结果经 `fmt.Fprintf` 填入。

映射体（`:1831-1838`）是 `name` / `version` / `group`（非空才写）+ `method_mapping`；每个方法（`:1790-1829`）含 `name`、`parameter_mapping[]` 的 `extract_key` / `extract_key_spec`（取自 `Http2RpcParamSourceMap()`）/ `mapping_type`、`path_matcher` 的 `match_http_method_spec`（取自 `Http2RpcMethodMap()[serviceMethod.HttpMethods[0]]`）与 `match_pattern`，以及 `passthrough_setting` 三态（空串 → `passthrough_all_headers:false`，`*` → `true`，其它 → `passthrough_headers`）。`match_http_method_spec` 只取第一个 HTTP 方法，配多个会被静默丢弃。

两种边界行为：`paramFromEntireBody != nil` 时忽略整个 `params` 列表，只生成单条 `extract_key_spec: BODY`（`:1794-1800`）；`HttpMethods` 为空则打 error 后 `continue` 跳过该方法（`:1812-1815`）。`buildPatchStruct:1847` 用 `jsonpb.Unmarshal` 转 `_struct.Struct`，失败只打 error、不返回错误。

**非 CRD 驱动的 EnvoyFilter（`convertEnvoyFilter:821` 内部，与 Http2Rpc 同函数）。** 同一次路由遍历还按注解/配置生成另外三类 EnvoyFilter：

- **basic-auth**（`constructBasicAuthEnvoyFilter:1856`）：把所有路由按 `secret+realm` 聚合成一个规则集（`:864-874`，同 key 的多路由 `MatchRoute` 合并），整体打包成**单个** EnvoyFilter。它**不是 wasm-cpp 编译产物再挂载**，而是翻译层直接构造一个 **Null VM wasm**（`envoy.wasm.runtime.null`，内联 code `envoy.wasm.basic_auth`，`:1876`）、`FailOpen: true`（插件加载/执行失败则放行，规则不匹配另算），`INSERT_AFTER envoy.filters.http.cors`（`:1922-1930`）注入到 `http_connection_manager` 过滤器链。⇒ 这是 Source Map 里"认证基础族在 wasm-cpp"在**控制面侧的落地形态**：cpp 是构建源，null-vm 是注入形态。
- **proxy / service-proxy**（`constructProxyEnvoyFilters:1939`）：每个 `ProxyWrapper` 直接 emit 一个 `proxy.<ProxyName>` EnvoyFilter（Spec 即 proxy 自带，`:1945-1949`）；随后为每个"使用 proxy 的服务"再生成一个 `service-proxy` EnvoyFilter——对每个 `outbound|<port>||<host>` 集群先做 `REMOVE`，再 `ADD` 一个 `STATIC` 集群指向 `127.0.0.1:<proxyWrapper.ListenerPort>`（connect_timeout 10s，`:1987-2050`），即把原上游改成**本机 sidecar 代理监听**；上游为 HTTPS 时附加 `envoy.transport_sockets.tls` 上游 TLS context（带 SNI，`:2029-2040`）。这是 Higress "服务级本地代理拦截" 的实现机制（对应 Source Map 的 `ServiceProxyConfig` / `ProxyWrapper`）。
- **MCP SSE 会话保持**（`constructMcpSseStatefulSessionEnvoyFilter:2186`，由 `loadBalance.McpSseStateful` 触发、`mcp-sse-stateful-param-name` 注解）：同样走 `INSERT_BEFORE envoy.filters.http.router` 的**全局一次性**注入（`:849/:855` 的 `initMcpSseGlobalFilter` 与 http2rpc 的全局布尔同构）。

本仓的 EnvoyFilter 全部走 `networking.EnvoyFilter`（Istio 原生类型），没有自造 CRD；四类（http2rpc / basic-auth / proxy / mcp-sse）都受 `AlwaysPushLabel` 与 `ProxyNeedsPush` 恒真的推送放大影响。

全仓 `networking.EnvoyFilter{` 构造、非测试代码共 9 处，分两族。`convertEnvoyFilter:821` 是路由翻译族的唯一制造点，四类产物落在 `:1756` / `:1910` / `:2062` / `:2273`；ConfigMap 派生族在 `pkg/ingress/kube/configmap/` 直接构造 5 处（`global.go:367`、`gzip.go:258`、`mcp_server.go:385`、`:448`、`tracing.go:317`），由 configmap controller 产出，经 `IngressConfig.cachedEnvoyFilters` 走 `List` 的 `gvk.EnvoyFilter` 独立分支提前返回（`:336-353`）。准确说法是两族、9 个构造点。McpBridge 变更广播的 `mcpbridge-envoyfilter` 合成 Meta 因此要同时顾及两族。

## The pilot Fork Boundary

**没有独立 pilot 进程。** `pkg/bootstrap/server.go` 直接 import `istio.io/istio/pilot/pkg/{xds,grpc,config/aggregate,serviceregistry/aggregate,...}`（`:31-48`），`go.mod:302-314` 用 replace 把 `istio.io/{api,pkg,client-go,istio}` 与 go-control-plane 全部指向 `./external/*`（`external/` 由 `tools/hack/prebuild.sh` 从子模块 `cp -RP` 生成，本机 clone 后不存在），**fork 是编译期硬前提**。同一个 `*xds.DiscoveryServer` 被分别塞给 IngressTranslation（`:240`）、cert.Server（`:440`）与 gateway 控制器（`ingress_config.go:286`），三者共享 `*model.Environment` 与 `aggregate.Controller` 指针。耦合强度是**内存对象级**，不是 RPC 级。

`pkg/ingress/mcp/` 不是 MCP 协议服务，而是 `DiscoveryServer.Generators` 的**替换层**（注册在 `bootstrap/server.go:387-392`）：六个类型 ServiceEntry / VirtualService / DestinationRule / EnvoyFilter / Gateway / WasmPlugin，每个 `Generate` 的第一动作都是 `Environment.List(gvk.X, NamespaceAll)`。`:393-398` 遍历 `collections.Pilot.All()`，把**没被覆盖的 gvk 一律塞 `FallbackGenerator`，而它恒返回空资源**（`mcp/generator.go:175-178`）。⇒ 除这六类之外的 Pilot collection 在这台网关上永远是空的。

符号图把这六次 pull 变成可数的：`unresolved_refs` 里 `c.Environment.List` 恰好 6 条，落在 `mcp/generator.go:54/87/105/123/141/159`，第七个 `FallbackGenerator::Generate` 没有 `List`。有两处不对称，单文件通读容易漏掉。其一是只有 `ServiceEntryGenerator` 排序（`:56-69`，先按 `CreationTimestamp`、并列时按 `name.namespace`，注释逐字说明是为"让 IP 分配逻辑确定性地给同一 ServiceEntry 分配同一个 IP"）。其二是 `GenerateDeltas` 签名分两批：前五个四参数（proxy / updates / w），`WasmPluginGenerator`（`:163`）与 `FallbackGenerator`（`:180`）多一个 `push *model.PushContext`，但七处函数体一律 `// TODO: delta implement` 并返回 `(..., false, nil)`，只有 `ServiceEntryGenerator` 在 `:36-39` 声明了 `XdsDeltaResourceGenerator` 断言。签名分两批是紧跟 fork 接口演进留下的残骸，与两种 delta 实现无关。`generate()`（`:186-236`）把每个 config 包成 `mcp.Resource`，`Metadata.Name = path.Join(namespace, name)`，labels / annotations 是否保留由 `GeneratorOptions` 两个布尔控制。

三条实现约束值得单独记：

- **Delta xDS 对这些类型不可用。** `GenerateDeltas` 全部是 `// TODO: delta implement` 并返回 `(..., false, nil)`（`mcp/generator.go:73-77` 等七处），只有 `ServiceEntryGenerator` 声明实现了 `XdsDeltaResourceGenerator`（`:36-39`）⇒ 会回退全量下发。
- **私有扩展靠 protobuf unknown field 夹带。** `generate()`（`:186-236`）把对象包成 `mcp/v1alpha1.Resource`，其中 `Metadata.Name = path.Join(namespace, name)`，而 `config.Extra` 通过 `addExtraToUnknownFields`（`:240-268`）写进 **字段号 100**（`:250`，注释解释该 proto 只用 1/2 号所以安全）。消费方必须是 Higress 的 fork——这是对 fork 侧 proto 未扩展的绕过手法。
- **`mesh` 段读到的是空对象。** `bootstrap/server.go:168` 注入的是 `meshwatcher.NewTestWatcher(&v1alpha1.MeshConfig{})`，即一个**静态的空 MeshConfig**。`HigressConfig` 结构体也没有 Mesh 字段（`pkg/ingress/kube/configmap/config.go:36-44`）。⇒ 别指望改 `higress-config` 的 `mesh` 段能像原生 Istio 那样被这个控制器响应。

顺带一条版本演进证据：`server.go:156` 注释掉 `buildLedger`、`:580-589` 整段标注 "ledger has been removed in istio 1.27"，而 `DistributionTrackingEnabled` 等字段仍留在 `RegistryOptions`（`:91-96`）却无人消费——**本仓紧跟 fork 的内部 API 变化，留下不少接口残骸**。

fork 内部常量现已可核：本仓 `.gitmodules` 把 `istio/istio` 钉在 **istio-1.27** 分支，本地该分支 HEAD 为 `65133dd`（与 submodule pin 一致），即下方证据的权威来源。`AlwaysPushLabel = "internal.istio.io/always-push"`（`pkg/config/constants/constants.go:132`）；pilot 的 `DebounceAfter` 默认 **100ms**（`PILOT_DEBOUNCE_AFTER`，`pilot/pkg/features/pilot.go:77`），但 Higress 侧三个 debounce 字段是死字段，该默认值对 Higress 推送行为无影响；`AddDebugHandlers`（`:154`）注册约 30 个 `/debug/*` 端点（`configz` / `adsz` / `ecdsz` / `syncz` / `registryz` / `endpointz` / `cachez` / `config_dump` / `push_status` / `connections` 等均在列），但整组受 `features.EnableDebugOnHTTP` 门控。`model.IngressRoute` 是 **fork 专有类型**（`pilot/pkg/model/ali_push_context.go:38`），字段含 `Host` / `Path` / `PathType` / `DestinationType` / `ServiceName` / `ServiceList []BackendService` / `Error` / `IngressNamespacedName` / `FullRequestURI` / `UnsupportedAnnotations`——它是 Ali push context 扩展对 Ingress 聚合的表示，并非上游 istio 类型。同一批 fork 基础设施里还有 `aggregate` 层：`MakeCache(caches []model.ConfigStoreController)`（`pilot/pkg/config/aggregate/config.go:79`）只是 `MakeWriteableCache(caches, nil)` 的薄壳（`:62`）⇒ **聚合后的 config store 恒不可写**（`Create` / `Delete` 返回 `errorUnsupported`，`:128-139`），`List` 按 `types.NamespacedName` 去重合并多个 store（`:109-126`）、`Get` 返回首个命中（`:98-106`）。这与 IngressConfig 自身 `Create/Update/Delete` 一律 `ErrUnsupportedOp` 是两层独立的事实：**先因为聚合层不写，再因为翻译层不写**。

## Debug Endpoints

`bootstrap/server.go:481` 只有一句 `s.xdsServer.AddDebugHandlers(s.httpMux, nil, true, nil)`：**`/debug/*` 的全部端点由 pilot fork 注册**，Higress 自己往 mux 上只加了两条——`:482` `/ready`（遍历 `readinessProbes`，`:495-504`）与 `:483` `/registry/watcherStatus`（经 `IngressTranslation` → `IngressConfig` → `RegistryReconciler.GetRegistryWatcherStatusList()`，`:506-527`）。

因此常被引用的 `http://127.0.0.1:8888/debug/configz` 是**从 fork 继承的端点**，现已核实存在（`pilot/pkg/xds/debug.go:192`）；整组 `/debug/*` 端点由 `AddDebugHandlers`（`:154`）注册，但受 `features.EnableDebugOnHTTP` 门控（`:157` 提前 return），该 feature 未开时**所有 debug 端点都不注册**。两个自有端点（`/ready` / `/registry/watcherStatus`）的鉴权由 `withConditionalAuth`（`:487-492`）按 pilot 的 `features.DebugAuth` 决定，与 fork 的 debug 端点共用同一套 localhost / XDS 认证逻辑。`/registry/watcherStatus` 的冷启动 404 见前文懒创建一节。

## What This Means in Practice

链路的形状直接决定几件运维与容量层面的事。**全量重算**意味着控制器的 CPU 与 Ingress **总数**相关而不是变更量相关：上千条 Ingress 时，任意一条的小改动都会触发一次全表 convert 加四类资源全推。**`AlwaysPushLabel` + `ProxyNeedsPush` 恒真**意味着 pilot 的"按需推送"优化被放弃，推送放大是设计取舍而非配置问题。**`resyncInterval = 0`** 意味着一旦事件在队列之外丢失（apiserver 重连、控制器重启窗口），没有周期性对账兜底——排查"配置对但没生效"时，比对 controller 生成侧与 Envoy 生效侧（见 [Deployment and Ops](/docs/CS/Framework/Higress/Deployment_and_Ops.md) 的四段链）比等自愈有效。**五类资源全推**（McpBridge）说明改一个服务来源的代价远大于直觉。

## Unverified

仍待核实：

- fork 内部真正的 debounce 生效路径、以及 `GenerateDeltas` 返回 false 后回退到全量下发的具体时机（Higress 侧三个 debounce 字段是死字段，但 fork 侧行为未实测）。
- `constructBasicAuthEnvoyFilter:1856` 的 Null VM 内联配置与 `constructProxyEnvoyFilters:1939` 的 cluster patch 模板逐字段语义；`buildPatchStruct` 解析失败后下发空 `Struct` 到 Envoy 的实际表现未验证。
- 十条 `ConfigUpdate` 入口在真实集群里的触发频率与合并效果未观测；`notifyXDSFullUpdate` 不带 `ConfigKey` 是否等价于全 proxy 全量重算，需在 fork 侧确认。

其余已核实并移入正文：McpBridge 落地为 ServiceEntry 而非 WorkloadEntry（证伪流传说法）；注册中心写入 Higress 自有内存 store（`registry/memory/cache.go`）而非 pilot 的 `aggregate.Controller`；`convertServiceEntry:931` 在 `List` 被 pull 时触发（前提是 `RegistryReconciler != nil`）；`ingressv1/status.go` 状态回写为 10s ticker + `reflect.DeepEqual` 去重；`AlwaysPushLabel` 字面量 `internal.istio.io/always-push`；pilot `DebounceAfter` 默认 100ms（Higress 侧为死字段）；`AddDebugHandlers` 端点清单（含 `configz`，受 `EnableDebugOnHTTP` 门控）；`model.IngressRoute` 为 fork 专有类型及其字段结构；四条 annotation/proxy 驱动的 EnvoyFilter（http2rpc / basic-auth / proxy / mcp-sse）的 patch 字面量与全局一次性注入逻辑；http2rpc 方法映射模板全字段语义；EnvoyFilter 两族 9 个构造点；六个 generator 的 6 次 `Environment.List` 与 delta 签名分两批；`ConfigUpdate` 十条入口共享同一 `DiscoveryServer`。证据基准：higress 主仓 v2.2.5（HEAD `4deae1dd`）+ standalone aio-v2.2.5（`36882509`）+ istio-1.27 fork（HEAD `65133dd`，即本仓 pin 的 `istio/istio` 分支，为旧会话离线核实结果）。

## Links

- [Source Map](/docs/CS/Framework/Higress/Source_Map.md)
- [Service Registry Internals](/docs/CS/Framework/Higress/Service_Registry_Internals.md)
- [Plugin System](/docs/CS/Framework/Higress/Plugin.md)
- [Traffic Governance](/docs/CS/Framework/Higress/Traffic_Governance.md)
- [Higress](/docs/CS/Framework/Higress/Higress.md)
- [Envoy](/docs/CS/Framework/Istio/Envoy.md)

## References

- [Higress v2.2.5 源码](https://github.com/alibaba/higress/tree/v2.2.5)
- [组件编译说明](https://higress.ai/docs/latest/dev/architecture/)
- [源码阅读指引](https://higress.ai/docs/latest/dev/code/)
- [Higress 自定义 CRD 开发指引](https://higress.ai/docs/latest/dev/customresourcedefinition/)
- [Wasm 生效原理](https://higress.ai/docs/latest/user/plugins/wasm-dev/wasm19/)
