> 版本基线：v0.2.2-rc.3（`E:/Projects/deepseek-harness-dsh-v0.2.2-rc.3`）。Agent Loop 的结束判断与 Session 事件溯源是 DSH 最有辨识度的两块——前者把结束拆成五层边界，后者把一切操作变成可重建的追加日志。

## Introduction

DSH 的默认 Agent Loop 本身也是一个插件（`AgentLoop extends Service implements AgentFactory`）。它不是裸 `while` 循环，而是**状态机 + 事件日志 + 拦截链**：从插件图取能力（工具、模型、上下文），把每个事实写回 session log。

> 版本基线：v0.2.2-rc.3。

几个反直觉的点：

- **turn-stopping 没有布尔返回**：`agent/turn-stopping` 是 serial 事件，监听器**不能**靠返回 false 否决继续，只能 `agent.steer()` 往 inbox 写消息——机器在 await 之后重新读 `inbox.nextStep.length` 决定开不开下一步。
- **重试不重跑门禁**：step 内 `agent/request-error` 返回 `{ kind:'retry' }` 只重跑 `prepareRequest/buildRequest/stream`，不重跑 `agent/pre-step`、不重新组装提示词、不重复追加 user/message。
- **取消时边界事件仍落盘，system/user 不落盘**：`turn/start`/`turn/end` 必有，但被取消的 step 若停在提交之前的异步阶段，则不会写入任何模型可见输入。

## The Driver and Phase State Machine

默认 loop 依赖六项 service（`packages/core/agent-loop/src/index.ts`）：

```ts
/** Concrete agent factory and driver service. */
export class AgentLoop extends Service implements AgentFactory {
  static inject = ['agents', 'sessions', 'llm', 'tools', 'systemPrompt', 'sessionProjections']
```

每台活 Agent 是一个 `ReactLoopAgent`，phase 是 idle/maintenance/running 三态（`packages/core/agent-loop/src/agent.ts`）：

```ts
type Phase =
  | { kind: 'idle'; lastTurn: number }
  | {
    kind: 'maintenance'
    abort: AbortController
    lastTurn: number
    wakeRequested: boolean
  }
  | { kind: 'running'; abort: AbortController; turn: number; step: number; wakeRequested: boolean }
```

顶层 driver 就是 `while (await this.turn())`，失败与取消在 driver 边界收敛（`packages/core/agent-loop/src/agent.ts`）：

```ts
  private async kick(): Promise<void> {
    try {
      while (await this.turn()) {}
    } catch (_error) {
      // Reported failures and cancellation are contained at the driver boundary.
    } finally {
      /* v8 ignore next -- kick owns a running phase until this driver boundary */
      if (this.phase.kind === 'running') {
        const { turn, wakeRequested } = this.phase
        this.setPhase({ kind: 'idle', lastTurn: turn })
        if (wakeRequested && this.inbox.hasPending) this.wakeDriver()
      }
    }
  }
```

`maintenance` 锁存维护期到来的唤醒意图（wakeRequested），维护后查 inbox 决定是否重启——解决"唤醒与卸载/重载交错"的竞态。

## Turn and Step: Precise Definitions

一个 **step** 是一次模型请求 + 它调用的工具批次；一个 **turn** 是零到多个 step，从 `turn/start` 到 `turn/end`。turn driver 的核心（`packages/core/agent-loop/src/agent.ts`）：

