# Execution

## Introduction

本文是 AgentScopeJava 子树的「源码级实现原理」，逐行核对本地 `v2.0.4` 源码树（`/Users/robin/Projects/agentscope-java`，git tag `v2.0.4`，commit `0b6743b26`）。功能语义、API 与默认值已经在 [智能体分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Agent.md)、[消息分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Message.md)、[工具分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Tool.md)、[上下文分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Context.md) 与 [会话分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Session.md) 落地；本文只讲底层「怎么实现」——状态机、无状态化机制、事件流源头、消息聚合、工具并行保序、权限决策链、中间件组合、结构化输出、模型 SPI、Harness 装配与状态持久化。

凡涉及类名、方法、默认值、枚举值，一律以源码为准，并附 `相对路径:行号`。行号取自 `v2.0.4` 源码；后续版本若重排，请以类名 + 方法名定位。

范围边界：本文不重述分册里的功能表格与 API 示例，只在对应段末尾点出「功能语义见 ×× 分册」。

## ReAct Loop State Machine

`ReActAgent` 是 `AgentBase` 的子类（`agentscope-core/src/main/java/io/agentscope/core/ReActAgent.java:218`），但真正的循环体不在顶层方法里，而在**非静态内部类 `CallExecution`**（`ReActAgent.java:1706`，Javadoc 明写 "hosts the entire ReAct reasoning loop"，`:1699-1704`）。

一轮迭代的阶段顺序（`CallExecution` 内）：

1. **推理** `reasoning(iter, ignoreMaxIters)`：用 `MiddlewareChain.build(... onReasoning ...)` 包住 `reasoningStream`，模型流逐 chunk 累积到 `ReasoningContext`，结束生成 `buildFinalMessage()`（`:2410 / :2456-2472 / :2486-2506 / :2649-2657`）。
2. **推理消息回灌** `state.contextMutable().add(eventMsg)`（`:2549`）。
3. **工具** `acting(iter)`：`MessageUtils.extractPendingToolCalls(...)` 取待执行工具 → `actingStream` → `executeToolCalls` → `dispatchToolCalls` → `activeToolkit.callTools(...)`（`:2858-2860 / :2881-2890 / :3210-3212 / :3562-3577`）。
4. **工具结果回灌** 写成 `ToolResultMsg` 并 `state.contextMutable().add(resultMsg)`（`:3672-3673 / :3706`）。
5. **下一轮** `return executeIteration(iter + 1)`（`:2984`）→ `reasoning(iter+1, false)`（`:2396-2398`）。

**终止条件**（`ReActAgent.java`）：

- 上限检查在 `reasoning` 开头，`iter >= maxIters` → `summarizing()`（`:2410-2414`）。`summarizing()` 为未完成的 pending tool 补 error 结果、发 `ExceedMaxItersEvent("", maxIters, maxIters)`、再单独调一次 summary 模型（`:3862-3892`）。
- 自然终止 `isFinished(Msg)` = 无 tool calls 且存在非空白 `TextBlock`（`:4107-4120`），命中后 `Mono.justOrEmpty(eventMsg)`（`:2572-2574`）。
- 其它提前返回：HITL `isStopRequested()`（`:2553-2560`）、中间件 `RequestStopEvent`（`:2531-2535 / :2904-2918`）、工具挂起 `buildSuspendedMsg`（`:2931 / :2981`）、`returnDirect`（`:2973-2976`）、`PERMISSION_ASKING`（`:2906-2915`）、全部工具被拒 `emitAllToolsDeniedThroughMiddleware`（`:2864-2867`）。
- 空回复不会静默结束：注入 `buildEmptyResponseReminder()` 后回灌再循环（`:2580-2587 / :4131-4143`）。

