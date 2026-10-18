## Introduction

计划任务是 cc-haha（及上游 Claude Code 的 Kairos cron）相对多数 agent 工作台的明显差异化能力：**把一段提示词按时间自动跑**，典型用法是每天审一遍提交、每周整理待办、每小时查一次日志。它不是云端调度器——只在桌面应用打开、且电脑处于唤醒状态时运行，合盖 / 退出 / 关机都不会跑，也不会补跑（`docs/desktop/schedule.md:18-20`）。

底层有两套**相互独立**的引擎：模型可调的 `CronCreate` 工具集（会话内 + 可持久化到磁盘），以及桌面服务端支撑 UI 向导的 headless 调度器。两者都依赖同一套自研 5 字段 cron 与抖动（jitter）算法。

## Two Independent Engines

- **(a) 模型可调工具集** —— `CronCreate` / `CronUpdate` / `CronDelete` / `CronList`（`src/tools/ScheduleCronTool/*`）。经 `src/utils/cronTasks.ts` 落库：`durable:true` 写 `<project>/.claude/scheduled_tasks.json`（`cronTasks.ts:113-115,214-248`）；`durable:false` 仅存于内存会话 store（`cronTasks.ts:300-339`）。由 REPL 侧调度器（`useScheduledTasks.ts` / `createCronScheduler`）触发，引用分散在注释里（`cronJitterConfig.ts:8,64`；`CronCreateTool.ts:129`）。
- **(b) 服务端调度器** —— `src/server/services/cronScheduler.ts` 单例 `cronScheduler`（`cronScheduler.ts:1228`，60s `setInterval` headless），支撑侧边栏 UI 向导（`docs/desktop/schedule.md`）与本地 HTTP API。任务列表由 `CronService`（`src/server/services/cronService.ts`，非 `.js`）管理：CRUD 落在**用户级** `~/.claude/scheduled_tasks.json`，每次读/写都强制 `permissionMode:'bypassPermissions'`，用模块级 per-file 互斥队列 `mutationQueues` 防止「调度器并发写 lastFired」与「API 增删改」互相覆盖丢失，原子写入走 tmp+rename（2 次重试，EPERM/ENOENT 可重试）。**不** import `cronTasks.ts`。

> 两套引擎写**两个不同的** `scheduled_tasks.json`：工具集写 `<project>/.claude/scheduled_tasks.json`（项目级，REPL 调度器 `createCronScheduler` 驱动）；服务端调度器经 `CronService` 写 `~/.claude/scheduled_tasks.json`（用户级，HTTP API / UI 向导驱动），运行日志另存 `~/.claude/scheduled_tasks_log.json`（canonical）+ `bun:sqlite` 派生索引。两者通过 `cronTasksLock.ts` 的跨会话租约避免重复触发。

## REPL Scheduler (createCronScheduler)

与引擎 (b) 的 headless 单例不同，交互式 REPL / Agent SDK（`-p` 模式）走 **`src/utils/cronScheduler.ts`** 的 `createCronScheduler` —— 一个**非 React 的纯调度内核**，被 `useScheduledTasks`（REPL）与 `print.ts`（SDK/-p）共用（`cronScheduler.ts:1-7`）。它才是真正**消费 jitter、跑 7 天自动过期删除循环**的组件（上一轮笔记标注的「缺失的 REPL 调度器」即此文件）。

**生命周期**（`cronScheduler.ts:4-7,396+`）：轮询 `getScheduledTasksEnabled()` 直到为 true（首次 `CronCreate` 或 skill `on:` 触发会翻转该 flag）→ 加载任务 + `chokidar` 监听文件 + 起 **1s** `check` 定时器 → 到点 `onFire(prompt)` → `stop()` 拆除。计时器常量：`CHECK_INTERVAL_MS=1000`、`FILE_STABILITY_MS=300`、`LOCK_PROBE_INTERVAL_MS=5000`。

