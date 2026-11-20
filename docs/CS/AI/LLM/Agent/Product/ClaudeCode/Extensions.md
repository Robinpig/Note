## Introduction

Claude Code 的扩展面有四层，都叠在核心 agentic loop 之上（见 [Architecture](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md?id=architecture)）：**skills**（补充知识）、**MCP servers**（接外部服务）、**plugins**（把上述成分打包分发）、**output styles**（改会话级的角色与文风）。此外 hooks（自动化工作流）见 [Hooks](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Hooks.md)，subagents 见 [Subagents](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Subagents.md)。

事实基线：`@anthropic-ai/claude-code` **2.1.326**，已按该版本的 CHANGELOG 把 `2.1.302` 基线以来的扩展面变更逐条对齐；官方 skills / plugins / mcp / output-styles 页（2026-10-18 核实）。

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

### Relation to the Legacy commands Format

**自定义命令已合并进 skills**：`.claude/commands/deploy.md` 与 `.claude/skills/deploy/SKILL.md` 等价（都创建 `/deploy`），旧文件继续可用；skill 多出支持文件目录、调用控制 frontmatter、自动加载三样能力。新工作一律用 skill 格式。

### Load Locations

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

几个跨来源的名字冲突规则：`--add-dir` 目录里的 skill 若因别的同名 skill 占位而不可达，会以 `<folder>:<name>` 提供（v2.1.309+）；嵌套 skill 在沙箱打开时，`.claude/skills` 下位于启动目录之下的目录只有从该目录启动或 `/cd` 进去才加载（v2.1.319+）。同名 skill/命令在一个位置重复时，`/`、`/skills`、`/plugin` 的列表也不再串行或丢光标（v2.1.326）。

### Dynamic Context Injection

SKILL.md 里 `!`command`` 行会在 Claude 看到内容**之前**被执行、并把输出内联防进来——官方的例子是在 skill 里写 ``!`git diff HEAD``` 让摘要指令带着真实 diff 到达。

v2.1.326 修掉了这个机制在 **Code Mode** 下的两处失败：auto mode 下内联 `!` 命令需要审批时，skill 与 slash command 曾加载失败，现在改为要求 Claude 去运行它；在 Code Mode 启动、预加载带内联 `!` 的 skill 的后台 subagent 也曾失败，现已修复。

### Skill Lifecycle And Reload

skill 列表与 hook 在会话生命周期里有几条值得记的行为（v2.1.304+）：压缩上下文后会**重新把 skill 列表发给 Claude**；`/reload-skills` 现在只发送**新增或改变**的 skill，而不是全量重发（此前插件在启动时重载会让续接会话和 cloud 会话每次都收到整份列表）。

hook 侧有两条硬边界与一处修复：同一来源（一个仓库、你自己的目录或一个插件）每个会话最多注册 **1,024 个 hook、16,384 个 matcher 字符**；一个 skill 的 `once` hook 运行后曾顺带删掉另一个 skill 里相同的 hook，现已修复。

### Bundled Skills

Claude Code 自带一批 prompt 型 bundled skills：`/doctor`（安装与配置体检）、`/code-review`、`/batch`、`/debug`、`/loop`、`/claude-api`（Claude API 参考材料，代码 import anthropic 时自动激活）、`/run` 与 `/verify`（启动并驱动 app 验证改动，`/run-skill-generator` 把项目的构建启动配方录成 per-project skill）、`/simplify`、`/workflow-authoring`（dynamic workflows 启用时）。`disableBundledSkills` 可整体关闭（`/doctor` 仍可键入，除非再设 `DISABLE_DOCTOR_COMMAND`）。

有个与提交相关的联动：会话启动时若存在名为 `verify` 或 `simplify` 的 skill（enterprise/personal/project/additional-dir 位置或 `.claude/commands/` 同名文件，bundled 与插件的不算），Claude Code 的提交指令会让 Claude 在**每次 commit 前跑它**（docs/tests 改动除外，v2.1.286+）。

`/claude-api` 这类 bundled skill 的正文也会随版本更新：2.1.326 起它默认教你在 **Managed Agents** 上搭 agent，除非你要自己托管 agent loop。

## Plugins

Plugin 是打包分发的单位：一个目录（带 `.claude-plugin/plugin.json` manifest）装上 skills、agents、hooks、MCP servers，一次安装整体生效。