**迭代上限默认值**——一个易错点：`Builder.maxIters` 默认 **10**（`ReActAgent.java:4806`）；同时存在 `ReactConfig.DEFAULT_MAX_ITERS = 20`（`agent/config/ReactConfig.java:33`），但只被 `ReactConfig.defaults()/fromJson` 使用，`assembleReactConfig` 用的是 `b.maxIters`，`reactConfig` 字段在循环中未被读取（无调用点）。**走 Builder 的默认上限是 10，不是 20**。功能语义见 [智能体分册 Builder 参数](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Agent.md)。

## Stateless Execution Engine

「完全无状态」靠两点：per-call 可变状态放进 `CallExecution` 实例，Reactor Context 只存该实例的引用，不存可变状态本身。

- `CallExecution` 是 per-call 作用域（Javadoc `ReActAgent.java:1699-1704`），非静态内部类，可变字段含 `InterruptControl interruption`、`AgentState state`、`PermissionEngine permissionEngine`、`Msg systemMsg`、`FluxSink<AgentEvent> eventSink`、`RuntimeContext rc`、`ToolRequestConfig toolRequestConfig` 等（`:1710-1791`）。
- Reactor Context 的 key：`AgentBase.CALL_SCOPE_KEY`（`:228`）、`RUNTIME_CONTEXT_KEY`（`:236-237`）、`EVENT_SINK_KEY`。写入 `body.contextWrite(c -> c.put(CALL_SCOPE_KEY, scope))`（`:348-349`）；读取 `Mono.deferContextual(cv -> { CallExecution scope = scopeFrom(cv); ... })`（ReActAgent.java:1205-1208）。
- **并发保证**：`slotKey(userId, sessionId)` 归一化键（`:397-399`）；实例级 `ConcurrentHashMap<String, AgentState> stateCache`、`slotVersions`（`:286-303`）；`AgentBase.serializeOnKey` 让同 slot 的调用 FIFO 串行、异 slot 并发（AgentBase.java:354-397），类注释直给 "Calls sharing a (userId, sessionId) slot are serialized; distinct slots can execute concurrently"（ReActAgent.java:212-215）。`CALL_SCOPE_KEY` 把 per-call scope 挂 Reactor Context，注释明确 "so concurrent calls on one instance never share mutable per-call state"（AgentBase.java:222-227）。`toolkit` 共享且 "never copied and never mutated per call"（ReActAgent.java:1755-1762）。

## call And streamEvents Are One Core

- 共同私有方法 `buildAgentStream(List<Msg>, RuntimeContext, Function<List<Msg>, Mono<Msg>>)`（`ReActAgent.java:1038`，注释 "Single implementation shared by both call() (via callInternal) and streamEvents()"），`streamEvents` 的 Javadoc 也写 "share the same internal buildAgentStream core"（`:1115-1116`）。
- `call()` 收敛成 `Mono<Msg>`：`callInternal` 过滤 `AgentResultEvent` 后 `takeLast(1).next()`（`:1011-1020`）；`streamEvents()` 直接订阅同一 `Flux<AgentEvent>`。
- **`observe()` 不是执行核**：`doObserve` 仅把 msg 追加进 `getAgentState().contextMutable()`（ReActAgent.java:4376-4382），不触发 ReAct 循环、不产生事件、不走 `buildAgentStream`。
- **订阅惰性**：`Flux.create` 的 sink lambda 只在订阅时运行（`:1043-1045`）；`runLifecycle = Mono.using(this::acquireExecution, resource -> Mono.deferContextual(cv -> runInContext(...)), this::releaseExecution)`（AgentBase.java:256-262）；`doCall` 用 `Mono.deferContextual`（ReActAgent.java:1206）；`MiddlewareChain.build` 只组装 `Function`，`.apply(...)` 在装配期执行，但 `core` 仍是惰性 `Flux.create`。订阅前不执行。

## Execution Control: AgentRun

