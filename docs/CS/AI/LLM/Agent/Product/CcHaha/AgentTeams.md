## Introduction

cc-haha 在多 Agent 协作上做了**两层东西**，常被营销打包成「Agent Teams + Dynamic Workflow」，但二者机制不同、需分开记录（Claude Code 的 agent teams 以 mailbox 架构在终端呈现，见 [ClaudeCode/Subagents](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Subagents.md)）。底层 subagent 机制（独立上下文、定义方式、agent 间消息信任边界）与 Claude Code 同源，本页讲 cc-haha 在 GUI / 引擎上叠加的协作层。

> [!NOTE]
> 此前本页曾把「Dynamic Workflow」标为营销夸大——**已据引擎源码纠正**：桌面 Agent Teams UI 确实是引擎快照的纯派生渲染，但引擎侧 `WorkflowTool` 是真实的「模型写并运行编排脚本」机制。两层入口不同，勿混为一谈。

### 两层机制

1. **Agent Teams（桌面可视化器）**：把引擎既有 agent-teams 的**快照**渲染成 GUI workbench（成员 / 任务 / 通信 feed / 依赖泳道画布 + 回放）。桌面层无写回引擎的编排逻辑。
2. **Dynamic Workflow（引擎真功能）**：`WorkflowTool` 让模型**现场编写编排脚本并在 Node `vm` 沙箱里运行**，脚本调用 `agent()/parallel()/pipeline()/phase()` 派生 subagent。这是真实的动态编排能力，非营销空话。

## Agent Teams UI Is a Live Visualizer of the Engine Snapshot

引擎推送 `snapshots` 流，**快照流是唯一真相源**（注释原文 "snapshot stream is the only source of truth"，`AgentTeamsWorkbench.tsx:115-120`），React 侧 `useTeamStore(s => s.workbenchesBySession[sessionId])` 直接消费。桌面层没有任何写回引擎的编排逻辑。组件带 `experimental` 徽标（`AgentTeamsWorkbench.tsx:341`）。

GUI 渲染细节（均为快照上的派生计算 / 纯排版）：

- **成员（members）**：`TeamMember` 含模型 / 工具 / system prompt，由可视化 SubAgent 管理器配置；`getMemberAvatarKey` 按 role 正则匹配职业头像（`agentTeamsModel.ts:103`）。
- **任务（tasks）**：`TeamWorkbenchTask`，含 `blockedBy` 依赖。
- **依赖泳道画布**：`layoutWorkbenchTasks`（`agentTeamsModel.ts:420`）用 `taskDepths`（按 `task.blockedBy` 求最长依赖路径得到 `depth`）把任务分入纵向 lane，`AgentTeamsCanvas.tsx:345` 生成依赖 DAG 边 `dependencyPath`。
- **通信 feed**：`classifyMessage` 分 `assignment` / `peer` / `report` / `system`（`AgentTeamsCommunicationFeed.tsx:60`），画布用 `flightRoutes` 画三类「航班」动画线（`AgentTeamsCanvas.tsx:442`）。
- **回放时间轴**：`replayFrameDelay` / `seekTimeline`（`agentTeamsModel.ts:62,292`）支持 live 跟随与回放。

## Dynamic Workflow Is a Real Engine Feature

营销所说的「Dynamic Workflow」不是空话——引擎侧 `WorkflowTool`（`src/tools/WorkflowTool/WorkflowTool.ts`）+ `src/utils/workflows/*` 实现了一套**模型创作的 VM 编排引擎**：

- **模型写脚本**：`WorkflowTool` 的 `script` 参数要求以 `export const meta = { name, description, phases }`（纯字面量）开头，正文用 `agent()/parallel()/pipeline()/phase()`（`WorkflowTool.ts:29-31`）。权限提示原文即「Claude wants to run a **dynamic workflow**, which can spawn many subagents」（`WorkflowTool.ts:172`）。
- **VM 沙箱执行**：脚本经 `compileWorkflowScript` 编译为 Node `vm.Script`，再由 `runInContext(sandbox.context, {timeout})` 在隔离上下文运行（`runtime.ts:105`；`compile.ts:56-67`）。为保证 resume 确定性，`Date` / `Math.random` 被显式禁用（`compile.ts:23-45`），动态 `import()` 也被拒绝（`compile.ts:63-65`）。
- **派生 subagent**：`harness.ts` 的 `agent(prompt, opts)` 真正 spawn 一个 subagent（可 `isolation:'worktree'`），受 `WORKFLOW_MAX_AGENTS` 硬上限约束（`harness.ts:101,167,190`）；`parallel()/pipeline()/phase()` 提供并发 / 流水线 / 分阶段原语。
- **可恢复**：`resumeFromRunId` 让已完成且 `(prompt, opts)` 未变的 `agent()` 直接命中缓存、只重跑改动或新增的调用（`WorkflowTool.ts:57-64`）。恢复协议细节见下。