- **mod**：hooks 写成 JavaScript 函数的插件，函数在 Claude Code 进程内运行、能画界面能加命令——它已是完整的编程平台（`$` 宿主对象、mod hook 事件族、managed settings 下的权力边界），单独立篇见 [Mods](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Mods.md)。
- **marketplace**：带 `.claude-plugin/marketplace.json` 的仓库/目录，是 catalog 不是 hosted store。官方 marketplace（`claude-plugins-official`）首次交互式终端会话自动添加；官方市场里可看每个插件的 **Context cost 预估**。
- **安装 scope**：user（本机所有项目）/ project（提交 `.claude/settings.json`，协作者各自安装）/ local（本仓库仅自己）。cloud session 不加载本地 settings 里的插件。
- **常驻成本**：插件里每个可被 Claude 自动调用的成分，其 name+description 每轮都在上下文里（计用量），全文只在被用时加载；MCP servers 随启用插件的每个会话常驻运行。
- 开发期不用 marketplace：`--plugin-dir` 直接加载本地文件夹。组织可经 managed settings allowlist/block marketplace、force-install 插件。
- `/plugin` 的 Discover 标签浏览安装；安装前三档市场（official / community / third-party）靠 marketplace 名区分，官方名只接受来自 `github.com/anthropics/` 的来源。
- `plugin.json` 可用 `engines["claude-code"]` 声明兼容的客户端版本区间，超出区间的插件不会被安装/更新/加载（v2.1.323+）。

## MCP

MCP server 给 Claude 接外部系统的工具（协议本身见 [MCP](/docs/CS/AI/LLM/Protocol/MCP.md)）。Claude Code 侧的关键事实：

- 四种添加方式：remote HTTP、remote SSE、local stdio、remote WebSocket；`claude mcp add` 一条命令搞定，也支持从写给别的 client 的 setup 指令导入。
- **工具定义默认延迟加载**：只把工具名与 server 指令放进上下文，Claude 真要用了才经 tool search 加载——这是控制 MCP 上下文成本的核心机制。
- 支持运行时动态工具更新（server 的 tool list 变了会反映）与自动重连。
- MCP 工具在 hooks 与权限系统里就是普通工具：命名 `mcp__<server>__<tool>`（匹配细节见 [Hooks](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Hooks.md)），可用 `permissions.deny` 按 `mcp__server__tool` 粒度管控。

**客户端代际（最高优先级纠偏）**：**v1 MCP 客户端已被移除**。`MCP_SDK_GENERATION=v1` 现在并不是切回旧客户端，而是以**兼容模式运行 v2 MCP 客户端**——更早的握手、放宽的 OAuth 登录检查（v2.1.323）。因此任何「v1 客户端仍在用 / 可切回 v1」的旧描述都不成立；该变量如今只是 v2 的兼容开关。作为对照，Bedrock、Vertex、Foundry 与关闭遥测的安装默认也用 v2 客户端 + `2026-07-28` 协商，`MCP_SDK_GENERATION=v1` 或 `MCP_PROTOCOL_NEGOTIATION=legacy` 可退回旧协商。

**工具调用后台化（v2.1.319+）**：MCP server 把工具调用作为 **task** 运行时，Claude Code 立即把它移到后台，完成再告知 Claude；设 `CLAUDE_CODE_DISABLE_MCP_TASK_BACKGROUND` 则改为在工具调用内等待。完全关闭 task 用 `CLAUDE_CODE_DISABLE_MCP_TASKS=1`。task 等待回答时会明确告诉 Claude（可指向 `/tasks`）；无人可问时按 Esc 相当于「稍后回答」，问题仍留在 `/tasks`。

**连接可靠性与结果隔离**：HTTP MCP 工具调用在连接中途断开时曾被**发送两次**，现只重试只读/幂等工具（v2.1.307）。并行 MCP 工具调用有两个长结果在同一毫秒到达时曾**互相读到对方的结果**——这暴露了结果缓存是按时间戳索引的（v2.1.326，anthropics/claude-code#105138）。带根 `anyOf` / `oneOf` 的 MCP 工具 schema 曾只向 Claude 展示第一个分支的参数形式，现可正确传其它分支（如文本 `42` 传给期望数字的分支）（v2.1.326）。tool search 按精确名查找时曾加载另一个 MCP server 的工具（v2.1.326）。

**鉴权与登录**：完成 MCP server 登录的工具现在即使在 bypass 和 auto 模式也**要求确认**；无人可问（如 `dontAsk` 模式）时要用 `/mcp`（v2.1.323）。MCP OAuth 请求在 server 重定向时曾把 refresh token 之类的机密发往另一主机，现已修复（v2.1.321）。

