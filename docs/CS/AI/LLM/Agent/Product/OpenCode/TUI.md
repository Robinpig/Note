> 版本基线：v1.19.5（`E:/Projects/opencode-1.19.5` release 源码快照）。本文基于 `packages/tui/`（OpenTUI + SolidJS）与 `packages/opencode/src/cli/tui/`、`cli/cmd/tui.ts`。TUI 与 server 的关系（in-process RPC vs 真实网络）见 [Server](/docs/CS/AI/LLM/Agent/Product/OpenCode/Server.md)。

## Introduction

TUI 是 OpenCode 的主客户端。它用 **OpenTUI（`@opentui/*`）+ SolidJS 响应式**构建，跑在一个 Worker 线程里，通过一个基于 `postMessage` 的 JSON RPC 协议与 server 通信。界面行为由一份独立的 `tui.json` / `tui.jsonc` 控制——与运行时配置 `opencode.json` 解耦。最大的认知要点是：**默认模式下 TUI 不开 TCP 端口**——worker 用假 URL 把 fetch 转成对 `Server.Default().app.fetch()` 的同进程调用。

几个反直觉点：

- **`tab` 默认绑的是 `agent_cycle`（切 agent），不是自动补全**：自动补全是另一个 mode 下的 `prompt.autocomplete.complete`（同样默认 `"tab"`），靠不同绑定上下文区分。
- **大量 keybind 默认值是 `"none"`**（默认无快捷键、需用户配置才生效），leader 是 `ctrl+x`；`<leader>q` 在不同 mode 下既是 `app_exit` 又是 `session_queued_prompts`。
- **worker 不走 HTTP**：`rpc.fetch` 在 worker 内直接 `Server.Default().app.fetch(request)`；只有显式传 `--port/--hostname/--mdns`（external）才起真实 listener 走网络。

## Framework and Worker Architecture

`packages/tui/package.json` 依赖 `@opentui/core` / `@opentui/keymap` / `@opentui/solid` / `solid-js`，JSX 用 `<box>` / `<text>` / `<scrollbox>` / `<diff>` 等终端原语。配置解耦：`tui.json`（界面：快捷键、主题、状态栏）与 `opencode.json`（运行时：模型、Agent、权限）分开，换终端不影响 Agent 行为。

TUI 进程结构：`cli/cmd/tui.ts` 启动一个 Worker，建立 `Rpc.client`，把 fetch 包装成 `client.call("fetch", ...)`：

```typescript
const worker = new Worker(file, {
  env: Object.fromEntries(Object.entries(process.env).filter((entry): entry is [string, string] => entry[1] !== undefined)),
})
const client = Rpc.client<typeof rpc>(worker)
const transport = external
  ? { url: (await client.call("server", network)).url, fetch: undefined, events: undefined, headers }
  : { url: "http://opencode.internal", fetch: createWorkerFetch(client), events: createEventSource(client) }
```

worker 侧（`cli/tui/worker.ts`）暴露 `rpc` 对象并 `Rpc.listen(rpc)`。`rpc.fetch` 构造 Request（注入 basic auth header）后直接内存调用 server app；全局事件通过 RPC 反向推给 TUI：

```typescript
export const rpc = {
  async fetch(input: { url: string; method: string; headers: Record<string, string>; body?: string }) {
    const headers = { ...input.headers }
    const auth = ServerAuth.header()
    if (auth && !headers["authorization"] && !headers["Authorization"]) headers["Authorization"] = auth
    const request = new Request(input.url, { method: input.method, headers, body: input.body })
    const response = await Server.Default().app.fetch(request)
    return { status: response.status, headers: Object.fromEntries(response.headers.entries()), body: await response.text() }
  },
  async server(input: { port: number; hostname: string; mdns?: boolean; cors?: string[] }) {
    if (server) await server.stop(true)
    server = await Server.listen(input)
    return { url: server.url.toString() }
  },
}
GlobalBus.on("event", (event) => { Rpc.emit("global.event", event) })
Rpc.listen(rpc)
```

`Rpc` 底层（`util/rpc.ts`）是基于 `postMessage` 的 JSON 协议：请求方法名 + input，响应 result/error + id；注释强调"抛异常的请求也必须回复，否则调用方永远等待"。

## Keybindings

