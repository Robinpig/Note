## Introduction

> 版本基线：v0.7.7（本地源码 E:/Projects/cc-haha-0.7.7）

计划任务是 cc-haha（及上游 Claude Code 的 Kairos cron）相对多数 agent 工作台的明显差异化能力：**把一段提示词按时间自动跑**，典型用法是每天审一遍提交、每周整理待办、每小时查一次日志。它不是云端调度器——只在桌面应用打开、且电脑处于唤醒状态时运行。旧笔记写的「合盖 / 退出 / 关机都不会跑，也不会补跑」在 v0.7.7 已被设计文档改写：会话型任务错过时间会在应用恢复且目标会话空闲时**补跑一次**，周期任务不重放每个周期，旧的独立 Cron 任务保持原行为不补跑。`docs/desktop/schedule.md` 的原文：

```text
:::warning
任务在本机执行，需要桌面应用打开、电脑唤醒。新任务错过执行时间后，会在应用恢复运行且目标会话空闲时补执行一次；周期任务不会把离线期间的每个周期都重放。旧的独立 Cron 任务保持原行为，不补跑离线期间错过的触发。
:::
```

底层有两套**相互独立**的引擎：模型可调的 `ScheduleCronTool`（`CronCreate` / `CronUpdate` / `CronDelete` / `CronList`，写项目级 `<project>/.claude/scheduled_tasks.json`），以及桌面服务端调度器（`src/server/services/cronScheduler.ts` 单例 + `CronService`，写用户级 `~/.claude/scheduled_tasks.json`）。v0.7.7 里两套引擎**不再共享** cron 解析与 jitter：服务端自带 `fieldMatches` / `cronMatches` 且完全不消费 jitter，jitter 只在 REPL/SDK 内核 `src/utils/cronScheduler.ts` 里消费。此外 v0.7.7 新增了面向桌面持久化任务的模型工具 `ScheduledTaskTool` 与会话型执行宿主 `scheduledTaskHost.ts`，详见 `## Corrections`。

## Two Independent Engines

- **(a) 模型可调工具集** —— `src/tools/ScheduleCronTool/` 暴露 `CronCreate` / `CronUpdate` / `CronDelete` / `CronList`。任务落库在 `src/utils/cronTasks.ts`：`durable:true` 写 `<project>/.claude/scheduled_tasks.json`，`durable:false` 只进内存会话 store。文件头与格式说明：

```ts
// Scheduled prompts, stored in <project>/.claude/scheduled_tasks.json.
//
// Tasks come in two flavors:
//   - One-shot (recurring: false/undefined) — fire once, then auto-delete.
//   - Recurring (recurring: true) — fire on schedule, reschedule from now,
//     persist until explicitly deleted via CronDelete or auto-expire after
//     a configurable limit (DEFAULT_CRON_JITTER_CONFIG.recurringMaxAgeMs).
//
// File format:
//   { "tasks": [{ id, cron, prompt, createdAt, recurring?, permanent? }] }
```

项目级路径由 `src/utils/cronTasks.ts` 的 `getCronFilePath` 决定：

```ts
const CRON_FILE_REL = join('.claude', 'scheduled_tasks.json')

/**
 * Path to the cron file. `dir` defaults to getProjectRoot() — pass it
 * explicitly from contexts that don't run through main.tsx (e.g. the Agent
 * SDK daemon, which has no bootstrap state).
 */
export function getCronFilePath(dir?: string): string {
  return join(dir ?? getProjectRoot(), CRON_FILE_REL)
}
```

`addCronTask` 体现 durable 与否的分叉，非 durable 走 `addSessionCronTask`（bootstrap 内存态），durable 走 `readCronTasks` + `writeCronTasks`：

```ts
/**
 * Append a task. Returns the generated id. Caller is responsible for having
 * already validated the cron string (the tool does this via validateInput).
 *
 * When `durable` is false the task is held in process memory only
 * (bootstrap/state.ts) — it fires on schedule this session but is never
 * written to .claude/scheduled_tasks.json and dies with the process. The
 * scheduler merges session tasks into its tick loop directly, so no file
 * change event is needed.
 */
export async function addCronTask(
  cron: string,
  prompt: string,
  recurring: boolean,
  durable: boolean,
  agentId?: string,
  meta?: CronTaskMeta,
): Promise<string> {
  // Short ID — 8 hex chars is plenty for MAX_JOBS=50, avoids slice/prefix
  // juggling between the tool layer (shows short IDs) and disk.
  const id = randomUUID().slice(0, 8)
  const task: CronTask = {
    id,
    cron,
    prompt,
    createdAt: Date.now(),
    ...(recurring ? { recurring: true } : {}),
    ...(meta?.name ? { name: meta.name } : {}),
    ...(meta?.description ? { description: meta.description } : {}),
    ...(meta?.folder ? { folder: meta.folder } : {}),
    ...(meta?.model ? { model: meta.model } : {}),
    ...(typeof meta?.providerId === 'string' || meta?.providerId === null
      ? { providerId: meta.providerId }
      : {}),
    ...(meta?.permissionMode
      ? { permissionMode: meta.permissionMode }
      : {}),
    ...(meta?.worktree !== undefined ? { worktree: meta.worktree } : {}),
    ...(meta?.frequency ? { frequency: meta.frequency } : {}),
    ...(meta?.scheduledTime ? { scheduledTime: meta.scheduledTime } : {}),
  }
  if (!durable) {
    addSessionCronTask({ ...task, ...(agentId ? { agentId } : {}) })
    return id
  }
  const tasks = await readCronTasks()
  tasks.push(task)
  await writeCronTasks(tasks)
  return id
}
```

写盘同样是 tmp + rename，并剥掉 `durable` / `agentId` 这类运行时字段（`src/utils/cronTasks.ts`）：

```ts
/**
 * Overwrite .claude/scheduled_tasks.json with the given tasks. Creates .claude/ if
 * missing. Empty task list writes an empty file (rather than deleting) so
 * the file watcher sees a change event on last-task-removed.
 */
export async function writeCronTasks(
  tasks: CronTask[],
  dir?: string,
): Promise<void> {
  const root = dir ?? getProjectRoot()
  const claudeDir = join(root, '.claude')
  await mkdir(claudeDir, { recursive: true })
  const originalDirectoryStats = await assertSafeCronDirectory(claudeDir)
  // Strip runtime-only flags — everything on disk is durable by definition,
  // and agentId is session-scoped (teammates don't persist across sessions).
  const body: CronFile = {
    tasks: tasks.map(({ durable: _durable, agentId: _agentId, ...rest }) => rest),
  }
  const targetPath = getCronFilePath(root)
  const temporaryPath = join(
    claudeDir,
    `.scheduled_tasks.${process.pid}.${randomUUID()}.tmp`,
  )
  try {
    await writeFile(temporaryPath, jsonStringify(body, null, 2) + '\n', {
      encoding: 'utf-8',
      flag: 'wx',
      mode: 0o600,
    })
    await assertSameCronDirectory(claudeDir, originalDirectoryStats)
    await rename(temporaryPath, targetPath)
    await assertSameCronDirectory(claudeDir, originalDirectoryStats)
  } catch (error) {
    if (
      await isSameCronDirectory(claudeDir, originalDirectoryStats)
    ) {
      await unlink(temporaryPath).catch(() => {})
    }
    throw error
  }
}
```

- **(b) 服务端调度器** —— `src/server/services/cronScheduler.ts` 末尾导出单例，60s `setInterval` headless，支撑侧边栏 UI 向导与本地 HTTP API：

```ts
export const cronScheduler = new CronScheduler()
```

任务列表由 `CronService`（`src/server/services/cronService.ts`）管理。v0.7.7 的 `CronTask` 已扩展出 `schedule` / `execution` / `revision` / `notificationPolicy` / `useWorktree` 等字段：

```ts
export type CronTask = {
  id: string
  revision?: number
  completedAt?: string
  scheduleAnchorAt?: number
  sourceSessionId?: string
  execution?: { kind: 'session'; targetSessionId: string } | { kind: 'new-session' }
  schedule?: TaskSchedule
  notificationPolicy?: 'important' | 'all' | 'failed' | 'none'
  nextRunAt?: number
  scheduleState?: 'active' | 'paused' | 'completed'
  name?: string
  description?: string
  cron: string // 5-field cron expression
  prompt: string
  createdAt: number // epoch ms
  lastFiredAt?: string // ISO timestamp of last execution
  enabled?: boolean // allow disabling without deleting (default true)
  recurring?: boolean
  permanent?: boolean
  permissionMode?: string
  model?: string
  providerId?: string | null
  folderPath?: string
  useWorktree?: boolean
  notification?: TaskNotificationConfig
}
```

CRUD 落在**用户级**路径（`src/server/services/cronService.ts`）：

```ts
export class CronService {
  /** 任务文件路径 */
  private getTasksFilePath(): string {
    const configDir =
      process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), '.claude')
    return path.join(configDir, 'scheduled_tasks.json')
  }
```

`permissionMode:'bypassPermissions'` 在 v0.7.7 **不再是每次读写都强制**：`createTask` / `updateTask` / `snapshot` 都只在任务**没有** `execution`（旧式独立任务）时才注入该值，会话型任务沿用会话权限：