**`CronSchedulerOptions`**（按需注入，`cronScheduler.ts:62-128`）：
- `onFire(prompt)` / `onFireTask(task)`：触发回调；daemon 用 `onFireTask` 拿到完整 `CronTask`（id/cron 等）而非纯 prompt 串。
- `isLoading()`：加载闸门，`assistantMode` 可绕过。
- `getJitterConfig()`：REPL 注入 GrowthBook 支持的实现（`cronJitterConfig.getCronJitterConfig` 读 `tengu_kairos_cron_config`），做到**不重启热调 jitter 窗口**；SDK/daemon 省略 → 回退 `DEFAULT_CRON_JITTER_CONFIG`。
- `isKilled()`：killswitch，每次 `check()` 轮询；CLI 注入 `()=>!isKairosCronEnabled()` 关掉 gate 即终止在跑调度器。
- `filter(t)`：per-task 闸门（daemon worker 用 `t=>t.permanent`，让同文件非永久任务对其不可见）。
- `dir` / `lockIdentity`：Agent SDK daemon 必填（无 session），绕过 bootstrap 状态与 enable 轮询。

**`check()` 的 jitter 消费与过期删除**（`cronScheduler.ts:230-394`）——这是 jitter 与 auto-expire 的真正落点：
- 每个 tick 先取 `jitterCfg = getJitterConfig?.() ?? DEFAULT_CRON_JITTER_CONFIG`（`:243`）。
- 每个任务首次见到时按 `recurring` 调 `jitteredNextCronRunMs` / `oneShotJitteredNextCronRunMs` 计算 `nextFireAt`（`:265-276`），锚点取 `lastFiredAt ?? createdAt`（避免 `isLoading` 延迟导致钉死 cron 算到明年）；触发后 recurring 从 `now` 重排（`:319-321`），jitter 保证每轮都偏离精确 `:00` 墙钟。
- **7 天自动过期**：`isRecurringTaskAged(t, now, jitterCfg.recurringMaxAgeMs)`（`:53-60,302`）——`recurring && !permanent && now-createdAt >= recurringMaxAgeMs` 即判老化；老化任务**最后触发一次**后落删除路径（`:302-313`，`tengu_scheduled_task_expired` 事件），解决了上一轮「强制删除循环代码不在切片内」的待核实项。
- 文件任务仅在**持有调度锁**时处理（双 Claude 同 cwd 防双触发）；会话任务进程私有、无需锁，每 tick 从 bootstrap 重读（`:347-378`）。

> 注意区分两个 `cronScheduler.ts`：本节的 `src/utils/cronScheduler.ts`（REPL/SDK 内核，1s tick，chokidar，消费 jitter + 跑过期）与引擎 (b) 的 `src/server/services/cronScheduler.ts`（服务端子进程，60s tick，spawn CLI）。二者**不互相 import**，但都最终驱动同一类任务。

## Cron Expression

标准 **5 字段** `分 时 日 月 星期`，按**用户本地时区**解析（`CronCreateTool/prompt.ts:90`）。**自研解析器、不依赖第三方库**：`parseCronExpression`（`cron.ts:83-101`）、`expandField`（`cron.ts:31-77`）、`computeNextCronRun`（`cron.ts:119-181`）。

- **拒绝 6 字段**：`parts.length !== 5` 直接返回 `null`，工具侧报 "Expected 5 fields"（`cron.ts:83-85`；`CronCreateTool.ts:86`；`cronScheduler.ts:198-200`）。
- 额外语义：周日 `7` 作为 `0` 的别名（`cron.ts:25,52-57,66`）；DOM 与 DOW 同时约束时取 OR（`cron.ts:150-158`）；DST 间隙有专门处理（`cron.ts:112-118`）。

## Jitter (Avoid the :00/:30 Herd)

抖动配置在 `DEFAULT_CRON_JITTER_CONFIG`（`cronTasks.ts:504-511`）：

