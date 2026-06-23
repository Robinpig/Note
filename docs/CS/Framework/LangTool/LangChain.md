## Introduction

LangChain 是最快速入门构建基于 LLM 的智能代理和应用的方法。不到 10 行代码，你就可以连接 OpenAI、Anthropic、Google 以及更多提供商

LangChain [agents](https://langchain-doc.cn/v1/python/langchain/agents) 构建在 LangGraph 之上，提供持久化执行、流式处理、人类参与、数据持久化等功能



## Installation

```shell
uv add langchain
```

test

```python
# pip install -qU "langchain[anthropic]" 调用模型

from langchain.agents import create_agent

def get_weather(city: str) -> str:
    """获取指定城市的天气"""
    return f"{city} 天气总是晴朗！"

agent = create_agent(
    model="anthropic:claude-sonnet-4-5",
    tools=[get_weather],
    system_prompt="你是一个乐于助人的助手",
)

# 执行代理
agent.invoke(
    {"messages": [{"role": "user", "content": "旧金山天气如何？"}]}
)
```







## Links







## References

1. [LangChain中文文档](https://langchain-doc.cn/)

