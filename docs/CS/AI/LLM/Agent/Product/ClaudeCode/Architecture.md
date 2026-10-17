## Introduction

Claude Code 是 Anthropic 官方的终端 agentic 助手：模型负责推理，工具负责行动，Claude Code 本身是包在外面的一层——提供工具、管理模型看到的上下文。官方文档把这层外围直接称为 **agentic harness**，与 [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) 理论篇的抽象精确对应，那篇的「三层定位」与「四大失败模式」可以直接拿来读本文。

本文是其内部机制的架构拆解，事实基线为 npm `@anthropic-ai/claude-code` **2.1.301**（2026-10-15 发布，stable 通道 2.1.292），全部结论来自官方文档 `code.claude.com/docs`（2026-10-16 核实）。Claude Code 闭源，没有源码仓库可读，因此本文的「实现细节」全部以官方文档的明确陈述为准，不凭记忆推断。

分册导航见 [ClaudeCode 主枢纽](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md)；会话树、压缩、权限的通用原理分别见 [Compaction](/docs/CS/AI/LLM/Agent/Theory/Compaction.md) 与 [Permission](/docs/CS/AI/LLM/Agent/Theory/Permission.md)。

## The Agentic Loop

Claude 执行一个任务时在三个阶段间循环，三个阶段互相交融：

| 阶段 | 做什么 |
| :--- | :--- |
| gather context | 读文件、搜代码、查文档，搞清楚现状 |
| take action | 编辑文件、跑命令、调用外部服务 |
| verify results | 跑测试、复查输出，确认改动生效 |

循环的节奏由模型自己决定：纯问答可能只需要 gather context；修 bug 会在三个阶段间反复；大规模重构则以 verify 为主。用户也在循环内——任何时刻可以打断（Esc 立即取消进行中的工具调用）或排队追加消息（不打断，当前工具调用结束后同一 turn 内读取）。

循环由两个组件驱动：**模型**（推理，`/model` 切换，Sonnet 应付多数编码任务、Opus 强在复杂架构决策）与**工具**（行动）。工具每次调用返回的信息喂回循环，成为下一步决策的输入——官方给的例子是「修失败测试」：跑测试 → 读报错 → 搜源文件 → 读文件 → 改代码 → 重跑测试。

### Five Tool Categories

内置工具按「赋予了哪种行动能力」分五类：

| 分类 | 能力 |
| :--- | :--- |
| File operations | Read / Edit / Write、重命名与重组 |
| Search | Glob 按模式找文件、Grep 正则搜内容、代码库探索 |
| Execution | 跑 shell 命令、起服务器、跑测试、用 git |
| Web | WebSearch 搜网页、WebFetch 取文档 |
| Code intelligence | 编辑后看类型错误与告警、跳定义、找引用（需 code intelligence 插件） |

在此之上还有编排类工具：Task（派生子 agent，见 [Subagents](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Subagents.md)）、AskUserQuestion（向用户提问）。扩展能力——skills（补充知识）、MCP（接外部服务）、hooks（自动化工作流）、subagents（卸载任务）——都叠在这层核心循环之上，本文只讲核心。

### The Same Loop in the SDK

Agent SDK（Python / TypeScript）把同一个循环嵌进用户程序，消息流与 CLI 完全一致：

- **turn 的定义**：Claude 产出含工具调用的输出 → SDK 执行工具 → 结果喂回 Claude，这样一个来回就是一个 turn；循环直到某次输出不含工具调用为止。
- **五种核心消息**：`SystemMessage`（会话生命周期，`init` / `compact_boundary` / `informational` / `worker_shutting_down` 等 subtype）、`AssistantMessage`（每个内容块一条，同一响应的多条共享 message ID）、`UserMessage`（工具执行后携带工具结果）、`StreamEvent`（仅开启 partial messages 时的原始流事件）、`ResultMessage`（循环终点，带最终文本、token 用量、成本、session ID）。
- **熔断机制**：`max_turns` / `maxTurns` 只数含工具调用的 turn；`max_budget_usd` / `maxBudgetUsd` 按花费阈值停。官方建议生产 agent 默认设预算——开放式提示词（「improve this codebase」）没有上限会跑很久。

## Environments And Interfaces

循环、工具、能力在所有界面里相同，变的是**代码在哪里执行**与**怎么交互**：

