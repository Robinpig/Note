## Introduction

cc-haha 的 **REPL（交互式命令行）** 是产品的核心交互骨架，区别于 Electron 桌面 GUI 的可视化层。无论是终端直跑、SDK 调用（`-p`）、还是桌面内部的命令通道，所有用户输入与系统生成命令都经由**同一个统一命令队列**流动。本篇深挖该队列的内部机制，以及它如何在 turns 之间 drain、如何与计划任务 / 远控子系统咬合。

进程与流协议的分层不在本篇范围内：桌面工作台的主链路是 Electron spawn `claude-sidecar server` → `src/server/index.ts` → `src/server/services/conversationService.ts` 按会话 spawn CLI，详见 [RuntimeTopology](/docs/CS/AI/LLM/Agent/Product/CcHaha/RuntimeTopology.md) 与 [StreamProtocol](/docs/CS/AI/LLM/Agent/Product/CcHaha/StreamProtocol.md)。`src/bridge/sessionRunner.ts` 属于独立的 remote code sessions 桥（调用方 `src/bridge/bridgeMain.ts`），**不是**桌面引擎子进程；旧笔记把它称作「引擎子进程的 NDJSON 通信」是错的，已在文末 `## Corrections` 据 v0.7.7 源码纠正。本篇聚焦交互骨架而非进程协议。

## Unified Command Queue

队列实现位于 `src/utils/messageQueueManager.ts`，是**模块级单例，独立于 React state**：

- **统一入口**：所有命令——用户输入、`task-notification`、orphaned permissions——都进同一个 `commandQueue` 数组。
- **React 订阅**：通过 `useSyncExternalStore`（`subscribeToCommandQueue` / `getCommandQueueSnapshot`）订阅，每次 mutation 重建 frozen snapshot。
- **非 React 读取**：源码注释以 `src/cli/print.ts` 的 streaming loop 为例，说明它可直接读 `getCommandQueue()` / `getCommandQueueLength()` 而不必走 React 渲染；在 v0.7.7 中 `getCommandQueue()` 确由 `print.ts` import 使用，`getCommandQueueLength()` 的实际调用点还包括 `src/screens/REPL.tsx`。

队列本体与订阅骨架原样摘自 `src/utils/messageQueueManager.ts`：

```ts
// ============================================================================
// Unified command queue (module-level, independent of React state)
//
// All commands — user input, task notifications, orphaned permissions — go
// through this single queue. React components subscribe via
// useSyncExternalStore (subscribeToCommandQueue / getCommandQueueSnapshot).
// Non-React code (print.ts streaming loop) reads directly via
// getCommandQueue() / getCommandQueueLength().
//
// Priority determines dequeue order: 'now' > 'next' > 'later'.
// Within the same priority, commands are processed FIFO.
// ============================================================================

const commandQueue: QueuedCommand[] = []
/** Frozen snapshot — recreated on every mutation for useSyncExternalStore. */
let snapshot: readonly QueuedCommand[] = Object.freeze([])
const queueChanged = createSignal()

function notifySubscribers(): void {
  snapshot = Object.freeze([...commandQueue])
  queueChanged.emit()
}
```

React 侧订阅原样摘自 `src/hooks/useCommandQueue.ts`：

```ts
/**
 * React hook to subscribe to the unified command queue.
 * Returns a frozen array that only changes reference on mutation.
 * Components re-render only when the queue changes.
 */
export function useCommandQueue(): readonly QueuedCommand[] {
  return useSyncExternalStore(subscribeToCommandQueue, getCommandQueueSnapshot)
}
```

供非 React 代码读取的两个函数原样摘自 `src/utils/messageQueueManager.ts`：

```ts
// ============================================================================
// Read operations (for non-React code)
// ============================================================================

/**
 * Get a mutable copy of the current queue.
 * Use for one-off reads where you need the actual commands.
 */
export function getCommandQueue(): QueuedCommand[] {
  return [...commandQueue]
}

/**
 * Get the current queue length without copying.
 */
export function getCommandQueueLength(): number {
  return commandQueue.length
}
```

### Priority: now > next > later

`PRIORITY_ORDER` 定义三档，同档 FIFO：

