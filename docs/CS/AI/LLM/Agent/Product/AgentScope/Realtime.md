## Introduction

`RealtimeAgent` 是另一个完全不继承 `Agent` 的类：双向语音会话、无 request/reply 边界，turn-taking 状态机夹在实时模型与 transport 之间。本分册从主干笔记拆出，保留 v2.0.8 源码事实。主干见 [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)。

## Realtime Agent

`RealtimeAgent`（`agent/_realtime/_agent.py:107`）是另一个**完全不继承 `Agent`** 的类：

```python
class RealtimeAgent:
    """A voice agent: a realtime model on one side, a transport on the
    other, and the turn-taking state machine in between.
    Unlike Agent it is bidirectional and has no request/reply boundary."""
```

注意别找错地方——`realtime/_base.py` 里的是 `RealtimeModelBase`（模型适配器基类），不是 Agent。

### Why It Cannot Reuse Agent

| | `Agent` | `RealtimeAgent` |
| :--- | :--- | :--- |
| 调用形态 | `reply()` / `reply_stream()` 一次性请求 | `connect()` / `send()` / `interrupt()` / `reply_stream(transport)` —— 后者是**常驻会话循环**，随 transport 生命周期结束 |
| 中断 | 中断即结束 reply | 需要**双向对齐**：本地立刻静音 + 通知服务端截断，把上下文改写成「用户实际听到的部分」 |
| 工具调用 | 由主循环串接 | `_run_tools()` 跑完后主动 `request_response()` 续接；权限仍走 `PermissionEngine`，ASK 时 `asyncio.wait_for(future, timeout=300)` |
| 上下文清洗 | 由配置驱动压缩 | `TurnAggregator` 清洗语音推断出的轮次边界——`merge_window_ms=800` 内合并被端点检测拆开的句子、`backchannels` 丢弃「嗯」类应答 |

**三层生命周期刻意分离**：Agent 拥有模型会话，transport 归创建者所有，`reply_stream` 只是借用两者。结果是客户端断线重连**不会丢模型会话**。

### Playout and Barge-in

barge-in（用户插话打断）是这套设计里最绕的部分：

```python
async def _barge_in_locked(self):
    position = await self._transport.clear_audio()   # 1. 本地静音，拿回 played_ms
    if position.item_id != reply.item_id: return     # 2. item 不对就放弃截断
    spoken = reply.spoken_prefix(played_ms)          # 3. 按 mark 反查已播文本前缀
    self._truncate_reply(spoken)                     # 4. 改本地上下文
    await self.model.truncate(reply.item_id, played_ms, spoken)  # 5. 改服务端上下文
    await self.model.cancel_response()
```

`_truncate_reply` 刻意**保留非文本块**——已执行的工具调用必须留在记录里，哪怕用户没听到对应的语音。

真正的播放队列在 `LocalAudioTransport`（`_transport/_local.py`）而不是 `_playout.py`——后者只有 19 行，是一个 `PlayoutPosition` 数据模型（`item_id` / `played_ms` / `first_played_at`），文档称它是「截断 barge-in 的唯一声音依据」。`clear_audio()` 会把清队列与上报位置合成一个调用并做 30ms 淡出防爆音，注释说明这是为了让调用者**无法忘记**把 position 喂给 `truncate`。

**VAD 是纯扩展点**：`realtime/_vad.py` 只有 49 行，`VADBase` 是抽象基类，**全树没有任何子类实现也没有阈值参数**（只有 docstring 提到 "Silero v5 wants 512 samples" 作为约束说明）。只有当用户自己传 `vad=` 时，才会把厂商自带的 turn detection 关掉。

「算不算打断」由谁判定取决于 provider 是否拥有 turn detection——有则由 provider 判，否则由 VAD 防抖判。

### Protocol Reality Check

厂商实时协议的形状差异比聊天 API 大得多。以 DashScope 为例（`realtime/_dashscope/_model.py`），连的是 `wss://dashscope.aliyuncs.com/api-ws/v1/realtime`，文档自述「OpenAI 形状但更窄」——**不支持 `conversation.item.truncate`，不支持文本轮次**（`truncation = TruncationSupport.NONE`、`supports_text_input = False`）。

