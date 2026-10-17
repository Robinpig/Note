## Introduction

AgentScope 把「一个 Agent 怎么跑」和「一串 Agent 怎么编排」用同一套接口表达：`PipelineProtocol` 只暴露 `reply_stream()`，和 `Agent.reply_stream()` 返回完全相同的 `AgentEvent` 流。这意味着 pipeline 可以无缝嵌进另一条 pipeline、被另一个 Agent 调用、或者挂在 Agent Service 的多租户会话里。

本分册聚焦四件事：**Pipeline 协议与 GoalPipeline 实现**、**强类型事件系统（28 个 EventType）**、**支撑类型（ReplyFinishedReason / ErrorInfo / Hook 类型）**、以及 **Msg 的状态机式增量重建**（尤其是 DataBlock 的 base64 拼接陷阱）。它们合起来构成 AgentScope 的「事件织物」，上层 ReAct 循环、中间件、HITL、App 层全部建立在这之上。主干 Agent 机制见 [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)。

## Pipeline Protocol

`PipelineProtocol` 定义在 `src/agentscope/pipeline/_base.py`，是一个 `Protocol`（结构化子类型，不靠继承）：

```python
class PipelineProtocol(Protocol):
    def reply_stream(
        self,
        inputs: ...,
    ) -> AsyncGenerator[AgentEvent | Msg, None]: ...
```

只有**一个**方法 `reply_stream`，签名与 `Agent.reply_stream` 对齐。注意方法体用的是 `def` 而非 `async def`——因为 `Protocol` 只描述结构，`def` 能同时匹配同步与异步实现；`GoalPipeline` 自身用 `async def` 提供真正的异步生成器。

`src/agentscope/pipeline/__init__.py` 只导出 `PipelineProtocol` 和 `GoalPipeline` 两个名字，没有其它内置 pipeline。Team Pipeline 在 v2.0.10 才独立成 `pipeline/_team_pipeline.py`（`Leader` 委派 `Worker`），v2.0.8 只有这两个符号。

## GoalPipeline

`GoalPipeline`（`src/agentscope/pipeline/_goal_pipeline.py:55`）是骨架化逻辑的 executor–verifier 双 Agent 循环，把「目标是否达成」的判断从 prompt 恳求变成硬契约。

### Constructor

```python
GoalPipeline(
    executor: Agent,
    verifier: Agent,
    verifier_reset_context: bool = True,
    max_iters: int = 10,
    max_retries: int = 3,
)
```

- `verifier_reset_context=True`：每轮验证后清掉 verifier 的对话上下文（`state.context.clear()` + `state.summary = ""`），但**工具/任务状态保留**——避免 verifier 记住上一轮细节而放水。
- `max_iters=10`：目标尝试上限；`max_retries=3`：executor/verifier 生成合法结构化输出的重试上限。

### The Two Structured Schemas

循环靠两个 Pydantic 模型收口，二者都是 `result` / `report` 式的「交卷」契约：

- `_ExecutionReport`（`_goal_pipeline.py:22`）：只有 `report: str`。executor 必须把「我做了什么」写成机器可核验的产出说明——文件路径、入口点、运行环境等，好让 verifier 去查。
- `_VerificationResult`（`_goal_pipeline.py:34`）：`result: Literal["pass","fail","impossible"]` + `message: str`。`message` 在失败时解释「缺什么、错在哪、精确到文件:行号」，而不是笼统说「不对」。`impossible` 表示目标本身不可达成，executor 应当立即停手。

### The Iteration Budget Lives On The Instance

关键设计：`self._iters = 0` 挂在**实例**上，不在 `reply_stream` 局部变量里（`_goal_pipeline.py:90`）。源码注释写明理由——**HITL resume 不重置预算**。一次新鲜运行（输入是 `Msg`/`list[Msg]`）会把 `_iters` 清零；而从外部回灌的确认/中断事件不会，因此 parked 之后恢复不会偷偷多给几轮尝试。

### reply_id Routing

`reply_stream` 入参除了 `Msg | list[Msg]`，还接受三类 HITL 事件：`UserConfirmResultEvent` / `UserInterruptEvent` / `ExternalExecutionResultEvent`。这些事件携带 `reply_id`，pipeline 据此把事件路由给正确的那一方（`_goal_pipeline.py:154-161`）：

```python
if inputs.reply_id == self.executor.state.reply_id:
    executor_inputs = inputs
elif inputs.reply_id == self.verifier.state.reply_id:
    verifier_inputs = inputs
else:
    raise ValueError(...)
```

若 `UserInterruptEvent` 落到 verifier 一侧，则把 parked 的对象换成 verifier 并直接 `reply_stream(inputs)` 转发后返回（`_goal_pipeline.py:163-169`）——打断的是正在等待外部输入的 Agent。

### The Loop Body

