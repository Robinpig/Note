## Introduction

[Config Pipeline](/docs/CS/Framework/Higress/Config_Pipeline.md) 与 [Source Map](/docs/CS/Framework/Higress/Source_Map.md) 逐文件读源码，回答函数在哪、做什么；这一页读符号图，回答谁实现谁、同一条推送有几条入口、某个类型在全仓被造出来几次。证据来自两个仓库各自的 `.codegraph/codegraph.db`（CodeGraph 1.6.2、extraction 27、schema v11），基准是主仓 v2.2.5（`4deae1dd`）与 standalone aio-v2.2.5（`36882509`）。

符号图能看到单文件读不到的扇入扇出，但图本身不是事实。两库的边按名称解析，跨包同名会误连；本页把 `nodes` / `implements` / `unresolved_refs` 当候选证据，`calls` 边只用来定位，写进正文的结论一律回源码核过。凡是靠一段代码就能说清的，源码直接贴在正文里；`路径:行号` 只用于回查。这套口径也是枢纽页 Verification Protocol 的第三层信源。

## Index Shape

| 项 | 主仓 | standalone |
| --- | --- | --- |
| 索引文件 | 1564（go 1115 / yaml 339 / cpp 51 / python 23 / rust 22 / 其余 14） | 99（go 26 / yaml 24 / python 4 / ts 1 / php 44 系误判） |
| 节点 | 26826 | 562 |
| 边 | 70358 | 1093 |
| 未解析引用 | 102002 | 1807 |
| 索引状态 | `index_state=complete` | `index_state=complete` |

主仓边类型分布：`contains` 29454、`calls` 22234、`references` 7818、`instantiates` 5443、`imports` 4204、`implements` 1104、`extends` 101；standalone 同构但小两个数量级（218 条 calls、34 条 instantiates、0 条 implements）。

覆盖边界决定哪些结论能靠图闭合。standalone 的 go 节点全部落在 `src/apiserver/`，`bin/` / `compose/` / `all-in-one/` 的 shell 与编排逻辑一个都不在图里；那 44 个 php 其实是 `test/configure/cases/*.inc` 被语言探测器误判。主仓侧多收了噪声：`.agents/` / `.claude/` 下的 Python 与 TypeScript 工具脚本也在索引里（例如节点 `function:ed1ce9d5…` 来自 `.agents/skills/agent-session-monitor/example/clawdbot_demo.py`），而 `external/` 因未跑 `make prebuild` 根本不存在，pilot fork 与 Envoy 的符号数为零。涉及 fork 内部行为的结论，这套图作不了证，只能靠 `go.mod` 的 replace 与 import 语句。

## Resolution Semantics

`calls` 边的 `metadata.resolvedBy` 分布（主仓）：`exact-match` 12485、`instance-method` 6636、`import` 533、`qualified-name` 521、无标记 2059。超过一半是纯名称匹配，误连不难找：`pkg/bootstrap/server.go` 的 `Start` 同时连到 `Server::Start` 与 `pkg/cmd/server_test.go` 的 `delayedServer::Start`；`initXdsServer` 连到 `plugins/wasm-go/pkg/mcp/server/schema_validator.go` 的 `schemaDiagnosticReason::String`；`writeJSON` 连到 `plugins/wasm-go/examples/jwt-auth/handler/verify.go` 的 `ErrDenied::Error`。三条都是同名跨包串线，与真实调用无关。standalone 的 218 条 calls 同样是 `exact-match` 121 / `instance-method` 80 / `import` 14 / `framework` 3。

`implements` 也不干净：`plugins/wasm-go/extensions/ai-proxy/provider/provider.go:223` 的 `providerInitializer` 接口被图上 40 条 implements 边连到 `milvusProviderInitializer` / `redisProviderInitializer` / `chromaProviderInitializer` 等来自 `ai-cache/vector/` 与 `ai-cache/cache/` 的类型。回源码看，真实机制是一张显式注册表（`:234-236` 起）：

