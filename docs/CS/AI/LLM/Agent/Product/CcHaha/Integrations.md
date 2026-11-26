## Introduction

> 版本基线：v0.7.7（本地源码 E:/Projects/cc-haha-0.7.7）

cc-haha 把「会话不止在桌面」做成核心卖点：IM 适配器把手机聊天软件的消息接进桌面会话，手机 / 平板浏览器打开 H5 地址可驱动同一台电脑，计划任务做无人值守运行。三者落点并不相同：IM 走 `adapters/common/ws-bridge.ts` 连服务端 `/ws/:sessionId`，H5 走本地服务端 `/ws/*` 端点并用 token 鉴权，计划任务由 CLI / REPL 侧调度器 headless 拉起独立进程，不经该桥。本页所有论述均以 v0.7.7 本地源码为准，路径写在代码块外、不带行号，块内为原样连续摘取的真实源码片段。

## IM Integration

`adapters/` 下实际实现的平台目录（相对仓库根）共 8 个：wechat / feishu / dingtalk / telegram / whatsapp / qq / slack / wecom。`adapters/README.md` 的用户文档清单与此一致（本次深挖只读 wechat / telegram / feishu 三端源码，其余以 README 为准）。这与 [OpenClaw](/docs/CS/AI/LLM/Agent/Product/OpenClaw/OpenClaw.md) 的「本地优先个人助手网关、接管 20+ 通讯软件」路线相似，区别在于 cc-haha 以编程工作台为本体、IM 是附属通道，而 OpenClaw 以网关为本体。

```md
# Claude Code IM Adapters

当前目录只放 IM Adapter 运行时代码。

用户文档已经迁移到 `docs/`，并且以 Desktop Webapp 配置流程为准：

- `docs/im/index.md`
- `docs/im/wechat.md`
- `docs/im/dingtalk.md`
- `docs/im/whatsapp.md`
- `docs/im/telegram.md`
- `docs/im/feishu.md`
- `docs/im/wecom.md`
- `docs/im/qq.md`
- `docs/im/slack.md`
```

**公共架构** `adapters/common/ws-bridge.ts`（`WsBridge`）：维护 `chatId → sessionId` 映射，`connect()` 连服务端 `/ws/${sessionId}` 并在需要时附 `token` 查询参数。

```ts
  /** Connect to a session with a known sessionId. Returns false if already connected. */
  connectSession(chatId: string, sessionId: string): boolean {
    const existing = this.sessions.get(chatId)
    if (existing && existing.ws.readyState === WebSocket.OPEN) {
      return false
    }
    this.connect(chatId, sessionId)
    return true
  }
```

```ts
  private connect(chatId: string, sessionId: string): void {
    const url = new URL(`${this.serverUrl}/ws/${sessionId}`)
    if (this.localAccessToken) {
      url.searchParams.set('token', this.localAccessToken)
    }
    const ws = new WebSocket(url)
```

心跳常量 30s、指数退避重连上限 30s / 10 次、以及 30min 空闲释放常量都在同一文件头部定义：

```ts
const HEARTBEAT_INTERVAL_MS = 30_000
const RECONNECT_BASE_MS = 1000
const RECONNECT_MAX_MS = 30_000
const MAX_RECONNECT_ATTEMPTS = 10
/**
 * A chat's socket keeps its session's CLI — and the MCP servers under it —
 * alive on the desktop host for as long as it stays open (#1485). After this
 * long without any traffic, with nothing running and nothing waiting for an
 * approval, the socket is closed; the chat's next message reopens it through
 * restoreStoredSessionBinding, at the cost of one CLI start.
 */
export const IDLE_SESSION_RELEASE_MS = 30 * 60_000
```

每个聊天有**串行化 handler 链**：文件头注释与 `ws.on('message')` 里把每条消息链到上一条 promise 之后，避免 `await` 处的状态竞态。

