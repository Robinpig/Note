# Agent Permission Control and Sandbox (Permission & Sandbox)

> 核实日期：2026-10-05。所有行为细节以官方文档 / 官方仓库源码为准。
> 本机可访问源：`code.claude.com`、`github.com`（HTML + git clone）、`opencode.ai`、`google-gemini.github.io`、`aider.chat`、`docs.cline.bot`、`openai.com/index`、`learn.chatgpt.com`（部分）。
> 不可访问：`docs.claude.com`（区域重定向）、`ai.google.dev`、`huggingface.co/api`、GitHub REST API（未认证即 403 限流，本次改用稀疏 clone 读源码）、`developers.openai.com` 与 `learn.chatgpt.com` 部分页面对 WebFetch 返回 Forbidden（改用 WebSearch 取官方页快照）。

---

## General Mechanism

### 1. Technical Forms of Sandboxing

分档不是「越强越好」的线性关系，真正的分歧点是**是否共享内核**。

| 形态 | 机制 | 隔离强度 | 性能代价 | 代表 |
| --- | --- | --- | --- | --- |
| 进程级（Linux） | Landlock LSM + seccomp BPF + user/mount/PID namespace | 中：受内核版本限制，无网络过滤（需另配） | 极低（µs 级） | Codex 的 legacy 路径、DSH `sandbox-local` |
| 进程级（当前主流） | bubblewrap（namespace 挂载视图）+ seccomp + 独立 network namespace + 代理转发 | 中高：文件系统视图完整可控，网络靠 namespace 切断 | 低（进程启动开销，毫秒级） | Claude Code（Linux/WSL2）、Codex（0.115+ 默认）、DSH `sandbox-local` Linux 后端 |
| 容器 | namespace + cgroup + overlayfs，共享宿主内核 | 中高，但内核共享是硬上限 | 中（构建缓存、启动秒级） | Gemini CLI 容器沙箱、Dev Container |
| microVM | 独立内核，Firecracker / gVisor | 高 | 高（启动百毫秒~秒级，内存开销） | Claude Code VM / Cloud sessions、Docker Sandboxes |
| 工作区隔离 | 只做「路径/目录」层面的逻辑围栏 | 低：**不是内核边界** | 近乎为零 | DSH `fs-sandbox`（自述为 "a policy fence, not a kernel boundary"） |

**关于「Linux 上是否普遍用 Landlock + seccomp」——本库这条需要修正。**

三家在 Linux 上的当前默认实现都**不是** Landlock + seccomp，而是 bubblewrap：

- **Codex**：官方文档写明 "Linux uses bwrap plus seccomp by default"。官方 `codex-rs/core/config.schema.json` 中的 `$.features.use_legacy_landlock`（`type: boolean`）证实它是 **[features] 表下的特性开关**；源码 `codex-rs/linux-sandbox/src/` 同时存在 `bwrap.rs`、`bundled_bwrap.rs`、`landlock.rs`，配置字段经 `core/src/tools/sandboxing.rs:418` 的 `config().use_legacy_landlock()` 传入执行层。即 **Landlock 是需要显式打开的 legacy 回退路径**。同一 schema 中还有紧邻的 `$.features.use_linux_sandbox_bwrap`（`type: boolean`），说明 bwrap 本身亦可被显式关闭——两条路径都在 `[features]` 表下可切换。
- **Claude Code**：官方 sandboxing 文档明确列出 Linux/WSL2 依赖 `bubblewrap` + 独立 network namespace + `socat`，**可选** seccomp 用于阻止 Unix domain socket。文档中**完全没有提到 Landlock**。文档明确说明 "Claude Code builds the sandbox on the open source `@anthropic-ai/sandbox-runtime` package"。
- **DSH**：`docs/subsystems/sandbox.md` 写 `dsh-sandbox-local` supplies **Linux bwrap/Landlock、macOS Seatbelt、Windows ACL restricted-token**；且把老旧 Landlock ABI 与 Windows ACL 的硬链接/宽松读/AppContainer-ACL 缺口都归类为 `SandboxEnforcement = 'partial'`。

**结论**：Landlock+seccomp 曾经是主流，但**当前主流已转向 bubblewrap**。Landlock 在今天更接近「无 bwrap 环境下的回退方案」，性能代价极低但覆盖不完整。

**值得单独指出的设计细节**：Claude Code 的 seccomp 是**可选依赖**，缺失时 `/sandbox` 面板仍会显示其它标签页，只多一个 Dependencies 页签；官方文档写明 seccomp 缺失时「无法可靠阻止」Unix domain socket。这是「按需依赖」换来启动灵活性、代价是 Unix socket 逃逸面默认敞开（例如 `/var/run/docker.sock`，文档直言允许它「基本等价于把宿主机控制权交给沙箱命令」）。

来源：
- https://code.claude.com/docs/en/sandboxing.md
- https://code.claude.com/docs/en/sandbox-environments.md
- https://developers.openai.com/codex/sandbox（WebSearch 快照）
- https://learn.chatgpt.com/docs/sandboxing（WebSearch 快照）
- https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/sandbox.md

### 2. Levels of Permission Judgment

四层实为「同一判定链上的四个粒度」，各家实现深度差异极大：

| 层级 | 含义 | 谁做到了 |
| --- | --- | --- |
| 工具级 | 这个工具能不能用 | 全部 |
| 路径级 | 这个文件/目录能不能碰 | Claude Code（Git ignore 风格模式）、Codex（filesystem rules / permission profiles）、OpenCode（`external_directory`、glob）、DSH（`fs-sandbox` 的 canonicalize-then-contain） |
| 命令级 | 命令文本前缀匹配 | Claude Code（`Bash(git log *)`）、Codex（rules 的 argv 前缀）、OpenCode（`bash` 对象语法）、Cline（`CLINE_COMMAND_PERMISSIONS`） |
| **参数级** | 同一工具不同参数区别对待 | **Claude Code 最深**：`Tool(param:value)` 只对顶层标量参数生效，且明确**不能**用于 `Bash(command:…)` / `Read(file_path)` / `WebFetch(url)`；**Codex 最严谨**：rules 走 **argv 列表匹配**（`execvp` 视角）而非字符串匹配 |

**「只允许 git status 不允许 git push」这个具体问题**：

- Claude Code 可以：`{"allow": ["Bash(git status *)"], "deny": ["Bash(git push *)"]}`，官方文档还专门警告 "Put the `*` after the subcommand"，因为 `Bash(git *)` 会连带放行 `git push` 和 `git -c <script> diff`。
- Codex 更强：rules 用 `.rules` 文件（Starlark）逐 argv 匹配，且**能安全拆分线性 shell 脚本**——`bash -lc "git add . && rm -rf /"` 会被 tree-sitter 拆成 `["git","add","."]` 与 `["rm","-rf","/"]` 分别求值，多规则命中时取**最严格**结果（`forbidden > prompt > allow`）。所以即使 allow 了 `git add`，也不会因夹带 `rm -rf /` 而整体放行。这正是「参数级判定」的意义：字符串前缀匹配会被拼接绕过，argv 级不会。
- 但要注意反面：**Codex 的 Claude 式复合命令拆分是「安全时拆、不安全时不拆」**。脚本用到重定向、命令替换、变量展开时退化为对整条调用求值——保守方向是「不拆」，所以 fail closed。