- `recurringFrac = 0.1` —— recurring 任务在其周期的基础上**最多延迟 10%** 触发，上限 `recurringCapMs = 15min`（`jitteredNextCronRunMs`，`cronTasks.ts:537-554`）。
- `oneShotMaxMs = 90s` —— 一次性任务若落在 `:00` / `:30`（即 `fireMinute % oneShotMinuteMod(30) === 0`），**提前最多 90s** 触发（`oneShotJitteredNextCronRunMs`，`cronTasks.ts:577-601`）。
- 每任务确定性：`jitterFrac = u32(taskId) / 2³²`（`cronTasks.ts:518-521`），同一任务每次延迟一致，全队不均。
- 动机：所有用户要「9am」都得到 `0 9`、要「每小时」都得到 `0 *`，会瞬间齐刷刷打向 API。模型 prompt 也主动要求避开 0/30 分（`CronCreateTool/prompt.ts:104-111,117`）。

> 注意：jitter 函数定义在 `cronTasks.ts`，但**服务端 `cronScheduler.ts`（`src/server/services/`）本身不加 jitter**——它按精确分钟匹配触发（`cronMatches`，`cronScheduler.ts:619`）并依赖 `lastFiredAt` 做分钟级去重（`cronScheduler.ts:613-617`）。抖动主要由 REPL 侧 `createCronScheduler`（`src/utils/cronScheduler.ts:243,265`）消费，见上节。

## Persistence and Run Logs

- **运行日志 canonical**：`~/.claude/scheduled_tasks_log.json`（用户级，`cronScheduler.ts:246-250`），原子写入（tmp + rename，`cronScheduler.ts:300-317`），每任务保留 `MAX_RUNS_PER_TASK = 100` 条（`cronScheduler.ts:422,425-438`）。`TaskRun` 形态含 status（running / completed / failed / timeout）、output、exitCode、durationMs、sessionId（`cronScheduler.ts:50-63`）。
- **派生索引（SQLite 已确认）**：canonical JSON → 经 `projectScheduledRunsAfterCanonicalWrite` 派生 read model（`cronScheduler.ts:36-42,318-329`），底层是 **`bun:sqlite`**（`scheduledRunIndex.ts:3`）：落盘 `<getCcHahaDir()>/db/scheduled-runs-v1.sqlite`（`scheduledRunIndex.ts:299,309`），表 `scheduled_runs`（`run_id/task_id/started_at/completed_at/status/has_output/has_error/exit_code/duration_ms/session_id`）+ `scheduled_run_source`（`sourceFingerprint/revision`）；读模型支持按 `taskId`/`status`/`completedAfterMs` 过滤与游标分页（`scheduledRunIndex.ts:411-456`）。上一轮「日志写 sqlite」的推断在此坐实——**canonical 是 JSON，派生索引确为 `bun:sqlite`**。
- **补跑**：durable 的 missed 一次性任务在下次启动时经 `findMissedTasks` 浮现补跑（`cronTasks.ts:609-614`；`prompt.ts:85`）；但**服务端调度器不重放**错过的分钟窗口（`tick` 只在 `cronMatches(now)` 时触发，`cronScheduler.ts:619`），与「睡眠不补跑」的设计一致。

## Headless Execution

`executeTaskOnce` 用 `Bun.spawn(cliArgs, …)` 起一个 headless CLI（`cronScheduler.ts:760`）；启动参数经 `buildCronCliArgs` 解析（`cronScheduler.ts:510-535`）：

- 固定 `--print --verbose --input-format stream-json --output-format stream-json`（`cronScheduler.ts:746-755`）。
- **全权限运行**：附加 `--dangerously-skip-permissions --permission-mode bypassPermissions`（`cronScheduler.ts:920-928`）——与设计文档「权限固定为所有权限，工作目录选最小范围」一致（`docs/desktop/schedule.md:29`）。
- `workdir = task.folderPath || homedir`，经 `realpathSync` 解析（`cronScheduler.ts:693-698`）；`--model` 仅在 `task.model` 指定时附加。
- **Worktree**：字段被存储，但 spawn 时**未传 `--worktree` 标志**——`folderPath` 预期已指向 worktree 内部。
- **仅手动「立即执行」** 才建 session（`options.createSession`，`cronScheduler.ts:703-717`）；自动触发跳过 session 以免侧边栏刷屏（`cronScheduler.ts:700-701`）。
- 调度循环为 60s `setInterval`（`cronScheduler.ts:568`），`start()/stop()` 绑定服务端 boot（`cronScheduler.ts:560-591`）；活动闸门是 `migrationMaintenance.isActive`（数据迁移暂停，非睡眠传感器）。

