## Introduction

Higress 是阿里巴巴开源、已进入 CNCF Sandbox 的云原生 API 网关，基于 Istio 与 Envoy 构建，用 Wasm 插件（Go / Rust / JS）扩展能力，官方文档站当前收录 **41 款插件、5 个分类**。它诞生于阿里内部，用来解决 Tengine reload 损伤长连接、以及对 gRPC / Dubbo 流量负载均衡能力不足的问题；阿里云基于它构建云原生 API 网关产品，并用它支撑通义千问 App、百炼大模型 API、PAI 平台等 AI 业务。

> [!NOTE]
> **版本锚点**：本子树全部结论锚定开源最新 release **v2.2.5**（2026-10-04 发布，主仓 commit `4deae1dd`）。

官方给出的使用场景是**四条**而不是三条：AI 网关、Kubernetes Ingress 网关、微服务网关、安全防护网关。把它们看成同一台网关的四个侧面是对的——[什么是 AI 网关](https://higress.ai/docs/latest/overview/what-is-higress/)的原文口径是 "AI Gateway = AI Native API Gateway"，即 AI 场景下 API 研发 / 供应 / 消费 / 观测各自演进出新能力，而不是另做一个产品。



## How to Read This Subtree

按"接到一个需求 → 定位它在哪一层 → 再查具体字段"的顺序读：

理解[架构与控制面](/docs/CS/Framework/Higress/Architecture.md)是所有判断的前提：Higress 的控制面**不自己实现 xDS**，而是把 Ingress / Gateway API / 自有 CRD / annotation 翻译成一整套 Istio 资源，交给一个 istiod 的 fork 下发。由此推出两个结论——它为什么能同时吃四种配置入口，以及为什么内置的 `istio` 不等于独立安装的 Istio。数据面那侧的机制细节交给 [Envoy](/docs/CS/Framework/Istio/Envoy.md)，xDS 与 Wasm 的通用原理交给 [WasmPlugin](/docs/CS/Framework/Istio/WasmPlugin.md)，本子树不重述。

配置入口确定后，扩展能力看[插件体系](/docs/CS/Framework/Higress/Plugin.md)：作用域在控制台与 CRD 侧是**两套口径**（三级 vs 四级），热更新靠 ECDS 订阅而非重启，官方插件以 OCI 镜像分发；自己写插件（Go SDK 的真实 API 名、外部 HTTP / Redis 调用、Go 1.24 编译换代）也在同一篇的 Wasm 开发小节。

流量与路由的日常操作集中在[Traffic Governance](/docs/CS/Framework/Higress/Traffic_Governance.md)：两个限流插件的配置面**完全不对称**，灰度有 annotation / 插件 / Kruise Rollout 三条路，nginx 注解兼容矩阵的实际分档是"兼容 / 部分兼容 / Higress 扩展"三档。后端服务从哪来、HTTP 怎么转 Dubbo，在 [Service Discovery and RPC](/docs/CS/Framework/Higress/Service_Discovery.md)。

安全与认证单列一页（[Security and Auth](/docs/CS/Framework/Higress/Security_and_Auth.md)），因为最容易写错的是"哪些插件属于同一个模型"：六个走 consumer，三个不走；而自动签发证书是**真实存在且默认开启**的，代价是一条很少人提到的限制——只对 Ingress 模式生效。观测（[Observability](/docs/CS/Framework/Higress/Observability.md)）只收通用三支柱，AI 侧的 token 计量与成本核算跟着 `ai-statistics` 写在 [AI Gateway](/docs/CS/Framework/Higress/AI_Gateway.md)，因为它与限流、配额是一组共生关系，拆开就看不出"缓存命中会绕过配额"这类后果。

[AI Gateway](/docs/CS/Framework/Higress/AI_Gateway.md) 是本子树写得最深的一篇：协议转换怎么发生、33 个厂商 type 字符串、负载均衡策略的真实名字（含一个**只有仓库 README、没有文档站页面**的 `ai-load-balancer`）、语义缓存在默认参数下为什么静默不命中、MCP 的三条互不相同的托管路径。最后，[Deployment and Ops](/docs/CS/Framework/Higress/Deployment_and_Ops.md) 覆盖三种部署形态（其中两种官方明写"没有大规模生产使用过"）、升级顺序、以及"配置正确但没生效"时必须按层定位的四段排障链。

上面这些都以文档口径为主。**再往下还有一层源码级分册**，它们回答的是"为什么是这样"而不是"怎么配"，所有断言带 `路径:行号`：[Config Pipeline](/docs/CS/Framework/Higress/Config_Pipeline.md) 追一条配置从 informer 到 xDS 的每一跳（结论形状是 **pilot 反向 pull、Higress 每次 List 全量重算、Higress 侧没有任何 debounce 生效**）；[Source Map](/docs/CS/Framework/Higress/Source_Map.md) 是以源码为准的模块地图与 108 条注解 key 总表；[Service Registry Internals](/docs/CS/Framework/Higress/Service_Registry_Internals.md) 讲 `registry/` 这一层——它是 Higress 少数真正自己写的部分，也是"服务名为什么长这样、`redis.static` 为什么不写端口就连 80"的出处；[Standalone and All-in-One](/docs/CS/Framework/Higress/Standalone_and_AllInOne.md) 说清"没有 Kubernetes 怎么办"其实是 fork 一个 `sample-apiserver` 并把 CR 存到 Nacos 或文件树；[Certificates and ACME](/docs/CS/Framework/Higress/Certificates_and_ACME.md) 则是自动签发的真实边界——只有 HTTP-01、续期参数其实是个比例、多副本之间没有任何互斥。

```text
                        ┌─ Architecture ─┬─ Config Pipeline ─ Source Map
              枢纽 ─────┤                ├─ Service Registry Internals
                        │                ├─ Standalone and All-in-One
                        │                └─ Certificates and ACME
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
- [Mcp Bridge 配置说明](https://higress.ai/docs/latest/user/mcp-bridge/)
- [Higress 自定义 CRD 开发指引](https://higress.ai/docs/latest/dev/customresourcedefinition/)
- [Wasm 插件使用简介](https://higress.ai/docs/latest/user/plugins/intro/)
- [Higress 插件市场](https://higress.ai/plugins/)
- [版本计划](https://higress.ai/docs/latest/overview/roadmap/)
- [Higress GitHub 仓库](https://github.com/alibaba/higress)
