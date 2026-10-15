## Introduction

Shenandoah 是一个开源的、**基于 Region 的低暂停并发**垃圾回收算法，面向大堆应用。

借助 SATB（Snapshot-At-The-Beginning）并发标记与 Brooks 风格的间接指针（indirection pointer）并发压缩，Shenandoah 实现了**暂停与存活数据量解耦**。GC 线程把对象拷贝到新位置后，只需原子 CAS 更新对象前置的 Brooks pointer word；所有后续访问通过 LRB（Load Reference Barrier）自动被导向新位置。

Shenandoah 与 ZGC 的核心差异：

| 维度 | Shenandoah | ZGC |
| --- | --- | --- |
| 并发重定位机制 | **Brooks pointer + speculative copy**（mutator 主动参与） | **Colored pointer + self-healing**（mutator 被动修复） |
| 读屏障复杂度 | LRB 1 条 movptr（无 slow path） | shift + test + self-healing CAS |
| 压缩指针 | ✅ 支持 32-bit LRB | ❌ 不支持（pointer metadata 占 bit） |
| per-object 开销 | 1 word（或 mark word 编码） | 无 |
| 并发标记算法 | SATB | 非 SATB（非分代 incremental-update，分代也 SATB） |
| GC 周期 | Initial Mark + Concurrent Mark/Remap + Final Mark + Concurrent Compaction | 三次 STW + 三阶段并发 |

代价是：Shenandoah 比其他算法需要更多堆空间。

### Heap Layout

堆被切分为等大 Region：

- 非分代模式：Region 无 young/old 固定划分，默认不追踪跨 Region 引用
- 分代模式（JEP 404）：Region 专属于 young 或 old 代
- 默认启发式：挑选垃圾占比 ≥ 60% 的 Region 回收，已分配 Region 达 75% 时启动并发标记

### Generational Transition Timeline

