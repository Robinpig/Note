## Introduction

Claude Code 的记忆分两套互补机制，都在每次会话开始时加载：

- **CLAUDE.md 文件**：你写的持久指令（项目规范、工作流、架构上下文）。
- **Auto memory**：Claude 自己根据你的纠正与偏好写的笔记。

外加两套相邻能力：`.claude/rules/` 把指令按路径拆分，AGENTS.md 支持让你复用给别的编码 agent 写的指令文件。压缩与上下文窗口的通用原理见 [Compaction](/docs/CS/AI/LLM/Agent/Theory/Compaction.md)，本文讲 Claude Code 的实现。

事实基线：`@anthropic-ai/claude-code` **2.1.301**（2026-10-15），官方 memory 页（2026-10-16 核实）。

## CLAUDE.md vs Auto Memory

| | CLAUDE.md | Auto memory |
| :--- | :--- | :--- |
| 谁写 | 你 | Claude |
| 内容 | 指令与规则 | 学到的模式与偏好 |
| 作用域 | 项目 / 用户 / 组织 | 每仓库，跨 worktree 共享 |
| 加载量 | 全部 | 每会话前 200 行或 25KB（先到为准） |
| 用途 | 编码标准、工作流、项目架构 | 你的偏好、你给的纠正、代码里推不出的项目上下文 |

⚠️ 两者都是 **context 不是 enforced configuration**——Claude 把它们当上下文而非强制配置对待。要无条件阻断某个动作，用 `PreToolUse` hook（见 [Hooks](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Hooks.md)），不要指望 CLAUDE.md。

subagent 也可以维护自己的 auto memory。

## Four Scopes

CLAUDE.md 按作用域分四层，加载顺序从宽到窄：

| 作用域 | 位置 | 共享 |
| :--- | :--- | :--- |
| Managed policy | macOS `/Library/Application Support/ClaudeCode/CLAUDE.md`；Linux/WSL `/etc/claude-code/CLAUDE.md`；Windows `C:\Program Files\ClaudeCode\CLAUDE.md` | 组织全员，个人设置无法排除 |
| User | `~/.claude/CLAUDE.md` | 仅自己，所有项目 |
| Project | `./CLAUDE.md` 或 `./.claude/CLAUDE.md` | 团队，随版本控制提交 |
| Local | `./CLAUDE.local.md` | 仅自己当前项目，应进 .gitignore |

managed settings 里也可以直接用 `claudeMd` 键写组织级指令（只在 managed/policy settings 里生效）。**managed 层与个人 settings 层的分工**：settings（`permissions.deny`、`sandbox.enabled`、`env`、`forceLoginMethod`）是客户端强制的技术面；CLAUDE.md 是行为引导，不是硬强制层。

## How Files Load

加载语义是**拼接而非覆盖**：

- 从**当前工作目录及每一级上级目录**加载 `CLAUDE.md` 与 `CLAUDE.local.md`，全部串接进上下文；顺序从文件系统根到工作目录，所以越靠近启动目录的指令越晚被读到。
- 每个目录内 `CLAUDE.local.md` 接在 `CLAUDE.md` 之后——个人备注是该层级 Claude 最后读到的东西。
- 工作目录**子目录**里的 CLAUDE.md 不随启动加载：Claude 读/写/编辑该子目录里某个文件时才加载（Bash 里 `cat`/`head` 单文件也算读）。
- 块级 HTML 注释（`<!-- ... -->`）在注入上下文前被剥掉，代码块内的注释保留——可以用来给人写维护备注而不花 token。
- monorepo 里被别的团队的 CLAUDE.md 打扰，用 `claudeMdExcludes` 按路径/glob 跳过。

### Import 语法

CLAUDE.md 里可以用 `@path/to/file` 导入其他文件，导入的文件在启动时连同宿主文件一起展开加载：

- 相对路径**相对包含 import 的文件**解析，不是相对工作目录；可递归导入，**最多 4 跳**。
- 路径含空格时每个空格前加反斜杠；带引号的路径不会被导入。
- **代码跨度与围栏代码块内的 `@` 不解析**——想提路径而不导入，用反斜杠号包起来。
- 解析到工作目录外的 **external import** 首次出现时有审批对话框（列文件、可拒绝）；user 级文件（`~/.claude/CLAUDE.md`、`~/.claude/rules/`）的导入免审批，Cowork 会话除外。

### Rules

`.claude/rules/` 把指令拆成主题文件，支持用 frontmatter 的 `paths` 字段按 glob 限定生效范围：