```ts
    if ((!task.cron && !task.schedule) || !task.prompt) {
      throw ApiError.badRequest('Fields "cron" and "prompt" are required')
    }

    this.validateTask(task)
    return runExclusive(this.getTasksFilePath(), async () => {
      const data = await this.readTasksFile()
      const creationKey = options?.requestId ? `${options.sourceSessionId ?? task.sourceSessionId ?? ''}:${options.requestId}` : undefined
      const input = JSON.stringify(task)
      const previous = creationKey ? data.creations?.[creationKey] : undefined
      if (previous) {
        if (previous.input !== input) throw ApiError.conflict('Request ID was already used with different task input')
        const existing = data.tasks.find(item => item.id === previous.taskId)
        if (!existing) throw ApiError.conflict('The task created by this request was deleted')
        return this.snapshot(existing)
      }
      if (task.schedule?.kind === 'once' && Date.parse(task.schedule.runAt) <= Date.now()) throw ApiError.badRequest('One-time task must be scheduled in the future')
      const newTask: CronTask = {
        ...task,
        cron: task.schedule?.kind === 'cron' ? task.schedule.expression : task.cron ?? '',
        ...(task.execution ? {} : { permissionMode: 'bypassPermissions' }),
        sourceSessionId: options?.sourceSessionId ?? task.sourceSessionId,
        recurring: task.schedule ? task.schedule.kind === 'cron' : task.recurring,
        revision: 1,
        id: crypto.randomBytes(4).toString('hex'),
        createdAt: Date.now(),
      }
```

每次读/写用模块级 per-file 互斥队列 `mutationQueues`，防止「调度器并发写 `lastFiredAt`」与「API 增删改」互相覆盖（`src/server/services/cronService.ts`）：

```ts
/**
 * 每个任务文件一条互斥队列（模块级，跨实例共享）。
 * 调度器会在同一分钟并发启动多个任务（各自调用 updateLastFired），
 * API 的增删改也可能与调度器写入交错；无互斥时后完成的写回会覆盖
 * 先完成的修改（执行时间丢失、创建不落盘、已删除任务复活）。
 * 注意 API 层（scheduled-tasks.ts）与调度器（cronScheduler.ts）持有
 * 不同的 CronService 实例，因此队列必须按文件路径共享而非挂在实例上。
 */
const mutationQueues = new Map<string, Promise<unknown>>()

/** 在指定文件的互斥队列中执行变更操作，保留其原始结果/错误。 */
function runExclusive<T>(filePath: string, operation: () => Promise<T>): Promise<T> {
  const previous = mutationQueues.get(filePath) ?? Promise.resolve()
  const result = previous.then(operation)
  mutationQueues.set(
    filePath,
    result.then(
      () => undefined,
      () => undefined,
    ),
  )
  return result
}
```

原子写入走 tmp + rename，重试上限由常量控制，仅 EPERM / ENOENT 可重试（`src/server/services/cronService.ts`）：

```ts
const TASKS_FILE_WRITE_ATTEMPTS = 2
```

```ts
  /** 原子写入任务 JSON 文件 */
  private async writeTasksFile(data: TasksFile): Promise<void> {
    const filePath = this.getTasksFilePath()
    const dir = path.dirname(filePath)
    const contents = JSON.stringify({ ...data, schemaVersion: 1 }, null, 2) + '\n'
    let lastError: Error | undefined

    for (let attempt = 0; attempt < TASKS_FILE_WRITE_ATTEMPTS; attempt++) {
      const tmpFile = `${filePath}.tmp.${process.pid}.${Date.now()}.${crypto.randomBytes(6).toString('hex')}`

      try {
        await fs.mkdir(dir, { recursive: true })
        await fs.writeFile(tmpFile, contents, 'utf-8')
        await fs.rename(tmpFile, filePath)
        return
      } catch (err) {
        lastError = err as Error
        await fs.unlink(tmpFile).catch(() => {})

        // EPERM: Windows 上与其他进程同时 rename 到同一目标可能瞬时失败，
        // 与 ENOENT 一样属于可重试的瞬时错误。
        const code = (err as NodeJS.ErrnoException).code
        const retryable = code === 'ENOENT' || code === 'EPERM'
        if (!retryable || attempt === TASKS_FILE_WRITE_ATTEMPTS - 1) {
          break
        }
      }
    }

    throw ApiError.internal(
      `Failed to write scheduled tasks: ${lastError?.message ?? 'unknown error'}`,
    )
  }
```

`CronService` 校验 cron 时 import 的是 `../../utils/cron.js` 的 `parseCronExpression`，**不** import `cronTasks.ts`。服务端调度器另有自带的分钟匹配器，完全不消费 jitter（`src/server/services/cronScheduler.ts`）：

```ts
export function cronMatches(cronExpr: string, date: Date): boolean {
  const fields = cronExpr.trim().split(/\s+/)
  if (fields.length !== 5) return false

  const [minute, hour, dayOfMonth, month, dayOfWeek] = fields
  return (
    fieldMatches(minute, date.getMinutes()) &&
    fieldMatches(hour, date.getHours()) &&
    fieldMatches(dayOfMonth, date.getDate()) &&
    fieldMatches(month, date.getMonth() + 1) &&
    fieldMatches(dayOfWeek, date.getDay())
  )
}
```

- **(c) v0.7.7 新增的模型工具** —— `src/tools/ScheduledTaskTool/` 的 `ScheduledTaskTool` 面向桌面持久化定时任务（会话型），动作含 `list` / `view` / `create` / `update` / `delete` / `runs` / `run` / `report`，与旧的会话内 `ScheduleCronTool` 并存：

```ts
export const ScheduledTaskTool = buildTool({
  name: 'ScheduledTask',
  searchHint: 'schedule reminder continue later recurring tasks automation execution results history',
  alwaysLoad: true,
  maxResultSizeChars: 100_000,
  inputSchema: scheduledTaskInputSchema,
  inputJSONSchema: scheduledTaskInputJSONSchema,
  isEnabled: isDesktopScheduleAvailable,
  isReadOnly: input => ['list', 'view', 'runs', 'run'].includes(input.action),
  isConcurrencySafe: input => ['list', 'view', 'runs', 'run'].includes(input.action),
  async description() { return description },
  async prompt() { return description },
```

> 两套引擎写**两个不同的** `scheduled_tasks.json`：工具集写 `<project>/.claude/scheduled_tasks.json`（项目级，`createCronScheduler` 驱动）；服务端调度器经 `CronService` 写 `~/.claude/scheduled_tasks.json`（用户级，HTTP API / UI 向导驱动），运行日志另存 `~/.claude/scheduled_tasks_log.json`（canonical）+ `bun:sqlite` 派生索引。**注意**：旧笔记称「两者通过 `cronTasksLock.ts` 的跨会话租约避免重复触发」不成立——该锁只服务 REPL/SDK 侧，服务端用 `lastFiredMinuteKey` + 文件持久化 `lastFiredAt` + `ScheduledTaskReceipt` 去重，见 `## Corrections`。

## REPL Scheduler (createCronScheduler)

与引擎 (b) 的 headless 单例不同，交互式 REPL / Agent SDK（`-p` 模式）走 **`src/utils/cronScheduler.ts`** 的 `createCronScheduler` —— 一个**非 React 的纯调度内核**，被 `useScheduledTasks`（REPL）与 `print.ts`（SDK/-p）共用。文件头的生命周期说明：

```ts
// Non-React scheduler core for .claude/scheduled_tasks.json.
// Shared by REPL (via useScheduledTasks) and SDK/-p mode (print.ts).
//
// Lifecycle: poll getScheduledTasksEnabled() until true (flag flips when
// CronCreate runs or a skill on: trigger fires) → load tasks + watch the
// file + start a 1s check timer → on fire, call onFire(prompt). stop()
// tears everything down.
```

计时器常量（`src/utils/cronScheduler.ts`）：

```ts
const CHECK_INTERVAL_MS = 1000
const FILE_STABILITY_MS = 300
// How often a non-owning session re-probes the scheduler lock. Coarse
// because takeover only matters when the owning session has crashed.
const LOCK_PROBE_INTERVAL_MS = 5000
```

`CronSchedulerOptions` 按需注入（`src/utils/cronScheduler.ts`）：`onFire(prompt)` / `onFireTask(task)` 触发回调；`isLoading()` 加载闸门（`assistantMode` 可绕过）；`getJitterConfig()` 注入 GrowthBook 实现做到不重启热调 jitter；`isKilled()` 每 tick 轮询的 killswitch；`filter(t)` per-task 闸门；`dir` / `lockIdentity` 供 Agent SDK daemon 绕过 bootstrap 状态与 enable 轮询；`onMissed` 供 daemon 处理启动时浮现的错过一次性任务。

