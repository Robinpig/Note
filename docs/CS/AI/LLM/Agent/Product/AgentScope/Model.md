## Introduction

AgentScope 的模型层把「统一 `Msg` 序列 → 厂商 JSON」的翻译收拢到 formatter，模型子类只注入 formatter 与 `_format_tools`。调用层是 retry 包着的直通线，流式累加按 block.id 做键。本分册从主干笔记拆出，按 v2.0.11 源码重核（计数、MiniMax 与 CredentialFactory 机制均已更新）。主干见 [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)。

## Model Abstraction

### Model Inventory and Call Flow

`ChatModelBase`（`model/_base.py`）之下有 **11 个**厂商子模块：`_anthropic _dashscope _deepseek _gemini _minimax _moonshot _ollama _openai_chat _openai_response _volcengine _xai`，每个里 `_model.py` + `_models/*.yaml` 卡片清单。OpenAI 占 `_openai_chat` / `_openai_response` 两个子模块，故厂商家数为 10；v2.0.9 新增的 `model/_minimax/_model.py` 直接继承 `AnthropicChatModel`，是观察「加一家厂商要动 model / formatter / credential 三层」的最好样本。`model/__init__.py` 另导出 `FinishedReason`。

MiniMax 子类确实直接继承 Anthropic（`model/_minimax/_model.py`）：

```python
class MiniMaxChatModel(AnthropicChatModel):
    """Chat model for MiniMax's Anthropic-compatible API."""

    type: Literal["minimax_chat"] = "minimax_chat"
    """The type of the chat model."""
```

`model/__init__.py` 的导出：

```python
from ._base import ChatModelBase
from ._model_card import ModelCard
from ._model_response import ChatResponse, StructuredResponse, FinishedReason
from ._model_usage import ChatUsage
```

`__call__`（`_base.py`）的流程是一条 retry 包着的直通线。retry 循环本身（`model/_base.py`）：

```python
        retryable = self._get_retryable_exceptions()
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            # The accumulated chat response
            try:
                res = await self._call_api(
                    self.model,
                    messages=messages,
                    tools=tools,
                    tool_choice=tool_choice,
                    **kwargs,
                )
                break
            except asyncio.CancelledError:
                return ChatResponse(
                    content=[],
                    is_last=True,
                    finished_reason=FinishedReason.INTERRUPTED,
                )

            except Exception as e:
                if not isinstance(e, retryable):
                    raise
                last_error = e
```

拿到结果后，非流式直接返回 `ChatResponse`，否则包成 async generator（同文件）：

```python
        # =====================================================================
        # Consume the model calling result
        # =====================================================================
        if isinstance(res, ChatResponse):
            return res

        async def _stream() -> AsyncGenerator[ChatResponse, None]:
            """The wrapper around model calling."""
            # For backward compatibility
            yield_acc_res = True
            acc_res = _StreamAccumulator()
```

`CancelledError` 被单独捕获，返回 `finished_reason=INTERRUPTED` 的空响应而不是抛出——这让「取消」在 AgentScope 里永远是一条正常路径。默认参数是 `stream=True, max_retries=3, retry_delay=1.0, context_size=32768`（`model/_base.py` 的构造器 docstring）：

```python
            stream (`bool`, defaults to `True`):
                Whether to enable streaming output for the LLM.
            max_retries (`int`, defaults to `3`):
                The maximum number of retries for API calls. Only exceptions
                listed in ``_get_retryable_exceptions()`` count against this
                budget; other exceptions are raised immediately.
            retry_delay (`float`, defaults to `1.0`):
                Seconds to sleep between retry attempts.
            context_size (`int`, defaults to `32768`):
                The model context size used for context compression.
```

**formatter 不在基类里**，由各子类 `__init__` 注入（如 `self.formatter = formatter or OpenAIChatFormatter()`）。**工具 JSON schema 也不归 formatter 管**，由 model 子类自己的 `_format_tools` 负责。这两件事读代码时容易找错地方。

### Retry Is Allowlisted

重试只对 `_get_retryable_exceptions()` 声明的类型生效，其它异常立即向上抛。各厂商声明得相当克制：OpenAI 系 / DashScope / DeepSeek / Moonshot / Volcengine 用 `APIConnectionError / APITimeoutError / RateLimitError / InternalServerError`；Anthropic 用自己的同名四件套；Gemini 用 `google.genai.errors.APIError`；Ollama 落到 `httpx` 传输层；xAI 用 `grpc.RpcError`。

