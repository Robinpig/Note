## Introduction

Claude Code 的权限体系回答一个问题：**哪些操作可以直接做，哪些要问你**。它由两层组成——permission mode（会话基线上「要不要问」）与 permission rules（在基线上叠具体工具的预批准/阻断），再加上独立的 Bash sandbox（OS 强制边界，管「跑起来之后能碰到什么」）。通用机制（沙箱技术形态、fail-closed、审批粒度）见 [Permission 理论篇](/docs/CS/AI/LLM/Agent/Theory/Permission.md)，本文只讲 Claude Code 的产品实现。

事实基线：`@anthropic-ai/claude-code` **2.1.326**（从 2.1.302 基线升级；本轮核实 `CHANGELOG.md` 的 2.1.302→2.1.326 区间与 `mods/types/claude-code.d.ts` 权限类型）。

## Six Modes

| 模式 | 不问就跑 | 定位 |
| :--- | :--- | :--- |
| `default` | 只读 | 每个动作自己审；敏感工作 |
| `acceptEdits` | 读 + 文件编辑 + 常见文件命令（`mkdir`/`touch`/`mv`/`cp` 等） | 边审边改 |
| `plan` | 读 + auto 可用时 classifier 批准的命令 | 改代码前先探索 |
| `auto` | 一切，带后台安全检查 | 长任务、消灭提示疲劳 |
| `dontAsk` | 工作目录内读文件 + 预批准工具；**其余原本会提示的一律拒** | 锁死的 CI 与脚本 |
| `bypassPermissions` | 一切 | 仅限隔离容器/VM |

两个命名坑：CLI 里显示为 **Manual** 的那个模式，config value 是 `default`（hooks 与 SDK 集成都用这个值），`manual` 是 CLI 接受的别名；**`dontAsk` 字面像「不询问就放行」，实际是「不询问就拒绝」**——语义完全相反。

### Starting Mode

**起始 mode 不再有「内置默认 = auto」这种静态答案——它由服务端下发的 `defaultMode` / 组织策略决定**（v2.1.326 起）。判定顺序：

1. `--permission-mode` flag 最高优先。
2. 未显式设 mode 的会话先按 auto 起步；**设置加载完成后改用服务端下发的 `defaultMode`**（v2.1.326）。
3. 设置加载失败且无本地副本、或策略失败/要求时，回退 Manual（v2.1.326）。组织策略尚未加载时，终端与 VS Code 会话仍以 auto 起步（v2.1.326）。

「默认进 auto」这件事分多版走完，且每版覆盖的会话类型不同，读文档时极易写成过时的全局结论：

| 版本 | 变化 |
| :--- | :--- |
| 2.1.283 | 交互式会话在第三方 provider 或 telemetry 关闭时也进 auto |
| 2.1.284 | 交互式会话扩展到**所有套餐与 provider** |
| 2.1.285 | `claude -p` 与 Python Agent SDK 在第三方 provider 或 telemetry 关闭时进 auto |
| 2.1.302 | **反向修订**：`-p` 与 SDK 在第三方 provider + telemetry 关闭或全新安装时回到 **`default`**，要 auto 得显式 `--permission-mode auto` |
| 2.1.323 | `--permission-mode auto` 或 settings `defaultMode: auto` 在 auto 不可用时，改为从 **Manual**（会先询问）启动，不再进入更宽松模式 |
| 2.1.326 | **再修订**：默认进 auto 的会话在设置加载后改用服务端下发的 `defaultMode`；设置加载失败且无本地副本 / 策略失败或要求时回退 Manual |

其余若干修正：

