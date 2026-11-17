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

## Architecture

### Layered Architecture

```dot
digraph CodexArch {
  rankdir=TB;
  node [shape=box, style=rounded];

  subgraph cluster_dist {
    label="发布层 / Distribution";
    shell [label="codex-cli (npm 壳)\nbin/codex.js"];
    native [label="原生二进制\n@openai/codex-<target>"];
  }

  subgraph cluster_bin {
    label="单一二进制 / codex-rs cli crate";
    arg0 [label="arg0_dispatch\n(argv0/argv1 自检)"];
    cli [label="MultitoolCli (clap 多工具)\ndispatch_cli"];
    helpers [label="专用子程序\napply_patch / sandbox / exec-fs helper"];
  }

  subgraph cluster_front {
    label="前端 / Frontends（薄壳，仅驱动引擎）";
    tui [label="tui crate\n交互式终端"];
    appsrv [label="app-server + app-server-protocol\n常驻守护进程 (JSON-RPC)"];
    remote [label="远程客户端\n桌面App / IDE / Web / 移动"];
  }

  subgraph cluster_engine {
    label="引擎 / codex-core（唯一 agent 逻辑）";
    tm [label="ThreadManager\n(建线程、驻留内存)"];
    thread [label="CodexThread\n(会话线程: Session + SessionIo)"];
    session [label="Session\n上下文/模型调用/工具/压缩/回放"];
  }

  protocol [label="codex-protocol\nTurnInput / Op / EnvironmentConfig", shape=note];

  shell -> native [label="按平台拉起"];
  native -> arg0;
  arg0 -> helpers [label="re-exec 专用角色"];
  arg0 -> cli;
  cli -> tui [label="无子命令 / agents"];
  cli -> appsrv [label="app-server 子命令"];
  remote -> appsrv [label="ws/tcp/stdio"];
  tui -> thread;
  appsrv -> tm;
  tm -> thread [label="start_thread"];
  thread -> session;
  tui -> protocol;
  appsrv -> protocol;
  thread -> protocol [label="Op 事件流"];
}
```

### The Distribution Shell

`codex` 命令的第一跳并不是 Rust 代码本身。`codex-cli` 这个 npm 包（`@openai/codex`）的 `bin/codex.js` 只是一个**下载器与启动器**：它根据 `process.platform`/`process.arch` 算出目标三元组，再映射到对应的平台原生包（如 `@openai/codex-linux-x64`、`@openai/codex-darwin-arm64`、`@openai/codex-win32-x64`），从中找到并 `spawn` 真正的原生可执行文件。

```javascript
const PLATFORM_PACKAGE_BY_TARGET = {
  "x86_64-unknown-linux-musl": "@openai/codex-linux-x64",
  "aarch64-apple-darwin": "@openai/codex-darwin-arm64",
  "x86_64-pc-windows-msvc": "@openai/codex-win32-x64",
  // ...
};
```

含义：用户通过 npm/pnpm 安装的是壳，**真正的逻辑、版本与更新都绑定在那个按平台分发的原生二进制上**。这也是为什么同一份文档对「Codex 是什么语言写的」会给出不同答案——入口是 JS，主体是 Rust。

### The Single Binary, Multiple Personalities

原生二进制由 `codex-rs/cli` crate 编译而成，但它**不只是一个 CLI**：`arg0_dispatch`（来自 `codex-rs/arg0`）在 `main` 最早期读取 `argv0`（可执行文件名）与 `argv1`，按约定把自己切到不同的专用 `main`。这是为了把「沙箱里的子进程」「补丁应用器」等都复用同一个二进制，而不是额外打包小工具。

```rust
pub fn arg0_dispatch() -> Option<Arg0PathEntryGuard> {
    let argv0 = /* 可执行文件名 */;
    if exe_name == CODEX_LINUX_SANDBOX_ARG0 {
        codex_linux_sandbox::run_main();
    } else if exe_name == APPLY_PATCH_ARG0 || exe_name == MISSPELLED_APPLY_PATCH_ARG0 {
        codex_apply_patch::main();
    }
    let argv1 = args.next().unwrap_or_default();
    if argv1 == CODEX_FS_HELPER_ARG1 {
        codex_exec_server::run_fs_helper_main();
    }
    // windows sandbox wrapper / exec helper 同理
}
```

要点：

