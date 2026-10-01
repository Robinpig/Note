## Introduction

[**OpenCode**](https://opencode.ai/) 是一个开源的 AI 编码代理（AI Coding Agent），由 [anomalyco](https://github.com/anomalyco/opencode) 维护。它提供终端界面（TUI）、桌面应用、IDE 扩展和 GitHub Agent 等多种使用方式

与 Claude Code 这类"绑定单一模型厂商"的工具相比，OpenCode 的两个核心差异是：

- **模型无关（Model-agnostic）**：同一套 Agent 循环可以驱动 Anthropic、OpenAI、Google 以及任意 OpenAI 兼容端点（Ollama、LM Studio、llama.cpp）
- **客户端/服务器架构**：内核是一个本地 HTTP 服务，TUI、Web、IDE 插件、SDK 都只是它的客户端，因此可以远程 attach、无头运行和二次开发

一句话概括：**OpenCode = Agent 循环（Harness） + 本地服务 + 一套以 Markdown 为载体的扩展协议（Rules / Skills / Commands / Agents / Plugins / MCP）**



## Architecture

自上而下可以拆成五层：

#### 1. 客户端层 (Client)

TUI（主客户端）、`opencode web`（浏览器界面）、IDE 插件、`opencode github`（CI 中的 Agent）、自定义脚本（SDK / HTTP）。它们都是同一后端的客户端

#### 2. 服务层 (Server)

```shell
opencode serve            # 无头 HTTP 服务，默认端口 4096
opencode attach <url>     # 让本地 TUI 连接到已存在的服务
opencode web              # 启动服务并打开浏览器
```

服务暴露 OpenAPI 3.1 规范（`/doc`），官方 SDK 即由该规范生成。可用 `--hostname`、`--port`、`--cors`、`--mdns` 控制监听与服务发现（mDNS），`opencode web` 与 `opencode serve` 共用同一套 basic-auth 环境变量防护

#### 3. 会话层 (Session)

会话以 `session → message → part` 三级结构持久化在本地 SQLite（`opencode db` 提供维护命令）。因此支持 `opencode session list`、`--continue`、`--session`、`--fork`（分叉会话）以及 `opencode export` / `opencode import`

#### 4. 代理与工具层 (Agent & Tools)

- **主 Agent**：`Build`（默认，全能力）与 `Plan`（默认对编辑和 bash 询问，用于只读分析）
- **子 Agent**：`general`（多步执行）、`explore`（只读检索代码库）、`scout`（只读检索外部文档与依赖）；另有 `compaction`、`title`、`summary` 等隐藏的自动 Agent
- **工具**：read / write / edit / bash / grep / glob / patch / webfetch / todo / task / skill 等，配合 **LSP** 与 **formatter** 保证编辑后的代码质量
- **权限**：`allow` / `ask` / `deny` 三态；默认为"不询问直接执行"，可对 `bash`、`edit`、`task`、`skill` 等按 glob 模式逐项收紧

#### 5. 扩展层 (Extension Surface)

`AGENTS.md`（规则）、`skills/`（技能）、`commands/`（自定义命令）、`agents/`（自定义 Agent）、`plugins/`（事件钩子）、`mcp`（外部工具）。除 plugin 是 JS/TS 之外，其余全部是 Markdown + JSON，"文件即配置"



## Installation

官网一键脚本

```shell
curl -fsSL https://opencode.ai/install | bash
```

Node 生态（Windows 上推荐此方式，本机安装即 `npm install -g opencode-ai`）

```shell
npm install -g opencode-ai
# bun / pnpm / yarn
bun install -g opencode-ai
pnpm install -g opencode-ai
yarn global add opencode-ai
```

macOS 通过 Homebrew

```shell
brew install anomalyco/tap/opencode

opencode --version
```

Windows 通过 `choco` 或 `scoop` 安装

```shell
choco install opencode
scoop install opencode

opencode --version
```

其他

```shell
sudo pacman -S opencode                              # Arch 稳定版
paru -S opencode-bin                                 # Arch AUR
mise use -g github:anomalyco/opencode                # mise
docker run -it --rm ghcr.io/anomalyco/opencode       # 容器内运行
```

启动

```shell
opencode                    # 在当前目录启动 TUI
opencode /path/to/project   # 指定项目
```



## Model

配置模型与提供商

```shell
opencode providers          # 别名 opencode auth，管理提供商与凭据
opencode providers list     # 查看已保存的凭据
/connect                    # TUI 内添加提供商（API Key 或 OAuth）
opencode models [provider]  # 列出可用模型
/models                     # TUI 内选择模型
```

凭据落盘在 `~/.local/share/opencode/auth.json`（与 Claude Code 把配置写在 `~/.claude/` 类似，便于备份与迁移）

`opencode.json` 中的模型相关配置

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "anthropic/claude-sonnet-4",   // 主模型：provider/model
  "small_model": "openai/gpt-4o-mini",    // 轻量任务（标题、摘要、压缩）模型
  "enabled_providers": ["anthropic"],
  "disabled_providers": ["github-copilot"], // 有凭据也跳过，优先级高于 enabled
  "provider": {
    "my-local": {
      "name": "Local Llama",
      "npm": "@ai-sdk/openai-compatible",  // 兼容 /v1/chat/completions 的端点
      "options": {
        "baseURL": "http://127.0.0.1:11434/v1",
        "apiKey": "sk-...",                // 也可走 auth 存储
        "timeout": 600000
      },
      "models": {
        "llama3.1-70b": { "name": "Llama 3.1 70B" }
      }
    }
  }
}
```

要点：接入 Ollama / LM Studio / 自建网关时在 `/connect` 里选 **Other**，填 provider ID，再把 `npm` 设为 `@ai-sdk/openai-compatible` 并给出 `baseURL`；用 `blacklist` / `whitelist` 控制哪些模型出现在 `/models` 列表里



## Agent

**Plan 与 Build 是 OpenCode 与传统 IDE 最大的不同之一**：Tab 键在两个主 Agent 间循环（或 `switch_agent`）。Plan 只读分析、动手前先出方案，Build 才放开编辑与执行——先规划再执行，能显著减少方向性返工

子 Agent 由主 Agent 自动调用，也可以用 `@` 显式提及；在子会话中可用 Down / Right / Left / Up 在 leader 与 children 之间进出

定义自定义 Agent：`opencode agent create`（交互式生成）或 `opencode agent list`（查看已有），也可以直接写 Markdown 文件，全局放 `~/.config/opencode/agents/`，项目放 `.opencode/agents/`，**文件名（去掉 `.md`）即 Agent 名**（`review.md` → `/review` 与 `@review`）

```markdown
---
description: 只读地审查改动，不写文件
mode: subagent            # primary | subagent | all
model: anthropic/claude-sonnet-4
temperature: 0.2
steps: 12                 # 最大迭代轮数，旧字段 maxSteps 已废弃
permission:
  edit: deny
  bash:
    "git diff *": allow
    "*": ask
  task: deny
