## Introduction

AgentScope Java 的输出模型是**消息（Msg）+ 事件（AgentEvent）双视图**：`call` 消费全部事件后还你一条完整 `Msg`，`streamEvents` 把执行过程逐事件交给你。两者是同一数据的两种形态——事件流可以按 `replyId` / `blockId` / `toolCallId` 聚合还原成完整消息。本分册记录这两套类型的完整事实，以及与持久层 `SessionEvent`、Service 公共 SSE 的边界。

Python 版用 Pydantic model 表达同一思想（`Msg.content` 是 `list[ContentBlock]`），Java 版换成不可变 `List<ContentBlock>` + builder；角色约束在两版都构造时强制，但 Java 版的块类型更细（`DataBlock` 统一取代旧的 Image / Audio / VideoBlock）。

## Message Model

`Msg`（`io.agentscope.core.message.Msg`）字段：

| 方法 | 类型 | 说明 |
| :--- | :--- | :--- |
| `getId()` | String | 唯一消息标识符 |
| `getName()` | String | 发送方名称（可空） |
| `getRole()` | MsgRole | USER / ASSISTANT / SYSTEM / TOOL |
| `getContent()` | `List<ContentBlock>` | 有序内容块列表（不可变） |
| `getMetadata()` | `Map<String, Object>` | 任意键值元数据 |
| `getTimestamp()` | String | 创建时间（`yyyy-MM-dd HH:mm:ss.SSS`） |
| `getUsage()` | ChatUsage | token 用量（仅 assistant 消息） |
| `getGenerateReason()` | GenerateReason | 退出原因：`MODEL_STOP` / `TOOL_SUSPENDED` / `REASONING_STOP_REQUESTED` / `ACTING_STOP_REQUESTED` / `ALL_TOOLS_DENIED` / `INTERRUPTED` / `MAX_ITERATIONS` |

### Content Blocks

| 块类型 | 说明 | 允许出现在 |
| :--- | :--- | :--- |
| `TextBlock` | 纯文本 | USER、ASSISTANT、SYSTEM |
| `DataBlock` | 二进制数据（图片 / 音频 / 视频），base64 或 URL；统一替代旧的 Image / Audio / VideoBlock | USER、ASSISTANT |
| `ImageBlock` / `AudioBlock` / `VideoBlock` | 旧版具体多媒体块（仍兼容，新代码用 `DataBlock`） | USER |
| `ThinkingBlock` | 模型推理过程（思维链） | ASSISTANT |
| `ToolUseBlock` | 工具调用：id / name / input / state（`ToolCallState`） | ASSISTANT |
| `ToolResultBlock` | 工具执行结果：id / name / output / state（`ToolResultState`） | ASSISTANT |
| `HintBlock` | 以用户上下文形式注入循环的指令 | ASSISTANT |

角色约束在构造时强制执行：USER 只能收 text / data / image / audio / video 块；SYSTEM 只能收 `TextBlock`；ASSISTANT 可含所有类型。

### Construction And Access

按 role 固定的子类提供便捷构造（`UserMessage` / `AssistantMessage` / `SystemMessage` / `ToolResultMessage`），content 传普通字符串会自动包装成 `TextBlock`：

```java
UserMessage userText = new UserMessage("user", "这张图片里有什么？");
UserMessage userMulti = new UserMessage("user",
        TextBlock.builder().text("描述这张图片：").build(),
        DataBlock.builder()
                .source(Base64Source.builder().data("...").mediaType("image/png").build())
                .build());
```

读取辅助方法：`getTextContent()`（所有 TextBlock 按 `\n` 拼接）、`getContentBlocks(Class<T>)`、`getFirstContentBlock(Class<T>)`、`hasContentBlocks(Class<T>)`。

## Event Model

事件是消息的流式对应物，全部继承 `io.agentscope.core.event.AgentEvent`，公共面：`getId()` / `getCreatedAt()`（ISO 8601）/ `getType()`（`AgentEventType`）/ `getSource()` / `getMetadata()`。**`getSource()` 是父子 Agent 的区分键**：顶层 Agent 为 null，子 Agent 事件为斜杠分隔路径（如 `"main/researcher"`）；远程子 Agent 转发时还会写 `metadata.taskId` 与 `metadata.parentSessionId`。

### Lifecycle: start → delta → end

每个事件携带 `getReplyId()` 关联到正在构建的消息；一次回复内部用 `getBlockId()` 关联文本 / 思考 / 数据块事件，用 `getToolCallId()` 关联工具调用与工具结果事件。`blockId` 是 replyId 作用域内的关联键，不要求全局唯一——某类内容块一次回复最多一个生命周期时可用稳定类型标识。这套三级键（reply → block / toolCall → event）就是「从事件流重建消息」的全部机制。

### Event Catalog

