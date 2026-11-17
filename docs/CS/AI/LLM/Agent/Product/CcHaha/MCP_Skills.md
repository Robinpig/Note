## Introduction

> 版本基线：v0.7.7（本地源码 E:/Projects/cc-haha-0.7.7）

cc-haha 把 MCP 与 Skills 这两套扩展机制都做成了**可视化 GUI 管理**，并额外提供了第三方 **Skill 市场**。底层协议与 [ClaudeCode/Extensions](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/Extensions.md)（Skills / Plugins / MCP / Output styles）同源，本页只讲 cc-haha 的 GUI 增量。本页所有论述均以 v0.7.7 本地源码为准，路径写在代码块外、不带行号，块内为原样连续摘取的真实源码片段。

## Visual MCP Manager

GUI 增删 MCP 服务器，传输与作用域来自 `desktop/src/types/mcp.ts` 与 `desktop/src/pages/McpSettings.tsx`。

**传输（transport）**：`stdio` | `http` | `sse`——对应营销所说的 STDIO / Streamable HTTP / SSE；http / sse 可选 `oauth`（`clientId` / `callbackPort`）：

```ts
export type McpEditableConfig =
  | {
      type: 'stdio'
      command: string
      args: string[]
      env: Record<string, string>
    }
  | {
      type: 'http' | 'sse'
      url: string
      headers: Record<string, string>
      headersHelper?: string
      oauth?: {
        clientId?: string
        callbackPort?: number
      }
    }
  | {
      type: string
    }
```

**可写作用域（McpWritableScope）**：`local` | `project` | `user`：

```ts
export type McpWritableScope = 'local' | 'project' | 'user'
```

**读取分组** `McpSettings` 的 `MCP_GROUP_ORDER` 还含 `plugin` / `managed` / `enterprise` / `claudeai` / `dynamic`；同一处也固定了可写作用域与 GUI 暴露的三种 transport：

```ts
type McpGroupKey =
  | 'plugin'
  | 'user'
  | 'project'
  | 'local'
  | 'managed'
  | 'enterprise'
  | 'claudeai'
  | 'dynamic'

const MCP_GROUP_ORDER: McpGroupKey[] = [
  'plugin',
  'user',
  'project',
  'local',
  'managed',
  'enterprise',
  'claudeai',
  'dynamic',
]

const WRITABLE_SCOPES: McpWritableScope[] = ['local', 'project', 'user']
const TRANSPORTS: TransportKind[] = ['stdio', 'http', 'sse']
```

可视化管理器经 `mcpApi.create / update / remove / toggle` 调用本地服务端 `/api/mcp/*`：

```ts
  create: (name: string, payload: McpUpsertPayload, cwd?: string) => {
    return api.post<{ server: McpServerRecord }>('/api/mcp', {
      name,
      ...payload,
      ...(cwd ? { cwd } : {}),
    })
  },

  update: (name: string, payload: McpUpsertPayload, cwd?: string, previousCwd?: string) => {
    return api.put<{ server: McpServerRecord }>(`/api/mcp/${encodeURIComponent(name)}`, {
      ...payload,
      ...(cwd ? { cwd } : {}),
      ...(previousCwd ? { previousCwd } : {}),
    })
  },

  remove: (name: string, scope: string, cwd?: string) => {
    const query = new URLSearchParams({ scope })
    if (cwd) query.set('cwd', cwd)
    return api.delete<{ ok: true }>(`/api/mcp/${encodeURIComponent(name)}?${query.toString()}`)
  },

  toggle: (name: string, cwd?: string, sessionId?: string) => {
    return api.post<McpToggleResult>(
      `/api/mcp/${encodeURIComponent(name)}/toggle`,
      {
        ...(cwd ? { cwd } : {}),
        ...(sessionId ? { sessionId } : {}),
      },
    )
  },
```

`desktop/src/stores/mcpStore.ts` 里 store 的动作签名与之对应（并且 v0.7.7 已多出 `saveProjectSharing`）：