- `enqueue()` 默认 `next` —— 用户输入、orphaned permission。
- `enqueuePendingNotification()` 默认 `later` —— 系统通知（计划任务触发、proactive ticks、plan verification、channel messages），**注释明言「user input is never starved by system messages」**。这正是计划任务触发不打断当前 streaming 的根因。
- `dequeue(filter?)` 支持谓词过滤——between-turn drain（SDK / REPL）用它把候选限制为主线程命令（`cmd.agentId === undefined`），不重排既有 while-loop 模式。

以下三档优先级与两个入队函数原样摘自 `src/utils/messageQueueManager.ts`：

```ts
const PRIORITY_ORDER: Record<QueuePriority, number> = {
  now: 0,
  next: 1,
  later: 2,
}
```

```ts
/**
 * Add a command to the queue.
 * Used for user-initiated commands (prompt, bash, orphaned-permission).
 * Defaults priority to 'next' (processed before task notifications).
 */
export function enqueue(command: QueuedCommand): void {
  commandQueue.push({ ...command, priority: command.priority ?? 'next' })
  notifySubscribers()
  logOperation(
    'enqueue',
    typeof command.value === 'string' ? command.value : undefined,
  )
}

/**
 * Add a task notification to the queue.
 * Convenience wrapper that defaults priority to 'later' so user input
 * is never starved by system messages.
 */
export function enqueuePendingNotification(command: QueuedCommand): void {
  commandQueue.push({ ...command, priority: command.priority ?? 'later' })
  notifySubscribers()
  logOperation(
    'enqueue',
    typeof command.value === 'string' ? command.value : undefined,
  )
}
```

`dequeue(filter?)` 的实现原样摘自 `src/utils/messageQueueManager.ts`：

```ts
/**
 * Remove and return the highest-priority command, or undefined if empty.
 * Within the same priority level, commands are dequeued FIFO.
 *
 * An optional `filter` narrows the candidates: only commands for which the
 * predicate returns `true` are considered. Non-matching commands stay in the
 * queue untouched. This lets between-turn drains (SDK, REPL) restrict to
 * main-thread commands (`cmd.agentId === undefined`) without restructuring
 * the existing while-loop patterns.
 */
export function dequeue(
  filter?: (cmd: QueuedCommand) => boolean,
): QueuedCommand | undefined {
  if (commandQueue.length === 0) {
    return undefined
  }

  // Find the first command with the highest priority (respecting filter)
  let bestIdx = -1
  let bestPriority = Infinity
  for (let i = 0; i < commandQueue.length; i++) {
    const cmd = commandQueue[i]!
    if (filter && !filter(cmd)) continue
    const priority = PRIORITY_ORDER[cmd.priority ?? 'next']
    if (priority < bestPriority) {
      bestIdx = i
      bestPriority = priority
    }
  }

  if (bestIdx === -1) return undefined

  const [dequeued] = commandQueue.splice(bestIdx, 1)
  notifySubscribers()
  logOperation('dequeue')
  return dequeued
}
```

### Visibility and Editability

系统生成的命令常含 raw XML（计划任务、plan 校验、channel 消息），必须不能泄露到用户输入框：

- `isQueuedCommandEditable()` —— 仅当输入模式属于 editable（即非 `task-notification` 这类 non-editable 模式）**且** `!cmd.isMeta` 时才可编辑。
- `isQueuedCommandVisible()` —— channel 消息可见但不可编辑。
- `popAllEditable()` —— 把 editable 命令与当前输入合并供编辑，`task-notification` 类 non-editable 留队列稍后自动处理。
- `clearCommandQueue()` —— ESC 取消时丢弃排队的 notifications。

以下判定函数原样摘自 `src/utils/messageQueueManager.ts`：

