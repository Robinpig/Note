## Introduction

AgentScope 的模型层把「统一 `Msg` 序列 → 厂商 JSON」的翻译收拢到 formatter，模型子类只注入 formatter 与 `_format_tools`。调用层是 retry 包着的直通线，流式累加按 block.id 做键。本分册从主干笔记拆出，保留 v2.0.8 源码事实。主干见 [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope.md)。

## Model Abstraction

### Model Inventory and Call Flow

`ChatModelBase`（`model/_base.py`）之下有 10 个厂商子模块：`_anthropic _dashscope _deepseek _gemini _moonshot _ollama _openai_chat _openai_response _volcengine _xai`，每个里 `_model.py` + `_models/*.yaml` 卡片清单。

`__call__`（`_base.py:182`）的流程是一条 retry 包着的直通线：

```python
for attempt in range(max_retries + 1):
    response = await self._call_api(...)
    if isinstance(response, ChatResponse):
        return response
    return self._stream(response)      # 否则包成 async generator
```

`CancelledError` 被单独捕获，返回 `finished_reason=INTERRUPTED` 的空响应而不是抛出——这让「取消」在 AgentScope 里永远是一条正常路径。默认参数是 `stream=True, max_retries=3, retry_delay=1.0, context_size=32768`。

**formatter 不在基类里**，由各子类 `__init__` 注入（如 `self.formatter = formatter or OpenAIChatFormatter()`）。**工具 JSON schema 也不归 formatter 管**，由 model 子类自己的 `_format_tools` 负责。这两件事读代码时容易找错地方。

### Retry Is Allowlisted

重试只对 `_get_retryable_exceptions()` 声明的类型生效，其它异常立即向上抛。各厂商声明得相当克制：OpenAI 系 / DashScope / DeepSeek / Moonshot / Volcengine 用 `APIConnectionError / APITimeoutError / RateLimitError / InternalServerError`；Anthropic 用自己的同名四件套；Gemini 用 `google.genai.errors.APIError`；Ollama 落到 `httpx` 传输层；xAI 用 `grpc.RpcError`。

### Stream Accumulation by Block ID

`_StreamAccumulator`（`model/_utils.py`）用 **`block.id` 做键的有序 dict** 累积 SSE 分片，四个累加器分别处理 Text / Thinking / ToolCall / Data。

两个实现细节值得学：

- **类型变化时丢弃重建**——同一个 id 如果后到的分片类型变了，宁可重来也不混合
- **audio 分片先 `b64decode` 存 bytes，build 时一次性 encode**——因为 base64 padding 会跨分片截断，边写边 encode 必然出错
- Thinking 累加器额外用 `model_extra` 回填 Anthropic 的 `signature`（丢了签名下一轮就回灌不了，见上一节）

源码注释写明它是为了替换掉早期 O(n²) 的 `ChatResponse.append_chat_response`。

### Structured Output Fallback

`generate_structured_output()` 是压缩、structured reply 等场景的基础。它不是单一策略，而是四级 fallback 链：

```
forced（强制 tool_choice）→ auto（自动）→ no_think（关 thinking + 强制 tool_choice）→ none（不强制）
```

实际代码（`model/_base.py:505`）是一条「最优优先」的策略元组：

```python
strategies = (
    ("forced", {}, forced_tc),
    ("auto", {}, ToolChoice(mode="auto")),
    *(("no_think", disable_kwargs, forced_tc),) if disable_kwargs else ()),
    ("none", {}, None),
)
```

三个容易漏看的点：

- **`no_think` 这一级是条件插入的**——只有 `_get_disable_thinking_kwargs()` 返回非空（即厂商支持关 thinking）时才存在。各厂商的参数形态差别很大：DashScope 是 `{"extra_body": {"enable_thinking": False}}`，Anthropic 是 `{"thinking": {"type": "disabled"}}`，DeepSeek / Moonshot / Volcengine 是 `{"extra_body": {"thinking": {"type": "disabled"}}}`
- **调用方显式传 `tool_choice` 时整条链退化为单策略** `("explicit", ...)`——用户明确指定了就不该再 fallback
- 每级内部再跑 `max_retries + 1` 次，且**只有** `StructuredOutputError` 和厂商声明的 fallback 异常会跳到下一级

单次尝试的做法是注入一个名为 `generate_structured_output` 的 function tool 加一段 `<system-reminder>` 指令，dict schema 走 `jsonschema.validate`、Pydantic 走 `model_validate`。

### Token Counting

`count_tokens()` 的实现简单到出乎意料：把所有 TextBlock/ThinkingBlock/ToolCallBlock/ToolResultBlock/HintBlock 里的文本拼起来，加上工具 JSON schema，**总字节数 / 4** 加一个 block 固定 2000 token。源码里明写了这是 quick estimate，子类可以覆盖。

这和前面 RAG 里 `ApproxTokenChunker` 的 `// 4` 是同一个取舍——宁可估得粗，也不引入 tokenizer 依赖。

### Credential Factory

凭据层（`credential/`）用 Pydantic 的 discriminator 联合类型做注册与发现：

```python
# credential/_factory.py:50
_adapter = TypeAdapter(
    Annotated[Union[OpenAICredential, AnthropicCredential, ...],
             Field(discriminator="type")]
)
```

9 个类静态预注册，`get_credential_class(provider)` 遍历时用 `get_type_hints` 取出 `type` 字段的 `Literal` args 来比字符串。discriminator 取值也就是你要传给它的 provider 字符串：`openai_credential` / `anthropic_credential` / `gemini_credential` / `dashscope_credential` / `deepseek_credential` / `moonshot_credential` / `ollama_credential` / `xai_credential` / `volcengine_credential`。

需要说明的是——**credential 包内不存在任何环境变量读取**（全树无 `os.getenv`）。`OPENAI_API_KEY` 这类名字只出现在示例代码里，是约定不是框架机制。

### Embedding and TTS

顺带一提两个边缘子系统，接口都窄到只有一个抽象方法：

- `EmbeddingModelBase`（`embedding/_embedding_base.py`）——`__call__(inputs, **kwargs)` 按 `batch_size` 切批后 `asyncio.gather` 并发，最后按序 merge 保序；`TextBlock` 入参自动解包取 `.text`。另有 `EmbeddingCacheBase` / `FileEmbeddingCache`
- `TTSModelBase`（`tts/_tts_base.py`）——`synthesize()` 唯一抽象，`push()` 非阻塞且可能返回空 `TTSResponse`；`connect()` / `close()` 只对 realtime 场景有意义



## Links

- [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope.md)

## References

- `src/agentscope/model/_base.py` / `_utils.py`
- `src/agentscope/embedding/_embedding_base.py` / `tts/_tts_base.py`
- `src/agentscope/credential/_factory.py`
