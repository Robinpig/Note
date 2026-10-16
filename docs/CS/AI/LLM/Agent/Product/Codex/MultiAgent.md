> 版本基线：核实于 2026-10-16，对应 commit `6b991972c5b5`（`main`，2026-10-15）。

## Introduction

2026 年的 Codex 已经从「一个会话跑一个任务」长成了**多 Agent 运行时**：会话可以派生子 Agent（`ThreadSpawn`）、角色可配置（`agent-roles`）、Agent 之间有消息板与图存储。与之配套的三块——**Memories**（跨会话记忆）、**Code Mode**（远程代码执行会话）、**Cloud Tasks**（云端任务）——共同回答「一个内核如何同时服务本地与云端、当前与跨会话」。

## Multi-Agent V2

多 Agent 能力以 `MultiAgentVersion::V2` 为门面：版本不是 V2 时，相关指令注入与模式判定全部关闭。配置在 `MultiAgentV2Config`：

| 字段 | 作用 |
| :--- | :--- |
| `root_agent_usage_hint_text` / `subagent_usage_hint_text` | 覆盖 root / 子 Agent 的默认角色指令 |
| `multi_agent_mode_hint_text` | 覆盖模式说明文本 |
| `max_concurrent_threads_per_session` | 单会话并发子 Agent 上限 |
| `wait_agent_enabled` | 是否提供等待子 Agent 的工具 |
| `expose_spawn_agent_model_overrides` | 派生时是否允许指定模型 |

**触发模式**（`MultiAgentMode`）分三档：`ExplicitRequestOnly`（默认，只有用户/模型显式要求才派生）、`Proactive`（推理档位为 `Ultra` 时主动派生）、`Custom`（用模型目录或配置里的自定义文本替换内置说明）。指令注入按会话来源分流（`SessionSource`）：Cli / VSCode / Exec / Mcp / Custom / Unknown 与 `SubAgent(ThreadSpawn)` 注入对应角色指令，`Internal` 与其他 SubAgent 来源不注入——**子 Agent 自己不再被鼓励继续派生**，防止层级爆炸。

支撑 crate 四个：`agent-roles`（角色配置的发现与加载：`agent_role_config` / `discovery` / `loader`）、`agent-graph-store`（Agent 关系图存储）、`agent-message-board-client`（Agent 间消息板客户端）、`agent-identity`（Agent 身份）。会话侧落点在 `core/src/agent/`（`agent_resolver`、`child_config`、`control`、`registry`、`role`、`status`）与 `core/src/thread_spawn.rs`、`thread_manager`；输入侧的 `InterAgentCommunication` 形态（见 [Turn](/docs/CS/AI/LLM/Agent/Product/Codex/Turn.md)）是跨 Agent 消息进入会话的入口。

⚠️ **权限不天然继承**：子 Agent 是独立会话，审批、沙箱与配置按自己的 `child_config` 走，父会话的授权不会自动带过去——这是与「同一会话内多工具」的本质区别。

## Memories

跨会话记忆分成读、写两个子 crate，职责对称：

**写侧**（`memories/write`）：拥有启动时的记忆固化流水线——Phase 1 / Phase 2 两阶段提示渲染（先粗加工再精炼）、工作区 diffing（对比本次会话改了哪些记忆相关文件）、扩展裁剪（`prune_old_extension_resources`）。产物落盘三件套：`raw_memories.md`（原始记忆）、`rollout_summaries/`（按会话的摘要）、`extensions/`（记忆扩展，每个扩展一份 `instructions.md` 说明如何解读该来源）。扩展资源保留 **14 天**（`RETENTION_DAYS`），过期由 `prune` 清理；`guard` 限制单来源写入量。`rebuild_raw_memories_file_from_memories` / `sync_rollout_summaries_from_memories` 负责从结构化记忆重建原始文件。

**读侧**（`memories/read`）：`citations`（记忆引用——模型用的每条记忆能指回来源）、`usage` / `metrics`（用量与指标）。

与 Rollout 的分工：Rollout 是**审计与恢复**的事实流（可完整重建会话），Memories 是**提炼后跨会话可用**的沉淀——前者求全，求可追溯；后者求压缩，求可消费。

## Code Mode

Code Mode 让模型在**远程/独立会话**里写代码执行，而不是在宿主进程里直接跑（`code-mode` + `code-mode-host` + `code-mode-protocol` + `code-mode-runtime` 四 crate）。三种会话提供方：

| 提供方 | 形态 |
| :--- | :--- |
| `ProcessOwnedCodeModeSession` | 本进程拥有的远程会话 |
| `GrpcCodeModeSessionProvider` | 经 gRPC 委托的远程会话 |
| `DisabledCodeModeSessionProvider` | 显式关闭 |

`code-mode-host` 内部有 gRPC 服务面（`grpc/session.rs`、`grpc/events.rs`、`grpc/routing.rs`）与 delegate 机制；会话侧 `session/code_mode_warning.rs` 负责模式切换时向用户示警。与 `exec-server` 的关系：exec-server 提供受控执行通道，Code Mode 在其上再包一层「远程会话」语义——本地与云端执行共享同一份沙箱策略（见 [Sandbox](/docs/CS/AI/LLM/Agent/Product/Codex/Sandbox.md)）。

## Cloud Tasks

`cloud-tasks` crate（`app.rs` / `cli.rs` / `new_task.rs` / `env_detect.rs` / `scrollable_diff.rs` / `ui.rs`）是**云端任务的本地控制面**：从本地发起云端 Codex 任务、检测环境（本地还是云端）、滚动 diff 查看。配合 `cloud-client` / `cloud-config` / `cloud-tasks-client`，本地 TUI 与云端执行之间是同一套 Thread/Turn 协议的两种部署。

## Links

- [Codex 主入口](/docs/CS/AI/LLM/Agent/Product/Codex/Codex.md) / [Turn：任务生命周期](/docs/CS/AI/LLM/Agent/Product/Codex/Turn.md)
- [Extensions：MCP/Skills/Plugins/Hooks](/docs/CS/AI/LLM/Agent/Product/Codex/Extensions.md) / [Sandbox：沙箱](/docs/CS/AI/LLM/Agent/Product/Codex/Sandbox.md)
- [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) — Multi-Agent 与 SubAgent 的通用模式
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) — Harness 作为外部记忆管理器

## References

- [openai/codex](https://github.com/openai/codex)
