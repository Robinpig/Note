## Introduction

AgentScope 的模型层把「统一 `Msg` 序列 → 厂商 JSON」的翻译收拢到 formatter，模型子类只注入 formatter 与 `_format_tools`。调用层是 retry 包着的直通线，流式累加按 block.id 做键。本分册从主干笔记拆出，保留 v2.0.8 源码事实。主干见 [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)。

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

主干已说明 `ChatModelBase` 之下有 10 个厂商子模块，这里逐一列出每个子模块注入的 formatter 与各自的 `_format_tools` 落点（行号以 v2.0.8 源码为准）。每个子模块同时携带 `_models/*.yaml` 模型卡片，`ChatModelBase.list_models`（`model/_base.py:135`）按子类源文件旁的 `_models` 目录加载，与主干「卡片清单」一致。

| 子模块目录 | 公开 ChatModel 类 | 注入的 formatter（默认） | `_format_tools` 定义位置 |
| :--- | :--- | :--- | :--- |
| `_anthropic` | `AnthropicChatModel` | `AnthropicChatFormatter`（`_anthropic/_model.py:147`） | `_anthropic/_model.py:525` |
| `_dashscope` | `DashScopeChatModel` | `DashScopeChatFormatter`（`_dashscope/_model.py:162`） | `_dashscope/_model.py:478` |
| `_deepseek` | `DeepSeekChatModel` | `DeepSeekChatFormatter`（`_deepseek/_model.py:127`） | `_deepseek/_model.py:400` |
| `_gemini` | `GeminiChatModel` | `GeminiChatFormatter`（`_gemini/_model.py:237`） | `_gemini/_model.py:533` |
| `_moonshot` | `MoonshotChatModel` | `MoonshotChatFormatter`（`_moonshot/_model.py:126`） | `_moonshot/_model.py:404` |
| `_ollama` | `OllamaChatModel` | `OllamaChatFormatter`（`_ollama/_model.py:109`） | `_ollama/_model.py:193` |
| `_openai_chat` | `OpenAIChatModel` | `OpenAIChatFormatter`（`_openai_chat/_model.py:163`） | `_openai_chat/_model.py:554` |
| `_openai_response` | `OpenAIResponseModel` | `OpenAIResponseFormatter`（`_openai_response/_model.py:153`） | `_openai_response/_model.py:482` |
| `_volcengine` | `VolcengineChatModel` | `VolcengineChatFormatter`（`_volcengine/_model.py:129`） | `_volcengine/_model.py:406` |
| `_xai` | `XAIChatModel` | `XAIChatFormatter`（`_xai/_model.py:144`） | `_xai/_model.py:239` |

两个值得记的结构事实：

- **formatter 与 `_format_tools` 都收在子类里，不在 `ChatModelBase`**。基类只声明 `_get_retryable_exceptions` / `_get_disable_thinking_kwargs` / `_get_structured_output_fallback_exceptions` 三个可被子类覆盖的 hook（`model/_base.py:100`、`:111`、`:122`）。工具 schema 的序列化由各子类自己的 `_format_tools` 完成，因为不同厂商的 tool 形状（尤其 xAI 走 protobuf）差异太大，无法在基类统一。
- **OpenAI 在模型层其实有两个子模块**：`_openai_chat`（Chat Completions）与 `_openai_response`（Responses API）。两者 formatter 不同、模型类不同，但共用 `_OpenAIFormatterBase` 的多模态转换逻辑（`_openai_formatter.py:26`）。主干 Formatter Layer 把「OpenAI」列成一个厂商名，实际对应两个 formatter 文件，这是下文差异表要补的关键点。

## Formatter Multi-Vendor Differences

主干的「Four Vendors, Four Divergent Choices」只展开了 OpenAI / Anthropic / Gemini / DashScope 四家。这里把 v2.0.8 全部 10 个厂商 formatter 的差异逐列补齐，所有单元格均来自源码核实。`FormatterBase` 的单一抽象方法 `format()`（`formatter/_formatter_base.py:46`）返回完整 `list[dict]`（xAI 例外，见下文）。

