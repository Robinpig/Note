## Introduction

Caffeine 是 Java 高性能**本地缓存**库（Google Guava Cache 的下一代重写，作者同一人），基于 Java 8+ 重写并发与淘汰算法，吞吐量显著高于 Guava，是 Spring Boot 默认的本地缓存提供者（通过 `spring-boot-starter-cache` 自动装配）。它在空间和时间两个维度淘汰 KV：空间维度是容量上限触发的大小淘汰，时间维度是 TTL/TTI 过期。

## 淘汰策略：W-TinyLFU

Caffeine 的核心竞争力是淘汰算法，而不只是"带过期的 ConcurrentHashMap"：

- **TinyLFU**：用 Count-Min Sketch 近似统计 key 的访问频率，只占约每 key 8 bit，在写入前判断新 key 是否比即将淘汰的 key 更有资格留下，显著抗扫描污染；
- **W-TinyLFU**：加入小窗口（Window，约 5%）保存新 key 以捕捉突发/一次性访问，主区再分 Probation 与 Protected 两级（类似 LRU 的晋升机制），兼顾 recency 与 frequency；
- 效果对比：命中率长期优于纯 LRU、ARC 等算法，接近理论最优，且 O(1) 摊销。算法全景对照见 [缓存驱逐](/docs/CS/SE/Cache.md?id=缓存驱逐) 与 [LRU](/docs/CS/Algorithms/LRU.md)。

## 时间过期

```java
Cache<String, User> cache = Caffeine.newBuilder()
        .maximumSize(10_000)                       // 空间维度：容量淘汰
        .expireAfterWrite(Duration.ofMinutes(10)) // 写后固定 TTL
        .expireAfterAccess(Duration.ofMinutes(5)) // 多久没访问就淘汰（TTI）
        .refreshAfterWrite(Duration.ofMinutes(1)) // 异步刷新（不阻塞读）
        .recordStats()                            // 命中率统计
        .build(key -> loadFromDb(key));           // CacheLoader：miss 时自动加载
```

实现要点：**过期检测用时间轮（hierarchical timing wheel）组织**，读写时顺带维护，而不是给每个 entry 挂定时器；清理是惰性的（发生在写操作后的维护阶段，读触发 `performCleanUp`），所以没有独立扫描线程也不会精准到毫秒。

**高并发下不要把大量 key 的过期时间设得过于接近**：同一瞬间集体失效会引发缓存雪崩，回源请求同时打到数据库。实践上给 TTL 加随机抖动（如 10min ± 2min），原理与缓存雪崩一致（见 [Cache 缓存失效](/docs/CS/SE/Cache.md)）。

`refreshAfterWrite` 与 `expireAfterWrite` 的区别：刷新是异步加载新值、旧值仍可返回（不阻塞、不击穿）；过期是先淘汰、下一次读同步回源（可能击穿，可借助 `get(key, callable)` 让同 key 并发只回源一次）。

## 并发模型

- 底层使用分片式哈希 + 无锁 Ring Buffer 缓冲写入事件（类似 Disruptor 的 striped buffer），把维护工作异步批处理，读路径基本无锁；
- 同一个 key 的并发加载通过 `ConcurrentHashMap#compute` 语义合并，天然防缓存击穿；
- 不支持分布式：它是单 JVM 本地缓存，多实例间不共享数据；需要共享时用 [Redis](/docs/CS/DB/Redis/Redis.md)，或本地+远程两级缓存（[JetCache](/docs/CS/SE/JetCache.md) 支持注解式两级缓存）。

## 适用边界

适合：读多写少、数据量可放入单机内存、能容忍秒级不一致（配置、字典、用户基础信息、热点商品）；不适合：强一致要求、数据量超出内存、需要跨实例共享状态的场景。Spring 中通常与 `@Cacheable` 配合，但要注意同一个类内自调用注解不生效（AOP 代理限制）。

## Links

- [Cache](/docs/CS/SE/Cache.md)
- [JetCache](/docs/CS/SE/JetCache.md)
- [Redis](/docs/CS/DB/Redis/Redis.md)
- [LRU](/docs/CS/Algorithms/LRU.md)
- [Scheduled Task](/docs/CS/SE/Scheduled_Task.md)

## References

1. [Caffeine 官方 Wiki](https://github.com/ben-manes/caffeine/wiki)
2. [TinyLFU 论文](https://arxiv.org/abs/1512.00727)