```ts
  private async turn(): Promise<boolean> {
    // ...
    const turn = phase.turn + 1
    try {
      this.session.append('turn/start', { turn })
    } catch (error: unknown) {
      this.throwError(error)
    }
    phase.turn = turn
    let turnEnds: TurnEndReason | null = null
    let target: InboxTarget = 'next-turn'
    try {
      while (true) {
        signal.throwIfAborted()
        const step = phase.step + 1
        const decision = await this.preStep(target, { turn, step })
        if (decision.kind === 'reject') {
          turnEnds = { kind: 'blocked' }
          return false
        }
        try {
          if (turnEnds && decision.messages.length === 0) break
          // A removed waking message or an enter decision rewritten to empty
          // still owns the initial turn boundary, but it spends no model call.
          if (phase.step === 0 && decision.messages.length === 0) {
            turnEnds = { kind: 'completed' }
            return false
          }
          signal.throwIfAborted()
          this.session.append('step/start', { turn, step })
          phase.step = step
          const toolRecovery = new ToolCallRecovery()
          // ...
          const stepEnd = await this.step(decision)
          // max-tokens stays sticky: a later completed step must not
          // downgrade the turn outcome.
          if (turnEnds === null || turnEnds.kind !== 'max-tokens') turnEnds = stepEnd
        } finally {
          decision.toolSet.dispose()
          this.session.append('step/end', { turn, step })
        }
        signal.throwIfAborted()
        if (turnEnds && this.inbox.nextStep.length === 0) {
          await this.dispatch.serial('agent/turn-stopping', { turn, signal })
          signal.throwIfAborted()
        }
        if (turnEnds && this.inbox.nextStep.length === 0) break
        target = 'next-step'
      }
    } catch (error: unknown) {
      // ... structured failure → turnEnds
    } finally {
      this.session.append('turn/end', { turn, reason: turnEnds! })
    }
    if (!this.inbox.hasPending) return false
    phase.abort = new AbortController()
    phase.wakeRequested = false
    phase.step = 0
    return true
  }
```

要点：领输入前写 `turn/start`，必有唯一 `turn/end` 收口；被 pre-step 拒绝（`blocked`）或首批消息改写为空的 turn 不打开 step、不调用模型。max-tokens 是**粘性**的，记整个 turn 的质量。

## Pre-Step: The Gate

`agent/pre-step` 是每个 step 开头的门禁 waterfall：领输入、快照 modelSelection、组装提示词与工具集，然后由监听器接纳/改写/拒绝（`packages/core/agent-loop/src/agent.ts`）：

```ts
  private async preStep(target: InboxTarget, position: { turn: number; step: number }): Promise<PreparedStep> {
    const signal = this.phase.abort.signal
    const claimed = this.inbox.claim(target, position.turn)
    const selection = this.model.current()
    if (selection === undefined) {
      throw new Error(`agent "${this.id}" has no provider/model: ...`)
    }
    const toolSet = await this.loopCtx.tools.resolve({ agent: this, modelSelection: selection, signal })
    try {
      const assembly = await this.loopCtx.systemPrompt.assemble({ ...assembleContextFor(this, signal), modelSelection: selection, toolSet })
      signal.throwIfAborted()
      const decision = await this.dispatch.waterfall(
        'agent/pre-step', { messages: claimed, ...position, signal, modelSelection: selection },
        (): Promise<PreStepDecision> => {
          const sections = renderContextSections(assembly)
          const context = this.runtimeContext.project(sections)
          return Promise.resolve<PreStepDecision>({
            kind: 'enter',
            messages: context === undefined ? claimed : [...claimed, context],
          })
        },
      )
      if (decision.kind === 'reject') {
        toolSet.dispose()
        return decision
      }
      return { ...decision, assembly, selection, toolSet }
    } catch (error: unknown) {
      toolSet.dispose()
      throw error
    }
  }
```

selection 在这里被快照冻结，贯穿整步；`agent/request` 监听器若试图改 provider/model/reasoningEffort 会被显式拒绝（要求改用 `agent.model.select()`），保证日志里的 header 与真正发出的请求一致。

## Request Preparation and Cancellation

`prepareRequest` 先把 `agent/request` waterfall 与 `llm.prepareCall()` 跑完、绑定好 adapter，**然后**才提交 system/user 消息（`packages/core/agent-loop/src/agent.ts`）：

```ts
    let config: LlmCallConfig
    let preparedCall: PreparedLlmCall | undefined
    try {
      preparedCall = await this.loopCtx.llm.prepareCall(proposedConfig, signal)
      config = preparedCall.config
    } catch (error: unknown) {
      // Middleware may serve an unregistered route; terminal dispatch still requires an adapter.
      if (!(error instanceof LlmError) || error.code !== 'NO_ADAPTER') throw error
      config = proposedConfig
    }
    signal.throwIfAborted()
```

提交前的多次 `signal.throwIfAborted()` 保证：取消落在任一异步阶段，都不写 system/message 与 user/message。真正发流时用已绑定的 `preparedCall?.stream(request)`，不重新解析 adapter。冻结请求再打标记：

