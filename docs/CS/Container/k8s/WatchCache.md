## Introduction

Kubernetes 的每个组件都在做同一件事：从 apiserver 读一份自己关心的事物的副本，然后反复对账。scheduler 读 Pod 与 Node，kubelet 读自己节点上的 Pod，每个 controller 读自己负责的资源。这些订阅加起来规模很大——一个中等集群里同时活跃的 informer 动辄上万个。

如果每个 informer 都直连 etcd，etcd 几秒内就会被打垮。所以 apiserver 在读路径上插了一层缓存：**watch cache**。它做的事情可以一句话概括：

> **把"N 个订阅者"收敛成"1 条到 etcd 的 watch"。**

注意收敛点是**资源类型**，不是集群规模、也不是 informer 数量。一个 group-resource 只有**一个** `Cacher`、**一条**到 etcd 的 watch（`staging/src/k8s.io/apiserver/pkg/storage/cacher/cacher.go`）。几万个 informer 对应的是 Cacher 内部的几万个 `cacheWatcher`，它们是纯内存结构。

| | 没有 watch cache | 有 watch cache |
|---|---|---|
| 1 万个 informer 的初始 List | 1 万次 etcd range | 命中内存 btree，etcd 零请求 |
| 1 万个 informer 的 watch | 1 万条 etcd watch 流 | **1 条** |
| 对象变更的扇出 | etcd 自己做 fan-out | apiserver 内存 fan-out |
| 扩容的瓶颈 | etcd 连接数与请求 QPS | apiserver 内存与 CPU |

这条链路同时是前面几篇笔记的隐形底座：写请求落库后的通知、调度器看到 Pod 更新、kubelet 感知删除，全都建立在这里描述的机制上。

> [!NOTE]
> 本文全部结论基于 **Kubernetes v1.37.2** 源码实读，各处只标注文件路径。v1.37 相比 v1.36 在这一层有一处结构性拆分（环形缓冲独立成 `watch_cache_history.go`）和一处 gate 退役（`ResilientWatchCacheInitialization` GA 后移除），统一收在文末「v1.37 纠偏清单」。

---

## Segment 1: Before the Read Request Comes — Where the Cache Should Be

apiserver 的存储栈自上而下是：REST handler → registry store → **CacheDelegator** → Cacher 或 etcd。

关键点是这一层**不是**"先查缓存、miss 再查 etcd"那种缓存。它更像一个**分流器**：一部分请求由内存服务，另一部分直接透传到 etcd，判断依据写在 `ShouldDelegateList` 里（`cacher/delegator/interface.go`）。

| `ResourceVersionMatch` | 其他条件 | 走哪 |
|---|---|---|
| `Exact` | — | 看缓存是否有对应快照，否则 etcd |
| `NotOlderThan` | — | **不委托**，缓存处理 |
| 空 | 带 `Continue` | 看 token 里的 RV |
| 空 | `Limit>0` 且 RV 非空非 0 | legacy exact 语义 |
| 空 | RV 为空 | 一致性读 |
| 其他 | — | 委托 etcd |

> [!TIP]
> `LabelSelector` / `FieldSelector` **不参与**这个决策。它们由缓存层自己过滤——`store.Element` 在写入时就把 labels/fields 算好存在一起，`GetList` 里直接拿来做预过滤。这也是为什么 selector 不会把请求"打穿"到 etcd。

真正的实现类型是 `*CacheDelegator`（`cacher/delegator.go`），它同时持有 cacher 与 `storage.Interface`（即 `*etcd3.store`），两个都能服务。取不到结果时会回退：

- 缓存返回 `ResourceExpired` 且 `ListFromCacheSnapshot` 开启 → 回退 etcd
- 一致性读返回 `IsTooLargeResourceVersion` → 回退 etcd

---

## Segment 2: watchCache Core — A Self-resizing Sliding Window

v1.37 把历史缓冲拆成了独立类型：`watchCache`（`watch_cache.go`）负责当前状态与新鲜度等待，`watchCacheHistory`（`watch_cache_history.go`）持有事件序列。整体由三部分组成：

| 组成 | 位置 | 作用 |
|---|---|---|
| 当前状态 | `watchCache` 的 btree（`store.Indexer`） | 内存索引，存对象**当前**的样子 |
| 历史事件 | `watchCacheHistory.cache []*watchCacheEvent` + `startIndex` / `endIndex` | 环形缓冲，存事件**序列** |
| 推进位置 | `watchCache.resourceVersion uint64` | 缓存已追上的 RV |

前两者解决的是两类不同的请求：List 要"现在有什么"，watch 要"从 RV X 之后发生了什么"。

### The Ring Buffer Is Not Fixed Capacity

老版本的 `--default-watch-cache-size`（默认 100）常说成"缓存能存 100 个事件"，现在不是这样了：

```go
// watch_cache_history.go
defaultLowerBoundCapacity = 100        // 只是下界
defaultUpperBoundCapacity = 100 * 1024 // 上界
```

`watchCacheHistory.resizeCacheLocked` 按需伸缩：缓冲满且所有事件都还在期望保留时长内 → 容量翻倍（封顶上界）；满但最近 1/4 窗口外的事件已超出期望时长 → 容量减半（保护下界，避免抖动）。

