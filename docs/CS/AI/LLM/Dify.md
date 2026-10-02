## Introduction

Dify（源自 "Do It For You"）是 LangGenius 出品的开源 LLM 应用开发平台，2023 年 5 月开源，Apache 2.0（在多租户/转售等商用形态上有附加条件，企业落地前需核对 LICENSE），同时提供收费的 Dify Cloud。

它的定位是**裸 LLM API 与代码框架之间的产品化中间层**：把工作流编排、RAG 管线、Agent、插件、发布渠道、日志与运维打包成一个可视化后端，把一条 LLM 应用从「几百行的 Python 脚本」变成「团队可协作、可灰度、可观测的服务」。截至 2026 年它是 GitHub 上星标数最高的 LLM 应用平台之一（十万量级），文档与社区生态也最厚。

它不是一个 SaaS 聊天工具，也不是一个 Python SDK——理解这一点，是理解它和 [LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md)（代码框架）与 [Coze](/docs/CS/AI/LLM/Coze.md)（可视化 + 观测一体）之间取舍的前提。

## 它在技术栈里的位置

```
模型层（OpenAI / Anthropic / 国产模型 / Ollama / vLLM）
        │
 编排框架层  LangGraph、LangChain、LlamaIndex  ← 写代码，控制力最强
        │
 应用平台层  Dify / Coze / Flowise / Langflow  ← 可视化画布，自带 API、知识库、权限、日志
        │
 Agent 层   自己的业务 Agent（Agent Loop + Tools + Memory，见 Harness）
```

框架与平台的分界线：**框架给你积木，平台给你连 UI、账号、API、日志的一整套成品。** 用 LangGraph 你得自己写前端、自己管会话数据、自己做鉴权；用 Dify 这些是现成的，代价是深度定制时要顺着它的抽象走，且输出结果不再是"你自己的代码"。

## 应用类型

| 类型 | 形态 | 适合场景 |
|------|------|----------|
| 聊天助手 Chatbot | 单轮/多轮对话，带会话记忆 | 客服问答、政策助手 |
| 文本生成 Completion | 输入若干变量 → 一次生成 | 文案、摘要、翻译、提取 |
| Agent | Function Calling 或 ReAct 自主调用工具 | 查库 + 分析 + 生成报告的自主任务 |
| Chatflow | 带记忆与分支的对话工作流 | 意图识别 → 不同分支，需要多轮填槽 |
| Workflow | 批处理/自动化，无会话状态 | 定时抽取、批量打标、数据管道 |

最容易混淆的是这三者的边界：**Workflow 是确定性编排**（你画图，它按图执行），**Agent 是自主规划**（模型决定调什么、调几次），**Chatflow 是二者在对话场景的折中**。多数生产应用是"以 Workflow 为主骨架，在需要不确定性的局部嵌 Agent 节点"。

## 工作流画布

拖拽节点组成数据流，常用节点：开始（入参定义）、LLM、知识检索、代码执行（Python/JS 沙箱）、工具、HTTP 请求、条件分支、迭代 Iteration、循环 Loop、变量聚合、模板转换、人工输入 HITL、结束。

工程经验（都是踩坑总结，不是文档抄来的）：

- **一个工作流只做一件事**。别堆成巨石，拆成子流程用 HTTP 或参数化 workflow 调用。
- **条件节点当守卫**：在进入 LLM 节点前先校验输入合法性，脏输入不值得烧 token。
- **批量数据用 Iteration 而非 Loop**：Iteration 对子流程有更好的并行与隔离语义。
- **Code 节点负责清洗**：LLM 输出不稳定，交给下游前先用 Python/JS 校验、规范和兜底。
- **超时与重试必须配**：HTTP / LLM 节点都会超时，30–60 秒超时 + 1–2 次重试是常规配置。
- **变量别泛滥**：复杂流程里变量节点超过 20 个就该用一个 Code 节点聚合。

## RAG 知识管线

这是 Dify 相对其他可视化平台最扎实的一块，可配置项也最多：

| 环节 | 可调项 |
|------|--------|
| 摄取 | 本地文档（PDF/Word/Markdown 等）、Notion、Web 抓取、GitHub 仓库等来源 |
| 切分 | chunk 大小、重叠、分段策略（父子分段可兼顾召回与上下文完整性） |
| 索引 | 经济型（倒排/关键词）与高质量（向量 + 可选 rerank）两档 |
| 检索 | 向量语义检索 + BM25 关键词的**混合检索**，可选 rerank 模型二次排序 |
| 过滤 | 元数据过滤，把查询限定在文档子集内，无需重建索引 |
| 引用 | 结果携带来源，前端可展示引用出处 |

向量存储默认是 Postgres 上的 pgvector，也可接外部向量库；它与 [RAG](/docs/CS/AI/RAG.md) 笔记里「索引器 / 检索器 / 生成器」的三段式分层正好对应起来。调不好 RAG 时先怀疑切分与检索方式，而不是先怪模型。

## 插件体系与模型接入

Dify **v1.0.0（2025-02-17）** 是架构分水岭：把模型与工具从核心里解耦成可热插拔的插件，并上线 Dify Marketplace，第三方不必改核心代码就能扩展能力。插件打包为 `.difypkg`，可以贡献：

- 工具 Tool（OpenAPI 描述或自定义实现）
- 新的工作流节点类型
- 新的模型（LLM / Embedding / Rerank / TTS / ASR）
- UI 扩展（自定义配置界面）

