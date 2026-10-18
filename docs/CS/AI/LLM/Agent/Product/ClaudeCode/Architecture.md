## Introduction

Claude Code 是 Anthropic 官方的终端 agentic 助手：模型负责推理，工具负责行动，Claude Code 本身是包在外面的一层——提供工具、管理模型看到的上下文。官方文档把这层外围直接称为 **agentic harness**，与 [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) 理论篇的抽象精确对应，那篇的「三层定位」与「四大失败模式」可以直接拿来读本文。

本文是其内部机制的架构拆解，事实基线为 npm `@anthropic-ai/claude-code` **2.1.302**（2026-10-16 发布，stable 通道 2.1.292），全部结论来自官方文档 `code.claude.com/docs`（2026-10-18 核实）。Claude Code 的官方 GitHub 仓库 [`anthropics/claude-code`](https://github.com/anthropics/claude-code) 现已公开——内含官方插件、marketplace、示例配置（如 HIPAA settings）、CHANGELOG 与 SECURITY 政策，但**不含**应用本身的 TypeScript 源码；核心客户端仍是编译型 npm 包，因此本文的「实现细节」仍以官方文档的明确陈述为准，不凭记忆推断。

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

### Default Permission Mode Is Not Fixed

「自动进auto 模式」这件事分四步走完，且**每一版覆盖的会话类型不同**，是典型的「存在 ≠ 生效」陷阱：

| 版本 | 覆盖范围 |
| :--- | :--- |
| 2.1.283 | 交互式会话（终端 / VS Code）在第三方 provider 或 telemetry 关闭时 |
| 2.1.284 | 交互式会话扩展到**所有套餐与 provider**，不再限第三方/telemetry 关 |
| 2.1.285 | `claude -p` 与 Python Agent SDK 在第三方 provider 或 telemetry 关闭时进入auto |
| 2.1.302 | **反向修订**：`-p` 与 SDK 在第三方 provider + telemetry 关闭或全新安装时回到 **`default` 模式**，需显式 `--permission-mode auto` |

`permissions.defaultMode` 始终覆盖上述默认值；一次性的「设为默认」提示也会在用户 settings 另有默认时出现（2.1.285）。

### Claude Apps Gateway

组织可以自建 **Claude apps gateway**（`claude gateway`）作为统一出口与管控点，客户端 `/login` 直通其 SSO 屏幕。它是「本地客户端 + 组织管控」的中枢：

- **upstream 路由**：支持 Anthropic API、Bedrock、Vertex、Foundry、Claude Platform on AWS 与 Mantle；每个 upstream 可配 `models` 白名单（单项内一个 `*` 为通配，failover 时同样受限，2.1.295+）、`timeouts.upstream_ttfb_ms`（限制流式响应多久必须起流，否则 failover 或502）、Bedrock 专属的 `assume_role`（经 STS 扮演 IAM 角色，可跨账号、可每位开发者一个会话）与 `guardrail: {id, version}`（2.1.281+）。
- **策略面**：`managed.policies[]` 里的 `cli` / `code` / `desktop` 三种键各管一类客户端；启动时会拒绝桌面无法使用的 `desktop:` 策略键并点名（2.1.296起）。`/login` 审批页有 Deny 按钮，点掉后等待中的终端数秒内退出，不再挂到超时（2.1.290）。
- **组织级约束**：`allowedProviders` 限定机器可用哪些 provider（2.1.285+）、`availableModels` 为空或漏掉启动模型时启动即告警（2.1.284+）、`managedMcpServers` 的 `envHelper` 路径拒绝 `\??\` 与 `/??/` 形式（2.1.281+）。
- **其他**：`load_test_mode` 让请求构造并签名但不真发上游、客户端拿固定回复，可做部署前的压测（2.1.283+）；`store.readiness_grace_seconds` 让 `/readyz` 扛过短暂的 Postgres 故障切换（2.1.282+）；最低支持 PostgreSQL 由14 降到 11（2.1.290）。遥测转发见 [Observability](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Observability.md)。

### How The Gateway Is Actually Deployed

上一节的能力清单来自 CHANGELOG。官方仓库 `examples/gateway/{aws,gcp}/` 提供了成套部署模板（Dockerfile + Terraform + `gateway.yaml.example` + `setup.sh`），以下是模板坐实的部分——**包含若干 CHANGELOG 与文档都不会说的事实**。

**运行时形态**：镜像**不构建二进制**，而是期待构建上下文里已有一个预编译的原生 `linux-x64` / `linux-arm64` `claude` 可执行文件（`setup.sh` 按 `DIST_URL`/`DIST_SHA256` 下载并校验）。基础镜像是 `gcr.io/distroless/cc-debian12:nonroot`，**按 digest 钉死**以免静默拿到新的上游字节；用 distroless/cc 而非 scratch 的原因是它提供 glibc + libstdc++——**Claude Code 客户端是 Bun 编译的原生二进制，需要这两个库**。容器以 uid/gid 65532 运行，ENTRYPOINT 是 `claude gateway --config /etc/claude/gateway.yaml`。

**配置注入的两条路线**（AWS 与 GCP 的关键差异，也解释了两种平台各自的限制）：

| | AWS（ECS / EKS） | GCP（Cloud Run / GKE） |
| :--- | :--- | :--- |
| 配置投递 | **烤进镜像** `/etc/claude/gateway.yaml` | 存Secret Manager secret `gateway-config`，**运行时挂载** |
| 改配置的后果 | **必须重建镜像**（`setup.sh` 以配置文件哈希打 tag，重跑即自动重建） | 重新发布 secret 并重新部署，无需重建 |
| 凭据注入 | task definition 的 `secrets` 字段（`valueFrom` → Secrets Manager ARN）作环境变量 | Cloud Run 把 JWT / OIDC / Postgres 注入为环境变量（**Cloud Run 无法把多个 secret 挂到同一目录**），只挂 `gateway.yaml` 本身 |
| 文件挂载 | EKS 上可用 `${file:/secrets/...}` | GKE 上可用 file mounts |

`setup.sh` 会**拒绝在还有 `REPLACE_ME` 占位符时构建/发布**——因为 AWS 侧配置是烤进镜像的，半填的配置会直接上线。配置本身不含密钥，全部凭据在启动时经 `${ENV_VAR}` / `${file:/path}` 展开。

**`gateway.yaml` 的骨架**（AWS + Okta 形态，注释里含大量 why）：

- `listen`：`host` / `port`（目标组把 ALB 的 :443 转到 :8080）/ **`public_url`（必需）** / `trusted_proxies` / 可选 `tls`（让 gateway 自己终止 TLS 而非在 ALB）。
- **`public_url` 为什么必需**：它固定 IdP 的 `redirect_uri`、OIDC discovery 文档与 gateway-token 的issuer，**三者都不从客户端可控的 `Host` 头推导**（`X-Forwarded-Host` / `-Proto` 同样永不受信）。这是把 IdP 与 issuer 从 Host 注入攻击里摘出来的关键一步。
- `trusted_proxies` 为什么必需：经内部 ALB 时每个请求的对端都是 ALB 节点 IP，不配则 `X-Forwarded-For` 不受信，**按 IP 的限流与审计 IP 记的都是负载均衡器而非真实客户端**。模板明确警告其代价——列入 ALB 所在子网即信任那些子网里**任何**能到 ALB 的工作负载都能 spoof 客户端 IP，所以 ALB :443 的入口 CIDR（`corporate_cidr`）不能与这些子网重叠。
- `oidc`：`issuer` / `client_id` / `client_secret` / `allowed_email_domains`（拒掉组织外的 id_token）/ `scopes` / `userinfo_fallback` / 可选 `ca_cert_pem`（IdP 在私有 CA 后）。
- `session`：`jwt_secret`（≥ 32 字节，`openssl rand -base64 32`）、`ttl_hours`（模板取 8，主要**界定离职回收延迟**，向1 调更紧）。数组形态 `[new, old]` 轮转密钥，index 0 签名、全部验证。
- `store`：**必需，缺它 gateway 拒绝启动**（`postgres_url`，`?sslmode=verify-full`）。
- `upstreams`：列表，按**从上到下**在 5xx / timeout / 501 时 failover。
- `telemetry.forward_to`：客户端把 OTLP/HTTP 发给 gateway，gateway **在服务端盖上 `user.id` / `user.email` / `user.groups` 戳**再扇出；`metrics: true` 是安全聚合计数器（默认），`logs: false` 因为它**带 bash 命令与工具输入**，要显式 opt-in。`forward_to` 与 `public_url` 都配好时，gateway **自动把 `CLAUDE_CODE_ENABLE_TELEMETRY` 与 OTel exporter 选择器推给每个客户端**，无需逐人配置。
- `managed.policies[]`：**first-match-wins，自上而下**，所以 catch-all 兜底项必须放最后。
- `admin`：`write_keys` / `read_keys`（命名键用于审计归因，键值≥ 32 字符）或 `admin_groups`；提供后开启 **db-mode 运行时配置 + 花费上限**。

**两个易踩的模型目录坑**：`auto_include_builtin_models` 默认 true，内置表已映射到 `us.anthropic.*` 跨区推理 profile，**仅在美国区可用**。非美区必须置 false 并手列本区 profile（`eu.anthropic.*` / `apac.anthropic.*`），同时把部署侧 `bedrock-invoke` IAM 策略的 geo 前缀放宽。

**一个只有 Dockerfile 里才有的事实**：gateway 的数据库驱动**会读URL 里的 `sslmode`，但不认 libpq 风格的 `sslrootcert=` 参数**——CA 只能经 `NODE_EXTRA_CA_CERTS` 环境变量传入（AWS 侧由 `setup.sh` 把 RDS CA bundle 下载后烤进镜像并信任）。想用 `verify-full` 就必须走这条。

部署形态（ALB + Route 53 私有区 + RDS、ECS/EKS 与 Cloud Run/GKE + Secret Manager、IAM / IRSA / STS `assume_role`）与本库的 [Container](/docs/CS/Container/Container.md)、[Distributed](/docs/CS/Distributed/Distributed.md) 主题相邻——这里只记Claude Code 侧的特有约束：配置烤进镜像 vs 运行时挂载这一取舍，正是「不可变镜像」与「配置外置」两种部署哲学在具体平台约束下的产物（Cloud Run 不能把多个 secret 挂到同一目录，才需要额外的 `gateway-config` secret）。

### Advisor

`/advisor`（Claude Platform on AWS，2.1.300+）是**模型自己决定要不要用的旁路助手**：不显式挑选前不运行，用 `/advisor`、`advisorModel` 或 `--advisor` 选，`CLAUDE_CODE_DISABLE_ADVISOR_TOOL=1` 关闭。它在遥测里以 `serverToolUses` 的形态出现——即 API 侧自己跑的工具调用，mod 可经 `turn.step` hook 读到（见 [Mods](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Mods.md)）。

### Worktree Isolation

`--worktree` 让会话跑在独立 git worktree 里，与主 checkout 的改动隔离（v2.1.277+ 的 skills 回退规则、`/exit` 的 Remove worktree 等都围绕它）。CHANGELOG 里这一块的高频 bug 几乎都指向**新版 git 的引用存储格式**：git 2.56+ 的 reftable 让worktree 创建/恢复、marketplace 重复 clone、新装 git 插件版本显示 unknown、`git_commit_id` 遥测等场景集体出问题（2.1.300–2.1.302）。用 `--worktree` 时若遇到诡异 git 行为，先确认 git 版本是否 ≥ 2.56。

### Cloud And Self-Hosted Runner

cloud session 有两项专属约束与本机不同：

- **保留名**：`widgets` 在 cloud session 与 self-hosted runner 上是保留的 MCP server 名，自建的同名前缀（如 `widgets_`）不再加载（2.1.285）；内置 `gh api` 只接受 github.com，`GH_HOST`/`GH_REPO` 指向别的主机会被拒绝（2.1.290）。
- **Hook 权限差异**：Cowork cloud session 的 auto mode 下，`PermissionRequest` hook **不能再批准 shell 命令或 subagent**——这类提示改为等待或拒绝（2.1.299）；`PermissionRequest` hook 的 allow 里带 `setMode` 更新会被忽略（2.1.300）。

self-hosted runner 有专门命令 `claude self-hosted-runner orchestrator`，`--shutdown-drain-sec` 决定收到 SIGTERM 后给在飞的轮询与 spawn hook 多少秒收尾（2.1.299+）。它把 system prompt 改为**私有文件**而非命令行文本传入，长 prompt 不再导致启动失败——包装器或 `command` hook 若自己追加 `--system-prompt` / `--append-system-prompt`，必须改成对应的 `--system-prompt-file` / `--append-system-prompt-file`（2.1.281）。

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

**空闲压缩（idle compaction）**：除基于上下文大小的自动压缩与手动 `/compact` 外，会话在空闲（无新输入）一段后会自动压缩以保持上下文新鲜；v2.1.302 起可在 `/config` 用 Idle compaction 行开关。它与「填满即压」是两套独立机制，都走 [Compaction](/docs/CS/AI/LLM/Agent/Theory/Compaction.md) 通用公式。

它的**触发阈值是双条件**（2.1.299）：终端里一个 **200K token 以上**的会话空闲**约 54 分钟**才会触发。两个条件都可调——`CLAUDE_CODE_IDLE_COMPACT_MIN_TOKENS` 改token 下限（`"idleCompaction"` 是 settings 里的对应键）。也就是说空闲压缩**不会清理小会话**，这是它与「填满即压」的关键差别：后者与上下文占用量直接挂钩，前者要求上下文已经相当满。

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
- [Claude Code on GitHub](https://github.com/anthropics/claude-code)
