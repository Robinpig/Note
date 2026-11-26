## Introduction

AgentScope 的语音能力在 v2.0.11 是**三套彼此几乎不耦合的子系统**：`asr/`（语音转文本）、`tts/`（文本转语音）、`realtime/`（双向语音会话），加上服务层的 WebRTC transport。本分册讲这三栈的模型抽象、模型卡机制、transport 边界与打包陷阱；`RealtimeAgent` 的 turn-taking 状态机细节归 Realtime 分册。

> 版本基线：v2.0.11（`src/agentscope/asr/`、`tts/`、`realtime/`、`app/_service/_webrtc_*`）

三个反直觉点：

1. **`asr/` 是 v2.0.11 整包新增的孤岛**：8 个文件全是 `A`，但 `realtime/`、`tui/`、`app/` 对它**零引用**，唯一入口是 `credential/_base.py` 的模型发现；app 层连一个 asr 路由都没有。
2. **`TruncationSupport` 枚举已经被删除了**：它是 v2.0.9 引入、`TruncationSupport` 在 v2.0.10 连同 `RealtimeModelBase.truncation` 一起移除，v2.0.11 全仓零命中，改由布尔能力位加模型卡承担。
3. **`aiortc` 装在 `service` extra，报错却提示装 `agentscope[realtime]`**：按提示装完仍然缺依赖（见 Packaging Traps）。

## Version Archaeology

逐 tag `git cat-file -e` 核对（本机 v2.0.11 树，实测）：

| 模块 | v2.0.8 | v2.0.9 | v2.0.10 | v2.0.11 |
| :--- | :---: | :---: | :---: | :---: |
| `tui/`（Textual） | — | ✅ | ✅ | ✅ |
| `pipeline/_team_pipeline.py` | — | ✅ | ✅ | ✅ |
| `sop/` 与 `formatter/_minimax_formatter.py` | — | ✅ | ✅ | ✅ |
| `realtime/_openai`,`_gemini`,`_xai` 适配器 | — | ✅ | ✅ | ✅ |
| `app/_service/_webrtc_session.py`（WebRTC） | — | — | ✅ | ✅ |
| `asr/` 整包 | — | — | — | ✅ |
| `tts/`、`realtime/_dashscope`、`console/` | ✅ | ✅ | ✅ | ✅ |

旧笔记把 `tui/`、Team Pipeline、SOP、MiniMax 与三家 Realtime 适配器都归到「v2.0.10 新增」，**整段版本归属是错的**；WebRTC 才是 v2.0.10，`asr/` 才是 v2.0.11。另外 `tts/` 整包 v2.0.8 就存在，v2.0.8→v2.0.11 新增的 4 个文件只是 4 张 `_cosyvoice_models/*.yaml` 模型卡。

## ASR: A Standalone Island in v2.0.11

`ASRModelBase`（注意全大写 ASR，`asr/_asr_base.py`）是 ABC，唯一 `@abstractmethod` 是 `transcribe`。基类同时定义 **batch 与 realtime 两套协议**：`realtime: bool = False`、`__aenter__` 仅在 realtime 时 `connect()`、`push(audio)` 默认抛 `RuntimeError`。`transcribe(audio=None)` 对 realtime 模型表示「收尾已 push 的分块」，传完整内存音频时是 batch，`filename` 供 multipart 识别格式。

类 docstring 与 realtime 开关（`asr/_asr_base.py`）：

```python
class ASRModelBase(ABC):
    """Base class for batch and realtime speech recognition models.

    Batch implementations transcribe complete audio by calling
    :meth:`transcribe` directly. Realtime implementations use the asynchronous
    context manager, call :meth:`push` for each audio chunk, and finally call
    :meth:`transcribe` without audio to finalize the current transcription.

    Every concrete implementation must override :meth:`transcribe`. Realtime
    implementations must additionally override :meth:`connect`,
    :meth:`close`, and :meth:`push`.
    """
```

```python
    realtime: bool = False
    """Whether the model supports realtime streaming input."""
```