- `argv0` 决定「我是谁」——`apply_patch`、Linux 沙箱等；`argv1` 决定「我要当哪种辅助进程」——fs helper、exec helper、Windows 沙箱 wrapper 等。
- 这些 re-exec 出来的子程序是**无独立前端、只做一件事**的专用进程，例如把模型产出的 diff 落盘为 `git apply`、在受限环境中跑命令。
- 主流程走不到任何特殊分支时，就落到正常的 `MultitoolCli` 分发（见下）。

### The Multitool CLI Dispatch

`cli` crate 的 `main` 用 clap 定义了一个 **multitool**：顶层 `MultitoolCli` 既接受一组扁平的「交互式选项」（prompt、图片、目录、remote 等），又接受一个可选的子命令。

```rust
struct MultitoolCli {
    #[clap(flatten)]
    pub config_overrides: CliConfigOverrides,
    #[clap(flatten)]
    pub interactive: TuiCli,
    #[clap(subcommand)]
    subcommand: Option<Subcommand>,
}
```

`Subcommand` 枚举里的分支众多，但按「是否进入交互式 agent」可归为两类：

- **进交互式 agent**：无子命令，或 `agents`（会话总览）。两者都走到 `run_interactive_tui`，即拉起 TUI 前端。
- **其它子命令（都是工具/运维/接入）**：`exec`/`review`（非交互式跑模型）、`app-server`（常驻守护）、`mcp`、`plugin`、`sandbox`、`login`/`logout`、`doctor`、`debug`、`responses-api-proxy`、`exec-server`、`stdio-to-uds`、`cloud` 等。

```rust
match subcommand {
    None | Some(Subcommand::Agents(_)) => {
        // 默认 / agents：进入交互式 TUI
        return Ok(Some(launch_tui(interactive, root_remote, root_remote_auth_token_env, arg0_paths)));
    }
    Some(Subcommand::AppServer(app_server_cli)) => {
        // 常驻守护进程
        // transport = Stdio | listen(ws/tcp)
    }
    Some(Subcommand::Exec(mut exec_cli)) => {
        codex_exec::run_main(exec_cli, arg0_paths.clone()).await?;
    }
    // Mcp / Plugin / Sandbox / Login / Debug / ... 各走各的模块
}
```

注意 `interactive` 里有一个 `--remote ws://...|unix://...` 选项：TUI 可以**不本地跑引擎，而是连到一个远程 app-server**，把本地终端当作远程 agent 的「显示器」。这把「前端」与「引擎」的分离彻底坐实了。

### The Engine: codex-core

无论走 TUI 还是 app-server，最终都汇入 `codex-core`（crate 名 `codex-core`）。它是整个 Codex **唯一承载 agent 逻辑的地方**：模型请求、上下文组装、工具执行、沙箱、压缩、回放全在这里。它的对外公开面由两个核心类型领衔：

```rust
pub struct CodexThread {
    pub(crate) session: Arc<Session>,
    pub(crate) io: SessionIo,
    pub(crate) residency_gate: Arc<RwLock<()>>,
    pub(crate) session_source: SessionSource,
    // ...
}

impl CodexThread {
    pub async fn submit(&self, op: Op) -> CodexResult<String> {
        self.io.submit(op).await
    }
    // prewarm / create_child / prepare_child / tool_invocation ...
}
```

注释里这句话点明了它的本质——*「Conduit for the bidirectional stream of messages that compose a thread (formerly called a conversation) in Codex.」* 也就是说：**一条 Thread = 一段双向消息流（用户 `Op` 进、事件 `Op` 出）**，底层包着一个 `Arc<Session>` 和一条 `SessionIo`。

线程怎么来的？由 `ThreadManager` 负责创建并驻留在内存里：

```rust
pub struct NewThread {
    pub thread_id: ThreadId,
    pub thread: Arc<CodexThread>,
    pub session_configured: SessionConfiguredEvent,
}

pub struct ThreadManager {
    state: Arc<ThreadManagerState>,
    // ...
}

impl ThreadManager {
    pub async fn start_thread(&self, options: StartThreadOptions) -> CodexResult<NewThread> {
        // ...
    }
}
```

`ThreadManager` 是「工厂 + 注册表」：`start_thread` 吃一份 `StartThreadOptions`（含 `Config`、动态工具、初始历史、fork 来源等），产出一个 `Arc<CodexThread>` 并把它的 `thread_id` 登记进来，供后续 `submit`、`fork`、`resume` 复用。app-server 里就是这样驱动会话的：

