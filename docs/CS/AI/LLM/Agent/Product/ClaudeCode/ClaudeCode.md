## Introduction

Claude Code 是 Anthropic 官方的终端 agentic 助手：模型推理、工具行动、Claude Code 本身做外面那层 harness——提供工具、管理模型看到的上下文。官方把这层外围直接称为 agentic harness，与 [Harness 理论篇](/docs/CS/AI/LLM/Agent/Theory/Harness.md) 精确对应。除终端外还有桌面 app、VS Code / JetBrains 扩展、claude.ai/code、Slack 与 CI/CD 等界面，底层循环完全相同（见 [Architecture](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Architecture.md)）。

本家族为「主枢纽 + 十四个专题分册」结构，事实基线统一为 npm `@anthropic-ai/claude-code` **2.1.302**（2026-10-16 发布；stable 通道 2.1.292）。结论主要来自官方文档 `code.claude.com/docs`，并已与官方 GitHub 仓库的 CHANGELOG 及 **`mods/types/claude-code.d.ts` 类型契约**全量比对（2026-10-18）——文档给概念，CHANGELOG 给版本边界，类型契约给**精确接口面**（字面量常量、事件联合类型、完整签名）。Claude Code 的核心客户端仍以编译型 npm 包分发，但官方仓库 [`anthropics/claude-code`](https://github.com/anthropics/claude-code) 已公开——内含**mod API 的完整类型契约**、五个可读的官方 mod 实现（`diff` / `sec-default` / `agents-md` / `telemetry`）、官方插件与 marketplace、CHANGELOG 与 SECURITY 政策（应用源码本身未开放）。

## Installation

三种安装通道，**推荐 native install**（后台自动更新）：

```bash
# macOS / Linux / WSL
curl -fsSL https://claude.ai/install.sh | bash
```

```powershell
# Windows PowerShell
irm https://claude.ai/install.ps1 | iex
```

```bash
brew install --cask claude-code        # Homebrew，stable 通道（约晚一周，跳过有重大回归的版本）
winget install Anthropic.ClaudeCode    # WinGet
```

Debian / Fedora / RHEL / Alpine 还支持 apt / dnf / apk。Homebrew 与 WinGet **不自动更新**，要手动 `brew upgrade` / `winget upgrade`；Homebrew 另有 `claude-code@latest` cask 跟 latest 通道。装完 `claude --version` 验证（输出版本号 + `(Claude Code)`）。

登录支持 Claude 订阅（Pro/Max/Team/Enterprise，推荐）、Claude Console（首次登录自动建 "Claude Code" workspace 做成本归集）、Amazon Bedrock / Google Cloud Agent Platform / Microsoft Foundry，以及组织自建的 Claude apps gateway（`/login` 直通网关屏幕走 SSO）。

## Common Commands

斜杠命令全集见官方 cli-reference，日常高频的：

| 命令 | 作用 |
| :--- | :--- |
| `/plan` | 进入 plan mode：只读探索、出方案，批准后才改源码 |
| `/compact` | 手动压缩上下文（可带焦点，如 `/compact focus on the API changes`） |
| `/context` | 看上下文空间被什么占用 |
| `/model` | 切换模型 |
| `/resume` | 选择历史会话继续 |
| `/sandbox` | 配置 Bash sandbox |
| `/permissions` | 权限模式与规则 |
| `/agents` | subagent 管理 |
| `/plugin` | 插件安装与管理（Discover 标签浏览 marketplace） |
| `/doctor` | 安装与配置体检，可自动修复 |
| `/init` | 生成起始 CLAUDE.md |

两个容易被忽略的：`Esc` 随时打断进行中的工具调用；**不打断直接回车**则把消息排队，当前工具调用结束后同一 turn 内读取。

## The Fourteen Companion Volumes

主链路是 [Architecture](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Architecture.md)：三阶段 agentic loop（gather context → take action → verify）、工具五分类、JSONL 会话与 checkpoint、上下文窗口的自动管理，以及运行面（Claude apps gateway 的**部署实况**、cloud/self-hosted runner、advisor、worktree 隔离）。围绕它的十一个专题：

- **[Permission](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Permission.md)**——六个权限模式（**v2.1.283 起 auto 是终端/VS Code 的内置默认起始模式，2.1.302 起 `-p`/SDK 部分回退 `default`**）、auto mode 的后台 classifier（默认拦截清单、decision order、3/20 次回退阈值）、Bash sandbox（Seatbelt / bubblewrap+socat、OS 强制边界）。
- **[Hooks](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Hooks.md)**——33 个生命周期事件、三种 cadence、matcher 与 `if` 的两级过滤语义、五种 handler、exec/shell form，以及 `async` 与 `asyncRewake`（不打断但必回到对话）、`onFailure` 等字段。
- **[Mods](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Mods.md)**——把 hook 写成进程内 TypeScript 的插件形态：模块沙箱契约、18 个命名空间的 `$` 宿主对象、**128 个事件**、四个渲染表面的元素差异、hook 的三个时间配额、五级 tier、testing kit、五个官方 mod 实现。
- **[ModInternals](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ModInternals.md)**——从四个内置 mod 的**真实源码**读出的实现机制：`engine.create` 折叠里**给 `$` 添加自己的 noun**（jQuery `$.fn` 式声明合并）、跨 mod 的 noun 契约与测试 provider 约定、测试文件布局约定、窄宿主接口（`Host`）模式、内置功能退场后插件接手的机制、以及类型契约落后于客户端版本的风险。
- **[Security](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Security.md)**——官方内置组织安全基线 `sec-default` 的设计规格：tier 落座机制、`tool.check` **双跑**如何让 deny 规则不被插件消掉、19 个钉死环境变量、两项管理员选项的 fail-closed 语义。
- **[PluginSpec](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/PluginSpec.md)**——写插件的字段级契约：`plugin.json` 全字段与路径四规则、slash command frontmatter 全字段、命令发现与命名空间、hook 两种 handler 的取舍与退出码语义、`${CLAUDE_PLUGIN_ROOT}` 可移植性、marketplace 分发注意事项。
- **[PluginPatterns](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/PluginPatterns.md)**——官方自己怎么用这些机制：`code-review` 的**按模型档位分层派 agent**（haiku 门禁 / sonnet 汇总 / opus 找 bug）与高信号判据、`feature-dev` 的七阶段编排与只读 agent 权限隔离、`ralph-wiggum` 用 `Stop` hook + `decision:block` 做自主循环、`hookify` 的 Markdown 规则 + Python 引擎范式。
- **[HookPatterns](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/HookPatterns.md)**——官方最大插件 `security-guidance` 的实现拆解：三层安全模型（正则 / LLM diff 审查 / agentic 跨文件审查）、26 条规则清单、prompt injection 防御、`asyncRewake` 接法、代码组织范式，以及它与 auto classifier 的机制对照。
- **[Memory](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Memory.md)**——CLAUDE.md 四层作用域与拼接式加载、`@path` 导入、`.claude/rules/` 路径限定、auto memory、AGENTS.md 互通、967K 压缩触发点。
- **[Subagents](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Subagents.md)**——subagent 的独立上下文与定义方式、内置 Explore/Plan/general-purpose、agent teams 的 mailbox 架构与 agent 间消息的信任边界。
- **[Extensions](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Extensions.md)**——Skills（Agent Skills 标准 + 动态上下文注入）、Plugins（marketplace、三档 scope）、MCP（工具延迟加载）、Output styles（四种内置风格）、官方插件清单。
- **[Observability](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Observability.md)**——OpenTelemetry 导出的事件表与字段（`api_request` / `user_prompt` / `tool_decision` / `tool_result`）、内容捕获的门控开关、GenAI 语义约定、gateway 转发。
- **[Headless](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Headless.md)**——`claude -p` 非交互运行、`--bare` 确定性模式、SIGTERM/SIGINT 退出语义、GitHub Actions 的双模式与准入检查。

版本更新后的补漏用仓库脚本 `scripts/cc_changelog_route.py`：把官方 CHANGELOG 的 Added/Changed 条目按主题路由到各分册，输出「哪些条目可能落进哪篇」的机械清单。

## Common Issues

- **`claude` 找不到**：安装目录不在 PATH，按官方 Fix your PATH 处理；PowerShell 里 `&&` 报错说明在用 PowerShell 而非 CMD（反之 `irm` 不识别是在 CMD）。
- **安装脚本 403 / syntax error**：对照官方 Troubleshoot installation 换安装方式。
- **指令不生效**：CLAUDE.md 是 context 不是强制配置——矛盾指令会被任意选一条、压缩可能吃掉早期指令；要硬阻断用 `PreToolUse` hook，用 `/doctor prompt-audit` 查过时/冲突内容。
- **上下文反复被填满**：单文件过大导致 thrashing 错误时，把大文件拆小或改用 skill/rules 按需加载，别指望压缩兜底。
- **hook 没反应**：matcher 加在不支持的事件上被静默忽略；`if` 加在非工具事件上 hook 不运行；`once: true` 在 settings 文件里被忽略。
- **auto 模式不可用**：查模型要求（Opus 4.6+/Sonnet 4.6+/Haiku 5.5/Fable）与 `disableAutoMode` 设置；服务端可能临时关停，换会话重试。

## Links

- [Architecture](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Architecture.md)
- [Permission](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Permission.md)
- [Hooks](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Hooks.md)
- [Mods](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Mods.md)
- [Security](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Security.md)
- [PluginSpec](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/PluginSpec.md)
- [Memory](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Memory.md)
- [Subagents](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Subagents.md)
- [Extensions](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Extensions.md)

## References

- [Claude Code documentation](https://code.claude.com/docs/en/overview)
- [Quickstart](https://code.claude.com/docs/en/quickstart)
- [CLI reference](https://code.claude.com/docs/en/cli-reference)
- [Claude Code on GitHub](https://github.com/anthropics/claude-code)
