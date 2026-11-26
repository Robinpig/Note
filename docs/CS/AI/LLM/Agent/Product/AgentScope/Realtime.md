## Introduction

`RealtimeAgent` 是另一个完全不继承 `Agent` 的类：双向语音会话、无 request/reply 边界，turn-taking 状态机夹在实时模型与 transport 之间。本分册聚焦**状态机本身**以及它和核心 `Agent` 的边界；ASR / TTS / 模型家族 / 模型卡 / WebRTC transport 的整体版图归 VoiceStack 分册。

> 版本基线：v2.0.11（`agent/_realtime/_agent.py`、`realtime/`）

三个反直觉点：

1. **`reply_stream` 是全局单例**：已有活跃流时直接 `raise RuntimeError`（`agent/_realtime/_agent.py`），且 transport 是 borrowed、不由 agent 关闭；`_pump_downlink` 遇到 provider 断线**不退出**，只标记 disconnected 等下一句用户音频重连。
2. **状态载体不是枚举，是三个私有 dataclass**：`_Reply(item_id, reply_id, text_started, audio_started)`、`_UserTurn(reply_id, open, speech_ended)`、`_QueuedEvent(event, checkpoint)`，外加 `_reply_id` / `_finished_item` / `_connected`。
3. **`TruncationSupport` 枚举已经不存在**：它 v2.0.9 引入、v2.0.10 连同 `RealtimeModelBase.truncation` 一起删除；barge-in 从旧笔记写的「五步含 `model.truncate()`」收敛成三步。

三个 dataclass（`agent/_realtime/_agent.py`）：

```python
@dataclass
class _Reply:
    """One in-flight model response."""

    item_id: str
    """The provider's response item identifier."""
    reply_id: str
    """The agent's reply this response belongs to, as seen in events and
    context. A reply spans every response up to the next user turn, so
    one that calls tools has several responses."""
    text_block_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    audio_block_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    text_started: bool = False
    audio_started: bool = False


@dataclass
class _UserTurn:
    """One user reply, retained until its transcription settles."""

    reply_id: str
    item_id: str = ""
    open: bool = True
    speech_ended: bool = False


@dataclass
class _QueuedEvent:
    """One outward event and its state at a persistence boundary."""

    event: AgentEvent
    checkpoint: AgentState | None = None
```

单例与「transport borrowed」「断线不退出」两处（`agent/_realtime/_agent.py`）：

```python
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
        ...
        """
        if self._transport is not None:
            raise RuntimeError("RealtimeAgent.reply_stream is already active.")
```

```python
    async def _pump_downlink(self) -> None:
        """Translate model events for as long as the agent is open.

        When the provider closes the session the pump does not exit: it
        marks the model disconnected and waits for :meth:`connect` to be
        called again, which the uplink does on the next user audio.
        """
```

> 上面 `reply_stream` docstring 的 `aclosing` 说明段用 `...` 标注省略。

## Realtime Agent

`RealtimeAgent`（`agent/_realtime/_agent.py`）是**完全不继承 `Agent`** 的类。类定义与 docstring：

```python
class RealtimeAgent:
    """A voice agent: a realtime model on one side, a transport on the
    other, and the turn-taking state machine in between.

    Unlike :class:`~agentscope.agent.Agent` it is bidirectional and has no
    request/reply boundary — audio flows in continuously while events flow
    out of :meth:`reply_stream`.

    Three lifetimes are kept apart on purpose. The agent owns the model
    session and the state; a transport is owned by whoever created it; a
    :meth:`reply_stream` borrows both for as long as both are alive. So a
    client can drop and reconnect without losing the model session, and
    the model session can time out during a long silence and be
    re-established on the next word without touching the transport.
    ...
    """
```

> 上面 docstring 的「public methods / Example」段用 `...` 标注省略。

注意别找错地方——`realtime/_base.py` 里的是 `RealtimeModelBase`（模型适配器基类），不是 Agent。

### Why It Cannot Reuse Agent

