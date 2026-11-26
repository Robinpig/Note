## Introduction

AgentScope 把「一个 Agent 怎么跑」和「一串 Agent 怎么编排」用同一套接口表达：`PipelineProtocol` 只暴露 `reply_stream()`，和 `Agent.reply_stream()` 返回完全相同的 `AgentEvent` 流。这意味着 pipeline 可以无缝嵌进另一条 pipeline、被另一个 Agent 调用、或者挂在 Agent Service 的多租户会话里。

本分册聚焦四件事：**Pipeline 协议与 GoalPipeline 实现**、**强类型事件系统（28 个 EventType）**、**支撑类型（ReplyFinishedReason / ErrorInfo / Hook 类型）**、以及 **Msg 的状态机式增量重建**（尤其是 DataBlock 的 block_id 分片合并）。它们合起来构成 AgentScope 的「事件织物」，上层 ReAct 循环、中间件、HITL、App 层全部建立在这之上。主干 Agent 机制见 [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)。

## Pipeline Protocol

`PipelineProtocol` 定义在 `src/agentscope/pipeline/_base.py`，是一个 `Protocol`（结构化子类型，不靠继承）：

```python
class PipelineProtocol(Protocol):
    """What a pipeline has to offer to go where an agent goes.

    Declared as a plain ``def`` returning an async generator rather than
    an ``async def``: such a function is called, not awaited, and an
    ``async def`` here would be satisfied by neither ``Agent`` nor any
    pipeline.
    """

    def reply_stream(
        self,
        inputs: Msg
        | list[Msg]
        | UserConfirmResultEvent
        | UserInterruptEvent
        | ExternalExecutionResultEvent,
    ) -> AsyncGenerator[AgentEvent | Msg, None]:
        """Reply to the given inputs and stream what happens."""
```

只有**一个**方法 `reply_stream`，签名与 `Agent.reply_stream` 对齐。注意方法体用的是 `def` 而非 `async def`——因为 `Protocol` 只描述结构，`def` 能同时匹配同步与异步实现；`GoalPipeline` 自身用 `async def` 提供真正的异步生成器。

`src/agentscope/pipeline/__init__.py` 导出 **4 个**名字：`PipelineProtocol` / `GoalPipeline` / `TeamPipeline` / `TeamMember`：

```python
from ._base import PipelineProtocol
from ._goal_pipeline import GoalPipeline
from ._team_pipeline import TeamMember, TeamPipeline

__all__ = [
    "PipelineProtocol",
    "GoalPipeline",
    "TeamMember",
    "TeamPipeline",
]
```

`TeamPipeline`（`pipeline/_team_pipeline.py`，Leader 委派 `TeamMember`）是 **v2.0.9** 引入（旧笔记写 v2.0.10 有误），且不显式继承 `PipelineProtocol`，靠结构化匹配。它分组并发：`asyncio.create_task(run_group)` + `gather`、同一 member 组内串行、`asyncio.Queue` 回收结果并按 call order 排序。`_team_pipeline.py` 里 `run_all` 建任务与汇总的真实源码：

```python
        async def run_all() -> None:
            """Run every group and mark the end of the stream."""
            tasks = [
                asyncio.create_task(run_group(*group))
                for group in groups.items()
            ]
            try:
                await asyncio.gather(*tasks)
            finally:
                # gather propagates a member failure without stopping siblings.
                # Join them before ending the round, preserving the exception.
                for task in tasks:
                    if not task.done():
                        task.cancel()
                await asyncio.gather(*tasks, return_exceptions=True)
                await queue.put(sentinel)
```

结果按调用顺序排回 leader 的 context，也由同一文件末尾连续几行实现：

```python
        # Results land in the leader's context in the order it called
        order = {_.id: i for i, _ in enumerate(tool_calls)}
        results.extend(sorted(round_results, key=lambda _: order[_.id]))
```

`GoalPipeline` 在 v2.0.11 另加 `_executor_retries` / `_verifier_retries` 与 `_check_retry_budget`（见下）。

## GoalPipeline

`GoalPipeline`（`src/agentscope/pipeline/_goal_pipeline.py`）是骨架化逻辑的 executor–verifier 双 Agent 循环，把「目标是否达成」的判断从 prompt 恳求变成硬契约。

### Constructor

`_goal_pipeline.py` 里的构造签名与默认值：

```python
    def __init__(
        self,
        executor: Agent,
        verifier: Agent,
        verifier_reset_context: bool = True,
        max_iters: int = 10,
        max_retries: int = 3,
    ) -> None:
```

- `verifier_reset_context=True`：每轮验证后清掉 verifier 的对话上下文（`state.context.clear()` + `state.summary = ""`），但**工具/任务状态保留**——避免 verifier 记住上一轮细节而放水。
- `max_iters=10`：目标尝试上限；`max_retries=3`：executor/verifier 生成合法结构化输出的重试上限。

### The Two Structured Schemas

循环靠两个 Pydantic 模型收口，二者都是 `result` / `report` 式的「交卷」契约，`_goal_pipeline.py` 里的真实定义：

```python
class _ExecutionReport(BaseModel):
    """The output of an execution."""

    report: str = Field(
        description=(
            "An achievement report of the given goal. E.g. file paths, entry "
            "points, how-to-run, runtime environment, etc. "
            "So that a verifier can check if you have achieved the goal. "
        ),
    )


class _VerificationResult(BaseModel):
    """The result of a verification."""

    result: Literal["pass", "fail", "impossible"] = Field(
        description=(
            "The verification result, which can be 'pass', 'fail', or "
            "'impossible'. 'impossible' means the given goal is impossible to "
            "achieve, and the executor should stop trying."
        ),
    )

    message: str = Field(
        description=(
            "If not passed, the message should explain why it "
            "failed, and what needs to be fixed. List the specific "
            "issues that need to be addressed, including where to "
            "exactly find them (e.g., file paths, line numbers)."
        ),
    )
```

- `_ExecutionReport`：只有 `report: str`。executor 必须把「我做了什么」写成机器可核验的产出说明——文件路径、入口点、运行环境等，好让 verifier 去查。
- `_VerificationResult`：`result: Literal["pass","fail","impossible"]` + `message: str`。`message` 在失败时解释「缺什么、错在哪、精确到文件:行号」，而不是笼统说「不对」。`impossible` 表示目标本身不可达成，executor 应当立即停手。