- 单次执行句柄 `AgentRun<T>`（`agent/AgentRun.java:38`，Javadoc "A single-use, lazy execution handle"）；创建入口 `prepareRun` / `prepareCall` → `AgentRun.create(agentId, source)`（ReActAgent.java:1101-1107 / AgentRun.java:103-105）。
- 暴露方法：`runId()` / `status()` / `stream()` / `termination()` / `cancel()` / `interrupt(Msg)` / `interrupt()`（AgentRun.java:108-138）；`Status` 六值 `CREATED/QUEUED/RUNNING/COMPLETED/FAILED/CANCELLED`（`:40-46`），单订阅保护 `subscribed.compareAndSet(false, true)`（`:66-69`）。
- 底层 `RunControl`（`agent/RunControl.java:28`）：含 `InterruptControl interruption`、`Sinks.Empty<Void> cancellation`、状态机 `queue/start/cancel/interrupt/finish`（`:52-103`）。
- **取消传播**：`RunControl.cancel()` → `cancellation.tryEmitEmpty()`（`:69-79`）；`guard()` 用 `takeUntilOther(cancellation.asMono())` 截断上游 + 抛 `CancellationException`（`:106-117`）；`buildAgentStream` 的 `sink.onCancel(lifecycleDisposable)`（ReActAgent.java:1093）与工具流 `sink.onCancel(toolCallsDisposable)`（`:3305`）把取消一路传播到 lifecycle 订阅 → 模型 `Flux` / 工具 `Mono`。
- **协作中断**：`interrupt(Msg)` → `control.interrupt(USER, msg)`，未启动时退化为 `cancel()`（RunControl.java:82-93）；`InterruptControl.trigger` 置 `AtomicBoolean flag`（interruption/InterruptControl.java:37-43）。该 `InterruptControl` 在 `beforeAgentExecution` 挂到 `scope.interruption`（ReActAgent.java:766），由 `checkInterrupted()` 在 reasoning 开始、streaming 每个 chunk、进 acting 前检查（`:1812-1819 / :2418 / :2590 / :2657`），抛 `InterruptedException` → `handleInterrupt` 补 error tool_result 并存盘（`:4339-4374`）。功能语义见 [智能体分册执行控制](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Agent.md)。

## Event Stream Source

- 真正 emit 事件的是 **`FluxSink`**，不是 `Sinks.Many`：`buildAgentStream` 用 `Flux.create` 拿 `FluxSink<AgentEvent>`（ReActAgent.java:1041-1045），`OverflowStrategy.BUFFER`（`:1095`）。
- 发布统一走 `CallExecution.publishEvent` → `FluxSink.next`（`:2226-2233`）；`AgentEventEmitter` 是工具侧函数式接口 = `sink::next`（event/AgentEventEmitter.java:38-39 / :63-64 注释 "the underlying FluxSink.next is thread-safe"）。
- **背压与多订阅者**：BUFFER = 无界缓冲，不丢事件、不向下游传导背压。`Flux.create` 是冷流、非多播，每次订阅独立 sink（ReActAgent.java:1141-1142 "each subscription gets its own event sink and lifecycle execution"）；`AgentStartEvent` / `AgentEndEvent` / `AgentResultEvent` 都写进订阅专属 sink。事件类型枚举 `AgentEventType` 共 **31** 值（event/AgentEventType.java:42-90），功能语义见 [消息分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Message.md)。

## Message Aggregation

两层，别混：

1. **增量块 → 单条 reasoning `Msg`**：`ReasoningContext` 用三个累加器 `TextAccumulator` / `ThinkingAccumulator` / `ToolCallsAccumulator`（agent/accumulator 包）把 chunk 聚合成 `AssistantMessage`（`ReasoningContext.java:162-208`，调用点 ReActAgent.java:2488-2489）。`ToolCallsAccumulator` 按 tool-call key 分桶累加 `args` + `rawContent`（ToolCallsAccumulator.java:59-115）。
2. **call 的最终 `Msg`**：从 `AgentResultEvent.getResult` 取（callInternal，ReActAgent.java:1012-1020），不是把 delta 事件重拼；`AgentResultEvent` 在完成时发出（`:1088-1091`），紧接 `doFinally` 发 `AgentEndEvent`。
- `ContentBlock` 是 **sealed 抽象类**，`permits` 9 个 final 子类（`message/ContentBlock.java:58-67`）：`TextBlock` / `ThinkingBlock` / `ImageBlock` / `AudioBlock` / `VideoBlock` / `ToolUseBlock` / `ToolResultBlock` / `HintBlock` / `DataBlock`。

