## Introduction

OpenCode 与 Claude Code 这类「单进程 CLI + SDK」工具最根本的架构差异，在于它是一个**本地 HTTP 服务 + 多个无状态客户端**的系统：内核是一个常驻 server，TUI、Web、IDE 插件、SDK 都只是它的客户端。这套架构让 OpenCode 可以远程 attach、无头运行和二次开发——理解 [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md) 必须先理解它的 C/S 边界。

与之对照，Claude Code 是单进程、Codex 是单进程的 Rust 二进制；OpenCode 把「执行引擎」与「交互外壳」解耦，代价是多一层进程与序列化。本文把这一层拆开。

## Client/Server Model

当你运行 `opencode` 时，进程会同时启动一个 TUI 和一个 server；TUI 就是那个 server 的客户端。`opencode serve` 则只起一个独立 server（无 TUI），供其他客户端连接。

```shell
opencode                    # 本地：TUI + 同进程 server
opencode serve              # 无头 HTTP 服务，默认端口 4096
opencode attach <url>       # 让本地 TUI 连接到已存在的 server
opencode web                # 启动 server 并打开浏览器
```

server 暴露一份 **OpenAPI 3.1** 规范（在 `/doc` 端点），官方 SDK 即由该规范生成。从 [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md) 的理论视角看，OpenCode 把「[Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md) 的执行面」搬到了一个可被任意客户端驱动的 HTTP 接口后面。

## Layers

自上而下可以拆成五层：

#### 1. Client Layer

TUI（主客户端）、`opencode web`（浏览器界面）、IDE 插件、`opencode github`（CI 中的 Agent）、自定义脚本（SDK / HTTP）。它们都是同一后端的客户端，互不影响。

#### 2. Server Layer

常驻 HTTP 服务，暴露 OpenAPI 3.1 规范。可用 `--hostname`、`--port`、`--cors`、`--mdns` 控制监听与服务发现（mDNS），`opencode web` 与 `opencode serve` 共用同一套 basic-auth 环境变量防护。

#### 3. Session Layer

会话以 `session → message → part` 三级结构持久化在本地 SQLite（`opencode db` 提供维护命令）。因此支持 `opencode session list`、`--continue`、`--session`、`--fork`（分叉会话）以及 `opencode export` / `opencode import`。

#### 4. Agent & Tools Layer

- **主 Agent**：`Build`（默认，全能力）与 `Plan`（默认对编辑和 bash 询问，用于只读分析）
- **子 Agent**：`General`（多步执行）、`Explore`（只读检索代码库）、`Scout`（只读检索外部文档与依赖）；另有 `compaction`、`title`、`summary` 等隐藏的自动 Agent
- **工具**：`bash` / `edit` / `write` / `read` / `grep` / `glob` / `apply_patch` / `skill` / `webfetch` / `websearch` / `question`，配合 **LSP**（实验性）与 **formatter** 保证编辑后的代码质量
- **权限**：`allow` / `ask` / `deny` 三态；默认的「不询问直接执行」可被 `permission` 配置逐项收紧（详见 [Agent](/docs/CS/AI/LLM/Agent/Product/OpenCode/Agent.md)）

#### 5. Extension Surface

`AGENTS.md`（规则）、`skills/`（技能）、`commands/`（自定义命令）、`agents/`（自定义 Agent）、`tools/`（自定义工具）、`plugins/`（事件钩子）、`mcp`（外部工具）。除 plugin / custom tool 是 JS/TS 之外，其余全部是 Markdown + JSON，「文件即配置」。

## REST API

server 暴露的接口按域划分（节选）：

| 域 | 代表端点 | 说明 |
| :--- | :--- | :--- |
| Global | `GET /global/health`、`GET /global/event`（SSE） | 健康检查 + 全局事件流 |
| Session | `GET/POST /session`、`POST /session/:id/fork`、`POST /session/:id/message` | 会话的增删改查与消息收发 |
| Message | `POST /session/:id/message`、`POST /session/:id/prompt_async` | 同步 / 异步发送消息 |
| TUI | `POST /tui/append-prompt`、`POST /tui/submit-prompt` | 经 server 驱动 TUI（IDE 插件据此嵌入） |
| MCP | `GET /mcp`、`POST /mcp` | 查询与动态添加 MCP server |

