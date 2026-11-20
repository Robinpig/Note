> 版本基线：v1.19.5（`E:/Projects/opencode-1.19.5` release 源码快照）。本文聚焦 OpenCode 的 **C/S 边界**：Effect 原生 HTTP 栈、路由树、事件到客户端的 SSE 链路、per-request 实例加载、鉴权与多客户端接入。架构分层总览见 [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)。

## Introduction

OpenCode 把引擎做成常驻的本地 HTTP 服务，TUI / Web / IDE / Desktop / SDK 都只是客户端。这套 C/S 边界让它可远程 attach、无头运行、二次开发。v1.19.5 的 HTTP 层已经**彻底迁移到 Effect 原生栈**，不再是早期版本的 Hono。

几个反直觉点：

- **没有 Hono / Express**：整个 HTTP 栈是 `effect/unstable/httpapi`（`HttpApi`/`HttpApiBuilder`/`HttpApiEndpoint`）+ `HttpRouter`/`HttpServer` + `@effect/platform-node` 的 `NodeHttpServer`，全部以 Layer 组合装配。
- **`opencode serve` 声明 `instance: false`**：启动时**不加载任何项目实例**，实例由请求的 `x-opencode-directory` 头/`?directory=` 按请求懒加载；一个 server 进程承载多个项目目录。
- **TUI 默认根本不开 TCP 端口**：worker 用假 URL `http://opencode.internal` + RPC 代理的 `fetch` 直调 `Server.Default().app.fetch(request)`，"TUI 连 server"多数时候是同进程函数调用。
- **`server/projectors.ts` 是空壳**（全文仅 `export function initProjectors() {}`），真正的事件投影在 core 的 EventV2 事务里。

## Starting the Server

入口 `cli/cmd/serve.ts`：`instance: false` → `resolveNetworkOptions` → `Server.listen` → `Effect.never` 挂住进程。地址默认 `127.0.0.1`、端口默认 `0`，另有 `--mdns`/`--cors`；端口 0 的非常规逻辑是先试 4096、失败再回退随机端口：

```typescript
function startWithPortFallback(opts: ListenOptions) {
  if (opts.port !== 0) return startListener(opts, opts.port)
  // Match the legacy listener port-resolution behavior: explicit `0` prefers
  // 4096 first, then any free port.
  return startListener(opts, 4096).pipe(Effect.catch(() => startListener(opts, 0)))
}
```

监听层 `HttpRouter.serve(HttpApiApp.createRoutes(opts))`，注入 WebSocket tracker 与 Node HTTP server layer，并**为每个 listener 重装一份 ConfigProvider**——否则 Effect 的默认 ConfigProvider 会把首次读取的 `process.env` 快照缓存到模块单例，导致后续 `Server.listen()` 看不到新环境变量：

```typescript
function listenerLayer(opts: ListenOptions, port: number) {
  return HttpRouter.serve(HttpApiApp.createRoutes(opts), {
    middleware: disposeMiddleware, disableLogger: true, disableListenLog: true,
  }).pipe(
    Layer.provideMerge(AppNodeBuilder.build(WebSocketTracker.node)),
    Layer.provideMerge(serverLayer({ port, hostname: opts.hostname })),
    Layer.provide(ConfigProvider.layer(ConfigProvider.fromEnv())),
  )
}
```

底层用 `node:http` 的 `createServer()`，并 monkey-patch `server.close` 以支持 `listener.stop(true)` 强关活跃连接（优雅关闭超时 1 秒）。此外 `Server.Default()` 提供**不监听端口的内存版 app**（`fetch(request)`），TUI 默认模式直接用它；`Server.openapi()` 用 `OpenApi.fromApi(PublicApi)` 生成 OpenAPI 规范。

## The Route Tree

路由是 `HttpApi.make(...).addHttpApi(...)` 的树式组合。v1 实例路由 + v2 protocol 路由两套并存：

```typescript
export const RootHttpApi = HttpApi.make("opencode-root")
  .addHttpApi(ControlApi).addHttpApi(ControlPlaneApi).addHttpApi(GlobalApi)
  .middleware(SchemaErrorMiddleware).middleware(Authorization)

export const InstanceHttpApi = HttpApi.make("opencode-instance")
  .addHttpApi(ConfigApi).addHttpApi(ExperimentalApi).addHttpApi(FileApi)
  .addHttpApi(InstanceApi).addHttpApi(McpApi).addHttpApi(ProjectApi)
  .addHttpApi(ProjectCopyApi).addHttpApi(PtyApi).addHttpApi(QuestionApi)
  .addHttpApi(PermissionApi).addHttpApi(ProviderApi).addHttpApi(SessionApi)
  .addHttpApi(SyncApi).addHttpApi(TuiApi).addHttpApi(WorkspaceApi)
  .middleware(SchemaErrorMiddleware)
```

