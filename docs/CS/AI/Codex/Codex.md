## Introduction

Codex（OpenAI）是一个**本地运行的 AI 编程 Agent**：它把用户的自然语言请求，转成对大模型的请求、并在本地执行工具（读写文件、运行命令、打补丁），再把结果回填进下一轮模型调用。它以一个 Rust 实现（`codex-rs`，133 个 crate）为核心，对外提供两种前端形态——交互式终端 TUI 与常驻的 app-server 守护进程（供桌面 App、IDE、Web、移动端远程接入）。

> 版本基线：v0.167.0（`E:/Projects/codex-rust-v0.167.0`）

几个反直觉的点：

- **你装到的 `codex` 命令只是一个壳**：npm 包 `@openai/codex` 本身不含引擎，它按平台解析并拉起一个预编译的原生二进制；真正的逻辑全在那一个 Rust 二进制里。
- **一个二进制扮演多种角色**：同一个可执行文件通过 `argv0`/`argv1` 自检，能把自己 re-exec 成 `apply_patch`、沙箱子进程、exec/fs helper 等专用子程序，而不是另外打包一堆小工具。
- **TUI 和 app-server 不是两套引擎**：它们都只是 `codex-core` 这个引擎库的不同「驾驶舱」，核心会话逻辑只有一份。

## What Codex Is

Codex 的定位是「在用户机器上、受沙箱约束地、闭环调用模型的编码代理」。它的边界可以这样理解：

- **输入端**：用户 prompt、初始图片、可附加目录（`--add-dir`）、仓库里的 `AGENTS.md`/`agents.md` 指令、MCP 工具、插件。
- **处理端**：`codex-core` 中的「线程（Thread）」——一个持有 `Session` 的会话单元，负责组装上下文、调用模型、执行工具、做压缩（compact）、产出回放（rollout）。
- **输出端**：模型回复、工具调用结果、流式事件（`Op`）、落盘的会话历史与回放文件。

为什么需要「两种前端」而不是只有 CLI？因为 IDE/桌面 App 需要的是**常驻、可被多客户端并发接入、走 JSON-RPC 协议**的服务，而你敲 `codex` 进的那个交互式终端则是**单用户、单会话、直接渲染**的前端。两者需求不同，但都只需要驱动同一份 `codex-core`，所以 Codex 把引擎做成库、把前端做成薄壳——这正是它的架构主轴。

## Architecture at a Glance