```ts
const NON_EDITABLE_MODES = new Set<PromptInputMode>([
  'task-notification',
] satisfies Permutations<Exclude<PromptInputMode, EditablePromptInputMode>>)

export function isPromptInputModeEditable(
  mode: PromptInputMode,
): mode is EditablePromptInputMode {
  return !NON_EDITABLE_MODES.has(mode)
}

/**
 * Whether this queued command can be pulled into the input buffer via UP/ESC.
 * System-generated commands (proactive ticks, scheduled tasks, plan
 * verification, channel messages) contain raw XML and must not leak into
 * the user's input.
 */
export function isQueuedCommandEditable(cmd: QueuedCommand): boolean {
  return isPromptInputModeEditable(cmd.mode) && !cmd.isMeta
}

/**
 * Whether this queued command should render in the queue preview under the
 * prompt. Superset of editable — channel messages show (so the keyboard user
 * sees what arrived) but stay non-editable (raw XML).
 */
export function isQueuedCommandVisible(cmd: QueuedCommand): boolean {
  if (
    (feature('KAIROS') || feature('KAIROS_CHANNELS')) &&
    cmd.origin?.kind === 'channel'
  )
    return true
  return isQueuedCommandEditable(cmd)
}
```

`popAllEditable()` 把 non-editable 命令留回队列的两处关键片段，原样摘自同一文件：

```ts
/**
 * Pop all editable commands and combine them with current input for editing.
 * Notification modes (task-notification) are left in the queue
 * to be auto-processed later.
 * Returns object with combined text, cursor offset, and images to restore.
 * Returns undefined if no editable commands in queue.
 */
export function popAllEditable(
  currentInput: string,
  currentCursorOffset: number,
): PopAllEditableResult | undefined {
  if (commandQueue.length === 0) {
    return undefined
  }

  const { editable = [], nonEditable = [] } = objectGroupBy(
    [...commandQueue],
    cmd => (isQueuedCommandEditable(cmd) ? 'editable' : 'nonEditable'),
  )
```

```ts
  for (const command of editable) {
    logOperation(
      'popAll',
      typeof command.value === 'string' ? command.value : undefined,
    )
  }

  // Replace queue contents with only the non-editable commands
  commandQueue.length = 0
  commandQueue.push(...nonEditable)
  notifySubscribers()

  return { text: newInput, cursorOffset, images }
}
```

`clearCommandQueue()` 原样摘自同一文件：

```ts
/**
 * Clear all commands from the queue.
 * Used by ESC cancellation to discard queued notifications.
 */
export function clearCommandQueue(): void {
  if (commandQueue.length === 0) {
    return
  }
  commandQueue.length = 0
  notifySubscribers()
}
```

> 历史痕迹：文件末尾保留大量 `subscribeToPendingNotifications` / `getPendingNotificationsSnapshot` 等 `@deprecated` 别名，说明这个「统一命令队列」是从早期的「pending notifications」机制演进合并而来。以下片段原样摘自 `src/utils/messageQueueManager.ts`：

```ts
// ============================================================================
// Backward-compatible aliases (deprecated — prefer new names)
// ============================================================================

/** @deprecated Use subscribeToCommandQueue */
export const subscribeToPendingNotifications = subscribeToCommandQueue

/** @deprecated Use getCommandQueueSnapshot */
export function getPendingNotificationsSnapshot(): readonly QueuedCommand[] {
  return snapshot
}

/** @deprecated Use hasCommandsInQueue */
export const hasPendingNotifications = hasCommandsInQueue

/** @deprecated Use getCommandQueueLength */
export const getPendingNotificationsCount = getCommandQueueLength

/** @deprecated Use recheckCommandQueue */
export const recheckPendingNotifications = recheckCommandQueue

/** @deprecated Use dequeue */
export function dequeuePendingNotification(): QueuedCommand | undefined {
  return dequeue()
}

/** @deprecated Use resetCommandQueue */
export const resetPendingNotifications = resetCommandQueue

/** @deprecated Use clearCommandQueue */
export const clearPendingNotifications = clearCommandQueue
```

## Drain Timing: Between Turns

队列不在用户输入瞬间立即执行，而是在**主线程 turn 间隙**被 drain：

- `dequeue(filter)` 的 `filter` 参数让 SDK / REPL 的 between-turn drain 只取主线程命令（`agentId === undefined`），跨进程 teammate 命令留在队列由各自 runner 取走。
- **计划任务触发**即在此间隙派发：teammate/lead 的 cron 触发经 `enqueuePendingNotification({ priority: 'later', isMeta: true, workload: WORKLOAD_CRON })`（见 [ScheduledTasks](/docs/CS/AI/LLM/Agent/Product/CcHaha/ScheduledTasks.md)），`later` 优先级保证它排在用户输入之后、且不打断正在进行的 model stream。