### The Iteration Budget Lives On The Instance

关键设计：`self._iters = 0` 挂在**实例**上，不在 `reply_stream` 局部变量里。源码注释写明理由——**HITL resume 不重置预算**；旁边就是 v2.0.11 新增的两个重试计数器：

```python
        # Rounds already judged. On the instance rather than in
        # ``reply_stream``, so a HITL resume does not restart the budget.
        self._iters = 0
        # Preserve each participant's retry budget across HITL resumes.
        self._executor_retries = 0
        self._verifier_retries = 0
        self._goal: None | list[TextBlock | DataBlock] = None
```

一次新鲜运行（输入是 `Msg`/`list[Msg]`）会把 `_iters` 清零；而从外部回灌的确认/中断事件不会，因此 parked 之后恢复不会偷偷多给几轮尝试。`_check_retry_budget` 是同一文件里对这两个计数器的收口：

```python
    def _check_retry_budget(
        self,
        retries: int,
        participant: Literal["executor", "verifier"],
    ) -> None:
        """Raise when a participant exhausts its structured-output retries."""
        if retries > self.max_retries:
            output_name = {
                "executor": "execution report",
                "verifier": "verification result",
            }[participant]
            raise RuntimeError(
                f"The {participant} failed to generate a valid "
                f"{output_name} after {self.max_retries} retries.",
            )
```

### reply_id Routing

`reply_stream` 入参除了 `Msg | list[Msg]`，还接受三类 HITL 事件：`UserConfirmResultEvent` / `UserInterruptEvent` / `ExternalExecutionResultEvent`。这些事件携带 `reply_id`，pipeline 据此把事件路由给正确的那一方。下面是 `_goal_pipeline.py` 里判定输入为 HITL 事件之后的连续分支：

```python
            if inputs.reply_id == self.executor.state.reply_id:
                executor_inputs = inputs
            elif inputs.reply_id == self.verifier.state.reply_id:
                verifier_inputs = inputs
            else:
                raise ValueError(
                    f"Invalid inputs with reply_id: {inputs.reply_id}. ",
                )
```

若 `UserInterruptEvent` 落到 verifier 一侧，则把 parked 的对象换成 verifier 并直接 `reply_stream(inputs)` 转发后返回——打断的是正在等待外部输入的 Agent。这段转发紧跟在路由之后：

```python
        if isinstance(inputs, UserInterruptEvent):
            parked = (
                self.verifier if verifier_inputs is not None else self.executor
            )
            async for _ in parked.reply_stream(inputs=inputs):
                yield _
            return
```

### The Loop Body

每轮：先跑 executor（带 `structured_schema=_ExecutionReport`），executor 一旦 yield `RequireExternalExecutionEvent` / `RequireUserConfirmEvent` 就 `break_loop` 跳出，把控制权交还调用方；executor 产出 `Msg` 且 `structured_output` 里有 `report` 才算拿到执行报告。循环开头这段真实源码把「带 schema 跑」「park 就 break」「从 structured_output 取 report」写在一起：

```python
        while True:
            # Executor step
            break_loop = False
            execution_report = None
            if executor_inputs is not None:
                while execution_report is None:
                    # Run the executor with the given inputs
                    async for _ in self.executor.reply_stream(
                        inputs=executor_inputs,
                        structured_schema=_ExecutionReport,
                        yield_final_msg=True,
                    ):
                        yield _
                        if isinstance(
                            _,
                            (
                                RequireExternalExecutionEvent,
                                RequireUserConfirmEvent,
                            ),
                        ):
                            break_loop = True
                        elif (
                            isinstance(_, Msg)
                            and _.finished_reason
                            == ReplyFinishedReason.COMPLETED
                            and _.structured_output
                        ):
                            execution_report = _.structured_output.get(
                                "report",
                            )
```

没交卷时注入提示逼它调 `GenerateStructuredOutput` 重来，也由紧随其后的连续几行实现：

```python
                    if execution_report is None:
                        self._executor_retries += 1
                        self._check_retry_budget(
                            self._executor_retries,
                            "executor",
                        )
                        # Update the instruction
                        executor_inputs = UserMsg(
                            name="system",
                            content=(
                                "<system-reminder>You have failed to generate "
                                "valid execution report. You should call the "
                                "'GenerateStructuredOutput' tool with a valid "
                                "structured output that matches the schema. "
                            ),
                        )
```

随后构造 verifier 输入：把原始 `_goal` 和 `report` 包进 `<goal>…</goal>` `<report>…</report>` 的 system-reminder。verifier 用 `structured_schema=_VerificationResult` 判定：

- `pass` / `impossible` → `break_loop=True`，循环结束（`impossible` 只打一条 info 日志）。
- `fail` → `self._iters += 1`；若 `verifier_reset_context` 则清上下文；若 `_iters >= max_iters` 则结束；否则把 verifier 的 `message` 作为 feedback 包成 system-reminder 回喂 executor 下一轮改进。

两条失败路径都会触发「executor 没交卷」的重试：若 executor 没产出合法 `_ExecutionReport`，注入提示让它调用 `GenerateStructuredOutput` 工具重来；verifier 同理。这复用了 Agent 层「吞掉 ReplyEndEvent 逼多跑一轮」的同一能力（见 [Middleware 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Middleware.md)）。

### A Minimal GoalPipeline Example

executor 与 verifier 就是两个普通 `Agent`，差别只在 system prompt 的「角色」。`GoalPipeline` 把它们套进 executor–verifier 双 Agent 循环，把「目标是否达成」变成硬契约：

```python
from agentscope.agent import Agent
from agentscope.credential import OpenAICredential
from agentscope.message import UserMsg
from agentscope.model import OpenAIChatModel
from agentscope.pipeline import GoalPipeline
from agentscope.tool import Toolkit

def build(model):
    return Agent(name="worker", system_prompt="...", model=model, toolkit=Toolkit())

model = OpenAIChatModel(credential=OpenAICredential(api_key="sk-..."), model="gpt-4.1")

pipeline = GoalPipeline(
    executor=build(model),        # 负责干活，交 _ExecutionReport
    verifier=build(model),        # 负责核验，判 pass/fail/impossible
    max_iters=10, max_retries=3,
)

# reply_stream 返回与 Agent.reply_stream 完全相同的 AgentEvent 流
async for event in pipeline.reply_stream(
    UserMsg(name="user", content="写一个 hello.py 并打印 Hello, World。"),
):
    if event.type == "reply_end":
        print("finished_reason =", event.finished_reason)
```

