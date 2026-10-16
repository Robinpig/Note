## Introduction

OpenCode 的 Agent 体系是它和「Tab 补全自动接受一切」类工具的分野之一：**两个主 Agent（Build / Plan）默认共存，Tab 键在它们之间循环**，子 Agent 由主 Agent 自动调度或经 `@` 显式唤起。本文覆盖内置 Agent、自定义 Agent 的两种声明方式，以及驱动整个体系的**权限模型**。

## Built-in Agents

OpenCode 自带两个主 Agent 和三个子 Agent，外加三个隐藏系统 Agent：

| Agent | 模式 | 能力 | 用途 |
| :--- | :--- | :--- | :--- |
| `Build` | primary | 全工具 | 默认开发 Agent，文件操作 + 系统命令全开 |
| `Plan` | primary | 编辑/执行默认 ask | 只读分析与方案制定，动手前先出计划 |
| `General` | subagent | 全工具 | 多步执行、并行推进若干工作单位 |
| `Explore` | subagent | 只读 | 快速按模式找文件、按关键词搜代码 |
| `Scout` | subagent | 只读 | 克隆依赖仓库到托管缓存、对照上游源码 |
| `compaction` / `title` / `summary` | primary（隐藏） | — | 上下文压缩、生成标题、生成摘要，自动运行不可选 |

`Plan` 把文件编辑与 bash 默认设为 `ask`，因此适合「先规划再执行」，能显著减少方向性返工；`Explore` / `Scout` 不能改文件。`session_child_first` / `session_child_cycle` / `session_parent` 三个默认快捷键负责在父会话与子 Agent 的子会话之间进出。

## Custom Agents

### Markdown 声明

全局放 `~/.config/opencode/agents/`，项目放 `.opencode/agents/`，**文件名（去掉 `.md`）即 Agent 名**（`review.md` → `/review` 与 `@review`）。`opencode agent create` 可交互式生成，也可直接写文件：

```markdown
---
description: 只读地审查改动，不写文件
mode: subagent            # primary | subagent | all
model: anthropic/claude-sonnet-4
temperature: 0.2
steps: 12                 # 最大迭代轮数（旧字段 maxSteps 已废弃）
permission:
  edit: deny
  bash:
    "git diff *": allow
    "*": ask
  task: deny
---

你是一个严格的评审者，先列问题再给结论，不要直接改代码。
```

### JSON 声明

也可以在 `opencode.json` 的 `agent` 键里用 JSON 声明，二者字段一致。未写 `model` 时，主 Agent 用全局模型，子 Agent 继承调用者的模型。

### 配置选项

| 字段 | 说明 |
| :--- | :--- |
| `mode` | `primary` / `subagent` / `all`（默认 `all`） |
| `model` / `temperature` | 模型与随机度（多数模型默认 0，Qwen 系默认 0.55） |
| `steps` | 最大 agentic 迭代轮数，到达后被告知做总结（替代废弃的 `maxSteps`） |
| `prompt` | 系统提示词文件路径，用 `{file:./prompts/x.txt}` 语法引用 |
| `permission` | 覆盖全局权限（见下文矩阵） |
| `hidden` | 从 `@` 自动补全菜单隐藏（仅对 `mode: subagent` 有效，仍可被 Task 工具调用） |
| `color` | UI 配色（`#FF5733` 或主题色 `primary`/`accent` 等） |
| `top_p` | 控制输出多样性，temperature 的替代项 |
| 其他键 | 透传给 provider 作为模型参数（如 OpenAI 推理模型的 `reasoningEffort`） |

`tool` 配置项已被废弃：新配置一律用 `permission` 表达（`true` 等价于 `{"*":"allow"}`，`false` 等价于 `{"*":"deny"}`）。

## Permissions

OpenCode 用 `permission` 配置决定每个动作是自动运行、询问还是阻断。每条规则解析为三态之一：`allow` / `ask` / `deny`。

### 权限键

权限按**工具名**匹配（同一套语法对内置工具、自定义工具、MCP 工具都生效）：

| 键 | 门控的工具 / 行为 |
| :--- | :--- |
| `read` | 读文件（匹配文件路径） |
| `edit` | 所有文件修改（`edit` / `write` / `apply_patch`） |
| `glob` | 文件 glob（匹配 glob 模式） |
| `grep` | 内容搜索（匹配正则模式） |
| `bash` | 运行 shell 命令（匹配解析后的命令，如 `git status --porcelain`） |
| `task` | 启动子 Agent（匹配子 Agent 类型） |
| `skill` | 加载技能（匹配技能名） |
| `lsp` | 运行 LSP 查询（目前不细分） |
| `question` | 执行中向用户提问 |
| `webfetch` | 抓取 URL（匹配 URL） |
| `websearch` | 网页搜索 |
| `external_directory` | 工具触及工作目录之外的路径时触发 |
| `doom_loop` | 同一工具调用以相同输入重复 3 次时触发 |

### 粒度语法

大多数键接受简写的动作字符串，或「glob/模式 → 动作」的对象做细粒度控制：

```json
{
  "$schema": "https://opencode.ai/config.json",
  "permission": {
    "bash": { "*": "ask", "git *": "allow", "rm *": "deny", "grep *": "allow" },
    "edit": { "*": "deny", "packages/web/src/content/docs/*.mdx": "allow" }
  }
}
```

规则按模式匹配求值，**最后匹配的规则生效**（catch-all `*` 放前、具体规则放后是常见写法）。模式支持 `*`（零或多字符）与 `?`（单个字符），`~` / `$HOME` 可放在模式开头引用主目录。

### 默认与守卫

不配置时 OpenCode 从宽松默认起步：多数权限默认 `allow`，但 `doom_loop` 与 `external_directory` 默认 `ask`，且 `.env` 文件默认 `deny`（防止密钥泄露）。`--auto` 启动可自动批准未被显式 `deny` 的权限请求（显式 `deny` 仍强制阻断），`opencode run --auto` 同样适用。询问时 UI 给出三种结果：`once` / `always`（当前会话内对建议模式免问）/ `reject`。

### 每 Agent 覆盖

Agent 权限与全局配置合并，Agent 规则优先。例如给 `build` 收紧 git push：

```json
{
  "permission": { "bash": { "*": "ask", "git *": "allow" } },
  "agent": { "build": { "permission": { "bash": { "git push *": "deny" } } } }
}
```

`permission.task` 还能用 glob 控制某个 Agent 可调用的子 Agent（设为 `deny` 时该子 Agent 从 Task 工具描述中彻底移除，模型不会尝试调用）。

## Version Note

权限模型的 `tools` 布尔配置自 **v1.1.1** 起废弃并合并进 `permission`；`maxSteps` 字段废弃、改用 `steps`；`external_directory` 与 `doom_loop` 是较新的安全守卫。本文以 1.19.x 稳定线为准。

## Links

- [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)
- [Architecture](/docs/CS/AI/LLM/Agent/Product/OpenCode/Architecture.md)
- [Tools](/docs/CS/AI/LLM/Agent/Product/OpenCode/Tools.md)
- [Agent (Theory)](/docs/CS/AI/LLM/Agent/Theory/Agent.md)
- [Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md)

## References

- [OpenCode Agents 文档](https://opencode.ai/docs/agents)
- [OpenCode Permissions 文档](https://opencode.ai/docs/permissions)
- [OpenCode Tools 文档](https://opencode.ai/docs/tools)
