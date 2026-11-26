## Introduction

DSH 的 Web、headless、SDK、ACP、Desktop 不是五套程序，而是**同一个 `dsh` launcher + 同一套 Cordis/Loader，叠加不同 profile patch** 得到的表示层。前端是薄壳：它把外部协议翻译成对同一棵插件树上 `ctx.agents` / `ctx.llm` / `ctx.sessions` 的调用，自己不含 agent 逻辑。

> 版本基线：v0.2.2-rc.3（`E:/Projects/deepseek-harness-dsh-v0.2.2-rc.3`）。

几个反直觉的点：

- **browser client 里根本没有 `ctx.agents`**：`create/steer/followup` 全在 host 侧 `api/session-controller`；前端只发 typed remote 调用 + 消费事件流。
- **`sdk-minimal` 不叠 `dsh-base`**：它是唯一的单 bundle profile，自带一整棵显式最小树，不是"更薄的 sdk"。
- **Python SDK 走的就是 Node 版 dsh CLI**：没有独立运行器或解析器，`runtime-bootstrap.mjs` 直接 import `runCli`，客户端只是多传 `--profile sdk`。

## Profile Selection and Bundle Composition

`dsh <name>` 是 `--profile <name>` 的语法糖（`plugin` 是保留名）；CLI 解析后按 mode 分发到 `runProfile`（`apps/cli/src/args.ts`、`apps/cli/src/bin.ts`）：

```ts
    const expanded = first !== undefined && !first.startsWith('-') && first !== 'plugin'
      ? ['--profile', ...argv]
      : argv
    program.parse(expanded, { from: 'user' })
```

```ts
  switch (invocation.mode) {
    case 'profile': {
      const { runProfile } = await import('./profile-boot.ts')
```

内置 profile 是一张 bundle 组合表（`packages/util/official-bundles/src/bundles.ts`）：

```ts
export const PROFILE_TEMPLATES: Record<string, ProfileTemplate> = {
  acp: { bundles: ['@deepseek-ai/dsh-base', '@deepseek-ai/dsh-acp-app'] },
  web: { bundles: ['@deepseek-ai/dsh-base', '@deepseek-ai/dsh-web-app'] },
  headless: { bundles: ['@deepseek-ai/dsh-base', '@deepseek-ai/dsh-headless'] },
  sdk: { bundles: ['@deepseek-ai/dsh-base', '@deepseek-ai/dsh-sdk-app'] },
  'sdk-minimal': { bundles: ['@deepseek-ai/dsh-sdk-minimal'] },
}
```

`dsh-base` 是 web/headless/sdk/acp 共享的第一层（模型适配器、工具、持久化、沙箱与审批策略、设置、凭证、遥测）；`sdk-minimal` 是刻意例外。层叠加顺序（`packages/boot/app-boot/src/profile-context.ts`）：

```ts
  const patches = structuredClone([
    ...readBundlePatches(binName, context, initialProfile),
    ...(initialProfile?.patches ?? loadOptionalPatches(binName, context.patchPath) ?? []),
    ...(loadOptionalPatches(binName, join(context.home, PROFILE_PATCH_FILENAME)) ?? []),
    ...context.overlays,
  ])
```

patch 按 id 整块替换（`target[key] = value`），不做深合并。HMR 用三层开关控制：base 默认启用（仅配置重载），headless/sdk/acp 显式 `disabled: true`，web 另挂 `client-hmr`；是否挂 HMR 还决定插件安装能否即时生效（`plugin-manager.reload` 有 HMR 才走 `hmr.reconcileProfile`，否则重启时重组合）。

boot 驱动 Loader 挂载根 `cordis:include` 并等整棵树 settle 后审计激活（`packages/boot/app-boot/src/index.ts`）：

```ts
    await ctx.plugin(Loader)
    await prepare?.(ctx)
    stage = 'plugin tree failed to load'
    await mountRootInclude(ctx, absoluteConfigPath, patches, bareModuleBaseUrl, binName)
    await ctx.get('loader')?.await()
    if (ctx.get('loader') === undefined) return ctx
    await auditStartupEntries(ctx, binName)
```

## Web: Remote Events and Session Follow

host 侧把 Cordis 事件（含 `api-session/*`）压入一个队列，通过 typert-gateway 的 `$events` 流推给 browser（`packages/api/remotes/src/index.ts`、`packages/api/gateway/src/index.ts`）：

```ts
  private async *openRemoteEvents(payload, signal, peer) {
    // ... validate empty args, resolve remoteEvents registration
    const client: RemoteEventClient = { peer, id: clientId, queue: new RemoteEventQueue(), signal: lifetime, ... }
    this.remoteEventClients.set(clientId, client)
    try {
      yield { ...REMOTE_EVENT_STREAM_READY, clientId, host: registration.host }
      yield* client.queue.iterate(lifetime)
    } finally {
      this.removeRemoteEventClient(client)
    }
  }
```

前端可见事件是显式白名单（`packages/api/remotes/src/remote-events.ts`），每项声明分派模式与资源访问——这是"前端只读"的类型层保证：

