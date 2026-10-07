## Introduction

Kubernetes 的每个组件都在做同一件事：从 apiserver 读一份自己关心的事物的副本，然后反复对账。scheduler 读 Pod 与 Node，kubelet 读自己节点上的 Pod，每个 controller 读自己负责的资源。这些订阅加起来规模很大——一个中等集群里同时活跃的 informer 动辄上万个。

如果每个 informer 都直连 etcd，etcd 几秒内就会被打垮。所以 apiserver 在读路径上插了一层缓存：**watch cache**。它做的事情可以一句话概括：

> **把"N 个订阅者"收敛成"1 条到 etcd 的 watch"。**

注意收敛点是**资源类型**，不是集群规模、也不是 informer 数量。一个 group-resource 只有**一个** `Cacher`、**一个** `Reflector`、**一条**到 etcd 的 watch（`staging/src/k8s.io/apiserver/pkg/storage/cacher/cacher.go:349`）。几万个 informer 对应的是 Cacher 内部的几万个 `cacheWatcher`（`cacher.go:310`），它们是纯内存结构。

| | 没有 watch cache | 有 watch cache |
|---|---|---|
| 1 万个 informer 的初始 List | 1 万次 etcd range | 命中内存 btree，etcd 零请求 |
| 1 万个 informer 的 watch | 1 万条 etcd watch 流 | **1 条** |
| 对象变更的扇出 | etcd 自己做 fan-out | apiserver 内存 fan-out |
| 扩容的瓶颈 | etcd 连接数与请求 QPS | apiserver 内存与 CPU |

这条链路同时是前面几篇笔记的隐形底座：写请求落库后的通知、调度器看到 Pod 更新、kubelet 感知删除，全都建立在这里描述的机制上。

> [!NOTE]
> 本文全部结论基于 **Kubernetes v1.36.4** 源码实读，各处标注文件路径与行号。v1.36 在这一层有若干结构性改动，统一收在文末「v1.36 反直觉清单」。

---

## Segment 1: Before the Read Request Comes — Where the Cache Should Be

apiserver 的存储栈自上而下是：REST handler → registry store → **CacheDelegator** → Cacher 或 etcd。

关键点是这一层**不是**"先查缓存、miss 再查 etcd"那种缓存。它更像一个**分流器**：一部分请求由内存服务，另一部分直接透传到 etcd，判断依据写在 `ShouldDelegateList` 里（`staging/src/k8s.io/apiserver/pkg/storage/cacher/delegator/interface.go:40`）。

| `ResourceVersionMatch` | 其他条件 | 走哪 |
|---|---|---|
| `Exact` | — | 看缓存是否有对应快照，否则 etcd（`:43`） |
| `NotOlderThan` | — | **不委托**，缓存处理（`:45`） |
| 空 | 带 `Continue` | 看 token 里的 RV（`:49`） |
| 空 | `Limit>0` 且 RV 非空非 0 | legacy exact 语义（`:53`） |
| 空 | RV 为空 | 一致性读（`:57`） |
| 其他 | — | 委托 etcd（`:61`） |

> [!TIP]
> `LabelSelector` / `FieldSelector` **不参与**这个决策。它们由缓存层自己过滤——`store.Element` 在写入时就把 labels/fields 算好存在一起，`GetList` 里直接拿来做预过滤（`cacher.go:815`）。这也是为什么 selector 不会把请求"打穿"到 etcd。

真正的实现类型是 `*CacheDelegator`（`cacher/delegator.go:79`），它同时持有 cacher 与 `storage.Interface`（即 `*etcd3.store`），两个都能服务。取不到结果时会回退：

- 缓存返回 `ResourceExpired` 且 `ListFromCacheSnapshot` 开启 → 回退 etcd（`delegator.go:215`）
- 一致性读返回 `IsTooLargeResourceVersion` → 回退 etcd（`delegator.go:218`）

---

## Segment 2: watchCache Core — A Self-resizing Sliding Window

`watchCache` 是整个缓存的实体（`storage/cacher/watch_cache.go:89`）。它由三部分组成：

| 组成 | 字段 | 作用 |
|---|---|---|
| 当前状态 | `store store.Indexer`（`:125`） | 内存 btree，存对象**当前**的样子 |
| 历史事件 | `cache []*watchCacheEvent`（`:114`） + `startIndex` / `endIndex` | 环形缓冲，存事件**序列** |
| 推进位置 | `resourceVersion uint64`（`:128`） | 缓存已追上的 RV |

