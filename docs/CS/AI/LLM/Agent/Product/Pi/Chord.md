## Introduction

`chord` 是 Pi 仓库里最容易被低估的包：它不是 Pi 编码 agent 的组件，而是一套**让对象跨进程存在、并且插件能在运行中热替换**的应用组合运行时。`pi-durable` 的存储和 Harness 建立在它之上，`pi-env` 用它做远程守护进程，但 `coding-agent` **不依赖它**（见 [Pi 枢纽](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md)）。本页按 v1.5.2（commit `b4afdddf`）源码核验，规则以 `docs/design.md` + `docs/layer-1.md` + 真实源码为准。

先纠正一处最常见的地图误读：**Chord v2 的 `src/` 下没有 `service/` 或 `rpc/` 目录**。v1 的分层是 L1 数据 / L2 watch / L3 存储 / L4 对象 / L5 引用 / L6 link / L7 host / L8 routine / L9 registry，v2 已改成按垂直 slice 推进，源码布局是 `contracts/` `data/` `delta/` `documents/` `host/` `link/` `jobs/` `registries/` `remote/` `store/` `sync/` 等；旧内核（`src/next-frozen/`）从不导入、从不编辑。`docs/layer-2.md` 明确标了 `superseded`——它的 watch handle 部分仍有效，其余只是背景，**不要照它实现**。

另外三点：① 插件的 facet **只声明、不执行**，Chord 才激活；② 调用方拿到的是 **reference**，不是对象本身，reference 本地 / 跨 link 同形且会让对象保活；③ delta tracker **不是乐观并发**——prepare 不夺取权威，adopt 校验并换根指针，竞争 draft 直接变 `stale`。

## Contracts, Params and Identity

契约是对象类型的声明：名字、kind（`local` / `remote`）、version、params、members。schema 用 pi-schema 的 builder 写成普通 JSON Schema（L1 文档里关于 TypeBox 的描述是历史记录——2026-11-01 已切换）。`remote` 带 variants（可按 principal 做字段脱敏），`local` 是单一 `members` 映射；同一成员名在所有 variant 中必须是同种（state / method），方法签名也必须一致：

```ts
const Notes = remote("notes", {
  version: 1,
  params: { session: str() },
  variants: {
    editor: { state: { notes: arr(Note) }, methods: { add: method(obj({ text: str() }), str()), clear: method() } },
    reader: { state: { notes: arr(PublicNote) } },
  },
});
```

`obj()` 一律产出闭合对象（`additionalProperties: false`），方法参数的**每一层**对象都必须闭合——这是声明期检查，防止未知字段被静默吞掉。契约持有 schema 快照（声明时复制一次），品牌化（私有 `WeakMap`），手写或展开复制的对象会被 `evolve` / `checkAccepts` / `bindProvider` 拒绝。每个版本在声明时算一次 `hash64` 指纹：键排序、`required` / `enum` 排序，但 union / intersection / tuple **保序**（顺序即语义），注解丢弃而 default / format / pattern / bounds 保留；`NORMAL_FORM_VERSION = 2`，改格式即改 link 协议。

