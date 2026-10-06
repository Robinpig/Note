## Introduction

Coze（中文名「扣子」）是字节跳动的一站式 AI Agent 开发平台。它同时存在两种形态：

- **云端 SaaS**：国内 `coze.cn`（扣子）、海外 `coze.com`，开箱即用、插件与发布渠道最丰富；
- **开源自建**：2025 年 7 月，字节把 Coze 最核心的两个引擎 **Coze Studio**（扣子开发平台）与 **Coze Loop**（扣子罗盘）以 **Apache 2.0** 协议开源，企业可在本地或私有云零授权费跑起「可视化开发 + 全链路观测」的一整套 Agent 工程设施。

它解决的是 [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) 从"想法"到"可运维服务"之间的那段工程距离：把模型、[工具与插件](/docs/CS/AI/LLM/Protocol/Tools.md)、[知识库（RAG）](/docs/CS/AI/RAG.md)、工作流、会话记忆、发布渠道和评测观测打包成一个可视化的产品，让业务工程师不必从零写编排代码。

## Studio vs Loop：工作台与望远镜

这是理解 Coze 的第一件事——**两个开源项目，分工明确**：

| 维度 | Coze Studio | Coze Loop |
|------|-------------|-----------|
| 定位 | 一站式 AI Agent 可视化开发平台 | Agent 全生命周期优化与观测平台 |
| 解决的问题 | 怎么快速搭出智能体、工作流、插件、知识库 | Prompt 怎么调、输出怎么评、线上异常怎么追 |
| 核心能力 | 智能体编排、工作流画布、插件商店、知识库、模型接入、API/SDK | Prompt Playground 与版本管理、多维度评测、Trace 全链路可观测、多语言 SDK |
| 典型用户 | 产品、低代码开发者、业务工程师 | 算法工程师、Prompt 工程师、SRE/运维 |
| 本地端口 | `http://localhost:8888` | `http://localhost:8082` |
| 仓库 | `coze-dev/coze-studio` | `coze-dev/cozeloop` |

一句话：**Studio 负责从 0 到 1 把 Agent 做出来，Loop 负责从 1 到 100 把它调稳、看好。** Studio 的社区热度（GitHub star 两万量级）远高于 Loop（五千量级），但后者恰好补足了多数可视化平台最缺的评测与观测。

## Coze Studio 的能力模块

| 模块 | 作用 |
|------|------|
| 模型服务 | 统一管理可用模型，可接入 OpenAI、火山方舟、DeepSeek、Ollama 等在线或离线模型 |
| 智能体 Agent | 配置人设与回复逻辑、绑定工作流/知识库/插件、多平台发布与版本管理 |
| 应用 App | 面向终端用户的完整应用，业务逻辑主要由工作流承载 |
| 工作流 Workflow | 可视化画布：LLM、插件、知识库、代码、数据库、条件分支、循环、变量等节点拖拽编排 |
| 插件 Plugin | 把第三方 API 或内部服务封装成可复用节点，是 Coze 的 [工具层](/docs/CS/AI/LLM/Protocol/Tools.md) |
| 知识库 Knowledge | 文档切片、向量化与检索，是 [RAG](/docs/CS/AI/RAG.md) 的产品化实现 |
| 数据库 | 内置表结构，存放业务结构化数据（Key-Value 式的业务记忆） |
| 提示词 | 集中管理 Prompt 模板并支持版本管理 |
| API 与 SDK | OpenAPI（创建会话、发起对话等）+ Chat SDK，用 PAT（Personal Access Token）认证 |

工作流画布是 Coze 的核心资产：它本质上是把 [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) 里那套"模型决策 → 框架执行 → 结果回填"的循环，变成了可拖拽的显式数据流。相比写代码，它的代价是复杂的循环/递归逻辑表达受限，收益是业务同学也能读懂和修改。

## 技术栈与部署

- **后端**：Golang，微服务架构，遵循领域驱动设计（DDD），可二次开发；
- **前端**：React + TypeScript；
- **运行时依赖**：Eino（CloudWeGo 的 LLM 应用框架）负责 Agent/编排抽象，FlowGram 提供工作流画布引擎；
- **部署**：Docker Compose 一键拉起（`coze-server` + MySQL + Redis + Elasticsearch 等），也提供 Helm Chart 上 K8s；
- **门槛**：最低 2 核 4 G，笔电即可跑。

```shell
git clone https://github.com/coze-dev/coze-studio.git
cd coze-studio
make web          # macOS/Linux；Windows 用 docker compose -f ./docker/docker-compose.yml up
# 启动后访问 http://localhost:8888/sign 注册
# 再到 http://localhost:8888/admin/#model-management 配置模型 API Key
```

