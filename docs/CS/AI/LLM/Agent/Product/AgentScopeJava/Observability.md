## Introduction

本分册覆盖 AgentScope Java v2.0.4 的**可观测性（observability）**机制——即「一次 agent 调用内部的每一步，如何被记录、被追踪、被导出供外部系统消费」。它不是单一的子系统，而是沿执行链路铺开的几层能力，且 v2.0.4 正处于从 legacy 体系向现代体系的迁移期，因此本分册特意用源码事实标清「哪些是现状、哪些是废弃、哪些是 extension 才有的增强」，避免把文档站未落地的描述当真。

所有类名、枚举值、方法签名与默认值均核对自本地 `v2.0.4` 源码树（`agentscope-core/.../event/`、`.../tracing/`、`.../hook/`、`.../middleware/`，以及 `agentscope-extensions-studio/.../tracing/telemetry/`）。与官方文档冲突处以源码为准。

## The Observability Model

AgentScope Java 的可观测性由四层叠加构成，沿「信息最丰富 → 最轻量」排列：

| 层 | 包 / 类 | 状态 | 作用 |
| :--- | :--- | :--- | :--- |
| 现代事件流 | `io.agentscope.core.event.AgentEvent`（+`AgentEventType` 31 值） | **现状，主路径** | `streamEvents()` 逐事件交付，`call()` 消费全部事件还你一条 `Msg` |
| 中间件拦截 → 追踪 | `OtelTracingMiddleware`（`MiddlewareBase`） | **现状，推荐 trace 路径** | 把 agent / 模型 / 工具三段包成 OpenTelemetry span |
| Legacy Hook 事件 + 导出 | `io.agentscope.core.hook.Hook` + `JsonlTraceExporter` | **@Deprecated 2.0.0** | 老全局事件 + JSONL 本地 trace 文件 |
| Studio 遥测桥 | `agentscope-extensions-studio` 的 `TelemetryTracer` | **extension 可选** | 更完整的 GenAI incubating 语义 + OTLP 导出 |

⚠️ **两层事件体系是最大的陷阱**：现代 `OtelTracingMiddleware` 消费的并不是 legacy `hook` 包的事件，而是现代的 `io.agentscope.core.event` 事件（`AgentStartEvent` / `ModelCallEndEvent` / `ToolResultEndEvent` 均来自后者）。`hook` 包是 2.0.0 被取代的老机制，两者**并存但互不直接耦合**。`ReActAgent` 的核心循环只走现代 `MiddlewareBase` + `AgentEvent` 路径；legacy `Hook` 的发射被收敛进 `LegacyHookDispatcher`，只为向后兼容。