```python
        if self.realtime:
            await self.connect()
        return self
```

`push` 的默认实现（同文件）：

```python
        raise RuntimeError(
            f"{type(self).__name__} does not support realtime audio input",
        )
```

模型卡机制：`list_models()` 扫 `inspect.getfile(cls).parent / "_models"` 下的 `*.yaml`，用 `card.realtime != cls.realtime` 过滤，坏卡只 warn 跳过。过滤与容错（`asr/_asr_base.py`）：

```python
        model_cards = []
        for path in sorted(yaml_dir.glob("*.yaml")):
            try:
                card = ASRModelCard.from_yaml(
                    str(path),
                    cls.Parameters,
                )
                if card.realtime != cls.realtime:
                    continue
                model_cards.append(card)
            # Keep one invalid card from hiding other valid cards.
            except Exception as error:
                logger.warning(
                    "Failed to load ASR model card %s: %s",
                    path,
                    error,
                )
        return model_cards
```

`ASRModelCard.from_yaml()` 只取 YAML 的 `name/label/input_types/output_types/realtime`，`parameter_schema` 由 `parameter_class.model_json_schema()` **现场生成**，不在 YAML 里（`asr/_asr_model_card.py`）：

```python
    @classmethod
    def from_yaml(
        cls,
        yaml_path: str,
        parameter_class: Type[BaseModel],
    ) -> Self:
        """Load a card and the implementation's parameter schema."""
        with open(yaml_path, "r", encoding="utf-8") as file:
            config = yaml.safe_load(file)
        return cls(
            name=config["name"],
            label=config["label"],
            input_types=config.get("input_types", []),
            output_types=config.get("output_types", ["text/plain"]),
            realtime=config.get("realtime", False),
            parameter_schema=parameter_class.model_json_schema(),
        )
```

`ASRResponse` 是 `DictMixin` dataclass：`content: TextBlock | None`、`type="asr"`、`is_last=True`（`asr/_asr_response.py`）：

```python
@dataclass
class ASRResponse(DictMixin):
    """The text produced by an ASR model."""

    content: TextBlock | None
    """The transcribed text content, or ``None`` when no text is ready."""
    ...
    type: Literal["asr"] = field(default_factory=lambda: "asr")
    """The response type discriminator."""
    ...
    is_last: bool = field(default_factory=lambda: True)
    """Whether this is the last response in the transcription stream."""
```

> 上面 `ASRResponse` 的 `id` / `created_at` / `metadata` 三段字段用 `...` 标注省略。

唯一实现 `OpenAIASRModel`（`asr/_openai/_model.py`）：`type="openai_asr"`、`realtime=False`、默认 `gpt-4o-mini-transcribe`，`transcribe` 调 `client.audio.transcriptions.create(file=(filename, audio), response_format="json")`。两张卡 `gpt-4o-transcribe` / `gpt-4o-mini-transcribe` 各 9 行，只有 6 种 audio MIME 的 `input_types`。包导出 4 个符号（`asr/__init__.py`）。

实现类与默认值（`asr/_openai/_model.py`）：

```python
class OpenAIASRModel(ASRModelBase):
    """Batch speech recognition using OpenAI's Audio Transcriptions API."""
    ...
    type: Literal["openai_asr"] = "openai_asr"
    """The model implementation type discriminator."""

    realtime: bool = False
    """OpenAI Audio Transcriptions accepts complete audio files."""

    def __init__(
        self,
        credential: OpenAICredential,
        model: str = "gpt-4o-mini-transcribe",
        parameters: "OpenAIASRModel.Parameters | None" = None,
    ) -> None:
```

> 上面 `Parameters` 内部类用 `...` 标注省略。

```python
        api_kwargs: dict[str, Any] = {
            "file": (filename, audio),
            "model": self.model,
            "response_format": "json",
            **self.parameters.model_dump(exclude_none=True),
            **kwargs,
        }
        result = await self.client.audio.transcriptions.create(**api_kwargs)
        text = result if isinstance(result, str) else result.text
        return ASRResponse(content=TextBlock(text=text))
```

