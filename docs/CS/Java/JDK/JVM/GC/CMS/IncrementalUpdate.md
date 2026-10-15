## Introduction

CMS（JDK 6–14）是 HotSpot 中**唯一使用增量更新（incremental update）**做并发标记的收集器。其他所有并发收集器（G1、Shenandoah、ZGC）都用 **SATB（Snapshot-At-The-Beginning）**。理解增量更新对理解 CMS 的"浮动垃圾 → CMF → 被移除"整条缺陷链至关重要——**增量更新是 CMS 所有结构性问题的根源**。

增量更新和 SATB 解决的是同一个问题：**mutator 在并发标记期间修改对象图，怎么保证标记的正确性**。解法截然不同：

| 维度 | CMS 增量更新 | G1/ZGC/Shenandoah SATB |
| --- | --- | --- |
| 写屏障记录**什么** | 记录**新值**（被写入的对象） | 记录**旧值**（被覆盖的对象） |
| 正确性保证 | 所有变成"外部可达"的对象会被追踪 | 快照时刻所有可达对象在标记结束时都被标记 |
| **浮动垃圾** | **会产生**（标记期间变成不可达的对象不会被取消标记） | **不会**（快照保证无关变化） |
| 与并发重定位的兼容性 | **不兼容**（标记期间引用变更太多，无法正确追踪） | **兼容**（快照保证让 evacuation 在标记并发时正确处理引用） |
| 写屏障复杂度 | 相对简单 | 更复杂（SATB record + card marking + RSet refinement 三合一） |
| Remark STW 压力 | 大（脏卡重扫 + Roots 补漏） | 相对小（SATB 快照减少漏标） |

## HotSpot 并发标记两流派

HotSpot 并发标记的两大正确性方案，源自对象图在 mutator + GC 并发下的三种不一致场景：

1. **Lost Pointer**（丢失指针）：GC 从 A 扫到 B，mutator 把 A→B 改成 A→C，同时把 B→D 改没了。GC 可能漏掉 D。
2. **Black → White**：mutator 覆盖一个黑对象到白对象的引用。黑对象是"已完成引用扫描"的，所以白对象不会被 GC 发现。
3. **White 新引用**：mutator 覆盖一个白对象到另一个对象的引用，两个都还没被 GC 扫过。

### 增量更新怎么解决

增量更新只解决 **Black → White**：

> 每当 mutator 修改了一个对象引用 `x.f = y`，写屏障检查 `x`（被修改字段所属对象）的标记颜色。如果 `x` 是**黑**的，说明 GC 已经完成了对 `x` 的子引用扫描——但 `x` 现在又多了一条新引用到 `y`（`y` 可能是白的）。写屏障把 `x` **重新置灰**（或把 `y` 加入标记队列），让 GC 重新扫一遍 `x` 的所有子引用。

增量更新**不处理"标记期间变成不可达"的对象**——如果对象在 GC 追踪之后变成不可达，它不会被取消标记，最终要等下一周期 Sweep 掉。这就是**浮动垃圾（floating garbage）**。

### SATB 怎么解决

SATB 在并发标记开始时对**所有 GC Roots** 做快照。写屏障在 mutator 覆盖一个字段时，把**被覆盖的旧值**（不是新值）入队。正确性保证：

- 快照时刻所有 Roots 可达的对象一定被标记
- 标记期间变成不可达的对象（原本在快照里）也一定被标记（因为它在快照里可达）
- 标记期间新出现的可达对象不需要标记（快照不关心）

SATB 天然不产生浮动垃圾——只要对象在快照里可达，标记就一定会覆盖到它；之后变成不可达也无关紧要。

### 关键代码：CMS Incremental Update Write Barrier

```cpp
// 简化伪代码
void CMSIncrementalUpdateBarrier::write_barrier(oop x, oop* p, oop y) {
  // x: 被修改字段所属对象
  // p: 字段地址
  // y: 新写入的对象引用

  // 只在老年代对象上做检查（CMS 只管 Old GC）
  if (!is_in_old_gen(x)) return;

  // 如果 x 已经是灰色或白色，标记线程会自然扫到它的新引用
  // 我们只需要处理 x 是黑色的情况（GC 已经完成了 x 的子引用扫描）
  if (mark_bitmap.is_black(x)) {
    // 把 y 加入 CMS 标记队列
    // 或者更高效地：把 x 重新置灰
    _mark_queue.push(y);
  }

  // 标记并发标记期间发生了引用变更
  _dirty_card_queue_set.enqueue(x);
}
```

对比 G1 SATB 写屏障：

```cpp
// G1 SATB 写屏障（简化伪代码）
void G1SATBBarrier::write_barrier(oop x, oop* p, oop y) {
  // 1. 只在并发标记进行中才执行
  if (!_marking_active) return;

  // 2. 把**旧值**（覆盖前的引用）入队，不是新值
  oop old = *p;
  if (old != nullptr) {
    _satb_queue.enqueue(old);
  }

  // 3. 额外：RSet refinement
  if (is_in_old_gen(x) && is_in_young_gen(y)) {
    _rset_refinement_queue.enqueue(x);
  }
}
```

## CMS Concurrent Mark 全流程

CMS 用**双色标记**（White = 未标记，Gray = 已标记但子引用未追踪）。没有 Black——当灰色对象的子引用全部追踪完，它自动"消失"在 CMS 的语义里（CMS 用 White = 不可达来决定 Sweep 哪些对象，Gray/Black 只是标记过程中的中间态）。

