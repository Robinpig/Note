## Introduction

Memcached 1.5.0（2017-02）之前用的是**单段双向链表 LRU**：每个 slabclass 一条 LRU 队列，新 item 插头部，淘汰从尾部取。item 被 GET 到时 bump 到头部，但 bump 有一个 60 秒的节流窗口（防止高频热点 item 反复触发锁争用）。

单段 LRU 在早期 co-located（缓存和应用同机部署）场景下够用，但随着部署模式变了（专用缓存节点、大量 RAM、请求批量 fetch 上百个 key），两个问题越来越突出：

1. **过期 item 占坑**：TTL 到期的 item 不会主动释放内存，必须等下次被 GET 到或者尾部被淘汰时才清理——如果它长期没被访问，就一直在内存里白白占位置。
2. **锁争用**：所有 item 的 bump 和淘汰都要抢同一把 LRU 锁，读密集负载下单核能跑满但多核扩展受阻。

1.5.0 起默认启用的 **modern LRU** 把每个 slabclass 的 LRU 拆成四段独立队列，由后台线程主动维护和爬行回收过期 item，同时把锁粒度降到每段一把。

## Segmented LRU

每个 slabclass 的 LRU 被拆成四条独立的双向链表：**HOT → WARM → COLD → TEMP**。每条链表有自己的 mutex。每个 item 头部有两个活动位：

- `FETCHED`：这个 item 被 GET 过至少一次。
- `ACTIVE`：这个 item 被 GET 过至少两次（即第二次 fetch 后置位）。

### HOT（Probation Queue）

新进 item 的第一站。HOT 队列是「试用期」——item 刚写进去，可能有强时间局部性，也可能就是个很快过期的临时值。

- **不做 bump**：HOT 内的 item 被 fetch 时不触发 bump，省掉大量锁争用。
- **出队规则**：HOT 尾部 item 如果是 `ACTIVE` → 移到 WARM；如果不是 `ACTIVE` → 直接移到 COLD。
- **大小限制**：按内存百分比（默认 20%）和尾部年龄（相对于 COLD 尾部年龄）双重限制。
- **直接回收**：当 COLD 也没 item 可淘汰时，worker 线程进入 Direct Reclaim 模式，从 HOT/WARM 尾部强制挤出 item。

### WARM（Buffer Queue）

WARM 是给「扫描型访问模式」（比如爬虫翻旧帖子）的缓冲区。被 fetch 过至少两次的 item 才能进 WARM，意味着它在某种程度上被重复访问过。

- **尾部 bump**：WARM 尾部 item 如果是 `ACTIVE`，被再次 fetch 时 bump 回 WARM 头部。
- **出队规则**：尾部 inactive item → 移到 COLD。
- **大小限制**：按内存百分比（默认 30%）和尾部年龄限制。

### COLD（Victim Queue）

COLD 存放最不活跃的 item，是真正的**淘汰受害者来源**。

- **tail eviction**：内存不够时从 COLD 尾部取 item 淘汰（先检查是否已过期，过期则直接回收，否则从哈希表摘除后释放）。
- **异步 bump**：COLD 内 item 被 fetch 时不立即 bump，而是放进一个异步 bump 队列，由 LRU Maintainer 批量处理。这避免了 worker 线程在 COLD 锁上长时间阻塞。
- **bump queue overflow**：高并发下异步 bump 队列可能溢出——此时 COLD 内的 bump 变成概率性的（不是所有请求都 bump），保证 worker 线程不阻塞。
- **无大小限制**：COLD 可以无限增长，直到内存耗尽触发淘汰。

### TEMP（TTL-Short Queue）

TEMP 专门接住 TTL 非常短（默认阈值由 `temp_ttl` 参数控制，默认 -1 关闭）的新 item。

