## Introduction

这一页是 OpenClaw 的**后台工作三层底座**：子进程怎么管、任务怎么记账、以及 OpenClaw 自己的管家 agent 长什么样。它与 [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md) 的分工是——那页的 agent loop 跑在前台请求上，这一页跑的是**没有用户在场**的工作；与 [SubAgent](/docs/CS/AI/LLM/Agent/Product/OpenClaw/SubAgent.md) 的分工是——子代理是「模型派模型」，这一页是「系统派进程」。

先纠正一个高频误解：**任务 owner 不止 cron**。`TASK_RUNTIMES = ["subagent", "acp", "cron", "cli"]` 四类 runtime 家族各是一名 owner，`task_runs` / `task_delivery_state` / `flow_runs` 三表是它们的共同账本，cron 只是其中一支。

## Task Ledger

`src/tasks/` 是持久任务账本，核心字段（`TaskRecord`）：`runtime` + `taskKind` 标识别名、`ownerKey`（授权键）、`scopeKind: "session"|"system"`、以及 `executionOwner {host, pid, startIdentity}`——**进程级执行归属三元组**。

「这个任务还活着吗」不靠心跳猜，靠三元组判活：Gateway 重启后由 maintenance 把对不上的任务判 `lost` 而非重放执行。状态机七值：`queued / running / succeeded / failed / timed_out / cancelled / lost`；delivery 另有 7 个子状态；notify 策略三档 `done_only / state_changes / silent`。

存储落**共享 state DB**：`task_runs`（STRICT，含 owner_key / scope_kind / execution_owner_* / cleanup_after 列与 8 个索引）+ 附属 `task_delivery_state`（FK → task_runs）；多跳编排另有 `flow_runs`。写路径走专用 worker（`task-registry.worker.ts`），与 [Storage](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Storage.md) 的「写事务同步」同源。

几条把账本缝进主线的机制：

- **`agent-harness-task-runtime-scope.ts`**：给 agent harness run 颁发**宿主签发**的 task runtime scope，用 **WeakSet 注册表防插件伪造 requester 所有权**——scope 只能由宿主签发，与 [Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md) 的「companion identity 表永不授予权限」同族。
- **`background-exec-task-contract.ts`**（7 行）：身份契约——后台 exec 进程在账本里是 `runtime:"cli", taskKind:"exec"`，`runId = exec:<processSessionId>`；exit code / timeOut / manual-cancel 映射到终态。**这是 exec 工具 → 任务账本的桥**。
- **`agent-harness-completion-recovery.ts`**：恢复「宿主会话重启时欠着一条 subagent 完成播报」的场景。识别 owed 靠 `runtime:"subagent"` + `deliveryStatus:"pending"` + `sourceId===runId`；`captureHarnessCompletionRecovery` 由 admitted host run 调用（**非启动扫描**），跨 store 两阶段提交：先校验 claim 未被 reset / 换主失效，再在 mutation 事务内重读 session 后置 delivered。
- **`context-engine-maintenance-task-owner.ts`**：[Memory](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Memory.md) 的 context engine 每轮维护任务身份是 `runtime:"acp", taskKind:"context_engine_turn_maintenance"`，进程内 active-owner 集合用 `Symbol.for` 全局单例。
- **保留窗**：terminal 7d、lost 24h（`task-retention.ts`）；cron 历史每 job 上限 `CRON_HISTORY_KEEP_PER_JOB = 2000` 行——**取代旧 `cron.runLog.keepLines` 配置**，按 storeKey + sourceId 分区、history 行与 "quiet tick" 行分开排序截断。

激活点在 Gateway 启动早期（懒加载 `task-registry.maintenance.js` + `configureTaskRegistryMaintenance({runtimeAuthoritative:true})`），**update canary 进程跳过**（注释："canary 行属源 Gateway，绝不 reconcile"）。`task-registry.maintenance.ts` 是所有 owner 的汇聚点：同时感知 ACP active turn、background exec session、subagent registry、cron `isCronJobActive`，**在权威信号都不存在时判 lost**。

## Process Foundation

`src/process/` 是进程底座，**无任何任务语义**。两条 spawn 路径：

- **长跑 / PTY 走全局 supervisor 单例**：`spawn(input): Promise<ManagedRun>`，exec 类工具经 `getProcessSupervisor()` 进来，取消走 `supervisor.cancel(sessionId, "manual-cancel")`。
- **同步短命令走 execa 封装**：`runExec` → `spawnCommand`；`withCommandProcessScope` 用 **AsyncLocalStorage 把 AbortSignal 与子进程集合绑成可级联停止的 scope**。

