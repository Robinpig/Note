## Introduction

这一页是 OpenClaw 的**记忆与上下文引擎**：agent 靠什么记住事、记忆怎么在会话之间固化、以及「压缩上下文」这件事实时住谁。它与 [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md) 的分工是——那页讲每轮 prompt 怎么拼、token 预算怎么决策，这一页讲记忆文件与 context engine 两个可插拔面；与 [Storage](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Storage.md) 的分工是——记忆事件落共享 state DB 的插件状态表，不走 per-agent transcript。

先纠正一个高频误解：**memory 不是 `src/memory/` 一个单例 slot**。该目录只有两个非测试文件；真正的 slot 选择逻辑在 `src/plugins/`，host 能力在 `src/memory-host-sdk/`，engine 注册表在 `src/context-engine/`——三层各有主人。

## Memory Slots and Host SDK

记忆能力按「slot 选择 → host 能力 → engine 注册」三层分工：

| 层 | 位置 | 职责 |
| :--- | :--- | :--- |
| slot 选择与注册 | `src/plugins/`（`memory-state.ts` / `memory-runtime.ts` / `registry-registrars-memory.ts` / `loader-shared.ts`，调用点 `config-normalization-shared.ts` 的 `resolveSlotSelection("memory", config?.slots?.memory)`） | 配置键 `plugins.slots.memory`；只有 `manifest.kind === "memory"` 的插件能注册 memory surface；slot 可置 `"none"` 关闭；sidecar 授权 |
| host 能力（给插件用） | `src/memory-host-sdk/`（`dreaming.ts` 707 行 + event 流 + `engine-storage.ts`） | dreaming 三阶段调度、记忆事件流、status / query / secret / multimodal 类型门面 |
| engine 注册表 + 桥 | `src/context-engine/` | context engine 的注册 / 解析 / 兼容性 / 隔离，以及到内建 compact 的 delegate 桥 |

`src/memory/` 本身只剩两件事，且都是**底座**而非引擎：

- `memory-artifact-provenance.ts` —— 记忆文件写来源账本。对 `MEMORY.md` / `USER.md` / `memory/*.md` 做相对路径归一，显式排除 `memory/dreaming/` 与 `memory/.dreams/`；用 `createCorePluginStateKeyedStore` 挂在 ownerId `"core:memory-artifact-provenance"` + namespace `"workspace-files"`，上限 50,000 条。防伪靠 **hash chain**：`recordMemoryArtifactWriteProvenance` 返回 rollback 闭包，`originClass: "agent"` 只有当前记录的 `fileHash === sha256(contentBefore)` 才成立，否则降级为 `"untrusted"`——**记忆是不是 agent 自己写的，要拿前一条内容验签**。
- `root-memory-files.ts` —— 规范 `MEMORY.md` 与遗留 `memory.md` 的路径 helper，repair 目录 `.openclaw-repair/root-memory`，resolve 拒绝 symlink。

日常形态上，记忆是**纯文本 Markdown 优先**：`memory/YYYY-MM-DD.md` 是追加式每日日志（会话启动时自动加载今天与昨天），`MEMORY.md` 存放提炼后的长期事实。没有向量数据库，检索就是读文件。

单槽机制：`plugins.slots.memory` 同刻仅一个 memory 插件生效（默认 `memory-core`）。当 slot 选的不是 `memory-core` 而 dreaming 仍启用时，bundled `memory-core` 作为 **AuthorizedDreamingSidecar** 加载做 consolidation（两个插件都必须 `manifest.kind === "memory"`），但 **slot-owner 的 facts 被剥掉**，防 sidecar 借用 runtime / recall grants。

还有一句设计意图值得单独记——`engine-storage.ts` 只有两行，注释写 "runtime storage belongs to the memory plugin"：**host SDK 不给插件存储，插件自持 store**。core 只提供事件流与调度，不替插件保管数据。

## Dreaming

dreaming 是**会话之间的记忆固化**，由 managed cron 触发（默认 `"0 3 * * *"` 每日，cron 名 `"Memory Dreaming Promotion"`，带 system-event marker；legacy 的 light/REM cron 名保留兼容）。三阶段各有分工：

| 阶段 | lookback / 门槛 | 执行预算 |
| :--- | :--- | :--- |
| `light` | lookback 2d，dedupe similarity 0.9 | fast / cheap |
| `deep` | `minScore 0.75`、`minRecallCount 3`、`minUniqueQueries 3`、recency half-life 14d、maxAge 30d | balanced / medium |
| `rem` | pattern-strength 0.75 | slow / expensive |

deep 的门槛是**校准过的**而非拍脑袋——注释原文对比 "durable facts score 0.750-0.756 vs filler 0.489-0.549"，阈值正卡在两类分布的间隙里。deep 阶段另有 recovery 线：health 低于 0.35 触发，auto-write 需 confidence ≥ 0.97。

主导出 `resolveMemoryDreamingPluginId` 读 slot（默认 `"memory-core"`），`resolveMemoryDreamingWorkspaces` 枚举所有 agent workspace 并按 `resolveWorkspaceStateIdentity` 去重——**每个 workspace 各做一次 dreaming**，不是全局一把梭。

## Memory Event Stream

