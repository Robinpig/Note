## Introduction

Shenandoah 的并发疏散（evacuation / concurrent compaction）是它与 G1 young GC / Full GC、ZGC relocation 的核心差异点。G1 和 ZGC 的 evacuation 本质上是**GC 线程自己做**——G1 young GC 是 STW 并行 Cheney 复制，ZGC relocation 是 GC 线程并发搬运 + mutator 被动 self-healing。Shenandoah 则引入了 **speculative copy 协议**，让 mutator 在**写入 from-region 对象时主动参与**疏散。

疏散的核心约束：
1. 全程与 mutator 并发，不暂停
2. 维持 from-region 不变式：写入不发生在 from-region
3. CSet（collection set）里的对象必须最终全部被疏散到 to-region
4. 引用更新（remap）在**下一轮并发标记期间**顺带完成，不单独做

## CSet Selection（Choosing the Collection Set）

CSet = 本轮要疏散的 from-region 集合。Shenandoah 的 CSet 选择遵循两个目标：

### 目标 1：跟上分配速度

必须回收的空间至少要跟上**上一个 GC 周期内 mutator 新分配的空间**。如果 CSet 太小，堆会持续增长直到耗尽。

### 目标 2：效率优先

挑选**存活数据最少**（垃圾占比最高）的 Region。理由：

- 如果一个 Region 里活对象只占 10%，搬 10% 就能释放 90% 空间——效率最高
- 暂停时间（Final Mark STW）与**根集大小**成正比，与 CSet 大小**无关**——Shenandoah 不需要在 STW 里处理 CSet 引用

这与 G1 young GC 的 CSet 选择完全不同：G1 young GC 只回收 Young Region，Mixed GC 才会加 Old Region，且 young GC 的暂停时间**随 Young Gen 大小线性增长**。

### 默认启发式（Heuristics）

Shenandoah 提供多种启发式，默认的规则大致是：

1. Initial Mark STW 时**初步**选一批垃圾占比 ≥ 60% 的 Region
2. Final Mark STW 时**最终**确定 CSet，加上存活统计更精确后的 Region
3. 已分配 Region 比例 ≥ 75% 时**启动**并发标记周期

Shenandoah 有完整的启发式接口（`ShenandoahHeuristics`），不同启发式可插拔替换——基于堆占用率、Region 密度、pace 等指标灵活选择。

## Speculative Copy 协议

CSet 确定后，GC 线程开始并发疏散。核心是 **speculative copy（推测性拷贝）**：

### 步骤

```
并发 GC 线程：
  1. 从 CSet 中取一个 from-region
  2. 遍历 from-region 的所有对象：
     a. 把对象"推测性"拷贝到自己的线程本地分配缓冲区（TLAB）
     b. CAS 更新对象的 Brooks pointer word，从指向自身 → 指向推测副本的 Brooks pointer word
     c. CAS 成功：拿到了权威副本，继续下一个对象
     d. CAS 失败：另一个线程（GC 或 mutator）抢先拷贝 → 回滚自己的副本，继续

mutator 线程（写入 from-region 对象时）：
  1. 疏散写屏障检查：evacuation in progress? 对象在 CSet 中?
  2. 如果是：同样用 speculative copy 协议，拷贝 + CAS
  3. CAS 成功：得到副本，在副本上执行写入
  4. CAS 失败：另一个线程抢先 → 回滚，改用对方副本
```

### CAS 循环伪代码

> 以下为**简化伪代码**，非 OpenJDK 实际源码。核心意图是传达 speculation copy + CAS retry 协议。

```cpp
oop ShenandoahEvacuator::speculation_copy(oop from) {
  address from_fwdptr = (address)from - 8;

  for (;;) {
    // 1. 读当前 Brooks pointer
    address cur_fwdptr = *from_fwdptr;
    if (cur_fwdptr != from_fwdptr) {
      // Brooks pointer 已经不在指向自己 → 对象已被拷贝过
      // 解引用得到真实副本地址
      oop real_copy = (oop)cur_fwdptr + 8;
      return real_copy;
    }

    // 2. 推测性拷贝
    oop speculation = (oop)_tlab->alloc(oop_size(from));
    Copy::aligned_disjoint_words((HeapWord*)from, (HeapWord*)speculation, obj_size);
    address spec_fwdptr = (address)speculation - 8;

    // 3. CAS 更新 Brooks pointer
    address prev = Atomic::cmpxchg(from_fwdptr, spec_fwdptr, cur_fwdptr);
    if (prev == cur_fwdptr) {
      // CAS 成功！我们的副本成了权威副本
      return speculation;
    }

    // CAS 失败：别人抢先了
    _tlab->undo_alloc(obj_size);  // 回滚推测副本
    // 用 prev 里的 Brooks pointer 继续尝试
  }
}
```

### 为什么叫 "speculative"