前两者解决的是两类不同的请求：List 要"现在有什么"，watch 要"从 RV X 之后发生了什么"。

### The Ring Buffer Is Not Fixed Capacity

老版本的 `--default-watch-cache-size`（默认 100）常说成"缓存能存 100 个事件"，v1.36 已经不是这样了：

```go
// watch_cache.go:61,64
defaultLowerBoundCapacity = 100        // 只是下界
defaultUpperBoundCapacity = 100 * 1024 // 上界
```

`resizeCacheLocked`（`:374`）按需伸缩：缓冲满且所有事件都还在期望保留时长内 → 容量翻倍（封顶上界）；满但最近 1/4 窗口外的事件已超出期望时长 → 容量减半（保护下界，避免抖动）。

期望保留时长是 `eventFreshDuration`，默认 **75 秒**（`cacher.go:73`：`defaultBookmarkFrequency(60s) + 15s`）。上界由它推算（`watch_cache.go:211`）：75s 及以内固定 102400，更大时按 2 的幂放大。

写入用取模落位（`:360`）：

```go
w.cache[w.endIndex%w.capacity] = event
w.endIndex++
```

注意 `endIndex` / `startIndex` 是**事件序号**，跟 RV 没有算术关系——RV 由 etcd 保证单调，序号只是"第几个事件"。

### Too-old RV Will Be Explicitly Rejected

"从 RV X 开始 watch"时，X 可能已经不在缓冲里了。判定在 `getAllEventsSinceLocked`（`:876`）：

```go
case w.listResourceVersion > 0 && !w.removedEventSinceRelist:
    oldest = w.listResourceVersion + 1
case size > 0:
    oldest = w.cache[w.startIndex%w.capacity].ResourceVersion
...
if resourceVersion < oldest-1 {
    return nil, errors.NewResourceExpired(...)   // :916 → HTTP 410
}
```

`removedEventSinceRelist` 这个布尔位（`:119`）专门记录"上次 list 之后是否已有事件被挤出缓冲"。没挤出过时，最老可交付的 RV 是 list 时的 RV + 1——即使缓冲里没剩几条，也能安全回答。

> [!TIP]
> 这一段解释了 **`410 Gone` 的真实来源**。客户端收到它只意味着"你要的起点已经不在 apiserver 内存里了"，**不一定跟 etcd 的 compaction 有关**。反之，如果请求直接透传到 etcd 撞上 compaction，410 来自 `etcd3/errors.go:31`。两者的排查方向完全不同。

### Wait When Freshness Is Insufficient, Rather Than Erroring

如果请求的 RV 比缓存当前追上的还新（比如刚写完立刻读），`waitUntilFreshAndBlock`（`:449`）会阻塞等待：

```go
for w.resourceVersion < resourceVersion {          // :481
    if w.clock.Since(startTime) >= blockTimeout {  // 3s
        return storage.NewTooLargeResourceVersionError(...)
    }
    w.cond.Wait()
}
```

唤醒来源有三个：`processEvent` 里的 `cond.Broadcast()`（`:328`）、etcd progress notify 回调 `UpdateResourceVersion`（`:424`）、`Replace`（`:790`）。

等待过程中 apiserver 会**主动向 etcd 要一次进度通知**，而不是傻等下次变更——这是 `progress` 包的职责（`cacher/progress/watch_progress.go:68`），周期 100ms，只在真有等待者时才发（`:36`）。

> [!WARNING]
> 这个函数**不监听 `ctx.Done()`**。ctx 只用于 metrics 与 tracing。所以客户端取消请求后，服务端 goroutine 不会立即释放，最多再占用 3 秒（`blockTimeout`）。不会永久泄漏，但高并发取消场景下这个尾延迟是可观测的。

---

## Segment 3: How Events Fan Out — Slow Consumers Get Disconnected

事件从 etcd 到 watcher 要穿过三段，每段都有明确的边界：

```
etcd watch → watchCache.processEvent → incoming chan(cap 100) → dispatchEvents(单 goroutine) → 每个 cacheWatcher
```

### The Shape of Each of the Three Segments

