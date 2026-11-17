> 版本基线：v1.5.2（commit `b4afdddf`，2026-11-10 发布）。全部结论以本地 `E:/Projects/pi-1.5.2` 该 tag 源码逐函数核验，结论以代码为准、非以文档为准。

## Introduction

Pi 把 agent 主循环拆成**有状态的外壳**与**无状态的核心循环**两层：生产路径是 `coding-agent/core` 的 `AgentSession`（外层，负责压缩/重试/排队/结算）驱动 `pi-agent-core` 的 `Agent`（内层 `runLoop`，只管一轮轮的"生成→工具→回填"）。这个切分是理解 Pi 全部机制的骨架——工具批次、steering/follow-up、压缩插入点都落在这两层的接缝上。

本文是原理专项，讲清两层循环如何咬合；包的完整分层与依赖见枢纽 [Pi 的 Architecture 章节](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md?id=architecture)，单次 turn 的事件时序见 [Events](/docs/CS/AI/LLM/Agent/Product/Pi/Events.md)。三个反直觉点先行：

- **没有最大轮数保护**：`runLoop` 就是裸 `while(true)`，只靠队列/退出条件收尾，不存在 `maxTurns`。
- **`stopReason==="length"` 时一条工具都不执行**：流式参数是 best-effort JSON 抢救出来的，参数"能校验但内容不全"，所以整批回填错误让模型重发。
- **`agent_end` ≠ `agent_settled`**：内层循环跑完只是 `agent_end`，外层还要过一遍裁决（重试/压缩/队列/before_settle）才真正结算。

## Two-Layer Collaboration

内层 `runLoop`（`packages/agent/src/agent-loop.ts`）是外层 `while(true)` 套内层 `while(hasMoreToolCalls || pendingMessages.length > 0)`。核心骨架原样如下：

```ts
	// Outer loop: continues when queued follow-up messages arrive after agent would stop
	while (true) {
		let hasMoreToolCalls = true;

		// Inner loop: process tool calls and steering messages
		while (hasMoreToolCalls || pendingMessages.length > 0) {
			let preparedMessages: AgentMessage[] = [];
			if (lastCompletedTurn) {
				const nextTurnSnapshot = await config.prepareNextTurn?.(lastCompletedTurn);
				if (nextTurnSnapshot) {
					currentContext = nextTurnSnapshot.context ?? currentContext;
					preparedMessages = nextTurnSnapshot.messages ?? [];
					// ... model/reasoning 更新
				}
				// Preparation can be long-running (for example, compaction). Pick up steering
				// queued while it ran. Only poll again if the earlier poll returned nothing;
				// otherwise one-at-a-time mode would deliver two messages in this turn.
				if (pendingMessages.length === 0) {
					pendingMessages = (await config.getSteeringMessages?.()) || [];
				}
				await emit({ type: "turn_start" });
			}
```

每个内层迭代就是一个 turn：`prepareNextTurn`（轮间压缩/更新 context）→ 注入 pending 消息 → `prepareRequest`（请求前最后一次裁决，含虚拟模型路由与阈值压缩）→ `streamAssistantResponse` → 解析 toolCall 并执行 → `finishTurn` → 轮边界轮询队列。收尾判定：

```ts
		// Agent would stop here. Check for follow-up messages.
		const followUpMessages = (await config.getFollowUpMessages?.()) || [];
		if (followUpMessages.length > 0) {
			// Set as pending so inner loop processes them
			explicitContinuation = false;
			pendingMessages = followUpMessages;
			continue;
		}

		// No natural request was selected, so fulfill the continuation decision with one context-only turn.
		if (explicitContinuation) {
			explicitContinuation = false;
			continue;
		}

		// No more messages, exit
		break;
	}

	await emit({ type: "agent_end", messages: newMessages });
```

外层 `_runAgentPrompt`（`AgentSession`）在每次内层 `agent_end` 后做唯一裁决：错误可重试 → `_prepareRetry`（省略失败尝试 + 指数退避）后续跑；压缩命中 → `_checkCompaction`/`_runAutoCompaction` 后续跑；队列非空 → `agent.continue()` 消费；三者皆否 → `_runBeforeSettleBoundary`（扩展的 `agent_before_settle` 钩子），返回 false 才 `emit agent_settled`。所以压缩/重试都发生在 turn 边界之后、下一轮生成之前，不会切进半截生成里。