---

你是一个严格的评审者，先列问题再给结论，不要直接改代码。
```

也可以在 `opencode.json` 的 `agent` 键里用 JSON 声明。未写 `model` 时，主 Agent 用全局模型，子 Agent 继承调用者的模型。`tools` 字段已不推荐，统一用 `permission` 表达；frontmatter 里多余的键会作为模型参数透传给 provider

隐藏的 `compaction` / `title` / `summary` Agent 负责上下文压缩、会话标题与摘要，是 `/compact`、`/undo` 等能力得以长期运行的基础



## Rules

OpenCode 的规则文件（长期记忆）加载顺序：

1. 项目规则：从当前目录**向上**查找 `AGENTS.md`，找到后其约束覆盖该目录下的文件
2. 兼容兜底：若项目内没有 `AGENTS.md`，则读取 `CLAUDE.md`（Claude Code 兼容）
3. 全局规则：`~/.config/opencode/AGENTS.md`；若不存在，退回到 `~/.claude/CLAUDE.md`
4. 额外注入：`opencode.json` 的 `instructions` 数组，支持本地路径、glob 通配甚至远程 URL（拉取超时 5s），与自动发现的规则**合并**而非替换

```json
{
  "instructions": ["./docs/rules/*.md", "https://example.com/style.md"]
}
```

> [!NOTE]
>
> `AGENTS.md` 与 `CLAUDE.md` 同时存在时只用前者。`/init` 会扫描项目并生成 `AGENTS.md`，因此从 Claude Code 迁移过来的仓库若希望两套工具共享同一份规则，可以让 `AGENTS.md` 通过 `instructions` 指回 `CLAUDE.md`，或者由安装脚本维护带标记块的 `AGENTS.md`



## Skills

技能（渐进式加载的专业流程）目录：

- 项目级：`.opencode/skills/<name>/SKILL.md`，同时兼容 `.claude/skills/`、`.agents/skills/`
- 全局：`~/.config/opencode/skills/`、`~/.claude/skills/`、`~/.agents/skills/`
- 项目级查找会一直向上直到仓库边界 / git worktree 根

`SKILL.md` 的 frontmatter 中 `name` 与 `description` 必填，`license`、`compatibility`、`metadata` 可选，未知字段忽略。启动时 Agent 只看到名称与描述的摘要，判断相关后才通过原生 `skill` 工具拉取全文——这正是 Skill 相比"把规范全塞进系统提示词"节省 token 的地方

访问控制

```json
{
  "permission": {
    "skill": {
      "*": "allow",
      "chinese-*": "ask",
      "internal-*": "deny"
    }
  },
  "agent": {
    "reviewer": {
      "permission": { "skill": { "*": "deny", "chinese-code-review": "allow" } },
      "tools": { "skill": false }   // 也可以直接关掉某个 Agent 的 skill 工具
    }
  }
}
```



## Commands

TUI 内置斜杠命令（默认 leader 键为 `ctrl+x`）

| 命令 | 作用 | 快捷键 |
| --- | --- | --- |
| `/connect` | 添加提供商与凭据 | — |
| `/init` | 扫描项目并生成 `AGENTS.md` | — |
| `/models` | 选择模型 | `ctrl+x m` |
| `/new` (`/clear`) | 新会话 | `ctrl+x n` |
| `/sessions` (`/resume`, `/continue`) | 列出并切换会话 | `ctrl+x l` |
| `/compact` (`/summarize`) | 压缩上下文 | `ctrl+x c` |
| `/undo` / `/redo` | 撤销/重做上一条消息及文件改动（依赖 Git） | `ctrl+x u` / `ctrl+x r` |
| `/share` / `/unshare` | 分享或取消分享会话 | — |
| `/export` | 导出会话为 Markdown | `ctrl+x x` |
| `/editor` | 用外部编辑器撰写长提示 | `ctrl+x e` |
| `/details` | 切换工具执行细节显示 | — |
| `/thinking` | 切换思考过程可见性 | — |
| `/themes` | 切换主题 | `ctrl+x t` |
| `/help` | 帮助 | — |
| `/exit` (`/quit`, `/q`) | 退出 | `ctrl+x q` |

自定义命令：全局 `~/.config/opencode/commands/`，项目 `.opencode/commands/`，文件名（去掉 `.md`）即命令名；也可以在 `opencode.json` 的 `command` 键里写。frontmatter 支持 `description`、`agent`、`model`，正文就是提示词模板

```markdown
---
description: 带覆盖率地跑测试并分析失败原因
agent: build
model: anthropic/claude-sonnet-4
---