```ts
type McpStore = {
  servers: McpServerRecord[]
  selectedServer: McpServerRecord | null
  isLoading: boolean
  error: string | null
  fetchServers: (projectPaths?: string[], fallbackCwd?: string) => Promise<void>
  fetchServersForKnownProjects: (currentWorkDir?: string) => Promise<void>
  createServer: (name: string, payload: McpUpsertPayload, cwd?: string) => Promise<McpServerRecord>
  updateServer: (server: McpServerRecord, payload: McpUpsertPayload, cwd?: string) => Promise<McpServerRecord>
  saveProjectSharing: (name: string, payload: McpProjectSharingPayload, currentWorkDir?: string) => Promise<McpProjectSharingResult>
  deleteServer: (server: McpServerRecord, cwd?: string) => Promise<void>
  toggleServer: (server: McpServerRecord, cwd?: string, sessionId?: string) => Promise<McpToggleResult>
  reconnectServer: (server: McpServerRecord, cwd?: string, sessionId?: string) => Promise<McpReconnectResult>
  refreshServerStatus: (server: McpServerRecord, cwd?: string) => Promise<McpServerRecord>
  selectServer: (server: McpServerRecord | null) => void
}
```

每条记录带 `configLocation` 字段：

```ts
export type McpServerRecord = {
  name: string
  scope: string
  transport: string
  enabled: boolean
  status: 'connected' | 'needs-auth' | 'failed' | 'disabled' | 'checking'
  statusLabel: string
  statusDetail?: string
  configLocation: string
  summary: string
  canEdit: boolean
  canRemove: boolean
  canReconnect: boolean
  canToggle: boolean
  config: McpEditableConfig
  projectPath?: string
  activeInCurrentContext?: boolean
}
```

配置持久化**继承 Claude Code 的位置约定**：project 写工作目录 `.mcp.json`、user 写全局 `getGlobalClaudeFile()`（user settings）、local 落在全局文件的 project 段、enterprise / claudeai 另有位置。`src/services/mcp/utils.ts`：

```ts
export function describeMcpConfigFilePath(scope: ConfigScope): string {
  switch (scope) {
    case 'user':
      return getGlobalClaudeFile()
    case 'project':
      return join(getCwd(), '.mcp.json')
    case 'local':
      return `${getGlobalClaudeFile()} [project: ${getCwd()}]`
    case 'dynamic':
      return 'Dynamically configured'
    case 'enterprise':
      return getEnterpriseMcpFilePath()
    case 'claudeai':
      return 'claude.ai'
    default:
      return scope
  }
```

## MCP Access: Consumer and Provider Sides

GUI 管理器的底层接入分两面（均区别于下节的 Skill 市场）。

### Consumer side: cc-haha connects to external MCP servers

- **模板工具 + 动态覆盖**：`src/tools/MCPTool/MCPTool.ts` 的 `MCPTool` 是 `isMcp: true` 的占位模板——默认 `name: 'mcp'`、`call()` 返回空数据、`checkPermissions` 返回 `passthrough`；真实 name / args / description / `call` 在 `mcpClient.ts` 按各 MCP server 动态覆盖（源码里逐字段标了 `Overridden in mcpClient.ts`）。

```ts
// Allow any input object since MCP tools define their own schemas
export const inputSchema = lazySchema(() => z.object({}).passthrough())
```

`inputSchema` 用 `z.object({}).passthrough()`——MCP 工具自带 schema，宿主不预设。

