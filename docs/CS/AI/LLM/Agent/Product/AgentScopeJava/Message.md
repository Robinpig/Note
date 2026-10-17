# Message

## Introduction

AgentScope Java 的输出模型是**消息（Msg）+ 事件（AgentEvent）双视图**：`call` 消费全部事件后还你一条完整 `Msg`，`streamEvents` 把执行过程逐事件交给你。本分册记录这两套类型的完整事实，以及与 harness 远程线格式、Service 持久事件、公共 SSE 的边界。

本分册所有类名、字段名、枚举值均核对自本地 `v2.0.4` 源码树（`agentscope-core/src/main/java/io/agentscope/core/event/`、`.../message/`、`agentscope-harness/.../subagent/protocol/`、`agentscope-service/`），与官方文档冲突处以源码为准。

## Two Event Generations

v2 里同时存在两套事件体系，**必须分清**：

| | v1 遗留 | v2 现行 |
| :--- | :--- | :--- |
| 类型 | `io.agentscope.core.agent.Event`（**类**，非接口） | `io.agentscope.core.event.AgentEvent`（**抽象类**） |
| 状态 | `@Deprecated(since = "2.0.0")`，全仓无任何类继承它 | 现行 |
| 类型鉴别 | `EventType` 枚举 6 值（`REASONING` / `TOOL_RESULT` / `HINT` / `AGENT_RESULT` / `SUMMARY` / `ALL`） | `AgentEventType` 枚举（31 值，一一对应 31 个事件子类） |
| 配套 | `EventSource` 是 **final class 不是枚举**（`agentKey/agentId/agentName/sessionId/parentSessionId/taskId/depth/path`） | `source` 字段直接挂在事件上（`/` 分隔路径，如 `main/researcher`） |
| 入口 | `stream(...)` 返回 `Flux<Event>` | `streamEvents(...)` 返回 `Flux<AgentEvent>` |

`AgentEvent` 基类只提供 `id` / `createdAt` / `source` / `metadata` 四样（`event/AgentEvent.java:98-103`），外加三个 metadata 键常量：`METADATA_TASK_ID = "taskId"`（`:80`）、`METADATA_PARENT_SESSION_ID = "parentSessionId"`（`:87`）、`METADATA_GENERATE_REASON = "generate_reason"`（`:96`）。

> 源码内部有一处过期注释：`Event.java:53` 的 javadoc 写「28 typed events」，而实际枚举值/子类是 **31 个**。以 `AgentEventType.java` 与 `@JsonSubTypes` 列表为准。

## Event Catalog

`event/` 包下共 **31 个具体事件类**（`@JsonSubTypes` 注册表在 `AgentEvent.java:36-72`），按功能分七组：

| 分组 | 事件类 |
| :--- | :--- |
| 生命周期 | `AgentStartEvent`、`AgentEndEvent`、`AgentResultEvent`、`ModelCallStartEvent`、`ModelCallEndEvent`、`ExceedMaxItersEvent` |
| 文本块 | `TextBlockStartEvent`、`TextBlockDeltaEvent`、`TextBlockEndEvent` |
| 思考块 | `ThinkingBlockStartEvent`、`ThinkingBlockDeltaEvent`、`ThinkingBlockEndEvent` |
| 工具调用 | `ToolCallStartEvent`、`ToolCallDeltaEvent`、`ToolCallEndEvent` |
| 工具结果 | `ToolResultStartEvent`、`ToolResultTextDeltaEvent`、`ToolResultDataDeltaEvent`、`ToolResultEndEvent` |
| 数据块 | `DataBlockStartEvent`、`DataBlockDeltaEvent`、`DataBlockEndEvent` |
| 中断与确认 | `RequestStopEvent`、`RequireUserConfirmEvent`、`RequireExternalExecutionEvent`、`UserConfirmResultEvent`、`ExternalExecutionResultEvent`、`AllToolsDeniedEvent` |
| 其他 | `HintBlockEvent`、`SubagentExposedEvent`、`CustomEvent` |

## Start-Delta-End Triples

块类型靠「起-增-终」三事件表达，但**不是所有块都是三件套**：

