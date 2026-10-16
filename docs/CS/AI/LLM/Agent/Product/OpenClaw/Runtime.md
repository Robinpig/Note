## Introduction

这一页是 OpenClaw 的**执行内核**：一次 agent run 怎么跑起来、模型怎么调、工具从哪来、上下文怎么压缩。它是 [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md) 枢纽那条「入站 → agent runtime → provider → 工具 → 回写」链路的中段；工具来源与插件契约在 [Plugins](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Plugins.md)，会话落盘在 [Storage](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Storage.md)；长在内核之上的记忆、子代理与后台工作各自独立成页（文末「Where the Loop Grows Things」给出指针）。

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

物理落点三件套：压缩产生 `session_windows` 新代际（`reason='compaction'`）、推进 `transcript_rewrite_watermarks`、活跃物化 `session_transcript_active_events` 经 `context_eligible` 重新标记哪些事件有资格进压缩后的 prompt。压缩后展示层读的是这个物化层而非全表，见 [Gateway](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Gateway.md) 的 chat display projection；用户 / 系统主动捕获的 compaction checkpoints（捕获 / 分支 / 恢复）则在 [Lifecycle](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Lifecycle.md) 的会话生命周期服务里，与这里的自动压缩互补。压缩的**执行者**是 context engine 注册表里的插件（内建 compact 只是 legacy delegate），见 [Memory](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Memory.md)。

## Where the Loop Grows Things

执行内核之上还长着三块可插拔机制，各自独立成页：

- **记忆与上下文引擎**在 [Memory](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Memory.md)：记忆是纯文本 Markdown 优先（`memory/YYYY-MM-DD.md` 每日日志 + `MEMORY.md` 长期事实），会话之间的固化靠 dreaming 三阶段；「压缩」的实际执行者是 context engine 注册表里的插件，内建 compact 只是 legacy delegate。该页还澄清了一个命名陷阱——`compaction-watchdog.ts` **不是计时器**，而是标记 canonical runtime delegate 的 process-global WeakSet。
- **子代理编排**在 [SubAgent](/docs/CS/AI/LLM/Agent/Product/OpenClaw/SubAgent.md)：`sessions_spawn` / `sessions_send_child` 派生的 child run 不重新认领权限，而是把 parent 的 worker turn claim 经身份信封下传为 child admission 身份。
- **后台工作三层底座**在 [Process](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Process.md)：进程底座（supervisor / spawn-broker / lane 队列）、任务账本（`TASK_RUNTIMES` 四类 owner）、以及 OpenClaw 自己的 system-agent 管家。

## Links

- [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md)
- [Gateway](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Gateway.md) / [Plugins](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Plugins.md)
- [Storage](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Storage.md) / [Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md)
- [Memory](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Memory.md) / [SubAgent](/docs/CS/AI/LLM/Agent/Product/OpenClaw/SubAgent.md) / [Process](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Process.md)
- [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) / [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)