1. **`watchCache.processEvent`**（`watch_cache.go:283`）：写环形缓冲、推进 `resourceVersion`、更新 btree、`Broadcast` 唤醒等待者。取旧值（`PrevObject`）的 `store.Get` 是**在锁外**做的（`:311`），减少持锁时间。
2. **`Cacher.processEvent`**（`cacher.go:878`）：唯一动作是 `c.incoming <- *event`，channel 容量硬编码 **100**（`:405`，代码里带 TODO）。
3. **`dispatchEvents`**（`cacher.go:886`）：单个 goroutine 串行消费，调 `startDispatching` 收集候选 watcher，再逐个投递。

`incoming` 是阻塞式投递，所以第 2 段能对第 1 段形成背压；但第 3 段对 watcher 是**非阻塞**的，这是关键设计。

### `nonblockingAdd` and Disconnecting Slow Watchers

```go
// cache_watcher.go:147
func (c *cacheWatcher) nonblockingAdd(event *watchCacheEvent) bool {
    if event.Type == watch.Bookmark && event.ResourceVersion < c.bookmarkAfterResourceVersion {
        return true   // 丢弃过期 bookmark，不污染输入队列
    }
    select {
    case c.input <- event:
        return true
    default:
        return false  // 放不下就直说
    }
}
```

分发主路径先对每个 watcher 试 `nonblockingAdd`，**成功的就结束**，避免快 watcher 被慢 watcher 拖累（`cacher.go:983` 注释）。失败的进 `blockedWatchers`，再走带超时的阻塞投递：

```go
timeout := c.dispatchTimeoutBudget.takeAvailable()   // cacher.go:1019
c.timer.Reset(timeout)
// ... 对每个 blocked watcher: watcher.add(event, timer)
```

超时仍未消费的 watcher 会被**直接关闭**（`cache_watcher.go:169` 的 `add` → `closeFunc`）。这就是"一个卡住的 informer 不会拖垮整个 Cacher"的源码保证。

### Distribution Budget Is Not a Fixed Value

预算来自 `timeBudget`，不是常见的"3 秒超时"：

```go
// time_budget.go:26
refreshPerSecond = 50 * time.Millisecond
maxBudget        = 100 * time.Millisecond
```

即每秒累积 50ms、上限 100ms，用掉就清零，没用完还能归还：

$$\text{budget}(t) = \min(100\text{ms},\ \text{budget}(t_0) + 50\text{ms} \times \Delta t)$$

所以被断开的 watcher 实际容忍度在 0～100ms 之间浮动。慢一点是能活的，持续慢就会被断。

> [!NOTE]
> `blockTimeout = 3s`（`watch_cache.go:53`）和这里的 100ms 预算很容易被混为一谈。前者管**等缓存追上 RV**，后者管**分发时给 watcher 多少缓冲时间**，两者毫无关系。

### Who Is Collecting Candidates

`startDispatching`（`cacher.go:1065`）持锁后按两级索引收集：`allWatchers` 按 namespace / name 的四种 scope 组合查，`valueWatchers` 再按 field selector 的触发值查（`:1089-1134`）。索引结构 `indexedWatchers` 定义在 `cacher.go:143`。

`watchersBuffer` / `blockedWatchers` / `watchersToStop` 都是复用切片（`:331-337`），每次分发开头 `watchersBuffer = watchersBuffer[:0]`——这条热路径上不做分配。

Bookmark 走另一条路：`startDispatchingBookmarkEventsLocked`（`:1047`）+ 按秒分桶的 `watcherBookmarkTimeBuckets`（`:340`）。

---

## Segment 4: List Request — Why Copy Only at the Last Step

`Cacher.GetList`（`cacher.go:748`）的流程值得单独看，因为它体现了一个刻意的性能取舍：

1. 检查就绪状态（`:763`）。
2. `WaitUntilFreshAndGetList` 拿到 `listResp`（`:789`）——里面装的是 **`*store.Element` 指针**，不是对象副本。
3. 用预先算好的 `elem.Labels` / `elem.Fields` 做 selector 预过滤（`:815`）。
4. **最后一步才拷贝**（`:824`）：`reflect` 逐元素赋值到 List 的 slice 里。

源码注释说得很直白（`:794`）：`ListObject` 的元素是 struct 类型，构造 slice 会带来过多内存消耗，所以这个动作要尽量推迟。

### Snapshot: Exact RV and Pagination’s Second Path

`ListFromCacheSnapshot` 在 1.34 转 Beta、默认开启（`apiserver/features/kube_features.go:434`）。开启后 `watchCache` 多两个字段：`snapshots store.Snapshotter` 与 `snapshottingEnabled atomic.Bool`（`watch_cache.go:160`）。

