## Introduction

回到 [Pydantic AI](/docs/CS/AI/LLM/LangTool/PydanticAI.md)。这一篇讲"从 demo 到生产"的工程件——这是 Pydantic AI 刻意强化的部分，也是它相对多数框架更"生产 shaped"的地方。能力系统见 [能力系统与 Harness](/docs/CS/AI/LLM/LangTool/PydanticAI/Capabilities.md)。

评测驱动的自进化链路，也可对照 [Self-Evolving](/docs/CS/AI/LLM/Agent/Practice/Self-Evolving.md)。

## 用量与成本硬约束

失控的 Agent 循环能把额度一夜烧穿。Pydantic AI 从源头提供硬约束：

- **`UsageLimits`**：设置每次 run 的**请求数、token 数、成本上限**三类上限，超限即停；
- **`SpendLimits` capability**：在 V2 的 capability 体系里做成本护栏，与 `UsageLimits` 互补。

这类护栏**应该在选型阶段就问清楚**，而不是等账单刺痛时才补——它直接决定"能不能放心把 Agent 跑在无人值守的批处理里"。

## 可观测：OpenTelemetry + Logfire

原生 **OpenTelemetry** 追踪，span 带 token 与成本指标，可直灌任何 OTLP 后端：Langfuse、Arize Phoenix、W&B Weave、MLflow 都行。

**Logfire** 是同团队做的"阻力最小"路径（云或自托管，EU 区域自 2025-03 起可用），**但它是默认项不是必需品**。注意一个可验证的细节：仪表化版本默认 v5，且**跨 provider 统一**，但 OTLP 语义约定不同后端支持不同版本——Pydantic AI 允许配置 instrumentation 版本，而该默认值可能在 minor 版本变动，消费 span 时要写防御性代码。

## Pydantic Evals（评测驱动自进化）

`pydantic-evals` 把回归评测挂进 CI：改提示词 / 改模型能自动卡住质量回退。核心三件套：

| 构件 | 作用 |
|------|------|
| `Cases` | 单条「输入 → 期望」样本 |
| `Datasets` | Cases 的集合，可批量跑 |
| `LLMJudge` | 用模型当裁判打分，适合开放题 |

把评测集随代码一起进版本库，每次 PR 自动跑，对应 [Self-Evolving](/docs/CS/AI/LLM/Agent/Practice/Self-Evolving.md) 里"评测驱动自进化"的那条链路——没有评测集，所谓的"自进化"只是盲目调参。

## 持久执行

跑几天的长任务不必自己造轮子：Pydantic AI 对 **Temporal / DBOS / Prefect** 有一等集成，提供持久化检查点——系统恢复时从最后一个已完成步骤继续，而非从头来过。

⚠️ 一个进行中的事实：持久执行正在迁移到 capability 层（带运行时扩展点），官方跟踪在 V2 之后。选型时把它当作"已有的一等集成能力"，但关注其 API 是否随 capability 化而调整。

## 互操作：MCP 与 A2A

- **MCP**：通过 extras 安装，`MCPToolset` 把远端 server 工具集接入（见 [能力系统](/docs/CS/AI/LLM/LangTool/PydanticAI/Capabilities.md)）；Agent 既能作为 MCP Client 消费工具，也能作为 MCP Server 暴露自己。
- **A2A**：原生支持，可与同样支持 A2A 的 Agent 互操作。
- **代码沙箱**：Monty / CodeMode 能力提供受限的 Python 代码执行（见 [能力系统](/docs/CS/AI/LLM/LangTool/PydanticAI/Capabilities.md)）。

## 多 Agent：委托而非图

Pydantic AI 没有内置编排图，多 Agent 靠**委托（delegation）**组合：在一个 Agent 的工具里调用另一个 Agent，并把 `ctx.usage` 传下去，让整棵调用树共享一个预算和一条 trace。

```python
@primary.tool
async def delegate(ctx: RunContext[Deps], question: str) -> str:
    # 把用量传下去，子树共享预算与 trace
    sub = await specialist.run(question, usage=ctx.usage)
    return sub.output
```

真需要"图"语义时，官方明确劝退自带的 `pydantic-graph`（"给钉子用的钉枪"），**直接上 [LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md)**——这也是常见组合：Pydantic AI 写类型安全的节点，LangGraph 做有状态编排。

## 选型定位（回顾）

完整的"什么时候选 Pydantic AI vs LangGraph"决策表在 [Pydantic AI](/docs/CS/AI/LLM/LangTool/PydanticAI.md) 的 How to Choose。一句话：**应用本质是"要嵌进真实系统、IO 必须有契约的 Agent"→ Pydantic AI；本质是"复杂有状态流程图"→ LangGraph。**

## Links

- [Pydantic AI](/docs/CS/AI/LLM/LangTool/PydanticAI.md)
- [核心机制](/docs/CS/AI/LLM/LangTool/PydanticAI/Core.md)
- [能力系统与 Harness](/docs/CS/AI/LLM/LangTool/PydanticAI/Capabilities.md)
- [LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md)
- [Self-Evolving](/docs/CS/AI/LLM/Agent/Practice/Self-Evolving.md)
- [MCP](/docs/CS/AI/LLM/Protocol/MCP.md)

## References

1. [Pydantic AI 文档：Usage Limits](https://ai.pydantic.dev/api/agent/#pydantic_ai.Agent.run)
2. [Pydantic AI 文档：Observability / Logfire](https://ai.pydantic.dev/logfire/)
3. [Pydantic Evals 仓库](https://github.com/pydantic/pydantic-evals)
4. [Pydantic AI 文档：Durable Execution（Temporal / DBOS / Prefect）](https://ai.pydantic.dev/durable-execution/)
5. [Pydantic AI 文档：Multi-Agent（委托）](https://ai.pydantic.dev/multi-agent-applications/)
6. [Pydantic AI 文档：MCP](https://ai.pydantic.dev/mcp/)
