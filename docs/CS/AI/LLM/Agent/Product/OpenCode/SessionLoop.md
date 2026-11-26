> 版本基线：v1.19.5（`E:/Projects/opencode-1.19.5`，无 `.git`，release 源码快照）。本文的会话循环指 **V2 Session Core**（`packages/core/src/session/`）——它是 v1.19.x 引入的 Event Sourcing 重构，与仍在 `packages/opencode/src/session/prompt.ts` 里的 legacy `SessionPrompt.loop(...)` 并存。`AGENTS.md` 专门立了 "V2 Session Core" 一節约束实现，本文对照实现逐条核实。

## Introduction

OpenCode 的 V2 会话循环要解决一个很具体的问题：**用户随时可能打断、补充或排队新指令，而模型这一轮可能正在流式输出、正在跑工具，进程也可能崩溃**。传统的"内存 while 循环驱动模型"很难回答"新输入在哪一个边界生效""两个进程同时 resume 谁说了算""崩溃后从哪续"。

V2 的答案是一套分层状态机：**durable admission**（输入先落库、不可见）→ **advisory wake**（只置标志，不等）→ **process-local coordinator**（同 Session join、不同 Session 并发）→ **runner drain**（在 safe boundary 晋升输入、跑单轮 provider turn、结算工具、判定 continuation）。

几个反直觉点：

- **admit 一条 prompt 不等于发了一条用户消息**：admit 只在 `session_input` 表留一行 `promoted_seq = NULL` 的 inbox 记录，`message-updater` 对 `session.next.prompt.admitted` 的处理是 `() => Effect.void`。消息真正出现在历史/UI 要等 drain 在边界发 `Prompted` 事件。
- **`wake` 是 advisory 且空转 no-op，显式 `resume` 却在零输入时也打一次模型**：名字相近，语义差别极大。
- **"重置 step allowance" 不是按 drain，而是按"上次用户输入之后"**，且一批 steer 只重置一次。
- **`events.claim(...)` 听上去像"锁定 session 供执行"，实际与执行无关**，只写事件聚合层的 owner 栅栏。

## Durable Admission

`SessionV2.prompt` 的入口在 `packages/core/src/session.ts`，整段被 `Effect.uninterruptible` 包裹，保证 admit 和 wake 不被中断撕裂：

```typescript
prompt: Effect.fn("V2Session.prompt")((input) =>
  Effect.uninterruptible(
    Effect.gen(function* () {
      yield* result.get(input.sessionID)
      const prompt = resolvePrompt(input.prompt)
      const messageID = input.id ?? SessionMessage.ID.create()
      const delivery = input.delivery ?? "steer"
      const expected = { sessionID: input.sessionID, messageID, prompt, delivery }
      const admitted = yield* SessionInput.admit(db, events, {
        id: messageID, sessionID: input.sessionID, prompt, delivery,
      }).pipe(
        Effect.catchDefect((defect) =>
          defect instanceof SessionInput.LifecycleConflict
            ? new PromptConflictError({ sessionID: input.sessionID, messageID })
            : Effect.die(defect),
        ),
      )
      if (!SessionInput.equivalent(admitted, expected))
        return yield* new PromptConflictError({ sessionID: input.sessionID, messageID })
      if (input.resume !== false) yield* execution.wake(admitted.sessionID)
      return admitted
    }),
  ),
),
```

要点：

- `delivery` 默认 `"steer"`；类型 `SessionDelivery.Delivery = Schema.Literals(["steer","queue"])`。
- `equivalent(admitted, expected)` 是**事后冲突校验**：比较 delivery、sessionID 与 `JSON.stringify(encodePrompt(...))` 完全相等。这就是"复用同一 message ID 只在 Session / prompt / delivery 三者都匹配时算精确重试，冲突则失败"的落点。`resume:false` 则只 admit、完全不 wake。

`SessionInput.admit`（`packages/core/src/session/input.ts`）先按 message ID 查重（幂等），durable 性来自 `EventV2.publish` 返回的 `event.durable.seq`（没有 aggregate sequence 就 `Effect.die`），这个 seq 成为 `admittedSeq`：