```go
providerInitializers = map[string]providerInitializer{
	providerTypeMoonshot:   &moonshotProviderInitializer{},
	providerTypeAzure:      &azureProviderInitializer{},
	providerTypeAi360:      &ai360ProviderInitializer{},
	providerTypeGithub:     &githubProviderInitializer{},
	providerTypeQwen:       &qwenProviderInitializer{},
	providerTypeOpenAI:     &openaiProviderInitializer{},
	providerTypeGroq:       &groqProviderInitializer{},
	providerTypeGrok:       &grokProviderInitializer{},
	providerTypeBaichuan:   &baichuanProviderInitializer{},
	providerTypeYi:         &yiProviderInitializer{},
	providerTypeDeepSeek:   &deepseekProviderInitializer{},
	// ...
}
```

`:130-167` 定义 38 个 `providerType*` 常量，这张 map 恰 38 项一一对应（含内部回退 `generic`，且 `providerTypeAi360` 在 `:132` 真实存在）。图上那 40 条是假象，源码里是 38 个显式注册项。图在这里的作用是指出存在一组同构类型，数量得回源码数。

反倒是 `unresolved_refs` 更可靠：它保留解析失败的调用原文（`reference_name` / `file_path` / `line` / `status='failed'`）并带 `from_node_id`。跨包调用全落在这里，例如主仓 `s.xdsServer.ConfigUpdate`（`pkg/bootstrap/server.go:212`）、standalone 的 `converter.RegisterConverters`（`apiserver.go:200`）、`codec.NewFlatAwareCodec`（`:187`）、`registry.NewFileREST`（`:188`）、`registry.NewNacosREST`（`:194`）全是 `failed`。要数全仓某方法有几个调用点，得查这张表再用 `grep` 复核。下面两节的计数都按这个口径。

## Interface Implementation Matrix

`implements` 边里，source 落在 `pkg/` 或 `registry/` 的共 104 条。其中最说明问题的是四个类型：`IngressConfig`（`pkg/ingress/config/ingress_config.go`）、`KIngressConfig`（`kingress_config.go`）、`IngressTranslation`（`translation/translation.go`）、`gatewayController`（`kube/gateway/controller.go`）各自实现同一组五个接口——`WasmPluginNamespaceLister` / `Http2RpcNamespaceLister` / `McpBridgeNamespaceLister` / `GatewayController` / `Value`。四个类型实现同一组接口，是翻译层可替换留下的形状：Ingress 侧与 Gateway API 侧各有一个配置存储，聚合层把两者并联，三者对 pilot 暴露同一份 lister 契约。

注解层的契约数量也可从图里直接读出（`pkg/ingress/kube/annotations/interface.go`）：`Parser` 25、`RouteHandler` 13、`TrafficPolicyHandler` 3、`GatewayHandler` 2、`VirtualServiceHandler` 2。`GatewayController` 有 7 个实现者（除上面四个，还有 `kube/ingress/` / `ingressv1/` / `kingress/` 三个 controller），对应三种 Ingress 代际并存的源码结构。

> [!WARNING]
> `registry/watcher.go` 的 `Watcher` 接口在图上只有 `BaseWatcher` 一个实现者，但源码里八种来源 watcher 全部满足该接口。原因是它们靠嵌入 `BaseWatcher` 继承方法集，而索引器只为显式方法声明建边。这是索引器的盲点：嵌入式实现和编译期接口断言（`_ model.XdsResourceGenerator = ...`）都不产生 implements 边，不能读成"只有基类实现接口"。

## Push Entry Points

全仓非测试代码里 `ConfigUpdate(` 共 10 个调用点，分三类触发源。过去把 `bootstrap/server.go:212` 当作入队事件到 xDS push 的唯一汇流点，只在方法/对象层面成立，在调用点层面不成立：

| 类别 | 位置 | 触发源 |
| --- | --- | --- |
| 合成 Meta handler | `pkg/bootstrap/server.go:212` | `initRegistryEventHandlers` 把 `configHandler` 注册到 `common.IngressIR.All()` 的六个 GVK（`:216-219`），reason 为 `model.ConfigUpdate` |
| `XDSUpdater` 接口间接 | `pkg/cert/certmgr.go:182`；`pkg/ingress/config/ingress_config.go:1524`、`:1553`、`:1578`、`:2288`；`kingress_config.go:470`；`secret_config_mgr.go:153`；`kube/configmap/controller.go:212` | `higress-https` 配置变更、Http2Rpc 增删、auth Secret 变更、MCP server 注解变更、ConfigMap 派生件变更 |
| krt 集合事件 | `kube/gateway/istio/controller.go:631`（泛型 `pushXds`） | Gateway API 移植层的 krt 事件，先聚合 `ConfigKey` 集合再推 |

