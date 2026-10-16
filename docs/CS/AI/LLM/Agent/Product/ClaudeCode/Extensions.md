## Introduction

Claude Code 的扩展面有四层，都叠在核心 agentic loop 之上（见 [Architecture](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Architecture.md)）：**skills**（补充知识）、**MCP servers**（接外部服务）、**plugins**（把上述成分打包分发）、**output styles**（改会话级的角色与文风）。此外 hooks（自动化工作流）见 [Hooks](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Hooks.md)，subagents 见 [Subagents](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Subagents.md)。

事实基线：`@anthropic-ai/claude-code` **2.1.301**（2026-10-15），官方 skills / plugins / mcp / output-styles 页（2026-10-16 核实）。

## Choosing The Right Extension

选型的第一刀是**加载时机**：

| 需求 | 用什么 |
| :--- | :--- |
| Claude 每次会话都该知道的事实 | CLAUDE.md（见 [Memory](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Memory.md)） |
| 按路径生效的指令 | `.claude/rules/` |
| 用时才加载的多步流程/参考资料 | skill |
| 必须每次都发生的动作 | hook |
| 改整个会话的角色/文风 | output style |
| 接外部系统的工具 | MCP server |
| 打包分发一组上述成分 | plugin |

## Skills

Skill 是带 frontmatter 的 `SKILL.md`：frontmatter 的 description 告诉 Claude 何时自动加载，正文是运行时才读的指令。Claude Code 的 skills 遵循 **Agent Skills 开放标准**（跨工具通用），在此之上扩展了调用控制、subagent 执行、动态上下文注入等能力。通用规范见 [Skill 理论篇](/docs/CS/AI/LLM/Agent/Theory/Skill.md)，本文只讲 Claude Code 侧。

### 与旧 commands 格式的关系

**自定义命令已合并进 skills**：`.claude/commands/deploy.md` 与 `.claude/skills/deploy/SKILL.md` 等价（都创建 `/deploy`），旧文件继续可用；skill 多出支持文件目录、调用控制 frontmatter、自动加载三样能力。新工作一律用 skill 格式。

### 加载位置

| 位置 | 路径 | 加载范围 |
| :--- | :--- | :--- |
| Enterprise | managed settings 目录下 `.claude/skills/<name>/SKILL.md` | 组织部署的所有机器 |
| Personal | `~/.claude/skills/<name>/SKILL.md` | 本机所有项目（不含 Cowork/cloud） |
| Project | `.claude/skills/<name>/SKILL.md` | 本仓库会话，提交即团队共享 |
| Nested | 子目录下同名结构 | 启动于该目录或其下时；从更上层启动则等 Claude 碰该目录文件时加载 |
| Additional directory | `--add-dir` 目录下的 `.claude/skills/` | 该会话 |
| Plugin | 插件内 `skills/<name>/SKILL.md` | 插件启用处，调用名为 `/plugin-name:skill-name` |
| claude.ai account | 账户同步的 skills | Cowork、cloud 与登录该账户的终端会话 |

monorepo 语义：从启动目录起**向上直到仓库根**都扫 `.claude/skills/`；启动目录之下的 skill 不随启动加载，等 Claude 读写该子目录文件时才可用。`--worktree` 会话只扫到 worktree 根；worktree 里没有 `.claude/skills` 时（v2.1.277+）回退加载主 checkout 的项目 skills。保留名：`synced`（claude.ai 下载位）与 `anthropic-skills` 开头的名字不加载。

### 动态上下文注入

SKILL.md 里 `!`command`` 行会在 Claude 看到内容**之前**被执行、并把输出内联防进来——官方的例子是在 skill 里写 ``!`git diff HEAD``` 让摘要指令带着真实 diff 到达。

### Bundled Skills

Claude Code 自带一批 prompt 型 bundled skills：`/doctor`（安装与配置体检）、`/code-review`、`/batch`、`/debug`、`/loop`、`/claude-api`（Claude API 参考材料，代码 import anthropic 时自动激活）、`/run` 与 `/verify`（启动并驱动 app 验证改动，`/run-skill-generator` 把项目的构建启动配方录成 per-project skill）、`/simplify`、`/workflow-authoring`（dynamic workflows 启用时）。`disableBundledSkills` 可整体关闭（`/doctor` 仍可键入，除非再设 `DISABLE_DOCTOR_COMMAND`）。

