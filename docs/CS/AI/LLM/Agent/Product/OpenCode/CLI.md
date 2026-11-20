> 版本基线：v1.19.5（`E:/Projects/opencode-1.19.5` release 源码快照）。本文基于 `packages/opencode/src/index.ts`（yargs 入口）、`cli/effect-cmd.ts` 与 `cli/cmd/`。架构层与 C/S 形态见 [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md) 与 [Server](/docs/CS/AI/LLM/Agent/Product/OpenCode/Server.md)。

## Introduction

OpenCode CLI 默认不带参数即启动 TUI，也能以子命令形式驱动，用于脚本、管道与 CI。几十个子命令挂在一个 yargs `cli` 上，每个命令通过 `effectCmd` 抽象把 yargs builder 与 Effect handler 结合。

几个反直觉点：

- **`instance:false` 不是"不执行命令"，而是"不加载项目 InstanceContext"**：handler 仍在 `AppRuntime` 下跑，但 yield `InstanceRef` 会得到 undefined 触发 defect；`run --attach` 用函数形式 `(args) => !args.attach` 动态切换。
- **`--share` 是隐藏的废弃参数**：仍在 builder 里（`hidden: true`）但只打印 "Session sharing has been discontinued"。
- **并非所有命令都迁移到了 `effectCmd`**：`upgrade`/`attach` 用旧式 `cmd()` + async handler（内部手动 `Effect.runPromise`），`run`/`db`/`session` 子命令才用 `effectCmd`。

## The effectCmd Abstraction

`effectCmd` 的注释把 `instance` 语义讲得很清楚（默认值 true）：`true` 把 handler 包在 `InstanceStore.Service.provide({directory})` 里、`Effect.ensuring(store.dispose(ctx))` 自动销毁；`false` 跳过实例、直接在 AppRuntime 跑、且抑制 `server.instance.disposed` IPC 事件；函数形式按每次调用决定。

```typescript
async handler(rawArgs) {
  const { AppRuntime } = await import("@/effect/app-runtime")
  const args = rawArgs as unknown as WithDoubleDash<Args>
  const useInstance = typeof opts.instance === "function" ? opts.instance(args) : opts.instance !== false
  if (!useInstance) {
    await AppRuntime.runPromise(opts.handler(args))
    return
  }
  const { InstanceStore } = await import("@/project/instance-store")
  const { InstanceRef } = await import("@/effect/instance-ref")
  const directory = opts.directory?.(args) ?? process.cwd()
  const { store, ctx } = await AppRuntime.runPromise(
    InstanceStore.Service.use((store) => store.load({ directory }).pipe(Effect.map((ctx) => ({ store, ctx })))),
  )
  try {
    await AppRuntime.runPromise(opts.handler(args).pipe(Effect.provideService(InstanceRef, ctx)))
  } finally {
    await AppRuntime.runPromise(store.dispose(ctx))
  }
}
```

`cmd()` 本身只是 typing 恒等包装；用户可见失败用 `fail()`（`CliError` Schema TaggedError），顶层 `src/cli/error.ts` 格式化输出。`.strict()` + `.parserConfiguration({ "populate--": true })` 让 `--` 后的参数透传。

## Command Landscape

`index.ts` 挂载的主要命令：`acp` / `mcp` / `tui`（TuiThread）/ `attach` / `run` / `generate` / `debug` / `account` / `providers` / `agent` / `upgrade` / `uninstall` / `serve` / `web` / `models` / `stats` / `export` / `import` / `github` / `pr` / `session` / `plugin` / `db`。按用途分组：

- **交互入口**：`tui`（默认）、`acp`（IDE）、`attach <url>`（远程 attach 到 serve 实例）
- **非交互**：`run [message..]`（单 prompt、流式输出、session idle 即退出）、`generate`
- **服务端**：`serve`（headless HTTP）、`web`（server + 浏览器）
- **运维/管理**：`session` / `db` / `models` / `providers` / `agent` / `plugin` / `upgrade` / `uninstall` / `stats` / `export` / `import` / `github` / `pr`

`serve` / `web` / `account` / `db` / `upgrade` / `models` 用 `instance:false`（不读项目状态）。

## run: Print Mode, Continue, Fork

