## Introduction

DSH 的 Session 是一份**追加式事件日志**（event-sourced），它同时是"系统刚才做过什么"的记录、模型上下文的唯一真相源、以及 fork / 回放 / 迁移 / 遥测的共同基座。理解 Session 就理解了 DSH 为什么能把上下文当成整个 Harness 的数据底座。

> 版本基线：v0.2.2-rc.3（`E:/Projects/deepseek-harness-dsh-v0.2.2-rc.3`）。

几个反直觉的点：

- **"append 成功" ≠ "已落盘"**：事件 push 进内存 log 即 committed，持久化是另一个异步、带 flush 检查点的通道。
- **压缩是"遮蔽"不是"删除"**：`surfaceOp: {op:'replace'}` 让 surface 遮蔽一段节点，被遮蔽事件仍完整留在 log 里，所以回放确定性、恢复后派生历史一致。
- **未知事件默认"必需"**：读者遇到不认识的类型必须**拒绝重建**而非丢弃，可忽略必须显式标 `ignorable: true`——宁可过度拒绝，不可静默 resume 一个被掏空的 session。

## The Append-Only Log

Session 是纯类（不是 Service），核心是日志与 seq 契约（`packages/core/session/src/index.ts`）：

```ts
/**
 * An event-sourced session: an append-only log of {@link SessionEvent}s.
 * Plain class (not a Service) — create live instances via
 * `ctx.sessions.create()` and detached instances via {@link create}.
 */
export class Session {
  private log: SessionEvent[] = []
  private batchPublication: SessionEvent | undefined
  /** Single incremental owner of surface acceptance and projection state. */
  private readonly surfaceManager: SurfaceManager

  /** The next event's sequence number — always the log length (the `seq = log.length` contiguity contract). */
  get seq(): SessionLogOffset {
    return SessionLogOffset(this.log.length)
  }
```

`seq = log.length` 让 seq 同时是数组下标——回放、fork、修复、投影共享同一坐标系（构造时逐条校验 `snapshot.seq === index`，否则拒绝）。

`append()` 在写入前做一次性 JSON 深拷贝与 surface 契约校验，返回事件自带 snapshot 的 data——读回来永远是日志里的值，不是调用方仍可变的输入（`packages/core/session/src/index.ts`）：

```ts
  append(
    type: SessionEventType | readonly SessionEventInput[],
    data?: SessionEventMap[SessionEventType],
    ...opts: [opts?: SurfaceIntent]
  ): SessionEvent | readonly SessionEvent[] {
    if (typeof type !== 'string') return this.#appendEvents(type)
    this.publicationEntry()
    const snapshot = snapshotAppend(type, data, opts[0], `session event "${type}"`)
    const entry = this.publicationEntry()
    const event = createAppendEvent(snapshot, SessionSeq(this.log.length))
    this.commit(event, entry)
    return event
  }
```

`commit()` 校验 surface → push 进 log → 同步派发 `session/event`。**提交点是内存 push，不是磁盘 fsync**：

```ts
  private commit(event: SessionEvent, entry: SessionEntry | undefined): void {
    this.surfaceManager.validateNext(event)
    if (entry !== undefined) entry.appending = true
    try {
      const callbacks = entry === undefined
        ? undefined
        : collectSessionCallbacks(entry.emitCtx, [entry.carrier, 'session/event', ...callbackArgs])
      this.log.push(event)
      this.eventsSnapshot = undefined
      if (entry !== undefined && callbacks !== undefined) {
        invokeContainedSessionObservers(entry.emitCtx, 'session/event', entry.id, callbackArgs, callbacks)
      }
    } finally {
      // ...
    }
  }
```

## SessionEvent and Surface Metadata

`SessionEventMap` 是 merge-extensible、append-only 的真相源；`SessionEvent` 是对 `type` 的判别联合，不是独立的 type/data 联合（`packages/core/session/src/types.ts`）：

```ts
export type SessionEvent<T extends SessionEventType = SessionEventType> = {
  [K in SessionEventType]: {
    type: K
    /** Monotonic sequence number within the session. */
    seq: SessionSeq
    /** Unix epoch milliseconds. */
    time: number
    data: SessionEventMap[K]
    ignorable?: true
  } & (K extends SurfaceEventType ? SurfaceIntent<K> : {
    surfaceOp?: never
    sourceEventSeqs?: never
  })
}[T]
```

只有五类消息产出事件（`system/message`、`user/message`、`assistant/message`、`tool/result`、checkpoint）能携带 `surfaceOp` / `sourceEventSeqs`；边界标记、attempt、错误等 log-only 事件在类型层就没有 surface 字段。`ignorable` 缺省即"必需"——读者遇到未知且不可忽略的类型必须拒绝重建。

## deriveMessages: The Single Source of Model Context