```ts
    deepFreeze(header)
    const boundaryMessages = session.deriveMessages()
    for (const message of boundaryMessages) {
      if (this.frozenMessages.has(message)) continue
      deepFreeze(message)
      this.frozenMessages.add(message)
    }
    Object.freeze(boundaryMessages)
    const request = markAgentLoopRequest(Object.freeze({
      ...header.config,
      messages: boundaryMessages,
      toolHistory: session.toolHistory(),
      sessionId: this.session.id,
      signal,
    }))
```

`cancel()` 先清 inbox（除 keepInbox）再 abort 当前活动（`packages/core/agent-loop/src/agent.ts`）：

```ts
  cancel(cause: AgentCancelCause, options: CancelOptions = {}): void {
    try {
      if (!options.keepInbox) this.inbox.clear()
    } finally {
      if (this.phase.kind !== 'idle') {
        if (!options.keepInbox) this.phase.wakeRequested = false
        this.phase.abort.abort(cause)
      }
    }
  }
```

## Tool Consolidation and Ordered Commit

工具批次由执行器并行跑，但 `concluded` 用 **OR 聚合**——任一结果 `concludesTurn === true` 就结束整轮（`packages/core/tools/src/batch.ts`、`packages/core/agent-loop/src/agent.ts`）：

```ts
        const toolCalls = message.content.filter(block => block.type === 'tool-call')
        if (toolCalls.length === 0) return { kind: 'completed' }
        const maxParallelToolCalls = this.loopCtx.agentLoop.config.maxParallelToolCalls.get()
        try {
          const result = await this.loopCtx.tools.execute({
            calls: toolCalls, signal, agent: this, log: { turn, step },
            maxParallelToolCalls, toolSet: decision.toolSet,
          })
          for (const context of result.additionalContexts) {
            this.inbox.splice('next-step', this.inbox.nextStep.length, 0, [context])
          }
          return result.concluded ? { kind: 'completed' } : null
        } catch (error: unknown) {
          // ... partial results preserved, then rethrow
        }
```

返回 `null` 表示模型欠一次回访（继续下一步），`completed` 表示收口。OR 是"软收口"：取消回访债务但不压消息债务，并行工具继续跑。与 Pi 的 **AND 聚合**（全部 terminate 才终止）相比更激进。步失败时用 `ToolCallRecovery` 为悬挂调用补合成 `tool/result`（配对 tool/call，维持协议）。

## Assistant Stream and Durable Settlement

`agent/assistant-stream` 是纯 live 的瞬时帧（start/chunk/end），durable 的是对应的 `assistant/message`/`assistant/attempt`（`packages/core/agent-loop/src/assistant-stream.ts`）：

```ts
  settle(
    eventType: 'assistant/message' | 'assistant/attempt',
    append: () => SessionSeq,
  ): void {
    let seq: SessionSeq
    try {
      seq = append()
    } catch (error: unknown) {
      this.abandon()
      throw error
    }
    this.terminal = true
    this.emit({
      type: 'end',
      attemptId: this.attemptId,
      revision: this.nextRevision(),
      index: this.index,
      outcome: { kind: 'committed', eventType, seq },
    })
  }
```

end 帧只在 durable 提交成功（带 committed seq）或明确放弃后发出——Web 的 Session-follow 适配器是它唯一的远端消费者。

## Five-Layer Boundary of Termination Semantics

生产环境里 `while (hasToolCalls)` 远远不够，DSH 把"什么时候真的停"拆成五层：

1. **模型请求结束**：Provider 流式输出完成（正常/工具调用/最大 token/错误/取消，见 `finish.reason`）。
2. **step 结束**：一次模型调用 + 它发起的整批工具执行；欠一次模型回访时 step 结束但 turn 未结束。
3. **turn 结束**：需同时满足 ①模型不欠回复（无未收口 tool call）②`next-step` inbox 无待处理输入——"模型债务 + 消息债务"共同决定。
4. **driver activity 结束**：一个 driver 连续处理多个 turn，队列耗尽回 idle。
5. **长期工作流结束**：Goal Driver 监听 idle 检查持久 Goal 开启新 turn；idle 只描述当前 activity，不回答长期目标是否完成。

`TurnEndReason` 的七种里 loop 活跃期只会产生五种：`completed`、`max-tokens`、`blocked`、`aborted`、`error`；`interrupted`（崩溃恢复补写）与 `forked`（分叉切分）是冷路径合成标记。

