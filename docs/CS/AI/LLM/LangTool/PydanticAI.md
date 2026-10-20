## Introduction

Pydantic AI 是 Pydantic 团队（[FastAPI](https://fastapi.tiangolo.com/) 同门）出品的 **Python Agent 框架**，MIT 许可。它把 Pydantic 那套"用类型标注描述数据契约"的思路搬进了 LLM 应用：**工具参数、依赖注入、结构化输出全部是普通 Python 类型标注**，模型返回不合法就会拿到一条类型化错误并被自动要求重试，而不是让脏数据一路流到业务代码里。

版本线（已核实，非凭记忆）：

- **V1.0 GA**：2025-09（约 09-04），并给出明确的 API 稳定性承诺；
- **V2.0 稳定版**：2026-06-23，带着"harness-first + capabilities 原语"的重构；
- **双线维护**：V1 仍收安全补丁（v1.107.7 于 2026-09-29 修安全）；V2 线迭代极快，至 2026-10 中旬已到 v2.5x 量级。在频繁 Breaking Change 的 Agent 框架圈子里，这是份很难得的升级记录。

它与 [LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md) 解决的是不同层的问题：**Pydantic AI 强在"单个类型安全的 Agent 能否可靠地嵌进真实代码库"，LangGraph 强在"多步有状态图 + 检查点 + 人在环路"。** 两者并不互斥，常见组合是用 Pydantic AI 写类型安全的 Agent 作为节点，上面再架一层编排。

## Four Pillars

| 支柱 | 说明 |
|------|------|
| **结构化校验输出** | 目标 schema 声明为 Pydantic 模型；Agent 保证交付匹配该 schema 的对象，否则抛校验错误并按提示让模型重试 |
| **依赖注入** | 数据库连接、HTTP 客户端、配置、鉴权上下文以类型注入 Agent，业务逻辑与 Agent 定义解耦；单元测试可以直接 mock（和 FastAPI 的直觉完全一致） |
| **模型无关** | `openai:gpt-5.2`、`anthropic:claude-...`、`google:...`、Bedrock、Azure、Groq、Mistral、xAI、Ollama 等共用一个字符串 API；切换 provider 不改业务代码 |
| **类型安全的工具** | 工具就是带类型标注的 Python 函数，框架从标注推导参数 schema，让工具层与输出层一样可被静态检查 |

FastAPI 的经验几乎可以一比一迁移过来——同样的校验直觉、同样的依赖注入写法。四个支柱各自的机制、三种结构化输出模式与最小示例，见 [核心机制](/docs/CS/AI/LLM/LangTool/PydanticAI/Core.md)。

## V2: Capability 与 Harness

V2.0 的头号特性是**能力系统（capability）**：把横切关注点打包成可组合的单元，通过一个 `capabilities=[...]` 参数挂到 Agent 上，官方提供 `Thinking`、`WebSearch`、`MCP`、`Guardrails`、`SpendLimits`、`CodeMode` 等；需要拦截 Agent 循环内生命周期钩子的（成本追踪、审批流、护栏），则继承 `AbstractCapability` 自定义。

与之配套的 **Harness 包**（`pydantic-ai-harness`，独立发布、仍是 0.x）把内存、护栏、上下文管理、文件访问、代码模式等"电池"挪了出去，让 Core（`pydantic-ai-slim`）保持小而稳。V2 起基础安装精简，部分 provider 以 extras 安装（如 `pydantic-ai[bedrock,groq]`）。完整的 capability 清单、自定义写法与 V1→V2 迁移清单，见 [能力系统与 Harness](/docs/CS/AI/LLM/LangTool/PydanticAI/Capabilities.md)。

## Going to Production

这一篇停留在"Pydantic AI 是什么、该怎么选"。真要把它在生产里跑起来，还有三块值得单独读，三篇按**核心机制 → 能力系统 → 工程化**分工，互不重复：

- **[核心机制](/docs/CS/AI/LLM/LangTool/PydanticAI/Core.md)** —— 四大支柱逐一拆解，带三种结构化输出模式、依赖注入、模型字符串与 provider extras、类型安全工具的最小可运行示例。**写第一个 Agent 从这里开始。**
- **[能力系统与 Harness](/docs/CS/AI/LLM/LangTool/PydanticAI/Capabilities.md)** —— Core / Capability / Harness 三层边界、内置与一等 capability、自定义 `AbstractCapability` 与 `defer_loading` 按需加载、V1→V2 破坏性变更与升级路径。**要做扩展或升级 V2 从这里开始。**
- **[工程化与生产](/docs/CS/AI/LLM/LangTool/PydanticAI/Production.md)** —— 用量/成本硬约束、原生 OpenTelemetry 与 Logfire、Pydantic Evals 评测回归、Temporal/DBOS/Prefect 持久执行、MCP 与 A2A 互操作、多 Agent 委托模式。**上线前从这里过一遍。**

## Shortcomings to Note

- **Python only**，没有 JS/TS 版本；跨语言团队要考虑这点；
- 主打**单 Agent 的类型可靠**，多 Agent 靠"委托"组合（一个 Agent 的工具里调用另一个 Agent，并把 `ctx.usage` 传下去，让整棵树共享一个预算和一条 trace），而不是内置图；
- 自带的 `pydantic-graph` 官方长期劝退——文档形容它是"给钉子用的钉枪"，生产代码用得不多，真需要图建议直接考虑 [LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md)；
- 泛型写出来有些啰嗦，生态与招人池子比 [LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md) 薄；
- Harness 仍是 0.x，其 API 仍可能变动，押注前需评估。

## How to Choose

| 需求 | 更合适 |
|------|--------|
| 需要 Postgres 支持的可恢复状态、时间旅行调试、图中途人工中断 | [LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md) |
| 需要真正的持久执行（扛过部署、等待数天、精确一次副作用） | Temporal / DBOS（Pydantic AI 官方集成）优于任何框架自带的持久化 |
| 团队已全面类型化、跑严格 mypy/pyright | **Pydantic AI**（类型驱动能在编译期就抓到连线错误） |
| 主体是几个类型化 Agent，只是偶尔需要显式控制流 | **Pydantic AI**（官方也建议留在 Agent 层，别急着上 graph） |
| 多年不动代码、最怕 API 漂移 | **Pydantic AI**（V1→V2 的双线维护记录是这类框架里最好的升级故事） |
| 招聘与上手速度优先 | [LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md)（教程与人力池最大） |

一句话决策：**如果你的应用本质是一个"要嵌进真实系统的、输入输出必须有契约的 Agent"，Pydantic AI 是最省心的选择；如果本质是"一张复杂的有状态流程图"，那就去找 [LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md)。**

## Links

- [LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md)
- [Langflow](/docs/CS/AI/LLM/LangTool/Langflow.md)
- [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md)
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)
- [MCP](/docs/CS/AI/LLM/Protocol/MCP.md)
- [LLM 应用开发框架](/docs/CS/AI/LangTools.md)

## References

1. [Pydantic AI 官网与文档](https://ai.pydantic.dev/)
2. [Pydantic AI 开源仓库](https://github.com/pydantic/pydantic-ai)
3. [Pydantic AI V2 发布说明（capabilities 与 Harness）](https://pydantic.dev/articles/pydantic-ai-v2)
4. [Pydantic AI 版本政策](https://pydantic.dev/docs/ai/project/version-policy)
5. [Pydantic Logfire（观测平台）](https://logfire.pydantic.dev/)
6. [Pydantic AI V2 in Late 2026: Capabilities, Graphs, Evals and MCP](https://www.developersdigest.tech/blog/pydantic-ai-whats-new-2026)