期望保留时长是 `eventFreshDuration`，默认 **75 秒**（`cacher.go`：`DefaultEventFreshDuration = defaultBookmarkFrequency + 15*time.Second`）。上界由它推算：75s 及以内固定 102400，更大时按 2 的幂放大。

写入用取模落位，`startIndex` / `endIndex` 是**事件序号**，跟 RV 没有算术关系——RV 由 etcd 保证单调，序号只是"第几个事件"。

### Too-old RV Will Be Explicitly Rejected

"从 RV X 开始 watch"时，X 可能已经不在缓冲里了。判定在 `watchCacheHistory.GetIntervalLocked`（摘录）：

```go
func (w *watchCacheHistory) GetIntervalLocked(resourceVersion uint64, listResourceVersion uint64, locker sync.Locker) (*watchCacheInterval, error) {
	size := w.endIndex - w.startIndex
	var oldest uint64
	switch {
	case listResourceVersion > 0 && !w.removedEventSinceRelist:
		// If no event was removed from the buffer since last relist, the oldest watch
		// event we can deliver is one greater than the resource version of the list.
		oldest = listResourceVersion + 1
	case size > 0:
		// If the previous condition is not satisfied: either some event was already
		// removed from the buffer or we've never completed a list (the latter can
		// only happen in unit tests that populate the buffer without performing
		// list/replace operations), the oldest watch event we can deliver is the first
		// one in the buffer.
		oldest = w.cache[w.startIndex%w.capacity].ResourceVersion
	default:
		return nil, fmt.Errorf("watch cache isn't correctly initialized")
	}

	if resourceVersion < oldest-1 {
		return nil, errors.NewResourceExpired(fmt.Sprintf("too old resource version: %d (%d)", resourceVersion, oldest-1))
	}

	// Binary search the smallest index at which resourceVersion is greater than the given one.
	f := func(i int) bool {
		return w.cache[(w.startIndex+i)%w.capacity].ResourceVersion > resourceVersion
	}
	first := sort.Search(size, f)
	// ...
}
```

`removedEventSinceRelist` 这个布尔位专门记录"上次 list 之后是否已有事件被挤出缓冲"。没挤出过时，最老可交付的 RV 是 list 时的 RV + 1——即使缓冲里没剩几条，也能安全回答。

> [!TIP]
> 这一段解释了 **`410 Gone` 的真实来源**。客户端收到它只意味着"你要的起点已经不在 apiserver 内存里了"，**不一定跟 etcd 的 compaction 有关**。反之，如果请求直接透传到 etcd 撞上 compaction，410 来自 etcd 侧错误转换。两者的排查方向完全不同。

### Wait When Freshness Is Insufficient, Rather Than Erroring

如果请求的 RV 比缓存当前追上的还新（比如刚写完立刻读），`waitUntilFreshLocked`（`watch_cache.go`）会阻塞等待（摘录）：

```go
	for w.resourceVersion < resourceVersion {
		if w.config.clock.Since(startTime) >= blockTimeout {
			// Request that the client retry after 'resourceVersionTooHighRetrySeconds' seconds.
			return storage.NewTooLargeResourceVersionError(resourceVersion, w.resourceVersion, resourceVersionTooHighRetrySeconds)
		}
		w.cond.Wait()
	}
```

`blockTimeout = 3 * time.Second`。唤醒来源有三个：事件处理里的 `cond.Broadcast()`、etcd progress notify 回调 `UpdateResourceVersion`、`Replace`。

等待过程中 apiserver 会**主动向 etcd 要一次进度通知**，而不是傻等下次变更——这是 `progress` 包的职责（`cacher/progress/watch_progress.go`），周期 100ms，只在真有等待者时才发。v1.37 里"有等待者"的判定是 `waitUntilFreshLocked` 的 `waitingUntilFresh` 计数（`consistentReadSupported` 为 true 时 `Add()`/`Remove()`）。

> [!WARNING]
> 这个函数**不监听 `ctx.Done()`**。ctx 只用于 metrics 与 tracing。所以客户端取消请求后，服务端 goroutine 不会立即释放，最多再占用 3 秒（`blockTimeout`）。不会永久泄漏，但高并发取消场景下这个尾延迟是可观测的。

---

## Segment 3: How Events Fan Out — Slow Consumers Get Disconnected

事件从 etcd 到 watcher 要穿过三段，每段都有明确的边界：

```
etcd watch → watchCache.processEvent → incoming chan(cap 100) → dispatchEvents(单 goroutine) → 每个 cacheWatcher
```

1. **`watchCache.processEvent`**：写环形缓冲、推进 `resourceVersion`、更新 btree、`Broadcast` 唤醒等待者。取旧值（`PrevObject`）的 `store.Get` 是**在锁外**做的，减少持锁时间。
2. **`Cacher.processEvent`**：唯一动作是 `c.incoming <- *event`，channel 容量硬编码 **100**（`cacher.go`：`incoming: make(chan watchCacheEvent, 100)`，代码里带 TODO）。
3. **`dispatchEvents`**：单个 goroutine 串行消费，调 `startDispatching` 收集候选 watcher，再逐个投递。

`incoming` 是阻塞式投递，所以第 2 段能对第 1 段形成背压；但第 3 段对 watcher 是**非阻塞**的，这是关键设计。

### `nonblockingAdd` and Disconnecting Slow Watchers