**这类规则都不是安全边界。** Claude Code 官方给出反例表：`Bash(curl *)` 拦不住 `/usr/bin/curl ...` 或 `sh -c 'curl ...'`；`Bash(git push *)` 拦不住 `git -C . push origin main`、`git -c push.default=current push`、`git 'push' origin main`。要真正不依赖命令文本，得靠沙箱 + `PreToolUse` hook。

来源：
- https://code.claude.com/docs/en/permissions.md
- https://developers.openai.com/codex/rules（WebSearch 快照）
- https://opencode.ai/docs/permissions/

### 3. Approval Granularity and 'How Much Scope One Authorization Covers'

这是各家最核心的差异点。

| 产品 | 一次授权的作用范围 | 机制 |
| --- | --- | --- |
| Claude Code | 一次 / 会话（部分）/ 按仓库+命令永久 | 审批提示提供 `Yes`（单次）、`Yes, and don't ask again`（保存规则，落到 `.claude/settings.local.json`）、`Yes, and switch to auto mode`。关键：**文件修改审批只到会话结束，不落盘**；Bash/WebFetch/WebSearch 规则按仓库持久化。批准复合命令时按子命令分别存规则，**单条复合命令最多存 5 条** |
| Codex | 一次 / 本会话（`ApprovedForSession`，走 session-scoped approval cache）/ 永久（`ApprovedExecpolicyAmendment` 写 rules、`ApprovedMcpPolicyAmendment` 跨会话、`NetworkPolicyAmendment` 持久化 host 规则） | 五种放行决策各有独立作用域，见下文对比表 |
| DSH | **只有 `allowed-once`** | `ApprovalOutcome = 'allowed-once' \| 'rejected' \| 'cancelled' \| 'unavailable'`。类型层面就不存在「永久授权」——这是四家里最保守的设计 |
| OpenCode | 一次 / 本次 OpenCode 会话 | 审批 UI 三选项 `once` / `always`（仅当前会话）/ `reject`；`always` 覆盖的模式集由工具提供（如 bash 给 `git status*` 前缀） |
| Gemini CLI | 一次 | `--approval-mode`（`default` / `auto_edit` / `yolo`）、`--allowed-tools` 白名单 |
| Cline | 一次 / 全自动 | `--auto-approve`（CLI **默认 true**）、`CLINE_COMMAND_PERMISSIONS` 策略 |

**DSH 的 `allowed-once` 是本轮核实里最值得记的设计**：把「放行」在类型上限制为一次性，永久授权这个概念根本不存在，从根上消除了「授权范围越滚越大」的类别错误。代价是长任务审批更频繁。

来源：
- https://code.claude.com/docs/en/permissions.md
- https://github.com/openai/codex/blob/main/docs/config.md + `codex-rs/protocol/src/protocol.rs:4146`
- https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/approval.md
- https://opencode.ai/docs/permissions/
- https://google-gemini.github.io/gemini-cli/docs/get-started/configuration
- https://docs.cline.bot/cli/configuration

### 4. Implementation of Fail-Closed

**先明确一个概念区分**：官方文档里 Codex 把决策枚举叫 `ReviewDecision::Abort`，而 Claude Code 在权限提示里把中途中断叫「停止当前 turn」。二者都指向「中止」，但语义不同：Codex 的 `Denied` 是「拒绝这一步，但会话继续、换个方法试」，`Abort` 是「什么都别做，直到用户下一条指令」。**把 `Denied` 误当成 `Abort` 会让 Agent 误以为可以换个姿势重试。**

#### Codex (source-level verification, hard evidence for fail-closed)

`codex-rs/protocol/src/protocol.rs:4183`：

```rust
impl Default for ReviewDecision {
    fn default() -> Self {
        Self::Denied { rejection: "denied".to_string() }
    }
}
```

**默认值就是拒绝**——任何未显式赋值的决策路径都落到 `Denied`。这是教科书式的 fail closed。

超时同样拒绝，`codex-rs/core/src/tools/approvals.rs:466`：

```rust
ReviewDecision::TimedOut => Err(ToolError::Rejected(
    ResolvedModelMessages::from_model(model_info)
        .auto_review().timeout_instructions.to_string(),
)),
ReviewDecision::Abort => Err(ToolError::Codex(CodexErr::TurnAborted)),
```

shell 提权路径同样如此，`core/src/tools/runtimes/zsh_fork/unix_escalation.rs:372`：`ReviewDecision::TimedOut => EscalationDecision::deny(...)`。MCP 侧 `mcp_tool_call.rs:1710` 把 `Denied | TimedOut | Abort` 合并处理。

**审批粒度与副作用类型的两条独立通道**——官方源码证实：`protocol.rs:1484` 与 `:1498` 是两个不同的协议事件：

```rust
ExecApprovalRequest(ExecApprovalRequestEvent),
ApplyPatchApprovalRequest(ApplyPatchApprovalRequestEvent),
```

即「执行命令」与「应用补丁」走**两条独立的请求/审批链**，而非共用一个通道。`apply_patch.rs` 有自己独立的 `use_legacy_landlock` 处理分支（`tools/runtimes/apply_patch.rs:111`），印证补丁路径与 shell 路径是分离的实现。

**注意一处与本库素材的偏差**：本库记为「等待审批期间连接断开或 Turn 被中断，一律默认 Abort」。源码支持「超时 → 拒绝」「用户 Abort → 中止 turn」，但**连接断开**这一具体场景未能在官方文档或源码注释中定位到对应表述，记入未查到项。

#### Claude Code

官方文档明确的 fail closed 机制：

- `dontAsk` 模式：自动拒绝所有原本会提示的调用；`AskUserQuestion`、`requiresUserInteraction` 的 MCP 工具、组织设为 `ask` 的 connector 工具仍被拒。
- `sandbox.failIfUnavailable: true`：沙箱不可用时**拒绝启动**，而不是退回无沙箱执行。默认是退回无沙箱。
- 沙箱启动失败 ≠ 命令失败。DSH 在这点上做得最清楚，明确区分两种 stderr 分类器：`denialSignatures`（围栏生效、命令被拦）与 `runnerFailureRules`（runner 拒绝或失败、命令根本没跑），并规定「runner failure 意味着命令从未执行，而 denial 意味着围栏正常工作并阻止了它」。消费者必须**先**检查 runner failure。
- 主对话中选 `No` 且不写备注，Claude Code 会停止当前 turn。

**未查到**：Claude Code 侧「审批等待期间 SSH/网络断开」是否有显式 fail-closed 表述。

来源：
- https://github.com/openai/codex/blob/main/codex-rs/protocol/src/protocol.rs（L4146、L4183）
- https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/approvals.rs（L440-475）
- https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/runtimes/zsh_fork/unix_escalation.rs（L350-390）
- https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/sandbox.md
- https://code.claude.com/docs/en/permissions.md

### 5. Enterprise Policy Injection and Bypass Prevention

