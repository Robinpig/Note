## Introduction

LLM 应用开发平台（也称 LLMOps / Agent 平台）指的是一类**可视化地把模型、提示词、知识库、工具和工作流组装成可用服务的产品**。它介于"直接调模型 API"和"用代码框架自己写"之间：往上屏蔽掉模型差异，往下替你搭好画布、会话、权限、API、日志与观测。

本笔记是这个谱系的枢纽：[Coze](/docs/CS/AI/LLM/Platform/Coze.md)、[Dify](/docs/CS/AI/LLM/Platform/Dify.md) 各有一篇专记，这里解决三件事——**平台到底是什么（和解决什么问题）、各家怎么横向选、自部署有哪些红线**。

## 为什么需要平台层

把 [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) 的四个构成（Loop / Tools / Memory / Harness）套进平台看，对应关系很直接：

| Agent 构成 | 平台里的对应物 |
|-----------|----------------|
| Loop（决策循环） | 工作流画布 / Agent 节点（ReAct、Function Calling） |
| Tools | 插件、工具节点、[MCP](/docs/CS/AI/LLM/Protocol/MCP.md) Client/Server |
| Memory | 会话变量、内置数据库/表、长期记忆与上下文压缩 |
| Harness（执行与治理） | 它就是平台本身：权限、审计、日志、限流、沙箱、发布渠道 |

换句话说：**平台 = 被产品化的 Harness。** 自己写 Harness（见 [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)）控制力最强，但你要重复实现上面那一整行；平台把这些做成了默认件，代价是深度定制时要顺着它的抽象走。

平台真正替团队省下的，往往不是"搭 Agents 的时间"，而是下面这些没人想写的部分：

- **账号、权限、多租户**：谁可以看哪些应用，业务团队能自助操作而不必找工程师；
- **发布与集成**：Web App、REST API、嵌入挂件、Webhook、SDK——业务系统要用得上；
- **知识库的脏活**：文档解析、切分、向量化、混合检索、重排、引用溯源；
- **可观测与评测**：Trace、成本/延迟统计、会话日志、回归评测集；
- **模型切换**：换模型、按场景配不同模型、灰度与降级。

## 主流平台横向对比

| 平台 | 主打场景 | 技术栈 / 形态 | 协议 | 备注 |
|------|----------|---------------|------|------|
| [Dify](/docs/CS/AI/LLM/Platform/Dify.md) | 生产级 LLM 应用：工作流 + RAG + Agent + LLMOps | Python + React，Docker/K8s，云+自部署 | Apache 2.0 + 商用附加条件 | 社区与生态最成熟，RAG 管线可调项最多；近期重点在 Agent 运行时与沙箱 |
| [Coze](/docs/CS/AI/LLM/Platform/Coze.md) | 可视化搭建 + 全生命周期观测一体化 | Go + React（依赖 Eino / FlowGram），云+自部署 | Apache 2.0 | Studio（开发）+ Loop（评测/Trace）双仓；国内渠道与中文生态友好 |
| n8n | 通用流程自动化 + AI 节点 | Node.js，自部署为主 | Sustainable Use（fair-code，非 OSI 开源） | 400+ 外部系统集成最强；把 Agent 嵌进业务流程最合适，转售需商业授权 |
| [Langflow](/docs/CS/AI/LLM/LangTool/Langflow.md) | Python 侧的 LLM/RAG 原型可视化 | Python，可导出 API / MCP | MIT | 与 LangChain 生态同源，适合先在画布上试、再落到代码 |
| Flowise | 聊天机器人与 RAG，看重出原型速度和可嵌入挂件 | Node.js/TS，可嵌入挂件 + API | 核心开源，商用条款各版本不同 | JS/TS 团队友好；从原型到可嵌入助手的路径最短 |
| FastGPT | 知识库问答 / 文档助手 | 可视化 Flow，Docker 快速起 | Apache 2.0 + 附加条件（限制未经授权的多租户 SaaS） | 国产，自动 QA 对抽取提升召回；商业化 hosting 需看条款 |
| [RAGFlow](/docs/CS/AI/LLM/Platform/RAGFlow.md) | 复杂文档的深度理解式 RAG | Web UI + Python SDK | Apache 2.0 | DeepDoc 解析版式/表格/扫描 PDF 是差异化点，回答可带引用溯源；门槛偏高（4C16G 起） |
| AnythingLLM | 单机/小团队私有文档问答 | 桌面端 + Docker | MIT | 最快搭建个人私有 RAG，不适合团队级生产 |

