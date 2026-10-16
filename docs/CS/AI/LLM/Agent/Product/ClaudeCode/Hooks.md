## Introduction

Hooks 是 Claude Code 生命周期上的自动化触点：在特定事件发生时执行用户定义的 shell 命令、HTTP 端点、MCP 工具调用、LLM 提示或子 agent。它是「把 harness 行为钉死」的最硬手段——[Permission](/docs/CS/AI/LLM/Agent/Theory/Permission.md) 理论篇说过 CLAUDE.md 只是 context 不是 enforced configuration，而 hook 是真正的强制层。

事实基线：`@anthropic-ai/claude-code` **2.1.301**（2026-10-15），官方 hooks reference（2026-10-16 核实）。本文覆盖事件全表、匹配语义、五种 handler、以及与旧版笔记的差异。

## Event Cadence

按触发节奏，33 个事件分三种 cadence：

| Cadence | 事件 |
| :--- | :--- |
| per session | `SessionStart`、`SessionEnd` |
| per turn | `UserPromptSubmit`、`Stop`、`StopFailure` |
| per tool call | `PreToolUse`、`PostToolUse`——`EndConversation` 调用除外，它两个都跳过 |

「per tool call」这条 cadence 解释了为什么 `PreToolUse`/`PostToolUse` 是 hooks 体系里最高频的事件，也是绝大多数 hook 配置的落点。

## Complete Event Table

按生命周期分组（挑有代表性的列全）：

| 分组 | 事件 |
| :--- | :--- |
| 会话生命周期 | `SessionStart`、`SessionEnd`、`Setup`、`InstructionsLoaded` |
| 提示与工具 | `UserPromptSubmit`、`UserPromptExpansion`、`PreToolUse`、`PostToolUse`、`PostToolUseFailure`、`PostToolBatch`、`PermissionRequest`、`PermissionDenied` |
| 子 agent 与任务 | `SubagentStart`、`SubagentStop`、`TaskCreated`、`TaskCompleted`、`TeammateIdle` |
| 上下文与模型 | `PreCompact`、`PostCompact`、`PreModelSwitch`、`PostModelSwitch` |
| 环境与文件 | `CwdChanged`、`DirectoryAdded`、`FileChanged`、`ConfigChange` |
| git worktree | `WorktreeCreate`、`WorktreeRemove` |
| MCP 与交互 | `Elicitation`、`ElicitationResult`、`Notification`、`MessageDisplay` |
| 其他 | `Stop`、`StopFailure` |

两个较新的事件值得单独说：

- **`UserPromptExpansion`**：用户输入的命令（如 `/deploy`）展开成 prompt 后、到达 Claude 前触发，**可以阻断展开**。
- **`DirectoryAdded`**：会话中经 `/add-dir` 或 SDK `register_repo_root` 添加工作目录时触发。

`InstructionsLoaded` 在 `CLAUDE.md` 或 `.claude/rules/*.md` 被载入上下文时触发——会话启动时与会话中懒加载时都会触发。`CwdChanged` 在 Claude 执行 `cd` 改变工作目录时触发，适合配合 direnv 做响应式环境管理。

## Matcher Semantics

`matcher` 过滤事件本身，**怎么解析取决于字符构成**：

| Matcher 值 | 解析为 |
| :--- | :--- |
| `*`、空、省略 | 匹配所有 |
| 只含字母数字与 `_ - 空格 , |` | 精确字符串，或 `|` / `,` 分隔的精确列表 |
| 含其他任何字符 | **未锚定的 JS 正则** |

正则路径用 `RegExp.prototype.test`，任何位置匹配即算中：`Edit.*` 会连 `NotebookEdit` 一起匹配，要精确匹配必须写 `^Edit$`。`FileChanged` 与 `StopFailure` 的字符集更窄——只有字母数字、`_`、`|`，连字符/空格/逗号都会把它推上正则路径。

