## Introduction

OpenCode 通过 **MCP**（Model Context Protocol）接入外部工具与服务——数据库、API 集成、第三方服务都可经 MCP server 引入。本文覆盖 `local` 与 `remote` 两种接入方式、OAuth 自动流程，以及工具名前缀与 per-agent 授权。

## Configuration

`local` 必须给 `command` 数组，`remote` 必须给 `url`；`{env:VAR}` 做环境变量插值：

```json
{
  "mcp": {
    "context7": {
      "type": "remote",
      "url": "https://mcp.context7.com/mcp",
      "headers": { "Authorization": "Bearer {env:CONTEXT7_API_KEY}" },
      "enabled": true,
      "timeout": 10000
    },
    "playwright": {
      "type": "local",
      "command": ["npx", "-y", "@playwright/mcp"],
      "cwd": ".",
      "environment": { "NODE_ENV": "development" }
    }
  }
}
```

## OAuth & Auth

远程服务返回未认证时，OpenCode 会自动发起 OAuth（支持动态注册），也可预先给 `clientId` / `clientSecret` / `scope`，或 `"oauth": false` 关掉自动流程。凭据在 `~/.local/share/opencode/mcp-auth.json`。

## Commands

```shell
opencode mcp add [name]        # 添加
opencode mcp list              # 查看状态
opencode mcp auth [name]       # OAuth 认证
opencode mcp logout <name>
opencode mcp debug <name>      # 排查 OAuth 连接
```

## Tool Prefix & Per-Agent Control

工具名默认以 `server_` 前缀出现（如 `context7_*`），可按模式屏蔽（如 `"my-mcp*": false`）后再单独授权给某个 Agent。权限键对所有工具统一生效——`mymcp_*` 可一次性 deny 整个 server，`mymcp_search` 则精确 target 单个工具。

## Links

- [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)
- [Tools](/docs/CS/AI/LLM/Agent/Product/OpenCode/Tools.md)
- [Agent](/docs/CS/AI/LLM/Agent/Product/OpenCode/Agent.md)
- [MCP (Protocol)](/docs/CS/AI/LLM/Protocol/MCP.md)

## References

- [OpenCode MCP Servers 文档](https://opencode.ai/docs/mcp-servers)
- [Model Context Protocol](https://modelcontextprotocol.io)
