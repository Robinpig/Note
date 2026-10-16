> 版本基线：核实于 2026-10-16，npm `opencode-ai` 最新稳定版 **1.19.2**（文档站最后更新 2026-10-15）。OpenCode **2.0** 是一条独立的主版本线：自 v1.19.0 起可通过 `opencode upgrade --major` 或 `/update` 里的 2.0 offer 升级，且 1.x 安装永远不会被作为常规更新推到 2.x——二者是显式分离的两条轨道。本文早期的版本记录已过期：自 **v1.19.1** 起 `/share` / `/unshare` 与分享 URL 导入不再工作；旧的 `patch` 工具已更名为 `apply_patch`，独立的 `todo` / `task` 工具不再作为内置工具列出（`task` 现在是权限键）。各专题页细节均以 1.19.x 核实。

## Introduction

[**OpenCode**](https://opencode.ai/) 是一个开源的 AI 编码代理（AI Coding Agent），由 [anomalyco](https://github.com/anomalyco/opencode) 维护。它提供终端界面（TUI）、桌面应用、IDE 扩展和 GitHub Agent 等多种使用方式。

与 Claude Code 这类「绑定单一模型厂商」的工具相比，OpenCode 的两个核心差异是：

- **模型无关（Model-agnostic）**：同一套 Agent 循环可以驱动 Anthropic、OpenAI、Google 以及任意 OpenAI 兼容端点（Ollama、LM Studio、llama.cpp）
- **客户端/服务器架构**：内核是一个本地 HTTP 服务，TUI、Web、IDE 插件、SDK 都只是它的客户端，因此可以远程 attach、无头运行和二次开发

一句话概括：**OpenCode = Agent 循环（Harness） + 本地服务 + 一套以 Markdown 为载体的扩展协议（Rules / Skills / Commands / Agents / Tools / Plugins / MCP）**。

本篇是 OpenCode 的**总入口**：安装、模型配置、客户端/服务器架构的导览，以及十个专题页的索引；源码级与命令细节在 `OpenCode/` 子目录的各分册。Harness 的通用概念（Host/Harness/Model 三层边界、SubAgent 委派、Compaction 等）已提炼到 [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)。

## Installation

官网一键脚本：

```shell
curl -fsSL https://opencode.ai/install | bash
```

Node 生态（Windows 上推荐此方式）：

```shell
npm install -g opencode-ai
# bun / pnpm / yarn
bun install -g opencode-ai
pnpm install -g opencode-ai
yarn global add opencode-ai
```

macOS 通过 Homebrew：

```shell
brew install anomalyco/tap/opencode
opencode --version
```

Windows 通过 `choco` 或 `scoop`：

```shell
choco install opencode
scoop install opencode
opencode --version
```

其他：

```shell
sudo pacman -S opencode                              # Arch 稳定版
paru -S opencode-bin                                 # Arch AUR
mise use -g github:anomalyco/opencode                # mise
docker run -it --rm ghcr.io/anomalyco/opencode       # 容器内运行
```

启动：

```shell
opencode                    # 在当前目录启动 TUI
opencode /path/to/project   # 指定项目
```

## Model

配置模型与提供商：

```shell
opencode providers          # 别名 opencode auth，管理提供商与凭据
opencode providers list     # 查看已保存的凭据
/connect                    # TUI 内添加提供商（API Key 或 OAuth）
opencode models [provider]  # 列出可用模型
/models                     # TUI 内选择模型
```

凭据落盘在 `~/.local/share/opencode/auth.json`（与 Claude Code 把配置写在 `~/.claude/` 类似，便于备份与迁移）。

`opencode.json` 中的模型相关配置：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "anthropic/claude-sonnet-4-5",       // 主模型：provider/model
  "small_model": "anthropic/claude-haiku-4-5",  // 轻量任务（标题、摘要、压缩）模型
  "enabled_providers": ["anthropic"],
  "disabled_providers": ["github-copilot"],     // 有凭据也跳过，优先级高于 enabled
  "provider": {
    "my-local": {
      "name": "Local Llama",
      "npm": "@ai-sdk/openai-compatible",       // 兼容 /v1/chat/completions 的端点
      "options": {
        "baseURL": "http://127.0.0.1:11434/v1",
        "apiKey": "sk-...",                     // 也可走 auth 存储
        "timeout": 600000
      },
      "models": {
        "llama3.1-70b": { "name": "Llama 3.1 70B" }
      }
    }
  }
}
```

要点：接入 Ollama / LM Studio / 自建网关时在 `/connect` 里选 **Other**，填 provider ID，再把 `npm` 设为 `@ai-sdk/openai-compatible` 并给出 `baseURL`；用 `blacklist` / `whitelist` 控制哪些模型出现在 `/models` 列表里。

## Architecture at a Glance

OpenCode 不是一个单进程 CLI，而是一个**本地 HTTP 服务 + 多个无状态客户端**的系统（TUI、Web、IDE 插件、SDK 都是客户端）。这套 C/S 边界让它可远程 attach、无头运行、二次开发。完整的五层拆解、REST API 表、ACP 协议、配置优先级与网络安全见 [Architecture](/docs/CS/AI/LLM/Agent/Product/OpenCode/Architecture.md)。

## How to Read the Notes

十个专题页按「架构 → Agent 与工具 → 扩展面 → 客户端 → 外部集成」组织。第一次接触建议从 [Architecture](/docs/CS/AI/LLM/Agent/Product/OpenCode/Architecture.md) 入手——必须先理解 C/S 边界，其余页面才有坐标系。

**Agent 与工具**。[Agent](/docs/CS/AI/LLM/Agent/Product/OpenCode/Agent.md) 讲双主 Agent（Build / Plan 默认共存、Tab 循环）与三个只读子 Agent（General / Explore / Scout），外加驱动整套体系的**权限模型**（13 个权限键、三态 `allow`/`ask`/`deny`、最后匹配者胜、默认全放行但 `.env` 默认 deny）。[Tools](/docs/CS/AI/LLM/Agent/Product/OpenCode/Tools.md) 列清 12 个内置工具（含 `apply_patch`、`websearch`、`question` 与实验性 `lsp`），以及用 `@opencode-ai/plugin` 的 `tool()` 写自定义工具、并可覆盖同名内置工具。

**扩展面（Markdown 即配置）**。[Rules](/docs/CS/AI/LLM/Agent/Product/OpenCode/Rules.md) 讲长期记忆的加载顺序（项目 `AGENTS.md` → 兼容 `CLAUDE.md` → 全局 → `instructions` 数组）。[Skills](/docs/CS/AI/LLM/Agent/Product/OpenCode/Skills.md) 讲渐进式加载的专业流程（摘要进上下文、相关才拉全文）与 `permission.skill` 访问控制。[Commands](/docs/CS/AI/LLM/Agent/Product/OpenCode/Commands.md) 讲内置斜杠命令与自定义命令的模板语法（`$ARGUMENTS` / `$1` / `!cmd` / `@path`）。

**客户端与界面**。[TUI](/docs/CS/AI/LLM/Agent/Product/OpenCode/TUI.md) 讲输入约定与独立的 `tui.json` 配置（界面与运行时解耦）。[CLI](/docs/CS/AI/LLM/Agent/Product/OpenCode/CLI.md) 讲 `run` / `serve` / `web` / `session` / `github` / `acp` 等非交互与运维命令。

**外部集成**。[MCP](/docs/CS/AI/LLM/Agent/Product/OpenCode/MCP.md) 讲 local / remote server 配置、OAuth 自动流程与按 Agent 控制工具可见性。[Plugin](/docs/CS/AI/LLM/Agent/Product/OpenCode/Plugin.md) 讲 JS/TS 事件钩子（如 `tool.execute.before`、`session.idle`），可以做 `.env`、密钥路径这类硬拦截。

## Comparison with Claude Code

| 维度 | Claude Code | OpenCode |
| :--- | :--- | :--- |
| 规则文件 | `CLAUDE.md`（全局 `~/.claude/CLAUDE.md`） | `AGENTS.md`（缺失时回退 `CLAUDE.md`） |
| 技能目录 | `.claude/skills/` | `.opencode/skills/`，同时兼容 `.claude/`、`.agents/` |
| 调用技能 | `Skill` 工具 | 原生 `skill` 工具，摘要 + 按需全文 |
| 配置 | `settings.json` + `CLAUDE.md` | `opencode.json`（运行时）+ `tui.json`（界面）分离 |
| 工作模式 | `/plan` 等 | Plan / Build 双主 Agent，Tab 循环 |
| 形态 | CLI + SDK | 本地 HTTP 服务 + TUI / Web / IDE / GitHub / SDK |
| 模型 | 以 Anthropic 为主 | 任意提供商，含 OpenAI 兼容本地端点 |
| 权限模型 | 默认关闭沙箱、deny 优先 | 13 键三态，默认全放行、`.env` 默认 deny、「最后匹配者胜」 |
| 扩展钩子 | hooks（settings 配置） | Plugin 事件钩子（`tool.execute.before` 等），可硬拦截 |

## Practical Recommendations

**规则分层**：全局 `~/.config/opencode/AGENTS.md` 放个人偏好（语言、讲解顺序、范式倾向），项目 `AGENTS.md` 放技术栈、目录结构、可执行的构建/测试命令与**负面约束**（「不要引入新的状态管理库」），子目录再放模块级规则。保持精简，过长提示词会稀释注意力。

**先 Plan 后 Build**：复杂任务用 Tab 切到 Plan 让它出方案，确认后再切 Build；`/undo` 依赖 Git，所以脏工作区前先提交，才能保证撤销/重做可用。

**上下文卫生**：接近窗口上限时 `/compact` 而不是硬撑；探索性闲聊污染上下文时直接 `/new`，长期记忆靠 `AGENTS.md` 重新加载，让 Agent 自己把决策写回 `AGENTS.md` 比手动维护更省力。

**权限最小化**：默认「不问即放行」，适合单人本地环境；一旦接入 MCP 或跑不可信仓库，把 `permission.edit` / `permission.bash` 设为 `ask`，对 `skill` 和 MCP 工具用 glob 精确放开，并用插件做 `.env`、密钥路径这类硬拦截。注意 OpenCode 的「最后匹配者胜」与 Claude Code 的「deny 优先」是**相反的优先级模型**。

## Links

- [Architecture](/docs/CS/AI/LLM/Agent/Product/OpenCode/Architecture.md) / [Agent](/docs/CS/AI/LLM/Agent/Product/OpenCode/Agent.md) / [Tools](/docs/CS/AI/LLM/Agent/Product/OpenCode/Tools.md)
- [Rules](/docs/CS/AI/LLM/Agent/Product/OpenCode/Rules.md) / [Skills](/docs/CS/AI/LLM/Agent/Product/OpenCode/Skills.md) / [Commands](/docs/CS/AI/LLM/Agent/Product/OpenCode/Commands.md)
- [TUI](/docs/CS/AI/LLM/Agent/Product/OpenCode/TUI.md) / [CLI](/docs/CS/AI/LLM/Agent/Product/OpenCode/CLI.md) / [MCP](/docs/CS/AI/LLM/Agent/Product/OpenCode/MCP.md) / [Plugin](/docs/CS/AI/LLM/Agent/Product/OpenCode/Plugin.md)
- [Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md) / [Codex](/docs/CS/AI/LLM/Agent/Product/Codex/Codex.md) / [Pi](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md)
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) — 通用 Harness 概念

## References

1. [OpenCode 官方文档](https://opencode.ai/docs/)
1. [OpenCode 配置](https://opencode.ai/docs/config)
1. [OpenCode Server](https://opencode.ai/docs/server)
1. [OpenCode ACP](https://opencode.ai/docs/acp)
1. [OpenCode Agents](https://opencode.ai/docs/agents)
1. [OpenCode Permissions](https://opencode.ai/docs/permissions)
1. [OpenCode Tools](https://opencode.ai/docs/tools)
1. [OpenCode Custom Tools](https://opencode.ai/docs/custom-tools)
1. [OpenCode Rules](https://opencode.ai/docs/rules)
1. [OpenCode Skills](https://opencode.ai/docs/skills)
1. [OpenCode Commands](https://opencode.ai/docs/commands)
1. [OpenCode MCP Servers](https://opencode.ai/docs/mcp-servers)
1. [OpenCode Plugins](https://opencode.ai/docs/plugins)
1. [OpenCode CLI](https://opencode.ai/docs/cli)
1. [anomalyco/opencode](https://github.com/anomalyco/opencode)