### Resume 缓存协议与确定性 VM（引擎内部）

`WorkflowTool` 的恢复不是「保存整个 VM 状态」，而是 **journal + 链式缓存键 + 一次性短路** 的确定性重放——这要求 VM 内不能出现真实时间或随机性，否则重放会跑偏。

- **Journal（执行日志）**：`WorkflowJournal` 是 append-only JSONL，每个 subagent 在 spawn 前写 `started` 行、返回后写 `result` 行（`journal.ts:14-16,57-67`）。`journal.load()` 读回时遇截断/损坏的尾部行直接跳过（最坏只多跑一个 agent，`journal.ts:69-108`）；写入经 promise 链串行化，运行结束前必须 `flush()` 落盘（`runtime.ts:130, journal.ts:53-55`）。
- **链式缓存键**：`workflowCacheKey = previousKey|prompt|opts`，即「上一条的 key + 本次 prompt + opts」——**调用顺序本身参与缓存身份**，故循环里两个相同的 `agent('review')` 不会共用缓存，中途插入一个调用也会使后续全部失效（`journal.ts:123-129`）。
- **一次性短路（replay 只重放剩余）**：`harness.agent()` 命中 `journalSnapshot.results` 就直接返回 `cached.result` 并标记 `cached:true`（`harness.ts:231-259`）；**首个未命中立即置 `cacheExhausted=true`，此后所有 agent 一律实跑**（`harness.ts:260-263`），因首个 miss 之后的顺序/结果已不可信。
- **确定性 VM 沙箱**：每次运行重建 `vm.createContext(Object.create(null), { codeGeneration: { strings:false, wasm:false } })`（`runtime.ts:177-179`）。`compile.ts` 的 `installDeterminismGuards` 把无参 `new Date()` / `Date.now` / `Math.random` 全部改为抛错，动态 `import()` 也被 `vm.Script` 的 `importModuleDynamically` 钩子拒绝（`compile.ts:23-46,56-67`）。**主机对象绝不暴露给脚本**：`agent/parallel/pipeline/log/phase/workflow/budget/console/setTimeout/args` 全经 VM 内箭头重包一层闭包，避免脚本借 `fn.constructor` 摸到 `Function` 逃出 VM；`budget/console/timers` 也在 VM 内重建（`runtime.ts:198-206,277-351`）。resume 时脚本重解析 + 重编译（`runtime.ts:382-395`），同一脚本文本 + 同一缓存结果 + 无真实时间/随机 = 重放一致。
- **嵌套工作流严格一层**：`workflow()` 全局调 `runNestedWorkflow`，否则抛 "not available"；子工作流复用同一 `runId` / 同一 `journal` / 同一并发计数 / 同一 token budget，但**子工作流的 `workflow()` 被置 `undefined`**，再嵌套一层即抛错（`runNestedWorkflow.ts:54-68,66-67`）。
- **ultracode 模式**：并非第六档 effort，而是 **`xhigh` effort + 常驻 workflow-orchestration 标志**（`ultracode.ts:1-16`），仅当 `areWorkflowsEnabled()` 且模型支持 xhigh 时启用；自动模式的单次 consent（`autoModeConsent.ts`）抑制每次启动弹窗。

#### 硬上限常量（已核实）

引擎对脚本与派生 subagent 设了明确护栏（`src/utils/workflows/constants.ts`，此前标「待核实」现已据源码填实）：

