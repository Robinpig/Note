## Introduction

AgentScope 把「终端」当成一等客户端：v2.0.9 起新增基于 Textual 的全屏 `tui/`，v2.0.8 就有的 `console/` 则保留轻量的 rich 逐行渲染。两者**完全独立**，共享的只有 `Msg.append_event()` 这套事件重建协议与 Agent 的 HITL 事件。本分册核验三种启动器各自的驱动模型、增量渲染链与 HITL 交互面。

> 版本基线：v2.0.11（`src/agentscope/tui/` 5 文件、`src/agentscope/console/` 3 文件）

三个反直觉点：

1. **HITL 的「四个选项」会缩成一个**：当 tool call 处于 `SUBMITTED`（`waiting_external`，即外部执行中）时，allow / always / deny 三个候选都不生成，只剩 Interrupt reply。
2. **`launch_tui` 与 `launch_realtime_ui` 的并发模型相反**：前者每次提交起一个 `reply_stream()` 并用锁串行，后者在 `on_mount` 起**单个** `reply_stream(transport)` 跑满整个会话。
3. **TUI 与 Agent 层完全解耦**：`_publish()` 只靠 `Msg.append_event()` 按 `reply_id` 归并事件，不 import Agent 内部方法——这正是事件重建能力在客户端侧收到的回报。

## Three Launchers, Three Driving Models

| 启动器 | 位置 | 驱动模型 |
| :--- | :--- | :--- |
| `launch_tui(target, *, messages, user_name)` | `tui/_launcher.py` → `_AgentScopeTUI.run_async()` | 每次提交一个 `reply_stream()`，`_reply_lock` 串行 |
| `launch_realtime_ui(agent, transport, *, messages, user_name)` | `tui/_launcher.py` → `_RealtimeTUI.run_async()` | `on_mount` 起单个 `reply_stream(transport)` 跑满会话 |
| `launch_console(agent, user_name, verbosity, max_tool_result_lines)` | `console/_console.py` | stdin 循环 + `ConsoleRenderer` 逐行 rich 输出 |

两个 TUI 启动器都是薄封装，真正的应用类各自 `run_async()`（`tui/_launcher.py`）：

```python
# tui/_launcher.py
async def launch_tui(
    target: Agent | PipelineProtocol,
    *,
    messages: Sequence[Msg] = (),
    user_name: str = "user",
) -> None:
    """Launch a full-screen interactive terminal chat.

    Args:
        target (`Agent | PipelineProtocol`):
            Agent or pipeline whose ``reply_stream`` consumes user messages
            and HITL continuation events.
        messages (`Sequence[Msg]`, optional):
            Historical messages displayed before live interaction starts.
        user_name (`str`, defaults to ``"user"``):
            Name assigned to messages submitted from the composer.
    """
    await _AgentScopeTUI(target, messages, user_name).run_async()
```

```python
# tui/_launcher.py
async def launch_realtime_ui(
    agent: RealtimeAgent,
    transport: TransportBase,
    *,
    messages: Sequence[Msg] = (),
    user_name: str = "user",
) -> None:
    """Launch a full-screen terminal view of a voice session.

    Both the agent and the transport are borrowed: they must already be
    started, and neither is closed here.
```

（后一段只摘到 docstring 的前几句；`Args` 与末尾的 `await _RealtimeTUI(...).run_async()` 省略。）

`launch_realtime_ui` 的 docstring 明确 agent 与 transport 都是 **borrowed**，不在此关闭（`tui/_launcher.py`）；文本输入是否可用取决于 `input_enabled = agent.model.supports_text_input`（`tui/_launcher.py`）：

```python
# tui/_launcher.py
        super().__init__(
            messages,
            user_name,
            input_enabled=agent.model.supports_text_input,
        )
```

`_RealtimeTUI._consume` 会过滤掉 `DataBlockStart/Delta/EndEvent` 不渲染，只显示转录文本（`tui/_launcher.py`）：

```python
# tui/_launcher.py
    def on_mount(self) -> None:
        # Audio flows for as long as the transport lives, so the session is
        # one stream, started here, rather than one per submission.
        self._spawn(self._consume())

    async def _consume(self) -> None:
        try:
            async for event in self.agent.reply_stream(self.transport):
                # The transport plays the reply; the view shows what was
                # said, so the audio blocks are of no use here.
                if isinstance(
                    event,
                    (
                        DataBlockStartEvent,
                        DataBlockDeltaEvent,
                        DataBlockEndEvent,
                    ),
                ):
                    continue
                await self._publish(event)
            # The stream ends with the transport, and there is no second
            # way in: nothing is left to show.
            self.exit()
```

## Serialization and the Single Stream

