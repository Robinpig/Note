> 版本基线：v1.19.5（`E:/Projects/opencode-1.19.5` release 源码快照）。本文以 **V1 工具体系**（`packages/opencode/src/tool/`，`Tool.define()` + Effect，`session/tools.ts` 走这套，是当前实际执行链路）为主线；**V2**（`packages/core/src/tool/`，`Tool.make()` + 不透明值 + WeakMap）作为对照，其 `builtins.ts` 的 TODO 明写 task / LSP / code mode 尚未移植。

## Introduction

工具是 LLM 在 OpenCode 里能采取的行动。理解这套实现的关键前提是：**权限不在 registry / 执行框架层统一鉴权，而在每个叶工具的 `execute` 里手写 `ctx.ask()`**。registry 的过滤只是"目录可见性"，不是授权判断。

几个反直觉点：

- **所谓"agent 工具白名单"实为黑名单**：工具默认全部对模型可见，只有权限规则命中 `pattern == "*" && action == "deny"` 才隐藏；`edit/write/apply_patch` 被归一成同一个 `edit` 键，禁 `edit` 等于一次禁三个。
- **`bash` 工具对外名仍是 `bash`**，类/文件叫 ShellTool，但 `ShellID.ToolID = "bash"` 刻意保留以兼容既有插件与已保存权限（注释写明 2.0 再改名）。内部变量名 `patch` / 对外 id `apply_patch` 也有错位。
- **apply_patch 有两套并存且能力不一致的实现**：V1 支持 move，V2 见到 move 直接失败。
- **执行链上有两道独立的门**：`tool.execute.before` 插件钩子（可改参数、可抛错硬拦截）与 `ctx.ask()` 权限审批，详见 [Plugin](/docs/CS/AI/LLM/Agent/Product/OpenCode/Plugin.md) 与 [Agent](/docs/CS/AI/LLM/Agent/Product/OpenCode/Agent.md)。

## The Tool Contract

一个工具的契约 = schema（参数/输出） + description + execute + 权限键 + 输出截断。关键点是权限键与截断都不写进工具定义本身：前者由 `execute` 内的 `ctx.ask()` 承担，后者由统一的 `wrap` 包装注入。V1 的 `Def` 契约字段是 `id / description / parameters / jsonSchema? / execute / formatValidationError?`，`execute` 返回 `{ title, metadata, output, attachments? }`。

V1 的 `wrap`（`packages/opencode/src/tool/tool.ts`）是**参数校验 + 截断的汇合点**，注意它本身不做权限：

```typescript
toolInfo.execute = (args, ctx) => {
  const attrs = { "tool.name": id, "session.id": ctx.sessionID, "message.id": ctx.messageID }
  return Effect.gen(function* () {
    const decoded = yield* decode(args).pipe(
      Effect.mapError((error) => new InvalidArgumentsError({
        tool: id,
        detail: toolInfo.formatValidationError ? toolInfo.formatValidationError(error) : String(error),
      })),
    )
    const result = yield* execute(decoded as Schema.Schema.Type<Parameters>, ctx)
    if (result.metadata.truncated !== undefined) return result
    const agent = yield* agents.get(ctx.agent)
    const truncated = yield* truncate.output(result.output, {}, agent)
    return {
      ...result, output: truncated.content,
      metadata: { ...result.metadata, truncated: truncated.truncated,
        ...(truncated.truncated && { outputPath: truncated.outputPath }) },
    }
  }).pipe(Effect.orDie, Effect.withSpan("Tool.execute", { attributes: attrs }))
}
```

decode 失败抛 `InvalidArgumentsError`（typed error，可回喂模型"请重写输入"）；成功后调原始 execute（叶子工具在这里面自己做权限）；最后统一截断。若叶子自己声明了 `metadata.truncated`（如 bash），跳过通用截断。

V2 的契约更显式（`packages/core/src/tool/tool.ts`），用 `withPermission(tool, permission)` 装饰出新工具，权限键存在 WeakMap 的 runtime 里；`permission()` 取不到就用注册名兜底；`edit/write/apply_patch` 共享 `edit` 动作。

## The Registry

V1 的 `Service`（`packages/opencode/src/tool/registry.ts`）用 `InstanceState.make<State>` 持有 `{ custom, builtin, task, read }`：

- **builtin**：`Tool.init()` 按条件拼数组——question（client 白名单）、execute（code mode）、lsp（实验 flag）、plan（实验 flag + cli）。
- **custom**：两条来源——扫描 `{tool,tools}/*.{js,ts}` 按文件名做 namespace；`plugin.list()` 里每个 plugin 的 `p.tool`。都经 `fromPlugin` 转成统一 `Tool.Def`，工具名解析为 `id === "default" ? namespace : ${namespace}_${id}`。

`tools()` 方法做 provider/model 级过滤（不是权限）：

