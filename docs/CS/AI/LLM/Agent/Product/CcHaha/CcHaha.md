## Introduction

cc-haha 是 [NanmiCoder/cc-haha](https://github.com/NanmiCoder/cc-haha) 开源（MIT）的**本地优先跨平台桌面 AI Agent 工作台**，常被称作「桌面版 Claude Code」。它的内核是一个从 Claude Code 源码修复而来的 CLI 引擎 `claude-haha`，桌面应用（Electron）则是包裹这层引擎的图形外壳：把会话、项目、权限、Diff、Computer Use、远程访问与模型提供商配置集中到一个 GUI 里。

> [!WARNING]
> cc-haha 基于泄露的 Claude Code 源码修复而来，其 README 自陈原始源码版权归 Anthropic 所有、仅供学习与研究用途。它**非 Anthropic 官方产品**，存在下架与版权追究风险，**不推荐用于生产环境或企业合规场景**。本笔记仅作技术架构记录。

本家族为「主枢纽 + 专题分册」结构，事实基线以 GitHub `main` 分支最新 commit 为准（仓库活跃维护中，最近 push 2026-10-17）。本家族笔记已对照源码核实关键事实：引擎以**子进程 + NDJSON 管道**被桌面驱动、Agent Teams 桌面 UI 是**引擎快照的实时可视化器**但引擎侧 **Dynamic Workflow 是真实的「模型写 VM 编排脚本」机制**、Computer Use **四层架构 + 原生 fail-closed 授权**、权限 **5 档**、MCP / Skill 市场的**本地服务端后端（ClawHub + SkillHub 双源）**等。底层 agentic loop / hooks / memory / subagents / skills / MCP 机制与 [Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md) 同源——这些机制不在本家族重写，统一交叉链到 ClaudeCode 家族，本笔记只覆盖 cc-haha 的**桌面外壳与差异化能力**。

## Installation

两种获取方式：

- **桌面安装包**：从 GitHub Releases 下载 macOS / Windows / Linux 安装包。未签名安装包会被系统拦截，需按官方安装指南放行（「Run anyway」）。
- **从源码启动 CLI**（用于调试底层引擎或本地开发）：

```bash
git clone https://github.com/NanmiCoder/cc-haha
cd cc-haha
bun install
cp .env.example .env
./bin/claude-haha
```

桌面端首次启动后，在 Settings 配置模型供应商、API Key 与默认模型，选择项目目录与 Git 分支即可开始使用多会话工作台。

## Desktop Feature Map

完整功能地图见官方 [Desktop](https://cchaha.ai/en/desktop) 文档。日常高频能力：

| 能力 | 说明 |
| :--- | :--- |
| 多会话工作台 | 标签页、项目切换、终端入口、会话历史集中管理，Cmd+K 跨所有会话全局搜索 |
| Branch / Worktree 启动 | 选分支并决定用当前工作树或隔离 Worktree |
| 文件级 Diff review | 右侧面板列出本轮改动，逐文件语法高亮 diff，可整轮 undo |
| 内置浏览器预览 | WebContentsView + 沙箱 partition，带 cookie / 登录态 |
| 5 档权限 | default / acceptEdits / auto / plan / bypassPermissions，危险命令 / 工具调用 / 追问都在 GUI 审批 |
| 可视化 MCP / SubAgent 管理器 | GUI 增删 MCP 服务器（stdio / http / sse，三档 scope）；GUI 创建调优 SubAgent |
| Skill 市场 | ClawHub / SkillHub（双源，均已核实）发现、预览、安装第三方 skill，安装前展示安全报告 |
| 6 主题 | white / paper / warm classic / celadon / ink night / ink blue，可跟随系统明暗 |
| Computer Use | 截屏 / 点击 / 输入 / 控制桌面应用（需授权） |
| Agent Teams | 桌面 UI 是引擎 agent-teams 快照的实时可视化器（成员 / 任务 / 通信 feed / 依赖泳道画布 + 回放）；引擎侧另有真实的 **Dynamic Workflow**（模型写 VM 编排脚本派生 subagent） |
| H5 远控 + IM | 手机浏览器扫码继续会话；接入微信 / 飞书 / 钉钉 / Telegram / WhatsApp / QQ / Slack / WeCom |
| 计划任务 | 8 步向导 + 自研 5 字段 cron，headless 执行并留运行日志 |
| 桌面宠物 | 常驻桌面的窗体宠物，跟随 agent 活动切换动作与气泡点评（Claude Code / OpenCode 均无） |

## 专题分册

主链路是 [Architecture](/docs/CS/AI/LLM/Agent/Product/CcHaha/Architecture.md)：Electron 外壳与 `claude-haha` CLI 内核的边界、桌面如何 spawn 引擎子进程走 NDJSON 管道、与终端 Claude Code 的差异。其余专题分册（按主题）：

- **[Models](/docs/CS/AI/LLM/Agent/Product/CcHaha/Models.md)**——BYO 模型：Claude / ChatGPT / Grok 账号登录、DeepSeek / Kimi / Zhipu GLM 预设、本地 LM Studio / Ollama，以及图像生成。
- **[Permission](/docs/CS/AI/LLM/Agent/Product/CcHaha/Permission.md)**——5 档权限模式（default / acceptEdits / auto / plan / bypassPermissions）与 GUI 审批流。
- **[AgentTeams](/docs/CS/AI/LLM/Agent/Product/CcHaha/AgentTeams.md)**——可视化多 Agent 协作 workbench + 引擎侧真实的 Dynamic Workflow（VM 编排，含硬上限常量）。
- **[ComputerUse](/docs/CS/AI/LLM/Agent/Product/CcHaha/ComputerUse.md)**——四层架构（Python Bridge + 原生 cu-helper fail-closed 授权）、截屏 / 点击 / 输入 / 控制桌面应用。
- **[Integrations](/docs/CS/AI/LLM/Agent/Product/CcHaha/Integrations.md)**——IM 整合（8 平台 + 公共 ws-bridge）/ H5 远控 / 计划任务 / 桌面宠物总览。
- **[MCP_Skills](/docs/CS/AI/LLM/Agent/Product/CcHaha/MCP_Skills.md)**——可视化 MCP 管理器（stdio / http / sse + local / project / user）与 Skill 市场（ClawHub + SkillHub 双源）。
- **[ScheduledTasks](/docs/CS/AI/LLM/Agent/Product/CcHaha/ScheduledTasks.md)**——计划任务完整引擎：两套独立调度器、自研 5 字段 cron、jitter、持久化、headless 执行、跨会话锁、7 天自动过期。
- **[RemoteAccess](/docs/CS/AI/LLM/Agent/Product/CcHaha/RemoteAccess.md)**——H5 远控令牌 / 配对 / 网络策略 / keepalive / 权限桥，并区分 cloud CCR 桥与 ngrok 隧道。
- **[Pets](/docs/CS/AI/LLM/Agent/Product/CcHaha/Pets.md)**——桌面宠物：内置 4 只、DOM/CSS spritesheet 渲染、透明置顶窗口、2s 轮询会话集成、自定义宠物校验。
- **[REPL](/docs/CS/AI/LLM/Agent/Product/CcHaha/REPL.md)**——统一命令队列：模块级单例、优先级 now>next>later、turn 间隙 drain、与计划任务 / 远控的注入咬合。
- **[GenerativeTools](/docs/CS/AI/LLM/Agent/Product/CcHaha/GenerativeTools.md)**——自有生成工具：ImageGen / ImageEdit（provider 驱动 schema，复用 OpenAI / Grok OAuth 令牌）、StructuredOutput（仅非交互会话 + Ajv 校验），以及两个不可用占位（tungsten 手写禁用、SnipTool 为 stub）。
- **[AssistantMode](/docs/CS/AI/LLM/Agent/Product/CcHaha/AssistantMode.md)**——assistant（Kairos）模式与 agent 主动消息投递：Brief 工具的 entitlement / activation 双重判定、六种 opt-in 来源，附全部自有工具在公开版的可用性对照。

## Common Issues

- **安装包被系统拦截**：未签名，按官方安装指南选择「Run anyway」放行。
- **连不上模型**：检查 Settings 里供应商 / API Key / 默认模型是否配置；本地模型确认 LM Studio / Ollama 已启动并暴露端口。
- **内核机制问题**（agentic loop / hooks / memory / subagents）：这些与 Claude Code 同源，先查 [ClaudeCode 家族](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md) 对应分册。
- **找不到上下文检查工具**：`CtxInspectTool`（`src/tools/CtxInspectTool/CtxInspectTool.ts`）在公开版是 `@generated stub`（`scan-missing-imports` 自动生成的 ant-internal `feature()` 占位，DCE 后不执行）——cc-haha 无特有上下文工具。记忆仅存类型契约 `utils/memory/types.ts`（`User / Project / Local / Managed / AutoMem` + `feature('TEAMMEM')` gated 的 `TeamMem`），实现同源 Claude Code。

## Links

- [Architecture](/docs/CS/AI/LLM/Agent/Product/CcHaha/Architecture.md)
- [Models](/docs/CS/AI/LLM/Agent/Product/CcHaha/Models.md)
- [Permission](/docs/CS/AI/LLM/Agent/Product/CcHaha/Permission.md)
- [AgentTeams](/docs/CS/AI/LLM/Agent/Product/CcHaha/AgentTeams.md)
- [ComputerUse](/docs/CS/AI/LLM/Agent/Product/CcHaha/ComputerUse.md)
- [Integrations](/docs/CS/AI/LLM/Agent/Product/CcHaha/Integrations.md)
- [三向对照：Claude Code / OpenCode / cc-haha](/docs/CS/AI/LLM/Agent/Product/CcHaha/Comparison.md)
- [REPL](/docs/CS/AI/LLM/Agent/Product/CcHaha/REPL.md)
- [GenerativeTools](/docs/CS/AI/LLM/Agent/Product/CcHaha/GenerativeTools.md)
- [AssistantMode](/docs/CS/AI/LLM/Agent/Product/CcHaha/AssistantMode.md)

## References

- [cc-haha 官网](https://cchaha.ai/)
- [NanmiCoder/cc-haha GitHub](https://github.com/NanmiCoder/cc-haha)
- [cc-haha 文档：What cc-haha is](https://cchaha.ai/en/start)