`config/keybind.ts` 用 `keybind(default, description)` 定义 `Definitions`，leader 默认 `ctrl+x`：

```typescript
export const LeaderDefault = "ctrl+x"
const keybind = (value: Definition["default"], description: string): Definition => ({ default: value, description })

agent_list: keybind("<leader>a", "List agents"),
agent_cycle: keybind("tab", "Next agent"),
agent_cycle_reverse: keybind("shift+tab", "Previous agent"),
variant_cycle: keybind("ctrl+t", "Cycle model variants"),
```

session 导航与管理：

```typescript
session_new: keybind("<leader>n", "Create a new session"),
session_list: keybind("<leader>l", "List all sessions"),
session_timeline: keybind("<leader>g", "Show session timeline"),
session_rename: keybind("ctrl+r", "Rename session"),
session_delete: keybind("ctrl+d", "Delete session"),
session_interrupt: keybind("escape", "Interrupt current session"),
session_compact: keybind("<leader>c", "Compact the session"),
session_queued_prompts: keybind("<leader>q", "Manage queued prompts"),
session_child_first: keybind("<leader>down", "Go to first child session"),
session_child_cycle: keybind("right", "Go to next child session"),
session_parent: keybind("up", "Go to parent session"),
```

其它高频项：`app_exit: "ctrl+c,ctrl+d,<leader>q"`、`command_list: "ctrl+p"`、`model_list: "<leader>m"`、`model_cycle_recent: "f2"/"shift+f2"`、`theme_list: "<leader>t"`、`sidebar_toggle: "<leader>b"`、`session_quick_switch_1..9: "<leader>1".."<leader>9"`、`which_key_toggle: "ctrl+alt+k"`、`messages_first: "ctrl+g,home"`、`messages_last: "ctrl+alt+g,end"`。注意 `tab` 的双重身份：Autocomplete 弹开时是补全、否则是切 agent，由不同 mode 的 `useBindings` 区分。

## Agent Switching and Permission UI

agent 切换的 UI 状态机在 `context/local.tsx` 的 `createAgent()`，`move(direction)` 做环形切换（对应 `agent_cycle`），只在非 subagent 且非 hidden 的 agent 间循环：

```typescript
move(direction: 1 | -1) {
  batch(() => {
    const current = this.current()
    if (!current) return
    let next = agents().findIndex((x) => x.name === current.name) + direction
    if (next < 0) next = agents().length - 1
    if (next >= agents().length) next = 0
    setAgentStore("current", agents()[next].name)
  })
}
```

权限确认 UI 在 `routes/session/permission.tsx` 的 `PermissionPrompt`，三段 stage（`permission | always | reject`），主界面给 once / always / reject 三选项，最终经 SDK 回写：

```typescript
onSelect={(option) => {
  if (option === "always") { setStore("stage", "always"); return }
  if (option === "reject") {
    if (session()?.parentID) { setStore("stage", "reject"); return }
    void sdk.client.permission.reply({ reply: "reject", requestID: props.request.id, /* ... */ })
    return
  }
  void sdk.client.permission.reply({ reply: "once", requestID: props.request.id, /* ... */ })
}}
```

`context/permission.tsx` 定义 `PermissionMode = "auto" | "normal"`（由 `--auto` flag 决定初始模式），对应 CLI 里权限请求自动批准的行为。权限的求值模型见 [Agent](/docs/CS/AI/LLM/Agent/Product/OpenCode/Agent.md)。

## Links

- [Server](/docs/CS/AI/LLM/Agent/Product/OpenCode/Server.md) / [CLI](/docs/CS/AI/LLM/Agent/Product/OpenCode/CLI.md) / [Agent](/docs/CS/AI/LLM/Agent/Product/OpenCode/Agent.md)
- [Commands](/docs/CS/AI/LLM/Agent/Product/OpenCode/Commands.md) / [Rules](/docs/CS/AI/LLM/Agent/Product/OpenCode/Rules.md) / [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)

## References

1. [tui/src/config/keybind.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/tui/src/config/keybind.ts)
2. [opencode/src/cli/tui/worker.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/cli/tui/worker.ts)
3. [opencode/src/cli/cmd/tui.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/cli/cmd/tui.ts)
4. [tui/src/routes/session/permission.tsx](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/tui/src/routes/session/permission.tsx)
5. [opencode/src/util/rpc.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/util/rpc.ts)