params 是扁平的必填字段（string / int / bool / 字符串字面量 union），`checkParams()` 用编译好的闭合对象检查，键按声明顺序取值、转义 `\` 与 `|` 后拼接；`identityKey()` = `name|paramsKey|principalKey`（local 无 principal）。每次调用都有 principal：link 负责打戳，应用定义类型，`principalKey()` 默认走 `canonicalJson()`（键排序、`-0` 写成 `0`），可用自定义函数但**所有 host 必须一致**，否则身份会静默分裂。`checkArgs()` 每次调用查三张表、跑一次编译检查、最多做一次 old→current 直接映射；无参方法传 `null`；结果和 state 从不检查。

契约演进用 `evolve(prev, e => e.state(...).args(...))` 追加版本；params 和 variant 集合不可演进（变了就是新历史基）。provider 可声明 `accepts` 表接受旧版本，映射是**直接映射、不链式**——升级到 v3 时每个仍接受的旧版本都要更新映射（组合成 `(old) => v2to3(v1to2(old))`）。`checkAccepts()` 是纯函数，只校验表不调用映射。

## Facets and Hosts

facet 是插件针对**某一个 host** 的声明文件，它 `serve` 契约类型与注册表、`contribute` 注册表值，仅此而已——**不含 documents / routines / natives，所以 load 之后 facet 不可能失败**：

```ts
// Facets (§16): a plugin's setup for one host, typed by the app's principal type. A setup only declares: the types and
// registries it serves, its contributions to registries (slice 8) and the host's presence lists; it has no documents,
// routines or natives, so a facet cannot fail after `load`.
export interface FacetHost<P extends Principal = Principal> {
	serve<C extends Contract>(Type: C, factory: Factory<C, P>, options?: ServeOptions<C>): void;
	serve<C, V>(R: Registry<C, V>, provider: RegistryProvider<C, V>): void;
	references<C extends Contract>(Type: C): Watchable<readonly Presence<C, P>[]>;
}
```

`ServeOptions` 里两个值得记：`accepts` 在声明处就校验（坏映射让 load / reload 直接失败），`linger` 是最后一个引用释放后对象继续存活的毫秒数（默认 0，期间新引用复用同一对象及其 documents 和依赖），`untraced: true` 关掉 `chord.method` span（telemetry ingest 自己调自己时会用它避免无限记录）。`host.serve` 同一注册表第二次声明会被拒绝。

`createHost()` 建 host，`host.load([...], context)` 加载 facet 列表，`host.get(Type, params, context)` 返回 **live reference**：state 有值、方法可调，`release()` 后最后一个引用释放才结束对象。方法调用必须传显式 `Context`（取消信号 + telemetry span），没有 ambient current span；`BACKGROUND_CONTEXT` / `TODO_CONTEXT` 用 no-op span。

## Links and Principals

link 是 host 之间的消息边界，内置 `memoryLinkPair` / `ipcLink` / `webSocketLink`；host origin 的 JSON part 超过 16 KiB 可用 `nodeCompression`（raw deflate）压缩。调用经 link 时 principal 由 link 打戳，wire 上传的是 params 本身而不是进程内 map key；版本在握手时比较 `PROTOCOL_VERSION = 1`，reason 与 code 的配对表也属协议——加一个 reason 必须升版本，有测试把表和版本钉在一起。错误统一为 `ChordError`（`code` / `reason` / `message` / `details`），`toJSON()` 不传 stack 和 cause，`chordErrorFromJson()` 在网络解码这个信任边界只校验信封，`details` 按引用保留不遍历。

## Delta: Transactional JSON Tracker

Delta 是 Chord 自己的 JSON 事务追踪器，独立于 `@earendil-works/chord/delta` 子路径导出。`track(initial)` 以 O(1) 取得无别名严格 JSON 根的所有权（不遍历、不冻结、不防御性复制——调用方承诺交出后不再改）：

```ts
const tracker = track({ output: "", count: 0 });
const change = tracker.beginChange();
change.state.output += "done\n";
change.state.count += 1;
const prepared = change.prepare();

tracker.adopt(prepared);
const replica = applyImmutable(prepared.base, prepared.ops);
```

`tracker.value` 永远指向最新采纳的不可变 revision。`beginChange()` 开 draft，`prepare()` 生成 ops 与新值但**不改变权威**，`adopt(prepared)` 校验（`baseRevision` 与 `#value` 一致性）后才做 O(1) 的根指针交换并把 revision +1；竞争 draft 被标 `stale`，外部仍持有其 proxy 也只会看到 stale 状态：

```ts
	adopt(prepared: Prepared<T>): void {
		const context = PREPARED.get(prepared as object);
		if (context?.owner !== this.#owner) throw new Error("Prepared change belongs to a different tracker");
		if (context.status.value === "consumed") throw new Error("Prepared change has already been used");
		if (context.status.value === "aborted") throw new Error("Prepared change has been aborted");
		if (context.status.value === "stale") throw new Error("Prepared change is stale");
		if (context.status.value !== "prepared") throw new Error("Prepared change is not ready");
		if (context.baseRevision !== this.#revision) {
			context.status.value = "stale";
			clearContext(context);
			throw new Error("Prepared change is stale");
		}

		if (this.#value !== prepared.base) {
			context.status.value = "stale";
			throw new Error("Prepared change is stale");
		}
		// Materialization happened during prepare. Adoption is an infallible pointer
		// swap so storage failure can discard the candidate without touching authority.
		this.#value = prepared.value;
		context.status.value = "consumed";
		this.#revision += 1;
		this.#invalidate(context);
	}
```

