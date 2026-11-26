## Introduction

Subagents 是 Claude Code 的任务卸载机制：把一个会往主对话里灌搜索结果、日志、文件内容的旁支任务，丢给一个**独立上下文窗口**里跑的专门 agent，它干完只把摘要带回来。往上是 agent teams——多个 teammate 组成的协作团队。两者都建立在 Task/Agent 工具之上，本文覆盖定义方式、内置类型、团队架构与权限语义。

事实基线：`@anthropic-ai/claude-code` **2.1.326**（CHANGELOG 2.1.302→2.1.326 区间与 `mods/types/claude-code.d.ts` 本次核实）；官方 sub-agents / agent-teams 页（2026-10-18 核实）。

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

模型与后台行为在 2.1.302 之后有几处纠偏，关系到「subagent 实际用什么模型、后台结果怎么回收」：

- `managed settings` 里设置的 subagent 模型此前在 Claude Desktop 的 Code tab 不生效，2.1.326 起它覆盖你自己的设置（与终端一致），除非那份 `managed settings` 同时指定了 provider 或 gateway。
- 模型设置是 `opusplan` / `haiku` 时，自带 `model` 的 subagent 此前会被挪到 plan mode 的模型，2.1.325 修复；不同模型的 subagent 此前用主会话模型估算文件读取与 MCP 结果的大小，2.1.325 也一并修复。
- 后台 subagent 的汇报链路：2.1.326 修掉后台服务因进程号被复用而误杀你自己进程（如 SSH 登录）的问题；2.1.321 起 headless / Desktop / VS Code 中集中等待的后台 subagent 报告合并为一次模型调用回答（与终端一致），同一版本修复 auto mode 下压缩发生在 Claude 回答之前时丢失「已开启一个 turn 的后台汇报」；2.1.319 修复 hand-back 报告在非 verbose 模式展开时露出内部标记与 provenance note；2.1.317 起给运行中的后台 agent 发 `SendMessage` 时消息更早到达——它正在执行的命令移到后台而不被停掉。

### Agent Identity In Hooks

`mods/types/claude-code.d.ts` 的 `BaseHookInput` 是各 hook 事件的公共输入，其中两个字段专门标记「这次 hook 是不是从 subagent 里触发的」。真实片段：

```typescript
      permission_mode?: string;
      /**
       * Subagent identifier. Present only when the hook fires from within a subagent (e.g., a tool called by an AgentTool worker). Absent for the main thread, even in --agent sessions. Use this field (not agent_type) to distinguish subagent calls from main-thread calls.
       */
      agent_id?: string;
      /**
       * Agent type name (e.g., "general-purpose", "code-reviewer"). Present when the hook fires from within a subagent (alongside agent_id), or on the main thread of a session started with --agent (without agent_id).
       */
      agent_type?: string;
```

要点：`agent_id` 只在 subagent 内部触发的 hook 中出现，主线程缺席（即便用 `--agent` 启动），所以**区分 subagent 调用要看 `agent_id` 而不是 `agent_type`**；`agent_type` 在 subagent 里与 `agent_id` 同时出现，在 `--agent` 主线程里单独出现。`SubagentStart` / `SubagentStop` 这类事件则把 `agent_id` 与 `agent_type` 作为必填字段带上。

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

## Fork 型子代理

`subagent_type: "fork"` 的子代理启动时带一份主对话的上下文副本（普通子代理不带历史），适合需要完整上下文的旁支任务。[枢纽 Sessions 小节](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md?id=sessions-context-checkpoints) 提到它是唯一启动即带对话副本的子代理类型。

v2.1.302 起，fork 子代理在 `claude -p`、Agent SDK、桌面 app 与 VS Code 中**默认开启**（终端此前已默认）；`CLAUDE_CODE_FORK_SUBAGENT=0` 可整体关闭，`claude mcp serve` 永不提供 fork 子代理。