落点对照上文：① `reply_stream` 入参是 `Msg | list[Msg]`，也能吃 HITL 事件（`UserConfirmResultEvent` / `UserInterruptEvent` / `ExternalExecutionResultEvent`）做断点续跑；② 循环预算 `self._iters` 挂在**实例**上——一次新鲜 `Msg` 输入会清零，外部回灌的确认/中断事件不会，因此 parked 后 resume 不会偷偷多给轮次；③ verifier 每轮核验后默认清上下文（`verifier_reset_context=True`），但工具/任务状态保留，避免它记住上一轮细节而放水。Team Pipeline 是 v2.0.9 引入的 `_team_pipeline.py`（Leader 委派 `TeamMember`），与 `GoalPipeline` 并列成为第二个内置 pipeline。

## Event System

AgentScope 的输出是**强类型事件流**，不是裸文本流。全部事件定义在 `src/agentscope/event/_event.py`，核心是 `EventType(StrEnum)` 的 **28 个值**。它们按生命周期分组：

| 分组 | 事件 | 形状 |
| :--- | :--- | :--- |
| Reply | `REPLY_START` / `REPLY_END` | `REPLY_END` 带 `finished_reason` + 可选 `error` |
| Model call | `MODEL_CALL_START` / `MODEL_CALL_END` | `END` 带 `input_tokens`/`output_tokens`/`cache_input_tokens`/`cache_creation_input_tokens` |
| Text block | `TEXT_BLOCK_START` / `TEXT_BLOCK_DELTA*` / `TEXT_BLOCK_END` | 增量 `delta: str`；`END` 的 `text` 仅在「非拼接」时填充（如语音被截断成用户实际听到的部分） |
| Data block | `DATA_BLOCK_START` / `DATA_BLOCK_DELTA*` / `DATA_BLOCK_END` | `DELTA` 的 `data`/`url` **互斥**（model_validator 强制二选一） |
| Thinking block | `THINKING_BLOCK_START` / `THINKING_BLOCK_DELTA*` / `THINKING_BLOCK_END` | 增量 `delta: str` |
| Hint | `HINT_BLOCK` | 一次性携带完整 `HintBlock`（非流式），`hint` 可为 `str` 或 `list[TextBlock \| DataBlock]` |
| Tool call | `TOOL_CALL_START` / `TOOL_CALL_DELTA*` / `TOOL_CALL_END` | `DELTA` 是 JSON 片段 `delta: str` |
| Tool result | `TOOL_RESULT_START` / `TOOL_RESULT_TEXT_DELTA*` / `TOOL_RESULT_DATA_DELTA*` / `TOOL_RESULT_END` | `END` 带 `state: ToolResultState` + `metadata` |
| Iteration cap | `EXCEED_MAX_ITERS` | `@deprecated`，语义已由 `ReplyEndEvent.finished_reason` 接管 |
| HITL | `REQUIRE_USER_CONFIRM` / `REQUIRE_EXTERNAL_EXECUTION` | 各带 `tool_calls: List[ToolCallBlock]` |
| HITL result | `USER_CONFIRM_RESULT` / `USER_INTERRUPT` / `EXTERNAL_EXECUTION_RESULT` | `USER_INTERRUPT` 仅带 `reply_id`；result 事件带 `confirm_results` / `execution_results` |
| Extensible | `CUSTOM` | `name: str` + `value: dict`，供服务层通知前端（如 `"state_updated"` / `"team_updated"`） |

计数：`2 + 2 + 3 + 3 + 3 + 1 + 3 + 4 + 1 + 2 + 3 + 1 = 28`。`EventType` 的真实枚举定义（`event/_event.py`）：

```python
class EventType(StrEnum):
    """Event type enumeration."""

    REPLY_START = "REPLY_START"
    REPLY_END = "REPLY_END"

    MODEL_CALL_START = "MODEL_CALL_START"
    MODEL_CALL_END = "MODEL_CALL_END"

    TEXT_BLOCK_START = "TEXT_BLOCK_START"
    TEXT_BLOCK_DELTA = "TEXT_BLOCK_DELTA"
    TEXT_BLOCK_END = "TEXT_BLOCK_END"

    DATA_BLOCK_START = "DATA_BLOCK_START"
    DATA_BLOCK_DELTA = "DATA_BLOCK_DELTA"
    DATA_BLOCK_END = "DATA_BLOCK_END"

    THINKING_BLOCK_START = "THINKING_BLOCK_START"
    THINKING_BLOCK_DELTA = "THINKING_BLOCK_DELTA"
    THINKING_BLOCK_END = "THINKING_BLOCK_END"

    HINT_BLOCK = "HINT_BLOCK"

    TOOL_CALL_START = "TOOL_CALL_START"
    TOOL_CALL_DELTA = "TOOL_CALL_DELTA"
    TOOL_CALL_END = "TOOL_CALL_END"

    TOOL_RESULT_START = "TOOL_RESULT_START"
    TOOL_RESULT_TEXT_DELTA = "TOOL_RESULT_TEXT_DELTA"
    TOOL_RESULT_DATA_DELTA = "TOOL_RESULT_DATA_DELTA"
    TOOL_RESULT_END = "TOOL_RESULT_END"

    EXCEED_MAX_ITERS = "EXCEED_MAX_ITERS"

    REQUIRE_USER_CONFIRM = "REQUIRE_USER_CONFIRM"
    REQUIRE_EXTERNAL_EXECUTION = "REQUIRE_EXTERNAL_EXECUTION"

    USER_CONFIRM_RESULT = "USER_CONFIRM_RESULT"
    USER_INTERRUPT = "USER_INTERRUPT"
    EXTERNAL_EXECUTION_RESULT = "EXTERNAL_EXECUTION_RESULT"

    CUSTOM = "CUSTOM"
```

### Why Strong Typing Instead Of Callbacks

`EventBase` 是全部事件的基类，带 `id`（`_generate_id`）、`created_at`（ISO 8601）、`metadata`，且设置 `use_enum_values=True`。每个具体事件都是 Pydantic model，字段静态可查。其真实定义：