最近一次测试输出：!`npm test`

请阅读 @src 下相关实现，定位 $1 的失败原因，给出修复方案（先不写代码）。
剩余上下文：$ARGUMENTS
```

参数替换：`$ARGUMENTS` 为命令后的全部文本，`$1`、`$2`、`$3` 为位置参数。模板里以 `!` 加反引号包裹的命令会先执行 shell 并把输出注入，`@路径` 会注入文件内容。**自定义命令可以覆盖同名内置命令**



## TUI

输入约定

- `@` 模糊搜索并把文件内容加入上下文（配置过的引用如 `@alias/` 会出现在补全里）
- 行首 `!` 直接进入 shell，输出作为工具结果回到对话
- 拖拽图片到终端即可作为输入
- `ctrl+p` 打开命令面板调整视图设置（持久化）

界面行为由**独立的 `tui.json` / `tui.jsonc`** 控制（schema `https://opencode.ai/tui.json`），与运行时配置解耦：换终端不影响 Agent 行为，改 Agent 行为也不动 UI。配置路径可用 `OPENCODE_CONFIG` / `OPENCODE_CONFIG_DIR` 和 `OPENCODE_TUI_CONFIG` 覆盖，多层配置始终按**键合并**而非整体替换

```json
{
  "$schema": "https://opencode.ai/tui.json",
  "theme": "opencode",
  "keybinds": { "command_list": "ctrl+p" },
  "leader_timeout": 2000,
  "scroll_speed": 3,
  "diff_style": "auto",        // auto | stacked
  "cursor": { "style": "block", "blinking": true },
  "mouse": true,
  "attention": {}              // 桌面通知与声音：提问、权限请求、报错、会话完成
}
```

