## Introduction





LangGraph 是一个低级别的编排框架，用于构建、管理和部署长时间运行、有状态的智能体，受到 Klarna、Replit、Elastic 等塑造智能体未来的公司的信任



```shell
 python3 -m venv lang
 source lang/bin/activate
 pip3 install langgraph langchain langchain-openai
 deactivate
```



API凭据配置

```python
import os
from langchain_openai import ChatOpenAI

# Configure your API Key
os.environ["OPENAI_API_KEY"] = "your-api-key-here"

# Initialize the model
llm = ChatOpenAI(model="gpt-4", temperature=0)
```



## Links