模型侧覆盖 OpenAI、Anthropic、Azure、火山方舟、DeepSeek、通义、本地 Ollama/vLLM 等数十家；本地模型配上私有化部署，就构成一套内网可用的 LLM 应用底座。

## 近期版本：从「能搭」到「能打」（1.17 / Agent V2）

**v1.17.0（2026-08-28）** 集中解决了 Agent 的工程化落地问题：

- **Agent 运行时**：新增 E2B 云沙箱后端（环境变量 `DIFY_AGENT_RUNTIME_BACKEND` 切换，配套 `docker-compose.e2b.yaml`），不必自己维护代码沙箱容器；**Home Snapshots** 在发布时固化沙箱主目录状态，使已发布 Agent 每次运行都从同一文件系统状态启动（可复现）。
- **Workspace 级 Skill 管理**：可复用、带版本（草稿 → 发布 → 版本）的能力包，包含代码与工具定义，供 Agent 发现与调用——和 [Skill](/docs/CS/AI/LLM/Skill.md) 的思路一致。
- **上下文自动压缩**：长会话自动压缩历史，避免超出上下文窗口。
- **工作流可复用 LLM 变量**：一处配置 provider/model，全链路引用，换模型不用逐个节点改。
- **Loop / Iteration 内支持人工介入**：HITL 表单终于能塞进循环节点。
- **统一链路追踪**：可接入 Phoenix、LangSmith 等观测后端，并输出 GenAI 语义的 span。
- **安全与企业加固**：Cloudflare Turnstile、Azure Key Vault/KMS 集成、大量 SSRF 与权限加固。

⚠️ 从 1.16 升到 1.17 属于**破坏性变更**（Agent V2），升级前务必备份 database volume 并按官方迁移说明走。

## 发布形态与对外接口

一条应用可同时发布为多种形态，各有独立访问控制（公开/私有/白名单）与限流：

| 形态 | 说明 | 典型用法 |
|------|------|----------|
| Web App | 自动生成的聊天/表单页面 | 直接给业务用、演示 |
| REST API | 每个应用独立 POST 接口 | 系统集成，最灵活；常被 n8n / 后端服务调用 |
| 嵌入 Widget | JS SDK 嵌入现有网站 | 官网挂件、客服机器人 |
| MCP Server | 把应用暴露为 MCP 工具 | 被其他 Agent 调用 |

反过来，Dify 也**作为 MCP Client** 接入外部 MCP Server，把它们的工具注册进 Agent 工具列表。这种"双向 MCP"让它既是 [MCP](/docs/CS/AI/LLM/MCP.md) 生态里的生产者也是消费者，企业内部可借它统一工具目录。

## 部署与运维

| 组件 | 作用 |
|------|------|
| API / Worker | Python 服务 + Celery 异步任务队列 |
| Web | 前端（Next.js） |
| PostgreSQL + pgvector | 元数据 + 向量检索 |
| Redis | 缓存与 Celery broker |
| Sandbox | 独立的代码执行容器（另有 E2B 云沙箱可选） |
| Nginx | 反向代理，默认对外 80 端口 |
| Plugin Daemon | 1.0 之后插件运行时 |

官方 `docker compose up` 即可起全套，生产上要注意：为 Agent V2 预留更多内存（官方建议 6 G 起步、8 G 以上更稳）、备份 Postgres 与向量数据卷、把 Nginx 换成自己的网关处理 TLS 与 SSO、并规划 sandbox 的出网策略——沙箱一旦能随意出网，工作流里的 Code 节点就是一条 SSRF 通道。

## 什么时候选 Dify

| 选 Dify 的信号 | 不选 Dify 的信号 |
|----------------|------------------|
| 团队需要一个「LLM 应用后端」成品，而不是再写一套 CRUD | 需要深度控制执行循环（用 LangGraph 自研 [Harness](/docs/CS/AI/LLM/Harness.md)） |
| 重视私有化部署、数据不出内网 | 只想做个人/团队聊天 UI（Open WebUI、LobeChat 更轻） |
| RAG 需求复杂，要细调切分/混合检索/rerank | 需要几百个外部系统连接器（n8n 更强） |
| 需要把应用统一封装成 API/MCP 对外提供服务 | 极端性能敏感场景（平台层有额外开销） |

真正挤在同一条走廊上的对手分几拨：开源同行（[Coze](/docs/CS/AI/LLM/Coze.md) 开源版、FastGPT、RAGFlow、Flowise、Langflow）、自动化工具派（n8n、Make、Zapier Agents）、以及云厂商的企业版形态（阿里云百炼、腾讯云 ADP、百度千帆、火山 HiAgent，海外是 Copilot Studio、Gemini Enterprise Agent Platform、Bedrock Agents）。它们各自不在一个维度上竞争，完整地图见 [LLM 应用开发平台](/docs/CS/AI/LLM/Platform.md) 的「竞争格局：五类玩家」。

## Links

- [LLM](/docs/CS/AI/LLM/LLM.md)
- [Agent](/docs/CS/AI/LLM/Agent.md)

## References

1. [Dify 官网](https://dify.ai/)
2. [Dify 开源仓库](https://github.com/langgenius/dify)
3. [Dify 文档](https://docs.dify.ai/)
4. [Dify Marketplace（插件市场）](https://marketplace.dify.ai/)
5. [Dify 1.17.0 发布说明](https://github.com/langgenius/dify/releases)
6. [Dify 1.17.0 全面解读：Agent 沙箱云端化、技能管理、统一追踪](https://blog.51cto.com/moonfdd/14924280)