两家都有真正的「成员绕不过」机制，但**文件路径与锁的粒度差异很大**。

#### Claude Code — `managed-settings.json`

官方系统路径（`code.claude.com/docs/en/managed-settings.md`）：

| 平台 | 路径 |
| --- | --- |
| macOS | `/Library/Application Support/ClaudeCode/managed-settings.json` |
| Linux / WSL | `/etc/claude-code/managed-settings.json` |
| Windows | `C:\Program Files\ClaudeCode\managed-settings.json` |

**⚠️ 本库记录 `C:\ProgramData\ClaudeCode\managed-settings.json`，官方实为 `C:\Program Files\ClaudeCode\managed-settings.json`；官方文档明确写 "Windows 旧路径不会被读取：Windows 旧路径不会被读取：`C:\ProgramData\ClaudeCode\managed-settings.json`"。这是会导致企业策略静默失效的严重错项。**

同目录还支持：
- `managed-settings.d/*.json` —— drop-in 目录，按文件名字母序合并。**列表合并去重**（`permissions.deny`、`sandbox.network.allowedDomains`）、**嵌套对象逐键递归合并**、单值后覆盖前。建议用数字前缀控制顺序（`10-telemetry.json`、`20-security.json`）。
- `managed-mcp.json`
- macOS MDM：domain `com.anthropic.claudecode`
- Windows `HKLM\SOFTWARE\Policies\ClaudeCode`，值名 `Settings`（REG_SZ / REG_EXPAND_SZ）
- Windows `HKCU\SOFTWARE\Policies\ClaudeCode` —— 用户可写，**只能作为无更高管理员配置时的回退**，不算正式 admin source
- Server-managed settings（claude.ai 控制台 / 自托管 gateway），**每小时轮询**

**优先级（高→低）**：Remote settings → MDM/OS policy → managed settings 文件（含 drop-in）→ Windows HKCU。默认 `"first-wins"`：只选最高优先级且至少提供一个 policy key 的来源，忽略其他（`/status` 的 `Skipped sources` 会列出被跳过的）。`"merge"` 模式需 v2.1.242+，且必须把 `managedSourcesBehavior = "merge"` 放在最高优先级的管理员来源里。

**防绕过锁**（这些键只能由受管来源设置，写进用户/项目设置不生效）：

| 键 | 作用 |
| --- | --- |
| `allowManagedPermissionRulesOnly` | 受管策略成为**唯一**权限规则来源；忽略用户/项目/本地规则、`--allowedTools`、host 提供的 allow rules 与 `additionalDirectories` |
| `permissions.disableBypassPermissionsMode: "disable"` | 禁用 `bypassPermissions`。值无效时按**限制性值**处理而非静默放宽 |
| `disableAutoMode: "disable"` | 移出 auto mode 切换循环 |
| `allowManagedHooksOnly` / `allowManagedMcpServersOnly` | 只允许受管 hooks / MCP |
| `disableSideloadFlags` | 启动时拒绝 `--plugin-dir`、`--plugin-url`、`--agents`、`--mcp-config` |
| `strictPluginOnlyCustomization` | 阻止用户/项目来源的 skills、agents、hooks、MCP |
| `forceRemoteSettingsRefresh` | 阻止 CLI 启动直到远程设置重新获取，**获取失败则退出** |
| `sandbox.allowUnsandboxedCommands: false` | 忽略 `dangerouslyDisableSandbox`，沙箱成为 admin-required |
| `sandbox.network.allowManagedDomainsOnly` | 只认 managed 的 `allowedDomains` 与 `WebFetch(domain:)` |
| `sandbox.filesystem.allowManagedReadPathsOnly` | 只认 managed 的 `allowRead` |
| `policyHelper` | 指定启动时计算受管策略的可执行程序 |

**admin-required 沙箱**：满足任一条件即触发——managed `sandbox.allowUnsandboxedCommands: false` / `--settings` 中该项为 false 且 managed 未设 true / managed `sandbox.network.allowManagedDomainsOnly: true`。此时仓库配置里的放宽项全部被忽略：`sandbox.excludedCommands`、`sandbox.ignoreViolations`、`sandbox.network.allowedDomains`、`allowUnixSockets`、`httpProxyPort`、`socksProxyPort`、`sandbox.filesystem.allowWrite`、`Edit(...)` allow、`permissions.additionalDirectories`、`WebFetch(domain:...)` allow，以及仓库把 `sandbox.enabled`/`failIfUnavailable` 设为 false。**但仓库的 deny 条目与 `sandbox.autoAllowBashIfSandboxed` 仍会应用**（除非 managed 另行锁定）。

**仅少数键是「更严格的下级值仍有效」而非锁定**：`maxEffortLevel`（所有来源取最低）、`useAutoModeDuringPlan`、`syncClaudeAiSkills`、`syncClaudeAiPlugins`、`enableArtifact`（任一来源 false 即全关）、`attribution`。**受管 `model` 只是默认值**，`--model` 与 `ANTHROPIC_MODEL` 仍可覆盖——要真限制模型须部署 `availableModels`。

**绕过面上的真实缺口**（官方自己承认）：
- Headless（`claude -p`）与 Agent SDK 会话**不显示 workspace trust 对话框**，因此项目 `.claude/settings.json` 的 Allow 规则与 `additionalDirectories` 不生效；但 hooks、环境变量、项目 Skill 的 `allowed-tools` 仍可能运行，`.mcp.json` 服务器可能无需项目批准即连接。缓解手段：`--setting-sources user`、`--bare`、`--settings '{"disableAllHooks": true}'`、`disabledMcpjsonServers`。
- Dev container 提交到仓库只是团队约定——官方明说「Claude Code 并不要求用户必须从容器启动」，防绕过要靠 MDM / software allowlisting。

#### Codex — `requirements.toml`

| 平台 | 路径 |
| --- | --- |
| Unix（含 Linux/macOS） | `/etc/codex/requirements.toml` |
| Windows | `%ProgramData%\OpenAI\Codex\requirements.toml` |
| macOS MDM | `com.openai.codex:requirements_toml_base64` |

两种机制区分得很清楚：
- **Requirements（admin 强制，用户不可覆盖）**：约束 approval policy、approvals reviewer、sandbox mode、permission profiles、web search mode、managed hooks、可启用的 MCP server、可添加/安装/刷新的 plugin marketplace 来源。**冲突时客户端回退到兼容值并通知用户**——不是报错，是静默降级。
- **Managed defaults（托管默认值）**：只是启动时的初始值，**用户可在运行中改**，下次启动才重新应用。官方明确建议「用 managed defaults 做标准化，不要用它做合规强制」。

关键键：`allowed_approval_policies`、`allowed_approvals_reviewers`、`allowed_sandbox_modes`、`allowed_permission_profiles`、`default_permissions`、`allowed_web_search_modes`、`allow_managed_hooks_only`（**仅 `requirements.toml` 支持，写进 `config.toml` 无效**）、`enforce_residency`、`allowed_login_methods`、`allowed_chatgpt_workspaces`、`experimental_network`、`[features]` 表可钉 feature flags。`[rules] prefix_rules` 可对 shell 入口强制 prompt。

