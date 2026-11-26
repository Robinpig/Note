> 版本基线：v1.19.5（`E:/Projects/opencode-1.19.5` release 源码快照）。本文聚焦 `packages/opencode/src/mcp/`：MCP server 的配置、连接建立、工具转换与 OAuth。MCP 工具进入 opencode 后与内置工具共享同一条执行链（hook + 权限），见 [Tools](/docs/CS/AI/LLM/Agent/Product/OpenCode/Tools.md)。

## Introduction

OpenCode 通过 **MCP**（Model Context Protocol）接入外部工具与服务——数据库、API 集成、第三方服务都可经 MCP server 引入。工具名做消毒并加 server 前缀（`server_tool`），按 agent 权限控制可见性，执行时同样过 `tool.execute.before` 钩子与 `ctx.ask()` 权限门。

几个反直觉点：

- **remote MCP 没有 sse/http 配置子类型**：配置只有 `type: "remote" + url`；传输方式靠运行时先试 `StreamableHTTP`、失败再降级 `SSE`，配置层无法强制指定。
- **code-mode 不是另一条 MCP 接入路径**，而是同一批 MCP 工具的"脚本化编排"消费方式：开启后不再逐个注册工具，改由 `execute` 元工具把工具树暴露给脚本。
- **按 agent 控制可见性是两处配合**：规则集决定工具是否进入 LLM 的 tool 列表（目录可见性），执行时再逐次 `ctx.ask` 交互审批——与权限是"两道门"，见 [Plugin](/docs/CS/AI/LLM/Agent/Product/OpenCode/Plugin.md)。

## Configuration and Connection

配置 schema（`core/src/v1/config/mcp.ts`）只有 local / remote 两个判别值：

```typescript
export const Local = Schema.Struct({
  type: Schema.Literal("local"),
  command: Schema.mutable(Schema.Array(Schema.String)),
  cwd: Schema.optional(Schema.String),
  environment: Schema.optional(Schema.Record(Schema.String, Schema.String)),
  enabled: Schema.optional(Schema.Boolean),
  timeout: Schema.optional(PositiveInt),
})
// Remote: { type:"remote", url, enabled?, headers?, oauth?: OAuth|false, timeout? }
export const Info = Schema.Union([Local, Remote]).annotate({ discriminator: "type" })
```

连接建立（`mcp/index.ts`）：local 用 `StdioClientTransport`（`command[0]` 为可执行文件、cwd 相对工作区解析、`env = {...process.env, ...mcp.environment}`，`cmd === "opencode"` 时加 `BUN_BE_BUN=1`）；remote 用 `StreamableHTTPClientTransport` 与 `SSEClientTransport`，**先 HTTP 再 SSE 逐个尝试**，带 30s 默认超时，认证错误中断尝试并记录 `needs_auth`/`needs_client_registration` 状态。client 声明 `roots` capability，返回本目录的 `file://` URI。状态枚举：`connected`/`disabled`/`failed`/`needs_auth`/`needs_client_registration`。

## Tool Conversion and Visibility

`mcp/catalog.ts` 把 MCP 工具包成 Vercel AI SDK 的 `dynamicTool`，`execute` 内部 `client.callTool`：

```typescript
export function convertTool(mcpTool: MCPToolDef, client: Client, timeout?: number): Tool {
  const inputSchema: JSONSchema7 = {
    ...(mcpTool.inputSchema as JSONSchema7), type: "object",
    properties: (mcpTool.inputSchema.properties ?? {}) as JSONSchema7["properties"],
    additionalProperties: false,
  }
  return dynamicTool({
    description: mcpTool.description ?? "",
    inputSchema: jsonSchema(inputSchema),
    execute: async (args: unknown, options) => {
      const result = await client.callTool(
        { name: mcpTool.name, arguments: (args || {}) as Record<string, unknown> },
        CallToolResultSchema,
        { resetTimeoutOnProgress: true, signal: options.abortSignal, timeout, onprogress: () => {} },
      )
      // ... isError → throw, content → attachments
    },
  })
}
```

工具名 `toolName(clientName, name) = sanitize(clientName) + "_" + sanitize(name)`。真正挂进 session 的工具在 `session/tools.ts`：对每个 MCP tool 包一层 `plugin.trigger("tool.execute.before")` → `ctx.ask(permission)` → 原 execute → `plugin.trigger("tool.execute.after")`，并把 MCP 的 image/resource content 转成 attachments。