```ts
export const MCPTool = buildTool({
  isMcp: true,
  // Overridden in mcpClient.ts with the real MCP tool name + args
  isOpenWorld() {
    return false
  },
  // Overridden in mcpClient.ts
  name: 'mcp',
  maxResultSizeChars: 100_000,
  // Overridden in mcpClient.ts
  async description() {
    return DESCRIPTION
  },
  // Overridden in mcpClient.ts
  async prompt() {
    return PROMPT
  },
  get inputSchema(): InputSchema {
    return inputSchema()
  },
  get outputSchema(): OutputSchema {
    return outputSchema()
  },
  // Overridden in mcpClient.ts
  async call() {
    return {
      data: '',
    }
  },
  async checkPermissions(): Promise<PermissionResult> {
    return {
      behavior: 'passthrough',
      message: 'MCPTool requires permission.',
    }
  },
```

- **OAuth 伪工具**：未认证的 sse/http server 不暴露真实工具，而是用 `createMcpAuthTool` 注入一个**伪工具**（`mcp__<server>__authenticate`），模型调用它启动 `performMCPOAuthFlow`（`skipBrowserOpen: true`）拿到 authUrl 转交用户；OAuth 后台完成后 `reconnectMcpServerImpl` 用**前缀替换**（`mcp__<server>__*`）把真实工具 swap 进 `appState.mcp.tools`，伪工具随之自动移除。`src/tools/McpAuthTool/McpAuthTool.ts` 的注释把整条链路写得很清楚：

```ts
/**
 * Creates a pseudo-tool for an MCP server that is installed but not
 * authenticated. Surfaced in place of the server's real tools so the model
 * knows the server exists and can start the OAuth flow on the user's behalf.
 *
 * When called, starts performMCPOAuthFlow with skipBrowserOpen and returns
 * the authorization URL. The OAuth callback completes in the background;
 * once it fires, reconnectMcpServerImpl runs and the server's real tools
 * are swapped into appState.mcp.tools via the existing prefix-based
 * replacement (useManageMCPConnections.updateServer wipes anything matching
 * mcp__<server>__*, so this pseudo-tool is removed automatically).
 */
```

```ts
  return {
    name: buildMcpToolName(serverName, 'authenticate'),
    isMcp: true,
    mcpInfo: { serverName, toolName: 'authenticate' },
```

```ts
      const oauthPromise = performMCPOAuthFlow(
        serverName,
        sseOrHttpConfig,
        u => resolveAuthUrl?.(u),
        controller.signal,
        { skipBrowserOpen: true },
      )

      // Background continuation: once OAuth completes, reconnect and swap
      // the real tools into appState. Prefix-based replacement removes this
      // pseudo-tool since it shares the mcp__<server>__ prefix.
      void oauthPromise
        .then(async () => {
          clearMcpAuthCache()
          const result = await reconnectMcpServerImpl(serverName, config)
          const prefix = getMcpPrefix(serverName)
          setAppState(prev => ({
            ...prev,
            mcp: {
              ...prev.mcp,
              clients: prev.mcp.clients.map(c =>
                c.name === serverName ? result.client : c,
              ),
              tools: [
                ...reject(prev.mcp.tools, t => t.name?.startsWith(prefix)),
                ...result.tools,
              ],
              commands: [
                ...reject(prev.mcp.commands, c => c.name?.startsWith(prefix)),
                ...result.commands,
              ],
              resources: result.resources
                ? { ...prev.mcp.resources, [serverName]: result.resources }
                : prev.mcp.resources,
            },
          }))
```

- **transport 支持**：`stdio` | `http` | `sse` | `claudeai-proxy`（GUI 层由 `McpSettings` 暴露，见上节）。伪工具的 `call()` 明确把 `claudeai-proxy` 与 stdio 挡在此流之外：前者走 `/mcp` 的独立认证，后者无 OAuth；只有 `sse` / `http` 才继续。