### Initial Mark → Concurrent Mark → Remark 时间线

```
Initial Mark (STW)
  └─ 扫描 Roots，标记第一层 young→old 引用为 Gray
      │
      ▼
Concurrent Mark（并发）
  ├─ 标记线程从 Gray 对象出发，BFS/DFS 追踪整个老年代对象图
  ├─ 增量更新写屏障持续把"黑对象的新引用"加入标记队列
  ├─ 标记完的对象清零标记位 → 标记完成 = 对象在 Sweep 时不会被清除
  ├─ Concurrent Precleaning（CMS 独有）：Remark 之前尝试并发处理最脏的卡
  │
  ▼
Remark (STW)
  ├─ 重扫脏卡（Concurrent Precleaning 漏掉的）
  ├─ 重扫所有 GC Roots（找出增量更新没覆盖到的新引用）
  ├─ 同步 flush CMS 内部标记队列
  │
  ▼
Concurrent Sweep（并发）
  └─ 所有没被标记为"可达"（White）的老年代对象归还到空闲链表
```

### Remark STW 三数据源

Remark 是 CMS 周期中最长的暂停，三个数据源：

1. **Card Table 脏卡重扫**：应用线程修改老年代跨代/跨对象引用时，写屏障把卡标脏。Remark 暂停后，CMS 逐张扫描脏卡对应的内存地址范围
2. **Roots 重扫**：Concurrent Mark 期间，ClassLoader 常量池、Monitor、JNI handles 等可能被 mutator 修改。Remark 重新扫描所有 GC Roots
3. **CMS 内部数据结构 flush**：`CMSCollector::_mark_stack`、`CMSCollector::_dirty_card_queue_set` 在 Remark 期间被同步处理

Remark 暂停时间典型在 几 ms ~ 几十 ms，取决于并发标记期间应用线程修改了多少引用。

### Why No Concurrent Relocation

CMS 增量更新 + 标记-清除 = **无法做并发重定位**。原因：

- 重定位需要修改所有对象字段中的引用（把指向 from-region 对象的旧地址改成新地址）
- 增量更新的写屏障只追踪"新值的对象"，不追踪"字段本身"——无法知道哪个字段当前指向一个被重定位的对象
- 如果 mutator 在 GC 移动对象的同时更新了引用，增量更新无法正确追踪这次变更

ZGC/Shenandoah 解决了这个问题：

- ZGC：**load barrier + colored pointer** 在每次引用读取时自动修复地址
- Shenandoah：**LRB + Brooks pointer** 在每次引用读取时自动穿越 forwarding 指针
- 两者都用 SATB（或 ZGC 非分代的变体），**配合读屏障**实现并发重定位

G1 是中间态：SATB + **STW 疏散**（Young GC 和 Mixed GC 的 evacuation 是 STW 的），没有完全并发重定位。

## Floating Garbage 详解

增量更新的"不取消标记"特性必然产生浮动垃圾——**在并发标记期间变成不可达的对象**。

### 数量估计

浮动垃圾的数量取决于：

```
浮动垃圾 ≈ 并发标记周期时长 × 应用分配速率 × 存活对象比例的估计误差
```

CMS 经验：老年代调大约 **20%** 以容纳浮动垃圾。上一周期结束时的浮动垃圾会在下一周期 Sweep 时被清除。

### 为什么 CMS 特别严重

- CMS 标记-清除**不压缩**，浮动垃圾直接占住真实内存
- G1/ZGC/Shenandoah 的浮动垃圾在疏散/重定位阶段就被搬掉了
- CMS 的浮动垃圾 + 不压缩碎片 = **双重问题**

浮动垃圾直接驱动 **CMF（Concurrent Mode Failure）**——如果浮动垃圾多到让老年代在 CMS 完成前耗尽，就触发 STW Full GC。

## References

1. [Pirinen: Incremental Update Marking](https://dl.acm.org/doi/10.1145/3061659.3061667) — 增量更新正确性论文
2. [Wilson: Garbage Collection Considered Harmful](https://dl.acm.org/doi/10.1145/60974.60978) — 写屏障方向对并发标记的影响
3. [CMS Collector Documentation (Java 8)](https://docs.oracle.com/javase/8/docs/technotes/guides/vm/gctuning/cms.html) — 官方文档
4. [HotSpot CMS 源码解读 - Incremental Update](https://blog.csdn.net/xushiyu1996818/article/details/102759591)
5. [CMS vs G1: Marking Barriers Compared](https://openjdk.org/jeps/404) — JEP 404 中有对比

## Links

- [CMS 枢纽页与知识地图](/docs/CS/Java/JDK/JVM/GC/CMS.md)
- [CMS Concurrent Mode Failure（浮动垃圾导致 CMF）](/docs/CS/Java/JDK/JVM/GC/CMS/ConcurrentModeFailure.md)
- [CMS Removal（增量更新的结构性缺陷导致 CMS 被移除）](/docs/CS/Java/JDK/JVM/GC/CMS/Removal.md)
- [G1 Concurrent Marking（对比：G1 SATB 原理）](/docs/CS/Java/JDK/JVM/GC/G1/ConcurrentMarking.md)
- [Shenandoah Concurrent Marking（SATB 实现）](/docs/CS/Java/JDK/JVM/GC/Shenandoah/ConcurrentMarking.md)
