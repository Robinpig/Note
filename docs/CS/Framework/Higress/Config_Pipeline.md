## Introduction

这一页只讲**链路**：一条配置从进控制器到变成 xDS 资源，中间经过哪些函数、在哪一步变成什么对象。模块与目录清单在 [Source Map](/docs/CS/Framework/Higress/Source_Map.md)，服务来源那一层的内部实现在 [Service Registry Internals](/docs/CS/Framework/Higress/Service_Registry_Internals.md)。

基准：`/Users/robin/Projects/higress` @ **v2.2.5**（HEAD `4deae1dd`）。全部行号可直接开文件复核。三条最先该知道的结论：**① Higress 对 pilot 是只读的 pull 模型，配置产物不缓存、每次 `List` 全量重算；② 事件只是脏标记，Higress 侧没有任何时间去抖生效；③ Higress 与 pilot fork 是同一个进程内共享指针，不是两个服务。**

## Process Assembly

`cmd/higress/main.go:28` 执行 `cmd.GetRootCommand().Execute()`，根命令（`pkg/cmd/root.go:21-31`）**只有 serve 与 version 两个子命令**——整个网关控制器就是一个 `higress serve`。`pkg/cmd/server.go:73` 构造、`:78` 启动，构造期与启动期是分开的。

`pkg/bootstrap/server.go:170-184` 的 `initFuncList` **注册顺序即执行顺序，全部同步，任一失败即整个构造失败**：

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

以 Ingress 为例（`pkg/ingress/kube/ingressv1/controller.go`）：`:119` 把 informer 的 EventHandler 直接接到 `controllers.ObjectHandler(c.queue.AddObject)`，队列是 pilot 的 `controllers.NewQueue("ingressv1", WithReconciler(c.onEvent), WithMaxAttempts(5))`（`:116-118`），key 就是 `namespace/name`，**没有自定义拼接**。Service / IngressClass 的 informer 在同一函数建立（`:95-102`）；CRD 侧走通用控制器 `pkg/ingress/kube/controller/model.go:67-70`，配置相同，只是内部 key 多带一个 ClusterId（`model.go:101-107`）。

真正的"合并"只有一处，且**不是时间窗**：`shouldProcessIngressUpdate`（`ingressv1/controller.go:1342-1387`）在对象已见过时用 `reflect.DeepEqual` 比较 **Annotations / Labels / Spec** 三项（`:1357-1372`，注释逐字为 "We only care about annotations, labels and spec."），三者全等就把事件丢掉。推论：**只改 status 或其它字段的更新不会触发下发**；而 `pkg/kube/client.go:73` 的 `resyncInterval = 0` 意味着**不存在周期性全量重推**——漏掉的事件不会靠 resync 自愈。

一次 Ingress 变更产生的是 **4 个合成 Meta**：`<name>-destinationrule` / `-virtualservice` / `-envoyfilter` / `-gateway`（`:191-212`），按 DR → VS → EnvoyFilter → Gateway 顺序向四组 handler 广播（`:219-233`），每个都带 `Labels{AlwaysPushLabel: "true"}`（注释："Set this label so that we do not compare configs and just push."）。所有下游 handler 最终汇流到同一个闭包：`bootstrap/server.go:201-213` 构造 `PushRequest{Full: true, ...}` 后调 `xdsServer.ConfigUpdate`（`:212`）——**这就是入队事件到 xDS push 的唯一汇流点**。合成名是全链路一致的约定，唯一例外是 Http2Rpc 用 CR 真名（`ingress_config.go:1528`）。

> [!WARNING]
> Higress 侧**没有任何限流或去抖在生效**：`pkg/cmd/server.go:97-99` 把 pilot 的 `DebounceAfter` / `DebounceMax` / `EnableEDSDebounce` 读进 `ServerArgs.XdsOptions`，但全仓 Go 代码对这三个字段的引用只有赋值处与结构体声明，`bootstrap` 实际只消费 `KeepConfigLabels` / `KeepConfigAnnotations`（`:386`）——**它们是死字段**，真正的 debounce 在 pilot fork 内部（本机无工作树，默认值不可核）。同时 `ProxyNeedsPush` 被硬置恒真（`:399-401`），即 Higress 主动放弃了"哪些配置变化影响哪些 proxy"的精确判定，把成本换成"重算 + 全推"。