`groups/` 下有 20 个路由组（config / control / control-plane / event / experimental / file / global / instance / mcp / permission / project / project-copy / provider / pty / question / session / sync / tui / workspace 等），每组配套一个 `handlers/<同名>.ts`。v2 侧由 `packages/protocol/src/api.ts` 的 `makeApi({...})` 提供，含 health / location / agent / session / message / model / provider / integration / credential / permission / fs / command / skill / event / pty / question / reference / projectCopy 等组。

`createRoutes()` 最终合并 root / event / ptyConnect / instance / server / doc / ui 七类路由，铺上 compression、CORS、fence、error 中间件。注意 `groups/` 下**没有**独立的 tool.ts 或 plugin.ts——Tool 与 Plugin 以 Layer/Service 形式注入，不直接暴露 HTTP 端点。

## Per-Request Instance Loading

`InstanceStore` 以 `directory` 为 key 缓存 `Deferred`，同一目录的并发请求共享一次 boot：

```typescript
const load = (input: LoadInput): Effect.Effect<InstanceContext> => {
  const directory = FSUtil.resolve(input.directory)
  return Effect.uninterruptibleMask((restore) =>
    Effect.gen(function* () {
      const existing = cache.get(directory)
      if (existing) return yield* restore(Deferred.await(existing.deferred))
      const entry: Entry = { deferred: Deferred.makeUnsafe<InstanceContext>() }
      cache.set(directory, entry)
      yield* Effect.gen(function* () {
        yield* Effect.logInfo("creating instance", { directory })
        yield* completeLoad(directory, input, entry)
      }).pipe(Effect.forkIn(scope, { startImmediately: true }))
      return yield* restore(Deferred.await(entry.deferred))
    }),
  )
}
```

HTTP 中间件从路由上下文取目录（默认来源 `?directory=` → `x-opencode-directory` 头 → `process.cwd()`），`store.load` 后注入 `InstanceRef` 与 `WorkspaceRef`。`bootstrap.run` 在已注入的 per-instance 环境里触发初始化——注意它**不是构建 Layer**，而是先 `config.get()`（一切依赖它）、再 `plugin.init()`（插件可改配置，必须最先），然后并发 init LSP / Format / Vcs / Snapshot / Project。`InstanceRuntime.load` 只是 Promise/ALS 调用者的薄桥接层。销毁时 `GlobalBus.emit` 一个 `server.instance.disposed` 合成事件，被 SSE 流用作终止信号。

## The Event Pipeline to SSE

事件主干是 core 的 `EventV2`（详见 [Persistence](/docs/CS/AI/LLM/Agent/Product/OpenCode/Persistence.md)）。opencode 侧的 `EventV2Bridge` 做两件事：发布时自动附加当前实例的 `location`；监听所有 EventV2 事件转发到 `GlobalBus`，durable 事件额外发一条 `sync` 消息：

```typescript
const publish: EventV2.Interface["publish"] = (definition, data, options) =>
  Effect.gen(function* () {
    if (options?.location) return yield* events.publish(definition, data, options)
    const ctx = yield* InstanceRef
    if (!ctx) return yield* events.publish(definition, data, options)
    const workspaceID = yield* WorkspaceRef
    return yield* events.publish(definition, data, {
      ...options,
      location: new Location.Info({
        directory: AbsolutePath.make(ctx.directory),
        ...(workspaceID ? { workspaceID } : {}),
        project: { id: Project.ID.make(ctx.project.id), directory: AbsolutePath.make(ctx.worktree) },
      }),
    })
  })
```

SSE handler（`handlers/event.ts`）订阅 `EventV2Bridge.listen`，**监听器注册是 eager 的**（HTTP body fiber 启动期间的事件不会丢）：按 `directory`/`workspaceID` 过滤，混入 `server.instance.disposed` 与 10 秒心跳，最后 SSE 编码输出：

```typescript
const queue = yield* Queue.unbounded<EventV2.Payload>()
const unsubscribe = yield* events.listen((event) => Effect.sync(() => Queue.offerUnsafe(queue, event)))
yield* Effect.addFinalizer(() => unsubscribe)
const stream = Stream.fromQueue(queue).pipe(
  Stream.filter((event) =>
    event.location?.directory === instance.directory &&
    (event.location.workspaceID === undefined || event.location.workspaceID === workspaceID),
  ),
  Stream.map((event) => ({ id: event.id, type: event.type, properties: event.data })),
)
```

**一句话链路**：`EventV2.publish` → `notify`/PubSub → `EventV2Bridge.listen` → SSE handler 的 Queue → directory/workspace 过滤 → `Sse.encode()` → `GET /event`。`GlobalBus`（`opencode/src/bus/global.ts`，一个带 id 自动补全的 Node `EventEmitter`）只承担 `server.instance.disposed` 通知与 TUI 的 `global.event` RPC 两件事，**SSE 主体流并不订阅它**。

## Protocol, Codegen and Clients

