> 版本基线：v0.2.2-rc.3（`E:/Projects/deepseek-harness-dsh-v0.2.2-rc.3`）。`packages/tool/` 不存在——工具核心在 `core/tools`，执行器在 `tool-executor-native` / `tool-executor-ptc`，审批在 `interaction/user-approval`，loop guard 在 `guard/`。

## Introduction

工具系统是 DSH "能力接缝"最完整的样本：注册表（`ctx.tools`）只认契约，执行器是可替换 provider，审批与 guard 是挂在事件 seam 上的策略。工具从注册到结果回流经过一条严格管线，同时保持"换 provider 不动 loop"。

> 版本基线：v0.2.2-rc.3。

几个反直觉的点：

- **审批没有"永久授权"**：结果词汇只有 `allowed-once` / `rejected` / `cancelled` / `unavailable`，没有 allow-always、记住的规则或授权存储。
- **"并行"只并行工具 body**：策略（pre-execute）与结果提交（post-execute/落库）严格按模型顺序；并发分类 fail-closed——只有 `isConcurrencySafe === true` 才并行。
- **`timeoutMs` 只是声明**：注册表从不强制执行，真正的 deadline 由 `tools/execute` 包装层 timeout-policy 协作式读取 `exec.signal`，忽略信号的工具不会被引擎硬杀；fs 的 read/write/edit 干脆不设超时。

## Tool Catalog

面向模型的工具由独立插件提供，注册在 `ctx.tools` 上、通过 `ToolSchema` 暴露，不是硬编码在 Agent Loop 里的函数集合。base bundle 挂入的工具按用途分组：

| 分组 | 工具 | 后端 / 说明 |
| --- | --- | --- |
| 文件系统 | `read` / `write` / `edit`（字面替换）/ `glob` / `grep` | `dsh-fs` + `dsh-fs-local`；edit 是 str_replace 语义（原子替换 + 版本守卫） |
| Shell | `bash` / `pwsh` | `dsh-shell` + `ctx.sandbox`；自动消费沙箱边界（见 [Subprocess](/docs/CS/AI/LLM/Agent/Product/DSH/Subprocess.md)） |
| 检索 | `web_search` / `web_fetch` / `lsp` | `dsh-web` / LSP client；网络策略在模型之外执行 |
| 编排 | `skill` / `todo` / `goal` / `jobs` / `workflow` / `subagent` / `subagent control` | 多步骤流程与多 Agent（见 [Subagent & Team](/docs/CS/AI/LLM/Agent/Product/DSH/SubagentTeam.md)） |
| 基础设施 | MCP 工具集、`run_code` | `dsh-mcp-*`；`run_code` 是 PTC 展示传输保留名，永不作为普通工具注册 |

工具后端由抽象的 `ctx.fs` / `ctx.shell` 与本地或沙箱 provider 支撑；MCP 与 LSP 经各自 capability seam 接入，不混进工具内核。

## Registry: Registration and Step Admission

`ToolsService` 构造时向 systemPrompt 注册一个 schema provider，工具 schema 由此进入提示词（`packages/core/tools/src/index.ts`）：

```ts
/** Concrete tool registry and scoped executor dispatcher. */
export class ToolsService extends Service {
  static inject = ['systemPrompt']
  static Config = z.object({
    mode: z.never().description('Removed. Mount a native or PTC tool executor instead.'),
    maxParallelSubCalls: z.never().description('Moved to the PTC tool executor configuration.'),
  })

  constructor(ctx: Context) {
    super(ctx, 'tools')
    ctx.systemPrompt.tools(({ scope, toolSet }) => {
      const executor = this.selectExecutor(scope)
      const description = executor.describe(this.definitions(scope, toolSet))
      return { ...description, knownNames: description.knownNames ?? [...this.view(scope).knownNames] }
    })
  }
```

`register()` 校验输出契约、保留名 `run_code`（PTC 模式传输专用），返回 effect disposer：

```ts
    const output = (definition as Partial<ToolDefinition>).output
    if (output === undefined || typeof output !== 'object'
      || typeof output.render !== 'function') {
      throw new TypeError(`tool "${name}" must declare output { schema, render, presentationMeta? }`)
    }
    // Reserved unconditionally: any agent may select a code mode for itself
    if (name === RUN_CODE_NAME) {
      throw new Error(`tool name "${RUN_CODE_NAME}" is reserved for the PTC mode presentation transport ...`)
    }
    return this.layers.effect(
      this.ctx,
      layer => layer.tools.insert(name, { definition, when: options.when }),
      { label: 'tools.register()' },
    )
```

每个 step 开头 `resolve()` 计算一次"准入工具集"：遍历可见工具、跑各自 `when(context)` 条件，冻结成 `ResolvedToolSet`——同一集合同时喂给提示词组装与批次执行（`packages/core/tools/src/index.ts`）：

