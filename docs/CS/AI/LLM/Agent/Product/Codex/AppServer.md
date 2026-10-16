> 版本基线：核实于 2026-10-16，对应 commit `6b991972c5b5`（`main`，2026-10-15）。

## Introduction

app-server 是 Codex 的**控制平面**：一个双向 JSON-RPC 服务，让 CLI、IDE、桌面应用与业务系统共享同一个 Agent 内核。它要解决的不是「怎么把功能做完」，而是「多个异构客户端如何安全地挂到同一个运行时上」——所以它的代码重心在协议版本管理（v1/v2 双轨）、传输抽象（stdio / UDS / 守护进程）与配置管理层，而非业务逻辑。

## Protocol

协议定义在独立 crate `app-server-protocol`，分三个模块：`protocol/v1`、`protocol/v2` 与 `rpc`，外加 `experimental_api` 放实验性接口。从 `lib.rs` 的导出面能看到协议的词汇表：

| 类别 | 代表类型 |
| :--- | :--- |
| 握手 | `InitializeParams` / `InitializeResponse` / `InitializeCapabilities` / `ClientInfo` |
| 审批 | `ExecCommandApprovalParams` / `ExecCommandApprovalResponse`、`ApplyPatchApprovalParams` / `ApplyPatchApprovalResponse` |
| 会话 | `ConversationSummary`、`ConversationGitInfo`、`GitSha`、`GetConversationSummaryParams` |
| 认证 | `GetAuthStatusParams` / `GetAuthStatusResponse`、`LoginApiKeyParams` |
| 其他 | `SandboxSettings`、`Tools`、`UserSavedConfig`、`InterruptConversationResponse`、`GitDiffToRemoteParams` |

协议还带**代码生成**：`generate_json` / `generate_ts` / `generate_types` 从 Rust 类型产出 JSON Schema 与 TypeScript 类型——SDK 与协议永远同源，不会出现「文档说一套、SDK 另一套」。

## Lifecycle

对外生命周期：

```
initialize → thread/start 或 thread/resume → turn/start → 持续接收 item/* 与 delta 事件 → turn/completed
```

双向 JSON-RPC：客户端发 `turn/start`，服务端推 `item/started`、delta、审批请求。队列有界并做背压，过载时返回可重试错误。中断是显式 RPC（`InterruptConversation`），不是断开连接——断开在服务端会被当作审批 fail-closed 的 `Abort` 触发器（见 [Approval](/docs/CS/AI/LLM/Agent/Product/Codex/Approval.md)）。

## Daemon and Transport

app-server 有三种部署形态，对应三组 crate：

| 形态 | crate | 场景 |
| :--- | :--- | :--- |
| 进程内 / stdio | `app-server` | IDE 扩展直接 spawn |
| 守护进程 | `app-server-daemon` | 长期驻留，多客户端连接 |
| 客户端库 | `app-server-client` + `app-server-transport` | SDK 复用连接逻辑 |

传输层 `uds`（Unix Domain Socket）与 `stdio-to-uds`（stdio 桥接）解耦了「客户端只会 stdio」与「服务端实际监听 UDS」的错配。守护进程侧有 `daemon_thread_recovery`（会话/`session/daemon_recovery.rs` 配套）处理崩溃后的 Thread 恢复。

## Config Management

`app-server/src/config_manager*.rs` 一族（`config_layer.rs`、`config_manager_service*.rs`、`effective_plugin_change.rs`）是控制面里最重的一块：客户端可以通过 RPC **查看与修改生效配置**（分层配置栈的用户层 / 会话层）。配置改动会触发 `config_refresh`（`session/config_refresh.rs`）——运行中的会话热加载配置，不需要重启。凭据编辑走独立路径（`config_manager_service_credential_edits.rs`），与普通配置分离。

`connection_rpc_gate.rs` 是 RPC 准入闸门（连接级权限检查），`dynamic_tools.rs` 允许客户端动态注册工具，`application_network.rs` 管理应用级网络策略。

## Three Integration Paths

外部接入内核有三条路，按控制力递增：

| 方式 | 入口 | 适用 |
| :--- | :--- | :--- |
| `codex exec` | `exec` crate（非交互模式） | 脚本化调用、CI |
| SDK | `sdk/`（Python / TypeScript） | 程序内嵌 |
| app-server | JSON-RPC | 复杂 UI、长期 Thread、多客户端 |

非交互模式（`codex exec`）有两套事件处理器：人类可读输出与 JSONL 输出（`event_processor_with_human_output.rs` / `event_processor_with_jsonl_output.rs`），后者是管道消费的正式接口。

## Links

- [Codex 主入口](/docs/CS/AI/LLM/Agent/Product/Codex/Codex.md) / [Architecture：仓库与 crate 地图](/docs/CS/AI/LLM/Agent/Product/Codex/Architecture.md)
- [Turn：任务生命周期](/docs/CS/AI/LLM/Agent/Product/Codex/Turn.md) — app-server 驱动的正是 Turn 生命周期
- [Approval：审批](/docs/CS/AI/LLM/Agent/Product/Codex/Approval.md) — 审批事件在协议层的Params/Response 成对出现
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) — Host/Harness/Model 三层边界

## References

- [openai/codex](https://github.com/openai/codex)
