## Introduction

Pi 的扩展用 `pi.on(event, handler)` 订阅 agent 生命周期事件，`on()` 返回取消订阅的函数。**真实事件名是 `tool_call` / `tool_result`**：`beforeToolCall` / `afterToolCall` 不是 `ExtensionAPI.on()` 的事件，而是 `packages/agent` 里 `AgentLoopConfig` 的底层 hook——`AgentSession` 把它们接到 `_beforeToolCall` / `_afterToolCall`，再分别转成 `tool_call` / `tool_result` 扩展事件。旧笔记说「`beforeToolCall`/`afterToolCall` 已不存在」方向对但归属说反了：它们一直存在，只是层级不同、不在扩展事件表里。

这些事件对应 [AgentLoop](/docs/CS/AI/LLM/Agent/Product/Pi/AgentLoop.md) 两层的各钩子点（turn 边界、工具执行、结算）。本文是 v1.5.2（2026-11-10 发布，commit `b4afdddf`）中 `packages/coding-agent/src/core/extensions/types.ts` 里 `ExtensionEvent` 联合类型与 `ExtensionAPI.on()` 全部重载的**权威总表**；纠正了散落各页的旧事件名。handler 的通用签名为 `(event, ctx) => R | void`；不同事件对返回值的处理分六种组合模式（见下）。所有事件的精确 payload 字段都在 `types.ts`，下表只列关键字段与行为。

```sequence
Title: 单次 turn 的事件流（生产路径）

participant R as runLoop
participant C as context/context_with_system
participant P as before_provider_*
participant T as tool_call/tool_result
participant E as tool_execution_*
participant B as turn_end
participant S as agent_before_settle
participant D as agent_settled

R->>C: turn_start
R->>C: context (过滤消息, 链式)
R->>C: context_with_system (含system, 链式)
R->>P: before_provider_request (替换payload, 链式)
R->>P: before_provider_headers (改headers, 原地)
P->>P: provider_stream_event (只读, 通知)
P->>P: after_provider_response (通知)
R->>T: message_start/update/end
loop 每个 toolCall
  R->>T: tool_call (Gate: 改input/block)
  R->>E: tool_execution_start/_update/_end (通知)
  R->>T: tool_result (脱敏/替换, 链式)
end
R->>B: turn_end (BoundaryResult: 可提议compaction/context_edit, continue)
B->>S: agent_before_settle (可追加entries)
S->>D: agent_settled (通知)
```

## Event Type and Subscription

`ExtensionEvent` 是一个联合类型，列出所有**可订阅**的事件名（不含 hook）。下面按原文顺序分两段贴出同一联合类型（过长拆块，不拼接）：

packages/coding-agent/src/core/extensions/types.ts：

```typescript
export type ExtensionEvent =
	| ProjectTrustEvent
	| ResourcesDiscoverEvent
	| McpServersChangeEvent
	| SessionEvent
	| ContextEvent
	| ContextWithSystemEvent
	| CacheWarmingDecisionEvent
	| BeforeProviderRequestEvent
	| BeforeProviderHeadersEvent
	| AfterProviderResponseEvent
	| ProviderStreamEvent
	| BeforeAgentStartEvent
	| AgentStartEvent
	| AgentEndEvent
	| AgentBeforeSettleEvent
	| AgentSettledEvent
	| UIPromptStartEvent
```

```typescript
	| UIPromptEndEvent
	| TurnStartEvent
	| TurnEndEvent
	| MessageStartEvent
	| MessageUpdateEvent
	| MessageEndEvent
	| ToolExecutionStartEvent
	| ToolExecutionUpdateEvent
	| ToolExecutionEndEvent
	| ModelSelectEvent
	| ThinkingLevelSelectEvent
	| UserBashEvent
	| InputEvent
	| ToolCallEvent
	| ToolResultEvent;
```

顶层成员三十余个，其中 `SessionEvent` 自身再展开十余个会话事件（见 B 表）。`ExtensionAPI.on()` 用逐事件重载把**事件名绑定到精确的 handler 类型与结果类型**——这是「同一 `on()` 调用、不同 payload / 返回值」能获得完整类型检查的原因：

