## Introduction

[Plugin](/docs/CS/Framework/Higress/Plugin.md) 回答插件怎么配，这一页回答插件怎么跑起来：CR 里哪些字段决定 wasm 二进制从哪来，控制器把它翻译成什么，pilot 看到的 `WasmPlugin` 由哪几处拼成，独立部署又为什么能把 OCI 直拉换成本地 HTTP。基准是主仓 v2.2.5（`4deae1dd`）与 standalone aio-v2.2.5（`36882509`）。

承载机制的源码直接抄在正文里，读者不必另开编辑器。`路径:行号` 只作回查用的出处，代码块节选处用 `// ...` 标出省略行。

证据边界得先说清。控制面前四步、产物字段、取件规范、发布供应链都能在本机两份源码里逐行核对。ECDS 订阅、pilot-agent 拦截与解包住在 fork 里，而 `.gitmodules` 声明的 `istio/istio`、`istio/proxy`、`envoy/envoy` 都是未 checkout 的空目录（`find istio -type f` 为 0），`envoy/` 整棵为空，后面几步只能沿用官方文档口径。符号图在这页只用于构造点普查；`calls` 边按名称解析会误连，口径见 [Call Graph Internals](/docs/CS/Framework/Higress/Call_Graph_Internals.md)。

## WasmPlugin CRD

`api/extensions/v1alpha1/wasmplugin.proto` 只有一张 message，字段分成两组：代码从哪来、生效策略怎么定。`:29-37` 的 cue-gen 注释固定了 `extensions.higress.io/v1alpha1`、Namespaced、status 子资源，并对 `pluginConfig` / `defaultConfig` / `matchRules.[].config` 开 `preserveUnknownFields`，插件配置因此可以塞任意 JSON，apiserver 不校验结构。

取件策略写在字段注释里，比任何二手说明都直白（`wasmplugin.proto:51-72`，message 后续字段略）：

```protobuf
message WasmPlugin {
  // URL of a Wasm module or OCI container. If no scheme is present,
  // defaults to `oci://`, referencing an OCI image. Other valid schemes
  // are `file://` for referencing .wasm module files present locally
  // within the proxy container, and `http[s]://` for .wasm module files
  // hosted remotely.
  string url = 2;

  // SHA256 checksum that will be used to verify Wasm module or OCI container.
  // If the `url` field already references a SHA256 (using the `@sha256:`
  // notation), it must match the value of this field. If an OCI image is
  // referenced by tag and this field is set, its checksum will be verified
  // against the contents of this field after pulling.
  string sha256 = 3;

  // The pull behaviour to be applied when fetching an OCI image. Only
  // relevant when images are referenced by tag instead of SHA. Defaults
  // to IfNotPresent, except when an OCI image is referenced in the `url`
  // and the `latest` tag is used, in which case `Always` is the default,
  // mirroring K8s behaviour.
  // Setting is ignored if `url` field is referencing a Wasm module directly
  // using `file://` or `http[s]://`
  PullPolicy image_pull_policy = 4;
```

失效策略在另一个 enum（`:208-218`）：

```protobuf
enum FailStrategy {
  // A fatal error in the binary fetching or during the plugin execution causes
  // all subsequent requests to fail with 5xx.
  FAIL_CLOSE = 0;

  // Enables the fail open behavior for the Wasm plugin fatal errors to bypass
  // the plugin execution. A fatal error can be a failure to fetch the remote
  // binary, an exception, or abort() on the VM. This flag is not recommended
  // for the authentication or the authorization plugins.
  FAIL_OPEN = 1;
}
```

`url` 省略 scheme 时默认 `oci://`，另外两种是 `file://`（proxy 容器内的本地 .wasm）与 `http[s]://`（远程 .wasm）。后面几种部署形态的差别都落在这行注释上：standalone 的 `http://localhost:8002/...`、wasm-cpp 文档的 `file:///opt/plugins/.../plugin.wasm` 用的都是 CRD 原生 scheme。`FAIL_CLOSE` 是枚举零值，因而是默认；`FAIL_OPEN` 才放行。

其余字段按组记：`sha256` 校验 OCI 内容或 wasm 字节，`image_pull_secret` 存拉镜像凭据，`verification_key` 是验签用的 PEM 公钥（`:58-82`）；`phase`（`:140-154`）四值 `UNSPECIFIED_PHASE` / `AUTHN` / `AUTHZ` / `STATS`，`priority`（`:95-101`）降序、未设置或同值时按 name + namespace 推导确定顺序；`vm_config`（`:179-206`）只暴露 `env[]`，每项 `value_from` 为 `INLINE`（显式值）或 `HOST`（透传 istio-proxy 环境变量）。

Higress 的扩展字段从编号 101 起，与 Istio 原生字段错开（`:110-116`）：`default_config` / `match_rules` / `default_config_disable`。`MatchRule`（`:119-127`）有 `ingress` / `domain` / `service` 三组匹配值、`config` / `config_disable`，以及 `route_type`（`:131-137`：HTTP=0、GRPC=1）。

## Control Plane: From CR to xDS