`packages/protocol` 是权威 HTTP 契约（Effect `HttpApi` 声明 group/endpoint/Schema），但把 middleware key 作为参数注入以保持 Core 服务身份在下游。`httpapi-codegen` 构建期反射它，`emitPromise`/`emitEffect` 生成两套 client；Promise 版零 Effect、直接 fetch、无运行时校验，Effect 版保留 schema/转换；stream 生成 `Stream`/`AsyncIterable` 且**都不自动重连**：

```typescript
const contract = compile(ClientApi, { groupNames, endpointNames, omitEndpoints })
await Effect.runPromise(Effect.all([
  write(emitPromise(contract, { /* ... */ }), fileURLToPath(new URL("../src/generated", import.meta.url))),
  write(emitEffectImported(contract, { module: "../contract", api: "ClientApi" }),
        fileURLToPath(new URL("../src/generated-effect", import.meta.url))),
], { concurrency: 2, discard: true }).pipe(Effect.provide(NodeFileSystem.layer)))
```

网络版与嵌入式共用同一个 generated Effect client，仅 `HttpClient` transport 不同。改契约后 `bun run generate` 重新生成，不手写生成物（仓库 `AGENTS.md` 硬约束）。

多客户端接入：

| 形态 | 入口 | 连接方式 |
| :--- | :--- | :--- |
| TUI | `cli/cmd/tui.ts` + `cli/tui/worker.ts` | 默认 in-process：假 URL + `createWorkerFetch` RPC 直调 `Server.Default().app.fetch`；事件走 `GlobalBus → Rpc.emit("global.event")` |
| Web | `cli/cmd/web.ts` | `Server.listen()` + `openUrl()`；静态 UI 内嵌 `opencode-web-ui.gen.ts`，否则反代 `https://app.opencode.ai` |
| IDE（ACP） | `cli/cmd/acp.ts` | 双层：本机起 HTTP server + SDK 连它，再用 `AgentSideConnection` 把 opencode 包装成 ACP Agent，与 IDE 走 stdio NDJSON |
| Desktop | `packages/desktop/src/main/sidecar.ts` | Electron `utilityProcess.fork(sidecar.js)`，sidecar 内 `import("virtual:opencode-server")` 后 `Server.listen` |
| SDK | `packages/sdk-next/src/` | `createOpencodeClient({ baseUrl, headers: ServerAuth.headers() })` |

TUI 按是否显式传 `--port/--hostname/--mdns` 选择 transport：external 走真实 URL + HTTP header 鉴权，否则 `url: "http://opencode.internal"` 配 RPC fetch。ACP 的双层结构：

```typescript
const server = yield* Effect.promise(() => ACPProfile.measure("cli.acp.server.listen", () => Server.listen(opts)))
const sdk = createOpencodeClient({ baseUrl: `http://${server.hostname}:${server.port}`, headers: ServerAuth.headers() })
const stream = ndJsonStream(input, output)
const agent = ACP.init({ sdk })
new AgentSideConnection((conn) => agent.create(conn), stream)
```

## Authentication

鉴权是 HTTP Basic Auth，凭据来自环境变量（`server/auth.ts`）：`OPENCODE_SERVER_PASSWORD`（可选）+ `OPENCODE_SERVER_USERNAME`（默认 `opencode`）。未设密码时 `required()` 为 false，所有鉴权 middleware 直接放行（`serve.ts`/`web.ts` 打印 "server is unsecured" 警告）。凭据可从 `Authorization: Basic ...` 头或 `?auth_token=` 查询参数读取，校验失败返回 401 + `WWW-Authenticate: Basic realm="Secure Area"`。

三种 middleware 形态：`authorizationLayer`（Typed HttpApi middleware，包住 Root/Event/Instance/Server API）、`authorizationRouterMiddleware`（Router 级，用于 `/doc` 与 catch-all UI，允许公开静态资源绕过）、`ptyConnectAuthorizationLayer`（WebSocket 升级专用，带 ticket 放行：`?ptyTicket` 存在即跳过 Basic 校验）。其他防护：CORS allowlist（`maxAge: 86400`）、UI 响应 CSP 头与 `X-Content-Type-Options: nosniff`、跨 workspace 同步的 fence 层。

## Links

- [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md) / [Persistence](/docs/CS/AI/LLM/Agent/Product/OpenCode/Persistence.md) / [Plugin](/docs/CS/AI/LLM/Agent/Product/OpenCode/Plugin.md)
- [MCP](/docs/CS/AI/LLM/Agent/Product/OpenCode/MCP.md) / [TUI](/docs/CS/AI/LLM/Agent/Product/OpenCode/TUI.md) / [CLI](/docs/CS/AI/LLM/Agent/Product/OpenCode/CLI.md)

## References

1. [server/server.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/server/server.ts)
2. [server/routes/instance/httpapi/api.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/server/routes/instance/httpapi/api.ts)
3. [event-v2-bridge.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/event-v2-bridge.ts)
4. [project/instance-store.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/project/instance-store.ts)
5. [cli/cmd/acp.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/cli/cmd/acp.ts)
