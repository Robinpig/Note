> 版本基线：核实于 2026-10-16。事实以 npm `@earendil-works/pi-coding-agent` **1.3.0**（2026-10-15 发布）与 GitHub `earendil-works/pi` `main` 分支的官方文档/源码为准。本篇早期的版本记录（`git tag v1.0.0`，提交 `a13d35a74`）已跨三个 minor：`protocol`/`client`/`server` 三个实验性远程会话包被删除、新增 `env`（SSH 远程执行环境）包，运行模式从三种增加到四种（JSON 事件流转正），技能体系切换到 Agent Skills 规范。旧文「持久化 Shell」「`/load-skill`」「`templates/` 目录」等表述已在各分册逐条修正。

## Introduction

Pi 是一个跑在终端里的 AI 编程 agent，口号是 **minimal, extensible agent harness that you can make your own**——把能力藏在基础操作里，而不是堆在界面上。默认只启用四个工具（`read` / `bash` / `edit` / `write`），sub-agent、plan mode 这类「重型」特性一概不带，需要就自己装包或写扩展。整仓 TypeScript（一个 Rust 边界库都没有——对比 OpenClaw 的 Rust 只做边界库，Pi 更纯），由 Earendil Works 维护，npm 包名 `@earendil-works/pi-coding-agent`。

它同时是 Harness 抽象的优秀标本：[Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) 的「对模型能力缺口的补偿面」在 Pi 身上被拆成了可替换的层——会话树、压缩、工具、信任机制各自独立成篇；内部实现（包分层、两层协作循环、工具批次链路）见 [Architecture](/docs/CS/AI/LLM/Agent/Product/Pi/Architecture.md)，与 [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) 的 Loop/Tools/Memory/Harness 四构成对照阅读最清楚。

模型无关是卖点：内置目录覆盖 44 个 provider（Anthropic / OpenAI / Google / Bedrock / OpenRouter / 国产各家……），`/login` 选 provider、`/model` 选模型，凭证、目录、兼容端点都可自定义。

## Installation

macOS / Linux 首选安装脚本（钉死所有依赖，之后 `pi update` 升级）：

```bash
curl -fsSL https://pi.dev/install.sh | sh
```

Windows 用 PowerShell：`powershell -c "irm https://pi.dev/install.ps1 | iex"`。也可以走 npm（不钉传递依赖，需 Node.js ≥ 22.19）：

```bash
npm install -g --ignore-scripts @earendil-works/pi-coding-agent
```

Nix 用户装 flake（从源码构建）：`nix profile add github:earendil-works/pi/stable`，可用 tag 钉版本，升级走 `nix profile upgrade pi`（`pi update` 管不了 Nix 装的 Pi）。卸载：npm 装的就 `npm uninstall -g`，脚本装的再跑一次脚本选 Uninstall，Nix 装的 `nix profile remove pi`——三种方式都不动 `~/.pi/agent/` 下的配置、凭证、会话和已装包。

装完 `pi --version` 验证，`cd` 到工作目录跑 `pi` 即启动；首次使用按 Quickstart 走 `/login` → 选模型 → 派活。

## Run Modes

同一份 AgentSession 套不同 I/O 外壳：

| 模式 | 触发 | 用途 |
| :--- | :--- | :--- |
| interactive | 终端直跑（默认全屏 TUI） | 人机交互 |
| print | `-p` / `--print`，或 stdin/stdout 被重定向 | 一次性任务、脚本 |
| json | `--mode json` | 单次运行的 JSONL 事件流 |
| rpc | `--mode rpc` | 控制一个独立 Pi 进程（stdin/stdout JSONL） |

另有 TypeScript SDK（`createAgentSession` 等）在应用内嵌 Pi。四种形态共享同一套 agent 与会话机制，详细协议面见 [Architecture](/docs/CS/AI/LLM/Agent/Product/Pi/Architecture.md)。

## Subsystem Notes

**日常交互**从 [Interaction](/docs/CS/AI/LLM/Agent/Product/Pi/Interaction.md) 入手：`@` 引用与图片粘贴、`!`/`!!` 两条 Shell 前缀（注意每条命令都是独立进程，旧文「持久化 Shell」已不成立）、可自定义的命名快捷键体系、七档思考级别与模型切换、steering/follow-up 两种排队语义。

**会话即数据**在 [Session](/docs/CS/AI/LLM/Agent/Product/Pi/Session.md)：会话是 JSONL 树，模型只见活跃分支；`/tree`（文件内移动）、`/fork`（早期消息建新会话）、`/clone`（复制当前分支）三种操作分工明确，离开分支时可带摘要迁移，`/export` / `/share` 负责出场。

**上下文与压缩**在 [Context](/docs/CS/AI/LLM/Agent/Product/Pi/Context.md)：AGENTS.md 层级与 override 语义、SYSTEM.md 两级优先、压缩的阈值公式（`contextTokens > contextWindow - reserveTokens`，默认保留 16k 响应空间、20k 近期消息）、切割点规则与结构化摘要格式。