`pkg/ingress/kube/wasmplugin/controller.go:35-49` 是很薄的一层：`WatchNamespace` 为空就用全局 informer，否则用 `NewWasmPluginInformer` 限定 ns；`GetWasmPlugin` 只做 lister 按 ns/name 取对象。插件专有逻辑一行都没有。

```go
func NewController(client kubeclient.Client, options common.Options) WasmPluginController {
	var informer cache.SharedIndexInformer
	if options.WatchNamespace == "" {
		informer = client.HigressInformer().Extensions().V1alpha1().WasmPlugins().Informer()
	} else {
		informer = client.HigressInformer().InformerFor(&v1.WasmPlugin{}, func(client versioned.Interface, resyncPeriod time.Duration) cache.SharedIndexInformer {
			return informersv1.NewWasmPluginInformer(client, options.WatchNamespace, resyncPeriod, nil)
		})
	}
	return controller.NewCommonController("wasmplugin", listersv1.NewWasmPluginLister(informer.GetIndexer()), informer, GetWasmPlugin, options.ClusterId)
}
```

行为都在 `pkg/ingress/config/ingress_config.go`。`:222-225` 把 `AddOrUpdateWasmPlugin` / `DeleteWasmPlugin` 注册为事件回调，`:260-261` 对 `gvk.WasmPlugin` 收集 handler，`:290-327` 的 `List` 白名单六类并在合并后跑 `templateProcessor.ProcessConfig`，`:2095` / `:2116` 分别负责 `Run` 与 `HasSynced` 的就绪门禁。

改坏配置会发生什么，看 `AddOrUpdateWasmPlugin:1351` 的执行顺序就够，不必再猜（完整函数）：

```go
func (m *IngressConfig) AddOrUpdateWasmPlugin(clusterNamespacedName util.ClusterNamespacedName) {
	if clusterNamespacedName.Namespace != m.namespace {
		return
	}
	wasmPlugin, err := m.wasmPluginLister.WasmPlugins(clusterNamespacedName.Namespace).Get(clusterNamespacedName.Name)
	if err != nil {
		IngressLog.Errorf("wasmPlugin is not found, namespace:%s, name:%s",
			clusterNamespacedName.Namespace, clusterNamespacedName.Name)
		return
	}
	metadata := config.Meta{
		Name:             clusterNamespacedName.Name + "-wasmplugin",
		Namespace:        clusterNamespacedName.Namespace,
		GroupVersionKind: gvk.WasmPlugin,
		// Set this label so that we do not compare configs and just push.
		Labels: map[string]string{constants.AlwaysPushLabel: "true"},
	}
	for _, f := range m.wasmPluginHandlers {
		IngressLog.Debug("WasmPlugin triggered update")
		f(config.Config{Meta: metadata}, config.Config{Meta: metadata}, istiomodel.EventUpdate)
	}
	istioWasmPlugin, err := m.convertIstioWasmPlugin(&wasmPlugin.Spec)
	if err != nil {
		IngressLog.Errorf("invalid wasmPlugin:%s, err:%v", clusterNamespacedName.Name, err)
		return
	}
	if istioWasmPlugin == nil {
		IngressLog.Infof("wasmPlugin:%s will not be transferred to istio since config disabled",
			clusterNamespacedName.Name)
		m.mutex.Lock()
		delete(m.wasmPlugins, clusterNamespacedName.Name)
		m.mutex.Unlock()
		return
	}
	IngressLog.Debugf("wasmPlugin:%s convert to istioWasmPlugin:%v", clusterNamespacedName.Name, istioWasmPlugin)
	m.mutex.Lock()
	m.wasmPlugins[clusterNamespacedName.Name] = istioWasmPlugin
	m.mutex.Unlock()
}
```

广播在转换之前，且合成 config 只有 Meta、没有 Spec。这意味着三件事：事件只是脏标记，插件内容不随事件传输；转换失败时推送已发出但缓存保留旧值，pilot 是 pull 模型，实际下发什么取决于随后的 `List`；转换返回 nil（禁用默认配置且无有效规则）时删掉缓存却不广播删除事件。`DeleteWasmPlugin:1391` 反过来，同样有 ns 门，且只有缓存命中才广播 `EventDelete`。`McpBridge` 变更在 `:1454-1478` 也会向 `wasmPluginHandlers` 广播合成事件，所以插件重新下发未必由插件 CR 触发。

每次 `List(gvk.WasmPlugin, NamespaceAll)` 由 `WasmPluginGenerator`（`pkg/ingress/mcp/generator.go:151-166`，注册于 `pkg/bootstrap/server.go:387`）拉走。`Generate` 只是一次 `Environment.List`，`GenerateDeltas` 是 `TODO` 并返回 `false`：

```go
func (c WasmPluginGenerator) Generate(proxy *model.Proxy, w *model.WatchedResource,
	updates *model.PushRequest) (model.Resources, model.XdsLogDetails, error) {
	wasmPlugins := c.Environment.List(gvk.WasmPlugin, model.NamespaceAll)
	return generate(proxy, wasmPlugins, w, updates, c.GeneratorOptions.KeepConfigLabels, c.GeneratorOptions.KeepConfigAnnotations)
}

func (c WasmPluginGenerator) GenerateDeltas(proxy *model.Proxy, push *model.PushContext, updates *model.PushRequest,
	w *model.WatchedResource) (model.Resources, []string, model.XdsLogDetails, bool, error) {
	// TODO: delta implement
	return nil, nil, model.DefaultXdsLogDetails, false, nil
}
```