| | `Agent` | `RealtimeAgent` |
| :--- | :--- | :--- |
| 调用形态 | `reply()` / `reply_stream()` 一次性请求 | `connect()` / `send()` / `interrupt()` / `reply_stream(transport)`——后者是**常驻会话循环** |
| 中断 | 中断即结束 reply | 需要双向对齐：本地立刻静音 + 通知服务端取消，并把当前 reply 标成 INTERRUPTED |
| 工具调用 | 由主循环串接 | `ResponseDoneEvent` 若带 pending tools 则 `_finish_response()` + `_schedule_tools()`，否则 `_finish_reply(COMPLETED)` |
| 上下文清洗 | 由配置驱动压缩 | `TurnAggregator` 清洗语音推断出的轮次边界 |

**三层生命周期刻意分离**：Agent 拥有模型会话，transport 归创建者所有，`reply_stream` 只是借用两者。结果是客户端断线重连不会丢模型会话。

## Playout and Barge-in

v2.0.8 笔记里那段「五步 barge-in（含 `model.truncate()` 与 `_truncate_reply`）」在 v2.0.11 已不存在。`_barge_in_locked()`（`agent/_realtime/_agent.py`）只剩三步：

```text
1. await transport.clear_audio()      → 本地静音，拿回 PlayoutPosition
2. await model.cancel_response()      → 通知 provider 取消生成
3. self._finish_reply(INTERRUPTED)    → 关闭本地 reply
```

真实源码（`agent/_realtime/_agent.py`）：

```python
    async def _barge_in_locked(self) -> None:
        """Body of :meth:`_barge_in`, run under the lock."""
        active_reply = self._reply
        if self._transport is not None and self._audio_pending:
            await self._transport.clear_audio()
            self._audio_pending = False

        if active_reply is not None and self._connected:
            await self.model.cancel_response()

        if self._reply_id:
            self._finish_reply(ReplyFinishedReason.INTERRUPTED)
```

`_finished_item` 防止 barge-in 之后迟到的 `AudioDeltaEvent` 把已关闭的 reply「复活」。判定的那两行（同文件）：

```python
        if item_id == self._finished_item:
            return None
```

`PlayoutPosition(item_id, played_ms, first_played_at)` 仍是截断精度的依据（`app/_service/_webrtc_audio_transport.py`），但**不再用于反查已播文本前缀去改写服务端上下文**——这是 v2.0.8 与 v2.0.11 最实质的行为差异。定义（`realtime/_playout.py`）：

```python
class PlayoutPosition(BaseModel):
    """How much assistant audio actually left the speaker — the only sound
    basis for truncating a barge-in."""

    item_id: str
    """The assistant item this position refers to."""

    played_ms: int = Field(default=0, ge=0)
    """Milliseconds of audio actually played out."""

    first_played_at: float | None = None
```

`VADBase` 仍是纯扩展点：`realtime/_vad.py` 的抽象边沿检测器只在「本帧发生转移」时返回 `SpeechTransition`（`STARTED` / `ENDED`），`realtime` 包内**没有任何具体实现**：

```python
class SpeechTransition(StrEnum):
    """A transition in voice activity, as detected by a VAD. Not an event
    class; the model-side ``SpeechStartedEvent`` is what a provider reports."""

    STARTED = "started"
    ENDED = "ended"


class VADBase(ABC):
    """Voice activity detection over a stream of PCM16 mono audio.

    Implementations are stateful: ``push`` is called with consecutive
    chunks and returns a transition only on the frame where it happens.
    """
```

## Turn-Taking State Machine

两套 turn detection 路径并存，由「调用方是否自跑 VAD」决定：

| 路径 | 起点 | 终点 |
| :--- | :--- | :--- |
| 自有 VAD | `STARTED` → `_start_user_turn()` + `_barge_in()` | `ENDED` → `commit_turn()` + `request_response()` |
| provider VAD | `SpeechStartedEvent` → `_start_user_turn()` + `_barge_in()` | `SpeechEndedEvent` → `speech_ended=True`，无转录则 `_end_user_turn()` |

provider VAD 路径的入口（`agent/_realtime/_agent.py`）：

```python
    async def _on_model_event(self, event: me.ModelEvent) -> None:
        """Handle one model event."""
        rate = self.model.output_sample_rate
        match event:
            case me.SpeechStartedEvent():
                self._start_user_turn(event.item_id)
                await self._barge_in()
```

