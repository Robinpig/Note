## Introduction

工具是 LLM 在 OpenCode 里能采取的行动。OpenCode 自带一组内置工具，同时支持用 TS/JS 定义**自定义工具**和接入 **MCP server**。本文列清内置工具、它们与权限键的对应关系，以及自定义工具的写法——后者是旧文档没有、但生产中很有用的扩展点。权限的整体模型见 [Agent](/docs/CS/AI/LLM/Agent/Product/OpenCode/Agent.md)。

## Built-in Tools

默认所有内置工具都启用、无需授权；用 `permission` 配置可改为 allow / ask / deny。

| 工具 | 受哪个权限键控制 | 说明 |
| :--- | :--- | :--- |
| `bash` | `bash` | 在项目环境执行 shell 命令 |
| `edit` | `edit` | 用精确字符串替换修改已有文件（主要改码方式） |
| `write` | `edit` | 创建新文件或覆盖已有文件 |
| `read` | `read` | 读文件内容，支持指定行范围 |
| `grep` | `grep` | 正则搜文件内容，支持文件模式过滤 |
| `glob` | `glob` | 按 glob 模式找文件（按修改时间排序） |
| `apply_patch` | `edit` | 应用 patch 文件（注意：插件钩子里 `input.tool` 是 `"apply_patch"`，不是 `"patch"`；patch 文本在 `output.args.patchText`，路径嵌在标记行里相对项目根） |
| `skill` | `skill` | 加载 `SKILL.md` 技能并返回内容 |
| `webfetch` | `webfetch` | 抓取并读取网页 |
| `websearch` | `websearch` | 经 Exa / Parallel 做网页发现（需 OpenCode 系 provider 或 `OPENCODE_ENABLE_EXA` / `OPENCODE_ENABLE_PARALLEL` 环境变量，无 API key） |
| `question` | `question` | 执行中向用户提问（带选项，用户可自定义回答） |
| `lsp` | `lsp` | 调 LSP server 取定义/引用/hover 等（实验性，需 `OPENCODE_EXPERIMENTAL_LSP_TOOL=true` 或 `OPENCODE_EXPERIMENTAL=true`） |

两个值得注意的迁移点（对照早期版本）：

- 旧的 `patch` 工具已更名为 **`apply_patch`**；旧的 `todo` / 独立 `task` 工具**不再作为内置工具列出**——`task` 现在是一个**权限键**（门控子 Agent 调用），而非可被 LLM 直接调用的工具。
- 新增了 **`websearch`**（独立于 `webfetch` 的发现能力）与 **`question`**（交互式澄清）。

## Internals

`grep` 与 `glob` 内部用 **ripgrep**，默认尊重 `.gitignore`（被忽略的文件/目录不进搜索与列举）。要在仓库里强制搜 `node_modules/`、`dist/` 等，可在项目根放一个 `.ignore` 文件显式放行：

```text
!node_modules/
!dist/
!build/
```

## Custom Tools

自定义工具是你可以创建的、LLM 能在会话里调用的函数——它们与内置工具（read / write / bash）并列工作。定义用 TypeScript 或 JavaScript（仅工具定义本身需 TS/JS，实际逻辑可以是任意语言的脚本）。

### Location

- 项目级：`.opencode/tools/`
- 全局：`~/.config/opencode/tools/`

### Structure

最省事的方式是用 `@opencode-ai/plugin` 的 `tool()` helper（自带类型安全与校验）：

```typescript
// .opencode/tools/database.ts
import { tool } from "@opencode-ai/plugin"

export default tool({
  description: "Query the project database",
  args: {
    query: tool.schema.string().describe("SQL query to execute"),
  },
  async execute(args) {
    // Your database logic here
    return `Executed query: ${args.query}`
  },
})
```

**文件名即工具名**（上例生成 `database` 工具）。同一文件可导出多个工具，每个导出变成 `<文件名>_<导出名>` 形式的工具（如 `math.ts` 导出 `add` / `multiply` → `math_add` / `math_multiply`）。

### Overriding Built-in Tools

自定义工具按工具名匹配；若与内置工具同名，**自定义工具优先**。例如下面的 `bash.ts` 会替换内置 `bash` 工具。除非有意替换，否则建议用唯一名字；只想禁用内置又不想覆盖时，走 `permission`。

### Arguments and Context

参数用 `tool.schema`（即 Zod）定义，也可直接 import `zod` 返回纯对象。工具执行时收到 `context`，包含 `agent`、`sessionID`、`messageID`、`directory`（会话工作目录）、`worktree`（git worktree 根）等会话信息。

### Arbitrary Language Logic

工具定义用 TS/JS，但真正干活的脚本可以是任意语言。下面用 `Bun.$` 调用 Python：

```typescript
// .opencode/tools/python-add.ts
import { tool } from "@opencode-ai/plugin"
import path from "path"

export default tool({
  description: "Add two numbers using Python",
  args: {
    a: tool.schema.number().describe("First number"),
    b: tool.schema.number().describe("Second number"),
  },
  async execute(args, context) {
    const script = path.join(context.worktree, ".opencode/tools/add.py")
    const result = await Bun.$`python3 ${script} ${args.a} ${args.b}`.text()
    return result.trim()
  },
})
```

## Links

- [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)
- [Agent](/docs/CS/AI/LLM/Agent/Product/OpenCode/Agent.md)
- [MCP](/docs/CS/AI/LLM/Agent/Product/OpenCode/MCP.md)
- [Plugin](/docs/CS/AI/LLM/Agent/Product/OpenCode/Plugin.md)
- [Permission (Theory)](/docs/CS/AI/LLM/Agent/Theory/Permission.md)

## References

- [OpenCode Tools 文档](https://opencode.ai/docs/tools)
- [OpenCode Custom Tools 文档](https://opencode.ai/docs/custom-tools)
- [OpenCode Permissions 文档](https://opencode.ai/docs/permissions)
