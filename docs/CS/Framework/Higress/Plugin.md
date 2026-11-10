## Introduction

Higress 把"扩展能力"压成一个模型：插件就是 Envoy HTTP filter 链里的一个 Wasm 模块，由 `WasmPlugin` CRD 声明、以 OCI 镜像分发、经 ECDS 热加载。本页是插件子系统的总入口，覆盖三块：

- **插件体系**：官方清单到底多少、作用域为什么有两套口径、多个插件谁先跑、以及"不重启就换插件"怎么做到。
- **插件开发**：Go SDK 的真实 API 名、外部 HTTP / Redis 寻址、Go 1.24 编译换代、Wasm 运行时模型。
- **AI 插件家族**：`ai-proxy` 协议转换、key 池 / 故障转移、模型负载均衡、token 限流配额、语义缓存、内容安全与脱敏、MCP 托管、AI 可观测。

不在本页的内容：AI 网关的产品定位、控制台路由层（模型级 Fallback 只在那一层）、网关内置 MCP Server Filter 与 McpBridge、HiMarket 平台——这些在 [AI Gateway](/docs/CS/Framework/Higress/AI_Gateway.md)。源码级模块地图（含约 89 个注解相对 key 的逐项清单与前缀行为）在 [Source Map](/docs/CS/Framework/Higress/Source_Map.md)；"108 条注解"是文档站流传概数，源码侧无此单一数字。**插件的加载链路**（CR 字段与三种 URL scheme → 控制面翻译 → 三源合并 → OCI / 本地 HTTP 取件 → 不可变发布快照 → 运行时配置解析）单列在 [Plugin Loading Internals](/docs/CS/Framework/Higress/Plugin_Loading_Internals.md)，本页只保留使用口径。

## Official Inventory

