## Introduction

Caffeine 上线之后的问题基本分三类：看不见（没有统计）、配错了（旋钮用错或漏配）、想不到（默认值与直觉不符）。这一页按这三类组织：`recordStats` 指标体系与 Policy 内省、全部调优旋钮的速查表、引用类型的语义、以及一份按出现频率排序的坑清单。算法与时间维度的细节分别见 [Eviction](/docs/CS/SE/Caffeine/Eviction.md) 与 [Expiration](/docs/CS/SE/Caffeine/Expiration.md)。

## Stats and Introspection

```java
Cache<String, User> cache = Caffeine.newBuilder()
        .maximumSize(10_000)
        .recordStats()                       // 不开这个开关，stats() 全是 0
        .build();

CacheStats stats = cache.stats();
stats.hitRate();          // hitCount / (hitCount + missCount)
stats.evictionCount();    // 因 SIZE 淘汰的次数——容量配没配够，看它
stats.totalLoadTime();    // 回源总耗时（LoadingCache）
```

`CacheStats` 字段：`hitCount` / `missCount` / `loadSuccessCount` / `loadFailureCount` / `totalLoadTime` / `evictionCount` / `evictionWeight`。不调 `recordStats()` 时统计走 no-op 实现（`StatsCounter` 接口的禁用实现），`stats()` 返回全零而非 null。

指标导出：Boot + Micrometer 场景可把 `CacheStats` 接到 `MeterRegistry`（自定义 gauge 或现成的 cache metrics 绑定），Actuator 侧消费方式见 [Spring Boot Actuator](/docs/CS/Framework/Spring_Boot/actuator.md)；纯 JVM 侧也可以定期打点 `stats()`。**判断容量是否不足的第一指标是 `evictionCount` 的增长速率**，而不是内存占用。

运行时内省走 `Policy`（不需要开统计）：

```java
cache.policy().eviction().weightedSize();   // 当前加权占用
cache.policy().eviction().maximum();        // 当前上限（含自适应调整后的值）
cache.policy().expireAfterAccess();         // 当前 TTI 配置
cache.policy().refreshes();                 // in-flight 刷新快照（3.0 新增）
```

`estimatedSize()` 也是近似值（CHM 的求和计数），精确占用用 `policy().eviction().weightedSize()`。

## Tuning Knobs

| 旋钮 | 默认 | 说明与坑 |
| :--- | :--- | :--- |
| `initialCapacity` | 16 | CHM 初始容量，load factor 0.75；预知量级时设一次，避免反复 rehash |
| `maximumSize` | 无（不设则无上限） | 按条数；触发 W-TinyLFU 淘汰；0 = 加载后立即淘汰 |
| `maximumWeight` + `weigher` | 无 | 与 `maximumSize` 互斥；权重函数要廉价且稳定 |
| `expireAfterWrite` / `expireAfterAccess` | 无 | 惰性清理；要主动删需配 scheduler |
| `expireAfter(Expiry)` | 无 | 每条目可变时长；与固定过期互斥 |
| `refreshAfterWrite` | 无 | 仅 `LoadingCache` 有效；读触发 + 异步 |
| `executor` | `ForkJoinPool.commonPool()` | 维护与异步加载共用；高负载建议换专用线程池 |
| `scheduler` | **`disabledScheduler`** | 不配 = 不过期不主动清理；`systemScheduler()` 才到点调度 |
| `weakKeys` / `weakValues` / `softValues` | 强引用 | GC 可回收；weakKeys 改用 `==` 比较 key |
| `removalListener` / `evictionListener` | 无 | 异步 cache 的通知在 executor 上跑；长计算卡维护循环 |
| `recordStats` | false | 生产建议开，成本可忽略 |
| `ticker` | 系统时钟 | 测试注入虚拟时钟，避免 sleep |

executor 选择：默认的 commonPool 与业务任务竞争；维护被饿死的极端表现是缓存暂时超过 `maximumSize`（写线程会兜底执行维护，但吞吐已受损）。给缓存配专用 executor 时注意 `rescheduleCleanUpIfIncomplete` 对它没有 commonPool 的即时重排分支，剩余 backlog 靠 pacer 补。

## Reference Types

