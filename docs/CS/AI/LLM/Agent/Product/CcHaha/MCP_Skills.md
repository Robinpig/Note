## Introduction

cc-haha 把 MCP 与 Skills 这两套扩展机制都做成了**可视化 GUI 管理**，并额外提供了第三方 **Skill 市场**。底层协议与 [ClaudeCode/Extensions](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Extensions.md)（Skills / Plugins / MCP / Output styles）同源，本页只讲 cc-haha 的 GUI 增量。

## Visual MCP Manager

GUI 增删 MCP 服务器，传输与作域来自 `desktop/src/types/mcp.ts` 与 `desktop/src/pages/McpSettings.tsx`：

- **传输（transport）**：`stdio` | `http` | `sse`——对应营销所说的 STDIO / Streamable HTTP / SSE；http / sse 可选 `oauth`（`clientId` / `callbackPort`）。
- **可写作用域（McpWritableScope）**：`local` | `project` | `user`——对应营销所说的 全局（user）/ 共享（user）/ 项目（project）。
- **读取分组**还含 `plugin` / `managed` / `enterprise` / `claudeai` / `dynamic`（`McpSettings` 的 `MCP_GROUP_ORDER`）。

可视化管理器经 `mcpApi.create / update / remove / toggle` 调用本地服务端 `/api/mcp/*`（`mcpStore.ts:19-24`），每条记录带 `configLocation` 字段。配置持久化**继承 Claude Code 的位置约定**（project 写 `.mcp.json`、user 写 user settings），确切文件路径以服务端实现为准。

## MCP Access: Consumer and Provider Sides

GUI 管理器的底层接入分两面（均区别于上节的 Skill 市场）：

### Consumer side: cc-haha connects to external MCP servers

- **模板工具 + 动态覆盖**：`MCPTool`（`MCPTool.ts`）是 `isMcp: true` 的占位模板——默认 `name: 'mcp'`、`call()` 返回空、`checkPermissions` 返回 `passthrough`；真实 name / args / description / `call` 在 `mcpClient.ts` 按各 MCP server 动态覆盖（`MCPTool.ts:27-55` 注释 "Overridden in mcpClient.ts"）。`inputSchema` 用 `z.object({}).passthrough()`——MCP 工具自带 schema，宿主不预设（`MCPTool.ts:14`）。
- **OAuth 伪工具**：未认证的 sse/http server 不暴露真实工具，而是用 `createMcpAuthTool` 注入一个**伪工具**（`mcp__<server>__authenticate`），模型调用它启动 `performMCPOAuthFlow`（`skipBrowserOpen: true`）拿到 authUrl 转交用户；OAuth 后台完成后 `reconnectMcpServerImpl` 用**前缀替换**（`mcp__<server>__*`）把真实工具 swap 进 `appState.mcp.tools`，伪工具随之自动移除（`McpAuthTool.ts:37-48,134-166`）。stdio 与 `claudeai-proxy` 不走此流（前者无 OAuth，后者走 `/mcp`）。
- **transport 支持**：`stdio` | `http` | `sse` | `claudeai-proxy`（GUI 层由 `McpSettings` 暴露，见上节）。

### Provider side: Computer Use as an MCP server

- `mcpServer.ts` 把 **Computer Use 能力包成 MCP server** 供外部 client（Cowork / claude-swift）调用，对应 `--computer-use-mcp` 子进程入口（`runComputerUseMcpServer`）：stdio transport、stdin close 退出、退出前 flush analytics（`mcpServer.ts:80-106`）。
- `createComputerUseMcpServerForCli` 委托 `vendor/computer-use-mcp` 的 `createComputerUseMcpServer`，并**替换 ListTools handler** 把已安装 app 名塞进平台特定 tool description（`mcpServer.ts:46-78`）；真实 dispatch 仍走 `wrapper.tsx` 的 `.call()` override——这个 server 只答 ListTools（`mcpServer.ts:57-58`）。
- 这是 cc-haha 把自家能力"反向"开放为 MCP 的示例，与消费侧形成闭环。

## Visual SubAgent Manager

GUI 创建与调优 SubAgent：配置模型、工具、权限模式——把原本要写配置的 subagent 定义变成表单操作。

## Skill Marketplace

由本地服务端 `/api/market/*` 后端聚合外部注册源（`desktop/src/api/market.ts:27-78`：list / detail / fileContent / install / uninstall / status）：

- **注册源（双源聚合）**：`ClawHub` 与 `SkillHub` 均已在服务端代码确认真实存在——`clawhubProvider.ts` 与 `skillhubProvider.ts`（`src/server/services/market/`）实现同一 `MarketProvider` 接口，由 `marketService.ts` 聚合。`SkillHub` 后端为 `https://api.skillhub.cn`，提供 `GET /api/skills`（list，分页参数须用 `pageSize`、搜索须用 `keyword`）、`/api/v1/skills/{slug}`（detail）、`/files`、`/file`（302 跳腾讯云 COS）四接口（`skillhubProvider.ts:1-11,140-283`）；`ClawHub` 同构。二者通过 `source` 字段区分（`skillId('clawhub' | 'skillhub', slug)`）。
- **两种 scope**：catalog（策展快照）与 live（实时）（`MarketHome.tsx:105`）。
- **安装前安全报告**：详情接口返回 `skills` + `sourceStatus`；`SecurityReportPanel` 在安装前渲染能力清单 + 各扫描器报告（`vendor` / `status` / `statusText` / `reportUrl`）+ 策展者 `securityNote`（`SecurityReportPanel.tsx:21-97`）。`SkillHub` 的 `securityReports` 被归一为 `benign`/`safe`/`clean` 或 `flagged`（`skillhubProvider.ts:73-93`）。列表支持 `security` 过滤（`market.ts:22,35`）。

在装上未知 skill 前先暴露风险，比纯命令行安装多一层可见性。

## Links

- [CcHaha 主枢纽](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md)
- [Models](/docs/CS/AI/LLM/Agent/Product/CcHaha/Models.md)

## References

- [cc-haha GitHub](https://github.com/NanmiCoder/cc-haha)
- [mcp.ts 类型](https://github.com/NanmiCoder/cc-haha/blob/main/desktop/src/types/mcp.ts)
- [market.ts](https://github.com/NanmiCoder/cc-haha/blob/main/desktop/src/api/market.ts)
- [MCPTool.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/MCPTool/MCPTool.ts)
- [McpAuthTool.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/McpAuthTool/McpAuthTool.ts)
- [computerUse mcpServer.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/computerUse/mcpServer.ts)