```go
func (c *cacheWatcher) nonblockingAdd(event *watchCacheEvent) bool {
	// if the bookmarkAfterResourceVersion hasn't been seen
	// we will try to deliver a bookmark event every second.
	// the following check will discard a bookmark event
	// if it is < than the bookmarkAfterResourceVersion
	// so that we don't pollute the input channel
	if event.Type == watch.Bookmark && event.ResourceVersion < c.bookmarkAfterResourceVersion {
		return false
	}
	select {
	case c.input <- event:
		c.markBookmarkAfterRvAsReceived(event)
		return true
	default:
		return false
	}
}
```

注意一个行为细节：v1.37 里过期 bookmark 直接返回 `false`（不算投递成功），发送方会把它当失败处理进重试路径。分发主路径先对每个 watcher 试 `nonblockingAdd`，**成功的就结束**，避免快 watcher 被慢 watcher 拖累。失败的进 `blockedWatchers`，再走带预算的阻塞投递：

```go
timeout := c.dispatchTimeoutBudget.takeAvailable()
c.timer.Reset(timeout)
// ... 对每个 blocked watcher: watcher.add(event, timer)
```

预算耗尽仍未消费的 watcher 会被**直接关闭**（`cache_watcher.go` 的 `add` → `closeFunc`）。这就是"一个卡住的 informer 不会拖垮整个 Cacher"的源码保证。

### Distribution Budget Is Not a Fixed Value

预算来自 `timeBudget`，不是常见的"3 秒超时"：

```go
// time_budget.go
refreshPerSecond = 50 * time.Millisecond
maxBudget        = 100 * time.Millisecond
```

即每秒累积 50ms、上限 100ms，用掉就清零，没用完还能归还：

$$\text{budget}(t) = \min(100\text{ms},\ \text{budget}(t_0) + 50\text{ms} \times \Delta t)$$

所以被断开的 watcher 实际容忍度在 0～100ms 之间浮动。慢一点是能活的，持续慢就会被断。

> [!NOTE]
> `blockTimeout = 3s`（`watch_cache.go`）和这里的 100ms 预算很容易被混为一谈。前者管**等缓存追上 RV**，后者管**分发时给 watcher 多少缓冲时间**，两者毫无关系。

### Who Is Collecting Candidates

`startDispatching` 持锁后按两级索引收集：`allWatchers` 按 namespace / name 的四种 scope 组合查，`valueWatchers` 再按 field selector 的触发值查。`watchersBuffer` / `blockedWatchers` / `watchersToStop` 都是复用切片，每次分发开头 `watchersBuffer = watchersBuffer[:0]`——这条热路径上不做分配。

Bookmark 走另一条路：`startDispatchingBookmarkEventsLocked` + 按秒分桶的 `watcherBookmarkTimeBuckets`。

---

## Segment 4: List Request — Why Copy Only at the Last Step

`Cacher.GetList` 的流程值得单独看，因为它体现了一个刻意的性能取舍：

1. 检查就绪状态。
2. `WaitUntilFreshAndGetList` 拿到 `listResp`——里面装的是 **`*store.Element` 指针**，不是对象副本。
3. 用预先算好的 `elem.Labels` / `elem.Fields` 做 selector 预过滤。
4. **最后一步才拷贝**：`reflect` 逐元素赋值到 List 的 slice 里。

源码注释说得很直白：`ListObject` 的元素是 struct 类型，构造 slice 会带来过多内存消耗，所以这个动作要尽量推迟。

### Snapshot: Exact RV and Pagination's Second Path

`ListFromCacheSnapshot` 1.34 转 Beta、默认开启（`apiserver/pkg/features/kube_features.go`）。开启后 `watchCache` 支持**按指定 RV 读快照**：实现是 btree 的惰性克隆，`waitAndGetExactSnapshot` → `GetLessOrEqual` → `store.ListPrefix`。

拿不到对应快照就返回 `ResourceExpired`，让上层回退 etcd——**宁可慢，不给错数据**。快照本身按 etcd 的 compaction revision 清理，轮询周期 15s（`cacher/compactor.go`：`compactorPollPeriod = 15 * time.Second`）。

### `cachingObject`: Not Lazy Decoding

`caching_object.go` 容易被名字误导。它不是延迟解码，而是**序列化结果缓存 + 惰性深拷贝**：

| 字段 | 作用 |
|---|---|
| `deepCopied bool` | 是否已被惰性深拷贝过一次 |
| `object metaRuntimeInterface` | 被包装的对象 |
| `serializations atomic.Value`（`serializationsCache map[runtime.Identifier]*serializationResult`） | 按标识缓存 encode 结果 |

流程是：一个对象被 N 个 watcher 共享**同一份** `cachingObject`，避免 N 次深拷贝；每次 encode 的结果按标识缓存；只有极少数真要改字段时才触发一次深拷贝（`conditionalSet`）。

分发时由 `setCachingObjects` 包上。注意 Deleted 事件只包 `PrevObject`，且会把事件的 RV 设成当前 RV——因为删除事件的对象本身没有 RV 可用。

---

## Segment 5: Pagination and continue token

分页由 `limit` + `continue` 两个参数驱动，token 的内容可以直接看源码：

