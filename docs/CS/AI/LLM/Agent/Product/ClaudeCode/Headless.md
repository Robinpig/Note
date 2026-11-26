## Introduction

同一个 agentic loop 换个外壳就能进脚本：Agent SDK 提供 CLI（`claude -p`）、Python 与 TypeScript 三种入口，把 Claude Code 的工具、循环与上下文管理嵌进你的程序。本文覆盖非交互运行、`--bare` 模式、退出语义与 GitHub Actions 集成。循环内部机制见 [Architecture](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md?id=architecture)。

事实基线：`@anthropic-ai/claude-code` **2.1.326**（2026-11-17 核实）；2.1.302 → 2.1.326 区间内与 headless 相关的变更逐条对照官方 CHANGELOG，headless / github-actions 产品页于 2026-10-18 核实。需要特别注意：原 2.1.302 基线引入、后被官方明确认定为回归的 turn 中途断线 `EPROTO` 行为，已在 2.1.321 修复并恢复 2.1.302 之前的语义（详见 Print Mode）。

## Print Mode

加 `-p`（`--print`）即非交互运行：读 stdin 或 prompt 参数，结果写 stdout，成功退出码 0、失败非 0——脚本可以直接按退出码分支。管道用法与普通命令行工具无异：

```bash
cat build-error.txt | claude -p 'concisely explain the root cause' > output.txt
```

常用组合：`--continue` 续会话、`--allowedTools` 预批准工具、`--output-format` 结构化输出（`text`/`json`/`stream-json`）。不是所有 flag 都能与 `-p` 组合：`--bg` 被拒，`--cloud` 带任务描述被拒（带 session ID 则是把消息排进该 cloud 会话后退出）。另外，退出码的"诚信"在多个版本被加固：`claude -p` 启动失败曾以 0 静默退出，2.1.314 起打印错误并退出 1；磁盘满或 NFS 配额耗尽导致 transcript 行丢失时，2.1.317 / 2.1.321 起 text 与 json 输出都会报错并退出 1（纯 NFS export 场景可能仍漏报）。

### Flag and Startup Warnings

- **列表选项后的 prompt 不再被吞**（2.1.326）：prompt 跟在 `--add-dir`、`--allowedTools` 等列表选项之后，曾被无声丢弃，现已修复。
- **不完整规则启动警告**（2.1.326）：`--allowedTools` / `--disallowedTools` / `--tools` 的值中出现看起来不像完整规则的条目时，启动阶段给警告。
- **损坏配置不再被默认值替换**（2.1.318）：非交互启动遇到不是合法 JSON 的 `~/.claude.json` 时，不再用默认值替换，而是启动失败、说明如何恢复并保留原文件；2.1.319 起 home 下同时存在新旧配置文件时会在 stderr 指出当前用的是哪一个。未被识别的 `teammateMode` 设置值（2.1.325）会被 `claude -p`、启动警告与 `claude doctor` 列为跳过项（仍不生效）。

### Interrupted Turns and Retries

> [!WARNING]
>
> **版本纠偏（回归点）**：连接在一回复中途断开时，turn 曾以 `API Error: EPROTO: The TLS handshake failed` 结束；2.1.321 起改为**保留已返回的部分回复，或重试该请求，与 2.1.302 之前的行为一致**。官方明确把 2.1.302 的行为视为回归，本分册旧基线正是 2.1.302，升级到 2.1.326 后不应再期望"整段回复被丢弃、只剩裸错误"的旧行为。

- **长 hooks 进度心跳**（2.1.323）：`claude -p` 与 SDK 会话中，hooks 长时间运行时每 30 秒发一次进度心跳，避免宿主（如 Claude Desktop）把该 turn 当成挂死而提前结束——需宿主端也包含该版本才生效。
- **重试可见性**（2.1.326）：`claude -p` 在重试 overloaded / 失败的 API 请求、或文本输出被重定向 / 捕获时，终端曾什么都不显示，现已修复。
- 2.1.314 起 sandbox 保护也覆盖 `claude -p --resume` / `--continue` 进入的 worktree；2.1.318 起，`turn.step` 被 hook 挂载时 API 错误截断回复曾被误报为成功的问题已修复。

### Structured Output

- **登录到期时间**（2.1.318）：claude.ai 登录的到期时间被加入 `claude auth status` 的 `loginExpiresAt` 以及 `claude -p` JSON 结果的 **`credential_expires_at`**；文本输出还会在到期前 10 天起于 stderr 给出单行警告。
- **模型被屏蔽要说明**（2.1.323）：settings 屏蔽了请求的模型时，`claude -p` 文本输出曾静默换用别的模型，现改为在 stderr 警告。
- 2.1.325 起 `claude -p` 在终端上的文本输出不再透出非样式控制序列（管道与文件输出不受影响）；无缓存账户数据时，2.1.325 起会等账户数据到手再发首个请求，干净环境首跑可能晚几秒。

### Resume, Teleport and Nested Runs

