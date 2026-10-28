## Introduction

Higress 是阿里巴巴开源、已进入 CNCF Sandbox 的云原生 API 网关，基于 Istio 与 Envoy 构建，用 Wasm 插件（Go / Rust / JS）扩展能力，官方文档站当前收录 **41 款插件、5 个分类**。它诞生于阿里内部，用来解决 Tengine reload 损伤长连接、以及对 gRPC / Dubbo 流量负载均衡能力不足的问题；阿里云基于它构建云原生 API 网关产品，并用它支撑通义千问 App、百炼大模型 API、PAI 平台等 AI 业务。

> [!NOTE]
> **版本锚点**：本子树全部结论锚定开源最新 release **v2.2.5**（2026-10-04 发布，主仓 commit `4deae1dd`）。

官方给出的使用场景是**四条**而不是三条：AI 网关、Kubernetes Ingress 网关、微服务网关、安全防护网关。把它们看成同一台网关的四个侧面是对的——[什么是 AI 网关](https://higress.ai/docs/latest/overview/what-is-higress/)的原文口径是 "AI Gateway = AI Native API Gateway"，即 AI 场景下 API 研发 / 供应 / 消费 / 观测各自演进出新能力，而不是另做一个产品。



## Architecture

Higress 的架构判断只有一句话：**它不重写数据面，也不重写服务网格控制面，它写的是一层"翻译器"**。Ingress、Gateway API、Higress 自有 CRD、nginx 兼容 annotation 四种配置入口，全部被翻译成 Istio API 对象，再交给一个 istiod 的 fork 生成 xDS 下发给内嵌 Envoy 的数据面。理解了这条链路，很多看起来矛盾的现象就有了统一解释——为什么它能同时吃四种配置入口、为什么内置的 `istio` 不等于独立安装的 Istio、为什么一个 CRD 必须叫 `default` 才生效。

组件与官方口径（v2.2.5）：

| 组件 | 角色 | 实现形态 |
| --- | --- | --- |
| **Higress Console** | 管理面 | Java / SpringBoot 后端 + 前端应用；Helm 里是独立子 chart `higress-console`，K8s 下 Service 默认 `ClusterIP` |
| **Higress Controller** | 控制面 | Pod 内含 `higress-core` 与 `pilot` 两个容器；`higress-core.controller.replicas` 默认 **1**，Service 类型 `ClusterIP`，健康检查走 `/ready:8888` |
| **Higress Gateway** | 数据面 | 内嵌 Envoy；`higress-core.gateway.replicas` 默认 **2**，Service 默认 `LoadBalancer`，`kind` 可为 Deployment 或 DaemonSet |

官方对 Controller 的定义逐字是"会连接 Istio，用于生成 Istio API 对象，通过 xDS 协议发送给 Istio"（[组件编译说明](https://higress.ai/docs/latest/dev/architecture/)）——这句读起来别扭，但它精确地描述了分工：**生成对象的是 higress-core，把对象变成 xDS 的是 pilot**。

### Translation Chain

配置流转分四步，前三步都在 `higress-core` 容器里：

1. **监听**。`pkg/ingress` 下的各 controller 用 informer 机制监听 K8s 资源变化。监听范围由三个全局参数决定：`global.ingressClass`（默认 `higress`；设为 `nginx` 则监听 class 为 nginx **或为空**的 Ingress，设为空字符串则监听集群内全部 Ingress——这是平滑迁移期的关键开关）、`global.watchNamespace`（默认空，非空则只监听该命名空间，用于"每个业务命名空间一套独立网关"的多租户形态）、以及 `global.enableIstioAPI` / `global.enableGatewayAPI`（**默认都是 false**）。
2. **翻译**。核心实现是 `pkg/ingress/config/ingress_config.go`。文档明确写出的产物有两类：自定义 CRD 变更"实现相关业务逻辑，比如生成 istio EnvoyFilter 等"（[自定义 CRD 开发指引](https://higress.ai/docs/latest/dev/customresourcedefinition/)），以及 Higress `WasmPlugin` → Istio `WasmPlugin` 的 `convertIstioWasmPlugin`。至于 Ingress 侧，[源码阅读指引](https://higress.ai/docs/latest/dev/code/)的表述是"把 Ingress 资源转换为 Istio 资源"，**并未逐字列出 VirtualService / DestinationRule**——把它们写进对照表是合理的推断，但不是文档原话。
3. **汇聚**。`higress-core` 通过 **MCP over XDS** 把翻译结果同步给 pilot。这条通道在 Wasm 插件的下发链路里被明确画出（见 [Plugin System](/docs/CS/Framework/Higress/Plugin.md)）。
4. **下发**。pilot 生成 xDS，经 ADS/LDS 推给数据面。`global.onlyPushRouteCluster` 默认 **true**，即对 K8s 服务**只推送被路由关联到的 cluster**——副本数多、Service 多的集群里，这个默认值直接控制 Envoy 的内存与推送体量。

**无损生效**是这条链路的收益，官方口径是"配置变更毫秒级生效且业务无感"，动机正是它诞生时要解决的问题：Tengine / nginx 的 reload 对长连接业务有损。需要区分两件事：路由配置的动态生效来自 xDS 增量推送；**Wasm 插件的热更新来自 ECDS 订阅**，机制不同、代价不同，展开在 [Wasm 插件体系](/docs/CS/Framework/Higress/Plugin.md)。

### Custom CRDs

Higress 自有 CRD 的 group 是 `networking.higress.io`，两个版本的 `apiVersion` 各不相同，这是最容易写错的一处：

| Kind | apiVersion | 作用域与元信息 | 关键约束 |
| --- | --- | --- | --- |
| `McpBridge` | `networking.higress.io/v1` | Namespaced | **只监听 higress 安装命名空间下名为 `default` 的资源**，`metadata.name` 当前只能是 `default`；控制台入口是"服务来源" |
| `Http2Rpc` | `networking.higress.io/v1` | Namespaced，plural `http2rpcs`，categories `higress-io`，带 status 子资源 | 由 proto + cue-gen 定义（`higress.networking.v1.Http2Rpc`），靠 `higress.io/rpc-destination-name` 与 Ingress 手工对齐 |
| `WasmPlugin` | **`extensions.higress.io/v1alpha1`** | Namespaced（示例在 `higress-system`） | Higress 侧写法是 `defaultConfig` + `matchRules`；被转换成 Istio 的 `extensions.istio.io/v1alpha1` 后才是 `pluginConfig` + `selector` |

> [!WARNING]
> 两条经常同时出错的口径：① 旧资料里常见的 WasmPlugin YAML 用 `apiVersion: extensions.istio.io/v1alpha1` 配 `selector.matchLabels` ——那是**转换之后**、由 pilot 交给 Envoy 的形态，不是给 Higress 写的入口配置；给 Higress 写要用 `extensions.higress.io/v1alpha1` + `matchRules`。② 因为 `McpBridge` 只认一个 `default`，**多租户不能靠建多个 McpBridge 实现**，只能在它的 `registries` 数组里配多个服务来源。字段细节见 [Service Discovery](/docs/CS/Framework/Higress/Service_Discovery.md)。

**内置的 istio 不等于 Istio。** `global.enableIstioAPI` 默认 false 这件事本身就是边界声明：Higress 不假定你要用、也不能直接用完整的 Istio API。pilot 容器是 istiod 的 pilot 模块 fork，若干网格能力在这套形态里被关掉了——从 Helm 参数就能看出取舍：`PILOT_ENABLE_METADATA_EXCHANGE` 默认 **false**、`PILOT_ENABLE_CROSS_CLUSTER_WORKLOAD_ENTRY` 默认 **false**、`VALIDATION_ENABLED` 默认 **false**，而 `PILOT_SCOPE_GATEWAY_TO_NAMESPACE` 默认 **true**（网关只能访问自己命名空间的服务）。需要完整服务网格能力时应当单独安装 Istio。

> [!IMPORTANT]
> **而且这个 fork 不是另一个进程。** `go.mod:302-314` 用 replace 把 `istio.io/{api,pkg,client-go,istio}` 与 go-control-plane 全部指向构建期生成的 `./external/*`，`pkg/bootstrap/server.go` 直接 import `pilot/pkg/xds`、`pilot/pkg/config/aggregate`、`pilot/pkg/serviceregistry/aggregate`，并把同一个 `*xds.DiscoveryServer` 指针分别交给翻译层（`:240`）与证书模块（`:440`）。⇒ **没有 istiod 进程、没有 RPC / UDS 边界、也没有"外部控制器向 istiod 上传配置"的通道**，耦合强度是编译期 + 内存对象级；方向还是反的——是 pilot **反向 pull** Higress 的配置存储。这既解释了 Higress 为什么能零成本复用 pilot 的 xDS 实现，也解释了它为什么必须紧跟 fork 的内部 API 演进（`server.go:580-589` 因 istio 1.27 删掉 ledger 而整段注释）。逐跳证据在 [Config Pipeline](/docs/CS/Framework/Higress/Config_Pipeline.md)。

### Configuration Storage without Kubernetes

"是否必须有 Kubernetes"的官方答案是**不需要**：一行 Docker 命令即可启动，也支持虚拟机与物理机场景。独立部署的实现方式值得单独记一笔，因为它反过来印证了这套架构的解耦点在哪——**Standalone 没有改控制面一行代码，而是补了一个假的 kube-apiserver**：

| 服务 | 职责 |
| --- | --- |
| `apiserver` | **模拟 K8s API Server**，让 controller 仍然按"监听资源变化"的方式工作 |
| `controller` | 收集配置与服务列表 |
| `pilot` | 下发路由 |
| `gateway` | 数据面 |
| `console` | 管理界面 |

源码侧要修正两点。**其一，"5 个容器"是核心五件套，默认真正常驻约 10 个**（另有 nacos、plugin-server 与 prometheus / promtail / loki / grafana 四件套）。**其二，那个 apiserver 不是 k3s、不是 kine、不是 envtest，而是 Kubernetes `sample-apiserver` 的直接 fork**，注册约 21 类资源、对外就是标准 REST + list/watch，controller 拿自签证书生成的 kubeconfig 连它的 8443——所以主仓完全不需要知道下面是什么。

配置的持久化位置也因此不是 etcd：`--storage` 只有 `nacos`（默认）与 `file` 两个合法取值，CR 实例分别落成 Nacos 配置项（靠 `ListenConfig` 模拟 watch）或本地文件树（靠 fsnotify 模拟 watch）。**结论：Higress 的翻译链不依赖 etcd，只依赖"有一个能被 list/watch 的配置源"。** 容器拓扑、存储实现与可复现性凭据见 [Standalone and All-in-One](/docs/CS/Framework/Higress/Standalone_and_AllInOne.md)，部署命令与参数见 [Deployment and Ops](/docs/CS/Framework/Higress/Deployment_and_Ops.md)。

### Source Layout

[源码阅读指引](https://higress.ai/docs/latest/dev/code/)与 [自定义 CRD 开发指引](https://higress.ai/docs/latest/dev/customresourcedefinition/)给出的目录职责表（后者更细，取两表并集）：

> [!NOTE]
> 这两张表**已经滞后于 v2.2.5 的真实树**：表里没有 `hgctl`、没有 `client`，`script` 实际在 `tools/` 下，而 `tools/hgctl` 根本不存在——**hgctl 在仓库顶层且是独立 go module**（`go.mod:316` 的 replace 为证）。以源码为准的完整模块地图（含 `api/` 的 buf + cue-gen 生成管线、`client/` 的 code-generator 产物、14 个 ingress 子控制器、注解注册表、插件的四种语言层分布）在 [Source Map](/docs/CS/Framework/Higress/Source_Map.md)。

| 目录 | 内容 |
| --- | --- |
| `api` | Higress 所涉及操作的 Kubernetes API（CRD 的 proto 定义在这里，如 `api/networking/v1/http_2_rpc.proto`） |
| `client` | 集成 K8s client 做资源监听与下发 |
| `cmd` | 命令行参数解析 |
| `pkg/ingress` | Ingress 资源转换为 Istio 资源等相关代码 |
| `pkg/bootstrap` | 启动 gRPC / xDS / HTTP server 等 |
| `registry` | 对接多种注册中心做服务发现 |
| `plugins` | 插件 SDK 与官方内置插件代码 |
| `envoy` / `istio` | **依赖的 envoy 与 istio 仓库 commit** |
| `helm` | Helm 安装配置 |
| `tools` / `script` / `docker` | 编译、构建、镜像分发与本地测试环境脚本 |
| `samples` / `test` / `docs` | 示例 yaml / 单测与 e2e / 文档 |

**编译过程会自动执行 `make prebuild`，产出 `external` 目录**，里面是真正用到的 envoy 与 istio 依赖。改这两块的路径很特别：在 `external/` 下改 → 重命名 → 再 `make prebuild` → `diff -Naur` 生成 `.patch` → 把补丁 PR 到 Higress fork 的 envoy / istio 仓库。也就是说 Higress 对 Envoy 与 Istio 的改动是以**补丁形式维护在 fork 上**的，不是在上游里。

构建入口按改动范围分档：Controller 用 `make build`（本地产物）/ `make docker-build`（镜像）/ `make build-istio-local`（编译它用的 Istio pilot 镜像）；Gateway 分**快速构建** `make build-gateway-local`（没改 Envoy 本体时）与**完整构建** `make build-envoy`（产物落在 `external/package/`，需上传到下载服务器且文件名以架构结尾，如 `envoy-amd64.tar.gz`，再用 `ENVOY_PACKAGE_URL_PATTERN` 指过去）。

### Version Pins

v2.2.5 依赖的内核版本不再是未决项——本地源码树的 `.gitmodules` 直接给出 fork 分支：`istio/api`、`istio/istio`、`istio/client-go` 走 higress-group 的 **`istio-1.27`** 分支（`istio/pkg` 单独走 **`istio-1.19`**），`istio/proxy`、`envoy/go-control-plane`、`envoy/envoy` 走 **`envoy-1.36`**；`go.mod:284-300` 把 K8s 侧依赖钉在 **v0.34.1**（cli-runtime / kubectl 是 v0.33.3），`go.mod:3` 是 `go 1.26.0`。三条推论：控制面语义以 **Istio 1.27** 为基线、数据面以 **Envoy 1.36** 为基线、而 `DEP_VERSION` 里的 `higress-console: v2.1.9` 说明 **console 走独立发布线**（与 standalone 仓 `release-provenance.json` 钉的 console **2.2.5** 不同步）。完整证据表在 [Source Map](/docs/CS/Framework/Higress/Source_Map.md)。

仍未闭合的三类（`IngressRoute` 等核心聚合类型定义在 pilot fork 内、`istio/` 与 `envoy/` 子模块未 checkout 因此 fork 内部默认值本地不可核、`changes/` 不是版本 changelog、`McpServer` 这个 Gvk 由谁安装未确认）一律留在各分册的 `## Unverified`，不写进正文结论。

## How to Read This Subtree

按"接到一个需求 → 定位它在哪一层 → 再查具体字段"的顺序读：

理解[架构与控制面](/docs/CS/Framework/Higress/Higress.md?id=architecture)是所有判断的前提：Higress 的控制面**不自己实现 xDS**，而是把 Ingress / Gateway API / 自有 CRD / annotation 翻译成一整套 Istio 资源，交给一个 istiod 的 fork 下发。由此推出两个结论——它为什么能同时吃四种配置入口，以及为什么内置的 `istio` 不等于独立安装的 Istio。数据面那侧的机制细节交给 [Envoy](/docs/CS/Framework/Istio/Envoy.md)，xDS 与 Wasm 的通用原理交给 [WasmPlugin](/docs/CS/Framework/Istio/WasmPlugin.md)，本子树不重述。

配置入口确定后，扩展能力看[插件体系](/docs/CS/Framework/Higress/Plugin.md)：作用域在控制台与 CRD 侧是**两套口径**（三级 vs 四级），热更新靠 ECDS 订阅而非重启，官方插件以 OCI 镜像分发；自己写插件（Go SDK 的真实 API 名、外部 HTTP / Redis 调用、Go 1.24 编译换代）也在同一篇的 Wasm 开发小节。

流量与路由的日常操作集中在[Traffic Governance](/docs/CS/Framework/Higress/Traffic_Governance.md)：两个限流插件的配置面**完全不对称**，灰度有 annotation / 插件 / Kruise Rollout 三条路，nginx 注解兼容矩阵的实际分档是"兼容 / 部分兼容 / Higress 扩展"三档。后端服务从哪来、HTTP 怎么转 Dubbo，在 [Service Discovery and RPC](/docs/CS/Framework/Higress/Service_Discovery.md)。

安全与认证单列一页（[Security and Auth](/docs/CS/Framework/Higress/Security_and_Auth.md)），因为最容易写错的是"哪些插件属于同一个模型"：六个走 consumer，三个不走；而自动签发证书是**真实存在且默认开启**的，代价是一条很少人提到的限制——只对 Ingress 模式生效。观测（[Observability](/docs/CS/Framework/Higress/Observability.md)）只收通用三支柱，AI 侧的 token 计量与成本核算跟着 `ai-statistics` 写在 [AI Gateway](/docs/CS/Framework/Higress/AI_Gateway.md)，因为它与限流、配额是一组共生关系，拆开就看不出"缓存命中会绕过配额"这类后果。

[AI Gateway](/docs/CS/Framework/Higress/AI_Gateway.md) 是本子树写得最深的一篇：协议转换怎么发生、33 个厂商 type 字符串、负载均衡策略的真实名字（含一个**只有仓库 README、没有文档站页面**的 `ai-load-balancer`）、语义缓存在默认参数下为什么静默不命中、MCP 的三条互不相同的托管路径。最后，[Deployment and Ops](/docs/CS/Framework/Higress/Deployment_and_Ops.md) 覆盖三种部署形态（其中两种官方明写"没有大规模生产使用过"）、升级顺序、以及"配置正确但没生效"时必须按层定位的四段排障链。

上面这些都以文档口径为主。**再往下还有一层源码级分册**，它们回答的是"为什么是这样"而不是"怎么配"，所有断言带 `路径:行号`：[Config Pipeline](/docs/CS/Framework/Higress/Config_Pipeline.md) 追一条配置从 informer 到 xDS 的每一跳（结论形状是 **pilot 反向 pull、Higress 每次 List 全量重算、Higress 侧没有任何 debounce 生效**）；[Source Map](/docs/CS/Framework/Higress/Source_Map.md) 是以源码为准的模块地图与 108 条注解 key 总表；[Service Registry Internals](/docs/CS/Framework/Higress/Service_Registry_Internals.md) 讲 `registry/` 这一层——它是 Higress 少数真正自己写的部分，也是"服务名为什么长这样、`redis.static` 为什么不写端口就连 80"的出处；[Standalone and All-in-One](/docs/CS/Framework/Higress/Standalone_and_AllInOne.md) 说清"没有 Kubernetes 怎么办"其实是 fork 一个 `sample-apiserver` 并把 CR 存到 Nacos 或文件树；[Certificates and ACME](/docs/CS/Framework/Higress/Certificates_and_ACME.md) 则是自动签发的真实边界——只有 HTTP-01、续期参数其实是个比例、多副本之间没有任何互斥。

```text
              枢纽 ─────┬─ Config Pipeline ─ Source Map
                        ├─ Service Registry Internals
                        ├─ Standalone and All-in-One
                        ├─ Certificates and ACME
                        ├─ Plugin
                        ├─ AI Gateway
                        ├─ Traffic Governance ── Service Discovery
                        ├─ Security and Auth
                        └─ Observability ── Deployment and Ops
```

## Links

- [Istio](/docs/CS/Framework/Istio/Istio.md)
- [Envoy](/docs/CS/Framework/Istio/Envoy.md)
- [WasmPlugin](/docs/CS/Framework/Istio/WasmPlugin.md)
- [Ingress](/docs/CS/Container/k8s/Ingress.md)
- [Nginx Compare](/docs/CS/CN/nginx/compare.md)
- [Spring Cloud Alibaba](/docs/CS/Framework/Spring_Cloud/Alibaba.md)

## Verification Protocol

### 信源与核实口径（两层）

本子树的信源有两层：**官方文档站** `higress.ai/docs/latest/`（Astro Starlight 文档）与 **v2.2.5 tag 的源码**，凡文档与源码冲突**一律以源码为准**，且偏差散在各页正文里说。

- **取文档正文**：用 `curl` 抓页面 + 正则抽 `<div class="sl-markdown-content">`（**WebFetch 抓这些页会 120s 超时**）；**文档 URL 一律取自 `https://higress.ai/llms.txt`，不要凭印象拼路径**（`higress.io/en/docs/...` 返回 404）。
- **取源码**：`git clone --branch v2.2.5`（主仓）与 `--branch aio-v2.2.5`（`higress-standalone`，独立部署形态）。**不要假定本机有源码树**：`raw.githubusercontent` / `cdn.jsdelivr.net` / `unpkg` / `registry.npmjs.org` 在部分网络下全不可用，`api.github.com` 共享 60/小时极易打光，整仓 clone 与 blobless sparse clone 都可能超时失败——**没有源码时一律降级成文档口径并把"需回源码确认"的项显式写进该页 `## Unverified`**。
- **每篇分册末尾都有 `## Unverified`**，这是本子树的固定结构，也是硬禁区：那里面的东西一条都不许写进正文。

### 已证伪清单（尚未在 Three Threads 覆盖的条目）

以下条目曾以"事实"形态流传，已被源码或文档核实推翻：

- `ai-security-guard` 的 "block / mask / audit 三种处置"（只有检查+拒绝，脱敏属 `ai-data-masking`）
- "WAF 依赖 ModSecurity 引擎"（底座是 Coraza，兼容的是 SecLang 与 Phase 规范）
- "多 API Key 轮询"（文档原文是随机）
- "模型级 fallback 是 `ai-proxy` 的能力"（在控制台 AI 路由管理的降级配置）
- 指标端口 15090（三处证据只有 15020）
- "LITE_METRICS 精简指标开关"（无对应字段）
- "50+ 官方插件"（文档站标 41）
- "本地限流配 100 QPS、3 副本实际约 300 QPS"（无出处；官方"每实例"口径是 `higress.io/route-limit-rps|rpm`，且带默认 **5 倍** burst 放大）
- "nacos 可作 MCP server 注册源"（仅 `nacos3`，且这条限制在源码里是**软校验**——nacos2 配了只打 error 日志后静默跳过）
- "Http2Rpc 支持 Dubbo3 Triple"（官方逐字"暂不支持 Triple 协议"，Triple 走 gRPC 直接代理）
- 语义缓存阈值字段 `similarityThreshold`（实为 `vector.threshold` + `vector.thresholdRelation`，且默认组合对 Cosine / DotProduct 永不命中）

### 源码核对后推翻的三条（含本库自己上一版的错误）

① **`hgctl config` 确实存在**（`hgctl/pkg/config_cmd.go:45-50`，是抓 xDS 的 all / bootstrap / cluster / endpoint / listener / route），文档站 hgctl 页没提它——旧版把它写成"不存在的子命令"是**反了**；`profile` / `install` / `upgrade` 等是 root 的子命令。
② **`wrapper.ProcessStreamDone` 与 `ProcessStreamDoneBy` 两个名字都真实存在**（前者见主仓 `plugins/wasm-go/pkg/mcp/server/plugin.go:910`，后者是文档 SDK 页形态；`wrapper` 包在外部模块 `github.com/higress-group/wasm-go`，本地不可枚举导出项），不许再写"其中一个不存在"。
③ **文档的 41 款插件不都在 wasm-go**：认证基础族（`key_auth` / `basic_auth` / `jwt_auth` / `hmac_auth` / `oauth` / `bot_detect` / `request_block` / `key_rate_limit` / `custom_response` 等）在 **`plugins/wasm-cpp/`（snake_case、bazel）**，`ai-data-masking` 在 **`wasm-rust/`**；而 `plugins/wasm-go/extensions/` 有 **53** 个目录、约 20 个没有文档页（`mcp-router` 就在此列——**存在性成立、语义未读**，旧版"不存在 mcp-router"是错的）。

另有一批源码事实值得常驻：**pilot fork 与 Higress 控制器同进程**（`go.mod:302-314` replace + 共享 `*xds.DiscoveryServer` 指针，不是两个服务）、**配置是 pilot 反向 pull、每次 List 全量重算、Higress 侧 debounce 是死字段**、**`higress-config` 的 `mesh` 段不走 Higress 解析**（注入的是 `meshwatcher.NewTestWatcher` 空对象）、**ACME 只有 HTTP-01 且多副本零互斥**、**独立部署的 apiserver 是 `sample-apiserver` fork、CR 存 Nacos 或文件树而非 etcd**。

## References
- [Higress 是什么](https://higress.ai/docs/latest/overview/what-is-higress/)
- [Higress 参数配置](https://higress.ai/docs/latest/user/configurations/)
- [全局配置说明](https://higress.ai/docs/latest/user/configmap/)
- [Mcp Bridge 配置说明](https://higress.ai/docs/latest/user/mcp-bridge/)
- [Higress 自定义 CRD 开发指引](https://higress.ai/docs/latest/dev/customresourcedefinition/)
- [组件编译说明](https://higress.ai/docs/latest/dev/architecture/)
- [源码阅读指引](https://higress.ai/docs/latest/dev/code/)
- [基于 Docker Compose 进行独立部署](https://higress.ai/docs/latest/ops/deploy-by-docker-compose/)
- [Wasm 插件使用简介](https://higress.ai/docs/latest/user/plugins/intro/)
- [Higress 插件市场](https://higress.ai/plugins/)
- [版本计划](https://higress.ai/docs/latest/overview/roadmap/)
- [Higress GitHub 仓库](https://github.com/alibaba/higress)