第一类入口长这样（`bootstrap/server.go:199-219`），`Full: true` 与 `AlwaysPushLabel` 分别出现在两端：

```go
func (s *Server) initRegistryEventHandlers() error {
	log.Info("initializing registry event handlers")
	configHandler := func(prev config.Config, curr config.Config, event model.Event) {
		// For update events, trigger push only if spec has changed.
		pushReq := &model.PushRequest{
			Full: true,
			ConfigsUpdated: map[model.ConfigKey]struct{}{{
				Kind:      gvk.MustToKind(curr.GroupVersionKind),
				Name:      curr.Name,
				Namespace: curr.Namespace,
			}: {}},
			Reason: model.NewReasonStats(model.ConfigUpdate),
		}
		s.xdsServer.ConfigUpdate(pushReq)
	}
	schemas := common.IngressIR.All()
	for _, schema := range schemas {
		s.configController.RegisterEventHandler(schema.GroupVersionKind(), configHandler)
	}
	return nil
}
```

回调签名里的 `prev` 和 `event` 都没被用到，注释说的"仅 spec 变化才推"并未实现，真正的去重在更上游的 `shouldProcessIngressUpdate`。第三类入口则是唯一先做集合去重、空集合直接 return 的一处（`kube/gateway/istio/controller.go:614-636`）：

```go
func pushXds[T any](xds model.XDSUpdater, f func(T) model.ConfigKey) func(events []krt.Event[T]) {
	return func(events []krt.Event[T]) {
		if xds == nil {
			return
		}
		cu := sets.New[model.ConfigKey]()
		for _, e := range events {
			for _, i := range e.Items() {
				c := f(i)
				if c != (model.ConfigKey{}) {
					cu.Insert(c)
				}
			}
		}
		if len(cu) == 0 {
			return
		}
		xds.ConfigUpdate(&model.PushRequest{
			Full:           true,
			ConfigsUpdated: cu,
			Reason:         model.NewReasonStats(model.ConfigUpdate),
		})
	}
}
```

它们最终是同一个对象：`bootstrap/server.go:240` 把 `s.xdsServer` 作为 `xdsUpdater` 传给 `translation.NewIngressTranslation`，后者再原样注入两个配置存储（`translation.go:46-54`）：

```go
func NewIngressTranslation(localKubeClient kube.Client, xdsUpdater istiomodel.XDSUpdater, namespace string, options common.Options) *IngressTranslation {
	if options.ClusterId == "Kubernetes" {
		options.ClusterId = ""
	}
	Config := &IngressTranslation{
		ingressConfig:  ingressconfig.NewIngressConfig(localKubeClient, xdsUpdater, namespace, options),
		kingressConfig: ingressconfig.NewKIngressConfig(localKubeClient, xdsUpdater, namespace, options),
	}
	return Config
}
```

`cert.NewServer` 与 `gateway.NewController` 拿的也是同一指针。十条入口、三类触发器，落到一个 `*xds.DiscoveryServer.ConfigUpdate`，且十条全部构造 `Full: true`。`AlwaysPushLabel` 与 `ProxyNeedsPush` 恒真带来的放大效应因此没法靠少发几次事件规避：直接推送路径绕过了 handler 广播。

另有两处细节。`notifyXDSFullUpdate`（`ingress_config.go:2279-2292`）全仓只有 `:496` 一个调用者（MCP server 注解变更），且传 `updatedConfigName=nil`；`ConfigsUpdated` 因此恒为 nil，是一次不带任何 ConfigKey 的全量推送：

