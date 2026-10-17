## Introduction

官方对 "AI 网关" 的定义是一句定位而非功能表：**AI Gateway = AI Native API Gateway**，"AI 原生的意义在于，在这样的 API 网关里，AI 是一等公民"——API 研发、供应、消费、观测都基于 AI 场景演进出新能力。落到实现上，Higress 的 AI 能力分布在**三个不同的层**，这也是本页的组织方式：

- **Wasm 插件层**：`ai-proxy`、`ai-cache`、`ai-token-ratelimit`、`ai-quota`、`ai-security-guard`、`ai-data-masking`、`ai-statistics`、`mcp-server`、`ai-load-balancer` 等，配置写进 `WasmPlugin` 的 YAML。
- **控制台路由层**：AI 服务提供者管理、AI 路由管理（域名、模型匹配方式、**降级配置**、请求消费者）。**模型级 Fallback 只存在于这一层**，插件 YAML 里没有对应字段。
- **网关内置层**：MCP Server Filter（golang-filter），走控制台"系统设置"改 `mcpServer` 配置项，不是插件。

把三层混为一谈是这片内容所有错误的共同来源。阶段与优先级的全表在 [Plugin System](/docs/CS/Framework/Higress/Plugin_System.md)，本页只解释由它造成的后果。

## Provider Adaptation

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

## Key Pool, Failover, Retry

这三件事经常被合并成一句"高可用"，实际是三个不同层次、由两个不同层承载：

| 名字 | 在哪一层 | 摘除 / 重试的对象 | 关键字段与默认值 |
| --- | --- | --- | --- |
| `apiTokens` | 插件 | 多个凭证之间**随机选取** | 文档原文是"插件会在请求时随机进行选择"，**不是轮询 / round-robin**；部分厂商只支持单个 token |
| `failover` | 插件 | **apiToken**（同厂商内换 key） | `failureThreshold` 3 / `successThreshold` 1 / `healthCheckInterval` 5000ms / `healthCheckTimeout` 5000ms / `failoverOnStatus` `["4.","5."]`；**启用时 `healthCheckModel` 必填** |
| `retryOnFailure` | 插件 | 同一请求立即重试 | `maxRetries` 1 / `retryTimeout` 30000ms / `retryOnStatus` `["4.","5."]`；**目前仅支持非流式请求** |
| 模型级 Fallback | **控制台路由层** | **换一个模型 / 换一个服务** | 入口是"AI 路由管理 → 为路由进行降级配置"，文档口径"当请求目标服务失败（如限流、访问失败等）时，降级到阿里云 `qwen-turbo` 模型" |

同一个 `failover` 在控制台侧的形态是"AI 服务提供者管理 → 每个服务提供商单独配令牌降级策略"。也就是说：**换 key 在插件里配，换模型只能在控制台配**，两者没有重叠字段。

## Load Balancing over Models

`ai-load-balancer` 是本页唯一**没有文档站页面**的插件（文档 URL 取不到正文、`llms.txt` 索引里也没有），只存在于仓库 `plugins/wasm-go/extensions/ai-load-balancer/` 的 README 中——因此下面这组事实的信源层级低于本页其余内容，且**取自 main 分支而非 v2.2.5 tag**。顶层三字段 `lb_type`（`endpoint` | `cluster`，默认 `endpoint`）/ `lb_policy`（必填）/ `lb_config`（必填），文档要求网关版本 >= v2.1.5。

| `lb_policy` | 属于 | 语义 |
| --- | --- | --- |
| `global_least_request` | endpoint | 基于 Redis 的全局最小请求数（在途计数 ±1） |
| `prefix_cache` | endpoint | **按 prompt 前缀匹配选后端节点以复用 KV Cache**，miss 时静默回落到 `global_least_request`；`redisKeyTTL` 默认 1800s |
| `endpoint_metrics` / `metrics_based` | endpoint | 读 LLM 服务自己暴露的 metrics，`metric_policy` 取 `default`（即 gateway-api-inference-extension 算法实现）/ `least` / `most`，配 `target_metric`（示例用 `vllm:num_requests_waiting`、`vllm:num_requests_running`）与 `rate_limit`（默认 1） |
| `cluster_metrics` | cluster | 跨服务负载，`mode` 取 `LeastBusy` / `LeastTotalLatency` / `LeastFirstTokenLatency` / `AdaptiveScore` |
| `cluster_hash` | cluster | 读指定请求头做 **FNV-1a** 一致性 hash 固定到同一 cluster |

