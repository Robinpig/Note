## Introduction

cc-haha、Claude Code、OpenCode 是三条**不同的架构路线**，常被混为一谈。把三者放在一起对照，能看清「桌面复刻」「官方闭源」「开源客户端/服务器」各自的选择与代价。

- **Claude Code** = Anthropic 官方终端 harness，把厂商能力用得最透（基线 `@anthropic-ai/claude-code` 2.1.302，官方仓库已公开但不开放应用源码，详见 [ClaudeCode](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md)）。
- **OpenCode** = 开源（MIT）客户端/服务器架构，内核是本地 HTTP 服务，TUI/Web/IDE 都是客户端，模型无关（基线 npm `opencode-ai` 1.19.2，详见 [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)）。
- **cc-haha** = 开源（MIT）**Claude Code 引擎复刻 + Electron 桌面工作台**（基线 GitHub `main`），在同源 harness 上叠 GUI 层与远程/IM 通道（详见 [CcHaha](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md)）。

> [!WARNING]
> cc-haha 引擎源自修复的 Claude Code 源码，非 Anthropic 官方产品，存在版权与下架风险（详见 [CcHaha 主枢纽](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md)）。本页仅作技术架构对照。

## Three-Way Comparison

| 维度 | Claude Code（官方） | OpenCode（开源） | cc-haha（开源复刻 + 桌面） |
| :--- | :--- | :--- | :--- |
| 开源 / 许可 | 核心闭源（应用是编译的原生二进制），**官方仓库公开**（插件 + mod 实现 + 类型契约 + CHANGELOG） | 开源 MIT（anomalyco） | 开源 MIT（NanmiCoder），引擎源自泄露 CC 源码 |
| 内核形态 | 单进程 CLI + SDK；客户端是 **Bun 编译的原生二进制**（gateway 镜像需 glibc + libstdc++） | 本地 HTTP 服务 + 多客户端 | Electron 桌面 + `claude-haha` 子进程（NDJSON 管道）+ `claude-server` HTTP sidecar |
| 引擎来源 | 官方自研 | 自研 harness | 复刻 Claude Code 引擎（fork） |
| 模型绑定 | 以 Anthropic 为主（也支持 Bedrock / Foundry / 网关） | 任意提供商（含 OpenAI 兼容 / 本地 Ollama·LM Studio） | 模型无关：账号登录 / 预设 / 本地 LM Studio·Ollama / 图像生成 |
| 桌面 / GUI | 有官方桌面 app | 有桌面 app + Web | 核心卖点：多会话工作台 + 内置浏览器预览 + 桌面宠物 + H5 远控 |
| 多会话 | 单会话（/resume 历史） | TUI/Web 多会话 | 多会话工作台 + Cmd+K 全局搜索 + Branch/Worktree 启动 |
| 权限模型 | 6 模式（default/acceptEdits/auto/plan/bypassPermissions/dontAsk） | 13 键三态 allow/ask/deny，默认全放行，「最后匹配者胜」 | 5 档 GUI（default/acceptEdits/auto/plan/bypassPermissions；dontAsk 不可选）+ GUI 审批流 |
| 沙箱 | Bash sandbox（Seatbelt / bubblewrap+socat），默认关闭 | 靠 Plugin 事件钩子做硬拦截 | 继承 CC 引擎沙箱（桌面无独立沙箱层） |
| 组织管控 | 官方内置 `sec-default`：`tool.check` **双跑**让 deny 规则不被插件消掉、19 个钉死环境变量、5 级 tier | 无内建 | 无内建 |
| 多 Agent 编排 | Subagents + agent teams（mailbox 架构，终端呈现） | 双主 Agent（Build/Plan）+ 3 只读子 Agent | ① 桌面 Agent Teams **可视化器**（引擎快照派生）② 引擎 **WorkflowTool 动态编排**：模型写 VM 脚本（agent()/parallel()/pipeline()/phase()）派生 subagent，有 `WORKFLOW_MAX_AGENTS` 上限 + resume 缓存 |
| Computer Use | 官方未内置 | 无 | 有：MCP → Python Bridge → 原生 cu-helper（Swift，fail closed） |
| MCP | 工具延迟加载 | local/remote，OAuth 自动，按 Agent 控可见性 | 可视化管理器：stdio/http/sse + local/project/user scope，后端 `/api/mcp/*` |
| Skill 扩展 | Skills（Agent Skills 标准）+ Plugin marketplace | Skills（渐进加载）+ Plugin 事件钩子 | 可视化市场：**ClawHub + SkillHub 双源聚合**，安装前安全报告（vendor/status/reportUrl） |
| 扩展编程性 | 三个层级：**hooks（JSON）→ mod（进程内 TS，18 命名空间 + 128 事件 + 4 渲染表面）→ 自建工具/命令**；官方仓库有 5 个可读 mod 实现 | Plugin 事件钩子 | 引擎继承 CC 的 hook 能力，桌面层做成 GUI |
| IM / 远控 | Slack 集成 + Remote Control（浏览器遥控，代码仍留本地） | 无 | H5 远控（二维码/配对码）+ **8 平台 IM adapter**（微信/飞书/钉钉/Telegram/WhatsApp/WeCom/QQ/Slack）独立 sidecar |
| 计划任务 | 无内建 | CLI/CI | 有：8 步向导 + 自研 5 字段 cron，headless 执行，日志 json+sqlite |
| 规则文件 | `CLAUDE.md`（全局 `~/.claude/CLAUDE.md`） | `AGENTS.md`（回退 `CLAUDE.md`） | 继承 CC：`CLAUDE.md` + `.claude/` |
| 事实基线 | npm 2.1.302（官方文档 + CHANGELOG + `claude-code.d.ts` 类型契约） | npm 1.19.2 | GitHub `main`（NanmiCoder/cc-haha） |

## Reading Order

- 想看「官方闭源把厂商能力用多透」→ [ClaudeCode](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md)。
- 想看「开源模型无关 + C/S 架构怎么落地」→ [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)。
- 想看「桌面外壳怎么包裹复刻引擎、远程/IM 怎么接」→ [CcHaha](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md) 七分册。

## Links

- [CcHaha 主枢纽](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md)
- [Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md)
- [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)

## References

- [NanmiCoder/cc-haha](https://github.com/NanmiCoder/cc-haha)
- [anomalyco/opencode](https://github.com/anomalyco/opencode)
- [Claude Code 文档](https://code.claude.com/docs/en/overview)