```go
func (m *IngressConfig) notifyXDSFullUpdate(GVK config.GroupVersionKind, reason istiomodel.TriggerReason, updatedConfigName *util.ClusterNamespacedName) {
	var configsUpdated map[istiomodel.ConfigKey]struct{}
	if updatedConfigName != nil {
		configsUpdated = map[istiomodel.ConfigKey]struct{}{{
			Kind:      gvk.MustToKind(GVK),
			Name:      updatedConfigName.Name,
			Namespace: updatedConfigName.Namespace,
		}: {}}
	}
	m.XDSUpdater.ConfigUpdate(&istiomodel.PushRequest{
		Full:           true,
		ConfigsUpdated: configsUpdated,
		Reason:         istiomodel.NewReasonStats(reason),
	})
}
```

## Generator Graph

`pkg/ingress/mcp/generator.go` 的七个 generator 类型与六次 pull 在图里可对上：`unresolved_refs` 中 `c.Environment.List` 恰好 6 条，分别落在 `:54` / `:87` / `:105` / `:123` / `:141` / `:159`，对应 ServiceEntry / VirtualService / DestinationRule / EnvoyFilter / Gateway / WasmPlugin 六个 `Generate`；第七个 `FallbackGenerator::Generate`（`:175-178`）恒返回空 resources，没有 `List`。注册侧是 `bootstrap/server.go:387-401`，六行赋值之后把未覆盖的 gvk 全塞 `FallbackGenerator`，并把 `ProxyNeedsPush` 硬置恒真：

```go
s.xdsServer.Generators[gvk.WasmPlugin.String()] = &mcp.WasmPluginGenerator{Environment: s.environment, Server: s.xdsServer, GeneratorOptions: generatorOptions}
s.xdsServer.Generators[gvk.DestinationRule.String()] = &mcp.DestinationRuleGenerator{Environment: s.environment, Server: s.xdsServer, GeneratorOptions: generatorOptions}
s.xdsServer.Generators[gvk.EnvoyFilter.String()] = &mcp.EnvoyFilterGenerator{Environment: s.environment, Server: s.xdsServer, GeneratorOptions: generatorOptions}
s.xdsServer.Generators[gvk.Gateway.String()] = &mcp.GatewayGenerator{Environment: s.environment, Server: s.xdsServer, GeneratorOptions: generatorOptions}
s.xdsServer.Generators[gvk.VirtualService.String()] = &mcp.VirtualServiceGenerator{Environment: s.environment, Server: s.xdsServer, GeneratorOptions: generatorOptions}
s.xdsServer.Generators[gvk.ServiceEntry.String()] = &mcp.ServiceEntryGenerator{Environment: s.environment, Server: s.xdsServer, GeneratorOptions: generatorOptions}
for _, schema := range collections.Pilot.All() {
	gvk := schema.GroupVersionKind().String()
	if _, ok := s.xdsServer.Generators[gvk]; !ok {
		s.xdsServer.Generators[gvk] = &mcp.FallbackGenerator{Environment: s.environment, Server: s.xdsServer}
	}
}
s.xdsServer.ProxyNeedsPush = func(proxy *model.Proxy, req *model.PushRequest) (*model.PushRequest, bool) {
	return req, true
}
```

`GeneratorOptions` 只喂了 `KeepConfigLabels` / `KeepConfigAnnotations` 两个字段，`pkg/cmd/server.go:89-102` 读进来的 `DebounceAfter` / `DebounceMax` / `EnableEDSDebounce` 在这里完全没被消费，是死字段。

有两处不对称，单文件通读容易漏掉。其一是只有 `ServiceEntryGenerator::Generate` 排序（`:50-77`），注释逐字说明目的是让 IP 分配逻辑确定性地给同一 ServiceEntry 分配同一个 IP；紧随其后的 `GenerateDeltas` 是 `TODO` 并返回 false：