```python
class EventBase(BaseModel):
    """Base event class."""

    model_config = ConfigDict(use_enum_values=True)

    id: str = Field(default_factory=_generate_id)
    """Unique event identifier."""
    created_at: str = Field(default_factory=_generate_timestamp)
    """ISO 8601 timestamp of when the event was created."""
    metadata: Dict[str, Any] = Field(default_factory=dict)
    """Optional metadata attached to the event."""
```

对比 LangGraph 式的 callback / node 钩子，AgentScope 选择把「发生了什么」建模成**可序列化、可重放、可跨进程传递**的事件对象：App 层直接把 `AgentEvent` 推给 WebSocket；TUI 用 `Msg.append_event()` 按 `reply_id` 归并重建消息；HITL 把事件作为下一次 `reply_stream` 的输入灌回——同一套数据结构贯穿本地、服务、终端三种客户端。

### Deprecation Notes

- `ReplyEndReason`：`@deprecated`，值与 `ReplyFinishedReason` 兼容（`completed`/`interrupted`/`exceed_max_iters`），保留只为向后兼容；新代码应改用 `agentscope.types.ReplyFinishedReason`。真实定义：

```python
@deprecated(
    "ReplyEndReason is deprecated and will be removed; "
    "use agentscope.types.ReplyFinishedReason instead.",
)
class ReplyEndReason(StrEnum):
    """Deprecated alias of :class:`~agentscope.types.ReplyFinishedReason`,
    kept for backward compatibility. Value-compatible (both ``StrEnum``),
    so existing code that constructs or compares against it keeps working."""

    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    EXCEED_MAX_ITERS = "exceed_max_iters"
```

- `ExceedMaxItersEvent`：`@deprecated`，仍 emit 但无语义；判断迭代超限应读 `ReplyEndEvent.finished_reason == ReplyFinishedReason.EXCEED_MAX_ITERS`。真实定义：

```python
@deprecated(
    "ExceedMaxItersEvent is deprecated and will be removed; check the "
    "'finished_reason' field of ReplyEndEvent against "
    "ReplyFinishedReason.EXCEED_MAX_ITERS instead.",
)
class ExceedMaxItersEvent(EventBase):
    """Deprecated exceeded max iteration event, still emitted for backward
    compatibility without semantics; use ``ReplyEndEvent.finished_reason``."""

    type: Literal[EventType.EXCEED_MAX_ITERS] = EventType.EXCEED_MAX_ITERS
    """Event type."""
    reply_id: str
    """ID of the reply message associated with this run."""
    name: str
    """Name of the agent."""
```

## Key Event Classes

除了上面的分组，有几个字段值得单独记：

- **`ModelCallEndEvent`**：四个 token 计数 `input_tokens` / `output_tokens` / `cache_input_tokens` / `cache_creation_input_tokens`（后两个默认 0）。这是后面 token 预算中间件（`ReplyBudgetControlMiddleware`）的唯一数据来源。
- **`DataBlockDeltaEvent`**：`data` 与 `url` **互斥**，由 `@model_validator(mode="after")` 强制——正好一个来源。真实定义：

```python
class DataBlockDeltaEvent(EventBase):
    """Data block delta event."""

    type: Literal[EventType.DATA_BLOCK_DELTA] = EventType.DATA_BLOCK_DELTA
    """Event type."""
    reply_id: str
    """ID of the reply message this block belongs to."""
    block_id: str
    """Unique identifier of the data block."""
    media_type: str
    """MIME type of the data content."""
    data: str | None = None
    """Incremental base64-encoded data, mutually exclusive with `url`."""
    url: str | None = None
    """URL pointing to the data, mutually exclusive with `data`."""

    @model_validator(mode="after")
    def validate_data_source(self) -> Self:
        """Ensure exactly one data source is provided."""
        if (self.data is None) == (self.url is None):
            raise ValueError(
                "Exactly one of `data` or `url` must be provided.",
            )
        return self
```

- **`ToolResultEndEvent`**：`state: ToolResultState`（`SUCCESS`/`ERROR`/`INTERRUPTED`/`DENIED`/`RUNNING`），外加 `metadata: dict`。真实定义：

```python
class ToolResultEndEvent(EventBase):
    """Tool result end event."""

    model_config = ConfigDict(use_enum_values=True)

    type: Literal[EventType.TOOL_RESULT_END] = EventType.TOOL_RESULT_END
    """Event type."""
    reply_id: str
    """ID of the reply message this tool result belongs to."""
    tool_call_id: str
    """ID of the corresponding tool call."""
    state: ToolResultState
    """Final execution state of the tool call."""
    metadata: dict[str, Any] = Field(default_factory=dict)
    """Optional metadata attached to the tool result event."""
```

- **`ConfirmResult`**：`confirmed: bool` + `tool_call: ToolCallBlock` + `rules: list[PermissionRule] | None`。注意 `rules` 仅在 `confirmed=True` 时适用，且用户修改权限时填**完整规则**而非引用 `RequireUserConfirmEvent` 里的 suggested_rules。真实定义：

```python
class ConfirmResult(BaseModel):
    """Confirm result for a tool call."""

    confirmed: bool
    """Whether the user confirmed the tool call."""
    tool_call: ToolCallBlock
    """The tool call that was confirmed or rejected."""
    rules: list[PermissionRule] | None = None
    """The allowed permission rules for this tool call. This field is only
    applicable when ``confirmed`` is True. In case user modification is
    needed, complete permission rules are used here instead of references to
    the suggested rules in ``RequireUserConfirmEvent``."""
```

- **`UserInterruptEvent`**：只对 **parked reply** 有意义——中止一个正在等确认/等外部执行的 reply：关闭所有 pending tool call（标 INTERRUPTED + 补 ToolResult）、emit 一条 fallback 消息、以 `INTERRUPTED` 结束，**不进入** reasoning-acting 循环。要打断一个正在活跃生成的 reply，应取消底层 task（Agent 自己走 `CancelledError` 清理）。其 docstring 把这层语义写死：

```python
class UserInterruptEvent(EventBase):
    """User-initiated interrupt targeting a parked reply.

    Delivered to :meth:`Agent.reply_stream` (or :meth:`Agent.reply`) to
    abort a reply that is currently waiting on external input — either
    user confirmation (:class:`RequireUserConfirmEvent`) or external
    execution (:class:`RequireExternalExecutionEvent`).

    On receipt, the agent closes every pending tool call with an
    interrupted tool result, emits a fallback assistant message, ends
    the reply with :attr:`ReplyEndReason.INTERRUPTED`, and does **not**
    enter the reasoning-acting loop.

    .. note:: This event is only meaningful for parked replies. To
        interrupt a running (actively-generating) reply, cancel the
        underlying task instead — the agent handles that path via its
        own ``CancelledError`` cleanup.
    """

    type: Literal[EventType.USER_INTERRUPT] = EventType.USER_INTERRUPT
    """Event type."""
    reply_id: str
    """ID of the reply message this interrupt targets."""
```

