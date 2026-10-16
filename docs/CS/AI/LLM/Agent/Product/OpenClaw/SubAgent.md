## Introduction

这一页是 OpenClaw 的**子代理编排**：主 agent 怎么派生子 agent、子 run 靠什么拿到执行权、结果怎么汇回来。它是 [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md) 双层工具循环之上的**第二层循环**——子代理是「模型决定再开一个模型」，编排层的全部价值在四件事：准入、生命周期注册、结果聚合、swarm 并发。

一句话机制：**subagent 不是另起一套调度器**——「启动一个 child agent」被封装成一次 Gateway `agent` RPC，最终复用 [Storage](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Storage.md) 的 worker placement 去调度 child run，并复用其 turn claim / run authority 作为 child admission 身份。

## Subsystem Structure

`src/agents/subagents/` 是独立子系统，分五块，外加三个根级文件：

| 组成 | 职责 |
| :--- | :--- |
| `spawn/` | 派发执行器（`subagent-spawn.ts`）+ 准入 / 规划 / 请求 / 上下文 / 线程绑定 / ACP 变体 |
| `registry/` | **活跃 run 注册协调器**（`subagent-registry.ts` + run manager + lifecycle controller + sweeper + restore） |
| `swarm/` | code-mode 扇出并发调度（`swarm-scheduler.ts` / `swarm-collector.ts` / `swarm-config.ts`） |
| `announce/` | child 完成后的**向上汇报**（捕获输出、apply wait 结果、路由 announcement、cleanup） |
| `completion/` | 完成认领与投递（`subagent-completion-delivery` / `-admission` / `-result`） |
| 根级 | `spawn-pipeline.ts`（adapter 模式三阶段管线）、`spawn-plan.ts`（准入 / 线程绑定规划）、`child-admission.ts`（并发槽位预留）、`subagent-requester-owner.ts`（legacy owner 回填） |

触发入口是 [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md) tool 系统的 `sessions_spawn` / `sessions_send_child` 两个工具，经 `spawnSubagentDirect` 进入派发。

## Admission

准入在 `spawn-plan.ts` 的 `resolveSpawnAdmission` 完成，三类约束：

- **深度**：`maxSpawnDepth`（config `agents.defaults.subagents.maxSpawnDepth`），`isSubagentSpawnDepthAllowed` 校验。child 的派生元数据（depth / role `orchestrator|leaf` / controlScope `children|none`）由 `resolveSubagentCapabilities` 算出并写进 child session patch——**child 自己知道能否再派生子代理**，形成递归深度门控。
- **并发 / 扇出**：`maxChildrenPerAgent`（subagent）与 swarm 的 `maxChildrenPerGroup` / `maxTotalPerGroup`（collect 模式）。
- **目标白名单**：`allowAgents` / `requireAgentId`（`resolveSubagentTargetPolicy`），防越权派发到未声明 agent。

并发槽位用 `child-admission.ts` 的 `reserveChildAdmissionSlot` 以 **global singleton Set** 预留，close-only 语义：registry 插入成功后 `release()`，**「占用 slot」与「注册」之间没有 await 窗口**，避免重复计数。`resolveChildAdmission` 返回 `governingCap` 标识命中的上限，错误文案精确指出哪个 `cfg` 字段被突破。

## Dispatch: Reusing Worker Placement

派发的 dispatch 阶段调 `launchChildRun` → `callNativeSubagentGateway(method:"agent", …)`。这一步是整套设计的关键，分两条路径：

- **in-process 分支**（派发本身就在 Gateway 进程内，`gatewayContextResolver` 存在）：直接 `dispatchGatewayMethodInProcess("agent", …)` 转发，**连 WS 都省了**——避免「同一事件循环里自我连 socket」。
- **out-of-process 分支**：`callGatewayTool("agent", …)` 经 WS 发给 Gateway（CLI / HTTP 触发的派发走此路径）。

幂等与对账：仅 `agent` 方法带 runId 幂等键；`reconcileSubagentAgentDispatch` 在 transport 歧义失败时**只重试「显式 provisional replay」**，不会二次 launch。

**child admission 身份下传**是 [Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md) 权威链在 subagent 层的物理固化：parent 的 `workerTurnClaim` / `operationalRunInstance` / `delegatedAuthority` 经 `AgentRuntimeIdentity` 信封注入 child launch；`workerTurnExecutionIdentityCapability` 在 dispatch 前校验 child admission identity 未变，否则抛 `"worker child admission identity changed"`。即 **child run 的调度权继承自 parent 的 worker turn，而非重新认领**。

