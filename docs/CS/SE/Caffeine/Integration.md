## Introduction

Caffeine 进入工程的路径主要有四条：Spring Cache 抽象的 provider（`CaffeineCacheManager`）、Spring Boot 的 spec 属性、JSR-107 的官方适配 artifact，以及 Guava 迁移的适配 artifact。这一页只写 **Caffeine 侧**的接口与语义——Spring Boot 的装配顺序、provider 优先级与 `@Cacheable` 注解语义分别见 [Spring Boot Cache](/docs/CS/Framework/Spring_Boot/cache.md) 与 [Spring Cache](/docs/CS/Framework/Spring/Cache.md)，这里只链接不重述。版本基线：Spring Framework 7.x（`CaffeineCacheManager` 要求 Caffeine 3.0+）、Spring Boot 4.x。

## Spring Cache Integration

`CaffeineCacheManager`（spring-context-support）把每个命名 cache 包成 `CaffeineCache`：

```java
@Bean
CacheManager cacheManager() {
  CaffeineCacheManager manager = new CaffeineCacheManager();
  manager.setCaffeine(Caffeine.newBuilder()
      .maximumSize(10_000)
      .expireAfterWrite(Duration.ofMinutes(10))
      .recordStats());
  return manager;
}
```

源码层面的事实：

- **默认 builder 是 `Caffeine.newBuilder()`——没有任何容量与过期限制**。不 `setCaffeine` / `setCaffeineSpec` 的 `CaffeineCacheManager` 产出的是无上限缓存；
- `setCaffeineSpec(CaffeineSpec)` 与 `setCacheSpecification(String)` 都走 `Caffeine.from(...)`，spec 语法见下文；
- `registerCustomCache(name, cache)` 注册预建实例（含 `AsyncCache`，6.1 起），与 spec 构建的动态缓存并存；
- `CaffeineCache` 的核心映射：
  - `get(key, Callable)` → `cache.get(key, LoadFunction)`——**`@Cacheable(sync = true)` 的防击穿就落在这一行**，复用 Caffeine 的按 key 原子加载；
  - `putIfAbsent` → 同样走 `cache.get(key, callable)`；
  - `lookup` → 若是 `LoadingCache` 走 `loadingCache.get(key)`（会回源），否则 `getIfPresent`；
  - `evict` → `invalidate(key)`；`clear` → `invalidateAll`；
- `allowNullValues` 默认 `true`；`setAsyncCacheMode(true)` 后经 `AsyncCache` 支持 Spring 7 的 `Cache#retrieve`（含 early-determined miss），可再配 `AsyncCacheLoader`。

## Spec Strings

`CaffeineSpec` 把 builder 配置压成逗号分隔的字符串，是 `spring.cache.caffeine.spec` 的解析目标：

```properties
spring.cache.caffeine.spec=maximumSize=10000,expireAfterWrite=10m,recordStats
```

| 键 | 对应 builder 方法 |
| :--- | :--- |
| `initialCapacity=[int]` | `initialCapacity` |
| `maximumSize=[long]` | `maximumSize` |
| `maximumWeight=[long]` | `maximumWeight` |
| `expireAfterAccess=[duration]` | `expireAfterAccess` |
| `expireAfterWrite=[duration]` | `expireAfterWrite` |
| `refreshAfterWrite=[duration]` | `refreshAfterWrite` |
| `weakKeys` / `weakValues` / `softValues` | 引用强度 |
| `recordStats` | 统计开关 |

- 时长支持 ISO-8601（`PT10M`）或整数加 `d`/`h`/`m`/`s`；**没有毫秒及以下单位的短语法**；
- 键不可重复；`maximumSize` 与 `maximumWeight`、`weakValues` 与 `softValues` 不可同时出现；
- **spec 语法与 Guava `CacheBuilder.from(spec)` 完全一致**（同一批键、同时长格式），从 Guava 迁移基本是复制粘贴；
- spec **表达不了** `executor` / `scheduler` / `removalListener` / `weigher` / `ticker`——这些只能在代码里配，是「spec 配了却看不到效果」类问题的常见原因（尤其是默认 `scheduler = disabledScheduler`，见 [Expiration](/docs/CS/SE/Caffeine/Expiration.md)）。

## JCache (JSR-107)

官方适配 artifact：`com.github.ben-manes.caffeine:jcache`（模块 `caffeine-jcache`，包 `com.github.benmanes.caffeine.jcache`）。`CaffeineCachingProvider` 经 `java.util.ServiceLoader` 被发现，`Caching.getCachingProvider()` 即可拿到；JCache API 仍在 `javax.cache` 命名空间（JSR-107 从未迁去 jakarta）。

注意与 Spring Boot 的相互作用：**classpath 上同时存在 JCache 实现（含 caffeine-jcache）与 Caffeine 核心时，Boot 的 provider 检测顺序里 JCache 排在 Caffeine 前面**——实际生效的很可能是 JCache 那条链路。要锁死 Caffeine 就显式 `spring.cache.type=caffeine`，完整顺序见 [Spring Boot Cache](/docs/CS/Framework/Spring_Boot/cache.md)。

## Guava Adapter

官方适配 artifact：`com.github.ben-manes.caffeine:guava`，`CaffeinatedGuava` 把 Caffeine cache 包装成 Guava 的 `Cache` / `LoadingCache` 接口。典型用法是过渡期：业务代码仍面向 Guava API，底层换成 Caffeine 的淘汰与并发实现。spec 语法一致（见上）让配置迁移成本接近零。

## JetCache

JetCache 的两级缓存把本地端交给 Caffeine（远程端走 Redis），并以注解形式提供 TTL、自动刷新、防击穿——这些能力在 Caffeine 侧分别对应 `expireAfterWrite`、`refreshAfterWrite`、`get(key, fn)`。本地缓存的实现原理见 [Architecture](/docs/CS/SE/Caffeine/Architecture.md)，JetCache 的封装与两级一致性见 [JetCache](/docs/CS/SE/JetCache.md)。

## Links

- [Caffeine](/docs/CS/SE/Caffeine.md)
- [Spring Boot Cache](/docs/CS/Framework/Spring_Boot/cache.md)
- [Spring Cache](/docs/CS/Framework/Spring/Cache.md)
- [JCache](/docs/CS/Java/JCache.md)
- [JetCache](/docs/CS/SE/JetCache.md)
- [Population](/docs/CS/SE/Caffeine/Population.md)

## References

1. [ben-manes/caffeine 源码：CaffeineSpec.java](https://github.com/ben-manes/caffeine/blob/v3.3.1/caffeine/src/main/java/com/github/benmanes/caffeine/cache/CaffeineSpec.java)
2. [Spring Framework 源码：CaffeineCacheManager.java](https://github.com/spring-projects/spring-framework/blob/main/spring-context-support/src/main/java/org/springframework/cache/caffeine/CaffeineCacheManager.java)
3. [Spring Boot Reference – Caching](https://docs.spring.io/spring-boot/reference/io/caching.html)