> 协议一栏只作快速印象，**商用（尤其多租户转售）前一律以官方 LICENSE 为准**——n8n、Dify、FastGPT 都有限制性条款，Flowise 不同版本条款也不一致。

## 竞争格局：五类玩家

Coze 和 Dify 只是其中一类。到 2026 年，"低代码 LLM 应用平台"这条赛道已经挤进了五种不同出身的玩家，它们相互抢的场景其实有限，更多是各占一条**选型走廊**。给产品盲目排"TOP10"意义不大，看清出身更有用。

### 第一类：开源自建派

即上一节表格里的 Dify、Coze 开源版、Langflow、Flowise、FastGPT、RAGFlow、AnythingLLM、n8n。

**共性**：数据留在自己手里、许可费为零、可二开。**代价**：升级、备份、扩容、故障全都自己背；社区的"插件丰富"不等于"企业级稳定"。这条路的隐性门槛是运维能力，不是拖拉拽的能力。

### 第二类：云厂商 / 大厂生态派

它们的逻辑是**拿自家模型 + 云资源 + 办公入口做捆绑**，卖点是"顺手"而非"最强"。

| 平台 | 归属 | 真正的抓手 |
|------|------|-----------|
| 阿里云百炼（ModelStudio） | 阿里 | 通义底座 + 钉钉入口 + 阿里云账号/安全/资源管控打通 |
| 腾讯云 ADP | 腾讯 | 企业级 AgentOps；原生打通微信、企微、腾讯会议的审批流与组织架构。**腾讯元器**是另一条轨道，偏 C 端 Bot 创作与微信生态分发 |
| 百度千帆（原 AppBuilder）+ 文心智能体 | 百度 | RAG 与知识增强路线，长期扎根政务、国企、大型集团；另有对话式开发的"秒哒" |
| [火山引擎 HiAgent](/docs/CS/AI/LLM/Platform/HiAgent.md) | 字节 | 企业级私有化 Agent 工作站（Agent DevOps），与偏对外发布运营的**扣子**构成字节双线 |
| 360 智语 | 360 | 安全/信创/审计优先，产品线覆盖 L2 工作流 → L3 推理 Agent → L4 多智能体蜂群 |
| 蚂蚁数科 Agentar | 蚂蚁 | 金融级"可信智能体"：推理可解释、知识可追溯、评测可归因，内置金融 MCP 服务广场 |
| 讯飞星辰 Agent | 讯飞 | 语音、OCR、虚拟人前台差异化；配套开源 Astron Agent |
| 智谱清流 | 智谱 | GLM 底座与平台同源优化，叠加 AutoGLM 方向的执行代理 |

海外对应：Microsoft **Copilot Studio**（M365 / Teams / SharePoint / Graph grounding，治理靠 Entra + Purview，Copilot Credits 计费）、Google **Gemini Enterprise Agent Platform**（原 Vertex AI Agent Builder，2026 年 Cloud Next 改名并与 Agentspace 合并；ADK 写代码 + Agent Studio 画画布 + Agent Engine 跑运行）、**AWS Bedrock Agents / AgentCore**、**Salesforce Agentforce**（CRM 原生，Flex Credits）、IBM watsonx Orchestrate。

**选型真话**：这类平台的价值全部来自"你已经在这个生态里"——离开自家云与办公套件，优势迅速归零。它们也几乎都提供私有化版本，因为企业侧的数据出境与信创需求是真实存在的。IDC 口径下国内私有化智能体平台市场已有十几亿元规模，竞争焦点已从"能不能搭"后移到**评测、观测、安全治理、多 Agent 协同与迭代闭环**。

### 第三类：自动化工具派（AI 只是其中一个节点）

n8n、Make、Zapier Agents、Gumloop、Relay.app、Lindy、Relevance AI、Voiceflow、Botpress。

它们的底盘是**业务流程自动化**，AI 节点是后来加上去的。强项是触达外部系统（n8n 400+ 集成、Zapier 覆盖数千应用），弱项是 LLM 侧的原生能力——会话记忆、知识库精调、评测回归都比较薄。什么时候选：**业务的主体是一串跨系统动作，AI 只负责其中一两步**（如"客户邮件进来 → 模型分类提取 → 写回 CRM → 通知群"）。

### 第四类：代码框架派（不是产品，是积木）

[LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md)、CrewAI、OpenAI Agents SDK、Claude Agent SDK、[Pydantic AI](/docs/CS/AI/LLM/PydanticAI.md)。

这一派内部的层次关系（Harness / Framework / Runtime / Platform）与选型路径，见 [LLM 应用开发框架](/docs/CS/AI/LangTools.md)。

其中 Pydantic AI 的定位最"反平台"：它不做画布也不做运维台，只解决**单个类型安全的 Agent 如何可靠地嵌进真实代码库**（结构化输出校验、依赖注入、用量硬约束、OpenTelemetry 追踪）。画布表达不出来的那些东西，答案往往就在这里。

画布表达不了的东西在这里表达：多 Agent 监督/分工、自定义记忆、持久执行与断点恢复、逐节点超时。代价是你要自己承担编排、托管、观测、提示词版本管理和 on-call。它是"什么时候应该离开平台"那一节的答案（见下文）。

### 第五类：模型厂商的一站式（往往最不稳的一类）

模型厂商也会下场做可视化搭建层。典型如 OpenAI **AgentKit**（Agents SDK + 可视化 Agent Builder + ChatKit 嵌入 UI + 评测与 Trace）。

⚠️ **一条时效性事实**：OpenAI 已于 2026-06-03 宣布 **Agent Builder（可视化画布）将在 2026-11-30 退役**，官方建议迁往 Agents SDK 或 ChatGPT 内的 Workspace Agents，ChatKit 不受影响。

这件事比它看起来更重要，可以直接改写成一条选型原则：**可视化画布是厂商的"产品表面"，SDK、协议和数据模型才是能沉淀的东西。** 厂商的战略风向一变，画布是最先被砍的那一层；而把核心逻辑押在 [MCP](/docs/CS/AI/LLM/Protocol/MCP.md) 这类协议与自有代码上，迁移成本就可控得多——这也是 [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) 强调"沉淀到自己的执行面"的现实依据。

### 五类边界速览

| 类型 | 强项 | 弱项 | 什么时候选 |
|------|------|------|-----------|
| 开源自建派 | 数据主权、零许可费、可二开 | 运维自担、企业级能力薄 | 私有化/信创/要把治理权握在自己手里 |
| 云厂商派 | 生态打通、合规组件齐全、有人兜底 | 锁云原生生态，跨云几乎不可行 | 已经重仓某朵云与其办公套件 |
| 自动化派 | 外部系统集成数量碾压 | LLM 原生能力（记忆/知识库/评测）弱 | 跨系统业务流程，AI 只是其中一步 |
| 代码框架派 | 表达力上限最高，沉淀为自有资产 | 一切都得自己写 | 复杂状态机、长任务、必须先上审计再上线 |
| 模型厂商一站式 | 与该厂商模型配合最顺、起步最快 | 画布层可能被砍，锁定单一模型生态 | 快速验证，或已完全绑定该厂商 |

## 怎么选：一张决策树

```
先判数据主权（一票否决）
├─ 数据必须留在内网 / 信创环境
│   ├─ 有运维能力 → 开源自建派（Dify / Coze 开源 / FastGPT / RAGFlow）
│   └─ 没有运维能力 → 云厂商的私有化版本（腾讯云 ADP、火山 HiAgent、阿里云百炼专属版…）
└─ 数据可以上云
    ├─ 已重仓某朵云与其办公套件 → 直接用那家的（百炼/ADP/千帆/HiAgent，或 Copilot Studio / Gemini / Bedrock）
    ├─ 要快速验证想法、预算有限 → Coze 云版 / Dify Cloud / Flowise
    └─ 追求可控与可迁移 → 开源自建（同上）

再看需求主体是什么
├─ 业务流程自动化（CRM/工单/邮件/表格），AI 只是其中一步 → n8n / Make / Zapier Agents
├─ 主打文档问答 / 知识库助手
│   ├─ 文档复杂（表格、扫描件、版式）→ RAGFlow
│   ├─ 需要快速私有化、小团队 → FastGPT / AnythingLLM
│   └─ 需要可调的 RAG 管线 + 生产运维 → Dify
├─ 想要「搭建 + 评测 + 观测」一体 / 国内渠道发布 → Coze（Studio + Loop）
├─ 强监管 / 要审计追溯（金融、政企）→ 蚂蚁 Agentar、360 智语，或退回自研
├─ 团队 Python 为主，画布只是过渡最终要落地代码 → Langflow（或 LangGraph）
├─ 团队 JS/TS 为主，要快速出可嵌入的对话助手 → Flowise
└─ 需要深度控制执行循环 / 长任务状态机 / 严格合规审计
    → 别用平台，写自己的 Harness（LangGraph + 自研）
```