实现是 btree 的**惰性克隆**：每个事件后 `snapshots.Add(rv, orderedLister)`，缓存满时 `RemoveLess(oldestRV)`（`:334`）。需要按指定 RV 读时走 `waitAndListExactRV`（`:592`）→ `GetLessOrEqual` → `store.ListPrefix`。

拿不到对应快照就返回 `ResourceExpired`，让上层回退 etcd——**宁可慢，不给错数据**。快照本身按 etcd 的 compaction revision 清理，轮询周期 15s（`cacher/compactor.go:30`）。

### `cachingObject`: Not Lazy Decoding

`caching_object.go` 容易被名字误导。它不是延迟解码，而是**序列化结果缓存 + 惰性深拷贝**：

| 字段 | 行号 | 作用 |
|---|---|---|
| `deepCopied bool` | `:75` | 是否已被惰性深拷贝过一次 |
| `object metaRuntimeInterface` | `:78` | 被包装的对象 |
| `serializations atomic.Value` | `:83` | 按 `runtime.Identifier` 缓存 encode 结果 |

流程是：一个对象被 N 个 watcher 共享**同一份** `cachingObject`，避免 N 次深拷贝；每次 encode 的结果按标识缓存（`:136`）；只有极少数真要改字段时才触发一次深拷贝（`conditionalSet`，`:227`）。

分发时由 `setCachingObjects` 包上（`cacher.go:947`，调用点 `:1004`）。注意 Deleted 事件只包 `PrevObject`，且会把事件的 RV 设成当前 RV（`:970`）——因为删除事件的对象本身没有 RV 可用。

---

## Segment 5: Pagination and continue token

分页由 `limit` + `continue` 两个参数驱动，token 的内容可以直接看源码：

```go
// storage/continue.go:39 —— 注意注释说这是 public API struct，不能改
type continueToken struct {
    APIVersion      string `json:"v"`
    ResourceVersion int64  `json:"rv"`
    StartKey        string `json:"start"`
}
```

编码就是 `base64url(JSON)`（`:83`）：

```go
return base64.RawURLEncoding.EncodeToString(out), nil
```

> [!WARNING]
> **continue token 不加密。** 它只是 base64url 编码的 JSON，任何人解码就能看到起始 key 与该次列表的 RV。它跟 `--api-audiences`、EncryptionConfiguration 都无关——后者是 etcd 静态数据加密，用途完全不同。这一点在排查"token 能否跨集群复用""会不会泄密"时最容易搞错。

### RV Must Be Bound into the Token

`rv` 字段不是装饰。`ValidateListOptions`（`storage/interfaces.go:346`）在 `continueRV > 0` 时把请求的 RV 覆盖成 token 里的值，让所有分页在**同一个快照 RV** 上读取。否则分页期间数据变化会导致重复或漏项。

两个衍生行为：

- 用 `continue` 时**再指定 RV 就是 400**（`:352`，报错 "specifying resource version is not allowed when using continue"）
- `continueRV < 0` 是特殊语义，表示"compaction 之后从最新继续"，由 `etcd3/errors.go:77` 生成。v1.36 把它当作一致性读处理（`cacher.go:1422` 注释）

`remainingItemCount` **仍在填充**，但只在没有 selector 时给（`continue.go:114`）——etcd 返回的 count 包含不匹配 predicate 的对象，有 selector 时给不准，干脆返回 nil。

---

## Segment 6: Watch Request — bookmark, Progress Notification and Two Errors

watch 的服务端实体是 `cacheWatcher`（`cache_watcher.go:53`），一个请求一个，有自己的输入 channel（容量由 `suggestedWatchChannelSize` 估算，`watch_cache.go:839`）。

容量常量的真实值（`watch_cache.go:820`）：

| 常量 | 值 | 场景 |
|---|---|---|
| `minWatchChanSize` | 10 | 下界 |
| `maxWatchChanSizeWithIndexAndTrigger` | 10 | 有索引且有触发 selector |
| `maxWatchChanSizeWithIndexWithoutTrigger` | 1000 | 有索引无触发 |
| `maxWatchChanSizeWithoutIndex` | 100 | 无索引 |

### Three bookmark Timing Cases

`nextBookmarkTime`（`cache_watcher.go:222`）决定何时发 bookmark：