可见性两处配合：`permission/index.ts` 的 `disabled()`/`visibleTools()` 用规则集过滤（详见 [Agent](/docs/CS/AI/LLM/Agent/Product/OpenCode/Agent.md)），`tool/code-mode.ts` 与 `describeCodeMode` 用 `Permission.visibleTools(yield* mcp.tools(), ruleset)`（ruleset = merge(agent.permission, session.permission)），发请求前还有 `resolveTools` 再过滤一次。

## OAuth

remote 且 `oauth !== false` 时，`startAuth` 确定 redirectUri（显式 > callbackPort > 默认 `http://127.0.0.1:19876/mcp/oauth/callback`）、起本地回调服务、生成 32 字节 `oauthState`、用 `McpOAuthPendingProvider` + `StreamableHTTPClientTransport` 触发 `UnauthorizedError` 拿 authorizationUrl。`authenticate` 注册 `waitForCallback(oauthState)`、把回调 URL 交给 `onAuthorization` 并尝试 `browser.open`，拿 code 后校验 state 防 CSRF。`finishAuth` 调 `pending.transport.finishAuth(code)` → `provider.commit()` 落盘 token → `createAndStore` 重连。

OAuth provider（`mcp/oauth-provider.ts`）声明 `clientMetadata`：`authorization_code` + `refresh_token`、`client_secret_post`/`none`。`McpOAuthPendingProvider` 把 clientInfo/tokens 暂存内存，成功后 `commit()` 一次性写入 `McpAuth`（落盘 `~/.local/share/opencode/mcp-auth.json`）。本地回调服务强制校验 state 参数（缺失/不匹配即判 CSRF）。CLI 入口 `opencode mcp auth [name]`。

## Code Mode and MCP

`code-mode`（`experimentalCodeMode` flag）把 MCP 工具编排成脚本调用。启用后 `session/tools.ts` 直接 return、**不再逐个注册 MCP 工具**；`code-mode.ts` 执行时取 `Permission.visibleTools(yield* mcp.tools(), ruleset)`，用 `groupByServer` 把 `server_tool` 平铺名转成 `server.tool` 命名空间，生成脚本工具树：

```typescript
const ruleset = Permission.merge(agent.permission, session.permission ?? [])
const mcpTools = Permission.visibleTools(yield* mcp.tools(), ruleset)
const servers = Object.keys(yield* mcp.clients()).map(McpCatalog.sanitize)
const catalog = [...groupByServer(mcpTools, servers).values()].flat()
const runtime = CodeMode.make({ tools: toolTree(catalog, callTool), onToolCallStart, onToolCallEnd })
```

脚本里每次子调用走 `invokeChildTool`，它**刻意复刻** `McpCatalog.convertTool` 的 `client.callTool`（注释："Deliberately mirrors McpCatalog.convertTool's transport call so the MCP service stays free of tool-loop concerns"），同样套 `tool.execute.before` → `ctx.ask` → `tool.execute.after`。一句话：普通模式每个 MCP 工具直接成为 AI tool；code-mode 把这些工具变成 `execute` 脚本里的命名空间函数，由解释器编排批量调用，但复用同一套 MCP client、permission 与 hook 链。详见 [Tools](/docs/CS/AI/LLM/Agent/Product/OpenCode/Tools.md)。

## Links

- [Tools](/docs/CS/AI/LLM/Agent/Product/OpenCode/Tools.md) / [Plugin](/docs/CS/AI/LLM/Agent/Product/OpenCode/Plugin.md) / [Agent](/docs/CS/AI/LLM/Agent/Product/OpenCode/Agent.md)
- [Server](/docs/CS/AI/LLM/Agent/Product/OpenCode/Server.md) / [Skills](/docs/CS/AI/LLM/Agent/Product/OpenCode/Skills.md) / [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)

## References

1. [opencode/src/mcp/index.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/mcp/index.ts)
2. [opencode/src/mcp/catalog.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/mcp/catalog.ts)
3. [opencode/src/mcp/oauth-provider.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/mcp/oauth-provider.ts)
4. [core/src/v1/config/mcp.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/core/src/v1/config/mcp.ts)
5. [OpenCode MCP 文档](https://opencode.ai/docs/mcp-servers/)
