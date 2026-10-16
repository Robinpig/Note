## Introduction

OpenClaw 的存储只有一条铁律——**全部 SQLite**。这一页覆盖会话的两层数据库、读投影与写路径，以及 agent run 可被调度到远端 worker 的 placement 机制；它是 [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md) 主链路里「回写 Session」那一站的完整展开，与 [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md) 的压缩写入、[Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md) 的 commit guard 校验点直接相接。

## Sessions and Storage

存储只有一条铁律：**SQLite（`node:sqlite`）+ Kysely，禁止新建 JSON / JSONL / sidecar 存储**，状态目录 `~/.openclaw`（`OPENCLAW_STATE_DIR` 可配）。分两层数据库角色：

- **共享 state DB**（每进程一个）：agent 注册、机器状态、lease、audit、approval、plugin state、任务账本等全局面。
- **per-agent SQLite**（每个 agent 一个）：对话 / transcript / 投影主存。

物理 DDL 的权威**不在文档站也不在 .ts**——是 `src/state/openclaw-agent-schema.sql`（933 行、46 张 STRICT 表），由 `openclaw-agent-schema.ts` 经 `readFileSync` 读取；生产构建会替换该模块，使打包后打开数据库无需附带资产文件。**schema 版本 `OPENCLAW_AGENT_SCHEMA_VERSION = 21`**，迁移只向前，旧版拒绝更新 schema（`openclaw-agent-db-contract.ts` 有版本契约注释）。CI 用 `check-native-state-schema-version.mjs` 校验 Swift 与 TS 两份 contract 的版本一致；`openclaw doctor --fix` 拥有 file→SQLite 迁移并把 receipt 写进 `migration_runs` / `migration_sources`。

核心表：

| 表 | 角色 |
| :--- | :--- |
| `session_nodes` | 逻辑会话节点；`entry_json` 整存整条元数据（避免 EAV，新字段不触发 DDL）；status CHECK 枚举；parent / spawned_by 层级 |
| `session_windows` | 会话代际；`reason` CHECK 含 compaction——压缩产生的代际翻转 |
| `transcript_events` | transcript 事件流，PK `(session_id, seq)`，agent run 逐 turn 写入 |
| `conversation_deliveries` | 渠道对话身份与出站收据（send/turn、platform_message_id、reply_*） |
| `trajectory_runtime_events` | agent run 内部执行轨迹（tool 调用 / 步骤 / 错误），与面向用户的 transcript 区分 |

几个值得记的设计点：所有表 STRICT + CHECK 枚举运行时即校验；partial 索引缩小热路径；`message_idempotency_key` 唯一索引保证消息不重复投递；**`session_nodes` 上的 AFTER 触发器在元数据写入时把 `entry_valid` 置 0**——写即失效、读前重准入，把权限校验固化到存储层；transcript 分 active（热，物化）/ archive（温，回收）/ cold archive（冷）三层，配 rewrite watermark。

读侧有一层**内存投影层**（`session-row-projection`）：不直接把 SQLite 暴露给列表接口，而是把多个物理 store 合并投影成行视图。Row 身份三元组 = 逻辑 agent + 物理 store 路径 + session key，**同一个 logical key 可同时存在于多个物理 store**（federation），列表时保留每个物理副本而非去重。**incognito 会话**走独立进程内 SQLite 路径，不进 resident 内存表、不跨重启持久化，但单 key 读可经 exact read 直达（web-only、immutable、无持久父、admin scope）。

写侧（`sessions-mutations`）是一条分层链路：RPC handler 校验 scope → patch engine preflight（按 store 去重）→ lifecycle mutex 串行化 → snapshot 再解析（防 stale alias 被提升）→ **commitGuard 在写前 / 写时多次重校验 authority** → 底层同步 SQLite 事务（权限校验在 commit 内，失败整事务回滚）。transcript 事件写是另一条独立路径，由 agent runtime 直接驱动。

preflight 与落盘之间还有几道容易被忽略的工序：archive 准备要在 mutex 之前做（cloud reclaim 可能更早就需要它）；分组键是 `storePath\0targetAgentId`，每个 store 内部并行；`sessions.patchMany` 里重复 target 直接判 `Duplicate target.` 而不是静默去重。底层替换投影还要做三组 CAS 校验——canonical keys 不重叠、被替换的 alias 必须存在、不能 targeting internal effects rows。

冷数据另有一个**独立 cold mutation Worker 线程**做 cold transcript 写入 / 恢复 / 回收：写许可走 `withWorkerWriteAdmission` 的 `admission-request` / `admission-release` 协议，**许可可被 revoke**（revoked 即抛错），`markSqliteReclamationSettled` 作为 commit gate 让 parent 加入 cold 事务，`reclaimSqliteFreePages` 回收空闲页且最多跑 64 趟。

一句话概括写路径的性格：**权限校验在事务 commit 之内**，失败整事务回滚，而不是 COMMIT 后再 repair——后者会让调用方去重试一个已经 durable 的事务。

## Worker Placement

OpenClaw 不是「Gateway 单进程跑到底」——agent run 可被**调度到远端 worker 节点**执行，这是全库最复杂的边界之一。

核心概念：

- **Worker / Worker Environment**：执行 agent run 的节点，分 `local`（Gateway 进程内）与远端 node worker（经注册 + tunnel 与 Gateway 通信，工作区同步）。
- **Placement**：session 到 worker environment 的指派，持久化在 `worker_session_placements` 表。
- **Turn claim**：单次执行轮次的**独占所有权声明**（owner / environmentId / ownerEpoch / claimId / runId / placementGeneration），一个 session 同时只能有一个 active claim。
- **Owner epoch / generation**：worker 世代号与 placement 状态机的 CAS 乐观锁版本号。

状态机：

```
local → requested → provisioning → syncing → starting → active → draining → reconciling → reclaimed / local / failed
```

准入是逐项强校验：credential hash 常量时间比较、turnClaim 必须匹配（owner + sessionId + runId + environmentId + ownerEpoch）、credential 未过期、environment 状态正常、bundle hash / openclaw version / ownerEpoch / protocolFeatures 一致（防 stale worker build 拿到 authority）。**每次 worker RPC 都重校验 live ownership**。

这里藏着全库最重要的一个工程原则：**HMAC / TTL / 匹配标识本身不等于 live authority**——「等待永不授予权限」，副作用前必须重校验。它在 worker placement、原生 app 连接、session 写路径、压缩写入、审批解析里反复出现，是同一种范式的不同落点，完整串联见 [Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md?id=the-authority-chain) 页的 The Authority Chain。

## Links

- [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md)
- [Gateway](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Gateway.md) / [Lifecycle](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Lifecycle.md)
- [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md) / [Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md)
- [Observability](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Observability.md)
- [Nodejs](/docs/CS/front-end/Nodejs.md)
