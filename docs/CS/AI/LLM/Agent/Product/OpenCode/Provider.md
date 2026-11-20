> 版本基线：v1.19.5（`E:/Projects/opencode-1.19.5` release 源码快照）。本文以 **legacy Provider**（`packages/opencode/src/provider/provider.ts`，标识 `@opencode/Provider`，session 主链路用它）为主线，V2（`packages/core/src/provider.ts` + `aisdk.ts` + `catalog.ts`，标识 `@opencode/v2/*`）作为对照。

## Introduction

OpenCode 的"模型无关"不是靠一个统一网络协议，而是靠四层接缝把 provider 差异关在局部：配置层把 provider/model 归约成统一 Info、SDK 适配层把包名映射成 AI SDK 的 `LanguageModelV3`、payload 转换层按 provider 种类改写参数、事件标准化层把任何 runtime 的输出都收敛为 `LLMEvent`。

几个反直觉点：

- **`@opencode-ai/openai-compatible` 这个包不存在**（全库零命中）：真实分发名是 `@ai-sdk/openai-compatible`。`@opencode-ai/*` 是 opencode 自家包名前缀，与 `@ai-sdk/*` 是两回事。
- **`small_model` 的真实用途只有会话标题生成**，压缩走独立的 compaction agent，不是"全局自动用便宜模型"。
- **凭据双轨制**：provider 主链路读 `auth.json`，而 core 另有一套 SQLite 的 `Credential` 服务，目前主链路不用后者。
- **重试不在调用层而在会话处理层**：`llm.ts` 只把 `retries` 传给 `streamText` 的 `maxRetries`（默认 0），真正的 5 次指数退避在 `processor.ts`；context-overflow 明确不重试，转成压缩。

## The Provider Abstraction

抽象核心是一个 tagged union `Provider.Api = AISDK | Native`（`packages/schema/src/provider.ts`）。"用哪个 SDK"被降级为模型上的一个字符串包名 `api.npm`：

```typescript
export const AISDK = Schema.Struct({
  type: Schema.Literal("aisdk"),
  package: Schema.String,
  url: Schema.String.pipe(optional),
  settings: Schema.Record(Schema.String, Schema.Unknown).pipe(optional),
}).annotate({ identifier: "Provider.AISDK" })

export const Api = Schema.Union([AISDK, Native])
  .pipe(Schema.toTaggedUnion("type"))
  .annotate({ identifier: "Provider.Api" })
```

`provider.ts` 用一张 `BUNDLED_PROVIDERS` 表把包名映射到 AI SDK 工厂函数：

```typescript
const BUNDLED_PROVIDERS: Record<string, () => Promise<(opts: any) => BundledSDK>> = {
  "@ai-sdk/anthropic": () => import("@ai-sdk/anthropic").then((m) => m.createAnthropic),
  "@ai-sdk/google": () => import("@ai-sdk/google").then((m) => m.createGoogleGenerativeAI),
  "@ai-sdk/openai": () => import("@ai-sdk/openai").then((m) => m.createOpenAI),
  "@ai-sdk/openai-compatible": () => import("@ai-sdk/openai-compatible").then((m) => m.createOpenAICompatible),
  "@openrouter/ai-sdk-provider": () => import("@openrouter/ai-sdk-provider").then((m) => m.createOpenRouter),
  // ... 二十余个
}
```

接自定义 OpenAI-compatible provider 有三条路：models.dev 数据里 `npm` 缺省时 fallback 到 `@ai-sdk/openai-compatible`；用户 config 的 `provider.<id>.models.<model>.provider.npm` 指定；任意未内置的包走 `Npm.add()` 动态安装后 `import`，反射找 `create*` 导出。`resolveSDK()` 完成 baseURL 的 `${ENV_VAR}` 插值、apiKey 注入、超时包装，并按 hash 缓存实例：

```typescript
const bundledLoader = BUNDLED_PROVIDERS[model.api.npm]
if (bundledLoader) {
  const factory = await bundledLoader()
  const loaded = factory({ name: model.providerID, ...options })
  s.sdk.set(key, loaded)
  return loaded as SDK
}
const installedPath = await (async () => {
  if (model.api.npm.startsWith("file://")) return model.api.npm
  const item = await Npm.add(model.api.npm)
  if (!item.entrypoint) throw new Error(`Package ${model.api.npm} has no import entrypoint`)
  return item.entrypoint
})()
const mod = await import(installedPath.startsWith("file://") ? installedPath : pathToFileURL(installedPath).href)
const fn = mod[Object.keys(mod).find((key) => key.startsWith("create"))!]
```

## Model Resolution and the Catalog

`provider/model` 按第一个 `/` 切分（`parseModel()` / V2 的 `ModelV2.parse()`）。`getModel(providerID, modelID)` 取不到时用 `fuzzysort` 做名字建议并抛 `ModelNotFoundError`；`getLanguage(model)` 经 `resolveSDK` 拿到 SDK，再经 `modelLoaders[providerID]`（custom 钩子，决定 `responses` 还是 `chat`）或 `sdk.languageModel(model.api.id)` 得到 LanguageModelV3，按 `providerID/modelID` 缓存。