`launch_tui` 的链路是 `_submit` → `_start_stream` → `_consume` → `self.target.reply_stream(inputs)`（`tui/_launcher.py`），用 `_reply_lock = asyncio.Lock()` 串行化，避免并发回复改坏同一条上下文；另有 `_reply_tasks` 支持按 `reply_id` 精确 cancel。

```python
# tui/_launcher.py
    def __init__(
        self,
        target: Agent | PipelineProtocol,
        messages: Sequence[Msg],
        user_name: str,
    ) -> None:
        super().__init__(messages, user_name)
        self.target = target
        self._reply_tasks: dict[str, asyncio.Task[None]] = {}
        self._reply_lock = asyncio.Lock()
```

```python
# tui/_launcher.py
    async def _consume(self, inputs: _TUIInput) -> None:
        if isinstance(inputs, Msg):
            await self._publish(inputs)
        async with self._reply_lock:
            task = asyncio.current_task()
            owned_reply_ids: set[str] = set()
            if not isinstance(inputs, Msg) and task is not None:
                self._reply_tasks[inputs.reply_id] = task
                owned_reply_ids.add(inputs.reply_id)
            try:
                if isinstance(inputs, UserConfirmResultEvent):
                    await self._publish(inputs)
                async for item in self.target.reply_stream(inputs):
                    if isinstance(item, ReplyStartEvent) and task is not None:
                        self._reply_tasks[item.reply_id] = task
                        owned_reply_ids.add(item.reply_id)
                    await self._publish(item)
            # The standalone UI must keep running if its target fails.
            # pylint: disable-next=broad-exception-caught
            except Exception as error:
                logger.exception("TUI reply stream failed")
                self.notify(str(error), title="Agent error", severity="error")
            finally:
                for reply_id in owned_reply_ids:
                    if self._reply_tasks.get(reply_id) is task:
                        self._reply_tasks.pop(reply_id, None)
```

`launch_realtime_ui` 在 `on_mount` 起**单个** `_consume()`（`tui/_launcher.py`），流一结束就 `self.exit()`。这与 `RealtimeAgent.reply_stream` 的全局单例约束一致——已有活跃流时直接 `raise RuntimeError`（`agent/_realtime/_agent.py`），且 `WebRTCSession._run()` 同样只起一个流。

```python
# agent/_realtime/_agent.py
    async def reply_stream(
        self,
        transport: TransportBase,
    ) -> AsyncIterator[AgentEvent]:
        """Pump *transport* and yield agent events until it ends.

        The transport is borrowed, not owned: it must already be started
        and is not closed here, so the caller can keep it, reuse it or hand
        it on. The stream ends when the transport's input ends — a client
        disconnecting — not when a reply ends; there may be many replies.
        Call again with a new transport to resume the same session.

        Breaking out of the loop early does not run cleanup immediately;
        wrap the generator in :func:`contextlib.aclosing` when that
        matters.
        """
        if self._transport is not None:
            raise RuntimeError("RealtimeAgent.reply_stream is already active.")
```

## Event Replay into Widgets

`_publish()`（`tui/_launcher.py`）按 `reply_id` 归并：命中 `_replies` 或回填历史 `Msg`，找不到时新建 `UserMsg` / `AssistantMsg`，然后 `message.append_event(item)`（`tui/_launcher.py`）。注意它**不只是**调用 `append_event`——还要维护 `_replies` 字典并在缺 reply 时补建消息。

```python
# tui/_launcher.py
    async def _publish(self, item: Msg | AgentEvent) -> None:
        """Fold one item of a stream into the open replies and render it."""
        if isinstance(item, Msg):
            message = item.model_copy(deep=True)
            if message.role == "assistant" and message.finished_at is None:
                self._replies[message.id] = message
        else:
            reply_id = getattr(item, "reply_id", None)
            if reply_id is None:
                return
            # An ended reply can still receive events, e.g. a spoken turn's
            # transcript trails its end, so continue from its shown copy.
            message = self._replies.get(reply_id) or next(
                (
                    msg.model_copy(deep=True)
                    for msg in reversed(
                        self.query_one(MessagesUI).current_messages(),
                    )
                    if msg.id == reply_id
                ),
                None,
            )
            if message is None:
                # A reply resumed after a confirmation gets no
                # ReplyStartEvent, so open one here as well.
                start = item if isinstance(item, ReplyStartEvent) else None
                if start is not None and start.role == "user":
                    message = UserMsg(name=start.name, content=[], id=reply_id)
                else:
                    message = AssistantMsg(
                        name=start.name if start else "agent",
                        content=[],
                        id=reply_id,
                    )
            self._replies[reply_id] = message
            if isinstance(item, ReplyStartEvent):
                message.name = item.name
            else:
                message.append_event(item)
```