模型历史是日志的纯函数。`deriveMessages()` 遍历 surface 维护的节点序列（都是 seq），回查日志、逐条派生消息（`packages/core/session/src/index.ts`）：

```ts
  deriveMessages(): Message[] {
    const surface = this.surface
    const nodes = surface.nodes
    const generation = surface.contentGeneration
    if (generation !== this.derivedGeneration) {
      this.derived = []
      this.derivedNodes = 0
      this.derivedGeneration = generation
    }
    for (const seq of nodes.slice(this.derivedNodes)) {
      const msg = this.deriveEventMessage(this.log[seq]!)
      if (msg) this.derived.push(msg)
    }
    this.derivedNodes = nodes.length
    return [...this.derived]
  }
```

纯尾部增长只算 O(新增节点)；replace 或消息投影使 `contentGeneration` 变化时整体重建。返回的数组每次是新快照，里面的 `Message` 对象共享且**深度冻结**——消费者无法通过它改动日志。

"model-visible means logged" 的字面证据在 agent loop：真正发给 LLM 的 `request.messages` 就是 `session.deriveMessages()`，没有任何旁路数组。surface 是把日志折叠成"当前可见消息序列"的派生视图（`packages/core/session/src/surface.ts`）：

```ts
function applySurfacePlan(
  state: SurfaceFoldState,
  plan: SurfacePlan | undefined,
): SurfaceFoldReplacement | undefined {
  if (plan?.kind === 'append') {
    state.nodes.push(plan.seq)
  } else if (plan?.kind === 'replace') {
    state.nodes.splice(plan.startIdx, plan.endIdx - plan.startIdx + 1, plan.seq)
    state.replaceGeneration += 1
    state.contentGeneration += 1
  } else if (plan?.kind === 'project') {
    for (const [seq, message] of plan.messages) state.projectedMessages.set(seq, message)
    state.projections.add(plan.projection)
    state.contentGeneration += 1
  }
```

压缩就以 `replace` 落地：checkpoint 消息替换一段旧节点，旧事件仍在 log 中（`packages/compaction/compaction-basic/src/region.ts`）：

```ts
  session.append('user/message', checkpointMessage, {
    surfaceOp: { op: 'replace', startSeq: start, endSeq: end },
    sourceEventSeqs: [startEvent.seq, summaryEvent.seq, ...shadowedSeqs],
  })
```

由于 replace 改变了可见序列，`start`/`end` 是 surface 位置而非数值 seq——替换后可见 seq 可以非单调。

## Projection Seam

`ctx.sessionProjections` 是可增生传播的投影 seam。一个投影单元声明 `init`（空日志状态）+ `apply`（纯转移）+ 可选 `wire`（前端视图），对不关心的事件必须返回**同一状态引用**以产生零下游工作（`packages/session/session-projection/src/index.ts`）：

```ts
export interface ProjectionDefinition<K extends string, S> {
  key: K
  stateSchema: ZodType<S>
  init(header: SessionHeader, inheritedEventCount: SessionLogOffset): NoInfer<S>
  apply(state: NoInfer<S>, event: SessionEvent): NoInfer<S>
```

`snapshot()` 把选中的投影视图取成带 `asOfSeq` 的快照：

```ts
  snapshot(session: Session, keys?: ProjectionKeySelection): ProjectionSnapshot {
    const values: Record<string, unknown> = {}
    for (const registration of this.registrations.values()) {
      if (registration.refs === 0) continue
      if (registration.def.wire === undefined) continue
      const cell = this.cellFor(registration, session)
      values[registration.def.key] = this.viewCell(registration, cell)
    }
    return { asOfSeq: cursorBefore(session.seq), values }
  }
```

AgentLoop 的 inbox、goal、preset、time-context 都靠这个 seam 把持久状态从日志 fold 出来。前端显示是"只读投影"，唯一数据源是 session 日志——这解释了为什么 DSH 的开发专注点可以放在"Session 文件该放什么"上。前端如何把 `session/event` 这条 live tail 经 gateway 推给浏览器，见 [Boot & Frontends](/docs/CS/AI/LLM/Agent/Product/DSH/BootAndFrontends.md)。

## Fork and Repair

`fork()` 复制一段前缀作为子会话 seed，并标记继承长度与 `isSeeded`（`packages/core/session/src/index.ts`）：

```ts
  fork(source: SessionForkSource, boundary?: SessionSeq, childSessionId?: SessionId): Session {
    const events = liveSource.snapshotEvents()
    const resolved = this._forkBoundary(liveSource.id, events, boundary)
    const seed = resolved === undefined ? [] : buildForkSeed(events, resolved)
    return this.create(childSessionId, {
      seed,
      inheritedEventCount: SessionLogOffset(resolved === undefined ? 0 : resolved + 1),
      meta: { isSeeded: true },
    })
  }
```