```ts
    async call(_input, context) {
      // claude.ai connectors use a separate auth flow (handleClaudeAIAuth in
      // MCPRemoteServerMenu) that we don't invoke programmatically here —
      // just point the user at /mcp.
      if (config.type === 'claudeai-proxy') {
        return {
          data: {
            status: 'unsupported' as const,
            message: `This is a claude.ai MCP connector. Ask the user to run /mcp and select "${serverName}" to authenticate.`,
          },
        }
      }

      // performMCPOAuthFlow only accepts sse/http. needs-auth state is only
      // set on HTTP 401 (UnauthorizedError) so other transports shouldn't
      // reach here, but be defensive.
      if (config.type !== 'sse' && config.type !== 'http') {
        return {
          data: {
            status: 'unsupported' as const,
            message: `Server "${serverName}" uses ${transport} transport which does not support OAuth from this tool. Ask the user to run /mcp and authenticate manually.`,
          },
        }
      }
```

### Provider side: Computer Use as an MCP server

- `src/utils/computerUse/mcpServer.ts` 把 **Computer Use 能力包成 MCP server** 供外部 client（Cowork / claude-swift）调用，对应 `--computer-use-mcp` 子进程入口（`runComputerUseMcpServer`）：stdio transport、stdin close 退出、退出前 flush analytics。

```ts
/**
 * Subprocess entrypoint for `--computer-use-mcp`. Mirror of
 * `runClaudeInChromeMcpServer` — stdio transport, exit on stdin close,
 * flush analytics before exit.
 */
export async function runComputerUseMcpServer(): Promise<void> {
  enableConfigs()
  initializeAnalyticsSink()

  const server = await createComputerUseMcpServerForCli()
  const transport = new StdioServerTransport()

  let exiting = false
  const shutdownAndExit = async (): Promise<void> => {
    if (exiting) return
    exiting = true
    await Promise.all([shutdown1PEventLogging(), shutdownDatadog()])
    // eslint-disable-next-line custom-rules/no-process-exit
    process.exit(0)
  }
  process.stdin.on('end', () => void shutdownAndExit())
  process.stdin.on('error', () => void shutdownAndExit())

  logForDebugging('[Computer Use MCP] Starting MCP server')
  await server.connect(transport)
  logForDebugging('[Computer Use MCP] MCP server started')
}
```

- `createComputerUseMcpServerForCli` 委托 `vendor/computer-use-mcp` 的 `createComputerUseMcpServer`，并**替换 ListTools handler** 把已安装 app 名塞进平台特定 tool description；真实 dispatch 仍走 `wrapper.tsx` 的 `.call()` override——这个 server 只答 ListTools。

```ts
/**
 * Construct the in-process server. Delegates to the package's
 * `createComputerUseMcpServer` for the Server object + stub CallTool handler,
 * then REPLACES the ListTools handler with one that includes installed-app
 * names in platform-specific tool descriptions (the package's factory doesn't
 * take `installedAppNames`, and Cowork builds its own tool array in
 * serverDef.ts for the same reason).
 *
 * Async so the 1s app-enumeration timeout doesn't block startup — called from
 * an `await import()` in `client.ts` on first CU connection, not `main.tsx`.
 *
 * Real dispatch still goes through `wrapper.tsx`'s `.call()` override; this
 * server exists only to answer ListTools.
 */
export async function createComputerUseMcpServerForCli(): Promise<
  ReturnType<typeof createComputerUseMcpServer>
> {
  const adapter = getComputerUseHostAdapter()
  const coordinateMode = getChicagoCoordinateMode()
  const server = createComputerUseMcpServer(adapter, coordinateMode)

  const installedAppNames = adapter.executor.capabilities.agentDesktop
    ? undefined : await tryGetInstalledAppNames()
  const tools = buildPlatformComputerUseTools(
    adapter.executor.capabilities,
    coordinateMode,
    installedAppNames,
  )
  server.setRequestHandler(ListToolsRequestSchema, async () =>
    adapter.isDisabled() ? { tools: [] } : { tools },
  )

  return server
}
```

- 这是 cc-haha 把自家能力「反向」开放为 MCP 的示例，与消费侧形成闭环。

## Visual SubAgent Manager

GUI 创建与调优 SubAgent：配置模型、工具、权限模式——把原本要写配置的 subagent 定义变成表单操作。