| 常量 | 值 | 含义 |
| :-- | :-- | :-- |
| `WORKFLOW_MAX_AGENTS` | **1000** | 单次 run 内 `agent()` 调用硬上限，防失控循环 |
| `WORKFLOW_MAX_FANOUT` | **4096** | 单次 `parallel()/pipeline()` 扇出上限 |
| `WORKFLOW_SCRIPT_MAX_BYTES` | **524288**（512 KiB） | 脚本超过此值解析前即拒绝 |
| `WORKFLOW_SYNC_TIMEOUT_MS` | 30000 | 脚本同步段的墙钟预算（`await` agent 不消耗） |
| `WORKFLOW_AGENT_STALL_MS` | 180000 | subagent 无进展判定 stalled 的阈值 |
| `getWorkflowConcurrency()` | `min(16, max(2, cpu-2))` | 在途 agent 并发上限，按 CPU 数避免笔记本上 500 条 model stream |

> 一个真实坑：`WORKFLOW_AGENT_CAP_MESSAGE` 揭示——若 `budget.total` 为 `null`，`budget.remaining()` 返回 **Infinity**，带 `remaining()` 的循环永不终止，最终撞上 `WORKFLOW_MAX_AGENTS=1000` 上限。写循环应设硬迭代上限或传入 token budget（`constants.ts:66-69`）。

> 注意：Desktop 的 Agent Teams 画布可视化的是引擎 agent-teams 快照，而 WorkflowTool 的 `agent()` 调用也会产生 `workflow_agent` 事件（`harness.ts:241,267`），很可能在同一个画布上呈现。但二者入口不同——前者是 composer 的「Agent Team 开关」（本质只是给消息前缀注入一段指令块 `<agent-team-request>...`，`agentTeamRequest.ts:13-21`），后者是模型主动调用 `Workflow` 工具。

## WorkflowTool: 模型侧入口

引擎段已覆盖 VM / 缓存协议 / 硬上限；本节点明**模型调用 `Workflow` 工具这一层**的契约与边界（`src/tools/WorkflowTool/WorkflowTool.ts`、`launchWorkflow.ts`、`prompt.ts`）。

### 输入 schema 与解析优先级
- `z.strictObject` 五字段：`script`（≤512 KiB，可选）、`scriptPath`（磁盘脚本路径）、`name`（预定义工作流，内置或 `.claude/workflows/`）、`args`（暴露为全局 `args`，verbatim，传 JSON 值而非字符串）、`resumeFromRunId`（`^wf_[a-z0-9-]{6,}$`）。
- 解析优先级 `scriptPath > name > script`（`WorkflowTool.ts:259-299`）：`scriptPath` 胜出以便字节级重放编辑过的脚本；`name` 解析后**不给 scriptPath**（避免运行写回用户文件、且 resume 应从实际运行内容而非文件）；三者皆无则报错。
- `title` / `description` 被显式忽略——元数据写在脚本头部的 `meta`。

### 权限模型（checkPermissions）
- 自动 allow 三情形：权限模式 `bypassPermissions`、非交互会话（`isNonInteractiveSession`）、`ultracode === true`（常驻编排指令，每轮弹窗等价于每轮弹）。
- `auto` 模式：若 `hasAcceptedWorkflowsInAutoMode()` 则一次性 consent 后 allow。
- 否则按 `name` 查 allow/deny 规则（`getRuleByContentsForTool`）；都不命中则 `ask`，并附 `addRules` 建议把该 workflow name 写入 localSettings 设为 allow（`WorkflowTool.ts:122-186`）。
- 弹窗文案明确「spawn many subagents and use a large number of tokens」（`WorkflowTool.ts:172`）。

### call 流程（异步，不 spawn 子进程）
1. `getWorkflowsDisabledReason()` 非 null 直接 throw（见启用 gate）。
2. `resolveScript(input)` 按上述优先级解析。
3. `prepareWorkflowScript(script)` → `{ ok, meta, vmScript }`，`meta` 为脚本头部纯字面量，`vmScript` 为编译后的 VM 脚本（衔接确定性 VM，`runtime.ts`）。
4. `launchWorkflow({...})`：写 `transcriptDir` / `scriptPath`、生成 `wf_` runId（`input.resumeFromRunId ?? createWorkflowRunId()`），通过 **task 系统**（`createTask` / `enqueueWorkflowNotification`）异步调度引擎——**不是直接 `child_process.spawn`**，引擎在独立任务上下文运行，主线程立即返回（`launchWorkflow.ts:67,200-265`）。
5. 返回 `async_launched` + `taskId` + `runId` + `transcriptDir` + `scriptPath`（`maxResultSizeChars = 100_000`）。

