## Introduction

`ctx.llm` 是 DSH 的模型能力接缝：它把"选哪家模型"与"怎么发请求"解耦，并用**两段式 prepareCall** 把配置解析、adapter 绑定、能力快照压缩成一次原子提交。上下文装配（system prompt 分节 + 模型可见 context 注入）与前缀缓存策略都围绕这个 seam 展开。

> 版本基线：v0.2.2-rc.3（`E:/Projects/deepseek-harness-dsh-v0.2.2-rc.3`）。

几个反直觉的点：

- **`NO_ADAPTER` 在 loop 的 prepare 阶段被吞掉**，不是致命错误——middleware 可以为未注册路由提供响应（回放/模拟），但真正的 terminal dispatch 仍必须有 adapter。
- **`PreparedLlmCall.stream()` 是一次性消费品**：`dispatched` 标志让第二次调用直接抛 `INVALID_PREPARED_CALL`，且要求 options 与冻结 config 逐字段相等。
- **context 快照走 user 消息，不是 system 消息**：runtime-context / time-context / workspace instructions 都通过带来源归因的 user message 注入派生历史；system prompt 单独落成 `system/message`（surface node 0）。

## The llm/stream Waterfall and Types

`llm/stream` 是围绕每次流式调用的 waterfall——bound 到 `LlmRuntime`，调 `next()` 到 adapter 的 stream，或自己 yield chunk 短路（`packages/llm/llm/src/index.ts`）：

```ts
    'llm/stream'(this: LlmRuntime, options: GenerateOptions, next: () => AsyncIterable<StreamChunk>): AsyncIterable<StreamChunk>
```

LOOP 构造的请求带 `markAgentLoopRequest` 身份且深度冻结（改动抛错）——它的内容是 session log 的纯函数，监听器只读、绝不改写。StreamChunk 是原始流式协议（`packages/llm/llm/src/types.ts`）：

```ts
export type StreamChunk =
  | { type: 'block-start'; index: number; blockType: ContentBlockType }
  | { type: 'text-delta'; index: number; text: string }
  | { type: 'reasoning-delta'; index: number; text: string }
  | { type: 'tool-call-delta'; index: number; id: ToolCallId; name?: string; argumentsDelta: string }
  | { type: 'block-end'; index: number; block: ContentBlock }
  | { type: 'usage'; usage: TokenUsage }
  | { type: 'finish'; reason: FinishReason; replayState?: ReplayEnvelope }
```

adapter 的 throw / iterator 失败会在 runtime 归一化成终态 `error`/`aborted` finish chunk，而非 reject——所以 `for await` 正常结束不代表成功，必须检查 `finish.reason.kind`。

## Adapter Registration and Routing

`registerAdapter` 用 provider 名列表注册 adapter，路由增删在 `commitRoutes` 的单个同步段内完成（`packages/llm/llm/src/index.ts`）：

```ts
  registerAdapter(providers: string[], adapter: LlmAdapter): AdapterRegistrationHandle {
    const owned = new Set<string>()
    let released = false
    const dispose = this.ctx.effect(function* (this: LlmRuntime) {
      if (providers.length === 0) throw new LlmError('an adapter must register at least one provider', 'INVALID_ADAPTER')
      this.commitRoutes(owned, this.prepareRoutes(providers, adapter, owned))
      yield () => {
        released = true
        for (const provider of owned) this.adapters.delete(provider)
        owned.clear()
        this.emitAdaptersUpdated()
      }
    }.bind(this), 'llm.registerAdapter()')
```

注意空 providers 的语义前后有意不同：初次注册空列表抛 `INVALID_ADAPTER`，但 `handle.replace([])` 合法（配置段被清空但注册仍在、随时可挂回）。disposer 已运行后调用 `replace()` 抛 `REGISTRATION_DISPOSED`，靠独立 `released` 布尔判断（空 owned 集合无法区分"空注册"与"已释放"）。

## prepareCall: Two-Phase Commit

`prepareCall` 把"选择 adapter → 解析能力 → 绑定 stream"压缩成一次提交（`packages/llm/llm/src/index.ts`）：

```ts
  async prepareCall(config, signal?, configure?): Promise<PreparedLlmCall> {
    const { provider, model, ...controls } = config
    const registration = this.registration(provider)
    const adapterCall = await registration.adapter.prepareCall(provider, model, signal)
    const modelInfo = this.normalizeModelInfo(registration, model, adapterCall.model)
    // ...
    const resolvedConfig = deepFreeze(structuredClone(resolved.config))
    let dispatched = false
    return Object.freeze({
      config: resolvedConfig,
      retryPolicy: registration.retryPolicy,
      stream: (options: GenerateOptions): AsyncIterable<StreamChunk> => {
        if (dispatched) throw new LlmError('a prepared LLM call can only be dispatched once', 'INVALID_PREPARED_CALL')
        if (!callConfigEquals(options, resolvedConfig)) throw new LlmError('prepared LLM call config changed before adapter dispatch', 'INVALID_PREPARED_CALL')
        dispatched = true
        return this.streamWithRegistration(options, { registration, config: resolvedConfig, modelInfo, dispatch: options => adapterCall.stream(options) })
      },
    })
  }
```

`registration(provider)` 不存在即抛 `NO_ADAPTER`。agent loop 在 prepare 阶段吞掉它、回退到 proposedConfig——因为 `llm/stream` waterfall 的 middleware 可能提供未注册路由的响应；但 terminal dispatch 仍走 `streamWithRegistration`，那里再次解析 adapter。

