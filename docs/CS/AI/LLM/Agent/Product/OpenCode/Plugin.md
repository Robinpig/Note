> 版本基线：v1.19.5（`E:/Projects/opencode-1.19.5` release 源码快照）。v1.19.5 并存**两套插件体系**：Hooks 体系（v1，`packages/plugin/src/index.ts` 的 `Hooks` 接口，用户熟知的 `tool.execute.before` 等）由 `packages/opencode/src/plugin/index.ts` 加载；Effect PluginV2（`packages/core/src/plugin.ts` + `host.ts`）提供 `host.agent/catalog/command/skill/reference/integration/plugin` 的 transform 注册面，不走 Hooks。本文以 v1 Hooks 为主。

## Introduction

插件是 OpenCode 的事件钩子机制——相当于 Claude Code 的 Hooks，但用 JS/TS 模块表达。插件导出一个函数，收到 `{ project, directory, worktree, client, $ }` 并返回一组 hook。它能改 LLM 请求参数、拦截工具调用、注入 shell 环境、监听事件。

几个反直觉点：

- **`session.idle` / `auth.provider` / `provider.models` 都不是 hook 名**：分别是 Event 事件类型、`AuthHook.provider` 字段、`ProviderHook.models()` 方法。真正通过 `plugin.trigger()` 调用的只有签名 `(input,output)=>Promise<void>` 的成员。
- **两套插件体系共存且互不相通**：v1 Hooks 走 `cfg.plugin_origins` 加载；v2 PluginV2 走 Effect scope + `host.transform`，同名概念语义不同。
- **hook 拦截与权限是两道独立的门**，顺序是 hook 先、permission 后；hook 里 `throw` 会让工具根本不被执行——这是硬拦截。
- **`permission.ask` hook 定义了但源码里找不到 trigger 点**，v1.19.5 是否生效未核实；真正的拦截靠 `Permission` 服务 + `tool.execute.before` 抛错。

## How Plugins Are Loaded

来源收敛到派生字段 `cfg.plugin_origins`（由 Config 在合并各层时构造，不是持久配置键），四类来源：`~/.config/opencode/opencode.json`（全局）→ `OPENCODE_CONFIG` → 项目的 `opencode.json(c)` → 目录扫描 `{plugin,plugins}/*.{ts,js}`：

```typescript
for (const item of await Glob.scan("{plugin,plugins}/*.{ts,js}", {
  cwd: dir, absolute: true, dot: true, symlink: true,
})) {
  plugins.push(pathToFileURL(item).href)
}
```

去重先 `toReversed()` 再 `seen` 再 `toReversed()`，意味着**后声明者胜出**。`flags.pure`（CLI `--pure`）会完全跳过外部插件。运行时真正加载在 `plugin/index.ts`：先加载内建插件（认证类，直接 import），再按 `plugin_origins` 外部加载。**加载动作并行、注册动作串行**——这是 hook 顺序确定性的来源：

```typescript
for (const load of loaded) {
  if (!load) continue
  // Keep plugin execution sequential so hook registration and execution order remains deterministic across plugin runs.
  yield* Effect.tryPromise({
    try: () => applyPlugin(load, input, hooks),
    // ...
  })
}
```

CLI 侧 `opencode plugin|plug <module>` 会 install → 读 manifest → patch 配置，`--global` 决定是否写全局配置。

## The Hook Surface

完整权威清单是 `packages/plugin/src/index.ts` 的 `Hooks` 接口：

```typescript
export interface Hooks {
  dispose?: () => Promise<void>
  event?: (input: { event: Event }) => Promise<void>
  config?: (input: Config) => Promise<void>
  tool?: { [key: string]: ToolDefinition }
  auth?: AuthHook
  provider?: ProviderHook
  "chat.message"?: (input, output: { message; parts }) => Promise<void>
  "chat.params"?: (input, output: { temperature; topP; topK; maxOutputTokens; options }) => Promise<void>
  "chat.headers"?: (input, output: { headers: Record<string,string> }) => Promise<void>
  "permission.ask"?: (input, output: { status: "ask"|"deny"|"allow" }) => Promise<void>
  "command.execute.before"?: (input: { command; sessionID; arguments }, output: { parts }) => Promise<void>
  "tool.execute.before"?: (input: { tool; sessionID; callID }, output: { args: any }) => Promise<void>
  "shell.env"?: (input: { cwd; sessionID?; callID? }, output: { env: Record<string,string> }) => Promise<void>
  "tool.execute.after"?: (input: { tool; sessionID; callID; args }, output: { title; output; metadata }) => Promise<void>
  "tool.definition"?: (input: { toolID }, output: { description; parameters }) => Promise<void>
  // experimental.*: chat.messages.transform / chat.system.transform /
  //   provider.small_model / session.compacting / compaction.autocontinue / text.complete
}
```

