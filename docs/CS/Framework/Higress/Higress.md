## Introduction

Higress 是阿里巴巴开源、已进入 CNCF Sandbox 的云原生 API 网关，基于 Istio 与 Envoy 构建，用 Wasm 插件（Go / Rust / JS）扩展能力，官方文档站当前收录 **41 款插件、5 个分类**。它诞生于阿里内部，用来解决 Tengine reload 损伤长连接、以及对 gRPC / Dubbo 流量负载均衡能力不足的问题；阿里云基于它构建云原生 API 网关产品，并用它支撑通义千问 App、百炼大模型 API、PAI 平台等 AI 业务。

> [!NOTE]
> **版本锚点**：本子树全部结论锚定开源最新 release **v2.2.5**（2026-10-04 发布），信源为官方文档站 `higress.ai/docs/latest/`（即 Astro Starlight 文档，`higress.cn` 为同一套内容的中文站）。两条与版本有关、容易被写错的事实：① **插件版本与主工程版本解耦**——仓库另有 `wasm-go-ai-proxy-v1.0.0`、`wasm-go-cluster-key-rate-limit-v1.0.0` 这类按插件打的 tag，官方插件镜像的稳定 tag 统一是 `1.0.0`，开发版是 `latest`；② 文档里的 `roadmap` 页是**计划表不是事实表**（它把 v2.2.0 的预计发布写成 2025-12、v2.3.0 写成 2026-06），不要据它推断某个特性"已发布/未发布"。

