## Introduction

Caffeine 的架构可以用一个反差概括：**对外是一张普通的 `ConcurrentHashMap`，对内所有「顺序」都是延迟计算的**。读写路径只做两件事——查表、往缓冲里投递事件；淘汰、过期、引用清理这些有成本的工作全部推迟到维护循环里批量完成。本页讲清这台机器的骨架：数据布局、读写路径、维护循环的每一步、无锁与有锁的边界，以及与 Guava 的分代差异。淘汰算法本身见 [Eviction](/docs/CS/SE/Caffeine/Eviction.md)，时间维度见 [Expiration](/docs/CS/SE/Caffeine/Expiration.md)。

## Data Layout

`BoundedLocalCache` 的核心字段：

```java
final ConcurrentHashMap<K, Node<K, V>> data;   // 存储本体
final ReentrantLock evictionLock;              // 维护循环专用锁
final Buffer<Node<K, V>> readBuffer;           // 读事件环形缓冲
final MpscGrowableArrayQueue<Runnable> writeBuffer;  // 写事件 MPSC 队列
final Executor executor;                       // 维护任务执行器
```

`Node` 不是裸 value：除了 key/value/next，它还挂着**访问顺序链表**（window / probation / protected 三条双向队列）与**写顺序链表**的指针，以及写时间、访问时间、可变过期时间三个时间戳。链表指针让「把某个条目从队列一头挪到另一头」是 O(1)，而不需要遍历。

三条访问顺序队列对应 W-TinyLFU 的三个区域（切分与晋升规则见 [Eviction](/docs/CS/SE/Caffeine/Eviction.md)）；写顺序队列则服务 `expireAfterWrite`——新写入排在队尾，队首就是最早写入的条目，过期检查从队首 peek 即可。

## Read Path

一次 `cache.getIfPresent(key)`：

```
data.get(key)
   │
   ├── 未命中 ────────────────────▶ 返回 null（同步 Cache 不自己回源）
   │
   └── 命中 ──▶ afterRead(node, now, recordHit)
                 ├── statsCounter().recordHits(1)
                 ├── readBuffer.offer(node)        // 延迟应用访问顺序
                 │     └── 返回 FULL ──▶ shouldDrainBuffers ──▶ scheduleDrainBuffers()
                 └── refreshIfNeeded(node, now)    // 需要则触发异步刷新
```

两个关键设计：

- **读缓冲是有条件的**：`readBuffer = (tracksAccess && !fastpath()) ? new BoundedBuffer<>() : Buffer.disabled()`。只有当缓存「跟踪访问」——即配了大小淘汰、`expireAfterAccess`、weakKeys/weakValues/collectKeys/collectValues——时读事件才需要入队；否则读就是一次纯 CHM get，连 offer 都省掉。
- **读缓冲是环形缓冲**：多生产者用 CAS 抢占槽位（允许虚假失败），单消费者排干；装满时最后一个 offer 者返回 `FULL`，触发一次及时的 drain，避免事件无限堆积。

维护循环排干读缓冲时，对每个节点执行 `onAccess`：频率草图自增、按所在区域重排访问顺序、给自适应窗口记录一次命中。**也就是说命中率的统计与晋升都不是在读那一刻发生的，而是维护时补算的**——这是「读路径基本无锁」的代价与解法。

## Write Path

一次 `cache.put(key, value)`：

```
data.put(key, value)
   │
   └── afterWrite(task)
         ├── writeBuffer.offer(task) ──成功──▶ scheduleDrainBuffers()
         │
         └── 失败（队列满且无法增长）──▶ 当前线程自己 lock() + maintenance(task)
```

- **写缓冲是 MPSC 队列**：`MpscGrowableArrayQueue` 是 JCTools 2.0 的 shaded 副本（随 caffeine 源码发布在 `cache` 包内），初容量 4，最大 `128 × ceilingPowerOfTwo(NCPU)`，按 chunk 链式增长、扩容不拷贝旧元素。
- **提交维护是带状态机的**：`scheduleDrainBuffers` 先 `tryLock` 抢到 `evictionLock`，把 `drainStatus` CAS 成 `PROCESSING_TO_IDLE`，再把 `drainBuffersTask` 提交给 executor；抢不到锁就直接返回（说明维护已在排队）。executor 抛异常（如被 shutdown 拒绝）时退化为**在调用线程上同步执行**维护。
- **写线程兜底**：offer 失败时，写线程会尝试自己拿锁执行维护——这是对「executor 被写操作占满、维护任务排不进来」的自我保护。官方注释明确列出它无法解决的情况（长计算的 eviction listener、victim 正在被计算等），这些情况会打日志提醒解耦。

## Maintenance Loop

维护循环是 Caffeine 的心脏，由 `PerformCleanupTask`（写入路径触发）或 `Pacer`（过期到期触发）调到 executor 上执行：

