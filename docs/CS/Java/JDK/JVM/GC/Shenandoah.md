## Introduction

Shenandoah 是一个开源的、**基于 Region 的低暂停并行且并发**垃圾回收算法，面向**大堆**应用。

借助 SATB（Snapshot-At-The-Beginning）并发标记与 Brooks 风格的间接指针（indirection pointer）并发压缩，Shenandoah 实现了明显更短的 GC 暂停，且暂停时长与应用的存活数据量大小无关。我们在 OpenJDK 中的实现使其能与成熟的生产级 GC 算法做对比测试。

现代机器的内存与处理器数量空前增长，SLA（Service Level Agreement）应用要求 10–500 ms 的响应时间。为满足这一目标的下限，我们需要既高效（能在可用内存中运行程序）、又优化到「从不打断运行中的程序超过几毫秒」的 GC 算法。

光是找到这些引用可能就需要扫描整个堆。并发压缩之所以复杂，是因为在移动一个可能仍在使用的对象的同时，还必须原子地更新指向该对象的所有引用，使其指向新位置。GC 线程与 mutator 线程一起拷贝对象，并用原子 CAS 更新转发指针（forwarding pointer）；若多个 GC/mutator 线程竞争移动同一对象，只有一个 CAS 会成功。引用会在下一个并发标记阶段被更新。

编译器仅在运行 Shenandoah 时才会发射（emit）相应的屏障。