这直接决定了上面那套 barge-in 在不同厂商上的保真度：厂商不支持截断时，服务端上下文里的「用户听到了什么」永远是不准的。

`TruncationSupport` 三值枚举（`NONE / SERVER / EXPLICIT`）就是为这种差异准备的抽象——RealtimeAgent 的代码必须按这三个档次分支。

### A Minimal Voice Session

`RealtimeAgent` 的入口语义和 `Agent` 完全不同：`connect()` 打开模型会话（随 Agent 生命周期，不随 transport）、`reply_stream(transport)` 是**常驻会话循环**、`LocalAudioTransport` 拥有声卡。`async with` 两段式把「模型会话」与「声音设备」刻意分开——前者断了可重建，后者换了不丢会话：

```python
from agentscope.agent._realtime._agent import RealtimeAgent
from agentscope.realtime._transport._local import LocalAudioTransport
# model 是 RealtimeModelBase 子类（如 DashScopeRealtimeModel），此处略

agent = RealtimeAgent("Friday", "Be brief.", model)

async with agent:                              # 打开模型会话（随 Agent 存活）
    async with LocalAudioTransport() as t:     # 占有声卡
        async for event in agent.reply_stream(t):   # 循环直到 transport 结束
            print(event)
```

几个对照上文的落点：① `reply_stream` 的参数是 transport 而不是 `Msg`——因为它没有 request/reply 边界，音频持续流入、事件持续流出；② 三层生命周期分离在这里可见：客户端断开 `LocalAudioTransport` 不会丢 `agent` 持有的模型会话；③ 真要打断正在生成的回复，不能调 `UserInterruptEvent`（那只对 parked reply 有意义），而是取消底层 task，Agent 自己走 `CancelledError` 清理（见 `Why It Cannot Reuse Agent` 表的「中断」行）。注意 `RealtimeAgent` / `LocalAudioTransport` 在 v2.0.8 是**下划线私有路径**，正式导出名请查 `agentscope.agent` / `agentscope.realtime` 的 `__init__`。



## Turn-Taking State Machine

类文档里说的「turn-taking 状态机」不是一个单独的类，而是三块协作件加上 agent 自己的事件派发共同拼出来的：

- **谁在说话由谁来判定**。`vad=` 传入 `RealtimeAgent` 时，provider 自带的 turn detection 被关掉——`connect()` 会发 `turn_detection_disabled=True`（`src/agentscope/agent/_realtime/_agent.py:271-275`），保证「轮次边界」只由一个来源决定；`vad` 为 `None` 时则由 provider 上报 `SpeechStartedEvent` / `SpeechEndedEvent`，agent 只做反应（`_agent.py:167-174`）。
- `VADBase`（`src/agentscope/realtime/_vad.py:15`）是一个抽象边沿检测器：`push()` 只在「语音起止发生的那一帧」返回一个 `SpeechTransition`（`STARTED` / `ENDED`，`_vad.py:7-12,25`）。v2.0.8 里它没有任何子类实现——纯扩展点，与现有笔记一致。
- `TurnAggregator`（`src/agentscope/agent/_realtime/_aggregator.py:8`）在事后把 provider 吐出的 transcript 收拢成干净的用户轮次：`merge_window_ms=800` 把端点检测拆开的半句合并（`_aggregator.py:20,42-66`），`backchannels`（如「嗯」类应答）直接丢弃（`_aggregator.py:21,57`）。

`_on_model_event` 的派发把三者串起来：一个 `SpeechStartedEvent` 打开用户轮次、并对正在生成的回复触发 barge-in（`src/agentscope/agent/_realtime/_agent.py:638-640`）；`SpeechEndedEvent` 关闭用户轮次，并在调用方掌控端点检测（`vad is not None`）时把轮次提交给模型（`_agent.py:642-648,516-521`）。所以「谁来定轮次」是一个 vad 期/构造期选择，但 agent 永远收口到同一对方法——`_start_user_turn` / `_end_user_turn`——它们为用户侧发出 `ReplyStartEvent` / `ReplyEndEvent`（`_agent.py:717-744`）。

