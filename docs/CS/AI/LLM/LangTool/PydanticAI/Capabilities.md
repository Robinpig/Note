## Introduction

V2.0（2026-06-23）的核心重构是：**capability 成为一等扩展原语**。产品视角与选型回到 [Pydantic AI](/docs/CS/AI/LLM/LangTool/PydanticAI.md)；四大支柱机制见 [核心机制](/docs/CS/AI/LLM/LangTool/PydanticAI/Core.md)。

V1 时代扩展一个 Agent 要靠给 `Agent` 构造函数不断塞参数——这里一个 `tools` 列表、那里一段 system prompt、别处一组 model settings、最后再 bolt 一个事件 hook。这四样东西没有任何约束要求它们一起旅行，于是"一个可复用的扩展（比如记忆系统、护栏）"意味着每次复用都要手工把好几块不相连的东西接线。**capability 正是用来堵这个缝的**：把指令、工具、生命周期钩子、模型设置打包进一个可组合单元，通过 `capabilities=[...]` 挂上去。

## Core / Capability / Harness 三层

V2 把框架切成三块，边界是刻意的：

| 层 | 包 | 职责 | 节奏 |
|----|----|------|------|
| **Core** | `pydantic-ai-slim` | Agent 循环、模型 provider 适配器、Capability API 本身 | 小而稳，只留需要深度 provider 集成或对几乎所有 Agent 都承重的东西 |
| **Capability** | （API 在 core） | 可组合单元：任何捆绑了 tools / instructions / hooks / model settings 的扩展，经 `capabilities=[...]` 挂载 | —— |
| **Harness** | `pydantic-ai-harness` | 官方预制 capability（内存、护栏、上下文管理、文件访问、代码模式）+ 一个 headless 编码 Agent | 独立发布、仍是 0.x，可快速迭代 |

这个切分不是随意的：**Core 只保留 Thinking、WebSearch、MCP 这类需要深度 provider 支持或几乎每个 Agent 都需要的；其余一切以 Harness 速度演进，并可在证明"广泛必需"后"毕业"进 Core**（官方点名 Code Mode 是 early candidate）。

## 内置与一等 Capability

随 Pydantic AI 自身或 Harness 提供、可直接 `capabilities=[...]` 挂载的代表：

| Capability | 来源 | 作用 |
|-----------|------|------|
| `Thinking` | Core | 跨 provider 统一的扩展思考（reasoning effort） |
| `WebSearch` / `WebFetch` | Core | 原生支持时走 provider 原生，否则本地兜底；V2 起默认 native |
| `MCP`（`MCPToolset`） | Core | 把远端 MCP server 的工具集接入 Agent |
| `ToolSearch` | Core | 按需发现工具，而不是一上来列几百个 |
| `Guardrails` | Harness | 输入/输出护栏 |
| `SpendLimits` | Harness / Core | 成本上限（与 `UsageLimits` 互补） |
| `CodeMode` | Harness | 一次 `run_code` 调用替代 N 次工具调用，由 **Monty**（Pydantic 的安全 Python 子集）沙箱执行 |
| `Memory` / `FileSystem` | Harness | 记忆与文件访问等"电池" |

社区也在贡献 capability（如 Vstorm），官方背书并链接，并努力 upstream。

## 自定义 Capability

简单场景用 `Capability()` 帮助函数即可；需要生命周期钩子（在每一步重写模型看到的工具、指令、消息历史）时，子类化 `AbstractCapability`。后者暴露构造期配置方法 `get_toolset` / `get_native_tools` / `get_instructions` / `get_model_settings`，以及每次运行都会触发的生命周期钩子（如 `before_tool_execute`）：

```python
from dataclasses import dataclass
from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import AbstractCapability

@dataclass
class ApprovalGate(AbstractCapability[None]):
    id: str = 'approval'
    description: str = '删除类操作前需确认。'

    def get_instructions(self) -> str:
        return '在执行删除前先向用户确认。'

    async def before_tool_execute(self, ctx, *, call, tool_def, args):
        if 'delete' in tool_def.name:
            # 自定义审批逻辑
            ...
        return args

agent = Agent('openai:gpt-5.2', capabilities=[ApprovalGate()])
```

`Capability()` 帮助函数最关键的字段是 **`defer_loading`**：设为 `True` 时，该 capability 在 prompt 里只塌缩成一行目录条目，直到模型显式调用框架托管的 `load_capability` 工具才激活——指令生效、工具注册，且跨历史重放保持激活。这对"几百个工具不能全塞进 prompt"的场景是刚需：

```python
from pydantic_ai.capabilities import Capability

refunds = Capability(
    id='refunds',
    description='用于退款资格与状态查询。',
    instructions='处理前务必先确认订单号。',
    defer_loading=True,
)
```

因为 capability 可序列化，一个 Agent 能从 spec 文件加载，表面积小到可以让一个 coding agent 直接替你写——这也是 V2 "harness-first" 想达成的 ergonomics。

## V1 → V2 迁移要点

破坏性变更（已核实，节选）：

- 模型字符串**必须带 provider 前缀**，裸 `'gpt-5'` 抛 `UserError`；
- `openai:` 现走 **Responses API**，`openai-chat:` 才是旧的 Chat Completions；
- MCP 接入从 `mcp_servers=[MCPServerStreamableHTTP(...)]` 改为 `toolsets=[MCPToolset(url)]` 或 MCP capability；
- `builtin_tools` → `native_tools`；`OpenAIModel` → `OpenAIChatModel`；
- 泛型默认从 `None` 改为 `object`（`Agent[object, str]`），影响工具注解方式；
- `end_strategy` 默认从 `'early'` 改为 `'graceful'`（输出产生后，与成功输出同批请求的函数工具现在会执行，而非被跳过）；
- 默认安装精简，Bedrock / Groq / Mistral / Cohere / xAI / HF / Temporal 等走 extras；
- 仪表化（instrumentation）默认 v5，聚合 token 用量落到 `gen_ai.aggregated_usage.*`。

官方推荐的三步升级路径：**升到最新 V1（v1.100.0+）→ 清掉每一个 deprecation 警告 → 升 V2 并修复那些警告没捕获的行为变更**。不必赶——版本政策承诺 V1 在 V2 稳定后至少 6 个月安全补丁，且 V1 仍在持续打补丁（v1.107.7 于 2026-09-29 修安全）。

⚠️ 版本策略本身的变动：主版本之间"无故意破坏变更"的窗口从 **6 个月缩到 3 个月**；大版本不会早于 V2.0 之后 3 个月发布。这是 Pydantic 主动的选择（领域变化太快），不是不重视稳定。

## Links

- [Pydantic AI](/docs/CS/AI/LLM/LangTool/PydanticAI.md)
- [核心机制](/docs/CS/AI/LLM/LangTool/PydanticAI/Core.md)
- [工程化与生产](/docs/CS/AI/LLM/LangTool/PydanticAI/Production.md)
- [MCP](/docs/CS/AI/LLM/Protocol/MCP.md)
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)

## References

1. [Pydantic AI V2 发布说明（capabilities 与 Harness）](https://pydantic.dev/articles/pydantic-ai-v2)
2. [Pydantic AI 文档：Capabilities](https://ai.pydantic.dev/capabilities/)
3. [Pydantic AI Harness 仓库](https://github.com/pydantic/pydantic-ai-harness)
4. [Pydantic AI 升级指南（V1→V2 破坏性变更清单）](https://pydantic.dev/docs/ai/project/changelog/)
5. [Pydantic AI 版本政策](https://pydantic.dev/docs/ai/project/version-policy)