```typescript
const filtered = (yield* all()).filter((tool) => {
  if (tool.id === WebSearchTool.id) return webSearchEnabled(input.providerID, { exa: flags.enableExa, parallel: flags.enableParallel })
  const usePatch = input.modelID.includes("gpt-") && !input.modelID.includes("oss") && !input.modelID.includes("gpt-4")
  if (tool.id === ApplyPatchTool.id) return usePatch
  if (tool.id === EditTool.id || tool.id === WriteTool.id) return !usePatch
  return true
})
```

GPT 系（非 oss、非 gpt-4）只暴露 `apply_patch`，隐藏 `edit`/`write`；code mode 开启时把众多 MCP 工具收敛成一个 `execute` 工具 + catalog 描述。真正的可见性归一在 `packages/opencode/src/permission/index.ts`：

```typescript
export function disabled(tools: string[], ruleset: PermissionV1.Ruleset): Set<string> {
  const edits = ["edit", "write", "apply_patch"]
  const reads = ["list_mcp_resources", "list_mcp_resource_templates", "read_mcp_resource"]
  return new Set(tools.filter((tool) => {
    const permission = edits.includes(tool) ? "edit" : reads.includes(tool) ? "read" : tool
    const rule = ruleset.findLast((rule) => Wildcard.match(permission, rule.permission))
    return rule?.pattern === "*" && rule.action === "deny"
  }))
}
```

发请求前 `resolveTools`（`session/llm/request.ts`）合并 agent + session 权限，再剔除 `user.tools[k] === false` 的工具。V2 registry（`core/src/tool/registry.ts`）用 `local: Map<name, Array<{token, registration}>>`（Location 作用域）+ `applications`（进程全局），`materialize(permissions)` 叠加后过滤，Location 注册优先于 Application 注册。

## The Execution Chain

链路（V1）：模型产出 tool_call → `processor.ts` 把 part 置 running → AI SDK `tool()` 的 `execute(args, options)` → `run.promise(Effect.gen)` 构造 ctx → `plugin.trigger("tool.execute.before")` → `item.execute`（decode → 叶子 `ctx.ask()` 鉴权 → truncate）→ `plugin.trigger("tool.execute.after")` → `processor.ts` 的 `completeToolCall` 回填 completed part。

`session/tools.ts` 的 `context()` 把 `ctx.ask` 桥接到 `Permission.ask`，并合并 agent + session 规则集：

```typescript
ask: (req) =>
  permission.ask({
    ...req, sessionID: input.session.id,
    tool: { messageID: input.processor.message.id, callID: options.toolCallId },
    ruleset: Permission.merge(input.agent.permission, input.session.permission ?? []),
  }).pipe(Effect.orDie),
```

execute 主体（每个工具都走这道钩子）：

```typescript
execute(args, options) {
  return run.promise(Effect.gen(function* () {
    const ctx = context(args, options)
    yield* plugin.trigger("tool.execute.before",
      { tool: item.id, sessionID: ctx.sessionID, callID: ctx.callID }, { args })
    const result = yield* item.execute(args, ctx)
    const output = { ...result, attachments: result.attachments?.map((attachment) => ({
      ...attachment, id: PartID.ascending(), sessionID: ctx.sessionID,
      messageID: input.processor.message.id,
    })) }
    yield* plugin.trigger("tool.execute.after",
      { tool: item.id, sessionID: ctx.sessionID, callID: ctx.callID, args }, output)
    if (options.abortSignal?.aborted) yield* input.processor.completeToolCall(options.toolCallId, output)
    return output
  }))
}
```

**权限在哪一步做**：在叶工具的 `execute` 内部由工具自己 `ctx.ask()`，不在 registry、不在 wrap、不在 processor。`apply_patch` 算好待改文件后 `ctx.ask({permission:"edit", patterns: relativePaths})`；`task` 用 `ctx.ask({permission:"task", patterns:[subagent_type]})`；`bash` 请求 `external_directory` + `bash` 两类权限。`processor.ts` 还做 doom-loop 检测（连续 N 次同名同输入 tool_call 触发 `doom_loop` 权限询问）。

## apply_patch

旧 `patch` 已更名 `apply_patch`（对外 id `"apply_patch"`，内部变量名仍是 patchtool）。`Patch.parsePatch`（`opencode/src/patch/index.ts`）先 `stripHeredoc`，用 `*** Begin Patch` / `*** End Patch` 定位，再按 `*** Add File:` / `*** Delete File:` / `*** Update File:`（可跟 `*** Move to:`）切成 Hunk，`Update File` 段按 `@@` 切 chunk。

V1 执行：逐 hunk `path.resolve` + `assertExternalDirectoryEffect`，add 拼内容、update 用 `deriveNewContentsFromChunks`、delete 生成删除 diff，统一 `ctx.ask({permission:"edit"})`，落盘后 `format.file`、发 `FileSystem.Event.Edited`/`Watcher.Event.Updated`、`lsp.touchFile` 收集 diagnostics。模糊匹配 `seekSequence` 做 **4 轮降级**：