## Tool Execution Chain

- **注册** `Toolkit.registerTool(Object)`：对象是 `AgentTool` 直接注册；否则 `getDeclaredMethods()` + `isAnnotationPresent(Tool.class)` 反射扫描（Toolkit.java:176-200）→ `ReflectiveFunctionTool`（ToolBase 子类） → `toolRegistry.registerTool`（`:233-237`）；MCP 注册（`:653-655`）。
- **schema 生成** `ToolSchemaGenerator.generateParameterSchema`（只收带 `@ToolParam` 的参数，类型 schema 由 `JsonSchemaUtils.generateSchemaFromType` 生成）（ToolSchemaGenerator.java:50-93）。
- **并行还是串行**：`ToolkitConfig.Builder.parallel` 默认 **true**（tool/ToolkitConfig.java:127）。`!parallel` → `Flux.concat` 严格串行；`parallel` → 按 `isConcurrencySafe` 把连续 safe 工具切批，用 **`Flux.mergeSequential`** 并发且保序，不安全或不可探查的 legacy 工具单独成串行槽（ToolExecutor.java:374-434）。**结果顺序保证**：`mergeSequential` 保序 + `collectList`；`ReActAgent.dispatchToolCalls` 把结果按 index 与 tool id 配对（`:3596-3599`），再按**原 `toolCalls` 顺序** `concatMap` 重组（`:3604-3623`）。
- **单工具异常** `onErrorResume` → `ToolResultBlock.error`，不中断整批（ToolExecutor.java:479-488）。功能语义见 [工具分册 MCP 与工具组](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Tool.md)。

## Permission Decision Chain

- `PermissionBehavior` 4 值：`ALLOW` / `DENY` / `ASK` / **`PASSTHROUGH`**（工具把决策踢回引擎做规则匹配）（permission/PermissionBehavior.java:32-36）；`PermissionMode` 5 值 `DEFAULT/ACCEPT_EDITS/EXPLORE/BYPASS/DONT_ASK`。默认 mode = `DEFAULT`（PermissionContextState.Builder.mode，PermissionContextState.java:202）。
- **六步决策**（`PermissionEngine.checkPermission`，PermissionEngine.java:139-178，javadoc :31-41）：`deny 规则` → `ask 规则` → `工具自带检查（bypass-immune）` → `allow 规则` → `BYPASS 模式兜底` → `默认 ASK（DONT_ASK 模式下变 DENY）`。
- **bypass-immune 的真相**：工具 `checkPermissions` 在第 3 步先于 BYPASS 兜底执行（`:156 / :188-196`）；工具返回 `DENY` / `ASK` 或 decisionReason 含 `"safety"` 的 `ASK` 直接 `return`，根本进不到 `continueAfterToolCheck` 里的 BYPASS 分支。`ToolBase` 默认 `checkPermissions` 返回 `passthrough`（ToolBase.java:235-238），所以**只有工具未 override（或返回 PASSTHROUGH）时 BYPASS 才生效**。
- **危险路径** `ToolBase.isDangerousPath`（大小写不敏感匹配 + `toRealPath()` 解符号链接再查）（ToolBase.java:263-299）；常量 `ToolDangerousPathConstants`：`DEFAULT_DANGEROUS_FILES` 22 项（`.gitconfig` / `.bashrc` / `.env*` / `.ssh/config` 等）、`DEFAULT_DANGEROUS_DIRECTORIES` 4 项（`.git/.vscode/.idea/.ssh`）、`DANGEROUS_COMMANDS` 11 项（`rm -rf` / `chmod 777` 等）。
- **规则 DSL**：无统一 parser。`PermissionRule` 是 record（tool_name / rule_content / behavior / source）；`ruleContent` 的语义由 `tool.matchRule(content, input)` 解释（PermissionEngine.java:310-316），`ToolBase` 默认实现 `return ruleContent == null`（ToolBase.java:244-246，即只有工具名级规则命中）。功能语义见 [工具分册权限](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Tool.md)。