插件因此永远走全量 SotW，没有增量通道。

## Three Sources of WasmPlugin Resources

全仓 `pkg/` + `registry/` 非测试代码里 `extensions.WasmPlugin{` 共 3 处，正好对应 `List` 的三条来源：

| # | 构造点 | 触发 | 关键字段 |
| --- | --- | --- | --- |
| ① | `ingress_config.go:1200` `convertIstioWasmPlugin` | 用户 / 控制台写 Higress `WasmPlugin` CR | 直拷 url/sha256/策略，塞 gateway selector；把 `defaultConfig` + `matchRules` 压成 `pluginConfig._rules_` |
| ② | `registry/memory/cache.go:115` | MCP Server 规则写入 registry | Name `istio-autogenerated-mcp-wasmplugin`，`Priority 999`、`FAIL_OPEN`、`ImagePullPolicy: Always`、Url 取 `MCP_SERVER_WASM_IMAGE_URL` |
| ③ | `ingress_config.go:433` `convertBuiltinInferenceEndpointPicker` | Gateway API `InferencePool` 路由且 mode=builtin | Name `higress-internal-ai-endpoint-picker`，`PluginName: ai-endpoint-picker`、`FAIL_OPEN`、`_rules_` 只含 `_match_route_` |

① 的产物存在 `m.wasmPlugins` map 里，`convertWasmPlugin:907-927` 逐项输出（未排序），随后追加 `RegistryReconciler.GetAllConfigs(gvk.WasmPlugin)` 即 ②：

```go
func (m *IngressConfig) convertWasmPlugin([]common.WrapperConfig) []config.Config {
	m.mutex.RLock()
	defer m.mutex.RUnlock()
	out := make([]config.Config, 0, len(m.wasmPlugins))
	for name, wasmPlugin := range m.wasmPlugins {
		out = append(out, config.Config{
			Meta: config.Meta{
				GroupVersionKind: gvk.WasmPlugin,
				Name:             name,
				Namespace:        m.namespace,
			},
			Spec: wasmPlugin,
		})
	}
	// add wasm plugin from nacos for mcp server
	if m.RegistryReconciler != nil {
		wasmFromMcp := m.RegistryReconciler.GetAllConfigs(gvk.WasmPlugin)
		for _, cfg := range wasmFromMcp {
			out = append(out, *cfg)
		}
	}
	return out
}
```

① 的转换函数决定了 CR 最终长什么样。`ingress_config.go:1199-1231` 先直拷字段、塞 selector，然后立刻检查 `pluginConfig`：非空就返回，`matchRules` 一眼都不看：

```go
func (m *IngressConfig) convertIstioWasmPlugin(obj *higressext.WasmPlugin) (*extensions.WasmPlugin, error) {
	result := &extensions.WasmPlugin{
		Selector: &istiotype.WorkloadSelector{
			MatchLabels: map[string]string{
				m.commonOptions.GatewaySelectorKey: m.commonOptions.GatewaySelectorValue,
			},
		},
		Url:             obj.Url,
		Sha256:          obj.Sha256,
		ImagePullPolicy: extensions.PullPolicy(obj.ImagePullPolicy),
		ImagePullSecret: obj.ImagePullSecret,
		VerificationKey: obj.VerificationKey,
		PluginConfig:    obj.PluginConfig,
		PluginName:      obj.PluginName,
		Phase:           extensions.PluginPhase(obj.Phase),
		FailStrategy:    extensions.FailStrategy(obj.FailStrategy),
		Priority:        obj.Priority,
	}
	if obj.VmConfig != nil {
		result.VmConfig = &extensions.VmConfig{}
		for _, env := range obj.VmConfig.Env {
			result.VmConfig.Env = append(result.VmConfig.Env, &extensions.EnvVar{
				Name:      env.Name,
				ValueFrom: extensions.EnvValueSource(env.ValueFrom),
				Value:     env.Value,
			})
		}
	}
	if result.PluginConfig != nil {
		return result, nil
	}
	if !isBoolValueTrue(obj.DefaultConfigDisable) {
		result.PluginConfig = obj.DefaultConfig
	}
	hasValidRule := false
	// ... 逐条 MatchRule 生成 _match_route_ / _match_service_ / _match_domain_
```

否则把 `defaultConfig` 当全局配置，逐条规则把匹配值写进四个下划线键，最后塞进 `_rules_`（`:1320-1344`）：

```go
			if validRule {
				ruleValues = append(ruleValues, &_struct.Value{
					Kind: v,
				})
			} else {
				return nil, fmt.Errorf("invalid match rule has no match condition, rule:%v", rule)
			}
		}
		if len(ruleValues) > 0 {
			hasValidRule = true
			result.PluginConfig.Fields["_rules_"] = &_struct.Value{
				Kind: &_struct.Value_ListValue{
					ListValue: &_struct.ListValue{
						Values: ruleValues,
					},
				},
			}
		}
	}
	if !hasValidRule && isBoolValueTrue(obj.DefaultConfigDisable) {
		return nil, nil
	}
	return result, nil
}
```