不同事件匹配的字段不同：工具类事件匹配 `tool_name`；`SessionStart` 匹配启动方式（`startup`/`resume`/`clear`/`compact`/`fork`）；`PreCompact`/`PostCompact` 匹配触发方式（`manual`/`auto`）；`PreModelSwitch`/`PostModelSwitch` 匹配模型 canonical 名。**十个事件根本不支持 matcher**（`UserPromptSubmit`、`Stop`、`CwdChanged`、`TaskCreated` 等），给它们加 `matcher` 会被静默忽略——不报错，只是没用。

### MCP 工具匹配

MCP 工具在工具事件里就是普通工具，命名 `mcp__<server>__<tool>`：

- `mcp__memory__.*` 匹配 memory server 的全部工具——`.*` 不能省，`mcp__memory` 只含精确匹配字符，按精确字符串比对一个工具都不中。
- 插件捆绑的 MCP server 用带插件名的 scoped 段：`mcp__plugin_<plugin-name>_<server-name>__<tool>`。写裸 server key 的 matcher 对这些工具永远不触发。

## If Condition

`if` 与 `matcher` 不是一回事：`matcher` 过滤事件，`if` 在单个 handler 上用 **permission rule 语法**做二次过滤，如 `Bash(git *)`、`Edit(*.ts)`。

- **只在工具类事件上评估**（`PreToolUse`、`PostToolUse`、`PostToolUseFailure`、`PermissionRequest`、`PermissionDenied`），其他事件上设了 `if` 的 hook 不运行。
- 一个 handler **只能写一条 rule**，没有 `&&`、`||`、列表语法；要多条件就定义多个 handler。
- Bash 匹配有子命令语义：`Bash(git *)` 对 `npm test && git push` 命中（每个子命令都查）、对 `echo $(rm -rf /)` 命中（`$()` 与反引号内的命令也查）；`FOO=bar git push` 会先剥掉前导赋值再匹配。
- 无法确定命令跑什么时（多次切目录、子 shell），**hook 照跑**——`if` 是 best-effort 过滤，硬性允许/拒绝要用权限系统。

## Handler Types

五种 handler，全部匹配的 hook **并行执行**：

| 类型 | 做什么 |
| :--- | :--- |
| `command` | 跑 shell 命令，stdin 收 JSON、退出码 + stdout 回传决策 |
| `http` | 把事件 JSON POST 到 URL，响体用与 command 相同的 JSON 格式 |
| `mcp_tool` | 调用已配置 MCP server 的工具，文本输出视同 command 的 stdout |
| `prompt` | 单轮问一个 Claude 模型，模型以 JSON 返回决策 |
| `agent` | 派一个能用 Read/Grep/Glob 验证条件的子 agent 再给决策（实验性） |

默认 timeout 差异很大，且有几个事件的默认值被单独压低：

| 事件 | 默认 timeout |
| :--- | :--- |
| `command` / `http` / `mcp_tool`（一般） | 600 秒 |
| `UserPromptSubmit`、`PreModelSwitch`、`PostModelSwitch` | 30 秒 |
| `MessageDisplay` | 10 秒 |
| `prompt` | 30 秒 |
| `agent` | 60 秒 |
| `SessionEnd`（所有 hook 共享总预算） | 1.5 秒，单 hook 设更长可把总预算提到最多 60 秒 |

## Command Hook Forms

`args` 字段决定 command hook 走哪种形态：

- **exec form**（设了 `args`）：`command` 解析为 PATH 上的可执行文件，直接以 `args` 为参数向量 spawn，**不经 shell**。每个 `args` 元素就是一个参数，`$`、反引号、单引号原样透传。引用路径占位符（`${CLAUDE_PROJECT_DIR}` 等）时官方建议用这种，避免 shell 二次解析。
- **shell form**（省略 `args`）：字符串交给 shell（macOS/Linux 为 `sh -c`，Windows 为 Git Bash），解释变量、管道、`&&`、重定向与 glob。需要 shell 特性时才用它。

Windows 上 exec form 要求 `command` 解析到真正的可执行文件——npm/npx/eslint 装在 `node_modules/.bin` 的 `.cmd`/`.bat` shim 不是可执行文件，跨平台稳妥写法是 `"command": "node", "args": [".../eslint.js"]`。

