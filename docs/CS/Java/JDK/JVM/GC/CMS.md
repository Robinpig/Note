## Introduction

Concurrent Mark Sweep（CMS）收集器专为**偏好更短垃圾回收暂停**且能够**在应用程序运行时与垃圾回收器共享处理器资源**的应用程序设计。
通常，具有相对大量长期存活数据（大老年代）并在具有两个或更多处理器的机器上运行的应用程序倾向于从此收集器的使用中受益。
然而，任何具有低暂停时间要求的应用程序都应考虑此收集器。CMS 收集器通过命令行选项 `-XX:+UseConcMarkSweepGC` 启用。

与其他可用收集器类似，CMS 收集器是分代的；因此会发生 minor 和 major 回收。
CMS 收集器尝试通过使用单独的垃圾回收器线程与应用程序线程同时追踪可达对象来减少 major 回收导致的暂停时间。
在每个 major 回收周期中，CMS 收集器在回收开始时和回收中途短暂暂停所有应用程序线程。
第二次暂停往往是两者中较长的一次。两次暂停期间都使用多个线程执行回收工作。
回收的其余部分（包括大部分存活对象追踪和不可达对象清除）由一个或多个与应用程序同时运行的垃圾回收器线程完成。
Minor 回收可以与正在进行的 major 周期交错，并以类似于并行收集器的方式完成（特别是，应用程序线程在 minor 回收期间停止）。

在 CMS 之前，Serial、Parallel 都是 STW。

CMS 用于 Old GC，Young GC 仍然由[其他收集器（ParNew）](/docs/CS/Java/JDK/JVM/ParNew.md)暂停执行。

- Initial Mark（STW）
- Concurrent Mark
- Remark Mark（STW）从 `GC ROOT`、`Write Barrier` 重新标记
- Concurrent Sweep

```
// CMS & ParNew code in same directory /hotspot/share/gc/cms (JDK12)
UseConcMarkSweepGC                       := true
UseParNewGC                              := true
```

UseCMSBestFit

#### Concurrent Mode Failure

CMS 收集器使用一个或多个与应用程序线程同时运行的垃圾回收器线程，目标是在老年代变满之前完成其回收。
如前所述，在正常操作中，CMS 收集器在应用程序线程仍在运行时完成大部分追踪和清除工作，因此应用程序线程只看到短暂的暂停。

**然而，如果 CMS 收集器无法在老年代填满之前完成回收不可达对象，
或者如果无法使用老年代中可用的空闲空间块满足分配，
那么应用程序将被暂停，并在所有应用程序线程停止的情况下完成回收。**

无法完成并发回收称为 `concurrent mode failure`，表明需要调整 CMS 收集器参数。
如果并发回收被显式垃圾回收（`System.gc()`）或为诊断工具提供信息所需的垃圾回收中断，则会报告 `concurrent mode interruption`。

#### Excessive GC Time and OutOfMemoryError

如果花在垃圾回收上的时间过多，CMS 收集器会抛出 OutOfMemoryError：如果超过 98% 的总时间花在垃圾回收上，并且回收的堆少于 2%，则抛出 OutOfMemoryError。此功能旨在防止应用程序由于堆太小而在长时间内几乎没有进展的情况下运行。如有必要，可以通过在命令行中添加选项 `-XX:-UseGCOverheadLimit` 来禁用此功能。

**该策略与并行收集器中的策略相同，不同之处在于执行并发回收所花费的时间不计入 98% 的时间限制。换句话说，只有在应用程序停止时执行的回收才计入 excessive GC time。此类回收通常是由于并发模式失败或显式回收请求（例如调用 `System.gc`）引起的。**

#### Floating Garbage

CMS 收集器与 Java HotSpot VM 中的所有其他收集器一样，是一种追踪收集器，它至少识别堆中所有可达对象。用 Richard Jones 和 Rafael D. Lins 在其著作《Garbage Collection: Algorithms for Automated Dynamic Memory》中的术语来说，它是一个**增量更新收集器**。**由于应用程序线程和垃圾回收器线程在 major 回收期间同时运行，垃圾回收器线程追踪过的对象可能在回收过程结束时变得不可达。** 这些尚未被回收的不可达对象称为浮动垃圾（floating garbage）。浮动垃圾的数量取决于并发回收周期的持续时间以及应用程序引用更新（也称为变更）的频率。此外，由于年轻代和老年代是独立回收的，它们各自作为对方根的来源。作为粗略的指导，尝试将老年代大小增加 20% 以应对浮动垃圾。一个并发回收周期结束时堆中的浮动垃圾将在下一个回收周期中被收集。