注释把设计意图讲得很直白：materialization 在 prepare 阶段就完成，adopt 是一次**不会失败的指针交换**，因此存储层失败可以丢弃候选而不碰权威数据。

数组变更用 piece tree（`PieceNode` 带 priority / elements，区分 base 数组与插入数组）做结构性增量，`diffRevisions(before, after)` 产出 `Op[]`，`applyImmutable(target, ops)` 把 ops 应用到副本；纯赋值的材料化走 `applyImmutableTrusted`，遇到 permutation / move op 才退回通用 `applyImmutable`。`appendText(draft, key, text)` 是专门的快路径：记录一个 append op 而**不比较新旧字符串**，普通 `draft[key] += text` 也能得到同样的 op，但 `prepare()` 要整串校验前缀，成本 O(length)。限制：tracker 只对无别名的严格 JSON 成立；发布出去的值不冻结，进程内消费者若原地改值就可能破坏权威——跨可变信任边界必须 clone 或序列化。

## Watchable and Derive

`Watchable<T>` 是统一观察接口：拿 `watch.value` 读当前值，`start(listener)` 后每个变更以 `(call, context)` 单次串行到达；`NativeWatchable<T>` 承载任意进程内值（函数、runtime），变更按 identity 判断、无 ops、**永远不能当契约 state 或上 wire**。变更在 listener 执行期间或 `start` 之前发生的会被折叠：JSON 取最新值并把 ops 用 `PendingOps` 折叠，超过 10,000 个 pending op 就退化成一次根替换 `[["r", newest]]`；native 超过 100 个 pending 值折叠成一个。failure 丢掉 pending 值、作为一次 `failed` 到达，后续值以 `[["r", value]]` 恢复。

`retired` 表示跟随的 document 被退役，但**不结束 watch**——这一帧带退役后的地址内容，之后同地址新建文档会以根替换到达。watch 只在 `stop()` / context abort / source end / listener 抛错 / source 永久失败时结束（`WatchEnd` 按 `kind` 区分），结束时清掉对 source 的全部引用。source 端用 `Watch<T>` / `NativeWatch<T>` 实现，`advance()` / `fail()` / `end()` / `endAfterDelivery()` 喂帧。

derive 是同步纯函数 `derive([sources], compute, publication)`，只在有消费者时挂载并在 flush 中按依赖秩重算；无消费者时读取才懒计算。`mapShared(f)` 用 WeakMap 记住元素结果，让 2000 条列表里改一条只产生一个 op。L2 规范虽已 superseded，「decided while specifying」一节仍有效：watchable state 只许 JSON（bytes 只在方法参数 / 结果中出现），一个 host 一个 publication（非模块单例），wire **不用 CBOR**（JSON + 原始字节段）。

## Reload

 reload 是 Chord 区别于普通插件系统的核心：**代码替换不改 host 身份**。每个插件版本是一组 attempt，新版本按 host 逐个 rollout；旧 work 在新的 attempt 上启动，旧 attempt drain 完后退出，data / 连接 / 正在跑的 work 尽量存活。规则「reload restarts every affected object; old work finishes on old code」被 `ReloadCycles` 强制：如果一段旧 work 等待的是某个 activation，而那个 activation 又通过 parked 依赖或 gate 反向等待这段旧 work 自己所在的 attempt，就构成死锁环，立刻以 `unavailable/reload_cycle` 失败（等开始时查一次，之后每次 park 或 gate 等待再查）。

## Entry Points and Boundaries