（方法末尾还有 `ChatUI.update_message()` 与 `_replies.pop(...)` 的收尾，此处省略。）

增量渲染链（`_publish` → `ChatUI.update_message()` → `MessagesUI.update_message()` → `MessageUI.apply(message)` → `widget.replace(block)`）落在 `tui/_chat.py`、`tui/_messages.py`。`apply()` 用 `_group_tool_calls()` 生成的 `old_keys/new_keys` 做 key-diff：相同则 retain，同类型则 `replace`，否则 mount 新 widget（`tui/_messages.py`）：

```python
# tui/_messages.py
        old_blocks = _group_tool_calls(previous.content)
        new_blocks = _group_tool_calls(message.content)
        old_keys = [
            tuple(pair.call.id for pair in block.calls)
            if isinstance(block, _ToolGroup)
            else block.id
            for block in old_blocks
        ]
        new_keys = [
            tuple(pair.call.id for pair in block.calls)
            if isinstance(block, _ToolGroup)
            else block.id
            for block in new_blocks
        ]
        old_by_key = dict(zip(old_keys, old_blocks))
        old_widgets = set(self._block_uis.values())
        next_widgets: dict[str, object] = {}
        retained: set[Widget] = set()
        ordered: list[Widget] = []
        for key, block in zip(new_keys, new_blocks):
            block_id = key[0] if isinstance(key, tuple) else key
            widget = self._block_uis.get(block_id)
            old_block = old_by_key.get(key)
            if isinstance(widget, Widget) and old_block == block:
                pass
```

相同 key 直接 retain；同类型走各自的 `replace()`，找不到旧 widget 则由 `_make_block_ui()` 新建后 `await self.mount(widget)`（同一循环的后续分支）。`TextBlockUI.replace()` 更细——借 `Markdown.get_stream()` 只写增量后缀 `text[len(self._text):]`，只有非前缀时才 `update(text)` 全量刷（`tui/_messages.py`）：

```python
# tui/_messages.py
    def on_mount(self) -> None:
        if not self._finished:
            self._stream = Markdown.get_stream(self)

    async def replace(self, block: TextBlock) -> None:
        text = block.text
        if self._stream is not None and text.startswith(self._text):
            await self._stream.write(text[len(self._text) :])
            if block.finished_at is not None:
                await self._stream.stop()
                self._stream = None
        else:
            if self._stream is not None:
                await self._stream.stop()
                self._stream = None
            await self.update(text)
        self._text = text
        self._finished = block.finished_at is not None
```

## HITL: Four Options That Shrink

TUI 侧仍是 4 个候选（`tui/_chat.py`）：`Allow once` / `Always allow with {rules}`（仅 `suggested_rules` 非空时出现）/ `Deny` / `Interrupt reply`。但 `waiting_external`（`ToolCallState.SUBMITTED`）时前三个都不生成，只剩 Interrupt（`tui/_chat.py`）——因为此时 Agent 已经把本轮推理结束、在等外部执行结果，权限决策早就做完了。

```python
# tui/_chat.py
    def _render_current(self) -> None:
        _, agent_name, tool_call = self._pending[0]
        waiting_external = tool_call.state == ToolCallState.SUBMITTED
```

```python
# tui/_chat.py
        options = self.query_one(OptionList)
        choice_specs: list[tuple[str, str]] = []
        if not waiting_external:
            choice_specs.append(("Allow once", "allow"))
            if tool_call.suggested_rules:
                rules = "; ".join(
                    f"{rule.behavior.value} {rule.tool_name}"
                    + (f" ({rule.rule_content})" if rule.rule_content else "")
                    for rule in tool_call.suggested_rules
                )
                choice_specs.append(
                    (f"Always allow with {rules}", "always"),
                )
            choice_specs.append(("Deny", "deny"))
        choice_specs.append(("Interrupt reply", "interrupt"))
```

（两段同出自 `_render_current()`，中间省略了标题与工具入参的渲染代码。）

v2.0.11 对 `_chat.py` / `_ask_user.py` 的主要改动是把 pending 标识从 `tool_call.id` 升级成 `(reply_id, tool_call.id)` 元组（`tui/_chat.py`），并给 `AskUser` 加了 `→` 切题键。这样同一个工具 id 在不同 reply 里不会串台。

```python
# tui/_chat.py
    def _pending_tools(self) -> list[tuple[str, str, ToolCallBlock]]:
        pending: list[tuple[str, str, ToolCallBlock]] = []
        pending_calls: set[tuple[str, str]] = set()
        for message in self._current_messages():
            if message.role != "assistant" or message.finished_at is not None:
                continue
            for block in message.content:
                if isinstance(block, ToolCallBlock) and block.state in (
                    ToolCallState.ASKING,
                    ToolCallState.SUBMITTED,
                ):
                    call = (message.id, block.id)
                    pending_calls.add(call)
                    if call not in self._dismissed_calls:
                        pending.append((message.id, message.name, block))
        self._dismissed_calls.intersection_update(pending_calls)
        return pending
```