三条必须一起写的注意事项：**README 自身矛盾**——`lb_type: endpoint` 的策略清单写 `endpoint_metrics`，而下面所有配置示例写 `lb_policy: metrics_based`，照抄清单和照抄示例会得到不同结果；**`cluster_hash` 是硬失败**——所有 `weight` 之和必须为 100，且请求缺少 `hash_header`（默认 `x-mse-consumer`）时插件**直接返回 403**，不是静默降级；**`AdaptiveScore` 的失败率只用插件实例生命周期内的累计值**，README 明写"目前不使用时间窗口或衰减"，即重启实例就清零，别当熔断器历史用；它开启 `global_inflight_enabled` 后靠 Redis Lua 原子选服务，**Redis 异常时降级到本地打分、不阻断请求**。

关闭 `ai-load-balancer` 后策略不是"退化为轮询"，而是退化为服务本身内置策略集合（轮询、本地最小请求数、随机、一致性 hash）。

**`prefix_cache` 与 `ai-cache` 是完全不同的两件事**，尽管名字都带 cache：前者选 pod（复用后端 LLM 的 KV Cache），后者直接短路 LLM 调用。

## Metering, Rate Limit and Quota

`ai-token-ratelimit`（默认阶段、priority 600）基于 Redis 实现，两种模式互斥：`global_threshold`（规则级全局限流）与 `rule_items`（Key 级动态限流），外加必填的 `rule_name` 与 `redis`。**限流粒度只有四个时间档**：`token_per_second` / `token_per_minute` / `token_per_hour` / `token_per_day`——**没有 week / month，也没有区分输入 / 输出 token 的字段**（这正是它与 `ai-quota` 的分工缺口）。key 来源共 9 种：`limit_by_header` / `limit_by_param` / `limit_by_consumer` / `limit_by_cookie`，以及逐键分别计数的 `limit_by_per_header` / `per_param` / `per_consumer` / `per_cookie` / `per_ip`（**不存在裸 `limit_by_ip`**；per_ip 取值 `from-header-<名>` 或 `from-remote-addr`）。`limit_keys[].key` 支持 `regexp:` 前缀与 `*`。`rejected_code` 默认 429、`rejected_msg` 默认 `Too many requests`。Redis key 拼装口径是"规则名称 + 限流类型 + 限流 key 名称 + 限流 key 实际值"。

`ai-quota`（默认阶段、priority 750）管的是**总额**：给特定 consumer 分配固定 quota，并提供查询 / 刷新 / 增减三类管理动作（`admin_consumer` 必填、`admin_path` 默认 `/quota`、`redis_key_prefix` 默认 `chat_quota:`）。它有两个硬前置，文档原话："需要配合认证插件比如 `key-auth`、`jwt-auth` 等获取认证身份的 consumer 名称，同时**需要配合 `ai-statistics` 插件获取 AI Token 统计信息**"。

于是这几个插件是**共生关系而不是可独立使用**：`ai-quota` 自己不认身份、也不自己数 token；`ai-token-ratelimit` 虽有 `limit_by_consumer`，但 consumer 仍需认证插件产出。

> [!WARNING]
> 两个后果经常被忽略。① **`rule_items` 是命中第一条即停**（官方"后续规则不再执行"），不是所有命中规则叠加生效——部分二手博客称"混合配置时所有命中规则叠加、任一触发即 429"，与官方正文直接冲突。② **`ai-cache` 跑在认证阶段 priority 10，而限流与配额跑在默认阶段**，所以缓存命中的请求可能根本走不到 `ai-token-ratelimit` / `ai-quota`；不要把"token 限流"写成对所有请求一定生效。

## Semantic Cache