```ts
  /** Single handler per chatId — separate from sessions so reconnect doesn't duplicate */
  private handlers = new Map<string, MessageHandler>()
  /** Per-chat FIFO queue of in-flight handler promises.
   *  Ensures an async handler for message N completes before handler for N+1
   *  starts, preventing state races at `await` points. */
  private handlerChains = new Map<string, Promise<void>>()
```

```ts
      // Serialize per-chat handler calls: chain each message onto the previous
      // one so a slow handler (e.g. one awaiting im.message.create) fully
      // finishes before the next message's handler runs. This prevents state
      // races where a later message reads stale map entries set up by an
      // earlier-but-still-in-flight handler.
      const prev = this.handlerChains.get(chatId) ?? Promise.resolve()
      const next = adapterMigrationLifecycle.track(prev
        .catch(() => {}) // upstream errors must not poison the chain
        .then(() => {
          // Resetting a chat cannot cancel promises already queued for its old
          // socket. Recheck ownership when delivery actually starts, then use
          // the current handler so restoration's temporary buffer cannot trap
          // initial status/permission frames after the live handler replaces it.
          if (this.sessions.get(chatId) !== session) return
          return this.handlers.get(chatId)?.(msg)
        })
        .catch((err) => {
          console.error(`[WsBridge] Handler error on ${chatId}:`, err)
        }))
      this.handlerChains.set(chatId, next)
```

指数退避重连按 `2^(n-1)` 计算 delay 并封顶，空闲释放由心跳 tick 顺带触发：

```ts
  private scheduleReconnect(chatId: string, sessionId: string): void {
    if (this.destroyed) return
    const session = this.sessions.get(chatId)
    if (!session) return
    if (session.reconnectAttempts >= MAX_RECONNECT_ATTEMPTS) {
      console.error(`[WsBridge] Max reconnect attempts reached for ${sessionId}, giving up`)
      this.sessions.delete(chatId)
      this.handlers.delete(chatId)
      return
    }

    session.reconnectAttempts++
    const delay = Math.min(
      RECONNECT_BASE_MS * Math.pow(2, session.reconnectAttempts - 1),
      RECONNECT_MAX_MS,
    )
    console.log(`[WsBridge] Reconnecting ${sessionId} in ${delay}ms (attempt ${session.reconnectAttempts}/${MAX_RECONNECT_ATTEMPTS})`)
    session.reconnectTimer = setTimeout(() => {
      if (this.destroyed) return
      if (this.sessions.get(chatId)?.sessionId === sessionId) {
        this.connect(chatId, sessionId)
      }
    }, delay)
  }

  private startHeartbeat(intervalMs: number): void {
    this.heartbeatTimer = setInterval(() => {
      this.releaseIdleSessions()
      for (const [, session] of this.sessions) {
        if (session.ws.readyState === WebSocket.OPEN) {
          session.ws.send(JSON.stringify({ type: 'ping' }))
        }
      }
    }, intervalMs)
  }
```

**入站消息流**。微信端靠 `pollLoop` 循环拉 `getWechatUpdates`；Telegram 用 `bot.on('message:text')`；飞书注册 `im.message.receive_v1` 分发器。三段分别是：

```ts
async function pollLoop(): Promise<void> {
  while (!stopped) {
    try {
      const resp = await getWechatUpdates({
        baseUrl,
        token: botToken,
        getUpdatesBuf,
        timeoutMs: GET_UPDATES_TIMEOUT_MS,
      })
      if (resp.get_updates_buf) getUpdatesBuf = resp.get_updates_buf
      if (stopped) return
```

```ts
bot.on('message:text', async (ctx) => {
  await routeUserMessage(ctx, ctx.message.text, [])
})
```

```ts
  dispatcher.register({
    'im.message.receive_v1': async (data: any) => {
      try {
        await adapterMigrationLifecycle.track(handleMessage(data))
      } catch (err) {
        logger.error('[Feishu] Message handler error:', err)
      }
    },
    'card.action.trigger': async (data: any) => {
      try {
        return await adapterMigrationLifecycle.track(handleCardAction(data))
      } catch (err) {
        logger.error('[Feishu] Card action error:', err)
      }
    },
  } as any)
```

