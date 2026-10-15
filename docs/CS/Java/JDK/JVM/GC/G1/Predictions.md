## Pause-Time Prediction and Adaptive Sizing

> G1 区别于 Parallel GC / Serial GC 的**核心竞争力**在于：它不追求单次 GC 最快，而是追求**每次 GC 的停顿时间都落在目标窗口内**。实现这一点靠的就是 G1Predictions 预测模型——它用历史数据估计下一次 GC 需要多久，反过来决定这次要做多少工作。

### 为什么需要预测模型

Parallel GC 和 Serial GC 没有预测能力——它们"能收集多少就收集多少"，停顿时间随堆大小、活对象比例和引用复杂度线性变化。G1 的设计目标不同：`-XX:MaxGCPauseMillis=200` 默认值意味着每次 GC 暂停都要尽量控制在 200ms 内，无论堆多大、活对象多不多。

G1 实现这个目标的策略是 **按可预测的工作量增量回收**：每次只回收"能在目标时间内完成的那部分"。具体落到三个决策上：

1. **这次 GC 要收多少 young regions**（决定 Eden / Survivor 尺寸）
2. **这次 Mixed GC 要追加多少 old regions**（决定 CSet 中 old gen 候选数）
3. **什么时候开始下一次并发标记**（IHOP 自适应）

这三个决策全都取决于同一个问题：**回收 1 个 region 大概要多久？**

### G1Predictions：历史数据驱动的成本估计

核心类是 `G1Predictions`（`src/hotspot/share/gc/g1/g1Predictions.hpp`），它维护一组从历史 GC pause 中采集的时间统计，用**指数加权移动平均（EWMA）**来估计下一次 GC 的"单位工作量耗时"。

#### 采集的数据

每次 evacuation pause 结束后，`G1YoungCollector::record_young_collection_end` 把以下时间片段记录到 `G1CollectorPolicy`：

| 指标 | 含义 |
| :--- | :--- |
| `_cur_social_rate_ms_per_byte` | 每复制 1 字节对象的平均耗时 |
| `_cur_non_copy_time_ms` | pause 中非复制工作的固定开销（根扫描、RSet merge 等） |
| `_cur_rs_scan_time_ms_per_byte` | 扫描 1 字节 card 的平均耗时 |
| `_cur_old_evac_rate_ms_per_byte` | 老年代对象的复制速率（通常比 young 慢，因为还要更新引用） |

```cpp
// src/hotspot/share/gc/g1/g1CollectorPolicy.cpp（简化）
void G1CollectorPolicy::record_young_collection_end(bool concurrent_operation_is_full_mark,
                                                    bool evacuation_failed) {
  // 从 phase_times 提取实际耗时
  _recent_copy_rate_ms_per_byte.add(worker_costs.young_copy_ms_per_byte);
  _recent_non_copy_ms.add(worker_costs.non_copy_ms);
  _recent_rs_scan_ms_per_byte.add(worker_costs.rs_scan_ms_per_byte);
  // …
}
```

每个指标的类型是 `TruncatedSeq`——一个带截断窗口的滑动序列，默认保留最近 **10 次 pause** 的数据。

#### 预测公式

`G1Predictions::predict_young_collection_time_ms` 用一个简单的线性模型估算"一次回收 young gen regions 的 GC pause 要多久"：

```
predict_pause_ms = non_copy_overhead_ms
                 + (live_bytes_to_copy × copy_rate_ms_per_byte)
                 + (rs_scan_bytes × rs_scan_rate_ms_per_byte)
```

即：**固定开销 + 复制成本 + RSet 扫描成本**。

关键函数链：

```
G1CollectorPolicy::recalculate_gc_time_info()  // pause 结束后调用
  → _predictor.predict_young_collection_time_ms()
  → _predictor.predict_region_non_copy_time_ms()
  → _predictor.predict_copy_time_ms()
```

#### 截断机制

真实世界中 GC pause 耗时偶尔会出现 **outlier**（比如一次分配风暴）。G1Predictions 有一个 `TruncatedSeq::truncated_mean`——它把数据排序后**截掉最大的 1/3**再算平均值，避免 outlier 污染预测。