**它怎么被用**：`codegraph callers` 反查显示 `ASRModelBase` / `OpenAIASRModel` 的引用全在 `asr/` 自身、`credential/_base.py`、`credential/_openai.py` 与 tests。接入方式是 **credential 模型发现**——`get_asr_model_classes()` 返回 `[OpenAIASRModel]`（`credential/_openai.py`），`list_asr_models()` 遍历调 `list_models()`（`credential/_base.py`）。`credential/_base.py` 的 `TYPE_CHECKING` 里同时 import ASR / TTS / Realtime / Chat 四类基类，说明四栈在 credential 层平级。

`credential/_base.py` 的 TYPE_CHECKING 块：

```python
if TYPE_CHECKING:
    from ..asr import ASRModelBase, ASRModelCard
    from ..embedding import EmbeddingModelBase
    from ..model import ChatModelBase, ModelCard
    from ..realtime import RealtimeModelBase, RealtimeModelCard
    from ..tts import TTSModelBase
    from ..tts._tts_model_card import TTSModelCard
```

发现入口（同文件）：

```python
    @classmethod
    def get_asr_model_classes(cls) -> list[Type["ASRModelBase"]]:
        """Return supported speech recognition implementations."""
        return []

    @classmethod
    def list_asr_models(cls) -> list["ASRModelCard"]:
        """List candidate ASR models for this credential."""
        cards: list["ASRModelCard"] = []
        for asr_cls in cls.get_asr_model_classes():
            cards.extend(asr_cls.list_models())
        return cards
```

`credential/_openai.py` 的覆写：

```python
    @classmethod
    def get_asr_model_classes(cls) -> list[Type["ASRModelBase"]]:
        """Return the OpenAI transcription implementation."""
        from ..asr import OpenAIASRModel

        return [OpenAIASRModel]
```

最容易混淆的一点：OpenAI Realtime 的 `input_audio_transcription` 默认值恰是字符串 `"gpt-4o-mini-transcribe"`（`realtime/_openai/_model.py`），与 asr 卡同名，**但它只是发给供应商的参数，不实例化 `OpenAIASRModel`**。两套「ASR」互不相干。字段定义（`realtime/_openai/_model.py`）：

```python
        input_audio_transcription: str = Field(
            default="gpt-4o-mini-transcribe",
            title="Input Transcription Model",
            description="The ASR model transcribing the user's speech; an "
            "empty string turns transcription off.",
        )
```

## TTS: Five Implementations, Three Providers

`TTSModelBase`（`tts/_tts_base.py`）唯一抽象方法 `synthesize`，另有 `push` / `connect` / `close`、`stream: bool`、`realtime: bool = False`。`synthesize` 返回 `TTSResponse | AsyncGenerator[TTSResponse, None]`；stream 模式下每块是**增量音频 delta**（非累积），末块 `is_last=True`。`TTSResponse` 用 `DataBlock` 而非 `TextBlock`，带 `TTSUsage(input_tokens, output_tokens, time)`（`tts/_tts_response.py`）。

基类 docstring（`tts/_tts_base.py`）：

```python
    For non-realtime TTS models, only :meth:`synthesize` needs to be
    implemented. For realtime TTS models, the lifecycle is managed via the
    async context manager (``async with model: ...``) or by calling
    :meth:`connect` / :meth:`close` manually; :meth:`push` appends text
    chunks and returns whatever audio is currently available, while
    :meth:`synthesize` blocks until the full speech has been synthesized.
```

`TTSUsage` 与 `TTSResponse`（`tts/_tts_response.py`）：

```python
@dataclass
class TTSUsage(DictMixin):
    """The usage of a TTS model API invocation."""

    input_tokens: int
    """The number of input tokens."""

    output_tokens: int
    """The number of output tokens."""

    time: float
    """The time used in seconds."""
    ...


@dataclass
class TTSResponse(DictMixin):
    """The response of TTS models."""

    content: DataBlock | None
    """The audio chunk produced by the TTS model. The audio format is
    indicated by ``content.source.media_type`` (e.g.
    ``"audio/pcm;rate=24000"``, ``"audio/mpeg"``)."""
    ...
```