- **不参与 bump**：TEMP 内 item 永远不 bump，直接在 TTL 到期后由 LRU Crawler 回收。
- **不流向其它段**：TEMP 内 item 不会流到 HOT/WARM/COLD。
- **目的**：TTL 几秒的临时 item 本来也不会被多次 fetch，没必要让它在 HOT 里排完整个生命周期才被淘汰——直接丢进 TEMP 等过期回收更高效，也减少了 HOT 的队列长度和迁移开销。

### Size and Tail Age Limits

HOT 和 WARM 有双重限制：

| 参数 | 默认值 | 含义 |
| :-- | :-- | :-- |
| `percent_hot` | 20% | HOT 最多占该 slabclass 可用内存的比例 |
| `percent_warm` | 30% | WARM 最多占该 slabclass 可用内存的比例 |
| `max_hot_age_factor` | 0.1 | HOT 尾部 item 的最大年龄 ≤ COLD 尾部年龄 × 0.1 |
| `max_warm_age_factor` | 2.0 | WARM 尾部 item 的最大年龄 ≤ COLD 尾部年龄 × 2.0 |

尾部年龄限制的核心思想是：**防止很老的 item 长期停留在 HOT/WARM 队列里**。如果 COLD 的尾部 item 已经很老了，而 HOT 尾部还有一个更老的 item（只是因为恰好被 fetch 过第二次所以一直在 WARM 里），那么这个 WARM 尾部 item 就被强制挪到 COLD。

## LRU Maintainer Thread

LRU Maintainer 后台线程每秒触发一次，执行以下工作：

1. **遍历每个 slabclass 的四段子 LRU**。
2. **检查各段的大小限制**：如果 HOT 超过 `percent_hot`，从尾部移 item 到 WARM/COLD；WARM 同理。
3. **检查尾部年龄限制**：HOT/WARM 尾部 item 超过年龄阈值则挪到 COLD。
4. **回收尾部已过期 item**：HOT/WARM/COLD/TEMP 尾部如果 item 已过 TTL，直接从哈希表摘除并释放 chunk。
5. **处理 COLD 的异步 bump 队列**：把队列中的 item 移到 WARM。
6. **处理 Direct Reclaim 触发**：如果 COLD 已经空了但还有新 item 要写入，LUR Maintainer 会从 HOT/WARM 强制挤出 item 到 COLD。

LRU Maintainer 是 modern LRU 能正常运转的核心驱动者——没有它，四段 LRU 会失去平衡，COLD 被压得很小而 HOT 膨胀到容纳不下新 item。

## LRU Crawler

LRU Maintainer 每秒一次只处理各段的**尾部**。但如果一个 slabclass 里有几百万 item，大量过期 item 散落在链表中间，仅靠尾部回收不够快。LRU Crawler 是第二个后台线程，专门解决这个问题。

### How It Works

Crawler 的工作方式很巧妙：

1. **插入 crawler item**：Crawler 在每个 slabclass 的每段子 LRU **尾部**插入一个伪装的 crawler item。
2. **向后爬行**：它从尾部开始，沿着 LRU 链表**向后（即向头部方向）** 逐个检查 item。
3. **回收过期 item**：每遇到一个已过期的 item，直接从哈希表摘除、释放 chunk、将其从 LRU 链表中摘除（这会让链表上的下一个 item 自动成为 crawler 的新后继）。
4. **同时扫描所有 slabclass 的所有段**：class 1 的 HOT 扫一个 → class 1 的 WARM 扫一个 → ... → class 2 的 HOT 扫一个 → ...。这样大 slabclass（item 少、chunk 大）很快扫完，小 slabclass（item 多、chunk 小）慢慢爬。

### Histogram-Driven Scheduling

Crawler 在爬行过程中为每个 slabclass 的每段子 LRU 建一个 **TTL 剩余直方图**。扫描完一轮后，它根据直方图决定下一轮什么时候开始：

- 如果某段的 item 大部分还有 0 TTL（已过期但没被回收），立即重扫。
- 如果某段的 item 大部分还有 5 分钟 TTL，安排 5 分钟后再扫。
- 可以为同 slabclass 的不同段安排不同的重扫频率：COLD 可能每 10 分钟扫一次，TEMP 可能每 30 秒扫一次（因为 TEMP 里都是 TTL 很短的 item）。

