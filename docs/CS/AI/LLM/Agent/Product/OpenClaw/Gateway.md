## Introduction

Gateway 是 OpenClaw 的控制平面与唯一枢纽：CLI、原生 app、Control UI、远端 worker、外部 harness 全部连它。这一页覆盖它的**启动结构**与**RPC / HTTP 协议面**两角；运行期的热重载与生命周期服务在 [Lifecycle](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Lifecycle.md)，会话存储在 [Storage](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Storage.md)，插件与渠道契约在 [Plugins](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Plugins.md) / [Channels](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Channels.md)，安全校验点在 [Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md)。它与 [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md) 枢纽页的「Tech Stack」一节相接。

## Gateway: The Center

Gateway 是全仓最大的子系统，也是唯一的核心枢纽。两个命名陷阱先记：

- 真入口是 `startGatewayServerCore`（`src/gateway/server-start.ts`）；目录下的 `boot.ts` **不是启动器**，而是「BOOT.md workspace 校验 runner」。
- 端口不是「双控制面」：**18789 是主端口，单端口承载 HTTP REST + WebSocket RPC + Control UI**（CLI、TUI、原生 app、Web UI、node worker、channel webhook 全连这里）；**18790 是 MCP App sandbox 端口**（= 18789 + 1，延迟启动），只服务 `/mcp-app-sandbox` 的隔离 HTML widget 渲染；Tailscale 是额外 ingress，不另起固定端口。

启动分两阶段，边界就是 control-plane / runtime-plane：

```
CLI gateway 命令
  ▼ server-start.ts  startGatewayServerCore(port=18789)
createGatewayKernel            阶段 A：Kernel 预载（零 plugin runtime）
  │  pluginMetadata.runBootstrap → 只做 discovery + manifest + config 快照
  │  prepareGatewayKernelState   → 备好 worker placement / channel runtime 引用（未加载）
  ▼ server-start.ts  createGatewayHttpTransport   阶段 B：Transport 创建
  │  wss = new WebSocketServer({noServer:true})    # 先建 WS，避免 upgrade 竞态
  │  per bindHost: HTTP server + WS upgrade handler（control-ui 挂主端口路由）
  ▼ server-startup-finish.ts  finishGatewayStartup 阶段 B：子系统挂载
     startListening() → http.listen(18789)          # health 即可答
     startGatewayPostAttachRuntime:
       loadStartupPlugins → register(api)           # plugin runtime 在此真正加载
       startChannels(...)                           # 渠道启动
       startWorkerEnvironmentRuntime(...)           # worker placement runtime
       markSidecarsReady() → cron 等计划服务激活
```

CLI 本身是双角色：`doctor / config / setup / plugins / secrets / models` 等本地执行；`message / send / agent / tasks / sessions` 等经 `findRoutedCommand` 路由到 Gateway 执行——**CLI 既是本地工具，也是 Gateway 的客户端**，且路由 fast lane 与 Commander 的 `.action()` 引用的是同一批 handler。

## Gateway Protocol Surface

CLI、原生 app、Control UI、外部 harness（ACP）全部走**同一张 Gateway 方法注册表**发起 RPC——这是全库调用面最集中的契约。

### RPC Method Registry

方法描述符词汇 = `name / handler / scope / owner / profileAccess / since / startup / controlPlaneWrite / advertise`；`startup: "available" | "unavailable-until-sidecars"`，`profileAccess: "independent" | "required"`（`owner.kind==="core"` 默认 independent，其余 required），`owner.kind` 闭集 `core | plugin | channel | aux`。

注册表规则：

- 插件 scope **强制归一化**（防插件声明宽松 scope 冒充 core 名）；
- **重名即硬抛**——授权与派发对 owner/scope 的判断不允许有不一致窗口；
- legacy 纯 handler 注册回退 `{kind:"plugin", pluginId:"unknown"}` + ADMIN_SCOPE。

core 规格表约 465 行 `[name, family|null, scope, since, policy?]`，注释立不变式「规范表让 listing/auth/startup/throttle 保持同步」，advertised 列表 **append-only** 保老客户端索引稳定；**任何 core handler 缺 spec 行即抛**。`server-methods/` 是 392 个非测试文件 / ~101.5k LOC 的巨族，112 个文件导出 handler map；**family = 懒加载单元**，且规格表 family 列与动态 import map 双声明 `satisfies` 互校。skills 是 36 方法的最大家族。