## Cross-Session Lock

`src/utils/cronTasksLock.ts` 实现跨会话**租约锁**：首个以 `O_EXCL` 原子创建成功（`'wx'`）的会话成为调度者，其余保持被动（`cronTasksLock.ts:1-9,23,64-91`）。owner 死亡经 PID 存活检测（`isProcessRunning`，`cronTasksLock.ts:149`）；陈旧锁 unlink 后重抢（`cronTasksLock.ts:159-172`）；退出时释放（`registerCleanup`，`cronTasksLock.ts:93-98,178-195`）。防止多会话同时驱动调度 / 并发触发。进程内另用 `lastFiredMinuteKey` + `runningTasks` 去重（`cronScheduler.ts:544,607-610,676-689`）。

## Auto-Expire

`recurringMaxAgeMs` 默认 `7 × 24 × 60 × 60 × 1000`（**7 天**，`cronTasks.ts:510`）；`DEFAULT_MAX_AGE_DAYS = 7`（`CronCreateTool/prompt.ts:8-9`）。`permanent:true` 任务豁免（仅 `src/assistant/install.ts` 设置，`cronTasks.ts:52-58`）。设计文档承诺「触发最后一次后删除」（`prompt.ts:119`）——删除循环现已在 **REPL 调度器 `createCronScheduler` 的 `check()`** 坐实：`isRecurringTaskAged`（`cronScheduler.ts:53-60`）判定 `recurring && !permanent && now-createdAt>=maxAgeMs`，老化任务先触发一次再走删除路径（`:302-313`），上一轮标「缺失的 REPL 调度器」已补齐。一次性任务触发后自动禁用已实装（服务端 `cronScheduler.ts:870-875`；工具集 `cronTasks.ts:341-344`）。

## End-to-end Lifecycle (Model CronCreate → Schedule → Fire)

完整闭环：模型调 `CronCreate` → REPL 调度器落到点 → 触发时把 prompt 注入命令队列，在 turns 之间执行。

**模型侧工具（4 个）**：`src/tools/ScheduleCronTool/` 暴露 `CronCreate` / `CronUpdate` / `CronDelete` / `CronList`（工具名见 `prompt.ts:64-67`）。`CronCreate` 的入参是 `z.strictObject`（`CronCreateTool.ts:27-42`）：
- `cron`：5 字段标准表达式 `M H DoM Mon DoW`（本地时区）。
- `prompt`：每次触发入队的提示。
- `recurring`：默认 `true`（每匹配一次触发，直到删除或 7 天自动过期）；`false` 为一次性（到点触发后自删）。
- `durable`：默认 `false`（仅内存，会话结束即死）；`true` 写 `.claude/scheduled_tasks.json` 跨重启。

`CronCreateTool` 关键约束：
- **上限 `MAX_JOBS = 50`**（`CronCreateTool.ts:25`）：`validateInput` 检查已存在任务数，超 50 报 `Too many scheduled jobs`（`errorCode:3`）。
- **双重 gate**（`prompt.ts:36-58`）：`isKairosCronEnabled()` = 编译期 `feature('AGENT_TRIGGERS')`（bun bundle dead-code elimination）**且** 运行时 GrowthBook `tengu_kairos_cron`（5 分钟刷新窗口）；`CronCreateTool.isEnabled()` 直接返回它。
- **kill switch 强制 session-only**：`effectiveDurable = durable && isDurableCronEnabled()`（`CronCreateTool.ts:120`）——即使模型传 `durable:true`，若 `tengu_kairos_cron_durable` 关则降级为 `false`，schema 不变故模型无感。
- **teammate 不支持 durable**：teammate 不跨会话存活，durable teammate cron 重启会孤儿，`validateInput` 直接拒绝（`errorCode:4`）。
- `call()`（`CronCreateTool.ts:117-142`）：`addCronTask(...)` 写项目级 `.claude/scheduled_tasks.json`（durable）或 session store（否则），再 `setScheduledTasksEnabled(true)` 让 `useScheduledTasks` 下一 tick 起开始 watch。