## Spawn Pipeline

`runSpawnPipeline` 把派发抽象成 adapter 三阶段：

1. `initialize()` —— 准备 child session、context engine、附件。
2. `dispatchTurn()` —— 发出 Gateway `agent` RPC；`collect=true` 时**不立即 dispatch**，返回 `childIdem` 交给 swarm scheduler 排队。
3. `register()` —— 构造 `RegisterSubagentRunInput` 后 `registerSubagentRun` **同步插入注册表**，再 `admissionReservation.release()`。

失败回滚按相位进行（`cleanupOnFailure`）：dispatch 失败回滚 context engine + 附件；**register 失败但 Gateway 已 accept** 时调 `terminateAcceptedCollectorRun` 主动终止那个「已接受但未登记」的 run——防止 Gateway 执行一个没有 owner 的孤儿 run。

## Registry

`subagent-registry.ts` 是活跃 run 的真相源：

- **内存 + 持久化双写**：`subagentRuns` Map + `persistSubagentRuns`，重启经 `subagentRestorer.restoreOnce()` 恢复——与 worker placement 的重启恢复同思路。
- **生命周期**：`subagentRunManager`（启动 / 暂停 / 终止 / steer / 替换）+ `SubagentLifecycleController` + `subagentSweeper`（扫超时 / 孤儿 run）+ maintenance。
- **公开 API**：`countActiveRunsForSession` 正是并发计数的来源；`listSwarmRunsForGroup` 服务 swarm。
- **follow-up 续跑**：`adoptPausedSubagentRunForFollowUp` 处理 `sessions_yield` 暂停后的续跑——复用暂停行的 owner 而非新建 sibling，否则会「把 requester 自己的 paused row 当成 superseded 而永久卡住」。

## Swarm

`collect=true` 时走 swarm 而非立即 dispatch：`swarm-scheduler.ts` 的 `reserveSwarmRun` / `bindSwarmRunReservation` / `activateSwarmRun` / `enqueueSwarmRun` / `releaseSwarmRun` 按 `swarmSchedulerGroupKey` + `maxConcurrent` 控并发；`swarm-collector.ts` 的 `updateSwarmCollectorCompletion` 聚合各 child 的结构化输出，`recordSwarmStructuredOutput` 落盘。swarm 调度器本身也触发 registry 初始化（`code-mode-swarm.runtime.ts` 调 `initSubagentRegistry()`）——**swarm 是 subagent 编排的直接消费方**。

## Result Aggregation

child 终态后由 `subagent-announce.ts`（completion announcement coordinator）向上汇报，四种 `completionMode`：

| 模式 | 行为 |
| :--- | :--- |
| `collector` | collect / swarm 模式，结果汇入 collector，不单独播报 |
| `thread-direct` | 绑定到 channel 线程（Discord/Slack thread、Telegram forum topic），direct delivery |
| `announce` | 经 `deliverSubagentAnnouncement` 回传给 requester（走 [Channels](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Channels.md) 的广播路径） |
| `quiet` | 静默，仅落库 |

announce 协调器捕获 child 输出（`readSubagentOutput` / `waitForSubagentRunOutcome`）、apply wait outcomes、路由 announcement 并做 cleanup 决策，同时触发 `runDescendantWake` **唤醒等待该 child 的下游 requester**——这正是 [Gateway](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Gateway.md) chat display projection 里「subagent 协调投影」的落地：requester 暂停等待 → child 完成 → 唤醒 + 注入结果 → requester 续跑。结果**自动推送回主 agent，无需轮询**。

## Gateway Mounting

registry 随 Gateway 启动完成 init + activate 两段挂载：`initSubagentRegistry()` 在启动期 plugin 加载阶段（`server-startup-plugins.ts`）调用；`activateSubagentRegistry(resolveGatewayContext)` 在 `startGatewayPostAttachRuntime` 阶段（`server-startup-post-attach.ts`）调用，与 `startChannels` / `startWorkerEnvironmentRuntime` 同批，绑定 `activeGatewayContextResolver` 供 in-process 分支复用。工具首次触发时即可登记活跃 run。

另有一个 ACP 变体：`runtime: "acp"` 的 `spawnAcpDirect` 与 subagent spawn 平级、复用同一条三阶段管线，session key 形如 `agent:<agentId>:acp:<uuid>`，详见 [Integrations](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Integrations.md)。

## Links

- [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md)
- [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md) / [Gateway](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Gateway.md)
- [Storage](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Storage.md) / [Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md)
- [Channels](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Channels.md) / [Integrations](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Integrations.md)
- [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md)
