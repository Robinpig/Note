## Introduction

本页记录 cc-haha v0.7.7 的遥测、诊断与成本追踪链路，以本地源码为基线区分「代码存在」与「公开版实际生效」。

> 版本基线：v0.7.7（本地源码 E:/Projects/cc-haha-0.7.7）

- `DATADOG_CLIENT_TOKEN` 在这份 release 快照里是空字符串，`initializeDatadog` 发送前直接判空返回，整套 Datadog sink 与 allowlist 代码都在，外发却默认不生效。
- `feature()` 来自 `bun:bundle`，是编译期 dead code elimination；analytics 的开关则是运行时 GrowthBook 动态配置、环境变量与 settings，两者常被混称 feature flag，机制却完全不同。
- `cost-tracker.ts` 不是 OTel trace，而是 bootstrap 累加器加终端格式化与 exit 钩子；本页点名的目标文件都不是 `@generated stub`，真正的占位出现在邻近同类命名的文件里。

## Event Entry And Sink Routing

`src/services/analytics/index.ts` 是无依赖的事件入口，刻意不 import 任何后端以避免循环；sink 挂载前事件进队列，挂载后用 `queueMicrotask` 排空。`logEvent` 的签名还禁止裸字符串，逼调用方用 `AnalyticsMetadata_I_VERIFIED_THIS_IS_NOT_CODE_OR_FILEPATHS` 显式声明没有代码或路径泄漏。

```typescript
export function logEvent(
  eventName: string,
  // intentionally no strings unless AnalyticsMetadata_I_VERIFIED_THIS_IS_NOT_CODE_OR_FILEPATHS,
  // to avoid accidentally logging code/filepaths
  metadata: LogEventMetadata,
): void {
  if (sink === null) {
    eventQueue.push({ eventName, metadata, async: false })
    return
  }
  sink.logEvent(eventName, metadata)
}
```

`src/services/analytics/sink.ts` 是真正的路由层：先按采样率丢弃，再决定 Datadog 与 1P 两条去向，并用 `stripProtoFields` 把 `_PROTO_*` 键从通用后端里剥掉，只有 1P 收到全量。

```typescript
function logEventImpl(eventName: string, metadata: LogEventMetadata): void {
  // Check if this event should be sampled
  const sampleResult = shouldSampleEvent(eventName)

  // If sample result is 0, the event was not selected for logging
  if (sampleResult === 0) {
    return
  }

  // If sample result is a positive number, add it to metadata
  const metadataWithSampleRate =
    sampleResult !== null
      ? { ...metadata, sample_rate: sampleResult }
      : metadata

  if (shouldTrackDatadog()) {
    // Datadog is a general-access backend — strip _PROTO_* keys
    // (unredacted PII-tagged values meant only for the 1P privileged column).
    void trackDatadogEvent(eventName, stripProtoFields(metadataWithSampleRate))
  }

  // 1P receives the full payload including _PROTO_* — the exporter
  // destructures and routes those keys to proto fields itself.
  logEventTo1P(eventName, metadataWithSampleRate)
}
```

整条链在测试环境、Bedrock / Vertex / Foundry / Azure 等第三方 provider 以及 privacy level 为 no-telemetry 时被整体关掉，见 `src/services/analytics/config.ts`：

```typescript
export function isAnalyticsDisabled(): boolean {
  return (
    process.env.NODE_ENV === 'test' ||
    isEnvTruthy(process.env.CLAUDE_CODE_USE_BEDROCK) ||
    isEnvTruthy(process.env.CLAUDE_CODE_USE_VERTEX) ||
    isEnvTruthy(process.env.CLAUDE_CODE_USE_FOUNDRY) ||
    isEnvTruthy(process.env.CLAUDE_CODE_USE_AZURE_OPENAI) ||
    isTelemetryDisabled()
  )
}
```

`src/services/analytics/sinkKillswitch.ts` 还提供按 sink 单独熔断的 GrowthBook JSON 配置，且注释强调它 fail-open：配置缺失或畸形时 sink 保持开启，并且不能在 `is1PEventLoggingEnabled` 内部调用以免递归。

```typescript
export function isSinkKilled(sink: SinkName): boolean {
  const config = getDynamicConfig_CACHED_MAY_BE_STALE<
    Partial<Record<SinkName, boolean>>
  >(SINK_KILLSWITCH_CONFIG_NAME, {})
  // getFeatureValue_CACHED_MAY_BE_STALE guards on `!== undefined`, so a
  // cached JSON null leaks through instead of falling back to {}.
  return config?.[sink] === true
}
```

## Backends And Sampling