| Vendor（formatter 类） | 消息形状 | system prompt | tool call | tool result | 多模态 input_types | ThinkingBlock |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| Anthropic（`AnthropicChat` / `AnthropicMultiAgent`，`_anthropic_formatter.py:361` / `:398`） | `{role, content[]}` | MultiAgent 单独 system 消息；Chat 由 model 层从首条 pop 进 `kwargs["system"]`（`_anthropic/_model.py:260`） | `{type:tool_use, id, name, input(字典)}`（`_anthropic_formatter.py:165`） | `{type:tool_result, tool_use_id}` 必须包在 `role:user`（`_anthropic_formatter.py:255`） | `image/*` / `application/pdf`，全部 base64（`:307`） | 有 `signature` 才保留，否则丢弃；`redacted_thinking_data` 还原为 `redacted_thinking`（`:84`） |
| OpenAI Chat（`OpenAIChat` / `OpenAIMultiAgent`，`_openai_formatter.py:229` / `:414`） | `{role, name, content[]}` | MultiAgent 首条 system 单独生成（`_openai_formatter.py:556`） | `tool_calls[]` + `function.arguments` | `{role:tool, tool_call_id}`（`:348`） | `text/plain` / `image/*` / `audio/*` / `application/pdf`（`:235`） | **丢弃**（`:384`） |
| OpenAI Response（`OpenAIResponse` / `OpenAIResponseMultiAgent`，`_openai_response_formatter.py:162` / `:399`） | input items：`input_text` / `input_image` / `function_call` / `function_call_output` | 独立 `system` 项（`:531`） | `{type:function_call, call_id, name, arguments}`（`:330`） | `{type:function_call_output, call_id, output}`（`:361`） | `text/plain` / `image/*` / `application/pdf`，**不含 audio**（`:31`） | 带 `reasoning_item_id` 时原样回放（`:273`） |
| Gemini（`GeminiChat` / `GeminiMultiAgent`，`_gemini_formatter.py:111` / `:287`） | `{role, parts[]}`，assistant 改 `model` | **降级为 `role:user`**（`_gemini_formatter.py:440`） | `{function_call:{id,name,args(字典)}}`（`_gemini_formatter.py:204`） | `{function_response:{id,name,response:{output}}}`（`_gemini_formatter.py:232`） | `text` / `image/*` / `audio/*` / `video/*` / `application/pdf`（`:117`） | `{thought:true, text}`，空则跳过（`:157`） |
| DashScope（`DashScopeChat` / `DashScopeMultiAgent`，`_dashscope_formatter.py:219` / `:408`） | OpenAI 兼容 + 扩展 | 同 OpenAI | `tool_calls[]` + `function.arguments` | `{role:tool, tool_call_id}` | `text` / `image/*` / `audio/*` / `video/*`（含 `application/x-thinking`，`:30`） | **唯一支持回灌**：`reasoning_content` 字段，`supports_thinking_input` 开关控制（`:323`） |
| DeepSeek（`DeepSeekChat` / `DeepSeekMultiAgent`，`_deepseek_formatter.py:20` / `:201`） | OpenAI 兼容 `{role, content}` | 同 OpenAI（独立 system 消息） | `tool_calls[]` + `function.arguments` | `{role:tool, tool_call_id}` | **仅 `text/plain`**（`:26`） | `reasoning_content` 保留在**所有** assistant 消息（即使空也带字段，`:181`） |
| Moonshot（`MoonshotChat` / `MoonshotMultiAgent`，`_moonshot_formatter.py:59` / `:277`，继承 `_OpenAIFormatterBase`） | OpenAI 兼容 | 同 OpenAI | `tool_calls[]` + `function.arguments` | `{role:tool, tool_call_id}` | `text` / `image/*` / `audio/*`（`:69`） | `reasoning_content` 保留（Preserved Thinking，`:113`） |
| Ollama（`OllamaChat` / `OllamaMultiAgent`，`_ollama_formatter.py:102` / `:332`） | `{role, content, images[]}` | 同 OpenAI（独立 system 消息，`:475`） | `tool_calls[]`，`function.arguments` 为**字典**（`:278`） | `{role:tool, tool_name}`（**非** `tool_call_id`，`:224`） | **仅 `image/*`**，base64 字符串列表（`:108`） | **丢弃**（`:183`） |
| Volcengine（`VolcengineChat` / `VolcengineMultiAgent`，`_volcengine_formatter.py:87` / `:289`，继承 `_OpenAIFormatterBase`） | OpenAI 兼容 | 同 OpenAI | `tool_calls[]` + `function.arguments` | `{role:tool, tool_call_id}` | `text` / `image/*` / `video/*`（`:93`） | `reasoning_content` 保留（`:271`） |
| xAI（`XAIChat` / `XAIMultiAgent`，`_xai_formatter.py:30` / `:374`） | **protobuf `Message` 对象，不是 dict** | `system()` / `user()` / `assistant()` 构造（`_xai_formatter.py:424`） | `tool_calls`（`TOOL_CALL_TYPE_CLIENT_SIDE_TOOL`，`:261`） | `tool_result()` proto（`:191`） | **仅 `image/jpeg` / `image/png`**（`:41`） | **丢弃**（`:94`） |

几个逐行核实出来的、主干四家表没覆盖的硬差异：