```typescript
	on(event: "project_trust", handler: ProjectTrustHandler): () => void;
	on(
		event: "resources_discover",
		handler: ExtensionHandler<ResourcesDiscoverEvent, ResourcesDiscoverResult>,
	): () => void;
	on(event: "session_start", handler: ExtensionHandler<SessionStartEvent>): () => void;
	on(event: "session_info_changed", handler: ExtensionHandler<SessionInfoChangedEvent>): () => void;
	on(
		event: "session_before_switch",
		handler: ExtensionHandler<SessionBeforeSwitchEvent, SessionBeforeSwitchResult>,
	): () => void;
	on(
		event: "session_before_fork",
		handler: ExtensionHandler<SessionBeforeForkEvent, SessionBeforeForkResult>,
	): () => void;
	on(
		event: "session_before_compact",
		handler: ExtensionHandler<SessionBeforeCompactEvent, SessionBeforeCompactResult>,
	): () => void;
	on(event: "session_compact", handler: ExtensionHandler<SessionCompactEvent>): () => void;
	on(event: "session_compact_failed", handler: ExtensionHandler<SessionCompactFailedEvent>): () => void;
	on(event: "session_shutdown", handler: ExtensionHandler<SessionShutdownEvent>): () => void;
	on(event: "mcp_servers_change", handler: ExtensionHandler<McpServersChangeEvent>): () => void;
```

```typescript
	on(
		event: "before_agent_start",
		handler: ExtensionHandler<BeforeAgentStartEvent, BeforeAgentStartEventResult>,
	): () => void;
	on(event: "agent_start", handler: ExtensionHandler<AgentStartEvent>): () => void;
	on(event: "agent_end", handler: ExtensionHandler<AgentEndEvent>): () => void;
	on(
		event: "agent_before_settle",
		handler: ExtensionHandler<AgentBeforeSettleEvent, AgentBeforeSettleEventResult>,
	): () => void;
	on(event: "agent_settled", handler: ExtensionHandler<AgentSettledEvent>): () => void;
	on(event: "ui_prompt_start", handler: ExtensionHandler<UIPromptStartEvent>): () => void;
	on(event: "ui_prompt_end", handler: ExtensionHandler<UIPromptEndEvent>): () => void;
	on(event: "turn_start", handler: ExtensionHandler<TurnStartEvent>): () => void;
	on(event: "turn_end", handler: ExtensionHandler<TurnEndEvent, TurnEndEventResult>): () => void;
	on(event: "message_start", handler: ExtensionHandler<MessageStartEvent>): () => void;
	on(event: "message_update", handler: ExtensionHandler<MessageUpdateEvent>): () => void;
	on(event: "message_end", handler: ExtensionHandler<MessageEndEvent, MessageEndEventResult>): () => void;
	on(event: "tool_execution_start", handler: ExtensionHandler<ToolExecutionStartEvent>): () => void;
	on(event: "tool_execution_update", handler: ExtensionHandler<ToolExecutionUpdateEvent>): () => void;
	on(event: "tool_execution_end", handler: ExtensionHandler<ToolExecutionEndEvent>): () => void;
	on(event: "model_select", handler: ExtensionHandler<ModelSelectEvent>): () => void;
	on(event: "thinking_level_select", handler: ExtensionHandler<ThinkingLevelSelectEvent>): () => void;
	on(event: "tool_call", handler: ExtensionHandler<ToolCallEvent, ToolCallEventResult>): () => void;
	on(event: "tool_result", handler: ExtensionHandler<ToolResultEvent, ToolResultEventResult>): () => void;
	on(event: "user_bash", handler: ExtensionHandler<UserBashEvent, UserBashEventResult>): () => void;
	on(event: "input", handler: ExtensionHandler<InputEvent, InputEventResult>): () => void;
```

`api.on()` 本身只是把 handler 塞进 `extension.handlers` 这个 `Map`，真正的分发由 `ExtensionRunner` 读取该 Map 完成：

packages/coding-agent/src/core/extensions/loader.ts：

```typescript
	const api = {
		// Registration methods - write to extension
		on(event: string, handler: HandlerFn): () => void {
			assertActive();
			const registeredHandler: HandlerFn = (...args) => handler(...args);
			const list = extension.handlers.get(event) ?? [];
			list.push(registeredHandler);
			extension.handlers.set(event, list);

			return () => {
				const handlers = extension.handlers.get(event);
				if (!handlers) return;
				const handlerIndex = handlers.indexOf(registeredHandler);
				if (handlerIndex === -1) return;
				handlers.splice(handlerIndex, 1);
				if (handlers.length === 0) extension.handlers.delete(event);
			};
		},
```