| 执行环境 | 代码跑在哪 | 用途 |
| :--- | :--- | :--- |
| Local | 本机 | 默认。完整访问本地文件、工具、环境 |
| Cloud | Anthropic 管理的 VM，或组织自建环境 | 卸载任务、操作本地没有的仓库 |
| Remote Control | 本机，浏览器遥控 | 用 Web UI，执行与文件仍留在本地 |

界面则覆盖终端、桌面 app、IDE 扩展（VS Code / JetBrains）、claude.ai/code、Slack 与 CI/CD 流水线。界面只决定「怎么看、怎么交互」，底层 agentic loop 完全相同。

## Sessions And Checkpoints

会话随工作进度落盘：每条消息、每次工具调用及其结果都写进 `~/.claude/projects/` 下的纯文本 JSONL 文件，支撑 rewind / resume / fork 三种操作。另外，Claude 改代码前会对受影响文件做快照，出问题时按两次 Esc 即可回退到之前的状态。

- checkpoint 与 git 相互独立，恢复会话后依然可用；只覆盖文件改动，恢复时跳过符号链接与硬链接文件；影响远端系统的动作（数据库、API、部署）无法 checkpoint，那些靠权限模式与权限规则控制。
- 会话相互独立：新会话 = 全新上下文窗口，不带历史对话；跨会话的知识靠 auto memory（[Memory](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Memory.md)）与 CLAUDE.md 延续。
- 会话绑定目录：`/resume` 选择器默认只列当前 worktree 的会话；切分支后 Claude 看到新分支的文件，但对话历史不变；用 git worktrees 可以并行跑多个会话。

## The Context Window

上下文窗口里装着：对话历史、文件内容、命令输出、CLAUDE.md、auto memory、已加载 skill、系统指令。装满时 Claude Code 自动管理——**先清较早的工具输出，不够再总结对话**；你的请求与关键代码片段会保留，但对话早期的详细指令可能丢失，所以持久规则应该写进 CLAUDE.md 而不是指望对话历史。

`/context` 可以看空间被什么占用。几个与上下文相关的现役事实：

- **MCP 工具定义默认延迟加载**：只有工具名与 server 指令占上下文，具体某个工具被使用时才经 tool search 加载。
- **skill 按需加载**：会话开始 Claude 只看到各 skill 的 description；手动调用的 skill 可设 `disable-model-invocation: true` 把 description 也挡在上下文外。
- **subagent 用独立上下文窗口**：子 agent 的工具调用不进主对话，完成后只把摘要带回（fork 型子 agent 例外，启动时带一份对话副本）。
- **单文件/工具输出过大时**：每次总结后上下文立刻被同一个大文件填满，Claude Code 尝试几次后停止自动压缩并报 thrashing 错误，而不是无限循环。
- **Claude Code 自己加的上下文**：CLAUDE.md、output style 的指令、Claude 早前读过的文件在磁盘上变更时的提示、commit/PR 的署名行。署名行可用 `attribution` 设置改掉，`includeGitInstructions: false` 可整体移除内置的 commit/PR 指令。

## How It Fits Together

把本文与理论篇对照着看：[Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) 讲「harness 为什么存在、补偿哪些模型缺口」，本文讲 Claude Code 这个具体 harness 怎么实现；[Permission](/docs/CS/AI/LLM/Agent/Theory/Permission.md) 讲审批与沙箱的通用机制，[Permission 产品篇](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Permission.md) 讲六模式与 Bash sandbox 的具体形态；[Compaction](/docs/CS/AI/LLM/Agent/Theory/Compaction.md) 讲压缩的通用公式，[Context 部分](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Memory.md) 讲 967K 触发点与保留策略。

## Links

- [ClaudeCode 主枢纽](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md)
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)
- [Permission](/docs/CS/AI/LLM/Agent/Theory/Permission.md)
- [Compaction](/docs/CS/AI/LLM/Agent/Theory/Compaction.md)
- [Codex 架构](/docs/CS/AI/LLM/Agent/Product/Codex/Architecture.md)

## References

- [How Claude Code works](https://code.claude.com/docs/en/how-claude-code-works)
- [Agent SDK: The agent loop](https://code.claude.com/docs/en/agent-sdk/agent-loop)
- [Tools reference](https://code.claude.com/docs/en/tools-reference)
