## Introduction

Caffeine 的核心竞争力是淘汰算法，而不只是「带过过的 ConcurrentHashMap」。它用的是 **W-TinyLFU**（Windowed TinyLFU）：把缓存切成一个小的 admission window 和一个大的 main 区，新条目先在 window 里证明自己，再与 main 区的淘汰候选比频率——频率低的出局。这样一次性扫描（scan）带来的冷 key 会被挡在 main 区之外，长期热点则能沉淀下来。本页讲清三个区域的结构与流转、频率草图的实现与老化、准入比较的细节与 hashDoS 防护、自适应窗口机制，以及大小/权重两种容量策略。

## Three Regions

```
┌─────────────────────────── BoundedLocalCache ───────────────────────────┐
│                                                                          │
│  Window（LRU，初始约 1%）                                                 │
│    └── 新写入的条目全部先进这里；命中只在 window 内重排                     │
│                                                                          │
│  Main（约 99%）                                                           │
│    ├── Probation（LRU，初始约占 main 的 20%）                              │
│    │     └── 从 window 搬上来的候选；再次命中才晋升 Protected               │
│    └── Protected（LRU，初始约占 main 的 80%）                              │
│          └── 经受了访问考验的热点；被淘汰时降回 Probation                   │
│                                                                          │
└──────────────────────────────────────────────────────────────────────────┘
```

初始切分来自两个常量：`PERCENT_MAIN = 0.99`（window = maximum − 0.99 × maximum，即 1%）与 `PERCENT_MAIN_PROTECTED = 0.80`（protected = 80% × main）。折算成总量：window 约 1%、probation 约 19.8%、protected 约 79.2%。**这个比例会被自适应机制持续调整**，见下文 Adaptive Window。

条目在区域间的流转全部由维护循环驱动：

| 事件 | 动作 |
| :--- | :--- |
| 新写入 | 进入 window MRU 端 |
| window 命中 | window 内重排到 MRU |
| window 超出配额 | window LRU 端条目**提升到 probation MRU 端**（每轮最多 1,000 个），随后立即参与准入比较 |
| probation 命中 | 晋升到 protected MRU 端（条目权重超过 protected 配额时留在 probation） |
| protected 命中 | protected 内重排到 MRU |
| protected 超出配额 | LRU 端条目**降回 probation** |
| main 区整体超限 | 拿 window 来的 candidate 与 victim 比频率，低者淘汰 |

## Frequency Sketch

准入判断依赖 `FrequencySketch`——一个 **4 位（0~15）计数器的 Count-Min Sketch**，带周期性老化：

```java
static final long RESET_MASK = 0x7777777777777777L;  // 每个 4 位计数器的掩码
static final long ONE_MASK   = 0x1111111111111111L;
static final int MIN_SKETCH_SIZE = 256;
```

实现要点（全部来自源码注释与 `FrequencySketch.java`）：

- **固定深度 4**：四个哈希函数（`spread` 做 murmur3 风格 finalizer，`rehash` 再一轮），宽度为数组长度的 4 倍，置信度 93.75%，误差界 e / width；
- **一维 long 数组**：每个 long 塞 16 个 4 位计数器；数组长度 = `maximumSize` 向上取 2 的幂（下限 256）。**内存成本约 8 字节 × 最大容量**，100 万容量的缓存就是约 8 MB——不是「每 key 8 bit」；
- **64 字节块约束**：一个 key 的 4 个计数器被约束在同一个 64 字节 block（L1 cache line）内，牺牲理论均匀性换取可预测的访存（典型成本是一次内存访问而非四次）；
- **懒初始化**：`setMaximumSize` 里只有 `weightedSize() >= max / 2` 时才 `ensureCapacity` 并打开读缓冲——缓存没填到一半，连草图都不分配；
- **老化（reset）**：自增操作累计到 `sampleSize = 10 × maximumSize` 时，把所有计数器减半（奇数个数通过 `ONE_MASK` 统计后修正），`size` 同步收缩。这对应 TinyLFU 论文里的 reset，作用是让长期不访问的老 key 频率衰减，避免「一次热点、永久驻留」。

频率上限 15，`frequency(e)` 取四个计数器的最小值。

## Admission

main 区超限时，`evictFromMain` 拿 window 搬上来的 candidate 与 victim（从 probation LRU 端开始，耗尽再取 protected）逐一比较：