配对校验用 `adapters/common/pairing.ts` 导出的 `isAllowedUser` / `tryPair`（三端均引入 `../common/pairing.js`）。微信端在入站消息里先判权限、未授权时尝试配对码：

```ts
  if (!isAllowedUser('wechat', chatId)) {
    const success = text
      ? tryPair(text, { userId: chatId, displayName: 'WeChat User' }, 'wechat')
      : false
    await sendText(
      chatId,
      success
        ? '配对成功！现在可以开始聊天了。\n\n发送消息即可与 Claude 对话。发送 /help 查看可用命令。'
        : '未授权。请先在 Claude Code 桌面端完成微信扫码绑定，再生成 IM 配对码后发送给我。',
    )
```

通过校验后 `ensureSession` → `createSessionForChat`：`httpClient.createSession(workDir)` 建会话、`bridge.connectSession` 连桥、注册 `handleServerMessage`：

```ts
async function ensureSession(chatId: string): Promise<boolean> {
  const result = await ensureExistingSession(chatId)
  if (result.status === 'restored') return true
  if (result.status === 'unavailable') {
    await sendText(chatId, SESSION_RECONNECT_NOTICE)
    return false
  }

  const workDir = defaultWorkDir
  if (workDir) return await createSessionForChat(chatId, workDir)

  await showProjectPicker(chatId)
  return false
}

async function createSessionForChat(chatId: string, workDir: string): Promise<boolean> {
  sessionSelectionController.clear(chatId)
  try {
    bridge.resetSession(chatId)
    clearTransientChatState(chatId)
    const sessionId = await httpClient.createSession(workDir)
    sessionStore.set(chatId, sessionId, workDir)
    bridge.connectSession(chatId, sessionId)
    bridge.onServerMessage(chatId, (msg) => handleServerMessage(chatId, msg))
    const opened = await bridge.waitForOpen(chatId)
    if (!opened) {
      await sendText(chatId, '连接服务器超时，请重试。')
      return false
    }
    return true
```

服务端回包经各端 `handleServerMessage` 渲染成 IM 消息；权限请求以 Telegram `InlineKeyboard`（允许 / 永久允许 / 拒绝，回传 `permit:<requestId>:...`）或飞书 `msg_type: 'interactive'` 卡片呈现，用户选择后经 `bridge.sendPermissionResponse` 回传：

```ts
      const text = `${formatPermissionRequest(msg.toolName, msg.input, msg.requestId)}\n\n${formatPermissionInstructions(msg.requestId)}`
      const keyboard = new InlineKeyboard()
        .text('✅ 允许', `permit:${msg.requestId}:yes`)
        .text('♾️ 永久允许', `permit:${msg.requestId}:always`)
        .row()
        .text('❌ 拒绝', `permit:${msg.requestId}:no`)
      await bot.api.sendMessage(numericChatId, text, { reply_markup: keyboard })
```

```ts
/** Send an interactive card (for permission requests). */
async function sendCard(chatId: string, card: Record<string, unknown>): Promise<string | undefined> {
  try {
    const resp = await larkClient.im.message.create({
      params: { receive_id_type: 'chat_id' },
      data: {
        receive_id: chatId,
        msg_type: 'interactive',
        content: JSON.stringify(card),
      },
    })
    return resp.data?.message_id
  } catch (err) {
    logger.error('[Feishu] Send card error:', err)
    return undefined
  }
}
```

```ts
  sendPermissionResponse(
    chatId: string,
    requestId: string,
    allowed: boolean,
    rule?: string,
  ): boolean {
    const message: Record<string, unknown> = {
      type: 'permission_response',
      requestId,
      allowed,
    }
    if (rule) message.rule = rule
    return this.send(chatId, message)
  }
```

## H5 Remote Access

`src/server/services/h5AccessService.ts` 是核心。`createToken()` 生成 `h5_<base64url 32 字节>`，`hashToken()` 用 sha256 做摘要：