下行事件转移：`ResponseCreatedEvent` → `_start_reply`、`AudioDeltaEvent` → `send_audio` + `_emit_audio`、`ToolCallEvent` → `_pending_tools`、`ResponseDoneEvent` → 有 pending tools 则续接否则 `_finish_reply(COMPLETED)`、`ModelErrorEvent` → `_finish_reply(ERROR)`。终止原因枚举 `ReplyFinishedReason` 四值 `COMPLETED / INTERRUPTED / EXCEED_MAX_ITERS / ERROR`（`types/_reply.py`）：

```python
class ReplyFinishedReason(StrEnum):
    """The reason a reply finished."""

    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    EXCEED_MAX_ITERS = "exceed_max_iters"
    ERROR = "error"
```

`realtime/_base.py` 的 `connect` docstring 明确 `turn_detection_disabled=True` 表示「调用方自跑 VAD」。但浏览器语音模式反过来——`app/_router/_realtime.py` 对 `parameters["turn_detection"] == "none"` 直接 409 拒绝，强制用 provider turn detection。**双路径 turn-taking 只在 Python / TUI 侧可用**。两处源码：

```python
            **kwargs (`Any`):
                Extra provider fields. ``turn_detection_disabled=True``
                asks the provider not to detect turns because the caller
                runs its own VAD; a resumption handle may also be passed.
```

```python
    if config.parameters.get("turn_detection") == "none":
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=(
                "Browser voice mode does not support "
                "turn_detection='none'. Select provider turn detection."
            ),
        )
```

`TurnAggregator`（`agent/_realtime/_aggregator.py`）仍负责事后把 transcript 收拢成干净用户轮次：`merge_window_ms=800` 合并被端点检测拆开的句子，`backchannels` 丢弃「嗯」类应答。默认值与 `take()` 里的合并判定：

```python
class TurnAggregator:
    """Collapses the transcripts a provider emits into clean user turns.
    ...
    """

    def __init__(
        self,
        merge_window_ms: int = 800,
        backchannels: frozenset[str] = frozenset(),
        min_chars: int = 1,
    ) -> None:
```

```python
        text = transcript.strip()
        if len(text) < self.min_chars:
            return None
        if text.strip(_TRAILING) in self.backchannels:
            return None

        now = time.monotonic()
        self._merges = (
            self._last_at is not None
            and (now - self._last_at) * 1000 <= self.merge_window_ms
        )
```

> 上面 `TurnAggregator` 类 docstring 中间段与 `__init__` 的 Args 段用 `...` 标注省略。

## Vendor Adapters in v2.0.11

v2.0.8 只发布 DashScope 一家；v2.0.11 是 **4 家 / 5 类，无 Anthropic**（`realtime/__init__.py`）：

| Vendor | 类 | `supports_text_input` | 备注 |
| :--- | :--- | :---: | :--- |
| DashScope | `DashScopeRealtimeModel`（`_dashscope/_model.py`） | `False` | OpenAI 形状但更窄 |
| DashScope | `DashScopeAudioRealtimeModel`（`_dashscope/_audio_model.py`） | `True` | 另开 `supports_history_replay=True` |
| OpenAI | `OpenAIRealtimeModel`（`_openai/_model.py`） | `True` | `input_audio_transcription` 默认 `gpt-4o-mini-transcribe` |
| Gemini | `GeminiRealtimeModel`（`_gemini/_model.py`） | `True` | — |
| xAI | `XAIRealtimeModel`（`_xai/_model.py`） | `True` | — |

`realtime/__init__.py` 的模型导出：

```python
__all__ = [
    # Model
    "RealtimeModelBase",
    "DashScopeRealtimeModel",
    "DashScopeAudioRealtimeModel",
    "GeminiRealtimeModel",
    "OpenAIRealtimeModel",
    "XAIRealtimeModel",
    "RealtimeModelCard",
    "ModelDisconnectedError",
```