> 上面 `TTSUsage` 的 `type` 字段与 `TTSResponse` 的 `id` / `created_at` / `type` / `is_last` 字段用 `...` 标注省略。

5 个实现类、3 家 provider（`tts/__init__.py`）：`DashScopeTTSModel`、`DashScopeCosyVoiceTTSModel`、`DashScopeRealtimeTTSModel`（QwenTtsRealtime WebSocket，支持 `push` 流式输入但限定同时仅一个 streaming 请求，`tts/_dashscope/_realtime_model.py`）、`GeminiTTSModel`、`OpenAITTSModel`。`TTSModelCard` 比 ASR 卡复杂，多了 `status/deprecated_at`、`parameters_overrides`，`voices` 会自动注入 `voice` 的 `default`/`enum`，`parameter_overrides` 可 hidden 删字段（`tts/_tts_model_card.py`）。

导出清单（`tts/__init__.py`）：

```python
__all__ = [
    "TTSModelBase",
    "TTSModelCard",
    "TTSResponse",
    "TTSUsage",
    "DashScopeCosyVoiceTTSModel",
    "DashScopeTTSModel",
    "DashScopeRealtimeTTSModel",
    "GeminiTTSModel",
    "OpenAITTSModel",
]
```

`from_yaml` 里的 voices 注入与 hidden 删字段（`tts/_tts_model_card.py`）：

```python
        # Auto-inject: populate voice enum from YAML voices list
        voices = config.get("voices", [])
        if voices and "voice" in properties:
            properties["voice"] = {
                **properties["voice"],
                "default": voices[0],
                "enum": voices,
            }

        # Apply parameter_overrides
        overrides = config.get("parameter_overrides", {})
        for param_name, override in overrides.items():
            if override is None:
                properties.pop(param_name, None)
                continue

            if isinstance(override, dict):
                if override.get("hidden"):
                    properties.pop(param_name, None)
                    continue
```

**TTS 与 realtime 零代码依赖**：全仓 `realtime/` 内 `import tts` 零命中，`RealtimeService.create_agent` 构造 `RealtimeAgent` 只传 `name/system_prompt/model/toolkit/state`，无 TTS 参数（`app/_service/_realtime.py`）。app 侧唯一 TTS 端点是列模型卡的 `GET /tts-model/`，走 `credential_cls.list_tts_models()`（`app/_router/_tts_model.py`）。

`RealtimeService.create_agent` 的返回（`app/_service/_realtime.py`）：

```python
        return RealtimeAgent(
            name=agent_record.data.name,
            system_prompt=system_prompt,
            model=model,
            toolkit=toolkit,
            state=session.state,
        )
```

TTS 端点（`app/_router/_tts_model.py`）：

```python
tts_model_router = APIRouter(
    prefix="/tts-model",
    tags=["tts-model"],
    responses={404: {"description": "Not found"}},
)


@tts_model_router.get(
    "/",
    response_model=ListTTSModelsResponse,
    summary="List all candidate TTS models under the given credential type",
)
async def list_tts_models(
    body: ListTTSModelsRequest = Depends(),
) -> ListTTSModelsResponse:
    ...
    models = credential_cls.list_tts_models()
    return ListTTSModelsResponse(models=models, total=len(models))
```

> 上面 `list_tts_models` 的 docstring 与 provider 查不到时的 404 分支用 `...` 标注省略。

## Realtime Models: Four Vendors, Five Adapters

模型家族是 **4 家 / 5 类，无 Anthropic**（`realtime/__init__.py`）：DashScope 有 `DashScopeRealtimeModel` 与 `DashScopeAudioRealtimeModel` 两类，另有 Gemini / OpenAI / xAI。

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