**上下文成本细节**：MCP 按需加载的工具在 `/context` 里每个 server 共用一行，直到被调用才展开（v2.1.319+）；cloud/Remote Control 里被组织屏蔽的工具会在 `/mcp` 行里用警告图标标出。

## Output Styles

Output style 是一组指令，设定整个会话里 Claude 的角色、语气与响应格式。除 Default（无 style，标准软工系统提示）外有四个内置：

| Style | 变化 |
| :--- | :--- |
| `Proactive` | 直接开干，常规决策自行假设而非停下来问；删数据/改共享或生产系统前仍会在对话里确认（这是指令不是权限提示） |
| `Concise` | 首句即结论，去掉铺垫与复述；简单问题 1~3 句（v2.1.237+）。错误报告、失败测试输出、安全告警、破坏性动作确认保持完整 |
| `Explanatory` | 代码前后加 `★ Insight` 块，解释选择背后的理由 |
| `Learning` | 同 Explanatory，并在有真实设计决策处留几行给你写（文件里标 `TODO(human)`） |

style 只是指令，不保证行为；它不改权限模式（Proactive 不改变哪些工具调用免问）。自定义 style 可以把它变成写作助手、数据分析师之类的非软工角色。

## Official Plugins From The Public Repo

官方插件的**开发仓已经迁走**：`anthropics/claude-code` 仓库的 `plugins/` 目录在 2.1.326 里只剩一份 `README.md`，官方插件改在 [`anthropics/claude-plugins-official`](https://github.com/anthropics/claude-plugins-official) 维护；本仓库的 `claude-code-plugins` marketplace 仍列出它们，并从那里安装。新插件一律提交到 `claude-plugins-official`。这与上文的内置 bundled skills 是不同层（这些需显式安装，内置 skill 随客户端分发）。

历史上随 `claude-code` 仓库 `plugins/` 分发的官方插件（与内置 bundled skills 不同层），其清单与用途如下——其中 `claude-opus-4-5-migration` 已**退役**（README 明示）：

| 插件 | 内容 |
| :--- | :--- |
| `frontend-design` | 自动调用的 skill，做出有辨识度、生产级的前端界面，避开通用 AI 审美 |
| `code-review` | `/code-review` 命令，5 个并行 Sonnet agent 做 CLAUDE.md 合规 / bug / 历史 / PR 历史 / 注释审查 |
| `pr-review-toolkit` | `/pr-review-toolkit:review-pr`，多视角 PR 审查 agent（注释、测试、错误、类型、质量、简化） |
| `commit-commands` | `/commit`、`/commit-push-pr`、`/clean_gone` 等 git 工作流命令 |
| `feature-dev` | `/feature-dev` 七阶段功能开发工作流，配 `code-explorer` / `code-architect` / `code-reviewer` agent |
| `agent-sdk-dev` | `/new-sdk-app` 新建 Agent SDK 项目，配 verifier agent |
| `plugin-dev` | 插件开发工具箱，8 阶段 `/plugin-dev:create-plugin` + 7 个专家 skill |
| `hookify` | `/hookify` 系列命令，按对话模式或显式指令自动生成 hook 防不当行为 |
| `ralph-wiggum` | `/ralph-loop` 自主迭代循环，同一任务反复跑到完成 |
| `security-guidance` | PreToolUse hook，编辑文件时警示命令注入 / XSS / eval / pickle 等 9 类安全问题 |
| `explanatory-output-style` | SessionStart hook，注入教学性上下文（复刻已弃用的 Explanatory style） |
| `learning-output-style` | SessionStart hook，决策点请你写 5~10 行代码（复刻未发布的 Learning style） |

## Links

- [ClaudeCode 主枢纽](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md)
- [Skill 理论篇](/docs/CS/AI/LLM/Agent/Theory/Skill.md)
- [MCP 协议](/docs/CS/AI/LLM/Protocol/MCP.md)
- [Mods](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Mods.md)

## References

- [Claude Code skills](https://code.claude.com/docs/en/skills)
- [Claude Code plugins](https://code.claude.com/docs/en/plugins)
- [Connect Claude Code to tools via MCP](https://code.claude.com/docs/en/mcp)
- [Output styles](https://code.claude.com/docs/en/output-styles)
- [anthropics/claude-plugins-official](https://github.com/anthropics/claude-plugins-official)
- [Code Mode](https://code.claude.com/docs/en/code-mode)