```typescript
function seekSequence(lines: string[], pattern: string[], startIndex: number, eof = false): number {
  if (pattern.length === 0) return -1
  const exact = tryMatch(lines, pattern, startIndex, (a, b) => a === b, eof)
  if (exact !== -1) return exact
  const rstrip = tryMatch(lines, pattern, startIndex, (a, b) => a.trimEnd() === b.trimEnd(), eof)
  if (rstrip !== -1) return rstrip
  const trim = tryMatch(lines, pattern, startIndex, (a, b) => a.trim() === b.trim(), eof)
  if (trim !== -1) return trim
  const normalized = tryMatch(lines, pattern, startIndex,
    (a, b) => normalizeUnicode(a.trim()) === normalizeUnicode(b.trim()), eof)
  return normalized
}
```

精确 → 去尾部空白 → 去两端空白 → Unicode 标点归一化后再 trim；`eof=true` 时优先从文件尾部试。V2 的 `core/src/patch.ts` 是同构实现，但额外约束：不支持 move 与原子回滚（见到 move 直接失败），用 `files.writeIfUnchanged({expected: source})` 做乐观并发保护。

## Code Mode and Task

`code-mode.ts` 定义一个名为 **`execute`** 的实验工具（`experimentalCodeMode` flag 才注册），它不是普通工具而是**元工具**：不在模型面前铺开所有 MCP 工具，而是给一段受限脚本解释器 + 由 MCP 工具构成的目录树，模型写脚本按需调用子工具，省 context/token。`Permission.visibleTools` 用黑名单制过滤，开启后 `session/tools.ts` 不再逐个注册 MCP 工具。详见 [MCP](/docs/CS/AI/LLM/Agent/Product/OpenCode/MCP.md)。

`task.ts`（`Tool.define("task")`）起子 agent：后台模式需 `experimentalBackgroundSubagents` flag；**深度限制**——沿 `parentID` 上溯 `depth >= cfg.subagent_depth ?? 1` 就拒绝（默认**不允许嵌套子 agent**）；`ctx.ask({permission:"task", patterns:[subagent_type]})`；子会话默认**禁掉 `todowrite` 和 `task` 自身**防无限递归；`sessions.create({parentID, agent, permission})` 后经 `promptOps.prompt()` 跑一轮，取最后 text，用 `<task id=... state=...>` XML 包裹结果。详见 [Agent](/docs/CS/AI/LLM/Agent/Product/OpenCode/Agent.md)。

## Truncation and Shell

`truncate.ts` 默认 `MAX_LINES = 2000`、`MAX_BYTES = 50 * 1024`（config `tool_output.max_lines/max_bytes` 可覆盖）。超限时按 `direction`（默认 head）逐行累加，完整文本写入 `~/.local/share/opencode/tool-output/`（保留 7 天、每小时清理），返回预览 + 提示。有 task 工具时提示"用 Task 委派 explore agent 去 Grep/Read，别自己读全文以省 context"。`bash` 工具不直接调用通用截断（自带 `tail()` 与边跑边落盘的流式截断）。

`shell.ts` 的对外 id 是 `"bash"`，工具描述按 shell 类型（bash / PowerShell 5.1 / PowerShell 7+ / cmd）与平台动态渲染。命令解析用 `web-tree-sitter` 加载 bash/powershell grammar，遍历 AST 提取命令名与路径参数做 `external_directory` 权限扫描；其余走 `BashArity.prefix(tokens)` 生成 pattern 请求 `bash` 权限（arity 字典见 [Agent](/docs/CS/AI/LLM/Agent/Product/OpenCode/Agent.md)）。执行用 `ChildProcess.make`，工作目录 `resolvePath(workdir, directory, shell)`（Windows 下用 `cygpath -w`），环境 `{...process.env, ...plugin.trigger("shell.env").env}`，默认超时 2 分钟，用 `Effect.raceAll([exitCode, abort, timeout+100ms])`，超时/中断后 `handle.kill({forceKillAfter:"3 seconds"})`。

## Links

- [Agent](/docs/CS/AI/LLM/Agent/Product/OpenCode/Agent.md) / [Plugin](/docs/CS/AI/LLM/Agent/Product/OpenCode/Plugin.md) / [MCP](/docs/CS/AI/LLM/Agent/Product/OpenCode/MCP.md)
- [SessionLoop](/docs/CS/AI/LLM/Agent/Product/OpenCode/SessionLoop.md) / [Context](/docs/CS/AI/LLM/Agent/Product/OpenCode/Context.md) / [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)

## References

1. [opencode/src/tool/tool.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/tool/tool.ts)
2. [opencode/src/tool/registry.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/tool/registry.ts)
3. [opencode/src/session/tools.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/session/tools.ts)
4. [opencode/src/patch/index.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/patch/index.ts)
5. [core/src/tool/tool.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/core/src/tool/tool.ts)