- project / local settings 里设 `"auto"` **不生效**（落到内置默认），设 `"bypassPermissions"` 也不生效（会话以 Manual 启动）。
- **HIPAA 配置**：v2.1.285+ 默认 Manual；**v2.1.326 反转**——Claude Code + Cowork HIPAA 配置的组织，终端与 VS Code 会话默认以 auto 启动，`disableAutoMode` 可关闭；直连 Anthropic API 时同样由服务端 classifier 审查动作。
- flag/settings/内置默认选了 auto 但会话不可用（模型不支持、组织关闭、服务端临时关停）时，会话以 Manual 启动（v2.1.323 起；此前会进入更宽松模式）。
- 管理员可用 managed settings 的 `permissions.disableAutoMode: "disable"` 移除 auto，或 `disableBypassPermissionsMode: "disable"` 禁掉 bypass；`allowedProviders` 可限定机器能用哪些 provider（v2.1.285+）。
- cloud session 的 auto 更严：Cowork cloud session 下 `PermissionRequest` hook **不能再批准 shell 命令或 subagent**，这类提示改为等待或拒绝（v2.1.299）；hook 的 allow 里带 `setMode` 更新被忽略（v2.1.300）。

## Rules On Top

mode 只是基线，rules 在其上叠加。几条硬语义：

- **deny rules 在所有模式生效，包括 bypassPermissions**；ask rules 匹配的工具任何模式都不自动批准。
- **allow rules 在 bypassPermissions 里无效**（已经全放行了）。
- deny/ask 规则不作用于 `EndConversation`——只要 Claude 还有别的工具可调。

任何模式（含 bypassPermissions）都不自动批准的操作：

- ask rule 匹配的工具；组织设为 ask 的 connector 工具。
- 需要用户交互的工具：内置 `AskUserQuestion`、MCP 里标了 `requiresUserInteraction` 的工具。
- 针对关键路径的 `rm`/`rmdir`（如 `rm -rf /`、`rm -rf ~`）——没有 allow rule 或 `PreToolUse` hook 的 "allow" 能批准它。
- 跨会话消息传递的安全机制。
- `blockReadsOutsideWorkingDirectories` 开启时读工作目录外的路径（v2.1.257+）：识别为文件读取的 Bash 命令即使在 auto 与 bypass 模式也会提示；沙箱内执行且沙箱执行阻断时不提示。
- `permissions.blockWritesOutsideWorkingDirectories`（v2.1.314+）：Write / Edit / NotebookEdit 在**所有权限模式**下拒绝工作目录外的路径（含 auto 与 bypassPermissions）。
- `permissions.denyInsteadOfPrompting`（v2.1.319+）：本会等待权限提示的调用改为**直接拒绝并让 turn 继续**，适用于终端会话、subagent 与 teammate。

## Auto Mode In Depth

auto 模式把「问你」换成「问分类器」：一个独立的 classifier 模型在动作执行前审查，拦截超出你请求范围的升级、瞄准不认识的基础设施的动作、或看起来被 Claude 读到的敌意内容驱动的动作。**它减少提示但不保证安全**——用于你信任大方向的任务，不能替代对敏感操作的审查。

### Availability

- 计划：所有计划（v2.1.283+）；更早版本仅 Pro/Max/Team。
- 模型（Anthropic API 与 Claude Platform on AWS）：Opus 4.6+、Sonnet 4.6+、Haiku 5.5 或 Fable 模型。Bedrock / Agent Platform / Foundry / Claude apps gateway 只支持 Sonnet 5+、Opus 4.7+、Haiku 5.5 与 Fable。
- 组织：Team/Enterprise 默认可用，管理员可 `disableAutoMode` 关停。
- **遥测 / feature flag 关闭或接第三方 LLM 网关**（v2.1.319+）：auto 对服务端无法检查的调用改为**询问或拒绝，不再回退本地分类器**；要保留本地分类器必须设 `CLAUDE_CODE_AUTO_MODE_SERVER=0`（强制只用本地 classifier）。Bedrock / Vertex / Foundry 不受此变化影响。

### Classifier Default Blocklist

classifier 信任会话启动时配置的工作目录与 remotes——会话中途 `git remote add`/`set-url` 进来的 remote 不算信任。默认阻止：