`RealtimeModelBase`（`realtime/_base.py`）的类属性面就是能力协商的全部：`type`、`supports_text_input = False`、`supports_history_replay = False`、`input_transcription_enabled` property 默认 False、`input_sample_rate` / `output_sample_rate` 取自模型卡。方法面 10 个：`connect` / `close` / `events` / `push_audio` / `push_text` / `push_tool_result` / `commit_turn` / `request_response` / `cancel_response` 九个抽象方法，加非抽象的 `replay_history(messages)` 与 classmethod `_find_card` / `list_models`。`connect` 的 docstring 明确 `turn_detection_disabled=True` 表示「调用方自跑 VAD」。

类属性（`realtime/_base.py`）：

```python
class RealtimeModelBase(ABC):
    """A bidirectional realtime model: audio in, audio and tool calls out.

    Facts live in three places: class attributes for what the adapter
    implements, the model card for what the model is, and properties for
    what is a constant on one provider and a parameter on another.
    """
    ...
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

> 上面 `Parameters` 内部类用 `...` 标注省略。

property 与 `connect` docstring（同文件）：

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

```python
            **kwargs (`Any`):
                Extra provider fields. ``turn_detection_disabled=True``
                asks the provider not to detect turns because the caller
                runs its own VAD; a resumption handle may also be passed.
```

能力差异**不再靠 `TruncationSupport` 枚举**：v2.0.9 曾定义 `StrEnum(NONE/SERVER/EXPLICIT)` 加 `RealtimeModelBase.truncation` 字段，v2.0.10 删除，v2.0.11 改由布尔类属性 + property + 模型卡字段（`realtime/_model_card.py`）承担。各适配器 `supports_text_input`：`DashScopeRealtimeModel=False`，其余 4 类均为 True；`DashScopeAudioRealtimeModel` 另开 `supports_history_replay=True`（`realtime/_dashscope/_model.py`、`_audio_model.py`、`_openai/_model.py`、`_gemini/_model.py`、`_xai/_model.py`）。模型卡的 `supports_tools` / `max_context_tokens`（`realtime/_model_card.py`）：

```python
    supports_tools: bool = Field(
        default=False,
        description="Whether this model accepts tool schemas.",
    )

    # Context limits. Providers use different units and several can apply
    # at once, so all are optional; ``None`` means unlimited or unknown.
    max_context_tokens: int | None = Field(default=None, gt=0)
```

12 个内部 `ModelEvent` 定义在 `realtime/_events.py`（`SessionEnded` / `SpeechStarted` / `SpeechEnded` / `InputTranscription(Failed)` / `ResponseCreated` / `AudioDelta` / `TranscriptDelta` / `ToolCall` / `ResponseDone` / `ModelError`）。事件基类与前几个事件（`realtime/_events.py`）：

```python
class ModelEvent(BaseModel):
    """Common base class, for type hinting only."""


class SessionEndedEvent(ModelEvent):
    """The provider session is gone; no further events will arrive."""

    reason: str = ""


class SpeechStartedEvent(ModelEvent):
    """The provider's own VAD detected the user starting to speak."""

    item_id: str = ""
    at_ms: int = 0


class SpeechEndedEvent(ModelEvent):
    """The provider's own VAD detected the user stopping."""

    item_id: str = ""
    at_ms: int = 0
```

一个常见误读：**`websockets` 是 model ↔ provider 的连接，不是 transport**。4 家 `connect()` 里都 `import websockets` + `websockets.connect(...)`（`realtime/_openai/_model.py`、`_gemini/_model.py`、`_dashscope/_model.py`、`_xai/_model.py`），OpenAI 拼 `wss://.../realtime?model=`。真正的 transport 抽象在 `realtime/_transport/`。

## Transports and WebRTC

`TransportBase`（`realtime/_transport/_base.py`）的契约是 `start` / `close` / `incoming()` / `send_audio(pcm, item_id)` / `clear_audio() -> PlayoutPosition` / `playout()`。`ControlFrameType` 只有 3 值 `TEXT / USER_CONFIRM / INTERRUPT`，注释说明「每个都是 `RealtimeAgent` 公有方法的 wire 形式」。枚举定义（`realtime/_transport/_base.py`）：

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