逐层展开见 [Codex Architecture](/docs/CS/AI/Codex/Architecture.md)：从发布壳 → 原生二进制 → 单一引擎 `codex-core` → 共享协议 `codex-protocol` 的分层，以及 TUI / app-server 两个前端如何共用引擎。引擎内部的会话循环见 [Codex 核心会话循环](/docs/CS/AI/Codex/SessionLoop.md)：`submit(Op)` 经 `submission_loop` 分发、`run_turn` 外层循环、`try_run_sampling_request` 流式内循环、工具并发执行与审批门控（oneshot 挂起/解挂）。隔离与审批机制的独立深挖见 [Codex Sandbox](/docs/CS/AI/Codex/Sandbox.md)：跨平台沙箱（bwrap+seccomp+landlock / Seatbelt / MXC）、`network-proxy` 的 MITM+凭证代理、execpolicy 与 session 审批两道正交门控。Agent 协作机制的独立深挖见 [Codex 多 Agent](/docs/CS/AI/Codex/MultiAgent.md)：角色层、spawn 引擎与配置遗传、spawn 拓扑 DAG（agent-graph-store）、消息板通信（channel/thread/post + SSE）；以及 [Codex Code Mode](/docs/CS/AI/Codex/CodeMode.md)：用 JS 在 V8 隔离环境编排工具调用的机制（exec/wait 工具、cell/session/delegate、宿主与运行时）。工具系统的链路式拆解见 [Codex 工具系统](/docs/CS/AI/Codex/Tools.md)：契约层（`ToolDefinition`/`ToolSpec`/`ToolExecutor`）、注册表与路由（`ToolRegistry`/`ToolRouter`，`register_trusted` vs `register_external`）、编排器（审批+沙箱+升级重试、`ToolRuntime` 与 handler/runtime 拆分）、`spec_plan` 工具集装配、自研 apply_patch 模糊匹配算法与 shell-command 解析。记忆与上下文管理的独立深挖见 [Codex 记忆与上下文管理](/docs/CS/AI/Codex/MemoryContext.md)：记忆的两阶段写入流水线（Phase1 抽取 / Phase2 合并智能体 + git 基线）、读取路径经 `ext/memories` 扩展切成带上限的 developer 片段注入、上下文片段模型（`ContextualUserFragment`/`RenderedFragment`/`AnnotatedContent`）、装配入口 `build_initial_context_with_world_state` 与每步 `capture_step_context`、`ContextManager` 快照共享、以及压缩/预算/GUARDIAN 截断的窗口管理。插件体系的独立深挖见 [Codex 插件系统](/docs/CS/AI/Codex/PluginSystem.md)：包级插件（marketplace 安装、manifest 四能力 skills/MCP/hooks/apps、`PluginsManager`+`loader`+`PluginLoadOutcome` 加载流水线、Agent 插件与可发现插件、`plugin-host` 的 V8 UI 插件宿主 ABI 与进程生命周期）；可观测性的独立深挖见 [Codex 可观测性](/docs/CS/AI/Codex/Observability.md)：`otel` crate 的 logs/traces/metrics 三路导出、`OtelProvider` 全局安装与导出过滤、`PolicyExporter` 网络策略约束、W3C trace 上下文、指标字典、会话遥测事件、trace websocket 桥与热重载。持久化与状态的独立深挖见 [Codex 持久化与状态](/docs/CS/AI/Codex/Persistence.md)：rollout JSONL 作为不可变主记录（后台 writer task、append-only、崩溃重开重试、`~/.codex/sessions/YYYY/MM/DD` 布局、压缩）、`state` crate 的 `StateRuntime` 多 SQLite 库（state/logs/goals/memories/queue）异步 backfill 索引、`SessionState` 内存态与 `LocalThreadStore`、以及 `reconstruct_history_from_rollout` 的重放/压缩点界定恢复。认证与模型接入的独立深挖见 [Codex 认证与模型接入](/docs/CS/AI/Codex/AuthAndModels.md)：`login`（AuthManager/OAuth/TokenData/WorkspaceRouting）、`agent-identity`（ed25519+JWT/JWKS）、`workload-identity`（断言兑换）三层认证，加上 `model-provider-info` 注册表、`model-provider`（create_model_provider + auth + workspace routing）与 `models-manager`（catalog/cache/预设），最终在 core 的 `ModelClient`/`ModelClientSession` 收口。远程执行的独立深挖见 [Codex exec-server 与远程执行](/docs/CS/AI/Codex/ExecServer.md)：`codex-exec-server` 独立服务把进程/文件系统/环境/能力发现/HTTP 封装为 JSON-RPC，经 WebSocket/stdio/Noise 三种传输暴露；`EnvironmentManager` 在本地沙箱与远程环境间择一，远端执行经 `ExecServerClient` 以协议方法发到远端或 fs-helper。TUI 与交互的独立深挖见 [Codex TUI 与交互](/docs/CS/AI/Codex/Tui.md)：TUI 实为 app-server 客户端（Embedded/LocalDaemon/Remote 三形态）、`AppServerSession` typed facade、终端层的 EventBroker drop/recreate 交接 stdin 与 FrameRequester 帧合并、已定稿历史直接写终端 scrollback（insert_history）、主循环五路 `tokio::select!`（AppEvent/线程事件/终端事件/多会话 app-server 事件/daemon 重启）、ChatWidget 双 cell 模型与 transcript overlay 缓存、审批 ServerRequest 往返闭环。

## Links

- [Codex Architecture](/docs/CS/AI/Codex/Architecture.md)
- [Codex 核心会话循环](/docs/CS/AI/Codex/SessionLoop.md)
- [Codex Sandbox](/docs/CS/AI/Codex/Sandbox.md)
- [Codex 多 Agent](/docs/CS/AI/Codex/MultiAgent.md)
- [Codex Code Mode](/docs/CS/AI/Codex/CodeMode.md)
- [Codex 工具系统](/docs/CS/AI/Codex/Tools.md)
- [Codex 记忆与上下文管理](/docs/CS/AI/Codex/MemoryContext.md)
- [Codex 插件系统](/docs/CS/AI/Codex/PluginSystem.md)
- [Codex 可观测性](/docs/CS/AI/Codex/Observability.md)
- [Codex 持久化与状态](/docs/CS/AI/Codex/Persistence.md)
- [Codex 认证与模型接入](/docs/CS/AI/Codex/AuthAndModels.md)
- [Codex exec-server 与远程执行](/docs/CS/AI/Codex/ExecServer.md)
- [Codex TUI 与交互](/docs/CS/AI/Codex/Tui.md)
- [AI 总纲](/docs/CS/AI/AI.md)
- [LLM Agent 理论](/docs/CS/AI/LLM/Agent/Theory/Agent.md)
- [MCP 协议](/docs/CS/AI/LLM/Protocol/MCP.md)

## References

1. [openai/codex（v0.167.0）](https://github.com/openai/codex/tree/v0.167.0)
2. [Codex CLI 文档](https://developers.openai.com/codex/cli/)
