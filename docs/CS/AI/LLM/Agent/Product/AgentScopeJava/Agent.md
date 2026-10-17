# Agent

## Introduction

本分册覆盖 AgentScope Java 的**智能体接口与调用方式**：`Agent` 接口的三段式组合、`ReActAgent.Builder` 的完整参数、实例生命周期模型、结构化输出、单次执行控制句柄（`AgentRun`）、中断、人机交互（HITL）与模型容错。消息与事件体系的完整事实在 [消息分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Message.md)，Harness 装配层的能力矩阵在 [主笔记](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/AgentScopeJava.md)。

本分册所有类名、方法签名与默认值均核对自本地 `v2.0.4` 源码树（`agentscope-core/src/main/java/io/agentscope/core/agent/` 与 `io/agentscope/core/ReActAgent.java`），与官方文档冲突处以源码为准。

## Agent Interface

`Agent` 不是一个大接口，而是三个能力接口的组合（`agent/Agent.java:47`）：

```java
public interface Agent extends CallableAgent, StreamableAgent, ObservableAgent {
    String getAgentId();
    String getName();
    default String getDescription() { return "Agent(" + getAgentId() + ") " + getName(); }
    void interrupt();
    void interrupt(Msg msg);
    default AgentState getAgentState() { return null; }
    default Toolkit getToolkit() { return null; }
}
```

| 子接口 | 方法 | 返回 | 语义 |
| :--- | :--- | :--- | :--- |
| `CallableAgent` | `call(List<Msg>)` 及 10 个重载 | `Mono<Msg>` | 运行推理-行动循环，内部消费全部事件，完成或暂停时返回**恰好一条**终态 `Msg` |
| `StreamableAgent` | `stream(List<Msg>, StreamOptions)` 及重载 | `Flux<Event>` | 同一循环逐事件流式产出，可发多个事件但收敛到单条终态 `Msg` |
| `ObservableAgent` | `observe(Msg)` / `observe(List<Msg>)` | `Mono<Void>` | 只把消息加进上下文，不触发推理——多 Agent 场景观察同伴输出用 |

两个必须记住的接口级事实：

1. **`Mono<Msg>` 的「单终态」是契约**：`Agent.java:42-45` 的 javadoc 明确「一次 `call(...)` 调用产生恰好一条终态 `Msg`，流式变体可以发很多事件但收敛到单条终态 `Msg`，这是由 `call` 方法的 `Mono<Msg>` 返回类型强制的」。
2. **接口级的 `stream(...)` 已废弃**。它返回的 `Flux<Event>` 里的 `Event` 是 `agent/Event.java:57` 的类，自 2.0.0 起 `@Deprecated`；`EventType`（6 值：`REASONING` / `TOOL_RESULT` / `HINT` / `AGENT_RESULT` / `SUMMARY` / `ALL`）与 `EventSource`（final class，非枚举）同属 v1 遗留体系。**新代码一律用 `ReActAgent.streamEvents(...)` 返回 `Flux<AgentEvent>`**，见 [消息分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Message.md)。`AgentEvent` 与 `Event` 两套体系**没有任何继承关系**（`event/AgentEvent.java:73` 是独立的抽象类，类型鉴别器是 `AgentEventType`）。

`ReActAgent`（`extends AgentBase implements AutoCloseable`）在接口之外补上的公开方法：

```java
public Flux<AgentEvent> streamEvents(List<Msg> msgs);                    // 及 Msg / String / + RuntimeContext 重载
public AgentRun<AgentEvent> prepareRun(List<Msg> msgs, RuntimeContext ctx);
public AgentRun<Msg>        prepareCall(List<Msg> msgs, RuntimeContext ctx);
public void interrupt();                       // 无参
public void interrupt(Msg msg);
public void interrupt(InterruptSource source);
public void interrupt(RuntimeContext ctx);
public void interrupt(RuntimeContext ctx, Msg msg);
public void interrupt(String userId, String sessionId);
public void interrupt(String userId, String sessionId, Msg msg);
public void clearStateCache(...);              // 三个重载
public void clearContext(...);                 // 两个重载
public void setPermissionMode(...);            // 两个重载
public void replacePermissionContext(...);
public void saveAgentState(...);               // 两个重载
public String getDefaultSessionId();
public boolean isPendingToolRecoveryEnabled();
```

## Builder Parameters