`ai-cache` 在认证阶段、priority 10（AI 插件里最早介入的一批，正是为了短路后端），**默认配置即可缓存 OpenAI 协议结果，支持流式与非流式**。它用同一个插件承载两种缓存，靠 `enableSemanticCache`（默认 true）切换；关闭即"使用字符串匹配的方式查找缓存，此时需要配置 `cache` 服务"。缓存键策略 `cacheKeyStrategy` 取 `lastQuestion`（默认）/ `allQuestions` / `disabled`。

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

## Safety and Masking

`ai-security-guard`（默认阶段、priority 300）**没有 block / mask / audit 三种处置动作**。它的配置面是 `checkRequest`（默认 false）/ `checkResponse`（默认 false）两个开关加 `denyCode` / `denyMessage`，**只有"合规检查 + 拒绝"一种处置**，既没有"脱敏放行"也没有"只记录不拦截"；**脱敏属于另一个插件 `ai-data-masking`**。两个隐性代价：`checkResponse` 生效时**会使流式响应变成非流式**；`denyCode` **默认是 200 而不是 4xx**（`denyMessage` 默认返回一个 OpenAI 格式、内容为"阿里云内容安全的建议回答"的响应）——用状态码判断是否被拦截会全部漏判。其余字段：`requestCheckService` 默认 `llm_query_moderation`、`responseCheckService` 默认 `llm_response_moderation`、`requestContentJsonPath` 默认 `messages.@reverse.0.content`、`responseContentJsonPath` 默认 `choices.0.message.content`、`responseStreamContentJsonPath` 默认 `choices.0.delta.content`。

它是**强绑定阿里云内容安全（Green）服务**的：`serviceName` / `servicePort` / `accessKey` / `secretKey` 必填，`serviceHost` 的说明就是"阿里云内容安全 endpoint 的域名"。开源 Higress 换检测方要走文档里"指定自定义内容安全检测服务"那条示例。同类绑定还有 `ai-rag`（对接阿里云向量检索服务）与 `ai-proxy` 的 `reasoningContentMode`（仅通义千问）。

`ai-data-masking`（认证阶段、priority 991）做敏感词的**拦截 + 替换**：处理范围三选一 `deny_openai`（默认 true）/ `deny_jsonpath`（默认 `[]`）/ `deny_raw`（默认 false，整个 body），另有 `system_deny`（内置规则，默认 false）、`deny_words`、`deny_code`（**默认同样 200**）、`deny_message`、`deny_content_type`。替换语义值得原文引用："将敏感词替换为脱敏字符串再传后端，保证敏感数据不出域；**部分脱敏数据在后端返回后可进行还原**；自定义规则支持标准正则和 **grok 规则**，替换字符串支持变量替换"。

## Three MCP Hosting Paths

MCP 有三条互不相同的路径，名字高度相似：

**一、`mcp-server` Wasm 插件**（默认阶段、priority 30）。定位"无需编写代码，将现有 REST API 转换为 AI 助手可调用的工具"，并复用网关的统一认证 / 鉴权 / 限流 / 可观测。`server.type` 只有两个取值且**默认是 `rest`**（REST-to-MCP：网关自己实现 MCP 协议端点，把 `tools/call` 翻译成对后端 REST API 的 HTTP 调用，需写 `tools` / `requestTemplate` / `responseTemplate`）；`mcp-proxy` 才是代理后端已有的 MCP server，此时 `server.mcpServerURL` 与 `server.transport` 必填，`transport` 取 `http`（StreamableHTTP，新协议）或 `sse`（旧协议），**不写 tools 就代理后端全部工具**。内置 MCP 服务器（文档举例 `quark-search`）只需填 `server.name`、无需配 tools。工具白名单 `allowTools` 不填即允许全部；另有**动态工具权限**——通过请求头下发白名单，规则是 header 不存在或为空串时用配置的 `allowTools`、为纯空白串（如 `"  ,  ,  "`）时**禁止全部**、有值时与 `allowTools` **取交集**。