```ts
type CronSchedulerOptions = {
  /** Called when a task fires (regular or missed-on-startup). */
  onFire: (prompt: string) => void
  /** While true, firing is deferred to the next tick. */
  isLoading: () => boolean
  /**
   * When true, bypasses the isLoading gate in check() and auto-enables the
   * scheduler without waiting for setScheduledTasksEnabled(). The
   * auto-enable is the load-bearing part — assistant mode has tasks in
   * scheduled_tasks.json at install time and shouldn't wait on a loader
   * skill to flip the flag. The isLoading bypass is minor post-#20425
   * (assistant mode now idles between turns like a normal REPL).
   */
  assistantMode?: boolean
  /**
   * When provided, receives the full CronTask on normal fires (and onFire is
   * NOT called for that fire). Lets daemon callers see the task id/cron/etc
   * instead of just the prompt string.
   */
  onFireTask?: (task: CronTask) => void
  /**
   * When provided, receives the missed one-shot tasks on initial load (and
   * onFire is NOT called with the pre-formatted notification). Daemon decides
   * how to surface them.
   */
  onMissed?: (tasks: CronTask[]) => void
  /**
   * Directory containing .claude/scheduled_tasks.json. When provided, the
   * scheduler never touches bootstrap state: getProjectRoot/getSessionId are
   * not read, and the getScheduledTasksEnabled() poll is skipped (enable()
   * runs immediately on start). Required for Agent SDK daemon callers.
   */
  dir?: string
  /**
   * Owner key written into the lock file. Defaults to getSessionId().
   * Daemon callers must pass a stable per-process UUID since they have no
   * session. PID remains the liveness probe regardless.
   */
  lockIdentity?: string
  /**
   * Returns the cron jitter config to use for this tick. Called once per
   * check() cycle. REPL callers pass a GrowthBook-backed implementation
   * (see cronJitterConfig.ts) for live tuning — ops can widen the jitter
   * window mid-session during a :00 load spike without restarting clients.
   * Agent SDK daemon callers omit this and get DEFAULT_CRON_JITTER_CONFIG,
   * which is safe since daemons restart on config change anyway, and the
   * growthbook.ts → config.ts → commands.ts → REPL chain stays out of
   * sdk.mjs.
   */
  getJitterConfig?: () => CronJitterConfig
  /**
   * Killswitch: polled once per check() tick. When true, check() bails
   * before firing anything — existing crons stop dead mid-session. CLI
   * callers inject `() => !isKairosCronEnabled()` so flipping the
   * tengu_kairos_cron gate off stops already-running schedulers (not just
   * new ones). Daemon callers omit this, same rationale as getJitterConfig.
   */
  isKilled?: () => boolean
  /**
   * Per-task gate applied before any side effect. Tasks returning false are
   * invisible to this scheduler: never fired, never stamped with
   * `lastFiredAt`, never deleted, never surfaced as missed, absent from
   * `getNextFireTime()`. The daemon cron worker uses `t => t.permanent` so
   * non-permanent tasks in the same scheduled_tasks.json are untouched.
   */
  filter?: (t: CronTask) => boolean
}
```

`getJitterConfig` 的具体实现在 `src/utils/cronJitterConfig.ts`：读 `tengu_kairos_cron_config`、Zod 校验、非法则回退默认，刷新窗口 60s（与 gate 的 5 分钟窗口是两个不同 config）：

```ts
export function getCronJitterConfig(): CronJitterConfig {
  const raw = getFeatureValue_CACHED_WITH_REFRESH<unknown>(
    'tengu_kairos_cron_config',
    DEFAULT_CRON_JITTER_CONFIG,
    JITTER_CONFIG_REFRESH_MS,
  )
  const parsed = cronJitterConfigSchema().safeParse(raw)
  return parsed.success ? parsed.data : DEFAULT_CRON_JITTER_CONFIG
}
```

**`check()` 的 jitter 消费**：每 tick 先取配置（`src/utils/cronScheduler.ts`）：

```ts
    // Read once per tick. REPL callers pass getJitterConfig backed by
    // GrowthBook so a config push takes effect without restart. Daemon and
    // SDK callers omit it and get DEFAULT_CRON_JITTER_CONFIG (safe — jitter
    // is an ops lever for REPL fleet load-shedding, not a daemon concern).
    const jitterCfg = getJitterConfig?.() ?? DEFAULT_CRON_JITTER_CONFIG
```

每个任务首次见到时按 `recurring` 调 `jitteredNextCronRunMs` / `oneShotJitteredNextCronRunMs`，锚点取 `lastFiredAt ?? createdAt`，避免 `isLoading` 延迟把 pinned cron 算到明年（`src/utils/cronScheduler.ts`）：

```ts
      let next = nextFireAt.get(t.id)
      if (next === undefined) {
        // First sight — anchor from lastFiredAt (recurring) or createdAt.
        // Never-fired recurring tasks use createdAt: if isLoading delayed
        // this tick past the fire time, anchoring from `now` would compute
        // next-year for pinned crons (`30 14 27 2 *`). Fired-before tasks
        // use lastFiredAt: the reschedule below writes `now` back to disk,
        // so on next process spawn first-sight computes the SAME newNext we
        // set in-memory here. Without this, a daemon child despawning on
        // idle loses nextFireAt and the next spawn re-anchors from 10-day-
        // old createdAt → fires every task every cycle.
        next = t.recurring
          ? (jitteredNextCronRunMs(
              t.cron,
              t.lastFiredAt ?? t.createdAt,
              t.id,
              jitterCfg,
            ) ?? Infinity)
          : (oneShotJitteredNextCronRunMs(
              t.cron,
              t.createdAt,
              t.id,
              jitterCfg,
            ) ?? Infinity)
        nextFireAt.set(t.id, next)
```

触发、老化判定、recurring 重排与一次性/老化删除路径（`src/utils/cronScheduler.ts`）——这是 jitter 与 auto-expire 的真正落点：

```ts
      // Aged-out recurring tasks fall through to the one-shot delete paths
      // below (session tasks get synchronous removal; file tasks get the
      // async inFlight/chokidar path). Fires one last time, then is removed.
      const aged = isRecurringTaskAged(t, now, jitterCfg.recurringMaxAgeMs)
      if (aged) {
        const ageHours = Math.floor((now - t.createdAt) / 1000 / 60 / 60)
        logForDebugging(
          `[ScheduledTasks] recurring task ${t.id} aged out (${ageHours}h since creation), deleting after final fire`,
        )
        logEvent('tengu_scheduled_task_expired', {
          taskId:
            t.id as AnalyticsMetadata_I_VERIFIED_THIS_IS_NOT_CODE_OR_FILEPATHS,
          ageHours,
        })
      }

      if (t.recurring && !aged) {
        // Recurring: reschedule from now (not from next) to avoid rapid
        // catch-up if the session was blocked. Jitter keeps us off the
        // exact :00 wall-clock boundary every cycle.
        const newNext =
          jitteredNextCronRunMs(t.cron, now, t.id, jitterCfg) ?? Infinity
        nextFireAt.set(t.id, newNext)
        // Persist lastFiredAt=now so next process spawn reconstructs this
        // same newNext on first-sight. Session tasks skip — process-local.
        if (!isSession) firedFileRecurring.push(t.id)
      } else if (isSession) {
        // One-shot (or aged-out recurring) session task: synchronous memory
        // removal. No inFlight window — the next tick will read a session
        // store without this id.
        removeSessionCronTasks([t.id])
        nextFireAt.delete(t.id)
      } else {
        // One-shot (or aged-out recurring) file task: delete from disk.
        // inFlight guards against double-fire during the async
        // removeCronTasks + chokidar reload.
        inFlight.add(t.id)
        void removeCronTasks([t.id], dir)
          .catch(e =>
            logForDebugging(
              `[ScheduledTasks] failed to remove task ${t.id}: ${e}`,
            ),
          )
          .finally(() => inFlight.delete(t.id))
        nextFireAt.delete(t.id)
      }
```

文件任务仅在**持有调度锁**时处理；`chokidar` 用 `awaitWriteFinish` 的 `stabilityThreshold = FILE_STABILITY_MS`，`checkTimer` 为 1s 且 `unref()`（`src/utils/cronScheduler.ts`）：

```ts
    const { default: chokidar } = await import('chokidar')
    if (stopped) return

    // Acquire the per-project scheduler lock. Only the owning session runs
    // check(). Other sessions probe periodically to take over if the owner
    // dies. Prevents double-firing when multiple Claudes share a cwd.
    isOwner = await tryAcquireSchedulerLock(lockOpts).catch(() => false)
    if (stopped) {
      if (isOwner) {
        isOwner = false
        void releaseSchedulerLock(lockOpts)
      }
      return
    }
    if (!isOwner) {
      lockProbeTimer = setInterval(() => {
        void tryAcquireSchedulerLock(lockOpts)
          .then(owned => {
            if (stopped) {
              if (owned) void releaseSchedulerLock(lockOpts)
              return
            }
            if (owned) {
              isOwner = true
              if (lockProbeTimer) {
                clearInterval(lockProbeTimer)
                lockProbeTimer = null
              }
            }
          })
          .catch(e => logForDebugging(String(e), { level: 'error' }))
      }, LOCK_PROBE_INTERVAL_MS)
      lockProbeTimer.unref?.()
    }

    void load(true)

    const path = getCronFilePath(dir)
    watcher = chokidar.watch(path, {
      persistent: false,
      ignoreInitial: true,
      awaitWriteFinish: { stabilityThreshold: FILE_STABILITY_MS },
      ignorePermissionErrors: true,
    })
    watcher.on('add', () => void load(false))
    watcher.on('change', () => void load(false))
    watcher.on('unlink', () => {
      if (!stopped) {
        tasks = []
        nextFireAt.clear()
      }
    })

    checkTimer = setInterval(check, CHECK_INTERVAL_MS)
```

> 注意区分两个 `cronScheduler.ts`：本节的 `src/utils/cronScheduler.ts`（REPL/SDK 内核，1s tick，chokidar，消费 jitter + 跑过期）与引擎 (b) 的 `src/server/services/cronScheduler.ts`（服务端，60s tick，会话注入 / CLI spawn）。二者**不互相 import**，但都最终驱动同一类任务。

## Cron Expression

标准 **5 字段** `分 时 日 月 星期`，按**用户本地时区**解析。v0.7.7 把 `parseCronExpression` / `expandField` 迁到了 `src/shared/cron.ts`，`src/utils/cron.ts` 只剩 re-export、`computeNextCronRun` 与 `cronToHuman`：