`ReActAgent.builder()` 定义共享配置，`build()` 产出实例。核心参数（`ReActAgent.Builder`，默认值取自源码）：

| 参数 | 类型 | 默认值 | 说明 |
| :--- | :--- | :--- | :--- |
| `name` | String | 必填 | 智能体标识符，用于消息和日志 |
| `sysPrompt` | String | 必填 | 基础系统提示词 |
| `model` | Model | 必填 | `ChatModelBase` 实例，或 `"provider:model"` 字符串 id 由 `ModelRegistry` 解析 |
| `toolkit` | Toolkit | `new Toolkit()` | 管理工具、MCP 客户端、技能和工具组 |
| `middlewares` | `List<MiddlewareBase>` | 空 | 5 个 hook 的拦截链，见 [工具分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Tool.md) |
| `stateStore` | AgentStateStore | null（不持久化） | 配置后每次 call 自动加载 / 保存 `AgentState` |
| `defaultSessionId` | String | agent name | 调用未带 sessionId 时的兜底 |
| `permissionContext` | PermissionContextState | 默认 DEFAULT 模式 | 工具执行细粒度规则 |
| `maxIters` | int | **10**（`ReActAgent.java:4806`） | ReAct 主循环最大迭代次数，必须为正 |
| `enableMetaTool` | boolean | **false** | 注册 `reset_equipped_tools` 元工具 |
| `taskListEnabled` | boolean | **false** | `enableTaskList()` 注册 `todo_write` |
| `enablePendingToolRecovery` | boolean | false | 悬空工具调用补错误结果 |

⚠️ **一批 Builder 字段是 1.x 兼容残留**：`longTermMemory`、`longTermMemoryMode`（默认 `BOTH`）、`longTermMemoryAsyncRecord`、`knowledgeBases`、`ragMode`、`retrieveConfig`、`skillBox` 全部标注 `@Deprecated(forRemoval = true, since = "2.0.0")`（`ReActAgent.java:4829-4855`），仅供 legacy 代码产生等价运行时行为，**新代码不要用**——v2 的对应能力在 harness 层，见 [上下文分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Context.md)。

`.model(...)` 两种写法：字符串 id（最常用，自动读环境变量，如 `DASHSCOPE_API_KEY`）与显式 builder（精细控制超时、端点、formatter 时用）。字符串形式要求对应模型扩展模块在 classpath，支持 dashscope / openai / openai-official / deepseek / anthropic / gemini / ollama。HarnessAgent 的 builder 接口与之一大体一致，额外多出工作区、记忆、压缩、沙箱等装配方法。

## Instance Lifecycle

推荐模式：**共享 Builder，每请求 `build()` 新实例，执行完关闭**。Builder 保存通用配置；用户、会话、请求参数通过新建的 `RuntimeContext` 传入，**不改共享 Builder**。

- 同步调用用 try-with-resources 包住执行和等待；响应式调用用 `Mono.using` / `Flux.using`，让实例在订阅结束、报错或取消时释放。不要在 try 块里返回尚未订阅的 `Mono`——Agent 会提前关闭。
- 模型客户端、连接池、存储、技能仓库等应用级依赖由应用统一管理，退出时再关；共享工具与中间件必须线程安全，**不能把当前用户或上下文存进成员字段**。
- **新实例与新会话是两个概念**：Harness 用稳定的 `agentId` + `userId` + `sessionId` + 同一日志后端恢复已提交状态；未配置日志或 stateStore 的普通 ReActAgent，旧实例内存里的上下文不会带到新实例。
- 也可以共享同一个 Agent 实例（无状态执行引擎设计，实例内相同 `(userId, sessionId)` 的直接调用由执行门串行化，不同会话可并行），但实例仍有缓存、执行门和后台资源，退出时要关。
- 后台 `AgentSession`、Channel 或托管运行时的生命周期由其管理器持有，**不能套用「提交请求返回就关闭」**；中断一次直接调用也必须定位到正在执行的实例，临时构建另一个实例中断不了旧实例里的请求。

## Structured Output

传一个 Java 类或 `JsonNode` schema 给 `call`，智能体按 schema 返回结构化结果而不是自由文本。常量 `ReActAgent.STRUCTURED_OUTPUT_TOOL_NAME = "generate_response"` 就是降级路径用的合成工具名：

```java
public record WeatherResponse(String location, String temperature, String condition) {}

Msg result = agent.call(List.of(new UserMessage("旧金山天气如何？")), WeatherResponse.class).block();
WeatherResponse weather = result.getStructuredData(WeatherResponse.class);
```