两种形态都会把 `CLAUDE_PROJECT_DIR`、`CLAUDE_PLUGIN_ROOT`、`CLAUDE_PLUGIN_DATA` 导出为环境变量；插件 hook 还会在 exec form 里替换 `${user_config.*}`（shell form 引用它会直接报错，要读 `$CLAUDE_PLUGIN_OPTION_<KEY>` 环境变量）。

## Advanced Fields

除 `type`/`timeout`/`statusMessage` 外，较新的字段：

- **`async: true`**：后台运行不阻塞（command hook 上不强制执行 timeout）。
- **`asyncRewake: true`**：后台运行，退出码 2 时唤醒 Claude——hook 的 stderr（空则 stdout）作为 system reminder 给 Claude 反应长任务失败的机会。
- **`shell`**：`"bash"` 或 `"powershell"`，默认 bash（Windows 无 Git Bash 时 powershell）。设了 `args` 时被忽略。
- **`onFailure`**：hook 失败时 `"continue"`（默认）或 `"block"`，需 **v2.1.295+**。
- **`once: true`**：首次成功运行后移除该 hook；失败、exit 2 阻断、超时都算没成功，hook 留着下次再跑。**只在 skill frontmatter 里生效**，settings 文件与 agent frontmatter 里会被忽略。

## Layering And Merge

多个来源的 hook 是**合并而非覆盖**：

| 来源 | 作用域 |
| :--- | :--- |
| `~/.claude/settings.json` | 本机所有项目 |
| `.claude/settings.json` | 单项目，可提交 |
| `.claude/settings.local.json` | 单项目本机，通常进 gitignore |
| managed policy settings | 组织级 |
| 插件 `hooks/hooks.json` | 插件启用期间 |
| skill frontmatter | skill 被调用后的本次会话余下时间 |
| subagent frontmatter | 该 subagent 运行期间 |

同一 settings 文件里定义的同一 handler 只跑一次；但**插件或 skill 内独立定义的同一 handler 算另一份**。`disableAllHooks` 关不掉 managed hooks。管理员可以：

- `allowManagedHooksOnly`：只放行 managed hooks（managed settings 里 force-enable 的插件 hooks 豁免），同时把 statusLine 等设置也收窄到 managed。
- `allowedHttpHookUrls` / `httpHookAllowedEnvVars`：HTTP hook 的 URL allowlist 与可插值到 header 的环境变量白名单。

hooks 在 subagent 里同样触发，输入带 `agent_id` 与 `agent_type` 标识子 agent。cloud session 不读本地 `~/.claude/settings.json`。运行环境里还有两个有用的变量：`$CLAUDE_CODE_REMOTE` 在远端 Web 环境为 `"true"`；`$CLAUDE_CODE_BRIDGE_SESSION_ID`（v2.1.199+）在有 Remote Control 连接时指向本地会话的桥接 session ID。

## Mods

插件可以把 hook 写成 **JavaScript 函数**，在 Claude Code 自己进程里运行，还能画界面、加命令——这种插件叫 **mod**。本文讲的 JSON 配置 hooks 与 mod 并存不冲突，但 mod 走的是 `tool.check` 等事件处理通道，配置在插件侧而非 settings JSON。

## Common Recipes

- **自动格式化**：`PostToolUse` + `matcher: "Edit|Write"` 跑 prettier。
- **类型检查**：编辑后跑 tsc，失败时用 `onFailure: "block"` 拦住后续动作（v2.1.295+）。
- **Git 拦截**：`PreToolUse` + `matcher: "Bash"` + `if: "Bash(git push *)"`，脚本返回 `permissionDecision: "deny"`。
- **桌面通知**：`Notification` 事件在 Claude 等待输入时发通知。

## Links

- [ClaudeCode 主枢纽](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md)
- [Permission 产品篇](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Permission.md)
- [Permission 理论篇](/docs/CS/AI/LLM/Agent/Theory/Permission.md)
- [Extensions](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Extensions.md)

## References

- [Claude Code Hooks reference](https://code.claude.com/docs/en/hooks)
- [Automate actions with hooks](https://code.claude.com/docs/en/hooks-guide)
