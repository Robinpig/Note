## Introduction

LangChain 是把 LLM 组装成应用的**高层框架**：用一套跨厂商的抽象统一模型调用、提示、工具、检索与结构化输出，让"换模型不改业务代码"成为默认行为。

2025 年 10 月发布的 **LangChain 1.0** 是一次收缩式重构。三年 v0.x 的社区反馈集中在两点——抽象太重、包面太散——1.0 的回应是把整个包收敛到一件事上：**Agent = Model + Harness**。只留 `create_agent` 一个高层入口，定制走 middleware，并承诺 2.0 之前不再破坏性变更。

先分清它和 [LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md) 的关系：**LangChain 是组件层与高层 Agent 入口，LangGraph 是它下面的状态机运行时**。`create_agent` 编译出来就是一张 LangGraph 图，持久化、流式、人在环路都由那层提供。

## 官方四层定位

LangChain Inc. 把自家产品切成四层，这套划分比"框架对比框架"更能说明问题：

| 层 | 产品 | 职责 |
| --- | --- | --- |
| Harness | [Deep Agents](/docs/CS/AI/LLM/LangTool/DeepAgents.md) | 自带规划、子 Agent、虚拟文件系统、上下文压缩的"整车" |
| Framework | **LangChain** | 模型/工具抽象与 Agent 循环，高层入口 `create_agent` |
| Runtime | [LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md) | 持久执行、流式、人在环路、持久化 |
| Platform | [LangSmith](/docs/CS/AI/LLM/LangTool/LangSmith.md) | 追踪、评测、提示管理、部署（含 LangGraph Studio 图调试器） |

自下而上能力递减、开箱即用程度递增。选型原则与 [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) 里的判断一致：**越靠上越省事，越靠下越可控**；只有当上层补的东西你用不上时，往下退一层才划算。

## 包结构

1.0 把包面切干净了，import 之前先认清楚该装哪个：

| 包 | 内容 |
| --- | --- |
| `langchain` | 主包，只留构建 Agent 最常用的部分：`create_agent`、middleware，以及从 core 再导出的核心抽象 |
| `langchain-core` | 最小抽象底座：`Runnable`、Message、Tool、Retriever 等接口，以及 1000+ 集成的抽象层 |
| `langchain-classic` | 历史包袱的收容所：旧 Chain 实现、indexing API、`langchain-community` 再导出、已废弃功能 |
| `langchain-<provider>` | 分厂商集成（`langchain-openai`、`langchain-anthropic` 等），按需安装 |

```shell
uv add langchain langchain-openai      # 等价于 pip install -qU "langchain[openai]"
```

> [!WARNING]
> **版本必须成套升级**。`langchain`、`langchain-core`、各集成包、`langgraph` 与其 checkpoint 包**不锁步发版**，只升其中一个会出现抽象与实现对不上的错误，历史上这种错配是明确的故障来源。要么整体升级，要么全部 pin 到实测过的组合。

## create_agent

1.0 的主线只有这一条：给模型、工具和提示，它用 LangGraph 运行时跑标准的 tool-calling 循环——模型返回工具调用 → 执行工具 → 结果回填 → 再问模型，直到给出最终答案。

```python
from langchain.agents import create_agent

def get_weather(city: str) -> str:
    """获取指定城市的天气"""
    return f"{city} 天气总是晴朗！"

agent = create_agent(
    model="anthropic:claude-sonnet-4-5",
    tools=[get_weather],
    system_prompt="你是一个乐于助人的助手",
)

agent.invoke(
    {"messages": [{"role": "user", "content": "旧金山天气如何？"}]}
)
```

`model` 用 `"provider:model"` 字符串指定，换厂商只是改一个字符串，而不是重写调用代码——这是"不锁模型"的具体形态。

## middleware

`create_agent` 默认极简，定制全部走 middleware 钩子，而不是像旧版那样去改写 AgentExecutor。官方内置三类：

| 内置 middleware | 作用 |
| --- | --- |
| Human-in-the-loop | 工具真正执行前暂停，等人工批准、修改或拒绝 |
| Summarization | 消息历史逼近上下文上限时压缩旧消息，保留近期消息 |
| PII redaction | 送模型前按模式识别并脱敏邮箱、电话等敏感信息 |

自定义 middleware 可以挂在循环的多个钩子点上，实现细粒度控制。

## 标准内容块（standard content blocks）

1.0 在 `langchain-core` 里加了 `content_blocks`：把各厂商返回的差异化内容（推理轨迹、引用、内置工具调用等）统一成一套带类型的标准结构。

```python
result["messages"][-1].content_blocks   # 跨厂商统一的输出结构
```

好处是换模型不用改解析逻辑，且对旧代码向后兼容（惰性加载）。

## Message 与 Tool

- **Message**：对话的基本单位，`SystemMessage` / `HumanMessage` / `AIMessage` / `ToolMessage` 各司其职。`MessagesState` 内置 reducer，新消息自动追加——LangGraph 的 ReAct 示例全靠这一条。
- **Tool**：用 `@tool` 装饰普通函数，函数的类型签名与 docstring 即工具 schema，不必手写 JSON Schema。

## 与 LangGraph 的分工

| 维度 | LangChain | LangGraph |
| --- | --- | --- |
| 层次 | 组件层 + 高层 Agent 入口 | 低层编排运行时 |
| 心智模型 | 一条链 / 一个 Agent 循环 | 节点 + 边 + 共享 State |
| 分支与循环 | 由 Agent 循环隐式提供 | `add_conditional_edges` 显式表达 |
| 持久化 | 通过底层运行时获得 | checkpointer 原生支持 |
| 适用 | 单轮助手、RAG、结构化抽取、标准 tool-calling Agent | 多步长任务、多 Agent、需人工审批或断点恢复 |

一条经验线：**线性流程用 LangChain 就够，一旦需要循环重试、跨轮持久状态或人工审批闸门，就加 LangGraph**。官方也是这个口径——LangGraph 文档明确写着"刚上手或想要更高抽象，就用 LangChain 的 agents"。

反过来也要知道**什么时候两个都别用**：如果只是把一两次模型调用包成一个函数，直接用厂商 SDK（OpenAI / Anthropic）反而更快、抽象泄漏更少。

## Links

- [LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md)
- [LangChain4j](/docs/CS/AI/LLM/LangTool/LangChain4j.md)
- [Langflow](/docs/CS/AI/LLM/LangTool/Langflow.md)
- [LangTools](/docs/CS/AI/LangTools.md)
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)
- [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md)

## References

1. [LangChain overview](https://docs.langchain.com/oss/python/langchain/overview)
2. [LangChain and LangGraph Reach v1.0 Milestones](https://www.langchain.com/blog/langchain-langgraph-1dot0)
3. [langchain-classic (PyPI)](https://pypi.org/project/langchain-classic/)
4. [LangChain 中文文档](https://langchain-doc.cn/)