基类默认返回空元组，即「不重试」（`model/_base.py`）：

```python
    @classmethod
    def _get_retryable_exceptions(cls) -> tuple[Type[Exception], ...]:
        """Return the exception types that should trigger a retry.

        Defaults to an empty tuple (no retries). Subclasses can override to
        declare provider-specific retryable exceptions. SDK exception types
        should be imported lazily inside the override so the SDK stays an
        optional dependency.
        """
        return ()
```

### Stream Accumulation by Block ID

`_StreamAccumulator`（`model/_utils.py`）用 **`block.id` 做键的有序 dict** 累积 SSE 分片，四个累加器分别处理 Text / Thinking / ToolCall / Data。

类定义与 docstring（`model/_utils.py`）：

```python
class _StreamAccumulator:
    """Accumulates the streaming ``ChatResponse`` deltas of one model call.

    Each block keeps its deltas in a fragment list that is joined exactly
    once in ``build``, which makes the accumulation O(n) in the total
    payload size. The ``ChatResponse.append_chat_response`` it replaces
    grows the blocks with ``block.field += delta`` instead, which is
    O(n^2) for large payloads (e.g. tool call arguments of 100k+ chars)
    and can block the event loop long enough to drop the connection.
    """

    def __init__(self) -> None:
        """Initialize an empty accumulator."""
        # Keyed by block id, the insertion order is the block order
        self._blocks: dict[str, _AccBlock] = {}
```

两个实现细节值得学：

- **类型变化时丢弃重建**——同一个 id 如果后到的分片类型变了，宁可重来也不混合。分支（`model/_utils.py`）：

```python
        for block in chat_response.content:
            acc = self._blocks.get(block.id)
            if acc is not None and acc.type != block.type:
                logger.warning(
                    "Block %s changed its type from %s to %s during "
                    "streaming, dropping the accumulated fragments.",
                    block.id,
                    acc.type,
                    block.type,
                )
                acc = None
```

- **audio 分片先 `b64decode` 存 bytes，build 时一次性 encode**——因为 base64 padding 会跨分片截断，边写边 encode 必然出错。累加器源码（`model/_utils.py`）：

```python
class _AccBase64Source(Base64Source):
    """The accumulating counterpart of ``Base64Source`` for audio streams,
    whose ``data`` field holds the raw decoded bytes of each delta.

    Base64 strings cannot be concatenated directly: a delta whose byte
    length is not a multiple of three is padded with ``=``, and everything
    after that padding is silently dropped on decoding. So each delta is
    decoded on arrival and the bytes are encoded once in ``build``.
    """

    data: list[bytes] = Field(  # type: ignore[assignment]
        default_factory=list,
    )

    def append(self, source: Base64Source) -> None:
        """Decode one delta source and collect its raw bytes.
        ...
        """
        if source.data:
            self.data.append(base64.b64decode(source.data))

    def build(self) -> Base64Source:
        """Join the raw bytes and base64-encode them once."""
        data = b"".join(self.data)
        if self.media_type == "audio/wav":
            # The stream began with the placeholder WAV header; now that
            # the buffer is complete, declare its real chunk sizes.
            data = _finalize_streaming_wav(data)
        return Base64Source(
            data=base64.b64encode(data).decode("ascii"),
            media_type=self.media_type,
        )
```

> 上面 `append` 的 docstring Args 段用 `...` 标注省略。

- Thinking 累加器额外用 `model_extra` 回填 Anthropic 的 `signature`（丢了签名下一轮就回灌不了，见上一节）

源码注释写明它是为了替换掉早期 O(n²) 的 `ChatResponse.append_chat_response`。

### Structured Output Fallback

`generate_structured_output()` 是压缩、structured reply 等场景的基础。它不是单一策略，而是四级 fallback 链：

```
forced（强制 tool_choice）→ auto（自动）→ no_think（关 thinking + 强制 tool_choice）→ none（不强制）
```

实际代码（`model/_base.py`）是一条「最优优先」的策略元组：