不要把它和 `event-bus.ts` 混为一谈。后者是一个**独立、基于 `EventEmitter` 的内部总线**，`safeHandler` 用 `try/catch` 包住 handler，出错只 `console.error`；它并不是 `ExtensionAPI.on()` 的实现。

packages/coding-agent/src/core/event-bus.ts：

```typescript
export function createEventBus(): EventBusController {
	const emitter = new EventEmitter();
	return {
		emit: (channel, data) => {
			emitter.emit(channel, data);
		},
		on: (channel, handler) => {
			const safeHandler = async (data: unknown) => {
				try {
					await handler(data);
				} catch (err) {
					console.error(`Event handler error (${channel}):`, err);
				}
			};
			emitter.on(channel, safeHandler);
			return () => emitter.off(channel, safeHandler);
		},
		clear: () => {
			emitter.removeAllListeners();
		},
	};
}
```

`beforeToolCall` / `afterToolCall` 到扩展事件的桥接也值得看一眼：`_beforeToolCall` 把 agent hook 的 `args` 原样作为 `tool_call.input` 交给 `emitToolCall`，`_afterToolCall` 则把结果交给 `emitToolResult`。

packages/coding-agent/src/core/agent-session.ts：

```typescript
	private _installAgentToolHooks(): void {
		this.agent.beforeToolCall = (context) => this._beforeToolCall(context);
		this.agent.afterToolCall = (context) => this._afterToolCall(context);
	}

	/** `tool_call` handlers. `parentToolCallId` is set for calls another tool made. */
	private async _beforeToolCall(
		{ toolCall, args }: BeforeToolCallContext,
		parentToolCallId?: string,
	): Promise<BeforeToolCallResult | undefined> {
		const runner = this._extensionRunner;
		if (!runner.hasHandlers("tool_call")) {
			return undefined;
		}

		try {
			return await runner.emitToolCall({
				type: "tool_call",
				toolName: toolCall.name,
				toolCallId: toolCall.id,
				...(parentToolCallId ? { parentToolCallId } : {}),
				input: args as Record<string, unknown>,
			});
		} catch (err) {
			if (err instanceof Error) {
				throw err;
			}
			throw new Error(`Extension failed, blocking execution: ${String(err)}`);
		}
	}
```

## Six Handler Composition Patterns

| 模式 | 语义 | 涉及事件 |
| --- | --- | --- |
| **通知型** | 返回值被忽略，纯观察 | `agent_start` / `agent_end` / `after_provider_response` / `provider_stream_event` / `message_start` / `message_update` / `tool_execution_start` / `tool_execution_update` / `tool_execution_end` / `agent_settled` / `session_start` / `session_compact` / `session_compact_failed` / `session_tree` / `session_shutdown` / `resources_discover` / `mcp_servers_change` / `ui_prompt_start` / `ui_prompt_end` / `model_select` / `thinking_level_select` / `turn_start` / `session_info_changed` |
| **原地修改型** | 改 `event` 上的可变字段，后续 handler 见改动 | `before_provider_headers`（改 `headers`）、`before_agent_start`（改 `systemPromptOptions`）、`tool_call`（改 `input`，不重新校验） |
| **链式转换型** | 返回值传给下一个 handler，Pi 随后恢复自身状态 | `input`（`transform`）、`context` / `context_with_system`（两阶段）、`message_end`、`tool_result`、`before_provider_request` |
| **Gate 短路型** | 停止该操作的正常 fallback 路径 | `input`（返回 `handled`）、`tool_call`（返回 `{ block }`）、`user_bash`（返回 `operations`/`result`）、`project_trust`（第一个 yes/no 胜出）、`session_before_switch`/`session_before_fork`/`session_before_tree`/`session_before_compact`（返回 `cancel`） |
| **行为边界型** | 看到已提议 entries 与延续决策，可追加 `custom`/`context_edit`/`compaction` 或 `continue`；`turn_end` 与 `agent_before_settle` 共享 `emitBoundary` | `turn_end`、`agent_before_settle` |
| **最后覆盖（last override）型** | 最后一个返回有效 action / prompt 的处理器胜出 | `before_agent_start`（`systemPrompt`）、`cache_warming_decision`（`{ action }`） |

**Gate 短路型**在通用 `emit()` 里体现为 `session_before_*` 一返回 `cancel` 就立即 `return`，后面的 handler 不再跑；每个 handler 都被 `try/catch` 包住，异常被转成 `emitError` 而不是中断整条链。