```rust
let codex_core::NewThread { thread, .. } =
    thread_manager.start_thread(codex_core::StartThreadOptions::new(config.clone())).await?;
```

### Two Frontends, One Engine

`codex-core` 之上飘着两个前端，**都只做「把用户/客户端意图翻译成 `Op` 喂给 `CodexThread`，再把流出的 `Op` 渲染/转发」**，自己不含 agent 逻辑。

**TUI（`codex-rs/tui`）**——交互式终端前端。它持有一个 `TurnContext`（每轮上下文）或直接包住 `CodexThread`，把键盘输入、slash 命令、权限确认翻译成 `Op` 提交，再把模型流式输出渲染成聊天界面。源码里随处可见 `AppCommand::OverrideTurnContext { .. }` 与 `AppEvent::CodexOp(Op::...)` 这类「前端命令 ↔ 引擎事件」的对偶。

**App Server（`codex-rs/app-server` + `app-server-protocol`）**——常驻守护进程，把引擎暴露成可供多客户端接入的**远程服务**。它选择传输方式：

```rust
let transport = if stdio {
    codex_app_server::AppServerTransport::Stdio
} else {
    listen   // ws:// 或 tcp 监听
};
```

远程客户端（桌面 App、IDE 插件、Web、移动端）通过 `app-server-protocol` 定义的 JSON-RPC 与之通信；守护进程内部仍然是 `ThreadManager` + `CodexThread`。TUI 也能用 `--remote` 退化成它的纯前端。这就解释了为什么 Codex 既有「一个二进制」的极简发布，又能支撑「桌面 App + CLI + IDE」的多端形态——**引擎一份，驾驶舱按需接**。

### Where the Protocol Lives

`codex-protocol`（crate `codex-protocol`，路径 `codex-rs/protocol`）是横切的**消息与类型层**：它定义了前端与引擎之间、以及 app-server 线格式里流转的语义——`turn_input::TurnInput`、`protocol::EnvironmentConfig`、`mcp_policy`、以及贯穿全文的事件类型 `Op`。`core`、`app-server`、`tui` 都依赖它，所以消息契约只有一份定义、被所有层共享。

### Why This Shape

把上面几点串起来，Codex 之所以长成「壳 + 单二进制 + 单引擎 + 双前端」，是几个约束共同决定的：

- **发布要跨平台且轻**：用 JS 壳按平台拉起原生二进制，避免让用户自己编 Rust；单二进制多重人格又省掉了额外的小工具分发包。
- **能力要被多端复用**：CLI、桌面 App、IDE 都要驱动同一套 agent 逻辑，于是把逻辑压进 `codex-core` 这个库，前端退化为「驾驶舱」。
- **远程接入要成服务**：IDE/桌面需要常驻、可并发、走协议的入口，于是有 app-server 守护进程；TUI 还能反向连它，证明前端与引擎已经解耦。
- **安全边界要独立进程**：沙箱执行、补丁应用被做成 re-exec 出来的专用子程序，让「受限执行」与「主引擎」在进程边界上隔离。

## Subsystem Deep Dives