```python
        user_tool_choice = kwargs.pop("tool_choice", None)
        if user_tool_choice is None:
            forced_tc = ToolChoice(mode="generate_structured_output")
            disable_kwargs = self._get_disable_thinking_kwargs()
            # (name, extra `_call_api` kwargs, tool_choice), best first.
            # The no-think strategy only applies when the provider can
            # toggle it.
            strategies = (
                ("forced", {}, forced_tc),
                ("auto", {}, ToolChoice(mode="auto")),
                *(
                    (("no_think", disable_kwargs, forced_tc),)
                    if disable_kwargs
                    else ()
                ),
                ("none", {}, None),
            )
        else:
            strategies = (("explicit", {}, user_tool_choice),)
```

三个容易漏看的点：

- **`no_think` 这一级是条件插入的**——只有 `_get_disable_thinking_kwargs()` 返回非空（即厂商支持关 thinking）时才存在。各厂商的参数形态差别很大：DashScope 是 `{"extra_body": {"enable_thinking": False}}`，Anthropic 是 `{"thinking": {"type": "disabled"}}`，DeepSeek / Moonshot / Volcengine 是 `{"extra_body": {"thinking": {"type": "disabled"}}}`
- **调用方显式传 `tool_choice` 时整条链退化为单策略** `("explicit", ...)`——用户明确指定了就不该再 fallback
- 每级内部再跑 `max_retries + 1` 次，且**只有** `StructuredOutputError` 和厂商声明的 fallback 异常会跳到下一级

单次尝试的做法是注入一个名为 `generate_structured_output` 的 function tool 加一段 `<system-reminder>` 指令，dict schema 走 `jsonschema.validate`、Pydantic 走 `model_validate`。

### Token Counting

`count_tokens()` 的实现简单到出乎意料：把所有 TextBlock/ThinkingBlock/ToolCallBlock/ToolResultBlock/HintBlock 里的文本拼起来，加上工具 JSON schema，**总字节数 / 4** 加一个 block 固定 2000 token。源码里明写了这是 quick estimate，子类可以覆盖。

docstring 与最后的计算（`model/_base.py`）：

```python
        """A quick and unified method to estimate the token count of the
        model input by dividing the total input size in bytes by 4.

        Note a standard way to count the tokens is first formatting the input
        messages into the API required format, then use the tokenizer of the
        underlying API to count the tokens.

        Subclasses may override this method to provide a more accurate
        implementation tailored to their specific tokenizer.
        ...
        """
```

> 上面 docstring 的 Args / Returns 段用 `...` 标注省略。

```python
        # Add the multimodal tokens. Binary payloads are not consumed by
        # multimodal models as base64 text, and file URLs should not count as
        # only a path string. Use a stable flat estimate for all DataBlocks.
        cnt += len(data_blocks) * _MULTIMODAL_DATA_BLOCK_TOKEN_ESTIMATE

        # Count the text tokens
        acc_text = "".join(acc_texts)
        cnt += int(len(acc_text.encode("utf-8")) / 4 + 0.5)

        return cnt
```

那个固定 2000 的常量（同文件）：

```python
_MULTIMODAL_DATA_BLOCK_TOKEN_ESTIMATE = 2000
```

这和前面 RAG 里 `ApproxTokenChunker` 的 `// 4` 是同一个取舍——宁可估得粗，也不引入 tokenizer 依赖。

### Credential Factory

凭据层（`credential/`）用 Pydantic 的 discriminator 联合类型做注册与发现。v2.0.11 的 `_classes` 注册表与惰性 `_get_adapter()`（`credential/_factory.py`）：

```python
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
    _adapter: TypeAdapter[CredentialBase] | None = None

    @classmethod
    def _get_adapter(cls) -> TypeAdapter[CredentialBase]:
        if cls._adapter is None:
            union = Annotated[  # type: ignore[valid-type]
                Union[tuple(cls._classes)],
                Field(discriminator="type"),
            ]
            cls._adapter = TypeAdapter(union)
        return cls._adapter
```

v2.0.11 的注册表是 **10 个类**（`credential/_factory.py`），机制从静态 `_adapter` 改成 `_classes` 列表 + 惰性 `_get_adapter()`，并新增 `register_credential()`。`get_credential_class(provider)` 仍用 `get_type_hints` 取出 `type` 字段的 `Literal` args 来比字符串。discriminator 取值也就是你要传给它的 provider 字符串：`openai_credential` / `anthropic_credential` / `gemini_credential` / `dashscope_credential` / `deepseek_credential` / `moonshot_credential` / `ollama_credential` / `xai_credential` / `volcengine_credential` / `minimax_credential`。

