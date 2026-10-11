## Introduction

> [!WARNING]
>
> **CMS 已被移除，本篇仅作历史与源码阅读材料。**
>
> - **JEP 291**（Release **9**）弃用 CMS：`-XX:+UseConcMarkSweepGC` 开始打印弃用警告。
> - **JEP 363**（Release **14**）**移除** CMS：HotSpot 源码树中整个 `gc/cms` 目录被删除，仅 CMS 专属的选项也一并移除。此后在命令行传 `-XX:+UseConcMarkSweepGC` 只会得到
>
>   ```text
>   Java HotSpot(TM) 64-Bit Server VM warning: Ignoring option UseConcMarkSweepGC; support was removed in <version>
>   ```
>
>   然后**回退到默认收集器继续运行**——不是报错退出，容易被忽略。
>
> 迁移路径：G1（`-XX:+UseG1GC`）是官方指定的继任者，低延迟大堆场景可选 ZGC 或 Shenandoah。本文描述的并发模式失败、浮动垃圾、i-cms 增量模式等机制在现役收集器中已无对应实现。
>
> 同理，文中提到的**增量模式（i-cms）**本身早在 **Java SE 8 就已弃用**（`incremental mode is being deprecated in Java SE 8`），随着 CMS 一起消失。

CMS（Concurrent Mark Sweep）收集器面向「偏好更短 GC 暂停、且能承受 GC 与应用程序并发共享处理器资源」的应用。典型受益者：拥有较大长寿命数据（大老年代）、运行在两颗及以上处理器上的应用。它通过 `-XX:+UseConcMarkSweepGC` 启用。

和其余收集器一样，CMS 是分代的，因此既会发生 minor 也会发生 major 收集。CMS 试图通过**单独的 GC 线程与应用线程并发地追踪可达对象**来降低 major 收集的暂停时间。每个 major 周期中，CMS 会在周期开头和中间各暂停一次应用线程；第二次暂停通常更长，两次暂停都用多线程完成收集工作。其余大部分工作（包括大部分存活对象追踪与不可达对象清除）由一个或多个与应用并发的 GC 线程完成。minor 收集可与进行中的 major 周期交错，其方式与并行收集器类似（minor 时应用线程停止）。

在 CMS 之前，Serial 与 Parallel 均为全程 STW。CMS 只负责老年代（Old GC）；年轻代回收仍由其他收集器（通常是 ParNew）以暂停方式完成。

## Place in the Collector Evolution

在 HotSpot 收集器家族中，CMS 是**首个把「并发」引入生产**的收集器：它在 Serial/Parallel 的「全程 STW」之后，第一次让大部分标记与清除工作与应用程序并发，从而显著缩短了 major 收集的暂停。代价是：标记-清除不压缩导致内存碎片、并发需要额外 CPU、以及后面会讲到的并发模式失败（CMF）与浮动垃圾。

CMS 是通往 G1（Region 化、可预测暂停）与 ZGC/Shenandoah（并发重定位）的过渡形态；它本身在 **JDK 14** 被整体移除（JEP 363）。演进位置：Serial（单线程 STW）→ Parallel（多线程 STW，换吞吐量）→ **CMS（并发，换低延迟但留结构性缺陷）** → G1（Region 化，平衡两者）→ Shenandoah/ZGC（并发重定位，暂停与堆解耦）。

## Collection Cycle

CMS 的 major 周期由四个阶段组成：

- **Initial Mark（STW）**：标记从 GC Roots 与老年代外（如年轻代）直接可达的对象。暂停很短。
- **Concurrent Mark（并发）**：从 Initial Mark 的结果出发，并发追踪整个对象图。
- **Remark（STW）**：重新标记在并发标记期间因应用线程修改引用而漏标的对象，借助 Write Barrier 捕获增量更新。这是周期中较长的暂停。
- **Concurrent Sweep（并发）**：回收被标记为不可达的对象，将其归还空闲链表。

```
// 一个 major 周期的典型步骤（CMS & ParNew 同目录 /hotspot/share/gc/cms，JDK 12）
// 1. 停止所有应用线程，标记 Roots 可达对象（Initial Mark，STW）
// 2. 并发追踪可达对象图（Concurrent Mark）
// 3. 并发重追踪被修改的局部（Precleaning）
// 4. 停止应用线程，重标记遗漏对象（Remark，STW）
// 5. 并发清除不可达对象（Concurrent Sweep）
// 6. 并发重置数据结构，准备下一周期（Reset）
UseConcMarkSweepGC                       := true
UseParNewGC                              := true
```