```ts
function hashToken(token: string): string {
  return createHash('sha256').update(token).digest('hex')
}

function createToken(): string {
  return `h5_${randomBytes(32).toString('base64url')}`
}

function createTokenPreview(token: string): string {
  return `${token.slice(0, 7)}...${token.slice(-4)}`
}
```

`enable()` 复用已有 token（重启 / 重新开启后已配对手机不失效），`setToken()` 把 `enabled` / `token` / `tokenHash` / `tokenPreview` 一起写进 managed settings 的 `h5Access` 块：

```ts
  private async setToken(
    managedSettings: Record<string, unknown>,
    current: StoredH5AccessSettings,
    { reuseExistingToken }: { reuseExistingToken: boolean },
  ): Promise<{
    settings: Record<string, unknown>
    result: H5AccessEnableResult
  }> {
    const token = reuseExistingToken && current.token ? current.token : createToken()
    const nextSettings: StoredH5AccessSettings = {
      ...current,
      enabled: true,
      token,
      tokenHash: hashToken(token),
      tokenPreview: createTokenPreview(token),
    }

    return {
      settings: {
        ...managedSettings,
        h5Access: nextSettings,
      },
      result: {
        settings: toPublicSettings(nextSettings),
        token,
      },
    }
  }

  async getSettings(): Promise<H5AccessSettings> {
    const { h5Access } = await this.readStoredSettings()
    return toPublicSettings(h5Access)
  }

  async enable(): Promise<H5AccessEnableResult> {
    // Re-enabling keeps the existing token (issue #767: a stable token means
    // phones that already paired keep working). Use regenerateToken to rotate.
    return this.managedSettingsService.updateSettings(async (current) => {
      return this.setToken(current, normalizeStoredSettings(current.h5Access), {
        reuseExistingToken: true,
      })
    })
  }
```

`validateToken` 只比对哈希；`isOriginAllowed` 用 `allowedOrigins` 白名单；`getDisconnectGraceMs` 把 `disconnectGraceSeconds` 换算成断连后停止会话的宽限毫秒：

```ts
  /**
   * Idle grace period (ms) before an unobserved session is stopped after the
   * last client disconnects. Reads the configured value, falling back to the
   * built-in default. Used by the WebSocket handler's disconnect cleanup.
   */
  async getDisconnectGraceMs(): Promise<number> {
    const { h5Access } = await this.readStoredSettings()
    return h5Access.disconnectGraceSeconds !== null
      ? h5Access.disconnectGraceSeconds * 1000
      : DEFAULT_DISCONNECT_GRACE_MS
  }

  async validateToken(token: string | null | undefined): Promise<boolean> {
    if (!token) {
      return false
    }

    const { h5Access } = await this.readStoredSettings()
    if (!h5Access.enabled || !h5Access.tokenHash) {
      return false
    }

    return hashToken(token) === h5Access.tokenHash
  }
```

```ts
  async isOriginAllowed(origin: string | null | undefined): Promise<boolean> {
    if (!origin) {
      return false
    }

    const { h5Access } = await this.readStoredSettings()
    if (!h5Access.enabled) {
      return false
    }

    try {
      const normalizedOrigin = normalizeOriginInput(origin, 'origin')
      return h5Access.allowedOrigins.includes(normalizedOrigin)
    } catch {
      return false
    }
  }
```

`publicBaseUrl` 的自动探测受 `CLAUDE_H5_AUTO_PUBLIC_URL` 门控，调用 `findPrivateLanAddress()` 取局域网 IPv4：