## Vendor Adapters in v2.0.8

v2.0.8 **只发布 DashScope 一家适配器**，且有两种口味：

| Class | File | `supports_text_input` | `truncation` |
| :--- | :--- | :--- | :--- |
| `DashScopeRealtimeModel` | `src/agentscope/realtime/_dashscope/_model.py:24` | `False`（`:52`） | `NONE`（`:51`） |
| `DashScopeAudioRealtimeModel` | `src/agentscope/realtime/_dashscope/_audio_model.py:15` | `True`（`:42`） | `NONE`（继承） |

二者是 `src/agentscope/realtime/__init__.py` 里仅有的导出项（`DashScopeRealtimeModel`、`DashScopeAudioRealtimeModel`）。`_dashscope/_model.py` 这套走的是 **OpenAI 形状但更窄** 的 Qwen-Omni 协议，连 `wss://dashscope.aliyuncs.com/api-ws/v1/realtime`（`_model.py:21`）：没有 `conversation.item.truncate` 帧、没有文本轮次、connect 时也无法前置历史（`_model.py:24-31`）。它的 `truncate()` 是刻意的 no-op（`_model.py:193-199`）。

> [!WARNING]
> 主干 `AgentScope.md` 的 Version Delta（"Smaller Deltas" 一节）写到 **Realtime 厂商扩到四家：Gemini / OpenAI / xAI + WebRTC transport**，那是 **v2.0.10** 的扩展。本分册锚定 v2.0.8，源码里 **不存在** Gemini / OpenAI / xAI 适配器，也 **不存在** WebRTC transport——v2.0.8 的 transport 层只有本地声卡一种（见下节）。不要把这些 v2.0.10 内容收进分册。

## Transport Layer

transport 是 agent 与「音频从哪来、到哪去」之间的边界（`src/agentscope/realtime/_transport/_base.py:48-56`）；它归创建者所有、不归 agent 所有，`reply_stream` 只是借用（`_base.py:48-56`，`_agent.py:339-355`）。

v2.0.8 只有一个具体 transport：`LocalAudioTransport`（`src/agentscope/realtime/_transport/_local.py:15`），基于 `sounddevice`（PortAudio）。它的契约来自抽象基类 `TransportBase`：

- `incoming()` 流出上游的 `AudioFrame | ControlFrame`（`_base.py:81-85`）——音频加三种控制帧 `TEXT` / `USER_CONFIRM` / `INTERRUPT`（`_base.py:19-35`）；
- `send_audio(pcm, item_id)` 把助手音频入队，按 `item_id` 归属播放位置（`_base.py:87-97`）；
- `clear_audio()` 淡出并上报被截断的位置；`playout()` 不上报截断地读出当前位置（`_base.py:99-117`）。

v2.0.8 **没有 `WebSocketTransport`、也没有 `WebRTC` transport 类**——`_transport/` 目录里只有 `_base.py` 与 `_local.py`。（`src/agentscope/realtime/_dashscope/_model.py:93` 处的 `websockets` 导入是 **模型适配器自己的网络客户端**，用来连 DashScope 会话，属于 model 侧而非 transport 侧；它不是 RealtimeAgent 意义上的 transport。）换言之 v2.0.8 里浏览器连接尚不能作为一种 transport 存在，agent 只能坐在本地麦克风/扬声器前面。

## TruncationSupport Enum

`TruncationSupport`（`src/agentscope/realtime/_base.py:21`）是一个在 v2.0.8 就已存在的 `StrEnum`，正好三个成员，用来在协议层吸收厂商能力差异：

- `NONE = "none"`——无法校正（也是 `RealtimeModelBase` 上的默认值，`_base.py:53`）；
- `SERVER = "server"`——provider 自己校正，`truncate` 是 no-op；
- `EXPLICIT = "explicit"`——provider 接受显式 truncate 帧。