- **`CustomEvent`**：服务层中间件用它通知前端状态变化，前端对未知 `name` 应**静默跳过**而非报错。其 docstring 与字段：

```python
class CustomEvent(EventBase):
    """Generic extensible event for signals that don't fit a specific
    ``AgentEvent`` subtype.

    Used by service-layer middleware to notify front-end subscribers
    about state changes (task progress, team membership, permission
    updates, …) without polluting the core agent event enum with
    application-specific types.

    Front-end implementations should handle unknown ``name`` values
    gracefully — skip with no error.

    Attributes:
        name (`str`):
            Identifies the kind of notification. Well-known values:

            - ``"state_updated"`` — agent state (tasks / permission)
              changed during a tool call.
            - ``"team_updated"`` — team membership changed (member
              added / team created or dissolved).
            - ``"mcp_progress"`` — transient MCP tool progress, with
              ``reply_id``, ``tool_call_id``, ``progress``, ``total`` and
              ``message`` in ``value``. Not part of the final tool result.

        value (`dict`):
            Arbitrary JSON-serializable payload whose schema depends
            on ``name``. May be empty.
    """

    type: Literal[EventType.CUSTOM] = EventType.CUSTOM
    """Event type discriminator."""
    name: str
    """Kind of notification — see class docstring for well-known values."""
    value: dict = Field(default_factory=dict)
    """Arbitrary payload."""
```

## AgentEvent Union

`AgentEvent` 是 28 个具体事件的 `TypeAlias` 联合类型，`reply_stream` 的 yield 类型就是它。`Agent` / `GoalPipeline` / App 层全部消费同一个联合类型——这是「pipeline 与 agent 同接口」能在类型层面成立的根。`event/_event.py` 里的真实定义：

```python
AgentEvent: TypeAlias = (
    ReplyStartEvent
    | ReplyEndEvent
    | ExceedMaxItersEvent
    | RequireUserConfirmEvent
    | RequireExternalExecutionEvent
    | ModelCallStartEvent
    | ModelCallEndEvent
    | TextBlockStartEvent
    | TextBlockDeltaEvent
    | TextBlockEndEvent
    | DataBlockStartEvent
    | DataBlockDeltaEvent
    | DataBlockEndEvent
    | ThinkingBlockStartEvent
    | ThinkingBlockDeltaEvent
    | ThinkingBlockEndEvent
    | HintBlockEvent
    | ToolCallStartEvent
    | ToolCallDeltaEvent
    | ToolCallEndEvent
    | ToolResultStartEvent
    | ToolResultTextDeltaEvent
    | ToolResultDataDeltaEvent
    | ToolResultEndEvent
    | UserConfirmResultEvent
    | UserInterruptEvent
    | ExternalExecutionResultEvent
    | CustomEvent
)
```

## HITL Event Flow

HITL 的核心不变量：**Agent 需要确认/外部执行时，不抛异常也不返回结果**，而是 yield 对应事件后停在 await 点。调用方（Web UI / TUI / 上游 Agent / 外部系统）决策后把 *Result 事件作为下一次 `reply_stream` 的输入灌回——同一实例、同一上下文，从断点继续。

```
Agent yields RequireUserConfirmEvent(tool_calls=[...])
   → 调用方收集用户决策 → UserConfirmResultEvent(confirm_results=[...])
   → agent.reply_stream(UserConfirmResultEvent) 继续

Agent yields RequireExternalExecutionEvent(tool_calls=[...]) 并立即 return
   → 外部系统执行 → ExternalExecutionResultEvent(execution_results=[...])
   → agent.reply_stream(ExternalExecutionResultEvent) 继续

任何时刻 → UserInterruptEvent(reply_id)
   → 关闭所有 pending tool call + fallback 消息 + INTERRUPTED 收尾
```

`_check_incoming_event()` 负责状态一致性：若 Agent 在等 2 个工具确认却只回 1 个结果、或回传的 tool id 不在等待列表里，都会报错。

## Types System

支撑类型集中在 `src/agentscope/types/`：

- **`ReplyFinishedReason`**（`types/_reply.py`）：`COMPLETED` / `INTERRUPTED` / `EXCEED_MAX_ITERS` / `ERROR` 四值。
- **`ErrorType`**（`types/_reply.py`）：9 个值——`AUTHENTICATION`/`PERMISSION`/`RATE_LIMIT`/`INVALID_REQUEST`/`UPSTREAM`/`CONNECTION`/`INTERNAL`/`SETUP`/`UNKNOWN`；配套 `ErrorInfo`（仅 `type: ErrorType`——默认 `UNKNOWN`——加 `message: str` **两个字段，没有 `detail` 字段**），仅在 `ReplyEndEvent.error` 里出现。`types/_reply.py` 的真实定义：

```python
class ReplyFinishedReason(StrEnum):
    """The reason a reply finished."""

    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    EXCEED_MAX_ITERS = "exceed_max_iters"
    ERROR = "error"


class ErrorType(StrEnum):
    """Classification of a fatal error that terminated a reply.

    Not model-specific: the status-derived members apply to any upstream
    service reached during a reply (chat model, embedding, TTS, MCP)."""

    AUTHENTICATION = "authentication"
    """401 — credential missing or wrong."""
    PERMISSION = "permission"
    """403 — authenticated but not allowed."""
    RATE_LIMIT = "rate_limit"
    """429 — rate/quota exceeded."""
    INVALID_REQUEST = "invalid_request"
    """400 / 422 — malformed request."""
    UPSTREAM = "upstream"
    """5xx — an upstream service failed."""
    CONNECTION = "connection"
    """Network error / timeout — no HTTP status available."""
    INTERNAL = "internal"
    """Framework bug or otherwise unexpected exception."""
    SETUP = "setup"
    """The run failed before the agent replied at all — assembling the
    agent, its toolkit, its knowledge bases, or resolving its model."""
    UNKNOWN = "unknown"
    """Fallback when no better classification is possible."""


class ErrorInfo(BaseModel):
    """Structured, UI-facing description of a fatal reply error."""

    type: ErrorType = ErrorType.UNKNOWN
    """Stable classification key; the frontend localizes off it."""
    message: str
    """Short, sanitized, human-readable description."""
```