## Inbox: Durable Pending Input

inbox 的 pending 状态本身也是投影，从一个规范化 `agent/inbox/spliced` 事件 fold 出来（`packages/core/agent-loop/src/inbox.ts`）：

```ts
export const inboxProjectionDefinition = {
  key: 'inbox',
  stateSchema: inboxProjectionSchema,
  init: (): InboxState => ({ 'next-turn': [], 'next-step': [] }),
  apply(state: InboxState, event) {
    if (event.type !== 'agent/inbox/spliced') return state
    const splice = event.data
    // ... validate bounds, apply toSpliced, check duplicate ids
  },
```

`claim()` 用纯删除领取输入（不产生 discarded 事件）：被领取的消息进入 step 的 decision.messages；若随后 pre-step reject，它既没被丢弃也没被投影为 user/message，turn 以 blocked 关闭。

## Extension Point Events

| 事件 | 模式 | 作用 |
| --- | --- | --- |
| `system-prompt/assemble` | waterfall | 组装系统提示词、动态上下文与工具列表 |
| `agent/pre-step` | waterfall | 执行门禁：接纳/拒绝/改写输入；reject 则 turn/end(blocked) |
| `agent/request` | waterfall（已弃用） | 只调 controls，不能改 provider/model/effort |
| `llm/stream` | waterfall | 包装或替换自定义流式迭代器 |
| `agent/request-error` | waterfall | 模型请求失败后的恢复；`{kind:'retry'}` -owned 恢复不调 next |
| `tools/pre-execute` | waterfall | 工具执行前校验，返回 allow/deny/ask/cancel |
| `tools/execute` | waterfall | 包装实际执行，可做超时/重试 |
| `tools/post-execute` | waterfall | 操作结果，替换内容或附加 context |
| `agent/turn-stopping` | serial（唯一） | Turn 关闭前最后机会，无布尔返回 |

emit 型通知包括 `agent/status`、`tools/result`（只读）、`agent/error`、`session/event`、`agent/assistant-stream`。注意 `session/event` 是 durable 事件写入时立即通知，承担前端推送与投影重算——它是 live 与 durable 的桥。

## Goal Outer Loop

Goal Driver 监听 idle → 检查 Goal 有效/phase active/round 上限 → 构造一条 `source.kind='goal'` 的 user message 用 `agent.followup()` 开新 turn（`packages/goal/goal-round-driver/src/index.ts`）：

```ts
    const round = goal.roundsStarted + 1
    const content = renderGoalRoundPrompt(goal, round)
    const message = createUserMessage({
      content,
      source: { kind: 'goal', goalId: goal.id, revision: goal.revision, round },
    })
    // ... reserve attempt, then agent.followup(message)
```

**持久 phase（active/complete/blocked/paused）与进程内 activation（armed/disarmed）分离**：恢复后 active Goal 默认 disarmed，需人工授权（fail-safe）。Goal 只记录状态、不调度工作——续跑就是"给自己 inbox 投一条消息"，仍在同一 session、同一 loop 里。

## Links

- [DSH 主入口](/docs/CS/AI/LLM/Agent/Product/DSH/DSH.md)
- [DSH Cordis 微内核](/docs/CS/AI/LLM/Agent/Product/DSH/Cordis.md)
- [DSH Tools & Capability Seams](/docs/CS/AI/LLM/Agent/Product/DSH/Tools.md)
- [DSH Session & Persistence](/docs/CS/AI/LLM/Agent/Product/DSH/SessionPersistence.md)
- [DSH Subagent & Team](/docs/CS/AI/LLM/Agent/Product/DSH/SubagentTeam.md)
- [Pi（AND 聚合对照）](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md)

## References

1. [deepseek-ai/deepseek-harness（v0.2.2-rc.3）agent-loop](https://github.com/deepseek-ai/deepseek-harness/tree/v0.2.2-rc.3/packages/core/agent-loop)
2. [架构文档 — Turn flow](https://github.com/deepseek-ai/deepseek-harness/blob/v0.2.2-rc.3/docs/architecture.md)
3. [DSH 和 Pi 的 Agent Loop 循环结束判断架构细节解析](https://mp.weixin.qq.com/s/7KJgpnKQ0VVHe-oMnS2L5Q)