`register_credential()` 与 `get_credential_class()`（同文件）：

```python
    @classmethod
    def register_credential(cls, credential_cls: Type[CredentialBase]) -> None:
        """Register a custom :class:`CredentialBase` subclass.

        The class must define a ``type`` field with a unique ``Literal``
        default so Pydantic can use it as a discriminator.
        ...
        """
        if credential_cls in cls._classes:
            return
        cls._classes.append(credential_cls)
        cls._adapter = None  # invalidate so it's rebuilt on next use
```

```python
    @classmethod
    def get_credential_class(
        cls,
        provider: str,
    ) -> Type[CredentialBase] | None:
        """Return the credential class for the given provider type, or None.
        ...
        """
        for c in cls._classes:
            hints = get_type_hints(c)
            type_hint = hints.get("type")
            if type_hint is None:
                continue
            args = get_args(type_hint)

            if args and args[0] == provider:
                return c
        return None
```

> 上面两个方法的 docstring 参数/返回段用 `...` 标注省略。

需要说明的是——**credential 包内不存在任何环境变量读取**（全树无 `os.getenv`）。`OPENAI_API_KEY` 这类名字只出现在示例代码里，是约定不是框架机制。

### Embedding and TTS

顺带一提两个边缘子系统，接口都窄到只有一个抽象方法：

- `EmbeddingModelBase`（`embedding/_embedding_base.py`）——`__call__(inputs, **kwargs)` 按 `batch_size` 切批后 `asyncio.gather` 并发，最后按序 merge 保序；`TextBlock` 入参自动解包取 `.text`。另有 `EmbeddingCacheBase` / `FileEmbeddingCache`
- `TTSModelBase`（`tts/_tts_base.py`）——`synthesize()` 唯一抽象，`push()` 非阻塞且可能返回空 `TTSResponse`；`connect()` / `close()` 只对 realtime 场景有意义

两个基类的 docstring（`embedding/_embedding_base.py` / `tts/_tts_base.py`）：

```python
    - ``__call__`` splits inputs into batches of size
      :attr:`batch_size`, calls :meth:`_call_api` for each batch
      **concurrently** via :func:`asyncio.gather`, and merges the
      results.  Each batch call is wrapped with retry logic.
    - Subclasses only implement :meth:`_call_api` for a **single
      batch** — no batching or retry code needed.
```

```python
    For non-realtime TTS models, only :meth:`synthesize` needs to be
    implemented. For realtime TTS models, the lifecycle is managed via the
    async context manager (``async with model: ...``) or by calling
    :meth:`connect` / :meth:`close` manually; :meth:`push` appends text
    chunks and returns whatever audio is currently available, while
    :meth:`synthesize` blocks until the full speech has been synthesized.
```

```python
    stream: bool
    """Whether to use streaming output if supported by the model."""

    realtime: bool = False
    """Whether the TTS model supports realtime (streaming-input) mode."""
```

### Model Instantiation and Structured Output

构造一个 chat 模型只需凭据 + 模型名（formatter 与 `_format_tools` 由子类在 `__init__` 注入，无需用户传）。结构化输出有两种入口——直接走模型，或交给 Agent 在 `reply()` 时声明：

```python
from pydantic import BaseModel
from agentscope.agent import Agent
from agentscope.credential import OpenAICredential
from agentscope.message import UserMsg
from agentscope.model import OpenAIChatModel
from agentscope.tool import Toolkit

model = OpenAIChatModel(
    credential=OpenAICredential(api_key="sk-..."),
    model="gpt-4.1", stream=True, max_retries=3,
)

# 入口 1：模型直出结构化对象（四级 fallback 链见上文）
class Answer(BaseModel):
    lang: str
    summary: str

resp = await model.generate_structured_output(
    messages=[UserMsg(name="user", content="用一句话介绍 AgentScope。")],
    structured_model=Answer,          # 也可传 dict schema
)
print(resp.content)                   # Answer 实例（或 None）

# 入口 2：交给 Agent，reply 返回 Msg，结构化结果进 Msg.structured_output
agent = Agent(name="a", system_prompt="...", model=model, toolkit=Toolkit())
reply = await agent.reply(
    UserMsg(name="user", content="..."),
    structured_schema=Answer,         # Agent.reply / reply_stream 都接受
)
data = reply.structured_output        # dict（不是 Answer 实例）
```