## Skill Marketplace

由本地服务端 `/api/market/*` 后端聚合外部注册源，`desktop/src/api/market.ts` 提供 list / detail / fileContent / install / uninstall / status 六个方法（列表带 `scope` / `source` / `security` / `installed` 等过滤参数）：

```ts
export const marketApi = {
  list: (params: MarketListParams = {}) => {
    const search = new URLSearchParams()
    if (params.scope) search.set('scope', params.scope)
    if (params.category && params.category !== 'all') search.set('category', params.category)
    if (params.q) search.set('q', params.q)
    if (params.source && params.source !== 'all') search.set('source', params.source)
    if (params.security && params.security !== 'all') search.set('security', params.security)
    if (params.installed && params.installed !== 'all') search.set('installed', params.installed)
    if (params.cursor) search.set('cursor', params.cursor)
    if (params.limit) search.set('limit', String(params.limit))
    const query = search.toString()
    return api.get<MarketListResponse>(`/api/market/skills${query ? `?${query}` : ''}`, { timeout: 30_000 })
  },

  /**
   * `owner` pins a ClawHub read to one publisher: ClawHub slugs are not unique,
   * so the slug alone can resolve to a different skill than the card showed.
   */
  detail: (source: MarketSource, slug: string, options: { owner?: string } = {}) =>
    api.get<{ skill: NormalizedSkillDetail; sourceStatus: SourceStatusInfo }>(
      `/api/market/skills/${source}/${encodeURIComponent(slug)}${
        options.owner ? `?owner=${encodeURIComponent(options.owner)}` : ''
      }`,
      { timeout: 30_000 },
    ),

  fileContent: (source: MarketSource, slug: string, path: string, owner?: string) =>
    api.get<{ file: MarketFileContent }>(
      `/api/market/skills/${source}/${encodeURIComponent(slug)}/file?path=${encodeURIComponent(path)}${
        owner ? `&owner=${encodeURIComponent(owner)}` : ''
      }`,
      { timeout: 30_000 },
    ),

  install: (id: string, owner?: string) =>
    api.post<{ ok: boolean; installedPath: string; skill: NormalizedSkill }>(
      '/api/market/install',
      owner ? { id, owner } : { id },
      { timeout: 120_000 },
    ),

  uninstall: (id: string) =>
    api.post<{ ok: boolean; removedPath: string; skill: NormalizedSkill | null }>(
      '/api/market/uninstall',
      { id },
      { timeout: 30_000 },
    ),

  status: () =>
    api.get<{ sources: Record<MarketSource, SourceStatusInfo> }>('/api/market/status'),
}
```

- **注册源（双源聚合）**：`ClawHub` 与 `SkillHub` 均已在服务端代码确认真实存在——`src/server/services/market/` 下 `clawhubProvider.ts` 与 `skillhubProvider.ts` 实现同一 `MarketProvider` 接口，由 `marketService.ts` 聚合；二者通过 `source` 字段区分。

```ts
const providers: Record<MarketSource, MarketProvider> = {
  clawhub: clawhubProvider,
  skillhub: skillhubProvider,
}
```

```ts
/**
 * Skills Market — shared types for the market aggregation layer.
 *
 * Upstream sources:
 *  - ClawHub  (https://clawhub.ai)      — cursor pagination, no security audits
 *  - SkillHub (https://api.skillhub.cn) — page/pageSize pagination, security reports
 */

export type MarketSource = 'clawhub' | 'skillhub'

export const MARKET_SOURCES: MarketSource[] = ['clawhub', 'skillhub']

export type SecurityStatus = 'verified' | 'benign' | 'unknown' | 'flagged'
```

```ts
export function skillId(source: MarketSource, slug: string): string {
  return `${source}:${slug}`
}
```

