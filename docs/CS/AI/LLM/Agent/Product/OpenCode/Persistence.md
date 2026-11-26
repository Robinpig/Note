> 版本基线：v1.19.5（`E:/Projects/opencode-1.19.5` release 源码快照）。本文聚焦 **EventV2 + 投影（Projector）** 这套 V2 持久化机制（`packages/core/src/event.ts`、`packages/core/src/session/`），V1 的 `message`/`part` 表与文件系统 JSON 存储作为对照。

## Introduction

OpenCode 的会话持久化是一次 Event Sourcing 重构：**durable 事件是唯一的权威记录，投影表是可重建的读模型**。用户 prompt、文本增量、工具状态、压缩摘要全部先写成不可变的 `EventV2` 事件，在同一事务里由 projector 投影成可查询的消息行；每轮 runner 再从投影表重建上下文。这套设计让"状态可重建、可跨进程同步、owner 栅栏可分离"成为可能。

几个反直觉点：

- **V2 的 text/tool 事件不写 `part` 表**，而是增量投影进 `session_message.data` 这一个 JSON 列的 `content` 数组；`message`/`part` 两张表是旧 V1 事件的投影，两套并存。
- **seq 从 0 开始**（`latest` 初始 -1），不是 1。
- **owner 不匹配默认静默丢弃**而非报错，只有 `strictOwner: true` 才 die；`claim` 可被后来者覆盖。
- **`packages/opencode/src/storage/` 与 SQLite 无关**，它是文件系统 JSON KV；真正的 DB 后端在 `packages/core/src/database/`。

## The EventV2 Data Model

一条 durable event 的 shape 定义在 `packages/schema/src/event.ts`。`Definition` 携带可选的 durable 元信息（`version` + `aggregate` 字段名），`aggregate` 不是值而是 data 里的字段名（session 事件统一为 `"sessionID"`）：

```typescript
export type Definition<Type extends string = string, DataSchema extends Schema.Codec<unknown, unknown> = Schema.Codec<unknown, unknown>> = Schema.Top & {
  readonly type: Type
  readonly durable?: { readonly version: number; readonly aggregate: string }
  readonly data: DataSchema
}

export type Payload<D extends Definition = Definition> = {
  readonly id: ID
  readonly type: D["type"]
  readonly data: Data<D>
  readonly durable?: { readonly aggregateID: string; readonly seq: number; readonly version: number }
  readonly location?: Location.Ref
  readonly metadata?: Record<string, unknown>
}
```

`id` 是 `evt_` 前缀的 branded string；落库的 `type` 是 `versionedType(type, version) = "${type}.${version}"`。`owner` 不属于事件本身，而在 `EventSequenceTable.owner_id`。

`publish` 补上 id/location/metadata，交给 `publishEvent`；durable 事件走 `commitDurableEvent`，成功后再 `notify`：

```typescript
function publish<D extends Definition>(definition: D, data: Data<D>, options?: PublishOptions) {
  return Effect.gen(function* () {
    const serviceLocation = Option.getOrUndefined(yield* Effect.serviceOption(Location.Service))
    const location = options?.location ?? (serviceLocation
      ? { directory: serviceLocation.directory, workspaceID: serviceLocation.workspaceID }
      : undefined)
    return yield* publishEvent(definition, {
      id: options?.id ?? ID.create(),
      ...(options?.metadata ? { metadata: options.metadata } : {}),
      type: definition.type,
      ...(location ? { location } : {}),
      data,
    } as Payload<D>, options?.commit)
  })
}
```

`PublishOptions.commit`（`core/src/event.ts`）是"本地操作投影"——注释明确：*Local operational projection committed atomically with a new durable event. Not replayed or serialized.*

## Two Tables, Optimistic Sequencing

`packages/core/src/event/sql.ts` 定义两张表：

```typescript
export const EventSequenceTable = sqliteTable("event_sequence", {
  aggregate_id: text().notNull().primaryKey(),
  seq: integer().notNull(),
  owner_id: text(),
})

export const EventTable = sqliteTable("event", {
  id: text().$type<EventV2.ID>().primaryKey(),
  aggregate_id: text().notNull().references(() => EventSequenceTable.aggregate_id, { onDelete: "cascade" }),
  seq: integer().notNull(),
  type: text().notNull(),
  data: text({ mode: "json" }).$type<Record<string, unknown>>().notNull(),
}, (table) => [
  uniqueIndex("event_aggregate_seq_idx").on(table.aggregate_id, table.seq),
  index("event_aggregate_type_seq_idx").on(table.aggregate_id, table.type, table.seq),
])
```

- **`event_sequence`**：每个 aggregate 一行，存当前 seq 游标与 owner_id，是并发控制点与所有权栅栏，本身不是事件日志。
- **`event`**：append-only 日志，`(aggregate_id, seq)` 唯一索引保证同 aggregate 内 seq 不重复。