```ts
    for (const [name, definition] of view.visible) {
      const registration = view.registrations.get(name)
      let enabled: boolean
      try {
        enabled = registration?.when === undefined || await registration.when(context)
      } catch (cause: unknown) {
        throw new ToolActivationError(name, cause)
      }
      if (enabled) admitted.set(name, definition)
    }
```

`ToolDefinition` 要求规范输出声明；`execute` 只返回规范 lossless-JSON 值，必须观察 `exec.signal`（`packages/core/tools/src/contracts.ts`）：

```ts
export interface ToolDefinition extends ToolSchema {
  /** Mandatory canonical output declaration. */
  readonly output: ToolOutputDefinition
  execute(args: unknown, exec: ToolRunContext): Promise<unknown>
}
```

## The Execution Pipeline: Four Waterfalls

工具执行管线是四段 waterfall（`packages/core/tools/src/events.ts`）：

```ts
    'tools/pre-execute'(this: Scoped<ToolsService>, exec: ToolExecution, next: () => Promise<PreToolDecision>): Promise<PreToolDecision>
    'tools/execute'(this: Scoped<ToolsService>, exec: ToolDispatchExecution, next: () => Promise<ToolExecutionResult>): Promise<ToolExecutionResult>
    'tools/post-execute'(this: Scoped<ToolsService>, exec: ToolExecution, result: Readonly<ToolExecutionResult>, next: () => Promise<PostToolDecision>): Promise<PostToolDecision>
    'tools/result'(this: Scoped<ToolsService>, exec: Readonly<ToolExecution>, result: Readonly<ToolExecutionResult>): undefined
```

**pre-execute** 先决定 allow/deny/ask/cancel，ask 再走审批 seam，最后跑单调 guard（`packages/core/tools/src/pipeline.ts`）：

```ts
      const gate = await this.ctx.waterfall(
        carrier, 'tools/pre-execute', exec,
        () => Promise.resolve<PreToolDecision>({ kind: 'allow' }),
      )
      const askResolution = gate.kind === 'ask'
        ? await this.serviceAsk(exec, gate)
        : { decision: gate, approvalCancelled: false }
      const { decision } = askResolution
      const denial = decision.kind === 'allow' ? this.tools.checkGuards(exec) : decision
```

guard 只有 deny、没有 allow，所以 pre-execute 里被 guard 拒绝后任何下游都改不回允许。

**execute** 用 waterfall 环绕真正 body，并把调用方信号 fuse 回来——wrapper（如 timeout）只能替换 `exec.signal`，无法脱离调用方取消（`packages/core/tools/src/pipeline.ts`）：

```ts
      const result = await this.ctx.waterfall(
        carrier, 'tools/execute', mutableExec,
        () => this.dispatchToolBody(mutableExec),
      )
```

```ts
    const wrapperSignal = exec.signal
    const fused = fuseToolSignals(state.callerSignal, wrapperSignal)
    const signal = fused.signal
    const tool = this.resolveExecution(exec.name, exec.agent, exec.parent !== undefined, exec.toolSet)
    const returned = await tool.execute(exec.arguments, exec)
```

**post-execute** 做内容投影、策略、finalize，最后 `tools/result` emit（只读）：

```ts
      const projected = content === undefined
        ? result
        : this.markCanonical(exec, this.materializeFinalResult({ ...result, content }))
      const postResult = await this.postExecute(exec, projected)
```

`projectToolSchema` 的白名单只有 `name/description/parameters/deferLoading`——`execute`、`output`、`timeoutMs`、呈现回调从不进入 wire（`packages/core/tools/src/schema.ts`）。

## Approval: allowed-once and Fail-Closed

`serviceAsk()` 机会式地取 `ctx.get('approval')`，缺失/无 agent/非 grant 一律 fail-closed 为 deny（`packages/core/tools/src/pipeline.ts`）：

```ts
    const approval = this.ctx.get('approval')
    if (approval === undefined) {
      return {
        decision: approvalDenial(ask.reason ?? `tool "${exec.name}" requires approval (not yet supported)`, APPROVAL_UNAVAILABLE),
        approvalCancelled: false,
      }
    }
    switch (outcome) {
      case 'allowed-once': return { decision: { kind: 'allow' }, approvalCancelled: false }
      case 'rejected': return { decision: approvalDenial(...), approvalCancelled: false }
      // ...
    }
```

审批服务自身把 `never` 策略在 waterfall **之前**确定（避免后注册监听器绕过），并把 `approval/asked` + `approval/decided` 成对写入 session 审计日志（`packages/interaction/user-approval/src/index.ts`）：

```ts
const OUTCOMES: readonly ApprovalOutcome[] = ['allowed-once', 'rejected', 'cancelled', 'unavailable']
    const outcome = await this.decide(req, session)
    session.append('approval/decided', { id, outcome })
```

## Concurrency and Ordered Commit

`executeToolBatch` 先按 `isConcurrencySafe` 分类，只有精确返回 `true` 才进滚动并行池，否则退化为 exclusive 并作为屏障（`packages/core/tools/src/batch.ts`）：