模型列表的源头是 **models.dev 的镜像** `https://models.opencode.ai/api.json`，不是代码内置 catalog。缓存落盘到 `Global.Path.cache/models.json`，TTL 5 分钟、后台每 60 分钟刷新，用跨进程 `Flock` 防竞争；可用 `OPENCODE_MODELS_URL` / `OPENCODE_MODELS_PATH` / `OPENCODE_DISABLE_MODELS_FETCH` 覆盖。过滤在状态 finalize 时：

```typescript
for (const [modelID, model] of Object.entries(provider.models)) {
  model.api.id = model.api.id ?? model.id ?? modelID
  if ((modelID === "gpt-5-chat-latest" && (providerID === ProviderV2.ID.openai || /* ... */))) delete provider.models[modelID]
  if (model.status === "alpha" && !runtimeFlags.enableExperimentalModels) delete provider.models[modelID]
  if (model.status === "deprecated") delete provider.models[modelID]
  if ((configProvider?.blacklist && configProvider.blacklist.includes(modelID)) ||
      (configProvider?.whitelist && !configProvider.whitelist.includes(modelID)))
    delete provider.models[modelID]
}
```

`small_model` 的优先级：`cfg.small_model` → plugin hook `experimental.provider.small_model` → family 启发式 `["gemini-flash","gpt-nano","claude-haiku"]`。实际调用点只有会话标题生成——`session/prompt.ts` 用 `agents.get("title")` + `small: true`：

```typescript
const ag = yield* agents.get("title")
if (!ag) return
const mdl = ag.model
  ? yield* provider.getModel(ag.model.providerID, ag.model.modelID)
  : ((yield* provider.getSmallModel(input.providerID)) ??
    (yield* provider.getModel(input.providerID, input.modelID)))
const text = yield* llm.stream({
  agent: ag, user: firstInfo, system: [], small: true, tools: {}, model: mdl,
  sessionID: input.session.id, retries: 2,
  messages: [{ role: "user", content: "Generate a title for this conversation:\n" }, ...msgs],
}).pipe(Stream.filter(LLMEvent.is.textDelta), Stream.map((e) => e.text), Stream.mkString, Effect.orDie)
```

`small: true` 进入 `llm/request.ts` 后，让 OpenAI/xAI 系注入 `store: false`、Venice 注入 `disableThinking`。V2 `Catalog.model.small()` 是另一套（按 cost/age 打分 + `/\b(nano|flash|lite|mini|haiku|small|fast)\b/`），对 azure 返回 undefined、对 opencode 硬编码 `gpt-5-nano`——两套结论可能不同。

## Credentials and OAuth

Legacy 凭据落在 `Global.Path.data/auth.json`（文件权限 `0o600`），由 `Auth.Service` 用 `FSUtil.readJson/writeJson` 读写；`OPENCODE_AUTH_CONTENT` 可整体覆盖（便于 CI）。结构是 tagged union：`Oauth {refresh, access, expires}` / `Api {key}` / `WellKnown {key, token}`：

```typescript
const OAUTH_DUMMY_KEY = "opencode-oauth-dummy-key"
const file = path.join(Global.Path.data, "auth.json")

export class Oauth extends Schema.Class<Oauth>("OAuth")({
  type: Schema.Literal("oauth"), refresh: Schema.String, access: Schema.String,
  expires: NonNegativeInt,
  accountId: Schema.optional(Schema.String),
  enterpriseUrl: Schema.optional(Schema.String),
}) {}
```

OAuth 的登录入口由**插件的 `auth.provider` 钩子**提供。`authorize()` 存 per-provider `pending`，`callback()` 取出后按 `code`/`auto` 调 `match.callback(...)`，成功结果为 key 就 `auth.set(api)`，含 refresh 就 `auth.set(oauth)`：

```typescript
const result = yield* Effect.promise(() =>
  match.method === "code" ? match.callback(input.code!) : match.callback(),
)
if (!result || result.type !== "success") return yield* new OauthCallbackFailed({})
if ("key" in result) {
  yield* auth.set(input.providerID, { type: "api", key: result.key,
    ...(result.metadata ? { metadata: result.metadata } : {}) })
}
if ("refresh" in result) {
  const { type: _, provider: __, refresh, access, expires, ...extra } = result
  yield* auth.set(input.providerID, { type: "oauth", access, refresh, expires, ...extra })
}
```

`packages/core/src/oauth/page.ts` 提供本地回环 HTTP 回调服务的品牌化 HTML（含 implicit-grant 的 bootstrap 脚本，把 URL fragment 的 token POST 回 `tokenPath`）。Copilot 凭据走 `createOpenaiCompatible`，API key 以 `Bearer` header 注入。

## LLM Stream and Event Standardization