```typescript
const existing = yield* find(db, input.id)
if (existing !== undefined) return existing
const timestamp = yield* DateTime.now
return yield* events
  .publish(SessionEvent.PromptAdmitted, {
    messageID: input.id, sessionID: input.sessionID, timestamp,
    prompt: input.prompt, delivery: input.delivery,
  })
  .pipe(
    Effect.flatMap((event) =>
      event.durable === undefined
        ? Effect.die("Prompt admission event is missing aggregate sequence")
        : Effect.succeed(Admitted.make({
            admittedSeq: event.durable.seq, id: input.id, sessionID: input.sessionID,
            prompt: input.prompt, delivery: input.delivery, timeCreated: timestamp,
          })),
    ),
    Effect.catchDefect((defect) =>
      find(db, input.id).pipe(Effect.flatMap((stored) => (stored ? Effect.succeed(stored) : Effect.die(defect)))),
    ),
  )
```

`Admitted` 的核心字段（`packages/schema/src/session-input.ts`）：`admittedSeq`、`id`（复用为 SessionMessage.ID）、`sessionID`、`prompt`、`delivery`、`timeCreated`、可选 `promotedSeq`。投影到 DB 后是 `session_input` 的一行，`promoted_seq` 初始为 NULL。`catchDefect` 是并发兜底：publish 中出缺陷就重查一次，别人已写入就当成功。

## Wake and the Process-Local Coordinator

`SessionExecution` 的 Service 只有 `active / resume / wake / interrupt` 四个方法。它是 **process-global** 单例（`LayerNode.unbound(Service, Node.tags.values.global)`），由 `execution/local.ts` 注入；相对地，runner / 模型 / 权限 / 工具 / 文件系统都是按 Location 构建的（Location-scoped）。

local 实现把 `wake` 直接透传给 `SessionRunCoordinator.wake`，并把 `drain` 定义为"到真正开跑时才解析 Location、取 runner"：

```typescript
const coordinator = yield* SessionRunCoordinator.make<SessionSchema.ID, SessionRunner.RunError>({
  drain: Effect.fnUntraced(function* (sessionID: SessionSchema.ID, force) {
    const session = yield* store.get(sessionID)
    if (!session) return yield* Effect.die(`Session not found: ${sessionID}`)
    return yield* SessionRunner.Service.use((runner) => runner.run({ sessionID, force })).pipe(
      Effect.provide(locations.get(session.location)),
    )
  }),
})
return SessionExecution.Service.of({
  active: coordinator.active, interrupt: coordinator.interrupt,
  resume: coordinator.run, wake: coordinator.wake,
})
```

这里有个重要限定：local 实现的注释写明 "Current-process routing for implicit-local Locations. Future remote placement belongs here."。也就是说 v1.19.5 快照里**没有真正的"发现 session 落在哪个进程"机制**——每个进程有自己的协调器，drain 解析的是"哪个 Location 的服务包"，不是"哪个远程进程"。跨进程 placement 是未实现的未来切片。

协调器本身是 `Map<Key, Entry>` + 共享 `FiberSet`。不同 Session（Key 不同）各自 fork，天然并发；同 Session 通过 `Deferred.await(entry.done)` join：

```typescript
const run = (key: Key): Effect.Effect<void, E> =>
  Effect.uninterruptibleMask((restore) => {
    const entry = active.get(key)
    if (entry !== undefined) {
      if (entry.stopping) return restore(Deferred.await(entry.done).pipe(Effect.andThen(run(key))))
      return restore(Deferred.await(entry.done))
    }
    const next = makeEntry()
    active.set(key, next)
    start(key, next, true)
    return restore(Deferred.await(next.done))
  })

const wake = (key: Key) =>
  Effect.sync(() => {
    const entry = active.get(key)
    if (entry !== undefined) { entry.pendingWake = true; return }
    const next = makeEntry()
    active.set(key, next)
    start(key, next, false)
  })
```

- 显式 `resume` 走 `run`：已有 entry 就 join；没有就 `force=true` 启动（即使零输入也跑一次 quiet turn）。
- prompt `wake` 走 `wake`：已有 entry 只置 `pendingWake=true`（合并、不阻塞、不重复启动）；没有才 `force=false` 启动。
- `settle` 在 drain 成功且 `pendingWake` 且未 stopping 时复用同一 entry 立即续跑（coalesced follow-up），否则新建 entry 接替或从 `active` 删除。
- `interrupt(key)` 只针对**本进程**里该 Session 当前 owner fiber 链；idle 或本进程无 entry 就是 no-op。

## The Drain and Safe-Boundary Promotion

`SessionRunner.run`（`packages/core/src/session/runner/llm.ts`）是双层循环：

