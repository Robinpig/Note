## Introduction

这一页是 OpenClaw 的**执行内核**：一次 agent run 怎么跑起来、模型怎么调、上下文怎么压缩、记忆与子代理如何长在上面，以及后台任务与进程底座如何支撑它们。它是 [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw.md) 枢纽那条「入站 → agent runtime → provider → 工具 → 回写」链路的中段；工具来源与插件契约在 [Plugins](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Plugins.md)，会话落盘在 [Storage](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Storage.md)。

## Agent Runtime and Tool Loop

所谓「具体 provider 的 tool-call 循环」其实不在 provider 代码里——provider 差异在 transport 层已被吸收成统一事件流，**真正的循环是 provider 无关的**，位于 `packages/agent-core`。它是双层循环：

- **外层 run 级 attempt 重试**：每次 attempt = 准备 + 派发 + 归一化，模型失败 / 权限恢复 / 模型切换时重试。这是「调用失败重试」，不是 tool-call 循环本身。
- **内层 turn 内 tool-call 循环**：流式响应 → 识别 `tool_use` → 执行 → 结果回灌 → 再次请求，直到 `stopReason` 表示收尾；用户在等待期间输入的 steering / follow-up 消息由外层处理。

回灌闭环是关键：工具结果作为 `toolResult` 消息 push 进 `context.messages`，下一轮经 `convertToLlm` 适配成该 provider 的格式（anthropic `tool_result` block / openai `tool` 角色 / gemini `functionResponse`），形成「模型 → tool_use → 执行 → 结果 → 模型」的回路。

循环防护是一套独立机制：多检测器（重复调用 / 参数 churn / 未知工具重复 / 无进度轮询 / 全局熔断 / ping-pong）配分级阈值（如未知工具重复 10 次、critical 20、全局熔断 30），临界级 veto 直接中断；工具执行前还有循环准入（`admitToolCallBatch`）与 compaction 后的 outcome 观察。

## Tools and MCP

循环体里「tool 从哪来、怎么执行、MCP 如何封装」是闭环的最后一环。四类来源先汇聚成 attempt-local catalog，再经 surface 裁剪 → schema 投影与隔离（不兼容 schema 进 quarantine）→ policy gating → tool-search，最终成为 agent loop 的 `context.tools`：

| # | 来源 | 说明 |
| :--- | :--- | :--- |
| 1 | 内置 tools | `src/agents/tools/`（cron、system-agent、code-mode 等），按 agent / profile 选择 |
| 2 | Plugin tools | 插件 manifest 声明 `capabilities:["tools"]`，经 `register(api)` 贡献 |
| 3 | Channel tools | 面向 channel 的 10 个操作（读会话 / 读消息 / 取附件 / 轮询事件 / 发消息 / 响应审批等），handler 很薄，路由与审批的权威仍在 Gateway |
| 4 | 外部 MCP server tools | session-scoped，`resolveDeferredTool` 懒解析汇入，声明来自 manifest `mcpServers` 或 `.mcp.json`，经 client grant admission 授予 |

执行路径是「准入 → 分批 → 回灌」：`executeToolCalls` 先做 `beforeToolBatch` 准入（校验 + intervention 短路），再按 `toolExecution` 或单 tool 的 `executionMode` 决定整批串行还是并行——并行的 prepare 一起做，但 **commit 保持源序**；每批 `prepareToolCallEntry`（发 `tool_execution_start` → `beforeToolCall` 拦截 → abort 早退 → 实际执行）→ 源序 finalize → `tool_result` 回灌 provider 进入下一轮。

一处身份对齐的硬校验值得单独记：`resolveToolCallTool` 对 `context.tools` 未命中的名字会走 deferred 懒解析，但**返回的名字必须与请求完全一致**——保持 execution 与 audit 身份对齐。Policy 也不是单层：`tool-policy-pipeline` 是 profile / global / agent / sender / subagent 的多级流水线，与 [Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md) 的 approval store 和最小权限联动。

OpenClaw 同时扮演 **MCP server** 与 **MCP client** 两个角色：

- **Server 侧**（把自身 tool 暴露给外部 LLM）：stdio 为主，两种 serve 入口——`openclaw-tools-serve` 暴露内置 `openclaw` / `cron` tool 给 ACP / Claude Code，`plugin-tools-serve` 暴露插件 tool 给 ACP 会话；channel 侧经 `registerChannelMcpTools` 把渠道操作注册成 MCP tools 并广告 `claude/channel` capability；远端 worker 场景另有 node-host 用 Streamable HTTP 暴露 skill session 工具。
- **Client 侧**（连外部 MCP server）：stdio / SSE / Streamable HTTP **三种 transport 全封装**，外部 server 生命周期**跟随 session**，run 结束即 retire 回收。

与 ACP 那边的分工见 [Integrations](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Integrations.md)：MCP 是 tool 级，ACP 是 session / turn 级。