- 下载并执行代码（`curl | bash`）；向外部端点发敏感数据。
- 生产部署与迁移；云存储大规模删除；授予 IAM 或仓库权限；修改共享基础设施。
- 不可逆销毁会话开始前就存在的文件；force push。
- 提交/推送会把 secret 或敏感数据送出仓库的改变（含 CI 工作流、deploy 配置、读取 secret store 外发的脚本——**任何分支都查，公开仓库也查**，commit 或 push 即触发）。
- `git reset --hard`、`git checkout -- .`、`git restore .`、`git clean -fd`、`git stash drop`、`git stash clear`；`git commit --amend`（HEAD commit 不是本会话建的，或已被推送过；仅改 message 且本会话创建的不拦）。
- `terraform destroy` / `pulumi destroy` / `cdk destroy` / `terragrunt destroy` 及销毁资源的 apply。
- 写 secret manager、改 DNS 记录或 TLS 证书；合并没有人类批准的 PR、批准 Claude 自己的 PR、禁用 CI 检查。
- 给自动化下命令的评论（atlantis apply、bot 的 /deploy /merge）；生产 feature flag 的开关/灰度/删除。
- 对受保护 IaC scope 的基础设施变更、排空并移除集群节点；波及未命名资源的共享集群写入（label selector、`--all`）。
- 创建每节点运行或拦截集群流量的 K8s 资源（DaemonSet、admission webhook）；对敏感远端目标的交互式 shell 或端口转发；把本地服务暴露到公网的隧道/反向 shell。
- 把实时凭证或 token 打印进 transcript 或文件；访问标为敏感数据位置的地点、从其中拷出数据或发给被排除的受众。

几个例外通道：push 到当前仓库任何分支、创建符合请求的 PR 默认不提示（除非落入上面的拦截清单）；**对话里说出来的边界**（「别 push」「部署前等我 review」）classifier 当拦截信号，**对话里说出来的批准**可以解除对应拦截——但必须点名动作及其危险细节（「你可以 force-push」这种只点动词的清不了阻塞），且默认只覆盖点名的那一个动作。边界不是规则：classifier 每轮从 transcript 重读，压缩可能把声明边界的消息挤掉——硬保证请用 deny rule。

### Decision Order

每个动作按固定顺序判定，第一个命中的步骤胜出：

1. 命中 allow/ask/deny 规则的立即结算。例外：受保护路径的写入即使 allow 命中也路由给 classifier；关键路径 rm/rmdir 没有 allow 能批准；`requiresUserInteraction` 与组织 ask 的 connector 工具直接提示你；带 per-command allowed domains 的 shell 命令路由给 classifier（规则批准的是命令不是域名）。
2. 只读动作与工作目录内的文件编辑自动批准（受保护路径写入、首次读工作目录外除外）。
3. 其余交给 classifier（关键路径移除按默认处理走）。
4. 装了的 mod 若处理 `tool.check`，可在第 3 步前批准，classifier 不再检查。mod 的 `tool.check` 回答可用 `decider: "person"`：只有权限对话框或宿主回调能批准这个 ask，无人可问时以 mod 的 reason 拒绝（v2.1.304+）。

第 4 步是一个明显的口子——`tool.check` 上任何 hook 都能回答任何裁决，那么「用来消掉提示」的插件岂不也能消掉 deny 规则？**在组织管控的机器上不会**，机制是**双跑**：先照原样跑一遍链，若发现裁决被改写过（改写 = 更宽松，或同样裁决换了理由；收紧不算），就把 user 层整个摘掉再跑一次（`next.to(e, "append")`）；这个裁决没过任何个人插件，规则在其中被求值，两次跑只差user 层，所以差异即证明改写。deny 一律替换掉链的答案，ask 则在点名了背后是什么（`rule` / `hook` / `setting` / `ceiling` / `decider`）时被原样返回。完整规格见 [Security](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Security.md)。

注意这条保护**管不到个人安装的 classic `PreToolUse` hook**——引擎在那时根本不发起 ask，`tool.check` 不会跑。这与「没装任何插件」时一模一样。