官方给出的使用场景是**四条**而不是三条：AI 网关、Kubernetes Ingress 网关、微服务网关、安全防护网关。把它们看成同一台网关的四个侧面是对的——[什么是 AI 网关](https://higress.ai/docs/latest/overview/what-is-higress/)的原文口径是 "AI Gateway = AI Native API Gateway"，即 AI 场景下 API 研发 / 供应 / 消费 / 观测各自演进出新能力，而不是另做一个产品。它与 [Spring Cloud Gateway](/docs/CS/Framework/Spring_Cloud/gateway.md)、[Nacos](/docs/CS/Framework/nacos/Nacos.md)、[Dubbo](/docs/CS/Framework/Dubbo/Dubbo.md)、[Sentinel](/docs/CS/Framework/Sentinel/Sentinel.md) 的集成关系见 [Spring Cloud Alibaba](/docs/CS/Framework/Spring_Cloud/Alibaba.md)。

## Three Threads

拆分这批笔记时反复用到三条判断，各分册只展开自己那一份，其余地方引用：

**一、先问"这个能力在哪一层"，再问"怎么配"。** 同一个需求可能落在四个完全不同的层：Ingress annotation、Higress 自有 CRD（`McpBridge` / `Http2Rpc`）、`WasmPlugin` 的 YAML、或者**只在控制台路由层有入口**。最典型的错位是模型级 Fallback：`ai-proxy` 里没有这个字段（它的 `failover` 摘的是同一厂商的 apiToken，`retryOnFailure` 只支持非流式重试），真正的降级要到控制台"AI 路由管理 → 降级配置"去配；同理，四层 TCP 路由走的是 Gateway API 的 `TCPRoute` 而不是任何 annotation，且受 `global.enableGatewayAPI`（默认 false）与版本区间两条约束。判错层，配置就静默不生效。

**二、插件的实际行为由 phase + priority + 作用域三者决定，不由插件名决定。** `ai-cache` 跑在**认证阶段 priority 10**，而 `ai-token-ratelimit`（600）、`ai-quota`（750）跑在**默认阶段**——所以缓存命中的请求可能根本走不到限流与配额；`frontend-gray` 名字在"转换"分类里，实际也在认证阶段；`oidc` / `opa` / `ext-auth` 三个认证插件**不走** `consumers` + `allow` + `global_auth` 模型；`opa` 的字段是 camelCase 而邻居都是 snake_case。完整的阶段与优先级表在 [Plugin System](/docs/CS/Framework/Higress/Plugin_System.md)。

**三、这个题目的二手描述普遍比官方文档乐观。** 本次逐条回文档核实，以下几条在现有资料里流传很广但**找不到一手出处**，本子树一律不写：`ai-security-guard` 的 "block / mask / audit 三种处置动作"（实际只有 `checkRequest` / `checkResponse` + `denyCode` / `denyMessage`，脱敏属于另一个插件 `ai-data-masking`）；"WAF 依赖 ModSecurity 引擎"（实现底座是 Coraza，兼容的是 SecLang 与 Phase 规范）；"多 API Key 轮询"（文档原文是**随机**选取）；指标端口 15090（三处证据只支持 15020）；"50+ 官方插件"（插件市场页自标 41 款）；"本地限流配 100 QPS、3 副本实际放行约 300 QPS"（两个限流插件正文都没有副本数与放大系数的任何表述，真正的"每实例"口径来自 `higress.io/route-limit-rps|rpm` annotation，还带一个默认 5 倍的 burst 放大）。

## How to Read This Subtree

按"接到一个需求 → 定位它在哪一层 → 再查具体字段"的顺序读：

理解[架构与控制面](/docs/CS/Framework/Higress/Architecture.md)是所有判断的前提：Higress 的控制面**不自己实现 xDS**，而是把 Ingress / Gateway API / 自有 CRD / annotation 翻译成一整套 Istio 资源，交给一个 istiod 的 fork 下发。由此推出两个结论——它为什么能同时吃四种配置入口，以及为什么内置的 `istio` 不等于独立安装的 Istio。数据面那侧的机制细节交给 [Envoy](/docs/CS/Framework/Istio/Envoy.md)，xDS 与 Wasm 的通用原理交给 [WasmPlugin](/docs/CS/Framework/Istio/WasmPlugin.md)，本子树不重述。

配置入口确定后，扩展能力看[插件体系](/docs/CS/Framework/Higress/Plugin_System.md)：作用域在控制台与 CRD 侧是**两套口径**（三级 vs 四级），热更新靠 ECDS 订阅而非重启，官方插件以 OCI 镜像分发。要自己写插件（Go SDK 的真实 API 名、外部 HTTP / Redis 调用、Go 1.24 编译换代）在 [Wasm Development](/docs/CS/Framework/Higress/Wasm_Development.md)。

流量与路由的日常操作集中在[Traffic Governance](/docs/CS/Framework/Higress/Traffic_Governance.md)：两个限流插件的配置面**完全不对称**，灰度有 annotation / 插件 / Kruise Rollout 三条路，nginx 注解兼容矩阵的实际分档是"兼容 / 部分兼容 / Higress 扩展"三档。后端服务从哪来、HTTP 怎么转 Dubbo，在 [Service Discovery and RPC](/docs/CS/Framework/Higress/Service_Discovery.md)。

安全与认证单列一页（[Security and Auth](/docs/CS/Framework/Higress/Security_and_Auth.md)），因为最容易写错的是"哪些插件属于同一个模型"：六个走 consumer，三个不走；而自动签发证书是**真实存在且默认开启**的，代价是一条很少人提到的限制——只对 Ingress 模式生效。观测（[Observability](/docs/CS/Framework/Higress/Observability.md)）只收通用三支柱，AI 侧的 token 计量与成本核算跟着 `ai-statistics` 写在 [AI Gateway](/docs/CS/Framework/Higress/AI_Gateway.md)，因为它与限流、配额是一组共生关系，拆开就看不出"缓存命中会绕过配额"这类后果。

[AI Gateway](/docs/CS/Framework/Higress/AI_Gateway.md) 是本子树写得最深的一篇：协议转换怎么发生、33 个厂商 type 字符串、负载均衡策略的真实名字（含一个**只有仓库 README、没有文档站页面**的 `ai-load-balancer`）、语义缓存在默认参数下为什么静默不命中、MCP 的三条互不相同的托管路径。最后，[Deployment and Ops](/docs/CS/Framework/Higress/Deployment_and_Ops.md) 覆盖三种部署形态（其中两种官方明写"没有大规模生产使用过"）、升级顺序、以及"配置正确但没生效"时必须按层定位的四段排障链。

## Links

- [Istio](/docs/CS/Framework/Istio/Istio.md)
- [Envoy](/docs/CS/Framework/Istio/Envoy.md)
- [WasmPlugin](/docs/CS/Framework/Istio/WasmPlugin.md)
- [Ingress](/docs/CS/Container/k8s/Ingress.md)
- [Nginx Compare](/docs/CS/CN/nginx/compare.md)
- [Spring Cloud Alibaba](/docs/CS/Framework/Spring_Cloud/Alibaba.md)

## References

- [Higress 是什么](https://higress.ai/docs/latest/overview/what-is-higress/)
- [Higress 参数配置](https://higress.ai/docs/latest/user/configurations/)
- [Mcp Bridge 配置说明](https://higress.ai/docs/latest/user/mcp-bridge/)
- [Higress 自定义 CRD 开发指引](https://higress.ai/docs/latest/dev/customresourcedefinition/)
- [Wasm 插件使用简介](https://higress.ai/docs/latest/user/plugins/intro/)
- [Higress 插件市场](https://higress.ai/plugins/)
- [版本计划](https://higress.ai/docs/latest/overview/roadmap/)
- [Higress GitHub 仓库](https://github.com/alibaba/higress)