## Two Independent HITL Implementations

| 维度 | `tui/` | `console/` |
| :--- | :--- | :--- |
| 交互面 | Textual `OptionList` 四选项（`tui/_chat.py`） | stdin 文本 `[y]es` / `[N]o` + 条件 `[a]lways`（`console/_console.py`） |
| 中断 | 界面按钮 / Ctrl+C | `loop.add_signal_handler(SIGINT, task.cancel)`（`console/_console.py`） |
| 事件归并 | `_publish()` 用 `append_event`（`tui/_launcher.py`） | `ConsoleRenderer` 同样 `msg.append_event(event)`（`console/_renderer.py`） |
| 渲染 | widget key-diff 增量 | rich 逐行输出，无 widget diff |

console 侧的确认提示与 SIGINT 钩子（`console/_console.py`）：

```python
# console/_console.py
        prompt = f"Allow '{tool_call.name}'? [y]es / [N]o"
        if tool_call.suggested_rules:
            prompt += " / [a]lways"
        answer = (await asyncio.to_thread(input, f"{prompt} ")).strip().lower()
```

```python
# console/_console.py
    task = asyncio.ensure_future(consume())
    loop = asyncio.get_running_loop()
    try:
        loop.add_signal_handler(signal.SIGINT, task.cancel)
        sigint_hooked = True
```

`ConsoleRenderer` 同样用 `msg.append_event(event)` 归并（`console/_renderer.py`）：

```python
# console/_renderer.py
        reply_id = getattr(event, "reply_id", None)
        if reply_id is None:
            return
        msg = self._active_msgs.get(reply_id)
        if msg is None:
            if self._msg is not None and self._msg.id == reply_id:
                msg = self._msg
            else:
                msg = AssistantMsg(name="agent", content=[], id=reply_id)
        if isinstance(event, ReplyStartEvent):
            msg.name = event.name
        self._msg = msg
        msg.append_event(event)
        # Keep paused replies across member events, without retaining every
        # completed reply for the lifetime of the interactive console.
        if msg.finished_at is None:
            self._active_msgs[reply_id] = msg
        else:
            self._active_msgs.pop(reply_id, None)
```

v2.0.11 给 console 补了 `ConsoleRenderer.reset()`，在 `reply_stream` 抛异常时清 `_active_msgs`、断行（`console/_renderer.py`、`console/_console.py`）：

```python
# console/_console.py
        except BaseException:
            # Failed streams may omit REPLY_END for several participants.
            pending = None
            renderer.reset()
            raise
```

```python
# console/_renderer.py
    def reset(self) -> None:
        """Release all accumulated messages and end any streamed line.

        Call this when abandoning a stream or when it raises without a
        ``ReplyEndEvent``. ``last_msg`` becomes ``None``. Do not reset on a
        normal HITL pause: its pending replies are needed when resuming.
        """
        self._active_msgs.clear()
        self._msg = None
        self._break_line(quiet_ok=True)
```

`tui/__init__.py` 用 `try/except ImportError` 捕获 `textual` 缺失并提示 `pip install "agentscope[tui]"`：

```python
# tui/__init__.py
try:
    from ._chat import ChatUI
    from ._launcher import launch_realtime_ui, launch_tui
    from ._messages import MessagesUI
except ImportError as error:
    if error.name == "textual":
        raise ImportError(
            'Install TUI support with: pip install "agentscope[tui]"',
        ) from error
    raise
```

## Links

- [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)
- [AgentLoop 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentLoop.md)
- [Pipeline 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Pipeline.md)
- [VoiceStack 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/VoiceStack.md)
- [App 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/App.md)
- [Memory 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Memory.md)

## References

- [AgentScope v2.0.11 — tui/_launcher.py](https://github.com/agentscope-ai/agentscope/blob/v2.0.11/src/agentscope/tui/_launcher.py)
- [AgentScope v2.0.11 — tui/_messages.py](https://github.com/agentscope-ai/agentscope/blob/v2.0.11/src/agentscope/tui/_messages.py)
- [AgentScope v2.0.11 — tui/_chat.py](https://github.com/agentscope-ai/agentscope/blob/v2.0.11/src/agentscope/tui/_chat.py)
- [AgentScope v2.0.11 — console/_console.py](https://github.com/agentscope-ai/agentscope/blob/v2.0.11/src/agentscope/console/_console.py)
- [AgentScope v2.0.11 — pyproject.toml](https://github.com/agentscope-ai/agentscope/blob/v2.0.11/pyproject.toml)
