## Introduction

Claude Code 是 Anthropic 官方推出的命令行工具，让你可以在终端中直接与 Claude 进行交互，完成代码编写、调试、重构等任务



## Installation

[Claude Code 一键安装](https://claude-zh.cn/guide/getting-started)



Mac
```shell
brew install --cask claude-code
```







## 命令

1 /plan - 先规划再执行

这是最重要的命令。不要上来就让 Claude 写代码，先让它分析需求、出方案。

\# 进入规划模式 /plan # Claude 会先分析，给出实施步骤 # 你确认后再执行

**为什么要这样做？**避免方向错误，减少返工。复杂任务必须用！

2 /compact - 压缩上下文

对话太长时，Claude 会变慢。用这个命令压缩历史记录，保留关键信息。

/compact

**使用时机：**对话超过 50 轮，或者 Claude 响应变慢时。

 /hooks - 自动化工作流

设置钩子，在特定时机自动执行命令。比如每次编辑完自动格式化代码。

\# 打开钩子配置界面 /hooks # 常用钩子： # - PostToolUse: 编辑文件后自动 prettier # - PreToolUse: git push 前自动检查 # - Stop: 会话结束前清理临时文件





### 常用 Hooks 配方

**自动格式化：**编辑 .ts/.tsx 文件后自动运行 prettier

**类型检查：**编辑后自动运行 tsc 检查类型错误

**Git 拦截：**push 前弹出确认框，让你再检查一遍

**桌面通知：**Claude 等待输入时发送通知
















## Links

- [AI](/docs/CS/AI/AI.md)