```ts
  const fillPool = async (): Promise<void> => {
    while (!aborted && nextToStart < group.length && inFlight.size < maxParallelToolCalls) {
      const nextCall = group[nextToStart]!
      if (nextToStart > 0 && mode === 'parallel'
        && pipeline.executionMode(nextCall.exec).kind !== 'parallel') break
      await startCall(nextToStart)
      nextToStart++
      await commitReady()
    }
  }
```

`commitReady()` 只在连续槽位提交，所以**重叠的只有工具 body**，结果按模型顺序落库（详见 [Agent Loop 的 Tool Consolidation](/docs/CS/AI/LLM/Agent/Product/DSH/AgentLoop.md?id=tool-consolidation-and-ordered-commit)）。默认并行上限 10（`packages/core/agent-loop/src/constants.ts`）：

```ts
export const DEFAULT_MAX_PARALLEL_TOOL_CALLS = 10
```

## Guards and Read-Before-Write

重复调用提醒挂在 post-execute：`next()` 先跑拿到下游决策，再把提醒 context 前置（`packages/guard/repeat-tool-reminder/src/index.ts`）：

```ts
  ctx.on('tools/post-execute', async (exec, _result, next): Promise<PostToolDecision> => {
    const reminder = observe(exec)
    const downstream = await next()
    if (!reminder) return downstream
    return { ...downstream, additionalContexts: prependContext(reminder, downstream.additionalContexts) }
  })
```

deadline enforcer 换上派生 deadline、按 code 限定作用域，避免把外层嵌套 deadline 误判为自己的超时（`packages/guard/timeout-policy/src/index.ts`）：

```ts
    using d = deadline(exec.signal, timeoutMs, TOOL_TIMEOUT)
    const upstream = exec.signal
    exec.signal = d.signal
    try {
      const result = await next()
      if (timeoutOf(d.signal, TOOL_TIMEOUT) !== undefined) {
        return toolTimeoutResult(timeoutMs)
      }
      return result
    } finally {
      exec.signal = upstream
    }
```

read-before-write 是 fs 上的观测策略：edit/delete 要求本 actor 先读过该路径，写入带版本守卫（`packages/fs/fs-observation-policy/src/index.ts`）：

```ts
    if (!owner || prior === undefined) {
      throw new FsError(`${verb} requires reading "${target.displayPath}" first`, 'FS_NOT_OBSERVED')
    }
```

## Capability Seams: Swap Provider, Not Loop

seam 三角色以工具执行器为例：

- **Service Definition**：`ctx.tools` + `ToolExecutor` 接口（`describe(definitions)` / `execute(batch)`）。
- **Service Provider**：`NativeToolExecutor` 或 `PtcExecutor`，各自 `setExecutor`；一个 scope 只允许一个：

```ts
  setExecutor(executor: ToolExecutor): () => void {
    const existing = scope === undefined ? this.root : this.scoped.get(scope)
    if (existing?.executor !== undefined) throw new Error('Only one tool executor may be registered in each scope')
```

- **Consumer**：agent-loop 只调 `ctx.tools.execute()` / `describe()`，从不 import 具体执行器。`selectExecutor` 在 dispatch 时才按作用域链晚绑定 provider：

```ts
  private selectExecutor(scope?: ScopeKey): ToolExecutor {
    for (const key of scopeChainOf(scope)) {
      const record = this.scoped.get(key)
      if (record !== undefined) break
    }
    // ...
  }
  async execute(input: ToolBatchInput): Promise<ToolBatchResult> {
    return this.selectExecutor(input.agent).execute(input)
  }
```

把 YAML 里的 native executor 换成 PTC executor，loop 零改动——PTC 只把 `describe` 改成只暴露 `run_code` 并生成 TS SDK，审批与 guard 原样复用。这就是"换 provider 不动 loop"的本质：loop 只认服务契约与事件 seam。

## Links

- [DSH 主入口](/docs/CS/AI/LLM/Agent/Product/DSH/DSH.md)
- [DSH Agent Loop](/docs/CS/AI/LLM/Agent/Product/DSH/AgentLoop.md)
- [DSH Permission & Sandbox](/docs/CS/AI/LLM/Agent/Product/DSH/Permission.md)
- [DSH LLM Adapter & Context](/docs/CS/AI/LLM/Agent/Product/DSH/LlmAdapter.md)
- [MCP 协议](/docs/CS/AI/LLM/Protocol/MCP.md)

## References

1. [deepseek-ai/deepseek-harness（v0.2.2-rc.3）core/tools](https://github.com/deepseek-ai/deepseek-harness/tree/v0.2.2-rc.3/packages/core/tools)
2. [架构文档 — Tool execution pipeline](https://github.com/deepseek-ai/deepseek-harness/blob/v0.2.2-rc.3/docs/tool-execution-pipeline.md)
3. [cookbook: adding a tool](https://github.com/deepseek-ai/deepseek-harness/blob/v0.2.2-rc.3/docs/cookbook/adding-a-tool.md)
