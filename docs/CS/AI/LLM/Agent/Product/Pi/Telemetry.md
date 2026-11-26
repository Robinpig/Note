## Introduction

`pi-telemetry` 常被误读成「Pi 自带的 OpenTelemetry 封装」，其实它**没有任何 exporter、没有全局 current-span、也不依赖任何后端**：它只定义一套厂商中立的 span / metric 契约，附一个内存参考适配器、一个 noop 上下文、类型化 schema 工具和渲染器。应用可以把它桥到 OpenTelemetry / Sentry / 日志，也可以完全不用。本页按 v1.5.2（commit `b4afdddf`）源码核验。

三个先摆正的事实：① `startSpan()` 用**回调**持有 span 生命周期，没有公开的 `end()`；② schema 只在**编译期**约束名字与属性，`defineTelemetrySchema()` 是恒等函数、运行时零校验；③ noop 不是「记录后丢弃」，而是**共享的冻结空对象**，连参数都不读。

## Core Contract

契约只有两级：`TelemetryContext` 负责开根 span（宿主持有），`TelemetrySpan` 既是记录器、又是子 span 的显式父上下文。可选能力 `metrics` / `propagation` 挂在 context 上，并沿子 span 与提取出的父上下文传递；只用 `startSpan()` 的适配器也是合法的。

```ts
export interface TelemetryContext {
	/** Adapter capabilities remain available on child spans and extracted parents. */
	readonly metrics?: TelemetryMetrics;
	readonly propagation?: TelemetryPropagation;
	startSpan<T>(options: SpanOptions, callback: (span: TelemetrySpan) => T | Promise<T>): Promise<T>;
}

export interface TelemetrySpan extends TelemetryContext {
	addLink(link: SpanLink): void;
	addEvent(name: string, attributes?: SpanAttributes): void;
	setAttributes(attributes: SpanAttributes): void;
	setStatus(status: SpanStatus): void;
}
```

`StoredSpan` 才是与适配器无关的**已结算快照**：`startedMs` / `endedMs` 是 epoch 毫秒（微秒精度），事件时间是相对 span 开始的偏移。查询侧 `findTraces()` 支持最早 span 的名字、时间区间、`errors: true`、标量属性和 opaque cursor 分页。

```ts
export interface StoredSpan {
	readonly id: string;
	readonly traceId: string;
	readonly parentId?: string;
	readonly name: string;
	/** Wall-clock milliseconds since the epoch (`telemetryNow`). */
	readonly startedMs: number;
	readonly endedMs: number;
	readonly attributes: SpanAttributes;
	readonly events: readonly { readonly name: string; readonly timeMs: number; readonly attributes: SpanAttributes }[];
	readonly links: readonly {
		readonly traceId: string;
		readonly spanId: string;
		readonly attributes?: SpanAttributes;
	}[];
	readonly status: SpanStatus;
}
```

适配器契约是可观察语义而非继承规范：回调**同步恰好一次**、返回值/拒绝值原样保留、返回的 promise 结算前 span 保持打开、正常完成即 `ok`、抛错即 `error`（除非显式设置过）、`setStatus` 后写覆盖、`setAttributes` 合并且忽略 `undefined`、所有记录方法同步、结算后的调用惰性忽略。Pi 自己的代码**永远通过参数显式传父 span**，不依赖 `AsyncLocalStorage`——所以同一套代码能跑在 Node、Bun、浏览器和 worker 里。

## Typed Schema

底层 span API 故意开放名字与属性包，领域包则声明封闭 schema，再由类型系统推导精确属性。`defineTelemetrySchema()` 只是带泛型的恒等函数；`createTypedSpanStarter()` 为每个 span 名生成一个重载，`_schemas` 参数**只参与类型推导、运行时根本不读**：