### Dispatch and Authorization Fence

一次 WS req 帧的派发围栏先于任何 handler 执行：

```
validateRequestFrame（packages/gateway-protocol）
  → registry 择优（caller-attached 优先，缺方法才重建并保 plugin-over-core 序）
  → authorizeGatewayRequestPreDispatch
      session 投影就绪 / plugin-registry scope / authenticated-profile 门
      startup 门（unavailableGatewayMethods → retryable UNAVAILABLE）
      session-sharing 授权解析（带 re-run 环）/ node pairing 复校
  → authorizeGatewayMethod：role 闭集 operator|node；write⇒read/talk 蕴含；未分类 default-deny
  → controlPlaneWrite 节流：30 req/60s，key = method|deviceId|clientIp
  → handler（unknown = INVALID_REQUEST）
```

握手后仍有 live-authority 复校：shared-auth 代际过期 → close 4001、重复未授权 flood guard → 1008。**不存在通用 HTTP→method 映射**——RPC 只有 WS req 帧 + 进程内两条路，HTTP 是独立的 route surface（见下节）。客户端 `callGateway` 是最小权限入口（149 个 import 站点）：写形 RPC 铸 `randomIdempotencyKey()`，服务端把 idempotency 行 + lifecycle claim **原子提交**，重试即采纳已持久化的 turn 而非二次提交。

### WS Connection Lifecycle

HTTP upgrade 领 preauth 预算（默认 32/IP，不可解析 IP 走 fail-closed 共享桶）→ 定 kind（worker vs gateway）→ 握手 phase tracker（**首帧必为 connect**）→ hello-ok 携带 `protocol / features.methods / events`。护栏密集：超大 preauth 帧 1009、worker 身份伪造 1008、origin 策略（配置提交后实时撤销）、payload-limit 注册后才抬高、operator 请求共享有界 start 队列（`MAX_STARTS_PER_TURN=64`）忙则 retryable UNAVAILABLE。**两种「代际」勿混**：`sha256(mode+secret)` 的认证-secret 代际（per-request staleness → close 4001）与数据库 / 投影代际是两回事。

### OpenAI Compatible API

主端口同端口承载，**默认关闭**（`gateway.http.endpoints.{chatCompletions,responses}.enabled` 默认 false，toggle 下一请求即生效）。端点全表面：

| 端点 | 说明 |
| :--- | :--- |
| `GET /v1/models[/:id]` | 列的是 **agent 目标**（`openclaw` / `openclaw/default` / `openclaw/<agentId>`），不是 provider 模型 |
| `POST /v1/chat/completions` | messages → prompt 翻译 → 进程内 run（`runId="chatcmpl_<uuid>"`、`deliver:false`）→ SSE |
| `POST /v1/responses` | OpenResponses；`resp_<uuid>`，`previous_response_id` 链是内存 map（30min TTL / 500 cap / auth-subject 绑定），具名 SSE 事件 |
| `POST /v1/embeddings` | 桥接 agent memory / embedding provider，不启动 run |
| `/tools/invoke`、`/sessions/:key/history`、`/sessions/:key/kill` | 邻近非 OpenAI HTTP（kill 需 ADMIN_SCOPE） |

映射链：model → agent（`resolveAgentIdFromModel`，`x-openclaw-agent-id` header 可覆盖）；session key 取 `x-openclaw-session-key` / `openai-user:<user>` / `openai:<uuid>`，**保留命名空间 `subagent:` / `cron:` / `acp:` 直接拒**；client tools / tool_choice 译成 `ClientToolDefinition` 且 run 后强制 satisfaction。执行**与 WS chat 共享同一执行器**（`agentCommandFromGatewayIngress` 进程内 run，不是另立 executor），增量经 run-scoped agent-event 总线推 SSE。认证是刻意不同的模型：**shared-secret bearer 视作完整 operator scopes**（代码注释 "designed-as-is"）。整个 HTTP 面是单端口**有序阶段路由**（first-claim-wins）：health → worker 命名空间 → device-pairing shortcode → OAuth 回调 → hooks → watchOS → OpenAI 端点 → board / control-ui assets → canvas docs → plugin routes → media → generic Control UI 垫底（注释明言 core+recovery 先、插件路由次、只读 UI 末）。

## Chat Display Projection