两个易混点：① 模型直出的 `generate_structured_output` 返回的是**模型实例**（`structured_model` 是 `BaseModel` 子类时），而经 Agent 的 `structured_schema` 落到 `Msg.structured_output` 里的是**字典**——Agent 层统一把结构反序列化成 `dict` 透传给上层，避免把 Pydantic 依赖强加给调用方；② 模型直出时若显式传了 `tool_choice`，整条 fallback 链退化为单策略 `("explicit", ...)`，不会再做 forced→auto→no_think 的降级尝试。`stream=True` 下走流式累加（见 `Stream Accumulation by Block ID`）；非流式则直接拿整条 `ChatResponse`。



## Vendor Module Inventory

主干已说明 `ChatModelBase` 之下有 11 个厂商子模块，这里逐一列出每个子模块注入的 formatter 与各自的 `_format_tools` 落点。每个子模块同时携带 `_models/*.yaml` 模型卡片，`ChatModelBase.list_models`（`model/_base.py`）按子类源文件旁的 `_models` 目录加载，与主干「卡片清单」一致。

| 子模块目录 | 公开 ChatModel 类 | 注入的 formatter（默认） | `_format_tools` 定义位置 |
| :--- | :--- | :--- | :--- |
| `_anthropic` | `AnthropicChatModel` | `AnthropicChatFormatter`（`_anthropic/_model.py`） | `_anthropic/_model.py` |
| `_dashscope` | `DashScopeChatModel` | `DashScopeChatFormatter`（`_dashscope/_model.py`） | `_dashscope/_model.py` |
| `_deepseek` | `DeepSeekChatModel` | `DeepSeekChatFormatter`（`_deepseek/_model.py`） | `_deepseek/_model.py` |
| `_gemini` | `GeminiChatModel` | `GeminiChatFormatter`（`_gemini/_model.py`） | `_gemini/_model.py` |
| `_moonshot` | `MoonshotChatModel` | `MoonshotChatFormatter`（`_moonshot/_model.py`） | `_moonshot/_model.py` |
| `_ollama` | `OllamaChatModel` | `OllamaChatFormatter`（`_ollama/_model.py`） | `_ollama/_model.py` |
| `_openai_chat` | `OpenAIChatModel` | `OpenAIChatFormatter`（`_openai_chat/_model.py`） | `_openai_chat/_model.py` |
| `_openai_response` | `OpenAIResponseModel` | `OpenAIResponseFormatter`（`_openai_response/_model.py`） | `_openai_response/_model.py` |
| `_volcengine` | `VolcengineChatModel` | `VolcengineChatFormatter`（`_volcengine/_model.py`） | `_volcengine/_model.py` |
| `_xai` | `XAIChatModel` | `XAIChatFormatter`（`_xai/_model.py`） | `_xai/_model.py` |

两个值得记的结构事实：

- **formatter 与 `_format_tools` 都收在子类里，不在 `ChatModelBase`**。基类只声明 `_get_retryable_exceptions` / `_get_disable_thinking_kwargs` / `_get_structured_output_fallback_exceptions` 三个可被子类覆盖的 hook（`model/_base.py`）。工具 schema 的序列化由各子类自己的 `_format_tools` 完成，因为不同厂商的 tool 形状（尤其 xAI 走 protobuf）差异太大，无法在基类统一。
- **OpenAI 在模型层其实有两个子模块**：`_openai_chat`（Chat Completions）与 `_openai_response`（Responses API）。两者 formatter 不同、模型类不同，但共用 `_OpenAIFormatterBase` 的多模态转换逻辑（`_openai_formatter.py`）。主干 Formatter Layer 把「OpenAI」列成一个厂商名，实际对应两个 formatter 文件，这是下文差异表要补的关键点。

三个 hook 的真实定义（`model/_base.py`）：

```python
    @classmethod
    def _get_retryable_exceptions(cls) -> tuple[Type[Exception], ...]:
        ...
        return ()

    def _get_disable_thinking_kwargs(self) -> dict:
        """Return kwargs that disable thinking for this provider.

        Subclasses whose API supports a thinking/reasoning toggle
        should override this to return the appropriate kwargs dict
        (e.g. ``{"extra_body": {"enable_thinking": False}}``).

        Used by the structured-output fallback mechanism.
        """
        return {}

    @classmethod
    def _get_structured_output_fallback_exceptions(
        cls,
    ) -> tuple[Type[Exception], ...]:
        """Provider exceptions that indicate the request shape was rejected
        (e.g. a forced ``tool_choice`` while thinking is enabled), so that
        another structured-output strategy may succeed. Subclasses should
        return the provider's bad-request exception types; the default is
        empty, i.e. only local structured-output failures trigger a fallback.
        """
        return ()
```