1. **deadline 前 2 秒**——这是最实用的一种，服务端在 watch 超时前主动给个 bookmark，客户端就有了确定的进度点，重连不用从头来
2. **大约每分钟**（`defaultBookmarkFrequency = time.Minute`，`cacher.go:77`）
3. **未收到期望下界时立即**——服务端已推进的 RV 超过客户端要求的下界，立刻通知

`bookmarkAfterResourceVersion` 字段（`:81`）就是这个下界的载体，请求侧由 `setBookmarkAfterResourceVersion` 设置（`:321`）。

### Two Types of watch Errors, Opposite Directions

| 情况 | 错误 | HTTP | 客户端该做什么 |
|---|---|---|---|
| RV 太旧，已不在缓存/etcd | `ResourceExpired` | **410** | 重新 List |
| RV 太新，缓存还没追上 | `TooLargeResourceVersionError` | **504** | 稍后重试（`RetryAfterSeconds=1`） |
| 缓存尚未初始化完成 | `TooManyRequests` | **429** | 退避重试（指数退避，1～30s） |

"太新"返回 **504 而不是 429** 这点反直觉：`NewTooLargeResourceVersionError` 内部调的是 `apierrors.NewTimeoutError`（`storage/errors.go:234`），而它的 `Code` 就是 `http.StatusGatewayTimeout`（`apimachinery/pkg/api/errors/errors.go:405`），并带上 `Details.Causes` 的 `ResourceVersionTooLarge` 标记。

> [!TIP]
> 所以在日志里看到 **504 不要先怀疑超时配置**，先看 `RetryAfterSeconds` 与 cause 类型。K8s 用"超时"这个语义来表达"你现在问的东西还不存在"，因为两者对客户端而言的处理方式一致：等一下再来。

### Readiness Is a Three-state Machine

`ready`（`cacher/ready.go:30`）只有 `Pending` / `Ready` / `Stopped` 三态，加上一个 `generation` 计数。

启动时 `startCaching`（`cacher.go:486`）把 `onReplace` 设为 `ready.setReady`：

```go
c.watchCache.SetOnReplace(func() {
    c.ready.setReady()      // :488 —— 只有完成一次 Replace 才算就绪
})
```

**为什么必须先从 etcd 全量 List 一遍**：只有这样才能同时得到 (a) btree 里的当前对象、(b) 单调基准 `resourceVersion` / `listResourceVersion`。没有 RV 基准，任何带 RV 的请求都无法安全服务。

`ResilientWatchCacheInitialization` 在 1.34 GA 并锁定默认开启（`kube_features.go:459`），行为是**不阻塞等待、直接返回 429**，重试秒数按停机时长指数增长并 clamp 到 [1, 30]（`cacher/util.go:50`）。而在 1.36，`WatchCacheInitializationPostStartHook` 也转为默认开启（`:531`），效果是 kube-apiserver 的 `/healthz`、`/livez` 会等所有 storage 就绪——**这意味着"apiserver 进程起来了"和"能服务读请求了"现在是同一时刻**。

---

## Segment 7: Streaming list (WatchList) — Using watch to Fake list

到这里可以回答一个现代 K8s 的问题：**为什么要有 WatchList 这个特性？**

传统 List 的问题是服务端要把整份结果物化、编码、一次性返回。对象多的时候这是一次内存尖峰。而 watch cache 里本来就有全部对象——那能不能不构造 List，直接用 watch 事件把等价的内容流出去？这就是 WatchList。

服务端的做法（`cacher.go:509` 起）：

1. 判定这是不是流式 list 请求：`isListWatchRequest`（`:1280`）要求 `SendInitialEvents == true` **且** `AllowWatchBookmarks == true`
2. 从 store 快照生成合成 ADDED 事件流（`watch_cache_interval.go:140` 的 `newCacheIntervalFromStore`），**按 key 排序**
3. 收尾发一个特殊 BOOKMARK：`setInitialEventsEndBookmarkIfRequested`（`cacher.go:1337`）构造 RV = 缓存当前 RV 的 bookmark，带注解 `k8s.io/initial-events-end: "true"`（常量 `apimachinery/pkg/apis/meta/v1/types.go:493`）
4. 由 `cache_watcher.go:513` 在区间事件发完后送出

客户端看到这个注解的 bookmark，就知道"初始状态已全部收到"，可以 `Replace` 本地 store 了。