```go
// storage/continue.go —— 注意注释说这是 public API struct，不能改
type continueToken struct {
    APIVersion      string `json:"v"`
    ResourceVersion int64  `json:"rv"`
    StartKey        string `json:"start"`
}
```

编码就是 `base64url(JSON)`：

```go
return base64.RawURLEncoding.EncodeToString(out), nil
```

> [!WARNING]
> **continue token 不加密。** 它只是 base64url 编码的 JSON，任何人解码就能看到起始 key 与该次列表的 RV。它跟 `--api-audiences`、EncryptionConfiguration 都无关——后者是 etcd 静态数据加密，用途完全不同。这一点在排查"token 能否跨集群复用""会不会泄密"时最容易搞错。

### RV Must Be Bound into the Token

`rv` 字段不是装饰。`ValidateListOptions`（`storage/interfaces.go`）在 `continueRV > 0` 时把请求的 RV 覆盖成 token 里的值，让所有分页在**同一个快照 RV** 上读取。否则分页期间数据变化会导致重复或漏项。

两个衍生行为：

- 用 `continue` 时**再指定 RV 就是 400**（报错 "specifying resource version is not allowed when using continue"）
- `continueRV < 0` 是特殊语义，表示"compaction 之后从最新继续"，由 etcd3 错误转换生成，当作一致性读处理

`remainingItemCount` **仍在填充**，但只在没有 selector 时给——etcd 返回的 count 包含不匹配 predicate 的对象，有 selector 时给不准，干脆返回 nil。

---

## Segment 6: Watch Request — bookmark, Progress Notification and Two Errors

watch 的服务端实体是 `cacheWatcher`（`cache_watcher.go`），一个请求一个，有自己的输入 channel。

v1.37 里 channel 容量不再是纯常量表，而是启发式：`watchCacheHistory.suggestedWatchChannelSize` 用"channel 应能装下一秒历史"估算——`ceil(capacity / eventFreshDuration.Seconds())`，再按场景夹到上下界之间（摘录）：

```go
func (w *watchCacheHistory) suggestedWatchChannelSize(indexExists, triggerUsed bool) int {
	// To estimate the channel size we use a heuristic that a channel
	// should roughly be able to keep one second of history.
	// We don't have an exact data, but given we store updates from
	// the last <eventFreshDuration>, we approach it by dividing the
	// capacity by the length of the history window.
	chanSize := int(math.Ceil(float64(w.capacity) / w.eventFreshDuration.Seconds()))

	// Finally we adjust the size to avoid ending with too low or
	// to large values.
	chanSize = max(chanSize, minWatchChanSize)
	var maxChanSize int
	switch {
	case indexExists && triggerUsed:
		maxChanSize = maxWatchChanSizeWithIndexAndTrigger
	case indexExists && !triggerUsed:
		maxChanSize = maxWatchChanSizeWithIndexWithoutTrigger
	case !indexExists:
		maxChanSize = maxWatchChanSizeWithoutIndex
	}
	return min(chanSize, maxChanSize)
}
```

上下界常量（`watch_cache_history.go`）：

| 常量 | 值 | 场景 |
|---|---|---|
| `minWatchChanSize` | 10 | 下界 |
| `maxWatchChanSizeWithIndexAndTrigger` | 10 | 有索引且有触发 selector |
| `maxWatchChanSizeWithIndexWithoutTrigger` | 1000 | 有索引无触发 |
| `maxWatchChanSizeWithoutIndex` | 100 | 无索引 |

### Three bookmark Timing Cases

`nextBookmarkTime`（`cache_watcher.go`）决定何时发 bookmark：

1. **deadline 前 2 秒**——这是最实用的一种，服务端在 watch 超时前主动给个 bookmark，客户端就有了确定的进度点，重连不用从头来
2. **大约每分钟**（`defaultBookmarkFrequency = time.Minute`）
3. **未收到期望下界时立即**——服务端已推进的 RV 超过客户端要求的下界，立刻通知

`bookmarkAfterResourceVersion` 字段就是这个下界的载体，请求侧由 `setBookmarkAfterResourceVersion` 设置。

### Two Types of watch Errors, Opposite Directions

| 情况 | 错误 | HTTP | 客户端该做什么 |
|---|---|---|---|
| RV 太旧，已不在缓存/etcd | `ResourceExpired` | **410** | 重新 List |
| RV 太新，缓存还没追上 | `TooLargeResourceVersionError` | **504** | 稍后重试（`RetryAfterSeconds=1`） |
| 缓存尚未初始化完成 | `TooManyRequests` | **429** | 退避重试（指数退避，1～30s） |

"太新"返回 **504 而不是 429** 这点反直觉：`NewTooLargeResourceVersionError` 内部调的是 `apierrors.NewTimeoutError`，而它的 `Code` 就是 `http.StatusGatewayTimeout`，并带上 `Details.Causes` 的 `ResourceVersionTooLarge` 标记。

> [!TIP]
> 所以在日志里看到 **504 不要先怀疑超时配置**，先看 `RetryAfterSeconds` 与 cause 类型。K8s 用"超时"这个语义来表达"你现在问的东西还不存在"，因为两者对客户端而言的处理方式一致：等一下再来。

### Readiness Is a Three-state Machine

`ready`（`cacher/ready.go`）只有 `Pending` / `Ready` / `Stopped` 三态，加上一个 `generation` 计数。