`session/llm.ts` 的 `run()` 并发取四样东西（language / config / provider / auth），交给 `LLMRequestPrep.prepare()` 生成 system/messages/tools/params/headers（含 `chat.params`、`chat.headers`、`chat.system.transform` 插件钩子）。`stream()` 用 `Stream.scoped/unwrap` 包一层 `AbortController`，把 `result.fullStream` 经 `LLMAISDK.toLLMEvents(state, event)` 转成统一 `LLMEvent`：

```typescript
const result = yield* run({ ...input, abort: ctrl.signal })
if (result.type === "native") return result.stream
// Adapter seam: both runtimes expose the same LLMEvent stream.
const state = LLMAISDK.adapterState()
return Stream.fromAsyncIterable(result.result.fullStream, (e) =>
  e instanceof Error ? e : new Error(String(e)),
).pipe(
  Stream.mapEffect((event) => LLMAISDK.toLLMEvents(state, event)),
  Stream.flatMap((events) => Stream.fromIterable(events)),
)
```

`ai-sdk.ts` 的 `toLLMEvents` 是穷尽 switch：`text-delta` → `LLMEvent.textDelta`、`tool-call` → `LLMEvent.toolCall`（维护 id→name 映射）、`finish-step` 检查 `network_error`、`raw` 里抽取 Copilot 的 `copilot_usage.total_nano_aiu` 计费字段；`abort`/`source`/`file` 等直接吞掉：

```typescript
case "tool-call":
  return Effect.sync(() => {
    state.toolNames[event.toolCallId] = event.toolName
    return [LLMEvent.toolCall({
      id: event.toolCallId, name: event.toolName, input: event.input,
      providerExecuted: "providerExecuted" in event ? event.providerExecuted : undefined,
    })]
  })
```

**重试在 `processor.ts`**：流经 `Stream.tap(handleEvent)` → `runDrain`，外层 `Effect.retry(SessionRetry.policy({...}))`。`session/retry.ts` 定义指数退避（初始 2s、因子 2、jitter 0.25、无 header 上限 30s、最多 5 次），优先遵守 `retry-after-ms`/`retry-after`；`retryable()` 用正则判断 429/5xx/rate limit/overloaded 等，context overflow 明确不重试。

## Two Runtimes

`OPENCODE_EXPERIMENTAL_NATIVE_LLM`（伞形 `OPENCODE_EXPERIMENTAL`）打开时走 `@opencode-ai/llm` 原生 route 运行时，有一道 gate 白名单：

```typescript
const providerID = input.model.providerID
if (providerID !== "openai" && providerID !== "anthropic" && !providerID.startsWith("opencode"))
  return { type: "unsupported", reason: "provider is not openai, opencode, or anthropic" }
const npm = input.model.api.npm
if (npm !== "@ai-sdk/openai" && npm !== "@ai-sdk/openai-compatible" && npm !== "@ai-sdk/anthropic")
  return { type: "unsupported", reason: "provider package is not OpenAI, OpenAI-compatible, or Anthropic" }
```

原生 runtime 的 `LLM.stream` 只跑一个 provider turn，工具调用由调用方显式 `ToolRuntime.dispatch` 并自己构造下一轮请求（dispatcher "does not count steps, or continue model rounds"）。`packages/llm/AGENTS.md` 明确："`LLM.stream(request)` and `LLM.generate(request)` each run exactly one provider turn." V2 runner 也遵循这条——详见 [SessionLoop](/docs/CS/AI/LLM/Agent/Product/OpenCode/SessionLoop.md)。

## Why Model-Agnostic Works

模型无关性靠四层接缝：① 所有 provider 归约为 `Provider.Info {api, request}` 与 `Model.Info {api, capabilities, cost, limit}`；② SDK 适配层把包名映射成统一的 LanguageModelV3，`@ai-sdk/openai-compatible` 让任意兼容端点复用同一实现；③ payload 转换层 `ProviderTransform.providerOptions()` 按 npm 种类分派 reasoning gate（openai/azure/bedrock-mantle → `forceReasoning`；gateway → 拆分命名空间）；④ 事件标准化层都产出 `LLMEvent`，下游不关心 runtime/provider。本地端点只需在 config 里给 `npm: @ai-sdk/openai-compatible` + baseURL + models，无需改代码。

## Links

- [SessionLoop](/docs/CS/AI/LLM/Agent/Product/OpenCode/SessionLoop.md) / [Tools](/docs/CS/AI/LLM/Agent/Product/OpenCode/Tools.md) / [Context](/docs/CS/AI/LLM/Agent/Product/OpenCode/Context.md)
- [Plugin](/docs/CS/AI/LLM/Agent/Product/OpenCode/Plugin.md) / [Agent](/docs/CS/AI/LLM/Agent/Product/OpenCode/Agent.md) / [OpenCode](/docs/CS/AI/LLM/Agent/Product/OpenCode/OpenCode.md)

## References

1. [provider/provider.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/provider/provider.ts)
2. [schema/provider.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/schema/src/provider.ts)
3. [session/llm.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/session/llm.ts)
4. [session/llm/ai-sdk.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/session/llm/ai-sdk.ts)
5. [session/retry.ts](https://github.com/anomalyco/opencode/blob/v1.19.5/packages/opencode/src/session/retry.ts)