四个键 `_match_route_`（`:1276`）、`_match_service_`（`:1295`）、`_match_domain_`（`:1314`）、`_rules_`（`:1332`）全是内联字符串字面量，本仓没有导出常量；控制面只负责压缩，语义解释在插件侧。某条规则的三个匹配条件全空会让整份 CR 翻译失败，配合前面的广播顺序就成了「旧配置继续生效」。另有一处值得单独记：`:1265-1267` 对非 HTTP 型规则做 `path.Join(rule.GetRouteType().String())`，单参数 Join 等于只留路由类型，原始 ingress 值被丢弃。

② 不是用户写的 CR，而是 registry 把 MCP 规则攒成的一份自动插件（`registry/memory/cache.go:93-131`）：

```go
if kind == gvk.WasmPlugin {
	pluginConfig := &registry.WasmPluginConfig{}
	var ns string
	for _, cfg := range cfgs {
		ns = cfg.Namespace
		rule := cfg.Spec.(*registry.McpServerRule)
		pluginConfig.Rules = append(pluginConfig.Rules, rule)
	}
	// ... json.Marshal → protojson.Unmarshal 成 structpb.Struct
	wasmPlugin := &extensions.WasmPlugin{
		ImagePullPolicy: extensions.PullPolicy_Always,
		Phase:           extensions.PluginPhase_UNSPECIFIED_PHASE,
		Priority:        &wrapperspb.Int32Value{Value: 999},
		PluginConfig:    pbs,
		Url:             higressconfig.McpServerWasmImageUrl,
		FailStrategy:    extensions.FailStrategy_FAIL_OPEN,
	}
	return map[string]*config.Config{"wasm": {
		Meta: config.Meta{
			GroupVersionKind: gvk.WasmPlugin,
			Name:             "istio-autogenerated-mcp-wasmplugin",
			Namespace:        ns,
		},
		Spec: wasmPlugin,
	}}
}
```

③ 走 `listFromGatewayControllers` 的独立分支，从各 VirtualService 的 `Extra[ConfigExtraPerRouteRuleInferencePoolConfigs]` 挑出 `Mode == builtin` 的路由名，排序后生成一份只含 `_match_route_` 的 `_rules_`；没有这类路由就返回 nil。URL 不写在 CR 里，两类内置插件的地址都来自环境变量（`pkg/config/envs.go:26-31`）：

```go
McpServerWasmImageUrl = env.RegisterStringVar("MCP_SERVER_WASM_IMAGE_URL",
	"oci://higress-registry.cn-hangzhou.cr.aliyuncs.com/mcp-server/all-in-one:1.0.0", "").Get()
AIEndpointPickerPluginURL = env.RegisterStringVar(
	"AI_ENDPOINT_PICKER_PLUGIN_URL",
	"oci://higress-registry.cn-hangzhou.cr.aliyuncs.com/plugins/ai-endpoint-picker:2.0.1",
	"OCI URL of the ai-endpoint-picker plugin injected for built-in Gateway API inference routing",
).Get()
```

所以「pilot 里的 `WasmPlugin` 就是用户写的 CR」这个理解漏了两类内置产物。实际取的是 CR 转换结果、MCP 自动插件、Gateway API 内置插件三者的并集，合并后还会被模板处理器改写。符号图里与 WasmPlugin 命名节点相关的边有 `contains 482` / `references 148` / `calls 118` / `instantiates 94` / `implements 68` / `imports 46`，但 `ingress_config.go` 内真正 calls 到 WasmPlugin 命名目标的只有 3 条（`:376` / `:1355` / `:1372`）。边计数不能当调用次数。

## Binary Acquisition and ECDS

官方文档给出的九步链路：CR 更新 → 控制面转 Istio `WasmPlugin` → MCP over XDS 推给 Discovery → ADS/LDS 下发 → Envoy 以 ECDS 订阅（`config_discovery` + `default_config: Composite` + `apply_default_config_without_warming: true`）→ pilot-agent 拦截 ECDS 响应、按 OCI 配置拉取 → 解包 wasm → 把响应里的地址改写成本地路径 → Envoy 加载本地文件。Listener 里只放订阅桩，热更新才不必重启、不必断连接。

本机源码能补的是最终加载形态：`docs/developers/wasm-runtime-verification/envoy.yaml:38-55` 给了一份最小静态配置，也是 pilot-agent 把 code 改写成本地路径之后的落地结果（为便于阅读去掉了外层缩进）：

```yaml
http_filters:
  - name: envoy.filters.http.wasm
    typed_config:
      "@type": type.googleapis.com/envoy.extensions.filters.http.wasm.v3.Wasm
      config:
        name: local-verification-plugin
        root_id: local-verification-plugin
        configuration:
          "@type": type.googleapis.com/google.protobuf.StringValue
          value: "{}"
        vm_config:
          vm_id: local-verification-plugin
          runtime: envoy.wasm.runtime.v8
          code:
            local:
              filename: /etc/envoy/main.wasm
  - name: envoy.filters.http.router
    typed_config:
      "@type": type.googleapis.com/envoy.extensions.filters.http.router.v3.Router
```