v2.0.8 里只有 `NONE` 分支被已发布的适配器走到：两个 DashScope 类都设 `truncation = TruncationSupport.NONE`，于是它们的 `truncate()` 什么都不做（`_dashscope/_model.py:51,193-199`）。barge-in 仍会改写 **本地** 上下文（`_truncate_reply`，`_agent.py:588-610`），但 **服务端** 上下文保持未校正——这正是现有笔记说的「厂商不支持截断时，服务端上下文里用户听到了什么永远是不准的」。`SERVER` / `EXPLICIT` 两个分支作为代码必须分支的抽象存在，等其它厂商落地（v2.0.10+）后才被走到。

## Boundary with Core Agent

`RealtimeAgent` 不继承 `Agent`，但它由 **与核心 `Agent` 完全相同的原语** 构建起来，这才是真正的交互边界：

- **共享事件词汇**。`reply_stream()` 吐出的正是普通 `Agent.reply_stream()` 会吐的同一批 `AgentEvent`：`ReplyStartEvent` / `ReplyEndEvent`、`TextBlock*Event`、`DataBlock*Event`、`ToolCall*Event`、`ToolResult*Event`、`ModelCall*Event`、`RequireUserConfirmEvent`、`UserInterruptEvent`、`UserConfirmResultEvent`（`src/agentscope/agent/_realtime/_agent.py:23-44`）。下游渲染器（TUI / Web UI）对实时事件与聊天事件一视同仁。
- **共享消息模型**。它从 `agentscope.message` 导入 `Msg` / `UserMsg` / `TextBlock` / `ToolCallBlock` / `ToolResultBlock` / `Usage`，从 `agentscope.state` 导入 `AgentState`（`_agent.py:45-55`），所以实时会话的 `state.context` 就是聊天 `Agent` 持有的同一份 `Msg` 列表。
- **共享权限与工具**。工具执行复用 `PermissionEngine` / `PermissionBehavior` 与 `Toolkit` / `ToolChunk` / `ToolResponse`（`_agent.py:54-56`）；ASK 确认仍用 `asyncio.wait_for(future, timeout=300)`（`_agent.py:1087`），与聊天路径一致。

**实时音频如何变成 Msg content block**（下行链路）：`AudioDeltaEvent` → `_emit_audio()` 发出 `DataBlockStartEvent` / `DataBlockDeltaEvent`，承载 base64 PCM、`media_type="audio/pcm;rate=<hz>"`，并增长助手 `Msg` 的 content（`src/agentscope/agent/_realtime/_agent.py:921-940`）；`TranscriptDeltaEvent` → `_emit_text()` 追加进**单个**不断增长的 `TextBlock` 而非每帧一个块（`_agent.py:887-919`）；用户落定的语音 `InputTranscriptionEvent` → `_on_transcription()` 往 `state.context` 追加一条 `UserMsg`（`_agent.py:746-776`）。这些事件经 `_emit()` 入 `asyncio.Queue`（`_agent.py:192,942-944`），再由 `reply_stream` 与上行任务一起泵出（`_agent.py:379-403`）。

> [!NOTE]
> 现有「A Minimal Voice Session」脚注称 `RealtimeAgent` / `LocalAudioTransport` 是「下划线私有路径」——这在 v2.0.8 **不准确**。`agent/__init__.py:6,11` 已公开导出 `agentscope.agent.RealtimeAgent`，`realtime/__init__.py` 也已导出 `agentscope.realtime.LocalAudioTransport`；`agent/_realtime/_agent.py` 与 `realtime/_transport/_local.py` 只是它们所在的内部模块文件名。正式导入名分别是 `from agentscope.agent import RealtimeAgent` 与 `from agentscope.realtime import LocalAudioTransport`。

## Links

- [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)
- [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md)

## References

- `src/agentscope/agent/_realtime/_agent.py`
- `src/agentscope/agent/_realtime/_aggregator.py`
- `src/agentscope/realtime/_base.py`
- `src/agentscope/realtime/_transport/_base.py` / `_local.py`
- `src/agentscope/realtime/_vad.py` / `_events.py` / `_playout.py`
- `src/agentscope/realtime/_dashscope/_model.py` / `_audio_model.py`