## Translation is Pull

`IngressConfig` 实现的接口是 `istiomodel.ConfigStoreController` + `istiomodel.IngressStore`（`ingress_config.go:80-82` 的编译期断言），且**写操作全部显式不支持**：`Create/Update/UpdateStatus/Patch/Delete` 一律返回 `ErrUnsupportedOp`（`:2166-2184`），`Get` 恒返回 nil（`:2162-2164`）。方向因此是反的：不是 Higress 把配置推给 pilot，而是 **pilot 反向 pull Higress**。

产物也不缓存。`List(typ, namespace)`（`:290-327`）先做 gvk 白名单，然后每次调用 `listFromIngressControllers`（`:329-380`）**把全部 Ingress 当场重算**：`:356-360` 从各集群子控制器取对象 → `:362` `SortIngressByCreationTime`（**排序是冲突路由归属的确定性来源**）→ `:363` `createWrapperConfigs` → `:366-377` 分派到 `convertGateways:502` / `convertVirtualService:555` / `convertDestinationRule:973` / `convertServiceEntry:931` / `convertWasmPlugin:907`；EnvoyFilter 在 `:336-353` 走独立分支提前 return，来源是 configmap 派生件加缓存。整个 `IngressConfig` 只有五处常驻状态：`wasmPlugins`、`http2rpcs`、`cachedEnvoyFilters`、`watchedSecretSet`、`mcpServerCache`。

Kingress（Gateway API）是同一机制的另一实现：`pkg/ingress/config/kingress_config.go`（562 行）具备同名同形的 `RegisterEventHandler` / `List` / `Run` / `HasSynced`，并复用同一个 `common.ConvertOptions.Route2Ingress` 结构（`:256` 与 `ingress_config.go:560` 逐字相同）；两者由 `translation/translation.go:50-53` 并联构造、`:163-192` 把两边结果 append 合并。Gateway API 资源本身又是第三个控制器，只在 `features.EnableGatewayAPI` 为真时注册（`ingress_config.go:285-287`）。

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

**WasmPlugin**。`convertIstioWasmPlugin` 精确在 `ingress_config.go:1199`。要点：`:1200-1216` 直拷 `Url/Sha256/ImagePullPolicy/ImagePullSecret/VerificationKey/PluginConfig/PluginName/Phase/FailStrategy/Priority` 并塞入 selector；**`:1227-1229`：`spec.pluginConfig` 非空就直接返回，`matchRules` 完全不看**（两者互斥、前者优先，这条文档没写）；`:1230-1232` 否则 `defaultConfigDisable != true` 时拿 `defaultConfig` 当 `PluginConfig`。四个下划线键 `_match_route_`（`:1276`）、`_match_service_`（`:1295`）、`_match_domain_`（`:1314`）、`_rules_`（`:1332`）**全是内联字符串字面量，本仓没有导出常量**。两处可疑实现值得记：`:1265-1267` 对非 HTTP 型规则做 `path.Join(rule.GetRouteType().String())`——**单参数 Join 等于只留路由类型，原始 ingress 值被丢弃**（是否构成实际缺陷需运行时验证，这里只记代码事实）；`:1322-1328` 一条规则的三个匹配条件全空会让**整份 CR 翻译失败**，而 `:1373-1375` 打 error 后保留旧缓存，即**旧配置继续生效**。另外 `AddOrUpdateWasmPlugin`（`:1351-1389`）是**先广播再写缓存**（`:1368` vs `:1386-1388`）。