`src/services/analytics/datadog.ts` 定义了 HTTP intake 端点、批量上限与刷新间隔，但客户端 token 是空字符串：

```typescript
const DATADOG_LOGS_ENDPOINT =
  'https://http-intake.logs.us5.datadoghq.com/api/v2/logs'
const DATADOG_CLIENT_TOKEN = ''
const DEFAULT_FLUSH_INTERVAL_MS = 15000
const MAX_BATCH_SIZE = 100
const NETWORK_TIMEOUT_MS = 5000
```

初始化守卫让这份快照里的 Datadog 分支直接短路，`DATADOG_ALLOWED_EVENTS` 白名单与 `flushLogs` 因此都只是「代码存在」而非「公开版在发」：

```typescript
export const initializeDatadog = memoize(async (): Promise<boolean> => {
  if (!DATADOG_CLIENT_TOKEN || isAnalyticsDisabled()) {
    datadogInitialized = false
    return false
  }
```

`src/services/analytics/firstPartyEventLogger.ts` 用 GrowthBook 动态配置 `tengu_event_sampling_config` 做按事件名采样，未出现在配置里的事件按全量记录：

```typescript
/**
 * Configuration for sampling individual event types.
 * Each event name maps to an object containing sample_rate (0-1).
 * Events not in the config are logged at 100% rate.
 */
export type EventSamplingConfig = {
  [eventName: string]: {
    sample_rate: number
  }
}

const EVENT_SAMPLING_CONFIG_NAME = 'tengu_event_sampling_config'
```

`src/services/analytics/firstPartyEventLoggingExporter.ts` 则把失败事件落到本地 JSONL，按进程 UUID 隔离，目录在运行时解析以尊重 `CLAUDE_CONFIG_DIR`：

```typescript
// Unique ID for this process run - used to isolate failed event files between runs
const BATCH_UUID = randomUUID()

// File prefix for failed event storage
const FILE_PREFIX = '1p_failed_events.'

// Storage directory for failed events - evaluated at runtime to respect CLAUDE_CONFIG_DIR in tests
function getStorageDir(): string {
  return path.join(getClaudeConfigHomeDir(), 'telemetry')
}
```

`src/utils/telemetry/bigqueryExporter.ts` 是真实的 `PushMetricExporter`，`src/utils/telemetry/instrumentation.ts` 组装 OpenTelemetry 的 tracer / meter / logger provider，`src/utils/telemetry/logger.ts` 把 OTel diag 转发到 `logForDebugging`。

## OpenTelemetry Tracing And Gates

`src/utils/telemetry/sessionTracing.ts` 的文件头直接写明它是 beta，且依赖编译期 gate：

```typescript
/**
 * Session Tracing for Claude Code using OpenTelemetry (BETA)
 *
 * This module provides a high-level API for creating and managing spans
 * to trace Claude Code workflows. Each user interaction creates a root
 * interaction span, which contains operation spans (LLM requests, tool calls, etc.).
 *
 * Requirements:
 * - Enhanced telemetry is enabled via feature('ENHANCED_TELEMETRY_BETA')
 * - Configure OTEL_TRACES_EXPORTER (console, otlp, etc.)
 */
```

`isEnhancedTelemetryEnabled` 的优先级是环境变量覆盖、ant build、GrowthBook gate；公开版在 `feature()` 为假时整段不进入。`src/utils/telemetry/betaSessionTracing.ts` 的 `isBetaTracingEnabled` 是另一套条件，它还要求 `ENABLE_BETA_TRACING_DETAILED` 与 `BETA_TRACING_ENDPOINT`，外部用户只能靠非交互模式或 `tengu_trace_lantern` 放行，`thinking_output` 更只对 ant 可见。

```typescript
export function isBetaTracingEnabled(): boolean {
  const baseEnabled =
    isEnvTruthy(process.env.ENABLE_BETA_TRACING_DETAILED) &&
    Boolean(process.env.BETA_TRACING_ENDPOINT)

  if (!baseEnabled) {
    return false
  }

  // For external users, enable in SDK/headless mode OR when org is allowlisted.
  // Gate reads from disk cache, so first run after allowlisting returns false;
  // works from second run onward (same behavior as enhanced_telemetry_beta).
  if (process.env.USER_TYPE !== 'ant') {
    return (
      getIsNonInteractiveSession() ||
      getFeatureValue_CACHED_MAY_BE_STALE('tengu_trace_lantern', false)
    )
  }

  return true
}
```

`src/utils/telemetry/perfettoTracing.ts` 更极端，文件头标注 ant-only 且从外部构建移除，初始化逻辑外面还套了一层注释明确的 DCE 包裹：

```typescript
  // Wrap in feature() for dead code elimination - entire block removed from external builds
  if (feature('PERFETTO_TRACING')) {
```