`/editor` 与 `/export` 使用 `EDITOR` 环境变量，GUI 编辑器要加 `--wait`：`export EDITOR="code --wait"`



## MCP

```json
{
  "mcp": {
    "context7": {
      "type": "remote",
      "url": "https://mcp.context7.com/mcp",
      "headers": { "Authorization": "Bearer {env:CONTEXT7_API_KEY}" },
      "enabled": true,
      "timeout": 10000
    },
    "playwright": {
      "type": "local",
      "command": ["npx", "-y", "@playwright/mcp"],
      "cwd": ".",
      "environment": { "NODE_ENV": "development" }
    }
  }
}
```

`local` 必须给 `command` 数组，`remote` 必须给 `url`；`{env:VAR}` 做环境变量插值。远程服务返回未认证时，OpenCode 会自动发起 OAuth（支持动态注册），也可预先给 `clientId` / `clientSecret` / `scope`，或 `"oauth": false` 关掉自动流程。凭据在 `~/.local/share/opencode/mcp-auth.json`

```shell
opencode mcp add [name]        # 添加
opencode mcp list              # 查看状态
opencode mcp auth [name]       # OAuth 认证
opencode mcp logout <name>
opencode mcp debug <name>      # 排查 OAuth 连接
```

工具名默认以 `server_` 前缀出现，可按模式屏蔽（如 `"my-mcp*": false`）后再单独授权给某个 Agent



## Plugin

插件是导出函数的 JS/TS 模块：函数收到 `{ project, directory, worktree, client, $ }`，返回一组钩子处理器

加载位置：项目 `.opencode/plugins/`、全局 `~/.config/opencode/plugins/`、或 `opencode.json` 里 `"plugin": ["opencode-helicone-session"]` 直接引 npm 包（`opencode plugin <module>` 会自动装依赖并改配置）。`--pure` 可临时禁用所有外部插件排查问题

常用事件：`command.executed`、`message.updated` / `message.part.updated`、`permission.asked` / `permission.replied`、`session.created` / `session.idle` / `session.error` / `session.diff` / `session.status` / `session.compacted`、`file.edited`、`lsp.client.diagnostics`、`shell.env`、`todo.updated`、`tool.execute.before` / `tool.execute.after`、`tui.prompt.append` / `tui.command.execute` / `tui.toast.show`，以及兜底的通用 `event` 处理器

```ts
import type { Plugin } from "@opencode-ai/plugin"

export const Guard: Plugin = async ({ client }) => ({
  // 拦截：禁止读取 .env
  "tool.execute.before": async (input, output) => {
    if (input.tool === "read" && output.args.filePath.includes(".env")) {
      throw new Error("Blocked")
    }
  },

  // 注入 shell 环境变量
  "shell.env": async (_input, output) => {
    output.env.MY_VAR = "value"
  },

  // 会话空闲时打点
  event: async ({ event }) => {
    if (event.type === "session.idle") {
      await client.app.log({ body: { service: "guard", level: "info", message: "idle" } })
    }
  },
})
```



## CLI

```shell
opencode run "解释这个报错"        # 非交互执行，适合脚本与管道
opencode run -m anthropic/claude-sonnet-4 --agent plan "先给方案"
opencode -c                        # 继续上一次会话
opencode --session <id> --fork     # 分叉会话
opencode pr 123                    # checkout PR 分支后进入 TUI
opencode github install            # 在仓库里安装 GitHub Agent（CI 中协作）
opencode github run
opencode stats                     # token 用量与费用统计
opencode export [sessionID] > s.json && opencode import s.json
opencode acp                       # 启动 ACP（Agent Client Protocol）服务，供 IDE 侧接入
opencode serve --port 4096 --hostname 127.0.0.1
opencode upgrade [target]          # 升级（autoupdate: false | "notify"）
opencode uninstall                 # 卸载并清理
opencode db | debug | completion   # 数据库维护 / 排障 / shell 补全
```