**cloud-managed requirements 的 fail closed**：拉取失败或超时且无有效 identity-matched 缓存时，**cloud config bundle load 返回错误，而非静默在缺少该层的情况下启动**。

MCP allowlist 要求**名称与身份同时匹配**，否则禁用。

#### Others

- **Gemini CLI**：系统级 `settings.json` 可设 `"tools": {"sandbox": "docker"}` 强制容器沙箱、`tools.core` 白名单（只留 `ReadFileTool`/`GlobTool`/`ShellTool(ls)` 等）、`mcp.allowed` 白名单、`enforcedAuthType`、`telemetry.logPrompts: false`。
- **Cline**：`CLINE_COMMAND_PERMISSIONS` 环境变量注入策略，`deny` 覆盖 `allow`，`allowRedirects` 默认 false（**默认禁止 shell 重定向**，这是个少见但很到位的默认）。
- **DSH**：有 config patch 分层（Bundle → Profile Patch → Harness home patch → CLI `--patch`），但**未查到**独立的「企业 managed settings」强制层——这是四家里企业管控最弱的一环。

来源：
- https://code.claude.com/docs/en/managed-settings.md
- https://developers.openai.com/codex/enterprise/managed-configuration/（WebSearch 快照）
- https://developers.openai.com/codex/config-advanced（WebSearch 快照）
- https://developers.openai.com/codex/hipaa-configuration（WebSearch 快照）
- https://google-gemini.github.io/gemini-cli/docs/cli/enterprise.html
- https://docs.cline.bot/cli/configuration

### 6. Boundary Between Sandbox and Permissions

**沙箱管「能不能」，权限管「该不该」，但两者的判定者不同，且权限层先于沙箱层执行。**

- 判定者不同：沙箱由**操作系统**（Seatbelt / bubblewrap / 内核）在命令运行期间强制；权限由**Claude Code / Codex 进程本身**在命令执行前评估。官方原文："权限规则在命令执行前评估；沙箱限制由操作系统在命令运行期间执行。"
- 顺序：权限层先判——若权限已 `Deny`，根本不进沙箱；沙箱只对已被放行的动作施加 OS 级边界。
- 关键的反向依赖：**沙箱可以被用来消解审批疲劳**。Claude Code 的 `sandbox.autoAllowBashIfSandboxed`（**默认 `true`**）意味着「已受沙箱保护的 Bash 命令不再显示权限提示」。逻辑是：既然 OS 已限制住这个命令的破坏范围，就不必再问人。这是「用『能不能』的确定性去替代『该不该』的人工判断」，也正是审批疲劳的主要解法。
- 但同一文档列出了这条捷径的例外，说明它不是等价交换：显式 deny 始终有效；`rm`/`rmdir` 触碰 critical path 仍走常规流程；**内容限定的 ask 规则仍会提示**（如 `Bash(git push *)`）；裸 `Bash` ask 规则通常被跳过但仍适用于无沙箱路径；Plan mode 不跳过。
- 沙箱不管什么：沙箱**只覆盖 shell 命令**。`Read`/`Edit`/`Write`、`WebFetch`/`WebSearch`、hooks、本地 MCP servers、plugin monitors、LSP servers、status line、`apiKeyHelper`、Mods 及其启动的进程、Computer use、用户在 `!` shell-mode 输入的命令——全部在沙箱外。官方两条硬提醒：`filesystem.denyRead` **不能**阻止内置 `Read` 工具；`network.allowedDomains` **不能**限制内置 `WebFetch`。Subagent 不是独立进程隔离边界，与父会话同一进程体系、仅复用同一沙箱配置。

### 7. Can Prompt Injection Be Prevented at This Layer

**核实结论：不能。权限模型不是提示注入的防御层。**

本库记录的 **Meta Muse Glimmer 在 Siren AgentDojo 上攻击成功率 28.4%** 已核实为真，且是 **Meta 自行披露（self-reported）** 的数据。对照组：Gemma 4-31B 为 25.6%，Qwen 3.6-27B 为 40.3%；Glimmer utility 94.2 为三者最高。CI Memories 违规率 Glimmer 26.4 vs Gemma 12.1（越低越好），此项更差。注意 `llm-stats.com` 的排行榜只有 1 个模型、0 个已验证结果，是纯自报数据转载，不可用作跨模型比较。

关键点：**28.4% 说的是模型层的鲁棒性，与权限模型无关**。第三方评测方给出的建议恰恰印证了这个边界——"put injection filtering, tool allowlists, and human approval gates around any agent with write access or credentials. The model is the reasoning layer; the security perimeter is still yours to build."

OpenAI 官方系统卡则把网络默认关闭直接当作注入缓解措施来陈述：默认沙箱 "Disable network access by default: This significantly reduces the risk of prompt injection attacks, data exfiltration"——注意这是**降低外泄通道**，不是防住注入本身。

所以权限层能做的，是把「被注入后能造成的破坏」压到最小：默认无网络、写权限限制在 workspace（Codex）、凭据 deny（Claude Code 需**显式配置**，无内置凭据 deny list）。这三项都是**限制爆炸半径**，不是**阻止注入**。

来源：
- https://awesomeagents.ai/reviews/review-muse-glimmer
- https://ai2.work/blog/meta-s-muse-glimmer-30b-open-agent-model-on-a-single-laptop-gpu
- https://llm-stats.com/benchmarks/siren-agentdojo-attack-success
- https://deploymentsafety.openai.com/gpt-5-3-codex/conversation-monitor
- https://deploymentsafety.openai.com/gpt-5-2-codex/agent-sandbox

---

## Comparison of Implementations Across Vendors

### Summary Table

