## Introduction

> 版本基线：v0.7.7（本地源码 E:/Projects/cc-haha-0.7.7）

cc-haha 在多 Agent 协作上做了**两层东西**，常被营销打包成「Agent Teams + Dynamic Workflow」，但二者机制不同、需分开记录（Claude Code 的 agent teams 以 mailbox 架构在终端呈现，见 [ClaudeCode/Subagents](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Subagents.md)）。底层 subagent 机制（独立上下文、定义方式、agent 间消息信任边界）与 Claude Code 同源，本页讲 cc-haha 在 GUI / 引擎上叠加的协作层。

> [!NOTE]
> 此前本页曾把「Dynamic Workflow」标为营销夸大——**已据引擎源码纠正**：桌面 Agent Teams UI 确实是引擎快照的纯派生渲染，但引擎侧 `WorkflowTool` 是真实的「模型写并运行编排脚本」机制。两层入口不同，勿混为一谈。

### 两层机制

1. **Agent Teams（桌面可视化器）**：把引擎既有 agent-teams 的**快照**渲染成 GUI workbench（成员 / 任务 / 通信 feed / 依赖泳道画布 + 回放）。桌面层无写回引擎的编排逻辑。
2. **Dynamic Workflow（引擎真功能）**：`WorkflowTool` 让模型**现场编写编排脚本并在 Node `vm` 沙箱里运行**，脚本调用 `agent()` / `parallel()` / `pipeline()` / `phase()` 派生 subagent。这是真实的动态编排能力，非营销空话。

## Agent Teams UI Is a Live Visualizer of the Engine Snapshot

引擎推送 `snapshots` 流，**快照流是唯一真相源**。`desktop/src/components/agentTeams/AgentTeamsWorkbench.tsx` 的组件注释在 v0.7.7 扩充为「live 与 replay 共用同一条流、回放只是移动游标」，所有视图不能各讲各的故事：

```tsx
/**
 * The full Agent Teams surface. The snapshot stream is the only source of
 * truth for both live mode and replay; replay merely moves the cursor through
 * that same stream, so the canvas, counters, member history and communication
 * feed cannot drift into different stories.
 */
export function AgentTeamsWorkbench({ sessionId }: { sessionId: string }) {
  const t = useTranslation()
  const timeline = useTeamStore((state) => state.workbenchesBySession[sessionId])
  const historyIndex = useTeamStore(
    (state) => state.workbenchHistoryIndexBySession[sessionId] ?? null,
  )
```

GUI 渲染细节（均为快照上的派生计算 / 纯排版）：

- **成员（members）**：`TeamMember` 含模型 / 工具 / system prompt，由可视化 SubAgent 管理器配置；`getMemberAvatarKey` 按 role 正则匹配职业头像。
- **任务（tasks）**：`TeamWorkbenchTask`，含 `blockedBy` 依赖。
- **依赖泳道画布**：`layoutWorkbenchTasks` 用 `taskDepths`（按 `task.blockedBy` 求最长依赖路径得到 `depth`）把任务分入纵向 lane，`AgentTeamsCanvas.tsx` 生成依赖 DAG 边 `dependencyPath`。`desktop/src/components/agentTeams/agentTeamsModel.ts`：

```ts
export function layoutWorkbenchTasks(
  tasks: TeamWorkbenchTask[],
  requestedWidth: number,
): WorkbenchLayout {
  const sortedTasks = tasks
    .map((task, index) => ({ task, index }))
    .sort((left, right) => (
      compareTaskIds(left.task.id, right.task.id) || left.index - right.index
    ))
    .map(({ task }) => task)
  const depths = taskDepths(sortedTasks)
  const byLayer = new Map<number, TeamWorkbenchTask[]>()

  for (const task of sortedTasks) {
    const depth = depths.get(task.id) ?? 0
    const layer = byLayer.get(depth)
    if (layer) layer.push(task)
    else byLayer.set(depth, [task])
  }
```

- **通信 feed**：`classifyMessage` 分 `assignment` / `peer` / `report` / `system`，画布用 `flightRoutes` 画三类「航班」动画线。
- **回放时间轴**：v0.7.7 由 `workbenchHistoryIndexBySession` + `setWorkbenchHistoryIndex` + `snapshotWithHistoricalMembers` 实现 live 跟随与历史回放（旧笔记的 `replayFrameDelay` / `seekTimeline` 在该版本 `agentTeamsModel.ts` 已不再命中）。