触发时机（grep 已逐一验证）：`tool.execute.before` 在 `session/tools.ts` 与 `code-mode.ts` 的工具真执行前（可改 `output.args`）；`tool.execute.after` 在返回后（可改 title/output/metadata）；`chat.params`/`chat.headers` 在 `session/llm/request.ts` 组装 LLM 请求时；`chat.message`/`command.execute.before` 在 `session/prompt.ts`；`shell.env` 在 `tool/shell.ts` 与 PTY handler（同时覆盖 AI 工具与用户终端）；`event` 在 `plugin/index.ts` 的 `events.listen`；`config` 在所有插件加载完成后；`dispose` 在实例销毁；`tool.definition` 在 `tool/registry.ts` 组装工具定义时。

`chat.params` 的真实触发片段：

```typescript
const params = yield* input.plugin.trigger("chat.params", {
  sessionID: input.sessionID, agent: input.agent.name, model: input.model,
  provider: input.provider, message: input.user,
}, {
  temperature: input.model.capabilities.temperature
    ? (input.agent.temperature ?? ProviderTransform.temperature(input.model)) : undefined,
  topP: input.agent.topP ?? ProviderTransform.topP(input.model),
  topK: ProviderTransform.topK(input.model),
  maxOutputTokens: ProviderTransform.maxOutputTokens(input.model, input.flags.outputTokenMax),
  options,
})
```

## Custom Tools and Overriding Built-ins

`tool()` 是一个**零逻辑的恒等函数**，仅提供类型收窄：

```typescript
export function tool<Args extends z.ZodRawShape>(input: {
  description: string
  args: Args
  execute(args: z.infer<z.ZodObject<Args>>, context: ToolContext): Promise<ToolResult>
}) {
  return input
}
tool.schema = z
```

插件通过返回对象的 `tool` 字段注册，`registry.ts` 统一经 `fromPlugin` 把 Zod args 转成 JSON Schema。覆盖同名内置工具的机制是顺序：`all()` 返回 `[...s.builtin, ...s.custom]`，`session/tools.ts` 用 `tools[item.id] = tool({...})` 写字典，后写覆盖先写——**自定义工具同名时覆盖内置工具**。详见 [Tools](/docs/CS/AI/LLM/Agent/Product/OpenCode/Tools.md)。

V2 的 tool 注册不在 `tool()` 体系内：经 `host.agent/catalog/skill/...` 的 `transform(callback)` 注册，返回带 `dispose` 的 Registration，生命周期由 Effect scope 管理。

## Hooks and Permission: Two Gates

插件能硬拦截，且 hook 先、permission 后。证据在 `session/tools.ts`（MCP 工具执行链，内置工具同构）：

```typescript
yield* plugin.trigger("tool.execute.before",
  { tool: key, sessionID: ctx.sessionID, callID: opts.toolCallId }, { args })
const result = ... yield* Effect.gen(function* () {
  yield* ctx.ask({ permission: key, metadata: {}, patterns: ["*"], always: ["*"] })
  return yield* Effect.promise(() => execute(args, opts))
})
yield* plugin.trigger("tool.execute.after", /* ... */, result)
```

`plugin.trigger` 内部是 `yield* Effect.promise(async () => fn(input,output))`，hook 里 `throw` 让 Effect 失败并冒泡，`execute` 根本不被调用——官方 `.env 保护`示例正是在 `tool.execute.before` 里对 `output.args.filePath.includes(".env")` 抛错。`ctx.ask` 走独立的 Permission 服务（详见 [Agent](/docs/CS/AI/LLM/Agent/Product/OpenCode/Agent.md)）。二者职责不同：**hook 是可扩展的策略拦截层（可改参数、可抛错终止），permission 是内建的用户审批层**，互不替代。

## Links

- [Tools](/docs/CS/AI/LLM/Agent/Product/OpenCode/Tools.md) / [Agent](/docs/CS/AI/LLM/Agent/Product/OpenCode/Agent.md) / [MCP](/docs/CS/AI/LLM/Agent/Product/OpenCode/MCP.md)
- [Provider](/docs/CS/AI/LLM/Agent/Product/OpenCode/Provider.md) / [Server](/docs/CS/AI/LLM/Agent/Product/OpenCode/Server.md) / [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)

## References

1. [plugin/src/index.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/plugin/src/index.ts)
2. [opencode/src/plugin/index.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/plugin/index.ts)
3. [opencode/src/config/plugin.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/config/plugin.ts)
4. [core/src/plugin.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/core/src/plugin.ts)
5. [OpenCode Plugins 文档](https://opencode.ai/docs/plugins/)