```ts
// Minimal cron expression parsing and next-run calculation.
//
// Supports the standard 5-field cron subset:
//   minute hour day-of-month month day-of-week
//
// Field syntax: wildcard, N, step (star-slash-N), range (N-M), list (N,M,...).
// No L, W, ?, or name aliases. All times are interpreted in the process's
// local timezone — "0 9 * * *" means 9am wherever the CLI is running.

import type { CronFields } from '../shared/cron.js'
export { parseCronExpression, type CronFields } from '../shared/cron.js'
```

字段范围里 `dayOfWeek` 明确接受 `7` 作为 `0` 的别名（`src/shared/cron.ts`）：

```ts
const FIELD_RANGES: FieldRange[] = [
  { min: 0, max: 59 }, // minute
  { min: 0, max: 23 }, // hour
  { min: 1, max: 31 }, // dayOfMonth
  { min: 1, max: 12 }, // month
  { min: 0, max: 6 }, // dayOfWeek (0=Sunday; 7 accepted as Sunday alias)
]
```

别名在 range 与单值两处都归一化（`src/shared/cron.ts`）：

```ts
      // dayOfWeek: accept 7 as Sunday alias in ranges (e.g. 5-7 = Fri,Sat,Sun → [5,6,0])
      const isDow = min === 0 && max === 6
      const effMax = isDow ? 7 : max
      if (lo > hi || step < 1 || lo < min || hi > effMax) return null
      for (let i = lo; i <= hi; i += step) {
        out.add(isDow && i === 7 ? 0 : i)
      }
      continue
    }

    // plain N
    const singleMatch = part.match(/^\d+$/)
    if (singleMatch) {
      let n = parseInt(part, 10)
      // dayOfWeek: accept 7 as Sunday alias → 0
      if (min === 0 && max === 6 && n === 7) n = 0
      if (n < min || n > max) return null
      out.add(n)
      continue
```

**拒绝 6 字段**：`parts.length !== 5` 直接返回 `null`（`src/shared/cron.ts`）：

```ts
/**
 * Parse a 5-field cron expression into expanded number arrays.
 * Returns null if invalid or unsupported syntax.
 */
export function parseCronExpression(expr: string): CronFields | null {
  const parts = expr.trim().split(/\s+/)
  if (parts.length !== 5) return null

  const expanded: number[][] = []
  for (let i = 0; i < 5; i++) {
    const result = expandField(parts[i]!, FIELD_RANGES[i]!)
    if (!result) return null
    expanded.push(result)
  }

  return {
    minute: expanded[0]!,
    hour: expanded[1]!,
    dayOfMonth: expanded[2]!,
    month: expanded[3]!,
    dayOfWeek: expanded[4]!,
  }
}
```

工具侧报 "Expected 5 fields"（`src/tools/ScheduleCronTool/CronCreateTool.ts`）：

```ts
  async validateInput(input): Promise<ValidationResult> {
    if (!parseCronExpression(input.cron)) {
      return {
        result: false,
        message: `Invalid cron expression '${input.cron}'. Expected 5 fields: M H DoM Mon DoW.`,
        errorCode: 1,
      }
    }
```

DOM 与 DOW 同时约束时取 OR；DST 间隙由逐分钟前向遍历处理（`src/utils/cron.ts`）：

```ts
    // When both dom/dow are constrained, either match is sufficient (OR semantics)
    const dayMatches =
      domWild && dowWild
        ? true
        : domWild
          ? dowSet.has(dow)
          : dowWild
            ? domSet.has(dom)
            : domSet.has(dom) || dowSet.has(dow)
```

## Jitter (Avoid the :00/:30 Herd)

抖动配置在 `src/utils/cronTasks.ts` 的 `DEFAULT_CRON_JITTER_CONFIG`（v0.7.7 增至 6 个字段，新增 `oneShotFloorMs`）：

```ts
export const DEFAULT_CRON_JITTER_CONFIG: CronJitterConfig = {
  recurringFrac: 0.1,
  recurringCapMs: 15 * 60 * 1000,
  oneShotMaxMs: 90 * 1000,
  oneShotFloorMs: 0,
  oneShotMinuteMod: 30,
  recurringMaxAgeMs: 7 * 24 * 60 * 60 * 1000,
}
```

字段语义（`src/utils/cronTasks.ts`）：

```ts
export type CronJitterConfig = {
  /** Recurring-task forward delay as a fraction of the interval between fires. */
  recurringFrac: number
  /** Upper bound on recurring forward delay regardless of interval length. */
  recurringCapMs: number
  /** One-shot backward lead: maximum ms a task may fire early. */
  oneShotMaxMs: number
  /**
   * One-shot backward lead: minimum ms a task fires early when the minute-mod
   * gate matches. 0 = taskIds hashing near zero fire on the exact mark. Raise
   * this to guarantee nobody lands on the wall-clock boundary.
   */
  oneShotFloorMs: number
  /**
   * Jitter fires landing on minutes where `minute % N === 0`. 30 → :00/:30
   * (the human-rounding hotspots). 15 → :00/:15/:30/:45. 1 → every minute.
   */
  oneShotMinuteMod: number
```

每任务确定性：`jitterFrac = parseInt(taskId.slice(0, 8), 16) / 2³²`，同一任务每次延迟一致（`src/utils/cronTasks.ts`）：

```ts
/**
 * taskId is an 8-hex-char UUID slice (see {@link addCronTask}) → parse as
 * u32 → [0, 1). Stable across restarts, uniformly distributed across the
 * fleet. Non-hex ids (hand-edited JSON) fall back to 0 = no jitter.
 */
function jitterFrac(taskId: string): number {
  const frac = parseInt(taskId.slice(0, 8), 16) / 0x1_0000_0000
  return Number.isFinite(frac) ? frac : 0
}
```

`recurring` 任务在周期基础上最多延迟 `recurringFrac`（`0.1`）倍、上限 `recurringCapMs`（15min）（`src/utils/cronTasks.ts`）：

```ts
export function jitteredNextCronRunMs(
  cron: string,
  fromMs: number,
  taskId: string,
  cfg: CronJitterConfig = DEFAULT_CRON_JITTER_CONFIG,
): number | null {
  const t1 = nextCronRunMs(cron, fromMs)
  if (t1 === null) return null
  const t2 = nextCronRunMs(cron, t1)
  // No second match in the next year (e.g. pinned date) → nothing to
  // proportion against, and near-certainly not a herd risk. Fire on t1.
  if (t2 === null) return t1
  const jitter = Math.min(
    jitterFrac(taskId) * cfg.recurringFrac * (t2 - t1),
    cfg.recurringCapMs,
  )
  return t1 + jitter
}
```

一次性任务若落在 `:00` / `:30`（`getMinutes() % oneShotMinuteMod === 0`）则**提前**最多 90s 触发（`src/utils/cronTasks.ts`）：

```ts
  if (new Date(t1).getMinutes() % cfg.oneShotMinuteMod !== 0) return t1
  // floor + frac * (max - floor) → uniform over [floor, max). With floor=0
  // this reduces to the original frac * max. With floor>0, even a taskId
  // hashing to 0 gets `floor` ms of lead — nobody fires on the exact mark.
  const lead =
    cfg.oneShotFloorMs +
    jitterFrac(taskId) * (cfg.oneShotMaxMs - cfg.oneShotFloorMs)
  // t1 > fromMs is guaranteed by nextCronRunMs (strictly after), so the
  // max() only bites when the task was created inside its own lead window.
  return Math.max(t1 - lead, fromMs)
```

动机：所有用户要「9am」都得到 `0 9`、要「每小时」都得到 `0 *`，会瞬间齐刷刷打向 API。模型 prompt 也主动要求避开 0/30 分（`src/tools/ScheduleCronTool/prompt.ts`）：

```text
Every user who asks for "9am" gets \`0 9\`, and every user who asks for "hourly" gets \`0 *\` — which means requests from across the planet land on the API at the same instant. When the user's request is approximate, pick a minute that is NOT 0 or 30:
```

> 注意：jitter 函数定义在 `src/utils/cronTasks.ts`，但**服务端 `cronScheduler.ts`（`src/server/services/`）本身不加 jitter**——它按精确分钟匹配触发（见上节 `cronMatches` 代码块）并依赖 `lastFiredAt` 做分钟级去重。抖动主要由 REPL 侧 `createCronScheduler`（`src/utils/cronScheduler.ts`）消费，见上节。

## Persistence and Run Logs

- **运行日志 canonical**：`~/.claude/scheduled_tasks_log.json`（用户级，`src/server/services/cronScheduler.ts`）：

```ts
function getLogFilePath(): string {
  const configDir =
    process.env.CLAUDE_CONFIG_DIR || path.join(os.homedir(), '.claude')
  return path.join(configDir, 'scheduled_tasks_log.json')
}
```

原子写入（tmp + rename）后派生 read model，派生失败不影响业务写入（`src/server/services/cronScheduler.ts`）：

```ts
  // The file is canonical. A derived-index failure must never turn a
  // successful task-history write into a failed business operation.
  if (resolveLocalIndexMode().mode === 'off') {
    deactivateScheduledRunReadModel(filePath)
  } else {
    void projectScheduledRunsAfterCanonicalWrite(
      filePath,
      serialized,
      data.runs,
      target.projectionTarget,
    ).catch(() => {})
  }
```

每任务保留 `MAX_RUNS_PER_TASK = 100` 条（`src/server/services/cronScheduler.ts`）：

```ts
const MAX_RUNS_PER_TASK = 100

/** Keep only the latest MAX_RUNS_PER_TASK entries per task. */
function trimRuns(data: RunsFile): void {
  const countByTask = new Map<string, number>()
  // Count from the end (newest first) and mark for removal
  const keep = new Array<boolean>(data.runs.length).fill(false)
  for (let i = data.runs.length - 1; i >= 0; i--) {
    const taskId = data.runs[i].taskId
    const count = countByTask.get(taskId) || 0
    if (count < MAX_RUNS_PER_TASK) {
      keep[i] = true
      countByTask.set(taskId, count + 1)
    }
  }
  data.runs = data.runs.filter((_, i) => keep[i])
}
```