```java
boolean admit(Object candidateKeyRef, Object victimKeyRef) {
  int candidateFreq = frequencySketch().frequency(candidateKeyRef);
  int victimFreq = frequencySketch().frequency(victimKeyRef);
  if (candidateFreq > victimFreq) {
    return true;                                    // 候选更热：准予驻留，淘汰 victim
  } else if (candidateFreq >= ADMIT_HASHDOS_THRESHOLD) {  // >= 6
    return (ThreadLocalRandom.current().nextInt() & 127) == 0;  // 1/128 随机准入
  }
  return false;                                     // 平局或更冷：淘汰候选
}
```

- **平局保留 victim**：进攻方（新 key）需要严格更高才换下旧 key，这是对驻留集的偏袒；
- **hashDoS 防护**：计数器最大 15、老化后减半为 7。攻击者可以故意制造哈希碰撞把 victim 的频率抬高，让任何新 key 都进不来。因此当候选频率已经 ≥ 6（足够热）时，额外给 1/128 的随机准入——攻击者无法预测随机序列，而正常负载下这点随机对命中率影响可忽略；
- **权重特例**：candidate 权重大于整个 `maximum` 时直接淘汰，不进比较。

## Adaptive Window

W-TinyLFU 论文的完整形态还有一层：window 与 main 的切分应该随负载自适应。3.x 用 `WindowClimber` 实现了这一点（对应官方 Wiki 的 Adaptive Window 一文）：

| 档位 | 条件 | 策略 |
| :--- | :--- | :--- |
| `DensityClimber` | `maximum > 4096` | 样本足够大，直接比较 window 与 main 的**命中密度**（每单位容量的命中），每 `4 × maximum` 次请求一个样本 |
| `ReactiveClimber` | `maximum ≤ 4096` | 样本不足，跨样本比较**命中率变化**决定伸缩方向；`maximum ≤ 512` 时进入慢适应（步长衰减 0.995、样本周期最多拉长 4 倍） |

配套的护栏：窗口下限 2%（`WINDOW_FLOOR_FRACTION`）、单步最大调整 30%（`MAX_STEP_FRACTION`）、命中率变化超过 5%（`RESTART_THRESHOLD`）视为工作负载切换并重置适配状态；`Anchor` 记录历史最优位置，后续调整使命中率变差时有权回退。

实践含义：**不要凭「网上说窗口是 5%」之类的固定比例去推理线上行为**。3.x 的初始值是 1%，之后由命中统计说话；同一种负载在不同容量下的最优切分本来就可能差几倍。

## Size and Weight Policies

两种容量语义互斥（builder 层强制）：

| 策略 | API | 语义 |
| :--- | :--- | :--- |
| 按条数 | `maximumSize(n)` | 加权大小 = 条目数；草图容量按 n 计算 |
| 按权重 | `maximumWeight(n)` + `weigher(...)` | 每条目权重由 `Weigher` 计算（如 value 字节数）；权重累加超限即淘汰 |

- `maximumSize(0)` / `maximumWeight(0)` 是合法的「加载后立即淘汰」语义（用于测试或强制回源），淘汰仍走 executor 异步完成；
- 权重模式同样懒初始化草图，`WeightLimiter` 在淘汰时按权重搬运；
- 运行时内省：`cache.policy().eviction()` 暴露 `weightedSize()` / `maximum()`，可直接观测当前占用——这是线上判断「容量是否配小了」的正确姿势，比猜 `estimatedSize()` 与 maximum 的差值更准（`estimatedSize()` 是近似值）。

## Links

- [Caffeine](/docs/CS/SE/Caffeine.md)
- [Architecture](/docs/CS/SE/Caffeine/Architecture.md)
- [Expiration](/docs/CS/SE/Caffeine/Expiration.md)
- [Operations](/docs/CS/SE/Caffeine/Operations.md)
- [LRU](/docs/CS/Algorithms/LRU.md)
- [Cache](/docs/CS/SE/Cache.md)

## References

1. [TinyLFU: A Highly Efficient Cache Admission Policy](https://arxiv.org/abs/1512.00727)
2. [Caffeine Wiki – Adaptive Window](https://ben-manes.github.io/caffeine/wiki/adaptive-window.html)
3. [Count-Min Sketch 论文](http://dimacs.rutgers.edu/~graham/pubs/papers/cm-full.pdf)
4. [ben-manes/caffeine 源码：FrequencySketch.java](https://github.com/ben-manes/caffeine/blob/v3.3.1/caffeine/src/main/java/com/github/benmanes/caffeine/cache/FrequencySketch.java)
