## Introduction

Caffeine 的时间维度有三种固定过期（写后 TTL、访问后 TTI、每条目可变过期）加一种「刷新」（`refreshAfterWrite`），底层由两套结构组织：**时间排序的过期队列**服务固定时长，**层级时间轮**服务可变时长。清理发生在维护循环里，是惰性的——默认没有任何后台线程到点删条目。本页讲清四种语义的实现差异、时间轮的规格、刷新与过期的本质区别、移除通知的原因枚举，以及「默认不主动清理」这条最容易被默认值坑的事实。

## Fixed Expiry Queues

`expireAfterWrite` 与 `expireAfterAccess` 不需要时间轮：

- 每个 Node 带 `writeTime` / `accessTime` 两个时间戳；
- 缓存维护一条**写顺序队列**和**访问顺序队列**（与淘汰用的三条区域队列共用链表指针），队首分别是「最早写入」和「最久未访问」的条目；
- `hasExpired` 就是两次时间戳相减比较；`expireAfterAccessEntries` / `expireAfterWriteEntries` 从队首 peek，过期一个摘一个，遇到未过期的就停——摊销 O(1)，且每轮最多处理 1,000 个（`EXPIRATION_THRESHOLD`）；
- 访问会把条目挪到访问顺序队列 MRU 端，等于自动续期——这正是 TTI 的语义。

固定过期**不占用时间轮的容量**，代价是每轮维护都要 peek 队列头；对海量 TTL 差异极大的固定过期，这个成本与条数无关，可以忽略。

## Hierarchical Timer Wheel

可变过期（`expireAfter(Expiry)`，每条目可返回不同时长）走 `TimerWheel`：

```java
static final int[] BUCKETS = { 64, 64, 32, 4, 1 };
static final long[] SPANS = {
    ceilingPowerOfTwo(SECONDS.toNanos(1)),   // 1.07s
    ceilingPowerOfTwo(MINUTES.toNanos(1)),   // 1.14m
    ceilingPowerOfTwo(HOURS.toNanos(1)),     // 1.22h
    ceilingPowerOfTwo(DAYS.toNanos(1)),      // 1.63d
    BUCKETS[3] * ceilingPowerOfTwo(DAYS.toNanos(1)),  // 6.5d
};
```

五层轮子，每层桶数递减、单桶时长按 2 的幂向上取整；条目按过期时刻哈希进某一层的某个桶，桶内是双向链表。轮子转动时把到期桶里的条目**级联（cascade）**到更细的层或直接判定过期——这就是「不给每个 entry 挂定时器，也能摊销 O(1) 地批量过期」的经典结构（Netty 的 `HashedWheelTimer`、Kafka 的延迟操作是同一思想，见 [Scheduled Task](/docs/CS/SE/Scheduled_Task.md)）。

- `advance` 在维护循环里被调用，每轮最多淘汰 1,000 个过期条目；没排完就把轮子时间回退，下轮继续消化 backlog；
- 覆盖范围约 6.5 天，`MAXIMUM_EXPIRY = Long.MAX_VALUE >> 1`（约 150 年）是可变过期的时间戳上限；
- 固定过期与可变过期互斥（builder 层 `requireState` 强制），所以一套缓存只有一套时间组织。

## Refresh vs Expire

`refreshAfterWrite` 与 `expireAfterWrite` 字面都带「时间」，语义完全相反：

| | `expireAfterWrite` | `refreshAfterWrite` |
| :--- | :--- | :--- |
| 到期后旧值 | 淘汰，读即 miss | **保留，继续返回旧值** |
| 触发时机 | 维护循环（惰性） | **读路径**上发现超过时长 |
| 加载方式 | 同步回源，并发会击穿 | 异步 `asyncReload`，不阻塞读 |
| 前置条件 | 无 | 必须是 `LoadingCache`（有 CacheLoader） |
| 失败后果 | miss 抛给调用方 | 记录 `loadFailure`，旧值继续服役 |

刷新的完整链路（`refreshIfNeeded`，跑在读路径上）：

```
读命中 → (now - writeTime) > refreshAfterWriteNanos？
  ├─ 否 → 正常返回
  └─ 是 → markRefreshing：CAS 改写 node 的 writeTime 打标记
          → refreshes（ConcurrentHashMap）computeIfAbsent 去重
          → cacheLoader.asyncReload(key, oldValue, executor)  // 异步加载新值
          → 完成后替换 value；失败则摘除 refreshes 记录、记 loadFailure、保留旧值
```