## Provider Abstraction

「调哪个模型、怎么调」分三层：**core model/stream 抽象 → provider 运行时路由 → provider 插件**，provider 不必自建 HTTP 流。

一个反直觉事实：**anthropic 插件没有 `createStreamFn`，只提供 `wrapStreamFn` 装饰器**——底层 HTTP 由 core transport 完成（SSE 归约成统一的 `AssistantMessageEvent` 异步可迭代流）。只有自定义协议的插件才自建流函数。插件经 `definePluginEntry` 注册，以 `provider` + `hookAliases` 查找。

工具 schema 也有一层适配：`normalizeToolSchemas` 把 tool 定义适配到各 provider 的 JSON Schema 子集（Gemini / llama.cpp GBNF / OpenAI strict），流中 `tool_use` 触发 agent 工具执行循环。

有效模型清单（`src/model-catalog/`）= 插件 manifest 声明 + 可选 remote overlay（存储 bundle 新于打包戳才激活，SSRF-guarded refresh TTL 6h），manifest 行与 overlay 行合并，**两插件 merge-key 冲突整条丢弃**；`model-picker` 是会话侧应用用户选定的模型，与清单装配分离。

## Context and Compaction

每轮 tool-call 前，`prepareEmbeddedAttemptPromptContext` 要把 transcript 投影 + system prompt + runtime context + 工具结果拼成提交给 provider 的 prompt。**顺序即处理管线**：心跳产物过滤 → replay 归一 → 工具结果投影状态协调（非 raw run）→ **超长工具结果截断**（按 `contextTokenBudget`）→ 组装 runtime context fragments → 拆成 session / runtime-only / model 三部分 → 运行时事实（能力工具名等）→ LLM boundary 归一 → 提交前 precheck（与 admission 同源校验）。

预算不是拍脑袋：`contextTokenBudget = attempt.contextTokenBudget ?? DEFAULT_CONTEXT_TOKENS`，硬上限由 `resolveEmbeddedSessionContextLimits` 约束成 `maxBytes = min(64MB, max(1024, tokenBudget * 8))`、`maxEvents = 10000`。注意这里的「截断」与下面的「压缩」是两条不同路径——截断只动工具结果，压缩会翻代际。

预算超限时的压缩决策在模型调用前评估，四个路由：

| 路由 | 条件 |
| :--- | :--- |
| `fits` | 放得下 |
| `truncate_tool_results_only` | 可减少的工具结果量远超溢出 |
| `compact_only` | 溢出但无可减工具结果 |
| `compact_then_truncate` | 两者都要 |

压力测量优先用 provider 真实的 `usage.contextUsage`（**避免低估活跃 transcript**），取不到才估算，并叠加 tool schema 的 token 压力（估完还要乘一个 `SAFETY_MARGIN`）。预算侧有专门的压缩预留（`effectiveReserveTokens`）与溢出量 `overflowTokens`，路由就由这两者的关系决定。precheck 失败时抛出的是固定文案 `Context overflow: prompt too large for the model (precheck)`——它是一次**准入失败**，与上层 admission 同源。

压缩执行复用 run authority：`writerFence` 校验 `expectedWriterRunId` / `expectedLifecycleRevision`，不匹配抛 `SessionTranscriptWriterClaimReboundError`——**压缩不绕过写权限**。此外还有恢复性压缩 `compactEmbeddedRunForRecovery` 与上下文溢出兜底 `recoverEmbeddedRunOverflow` 两个入口。

物理落点三件套：压缩产生 `session_windows` 新代际（`reason='compaction'`）、推进 `transcript_rewrite_watermarks`、活跃物化 `session_transcript_active_events` 经 `context_eligible` 重新标记哪些事件有资格进压缩后的 prompt。压缩后展示层读的是这个物化层而非全表，见 [Gateway](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Gateway.md) 的 chat display projection；checkpoint 的捕获 / 分支 / 恢复则在该页的生命周期服务里，两处互补。

## Memory

OpenClaw 的记忆是**纯文本 Markdown 优先**：

- **短期 / 每日记忆**：`memory/YYYY-MM-DD.md` 追加式日志，会话启动时自动加载今天与昨天，提供最新短期上下文。
- **长期 / 核心记忆**：`MEMORY.md` 存放提炼后的长期事实（用户偏好、重要事实、长期项目状态）。
- **记忆巩固（dreaming）**：三阶段 `light / deep / rem`，由 managed cron（默认每天凌晨）触发；deep 阶段有校准过的评分门槛（minScore 0.75、minRecallCount 3、recency half-life 14d、maxAge 30d），按阶段分层执行预算（fast/cheap → balanced/medium → slow/expensive）。
- **单槽机制**：`plugins.slots.memory` 同刻仅一个 memory 插件生效（默认 `memory-core`，可置 `"none"` 关闭）；第三方记忆引擎可经 sidecar 授权并存做 consolidation，但 slot-owner facts 被剥掉防借用权限。
- **来源证明**：记忆文件写入带 hash chain 账本——`originClass: "agent"` 只有当前记录的 `fileHash === sha256(contentBefore)` 才成立，否则降级为 `"untrusted"`。
- **记忆事件流**：recall / promotion / dream 四类事件落共享 state DB 的 `plugin_state_entries`（非专用表），zod 校验 + UTF8-safe 截断 + 有界保留。