## Middleware Composition

- `MiddlewareBase` 是接口，**6 个方法**：`order()` + 5 个拦截（`MiddlewareBase.java:59-160`）。其中 4 个洋葱型 `onAgent` / `onReasoning` / `onActing` / `onModelCall`（before/after 包裹），1 个管道型 `onSystemPrompt`（顺序变换字符串）。`order()` 默认 1，是排序配置不是 hook。
- **order 决定洋葱顺序**：`Builder.build()` 里 `middlewares.sort(Comparator.comparingInt(MiddlewareBase::order).reversed())`（ReActAgent.java:5620-5621），大 order 在前、同级稳定。`MiddlewareChain.build` 从最后一个向前循环组合（`:46-62`），列表第一个成为最外层。
- **onSystemPrompt 管道串接** `applySystemPromptMiddlewares`：先用反射检查是否有任一中间件覆写了 `onSystemPrompt`（未覆写则原样返回），否则 `Mono` 链式 `flatMap` 串行接力，顺序 = 排好序的列表（ReActAgent.java:789-820）。
- **after 阶段是否逆序**：框架只显式编排 before；after 依赖中间件把后置挂到返回 `Flux` 上（`.doFinally` 等），Reactor 终止信号由内向外传播 → 严格逆序是**官方范式而非框架强制**。未找到显式的 after 栈 / 逆序注册表。功能语义见 [工具分册中间件](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Tool.md)。

## Structured Output

- 分发 `doStructuredCall(msgs, targetClass, schemaDesc)`：`JsonSchemaUtils.generateSchemaFromClass(targetClass)` / `generateSchemaFromJsonNode(schemaDesc)` 生成 schema，再判 `Model.supportsNativeStructuredOutput()`（ReActAgent.java:1254-1281）。
- **native 路径**：`ResponseFormat.jsonSchema(...)` 直传，模型返回 JSON 后 `wrapNativeStructuredResult` 用 `fromJson(text, Object.class)` 写入 metadata `_structured_output`（`:1276-1281 / :1419-1424`）。**解析失败只 `log.warn` 原样返回，不抛错、不重试**（`:1433-1436`）。
- **fallback 路径**：注入 `generate_response` 合成工具（`:1358-1377`），`ToolValidator.validateInput` 校验 schema（`:3630-3641`）；校验失败作为错误 `ToolResultBlock` 回灌，下一轮 reasoning 自然看到错误 → 由 ReAct 循环再试（非独立重试组件）。
- **最终类型转换** `Msg.getStructuredData(Class<T>)` via Jackson `convertValue`（Msg.java:443-452）；未找到结构化输出专用重试次数配置；`StructuredOutputReminder` 枚举在 v2.0.4 主源码无使用点（v2 changelog 标 "No longer needed"）。功能语义见 [智能体分册结构化输出](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Agent.md)。

## Model Failover And SPI

