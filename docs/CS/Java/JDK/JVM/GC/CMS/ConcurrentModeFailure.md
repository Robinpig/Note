## Introduction

**Concurrent Mode Failure（CMF）** 是 CMS 独有的、最臭名昭著的退化机制。CMS 的设计假设是：**并发标记-清除在老年代填满之前完成回收**。如果 CMS 跟不上 mutator 的分配速度，老年代会耗尽，应用线程不得不 fallback 到 STW 执行完整的 mark-compact——**这是 CMS 被移除的根本原因**。

其他收集器都有自己的退化机制，但**没有一个像 CMS 那样在 Full GC 里彻底放弃自己的收集逻辑**：

| 收集器 | 退化机制 | 退化后 |
| --- | --- | --- |
| CMS | Concurrent Mode Failure | **完全放弃 CMS**，退化成 `Serial Old` mark-compact |
| G1 | Evacuation Failure | 就地晋升（promotion），继续 G1 |
| Shenandoah | Degenerated GC / Full GC | STW 执行部分或完整 evacuation，**仍然用 Shenandoah 逻辑** |
| ZGC | Allocation Stall + Emergency Collection | 临时 STW 并发周期，**仍然用 ZGC 逻辑** |

## 触发条件

CMS 用一个或多个 GC 线程与应用并发运行。正常情况下 CMS 会在老年代填满前完成标记-清除：

```
老年代占用时间线：

    ╱╲
   ╱  ╲      CMS sweep 完成 ← 正常
  ╱    ╲
 ╱      ╲
╱────────╲────────────────────→
          ╲
           ╲___ CMF 触发 ← CMS 还没完成 sweep，老年代就满了
```

### 直接检测点

源码在 `cmscollector.cpp::CMSCollector::handle_allocation_failure()`（JDK 12）：

1. 应用线程尝试在老年代分配对象
2. CMS 分配器查分段空闲链表（segmented free lists），**没有足够大的空闲块**
3. 检查是否有一个 CMS 周期正在进行中（`_state == ConcurrentMarking` 或 `_state == ConcurrentSweep`）
4. 如果是且**不在** STW 阶段，设置 `_cmf = true`，触发 CMF

注意：如果分配失败发生在 Initial Mark / Remark STW 期间，CMS 不会触发 CMF——它会**在当前 STW 里把分配失败处理掉**，因为应用线程本来就停下来了。

### CMF vs CM Interruption

CMS 还有一个类似但**不是** CMF 的退化路径：**Concurrent Mode Interruption**。

| 维度 | CMF | CM Interruption |
| --- | --- | --- |
| 触发 | 老年代分配失败 | 外部强制（`System.gc()` / 诊断工具） |
| 根本原因 | CMS **自己**没完成回收 | CMS **被外部**打断 |
| 处理 | Full GC mark-compact | Full GC mark-compact（路径相同） |
| 可避免 | 可（调大堆、提高 GC 频率、用 G1/ZGC） | 不可避免（外部强制就是要 Full GC） |

## Fallback 路径：Full Mark-Compact

CMF 发生后，CMS 的 `CMSTriggerTask::execute()` 调用 `CMSCollector::do_pause()`，进入 Full GC：

```
CMSCollector::do_pause()
  └─ CMSCollector::mark_compact_collect()
       // 1. 全 STW 标记
       //    包括 年轻代 + 老年代 + Perm/Metaspace
       //    用 CMS 的 Full GC marking 逻辑（串行，不是并发）
       //
       // 2. Compaction Point 计算
       //    把存活对象从分散位置搬到连续区域
       //
       // 3. 对象搬移
       //    从 compaction point 开始，逐对象移动
       //
       // 4. 更新所有引用
       //    扫描整个堆，把旧地址改成新地址
       //    包括 老年代内部引用 + 年轻代→老年代 + GC Roots
```

⚠️ **关键**：CMF 发生时，CMS **放弃了自己的并发标记-清除**，退化成 `Serial Old` 的 mark-compact。延迟保证彻底崩塌——Full GC 的暂停时间与**存活数据量 + 堆大小**成正比，可能长达数秒甚至数十秒。

### CMF 与 GC Pause 的时间线

```
[正常运行]
  ├─ CMS 并发标记中...
  ├─ [minor GC (ParNew)]  ← 应用暂停 ~几 ms
  ├─ CMS 标记继续...
  ├─ [minor GC (ParNew)]
  ├─ CMS 标记继续...
  ├─ ⚠️ CMF 触发！老年代满了但 CMS 还没 sweep
  │
  ▼
[CMF → Full GC]
  ├─ 应用线程全部暂停
  ├─ Full mark-compact（暂停随堆大小）
  │
  ▼
[恢复运行]  ← 暂停可能长达数秒
```

## 经验公式

CMS 要在老年代**填满之前**启动并发收集。触发时机是：

```
剩余可用时间 < 并发周期所需时间 × SafetyFactor
```

CMS 基于近期历史维护两个估计：
1. **老年代耗尽前的剩余时间**（基于当前分配速率）
2. **并发周期所需时间**（基于近期 CMS 周期）

### Initiating Occupancy 阈值

