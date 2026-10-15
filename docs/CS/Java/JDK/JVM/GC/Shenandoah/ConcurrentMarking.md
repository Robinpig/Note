## Introduction

Shenandoah 用 **SATB（Snapshot-At-The-Beginning，起点快照）** 算法实现并发标记。并发标记的目标是遍历堆中所有对象，找出哪些是存活对象，为后续 CSet 选择和并发疏散做准备。

Shenandoah 的标记阶段有几个独特点：

1. **标记 + 引用更新（remap）合二为一**：不拆成两个独立阶段，节省一次并发周期
2. **Initial Update Reference（并发标记开始时）** 和 **Final Update Reference（Final Mark 前）** 各有一轮专门扫描
3. **Immediate Garbage Region（IGR）**：标记阶段就能识别出"全垃圾 Region"，直接回收，不需要等 CSet 选择

## GC Cycle Overview

Shenandoah 的 GC 周期（非分代模式）四个顶层阶段：

```
Initial Mark (STW, ~1-5 ms)
        │
Concurrent Marking + Update References（并发，可与 mutator 同时运行）
        │
Final Mark (STW, ~1-10 ms)
        │
Concurrent Compaction（并发，可与 mutator 同时运行）
```

SATB 标记跨越 Initial Mark → Concurrent Marking → Final Mark 三个阶段。

## Three-Color Abstraction

Shenandoah 的标记是经典三色抽象：

| 颜色 | 含义 | Shenandoah 编码 |
| --- | --- | --- |
| **White（白）** | 未访问 | Region bitmap 中对应 bit = 0 |
| **Gray（灰）** | 已访问，但引用未扫完 | 在 mark queue 中 |
| **Black（黑）** | 已访问，引用已全部扫完 | Region bitmap 中对应 bit = 1 |

三色不变式：**标记结束时没有 black → white 的指针**。如果有，说明那个 white 对象被 black 对象引用却没被标记，GC 会漏它。

## Initial Mark（STW）

Initial Mark 是 GC 周期的第一个 STW 暂停，做三件事：

### 1. 扫描根集并染黑

GC Root 包括：

- Java 线程栈帧中的对象引用
- 类静态变量
- JNI handles
- 系统字典
- VM 内部结构

Initial Mark STW 把所有这些根引用标记为 **black**——它们是标记的起点。

### 2. 武装 SATB 屏障

SATB 标记需要知道"标记开始时堆里有哪些引用"。Initial Mark STW 武装 SATB 写屏障——在 C2 编译的代码里动态 patch 写入 flag，让所有引用写操作开始把被覆盖的旧值入 SATB 队列。

### 3. 选 CSet（首次近似）

根据初始根集扫描得到的存活对象统计，**初步挑选**一轮 CSet。真正的 CSet 会在 Final Mark 阶段根据完整标记结果**最终确定**，但 Initial Mark 的初步选择让后续并发标记有了目标方向。

Initial Mark STW 的耗时与**根集大小**成正比（线程栈越多、类静态变量越多，越长），与堆大小完全无关——这是 Shenandoah 与 G1 young GC 的关键差异。

## Concurrent Marking + Update References

Initial Mark 结束后，mutator 继续运行，**并发标记线程**开始遍历对象图。

### SATB 原理

SATB 的正确性保证：**任何在标记开始时存活的对象，一定能被标记线程看到**。实现方式：

1. **快照时刻**：Initial Mark STW 结束那一刻，所有 GC Roots 被染黑
2. **SATB 队列**：之后任何 mutator 覆盖堆引用时，SATB 写屏障把**被覆盖的旧值**入队
3. **标记线程**扫描 SATB 队列：如果旧值指向白对象，标记线程把它染灰、并继续扫它的引用

这样就保证了：
- 标记开始时已经存在的引用不会被漏掉（旧值被入队）
- 标记开始后新分配的对象默认不算存活（等 Final Mark 时再判断）

### Update References（Remap）

并发标记期间，Shenandoah **同时**做一件额外工作：**把上一个 GC 周期已经被疏散（evacuate）的 Region 中的旧引用，更新到新位置**。这一步叫 Update Reference，通常分两轮：

| 阶段 | 内容 |
| --- | --- |
| **Initial Update Reference** | 并发标记**开始时**做一轮快速扫，处理上一个周期遗留的旧引用 |
| **Concurrent Update Reference** | 标记线程在遍历对象图时，顺便把指向"上一个周期 from-region"的引用更新掉 |
| **Final Update Reference** | Final Mark 前做最后一轮，清理 Initial 没覆盖到的旧引用 |

把 remap 合在标记里而不是拆成独立阶段，让 Shenandoah 的 GC 周期**比 G1（mark → remap → cleanup 三阶段）更紧凑**。