- **配置**：`ModelConfig(DEFAULT_MAX_RETRIES = 3)`（agent/config/ModelConfig.java:36）；`ExecutionConfig.MODEL_DEFAULTS`（`timeout 5min` / `maxAttempts 3` / `initialBackoff 2s` / `maxBackoff 30s` / `backoffMultiplier 2.0`，ExecutionConfig.java:145-153），`RETRYABLE_ERRORS` 判 429 / 5xx / `TimeoutException` / `IOException`（`:91-128`）；`TOOL_DEFAULTS` `maxAttempts(1)` 不重试（`:163-164`）。
- **retry**：`ModelUtils.applyTimeoutAndRetry` 用 Reactor `Retry.backoff(maxAttempts-1, initialBackoff).maxBackoff(...).jitter(0.5).filter(retryOn)` + `retryWhen`（ModelUtils.java:117-132）；工具侧 `ToolExecutor.applyRetry` 同构。
- **fallback**：`modelForCall()` 返回匿名 `Model` 包装，`Flux.defer` + `switchOnFirst` 在首个错误信号切到 fallbackModel（ReActAgent.java:4274-4299）；无 fallbackModel 时原样返回；`FailoverListener` 吞异常只记日志。
- **Formatter 不聚合 chunk**：`Formatter` 接口只有 `format` / `parseResponse` / `applyOptions` / `applyTools` / `applyToolChoice`（formatter/Formatter.java:55-160）；流式 chunk 聚合在 `agent/accumulator` 包（见上文 Message Aggregation）。
- **SPI**：`ModelRegistry` + `ModelProvider` 接口 + `META-INF/services/io.agentscope.core.model.spi.ModelProvider`（每个扩展模块一个文件：`dashscope/anthropic/gemini/ollama/openai` 含 `DeepSeek/Kimi/GLM/MiniMax`），`ServiceLoader.load(ModelProvider.class)` 自动发现（ModelRegistry.java:367-370）。
- **解析链**：`model("dashscope:qwen-plus")` 把**完整** modelId 交给 Provider 的 `supports(modelId)` 正则匹配、`create` 时再自己 `substring(PREFIX.length())` 剥前缀（`DashScopeModelProvider.java:41-85`）；`ModelRegistry` 本身**不按冒号 split**。功能语义见 [智能体分册模型容错](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Agent.md)。

## Harness Composition

- `HarnessAgent implements Agent, AutoCloseable`，**组合**非继承 `ReActAgent`：`private final ReActAgent delegate`（HarnessAgent.java:169 / :205）；builder 内持 `ReActAgent.Builder inner`（`:1196`）；`build()` 末尾 `inner.build()` → `new HarnessAgent(delegate, ...)`（`:2946-2968`）。
- `build()` 各阶段注入（`HarnessAgent.java:2361` 起，`build()` 行号）：

| 阶段 | 行号 | 注入内容 |
| :--- | :--- | :--- |
| Validation | `:2361-2380` | 三种 filesystem spec 互斥校验、`resolveDefaultWorkspace`、`resolvedAgentId` |
| DistributedStore 自动接线 | `:2381-2407` | `stateStore` / `baseStore` / `snapshotSpec` / `executionGuard` / `messageBus` / `asyncToolRegistry` |
| 默认 stateStore | `:2426-2429` | `new JsonFileAgentStateStore(defaultStateDir(resolvedAgentId))` → `inner.stateStore(...)` |
| Sandbox 集成 | `:2446-2484` | `SessionSandboxStateStore` / `SandboxManager` / `SandboxLifecycleMiddleware`；`filesystem` 换 `SandboxBackedFilesystem` |
| WorkspaceManager | `:2485-2502` | `workspaceFactoryFn`（`BakedContextFilesystem` + `NamespaceFactory`） |
| MessageBus 默认 | `:2504-2515` | `WorkspaceMessageBus(filesystem, ".agentscope/bus")` |
| Middlewares | `:2518-2685` | sandbox / `MemoryFlushMiddleware` / `InboxMiddleware` / `DynamicSubagentsMiddleware` / `SubagentsMiddleware` / `AsyncToolMiddleware` |
| Toolkit（memory/fs/shell 工具） | `:2687-2689` | `MemorySearchTool` 等注册 |
| Plan mode | `:2735` | 计划模式中间件 |
| workspace/tools.json（MCP + 过滤） | `:2757 / :2933-2937` | `ToolFilter.apply` |
| **Skills** | `:2773-2812` | `composeSkillRepositories(...)` + 可写仓库 + `skill_manage` 自学习 |
| 构建内层 | `:2946-2948` | `inner.toolkit(agentToolkit); ReActAgent delegate = inner.build();` |

> Builder setter（`model` / `workspace` / `filesystem` / `memory` / `subagent` / `skillRepository`）只暂存配置，最终在 `build()` 注入内层——`toolkit(...)` 明确标注 "Don't push to inner yet"（HarnessAgent.java:1543-1548）。功能语义见 [工作区分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Workspace.md) 与 [技能分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Skill.md)。