`RealtimeModelBase`（`realtime/_base.py`）的方法面 10 个：`connect` / `close` / `events` / `push_audio` / `push_text` / `push_tool_result` / `commit_turn` / `request_response` / `cancel_response` 九个抽象方法，加非抽象 `replay_history(messages)` 与 classmethod `_find_card` / `list_models`。12 个内部 `ModelEvent` 在 `realtime/_events.py`。能力位（`realtime/_base.py`）：

```python
    # ------------------------------------------------------------------
    # Adapter facts — constant across every model of this API
    # ------------------------------------------------------------------

    type: str = ""
    """Identifies the adapter; stamped onto every card it lists so a stored
    config can be mapped back to this class."""

    supports_text_input: bool = False
    """Whether a text turn can be injected mid-session."""

    supports_history_replay: bool = False
    """Whether completed messages can seed a newly opened session."""
```

一个常见误读：**`websockets` 是 model ↔ provider 的连接，不是 transport**。4 家 `connect()` 里都 `import websockets` + `websockets.connect(...)`（`realtime/_openai/_model.py`、`_gemini/_model.py`、`_dashscope/_model.py`、`_xai/_model.py`）。

## Transport Layer

`TransportBase`（`realtime/_transport/_base.py`）契约是 `start` / `close` / `incoming()` / `send_audio(pcm, item_id)` / `clear_audio() -> PlayoutPosition` / `playout()`。`ControlFrameType` 只有 3 值 `TEXT / USER_CONFIRM / INTERRUPT`，注释说明「每个都是 `RealtimeAgent` 公有方法的 wire 形式」。枚举（`realtime/_transport/_base.py`）：

```python
class ControlFrameType(StrEnum):
    """The non-audio things a remote client can say.

    Each one is the wire form of a public :class:`RealtimeAgent` method,
    so that a browser can do what a Python caller does directly. Traffic
    a transport handles for itself — handshakes, playback reports — never
    reaches the agent and has no member here.
    """

    TEXT = "text"
    """A typed user turn."""

    USER_CONFIRM = "user_confirm"
    """The outcome of a tool permission prompt."""

    INTERRUPT = "interrupt"
    """The user pressed stop, as opposed to speaking over the reply."""
```

`realtime` 包内唯一实现仍是 `LocalAudioTransport`（`_local.py`，sounddevice / PortAudio，回调在 PortAudio 线程）。但 **v2.0.10 起 WebRTC 在 app 层跨包实现**：`WebRTCAudioTransport(TransportBase)`（`app/_service/_webrtc_audio_transport.py`）与 `WebRTCSession`（`app/_service/_webrtc_session.py`）。所以旧笔记「v2.0.8 没有 WebRTC transport 类」在 `realtime/_transport/` 目录层面仍成立，但**在整个框架层面已失效**——`_router/__init__.py` 也确实注册了 `realtime_router`。跨包实现的类定义：

```python
class WebRTCAudioTransport(TransportBase):
    """Bridge WebRTC audio tracks and a control DataChannel to an agent."""
```

`WebRTCSession._run()` 持 session lock，`async with transport` + `async with agent` + **单个** `async for event in agent.reply_stream(transport)` 跑满会话，过滤 PCM 的 `DataBlockStart/Delta/EndEvent` 后把其余事件写 SSE（`app/_service/_webrtc_session.py`）：

```python
    async def _run(self) -> None:
        """Hold the session lock while forwarding events to the SSE log."""
        try:
            async with self.message_bus.acquire_lock(
                MessageBusKeys.session_lock(self.session_id),
                ttl_secs=MessageBusKeys.SESSION_RUN_TTL_SECS,
            ):
                self._lock_acquired.set()
                try:
                    self.agent = await self._agent_factory()
                    ...
                    async with self.transport:
                        async with self.agent:
                            async for event in self.agent.reply_stream(
                                self.transport,
                            ):
                                if isinstance(event, DataBlockStartEvent) and (
                                    event.media_type.startswith("audio/pcm")
                                ):
```

> 上面 `_persisted_messages` 快照段用 `...` 标注省略。

3 个端点是 `GET /realtime/models`、`GET /realtime/config`、`POST /realtime/sessions/{session_id}/offer`（`app/_router/_realtime.py`）。