```ts
export function defineTelemetrySchema<const T extends TelemetrySchemaDefinition>(schema: T): T {
	return schema;
}

/**
 * Bind an explicit parent context to the combined span vocabulary of one or more schemas.
 * Schema values are used only for type inference; no runtime schema validation is performed.
 */
export function createTypedSpanStarter<const Schemas extends TelemetrySchemaTuple>(
	telemetryContext: TelemetryContext,
	_schemas: Schemas & UniqueTelemetrySchemas<Schemas>,
): TypedSpanStarter<Schemas> {
	return bindTypedSpanStarter<Schemas>(telemetryContext);
}
```

`ExactTelemetryAttributes<Expected, Actual>` 用 `Record<Exclude<keyof Actual, keyof Expected>, never>` 拒绝多余键，配合 `RequiredAttributeNames` 把 `required: true` 的属性变成必填参数。多个 schema 可以用 `createTypedSpanStarter(ctx, [schemaA, schemaB])` 组合，字面量重复的 span 名在编译期就被 `DuplicateTelemetrySpanNames` 挡掉。

`startAttributes` 与 `endAttributes` **不是两套运行时存储**：前者在调用 starter 时传，后者通过 schema 限定的 `setAttributes()` 追加，都落进同一个属性包；end 属性永远可选，零次调用也合法（早失败与取消路径可能根本没有值）。"end" 只是「完成时的信息补充」，不负责结束 span——回调 return / resolve / throw / reject 才控制结算。

## Instruments

指标能力是 context 上的**可选** `TelemetryMetrics`，三种乐器：`counter.add()` / `upDownCounter.add()` / `histogram.record(value, attributes?, context?)`。第三个参数是 exemplar：把一次测量关联到当前 span；counter 没有 context 参数。边界 `boundaries` 只是给后端的提示，调用方保证有限且严格递增，后端可自行解释。

```ts
export interface TelemetryMetrics {
	counter(name: string, options?: InstrumentOptions): TelemetryCounter;
	upDownCounter(name: string, options?: InstrumentOptions): TelemetryUpDownCounter;
	histogram(name: string, options?: HistogramOptions): TelemetryHistogram;
}

export type TelemetryMetricDefinition = {
	description: string;
	unit?: string;
	attributes: Record<string, TelemetryMetricAttributeDefinition>;
} & ({ kind: "counter" | "upDownCounter"; boundaries?: never } | { kind: "histogram"; boundaries?: readonly number[] });
```

类型化指标与类型化 span 有一个关键差异：`createTypedMetrics()` **会在运行时读取并保留** schema 里的乐器元数据（description / unit / boundaries），但仍不做属性校验。`TelemetryMetricAttributeDefinition` 把 `cardinality` 限制为 `"low"`，且注释明确「不写基数注解不等于放宽策略」——请求 ID、用户 ID、prompt、任意路径都不该进指标属性。

```ts
export function createTypedMetrics<const Schemas extends MetricSchemas>(
	metrics: TelemetryMetrics,
	schemas: Schemas &
		([DuplicateMetricNames<Schemas>] extends [never]
			? unknown
			: { readonly "duplicate telemetry metric names": DuplicateMetricNames<Schemas> }),
): TypedTelemetryMetrics<Schemas> {
	const definitions = new Map<string, TelemetryMetricDefinition>();
	for (const schema of schemas) {
		for (const [name, definition] of Object.entries(schema.metrics ?? {})) definitions.set(name, definition);
	}
	return {
		counter: (name: string) => metrics.counter(name, definitions.get(name)),
		upDownCounter: (name: string) => metrics.upDownCounter(name, definitions.get(name)),
		histogram: (name: string) => metrics.histogram(name, definitions.get(name)),
	} as unknown as TypedTelemetryMetrics<Schemas>;
}
```

## In-Memory Reference

`InMemoryTelemetryContext` 是后端中立的参考实现，同时实现 context / propagation / metrics / store 四个角色。它没有 exporter、存储无上界、只在进程内——适合测试与本地诊断，不适合当生产后端。

时间戳不用裸 `Date.now()`。`telemetryNow()` 把单调的 `performance.now()` 锚到墙上时钟，两者偏差超过 10ms 才重新锚定，最后四舍五入到微秒；这样同一进程内既有单调顺序与微秒间距，又与墙上时间一致。注释说明它与 Chord 的 SQLite store 用同一时钟，两者时间戳可直接比较：

