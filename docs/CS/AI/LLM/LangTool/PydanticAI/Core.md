## Introduction

这一篇把 Pydantic AI 的四大支柱逐一拆开，带最小可运行示例。产品视角与选型回到 [Pydantic AI](/docs/CS/AI/LLM/LangTool/PydanticAI.md)；V2 的能力系统见 [能力系统与 Harness](/docs/CS/AI/LLM/LangTool/PydanticAI/Capabilities.md)。

设计直觉一句话：**Agent 应当像一个带类型的函数——类型化的依赖进去，校验过的输出出来，模型能碰到的东西（工具参数、结构化结果）在业务代码看到之前先被 Pydantic 查一遍。** 用过 FastAPI 的人会立刻认出这是同一套哲学，只是从"HTTP 请求"上移到了"Agent"这一层。

## Structured Validated Output

把目标结构声明成一个 Pydantic 模型，`output_type` 指向它。Agent 保证交付匹配该 schema 的对象；若模型吐出的 JSON 不合法，框架会把校验错误连同原始报错回灌模型重试（这正是 `ModelRetry` 的底层机制），业务代码永远拿不到脏数据。

Pydantic AI 提供三种结构化输出模式，按"模型原生支持度"与"兼容性"取舍：

| 模式 | 机制 | 适用 |
|------|------|------|
| `tool`（默认） | 让模型调用一个返回结构化结果的工具 | 兼容性最好，所有模型都走 function calling |
| `native` | 直接用模型的结构化输出能力（如 JSON mode / 原生 schema） | 模型原生支持时更省 token、更稳 |
| `prompted` | 在提示词里要求按格式输出再解析 | 兜底，模型不支持上述两者时 |

```python
from pydantic import BaseModel
from pydantic_ai import Agent

class CityWeather(BaseModel):
    city: str
    temp_c: float
    summary: str

agent = Agent(
    'openai:gpt-5.2',
    output_type=CityWeather,
    instructions='把天气结果整理成结构化对象。',
)

result = await agent.run('北京现在天气怎么样？')
reveal_type(result.output)  # CityWeather，已通过校验
```

## Dependency Injection

`deps_type` 把依赖（DB 连接、HTTP 客户端、配置、鉴权上下文）以类型注入 Agent。业务逻辑与 Agent 定义解耦，**测试时直接换一个 mock 实现即可**，无需改动 Agent 主体——和 FastAPI 的 `Depends` 直觉一致。依赖通常声明为 dataclass。

```python
from dataclasses import dataclass

@dataclass
class Deps:
    db: Database
    http: HttpClient
    user_id: str

agent = Agent(
    'anthropic:claude-...',
    deps_type=Deps,
    output_type=Receipt,
)

@agent.tool
async def lookup_order(ctx: RunContext[Deps], order_id: str) -> str:
    # ctx.deps 拿到注入的依赖，类型已知、可被静态检查
    return await ctx.deps.db.get_order(ctx.deps.user_id, order_id)
```

## Model-Agnostic

全部模型共用一个**模型字符串** API：`openai:gpt-5.2`、`anthropic:claude-fable-5`、`google:gemini-...`、`grok:...`、`ollama:llama3.1` 等，切换 provider 时业务代码一行不动。

⚠️ **V2 的两个易踩点（已核实）**：

1. **必须带 provider 前缀**。V2 起裸模型名如 `Agent('gpt-5')` 会直接抛 `UserError`；要么写 `openai:gpt-5`，要么显式构造 `OpenAIChatModel(...)`。
2. **`openai:` 现在走 Responses API**。想留在旧的 Chat Completions，用 `openai-chat:` 前缀。

安装侧：V2 默认安装（`pydantic-ai` / `pydantic-ai-slim`）只含 OpenAI、Anthropic、Google 三家，其余 provider 走 extras 显式安装：

```bash
uv add "pydantic-ai[bedrock,groq,mistral,xai,huggingface,temporal]"
```

已覆盖的 provider 包括 OpenAI、Anthropic、Google（Gemini / Vertex AI）、Amazon Bedrock、Azure AI Foundry、Groq、Mistral、Cohere、xAI（Grok）、Perplexity、Ollama（本地）、DeepSeek，以及自定义模型。

## Type-Safe Tools

工具就是带类型标注的 Python 函数，框架从函数签名 + docstring 推导参数 schema，工具层和输出层一样可被 mypy/pyright 静态检查。

- 用 `@agent.tool` 定义需要 `RunContext`（取依赖、用量、模型）的工具；`@agent.tool_plain` 定义无上下文的工具。
- 工具参数与返回值都是普通类型标注；模型调用工具时参数已被校验。
- 当工具自己知道"这次结果不对"时，抛 `ModelRetry` 而非普通异常——框架会把错误回灌模型，让它换一种调法或换一个答案，而不是在业务代码里写脏数据处理。

```python
from pydantic_ai import Agent, RunContext, ModelRetry

@agent.tool
async def search_docs(ctx: RunContext[Deps], query: str) -> str:
    """在知识库里检索与 query 相关的段落。"""
    hits = await ctx.deps.http.get(f'/search?q={query}')
    if not hits:
        raise ModelRetry('没检索到相关文档，换个说法再试。')
    return hits
```

工具层、输出层、依赖层都被同一套类型系统约束，这正是 Pydantic AI "类型驱动能在编译期就抓到连线错误"的根。

## Links

- [Pydantic AI](/docs/CS/AI/LLM/LangTool/PydanticAI.md)
- [能力系统与 Harness](/docs/CS/AI/LLM/LangTool/PydanticAI/Capabilities.md)
- [工程化与生产](/docs/CS/AI/LLM/LangTool/PydanticAI/Production.md)
- [LangGraph](/docs/CS/AI/LLM/LangTool/LangGraph.md)
- [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md)

## References

1. [Pydantic AI 文档：Agents](https://ai.pydantic.dev/agents/)
2. [Pydantic AI 文档：Structured Output（输出模式）](https://ai.pydantic.dev/output/)
3. [Pydantic AI 文档：Tools](https://ai.pydantic.dev/tools/)
4. [Pydantic AI 文档：Dependency Injection](https://ai.pydantic.dev/agents/#dependency-injection)
5. [Pydantic AI 文档：Models（模型字符串与 providers）](https://ai.pydantic.dev/models/)