实现路径由框架按模型能力自动选择，**对调用方透明**——判据是 `Model.supportsNativeStructuredOutput()`：

| 路径 | 条件 | 行为 |
| :--- | :--- | :--- |
| 原生 | 模型支持 `response_format` + tools 并行（OpenAI、DashScope 等） | JSON Schema 经 `response_format` 直传，模型保证输出合法 JSON，循环自然结束 |
| 降级 | 模型不支持（Anthropic、Ollama 等） | 注入 `generate_response` 合成工具 + 指令提示，模型以 tool call 方式输出结构化结果 |

结构化输出与工具可同时使用——先调工具完成任务，最后以指定 schema 输出。也可从 `result.getMetadata().get("_structured_output")` 以 `Map` 形式读取（`MessageMetadataKeys.STRUCTURED_OUTPUT = "_structured_output"`，`MessageMetadataKeys.java:120`）。

## Execution Control: AgentRun

高级用法：自行管理单次执行。`prepareRun(messages, context)`（事件流，返回 `AgentRun<AgentEvent>`）与 `prepareCall(messages, context)`（最终回复，返回 `AgentRun<Msg>`）产出带唯一 `runId()` 的 `AgentRun<T>`。**创建句柄不执行 Agent，订阅一次 `stream()` 才开始**（`AgentRun.java:107-110`，`runId` 是 `UUID.randomUUID().toString()`）：

```java
AgentRun<AgentEvent> run = agent.prepareRun(List.of(new UserMessage("你好")), context);
String runId = run.runId();          // 先在应用的运行管理器里登记句柄
run.stream().subscribe(this::onEvent, this::onError);
// 另一条请求链路可按 runId 找到这个句柄
run.cancel();
```

句柄语义（`AgentRun.java` / `RunControl.java`）：

- `cancel()` 立即取消响应式执行，订阅前和排队期间也可取消；取消排队中的 B 不会中断正在执行的 A，也不会让 C 越过 A 提前执行。
- `interrupt()` / `interrupt(message)` 请求已获得执行位置的调用在**协作检查点**中断；尚未获得执行位置时只取消这次排队调用。
- `status()` 返回 `CREATED` / `QUEUED` / `RUNNING` / `COMPLETED` / `FAILED` / `CANCELLED`（`AgentRun.Status` 六值，`isTerminal()` 判定后三者）；`termination()` 可观察终态而不启动执行。
- **一个句柄只允许一次订阅**，重复订阅被拒绝；已结束的句柄不能中断后续调用。

`runId` 与 `RuntimeContext.getRunId()` 同源（显式传入或 build 时生成），`AgentRunRegistry` 注册键、SSE 的 `SESSION_RUN_STARTED`、前端取消运行用的 id 天然一致。取消不回滚外部副作用，也不能强行终止不响应取消的阻塞工具。

## Interrupt

针对通过 `call` / `streamEvents` 启动的执行，跨请求中断要保存并找到目标实例。`ReActAgent` 提供 7 个 `interrupt` 重载，最细粒度到 `(userId, sessionId)`：

```java
RuntimeContext target = RuntimeContext.builder()
        .userId("alice").sessionId("session-001").build();
agent.interrupt(target);                                    // 中断该 session 正在进行的 call
agent.interrupt(target, new UserMessage("用户已取消操作"));   // 附中断消息
```

便捷 API 选择指定 `(userId, sessionId)` 中**当前正在执行**的调用，不能选排队中的某次；精确操作用该次执行的句柄。中断空闲 session 无效果；中断信号属于执行，不保存在 `AgentState`。中断后行为：当前推理 / 工具执行在下一个检查点（reasoning 开始、acting 开始、streaming 每个 chunk）被拦截；agent 返回带 `GenerateReason.INTERRUPTED` 标记的 `Msg`（`GenerateReason` 共 11 个值，`INTERRUPTED` 在 `GenerateReason.java:82`）；按已配置后端保存状态。挂起的工具请求仍需提供答案，不会恢复工具内部执行进度。

## Human-in-the-loop

两种暂停：权限系统返回 ASK 的工具调用（`RequireUserConfirmEvent`），与标记为外部执行的工具（`RequireExternalExecutionEvent`）。两种都用「把结果事件再次喂给下一次 call」恢复，且**沿用同一个 `ctx`**。