between-turn drain 的谓词与 while 循环原样摘自 `src/cli/print.ts`：

```ts
    // Only main-thread commands (agentId===undefined) — subagent
    // notifications are drained by the subagent's mid-turn gate in query.ts.
    // Defined outside the try block so it's accessible in the post-finally
    // queue re-checks at the bottom of run().
    const isMainThread = (cmd: QueuedCommand) => cmd.agentId === undefined

    try {
      let command: QueuedCommand | undefined
      let waitingForAgents = false

      const startPushSuggestion = (cacheSafeParams: CacheSafeParams) =>
        startSdkPushSuggestion(suggestionState, {
          cacheSafeParams,
          messages: mutableMessages,
          getAppState,
          isResultHeld: () => heldBackResult !== null,
          emit: message => output.enqueue(message),
          onActivity: createPromptSuggestionActivityEmitter(structuredIO),
        })

      // Extract command processing into a named function for the do-while pattern.
      // Drains the queue, batching consecutive prompt-mode commands into one
      // ask() call so messages that queued up during a long turn coalesce
      // into a single follow-up turn instead of N separate turns.
      const drainCommandQueue = async () => {
        while ((command = dequeue(isMainThread))) {
          if (
            command.mode !== 'prompt' &&
            command.mode !== 'orphaned-permission' &&
            command.mode !== 'task-notification'
          ) {
            throw new Error(
              'only prompt commands are supported in streaming mode',
            )
          }

          // Non-prompt commands (task-notification, orphaned-permission) carry
          // side effects or orphanedPermission state, so they process singly.
          // Prompt commands greedily collect followers with matching workload.
          const batch: QueuedCommand[] = [command]
          if (command.mode === 'prompt') {
            while (canBatchWith(command, peek(isMainThread))) {
              batch.push(dequeue(isMainThread)!)
            }
```

## Integration with Subsystems

统一队列是多个子系统的「注入点」：

- **计划任务**：`useScheduledTasks.enqueueForLead(prompt)` → `enqueuePendingNotification(later, WORKLOAD_CRON)`，隐藏于队列预览 / transcript，billing 标 `cc_workload=` 低 QoS。
- **远控 / 协作**：`RemoteTrigger`（cloud CCR 触发器）、`SessionCollaboration`（loopback 桌面服务器桥）、`claude ssh`（SSH child process）都通过把命令送入同一队列来驱动本地执行（见 [RemoteAccess](/docs/CS/AI/LLM/Agent/Product/CcHaha/RemoteAccess.md)）。
- **ESC 取消**：`clearCommandQueue()` 丢弃排队中的系统通知，避免取消后仍被执行。

## REPL Bridge and Launcher

- `src/replLauncher.tsx` 负责启动 REPL 入口。
- `src/hooks/useReplBridge.tsx` 是 REPL 侧的 always-on 远控桥：把新的 user/assistant 消息写往 claude.ai/code 的 bridge session，并把远端入站消息注入 REPL 的命令队列。**它既不连接 Ink / 终端 runtime 与 UI 状态，也不桥接任何 NDJSON 引擎子进程通信**（旧笔记这两处描述均有误，见 `## Corrections`）。其职责由文件头注释原样给出，摘自 `src/hooks/useReplBridge.tsx`：

```ts
/**
 * Hook that initializes an always-on bridge connection in the background
 * and writes new user/assistant messages to the bridge session.
 *
 * Silently skips if bridge is not enabled or user is not OAuth-authenticated.
 *
 * Watches AppState.replBridgeEnabled — when toggled off (via /config or footer),
 * the bridge is torn down. When toggled back on, it re-initializes.
 *
 * Inbound messages from claude.ai are injected into the REPL via queuedCommands.
 */
export function useReplBridge(messages: Message[], setMessages: (action: React.SetStateAction<Message[]>) => void, abortControllerRef: React.RefObject<AbortController | null>, commands: readonly Command[], mainLoopModel: string): {
  sendBridgeResult: () => void;
} {
```