classifier 的审查范围：Claude Code 自己发的 classifier 请求里，classifier 看得到用户消息、工具调用（只读查询除外）与 CLAUDE.md 内容，**工具结果被剥掉**——文件或网页里的敌意内容无法直接操纵 classifier。`PostToolUse` hook 可用 `classifierContext` 字段给调用结果附上应用侧上下文（v2.1.236+）。另有一个服务端探针在 Claude 读之前先扫工具结果里的可疑内容。

### Fallbacks

- 动作被拦：`/permissions` 的 Recently denied 标签列出，按 `r` 可手动批准重试。
- **连续拦 3 次或累计 20 次**（阈值不可配，累计计数器只在触发回退时重置）：auto 暂停，恢复提示，批准被提示的动作即恢复 auto。无提示可回的 `-p` 运行则是动作不跑、Claude 继续干活。
- classifier 无裁决（安全检查拒掉 classifier 自己的请求、或响应无法解析）：直接拒绝动作，无通知、无 Recently denied 条目。
- 服务端审查无裁决：拒绝该动作，连续 10 个无裁决响应后停掉本 turn。
- 检查待定时切换模式：新模式不会请求的裁决被丢弃，改为提示或（dontAsk）自动拒绝。

### Cost And Latency

classifier 默认跑在 Claude Sonnet 5 上（服务端配置优先；会话模型是 Sonnet 4.6 或 `availableModels` 排除 Sonnet 5 时用会话模型，Fable 会话用 Opus）。客户端分类器模型可用 `CLAUDE_CODE_AUTO_MODE_MODEL` 环境变量指定（v2.1.302 引入，只改客户端分类器、不影响服务端自动模式）。Enterprise 与 API/Bedrock/Foundry 等账户上，classifier 调用计入 token 用量，每次检查带一轮往返；只读与工作目录内编辑跳过 classifier，开销主要来自 shell 命令与网络操作。服务端审查（把审查并进会话的模型请求）则没有单独调用可计。`CLAUDE_CODE_AUTO_MODE_SERVER` 决定走哪路分类器：`0` **强制只用本地 classifier 请求**（本地分类器计入用量），`1` 打开服务端审查；该变量在直连 Anthropic API 的会话同样生效（v2.1.326 明确）。结合上文的 v2.1.319 变化：遥测关闭 / 网关场景下若不放 `0`，服务端无法检查的调用不会回退本地分类器，而是询问或拒绝。

## Type Contracts

权限裁决的类型契约可从 `mods/types/claude-code.d.ts` 原文核对——几个最容易被写错的点如下（片段按该版本原样摘取，路径不带行号）。

`PermissionMode` 恰好六值，`dontAsk` 的语义见上文（不询问即拒绝）；紧随其后的 `PermissionRequestDecision` 说明 classic hook 只能回答 allow / deny 两态：

```ts
  /**
   * Permission mode for controlling how tool executions are handled. 'default' - Standard behavior, prompts for dangerous operations. 'acceptEdits' - Auto-accept file edit operations. 'bypassPermissions' - Bypass all permission checks (requires allowDangerouslySkipPermissions). 'plan' - Planning mode, no actual tool execution. 'dontAsk' - Don't prompt for permissions, deny if not pre-approved. 'auto' - Use a model classifier to approve/deny permission prompts.
   */
  type PermissionMode = 'default' | 'acceptEdits' | 'bypassPermissions' | 'plan' | 'dontAsk' | 'auto';

  /**
   * A `classic.PermissionRequest` answer's `decision`, as the classic hook's
   * `hookSpecificOutput.decision`: allow (with a rewrite or rules) or deny.
   *
   * Off the person's machine a mod's update stands unless it is `setMode`, loosens
   * a device tool, or lifts a deny or ask or removes an exception on a shell, Read,
   * Write, Edit, Glob, Grep or TaskStop. A restarted cloud worker has none of the
   * session allow rules the mod added. Its directory lifts no forwarded call's block.
   */
  export type PermissionRequestDecision = {
      behavior: 'allow';
      updatedInput?: Record<string, unknown>;
      updatedPermissions?: PermissionUpdates;
  } | {
      behavior: 'deny';
      message?: string;
      interrupt?: true;
  };
```