## Dynamic Workflow Is a Real Engine Feature

营销所说的「Dynamic Workflow」不是空话——引擎侧 `WorkflowTool`（`src/tools/WorkflowTool/WorkflowTool.ts`）+ `src/utils/workflows/*` 实现了一套**模型创作的 VM 编排引擎**：

- **模型写脚本**：`WorkflowTool` 的 `script` 参数要求以 `export const meta = { name, description, phases }`（纯字面量）开头，正文用 `agent()` / `parallel()` / `pipeline()` / `phase()`。权限提示原文即「Claude wants to run a **dynamic workflow**, which can spawn many subagents and use a large number of tokens」。
- **VM 沙箱执行**：`compileWorkflowScript` 编译为 Node `vm.Script`，再由 `runInContext(sandbox.context, {timeout})` 在隔离上下文运行。为保证 resume 确定性，`Date` / `Math.random` 被显式禁用，动态 `import()` 也被拒绝。`src/utils/workflows/compile.ts`：

```ts
 *
 * A resumed run replays cached agent results in start order. A script whose
 * control flow depends on wall-clock time or randomness would take a different
 * branch on replay and silently consume the wrong cache entries, so both are
 * made to throw at the first call rather than shimmed into something plausible.
 *
 * Installed on the context (not prepended to the script) so `globalThis.Date`
 * and an aliased `const r = Math.random` are covered too.
 */
export function installDeterminismGuards(context: vm.Context): void {
  vm.runInContext(
    `(() => {
      const dateMessage = ${JSON.stringify(WORKFLOW_DATE_BANNED_MESSAGE)}
      const randomMessage = ${JSON.stringify(WORKFLOW_RANDOM_BANNED_MESSAGE)}
      const RealDate = Date
      globalThis.Date = new Proxy(RealDate, {
        construct(target, argv, newTarget) {
          if (argv.length === 0) throw new Error(dateMessage)
          return Reflect.construct(target, argv, newTarget === undefined ? target : newTarget)
        },
        get(target, prop, receiver) {
          if (prop === 'now') throw new Error(dateMessage)
          return Reflect.get(target, prop, receiver)
        },
      })
      Math.random = () => {
        throw new Error(randomMessage)
      }
    })()`,
    context,
    { filename: 'workflow-guards.js' },
  )
}
```

- **派生 subagent**：`harness.ts` 的 `agent(prompt, opts)` 真正 spawn 一个 subagent（可 `isolation:'worktree'`），受 `WORKFLOW_MAX_AGENTS` 硬上限约束；`parallel()` / `pipeline()` / `phase()` 提供并发 / 流水线 / 分阶段原语。
- **可恢复**：`resumeFromRunId` 让已完成且 `(prompt, opts)` 未变的 `agent()` 直接命中缓存、只重跑改动或新增的调用。恢复协议细节见下。

### Resume 缓存协议与确定性 VM（引擎内部）

`WorkflowTool` 的恢复不是「保存整个 VM 状态」，而是 **journal + 链式缓存键 + 一次性短路** 的确定性重放——这要求 VM 内不能出现真实时间或随机性，否则重放会跑偏。

- **Journal（执行日志）**：`WorkflowJournal` 是 append-only JSONL，每个 subagent 在 spawn 前写 `started` 行、返回后写 `result` 行；`journal.load()` 读回时遇截断 / 损坏的尾部行直接跳过（最坏只多跑一个 agent）；写入经 promise 链串行化，运行结束前必须 `flush()` 落盘。`src/utils/workflows/journal.ts`：

```ts
/**
 * One line per agent lifecycle transition, appended as the run progresses.
 *
 * `started` is written before the subagent is spawned and `result` after it
 * returns. Resume needs both: an agent that has a `started` line but no
 * `result` was in flight when the run stopped, which is what makes every agent
 * after it re-run instead of replaying.
 */
export type WorkflowJournalEntry =
  | { type: 'started'; key: string; agentId: string }
  | { type: 'result'; key: string; agentId: string; result: unknown }

export type WorkflowJournalSnapshot = {
  /** key → the cached return value of a completed agent. */
  results: Map<string, { agentId: string; result: unknown }>
  /** key → agent ids that started but never produced a result. */
  started: Map<string, string[]>
}
```