recall / promotion / dream 四类事件（`memory.recall.recorded` / `memory.recall.skipped` / `memory.promotion.applied` / `memory.dream.completed`）构成记忆事件流。两个容易踩的点：

- **不是专用表**：落在共享 state DB 的 `plugin_state_entries`（namespace `"memory-host.events"`、pluginId `"memory-core"`），序列 journal + cursor namespace `"memory-host.event-cursors"`——journal 是表上的 append 约定，不是独立表，机制见 [Plugins](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Plugins.md)。
- **每 workspace 一个逻辑分区**：key 前缀 `sha256(workspaceKey)[:24] + ":event:"`。

保留与上限：10,000 events / 1,000 cursors；每 event JSON 上限 8 KiB、10 items、2 KiB texts；写前过 zod discriminated-union 校验 + UTF8-safe 截断。消费面是 plugin-sdk 的 `memory-host-events.ts`；`serializeMemoryHostEventExport` 导出时间序 JSONL，上限 1 MiB。旧 workspace 的 `memory/.dreams/events.jsonl` 只留给 doctor 迁移发现。

## Context Engine Registry

`src/context-engine/` 管的是「谁来实现 compact / assemble」这件事本身。接口 `ContextEngine` 有八个槽：`bootstrap? / maintain? / ingest / ingestBatch? / afterTurn? / commitTurn? / assemble / compact`——**压缩只是其中一槽**，上下文维护是完整生命周期。

- **slot 选择**：`plugins.slots.contextEngine` + `defaultSlotIdForKey("contextEngine")` fallback。全库 slot 恰有 `{memory, contextEngine}` 两个，不存在通用 provider slot。
- **legacy 引擎**（`legacy.ts`）：`ingest` no-op（SessionManager 已持久化）、`assemble` pass-through（attempt 管线）、`compact = delegateCompactionToRuntime`——保留为 canonical delegate 身份，让 host 知道 runtime 拥有 watchdog。`registerLegacyContextEngine()` 支持 `allowSameOwnerRefresh` 供测试 / bootstrap 重注册；`ensureContextEnginesInitialized()` 在 boot 时保证 legacy fallback slot 存在。
- **quarantine**：失败引擎进 `quarantine-health.ts` 隔离，不拖垮主链路。
- **host 能力协商**（`host-compat.ts`）：host 声明能力集（`OPENCLAW_EMBEDDED_CONTEXT_ENGINE_HOST = [bootstrap, assemble-before-prompt, after-turn, maintain, compact, runtime-llm-complete]`；Codex app-server 追加 `thread-bootstrap-projection`；generic CLI 默认只 `[bootstrap, after-turn, maintain]`），engine 自己按 operation 声明 `hostRequirements[operation].requiredCapabilities`，`evaluateContextEngineHostSupport` 做差集、不匹配即抛诊断错误。`supportsContextEngineDurableTurnAdvancement` 门控在 `turnAdvancementIdempotency === "atomic-idempotent-v1"` + `commitTurn` 存在。

**delegate 桥**（`delegate.ts`）让第三方引擎复用内建 compact：`delegateCompactionToRuntime` 懒加载 `embedded-agent-runner/compact.runtime.js` → `compactEmbeddedAgentSessionOnDemand`——与 `/compact` 和 overflow recovery 同一通路；`compactionTarget` knob 被故意忽略以保 legacy 行为。记忆 system prompt 也走这座桥（`buildMemorySystemPromptAddition`），让第三方引擎得到同样的记忆指导。

## Compaction Watchdog

`compaction-watchdog.ts` 的名字最容易误导——**它不是计时器，是身份标签**。本体是挂在 `Symbol.for("openclaw.runtimeCompactionDelegates")` 上的 **process-global WeakSet**，标记哪个 `compact` 函数是 canonical runtime delegate（注释："ownership must survive registry projection proxies and duplicate dist chunks"）。导出 `markRuntimeCompactionDelegate` / `inheritRuntimeCompactionDelegate` / `bindContextEngineCompaction` / `isRuntimeCompactionDelegate` 四个函数，全是打标签与认标签。

真正的超时在 `src/agents/embedded-agent-runner/compaction-safety-timeout.ts`：`compactContextEngineWithSafetyTimeout` 对 delegate 保留 native runtime 的**进度感知 watchdog**（`resetTimeout` 经 `runtimeContext.compactionTimeoutReset` 传递）并 race caller abort；非 delegate 受 host 边界 `EMBEDDED_COMPACTION_TIMEOUT_MS` 约束，防挂起的插件 compact 拖住 turn。

这与 [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md) 的压缩决策是**两种触发**：`shouldPreemptivelyCompactBeforePrompt` 是 before-prompt 的 **token 预算**决策；watchdog 是 during-compact 的 **wall-clock 执行超时归属**。桥接点在 `run/compaction-runtime.ts` 与 `compact.queued-execution.ts` 调 `bindContextEngineCompaction`。另外 context engine 的每轮维护任务在任务账本里的身份是 `runtime:"acp", taskKind:"context_engine_turn_maintenance"`，见 [Process](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Process.md)。

## Links

- [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md)
- [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md) / [Storage](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Storage.md)
- [Plugins](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Plugins.md) / [Process](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Process.md)
- [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) / [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)