有个与提交相关的联动：会话启动时若存在名为 `verify` 或 `simplify` 的 skill（enterprise/personal/project/additional-dir 位置或 `.claude/commands/` 同名文件，bundled 与插件的不算），Claude Code 的提交指令会让 Claude 在**每次 commit 前跑它**（docs/tests 改动除外，v2.1.286+）。

## Plugins

Plugin 是打包分发的单位：一个目录（带 `.claude-plugin/plugin.json` manifest）装上 skills、agents、hooks、MCP servers，一次安装整体生效。

- **mod**：hooks 写成 JavaScript 函数的插件，函数在 Claude Code 进程内运行、能画界面能加命令。
- **marketplace**：带 `.claude-plugin/marketplace.json` 的仓库/目录，是 catalog 不是 hosted store。官方 marketplace（`claude-plugins-official`）首次交互式终端会话自动添加；官方市场里可看每个插件的 **Context cost 预估**。
- **安装 scope**：user（本机所有项目）/ project（提交 `.claude/settings.json`，协作者各自安装）/ local（本仓库仅自己）。cloud session 不加载本地 settings 里的插件。
- **常驻成本**：插件里每个可被 Claude 自动调用的成分，其 name+description 每轮都在上下文里（计用量），全文只在被用时加载；MCP servers 随启用插件的每个会话常驻运行。
- 开发期不用 marketplace：`--plugin-dir` 直接加载本地文件夹。组织可经 managed settings allowlist/block marketplace、force-install 插件。
- `/plugin` 的 Discover 标签浏览安装；安装前三档市场（official / community / third-party）靠 marketplace 名区分，官方名只接受来自 `github.com/anthropics/` 的来源。

## MCP

MCP server 给 Claude 接外部系统的工具（协议本身见 [MCP](/docs/CS/AI/LLM/Protocol/MCP.md)）。Claude Code 侧的关键事实：

- 四种添加方式：remote HTTP、remote SSE、local stdio、remote WebSocket；`claude mcp add` 一条命令搞定，也支持从写给别的 client 的 setup 指令导入。
- **工具定义默认延迟加载**：只把工具名与 server 指令放进上下文，Claude 真要用了才经 tool search 加载——这是控制 MCP 上下文成本的核心机制。
- 支持运行时动态工具更新（server 的 tool list 变了会反映）与自动重连。
- MCP 工具在 hooks 与权限系统里就是普通工具：命名 `mcp__<server>__<tool>`（匹配细节见 [Hooks](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Hooks.md)），可用 `permissions.deny` 按 `mcp__server__tool` 粒度管控。

## Output Styles

Output style 是一组指令，设定整个会话里 Claude 的角色、语气与响应格式。除 Default（无 style，标准软工系统提示）外有四个内置：

| Style | 变化 |
| :--- | :--- |
| `Proactive` | 直接开干，常规决策自行假设而非停下来问；删数据/改共享或生产系统前仍会在对话里确认（这是指令不是权限提示） |
| `Concise` | 首句即结论，去掉铺垫与复述；简单问题 1~3 句（v2.1.237+）。错误报告、失败测试输出、安全告警、破坏性动作确认保持完整 |
| `Explanatory` | 代码前后加 `★ Insight` 块，解释选择背后的理由 |
| `Learning` | 同 Explanatory，并在有真实设计决策处留几行给你写（文件里标 `TODO(human)`） |

style 只是指令，不保证行为；它不改权限模式（Proactive 不改变哪些工具调用免问）。自定义 style 可以把它变成写作助手、数据分析师之类的非软工角色。

## Links

- [ClaudeCode 主枢纽](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md)
- [Skill 理论篇](/docs/CS/AI/LLM/Agent/Theory/Skill.md)
- [MCP 协议](/docs/CS/AI/LLM/Protocol/MCP.md)
- [Hooks](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Hooks.md)

## References

- [Claude Code skills](https://code.claude.com/docs/en/skills)
- [Claude Code plugins](https://code.claude.com/docs/en/plugins)
- [Connect Claude Code to tools via MCP](https://code.claude.com/docs/en/mcp)
- [Output styles](https://code.claude.com/docs/en/output-styles)