这份配置不走 ECDS，是本地验证用的。`Config_Pipeline.md` 里记的 basic-auth 注入（`envoy.wasm.runtime.null` + 内联 code）是第三种形态：翻译层直接造 EnvoyFilter，ECDS 和镜像都不经过。三种形态里 Envoy 都只面对本地字节或本地 VM，区别在于谁去取、什么时候取。第 5~9 步的 fork 源码本机无工作树，见 Unverified。

## Two OCI Layouts

v2.2.5 仓里有两套镜像规范，字段和层数互不相容。谈规范前得先说清是哪一套，否则把开发镜像的 mediaType 套到官方产物上就会出错。

A 是 `hgctl` 本地开发规范。`hgctl/pkg/plugin/build/templates.go:44-56` 的构建脚本把 TinyGo 产物打成 tar.gz，作为最后一层追加到 `oras push` 命令里；`spec.yaml` / `README*.md` / `icon.png` 各占一层，mediaType 一一对应（`build.go:48-53`、`:425-441`）：

```bash
go mod tidy
tinygo build -o {{ .BuildDestDir }}/plugin.wasm -scheduler=none -gc=custom -tags='custommalloc nottinygc_finalizer' -target=wasi {{ .BuildSrcDir }}

cd {{ .BuildDestDir }}
tar czf plugin.tar.gz plugin.wasm
cmd="{{ .BasicCmd }}"
products=({{ .Products }})
for ((i=0; i<${#products[*]}; i=i+2)); do
  f=${products[i]}
  typ=${products[i+1]}
  if [ -e ${f} ]; then
    cmd="${cmd} ./${f}:${typ}"
  fi
done
cmd="${cmd} ./plugin.tar.gz:{{ .MediaTypePlugin }}"
eval ${cmd}
```

`BasicCmd` 就是 `oras push <dest> ./spec.yaml:<type> ./README.md:<type>`（`build.go:446`）。最后一层装的是 tar.gz，里面才是 wasm，这是 TinyGo 路径。另有 `plugins/wasm-go/Dockerfile:26-29` 的纯二进制路径：`FROM scratch` + `COPY --from=builder /main.wasm plugin.wasm`，配 `Makefile` 的 `GOOS=wasip1 GOARCH=wasm go build`，也就是 Go 1.24 换代后的正式编译方式。

B 是官方不可变发布规范（`docs/developers/immutable-plugin-releases.md:90-93`、`:181-196`），严格两层，没有 spec/README/icon 层。文档把门禁的理由写得很明确：

```text
- **Structural.** The pulled manifest must be a canonical OCI v1.0 schema 2
  image manifest in the deterministic two-layer form Envoy loads: the
  empty-JSON config descriptor, exactly four provenance annotations (`created`,
  `revision`, `version`, `io.higress.plugin.input-hash`), layer 0 `config.json`
  with media type `application/vnd.module.wasm.config.v1+json`, and layer 1
  `plugin.wasm` with media type
  `application/vnd.module.wasm.content.layer.v1+wasm`. Every descriptor size and
  digest must equal the pulled bytes, and `config.json` must be the canonical
  empty JSON object. This is the defect class behind the one-layer `latest`
  incident this change responds to: such a manifest is not loadable by Envoy,
  and the gate rejects it.
- **Compile level.** The pulled `plugin.wasm` bytes are compiled with wazero
  (`CompileModule`, interpreter backend) and the compiled module's exports are
  inspected: exported memory, exact `(i32,i32)->i32` signatures for
  `proxy_on_vm_start` and `proxy_on_configure`, and a `proxy_abi_version_0_2_*`
  export with signature `()->()`.

The module is compiled but never instantiated, so no plugin code executes. The
gate proves that the registry serves a well-formed, digest-consistent,
compilable Proxy-Wasm module; it does not prove that the plugin initializes
inside Envoy or serves a request.
```

`created` 固定为源码 commit 时间。`:198` 特别声明只编译不实例化、不执行插件代码，也不证明在 Envoy 里能初始化。A 用于 `hgctl plugin build/install` 与教程里的开发者镜像，B 用于官方 `plugins/<name>:<VERSION>` 产物。

## Immutable Release Supply Chain

B 规范的约束力来自仓库内一条快照流水线：

| 文件 | 内容（v2.2.5 实测） |
| --- | --- |
| `plugins/release/catalog.json` | 54 个插件条目（53 go + 1 rust），其中 `releaseEligible=true` 44 个；声明 `consoleMarketplace`、`sharedInputGroups`、`consumerInventories`、`artifactInputs` |
| `plugins/release/snapshots/2.2.5.json` | 43 项（42 go + 1 rust）：`provenanceMode` 为 candidate 40 / public 3，36 项版本 `2.0.3`；每项带 `ociRef` + `digest` + `inputHash` + `sourceCommit` |
| `plugins/release/plans/2.2.5.json`、`evidence/2.2.5.json`、`bootstrap-evidence/`、`console-recovery/` | plan / 证据 / 首次发布 bootstrap / console 恢复记录 |

快照的一项长这样（`ai-context-limit`，原样贴出）。digest 与源码 commit 把产物钉死，console 消费方要读的 spec/README 也按文件摘要列在对象里：

