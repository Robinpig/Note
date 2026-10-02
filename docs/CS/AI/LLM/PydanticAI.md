## Introduction

Pydantic AI 是 Pydantic 公司（[FastAPI](https://fastapi.tiangolo.com/) 同出一门）出品的 **Python Agent 框架**，MIT 许可。它把 Pydantic 那套"用类型标注描述数据契约"的思路搬进了 LLM 应用：**工具参数、依赖注入、结构化输出全部是普通 Python 类型标注**，模型返回不对就会拿到一条类型化错误并被自动要求重试，而不是让脏数据一路流到业务代码里。

版本节奏值得记：V1 GA 于 **2025-09-04**，带着明确的 API 稳定性承诺；V2 于 **2026-06-23** 稳定发布，同时 V1 保留为兼容线继续维护——这在频繁 Breaking Change 的 Agent 框架圈子里是份很难得的升级记录。

它与 [LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md) 解决的是不同层的问题：**Pydantic AI 强在"单个类型安全的 Agent 能否可靠地嵌进真实代码库"，LangGraph 强在"多步有状态图 + 检查点 + 人在环路"。** 两者并不互斥，常见组合是用 Pydantic AI 写类型安全的 Agent 作为节点，上面再架一层编排。

## 四个支柱

| 支柱 | 说明 |
|------|------|
| **结构化校验输出** | 目标 schema 声明为 Pydantic 模型；Agent 保证交付匹配该 schema 的对象，否则抛校验错误并按提示让模型重试 |
| **依赖注入** | 数据库连接、HTTP 客户端、配置、鉴权上下文以类型注入 Agent，业务逻辑与 Agent 定义解耦；单元测试可以直接 mock（和 FastAPI 的直觉完全一致） |
| **模型无关** | OpenAI、Anthropic、Google、AWS Bedrock、Azure、Groq、Mistral、xAI 等，另有 Ollama 走本地模型；切换 provider 不用改 Agent 代码。V2 起基础安装精简，部分 provider 以 extras 安装（如 `pydantic-ai[bedrock,groq]`） |
| **类型安全的工具** | 工具就是带类型标注的 Python 函数，框架从标注推导参数 schema，让工具层与输出层一样可被静态检查 |

FastAPI 的经验几乎可以一比一迁移过来——同样的校验直觉、同样的依赖注入写法。

## V2 的关键词：Capabilities 与 Harness

V2.0 的头号特性是**能力系统（capabilities）**：把横切关注点打包成可组合的能力，通过一个 `capabilities=[...]` 参数挂到 Agent 上，官方提供 `WebSearch`、`MCP`、`Thinking`、`Guardrails`、`SpendLimits` 等；需要拦截 Agent 循环内生命周期钩子的（成本追踪、审批流、护栏），则继承 `AbstractCapability` 自定义。

配套还有一个 **Harness 包**，直接把编码型和研究型 Agent 的执行环境（沙箱、工具集、预算）打包好。

迁移建议是先升到最新的 V1、清完所有 deprecation 警告，再上 V2；V2 的破坏性变更包括：安装变为精简版 + provider extras、`builtin_tools` 改名 `native_tools`、`OpenAIModel` 改名 `OpenAIChatModel`， graceful 工具执行成为默认。

## 工程友好性：它解决的是"上生产"那几件事

- **用量与成本硬约束**：`UsageLimits` 可以设置每次 run 的请求数、token 数与**成本上限**，避免失控循环把额度烧穿（这类护栏应该在选型阶段就问清楚，而不是等账单刺痛时才补）。
- **输出校验 + 自动重试**：不符 schema 的错误会被连同错误信息一起回灌模型重试，业务代码不必写脏数据处理。
- **原生 OpenTelemetry**：追踪带 token 与成本指标，可直灌任何 OTLP 后端（Langfuse、Arize Phoenix、W&B Weave、MLflow）。Logfire 是同团队做的"阻力最小"路径（2025 年 3 月起提供 EU 区域与自托管），**但它是默认项不是必需品**。
- **Pydantic Evals**：把回归评测挂进 CI，改提示词/改模型能自动卡住质量回退——对应 [Self-Evolving](/docs/CS/AI/LLM/Self-Evolving.md) 里"评测驱动自进化"的那条链路。
- **持久执行**：与 Temporal、DBOS、Prefect 有一等集成，跑几天的任务不必自己造轮子。
- **互操作**：MCP（通过 extras）与 [A2A](/docs/CS/AI/LLM/A2A.md) 均原生支持；另有一个 Python 沙箱（Monty / CodeMode 能力）用于代码执行。

## 需要注意的短板

- **Python only**，没有 JS/TS 版本；
- 主打**单 Agent 的类型可靠**，多 Agent 靠"委托"组合（一个 Agent 的工具里调用另一个 Agent，并把 `ctx.usage` 传下去，让整棵树共享一个预算和一条 trace），而不是内置图；
- 自带的 `pydantic-graph` 存在但**官方自己都劝退**——文档形容它是"给钉子用的钉枪"，生产代码用得不多，真需要图建议直接考虑 LangGraph；
- 泛型写出来有些啰嗦，生态与招人池子比 LangGraph 薄。

## 怎么选

| 需求 | 更合适 |
|------|--------|
| 需要 Postgres 支持的可恢复状态、时间旅行调试、图中途人工中断 | [LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md) |
| 需要真正的持久执行（扛过部署、等待数天、精确一次副作用） | Temporal（用 Pydantic AI 的官方集成）优于任何框架自带的持久化 |
| 团队已全面类型化、跑严格 mypy/pyright | **Pydantic AI**（类型驱动能在编译期就抓到连线错误） |
| 主体是几个类型化 Agent，只是偶尔需要显式控制流 | **Pydantic AI**（官方也建议留在 Agent 层，别急着上 graph） |
| 多年不动代码、最怕 API 漂移 | **Pydantic AI**（V1→V2 的双线维护记录是这类框架里最好的升级故事） |
| 招聘与上手速度优先 | LangGraph（教程与人力池最大） |

一句话决策：**如果你的应用本质是一个"要嵌进真实系统的、输入输出必须有契约的 Agent"，Pydantic AI 是最省心的选择；如果本质是"一张复杂的有状态流程图"，那就去找 LangGraph。**

## Links

- [LangChain](/docs/CS/AI/LLM/LangTool/LangChain.md)
- [Langflow](/docs/CS/AI/LLM/LangTool/Langflow.md)
- [Agent](/docs/CS/AI/LLM/Agent.md)
- [Harness](/docs/CS/AI/LLM/Harness.md)
- [MCP](/docs/CS/AI/LLM/MCP.md)
- [LLM 应用开发平台](/docs/CS/AI/LLM/Platform.md)

## References

1. [Pydantic AI 官网与文档](https://ai.pydantic.dev/)
2. [Pydantic AI 开源仓库](https://github.com/pydantic/pydantic-ai)
3. [Pydantic Logfire](https://logfire.pydantic.dev/)
4. [Pydantic AI: The Type-first Approach to Python Agents（含与 LangGraph / CrewAI 的对比表）](https://blckalpaca.at/en/knowledge-base/ai-agents/ai-agent-frameworks-comparison/pydantic-ai-framework)
5. [Pydantic AI (pydantic-graph) vs LangGraph](https://www.agentnative.dev/compare/pydantic-ai-graph-vs-langgraph)
