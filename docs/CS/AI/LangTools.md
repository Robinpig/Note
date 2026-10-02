## Introduction

本页是 **LLM 应用开发框架**的横向地图：当你不满足于直接调 API，而要把模型、工具、检索、记忆与多步流程组装成可维护的工程时，就进入了这一层。

先厘清它和 [LLM 应用开发平台](/docs/CS/AI/LLM/Platform.md) 的关系：两者是并行路线，不是一回事。平台交付的是"产品表面"（画布 + 内置 RAG + 现成运维），框架交付的是"库与运行时"。这笔账的本质是**用开发速度换可控性**——平台上手快，但能改的边界由厂商画布划定；框架起步慢，但每一层都可替换。

这一层当下的格局几乎由 LangChain Inc. 定义：它把自家产品切成 Harness / Framework / Runtime / Platform 四层，其他玩家基本都在其中某几层上对标。

## LangChain 家族的四层

| 层 | 产品 | 职责 |
| --- | --- | --- |
| Harness | [Deep Agents](/docs/CS/AI/LLM/LangTool/DeepAgents.md) | 自带规划、子 Agent、虚拟文件系统、上下文压缩的"整车" |
| Framework | [LangChain](/docs/CS/AI/LLM/LangTool/LangChain.md) | 模型/工具抽象与 Agent 循环（`create_agent`） |
| Runtime | [LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md) | 持久执行、流式、人在环路、持久化 |
| Platform | [LangSmith](/docs/CS/AI/LLM/LangTool/LangSmith.md) | 追踪、评测、提示管理与部署（原 LangGraph Platform） |

这四层自上而下能力递减、开箱即用程度递增；越靠上越省事，越靠下越可控。

家族内还有两个横向分支值得单独记：

- [LangChain4j](/docs/CS/AI/LLM/LangTool/LangChain4j.md)——同一套理念的 Java 实现（Spring Boot / Quarkus 集成），适合"给现有后端加一个会用工具的助手"，而不必另起 Python 服务。
- [Langflow](/docs/CS/AI/LLM/LangTool/Langflow.md)——把 LangChain 组件做成可视化画布，可导出 Python 或发布成 API，走"先可视化验证、再落回代码"的路径。

## 同层的其他玩家

| 框架 | 定位 | 什么时候选它 |
| --- | --- | --- |
| [Pydantic AI](/docs/CS/AI/LLM/PydanticAI.md) | 类型优先的 Python Agent 框架 | 团队本就吃 Pydantic 的类型约束，要的是能嵌进真实代码库的 Agent |
| CrewAI | 角色扮演式多 Agent | 快速搭"一组角色分工协作"的原型 |
| OpenAI Agents SDK | 厂商原生 Agent SDK | 只用 OpenAI，或想跟着官方路线走 |
| Claude Agent SDK | 厂商原生 Agent SDK | 同上，且更偏"在开发机上干活的编码 Agent" |

## 怎么选

- **要标准 tool-calling Agent，且预期会换模型** → [LangChain](/docs/CS/AI/LLM/LangTool/LangChain.md)
- **要长任务开箱即用：规划、文件系统、子 Agent 都现成** → [Deep Agents](/docs/CS/AI/LLM/LangTool/DeepAgents.md)
- **要多步长任务、人工审批、断点恢复** → [LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md)
- **团队主力是 Java 后端** → [LangChain4j](/docs/CS/AI/LLM/LangTool/LangChain4j.md)
- **想先把流程搭出来看看效果** → [Langflow](/docs/CS/AI/LLM/LangTool/Langflow.md)，或直接用[平台](/docs/CS/AI/LLM/Platform.md)
- **要追踪、评测与部署上线** → [LangSmith](/docs/CS/AI/LLM/LangTool/LangSmith.md)
- **只有一两次模型调用** → 直接用厂商 SDK 最快，框架反而是负担

## 上手准备

这一层的例子基本都能用同一个 Python 环境跑起来：

```shell
python3 -m venv lang
source lang/bin/activate
pip3 install langgraph langchain langchain-openai
```

模型凭据按厂商配环境变量即可（以 OpenAI 兼容接口为例）：

```python
import os
from langchain_openai import ChatOpenAI

os.environ["OPENAI_API_KEY"] = "your-api-key-here"

llm = ChatOpenAI(model="gpt-4", temperature=0)
```

## Links

- [LangChain](/docs/CS/AI/LLM/LangTool/LangChain.md)
- [LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md)
- [LangChain4j](/docs/CS/AI/LLM/LangTool/LangChain4j.md)
- [Langflow](/docs/CS/AI/LLM/LangTool/Langflow.md)
- [Pydantic AI](/docs/CS/AI/LLM/PydanticAI.md)
- [Platform](/docs/CS/AI/LLM/Platform.md)

## References

1. [Frameworks, runtimes, and harnesses](https://docs.langchain.com/oss/python/concepts/products)
2. [LangChain overview](https://docs.langchain.com/oss/python/langchain/overview)
3. [LangGraph overview](https://docs.langchain.com/oss/python/langgraph/overview)