packages/coding-agent/src/core/extensions/runner.ts：

```typescript
	async emit<TEvent extends RunnerEmitEvent>(event: TEvent): Promise<RunnerEmitResult<TEvent>> {
		const ctx = this.createContext();
		let result: SessionBeforeEventResult | undefined;

		for (const { ext, handlers } of snapshotEventHandlers(this.extensions, event.type)) {
			for (const handler of handlers) {
				try {
					const handlerResult = await handler(event, ctx);

					if (this.isSessionBeforeEvent(event) && handlerResult) {
						result = handlerResult as SessionBeforeEventResult;
						if (result.cancel) {
							return result as RunnerEmitResult<TEvent>;
						}
					}
				} catch (err) {
					const message = err instanceof Error ? err.message : String(err);
					const stack = err instanceof Error ? err.stack : undefined;
					this.emitError({
						extensionPath: ext.path,
						event: event.type,
						error: message,
						stack,
					});
				}
			}
		}

		return result as RunnerEmitResult<TEvent>;
	}
```

`project_trust` 的 Gate 规则更特殊：`undecided` 继续往下走，**第一个返回 yes/no 的 handler 胜出**并压掉内置信任提示。

packages/coding-agent/src/core/extensions/runner.ts：

```typescript
export async function emitProjectTrustEvent(
	extensionsResult: LoadExtensionsResult,
	event: ProjectTrustEvent,
	ctx: ProjectTrustContext,
): Promise<{ result?: ProjectTrustEventResult; errors: ExtensionError[] }> {
	const errors: ExtensionError[] = [];
	for (const { ext, handlers } of snapshotEventHandlers(extensionsResult.extensions, "project_trust")) {
		// A single extension may register multiple handlers for the same event.
		// The first project_trust handler that returns yes/no wins; undecided falls through.
		for (const handler of handlers) {
			try {
				const handlerResult = (await handler(event, ctx)) as ProjectTrustEventResult;
				if (handlerResult.trusted === "undecided") {
					continue;
				}
				return { result: handlerResult, errors };
			} catch (error) {
				errors.push({
					extensionPath: ext.path,
					event: event.type,
					error: error instanceof Error ? error.message : String(error),
					stack: error instanceof Error ? error.stack : undefined,
				});
			}
		}
	}
	return { errors };
}
```

**原地修改型**的代表是 `tool_call`：`emitToolCall` 把**同一个 `event` 对象**依次传给所有 handler，前一个人改的 `input` 后一个人直接看见；返回 `{ block }` 立刻短路。需要特别记住的是——它是**唯一不做 `try/catch` 的 emit 方法**，handler 抛出的异常会原样上抛到 `_beforeToolCall`，从而阻断这次工具调用（这就是权限控制的 fail-safe）。

packages/coding-agent/src/core/extensions/runner.ts：

```typescript
	async emitToolCall(event: ToolCallEvent): Promise<ToolCallEventResult | undefined> {
		const ctx = this.createContext();
		let result: ToolCallEventResult | undefined;

		for (const { handlers } of snapshotEventHandlers(this.extensions, "tool_call")) {
			for (const handler of handlers) {
				const handlerResult = await handler(event, ctx);

				if (handlerResult) {
					result = handlerResult as ToolCallEventResult;
					if (result.block) {
						return result;
					}
				}
			}
		}

		return result;
	}
```

对比 `tool_result` 的**链式转换型**：它每次都基于 `{ ...event }` 的副本调用 handler，把返回值里的 `content` / `details` / `structuredContent` / `isError` / `usage` 合并回 `currentEvent`，后面 handler 看到的是上一次改过的值；每个 handler 仍有 `try/catch`，出错只记 `emitError`。

packages/coding-agent/src/core/extensions/runner.ts：

```typescript
	async emitToolResult(event: ToolResultEvent): Promise<ToolResultEventResult | undefined> {
		const ctx = this.createContext();
		const currentEvent: ToolResultEvent = { ...event };
		let modified = false;

		for (const { ext, handlers } of snapshotEventHandlers(this.extensions, "tool_result")) {
			for (const handler of handlers) {
				try {
					const handlerResult = (await handler(currentEvent, ctx)) as ToolResultEventResult | undefined;
					if (!handlerResult) continue;

					if (handlerResult.content !== undefined) {
						currentEvent.content = handlerResult.content;
						// Structured content that is not replaced along with the content may no longer match it.
						if (handlerResult.structuredContent === undefined) delete currentEvent.structuredContent;
						modified = true;
					}
```