安全默认值是这里最容易踩的一点：`server.passthroughAuthHeader` **默认 false**，未配置下游安全认证时网关会**主动移除 Authorization 头**，防止客户端凭证被错误传到后端。"配了需要 API Key 的后端 MCP 工具却总是 401"往往就是这个默认值。凭证体系分三级生效：工具级 `tools[].security`（`id` + `passthrough`）、工具级 `tools[].requestTemplate.security`（`id` + `credential`）、服务器级 `server.defaultDownstreamSecurity`（客户端 → 网关，覆盖所有 `tools/list` 与 `tools/call`）与 `server.defaultUpstreamSecurity`（网关 → 后端），**工具级可覆盖服务器级**；`passthrough=true` 时 `requestTemplate.security.credential` 被忽略。

**二、网关内置 MCP Server Filter（golang-filter）**。走的是完全另一条路：控制台 → 服务来源 → 路由配置（含"重写"策略）→ **系统设置 → 修改 higress 配置项中的 `mcpServer` → 将 `enable` 改为 `true` → 移除 `redis` 配置项 → 在 `match_list` 添加元素**（字段如 `match_rule_domain: "*"`、`match_rule_path: /mcp/sample`、`match_rule_type: prefix`）。它没有 WasmPlugin 配置页。

**三、McpBridge 作为 MCP 注册源**。`enableMCPServer` 的文档说明逐字写着"**目前仅支持 nacos3 类型的服务来源**"，配套字段 `mcpServerExportDomains`（不填即所有域名暴露）与 `mcpServerBaseUrl`（要暴露的 url 或 url 前缀，"例如使用 nacos 聚合多个 mcp server 时"）。所以"nacos 能当 MCP server 注册源"是错的，**只有 nacos3 能**；`RegistryConfig.type` 枚举里 `nacos` / `nacos2` / `nacos3` 是三个并列值，而文档示例值仍写 `nacos2`。字段细节见 [Service Discovery](/docs/CS/Framework/Higress/Service_Discovery.md)。

## AI Observability and Cost

`ai-statistics`（默认阶段、priority 200）是 AI 观测的数据源，定位"提供 AI 可观测基础能力，包括 metric, log, trace"，并有一条前置：**其后需接 `ai-proxy` 插件，不接的话需要用户自行配置才生效**。默认零配置即可得到输入 token、输出 token、**首个 token 的 rt（仅流式）**、请求总 rt，支持**网关 / 路由 / 服务 / 模型四个观测维度**。

六个 counter 指标共享前缀 `route_upstream_model_consumer_metric_`，后缀分别是 `input_token`、`output_token`、`llm_service_duration`（流式 + 非流式总耗时累加）、`llm_duration_count`、`llm_first_token_duration`（**流式请求首 token 延时累加，即 TTFT**）、`llm_stream_duration_count`；标签为 `ai_route`、`ai_cluster`、`ai_model`、`ai_consumer`。访问日志侧对应字段是 `input_token`、`output_token`、`model`、`llm_service_duration`、`llm_first_token_duration`。通用三支柱（指标端口、日志格式、追踪后端）在 [Observability](/docs/CS/Framework/Higress/Observability.md)。

扩展靠 `attributes`（每项 `key` / `value_source` / `value` / `rule` / `apply_to_log` / `apply_to_span`）：`value_source` 六种取值 `fixed_value` / `request_header` / `request_body` / `response_header` / `response_body` / `response_streaming_body`（body 类的 `value` 用 gjson jsonpath，header 类填 header key）；`rule` 决定从流式响应哪一段取值——`first` / `replace`（取最后一个）/ `append`（拼接，可用来取完整回答）。

**HiMarket** 不是网关组件：官方定义是"基于 Higress AI 网关构建的**企业级 AI 开放平台**"，统一管理 LLM、MCP Server、Agent、Agent Skill、Agent Worker，平台"以 Higress 作为模型服务的网关代理，提供内容安全、Token 限流等防护能力"——即它不自己实现限流与安全，而是**编排本页这些网关插件**。它的观测大盘同样不自建数据源，两种方案互斥：**SLS 方案（推荐）** 靠 `ai-statistics` + 阿里云 SLS 采集，依赖阿里云、商业化网关开箱即用；**数据库方案** 靠 `db-log-pusher` + `db-log-collector` + MySQL，完全开源、非阿里云环境适用，但**商业化网关不适用**。文档明确"两种方案的功能完全一致，区别仅在于数据存储和采集方式"。

