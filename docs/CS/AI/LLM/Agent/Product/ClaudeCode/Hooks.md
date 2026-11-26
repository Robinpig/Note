## Introduction

Hooks 是 Claude Code 生命周期上的自动化触点：在特定事件发生时执行用户定义的 shell 命令、HTTP 端点、MCP 工具调用、LLM 提示或子 agent。它是「把 harness 行为钉死」的最硬手段——[Permission](/docs/CS/AI/LLM/Agent/Theory/Permission.md) 理论篇说过 CLAUDE.md 只是 context 不是 enforced configuration，而 hook 是真正的强制层。

事实基线：`@anthropic-ai/claude-code` **2.1.326**（CHANGELOG 2.1.326→2.1.302 区间 + `mods/types/claude-code.d.ts` 类型契约核实；官方 hooks reference 2026-10-18 核实）。本篇从 2.1.302 基线升级而来，正文对每一处版本相关结论都标了真实版本；被新版本推翻的旧结论在对应小节显式注明。

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

这张表已完整覆盖 `ClassicHookEvent` 的全部 **33 个事件名**，与 2.1.326 类型声明里的 `HookInput` 联合逐项一致（核对见 [Type Contracts](#type-contracts)）。

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

### MCP Tool Matching

MCP 工具在工具事件里就是普通工具，命名 `mcp__<server>__<tool>`：

- `mcp__memory__.*` 匹配 memory server 的全部工具——`.*` 不能省，`mcp__memory` 只含精确匹配字符，按精确字符串比对一个工具都不中。
- 插件捆绑的 MCP server 用带插件名的 scoped 段：`mcp__plugin_<plugin-name>_<server-name>__<tool>`。写裸 server key 的 matcher 对这些工具永远不触发。

## If Condition

`if` 与 `matcher` 不是一回事：`matcher` 过滤事件，`if` 在单个 handler 上用 **permission rule 语法**做二次过滤，如 `Bash(git *)`、`Edit(*.ts)`。

- **只在工具类事件上评估**（`PreToolUse`、`PostToolUse`、`PostToolUseFailure`、`PermissionRequest`、`PermissionDenied`），其他事件上设了 `if` 的 hook 不运行。
- 一个 handler **只能写一条 rule**，没有 `&&`、`||`、列表语法；要多条件就定义多个 handler。
- Bash 匹配有子命令语义：`Bash(git *)` 对 `npm test && git push` 命中（每个子命令都查）、对 `echo $(rm -rf /)` 命中（`$()` 与反引号内的命令也查）；`FOO=bar git push` 会先剥掉前导赋值再匹配。
- 无法确定命令跑什么时（多次切目录、子 shell），**hook 照跑**——`if` 是 best-effort 过滤，硬性允许/拒绝要用权限系统。
- **Monitor 工具的 shell 命令**（2.1.317）：`if: Monitor(tail *)` 这类条件现在按 `Bash(tail *)` 匹配 Bash 命令的方式去匹配 Monitor 启动的 shell 命令；同期还修复了「匹配 Bash 的 hooks 不在 Monitor 启动的 shell 命令上触发」，这类 hooks 可以 block / ask，但不能 approve 或 rewrite 这些命令。

## Handler Types

五种 handler，全部匹配的 hook **并行执行**。并发上限在 **2.1.312** 被改过：**每个会话最多 24 个 `prompt` / `agent` hook 同时跑（含 subagent），外加最多 12 个等待时间已超过其事件 `timeout` 的；`timeout` 小于 1 秒按 1 秒计**，其余排队。`command` / `http` / `mcp_tool` 不受此限。旧笔记写的「同一事件 `prompt`/`agent` hook 至多 12 个同时跑」是 2.1.302 的表述，**已被 2.1.312 推翻**。

| 类型 | 做什么 |
| :--- | :--- |
| `command` | 跑 shell 命令，stdin 收 JSON、退出码 + stdout 回传决策 |
| `http` | 把事件 JSON POST 到 URL，响体用与 command 相同的 JSON 格式 |
| `mcp_tool` | 调用已配置 MCP server 的工具，文本输出视同 command 的 stdout |
| `prompt` | 单轮问一个 Claude 模型，模型以 JSON 返回决策 |
| `agent` | 派一个能用 Read/Grep/Glob 验证条件的子 agent 再给决策（实验性） |

`prompt` handler 有个容易踩的边界：**只有 `Stop` / `SubagentStop` / `UserPromptSubmit` / `PreToolUse` 四个事件支持它**，其余事件只能用 `command`（官方 plugin-dev skill 明确列出）。需要模型判定但事件不在此列，只能换事件或改用 `agent`。完整取舍与可抄的样例见 [HookPatterns](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/HookPatterns.md)。

### Async Versus AsyncRewake

两者都「不等这个 hook」，但**第二个字段的含义此前未见官方文档记载**——它来自 `security-guidance` 插件的实际用法：

| 字段 | 行为 |
| :--- | :--- |
| `async: true` | hook 后台跑，**不阻塞当前 turn**，结果不保证回到对话 |
| `asyncRewake: true` | hook 后台跑，**完成后主动重新唤醒会话**，把结果交给 Claude |

`asyncRewake` 配两个文本字段：`rewakeMessage` 是唤醒时给 **Claude** 的完整提示词，`rewakeSummary` 是给**用户**看的一行摘要。官方插件的措辞值得抄：「处理或确认下面的发现，然后继续用户的原始请求，或继续等待用户回复」——它显式承认「此刻用户可能在等你回话」这个场景。

这个模式是为**重活**设计的：要读多个文件、跑多次工具调用与模型推理的 hook（比如 agentic 的 commit 安全审查）不可能同步等，而 `async` 又会让结论石沉大海。`asyncRewake` 是「不打断 + 必达」的中间态。

默认 timeout 差异很大，且有几个事件的默认值被单独压低：

| 事件 | 默认 timeout |
| :--- | :--- |
| `command` / `http` / `mcp_tool`（一般） | 600 秒 |
| `UserPromptSubmit`、`PreModelSwitch`、`PostModelSwitch` | 30 秒 |
| `MessageDisplay` | 10 秒 |
| `prompt` | 30 秒 |
| `agent` | 60 秒 |
| `SessionEnd`（所有 hook 共享总预算） | 1.5 秒，单 hook 设更长可把总预算提到最多 60 秒 |

两个与「久」相关的版本事实：

- **进度心跳（2.1.323）**：在 `claude -p` / SDK 会话里，hook 跑得久时宿主每 30 秒收到一次进度心跳，避免宿主（如 Claude Desktop）把该 turn 当挂死而结束（宿主需包含该版本）。
- **被打断 turn 上的 PostToolUse（2.1.319）**：工具调用若在一条新消息打断 turn 之后才完成，其 `PostToolUse` hooks 现在仍会运行，并有最多 10 秒完成。

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
- **`onFailure`**：hook 失败时 `"continue"`（默认）或 `"block"`（v2.1.295+，command / HTTP）。**2.1.317 起 Agent SDK 的 hook 回调也支持 `onFailure: "block"`**：回调失败时阻塞该动作，而不是放行让它继续执行。
- **`once: true`**：首次成功运行后移除该 hook；失败、exit 2 阻断、超时都算没成功，hook 留着下次再跑。**只在 skill frontmatter 里生效**，settings 文件与 agent frontmatter 里会被忽略。

## Type Contracts

2.1.326 的 `mods/types/claude-code.d.ts` 把经典（settings）hook 的输入与结果按事件名做了精确约束。两点核对结论：`ClassicHookEvent` 联合恰好 **33 个事件名**，与本文 [Complete Event Table](#complete-event-table) 一致；各事件能返回的结果字段由 `ClassicResultFields` 逐事件限定，并非所有事件都能返回 `additionalContext` 这类通用字段。

公共输入字段 `BaseHookInput`（`mods/types/claude-code.d.ts`）：

```
  type BaseHookInput = {
      session_id: string;
      transcript_path: string;
      cwd: string;
      /**
       * UUID correlating a user prompt with all subsequent events until the next prompt. Same value emitted on OpenTelemetry events as the `prompt.id` attribute, so hook output can be joined to OTel events at prompt grain. Absent until the first user input of the process lifetime.
       */
      prompt_id?: string;
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

三个字段的精确语义：

- `prompt_id` 是一个 UUID，把一条用户提示与其后所有事件关联到下一条提示为止；它与 OpenTelemetry 事件上的 `prompt.id` 属性**同值**，因此可把 hook 输出按 prompt 粒度与 OTel 事件 join。进程生命周期内首个用户输入之前该字段缺省。
- `agent_id` 只在 hook 于 subagent 内部触发时出现（如 AgentTool worker 调用的工具）；主线程即便在 `--agent` 会话里也没有。**区分 subagent 调用要用 `agent_id` 而不是 `agent_type`**。`agent_type` 在 subagent 内（与 `agent_id` 同时）出现，或在 `--agent` 启动的会话主线程上（无 `agent_id`）出现。
- 另有可选的 `permission_mode` 与 `effort`（当前 turn 的推理强度，`level` 与 `CLAUDE_EFFORT` 同源）。

结果字段逐事件限定于 `ClassicResultFields`（`mods/types/claude-code.d.ts`）：

```
  export type ClassicResultFields = {
      UserPromptSubmit: 'additionalContext' | 'sessionTitle' | 'suppressOriginalPrompt';
      UserPromptExpansion: 'additionalContext' | 'suppressOriginalPrompt';
      SessionStart: 'additionalContext' | 'initialUserMessage' | 'sessionTitle' | 'watchPaths' | 'reloadSkills';
      Setup: 'additionalContext';
      PreModelSwitch: 'permissionDecision' | 'permissionDecisionReason';
      PostModelSwitch: 'additionalContext';
      SubagentStart: 'additionalContext';
      PostToolUse: 'additionalContext' | 'updatedToolOutput' | 'updatedMCPToolOutput';
      PostToolUseFailure: 'additionalContext';
      PostToolBatch: 'additionalContext';
      Stop: 'additionalContext';
      SubagentStop: 'additionalContext';
      PermissionDenied: 'retry';
      PermissionRequest: 'decision';
      MessageDisplay: 'displayContent';
      WorktreeCreate: 'worktreePath';
  };
```

读这张表要注意：

- 每个事件都能读 `block` / `preventContinuation` / `stopReason` 这三个通用字段（表里未逐条列出），事件专属字段只在列出的事件上生效。
- 例如 `UserPromptSubmit` 可返回 `additionalContext`、`sessionTitle`、`suppressOriginalPrompt`；`SessionStart` 还能给 `initialUserMessage`、`watchPaths`、`reloadSkills`；`PreModelSwitch` 用 `permissionDecision` / `permissionDecisionReason`；`PermissionDenied` 只能给 `retry`；`WorktreeCreate` 给 `worktreePath`。
- 字段形状不对会让 hook 失败并被跳过；多个 settings hook 的结果按「后写覆盖、context 拼接」合并。`classic.PreToolUse` 是唯一例外，它保留自己的 `allow`/`ask`/`deny` 结果（`PreToolUseResult`）。

事件名的权威来源是 `HookInput` 联合，`ClassicHookEvent` 取它的 `hook_event_name`（`mods/types/claude-code.d.ts`）：

```
  type HookInput = PreToolUseHookInput | PostToolUseHookInput | PostToolUseFailureHookInput | PostToolBatchHookInput | PermissionDeniedHookInput | NotificationHookInput | UserPromptSubmitHookInput | UserPromptExpansionHookInput | SessionStartHookInput | SessionEndHookInput | StopHookInput | StopFailureHookInput | SubagentStartHookInput | SubagentStopHookInput | PreCompactHookInput | PostCompactHookInput | PreModelSwitchHookInput | PostModelSwitchHookInput | PermissionRequestHookInput | SetupHookInput | TeammateIdleHookInput | TaskCreatedHookInput | TaskCompletedHookInput | ElicitationHookInput | ElicitationResultHookInput | ConfigChangeHookInput | InstructionsLoadedHookInput | WorktreeCreateHookInput | WorktreeRemoveHookInput | CwdChangedHookInput | FileChangedHookInput | DirectoryAddedHookInput | MessageDisplayHookInput;
```

共 33 个成员，与 [Complete Event Table](#complete-event-table) 的事件集合一致——这就是「33 个事件」这一数字的来源。

## Decision Rendering And Diagnostics

2.1.326 对「同一工具调用被多个 hook 回答」的决策处理与可观测性做了几处改进：

- **`updatedInput` 更易保留**：多个 hook 回答同一工具调用时，PreToolUse 的 `updatedInput` 在更多情形下被保留并生效，改写现在跑在更多场景里。
- **退出码 127**：PreToolUse hook 以 127 退出时，报错会提示「它的检查可能没有运行」。
- **transcript 状态着色**：hook 失败从灰色改为红色，阻断 Claude 的 hook 显示为黄色，失败原因显示在对应行下方。
- **OTel 补齐**：managed settings 里的 PreToolUse hook 拒绝一次直接工具调用时，过去不会产出 `tool_decision` 事件或 `permission_denials` 条目，2.1.326 修复了这一缺口。

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

hooks 在 subagent 里同样触发，输入带 `agent_id` 与 `agent_type` 标识子 agent（字段语义见 [Type Contracts](#type-contracts)）。**2.1.323** 修复了 subagent 压缩时 `PreCompact` / `PostCompact` 以及压缩后 `SessionStart` hooks 收不到 `agent_id` / `agent_type` 的问题。

多来源叠加还有两条值得记（均 **2.1.304**）：

- 先运行的插件如果跳过用户某个 mod 的 hook，transcript 会新增一行，点名该事件与插件名。
- skill hooks 每个来源（repo、个人目录或插件）每会话最多注册 1024 个 hook、16384 个 matcher 字符。

cloud session 不读本地 `~/.claude/settings.json`。运行环境里还有两个有用的变量：`$CLAUDE_CODE_REMOTE` 在远端 Web 环境为 `"true"`；`$CLAUDE_CODE_BRIDGE_SESSION_ID`（v2.1.199+）在有 Remote Control 连接时指向本地会话的桥接 session ID。

## Mods

插件可以把 hook 写成 **JavaScript 函数**，在 Claude Code 自己进程里运行，还能画界面、加命令——这种插件叫 **mod**。本文讲的 JSON 配置 hooks 与 mod 并存不冲突，但 mod 走的是 `tool.check` 等事件处理通道，配置在插件侧而非 settings JSON。

mod 已经发展成完整的编程平台（`$` 宿主对象、十余个 hook 事件、`claude plugin test` / `validate` 工具链、组织管控下的权力削减边界），单独立篇见 [Mods](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Mods.md)。

## Common Recipes

- **自动格式化**：`PostToolUse` + `matcher: "Edit|Write"` 跑 prettier。
- **类型检查**：编辑后跑 tsc，失败时用 `onFailure: "block"` 拦住后续动作（command / HTTP 为 v2.1.295+，Agent SDK 回调为 2.1.317+）。
- **Git 拦截**：`PreToolUse` + `matcher: "Bash"` + `if: "Bash(git push *)"`，脚本返回 `permissionDecision: "deny"`。
- **桌面通知**：`Notification` 事件在 Claude 等待输入时发通知。

## Links

- [ClaudeCode 主枢纽](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md)
- [Permission 产品篇](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Permission.md)
- [Permission 理论篇](/docs/CS/AI/LLM/Agent/Theory/Permission.md)
- [Extensions](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Extensions.md)
- [Mods](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Mods.md)
- [Security](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Security.md)

## References

- [Claude Code Hooks reference](https://code.claude.com/docs/en/hooks)
- [Automate actions with hooks](https://code.claude.com/docs/en/hooks-guide)