当老年代占用率超过 **initiating occupancy** 百分比时，CMS 提前启动并发标记，避免 CMF：

```
可用 ≈ HeapSize × (1 - CMSInitiatingOccupancyFraction/100)
```

- 默认值：约 `92%`（随发行版变化，可用 `-XX:CMSInitiatingOccupancyFraction=<N>` 手动调）
- **调小**（如 75%）：CMS 更早启动，减少 CMF 概率，但 GC CPU 开销更高
- **调大**（如 95%）：堆利用率更高，但 CMF 风险陡增

### 安全因子

经验公式：

```
需要预留 ≈ HeapSize × CMSInitiatingOccupancyFraction × SafetyFactor
```

默认 SafetyFactor ≈ 1.1（10% 额外缓冲）。并发标记-清除在老年代占用到阈值前完成，浮动垃圾被下一周期清理；否则 CMF。

## 与 G1 Evacuation Failure 对比

G1 也有"老年代满了怎么办"的场景，但机制和 CMS 完全不同：

| 维度 | CMS CMF | G1 Evacuation Failure |
| --- | --- | --- |
| 触发 | CMS 没在老年代填满前完成 sweep | G1 young/mixed GC 疏散时没有足够空闲 Region |
| 处理 | **完全放弃 CMS** → Serial Old mark-compact | **就地晋升（promotion）** → 对象留在 from Region，继续 G1 |
| 后续 | Full GC 暂停（随堆大小） | 下一轮 GC 用 **Full GC STW** 兜底，但**仍然是 G1 逻辑** |
| 可恢复 | 自动恢复（Full GC 完继续 CMS） | Full GC 完继续 G1，G1 不会退化成 Parallel |
| 堆碎片 | CMF → Full GC 解决碎片 | Evacuation Failure → promotion 加剧碎片 → Full GC |

**G1 与 CMS 的核心差异**：G1 **从不放弃自己的收集逻辑**。哪怕堆碎到 Full GC，也是 G1 的 STW Full GC（Region 化的 mark-compact），而不是退化成 Serial Old。这是 G1 能取代 CMS 的关键设计。

## 与 Shenandoah / ZGC 退化对比

| 维度 | Shenandoah | ZGC |
| --- | --- | --- |
| 退化机制 | Degenerated GC（STW 部分 evacuation）+ Full GC | Emergency Collection（临时 STW 并发标记）+ Allocation Stall |
| 是否放弃自己的逻辑 | **不放弃**，STW evacuation 仍用 Shenandoah speculative copy | **不放弃**，stall 等 GC 而不是退化成 STW |
| Full GC 时 | Shenandoah Full GC 仍是并发重定位逻辑 | ZGC Full GC 仍是并发周期，不是 STW mark-compact |
| 与 CMS CMF 本质差异 | **没有退化**，只有"更紧急"的同一套逻辑 | **没有退化**，stall 是同步等待，不是放弃 |

## 为什么 CMF 如此致命

CMF 是 CMS 设计的**根 bug**：

1. **架构上无法根治**：CMS 的标记-清除天生有浮动垃圾 + 不压缩，堆碎片化后迟早触发
2. **退化后丢失所有并发优势**：Full GC mark-compact 是 STW 的，暂停时间可能是 CMS 常规暂停的 100 倍
3. **无法渐进缓解**：G1 可以调 mixed GC 的 CSet 尺寸、IHOP、MixedGCCountTarget 等渐进降低 CMF 概率——CMS 没有
4. **与 ParNew 紧耦合**：CMS 必须配合 ParNew，不能用 G1/ZGC 的新生代方案——升级路径被迫"换整个收集器"

JEP 363（JDK 14）移除 CMS 的根本原因之一就是 **CMF 的不可接受性**：在生产环境中，CMS 给出的"短暂停"承诺随时可能退化成 Full GC 的长暂停，且无法可靠预测。

## References

1. [CMS Collector Documentation (Java 8)](https://docs.oracle.com/javase/8/docs/technotes/guides/vm/gctuning/cms.html) — CMS 的官方指南，CMF 是已知问题
2. [JEP 291: Deprecate CMS](https://openjdk.org/jeps/291) — 弃用的主要动机之一是 CMF
3. [JEP 363: Remove CMS](https://openjdk.org/jeps/363) — 移除的具体内容
4. [HotSpot CMS CMF 路径源码分析](https://mail.openjdk.org/pipermail/hotspot-gc-use/2011-May.txt) — CMF fallback 到 mark_compact_collect
5. [G1 Evacuation Failure vs CMS CMF](https://openjdk.org/jeps/377) — JEP 377 对比了两者的退化行为

## Links

- [CMS 枢纽页与知识地图](/docs/CS/Java/JDK/JVM/GC/CMS.md)
- [CMS Incremental Update（浮动垃圾来源）](/docs/CS/Java/JDK/JVM/GC/CMS/IncrementalUpdate.md)
- [CMS Removal（CMF 是 CMS 被移除的核心原因）](/docs/CS/Java/JDK/JVM/GC/CMS/Removal.md)
- [G1 Garbage Collector（G1 evacuation failure 与 CMS CMF 的本质差异）](/docs/CS/Java/JDK/JVM/GC/G1.md)