官方[插件市场页](https://higress.ai/plugins/)自标 **"共 41 款插件 覆盖 5 个分类"**，与文档站索引 `user/plugins/**` 的 41 条一一对应（`intro` 与 `custom` 是使用说明页，不计入）。旧口径"50+ 官方内置插件"应改为 **41**。

> [!NOTE]
> **"41" 是文档站自标口径，版本匹配的实际发布量更大**：`higress-console` v2.2.5（commit `0279ce1a`）的 `backend/sdk/src/main/resources/plugins/` 下实际有 **52** 个 `spec.yaml`（每个 = 一个 marketplace 插件 manifest），已经包含 wasm-cpp 基础族（`key-auth` / `basic-auth` / `jwt-auth` / `hmac-auth` / `hmac-auth-apisix` / `oauth` / `bot-detect` / `request-block` / `key-rate-limit` / `custom-response` / `model-mapper` / `model-router` 等）与若干文档站未单列的工具类插件（`nginx-rewrite-compatible` / `response-cache` / `log-request-response` / `gw-error-format` / `traffic-editor` / `json-converter` / `de-graphql` 等）。文档站索引与"41"已落后于实际 bundle；统计"官方插件数"以 console 仓的 manifest 数为准，且要区分"marketplace 发布"与"`plugins/wasm-go/extensions/` 里存在但未发布"两类（后者如 `hello-world` / `gc-test` / `test-redis-inject-spin` / `streaming-body-example` / `http-call` / `api-workflow` / `chatgpt-proxy` / `jsonrpc-converter` / `qwen3guard` / `ai-image-reader` / `traffic-editor` / `replay-protection` 共 12 个，不进 marketplace）。

| 分类 | 数量 | 插件 |
| --- | --- | --- |
| AI | 17 | api-provider：`ai-cache`、`ai-prompt-decorator`、`ai-proxy`、`ai-security-guard`；api-consumer：`ai-data-masking`、`ai-quota`、`ai-token-ratelimit`；api-dev：`ai-agent`、`ai-json-resp`、`ai-prompt-template`、`ai-search`；api-o11y：`ai-statistics`、`geo-ip`；others：`ai-history`、`ai-intent`、`ai-rag`、`ai-transformer` |
| 认证鉴权 | 9 | `basic-auth`、`ext-auth`、`hmac-auth`、`hmac-auth-apisix`、`jwt-auth`、`key-auth`、`oauth`、`oidc`、`opa` |
| 安全防护 | 6 | `bot-detect`、`cors`、`ip-restriction`、`replay-protection`、`request-block`、`waf` |
| 流量管理 | 4 | `cluster-key-rate-limit`、`key-rate-limit`、`request-validation`、`traffic-tag` |
| 请求转换 | 5 | `cache-control`、`custom-response`、`de-graphql`、`frontend-gray`、`transformer` |

三条按目录归类会踩空的地方：`request-validation` 在 **traffic** 目录而不是 security；`custom-response` 与 `frontend-gray` 在 **transformation**；`geo-ip` 归在 AI 分类（路径 `api-o11y`）而不是安全。分类只是文档站的信息架构，**不代表执行时机**——时机看 Phase and Priority 一节。

比清单本身更重要的是：文档站索引不等于插件全集。`ai-load-balancer` 是真实存在的 wasm-go 插件，但它的文档页取不到正文、`llms.txt` 里也没有条目，属于"只有仓库 README、没有文档站页面"的那一类；用索引当权威清单会系统性漏能力。

源码侧把这个偏差量化了：`plugins/wasm-go/extensions/` 在 v2.2.5 有 **53** 个目录（其中约 20 个不进文档站，含 `mcp-router`、Go 版 `model-router`、`nginx-rewrite-compatible`、`ai-context-limit`、`ai-endpoint-picker`、`response-cache`、`traffic-editor` 等），而**文档收录的认证基础族根本不在 wasm-go 里**——`key-auth`、`basic-auth`、`jwt-auth`、`hmac-auth`、`oauth`、`bot-detect`、`request-block`、`key-rate-limit`、`custom-response`、`sni-misdirect`、`model-mapper`、`model-router` 都在 **`plugins/wasm-cpp/extensions/`（snake_case 目录，bazel 构建）**，`ai-data-masking` 在 **`plugins/wasm-rust/`**。⇒ 41 与 53 是两个不相等的集合，按"官方插件都用 Go 写的"去找源码会一无所获；完整分布表在 [Source Map](/docs/CS/Framework/Higress/Source_Map.md)。

## Two Scope Systems

"作用域有几级"有两个答案，因为它们说的是两套东西：

**控制台口径是三级**：全局（插件市场）、域名级（域名管理 → 策略）、路由级（路由配置 → 策略），生效优先级 **路由级 > 域名级 > 全局**，且"对于没有匹配到具体路由或域名的请求才会生效全局配置"。一般插件的路由 / 域名级配置字段与全局配置字段**完全一样**；认证类插件是例外——全局级只放 Consumer 凭证与是否开启全局认证，路由 / 域名级只放 `allow`（见 [Security and Auth](/docs/CS/Framework/Higress/Security_and_Auth.md)）。

**CRD 口径多出一级 service**。`WasmPlugin` 在 Higress 侧（`extensions.higress.io/v1alpha1`）扩展的字段，[插件使用简介](https://higress.ai/docs/latest/user/plugins/intro/)的字段表只列了两个：`defaultConfig`（"插件默认配置，全局生效于没有匹配具体域名和路由配置的请求"）与 `matchRules`。但生效原理页的样例里出现了第三种匹配键：

```yaml
matchRules:
  - service: [echo-server.higress-course.svc.cluster.local]
    config:
      ...
```

`convertIstioWasmPlugin`（`pkg/ingress/config/ingress_config.go`）会生成 Istio `WasmPlugin`，其 `pluginConfig` 内出现 `_rules_` 列表，匹配键有三个：`_match_domain_`（域名，支持通配）、`_match_route_`（格式 `命名空间/Ingress名称`）、`_match_service_`（服务，支持通配）。运行时插件在 `OnHttpRequestHeaders` 阶段按当前请求的 `:authority` / `route_name` / `cluster_name` 取对应级别配置。有一处路径要订正：v2.2.5 本仓 `plugins/wasm-go/pkg/` 下只有 `mcp/` 与 `pathutil/` 两个 module，**没有** `matcher/rule_matcher.go`；SDK 来自外部 module `github.com/higress-group/wasm-go`（扩展实际 import `.../pkg/wrapper` 与 `.../pkg/log`），旧资料里的 `rule_matcher.go` / `GetMatchConfig` 属外部 SDK 仓或更早布局，本机无工作树可核。配置解析入口与加载链路见 [Plugin Loading Internals](/docs/CS/Framework/Higress/Plugin_Loading_Internals.md)。

> [!NOTE]
> 两条容易漏掉的规则：① **多条 `matchRules` 按数组书写顺序优先匹配**，不是按特异性；官方建议把 `ingress` 匹配放在 `domain` 之前，控制台就是这么做的。② `configDisable` 与 `defaultConfigDisable` **确实存在**（Go SDK 原理页的 basic-auth 样例里真实出现，分别关闭某条规则与默认配置），但 `intro` 页的字段表没列——引用出处要用后者。

源码侧还有三条只在实现里看得到的规则（`convertIstioWasmPlugin` @ `pkg/ingress/config/ingress_config.go:1199`）：**① `spec.pluginConfig` 与 `matchRules` 互斥且前者优先**——`pluginConfig` 非空时函数直接返回，`matchRules` 完全不看（`:1227-1229`），这条文档没写；**② `matchRules` 某条的 `config` 为 nil 是合法的**（自动补空 struct，`:1245-1249`），但三个匹配条件（ingress / domain / service）**全空会让整份 CR 翻译失败**（`:1322-1328`），且失败后**旧配置继续生效**（`:1373-1375` 只打 error、不动缓存）；**③ `_rules_` / `_match_domain_` / `_match_route_` / `_match_service_` 四个键是内联字符串字面量，没有导出常量**（`:1332/1314/1276/1295`），想在自定义控制器里复用这套约定只能照抄字面量。另外 `spec.phase` 与 `spec.priority` 是 CRD 顶层字段、被原样拷进 Istio 侧（`:1200-1216`），`defaultConfigDisable` / `configDisable` 走 `BoolValue` 三态判定（`:1347-1349`）——**"没写"与"写了 false"不是一回事**。

## Phase and Priority Registry

插件链的顺序由 `WasmPlugin` **顶层**的 `phase` 与 `priority` 决定（注意不是 `matchRules` 项内字段）。`phase` 四个取值对应四个插入点：`UNSPECIFIED_PHASE`（插件过滤器链末端）、`AUTHN`（Istio 认证过滤器之前）、`AUTHZ`（认证之后、授权之前）、`STATS`（授权之后、统计之前）；**同 phase 下 priority 越大越靠前**。

下面这张表是全子树共用的判读件，其它页引用而不重述。

> [!NOTE]
> **phase / priority 的权威源是 `higress-console` 的 marketplace 元数据**（`backend/sdk/src/main/resources/plugins/<name>/spec.yaml`，版本匹配 v2.2.5，commit `0279ce1a`）。本表此前取自官方文档站，与 marketplace 实际下发的默认值有多处不符，已用 console 源逐项订正。**两套源会互相打架**：wasm-go 扩展自己的 `README_EN.md` 也声明 priority（如 `ai-cache` 的 README 写 10），但 marketplace 真正下发的是 800——以 console 元数据为准（它才是 `hgctl` / 控制台安装时实际写入 `WasmPlugin` 的值）。

| 插件 | 阶段 | priority |
| --- | --- | --- |
| `ai-cache` | 默认阶段 | 800 |
| `ip-restriction` | 认证阶段 | 210 |
| `key-auth` | 认证阶段 | 310 |
| `basic-auth` | 认证阶段 | 320 |
| `hmac-auth` | 认证阶段 | 330 |
| `hmac-auth-apisix` | 认证阶段 | 200 |
| `jwt-auth` | 认证阶段 | 340 |
| `oauth` / `oidc` | 认证阶段 | 350 |
| `ext-auth` | 认证阶段 | 360 |
| `frontend-gray` | 默认阶段 | 450 |
| `replay-protection` | 认证阶段 | 800 |
| `ai-data-masking` | 认证阶段 | 991 |
| `key-rate-limit` | 默认阶段 | 10 |
| `cluster-key-rate-limit` | 默认阶段 | 20 |
| `mcp-server` | 默认阶段 | 999 |
| `ai-proxy` | 默认阶段 | 100 |
| `ai-statistics` | 默认阶段 | 900 |
| `opa` | 认证阶段 | 225 |
| `ai-security-guard` | 默认阶段 | 300 |
| `traffic-tag` | 默认阶段 | 400 |
| `ai-token-ratelimit` | 默认阶段 | 600 |
| `ai-quota` | 默认阶段 | 750 |
| `custom-response` | 认证阶段 | 910 |

> [!WARNING]
> **`replay-protection` 未进入 v2.2.5 的 marketplace**（`higress-console` 资源目录下没有该插件），它只作为 wasm-go 扩展存在（README_EN 声明 priority 800）。marketplace 安装列表里看不到它；手动写 `WasmPlugin` 才能用。
> 阶段标签：`认证阶段` = Istio `AUTHN`，`默认阶段` = `UNSPECIFIED_PHASE`（过滤器链末端）；同阶段下 priority 越大越靠前。

这张表重新解释三件反直觉的事——**与旧版结论相反**：`ai-cache` 现在落在**默认阶段 800**，**晚于** `ai-token-ratelimit`（默认 600）和 `ai-quota`（默认 750），即请求**必然先过限流与配额、再进语义缓存**；所谓"缓存命中绕过限流"是旧表把关口错写成认证阶段 10 造成的错觉，真实顺序下缓存省的是后端算力、不绕开限流/配额计数。`ai-data-masking` 在认证阶段末尾（991），所以它跑在 consumer 鉴权之后、但**早于**默认阶段的 `ai-security-guard`（内容安全在默认阶段）；`frontend-gray` 名字在"转换"分类里，实际落在**默认阶段** 450（旧表误标为认证阶段）。写任何"某插件一定生效"的结论前，先回这张表核对它和谁抢顺序。

## Hot Reload via ECDS

热更新的完整链路九步，关键是**Envoy 收到的不是插件配置，而是一个订阅桩**：

1. `WasmPlugin` 资源更新 → 2. Higress Core 转成 Istio `WasmPlugin` → 3. MCP over XDS 推给 Discovery → 4. 经 Pilot Agent 走 ADS/LDS 下发 → 5. **Envoy 通过 ECDS（Extension Config Discovery Service）订阅插件配置**，Listener 里只有 `config_discovery` → 6. Pilot Agent 拦截 ECDS 响应，按 OCI 配置从 Registry Hub 拉镜像 → 7. 解压 wasm 到本地 → 8. 把 ECDS 响应里的地址改写成本地路径 → 9. Envoy 加载本地 wasm 文件。

官方对结果的表述是"Wasm 插件是通过 OCI 实现了 wasm 文件更新，直接热加载，不会导致任何连接中断，业务流量完全无损"。Envoy 侧每个插件条目的形态是 `config_discovery` + `default_config: Composite` + `apply_default_config_without_warming: true`，`type_urls` 含 `envoy.filters.http.wasm.v3.Wasm` 与 `composite.v3.Composite`。插件链生成的 filter 名形如 `higress-system.custom-response`、`higress-system.wasm-keyauth`。

OCI 直拉只是取件通道之一（上面第 6~8 步）。v2.2.5 还有一条 plugin-server 本地 HTTP 通道：把 Console 的 `HIGRESS_ADMIN_WASM_PLUGIN_CUSTOM_IMAGE_URL_PATTERN` 指到 `http://.../plugins/${name}/${version}/plugin.wasm`，CR 的 `url` 就变成 `http[s]://` —— 这是 `api/extensions/v1alpha1/wasmplugin.proto:51-56` 原生支持的 scheme，不是私有扩展；`file://` 同理。Helm 默认**关闭**（`helm/core/values.yaml:16 enablePluginServer: false`），standalone 默认**开启**（all-in-one `localhost:8002`、compose `plugin-server:8080`）。控制面翻译只有一套，差别在二进制怎么取。三源合并、三条 URL scheme、不可变发布供应链与 standalone 的本地托管细节，收在 [Plugin Loading Internals](/docs/CS/Framework/Higress/Plugin_Loading_Internals.md)。

镜像规范有两套，字段和层数互不相容：

- A（`hgctl` / 文档站的开发者规范）。`hgctl/pkg/plugin/build/build.go:48-53` 定义 `spec.yaml` → `application/vnd.module.wasm.spec.v1+yaml`、`README.md` → `...doc.v1+markdown`（多语言 README 与 icon 各有 type，`:425-441` 按存在与否追加）；`:446` 的基准命令是 `oras push`；`templates.go:44-52` 先 `tinygo build -o plugin.wasm`，再 `tar czf plugin.tar.gz plugin.wasm`，最后追加 `./plugin.tar.gz:application/vnd.oci.image.layer.v1.tar+gzip`。最后一层装的是 `plugin.tar.gz`，里面才是 wasm。另有 `plugins/wasm-go/Dockerfile:26-29` 的纯二进制路径（`FROM scratch` + `COPY /main.wasm plugin.wasm`），配 `Makefile` 的 `GOOS=wasip1 GOARCH=wasm go build`。
- B（官方 v2.2.5 不可变发布规范）。`docs/developers/immutable-plugin-releases.md:90-93` 要求严格两层、没有 spec/README/icon 层：layer 0 `config.json` = `application/vnd.module.wasm.config.v1+json`（规范空对象 `{}`），layer 1 `plugin.wasm` = `application/vnd.module.wasm.content.layer.v1+wasm`；OCI image-spec v1.0、四个 provenance 注解、发布前 pull gate 做结构校验 + wazero 编译并检 Proxy-Wasm 导出（`:181-196`）。`:189-191` 明说单层 `latest` 镜像曾导致 Envoy 无法加载；`:198` 也声明该门禁只编译不实例化、不证明运行时可用。

`spec.yaml` 元数据（phase / priority / `configSchema`，仅 OpenAPI 3.0.0）属于第一套；第二套的元数据走 `plugins/release/catalog.json` 与快照。把第一套的 mediaType 套到官方产物上是错的。也支持 `url` 直接指向 http(s) 的 `.wasm`（Gateway 容器需能访问）；自签证书场景要在 Gateway 容器设 `WASM_INSECURE_REGISTRIES=*`（该变量只见于文档站，Helm 模板与本机源码未 grep 到）。

官方插件地址。旧清单在 `higress-console` 的 `backend/sdk/src/main/resources/plugins/plugins.properties`，稳定 tag 统一 `1.0.0`、开发版 `latest`；示例形态 `oci://higress-registry.cn-hangzhou.cr.aliyuncs.com/plugins/request-block:1.0.0`，用 `latest` 时"插件有任意配置更新就会自动拉取最新版本"。v2.2.5 的新口径是快照锁：主仓 `plugins/release/snapshots/2.2.5.json` 列 **43** 个插件（42 go + 1 rust、36 项版本 `2.0.3`），每项带 `ociRef` + `digest`，`plugin-server` 与 Console 都从这份不可变快照构建；`1.0.0` / `latest` 是旧通道说法，两者在 console 仓是否并存本机无工作树可核（列在分册 Unverified）。换私有仓库仍是改 Console 容器的 `HIGRESS_ADMIN_WASM_PLUGIN_CUSTOM_IMAGE_URL_PATTERN`（占位符 `${name}` / `${version}`），Nacos 3.x 的 MCP 注册中心另有 `MCP_SERVER_WASM_IMAGE_URL`；各形态的写法与转义细节见 [Deployment and Ops](/docs/CS/Framework/Higress/Deployment_and_Ops.md)。

## Inspecting the Plugin Chain

两个命令能回答"我的配置到底变成什么了"，分别打在控制面和数据面：

```bash
# 控制面：看 higress-core 生成的配置（转换后的 WasmPlugin / _rules_ 就在这份输出里）
kubectl exec <higress-controller-pod> -c higress-core -n higress-system -- \
  curl http://127.0.0.1:8888/debug/configz?pretty

# 数据面：看 Envoy 实际加载的过滤器链与相对顺序
kubectl exec <higress-gateway-pod> -n higress-system -- \
  curl http://127.0.0.1:15000/config_dump
```

`config_dump` 里能直接看到 wasm 插件被插在 `envoy.filters.http.cors`、`envoy.filters.http.rbac`、`envoy.filters.http.local_ratelimit`、`envoy.filters.http.fault`、`envoy.filters.http.router` 这些原生过滤器之间——这也是"为什么某些安全语义与 Envoy 原生不一致"的答案。四层排障链（8888 → 15014 → 15000）的完整走法在 [Deployment and Ops](/docs/CS/Framework/Higress/Deployment_and_Ops.md)。

## Wasm Development (Go)

Higress 的插件开发以 Go 为主路径（`wasm-go` SDK 封装了 higress-group 自己维护的 proxy-wasm-go-sdk）。下面只收**能照着写的准确名字**：钩子函数的真实 API 名、外部调用的寻址方式、以及 Go 1.24 编译换代带来的三处改动。

### SDK Surface

`wrapper.SetCtx(pluginName, ...)` 可挂的选项，全部取自 [Go SDK 与处理流程](https://higress.ai/docs/latest/user/plugins/wasm-dev/wasm16/)与 [使用 GO 语言开发 WASM 插件](https://higress.ai/docs/latest/user/wasm-go/)的原文：

| 选项函数 | 回调签名 | 用途 |
| --- | --- | --- |
| `wrapper.ParseConfigBy(parseConfig)` | `func(json gjson.Result, cfg *PluginConfig, log) error` | 全局与各级配置结构相同 |
| `wrapper.ParseOverrideConfigBy(parseConfig, parseRuleConfig)` | 第二个回调 `func(json gjson.Result, global PluginConfig, cfg *PluginConfig, log) error` | 全局与路由/域名/服务级**结构不同**时用（basic-auth 即典型：`defaultConfig` 放 `consumers`，`matchRules.config` 放 `allow`） |
| `wrapper.ProcessRequestHeadersBy` | `onHttpRequestHeaders(ctx, config, log) types.Action` | 请求头 |
| `wrapper.ProcessRequestBodyBy` | `onHttpRequestBody` | 请求体（缓冲） |
| `wrapper.ProcessStreamingRequestBodyBy` | `onHttpStreamingRequestBody` | 流式请求体 |
| `wrapper.ProcessResponseHeadersBy` / `ProcessResponseBodyBy` | `onHttpResponseHeaders` / `onHttpResponseBody` | 响应侧 |
| `wrapper.ProcessStreamingResponseBodyBy` | `onHttpStreamingResponseBody` | 流式响应体，SSE 在途处理靠它 |
| `wrapper.ProcessStreamDoneBy(onHttpStreamDone)` | — | 流式 / 请求结束回调 |

> [!WARNING]
> **`ProcessStreamDone` 与 `ProcessStreamDoneBy` 两个名字都真实存在**，用途不同：`*By` 系列是文档 Go SDK 原理页给出的形态（配 `ParseConfigBy` / `ProcessRequestBodyBy` 一起用），而**主仓自带的 MCP 插件走的是不带 `By` 的 `wrapper.ProcessStreamDone(onHttpStreamDone)`**（`plugins/wasm-go/pkg/mcp/server/plugin.go:910`）。`wrapper` 包来自外部模块 `github.com/higress-group/wasm-go`（不在本仓 `plugins/wasm-go/pkg/` 下，那里只有 `mcp` 与 `pathutil`），因此本机无法枚举它的全部导出项——**照抄文档示例时以 `*By` 系列为准，读主仓插件源码时会看到两种写法混用**。另注意文档示例里有一处 `wrappper.ProcessStreamDoneBy`（三个 p）是**页面笔误**。

最小可编译骨架，注意 Go 1.24 形态下 `main()` 是空的、注册在 `init()`：

```go
package main

import (
  "github.com/higress-group/wasm-go/pkg/wrapper"
  logs "github.com/higress-group/wasm-go/pkg/log"
  "github.com/higress-group/proxy-wasm-go-sdk/proxywasm"
  "github.com/higress-group/proxy-wasm-go-sdk/proxywasm/types"
  "github.com/tidwall/gjson"
)

func main() {}

func init() {
  wrapper.SetCtx(
    "my-plugin",
    wrapper.ParseConfigBy(parseConfig),
    wrapper.ProcessRequestHeadersBy(onHttpRequestHeaders),
  )
}

type MyConfig struct{ mockEnable bool }

func parseConfig(json gjson.Result, config *MyConfig, log logs.Log) error {
  config.mockEnable = json.Get("mockEnable").Bool()
  return nil
}

func onHttpRequestHeaders(ctx wrapper.HttpContext, config MyConfig, log logs.Log) types.Action {
  proxywasm.AddHttpRequestHeader("hello", "world")
  if config.mockEnable {
    proxywasm.SendHttpResponse(200, nil, []byte("hello world"), -1)
  }
  return types.HeaderContinue
}
```

依赖与代理：`go get github.com/higress-group/proxy-wasm-go-sdk@go-1.24`、`go get github.com/higress-group/wasm-go@main`、`github.com/tidwall/gjson`；国内可 `go env -w GOPROXY=https://proxy.golang.com.cn,direct`。控制台下发的 YAML 会**自动转成 JSON**，`parseConfig` 直接按 JSON 解析。

SDK 帮你做的三件自动行为：注册了 body / streaming 回调才会置 `needRequestBody` / `needResponseBody`；请求 `content-type` 为 octet-stream、grpc 或带 `content-encoding` 时**跳过 body 处理**；没注册 body 回调时 `OnHttpRequestBody` 直接 `ActionContinue`。上下文分三层：`CommonVmCtx`（`SetCtx` 创建，内部 `proxywasm.SetVMContext`）→ `CommonPluginCtx`（`OnPluginStart` 里取插件配置并 `ParseRuleConfig`）→ `CommonHttpCtx`（`NewHttpContext`，`OnHttpRequestHeaders` 里 `GetMatchConfig` 取当前请求生效配置）。

常用工具方法：`GetHttpRequestHeader(s)`、`Add`/`Remove`/`ReplaceHttpRequestHeader(s)`、`Get`/`Append`/`Prepend`/`ReplaceHttpRequestBody`（响应侧同名）、`DispatchHttpCall`、`GetHttpCallResponseHeaders/Body/Trailers`、`SendHttpResponse`、`SendHttpResponseWithDetail`、`ResumeHttpRequest` / `ResumeHttpResponse`。

### Compile Generation Shift

编译方案已经换过一次代，两页文档分属不同时间层，引用时必须分清。Go SDK 原理页仍按 TinyGo 叙述（Proxy-Wasm Go SDK 依赖 TinyGo，理由是当时官方 Go 编译器不适合出 wasm，页面列了 golang/go issues 25612 / 31105 / 38248）；而 wasm-go 页的注意块原话是：

> go 1.24 已经原生支持编译 wasm 文件，目前 higress 已从之前的 tinygo 0.29 + go 1.20 编译方案完整迁移为 go 1.24 原生编译 wasm 文件，Higress 版本需要 >= 2.1.4。

当前命令：

```bash
go mod tidy && GOOS=wasip1 GOARCH=wasm go build -buildmode=c-shared -o main.wasm ./
```

这条在源码里能直接对上：**主仓的插件构建用的就是同一行**（`plugins/wasm-go/Makefile:68`，`GOOS=wasip1 GOARCH=wasm go build -buildmode=c-shared -o ./main.wasm .`），该模块 `go.mod:3` 要求 `go 1.24.1`，`grep tinygo` 在 `plugins/wasm-go/Makefile` 中零命中，SDK 依赖 pin 在 `github.com/higress-group/proxy-wasm-go-sdk v0.0.0-20250611100342-...`（`plugins/wasm-go/go.mod:7`）。旧写法 `tinygo build -o plugin.wasm -scheduler=none -target=wasi ...` 已不是当前口径。

迁移带来三处必须改的代码，这是老插件升级时的清单：① 初始化逻辑从 `main()` 挪到 `init()`；② Header 阶段需要暂停等待外部回调时，`types.ActionPause` 要改成 **`types.HeaderStopAllIterationAndWatermark`**（官方注明"0.2.1 ABI 中的 `types.ActionPause` 实际上对应就是这个状态"）；③ `go-re2` 换回官方 `regexp`。

Header 阶段的三个状态语义要分清，选错会丢包：`HeaderContinue` 正常继续；`HeaderStopIteration` 暂停后续 header 迭代但**允许 body 继续缓冲**；`HeaderStopAllIterationAndBuffer` 停掉整个迭代、body 继续缓冲（**超过缓冲上限会丢包**）。暂停后必须显式恢复：`proxywasm.ResumeHttpRequest()` / `ResumeHttpResponse()`，或直接用 `SendHttpResponseWithDetail()` 回响应。

### Cluster Addressing

**外部调用按 Envoy cluster 名寻址，不是任意 URL**。这意味着被调用的服务必须先出现在 Higress 的服务发现里（McpBridge 或 K8s Service），SDK 才能按名字把它包装成 cluster——"插件里 Post 一个公网 URL 却总是连不上"通常是这个原因。`Cluster` 接口两个方法：`ClusterName()`（Envoy 集群名）与 `HostName()`（HTTP 调用时的 host / authority 头）。

| 构造函数 | 生成的 cluster 名 |
| --- | --- |
| `FQDNCluster{FQDN, Host, Port}` | `outbound|<Port>||<FQDN>`，FQDN 如 `foo.default.svc.cluster.local`、`my-cluster.static` |
| `RouteCluster{Host}` | 直接取 `proxywasm.GetProperty([]string{"cluster_name"})`，即当前路由的目标服务 |
| `StaticIpCluster` | `outbound|<port>||<service_name>.static` |
| `DnsCluster` | `outbound|<Port>||<ServiceName>.dns` |
| `K8sCluster` | `outbound|<Port>|<Version>|<ServiceName>.<Namespace>.svc.cluster.local` |
| `NacosCluster` | `outbound|<Port>|<Version>|<ServiceName>.<Group>.<NamespaceID>.nacos` |
| `ConsulCluster` | `outbound|<Port>||<ServiceName>.<Datacenter>.consul` |

HTTP 侧 `wrapper.HttpClient` 的方法集是 `Get/Head/Options/Post/Put/Patch/Delete/Connect/Trace/Call`，签名统一为 `method, rawURL string, headers [][2]string, [body []byte,] cb ResponseCallback, timeoutMillisecond ...uint32`；回调 `func ResponseCallback(statusCode int, responseHeaders http.Header, responseBody []byte)`。构造与调用：

```go
config.client = wrapper.NewClusterClient(wrapper.FQDNCluster{FQDN: "ext-auth.default.svc.cluster.local", Port: 8080})
// 底层收敛到 HttpCall() -> proxywasm.DispatchHttpCall(cluster.ClusterName(), ...)
```

三个已知行为要提前知道：**`HttpCall` 默认超时 500ms**（比直觉短得多，外部鉴权服务稍慢就会失败）；headers 参数里用户塞的 `:method` / `:path` / `:authority` **会被 SDK 静默剔除**；URL 的 host 会覆盖 `cluster.HostName()` 作为 authority；非 2xx 时 code 默认 `http.StatusBadGateway`。

Redis 侧**必须先初始化再调用**：`wrapper.NewRedisClusterClient(wrapper.FQDNCluster{...})` 之后要 `client.Init(username, password string, timeout int64) error`（内部走 `proxywasm.RedisInit(cluster.ClusterName(), ...)`）。命令接口含 `Eval(script, numkeys, keys, args, callback)` 与 `Del` / `Exists` / `Expire` / `Persist` 等，底层是 `RedisCall(cluster, respQuery []byte, callback)`；官方示例即用 `Eval` 实现令牌桶集群限流。这也是 `cluster-key-rate-limit` 这类有状态插件的实现基础。

### Wasm Runtime Model

数据面为什么是"沙箱隔离 + 内存安全"，答案在 VM 模型里：Wasm VM 是加载 Wasm 程序的实例，**在 Envoy 中通常每个工作线程创建一个、相互隔离**，Wasm 程序被复制进各线程执行。规范允许一个 VM 内配置多个插件，**完全相同 `vm_config` 的多个插件共享同一个 VM**（要求 `vm_config.vm_id`、`runtime`、`configuration`、`code` 全部相同），从而省内存、降启动延迟。`vm_config` 字段：`vm_id`（跨 VM 通信的语义隔离）、`runtime`（默认 `envoy.wasm.runtime.v8`，可选 `null` / `v8` / `wamr` / `wasmtime`）、`configuration`（VM 级配置）、`code`（wasm 二进制位置）；此外还有插件实例级 `configuration`。

Envoy 侧的插件类型有三种，Higress 网关逻辑用的是第一种：Http Filter（`envoy.filters.http.wasm`，处理 HTTP）、Network Filter（`envoy.filters.network.wasm`，处理 TCP）、Wasm Service（`envoy.bootstrap.wasm`，`singleton: true` 时在主线程跑单例 VM，适合指标与日志聚合这类不该阻塞工作线程的活）。

### Wasm Development Unverified

已从源码核实两项：① 镜像构建用的 CLI 是 `oras push`（`hgctl/pkg/plugin/build/build.go:446`），`templates.go:44-52` 还给出完整命令链 `tinygo build -o plugin.wasm` → `tar czf plugin.tar.gz plugin.wasm` → 把 tar.gz 作为最后一层追加；两套 OCI 规范的差异见 Hot Reload via ECDS。② `hgctl plugin` 的二级子命令已按 `hgctl/pkg/plugin/` 目录与 cobra `Use:` 核实为 `build` / `config`（下含 `create` / `edit`）/ `init` / `install` / `ls` / `test`（下含 `clean` / `create` / `ls` / `start` / `stop`）/ `uninstall`；`install` 有 `-y` 从 YAML 与 `-g` 从 Go 源码两条路径，后者先 build+push 镜像、再按 `spec.yaml` 的 `configSchema` 交互式问配置、生成 `plugin-conf.yaml`、最终 `Create` 到 `higress-system`（`install/install.go:141-290`、`config/templates.go:29-51`）。

仍缺一手出处的两项：Rust / JS SDK 的现状与 API 名（文档站在 `user/plugins/**` 与 `llms.txt` 索引里没有对应页面，本次只核实到 Go 路径）；wasm17 示例在发起外部调用后**确切返回哪个 Action**——该页可见代码只印出 `types.ActionContinue`，暂停 / 恢复的权威表述在 wasm-go 页，引用要引后者。另需注意：外部 SDK 仓 `github.com/higress-group/wasm-go` 本机无工作树，运行时规则匹配的实现细节不在本页证据范围内（见 [Plugin Loading Internals](/docs/CS/Framework/Higress/Plugin_Loading_Internals.md) 的 Unverified）。

## AI Plugins

Higress 的 17 款 AI 插件分布在一个**三层模型**里，把三层混为一谈是这片内容所有错误的共同来源：

- **Wasm 插件层**：`ai-proxy`、`ai-cache`、`ai-token-ratelimit`、`ai-quota`、`ai-security-guard`、`ai-data-masking`、`ai-statistics`、`mcp-server`、`ai-load-balancer` 等，配置写进 `WasmPlugin` 的 YAML（本节的字段口径都在这一层）。
- **控制台路由层**：AI 服务提供者管理、AI 路由管理（域名、模型匹配方式、**降级配置**、请求消费者）。**模型级 Fallback 只存在于这一层**，插件 YAML 里没有对应字段。
- **网关内置层**：MCP Server Filter（golang-filter），走控制台"系统设置"改 `mcpServer` 配置项，不是插件。

阶段与优先级的全表见上文 Phase and Priority Registry。控制台路由层、内置 MCP Filter、McpBridge、HiMarket 平台这些非插件内容见 [AI Gateway](/docs/CS/Framework/Higress/AI_Gateway.md)。

### Console Routing Persistence and Platform Boundary

三层模型里的控制台路由层与 HiMarket 平台都不是插件，但它们的落盘形态常被误判成"某个 AI 网关 CRD"或"网关自带组件"。本段一处从 `higress-console` 源码坐实、一处界定本地检索范围，把边界钉死。

**AI 路由管理落成 ConfigMap，不是 CRD**。控制台"AI 路由管理"的核心定义（`AiRoute`：域名、模型匹配方式、请求消费者等）在 `higress-console` v2.2.5 里落盘为 K8s 原生 **ConfigMap**：`KubernetesModelConverter.aiRoute2ConfigMap` 把整个 `AiRoute` 序列化进 `ConfigMap.data`、命名为 `AI_ROUTE_PREFIX + routeName` 并打 `CONFIG_MAP_TYPE_VALUE_AI_ROUTE` 标签（`KubernetesModelConverter.java:320-365`），写回走 `AiRouteServiceImpl.java:136-139` 的 `createConfigMap` 与 `:192-195` 的 `replaceConfigMap`。**模型级降级配置单独落成 `EnvoyFilter`**（`AiRouteServiceImpl` 的 `createEnvoyFilter` / `replaceEnvoyFilter`，`V1alpha3EnvoyFilter`），**路由上挂的 AI 插件实例落成 `WasmPlugin`**（`WasmPluginInstance`，scope `ROUTE` / `SERVICE`）。所以"AI 路由管理 = 某个 AI 网关 CRD"不成立——主对象是无类型 ConfigMap，仅降级与插件实例走标准 Istio 资源。功能面见 [AI Gateway](/docs/CS/Framework/Higress/AI_Gateway.md)。

**HiMarket 的计量计费不在 Higress 仓内**。已在本地三仓 `higress` / `higress-console` / `higress-standalone` 检索，HiMarket 平台实现不在其中，主仓仅保留文档引用；因此"计量计费由哪个组件承载、能否脱离 Higress 使用"无法由本地源码坐实，属跨仓库运行时问题，不作为网关插件层的事实写入。HiMarket 与网关插件的编排关系见 [AI Gateway](/docs/CS/Framework/Higress/AI_Gateway.md)。

### Provider Adaptation (ai-proxy)

`ai-proxy` 是默认阶段、priority 100 的插件，定位"基于 OpenAI API 契约的 AI 代理"。**协议转换靠路径后缀匹配 + 零配置自动检测，不需要用户声明 protocol**：

| 入口路径 | 行为 |
| --- | --- |
| `/v1/chat/completions` | 按 OpenAI 文生文协议解析请求 Body，再转成目标厂商协议 |
| `/v1/messages` | 按 Claude Messages API 解析；**若目标厂商原生支持 Claude 协议则直接转发，否则先转成 OpenAI 协议再转发** |
| `/v1/embeddings` | 按 OpenAI 向量协议解析后转换 |

`protocol` 字段只有两个取值：`openai`（默认）与 `original`（使用厂商原始接口契约）。真正的"逃生口"是 `capabilities`（map of string）——**部分 provider 的某些能力原生就兼容 openai/v1 格式，配置后直接透传、绕过重写**，key 是厂商协议能力、value 是真实 api path，当前支持 5 项：`openai/v1/chatcompletions`、`openai/v1/embeddings`、`openai/v1/imagegeneration`、`openai/v1/audiospeech`、`cohere/v1/rerank`。

厂商用 `type` 指定，文档正文以"X 所对应的 type 为 Y"逐字给出 **31 个**：`openai`、`azure`、`moonshot`、`qwen`、`baichuan`、`yi`、`zhipuai`、`deepseek`、`groq`、`grok`、`openrouter`、`fireworks`、`baidu`、`ai360`、`github`、`mistral`、`minimax`、`claude`、`ollama`、`hunyuan`、`stepfun`、`cloudflare`、`spark`、`gemini`、`deepl`、`cohere`、`together-ai`、`dify`、`vertex`、`bedrock`、`triton`；另有 `doubao`、`coze` **只出现在用法示例 YAML 里、没有独立条目**，合计文档层面出现 33 个 type 字符串。带特配字段的例子：`ollama` 必填 `ollamaServerHost` / `ollamaServerPort`（默认 11434）；`triton` 有 `modelVersion` / `tritonDomain` / `tritonModelVersion`。**注意这是文档收录数，不是源码 provider 数**（本次无法回源码核对，见 Unverified）。

模型名改写走 `modelMapping`（map of string），四条规则要一起记：前缀匹配 `gpt-3-*`；`"*"` 作键做通用兜底；目标值为空字符串 `""` 表示**保留原模型名**；`~` 前缀走正则并支持 capture group 引用（`~gpt(.*): openai/gpt$1`）。参数级透传用 `customSettings`（每项 `name` / `value` / `mode` / `overwrite`）：`mode` 为 `auto`（默认，按映射表自动改写参数名）或 `raw`（不改写、不做限制检查）；`overwrite=false` 时只在用户未设置该参数时填充。映射表覆盖 `max_tokens` / `temperature` / `top_p` / `top_k` / `seed` 五个设置对 8 个协议（openai / baidu / spark / qwen / gemini / hunyuan / claude / minimax）的支持矩阵，**改写位置有特例：qwen 改 `parameters` 子路径、gemini 改 `generation_config` 子路径**，其余改 JSON 根路径。

两个容易误用的字段：`timeout` 默认 120000，但文档明确"此项配置目前仅用于获取上下文信息，**并不影响实际转发大模型请求**"；`reasoningContentMode` 取值 `passthrough`（默认）/ `ignore` / `concat`，且**仅支持通义千问**。`subPath` 会先移除请求 path 中的该前缀再做后续处理。

### Key Pool, Failover, Retry

这三件事经常被合并成一句"高可用"，实际是三个不同层次、由两个不同层承载：

| 名字 | 在哪一层 | 摘除 / 重试的对象 | 关键字段与默认值 |
| --- | --- | --- | --- |
| `apiTokens` | 插件 | 多个凭证之间**随机选取** | 文档原文是"插件会在请求时随机进行选择"，**不是轮询 / round-robin**；部分厂商只支持单个 token |
| `failover` | 插件 | **apiToken**（同厂商内换 key） | `failureThreshold` 3 / `successThreshold` 1 / `healthCheckInterval` 5000ms / `healthCheckTimeout` 5000ms / `failoverOnStatus` `["4.","5."]`；**启用时 `healthCheckModel` 必填** |
| `retryOnFailure` | 插件 | 同一请求立即重试 | `maxRetries` 1 / `retryTimeout` 30000ms / `retryOnStatus` `["4.","5."]`；**目前仅支持非流式请求** |
| 模型级 Fallback | **控制台路由层** | **换一个模型 / 换一个服务** | 入口是"AI 路由管理 → 为路由进行降级配置"，文档口径"当请求目标服务失败（如限流、访问失败等）时，降级到阿里云 `qwen-turbo` 模型" |

同一个 `failover` 在控制台侧的形态是"AI 服务提供者管理 → 每个服务提供商单独配令牌降级策略"。也就是说：**换 key 在插件里配，换模型只能在控制台配**，两者没有重叠字段。

### Load Balancing over Models (ai-load-balancer)

`ai-load-balancer` 是本页唯一**没有文档站页面**的插件（文档 URL 取不到正文、`llms.txt` 索引里也没有），只存在于仓库 `plugins/wasm-go/extensions/ai-load-balancer/` 的 README 中。其字段口径最早取自 main 分支 README，现已用本地 v2.2.5 tag 源码坐实——`main.go:47-58` 的 `lb_type`/`lb_policy` 常量枚举 + 五个策略子目录 `cluster_hash`/`cluster_metrics`/`endpoint_metrics`/`global_least_request`/`prefix_cache` 全部存在，信源层级提升为源码核实。顶层三字段 `lb_type`（`endpoint` | `cluster`，空值回退 `endpoint`，见 `main.go:63-65`）/ `lb_policy`（必填）/ `lb_config`（必填），README 要求网关版本 >= v2.1.5。

| `lb_policy` | 属于 | 语义 |
| --- | --- | --- |
| `global_least_request` | endpoint | 基于 Redis 的全局最小请求数（在途计数 ±1） |
| `prefix_cache` | endpoint | **按 prompt 前缀匹配选后端节点以复用 KV Cache**，miss 时静默回落到 `global_least_request`；`redisKeyTTL` 默认 1800s |
| `endpoint_metrics`（含兼容别名 `metrics_based`） | endpoint | 读 LLM 服务自己暴露的 metrics，`metric_policy` 取 `default`（即 gateway-api-inference-extension 算法实现）/ `least` / `most`，配 `target_metric`（示例用 `vllm:num_requests_waiting`、`vllm:num_requests_running`）与 `rate_limit`（默认 1）。**`metrics_based` 是 `main.go:55` 标注的废弃兼容名（`MetricsBasedEndpointDeprecated`，解析时与 `endpoint_metrics` 同分支），不是独立策略** |
| `cluster_metrics` | cluster | 跨服务负载，`mode` 取 `LeastBusy` / `LeastTotalLatency` / `LeastFirstTokenLatency` / `AdaptiveScore` |
| `cluster_hash` | cluster | 读指定请求头做 **FNV-1a** 一致性 hash 固定到同一 cluster |

三条必须一起写的注意事项：~~**README 自身矛盾**~~（**已证伪**）——清单写 `endpoint_metrics`、示例写 `metrics_based` 只是命名差异：`metrics_based` 是 `main.go:55` 标注的废弃兼容名（`MetricsBasedEndpointDeprecated`），解析走与 `endpoint_metrics` 完全相同的分支，**照抄清单或示例结果等价**，不存在"不同结果"；**`cluster_hash` 是硬失败**——所有 `weight` 之和必须为 100，且请求缺少 `hash_header`（默认 `x-mse-consumer`）时插件**直接返回 403**，不是静默降级（与 README 一致）；**`AdaptiveScore` 已随 v2.2.5 进 `cluster_metrics.mode`**（README_EN:219/246 列出 `[LeastBusy, LeastTotalLatency, LeastFirstTokenLatency, AdaptiveScore]`，源码子目录 `cluster_metrics/` 佐证），其失败率只用插件实例生命周期内的累计值，README 明写"目前不使用时间窗口或衰减"，即重启实例就清零，别当熔断器历史用；它开启 `global_inflight_enabled` 后靠 Redis Lua 原子选服务，**Redis 异常时降级到本地打分、不阻断请求**。

关闭 `ai-load-balancer` 后策略不是"退化为轮询"，而是退化为服务本身内置策略集合（轮询、本地最小请求数、随机、一致性 hash）。

> [!NOTE]
> **`higress.io/load-balance` 注解是集群级简单 LB，不能做模型级负载均衡**——这点从源码坐实，且与本段插件强相关。它是控制面 Ingress 注解（`pkg/ingress/kube/annotations/loadbalance.go:25,142-153`），解析后翻译成 Istio `TrafficPolicy.LoadBalancer.Simple`（即 Envoy 集群级简单 LB），与 `ai-load-balancer` wasm 插件的模型级加权（`endpoint_metrics` / `cluster_hash` / `AdaptiveScore`）是**完全不同的两层**。取值集合来自 Istio `LoadBalancerSettings_SimpleLB` 枚举（`istio.io/api` 的 `v1.27.1` 分支，fork 内 `pilot/pkg` 对 `ROUND_ROBIN` / `LEAST_CONN` / `RANDOM` / `PASSTHROUGH` 四常量均有引用），**大小写不敏感**（源码 `strings.ToUpper`）：有效值为 `ROUND_ROBIN`（默认，且**无效值会静默 fallback 到它**——`SimpleLB_value[lb]` 对未命中 key 返回 int32 零值 0，不报错）、`LEAST_CONN`、`RANDOM`、`PASSTHROUGH`；另有特判值 `MCP-SSE`（非 LB 算法，触发 McpSse 会话保持开关，见 [Config Pipeline](/docs/CS/Framework/Higress/Config_Pipeline.md)）。解析优先级需注意：**若 `affinity` / `session-cookie-name` / `session-cookie-path` 任一存在 → cookie 一致性 hash（忽略 `load-balance` 值）；否则若 `upstream-hash-by` 存在 → 按 header / query / 源 IP 的一致性 hash（同样忽略 `load-balance` 值）；否则才读 `load-balance` 本身**。⇒ 想做模型级加权必须装 `ai-load-balancer` 插件，仅靠注解最多到集群级轮询 / 最小连接 / 随机 / 透传。

**`prefix_cache` 与 `ai-cache` 是完全不同的两件事**，尽管名字都带 cache：前者选 pod（复用后端 LLM 的 KV Cache），后者直接短路 LLM 调用。

### Metering, Rate Limit and Quota

`ai-token-ratelimit`（默认阶段、priority 600）基于 Redis 实现，两种模式互斥：`global_threshold`（规则级全局限流）与 `rule_items`（Key 级动态限流），外加必填的 `rule_name` 与 `redis`。**限流粒度只有四个时间档**：`token_per_second` / `token_per_minute` / `token_per_hour` / `token_per_day`——**没有 week / month，也没有区分输入 / 输出 token 的字段**（这正是它与 `ai-quota` 的分工缺口）。key 来源共 9 种：`limit_by_header` / `limit_by_param` / `limit_by_consumer` / `limit_by_cookie`，以及逐键分别计数的 `limit_by_per_header` / `per_param` / `per_consumer` / `per_cookie` / `per_ip`（**不存在裸 `limit_by_ip`**；per_ip 取值 `from-header-<名>` 或 `from-remote-addr`）。`limit_keys[].key` 支持 `regexp:` 前缀与 `*`。`rejected_code` 默认 429、`rejected_msg` 默认 `Too many requests`。Redis key 拼装口径是"规则名称 + 限流类型 + 限流 key 名称 + 限流 key 实际值"。

`ai-quota`（默认阶段、priority 750）管的是**总额**：给特定 consumer 分配固定 quota，并提供查询 / 刷新 / 增减三类管理动作（`admin_consumer` 必填、`admin_path` 默认 `/quota`、`redis_key_prefix` 默认 `chat_quota:`）。它有两个硬前置，文档原话："需要配合认证插件比如 `key-auth`、`jwt-auth` 等获取认证身份的 consumer 名称，同时**需要配合 `ai-statistics` 插件获取 AI Token 统计信息**"。

于是这几个插件是**共生关系而不是可独立使用**：`ai-quota` 不认身份（consumer 来自认证插件），但**自己通过共享库 `pkg/tokenusage` 从响应体解析并计量 token**、并写自有 Redis（`chat_quota:` 前缀）；`ai-token-ratelimit` 同理自解 token、写 `higress-token-ratelimit:` 前缀 Redis。三者**与 `ai-statistics` 无运行时数据耦合**——它只是纯观测插件（见下方 AI Observability 段 NOTE）。

> [!WARNING]
> 两个后果经常被忽略。① **`rule_items` 是命中第一条即停**（官方"后续规则不再执行"），不是所有命中规则叠加生效——部分二手博客称"混合配置时所有命中规则叠加、任一触发即 429"，与官方正文直接冲突。② **`ai-cache` 落在默认阶段 priority 800，晚于 `ai-token-ratelimit`（默认 600）与 `ai-quota`（默认 750）**——请求必然先过限流与配额、再进语义缓存，缓存命中省的是后端算力、不绕过限流/配额计数；不要写"缓存命中使限流失效"。（旧表曾把 `ai-cache` 误标为认证阶段 10，结论正好相反。）

### Semantic Cache (ai-cache)

`ai-cache` 在默认阶段、priority 800（注意它**晚于** `ai-token-ratelimit` 600 / `ai-quota` 750，请求先过限流配额再进缓存，并非"最早介入"），**默认配置即可缓存 OpenAI 协议结果，支持流式与非流式**。它用同一个插件承载两种缓存，靠 `enableSemanticCache`（默认 true）切换；关闭即"使用字符串匹配的方式查找缓存，此时需要配置 `cache` 服务"。缓存键策略 `cacheKeyStrategy` 取 `lastQuestion`（默认）/ `allQuestions` / `disabled`。

三种合法组合与一个优先级：`cache` 单用 = 字符串精确匹配；`vector`(+`embedding`) = 语义缓存（向量库自身不提供字符串向量化时必须配 `embedding`）；`vector`(+`embedding`) + `cache` = 语义缓存并用缓存服务存响应以加速。`vector` 与 `cache` 不能同时为空，而**同时配置时字符串匹配优先**（"优先使用缓存数据库，未命中场景下使用向量数据库能力"）——所以"配了向量库却没生效"不一定是 bug。embedding 一律来自**外部文本向量化服务**，插件不做本地向量化。

```yaml
cacheKeyStrategy: lastQuestion
enableSemanticCache: true
vector:    { type: dashvector, serviceName: ..., serviceHost: ..., apiKey: ...,
             topK: 1, threshold: 0.8, thresholdRelation: gt }   # Cosine/DotProduct 用 gt，Euclidean 用 lt
embedding: { type: dashscope, serviceName: ..., apiKey: ..., model: ... }
cache:     { type: redis, serviceName: ..., cacheTTL: 0, cacheKeyPrefix: "higress-ai-cache:" }
```

> [!WARNING]
> **相似度阈值的字段名与默认值组合起来是不可用的**：真名是 `vector.threshold`（float64，默认 **1000**）配 `vector.thresholdRelation`（默认 **`lt`**）。而文档自己给的语义是"Cosine 与 DotProduct 值越大越相似 → 应选 `gt`"。也就是说对最常见的两种度量，**默认值等于永远不命中**——不显式配这两个字段就等于没开语义缓存。这是"照抄最小配置但结果静默不生效"的典型坑，值得单独记。

命中后不调后端、也不产生真实 token 消耗：响应由 `responseTemplate` / `streamResponseTemplate` 直接拼出，默认模板的 `id` 是 `"ai-cache.hit"`、`finish_reason: "stop"`、**`usage` 三项 token 全为 0**（流式模板自带 `data:[DONE]`）。若下游按 usage 计费或统计，缓存命中会表现为"零 token 消耗"，写"缓存省 token"时要说清省的是后端算力还是计费。逃生开关：请求头 `x-higress-skip-ai-cache: on` 让当前请求**既不读也不写**缓存。GJSON 路径可自定义提取位置：`cacheKeyFrom`（默认 `messages.@reverse.0.content`）、`cacheValueFrom`、`cacheStreamValueFrom`、`cacheToolCallsFrom`。向量库支持 Chroma / DashVector / ElasticSearch（额外 `esUsername` / `esPassword`）/ Milvus / Pinecone / Qdrant / Weaviate；embedding 支持 OpenAI / Ollama / 讯飞星火（`appId` / `apiSecret`）/ TextIn（`textinAppId` / `textinSecretCode` / `textinMatryoshkaDim`）/ Hugging Face / Cohere。

### Safety and Masking

`ai-security-guard`（默认阶段、priority 300）**没有 block / mask / audit 三种处置动作**。它的配置面是 `checkRequest`（默认 false）/ `checkResponse`（默认 false）两个开关加 `denyCode` / `denyMessage`，**只有"合规检查 + 拒绝"一种处置**，既没有"脱敏放行"也没有"只记录不拦截"；**脱敏属于另一个插件 `ai-data-masking`**。两个隐性代价：`checkResponse` 生效时**会使流式响应变成非流式**；`denyCode` **默认是 200 而不是 4xx**（`denyMessage` 默认返回一个 OpenAI 格式、内容为"阿里云内容安全的建议回答"的响应）——用状态码判断是否被拦截会全部漏判。其余字段：`requestCheckService` 默认 `llm_query_moderation`、`responseCheckService` 默认 `llm_response_moderation`、`requestContentJsonPath` 默认 `messages.@reverse.0.content`、`responseContentJsonPath` 默认 `choices.0.message.content`、`responseStreamContentJsonPath` 默认 `choices.0.delta.content`。

它是**强绑定阿里云内容安全（Green）服务**的：`serviceName` / `servicePort` / `accessKey` / `secretKey` 必填，`serviceHost` 的说明就是"阿里云内容安全 endpoint 的域名"。开源 Higress 换检测方要走文档里"指定自定义内容安全检测服务"那条示例。同类绑定还有 `ai-rag`（对接阿里云向量检索服务）与 `ai-proxy` 的 `reasoningContentMode`（仅通义千问）。

`ai-data-masking`（认证阶段、priority 991）做敏感词的**拦截 + 替换**：处理范围三选一 `deny_openai`（默认 true）/ `deny_jsonpath`（默认 `[]`）/ `deny_raw`（默认 false，整个 body），另有 `system_deny`（内置规则，默认 false）、`deny_words`、`deny_code`（**默认同样 200**）、`deny_message`、`deny_content_type`。替换语义值得原文引用："将敏感词替换为脱敏字符串再传后端，保证敏感数据不出域；**部分脱敏数据在后端返回后可进行还原**；自定义规则支持标准正则和 **grok 规则**，替换字符串支持变量替换"。

### MCP Hosting (mcp-server plugin)

`mcp-server` Wasm 插件（默认阶段、priority 30）定位"无需编写代码，将现有 REST API 转换为 AI 助手可调用的工具"，并复用网关的统一认证 / 鉴权 / 限流 / 可观测。`server.type` 只有两个取值且**默认是 `rest`**（REST-to-MCP：网关自己实现 MCP 协议端点，把 `tools/call` 翻译成对后端 REST API 的 HTTP 调用，需写 `tools` / `requestTemplate` / `responseTemplate`）；`mcp-proxy` 才是代理后端已有的 MCP server，此时 `server.mcpServerURL` 与 `server.transport` 必填，`transport` 取 `http`（StreamableHTTP，新协议）或 `sse`（旧协议），**不写 tools 就代理后端全部工具**。内置 MCP 服务器（文档举例 `quark-search`）只需填 `server.name`、无需配 tools。工具白名单 `allowTools` 不填即允许全部；另有**动态工具权限**——通过请求头下发白名单，规则是 header 不存在或为空串时用配置的 `allowTools`、为纯空白串（如 `"  ,  ,  "`）时**禁止全部**、有值时与 `allowTools` **取交集**。

安全默认值是这里最容易踩的一点：`server.passthroughAuthHeader` **默认 false**，未配置下游安全认证时网关会**主动移除 Authorization 头**，防止客户端凭证被错误传到后端。"配了需要 API Key 的后端 MCP 工具却总是 401"往往就是这个默认值。凭证体系分三级生效：工具级 `tools[].security`（`id` + `passthrough`）、工具级 `tools[].requestTemplate.security`（`id` + `credential`）、服务器级 `server.defaultDownstreamSecurity`（客户端 → 网关，覆盖所有 `tools/list` 与 `tools/call`）与 `server.defaultUpstreamSecurity`（网关 → 后端），**工具级可覆盖服务器级**；`passthrough=true` 时 `requestTemplate.security.credential` 被忽略。

网关内置的 MCP Server Filter（golang-filter）与 McpBridge 注册源这两条**非插件**路径见 [AI Gateway](/docs/CS/Framework/Higress/AI_Gateway.md)。

### AI Observability (ai-statistics)

`ai-statistics`（默认阶段、priority 900）是 AI 观测的数据源，定位"提供 AI 可观测基础能力，包括 metric, log, trace"，并有一条前置：**其后需接 `ai-proxy` 插件，不接的话需要用户自行配置才生效**。默认零配置即可得到输入 token、输出 token、**首个 token 的 rt（仅流式）**、请求总 rt，支持**网关 / 路由 / 服务 / 模型四个观测维度**。

> [!NOTE]
> **`ai-statistics` 是纯观测插件，不是管控插件的数据源**。源码（`ai-statistics/main.go`）从 LLM 响应体提取 token 用量后，只通过 Proxy-Wasm metric API 上报为 Envoy 指标 / 访问日志 / 链路 span，**自身不写 Redis、也不被 `ai-quota` / `ai-token-ratelimit` 调用**。限流与配额插件各自通过共享库 `pkg/tokenusage` 直接从响应体解析 token、并写各自独立的 Redis 前缀（`higress-token-ratelimit:` / `chat_quota:`）。因此"管控插件依赖 ai-statistics 取数"是文档把"功能配套、建议同装"误表述成了数据依赖——三者是**观测与管控解耦**的关系。

六个 counter 指标共享前缀 `route_upstream_model_consumer_metric_`，后缀分别是 `input_token`、`output_token`、`llm_service_duration`（流式 + 非流式总耗时累加）、`llm_duration_count`、`llm_first_token_duration`（**流式请求首 token 延时累加，即 TTFT**）、`llm_stream_duration_count`；标签为 `ai_route`、`ai_cluster`、`ai_model`、`ai_consumer`。访问日志侧对应字段是 `input_token`、`output_token`、`model`、`llm_service_duration`、`llm_first_token_duration`。通用三支柱（指标端口、日志格式、追踪后端）在 [Observability](/docs/CS/Framework/Higress/Observability.md)。

扩展靠 `attributes`（每项 `key` / `value_source` / `value` / `rule` / `apply_to_log` / `apply_to_span`）：`value_source` 六种取值 `fixed_value` / `request_header` / `request_body` / `response_header` / `response_body` / `response_streaming_body`（body 类的 `value` 用 gjson jsonpath，header 类填 header key）；`rule` 决定从流式响应哪一段取值——`first` / `replace`（取最后一个）/ `append`（拼接，可用来取完整回答）。

HiMarket 不是网关组件：官方定义是"基于 Higress AI 网关构建的**企业级 AI 开放平台**"，统一管理 LLM、MCP Server、Agent、Agent Skill、Agent Worker，平台"以 Higress 作为模型服务的网关代理，提供内容安全、Token 限流等防护能力"——即它不自己实现限流与安全，而是**编排本页这些网关插件**。它的观测大盘同样不自建数据源，两种方案互斥：**SLS 方案（推荐）** 靠 `ai-statistics` + 阿里云 SLS 采集，依赖阿里云、商业化网关开箱即用；**数据库方案** 靠 `db-log-pusher` + `db-log-collector` + MySQL，完全开源、非阿里云环境适用，但**商业化网关不适用**。文档明确"两种方案的功能完全一致，区别仅在于数据存储和采集方式"。

### Remaining AI Plugins

| 插件 | 一句话定位（取自各页功能说明） |
| --- | --- |
| `ai-agent` | 可定制化 API AI Agent，支持 GET / POST 两类 API、多轮对话、流式与非流式 |
| `ai-rag` | 通过对接阿里云向量检索服务实现 LLM-RAG |
| `ai-search` | 集成搜索引擎（Google / Bing / Arxiv / Elasticsearch 等）实时结果，自动把搜索结果注入提示模板，按配置决定是否在回答中加引用来源 |
| `ai-intent` | LLM 意图识别，判断请求与某个领域 / agent 功能的契合度 |
| `ai-prompt-decorator` | 在 LLM 请求前后插入 prompt（可配合 `geo-ip` 携带用户地理位置） |
| `ai-prompt-template` | 快速构建同类型 AI 请求的模板 |
| `ai-json-resp` / `ai-history` / `ai-transformer` / `geo-ip` | 分别做 JSON 格式化、历史对话、请求响应转换、IP 地理位置；本次只读到标题，未逐页核实 |

### AI Plugin Claims That Don't Hold

| 流传说法 | 一手文档口径 | 处置 |
| --- | --- | --- |
| `ai-security-guard` 支持 block / mask / audit | 只有 `checkRequest` / `checkResponse` + `denyCode` / `denyMessage` | 废弃，mask 归 `ai-data-masking` |
| 多 API Key 轮询（round-robin） | 多个 token 时**随机**选取 | 改 |
| 模型级 Fallback 是 `ai-proxy` 的能力 | 插件侧只有 apiToken 级 `failover`；模型级降级在**控制台 AI 路由管理** | 拆成两件事 |
| token 计量在 `ai-proxy` 内 | 由 `ai-statistics` 承担 | 归属改正 |
| 语义缓存阈值字段 `similarityThreshold` | `vector.threshold` + `vector.thresholdRelation`，默认组合不可用 | 字段名改正并写坑 |
| nacos（任意版本）可作 MCP 注册源 | 仅 `nacos3` | 收窄 |
| token 限流多条规则叠加生效 | `rule_items` 命中第一条即停 | 采信官方 |
| `openapi-to-mcpserver` 是独立工具 / 插件 | 官方文档站无页面；本仓源码里也**没有**这个目录（`plugins/wasm-go/extensions` 全清单已比对） | 不作为已核实名称写 |
| 不存在 `mcp-router` | **源码里有且已读**：`plugins/wasm-go/extensions/mcp-router/` 是真实目录，基于 `mcp.LoadMCPFilter` 框架（`pkg/mcp`）；`higress-console` 的 marketplace `spec.yaml` 也已收录（确属发布插件）。**功能面已核**：为 MCP `tools/call` 做路由聚合，按工具名前缀 `server-name___tool-name`（`consts.ToolSetNameSplitter = "___"`，`pkg/mcp/consts/vars.go:18`）匹配 `servers[].name`，改写 `:authority`/`:path`、注入 `x-envoy-internal-route: true` 并剥离前缀后重路由；`domain` 省略则保留原域名。**注意 README_ZH 写的分隔符是 `/`，与源码 `___` 冲突，以源码为准** | 已核实 |

### AI Plugin Unverified

本页曾列的 AI 插件未决项已在 v2.2.5 源码中全部转正或界定范围，结论已移入正文；以下保留逐项核实记录与信源层级说明。

> [!NOTE]
> **`ai-proxy` 在 v2.2.5 已完整支持 OpenAI Responses API 与全套 Fine-Tuning API**（已从源码坐实）。`provider.go:54,103` 定义 `ApiNameResponses = "openai/v1/responses"` + `PathOpenAIResponses = "/v1/responses"`，并在 `main.go:72` 注册；Fine-Tuning 全套 9 个能力（`provider.go:55-63`：`ApiNameFineTuningJobs` / `RetrieveFineTuningJob` / `FineTuningJobEvents` / `FineTuningJobCheckpoints` / `CancelFineTuningJob` / `ResumeFineTuningJob` / `PauseFineTuningJob` / `FineTuningCheckpointPermissions` / `DeleteFineTuningCheckpointPermission`，对应 `/v1/fine_tuning/jobs` 及其子资源，`main.go:71` 等注册）。不止 OpenAI 一家：`qwen` / `doubao` / `vllm` / `groq` / `azure` 的 capabilities 映射也都包含 Responses（`needToProcessRequestBody(ApiNameResponses)=true` 表明走请求体转换、可用于 provider 间格式翻译）；`provider.go:881,888-893` 标注 Responses 与 Fine-Tuning 系列 `needProcessResponseBody = true`——前者维护 `previous_response_id` 对话状态、后者维护 job 状态。文档站若把这些 API 写成"不支持"，与源码直接冲突。

**信源层级说明**：本页字段名、默认值**仍以官方文档站正文为主**（逐条 `[摘要级]`），但两类关键结论现已从源码坐实：① **阶段与优先级不再来自文档站**，改为 `higress-console` 的 marketplace `spec.yaml`（v2.2.5，commit `0279ce1a`）逐项抽取（见上方 Phase and Priority Registry 的 NOTE），旧表据此订正了 `ai-cache` / `ai-statistics` / `mcp-server` / `custom-response` / `hmac-auth-apisix` / `frontend-gray` / `opa` 七项；② **两个高频默认值已从 Go 配置结构体核实**——`ai-security-guard.denyCode` 默认 `200`（`config/config.go:68` `DefaultDenyCode`）、`ai-cache.vector.threshold` 默认 `1000` 且 `thresholdRelation` 默认 `lt`（`vector/provider.go:151-157`），与文档一致。本地源码树（v2.2.5）还确认了**插件的存在性与语言层归属**——`ai-load-balancer` 与 `mcp-router` 在 `plugins/wasm-go/extensions/`，认证基础族在 `plugins/wasm-cpp/`，`ai-data-masking` 在 `plugins/wasm-rust/`（见 [Source Map](/docs/CS/Framework/Higress/Source_Map.md)）。控制台"AI 路由管理"落成对象已从 `higress-console` 源码坐实，HiMarket 计量计费界定为跨仓库运行时问题，两条结论都在正文 Console Routing Persistence and Platform Boundary 段；`higress.io/load-balance` 注解取值集合（见上方 ai-load-balancer 段 NOTE）、`ai-proxy` 对 OpenAI Responses / Fine-Tuning 的支持（见上方 NOTE）、`ai-load-balancer` 在 v2.2.5 的策略集（含 `metrics_based` 别名、`AdaptiveScore` 已进入 `cluster_metrics.mode`）与 `mcp-router` 的功能面亦均已从源码坐实，见上方对应小节。

> [!NOTE]
> `ai-proxy` 的 provider 数是 38，与文档收录的 33 个 `type` 字符串不相等。`plugins/wasm-go/extensions/ai-proxy/provider/provider.go:130-167` 定义 38 个 `providerType*` 常量（37 个厂商类型 + 内部回退 `generic`），`:236` 的 `providerInitializers map[string]providerInitializer` 注册表也恰 38 项、与常量一一对应，`providerTypeAi360 = "ai360"` 就在 `:132`。文档那 33 个全部能在源码常量里找到，源码多出 `galadriel` / `kling` / `longcat` / `vllm` 四个厂商类型与内部 `generic`。另注：codegraph 的 `implements` 边把 `providerInitializer` 连出 40 条，其中混入 `ai-cache/vector/` 与 `ai-cache/cache/` 的同名类型，属于按名称匹配的误连，不能当 provider 数（口径见 [Call Graph Internals](/docs/CS/Framework/Higress/Call_Graph_Internals.md)）。

## Links

- [Security and Auth](/docs/CS/Framework/Higress/Security_and_Auth.md)
- [AI Gateway](/docs/CS/Framework/Higress/AI_Gateway.md)
- [Source Map](/docs/CS/Framework/Higress/Source_Map.md)
- [Observability](/docs/CS/Framework/Higress/Observability.md)
- [Deployment and Ops](/docs/CS/Framework/Higress/Deployment_and_Ops.md)
- [Service Discovery](/docs/CS/Framework/Higress/Service_Discovery.md)
- [WasmPlugin](/docs/CS/Framework/Istio/WasmPlugin.md)
- [Envoy](/docs/CS/Framework/Istio/Envoy.md)
- [Higress](/docs/CS/Framework/Higress/Higress.md)
- [Config Pipeline](/docs/CS/Framework/Higress/Config_Pipeline.md)
- [Plugin Loading Internals](/docs/CS/Framework/Higress/Plugin_Loading_Internals.md)
- [Call Graph Internals](/docs/CS/Framework/Higress/Call_Graph_Internals.md)

## References

- [Wasm 插件使用简介](https://higress.ai/docs/latest/user/plugins/intro/)
- [Wasm 插件原理](https://higress.ai/docs/latest/user/plugins/wasm-dev/wasm15/)
- [Wasm 生效原理](https://higress.ai/docs/latest/user/plugins/wasm-dev/wasm19/)
- [Wasm 插件镜像规范](https://higress.ai/docs/latest/user/wasm-image-spec/)
- [Higress 插件市场](https://higress.ai/plugins/)
- [使用 HTTP/HTTPS 协议加载 Wasm 插件](https://higress.ai/docs/latest/ops/how-tos/load-wasm-with-http/)
- [修改内置插件镜像地址](https://higress.ai/docs/latest/ops/how-tos/builtin-plugin-url/)
- [使用 GO 语言开发 WASM 插件](https://higress.ai/docs/latest/user/wasm-go/)
- [Higress 插件 Go SDK 与处理流程](https://higress.ai/docs/latest/user/plugins/wasm-dev/wasm16/)
- [HTTP 调用](https://higress.ai/docs/latest/user/plugins/wasm-dev/wasm17/)
- [Redis 调用](https://higress.ai/docs/latest/user/plugins/wasm-dev/wasm18/)
- [自定义插件](https://higress.ai/docs/latest/user/plugins/custom/)
- [AI 代理](https://higress.ai/docs/latest/user/plugins/ai/api-provider/ai-proxy/)
- [AI Token限流](https://higress.ai/docs/latest/user/plugins/ai/api-consumer/ai-token-ratelimit/)
- [AI 配额管理](https://higress.ai/docs/latest/user/plugins/ai/api-consumer/ai-quota/)
- [AI 缓存](https://higress.ai/docs/latest/user/plugins/ai/api-provider/ai-cache/)
- [AI 数据脱敏](https://higress.ai/docs/latest/user/plugins/ai/api-consumer/ai-data-masking/)
- [AI 内容安全](https://higress.ai/docs/latest/user/plugins/ai/api-provider/ai-security-guard/)
- [AI可观测](https://higress.ai/docs/latest/user/plugins/ai/api-o11y/ai-statistics/)
- [MCP 插件配置](https://higress.ai/docs/ai/mcp-server/)
- [MCP Server 快速开始（对接现存 SSE Server）](https://higress.ai/docs/ai/mcp-with-sse/)
- [多模型代理](https://higress.ai/docs/ai/scene-guide/multi-proxy/)
- [语义缓存](https://higress.ai/docs/ai/scene-guide/semantic-cache/)
- [一键部署 Higress AI 网关](https://higress.ai/docs/ai/quick-start/)
- [HiMarket 介绍](https://higress.ai/docs/himarket/himarket-introduction/)
- [可观测能力介绍](https://higress.ai/docs/himarket/himarket-observability-overview/)
- [ai-load-balancer 插件 README](https://github.com/higress-group/higress/tree/main/plugins/wasm-go/extensions/ai-load-balancer)