`isPerfettoTracingEnabled` 返回的 `isEnabled` 只在这个块内被置 true，所以外部构建里它恒为 false，尽管 `runAgent` 会调用它。用户提示词也默认脱敏，见 `src/utils/telemetry/events.ts`：

```typescript
function isUserPromptLoggingEnabled() {
  return isEnvTruthy(process.env.OTEL_LOG_USER_PROMPTS)
}

export function redactIfDisabled(content: string): string {
  return isUserPromptLoggingEnabled() ? content : '<REDACTED>'
}
```

## Generated Stubs And Feature Gates

必须把三类代码分开读。真实生效的是运行时链路：`analytics/index.ts`、`sink.ts`、`config.ts`、`sinkKillswitch.ts`、`firstPartyEventLogger.ts`、`firstPartyEventLoggingExporter.ts`、`growthbook.ts`、`metadata.ts`、`datadog.ts`，以及 `internalLogging.ts`、`diagnosticsService.ts`、`apiPerformanceMonitor.ts`、`cost-tracker.ts`、`costHook.ts`、`bigqueryExporter.ts`、`events.ts`、`instrumentation.ts`、`logger.ts`、`pluginTelemetry.ts`、`skillLoadedEvent.ts`。其中 `metadata.ts` 的部分字段仍带 `feature('COWORKER_TYPE_TELEMETRY')` 与 `feature('KAIROS')`，属于局部而非整模块关闭。

被 `feature()` 整段 gate 或标注 ant-only / 外部构建移除的是 `perfettoTracing.ts`、`sessionTracing.ts`，以及 `betaSessionTracing.ts` 里 ant-only 的 thinking 输出。条件生效但非编译期 gate 的是 `betaSessionTracing.ts` 的主体与 `firstPartyEventLogger.ts` 的采样。

本页点名的目标文件里没有一个是 `@generated stub`；占位出现在邻近同类命名的文件，例如 `src/services/skillSearch/telemetry.ts`、`src/services/skillSearch/featureCheck.ts`、`src/memdir/memoryShapeTelemetry.ts`、`src/utils/eventLoopStallDetector.ts`，以及引擎侧的 `src/coordinator/workerAgent.ts`。它们的形态一致：`scan-missing-imports` 生成、导出 noop Proxy、注释写明外部 build 经 DCE 后不会执行。

```typescript
// @generated stub from scan-missing-imports
// 该文件自动生成，对应 ant-internal 的 feature() gated 模块。
// 所有外部 build 的代码路径在 DCE 后都不会真的执行这里的代码，这只是
// bun build resolver 的占位符。
const __target = function noop() {}
const __handler: ProxyHandler<any> = {
  get(_t, prop) {
    if (prop === '__esModule') return true
    if (prop === 'default') return new Proxy(__target, __handler)
    if (prop === Symbol.toPrimitive) return () => undefined
    if (prop === Symbol.iterator) return function* () {}
    if (prop === Symbol.asyncIterator) return async function* () {}
    if (prop === 'then') return undefined
    return new Proxy(__target, __handler)
  },
```

`src/services/internalLogging.ts` 虽是真实文件，但 K8s namespace 与 container id 的采集在 `USER_TYPE !== 'ant'` 时直接返回 null，外部用户拿不到这些字段：

```typescript
const getKubernetesNamespace = memoize(async (): Promise<string | null> => {
  if (process.env.USER_TYPE !== 'ant') {
    return null
  }
```

## Diagnostics And API Performance

`src/server/services/apiPerformanceMonitor.ts` 是真实的性能采样器，记录慢请求、事件循环卡顿、CPU 与内存，并把长轮询路径排除在延迟统计外：

```typescript
const DEFAULT_SLOW_REQUEST_MS = 1_000
const DEFAULT_EVENT_LOOP_SAMPLE_MS = 1_000
const DEFAULT_EVENT_LOOP_STALL_MS = 500
const DEFAULT_STALL_REPORT_COOLDOWN_MS = 10_000
/** Requests that wait on purpose; their duration is not latency. */
const LONG_POLL_PATHS = new Set(['/api/sessions/mobile-push/pull'])
```

它的依赖可注入，默认落到 `diagnosticsService.recordEvent`，并用 `unref` 让定时器不阻止进程退出：