| 内容类型 | Start | Delta | End | 形态 |
| :--- | :--- | :--- | :--- | :--- |
| 文本 | `TextBlockStartEvent` | `TextBlockDeltaEvent` | `TextBlockEndEvent` | 三件套 |
| 思考 | `ThinkingBlockStartEvent` | `ThinkingBlockDeltaEvent` | `ThinkingBlockEndEvent` | 三件套 |
| 工具调用 | `ToolCallStartEvent` | `ToolCallDeltaEvent` | `ToolCallEndEvent` | 三件套 |
| 工具结果 | `ToolResultStartEvent` | `ToolResultTextDeltaEvent` + `ToolResultDataDeltaEvent` | `ToolResultEndEvent` | **四件套（两个 delta 变体）** |
| 数据块 | `DataBlockStartEvent` | `DataBlockDeltaEvent` | `DataBlockEndEvent` | 三件套 |
| 提示 | — | — | — | **单事件** `HintBlockEvent`，不流式 |

两个容易踩的细节：

1. **增量字段统一叫 `delta`**（`String`），唯一例外是 `ToolResultDataDeltaEvent` 用 **`data`**（`ContentBlock`）。源码里**不存在** `textDelta` / `argumentsDelta` 这类名字——`ToolCallDeltaEvent` 语义上是参数增量，字段名仍叫 `delta`（`ToolCallDeltaEvent.java:26-29`）。
2. **`HintBlockEvent` 明确不流式**（`HintBlockEvent.java:21-27` javadoc）：「Unlike text/thinking blocks, hint blocks are not streamed — the full content is available at creation time」，团队消息、后台工具结果、用户中断都走它。

## ID Contract

五个 ID **全不在 `AgentEvent` 基类上**，而是各子类自己持有：

| ID | 定义位置 | 作用 |
| :--- | :--- | :--- |
| `replyId` | 各子类私有字段（约 20 处），基类没有 | 一次「回复/turn」的关联键，同一 reply 内所有事件共享 |
| `blockId` | `TextBlock*` / `ThinkingBlock*` / `DataBlock*` / `HintBlockEvent` | reply 内定位一个内容块的生命周期 |
| `toolCallId` | `ToolCall*` / `ToolResult*` | 把工具调用与其结果配对 |
| `sessionId` | 仅 `AgentStartEvent:26` 与 `SubagentExposedEvent:30` | **不是**通用事件字段 |
| `runId` | **不在事件包**，在 `agent/AgentRun.java:54` | 单次执行的稳定 ID，不属事件体系 |

**从事件流拿完整 `Msg` 的正规入口是 `AgentResultEvent`**（`event/AgentResultEvent.java:35-41`，直接携带整个 `Msg`，`call()` 与 `streamEvents()` 两条路径都发它，位于 `AgentEndEvent` 之前）——不需要自己回放 delta 拼消息。

`agent/accumulator/` 包**不是** Msg 重建器：`ContentAccumulator` / `TextAccumulator` / `ThinkingAccumulator` / `ToolCallsAccumulator` 的粒度是 **ContentBlock**（把模型流式 chunk 聚合成单个块），服务的是 v1 `stream()` 路径。全仓 grep `MsgAccumulator` **零命中**——这个名字不存在。

## Msg And ContentBlock

`Msg` 用 builder 构造，**没有** `Msg.user(...)` 这类静态工厂：`Msg.builder()` 返回基础 builder，`Msg.builderForRole(MsgRole)` 按角色分派到 `UserMessage` / `AssistantMessage` / `SystemMessage` / `ToolResultMessage` 的 builder（`Msg.java:240-250`）。`MsgRole` 四值：`USER` / `ASSISTANT` / `SYSTEM` / `TOOL`。`getStructuredData(Class)` / `getStructuredData(boolean)` / `hasStructuredData()` 都在 `Msg.java:401-506`。

`ContentBlock` 是 **sealed 抽象类**（`ContentBlock.java:58-67`，`implements State`），`permits` 恰好 9 个 final 子类，JSON 判别器 `"type"` 映射 `text` / `thinking` / `image` / `audio` / `video` / `tool_use` / `tool_result` / `hint` / `data`：

```java
public sealed class ContentBlock implements State
        permits TextBlock, ImageBlock, AudioBlock, VideoBlock,
                 ThinkingBlock, ToolUseBlock, ToolResultBlock,
                 HintBlock, DataBlock {}
```

两个状态枚举都是 5 值（默认值在 builder 里兜底）：

| 枚举 | 值 |
| :--- | :--- |
| `ToolCallState`（`ToolCallState.java:20-29`） | `PENDING`（默认）/ `ASKING` / `ALLOWED` / `SUBMITTED` / `FINISHED` |
| `ToolResultState`（`ToolResultState.java:20-29`） | `SUCCESS` / `ERROR` / `INTERRUPTED` / `DENIED` / `RUNNING`（默认） |