Gateway 里有**两个投影层，维度不同**：[Storage](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Storage.md) 里的 `session-row-projection` 投影「会话列表行」（list / describe 维度），而 `chat-display-projection` 投影「会话内的聊天历史消息」（message / history 维度）。后者把底层 session transcript 投影成前端 / Chat UI 可消费的渲染消息结构，本体是 `chat-display-projection.core.ts` 加一组子模块。

核心管线 `projectChatDisplayMessagesWithState` 是**一条严格有序的多阶段投影**：

```
1. projectChatHistoryRecovery          —— 历史恢复：run-failed-before-reply、嵌套工具活动、
                                          message-tool 可见回复镜像、subagent 协调投影、
                                          被后续成功轮次修复的 assistant error
2. projectEmptyAssistantErrorMessages  —— 空错误 assistant 消息 → 兜底文案
3. sanitizeChatHistoryMessages(MAX)    —— 全量 sanitize（不截断），保留 commentary fallback 观察
4. projectForwardedMessages            —— 转发消息标 senderSession/senderLabel、剥 prompt 前缀
   filterVisibleProjectedHistoryMessages —— 隐藏 heartbeat 探测对与 display:false、
                                          去重 ACP/delivery 镜像、挂接 pending turn boundary
5. mergeTtsSupplementMessages          —— 把 TTS spawn 的音频块回贴到目标文本消息
6. sanitizeChatHistoryMessages(max)    —— 最终按 maxChars 截断
7. projectCurrentUserProfileAvatars    —— 给 user 消息投影当前用户头像/身份
```

返回结构除 `messages` 外还带四个展示态标志：`turnBoundaryPending`（有未闭合的轮次边界）、`assistantErrorPending`（还有挂起错误）、`assistantErrorRecoveryObserved`（观察到错误被修复）、`commentaryFallbacksObserved`——它们驱动 UI 的 loading / 重试态，而不是阻塞整个快照。

几个数值与策略值得记：展示截断上限 `DEFAULT_CHAT_HISTORY_TEXT_MAX_CHARS = 8_000`；reasoning / thinking 类 content 在展示中隐藏；媒体 URL 走脱敏与 `media://inbound/<id>` 鉴权路由归一；工具结果细节投影有 `MAX_TOOL_APPROVAL_REVIEWS = 16` 上限；**两次 sanitize 是刻意分开的**——中段全量做隐私 / 结构清洗，尾段只按 `maxChars` 截断，把「隐私」与「尺寸上限」两件事解耦。

还有一条设计取向很能说明产品态度：**错误恢复优先于展示**。`createRecoveredAssistantErrorProjection` 用 runId 关联「失败的 assistant 错误」与「后续成功完成的同 run」，把已被自愈的错误行从展示中摘掉——用户不该看到自己已经恢复的错误。

调用方是聊天历史页的 RPC 层（`chat-history-page-kernel.ts` / `chat-history-pages.ts`）：读 transcript 后做整页投影，并叠加 subagent 可见性、CLI 会话导入、canvas 增强与 compaction marker 的 token 指标。路由上有个分支：**incognito 会话与 CLI 会话走 local 路径不进 worker**，非 incognito 且非 CLI 绑定的才在 worker 进程里读 + 投影。

最后是另一条**互补路径** `live-chat-projector.ts`：历史投影做「完整页」，实时投影做「增量缓冲」——`capLiveAssistantText` 500_000 字符缓冲上限（裁剪不回填）、`normalizeLiveAssistantBufferedText` 去掉运行时内部上下文与媒体指令、`shouldSuppressAssistantEventForLiveChat` 在实时聊天中抑制 commentary 阶段事件。两者共享 helpers / visibility 等底层归一逻辑。

## Hot Reload and Lifecycle Services

配置热重载、node registry 与 session 生命周期服务（session-sharing、compaction checkpoints、`chat.abort`）已独立成页：[Lifecycle](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Lifecycle.md)。那里与这一页是「怎么说话 / 活着的时候怎么变」的分工；它与 [Storage](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Storage.md) 的写路径、[Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md) 的权威链直接相接。

## Links

- [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md)
- [Runtime](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Runtime.md) / [Plugins](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Plugins.md)
- [Storage](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Storage.md) / [Security](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Security.md)
- [Lifecycle](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Lifecycle.md) / [Clients](/docs/CS/AI/LLM/Agent/Product/OpenClaw/Clients.md)
- [TypeScript](/docs/CS/TypeScript/TypeScript.md) / [Nodejs](/docs/CS/front-end/Nodejs.md)