```json
{
  "logicalId": "ai-context-limit",
  "implementation": "go",
  "sourceDir": "plugins/wasm-go/extensions/ai-context-limit",
  "image": "plugins/ai-context-limit",
  "version": "1.0.0",
  "ociRef": "higress-registry.cn-hangzhou.cr.aliyuncs.com/plugins/ai-context-limit:1.0.0",
  "digest": "sha256:2a86d8826d20a35b88af498276589392ef9de3756bb250b91cabe0beba658dc1",
  "inputHash": "sha256:e2e73f72b87c9dbf47d763e287d7a4e6bfaa405cf27e2283020034a4cf7c1b74",
  "sourceCommit": "2b837c0ada8dbfb3e4bd92fc3f18ea532d269cb1",
  "candidateRef": "",
  "provenanceMode": "public",
  "consumers": {
    "console": {
      "propertyKey": "ai-context-limit",
      "resourceDir": "ai-context-limit",
      "urlForm": "oci",
      "marketplace": {
        "repository": "higress-group/higress",
        "files": [
          {
            "sourcePath": "plugins/release/console/ai-context-limit/spec.yaml",
            "targetPath": "spec.yaml",
            "sha256": "4507454263642ba71290f11a59905850054c868a22228f812a33c4fdb3f3e82e"
          },
          {
            "sourcePath": "plugins/wasm-go/extensions/ai-context-limit/README.md",
            "targetPath": "README.md",
            "sha256": "64613bf129cf37f9a5a25beeb044a6e0364907f884819842ae7ef1538e4e18b2"
          },
          {
            "sourcePath": "plugins/wasm-go/extensions/ai-context-limit/README_EN.md",
            "targetPath": "README_EN.md",
            "sha256": "b57b8beca499787203ad73ea05388ed5a16b7ccbe5790a07252aeb0e0dc55ce7"
          }
        ]
      }
    }
  }
}
```

快照里 43 项全部有 console consumer（`urlForm` 全是 `oci`），35 项另有一个 pluginServer consumer，形如 `{"inventoryKey": "opa", "httpPath": "opa"}`，这就是静态 HTTP 目录里的路径来源。`docs/developers/immutable-plugin-releases.md:107-174` 给出的顺序：冻结 commit → prepare 生成 plan/snapshot PR（人工门 1）→ promote 发布不可变版本 tag 与受保护环境批准的 `latest`（人工门 2）→ 从精确 snapshot 与精确 plugin-server commit 构建 `higress/plugin-server:<gateway-version>` → dispatch 给 Console 生成 pluginLock → Higress release PR → Standalone dispatch。

`.github/workflows/build-plugin-server-from-snapshot.yaml` 固定了内置插件的来源：`:62-97` 校验 snapshot 路径、SHA-256、plan、previous snapshot 与 `verify-snapshot --resolve --oci-source candidate`；`:151-152` 把快照复制成 `plugin-server/snapshot.json` 并复验摘要；`:82-84` 要求源仓有 `pull_plugins.py` / `unmanaged-plugins.lock.json` 并通过单测；`:199-207` 检查镜像的四个不可变 label（`org.opencontainers.image.revision` / `io.higress.higress-source-commit` / `io.higress.plugin-snapshot-sha256` / `io.higress.gateway-version`）并从容器里取 `plugins/snapshot-inventory.json` 验证实际 served bytes；`:243-265` 才把快照 dispatch 给 Console。plugin-server 因此是按 digest 从 OCI 拉取、再摊平成静态 HTTP 目录的构建产物，与插件仓库无关。

`docs/developers/immutable-plugin-releases.md:449-451` 还点明更新语义的差别：紧急同版本覆盖能立刻修好按 tag 拉取（Envoy-direct）的消费方，已打包的 plugin-server 与 Console 镜像只能等下一个 gateway release 才被 heal。

## Local HTTP Channel

同一套静态目录，三种部署形态的默认开关各不相同：

| 形态 | 开关 | 端口 | URL 模板 |
| --- | --- | --- | --- |
| Helm / K8s | `helm/core/values.yaml:16` 的 `enablePluginServer: false`（默认关）；两个 template 都按它条件渲染；`values.yaml:837-848` 给 replicas 2、容器 8080、Service port 80 | 8080 | 由 Console 自定义 pattern 决定 |
| all-in-one | `all-in-one/scripts/base.sh:68-77` 默认 on（`bin/configure.sh:25` `DEFAULT_USE_PLUGIN_SERVER="Y"`）；`start-plugin-server.sh:8-11` 关闭时直接退出；`supervisord.conf:21-31` 该 program priority 50 | 8002 | `http://localhost:8002/plugins/${name}/${version}/plugin.wasm` |
| Docker Compose | `bin/configure.sh:652-666` 把 `plugin-server` 加入 `COMPOSE_PROFILES`；`compose/.env:1` 默认已含该 profile | 8080 | `http://plugin-server:8080/plugins/${name}/${version}/plugin.wasm` |

all-in-one 的静态目录由一段极简 nginx 配置提供（`all-in-one/plugin-server/nginx.conf`），没有反向代理、没有动态路由，只有 `/healthz`：

```nginx
server {
    listen 8002;
    server_name localhost;

    # Static files root directory
    root /usr/share/nginx/html;

    # Hide Nginx version
    server_tokens off;

    # Health check endpoint
    location = /healthz {
        return 200 'ok';
        add_header Content-Type text/plain;
    }
}
```

