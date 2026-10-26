## Introduction

Caffeine 是 Java 的高性能**本地缓存**库，Google Guava Cache 的下一代重写（作者同为 Ben Manes）。Guava 的并发与淘汰算法按 Java 6 时代设计；Caffeine 把 segment 锁换成 `ConcurrentHashMap` 加无锁环形缓冲，把 LRU 换成带频率准入的 W-TinyLFU，读写吞吐与命中率都显著高于 Guava，也是 Spring Boot 生态里本地缓存的默认选择。它在空间（容量/权重）与时间（TTL/TTI/可变过期）两个维度淘汰 KV，两者由同一套维护循环统一驱动。

版本锚点 **3.3.1**（2026-10-13 发布，Maven Central 当前最新）。**3.x 要求 Java 11+**，Java 8 项目继续用 2.x（官方承诺维护）——3.0 起不再依赖 `sun.misc.Unsafe`，改走 VarHandle。所有结论以 3.3.1 源码（`com.github.benmanes.caffeine.cache` 包）与官方 Wiki 为准。

本页是**枢纽页**：只放定位、架构总览、适用边界与最要紧的几条反直觉事实；架构、淘汰、过期、加载、集成、运维六个方向各有分册展开。

## Architecture

Caffeine 的骨架是「一张 `ConcurrentHashMap` + 两条缓冲 + 一个维护循环」：

```
读：data.get(key) ──命中──▶ afterRead ──▶ readBuffer.offer(node) ──┐
                          │                                      ├─▶ 维护循环异步应用
写：data.put(key) ───────▶ afterWrite ─▶ writeBuffer.offer(task) ─┘
                                                                  │
维护循环（evictionLock 串行，默认跑在 ForkJoinPool.commonPool）：
  drainReadBuffer → drainWriteBuffer → 引用队列 → expireEntries → evictEntries
```

- **存储就是一张 `ConcurrentHashMap<K, Node>`**：`Node` 在 value/next 之外挂着访问顺序与写顺序的链表指针，维护循环（而不是读写路径）负责把这些顺序向量化地应用到淘汰与过期决策上。
- **读写路径不加淘汰锁**：读只往读缓冲投递节点，写只往写缓冲投递任务，真正的维护工作由 executor 异步批量完成；每条维护命令都有摊销上限（每轮最多搬运/淘汰约 1000 项），单个维护循环不会长时间持锁。
- **并发加载按 key 合并**：同 key 的并发 miss 由 CHM 的 bin 锁合并，`get(key, mappingFunction)` 的整个调用原子完成，函数对同一 key 最多执行一次——这是缓存击穿的防线。
- **淘汰算法是 W-TinyLFU**：窗口（LRU）+ 主区（ probation / protected 两级），用 4 位计数器的频率草图做准入；过期用层级时间轮与时间排序队列组织。

细节见 [Architecture](/docs/CS/SE/Caffeine/Architecture.md)（数据结构与读写路径）、[Eviction](/docs/CS/SE/Caffeine/Eviction.md)（W-TinyLFU 与频率草图）、[Expiration](/docs/CS/SE/Caffeine/Expiration.md)（时间轮、过期与刷新）、[Population](/docs/CS/SE/Caffeine/Population.md)（加载语义）、[Integration](/docs/CS/SE/Caffeine/Integration.md)（Spring 与生态桥接）、[Operations](/docs/CS/SE/Caffeine/Operations.md)（统计、调优与坑）。

## Map of This Section

六个分册对应使用 Caffeine 时六类不同的问题：

- **[Architecture](/docs/CS/SE/Caffeine/Architecture.md)**——「它到底怎么做到快」。CHM 加双缓冲的读写路径、维护循环的每一步、无锁/有锁的边界、与 Guava 的分代差异。理解所有其他分册的地图。
- **[Eviction](/docs/CS/SE/Caffeine/Eviction.md)**——「留谁汰谁由什么决定」。W-TinyLFU 三段结构、4 位频率草图与老化、准入比较与 hashDoS 防护、自适应窗口（WindowClimber）、大小与权重两种容量策略。调 `maximumSize` 之前必读。
- **[Expiration](/docs/CS/SE/Caffeine/Expiration.md)**——「时间维度怎么管」。写/访问/可变三种过期的实现差异、层级时间轮的规格、`refreshAfterWrite` 与 `expireAfterWrite` 的本质区别、移除通知与原因枚举。「过期了怎么还在」类问题的归属页。
- **[Population](/docs/CS/SE/Caffeine/Population.md)**——「值从哪来」。三种 cache 形态、`CacheLoader` 的批量与重载语义、`get(key, fn)` 的原子性与使用约束、`refresh` 的 in-flight 语义、`AsyncCache` 与同步视图的桥接。
- **[Integration](/docs/CS/SE/Caffeine/Integration.md)**——「怎么落到工程里」。`CaffeineCacheManager` 与 `@Cacheable(sync=true)` 的真实防线、spec 字符串语法（与 Guava 兼容）、JCache 与 Guava 两个官方适配 artifact、JetCache 两级缓存的本地端。Spring Boot 装配顺序见 Boot 侧专文。
- **[Operations](/docs/CS/SE/Caffeine/Operations.md)**——「上线之后怎么管」。`recordStats` 指标体系、Policy 内省、全部调优旋钮、引用类型语义、常见坑清单（自调用、null 值、TTL 抖动、executor 饱和）。

