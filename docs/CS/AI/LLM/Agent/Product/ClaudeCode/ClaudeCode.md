## Introduction

Claude Code 是 Anthropic 官方的终端 agentic 助手：模型推理、工具行动、Claude Code 本身做外面那层 harness——提供工具、管理模型看到的上下文。官方把这层外围直接称为 agentic harness，与 [Harness 理论篇](/docs/CS/AI/LLM/Agent/Theory/Harness.md) 精确对应。除终端外还有桌面 app、VS Code / JetBrains 扩展、claude.ai/code、Slack 与 CI/CD 等界面，底层循环完全相同（见 [Architecture](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Architecture.md)）。

本家族为「主枢纽 + 七个专题分册」结构，事实基线统一为 npm `@anthropic-ai/claude-code` **2.1.301**（2026-10-15 发布；stable 通道 2.1.292），全部结论来自官方文档 `code.claude.com/docs`（2026-10-16 核实）。Claude Code 闭源，细节以官方文档明确陈述为准。

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

## The Seven Companion Volumes

主链路是 [Architecture](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Architecture.md)：三阶段 agentic loop（gather context → take action → verify）、工具五分类、JSONL 会话与 checkpoint、上下文窗口的自动管理。围绕它的六个专题：

- **[Permission](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Permission.md)**——六个权限模式（**v2.1.283 起 auto 是终端/VS Code 的内置默认起始模式**）、auto mode 的后台 classifier（默认拦截清单、decision order、3/20 次回退阈值）、Bash sandbox（Seatbelt / bubblewrap+socat、OS 强制边界）。
- **[Hooks](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Hooks.md)**——33 个生命周期事件、三种 cadence、matcher 与 `if` 的两级过滤语义、五种 handler、exec/shell form，以及 `async` / `onFailure` 等新字段。
- **[Memory](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Memory.md)**——CLAUDE.md 四层作用域与拼接式加载、`@path` 导入、`.claude/rules/` 路径限定、auto memory、AGENTS.md 互通、967K 压缩触发点。
- **[Subagents](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Subagents.md)**——subagent 的独立上下文与定义方式、内置 Explore/Plan/general-purpose、agent teams 的 mailbox 架构与 agent 间消息的信任边界。
- **[Extensions](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Extensions.md)**——Skills（Agent Skills 标准 + 动态上下文注入）、Plugins（marketplace、mod、三档 scope）、MCP（工具延迟加载）、Output styles（四种内置风格）。
- **[Headless](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Headless.md)**——`claude -p` 非交互运行、`--bare` 确定性模式、SIGTERM/SIGINT 退出语义、GitHub Actions 的双模式与准入检查。

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
- [Memory](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Memory.md)
- [Subagents](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Subagents.md)
- [Extensions](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Extensions.md)

## References

- [Claude Code documentation](https://code.claude.com/docs/en/overview)
- [Quickstart](https://code.claude.com/docs/en/quickstart)
- [CLI reference](https://code.claude.com/docs/en/cli-reference)
