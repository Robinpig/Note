## Introduction

Claude Code 的权限体系回答一个问题：**哪些操作可以直接做，哪些要问你**。它由两层组成——permission mode（会话基线上「要不要问」）与 permission rules（在基线上叠具体工具的预批准/阻断），再加上独立的 Bash sandbox（OS 强制边界，管「跑起来之后能碰到什么」）。通用机制（沙箱技术形态、fail-closed、审批粒度）见 [Permission 理论篇](/docs/CS/AI/LLM/Agent/Theory/Permission.md)，本文只讲 Claude Code 的产品实现。

事实基线：`@anthropic-ai/claude-code` **2.1.302**（2026-10-16），官方 permissions / permission-modes / sandboxing 三页（2026-10-18 核实）。

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

会话起始模式取第一个适用的来源：`--permission-mode` flag → settings 的 `permissions.defaultMode` → 内置默认。

**v2.1.283 起，交互式终端与 VS Code 会话的内置默认起始模式是 `auto`**（此前是 Manual；更早版本仅 Pro/Max/Team 计划如此）。但「默认进auto」这件事分四版走完、且每版覆盖的会话类型不同，读文档时极易写成过时的全局结论：

| 版本 | 变化 |
| :--- | :--- |
| 2.1.283 | 交互式会话在第三方 provider 或 telemetry 关闭时也进auto |
| 2.1.284 | 交互式会话扩展到**所有套餐与 provider** |
| 2.1.285 | `claude -p` 与 Python Agent SDK 在第三方 provider 或 telemetry 关闭时进 auto |
| 2.1.302 | **反向修订**：`-p` 与 SDK 在第三方 provider + telemetry 关闭或全新安装时回到 **`default`**，要 auto 得显式 `--permission-mode auto` |

其余若干修正：

- project / local settings 里设 `"auto"` **不生效**（落到内置默认），设 `"bypassPermissions"` 也不生效（会话以 Manual 启动）。
- HIPAA 配置的组织默认 Manual（v2.1.285+）。
- flag/settings/内置默认选了 auto 但会话不可用（模型不支持、组织关闭、服务端临时关停）时，会话以 Manual 启动。
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

## Auto Mode In Depth

auto 模式把「问你」换成「问分类器」：一个独立的 classifier 模型在动作执行前审查，拦截超出你请求范围的升级、瞄准不认识的基础设施的动作、或看起来被 Claude 读到的敌意内容驱动的动作。**它减少提示但不保证安全**——用于你信任大方向的任务，不能替代对敏感操作的审查。

### Availability

- 计划：所有计划（v2.1.283+）；更早版本仅 Pro/Max/Team。
- 模型（Anthropic API 与 Claude Platform on AWS）：Opus 4.6+、Sonnet 4.6+、Haiku 5.5 或 Fable 模型。Bedrock / Agent Platform / Foundry / Claude apps gateway 只支持 Sonnet 5+、Opus 4.7+、Haiku 5.5 与 Fable。
- 组织：Team/Enterprise 默认可用，管理员可 `disableAutoMode` 关停。

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
4. 装了的 mod 若处理 `tool.check`，可在第 3 步前批准，classifier 不再检查。

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

classifier 默认跑在 Claude Sonnet 5 上（服务端配置优先；会话模型是 Sonnet 4.6 或 `availableModels` 排除 Sonnet 5 时用会话模型，Fable 会话用 Opus）。客户端分类器模型可用 `CLAUDE_CODE_AUTO_MODE_MODEL` 环境变量指定（v2.1.302 引入，只改客户端分类器、不影响服务端自动模式）。Enterprise 与 API/Bedrock/Foundry 等账户上，classifier 调用计入 token 用量，每次检查带一轮往返；只读与工作目录内编辑跳过 classifier，开销主要来自 shell 命令与网络操作。服务端审查（把审查并进会话的模型请求）则没有单独调用可计——`CLAUDE_CODE_AUTO_MODE_SERVER=0` 可强制只用本地 classifier 请求。

## Bash Sandbox

Bash sandbox 是 **OS 强制**的边界，包住 Claude 跑的 shell 命令及其派生的进程；因为限制在命令运行时由操作系统执行，沙箱内命令可以不经批准直接跑。它只覆盖 shell 命令——Claude 的文件工具、MCP server、hooks 都在沙箱外。

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

- **auto-allow**：沙箱命令不提示直接跑；ask rules（如 `Bash(git push *)`）与 deny rules 仍然生效。
- **regular permissions**：即使沙箱内也照常提示。

### Escape Hatches

- **unsandboxed retry**：命令在沙箱里失败后 Claude 可以请求非沙箱重跑（`allowUnsandboxedCommands` 控制）。
- **strict sandbox mode**：关掉 retry，沙箱失败就是失败。
- **excludedCommands**：匹配的命令跑在沙箱外。
- 你自己在 `!` prompt 输入的命令，多数会话里非沙箱执行——想验证沙箱是否生效，让 Claude 跑探针命令（如 `touch ~/sandbox-probe`、`curl --noproxy '*' https://example.com`），而不是自己敲。

凭证侧还有专门设置：`credentials` 可把 secret 从沙箱命令的环境里遮掉（环境变量掩码、AWS 请求重签名、凭证文件掩码三路）。

## Common Setups

| 想要 | 起手式 | 隔离 |
| :--- | :--- | :--- |
| 每个动作自己审 | `--permission-mode default` | 无 |
| 少提示但不用 classifier | default + Bash sandbox auto-allow | 内置沙箱 |
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
