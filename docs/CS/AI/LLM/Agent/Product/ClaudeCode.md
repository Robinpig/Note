## Introduction

Claude Code 是 Anthropic 官方推出的命令行工具，让你可以在终端中直接与 Claude 进行交互，完成代码编写、调试、重构等任务



## Installation

[Claude Code 一键安装](https://claude-zh.cn/guide/getting-started)



Mac
```shell
brew install --cask claude-code
```







## Commands

1 /plan - 先规划再执行

这是最重要的命令。不要上来就让 Claude 写代码，先让它分析需求、出方案。

\# 进入规划模式 /plan # Claude 会先分析，给出实施步骤 # 你确认后再执行

**为什么要这样做？**避免方向错误，减少返工。复杂任务必须用！

2 /compact - 压缩上下文

对话太长时，Claude 会变慢。用这个命令压缩历史记录，保留关键信息。

/compact

**使用时机：**对话超过 50 轮，或者 Claude 响应变慢时。
## Hooks

> **核实于 2026-10-05**（来源 [Claude Code Hooks reference](https://code.claude.com/docs/en/hooks)）：**当前支持 33 个 hook event**，常见的三类只是入门。配置按 `hook event → matcher group → hook handler` 三层嵌套写在 settings JSON 里。

最常用的三个：

```text
PostToolUse  编辑文件后自动 prettier
PreToolUse   git push 前自动检查
Stop         会话结束前清理临时文件
```

### Complete Event Table

按生命周期分组，挑有代表性的：

| 分组 | 事件 |
| :--- | :--- |
| 会话生命周期 | `SessionStart`、`SessionEnd`、`Setup`、`InstructionsLoaded` |
| 提示与工具 | `UserPromptSubmit`、`PreToolUse`、`PostToolUse`、`PostToolUseFailure`、`PostToolBatch`、`PermissionRequest`、`PermissionDenied` |
| 子 agent 与任务 | `SubagentStart`、`SubagentStop`、`TaskCreated`、`TaskCompleted`、`TeammateIdle` |
| 上下文与模型 | `PreCompact`、`PostCompact`、`PreModelSwitch`、`PostModelSwitch` |
| 环境与文件 | `CwdChanged`、`DirectoryAdded`、`FileChanged`、`ConfigChange` |
| git worktree | `WorktreeCreate`、`WorktreeRemove` |
| MCP 与交互 | `Elicitation`、`ElicitationResult`、`Notification`、`MessageDisplay` |

> `InstructionsLoaded` 在 `CLAUDE.md` 或 `.claude/rules/*.md` 被载入上下文时触发——会话启动时、以及会话中被懒加载时都会触发。`CwdChanged` 在 Claude 执行 `cd` 改变工作目录时触发，适合配合 direnv 做响应式环境管理。

### Easy Pitfalls

- **不是所有事件都支持 `matcher`**。`UserPromptSubmit`、`Stop`、`CwdChanged`、`TaskCreated` 等十个事件每次触发都执行，给它们加 `matcher` 会被**静默忽略**——不报错，只是没用。
- **`matcher` 的匹配语义会随字符变化**：只含字母数字与 `_ - 空格 , |` 时按精确字符串（支持 `|` 或 `,` 分隔的列表）匹配；一旦出现其他字符，就当**未锚定的 JS 正则**处理，于是 `Edit.*` 会连 `NotebookEdit` 一起匹配，要精确匹配必须写 `^Edit$`。`FileChanged` 与 `StopFailure` 的匹配字符集更窄，只有字母数字与 `_`、`|`。
- **`if` 与 `matcher` 不是一回事**：`matcher` 过滤事件本身，`if` 在单个 handler 上做二次过滤，用的是 permission rule 语法（如 `Bash(git *)`）。**`if` 只在工具类事件上评估**（`PreToolUse`、`PostToolUse`、`PostToolUseFailure`、`PermissionRequest`、`PermissionDenied`），其他事件上设置它 hook 不运行；而且一个 handler 只能写一条 rule，不支持 `&&`、`||` 或列表语法。
- **handler 有五种类型**：`command`、`http`、`mcp_tool`、`prompt`、`agent`。默认 timeout 差异很大——`command`/`http`/`mcp_tool` 是 600 秒，`prompt` 是 30 秒，`agent` 是 60 秒。`SessionEnd` 是例外：**所有 hook 共享 1.5 秒总预算**，单 hook 设再长总预算最高也只提到 60 秒。
- **配置分层是合并而非覆盖**。`~/.claude/settings.json`（仅本机）、`.claude/settings.json`（可提交）、`.claude/settings.local.json`（通常进 gitignore）、managed policy、插件的 `hooks/hooks.json`、skill 与 subagent 的 frontmatter——多个 settings 文件里定义的同一 handler 只跑一次，但插件或 skill 内独立定义的同一 handler 算另一份。
- **`command` handler 的 `args` 决定是否走 shell**：设了 `args` 就用 exec form 直接启动 executable，不经 shell；省略则由 shell 解释变量、管道、`&&`、重定向与 glob。引用路径占位符（`${CLAUDE_PROJECT_DIR}` 等）时官方建议用 `args`，避免 shell 二次解析。
- **`once: true`** 只在 skill frontmatter 里生效，在 settings 文件与 agent frontmatter 会被忽略。
- `EndConversation` 是工具行为不是 hook event——它的调用会跳过 `PreToolUse` 与 `PostToolUse`。

### Common Hook Recipes

**自动格式化：**编辑 .ts/.tsx 文件后自动运行 prettier

**类型检查：**编辑后自动运行 tsc 检查类型错误

**Git 拦截：**push 前弹出确认框，让你再检查一遍

**桌面通知：**Claude 等待输入时发送通知

## Permission

> 核实于 2026-10-05（来源 `code.claude.com/docs/en/permissions`）。当前是**六个**模式，不是四个。机制层面的通用原理（沙箱形态、审批粒度、fail-closed）见 [权限与沙箱](/docs/CS/AI/LLM/Agent/Theory/Permission.md)。

Claude Code 的权限模式决定「哪些操作可以直接做，哪些要问你」：

| 模式 | 自动批准情况 |
| :--- | :--- |
| `default` | 否。首次使用每个工具时通常询问（CLI 里标注为 Manual，`manual` 是它的别名） |
| `acceptEdits` | 部分自动。工作目录与 `additionalDirectories` 内的文件编辑，以及 `mkdir`/`touch`/`mv`/`cp` 等常见文件命令 |
| `plan` | 部分且有条件。可读文件、跑只读 shell 命令探索，**不编辑源文件**；`auto` 可用时分类器批准的额外命令也会跑 |
| `auto` | 条件式。不再逐项提示，但 shell 命令与网络请求执行前由**后台分类器**判断是否符合你的请求 |
| `dontAsk` | **不自动批准，而是自动拒绝**。原本会提示的调用一律拒；无需批准的操作（工作目录内读文件）与已通过 `/permissions`、`permissions.allow` 预批准的工具仍会跑 |
| `bypassPermissions` | 基本全放行。**但仍存在任何模式都不会自动批准的操作**——官方要求只在容器或虚拟机等隔离环境里用 |

⚠️ **`auto` 与 `dontAsk` 是最容易被误解的两个**：`auto` 的后台分类器审查不等于无条件放行（这是本库早期版本缺失记录的模式），而 `dontAsk` 字面像「不询问就放行」，**实际是「不询问就拒绝」**——语义完全相反。

`bypassPermissions` 也不是万能钥匙，文档明确有「任何模式都不会自动批准」的操作清单，所以它不能替代沙箱。

## Memory

Claude Code 的记忆系统主要可以分为三大核心模块：长期持久记忆（CLAUDE.md）、短期工作记忆（会话上下文），以及环境感知记忆（隐式状态）

### Memory Architecture

#### Long-Term Persistent Memory

这是 Claude Code 记忆系统中最核心、最具特色的部分。它通过读取 Markdown 文件来为 AI 注入“长期记忆”，这些记忆会在每次启动新会话时自动加载。
CLAUDE.md 采用了分层加载机制，优先级从低到高（或从全局到局部）如下：
1. 全局记忆 (Global Memory)
路径：~/.claude/CLAUDE.md
作用：存储适用于你所有项目的个人通用偏好。
示例内容：
“我总是使用中文与你交流。”
“在解释代码时，请先给出核心思路，再给出代码。”
“我偏好使用函数式编程范式。”
2. 项目记忆 (Project Memory)
路径：<项目根目录>/CLAUDE.md
作用：存储整个项目级别的规范、架构和上下文。强烈建议将此文件提交到 Git，这样团队中的所有成员在使用 Claude Code 时都能共享同一套“项目记忆”。
示例内容：
项目技术栈说明（如：Next.js 14, TailwindCSS, Prisma）。
核心目录结构说明。
构建、运行、测试的具体命令（如：pnpm run test:unit）。
代码风格指南和架构决策记录（ADR）。
3. 目录级记忆 (Directory Memory)
路径：<特定子目录>/CLAUDE.md
作用：当你在特定子目录下工作，或者让 Claude 操作该目录下的文件时，它会加载该目录专属的记忆。适合用于复杂 monorepo 中不同模块的特定规则。
4. 本地/个人项目记忆 (Local/Personal Memory)
路径：.claude/CLAUDE.md （位于项目根目录下）
作用：存储仅属于你个人、不想提交到 Git 共享的项目特定偏好。例如你个人的调试习惯、临时的上下文提示等。这个文件应该被加入到 .gitignore 中。

#### Short-Term Working Memory


这是 Claude Code 在当前终端会话中的“工作记忆”，用于维持多轮对话的连贯性。
1. 对话与工具调用历史
Claude Code 会记住你在当前会话中说过的话，以及它执行过的所有工具调用结果（如读取的文件内容、执行的终端命令输出、搜索代码的结果）。
2. 上下文窗口与自动压缩 (Context Compaction)
超大上下文：Claude Code 随模型拿到不同窗口——**Sonnet 5/5.5、Fable 5/5.1、Opus 4.7 及以上原生 1M**（无 `[1m]` 变体名），自动压缩默认在约 **967K token** 触发。旧的「200K」说法已过时。
自动压缩机制：上下文接近窗口极限时自动触发，后台总结历史、提取核心决策与关键代码修改、遗忘冗长中间推理。`/compact` 可手动触发，`PreCompact` / `PostCompact` 两个 hook 事件可介入其前后。官方建议**别抢在自动压缩之前手动 compact**，留给任务之间的自然断点——压缩发生在任务中途会打断思路。
细节（触发公式、保留策略、压缩与 skill 状态的关系、各家对比）见 [上下文压缩](/docs/CS/AI/LLM/Agent/Theory/Compaction.md)。

#### Environment-Aware Memory

除了显式的文件和对话，Claude Code 还会主动“感知”当前环境，将其作为隐式记忆。
1. 文件系统感知
当你提出需求时，Claude Code 不会凭空想象，而是会通过内置工具（如 ls, read_file, grep）实时扫描你的项目结构，记住当前有哪些文件、目录层级是怎样的。
2. Git 状态感知
Claude Code 深度集成了 Git。它会自动读取：
当前所在的 Git 分支。
最近的 Commit 历史（了解项目的演进方向）。
当前的 git diff（了解你尚未提交的修改）。
这使得它在帮你写代码或解决冲突时，能完美契合你当前的工作进度。
3. 依赖与环境感知
它会自动读取 package.json、requirements.txt 或 go.mod 等依赖文件，记住项目使用了哪些第三方库，从而避免生成不兼容的代码



### "Memory Management" Tips

1. 打造高质量的 CLAUDE.md
CLAUDE.md 的质量直接决定了 Claude Code 的表现。编写时请遵循以下原则：
结构化：使用清晰的 Markdown 标题（#, ##）和列表。
具体可执行：不要写“运行测试”，要写“使用 npm run test 运行单元测试”。
包含“负面约束”：明确告诉它不要做什么。例如：“不要使用 any 类型”、“不要引入新的第三方状态管理库，只用 Zustand”。
保持精简：大模型对过长的提示词会产生“注意力丢失”。只保留最核心、最高频的规则，删除过时信息。
2. 让 Claude 自己更新记忆
你不需要总是手动去修改 CLAUDE.md。在对话中，你可以直接指示 Claude 去更新记忆。例如：
“我们刚才决定使用 Redis 来做缓存，请把这个架构决策记录到根目录的 CLAUDE.md 中。”
“我刚才修改了测试命令，请更新 CLAUDE.md 里的相关说明。”
3. 利用“@”符号注入临时记忆
在对话中，如果你需要 Claude 记住某个特定的文件或上下文，可以使用 @ 符号（如 @src/utils/auth.ts）将其显式拉入当前会话的短期记忆中。
4. 定期“清理”短期记忆
如果你在一个会话中进行了大量无关的探索，导致上下文变得混乱，或者触发了不准确的上下文压缩，最好的办法是开启一个新的终端会话（Session）。新会话会重新加载干净的 CLAUDE.md 长期记忆，而不会被之前混乱的短期记忆干扰。
总结
Claude Code 的记忆系统是一个 “长期规则（CLAUDE.md） + 短期推理（会话上下文） + 实时感知（环境/Git）” 的三维立体架构。






## Links

- [AI](/docs/CS/AI/AI.md)