## Remaining AI Plugins

| 插件 | 一句话定位（取自各页功能说明） |
| --- | --- |
| `ai-agent` | 可定制化 API AI Agent，支持 GET / POST 两类 API、多轮对话、流式与非流式 |
| `ai-rag` | 通过对接阿里云向量检索服务实现 LLM-RAG |
| `ai-search` | 集成搜索引擎（Google / Bing / Arxiv / Elasticsearch 等）实时结果，自动把搜索结果注入提示模板，按配置决定是否在回答中加引用来源 |
| `ai-intent` | LLM 意图识别，判断请求与某个领域 / agent 功能的契合度 |
| `ai-prompt-decorator` | 在 LLM 请求前后插入 prompt（可配合 `geo-ip` 携带用户地理位置） |
| `ai-prompt-template` | 快速构建同类型 AI 请求的模板 |
| `ai-json-resp` / `ai-history` / `ai-transformer` / `geo-ip` | 分别做 JSON 格式化、历史对话、请求响应转换、IP 地理位置；本次只读到标题，未逐页核实 |

## Claims That Do Not Hold

| 流传说法 | 一手文档口径 | 处置 |
| --- | --- | --- |
| `ai-security-guard` 支持 block / mask / audit | 只有 `checkRequest` / `checkResponse` + `denyCode` / `denyMessage` | 废弃，mask 归 `ai-data-masking` |
| 多 API Key 轮询（round-robin） | 多个 token 时**随机**选取 | 改 |
| 模型级 Fallback 是 `ai-proxy` 的能力 | 插件侧只有 apiToken 级 `failover`；模型级降级在**控制台 AI 路由管理** | 拆成两件事 |
| token 计量在 `ai-proxy` 内 | 由 `ai-statistics` 承担 | 归属改正 |
| 语义缓存阈值字段 `similarityThreshold` | `vector.threshold` + `vector.thresholdRelation`，默认组合不可用 | 字段名改正并写坑 |
| nacos（任意版本）可作 MCP 注册源 | 仅 `nacos3` | 收窄 |
| token 限流多条规则叠加生效 | `rule_items` 命中第一条即停 | 采信官方 |
| `openapi-to-mcpserver` 是独立工具 / 插件 | 官方文档站无页面，本次未核实存在性 | 不写 |
| 存在 `mcp-router` 插件 | 仅二手博客出现 | 不写 |

## Unverified

**源码层级全部未核实**（本机 clone 失败，见 [Architecture](/docs/CS/Framework/Higress/Architecture.md) 末节）：33 个 `type` 是否等于 `ai-proxy` 源码里的 provider 数、是否存在文档未收录的 type；`ai-load-balancer` 在 **v2.2.5** 的确切策略集合与默认值（含 `AdaptiveScore` 是否已进 2.2.5、`endpoint_metrics` 与 `metrics_based` 哪个是有效值）；`higress.io/load-balance` 注解的取值集合；`ai-proxy` 对 OpenAI Responses / Fine-Tuning 接口的支持；`ai-token-ratelimit` 是否也依赖 `ai-statistics` 取数（`ai-quota` 依赖已核实）；其余 AI 插件的执行阶段与优先级；控制台"AI 路由管理"最终落成哪种 K8s 对象；HiMarket"计量计费"由哪个组件承载、能否脱离 Higress 使用。

## Links

- [Plugin System](/docs/CS/Framework/Higress/Plugin_System.md)
- [Observability](/docs/CS/Framework/Higress/Observability.md)
- [Service Discovery](/docs/CS/Framework/Higress/Service_Discovery.md)
- [Traffic Governance](/docs/CS/Framework/Higress/Traffic_Governance.md)
- [AI](/docs/CS/AI/AI.md)
- [Higress](/docs/CS/Framework/Higress/Higress.md)

## References

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
