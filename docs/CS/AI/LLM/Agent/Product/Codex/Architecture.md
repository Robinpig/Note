> 版本基线：核实于 2026-10-16，对应 commit `6b991972c5b5`（`main`，2026-10-15）。本主题早期的版本记录（commit `633ab199cf`）已大幅过期——Rust 工作区的 crate 从十几个扩展到约 110 个，新增 skills / hooks / plugin / memories / multi-agent / code-mode / cloud-tasks 整层能力。

## Introduction

Codex 的开源仓库**不含模型权重**，公开的是三块集成面：`codex-cli`（Node.js 包装层）、`codex-rs`（Rust 工作区，Harness 主体）、`sdk/`（Python / TypeScript SDK）。理解这个仓库的入口不是某一个 `main.rs`，而是两张地图：**crate 分工图**（哪个 crate 负责什么）与 **Session-Turn-Item 数据模型**（一次任务在协议层由哪些对象构成）。

Harness 的通用概念（三层边界 Host/Harness/Model、Thread/Turn/Step/Item 四级粒度、四层安全模型）已提炼到 [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)，本篇只记 Codex 仓库本身的落地结构。

## Repository Layout

```
codex/
├── codex-cli/          # Node.js 包装层（npm 分发入口）
├── codex-rs/           # Rust 工作区（Harness 主体，约 110 个 crate）
└── sdk/                # Python / TypeScript SDK
```

分发形态有三条互不依赖的安装路径（curl 安装脚本 / npm / Homebrew），加上 IDE 扩展、桌面应用（`codex app`）与云端 Codex Web——**它们共享同一个 Rust 内核**，差异只在 Host 层。这正是 Harness 作为集成层的直接证据：协议不变，前端可以任意增加。

## Crate Map

`codex-rs/` 下的 crate 按职责可以分成十组。记住分组比记住单个 crate 名字更重要——新增能力几乎总是以「新组」而非「改旧 crate」的形式出现：

| 分组 | 代表 crate | 职责 |
| :--- | :--- | :--- |
| 内核 | `core`、`core-api`、`protocol`、`config`、`state` | 会话、Turn、Agent loop、工具、协议类型、配置解析 |
| 执行 | `exec`、`exec-server`、`shell-command`、`apply-patch`、`process-hardening` | 非交互模式、执行服务（可代理到远端）、补丁应用 |
| 沙箱 | `sandboxing`、`linux-sandbox`、`bwrap`、`windows-sandbox-rs`、`windows-sandbox-service`、`mxc-sandbox`、`network-proxy` | 三平台沙箱后端与网络策略执行 |
| 工具 | `tools`、`codex-mcp`、`rmcp-client`、`file-search` | 工具名与定义、MCP 客户端、文件检索 |
| 控制面 | `app-server`、`app-server-protocol`、`app-server-client`、`app-server-daemon`、`app-server-transport`、`uds`、`stdio-to-uds` | JSON-RPC 服务、协议定义、守护进程与传输 |
| Agent 协作 | `agent-graph-store`、`agent-identity`、`agent-message-board-client`、`agent-roles` | 多 Agent 的角色、消息板、图存储与身份 |
| 扩展 | `plugin`、`core-plugins`、`core-plugin-common`、`skills`、`hooks`、`connectors`、`ext` | 插件清单、Skill 加载、Hooks、连接器 |
| 记忆 | `memories`（read / write 两个子 crate）、`history` | 跨会话记忆的读写两侧与历史条目类型 |
| 持久化 | `rollout`、`thread-store`、`attachment-store` | 会话文件、Thread 存储、附件 |
| 云与远程 | `cloud-tasks`、`cloud-client`、`cloud-config`、`code-mode`、`code-mode-host`、`code-mode-protocol`、`code-mode-runtime`、`realtime-webrtc`、`voice-host` | 云端任务、Code Mode 远程会话、实时语音 |
| 界面与可观测 | `tui`、`cli`、`arg0`、`otel`、`analytics`、`diagnostics` | 终端 UI、入口包装、遥测与诊断 |

注意两个容易混淆的点：