#### Pauses

CMS 收集器在并发回收周期中暂停应用程序两次。第一次暂停是将根直接可达的对象（例如，来自应用程序线程栈和寄存器的对象引用、静态对象等）以及来自堆中其他地方（例如年轻代）的对象标记为存活。此第一次暂停称为 `initial mark pause`。第二次暂停发生在并发追踪阶段结束时，用于查找由于 CMS 收集器完成对某个对象的追踪后应用程序线程更新了该对象中的引用而未被并发追踪发现的对象。此第二次暂停称为 `remark pause`。

#### Concurrent Phases

可达对象图的并发追踪发生在 initial mark pause 和 remark pause 之间。在此并发追踪阶段期间，一个或多个并发垃圾回收器线程可能正在使用本可用于应用程序的处理器资源。因此，计算密集型应用程序可能会在此和其他并发阶段期间看到应用程序吞吐量的相应下降，即使应用程序线程未被暂停。在 remark pause 之后，并发清除阶段收集被识别为不可达的对象。一旦回收周期完成，CMS 收集器就会等待，几乎不消耗计算资源，直到下一个 major 回收周期开始。

#### Starting a Concurrent Collection Cycle

对于串行收集器，每当老年代变满时就会发生 major 回收，并且在回收完成时所有应用程序线程都会停止。相比之下，并发回收的启动必须计时，以便回收可以在老年代变满之前完成；否则，应用程序将由于并发模式失败而观察到更长的暂停。有几种方法可以启动并发回收。

基于最近的历史记录，CMS 收集器维护对老年代将要耗尽之前剩余时间的估计以及对并发回收周期所需时间的估计。使用这些动态估计，并发回收周期的目标是确保在老年耗尽之前完成回收周期。这些估计添加了安全填充，因为并发模式失败可能代价高昂。

如果老年代的占用率超过启动占用率（老年代的一个百分比），也会启动并发回收。此启动占用率阈值的默认值约为 `92%`，但该值可能随版本而变。可以使用命令行选项 `-XX:CMSInitiatingOccupancyFraction=<N>` 手动调整此值，其中 `<N>` 是老年代大小的整数百分比（0 到 100）。

#### Scheduling Pauses

年轻代回收和老年代回收的暂停独立发生。它们不重叠，但可能接连发生，使得一次回收的暂停紧接着另一次回收的暂停，看起来像是一次更长的暂停。为了避免这种情况，CMS 收集器尝试将 remark pause 安排在前一个和后一个年轻代暂停之间的大致中间位置。目前，initial mark pause 不进行此调度，它通常比 remark pause 短得多。

#### Incremental Mode

注意，增量模式在 Java SE 8 中已弃用，可能在未来的主要版本中移除。

CMS 收集器可以在一种模式下使用，其中并发阶段是增量完成的。回想一下，在并发阶段期间，垃圾回收器线程正在使用一个或多个处理器。增量模式旨在通过定期停止并发阶段将处理器交还给应用程序来减轻长并发阶段的影响。此模式在此称为 i-cms，它将收集器并发完成的工作分成小块时间，安排在年轻代回收之间。当需要在具有少量处理器（例如 1 或 2 个）的机器上运行需要 CMS 收集器提供的低暂停时间的应用程序时，此功能很有用。

并发回收周期通常包括以下步骤：
- 停止所有应用程序线程，识别根可达的对象集，然后恢复所有应用程序线程。
- 在应用程序线程执行的同时，使用一个或多个处理器并发追踪可达对象图。
- 使用一个处理器并发重新追踪自上一步骤追踪以来被修改的对象图部分。
- 停止所有应用程序线程并重新追踪自上次检查以来可能被修改的根和对象图部分，然后恢复所有应用程序线程。
- 使用一个处理器将不可达对象并发清除到用于分配的空闲列表。
- 使用一个处理器并发调整堆大小并为下一个回收周期准备支持数据结构。

通常，CMS 收集器在整个并发追踪阶段使用一个或多个处理器，不会自愿放弃它们。类似地，一个处理器用于整个并发清除阶段，同样不会放弃它。对于有响应时间约束的应用程序（它们可能本来会使用处理核心），这种开销可能过于干扰，尤其是在只有一两个处理器的系统上运行时。增量模式通过将并发阶段分解为短暂的活动 burst 来解决此问题，这些 burst 被安排在 minor 暂停之间发生。

