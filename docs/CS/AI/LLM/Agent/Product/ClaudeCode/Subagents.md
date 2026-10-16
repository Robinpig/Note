## Introduction

Subagents 是 Claude Code 的任务卸载机制：把一个会往主对话里灌搜索结果、日志、文件内容的旁支任务，丢给一个**独立上下文窗口**里跑的专门 agent，它干完只把摘要带回来。往上是 agent teams——多个 teammate 组成的协作团队。两者都建立在 Task/Agent 工具之上，本文覆盖定义方式、内置类型、团队架构与权限语义。

事实基线：`@anthropic-ai/claude-code` **2.1.301**（2026-10-15），官方 sub-agents / agent-teams 页（2026-10-16 核实）。

## What A Subagent Is

每个 subagent 跑在自己的上下文窗口里，带自定义系统提示、特定工具集与独立权限；它自己发请求，**计入与主对话相同的用量限额**。Claude 按各 subagent 的 description 决定何时委派——所以 description 要写清「什么时候用我」。

description 也占上下文（每轮都在），自定义 subagent 的 description 合计超过 **15,000 tokens** 时启动告警；细节应写进 subagent 的 system prompt（只在它运行时才加载）。

相邻概念的分界：

| 机制 | 形态 |
| :--- | :--- |
| subagent | 单会话内委派，独立上下文，结果摘要回主对话 |
| background agents | 多个独立会话并行，一处总览 |
| cross-session messaging | 独立会话之间互发消息 |
| agent teams | Claude 拉起并监督的协调团队 |

## Built-In Subagents

| 类型 | 模型 | 工具 | 用途 |
| :--- | :--- | :--- | :--- |
| `Explore` | 主对话模型（Fable 会话按连接方式分流） | 只读，Write/Edit 被拒 | 文件发现、代码搜索、代码库探索 |
| `Plan` | 继承主对话 | 只读 | plan mode 下的规划前研究 |
| `general-purpose` | 主对话模型 | subagent 可用的全部工具 | 复杂研究、多步操作、代码修改 |
| `claude` | 按模型顺序 | subagent 可用全部工具 | 兜底；也是 background session 的默认 agent |
| `statusline-setup` | Sonnet | — | `/statusline` 配置时用 |
| `claude-code-guide` | Haiku | — | 回答 Claude Code 功能问题 |

- `Explore` 与 `Plan` **启动时不带你的 CLAUDE.md 与 git status 快照**，保持研究快而便宜；其他内置与自定义 subagent 默认都带（自定义定义里设 `omitClaudeMd` 可去掉）。
- Claude 调 `Explore` 时会指定 thoroughness：`quick`（定点查找）/ `medium` / `very thorough`（全面分析）。
- 自定义一个叫 `Explore` 的 user/project subagent 会覆盖内置的那个，可借它把探索跑到便宜模型上（`model: haiku`）。

限制手段：`permissions.deny` 里加具体类型可屏蔽某个内置类型；deny 掉 Agent 工具本身可禁止一切委派；`CLAUDE_CODE_DISABLE_EXPLORE_PLAN_AGENTS=1`（v2.1.198+）只移除 Explore 与 Plan；非交互模式与 Agent SDK 里 `CLAUDE_AGENT_SDK_DISABLE_BUILTIN_AGENTS=1` 移除全部内置类型。`CLAUDE_CODE_SUBAGENT_MODEL` 可给所有 subagent 强制一个模型。

## Define Your Own

Subagent 是带 YAML frontmatter 的 Markdown 文件：

```
---
name: code-improver
description: Scans files and suggests improvements... Use after writing or modifying code.
tools: Read, Grep, Glob
model: sonnet
---

You are a code improvement specialist...
```

文件位置决定可见范围，同名时高优先级位置胜出：

| 位置 | 作用域 | 优先级 |
| :--- | :--- | :--- |
| managed settings | 组织 | 1（最高） |
| `--agents` CLI flag | 当前会话 | 2 |
| `.claude/agents/` | 当前项目 | 3 |
| `~/.claude/agents/` | 本机所有项目 | 4 |
| 插件的 `agents/` 目录 | 插件启用处 | 5（最低） |