### 启用 gate 与规模建议（enabled.ts）
- **无 feature flag**：启用完全由 settings 驱动。`getWorkflowsDisabledReason()` 三来源：`CLAUDE_CODE_DISABLE_WORKFLOWS`（env）、`policySettings.disableWorkflows`（managed）、`disableWorkflows === true` 或 `enableWorkflows === false`（settings）；`areWorkflowsEnabled()` 即该 reason 为 null。
- `ultracode` 关键词触发：仅交互式会话（非 `-p` / SDK / 计划任务 / PR 评论），默认开、`/config` 可关；特性本身禁用时关键词无意义（`enabled.ts:isWorkflowKeywordTriggerEnabled`）。
- **规模建议（guideline，非硬限）**：`unrestricted / small / medium / large` → agent 目标 `null / 5 / 15 / 50`；在 prompt 注入让模型按口味定规模，settings 文件优先于 `/config` 选择。
- **大 workflow 预警（advisory，不阻塞）**：`scheduledAgents > 25` 或 token `> 1.5M`（每 agent 假设 70k）时弹「Large workflow」提示，供用户在 `/workflows` 中止；ultracode 下抑制（已 opt-in 大规模）。

### resume 协议（模型侧视角）
- 输出含 `runId`；中断 / 被杀 / 改脚本后用 `Workflow({ scriptPath, resumeFromRunId })` 重放：最长未变前缀的 `agent()` 瞬时命中缓存，首个改动 / 新增调用及其之后实跑（`prompt.ts:156`）。
- 同一脚本 + 同一 `args` → 100% 缓存命中。
- 诊断空 / 异常结果：读 `<transcriptDir>/journal.jsonl`（记录每个 agent 实际返回值）。

## Teammate Tools: Team Lifecycle