- **tool result 的并行合并**：Anthropic 严格要求并行 `tool_result` 合并进同一条 `role:user`（`_anthropic_formatter.py:182` 的 `has_tool_result` 标志防止拆分），注释明确写「strict endpoints (e.g. DeepSeek) reject with 400」。这解释了为什么主干说「拆开会 400」。
- **Ollama 用 `tool_name` 不用 `tool_call_id`**：按 Ollama 官方 tool-calling spec，结果消息必须带 `tool_name` 字段让模型关联函数（`_ollama_formatter.py:219`）。
- **DeepSeek 的 `reasoning_content` 强制在场**：每轮 assistant 消息都带该字段（无思考时也填空串），否则多轮思考模式上下文非法（`_deepseek_formatter.py:181`）。
- **xAI 的 `format()` 返回类型不同**：其它 formatter 返回 `list[dict]`，xAI 返回 `list[Any]`（protobuf `chat_pb2.Message`），基类 `format()` 的抽象签名用 `*args, **kwargs` 容忍了这种差异（`formatter/_formatter_base.py:47`）。
- **音频支持矩阵**：OpenAI / DashScope / Moonshot 支持 audio；OpenAI Response API 明确**不支持 audio**（`:70` 直接跳过并告警）；Ollama / xAI / DeepSeek 完全不支持音频。

## Cross-Check with Trunk Four Vendors Table

主干「Four Vendors, Four Divergent Choices」表的逐格与源码对照：

| 主干声称 | 源码核实结果 |
| :--- | :--- |
| OpenAI 消息 `{role, name, content[]}` | 准确（`_openai_formatter.py:395` 确实带 `name`） |
| Anthropic system 由 model 层 pop 进 `kwargs["system"]` | 准确（`_anthropic/_model.py:260`） |
| Gemini assistant 改 `model`、system 降级为 user | 准确（`:272`、`:440`） |
| DashScope 同 OpenAI + 扩展 | 准确；额外有 `video_url`（`_dashscope_formatter.py:142`）与 `application/x-thinking` 回灌 |
| Anthropic ThinkingBlock 无 signature 丢弃、有 `redacted_thinking_data` 还原 | 准确（`:84-122`） |
| Gemini ThinkingBlock `{thought:true}`，空则跳过 | 准确（`:157`） |
| DashScope 唯一支持 thinking 回灌 `reasoning_content` | 准确（`:323`、`supports_thinking_input` 开关） |
| OpenAI ThinkingBlock 丢弃 | 准确（`:384`） |
| formatter 层无流式概念 | 准确；流式累加在 `model/_utils.py` 的 `_StreamAccumulator`（主干 Model Abstraction 已写） |

唯一需要修正主干措辞的是厂商计数：**主干写「11 个文件覆盖 OpenAI / Anthropic / Gemini / DashScope / DeepSeek / Moonshot / Ollama / Volcengine / xAI（9 家）」**。实际 v2.0.8 的 `formatter/` 目录是 **11 个 `.py` 文件 = 1 个基类 `_formatter_base.py` + 10 个厂商 formatter**；那 10 个厂商里 OpenAI 拆成了 `OpenAIChatFormatter` 与 `OpenAIResponseFormatter` 两族，所以「厂商」应算 **10 家**而非 9 家（主干把两个 OpenAI 家族合并成一个名字了）。数字「11 个文件」本身成立，只是包含了基类文件。

## Credential Factory Nuances

主干 Model Abstraction 已写 `CredentialFactory` 的基本机制，这里补三个 v2.0.8 下才成立的细节：

- **注册表只有 9 个类**（`credential/_factory.py:37-47`）：`Anthropic` / `DashScope` / `DeepSeek` / `Gemini` / `Moonshot` / `Ollama` / `OpenAI` / `xAI` / `Volcengine`。`from_dict`（`_factory.py:76`）、`get_credential_class`（`_factory.py:88`，用 `get_type_hints` 取 `type` 的 `Literal` 比对）、`list_schemas`（`_factory.py:113`）三件套分别服务「存储反序列化 / 按 provider 查类 / 前端表单」。discriminator 字符串就是传给 `type` 字段的值（`openai_credential` 等），与主干一致。
- **`credential/` 目录里有个 `_kimi.py`，是 0 字节空文件**，既没有类也没有注册进 factory。`MoonshotCredential` 实际在 `_moonshot.py`。这是历史遗留占位，不要误读成「第 10 个凭据类」。
- **v2.0.8 没有 `credential/_typesafe.py`**：主干 Version Delta 把它列为 v2.0.10 新增。以本笔记的 v2.0.8 为准时，`credential/` 只有上表文件，且全目录无 `os.getenv`（凭据不读环境变量，与主干一致）。

## No LangChain Compatibility Layer

主干称「仓库里没有任何 LangChain 兼容层」。在 v2.0.8 整棵树上执行 `grep -rni "langchain" src/agentscope/` 返回**空**，确认该结论成立：AgentScope 的跨厂商抽象完全自建在 `model/` + `formatter/` + `credential/` 三层，不依赖 LangChain。

## Links

- [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)

## References

- `src/agentscope/model/_base.py` / `_utils.py`
- `src/agentscope/embedding/_embedding_base.py` / `tts/_tts_base.py`
- `src/agentscope/credential/_factory.py`