### Immediate Garbage Region (IGR)

标记线程在遍历某个 Region 的时候，会检查：这个 Region 里的所有对象是不是都已经被标记了？如果是，说明这个 Region **全是垃圾**（没有活对象指向它）。

这种 Region 可以**立刻回收**——标记线程直接更新 Region 状态为 "collected"，后续 GC 周期不需要再把它纳入 CSet。这是 Shenandoah 的一个优化，让**标记阶段就能释放内存**。

G1 没有 IGR 机制——G1 必须等 Final Mark 汇总完整 bitmap 后才能判断哪些 Region 全垃圾。

## Final Mark（STW）

Final Mark 是 GC 周期的第二个 STW 暂停，做四件事：

### 1. 排空 SATB 缓冲区

并发标记期间 SATB 队列不断积累旧值，Final Mark STW 必须把队列里**所有剩余的旧值**都标记完。这是 Final Mark STW 最耗时的部分。

### 2. 处理弱 / 软 / 虚引用

弱引用、软引用、虚引用的处理必须在 STW 中完成，原因：

- 不同强度引用的处理顺序必须严格：soft 先于 weak 先于 phantom
- `Reference.referent()` 与 Finalizer 的交互可能涉及对象图遍历，并发执行会产生竞争
- Shenandoah 的经验是**弱引用处理占 Final Mark STW 时间的主要部分**

### 3. 确定 CSet

Final Mark STW 汇总所有 Region 的存活数据统计，正式**确定**本轮要回收的 Region 集合（CSet）。选择策略见 [Shenandoah Evacuation](/docs/CS/Java/JDK/JVM/GC/Shenandoah/Evacuation.md)。

### 4. 触发并发疏散

Final Mark STW 结束后，GC 启动并发疏散阶段，同时清除 SATB 写屏障的武装状态。

## Final Mark STW Time Breakdown

Shenandoah 官方测试中 Final Mark STW 的时间分布大致是：

| 工作项 | 占比 |
| --- | --- |
| 排空 SATB 缓冲区 | ~30-50% |
| 弱引用处理 | ~20-40% |
| 扫描活跃监视器（Locked Objects） | ~10-20% |
| CSet 选择 + Region 状态切换 | <10% |
| 类卸载 | <5% |

弱引用和 SATB 排空是 Final Mark 暂停时间的主要瓶颈。

## Two Pauses Summary

整个 GC 周期只有两个 STW 阶段：

| 阶段 | 典型耗时 | 工作内容 |
| --- | --- | --- |
| **Initial Mark** | ~1-5 ms | 根集扫、武装 SATB、初步 CSet |
| **Final Mark** | ~2-12 ms | SATB 排空、弱引用处理、Final CSet、触发疏散 |

**两个 STW 的耗时都与堆大小基本无关**——只与根集大小、SATB 队列长度、弱引用数量相关。这是 Shenandoah（以及 ZGC、G1）相对 Parallel GC / CMS 的核心优势。

## References

1. [PPPJ 2016: Shenandoah](https://tech-notes.accel.dk/programming/java/java12/docs/PPPJ2016.pdf) — 原始 SATB 设计
2. [Shenandoah Proposal PDF](https://mail.openjdk.org/pipermail/hotspot-gc-dev/attachments/20160513/cde124dd/ShenandoahProposal.pdf) — Concurrent Marking + Update References
3. [Shipilev: Shenandoah GC September 2017](https://shipilev.net/talks/vmm-Sep2017-shenandoah.pdf) — Final Mark STW 时间分布
4. [Deep Dive into ZGC](https://dl.acm.org/doi/pdf/10.1145/3538532) — ZGC 标记机制，可对比
5. [The Taming of the Shrew: SATB Marking in Shenandoah](https://openjdk.org/jeps/379) — JEP 379 Shenandoah production 引入的 SATB 细节

## Links

- [Shenandoah 枢纽页与知识地图](/docs/CS/Java/JDK/JVM/GC/Shenandoah.md)
- [Shenandoah Brooks Pointer（标记和转发都用 Region bitmap）](/docs/CS/Java/JDK/JVM/GC/Shenandoah/BrooksPointer.md)
- [Shenandoah Evacuation（标记完成后的疏散阶段）](/docs/CS/Java/JDK/JVM/GC/Shenandoah/Evacuation.md)
- [Shenandoah Barriers（SATB 写屏障原理）](/docs/CS/Java/JDK/JVM/GC/Shenandoah/Barriers.md)
- [G1 Concurrent Marking（对比：G1 SATB + TAMS + Finger）](/docs/CS/Java/JDK/JVM/GC/G1/ConcurrentMarking.md)