## Corrections

旧版笔记把 `src/bridge/sessionRunner.ts` 的 NDJSON spawn 称作「底层引擎子进程的 NDJSON 通信 / 引擎子进程」，并称该通信「经由 `useReplBridge.tsx` 或 `sessionRunner.ts` 桥接」。据 v0.7.7 源码，这一归属不成立：

- `src/bridge/sessionRunner.ts` 导出 `createSessionSpawner`，它 spawn 的是**远控桥自己的 CLI 子进程**（参数含 `--sdk-url` 与 `--output-format stream-json`），并按行解析子进程 stdout 的 NDJSON；其类型注释明言「The bridge forwards this to the server」。调用方是 `src/bridge/bridgeMain.ts`（`claude remote-control` 的 poll loop），属于**独立的 remote code sessions 桥**，与桌面工作台的引擎子进程不是同一链路。
- 桌面工作台的主链路是：Electron 用 `['server', ...]` spawn `claude-sidecar`（`desktop/electron/services/sidecarManager.ts`）→ `src/server/index.ts`（桌面 HTTP + WebSocket 服务）→ `src/server/services/conversationService.ts` 用 `Bun.spawn(args, ...)` **按会话 spawn CLI**。进程分层与流协议详见 [RuntimeTopology](/docs/CS/AI/LLM/Agent/Product/CcHaha/RuntimeTopology.md) 与 [StreamProtocol](/docs/CS/AI/LLM/Agent/Product/CcHaha/StreamProtocol.md)。

调用方 `src/bridge/bridgeMain.ts` 的 import 原样摘录：

```ts
import { toCompatSessionId, toInfraSessionId } from './sessionIdCompat.js'
import { createSessionSpawner, safeFilenameId } from './sessionRunner.js'
import { getTrustedDeviceToken } from './trustedDevice.js'
```

`src/bridge/sessionRunner.ts` 中关于「bridge 转发给 server」的类型注释原样摘录：

```ts
/**
 * A control_request emitted by the child CLI when it needs permission to
 * execute a **specific** tool invocation (not a general capability check).
 * The bridge forwards this to the server so the user can approve/deny.
 */
export type PermissionRequest = {
  type: 'control_request'
  request_id: string
  request: {
    /** Per-invocation permission check — "may I run this tool with these inputs?" */
    subtype: 'can_use_tool'
    tool_name: string
    input: Record<string, unknown>
    tool_use_id: string
  }
}
```

`src/bridge/sessionRunner.ts` 的 spawn 参数与子进程创建原样摘录：

```ts
      const args = [
        ...deps.scriptArgs,
        '--print',
        '--sdk-url',
        opts.sdkUrl,
        '--session-id',
        opts.sessionId,
        '--input-format',
        'stream-json',
        '--output-format',
        'stream-json',
        '--replay-user-messages',
        ...(deps.verbose ? ['--verbose'] : []),
        ...(debugFile ? ['--debug-file', debugFile] : []),
        ...(deps.permissionMode
          ? ['--permission-mode', deps.permissionMode]
          : []),
      ]

      const env: NodeJS.ProcessEnv = {
        ...deps.env,
        // Strip the bridge's OAuth token so the child CC process uses
        // the session access token for inference instead.
        CLAUDE_CODE_OAUTH_TOKEN: undefined,
        CLAUDE_CODE_ENVIRONMENT_KIND: 'bridge',
        ...(deps.sandbox && { CLAUDE_CODE_FORCE_SANDBOX: '1' }),
        CLAUDE_CODE_SESSION_ACCESS_TOKEN: opts.accessToken,
        // v1: HybridTransport (WS reads + POST writes) to Session-Ingress.
        // Harmless in v2 mode — transportUtils checks CLAUDE_CODE_USE_CCR_V2 first.
        CLAUDE_CODE_POST_FOR_SESSION_INGRESS_V2: '1',
        // v2: SSETransport + CCRClient to CCR's /v1/code/sessions/* endpoints.
        // Same env vars environment-manager sets in the container path.
        ...(opts.useCcrV2 && {
          CLAUDE_CODE_USE_CCR_V2: '1',
          CLAUDE_CODE_WORKER_EPOCH: String(opts.workerEpoch),
        }),
      }

      deps.onDebug(
        `[bridge:session] Spawning sessionId=${opts.sessionId} sdkUrl=${opts.sdkUrl} accessToken=${opts.accessToken ? 'present' : 'MISSING'}`,
      )
      deps.onDebug(`[bridge:session] Child args: ${args.join(' ')}`)
      if (debugFile) {
        deps.onDebug(`[bridge:session] Debug log: ${debugFile}`)
      }

      // Pipe all three streams: stdin for control, stdout for NDJSON parsing,
      // stderr for error capture and diagnostics.
      const child: ChildProcess = spawn(deps.execPath, args, {
        cwd: dir,
        stdio: ['pipe', 'pipe', 'pipe'],
        env,
        windowsHide: true,
      })
```