```typescript
const hasSteer = yield* SessionInput.hasPending(db, input.sessionID, "steer")
const hasQueue = hasSteer ? false : yield* SessionInput.hasPending(db, input.sessionID, "queue")
if (!input.force && !hasSteer && !hasQueue) return
yield* failInterruptedTools(input.sessionID)
let promotion: SessionInput.Delivery | undefined = hasSteer ? "steer" : hasQueue ? "queue" : undefined
let shouldRun = input.force || hasSteer || hasQueue
while (shouldRun) {
  let needsContinuation = true
  let step = 1
  while (needsContinuation) {
    const result = yield* runTurn(input.sessionID, promotion, step)
    needsContinuation = result.needsContinuation
    step = result.step + 1
    promotion = "steer"
    if (!needsContinuation) needsContinuation = yield* SessionInput.hasPending(db, input.sessionID, "steer")
  }
  shouldRun = yield* SessionInput.hasPending(db, input.sessionID, "queue")
  promotion = shouldRun ? "queue" : undefined
}
```

- steer 优先于 queue（`hasQueue = hasSteer ? false : ...`）；advisory wake（`force=false`）且无 eligible 输入直接 return。
- `failInterruptedTools` 先把上一轮遗留的 pending/running 工具标失败。
- 内层 `while(needsContinuation)` 是工具/continuation 循环；每轮结束 `promotion = "steer"`，drain 期间新到的 steer 会在下一个 provider-turn 边界自动被消费。
- 内层退出后外层只查 queue：queue 输入一直 pending 到 Session 将转 idle 的边界，每次只 promote 最早一条，再重新评估 continuation。

safe boundary 在 `runTurnAttempt` 开头。先做 Location 归属校验（session 的 directory/workspaceID 与当前 Location 不符就 `Effect.interrupt`），再选 agent、初始化 context epoch，然后晋升输入：

```typescript
if (promotion) {
  const cutoff = yield* EventV2.latestSequence(db, session.id)
  let promoted = 0
  if (promotion === "steer") promoted = yield* SessionInput.promoteSteers(db, events, session.id, cutoff)
  if (promotion === "queue") {
    promoted += Number(yield* SessionInput.promoteNextQueued(db, events, session.id))
    promoted += yield* SessionInput.promoteSteers(db, events, session.id, cutoff)
  }
  if (promoted > 0) currentStep = 1
}
```

`cutoff = latestSequence` 保证只晋升该轮开始前的 admitted 输入；`if (promoted > 0) currentStep = 1` 就是"新输入重置 provider-turn allowance"，一批 steer 因在一次 `promoteSteers` 调用内晋升而只重置一次。晋升最终走 `SessionEvent.Prompted`，`message-updater` 的对应分支才追加可见消息：

```typescript
"session.next.prompted": (event) => {
  return adapter.appendMessage(SessionMessage.User.make({
    id: event.data.messageID, type: "user", metadata: event.metadata,
    text: event.data.prompt.text, files: event.data.prompt.files,
    agents: event.data.prompt.agents, time: { created: event.data.timestamp },
  }))
},
"session.next.prompt.admitted": () => Effect.void,
```

## One Provider Turn and Tool Settlement

每轮 `runTurnAttempt` 的顺序：校验 Location → 选 agent → `SessionContextEpoch.initialize/prepare` → `models.resolve(session)` → `SessionHistory.entriesForRunner(...)` **重新加载投影历史** → `toLLMMessages` → `LLM.request({...})` → compaction 检查 → 一次 `llm.stream(request)`。

```typescript
const providerStream = llm.stream(request).pipe(
  Stream.runForEach((event) =>
    Effect.gen(function* () {
      if (overflowFailure || publisher.hasProviderError()) return
      if (LLMEvent.is.providerError(event)) {
        if (isContextOverflowFailure(event) && !publisher.hasAssistantStarted()) {
          overflowFailure = event
          return
        }
      }
      yield* publish(event)
      if (event.type !== "tool-call" || event.providerExecuted) return
      if (!toolMaterialization) {
        yield* withPublication(publisher.failUnsettledTools("Tools are disabled after the maximum agent steps"))
        return
      }
      needsContinuation = true
      const assistantMessageID = yield* publisher.assistantMessageID(event.id)
      yield* Effect.uninterruptibleMask((restore) =>
        restore(toolMaterialization.settle({
          sessionID: session.id, agent: agent.id, assistantMessageID, call: event,
        })).pipe(
          Effect.flatMap((settlement) =>
            publish(LLMEvent.toolResult({ id: event.id, name: event.name,
              result: settlement.result, output: settlement.output }), settlement.outputPaths ?? []),
          ),
        ),
      ).pipe(FiberSet.run(toolFibers))
    }),
  ),
  Effect.ensuring(withPublication(publisher.flush())),
)
```