| 类别 | 事件 |
| :--- | :--- |
| 生命周期 | `AgentStartEvent`（replyId / sessionId / name / role）、`AgentEndEvent`、`ExceedMaxItersEvent`、`RequestStopEvent`（中间件或工具发起提前停止） |
| 文本流式 | `TextBlockStartEvent` / `TextBlockDeltaEvent`（`getDelta()`）/ `TextBlockEndEvent` |
| 思考流式 | `ThinkingBlockStartEvent` / `ThinkingBlockDeltaEvent` / `ThinkingBlockEndEvent`（结构同文本） |
| 数据流式 | `DataBlockStartEvent`（`getMediaType()`）/ `DataBlockDeltaEvent`（增量 base64）/ `DataBlockEndEvent` |
| 工具调用 | `ToolCallStartEvent`（toolCallId / toolCallName）/ `ToolCallDeltaEvent`（JSON 参数片段）/ `ToolCallEndEvent` |
| 工具结果 | `ToolResultStartEvent`、`ToolProgressEvent`（中间进度，**仅展示，不发给 LLM**）、`ToolResultTextDeltaEvent` / `ToolResultDataDeltaEvent`（LLM 实际收到的结果）、`ToolResultEndEvent`（`getState()`：SUCCESS / ERROR / INTERRUPTED / DENIED / RUNNING / SUSPENDED） |
| 模型调用 | `ModelCallStartEvent`（modelName）/ `ModelCallEndEvent`（inputTokens / outputTokens） |
| 人工介入 | `RequireUserConfirmEvent`（`getToolCalls()`）/ `RequireExternalExecutionEvent` / `UserConfirmResultEvent`（`getConfirmResults()`）/ `ExternalExecutionResultEvent`（`getToolResults()`）/ `AllToolsDeniedEvent`（`getDeniedToolCalls()`） |
| 子 Agent | `SubagentExposedEvent`（subagentId / agentId / sessionId / label） |

两个容易踩的契约细节：

1. **`ToolProgressEvent` 与 `ToolResult*DeltaEvent` 不能混用**。从事件流重建工具结果的客户端必须只累积 `ToolResult*DeltaEvent` 并忽略 `ToolProgressEvent`——混用会让进度文本进入工具消息，下一轮被送回模型，违背 `ToolEmitter` 的契约。
2. **外部执行暂停期间不产出 `ToolResult*` 事件**——工具尚未执行，真实结果由调用方回传后经 `ExternalExecutionResultEvent` 表达。

### Rebuilding Messages From Events

事件与消息是同一数据的两种视图，按 `replyId` / `blockId` / `toolCallId` 聚合即可还原完整 `AssistantMessage`：

```java
StringBuilder accumulated = new StringBuilder();
agent.streamEvents(userMsg)
        .doOnNext(event -> {
            if (event instanceof TextBlockDeltaEvent delta) {
                accumulated.append(delta.getDelta());
            } else if (event instanceof ToolCallStartEvent tc) {
                System.out.println("[tool] " + tc.getToolCallName());
            } else if (event instanceof ToolResultEndEvent end) {
                System.out.println("[tool result state=" + end.getState() + "]");
            }
        })
        .blockLast();
```

标准做法可参考 `agentscope-core` 的 `agent/StreamingHook.java` 与示例 `streaming/AgentEventStreamExample.java`。这个重建能力是 HITL 恢复与断线重连的基础：前端可把被暂停的事件流完整存下，恢复时 replay 拿到同一条 Msg。

## Three Event Views, Do Not Mix

框架里存在三种「事件」，格式与游标各自独立，是最容易混淆的地方：

| 视图 | 类型 | 定位 |
| :--- | :--- | :--- |
| 实时交互 | `AgentEvent`（`streamEvents` 产出） | 展示当前请求；到达不代表已提交 |
| 持久事实 | `SessionEvent`（原生 Session Log） | 不可变执行记录，有持久 `seq`；恢复、导出、诊断以它为准 |
| 公共 SSE | Service 投影事件 | 面向客户端的 turn / item / action 整理，cursor 与 SDK 原生序号不是同一协议 |

`streamEvents()` 本身没有持久游标，**不应用它重新执行请求来补齐断线期间的内容**——补历史用 Session Log 读取 API，见 [会话分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Session.md)。Harness 默认也会保存直接调用的日志。

## Links

- [AgentScope Java 主笔记](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/AgentScopeJava.md)
- [AgentScope Java 智能体分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Agent.md)
- [AgentScope Java 会话分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Session.md)
- [AgentScope Python 版 Pipeline 分册（事件与类型）](/docs/CS/AI/LLM/Agent/Product/AgentScope/Pipeline.md)

## References

- [AgentScope Java 消息与事件](https://java.agentscope.io/v2/zh/docs/building-blocks/message-and-event)
