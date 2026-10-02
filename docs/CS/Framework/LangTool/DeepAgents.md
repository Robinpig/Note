## Introduction

Deep Agents 是 LangChain 官方给出的 **agent harness**——一个开箱即用、但每一块都能替换的"成体 Agent"。它不是又一个 Agent 框架，而是把"让 Agent 能长时间干活"所需的零配件预先装好。

它要解决的是 tool loop 的天花板问题：**"让 LLM 在循环里调工具"是最简单的 Agent 形态，但这样长出来的 Agent 是"浅"的**——不擅长规划，也难以跨越长任务持续行动。Deep Research、Manus、Claude Code 这类产品绕开限制的办法，是同时补上四样东西：**一个规划工具、子 Agent、文件系统访问、以及一段足够详细的提示**。Deep Agents 把这四件事做成通用实现。

设计取向写在官方致谢里，值得原文一读：**"本项目主要受 Claude Code 启发，最初很大程度上是想搞清楚是什么让 Claude Code 变得通用，并让它更通用。"** 这解释了它为什么长得像编码 Agent——但它并不限于编码场景。

## 在家族里的位置

官方口径把三者描述成同一个栈的三层，区别只在"你已经拿到了多少"：

| 层 | 产品 | 你需要自己写多少 |
| --- | --- | --- |
| Harness | **Deep Agents** | 最少：`create_deep_agent()` 就自带规划、文件系统、子 Agent、上下文管理 |
| Framework | [LangChain](/docs/CS/Framework/LangTool/LangChain.md) 的 `create_agent` | 中等：给模型、工具、提示，middleware 自己挑 |
| Runtime | [LangGraph](/docs/CS/Framework/LangTool/LangGraph.md) | 最多：节点、边、状态全自己画 |

对应到 [Harness](/docs/CS/AI/LLM/Harness.md) 的判断方法：**上层替你把模型缺口补上了，只有当它补的东西你用不上（或反过来在拖后腿）时，才往下退一层**。官方给的选择线很干脆——要全副 harness 用 Deep Agents，要更轻的 harness 用 `create_agent`，当 agent loop 本身形状就不对时下到 LangGraph。

## 内置了什么

自动挂载的 middleware 带来四组能力：

| 能力 | 内置工具 | 作用 |
| --- | --- | --- |
| 规划 | `write_todos` | 把复杂任务拆成待办并跟踪进度 |
| 文件系统 | `ls` / `read_file` / `write_file` / `edit_file` / `glob` / `grep` | 充当工作记忆：中间结果落盘，而不是全塞进上下文 |
| 子 Agent | `task` | 把子任务委派给**上下文窗口隔离**的 Agent，返回结论而非全过程 |
| 上下文管理 | — | 摘要长线程、把工具输出卸载到磁盘，避免 token 爆掉 |

这些工具不是散装函数，而是由 `TodoListMiddleware`、`FilesystemMiddleware`、`SubAgentMiddleware`、`SummarizationMiddleware` 等中间件注入的——所以每一块都能单点替换，包括文件系统后端（本地 / 沙箱 / 远程）。

## 最小用法

```python
from deepagents import create_deep_agent

agent = create_deep_agent(
    model="anthropic:claude-sonnet-4-5",
    tools=[my_custom_tool],
    system_prompt="You are a research assistant.",
)

result = agent.invoke(
    {"messages": [{"role": "user", "content": "Research LangGraph and write a summary"}]}
)
```

`create_deep_agent` 返回的**就是一个 LangGraph graph**，所以流式、人在环路、checkpointer、Studio 调试全都能直接用。反过来也成立：任何 LangGraph `CompiledStateGraph` 都能作为子 Agent 塞进 Deep Agent，自定义编排与 harness 默认值并存。

## 可定制点

| 参数 | 作用 |
| --- | --- |
| `tools` | 主 Agent 与所有子 Agent 共享的工具（也支持接 MCP server） |
| `system_prompt` | 自定义提示；中间件还会追加待办、文件系统、子 Agent 的使用说明，所以这不是 Agent 看到的全部提示 |
| `subagents` | 子 Agent 列表，两种形态：声明式 `SubAgent`（name / description / prompt / tools / model），或 `CustomSubAgent` 直接传一个现成的 LangGraph graph |
| `model` | 任何支持 tool calling 的 LangChain 模型对象；也可在子 Agent 粒度单独指定模型 |
| `backend` | 文件系统后端，可插拔（本地目录、沙箱、远程） |
| `interrupt_on` | 人在环路：指定哪些工具执行前必须人工批准 |
| `checkpointer` / `store` | 前者管线程内短期状态，后者管跨会话长期记忆 |

> [!WARNING]
> 官方安全政策写的是 **"trust the LLM"**：Agent 能做它的工具允许的任何事。**边界必须落在工具与沙箱层，不要指望模型自律**。也就是说，文件系统后端与 shell 执行用什么沙箱，属于安全设计的一部分，而不是部署细节——把 shell 工具接到无隔离环境上，等于把主机交出去了。

## 什么时候用它

- **长任务、需要规划与自我管理上下文**（深度调研、代码迁移、批量分析）→ Deep Agents
- **单轮或轻量多轮、上下文装得下** → 用 [LangChain](/docs/CS/Framework/LangTool/LangChain.md) 的 `create_agent` 更轻
- **需要精确控制每一步的确定性流程** → 下到 [LangGraph](/docs/CS/Framework/LangTool/LangGraph.md) 自己画图

反过来说，如果你只需要"问一次答一次"，harness 带来的文件系统与待办机制纯属负担——那点复杂度换不来任何可靠性。

## Links

- [LangChain](/docs/CS/Framework/LangTool/LangChain.md)
- [LangGraph](/docs/CS/Framework/LangTool/LangGraph.md)
- [LangSmith](/docs/CS/Framework/LangTool/LangSmith.md)
- [LangTools](/docs/CS/AI/LangTools.md)
- [Harness](/docs/CS/AI/LLM/Harness.md)
- [Agent](/docs/CS/AI/LLM/Agent.md)

## References

1. [Deep Agents 文档](https://docs.langchain.com/oss/python/deepagents/overview)
2. [deepagents (PyPI)](https://pypi.org/project/deepagents/)
3. [Frameworks, runtimes, and harnesses](https://docs.langchain.com/oss/python/concepts/products)