```cpp
// src/hotspot/share/gc/g1/g1Predictions.hpp
double get_new_prediction(TruncatedSeq const* seq) const {
  // 不直接用均值：极端值会让 G1 过度保守，
  // 截断最大值后再用 EWMA 平滑
  return seq->truncated_mean() * confidence_factor();
}
```

### 决策 1：Young Gen 尺寸自适应

预测出"回收一个 young region 平均耗时 X ms"后，G1 用这个信息决定**下一个 mutator phase 要分多少 regions 给 Eden**。

入口：`G1CollectorPolicy::choose_young_generation_length`，在 young GC 结束时调用。

```
G1CollectorPolicy::choose_young_generation_length()
  → G1Predictions::predict_pause_time_ms()         // 预测
  → G1Predictions::prediction_deviation_ms()       // 计算波动范围
  → 根据 _target_pause_time_ms 和 prediction + deviation
    算出这次可以接受多少 young regions
  → 在 [_young_length_min, _young_length_max] 范围内 clamp
```

核心公式（简化）：

```
allowed_young_regions = floor(
    (_target_pause_time_ms - predicted_non_copy_overhead)
    / predicted_ms_per_young_region
)
```

`young_length_min` 和 `young_length_max` 由 `-XX:G1NewSizePercent`（默认 5% heap）和 `-XX:G1MaxNewSizePercent`（默认 60% heap）决定。这两个参数是 Young Gen 尺寸的硬边界，G1 永远不会越界。

#### MMU（Minimum Mutator Utilization）约束

光靠 `-XX:MaxGCPauseMillis` 还不够——极端情况下 G1 可以把每次 GC 都做得极短，但 GC 频率高到 mutator 几乎不跑。G1 同时维护一个 **MMU** 约束：在 `-XX:GCPauseIntervalMillis`（默认 200ms）窗口内，GC 时间占比不能超过某个下限。

函数链：

```
G1CollectorPolicy::calc_g1_mmu()
  → GC time in last interval / interval length
  → 如果 GC 占比太高，强制收缩 young gen（让 GC 更频繁）
  → 如果 GC 占比太低，允许扩展 young gen（让 GC 更快）
```

### 决策 2：Mixed GC 的 CSet 选择（三部分模型）

Marking 周期结束后，G1 知道哪些 old regions 最值得回收（live data 少、连接度低）。但 Mixed GC 的 CSet 不能全放进去——要控制 pause time。

`G1CollectorPolicy::next_collection_size` 在每次 Mixed GC 开始时决定 CSet 中要放多少 old regions：

```cpp
// src/hotspot/share/gc/g1/g1Policy.cpp（简化）
void G1CollectorPolicy::choose_collection_set() {
  // 1. 基础部分：保证每次 Mixed GC 都有进展
  uint min_old = _candidate_regions_num / _mixed_gc_count_target;
  
  // 2. 增量部分：在时间允许的前提下尽量多收
  uint predicted_old = _predictor.predict_old_collection_regions_ms()
                       / _predictor.ms_per_old_region();
  // 80% 规则：只加到还剩 20% 目标时间
  uint time_budget_left = _target_pause_time_ms - _predictor.young_cost();
  uint max_from_time = floor(time_budget_left / _predictor.ms_per_old_region() * 0.8);
  
  // 3. 可选部分：evacuate_initial_collection_set 完成后
  //    如果还有时间，G1 会把剩余候选者追加进去
}
```

三个部分的最终 CSet = **young regions + min_old + incremental_old** + optional（如果有剩余时间）。

- `-XX:G1MixedGCCountTarget`（默认 8）控制整个 space-reclamation phase 要分几次才把所有候选 old regions 收完
- `-XX:G1HeapWastePercent`（默认 5）控制"回收能释放的空间占比低于这个阈值的 region 直接跳过"

### 决策 3：IHOP 自适应——什么时候开始并发标记

IHOP（Initiating Heap Occupancy Percent）决定并发标记的启动时机。如果启动太晚，标记还没完成 old gen 就满了，被迫 Full GC；如果启动太早，mutator 分配压力还不大，标记白做。