### Client and Server Are Two Independent Switches

这点极易混淆，因为名字太像：

| 层 | gate | v1.36 状态 |
|---|---|---|
| 客户端（client-go） | `WatchListClient` | **Beta，默认 true**（自 1.35 起，`client-go/features/known_features.go:141`） |
| 服务端（apiserver） | `WatchList` | **Beta，默认 true**（自 1.34 起，`apiserver/features/kube_features.go:536`） |

两个门各自独立，**任一方关闭都会回退到普通 List**——客户端侧是自动 fallback，不是报错。

服务端 gate 有一处值得注意的反复：1.32 转 Beta true 之后，**1.33 又改回 false**，源码注释给的理由是"json 和 proto 的 streaming encoder 表现更好"。1.34 才恢复 true。所以它到 v1.36 仍是 **Beta，没有 GA**，这一点别记成已 GA。

服务端还会**自动打开**它：只要 gate 开着，watch 请求且 RV 为空或 "0" 时，`SetListOptionsDefaults` 会补上 `SendInitialEvents=true` + `ResourceVersionMatch=NotOlderThan`（`apimachinery/pkg/apis/meta/internalversion/defaults.go:25`）。

---

## Segment 8: Client Side — Reflector and Streaming list

`Reflector`（`client-go/tools/cache/reflector.go:106`）是 List-Watch 循环的实现者，也是 informer 拉取数据的唯一入口。

### The Main Loop Is Not a Bare `for {}`

```go
// reflector.go:428
r.delayHandler.Until(ctx, true, true, func(ctx context.Context) (bool, error) {
    ...
    if err := r.ListAndWatchWithContext(ctx); err != nil {
        r.watchErrorHandler(ctx, r, err)
    }
    return false, nil    // 永远不退出，只能靠 ctx 取消
})
```

回调永远返回 `false, nil`，所以循环不会因返回值结束——这就是"断线自动重连"的实现方式。退避参数在 `:62`：初始 800ms、上限 30s、因子 2.0、jitter 1.0、2 分钟无错就重置。

### `useWatchList` Judgment Is Simpler Than Imagined

只有两个条件（`reflector.go:361`）：

```go
r.useWatchList = clientfeatures.FeatureGates().Enabled(clientfeatures.WatchListClient)
if r.useWatchList && watchlist.DoesClientNotSupportWatchListSemantics(lw) {
    r.useWatchList = false
}
```

不看 `WatchListPageSize`、不看 `resourceVersionMatch`、不看 `AllowWatchBookmarks`。（那组合条件来自 `util/watchlist/watch_list.go:40` 的 `PrepareWatchListOptionsFromListOptions`，而它**不被 Reflector 调用**，只被 e2e 测试与单测用。）

失败会自动降级并打日志（`:490`）："Data couldn't be fetched in watchlist mode. Falling back to regular list."——**这条日志在生产集群里出现是正常的**，说明服务端不支持或关闭了该特性。

### Key Implementation Points of Streaming list

`watchList`（`:804`）的关键动作：

- 用**临时 store** 承接增量（`:849`），最后一次性 `Replace` 到真实 store。这样做的理由很实在：真实 store 可能是队列，中途塞入会破坏语义。
- watch 选项里**不设 `Limit`**——流式 list 不做分页，`WatchListPageSize` 对它完全无效（它只影响传统 `list()` 的 pager 分页）
- 一路消费事件，直到 `handleAnyWatch` 判定收到 initial-events-end bookmark（`:1061`）
- 收到后**复用同一条 watch 流**继续收增量（`:891`、`:1077` 把 `stopWatcher` 显式置为 false），不重新建连

### The Truth About resync

这是被误解最深的一点。`startResync`（`:514`）的全过程是：

```go
resyncCh, cleanup := r.resyncChan()   // 就是 clock.NewTimer(r.resyncPeriod)
for { select { case <-resyncCh: ... case <-ctx.Done(): return } }
    if r.ShouldResync == nil || r.ShouldResync() {
        r.store.Resync()               // ← 只调这一句
    }
```

**Resync 不发任何 apiserver 请求。** 它的作用是把本地 store 里已有的对象重新"过一遍"事件处理器，触发一次全量收敛。没有"从 apiserver 重新拉"这回事，也不存在"带 RV 的 resync"。