## SubAgent

主 Agent 通过 `sessions_spawn` / `sessions_send_child` 工具派生子代理，子代理执行完成后结果**自动推送**回主 Agent，无需轮询。

准入有三类约束：**深度**（`maxSpawnDepth`，child 自己知道能否再派生子代理，形成递归深度门控）、**并发 / 扇出**（每 agent 子代数、swarm 组并发与总数）、**目标白名单**（`allowAgents` / `requireAgentId`，防越权派发）。

核心机制是**复用而非另起炉灶**：child 派发被封装成一次 Gateway `agent` RPC，最终复用 worker placement 调度 child run；parent 的 worker turn claim / delegated authority 经身份信封下传为 child admission 身份——**child run 的调度权继承自 parent 的 worker turn，而非重新认领**。派发本身在 Gateway 进程内时走进程内直转（连 WS 都省了），且仅 `agent` 方法带 runId 幂等键，transport 歧义失败时只重试显式 provisional replay，不会二次 launch。

spawn 是三阶段管线（initialize → dispatchTurn → register），register 同步插入注册表避免 slot 重复计数；失败回滚按相位进行——register 失败但 Gateway 已 accept 时，会主动终止那个「已接受但未登记」的孤儿 run。结果聚合有四种 completionMode：`collector`（汇入 swarm collector）、`thread-direct`（绑渠道线程）、`announce`（回传 requester）、`quiet`（仅落库）；announce 还会唤醒等待该 child 的下游 requester 续跑。

## Background Tasks, Process and System Agent

三层分工：`src/process/` 是**进程底座**（无任务语义）、`src/tasks/` 是**持久任务账本**、`src/system-agent/` 是**OpenClaw 自己的管家 agent**。

一个常见误解要纠正：**任务 owner 不止 cron**——`TASK_RUNTIMES = ["subagent", "acp", "cron", "cli"]` 四类 runtime 家族各是一名 owner，`task_runs` / `task_delivery_state` / `flow_runs` 三表是它们的共同账本。「这个任务还活着吗」不靠心跳猜，而靠 `execution_owner_{host, pid, startIdentity}` **三元组判活**：Gateway 重启后由 maintenance 把对不上的任务判 `lost` 而非重放执行。

进程底座是双 spawn 路径：长跑 / PTY 走**全局 supervisor 单例**，同步短命令走 execa 封装并用 AsyncLocalStorage 把 AbortSignal 与子进程集合绑成可级联停止的 scope。POSIX 下 spawn 即 detached，终止靠 `kill(-pid, 0)` 探测进程组再整组 SIGTERM/SIGKILL，并显式调度「过继僵尸回收」防止树杀后的后代变成未跟踪僵尸。几个有意思的点：

- **`spawn-broker` 让子进程在 Gateway 重启时「过户」而非被杀**——跨进程 spawn 代理经 IPC handoff 交出句柄与管道。
- `child-process-bridge` **不是 Gateway 桥**，是父→子的信号转发桥。
- `CommandLane` 枚举（Main / SystemAgent / Cron / Subagent / Background / HookDispatch）是调度隔离词汇；后台 work 在 command-queue 之上按 owner key 注册 lane，**全局封顶 3 且只允许 leaf work**（防嵌套等待）。
- `linux-oom-score` 调子进程 OOM 优先级——**防网关自己被 OOM killer 选中**。
- 插件想声称自己是某个 task 的 requester 会被 **WeakSet 注册表**挡住，scope 只能由宿主签发。

**System-agent**（`SYSTEM_AGENT_ID = "openclaw"`）是真实 agent：与用户 agent 共用同一条 embedded loop、session transcript、tool pipeline，但**工具面收窄到单一 ring-zero `openclaw` 工具**，指令是闭集 command vocabulary（「自由文本永不直接执行」），超时按本地路由 120s / 外部路由 30s。它的审批是**独立的一套**（不与 [Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md) 里的通用 approval store 混）：三条安全线——**host 而非会话模型决定 armed**、**agent loop 永不自我批准**、模糊输入交给独立的 single-shot classifier 且要求 provider / model / authFingerprint **全等**否则回退；待批准操作以 `sha256(stableStringify(operation))` 指纹绑定，**批准只对该精确变更有效**。

## Links

- [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw.md)
- [Gateway](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Gateway.md) / [Plugins](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Plugins.md)
- [Storage](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Storage.md) / [Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md)
- [Integrations](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Integrations.md)
- [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) / [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)