`TaskRun` 形态含 status（running / completed / failed / timeout）、output、exitCode、durationMs、sessionId、notificationDecision 等（`src/server/services/cronScheduler.ts`）：

```ts
export type TaskRun = {
  id: string // random ID
  taskId: string // references CronTask.id
  taskName: string
  startedAt: string // ISO timestamp
  completedAt?: string
  status: 'running' | 'completed' | 'failed' | 'timeout'
  prompt: string
  output?: string // captured stdout summary
  error?: string
  exitCode?: number
  durationMs?: number
  occurrenceId?: string
  scheduledFor?: string
  notificationDecision?: 'notify' | 'silent'
  notificationPolicy?: 'important' | 'all' | 'failed' | 'none'
  sessionId?: string // links to a session for rich output rendering
}
```

- **派生索引（SQLite 已确认）**：canonical JSON → 经 `projectScheduledRunsAfterCanonicalWrite` 派生 read model，底层是 **`bun:sqlite`**（`src/server/services/localIndex/scheduledRunIndex.ts`）：

```ts
import { createHash } from 'node:crypto'
import { join } from 'node:path'
import { Database } from 'bun:sqlite'
```

落盘 `<getCcHahaDir()>/db/scheduled-runs-v1.sqlite`（`src/server/services/localIndex/scheduledRunIndex.ts`）：

```ts
export function getScheduledRunIndexDatabasePath(): string {
  return join(getCcHahaDir(), 'db', 'scheduled-runs-v1.sqlite')
}

export function openScheduledRunIndex(options?: {
  path?: string
  scope?: string
}): ScheduledRunIndex {
  const databasePath = options?.path ?? getScheduledRunIndexDatabasePath()
  prepareManagedDatabasePath({
    databasePath,
    filename: 'scheduled-runs-v1.sqlite',
    scope: options?.scope ?? (options?.path ? undefined : getClaudeConfigHomeDir()),
  })
  const database = new Database(databasePath)
```

表 `scheduled_runs` 与 `scheduled_run_source`（`src/server/services/localIndex/scheduledRunIndex.ts`）：