> 上面第一个 hook 的 docstring 用 `...` 标注省略（完整版本见 `Retry Is Allowlisted`）。

## Formatter Multi-Vendor Differences

主干的「Four Vendors, Four Divergent Choices」只展开了 OpenAI / Anthropic / Gemini / DashScope 四家。这里把 v2.0.11 全部 11 个厂商 formatter 文件的差异逐列补齐，所有单元格均来自源码核实。`FormatterBase` 的单一抽象方法 `format()`（`formatter/_formatter_base.py`）返回完整 `list[dict]`（xAI 例外，见下文）。

基类的抽象签名（`formatter/_formatter_base.py`）：

```python
    @abstractmethod
    async def format(self, *args: Any, **kwargs: Any) -> list[dict[str, Any]]:
        """Format the Msg objects to a list of dictionaries that satisfy the
        API requirements."""
```

| Vendor（formatter 类） | 消息形状 | system prompt | tool call | tool result | 多模态 input_types | ThinkingBlock |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Anthropic（`AnthropicChat` / `AnthropicMultiAgent`，`_anthropic_formatter.py`） | `{role, content[]}` | MultiAgent 单独 system 消息；Chat 由 model 层从首条 pop 进 `kwargs["system"]`（`_anthropic/_model.py`） | `{type:tool_use, id, name, input(字典)}` | `{type:tool_result, tool_use_id}` 必须包在 `role:user` | `image/*` / `application/pdf`，全部 base64 | 有 `signature` 才保留，否则丢弃；`redacted_thinking_data` 还原为 `redacted_thinking` |
| OpenAI Chat（`OpenAIChat` / `OpenAIMultiAgent`，`_openai_formatter.py`） | `{role, name, content[]}` | MultiAgent 首条 system 单独生成 | `tool_calls[]` + `function.arguments` | `{role:tool, tool_call_id}` | `text/plain` / `image/*` / `audio/*` / `application/pdf` | **丢弃** |
| OpenAI Response（`OpenAIResponse` / `OpenAIResponseMultiAgent`，`_openai_response_formatter.py`） | input items：`input_text` / `input_image` / `function_call` / `function_call_output` | 独立 `system` 项 | `{type:function_call, call_id, name, arguments}` | `{type:function_call_output, call_id, output}` | `text/plain` / `image/*` / `application/pdf`，**不含 audio** | 带 `reasoning_item_id` 时原样回放 |
| Gemini（`GeminiChat` / `GeminiMultiAgent`，`_gemini_formatter.py`） | `{role, parts[]}`，assistant 改 `model` | **降级为 `role:user`** | `{function_call:{id,name,args(字典)}}` | `{function_response:{id,name,response:{output}}}` | `text` / `image/*` / `audio/*` / `video/*` / `application/pdf` | `{thought:true, text}`，空则跳过 |
| DashScope（`DashScopeChat` / `DashScopeMultiAgent`，`_dashscope_formatter.py`） | OpenAI 兼容 + 扩展 | 同 OpenAI | `tool_calls[]` + `function.arguments` | `{role:tool, tool_call_id}` | `text` / `image/*` / `audio/*` / `video/*`（含 `application/x-thinking`） | **唯一支持回灌**：`reasoning_content` 字段，`supports_thinking_input` 开关控制 |
| DeepSeek（`DeepSeekChat` / `DeepSeekMultiAgent`，`_deepseek_formatter.py`） | OpenAI 兼容 `{role, content}` | 同 OpenAI（独立 system 消息） | `tool_calls[]` + `function.arguments` | `{role:tool, tool_call_id}` | **仅 `text/plain`** | `reasoning_content` 保留在**所有** assistant 消息（即使空也带字段） |
| Moonshot（`MoonshotChat` / `MoonshotMultiAgent`，`_moonshot_formatter.py`，继承 `_OpenAIFormatterBase`） | OpenAI 兼容 | 同 OpenAI | `tool_calls[]` + `function.arguments` | `{role:tool, tool_call_id}` | `text` / `image/*` / `audio/*` | `reasoning_content` 保留（Preserved Thinking） |
| Ollama（`OllamaChat` / `OllamaMultiAgent`，`_ollama_formatter.py`） | `{role, content, images[]}` | 同 OpenAI（独立 system 消息） | `tool_calls[]`，`function.arguments` 为**字典** | `{role:tool, tool_name}`（**非** `tool_call_id`） | **仅 `image/*`**，base64 字符串列表 | **丢弃** |
| Volcengine（`VolcengineChat` / `VolcengineMultiAgent`，`_volcengine_formatter.py`，继承 `_OpenAIFormatterBase`） | OpenAI 兼容 | 同 OpenAI | `tool_calls[]` + `function.arguments` | `{role:tool, tool_call_id}` | `text` / `image/*` / `video/*` | `reasoning_content` 保留 |
| xAI（`XAIChat` / `XAIMultiAgent`，`_xai_formatter.py`） | **protobuf `Message` 对象，不是 dict** | `system()` / `user()` / `assistant()` 构造 | `tool_calls`（`TOOL_CALL_TYPE_CLIENT_SIDE_TOOL`） | `tool_result()` proto | **仅 `image/jpeg` / `image/png`** | **丢弃** |