通用参数：`--print-logs`、`--log-level DEBUG|INFO|WARN|ERROR`、`--pure`、`--prompt`、`--agent`、`--mdns`、`--mdns-domain`、`--cors`



## 与 Claude Code 的对照

| 维度 | Claude Code | OpenCode |
| --- | --- | --- |
| 规则文件 | `CLAUDE.md`（全局 `~/.claude/CLAUDE.md`） | `AGENTS.md`（缺失时回退 `CLAUDE.md`） |
| 技能目录 | `.claude/skills/` | `.opencode/skills/`，同时兼容 `.claude/`、`.agents/` |
| 调用技能 | `Skill` 工具 | 原生 `skill` 工具，摘要 + 按需全文 |
| 配置 | `settings.json` + `CLAUDE.md` | `opencode.json`（运行时）+ `tui.json`（界面）分离 |
| 工作模式 | `/plan` 等 | Plan / Build 双主 Agent，Tab 循环 |
| 形态 | CLI + SDK | 本地 HTTP 服务 + TUI / Web / IDE / GitHub / SDK |
| 模型 | 以 Anthropic 为主 | 任意提供商，含 OpenAI 兼容本地端点 |



## 实践建议

**规则分层**：全局 `~/.config/opencode/AGENTS.md` 放个人偏好（语言、讲解顺序、范式倾向），项目 `AGENTS.md` 放技术栈、目录结构、可执行的构建/测试命令与**负面约束**（"不要引入新的状态管理库"），子目录再放模块级规则。保持精简，过长提示词会稀释注意力

**先 Plan 后 Build**：复杂任务用 Tab 切到 Plan 让它出方案，确认后再切 Build；`/undo` 依赖 Git，所以脏工作区前先提交，才能保证撤销/重做可用

**上下文卫生**：接近窗口上限时 `/compact` 而不是硬撑；探索性闲聊污染上下文时直接 `/new`，长期记忆靠 `AGENTS.md` 重新加载，让 Agent 自己把决策写回 `AGENTS.md` 比手动维护更省力

**权限最小化**：默认"不问即放行"，适合单人本地环境；一旦接入 MCP 或跑不可信仓库，把 `permission.edit` / `permission.bash` 设为 `ask`，对 `skill` 和 MCP 工具用 glob 精确放开，并用插件做 `.env`、密钥路径这类硬拦截



## Links

- [AI](/docs/CS/AI/AI.md)
- [LLM](/docs/CS/AI/LLM/LLM.md)
- [Agent](/docs/CS/AI/LLM/Agent.md)
- [Claude](/docs/CS/AI/LLM/Claude.md)
- [Codex](/docs/CS/AI/LLM/Codex.md)
- [Skill](/docs/CS/AI/LLM/Skill.md)
- [MCP](/docs/CS/AI/LLM/MCP.md)
- [Harness](/docs/CS/AI/LLM/Harness.md)
- [Vibe](/docs/CS/AI/LLM/Vibe.md)



## References

1. [OpenCode 官方文档](https://opencode.ai/docs/)
1. [Agents-OpenCode](https://opencode.ai/docs/agents)
1. [Rules-OpenCode](https://opencode.ai/docs/rules)
1. [Skills-OpenCode](https://opencode.ai/docs/skills)
1. [Commands-OpenCode](https://opencode.ai/docs/commands)
1. [Config-OpenCode](https://opencode.ai/docs/config)
1. [Providers-OpenCode](https://opencode.ai/docs/providers)
1. [MCP Servers-OpenCode](https://opencode.ai/docs/mcp-servers)
1. [Plugins-OpenCode](https://opencode.ai/docs/plugins)
1. [Server-OpenCode](https://opencode.ai/docs/server)
1. [anomalyco/opencode](https://github.com/anomalyco/opencode)