版本纠偏：v2.1.307 起同时启动的多个 fork 子代理各自会被告知「哪一次启动是它自己」，大幅减少 fork 互相去启动对方工作；v2.1.319 起 subagent hand-back 报告在 verbose 之外展开时不再露出内部标记与 provenance note；v2.1.323 起 safeguards 停掉 forked skill / workflow agent 后，Claude 被要求改用更窄的 prompt 重试或告知你，而不是自己接手做掉。

## Agent Teams

Agent teams 是 subagent 之上的协作形态：**team lead**（主会话，负责拉人与协调）+ **teammates**（各自独立的 Claude Code 实例）+ **shared task list** + **mailbox**。

### Architecture

| 组件 | 落点 |
| :--- | :--- |
| Team config | `~/.claude/teams/{team-name}/config.json`（members 数组带 name/agent ID，lead 的 agent type 恒为 `team-lead`） |
| Mailbox | `~/.claude/teams/{team-name}/inboxes/{agent-name}.json`，读时逐条校验格式，非法条目报错后移除 |
| Task list | `~/.claude/tasks/{team-name}/`，本地持久、从不上传 |

team 名形如 `session-` + 会话 ID 前 8 位；team config 目录会话结束即删，task list 目录按 `cleanupPeriodDays` 的保留规则清理。任务依赖自动管理：被依赖任务完成时，依赖它的任务自动解锁。**没有项目级的 team config**——仓库里放 `.claude/teams/teams.json` 不会被当配置。

worktree 与 transcript 落点的几处收紧：v2.1.326 起，被隔离进 worktree 的 subagent 在**任何仓库**里都会拒绝 Bash 中可能改写与你 checkout 共享分支的 git 命令（普通会话不受影响），且 `ExitWorktree` 在后台 subagent 或 shell 命令仍可能运行于其中时拒绝移除该 worktree，除非 Claude 传 `discard_changes`。v2.1.323 起 worktree 创建拒绝 `.git` 目录是链接或含硬链接的 checkout（如 git-new-workdir 布局、`cp -al` 副本），要求用普通 clone；同一版本修复了 subagent transcript 与大工具结果在进入由 `WorktreeCreate` hook 创建的 worktree 或嵌套仓库后被另存到会话 transcript 之外的问题。

### How Teams Form

agent teams 启用后，Claude 调 Agent 工具时带 name 就拉起一个 teammate（无需你确认）；Claude 也会主动给普通 subagent 起名以便之后消息它们——**所以团队可能在你没要求时形成**，只要 subagent 就关掉 agent teams。

v2.1.326 起 Code Mode 与 agent teams 可以同时开启——此前已打开 Code Mode 的会话，若带 teams 启动，现在直接从 Code Mode 开始。

### Permissions

- teammate 默认继承 lead 的权限模式，**`dontAsk` 不继承**；lead 带 `--dangerously-skip-permissions` 时全部 teammate 都带。
- teammate 的权限提示出现在 lead 会话里（在那儿批准）；**plan approval 是设计上的例外**——lead 会话直接授予 teammate 的计划批准，不另弹提示。
- **agent 之间的消息不可作为授权**：接收方被告知消息来自另一个 Claude 会话而不是你；teammate 不能代你批准权限提示，被拒的 teammate 也不能把动作转给另一个 teammate 绕过检查。auto mode 下 classifier 对每条 agent 间消息做两个检查：转述来的批准声明当不可信输入；消息（含 shutdown 请求、plan approval 响应这类结构化协议消息）送达前逐一审查，拦下的消息不到达接收方。
- split-pane 的 teammate 自 v2.1.323 起会校验请求是否来自自己的 team lead：leader 结束后，它发出的请求会被拒；plan 批准在 `/clear` / `/resume` 之后必须重发。

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
- [Architecture](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md?id=architecture)
- [Permission 产品篇](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Permission.md)
- [Codex Multi-Agent](/docs/CS/AI/LLM/Agent/Product/Codex/MultiAgent.md)

## References

- [Claude Code subagents](https://code.claude.com/docs/en/sub-agents)
- [Agent teams](https://code.claude.com/docs/en/agent-teams)