```ts
const TOLERANCE_MS = 10;

export function telemetryNow(): number {
	const clock = performance.now();
	const wall = Date.now();
	if (Math.abs(anchor + clock - wall) > TOLERANCE_MS) anchor = wall - clock;
	return microseconds(anchor + clock);
}
```

传播用的 carrier 是三个自描述字段：`pi-memory-scope`（每个 recorder 一个 UUID）、`pi-memory-span`（进程内递增 ID）、`pi-memory-trace`（根 span 的 `scope:id`，子 span 继承）。`contextCarriers` 是 `WeakMap<TelemetryContext, TelemetryCarrier>`，结算后仍可 inject 目标，但结算后的源 span 忽略 `addLink()`。

```ts
	context: {
		"pi-memory-scope": state.scope,
		"pi-memory-span": String(id),
		"pi-memory-trace": parent?.context["pi-memory-trace"] ?? `${state.scope}:${id}`,
	},
	parentContext: parent ? { ...parent.context } : null,
```

`final` 块里结算 span、记 `endedMs` 与递增的 `endSequence`；回调抛错时若没有显式状态，自动写 error。测量记录按 **10 秒区间**打戳，`findMetrics()` 把每条原始测量映射为 `count: 1` 的行——内存实现不做聚合，SQLite 适配器才按 series × interval 聚合：

```ts
	return (value, attributes, context) => {
		const carrier = context === undefined ? undefined : contextCarriers.get(context);
		state.measurements.push({
			intervalMs: Math.floor(Date.now() / 10_000) * 10_000,
			measurement: {
				...metadata,
				value,
				attributes: copyAttributes(attributes),
				context: carrier ? { ...carrier } : null,
			},
		});
	};
```

## Propagation

`inject()` 返回**分离的** carrier（调用方改它不影响内部），`extract()` 返回一个由接收方持有的父上下文；缺失或格式不认识的 carrier 一律回退到该适配器的 root，trace 元数据只做诊断关联、绝不当授权依据。carrier 只是 `Record<string, string>`，W3C `traceparent` / `tracestate` 也能塞进去，格式由适配器自己拥有。

```ts
export interface TelemetryPropagation {
	inject(context: TelemetryContext): TelemetryCarrier | undefined;
	/** Absent or unknown carriers use the root; recognized identifiers are opaque strings. */
	extract(carrier: TelemetryCarrier | undefined): TelemetryContext;
}
```

跨进程测试验证了「无需共享注册表」：调用方 inject 出 carrier，JSON 序列化后传给另一个 Node 进程；接收方的 span 有 `parentContext === carrier` 但 `parentId === null`（远端父），本地 ID 重新分配。`links` 是另一种关联——不改变父子关系，目标可以是已结算 span 或 extract 出来的远端父，`renderTrace()` 会把它打印为 `→ link trace ... span ...`。

## Noop

noop 是**单例冻结对象**，不是「分配一个 span 再丢掉」。所有方法都是空函数，连 `options` 都不看；嵌套 span 返回同一个 `noopTelemetrySpan`；propagation 的 `inject` 恒返回 `undefined`、`extract` 恒返回 noop context。这让「可选遥测」的调用路径没有分配开销，也让业务代码不必到处判空：

```ts
const noopCounter: TelemetryCounter = Object.freeze({ add: () => {} });
const noopUpDownCounter: TelemetryUpDownCounter = Object.freeze({ add: () => {} });
const noopHistogram: TelemetryHistogram = Object.freeze({ record: () => {} });

/** Shared instruments that never inspect or retain metadata, measurements, or contexts. */
export const NOOP_TELEMETRY_METRICS: TelemetryMetrics = Object.freeze({
	counter: () => noopCounter,
	upDownCounter: () => noopUpDownCounter,
	histogram: () => noopHistogram,
});
```

## Rendering

