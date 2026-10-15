## Introduction

Shenandoah 的屏障体系与 ZGC 形成鲜明对比：

| 维度 | Shenandoah | ZGC |
| --- | --- | --- |
| **读屏障（LRB）** | ✅，1 条 movptr，fast path 恒等，slow path 极轻 | ✅，shift + test + slow path（self-healing CAS） |
| **SATB 写屏障** | ✅（SATB 标记需要） | ❌（ZGC 不用 SATB，非分代 ZGC 无写屏障） |
| **并发疏散写屏障** | ✅（speculative copy 协议需要） | ❌（ZGC 用 self-heal 而不是让 mutator 拷贝） |
| **双重写屏障** | ✅（SATB 写屏障 + 疏散写屏障同时生效） | ❌ |

这个三重屏障体系让 Shenandoah 能**同时**：
1. 维持 SATB 标记正确性
2. 维持 from-region 不变式（写入不发生在 from-region）
3. 通过 LRB 自动修复所有重定位引用

## Load Reference Barrier (LRB)

LRB 是 Shenandoah 读路径上唯一的屏障。详细机制见 [Shenandoah Brooks Pointer](/docs/CS/Java/JDK/JVM/GC/Shenandoah/BrooksPointer.md)。这里只总结关键点。

### C2 伪代码

```cpp
void ShenandoahBarrierSet::compile_resolve_oop() {
  __ movptr(dst, Address(dst, -8));  // dst - 8 指向 Brooks pointer word
}
```

### Fast Path / Slow Path

**严格来说 LRB 没有 slow path 检查**——它总是执行同一条 movptr：

- 如果对象没被重定位：Brooks pointer word 指向自身 → LRB 是恒等变换
- 如果对象已被重定位：Brooks pointer word 指向 to-region 副本 → LRB 自动转发

这种"无分支、无条件"的屏障实现让 LRB 比 ZGC load barrier fast path **简单得多**。ZGC 必须先 shift 剥离 metadata bits，再 test 判断是否需要 slow path（relocation 修复）。

### 与 ZGC Load Barrier 开销对比

在对象未被重定位时：

- **Shenandoah LRB**：1 条 movptr（缓存命中后 ~1 周期），可被 JIT 在某些情况下去除
- **ZGC load barrier**：1 条 shift + 1 条 test + 条件跳转（~2-3 周期）

Shenandoah 用 per-object 8 bytes（或 mark word bits）换来了更简单的读屏障。

## SATB Write Barrier

Shenandoah 用 SATB（Snapshot-At-The-Beginning）并发标记算法。SATB 正确性的维护依赖一道**写屏障**——当 mutator 覆盖某个堆对象的引用字段时，必须把**被覆盖的旧值**交给 GC 标记线程扫描。

### 问题场景

初始标记（Initial Mark）STW 结束时，GC 对所有 GC Roots 做了快照。在后续并发标记期间，如果 mutator 把对象 A 的某个字段从 B 改成 C（假设 B 原本"应该被标记"但还没被标记线程扫到），GC 就可能漏掉 B。SATB 写屏障确保：**任何在标记开始时被引用、后来又被断开的对象，都会被 GC 看到**。

### 写屏障逻辑

```cpp
void ShenandoahBarrierSet::satb_store_oop(oop* p, oop v) {
  // 1. 读旧值
  oop old = *p;

  // 2. 存入新值
  *p = v;

  // 3. 把旧值交给 SATB 标记队列
  if (old != nullptr) {
    _satb_queue.enqueue(old);
  }
}
```

### Fast Path 优化

SATB 写屏障的 fast path 只在**标记周期进行中**才真正执行——当 GC 不在标记时，写屏障退化成纯 store。具体优化：

- 编译时插入一条 GC 标记期 flag 检查：flag == false → 跳过屏障
- C2 在编译路径上可以**在 GC 安全点动态 patch 这个检查**：标记开始时把条件 patch 成"永远真"，标记结束时 patch 回"永远假"

这让 SATB 写屏障的非标记期开销几乎为零。

### 与 G1 / CMS SATB 写屏障对比

Shenandoah 的 SATB 写屏障与 G1（SATB 模式）、CMS（SATB 模式）的实现几乎相同——都是"覆盖 → 入队旧值"。差异在于：

- G1 的 SATB 写屏障只在并发标记期间生效，**标记结束后自动失效**
- CMS 类似，但 CMS 的 Concurrent Mark 之后还有 Remark STW 补漏
- Shenandoah 也类似（标记期间生效），但它的 Final Mark STW 非常短（因为并发疏散是独立的、不依赖 SATB）

## Evacuation Write Barrier（Concurent Evacuation Write Barrier）

这是 Shenandoah 特有的第二道写屏障。SATB 写屏障负责标记正确性，疏散写屏障负责**维持 from-region 不变式：写入永远不发生在 from-region**。

### 不变式

Shenandoah 并发疏散期间有一个核心不变式：

> **mutator 永远不会直接写入 from-region 对象**——要么该对象已经被拷贝到 to-region（通过 speculative copy），要么写入操作会触发一次 speculation copy。