```ts
function resolveAutoLanPublicBaseUrl(): string | null {
  if (process.env.CLAUDE_H5_AUTO_PUBLIC_URL !== '1') {
    return null
  }

  const host = findPrivateLanAddress()
  if (!host) {
    return null
  }

  return `http://${host}:${ProviderService.getServerPort()}`
}
```

```ts
export function findPrivateLanAddress(networkInterfaces: NetworkInterfaces = os.networkInterfaces()): string | null {
  const candidates: Array<{
    address: string
    interfaceName: string
    index: number
    score: number
  }> = []

  let index = 0
  for (const [interfaceName, entries] of Object.entries(networkInterfaces)) {
    for (const entry of entries ?? []) {
      if (entry.family !== 'IPv4' || entry.internal || !isPrivateIPv4(entry.address)) {
        continue
      }

      candidates.push({
        address: entry.address,
        interfaceName,
        index,
        score: scoreLanAddressCandidate(interfaceName, entry.address),
      })
      index += 1
    }
  }
```

手机 / 平板扫码后由 `src/server/staticH5.ts` 提供页面。v0.7.7 这里服务的是手机 App 的 H5（Expo web 导出、`/m` 路由），资产缓存正则覆盖 `/assets/` 与 `m/_expo/static`、`m/assets`：

```ts
/**
 * The phone H5 app: the Expo web export of `mobile/`, built into `dist/m`
 * (`mobile/app.config.ts` sets this base path). It is its own single-page
 * app, so a reload anywhere under it must get its own index document.
 */
export const MOBILE_H5_BASE_PATH = '/m'

// Content-hashed file names: Vite's `/assets/`, and Expo's bundles and assets.
const CACHEABLE_ASSET_RE = /^\/(?:assets|m\/_expo\/static|m\/assets)\//
```

```ts
export async function handleStaticH5Request(req: Request, url: URL): Promise<Response | null> {
  if (req.method !== 'GET' && req.method !== 'HEAD') {
    return null
  }

  const distDir = await resolveH5DistDir()
  if (!distDir) {
    return null
  }

  if (isMobileH5Page(url.pathname) && !(await fileIfExists(mobileIndexPath(distDir)))) {
    // A phone that index.html sent here, on a server built without the phone
    // app. The desktop document cannot boot under /m/ (its asset URLs are
    // relative), so send it back to the entry: arriving straight back skips
    // the fast path, and the app keeps its own phone layout.
    return new Response(null, {
      status: 302,
      headers: { Location: '/', 'Cache-Control': 'no-store' },
    })
  }

  const filePath = await resolveStaticFilePath(distDir, url.pathname)
  if (!filePath) {
    return null
  }
```

`desktop/dist` 只是 `resolveH5DistDir()` 的一众候选目录之一，不是「发给手机的桌面页面」：

```ts
    path.resolve(process.cwd(), 'desktop', 'dist'),
    path.resolve(process.cwd(), 'dist'),
  ].filter((candidate): candidate is string => !!candidate)
```

H5 连 `/ws/:sessionId?token=...`：服务端从 `/ws/` 路径的查询参数取 `token`，鉴权中间件用 `validateToken` 校验（哈希），CORS 中间件用 `isOriginAllowed`：

```ts
        const localTokenOverride = url.searchParams.get('localToken') ?? url.searchParams.get('token')
        // Browser WebSockets cannot set Authorization headers. Keep the pet
        // query-token exception scoped to /ws; REST pet access remains bearer-only.
        const petTokenOverride = url.pathname.startsWith('/ws/')
          ? url.searchParams.get('token')
          : null
```

```ts
  const parsedAuth = parseBearerToken(req.headers.get('Authorization'))
  const h5Token = tokenOverride ?? parsedAuth.token
  if (h5Token) {
    const h5AccessService = new H5AccessService()
    if (await h5AccessService.validateToken(h5Token)) {
      return { valid: true }
    }
    return { valid: false, error: 'Invalid H5 access token' }
  }
```

> 注意 `src/bridge/remoteBridgeCore.ts` 是**另一种特性**——「Env-less Remote Control」云端桥（OAuth → `POST /v1/code/sessions` → `/bridge` → `worker_jwt` → SSE + CCRClient），**不是**本地 H5 扫码，勿混淆。

```ts
 *   1. POST /v1/code/sessions              (OAuth, no env_id)  → session.id
 *   2. POST /v1/code/sessions/{id}/bridge  (OAuth)             → {worker_jwt, expires_in, api_base_url, worker_epoch}
 *      Each /bridge call bumps epoch — it IS the register. No separate /worker/register.
 *   3. createV2ReplTransport(worker_jwt, worker_epoch)         → SSE + CCRClient
 *   4. createTokenRefreshScheduler                             → proactive /bridge re-call (new JWT + new epoch)
 *   5. 401 on SSE → rebuild transport with fresh /bridge credentials (same seq-num)
```

H5 远控的完整令牌 / 配对 / 网络策略 / keepalive / 权限桥协议见 [RemoteAccess](/docs/CS/AI/LLM/Agent/Product/CcHaha/RemoteAccess.md)。

## Scheduled Tasks

**定义**：向导 8 步，`ScheduledTaskWizard` 的 `steps` 数组按序为 Name / Description / Prompt / Model / Permission / Folder / Schedule / Confirm：

```ts
  const steps = [
    NameStep,
    TaskDescriptionStep,
    TaskPromptStep,
    TaskModelStep,
    PermissionStep,
    FolderStep,
    ScheduleStep,
    TaskConfirmStep,
  ]
```

**执行**：`src/hooks/useScheduledTasks.ts` 里 `onFire` 把 prompt 以 `'later'` 优先级入队，`createCronScheduler` 挂载一次、卸载时 stop；注释明言调度核心放在 `cronScheduler.ts` 以便 SDK / `-p` headless 共享：

```ts
    const enqueueForLead = (prompt: string) =>
      enqueuePendingNotification({
        value: prompt,
        mode: 'prompt',
        priority: 'later',
        isMeta: true,
        // Threaded through to cc_workload= in the billing-header
        // attribution block so the API can serve cron-initiated requests
        // at lower QoS when capacity is tight. No human is actively
        // waiting on this response.
        workload: WORKLOAD_CRON,
      })

    const scheduler = createCronScheduler({
      // Missed-task surfacing (onFire fallback). Teammate crons are always
      // session-only (durable:false) so they never appear in the missed list,
      // which is populated from disk at scheduler startup — this path only
      // handles team-lead durable crons.
      onFire: enqueueForLead,
```

```ts
 * REPL wrapper for the cron scheduler. Mounts the scheduler once and tears
 * it down on unmount. Fired prompts go into the command queue as 'later'
 * priority, which the REPL drains via useCommandQueue between turns.
 *
 * Scheduler core (timer, file watcher, fire logic) lives in cronScheduler.ts
 * so SDK/-p mode can share it — see print.ts for the headless wiring.
```

**Cron 方案**：自研 `fieldMatches` / `cronMatches` 在 `src/server/services/cronScheduler.ts`，5 字段 `minute hour day-of-month month day-of-week`，字段数不等于 5 直接返回 false（即拒绝 6 字段），支持 `*`、`,` 列表、`-` 区间、`*/n` 步进、`1-10/3` 区间步进；`date.getDay()` 使周日 = 0。完整引擎（两套独立调度器、jitter、持久化形态、headless 执行、跨会话锁、7 天自动过期）见 [ScheduledTasks](/docs/CS/AI/LLM/Agent/Product/CcHaha/ScheduledTasks.md)。

```ts
/**
 * Check whether a standard 5-field cron expression matches the given date.
 * Fields: minute hour day-of-month month day-of-week
 */
export function cronMatches(cronExpr: string, date: Date): boolean {
  const fields = cronExpr.trim().split(/\s+/)
  if (fields.length !== 5) return false

  const [minute, hour, dayOfMonth, month, dayOfWeek] = fields
  return (
    fieldMatches(minute, date.getMinutes()) &&
    fieldMatches(hour, date.getHours()) &&
    fieldMatches(dayOfMonth, date.getDate()) &&
    fieldMatches(month, date.getMonth() + 1) &&
    fieldMatches(dayOfWeek, date.getDay())
  )
}
```

```ts
export function fieldMatches(field: string, value: number): boolean {
  if (field === '*') return true

  // Comma-separated list — each element can be a range or step
  const parts = field.split(',')
  return parts.some((part) => singleFieldMatches(part.trim(), value))
}

function singleFieldMatches(part: string, value: number): boolean {
  // Step: */n or range/n
  if (part.includes('/')) {
    const [rangePart, stepStr] = part.split('/')
    const step = parseInt(stepStr, 10)
    if (isNaN(step) || step <= 0) return false

    if (rangePart === '*') {
      return value % step === 0
    }
    // range/step  e.g. 1-10/3
    if (rangePart.includes('-')) {
      const [startStr, endStr] = rangePart.split('-')
      const start = parseInt(startStr, 10)
      const end = parseInt(endStr, 10)
      if (value < start || value > end) return false
      return (value - start) % step === 0
    }
    // single/step  e.g. 5/2  — treat as start with step
    const start = parseInt(rangePart, 10)
    if (value < start) return false
    return (value - start) % step === 0
  }

  // Range: a-b
  if (part.includes('-')) {
    const [startStr, endStr] = part.split('-')
    const start = parseInt(startStr, 10)
    const end = parseInt(endStr, 10)
    return value >= start && value <= end
  }

  // Exact number
  return parseInt(part, 10) === value
}
```

任务是 **headless 执行**：调度器用 `Bun.spawn` 拉起独立 CLI 子进程，参数含 `--print` / `--output-format stream-json`，把 prompt 写进 stdin：

```ts
    const cliArgs = buildCronCliArgs([
      '--print',
      '--verbose',
      '--input-format',
      'stream-json',
      '--output-format',
      'stream-json',
      ...(sessionId ? ['--session-id', sessionId] : []),
      ...additionalDirectories.flatMap(directory => ['--add-dir', directory]),
      ...this.getRuntimeArgs(task),
    ])

    const taskTimeoutMs = resolveCronTaskTimeoutMs()
    const proc = Bun.spawn(
      cliArgs,
      buildCronTaskSpawnOptions(workDir, childEnv),
    )
```

## Desktop Pet

窗体宠物常驻桌面、跟随 agent 活动切换动作与气泡点评（[Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md) / [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md) 均无此能力）。内置 4 只，各带 spritesheet（DOM/CSS 渲染）、透明置顶点击穿透窗口；会话集成靠 2s 轮询全局聚合所有 session。完整渲染 / 窗口 / 会话集成 / 自定义宠物校验见 [Pets](/docs/CS/AI/LLM/Agent/Product/CcHaha/Pets.md)。`desktop/src/features/pets/builtinPets.ts` 中的 4 只定义：

```ts
export const BUILTIN_PETS = [
  {
    source: 'builtin',
    id: 'dada-code',
    displayName: '搭搭 Dada',
    description: '沉稳的协作机器人，陪你把想法一块块搭起来。',
    descriptionKey: 'settings.pets.builtin.dada',
    imageUrl: dadaImage,
    spriteVersionNumber: 2,
    spritesheetUrl: dadaSpritesheet,
    accent: '#4fd1b6',
  },
  {
    source: 'builtin',
    id: 'huhu-plan',
    displayName: '弧弧 Huhu',
    description: '拿着铅笔和计划本的路线机器人，复杂任务也能找到出口。',
    descriptionKey: 'settings.pets.builtin.huhu',
    imageUrl: huhuImage,
    spriteVersionNumber: 2,
    spritesheetUrl: huhuSpritesheet,
    accent: '#6ea8ff',
  },
  {
    source: 'builtin',
    id: 'bubu-fix',
    displayName: '补补 Bubu',
    description: '举着修补扳手的小机器人，最擅长发现并修好裂缝。',
    descriptionKey: 'settings.pets.builtin.bubu',
    imageUrl: bubuImage,
    spriteVersionNumber: 2,
    spritesheetUrl: bubuSpritesheet,
    accent: '#ff9a76',
  },
  {
    source: 'builtin',
    id: 'huihui-build',
    displayName: '回回 Huihui',
    description: '抱着构建齿轮的小机器人，新回复一到就精神满满。',
    descriptionKey: 'settings.pets.builtin.huihui',
    imageUrl: huihuiImage,
    spriteVersionNumber: 2,
    spritesheetUrl: huihuiSpritesheet,
    accent: '#9b8cff',
  },
] as const satisfies readonly BuiltinPet[]
```

## Usage Stats

内置用量统计，便于观察模型调用与成本分布。

## Corrections

- **旧描述**：H5 远控、IM 整合、计划任务「三者都依赖同一套 `adapters/common/ws-bridge.ts` 的 WebSocket 桥」。
  **源码事实**：v0.7.7 中 `adapters/common/ws-bridge.ts` 只服务 IM 适配器；H5 手机端连的是本地服务端 `/ws/*`（`src/server/index.ts` 的 upgrade 与 token 参数处理）；计划任务由 `src/hooks/useScheduledTasks.ts` 的 `createCronScheduler` 与 `src/server/services/cronScheduler.ts` 的 `Bun.spawn` headless CLI 执行，不经该桥。

- **旧描述**：`staticH5.ts` 把 `desktop/dist` 的 H5 页面与 `/assets/*` 提供给手机浏览器，手机扫码加载的是桌面 H5 页面。
  **源码事实**：v0.7.7 `src/server/staticH5.ts` 定义 `MOBILE_H5_BASE_PATH = '/m'`，服务 `mobile/` 的 Expo web 导出（构建到 `dist/m`），手机 / 平板浏览器进入的是与手机 App 同一套界面（见 release-notes/v0.7.7.md）；`desktop/dist` 仅是 `resolveH5DistDir()` 的候选目录之一，代码明确「桌面文档不能在 /m/ 下启动」并回退到 `/`。

```md
- **手机和平板浏览器直接用手机 App 界面**（#1749，#1757）：手机和平板浏览器打开电脑的 H5 地址后，进入的就是 cc-haha 手机 App 的同一套界面，只连接打开它的这台电脑；没有推送通知和锁屏活动，不能添加或切换其他电脑。
```

- **旧描述**（本页 Links 所链的家族 ComputerUse 分册）：Windows 的 Computer Use 走 Python Bridge，需要建 venv、装依赖。
  **源码事实**：v0.7.7 的 Windows / Linux Computer Use 改用随安装包提供的原生运行组件，不再需要安装 Python 或创建虚拟环境；Windows / Linux 不显示 macOS 权限卡，也不要求 Download Python / Install Environment。

```md
- **Computer Use**（#1789，#1759，#1832）：Windows 和 Linux 改用随安装包提供的原生运行组件，不再需要安装 Python 或创建虚拟环境，Linux 也可以使用；后台操作的范围见 Computer Use 文档。
```

```md
**One confirmation authorizes Computer Use for all supported apps on this computer; there is no separate approval for each app.** macOS system permissions, the global switch, and target-validity checks still apply. Windows and Linux do not show the macOS permission card or require **Download Python** or **Install Environment**.
```

## Links

- [CcHaha 主枢纽](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md)
- [ComputerUse](/docs/CS/AI/LLM/Agent/Product/CcHaha/ComputerUse.md)
- [MCP_Skills](/docs/CS/AI/LLM/Agent/Product/CcHaha/MCP_Skills.md)
- [AgentTeams](/docs/CS/AI/LLM/Agent/Product/CcHaha/AgentTeams.md)
- [RuntimeTopology](/docs/CS/AI/LLM/Agent/Product/CcHaha/RuntimeTopology.md)
- [StreamProtocol](/docs/CS/AI/LLM/Agent/Product/CcHaha/StreamProtocol.md)

## References

- [cc-haha GitHub](https://github.com/NanmiCoder/cc-haha)
- [adapters/README.md](https://github.com/NanmiCoder/cc-haha/blob/main/adapters/README.md)
- [h5AccessService.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/server/services/h5AccessService.ts)