启动时 `startCaching` 把 `onReplace` 设为 `ready.setReady`：

```go
c.watchCache.SetOnReplace(func() {
    c.ready.setReady()      // 只有完成一次 Replace 才算就绪
})
```

**为什么必须先从 etcd 全量 List 一遍**：只有这样才能同时得到 (a) btree 里的当前对象、(b) 单调基准 `resourceVersion` / `listResourceVersion`。没有 RV 基准，任何带 RV 的请求都无法安全服务。

v1.37 里，缓存未就绪时的 429 重试秒数由 `calculateRetryAfterForUnreadyCache`（`cacher/util.go`）计算——**这段逻辑已经无条件生效**：

```go
// calculateRetryAfterForUnreadyCache calculates the retry duration based on the cache downtime.
func calculateRetryAfterForUnreadyCache(downtime time.Duration) int {
	factor := 0.06
	result := math.Exp(factor * downtime.Seconds())
	result = math.Min(30, math.Max(1, result))
	return int(result)
}
```

按停机时长指数增长并 clamp 到 [1, 30]。原本控制它的 `ResilientWatchCacheInitialization` gate 已在 1.37 GA 并从代码中移除（行为转正）。同时 `WatchCacheInitializationPostStartHook` 在 1.37 也 GA 并 `LockToDefault`——kube-apiserver 的 `/healthz`、`/livez` 会等所有 storage 就绪，**"apiserver 进程起来了"和"能服务读请求了"是同一时刻**。

---

## Segment 7: Streaming list (WatchList) — Using watch to Fake list

到这里可以回答一个现代 K8s 的问题：**为什么要有 WatchList 这个特性？**

传统 List 的问题是服务端要把整份结果物化、编码、一次性返回。对象多的时候这是一次内存尖峰。而 watch cache 里本来就有全部对象——那能不能不构造 List，直接用 watch 事件把等价的内容流出去？这就是 WatchList。

服务端的做法：

1. 判定这是不是流式 list 请求：`isListWatchRequest`（`cacher.go`，注释明确说与 `endpoints/handlers/get.go` 镜像）要求 `SendInitialEvents == true` **且** `AllowWatchBookmarks == true`
2. 从 store 快照生成合成 ADDED 事件流（`watch_cache_interval.go` 的 `newCacheIntervalFromStore`，或惰性快照版本 `newCacheIntervalFromLazySnapshot`），**按 key 排序**
3. 收尾发一个特殊 BOOKMARK：`setInitialEventsEndBookmarkIfRequested` 构造 RV = 缓存当前 RV 的 bookmark，注解 `k8s.io/initial-events-end: "true"` 在 `cache_watcher.go` 的 `convertToWatchEvent` 里统一打上
4. 由 `cacheWatcher.processInterval` 在区间事件发完后送出

客户端看到这个注解的 bookmark，就知道"初始状态已全部收到"，可以 `Replace` 本地 store 了。

### The Synchronization Point Comes from etcd, Not the Cache

流式 list 的一致性锚点不是 watch cache 自己走到哪，而是**向 etcd 要来的当前 RV**。RV 为空且 `SendInitialEvents=true` 时，`getWatchCacheResourceVersion`（`cacher.go`）直接调 `c.storage.GetCurrentResourceVersion(ctx)` 穿透到 etcd 取同步点。拿到之后，`waitUntilWatchCacheFreshAndForceAllEvents` 把请求挂起，直到缓存追平该 RV。

等待机制是 `cond.Wait` 循环（`watch_cache.go` 的 `waitUntilFreshLocked`），每次缓存 `processEvent` 推进 RV 后 `Broadcast` 唤醒检查，超时上限 `blockTimeout = 3s`，超时返回 `TooLargeResourceVersion` 让客户端几秒后重试。这里有一个隐蔽的依赖：**如果该资源一分钟都没有任何写事件，缓存的 RV 永远不会前进，等待就永远不会结束**——所以要求存储层支持 progress notify。`ConditionalProgressRequester`（`progress/watch_progress.go`）只在"有等待者"（`waitingUntilFresh` 计数非零）时周期性地向 etcd 发 `RequestWatchProgress`，逼 etcd 回一个 bookmark 事件把缓存 RV 推过同步点。这正解释了 `cacher.go` 里流式 list 请求的硬性前置：先检查 etcd 特性 `RequestWatchProgress`，不支持就直接返回错误 watcher，客户端回退传统 List。

### Interval Comes from the Store, Not the Ring Buffer

普通 watch（RV>0）的初始事件来自 history 环形缓冲（`history.GetIntervalLocked`），但流式 list **绕开环形缓冲，直接拍 store 快照**。入口在 `getAllEventsSinceLocked`（摘录）：

```go
func (w *watchCache) getAllEventsSinceLocked(resourceVersion uint64, key string, opts storage.ListOptions) (*watchCacheInterval, error) {
	_, matchesSingle := opts.Predicate.MatchesSingle()
	matchesSingle = matchesSingle && !opts.Recursive
	if opts.SendInitialEvents != nil && *opts.SendInitialEvents {
		return w.getIntervalFromStoreLocked(key, matchesSingle)
	}

	if resourceVersion == 0 {
		if opts.SendInitialEvents == nil {
			// resourceVersion = 0 means that we don't require any specific starting point
			// and we would like to start watching from ~now.
			// However, to keep backward compatibility, we additionally need to return the
			// current state and only then start watching from that point.
			//
			// TODO: In v2 api, we should stop returning the current state - #13969.
			return w.getIntervalFromStoreLocked(key, matchesSingle)
		}
		// SendInitialEvents = false and resourceVersion = 0
		// means that the request would like to start watching
		// from Any resourceVersion
		resourceVersion = w.resourceVersion
	}

	return w.history.GetIntervalLocked(resourceVersion, w.storage.ListResourceVersion(), w.RWMutex.RLocker())
}
```