几个逐行核实出来的、主干四家表没覆盖的硬差异：

- **tool result 的并行合并**：Anthropic 严格要求并行 `tool_result` 合并进同一条 `role:user`（`_anthropic_formatter.py` 的 `has_tool_result` 标志防止拆分），注释明确写「strict endpoints (e.g. DeepSeek) reject with 400」。这解释了为什么主干说「拆开会 400」。源码注释（`formatter/_anthropic_formatter.py`）：

```python
                elif isinstance(block, ToolResultBlock):
                    # Only flush when we have non-tool-result content
                    # (i.e. the preceding assistant turn). Once
                    # `has_tool_result` is True we are already accumulating
                    # tool_results into the current user message, so we must
                    # NOT flush on each additional ToolResultBlock — doing so
                    # would split parallel results into separate user messages
                    # which strict endpoints (e.g. DeepSeek) reject with 400.
                    if content_blocks and not has_tool_result:
```

- **Ollama 用 `tool_name` 不用 `tool_call_id`**：按 Ollama 官方 tool-calling spec，结果消息必须带 `tool_name` 字段让模型关联函数（`_ollama_formatter.py`）。源码（`formatter/_ollama_formatter.py`）：

```python
                    # Ollama expects tool results as a separate "tool" role
                    # message, regardless of the containing Msg's role.
                    # Per the Ollama tool-calling spec, the "tool" message
                    # must carry a "tool_name" field (not the OpenAI-style
                    # "tool_call_id") so the model can correlate the result
                    # with the function that produced it — see
                    # https://docs.ollama.com/capabilities/tool-calling
                    messages.append(
                        {
                            "role": "tool",
                            "tool_name": block.name,
                            "content": textual_output,
                        },
                    )
```

- **DeepSeek 的 `reasoning_content` 强制在场**：每轮 assistant 消息都带该字段（无思考时也填空串），否则多轮思考模式上下文非法（`_deepseek_formatter.py`）。
- **xAI 的 `format()` 返回类型不同**：其它 formatter 返回 `list[dict]`，xAI 返回 `list[Any]`（protobuf `chat_pb2.Message`），基类 `format()` 的抽象签名用 `*args, **kwargs` 容忍了这种差异（`formatter/_formatter_base.py`）。xAI 的签名（`formatter/_xai_formatter.py`）：

```python
    # pylint: disable=too-many-statements, too-many-branches
    async def format(
        self,
        msgs: list[Msg],
        **kwargs: Any,
    ) -> List[Any]:
        """Convert a list of ``Msg`` objects to ``xai_sdk`` proto messages.
```

- **音频支持矩阵**：OpenAI / DashScope / Moonshot 支持 audio；OpenAI Response API 明确**不支持 audio**（直接跳过并告警）；Ollama / xAI / DeepSeek 完全不支持音频。

## Cross-Check with Trunk Four Vendors Table

主干「Four Vendors, Four Divergent Choices」表的逐格与源码对照：

