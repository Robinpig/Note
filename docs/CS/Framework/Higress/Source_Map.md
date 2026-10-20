## Introduction

这是 [Config Pipeline](/docs/CS/Framework/Higress/Config_Pipeline.md) 的静态 counterpart：那条链路上的每个函数住在哪个目录、由哪个生成器产出、以什么形态被编译进来。基准同样钉在 **v2.2.5**（HEAD `4deae1dd`），全部结论带 `路径:行号`。

先说这张地图存在的理由：**文档版的目录职责表已经和源码对不上**。[源码阅读指引](https://higress.ai/docs/latest/dev/code/)列的九项（`cmd` / `pkg/ingress` / `pkg/bootstrap` / `registry` / `envoy` / `istio` / `plugins` / `script` / `docker`）没有 `hgctl`、没有 `api`、没有 `client`，而 `script` 实际在 `tools/` 下、`tools/hgctl` 根本不存在（hgctl 在顶层且是独立 Go module）。要读源码，得先有一张以源码为准的表。

## Top-Level Layout

| 目录 | 内容 | 证据 |
| --- | --- | --- |
| `cmd/higress/` | 唯一入口，`main.go:28` 执行 `cmd.GetRootCommand().Execute()` | 整个控制器只有 serve / version 两个子命令（`pkg/cmd/root.go:28-29`） |
| `pkg/` | `bootstrap` `cert` `cmd` `common` `config` `ingress` `kube` 七个子包 | `pkg/config/constants/constants.go` 全文只有 7 个常量 |
| `api/` | CRD 的 proto 定义与生成物，`buf` + `cue-gen` 双工具链 | `api/gen.sh:6` `buf generate`、`:11` `cue-gen -verbose -f=./cue.yaml -crd=true` |
| `client/` | code-generator 产物：`apis` / `clientset` / `informers` / `lister` / `applyconfiguration` | 非手写，入口 `client/Makefile` |
| `registry/` | 服务来源 watcher 层，详见 [Service Registry Internals](/docs/CS/Framework/Higress/Service_Registry_Internals.md) | `registry/watcher.go` `registry/reconcile/` |
| `hgctl/` | **顶层、独立 go.mod**（`go.mod:316` `replace .../hgctl => ./hgctl`） | `tools/` 下只有 `hack` `linter` `plugin-release` `src`，**没有 `tools/hgctl`** |
| `plugins/` | `wasm-go` `wasm-rust` `wasm-cpp` `wasm-assemblyscript` `golang-filter` `release` | 源码文件数 526 / 23 / 29 / 9 / 98 |
| `helm/` | 两个 chart：`core`（控制面 + 数据面 + CRD）与 `higress`（console 子 chart） | `helm/core/crds/`、`helm/core/templates/configmap.yaml` |
| `istio/`、`envoy/` | 子模块挂载点（见本页"构建"一节） | 本机工作树为空，需 `make prebuild` |
| `test/` | `e2e` `gateway` `inference-extension` | — |
| `samples/` | `gateway-api` `hello-world` `loadbalance` `mcp` `nacos-discovery` `wasmplugin` `quickstart.yaml` | — |
| `changes/` | **不是版本 changelog**，现存 4 个 md 全是贡献流程记录 | 另有 `release-notes/` 目录 |

## hgctl Command Tree

命令树在 `hgctl/pkg/root.go:35-47` 的 `AddCommand`，**13 个顶层子命令**：`version`、`config`、`install`、`uninstall`、`upgrade`、`profile`、`dashboard`、`manifest`、`plugin`、`completion`、`code-debug`、`mcp`、`agent`。

> [!NOTE]
> 两条与文档相反的结论。① **`hgctl config` 是存在的**（文档站 hgctl 页没列它），但它的语义是**抓 xDS 配置**：二级命令为 `all` / `bootstrap` / `cluster` / `endpoint` / `listener` / `route`（`hgctl/pkg/config_cmd.go:45-50`），不是"profile / install / upgrade"那一组——后者是 root 的子命令，文档页把两者混为一谈了。② `hgctl plugin` 确实是一个子命令组，成员为 `build` / `install` / `uninstall` / `ls` / `test` / `config` / `init`（`hgctl/pkg/plugin/plugin.go:36-42`），其中 `test`（`plugin/test/test.go:28-32`）与 `config`（`plugin/config/config.go:26-27`）是二级动作；`agent` 是 `create` / `deploy` / `add`（`agent/agent.go:42-44`），`mcp` 只有 `add`（`agent/mcp.go:73`），`code-debug` 是 `start` / `stop`（`code_debug.go:44-45`），`dashboard` 覆盖 prom / grafana / envoy / console / controller-debug（`dashboard.go:96-116`）。

## CRD Definitions

三个 CRD 的 group / version / scope **来自 proto 上的 `+cue-gen` 注释，不是 `+kubebuilder` 标记**（`api/` 下 grep `kubebuilder` 零命中）：

| Kind | 定义位置 | groupName / version |
| --- | --- | --- |
| `McpBridge` | `api/networking/v1/mcp_bridge.proto:31` | `networking.higress.io` / `v1`，Namespaced；含 `RegistryConfig`（`type` / `domain` 标 REQUIRED）与 `proxies` 字段 |
| `Http2Rpc` | `api/networking/v1/http_2_rpc.proto:29` | `networking.higress.io` / `v1`，Namespaced |
| `WasmPlugin` | `api/extensions/v1alpha1/wasmplugin.proto:30` | **`extensions.higress.io` / `v1alpha1`**，Namespaced，categories `higress-io` / `extensions-higress-io` |

proto 里**没有 `plural:` marker**，复数形式（mcpbridges / http2rpcs / wasmplugins）由 cue-gen 派生，落地证据是生成的 CRD yaml：`helm/core/crds/customresourcedefinitions.gen.yaml` 依次在 `:7` wasmplugins、`:150` http2rpcs、`:237` mcpbridges，另有老版本 K8s 变体 `customresourcedefinitions.gen_lt1.16.yaml` 与独立的 `istio-envoyfilter.yaml`（EnvoyFilter，group `networking.istio.io`）。`api/kubernetes/customresourcedefinitions.gen.yaml` 是同源副本，由 `api/kubernetes/crd_contract.go` 保证两处一致。运行时探测 CRD 版本用的 JSONPath 表在 `pkg/kube/crd_version.go:53-55`。

> [!WARNING]
> 代码里还引用了**第四个 kind** `McpServer`（`pkg/ingress/kube/mcpserver/model.go:22`，Gvk `networking.higress.io/v1alpha1 Kind: McpServer`），但它既不在 `api/` 的生成源、也不在 `helm/core/crds` 三件套里——**这个 CRD 不由本仓的生成管线提供**。据此拼 `mcpservers.networking.higress.io` 的 yaml 前，要先确认它是 console 还是别处装的。

## Key Abstractions

`pkg/ingress/kube/common/controller.go` 是一串 `Wrapper*`：`ServiceKey:36`、`WrapperConfig:43`、`WrapperConfigWithRuleKey:48`、`WrapperGateway:53`、`WrapperHTTPRoute:127`、`WrapperVirtualService:153`、`WrapperTrafficPolicy:204`、`DestinationRuleWrapper:210`、`ServiceProxyConfig:216`、`ServiceWrapper:222`、`ProxyWrapper:253`，以及三个控制器接口 `IngressController:278`、`KIngressController:308`（Knative）、`GatewayController:332`。`model.go` 侧是转换的输入输出形状：`PathType:32`、`Options:96`、`BasicAuthRules:111`、`Rule:115`、`IngressDomainCache:122`、`ConvertOptions:183`、`IngressRouteCache:217`、`IngressRouteBuilder:309`（`Build()` 返回 `model.IngressRoute`）、`Protocol:377`、`IngressDomainBuilder:384`。

`schema.go:22` 的 `IngressIR` 定义了控制器对 pilot 声明的监听集合：**DestinationRule / EnvoyFilter / Gateway / ServiceEntry / VirtualService / WasmPlugin** 六项——这正是 `Config Pipeline` 里那六个被覆盖的 generator 的另一面。

两处容易找错地方：核心聚合类型 `model.IngressRoute` **定义在 pilot fork**（`model.go:22` import `istio.io/istio/pilot/pkg/model`），本仓只是消费方；`pkg/config/constants/constants.go` 只有 `DefaultIngressClass` / `DefaultGatewayClass`（都是 `higress`）、两个 Knative CRD 名、`ManagedGatewayController`、以及 `RegistryTypeLabelKey` / `RegistryNameLabelKey`（`higress-registry-type` / `higress-registry-name`）**七个常量**——端口、系统命名空间、finalizer 常量都不在这里（`pkg/` 全量 grep `finalizer` 零命中；命名空间走 `higressconfig.PodNamespace` 运行时参数）。`pkg/common/` 提供协议与分隔符枚举：`protocol.go:22-29`（TCP / HTTP / HTTP2 / HTTPS / GRPC / GRPCS / Dubbo / Unsupported）、`proxy.go:24-28`（ProxyType）、`symbol.go:21`（`SpecialSeparator = "#@"`）。

## Annotation Registry

`pkg/ingress/kube/annotations/` 共 47 个文件（能力实现约 24 个 + 同名 test）。注册表是 `NewAnnotationHandlerManager()`（`annotations.go:161`），内部五组：`parsers`（`:163-185`，**21 个**：canary / cors / downstreamTLS / sslPassthrough / redirect / rewrite / upstreamTLS / ipAccessControl / timeout / retry / loadBalance / localRateLimit / fallback / auth / mirror / destination / ignoreCaseMatching / match / headerControl / http2rpc / mcpServer）、`gatewayHandlers`（`:186-188`，只有 downstreamTLS）、`virtualServiceHandlers`（`:189-191`，只有 ipAccessControl）、`routeHandlers`（`:192-205`，12 个）、`trafficPolicyHandlers`（`:206-209`，upstreamTLS + loadBalance）。接口 `AnnotationHandler:145` 由这五类能力组合而成，`Parse():213` 遍历 parsers 把结果填进聚合结构体 `Ingress:47-89`（每个能力一个 `*Config` 字段）。

前缀常量在 `parser.go:25`（`nginx.ingress.kubernetes.io`，默认）与 `:28`（`higress.io`），拼接函数 `buildNginxAnnotationKey:256` / `buildHigressAnnotationKey:260`。

> [!WARNING]
> 文档说"两个前缀等价"，源码说得更准：**等价只对走 `*ASAP` 的能力成立，且 nginx 前缀优先**——`ParseStringASAP:130`（注释 `:128-129`："先试 nginx annotation，失败再试 Higress annotation"）、`ParseBoolASAP:87`、`ParseIntASAP:217`、`ParseInt32ASAP:224`、`HasASAP:249`。而 `destination`、`header-control`、`route-limit-*`、`match-*`、`http2rpc-name`、部分 `timeout` / `rewrite` key 走 `*ForHigress`，**只认 `higress.io` 前缀**。`nginx.ingress.kubernetes.io/auth-type` 则在 `auth.go:54` 明确标注 2.0.0 之后不再支持。迁移时把 `higress.io/destination` 改写成 nginx 前缀不会生效，就是这个原因。

注解相对 key 的源码清单（完整 key = 前缀 + `/` + 下列值，取自各文件的 const 块）：

| 能力 | 相对 key | 位置 | 前缀行为 |
| --- | --- | --- | --- |
| canary 家族 | `canary`、`-by-header`、`-by-header-value`、`-by-header-pattern`、`-by-cookie`、`-weight`、`-weight-total` | `canary.go:22-28` | ASAP |
| destination | `destination` | `destination.go:28` | 仅 `higress.io` |
| rewrite | `rewrite-path`、`rewrite-target`、`use-regex`、`full-path-regex`、`upstream-vhost` | `rewrite.go:26-30` | 混用 |
| 上游协议与 TLS | `backend-protocol`（默认 `HTTP`）、`proxy-ssl-secret`、`proxy-ssl-verify`、`proxy-ssl-name`、`proxy-ssl-server-name` | `upstreamtls.go:25,29-33` | ASAP |
| 下游 TLS | `auth-tls-secret`、`ssl-cipher`、`tls-min-protocol-version`、`tls-max-protocol-version` | `downstreamtls.go:31-35` | ASAP |
| 流量镜像 | `mirror-target-service`、`mirror-percentage`、`mirror-target-fqdn`、`mirror-target-fqdn-port` | `mirror.go:25-28` | ASAP（后两条是文档未列的 FQDN 直连形态） |
| 本地限流 | `route-limit-rpm`、`route-limit-rps`、`route-limit-burst-multiplier` | `local_rate_limit.go:26-28` | 仅 `higress.io` |
| Header 控制 | `request-header-control-{add,update,remove}`、`response-header-control-{add,update,remove}` | `header_control.go:28-35` | 仅 `higress.io` |
| 路由匹配 | `match-method`、`match-query`、`match-header`、`match-pseudo-header` | `match.go:29-32` | 仅 `higress.io`（**方法 / query / header 作为匹配条件的真实入口在这里**，文档站没有对应页面） |
| 负载均衡与会话 | 13 个 key，含 `affinity`（默认 cookie 名 `INGRESSCOOKIE`）、MCP 会话保持 `mcp-sse-stateful-param-name`（默认 `sessionId`） | `loadbalance.go:25-46` | ASAP |
| 重试 / 容灾 | `proxy-next-upstream*` 4 个（`retry.go:25-31`）；`default-backend` + `custom-http-errors`（`default_backend.go:27-28`），fallback 路由后缀 `-fallback` 并注入 `x-envoy-route-name` / `x-envoy-fallback-service`（`:31-33`） | 同左 | ASAP |
| 其余 | cors 7（`cors.go:28-34`）、redirect 6（`redirect.go:27-32`）、`whitelist-source-range`（`ip_access_control.go:23`）、`ignore-path-case`（`:22`）、`ssl-passthrough`（`ssl_passthrough.go:17`）、http2rpc 2（`http2rpc.go:22-23`）、mcp-server 家族 7（`mcpserver.go:25-31`） | 见各文件 | ASAP / ForHigress |

## ConfigMap Layer

`pkg/ingress/kube/configmap/` 由 `config.go` `controller.go` `global.go` `gzip.go` `mcp_server.go` `tracing.go` 组成。`config.go:28-29` 定下 `HigressConfigMapName = "higress-config"` 与 key `"higress"`；聚合结构体 `HigressConfig:36-44` 的字段映射是 `tracing→Tracing`、`gzip→Gzip`、`downstream→Downstream`（`global.go:62`）、`upstream→Upstream`（`global.go:76`）、`mcpServer→mcp_server.go`，外加 `disableXEnvoyHeaders` 与 `addXRealIpHeader`；默认值入口 `NewDefaultHigressConfig():46-58`。`global.go` 还有 `Http2:84` 与四个默认构造函数（`:176/:186/:197/:205`）与 `GlobalOptionController:214`；`controller.go:64` 的 `ConfigmapMgr` 在 `:140-146` 反序列化 `higress` 段。三个派生 EnvoyFilter 的名字写死在：`higress-config-tracing`（`tracing.go:33`）、`higress-config-gzip`（`gzip.go:32`）、`higress-config-mcp-server`（`mcp_server.go:126`）。

**`mesh` 段不在这个包里**——`HigressConfig` 没有 Mesh 字段，`mesh` 由 pilot fork 的 meshwatcher 消费（且拿到的是空对象，见 [Config Pipeline](/docs/CS/Framework/Higress/Config_Pipeline.md)），ConfigMap 挂载路径是 `/etc/istio/config`（`helm/core/templates/controller-deployment.yaml:286`），拼装逻辑在 `helm/core/templates/configmap.yaml:102`（`higress:`）与 `:131`（`mesh:`）。`higress-https` 则在 `pkg/cert` 解析（`config.go:33`、`controller.go:35`），实现细节见 [Certificates and ACME](/docs/CS/Framework/Higress/Certificates_and_ACME.md)。

## Plugin Source Distribution

**官方文档站的 41 款插件并不都在 wasm-go 里**，这是找源码时最容易空手而归的地方：

| 语言层 | 扩展目录 | 内容 |
| --- | --- | --- |
| `plugins/wasm-go/` | **53** 个 extensions | AI 全家桶、`mcp-server`、`mcp-router`、`cluster-key-rate-limit`、`traffic-tag`、`oidc`、`opa`、`waf`、`transformer`、`ext-auth`…；另有 `mcp-servers/`（约 56 个 `mcp-*` MCP server 源码 + `quark-search`、`amap-tools`）与 `examples/`（12 个示例目录，里面的 `key-auth`、`basic-auth` 是**示例不是实现**，别混） |
| `plugins/wasm-cpp/` | **12** 个，**snake_case 命名**，bazel 构建（根有 `WORKSPACE`） | `basic_auth`、`key_auth`、`jwt_auth`、`hmac_auth`、`oauth`、`bot_detect`、`request_block`、`key_rate_limit`、`custom_response`、`sni_misdirect`、`model_mapper`、`model_router`——**整个认证基础族都在这里**，每个目录含 `plugin.cc` / `BUILD` / `VERSION` |
| `plugins/wasm-rust/` | 1 个 | `ai-data-masking`（其余 6 个目录在 `example/` 下） |
| `plugins/wasm-assemblyscript/` | 少量 | `custom-response` 的第二实现（`asconfig.json`） |
| `plugins/golang-filter/` | 98 文件，独立 go.mod | **MCP Server Filter 的真身**：`main.go:13-14` 两次 `envoyHttp.RegisterHttpFilterFactoryAndConfigParser`，分别注册 `mcp-session` 与 `mcp-server` 两个 filter，子树 `mcp-server/{registry,servers}` 与 `mcp-session/handler`；构建 target `build-golang-filter` |
| `plugins/release/` | — | 发布管线产物区（`console/` 下 9 个目录：`ai-context-limit`、`ai-endpoint-picker`、`gw-error-format`、`hmac-auth-apisix`、`json-converter`、`log-request-response`、`mcp-router`、`nginx-rewrite-compatible`、`response-cache` + `plans/ evidence/ snapshots/`） |

按语言层数一遍就知道：**文档站的 41 与 wasm-go 的 53 是两个不相等的集合**。wasm-go 里约 20 个扩展没有文档页（含 `mcp-router`、Go 版 `model-router`、`nginx-rewrite-compatible`、`ai-context-limit`、`ai-endpoint-picker`、`ai-image-reader`、`api-workflow`、`jsonrpc-converter`、`log-request-response`、`response-cache`、`traffic-editor`、`gc-test`、`hello-world`、`http-call`、`streaming-body-example`、`test-redis-inject-spin`、`chatgpt-proxy`、`qwen3guard` 等），而文档收录的认证基础族在 wasm-cpp。上一版笔记据此写"41 款插件"是对的（那是**文档站口径**），但补一句"源码侧另有未入文档的扩展"更准确——`mcp-router` 此前被判为"未核实存在"，源码里它确实是一个目录。

## Build and Version Evidence

顶层 `Makefile` 只是 istio 式薄壳，**目标全部在 `Makefile.core.mk`**：`submodule:96`（`git submodule update --init`）、`prebuild:101`（依赖 submodule，跑 `tools/hack/prebuild.sh`）、`build:120`（产物只有一个 `./cmd/higress`，定义在 `:88`，经 `tools/hack/gobuild.sh`）、`build-hgctl:134`（含 multiarch / macos 变体 `:142/:149/:153`）、`docker-build:188`、`build-envoy:197`、`build-pilot:200` / `build-pilot-local:204`、`build-gateway:210` / `build-gateway-local:215`、`build-wasmplugins:234`、`gen-api:290` / `gen-client:293`、`build-gateway-api-pilot:362`，clean 系列 `:303-313` 逐个删 `external/*`。**几乎所有 build / test 都以 `prebuild` 为前置**。

`prebuild.sh` 做的事：`mkdir -p external/package`，把 `envoy/{go-control-plane,envoy}` 与 `istio/{api,client-go,pkg,istio,proxy}` **`cp -RP` 进 `external/`** 并写伪造 `.git`（`gitdir: /parent/.git/modules/...`），最后 `go mod tidy`。所以 **`external/` 在 clone 后默认不存在**，`go.mod:302-314` 的 replace 全指向它。

版本 pin 的三条硬证据（这几项在文档里拿不到）：

| 事实 | 值 | 出处 |
| --- | --- | --- |
| 主工程版本 | `v2.2.5` | `VERSION` 文件、`git describe` |
| Istio fork 分支 | **`istio-1.27`**（api / istio / client-go）；`istio/pkg` 单独走 **`istio-1.19`** | `.gitmodules` |
| Envoy 侧分支 | **`envoy-1.36`**（proxy / go-control-plane / envoy） | `.gitmodules` |
| console 版本线 | `higress-console: v2.1.9` | `DEP_VERSION`——⚠️ 与 standalone 仓 `release-provenance.json` 里的 **console 2.2.5** 不一致，见 [Standalone and All-in-One](/docs/CS/Framework/Higress/Standalone_and_AllInOne.md) |
| K8s 生态 pin | api / apimachinery / client-go / apiextensions / apiserver / component-base = **v0.34.1**；cli-runtime / kubectl = **v0.33.3**；controller-runtime v0.22.3 | `go.mod:284-300` |
| Go 版本 | `go 1.26.0` | `go.mod:3` |

## Unverified

`istio/` 与 `envoy/` 子模块在本机**均未 checkout**（`ls istio/istio` 空），`external/` 不存在 ⇒ fork 与 Envoy 侧的内部实现一律未核，包括 `model.IngressRoute` 字段、cue-gen 的 plural 派生规则（结论标推断）、`hgctl` 各命令 `Use:` 字符串字面量（一次 `grep 'Use:\s+"'` 返回空，与该文件确实存在命令定义相矛盾，故不作为"不存在"的结论）、端口与 finalizer 常量的真实定义处（很可能在 fork 的 `features` 或 helm values）、`plugins/release/` 九个工作目录的性质、`test/inference-extension` 与 `pkg/ingress/kube/gateway/istio/` 移植层的细节。

## Links

- [Config Pipeline](/docs/CS/Framework/Higress/Config_Pipeline.md)
- [Service Registry Internals](/docs/CS/Framework/Higress/Service_Registry_Internals.md)
- [Plugin System](/docs/CS/Framework/Higress/Plugin.md)
- [Traffic Governance](/docs/CS/Framework/Higress/Traffic_Governance.md)
- [Architecture](/docs/CS/Framework/Higress/Architecture.md)
- [Higress](/docs/CS/Framework/Higress/Higress.md)
- [Service Discovery](/docs/CS/Framework/Higress/Service_Discovery.md)

## References

- [Higress v2.2.5 源码](https://github.com/alibaba/higress/tree/v2.2.5)
- [源码阅读指引](https://higress.ai/docs/latest/dev/code/)
- [Higress 自定义 CRD 开发指引](https://higress.ai/docs/latest/dev/customresourcedefinition/)
- [Nginx Ingress Annotation 兼容说明](https://higress.ai/docs/latest/user/annotation/)
- [hgctl 工具使用说明](https://higress.ai/docs/latest/ops/hgctl/)
- [组件编译说明](https://higress.ai/docs/latest/dev/architecture/)