`renderTrace()` 在独立子路径 `@earendil-works/pi-telemetry/render`，不进根入口图。它把已结算 span 按 ID 去重、缺失父当根、按开始时间排成森林，打印属性、时长、错误、事件相对偏移和跨 trace link。因为 id / name / 错误消息可能来自别的进程（carrier），渲染前会把 C0/C1 控制字符和 DEL 全部转成 `\uXXXX`，属性值走 JSON：

```ts
const CONTROL = /[\u0000-\u001f\u007f-\u009f]/g;

/** `text` with every control character written as a `\uXXXX` escape. */
function escaped(text: string): string {
	return text.replace(CONTROL, (char) => `\\u${char.charCodeAt(0).toString(16).padStart(4, "0")}`);
}
```

## Adapter Conformance

`./testing` 子路径提供**测试框架无关**的一致性套件：它只返回 `{ group, name, run }` 数组，由 vitest 或任意框架注册。每个用例用 `await using` 从工厂拿一个全新适配器夹具，用例之间完全隔离；夹具是 `AsyncDisposable`，因此适配器可以先 flush 异步 exporter 再返回快照。

```ts
function createCase(
	factory: TelemetryAdapterFixtureFactory,
	group: string,
	name: string,
	test: ConformanceTest,
): TelemetryAdapterConformanceCase {
	return {
		group,
		name,
		async run() {
			await using fixture = await factory();
			await test(fixture);
		},
	};
}
```

套件覆盖能力身份（root / 子 span / 提取的父 / inert span）、同步单次回调、返回值与拒绝值身份、自动与显式状态、属性合并、事件顺序、结算后惰性、嵌套与并发父子关系、links；夹具提供 `propagation` / `metrics` 时追加 JSON roundtrip、多跳传播、未知 carrier 回退、测量顺序与 exemplar 检查。它**不测畸形输入、也不要求吞掉后端异常**。注意 testing 子路径用 Node 的 assertion API，根包保持运行时中立——这是它独立导出的原因，Pi 自己也用这套套件验证 `InMemoryTelemetryContext`。

## Corrections

| 常见误述 | 源码事实 |
| :--- | :--- |
| 这是 Pi 的 OpenTelemetry SDK / 会导出 OTLP | 没有任何 exporter；只是契约 + 参考实现，桥接由应用提供的适配器完成 |
| 有类似 `tracer.getCurrentSpan()` 的全局上下文 | 完全没有；父 span 通过参数显式传递，因此不依赖 `AsyncLocalStorage` |
| schema 会在运行时校验属性 | `defineTelemetrySchema()` 是恒等函数；类型化 starter 只做编译期约束，明确「no runtime schema validation」 |
| noop 会创建 span 然后丢弃 | 单例冻结空对象，嵌套仍是同一对象，不读也不用参数 |
| `findMetrics()` 返回聚合计数器 | 内存实现每条测量映射为 `count:1` 行；聚合是 SQLite 适配器的行为 |
| `endAttributes` 是独立的结束阶段数据 | 只是完成时的可选补充，落进同一个属性 bag，不负责结算 |
| 指标属性可以带 request ID 做高基数分析 | `TelemetryMetricAttributeDefinition.cardinality` 只允许 `"low"`，注释明确策略不因省略注解而放宽 |

## Links

- [Pi 枢纽](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md)
- [Durable：持久化运行时](/docs/CS/AI/LLM/Agent/Product/Pi/Durable.md)
- [Events：扩展事件总表](/docs/CS/AI/LLM/Agent/Product/Pi/Events.md)
- [AgentLoop：主循环](/docs/CS/AI/LLM/Agent/Product/Pi/AgentLoop.md)
- [Observability 理论](/docs/CS/AI/LLM/Agent/Theory/Observability.md)
- [Distributed Tracing](/docs/CS/Distributed/Tracing/Tracing.md)

## References

- [pi-telemetry README（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/telemetry/README.md)
- [契约与类型化 schema（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/telemetry/src/index.ts)
- [指标契约（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/telemetry/src/metrics.ts)
- [内存参考适配器（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/telemetry/src/memory.ts)
- [noop 上下文（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/telemetry/src/noop.ts)
- [渲染器（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/telemetry/src/render.ts)
