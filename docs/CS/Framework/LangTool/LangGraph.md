## Introduction

LangGraph是一个低级编排框架和运行时，用于构建、管理和部署长时间运行的有状态代理

LangGraph为任何长时间运行的有状态工作流或代理提供低级支持基础设施。LangGraph不抽象提示或架构，并提供以下核心优势：

- [持久执行](https://langchain-doc.cn/v1/python/langgraph/durable-execution)：构建能够在故障中持久存在并可以长时间运行的代理，从停止的地方继续执行。
- [人机协作](https://langchain-doc.cn/v1/python/langgraph/interrupts)：通过在任何点检查和修改代理状态来纳入人工监督。
- [全面的记忆](https://langchain-doc.cn/v1/python/concepts/memory)：创建具有短期工作记忆（用于持续推理）和跨会话长期记忆的有状态代理。
- [使用LangSmith进行调试](https://langchain-doc.cn/langsmith/home)：通过可视化工具深入了解复杂的代理行为，这些工具可以跟踪执行路径、捕获状态转换并提供详细的运行时指标。
- [生产就绪的部署](https://langchain-doc.cn/langsmith/deployments)：使用专为处理有状态、长时间运行的工作流的独特挑战而设计的可扩展基础设施，自信地部署复杂的代理系统

## Installation

```shell
uv add langgraph
```



```python
from langgraph.graph import StateGraph, MessagesState, START, END

def mock_llm(state: MessagesState):
    return {"messages": [{"role": "ai", "content": "hello world"}]}

graph = StateGraph(MessagesState)
graph.add_node(mock_llm)
graph.add_edge(START, "mock_llm")
graph.add_edge("mock_llm", END)
graph = graph.compile()

graph.invoke({"messages": [{"role": "user", "content": "hi!"}]})
```







## Links





## References

1. [LangGraph中文文档](https://langchain-doc.cn/v1/python/langgraph/overview.html)

