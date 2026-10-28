## Introduction

Caffeine 的「值从哪来」由 cache 的三种形态决定：纯手填的 `Cache`、带加载器的 `LoadingCache`、返回 future 的 `AsyncLoadingCache`。三者的分界不是语法糖，而是**回源责任放在谁身上**：`Cache` 的 miss 是调用方的事，`LoadingCache` 的 miss 由 `CacheLoader` 兜底，`AsyncCache` 则把整个读路径 future 化。本页讲清三种形态的 API 面、`CacheLoader` 的三个方法语义、`get(key, fn)` 的原子性与使用约束、`refresh` 的 in-flight 语义，以及失败时的行为差异。

## Three Cache Forms

```java
// 1. 手动缓存：miss 返回 null，回源由调用方负责
Cache<String, User> cache = Caffeine.newBuilder().maximumSize(10_000).build();

// 2. 加载缓存：miss 自动走 CacheLoader
LoadingCache<String, User> loading = Caffeine.newBuilder().maximumSize(10_000)
        .build(key -> loadFromDb(key));

// 3. 异步加载缓存：值以 CompletableFuture 形态存放
AsyncLoadingCache<String, User> async = Caffeine.newBuilder().maximumSize(10_000)
        .buildAsync(key -> loadFromDbAsync(key));
```

| 形态 | 读 API | miss 行为 | 与 executor 的关系 |
| :--- | :--- | :--- | :--- |
| `Cache` | `getIfPresent` / `get(key, fn)` | 返回 null / 调 `fn` | 只跑维护任务 |
| `LoadingCache` | `get` / `getAll` / `refresh` | 同步调 `CacheLoader.load` | 维护 + 加载/刷新 |
| `AsyncLoadingCache` | `get` 返回 `CompletableFuture` | 返回未完成的 future | 维护 + 异步加载 |

`AsyncCache.synchronous()` 提供回到同步视图的桥；反向没有——同步 cache 无法「变成」异步 cache。

## CacheLoader

`CacheLoader` 是函数式接口，三个方法：

```java
public interface CacheLoader<K, V> {
  V load(K key) throws Exception;                              // 单条加载（唯一必需）
  default Map<K, V> loadAll(Set<? extends K> keys) { ... }     // 批量：默认逐条调 load
  default V reload(K key, V oldValue) { return load(key); }   // 刷新：默认重新 load
}
```

- `load` 抛异常时 `get` 把异常抛给调用方，**不缓存异常**——下次读会再次触发加载；
- `loadAll` 的默认实现是逐条 `load`；重写它可以用一次批量查询替换 N 次往返，这是 `getAll` 性能的关键；
- `reload` 默认丢弃旧值重新加载；重写它可以做增量更新（旧值可用时只补差额），异常时旧值继续服役（见 [Expiration](/docs/CS/SE/Caffeine/Expiration.md) 的刷新链路）；
- 异步侧对应 `AsyncCacheLoader`，3.0 起提供 bulk 工厂方法且允许方法抛受检异常。

## Atomic Load: get(key, mappingFunction)

`Cache.get(K, Function)` 是 Caffeine 里最被低估的 API，也是 Spring `@Cacheable(sync = true)` 的真正落点：

```java
V value = cache.get(key, k -> expensiveCompute(k));
```

语义（源码 javadoc 原文要点）：**整个方法调用原子完成，mappingFunction 对同一 key 最多执行一次**；执行期间其他线程对同一 key（同一 CHM bin）的更新会被阻塞。由此推出三条使用纪律：

1. **函数必须短**：阻塞的是同 bin 的所有操作，长计算会让无关 key 的写入一起排队；
2. **函数内不得修改这个缓存**：递归更新会抛 `IllegalStateException`（"detectably attempts a recursive update"）；
3. **它替代的是「if cached return; else create, cache and return」**整套模式——手写 get-if-absent-then-put 在并发下就是缓存击穿的标准入口。

## Refresh Semantics

`LoadingCache` 的手动刷新与 `refreshAfterWrite` 的自动刷新共用同一套底层：

| API | 行为 |
| :--- | :--- |
| `refresh(key)` | 返回 `CompletableFuture<V>`；3.0 起返回的是**该 key 的 in-flight future**（已在刷新则复用，不会重复加载） |
| `refreshAll(keys)` | 批量刷新，聚合 future |
| `refreshAfterWrite` 自动触发 | 读路径发现超过时长时异步刷新，旧值可读 |

注意 `refresh` 的 `RemovalCause` 是 `REPLACED` 而不是 `EXPIRED`——刷新是「换值」不是「移除后重填」，listener 里区分这两者才能算对指标。

## Async Caches

`AsyncCache` / `AsyncLoadingCache` 把 future 作为一等公民存进缓存：

```java
AsyncCache<String, User> cache = Caffeine.newBuilder().buildAsync();
cache.put(key, CompletableFuture.supplyAsync(() -> loadFromDb(key)));
CompletableFuture<User> value = cache.get(key, k -> loadFromDbAsync(k));
```

- `get` 直接返回 future，miss 时映射函数在 executor 上执行，读线程不阻塞；
- **value 可以是未完成的 future**：多个读线程拿到同一个 future 各自 `thenApply`，天然合并回源；
- 刷新走 `asyncReload(key, oldFuture, executor)`，且只在前一个 future 已完成时才刷新（未完成说明加载还在飞，无需重复）；
- Spring Framework 7 的 `Cache#retrieve` 系列就是经 `CaffeineCacheManager.setAsyncCacheMode(true)` 落到这套 API 上（见 [Integration](/docs/CS/SE/Caffeine/Integration.md)）。

## Error Semantics

| 场景 | 行为 |
| :--- | :--- |
| `load` 抛异常 | 原样抛给 `get` 调用方；不缓存；下次读重试 |
| `loadAll` 部分失败 | 异常上抛，已成功的条目按实现决定是否入缓存 |
| `refresh` / `reload` 失败 | 记 `loadFailureCount`，摘除 refreshes 记录，**旧值保留** |
| `get(key, fn)` 的 fn 抛异常 | mapping 不建立，异常上抛 |
| executor 拒绝任务 | 写路径退化为调用线程同步维护；加载任务失败按对应异常路径处理 |

## Links

- [Caffeine](/docs/CS/SE/Caffeine.md)
- [Expiration](/docs/CS/SE/Caffeine/Expiration.md)
- [Integration](/docs/CS/SE/Caffeine/Integration.md)
- [Operations](/docs/CS/SE/Caffeine/Operations.md)
- [Concurrency](/docs/CS/SE/Concurrency.md)
- [Cache](/docs/CS/SE/Cache.md)

## References

1. [Caffeine 官方 Wiki – Populate a Cache](https://github.com/ben-manes/caffeine/wiki/Population)
2. [ben-manes/caffeine 源码：LoadingCache.java](https://github.com/ben-manes/caffeine/blob/v3.3.1/caffeine/src/main/java/com/github/benmanes/caffeine/cache/LoadingCache.java)