| 维度 | Claude Code | OpenAI Codex | DSH (deepseek-harness) | OpenCode |
| --- | --- | --- | --- | --- |
| **沙箱形态** | macOS **Seatbelt**；Linux/WSL2 **bubblewrap** + network namespace + `socat` + 可选 seccomp；原生 Windows 不支持。底层 `@anthropic-ai/sandbox-runtime` | macOS **Seatbelt**（`sandbox-exec -p`）；Linux **bwrap + seccomp**（默认，Landlock 为 `use_legacy_landlock` legacy 回退）；Windows 原生沙箱（`unelevated`/`elevated`）+ WSL2 走 Linux 实现 | `dsh-sandbox-local`：Linux **bwrap/Landlock**、macOS **Seatbelt**、Windows **ACL restricted-token**；`fs-sandbox` 自述为策略围栏非内核边界 | 无内置 OS 级沙箱 |
| **默认是否开沙箱** | **默认关闭**（`sandbox.enabled` 需显式开启） | **默认开**，`sandbox_mode = "read-only"`；推荐 `workspace-write` + `on-request` | 部署默认 **`read-only`**（fail-safe）；要可写须显式 opt-in `workspace-write` | 无 |
| **权限配置方式** | `permissions.allow/ask/deny` 规则；`Tool(param:value)`；Git ignore 风格路径；`PreToolUse` hook | `config.toml` 的 `approval_policy` / `sandbox_mode` / `[sandbox_workspace_write]` / `[permissions.<name>]` / `.rules` (Starlark) | YAML 插件配置 + `ctx.sandboxPolicy` + `ctx.approval`；`tools/pre-execute` waterfall 返回 `allow/deny/ask` | `permission` 对象语法，按工具名 + glob 模式 |
| **审批粒度** | once / 按仓库+命令永久；**文件编辑审批只到会话结束**；复合命令最多存 5 条规则 | 5 种决策：`Approved` / `ApprovedForSession`（会话缓存）/ `ApprovedExecpolicyAmendment`（写 rules）/ `ApprovedMcpPolicyAmendment`（跨会话）/ `NetworkPolicyAmendment` | **只有 `allowed-once`** | once / `always`（仅当前会话） |
| **fail-closed** | `dontAsk` 全拒；`sandbox.failIfUnavailable` 拒绝启动；选 `No` 停 turn | **`ReviewDecision::default() == Denied`**（源码）；`TimedOut → Rejected`；`Abort → TurnAborted`；规则冲突取最严 `forbidden > prompt > allow` | `ApprovalOutcome` 闭合枚举含 `unavailable`；**「callers fail closed unless it is `allowed-once`」**；`never` 策略确定性 `rejected`，且在 waterfall 分发**之前**强制，后注册 `prepend` 的 answerer 也无法绕过 | 未见显式 fail-closed 表述 |
| **企业管控** | `managed-settings.json`（macOS `/Library/Application Support/ClaudeCode/`、Linux `/etc/claude-code/`、**Windows `C:\Program Files\ClaudeCode\`**）+ `managed-settings.d/` + MDM plist + HKLM/HKCU + server-managed；约 20 个「只能由受管来源设置」的锁 | `/etc/codex/requirements.toml`（Windows `%ProgramData%\OpenAI\Codex\`）+ MDM `com.openai.codex:requirements_toml_base64` + cloud bundle；**冲突时静默回退到兼容值**并通知 | 仅 config patch 分层（Bundle→Profile→home patch→CLI），**无独立企业强制层** | 未查到独立企业层 |
| **特色机制** | ①`sandbox.credentials` 凭据 **deny / mask**（mask 用 per-session sentinel + 代理在允许主机注入真值，需 `tlsTerminate`）②OS 层 **protected paths**（`.git/hooks`、`.claude/`、`~/.claude.json`、`.credentials.json`；session 内新建 `HEAD`/`objects`/`refs` 会被沙箱删除；符号链接指向也拒写）③`excludedCommands` 移出沙箱 ④`dangerouslyDisableSandbox` + `Bash(dangerouslyDisableSandbox:true)` 强制提示 ⑤bash 网络规则剥离 `timeout/time/nice/nohup/stdbuf/command/builtin/noglob` 与安全 env 前缀 | ①**rules 的 argv 级匹配 + tree-sitter 安全拆分线性脚本**（`git add . && rm -rf /` 不会被整体放行）②`approvals_reviewer = "auto_review"` 由 reviewer subagent 自动审批 ③`approval_policy = { granular = {...} }` 按类别允许/自动拒绝 ④`codex sandbox {macos,linux,windows}` 可本地测试沙箱，含 `landlock` 别名 ⑤permission profiles（`:read-only` / `:workspace` / `:danger-full-access`）替代旧 sandbox 设置 | ①**per-call 策略携带**：`SandboxExecutionPolicy` 按调用传，provider 状态不变，同一时刻 bash 与子 Agent 可在不同边界 ②`SandboxEnforcement = 'full' \| 'partial'` 诚实上报，老 Landlock ABI 与 Windows ACL 归为 partial ③denial 签名按后端区分（bwrap EROFS / Landlock EACCES / Seatbelt EPERM），拒绝用跨后端并集 ④`writableRoots` 单一来源同时喂 fs 围栏与 Seatbelt profile，防漂移 ⑤审计事件 log-only，不进模型 transcript | ①**`doom_loop` 权限**：同一工具调用重复 3 次即触发（默认 ask）②`external_directory` 独立权限键 ③`*.env`/`*.env.*` 默认 deny、`*.env.example` 默认 allow ④每 agent 可覆写权限，Markdown frontmatter 即可配置 |
| **默认权限取向** | Manual 模式：只读工具免批，**Bash/文件编辑/WebFetch/WebSearch 首次均需批准** | read-only 沙箱 + 无网络 | read-only | **默认宽松**：多数权限 `"allow"` |

### Supplement: Products with Divergent Approaches

| 产品 | 独特之处 |
| --- | --- |
| **Gemini CLI** | 唯一把 **Seatbelt profile 做成 5 档命名预设**：`permissive-open`（默认，写限制+允许网络）/ `permissive-closed`（写限制+无网络）/ `permissive-proxied`（写限制+代理上网）/ `restrictive-open` / `restrictive-closed`。可在项目 `.gemini/sandbox-macos-<name>.sb` 放自定义 profile。Linux 上用 Docker/Podman + `SANDBOX_SET_UID_GID`、`SANDBOX_FLAGS`。沙箱失败有专用 exit code **44 `FatalSandboxError`**（41 认证 / 42 输入 / 44 沙箱 / 52 配置 / 53 turn 超限）。`DEBUG`/`DEBUG_MODE` 被自动排除出项目 `.env`，须用 `.gemini/.env` |
| **Cline** | `--auto-approve` 在 CLI 下**默认为 true**（需显式关）；`CLINE_COMMAND_PERMISSIONS` 的 `allowRedirects` **默认 false**，直接禁 shell 重定向；shadow Git repo checkpoint 作为「让 auto-approve 变可行」的补偿机制 |
| **Aider** | 无沙箱、无参数级权限。确认只有一个 `--yes-always` / `AIDER_YES_ALWAYS`，粒度最粗。相关：`--auto-accept-architect`（默认 **True**）、`--dry-run`、`--suggest-shell-commands`、`--check-model-accepts-settings`、`--verify-ssl`、`--lint`/`--test-cmd`。**Git 集成是补偿机制而非权限机制** |
| **Cursor** | 未查到官方权限/沙箱专页 |
| **DSH** | 另有 `guard` 包（`repeat-tool-reminder`、`timeout-policy`），但那是行为提醒与超时，不是权限围栏 |

---

## Pitfalls and Easy Mistakes

### 1. 'Sandbox Means Safe' Is a Misconception

Claude Code 官方文档自己列了 12 条限制，挑最该记住的：

1. **只覆盖 shell 命令**——文件工具、Web 工具、MCP、hooks、LSP、Mods 都不在 Bash 沙箱保护内。`filesystem.denyRead` 拦不住内置 `Read`；`network.allowedDomains` 拦不住内置 `WebFetch`。
2. **默认读取范围很宽**——默认可读机器大部分内容，含 `~/.ssh`、`~/.aws/credentials`；**环境变量含 secrets 也被继承**。没有内置凭据 deny list，必须显式配 `sandbox.credentials`。
3. **默认不检查 TLS 内容**——内置代理按客户端提交的 hostname 判断，**不终止 TLS**。官方警告宽泛域名可能成为外泄路径，可被 domain fronting 之类手段绕过。要强保证须自建终止 TLS 且检查内容的 proxy 并把 CA 装进沙箱。
4. **自定义 proxy 会接管过滤责任**——一旦设置 `sandbox.network.httpProxyPort`/`socksProxyPort`，`allowedDomains`/`deniedDomains`/`strictAllowlist`/域名审批/local-address 检查**全部不再应用于经过该代理的流量**。只配 HTTP 而没配 SOCKS，则 SOCKS 流量也不受域名列表保护。
5. **Unix socket 可能导致沙箱绕过**——尤其 `/var/run/docker.sock`。且 seccomp 在 Claude Code 是**可选依赖**，缺失时无法可靠阻止。
6. **Subagent 不是隔离边界**。
7. 沙箱管不了**提示注入**（见 §1.7）。

**「开沙箱就安全」的真正含义**：沙箱降低的是**破坏范围**，不是**风险总量**。它降低不了数据外泄（内容照样出网）、降低不了模型被注入后作出的错误决策、也降低不了「宽泛写权限导致的权限提升」。

### 2. Default Values per Vendor (Huge Differences, Easy to Trip Up)

| 产品 | 默认 | 踩坑方向 |
| --- | --- | --- |
| **Claude Code** | 沙箱**关闭**；`autoAllowBashIfSandboxed` **默认 `true`**；`allowUnsandboxedCommands` 默认允许无沙箱重试；`failIfUnavailable` 默认**退回无沙箱**而非失败 | 一旦 `enabled: true` 就以为万事大吉，实际同时获得了「沙箱内免审批」——两个默认叠加的组合效应容易超出预期。企业必须同时设 `failIfUnavailable: true` + `allowUnsandboxedCommands: false` 才构成门禁 |
| **Codex** | `sandbox_mode = "read-only"`（**偏保守**）、网络关闭；`approval_policy` 在 `exec` 子命令下**强制 `never`**；`allow_login_shell` 默认 true | `codex exec` 永不提示；旧 `codex exec --full-auto` 已是 deprecated 兼容路径并会打警告 |
| **DSH** | 沙箱 `read-only`、approval `ask` | 双重保守 |
| **OpenCode** | **默认宽松**：多数权限 `"allow"`，仅 `doom_loop` 与 `external_directory` 默认 `ask`；`read` allow 但 `.env` 系列 deny；`--auto` 自动批准所有非显式 deny | **默认全放行**。四家里默认最宽松的一家 |
| **Gemini CLI** | `permissive-open`（**允许网络**）；`--auto-approve` 类 yolo 需显式 | 默认档位带网络 |
| **Cline** | `--auto-approve` **默认 true**；`allowRedirects` 默认 false | 默认近乎无人值守 |
| **Aider** | `--auto-accept-architect` 默认 True；`--yes-always` 存在 | 无沙箱 |

一个反直觉的细节：**OpenCode 的规则是「最后匹配者胜」（last matching rule wins），Claude Code 是「deny → ask → allow」固定顺序**。这意味着在 OpenCode 里，把 `"*": "deny"` 写在末尾会覆盖掉前面所有具体 allow——**规则顺序即优先级**，与 Claude Code 的「规则宽泛程度不改变优先级」正好相反。这是跨产品迁移配置时最容易出事的地方。

### 3. Which Operations Should Never Be Auto-Approved

综合各家机制，以下应在任何自动放行配置中显式 deny 或强制 prompt：

- **版本控制的外向操作**：`git push`、force push、`git clean -f`（尤其 `-fd`）。`git log *` 与 `git *` 的差距是安全量级差异——官方文档专门警告 `Bash(git *)` 会放行 `git -c <script> diff` 这类形态。
- **凭据与配置读取**：`.env`、SSH 私钥、云凭据、token。Claude Code **无内置 deny list**，`sandbox.credentials` 默认什么都不拦。
- **包发布**：`npm publish`、`cargo publish`、镜像推送。
- **shell 入口本身**：`bash -c`、`sh -c`、`zsh -c`。Codex `requirements.toml` 的 `[rules] prefix_rules` 官方示例正是对 `["bash","sh","zsh"]` 强制 `prompt`——因为 shell 入口能把任意动作藏进一个字符串。
- **递归删除**：`rm -rf *`、`find -delete`、`find -exec`。注意 Claude Code 中带 `-exec`/`-delete` 的 `find` **不会**被 `Bash(find *)` 自动批准（官方专门说明），这是刻意的。
- **提权与系统变更**：`sudo`、`chmod`、`systemctl`、包管理器安装全局包。
- **沙箱逃逸路径**：`excludedCommands` 覆盖的解释器（`python`、`node`、`sh`）、能改项目文件的脚本、以及任何 `docker *`。官方警告：模型可能先改脚本再让脚本在沙箱外跑。
- **控制面自身**：`.claude/`、`.git/hooks`、`.git/config`、`~/.claude/settings.json`。Claude Code 已用 OS 层 protected paths 挡住，Codex 把 `.git/`、`.codex/` 在可写根内设为只读（故 `git commit` 默认会失败并要求批准）。

### 4. Approval Fatigue: How to Design Granularity

这是真实且有据的问题——OpenAI 官方文档明确把「降低审批疲劳」列为沙箱的设计目标之一："The sandbox reduces approval fatigue. Instead of asking you to confirm every low-risk command, the agent can read files, make edits, and run routine project commands within the boundary you already approved."

可操作的四条：

1. **用沙箱换审批，而不是用审批换安全**。开启沙箱并让 `autoAllowBashIfSandboxed` 生效，把「低风险」从主观判断变成 OS 可判定的属性。这是最有效的一招。
2. **给读和写不同待遇**。只读 Bash 命令（`ls`/`cat`/`grep`/`git status` 等）在 Claude Code Manual 模式下本就不提示——先确保只读清单覆盖你的实际工作流。
3. **授权范围宁窄勿宽，但一次授权要够用**。Claude Code 复合命令按子命令分别存规则、上限 5 条，说明设计上倾向于生成精确规则；OpenCode 的 `always` 只覆盖工具建议的前缀（如 `git status*`）。反面教材是 `Bash(git *)`。
4. **把安全网做在审批之外**。Cline 的做法值得借鉴：shadow Git checkpoint 让「先放行、错了回滚」变成低成本选项，从而真正敢开 auto-approve——**降低撤销成本比增加审批摩擦更有效**。
5. **企业场景直接关掉通道而非依赖判断**。`dontAsk`（全拒）、`approval_policy = "never"`、`ApprovalPolicy = 'never'`、Gemini 强制 `sandbox: "docker"`。无头场景下「不询问」必须是确定性拒绝，不能是「没问就当同意」。

### 5. Fundamental Differences Between Local and Cloud Agents

**根本差异在信任边界的位置，不在功能多少。**

| | 本地 Agent | 云端 Agent |
| --- | --- | --- |
| 信任边界 | Agent 与**用户本机**之间。模型输出经本地进程落地到用户文件系统与凭据 | Agent 与**厂商托管环境**之间。用户机器上不存在执行面 |
| 爆炸半径 | 直接是用户本机 | 限于该次任务的环境与凭据 |
| 违规成本 | 触及真实凭据、真实仓库、真实网络 | 触及临时容器与短期 token |
| 隔离手段 | 沙箱 + managed settings（**用户同时是防线构建者和防线绕过者**） | 托管容器 / microVM，**用户无法绕过也不需要配置** |
| 特有风险 | 沙箱配置被用户误配；managed settings 缺失即全量失效；本地 MCP/hooks 是沙箱外的后门 | 供应链与租户隔离；`system-prompt` 类内容面；云侧配置对用户不可见 |

**因此企业落地的关键差异是**：本地 Agent 的权限控制是一个「**必须被强制**」的问题，因为防线构建者和绕过者是同一个人；而 Codex 官方那句「If a value conflicts with an enforced rule, the local client **falls back to a compatible value and notifies the user**」，在便利性上是优点，在安全审计上是一个需要警惕的点——**静默降级需要集中采集这些通知才能发现策略没落地**。

云端侧 Codex 用两阶段运行时收窄注入面：setup 阶段可联网装依赖，agent 阶段默认离线，且**secrets 只在 setup 阶段可用、进入 agent 阶段前移除**。Claude Code Cloud sessions 类似：GitHub token 存在沙箱外的独立代理里，沙箱内只拿到 scope 受限的仓库凭据。

来源：https://learn.chatgpt.com/docs/sandboxing、https://developers.openai.com/codex/agent-approvals-security、https://code.claude.com/docs/en/sandbox-environments.md（均为 WebSearch 官方页快照）

---

## Conflicts with Existing Material in This Repository (Must Be Fixed)

| # | 本库记录 | 官方实为 | 严重度 |
| --- | --- | --- | --- |
| 1 | Claude Code managed settings Windows 路径 `C:\ProgramData\ClaudeCode\managed-settings.json` | **`C:\Program Files\ClaudeCode\managed-settings.json`**。官方文档明确写旧路径 `C:\ProgramData\...` **不会被读取** | **高**（企业策略静默失效） |
| 2 | DSH 基础配置 78 个插件条目 | **94 个**（`packages/bundle/base/cordis.patch.yml`，4 空格缩进 `- id:` 计数）。仓库 pushed 2026-10-03 | 中（计数过期） |
| 3 | DSH `minimal` preset 私有 realm 提供裸 `fs-local`（非 `fs-sandbox`） | **`minimal.patch.yml` 里已完全没有 fs 相关插件**（只有 `persona` + persistent shell/terminal group）。同时 **base 配置已改用 `fs-sandbox`**（`base/cordis.patch.yml:518`），不再是 `fs-local` | **高**（整条结论已失效） |
| 4 | Linux Agent 沙箱主流做法是 Landlock + seccomp | **当前主流是 bubblewrap**。Codex 默认 `bwrap + seccomp`，Landlock 是 `use_legacy_landlock` legacy 回退；Claude Code 文档完全不提 Landlock；DSH 是 `bwrap/Landlock` 并列 | 中 |
| 5 | Codex 等待审批期间「连接断开」默认 Abort | 源码支持「**超时 → 拒绝**」「用户 Abort → TurnAborted」「`ReviewDecision::default() == Denied`」；**「连接断开」未查到官方对应表述** | 中（机制描述需精确化） |
| 6 | Claude Code 权限模式四选一 | 实为**六个**：`default` / `acceptEdits` / `bypassPermissions` / `plan` / **`auto`**（后台分类器审查）/ **`dontAsk`**（自动拒绝）。后两个是本库未收录的新增模式 | 中 |
| 7 | Codex `approval_policy` 含 `untrusted` | 官方 config-reference 标注 **`on-failure` is deprecated**；HIPAA 文档写 "Don't set `approval_policy = "untrusted"` directly; Codex and ChatGPT Work no longer support that setting"，但 `untrusted` 仍在 enum 与 `allowed_approval_policies` 中。**文档内部存在不一致** | 低（官方自身矛盾，需注明） |

---

## Items Not Found

1. ~~**Codex `features.use_legacy_landlock` 的官方页面原文**。~~ **已解决（2026-10-05 补）**：官方 `codex-rs/core/config.schema.json` 中存在 `$.features.use_legacy_landlock`（`{"type": "boolean"}`），紧邻的还有 `$.features.use_linux_sandbox_bwrap`。两条路径均在 `[features]` 表下。源码链路：`core/src/tools/sandboxing.rs:418` → `config().use_legacy_landlock()`（`thread_manager_tests.rs:1374` 可见调用点）→ `tools/runtimes/{unix_escalation,apply_patch}.rs`。此前列为未查到的原因是只搜了 `config.md` / `config-reference` 的网页快照，**没查仓库内的生成 schema**——教训：官方仓库里的机器可读 schema 比文档页更权威。
2. **Codex「审批等待期间连接断开」的 fail-closed 官方表述**。源码只证实超时与 Abort 路径。
3. **Codex `codex sandbox landlock` 别名的官方文档原文**。仅见于 WebSearch 快照的一句括注「the platform helpers have aliases (for example `codex sandbox seatbelt` and `codex sandbox landlock`)」，未取到独立章节。
4. **Claude Code 审批等待期间 SSH/网络断开的 fail-closed 表述**。文档只覆盖 `dontAsk`、`failIfUnavailable`、选 `No` 停 turn 三种。
5. **Claude Code 各沙箱/权限设置键的精确类型与默认值**。`settings-reference.md` 正文在 `modelSettings` 条目处截断，`Permission settings` 与 `Sandbox settings` 详细分节未取到。已确认存在的键名 38 个沙箱键 + 15 个权限键，但**默认值逐项未证实**（例外：`autoAllowBashIfSandboxed` 默认 `true` 已从 sandboxing.md 确认）。
6. **DSH 企业级 managed/强制策略层**。仅有 Bundle/Profile/home patch/CLI 四层 patch，未查到独立的组织级强制下发机制。
7. **OpenCode 的企业管控层**与 fail-closed 显式机制。
8. **Cursor 官方权限/沙箱文档**。未查到专页。
9. **Muse Glimmer / Siren AgentDojo 的 Meta 官方模型卡原文**。28.4% 数字在 4 个独立二手源一致复现且标注 self-reported，但 `huggingface.co/api` 与 Meta 一手页面本机不可访问，未能取到一手确认。
10. **`permissions.disableAutoMode` 与顶层 `disableAutoMode` 的确切层级**。`settings-reference` 索引中两者同时出现（顶层 `disableAutoMode` 与 `permissions.disableBypassPermissionsMode`），而 `managed-settings` 的「只能由受管来源设置」表中又出现顶层 `allowManagedPermissionRulesOnly`。层级归属未能完全确定。
11. **Codex `untrusted` approval policy 的当前状态**。官方 config-reference 的 enum 含它、HIPAA 文档说「不再支持」，**官方两处表述冲突**，未找到解释性变更说明。

### Blocks Bypassed via Alternative Paths (for Later Review)

| 目标 | 封锁情况 | 实际使用 |
| --- | --- | --- |
| `code.claude.com/docs/en/sandbox` | 404（正确路径是 `sandboxing.md`） | 正确路径直取成功 |
| `docs.claude.com` | 区域重定向拦截 | 全程改用 `code.claude.com` |
| `developers.openai.com/codex/*` | WebFetch 返回 Forbidden | WebSearch 官方页快照，取到 security / sandbox / config-reference / managed-configuration / rules / config-advanced / permissions 全文 |
| `learn.chatgpt.com/docs/*` | WebFetch 部分 fetch failed | WebSearch 快照兜底 |
| `raw.githubusercontent.com` | 本机不可达（HTTP 000） | GitHub REST API → 限流 → **稀疏 clone**（`--depth 1 --filter=blob:none --sparse`）直读源码，此路径最可靠 |
| GitHub REST API | 未认证 403 限流 | 同上 |

**一条方法论教训**：Codex 的 `use_legacy_landlock` 一开始在「未查到项」里，因为只搜了 `config.md` 与 config-reference 的**网页快照**。后来在克隆下来的仓库里找到 `codex-rs/core/config.schema.json`，里面是机器可读的完整配置 schema，`$.features.*` 全部键名与类型一应俱全。**官方仓库里的生成 schema 比文档页更权威**——文档页会截断、会滞后，schema 不会。下次核实配置项应优先找 schema 文件。

## Incidental Verification (for [Compaction](/docs/CS/AI/LLM/Agent/Theory/Compaction.md) cross-reference)

[Compaction](/docs/CS/AI/LLM/Agent/Theory/Compaction.md) 的未查到项里有一条「DSH `minimal` preset 不加载 compaction」，本轮克隆源码时可确认：

- `packages/bundle/web-app/presets/minimal.patch.yml` 中 `compaction` 出现 **0 次**，只含 `persona` + persistent shell/terminal group；
- `standard.patch.yml` 中出现 5 次，其中 `compaction-basic`、`command-compact`、`tool-result-pruner` 被包在一个 `isolate: { compaction: true, toolResultPruner: true }` 的 `cordis:group` 里（各自独立 realm），`tool-result-pruner` 带 `thresholdChars: 8192` / `headChars: 4096`；
- `base/cordis.patch.yml` 里有 `compaction-basic`（L341）、`compaction-tool-result-pruner`（L419）、`compaction-image-offload`（L428）三个条目。

**结论：`minimal` 确实不加载 compaction，该条记录成立**，可从 Compaction 的未查到项中移出。

## References

1. [Claude Code — Sandboxing](https://code.claude.com/docs/en/sandboxing.md)
2. [Claude Code — Sandbox environments](https://code.claude.com/docs/en/sandbox-environments.md)
3. [Claude Code — Permissions](https://code.claude.com/docs/en/permissions.md)
4. [Claude Code — Settings reference](https://code.claude.com/docs/en/settings-reference.md)
5. [Claude Code — Managed settings](https://code.claude.com/docs/en/managed-settings.md)
6. [Claude Code — Hooks](https://code.claude.com/docs/en/hooks.md)
7. [Claude Code — Debug your configuration](https://code.claude.com/docs/en/debug-your-config)
8. [anthropics/sandbox-runtime](https://github.com/anthropics/sandbox-runtime)
9. [OpenAI Codex — Agent approvals & security](https://developers.openai.com/codex/agent-approvals-security)
10. [OpenAI Codex — Rules（exec policy）](https://developers.openai.com/codex/rules)
11. [OpenAI Codex — Configuration reference](https://developers.openai.com/codex/config-reference)
12. [OpenAI Codex — Advanced configuration](https://developers.openai.com/codex/config-advanced)
13. [OpenAI Codex — Managed configuration](https://developers.openai.com/codex/enterprise/managed-configuration/)
14. [OpenAI Codex — Permissions（permission profiles, beta）](https://developers.openai.com/codex/permissions)
15. [openai/codex — codex-rs/protocol/src/protocol.rs（ReviewDecision，L4146/L4183）](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/protocol.rs)
16. [openai/codex — codex-rs/protocol/src/approvals.rs](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/approvals.rs)
17. [openai/codex — codex-rs/core/src/tools/approvals.rs](https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/approvals.rs)
18. [openai/codex — codex-rs/core/src/tools/sandboxing.rs](https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/sandboxing.rs)
19. [openai/codex — codex-rs/core/config.schema.json（`$.features.*` 权威键名）](https://github.com/openai/codex/blob/main/codex-rs/core/config.schema.json)
20. [openai/codex — codex-rs/linux-sandbox/src（bwrap.rs / landlock.rs）](https://github.com/openai/codex/tree/main/codex-rs/linux-sandbox/src)
21. [openai/codex — codex-rs/core/src/tools/runtimes/zsh_fork/unix_escalation.rs](https://github.com/openai/codex/blob/main/codex-rs/core/src/tools/runtimes/zsh_fork/unix_escalation.rs)
22. [deepseek-ai/deepseek-harness — docs/subsystems/sandbox.md](https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/sandbox.md)
23. [deepseek-ai/deepseek-harness — docs/subsystems/approval.md](https://github.com/deepseek-ai/deepseek-harness/blob/main/docs/subsystems/approval.md)
24. [deepseek-ai/deepseek-harness — packages/fs/fs-sandbox/README.md](https://github.com/deepseek-ai/deepseek-harness/blob/main/packages/fs/fs-sandbox/README.md)
25. [deepseek-ai/deepseek-harness — packages/sandbox/sandbox-policy/README.md](https://github.com/deepseek-ai/deepseek-harness/blob/main/packages/sandbox/sandbox-policy/README.md)
26. [deepseek-ai/deepseek-harness — packages/bundle/base/cordis.patch.yml（94 条基础配置）](https://github.com/deepseek-ai/deepseek-harness/blob/main/packages/bundle/base/cordis.patch.yml)
27. [deepseek-ai/deepseek-harness — packages/bundle/web-app/presets/minimal.patch.yml](https://github.com/deepseek-ai/deepseek-harness/blob/main/packages/bundle/web-app/presets/minimal.patch.yml)
28. [OpenCode — Permissions](https://opencode.ai/docs/permissions/)
29. [Gemini CLI — Sandboxing](https://google-gemini.github.io/gemini-cli/docs/cli/sandbox.html)
30. [Gemini CLI — Configuration](https://google-gemini.github.io/gemini-cli/docs/get-started/configuration)
31. [Gemini CLI — Enterprise](https://google-gemini.github.io/gemini-cli/docs/cli/enterprise.html)
32. [Cline — CLI configuration](https://docs.cline.bot/cli/configuration)
33. [Cline — Checkpoints](https://docs.cline.bot/core-workflows/checkpoints)
34. [aider — Options reference](https://aider.chat/docs/config/options.html)
35. [Meta GPT-5.3-Codex System Card — Agent sandbox](https://deploymentsafety.openai.com/gpt-5-3-codex/conversation-monitor)
36. [Muse Glimmer 模型卡数据转述（awesomeagents.ai）](https://awesomeagents.ai/reviews/review-muse-glimmer)
37. [Siren AgentDojo 排行榜（llm-stats，注意仅自报数据）](https://llm-stats.com/benchmarks/siren-agentdojo-attack-success)