## Applicable Scenarios

Caffeine 的甜点区一句话概括：**读多写少、数据能放进单机内存、能容忍秒级不一致的单 JVM 缓存**。

适合：

- **本地热点数据**：配置、字典、权限、用户基础信息、热点商品——回源成本高而变化慢的数据；
- **抗回源峰值的 L1**：作为 Redis 前的第一级（本地 + 远程两级），把绝大多数热点读挡在进程内；
- **计算结果的 memoization**：相同入参的昂贵计算（报表、聚合、鉴权决策）；
- **Spring Cache 的默认 provider**：`@Cacheable` 声明式使用，`sync = true` 复用 Caffeine 的按 key 合并加载。

不适合：

- **强一致要求**：本地缓存天然是多副本的，任何写入都不会同步到其他实例；
- **数据量超出单机内存**：容量上限触发的是淘汰不是扩容，超量数据请用 Redis 等外部存储；
- **需要跨实例共享状态**：Caffeine 不做任何集群协同，多实例间各缓存各的。

| 条件 | 选择 |
| :--- | :--- |
| 单 JVM、读多写少、可容忍秒级不一致 | Caffeine |
| 需要跨实例共享、容忍网络一跳 | Redis |
| 既要本地又要共享、接受最终一致 | JetCache 两级（本地 Caffeine + 远程 Redis） |
| 强一致或数据量大到单机放不下 | 直接查源存储或换分布式缓存 |

## Facts Worth Pinning Down

最容易被默认值与版本坑到的几条，完整依据散布在各分册：

1. **默认不主动清理过期条目**：`scheduler` 默认是 `disabledScheduler`，过期只发生在缓存活动（或显式 `cleanUp()`）触发的维护循环里。想「到点就删」必须显式配 `Scheduler.systemScheduler()` 或自定义 scheduler，且调度是 best-effort，两次维护之间至少有约 1 秒的 pacing 间隔。
2. **3.x 要求 Java 11+**：还在 Java 8 的工程请锁 2.x。JDK 24 之后 `sun.misc.Unsafe` 弃用警告的常见来源之一就是老版本 Caffeine 的 `UnsafeAccess`。
3. **频率草图是约 8 字节/容量条目，不是 8 bit**：`FrequencySketch` 的 long 数组长度约等于 `maximumSize`，100 万容量的缓存要额外付约 8 MB 统计内存；且它是懒初始化的——缓存填充到约一半才分配。小缓存（默认下限 256）的内存占比会比直觉高。
4. **W-TinyLFU 的分区比例不是死的**：初始 window 约 1%、probation 约 20%、protected 约 79%，但 `WindowClimber` 会按命中统计自适应调整窗口大小（> 4096 用区域命中密度反馈，小缓存跨样本比较命中率），所以「窗口一定是 5%」这类说法是过时的。
5. **`refreshAfterWrite` 只对 `LoadingCache` 有效**，且由读触发、异步执行；纯 `Cache`（没有 CacheLoader）配了不报错，但永远不会刷新。
6. **淘汰是异步且有摊销上限的**：写事件进 MPSC 队列后由 executor 异步排干，每轮维护最多处理约 1000 项搬运/淘汰。executor 被占满时缓存会**暂时超过** `maximumSize`，此时写线程会「协助」执行维护；长计算放在 eviction listener 里会卡住整个维护循环（等待超 30 秒会打警告）。
7. **`get(key, mappingFunction)` 才是防击穿的正解**：整个调用原子完成、函数对同一 key 最多执行一次，其他线程的更新会被阻塞——所以函数必须短，且不得在函数内改这个缓存。
8. **`CaffeineCacheManager` 不配 spec 就是无上限缓存**：Spring 的 manager 默认 `Caffeine.newBuilder()`，没有任何容量与过期限制。忘配 `spring.cache.caffeine.spec` 的后果是内存只增不减，且没有任何报错。

## Links

- [Cache](/docs/CS/SE/Cache.md)
- [JetCache](/docs/CS/SE/JetCache.md)
- [Redis](/docs/CS/DB/Redis/Redis.md)
- [LRU](/docs/CS/Algorithms/LRU.md)

## References

1. [Caffeine 官方 Wiki](https://github.com/ben-manes/caffeine/wiki)
2. [ben-manes/caffeine v3.3.1 源码](https://github.com/ben-manes/caffeine/tree/v3.3.1)
3. [Caffeine v3.0.0 Release Notes（Java 11 基线、CacheWriter 移除）](https://github.com/ben-manes/caffeine/releases/tag/v3.0.0)
4. [Caffeine on Maven Central](https://central.sonatype.com/artifact/com.github.ben-manes/caffeine)