```sequence
Title: Pi 两层循环交互（生产路径）

participant U as 调用方(CLI/RPC)
participant S as AgentSession._runAgentPrompt
participant A as Agent(agent.ts)
participant L as runLoop(agent-loop.ts)
participant P as Provider(streamSimple)
participant T as executeToolCalls
participant C as _handlePostAgentRun 裁决

U->>S: prompt(messages)
S->>A: agent.prompt(messages)
A->>L: runLoop()
loop 内层 while(还有 toolCall 或 pending 消息)
  L->>L: prepareNextTurn + 注入 steering
  L->>L: prepareRequest(虚拟模型路由/阈值压缩)
  L->>P: streamAssistantResponse(convertToLlm→streamSimple)
  P-->>L: AssistantMessage(toolCalls?/stopReason)
  alt stopReason==error/aborted
    L->>L: finishTurn+turn_end+agent_end→return
  else 含 toolCall
    L->>T: executeToolCalls(parallel/sequential)
    T-->>L: toolResults(全批 terminate 则早停)
  end
  L->>L: turn_end; 轮询 steering
end
L-->>S: agent_end
S->>C: 错误可重试/压缩命中/队列非空?
alt 需续跑
  C->>A: agent.continue()→runLoop()
else 进入结算
  C->>C: agent_before_settle→agent_settled
end
```

## The Stream Boundary

一个关键设计：**agent loop 全程用 `AgentMessage`，只在调 LLM 的边界转成 `Message[]`**。这让压缩摘要、分支摘要这类自定义消息能在会话树里存活，直到边界才变 provider 认得的格式：

```ts
	// Apply context transform if configured (AgentMessage[] → AgentMessage[])
	let messages = context.messages;
	if (config.transformContext) {
		messages = await config.transformContext(messages, signal);
	}

	// Convert to LLM-compatible messages (AgentMessage[] → Message[])
	const llmMessages = await config.convertToLlm(messages);

	const llmContext = normalizeContext({ messages: llmMessages });

	// Resolve API key (important for expiring tokens)
	const resolvedApiKey =
		(config.getApiKey ? await config.getApiKey(config.model.provider) : undefined) || config.apiKey;
```

`streamFn` 是注入点且有严格契约：必须"不 throw/reject"，错误要编码进流（`stopReason:"error"|"aborted"` + `errorMessage`）。coding-agent 通过 `modelRuntime.streamSimple` 注入（见 [Providers](/docs/CS/AI/LLM/Agent/Product/Pi/Providers.md)）。`proxy.ts` 的 `streamProxy` 甚至在干净 EOF 无 done/error 事件时主动造一个 error 事件，避免消费者死等。

## Tool Batches

一个 assistant 消息里的多个 toolCall 组成一个 batch，由 `executeToolCalls` 执行。默认**并发无上限**，但任一工具声明 `executionMode==="sequential"` 则整批降级串行：

```ts
	const toolCalls = assistantMessage.content.filter((c) => c.type === "toolCall");
	const hasSequentialToolCall = toolCalls.some(
		(tc) => currentContext.tools?.find((t) => t.name === tc.name)?.executionMode === "sequential",
	);
	if (config.toolExecution === "sequential" || hasSequentialToolCall) {
		return executeToolCallsSequential(currentContext, assistantMessage, toolCalls, config, signal, emit);
	}
	return executeToolCallsParallel(currentContext, assistantMessage, toolCalls, config, signal, emit);
```

并发路径里 `Promise.all` 一次性跑完，事件顺序与历史顺序**故意不同**：`tool_execution_end` 按完成顺序 emit（UI 实时性），`ToolResultMessage` 按 assistant 消息里的源顺序 emit 并入历史（回放稳定）：

```ts
	const orderedFinalizedCalls = await Promise.all(
		finalizedCalls.map((entry) => (typeof entry === "function" ? entry() : Promise.resolve(entry))),
	);
	const messages: ToolResultMessage[] = [];
	for (const finalized of orderedFinalizedCalls) {
		const toolResultMessage = createToolResultMessage(finalized);
		await emitToolResultMessage(toolResultMessage, emit);
		messages.push(toolResultMessage);
	}
```

`stopReason==="length"` 时整批判失败的理由写死在注释里：

```ts
/**
 * Fail all tool calls from an assistant message that was truncated by the
 * output token limit. Streamed tool-call arguments are finalized with a
 * best-effort JSON salvage parser, so a truncated message can yield tool calls
 * whose arguments parse and validate but are silently incomplete. None of them
 * are safe to execute; report each as an error so the model can re-issue them.
 */
async function failToolCallsFromTruncatedMessage(
	toolCalls: AgentToolCall[],
	emit: AgentEventSink,
): Promise<ExecutedToolCallBatch> {
```