```typescript
  constructor(dependencies: MonitorDependencies = {}) {
    this.now = dependencies.now ?? (() => performance.now())
    this.cpuUsage = dependencies.cpuUsage ?? process.cpuUsage.bind(process)
    this.memoryUsage = dependencies.memoryUsage ?? process.memoryUsage.bind(process)
    this.recordEvent = dependencies.recordEvent ?? ((event) => diagnosticsService.recordEvent(event))
    this.scheduleInterval = dependencies.setInterval ?? globalThis.setInterval
    this.cancelInterval = dependencies.clearInterval ?? globalThis.clearInterval
    this.slowRequestMs = dependencies.slowRequestMs ?? DEFAULT_SLOW_REQUEST_MS
    this.eventLoopSampleMs = dependencies.eventLoopSampleMs ?? DEFAULT_EVENT_LOOP_SAMPLE_MS
    this.eventLoopStallMs = dependencies.eventLoopStallMs ?? DEFAULT_EVENT_LOOP_STALL_MS
    this.stallReportCooldownMs = dependencies.stallReportCooldownMs ?? DEFAULT_STALL_REPORT_COOLDOWN_MS
  }
```

`src/server/services/diagnosticsService.ts` 定义结构化诊断事件，带 severity、sessionId 与 details，并自带 `diagnosticRedaction` 脱敏、gzip 导出、retention 与字节上限、损坏行计数：

```typescript
export type DiagnosticSeverity = 'debug' | 'info' | 'warn' | 'error'

export type DiagnosticEventInput = {
  type: string
  severity?: DiagnosticSeverity
  summary: string
  sessionId?: string
  details?: unknown
}

export type DiagnosticEvent = {
  id: string
  timestamp: string
  type: string
  severity: DiagnosticSeverity
  summary: string
  sessionId?: string
  details?: unknown
}
```

两者都是本地可观测能力，不是 stub，也不依赖 `feature()` 编译期开关。

## Cost Tracking And Model Trace

`src/cost-tracker.ts` 从 `bootstrap/state.js` 取累加的 token、时长、行数与 `getModelUsage`，用 `calculateUSDCost` 算钱，再格式化成终端输出；`formatModelUsage` 按 `getCanonicalName` 聚合短名，命中未知模型时附「成本可能不准」提示。

```typescript
export function formatTotalCost(): string {
  const costDisplay =
    formatCost(getTotalCostUSD()) +
    (hasUnknownModelCost()
      ? ' (costs may be inaccurate due to usage of unknown models)'
      : '')

  const modelUsageDisplay = formatModelUsage()

  return chalk.dim(
    `Total cost:            ${costDisplay}\n` +
      `Total duration (API):  ${formatDuration(getTotalAPIDuration())}
Total duration (wall): ${formatDuration(getTotalDuration())}
Total code changes:    ${getTotalLinesAdded()} ${getTotalLinesAdded() === 1 ? 'line' : 'lines'} added, ${getTotalLinesRemoved()} ${getTotalLinesRemoved() === 1 ? 'line' : 'lines'} removed
${modelUsageDisplay}`,
  )
}
```

`src/costHook.ts` 用 React `useEffect` 挂 `process.on('exit')`，退出时按 billing 权限打印成本并 `saveCurrentSessionCosts` 落盘，这就是所谓 model trace 与成本追踪的主路径：

```typescript
export function useCostSummary(
  getFpsMetrics?: () => FpsMetrics | undefined,
): void {
  useEffect(() => {
    const f = () => {
      if (hasConsoleBillingAccess()) {
        process.stdout.write('\n' + formatTotalCost() + '\n')
      }

      saveCurrentSessionCosts(getFpsMetrics?.())
    }
    process.on('exit', f)
    return () => {
      process.off('exit', f)
    }
  }, [])
}
```

它随带一个 `logEvent('tengu_advisor_tool_token_usage', ...)` 事件，但这只是把 advisor 用量送进 analytics，并不是把每次模型调用做成分布式 trace。真正的 span 与 trace 在 `sessionTracing.ts` / `betaSessionTracing.ts`，且如前所述都被 gate 约束。

## Links

- [CcHaha 产品总览](/docs/CS/AI/LLM/Agent/Product/CcHaha/CcHaha.md)
- [Models](/docs/CS/AI/LLM/Agent/Product/CcHaha/Models.md)
- [REPL](/docs/CS/AI/LLM/Agent/Product/CcHaha/REPL.md)
- [Computer Use](/docs/CS/AI/LLM/Agent/Product/CcHaha/ComputerUse.md)
- [Claude Code](/docs/CS/AI/LLM/Agent/Product/ClaudeCode/ClaudeCode.md)
- [Agent 理论](/docs/CS/AI/LLM/Agent/Theory/Agent.md)

## References

- https://github.com/anthropics/claude-code
- https://docs.anthropic.com/en/docs/claude-code/overview
- https://opentelemetry.io/docs/
- https://ui.perfetto.dev/
- https://docs.datadoghq.com/