镜像来源是 `all-in-one/Dockerfile:11,19,47`：`FROM ${PLUGIN_SERVER_IMAGE}`（带 sha256 digest）后 `COPY --from=plugin-server /usr/share/nginx/html/plugins /usr/share/nginx/html/plugins`。URL 改写发生在两个启动脚本，条件都是「开关打开且用户没自定义」：

```bash
# all-in-one/scripts/start-console.sh:33-36
if [ "$USE_PLUGIN_SERVER" == "on" -a -z "$HIGRESS_ADMIN_WASM_PLUGIN_CUSTOM_IMAGE_URL_PATTERN" ]; then
    HIGRESS_ADMIN_WASM_PLUGIN_CUSTOM_IMAGE_URL_PATTERN="http://localhost:8002/plugins/\${name}/\${version}/plugin.wasm"
fi
export HIGRESS_ADMIN_WASM_PLUGIN_CUSTOM_IMAGE_URL_PATTERN

# all-in-one/scripts/start-controller.sh:23-26
if [ "$USE_PLUGIN_SERVER" == "on" -a -z "$MCP_SERVER_WASM_IMAGE_URL" ]; then
    MCP_SERVER_WASM_IMAGE_URL="http://localhost:8002/plugins/mcp-server/2.0.3/plugin.wasm"
fi
export MCP_SERVER_WASM_IMAGE_URL
```

Compose 侧对应 `docker-compose.yml:136`（controller）与 `:261`（console），值来自 `compose/.env:21-22`；`:206` 让 gateway 依赖 plugin-server healthy。

内置插件的 CR 不在镜像里，是启动时写进文件树的。`all-in-one/scripts/config-template/ai-gateway.sh:357-434` 往 `/data/wasmplugins/` 写三份 Higress `WasmPlugin` YAML：`ai-proxy.internal`（UNSPECIFIED / 100）、`ai-statistics-1.0.0`（UNSPECIFIED / 900）、`model-router.internal`（AUTHN / 900）。第一份长这样：

```yaml
apiVersion: extensions.higress.io/v1alpha1
kind: WasmPlugin
metadata:
  annotations:
    higress.io/wasm-plugin-title: AI Proxy
  labels:
    higress.io/resource-definer: higress
    higress.io/wasm-plugin-built-in: "true"
    higress.io/wasm-plugin-category: ai
    higress.io/wasm-plugin-name: ai-proxy
    higress.io/wasm-plugin-version: 1.0.0
  name: ai-proxy.internal
  namespace: higress-system
  resourceVersion: "1"
spec:
  defaultConfig:
    providers:${AI_PROXY_PROVIDERS}
  defaultConfigDisable: false
  matchRules:${AI_PROXY_MATCH_RULES}
  failStrategy: FAIL_OPEN
  phase: UNSPECIFIED_PHASE
  priority: 100
  url: http://localhost:8002/plugins/ai-proxy/1.0.0/plugin.wasm
```

`start-apiserver.sh:41` 用 `--storage file --file-root-dir /data` 启动 apiserver，这些 YAML 就是 file 后端的 CR 对象；控制器经 kubeconfig 读它们，路径与 [Standalone and All-in-One](/docs/CS/Framework/Higress/Standalone_and_AllInOne.md) 记的 100ms fsnotify 去抖衔接。standalone 换掉的是三样东西：OCI registry 变成本地 nginx 静态目录，拉镜像的 pilot-agent 变成直接 HTTP GET .wasm，CR 存储从 etcd 变成文件树。控制面翻译代码没有改动。

`all-in-one/get-ai-gateway.sh:90-126` 的 `detectPluginRegistry()` 是另一条独立选择，按时区把 `PLUGIN_REGISTRY` 选成杭州 / 新加坡 / 美西，默认杭州；它决定关掉 plugin-server 时去哪拉 OCI，与本地 HTTP 通道互斥。

## Runtime Configuration Loading

插件进程侧的入口在 `plugins/wasm-go/extensions/ai-proxy/main.go:109-119`：`main()` 是空的，`init()` 把全局配置与规则级配置的解析回调连同各阶段 hook 一起注册给 SDK：

```go
func main() {}

func init() {
	wrapper.SetCtx(
		pluginName,
		wrapper.ParseOverrideConfig(parseGlobalConfig, parseOverrideRuleConfig),
		wrapper.ProcessRequestHeaders(onHttpRequestHeader),
		wrapper.ProcessRequestBody(onHttpRequestBody),
		wrapper.ProcessResponseHeaders(onHttpResponseHeaders),
		wrapper.ProcessStreamingResponseBody(onStreamingResponseBody),
		wrapper.ProcessResponseBody(onHttpResponseBody),
		wrapper.WithRebuildMaxMemBytes[config.PluginConfig](200*1024*1024),
	)
}
```

宿主在 VM 启动时把 `pluginConfig` 交给这两个回调；`_rules_` 里的 `_match_route_` / `_match_domain_` / `_match_service_` 由 SDK 在请求阶段按 `:authority` / `route_name` / `cluster_name` 选择生效的那份。控制面只负责把 CR 压成这四个下划线键，语义解释全在插件侧。