## Concurrent Mode Failure

CMS 用一个或多个 GC 线程与应用线程同时运行，目标是在老年代填满之前完成回收。正常情况下，CMS 在应用仍运行时完成大部分追踪与清除，因此应用只看到很短的暂停。

然而，如果 CMS **无法在老年代填满前完成不可达对象的回收**，或者空闲块不足以满足一次分配，应用将被暂停，并由所有应用线程停止的方式完成收集。这种「无法并发完成收集」被称为 `concurrent mode failure`，意味着需要调整 CMS 参数。若并发收集被显式 `System.gc()` 或诊断工具所需的中断打断，则报告 `concurrent mode interruption`。

## Floating Garbage

CMS 与其它 HotSpot 收集器一样是 tracing collector，至少会标记所有可达对象。按 Jones & Lins 的术语，它是 **incremental update collector**（增量更新式）。由于 major 收集期间应用线程与 GC 线程并发运行，被 GC 线程追踪过的对象可能在收集结束前变得不可达，这些尚未回收的不可达对象称为**浮动垃圾（floating garbage）**。其数量取决于并发周期时长与引用更新（mutation）频率。经验上，把老年代调大约 20% 以容纳浮动垃圾。上一周期结束时的浮动垃圾会在下一周期被回收。

## Excessive GC Time and OutOfMemoryError

若 GC 占用时间过多，CMS 会抛出 `OutOfMemoryError`：当超过 98% 的总时间花在 GC 上、且回收的堆少于 2% 时即抛出，目的为防止堆过小导致应用长时间无进展。可用 `-XX:-UseGCOverheadLimit` 关闭。

该策略与并行收集器相同，但**并发阶段消耗的时间不计入 98% 时限**——只有应用被停止时的收集（通常是 CMF 或显式 `System.gc`）才计入。

## Pauses and Scheduling

CMS 在一个并发周期中暂停应用两次。第一次（Initial Mark）标记从 Roots 与堆中其它地方（如年轻代）直接可达的对象；第二次（Remark）在并发追踪阶段末尾，找回因应用线程在对象被追踪后更新引用而漏标的对象。

两次暂停相互独立，但可能接连发生，看起来像一次更长的暂停。为避免这一点，CMS 尝试把 Remark 暂停安排在上一次与下一次年轻代暂停的**大致中点**。Initial Mark 暂停通常远短于 Remark，目前不做此调度。

## Starting a Cycle / Initiating Occupancy

串行收集器在老年代满时触发 major 收集并停止所有线程；CMS 则必须**在老年代填满之前启动并发收集**，否则会因 CMF 而观察到更长暂停。CMS 基于近期历史维护两个估计：老年代耗尽前的剩余时间、以及一个并发周期所需时间，借此动态决定启动时机（并加安全填充）。

此外，当老年代占用率超过 **initiating occupancy**（占老年代百分比）时也会启动。默认值约为 `92%`，但随发行版变化，可用 `-XX:CMSInitiatingOccupancyFraction=<N>` 手动调整。

## Incremental Mode (i-cms)

> 增量模式（i-cms）在 **Java SE 8 已弃用**，随 CMS 一起消失。

i-cms 把并发阶段切成小时间片，穿插在年轻代收集之间调度，使单/双处理器机器上也能享受 CMS 的低延迟。它用 duty cycle（占年轻代收集间隔中允许运行 CMS 的时间比例）控制，可自动 pacing 或手工设定。

i-cms 模式用 duty cycle（占空比）来控制 CMS 收集器在主动让出处理器之前允许完成的工作量：duty cycle 即「两次年轻代收集之间允许 CMS 运行的时间占比」。i-cms 可基于应用行为自动计算 duty cycle（推荐方式，称为 automatic pacing），也可在命令行设为固定值。

| Step | Options |
| --- | --- |
| 1. Increase the safety factor. | -XX:CMSIncrementalSafetyFactor=<N> |
| 2. Increase the minimum duty cycle. | -XX:CMSIncrementalDutyCycleMin=<N> |
| 3. Disable automatic pacing and use a fixed duty cycle. | -XX:-CMSIncrementalPacing -XX:CMSIncrementalDutyCycle=<N> |

## Measuring