**Http2Rpc**。产物是 **EnvoyFilter**，不是独立路由资源：`convertEnvoyFilter:821` → `constructHttp2RpcEnvoyFilter:836`（函数体 `:1652`，方法映射在 `constructHttp2RpcMethods:1762`，patch 载体由 `buildPatchStruct:1847` 从内联 JSON 构造）。方法名与参数来源的映射表是包级变量：`Http2RpcMethodMap`（`:83-91`，`GET→ALL_GET` 等 5 项）、`Http2RpcParamSourceMap`（`:92-99`，`QUERY→ALL_QUERY_PARAMETER` 等 4 项）——这就是文档里两张枚举表的源码对应物。路由侧靠注解 `higress.io/http2rpc-name` / `higress.io/rpc-destination-name`（`pkg/ingress/kube/annotations/http2rpc.go:22-23`）按名字引用它，`:1534-1535` 则连推 VirtualService 与 EnvoyFilter 两次。

## The pilot Fork Boundary

**没有独立 pilot 进程。** `pkg/bootstrap/server.go` 直接 import `istio.io/istio/pilot/pkg/{xds,grpc,config/aggregate,serviceregistry/aggregate,...}`（`:31-48`），`go.mod:302-314` 用 replace 把 `istio.io/{api,pkg,client-go,istio}` 与 go-control-plane 全部指向 `./external/*`（`external/` 由 `tools/hack/prebuild.sh` 从子模块 `cp -RP` 生成，本机 clone 后不存在），**fork 是编译期硬前提**。同一个 `*xds.DiscoveryServer` 被分别塞给 IngressTranslation（`:240`）、cert.Server（`:440`）与 gateway 控制器（`ingress_config.go:286`），三者共享 `*model.Environment` 与 `aggregate.Controller` 指针。耦合强度是**内存对象级**，不是 RPC 级。

`pkg/ingress/mcp/` 不是 MCP 协议服务，而是 `DiscoveryServer.Generators` 的**替换层**（注册在 `bootstrap/server.go:387-392`）：六个类型 ServiceEntry / VirtualService / DestinationRule / EnvoyFilter / Gateway / WasmPlugin，每个 `Generate` 的第一动作都是 `Environment.List(gvk.X, NamespaceAll)`。`:393-398` 遍历 `collections.Pilot.All()`，把**没被覆盖的 gvk 一律塞 `FallbackGenerator`，而它恒返回空资源**（`mcp/generator.go:175-178`）。⇒ 除这六类之外的 Pilot collection 在这台网关上永远是空的。

三条实现约束值得单独记：

- **Delta xDS 对这些类型不可用。** `GenerateDeltas` 全部是 `// TODO: delta implement` 并返回 `(..., false, nil)`（`mcp/generator.go:73-77` 等七处），只有 `ServiceEntryGenerator` 声明实现了 `XdsDeltaResourceGenerator`（`:36-39`）⇒ 会回退全量下发。
- **私有扩展靠 protobuf unknown field 夹带。** `generate()`（`:186-236`）把对象包成 `mcp/v1alpha1.Resource`，其中 `Metadata.Name = path.Join(namespace, name)`，而 `config.Extra` 通过 `addExtraToUnknownFields`（`:240-268`）写进 **字段号 100**（`:250`，注释解释该 proto 只用 1/2 号所以安全）。消费方必须是 Higress 的 fork——这是对 fork 侧 proto 未扩展的绕过手法。
- **`mesh` 段读到的是空对象。** `bootstrap/server.go:168` 注入的是 `meshwatcher.NewTestWatcher(&v1alpha1.MeshConfig{})`，即一个**静态的空 MeshConfig**。`HigressConfig` 结构体也没有 Mesh 字段（`pkg/ingress/kube/configmap/config.go:36-44`）。⇒ 别指望改 `higress-config` 的 `mesh` 段能像原生 Istio 那样被这个控制器响应。

顺带一条版本演进证据：`server.go:156` 注释掉 `buildLedger`、`:580-589` 整段标注 "ledger has been removed in istio 1.27"，而 `DistributionTrackingEnabled` 等字段仍留在 `RegistryOptions`（`:91-96`）却无人消费——**本仓紧跟 fork 的内部 API 变化，留下不少接口残骸**。

## Debug Endpoints

