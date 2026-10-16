## Introduction

OpenCode 的 TUI 是默认客户端，但它的界面行为由一份**独立的 `tui.json` / `tui.jsonc`** 控制——与运行时配置（`opencode.json`）解耦：换终端不影响 Agent 行为，改 Agent 行为也不动 UI。本文覆盖输入约定、快捷键与 `tui.json` 的覆盖机制。

## Input Conventions

- `@` 模糊搜索并把文件内容加入上下文（配置过的引用如 `@alias/` 会出现在补全里）
- 行首 `!` 直接进入 shell，输出作为工具结果回到对话
- 拖拽图片到终端即可作为输入
- `ctrl+p` 打开命令面板调整视图设置（持久化）

## Configuration

界面行为由 `tui.json` / `tui.jsonc` 控制（schema `https://opencode.ai/tui.json`），与运行时配置解耦。配置路径可用 `OPENCODE_CONFIG` / `OPENCODE_CONFIG_DIR` 和 `OPENCODE_TUI_CONFIG` 覆盖，多层配置始终按**键合并**而非整体替换：

```json
{
  "$schema": "https://opencode.ai/tui.json",
  "theme": "opencode",
  "keybinds": { "command_list": "ctrl+p" },
  "leader_timeout": 2000,
  "scroll_speed": 3,
  "diff_style": "auto",        // auto | stacked
  "cursor": { "style": "block", "blinking": true },
  "mouse": true,
  "attention": {}              // 桌面通知与声音：提问、权限请求、报错、会话完成
}
```

## External Editor

`/editor` 与 `/export` 使用 `EDITOR` 环境变量，GUI 编辑器要加 `--wait`：`export EDITOR="code --wait"`。

## Links

- [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)
- [Commands](/docs/CS/AI/LLM/Agent/Product/OpenCode/Commands.md)
- [Architecture](/docs/CS/AI/LLM/Agent/Product/OpenCode/Architecture.md)
- [Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md)

## References

- [OpenCode TUI 文档](https://opencode.ai/docs/tui)
- [OpenCode Keybinds 文档](https://opencode.ai/docs/keybinds)