`realtime` 包内唯一实现是 `LocalAudioTransport`（sounddevice/PortAudio，回调在 PortAudio 线程，`_local.py`）。它的 docstring（`realtime/_transport/_local.py`）：

```python
class LocalAudioTransport(TransportBase):
    """Microphone in, speaker out, via ``sounddevice``.

    Audio callbacks run on PortAudio's thread, not the event loop: captured
    chunks are handed to the loop with ``call_soon_threadsafe`` and
    playback pulls from a lock-guarded buffer. Playout accounting lives in
    that callback, the same place a browser's AudioWorklet does it.
    """
```

`SpeechTransition` 只有 `STARTED/ENDED`，`VADBase` 是边沿检测器且包内**无具体实现**（`realtime/_vad.py`）：

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

WebRTC 是**跨包**实现的：`WebRTCAudioTransport(TransportBase)` 在 `app/_service/_webrtc_audio_transport.py`，`WebRTCAudioTrack(MediaStreamTrack)` 48 kHz / 20 ms 帧 / `AudioResampler` 负责模型 PCM → 浏览器。常量与类（`app/_service/_webrtc_audio_transport.py`）：

```python
_WEBRTC_SAMPLE_RATE = 48_000
_FRAME_DURATION_MS = 20
_FRAME_SAMPLES = _WEBRTC_SAMPLE_RATE * _FRAME_DURATION_MS // 1_000
_FRAME_BYTES = _FRAME_SAMPLES * 2
_MAX_INCOMING_AUDIO_MS = 10_000


class WebRTCAudioTrack(MediaStreamTrack):
    """A continuous mono audio track fed by model PCM chunks."""

    kind = "audio"

    def __init__(
        self,
        source_sample_rate: int,
        on_item_started: Callable[[str, int], None],
    ) -> None:
        super().__init__()
        self._source_sample_rate = source_sample_rate
        self._on_item_started = on_item_started
        self._resampler = AudioResampler(
            format="s16",
            layout="mono",
            rate=_WEBRTC_SAMPLE_RATE,
        )
```

```python
class WebRTCAudioTransport(TransportBase):
    """Bridge WebRTC audio tracks and a control DataChannel to an agent."""
```

DataChannel JSON 里 `type=control` 映射成 `ControlFrameType`，另有 `playout` / `playout_cleared` / `close` 三类帧自行处理、不进 agent；`PlayoutPosition(item_id, played_ms, first_played_at)` 回报播放位置供 barge-in 精确截断（`realtime/_playout.py`）：

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

`WebRTCSession._run()` 持 session lock，`async with transport` + `async with agent` + **单个** `async for event in agent.reply_stream(transport)` 跑满会话，过滤掉 PCM 的 `DataBlockStart/Delta/EndEvent` 后把其余事件写 SSE（`app/_service/_webrtc_session.py`）。核心几行：

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

路由 3 个（`app/_router/_realtime.py`）：`GET /realtime/models`、`GET /realtime/config`（ICE servers）、`POST /realtime/sessions/{session_id}/offer`（SDP 协商，绑定 `track` / `datachannel` / `connectionstatechange`）。

**浏览器语音模式禁用本地 VAD**：`connect` 支持 `turn_detection_disabled=True` 让调用方自跑 VAD，但 offer 端点对 `parameters["turn_detection"] == "none"` 直接 409 拒绝，强制用 provider turn detection；双路径 turn-taking 只在 Python / TUI 侧可用。409 分支（`app/_router/_realtime.py`）：

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

`aiortc` 缺失时报 503，但提示的是装 `[realtime]`（同文件）：

```python
    except ImportError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "WebRTC support is not installed. Install "
                "agentscope[realtime]."
            ),
        ) from exc
```

## Packaging Traps

`pyproject.toml` 的 extras 边界有几处与直觉不符（均为 v2.0.11 实测）：

