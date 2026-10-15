## Introduction

分代 ZGC（**[JEP 439](https://openjdk.org/jeps/439)**）于 JDK 21 引入，**[JDK 474](https://openjdk.org/jeps/474)**（Release 23）起成为默认模式，**[JEP 490](https://openjdk.org/jeps/490)**（Release 25）移除了非分代模式。现在 `java -XX:+UseZGC` 直接启用分代 ZGC。

非分代 ZGC 的设计目标是**超低延迟（暂停 < 1ms）+ 超大堆（数 TB）**，但它不利用"多数对象朝生夕死"这个分代假设，导致三个问题：

| 问题 | 影响 |
| --- | --- |
| 分配停顿（allocation stalls）风险高 | 堆中存活对象多，全堆并发标记耗时长，Mutator 被迫 stall 等待 GC 回收出空间 |
| 堆冗余开销大 | 非分代 GC 必须预留足够空间给最坏情况（所有对象长寿命），实际却有大量短命对象被白白保留 |
| GC CPU 开销高 | 每次回收都要扫描全堆对象图 |

分代 ZGC 把堆切成 **young generation**（新分配对象）和 **old generation**（长寿命对象），让 young gen 被更频繁、更高效地回收。同时**保留了非分代 ZGC 的所有核心特性**：暂停 < 1ms、TB 级堆、着色指针、load barrier。

## Enabling

```shell
# JDK 21/22：显式开启分代（当时非默认）
java -XX:+UseZGC -XX:+ZGenerational

# JDK 23+：分代已是默认
java -XX:+UseZGC

# 废弃的非分代模式（JDK 23+ 给废弃警告）
java -XX:+UseZGC -XX:-ZGenerational
```

## Design Overview

分代 ZGC 的关键设计决策：

1. **在着色指针里用独立的 metadata bits 追踪各代状态**，让两个代可以独立回收
2. **引入 store barrier（写屏障）**，高效维护 old→young 的 remembered set
3. **取消 multi-mapped memory**，用显式 barrier 代码替代
4. **把标记职责从 load barrier 移到 store barrier**

### 两类 Driver 线程

分代 ZGC 维护两个 GC 驱动线程：

- **`ZDriverMinor`**：负责 young generation 的 minor GC
- **`ZDriverMajor`**：先回收 young（preclean / roots 阶段），再回收 old generation

major GC 内部可以包含一次 young gen 的 preclean（为后续 old gen 收集做准备），然后再独立完整地回收 old gen。

## Design Concepts

JEP 439 列出了七个区分分代 ZGC 与非分代 ZGC（以及与其他收集器）的设计概念。

### No Multi-Mapped Memory

非分代 ZGC 用 multi-mapped memory 把同一段物理内存映射到三个虚拟地址区间（Marked0 / Marked1 / Remapped），让 load barrier fast path 几乎零开销。

分代 ZGC **完全取消了 multi-mapping**，改用显式 barrier 代码。收益：

- `ps` 报告的堆内存不再虚高 3 倍，运维能正确评估实际占用
- colored pointer 设计不再受虚拟地址范围限制，可以塞入更多 metadata bits
- 理论上最大堆可以超越非分代 ZGC 的 ~16 TB 上限

代价是 load barrier fast path 多了一条指令。但分代 ZGC 通过**把 metadata bits 移到低阶位**来抵消——低阶位布局下，一条 shift 指令同时完成"检查是否需要处理"和"剥离元数据"两个工作。

### Optimized Barriers

引入 store barrier 后，更多 GC 代码混入 JIT 编译路径。分代 ZGC 用以下优化降低 barrier 开销：

#### Fast Path / Slow Path

所有 barrier（load / store）都分裂为两部分：

- **Fast path**（>99% 执行）：直接嵌入 JIT 代码，检查一个条件位，条件满足则立即返回
- **Slow path**（<1% 执行）：独立 C++ 函数，做实际 GC 工作

fast path 设计准则：**纯算术逻辑、无内存访问、无函数调用**。

#### Minimizing Load Barrier Responsibilities

非分代 ZGC 的 load barrier 要做两件事：
1. Self-heal（relocation 修复）
2. **标记存活对象**（"应用在读这个对象 → 它被标记为活"）

分代 ZGC 把**标记职责全移到 store barrier**，load barrier 只做：
1. 剥离 metadata bits 得到纯地址
2. Self-heal

这让 load barrier fast path 几乎退化为一条 shift 指令。

#### Remembered-Set Barriers

分代 ZGC 维护一个 **remembered set**：记录 old generation 中所有可能指向 young generation 的对象字段地址。

store barrier 维护 RSet 的方式遵循 **act-once 语义**：
- 一个字段在一个 young gen 标记周期内，最多触发一次 slow path
- 第一次写入某个字段时，store barrier 检查旧值的 metadata bits
- 如果还没标记过（fast path 通过不了），slow path 把该字段地址加入 RSet，同时把**新写入的彩色指针**标记为"已登记"
- 后续对同一字段的写入，fast path 看到新彩色指针的标记位已置位，直接跳过 slow path

这个设计比传统 card marking 更精确——RSet 记录的是**具体字段地址**，而不是整张卡（通常 512 bytes），young gen GC 扫描效率更高。

#### SATB Marking Barriers

非分代 ZGC 用 incremental-update 标记算法，分代 ZGC 改用 **SATB（Snapshot-At-The-Beginning）**：

- 标记周期开始时，GC 对所有 GC Roots 做快照
- 标记结束时，**所有快照时刻存活的对象一定被标记**
- SATB 通过 store barrier 实现：每次写覆盖一个字段时，store barrier slow path 把**被覆盖的旧值**交给 GC 标记

为什么 SATB 适合分代 ZGC？
- SATB 的 store barrier slow path 同样遵循 act-once 语义（同一字段同一标记周期只报告一次旧值）
- 非分代 ZGC 用 incremental-update 是因为它有 multi-mapping，可以让 load barrier 同时做 relocating 和 marking；分代 ZGC 取消 multi-mapping 后，store barrier 成了更自然的标记承担者

#### Fused Store Barrier Checks & Barrier Patching

- **Fused checks**：把 RSet 检查、SATB 检查、彩色化新指针三个逻辑合并成一次 fast path
- **Barrier patching**：JIT 编译后，C2 可以在 GC 安全点把某些 fast path 条件从"检查 metadata bit"改写成"永远真"或"永远假"，完全跳过 barrier 代码

### Double-Buffered Remembered Sets

分代 ZGC 的 remembered set 使用**双缓冲设计**，让 RSet 的维护和消费可以并发进行：

- Young gen GC 的标记周期开始时，切换 RSet 的"读缓冲"和"写缓冲"
- GC 线程只扫描读缓冲，store barrier slow path 只往写缓冲加条目
- 如果写缓冲满了，标记周期会被延迟（或触发一次紧急清理）

这个设计避免了 young gen GC 期间 RSet 的读写竞争，让 young gen 回收**完全并发**（除了开始时的根集扫描）。

### Relocations Without Additional Heap Memory

传统分代 GC（G1 young GC、Parallel Scavenge）在 evacuation 时需要预留空闲 Region 作为 to-space。ZGC 不需要——它的 relocation **直接复用已经回收的 Region**：

1. 标记 → 选出存活对象
2. Relocation 准备 → 选出要回收的 Region（relocation set）
3. 并发 Relocation → 把 relocation set 中的存活对象拷贝到**上一个周期已经回收的 Region**（这些 Region 已经空闲）
4. 原位置 → 回收复用

这样 ZGC 不需要为 relocation 预留额外堆内存，堆利用率更高。

### Dense Heap Regions

分代 ZGC 把 old generation 的 Region 做得**更密集**（dense），不刻意选存活对象少的 Region 优先回收——因为 relocation 是完全并发的，GC 不用关心"搬多搬少"的 STW 成本。

这意味着 old gen 的回收选择标准是**Region 密度**（存活/总字节数比），密度高的 Region 可以更高效地搬迁（搬少量对象、释放大量空间）。

### Large Objects

非分代 ZGC 的 Large Region（N × 2 MB）在分代 ZGC 中继续保留，但有一个变化：

- Large objects 始终在 old generation
- Large objects 不参与 young gen GC（这是自然的，因为它们属于 old gen）
- Large objects 的 relocation 行为与普通 old gen Region 一致

这避免了大对象在 young gen 来回复制的开销。

### Full Garbage Collections

分代 ZGC 仍然可以触发 Full GC，但语义不同：

- **非分代 ZGC Full GC**：STW mark-compact，回收整个堆
- **分代 ZGC Full GC**：等价于一次 major GC + 更强的内存整理，不额外引入 mark-compact 算法

分代 ZGC 在以下情况触发 Full GC：
- 应用调用 `System.gc()`
- JVMTI force GC
- Heap dump / inspection
- 外部 DCMD `GC.run`

由于 ZGC 的常规回收周期已经包含并发 relocation，Full GC 的触发频率应该比 G1 更低。

## Links

- [ZGC 枢纽页与知识地图](/docs/CS/Java/JDK/JVM/GC/ZGC.md)
- [ZGC Colored Pointers（分代版 pointer layout 变更）](/docs/CS/Java/JDK/JVM/GC/ZGC/ColoredPointers.md)
- [ZGC Load Barrier（load/store barrier 职责分工）](/docs/CS/Java/JDK/JVM/GC/ZGC/LoadBarrier.md)
- [CardTable（分代 GC 的 remembered set 基础）](/docs/CS/Java/JDK/JVM/GC/CardTable.md)
- [Shenandoah Generational（分代模式对比：LRB+SATB vs 着色指针 store barrier）](/docs/CS/Java/JDK/JVM/GC/Shenandoah/Generational.md)
- [G1 Garbage Collector（同为分代 GC，对比）](/docs/CS/Java/JDK/JVM/GC/G1.md)

## References

1. [JEP 439: Generational ZGC](https://openjdk.org/jeps/439) — 分代 ZGC 原始设计文档，7 个设计概念的权威来源
2. [JEP 474: ZGC: Generational Mode by Default](https://openjdk.org/jeps/474) — JDK 23 起分代成为默认
3. [JEP 490: ZGC: Remove the Non-Generational Mode](https://openjdk.org/jeps/490) — 非分代模式移除
4. [Deep Dive into ZGC](https://dl.acm.org/doi/pdf/10.1145/3538532) — SATB、并发 relocation、SPIN 模型验证
5. [HotSpot-GC-Dev Mailing List - Generational ZGC RFR](https://mail.openjdk.org/archives/list/hotspot-gc-dev@openjdk.org/2025/6/) — 开发讨论
6. [ZGC: The Next Generation Low-Latency Garbage Collector](http://cr.openjdk.java.net/~pliden/slides/ZGC-OracleDevLive-2020.pdf) — 分代 ZGC 演进
