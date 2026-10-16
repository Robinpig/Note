## Introduction

插件是 OpenCode 的事件钩子机制——相当于 Claude Code 的 Hooks，但用 JS/TS 模块表达。插件导出函数，函数收到 `{ project, directory, worktree, client, $ }` 并返回一组事件处理器。本文覆盖加载位置、事件清单与一个拦截示例。

## Loading

加载位置：项目 `.opencode/plugins/`、全局 `~/.config/opencode/plugins/`、或 `opencode.json` 里 `"plugin": ["opencode-helicone-session"]` 直接引 npm 包（`opencode plugin <module>` 会自动装依赖并改配置）。`--pure` 可临时禁用所有外部插件排查问题。

## Events

常用事件：

- `command.executed`
- `message.updated` / `message.part.updated`
- `permission.asked` / `permission.replied`
- `session.created` / `session.idle` / `session.error` / `session.diff` / `session.status` / `session.compacted`
- `file.edited`
- `lsp.client.diagnostics`
- `shell.env`
- `todo.updated`
- `tool.execute.before` / `tool.execute.after`
- `tui.prompt.append` / `tui.command.execute` / `tui.toast.show`
- 兜底通用 `event` 处理器

> 注意：`tool.execute.before` / `after` 钩子里判断工具时，`apply_patch` 的 `input.tool` 是 `"apply_patch"`（不是 `"patch"`），其 patch 文本在 `output.args.patchText`。

## Example

```ts
import type { Plugin } from "@opencode-ai/plugin"

export const Guard: Plugin = async ({ client }) => ({
  // 拦截：禁止读取 .env
  "tool.execute.before": async (input, output) => {
    if (input.tool === "read" && output.args.filePath.includes(".env")) {
      throw new Error("Blocked")
    }
  },

  // 注入 shell 环境变量
  "shell.env": async (_input, output) => {
    output.env.MY_VAR = "value"
  },

  // 会话空闲时打点
  event: async ({ event }) => {
    if (event.type === "session.idle") {
      await client.app.log({ body: { service: "guard", level: "info", message: "idle" } })
    }
  },
})
```

## Links

- [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)
- [Tools](/docs/CS/AI/LLM/Agent/Product/OpenCode/Tools.md)
- [Agent](/docs/CS/AI/LLM/Agent/Product/OpenCode/Agent.md)
- [Claude Code Hooks](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Hooks.md)

## References

- [OpenCode Plugins 文档](https://opencode.ai/docs/plugins)