**设计动机**：为什么可观测性要做成「事件流 + 中间件」而非「全局 AOP 拦截」？因为 agent 执行本质是 Reactor 异步流，跨 `publishOn` / `subscribeOn` 的线程跳变会让 ThreadLocal 上下文（如 trace parent）丢失；现代方案把事件从 `FluxSink` 源头发出、把 OTel context 注入 Reactor `ContextView`，从根上解决传播问题（见 [Middleware Tracing: OtelTracingMiddleware](#middleware-tracing-oteltracingmiddleware)）。legacy `TracerRegistry` 用 `Hooks.onEachOperator` 全局拦截 JVM 内**所有** Reactor 流来传播 context，代价是无关流也背上包裹 subscriber 的开销——这正是它被废弃的原因。

## Event Stream: AgentEvent

`io.agentscope.core.event.AgentEventType` 是执行期发射的细粒度事件类型枚举，**v2.0.4 共 31 个值**（已与 `AgentEventType.java` 逐一核对，与已知「易错计数」记录一致）。按语义分组：

- **Agent 生命周期**：`AGENT_START` / `AGENT_END` / `AGENT_RESULT`
- **模型调用**：`MODEL_CALL_START` / `MODEL_CALL_END`
- **文本块流式**：`TEXT_BLOCK_START` / `TEXT_BLOCK_DELTA` / `TEXT_BLOCK_END`
- **思考块流式**：`THINKING_BLOCK_START` / `THINKING_BLOCK_DELTA` / `THINKING_BLOCK_END`
- **数据块（二进制 / 文件）**：`DATA_BLOCK_START` / `DATA_BLOCK_DELTA` / `DATA_BLOCK_END`
- **工具调用**：`TOOL_CALL_START` / `TOOL_CALL_DELTA` / `TOOL_CALL_END`
- **工具结果**：`TOOL_RESULT_START` / `TOOL_RESULT_TEXT_DELTA` / `TOOL_RESULT_DATA_DELTA` / `TOOL_RESULT_END`
- **控制流**：`EXCEED_MAX_ITERS` / `REQUIRE_USER_CONFIRM` / `REQUIRE_EXTERNAL_EXECUTION` / `USER_CONFIRM_RESULT` / `EXTERNAL_EXECUTION_RESULT` / `REQUEST_STOP`
- **编排 / 诊断**：`SUBAGENT_EXPOSED` / `HINT_BLOCK` / `ALL_TOOLS_DENIED` / `CUSTOM`

**序列化兼容（打假点）**：每个枚举值带 `@JsonValue` 发射 canonical 名，同时用 `@JsonAlias` 保留一批**旧名字**以便老 JSON 反序列化——`RUN_STARTED` / `REPLY_START` → `AGENT_START`，`RUN_FINISHED` / `REPLY_END` → `AGENT_END`，`MODEL_CALL_STARTED` / `MODEL_CALL_ENDED`，`BINARY_BLOCK_*` → `DATA_BLOCK_*`，`TOOL_RESULT_BINARY_DELTA` → `TOOL_RESULT_DATA_DELTA`，`THREAD_EXPOSED` → `SUBAGENT_EXPOSED`。`fromValue(String)` 同时做 canonical 与 legacy 兜底匹配。这说明事件 schema 仍在演进，下游消费者**必须**用 `fromValue` 而非按字符串硬匹配，否则老持久化数据解析失败。

### AgentEventEmitter: 工具内发事件

`AgentEventEmitter`（`event/AgentEventEmitter.java`）是 functional interface，把发射器实例存进 Reactor `ContextView`（key `agentscope.agent.event.emitter`）。它的存在让**运行在流式 pipeline 之内的工具方法**（如 `agent_spawn`）也能往父 agent 的 `streamEvents()` 流里注入自定义事件（如 `SubagentExposedEvent`）：

```java
// 工具内部取发射器
AgentEventEmitter.fromContext(ctx).ifPresent(emitter -> emitter.emit(new SubagentExposedEvent(...)));
```

两个关键设计：

- **子 agent 事件转发标记**：`FORWARDING_CONTEXT_KEY`（`agentscope.agent.event.forwarding.emitter`）让父工具把「带 source-path 标签的转发发射器」注入子 agent 的 Reactor Context，使子 agent 的每条内部事件在进入父流前被打上来源路径——实现嵌套 agent 的可追溯。
- **非流式优雅降级**：当 agent 经 `call()`（非 `streamEvents()`）调用时，Reactor Context 里**没有**发射器，`fromContext` 返回 `Optional.empty()`，调用方直接跳过事件发射即可。这保证「可观测性增强」永远不会成为主链路的硬依赖。

**设计动机**：为什么事件流是「一等公民」而不是事后埋点？因为 `call()` 与 `streamEvents()` **共用同一条执行核**（`buildAgentStream`），事件从 `FluxSink` 源头发出，`call()` 的终结 `Msg` 是从 `AgentResultEvent` 取的——观测与执行是同一份数据，不存在「两套真相」。再加上 Reactor Context 传递，连跨线程运行的工具都能可靠发事件，使「agent 调用一个会 spawn 子 agent 的工具」这类深度嵌套场景依然可被完整追踪。

## Middleware Tracing: OtelTracingMiddleware

`OtelTracingMiddleware`（`core/tracing/OtelTracingMiddleware.java`，实现 `MiddlewareBase`）是当前**官方推荐**的分布式追踪接入点。它不自己持有 span 存储，而是从**全局已注册的 OpenTelemetry** 取 tracer：

```java
private Tracer getTracer() {
    return GlobalOpenTelemetry.getTracer(INSTRUMENTATION_NAME); // "io.agentscope"
}
```

构造时通过 DCL（double-checked locking）注册一次 `ContextPropagationOperator.registerOnEachOperator()`——这是 OTel 的 Reactor 上下文传播算子，确保 span 的 parent context 在 `publishOn` / `subscribeOn` 线程跳变后依然能被子 span 正确找到。**这是它替代 legacy `TracerRegistry` 全局 hook 的根本原因**：旧方案拦截 JVM 内所有 Reactor 流，新方案只注入与 tracing 相关的传播，且由用户按需挂载中间件。

### 三个 Span

| Middleware 钩子 | Span 名 | 关键属性 |
| :--- | :--- | :--- |
| `onAgent` | `invoke_agent <name>` | `gen_ai.operation.name`、`gen_ai.agent.name`、`gen_ai.agent.id`、`gen_ai.request.messages.count`；`doOnNext` 抓 `AgentStartEvent.replyId` → `agentscope.agent.reply_id` |
| `onModelCall` | `chat <model>` | `gen_ai.request.model`、`gen_ai.request.messages.count`、`gen_ai.request.tools.count`；结束时写 token 用量 |
| `onActing` | `execute_tool <name>` | `gen_ai.tool.name`（逗号分隔）、`gen_ai.tool.call.count`、`gen_ai.tool.call.id`（收集 `ToolResultEndEvent` 的 tool call id） |

**Token 用量属性**走 OpenTelemetry **GenAI semantic conventions**（`gen_ai.usage.input_tokens` / `output_tokens` / `cache_creation.input_tokens` / `cache_read.input_tokens` / `reasoning.output_tokens`），外加一个 AgentScope 私有属性 `agentscope.usage.tool_use_prompt_tokens`——因为 GenAI 约定**尚未定义**「工具提示 token」字段，框架用私有前缀兜底，避免与未来官方字段冲突。

### Span 结束的竞态防护

每个 span 用 `AtomicReference<Boolean> ended` + `compareAndSet(false, true)` 包住 `doOnComplete` / `doOnError` / `doOnCancel` 三路终止信号：

```java
.doOnComplete(() -> { if (ended.compareAndSet(false, true)) { span.setStatus(StatusCode.OK); span.end(); } })
.doOnError(e -> { if (ended.compareAndSet(false, true)) { span.setStatus(StatusCode.ERROR, e.getMessage()); span.recordException(e); span.end(); } })
.doOnCancel(() -> { if (ended.compareAndSet(false, true)) { span.setStatus(StatusCode.ERROR, "cancelled"); span.end(); } })
```

**设计动机**：Reactor 流可能因取消（如客户端断连）与完成 / 错误信号竞发，不加 CAS 会导致同一个 span 被 `end()` 两次（OTel 会报非法状态）。CAS 保证「三选一」只生效一次。

### 零成本短路与基数控制

- **无 SDK 时近零开销**：若只激活了 OTel 默认的 no-op provider（即用户没 `buildAndRegisterGlobal` 任何 `OpenTelemetrySdk`），每个 hook 直接短路返回原流，不创建 span。
- **Span 名基数控制**：`execute_tool` 的 span 名取**首个工具名**并追加 `(+N more)`（N = 其余工具数），完整工具名列表仍在 `gen_ai.tool.name` 属性里。防止「一次 batch 调几十个工具」把 span 名空间撑爆——这是 LLM 应用接入 APM 时的常见基数炸弹。

**设计动机**：为什么追踪挂在 middleware 而非 agent 内部硬编码？因为 middleware 是 v2 的可替换装配层（与 filesystem / store / sandbox 同思路），用户不想要 trace 就不挂这个 middleware，连 hook 注册开销都没有；想要更强语义就换 extension 的 `TelemetryTracer`（见下）。框架把「观测什么、怎么导出」完全交给用户侧的 OTel 配置，自己只负责**产出规范 span**。

## Legacy Hook System

`io.agentscope.core.hook` 包（含 `Hook` 接口、`HookEvent` sealed 类、`HookEventType` 枚举、`LegacyHookDispatcher`、`recorder.JsonlTraceExporter`）整体 `@Deprecated(since = "2.0.0", forRemoval = true)`。它代表 2.0 之前的全局事件 / 拦截机制，2.0 起被 `MiddlewareBase` + `AgentEvent` 取代，仅保留向后兼容。

### Hook 接口与事件类型

`Hook` 是单一方法 `onEvent(T event)` 的接口，配 `priority()`（默认 100，值越小优先级越高）与可选 `tools()`（hook 可顺带注册工具进 agent 本地 toolkit）。事件分两类：

- **可修改**（含 setter）：`PreReasoningEvent` / `PostReasoningEvent` / `PreActingEvent` / `PostActingEvent` / `PreCallEvent` / `PostCallEvent`——hook 改了消息 / 工具参数 / 结果会回灌执行。
- **只读**（通知）：`ReasoningChunkEvent` / `ActingChunkEvent` / `ErrorEvent`。

`HookEventType` 共 **12 个值**：`PRE_CALL` / `POST_CALL` / `PRE_REASONING` / `POST_REASONING` / `REASONING_CHUNK` / `PRE_ACTING` / `POST_ACTING` / `ACTING_CHUNK` / `PRE_SUMMARY` / `POST_SUMMARY` / `SUMMARY_CHUNK` / `ERROR`。`HookEvent` 是 sealed 抽象类，只允许 6 个具体子类（`PreCallEvent` / `PostCallEvent` / `ReasoningEvent` / `ActingEvent` / `SummaryEvent` / `ErrorEvent`），从而支持 switch 穷举。

`ReActAgent` 持有一个 `LegacyHookDispatcher`，把 hook 的构造与分发从主循环剥离。`fire(event)` 用 `Mono.just(event).flatMap(hook::onEvent)` 按 `getSortedHooks()`（priority 升序）串成链；chunk 类事件则用 `Flux.fromIterable(getSortedHooks()).flatMap(...).then()` 广播。

## JsonlTraceExporter

`JsonlTraceExporter`（`hook/recorder/JsonlTraceExporter.java`）是内置的、开箱即用的 trace 导出器——它**本身就实现 `Hook` 接口**，把每个 `HookEvent` 写成一行 JSON，专为本地调试、离线排障、随 issue 附日志设计。

每行记录的基础字段：

```json
{"ts":..., "event_type":"PRE_REASONING", "agent_id":..., "agent_name":...,
 "run_id":..., "turn_id":..., "step_id":..., "...事件特有字段...",
 "trace_id":..., "span_id":...}
```

事件特有字段按类型分支写入：`input_messages` / `final_message` / `model_name` / `reasoning_message` / `tool_use` / `tool_result` / `incremental_chunk` / `error_class` / `error_message` / `stacktrace` 等。

**Run / Turn / Step 跟踪**：用 `WeakHashMap<String, RunState>`（key = agentId）维护每 agent 的运行计数。`PRE_CALL` 触发新 run（`currentRunId = UUID`、`turnId++`、`stepId = 0`），后续事件 `stepId++`，从而把交错的事件重新组装成「哪次调用、哪一轮、第几步」。

**OTel 关联（跨系统跳转）**：`OpenTelemetryAccess` 用**反射**调用 `Span.current().getSpanContext()` 取当前活动的 `trace_id` / `span_id` 注入每条记录。反射而非编译依赖的原因：core 只依赖 OTel **API**；若运行环境没有 OTel SDK，`Class.forName` 失败则 `OpenTelemetryAccess` 全字段为 `null`，`putIfPresent` 静默跳过——JSONL 与 OTel trace 的关联是**有则增强、无则降级**，绝不因缺 SDK 而崩。

**IO 模型与其他默认值**：导出在**单线程 daemon 执行器**（`agentscope-jsonl-trace-exporter`）上做阻塞文件 IO，以保证「行顺序 / step id / run id」天然一致；`flushEveryLine` 默认 `true`；`failFast` 默认 `false`（best-effort——序列化或 IO 错误只 warn，不打断 agent 执行）；`priority` 默认 `900`（落入 Hook 文档建议的「501–1000 logging / metrics」低优先级段）；`enabledEvents` 默认只开 `PRE_CALL` / `POST_CALL` / `PRE_REASONING` / `POST_REASONING` / `PRE_ACTING` / `POST_ACTING` / `ERROR` 7 类，流式 chunk 与 summary 默认关闭（由 `includeReasoningChunks` / `includeActingChunks` / `includeSummary` 等开关打开）。`close()` 提交一个 barrier 任务等队列排空（30s 超时），再安全关闭 writer。

**设计动机**：为什么用 `WeakHashMap` 存 run state？因为 exporter 是进程级单例、按 agentId 索引，若用普通 Map，已不再被引用的 agent 实例的 run state 会永久堆积导致内存泄漏；弱键使它随 agent 实例 GC 自动清理（并发安全不依赖 WeakHashMap 本身——所有访问经单线程队列串行化）。

## Studio TelemetryTracer

`agentscope-extensions-studio` 模块提供 `TelemetryTracer`（`core/tracing/telemetry/TelemetryTracer.java`）。需要注意一个**容易混淆的点**：它实现的 `Tracer` 接口，正是 core 里那个 `@Deprecated` 的老 `io.agentscope.core.tracing.Tracer`（包装式 `callAgent` / `callModel` / `callTool`），**不是** `OtelTracingMiddleware` 的 `MiddlewareBase` 路径。也就是说，studio 的遥测桥走的是「老 Tracer 体系 + 更完整语义」这条正交线，与 core 推荐的 middleware 路径并存。

它的增强在于**语义完整度**：

- 使用 OpenTelemetry **GenAI incubating** 语义约定（`GenAiIncubatingAttributes`）+ AgentScope 私有 incubating 属性（`AgentScopeIncubatingAttributes`），覆盖 `invoke_agent` / `chat` / `execute_tool` / `format` 四种 operation（比 core middleware 多一个 `format` / 结构化输出段）。
- `AttributesExtractors` 把 LLM / tool / agent / format 的请求与响应拆成细粒度属性；`StreamChatResponseAggregator` 把流式响应聚合成语义化的消息 parts（input / output message、tool definition、text / reasoning / file / blob / uri 等）。
- 它甚至可以自建 `SdkTracerProvider` + `BatchSpanProcessor` + `OtlpHttpSpanExporter` + `Sampler`，即自带 OTLP 导出能力，适合直接对接 Jaeger / Tempo / 云厂商 APM。

**定位总结**：core 的 `OtelTracingMiddleware` 是「轻量、规范、靠用户侧 OTel 配置导出」的**默认推荐**；studio 的 `TelemetryTracer` 是「重语义、自带聚合与导出、走老 Tracer 接口」的**可选增强**。二者都产出符合 GenAI semantic conventions 的 span，生产环境择一即可。

## What Core Does NOT Provide

- **core 没有 metrics registry**：全仓 grep `MeterRegistry` 只出现在 `agentscope-admin-spring-boot-starter`（`MetricsRecorder` / `UsageStats` / `MetricsHook` / `AgentscopeUsageEndpoint`）与 `agentscope-examples`（如 `CodingAgentMetrics`）。即 AgentScope Java 在 **core 层不提供指标抽象、不提供埋点 API**——「可观测性」在 core 只覆盖 **tracing（OTel span）+ logging / event（AgentEvent 流 + JSONL 导出）** 两层。Metrics 是 admin / service starter 的领域（基于 Spring Boot Actuator / Micrometer 之类），不在本分册范围。
- **core 没有内置 dashboard / exporter 配置**：OTel 的 `TracerProvider`、采样、`SpanExporter`（OTLP / Jaeger / Zipkin）全部由用户侧代码或 studio extension 提供；框架只负责「在正确的 lifecycle 点产出 span」。

## Links

- [主笔记](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/AgentScopeJava.md)
- [智能体分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Agent.md)
- [消息分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Message.md)
- [工具分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Tool.md)
- [执行内核分册](/docs/CS/AI/LLM/Agent/Product/AgentScopeJava/Execution.md)

## References

- OpenTelemetry GenAI semantic conventions (current source of truth): https://github.com/open-telemetry/semantic-conventions-genai
- OpenTelemetry Java Reactor ContextPropagationOperator: https://github.com/open-telemetry/opentelemetry-java-instrumentation/tree/main/instrumentation/reactor/reactor-3.1/library