- 每轮**恰好一次** `llm.stream(request)`；文本/usage/reasoning/tool-call 增量都 `publish` 成 durable session event。
- 遇到非 provider 执行的 tool-call，置 `needsContinuation = true`，并在 `uninterruptibleMask` 下 `settle` 抛进 `FiberSet` 并行执行（durably record before side effects），完成后 publish toolResult。
- 流结束后处理 overflow compaction（`TurnTransitionError` 重建 request 再显式开下一轮）、LLM 失败、用户 decline（`PermissionV2.DeclinedError` → `Effect.interrupt`），await 所有工具结算，最后 publish `Step.Ended`，返回 `{ needsContinuation, step }`。
- 外层每轮重新 `entriesForRunner` 加载上一轮新落库的 assistant/tool 结果——这就是"reload projected history before durable continuation"。

**为什么禁止 bridge 到 legacy `SessionPrompt.loop(...)`**：两者是两套互不兼容的状态与所有权模型。legacy 用实例内存 `Map<SessionID, Runner>` + `runLoop` 的 `while(true)`，读写 V1 `MessageTable`/`PartTable`；V2 用 process-global coordinator + EventV2 durable 投影 + `SessionMessageTable`。V2 runner 的 import 里没有任何 legacy `SessionPrompt`/`processor` 依赖，"禁止 bridge"体现为 V2 独立实现编排 + `AGENTS.md` 硬约束，而非运行时检查。

## Replay Owner vs Execution Ownership

`events.claim(sessionID, workspaceID)` 只写 `EventSequenceTable.owner_id`，用途是 replay/sync 时忽略旧 workspace 来的事件（`strictOwner` 不匹配直接 die，同 owner 重复事件按 seq 幂等吞掉，不同 owner 静默忽略）。它是**持久化、与进程生命周期无关**的"哪个 workspace 拥有这个聚合事件流"标签。

而 execution ownership 在 v1.19.5 中是 `run-coordinator.ts` 里进程内存的 `Map<Key, Entry>` + FiberSet + `Deferred`，完全不使用 owner_id。所以二者职责不同：一个是事件日志的同步权威，一个是（未来的）运行时租约。把二者合并会让 replay 授权标签兼任运行时锁，并把事件重放耦合到进程存活状态。

## What Is Not Implemented

`packages/core/src/session/runner/llm.ts` 的文件头清单是判断现状最权威的素材，未勾选（`[ ]`）的包括：

```typescript
 * - [ ] Replace local ownership with durable multi-node ownership when clustered.
 * - [ ] Mark busy, retrying, idle, interrupted, or terminal-failure status durably.
 * - [ ] Honor interruption and reject stale work after runtime attachment replacement.
 * - [ ] Bound provider retries and repeated identical tool calls.
 * - [ ] Continue for compaction or another continuation condition when required.
```

文件结尾明确写 "Durable continuation recovery remains a separate future slice with an explicit retry policy."。当前现状：wake 只晋升 eligible 的 durable inbox 行；进程若在 provider turn 中途崩溃，没有"这一 turn 正在进行"的 durable 标记、没有重试策略、没有恢复半截 turn 的机制。下一次 drain 的唯一清理动作 `failInterruptedTools` 属于清理而非 provider work 恢复。drain 本身"无 durable identity、无 transcript boundary"，无法判定 crashed turn 从哪个 seq 续起。

## Links

- [Context](/docs/CS/AI/LLM/Agent/Product/OpenCode/Context.md) / [Persistence](/docs/CS/AI/LLM/Agent/Product/OpenCode/Persistence.md) / [Tools](/docs/CS/AI/LLM/Agent/Product/OpenCode/Tools.md)
- [Agent](/docs/CS/AI/LLM/Agent/Product/OpenCode/Agent.md) / [Provider](/docs/CS/AI/LLM/Agent/Product/OpenCode/Provider.md) / [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)

## References

1. [core 会话循环 runner/llm.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/core/src/session/runner/llm.ts)
2. [admission input.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/core/src/session/input.ts)
3. [协调器 run-coordinator.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/core/src/session/run-coordinator.ts)
4. [执行执行层 execution/local.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/core/src/session/execution/local.ts)
5. [SessionV2 入口 session.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/core/src/session.ts)