```typescript
		if (!modified) {
			return undefined;
		}

		return {
			content: currentEvent.content,
			details: currentEvent.details,
			structuredContent: currentEvent.structuredContent,
			isError: currentEvent.isError,
			usage: currentEvent.usage,
		};
	}
```

`context` / `context_with_system` 是**两阶段链式转换**：先让所有 `context` handler 只看非 system 消息，并在每个 handler 后把 system 消息恢复回去；再让所有 `context_with_system` handler 看完整转录——后者若删掉了 index 0 的 system 消息会收到 `emitError`（因为 provider 从这里读 prompt 与初始工具声明）。

packages/coding-agent/src/core/extensions/runner.ts：

```typescript
	async emitContext(messages: AgentMessage[]): Promise<AgentMessage[]> {
		const ctx = this.createContext();
		let currentMessages = structuredClone(messages);

		for (const { ext, handlers } of snapshotEventHandlers(this.extensions, "context")) {
			for (const handler of handlers) {
				try {
					const visibleMessages = currentMessages.filter((message) => message.role !== "system");
					const visibleSnapshot = visibleMessages.slice();
					const event: ContextEvent = { type: "context", messages: visibleMessages };
					const handlerResult = (await handler(event, ctx)) as ContextEventResult | undefined;

					// Handlers may return a new list or edit event.messages in place.
					const returned =
						handlerResult?.messages ??
						(sameMessages(visibleMessages, visibleSnapshot) ? undefined : visibleMessages);
					if (!returned) continue;
					currentMessages = restoreSystemMessages(currentMessages, visibleSnapshot, returned);
				} catch (err) {
```

```typescript
		for (const { ext, handlers } of snapshotEventHandlers(this.extensions, "context_with_system")) {
			for (const handler of handlers) {
				try {
					const hadLeadingSystemMessage = currentMessages[0]?.role === "system";
					const event: ContextWithSystemEvent = { type: "context_with_system", messages: currentMessages };
					const handlerResult = (await handler(event, ctx)) as ContextEventResult | undefined;
					currentMessages = handlerResult?.messages ?? currentMessages;
					// Providers read the prompt and initial tools from the leading system message.
					// Losing it is never intended; report it but honor the handler's output.
					if (hadLeadingSystemMessage && currentMessages[0]?.role !== "system") {
```

`input` 同时展示链式转换与 Gate：`transform` 把新 text/images 交给下一个 handler，`handled` 立刻返回不再走本地路径；没有改动时返回 `continue`。

packages/coding-agent/src/core/extensions/runner.ts：

```typescript
					const result = (await handler(event, ctx)) as InputEventResult | undefined;
					if (result?.action === "handled") return result;
					if (result?.action === "transform") {
						currentText = result.text;
						currentImages = result.images ?? currentImages;
					}
				} catch (err) {
					this.emitError({
						extensionPath: ext.path,
						event: "input",
						error: err instanceof Error ? err.message : String(err),
						stack: err instanceof Error ? err.stack : undefined,
					});
				}
			}
		}
		return currentText !== text || currentImages !== images
			? { action: "transform", text: currentText, images: currentImages }
			: { action: "continue" };
	}
```

**行为边界型**由 `turn_end` / `agent_before_settle` 共享同一个 `emitBoundary(baseEvent, buildContext)`：每个 handler 都拿到「目前为止别人提议的 `entries` 与 `continue`」，改完立刻用 `buildContext(entries)` 重建预览；一旦 entries 非法，`valid` 变 false，最终**整体回滚**成空 entries、`continue: false`。

packages/coding-agent/src/core/extensions/runner.ts：

```typescript
		const ctx = this.createContext();
		let entries: SessionBoundaryDraft[] = [];
		let shouldContinue = false;
		let context = await buildContext(entries);
		let valid = true;

		for (const { ext, handlers } of snapshotEventHandlers(this.extensions, baseEvent.type)) {
			for (const handler of handlers) {
				const event = {
					...baseEvent,
					entries,
					continue: shouldContinue,
					context,
				} as TurnEndEvent | AgentBeforeSettleEvent;
				try {
					const handlerResult = (await handler(event, ctx)) as BoundaryResult | undefined;
					if (handlerResult?.entries !== undefined) entries = handlerResult.entries;
					if (handlerResult?.continue !== undefined) shouldContinue = handlerResult.continue;
				} catch (err) {
```