选平台时真正该先回答的三个问题（比功能清单有用得多）：**数据住在哪？谁来维护它？这个 Agent 被允许做哪些动作？** 这三个答案含糊时，讨论平台选型为时过早。

另有一条经验：**功能区对比几乎总是无效信息**——到了 2026 年，主流平台都有画布、都能接知识库、都能发 API。真正的差异都在不那么显眼的地方：观测能否归因到单步、成本能否解释给财务听、失败能否复盘、换人会不会失传。

## 什么时候应该离开平台

平台解决的是"大多数应用的共性部分"，它会在下面这些地方开始成为负担：

- **复杂的状态与容错**：长任务、暂停/恢复、分支重放、精细超时——画布表达不了，需要 LangGraph 式的持久执行；
- **非标准数据源**：专有的内部协议、奇特的检索链路（multi-hop、图检索），插件抽象反而是墙；
- **强合规与审计**：要给每一次工具调用产出可验证凭证时，可视化黑盒不够用；
- **极致性能/成本**：平台层的额外开销在超大批量场景会被放大；
- **想要沉淀成自家能力**：平台上的成果难以导出为自有代码资产（画布 JSON ≠ 可维护 codebase）。

常见折中路线：**用平台做前 80%（原型、知识库、灰度、给业务自助操作），把真正复杂的确定性部分写成服务，用 HTTP / MCP 节点接回画布。**

## 自部署通用红线

不管选哪家，私有化部署都会撞上同一批问题：

1. **鉴权先行**：默认注册必须关掉或加白名单；平台对内是可信工具、对外则是一台带代码执行能力的服务器。
2. **沙箱出网策略**：工作流里的代码节点（Python/JS）是 SSRF 与命令执行的一号攻击面，限制出网、给资源上限、定期打补丁。
3. **不要直接暴露 0.0.0.0**：统一由网关承接 TLS、SSO 和限流。
4. **数据与版本**：Postgres/向量库/Redis 都要定备份策略；跨大版本升级（如 Dify 1.16 → 1.17 的 Agent V2）先备份并在预发演练。
5. **模型配额与成本**：给 API Key 设额度上限，给应用设用量限额，否则一个失控的循环能把额度烧穿。
6. **观测要接全**：Trace 一定要攒起来，否则线上质量问题的归因只能靠猜——这一步对应 Coze Loop 的评测/Trace 或 Dify 的接入 Phoenix / LangSmith。
7. **向量库容量规划**：知识库规模增长比预期快，提前算好维度 × 条数的内存占用和索引策略。

## Links

- [LLM](/docs/CS/AI/LLM/LLM.md)
- [Tools](/docs/CS/AI/LLM/Protocol/Tools.md)
- [Skill](/docs/CS/AI/LLM/Agent/Theory/Skill.md)
- [RAG](/docs/CS/AI/RAG.md)
- [Transformer](/docs/CS/AI/Transformer.md)

## References

1. [10 Open-Source No-Code Platforms for LLMs & RAG（含各平台协议核对）](https://kiadev.net/news/2026-07-19-open-source-no-code-llm-platforms)
2. [Visual Agent Builder: Langflow vs. Flowise vs. n8n（含 fair-code 协议差异）](https://blckalpaca.at/en/knowledge-base/ai-agents/ai-agent-frameworks-comparison/langflow-vs-flowise-vs-n8n)
3. [n8n 开源仓库](https://github.com/n8n-io/n8n)
4. [RAGFlow 开源仓库](https://github.com/infiniflow/ragflow)
5. [FastGPT 开源仓库](https://github.com/labring/FastGPT)
6. [Langflow 开源仓库](https://github.com/langflow-ai/langflow)
7. [2026 中国智能体平台全景盘点：主流阵营对比与选型指南](https://tech.ifeng.com/c/8wHT8z2482H)
8. [2026 企业级 AI 开发平台选型评估（海比研究院）](https://www.sohu.com/a/1077009138_434604)
9. [Best AI Agent Platforms of 2026: Ranked & Reviewed（含 OpenAI Agent Builder 退役说明）](https://www.make.com/en/blog/best-ai-agent-platforms)
10. [13 Best AI Agent Builders in 2026 Compared](https://www.testmuai.com/blog/best-ai-agent-builder/)