`SkillHub` 后端为 `https://api.skillhub.cn`，提供 `GET /api/skills`（list）、`/api/v1/skills/{slug}`（detail）、`/files`、`/file`（302 跳腾讯云 COS）四接口；分页参数必须用 `pageSize`、搜索必须用 `keyword`（`limit` / `q` 会被忽略）：

```ts
/**
 * SkillHub provider (https://api.skillhub.cn)
 *
 * Endpoints (verified against the live API):
 *  - GET /api/skills?page=&pageSize=&keyword=      → {code, data:{skills[], total}, message}
 *      NOTE: pagination param MUST be `pageSize` (a `limit` param is silently ignored)
 *      NOTE: search param MUST be `keyword` (a `q` param is silently ignored)
 *  - GET /api/v1/skills/{slug}                     → {skill, owner, latestVersion, securityReports}
 *  - GET /api/v1/skills/{slug}/files               → {count, files:[{path, sha256, size}]}
 *  - GET /api/v1/skills/{slug}/file?path=          → 302 redirect to Tencent COS (follow)
 */
```

```ts
async function fetchPage(params: { keyword?: string; page: number; pageSize: number }): Promise<ProviderListPage> {
  const base = getProviderBase('skillhub')
  const url = new URL('/api/skills', base)
  url.searchParams.set('page', String(params.page))
  url.searchParams.set('pageSize', String(params.pageSize))
  if (params.keyword) url.searchParams.set('keyword', params.keyword)

  const envelope = await providerFetchJson<SkillhubEnvelope<{ skills?: SkillhubListItem[]; total?: number }>>(
    'skillhub',
    url.toString(),
  )
  if (envelope.code !== 0 || !Array.isArray(envelope.data?.skills)) {
    throw new MarketUpstreamError(
      'skillhub',
      MARKET_ERROR_CODES.upstreamBadResponse,
      `skillhub responded code=${envelope.code}: ${envelope.message || 'bad payload'}`,
    )
  }
  const items = envelope.data.skills.filter((s) => s?.slug).map(normalizeListItem)
  const total = envelope.data.total ?? 0
  const hasMore = params.page * params.pageSize < total
  return {
    items,
    nextCursor: hasMore ? String(params.page + 1) : undefined,
    total,
  }
}

export const skillhubProvider: MarketProvider = {
  source: 'skillhub',

  async list({ cursor, limit }): Promise<ProviderListPage> {
    const page = cursor ? Math.max(1, Number.parseInt(cursor, 10) || 1) : 1
    return fetchPage({ page, pageSize: limit })
  },

  async search({ q, cursor, limit }): Promise<ProviderListPage> {
    const page = cursor ? Math.max(1, Number.parseInt(cursor, 10) || 1) : 1
    return fetchPage({ keyword: q, page, pageSize: limit })
  },
```

```ts
const DEFAULT_BASES: Record<MarketSource, string> = {
  clawhub: 'https://clawhub.ai',
  skillhub: 'https://api.skillhub.cn',
}
```

- **两种 scope**：`catalog`（随包策展快照，无网络）与 `market`（实时跨两个上游注册源查）；`MarketHome` 用 `scope === 'catalog'` 判定，`marketService.ts` 的注释也以 `market` 称呼它。

```ts
/**
 * `catalog`: the curated snapshot shipped with the app (no network).
 * `market`: live list/search across both upstream registries.
 */
export type MarketScope = 'catalog' | 'market'
```

```ts
  const catalog = scope === 'catalog'
```

```ts
 * The default `catalog` scope pages through the curated snapshot shipped with
 * the app (no network). The `market` scope merges the two upstream providers
 * into a single paginated feed with cross-source dedupe, per-source
 * health/degradation reporting, TTL caching (stale-while-error), and
 * locally-computed install state.
```

- **安装前安全报告**：详情接口返回 `skill` + `sourceStatus`；`SecurityReportPanel` 在安装前渲染能力清单 + 各扫描器报告（`vendor` / `status` / `statusText` / `reportUrl` / `summary`）+ 策展者 `securityNote`。