- **`AgentHookTypes`**（`types/_hook.py`）：`pre_reply` / `post_reply` / `pre_observe` / `post_observe` / `pre_print` / `post_print`——这是**旧式 Agent 级 hook** 命名，与中间件 `_base.py` 的 `on_*` 系列（见 [Middleware 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Middleware.md)）**是两套独立的机制**，写笔记时容易混。
- **`ReActAgentHookTypes`**（`types/_hook.py`）：在 `AgentHookTypes` 基础上追加 `pre_reasoning` / `post_reasoning` / `pre_acting` / `post_acting`，是 ReAct Agent 专用的扩展。两个类型的真实定义：

```python
AgentHookTypes = (
    str
    | Literal[
        "pre_reply",
        "post_reply",
        "pre_print",
        "post_print",
        "pre_observe",
        "post_observe",
    ]
)

ReActAgentHookTypes = (
    AgentHookTypes
    | Literal[
        "pre_reasoning",
        "post_reasoning",
        "pre_acting",
        "post_acting",
    ]
)
```

- **`Embedding`**（`types/_object.py`）：就是 `List[float]`，没有更花哨的封装：

```python
Embedding = List[float]
```

## Message System Deep Dive

`Msg`（`src/agentscope/message/_base.py`）是所有事件的「归并目标」。它不是简单容器，而是一个**状态机**：消费 `AgentEvent` 流，把增量事件重建成本地 `content` 里的 block。

### The append_event State Machine

`Msg.append_event(event)`（`_base.py` 内 `match event.type` 大分支）按 block 类型归并：

- `TEXT_BLOCK_*`：按 `block_id` 找/建 `TextBlock`，DELTA 时 `text += delta`，END 时写 `finished_at`。
- `THINKING_BLOCK_*`：同理，`THINKING_BLOCK_DELTA` 时 `thinking += delta`。
- `DATA_BLOCK_DELTA` / `DATA_BLOCK_END`：这是最容易写错的地方（见下）。
- `HINT_BLOCK`：一次性事件，整块 `HintBlock` 直接 append（不流式）。
- `TOOL_CALL_*` / `TOOL_RESULT_*`：按 `tool_call_id` 关联，状态随事件流转（`ToolCallBlock.state` 走 `PENDING→ASKING→ALLOWED→SUBMITTED→FINISHED` 及 `DENIED`/`INTERRUPTED`/`ERROR`；`ToolResultBlock.state` 走 `RUNNING→SUCCESS/ERROR/INTERRUPTED/DENIED`）。

### DataBlock Chunk Merging

`DATA_BLOCK_DELTA` 的 `data` 字段是**各自独立 base64 编码**的（每个分片带自己的 padding）。`append_event` 在 `message/_base.py` 的处理是 decode → concat bytes → re-encode，真实分支：

```python
                elif event.type == EventType.DATA_BLOCK_DELTA and event.data:
                    # Each delta is an independently base64-encoded chunk
                    # (with its own padding); naive string concat would
                    # corrupt the byte stream. Decode, concat bytes, re-encode.
                    existing = (
                        base64.b64decode(block.source.data)
                        if block.source.data
                        else b""
                    )
                    incoming = base64.b64decode(event.data)
                    block.source.data = base64.b64encode(
                        existing + incoming,
                    ).decode("ascii")
```

若 delta 带的是 `url`，则整块替换为 `URLSource`（url 是完整内容，直接替代 start 事件创建的空 base64 source）。**任何自己拼事件的代码都必须走 decode→concat→re-encode，直接字符串拼接会破坏字节流**——base64 padding 会跨分片截断，这与 model 层 `_StreamAccumulator` 的取舍一致。

v2.0.11 的精化在于**按 `event.block_id` 定位同 id 的 DataBlock**（`message/_base.py`）：找到同 id 分片才拼接，否则 append 新块；生产端也真的传 `block_id=block.id`，`event/_event.py` 里 `DataBlockDeltaEvent` 的字段带默认工厂。这解决的是「多个 DataBlock 并存于同一条 Msg 时把上一个块的尾部当成当前块前缀」的串台问题，**不是首次实现 decode→concat→re-encode**。工具结果里按 `block_id` 找同 id 分片的真实源码：

