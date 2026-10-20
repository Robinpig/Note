## Introduction

官方对 "AI 网关" 的定义是一句定位而非功能表：**AI Gateway = AI Native API Gateway**，"AI 原生的意义在于，在这样的 API 网关里，AI 是一等公民"——API 研发、供应、消费、观测都基于 AI 场景演进出新能力。

落到实现上，Higress 的 AI 能力分散在**三个不同的层**。把三层混为一谈是这片内容所有错误的共同来源，也是配置静默不生效的高发区：

- **Wasm 插件层**：`ai-proxy`、`ai-cache`、`ai-token-ratelimit`、`ai-quota`、`ai-security-guard`、`ai-data-masking`、`ai-statistics`、`mcp-server`、`ai-load-balancer` 等，配置写进 `WasmPlugin` 的 YAML。这一层的完整字段口径、阶段与优先级、协议转换、限流配额、语义缓存、内容安全、MCP 托管、AI 可观测**全部收在 [Plugin](/docs/CS/Framework/Higress/Plugin.md)**，本页不再重述。
- **控制台路由层**：AI 服务提供者管理、AI 路由管理（域名、模型匹配方式、**降级配置**、请求消费者）。**模型级 Fallback 只存在于这一层**，插件 YAML 里没有对应字段。
- **网关内置层**：MCP Server Filter（golang-filter），走控制台"系统设置"改 `mcpServer` 配置项，不是插件。

## Console Routing Layer (Model-level Fallback)

同一个"高可用 / 降级"需求，在插件层和控制台路由层是两件事，字段没有重叠：

- `ai-proxy` 里的 `failover` 摘的是**同一厂商的 apiToken**（同厂商内换 key），`retryOnFailure` 只支持非流式请求的立即重试；多个 token 之间是**随机**选取，不是轮询。
- **换模型 / 换服务**的降级只能到控制台"AI 路由管理 → 为路由进行降级配置"去配，文档口径是"当请求目标服务失败（如限流、访问失败等）时，降级到阿里云 `qwen-turbo` 模型"。

所以"换 key 在插件里配，换模型只能在控制台配"，两者没有共享字段。这条边界也决定了为什么 `ai-quota`、`ai-token-ratelimit` 这类插件的"总额 / 限流"和"缓存命中绕过配额"这类后果必须连同插件层一起看——见 [Plugin](/docs/CS/Framework/Higress/Plugin.md)。

## Built-in MCP Server Filter

除了 `mcp-server` Wasm 插件（见 [Plugin](/docs/CS/Framework/Higress/Plugin.md)），MCP 还有两条**非插件**路径，名字高度相似，别和插件那条混为一谈。

**一、网关内置 MCP Server Filter（golang-filter）**。走的是完全另一条路：控制台 → 服务来源 → 路由配置（含"重写"策略）→ **系统设置 → 修改 higress 配置项中的 `mcpServer` → 将 `enable` 改为 `true` → 移除 `redis` 配置项 → 在 `match_list` 添加元素**（字段如 `match_rule_domain: "*"`、`match_rule_path: /mcp/sample`、`match_rule_type: prefix`）。它没有 WasmPlugin 配置页。源码真身在 `plugins/golang-filter/`（`main.go` 两次 `envoyHttp.RegisterHttpFilterFactoryAndConfigParser`，分别注册 `mcp-session` 与 `mcp-server` 两个 filter）。

**二、McpBridge 作为 MCP 注册源**。`enableMCPServer` 的文档说明逐字写着"**目前仅支持 nacos3 类型的服务来源**"，配套字段 `mcpServerExportDomains`（不填即所有域名暴露）与 `mcpServerBaseUrl`（要暴露的 url 或 url 前缀，"例如使用 nacos 聚合多个 mcp server 时"）。所以"nacos 能当 MCP server 注册源"是错的，**只有 nacos3 能**；`RegistryConfig.type` 枚举里 `nacos` / `nacos2` / `nacos3` 是三个并列值，而文档示例值仍写 `nacos2`。字段细节见 [Service Discovery](/docs/CS/Framework/Higress/Service_Discovery.md)。

## HiMarket

HiMarket 不是网关组件：官方定义是"基于 Higress AI 网关构建的**企业级 AI 开放平台**"，统一管理 LLM、MCP Server、Agent、Agent Skill、Agent Worker，平台"以 Higress 作为模型服务的网关代理，提供内容安全、Token 限流等防护能力"——即它不自己实现限流与安全，而是**编排 [Plugin](/docs/CS/Framework/Higress/Plugin.md) 里的那些网关插件**。

它的观测大盘同样不自建数据源，两种方案互斥：**SLS 方案（推荐）** 靠 `ai-statistics` + 阿里云 SLS 采集，依赖阿里云、商业化网关开箱即用；**数据库方案** 靠 `db-log-pusher` + `db-log-collector` + MySQL，完全开源、非阿里云环境适用，但**商业化网关不适用**。文档明确"两种方案的功能完全一致，区别仅在于数据存储和采集方式"。

## Links

- [Plugin](/docs/CS/Framework/Higress/Plugin.md)
- [Source Map](/docs/CS/Framework/Higress/Source_Map.md)
- [Observability](/docs/CS/Framework/Higress/Observability.md)
- [Service Discovery](/docs/CS/Framework/Higress/Service_Discovery.md)
- [Service Registry Internals](/docs/CS/Framework/Higress/Service_Registry_Internals.md)
- [Traffic Governance](/docs/CS/Framework/Higress/Traffic_Governance.md)
- [AI](/docs/CS/AI/AI.md)
- [Higress](/docs/CS/Framework/Higress/Higress.md)

## References

- [什么是 AI 网关](https://higress.ai/docs/latest/overview/what-is-higress/)
- [MCP Server 快速开始（对接现存 SSE Server）](https://higress.ai/docs/ai/mcp-with-sse/)
- [多模型代理](https://higress.ai/docs/ai/scene-guide/multi-proxy/)
- [一键部署 Higress AI 网关](https://higress.ai/docs/ai/quick-start/)
- [HiMarket 介绍](https://higress.ai/docs/himarket/himarket-introduction/)
- [可观测能力介绍](https://higress.ai/docs/himarket/himarket-observability-overview/)