- **链式缓存键**：`workflowCacheKey = previousKey|prompt|opts`，即「上一条的 key + 本次 prompt + opts」——**调用顺序本身参与缓存身份**，故循环里两个相同的 `agent('review')` 不会共用缓存，中途插入一个调用也会使后续全部失效。
- **一次性短路（replay 只重放剩余）**：`harness.agent()` 命中 `journalSnapshot.results` 就直接返回 `cached.result` 并标记 `cached:true`；**首个未命中立即置 `cacheExhausted=true`，此后所有 agent 一律实跑**，因首个 miss 之后的顺序 / 结果已不可信。`src/utils/workflows/harness.ts`：

```ts
    const cacheKey = journal
      ? workflowCacheKey(prompt, opts, previousCacheKey)
      : undefined
    if (cacheKey !== undefined) previousCacheKey = cacheKey

    if (cacheKey !== undefined && !cacheExhausted) {
      const cached = journalSnapshot?.results.get(cacheKey)
      if (cached !== undefined) {
        const now = Date.now()
        emit({
          type: 'workflow_agent',
          index,
          label,
          state: 'done',
          phaseIndex,
          phaseTitle,
          model,
          agentId: cached.agentId,
          startedAt: now,
          lastProgressAt: now,
          cached: true,
          promptPreview,
          resultPreview: clip(
            coerceToString(cached.result),
            WORKFLOW_PREVIEW_MAX_CHARS,
          ),
        })
        return cached.result
      }
      // First miss: every later agent started after this one, so none of their
      // cached results are valid any more.
      cacheExhausted = true
    }
```

- **确定性 VM 沙箱**：每次运行重建 `vm.createContext(Object.create(null), { codeGeneration: { strings:false, wasm:false } })`。`compile.ts` 的 `installDeterminismGuards` 把无参 `new Date()` / `Date.now` / `Math.random` 全部改为抛错，动态 `import()` 也被 `vm.Script` 的 `importModuleDynamically` 钩子拒绝。**主机对象绝不暴露给脚本**：`agent` / `parallel` / `pipeline` / `log` / `phase` / `workflow` / `budget` / `console` / `setTimeout` / `args` 全经 VM 内箭头重包一层闭包，避免脚本借 `fn.constructor` 摸到 `Function` 逃出 VM；`budget` / `console` / timers 也在 VM 内重建。`src/utils/workflows/runtime.ts`：

```ts
  // codeGeneration off: `eval` and `new Function` inside the script would
  // otherwise reconstruct anything the sandbox withholds.
  const context = vm.createContext(Object.create(null) as object, {
    codeGeneration: { strings: false, wasm: false },
  })
  installDeterminismGuards(context)

  const evalInVm = <T>(source: string): T =>
    vm.runInContext(source, context, { filename: 'workflow-bridge.js' }) as T

  const awaitInVm = evalInVm<(value: unknown) => Promise<{ v: unknown }>>(
    '(async v => ({ __proto__: null, v: await v }))',
  )
```

resume 时脚本重解析 + 重编译，同一脚本文本 + 同一缓存结果 + 无真实时间 / 随机 = 重放一致。

- **嵌套工作流严格一层**：`workflow()` 全局调 `runNestedWorkflow`，否则抛 "not available"；子工作流复用同一 `runId` / 同一 `journal` / 同一并发计数 / 同一 token budget，但**子工作流的 `workflow()` 被置 `undefined`**，再嵌套一层即抛错。
- **ultracode 模式**：并非第六档 effort，而是 **`xhigh` effort + 常驻 workflow-orchestration 标志**，仅当 `areWorkflowsEnabled()` 且模型支持 xhigh 时启用；自动模式的单次 consent（`autoModeConsent.ts`）抑制每次启动弹窗。`src/utils/workflows/ultracode.ts`：

```ts
/**
 * Ultracode: xhigh effort plus standing dynamic-workflow orchestration.
 *
 * Not a sixth effort level — it is `xhigh` with a flag beside it. Keeping it
 * out of `EffortLevel` matters: every model-capability check, settings write,
 * and picker row already reasons about the five real levels, and a sixth would
 * have to be special-cased in all of them to mean "xhigh, but also…".
 */

import { modelSupportsXHighEffort } from '../effort.js'
import { areWorkflowsEnabled } from './enabled.js'

export const ULTRACODE_EFFORT_ARG = 'ultracode'

/** Effort ultracode resolves to once the flag is recorded separately. */
export const ULTRACODE_EFFORT_LEVEL = 'xhigh' as const
```

#### 硬上限常量（已核实）