- **`core` 既是 crate 又是模块森林**：`core/src/session/`、`core/src/tools/`、`core/src/agent/` 等目录本身就是最大的源码体量所在，独立 crate 往往只是把其中的某类能力抽出来共享（如 `protocol` 抽出协议类型、`config` 抽出配置层）。
- **`tools/` crate 与 `core/src/tools/` 模块并存**：前者拥有 `ToolName` 这类跨 crate 共享的工具标识（`parallel.rs` 等处引用 `codex_tools::ToolName`），后者是路由器与并发执行的具体实现。

## Session, Turn, Item

协议层的数据模型在 `protocol` crate（`SessionSource`、`TurnInput`、`ResponseItem` 一族）与 `app-server-protocol`（v1/v2 两套 JSON-RPC 消息）里落地。四粒度的职责划分：

| 粒度 | 协议对象 | 持久化落点 |
| :--- | :--- | :--- |
| Thread | `SessionSource` 标注来源（Cli / VSCode / Exec / Mcp / Internal / SubAgent…） | `thread-store` + Rollout 文件 |
| Turn | `TurnContext`（长期身份、环境快照、输出约束） | Rollout 文件内一条 Turn 记录 |
| Step | `StepContext`（一次采样前的不可变设置快照） | 不单独持久化，随 Item 事件重建 |
| Item | `ResponseItem`（一次输入、一条消息、一次工具结果） | Rollout JSONL 的 `RolloutLine` |

**UI 订阅的是 Item 事件流，而不是自己保存一份状态**——这是同一个内核能驱动 CLI、TUI、IDE 与 app-server 的前提，细节见 [Turn](/docs/CS/AI/LLM/Agent/Product/Codex/Turn.md)。

## Core Symbols

读源码前先记七个符号，它们分别对应「一个任务怎么跑起来」这条链上的关键节点：

| 符号 | 位置 | 回答的问题 |
| :--- | :--- | :--- |
| `run_turn` | `core/src/session/turn.rs:166` | 采样主循环长什么样 |
| `StepContext` | `core/src/session/step_context.rs` | 决策与执行如何看到同一套设置 |
| `ToolRouter` | `core/src/tools/router.rs` | 模型可见名如何映射到真实执行器 |
| `ToolCallRuntime` | `core/src/tools/parallel.rs:46` | 并发执行与取消如何被闸门控制 |
| `request_command_approval` | `core/src/session/mod.rs:2923` | 人工审批如何卡住真实执行 |
| `CancellationToken` | `tokio_util` | 停止信号如何沿调用链传播 |
| `RolloutItem` | `rollout` crate | 恢复与审计的事实从哪来 |
| `app-server` | `app-server` crate | 外部如何驱动这个内核 |

## Source Reading Path

按「先协议、再循环、再边界」的顺序读，比按目录字母序读高效得多：

```
app-server-protocol/src/protocol/v2
  ↓ 先建立消息与事件的词汇表（initialize / thread / turn / item 各族）
core/src/session/turn_input.rs::start_or_steer
  ↓ 输入如何启动或转向一个 Turn
core/src/session/turn.rs::run_turn
  ↓ 主循环如何反复采样、何时继续、何时收口
core/src/tools/router.rs + parallel.rs + spec_plan.rs
  ↓ 工具计划、路由与并发闸门
core/src/session/mod.rs::request_command_approval
  ↓ 人工审批如何异步等待并 fail closed
sandboxing/src/lib.rs + linux-sandbox/src/lib.rs
  ↓ 沙箱策略如何落到具体平台机制
rollout/src/lib.rs
  ↓ 会话如何落盘、如何恢复
```

早期（`633ab199cf`）阅读路径里的 `tasks/regular.rs`、`tools/spec_plan.rs`、`session/mod.rs` 仍然有效，但主循环周边已长出压缩前置、hooks 落账、MCP 启动需求等新阶段，见 [Turn](/docs/CS/AI/LLM/Agent/Product/Codex/Turn.md)。

## Links

- [Codex 主入口](/docs/CS/AI/LLM/Agent/Product/Codex/Codex.md)
- [Turn：任务生命周期](/docs/CS/AI/LLM/Agent/Product/Codex/Turn.md) / [Tools：工具系统](/docs/CS/AI/LLM/Agent/Product/Codex/Tools.md)
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) — 通用 Harness 概念与「工程实例：Codex」

## References

- [openai/codex](https://github.com/openai/codex)