`PreToolUseDecision` 是四态：`allow`、`ask`、`deny`、以及三者全空（交回正常权限流程）——不是三态：

```ts
  export type PreToolUseDecision = {
      /**
       * Lets the call run without a permission prompt (the managed-settings
       * hooks ran first; a deny from them ended the chain above).
       */
      allow: true;
      ask?: undefined;
      deny?: undefined;
  } | {
      /**
       * Asks the user before the call runs; the text is shown as the reason.
       */
      ask: string;
      allow?: undefined;
      deny?: undefined;
  } | {
      /**
       * Refuses the call; the model receives the text as the reason.
       */
      deny: string;
      allow?: undefined;
      ask?: undefined;
  } | {
      allow?: undefined;
      ask?: undefined;
      deny?: undefined;
  };
```

`tool.check` 的裁决与结果是 `ToolCheckDecision = 'allow' | 'ask' | 'deny'`、`ToolCheckResult = { decision, reason?, rule?, hook?, setting?, plugin?, ceiling? }`：`decision` 必填，其余可选；`plugin` 由引擎在 hook 回答 ask 时写入且 pinned（hook 自写被丢弃），`ceiling` 来自组织对连接器工具设的上限。`e.isReadOnly` 是工具自报的只读声明——注释明确它不是「无副作用」的证明：fetch、发消息、委派给 agent 都会自报只读，MCP 工具的声明来自其 server 且未经证实；缺位也只表示工具无法声明，谨慎的 hook 应把它当写操作（该事件字段 v2.1.304 新增）：

```ts
      /**
       * Set by the engine, present only when the tool's own `isReadOnly` holds
       * this input read-only, and pinned; a matcher can select reads, never writes.
       *
       * Absent also means the tool cannot say: a careful hook reads it as a write.
       * It is the tool's word, no proof of no effect (a fetch, a sent message, an
       * agent that delegates all say it); an MCP tool's is its server's, unproven.
       */
      isReadOnly?: true;
```

## Bash Sandbox

Bash sandbox 是 **OS 强制**的边界，包住 Claude 跑的 shell 命令及其派生的进程；它只覆盖 shell 命令——Claude 的文件工具、MCP server、hooks 都在沙箱外。**反直觉点：v2.1.325 起沙箱内的 Bash 命令默认走正常权限流程，不再自动放行**；要恢复静默运行须显式设 `sandbox.autoAllowBashIfSandboxed: true`（由 managed settings 开启沙箱时，要在最高优先级的 managed 来源里也设该值）。

### Platform And Dependencies

| 平台 | 机制 |
| :--- | :--- |
| macOS | 内置 Seatbelt 框架 |
| Linux / WSL2 | bubblewrap（文件系统隔离）+ socat（网络中继）；可选 seccomp 过滤器堵 Unix domain socket |
| 原生 Windows | 不支持（命令非沙箱跑）；要沙箱得在 WSL2 里跑 Claude Code |

Claude Code 的沙箱基于开源包 **`@anthropic-ai/sandbox-runtime`**（seccomp 过滤器可 `npm install -g @anthropic-ai/sandbox-runtime` 装上）。Ubuntu 24.04+ 的默认 AppArmor 策略会阻止 bwrap 建 user namespace，需要给 `/usr/bin/bwrap` 加一个带 `userns` 的 profile。WSL2 上沙箱命令启动 Windows 二进制（`cmd.exe`、`/mnt/c/` 下的东西）是通过 Unix socket 交给宿主的，要堵得装 seccomp 过滤器。

### Defaults