```typescript
				try {
					context = await buildContext(entries);
					valid = true;
				} catch (err) {
					valid = false;
					this.emitError({
						extensionPath: ext.path,
						event: baseEvent.type,
						error: `Invalid boundary entries: ${err instanceof Error ? err.message : String(err)}`,
						stack: err instanceof Error ? err.stack : undefined,
					});
				}
			}
		}

		return valid
			? { entries, continue: shouldContinue, context, valid: true }
			: { entries: [], continue: false, context, valid: false };
	}
```

**最后覆盖型**在 `before_agent_start` 上体现为：`systemPromptOptions` 是原地修改（后续 handler 的 `event.systemPrompt` getter 会重新渲染当前 prompt），而返回 `systemPrompt` 会写入 `forceSystemPrompt`，后写覆盖先写。`cache_warming_decision` 同理，最后一个返回 action 的 handler 胜出。

packages/coding-agent/src/core/extensions/runner.ts：

```typescript
					const event: BeforeAgentStartEvent = {
						...trigger,
						type: "before_agent_start",
						get systemPrompt() {
							return renderCurrentSystemPrompt();
						},
						systemPromptOptions: currentOptions,
					};
					const handlerResult = await handler(event, ctx);

					if (handlerResult) {
						const result = handlerResult as BeforeAgentStartEventResult;
						if (result.message) messages.push(result.message);
						if (result.systemPrompt !== undefined) {
							currentOptions.forceSystemPrompt = result.systemPrompt;
						}
					}
```

> **fail-safe 小结**：`tool_call` 的 `emitToolCall` 不做 `try/catch`，异常直接上抛并阻断调用（唯一例外）；`user_bash` 的 `emitUserBash` 在 `catch` 里记 `emitError` 后 `throw err`，同样阻断命令且不 fallback；其余大多数 emit 方法只记错误、让事件链继续。

## A. Startup and Resources

| 事件 | 触发 | 关键 payload | 行为 / 返回 |
| --- | --- | --- | --- |
| `project_trust` | 受信项目资源加载前（进新目录可能重跑） | `cwd` | 仅**个人 / 显式 CLI 扩展**可参与；返回 `{ trusted: "yes"\|"no"\|"undecided", remember? }` 做信任决策，第一个 yes/no 胜出 |
| `resources_discover` | `session_start` 之后 | `cwd`、`reason: startup\|reload` | 返回 `{ skillPaths?, promptPaths?, themePaths? }` 提供额外资源路径 |
| `mcp_servers_change` | 扩展注册/注销 MCP 服务器后 | `servers: RegisteredMcpServer[]` | 供接管已注册服务器连接的 MCP 扩展使用 |

## B. Session Lifecycle

| 事件 | 触发 | 关键 payload | 行为 / 返回 |
| --- | --- | --- | --- |
| `session_start` | 启动 / 加载 / 重载 / new / resume / fork | `reason`、`previousSessionFile?` | 初始化会话级资源；可从此读 `pi.getMcpServers()`（通知） |
| `session_info_changed` | 会话元信息变化 | `name` | 通知 |
| `session_before_switch` | `/new` 或 `/resume` 触发 | `reason`、`targetSessionFile?` | **Gate**：返回 `{ cancel? }` 取消 |
| `session_before_fork` | `/fork` 或 `/clone` 触发 | `entryId`、`position` | **Gate**：返回 `{ cancel?, skipConversationRestore? }` |
| `session_before_compact` | 压缩前 | `preparation`、`branchEntries`、`reason: manual\|threshold\|overflow`、`willRetry`、`signal` | **Gate + 自定义**：返回 `{ cancel?, compaction? }` 可直接提供 `CompactionResult` 替换默认摘要 |
| `session_compact` | 压缩成功 | `compactionEntry`、`fromExtension`、`reason`、`willRetry` | 通知 |
| `session_compact_failed` | 压缩失败 / 中止 | `reason`、`errorMessage?`、`aborted`、`willRetry`、`fromExtension` | 通知 |
| `session_shutdown` | 退出 / 重载 / 替换 / 切换（汇聚） | `reason`、`targetSessionFile?` | 释放资源，**需幂等** |
| `session_before_tree` | `/tree` 分支导航前 | `preparation: TreePreparation`、`signal` | **Gate + 自定义摘要**：返回 `{ cancel?, summary?, customInstructions?, replaceInstructions?, label? }` |
| `session_tree` | 分支导航后 | `newLeafId`、`oldLeafId`、`summaryEntry?` | 通知 |