每轮：先跑 executor（带 `structured_schema=_ExecutionReport`），executor 一旦 yield `RequireExternalExecutionEvent` / `RequireUserConfirmEvent` 就 `break_loop` 跳出，把控制权交还调用方；executor 产出 `Msg` 且 `structured_output` 里有 `report` 才算拿到执行报告。

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

落点对照上文：① `reply_stream` 入参是 `Msg | list[Msg]`，也能吃 HITL 事件（`UserConfirmResultEvent` / `UserInterruptEvent` / `ExternalExecutionResultEvent`）做断点续跑；② 循环预算 `self._iters` 挂在**实例**上——一次新鲜 `Msg` 输入会清零，外部回灌的确认/中断事件不会，因此 parked 后 resume 不会偷偷多给轮次；③ verifier 每轮核验后默认清上下文（`verifier_reset_context=True`），但工具/任务状态保留，避免它记住上一轮细节而放水。Team Pipeline 在 v2.0.10 才独立成 `_team_pipeline.py`（Leader 委派 Worker），v2.0.8 只有 `GoalPipeline` 一个内置 pipeline。

## Event System

AgentScope 的输出是**强类型事件流**，不是裸文本流。全部事件定义在 `src/agentscope/event/_event.py`，核心是 `EventType(StrEnum)` 的 **28 个值**（`:26-67`）。它们按生命周期分组：

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

计数：`2 + 2 + 3 + 3 + 3 + 1 + 3 + 4 + 1 + 2 + 3 + 1 = 28`。

### Why Strong Typing Instead Of Callbacks

`EventBase`（`_event.py:70`）是全部事件的基类，带 `id`（`_generate_id`）、`created_at`（ISO 8601）、`metadata`。每个具体事件都是 Pydantic model，字段静态可查、`use_enum_values=True`。对比 LangGraph 式的 callback / node 钩子，AgentScope 选择把「发生了什么」建模成**可序列化、可重放、可跨进程传递**的事件对象：App 层直接把 `AgentEvent` 推给 WebSocket；TUI 用 `Msg.append_event()` 按 `reply_id` 归并重建消息；HITL 把事件作为下一次 `reply_stream` 的输入灌回——同一套数据结构贯穿本地、服务、终端三种客户端。

### Deprecation Notes

- `ReplyEndReason`（`_event.py:102`）：`@deprecated`，值与 `ReplyFinishedReason` 兼容（`completed`/`interrupted`/`exceed_max_iters`），保留只为向后兼容；新代码应改用 `agentscope.types.ReplyFinishedReason`。
- `ExceedMaxItersEvent`（`_event.py:431`）：`@deprecated`，仍 emit 但无语义；判断迭代超限应读 `ReplyEndEvent.finished_reason == ReplyFinishedReason.EXCEED_MAX_ITERS`。

## Key Event Classes

除了上面的分组，有几个字段值得单独记：

- **`ModelCallEndEvent`**（`_event.py:139`）：四个 token 计数 `input_tokens` / `output_tokens` / `cache_input_tokens` / `cache_creation_input_tokens`（后两个默认 0）。这是后面 token 预算中间件（`ReplyBudgetControlMiddleware`）的唯一数据来源。
- **`DataBlockDeltaEvent`**（`_event.py:213`）：`data` 与 `url` **互斥**，由 `@model_validator(mode="after")` 强制——正好一个来源。
- **`ToolResultEndEvent`**（`_event.py:409`）：`state: ToolResultState`（`SUCCESS`/`ERROR`/`INTERRUPTED`/`DENIED`/`RUNNING`），外加 `metadata: dict`。
- **`ConfirmResult`**（`_event.py:469`）：`confirmed: bool` + `tool_call: ToolCallBlock` + `rules: list[PermissionRule] | None`。注意 `rules` 仅在 `confirmed=True` 时适用，且用户修改权限时填**完整规则**而非引用 `RequireUserConfirmEvent` 里的 suggested_rules。
- **`UserInterruptEvent`**（`_event.py:496`）：只对 **parked reply** 有意义——中止一个正在等确认/等外部执行的 reply：关闭所有 pending tool call（标 INTERRUPTED + 补 ToolResult）、emit 一条 fallback 消息、以 `INTERRUPTED` 结束，**不进入** reasoning-acting 循环。要打断一个正在活跃生成的 reply，应取消底层 task（Agent 自己走 `CancelledError` 清理）。
- **`CustomEvent`**（`_event.py:534`）：服务层中间件用它通知前端状态变化，前端对未知 `name` 应**静默跳过**而非报错。

## AgentEvent Union