完整清单见 `/doc`（Swagger 视图）。`/tui` 端点特别重要：它让 IDE 插件把 OpenCode 的 TUI 作为一个可驱动的子进程嵌入编辑器。

## ACP (Agent Client Protocol)

OpenCode 支持 **ACP**（Agent Client Protocol）——一个标准化的、编辑器与 AI 编码 Agent 之间的通信协议。运行 `opencode acp` 时，OpenCode 作为 ACP 兼容的子进程启动，与编辑器通过 **JSON-RPC over stdio** 通信：

- **Zed**：从 ACP Registry 安装，或在 `~/.config/zed/settings.json` 的 `agent_servers` 注册 `opencode` + `args: ["acp"]`
- **JetBrains IDEs**：在 `acp.json` 中指向 OpenCode 可执行文件
- **Neovim**：`Avante.nvim`（`acp_providers`）与 `CodeCompanion.nvim`（`agent_servers`）

经 ACP 使用时，OpenCode 的终端行为完全一致，所有特性都受支持——ACP 只是把「TUI 外壳」换成「编辑器外壳」，内核不变。

## Config & Precedence

配置用 JSON 或 JSONC（带注释），写在 `opencode.json` / `opencode.jsonc`。**配置文件是合并而非替换**：多个来源的配置按优先级叠加，后写来源只为冲突键覆盖，非冲突设置全部保留。

优先级（后者覆盖前者）：

1. 远程配置（`.well-known/opencode`）——组织默认值
2. 全局配置（`~/.config/opencode/opencode.json`）——用户偏好
3. 自定义配置（`OPENCODE_CONFIG` 环境变量）
4. 项目配置（`.opencode/opencode.json`）——项目级

```json
{
  "$schema": "https://opencode.ai/config.json",
  "model": "anthropic/claude-sonnet-4-5",
  "autoupdate": true,
  "server": { "port": 4096 }
}
```

## Network & Security

server 的监听面由若干开关控制：

- `--hostname` 默认 `127.0.0.1`（仅本机）；要让远程客户端连接需显式绑定 `0.0.0.0`
- `--cors` 可多次传入，放行额外的浏览器源（如 `http://localhost:5173`）
- `--mdns` 启用 mDNS 服务发现（默认域名 `opencode.local`）
- 设置 `OPENCODE_SERVER_PASSWORD` 后，server 用 HTTP basic-auth 保护（用户名默认 `opencode`，可用 `OPENCODE_SERVER_USERNAME` 覆盖）；该保护同时覆盖 `opencode serve` 与 `opencode web`

## Version Note

笔记基线为 npm `@opencode-ai/opencode` 的 **1.19.x 稳定线**（文档站最后更新 2026-10-15）。OpenCode **2.0** 是一条独立的主版本线：自 v1.19.0 起可通过 `opencode upgrade --major` 或 `/update` 里的 2.0 offer 升级，且 1.x 安装永远不会被作为常规更新推到 2.x——二者是显式分离的两条轨道。本文内容同时适用于 1.x 与 2.x 的架构层；涉及命令与扩展的差异会在对应分册注明。

## Links

- [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)
- [Agent](/docs/CS/AI/LLM/Agent/Product/OpenCode/Agent.md)
- [Tools](/docs/CS/AI/LLM/Agent/Product/OpenCode/Tools.md)
- [Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md)
- [Harness](/docs/CS/AI/LLM/Agent/Theory/Harness.md)

## References

- [OpenCode Server 文档](https://opencode.ai/docs/server)
- [OpenCode ACP 文档](https://opencode.ai/docs/acp)
- [OpenCode Config 文档](https://opencode.ai/docs/config)
- [OpenCode Network 文档](https://opencode.ai/docs/network)
- [anomalyco/opencode](https://github.com/anomalyco/opencode)