顺带修正另一个常见说法：内置控制器的 resync 周期不是"随机 8h~16h"那么和谐。`MinResyncPeriod` 默认是 **12h**，`ResyncPeriod()` 里乘 `rand.Float64() + 1`（因子落在 `[1, 2)`），所以实际区间是 **[12h, 24h)**（`cmd/kube-controller-manager/app/controllermanager.go:191`、`controller-manager/config/v1alpha1/defaults.go:31`）。informer 层还有个 `minimumResyncPeriod = 1s` 的下限保护（`shared_informer.go:871`）。

### Two RV Fallback Paths

Reflector 用 `isLastSyncResourceVersionUnavailable` 标记（`:145`）来处理"上次同步点已失效"，但两条路径取的值不同：

| 方法 | 用于 | unavailable 时返回 | 正常时返回 |
|---|---|---|---|
| `relistResourceVersion()`（`:1116`） | 传统 `list()` | `""` | lastSync RV，首次为 `"0"` |
| `rewatchResourceVersion()`（`:1135`） | `watchList()` | `""` | lastSync RV |

`"0"` 的含义是"让服务端从 watch cache 读"，`""` 的含义是"不管多旧，给我一个一致的快照"。区别就在这。

> [!NOTE]
> `RetryAfterSeconds` **不参与** Reflector 的重试决策。客户端流控完全靠自己的 `delayHandler` 指数退避。这个字段只被 `rest/with_retry.go`（读 HTTP `Retry-After` 头）与 `tools/watch/retrywatcher.go` 使用。

---

## Whole-chain Comparison

| 阶段 | 服务端位置 | 客户端位置 |
|---|---|---|
| 发起同步 | — | `reflector.go:470` `ListAndWatchWithContext` |
| 流式 list | `cacher.go:1280` + `watch_cache_interval.go:140` | `reflector.go:804` `watchList` |
| 传统 list | `cacher.go:748` `GetList` | `reflector.go:674` `list` + `pager.go` |
| 缓存分流 | `delegator/interface.go:40` `ShouldDelegateList` | — |
| 新鲜度等待 | `watch_cache.go:449` + `progress/watch_progress.go` | — |
| 事件分发 | `cacher.go:886` `dispatchEvents` → `cache_watcher.go:147` | `reflector.go:972` `handleAnyWatch` |
| 断线重连 | — | `reflector.go:428` `delayHandler.Until` |

---

## Troubleshooting Quick Reference

| 现象 | 优先看什么 |
|---|---|
| informer 报 `410 Gone` | 先分清来源：缓存挤出了（`watch_cache.go:916`，可调大 `EventsHistoryWindow`）还是 etcd compaction（`etcd3/errors.go:31`，查 compaction 间隔） |
| 读请求返回 **504** | 不是超时配置问题，是 RV 比缓存新（`TooLargeResourceVersionError`）。看 `Details.Causes` 里的 `ResourceVersionTooLarge` |
| 读请求返回 **429** | 缓存尚未完成初始化（`cacher.go:525`）。看 apiserver 启动日志里的 watch cache 初始化进度 |
| 某个 informer 反复断开重连 | 看是否触发了慢 watcher 断开（`cache_watcher.go:179` 有日志与指标）。根因通常是该 informer 的事件处理器太慢 |
| 响应里的 `continue` 很奇怪 | 解码看看：`base64url` 解出 JSON 能看到 `start` 与 `rv`。**它不加密** |
| `--default-watch-cache-size` 不生效 | 该 flag 已 deprecated，容量改为自适应（`watch_cache.go:374`）。`--watch-cache-sizes` 只有在设为 `0`（禁用该资源的缓存）时才有意义，非零值会被丢弃并告警（`server/options/etcd.go:446`） |
| 大量 List 打到 etcd | 检查是否用了 `resourceVersion=0`（这会走缓存）还是显式 `Exact`（可能委托 etcd）。参考 `ShouldDelegateList` 的分流表 |
| apiserver 内存高 | watch cache 容量上界 102400 事件 × 资源类型数。`apiserver_watch_cache_capacity` 指标可直接观察 |

---

## v1.36 Counterintuitive List