```python
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

另外 CUSTOM 事件现在直接 `return self`、不参与 Msg 重建，`mcp_progress` 这类旁路事件因此不会污染重建结果。`EventType` 仍是 28 个值，v2.0.8 → v2.0.11 零新增。

### Block Taxonomy

`src/agentscope/message/_block.py` 定义的内容块：

- `TextBlock`（流式文本）、`ThinkingBlock`（`extra="allow"`，可携带模型签名）、`DataBlock`（`Base64Source` | `URLSource`，多模态）、`HintBlock`（一次性提示，可多模态）。
- `ToolCallBlock`：`state: ToolCallState`（`PENDING`/`ASKING`/`ALLOWED`/`SUBMITTED`/`FINISHED`）+ `suggested_rules`。
- `ToolResultBlock`：`state: ToolResultState`（`SUCCESS`/`ERROR`/`INTERRUPTED`/`DENIED`/`RUNNING`）+ `metadata`。

### Query Helpers

`Msg` 提供：`has_content_blocks()`（content 是否非空）、`get_text_content()`（把所有文本块拼成字符串）、`get_content_blocks()`（overloaded，按类型取块）、`_find_block(kind, id)`（状态机内部按 `block_id` 定位）。`append_usage()` 把 `ModelCallEndEvent` 的 token 计数累加进 `Msg.usage`。

## Source Module Map

v2.0.11 的真实布局，先厘清几处易混的模块名（任何自己拼事件/消息的代码都按这个路径 import）：

- `pipeline/__init__.py` 只导出 `PipelineProtocol`（来自 `pipeline/_base.py`）与 `GoalPipeline`（来自 `pipeline/_goal_pipeline.py`）两个符号，**没有**独立的 `pipeline/_pipeline_protocol.py`。
- `Msg` 类定义在 `message/_base.py`（**不是** `message/_msg.py`），`append_event` 是该文件的方法。`message/_block.py` 只定义内容块与状态枚举。
- 全部事件在 `event/_event.py`：`EventType`、各 `AgentEvent` 子类、以及 `AgentEvent` 联合类型。
- 支撑类型在 `types/`：`_reply.py`（`ReplyFinishedReason` / `ErrorType` / `ErrorInfo`）、`_hook.py`（`AgentHookTypes` / `ReActAgentHookTypes`）、`_object.py`（`Embedding`）。
- `TeamPipeline`（在 `pipeline/_team_pipeline.py`，Leader 委派 `TeamMember`）**在 v2.0.11 是正式导出成员**，只是不显式继承 `PipelineProtocol`，靠结构化匹配；`pipeline/` 目录现有 `__init__.py` / `_base.py` / `_goal_pipeline.py` / `_team_pipeline.py` 四个文件。它是 **v2.0.9** 引入（见主干 Version Evolution），不是旧笔记写的 v2.0.10。

## EventType Full Enumeration

`EventType`（`event/_event.py`）是 `StrEnum`，**共 28 个值**。下面按源码顺序逐一列出，每个值对应一个 `EventBase` 子类：

| # | `EventType` 值 | 事件类 | 备注 |
| :--- | :--- | :--- | :--- |
| 1 | `REPLY_START` | `ReplyStartEvent` | 带 `session_id`/`reply_id`/`name`/`role` |
| 2 | `REPLY_END` | `ReplyEndEvent` | 带 `finished_reason` + 可选 `error` |
| 3 | `MODEL_CALL_START` | `ModelCallStartEvent` | 带 `model_name` |
| 4 | `MODEL_CALL_END` | `ModelCallEndEvent` | 4 个 token 计数 |
| 5 | `TEXT_BLOCK_START` | `TextBlockStartEvent` | |
| 6 | `TEXT_BLOCK_DELTA` | `TextBlockDeltaEvent` | `delta: str` |
| 7 | `TEXT_BLOCK_END` | `TextBlockEndEvent` | `text` 仅在「非拼接」时填充 |
| 8 | `DATA_BLOCK_START` | `DataBlockStartEvent` | 带 `media_type` |
| 9 | `DATA_BLOCK_DELTA` | `DataBlockDeltaEvent` | `data`/`url` 互斥 |
| 10 | `DATA_BLOCK_END` | `DataBlockEndEvent` | |
| 11 | `THINKING_BLOCK_START` | `ThinkingBlockStartEvent` | |
| 12 | `THINKING_BLOCK_DELTA` | `ThinkingBlockDeltaEvent` | `delta: str` |
| 13 | `THINKING_BLOCK_END` | `ThinkingBlockEndEvent` | |
| 14 | `HINT_BLOCK` | `HintBlockEvent` | 一次性，非流式 |
| 15 | `TOOL_CALL_START` | `ToolCallStartEvent` | |
| 16 | `TOOL_CALL_DELTA` | `ToolCallDeltaEvent` | `delta` 是 JSON 片段 |
| 17 | `TOOL_CALL_END` | `ToolCallEndEvent` | |
| 18 | `TOOL_RESULT_START` | `ToolResultStartEvent` | |
| 19 | `TOOL_RESULT_TEXT_DELTA` | `ToolResultTextDeltaEvent` | |
| 20 | `TOOL_RESULT_DATA_DELTA` | `ToolResultDataDeltaEvent` | `data`/`url` 互斥 |
| 21 | `TOOL_RESULT_END` | `ToolResultEndEvent` | 带 `state: ToolResultState` |
| 22 | `EXCEED_MAX_ITERS` | `ExceedMaxItersEvent` | `@deprecated`，仍 emit 无语义 |
| 23 | `REQUIRE_USER_CONFIRM` | `RequireUserConfirmEvent` | 带 `tool_calls` |
| 24 | `REQUIRE_EXTERNAL_EXECUTION` | `RequireExternalExecutionEvent` | 带 `tool_calls` |
| 25 | `USER_CONFIRM_RESULT` | `UserConfirmResultEvent` | 带 `confirm_results` |
| 26 | `USER_INTERRUPT` | `UserInterruptEvent` | 仅带 `reply_id` |
| 27 | `EXTERNAL_EXECUTION_RESULT` | `ExternalExecutionResultEvent` | 带 `execution_results` |
| 28 | `CUSTOM` | `CustomEvent` | `name` + `value` 扩展槽 |

计数核对：Reply 2 + Model 2 + Text 3 + Data 3 + Thinking 3 + Hint 1 + ToolCall 3 + ToolResult 4 + IterCap 1 + HITL 2 + HITLResult 3 + Custom 1 = **28**。`AgentEvent`（`event/_event.py`）正是这 28 个类的 `TypeAlias` 联合，与上面一一对应。

## append_event reply_id Guard

`Msg.append_event(event)`（`message/_base.py`）是「状态机式增量重建」的落地方法，但它**不是无差别吞下所有事件**：方法入口先校验 `event.reply_id != self.id`，不匹配就 `logger.warning(...)` 后直接 `return`。这就是「按 reply_id 归并」的硬机制——多条并发 reply 的事件流可以被交错喂给各自对应的 `Msg`，每条 `Msg` 只吸收属于自己 `reply_id` 的那一份，从而从一条混流里重建出多条独立 `Msg`（TUI、HITL 恢复都依赖这一点）。`message/_base.py` 里的入口与 `REPLY_END` / `MODEL_CALL_END` 分支：

```python
        if event.type == EventType.CUSTOM:
            return self

        if event.reply_id != self.id:
            logger.warning(
                "Event %s with reply_id %r does not match message id %r, "
                "skipping.",
                event.__class__.__name__,
                event.reply_id,
                self.id,
            )
            return self

        match event.type:
            case EventType.REPLY_END:
                self.finished_at = event.created_at
                # ``event.finished_reason`` is a bare string (EventBase sets
                # ``use_enum_values``); coerce back to the enum so this
                # field serializes cleanly.
                self.finished_reason = ReplyFinishedReason(
                    event.finished_reason,
                )
                self.error = event.error

            case EventType.MODEL_CALL_END:
                self.append_usage(
                    Usage(
                        input_tokens=event.input_tokens,
                        output_tokens=event.output_tokens,
                        cache_input_tokens=event.cache_input_tokens,
                        cache_creation_input_tokens=(
                            event.cache_creation_input_tokens
                        ),
                    ),
                )