项目级 subagent 从 cwd 向上逐级扫描 `.claude/agents/`，同名取**最靠近工作目录**的那份；`.claude/agents/` 与 `~/.claude/agents/` 都递归扫描，子目录路径不影响身份（身份只来自 frontmatter 的 `name`）。同一目录下两个文件声明同名 `name` 只会加载一个（按文件系统读序，无文档化优先级），`/doctor` 会报这种冲突。

除 `tools`/`model` 外，frontmatter 还支持 `disallowedTools`、`effort`、`autoCompactWindow` 等字段；定义可以通过插件分发。

## Agent Teams

Agent teams 是 subagent 之上的协作形态：**team lead**（主会话，负责拉人与协调）+ **teammates**（各自独立的 Claude Code 实例）+ **shared task list** + **mailbox**。

### Architecture

| 组件 | 落点 |
| :--- | :--- |
| Team config | `~/.claude/teams/{team-name}/config.json`（members 数组带 name/agent ID，lead 的 agent type 恒为 `team-lead`） |
| Mailbox | `~/.claude/teams/{team-name}/inboxes/{agent-name}.json`，读时逐条校验格式，非法条目报错后移除 |
| Task list | `~/.claude/tasks/{team-name}/`，本地持久、从不上传 |

team 名形如 `session-` + 会话 ID 前 8 位；team config 目录会话结束即删，task list 目录按 `cleanupPeriodDays` 的保留规则清理。任务依赖自动管理：被依赖任务完成时，依赖它的任务自动解锁。**没有项目级的 team config**——仓库里放 `.claude/teams/teams.json` 不会被当配置。

### How Teams Form

agent teams 启用后，Claude 调 Agent 工具时带 name 就拉起一个 teammate（无需你确认）；Claude 也会主动给普通 subagent 起名以便之后消息它们——**所以团队可能在你没要求时形成**，只要 subagent 就关掉 agent teams。

### Permissions

- teammate 默认继承 lead 的权限模式，**`dontAsk` 不继承**；lead 带 `--dangerously-skip-permissions` 时全部 teammate 都带。
- teammate 的权限提示出现在 lead 会话里（在那儿批准）；**plan approval 是设计上的例外**——lead 会话直接授予 teammate 的计划批准，不另弹提示。
- **agent 之间的消息不可作为授权**：接收方被告知消息来自另一个 Claude 会话而不是你；teammate 不能代你批准权限提示，被拒的 teammate 也不能把动作转给另一个 teammate 绕过检查。auto mode 下 classifier 对每条 agent 间消息做两个检查：转述来的批准声明当不可信输入；消息（含 shutdown 请求、plan approval 响应这类结构化协议消息）送达前逐一审查，拦下的消息不到达接收方。

### Context And Cost

每个 teammate 独立上下文窗口，启动时加载与普通会话相同的项目上下文（CLAUDE.md、MCP servers、skills）+ lead 的 spawn prompt；**lead 的对话历史不带过去**。teammate 可复用 subagent 定义（`tools`/`model`/`disallowedTools`/`effort`/`body` 等按定义套用，`skills` 字段两模式都不套用）。

成本上，teammate 越多 token 用量显著上升（各自上下文窗口）；in-process teammate 的请求不落在主对话的 cache TTL 桶里，默认缓存只保 5 分钟，`subagentPromptCacheTtl: "1h"` 可保一小时（API 侧 1 小时缓存写入计费更贵）。

### Team Operations

- 显示模式可选（split-pane / in-process），`/teams` 相关命令控制；teammate 完成时自动通知 lead 并附最终答案，API 错误则报失败与错误文本。
- 直接点名给某个 teammate 发消息；广播要逐个发。
- 用 subagent 定义声明可复用的 teammate 角色（security-reviewer、test-runner 之类，一处定义两处复用）。
- hooks 可给团队上质量门（TeammateIdle 等事件）。

典型用法：并行 code review（一个 teammate 看安全、一个看性能、一个看测试覆盖——各自一个视角避免重叠）、竞争假设调查（多个 teammate 同时验证互相排斥的假设）。

## Links

- [ClaudeCode 主枢纽](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md)
- [Architecture](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Architecture.md)
- [Permission 产品篇](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Permission.md)
- [Codex Multi-Agent](/docs/CS/AI/LLM/Agent/Product/Codex/MultiAgent.md)

## References

- [Claude Code subagents](https://code.claude.com/docs/en/sub-agents)
- [Agent teams](https://code.claude.com/docs/en/agent-teams)