`run` 的顶部注释把三种模式讲得很清楚：非交互（默认，单 prompt → stdout 流式 → idle 退出）、交互本地（`opencode --mini`，in-process server）、交互 attach（`--mini --attach`，连远端 server）。还支持 `--command`（斜杠命令）、`--format json`（原始事件流）、`--continue`/`--session`（续会话）、`--fork`（续前分叉）：

```typescript
export const RunCommand = effectCmd({
  command: "run [message..]",
  instance: (args) => !args.attach,
  directory: (args) => (args.dir && !args.attach ? path.resolve(process.cwd(), args.dir) : process.cwd()),
  builder: (yargs) => yargs
    .option("command", { describe: "the command to run, use message for args", type: "string" })
    .option("continue", { alias: ["c"], describe: "continue the last session", type: "boolean" })
    .option("session", { alias: ["s"], describe: "session id to continue", type: "string" })
    .option("fork", { describe: "fork the session before continuing (requires --continue or --session)", type: "boolean" })
    .option("share", { type: "boolean", describe: "deprecated: session sharing was discontinued", hidden: true }),
})
```

非交互模式下权限请求自动处理：`--auto` 时 reply `"once"`，否则打印权限名与 patterns 后 `"reject"`（自动拒绝）。这解释了脚本/CI 场景如何无人值守运行。

## attach and Network Security

`attach <url>` 构造 SDK client（`createOpencodeClient({ baseUrl: args.attach, headers })`）连远端 server，经 `validateSession` 校验后把 TUI 跑在该会话上：

```typescript
const headers = ServerAuth.headers({ password: args.password, username: args.username })
await validateSession({ url: args.url, sessionID: args.session, directory, headers })
await Effect.runPromise(run({
  url: args.url, config, pluginHost: createLegacyTuiPluginHost(),
  args: { continue: args.continue, sessionID: args.session, fork: args.fork },
  directory, headers,
}))
```

远程 attach 时本地文件读成 `data:<mime>;base64,...`，限制 10 MiB、不允许目录（无共享文件系统）。认证走 HTTP Basic（`OPENCODE_SERVER_PASSWORD` / `OPENCODE_SERVER_USERNAME`，见 [Server](/docs/CS/AI/LLM/Agent/Product/OpenCode/Server.md)）。

## upgrade: The Two Tracks

`upgrade` 用旧式 `cmd()`，`--major` 从 1.x 升到 2.x 并移除 OpenCode 1，普通升级只拉最新 1.x target：

```typescript
.option("major", { describe: "upgrade to OpenCode 2 and remove OpenCode 1", type: "boolean" })
// ...
if (args.major) {
  prompts.log.info(`From ${InstallationVersion} → OpenCode 2`)
  const err = await Installation.upgradeMajor(method).catch((err) => err)
}
const target = args.target ? args.target.replace(/^v/, "") : await Installation.latest(method).catch(() => undefined)
if (InstallationVersion === target) {
  prompts.log.warn(`opencode upgrade skipped: ${target} is already installed`)
  prompts.log.info("OpenCode 2 is available. Upgrade with `opencode upgrade --major`")
  return
}
```

TUI 内的更新提示（`cli/upgrade.ts`）返回 `available`（常规更新）或 `major`（2.0 offer）两态，由 `shouldNotify` 依 `config.autoupdate` 与各种 flag 判定。这就是 1.x 与 2.x 显式分离的落地——常规更新永不把 1.x 推到 2.x。

## Links

- [TUI](/docs/CS/AI/LLM/Agent/Product/OpenCode/TUI.md) / [Server](/docs/CS/AI/LLM/Agent/Product/OpenCode/Server.md) / [Commands](/docs/CS/AI/LLM/Agent/Product/OpenCode/Commands.md)
- [Agent](/docs/CS/AI/LLM/Agent/Product/OpenCode/Agent.md) / [Plugin](/docs/CS/AI/LLM/Agent/Product/OpenCode/Plugin.md) / [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)

## References

1. [opencode/src/index.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/index.ts)
2. [opencode/src/cli/effect-cmd.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/cli/effect-cmd.ts)
3. [opencode/src/cli/cmd/run.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/cli/cmd/run.ts)
4. [opencode/src/cli/cmd/attach.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/cli/cmd/attach.ts)
5. [opencode/src/cli/cmd/upgrade.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/cli/cmd/upgrade.ts)