#### Adaptive IHOP 算法（`G1IHOPControl`）

`G1Policy::create_ihop_control` 创建一个 `G1AdaptiveIHOPControl`，它维护两个时间统计：

```
IHOP_candidate = max(
    // 上一次 marking 启动时的 old occupancy
    last_conc_mark_start_occupancy_bytes,
    // 历史 marking 期间 old gen 的平均分配速率 × 预期 marking 耗时
    _predictor.mark_rate_ms_per_byte * expected_mark_duration_ms,
    // 目标 old gen 上限 - G1HeapReservePercent 的缓冲
    max_old_capacity - _heap_reserve_bytes
)
```

决策链：

```
Young GC 结束时（G1YoungCollector::collect → policy()->need_to_start_conc_mark()）
  → _ihop_control->get_conc_mark_start_threshold()
  → 比较当前 old gen occupancy + 即将分配的对象大小
  → 如果超过 IHOP 阈值 → 在这次 Young GC 上 piggy-back 一个 Concurrent Start pause
  → 触发 VM_G1TryInitiateConcMark
```

#### 关键参数

- `-XX:InitiatingHeapOccupancyPercent`（默认 45）：非 Adaptive 模式下的固定阈值，以及 Adaptive 模式下的**初始值**（第一次 concurrent marking 用这个值）
- `-XX:-G1UseAdaptiveIHOP`：关闭自适应，回到固定阈值模式
- `-XX:G1HeapReservePercent`（默认 10）：old gen 容量的缓冲百分比，防止 Adaptive IHOP 算出的阈值太激进导致 Full GC

### 决策总结：G1 的三段自适应体系

```
┌─────────────────────────────────────────────────────────────────────┐
│                     G1Predictions（历史统计）                        │
│                                                                     │
│  TruncatedSeq × 5（copy rate / non-copy / RS scan / ...）           │
│  ── EWMA ──▶ 预测 pause time for X bytes                            │
└─────────┬──────────────────┬───────────────────────┬───────────────┘
          │                  │                       │
          ▼                  ▼                       ▼
  ┌───────────────┐   ┌───────────────┐   ┌───────────────────────┐
  │ Young Gen     │   │ Mixed GC      │   │ IHOP Adaptive         │
  │ Size Decision │   │ CSet Selection│   │ Concurrent Mark Start │
  │               │   │               │   │                       │
  │ clamp(        │   │ min_old +     │   │ max(last_start,       │
  │  allowed,     │   │ incremental,   │   │  alloc_rate×mark_time,│
  │  [min,max])   │   │ optional)     │   │  max_capacity-buffer) │
  └───────────────┘   └───────────────┘   └───────────────────────┘
          │                  │                       │
          ▼                  ▼                       ▼
    Eden regions      Old regions             Concurrent Mark
    allocation         candidates              start or not?
```

这套体系的设计哲学是：**G1 永远不预测"我要收集多少"，而是预测"我在目标时间内能收集多少"**——然后反推工作量。这和 Parallel GC 的"尽量收"恰好相反。

### Collection Set

Collection set 是要从中回收空间的源 region 集合。根据垃圾回收类型不同，collection set 由不同类型的 region 组成：

- 在 Young-Only 阶段，collection set 仅由年轻代 region 和其中对象可能被回收的大对象 region 组成。
- 在 Space-Reclamation 阶段，collection set 由年轻代 region、其中对象可能被回收的大对象 region 以及一些来自 collection set 候选 region 集合的老年代 region 组成。

Collection set 候选 region 是那些很可能在空间回收阶段被回收的 region。
G1 在 Remark 停顿期间根据它们包含的存活数据量和与其他 region 的连接度来选择。
存活数据少（空闲空间多）的 region 优于大部分是存活数据的 region，连接度低的 region 优于连接度高的 region，因为回收这些更"高效" region 的工作量更小。
G1 会从 collection set 候选 region 中剔除那些对释放内存贡献不大的 region。
这包括所有可回收空间少于当前堆大小的 -XX:G1HeapWastePercent 百分比的 region。
G1 在此空间回收阶段不会回收这些 region。默认 5，建议 2。