`GenerateReason` 共 **11 值**（`GenerateReason.java:36-89`）：`MODEL_STOP`、`TOOL_CALLS`、`STRUCTURED_OUTPUT`、`TOOL_SUSPENDED`、`REASONING_STOP_REQUESTED`、`ACTING_STOP_REQUESTED`、`PERMISSION_ASKING`、`MIDDLEWARE_STOP_REQUESTED`、`ALL_TOOLS_DENIED`、`INTERRUPTED`、`MAX_ITERATIONS`、`TOOL_RETURN_DIRECT`（后两者对应 `ExceedMaxItersEvent` 与 `@Tool(returnDirect=true)`）。

metadata 常量分两处，别找错地方：

- `MessageMetadataKeys.java` 8 个：`BYPASS_MULTIAGENT_HISTORY_MERGE`、`STRUCTURED_OUTPUT_REMINDER`、`STRUCTURED_OUTPUT_REMINDER_TYPE`、`SUMMARY_FAILED`、`CHAT_USAGE`、`STRUCTURED_OUTPUT`（`"_structured_output"`，`:120`）、`CACHE_CONTROL`、`TOOL_RETURN_DIRECT`。
- `Msg.java` 6 个：`METADATA_GENERATE_REASON`、`METADATA_CONFIRM_RESULTS`、`METADATA_CONFIRM_REQUEST_REPLY_ID`、`METADATA_EXTERNAL_EXECUTION_REQUEST_REPLY_ID`、`METADATA_SYNTHETIC`、`METADATA_REMINDER_KIND`。

## Three Event Views

同一份执行事实在三层有三种表示，互不等价：

**① Agent 层 `AgentEvent`**（agentscope-core）——`streamEvents()` 的实时通知，适合展示当前请求。实时到达**不代表**对应日志已提交。

**② Harness 层远程线格式**（`agentscope-harness/.../subagent/protocol/`）——远程子 Agent 过网用：

- `RemoteAgentEvent` 是扁平 DTO（`seq/type/taskId/agentId/text/toolCallId/toolName/toolInput/pendingConfirms/status/error/eventType/payload`），其中 `payload` 承载**完整序列化的 `AgentEvent`**。
- `RemoteEventType` 11 值：`RUN_STARTED`、`RUN_FINISHED`、`RUN_ERROR`、`TEXT_DELTA`、`THINKING_DELTA`、`TOOL_CALL_START`、`TOOL_CALL_END`、`TOOL_RESULT`、`REQUIRE_CONFIRM`、`STATUS`、`AGENT_EVENT`。没有专属 wire 类型的事件走 `AGENT_EVENT`，原事件完整序列化在 `payload` 里——不認識该字段的旧客户端仍读扁平字段。

**③ Service 层持久事件**（agentscope-service，跨两个子模块）：

- `service-common`：`SessionEventDto`（record，`id/sessionId/seq/type/payload/processedAt/createdAt`）、`SessionEventTypes`（约 30 个事件名常量，含 `event_start` / `event_delta` 这类**只流式不落库**的）、`SessionEventEntity`（JPA）、`SessionEventLog`（append-only，seq 冲突重试）。
- `service-dataplane`：`SessionEventMapper` 把 harness 的 `AgentEvent` 映射成持久事件类型 + payload；`SessionEventPreviewBus` 是进程内 `event_start`/`event_delta` 预览总线，**从不落库**。
- **SSE 出口**在 `DataSessionApiController.java:199-201`：`GET /{id}/events/stream`，帧构造在 `:379-386`（`.id(seq)` / `.event(dto.type())` / `.data(json)`）。

另有两个旁支：AG-UI 协议适配器在 `io.agentscope.core.agui.adapter.strategy`（11 个 `*EventConverter` + `AguiEventEncoder`）；aistio 子模块有 Level-2 的 `io.agentscope.extensions.aistio.model.SessionEvent`（镜像 ASDP protobuf）。

**没有名为 `ServiceEvent` 的类**（全仓零命中）——service 层的对应物就是上面这套 `SessionEventDto` / `SessionEventTypes` / `SessionEventEntity` / `SessionEventLog`。

## Links

- [主笔记](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/AgentScopeJava.md)
- [智能体分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Agent.md)
- [工具分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Tool.md)
- [会话分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Session.md)
- [AgentScope（Python 版）](/docs/CS/AI/LLM/Agent/Product/AgentScope/AgentScope.md)

## References

- [AgentScope Java 消息与事件](https://java.agentscope.io/v2/zh/docs/building-blocks/message-and-event)
- [AgentScope Java 子 Agent（流式转发与 source 标记）](https://java.agentscope.io/v2/zh/docs/harness/subagent)
