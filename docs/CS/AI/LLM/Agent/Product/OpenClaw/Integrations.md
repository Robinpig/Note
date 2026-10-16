## Introduction

这一页装 OpenClaw 对外互操作的那张牌：**ACP**（Agent Client Protocol）让 OpenClaw 与外部 agent 在 session / turn 级互操作，与 MCP 的 tool 级互补。媒体与多模态 I/O 在 [Media](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Media.md)。二者都是 [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md)「精简 core」原则下的产物：vendor 与协议 adapter 都在插件 / 扩展侧，core 只留契约与护栏。

## ACP: Agent Client Protocol

**ACP**（Zed 主导的开放协议）是 OpenClaw 对外互操作的第二张牌，与 MCP 互补但**抽象层级不同**：

| 维度 | MCP | ACP |
| :--- | :--- | :--- |
| 抽象层级 | **tool 级**（`tools/list` / `tools/call`） | **session / turn 级**（`initialize` / `newSession` / `loadSession` / `prompt` / `cancel` / `resumeSession` / `closeSession` / `setSessionMode` …） |
| Transport | stdio / SSE / Streamable HTTP | ndjson JSON-RPC over stdio，Gateway 侧走 WS |
| 组合约束 | — | **与 ACP bridge 互斥**：per-session `mcpServers` 一律被拒；要让外部 MCP client 直连 channel 走 `openclaw mcp serve` |

同一个 `src/acp/` 目录承载两种角色：**bridge**（OpenClaw 作 ACP server 被 IDE 驱动，`openclaw acp`）与 **harness**（OpenClaw 作 ACP client 驱动 Claude Code / Codex / Cursor 等外部 agent，backend 由 `acpx` 插件在 runtime registry 注册）。

Bridge 侧几处工程细节值得单独记：

- **启动防死锁**：`serveAcpGateway` 先把 stdin 缓存进 `MAX_STARTUP_ACP_BUFFER_BYTES = 1 MiB` 等 Gateway hello，避免握手前静默卡死。
- **协议面拆分**：11 个 ACP 方法拆给四个协作类——session 生命周期、prompt stream（落成 Gateway `chat.send` / `chat.abort`）、agent events（Gateway tool/approval 事件流 → ACP `tool_call` / `session/request_permission`）、session updates（客户端 emit 与 ledger **双写**）。
- **`session/new` 保序**：SDK 只在 handler 返回后才序列化结果，所以 `loadSession` / `resumeSession` 期间的 `session/update` 先经一层独立 TransformStream 排队（上限 256 条/会话），等 response 落地再放行。
- **两条硬防线**：session 创建限流 120 req / 10s；`MAX_PROMPT_BYTES = 2 MiB`，拼接前**逐 block 累加 UTF-8 字节**而非事后测长度（对应 CWE-400 / GHSA-cxpw-2g23-2vgw）。

`runtime: "acp"` 也是 SubAgent 派生的变体：`spawnAcpDirect` 与 subagent spawn 平级、复用同一条三阶段管线，session key 形如 `agent:<agentId>:acp:<uuid>`；一条架构守卫测试逐个源文件断言不得出现 Discord 专用 legacy thread binding —— **ACP 一律走通用 session binding service**。

外部 agent 的工具审批走**八桶风险分桶**（`readonly_scoped` / `readonly_search` / `mutating` / `exec_capable` / `control_plane` / `interactive` / `other` / `unknown`），**只有前两类自动批准**：

- **反伪造身份**：`_meta.toolName`、title 前缀、`rawInput.tool` **三源必须一致**，否则归 `unknown` 拒批——协议里的 `toolCall.kind` 被明确当作不可信元数据。
- **cwd 作用域**：`read` 只在路径**全部落在 cwd 内**才算 `readonly_scoped`，`file:` URL 逃逸与 `~` 展开都被显式处理。
- **非 TTY 自动拒绝**（stdin 交互 30s 超时默认拒），防 CI 环境静默批准。
- ACP 侧只是把 pending 审批**投影**到客户端，权威仍在 [Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md) 里的 Gateway approval store；断线重连会重放未决审批。

`loadSession` 重放用的是一张 **ACP 专用双表账本**（共享 state DB 的 `acp_replay_sessions` + `acp_replay_events`，不是 per-agent transcript）：每 row 计 32 字节固定开销、**列级分别测量 UTF-8**（避免孤立代理项跨列拼成合法字符导致误算）、每 session 维护运行字节聚合使预算检查从 O(events) 降到 O(sessions)；预算三档 200 sessions / 5000 events / 16 MiB；trim 按事件批（64）与「最老更新优先」三级递进；账本被判不完整时降级回退到 Gateway transcript 抽取回放块。ACP sessionId ↔ Gateway sessionKey 的映射是唯一单点，默认 fallback `acp-bridge:<uuid>` 属「合成且可弃」。

## Media and Multimodal I/O

媒体与多模态 I/O（图像 / 视频 / 音乐生成、入站附件理解、语音输出与实时转写、会议机器人、网页抓取搜索）已独立成页：[Media](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Media.md)。那一页与 ACP 同属「精简 core 原则下的对外边界」：vendor 与协议 adapter 都在插件 / 扩展侧，core 只留契约与护栏。

## Links

- [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md)
- [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md) / [Plugins](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Plugins.md)
- [Media](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Media.md) / [Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md)
- [MCP](/docs/CS/AI/LLM/Protocol/MCP.md)

## References

- [Agent Client Protocol 官方站](https://agentclientprotocol.com/)