`AgentEvent`（`_event.py:568`）是 28 个具体事件的 `TypeAlias` 联合类型，`reply_stream` 的 yield 类型就是它。`Agent` / `GoalPipeline` / App 层全部消费同一个联合类型——这是「pipeline 与 agent 同接口」能在类型层面成立的根。

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
- **`ErrorType`**（`types/_reply.py`）：9 个值；配套 `ErrorInfo`（`ErrorType` + `message` + 可选 `detail`），仅在 `ReplyEndEvent.error` 里出现。
- **`AgentHookTypes`**（`types/_hook.py`）：`pre_reply` / `post_reply` / `pre_observe` / `post_observe` / `pre_print` / `post_print`——这是**旧式 Agent 级 hook** 命名，与中间件 `_base.py` 的 `on_*` 系列（见 [Middleware 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Middleware.md)）**是两套独立的机制**，写笔记时容易混。
- **`ReActAgentHookTypes`**（`types/_hook.py`）：在 `AgentHookTypes` 基础上追加 `pre_reasoning` / `post_reasoning` / `pre_acting` / `post_acting`，是 ReAct Agent 专用的扩展。
- **`Embedding`**（`types/_object.py`）：就是 `List[float]`，没有更花哨的封装。

## Message System Deep Dive

`Msg`（`src/agentscope/message/_base.py`）是所有事件的「归并目标」。它不是简单容器，而是一个**状态机**：消费 `AgentEvent` 流，把增量事件重建成本地 `content` 里的 block。

### The append_event State Machine

`Msg.append_event(event)`（`_base.py` 内 `match event.type` 大分支）按 block 类型归并：

- `TEXT_BLOCK_*`：按 `block_id` 找/建 `TextBlock`，DELTA 时 `text += delta`，END 时写 `finished_at`。
- `THINKING_BLOCK_*`：同理，`THINKING_BLOCK_DELTA` 时 `thinking += delta`。
- `DATA_BLOCK_DELTA` / `DATA_BLOCK_END`：这是最容易写错的地方（见下）。
- `HINT_BLOCK`：一次性事件，整块 `HintBlock` 直接 append（不流式）。
- `TOOL_CALL_*` / `TOOL_RESULT_*`：按 `tool_call_id` 关联，状态随事件流转（`ToolCallBlock.state` 走 `PENDING→ASKING→ALLOWED→SUBMITTED→FINISHED` 及 `DENIED`/`INTERRUPTED`/`ERROR`；`ToolResultBlock.state` 走 `RUNNING→SUCCESS/ERROR/INTERRUPTED/DENIED`）。

### The base64 Concatenation Trap

`DATA_BLOCK_DELTA` 的 `data` 字段是**各自独立 base64 编码**的（每个分片带自己的 padding）。`append_event` 在 `_base.py:340-352` 明确处理：

```python
elif event.type == EventType.DATA_BLOCK_DELTA and event.data:
    # Each delta is an independently base64-encoded chunk
    # (with its own padding); naive string concat would
    # corrupt the byte stream. Decode, concat bytes, re-encode.
    existing = base64.b64decode(block.source.data) if block.source.data else b""
    incoming = base64.b64decode(event.data)
    block.source.data = base64.b64encode(existing + incoming).decode("ascii")
```

若 delta 带的是 `url`，则整块替换为 `URLSource`（url 是完整内容，直接替代 start 事件创建的空 base64 source）。**任何自己拼事件的代码都必须走 decode→concat→re-encode，直接字符串拼接会破坏字节流**。这也呼应了 model 层 `_StreamAccumulator` 对 audio 分片「先 `b64decode` 存 bytes、build 时一次性 encode」的同一取舍（base64 padding 会跨分片截断）。

### Block Taxonomy

`src/agentscope/message/_block.py` 定义的内容块：

- `TextBlock`（流式文本）、`ThinkingBlock`（`extra="allow"`，可携带模型签名）、`DataBlock`（`Base64Source` | `URLSource`，多模态）、`HintBlock`（一次性提示，可多模态）。
- `ToolCallBlock`：`state: ToolCallState`（`PENDING`/`ASKING`/`ALLOWED`/`SUBMITTED`/`FINISHED`）+ `suggested_rules`。
- `ToolResultBlock`：`state: ToolResultState`（`SUCCESS`/`ERROR`/`INTERRUPTED`/`DENIED`/`RUNNING`）+ `metadata`。

### Query Helpers

`Msg` 提供：`has_content_blocks()`（content 是否非空）、`get_text_content()`（把所有文本块拼成字符串）、`get_content_blocks()`（overloaded，按类型取块）、`_find_block(kind, id)`（状态机内部按 `block_id` 定位）。`append_usage()` 把 `ModelCallEndEvent` 的 token 计数累加进 `Msg.usage`。

## Links

- [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)
- [Agent 理论](/docs/CS/AI/LLM/Agent/Theory/Agent.md)
- [Middleware 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Middleware.md)
- [App 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/App.md)

## References

- AgentScope GitHub: https://github.com/modelscope/agentscope
- `src/agentscope/pipeline/_goal_pipeline.py`
- `src/agentscope/event/_event.py`
- `src/agentscope/message/_base.py`
- `src/agentscope/types/_reply.py` / `_hook.py` / `_object.py`
- `src/agentscope/tool/_types.py`