```ts
/**
 * The security tab: what the skill will do (rule-based, from its own files),
 * then each upstream scanner's verdict with its own explanation, then — for a
 * curated skill shipped despite a flag — the curator's reason.
 *
 * Report links come from upstream, so only absolute http(s) URLs become an
 * `href`; anything else is dropped rather than rendered as a dead or hostile link.
 */
export function SecurityReportPanel({
  capabilities,
  reports,
  securityNote,
}: {
  capabilities: readonly Capability[]
  reports: readonly SecurityReport[]
  securityNote?: string
}) {
  const t = useTranslation()

  return (
    <div className="flex flex-col gap-4" data-testid="market-security-panel">
      <CapabilityPanel capabilities={capabilities} />
```

```ts
      <Card radius="lg" surface="lowest" padding="none" className="overflow-hidden">
        <h2 className="flex h-10 items-center border-b border-[var(--color-border)] px-4 text-[13px] font-medium text-[var(--color-text-primary)]">{t('market.detail.scanReports')}</h2>
        {reports.length > 0 ? (
          <ul className="divide-y divide-[var(--color-border)]">
            {reports.map((report) => {
              const url = safeUrl(report.reportUrl)
              return (
                <li
                  key={`${report.vendor}:${report.status}`}
                  data-testid="market-security-report"
```

`SkillHub` 的 `securityReports` 被归一为 `benign` / `safe` / `clean` 或 `flagged`（其余状态 / 无报告归 `unknown` / `verified`）；列表支持 `security` 过滤（见上方 `marketApi.list`）。

```ts
const BENIGN_STATUSES = new Set(['benign', 'safe', 'clean'])

function mapSecurity(
  reports: SkillhubSecurityReports | undefined,
  verified: boolean | undefined,
): { status: SecurityStatus; reports: SecurityReport[] } {
  const normalized: SecurityReport[] = []
  for (const [vendor, report] of Object.entries(reports ?? {})) {
    if (!report?.status) continue
    normalized.push({
      vendor,
      status: report.status,
      statusText: report.statusText || report.status,
      reportUrl: report.reportUrl,
    })
  }
  if (normalized.length === 0) return { status: 'unknown', reports: normalized }
  const anyFlagged = normalized.some((r) => !BENIGN_STATUSES.has(r.status.toLowerCase()))
  if (anyFlagged) return { status: 'flagged', reports: normalized }
  return { status: verified ? 'verified' : 'benign', reports: normalized }
}
```

在装上未知 skill 前先暴露风险，比纯命令行安装多一层可见性。

## Corrections

- **旧描述**：可写作用域只有 `local | project | user`、project 写单个项目 `.mcp.json`，并把「共享」归到 user 作用域。
  **源码事实**：v0.7.7 新增「MCP 共享到多个项目」——`desktop/src/types/mcp.ts` 定义 `McpProjectSharingPayload`（`targets` 为 `{ projectPath, selected, expectedRevision }` 数组）与 `McpProjectSharingSnapshot` / `McpProjectSharingResult`；`desktop/src/api/mcp.ts` 新增 `projectSharing` / `saveProjectSharing`（`PUT /api/mcp/:name/projects`）；`McpSettings.tsx` 在 project scope 下用 `usesProjectSharing` 启用多选目标项目，保存后才生效，取消勾选只移除该项目 `.mcp.json` 里的这一项。

```ts
export type McpProjectSharingSnapshot = {
  projects: McpProjectSnapshot[]
  config?: McpEditableConfig
  sourceConfig?: Record<string, unknown>
}

export type McpProjectSharingPayload = {
  config: McpEditableConfig
  sourceCwd?: string
  sourceConfig?: Record<string, unknown>
  targets: Array<{ projectPath: string; selected: boolean; expectedRevision: string | null }>
}

export type McpProjectSharingResult = {
  results: Array<{
    projectPath: string
    selected: boolean
    success: boolean
    persisted?: boolean
    revision?: string | null
    configHash?: string | null
    error?: string
  }>
}
```