- **同 key 并发只刷一次**：`refreshes` map 加 writeTime 的 CAS 双重保证；3.0 起 `refresh` 操作线性化，重复调用返回的是**同一个 in-flight future**；
- **刷新不影响可用性**：异步加载期间旧值照常返回，这是它相对「到期淘汰 + 同步回源」的核心价值；
- **没有 CacheLoader 就没有刷新**：纯 `Cache` 调 `refreshAfterWrite` 不报错，但永远不触发——`refreshIfNeeded` 第一行就检查 `refreshAfterWrite()`（builder 层 `build()` 时还会强制「refreshAfterWrite requires a LoadingCache」）。

## Removal Notification

移除监听分两个 API，用途不同：

- `removalListener`：任何移除都通知，带 `RemovalCause`；
- `evictionListener`：只通知因容量/过期/GC 的移除（`wasEvicted() == true`）。

`RemovalCause` 五个值（源码枚举，注释里逐一列出了触发方法清单）：

| 值 | 含义 | `wasEvicted()` |
| :--- | :--- | :--- |
| `EXPLICIT` | 用户主动移除：`invalidate` / `Map.remove` / `compute` / 集合视图的 remove 等 | false |
| `REPLACED` | 值被替换：`put` / `getAll` / `refresh` / `replace` 等 | false |
| `COLLECTED` | key 或 value 被 GC 回收（weakKeys/weakValues/softValues） | true |
| `EXPIRED` | 过期时间已过（三种过期之一） | true |
| `SIZE` | 容量淘汰 | true |

两个 listener 的执行时机完全不同，选错就是线上事故：

- `removalListener`：**移除完成后在 executor 上异步执行**（`notifyRemoval` → `executor.execute`，仅当提交被拒绝才退回调用线程内联），默认 `ForkJoinPool.commonPool()`。排队中的通知任务持有 key/value 强引用——「value 大 + 高并发 + 调度慢」会延迟 GC；且与异步加载、刷新共用同一个线程池，互相挤占。
- `evictionListener`：**作为原子移除操作的一部分同步执行**——同步缓存上内联在维护循环里（持着 node 监视器与 CHM bin 锁），异步缓存上则包装成 `AsyncEvictionListener` 后仍走 executor。长计算会直接阻塞淘汰，写线程等待维护锁超 30 秒的警告多与此有关。

## Lazy by Default

这是本篇最重要的一条：**默认没有任何后台清理线程**。

- `Caffeine.scheduler(...)` 不设置时，`getScheduler()` 返回 `disabledScheduler`——过期条目的移除只发生在：① 读写操作触发的维护循环；② 显式 `cache.cleanUp()`。一个只写不读的缓存，过期条目可以无限期滞留；
- 显式配 `Scheduler.systemScheduler()`（或自定义）后，`expireEntries` 会用 `getExpirationDelay` 算出「下一个条目何时过期」，通过 `Pacer` 把维护任务延迟提交到 executor——`SystemScheduler` 的实现是 `CompletableFuture.delayedExecutor`，不占独立线程，任务最终仍跑在配置的 executor 上；
- `Pacer.TOLERANCE = 1.07s`：两次维护之间至少间隔约 1 秒，防止空转缓存被高频调度；
- 官方明确定义为 best-effort：`ScheduledThreadPoolExecutor` 也不提供实时保证，「到点就删」的精度是秒级。

工程含义：依赖「过期即消失」来做资源释放（如持有外部连接的 value）是不可靠的，要么用 listener，要么显式配 scheduler，要么别把过期当回收机制。

## Links

- [Caffeine](/docs/CS/SE/Caffeine.md)
- [Eviction](/docs/CS/SE/Caffeine/Eviction.md)
- [Architecture](/docs/CS/SE/Caffeine/Architecture.md)
- [Population](/docs/CS/SE/Caffeine/Population.md)
- [Scheduled Task](/docs/CS/SE/Scheduled_Task.md)
- [Cache](/docs/CS/SE/Cache.md)

## References

1. [Hashed and Hierarchical Timing Wheels](http://www.cs.columbia.edu/~nahum/w6998/papers/ton97-timing-wheels.pdf)
2. [ben-manes/caffeine 源码：TimerWheel.java](https://github.com/ben-manes/caffeine/blob/v3.3.1/caffeine/src/main/java/com/github/benmanes/caffeine/cache/TimerWheel.java)
3. [Caffeine 官方 Wiki](https://github.com/ben-manes/caffeine/wiki)