原因是语义不同：流式 list 要的是"某一时刻的全量状态"，不是"某段历史变更"。

快照有两个版本，差别在锁内开销：

| 版本 | 条件 | 锁内成本 |
|---|---|---|
| `newCacheIntervalFromLazySnapshot` | store 能提供不可变快照 `LatestSnapshotLocked` | **O(1)**：只拿快照引用，O(N) 遍历推迟到锁释放后的首次 `Next()` |
| `newCacheIntervalFromStore` | 兜底 | 锁内物化整份 buffer，按 key 有序 |

合成的动作只有一处：`storeElementToWatchCacheEvent` 把每个元素包成一条 `watch.Added`，**全部盖同一个同步 RV**。所以客户端看到的"初始状态"是一组 RV 相同的 ADDED——这与历史事件（每条 RV 各异）在数据面上就能区分开。

### The Handoff: processInterval

发送侧的流水线在 `cacheWatcher.processInterval`：

```
发完 interval 全部合成事件（逐条 Next()）
  → 发 initialEventsEndBookmark
  → process(ctx, resourceVersion) 切换为实时事件
```

三条防错细节：

1. **抬高下限**：快照可能比请求的更新（NotOlderThan 语义），`cacheInterval.resourceVersion > resourceVersion` 时把下限抬到快照 RV，防止把比快照旧的事件发出去造成"时间倒流"。
2. **发件去重**：每发一条 init 事件就拿事件 RV 与当前下限取 max；进入实时阶段后只发 `event.ResourceVersion > resourceVersion` 的事件。初始化期间到达的实时事件缓冲在 watcher 的 input channel 里不会丢——**接缝不漏事件靠的就是这个缓冲 + RV 去重**。
3. **成本不可线性外推**：源码 TODO 注释给了 Kubemark 实测——13862 条 initEvents 花 66ms，14040 条却花 993ms，耗时与事件数不成比例，疑似卡在序列化/GC。这就是为什么 watcher channel 的缓冲设计是"防一个慢 watcher 拖累全体"，而不是无限大。

发完初始书签后调 `utilflowcontrol.WatchInitialized(ctx)` 通知 APF：**初始化结束，席位可以释放了**。这条线与 [APF](/docs/CS/Container/k8s/APF.md) 笔记里"watch 只在初始化阶段占座"的闭环正好接上——APF 的 `watchInitializationSignal.Wait()` 等的就是这里发出的信号。

### Why the Stream Is Equivalent to List+Watch

把三段拼起来，一致性论证很短：同步点 `RV_sync` 来自 etcd；快照内容是缓存 RV ≥ `RV_sync` 时刻的全量；接缝处实时事件按 RV 去重。客户端最终收到的序列 = 「`RV_sync` 时刻的全量 ADDED」+「`initial-events-end` 书签」+「之后的增量」，**等价于 `List(RV_sync)` + `Watch(RV_sync)`，但没有两次请求之间漏事件/重复事件的窗口**。这就是流式 list 在语义上严格强于 List+Watch 的原因——两次请求合成了一条流。

### Client and Server Are Two Independent Switches

这点极易混淆，因为名字太像：

| 层 | gate | v1.37.2 状态 |
|---|---|---|
| 客户端（client-go） | `WatchListClient` | **Beta，默认 true**（自 1.35 起） |
| 服务端（apiserver） | `WatchList` | **Beta，默认 true**（自 1.34 起） |

两个门各自独立，**任一方关闭都会回退到普通 List**——客户端侧是自动 fallback，不是报错。

服务端 gate 有一处值得注意的反复：1.32 转 Beta true 之后，**1.33 又改回 false**，源码注释给的理由是"json 和 proto 的 streaming encoder 表现更好"。1.34 才恢复 true。所以它到 v1.37 仍是 **Beta，没有 GA**，这一点别记成已 GA。

服务端还会**自动打开**它：只要 gate 开着，watch 请求且 RV 为空或 "0" 时，`SetListOptionsDefaults` 会补上 `SendInitialEvents=true` + `ResourceVersionMatch=NotOlderThan`。

---

## Segment 8: Client Side — Reflector and Streaming list

`Reflector`（`client-go/tools/cache/reflector.go`）是 List-Watch 循环的实现者，也是 informer 拉取数据的唯一入口。

### The Main Loop Is Not a Bare `for {}`

```go
_ = r.delayHandler.Until(ctx, true, true, func(ctx context.Context) (bool, error) {
    ...
    if err := r.ListAndWatchWithContext(ctx); err != nil {
        r.watchErrorHandler(ctx, r, err)
    }
    return false, nil    // 永远不退出，只能靠 ctx 取消
})
```