seq 分配在 `db.transaction(..., { behavior: "immediate" })`（SQLite `BEGIN IMMEDIATE` 拿写锁）里：`seq = input?.seq ?? latest + 1`，`latest = row?.seq ?? -1`，所以第一个事件 seq = 0。projector 与 commit 钩子都在同一事务内执行，然后才 upsert sequence 与 insert event——投影与事件原子提交：

```typescript
for (const projector of list) {
  yield* projector(committed)
}
if (commit) yield* commit(seq)
yield* db.insert(EventSequenceTable).values([{ aggregate_id: aggregateID, seq, owner_id: input?.ownerID }])
  .onConflictDoUpdate({ target: EventSequenceTable.aggregate_id, set: { seq, /* ... */ } })
  .run()
```

replay 的幂等判定：`input.seq <= latest` 时用 `id/type/data`（deep equal）比对，相同则跳过并可认领 owner，不同则 die `Replay diverged`；`input.seq !== latest + 1` 则 die `Sequence mismatch`。`latestSequence` 只读 `EventSequenceTable.seq`，缺失返回 -1，被 promotion cutoff 与 context epoch 的 baselineSeq 使用。

## Projectors: Events to Rows

投影器通过 `events.project(definition, fn)` 注册，在 durable 事件提交事务内同步调用。session 投影器集中在 `core/src/session/projector.ts`。`PromptAdmitted` 与 `Prompted` 分别投影 inbox 行的两个 seq：

```typescript
yield* events.project(SessionEvent.Prompted, (event) =>
  Effect.gen(function* () {
    yield* SessionInput.projectPrompted(db, {
      id: event.data.messageID, sessionID: event.data.sessionID,
      prompt: event.data.prompt, delivery: event.data.delivery,
      timeCreated: event.data.timestamp, promotedSeq: event.durable.seq,
    })
    yield* run(db, event)
  }),
)
yield* events.project(SessionEvent.PromptAdmitted, (event) =>
  Effect.gen(function* () {
    yield* SessionInput.projectAdmitted(db, {
      admittedSeq: event.durable.seq, id: event.data.messageID, /* ... */
    })
  }),
)
```

`projectAdmitted` insert 一行、`promoted_seq` 留 null；`projectPrompted` 把 `promoted_seq` 更新为该事件 seq（`WHERE promoted_seq IS NULL`），找不到行时 fallback insert 且两个 seq 取同一个值。命名看似颠倒：实际时序是先 admit（admitted_seq 小）后 promote（promoted_seq 大）。

所有 text/tool/step 事件走 `run(db, event)`。它构造一个 DB-backed Adapter（`getCurrentAssistant` 从 `SessionMessageTable` 按 `seq DESC` 读行并 decode，`appendMessage`/`updateMessage` 写回），交给纯函数 `SessionMessageUpdater.update(adapter, event)`：

```typescript
"session.next.text.delta": (event) => {
  return updateOwnedAssistant(event.data.assistantMessageID, (draft) => {
    const match = latestText(draft, event.data.textID)
    if (match) match.text += event.data.delta
  })
},
"session.next.tool.called": (event) => {
  return updateOwnedAssistant(event.data.assistantMessageID, (draft) => {
    const match = latestTool(draft, event.data.callID)
    if (match) {
      match.time.ran = event.data.timestamp
      match.state = castDraft(SessionMessage.ToolStateRunning.make({
        status: "running", input: event.data.input, structured: {}, content: [],
      }))
    }
  }),
},
```

`updateOwnedAssistant` 用 immer `produce` 就地修改 assistant 行的 `content` 数组（text/tool/reasoning item），再由 adapter 写回。一条 V2 assistant 消息就是 `session_message` 的一行，`data` 是 JSON（含完整 content 数组，delta 累加、tool state 从 pending→running→completed/error），行的 `seq = event.durable.seq`。

## Replay, Claim and Owner

owner 存在 `EventSequenceTable.owner_id`。语义由测试与调用点佐证：

```typescript
if (input?.strictOwner && row?.ownerID && row.ownerID !== input.ownerID) {
  yield* Effect.die(new InvalidDurableEventError({
    type: event.type,
    message: `Replay owner mismatch for aggregate ${aggregateID}: expected ${row.ownerID}, got ${input.ownerID ?? "none"}`,
  }))
}
// ... 幂等跳过分支中可认领 owner（row?.ownerID == null 时）
if (input && row?.ownerID && row.ownerID !== input.ownerID) {
  return  // 非 strict：静默丢弃
}
```

- **owner 是 aggregate 级栅栏**：`claim(sessionID, workspaceID)` 把 session 归给某 workspace，session warp/steal 时调用（注释："claim this session so any future events coming from the old workspace are ignored"）。
- **非 strict 不匹配 → 静默 `return`**（事件被丢弃、不投影、不写库）；`strictOwner: true` 不匹配 → die。同步端点用 `replayAll(payload, { ownerID, strictOwner: true })`，ownerID 来自 `InstanceState.workspaceID`。
- **owner 只在未被认领时回填**（`row?.ownerID == null`），但 `claim` 本身可覆盖已有 owner（后 claim 者胜）。