- **没有 `asr` extra，也没有 `tts` extra**：`openai`、`dashscope`、`rich` 都在核心 `dependencies` 里；`google-genai` 并不在核心依赖中，它只出现在 `model-gemini` extra。
- `realtime = ["websockets>=13"]`、`realtime-local = ["sounddevice"]`——拆分发生在 v2.0.10，前者不再逼装 PortAudio；`tui = ["textual>=8.2,<9"]`（`pyproject.toml`）：

```toml
# ------------ Realtime voice ------------
realtime = [
    "websockets>=13",
]
realtime-local = ["sounddevice"]
# ------------ Terminal UI ------------
tui = [
    "textual>=8.2,<9",
]
```

- **`aiortc>=1.14` 挂在 `service` extra**，不在 `realtime`；而 offer 端点的 ImportError 提示是 `"Install agentscope[realtime]"`（`app/_router/_realtime.py`）——按提示装完仍缺 aiortc。`service` extra（`pyproject.toml`）：

```toml
# ------------ Service ------------
service = [
    "fastapi",
    "uvicorn",
    "apscheduler",
    "ag-ui-protocol>=0.1.10",
    "aiortc>=1.14",
]
```

- `full` 含 `[realtime]` 与 `[tui]`，**不含** `[realtime-local]`（`pyproject.toml`）：

```toml
# ------------ Full ------------
full = [
    "agentscope[models]",
    "agentscope[classifiers]",
    "agentscope[service]",
    "agentscope[realtime]",
    "agentscope[storage-redis]",
    "agentscope[storage-sql]",
    "agentscope[storage-s3]",
    "agentscope[channel]",
    "agentscope[workspace]",
    "agentscope[tools]",
    "agentscope[tui]",
```

> 上面 `full` 列表尾部用省略处理，未列出 `[a2a]` / `[rag]` 等其余项。

- **PyYAML 未声明为依赖**：`ASRModelCard.from_yaml` 与 `TTSModelCard.from_yaml` 都 `import yaml` + `yaml.safe_load`（`asr/_asr_model_card.py`、`tts/_tts_model_card.py`），只能靠传递依赖。
- package-data 只列 `_models/*.yaml` 与 `_cosyvoice_models/*.yaml`，`_audio_models/*.yaml` 未列，而 `DashScopeAudioRealtimeModel.list_models()` 显式扫描它（`realtime/_dashscope/_audio_model.py`）；仓库无 `MANIFEST.in`、无 setuptools_scm（`pyproject.toml`）：

```toml
[tool.setuptools.package-data]
# ``"*"`` applies to every discovered package. Patterns:
# - ``py.typed`` marks the typed package per PEP 561.
# - ``_models/*.yaml`` reaches into the data-only ``_models/``
#  subdirs that ship with each model provider (they have no
#   ``__init__.py`` and are not packages, but the files still
#   live alongside the parent package's source on disk).
"*" = [
    "py.typed",
    "_models/*.yaml",
    "_cosyvoice_models/*.yaml",
]
```

## Links

- [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)
- [Realtime 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Realtime.md)
- [App 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/App.md)
- [TUI 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/TUI.md)
- [Model 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Model.md)
- [Memory 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Memory.md)

## References

- [AgentScope v2.0.11 — asr/_asr_base.py](https://github.com/agentscope-ai/agentscope/blob/v2.0.11/src/agentscope/asr/_asr_base.py)
- [AgentScope v2.0.11 — tts/_tts_base.py](https://github.com/agentscope-ai/agentscope/blob/v2.0.11/src/agentscope/tts/_tts_base.py)
- [AgentScope v2.0.11 — realtime/_base.py](https://github.com/agentscope-ai/agentscope/blob/v2.0.11/src/agentscope/realtime/_base.py)
- [AgentScope v2.0.11 — app/_service/_webrtc_audio_transport.py](https://github.com/agentscope-ai/agentscope/blob/v2.0.11/src/agentscope/app/_service/_webrtc_audio_transport.py)
- [AgentScope v2.0.11 — pyproject.toml](https://github.com/agentscope-ai/agentscope/blob/v2.0.11/pyproject.toml)