"推测" 的含义是：拷贝对象时还不知道"这个副本会不会被用到"——可能其他线程抢先拷贝了同一个对象，你的推测副本就白做了，需要回滚。这个推测成本极低（TLAB 上归只是 bump pointer 回退），而在 CSet 里对象通常没有竞争（每个 from-region 里的对象几乎不会被多个线程同时写）。

## 并发疏散的不变式

Shenandoah 在疏散期间维持两个关键不变式：

### 不变式 1：from-region 无写入

**所有对 from-region 对象的写入，要么在拷贝前触发 speculation copy，要么写入 to-region 副本**。这保证了 GC 线程并发拷贝时，from-region 里的对象内容不会被中途修改——拷贝出来的数据总是一致的。

### 不变式 2：to-region 不被移动

**to-region 对象在疏散期间不会被再次移动**。mutator 读 to-region 对象时，LRB 直接返回自身（Brooks pointer 指向自己），不需要做任何转发。这避免了 read storms（大量并发读同时触发屏障）。

## Read Storms vs Write Storms

传统 concurrent compaction GC（如早期 CMS Full GC）面临 **read storms**——GC 移动对象时，所有 mutator 读路径都被中断、需要跟着转发指针走。Shenandoah 把转发成本从读路径转移到写路径：

- **正常读路径**（占 90%+）：LRB 退化为恒等 mov，几乎零开销
- **写路径**（占 <10%）：需要 speculation copy，有一定开销

Shipilev 在 SpecJBB2015 基准上的测试：**两小时跑下来，mutator 在疏散写屏障里花的时间总计不到 118 微秒**——可忽略。代价转移成功。

## Updating References（Remap）

疏散完成后，from-region 可以被回收复用。但 **所有指向 from-region 对象的引用还指向旧位置**。

Shenandoah 不做独立的"remap 阶段"——它在下一轮**并发标记期间顺带**完成 remap：

1. Concurrent Marking 线程遍历对象图
2. 每次碰到一个对象引用，先 LRB 解 Brooks pointer（自然 remap 到新位置）
3. 同时如果发现引用仍指向"上一轮 from-region"（对象还没被疏散），直接用 LRB 自愈

把 remap 合进标记让 GC 周期更紧凑，代价是下一轮标记刚开始时，一些引用还指向旧位置——但 LRB 自动处理了。

## Degenerated GC & Full GC

尽管 Shenandoah 的疏散设计精巧，在某些极端情况下仍会退化：

### Degenerated GC

当并发疏散**跟不上 mutator 分配速度**时，堆持续增长。如果堆占用超过某个阈值（通常 92%），Shenandoah 会触发 **Degenerated GC**：

- STW 执行**部分** evacuation（只疏散最紧急的 Region）
- 比 Full GC 轻，但暂停时间比常规并发周期长
- 触发原因：heap 扩容跟不上、CSet 太小、分配速率远超 GC 速度

### Full GC

当 Degenerated GC 也不够时，触发 **Full GC**：

- STW 扫描整个堆 + STW 并行拷贝 + STW 更新所有引用
- 类似其他 GC 的 Full GC，暂停时间随堆大小增长
- Shenandoah 尽可能避免 Full GC，但无法完全消除

## References

1. [Shenandoah Proposal PDF](https://mail.openjdk.org/pipermail/hotspot-gc-dev/attachments/20160513/cde124dd/ShenandoahProposal.pdf) — speculative copy 原始设计
2. [PPPJ 2016: Shenandoah](https://tech-notes.accel.dk/programming/java/java12/docs/CSEN/PPPJ2016.pdf) — CSet 选择与 heuristics
3. [Shipilev: Shenandoah GC September 2017](https://shipilev.net/talks/vmm-Sep2017-shenandoah.pdf) — read storms vs write storms 分析
4. [Shenandoah GC in JDK 13, Part I](https://rkennke.wordpress.com/2019/05/15/shenandoah-gc-in-jdk13-part-i-load-reference-barriers/) — evacuation write barrier
5. [Deep Dive into ZGC](https://dl.acm.org/doi/pdf/10.1145/3538532) — ZGC relocation 可对比

## Links

- [Shenandoah 枢纽页与知识地图](/docs/CS/Java/JDK/JVM/GC/Shenandoah.md)
- [Shenandoah Brooks Pointer（speculative copy 的 CAS 基础）](/docs/CS/Java/JDK/JVM/GC/Shenandoah/BrooksPointer.md)
- [Shenandoah Concurrent Marking（标记完成后选 CSet）](/docs/CS/Java/JDK/JVM/GC/Shenandoah/ConcurrentMarking.md)
- [Shenandoah Barriers（疏散写屏障原理）](/docs/CS/Java/JDK/JVM/GC/Shenandoah/Barriers.md)
- [ZGC Collection Cycle（对比：ZGC relocation 用 self-heal 而非 speculation copy）](/docs/CS/Java/JDK/JVM/GC/ZGC/CollectionCycle.md)