以下为 `-verbose:gc -XX:+PrintGCDetails` 的典型输出片段（已删减细节）。可见 major 周期与多次 minor 收集交错：`CMS-initial-mark` 标志周期起点，`CMS-concurrent-mark`/`CMS-concurrent-preclean`/`CMS-concurrent-sweep`/`CMS-concurrent-reset` 为各并发阶段，`CMS-remark` 为重标记暂停。

```
[GC [1 CMS-initial-mark: 13991K(20288K)] 14103K(22400K), 0.0023781 secs]
[GC [DefNew: 2112K->64K(2112K), 0.0837052 secs] 16103K->15476K(22400K), 0.0838519 secs]
...
[GC [DefNew: 2077K->63K(2112K), 0.0126205 secs] 17552K->15855K(22400K), 0.0127483 secs]
[CMS-concurrent-mark: 0.267/0.374 secs]
[GC [DefNew: 2111K->64K(2112K), 0.0190851 secs] 17903K->16154K(22400K), 0.0191903 secs]
[CMS-concurrent-preclean: 0.044/0.064 secs]
[GC [1 CMS-remark: 16090K(20288K)] 17242K(22400K), 0.0210460 secs]
...
[CMS-concurrent-sweep: 0.291/0.662 secs]
[GC [DefNew: 2048K->0K(2112K), 0.0013347 secs] 17527K->15479K(22400K), 0.0014231 secs]
[CMS-concurrent-reset: 0.016/0.016 secs]
```

初始标记暂停相对 minor 暂停通常较短；并发阶段（mark/preclean/sweep）持续时间远长于 minor 暂停，但此间应用不暂停；remark 暂停常与 minor 收集相当，受对象修改率与距上次 minor 收集的时长影响。

## Why Removed: CMS → G1 / ZGC

CMS 被官方移除并非偶然，其设计存在若干结构性缺陷：

- **内存碎片**：标记-清除不压缩，长期运行后老年代碎片化，可能即使总空闲足够也无法分配大对象，被迫触发昂贵 Full GC（Serial Old 兜底）。
- **浮动垃圾 + CMF**：并发回收期间应用继续分配，若回收跟不上分配速度就发生并发模式失败，退化成全暂停的 Serial Old。
- **CPU 占用**：并发阶段持续占用 1 到「N/4 向上取整」个处理器，吞吐低于并行收集器。
- **维护成本**：CMS 与 ParNew 紧密耦合、代码路径复杂，是 HotSpot GC 现代化的包袱。

因此 JEP 291（JDK 9）弃用、JEP 363（JDK 14）整体删除 `gc/cms`。官方指定 **G1** 为继任者（Region 化、可预测暂停、无碎片问题），超大堆/超低延迟场景则选 **ZGC** 或 **Shenandoah**。现役收集器已无 CMS 的并发模式失败、浮动垃圾、i-cms 等机制对应实现。

## Pros, Cons and Fitness

| 维度 | 说明 |
| --- | --- |
| 主要优势 | 相对更短的 major 暂停（标记/清除并发）；适合 JDK 14 前的中堆低延迟服务 |
| 主要缺点 | 内存碎片、浮动垃圾、CMF 退化、CPU 占用高、无压缩 |
| 最佳场景 | JDK 14 之前、堆中等、对延迟敏感、多处理器服务 |
| 关键限制 | JDK 14 起彻底移除，不可再用；必须与 ParNew 配合，不支持与 G1/ZGC 混用 |
| 新生代搭档 | 必须配合 ParNew（`UseParNewGC`） |

## Summary

1. CMS 是首个把并发引入生产的 HotSpot 收集器，用并发标记-清除换取更短 major 暂停。
2. 四个阶段：Initial Mark(STW) → Concurrent Mark → Remark(STW) → Concurrent Sweep。
3. 结构性缺陷（碎片、浮动垃圾、CMF、CPU）导致 JEP 291 弃用、JEP 363（JDK 14）移除，由 G1 继任。

## Links

- [Garbage Collection](/docs/CS/Java/JDK/JVM/GC/GC.md)

## References

1. [Concurrent Mark Sweep (CMS) Collector](https://docs.oracle.com/javase/8/docs/technotes/guides/vm/gctuning/cms.html)
2. [JEP 291: Deprecate the Concurrent Mark Sweep (CMS) Garbage Collector](https://openjdk.org/jeps/291)
3. [JEP 363: Remove the Concurrent Mark Sweep (CMS) Garbage Collector](https://openjdk.org/jeps/363)