```

`REPLY_END` 分支的三个动作值得单独记，因为它们解释了 `Msg` 上几个关键字段的来源：

- `self.finished_at = event.created_at`——用事件时间戳盖戳。
- `self.finished_reason = ReplyFinishedReason(event.finished_reason)`——**注意这里做了一次显式 coerce**：因为 `EventBase` 设置了 `use_enum_values=True`，`event.finished_reason` 到达时已是**裸字符串**而非枚举，必须用 `ReplyFinishedReason(...)` 包回枚举，字段才能干净序列化（上面注释原话）。
- `self.error = event.error`——仅在 `finished_reason == ERROR` 时事件才带非 `None` 的 `error`。

`MODEL_CALL_END` 分支则把 `input_tokens` / `output_tokens` / `cache_input_tokens` / `cache_creation_input_tokens` 累加进 `Msg.usage`（`append_usage`）。找不到目标的 block 级事件（如 `block_id` 未知的 `TEXT_BLOCK_DELTA`）同样 `logger.warning` 后跳过，不会抛异常。

## ToolCallState and ToolResultState

工具调用在流式事件里的状态机由 `_block.py` 的两个 `StrEnum` 收口，二者是 `append_event` 里 `TOOL_CALL_*` / `TOOL_RESULT_*` / HITL 分支翻转的对象。`message/_block.py` 里的真实定义：

```python
class ToolCallState(StrEnum):
    """The state of the tool call."""

    PENDING = "pending"
    ASKING = "asking"
    ALLOWED = "allowed"
    SUBMITTED = "submitted"
    FINISHED = "finished"
```

`ToolResultState` 是同一文件里另一个独立的枚举（两者之间隔着 `ToolCallBlock` / `ToolResultBlock` 定义，故分块贴出）：

```python
class ToolResultState(StrEnum):
    """The tool result state."""

    SUCCESS = "success"
    ERROR = "error"
    INTERRUPTED = "interrupted"
    DENIED = "denied"
    RUNNING = "running"
```

- **`ToolCallState`**：`PENDING` / `ASKING` / `ALLOWED` / `SUBMITTED` / `FINISHED` 五值。完整转移图见 `ToolCallBlock.state` 的 docstring（`message/_block.py`）：`pending` 经权限判定 → `asking`（需确认）或 `allowed`；`asking` 经用户决策 → `allowed`（批准）或 `finished`（拒绝）；`allowed` 本地工具直接 `finished`、外部工具 → `submitted`；`submitted` 等 `ExternalExecutionResultEvent` → `finished`。该 docstring 的转移图原文：

```python
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

- **`ToolResultState`**：`SUCCESS` / `ERROR` / `INTERRUPTED` / `DENIED` / `RUNNING` 五值，是 `ToolResultBlock.state` 的取值，`ToolResultEndEvent.state` 同此枚举。

这些状态在 `append_event` 里被翻转的位置（均位于 `message/_base.py`）：

- `REQUIRE_USER_CONFIRM` → 对应 `ToolCallBlock.state = ASKING`；
- `USER_CONFIRM_RESULT` → `ALLOWED`（批准）或 `FINISHED`（拒绝），且仅当当前为 `ASKING` 才转移；
- `REQUIRE_EXTERNAL_EXECUTION` → `SUBMITTED`；
- `TOOL_RESULT_END` → 把**配对**的 `ToolCallBlock` 一并置为 `FINISHED`，使 SSE 重建出的 `Msg` 与 `agent.state.context` 一致；
- `EXTERNAL_EXECUTION_RESULT` → 直接把 `ToolResultBlock` 拼入 `content`，并对已存在同 id 的结果去重。

其中「配对翻转」与「确认转移」的真实源码：

```python
                else:
                    assert isinstance(block, ToolResultBlock)
                    block.state = event.state
                    block.metadata = event.metadata
                    block.finished_at = event.created_at
                    # The paired ToolCallBlock's lifecycle ends with its
                    # result — flip it to FINISHED here so the SSE-rebuilt
                    # reply_msg matches ``agent.state.context``, which
                    # ``_update_tool_call_state`` mutates directly.
                    call_block = self._find_block(
                        "tool_call",
                        event.tool_call_id,
                    )
                    if call_block is not None:
                        assert isinstance(call_block, ToolCallBlock)
                        call_block.state = ToolCallState.FINISHED

            case EventType.REQUIRE_USER_CONFIRM:
                for tool_call in event.tool_calls:
                    b = self._find_block("tool_call", tool_call.id)
                    if b is not None:
                        assert isinstance(b, ToolCallBlock)
                        # Update the state
                        b.state = ToolCallState.ASKING
                        # Record the suggestions
                        b.suggested_rules = tool_call.suggested_rules

            case EventType.USER_CONFIRM_RESULT:
                for result in event.confirm_results:
                    b = self._find_block("tool_call", result.tool_call.id)
                    # Only ASKING calls can transition; skip stale results
                    # (e.g. arriving after an interrupt already resolved the
                    # tool call).
                    if b is not None and b.state == ToolCallState.ASKING:
                        assert isinstance(b, ToolCallBlock)
                        b.state = (
                            ToolCallState.ALLOWED
                            if result.confirmed
                            else ToolCallState.FINISHED
                        )
```

## Links

- [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)
- [Agent 理论](/docs/CS/AI/LLM/Agent/Theory/Agent.md)
- [Middleware 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Middleware.md)
- [App 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/App.md)
- [AgentLoop](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentLoop.md) / [SOP](/docs/CS/AI/LLM/Agent/Product/AgentScope/SOP.md) / [TUI](/docs/CS/AI/LLM/Agent/Product/AgentScope/TUI.md) / [Memory](/docs/CS/AI/LLM/Agent/Product/AgentScope/Memory.md)

## References

- [AgentScope v2.0.11 — pipeline/](https://github.com/agentscope-ai/agentscope/tree/v2.0.11/src/agentscope/pipeline)
- [AgentScope v2.0.11 — message/_base.py](https://github.com/agentscope-ai/agentscope/blob/v2.0.11/src/agentscope/message/_base.py)
- `src/agentscope/pipeline/_goal_pipeline.py` / `_team_pipeline.py`
- `src/agentscope/event/_event.py`
- `src/agentscope/message/_base.py`
- `src/agentscope/types/_reply.py` / `_hook.py` / `_object.py`
- `src/agentscope/tool/_types.py`
