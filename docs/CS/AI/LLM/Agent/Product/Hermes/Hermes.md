## Introduction

Hermes Agent（"The agent that grows with you"）是 **Nous Research 开源、MIT 许可的自进化个人 AI agent**：同一套 agent core 跑在 CLI、TUI、消息网关（Telegram / Discord / Slack 等约 27 个平台）、Electron 桌面端上；它**跨会话持续沉淀记忆与 Skill**，用任意模型（Nous Portal / OpenRouter / OpenAI / Anthropic / 自托管 endpoint 等 40+ 个 model-provider 插件），并在本地硬件或云端 24/7 运行。

> 事实基线：本文为 **main 分支 @ 2026-10-17 的源码剖析**（仓库 `NousResearch/hermes-agent`，创建于 2025-07-22）。`pyproject.toml` 的 `version` 字段是占位 `0.0.0`——版本由独立的 config schema 版本管理，结论全部来自源码与仓库各级 `AGENTS.md`。GitHub API 同日显示约 **25.4 万 stars / 5.5 万 forks**（数值异常高，可能反映极强的社区热度，或承接了 OpenClaw 生态的动量；`hermes claw migrate` 命令可一键导入 OpenClaw 的设置/记忆/Skill/密钥，见 [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md)）。

它和本库 [Practice/Hermes](/docs/CS/AI/LLM/Agent/Practice/Hermes.md) 是同一对象的两面：那篇把它当 **Self-Evolving 的落地标本**（三层记忆、后台复盘、自主建 Skill），本家族则从**工程实现**角度做源码级拆解。两条不变式贯穿全部设计：

- **每会话 prompt 缓存神圣不可侵犯**——会话期间不改历史上下文、不换 toolset、不重载记忆、不重建系统提示；唯一允许的上下文变更是压缩。
- **核心窄腰，能力在边缘**——每个核心工具都会随每次 API 调用发出，所以新能力应走 CLI 命令 + Skill、service-gated tool 或插件，而非塞进 core。

## Installation

一行安装（Linux / macOS / WSL2）：

```bash
curl -fsSL https://hermes-agent.nousresearch.com/install.sh | bash
```

Windows（原生 PowerShell，无需 WSL）：

```powershell
iex (irm https://hermes-agent.nousresearch.com/install.ps1)
```

Android / Termux 走签名 APT 仓库（`stable` + `canary` 双通道，含 Python / Node.js / TUI）。安装器把 Python 3.14、Node.js、ripgrep、FFmpeg 与依赖托管给内置的 **PM**（基于 `uv` 的包/环境管理器）统一管理；Git 缺失时 staging 经校验的 Git for Windows 到 Hermes 工具目录，不替换系统 Git。装完 `source ~/.bashrc && hermes` 即可。

## Common Commands

| 命令 | 作用 |
| :--- | :--- |
| `hermes` | 启动交互式 TUI（多行编辑、slash 补全、对话历史、中断重定向、流式工具输出） |
| `hermes model` | 切换 LLM provider / model，无代码改动、无锁定 |
| `hermes tools` | 配置启用的 toolset（curses 交互） |
| `hermes config set/get <NAME>` | 读写 `config.yaml` / `.env` 中的配置项 |
| `hermes gateway` | 启动消息网关（`gateway setup` + `gateway start`），从 Telegram / Discord / Slack / WhatsApp / Signal / Email 等对话 |
| `hermes setup` | 全量配置向导（含从 OpenClaw 迁移检测） |
| `hermes claw migrate` | 从 OpenClaw 导入设置 / 记忆 / Skill / API 密钥（支持 `--dry-run` / `--preset`） |
| `hermes update` | 事务化升级（plan → snapshot → apply → restart → verify → report） |
| `hermes doctor` | 诊断安装与配置问题 |

CLI 与网关共享大量 slash 命令（`/new`、`/model`、`/personality`、`/retry`、`/compress`、`/skills`、`/stop`、`/usage` 等）；`/model [provider:model]`、`/compress`、`/usage` 在两个界面通用。

## The Nine Companion Volumes

主链路是 [Architecture](/docs/CS/AI/LLM/Agent/Product/Hermes/Architecture.md)：三层骨架（入口层 / 核心层 / 后端层）+ facade-siblings 模式 + 两条不变式，四套表面（CLI / TUI / 网关 / 桌面端）共享同一 core。围绕它展开八个专题：