分层与启动链路已在上节展开；各子系统的独立深挖如下。引擎内部的会话循环见 [Codex 核心会话循环](/docs/CS/AI/Codex/SessionLoop.md)：`submit(Op)` 经 `submission_loop` 分发、`run_turn` 外层循环、`try_run_sampling_request` 流式内循环、工具并发执行与审批门控（oneshot 挂起/解挂）。隔离与审批机制的独立深挖见 [Codex Sandbox](/docs/CS/AI/Codex/Sandbox.md)：跨平台沙箱（bwrap+seccomp+landlock / Seatbelt / MXC）、`network-proxy` 的 MITM+凭证代理、execpolicy 与 session 审批两道正交门控。Agent 协作机制的独立深挖见 [Codex 多 Agent](/docs/CS/AI/Codex/MultiAgent.md)：角色层、spawn 引擎与配置遗传、spawn 拓扑 DAG（agent-graph-store）、消息板通信（channel/thread/post + SSE）；以及 [Codex Code Mode](/docs/CS/AI/Codex/CodeMode.md)：用 JS 在 V8 隔离环境编排工具调用的机制（exec/wait 工具、cell/session/delegate、宿主与运行时）。工具系统的链路式拆解见 [Codex 工具系统](/docs/CS/AI/Codex/Tools.md)：契约层（`ToolDefinition`/`ToolSpec`/`ToolExecutor`）、注册表与路由（`ToolRegistry`/`ToolRouter`，`register_trusted` vs `register_external`）、编排器（审批+沙箱+升级重试、`ToolRuntime` 与 handler/runtime 拆分）、`spec_plan` 工具集装配、自研 apply_patch 模糊匹配算法与 shell-command 解析。记忆与上下文管理的独立深挖见 [Codex 记忆与上下文管理](/docs/CS/AI/Codex/MemoryContext.md)：记忆的两阶段写入流水线（Phase1 抽取 / Phase2 合并智能体 + git 基线）、读取路径经 `ext/memories` 扩展切成带上限的 developer 片段注入、上下文片段模型（`ContextualUserFragment`/`RenderedFragment`/`AnnotatedContent`）、装配入口 `build_initial_context_with_world_state` 与每步 `capture_step_context`、`ContextManager` 快照共享、以及压缩/预算/GUARDIAN 截断的窗口管理。插件体系的独立深挖见 [Codex 插件系统](/docs/CS/AI/Codex/PluginSystem.md)：包级插件（marketplace 安装、manifest 四能力 skills/MCP/hooks/apps、`PluginsManager`+`loader`+`PluginLoadOutcome` 加载流水线、Agent 插件与可发现插件、`plugin-host` 的 V8 UI 插件宿主 ABI 与进程生命周期）；可观测性的独立深挖见 [Codex 可观测性](/docs/CS/AI/Codex/Observability.md)：`otel` crate 的 logs/traces/metrics 三路导出、`OtelProvider` 全局安装与导出过滤、`PolicyExporter` 网络策略约束、W3C trace 上下文、指标字典、会话遥测事件、trace websocket 桥与热重载。持久化与状态的独立深挖见 [Codex 持久化与状态](/docs/CS/AI/Codex/Persistence.md)：rollout JSONL 作为不可变主记录（后台 writer task、append-only、崩溃重开重试、`~/.codex/sessions/YYYY/MM/DD` 布局、压缩）、`state` crate 的 `StateRuntime` 多 SQLite 库（state/logs/goals/memories/queue）异步 backfill 索引、`SessionState` 内存态与 `LocalThreadStore`、以及 `reconstruct_history_from_rollout` 的重放/压缩点界定恢复。认证与模型接入的独立深挖见 [Codex 认证与模型接入](/docs/CS/AI/Codex/AuthAndModels.md)：`login`（AuthManager/OAuth/TokenData/WorkspaceRouting）、`agent-identity`（ed25519+JWT/JWKS）、`workload-identity`（断言兑换）三层认证，加上 `model-provider-info` 注册表、`model-provider`（create_model_provider + auth + workspace routing）与 `models-manager`（catalog/cache/预设），最终在 core 的 `ModelClient`/`ModelClientSession` 收口。远程执行的独立深挖见 [Codex exec-server 与远程执行](/docs/CS/AI/Codex/ExecServer.md)：`codex-exec-server` 独立服务把进程/文件系统/环境/能力发现/HTTP 封装为 JSON-RPC，经 WebSocket/stdio/Noise 三种传输暴露；`EnvironmentManager` 在本地沙箱与远程环境间择一，远端执行经 `ExecServerClient` 以协议方法发到远端或 fs-helper。TUI 与交互的独立深挖见 [Codex TUI 与交互](/docs/CS/AI/Codex/Tui.md)：TUI 实为 app-server 客户端（Embedded/LocalDaemon/Remote 三形态）、`AppServerSession` typed facade、终端层的 EventBroker drop/recreate 交接 stdin 与 FrameRequester 帧合并、已定稿历史直接写终端 scrollback（insert_history）、主循环五路 `tokio::select!`（AppEvent/线程事件/终端事件/多会话 app-server 事件/daemon 重启）、ChatWidget 双 cell 模型与 transcript overlay 缓存、审批 ServerRequest 往返闭环。

## Links

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
2. [codex 二进制入口 cli/src/main.rs](https://github.com/openai/codex/blob/v0.167.0/codex-rs/cli/src/main.rs)
3. [codex-core 线程模型 core/src/codex_thread.rs](https://github.com/openai/codex/blob/v0.167.0/codex-rs/core/src/codex_thread.rs)
4. [arg0 多重人格 arg0/src/lib.rs](https://github.com/openai/codex/blob/v0.167.0/codex-rs/arg0/src/lib.rs)
5. [Codex CLI 文档](https://developers.openai.com/codex/cli/)