| 主干声称 | 源码核实结果 |
| :--- | :--- |
| OpenAI 消息 `{role, name, content[]}` | 准确（`_openai_formatter.py` 确实带 `name`） |
| Anthropic system 由 model 层 pop 进 `kwargs["system"]` | 准确（`_anthropic/_model.py`） |
| Gemini assistant 改 `model`、system 降级为 user | 准确（`_gemini_formatter.py`） |
| DashScope 同 OpenAI + 扩展 | 准确；额外有 `video_url`（`_dashscope_formatter.py`）与 `application/x-thinking` 回灌 |
| Anthropic ThinkingBlock 无 signature 丢弃、有 `redacted_thinking_data` 还原 | 准确（`_anthropic_formatter.py`） |
| Gemini ThinkingBlock `{thought:true}`，空则跳过 | 准确（`_gemini_formatter.py`） |
| DashScope 唯一支持 thinking 回灌 `reasoning_content` | 准确（`supports_thinking_input` 开关） |
| OpenAI ThinkingBlock 丢弃 | 准确（`_openai_formatter.py`） |
| formatter 层无流式概念 | 准确；流式累加在 `model/_utils.py` 的 `_StreamAccumulator`（主干 Model Abstraction 已写） |

厂商计数在 v2.0.11 要重新算：**`formatter/` 目录是 12 个非 `__init__` 的 `.py` = 1 个基类 `_formatter_base.py` + 11 个厂商 formatter 文件**。其中 OpenAI 拆成 `OpenAIChatFormatter` 与 `OpenAIResponseFormatter` 两族，另加 v2.0.9 的 `_minimax_formatter.py`（`MiniMaxChatFormatter` / `MiniMaxMultiAgentFormatter` 继承 Anthropic），所以厂商家数是 **10 家**。旧笔记写的「11 个文件 / 10 家」既少算了文件也没算进 MiniMax；注意别把「11 个 formatter 文件」误读成「11 家厂商」。

MiniMax formatter 的类定义（`formatter/_minimax_formatter.py`）：

```python
class MiniMaxChatFormatter(AnthropicChatFormatter):
    """The MiniMax formatter for chatbot scenario."""

    input_types: list[str] = Field(
        default_factory=lambda: ["text/plain", "image/*", "video/*"],
```

## Credential Factory Nuances

主干 Model Abstraction 已写 `CredentialFactory` 的基本机制，这里补 v2.0.11 下才成立的细节（v2.0.8 的三条旧结论已全部失效）：

- **注册表是 10 个类**（`credential/_factory.py`），不再是静态 `_adapter`，而是 `_classes` 列表 + 惰性 `_get_adapter()` + 新增的 `register_credential()`。`from_dict`、`get_credential_class`、`list_schemas` 三件套职责不变，分别服务「存储反序列化 / 按 provider 查类 / 前端表单」。
- **`credential/_kimi.py` 已不存在**：v2.0.8 那个 0 字节占位文件在 v2.0.11 被删掉；`MoonshotCredential` 仍在 `_moonshot.py`。
- **`credential/_typesafe.py` 已存在**，并新增 `credential/_minimax.py`；全目录仍无 `os.getenv`（凭据不读环境变量这一结论延续）。旧笔记把 `_typesafe.py` 归给 v2.0.10 也不准，它随 v2.0.9 的 classifier 一同进来。

## No LangChain Compatibility Layer

主干称「仓库里没有任何 LangChain 兼容层」。在 v2.0.11 整棵树上执行 `grep -rni "langchain" src/agentscope/` 返回**空**，确认该结论成立：AgentScope 的跨厂商抽象完全自建在 `model/` + `formatter/` + `credential/` 三层，不依赖 LangChain。

## Links

- [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)
- [AgentLoop 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentLoop.md)
- [Classifier 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Classifier.md)
- [VoiceStack 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/VoiceStack.md)
- [Memory 分册](/docs/CS/AI/LLM/Agent/Product/AgentScope/Memory.md)

## References

- [AgentScope v2.0.11 — formatter/](https://github.com/agentscope-ai/agentscope/tree/v2.0.11/src/agentscope/formatter)
- [AgentScope v2.0.11 — credential/_factory.py](https://github.com/agentscope-ai/agentscope/blob/v2.0.11/src/agentscope/credential/_factory.py)
- `src/agentscope/model/_base.py` / `_utils.py`
- `src/agentscope/embedding/_embedding_base.py` / `tts/_tts_base.py`
- `src/agentscope/credential/_factory.py`