Chord 的入口按运行环境切分，可选 peer 依赖只出现在对应入口：`@earendil-works/chord`（核心，Node + 浏览器）、`/http`（fetch handler + 安全基线 + links endpoint，Node）、`/workers`（fork worker per address、按需启停）、`/plugins`（esbuild 构建 / watcher / rollout）、`/app`（startServer / startWorker / 会话与配对）、`/surfaces` `/web` `/react` `/tui`（web / 终端 UI）、`/context`（显式取消与 telemetry）、`/delta`、`/sqlite` `/sqlite/node` `/sqlite/cloudflare`、`/telemetry-sqlite`、`/sync`（实验性 outbox 同步）。`esbuild` / `ws` / `react` 只在需要它们的子路径导入。

它和 Pi 遥测层的接缝是 `TelemetryContext`：`Context` 总带 `telemetry: TelemetrySpan`，`withTelemetry(span, context)` 派生新 context，`traceIn()` 建 callback 管理的子 span；README 明确这些 helper **尚未 instrumentChord 的 host / method / 网络帧**。`/telemetry-sqlite` 适配器每秒事务性 flush 已结算 span 与完成的 10 秒指标区间，保留 7 天、队列上限 1 万 span，溢出计 `droppedSpans` / `droppedMeasurements`；它实现 `TelemetryStore`，`findTraces` / `findMetrics` 读已提交行，与 [Telemetry](/docs/CS/AI/LLM/Agent/Product/Pi/Telemetry.md) 的契约完全对接。

## Corrections

| 常见误述 | 源码事实 |
| :--- | :--- |
| Chord v2 = Context / Service / RPC / facet 四层，有 `service/` `rpc/` 目录 | 源码没有这两个目录；v1 的 L1–L9 已被 vertical slices 取代，旧内核 `next-frozen/` 不导入 |
| facet 是插件的可执行部分，load 后还能失败 | facet **只声明** types / registries / contributions，不含 documents / routines / natives，load 后不会失败 |
| `host.get()` 返回对象本身 | 返回 live reference，本地与跨 link 同形，最后一个引用 release 才结束对象（可配 linger） |
| Delta tracker 是乐观并发控制 | prepare 不夺取权威，adopt 校验 baseRevision + base 后换根；竞争 draft 标 stale |
| tracker 会冻结 / 深拷贝数据保证安全 | 信任不可变所有权，不遍历不冻结；原地改发布值会破坏权威 |
| `retired` 会结束 watch | 只表示文档退役，watch 继续；同地址新建文档以根替换到达 |
| watchable 可以带 bytes | watchable state 只允许 JSON；bytes 只在方法参数 / 结果和分块传输中出现 |
| wire 用 CBOR 编码 | JSON + 原始字节段；文档明确「no CBOR」，仅在基准显示瓶颈时才重议 |
| reload 会杀掉旧 work | 旧 work 在旧 attempt 上跑完；只有形成自等待环时才以 `unavailable/reload_cycle` 立即失败 |
| `docs/layer-2.md` 是可实现规范 | 已标 superseded，只有「Decided while specifying」与共享 watch handle 仍有效 |

## Links

- [Pi 枢纽](/docs/CS/AI/LLM/Agent/Product/Pi/Pi.md)
- [Telemetry：类型化契约](/docs/CS/AI/LLM/Agent/Product/Pi/Telemetry.md)
- [Schema：无 eval 校验](/docs/CS/AI/LLM/Agent/Product/Pi/Schema.md)
- [Durable：持久化运行时](/docs/CS/AI/LLM/Agent/Product/Pi/Durable.md)
- [Env：远程执行环境](/docs/CS/AI/LLM/Agent/Product/Pi/Env.md)

## References

- [Chord README（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/chord/README.md)
- [Chord design：规则唯一来源（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/chord/docs/design.md)
- [L1 data and contracts 规范（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/chord/docs/layer-1.md)
- [Slice plan（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/chord/docs/slices.md)
- [Facet 声明（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/chord/src/host/facet.ts)
- [Delta tracker（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/chord/src/delta/tracker.ts)
- [Reload cycle 检测（v1.5.2）](https://github.com/earendil-works/pi/blob/v1.5.2/packages/chord/src/host/reload-cycle.ts)