```
---
paths:
  - "src/api/**/*.ts"
  - "lib/**/*.ts"
---
```

- 无 `paths` 的 rule 随启动加载，优先级与 `.claude/CLAUDE.md` 相同；path-scoped rule 在 Claude 用 Read/Write/Edit 碰匹配文件（或 Bash 读它）时才加载。
- `paths` 是 rule 的**唯一** frontmatter 字段，别的字段被静默忽略；YAML 解析失败则当作无 `paths` 加载。
- glob 花括号展开有预算：整个 `paths` 列表共享 **1000 个展开模式与 4 MiB**，超预算的模式按未展开字面量使用（其字面花括号匹配不到任何文件）。
- `.claude/rules/` 支持 symlink，可跨项目共享一套规则；指向工作目录外的 symlink 按 external import 对待（需审批，且审批后只加载无 `paths` 的）；指向网络路径（UNC、`/net`）的链接**不加载**。
- user 级规则放 `~/.claude/rules/`，对本机所有项目生效，加载在项目规则之前。

## Auto Memory

Claude 会在你纠正它、表达偏好时自动把学到的东西写进每仓库的 memory 文件（`MEMORY.md`），**跨 worktree 共享**，每会话加载前 200 行或 25KB。它补的是 CLAUDE.md 的反面：你反复解释的东西写进 CLAUDE.md，Claude 自己该长记性的东西交给 auto memory。

## AGENTS.md

Claude Code 原生读仓库里的 AGENTS.md——那是给别的编码 agent 用的开放指令文件格式。何时读、与 CLAUDE.md 的差异（AGENTS.md 支持不可用时怎么办、怎么选加载哪个、如何与用同一文件的其他工具共存）官方有专门一节；核心规则是：仓库有 AGENTS.md 时 Claude 可以拿它当 CLAUDE.md 用，两者并存时的取舍见官方 AGENTS.md 页。

## Compaction And Context

上下文窗口装着对话历史、文件内容、命令输出、CLAUDE.md、auto memory、已加载 skill 与系统指令。装满时自动管理：**先清较早的工具输出，不够再总结对话**。要点：

- 模型侧基线：Sonnet 5/5.5、Fable 5/5.1、Opus 4.7 及以上**原生 1M 窗口**（无 `[1m]` 变体名），自动压缩默认在约 **967K token** 触发；旧的「200K」说法已过时。
- `/compact` 手动触发，`PreCompact` / `PostCompact` 两个 hook 事件可介入前后；官方建议别抢在自动压缩之前手动 compact，留给任务间的自然断点。
- 想控制压缩保留什么，在 CLAUDE.md 里加「Compact Instructions」一节，或 `/compact focus on the API changes` 带焦点压缩。
- 单个文件/工具输出大到每次总结后立刻填满上下文时，Claude Code 尝试几次后停止自动压缩并报 thrashing 错误。
- `/context` 看空间占用；MCP 工具定义默认延迟加载，skill 按需加载——两者都不进常驻上下文。

细节（触发公式、保留策略、压缩与 skill 状态的关系、各家对比）见 [Compaction 理论篇](/docs/CS/AI/LLM/Agent/Theory/Compaction.md)。

## Working With Memory Files

- `/init` 生成起始 CLAUDE.md（已有时给改进建议而非覆盖）；`CLAUDE_CODE_NEW_INIT=1` 走多阶段交互流程。
- `/doctor prompt-audit`（v2.1.283+）让 Claude 审查指令文件的过时/冲突内容，先出报告、你点头才改。
- 写有效指令的要点：具体到可验证（「用 2 空格缩进」而非「正确格式化代码」）、单文件控制在 200 行内、相关指令归组、矛盾指令定期清理。
- 让 Claude 自己更新记忆：对话里直接指示（「把这个架构决策记到根目录的 CLAUDE.md」）。
- `@` 符号在对话中把文件拉进当前会话短期记忆；`/context` 的 Memory files 一节可确认 CLAUDE.md 确实加载了。

## Links

- [ClaudeCode 主枢纽](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md)
- [Compaction 理论篇](/docs/CS/AI/LLM/Agent/Theory/Compaction.md)
- [Hooks](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Hooks.md)
- [Skill 理论篇](/docs/CS/AI/LLM/Agent/Theory/Skill.md)

## References

- [Claude Code memory](https://code.claude.com/docs/en/memory)
- [Explore the context window](https://code.claude.com/docs/en/context-window)