```go
func (c ServiceEntryGenerator) Generate(proxy *model.Proxy, w *model.WatchedResource,
	updates *model.PushRequest) (model.Resources, model.XdsLogDetails, error) {
	serviceEntries := c.Environment.List(gvk.ServiceEntry, model.NamespaceAll)
	if serviceEntries != nil {
		// To ensure the ip allocation logic deterministically
		// allocates the same IP to a service entry.
		sort.Slice(serviceEntries, func(i, j int) bool {
			// If creation time is the same, then behavior is nondeterministic. In this case, we can
			// pick an arbitrary but consistent ordering based on name and namespace, which is unique.
			// CreationTimestamp is stored in seconds, so this is not uncommon.
			if serviceEntries[i].CreationTimestamp == serviceEntries[j].CreationTimestamp {
				in := serviceEntries[i].Name + "." + serviceEntries[i].Namespace
				jn := serviceEntries[j].Name + "." + serviceEntries[j].Namespace
				return in < jn
			}
			return serviceEntries[i].CreationTimestamp.Before(serviceEntries[j].CreationTimestamp)
		})
	}
	return generate(proxy, serviceEntries, w, updates, c.GeneratorOptions.KeepConfigLabels, c.GeneratorOptions.KeepConfigAnnotations)
}

func (c ServiceEntryGenerator) GenerateDeltas(proxy *model.Proxy, updates *model.PushRequest,
	w *model.WatchedResource) (model.Resources, []string, model.XdsLogDetails, bool, error) {
	// TODO: delta implement
	return nil, nil, model.DefaultXdsLogDetails, false, nil
}
```

其余五个 `Generate` 直接把 `List` 结果交给 `generate()`。其二是 `GenerateDeltas` 的签名分两批：前五个四参数（proxy / updates / w），`WasmPluginGenerator`（`:163`）与 `FallbackGenerator`（`:180`）多一个 `push *model.PushContext`，但七处函数体一律 `// TODO: delta implement` 并返回 `(..., false, nil)`，只有 `ServiceEntryGenerator` 在 `:36-39` 声明了 `XdsDeltaResourceGenerator` 断言。签名分两批是紧跟 fork 接口演进留下的残骸，与两种 delta 实现无关。

`generate()`（`:186-236`）把每个 config 包成 `mcp.Resource`，`Metadata.Name = path.Join(namespace, name)`，labels / annotations 是否保留由 `GeneratorOptions` 两个布尔控制；`config.Extra` 则写进 protobuf 字段号 100 的 unknown field（`addExtraToUnknownFields:240-268`），绕过 fork 侧 proto 未扩展的限制：

```go
func addExtraToUnknownFields(resource *mcp.Resource, extra map[string]any) error {
	// Serialize Extra to JSON
	extraJSON, err := json.Marshal(extra)
	if err != nil {
		return err
	}

	// Use field number 100 (arbitrary high number not used in the proto definition)
	// Resource proto only has field 1 (metadata) and field 2 (body), so 100 is safe
	// Field 100, wire type 2 (length-delimited for bytes/string)
	const extraFieldNumber = 100

	// Encode the field: tag (field number + wire type) + length + data
	tag := protowire.EncodeTag(extraFieldNumber, protowire.BytesType)
	unknownData := protowire.AppendVarint(nil, uint64(tag))
	unknownData = protowire.AppendBytes(unknownData, extraJSON)

	resourceReflect := resource.ProtoReflect()
	existingUnknown := resourceReflect.GetUnknown()
	resourceReflect.SetUnknown(append(existingUnknown, unknownData...))
	return nil
}
```

节选省去了四行 `Debugf` 与两行说明注释。消费方必须是 Higress 的 fork，这是理解「为什么不能拿原生 Istio 直接替换」的一条硬证据。

## EnvoyFilter Factory Census

全仓普查 `networking.EnvoyFilter{` 构造点，可以把"唯一制造点"的说法精确化：非测试代码共 9 处，分两族。`pkg/ingress/config/ingress_config.go` 内 4 处是路由翻译族——`:1756` http2rpc、`:1910` basic-auth、`:2062` proxy / service-proxy、`:2273` MCP SSE 会话保持；`pkg/ingress/kube/configmap/` 内 5 处是 ConfigMap 派生族——`global.go:367`、`gzip.go:258`、`mcp_server.go:385`、`:448`、`tracing.go:317`。

`convertEnvoyFilter`（`:821`）只是路由翻译族的唯一制造点。另一族由 configmap controller 直接产出，经 `IngressConfig.cachedEnvoyFilters` 缓存在 `List` 的 `gvk.EnvoyFilter` 独立分支提前返回（`:336-353`）。McpBridge 变更广播的 `mcpbridge-envoyfilter` 合成 Meta 因此要同时顾及两族来源。