引擎对脚本与派生 subagent 设了明确护栏（`src/utils/workflows/constants.ts`）：

```ts
/** Hard cap on `agent()` calls per run — a backstop against runaway loops. */
export const WORKFLOW_MAX_AGENTS = 1000

/** A single parallel()/pipeline() call may not fan out wider than this. */
export const WORKFLOW_MAX_FANOUT = 4096

/** Scripts larger than this are rejected before parsing (512 KiB). */
export const WORKFLOW_SCRIPT_MAX_BYTES = 524_288

/**
 * Wall-clock budget for the *synchronous* portion of the script. Awaiting an
 * agent does not consume it; a `while (true) {}` with no await does.
 */
export const WORKFLOW_SYNC_TIMEOUT_MS = 30_000

/** An agent that emits no progress for this long is reported as stalled. */
export const WORKFLOW_AGENT_STALL_MS = 180_000
```

| 常量 | 值 | 含义 |
| :-- | :-- | :-- |
| `WORKFLOW_MAX_AGENTS` | **1000** | 单次 run 内 `agent()` 调用硬上限，防失控循环 |
| `WORKFLOW_MAX_FANOUT` | **4096** | 单次 `parallel()` / `pipeline()` 扇出上限 |
| `WORKFLOW_SCRIPT_MAX_BYTES` | **524288**（512 KiB） | 脚本超过此值解析前即拒绝 |
| `WORKFLOW_SYNC_TIMEOUT_MS` | 30000 | 脚本同步段的墙钟预算（`await` agent 不消耗） |
| `WORKFLOW_AGENT_STALL_MS` | 180000 | subagent 无进展判定 stalled 的阈值 |
| `getWorkflowConcurrency()` | `min(16, max(2, cpu-2))` | 在途 agent 并发上限，按 CPU 数避免笔记本上 500 条 model stream |

> 一个真实坑：`WORKFLOW_AGENT_CAP_MESSAGE` 揭示——若 `budget.total` 为 `null`，`budget.remaining()` 返回 **Infinity**，带 `remaining()` 的循环永不终止，最终撞上 `WORKFLOW_MAX_AGENTS=1000` 上限。写循环应设硬迭代上限或传入 token budget。`src/utils/workflows/constants.ts`：

```ts
export const WORKFLOW_AGENT_CAP_MESSAGE =
  `Workflow agent() call cap reached (${WORKFLOW_MAX_AGENTS}). This usually means a loop using ` +
  'budget.remaining() never terminates because no token budget was set — remaining() returns ' +
  'Infinity when budget.total is null. Add a hard iteration cap to the loop, or pass a token budget.'
```

> 注意：Desktop 的 Agent Teams 画布可视化的是引擎 agent-teams 快照，而 `WorkflowTool` 的 `agent()` 调用也会产生 `workflow_agent` 事件，很可能在同一个画布上呈现。但二者入口不同——前者是 composer 的「Agent Team 开关」（本质只是给消息前缀注入一段指令块 `<agent-team-request>...`），后者是模型主动调用 `Workflow` 工具。

## WorkflowTool: 模型侧入口

引擎段已覆盖 VM / 缓存协议 / 硬上限；本节点明**模型调用 `Workflow` 工具这一层**的契约与边界（`src/tools/WorkflowTool/WorkflowTool.ts`、`launchWorkflow.ts`、`prompt.ts`）。

### 输入 schema 与解析优先级
- `z.strictObject` 五字段：`script`（≤512 KiB，可选）、`scriptPath`（磁盘脚本路径）、`name`（预定义工作流，内置或 `.claude/workflows/`）、`args`（暴露为全局 `args`，verbatim，传 JSON 值而非字符串）、`resumeFromRunId`（`^wf_[a-z0-9-]{6,}$`）。`src/tools/WorkflowTool/WorkflowTool.ts`：

```ts
    resumeFromRunId: z
      .string()
      .regex(/^wf_[a-z0-9-]{6,}$/)
      .optional()
```

- 解析优先级 `scriptPath > name > script`：`scriptPath` 胜出以便字节级重放编辑过的脚本；`name` 解析后**不给 scriptPath**（避免运行写回用户文件、且 resume 应从实际运行内容而非文件）；三者皆无则报错。
- `title` / `description` 被显式忽略——元数据写在脚本头部的 `meta`。