- **`--resume` 丢延迟工具调用**（2.1.319）：`claude -p --resume` 带 prompt 时，若某延迟工具调用的 MCP server 缺失，曾丢失该调用；现改为退出码 1、保留该调用并拒绝后续输入。
- **`--teleport` 失败退出码**（2.1.323）：修复 `claude -p --teleport` 恢复失败却以 0 退出（同时修复 `claude --teleport` 在服务器找不到会话历史时打开空会话）。
- **嵌套 `claude -p` 不再共享会话 ID**（2.1.317）：`claude -p` 运行在 cloud / self-hosted runner 会话内时，曾借用该会话的 ID——写进其 transcript、重启可能恢复错会话，还会自拟标题发给该会话；现已修复（旧行为可用 `CLAUDE_CODE_DISABLE_NESTED_SESSION_ID=1` 恢复）。
- 2.1.309 起，print / SDK 会话中被禁用的 MCP server 不再被后续权限提示重连；2.1.318 起 `--continue` 在畸形工具调用重试耗尽后丢失更早对话的问题（2.1.314 引入的回归）已修复；同一版本还修复了空闲非交互会话退出时把已删除的 transcript 用最后一条 prompt 重建的问题。

## Bare Mode

`--bare` 跳过启动时的一切自动发现——hooks、skills、自定义命令、subagents、已装插件、MCP servers、auto memory、CLAUDE.md 全不加载。为 CI 与脚本提供「每台机器同样结果」的确定性，官方说它将成为 `-p` 未来版本的默认模式。

- **凭证**：bare 模式**不读 OAuth 凭证与系统 keychain**——Anthropic API 要显式设 `ANTHROPIC_API_KEY`（或 `--settings` 里给 `apiKeyHelper`）；Bedrock / Agent Platform / Foundry 仍照常读各自 provider 凭证。
- **要带的上下文用 flag 传**：`--append-system-prompt`（及 `-file` 变体）、`--settings`、`--mcp-config`、`--agents`、`--plugin-dir` / `--plugin-url`。
- **例外**：`--add-dir` 目录下只加载其 `.claude/skills/`，`.claude/commands/` 与 `.claude/agents/` 仍跳过。
- **运行期限制**：只有命令行给的 MCP server 会连；Claude 拿不到 system reminders（文件变更提示、可用 skill 列表都没有）；没有后台任务——命令超时就是停，不会转后台。
- v2.1.286 之前这些限制只部分生效（bare 会话会连正常会话的 MCP、会发 system reminders、有后台任务）。

**认证与后台迁移（2.1.326）**：未批准 API key 的 `--bare` 会话，移到后台在多数配置下被拒；后台服务没有该 key 时 `claude --bare --bg` 报错退出。同类约束不限于 bare：当会话同时使用 API key / auth token / profile（或 workload identity），又存有 claude.ai 登录时，发往另一台机器上会话的消息会被拒。

没有 `--bare` 时，`-p` 会话照常加载工作目录与 `~/.claude` 的配置（包括从未信任过的目录里的 hooks 与 `.mcp.json`），且**不显示 workspace trust 对话框**——在不可信仓库上跑 `-p` 要知道这点。会话运行期间，`.claude/skills` 里的 mods 文件发生变化会触发 headless 会话重新加载（2.1.321），设 `CLAUDE_CODE_PLUGIN_DIR_WATCH=0` 可关闭。

## Exit Semantics

### Background Work At Exit

stdin 关闭后，`-p` 运行会保持打开等 Claude 拉起的后台工作：后台命令（等退出或超时，其间 10 分钟上限不计时）、后台 subagent 与 workflows、Monitor watches（默认 5 分钟超时）、待触发的 `/loop` wakeup（可超过 10 分钟上限）。默认 10 分钟连续空闲后停掉剩余后台工作并丢弃部分结果，`CLAUDE_CODE_PRINT_BG_WAIT_CEILING_MS` 可改（0 = 不限）。达到 `--max-budget-usd` 上限则直接停。

两点版本相关的补充：2.1.321 修复了 `claude -p` 有时误称后台命令有 30 分钟——实际到 10 分钟就被停；同版本起，auto mode 下 headless、桌面与 VS Code 会话中**一起等待的后台 subagent 报告合并为一次模型调用回答**，与终端行为一致。

### Signals

- **SIGTERM**：退出码 **143**；进行中的 turn 留作未完成、不记结果；终止仍在跑的 Bash 命令进程树，跑 SessionEnd hooks 后退出，退出途中不开新工具调用、不发新模型请求。恢复会话时被中断的 turn 原样保留（`CLAUDE_CODE_RESUME_INTERRUPTED_TURN=1` 可让 resume 继续该 turn）。2.1.325 起，`--no-session-persistence` 会话的长工具结果会在正常退出、Ctrl+C 或 SIGTERM 时被清理。
- **SIGINT**（或 SDK 的 `interrupt()`）：正常结束当前 turn。

### Deleted Working Directory

`-p` / SDK 会话的工作目录被删后会话继续跑，但 turn 启动时目录缺失会在 stream-json 输出里给 warning。2.1.325 起，工作目录被删后 shell 命令不再偷偷在启动目录执行，而是失败并给出消息，可重新发出。

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
- [Architecture](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md?id=architecture)
- [Extensions](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Extensions.md)
- [Permission 产品篇](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Permission.md)

## References

- [Run Claude Code programmatically (headless)](https://code.claude.com/docs/en/headless)
- [Claude Code GitHub Actions](https://code.claude.com/docs/en/github-actions)