owner 与集群执行所有权是两套东西：owner 只存在于 `EventSequenceTable`，事件行不带 owner 字段；runner 的执行所有权是进程内存的 coordinator（见 [SessionLoop](/docs/CS/AI/LLM/Agent/Product/OpenCode/SessionLoop.md)）。

## History Reconstruction

`SessionHistory.entriesForRunner`（`core/src/session/history.ts`）从投影表读行、按 seq 排序、结合 compaction 与 epoch baselineSeq 过滤再 decode：

```typescript
export const entriesForRunner = Effect.fn("SessionHistory.entriesForRunner")(function* (
  db: DatabaseService, sessionID: SessionSchema.ID, baselineSeq: number,
) {
  const rows = yield* messageRows(db, sessionID, yield* latestCompaction(db, sessionID), baselineSeq)
  return yield* Effect.forEach(rows, (row) =>
    decodeMessageRow(row).pipe(Effect.map((message) => ({ seq: row.seq, message }))),
  )
})
```

`messageRows` 的过滤：普通消息取 `>= compaction.seq`；system 类消息（含 `ContextUpdated` 增量）只取 `> baselineSeq`，避免重复注入旧 baseline。**每轮 reload 的原因**是 text/tool delta 是增量投影进 content 的，assistant 消息在 step 进行中被反复 update；runner 逐步循环，每步重新读投影表才能拿到最新 content 与刚提升的 user prompt。再用 `EventV2.latestSequence` 作 promotion cutoff，保证只提升该轮开始前的 admitted 输入。详见 [Context](/docs/CS/AI/LLM/Agent/Product/OpenCode/Context.md)。

## Storage Layers and DB Backends

四层职责：

- **`effect-drizzle-sqlite`**：通用 Drizzle + Effect 的 SQLite 抽象，事务是手写 `begin/savepoint/commit/rollback`。
- **`effect-sqlite-node`**：独立的 Node SQLite `SqlClient`（`node:sqlite` 的 `DatabaseSync`），仅列为依赖，core 源码未见直接 import。
- **`core/database`**：`Database.Service` 组装层——选 `EffectDrizzleSqlite.makeWithDefaults()`、设 PRAGMA（`journal_mode = WAL`、`synchronous = NORMAL`、`busy_timeout = 5000`、`foreign_keys = ON`）、跑 migration、决定库文件路径：

```typescript
export function path() {
  if (Flag.OPENCODE_DB) { /* env 覆盖 */ }
  if (["latest", "beta", "prod"].includes(InstallationChannel) || /* ... */)
    return join(Global.Path.data, "opencode.db")
  return join(Global.Path.data, `opencode-${InstallationChannel.replace(/[^a-zA-Z0-9._-]/g, "-")}.db`)
}
```

- **`opencode/storage`**：不是 SQLite，而是文件系统 JSON KV（根目录 `~/.local/share/opencode/storage/`），带自己的 MIGRATIONS（迁移旧 `project/session/message/part` 目录结构）、marker 文件记录进度、`TxReentrantLock` 加锁。

Bun/Node 切换通过 `core/package.json` 的条件导出：`#sqlite` 在 bun 下解析到 `sqlite.bun.ts`、node 下到 `sqlite.node.ts`。migration（`core/src/database/migration.ts`）用 `Semaphore(1)` 串行，根据 `sqlite_master` 分三种情况；空库跑 `schema.gen.ts` 的 `up()` 并把所有 migration id 标记完成，自建 `migration` journal 兼容旧 Drizzle 表。

数据目录 `~/.local/share/opencode/`（Linux；由 xdg-basedir 决定）下有：`opencode.db`（或 channel 变体）、`auth.json`、`mcp-auth.json`、`tool-output/`、`storage/`、`plans/`、`log/`、`repos/`。

## Links

- [SessionLoop](/docs/CS/AI/LLM/Agent/Product/OpenCode/SessionLoop.md) / [Context](/docs/CS/AI/LLM/Agent/Product/OpenCode/Context.md) / [Server](/docs/CS/AI/LLM/Agent/Product/OpenCode/Server.md)
- [Tools](/docs/CS/AI/LLM/Agent/Product/OpenCode/Tools.md) / [Provider](/docs/CS/AI/LLM/Agent/Product/OpenCode/Provider.md) / [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)

## References

1. [core/event.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/core/src/event.ts)
2. [core/event/sql.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/core/src/event/sql.ts)
3. [session/projector.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/core/src/session/projector.ts)
4. [session/history.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/core/src/session/history.ts)
5. [core/database/database.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/core/src/database/database.ts)
