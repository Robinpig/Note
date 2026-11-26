## Introduction

AgentScope 是阿里巴巴开源的 Python Agent 框架，从 v2.0 开始面向生产场景。核心设计目标是「充分发挥大模型的推理与工具调用能力，而非用严格的提示词和固化的编排方式来束缚它们」——这句话来自官方 README，也是理解它架构选择的钥匙。

这个定位把 AgentScope 放在了 Framework 与 Harness 之间：它提供 LangChain 级别的跨厂商抽象，又把权限、上下文压缩、运行时状态注入这些通常由 Harness 层处理的能力直接做进了核心 Agent 类。再往上，它还附带一套开箱即用的 Agent Service（FastAPI 后端 + 预构建 Web UI），把单个 Agent 包装成多租户、多会话的在线服务。

> 版本基线：v2.0.11（2026-10-27 发布的最新正式版，tag `v2.0.11`；`src/agentscope/_version.py` 为 `__version__ = "2.0.11"`）

```python
# src/agentscope/_version.py
__version__ = "2.0.11"
```

本笔记采用「枢纽 + 分册」结构：主干保留架构叙事与跨模块分析，十二个专题分册统一放在 `AgentScope/` 子目录，**全部按 v2.0.11 源码逐文件重核**。其中七册沿用 v2.0.8 时期的结构，五册是本次全量升级新增，专门承接 v2.0.9~v2.0.11 才出现的子系统。旧基线里被证伪的结论集中列在 [Corrections](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md?id=corrections-v208-baseline-to-v2011)。各分册由哪里接手、按什么顺序读，见下文 [How to Read the Subsystem Notes](#how-to-read-the-subsystem-notes)。

## Quickstart: From Zero to a Running Agent

这一节给一个**最小可运行**的纵向切片，把「装包 → 造模型 → 造 Agent → 跑对话 → 流式渲染 → 拿结构化结果」六个动作串起来。所有 API 取自 v2.0.11 的公开符号：`agentscope.agent.Agent` / `agentscope.model.*` / `agentscope.tool.Toolkit` / `agentscope.message.UserMsg` / `agentscope.console.launch_console` / `agentscope.event`。

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

十三个分册按「**装配 → 边界 → 编排 → 服务化 → 记忆 → 新版扩张**」六条线组织，大致对应上面三层表里的 Infrastructure 与 Service 两层，再加一层横跨短期/长期/服务层的记忆子系统，以及一层 v2.0.9 起长出来的新能力。只想把框架用起来的读者读完 Quickstart 与 Architecture Overview 即可；要改框架行为、或判断某个能力该不该自己补，按下面六条线找对应分册。

**装配线：一个 Agent 身上挂什么。**[Tool 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Tool.md) 讲工具体系——内置 14 个工具（含外部工具 `AskUser`）、全部委托 `BackendBase`，`ToolBase` 之下的三种实现（手写类 / `FunctionTool` / `MCPTool`）统一走中间件洋葱链，模型拿到的永远是同一套 JSON schema。[Middleware 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Middleware.md) 讲最值得细看的一层：`MiddlewareBase` 的 7 个 hook 与 `is_implemented()` 分派、内置中间件家族（预算 / TTS / 追踪 / 长期记忆三实现），以及权限 DSL 的完整细节（5 模式 × 4 行为、引擎 6 步判定、`bypass_immune` 安全 ASK）。[Model 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Model.md) 讲模型层——「统一 `Msg` 序列 → 厂商 JSON」的翻译为什么收拢在 formatter、11 个厂商子模块（10 家厂商）的卡片清单，以及 retry 包着的直通调用线。

**边界线：Agent 伸手能碰到什么。**[RAG 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/RAG.md) 讲自带的那套完整 RAG（`rag/`，纯算法层、可完全独立使用）：Parser → Section → Chunk → embed → VectorStore 的数据流、`Chunk` 比 `Section` 多出的两个字段为什么服务检索期，以及它与服务层托管版（`app/rag/knowledge_base_manager/`）的边界。

**编排线：一串 Agent 怎么跑。**[Pipeline 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Pipeline.md) 讲 AgentScope 的「事件织物」：`PipelineProtocol` 只暴露 `reply_stream()` 一个方法、强类型事件系统（`EventType` 28 值）、支撑类型（`ReplyFinishedReason` / `ErrorInfo` / Hook 类型），以及 `Msg` 的状态机式增量重建——尤其是 DataBlock 按 `block_id` 的分片合并。[Realtime 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Realtime.md) 讲另一个完全不继承 `Agent` 的类：双向语音会话、无 request/reply 边界，turn-taking 状态机夹在实时模型与 transport 之间。

**服务化线：怎么上线。**[App 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/App.md) 讲 v2.0.8 起成为正式包的 Agent Service：`create_app` 工厂与 v2.0.11 的 17 个路由、`lifespan` 的 AsyncExitStack 生命周期、Redis + 异步 SQLAlchemy 双存储后端、Hub 抽象、Workspace 隔离策略与跨 owner 资源访问策略。

**记忆线：什么被记住、存在哪、怎么回来。**[Memory 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Memory.md) 先拆穿一个直觉——框架里**没有一个叫 `Memory` 的类**，顶层也没有 `memory/` 包：短期层是 `AgentState.context` / `summary` 加五维结构化压缩与四维运行时注入，长期层是三套中间件各自的后端，服务化层是 `SessionRecord.state` 落 DB `payload`；workspace 的 `context.jsonl` 是**只写归档**，不是恢复路径。三套长期记忆中间件的逐文件事实仍归 Middleware 分册，这里负责讲清四层之间的边界与命名陷阱。

**新版扩张线：v2.0.9~v2.0.11 长出来的东西。**[AgentLoop 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentLoop.md) 把主循环、三动作状态机、事件重建与「两个五态枚举」按 3942 行的真源码重讲一遍，并记下 v2.0.11 新增的外部执行契约。[SOP 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/SOP.md) 讲存储过程式的流程硬约束：引擎状态机、两套提交路径、nudge 预算与 attempt 预算的分工。[Classifier 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Classifier.md) 讲概率化分类与 `ModelRouterMiddleware` 的逐 reply 选模。[VoiceStack 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/VoiceStack.md) 讲 ASR / TTS / Realtime 三栈、模型卡机制、WebRTC transport 与打包陷阱，RealtimeAgent 的 turn-taking 状态机仍归 [Realtime 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Realtime.md)。[TUI 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/TUI.md) 讲终端三类启动器、增量 widget 渲染与两套独立的 HITL 实现。读这五册之前建议先看 [Version Evolution](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md?id=version-evolution-v208-to-v2011)，那里逐 tag 标清了每个模块究竟是哪一版进来的。

## The Unified Agent Class

`Agent` 类（`agent/_agent.py`，v2.0.11 实为 **3942 行**；v2.0.8 已是 3908 行，旧笔记的「约 2500 行」从一开始就不准）是整个框架的心脏。但真正的 ReAct 主循环 `_reply_impl()` 只有 270 行，其余三千多行是事件转换、压缩、权限、HITL 与工具执行的辅助面。构造函数接收四大配置对象：

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

构造函数的真实签名（`agent/_agent.py`）里，四个 Config 与 `offloader` 都是可选参数：

```python
# agent/_agent.py
class Agent:
    """The agent class."""

    def __init__(
        self,
        name: str,
        system_prompt: str,
        model: ChatModelBase,
        toolkit: Toolkit | None = None,
        middlewares: list[MiddlewareBase] | None = None,
        state: AgentState | None = None,
        offloader: Offloader | None = None,
        # The agent configurations
        model_config: ModelConfig | None = None,
        context_config: ContextConfig | None = None,
        react_config: ReActConfig | None = None,
        injection_config: InjectionConfig | None = None,
    ) -> None:
```

四个 Config 是 Pydantic BaseModel，字段默认值覆盖了绝大多数场景。`_validate_configs()` 在构造时检查一个核心不变量：`reserve_ratio < trigger_ratio`、`context_buffer_ratio < trigger_ratio`——确保压缩阈值、缓冲区间距、保留区三者不重叠（`agent/_agent.py`）：

```python
# agent/_agent.py
    def _validate_configs(self) -> None:
        """Validate the config combinations that a single config class cannot
        check by itself.

        Raises:
            `ValueError`:
                If the reserved/buffer ratios don't leave room ahead of the
                context compression threshold.
        """
        if (
            self.context_config.reserve_ratio
            >= self.context_config.trigger_ratio
        ):
            raise ValueError(
                "The 'reserve_ratio' of the context config must be smaller "
                "than its 'trigger_ratio', got "
                f"{self.context_config.reserve_ratio} and "
                f"{self.context_config.trigger_ratio}.",
            )

        # The buffer is only consumed by the runtime state injection and
        # the compression tool, so it's checked only when one of them is on
        if (
            self.injection_config.inject_runtime_state
            or self.context_config.compression_tool_enabled
        ) and (
            self.context_config.context_buffer_ratio
            >= self.context_config.trigger_ratio
        ):
            raise ValueError(
                "The 'context_buffer_ratio' of the context config must be "
                "smaller than its 'trigger_ratio', so that the context "
                "length is injected and the compression tool takes effect "
                "before the hard compression, got "
                f"{self.context_config.context_buffer_ratio} and "
                f"{self.context_config.trigger_ratio}.",
            )
```

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

事件类型枚举（`EventType` 28 值，v2.0.8→v2.0.11 **零新增**）、`Msg.append_event` 状态机的完整清单见 [Pipeline 分册（事件与类型）](/docs/CS/AI/LLM/Agent/Product/AgentScope/Pipeline.md)。注意旧笔记记的「DataBlock base64 增量拼接陷阱」在 v2.0.11 应改称**分片合并规则**：decode → 拼接 → encode 在 v2.0.8 就已实现，v2.0.11 的精化是按 `event.block_id` 定位**同 id** 的 DataBlock，找不到就 append 新块，避免多个 DataBlock 并存于同一条 Msg 时串台（`message/_base.py`）：

```python
# message/_base.py
                    # Merge same-id Base64 chunks like
                    # ToolResponse.append_chunk.
                    merge_target: DataBlock | None = None
                    for output_block in block.output:
                        if (
                            isinstance(output_block, DataBlock)
                            and output_block.id == event.block_id
                            and isinstance(output_block.source, Base64Source)
                        ):
                            merge_target = output_block
                            break
                    if merge_target is not None and isinstance(
                        src,
                        Base64Source,
                    ):
                        existing = base64.b64decode(merge_target.source.data)
                        incoming = base64.b64decode(src.data)
                        merge_target.source.data = base64.b64encode(
                            existing + incoming,
                        ).decode("ascii")
                        merge_target.source.media_type = (
                            src.media_type or merge_target.source.media_type
                        )
                    else:
                        block.output.append(
                            DataBlock(id=event.block_id, source=src),
                        )
```

生产端也真的传 `block_id=block.id`（`agent/_agent.py`）：

```python
# agent/_agent.py
            elif isinstance(block, DataBlock):
                if isinstance(block.source, Base64Source):
                    yield ToolResultDataDeltaEvent(
                        reply_id=self.state.reply_id,
                        tool_call_id=tool_call_id,
                        # Keep the block id so replay groups one payload.
                        block_id=block.id,
                        media_type=block.source.media_type,
                        data=block.source.data,
                    )
```

## ReAct Loop: The Core

`_reply_impl()` 是约 300 行的主循环，核心逻辑在一个 `while True` 里。真实的函数签名与循环头如下（`agent/_agent.py`）：

```python
# agent/_agent.py
    async def _reply_impl(  # pylint: disable=too-many-branches
        self,
        inputs: Msg
        | list[Msg]
        | UserConfirmResultEvent
        | UserInterruptEvent
        | ExternalExecutionResultEvent
        | None = None,
        structured_schema: Type[BaseModel] | None = None,
    ) -> AsyncGenerator[AgentEvent | Msg, None]:
        """Core reply logic."""
```

```python
# agent/_agent.py
            while True:
                # =============================================================
                # Step 3.1: Decide the next action based on the current state
                # =============================================================
                next_action = self._next_action(final_msg)

                match next_action:
                    case Exit(exit_msg=exit_msg, exit_events=exit_events):
                        if not exit_events:
                            # Parked on HITL: the reply is not finished, so
                            # the continuation protocol doesn't apply
                            yield exit_msg
                            return
```

下面是把三种动作摊开后的**简化骨架**（非逐字源码，中文注释为说明）：

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

旧版笔记把 HITL 画成一条状态链，其实**混淆了两个各 5 态的枚举**（v2.0.11 与 v2.0.8 都是如此）：

| 枚举 | 五态 | 位置 |
| :--- | :--- | :--- |
| `ToolCallState` | `PENDING / ASKING / ALLOWED / SUBMITTED / FINISHED` | `message/_block.py` |
| `ToolResultState` | `SUCCESS / ERROR / INTERRUPTED / DENIED / RUNNING` | `message/_block.py` |

两个枚举的真实定义（`message/_block.py`）：

```python
# message/_block.py
class ToolCallState(StrEnum):
    """The state of the tool call."""

    PENDING = "pending"
    ASKING = "asking"
    ALLOWED = "allowed"
    SUBMITTED = "submitted"
    FINISHED = "finished"
```

```python
# message/_block.py
class ToolResultState(StrEnum):
    """The tool result state."""

    SUCCESS = "success"
    ERROR = "error"
    INTERRUPTED = "interrupted"
    DENIED = "denied"
    RUNNING = "running"
```

`DENIED`、`INTERRUPTED`、`ERROR` 是**结果**的状态，不是调用的状态；完整转移图写在 `ToolCallBlock` 的 docstring（`message/_block.py`）：

```python
# message/_block.py
    state: ToolCallState = ToolCallState.PENDING
    """The tool call state
    - 'pending': the initial state when the tool call hasn't been processed
     by the permission system
    - 'asking': the tool call is asking and waiting for user confirmation
    - 'allowed': allowed by the permission system/user and waits for execution
    - 'submitted': the tool call has been submitted for external execution
     and is waiting for results event

    Transitions
    -----------
    pending
      ├── permission DENY / input validation failed ──► finished
      ├── permission ASK ──────────────────────────── ► asking
      │       ├── user denied ───────────────────────► finished
      │       └── user approved ─────────────────────► allowed
      └── permission ALLOW ────────────────────────── ► allowed

    allowed
      ├── local tool  ── (execute) ─────────────────► finished
      └── external tool ──────────────────────────── ► submitted

    submitted
      └── ExternalExecutionResultEvent received ─────► finished
    """
```

v2.0.11 还把主动中断统一收敛成抛 `asyncio.CancelledError`，由 except / finally 一处产出 INTERRUPTED（`agent/_agent.py`）：

```python
# agent/_agent.py
        except asyncio.CancelledError:
            # Handle the CancelledError within the _reply_impl for the
            # agent middlewares
            end_event = ReplyEndEvent(
                session_id=self.state.session_id,
                reply_id=self.state.reply_id,
                finished_reason=ReplyFinishedReason.INTERRUPTED,
            )

            if self.react_config.interruption_raise_cancelled_error:
                raise

        finally:
            if end_event is not None:
                interrupted_end = (
                    end_event.finished_reason
                    == ReplyFinishedReason.INTERRUPTED
                )
                if interrupted_end:
                    # Handle the context when interruption
                    async for _ in self._close_unfinished_tool_calls():
                        yield _

                yield end_event
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

Onion hook 的签名统一是下面这样（`middleware/_base.py` 中 `on_reply` 的原样定义，其余 5 个 hook 参数一致）：

```python
    async def on_reply(
        self,
        agent: "Agent",
        input_kwargs: dict,
        next_handler: Callable[..., AsyncGenerator],
    ) -> AsyncGenerator:
```

基类默认实现直接 `raise RuntimeError(...)`；`is_implemented()` 用 `base_method is not sub_method` 比对基类与子类的方法对象，因此「实现了哪些 hook」是运行时探测出来的，无需显式注册。

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

权限 DSL 的完整逐文件事实（五种模式字段语义、`_check_<mode>` 分发顺序、`suggested_rules` 生成）见 [Middleware 分册（权限）](/docs/CS/AI/LLM/Agent/Product/AgentScope/Middleware.md)。注意：`DenyAllResourceAccessPolicy` 不属于 `permission/` 包的权限 DSL，而是 Service 层的跨 owner 资源访问策略，位于 `src/agentscope/app/access/_policy.py`（见 [App 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/App.md)），与 `PermissionEngine` 的工具级 allow/deny/ask 判定是两条独立链路。

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
# tool/_builtin/_backend.py
    # ── abstract primitives ────────────────────────────────────────

    @abstractmethod
    async def exec_shell(
        self,
        command: list[str],
        *,
        cwd: str | None = None,
        timeout: float | None = None,
    ) -> ExecResult:
        # ...（以下为该方法的 docstring，省略；抽象方法无实现体）

    @abstractmethod
    async def read_file(self, path: str) -> bytes:
        # ...（以下为该方法的 docstring，省略）

    @abstractmethod
    async def write_file(self, path: str, data: bytes) -> None:
        # ...（以下为该方法的 docstring，省略）
```

（三段签名连续摘自 `BackendBase`，中间的 docstring 已用注释标出省略；`exec_shell` 收的是参数列表而非命令行字符串。）

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

`Offloader`（`workspace/_offload_protocol.py`）是个 **Protocol**，只有三个方法——`offload_data_block` / `offload_context` / `offload_tool_result`。`WorkspaceBase` 是它的默认实现，而 Agent 只依赖这个 Protocol（`agent/_agent.py`）。换句话说 offloader 是可替换的，不必是 workspace。

```python
# workspace/_offload_protocol.py
class Offloader(Protocol):
    """The offloader protocol."""

    async def offload_data_block(self, block: DataBlock) -> DataBlock:
        # ...（以下为该方法的 docstring，省略）

    async def offload_context(
        self,
        session_id: str,
        msgs: list[Msg],
    ) -> str:
        # ...（以下为该方法的 docstring，省略）

    async def offload_tool_result(
        self,
        session_id: str,
        tool_result: ToolResultBlock,
    ) -> str:
        # ...（以下为该方法的 docstring，省略）
```

（节选自 `workspace/_offload_protocol.py`，三个方法的 docstring 已用注释标出省略。）

workspace 布局是固定的（`_utils.py`）：

```
${workdir}/
├── data/        # 卸载出来的多模态负载
├── skills/      # 安装进来的 skill
├── sessions/    # 按 session 分的上下文与工具结果
└── .mcp         # MCP 声明，只记录偏离 default_mcps 的 session
```

三条落盘路径：

- **上下文压缩**——`offload_context()` 把消息**追加**写进 `sessions/<session_id>/context.jsonl`，一行一条 JSONL。写之前会把 inline base64 的 DataBlock 先抽到 `data/` 再改写成 **`workspace://`** URL 块（`workspace/_base.py`，旧笔记写的 `file://` 已失效），保证单行体积有界：

```python
# workspace/_base.py
        # A ``workspace://`` reference (workspace-relative path). Unlike a
        # node-local ``file://`` path it is portable: a serving endpoint
        # resolves the actual workspace from the request's session
        # context and reads the relative path. See docs TODO (frontend
        # ``workspace://`` rendering).
        return DataBlock(
            id=block.id,
            name=block.name,
            source=URLSource(
                url=AnyUrl(f"workspace:///{rel}"),
                media_type=block.source.media_type,
            ),
        )
```
- **超长工具结果**——`offload_tool_result()` 写 `sessions/<session_id>/tool_result-<id>.txt`；同名冲突时后缀 `(1)` `(2)`，绝不覆盖旧内容
- **多模态数据**——`offload_data_block()` 写 `data/<sha256(base64)>.<ext>`，同内容短路复用

关键点：**这三份 workspace 文件没有自动回读 API**（`context.jsonl` 全仓只写不读，唯一的 `read_file` 是 `offload_context()` 自己为拼接追加而读）。卸载后只在原位留下 `<system-reminder>offloaded to /path</system-reminder>`，让 Agent 自己用 Read / Grep 去取——决策权留给模型。但别把它和**跨进程会话恢复**混为一谈：后者走 `SessionRecord.state: AgentState` 落 SQL/Redis 的 JSON `payload` 列（`app/storage/_model/_session.py`、`app/_service/_chat.py`），两套持久化互不相通。完整展开见 [Memory 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Memory.md)。

会话恢复一侧确实把持久化的 state 直接灌回 Agent（`app/_service/_chat.py`）：

```python
# app/_service/_chat.py
                agent_state = session_record.state
                agent_state.session_id = session_id
                chat_config = agent_record.data.chat_config
                agent = self._agent_cls(
                    name=agent_record.data.name,
                    system_prompt=system_prompt,
                    model=model,
                    toolkit=toolkit,
                    model_config=ModelConfig(fallback_model=fallback_model),
                    context_config=chat_config.context_config,
                    react_config=chat_config.react_config,
                    state=agent_state,
                    middlewares=middlewares,
                    offloader=workspace,
                )
```

```python
# app/storage/_model/_session.py
    state: AgentState = Field(default_factory=AgentState)
    """Mutable runtime state, updated after each chat turn."""
```

注意别混淆：**Application 层还有一个后台工具卸载**（`app/middleware/_tool_offload_middleware.py`），默认 10s 超时后不取消任务，转交给 `BackgroundTaskManager`，跑完通过 HintBlock 投递 session inbox 并唤醒 Agent。那个是「任务后台化」，这个是「上下文磁盘化」，两回事。


## RAG Subsystem

> RAG 子系统的完整事实（`_document`/`_parser`/`_chunker`/`_knowledge` 算法层、`RAGMiddleware` 双模式、与服务层 `knowledge_base_manager` 的边界）已拆到：[RAG 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/RAG.md)。
## Skill Loading

Skill 的数据结构极简（`skill/_base.py` 的 dataclass，**5 个**字段：`name` / `description` / `dir` / `markdown` / `updated_at`；旧笔记写「六个」是误记），加载逻辑也就没什么花样：

```python
# skill/_base.py
@dataclass
class Skill:
    """The agent skill class"""

    name: str
    """The name of the skill."""
    description: str
    """The description of the skill."""
    dir: str
    """The directory of the agent skill."""
    markdown: str
    """The markdown content of the agent skill."""
    updated_at: float
    """The last updated time of the skill."""
```

- **目录约定**：每个 skill 根目录下必须有 `SKILL.md`，除此之外**不读任何东西**（没有 scripts 子目录机制）
- frontmatter 用 `frontmatter.loads()` 解析，取 `name` 与 `description`，两者任一缺失就 warn 并跳过整个 skill
- 缓存键是 skill 根目录，失效判据是 mtime **精确相等**
- 发现阶段用 `asyncio.to_thread(os.walk)` 避开阻塞，加载阶段 `asyncio.gather(..., return_exceptions=True)` 并发读文件；所有失败路径都吞异常返回空列表

值得记的是 **Jinja2 渲染的时机不在 `skill/` 包里**——skill 正文进入 `Toolkit` 后，要在生成 system prompt 时才渲染（`tool/_toolkit.py`）：

```python
# tool/_toolkit.py
        # If no skills were collected, return None
        if len(skills) == 0:
            return None

        # Generate the skill instruction prompt with the template
        template = Template(self.skill_instruction_template)

        return template.render(
            skills=skills.values(),
            skill_viewer=self.builtin_skill_viewer.tool.name,
        )
```

加载时只做 YAML frontmatter 解析，字符串渲染推迟到最后组装 prompt 那一刻。这样同一个 loader 可以被多种渲染方式复用。

## Formatter Layer

模型适配真正的复杂点不在「怎么发 HTTP 请求」，而在「怎么把统一的 `Msg` 序列翻译成某家 API 认得的 JSON」。AgentScope 用一整包 formatter 来收拢这件事——v2.0.11 的 `formatter/` 目录下 **12 个**非 `__init__` 的 `.py` = 1 个 `FormatterBase` 抽象基类 + **11 个厂商 formatter 文件**；OpenAI 较特殊拆成 `OpenAIChatFormatter` 与 `OpenAIResponseFormatter` 两族（对应 Chat Completions 与 Responses 两套 API），另有 v2.0.9 新增的 `_minimax_formatter.py`，故厂商实为 **10 家**（Anthropic / DashScope / DeepSeek / Gemini / MiniMax / Moonshot / Ollama / OpenAI / Volcengine / xAI）。`model/` 下对应 11 个厂商子模块、`credential/_factory.py` 注册 10 个 Credential 类：

```python
# credential/_factory.py
    _classes: list[Type[CredentialBase]] = [
        AnthropicCredential,
        DashScopeCredential,
        DeepSeekCredential,
        GeminiCredential,
        MiniMaxCredential,
        MoonshotCredential,
        OllamaCredential,
        OpenAICredential,
        XAICredential,
        VolcengineCredential,
    ]
```

`FormatterBase`（`formatter/_formatter_base.py`）的抽象面窄得出人意料——**只有一个抽象方法**：

```python
# formatter/_formatter_base.py
    @abstractmethod
    async def format(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        """Format the Msg objects to a list of dictionaries that satisfy the
        API requirements."""
```

仅就 `FormatterBase` 而言，没有独立的 system prompt / memory / tool schema 抽象方法（框架层的 `MiddlewareBase.on_system_prompt` 是另一套机制，三套长期记忆中间件都实现它）。基类只提供几个共享工具：`convert_tool_result_to_string()`（把工具结果里支持的媒体用 block.id 作 identifier 写进 `<system-reminder>`，并把它作为「提升」出来的 user 消息返回）、`_convert_unsupported_data_block_to_string()`（不支持的媒体 base64 落临时文件、URL 保持 URL）、`_group_messages()`（把 Msg 流切成 tool_sequence / agent_message 两组）。

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

异常只有 7 个类，但分类逻辑很清晰。v2.0.8 全挤在 `exception/_base.py`，v2.0.11 已**拆成三个文件**（`exception/__init__.py`）：`_base.py` 放 2 个基类、`_tool.py` 放 4 个工具异常、`_model.py` 放 1 个。数量没变，路径变了：

```python
# exception/__init__.py
from ._base import (
    AgentOrientedException,
    DeveloperOrientedException,
)
from ._model import StructuredOutputError
from ._tool import (
    ToolInterruptedError,
    ToolNotFoundError,
    ToolJSONDecodeError,
    ToolGroupInactiveError,
)
```

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

`agent/_a2a_agent.py` 的 `A2AAgent` 是把远端 [A2A](/docs/CS/AI/LLM/Protocol/A2A.md) Agent 包装成本地 Agent 形态的适配器——它持有独立的 `A2AAgentState`（含协议层的 `context_id` / `task_id`，与 `AgentState` **没有继承关系**），把 `a2a.types.Part` 转成 `Msg` 的 content block，并发 `ReplyStartEvent` 等本地事件流。用途是让远端 Agent 能混进本地 Pipeline 编排。注意 v2.0.11 里 `A2AAgentState` 已迁到 `state/_a2a_state.py`（`_a2a_agent.py` 从 `..state` 导入），旧笔记写的路径已失效。

```python
# agent/_a2a_agent.py
from ..state import A2AAgentState
```

```python
# state/_a2a_state.py
class A2AAgentState(BaseModel):
    """The A2A agent state."""

    session_id: str = Field(default_factory=_generate_id)
    """The session id of the agent, used to group its streamed events."""

    context_id: str | None = None
    """The context_id of the A2A protocol."""

    task_id: str | None = None
    """The current task id of the agent."""
```

Plan 机制的数据模型在 `state/_task.py`：一个带 DAG 依赖的通用 Task（`blocks` / `blocked_by` 双向列表、`state` 三值 `pending / in_progress / completed`），没有 Plan / Injection 之分。这也解释了为什么 `TaskUpdate` 支持 `add_blocks` / `add_blocked_by` 这类字段。


## Realtime Agent

> `RealtimeAgent`（双向语音、turn-taking 状态机、不继承 `Agent`）的完整事实已拆到：[Realtime 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Realtime.md)。

## Pipeline & Agent Service

`PipelineProtocol` 与 `Agent` 共用 `reply_stream()` 接口——Pipeline 是「固化逻辑的多 Agent 编排器」，按预设顺序把消息喂给一串 Agent；`GoalPipeline` 在此基础上加 executor/verifier 循环与目标检查。事件类型枚举（`EventType` 28 值）、`Msg.append_event` 状态机、DataBlock base64 增量拼接陷阱，以及 Types 系统（`ReplyFinishedReason` / `ErrorType` / `AgentHookTypes`）的完整事实见 [Pipeline 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Pipeline.md)。

Agent Service（`src/agentscope/app/`）到 v2.0.8 已是正式包，v2.0.11 为 **209 文件 / 1.83 MB**、**12 个一级子目录**（`_manager/` `_router/` `_service/` `_tool/` `access/` `channel/` `hub/` `message_bus/` `middleware/` `rag/` `storage/` `workspace_manager/`；旧笔记的「八目录」本就漏了 `access/` `channel/` `message_bus/` `middleware/`）。依赖按组分包（`agentscope[service]` / `[storage-sql]` / `[workspace-docker]` / `[tools]`，v2.0.11 另有 `[realtime]` / `[realtime-local]` / `[tui]`），连内置 Grep 工具都锁 `ripgrep>=14.1,<15`（`pyproject.toml`）。存储层仍是两套后端（`AsyncSQLAlchemyStorage` + `RedisStorage`），**`create_app` 注册 17 个 router**（`app/_app.py`；v2.0.8 是 15 个，新增 `sop_router` 与 `realtime_router`）——`_router/_schema` 是 Pydantic 模型集合不是路由。完整事实见 [App 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/App.md)。

```toml
# pyproject.toml
tools = [
    "ripgrep>=14.1,<15",
]
```

```python
# app/_app.py
    # Built-in routers
    for router in (
        agent_router,
        chat_router,
        credential_router,
        health_router,
        hub_router,
        knowledge_base_router,
        mcp_router,
        schedule_router,
        session_router,
        skill_router,
        sop_router,
        workspace_router,
        model_router,
        realtime_router,
        tts_model_router,
        embedding_model_router,
        channel_router,
    ):
        app.include_router(router)
```

### Hub Subsystem: Registry as Assembly

Agent Service 不直接 hardcode MCP server 或 skill 的来源，而是把它们抽象成 **Hub**——一个「从远端注册中心发现并装载」的抽象（`app/hub/_base.py`）。v2.0.11 含两类：

- **MCPHubBase**（`app/hub/_mcp/_base.py`）—— 发现并装载 MCP server；首实现类名是 `GitHubMCPHub`（`app/hub/_mcp/_github_hub.py`），旧笔记写的 `GitHubHub` 不准确。
- **SkillHubBase**（`app/hub/_skill/_base.py`）—— 发现并装载 skill；首实现类名是 `ClawSkillHub`（`app/hub/_skill/_claw_hub.py`），旧笔记写的 `ClawHub` 不准确。

`hub_id` 受 `HUB_ID_PATTERN = [a-zA-Z0-9_-]+` 约束，`create_app` 的 `_index_hubs` 按 id 建索引，重复 id 直接 `ValueError`——同一 kind 的 hub 必须 id 唯一，否则路由无法唯一定址。`hub` router 把「发现 / 装载 / 列出」能力暴露成 HTTP 端点。完整事实（生命周期、索引、与 workspace 网关的关系）见 [App 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/App.md)。

```python
# app/hub/_base.py
# A hub id is a path segment in the hub routes.
HUB_ID_PATTERN = re.compile(r"[a-zA-Z0-9_-]+")
```

```python
# app/hub/_base.py
        if not HUB_ID_PATTERN.fullmatch(hub_id):
            raise ValueError(
                f"Hub id {hub_id!r} must match [a-zA-Z0-9_-]+ so it is "
                f"usable as a route path segment.",
            )
```

```python
# app/_app.py
    indexed: dict[str, HubBase] = {}
    for hub in hubs or []:
        if hub.hub_id in indexed:
            raise ValueError(
                f"Duplicate {kind} hub id {hub.hub_id!r}: hub ids must be "
                f"unique so routes address exactly one hub.",
            )
        indexed[hub.hub_id] = hub
    return indexed
```

## Comparison

### AgentScope vs LangChain / LangGraph

AgentScope 属于和 LangChain 同层的 Framework，但架构选择不同：

| 维度 | AgentScope | LangChain |
| :--- | :--- | :--- |
| Agent 设计 | 单一 `Agent` 类，内置全部能力 | BaseAgent 继承体系，ReActAgent / PlanExecuteAgent 等 |
| 中间件 | 7 hook 自动检测，onion + transformer 双通道 | Callback 机制（on_chain_start / on_tool_start 等），不区分 hook 位置 |
| 权限 | 核心组件，5 种 mode + 三级规则 + safety ASK | 无内置权限层，靠自定义 chain |
| 事件驱动 | 原生 AgentEvent 流式输出，ReplyStart → ReplyEnd 完整生命周期 | Callback 体系 + streaming 分开 |
| 上下文压缩 | 内置结构化压缩 + runtime injection + 主动 CompressContext 工具；**另有三套长期记忆中间件**（见 [Memory 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Memory.md)） | 需要自己实现 Memory 类（ConversationSummaryMemory 等） |
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
- **AgentState 是所有组件的共享数据总线**——**8 个字段**（`session_id` / `summary` / `context` / `reply_context` / `permission_context` / `tool_context` / `tasks_context` / `middle_context`），被 Agent / PermissionEngine / Toolkit / 所有 Middleware 共同读写。分层与持久化见 [Memory 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Memory.md)
- **中间件在六个不同层级切入**——on_reply 包整个循环、on_reasoning 包模型调用、on_model_call 包底层 API、on_check_permission 包权限判定、on_acting 包工具执行（只包纯 I/O 层）、on_compress_context 包压缩
- **HITL 暂停是轻量的**——yield `RequireUserConfirmEvent` 后直接停在 `_reply_impl` 的 await 点，没有任何 cleanup 或状态保存；下次回来同一条 Agent 实例、同一个 state、循环从断点继续

### AgentState: The Unifying Data Container

`AgentState` 是一个**纯 Pydantic BaseModel**，**8 个字段**，其中只有 5 个是子 context 模型（`reply` / `permission` / `tool` / `tasks` / `middle`，`middle_context` 还是裸 dict），另外三个是 `session_id` / `summary` / `context`：

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
- **不是分离的 Store/Repository**——AgentScope 没有 `ContextStore` / `PermissionStore` 这类类，各个子 context 直接嵌在一个模型里。好处是引用透明（`state.context`、`state.permission_context`），坏处是 state 对象会越来越大；但 AgentScope 的压缩机制（`trigger_ratio=0.8` 就动手）和 tool result truncation（`tool_result_limit=50000`）就是为了限制 state 的体量
- **middle_context 的 key 设计**——每个 middleware 实例用 `get_middleware_key()`（默认类名）注册自己的状态，budget middleware 在里面存 per-reply 的 token 计数。同一个 middleware 实例可以安全地被多个 Agent 共享（因为状态全在 state 里，不在实例里）
- **read_file_cache 的 LRU**——`ToolContext.read_file_cache` 是一个 list（`state/_state.py`），带 `max_cache_files=100` / `max_cache_bytes=25000` 双上限，重复读同一文件时先查 cache（按 mtime 判过期），命中移到末尾、超出则 `pop(0)` 驱逐。`_clear_unreserved_read_cache()` 是**按保留消息里仍引用的路径反向保留、清掉其余**，不是「只清压缩掉的路径」。这个 cache 减少了模型决策后再次 `Read` 同一个文件的开销——典型场景是 Agent 读完 main.py → 让模型推理 → 又要读 main.py 的某行

```python
# state/_state.py
class ToolContext(BaseModel):
    """The tool context, e.g. tool cache"""

    max_cache_files: int = Field(default=100, gt=1)
    """The maximum number of cached files."""
    max_cache_bytes: float = Field(default=25000, gt=10000)
    """The maximum size of the accumulated read file cache."""
    read_file_cache: list[ReadCacheEntry] = Field(default_factory=list)
    """The cache for Read/Write/Edit file tools."""
```

```python
# state/_state.py
        # Find the cache entry
        for entry in self.read_file_cache:
            if entry.file_path == file_path:
                if mtime is None:
                    try:
                        mtime = await aiofiles.os.path.getmtime(file_path)
                    except Exception:
                        mtime = None

                # Concurrent calls may have reordered or dropped the entry
                # while awaiting, so locate it again by the object itself.
                if entry not in self.read_file_cache:
                    return None

                self.read_file_cache.remove(entry)
                if mtime != entry.updated_at:
                    # Cache is outdated, or the file no longer exists
                    return None

                # Move the entry to the most recent position
                self.read_file_cache.append(entry)
                return entry
        return None
```

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

#### MessageBus: Five Primitives Instead of Domain-Specific APIs

`MessageBus` 是整个 Service 层的神经中枢。AgentScope 没有定义 `InboxQueue` / `EventLog` / `WakeupSignal` 这类领域对象，而是把协调需求收敛成**五种消费语义原语（Mode A/C/D/E/F，编号无 B）**，每个原语对应一种数据生命周期：

| 原语模式 | 语义 | 典型用途 |
| :--- | :--- | :--- |
| **Mode A — drain queue** | 单一消费者、ack-on-read。每条 entry 被一个读者拿走后立即删除 | wakeup trigger queue、session inbox（HintBlock 投递） |
| **Mode C — replay log** | 多消费者、非破坏性读取、`max_len` 或 TTL 限长 | session event log（SSE late-join 补历史） |
| **Mode D — transient broadcast** | fire-and-forget，只有实时订阅者能收到 | wakeup signal、cancel broadcast、schedule lifecycle notify |
| **Mode E — distributed lock** | 集群级互斥，带心跳续租防止进程崩溃死锁 | session run 锁（同一 session 同时只有一个 ChatService.run 在跑） |
| **Mode F — registry map** | hash-keyed namespace，支持 CAS（compare-and-set）和 pop-exactly-once | background task 全局注册表、channel liveness 心跳 |

**设计动机**：把业务语义与传输层解耦。Service 层上层代码只管选原语 + 定义 key 命名约定（`MessageBusKeys` 静态类集中管理所有 key 格式），底层可以换成 Redis / NATS / InMemory 而不触动业务代码。`_base.py` 里那句"Counted broadcast is intentionally not exposed"尤其说明问题——想 fan-out 给 N 个成员？写时 fan-out（每个收件人 inbox push 一条 Mode A），不要让总线维护 consumer group 协调状态。总线保持简单，复杂性留给生产者。

**Mode C 的 replay-then-live 模式**是事件流 gap-free 读取的基础。Service 层的 `open_reply_stream()`（位于 `app/channel/_stream.py`，**并非 `MessageBus` 成员**，而是模块级 async 生成器）的两阶段读取——先 `log_read(max_count=SESSION_REPLAY_MAX_LEN)` 把最近 1000 条历史拉回来，再进入 `subscribe` 实时模式，用 entry_id 做去重——让消费者可以在 Agent 已经在跑之后才订阅（SSE endpoint 的典型场景），而不会错过任何事件。

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

## Version Evolution: v2.0.8 to v2.0.11

旧笔记把这一节写成「v2.0.8 → v2.0.10」，并把 `tui/`、Team Pipeline、SOP、MiniMax、三家 Realtime 适配器都归给 v2.0.10。逐 tag `git cat-file -e` 核对后，**版本归属整段要改**。下表是本机 v2.0.11 树的实测结果：

| 模块 | v2.0.8 | v2.0.9 | v2.0.10 | v2.0.11 |
| :--- | :---: | :---: | :---: | :---: |
| `tui/`（Textual） | — | ✅ | ✅ | ✅ |
| `pipeline/_team_pipeline.py` | — | ✅ | ✅ | ✅ |
| `sop/` 与 `formatter/_minimax_formatter.py` | — | ✅ | ✅ | ✅ |
| `realtime/_openai`、`_gemini`、`_xai` 适配器 | — | ✅ | ✅ | ✅ |
| `app/_service/_webrtc_session.py`（WebRTC） | — | — | ✅ | ✅ |
| `asr/` 整包 | — | — | — | ✅ |
| `tts/`、`realtime/_dashscope`、`console/` | ✅ | ✅ | ✅ | ✅ |

三段节奏很清楚：

- **v2.0.9 是结构性大改**（`app/` + `pipeline/` 45 文件、+4237/−68）：SOP、Classifier、TeamPipeline、TUI、MiniMax 与三家 Realtime 适配器都在这一版进来。
- **v2.0.10 是服务化补齐**（48 文件、+2160/−258）：WebRTC transport/session、`RealtimeService`、`/realtime` 路由、`realtime-local` extra；同时**删掉**了 v2.0.9 才引入的 `TruncationSupport` 枚举，改用 `supports_text_input` / `supports_history_replay` 等布尔能力位。
- **v2.0.11 是收敛版**：`app/` + `pipeline/` 只有 10 文件、+78/−26，全是 Starlette 的 `HTTP_422_UNPROCESSABLE_ENTITY` → `HTTP_422_UNPROCESSABLE_CONTENT` 常量改名、`ttl_secs=0` 单行修复、Node 版本与 `model_class`。真正的新东西在别处：`asr/` 整包（8 文件、+447 行）与三张 realtime 模型卡。

全树 `git diff --shortstat v2.0.8..v2.0.11` 是 502 文件、+52995/−3030，但那个数字含 docs / examples / tests。**按 tag 逐段看，最新一版反而是改动最小的一版**——照旧笔记的口径外推「v2.0.11 大改」会严重误判。

四个重点方向各自的完整展开已经拆到独立分册：主循环与状态机归 [AgentLoop 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentLoop.md)，流程硬约束归 [SOP 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/SOP.md)，概率分类与逐 reply 选模归 [Classifier 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Classifier.md)，语音三栈与 WebRTC 归 [VoiceStack 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/VoiceStack.md)，终端客户端归 [TUI 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/TUI.md)。

## Corrections: v2.0.8 Baseline to v2.0.11

本次重核把旧笔记里所有可证伪的断言逐条对照了 v2.0.11 源码。下表只列**失效或需要精化**的项；完全成立的部分（BackendBase 三原语、7 个 middleware hook、5 种权限模式、ContextConfig 八个默认值、RAG 四层算法、28 个 EventType、六种 ContentBlock）不再重复。

### Core Agent Layer

| 旧结论 | v2.0.11 事实 | 依据 |
| :--- | :--- | :--- |
| `agent/_agent.py` 约 2500 行 | **3942 行**，且 v2.0.8 已是 3908 行——旧基线本身即误 | `agent/_agent.py` |
| `_reply_impl()` 约 300 行 | 共 270 行，主循环是 `while True` | `agent/_agent.py` |
| AgentState 六/七个子 context | **8 字段**（含 `middle_context`），v2.0.8→v2.0.11 只改了注释拼写 | `state/_state.py` |
| HITL 一条 `PENDING→…→ERROR` 状态链 | 两个各 5 态的枚举：`ToolCallState` 与 `ToolResultState`，`DENIED/INTERRUPTED/ERROR` 属后者 | `message/_block.py` |
| DataBlock base64 增量拼接「陷阱」 | 术语应改：decode→concat→re-encode 在 v2.0.8 已实现；v2.0.11 **按 `event.block_id` 定位同 id 分片**，找不到则 append 新块，解决多 DataBlock 串台 | `message/_base.py`、`agent/_agent.py` |
| 异常 7 类全在 `exception/_base.py` | 数量仍 7，但拆成 `_base.py` / `_tool.py` / `_model.py` 三文件 | `exception/__init__.py` |
| `A2AAgentState` 在 `agent/_a2a_agent.py` | 迁到 `state/_a2a_state.py` | `agent/_a2a_agent.py` |

### Model and Tool Layer

| 旧结论 | v2.0.11 事实 | 依据 |
| :--- | :--- | :--- |
| formatter 11 个 py = 1 基类 + 10 家 | **12 个 py = 1 基类 + 11 个厂商 formatter 文件**；OpenAI 占两族，故厂商实为 10 家（新增 MiniMax） | `formatter/__init__.py` |
| 10 个模型厂商子模块 | 11 个（`model/_minimax/`） | `model/__init__.py` |
| CredentialFactory 静态注册 9 个类 | 10 个类，改为 `_classes` 列表 + 惰性 `_get_adapter()`，并新增 `register_credential()` | `credential/_factory.py` |
| `credential/_kimi.py` 是 0 字节空文件；没有 `_typesafe.py` | 前者已不存在，后者已存在 | `credential/` 清单 |
| Skill 六个字段 | **5 个**：`name/description/dir/markdown/updated_at` | `skill/_base.py` |
| 内置 13 个工具；没有 `metadata_schema` / `check_external_result()` | 14 个（新增 `AskUser`）；两个契约都已落地 | `tool/_builtin/_ask_user.py`、`tool/_base.py` |

### Realtime and Service Layer

| 旧结论 | v2.0.11 事实 | 依据 |
| :--- | :--- | :--- |
| Realtime 只有 DashScope 一家 | **4 家 / 5 类**（DashScope 两类 + Gemini / OpenAI / xAI） | `realtime/__init__.py` |
| 能力差异靠 `TruncationSupport` 三值枚举吸收 | 枚举 v2.0.9 引入、**v2.0.10 已删除**，改为 `supports_text_input` / `supports_history_replay` 等布尔位 | `realtime/_base.py` |
| barge-in 五步含 `model.truncate()` | 三步：`clear_audio()` + `cancel_response()` + `_finish_reply(INTERRUPTED)` | `agent/_realtime/_agent.py` |
| 没有 WebRTC transport | `WebRTCAudioTransport(TransportBase)` 在 app 层跨包实现 | `app/_service/_webrtc_audio_transport.py` |
| `pipeline/` 只导出 2 个名字 | 4 个（含 `TeamPipeline` / `TeamMember`），且 Team Pipeline 是 **v2.0.9** 引入 | `pipeline/__init__.py` |
| `create_app` 注册 15 个路由；app 八目录 | **17 个 router**（+sop、+realtime）、**12 个一级子目录**、209 文件 1.83 MB | `app/_app.py` |
| Hub 实现叫 `GitHubHub` / `ClawHub` | `GitHubMCPHub` / `ClawSkillHub` | `app/hub/_mcp/_github_hub.py`、`app/hub/_skill/_claw_hub.py` |
| `open_reply_stream` 拉最近 1000 条再订阅 | 先订阅（5s 超时），再按**持久化 checkpoint `since`** 回放最多 1000 条；且函数体无 `yield`，是 `return _read(...)` | `app/channel/_stream.py` |
| lifespan 的 enter 顺序含 ChatService / SessionService | 二者 inline 构造、**不进 AsyncExitStack**；v2.0.11 真正在 stack 上新增的是 `SOPService` | `app/_lifespan.py` |
| App 分册称 SOP / Classifier / AskUser / TUI「本树不存在」 | v2.0.11 全部存在，SOP 核心在顶层 `src/agentscope/sop/` | `sop/__init__.py`、`classifier/__init__.py` |

### Version Attribution

| 旧结论 | v2.0.11 事实 |
| :--- | :--- |
| `tui/`、Team Pipeline、SOP、MiniMax、三家 Realtime 适配器是 v2.0.10 新增 | 全部是 **v2.0.9** 引入（`git cat-file -e` 逐 tag 核对） |
| WebRTC 与三家 Realtime 适配器同批 | WebRTC 是 **v2.0.10**；`asr/` 是 **v2.0.11**；`tts/` 整包 v2.0.8 已有 |

> [!NOTE]
>
> 判断这类框架笔记是否过时，最可靠的做法不是看 release notes 的「新特性」列表，而是拿本地 tag 做 `git cat-file -e <tag>:<path>` 逐个探测。文档里的「新增」常按发布节奏归组，与代码实际落地的版本差一个 tag。


## Links

- [Agent 目录](/docs/CS/AI/LLM/Agent/README.md)
- [AgentLoop](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentLoop.md) / [SOP](/docs/CS/AI/LLM/Agent/Product/AgentScope/SOP.md) / [Classifier](/docs/CS/AI/LLM/Agent/Product/AgentScope/Classifier.md) / [VoiceStack](/docs/CS/AI/LLM/Agent/Product/AgentScope/VoiceStack.md) / [TUI](/docs/CS/AI/LLM/Agent/Product/AgentScope/TUI.md) / [Memory](/docs/CS/AI/LLM/Agent/Product/AgentScope/Memory.md)
- [AgentScopeJava](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/AgentScopeJava.md) / [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md) / [Pi](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md) / [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md)
- [LLM 应用开发框架](/docs/CS/AI/LangTools.md)
- [Agent Theory](/docs/CS/AI/LLM/Agent/Theory/Agent.md) / [Permission](/docs/CS/AI/LLM/Agent/Theory/Permission.md) / [Compaction](/docs/CS/AI/LLM/Agent/Theory/Compaction.md)

## References

- [AgentScope GitHub](https://github.com/agentscope-ai/agentscope)
- [AgentScope v2.0.11 release notes (2026-10-27)](https://github.com/agentscope-ai/agentscope/releases/tag/v2.0.11)
- [AgentScope v2.0.11 源码树](https://github.com/agentscope-ai/agentscope/tree/v2.0.11/src/agentscope)
- [AgentScope 文档](https://docs.agentscope.io/)
- [AgentScope: A Flexible yet Robust Multi-Agent Platform (arxiv 2402.14034)](https://arxiv.org/abs/2402.14034)
- [AgentScope 1.0: A Developer-Centric Framework for Building Agentic Applications (arxiv 2508.16279)](https://arxiv.org/abs/2508.16279)