进程树终止是 POSIX 惯例的完整版：spawn 即 detached，存活探测 `kill(-pid, 0)` 打整个进程组，`signalChildProcessTree` 按组 SIGTERM/SIGKILL，并显式调度「过继僵尸回收」——**防树杀后的后代变成未跟踪僵尸**（注释挂 issue #97616）。平台遍历的真身在 `packages/agent-core` 的 kill-tree。

几个有意思的边界件：

- **`spawn-broker` 让子进程在 Gateway 重启时「过户」而非被杀**——跨进程 spawn 代理经 IPC handoff 交出句柄与管道（host 侧有退避重启与 MAX_REQUESTS 256 上限）。
- `child-process-bridge` **不是 Gateway 桥**，是父→子的信号转发桥（SIGTERM/SIGINT/SIGHUP/SIGQUIT，exit 时自动 detach）。
- `releaseChildProcessOutputAfterExit` 只做输出管道清理：detached 后代继承管道时，限制 execa 等待 stdout/stderr 的时间（100ms idle 宽限 / 1s 硬上限）。
- `gateway-work-admission.ts` 是进程级 root work 准入：draining 时抛 `GatewayDrainingError` 拒收新任务——Gateway 优雅停机与 cron 准入的共同底座。
- `background-work.ts` 在 command-queue 之上做 **lane 容量注册**：按稳定 owner key 注册 `background:<owner>` lane，组预算**全局封顶 3** 且注释明确「只有 leaf work 能进来」——防嵌套等待死锁。
- `bounded-line-framer.ts`：按 LF 切帧、不 decode 不完整尾行、超字节预算抛错，服务 stdio / NDJSON 协议行（[Integrations](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Integrations.md) 的 ACP ndjson 就在用）。
- `CommandLane` 枚举（Main / SystemAgent / Cron / Subagent / Background / HookDispatch）是全库共用的调度隔离词汇。
- `linux-oom-score` 调子进程 OOM 优先级——**防网关自己被 OOM killer 选中**。

## Cron and Scheduled Services

`CronService` 是有状态 facade（可变调度状态锁在 state 对象里，委托给 lifecycle / mutations / read / run 四组 ops，`start()` 带 `lifecycleGeneration` 防并发重入），经 `activateScheduledServicesWhenReady` 随 Gateway 激活，`heartbeat-monitor` 提供活体探活。两类 payload：

- **command**（`runCronCommandJob`）：纯 `exec`，**不启动 agent / model run**，默认超时 10 分钟，产出 exec 源诊断。
- **agent**（`isolated-agent.ts`）：真正触发一次 agent run，复用 [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md) 的 provider 调用 + 双层 tool-call 循环。

权限控制直接复用主线的权威机制，不另起一套：`bindCronJobAdmittedRun` 把 cron job 绑定到 `AdmittedRunContext`，`captureCronJobMessageActionAuthority` 签发**一次性**消息动作权——host-owned，复制 token 或同 id 重跑都无法兑现。执行结果经 `delivery.ts` 投递 / 通知，走 [Channels](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Channels.md) 的出站路径。历史裁剪在任务账本侧（每 job 2000 行），cron 侧读回 `listTaskRegistryRecordsByRuntimeSourceIdFromSqlite`。

## System Agent

`src/system-agent/` 是 OpenClaw 自己的管家 agent，`SYSTEM_AGENT_ID = "openclaw"`（保留名）。它是**真实 agent**：与用户 agent 共用同一条 embedded loop、session transcript、tool pipeline，持久单会话即真多轮记忆；但有三处收窄：

- **工具面收窄到单一 ring-zero `openclaw` 工具**（CLI harness 则经专用 stdio MCP server 注入）；
- **指令是闭集 command vocabulary**——「解析刻意收窄，使自由文本永不直接执行」；
- **超时按路由分档**：本地路由 120s / 外部路由 30s（从 manifest 的 `modelPricing.providers[].external === false` 判定）。

它的审批是**独立的一套**，不与 [Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md) 的通用 approval store 混。三条安全线：**host 而非会话模型决定 armed**、**agent loop 永不自我批准**、模糊输入交给独立的 single-shot classifier 且要求 provider / model / authFingerprint **全等**否则回退 "other"（闭集 yes/no 短路，正则 `approve` 起）。待批准操作以 `sha256(stableStringify(operation))` 指纹绑定 session 的 `proposalRef.current`——**批准只对该精确变更有效**。CLI harness 路由不起第二 harness，模糊即保持 pending。

`planSystemAgentCommand` 是单命令规划器：把模糊输入转成一条安全命令；外围的 setup-inference 操作族负责执行解析出的操作与推理配置向导。

## Links

- [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md)
- [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md) / [SubAgent](/docs/CS/AI/LLM/Agent/Product/OpenClaw/SubAgent.md)
- [Storage](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Storage.md) / [Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md)
- [Memory](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Memory.md) / [Gateway](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Gateway.md)
- [Nodejs](/docs/CS/front-end/Nodejs.md)
