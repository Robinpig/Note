> 版本基线：核实于 2026-10-16，对应 commit `6b991972c5b5`（`main`，2026-10-15）。本文早期的版本记录（commit `633ab199cf`）已大幅过期：Rust 工作区从十几个 crate 扩到约 110 个，并长出 Skills / Hooks / Plugins / Memories / Multi-Agent / Code Mode / Cloud Tasks 整层能力。各专题页的细节均以该基线核实。

## Introduction

OpenAI Codex 是一个 AI 编程代理（AI Coding Agent），目标不是帮你补全代码，而是直接参与并完成整个开发任务——写代码、修 Bug、跑测试、提 Pull Request。它有多种形态：本地 CLI、IDE 扩展（VS Code / Cursor / Windsurf）、桌面应用（`codex app`）与云端 Codex Web，但**它们共享同一个 Rust 实现的内核**——这正是它作为 Harness 工程样本的价值：协议不变，前端可以任意增加。

Harness 的通用概念（三层边界 Host/Harness/Model、Thread/Turn/Step/Item 四级粒度、四层安全、业务系统接入要点）已提炼到 [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) 笔记的「工程实例：Codex」一节。本篇是 Codex 的**总入口**：安装、总体结构与八个专题页的导览；源码级实现细节在 `Codex/` 子目录的各分册。

开源仓库不含模型权重，只公开 CLI、核心运行时、app-server、SDK 等集成面。

## Installation

```shell
# 官方安装脚本（默认从 releases.openai.com/codex 下载，失败回退 GitHub Releases）
curl -fsSL https://chatgpt.com/codex/install.sh | sh

# 包管理器
npm install -g @openai/codex
brew install --cask codex
```

- 推荐 **Sign in with ChatGPT** 登录（Plus / Pro / Business / Edu / Enterprise 套餐内含额度）；API key 需要额外配置
- 认证凭据落在 `~/.codex/`（`CODEX_HOME`）下，默认 `auth.json`，也可配置系统 keyring 后端
- 强制走 GitHub Releases：`CODEX_INSTALLER_USE_RELEASES_OPENAI_COM=false curl -fsSL https://chatgpt.com/codex/install.sh | sh`

## Architecture at A Glance

仓库三块：`codex-cli`（Node.js 包装层）、`codex-rs`（Rust 工作区，Harness 主体，约 110 个 crate）、`sdk/`（Python / TypeScript SDK）。crate 按职责分十组——内核（core/protocol/config）、执行（exec/exec-server）、沙箱（sandboxing/linux-sandbox/windows-sandbox-*）、工具（tools/codex-mcp）、控制面（app-server 一族）、Agent 协作（agent-roles/graph-store/message-board）、扩展（plugin/skills/hooks/connectors）、记忆（memories）、持久化（rollout/thread-store）、云与远程（cloud-tasks/code-mode/realtime-webrtc）。

一次任务的主链路一句话：**`start_or_steer` 接单 → `run_turn` 反复采样 → `ToolCallRuntime` 并发执行工具 → 审批按需挂起（fail closed）→ Item 事件流推给 UI → Rollout 落盘可恢复**。完整的 crate 地图、Session-Turn-Item 模型与源码阅读路径见 [Architecture](/docs/CS/AI/LLM/Agent/Product/Codex/Architecture.md)。

## How to Read the Subsystem Notes

八个专题页按「**结构 → 主循环 → 边界 → 控制面 → 扩展 → 协作**」组织。第一次接触建议从 [Turn](/docs/CS/AI/LLM/Agent/Product/Codex/Turn.md) 入手——它是所有其他页面的汇流点；只关心安全就看 [Sandbox](/docs/CS/AI/LLM/Agent/Product/Codex/Sandbox.md) 与 [Approval](/docs/CS/AI/LLM/Agent/Product/Codex/Approval.md) 两页。

**结构与主循环**。[Architecture](/docs/CS/AI/LLM/Agent/Product/Codex/Architecture.md) 是地图页：crate 十组分工、Session/Turn/Item 的协议落点、七个必记符号与一条源码阅读路径。[Turn](/docs/CS/AI/LLM/Agent/Product/Codex/Turn.md) 走完一个 Turn 的五问——输入怎么进来（`start_or_steer` 三模式）、循环怎么转（`run_turn` 与 `needs_follow_up`）、事件怎么出去（UI 订阅事实流而非自存状态）、中途怎么改（注入 / 挂起 / 取消传播）、结果怎么留（Rollout JSONL 与恢复语义）。这一页还覆盖 2026 年新长出的循环周边机制：**采样前主动压缩**（新输入落账前预估阈值）、**hooks 落账**（异步 hook 结果在下轮开始前清账）、**MCP 启动需求跨重启保留**。