- `weakKeys()`：key 弱引用，GC 回收后条目经引用队列清理，`RemovalCause.COLLECTED`；**key 比较改为恒等（`==`）**，`equals`/`hashCode` 被忽略——自定义 key 类用前先想清楚；
- `weakValues()`：value 弱引用，内存紧张即被回收，语义接近「缓存随时可能没有」；
- `softValues()`：软引用，只在 JVM 真正缺内存（`OutOfMemoryError` 前）回收；代价是每次访问都可能触发 GC 压力，且 JVM 策略不可控；
- 两者都可与 `evictionListener` 之外的配置组合，但 **不能**与 `evictionListener` + weakKeys 同用（builder 层禁止，因为 listener 拿不到已被回收的 key 做有意义的通知）。

工程建议：容量可控就用 `maximumSize` / `maximumWeight`，引用强度是最后手段——它把「容量管理」变成了「GC 行为管理」，而后者不可预测。

## Common Pitfalls

按踩坑频率排序：

1. **`@Cacheable` 自调用不生效**：同类内方法互调走 this 而非代理，注解被绕过。AOP 通用约束，不是 Caffeine 的问题，但 Caffeine 场景最常见；
2. **TTL 集体到期引发缓存雪崩**：大量 key 同一时刻写入、同一 TTL，到期时回源请求同时打到 DB。给 TTL 加随机抖动（如 10min ± 2min），原理见 [Cache](/docs/CS/SE/Cache.md) 的雪崩一节；
3. **忘配 `scheduler`，过期条目长期滞留**：默认惰性清理，只写不读的缓存（如预加载后只读一次）会记住过期的值。要么配 scheduler，要么接受惰性语义；
4. **`CaffeineCacheManager` 不配 spec = 无上限**：Spring 侧最常见的 Caffeine 事故，内存只增不减且无任何报错（见 [Integration](/docs/CS/SE/Caffeine/Integration.md)）；
5. **`refreshAfterWrite` 配在纯 `Cache` 上**：不报错、不刷新，静默失效；
6. **两个 listener 用错场景**：`removalListener` 在 executor 上异步执行，长计算会占满与加载、刷新共用的线程池，排队中的通知还持有 key/value 强引用——「value 较大 + 高并发 + 调度不及时」正是线上 FGC 的常见机制（同类案例见 [Cache](/docs/CS/SE/Cache.md)）；`evictionListener` 则在原子移除中同步执行，长计算直接阻塞淘汰，是「等待维护锁超 30 秒」警告的主要来源。按语义选：事后通知用 `removalListener`，随移除原子完成用 `evictionListener`，两者都别放长计算；
7. **`null` 值语义**：`get(key, fn)` 的 fn 返回 null 不入缓存，下次仍 miss；要缓存空结果防穿透，用哨兵值或 `put` 显式写入，Spring 侧对应 `allowNullValues`；
8. **自定义 key 的 `equals`/`hashCode`**：Caffeine 直接复用 key 的哈希；劣质哈希（如全同 hash）会让 CHM 退化、草图失准，还会触发准入的随机分支频率上升；
9. **序列化缓存**：带 loader 的实现标了 `Serializable`，但 executor/scheduler/listener 不保留、数据不保留——不要把它当分布式传递手段；
10. **2.x 升 3.x 的断点**：Java 基线从 8 提到 11；`CacheWriter` 被移除（用 Map computation + `evictionListener` 替代）；`LoadingCache.refresh` 改为返回 in-flight future；`CacheStats` 构造器变化。升级前对照 v3.0.0 release notes。

## Links

- [Caffeine](/docs/CS/SE/Caffeine.md)
- [Eviction](/docs/CS/SE/Caffeine/Eviction.md)
- [Expiration](/docs/CS/SE/Caffeine/Expiration.md)
- [Integration](/docs/CS/SE/Caffeine/Integration.md)
- [Spring Boot Actuator](/docs/CS/Framework/Spring_Boot/actuator.md)
- [APM](/docs/CS/SE/APM.md)

## References

1. [Caffeine 官方 Wiki](https://github.com/ben-manes/caffeine/wiki)
2. [Caffeine v3.0.0 Release Notes（升级断点清单）](https://github.com/ben-manes/caffeine/releases/tag/v3.0.0)
3. [ben-manes/caffeine 源码：CacheStats.java](https://github.com/ben-manes/caffeine/blob/v3.3.1/caffeine/src/main/java/com/github/benmanes/caffeine/cache/CacheStats.java)