## State Persistence And Recovery

- **没有名为 `checkpoint` 的类或配置**。持久化触发点在每次 `doCallInner` 成功后 `saveStateToSession`（ReActAgent.java:1226-1233），失败走 `saveStateAfterCallFailure`；写入实现 `saveStateToSession` / `persistAgentStateCas`（`:475-496 / :535-640`）。
- `AgentState` 字段（`state/AgentState.java:59-69`）：`sessionId` / `userId` / `summary` / `List<Msg> context` / `replyId` / `int curIter` / `boolean shutdownInterrupted` / `PermissionContextState` / `ToolContextState` / `TaskContextState` / `PlanModeContextState`；Jackson 整对象 pretty JSON（`toJson` / `fromJsonString`，`:250-259`）。
- **恢复**：`loadOrCreateAgentStateForSlot` → `stateStore.getVersioned` → 缺失则 `LegacyStateLoader`（一次性兼容，不直接迁移原数据；后续保存自动用新格式）（ReActAgent.java:432-443 / state/LegacyStateLoader.java:24-30）。`JsonFileAgentStateStore` 默认根 `~/.agentscope/state`，路径 `(userId, sessionId)` → `safeSegment + normalizeUser`（`null` 映射 `__anon__`）（JsonFileAgentStateStore.java:285-301 / :386-405）。
- **冲突策略** `ConflictPolicy` 三值 `OVERWRITE / FAIL / APPEND_MERGE`（state/ConflictPolicy.java:34）；`persistAgentStateCas` 按策略处理（ReActAgent.java:535-640）。
- **跨副本**：Redis / JDBC / Mongo / PG / COS / OSS 各实现 `BaseStore`，版本 CAS 用 Lua 或读 `.version` 比较（`RedisStateVersionSupport` / `OssBaseStore`）；service 侧 `SessionEventLog` 用 seq 唯一约束 + `MAX_SEQ_RETRIES = 16` 冲突重试（service-common/.../managed/service/SessionEventLog.java:52 / :225 / :240-259）。
- ⚠️ **源码校准**：官方文档站描述的 `commits` / `blobs` / `exports` / `inbox` 四目录 Session Log，以及 `WorkspaceSessionLogStore` / `JournalSessionLog` / `AtomicSessionStorage` / `SessionMigration` / `SessionLogExporter` / `SessionRecorder` / `SessionEventCodecRegistry` 等类名，在 v2.0.4 主源码（`core` / `harness` / `extensions` / `service`）中**未落地**——core 里甚至没有 `session/` 包。v2.0.4 真实持久化是上面的 `AgentStateStore`（`JsonFile` / Redis / JDBC / Mongo / PG / COS / OSS）与 harness 的 `TranscriptStore` / `SessionTranscriptWriter`（append-only JSONL）。[会话分册 Compat Session Tree 段](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Session.md) 写的 `.log.jsonl` + `TranscriptStore` 才是源码事实；其 Object Layout 段的 `commits/blobs/exports/inbox` 来自文档站逻辑对象模型，应以本文与 Compat Session Tree 段为准。

## Links

- [主笔记](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/AgentScopeJava.md)
- [智能体分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Agent.md)
- [消息分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Message.md)
- [工具分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Tool.md)
- [上下文分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Context.md)
- [会话分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Session.md)

## References

- [AgentScope Java 执行（Agent）](https://java.agentscope.io/v2/zh/docs/building-blocks/agent)
- [AgentScope Java 消息与事件](https://java.agentscope.io/v2/zh/docs/building-blocks/message-and-event)
- [AgentScope Java 中间件](https://java.agentscope.io/v2/zh/docs/building-blocks/middleware)
- [AgentScope Java 模型](https://java.agentscope.io/v2/zh/docs/building-blocks/model)
- [agentscope-java GitHub（v2.0.4）](https://github.com/agentscope-ai/agentscope-java)