```ts
  projectSharing: (name: string, projectPaths: string[], sourceCwd?: string, configHashes?: string[]) => {
    const query = new URLSearchParams()
    for (const path of projectPaths) query.append('projectPath', path)
    if (sourceCwd) query.set('sourceCwd', sourceCwd)
    for (const hash of configHashes ?? []) query.append('configHash', hash)
    return api.get<McpProjectSharingSnapshot>(`/api/mcp/${encodeURIComponent(name)}/projects?${query}`)
  },

  saveProjectSharing: (name: string, payload: McpProjectSharingPayload) => {
    return api.put<McpProjectSharingResult>(`/api/mcp/${encodeURIComponent(name)}/projects`, payload)
  },
```

```ts
  const sharedSource = view.type === 'edit' && view.server.scope === 'project' ? view.server : undefined
  const usesProjectSharing = draft.scope === 'project' && (view.type === 'create' || !!sharedSource)
  const projectSharing = useMcpProjectSharing({
```

```md
- **MCP 共享到多个项目**（#1769）：在 MCP 设置里可以多选目标项目，把同一个 MCP 配置共享出去，保存后才会生效；取消勾选只会移除该项目 `.mcp.json` 里的这一项。
```

- **旧描述**（家族 ComputerUse 分册，本页 Provider side 相关）：Windows / Linux 的 Computer Use 依赖 Python Bridge，需要建 venv、装依赖；只有 macOS 走原生守护进程。
  **源码事实**：v0.7.7 的 Windows / Linux Computer Use 改用随安装包提供的原生运行组件，不再需要安装 Python 或创建虚拟环境，Linux 也可使用；本页 `runComputerUseMcpServer` / `createComputerUseMcpServerForCli` 源码仍在，但底层 host adapter 已切到原生组件，旧 Python 假设不再成立。

```md
- **Computer Use**（#1789，#1759，#1832）：Windows 和 Linux 改用随安装包提供的原生运行组件，不再需要安装 Python 或创建虚拟环境，Linux 也可以使用；后台操作的范围见 Computer Use 文档。
```

```md
Computer Use lets Claude read interface elements, take screenshots, click, and type in native notes, file managers, system settings, and other desktop apps. macOS, Windows, and Linux use native runtime components; no Python installation or virtual environment is required.
```

- **旧描述**：市场两种 scope 是 `catalog`（策展快照）与 `live`（实时）。
  **源码事实**：v0.7.7 `desktop/src/types/market.ts` 定义 `MarketScope = 'catalog' | 'market'`，`market` 才是「实时跨两个上游注册源」的取值，`live` 只是语义描述、不是合法 scope 值；`MarketHome.tsx` 用 `scope === 'catalog'` 判定，服务端 `marketService.ts` 同样以 `market` 称呼该 scope。

## Links

- [CcHaha 主枢纽](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md)
- [Models](/docs/CS/AI/LLM/Agent/Product/CcHaha/Models.md)
- [Tools](/docs/CS/AI/LLM/Agent/Product/CcHaha/Tools.md)
- [PermissionEngine](/docs/CS/AI/LLM/Agent/Product/CcHaha/PermissionEngine.md)

## References

- [cc-haha GitHub](https://github.com/NanmiCoder/cc-haha)
- [mcp.ts 类型](https://github.com/NanmiCoder/cc-haha/blob/main/desktop/src/types/mcp.ts)
- [market.ts](https://github.com/NanmiCoder/cc-haha/blob/main/desktop/src/api/market.ts)
- [MCPTool.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/MCPTool/MCPTool.ts)
- [McpAuthTool.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/tools/McpAuthTool/McpAuthTool.ts)
- [computerUse mcpServer.ts](https://github.com/NanmiCoder/cc-haha/blob/main/src/utils/computerUse/mcpServer.ts)