- **[AgentLoop](/docs/CS/AI/LLM/Agent/Product/Hermes/AgentLoop.md)**——`AIAgent` facade 与 `conversation_loop`；turn 被拆成 34 个 `turn_*.py` 阶段文件；同步循环、`max_iterations=500`、OpenAI 消息格式、两条消息流不变式（字节稳定的 system prompt / 严格角色交替）、压缩双层级（网关 85% + agent 50%）、模型/aux 解析与 side-LLM 路由。
- **[Tools](/docs/CS/AI/LLM/Agent/Product/Hermes/Tools.md)**——`registry` 导入期自发现、精确 28 个 toolset（按能力分组表）、6 种终端后端（local / docker / ssh / modal / daytona / singularity，README 另称含 Vercel Sandbox 共 7）、browser（CDP / cloud）、MCP 客户端、TTS、delegation 子代理（默认并发 10、最大深度 1（扁平；2 才启用 orchestrator→leaf））、approval 与「能力属于会话而非进程」原则。
- **[Skills](/docs/CS/AI/LLM/Agent/Product/Hermes/Skills.md)**——两套 surface（`skills/` 内置 13 类 + `optional-skills/` 23 类，默认不激活）；`SKILL.md` frontmatter 兼容 agentskills.io 开放标准；作者规范（description ≤ 60 字）；curator 生命周期（`agent/curator.py` 后台维护、只归档不删除、pinned 豁免），即自进化闭环的 Skill 侧。
- **[Memory](/docs/CS/AI/LLM/Agent/Product/Hermes/Memory.md)**——三层记忆；持久化 memory provider 插件（含 Honcho 辩证式用户建模）；`state.db` 的 SQLite **FTS5 全文检索**（自带 CJK 分词原生扩展 `native/fts5_cjk`）；`hermes_state_*.py` 的 SessionDB 家族；secret scope 与多 profile 隔离。
- **[Gateway](/docs/CS/AI/LLM/Agent/Product/Hermes/Gateway.md)**——单一网关进程接约 27 个平台适配器 + `api_server`（OpenAI 兼容 `/v1` 路由）+ webhook + A2A；双消息守卫、流式投递契约、`/login`（仅配对 DM）、profile scope 与 token 锁、multiplex 多 profile 同进程服务。
- **[Evolve](/docs/CS/AI/LLM/Agent/Product/Hermes/Evolve.md)**——自进化闭环（Hermes 的灵魂）：每轮后的 **background review**（fork 复盘）、**curator** 的 active/stale/archived 状态机（7 天周期、只归档不删、pinned 豁免）、**`/learn`** 把任意来源蒸馏成 Skill（8 段 authoring 标准 + book-to-skill 布局）、**learning graph** 桌面学习可视化、**periodic scheduler** 全进程单一定时器、**skill bundles** 多 Skill 别名。
- **[Extensions](/docs/CS/AI/LLM/Agent/Product/Hermes/Extensions.md)**——插件种类（general / memory / model-provider / context-engine / image-gen / platform）与「插件不碰 core」铁律；`plugin-catalog/` 646 个社区插件；42 个 model-provider、65 个 optional-mcp；`cron`（含 kanban 多 agent 工作队列）与 context files。
- **[Infrastructure](/docs/CS/AI/LLM/Agent/Product/Hermes/Infrastructure.md)**——差异化硬基建：`native/fts5_cjk`（C 写 FTS5 扩展，unicode61 + CJK bigram，自带 sqlite 头）、`pm`（uv 系包管理器 + 14 天 release-age 护栏）、`docker/`（s6-rc 监管 + tini + 多层 entrypoint）、`acp_adapter/`（ACP 协议适配层）。

## Positioning and Boundary

与同族产品对照，Hermes 的差异化是 **local-first、model-agnostic、跨会话持久进化**：

- 对比 **[OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md)**：两者都走本地优先的个人助手网关，Hermes 在记忆/Skill 自进化与多模型广度上走得更远（42 provider vs OpenClaw 以少量原生平台为主），并显式提供 OpenClaw 迁移路径。
- 对比 **[Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md) / [Codex](/docs/CS/AI/LLM/Agent/Product/Codex/Codex.md)**：后两者绑定单一模型厂商、重在工具闭环与执行安全；Hermes 不绑厂商，重在跨会话的记忆与 Skill 沉淀，且以「可靠设计」为卖点——Nous Research 人工筛选并压测随附的每项 Skill/工具/插件，让 30B 级本地模型也能开箱即用。
- 对比 **[DSH](/docs/CS/AI/LLM/Agent/Product/DSH/DSH.md)**：DSH 哲学最激进（一切皆插件、无特权内核）；Hermes 则是「窄腰核心 + 边缘插件」，core 刻意小、扩展走插件/Skill/MCP。

它属于 [Self-Evolving](/docs/CS/AI/LLM/Agent/Practice/Self-Evolving.md) 的「上下文 / 记忆进化 + Harness 级轻量结构进化」完整落地：Skill 创建与 patch 是 Harness 层轻量结构进化，**不更新权重，不属于参数进化**。可靠 Evolve Loop 仍需治理（成功率/成本/人工反馈/回归测试），见 Practice 篇。

## Links

- [Architecture](/docs/CS/AI/LLM/Agent/Product/Hermes/Architecture.md)
- [AgentLoop](/docs/CS/AI/LLM/Agent/Product/Hermes/AgentLoop.md)
- [Tools](/docs/CS/AI/LLM/Agent/Product/Hermes/Tools.md)
- [Skills](/docs/CS/AI/LLM/Agent/Product/Hermes/Skills.md)
- [Evolve](/docs/CS/AI/LLM/Agent/Product/Hermes/Evolve.md)
- [Infrastructure](/docs/CS/AI/LLM/Agent/Product/Hermes/Infrastructure.md)

## References

- [Hermes Agent 官方仓库（NousResearch/hermes-agent）](https://github.com/NousResearch/hermes-agent)
- [Hermes Agent 文档](https://hermes-agent.nousresearch.com/)
- [Hermes Agent 安装脚本](https://hermes-agent.nousresearch.com/install.sh)
- [agentskills.io（Skill 开放标准）](https://agentskills.io)
- [Honcho（辩证式用户建模）](https://github.com/plastic-labs/honcho)