| 版本 | 变化 |
| --- | --- |
| JDK 12 | 实验特性（[JEP 189](https://openjdk.org/jeps/189)） |
| JDK 15 | 生产特性（[JEP 379](https://openjdk.org/jeps/379)），非分代默认 |
| JDK 24 | 分代模式可选（[JEP 404](https://openjdk.org/jeps/404)，实验性，需 `-XX:ShenandoahGCMode=generational`） |
| **JDK 27** | **非分代（`satb`）仍是默认** |
| JDK 28 目标 | 分代成为默认（[JEP 535](https://openjdk.org/jeps/535)，Targeted） |

### GC Cycle Phases

Shenandoah 的 GC 周期有四个顶层阶段、两个 STW：

```
Initial Mark (STW, ~1-5 ms)
    │  根集扫 + 武装 SATB + 初步 CSet
Concurrent Marking + Update References（并发）
    │  SATB 遍历对象图 + 顺带 remap 上一轮 from-region 引用
Final Mark (STW, ~2-12 ms)
    │  SATB 排空 + 弱引用 + Final CSet + 触发疏散
Concurrent Compaction（并发）
    │  speculative copy 搬运 CSet 对象 + CAS 更新 Brooks pointer
```

**Update References 合在标记阶段**是 Shenandoah 独有的设计——不需要独立 remap 阶段。

## Knowledge Map

Shenandoah 已拆分为 5 篇独立笔记，下表给出每篇的覆盖范围。阅读顺序建议：**BrooksPointer → Barriers → ConcurrentMarking → Evacuation → Generational**。

### Brooks Pointer

**对象前置字、LRB、speculative copy、mark word 编码演进——Shenandoah 实现并发重定位的核心机制。**

- 对象布局：前置 word（Brooks pointer）→ 后置优化进 mark word
- Brooks pointer 语义：未重定位时指向自身、重定位后指向 to-region 副本的 Brooks pointer word
- Speculative copy CAS 协议：GC 线程和 mutator 竞争拷贝 + CAS 更新 forwarding 指针
- Load Reference Barrier（LRB）：1 条 movptr（`dst = *(dst - 8)`），fast path 无 slow path
- 与 ZGC colored pointer 对比表

👉 [**跳转 → Shenandoah/BrooksPointer.md**](/docs/CS/Java/JDK/JVM/GC/Shenandoah/BrooksPointer.md)

### Barriers

**三重屏障体系：LRB（读）+ SATB 写屏障 + 并发疏散写屏障；fast path / slow path 分流。**

- LRB 原理 + C2 伪代码
- SATB 写屏障：旧值入队、flag 检查 + GC 安全点动态 patch
- 疏散写屏障：from-region 不变式维持、speculation copy 触发、flag 可见性
- 双屏障顺序 + evacuation_in_progress 保守检查
- Shenandoah vs Generational ZGC barrier 体系对比

👉 [**跳转 → Shenandoah/Barriers.md**](/docs/CS/Java/JDK/JVM/GC/Shenandoah/Barriers.md)

### Concurrent Marking

**SATB 三着色、Initial Mark / Final Mark STW、Immediate Garbage Region、Update References 合入标记。**

- 三色抽象：White / Gray / Black 编码
- Initial Mark STW：根集染黑 + 武装 SATB + 初步 CSet
- SATB 原理：快照 + 旧值入队 → 保证"标记开始时存活的对象都能被标记"
- **Update References 合在标记里**：Initial / Concurrent / Final 三轮 remap
- Immediate Garbage Region（IGR）：标记阶段就能回收全垃圾 Region
- Final Mark STW 时间分布：SATB 排空 + 弱引用（两大瓶颈）

👉 [**跳转 → Shenandoah/ConcurrentMarking.md**](/docs/CS/Java/JDK/JVM/GC/Shenandoah/ConcurrentMarking.md)

### Evacuation

**Speculative copy 协议、CSet 选择、read storms vs write storms、Degenerated GC / Full GC。**

- CSet 选择：效率优先（垃圾占比最高的 Region）+ 跟上分配速度
- Speculative copy 完整 CAS 循环伪代码（GC 线程 + mutator 线程版本）
- 疏散两个不变式：from-region 无写入、to-region 不被移动
- 转发成本从读路径转移到写路径（read storms → write storms）
- Remap 合在下一轮标记里，不单独做
- Degenerated GC（STW 部分 evacuation）与 Full GC

👉 [**跳转 → Shenandoah/Evacuation.md**](/docs/CS/Java/JDK/JVM/GC/Shenandoah/Evacuation.md)

### Generational Shenandoah

**JEP 404 分代设计、双代 Region 布局、Card Marking RSet、与 ZGC Generational 完整对比。**

- 版本时间线：JDK 24 实验 → JDK 28 默认目标
- 双代 Region 布局 + 配额 + 越界借用
- RSet 来源：card marking（借 Parallel/CMS）+ 并发扫描（Shenandoah 独有）
- Young / Mixed / Old 三种收集模式，**young 和 mixed 都并发**
- 最大程度复用非分代机制（LRB / SATB / Evacuator）
- Shenandoah vs ZGC Generational 六维度对比表

👉 [**跳转 → Shenandoah/Generational.md**](/docs/CS/Java/JDK/JVM/GC/Shenandoah/Generational.md)

## Pros, Cons and Fitness

| 维度 | 说明 |
| --- | --- |
| 主要优势 | 暂停与堆大小基本无关（并发重定位）；支持压缩指针（堆 < 32 GB 有优势）；主动把空闲内存归还 OS |
| 主要缺点 | Brooks pointer 带来 per-object 8 bytes 开销（可选 mark word 编码消除）；并发屏障 CPU 开销略高；吞吐相比 G1/ZGC 略降 |
| 最佳场景 | 堆较大、要求稳定低延迟（与堆大小解耦）、且 heap < 32 GB 希望用 CompressedOops 的服务端应用 |
| 关键限制 | 不在默认收集器之列；非分代模式为 JDK 27 默认；分代 JEP 404（JDK 24 实验）/ JEP 535（JDK 28 默认目标）仍在演进 |
| 启用方式 | `-XX:+UseShenandoahGC`（JDK 15+ 为 product）；分代需 `-XX:+UnlockExperimentalVMOptions -XX:ShenandoahGCMode=generational` |

## Links

- [Garbage Collection](/docs/CS/Java/JDK/JVM/GC/GC.md)
- [ZGC（同为低延迟 GC，对比屏障体系）](/docs/CS/Java/JDK/JVM/GC/ZGC.md)
- [ZGC Brooks Pointer vs Colored Pointer](/docs/CS/Java/JDK/JVM/GC/ZGC/ColoredPointers.md)
- [Card Table（RSet 的基础实现）](/docs/CS/Java/JDK/JVM/GC/CardTable.md)
- [TLAB](/docs/CS/Java/JDK/JVM/TLAB.md)

## References

1. [Shenandoah Proposal PDF (OpenJDK)](https://mail.openjdk.org/pipermail/hotspot-gc-dev/attachments/20160513/cde124dd/ShenandoahProposal.pdf) — Shenandoah 原始设计论文
2. [PPPJ 2016: Shenandoah](https://tech-notes.accel.dk/programming/java/java12/docs/PPPJ2016.pdf) — concurrent compacting GC 学术论文
3. [Shenandoah GC September 2017](https://shipilev.net/talks/vmm-Sep2017-shenandoah.pdf) — Aleksey Shipilev 讲解
4. [JEP 189: Shenandoah (Experimental)](https://openjdk.org/jeps/189)
5. [JEP 379: Shenandoah (Production)](https://openjdk.org/jeps/379)
6. [JEP 404: Generational Shenandoah](https://openjdk.org/jeps/404)
7. [JEP 535: Shenandoah GC: Generational Mode by Default](https://openjdk.org/jeps/535)
8. [Shenandoah GC in JDK 13, Part I: Load Reference Barriers](https://rkennke.wordpress.com/2019/05/15/shenandoah-gc-in-jdk13-part-i-load-reference-barriers/)
9. [RFR JDK-8224584: Eliminate forwarding pointer word](https://mail.openjdk.org/archives/list/shenandoah-dev@openjdk.org/thread/ZMS7UZTPHHAWLNK35N6JT4WODB7YDORC/)
10. [Shenandoah GC - by RednaxelaFX / R 大](https://www.zhihu.com/question/287945354/answer/458761494)