如果没有这条不变式，并发 GC 线程在拷贝对象时，mutator 可能同时修改 from-region 的副本——GC 线程读到的是部分更新后的对象，拷贝出去的是不一致数据。

### 写屏障逻辑

```cpp
void ShenandoahBarrierSet::evacuation_store_oop(oop* p, oop v) {
  oop obj = obj_of(p);  // p 所在的对象

  // 检查 evacuation 是否进行中
  if (!ShenandoahHeap::evacuation_in_progress()) {
    return;  // 不在疏散期，跳过
  }

  // 检查 obj 是否在 from-region
  if (!ShenandoahHeap::is_in_cset(obj)) {
    return;  // 不在 CSet，跳过
  }

  // speculation copy：把 obj 拷贝到 to-region，然后更新 Brooks pointer
  obj = ShenandoahEvacuator::speculation_copy(obj);

  // 在新副本上执行原本打算的写入
  *p_in_new_copy = v;
}
```

### 双屏障顺序

当两道写屏障同时生效（并发标记 + 并发疏散都在进行时），顺序至关重要：

```
1. 先读旧值（SATB 写屏障需要）
2. SATB 入队旧值（SATB 写屏障 slow path）
3. 执行 evacuation write barrier（如果对象在 from-region）
4. 存入新值
```

### evacuation_in_progress Flag 的可见性

`evacuation_in_progress` flag 在 **Final Mark STW 期间被置位**，在**所有拷贝工作完成时被并发清除**。这个 flag 的读写顺序必须严格：

- 如果写屏障先读到 **flag 已清除**、但对象 Brooks pointer 还指向 from-region，就可能误写到 from-region 对象
- 反过来，如果先读到 Brooks pointer 指向 from-region、再读到 flag 为 true，会触发保守的 speculation copy

Shenandoah 在写屏障里用了**保守策略**：先检查 `evacuation_in_progress` flag → 如果为 true 就检查对象是否在 CSet。这样即使 flag 从 true 翻到 false，也只会多做一次不必要的 speculation copy（回滚成本极低）。

## Read vs Write Barrier 分工

| Barrier | 插入位置 | 做什么 | Fast Path | Slow Path |
| --- | --- | --- | --- | --- |
| **LRB** | 堆引用**读** | 解 Brooks pointer → 自动转发 | 1 条 movptr | 无（LRB 总是 movptr） |
| **SATB** | 堆引用**写** | 入队被覆盖的旧值 | flag 检查 + 纯 store | SATB queue enqueue |
| **疏散** | 堆引用**写** + mark word 写 | speculation copy from-region 对象 | flag + CSet 检查 | 拷贝 + CAS 更新 Brooks pointer |

注意疏散写屏障不只在堆引用写时触发——**对象加锁（mark word 写）**也需要它，因为 mark word 写也算堆内写操作。

## 与 ZGC Barrier 体系对比

| 维度 | Shenandoah | Generational ZGC |
| --- | --- | --- |
| 读屏障 | LRB：恒等 movptr（无 slow path） | load barrier：shift + test + self-heal |
| 写屏障 | SATB + 疏散（双重） | store barrier：RSet + SATB |
| slow path 频率 | LRB 几乎零；SATB/疏散只在 GC 活跃期 | load barrier 在 relocation 期较高；store barrier act-once |
| mutator GC 工作 | speculation copy 失败时回滚 | self-healing CAS + SATB 标记 |
| 压缩指针 | ✅ 支持 32-bit LRB | ❌ 不支持 |
| Barrier 总数 | 2 种（LRB + 双重写） | 2 种（load + store），职责分割不同 |

## References

1. [Shenandoah Proposal PDF (OpenJDK)](https://mail.openjdk.org/pipermail/hotspot-gc-dev/attachments/20160513/cde124dd/ShenandoahProposal.pdf) — 原始屏障设计
2. [Shenandoah GC in JDK 13, Part I: Load Reference Barriers](https://rkennke.wordpress.com/2019/05/15/shenandoah-gc-in-jdk13-part-i-load-reference-barriers/) — R. Kennke 的博客
3. [Deep Dive into ZGC](https://dl.acm.org/doi/pdf/10.1145/3538532) — ZGC barrier 体系，可对比
4. [PPPJ 2016: Shenandoah](https://tech-notes.accel.dk/programming/java/java12/docs/PPPJ2016.pdf) — 三重屏障原理
5. [Shenandoah GC...September 2017](https://shipilev.net/talks/vmm-Sep2017-shenandoah.pdf) — Shipilev 讲解 evacuation 写屏障

## Links

- [Shenandoah 枢纽页与知识地图](/docs/CS/Java/JDK/JVM/GC/Shenandoah.md)
- [Shenandoah Brooks Pointer（LRB 的底层机制）](/docs/CS/Java/JDK/JVM/GC/Shenandoah/BrooksPointer.md)
- [Shenandoah Concurrent Marking（SATB 标记正确性）](/docs/CS/Java/JDK/JVM/GC/Shenandoah/ConcurrentMarking.md)
- [Card Table（传统分代 GC 的 remembered set）](/docs/CS/Java/JDK/JVM/GC/CardTable.md)