回调永远返回 `false, nil`，所以循环不会因返回值结束——这就是"断线自动重连"的实现方式。退避参数：初始 800ms、上限 30s、因子 2.0、jitter 1.0、2 分钟无错就重置。

### `useWatchList` Judgment Is Simpler Than Imagined

只有两个条件：

```go
r.useWatchList = clientfeatures.FeatureGates().Enabled(clientfeatures.WatchListClient)
if r.useWatchList && watchlist.DoesClientNotSupportWatchListSemantics(lw) {
    r.useWatchList = false
}
```

不看 `WatchListPageSize`、不看 `resourceVersionMatch`、不看 `AllowWatchBookmarks`。（那组合条件来自 `util/watchlist/watch_list.go` 的 `PrepareWatchListOptionsFromListOptions`，而它**不被 Reflector 调用**，只被 e2e 测试与单测用。）

失败会自动降级并打日志："Data couldn't be fetched in watchlist mode. Falling back to regular list."——**这条日志在生产集群里出现是正常的**，说明服务端不支持或关闭了该特性。

### Key Implementation Points of Streaming list

`watchList` 的关键动作：

- 用**临时 store** 承接增量，最后一次性 `Replace` 到真实 store。这样做的理由很实在：真实 store 可能是队列，中途塞入会破坏语义。
- watch 选项里**不设 `Limit`**——流式 list 不做分页，`WatchListPageSize` 对它完全无效（它只影响传统 `list()` 的 pager 分页）
- 一路消费事件，直到 `handleAnyWatch` 判定收到 initial-events-end bookmark
- 收到后**复用同一条 watch 流**继续收增量（把 `stopWatcher` 显式置为 false），不重新建连

### The Truth About resync

这是被误解最深的一点。`startResync` 的全过程是：

```go
resyncCh, cleanup := r.resyncChan()   // 就是 clock.NewTimer(r.resyncPeriod)
for { select { case <-resyncCh: ... case <-ctx.Done(): return } }
    if r.ShouldResync == nil || r.ShouldResync() {
        r.store.Resync()               // ← 只调这一句
    }
```

**Resync 不发任何 apiserver 请求。** 它的作用是把本地 store 里已有的对象重新"过一遍"事件处理器，触发一次全量收敛。没有"从 apiserver 重新拉"这回事，也不存在"带 RV 的 resync"。

顺带修正另一个常见说法：内置控制器的 resync 周期不是"随机 8h~16h"那么和谐。`MinResyncPeriod` 默认是 **12h**，`ResyncPeriod()` 里乘 `rand.Float64() + 1`（因子落在 `[1, 2)`），所以实际区间是 **[12h, 24h)**。informer 层还有个 `minimumResyncPeriod = 1s` 的下限保护（`shared_informer.go`）。

### Two RV Fallback Paths

Reflector 用 `isLastSyncResourceVersionUnavailable` 标记来处理"上次同步点已失效"，但两条路径取的值不同：

| 方法 | 用于 | unavailable 时返回 | 正常时返回 |
|---|---|---|---|
| `relistResourceVersion()` | 传统 `list()` | `""` | lastSync RV，首次为 `"0"` |
| `rewatchResourceVersion()` | `watchList()` | `""` | lastSync RV |

`"0"` 的含义是"让服务端从 watch cache 读"，`""` 的含义是"不管多旧，给我一个一致的快照"。区别就在这。

> [!NOTE]
> `RetryAfterSeconds` **不参与** Reflector 的重试决策。客户端流控完全靠自己的 `delayHandler` 指数退避。这个字段只被 `rest/with_retry.go`（读 HTTP `Retry-After` 头）与 `tools/watch/retrywatcher.go` 使用。

---

## Whole-chain Comparison

| 阶段 | 服务端位置 | 客户端位置 |
|---|---|---|
| 发起同步 | — | `reflector.go` `ListAndWatchWithContext` |
| 流式 list | `cacher.go` `isListWatchRequest` + `watch_cache_interval.go` | `reflector.go` `watchList` |
| 传统 list | `cacher.go` `GetList` | `reflector.go` `list` + `pager.go` |
| 缓存分流 | `delegator/interface.go` `ShouldDelegateList` | — |
| 新鲜度等待 | `watch_cache.go` `waitUntilFreshLocked` + `progress/watch_progress.go` | — |
| 事件分发 | `cacher.go` `dispatchEvents` → `cache_watcher.go` `nonblockingAdd` | `reflector.go` `handleAnyWatch` |
| 断线重连 | — | `reflector.go` `delayHandler.Until` |

---

## Troubleshooting Quick Reference

