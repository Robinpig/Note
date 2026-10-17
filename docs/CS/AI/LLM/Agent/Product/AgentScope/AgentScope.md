## Introduction

AgentScope 是阿里巴巴开源的 Python Agent 框架，从 v2.0 开始面向生产场景。核心设计目标是「充分发挥大模型的推理与工具调用能力，而非用严格的提示词和固化的编排方式来束缚它们」——这句话来自官方 README，也是理解它架构选择的钥匙。

这个定位把 AgentScope 放在了 Framework 与 Harness 之间：它提供 LangChain 级别的跨厂商抽象，又把权限、上下文压缩、运行时状态注入这些通常由 Harness 层处理的能力直接做进了核心 Agent 类。再往上，它还附带一套开箱即用的 Agent Service（FastAPI 后端 + 预构建 Web UI），把单个 Agent 包装成多租户、多会话的在线服务。

本笔记以 **v2.0.8** 为基准

本笔记采用「枢纽 + 分册」结构：主干保留架构叙事与跨模块分析，七个专题已拆为独立分册（均基于 v2.0.8 源码逐文件核实，统一放在 `AgentScope/` 子目录）。各分册由哪里接手、按什么顺序读，见下文 [How to Read the Subsystem Notes](#how-to-read-the-subsystem-notes)。

## Quickstart: From Zero to a Running Agent

这一节给一个**最小可运行**的纵向切片，把「装包 → 造模型 → 造 Agent → 跑对话 → 流式渲染 → 拿结构化结果」六个动作串起来。所有 API 取自 v2.0.8 的公开符号：`agentscope.agent.Agent` / `agentscope.model.*` / `agentscope.tool.Toolkit` / `agentscope.message.UserMsg` / `agentscope.console.launch_console` / `agentscope.event`。

### Installation

```bash
pip install "agentscope[tools]"   # [tools] 提供内置 Grep 依赖的 ripgrep 二进制
```

### A Minimal Conversational Agent

不带任何工具、不做权限交互，可以直接 `reply()` 拿最终结果：

```python
import asyncio
from agentscope.agent import Agent
from agentscope.credential import OpenAICredential
from agentscope.message import UserMsg
from agentscope.model import OpenAIChatModel
from agentscope.tool import Toolkit

async def main() -> None:
    agent = Agent(
        name="Friday",
        system_prompt="You are a helpful assistant.",
        model=OpenAIChatModel(
            credential=OpenAICredential(api_key="sk-..."),
            model="gpt-4.1",
            stream=True,
        ),
        toolkit=Toolkit(),          # 空工具集 = 纯对话
    )
    reply = await agent.reply(
        UserMsg(name="user", content="用一句话解释什么是 ReAct。"),
    )
    print(reply.content[0].text)   # content 是 list[ContentBlock]，文本在 TextBlock.text

asyncio.run(main())
```

两个容易踩的点：① `UserMsg(name, content)` 的 `content` 既可以是纯字符串（自动包成 `TextBlock`）也可以是 `list[TextBlock | DataBlock]`；② `reply()` 内部把整条事件流消费完、返回**最后一条** `Msg`，中间的工具调用 / 思考事件不出现在返回值里。

### A Full Agent in the Terminal (Tools and HITL)

想要文件工具、skill、工具调用人工确认、Ctrl+C 中断这一整套终端体验，用 `launch_console` 一行接管，不用自己写事件渲染与交互：

```python
import asyncio, os
from agentscope.agent import Agent
from agentscope.console import launch_console
from agentscope.credential import DashScopeCredential
from agentscope.message import UserMsg
from agentscope.model import DashScopeChatModel
from agentscope.tool import Toolkit
from agentscope.workspace import LocalWorkspace

async def main() -> None:
    async with LocalWorkspace(workdir="./workspace") as ws:
        agent = Agent(
            name="Friday",
            system_prompt="You are Friday. Use the provided tools when helpful.\n"
                          + await ws.get_instructions(),
            model=DashScopeChatModel(
                credential=DashScopeCredential(api_key=os.environ["DASHSCOPE_API_KEY"]),
                model="qwen3.7-max", stream=True,
            ),
            toolkit=Toolkit(tools=await ws.list_tools(),
                            skills_or_loaders=await ws.list_skills()),
            offloader=ws,                  # 压缩掉的上下文 / 超大工具结果落盘到 workspace
        )
        await launch_console(agent)

asyncio.run(main())
```

（这是仓库 `examples/console/main.py` 的精简版；`LocalWorkspace` 同时提供文件系统后端与 skill 来源，文件系统级长期记忆由 `AgenticMemoryMiddleware` 注入。）

### Adding a Custom Tool

```python
from agentscope.tool import FunctionTool

def get_weather(city: str) -> str:
    """查询指定城市的当前天气。

    Args:
        city: 城市名称，例如「北京」
    """
    return f"{city}: 晴，25°C"

agent = Agent(
    ...,
    toolkit=Toolkit(tools=[FunctionTool(get_weather)]),
)
```

`FunctionTool` 从函数签名 + docstring **自动抽取 JSON schema**；默认 `is_concurrency_safe=True`、`is_read_only=False`，因此默认权限是 ASK——这就是为什么带工具的 Agent 走 `launch_console` 这类带 HITL 的入口最顺。想在非交互脚本里直接放行，把 `AgentState.permission_context.mode` 设成 `BYPASS`（见 [Permission System](#permission-system)）。

### Streaming Rendering

`reply_stream()` 产出 `AsyncGenerator[AgentEvent | Msg]`。下面的骨架把文本增量与工具调用增量分别渲染（事件类型与 `Msg.append_event()` 重建规则见 [Pipeline 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Pipeline.md)）：

```python
from agentscope.event import TextBlockDeltaEvent, ToolCallDeltaEvent
from agentscope.message import Msg

async for chunk in agent.reply_stream(UserMsg(name="user", content="...")):
    if isinstance(chunk, TextBlockDeltaEvent):
        print(chunk.delta, end="", flush=True)   # 文本增量
    elif isinstance(chunk, ToolCallDeltaEvent):
        ...                                       # 工具调用增量（参数 JSON 片段）
    elif isinstance(chunk, Msg):                  # 最后一条完整消息
        break
```

### Structured Output

`msg.content` 是自由文本，但很多时候你要的是**强类型的字段**。`Agent.reply()` / `reply_stream()` 的 `structured_schema` 参数接受一个 Pydantic `BaseModel` 子类，模型被要求按该 schema 输出 JSON，校验通过后的字典挂在返回 `Msg` 的 `structured_output` 上（`None` 表示未请求，或回复在产出前就中断 / 出错——见 `Msg.structured_output` 的字段注释）。

```python
from pydantic import BaseModel
from agentscope.message import UserMsg

class Weather(BaseModel):
    city: str
    temp_c: int
    condition: str

reply = await agent.reply(
    UserMsg(name="user", content="北京现在天气怎么样？"),
    structured_schema=Weather,
)
print(reply.structured_output)   # {'city': '北京', 'temp_c': 25, 'condition': '晴'}
```

流式场景要显式 `yield_final_msg=True`——否则 `reply_stream()` 默认只 yield 事件、跳过最后的 `Msg`：

```python
async for chunk in agent.reply_stream(
    UserMsg(name="user", content="..."),
    structured_schema=Weather,
    yield_final_msg=True,
):
    if isinstance(chunk, Msg):
        print(chunk.structured_output)
```

结构化输出失败属于 `DeveloperOrientedException` 里的 `StructuredOutputError`——是配置或模型能力问题，框架把它和工具层错误明确分开（见 [Supporting Types](#supporting-types-exception-a2a-task)）。模型不支持时的降级（回退为文本 + 后处理解析）逻辑在 [Model 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Model.md)。

## Architecture Overview

AgentScope v2.0 的核心架构可以概括为三层：

| 层次 | 组件 | 职责 |
| :--- | :--- | :--- |
| **Core Agent** | `Agent` 类 + ReAct 循环 | 推理-行动的主循环、上下文管理、事件流式输出 |
| **Infrastructure** | Model / Toolkit / Permission / Middleware / Offloader | 模型调用、工具执行、权限判定、可插拔钩子、上下文卸载 |
| **Service** | FastAPI 后端 + Web UI | 多租户多会话、频道接入、Hub（MCP/Skill）、定时调度 |

核心设计选择只有一个——**一切围绕 `Agent` 类展开**。没有 BaseAgent → ReActAgent → PlanAgent 的类继承层次，`Agent` 就是唯一入口。ReAct 循环是内置的，规划、子 Agent、HITL、中断、压缩全都是这个类里的方法或中间件实现。这意味着一个 AgentScope Agent 可以同时具备 ReAct、Plan-and-Execute、HITL、上下文压缩等能力，而不需要切换类。

## How to Read the Subsystem Notes

七个分册按「**装配 → 边界 → 编排 → 服务化**」四条线组织，大致对应上面三层表里的 Infrastructure 与 Service 两层。只想把框架用起来的读者读完 Quickstart 与 Architecture Overview 即可；要改框架行为、或判断某个能力该不该自己补，按下面四条线找对应分册。

**装配线：一个 Agent 身上挂什么。**[Tool 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Tool.md) 讲工具体系——内置 13 个工具自己不做任何 I/O、全部委托 `BackendBase`，`ToolBase` 之下的三种实现（手写类 / `FunctionTool` / `MCPTool`）统一走中间件洋葱链，模型拿到的永远是同一套 JSON schema。[Middleware 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Middleware.md) 讲最值得细看的一层：`MiddlewareBase` 的 7 个 hook 与 `is_implemented()` 分派、内置中间件家族（预算 / TTS / 追踪 / 长期记忆三实现），以及权限 DSL 的完整细节（5 模式 × 4 行为、引擎 6 步判定、`bypass_immune` 安全 ASK）。[Model 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Model.md) 讲模型层——「统一 `Msg` 序列 → 厂商 JSON」的翻译为什么收拢在 formatter、10 个厂商子模块的卡片清单，以及 retry 包着的直通调用线。

**边界线：Agent 伸手能碰到什么。**[RAG 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/RAG.md) 讲自带的那套完整 RAG（`rag/`，纯算法层、可完全独立使用）：Parser → Section → Chunk → embed → VectorStore 的数据流、`Chunk` 比 `Section` 多出的两个字段为什么服务检索期，以及它与服务层托管版（`app/rag/knowledge_base_manager/`）的边界。

**编排线：一串 Agent 怎么跑。**[Pipeline 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Pipeline.md) 讲 AgentScope 的「事件织物」：`PipelineProtocol` 只暴露 `reply_stream()` 一个方法、强类型事件系统（`EventType` 28 值）、支撑类型（`ReplyFinishedReason` / `ErrorInfo` / Hook 类型），以及 `Msg` 的状态机式增量重建——尤其是 DataBlock 的 base64 拼接陷阱。[Realtime 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Realtime.md) 讲另一个完全不继承 `Agent` 的类：双向语音会话、无 request/reply 边界，turn-taking 状态机夹在实时模型与 transport 之间。

**服务化线：怎么上线。**[App 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/App.md) 讲 v2.0.8 起成为正式包的 Agent Service：`create_app` 工厂与 15 个路由、`lifespan` 的 AsyncExitStack 生命周期、Redis + 异步 SQLAlchemy 双存储后端、Hub 抽象（GitHub MCP + ClawHub Skill）、Workspace 隔离策略与跨 owner 资源访问策略。

## The Unified Agent Class

`Agent` 类（`agent/_agent.py`，约 2500 行）是整个框架的心脏。构造函数接收四大配置对象：

```python
Agent(
    name="Friday",
    system_prompt="...",
    model=DashScopeChatModel(...),
    toolkit=Toolkit(tools=[Bash(), Grep(), ...]),
    middlewares=[...],
    model_config=ModelConfig(...),        # fallback model + retries
    context_config=ContextConfig(...),    # 压缩阈值 + 摘要模板
    react_config=ReActConfig(...),        # max_iters + 中断行为
    injection_config=InjectionConfig(...),# 运行时状态注入
)
```

四个 Config 是 Pydantic BaseModel，字段默认值覆盖了绝大多数场景。`_validate_configs()` 在构造时检查一个核心不变量：`reserve_ratio < trigger_ratio`、`context_buffer_ratio < trigger_ratio`——确保压缩阈值、缓冲区间距、保留区三者不重叠。

Agent 的两个公开方法是 `reply()` 和 `reply_stream()`，后者返回 `AsyncGenerator[AgentEvent | Msg]`。内部统一走 `_reply()` → 中间件链 → `_reply_impl()` 主循环。

## Message System

AgentScope 的消息模型是 **结构化 ContentBlock 列表**，而不是纯文本。`Msg.content` 是 `list[ContentBlock]`，六种 block 类型：

| Block 类型 | 角色限制 | 内容 |
| :--- | :--- | :--- |
| `TextBlock` | 全部 | 文本 |
| `ThinkingBlock` | 仅 assistant | 模型推理过程（reasoning token） |
| `ToolCallBlock` | 仅 assistant | 工具调用意图（id + name + input JSON） |
| `ToolResultBlock` | 仅 assistant | 工具执行结果（id + name + output + state） |
| `DataBlock` | user / assistant | 多模态数据（image / audio / file） |
| `HintBlock` | 仅 assistant | 系统提示（运行时注入、offload 提醒） |

role 有严格约束：`user` 只收 TextBlock + DataBlock；`system` 只收 TextBlock；`assistant` 收全部。`Msg` 的 Pydantic validator 在构造时强制执行这些约束。

`Msg` 还携带 token usage（input/output/cache 分拆）、`structured_output`（结构化输出时填充）、`finished_reason`（COMPLETED / INTERRUPTED / EXCEED_MAX_ITERS / ERROR）等元数据。`append_event()` 方法是流式输出的重建器——把一串 AgentEvent 按 reply_id 归并到一条 Msg 的 content 里。

## Event-Driven Streaming

AgentScope 的输出是**事件流**，不是文本流。`agent._agent.py` 的事件类型覆盖了 reply 的每个阶段：

```
REPLY_START → MODEL_CALL_START → TEXT_BLOCK_START → TEXT_BLOCK_DELTA* → TEXT_BLOCK_END
                               → TOOL_CALL_START → TOOL_CALL_DELTA* → TOOL_CALL_END
                               → THINKING_BLOCK_START → ...
                               → MODEL_CALL_END → ...
→ (每轮 ReAct 循环)
→ REPLY_END
```

还有三类交互事件：
- `REQUIRE_USER_CONFIRM` / `USER_CONFIRM_RESULT` —— 工具调用需要人工确认，Agent 暂停等待
- `REQUIRE_EXTERNAL_EXECUTION` / `EXTERNAL_EXECUTION_RESULT` —— 外部系统执行的工具（后台任务卸载），Agent 提交后继续等待
- `USER_INTERRUPT` —— 用户中断，Agent 关闭所有 pending 工具调用

HITL 交互的核心设计：Agent 在遇到需要确认的工具调用时，**不抛出异常也不返回结果**，而是 yield `RequireUserConfirmEvent` 后停在 await 点。调用方（Web UI、Console、上游 Agent）决定后把结果作为下一次 `reply()` 的输入传回来——同一个 Agent 实例、同一条上下文、循环从断点继续。

事件类型枚举（`EventType` 28 值）、`Msg.append_event` 状态机与 DataBlock base64 增量拼接陷阱的完整清单见 [Pipeline 分册（事件与类型）](/docs/CS/AI/LLM/Agent/Product/AgentScope/Pipeline.md)。

## ReAct Loop: The Core

`_reply_impl()` 是约 300 行的主循环，核心逻辑在一个 `while True` 里：

```python
while True:
    next_action = self._next_action(final_msg)

    match next_action:
        case Exit(...):         # 没有工具调用 + 已完成
            yield exit_msg
            return

        case Reasoning(...):    # 调用模型
            await self.compress_context()        # 先检查压缩
            async for evt in self._inject_runtime_state():
                yield evt
            async for evt in self._reasoning():  # 调模型、流式输出
                yield evt

        case Acting(...):       # 执行工具调用
            for batch in await self._batch_tool_calls(tool_calls):
                # 按 is_concurrency_safe 分 batch
                if batch.type == "concurrent":
                    async for evt in self._execute_concurrent_tool_calls(...):
                        yield evt
                else:
                    async for evt in self._execute_sequential_tool_calls(...):
                        yield evt
```

### Three Action Types

`_next_action()` 根据当前状态返回三种之一：

1. **Exit**：模型没有返回工具调用（纯文本回复），或迭代次数超过 `max_iters`，或收到中断信号
2. **Reasoning**：正常下一轮模型调用
3. **Acting**：模型返回了工具调用，需要执行

### Batch Tool Execution

模型一轮可能返回多个工具调用。`_batch_tool_calls()` 按工具的 `is_concurrency_safe` 属性分批——**安全的并发执行，有副作用的顺序执行**。同一批次内并发调用通过 `asyncio.gather(return_exceptions=True)` 并行跑，结果通过 `asyncio.Queue` 合并事件流。

顺序执行遇到 `RequireUserConfirmEvent` 或 `RequireExternalExecutionEvent` 时立即 break，后续调用在恢复后继续；并发执行时用户确认会导致整批的后续调用也停下来。

### Interruption

中断路径分两条：
- **`UserInterruptEvent` 主动触发**：Agent 先跑 `_close_unfinished_tool_calls()` 把所有 pending 的 ToolCall 标成 INTERRUPTED 并补 ToolResult，然后 yield 一条默认消息（`react_config.interruption_message`）
- **`asyncio.CancelledError` 被动捕获**：压缩过程被中断、模型调用超时等。`react_config.interruption_raise_cancelled_error` 决定是吞掉异常让循环正常结束还是 re-raise

### HITL State Machine

Agent 的 ToolCall 有完整的生命周期：

```
PENDING → ASKING → ALLOWED → FINISHED
                 → DENIED
                 → SUBMITTED → FINISHED
                 → INTERRUPTED（用户中断）
                 → ERROR（执行失败）
```

`_check_incoming_event()` 确保状态一致性——如果 Agent 正在等待 2 个工具的确认，只传回来 1 个结果会报错；传回来的工具 id 不在等待列表里也会报错。

## Middleware System

中间件是 AgentScope 最值得细看的设计。`MiddlewareBase` 定义了 **7 个 hook**，运行时自动检测子类实现了哪些（`is_implemented()` 用 `base_method is not sub_method` 判断），Agent 在构造时把它们按 hook 类型分到七个列表里。

七个 hook 分两种模式：

**Onion Pattern（6 个，有 before/after 语义）**：
- `on_reply` —— 拦截整个 reply 循环。**可以吞掉 ReplyEndEvent 强制多跑一轮**（不 yield 它），`_receive_reply_end` 标志位防止中间件无限套娃
- `on_reasoning` —— 拦截模型调用前后
- `on_acting` —— 拦截单个工具执行的纯 I/O 层（不包含权限检查、输入校验、context 写入）
- `on_check_permission` —— 拦截权限判定，middleware 可以替代引擎返回决策
- `on_model_call` —— 拦截底层 API 调用
- `on_compress_context` —— 拦截上下文压缩

**Transformer Pattern（1 个，串行管道）**：
- `on_system_prompt` —— 把 system_prompt 字符串改一下返回，每个 middleware 拿上一个的输出当输入

Onion hook 的签名统一是：
```python
async def on_xxx(self, agent, input_kwargs, next_handler):
    # before: agent=agent（可读写 agent 状态）
    async for item in next_handler(**input_kwargs):
        # after: yield 前可修改事件
        yield item
```

中间件链内部用递归构造执行器（`execute_chain`），和 Koa/Express 的洋葱模型写法一模一样。

七个 `on_*` hook 的签名语义、`ReplyBudgetControlMiddleware` / `TTSMiddleware` / `TracingMiddleware` / 三类长期记忆中间件，以及权限 DSL（`PermissionMode` / `PermissionRule` / `PermissionDecision` / `PermissionContext` / `bypass_immune` 安全 ASK）的逐文件事实见 [Middleware 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Middleware.md)。

## Permission System

权限系统由 `PermissionEngine` + `PermissionRule` + `PermissionDecision` 组成。五种模式覆盖了从最严格到最宽松的完整光谱：

| 模式 | 默认行为 | 典型场景 |
| :--- | :--- | :--- |
| `DEFAULT` | 非只读操作都 ASK | 日常使用，每步确认 |
| `EXPLORE` | 只读 ALLOW，修改 DENY | 探索代码库、浏览 |
| `ACCEPT_EDITS` | 工作目录内的编辑自动 ALLOW | 编码场景（Write/Edit 工作目录） |
| `BYPASS` | 除 DENY 规则外全部 ALLOW | 沙箱环境、全托管场景 |
| `DONT_ASK` | 所有 ASK 转成 DENY | 定时任务、后台无人值守 |

每个 mode 有独立的 `_check_<mode>` 方法，优先级链清晰：

```
deny_rules → ask_rules → read_only → tool.check_permissions → allow_rules → mode_fallback
```

**三个关键设计**：

1. **Safety ASK（bypass_immune）**：工具自己返回的 ASK 可以标记 `bypass_immune=True`，在 DEFAULT/ACCEPT_EDITS 模式下无法被 allow rule 覆盖。典型场景是 `Bash("rm -rf /")`——即使用户加了 `Bash:*` 的允许规则，安全 ASK 仍然会弹确认。BYPASS 模式主动跳过安全 ASK（因为"完全信任用户"），DONT_ASK 把安全 ASK 转成 DENY（因为"没人回答"）。

2. **suggested_rules**：每次 ASK 都生成建议规则（Bash 提取命令前缀、文件操作提取目录 glob），用户一键添加后下次同类调用自动放行。

3. **Concurrent batch 内的 ASK 去重**：并发执行多个工具时，同一批次的 `kept_rules` 列表累积已确认生成的 allow rule。后续工具的 ASK 如果已被某个 earlier rule 覆盖，就不再弹第二次——只对非安全 ASK 生效。

权限 DSL 的完整逐文件事实（五种模式字段语义、`_check_<mode>` 分发顺序、`suggested_rules` 生成、`DenyAllResourceAccessPolicy` 跨 owner 访问）见 [Middleware 分册（权限）](/docs/CS/AI/LLM/Agent/Product/AgentScope/Middleware.md)。

## Context Management

AgentScope 的上下文管理有三层机制，**全部在核心 Agent 类里**，不是中间件。

### ContextConfig

```python
ContextConfig(
    trigger_ratio=0.8,         # 触发硬压缩的 token 比例
    reserve_ratio=0.1,          # 压缩后保留的尾部上下文比例
    context_buffer_ratio=0.2,   # 缓冲区：提前注入"快到压缩了"的提示
    tool_result_limit=50000,    # 工具结果 token 上限，超过截断
    max_image_num=5,            # 上下文里最多保留的图片数
    compression_tool_enabled=False,  # 是否暴露 CompressContext 工具给 Agent
    compression_fallback_to_truncation=True,  # 压缩失败时降级为截断
)
```

`trigger_ratio` 最大 0.9，留出最后 10% 给压缩过程本身；`reserve_ratio` 不能 >= `trigger_ratio`——否则压缩完保留区就比整个窗口还大了。

### Structured Compression

压缩不是一把梭，而是结构化的。`SummarySchema` 定义了压缩产物的五个维度：

1. `task_overview` —— 用户核心请求与成功标准
2. `current_state` —— 已完成的工作（文件路径、关键输出）
3. `important_discoveries` —— 技术约束、决策理由、踩过的坑
4. `next_steps` —— 具体下一步动作
5. `context_to_preserve` —— 用户偏好、领域细节、已做的承诺

压缩提示词（`compression_prompt`）里特别强调了**时间锚定**（"today" 转绝对日期）、**指针解析**（不能写 "this file" 必须写完整路径）、**后台任务状态**（"我还在等哪个任务的结果"）——因为压缩后的摘要可能被再次压缩，所有引用必须自包含。

压缩产物通过 `summary_template` 格式化成 `<system-info>...</system-info>` 块，替换掉上下文里被压缩的消息，保存在 `AgentState.summary`。

### Runtime State Injection

`InjectionConfig` 控制每轮 reasoning 前注入的四个维度：

1. **Time**：当前时间（指定时区），首次 reply 或上次注入超过 `time_interval`（默认 0.5 小时）时触发
2. **Plan Tasks**：有 pending/in_progress 任务且上下文里没提过时触发（通过扫描 TaskCreate/TaskList 等工具调用或上次的 tasks injection 判断）
3. **Context Length**：reply 开始时 token 超过 `(trigger - buffer) * context_size` 触发。如果 `compression_tool_enabled=True` 且没在做任务，还会告诉 Agent "你可以主动调 CompressContext"
4. **Tool Error**：同一个工具 + 相同参数连续失败 `tool_retries_limit`（默认 3）次时，注入提示 "别再重试了，换个方式"

所有注入都通过 `HintBlock`（不是改 system prompt）实现，**故意这样做是为了让 prompt caching 继续生效**——system prompt 一 cache 就锁死了，而 HintBlock 每次追加到 context 尾部，不影响前缀缓存。

### Offloader

如果提供了 `Offloader`，压缩掉的上下文和超过 `max_image_num` 的旧图片会被写到 workspace（Daytona / Bubblewrap / 本地文件），原来的位置替换成 `<system-reminder>offloaded to /path</system-reminder>`——不是丢弃，而是换个地方放。

三条具体落盘路径（JSONL 上下文、扁平工具结果、多模态 blob）见后面 Workspace and Sandbox 一节的 Offloading 小节。


## Tool System

> 工具层的完整事实（13 个内置工具、三种 Adapter 实现、`BashCommandParser` 真实解析、`BackendBase` 三原语与后端矩阵、Compression Tool）已拆到独立分册：[Tool 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Tool.md)。本节在主干中仅保留枢纽定位。
## Workspace and Sandbox

上一节的工具做的是「参数校验 + 结果整形」，真正的读写在一层极易被忽略的抽象里——**`BackendBase`**。这是 AgentScope 把「Agent 在哪台机器上跑」和「Agent 怎么调工具」彻底解耦的地方，也是它能从笔记本本地执行无缝切到容器沙箱的原因。

### BackendBase: Three Primitives

`WorkspaceBase`（`workspace/_base.py`）自己**不定义任何文件读写方法**，全部委托 `BackendBase`（`tool/_builtin/_backend.py`）。后者只有三个抽象方法：

```python
async def exec_shell(self, command: str, ...) -> ...     # _backend.py:294
async def read_file(self, path: str) -> bytes            # :331
async def write_file(self, path: str, content: bytes)    # :344
```

其余十来个能力（`file_exists` / `is_dir` / `list_dir` / `scandir` / `stat` / `stat_mtime` / `delete_path` / `getcwd` / `expanduser` / `write_stream` / `read_stream`）全部是**基于 `exec_shell` 的默认实现**，`LocalBackend` 才覆盖成原生系统调用。

这个三层划分（工具 → backend → 真实文件系统）让同一套 `Read` / `Write` / `Bash` 工具可以在本地进程、容器、K8s Pod、远端托管沙箱上跑同一份代码。

### The Backend Matrix

`SandboxedWorkspaceBase`（`_sandboxed_base.py`）是所有沙箱的公共基类，提供四件事：

1. **生命周期钩子**——`_provision_backend()` / `_teardown_backend()` / `_bootstrap_commands()`（Docker 镜像内置 venv，所以返回空）
2. **网关启动命令**——`nohup {venv python} -u _mcp_gateway_app.py --port N > gateway.log 2>&1 &`，启动前先 `pkill` 掉残留进程
3. **健康探测**——GatewayClient 轮询 `/health`，30s 超时，退避从 0.1s 涨到 1.0s，超时后 tail 日志抛错；单条 bootstrap 命令超时 1800s（E2B 600s）
4. **清理**——`close()` 先关网关再拆后端，`reset()` 删掉 `sessions/ data/ skills/ .mcp`

具体的容器镜像不在这个基类里，由各子类自己提供。各实现的差异：

| 后端 | 目录 | 要点 |
| :--- | :--- | :--- |
| Local | `_local_workspace.py` | `_python_command = sys.executable`，Windows 换 PowerShell；技能安装走 `.skills` hash 索引 + `shutil.copytree` |
| Bubblewrap | `_bubblewrap/` | 需 `share_net=True`，源码注释明确警告**它不是网络沙箱** |
| Docker | `_docker/` | `_build_or_reuse_image()` + 动态生成 Dockerfile；仅绑定挂载时 `is_persistent=True` |
| Kubernetes | `_k8s/` | Pod 作为 workspace 载体 |
| Daytona / E2B | `_daytona/` `_e2b/` | 远端托管沙箱，E2B 用 `template=DEFAULT_TEMPLATE` |
| OpenSandbox | `_opensandbox/` | 另一套远端沙箱协议 |
| AppleContainer | `_applecontainer/` | macOS 原生容器 |

**只有沙箱才有**的能力是 MCP 网关——沙箱内的 MCP  clients 统一走那个 `_mcp_gateway_app.py` 代理。

### Gateway Shim: Shell As Transport

`_gateway_shim.py` 解决了一个很实际的部署问题：网关只监听沙箱内部的 loopback，宿主机网络不可达，怎么调它？答案是在沙箱内 `python3 -c` 跑一段**只用 stdlib `urllib` 的中继脚本**，把 HTTP 请求的输出序列化成 `{status, body|body_file, error}`（超过 4MB 的 body 落文件不内联）。

于是就有了 `_gateway_client.py` 里的三个类：`GatewayClient`（`/health`、`/mcps` 门面）、`GatewayMCPClient`、`GatewayMCPTool`（工具名规则 `mcp__{mcp}__{tool}`，调 `POST /mcps/{name}/tools/{tool}`）。整条链路是 exec_shell → shim → localhost → 网关 → 真正的 MCP server。不优雅，但对「网络隔离的沙箱」这个约束来说是最稳的做法。

### Offloading: Where Compressed Context Actually Goes

`Offloader`（`workspace/_offload_protocol.py`）是个 **Protocol**，只有三个方法——`offload_data_block` / `offload_context` / `offload_tool_result`。`WorkspaceBase` 是它的默认实现，而 Agent 只依赖这个 Protocol（`agent/_agent.py:195`）。换句话说 offloader 是可替换的，不必是 workspace。

workspace 布局是固定的（`_utils.py`）：

```
${workdir}/
├── data/        # 卸载出来的多模态负载
├── skills/      # 安装进来的 skill
├── sessions/    # 按 session 分的上下文与工具结果
└── .mcp         # MCP 声明，只记录偏离 default_mcps 的 session
```

三条落盘路径：

- **上下文压缩**——`offload_context()` 把消息**追加**写进 `sessions/<session_id>/context.jsonl`，一行一条 JSONL。写之前会把 inline base64 的 DataBlock 先抽到 `data/` 再改写成 `file://` URL 块，保证单行体积有界
- **超长工具结果**——`offload_tool_result()` 写 `sessions/<session_id>/tool_result-<id>.txt`；同名冲突时后缀 `(1)` `(2)`，绝不覆盖旧内容
- **多模态数据**——`offload_data_block()` 写 `data/<sha256(base64)>.<ext>`，同内容短路复用

关键点：**没有自动回读 API**。卸载后只在原位留下 `<system-reminder>offloaded to /path</system-reminder>`，让 Agent 自己用 Read / Grep 去取。这个设计把「要不要找回上下文」的决策权留给了模型——大部分被卸载的内容确实不该再读回来。

注意别混淆：**Application 层还有一个后台工具卸载**（`app/middleware/_tool_offload_middleware.py`），默认 10s 超时后不取消任务，转交给 `BackgroundTaskManager`，跑完通过 HintBlock 投递 session inbox 并唤醒 Agent。那个是「任务后台化」，这个是「上下文磁盘化」，两回事。


## RAG Subsystem

> RAG 子系统的完整事实（`_document`/`_parser`/`_chunker`/`_knowledge` 算法层、`RAGMiddleware` 双模式、与服务层 `knowledge_base_manager` 的边界）已拆到：[RAG 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/RAG.md)。
## Skill Loading

Skill 的数据结构极简（`skill/_base.py` 的 dataclass，六个字段：`name` / `description` / `dir` / `markdown` / `updated_at`），加载逻辑也就没什么花样：

- **目录约定**：每个 skill 根目录下必须有 `SKILL.md`，除此之外**不读任何东西**（没有 scripts 子目录机制）
- frontmatter 用 `frontmatter.loads()` 解析，取 `name` 与 `description`，两者任一缺失就 warn 并跳过整个 skill
- 缓存键是 skill 根目录，失效判据是 mtime **精确相等**
- 发现阶段用 `asyncio.to_thread(os.walk)` 避开阻塞，加载阶段 `asyncio.gather(..., return_exceptions=True)` 并发读文件；所有失败路径都吞异常返回空列表

值得记的是 **Jinja2 渲染的时机不在 `skill/` 包里**——skill 正文进入 `Toolkit` 后，要在生成 system prompt 时才渲染（`tool/_toolkit.py:466`）：

```python
template = Template(self.skill_instruction_template)
return template.render(
    skills=skills.values(),
    skill_viewer=self.builtin_skill_viewer.tool.name,
)
```

加载时只做 YAML frontmatter 解析，字符串渲染推迟到最后组装 prompt 那一刻。这样同一个 loader 可以被多种渲染方式复用。

## Formatter Layer

模型适配真正的复杂点不在「怎么发 HTTP 请求」，而在「怎么把统一的 `Msg` 序列翻译成某家 API 认得的 JSON」。AgentScope 用一整包 formatter 来收拢这件事——每家厂商两个类（`XxxChatFormatter` / `XxxMultiAgentFormatter`），目前 11 个文件覆盖 OpenAI / Anthropic / Gemini / DashScope / DeepSeek / Moonshot / Ollama / Volcengine / xAI。

`FormatterBase`（`formatter/_formatter_base.py`）的抽象面窄得出人意料——**只有一个抽象方法**：

```python
# formatter/_formatter_base.py:46
@abstractmethod
async def format(self, *args, **kwargs) -> list[dict[str, Any]]:
```

没有独立的 system prompt / memory / tool schema 抽象方法。基类只提供几个共享工具：`convert_tool_result_to_string()`（把工具结果里支持的媒体用 block.id 作 identifier 写进 `<system-reminder>`，并把它作为「提升」出来的 user 消息返回）、`_convert_unsupported_data_block_to_string()`（不支持的媒体 base64 落临时文件、URL 保持 URL）、`_group_messages()`（把 Msg 流切成 tool_sequence / agent_message 两组）。

值得一提的是：**仓库里没有任何 LangChain 兼容层**，全树搜不到 `langchain` 字样。

### Four Vendors, Four Divergent Choices

| 设计点 | OpenAI | Anthropic | Gemini | DashScope |
| :--- | :--- | :--- | :--- | :--- |
| 消息形状 | `{role, name, content[]}` | `{role, content[]}` | `{role, parts[]}`，assistant 改叫 `model` | OpenAI 兼容 + 扩展 |
| system prompt | 只在 MultiAgent 且首条是 system 时单独生成 | 生成后由 model 层从 messages 里 pop 进 `kwargs["system"]` | **降级为普通 `{"role": "user"}`** | 同 OpenAI |
| tool call | `tool_calls[]` + `function.arguments` | `{"type": "tool_use", "input": {...}}` | `{"function_call": {...}}` | 同 OpenAI |
| tool result | 独立 `{"role": "tool", "tool_call_id"}` | `{"type": "tool_result"}`，**必须包在 role=user 里；并行结果必须合并进同一条**，拆开会 400 | `{"function_response": {...}}` | 同 OpenAI |
| 多模态 | image→`image_url`；audio→`input_audio`（仅 wav/mp3，远端 URL 要下载） | 仅 image/PDF，全部 base64 | 统一 `{"inline_data": {...}}` | 独有 `video_url`；audio 远端 URL 直传不下载 |
| ThinkingBlock | **丢弃** | 无 `signature` 就丢弃；有 `redacted_thinking_data` 则还原 | `{"thought": true}`，空则跳过 | **唯一支持回灌**：`reasoning_content` 字段，由 `supports_thinking_input` 开关控制 |

这张表解释了一个反直觉的事实——**thinking block 能不能跨轮保留，不是上层框架决定的，而是厂商 formatter 的私有能力**。DashScope 之外，你此刻的推理过程在下一轮就已经不在上下文里了。

另外 formatter 层**没有流式概念**，所有 `format()` 返回的都是完整 `list[dict]`；流式累加在 model 层做。


## Model Abstraction

> 模型抽象层的完整事实（`ModelBase` 调用流、retry 直通线、block.id 流式累加、结构化输出回退、token 计数、`CredentialFactory`）已拆到：[Model 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Model.md)。
## Supporting Types: Exception, A2A, Task

### Exception Model

异常只有 7 个类，但分类逻辑很清晰（`exception/_base.py`）：

```python
class AgentOrientedException(Exception):
    """The base class for all agent-oriented exceptions. These exceptions are
    expect to the captured and exposed to the agent during runtime, so that
    agents can handle the error appropriately during the runtime."""
```

- **`AgentOrientedException`** —— 预期在运行时被捕获并**暴露给 Agent**，让它自行纠错。全部 4 个 tool 异常都走这条：`ToolNotFoundError` / `ToolInterruptedError` / `ToolJSONDecodeError` / `ToolGroupInactiveError`
- **`DeveloperOrientedException`** —— 抛给开发者。目前只有 1 个：`StructuredOutputError`

分类逻辑一句话：**工具层错误是 Agent 能看懂并重试的，所以给 Agent；结构化输出错误是配置或模型能力问题，只能让开发者改。**

### A2A Agent and Task Model

`agent/_a2a_agent.py` 的 `A2AAgent` 是把远端 [A2A](/docs/CS/AI/LLM/Protocol/A2A.md) Agent 包装成本地 Agent 形态的适配器——它持有独立的 `A2AAgentState`（含协议层的 `context_id` / `task_id`，与 `AgentState` **没有继承关系**），把 `a2a.types.Part` 转成 `Msg` 的 content block，并发 `ReplyStartEvent` 等本地事件流。用途是让远端 Agent 能混进本地 Pipeline 编排。

Plan 机制的数据模型在 `state/_task.py`：一个带 DAG 依赖的通用 Task（`blocks` / `blocked_by` 双向列表、`state` 三值 `pending / in_progress / completed`），没有 Plan / Injection 之分。这也解释了为什么 `TaskUpdate` 支持 `add_blocks` / `add_blocked_by` 这类字段。


## Realtime Agent

> `RealtimeAgent`（双向语音、turn-taking 状态机、不继承 `Agent`）的完整事实已拆到：[Realtime 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Realtime.md)。

## Pipeline & Agent Service

`PipelineProtocol` 与 `Agent` 共用 `reply_stream()` 接口——Pipeline 是「固化逻辑的多 Agent 编排器」，按预设顺序把消息喂给一串 Agent；`GoalPipeline` 在此基础上加 executor/verifier 循环与目标检查。事件类型枚举（`EventType` 28 值）、`Msg.append_event` 状态机、DataBlock base64 增量拼接陷阱，以及 Types 系统（`ReplyFinishedReason` / `ErrorType` / `AgentHookTypes`）的完整事实见 [Pipeline 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Pipeline.md)。

Agent Service（`src/agentscope/app/`）到 v2.0.8 已是正式包：2MB、约 200 文件的应用层，按职责分 `_router/` `_service/` `_manager/` `_tool/` `storage/` `rag/` `hub/` `workspace_manager/` 八目录，外加 Feishu / Discord / DingTalk 频道适配与 GitHub MCP Hub、ClawHub Skill Hub。依赖按组分包（`agentscope[service]` / `[storage-sql]` / `[workspace-docker]` / `[tools]`），连内置 Grep 工具都锁 `ripgrep>=14.1,<15`（15.x 缺 Windows / glibc<2.39 / musl / aarch64 的 wheel，远程沙箱走镜像内安装）。存储层有两套后端（`AsyncSQLAlchemyStorage` + `RedisStorage`），**路由器注册 15 个而非 16 个**——`_router/_schema` 是 Pydantic 模型集合不是路由。完整事实见 [App 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/App.md)。

### Hub Subsystem: Registry as Assembly

Agent Service 不直接 hardcode MCP server 或 skill 的来源，而是把它们抽象成 **Hub**——一个「从远端注册中心发现并装载」的抽象（`app/hub/_base.py`）。v2.0.8 含两类：

- **MCPHubBase** —— 发现并装载 MCP server；首实现 `GitHubHub`（`hub/_mcp/_github_hub.py`），从 GitHub 上的 MCP 注册中心拉取 server 清单并装载。
- **SkillHubBase** —— 发现并装载 skill；首实现 `ClawHub`（`hub/_skill/_claw_hub.py`）。

`hub_id` 受 `HUB_ID_PATTERN = [a-zA-Z0-9_-]+` 约束，`create_app` 的 `_index_hubs` 按 id 建索引，重复 id 直接 `ValueError`——同一 kind 的 hub 必须 id 唯一，否则路由无法唯一定址。`hub` router 把「发现 / 装载 / 列出」能力暴露成 HTTP 端点。完整事实（生命周期、索引、与 workspace 网关的关系）见 [App 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/App.md)。

## Comparison

### AgentScope vs LangChain / LangGraph

AgentScope 属于和 LangChain 同层的 Framework，但架构选择不同：

| 维度 | AgentScope | LangChain |
| :--- | :--- | :--- |
| Agent 设计 | 单一 `Agent` 类，内置全部能力 | BaseAgent 继承体系，ReActAgent / PlanExecuteAgent 等 |
| 中间件 | 7 hook 自动检测，onion + transformer 双通道 | Callback 机制（on_chain_start / on_tool_start 等），不区分 hook 位置 |
| 权限 | 核心组件，5 种 mode + 三级规则 + safety ASK | 无内置权限层，靠自定义 chain |
| 事件驱动 | 原生 AgentEvent 流式输出，ReplyStart → ReplyEnd 完整生命周期 | Callback 体系 + streaming 分开 |
| 上下文压缩 | 内置结构化压缩 + runtime injection + 主动 CompressContext 工具 | 需要自己实现 Memory 类（ConversationSummaryMemory 等） |
| 服务化 | 内置 FastAPI + Web UI + 多租户 | 无，靠自研或 LangSmith |

AgentScope 的选择是**把 Harness 层的能力直接做进 Framework 核心**——权限、压缩、运行时状态注入、offloader 都是 `Agent` 类的内置机制，不需要额外组件。这和本库 [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) 里说的「Runtime / Framework / Harness 三层」对照来看，AgentScope v2.0 实际上是**把 Framework 和 Harness 两层合并了**，而把 Runtime（图式状态、持久化、人工协作断点恢复）留给 Pipeline 和 Agent Service 层补全。

### AgentScope vs Coding Agents

和 [Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md)、[Codex](/docs/CS/AI/LLM/Agent/Product/Codex/Codex.md)、[DSH](/docs/CS/AI/LLM/Agent/Product/DSH/DSH.md) 这些编程 Agent 比，AgentScope 的定位更基础——它不预设"用户是开发者、Agent 写代码"这种场景，而是提供一个可以包装任意模型、接入任意工具、通过中间件扩展行为的通用框架。编码场景只是其中一个 Toolkit（Bash / Grep / Read / Write / Edit）。

反过来说，如果要在 AgentScope 上搭一个 Coding Agent，需要自己加 Shell 执行环境（Bubblewrap / Daytona）、文件系统权限模型、PTY 支持这些东西——这些在 Claude Code / Codex 里是 Harness 内置的。AgentScope 给的是脚手架，不是成品。

## Component Design Analysis

上一节讲"有什么"，这一节讲"为什么这样设计"。每个组件都从**设计动机 → 取舍 → 关键实现细节**三个角度展开。

### Runtime Component Interaction: One ReAct Iteration

先给一张图，把一轮 ReAct 循环里所有组件怎么交互画出来。对照这张图读后文的组件分析最清晰：

```
  UserMsg ──→ Agent.reply(inputs)
                   │
                   ▼
          [middleware: on_reply chain]
                   │
          ┌────────▼────────┐
          │  _reply_impl()   │ ◀─── AgentState.reply_context 初始化
          │  ReAct 主循环    │
          └────────┬────────┘
                   │
    ┌─── cur_iter < max_iters? ───┐
    │  │                          │
    ▼  │  yes                     ▼ no
 Exit  │                  EXCEED_MAX_ITERS
    │  │                          │
    ▼  │  Reasoning path          ▼
    │  ├── compress_context()     │
    │  │     │                    │
    │  │     └── _limit_context_images()
    │  │     └── 计数 tokens
    │  │     └── LLM 生成 summary (structured_output)
    │  │     └── state.summary / state.context 替换
    │  │                          │
    │  ├── _inject_runtime_state()│
    │  │     │                    │
    │  │     └── HintBlock 追加到 state.context
    │  │     └── yield HintBlockEvent
    │  │                          │
    │  ├── _reasoning()           │
    │  │     │                    │
    │  │     ├── [mw: on_reasoning]
    │  │     ├── _prepare_model_input()
    │  │     │     ├── system prompt + on_system_prompt chain
    │  │     │     ├── state.context 全部 Msg
    │  │     │     └── toolkit.get_tool_schemas() (activated_groups)
    │  │     ├── ChatModelBase() ──── model._call_api()
    │  │     │     │                    ├── retry loop
    │  │     │     │                    └── _StreamAccumulator
    │  │     │     └── yield 各类 Block Event + ModelCallEndEvent
    │  │     └── _save_to_context() ──── state.context append AssistantMsg
    │  │                          │
    │  └── ToolCallBlock 返回? ─┐ │
    │         │                  │ │
    │      无 ─┤                  │ │
    │         │  纯文本回复       │ │
    │         ▼                  │ │
    │   生成 final AssistantMsg ──┤ │
    │         │                  │ │
    │         ▼                  │ │
    │   ReplyEndEvent ──── Exit  │ │
    │                              │ │
    │  Acting path                 │ │
    │  ├── _batch_tool_calls()    │ │
    │  │     │                    │ │
    │  │     └── is_concurrency_safe → concurrent / sequential batch
    │  │                          │ │
    │  └── _execute_tool_call()   │ │
    │        │                    │ │
    │        ├── toolkit.check_tool_available()
    │        ├── _json_loads_with_repair + jsonschema.validate
    │        ├── _check_permission()
    │        │     │              │ │
    │        │     ├── [mw: on_check_permission]
    │        │     └── PermissionEngine.check_permission()
    │        │           │        │ │
    │        │           └── mode 分发 (_check_default / _check_explore / ...)
    │        │               └── deny → ask → readonly → tool.rule → allow → default
    │        │                    │
    │        │              ASK? ─┼─── yield REQUIRE_USER_CONFIRM, loop park
    │        │               │          下次 reply(UserConfirmResultEvent) 恢复
    │        │            ALLOW ──┤
    │        │                    │
    │        ├── _acting()        │ │
    │        │     │              │ │
    │        │     ├── [mw: on_acting]  ← 只包 toolkit.call_tool()
    │        │     │     │        │ │
    │        │     │     └── Tool.__call__() ← ToolMiddlewareBase 洋葱
    │        │     │           │  │ │
    │        │     │           └── Tool.call()
    │        │     │              │ │
    │        │     └── yield ToolResult events
    │        │                    │ │
    │        └── ToolResultBlock 写入 state.context
    │                               │
    └─────────── loop back to cur_iter++ ────┘
```

这张图里可以看到几个核心事实：
- **AgentState 是所有组件的共享数据总线**——context、summary、reply_context、permission_context、tool_context、tasks_context、middle_context 七块数据，被 Agent / PermissionEngine / Toolkit / 所有 Middleware 共同读写
- **中间件在六个不同层级切入**——on_reply 包整个循环、on_reasoning 包模型调用、on_model_call 包底层 API、on_check_permission 包权限判定、on_acting 包工具执行（只包纯 I/O 层）、on_compress_context 包压缩
- **HITL 暂停是轻量的**——yield `RequireUserConfirmEvent` 后直接停在 `_reply_impl` 的 await 点，没有任何 cleanup 或状态保存；下次回来同一条 Agent 实例、同一个 state、循环从断点继续

### AgentState: The Unifying Data Container

`AgentState` 是一个**纯 Pydantic BaseModel**，六个字段全部是子 context：

```python
class AgentState(BaseModel):
    session_id: str                              # 会话级标识
    summary: str | list[TextBlock | DataBlock]   # 压缩后的摘要
    context: list[Msg]                           # 未压缩的对话上下文
    reply_context: ReplyContext                  # 当前 reply 的 reply_id / cur_iter / structured_schema
    permission_context: PermissionContext       # 权限规则 + mode
    tool_context: ToolContext                    # 文件缓存 + activated tool groups
    tasks_context: TaskContext                  # Plan 模式的任务列表
    middle_context: dict[str, Any]               # 中间件跨回复状态
```

**设计动机**：把所有需要跨回复、跨 HITL 断点保留的状态，装进一个可序列化的模型，而不是散落在 Agent 实例的各个属性里。AgentScope 的 FastAPI 服务需要把 Agent 持久化到 SQL（会话暂停、进程重启后恢复），一个 BaseModel 直接 `.model_dump()` + Alembic migration 就搞定了。

**关键取舍**：
- **不是分离的 Store/Repository**——AgentScope 没有 `ContextStore` / `PermissionStore` 这类类，六个子 context 就是直接嵌在一个模型里。好处是引用透明（`state.context`、`state.permission_context`），坏处是 state 对象会越来越大；但 AgentScope 的压缩机制（`trigger_ratio=0.8` 就动手）和 tool result truncation（`tool_result_limit=50000`）就是为了限制 state 的体量
- **middle_context 的 key 设计**——每个 middleware 实例用 `get_middleware_key()`（默认类名）注册自己的状态，budget middleware 在里面存 per-reply 的 token 计数。同一个 middleware 实例可以安全地被多个 Agent 共享（因为状态全在 state 里，不在实例里）
- **read_file_cache 的 LRU**——`ToolContext.read_file_cache` 是一个 list，文件工具重复读同一个文件时先查 cache（按 mtime 判过期），修改后 `_clear_unreserved_read_cache()` 只清压缩掉的路径。这个 cache 减少了模型决策后再次 `Read` 同一个文件的开销——典型场景是 Agent 读完 main.py → 让模型推理 → 又要读 main.py 的某行

### Dual Middleware: Agent-Level + Tool-Level

AgentScope 有两层独立的中间件系统，这不是巧合：

| 维度 | Agent 层 `MiddlewareBase` | Tool 层 `ToolMiddlewareBase` |
| :--- | :--- | :--- |
| 注册位置 | `Agent(middlewares=[...])` | `Tool(middlewares=[...])` |
| 洋葱层数 | 6 个 onion hook + 1 个 transformer | 仅 1 个 hook `on_tool_call` |
| `next_handler` 返回值 | AsyncGenerator（流事件） | AsyncGenerator[ToolChunk]（流 chunk） |
| 能访问什么 | `agent`（含 state）、`input_kwargs` | `tool`、`input_kwargs` |
| 状态存储 | `agent.state.middle_context` | 无内置约定 |
| 能否 offload 到后台 | 只有 `on_acting` 可以（因为只包纯 I/O 层） | 可以（Tool.call 本身就是 async generator） |

**设计动机**：两层中间件解决两个不同粒度的问题。Agent 层中间件处理"整个 Agent 的行为"——预算控制、RAG 注入、Tracing 观测——需要跨多轮 reasoning-acting 循环，需要能读/写 agent state。Tool 层中间件处理"单个工具的执行"——日志、重试、输出格式转换——粒度更细，而且 tool 可能被 Agent 层的 `Toolkit.call_tool()` 直接调到（甚至可能绕开 Agent 层中间件）。

**关键取舍**：
- **Tool 层中间件是 Tool 自己的属性**——这意味着同一个 `Bash` 工具实例共享它的中间件链。如果两个 Agent 共享同一个 Toolkit 里的 Bash 实例，它们也共享 Bash 的 middleware。AgentScope 默认让每个 Agent 构造自己的 Toolkit，所以这不是问题，但在多 Agent 协作场景（Agent Service 的 TeamCreate）里需要注意
- **`__call__` 始终返回 AsyncGenerator**——Tool.call 可以是 coroutine、asyncgen 或 sync gen，但 `__call__` 统一包装成 asyncgen 返回。这样 ToolMiddlewareBase 永远只和一种返回类型打交道，不需要处理多态

### Toolkit: Unified Registration + Dynamic Activation

`Toolkit` 把 Python 工具、MCP 工具、Skill 三件事**统一成 ToolBase 对象**，再挂进 `ToolGroup` 分组。这背后的设计是：

**动态工具集**：AgentScope 内置了两个 meta tool——`ResetTools`（激活/停用 tool group）和 `SkillViewer`（列出可用 Skill）。Agent 自己可以调这两个工具来动态改变它看到的工具集：

```python
class ResetTools(ToolBase):
    # input schema 动态生成——根据已注册的 tool_groups 决定哪些 group 可切
    # 执行时修改 Toolkit.activated_groups
    # 返回值被包装成 Jinja2 模板渲染的文本（激活了哪些 group、各 group 的 instructions）
```

这个设计让 Agent 可以**在运行时决定自己看到什么工具**——编码任务激活 bash/file tool group，调研任务激活 web/search group，而不是在构造 Agent 时一次性定死。

**MCP / Skill / Python 的统一入口**：
- MCP Client 在构造 Toolkit 时 list_tools()，返回的每个 tool 都被包装成 `ToolBase`（带 `is_mcp=True` + `mcp_name`）
- Skill 是纯 Markdown 文件夹，不是 Tool——Toolkit 把 Skill 的 description 收集起来，通过 `skill_instruction_template`（Jinja2）生成一段 prompt 注入到 system prompt，同时暴露 `SkillViewer` 让 Agent 主动读 skill 内容
- Python 工具直接继承 `ToolBase`，或用 `FunctionTool(func)` 包装一个 Python 函数

三种来源最后统一成 `Toolkit._get_available_tools()` 返回的 `dict[name, RegisteredTool]`——模型拿到的永远是同一套 JSON schema，不管工具是 MCP server 来的还是本地 Python 函数。

**一个 MCP 工具挂了不会拖垮整个 reply**：`Toolkit._get_available_tools()` 在注册 MCP client 的 tools 时，如果 `client.list_tools()` 抛异常，只是 `logger.warning` 然后跳过这个 client，**不会让整个 reply 崩溃**。设计动机在源码注释里写得很直白："一个过期 token 或宕机的 MCP server 不应该终止整个对话"。

### Event System: Why Typed Events Instead of Callbacks

AgentScope 的输出是 `AsyncGenerator[AgentEvent | Msg]`，每种事件都是带 type 标识的 Pydantic 模型（`EventType` 是 `StrEnum`）。这套设计和 LangChain 的 Callback 体系的核心差异：

| 维度 | AgentScope AgentEvent | LangChain Callback |
| :--- | :--- | :--- |
| 传输方式 | async generator yield | 同步 hook 调用 |
| 消费者 | 单一（上游），事件是串行流 | 多个 observer，回调可能乱序 |
| 与 Msg 重建 | `Msg.append_event()` 按 reply_id 归并 | 无原生重建 |
| HITL 协议 | `RequireUserConfirmEvent` + `UserConfirmResultEvent` 形成对 | 需要自定义 callback handler + Agent 状态管理 |

**设计动机**：AgentScope 的事件系统承担了两件事——① 流式输出给前端（Web UI、Console）；② HITL 暂停/恢复协议。`ReplyStartEvent` 和 `ReplyEndEvent` 成对出现，中间的所有事件都带 `reply_id`，让 `Msg.append_event()` 能把整个事件流重建回一条完整的 Msg。这个重建能力是 HITL 恢复的基础——前端可以把一个被暂停的事件流完整存下来，恢复时直接 replay 就能拿到同一条 Msg。

**`_receive_reply_end` 的反直觉设计**：Agent 层 middleware 的 `on_reply` 可以**故意吞掉** `ReplyEndEvent`（收到但不 yield），强制让 ReAct 循环多跑一轮。但这不是无限的——Agent 内部跟踪一个 `_receive_reply_end` flag 和 `made_progress` flag：如果 middleware 连续两次吞掉 ReplyEndEvent 且中间没有 reasoning/acting（即 cur_iter 没有增长、没有任何工具调用），会抛 RuntimeError。这个防套娃的逻辑写在 `_reply_impl` 的 Exit 分支里，是 AgentScope 少有的内置安全网。

### Agent + Four Config Objects

`Agent` 构造函数接收四个 Pydantic Config（`ModelConfig` / `ContextConfig` / `ReActConfig` / `InjectionConfig`），而不是一堆参数。这个设计带来三件事：

1. **自动校验**——`ContextConfig` 的 `trigger_ratio` 必须 > `reserve_ratio` 且 <= 0.9，`InjectionConfig.template` 必须包含 `{runtime_state}` 占位符。Pydantic validator 在构造时就挡住不合法配置
2. **可序列化**——四个 Config 加 `AgentState` 一起 `.model_dump()` 就是一份完整的 Agent 快照，方便持久化和恢复
3. **Config 组合而非继承**——LangChain 体系常见"子类覆盖一个 config 再继承另一个"，AgentScope 用组合，四个 Config 之间通过 `_validate_configs()` 检查跨对象不变量（比如 `injection_config.context_buffer_ratio` 已 deprecated，移到 `context_config`）

### Pipeline's Interface Segregation

`PipelineProtocol` 只有一个方法——`reply_stream()`，签名和 `Agent.reply_stream()` **完全相同**。这意味着 GoalPipeline（executor + verifier 循环）可以无缝替换 Agent 传给上游，Team Pipeline（leader 委派 worker）也一样。

这不是巧合——AgentScope 设计 Agent 和 Pipeline 时就把它们放在同一个抽象层：都是能"输入 Msg/Event、输出事件流"的东西。区别只是：Agent 内部是一次 ReAct 循环，Pipeline 内部是多次 Agent 调用的编排。

### GoalPipeline: The Executor-Verifier Pattern

`GoalPipeline` 的核心逻辑：

```python
async for event in executor.reply_stream(goal):
    yield event
    if isinstance(event, Msg) and event.id == executor.state.reply_id:
        executor_report = event
        break

verifier_input = UserMsg(name="user", content=[goal, executor_report])
verifier_result = await verifier.reply(verifier_input, structured_schema=_VerificationResult)

if verifier_result.structured_output.result == "pass":
    # Goal achieved
    yield ReplyEndEvent(...)
    break
elif verifier_result.structured_output.result == "impossible":
    # Goal impossible, stop
    yield ReplyEndEvent(finished_reason=ExceedMaxIters)
    break
else:
    # Fail with feedback → executor 下一轮
    pass
```

三个设计点值得单独记：
- **verifier_reset_context**——默认 True，每轮 verifier 从零开始，不累积上下文。动机是"让 verifier 每次只看 executor 的报告，不被之前轮次的历史影响"
- **_iters 存在实例上而非 reply_context 里**——HITL 恢复时，reply_context 会重建，但 GoalPipeline 实例的 `_iters` 不变。设计动机是"budget 不应该因为 HITL 恢复而重置"
- **impossible 结果**——三值枚举（pass / fail / impossible），impossible 让 executor 停止尝试而不是继续重试。这是比大多数 Agent 框架更精细的终止条件控制

### Service Layer: Multi-Tenant Agent Runtime

Core Agent 层是 AgentScope 的大脑，但它假设"Agent 实例存在、输入消息有人喂、状态有人存"。Service 层（`agentscope/app/`）补上这三块——把 `Agent` 包装成一个可以被多用户、多会话、多进程并发调用的在线服务。这一层的设计模式和 Core Agent 层完全不同，因为它解决的是分布式系统问题，不是推理问题。

#### MessageBus: Six Primitives Instead of Domain-Specific APIs

`MessageBus` 是整个 Service 层的神经中枢。AgentScope 没有定义 `InboxQueue` / `EventLog` / `WakeupSignal` 这类领域对象，而是把协调需求收敛成**六种消费语义原语**，每个原语对应一种数据生命周期：

| 原语模式 | 语义 | 典型用途 |
| :--- | :--- | :--- |
| **Mode A — drain queue** | 单一消费者、ack-on-read。每条 entry 被一个读者拿走后立即删除 | wakeup trigger queue、session inbox（HintBlock 投递） |
| **Mode C — replay log** | 多消费者、非破坏性读取、`max_len` 或 TTL 限长 | session event log（SSE late-join 补历史） |
| **Mode D — transient broadcast** | fire-and-forget，只有实时订阅者能收到 | wakeup signal、cancel broadcast、schedule lifecycle notify |
| **Mode E — distributed lock** | 集群级互斥，带心跳续租防止进程崩溃死锁 | session run 锁（同一 session 同时只有一个 ChatService.run 在跑） |
| **Mode F — registry map** | hash-keyed namespace，支持 CAS（compare-and-set）和 pop-exactly-once | background task 全局注册表、channel liveness 心跳 |

**设计动机**：把业务语义与传输层解耦。Service 层上层代码只管选原语 + 定义 key 命名约定（`MessageBusKeys` 静态类集中管理所有 key 格式），底层可以换成 Redis / NATS / InMemory 而不触动业务代码。`_base.py` 里那句"Counted broadcast is intentionally not exposed"尤其说明问题——想 fan-out 给 N 个成员？写时 fan-out（每个收件人 inbox push 一条 Mode A），不要让总线维护 consumer group 协调状态。总线保持简单，复杂性留给生产者。

**Mode C 的 replay-then-live 模式**是事件流 gap-free 读取的基础。`open_reply_stream()` 的两阶段读取——先 `log_read(max_count=SESSION_REPLAY_MAX_LEN)` 把最近 1000 条历史拉回来，再进入 `subscribe` 实时模式，用 entry_id 做去重——让消费者可以在 Agent 已经在跑之后才订阅（SSE endpoint 的典型场景），而不会错过任何事件。

#### Deployment Mode: Three Role-Separation Switches

`create_app()` 有三个布尔开关，把 Service 层拆成四种可独立部署的角色：

| 开关 | 关闭后谁接管 | 典型部署 |
| :--- | :--- | :--- |
| `enable_channel_worker=False` | 独立 channel worker 进程 | 每平台一个 bot 长连接，API 副本变成纯无状态 |
| `enable_scheduler=False` | 独立 scheduler owner 节点 | 单 owner 跑 APScheduler（jobstore 内存），其余节点只写 storage |
| `enable_index_worker=False` | 独立 index worker 进程 | API 副本只发布 index task，worker 进程消费并调 Milvus/ES |

**设计动机**：APScheduler 的 jobstore 是内存的——每个持有它的节点都会在 cron tick 时触发任务，多副本部署必然重复执行。Channel 长连接同理——飞书/DingTalk 一个 bot token 只能有一个活跃 WebSocket，每个 API 副本都持有连接要么浪费要么重复。把长连接、定时器、重活从 API 路径剥离出去，API 副本就可以纯粹水平扩展。

**一个值得注意的设计取舍**：三个开关关闭后，对应的 API 端点**仍然可用**——只是它们不做长连接、不持有定时器、不跑索引循环。API 层写 storage → 发 message_bus signal → owner 节点收到 signal 后 reconcile 自己的本地状态。这个 reconcile 模式（`ChannelLifecycleDispatcher.reconcile()` / `SchedulerManager.reconcile()` / IndexSweeper）统一了所有 owner 的状态同步机制。

#### WakeupDispatcher: Single Serial Consumer Per Process

每个进程只有一个 `WakeupDispatcher` asyncio task 消费全局 `wakeup_queue`。这不是效率选择（一条 64 条的 queue 用不上并发），而是**结构性保证**——从消息队列 drain 出来的 trigger 是串行处理的，每个 trigger 在 spawn ChatService.run 之前先 `is_locked(session_lock)` 检查 session 是否在跑，冲突时 backoff 0.1s 重入队。

这种设计让分布式 session 串行化**几乎没有竞争**：
- 正常流程：前一个 run 结束 → 释放 session lock → WakeupDispatcher 下一次 drain 看到 trigger → `try_lock` 成功 → spawn
- 竞态场景：trigger 入队时前一个 run 还没释放 lock → `is_locked` 返回 True → re-enqueue（不会丢）→ 下次 drain 再试

代码注释里写得直白："every run trigger funnels through this one serial consumer, which is what makes concurrent-spawn races structurally impossible"。分布式 lock 是保险，串行消费让锁几乎不会被竞态。

#### Channel Subsystem: Gateway (Data Plane) + Dispatcher (Control Plane) Split

Channel 子系统分成两个完全独立的组件：

**ChannelGateway（data plane，无状态）**：
- `process(event)` 是唯一入口，接收入站消息或确认卡片点击
- 消息路径：`resolve()` 路由 → `is_locked(session_lock)` 判定 → 活跃 session 写 inbox（HintBlock）/ 空闲 session enqueue wakeup
- 确认点击路径：`_resume()` 读 session state 找等待中的 tool_call → 恢复 parked run

**ChannelLifecycleDispatcher（control plane，持有长连接）**：
- 每进程一个，`_instances: dict[channel_id, ChannelInstance]` 持有所有本地长连接
- 两个 loop：`_listen()`（订阅 lifecycle 事件 reconcile）+ `_periodic()`（10s reconcile + heartbeat）
- reconcile 驱动 `_instances` 和 storage 里 enabled records 保持一致

**输出方向完全反向**：Agent 跑完后，事件直接发 message_bus；持有该 channel 长连接的 Dispatcher 通过 `open_reply_stream()` 订阅 session events → 调 channel client 发送 REST。Gateway 只入站，Dispatcher 只持有连接；两者通过 message_bus + storage 间接协作，没有直接调用。

#### Deterministic Channel Routing: uuid5 Session IDs

最精妙的一个设计：**Channel 路由不需要持久化映射表**。给定入站消息，`resolve()` 纯函数算出 `session_id`：

```python
_SESSION_NAMESPACE = uuid5(NAMESPACE_URL, "agentscope.channel.session")

session_id = uuid5(
    _SESSION_NAMESPACE,
    f"{record.id}:{binding.agent_id}:{scope_key}",
)
```

其中 `scope_key` 由 `SessionScope` 决定——`PER_CHAT` 是 chat_id，`PER_CHAT_USER` 是 `chat_id:user_id`。

**这个设计的后果**：
1. **多节点零协调**——任何节点收到同一条消息都会算出同一个 session_id，不需要路由查询
2. **幂等 session 创建**——`ChannelGateway._ensure_session()` 调 `storage.get_session(..., session_id)` 查存在不，不存在才 upsert；同一个 session_id 永远对应同一个 Agent + 同一个 scope
3. **删除安全**——session 被删后，下次同 chat 同 scope 的消息自动重新创建（UUID 稳定，不会 orphan 旧 session）

没有 Redis 映射表，没有 CRDT，没有中心路由服务——一个 uuid5 解决了分布式路由的核心问题。

#### Lifespan Pattern: AsyncExitStack with Reverse-Order Cleanup

整个 Service 层的资源生命周期由 `lifespan()` 中的一个 `AsyncExitStack` 统一管理。`storage → message_bus → workspace_manager → knowledge_base_manager → BlobStore → Hubs → BackgroundTaskManager → ChatRunRegistry → SchedulerManager → channel subsystem → ChatService → SessionService → WakeupDispatcher → CancelDispatcher → ChannelLifecycleDispatcher` 这串 enter 顺序，退出时按**逆序**关闭。

这个设计有两个好处：
1. **部分启动失败不会泄漏资源**——中间某个 `enter_async_context` 抛异常，AsyncExitStack 会自动关闭之前已经 enter 的所有资源
2. **依赖顺序自动正确**——`ChatRunRegistry` 必须在 `WakeupDispatcher` 之前 enter（Dispatcher 依赖 Registry spawn task），而 shutdown 时 Registry 在 Dispatcher 之后退出（Dispatcher 先停收 trigger，再 cancel 所有还在跑的 chat run）。代码里的 enter 顺序就是依赖图的拓扑排序，不需要额外文档

#### Summary: How Service Layer and Core Agent Layer Connect

两层之间的接口极其简单：Service 层不继承 Agent、不包装 Agent、甚至不 import Agent 的内部方法。唯一的接触点是：

1. **运行时装配**：`ChatService._run_impl()` 每次调用时从 storage 读 AgentRecord + SessionRecord → 组装 `Agent` 实例（模型、Toolkit、中间件链都来自 storage 配置 + workspace 派生）
2. **State 传递**：`AgentState` 在 Agent 构造时从 session 的持久化 state 加载；run 结束后写回 storage。Agent 本身不持久化，纯函数式
3. **Event 管道**：Agent 产出的事件流同时发布到 Mode C replay log（持久化）和 Mode D live broadcast（实时订阅），Service 层不拦截也不修改

这个边界设计意味着：Core Agent 层可以独立演进（比如加一个新的 middleware hook、换一种压缩算法），只要不破坏 `Agent.reply_stream()` 和 `AgentState` 的结构，Service 层不需要改一行代码。

## Version Delta: v2.0.8 → v2.0.10

本章记的内容超出 v2.0.8——本地树上另有 `v2.0.9`（9 月中旬）和 `v2.0.10`（2026-10-12）两个 tag。这两个版本加的东西不只是补丁，**出现了三个新子系统**，值得单独看，因为它们能说明这个项目在往哪走。

### SOP: Stored Procedures For Agent Workflows

新增的 `sop/` 包是最大的一块。源码给的类比很直白——`app/_service/_sop.py` 首句写着「Running a **stored procedure**, one ChatService turn per step half」，把流程定义类比数据库的存储过程：**定义是代码，可以跑无数次；运行实例是纯数据，属于某一次具体的执行**。

数据模型：

- `SOPPhase` —— `PENDING / RUNNING / AWAITING / COMPLETED / FAILED`，**一个 step 和整个 run 共用同一套枚举**（「a run is only ever as far along as its steps let it be」）。`AWAITING` 就是 parked 状态——有人在外部回答之前它不会前进，这和 Agent 的 HITL 是同一套世界观
- `VerificationResult` —— `passed` + `message`（说明缺什么而不是说「不对」）+ `verifier`（模型 / 人 / 外部系统都可以是裁判）。注释强调只记录**已定论**的裁决，没发生过的裁决不算裁决
- `SOPStepRunState` —— `model_config = ConfigDict(extra="allow")`，允许子类加字段且能穿过 storage 往返

`SOPStepBase` 的契约只有一条：**一次 `reply_stream()` 调用算一次尝试**，要么 parked 要么在 state 上留下裁决。`max_attempts=3` 由引擎执行而非步骤自查。

最有意思的是 `app/middleware/_sop_step_middleware.py`——它解决的是「Agent 忘了交卷怎么办」：

> A reply-end with nothing submitted is **swallowed with a nudge**, and failed after `max_nudges` so it costs an attempt instead of hanging.

也就是复用前面说的「吞掉 `ReplyEndEvent`」能力，但这里不是为了漫无目的地让 ReAct 多跑一轮，而是带着明确目标——必须调用 `SubmitHandover` 或 `SubmitVerdict` 才算结束。`SubmitHandover` 的参数说明也写得很有实践感：

> 后面的步骤看不到这段对话和你的工具输出，所以任何他们需要的东西都必须写在这里。唯一例外是共享 workspace 时的文件——说路径，别描述内容。

这实际上是**用中间件约束替代 prompt 恳求**。对比本库 [Skill](/docs/CS/AI/LLM/Agent/Theory/Skill.md) 里说的 soft instruction，SOP 走的是硬约束路线。

### Classifier and Model Router

`classifier/` 包加了一个新抽象：`ClassifierModelBase`——「返回**带类型的概率化决策**」的模型，输入是共享 state + 一批具名 question，输出 `ClassifierResponse`。目前两家实现：OpenAI 与 jev。

配套的 `middleware/_model_router.py`（`ModelRouterMiddleware`）把它接进了 Agent：**每个 reply 用分类器挑一个 chat model**。`on_reply` hook 里临时把 `agent.model` 换成选中的候选，路由 **once per reply 且 HITL 恢复后保持不变**；分类失败或选到未知候选时保持 Agent 自己的模型。

这是把以往放在 A2A 网关或应用层做的「大小模型分流」下沉到了单个 Agent 内部。

### AskUser Tool and External Execution Contract

`tool/_builtin/_ask_user.py` 是 v2.0.8 完全没有的新内置工具：`is_external_tool=True`、`is_read_only=True`、1–4 题每题 2–4 选项，`check_permissions` 恒 ALLOW。

它暴露的是前面 Tool System 那节提到的那个缺口——`ToolBase` 以前只有 `input_schema`（告诉模型怎么调），没有「外部执行方必须回填什么」的契约。v2.0.10 补上了另一半：`metadata_schema` + `check_external_result()`，用 jsonschema 校验回填的 metadata，不合规的结果会被 parked 且允许重发。

外部工具的行为本身就值得一记：Agent 把状态置 `SUBMITTED` 后 yield `RequireExternalExecutionEvent` 并**立即 return**，本轮推理到此中断；外部系统填完再把 `ExternalExecutionResultEvent` 灌回来。这就是 AgentScope 版的「工具调用可以跨进程、跨人、跨天」。

### TUI: Terminal Is A First-Class Client

`src/agentscope/tui/`（v2.0.10 新增，基于 **Textual**，`agentscope[tui]` extra）把终端提升为一等客户端。这不是 demo：

- `launch_tui(agent)` —— 每次提交起一个 `reply_stream()`，用 `_reply_lock` 串行化避免并发回复改坏同一上下文
- `launch_realtime_ui(agent, transport)` —— `on_mount` 起**单个** `reply_stream(transport)` 跑满整个会话；文本输入是否可用取决于 `agent.model.supports_text_input`
- **HITL 在终端里的四个选项**：`allow` / `always`（仅在 `suggested_rules` 非空时出现，标签形如 `Always allow with {tool_name} {rule_content}`）/ `deny` / `interrupt`；`Ctrl+C` 中断
- 事件到 widget 的渲染是全增量的（`replace(block)` / `apply(message)`），不是整体重绘

值得注意的是它和 Agent 层**完全解耦**——TUI 里的 `_publish()` 只用 `Msg.append_event()` 按 reply_id 归并，这一节前面设计的事件重建能力在这里收到了回报。

### Smaller Deltas

- **`pipeline/_team_pipeline.py`** —— Team Pipeline 独立成文件（Leader 委派 Worker）
- **Realtime 厂商扩到四家** —— 新增 Gemini / OpenAI / xAI 适配器 + WebRTC transport（`app/_service/_webrtc_*`）；注意 Gemini 和 OpenAI 有能力差异仍在靠 `TruncationSupport` 枚举吸收
- **`model/_minimax/`** + `formatter/_minimax_formatter.py` + `credential/_minimax.py` —— 新增 MiniMax 厂商，完整地补齐了 model / formatter / credential 三层（这也是观察这套分层的好例子：每加一家厂商要动三个地方）
- **`credential/_typesafe.py`** —— 新增
- **`realtime` extra 拆分** —— 从 `["websockets>=13", "sounddevice"]` 拆成 `realtime` + `realtime-local`，前者不再逼着装 PortAudio


## Links

- [Agent 目录](/docs/CS/AI/LLM/Agent/README.md)
- [AgentScopeJava](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/AgentScopeJava.md) / [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md) / [Pi](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md) / [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md)
- [LLM 应用开发框架](/docs/CS/AI/LangTools.md)
- [Agent Theory](/docs/CS/AI/LLM/Agent/Theory/Agent.md) / [Permission](/docs/CS/AI/LLM/Agent/Theory/Permission.md) / [Compaction](/docs/CS/AI/LLM/Agent/Theory/Compaction.md)

## References

- [AgentScope GitHub](https://github.com/agentscope-ai/agentscope)
- [AgentScope 文档](https://docs.agentscope.io/)
- [AgentScope: A Flexible yet Robust Multi-Agent Platform (arxiv 2402.14034)](https://arxiv.org/abs/2402.14034)
- [AgentScope 1.0: A Developer-Centric Framework for Building Agentic Applications (arxiv 2508.16279)](https://arxiv.org/abs/2508.16279)
