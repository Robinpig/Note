## Introduction

Pi 把能力藏在**基础操作**里：`@` 引用文件、`!` 跑命令、Enter/Alt+Enter 两种发送语义、一整套可自定义的快捷键。本页覆盖这些日常交互的完整机制——输入、Shell 集成、快捷键体系、模型与思考级别、消息队列与 TUI 形态。

会话树操作（`/tree` / `/fork` / `/clone`）在 [Session](/docs/CS/AI/LLM/Agent/Product/Pi/Session.md)；上下文文件在 [Context](/docs/CS/AI/LLM/Agent/Product/Pi/Context.md)。

## Enter a Prompt

- `Enter` 提交；`Shift+Enter`（或 `ctrl+j`）换行；`ctrl+g` 把当前编辑内容丢进外部编辑器（`externalEditor` 设置 → `$VISUAL` → `$EDITOR` → Windows 记事本 / 其他 `nano`）写长提示。
- `@` 触发文件模糊搜索，`Tab` 补全路径；一条消息可引用多个文件，启动参数也支持 `pi @README.md "总结一下"` 与管道 stdin（内容会前置到第一条提示）。
- 粘贴或拖拽图片进兼容终端即入上下文（macOS `ctrl+v`，Windows/WSL `alt+v`）。

## Steer, Follow Up, Abort

Pi 工作时还能继续输入，两种发送语义对应两种排队时机：

| 操作 | 时机 |
| :--- | :--- |
| `Enter`（steering） | 等当前响应及其工具调用跑完后，引导下一轮生成 |
| `Alt+Enter`（follow-up） | 等 Pi 把当前**任务**全部做完才投入 |
| `Alt+Up` | 把排队中的消息取回编辑器 |
| `Escape` | 中止当前运行，排队消息同时归还 |

「忙」的判定从 run 启动就开始（含压缩检查与 `before_agent_start`），这期间发出的消息会进入即将开始的 run，而不是被当成下一轮。

## Shell Integration

行首加 `!` 执行命令并**把输出送进对话**，`!!` 则静默执行（不发给模型）。

但每条命令都是**独立的非交互 shell 进程**（`bash -c`）——旧版社区文章里「导出的环境变量、切换的目录会保留」的说法已不成立：`!cd backend` 之后的下一条命令并不会停在 `backend`。要跨命令复现状态，用设置项在**每条命令前**垫 setup：

| 设置 | 作用 |
| :--- | :--- |
| `shellPath` | 指定 Bash 可执行文件 |
| `shellCommandPrefix` | 每条命令前执行的前缀（与命令以换行拼接） |

Bash 解析顺序：`/bin/bash` → `PATH` 上的 `bash` → 都没有才退到 `sh`；原生 Windows 先看配置路径，再 Git Bash，最后 `PATH` 上的 `bash.exe`。让 alias 可用（非交互 shell 默认不展开）的标准写法：

```json
{
  "shellCommandPrefix": "shopt -s expand_aliases\nsource ~/.bash_aliases"
}
```

前缀每条命令都会重跑，别放交互式命令；模型侧另有可选的 `powershell` 工具（PowerShell 7 或 Windows PowerShell）。

## Keybindings

快捷键背后是一套**命名动作**（如 `app.session.new`、`tui.editor.cursorUp`），默认绑定只是初始值——在 `<agent-dir>/keybindings.json` 里可改绑、可绑多个键、可用空数组禁用：

```json
{
  "$schema": "https://pi.dev/schemas/keybindings.schema.json",
  "app.session.tree": ["ctrl+shift+t", "alt+shift+t"],
  "tui.altScreen.pageUp": []
}
```

改完 `/reload` 生效；`/hotkeys` 随时查看当前会话实际激活的快捷键。常用默认键：

| 键 | 动作 |
| :--- | :--- |
| `ctrl+l` | 模型选择器 |
| `ctrl+p` / `shift+ctrl+p` | 正/反向循环模型 |
| `shift+tab` | 循环思考级别 |
| `ctrl+o` | 展开/折叠工具输出 |
| `ctrl+t` | 显示/隐藏 thinking 块 |
| `ctrl+x` | 复制（`/tree` 内为选中消息；否则最后一条 assistant 消息） |
| `ctrl+g` | 外部编辑器 |
| `alt+enter` / `alt+up` | 排队 follow-up / 取回 |
| `escape` | 中止 |
| `ctrl+c` | 第一次清空编辑器，第二次退出 |
| `ctrl+z` | 挂到后台（Windows 无默认，终端不支持 Unix 作业控制） |

编辑器内还有一套 emacs 风格移动（`ctrl+a`/`ctrl+e`/`ctrl+w`/`ctrl+u`/`ctrl+k`/`ctrl+y`…）；全屏模式下 `pageUp`/`pageDown`/`ctrl+shift+up/down`（跳到上/下一条标记消息）与 `ctrl+shift+f`（转录搜索）优先于编辑器动作。Windows Terminal 占用部分 Alt 组合，替代键见官方 Terminal Setup（如 `alt+v`→`ctrl+q` 之类映射以文档为准）。

## Models and Thinking

`/model`（或 `ctrl+l`）打开选择器，只列出**凭证可用**的模型；在选择器里 `ctrl+s` 把当前模型存为启动默认。命令行侧：

```sh
pi --model sonnet:high              # provider/id 可选，:thinking 后缀可选
pi --provider openai --model gpt-6  # 限定 provider（需配合 --model）
pi --models "*-sonnet*,o3-mini"     # 启动作用域：glob/精确/模糊混排
pi --list-models claude             # 列出可用模型后退出
```

思考级别共七档：`off` / `minimal` / `low` / `medium` / `high` / `xhigh` / `max`，`--thinking` 会覆盖 `--model` 后缀并被模型能力钳制。凭证解析顺序：运行时 `--api-key` > `auth.json` 已存凭证 > `models.json` 的 `apiKey` > provider 环境变量或云厂商 ambient 凭证。

模型目录随包发布，可叠加 pi.dev 的新目录数据，缓存离线可用，`pi update --models` 强制刷新。除聊天模型，目录里还有**分类模型**（TypeSafe Jev、Cloudflare Clef/Clef Flash、OpenAI GPT-6 Luna 走 Decisions API——不对话，只对 JSON 状态做选择/是非/打分）与**图像模型**（OpenRouter 系列，`models.generateImages()`）。

## TUI Shape

默认全屏模式（fullscreen）：编辑器与状态区固定，转录在窗口内滚动；`--tui-mode regular` 或 `/settings` 可切换回终端原生滚动。启动头部列出本次加载的指令与资源；底部状态栏随上下文占用与累计用量/成本实时更新。

## Links

- [Pi 枢纽](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md)
- [Session：会话树](/docs/CS/AI/LLM/Agent/Product/Pi/Session.md)
- [Context：上下文与压缩](/docs/CS/AI/LLM/Agent/Product/Pi/Context.md)
- [Extensions：扩展体系](/docs/CS/AI/LLM/Agent/Product/Pi/Extensions.md) — 快捷键、slash 命令、CLI flag 都能由扩展注册

## References

- [Pi Usage](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/usage.md)
- [Pi Keybindings](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/keybindings.md)
- [Pi Shell Aliases](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/shell-aliases.md)
- [Pi Models](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/models.md)