有一处路径要订正：v2.2.5 的 `plugins/wasm-go/pkg/` 下只有 `mcp/` 与 `pathutil/` 两个 module，没有 `matcher/rule_matcher.go`。`plugins/wasm-go/go.mod` 的 SDK 依赖指向外部仓 `github.com/higress-group/proxy-wasm-go-sdk` 与 `github.com/higress-group/wasm-go`，扩展实际 import 的是 `.../pkg/wrapper` 与 `.../pkg/log`。`rule_matcher.go` 属于外部 SDK 仓或更早的源码布局，本机无工作树可核，运行时匹配细节因此不在这页的证据范围内。

## Failure and Update Semantics

失效行为分散在几层，排障时按层查这张表：

| 层 | 行为 | 证据 |
| --- | --- | --- |
| CR 校验 | CR 放到非 `higress-system`（控制器自身 ns）→ 事件静默忽略 | `ingress_config.go:1352` / `:1392` |
| CR 校验 | `spec.pluginConfig` 非空 → `matchRules` 完全不看 | `:1227-1229` |
| CR 校验 | 某条 rule 的 ingress/domain/service 全空 → 整份翻译失败 | `:1322-1328` |
| 翻译 | 失败只打 error，广播已发出、缓存保留旧值，旧配置继续生效 | `:1368-1375` |
| 翻译 | `route_type != HTTP` 时 `path.Join(rule.GetRouteType().String())` 是单参数 Join，原始 ingress 值被丢弃 | `:1265-1267` |
| 推送 | 合成事件带 `AlwaysPushLabel`，pilot 不比较内容直接 push；`GenerateDeltas` 恒 false，全量 SotW | `:1366` / `generator.go:163-166` |
| 取件 | `file://` / `http://` 忽略 `imagePullPolicy`；`latest` 默认 `Always`；`FAIL_CLOSE` 默认取件失败即 5xx | `wasmplugin.proto:65-72` / `:208-218` |
| 发布 | 单层 / 结构不合规的镜像被 pull gate 拒绝；已打包的 plugin-server 与 Console 镜像只能靠下次 gateway release 更新 | `immutable-plugin-releases.md:189-191` / `:449-451` |

## Unverified

- ECDS 与 pilot-agent 的拦截/解包/改写代码：`istio/istio`、`istio/proxy`、`envoy/envoy` 三个 submodule 均未 checkout（本机 0 文件），九步链路的第 5~9 步只有官方文档口径；`WASM_INSECURE_REGISTRIES` 在 Helm 模板与本机源码中均未 grep 到，只有文档站说明。
- `higress-console` 仓的 pluginLock 落地：主仓 workflow 只证明"把 snapshot dispatch 给 Console、等含该 lock 的 chart 发布"；本机没有 console 工作树，`plugins.properties` 的 `1.0.0` / `latest` 旧口径是否仍与 snapshot lock 并存，未逐行核对。
- 外部 SDK 的 matcher 实现：`github.com/higress-group/wasm-go` 不在本仓，四级匹配的优先级细节（数组顺序优先、通配规则）来自文档站，未在本机源码复核。
- plugin-server 源仓的 `pull_plugins.py` 与 `unmanaged-plugins.lock.json`：主仓 workflow 只检查它们存在并跑单测，解包与 inventory 生成的具体实现未读。
- 两套 OCI 规范在 Envoy 侧的兼容边界：B 规范明说单层不可加载，但 A 规范的多层镜像由谁剥掉 spec/README/icon、是否同一段 pilot-agent 代码处理，本机无法证明。
- `catalog.json` 44 个 releaseEligible 与 snapshot 43 项之间的差额：文档提到 migration-excluded 与 alpha deferred 两种排除机制，但未逐项核对 2.2.5 具体排除的是哪个插件；表中两个数字都是实测，不推断原因。
- 模板处理器对 WasmPlugin 的实际改写范围：`List:300-327` 确认会跑 `ProcessConfig`，但哪些字段可被模板替换、与 `_rules_` 下划线键是否冲突，未逐例验证。

## Links

- [Config Pipeline](/docs/CS/Framework/Higress/Config_Pipeline.md)
- [Source Map](/docs/CS/Framework/Higress/Source_Map.md)
- [Service Registry Internals](/docs/CS/Framework/Higress/Service_Registry_Internals.md)
- [Deployment and Ops](/docs/CS/Framework/Higress/Deployment_and_Ops.md)
- [Higress](/docs/CS/Framework/Higress/Higress.md)
- [WasmPlugin](/docs/CS/Framework/Istio/WasmPlugin.md)

## References

- [Higress v2.2.5 源码](https://github.com/alibaba/higress/tree/v2.2.5)
- [higress-standalone 仓库](https://github.com/higress-group/higress-standalone)
- [Wasm 插件镜像规范](https://higress.ai/docs/latest/user/wasm-image-spec/)
- [Wasm 生效原理](https://higress.ai/docs/latest/user/plugins/wasm-dev/wasm19/)
- [基于 Docker Compose 进行独立部署](https://higress.ai/docs/latest/ops/deploy-by-docker-compose/)
- [hgctl 工具使用说明](https://higress.ai/docs/latest/ops/hgctl/)