`bootstrap/server.go:481` 只有一句 `s.xdsServer.AddDebugHandlers(s.httpMux, nil, true, nil)`：**`/debug/*` 的全部端点由 pilot fork 注册**，Higress 自己往 mux 上只加了两条——`:482` `/ready`（遍历 `readinessProbes`，`:495-504`）与 `:483` `/registry/watcherStatus`（经 `IngressTranslation` → `IngressConfig` → `RegistryReconciler.GetRegistryWatcherStatusList()`，`:506-527`）。

因此常被引用的 `http://127.0.0.1:8888/debug/configz` 是**从 fork 继承的端点**，其存在性与参数在本仓不可核实（全仓 `grep configz` 在 `pkg/` 下零命中）。两个自有端点的鉴权由 `withConditionalAuth`（`:487-492`）按 pilot 的 `features.DebugAuth` 决定。`/registry/watcherStatus` 的冷启动 404 见前文懒创建一节。

## What This Means in Practice

链路的形状直接决定几件运维与容量层面的事。**全量重算**意味着控制器的 CPU 与 Ingress **总数**相关而不是变更量相关：上千条 Ingress 时，任意一条的小改动都会触发一次全表 convert 加四类资源全推。**`AlwaysPushLabel` + `ProxyNeedsPush` 恒真**意味着 pilot 的"按需推送"优化被放弃，推送放大是设计取舍而非配置问题。**`resyncInterval = 0`** 意味着一旦事件在队列之外丢失（apiserver 重连、控制器重启窗口），没有周期性对账兜底——排查"配置对但没生效"时，比对 controller 生成侧与 Envoy 生效侧（见 [Deployment and Ops](/docs/CS/Framework/Higress/Deployment_and_Ops.md) 的四段链）比等自愈有效。**五类资源全推**（McpBridge）说明改一个服务来源的代价远大于直觉。

## Unverified

pilot / envoy fork 内部一律未核（本机 `istio/`、`envoy/` 子模块与 `external/` 均无工作树）：debounce 的真实算法与默认值（本地唯一线索是 `bootstrap/server.go:65` 的注释 "Defaults to 10 seconds"）；`controllers.Queue` 底层是否 `workqueue.RateLimitingInterface` 及速率参数；`configaggregate.MakeCache` 的事件重放与 `HasSynced` 语义；`AddDebugHandlers` 注册了哪些端点；`AlwaysPushLabel` 等常量的字面值；`model.IngressRoute` 字段结构。链路最后一跳未追到底：`BaseWatcher.UpdateService()` 的实现体未读，`registry/memory/` 未打开，因此 watcher 生成的 ServiceEntry 究竟写进 pilot 的 `aggregate.Controller` 还是另有 store 未确认；**"McpBridge 生成 WorkloadEntry" 这一常见说法本次既未证实也未证伪**（一次检索因 zsh glob 展开整条失败，不作为"不存在"的结论）。`constructHttp2RpcEnvoyFilter`（`:1652-1761`）与 `constructBasicAuthEnvoyFilter`（`:1856`）、`constructProxyEnvoyFilters`（`:1939`）的 patch 字面量未展开；`convertServiceEntry:931-972` 的触发条件未读；`ingressv1/status.go` 的状态回写节流未读。

## Links

- [Source Map](/docs/CS/Framework/Higress/Source_Map.md)
- [Service Registry Internals](/docs/CS/Framework/Higress/Service_Registry_Internals.md)
- [Plugin System](/docs/CS/Framework/Higress/Plugin.md)
- [Architecture](/docs/CS/Framework/Higress/Architecture.md)
- [Traffic Governance](/docs/CS/Framework/Higress/Traffic_Governance.md)
- [Higress](/docs/CS/Framework/Higress/Higress.md)
- [Envoy](/docs/CS/Framework/Istio/Envoy.md)

## References

- [Higress v2.2.5 源码](https://github.com/alibaba/higress/tree/v2.2.5)
- [组件编译说明](https://higress.ai/docs/latest/dev/architecture/)
- [源码阅读指引](https://higress.ai/docs/latest/dev/code/)
- [Higress 自定义 CRD 开发指引](https://higress.ai/docs/latest/dev/customresourcedefinition/)
- [Wasm 生效原理](https://higress.ai/docs/latest/user/plugins/wasm-dev/wasm19/)