注意 `inheritedEventCount = resolved + 1` 只数**复制的源事件**（含 cut 处插入的 `{inherited:true}` marker）；`openTurnClosers` 生成的合成 tool result / step/turn closers 排在 marker 之后、不计入继承前缀。崩溃恢复用 `interruptedTurnClosers` 为打开的尾轮次补写 `turn/end`（`packages/core/session/src/repair.ts`）：

```ts
  // Close an open step before its turn.
  if (openStep !== null) {
    closers.push({ type: 'step/end', seq: SessionSeq(seq++), time, data: { turn: openTurn, step: openStep } })
  }
  closers.push({ type: 'turn/end', seq: SessionSeq(seq++), time, data: { turn: openTurn, reason: { kind: cause.kind } } })
```

这只对"已被后续 turn/start 封口的有限重启"插入缺失 turn/end；普通未封尾的中断仍由 handle 消费者修复。

## JSONL Generations and Exclusive Publication

JSONL 后端把每个事件写成一行（无尾换行，writer 补），压缩用拼接 zstd 帧容器（`packages/session/session-persistence-jsonl/src/format.ts`、`zstd.ts`）：

```ts
export function eventLine(event: SessionEvent): string {
  return JSON.stringify(sessionFormatCatalog.encodeCurrentEvent(event as unknown as SessionFormatEvent))
}
```

文件名按版本代际命名：v0 用 `session.jsonl`，vN≥1 用 `session.vN.jsonl`（`packages/session/session-format/src/filename.ts`）：

```ts
export function sessionFormatLogFilename(version: number): string {
  const generation = sessionFormatVersion(version, 'Session log generation version')
  return generation === 0 ? 'session.jsonl' : `session.v${generation}.jsonl`
}
```

读取永远选目录中数值最高的规范代际（`packages/session/session-persistence-jsonl/src/index.ts`）：

```ts
    const latest = generations.sort((left, right) => right.version - left.version)[0]
    if (latest === undefined) return undefined
    return {
      sourcePath: latest.path,
      sourceVersion: latest.version,
      currentPath: join(dir, generationLogFilename(sessionFormatCatalog.currentVersion, this.compression)),
    }
```

写入用**排他发布**——`fs.link(staged, currentPath)` 存在即返回 false，绝不覆盖已提交代际（`packages/session/session-persistence-jsonl/src/generation.ts`）：

```ts
  try {
    await internals.fs.link(staged, currentPath)
  } catch (error) {
    /* a non-collision filesystem error propagates unchanged. */
    if (isEEXIST(error)) return false
    throw error
  }
```

活会话对当前代际则是纯追加（`open(path,'a')`），部分写失败时 rollback 回原 size——因为留半截字节会产生重复 seq。净效果：历史格式文件永远保持原始字节与文件名，新读者把旧代际**迁移**成新的 v4 文件并排他发布，而非原地升级。

## The Adjacent Migration Chain

版本迁移由相邻步骤串成，每步强制 `to === from + 1`（`packages/session/session-format/src/chain.ts`）：

```ts
  if (to !== from + 1) {
    throw new SessionFormatError(`${migration.name} must declare adjacent v${from}->v${from + 1}`)
  }
```

catalog 静态装配四步 v0→v1→v2→v3→v4（`packages/session/session-format-catalog/src/generated.ts`）：

```ts
export const sessionFormatCatalogOptions: SessionFormatCatalogOptions = {
  currentVersion: 4,
  migrations: [
    sessionFormatV0ToV1,
    sessionFormatV1ToV2,
    sessionFormatV2ToV3,
    sessionFormatV3ToV4,
  ],
```

读取时若 storedVersion === currentVersion 直接走当前解码器、**不跑迁移**；否则用 `chain.createStream()` 流式串接各步，最后做当前版本的关系统一校验。

## Links

- [DSH 主入口](/docs/CS/AI/LLM/Agent/Product/DSH/DSH.md)
- [DSH Agent Loop](/docs/CS/AI/LLM/Agent/Product/DSH/AgentLoop.md)
- [DSH LLM Adapter & Context](/docs/CS/AI/LLM/Agent/Product/DSH/LlmAdapter.md)
- [DSH Subagent & Team](/docs/CS/AI/LLM/Agent/Product/DSH/SubagentTeam.md)
- [Compaction 理论](/docs/CS/AI/LLM/Agent/Theory/Compaction.md)

## References

1. [deepseek-ai/deepseek-harness（v0.2.2-rc.3）core/session](https://github.com/deepseek-ai/deepseek-harness/tree/v0.2.2-rc.3/packages/core/session)
2. [架构文档 — Session log](https://github.com/deepseek-ai/deepseek-harness/blob/v0.2.2-rc.3/docs/architecture.md)
3. [DSH 的宝藏之一：Session 持久化的设计](https://mp.weixin.qq.com/s/uH3vuY9nNCmp-q4yUtRRYA)
