## Introduction

这一页装两块「对外的边」：**ACP** 让 OpenClaw 与外部 agent 互操作（session/turn 级，与 MCP 的 tool 级互补），**媒体与多模态 I/O** 是内置 tools 的实体部分（图像 / 视频 / 音乐生成、入站附件理解、语音输出、网页抓取）。二者都是 [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw.md)「精简 core」原则下的产物：vendor 与协议 adapter 都在插件 / 扩展侧，core 只留契约与护栏。

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

媒体是四类 tool 来源里「内置 tools」的实体部分，分三层：**共享底座**（`src/media/`，modality-agnostic 的 probe / transcode / ffmpeg 沙箱 / media store，被生成与理解两侧同时复用）、**生成侧**（`media-generation/` 共享 registry + image / video / music 各模态 runtime）、**理解侧 + 语音 + 网页**（`media-understanding/` `tts/` `realtime-transcription/` `web-*`）。

生成侧的关键差别：**生成不走 LLM 的 `streamText` provider 调用，而是独立的 capability-provider 契约**（`provider.generateImage/Video/Music()` 直接执行）。三模态共用同一个 provider registry factory，配有序候选 fallback 引擎与几何归一；候选来自 `agents.defaults.mediaModels.<modality>`、override 与跨 provider auto fallback。 vendor（OpenAI / Google / fal / 阿里百炼等）是 `extensions/*` 插件，经 `registerImageGenerationProvider` 一类 API 注册；core 提供 OpenAI 兼容 / DashScope 兼容的 provider factory 供它们复用。工具名是 `image_generate` / `video_generate` / `music_generate`——**没有配置对应能力模型时 creator 返回 null，工具根本不注册**。生成结果**落文件 media store**（`<configDir>/media` 下按工具分子目录），SQLite 只记引用；任务状态是进程内 Map，不进 SQLite。

三条容易搞反的事实：

1. **理解是回退而非默认**：`runCapability` 里 native-vision 门控——活跃 chat 模型本身支持视觉时**跳过 image 理解**，图直接进模型上下文；理解只在模型不具备该能力时才发生。
2. **不是「生成 + 理解干净二分」**：生成侧的下载 helper 反而 import 自 `media-understanding/shared.js`，同一 registry 也服务两个转写 key。
3. **语音归属**：`src/tts/` 是 reply→audio 的**输出** owner，被 talk / meeting-bot 与渠道 reply 共享；`realtime-transcription/` 是入站 streaming STT（talk 经 transcription-relay 消费）。二者是 meeting-bot / talk 这个双向模态的两侧对偶，不是「一个补入站一个补出站」。

底座侧两处护栏：**ffmpeg 沙箱**有硬上限（buffer 10MB、ffprobe 10s、ffmpeg 45s、audio 20min）；读侧 hydrate 出不透明的 **`media://inbound/<id>` claim-check URI**（Gateway offload 写出），媒体不直接内联进存储。渠道扩展**不得直接 import `src/media`**，只走 plugin-sdk 的 `core.channel.media.*`。

网页 I/O 有两条内置 tool 与一个非工具富化环节，边界要分清：`src/web-*` 是 **provider 选择 / 执行层**，不是工具本体——工具是 `src/agents/tools/web-fetch.ts` / `web-search.ts`。

`web_fetch` 的**默认引擎在 tool 内**（core 直取 + Readability），`src/web-fetch/` 只负责 provider fallback 选择。执行流是：cache → `fetchWithWebToolsNetworkGuard`（SSRF-guarded）→ 内容整形（cf-markdown 直通 / HTML 经 `extractReadableContent` → provider fallback → 基本 HTML / JSON pretty）→ **untrusted 包裹**（来自 `security/external-content.js`，呼应 [Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md) 家族）+ 有界截断 + 私域内容 temp spill。两个「唯一」值得记：readability 的唯一 registrant 是 `extensions/web-readability`，唯一 fetch provider 是 `extensions/firecrawl`。

`web_search` 的候选序是 explicit → metadata → configured/auto，且**额外 consult provider auth profile**——用 codex / xai 时无需单独配 web key；provider（brave / perplexity / duckduckgo / exa / tavily 等）都是 extension 插件经 manifest 的 `webSearchProviders` capability 注册。这里有个易冲突点：**host `web_search` 与 provider-hosted `web_search` 服务工具不能撞车**，靠 `allowedHostedToolTypes` 过滤。

`link-understanding` 不是 tool，而是入站消息的**链接富化**：`extractLinksFromMessage` 先去 markdown-link span、用 `isBlockedHostnameOrIp` 预筛、默认 cap 3 条，然后严格 SSRF fetch + CLI processors，结果写进 `ctx.LinkUnderstanding`；时机是 media 理解之后、agent dispatch 之前。

**SSRF 只有一个 owner**：`src/infra/net/ssrf.ts`（`SsrFBlockedError` / `isBlockedHostnameOrIp` / `createPinnedDispatcher`）加 guard `fetch-guard.ts`（`GUARDED_FETCH_MODE` 三档 strict / trusted_env_proxy / trusted_explicit_proxy），web tool 与 link-understanding 共用；browser 扩展里那个同名文件只是 re-export shim。另外 guard 会在 `OPENCLAW_DEBUG_PROXY_ENABLED` 时 lazy-import proxy-capture 做 debug 抓取，与 [Observability](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Observability.md) 那页接上。

## Links

- [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw.md)
- [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md) / [Plugins](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Plugins.md)
- [Channels](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Channels.md) / [Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md)
- [MCP](/docs/CS/AI/LLM/Protocol/MCP.md)

## References

- [Agent Client Protocol 官方站](https://agentclientprotocol.com/)