**REPL 接线层 `useScheduledTasks`**：`src/hooks/useScheduledTasks.ts` 是 React 薄层，把 `createCronScheduler` 接进 UI：
- `useEffect`（仅 `assistantMode` 为 dep）挂载一次，卸载 `stop()`；runtime gate `isKairosCronEnabled()` 在 effect 内检查（rules-of-hooks 要求无条件挂载），mid-session killswitch 由 `isKilled: () => !isKairosCronEnabled()` 每 tick 轮询（`useScheduledTasks.ts:53-126`）。
- `onFireTask`（`useScheduledTasks.ts:91-115`）是触发出口：
  - **teammate cron**（有 `agentId`）：路由到对应 teammate（`injectUserMessageToTeammate`）；若 teammate 已终态，清理孤儿 cron（`removeCronTasks`），否则 recurring 会空转直到自动过期。
  - **team-lead durable cron**（无 `agentId`）：插入「Running scheduled task」消息 + `enqueueForLead(prompt)`。
- `enqueueForLead`（`useScheduledTasks.ts:71-82`）：`enqueuePendingNotification({mode:'prompt', priority:'later', isMeta:true, workload:WORKLOAD_CRON})`——隐藏于队列预览与 transcript UI，billing 标 `cc_workload=` 低 QoS（无人实时等待）；命令队列由 `useCommandQueue` 在 turns 之间 drain，不打断当前 streaming。

**闭环路径**：模型 `CronCreate` → `addCronTask` 落盘 / 入 session store + 置 enable 标志 → `createCronScheduler` 1s tick 命中（`jitteredNextCronRunMs` 锚 `lastFiredAt ?? createdAt`）→ `onFireTask` → `enqueueForLead(prompt)` 以 `later` 优先级进命令队列 → `useCommandQueue` 在 turn 间隙派发 → 模型执行该 prompt。recurring 循环；一次性触发后自删；recurring 超 7 天（`recurringMaxAgeMs`）先触发一次再删。

## Links

- [CcHaha 主枢纽](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md)
- [Integrations](/docs/CS/AI/LLM/Agent/Product/CcHaha/Integrations.md)
- [AgentTeams](/docs/CS/AI/LLM/Agent/Product/CcHaha/AgentTeams.md)

## References

- [cc-haha GitHub](https://github.com/NanmiCoder/cc-haha)
- [schedule.md 设计文档](https://github.com/NanmiCoder/cc-haha/blob/main/docs/desktop/schedule.md)
- [cronScheduler.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/server/services/cronScheduler.ts)
- [cronTasks.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/cronTasks.ts)
- [CronCreateTool.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/ScheduleCronTool/CronCreateTool.ts)
- [prompt.ts (ScheduleCronTool)](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/ScheduleCronTool/prompt.ts)
- [useScheduledTasks.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/hooks/useScheduledTasks.ts)
- [cron.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/cron.ts)
- [CronCreateTool/prompt.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/ScheduleCronTool/prompt.ts)
- [cronTasksLock.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/cronTasksLock.ts)
- [cronService.ts（服务端 HTTP API 任务存储）](https://github.com/NanmiCoder/cc-haha/blob/main/src/server/services/cronService.ts)
- [utils/cronScheduler.ts（REPL/SDK 调度内核）](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/cronScheduler.ts)
- [cronJitterConfig.ts（GrowthBook jitter 配置）](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/cronJitterConfig.ts)
- [scheduledRunIndex.ts（bun:sqlite 派生索引）](https://github.com/NanmiCoder/cc-haha/blob/main/src/server/services/localIndex/scheduledRunIndex.ts)