用户确认的三步（streamEvents 里监听 `RequireUserConfirmEvent`，其 `getToolCalls()` 给出待确认的 `ToolUseBlock`）：

```java
// 1. 构造确认结果（可在传回前修改工具输入；rules 可带建议规则）
List<ConfirmResult> confirmResults = new ArrayList<>();
for (var tc : confirmEvent.getToolCalls()) {
    confirmResults.add(new ConfirmResult(true, tc));
}

// 2. 通过 metadata 传给下一次 call 恢复
UserMessage resumeMsg = UserMessage.builder()
        .metadata(Map.of(Msg.METADATA_CONFIRM_RESULTS, confirmResults))
        .build();
Msg result = agent.call(List.of(resumeMsg), ctx).block();
```

metadata 常量定义在 `Msg.java` 而**不是** `MessageMetadataKeys.java`：`METADATA_CONFIRM_RESULTS = "agentscope_confirm_results"`（`Msg.java:77`）、`METADATA_CONFIRM_REQUEST_REPLY_ID = "agentscope_confirm_request_reply_id"`（`:83`）、`METADATA_EXTERNAL_EXECUTION_REQUEST_REPLY_ID = "agentscope_external_execution_request_reply_id"`（`:91`）。

已确认的立即执行并继续推理；已拒绝的产生 LLM 可见的错误结果，模型可能换方式重试；已接受的规则持久化进权限引擎，未来匹配的调用自动放行。外部执行则把每个结果封装为 `ToolResultBlock`（`state` 设 `SUCCESS`）回传，agent 先发 `ExternalExecutionResultEvent`（`replyId` 与原暂停事件相同）再从中断处继续。完整可运行示例见 `agentscope-examples/documentation/.../hitl/PermissionHITLExample.java`。

## Model Failover

```java
ReActAgent.builder()
        .model("dashscope:qwen-plus")
        .maxRetries(3)                        // 模型调用失败自动重试
        .fallbackModel("dashscope:qwen-max")  // 主模型失败时切换备用
        .failoverListener((primary, error) -> // 观察切换：哪个模型失败、因何失败
                metrics.recordFailover(primary.getModelName(), error))
        .build();
```

实现要点（`ReActAgent.modelForCall()`，`:4273-4320`）：

- `maxRetries` 不是自己的重试循环，而是折算进 `GenerateOptions.executionConfig.maxAttempts` 覆盖在用户配置之下（`:4252-4261`）——**显式的 per-call 设置优先级更高**。
- 切换发生在 `Flux.switchOnFirst` 的**第一个错误信号**上（`:4288`），不是「连续失败 N 次后」——主模型流一出错就整体切到 fallback，同步的建连失败也走同一条路径（`:4285-4286` 注释）。
- failover 监听器在切换现场**同步回调**并携带原始错误——这是切换唯一的进程内信号，主模型的错误不会到达事件流或中间件。监听器抛出的异常被就地吞掉只记日志（`notifyFailover`，`:4327-4336`），不影响切换与后续 fallback 调用。
- 包装后的 `Model` 代理把 `getModelName()` / `supportsNativeStructuredOutput()` / `getContextWindowSize()` 全部转发给**当前活跃模型**（`:4305-4318`）——切换后这些能力查询的结果会跟着变。

## Built-in Capabilities

| Builder 方法 | 效果 |
| :--- | :--- |
| `enableMetaTool(true)` | 注册 `reset_equipped_tools` 元工具（默认 false），让 LLM 自己按任务需求切换工具组 |
| `enableTaskList()` | 注册 `todo_write` 任务列表工具，LLM 拆解复杂任务逐步完成；每轮推理前以小提示形式回看当前 todos |
| `skillRepository(...)` | 接技能市场（Git / Nacos / MySQL / classpath），详见 [技能分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Skill.md) |

## Links

- [主笔记](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/AgentScopeJava.md)
- [消息分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Message.md)
- [工具分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Tool.md)
- [会话分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Session.md)
- [Agent Theory](/docs/CS/AI/LLM/Agent/Theory/Agent.md)

## References

- [AgentScope Java 智能体（Agent）](https://java.agentscope.io/v2/zh/docs/building-blocks/agent)
- [AgentScope Java 模型](https://java.agentscope.io/v2/zh/docs/building-blocks/model)
- [AgentScope Java 消息与事件](https://java.agentscope.io/v2/zh/docs/building-blocks/message-and-event)