## WasmPlugin Graph

把同一套普查用在插件上：与 WasmPlugin 命名节点相关的边是 `contains 482` / `references 148` / `calls 118` / `instantiates 94` / `implements 68` / `imports 46`，但 `ingress_config.go` 内真正 calls 到 WasmPlugin 命名目标的只有 3 条——`:376` `convertWasmPlugin`、`:1355` `WasmPluginLister::WasmPlugins`、`:1372` `convertIstioWasmPlugin`。那 118 条绝大多数来自 `wasmplugin.pb.go` / clientset / informer 的生成代码里同名字段访问，不能当"插件被调用的次数"。`unresolved_refs` 更干净：`config.AddOrUpdateWasmPlugin` 与 `config.DeleteWasmPlugin` 都在 `:223`，`gvk.WasmPlugin.String` 在 `bootstrap/server.go:387`。

回源码 `grep 'extensions.WasmPlugin{'`（`pkg/` + `registry/`，排除测试）得恰好 3 处：`ingress_config.go:433` 内置 inference endpoint picker、`:1200` CR 转换、`registry/memory/cache.go:115` MCP 自动插件，与 `List(gvk.WasmPlugin)` 的三条来源对得上。图负责指路，定性还得回源码。三段构造代码与完整加载链见 [Plugin Loading Internals](/docs/CS/Framework/Higress/Plugin_Loading_Internals.md)。

## Console API Surface in hgctl

图里的 25 个 `route` 节点中，9 个属于 `hgctl/pkg/agent/services/service.go`：`POST /v1/service-sources`、`PUT /v1/mcpServer`（两处）、`POST /v1/ai/providers`、`POST /v1/ai/routes`、`POST /v1/routes`、`POST /api/v1/gateways`、`POST /api/v1/products`，以及 `gateway_config_test.go:52` 的 `ANY /`。这些是 hgctl agent 调 Higress Console REST API 的客户端端点，与网关数据面路由无关；控制台管理面的服务来源、AI 路由管理、产品与网关，在 CLI 侧都能对上。另两条自有 HTTP 端点 `ANY /ready` 与 `ANY /registry/watcherStatus` 落在 `pkg/bootstrap/server.go:482-483`，其余 route 节点来自 wasm 插件对外调用向量库与模型厂商的 URL 字面量。

## Unverified

- `calls` 与 `implements` 边的误连比例未量化：本页只举出可复核的实例（`Start` / `initXdsServer` / `providerInitializer`），没有抽样统计全库置信度，因此不要把任何"边计数"直接当源码事实引用。
- pilot fork、Envoy、`external/` 与 nacos SDK 内部均不在两库索引内；跨 fork 的 xDS 推送行为、Delta 回退时机、SDK 传输层仍以源码正文为准。
- `compose/` 与 `all-in-one/` 的 shell 编排、console 仓库的 API 实现未被索引；上节 9 个 Console 端点只核到 hgctl 侧的 URL 字面量，服务端实现未逐行核对。
- `test/configure/cases/*.inc` 被判为 php 是索引器的语言识别结果，未查其判定规则；不影响正文结论，但引用 standalone 库的语言分布时需带这个前提。

## Links

- [Standalone and All-in-One](/docs/CS/Framework/Higress/Standalone_and_AllInOne.md)
- [Service Registry Internals](/docs/CS/Framework/Higress/Service_Registry_Internals.md)
- [Plugin System](/docs/CS/Framework/Higress/Plugin.md)
- [Plugin Loading Internals](/docs/CS/Framework/Higress/Plugin_Loading_Internals.md)
- [Higress](/docs/CS/Framework/Higress/Higress.md)

## References

- [Higress v2.2.5 源码](https://github.com/alibaba/higress/tree/v2.2.5)
- [higress-standalone 仓库](https://github.com/higress-group/higress-standalone)
- [源码阅读指引](https://higress.ai/docs/latest/dev/code/)
- [Higress 组件编译说明](https://higress.ai/docs/latest/dev/architecture/)
