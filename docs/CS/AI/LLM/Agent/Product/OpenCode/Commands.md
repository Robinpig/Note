## Introduction

OpenCode 的斜杠命令分两类：内置命令与自定义命令。内置命令是 TUI 内常用的会话/模型/视图操作；自定义命令是一段可参数化的提示词模板，用来把重复任务固化下来。本文列出常用内置命令、自定义命令的写法，并标注一个近期变化：**session sharing 自 v1.19.1 起停用**，相关的 `/share` / `/unshare` 已不再可用。

## Built-in Commands

TUI 内置斜杠命令（默认 leader 键为 `ctrl+x`）：

| 命令 | 作用 | 快捷键 |
| :--- | :--- | :--- |
| `/connect` | 添加提供商与凭据 | — |
| `/init` | 扫描项目并生成 `AGENTS.md` | — |
| `/models` | 选择模型 | `ctrl+x m` |
| `/new` (`/clear`) | 新会话 | `ctrl+x n` |
| `/sessions` (`/resume`, `/continue`) | 列出并切换会话 | `ctrl+x l` |
| `/compact` (`/summarize`) | 压缩上下文 | `ctrl+x c` |
| `/undo` / `/redo` | 撤销/重做上一条消息及文件改动（依赖 Git） | `ctrl+x u` / `ctrl+x r` |
| `/export` | 导出会话为 Markdown | `ctrl+x x` |
| `/editor` | 用外部编辑器撰写长提示 | `ctrl+x e` |
| `/details` | 切换工具执行细节显示 | — |
| `/thinking` | 切换思考过程可见性 | — |
| `/themes` | 切换主题 | `ctrl+x t` |
| `/help` | 帮助 | — |
| `/exit` (`/quit`, `/q`) | 退出 | `ctrl+x q` |

> 注意：早期版本有 `/share` / `/unshare` 用于分享或取消分享会话，但自 **v1.19.1** 起 session sharing 已停用——现有分享链接与分享命令都不再可用，从分享 URL 导入会话也不再支持。

## Custom Commands

全局 `~/.config/opencode/commands/`，项目 `.opencode/commands/`，**文件名（去掉 `.md`）即命令名**；也可以在 `opencode.json` 的 `command` 键里写。frontmatter 支持 `description`、`agent`、`model`，正文就是提示词模板。

```markdown
---
description: 带覆盖率地跑测试并分析失败原因
agent: build
model: anthropic/claude-sonnet-4
---

最近一次测试输出：!`npm test`

请阅读 @src 下相关实现，定位 $1 的失败原因，给出修复方案（先不写代码）。
剩余上下文：$ARGUMENTS
```

### Template Syntax

- `$ARGUMENTS`：命令后的全部文本
- `$1`、`$2`、`$3`：位置参数
- `!` 加反引号包裹的命令先执行 shell 并把输出注入（`!`npm test` `）
- `@路径`：注入文件内容

**自定义命令可以覆盖同名内置命令**——定义同名命令即可替换。

### Configuration Options

| 选项 | 说明 |
| :--- | :--- |
| `template` | 发送给 LLM 的提示词（必填） |
| `description` | TUI 中显示的命令描述 |
| `agent` | 指定执行命令的 Agent；若是 subagent，默认触发子 Agent 调用 |
| `subtask` | `true` 时强制触发子 Agent 调用（即使 Agent 配置为 `primary`，也不污染主上下文） |
| `model` | 覆盖该命令的默认模型 |

## Links

- [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)
- [Rules](/docs/CS/AI/LLM/Agent/Product/OpenCode/Rules.md)
- [Skills](/docs/CS/AI/LLM/Agent/Product/OpenCode/Skills.md)
- [CLI](/docs/CS/AI/LLM/Agent/Product/OpenCode/CLI.md)
- [Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md)

## References

- [OpenCode Commands 文档](https://opencode.ai/docs/commands)
- [OpenCode GitHub 文档](https://opencode.ai/docs/github)