### 权限模型（checkPermissions）
- 自动 allow 三情形：权限模式 `bypassPermissions`、非交互会话（`isNonInteractiveSession`）、`ultracode === true`（常驻编排指令，每轮弹窗等价于每轮弹）。
- `auto` 模式：若 `hasAcceptedWorkflowsInAutoMode()` 则一次性 consent 后 allow。
- 否则按 `name` 查 allow/deny 规则（`getRuleByContentsForTool`）；都不命中则 `ask`，并附 `addRules` 建议把该 workflow name 写入 localSettings 设为 allow。
- 弹窗文案明确「spawn many subagents and use a large number of tokens」。

### call 流程（异步，不 spawn 子进程）
1. `getWorkflowsDisabledReason()` 非 null 直接 throw（见启用 gate）。
2. `resolveScript(input)` 按上述优先级解析。
3. `prepareWorkflowScript(script)` → `{ ok, meta, vmScript }`，`meta` 为脚本头部纯字面量，`vmScript` 为编译后的 VM 脚本（衔接确定性 VM）。
4. `launchWorkflow({...})`：写 `transcriptDir` / `scriptPath`、生成 `wf_` runId（`input.resumeFromRunId ?? createWorkflowRunId()`），通过 **task 系统**（`createTask` / `enqueueWorkflowNotification`）异步调度引擎——**不是直接 `child_process.spawn`**，引擎在独立任务上下文运行，主线程立即返回。`src/tools/WorkflowTool/WorkflowTool.ts`：

```ts
    const workflowRunId = input.resumeFromRunId ?? createWorkflowRunId()
    const taskId = generateTaskId('local_workflow')

    const launched = launchWorkflow({
```

5. 返回 `async_launched` + `taskId` + `runId` + `transcriptDir` + `scriptPath`（`maxResultSizeChars = 100_000`）。

### 启用 gate 与规模建议（enabled.ts）
- **无 feature flag**：启用完全由 settings 驱动。`getWorkflowsDisabledReason()` 三来源：`CLAUDE_CODE_DISABLE_WORKFLOWS`（env）、`policySettings.disableWorkflows`（managed）、`disableWorkflows === true` 或 `enableWorkflows === false`（settings）；`areWorkflowsEnabled()` 即该 reason 为 null。`src/utils/workflows/enabled.ts`：

```ts
export function getWorkflowsDisabledReason(): WorkflowsDisabledReason | null {
  if (isEnvTruthy(process.env.CLAUDE_CODE_DISABLE_WORKFLOWS)) return 'env'
  if (getSettingsForSource('policySettings')?.disableWorkflows === true) {
    return 'managed'
  }
  const merged = getSettings_DEPRECATED()
  if (merged.disableWorkflows === true) return 'settings'
  // `enableWorkflows: false` is the /config toggle's off position. It is a
  // separate key from `disableWorkflows` so an org can hard-disable while a
  // user's toggle stays untouched underneath.
  if (merged.enableWorkflows === false) return 'settings'
  return null
}

export function areWorkflowsEnabled(): boolean {
  return getWorkflowsDisabledReason() === null
}
```

- `ultracode` 关键词触发：仅交互式会话（非 `-p` / SDK / 计划任务 / PR 评论），默认开、`/config` 可关；特性本身禁用时关键词无意义（`isWorkflowKeywordTriggerEnabled`）。
- **规模建议（guideline，非硬限）**：`unrestricted / small / medium / large` → agent 目标 `null / 5 / 15 / 50`；在 prompt 注入让模型按口味定规模，settings 文件优先于 `/config` 选择。`src/utils/workflows/enabled.ts`：

```ts
/** Agent count each guideline asks Claude to aim for. Advice, not a cap. */
export const WORKFLOW_SIZE_AGENT_TARGETS: Record<
  WorkflowSizeGuideline,
  number | null
> = {
  unrestricted: null,
  small: 5,
  medium: 15,
  large: 50,
}
```

- **大 workflow 预警（advisory，不阻塞）**：`scheduledAgents > 25` 或 token `> 1.5M`（每 agent 假设 70k）时弹「Large workflow」提示，供用户在 `/workflows` 中止；ultracode 下抑制（已 opt-in 大规模）。

### resume 协议（模型侧视角）
- 输出含 `runId`；中断 / 被杀 / 改脚本后用 `Workflow({ scriptPath, resumeFromRunId })` 重放：最长未变前缀的 `agent()` 瞬时命中缓存，首个改动 / 新增调用及其之后实跑。
- 同一脚本 + 同一 `args` → 100% 缓存命中。
- 诊断空 / 异常结果：读 `<transcriptDir>/journal.jsonl`（记录每个 agent 实际返回值）。