```ts
export const API_REMOTE_FORWARDED_EVENTS = [
  { event: 'agent-preset/selected', mode: 'emit' },
  { event: 'approval/request', mode: 'waterfall' },
  { event: 'api-session/activity', mode: 'emit', resources: { session: (sessionId): SessionId => sessionId } },
  // ...
] as const satisfies readonly TypertForwardableEventEntry[]
```

client 侧 `pumpEvents` 只读帧 → 在本地 Cordis 上 `parallel`/`waterfall` 派发，没有 agent 实例、没有 prompt 组装（`packages/api/gateway/src/client/remote-events.ts`）。真正的控制在 host 侧 session-controller：

```ts
        if (request.mode === 'steer') agent.steer(message)
        else agent.followup(message)
```

durable log 与 live 帧接成一条 seq 轴（`packages/api/session-controller/src/client/transport.ts`）：`SessionEventStream.follow()` 先收 `snapshot`（durable 基线）、再收 `entry`（durable 追加）与 `assistant-stream`（client-only 瞬时帧，走 notification、**不推进 durable cursor**）；`follows: (l,r) => r === l + 1` 强制 seq 连续，断流由 `RemoteJournalStream.readPage` 补洞。

WebSocket upgrade 的注册要等 `appReady`——重启中的 Host 不接受流（`packages/api/gateway/src/index.ts`）。

## SDK and ACP: stdio Presentation Adapters

SDK server 把 stdin 接进 JSON-RPC transport，`initialize` 是 readiness 边界——等到整棵 Loader 树稳定才宣告就绪（`packages/sdk/server/src/index.ts`）：

```ts
    if (method === 'initialize') {
      await ctx.get('loader')?.await()
    }
    const result = await server.handleRequest(method, params)
    if (method === 'shutdown') {
      setImmediate(() => { void disposeAndExit() })
    }
```

`session/event` → `session.event` 通知就是 SDK 的 session follow（`packages/sdk/server/src/server.ts`）：

```ts
    this.disposers.push(ctx.on('session/event', (session, event) => {
      const payload: SessionEventNotification = { sessionId: String(session.id), event }
      this.transport.notify('session.event', payload)
    }))
```

ACP server 用 `AgentSideConnection` 注册标准 ACP v1 方法，走 stdio NDJSON（`packages/acp/acp/src/index.ts`）：

```ts
  const app = createAcpAgentApp({ name: 'deepseek-harness-acp' })
    .onRequest(methods.agent.initialize, ({ params }) => implementation.initialize(params))
    .onRequest(methods.agent.session.new, ({ params, signal }) => implementation.newSession(params, signal))
    .onRequest(methods.agent.session.prompt, ({ params, signal }) => implementation.prompt(params, signal))
    .onNotification(methods.agent.session.cancel, ({ params }) => implementation.cancel(params))
```

stdout 是协议信道，不是日志——任何 stdout logger 都会破坏 JSON-RPC/NDJSON 帧。

## Desktop: Electron Host Running a Web Profile

Electron 主进程 spawn `dsh-desktop-host/lib/index.js`，host 用 `runProfile({ profile: 'desktop' })` 拉起的**仍是 web-app 那棵插件图**（`apps/desktop/src/host-process.ts`、`apps/desktop-host/src/index.ts`）：

```ts
  const application = runProfile({
    environment: loadLayeredEnv('dsh'),
    profile: 'desktop',
    resolvedProfile: { profile, installAnchor },
    patchFiles: [],
    args: ['--no-open', '--host', '127.0.0.1', '--port', '0'],
  })
```

ready 后把认证 URL 与 boot injections 通过 IPC 回传 Electron；浏览器加载的还是同一个 SPA 入口 `AppWebEntry`，Desktop 只是多一道 boot gate（`apps/web/src/main.ts`）。CLI 的 `rejectElectronProfile` 显式拒绝 `dsh --profile desktop`——管理 desktop 插件要走 Electron 内置 CLI 转发。

## Links

- [DSH 主入口](/docs/CS/AI/LLM/Agent/Product/DSH/DSH.md)
- [DSH Cordis 微内核](/docs/CS/AI/LLM/Agent/Product/DSH/Cordis.md)
- [DSH Session & Persistence](/docs/CS/AI/LLM/Agent/Product/DSH/SessionPersistence.md)
- [DSH Agent Loop](/docs/CS/AI/LLM/Agent/Product/DSH/AgentLoop.md)
- [Agent Client Protocol](/docs/CS/AI/LLM/Protocol/MCP.md)

## References

1. [deepseek-ai/deepseek-harness（v0.2.2-rc.3）apps/cli](https://github.com/deepseek-ai/deepseek-harness/tree/v0.2.2-rc.3/apps/cli)
2. [架构文档 — Profiles and bundles / Application launch / Desktop](https://github.com/deepseek-ai/deepseek-harness/blob/v0.2.2-rc.3/docs/architecture.md)
3. [packages/boot/app-boot](https://github.com/deepseek-ai/deepseek-harness/tree/v0.2.2-rc.3/packages/boot/app-boot)