为什么绑定在提交前？动态 adapter（如 pi-ai）的 `prepareCall` 读取"当前连接世代"的模型能力并返回闭包，把 endpoint 与 capability 绑成同一 generation——避免 HMR 期间"用 A 世代的能力打 B 世代的 endpoint"。源码注释直白：*so HMR cannot combine one adapter's capability result with another adapter*。

DeepSeek adapter 的 `generate()` 用 `AbortSignal.any` + idle watchdog，并把异常归一化（`packages/llm/llm-deepseek/src/adapter.ts`）：

```ts
  private async * generate(options, connection): AsyncGenerator<StreamChunk> {
    const consumer = new AbortController()
    const signal = options.signal === undefined ? consumer.signal : AbortSignal.any([consumer.signal, options.signal])
    using watchdog = idleWatchdog(signal, connection.streamIdleTimeoutMs, 'MESSAGES_IDLE')
    const iterator = this.request(options, connection, watchdog.signal, () => { watchdog.pulse() })
    try {
      while (true) {
        const next = await watchdog.next(iterator)
        if (next.done) return
        yield next.value
      }
    } catch (error) {
      if (timeoutOf(watchdog.signal, 'MESSAGES_IDLE') !== undefined) throw new LlmError('DeepSeek Messages stream idle timeout', 'TIMEOUT', { cause: error })
      // ...
    } finally {
      consumer.abort()
      void iterator.return(undefined).catch(() => {})
    }
  }
```

## System Prompt Assembly

`systemPrompt.assemble()` 把分节、context、工具 schema 汇总成一个 `PromptAssembly`，最后过 `system-prompt/assemble` waterfall（`packages/core/system-prompt/src/index.ts`）：

```ts
  async assemble(context: AssembleContext = {}): Promise<PromptAssembly> {
    const sectionByName = this.layers.merge(scope, layer => layer.sections)
    const contextByName = this.layers.merge(scope, layer => layer.contexts)
    // 收集工具 schema（projectToolSchema 白名单）
    const sectionDefinitions = [...sectionByName.values()].sort(comparePromptSections)
    const assembly: PromptPresentation = {
      sections,
      contexts: [...contextByName.values()].sort((a, b) => a.order - b.order).map(entry => resolveContext(entry, context)),
      variables,
    }
    const transformed = await this.ctx.waterfall(
      scopeTarget(this, scope), 'system-prompt/assemble', assembly, context,
      () => Promise.resolve(assembly),
    )
    return { ...transformed, tools }
  }
```

分节顺序表是硬编码的确定性排序（HARNESS_IDENTITY=-1000 … TOOL_SUBAGENT=2800 … HARNESS_SOURCE=10000），本地路径与端点排在可复用指令之后、不进缓存的系统提示词主体。只有当前执行器的 `describe()` 产出的 schema 进入 wire。

## Context Injection and Prefix Cache

runtime-context 把当前会话的快照投影成一条带来源的 user message，无变化则不注入（`packages/core/agent-loop/src/runtime-context.ts`）：

```ts
  project(sections: readonly ContextSnapshotSection[]): UserMessage | undefined {
    const previous = this.retained?.sections
    if (this.retained === undefined && sections.length === 0) return
    if (previous !== undefined && deepEqualJson(previous, sections)) return
    const snapshot = sections.length === 0
      ? CLEARED
      : `<\system-reminder>\n${intro}\n\n${body}\n<\/system-reminder>`
    return createUserMessage({ content: [{ type: 'text', text: snapshot }], source: { kind: SOURCE, form: 'snapshot', sections } })
  }
```

time-context 在 pre-step waterfall 里追加带来源的时间快照，受 refreshIntervalMs 节流（`packages/context/time-context/src/index.ts`）；working-directory 用 `required: true` 的 context 条目注入。

前缀缓存复用的前提是 system prompt + tools + 历史逐字节稳定。adapter 通过 `SystemPromptUpdate`/`ToolUpdate` 声明"历史内更新"能力：

```ts
export type SystemPromptUpdate = 'in-history'
export type ToolUpdate = 'in-history' | 'addition-only'
```

`'in-history'` 让变化跟在缓存历史之后而非改写 message 0；`deferLoading` + `tool-addition` 让新增工具走历史内追加。surface 的 `contentGeneration` 变化或工具列表变化时，loop 置 `startsSeries`、**主动切断前缀复用**并开新 series；pi-ai 的 `bindThinkingToPrefix` 还用 system+tools+消息的哈希链校验签名 thinking，前缀被改写就移除签名块，否则端点会整单拒绝。

## Links

- [DSH 主入口](/docs/CS/AI/LLM/Agent/Product/DSH/DSH.md)
- [DSH Agent Loop](/docs/CS/AI/LLM/Agent/Product/DSH/AgentLoop.md)
- [DSH Session & Persistence](/docs/CS/AI/LLM/Agent/Product/DSH/SessionPersistence.md)
- [DSH Tools & Capability Seams](/docs/CS/AI/LLM/Agent/Product/DSH/Tools.md)
- [DSH Context / Memory](/docs/CS/AI/LLM/Agent/Product/DSH/Context.md)

## References

1. [deepseek-ai/deepseek-harness（v0.2.2-rc.3）llm](https://github.com/deepseek-ai/deepseek-harness/tree/v0.2.2-rc.3/packages/llm/llm)
2. [架构文档 — Turn flow / Session log](https://github.com/deepseek-ai/deepseek-harness/blob/v0.2.2-rc.3/docs/architecture.md)
3. [cookbook: adding an LLM adapter](https://github.com/deepseek-ai/deepseek-harness/blob/v0.2.2-rc.3/docs/cookbook/adding-an-llm-adapter.md)