1. **watch cache 容量不再是固定 100**。改为 [100, 102400] 的**自适应区间**（`watch_cache.go:61,64,374`），由 `eventFreshDuration`（默认 75s）驱动。`--default-watch-cache-size` 已 deprecated，`--watch-cache-sizes` 非零值直接丢弃并告警。
2. **`dispatchTimeout` 这个 3 秒超时不存在**。分发预算是 `timeBudget`：每秒积攒 50ms、上限 100ms（`time_budget.go:26`）。`blockTimeout = 3s` 是另一件事——等缓存追上 RV。
3. **continue token 不加密**，就是 `base64url(JSON)`（`continue.go:39`）。与 `--api-audiences`、EncryptionConfiguration 都无关。
4. **RV 太新返回 504，不是 429**（`storage/errors.go:234` → `apimachinery/.../errors.go:405`）。429 只来自缓存未就绪。
5. **`watchCacheInterval` 的 buffer 是固定 100，没有指数扩容**（`watch_cache_interval.go:225`）。`WatchCacheIntervalBufferSize` 这个符号不存在。
6. **`cachingObject` 不是延迟解码**，而是序列化缓存 + 惰性深拷贝（`caching_object.go:64`）。`originalData` / `data` 字段、`AssignResourceVersion` 方法都不存在。
7. **`processEvent` 里没有 RV 递减校验**（`watch_cache.go:283`）。单调性靠"只有一个调用方且同步调用"的契约保证，注释写在 `:281`。
8. **`WatchBookmark` 这个 feature gate 已被移除**。只剩 `ListOptions.AllowWatchBookmarks` 字段。
9. **`WatchList` 到 1.36 仍是 Beta**，且中途在 1.33 被改回 false（`kube_features.go:536`）。别记成 GA。
10. **`WaitUntilFreshAndList` 已改名**为 `WaitUntilFreshAndGetList`（`watch_cache.go:506`）；`watchCache.Resync()` 是 **no-op**（`:803`）。
11. **`waitUntilFreshAndBlock` 不监听 `ctx.Done()`**（`:449`）——请求取消了也要等到 3 秒超时。
12. **Reflector 的 `watchHandler` 方法已不存在**，重构为包级 `handleAnyWatch` / `handleListWatch` / `handleWatch`（`reflector.go:923`）。
13. **没有导出的 `Reflector.UseWatchList` 字段**，只有未导出的 `useWatchList`，在构造函数里一次性算出（`:361`）。
14. **`InOrderInformers` 在 1.36 已 GA 且 LockToDefault**（`known_features.go:127`），FIFO 为 `RealFIFO`。`AtomicFIFO` 默认开启，此时 **不再把 store 作为 `KnownObjects` 传入**（`controller.go:859`），只有 atomic 关闭时才传。
15. **`ListFromCacheSnapshot` 1.34 起 Beta 默认开启**（`kube_features.go:434`），这是 v1.36 读路径上一个容易被忽略的加速点。
16. **`WatchCacheInitializationPostStartHook` 在 1.36 转为默认开启**（`:531`），`/livez` 与 `/healthz` 现在会等 storage 就绪。
17. **apiserver 的 compaction 间隔仍是 5 分钟**（`storagebackend/config.go:38`）——这条老说法仍然准确。但触发方式已改为 apiserver 侧按 endpoint 协调，不是 etcd 自己决定。

## Links

- [K8s 架构与四条主链路](/docs/CS/Container/k8s/Architecture.md)
- [apiserver](/docs/CS/Container/k8s/apiserver.md)
- [client-go](/docs/CS/Container/k8s/client-go.md)
- [etcd](/docs/CS/Container/k8s/etcd.md)
- [controller-manager](/docs/CS/Container/k8s/controller-manager.md)
- [常见问题排查](/docs/CS/Container/k8s/Issues.md)

## References

1. [Kubernetes v1.36.4 source](https://github.com/kubernetes/kubernetes/tree/v1.36.4)
2. [KEP-3157: Allow informers for getting a stream of data instead of chunking](https://github.com/kubernetes/enhancements/tree/master/keps/sig-api-machinery/3157-watch-list)
3. [KEP-2340: Consistent Reads from Cache](https://github.com/kubernetes/enhancements/tree/master/keps/sig-api-machinery/2340-Consistent-reads-from-cache)
4. [KEP-956: Watch Bookmarks](https://github.com/kubernetes/enhancements/tree/master/keps/sig-api-machinery/956-watch-bookmark)
5. [API Concepts: Resource Versions](https://kubernetes.io/docs/reference/using-api/api-concepts/#resource-versions)
6. [etcd Watch API](https://etcd.io/docs/latest/learning/api/#watch-api)