i-cms 模式使用 duty cycle 来控制 CMS 收集器在自愿放弃处理器之前允许执行的工作量。duty cycle 是 CMS 收集器在年轻代回收之间允许运行的时间百分比。i-cms 模式可以根据应用程序的行为自动计算 duty cycle（推荐的方法，称为自动 pacing），也可以在命令行上将 duty cycle 设置为固定值。

### Basic Troubleshooting

i-cms 自动 pacing 功能使用程序运行时收集的统计数据来计算 duty cycle，以便并发回收在堆变满之前完成。然而，过去的行为并非未来的完美预测器，估计值可能并不总是足够准确以防止堆变满。如果发生过多的 full GC，请尝试表 8-2 "Troubleshooting the i-cms Automatic Pacing Feature" 中的步骤，一次一个。

Table Troubleshooting the i-cms Automatic Pacing Feature

| Step | Options |
| --- | --- |
| 1. 增加安全系数。 | -XX:CMSIncrementalSafetyFactor=<N> |
| 2. 增加最小 duty cycle。 | -XX:CMSIncrementalDutyCycleMin=<N> |
| 3. 禁用自动 pacing 并使用固定 duty cycle。 | -XX:-CMSIncrementalPacing -XX:CMSIncrementalDutyCycle=<N> |

### Measurements

示例 "Output from the CMS Collector" 是使用选项 -verbose:gc 和 -XX:+PrintGCDetails 的 CMS 收集器的输出，删除了少量细节。注意，CMS 收集器的输出与 minor 回收的输出交错在一起；通常在并发回收周期内发生多次 minor 回收。CMS-initial-mark 表示并发回收周期的开始，CMS-concurrent-mark 表示并发标记阶段的结束，CMS-concurrent-sweep 表示并发清除阶段的结束。之前未讨论的是由 CMS-concurrent-preclean 指示的预清理阶段。预清理表示可以在并发状态下完成的工作，为 remark 阶段 CMS-remark 做准备。最后一个阶段由 CMS-concurrent-reset 指示，为下一个并发回收做准备。

Example Output from the CMS Collector
```
[GC [1 CMS-initial-mark: 13991K(20288K)] 14103K(22400K), 0.0023781 secs]
[GC [DefNew: 2112K->64K(2112K), 0.0837052 secs] 16103K->15476K(22400K), 0.0838519 secs]
...
[GC [DefNew: 2077K->63K(2112K), 0.0126205 secs] 17552K->15855K(22400K), 0.0127482 secs]
[CMS-concurrent-mark: 0.267/0.374 secs]
[GC [DefNew: 2111K->64K(2112K), 0.0190851 secs] 17903K->16154K(22400K), 0.0191903 secs]
[CMS-concurrent-preclean: 0.044/0.064 secs]
[GC [1 CMS-remark: 16090K(20288K)] 17242K(22400K), 0.0210460 secs]
[GC [DefNew: 2112K->63K(2112K), 0.0716116 secs] 18177K->17382K(22400K), 0.0718204 secs]
[GC [DefNew: 2111K->63K(2112K), 0.0830392 secs] 19363K->18757K(22400K), 0.0832943 secs]
...
[GC [DefNew: 2111K->0K(2112K), 0.0035190 secs] 17527K->15479K(22400K), 0.0036052 secs]
[CMS-concurrent-sweep: 0.291/0.662 secs]
[GC [DefNew: 2048K->0K(2112K), 0.0013347 secs] 17527K->15479K(27912K), 0.0014231 secs]
[CMS-concurrent-reset: 0.016/0.016 secs]
[GC [DefNew: 2048K->1K(2112K), 0.0013936 secs] 17527K->15479K(27912K), 0.0014814 secs
]
```
Initial mark pause 通常相对于 minor 回收暂停时间较短。并发阶段（concurrent mark、concurrent preclean 和 concurrent sweep）通常比 minor 暂停持续时间长得多，如示例 8-1 "Output from the CMS Collector" 所示。但请注意，在这些并发阶段期间应用程序不会暂停。Remark pause 的长度通常与 minor 回收相当。Remark pause 受到某些应用程序特性（例如，对象修改率高可能增加此暂停）和自上次 minor 回收以来的时间（例如，年轻代中对象更多可能增加此暂停）的影响。

## Summary

1. Concurrent Mark Sweep（CMS）收集器是一种偏好更短垃圾回收暂停的并发收集器。

## Links

- [Garbage Collection](/docs/CS/Java/JDK/JVM/GC/GC.md)

## References
1. [Concurrent Mark Sweep (CMS) Collector](https://docs.oracle.com/javase/8/docs/technotes/guides/vm/gctuning/cms.html)