区别于 [Dynamic Workflow](#dynamic-workflow-is-a-real-engine-feature) 引擎，以下是模型可**直接调用**的团队管理工具（`isAgentSwarmsEnabled()` 总开关，`TeamCreateTool.ts:82`）：

| 工具 | 文件 | 关键语义 |
|---|---|---|
| `TeamCreate` | `TeamCreateTool.ts` | 1 leader 只能管 1 team；写 teamFile 到磁盘；可选 `plan` 草稿评审 |
| `TeamPlan` | `TeamPlanTool.ts` | `get`/`replace`/`submit` + `expected_revision` 乐观锁；`submit` 后暂停等人类审批 |
| `TeamDelete` | `TeamDeleteTool.ts` | 有 active teammate 时拒绝，要求先 `requestShutdown` |
| `SendMessage` | `SendMessageTool.ts` | teammate 间通信（见下节） |
| `ListPeers` | `ListPeersTool.ts` | **`@generated stub`** — ant-internal feature-gated 占位，公开 build DCE 后不执行 |

要点：

- **1 leader 1 team**：`TeamCreate` 检查 `appState.teamContext?.teamName`，已存在则抛错要求先 `TeamDelete`（`TeamCreateTool.ts:127-134`）。
- **Team = Project = TaskList 同构**：`teamName` → `sanitizeName` → `taskListId`；`resetTaskList` 让任务编号从 1 开始；`setLeaderTeamName` 让 leader 的 `getTaskListId()` 返回 teamName（否则 tmux/iTerm2 teammate 写到不同目录，`TeamCreateTool.ts:163,210-230`）。
- **持久化与清理**：teamFile 写磁盘 `writeTeamFileAsync`；`registerTeamForSessionCleanup` 修复了 gh-32730（team 不再永远留磁盘，session 结束清理）。
- **TeamDelete 安全闸门**：若仍有 `nonLeadMembers`（含未 terminated 的 process 成员），直接拒绝并提示先 `requestShutdown`——防止旧 actor 在同名 team 重生、mutate 新 generation 的 task list（`TeamDeleteTool.ts:87-105`）。
- **TeamPlan 草稿评审**（仅桌面 session `isTeamReviewRequired()`）：`submit` 后 `requestTeamPlanTurnPause` 等待人类在 team panel 审批，**不启动成员、不审批即不执行**；teammate 不可 submit（`TeamPlanTool.ts:28,39,52-54`）。

> 关键澄清：`ListPeersTool.ts` 是自动生成的 stub（开头 `@generated stub from scan-missing-imports`，对应 ant-internal 的 `feature()` gated 模块，注释明言「DCE 后都不会真的执行」）。但 `SendMessage` 的接收者语法里 `bridge:<session-id>`（Remote Control peer）与 `uds:<socket-path>`（本地 peer）依赖 `ListPeers` 发现——**公开 build 里 peer 发现能力受限于该 stub**，需留意文档与公开版行为差异。

## SendMessage: Teammate Communication Model

`SendMessage` 的接收者语法（`SendMessageTool.ts:81`）：

- `*` — 广播给所有 teammate（`handleBroadcast`）
- 具名 teammate — 单发
- `uds:<socket-path>` — 本地 peer（UDS）
- `bridge:<session-id>` — Remote Control peer

**投递模型 = 持久化 inbox + 按需 resume，不是常驻进程 IPC**（基于 `teammateMailbox.js`）：

- lead 与 in-process teammate 直接写 teammate 的 inbox（`handleMessage`）。
- **in-process teammate 的 runner 挂了**（failed / finished / stopped / evicted）→ inbox 无人读 → 从 transcript **resume** 该 teammate，把消息作为 next prompt（`resumeTeammateWithMessage`，`SendMessageTool.ts:210-358`）。
- 状态分支：running teammate → 排队下个 turn；未 running → resume 为 in-process teammate + 消息作 next prompt；pending plan member（plan 未审批）→ 排队，审批后读取；desktop process member → 只写 inbox，server restart 重投。

> 这解释了 teammate 为何无需常驻进程也能异步通信：**崩溃 / 停止的 teammate 通过 resume-from-transcript 重新读取 inbox**，消息不丢。

## Swarm Lifecycle: Runtime Semantics

- **初始化与恢复**：`useSwarmInitialization` 区分 fresh spawn（从 env 读 teamName/agentId/agentName）与 resumed teammate session（从 transcript messages 的 teamName/agentName 恢复），两者都调 `initializeTeammateHooks`（`useSwarmInitialization.ts:38-78`）。
- **权限集中裁决**：swarm worker（teammate）调用危险工具时，`useCanUseTool` 创建 pending permission request 并写入磁盘 / inbox（mailbox IPC）；leader 批准后写回 response；`useSwarmPermissionPoller` 每 **500ms** 轮询 `pollForResponse` 并触发回调（`useSwarmPermissionPoller.ts:28,268-322`）。另有 **sandbox permission** 回调（worker 向 leader 请求 sandbox 权限）。模块级 `pendingCallbacks` registry，`/clear` 时 `clearSessionCaches()` 清理。→ **teammate 的危险操作由 leader 集中审批，worker 不能自决**。
- **视图自动退出**：teammate 进入 `killed` / `failed` / `error` / 非 running 状态时，`useTeammateViewAutoExit` 自动退出查看模式（保留 `completed` 供 review，`useTeammateViewAutoExit.ts:44-54`）。

## Summary

- **Agent Teams（UI）** = 引擎既有 agent-teams 的实时可视化器：成员 / 任务 / 通信 feed / 依赖泳道画布 / 回放游标均为 GUI-only。
- **Dynamic Workflow（引擎）** = 真实的模型创作 + VM 执行编排系统，派生受上限约束的 subagent 并支持缓存恢复。
- **Teammate Tools（工具层）** = 模型可直调的团队生命周期工具：`TeamCreate`（1 leader 1 team、Team=Project=TaskList 同构）/ `TeamPlan`（草稿评审、`submit` 暂停等人类）/ `TeamDelete`（active teammate 闸门）/ `SendMessage`（inbox + resume 通信）/ `ListPeers`（公开版为 stub）。
- **Swarm Lifecycle（运行语义）** = 初始化与 resume、权限由 leader 集中裁决（500ms 轮询）、视图自动退出。

## Links

- [CcHaha 主枢纽](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md)
- [Permission](/docs/CS/AI/LLM/Agent/Product/CcHaha/Permission.md)
- [三向对照：Claude Code / OpenCode / cc-haha](/docs/CS/AI/LLM/Agent/Product/CcHaha/Comparison.md)

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
