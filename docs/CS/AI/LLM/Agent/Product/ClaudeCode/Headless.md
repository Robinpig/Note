## Introduction

同一个 agentic loop 换个外壳就能进脚本：Agent SDK 提供 CLI（`claude -p`）、Python 与 TypeScript 三种入口，把 Claude Code 的工具、循环与上下文管理嵌进你的程序。本文覆盖非交互运行、`--bare` 模式、退出语义与 GitHub Actions 集成。循环内部机制见 [Architecture](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Architecture.md)。

事实基线：`@anthropic-ai/claude-code` **2.1.301**（2026-10-15），官方 headless / github-actions 页（2026-10-16 核实）。

## Print Mode

加 `-p`（`--print`）即非交互运行：读 stdin 或 prompt 参数，结果写 stdout，成功退出码 0、失败非 0——脚本可以直接按退出码分支。管道用法与普通命令行工具无异：

```bash
cat build-error.txt | claude -p 'concisely explain the root cause' > output.txt
```

常用组合：`--continue` 续会话、`--allowedTools` 预批准工具、`--output-format` 结构化输出（`text`/`json`/`stream-json`）。不是所有 flag 都能与 `-p` 组合：`--bg` 被拒，`--cloud` 带任务描述被拒（带 session ID 则是把消息排进该 cloud 会话后退出）。

## Bare Mode

`--bare` 跳过启动时的一切自动发现——hooks、skills、自定义命令、subagents、已装插件、MCP servers、auto memory、CLAUDE.md 全不加载。为 CI 与脚本提供「每台机器同样结果」的确定性，官方说它将成为 `-p` 未来版本的默认模式。

- **凭证**：bare 模式**不读 OAuth 凭证与系统 keychain**——Anthropic API 要显式设 `ANTHROPIC_API_KEY`（或 `--settings` 里给 `apiKeyHelper`）；Bedrock / Agent Platform / Foundry 仍照常读各自 provider 凭证。
- **要带的上下文用 flag 传**：`--append-system-prompt`（及 `-file` 变体）、`--settings`、`--mcp-config`、`--agents`、`--plugin-dir` / `--plugin-url`。
- **例外**：`--add-dir` 目录下只加载其 `.claude/skills/`，`.claude/commands/` 与 `.claude/agents/` 仍跳过。
- **运行期限制**：只有命令行给的 MCP server 会连；Claude 拿不到 system reminders（文件变更提示、可用 skill 列表都没有）；没有后台任务——命令超时就是停，不会转后台。
- v2.1.286 之前这些限制只部分生效（bare 会话会连正常会话的 MCP、会发 system reminders、有后台任务）。

没有 `--bare` 时，`-p` 会话照常加载工作目录与 `~/.claude` 的配置（包括从未信任过的目录里的 hooks 与 `.mcp.json`），且**不显示 workspace trust 对话框**——在不可信仓库上跑 `-p` 要知道这点。

## Exit Semantics

### Background Work At Exit

stdin 关闭后，`-p` 运行会保持打开等 Claude 拉起的后台工作：后台命令（等退出或超时，其间 10 分钟上限不计时）、后台 subagent 与 workflows、Monitor watches（默认 5 分钟超时）、待触发的 `/loop` wakeup（可超过 10 分钟上限）。默认 10 分钟连续空闲后停掉剩余后台工作并丢弃部分结果，`CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS` 可改（0 = 不限）。达到 `--max-budget-usd` 上限则直接停。

### Signals

- **SIGTERM**：退出码 **143**；进行中的 turn 留作未完成、不记结果；终止仍在跑的 Bash 命令进程树，跑 SessionEnd hooks 后退出，退出途中不开新工具调用、不发新模型请求。恢复会话时被中断的 turn 原样保留（`CLAUDE_CODE_RESUME_INTERRUPTED_TURN=1` 可让 resume 继续该 turn）。
- **SIGINT**（或 SDK 的 `interrupt()`）：正常结束当前 turn。

### Deleted Working Directory

`-p` / SDK 会话的工作目录被删后会话继续跑，但 turn 启动时目录缺失会在 stream-json 输出里给 warning，shell 命令失败直到目录恢复。

## GitHub Actions

Claude Code GitHub Action（`anthropics/claude-code-action@v1`）按 workflow 配置分两种模式：

| 模式 | 触发 | 结果 |
| :--- | :--- | :--- |
| Interactive | workflow 无 prompt 输入；等 issue/PR 评论、PR review 或新 issue 标题正文里的 `@claude` | 以评论形式回复并持续更新 |
| Automation | workflow 提供 prompt 输入 | 不等提及直接跑，结果默认进 workflow run log |

两道准入检查（任一不过则 run 失败）：**写权限**（issue/PR 事件上触发者须有仓库写权限，`allowed_non_write_users` 可放行特定用户；schedule 等无作者事件跳过）与**人类作者**（bot actor 一律拒，除非列进 `allowed_bots`——这条防 bot 把 Claude 引着互刷，schedule 运行也查，因为 GitHub 把它归因于某个仓库用户）。

典型配置：`id-token: write`（GitHub App 认证必需）、`actions: read`（让 Claude 读 CI 结果）、`actions/checkout` 给 Claude 一份仓库副本。认证可用 `anthropic_api_key` 或 `claude_code_oauth_token`（订阅登录）。prompt 输入也接受 skill 调用：仓库内 skill 传 `/skill-name`（需先 checkout），插件 skill 传 `/plugin-name:skill-name`（配 `plugin_marketplaces` 与 `plugins` 输入）。

凭证保护（fork PR 不泄露 secrets）、成本管理（按需触发、限定路径）与排障（@claude 无响应、Claude 的 commit 不触发 CI）见官方 github-actions 页。

## Links

- [ClaudeCode 主枢纽](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md)
- [Architecture](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Architecture.md)
- [Extensions](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Extensions.md)
- [Permission 产品篇](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Permission.md)

## References

- [Run Claude Code programmatically (headless)](https://code.claude.com/docs/en/headless)
- [Claude Code GitHub Actions](https://code.claude.com/docs/en/github-actions)