## Capability Negotiation

`TruncationSupport`（`NONE / SERVER / EXPLICIT`）是 v2.0.9 的 `StrEnum`，**v2.0.10 已删除**，`RealtimeModelBase.truncation` 字段一并移除，v2.0.11 全仓零命中。取而代之的是三个布尔/property 能力位（`realtime/_base.py`）：

| 能力位 | 位置 | 语义 |
| :--- | :--- | :--- |
| `type` | `realtime/_base.py` | 标识适配器，盖在它列出的每张卡上，供存储配置映射回类 |
| `supports_text_input` | `realtime/_base.py` | 会话中能否注入文本轮次 |
| `supports_history_replay` | `realtime/_base.py` | 新开会话能否用历史消息打底 |
| `input_transcription_enabled` | `realtime/_base.py` | property，默认 False |
| 采样率 | `realtime/_base.py` | `input_sample_rate` / `output_sample_rate` 取自模型卡 |

采样率与 `input_transcription_enabled` 的 property（`realtime/_base.py`）：

```python
    @property
    def input_sample_rate(self) -> int:
        """The PCM rate :meth:`push_audio` expects, in Hz."""
        return self.card.input_sample_rate

    @property
    def output_sample_rate(self) -> int:
        """The PCM rate of the audio in :class:`AudioDelta`, in Hz."""
        return self.card.output_sample_rate

    @property
    def input_transcription_enabled(self) -> bool:
        """Whether a settled user transcript is expected after speech."""
        return False
```

模型卡本身还带 `supports_tools`、`max_context_tokens` 等（`realtime/_model_card.py`）：

```python
    supports_tools: bool = Field(
        default=False,
        description="Whether this model accepts tool schemas.",
    )

    # Context limits. Providers use different units and several can apply
    # at once, so all are optional; ``None`` means unlimited or unknown.
    max_context_tokens: int | None = Field(default=None, gt=0)
```

也就是说能力差异从「一个三值枚举 + 代码按档分支」变成了「一组正交布尔位 + 模型卡字段」——这是 v2.0.9 → v2.0.10 一次方向性的重构，旧笔记把它记成「v2.0.10 仍在靠 `TruncationSupport` 吸收」，正好说反了。

## Boundary with Core Agent

`RealtimeAgent` 不继承 `Agent`，但它由**与核心 `Agent` 完全相同的原语**构建：

- **共享事件词汇**：`reply_stream()` 吐出的正是普通 `Agent.reply_stream()` 会吐的同一批 `AgentEvent`（`agent/_realtime/_agent.py`），下游渲染器（TUI / Web UI）对实时事件与聊天事件一视同仁。
- **共享消息模型**：从 `agentscope.message` 导入 `Msg` / `UserMsg` / `TextBlock` / `ToolCallBlock` / `ToolResultBlock` / `Usage`，从 `agentscope.state` 导入 `AgentState`。
- **共享权限与工具**：复用 `PermissionEngine` / `PermissionBehavior` 与 `Toolkit` / `ToolChunk` / `ToolResponse`。

文件顶部的 import 清单（`agent/_realtime/_agent.py`）：

```python
from ...event import (
    AgentEvent,
    ConfirmResult,
    DataBlockDeltaEvent,
    DataBlockEndEvent,
    DataBlockStartEvent,
    ModelCallEndEvent,
    ModelCallStartEvent,
    ReplyEndEvent,
    ReplyStartEvent,
    RequireUserConfirmEvent,
    TextBlockDeltaEvent,
    TextBlockEndEvent,
    TextBlockStartEvent,
    ToolCallDeltaEvent,
    ToolCallEndEvent,
    ToolCallStartEvent,
    ToolResultEndEvent,
    ToolResultStartEvent,
    ToolResultTextDeltaEvent,
    UserConfirmResultEvent,
    UserInterruptEvent,
)
from ...message import (
    Msg,
    SystemMsg,
    TextBlock,
    ToolCallBlock,
    ToolCallState,
    ToolResultBlock,
    ToolResultState,
    Usage,
    UserMsg,
)
from ...permission import PermissionBehavior, PermissionEngine
from ...state import AgentState
from ...tool import ToolChunk, ToolResponse, Toolkit
```