## Teammate Tools: Team Lifecycle

区别于 [Dynamic Workflow](#dynamic-workflow-is-a-real-engine-feature) 引擎，以下是模型可**直接调用**的团队管理工具（`isAgentSwarmsEnabled()` 总开关）：

| 工具 | 文件 | 关键语义 |
|---|---|---|
| `TeamCreate` | `TeamCreateTool.ts` | 1 leader 只能管 1 team；写 teamFile 到磁盘；可选 `plan` 草稿评审 |
| `TeamPlan` | `TeamPlanTool.ts` | `get` / `replace` / `submit` + `expected_revision` 乐观锁；`submit` 后暂停等人类审批 |
| `TeamDelete` | `TeamDeleteTool.ts` | 有 active teammate 时拒绝，要求先 `requestShutdown` |
| `SendMessage` | `SendMessageTool.ts` | teammate 间通信（见下节） |
| `ListPeers` | `ListPeersTool.ts` | **`@generated stub`** — ant-internal feature-gated 占位，公开 build DCE 后不执行 |

要点：

- **1 leader 1 team**：`TeamCreate` 检查 `appState.teamContext?.teamName`，已存在则抛错要求先 `TeamDelete`。`src/tools/TeamCreateTool/TeamCreateTool.ts`：

```ts
    // Check if already in a team - restrict to one team per leader
    const appState = getAppState()
    const existingTeam = appState.teamContext?.teamName

    if (existingTeam) {
      throw new Error(
        `Already leading team "${existingTeam}". A leader can only manage one team at a time, and this team can take the new work: message its members with SendMessage, or add members with the Agent tool (team_name: "${existingTeam}"). Use TeamDelete only when the user wants this team replaced by a new one.`,
      )
    }
```

- **Team = Project = TaskList 同构**：`teamName` → `sanitizeName` → `taskListId`；`resetTaskList` 让任务编号从 1 开始；`setLeaderTeamName` 让 leader 的 `getTaskListId()` 返回 teamName（否则 tmux/iTerm2 teammate 写到不同目录）。v0.7.7 还用 `withTaskListLifecycleLock` 把命名预留与生命周期创建合成一个跨进程事务，避免两个 leader 覆盖同一 generation。`src/tools/TeamCreateTool/TeamCreateTool.ts`：

```ts
      const taskListId = sanitizeName(finalTeamName)
      created = await withTaskListLifecycleLock(taskListId, async () => {
        // Name reservation and lifecycle creation are one cross-process
        // transaction. A pre-lock existence check allowed two leaders to both
        // create the same absent Team and overwrite each other's generation.
        const lifecycleState = await readTaskListLifecycleState(taskListId)
```

- **持久化与清理**：teamFile 写磁盘 `writeTeamFileAsync`；`registerTeamForSessionCleanup` 修复了 gh-32730（team 不再永远留磁盘，session 结束清理）。
- **TeamDelete 安全闸门**：若仍有 `nonLeadMembers`（含未 terminated 的 process 成员），直接拒绝并提示先 `requestShutdown`——防止旧 actor 在同名 team 重生、mutate 新 generation 的 task list。`src/tools/TeamDeleteTool/TeamDeleteTool.ts`：

```ts
        // Shutdown approval removes teammates from the config; only that
        // durable transition makes cleanup safe.
        const nonLeadMembers = teamFile.members.filter(
          m => m.agentId !== teamFile.leadAgentId && !(m.backendType === 'process' && m.terminated === true),
        )

        if (nonLeadMembers.length > 0) {
          const memberNames = nonLeadMembers.map(m => m.name).join(', ')
          return {
            data: {
              success: false,
              message: `Cannot cleanup team with ${nonLeadMembers.length} registered teammate(s): ${memberNames}. Send each a shutdown_request with SendMessage, then end your turn: approvals arrive as messages, and TeamDelete succeeds once those teammates have exited. Never delete the team or task directories yourself.`,
              team_name: teamName,
            },
          }
        }
```

- **TeamPlan 草稿评审**（仅桌面 session `isTeamReviewRequired()`）：`submit` 后 `requestTeamPlanTurnPause` 等待人类在 team panel 审批，**不启动成员、不审批即不执行**；teammate 不可 submit（`isEnabled()` 还要求 `isAgentSwarmsEnabled() && !isTeammate()`）。`src/tools/TeamPlanTool/TeamPlanTool.ts`：

```ts
  operation: z.enum(['get', 'replace', 'submit']),
  expected_revision: z.number().int().positive().optional().describe('Required for replace and submit; use the revision returned by TeamCreate, Agent or TeamPlan.'),
  plan: proposedTeamPlanSchema.optional(),
}))
```

> 关键澄清：`ListPeersTool.ts` 是自动生成的 stub（开头 `@generated stub from scan-missing-imports`，对应 ant-internal 的 `feature()` gated 模块，注释明言「DCE 后都不会真的执行」）。**代码存在 ≠ 公开版实际生效**：`src/tools/ListPeersTool/ListPeersTool.ts`：

```ts
// @generated stub from scan-missing-imports
// 该文件自动生成，对应 ant-internal 的 feature() gated 模块。
// 所有外部 build 的代码路径在 DCE 后都不会真的执行这里的代码，这只是
// bun build resolver 的占位符。
const __target = function noop() {}
const __handler: ProxyHandler<any> = {
  get(_t, prop) {
    if (prop === '__esModule') return true
    if (prop === 'default') return new Proxy(__target, __handler)
```

## SendMessage: Teammate Communication Model

`SendMessage` 的接收者语法（`src/tools/SendMessageTool/SendMessageTool.ts`）**受 `feature('UDS_INBOX')` 门控**：该 flag 为真时才有 `uds:<socket-path>`（本地 peer）、`bridge:<session-id>`（Remote Control peer）与 `ListPeers` 发现；公开版默认只有具名 teammate 与 `*` 广播：

```ts
const standardInputSchema = lazySchema(() =>
  z.object({
    to: z
      .string()
      .describe(
        feature('UDS_INBOX')
          ? 'Recipient: teammate name, "*" for broadcast, "uds:<socket-path>" for a local peer, or "bridge:<session-id>" for a Remote Control peer (use ListPeers to discover)'
          : 'Recipient: teammate name, or "*" for broadcast to all teammates',
      ),
```

**投递模型 = 持久化 inbox + 按需 resume，不是常驻进程 IPC**（基于 `teammateMailbox.js`）：

- lead 与 in-process teammate 直接写 teammate 的 inbox（`handleMessage`）；`*`（`handleBroadcast`）广播给所有 teammate。
- **in-process teammate 的 runner 挂了**（failed / finished / stopped / evicted）→ inbox 无人读 → 从 transcript **resume** 该 teammate，把消息作为 next prompt（`resumeTeammateWithMessage`）。
- 状态分支：running teammate → 排队下个 turn；未 running → resume 为 in-process teammate + 消息作 next prompt；pending plan member（plan 未审批）→ 排队，审批后读取；desktop process member → 只写 inbox，server restart 重投。

> 这解释了 teammate 为何无需常驻进程也能异步通信：**崩溃 / 停止的 teammate 通过 resume-from-transcript 重新读取 inbox**，消息不丢。

## Swarm Lifecycle: Runtime Semantics

- **初始化与恢复**：`useSwarmInitialization` 区分 fresh spawn（从 env 读 teamName / agentId / agentName）与 resumed teammate session（从 transcript messages 的 teamName / agentName 恢复），两者都调 `initializeTeammateHooks`。
- **权限集中裁决**：swarm worker（teammate）调用危险工具时，`useCanUseTool` 创建 pending permission request 并写入磁盘 / inbox（mailbox IPC）；leader 批准后写回 response；`useSwarmPermissionPoller` 每 **500ms** 轮询 `pollForResponse` 并触发回调，模块级 `pendingCallbacks` registry 在 `/clear` 时由 `clearSessionCaches()` 清理。`src/hooks/useSwarmPermissionPoller.ts`：

```ts
const POLL_INTERVAL_MS = 500

/**
 * Validate permissionUpdates from external sources (mailbox IPC, disk polling).
```

→ **teammate 的危险操作由 leader 集中审批，worker 不能自决**。另有 **sandbox permission** 回调（worker 向 leader 请求 sandbox 权限）。
- **视图自动退出**：teammate 进入 `killed` / `failed` / `error` / 非 running 状态时，`useTeammateViewAutoExit` 自动退出查看模式（保留 `completed` 供 review）。

## Summary

- **Agent Teams（UI）** = 引擎既有 agent-teams 的实时可视化器：成员 / 任务 / 通信 feed / 依赖泳道画布 / 回放游标均为 GUI-only。
- **Dynamic Workflow（引擎）** = 真实的模型创作 + VM 执行编排系统，派生受上限约束的 subagent 并支持缓存恢复。
- **Teammate Tools（工具层）** = 模型可直调的团队生命周期工具：`TeamCreate`（1 leader 1 team、Team=Project=TaskList 同构）/ `TeamPlan`（草稿评审、`submit` 暂停等人类）/ `TeamDelete`（active teammate 闸门）/ `SendMessage`（inbox + resume 通信）/ `ListPeers`（公开版为 stub）。
- **Swarm Lifecycle（运行语义）** = 初始化与 resume、权限由 leader 集中裁决（500ms 轮询）、视图自动退出。

## Corrections

| 旧描述 | 源码事实（v0.7.7） |
| :-- | :-- |
| `SendMessage` 默认支持 `uds:<socket-path>` / `bridge:<session-id>` 与 `ListPeers` peer 发现 | 该接收者语法被 `feature('UDS_INBOX')` 门控；flag 关闭时 `to` 只接受具名 teammate 或 `*` 广播。`ListPeersTool.ts` 是 `@generated stub`，公开 build DCE 后不执行——「代码存在」不等于「公开版实际生效」 |
| 回放由 `replayFrameDelay` / `seekTimeline` 驱动，且组件注释原文仅为 "snapshot stream is the only source of truth" | v0.7.7 注释扩充为「live 与 replay 共用同一条流、回放只是移动游标」；回放改由 `workbenchHistoryIndexBySession` + `setWorkbenchHistoryIndex` + `snapshotWithHistoricalMembers` 实现，`replayFrameDelay` / `seekTimeline` 在 `agentTeamsModel.ts` 已不再命中 |
| 旧笔记大量逐处行号引证 | 已逐处按 v0.7.7 真实源码重新核实，改为原样连续代码块；硬上限、确定性 VM、journal 链式缓存键、`cacheExhausted`、启用 gate、ultracode、1 leader 1 team、`TeamDelete` 闸门等结论在 v0.7.7 仍成立 |

## Links

- [CcHaha 主枢纽](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md)
- [Permission](/docs/CS/AI/LLM/Agent/Product/CcHaha/Permission.md)
- [三向对照：Claude Code / OpenCode / cc-haha](/docs/CS/AI/LLM/Agent/Product/CcHaha/Comparison.md)
- [AgentTeamsEngine](/docs/CS/AI/LLM/Agent/Product/CcHaha/AgentTeamsEngine.md)
- [RuntimeTopology](/docs/CS/AI/LLM/Agent/Product/CcHaha/RuntimeTopology.md)

## References

- [cc-haha GitHub](https://github.com/NanmiCoder/cc-haha)
- [agentTeamsModel.ts](https://github.com/NanmiCoder/cc-haha/blob/main/desktop/src/components/agentTeams/agentTeamsModel.ts)
- [TeamCreateTool.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/TeamCreateTool/TeamCreateTool.ts)
- [TeamDeleteTool.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/TeamDeleteTool/TeamDeleteTool.ts)
- [TeamPlanTool.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/TeamPlanTool/TeamPlanTool.ts)
- [SendMessageTool.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/SendMessageTool/SendMessageTool.ts)
- [ListPeersTool.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/ListPeersTool/ListPeersTool.ts)
- [useSwarmInitialization.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/hooks/useSwarmInitialization.ts)
- [useSwarmPermissionPoller.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/hooks/useSwarmPermissionPoller.ts)
- [useTeammateViewAutoExit.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/hooks/useTeammateViewAutoExit.ts)
- [AgentTeamsCanvas.tsx](https://github.com/NanmiCoder/cc-haha/blob/main/desktop/src/components/agentTeams/AgentTeamsCanvas.tsx)
- [WorkflowTool.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/WorkflowTool/WorkflowTool.ts)
- [launchWorkflow.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/WorkflowTool/launchWorkflow.ts)
- [prompt.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/WorkflowTool/prompt.ts)
- [enabled.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/workflows/enabled.ts)
- [constants.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/workflows/constants.ts)
- [runtime.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/workflows/runtime.ts)
- [harness.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/workflows/harness.ts)
- [compile.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/workflows/compile.ts)
- [journal.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/workflows/journal.ts)
- [runNestedWorkflow.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/WorkflowTool/runNestedWorkflow.ts)
- [ultracode.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/workflows/ultracode.ts)