| 现象 | 优先看什么 |
|---|---|
| informer 报 `410 Gone` | 先分清来源：缓存挤出了（`watch_cache_history.go` 的 `GetIntervalLocked`，可调大 `EventsHistoryWindow`）还是 etcd compaction（`etcd3` 错误转换，查 compaction 间隔） |
| 读请求返回 **504** | 不是超时配置问题，是 RV 比缓存新（`TooLargeResourceVersionError`）。看 `Details.Causes` 里的 `ResourceVersionTooLarge` |
| 读请求返回 **429** | 缓存尚未完成初始化。看 apiserver 启动日志里的 watch cache 初始化进度 |
| 某个 informer 反复断开重连 | 看是否触发了慢 watcher 断开（`cache_watcher.go` 有日志与指标）。根因通常是该 informer 的事件处理器太慢 |
| 响应里的 `continue` 很奇怪 | 解码看看：`base64url` 解出 JSON 能看到 `start` 与 `rv`。**它不加密** |
| `--default-watch-cache-size` 不生效 | 该 flag 已 deprecated，容量改为自适应。`--watch-cache-sizes` 只有在设为 `0`（禁用该资源的缓存）时才有意义，非零值会被丢弃并告警 |
| 大量 List 打到 etcd | 检查是否用了 `resourceVersion=0`（这会走缓存）还是显式 `Exact`（可能委托 etcd）。参考 `ShouldDelegateList` 的分流表 |
| apiserver 内存高 | watch cache 容量上界 102400 事件 × 资源类型数。`apiserver_watch_cache_capacity` 指标可直接观察 |

---

## v1.37 Counterintuitive List

1. **环形缓冲已拆出独立文件**。`watchCacheHistory`（`watch_cache_history.go`）持有事件序列、容量自适应与 `removedEventSinceRelist`；`watchCache` 只管当前状态与新鲜度等待。别再在 `watch_cache.go` 里找 resize 逻辑。
2. **`ResilientWatchCacheInitialization` gate 已移除**。1.35 GA、1.37 从 `kube_features.go` 删除（commit `591f5acf379`），429 重试秒数计算（指数、clamp [1,30]）转正为无条件行为。
3. **`WatchCacheInitializationPostStartHook` 1.37 GA + LockToDefault**。`/livez` 与 `/healthz` 等 storage 就绪不再是可选行为。
4. **watcher channel 容量从"常量查表"变成"启发式估算"**：`ceil(capacity / eventFreshDuration.Seconds())`，再按索引/触发 selector 夹到 [10, 10/1000/100] 之一。
5. **过期 bookmark 在 `nonblockingAdd` 里返回 `false`**（不再算投递成功），发送方按失败处理。
6. **watch cache 容量不是固定 100**。[100, 102400] 的**自适应区间**，由 `eventFreshDuration`（默认 75s）驱动。`--default-watch-cache-size` 已 deprecated，`--watch-cache-sizes` 非零值直接丢弃并告警。
7. **`dispatchTimeout` 这个 3 秒超时不存在**。分发预算是 `timeBudget`：每秒积攒 50ms、上限 100ms。`blockTimeout = 3s` 是另一件事——等缓存追上 RV。
8. **continue token 不加密**，就是 `base64url(JSON)`。与 `--api-audiences`、EncryptionConfiguration 都无关。
9. **RV 太新返回 504，不是 429**。429 只来自缓存未就绪。
10. **`cachingObject` 不是延迟解码**，而是序列化缓存 + 惰性深拷贝。
11. **`WaitUntilFreshAndList` 已改名**为 `WaitUntilFreshAndGetList`；`waitUntilFreshAndBlock` 已重构为 `waitUntilFreshLocked`（行为不变：不监听 ctx、3 秒上限）。
12. **Reflector 的 `watchHandler` 方法已不存在**，重构为包级 `handleAnyWatch` / `handleListWatch` / `handleWatch`。
13. **没有导出的 `Reflector.UseWatchList` 字段**，只有未导出的 `useWatchList`，在构造函数里一次性算出。
14. **`InOrderInformers` 1.36 已 GA 且 LockToDefault**，FIFO 为 `RealFIFO`。`AtomicFIFO` 默认开启，此时 **不再把 store 作为 `KnownObjects` 传入**，只有 atomic 关闭时才传。
15. **`WatchList` 到 1.37 仍是 Beta**，且中途在 1.33 被改回 false。别记成 GA。`WatchListClient` 同为 Beta（1.35 起默认 true）。
16. **apiserver 的 compaction 间隔仍是 5 分钟**（`storagebackend/config.go`：`DefaultCompactInterval = 5 * time.Minute`）。但触发方式是 apiserver 侧按 endpoint 协调，不是 etcd 自己决定。

## Links

- [K8s 架构与四条主链路](/docs/CS/Container/k8s/Architecture.md)
- [apiserver](/docs/CS/Container/k8s/apiserver.md)
- [client-go](/docs/CS/Container/k8s/client-go.md)
- [etcd](/docs/CS/Container/k8s/etcd.md)
- [controller-manager](/docs/CS/Container/k8s/controller-manager.md)
- [常见问题排查](/docs/CS/Container/k8s/Issues.md)

## References

1. [Kubernetes v1.37.2 source](https://github.com/kubernetes/kubernetes/tree/v1.37.2)
2. [KEP-3157: Allow informers for getting a stream of data instead of chunking](https://github.com/kubernetes/enhancements/tree/master/keps/sig-api-machinery/3157-watch-list)
3. [KEP-2340: Consistent Reads from Cache](https://github.com/kubernetes/enhancements/tree/master/keps/sig-api-machinery/2340-Consistent-reads-from-cache)
4. [KEP-956: Watch Bookmarks](https://github.com/kubernetes/enhancements/tree/master/keps/sig-api-machinery/956-watch-bookmark)
5. [API Concepts: Resource Versions](https://kubernetes.io/docs/reference/using-api/api-concepts/#resource-versions)
6. [etcd Watch API](https://etcd.io/docs/latest/learning/api/#watch-api)