模型要先用 YAML 模板配置（例如 `model_template_ark_doubao-*.yaml` 配置火山方舟模型 ID 与密钥），配好之后画布里才选得到模型——这一步几乎是所有自部署踩坑第一名。

**开源版与云版的差异**要心里有数：开源版开放的是引擎骨架与核心能力（上述模块），云版的插件数量、模板、发布渠道与托管资源更丰富；开源版插件支持自行开发，但生态规模小于云端。

## Coze Loop：让 Agent 不再是黑盒

Loop 覆盖上线前后的四个环节，正好对应 Agent 最容易"看不见"的部分：

1. **Prompt 开发与调试**：可视化 Playground，同一份输入对比不同模型/不同版本 Prompt 的输出，带版本管理，避免"改来改去发现还是第一版好"。
2. **系统化评测**：管理评测集、评测器、实验；从准确性、简洁性、合规性、召回效果等维度自动打分，把"感觉还行"变成可追溯的指标。
3. **全链路 Trace 可观测**：记录从用户输入到最终输出的完整链路，展示 Prompt 解析、模型调用、工具执行等关键节点与中间结果，异常自动捕获。
4. **SDK 上报**：提供 Go / Python / Java 等 SDK，可把观测与评测嵌入已有业务系统（对开源版与企业版都适用）。

于是可以形成一条正经的工程闭环：**Studio 搭建 → Loop 调优和评测 → SDK 上报线上 Trace → 从观测结果反推 Studio 迭代**。这条闭环与 [Self-Evolving](/docs/CS/AI/LLM/Agent/Practice/Self-Evolving.md) 里"评测驱动的自进化循环"是同一套思路，只是 Coze 把它做成了平台能力。

## 自部署的安全红线

两个项目的 README 都明确提醒：部署到公网前必须先做安全评估。常见风险清单：

- **默认开启注册**：公网暴露意味着任何人可建账号、消耗你的模型额度；
- **代码节点的 SSRF / 命令执行**：工作流里的 Python 执行环境是高价值攻击面，必须做网络出网限制与资源隔离；
- **监听地址**：不要让 Coze Server 直接绑 `0.0.0.0`，统一由前置 Nginx（或网关）承接 TLS 与鉴权；
- **水平越权**：部分 API 需前置权限校验，勿直接对外；
- **Elasticsearch 资源**：知识库检索依赖 ES，生产要给足内存并规划索引生命周期。

一句话原则：**把 Coze 当一台有执行能力的应用服务器对待，而不是一个静态网站。**

## 什么时候选 Coze

| 选 Coze 的信号 | 不选 Coze 的信号 |
|----------------|------------------|
| 面向国内业务，需要发布到飞书、抖音、微信等渠道 | 需要纯粹的"LLM 后端"，只对外提供 REST API |
| 想要「搭建 + 调优 + 观测」一体化，不想自己接 LangSmith/自建评测 | 团队主栈是 Java/Python 且要求深度定制源码行为 |
| 团队以产品/业务为主，低代码优先 | 需要代码级别的编排控制（用 [LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md) 或直接写 Harness） |
| 认可 Go 技术栈，可接受在 Go 侧做二次开发 | 强烈依赖某种特定向量库/数据源，平台没有对应插件 |

与 [Dify](/docs/CS/AI/LLM/Platform/Dify.md) 的核心取舍：**Coze 胜在"开发 + 观测"原生一体（Studio + Loop）与国内生态；Dify 胜在 RAG 管线的可调深度、社区规模与技能/插件生态。**

真正抢 Coze 生意的不只有开源同行：国内同赛道还有阿里云百炼、腾讯云 ADP、百度千帆、火山 HiAgent（字节自家对企业侧的那一半）等云厂商形态，它们卖的是"你已经在我的生态里"。完整竞品地图见 [LLM 应用开发平台](/docs/CS/AI/LLM/Platform/Platform.md) 的「竞争格局：五类玩家」。

## Links

- [LLM](/docs/CS/AI/LLM/LLM.md)
- [Vibe](/docs/CS/AI/LLM/Agent/Practice/Vibe.md)

## References

1. [Coze Studio 开源仓库](https://github.com/coze-dev/coze-studio)
2. [Coze Loop 开源仓库](https://github.com/coze-dev/cozeloop)
3. [扣子（Coze）官方文档](https://www.coze.cn/open/docs)
4. [Eino：字节 CloudWeGo 的 LLM 应用框架](https://github.com/cloudwego/eino)
5. [字节跳动 Coze 核心项目开源：Coze Studio 与 Coze Loop](https://news.aibase.cn/news/19989)