**两条边界**。[Tools](/docs/CS/AI/LLM/Agent/Product/Codex/Tools.md) 讲工具系统：`ToolRouter` 的双表映射、`ToolCallRuntime` 用一把 `RwLock<()>` 单元锁做并发闸门（并行工具读锁、独占工具写锁）、四层调用形态、`executed_tool_calls` 调用记录与网络审批上下文。[Approval](/docs/CS/AI/LLM/Agent/Product/Codex/Approval.md) 讲人的层：`request_command_approval` 的 oneshot 异步等待与 `unwrap_or(Abort)` 的 fail closed、命令与补丁双通道、`ReviewDecision` 的会话级放行与规则修正案、`AskForApproval` 四态（注意 `untrusted` 已从用户配置移除、`on-failure` 是 `on-request` 的别名）、`Granular` 五类开关、可路由给子 agent 的 `auto_review` 与目录信任级 `TrustLevel`。[Sandbox](/docs/CS/AI/LLM/Agent/Product/Codex/Sandbox.md) 讲系统的层：三模式（默认 `read-only`）、三平台后端（Seatbelt / seccomp+bubblewrap / 受限令牌）、网络策略（托管 MITM CA、按 host 的审批修正案）与违规记录。

**控制面**。[AppServer](/docs/CS/AI/LLM/Agent/Product/Codex/AppServer.md) 讲外部怎么驱动内核：v1/v2 双轨协议与代码生成（TS 类型与协议同源）、生命周期（initialize → thread → turn → item 事件）、三种部署（进程内 / 守护进程 / 客户端库）、配置热刷新与 RPC 准入闸门，以及 `codex exec` / SDK / app-server 三条接入路径的取舍。

**扩展与协作**。[Extensions](/docs/CS/AI/LLM/Agent/Product/Codex/Extensions.md) 覆盖五套扩展机制：MCP（客户端到工具暴露的全链）、Skills（目录 token 预算默认 2%、超限静默省略）、Plugins（清单可带 skills/MCP/apps/hooks 与市场元数据）、Hooks（三态结果与跨 Turn 异步语义）、Connectors。[MultiAgent](/docs/CS/AI/LLM/Agent/Product/Codex/MultiAgent.md) 覆盖多 Agent V2（角色指令按会话来源分流、三档触发模式、权限不天然继承）、Memories 两阶段固化（读/写两侧、14 天扩展保留）、Code Mode 远程会话与 Cloud Tasks 云端任务。

## Common Issues

| 问题 | 回答 |
| :--- | :--- | :--- |
| 这是不是 ReAct？ | 不是。ReAct 是模式，Harness 是完整生产运行时 |
| 会改变模型能力吗？ | 不改权重，但影响表现（尤其长任务的上下文正确性与恢复能力） |
| 开源仓库含模型吗？ | 不含，只有 CLI、运行时、app-server、SDK |
| 核心入口在哪？ | 理解运行看 `run_turn`，理解控制看 app-server，理解安全看 `ToolRouter` + `request_command_approval` |
| 和 Claude Code 比沙箱谁更保守？ | Codex 默认 `read-only` + 审批 fail closed；Claude Code 沙箱默认关闭。对照见 [Permission](/docs/CS/AI/LLM/Agent/Theory/Permission.md) |
| 子 Agent 会继承父会话权限吗？ | 不。独立会话、独立 `child_config`，见 [MultiAgent](/docs/CS/AI/LLM/Agent/Product/Codex/MultiAgent.md) |
| skill 装多了会怎样？ | description 每轮都进上下文；可用目录默认按上下文 2% 设预算，超限静默省略，见 [Extensions](/docs/CS/AI/LLM/Agent/Product/Codex/Extensions.md) |

## Links

- [Architecture](/docs/CS/AI/LLM/Agent/Product/Codex/Architecture.md) / [Turn](/docs/CS/AI/LLM/Agent/Product/Codex/Turn.md) / [Tools](/docs/CS/AI/LLM/Agent/Product/Codex/Tools.md) / [Approval](/docs/CS/AI/LLM/Agent/Product/Codex/Approval.md)
- [Sandbox](/docs/CS/AI/LLM/Agent/Product/Codex/Sandbox.md) / [AppServer](/docs/CS/AI/LLM/Agent/Product/Codex/AppServer.md) / [Extensions](/docs/CS/AI/LLM/Agent/Product/Codex/Extensions.md) / [MultiAgent](/docs/CS/AI/LLM/Agent/Product/Codex/MultiAgent.md)
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) — 通用 Harness 概念，含「工程实例：Codex」一节
- [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) — Agent 四构成（Loop/Tools/Memory/Harness）
- [ClaudeCode](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md) / [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md) / [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md) / [DSH](/docs/CS/AI/LLM/Agent/Product/DSH/DSH.md) — 同层产品对照
- [MCP](/docs/CS/AI/LLM/Protocol/MCP.md) / [Skill](/docs/CS/AI/LLM/Agent/Theory/Skill.md) / [Permission](/docs/CS/AI/LLM/Agent/Theory/Permission.md) / [Compaction](/docs/CS/AI/LLM/Agent/Theory/Compaction.md)

## References

- [openai/codex](https://github.com/openai/codex)
- [Codex Documentation](https://developers.openai.com/codex)
- [万字长文 | 深度解读 Codex Harness 源码](https://mp.weixin.qq.com/s/xa2xrK-LyM5Ktow2hq1vWQ)