**扩展体系**在 [Extensions](/docs/CS/AI/LLM/Agent/Product/Pi/Extensions.md)：Skill（Agent Skills 规范，两阶段加载）、Prompt Template（文件名即命令）、Pi Package（npm/git 分发 + peerDependencies 纪律）、TypeScript Extension（工具 exposure 五态、嵌套调用、生命周期纪律）四层由浅入深。

**信任与隔离**在 [Security](/docs/CS/AI/LLM/Agent/Product/Pi/Security.md)：Pi 无内置权限系统，project trust 管加载（决策链四级、`trust.json`、非交互模式行为），隔离靠 Docker / Docker Sandboxes / OpenShell / Gondolin 四法，凭证处理各有取舍。

**内部架构**在 [Architecture](/docs/CS/AI/LLM/Agent/Product/Pi/Architecture.md)：11 个 workspace 包的分层与依赖图、`AgentSession` 驱动 `pi-agent-core` 的两层协作循环、工具批次与事件持久化顺序、四种运行模式与 SDK、构建顺序与质量门禁。

## Trade-offs

- **上手快但需自己配置**：安装一条命令，但不像 [Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md) / [Codex](/docs/CS/AI/LLM/Agent/Product/Codex/Codex.md) 那样开箱带 Plan mode、子 agent、审批框——这些在 Pi 里要么装包要么写扩展。
- **透明度高**：每次读了哪个文件、跑了什么命令、改了哪几行都可见，没有子 agent 黑盒，契合 plan-act-verify 工作法。
- **会话是树**：从任意消息分叉试不同方案，实验成本低；分支摘要让「换路子」不丢上下文。
- **轻量提示词、上下文干净**：系统提示和工具定义精简，部分评测中同任务比重型 harness 省 token——但这依赖模型与任务，不是任何 workload 都更省。
- **长会话强**：单会话可承载数百轮，压缩策略与替换实现都能用扩展换掉。
- **短板**：无内置审批与沙箱（安全靠外部环境，见 [Security](/docs/CS/AI/LLM/Agent/Product/Pi/Security.md)）、无跨会话持久记忆、深度定制要写 TypeScript、生态规模不及 [MCP](/docs/CS/AI/LLM/Protocol/MCP.md) 成熟阵营；四个默认工具是刻意的极简设计而非缺失。

适合想自己掌控 harness 形态、需要在同一会话切换多家模型、重视上下文干净与 token 效率、愿意锻造工作流的用户；不适合追求一站式开箱、依赖消息平台网关、或要求内置审批流的企业场景。

## Common Issues

| 问题 | 回答 |
| :--- | :--- |
| 会话太多会不会卡？ | 不会。会话是 `~/.pi/agent/sessions/` 下的 JSONL 文件，卡顿主要来自模型响应速度，与会话数量无关 |
| Shell 里 `cd` / `export` 为什么不保留？ | 每条命令都是独立的非交互 shell 进程（`bash -c`）。要跨命令复现状态，用 `shellCommandPrefix` 在每条命令前垫 setup，详见 [Interaction](/docs/CS/AI/LLM/Agent/Product/Pi/Interaction.md) |
| 换模型后会话还在吗？ | 在。会话记录与模型相互独立，同一会话内随时切换模型不丢内容 |
| 打开陌生仓库要注意什么？ | 触发 project trust 时先看清它要加载什么（扩展/技能/MCP 都能执行代码）；文件夹里的 `AGENTS.md` 等指令一律按不可信输入对待，详见 [Security](/docs/CS/AI/LLM/Agent/Product/Pi/Security.md) |
| 能用 Pi 联网搜索吗？ | 不内置。可以 bash 里 `curl`，或装社区搜索包（Tavily / Grok） |
| 想加能力从哪入手？ | 从最弱的机制开始：指令 → 模板 → Skill → Package → Extension，选型表见 [Extensions](/docs/CS/AI/LLM/Agent/Product/Pi/Extensions.md) |

## Links

- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) / [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) — Pi 对应的两个抽象层
- [Codex](/docs/CS/AI/LLM/Agent/Product/Codex/Codex.md) / [Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md) / [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md) / [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md) / [DSH](/docs/CS/AI/LLM/Agent/Product/DSH/DSH.md) — 同层产品对照
- [MCP](/docs/CS/AI/LLM/Protocol/MCP.md) — Pi 内置 MCP 客户端的外部协议面

## References

- [earendil-works/pi 仓库](https://github.com/earendil-works/pi)
- [Pi 官方文档](https://pi.dev/docs) / [Pi package gallery](https://pi.dev/packages) / [Pi 模型目录](https://pi.dev/models)
- [PI 系列（三）：扩展能力与选型指南](https://mp.weixin.qq.com/s/Rv0a2_7dzSSWJeTOXKQiLA)
- [PI 系列（二）：日常使用技巧](https://mp.weixin.qq.com/s/1MSVysazeK_uyaY46XG7Cw)
- [Pi 中文文档](https://pi-doc.com)