代价是：Shenandoah 比其他算法需要更多的空间。
> [!NOTE]
> 版本基线：Shenandoah 于 **JDK 12 作为实验特性集成（[JEP 189](https://openjdk.org/jeps/189)）**，**JDK 15 转为生产特性（[JEP 379](https://openjdk.org/jeps/379)）**，不在默认收集器之列。分代模式 **JDK 24 引入（[JEP 404](https://openjdk.org/jeps/404)，实验性）**，需 `-XX:ShenandoahGCMode=generational`；**截至 JDK 27 默认仍是 `satb` 非分代模式**，分代成为默认是 JDK 28 的目标（[JEP 535](https://openjdk.org/jeps/535)，Targeted）。

### Object Layout

Shenandoah 的对象布局为每个对象额外增加一个字（word）。这个字位于对象正前方，仅在使用 Shenandoah 收集器时才会被分配。

### Heap Layout

堆被切分为等大的 Region。一个 Region 可能包含新分配的对象、长生命周期对象，或两者混合。在任意一次 GC 周期中，可以选择任意 Region 子集进行回收：

- Region 的划分、Humongous（大对象）Region 等都与 G1 类似；
- 默认优先回收垃圾最多的 Region；
- 默认**非分代**，没有 young/old 的划分（时间上也没有）；
- 默认不需要追踪跨 Region 引用。

我们为 GC 启发式（heuristics）开发了一套接口，用于追踪分配与回收速率。Shenandoah 提供若干自定义策略，决定何时启动并发标记、以及把哪些 Region 纳入回收集合（collection set）。我们测量所用的默认启发式只挑选垃圾占比 60% 以上的 Region，并在已分配 Region 达到 75% 时启动并发标记周期。

## GC Phases

Shenandoah 的 GC 周期包含以下阶段：

1. **Initial Marking（初始标记）**：Stop-The-World，扫描根集（Java 线程栈、类静态变量等）；
2. **Concurrent Marking（并发标记）**：遍历堆，标记存活对象，并更新指向"上一周期已被疏散 Region"的引用；
3. **Final Marking（最终标记）**：Stop-The-World，重新扫描根集，将根复制到 to-region 副本并做更新，发起并发压缩，释放上一轮压缩中已完全疏散的 Region；
4. **Concurrent Compaction（并发压缩）**：从目标 Region 中疏散（evacuate）存活对象。

每个 GC 周期由两个 STW 阶段和两个并发阶段组成：先在 Initial Mark 暂停中 STW 扫描根集，随后 Java 线程继续运行时做并发标记；再次 STW 做最终标记，然后进入并发疏散阶段。

内存保护陷阱（Memory Protection Trap）

### Concurrent Marking

我们使用 **SATB（Snapshot-At-The-Beginning，起点快照）** 算法：任何在标记开始时存活、或在标记开始后才被分配的对象，都被视为存活。

维持堆的 SATB 视图需要一个写屏障——当 mutator 覆盖某个对象的引用时，该对象仍会在标记期间被 tracing。实现方式是：写屏障把被覆盖的旧值放入一个队列，供标记线程扫描。

每个并发标记线程都为每个堆 Region 维护一份线程本地的存活数据总量统计。我们在最终标记阶段结束时汇总所有这些统计，随后用它来挑选回收集合（collection set）里要收纳的 Region。并发标记线程使用 **work stealing（工作窃取）** 算法，尽可能利用机器上所有空闲线程。

### Choosing the collection set

我们基于"存活数据最少"的 Region 来选择回收集合。目标是跟上 mutation 的步伐，因此需要回收的空间至少不少于上一 GC 周期内分配的空间。Shenandoah 提供若干启发式，可基于堆占用率或 Region 密度来挑选 Region。由于暂停时间与根集大小成正比、而与回收集合里的 Region 数量无关，我们可以纯粹按收集器效率来挑选回收集合。

### Concurrent Compaction

一旦回收集合确定，我们就启动并发压缩阶段。并发 GC 线程知道回收集合里有多少字节的存活数据，因此清楚要预留多少 Region。所有 GC 线程协作，从目标 Region 中疏散存活对象。

mutator 可以读取目标 Region 中的对象，但一旦发生写入，mutator 也必须尝试自己拷贝一份，以保证对象视图的一致性。我们算法的一条不变式（invariant）是：**写入永远不会发生在 from Region**。

并发 GC 线程借助 **speculative copy（推测性拷贝）协议**完成大部分疏散工作：

- 先 speculative 地把对象拷贝到自己的线程本地分配缓冲区（TLAB）；
- 然后尝试用 CAS 把 Brooks 风格的间接指针（indirection pointer）指向自己的推测副本；
- 若 CAS 成功，则拿到了对象的新地址；
- 若 CAS 失败，说明有别的线程在拷贝竞争中胜出；此时该并发 GC 线程回滚（unroll）自己的推测副本，转而使用另一线程留在间接指针里的 to-region 指针值继续。

当 Java 线程想要写入一个 from-space 对象时，它同样使用推测性分配协议，把对象拷贝到自己的线程本地分配缓冲区；只有拿到对象的新地址后，才执行原本打算的写入。写入 to-region 对象是安全的，因为 to-region 对象在并发疏散期间不会被移动。我们在 SpecJBB2015 基准上测过 Java 线程在写屏障里花在拷贝对象上的时间，几乎可忽略——两小时跑下来总计不到 118 微秒。

在其它线程把对象拷贝到 to-region 期间，Java 线程仍可继续读取 from-region 数据。一旦对象被拷贝完，间接指针就会指向新副本，后续访问也将被导向那里。相比之下，要求"所有访问都必须在 to-region"的收集器可能遭受 read storms（读风暴）；在疏散期间，mutator 为维持"所有访问都在 to-region"的不变式而做 GC 工作，可能显著拖慢前进进度。Shenandoah 的解法把这种代价限制在平时远更少发生的"更新"路径上。

**注意：对不可变数据（如类指针、数组长度、final 字段）的读取不需要读屏障，因为这些值在所有副本中都相同。**

### Updating References

把所有指向 from-region 对象的引用更新为指向其 to-region 副本，需要遍历整个堆。我们没有把它放到一个独立阶段、从而每个 GC 周期额外多一次停顿，而是在下一次并发标记期间顺带完成这些更新。

### Barriers

Shenandoah 依赖一个**读屏障**来穿过 Brooks 风格的间接指针，同时还有一道**双重写屏障（double write barrier）**。我们在"把对象引用存入堆中对象"的写操作上使用 SATB 写屏障——这些对象引用写操作会把被覆盖的旧值入队，以维持 SATB 的正确性。

此外还有一道**并发疏散写屏障**，它通过把"即将被写入的对象"从目标 Region 中拷贝出去，来协助并发 GC 维持"目标 Region 中不发生写入"的不变式。

我们的读屏障和写屏障在每一编译层级上都做了实现，但各层解法非常相似，这里只讨论优化编译器（C2）的实现。

需要屏障的地方不止于读写对象字段。对象加锁会写入对象的 mark word，因此也需要写屏障；只要 VM 访问堆中对象且涉及屏障语义，都需要相应的屏障处理。

### Read Barriers

我们编译出的读屏障只是一条汇编指令：

```cpp
void
ShenandoahBarrierSet::compile_resolve_oop(){
__ movptr(dst, Address(dst, -8));
}
```

### Write Barriers

写屏障比读屏障需要做更多工作，但由于写操作频率更低，这一点被抵消了。当并发标记运行时，我们使用 SATB 写屏障，确保并发标记期间被覆盖的任何值都能被并发标记线程扫描到——这道屏障与 G1、CMS 使用的完全相同。此外还有一道 Shenandoah 特有的写屏障，仅在并发疏散阶段生效，它确保目标 Region 中的对象在写入发生前已被转发。

"疏散是否进行中（evacuation in progress）"的检查、与读取间接指针的顺序非常关键。evacuation in progress 标志在最终标记 STW 阶段被置位，而在所有拷贝工作完成时以并发方式清除；在我们处于写屏障期间，该标志可能从 true 翻转为 false。如果先读间接指针、发现 from-region 对象指向自身，再读到 false 的 evacuation in progress 字段，就可能误写到一个 from-region 对象。反过来，如果先读 evacuation in progress 标志，则采取的是保守策略，保证在必要时一定调用写屏障。

## Lessons Learned

### Weak References and Class Unloading

弱引用与类卸载是我们最终标记暂停时间的主要来源。我们可以并发地发现弱引用，但必须在 STW 暂停中按强度顺序处理它们：所有强引用必须先完成，随后依次是 soft、weak、phantom 与 JNI 引用。理论上类卸载可以并发完成，但这并不简单，我们目前尚未解决。

### Locked Objects

对象的加锁/解锁属于写操作，要走写屏障协议；但在最终标记暂停期间，我们会主动（eagerly）疏散所有活跃监视器（monitor），从而得以在 `monitor-exit` 上避免一次写屏障。

## Cycle

### Overview

三个主要阶段：

1. 基于起点快照（SATB）的并发标记
2. 并发疏散（evacuation）
3. 并发引用更新（可选）

## Concurrent Mark

### Three-Color Abstraction

为对象分配颜色：

1. 白色（White）：尚未访问
2. 灰色（Gray）：已访问，但引用尚未扫描
3. 黑色（Black）：已访问，且引用已全部扫描

### Stop-The-World Mark

### Mutator Problems

### SATB

### Concurrent Cleanup

Immediate Garbage Region

### Concurrent Evacuation

Brooks Pointers

### Initial Update Reference

### Concurrent Update Reference

### Final Update Reference

### Two Pauses

Init Mark（初始标记）：

1. 停止 mutator 以避免竞争
2. 把根集染黑（Black）← 最重量级
3. 武装（Arm）SATB 屏障

Final Mark（最终标记）：

1. 停止 mutator 以避免竞争
2. 排空（Drain）SATB 缓冲区
3. 完成 SATB 更新遗留的工作 ← 最重量级

## Generational Shenandoah

分代 Shenandoah 由 **[JEP 404](https://openjdk.org/jeps/404)（JDK 24，实验性）** 引入，把 Java 堆分为 young / old 两代，沿用"多数对象朝生夕死"的分代假设，让 GC 把工作集中在年轻、且大多已死的对象上。它与非分代（默认 `satb` 模式）并存，**截至 JDK 27 默认仍是非分代模式**，分代成为默认是 JDK 28 的目标（[JEP 535](https://openjdk.org/jeps/535)，Targeted）。

### How to Enable

```shell
# JDK 24+ 实验性分代模式（需解锁实验选项）
java -XX:+UnlockExperimentalVMOptions -XX:ShenandoahGCMode=generational
```

### Differences from Non-generational Mode

- **双代结构**：每一代由 Shenandoah 堆中 region 的一个子集构成；任一时刻某 region 要么空闲、要么专属于 young 或 old。每代大小 = 其已占用 region + 一部分空闲 region 配额，可临时越界借用对方配额（但会加速触发收集）。
- **复用既有机制**：分代模式复用同一个 Load Reference Barrier（支持压缩指针的 32 位 LRB）、同一个 evacuator，以及已广义化的 SATB 写屏障——SATB 缓冲区后处理时区分指向 old/young 的引用，但快路径不变。
- **记忆集**：借用 Parallel/CMS 的 card marking 代码实现跨代引用记录，并新增"可随 mutator 并发扫描"的 remembered set 实现。
- **收集拓扑**：young 收集与 G1 的 young 收集类似，mixed 收集（young + 部分 old）则并发进行——核心优势在于 **young 与 mixed 收集都与 mutator 并发**，而 G1 的 young/mixed 转移必须 STW。

### Comparison with ZGC Generational

| 维度 | Generational Shenandoah | Generational ZGC |
| :--- | :--- | :--- |
| 引入版本 | JDK 24（实验，JEP 404） | JDK 21（JEP 439） |
| 成为默认 | JDK 28 目标（JEP 535, Targeted） | JDK 23 已默认（JEP 474） |
| 写屏障 | SATB 写屏障 + 并发转移写屏障 | 着色指针 + store barrier |
| 读屏障 | Brooks 指针读屏障（LRB） | 着色指针读屏障（load barrier） |
| 压缩指针 | 支持（32 位 LRB） | 不支持（着色指针占用高位） |

> 注意：Azul 的 C4 收集器早已分代但非开源；ZGC 分代在 JDK 21 已实现，且两者都不支持压缩对象指针。对绝大多数 heap 小于 32GB 的云负载，Shenandoah 分代支持压缩指针是相对 ZGC 分代的一个差异化优势。

## Pros, Cons and Fitness

| 维度 | 说明 |
| --- | --- |
| 主要优势 | 暂停与堆大小基本无关（并发重定位）；主动把空闲内存归还 OS；对大堆低延迟场景友好 |
| 主要缺点 | 并发屏障（Brooks 指针 + 读屏障）带来更高的 CPU 开销；相比 G1/ZGC 吞吐略降；需要更多空间 |
| 最佳场景 | 堆较大、且要求稳定低延迟（与堆大小解耦）的服务端应用 |
| 关键限制 | 不在默认收集器之列；非分代模式为 JDK 27 默认（`satb`），分代（JEP 404/535）仍在演进 |
| 启用方式 | `-XX:+UseShenandoahGC`（JDK 15+ 为 product；JDK 24+ 分代需 `-XX:ShenandoahGCMode=generational`） |

## Links

- [Garbage Collection](/docs/CS/Java/JDK/JVM/GC/GC.md)
- [TLAB](/docs/CS/Java/JDK/JVM/TLAB.md)
- [Card Table](/docs/CS/Java/JDK/JVM/GC/CardTable.md)




## References

1. [Shenandoah GC in JDK 13, Part I: Load Reference Barriers](https://rkennke.wordpress.com/2019/05/15/shenandoah-gc-in-jdk13-part-i-load-reference-barriers/)
2. [JEP 379: Shenandoah: A Low-Pause-Time Garbage Collector (Production)](https://openjdk.org/jeps/379)
2. [JEP 404: Generational Shenandoah](https://openjdk.org/jeps/404)