**实时音频如何变成 Msg content block**：`AudioDeltaEvent` → `_emit_audio()` 发出 `DataBlockStartEvent` / `DataBlockDeltaEvent`，承载 base64 PCM、`media_type="audio/pcm;rate=<hz>"`；`TranscriptDeltaEvent` → `_emit_text()` 追加进**单个**不断增长的 `TextBlock`；用户落定的语音 `InputTranscriptionEvent` → `_on_transcription()` 往 `state.context` 追加一条 `UserMsg`。这些事件经 `_emit()` 入 `asyncio.Queue` 再由 `reply_stream` 泵出。音频与文本两条发射路径（同文件）：

```python
    def _emit_audio(self, reply: _Reply, pcm: bytes, rate: int) -> None:
        """Emit an audio delta, opening the block on first use."""
        media_type = f"audio/pcm;rate={rate}"
        if not reply.audio_started:
            reply.audio_started = True
            self._emit(
                DataBlockStartEvent(
                    reply_id=reply.reply_id,
                    block_id=reply.audio_block_id,
                    media_type=media_type,
                ),
            )
        self._emit(
            DataBlockDeltaEvent(
                reply_id=reply.reply_id,
                block_id=reply.audio_block_id,
                data=base64.b64encode(pcm).decode("ascii"),
                media_type=media_type,
            ),
        )
```

```python
        # Grow the tail text block rather than appending one per delta,
        # or the context ends up as dozens of one-word blocks.
        message = self._find_reply_message(reply.reply_id)
        blocks = message.content if message is not None else None
        if (
            isinstance(blocks, list)
            and blocks
            and isinstance(blocks[-1], TextBlock)
        ):
            blocks[-1].text += delta
        else:
            self._append_reply_block(
                reply.reply_id,
                TextBlock(id=reply.text_block_id, text=delta),
            )
```

```python
    def _on_transcription(self, event: me.InputTranscriptionEvent) -> None:
        """Record a settled user turn, merging a split one back together,
        and report its text on the user's reply."""
        turn = self.aggregator.take(event.text)
```

> [!NOTE]
>
> `RealtimeAgent` / `LocalAudioTransport` 不是私有 API：`agent/__init__.py` 公开导出 `agentscope.agent.RealtimeAgent`，`realtime/__init__.py` 导出 `agentscope.realtime.LocalAudioTransport`；带下划线的只是内部模块文件名。

导出（`agent/__init__.py`）：

```python
from ._agent import Agent
from ._a2a_agent import A2AAgent
from ._config import ContextConfig, InjectionConfig, ModelConfig, ReActConfig
from ._realtime import RealtimeAgent, TurnAggregator, TurnMetrics

__all__ = [
    "Agent",
    "A2AAgent",
    "RealtimeAgent",
    "TurnAggregator",
```

## Links

- [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)
- [VoiceStack 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/VoiceStack.md)
- [TUI 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/TUI.md)
- [App 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/App.md)
- [Agent 理论](/docs/CS/AI/LLM/Agent/Theory/Agent.md)
- [Memory 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Memory.md)

## References

- [AgentScope v2.0.11 — agent/_realtime/_agent.py](https://github.com/agentscope-ai/agentscope/blob/v2.0.11/src/agentscope/agent/_realtime/_agent.py)
- [AgentScope v2.0.11 — realtime/_base.py](https://github.com/agentscope-ai/agentscope/blob/v2.0.11/src/agentscope/realtime/_base.py)
- [AgentScope v2.0.11 — realtime/_events.py](https://github.com/agentscope-ai/agentscope/blob/v2.0.11/src/agentscope/realtime/_events.py)
- [AgentScope v2.0.11 — app/_service/_webrtc_session.py](https://github.com/agentscope-ai/agentscope/blob/v2.0.11/src/agentscope/app/_service/_webrtc_session.py)
- [AgentScope v2.0.11 — app/_router/_realtime.py](https://github.com/agentscope-ai/agentscope/blob/v2.0.11/src/agentscope/app/_router/_realtime.py)