| 访问 | 默认 | 改它 |
| :--- | :--- |
| 写 | 工作目录 + per-user 临时目录 + `--add-dir`/`/add-dir` 加的目录；受保护路径始终拒写 | `filesystem.allowWrite` / `denyWrite` |
| 读 | 大半个机器，**含凭证文件如 `~/.ssh`、`~/.aws/credentials`** | `filesystem.denyRead` / `credentials` |
| 网络 | 无直连路由；连本机代理，按 allowed domains（默认空）逐个查 host | `network.allowedDomains` / `deniedDomains` |
| 环境变量 | 继承 Claude Code 的环境（含其中的 secret） | `credentials`、`CLAUDE_CODE_SUBPROCESS_ENV_SCRUB` |

开启：会话里 `/sandbox`（选模式，存进 `.claude/settings.local.json`）或 settings 里 `sandbox.enabled: true`。**默认关闭**；依赖缺失或平台不支持时默认退化为非沙箱运行，要硬失败就设 `sandbox.failIfUnavailable: true`。

### Two Sandbox Modes

- **regular permissions**（v2.1.325 起的**默认**）：沙箱内命令照常走权限提示。
- **auto-allow**：需显式设 `sandbox.autoAllowBashIfSandboxed: true`；此时沙箱命令不提示直接跑，但 ask rules（如 `Bash(git push *)`）与 deny rules 仍然生效。

### Escape Hatches

- **unsandboxed retry**：命令在沙箱里失败后 Claude 可以请求非沙箱重跑（`allowUnsandboxedCommands` 控制）。
- **strict sandbox mode**：关掉 retry，沙箱失败就是失败。
- **excludedCommands**：匹配的命令跑在沙箱外。
- 你自己在 `!` prompt 输入的命令，多数会话里非沙箱执行——想验证沙箱是否生效，让 Claude 跑探针命令（如 `touch ~/sandbox-probe`、`curl --noproxy '*' https://example.com`），而不是自己敲。
- **沙箱状态的持续性**（v2.1.326+）：Bash sandbox 在会话中按 cwd 持有状态，直到你运行 `/sandbox` 或 `/cd`；其间 Bash 可能先询问。
- **批准时的命令改写**（v2.1.326+）：权限 hook 或 SDK 宿主在批准时改写过的命令，若原命令是按沙箱检查的，改写后仍留在沙箱内；批准者可加 `dangerouslyDisableSandbox: true` 让它跳出沙箱。

凭证侧还有专门设置：`credentials` 可把 secret 从沙箱命令的环境里遮掉（环境变量掩码、AWS 请求重签名、凭证文件掩码三路）。

## Common Setups

| 想要 | 起手式 | 隔离 |
| :--- | :--- | :--- |
| 每个动作自己审 | `--permission-mode default` | 无 |
| 少提示但不用 classifier | default + Bash sandbox（须设 `sandbox.autoAllowBashIfSandboxed: true`，v2.1.325+） | 内置沙箱 |
| 先探索再改 | `--permission-mode plan` | 无 |
| auto 放手跑 | `--permission-mode auto` | 无；沙箱/容器是纵深 |
| CI 精确 allowlist | `-p "..." --permission-mode dontAsk --allowedTools "Bash(npm test)" "Read"` | CI runner 自带 |
| 容器内全无人值守 | `-p "" --dangerously-skip-permissions` | **必须**容器/VM；Linux/macOS 上以非 root 跑 |

## Links

- [ClaudeCode 主枢纽](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md)
- [Permission 理论篇](/docs/CS/AI/LLM/Agent/Theory/Permission.md)
- [Hooks](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Hooks.md)
- [Codex 审批与沙箱](/docs/CS/AI/LLM/Agent/Product/Codex/Approval.md)

## References

- [Claude Code permissions](https://code.claude.com/docs/en/permissions)
- [Permission modes](https://code.claude.com/docs/en/permission-modes)
- [Bash sandboxing](https://code.claude.com/docs/en/sandboxing)
