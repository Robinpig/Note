## Introduction

OpenCode CLI 默认不带参数即启动 TUI，但也能以命令形式驱动，用于脚本、管道与 CI。本文覆盖非交互命令（`run` / `serve` / `github` / `export` / `session` 等）。架构层与客户端/服务器形态见 [Architecture](/docs/CS/AI/LLM/Agent/Product/OpenCode/Architecture.md)。

## Run (Headless)

```shell
opencode run "解释这个报错"        # 非交互执行，适合脚本与管道
opencode run -m anthropic/claude-sonnet-4 --agent plan "先给方案"
opencode --continue               # 继续上一次会话
opencode --session <id> --fork    # 分叉会话
```

`opencode run` 是接入 Agent Client Protocol、CI、一次性提问的主要入口。

## Server & Web

```shell
opencode serve --port 4096 --hostname 127.0.0.1   # 无头 HTTP 服务
opencode web                                       # 启动服务并打开浏览器
opencode attach <url>                              # 让本地 TUI 连接到已存在的 server
opencode acp                                       # 启动 ACP 兼容子进程，供 IDE 接入
```

`serve` / `attach` / `web` / `acp` 都是围绕同一个 server 的不同外壳；`attach` 用于远程后端，把 TUI 接到别人（或容器里）已起的 server。

## Session Management

```shell
opencode session list              # 列出会话
opencode export [sessionID] > s.json && opencode import s.json   # 导出/导入（分享 URL 导入已停用）
```

> session sharing 自 **v1.19.1** 起停用，`opencode export` 仍可导出为本地 JSON 用于备份/迁移，但从分享 URL 导入不再支持。

## GitHub & CI

```shell
opencode github install            # 在仓库里安装 GitHub Agent（CI 中协作）
opencode github run
opencode pr 123                    # checkout PR 分支后进入 TUI
```

## Utility

```shell
opencode providers          # 别名 opencode auth，管理提供商与凭据
opencode providers list     # 查看已保存的凭据
opencode models [provider]  # 列出可用模型
opencode stats              # token 用量与费用统计
opencode db | debug | completion   # 数据库维护 / 排障 / shell 补全
opencode upgrade [target]          # 升级（autoupdate: false | "notify"）
opencode uninstall                 # 卸载并清理
```

## Global Flags

`tui` / `run` 等通用参数：`--print-logs`、`--log-level DEBUG|INFO|WARN|ERROR`、`--pure`、`--prompt`、`--agent`、`--mdns`、`--mdns-domain`、`--cors`。

## Links

- [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)
- [Architecture](/docs/CS/AI/LLM/Agent/Product/OpenCode/Architecture.md)
- [Commands](/docs/CS/AI/LLM/Agent/Product/OpenCode/Commands.md)
- [Claude Code Headless](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Headless.md)

## References

- [OpenCode CLI 文档](https://opencode.ai/docs/cli)
- [OpenCode GitHub 文档](https://opencode.ai/docs/github)
- [OpenCode Server 文档](https://opencode.ai/docs/server)