在 Remark 和 Cleanup 停顿之间，G1 准备它们以供后续回收，Cleanup 停顿完成工作并按效率排序。
更高效、回收时间更短且包含更多空闲空间的 region 优先在后续的 Mixed collection 中被回收。

### Garbage Collection Process

垃圾回收由四个阶段组成。

- Pre Evacuate Collection Set 阶段执行一些垃圾回收的准备工作：从 mutator 线程断开 TLAB、如 Java Heap Sizing 中所述选择本次回收的 collection set，以及其他小型准备工作。
- 在 Merge Heap Roots 期间，G1 为 collection set region 创建一个统一的记忆集，以便后续更容易进行并行处理。
  这消除了各个记忆集中的许多重复项，否则稍后需要以更昂贵的方式过滤掉。
- Evacuate Collection Set 阶段包含大部分工作：G1 从 roots 开始移动对象。
  根引用是来自 collection set 外部的引用，可能来自某些 VM 内部数据结构（external roots）、代码（code roots）或 Java 堆的其余部分（heap roots）。
  对于所有 roots，G1 将 collection set 中被引用的对象复制到其目的地，将其进入 collection set 的引用处理为新的 roots，直到不再有 roots。
  这些阶段的单独计时可以通过 -Xlog:gc+phases=debug 日志在 Ext Root Scanning、Code Root Scan、Scan Heap Roots 和 Object Copy 子阶段中分别观察。
  G1 可以可选地为可选 collection set 重复主要疏散阶段。
- Post Evacuate Collection Set 包含清理工作，包括引用处理和为后续 mutator 阶段做准备。

这些阶段对应于 -Xlog:gc+phases=info 日志打印的阶段。

Young GC

Mixed GC

Full GC

-XX:InitiatingHeapOccupancyPercent

全局采⽤标记-整理算法

局部是copy

G1收集器的特短：
并⾏与并发
分代收集（与其他收集器⼀样）
空间整理（标记-整理算法）
可预测的停顿

如果不计算维护Remembered Set的操作，G1收集器的运作⼤致可划分为以下⼏个步骤：

- Initial Marking
- Concurrent Marking
- Final Marking
- Live Data Counting and Evacuation

Compact - 更小、可调整，但仍然是停顿

Young GC 都使用 copy 和 STW（更小、可调整）。

CMS的写屏障实现是直接的同步操作，而G1就不得不将其实现为类似于消息队列的结构，把写前屏障和写后屏障中要做的事情都放到队列里，然后再异步处理

在发⽣Minor Gc之前，虚拟机会先检查⽼年代最⼤可⽤的连续空间是否⼤于新⽣代所有对象的总空间，如
果这个条件成⽴，那么Minnor Gc可⽤确保是安全的。如果不成⽴，则虚拟机会查看
HandlePromotyionFailure设置值是否允许担保失败。如果允许，那么会继续检查⽼年代最⼤空间是否⼤
于历次晋升到⽼年代对象的平均⼤⼩，如果⼤于，将尝试⼀次 Minnor Gc；如果⼩于，或者
HandlePromotyionFailure设置不允许冒险，那么这时要进⾏⼀次Full Gc

[JEP 345: NUMA-Aware Memory Allocation for G1](https://openjdk.java.net/jeps/345)
## Links

- [G1 枢纽页与知识地图](/docs/CS/Java/JDK/JVM/GC/G1.md)
- [G1 Mixed GC（分段 evacuate + CSet 候选选择）](/docs/CS/Java/JDK/JVM/GC/G1/MixedGC.md)
- [G1 Evacuation（Young GC Cheney 复制）](/docs/CS/Java/JDK/JVM/GC/G1/Evacuation.md)
- [G1 Full GC](/docs/CS/Java/JDK/JVM/GC/G1/FullGC.md)

## References

- [G1Predictions Source (openjdk.org)](https://github.com/openjdk/jdk/blob/master/src/hotspot/share/gc/g1/g1Predictions.hpp)