这使得 Crawler 的扫描强度自适应地跟数据分布对齐，不会浪费 CPU 在 TTL 还很充裕的 item 上。

### Concurrent Crawling

Crawler 和 LRU Maintainer 以及 worker 线程可以并发操作同一段 LRU——因为它们加的是**同一条 mutex**。Crawler 加锁检查 item 是否过期、摘除过期 item 后立即释放锁，不会长时间阻塞 worker 的 GET/SET。

### `lru_crawler metadump`

Crawler 还暴露了一个管理命令 `lru_crawler metadump <classid|all>`，用于异步打印所有 item 的 key 和元信息（过期时间、最后访问时间、CAS value、slabclass、size、FETCHED 状态）。这在定位缓存热点、排查过期 item 比例时非常有用。

## Direct Reclaim

当某个 slabclass 的 COLD LRU **完全为空**时（所有 item 都活跃，或 slabclass 刚建好还没填过数据），如果此时有新 item 要 SET，worker 线程就进入 **Direct Reclaim 模式**：worker 自己阻塞在该 slabclass 的锁上，强制从 HOT 或 WARM 尾部挤出 item 到 COLD，直到 COLD 有 item 可淘汰为止。

这是 modern LRU 的**兜底机制**，确保即使在极端负载下（高 SET 频率、所有 item 都非常活跃），新写请求也不会被拒绝。但 Direct Reclaim 会阻塞 worker 线程，应该尽量避免触发——通常意味着内存配置不够或增长因子不合适。

## Flat vs Segmented Mode

Memcached 支持在运行时通过 `lru mode flat|segmented` 切换 LRU 模式：

- **flat**：退回到传统的单段双向链表 LRU（所有 item 一条队列）。
- **segmented**：四段式 LRU（1.5.0 起默认）。

切换时 LRU Maintainer 会在后台把 HOT/WARM 里的 item 逐步 drain 到 COLD，然后重建单一的 LRU 链表。这个过程不会阻塞请求，但切换期间内存效率会临时下降。

## Tuning

### Startup Parameters

| 参数 | 默认 | 含义 |
| :-- | :-- | :-- |
| `-o modern` | 已废弃（1.5.0 起默认开启） | 启用 modern 模式（segmented LRU + crawler） |
| `-o max-hot-percent=20` | 20 | HOT 内存占比上限 |
| `-o max-warm-percent=30` | 30 | WARM 内存占比上限 |
| `-o max-hot-age=0.1` | 0.1 | HOT 尾部年龄相对 COLD 尾部年龄的倍数 |
| `-o max-warm-age=2.0` | 2.0 | WARM 尾部年龄相对 COLD 尾部年龄的倍数 |
| `-o temp_ttl=-1` | -1（关闭） | TEMP LRU 的 TTL 阈值（秒） |

### Runtime Tuning

```
lru tune 10 25 0.1 2.0        # 运行时调整 HOT% / WARM% / hot_age / warm_age
lru temp_ttl 60               # 运行时开启 TEMP LRU，TTL < 60 秒的 item 进 TEMP
lru mode segmented            # 切换 LRU 模式
```

## Links

- [Memcached](/docs/CS/DB/Memcached.md)
- [Memory Allocation](/docs/CS/DB/Memcached/Memory_Allocation.md)
- [Architecture](/docs/CS/DB/Memcached/Architecture.md)
- [Hash Table](/docs/CS/DB/Memcached/Hash_Table.md)

## References

1. [Replacing the Cache Replacement Algorithm in Memcached](https://memcached.org/blog/modern-lru) — 官方博客，modern LRU 的完整设计动机与实现
2. [Memcached GitHub — items.c](https://github.com/memcached/memcached/blob/master/items.c) — LRU + Crawler 实现源码
3. [Memcached GitHub — crawler.c](https://github.com/memcached/memcached/blob/master/crawler.c) — LRU Crawler 核心源码
