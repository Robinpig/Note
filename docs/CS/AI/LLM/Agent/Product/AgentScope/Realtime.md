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



## Links

- [AgentScope](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)

## References

- `src/agentscope/agent/_realtime/_agent.py`
- `src/agentscope/realtime/_transport/_local.py` / `_vad.py`
- `src/agentscope/realtime/_dashscope/_model.py`