```java
void maintenance(Runnable task) {
    drainReadBuffer();        // 应用访问顺序：频率自增、晋升/重排、窗口统计
    drainWriteBuffer();       // 执行写任务：最多 WRITE_BUFFER_MAX 个
    drainKeyReferences();     // 清理被 GC 的弱键（最多 REFERENCE_THRESHOLD 次探测）
    drainValueReferences();   // 清理被 GC 的弱值/软值
    expireEntries(now);       // 过期：写序/访问序队列 + 时间轮，各最多 1000 项
    evictEntries(now);        // 淘汰：W-TinyLFU 窗口搬运 + 准入比较
}
```

每一步都有摊销上限，这是「单个维护循环不会长时间持锁」的保证：

| 步骤 | 上限常量 | 值 |
| :--- | :--- | :--- |
| 窗口条目搬运 | `QUEUE_TRANSFER_THRESHOLD` | 1,000 |
| 过期条目淘汰 | `EXPIRATION_THRESHOLD` | 1,000 |
| 引用队列探测 | `REFERENCE_THRESHOLD` | 1,000 |
| 写任务排干 | `WRITE_BUFFER_MAX` | 128 × 2^⌈log₂ NCPU⌉ |

没排完的 backlog 通过 `drainStatus`（`IDLE` / `REQUIRED` / `PROCESSING_TO_IDLE` / `PROCESSING_TO_REQUIRED`）登记为「仍需要维护」，由后续写操作或 pacer 重新武装，分批消化。`cache.cleanUp()` 是给测试与主动收敛用的同步入口：拿锁、跑满一轮、释放。

## Concurrency Model

- **读无锁、写少锁、维护一把锁**：读写路径只碰 CHM 与无锁缓冲；`evictionLock`（ReentrantLock）只被维护循环持有，且每轮工作量有界。
- **同 key 并发加载由 CHM bin 锁合并**：`get(key, mappingFunction)` 与 `computeIfAbsent` 依赖 bin 锁保证「函数对同一 key 最多执行一次」，期间其他线程对**同一 bin** 的更新会被阻塞——所以映射函数必须短，且不得回调修改本缓存（否则抛 `IllegalStateException`）。
- **executor 默认 `ForkJoinPool.commonPool()`**：维护任务与用户的异步加载（`CacheLoader` 的 `load`、`refresh`）共用。`rescheduleCleanUpIfIncomplete` 对 commonPool 有特殊分支——立即重新 `scheduleDrainBuffers` 而不是走 pacer，避免 caller-runs 策略把惩罚转嫁给调用线程。
- **等待锁超时会说话**：写操作等待维护超过 30 秒（`WARN_AFTER_LOCK_WAIT_NANOS`）会打警告，提示把长计算从 map 操作里解耦；put 的自旋等待上限是 1023 次（`MAX_PUT_SPIN_WAIT_ATTEMPTS`）。
- **序列化只保配置不保数据**：带 CacheLoader 的 cache 实现 `Serializable`，但反序列化得到的是空 cache——executor、scheduler、listener 均不保留，序列化缓存没有实际用途。

## Why It Beats Guava

| 维度 | Guava Cache | Caffeine |
| :--- | :--- | :--- |
| 并发结构 | 分段 `ReentrantLock`（段数固定） | 单张 `ConcurrentHashMap` + 无锁缓冲 |
| 读路径 | 段内同步 + 访问顺序重排 | 纯 CHM get + 环形缓冲投递 |
| 淘汰算法 | LRU（并发模式近似） | W-TinyLFU（频率准入） |
| 过期组织 | 每 entry 比较时间戳 | 时间排序队列 + 层级时间轮 |
| 底层访问 | `sun.misc.Unsafe`（2.x） | VarHandle（3.x），无 Unsafe 弃用困扰 |
| Java 基线 | Java 8 | Java 11（3.x） |

结论层面的差异（吞吐数量级、命中率曲线）随工作负载而变，不要引用单一 benchmark 数字；可复现的对比方式是同一负载下跑两侧的官方模拟器或自建基准。迁移层面的兼容性（spec 语法一致、Guava 适配 artifact）见 [Integration](/docs/CS/SE/Caffeine/Integration.md)。

## Links

- [Caffeine](/docs/CS/SE/Caffeine.md)
- [Eviction](/docs/CS/SE/Caffeine/Eviction.md)
- [Expiration](/docs/CS/SE/Caffeine/Expiration.md)
- [Concurrency](/docs/CS/SE/Concurrency.md)

## References

1. [Caffeine 官方 Wiki – Design](https://github.com/ben-manes/caffeine/wiki/Design)
2. [ben-manes/caffeine 源码：BoundedLocalCache.java](https://github.com/ben-manes/caffeine/blob/v3.3.1/caffeine/src/main/java/com/github/benmanes/caffeine/cache/BoundedLocalCache.java)
3. [JCTools](https://github.com/JCTools/JCTools)
