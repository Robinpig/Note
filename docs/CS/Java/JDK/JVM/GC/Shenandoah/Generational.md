## Introduction

分代 Shenandoah 由 **[JEP 404](https://openjdk.org/jeps/404)**（JDK 24，实验性）引入，把 Java 堆分为 young / old 两代，利用"多数对象朝生夕死"的分代假设。截至 JDK 27，**默认仍是 `satb` 非分代模式**；分代成为默认是 JDK 28 的目标（[JEP 535](https://openjdk.org/jeps/535)，Targeted）。

与非分代 Shenandoah 相比，分代模式的改进目标：

| 目标 | 非分代 Shenandoah 的问题 | 分代方案 |
| --- | --- | --- |
| 降低内存占用 | 不分代标记全堆 → 标记阶段堆冗余大 | GC 集中在 young 代（大多已死）→ 回收效率高 |
| 降低 CPU 开销 | 每次标记都扫全堆 | young 收集只扫 young + old→young 引用 |
| 减少退化 GC / Full GC | 分配尖峰容易把堆撑爆 → 退化或 Full GC | young 代回收频繁、空间释放及时 → 分配尖峰更稳 |
| 维持压缩指针 | ✅ LRB 已支持 32-bit | ✅ 分代模式继续支持（ZGC 分代做不到） |

## How to Enable

```shell
# JDK 24+ 实验性分代模式（需解锁实验选项）
java -XX:+UnlockExperimentalVMOptions -XX:ShenandoahGCMode=generational

# 确认模式
java -XX:+UnlockExperimentalVMOptions -XX:ShenandoahGCMode=generational -Xlog:gc
# 输出中应包含 "Shenandoah GC mode: generational"
```

对比 ZGC 的分代启用：

```shell
# ZGC 分代：JDK 21+ 默认就有（JDK 23 起已是默认）
java -XX:+UseZGC
```

Shenandoah 分代比 ZGC 分代**晚了 3 个 JDK 版本**（JDK 24 vs JDK 21），且尚未成为默认。

## Generation Layout

分代 Shenandoah 仍使用 Region 堆布局，但每个 Region 有了代属：

- 任一时刻，一个 Region 要么 free、要么专属于 young、要么专属于 old
- **没有** Region 可以同时属两代，也没有 Region 可以部分转移代属

### Generation Size 与 Quota

每一代的大小 = 已占用 Region 数量 + 一部分**空闲 Region 配额**。两代配额之间可以**临时越界借用**，但越界会加速触发 GC：

- young 代借用 old 配额 → 更早触发 young GC
- old 代借用 young 配额 → 更早触发 old GC

越界不会立即 OOM，但持续越界会把 GC 频率推到极致，最终可能退化或 Full GC。

### 与 G1 代布局对比

| 维度 | G1 Young/Old | Shenandoah Generational |
| --- | --- | --- |
| Region 划分 | Young Region（Eden + Survivor）/ Old Region（按年龄） | Young Region / Old Region（每代专属 Region） |
| 年龄追踪 | TLAB + age table + MaxTenuringThreshold | 内部年龄统计，tenuring 自动调优 |
| 代间转移 | STW 做 tenuring | 并发 tenuring（GC 周期内自动） |
| Mixed GC | Young + 部分 Old（STW 并发 CSet） | young/mixed 都**并发**，不 STW |

## Remembered Set（跨代引用）

分代 Shenandoah 的 RSet 有两个来源：

### 1. Card Marking（写屏障 + 卡表）

借用 Parallel / CMS 的 card marking 代码：

- Region 被切成固定大小的 card（通常 512 bytes）
- 当 mutator 写 old generation Region 的一个字段时，SATB 写屏障顺便把该字段所在的 card 标记为 dirty
- dirty card 集合就是 old→young 跨代引用的候选位置

### 2. 并发 RSet 扫描

Shenandoah 相比 G1 独有的优势：RSet 扫描可以**与 mutator 并发执行**，不需要 STW。原因：

- Shenandoah 的 Region bitmap + Brooks pointer 让 RSet 扫描线程能安全并发遍历
- G1 的 RSet 扫描必须 STW（或 STW 部分），因为 G1 的 refinement 线程是并发**维护** RSet，而 young GC 必须 STW **扫描** RSet

这直接导致 Shenandoah 的 young GC 也是并发的——G1 young GC 必须 STW。

### 与 ZGC RSet 对比

| 维度 | Shenandoah Generational | Generational ZGC |
| --- | --- | --- |
| RSet 来源 | Card marking + SATB 写屏障 | Store barrier + metadata bits |
| RSet 粒度 | Card（512 bytes，偏粗） | 具体字段地址（精确） |
| RSet 维护 | 写屏障 + refinement 线程 | store barrier slow path act-once |
| RSet 扫描 | **并发** | 并发 |
| RSet 复杂度 | 低（复用成熟 card marking） | 高（双缓冲、与 metadata bits 深度耦合） |

## Collection Modes

分代 Shenandoah 有三种收集模式：

### 1. Young Collection

只回收 young generation，流程：

1. Concurrent Mark young generation（satb + RSet 扫描 old→young 引用）
2. Concurrent Evacuation young generation（speculative copy）
3. 把存活对象 tenuring 到 old generation

**全程并发，无 STW**。这是 Shenandoah 分代最大的卖点——G1 young GC 必须 STW。

### 2. Mixed Collection

回收 young generation + **部分** old generation（选存活数据最少的 old Region）。流程类似 young collection，但 old Region 也被纳入 CSet。

G1 也有 mixed GC，但 **G1 mixed GC 的 young/mixed 切换必须 STW**。Shenandoah 的 young 和 mixed collection 都并发。

### 3. Old Collection

只回收 old generation。类似 G1 的 full marking cycle，但 Shenandoah 的 old marking **与 young marking 解耦**——old marking 在后台并发推进，young GC 多次发生后 old marking 才完成。

## Reused Mechanisms

分代 Shenandoah **最大程度复用了非分代 Shenandoah 的既有机制**：

| 机制 | 是否复用 | 说明 |
| --- | --- | --- |
| LRB（Load Reference Barrier） | ✅ 原样 | 32-bit LRB 压缩指针支持，分代不改变 LRB 语义 |
| SATB 写屏障 | ✅ 广义化 | SATB 缓冲区后处理区分 old/young 引用，但 fast path 不变 |
| Evacuator（疏散器） | ✅ 一个 evacuator 服务两代 | young 和 old 的 evacuation 用同一个 speculative copy 协议 |
| Heuristics | ⚠️ 新增 young 相关启发 | young GC 触发频率、young 代 sizing、tenuring age |
| Brooks Pointer | ✅ 原样 | 分代不改变对象布局和转发协议 |

复用是 Shenandoah 分代比 ZGC 分代**成本更低**的原因之一——ZGC 分代取消 multi-mapping、改低阶位 layout、加 store barrier，是破坏性变更。

## Comparison with ZGC Generational

| 维度 | Generational Shenandoah | Generational ZGC |
| --- | --- | --- |
| 引入版本 | JDK 24（实验，JEP 404） | JDK 21（JEP 439） |
| 成为默认 | JDK 28 目标（JEP 535, Targeted） | JDK 23 已默认（JEP 474） |
| 读屏障 | Brooks 指针 LRB（1 条 movptr，无 slow path） | 着色指针 load barrier（shift + test + self-heal） |
| 写屏障 | SATB 写屏障 + 疏散写屏障 | store barrier（RSet + SATB） |
| 并发重定位 | speculative copy（mutator 主动参与） | self-healing CAS（mutator 被动修复） |
| 压缩指针 | ✅ 支持（32-bit LRB） | ❌ 不支持（指针 metadata 占用 bit） |
| 最大堆 | 与 G1 相当（~4-8 TB 视配置） | TB 级（理论 ~16+ TB） |
| RSet | Card marking（粗粒度） | metadata bits + 双缓冲（精确） |
| young GC 模式 | **并发** | 并发 |
| mixed GC young/mixed 切换 | **并发** | 并发 |
| 对象布局开销 | 可选 extra word / mark word 编码 | 无 |

> **对绝大多数堆 < 32 GB 的云负载**，Shenandoah 分代支持压缩指针是相对 ZGC 分代的**唯一显著优势**。ZGC 分代在大堆、超低停顿、最大堆等维度明显领先。

## References

1. [JEP 404: Generational Shenandoah](https://openjdk.org/jeps/404) — 分代 Shenandoah 原始设计
2. [JEP 535: Shenandoah GC: Generational Mode by Default](https://openjdk.org/jeps/535) — JDK 28 目标（Targeted）
3. [PPPJ 2016: Shenandoah](https://tech-notes.accel.dk/programming/java/java12/docs/PPPJ2016.pdf) — RSet 并发扫描
4. [Deep Dive into ZGC](https://dl.acm.org/doi/pdf/10.1145/3538532) — ZGC Generational 可对比
5. [JEP 439: Generational ZGC](https://openjdk.org/jeps/439) — ZGC Generational 设计，对比表来源

## Links

- [Shenandoah 枢纽页与知识地图](/docs/CS/Java/JDK/JVM/GC/Shenandoah.md)
- [Shenandoah Brooks Pointer（分代模式复用的 LRB 基础）](/docs/CS/Java/JDK/JVM/GC/Shenandoah/BrooksPointer.md)
- [Shenandoah Barriers（分代模式复用的 SATB 写屏障）](/docs/CS/Java/JDK/JVM/GC/Shenandoah/Barriers.md)
- [ZGC Generational（对比：着色指针 store barrier vs Shenandoah card marking）](/docs/CS/Java/JDK/JVM/GC/ZGC/Generational.md)
- [Card Table（RSet 的基础实现）](/docs/CS/Java/JDK/JVM/GC/CardTable.md)
- [G1 Garbage Collector（同为分代 GC，对比）](/docs/CS/Java/JDK/JVM/GC/G1.md)