```ts
        database.exec('DELETE FROM scheduled_runs')
        const insert = database.query(`
          INSERT INTO scheduled_runs (
            run_id, task_id, started_at, started_at_ms, completed_at, completed_at_ms,
            status, has_output, has_error, exit_code, duration_ms, session_id,
            source_ordinal, revision
          ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        `)
```

```ts
          INSERT INTO scheduled_run_source (
            singleton, source_path, source_size, source_mtime_ms,
            source_fingerprint, revision, state, last_error_code, updated_at_ms
          ) VALUES (1, ?, ?, ?, ?, ?, 'ready', NULL, ?)
```

读模型支持按 `taskId` / `status` / `completedAfterMs` 过滤与游标分页（`src/server/services/cronScheduler.ts`）：

```ts
type ScheduledRunPageOptions = {
  taskId?: string
  limit?: number
  cursor?: string
  summaryOnly?: boolean
  nonterminalOnly?: boolean
  completedAfterMs?: number
}
```

上一轮「日志写 sqlite」的推断在此坐实——**canonical 是 JSON，派生索引确为 `bun:sqlite`**。

- **补跑**：durable 的 missed 一次性任务在下次启动时经 `findMissedTasks` 浮现补跑（`src/utils/cronTasks.ts`）：

```ts
/**
 * A task is "missed" when its next scheduled run (computed from createdAt)
 * is in the past. Surfaced to the user at startup. Works for both one-shot
 * and recurring tasks — a recurring task whose window passed while Claude
 * was down is still "missed".
 */
export function findMissedTasks(tasks: CronTask[], nowMs: number): CronTask[] {
  return tasks.filter(t => {
    const next = nextCronRunMs(t.cron, t.createdAt)
    return next !== null && next < nowMs
  })
}
```

服务端对**旧式独立任务**不重放错过的分钟窗口（`tick` 只在 `cronMatches(now)` 时触发），但对带 `schedule` 的会话型任务会按 `nextScheduledTime` 判断 `due <= now` 补跑一次（`src/server/services/cronScheduler.ts`）：

```ts
        // Skip if this process already fired the task in the current minute
        if (this.lastFiredMinuteKey.get(task.id) === currentKey) continue

        // Skip if ANY process already fired the task in the current minute
        // (cross-process guard via file-persisted lastFiredAt)
        if (task.lastFiredAt) {
          const lastFiredKey = CronScheduler.minuteKey(new Date(task.lastFiredAt))
          if (lastFiredKey === currentKey) continue
        }

        const scheduledDue = task.schedule ? nextScheduledTime(task.schedule, Math.max(task.scheduleAnchorAt ?? task.createdAt, task.lastFiredAt ? Date.parse(task.lastFiredAt) : 0)) : null
```

## Headless Execution

v0.7.7 服务端有**两条执行路径**：带 `execution` 的会话型任务经 `scheduledTaskHost.ts` 注入会话；旧式独立任务才用 `Bun.spawn` 起 headless CLI。`tick()` 的分叉（`src/server/services/cronScheduler.ts`）：

```ts
        if (task.execution) {
          if (task.schedule?.kind === 'once' && task.lastFiredAt && Date.parse(task.lastFiredAt) >= (task.scheduleAnchorAt ?? task.createdAt)) continue
          const due = task.schedule
            ? nextScheduledTime(task.schedule, Math.max(task.scheduleAnchorAt ?? task.createdAt, task.lastFiredAt ? Date.parse(task.lastFiredAt) : 0))
            : cronMatches(task.cron, now) ? Math.floor(now.getTime() / 60_000) * 60_000 : null
          if (due !== null && due <= now.getTime() && !this.sessionTasks.has(task.id)) {
            void this.launchSessionTask(task, new Date(due).toISOString()).catch(error => console.error('[CronScheduler] Session task failed:', error))
          }
          continue
        }
```

会话执行宿主在 server boot 时注册（`src/server/index.ts`）：

```ts
    const disposeScheduledTaskHost = configureScheduledTaskHost(localConnectHost, server.port)
```

`configureScheduledTaskHost` 把 executor 注入 `scheduledTaskExecution.ts`（`src/server/services/scheduledTaskHost.ts`）：

```ts
export function configureScheduledTaskHost(serverHost: string, serverPort: number): () => void {
  return setScheduledSessionTaskExecutor({
    async canStart(task) {
      return task.execution?.kind !== 'session' || getSessionTurnState(task.execution.targetSessionId) === 'idle'
    },
    execute: input => executeScheduledSessionTask(input, { serverHost, serverPort }),
  })
}
```

executor 接口（`src/server/services/scheduledTaskExecution.ts`）：

```ts
export type ScheduledSessionTaskExecutor = {
  canStart(task: CronTask): Promise<boolean>
  execute(input: ScheduledSessionTaskInput): Promise<ScheduledSessionTaskResult>
}
let executor: ScheduledSessionTaskExecutor | undefined
export function setScheduledSessionTaskExecutor(value: ScheduledSessionTaskExecutor): () => void {
  executor = value
  return () => { if (executor === value) executor = undefined }
}
export function getScheduledSessionTaskExecutor(): ScheduledSessionTaskExecutor | undefined { return executor }
```

会话型任务支持 `session` / `new-session` 两种模式，沿用会话权限、可选 worktree（`src/server/services/scheduledTaskHost.ts`）：

```ts
  const permissionMode = sourceInfo?.permissionMode ?? task.permissionMode ?? await new SettingsService().getPermissionMode()
  if (!await input.canSend()) throw new Error('Scheduled task changed before session creation')
  const created = await sessionService.createSession(workDir, task.useWorktree ? { worktree: true } : undefined, permissionMode)
```

最终通过 `submitScheduledTaskTurn` 把格式化后的 prompt 注入会话（`src/server/services/scheduledTaskHost.ts`）：

```ts
    const ack = await submitScheduledTaskTurn(target, formatScheduledTaskPrompt(input.task.prompt, input.runId, input.task.notificationPolicy === 'important'), {
      ...endpoint, messageId: input.occurrenceId, signal: input.signal,
      scheduledTask: { taskId: input.task.id, runId: input.runId, scheduledFor: input.scheduledFor, taskName: input.task.name || input.task.prompt.slice(0, 80) },
      canSend: () => !input.signal.aborted && !settled,
      beforeSend: input.canSend,
    })
```

旧式独立任务的 CLI 参数：固定 `--print --verbose --input-format stream-json --output-format stream-json`，经 `buildCronCliArgs` 解析 launcher 后 `Bun.spawn`（`src/server/services/cronScheduler.ts`）：

```ts
    const cliArgs = buildCronCliArgs([
      '--print',
      '--verbose',
      '--input-format',
      'stream-json',
      '--output-format',
      'stream-json',
      ...(sessionId ? ['--session-id', sessionId] : []),
      ...additionalDirectories.flatMap(directory => ['--add-dir', directory]),
      ...this.getRuntimeArgs(task),
    ])

    const taskTimeoutMs = resolveCronTaskTimeoutMs()
    const proc = Bun.spawn(
      cliArgs,
      buildCronTaskSpawnOptions(workDir, childEnv),
    )
```

`buildCronCliArgs` 现在负责解析 CLI launcher（`src/server/services/cronScheduler.ts`）：

```ts
export function buildCronCliArgs(
  baseArgs: string[],
  options: CronCliResolutionOptions = {},
): string[] {
  const launcher = resolveClaudeCliLauncher({
    cliPath: options.cliPath ?? process.env.CLAUDE_CLI_PATH,
    execPath: options.execPath ?? process.execPath,
  })

  if (launcher) {
    return buildClaudeCliArgs(
      launcher,
      baseArgs,
      options.appRoot ?? process.env.CLAUDE_APP_ROOT,
    )
  }

  const projectRoot = resolveCronProjectRoot(options)
  return [
    'bun',
    '--preload',
    path.join(projectRoot, 'preload.ts'),
    path.join(projectRoot, 'src', 'entrypoints', 'cli.tsx'),
    ...baseArgs,
  ]
}
```

**全权限运行**由 `getRuntimeArgs` 附加，`--model` 仅在 `task.model` 指定时附加（`src/server/services/cronScheduler.ts`）：

```ts
  private getRuntimeArgs(task: CronTask): string[] {
    const model = task.model?.trim()
    return [
      ...(model ? ['--model', model] : []),
      '--dangerously-skip-permissions',
      '--permission-mode',
      'bypassPermissions',
    ]
  }
```

`workdir = task.folderPath || homedir`，v0.7.7 用 `readProjectDirectory` 校验而非 `realpathSync`，仅在目录缺失/非目录时回退（`src/server/services/cronScheduler.ts`）：

```ts
    let workDir = task.folderPath || os.homedir()
    let additionalDirectories: string[] = []
    let directoryError: string | undefined
    let sessionId: string | undefined
    const releasePreparation = await acquireTaskPreparation()
    try {
      this.assertTaskPreparationAvailable(generation)
      try {
        try {
          workDir = (await readProjectDirectory({ kind: 'identity', path: path.resolve(workDir) })).directory
        } catch (error) {
          // Only a proven missing/non-directory legacy task target falls back.
          // A stalled or inaccessible target must never silently execute in HOME.
          if (!task.folderPath || !(error instanceof ProjectDirectoryIoError) ||
            (error.reason !== 'missing' && error.reason !== 'not-directory')) throw error
          console.warn(`[cron] task ${task.id}: folderPath "${task.folderPath}" is not a valid directory, falling back to homedir`)
          workDir = (await readProjectDirectory({ kind: 'identity', path: os.homedir() })).directory
        }
```

**仅手动「立即执行」才为独立 CLI 路径建 session**（`options.createSession`），自动触发跳过以免侧边栏刷屏（`src/server/services/cronScheduler.ts`）；该约束不适用于会话型任务——它们自动触发即走会话注入：

```ts
      // Only create a session when explicitly requested (manual "Run Now"),
      // not for automatic cron runs — avoids flooding the sidebar.
      if (options?.createSession && !directoryError) {
        try {
          const result = await this.sessionService.createSession(
            workDir,
            undefined,
            'bypassPermissions',
          )
          sessionId = result.sessionId
```

调度循环为 60s `setInterval`，`start()` 绑定服务端 boot，活动闸门是 `migrationMaintenance.isActive`（数据迁移暂停）（`src/server/services/cronScheduler.ts`）：

```ts
  /** Start the scheduler (called on server boot). */
  start(): void {
    if (migrationMaintenance.isActive) return
    if (this.intervalId) return // already running
    console.log('[CronScheduler] Starting — checking every 60 s')
    // Clean up stale "running" entries left by previously crashed processes
    migrationMaintenance.track(this.cleanupStaleRuns()).catch((err) =>
      console.error('[CronScheduler] Error cleaning up stale runs:', err),
    )
    migrationMaintenance.track(this.recoverSessionTaskReceipts()).catch(error => console.error('[CronScheduler] Cannot recover scheduled receipts:', error))
    this.intervalId = setInterval(() => this.tick(), 60_000)
    // Immediate first check
    this.tick()
  }
```

> 设计文档 `docs/desktop/schedule.md` 对权限的表述也已变化：会话型任务「沿用该会话的模型、权限和工作目录；不会因为设了定时任务就把会话升级成『所有权限』」，只有旧式独立任务保留「所有权限」。旧笔记称「权限固定为所有权限，工作目录选最小范围」已不完全成立，见 `## Corrections`。

## Cross-Session Lock

`src/utils/cronTasksLock.ts` 实现跨会话**租约锁**，仅服务于 REPL/SDK 侧同 cwd 防双触发（文件头说明）：

```ts
// Scheduler lease lock for .claude/scheduled_tasks.json.
//
// When multiple Claude sessions run in the same project directory, only one
// should drive the cron scheduler. The first session to acquire this lock
// becomes the scheduler; others stay passive and periodically probe the lock.
// If the owner dies (PID no longer running), a passive session takes over.
//
// Pattern mirrors computerUseLock.ts: O_EXCL atomic create, PID liveness
// probe, stale-lock recovery, cleanup-on-exit.
```

首个以 `O_EXCL` 原子创建成功（`flag:'wx'`）的会话成为调度者（`src/utils/cronTasksLock.ts`）：

```ts
async function tryCreateExclusive(
  lock: SchedulerLock,
  dir?: string,
): Promise<boolean> {
  const path = getLockPath(dir)
  const body = jsonStringify(lock)
  try {
    await writeFile(path, body, { flag: 'wx' })
    return true
  } catch (e: unknown) {
    const code = getErrnoCode(e)
    if (code === 'EEXIST') return false
    if (code === 'ENOENT') {
      // .claude/ doesn't exist yet — create it and retry once. In steady
      // state the dir already exists (scheduled_tasks.json lives there),
      // so this path is hit at most once.
      await mkdir(dirname(path), { recursive: true })
      try {
        await writeFile(path, body, { flag: 'wx' })
        return true
      } catch (retryErr: unknown) {
        if (getErrnoCode(retryErr) === 'EEXIST') return false
        throw retryErr
      }
    }
    throw e
  }
}
```

owner 死亡经 PID 存活检测（`isProcessRunning`），陈旧锁 unlink 后重抢（`src/utils/cronTasksLock.ts`）：

```ts
  // Corrupt or unparseable — treat as stale.
  // Another live session — blocked.
  if (existing && isProcessRunning(existing.pid)) {
    if (lastBlockedBy !== existing.sessionId) {
      lastBlockedBy = existing.sessionId
      logForDebugging(
        `[ScheduledTasks] scheduler lock held by session ${existing.sessionId} (PID ${existing.pid})`,
      )
    }
    return false
  }

  // Stale — unlink and retry the exclusive create once.
  if (existing) {
    logForDebugging(
      `[ScheduledTasks] recovering stale scheduler lock from PID ${existing.pid}`,
    )
  }
  await unlink(getLockPath(dir)).catch(() => {})
  if (await tryCreateExclusive(lock, dir)) {
    lastBlockedBy = undefined
    registerLockCleanup(opts)
    return true
  }
  // Another session won the recovery race.
  return false
```

退出时经 `registerCleanup` 释放（`src/utils/cronTasksLock.ts`）：

```ts
export async function releaseSchedulerLock(
  opts?: SchedulerLockOptions,
): Promise<void> {
  unregisterCleanup?.()
  unregisterCleanup = undefined
  lastBlockedBy = undefined

  const dir = opts?.dir
  const sessionId = opts?.lockIdentity ?? getSessionId()
  const existing = await readLock(dir)
  if (!existing || existing.sessionId !== sessionId) return
  try {
    await unlink(getLockPath(dir))
    logForDebugging('[ScheduledTasks] released scheduler lock')
  } catch {
    // Already gone.
  }
}
```

**服务端调度器不使用该租约**，而是进程内 `lastFiredMinuteKey` + `runningTasks` / `standaloneTaskPromises` 去重，并用文件持久化的 `lastFiredAt` 做跨进程分钟级去重（`src/server/services/cronScheduler.ts`）：

```ts
export class CronScheduler {
  private intervalId: Timer | null = null
  private sessionTasks = new Map<string, AbortController>()
  private sessionTaskPromises = new Set<Promise<TaskRun | undefined>>()
  private standaloneTaskPromises = new Map<string, Promise<TaskRun>>()
  private stopGeneration = 0
  private runningTasks = new Map<
    string,
    { proc: ReturnType<typeof Bun.spawn>; startedAt: number; runId: string; resultReceived?: boolean; resultSucceeded?: boolean; migrationInterrupted?: boolean }
  >()
  /** Track which minute each task last fired (prevents same-process duplicate within a minute). */
  private lastFiredMinuteKey = new Map<string, string>()
```

```ts
        // Skip if already running (in-memory guard — same process)
        if (this.runningTasks.has(task.id) || this.standaloneTaskPromises.has(task.id)) continue

        // Skip if this process already fired the task in the current minute
        if (this.lastFiredMinuteKey.get(task.id) === currentKey) continue

        // Skip if ANY process already fired the task in the current minute
        // (cross-process guard via file-persisted lastFiredAt)
        if (task.lastFiredAt) {
          const lastFiredKey = CronScheduler.minuteKey(new Date(task.lastFiredAt))
          if (lastFiredKey === currentKey) continue
        }
```

## Auto-Expire

`recurringMaxAgeMs` 默认 `7 × 24 × 60 × 60 × 1000`（**7 天**，`src/utils/cronTasks.ts`）；`DEFAULT_MAX_AGE_DAYS` 由它换算而来（`src/tools/ScheduleCronTool/prompt.ts`）：

```ts
export const DEFAULT_MAX_AGE_DAYS =
  DEFAULT_CRON_JITTER_CONFIG.recurringMaxAgeMs / (24 * 60 * 60 * 1000)
```

`isRecurringTaskAged` 判定 `recurring && !permanent && nowMs - createdAt >= maxAgeMs`（`src/utils/cronScheduler.ts`）：

```ts
/**
 * True when a recurring task was created more than `maxAgeMs` ago and should
 * be deleted on its next fire. Permanent tasks never age. `maxAgeMs === 0`
 * means unlimited (never ages out). Sourced from
 * {@link CronJitterConfig.recurringMaxAgeMs} at call time.
 * Extracted for testability — the scheduler's check() is buried under
 * setInterval/chokidar/lock machinery.
 */
export function isRecurringTaskAged(
  t: CronTask,
  nowMs: number,
  maxAgeMs: number,
): boolean {
  if (maxAgeMs === 0) return false
  return Boolean(t.recurring && !t.permanent && nowMs - t.createdAt >= maxAgeMs)
}
```

老化任务**最后触发一次**后落删除路径（`tengu_scheduled_task_expired` 事件），见 `## REPL Scheduler` 的 `check()` 代码块。设计文档承诺「触发最后一次后删除」，模型 prompt 也明确告知 7 天上限（`src/tools/ScheduleCronTool/prompt.ts`）：

```text
Recurring tasks auto-expire after ${DEFAULT_MAX_AGE_DAYS} days — they fire one final time, then are deleted. This bounds session lifetime. Tell the user about the ${DEFAULT_MAX_AGE_DAYS}-day limit when scheduling recurring jobs.
```

关于 `permanent:true`：`src/utils/cronTasks.ts` 的注释仍写「only written directly to scheduled_tasks.json by src/assistant/install.ts」，但 v0.7.7 里 `src/assistant/` 全是 `// @generated stub from scan-missing-imports` 占位文件、`install.ts` 根本不存在（区分 stub 占位与真实实现）：

```ts
// @generated stub from scan-missing-imports
// 该文件自动生成，对应 ant-internal 的 feature() gated 模块。
// 所有外部 build 的代码路径在 DCE 后都不会真的执行这里的代码，这只是
// bun build resolver 的占位符。
```

全仓非测试代码里 `permanent` 只剩 `src/utils/cronTasks.ts` 的写盘透传，不能再把 `install.ts` 当真实实现引用：

```ts
      ...(t.permanent ? { permanent: true } : {}),
```

一次性任务触发后自动禁用已实装（服务端 `src/server/services/cronScheduler.ts` 会话型与独立路径；工具集 `src/utils/cronTasks.ts` 的 `removeCronTasks`）：

```ts
      if (task.schedule?.kind === 'once' || !task.recurring) {
        const latest = await this.cronService.getTask(task.id)
        const sameSchedule = latest && JSON.stringify(latest.schedule) === JSON.stringify(task.schedule) && latest.scheduleAnchorAt === task.scheduleAnchorAt
        if (sameSchedule && latest.enabled !== false) await this.cronService.updateTask(task.id, { enabled: false, completedAt: completed.completedAt }, { expectedRevision: latest.revision ?? 1 }).catch(() => {})
      }
```

## End-to-end Lifecycle (Model CronCreate → Schedule → Fire)

完整闭环：模型调 `CronCreate` → REPL 调度器落到点 → 触发时把 prompt 注入命令队列，在 turns 之间执行。

**模型侧工具（4 个）**：`src/tools/ScheduleCronTool/` 暴露 `CronCreate` / `CronUpdate` / `CronDelete` / `CronList`（工具名见 `src/tools/ScheduleCronTool/prompt.ts`）：

```ts
export const CRON_CREATE_TOOL_NAME = 'CronCreate'
export const CRON_UPDATE_TOOL_NAME = 'CronUpdate'
export const CRON_DELETE_TOOL_NAME = 'CronDelete'
export const CRON_LIST_TOOL_NAME = 'CronList'
```

`CronCreate` 的入参是 `z.strictObject`，`cron` 为 5 字段、`recurring` 默认 `true`、`durable` 默认 `false`（`src/tools/ScheduleCronTool/CronCreateTool.ts`）：

```ts
const MAX_JOBS = 50

const inputSchema = lazySchema(() =>
  z.strictObject({
    cron: z
      .string()
      .describe(
        'Standard 5-field cron expression in local time: "M H DoM Mon DoW" (e.g. "*/5 * * * *" = every 5 minutes, "30 14 28 2 *" = Feb 28 at 2:30pm local once).',
      ),
    prompt: z.string().describe('The prompt to enqueue at each fire time.'),
    recurring: semanticBoolean(z.boolean().optional()).describe(
      `true (default) = fire on every cron match until deleted or auto-expired after ${DEFAULT_MAX_AGE_DAYS} days. false = fire once at the next match, then auto-delete. Use false for "remind me at X" one-shot requests with pinned minute/hour/dom/month.`,
    ),
    durable: semanticBoolean(z.boolean().optional()).describe(
      'true = persist to .claude/scheduled_tasks.json and survive restarts. false (default) = in-memory only, dies when this Claude session ends. Use true only when the user asks the task to survive across sessions.',
    ),
  }),
)
```

`CronCreateTool` 关键约束：上限 `MAX_JOBS = 50`（`validateInput` 超 50 报 `Too many scheduled jobs`，`errorCode:3`）、teammate 不支持 durable（`errorCode:4`）、cron 非法 `errorCode:1`、一年内无匹配 `errorCode:2`（`src/tools/ScheduleCronTool/CronCreateTool.ts`）：

```ts
  async validateInput(input): Promise<ValidationResult> {
    if (!parseCronExpression(input.cron)) {
      return {
        result: false,
        message: `Invalid cron expression '${input.cron}'. Expected 5 fields: M H DoM Mon DoW.`,
        errorCode: 1,
      }
    }
    if (nextCronRunMs(input.cron, Date.now()) === null) {
      return {
        result: false,
        message: `Cron expression '${input.cron}' does not match any calendar date in the next year.`,
        errorCode: 2,
      }
    }
    const tasks = await listAllCronTasks()
    if (tasks.length >= MAX_JOBS) {
      return {
        result: false,
        message: `Too many scheduled jobs (max ${MAX_JOBS}). Cancel one first.`,
        errorCode: 3,
      }
    }
    // Teammates don't persist across sessions, so a durable teammate cron
    // would orphan on restart (agentId would point to a nonexistent teammate).
    if (input.durable && getTeammateContext()) {
      return {
        result: false,
        message:
          'durable crons are not supported for teammates (teammates do not persist across sessions)',
        errorCode: 4,
      }
    }
    return { result: true }
  },
```

**双重 gate**：`isKairosCronEnabled()` = 编译期 `feature('AGENT_TRIGGERS')`（bun bundle dead-code elimination）**且**运行时 GrowthBook `tengu_kairos_cron`（5 分钟刷新窗口，`KAIROS_CRON_REFRESH_MS`）；`CronCreateTool.isEnabled()` 直接返回它（`src/tools/ScheduleCronTool/prompt.ts`）：

```ts
export function isKairosCronEnabled(): boolean {
  return feature('AGENT_TRIGGERS')
    ? !isEnvTruthy(process.env.CLAUDE_CODE_DISABLE_CRON) &&
        getFeatureValue_CACHED_WITH_REFRESH(
          'tengu_kairos_cron',
          true,
          KAIROS_CRON_REFRESH_MS,
        )
    : false
}
```

**kill switch 强制 session-only**：`effectiveDurable = durable && isDurableCronEnabled()`（`tengu_kairos_cron_durable` 关则降级为 `false`，schema 不变故模型无感）；`call()` 写项目级文件 / session store，再 `setScheduledTasksEnabled(true)` 让 `useScheduledTasks` 下一 tick 起开始 watch（`src/tools/ScheduleCronTool/CronCreateTool.ts`）：

```ts
  async call({ cron, prompt, recurring = true, durable = false }) {
    // Kill switch forces session-only; schema stays stable so the model sees
    // no validation errors when the gate flips mid-session.
    const effectiveDurable = durable && isDurableCronEnabled()
    const id = await addCronTask(
      cron,
      prompt,
      recurring,
      effectiveDurable,
      getTeammateContext()?.agentId,
    )
    // Enable the scheduler so the task fires in this session. The
    // useScheduledTasks hook polls this flag and will start watching
    // on the next tick. For durable: false tasks the file never changes
    // — check() reads the session store directly — but the enable flag
    // is still what starts the tick loop.
    setScheduledTasksEnabled(true)
    return {
      data: {
        id,
        humanSchedule: cronToHuman(cron),
        recurring,
        durable: effectiveDurable,
      },
    }
  },
```

**REPL 接线层 `useScheduledTasks`**：`src/hooks/useScheduledTasks.ts` 是 React 薄层，把 `createCronScheduler` 接进 UI。`enqueueForLead` 用 `enqueuePendingNotification({ mode:'prompt', priority:'later', isMeta:true, workload:WORKLOAD_CRON })`，隐藏于队列预览与 transcript UI，billing 标低 QoS；命令队列由 `useCommandQueue` 在 turns 之间 drain：

```ts
    const enqueueForLead = (prompt: string) =>
      enqueuePendingNotification({
        value: prompt,
        mode: 'prompt',
        priority: 'later',
        isMeta: true,
        // Threaded through to cc_workload= in the billing-header
        // attribution block so the API can serve cron-initiated requests
        // at lower QoS when capacity is tight. No human is actively
        // waiting on this response.
        workload: WORKLOAD_CRON,
      })
```

`useEffect`（仅 `assistantMode` 为 dep）挂载一次、卸载 `stop()`；runtime gate 在 effect 内检查，mid-session killswitch 由 `isKilled` 每 tick 轮询；`onFireTask` 是触发出口：teammate cron（有 `agentId`）路由到对应 teammate，终态则清理孤儿 cron；team-lead durable cron 插入「Running scheduled task」消息 + `enqueueForLead(prompt)`（`src/hooks/useScheduledTasks.ts`）：

```ts
    const scheduler = createCronScheduler({
      // Missed-task surfacing (onFire fallback). Teammate crons are always
      // session-only (durable:false) so they never appear in the missed list,
      // which is populated from disk at scheduler startup — this path only
      // handles team-lead durable crons.
      onFire: enqueueForLead,
      // Normal fires receive the full CronTask so we can route by agentId.
      onFireTask: task => {
        if (task.agentId) {
          const teammate = findTeammateTaskByAgentId(
            task.agentId,
            store.getState().tasks,
          )
          if (teammate && !isTerminalTaskStatus(teammate.status)) {
            injectUserMessageToTeammate(teammate.id, task.prompt, setAppState)
            return
          }
          // Teammate is gone — clean up the orphaned cron so it doesn't keep
          // firing into nowhere every tick. One-shots would auto-delete on
          // fire anyway, but recurring crons would loop until auto-expiry.
          logForDebugging(
            `[ScheduledTasks] teammate ${task.agentId} gone, removing orphaned cron ${task.id}`,
          )
          void removeCronTasks([task.id])
          return
        }
        const msg = createScheduledTaskFireMessage(
          `Running scheduled task (${formatCronFireTime(new Date())})`,
        )
        setMessages(prev => [...prev, msg])
        enqueueForLead(task.prompt)
      },
      isLoading: () => isLoadingRef.current,
      assistantMode,
      getJitterConfig: getCronJitterConfig,
      isKilled: () => !isKairosCronEnabled(),
    })
    scheduler.start()
    return () => scheduler.stop()
```

**闭环路径**：模型 `CronCreate` → `addCronTask` 落盘 / 入 session store + 置 enable 标志 → `createCronScheduler` 1s tick 命中（`jitteredNextCronRunMs` 锚 `lastFiredAt ?? createdAt`）→ `onFireTask` → `enqueueForLead(prompt)` 以 `later` 优先级进命令队列 → `useCommandQueue` 在 turn 间隙派发 → 模型执行该 prompt。recurring 循环；一次性触发后自删；recurring 超 7 天（`recurringMaxAgeMs`）先触发一次再删。

## Corrections

| 旧描述 | 源码事实 |
| --- | --- |
| 只在桌面打开且唤醒时跑；合盖 / 退出 / 关机都不会跑，也**不会补跑**。 | `docs/desktop/schedule.md` 明确：会话型任务错过时间会在应用恢复且目标会话空闲时**补执行一次**；周期任务不重放每个周期；旧的独立 Cron 任务保持原行为不补跑。 |
| 两套引擎都依赖同一套自研 5 字段 cron 与抖动（jitter）算法。 | 服务端 `src/server/services/cronScheduler.ts` 自带 `fieldMatches` / `cronMatches`，且**完全不消费 jitter**；jitter 只在 `src/utils/cronScheduler.ts`（REPL/SDK）里消费。二者不共享解析器与抖动。 |
| `src/utils/cron.ts` 内定义 `parseCronExpression`、`expandField`、`computeNextCronRun`。 | `parseCronExpression` 与 `expandField` 已迁到 `src/shared/cron.ts`；`src/utils/cron.ts` 只 re-export `parseCronExpression`，并保留 `computeNextCronRun` / `cronToHuman`。 |
| 两套引擎经 `cronTasksLock.ts` 的跨会话租约避免重复触发。 | `cronTasksLock.ts` 只被 `src/utils/cronScheduler.ts` 引用（REPL/SDK 同 cwd 防双触发）；服务端用 `lastFiredMinuteKey` + 文件持久化 `lastFiredAt` + `ScheduledTaskReceipt` 去重，不 import 该锁。 |
| 服务端 `CronService` 每次读 / 写都强制 `permissionMode:'bypassPermissions'`。 | 仅当任务**没有** `execution`（旧式独立任务）时才注入 `permissionMode: 'bypassPermissions'`（`createTask` / `updateTask` / `snapshot` 的 `...(task.execution ? {} : { permissionMode: 'bypassPermissions' })`）；会话型任务沿用会话权限，不升级为「所有权限」。 |
| `executeTaskOnce` 用 `Bun.spawn` 起 headless CLI 是服务端唯一执行方式；仅手动「立即执行」才建 session。 | v0.7.7 有两条路径：带 `execution` 的任务经 `scheduledTaskHost.ts` → `scheduledTaskExecution.ts` → `submitScheduledTaskTurn` 注入会话（自动触发即如此）；只有旧式独立任务才走 `Bun.spawn` CLI，`options.createSession` 的「仅手动」约束只对该 CLI 路径成立。 |
| `buildCronCliArgs` 解析固定的 headless 启动参数。 | `buildCronCliArgs(baseArgs, options)` 现在负责解析 CLI launcher（`resolveClaudeCliLauncher` / `buildClaudeCliArgs`），flags 由调用处数组传入；`getRuntimeArgs` 提供 `--dangerously-skip-permissions --permission-mode bypassPermissions` 与可选 `--model`。 |
| `workdir = task.folderPath \|\| homedir`，经 `realpathSync` 解析。 | `src/server/services/cronScheduler.ts` 用 `readProjectDirectory({ kind:'identity', path: path.resolve(workDir) })` 校验，仅目录缺失 / 非目录时回退 homedir，不是 `realpathSync`。 |
| Worktree 字段被存储，但 spawn 时未传 `--worktree` 标志。 | 会话型任务有 first-class `useWorktree`：`scheduledTaskHost.ts` 里 `sessionService.createSession(workDir, task.useWorktree ? { worktree: true } : undefined, permissionMode)`；旧式独立 CLI 路径仍不传 `--worktree`。 |
| 服务端调度器不重放错过的分钟窗口。 | 对旧式独立任务成立（`cronMatches(now)` 精确分钟匹配）；但带 `schedule` 的会话型任务经 `nextScheduledTime(schedule, ...)` 判断 `due <= now` 会补跑一次。 |
| `permanent:true` 仅 `src/assistant/install.ts` 设置。 | v0.7.7 的 `src/assistant/` 全是 `// @generated stub from scan-missing-imports` 占位文件，`install.ts` 根本不存在；全仓非测试代码里 `permanent` 只剩 `src/utils/cronTasks.ts` 的写盘透传 `...(t.permanent ? { permanent: true } : {})` 与类型注释。**不能把 stub 占位当真实实现引用**。 |
| 模型侧工具只有 4 个 `CronCreate` / `CronUpdate` / `CronDelete` / `CronList`。 | v0.7.7 新增面向桌面持久化任务的 `ScheduledTaskTool`（`src/tools/ScheduledTaskTool/`），动作含 `list` / `view` / `create` / `update` / `delete` / `runs` / `run` / `report`，与旧的会话内 `ScheduleCronTool` 并存。 |
| `DEFAULT_CRON_JITTER_CONFIG` 为 5 字段；jitter 配置刷新窗口 5 分钟。 | 字段增至 6 个，新增 `oneShotFloorMs`（默认 0）；`src/utils/cronJitterConfig.ts` 的 `JITTER_CONFIG_REFRESH_MS = 60 * 1000`（jitter 配置）与 gate 的 `KAIROS_CRON_REFRESH_MS = 5 * 60 * 1000` 是两个不同 config。 |
| 设计文档「权限固定为所有权限，工作目录选最小范围」。 | `docs/desktop/schedule.md` 改为：会话型任务沿用会话的模型、权限、工作目录，不因定时任务升级为「所有权限」；只有旧式独立任务保留「所有权限」。 |

## Links

- [CcHaha 主枢纽](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md)
- [Integrations](/docs/CS/AI/LLM/Agent/Product/CcHaha/Integrations.md)
- [AgentTeams](/docs/CS/AI/LLM/Agent/Product/CcHaha/AgentTeams.md)
- [REPL](/docs/CS/AI/LLM/Agent/Product/CcHaha/REPL.md)
- [Persistence](/docs/CS/AI/LLM/Agent/Product/CcHaha/Persistence.md)

## References

- [cc-haha GitHub](https://github.com/NanmiCoder/cc-haha)
- [schedule.md 设计文档](https://github.com/NanmiCoder/cc-haha/blob/main/docs/desktop/schedule.md)
- [cronScheduler.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/server/services/cronScheduler.ts)
- [cronTasks.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/cronTasks.ts)
- [CronCreateTool.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/ScheduleCronTool/CronCreateTool.ts)
- [prompt.ts (ScheduleCronTool)](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/ScheduleCronTool/prompt.ts)
- [useScheduledTasks.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/hooks/useScheduledTasks.ts)
- [cron.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/cron.ts)
- [cronTasksLock.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/cronTasksLock.ts)
- [cronService.ts（服务端 HTTP API 任务存储）](https://github.com/NanmiCoder/cc-haha/blob/main/src/server/services/cronService.ts)
- [utils/cronScheduler.ts（REPL/SDK 调度内核）](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/cronScheduler.ts)
- [cronJitterConfig.ts（GrowthBook jitter 配置）](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/cronJitterConfig.ts)
- [scheduledRunIndex.ts（bun:sqlite 派生索引）](https://github.com/NanmiCoder/cc-haha/blob/main/src/server/services/localIndex/scheduledRunIndex.ts)