> 压缩链路：压缩是**一等事件**（`session_before_compact` / `session_compact` / `session_compact_failed`），不是隐藏钩子；`turn_end` 的 `BoundaryResult` 还可主动提议 `compaction` entry 触发压缩。

## C. Agent Runtime

| 事件 | 触发 | 关键 payload | 行为 / 返回 |
| --- | --- | --- | --- |
| `before_agent_start` | 运行前（用户消息或空闲 custom 触发） | `systemPrompt`、`systemPromptOptions`（可变）、`messageType: user\|custom`、`prompt`/`message`、`images?` | **原地修改 + 最后覆盖**：改 `systemPromptOptions`；返回 `message` 追加运行；返回 `systemPrompt` 替换整段 prompt |
| `agent_start` | 一次底层 agent 运行开始 | — | 通知 |
| `agent_end` | 一次底层运行结束（重试/恢复可能重启，**非**空闲终态） | `messages` | 通知 |
| `agent_before_settle` | 自动处理停止前、最终化前 | `entries`、`continue`、`context`、`outcome` | **行为边界**：可追加 entries 或 `continue: true` 做最后一次延续 |
| `agent_settled` | 所有自动延续结束后（无重试/压缩/排队延续） | `aborted` | 通知，仅做通知类工作 |

## D. Turns and Transcript Conversion

| 事件 | 触发 | 关键 payload | 行为 / 返回 |
| --- | --- | --- | --- |
| `turn_start` | 每个模型请求轮次开始 | `turnIndex`、`timestamp` | 通知 |
| `turn_end` | 一次模型响应及其工具调用后 | `message`、`toolResults`、`messageEntryId`、`toolResultEntryIds`、`entries`、`continue`、`context` | **行为边界**：可链式提议 `custom`/`context_edit`/`compaction` entries，返回 `continue: true` 触发下一请求 |
| `context` | 每次提供方请求前，过滤会话消息（**不含** prompt/工具系统消息） | `messages: AgentMessage[]` | **链式转换（阶段一）**：返回值传给下一处理器；Pi 之后恢复 prompt/工具状态 |
| `context_with_system` | `context` 全部跑完后，含系统消息的完整转录 | `messages` | **链式转换（阶段二）**：handler 拥有 prompt 与工具声明（需保留 index 0 系统消息） |

## E. Provider Requests

| 事件 | 触发 | 关键 payload | 行为 / 返回 |
| --- | --- | --- | --- |
| `before_provider_request` | 请求体序列化前 | `payload` | **链式转换**：返回值作为新 payload 传给下一处理器 |
| `before_provider_headers` | 请求头发送前 | `headers` | **原地修改**：改 `headers`（返回忽略；`null` 删除该头） |
| `after_provider_response` | 响应后、流消费前 | `status`、`headers` | 通知，观察元数据 |
| `provider_stream_event` | 每个解析后的提供方流事件（Pi 规范化前） | `provider`、`api`、`model`、`data` | **通知 + 只读**：不持久化；慢处理器会阻塞流消费 |

## F. Message Lifecycle

| 事件 | 触发 | 关键 payload | 行为 / 返回 |
| --- | --- | --- | --- |
| `message_start` | 消息（user/assistant/toolResult）开始 | `message` | 通知 |
| `message_update` | assistant 流式 token 级更新 | `message`、`assistantMessageEvent` | 通知 |
| `message_end` | 消息终结 | `message` | **链式转换**：返回 `{ message }` 替换最终消息，**必须保留原角色** |

## G. Tool Execution

| 事件 | 触发 | 关键 payload | 行为 / 返回 |
| --- | --- | --- | --- |
| `tool_execution_start` | 工具调用执行开始 | `toolCallId`、`toolName`、`args`、`parentToolCallId?` | 通知 |
| `tool_execution_update` | 执行期间部分结果 | `toolCallId`、`partialResult`、`parentToolCallId?` | 通知 |
| `tool_execution_end` | 执行结束 | `toolCallId`、`result`、`isError`、`durationMs?`、`parentToolCallId?` | 通知 |
| `tool_call` | 工具调用授权 / 改写时（由 `beforeToolCall` hook 桥接而来） | `toolCallId`、`toolName`、`input`（可变）、`parentToolCallId?` | **Gate + 原地修改**：改 `input` 修补参数（**不重新校验**），后续 handler 看见改动；返回 `{ block?, reason?, terminate? }` 阻止；**抛错上抛并阻断**（唯一无 `try/catch` 的 emit） |
| `tool_result` | 工具结果返回（由 `afterToolCall` hook 桥接而来） | `toolCallId`、`input`、`content`、`structuredContent?`、`isError`、`usage?`、`parentToolCallId?` | **链式转换 + 组合**：各 handler 见先前改动；可脱敏/替换 `content`/`structuredContent`/`details`/`isError`/`usage` |