`src/bridge/sessionRunner.ts` 解析子进程 stdout NDJSON 的原样摘录：

```ts
      // Parse NDJSON from child stdout
      if (child.stdout) {
        const rl = createInterface({ input: child.stdout })
        rl.on('line', line => {
          // Write raw NDJSON to transcript file
          if (transcriptStream) {
            transcriptStream.write(line + '\n')
          }
```

桌面主链路第一段：Electron 启动 sidecar server，原样摘自 `desktop/electron/services/sidecarManager.ts`：

```ts
}): SidecarPlan {
  return {
    command: resolveSidecarExecutable(desktopRoot),
    args: ['server', '--app-root', appRoot, '--host', bindHost, '--port', String(port)],
    env: buildSidecarEnv(withBundledRipgrepPath(env, desktopRoot), h5DistDir),
  }
}
```

桌面主链路第二段：服务入口注释，原样摘自 `src/server/index.ts`：

```ts
/**
 * Claude Code Desktop App — HTTP + WebSocket Server
 *
 * 为桌面端 UI 提供 REST API 和 WebSocket 实时通信。
 * 读写与 CLI 完全相同的文件系统，确保 CLI/UI 数据互通。
 */
```

桌面主链路第三段：按会话 spawn CLI，原样摘自 `src/server/services/conversationService.ts`：

```ts
    let proc: ReturnType<typeof Bun.spawn>
    migrationMaintenance.assertAvailable()
    // Another start registered a CLI for this session while this one was
    // awaiting. Overwriting the entry would leave that process running with
    // no owner, so retire it the way a runtime restart does (approved team
    // members keep running) and continue with this newer start.
    const registered = this.sessions.get(sessionId)
    if (registered) {
      console.warn(
        `[ConversationService] Replacing CLI pid ${registered.proc.pid} for ${sessionId}: a newer start reached spawn`,
      )
      this.stopSession(sessionId, { keepTeamWorkers: true })
    }
    try {
      proc = Bun.spawn(args, buildConversationCliSpawnOptions(launchWorkDir, childEnv))
      if (side) side.started = true
```

## Links

- [CcHaha 主枢纽](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md)
- [ScheduledTasks](/docs/CS/AI/LLM/Agent/Product/CcHaha/ScheduledTasks.md)
- [RemoteAccess](/docs/CS/AI/LLM/Agent/Product/CcHaha/RemoteAccess.md)
- [AgentTeams](/docs/CS/AI/LLM/Agent/Product/CcHaha/AgentTeams.md)
- [RuntimeTopology](/docs/CS/AI/LLM/Agent/Product/CcHaha/RuntimeTopology.md)
- [StreamProtocol](/docs/CS/AI/LLM/Agent/Product/CcHaha/StreamProtocol.md)

## References

- [cc-haha GitHub](https://github.com/NanmiCoder/cc-haha)
- [messageQueueManager.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/messageQueueManager.ts)
- [useCommandQueue.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/hooks/useCommandQueue.ts)
- [useReplBridge.tsx](https://github.com/NanmiCoder/cc-haha/blob/main/src/hooks/useReplBridge.tsx)
- [replLauncher.tsx](https://github.com/NanmiCoder/cc-haha/blob/main/src/replLauncher.tsx)