终止也受工具结果影响：`shouldTerminateToolBatch` 要求整批每一个 result 都 `terminate===true` 才早停；`beforeToolCall` 的 block 也能带 terminate 参与这个"全体一致"规则。工具集本身是可声明变更的一等公民——`context.tools` 是"运行时能执行什么"，transcript 的 system message 才是"模型能调用什么"，`declareToolChanges` 每次请求前把差异写成 `toolsAdded`/`toolsRemoved` 注入，重放始终还原为 `context.tools`。详见 [Tools](/docs/CS/AI/LLM/Agent/Product/Pi/Tools.md) 与 [Events](/docs/CS/AI/LLM/Agent/Product/Pi/Events.md)。

## Queues: Steering / Follow-up / Abort

`Agent` 维护两个独立 `PendingMessageQueue`（steering / follow-up），各有 `mode: "all" | "one-at-a-time"`，默认都是 `one-at-a-time`：

```ts
	peek(): AgentMessage[] {
		if (this.mode === "all") return this.messages.slice();
		const first = this.messages[0];
		return first ? [first] : [];
	}

	drain(): AgentMessage[] {
		const drained = this.peek();
		this.messages = this.messages.slice(drained.length);
		return drained;
	}
```

三种注入语义构成 Pi 的人机协作节奏：

| 机制 | 入队 | 注入时机 | 中断后 |
| :--- | :--- | :--- | :--- |
| steering | `Agent.steer()` / Enter | 当前工具调用跑完后、下一次 LLM 请求前；多个 drain point | 消息留在队列 |
| follow-up | `Agent.followUp()` / Alt+Enter | 仅当 agent 本来要停（无工具调用且无 steering） | 消息留在队列 |
| abort | `Agent.abort()` | 立即 `abortController.abort()`，`stopReason==="aborted"` 硬退出 | 队列不消耗 |

优先级 steering > follow-up。abort 是硬退出：`runLoop` 见 `error`/`aborted` 就 `finishTurn → turn_end → agent_end → return`，不再 poll 任何队列，响应期间新入队的消息**都保留在队列里**留给下次 `continue()`。交互层触发键见 [Interaction](/docs/CS/AI/LLM/Agent/Product/Pi/Interaction.md)。

## No Turn Limit

这是最容易与别的 agent 混淆的一点：`runLoop` 通篇没有任何 `maxTurns` / `maxIterations` / `maxRounds` 计数器。退出只有四条路径——`stopReason==="error"/"aborted"`、`finishTurn` 返回 `action:"end"`、整批工具 `terminate` 且无队列、内外层队列都空。理论上一个会自我追加 follow-up 的扩展能让循环无限跑，安全阀要自己写。另两个"提前结束但非轮数上限"的机制是 `finishTurn` 的 `end` 决策与工具结果的全票 terminate。

## Links

- [Pi 枢纽](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md)
- [Agent Loop 理论](/docs/CS/AI/LLM/Agent/Theory/Agent.md)
- [Tools：工具系统](/docs/CS/AI/LLM/Agent/Product/Pi/Tools.md)
- [Context：上下文与压缩](/docs/CS/AI/LLM/Agent/Product/Pi/Context.md)
- [Session：会话树](/docs/CS/AI/LLM/Agent/Product/Pi/Session.md)
- [Events：扩展事件 / 钩子总表](/docs/CS/AI/LLM/Agent/Product/Pi/Events.md)

## References

- [pi/packages/agent/src/agent-loop.ts](https://github.com/earendil-works/pi/blob/v1.5.2/packages/agent/src/agent-loop.ts) — `runLoop` 双层循环、工具批次、队列语义
- [pi/packages/agent/src/agent.ts](https://github.com/earendil-works/pi/blob/v1.5.2/packages/agent/src/agent.ts) — `Agent`、`PendingMessageQueue`、`steer/followUp/abort`
- [pi/packages/agent/src/types.ts](https://github.com/earendil-works/pi/blob/v1.5.2/packages/agent/src/types.ts) — `AgentEvent`、`ToolExecutionMode`、`QueueMode`
- [pi/packages/coding-agent/src/core/agent-session.ts](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/src/core/agent-session.ts) — 外层 `_handlePostAgentRun` 裁决与结算
- [Pi 官方文档：How Pi Works](https://pi.dev/docs/latest/coding-agent/how-pi-works) — 官方机制概览（辅助，结论以源码为准）