> **嵌套调用贯穿**：工具内部经 `ctx.executeTool()` 再调子工具时，子调用 id 形如 `<parent id>/<n>`，其 `tool_call`/`tool_result`/`tool_execution_*` 同样携带 `parentToolCallId`，**权限检查不漏底**；嵌套调用不进转录，只在调用方结果的 `nestedCalls` 里留有限记录（参数 >8KiB、结果 >32KiB 省略，至多 256 条）。

## H. Models and Thinking Levels

| 事件 | 触发 | 关键 payload | 行为 / 返回 |
| --- | --- | --- | --- |
| `model_select` | 新模型被选中 | `model`、`previousModel`、`source: set\|cycle\|restore` | 通知 |
| `thinking_level_select` | 思考级别切换 | `level`、`previousLevel` | 通知 |

## I. Input and Shell

| 事件 | 触发 | 关键 payload | 行为 / 返回 |
| --- | --- | --- | --- |
| `input` | 用户输入进入、agent 处理前 | `text`、`images?`、`source: interactive\|rpc\|extension`、`streamingBehavior?` | **链式转换 + Gate**：返回 `{ action: "continue" }` / `{ action: "transform", text, images? }` / `{ action: "handled" }` |
| `user_bash` | 用户经 `!`/`!!` 前缀执行 bash | `command`、`excludeFromContext`、`cwd` | **Gate**：返回 `undefined` 透传本地执行；返回 `{ operations }` 或 `{ result }` 接管执行；抛错阻断命令（记 `emitError` 后 rethrow，不 fallback） |

## J. UI Prompts and Caching

| 事件 | 触发 | 关键 payload | 行为 / 返回 |
| --- | --- | --- | --- |
| `ui_prompt_start` / `ui_prompt_end` | 阻塞式扩展 UI 提示起 / 止 | `kind: select\|confirm\|input\|editor\|custom`、`title?` | 通知 |
| `cache_warming_decision` | 空闲提示缓存刷新决策 | `CacheWarmingDecisionEvent` | **最后覆盖**：最后返回 `{ action: "warm" }` 或 `{ action: "stop" }` 的处理器生效 |

## Lifecycle Order

`session_start` → `resources_discover` → （`project_trust` 视情况）→ `before_agent_start` → `agent_start` → `turn_start` → `context`/`context_with_system` → `before_provider_*` → `provider_stream_event` → `after_provider_response` → `message_*` → `tool_execution_*`/`tool_call`/`tool_result` → `turn_end`（可续跑）→ … → `agent_before_settle` → `agent_settled`；退出时 `session_shutdown`（需幂等）。

## Links

- [Extensions：扩展体系](/docs/CS/AI/LLM/Agent/Product/Pi/Extensions.md)
- [Tools：工具系统](/docs/CS/AI/LLM/Agent/Product/Pi/Tools.md)
- [Pi.md?id=architecture](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md?id=architecture)
- [Context：上下文与压缩](/docs/CS/AI/LLM/Agent/Product/Pi/Context.md)
- [Pi 枢纽](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md)

## References

- [pi/types.ts](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/src/core/extensions/types.ts) — `ExtensionEvent` 联合类型与 `ExtensionAPI.on()` 全部重载（权威事件清单）
- [pi/runner.ts](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/src/core/extensions/runner.ts) — 六种返回值处理模式的实际实现
- [pi/event-bus.ts](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/src/core/event-bus.ts) — 独立的内部 EventEmitter 总线
- [pi/agent.ts](https://github.com/earendil-works/pi/blob/v1.5.2/packages/agent/src/agent.ts) — `AgentLoopConfig` 的 `beforeToolCall` / `afterToolCall` hook
- [pi/extensions.md](https://github.com/earendil-works/pi/blob/v1.5.2/packages/coding-agent/docs/extensions.md) — 扩展作者文档
