## Region Pinning ([JEP 423](https://openjdk.org/jeps/423))

**Release**: 22 | **Status**: Delivered

### 问题背景

JNI 规范定义了 `GetPrimitiveArrayCritical` / `ReleasePrimitiveArrayCritical` 等函数对——`Get...Critical` 返回 Java 对象数组的直接指针，调用方在 `Release...Critical` 之前"持有"这个指针。这期间如果 GC 把这个数组对象搬走，C 代码持有的指针就会悬空。

pre-JDK-22 的 G1 对此的解决方案是 **在所有 JNI critical 区域期间禁止 GC**：任何触发 GC 的 mutator 线程必须等所有 critical 区域结束才能开始暂停。实际生产中这个方案的问题在于：

- critical 区域阻塞的时间可能很短（微秒级），但 **mutator 线程触发 GC 的时机不可预测**——如果恰好在那几十微秒内，就必须等
- 高并发场景下多个 JNI critical 区域重叠，可能导致 GC 暂停被延迟数分钟，甚至触发 OOM

社区反馈包括 JIRA 因这个问题导致的 [线程饥饿 OOM](https://bugs.openjdk.org/browse/JDK-8192647) 和 [Jira 官方博客](https://confluence.atlassian.com/jirakb/jira-running-out-of-memory-due-to-gc-allocation-race-condition-957122851.html)。

### 实现方案

G1 自诞生以来就有一种隐含的"pinning"机制——humongous regions 和某些 liveness 过高的 region 不会被 evacuation。JEP 423 把这个机制扩展到任意 region：

1. **per-region critical object counter**：每个 HeapRegion 维护一个 `_critical_objects_count`。`GetPrimitiveArrayCritical` 成功后给所在 region **+1**，`ReleasePrimitiveArrayCritical` **-1**。

2. **pin 语义**：`count > 0` 的 region 被视为 **pinned**——GC pause 中会跳过它们。

3. **YGC 中的 pinned region 处理**：YGC 中的 pinned young region **不会被 evacuation**，而是当作 evacuation failure 处理——就地晋升到 old gen（promoted），下次 Mixed GC 时再尝试回收。

4. **Full GC 中的 pinned region 处理**：Full GC 中的 pinned region **不会被 compact**。

```cpp
// src/hotspot/share/gc/g1/heapRegion.hpp
class HeapRegion : public G1ContiguousSpace {
  // JEP 423 新增：critical object 计数
  uint  _critical_objects_count;
  
  void inc_critical_objects_count() { _critical_objects_count++; }
  void dec_critical_objects_count() { _critical_objects_count--; }
  bool is_pinned() const { return _critical_objects_count > 0 || humongous(); }
};

// JNI 入口处调用
oop JNIFastGetPrimitiveArrayCritical(JNIEnv* env, jarray array, jboolean* isCopy) {
  oop o = ...;
  HeapRegion* hr = heap_region_containing(o);
  hr->inc_critical_objects_count();  // pin
  return array_oop_to_array(o);
}
```

### 权衡与风险

| 维度 | 说明 |
| :--- | :--- |
| GC 不再被禁用 | mutator 线程永远不会因 JNI critical 区域而等 GC |
| 可 pin region 粒度 | 只能 pin region，不能 pin 单个对象——一个 region 中只要有一个 critical object，整个 region 都不会被 evacuation |
| young region pinned 后果 | 立即晋升 old gen，可能增加 old gen 占用（但这是临时的，下次 Mixed GC 会处理） |
| 理论风险 | 极端情况下大量 region 同时被 pin，GC 可用空间急剧减少 |

OpenJDK 假设 JNI critical 区域会继续被"短时间、少量使用"——这是 JNI 对它们的设计初衷。Shenandoah GC 也有类似 pinning 机制且运行良好，G1 直接复用了这一假设。

### 与其他收集器的对比

| 收集器 | JNI critical 处理 |
| :--- | :--- |
| Serial / Parallel | 单线程 STW，无 pinning 概念 |
| CMS | 也禁用 GC |
| **G1 (pre-JEP 423)** | **禁用 GC**（与 CMS 同） |
| **G1 (JEP 423+)** | **region pinning** |
| ZGC | 有类似 pinning 机制 |
| Shenandoah | region pinning（G1 JEP 423 前就已实现） |

## Late Barrier Expansion ([JEP 475](https://openjdk.org/jeps/475))

**Release**: 24 | **Status**: Delivered | **Component**: hotspot / compiler

### 问题：C2 的早屏障扩展带来的编译开销

JIT 编译管道（以 C2 为例）通常按以下阶段展开：

```
bytecode → IR → 指令选择 → 寄存器分配 → 代码生成
               ↑  ← 旧模型：G1 写屏障在这里就展开成具体指令
```

pre-JEP 475 的 G1 写屏障扩展发生在 **IR 阶段**——编译器还没有决定使用哪些寄存器、哪些指令序列。这导致：

1. 屏障展开时需要预估额外的寄存器需求，可能导致编译器做出次优的寄存器分配决策
2. 屏障的指令序列在不了解平台细节的情况下生成，某些优化（如延迟分支、指令融合）无法应用
3. HotSpot 开发者如果不深入理解 C2 的 IR 形式，很难改动屏障逻辑

性能影响：初步测试显示 C2 编译时间因此增加了 **~10–20%**，特别是对屏障密集的代码（如大型缓存、序列化）。

### 解决方案：在代码生成阶段插入屏障指令

JEP 475 把 G1 写屏障的展开推迟到 **指令选择 + 寄存器分配之后、代码生成之前**——此时编译器已经决定了具体使用哪些寄存器和指令序列：

```
bytecode → IR → 指令选择 → 寄存器分配 → 代码生成
                                        ↑  ← 新模型：屏障在这里插入具体机器指令
```

具体实现上，JEP 475 在 C2 的代码生成器（`CodeGenerator`）中为 G1 加了平台特定的 barrier 插入点：

```cpp
// src/hotspot/share/opto/codeGenerator.cpp（简化）
void CodeGenerator::generate_memory_access(MachNode* node) {
  // 1. 正常生成 store 指令
  emit_store(node);
  
  // 2. 检查这个 store 是否需要屏障
  if (node->needs_g1_barrier()) {
    // 3. 在 store 指令之后，直接插入平台特定的屏障代码
    //    此时已知哪些寄存器被占用，可以做最优的指令选择
    emit_g1_barrier(node);
  }
}
```

### 收益

| 收益 | 细节 |
| :--- | :--- |
| C2 编译时间降低 | **~10–20%**（取决于应用中引用写操作的密度） |
| 屏障指令更高效 | 可利用寄存器分配信息做最优指令选择，在 x64 上平均减少 30% 指令数 |
| 屏障实现简化 | 把 G1 屏障的"是什么"（逻辑）和"怎么生成"（机器码）解耦 |

### 与 JEP 522 的关系

JEP 475 和 JEP 522 是**互补关系**：

- JEP 475（JDK 24）改变的是**屏障在哪里展开**（编译器管道的阶段）
- JEP 522（JDK 26）改变的是**屏障本身做什么**（双卡表取代单卡表 + DCQS）

两者叠加后，G1 写屏障在 JDK 27 中的最终形态是：**极简逻辑（~12 指令的标脏 + 过滤）** + **最优机器码生成（寄存器分配后插入）**，达到了"小而快"的极致。

## Barrier

分代式垃圾回收器需要跟踪从老年代到年轻代的引用，这样才能在不检查老年代中每个对象的情况下回收年轻代。
潜在包含指向较新对象指针的位置集合通常称为*记忆集*（remembered set）。
在每次存储操作时，系统必须确保如果该存储创建了从较老对象到较新对象的引用，则将更新的位置添加到记忆集中。
此机制通常称为*写屏障*（write barrier）或*存储检查*（store check）。

对于某些存储操作，编译器可以静态确定不需要存储检查，例如存储整数时（假设整数以立即数实现，而不是实际的堆分配对象）。
但在一般情况下，每次存储操作都必须执行存储检查。
由于在非函数式语言中存储操作相当频繁，高效的写屏障实现至关重要。
这里描述的写屏障实现将 mutator 中的写屏障开销降低到每次被检查的存储操作仅额外两条指令。

### Card Marking

我们的新写屏障实现基于 Wilson 的 card marking 方案。
在此方案中，堆被划分为大小为 $2^k$ words 的 card（通常 k = 5..7），每个 card 在独立的位向量中有一个关联的位。
存储检查只需标记与正在更新的位置对应的位。
垃圾回收时，收集器扫描位向量，每当发现标记的位时，就检查堆中对应 card 内的所有指针。

不幸的是，刚才描述的 card marking 可能相当慢。
由于必须将位插入位向量，因此需要从内存中读取对应的字，更新后写回。
此外，位操作通常需要 RISC 处理器上的多条指令。
Chambers 和 Ungar 通过使用字节代替位来标记 card，改进了 Wilson 的方案。
也就是说，堆中每个 card 关联一个字节；标记 card 只需向对应字节存储一个特殊值（例如零）。
虽然此方案使用了八倍的内存，但空间开销通常仍然很小；例如，card 大小为 32 words = 128 bytes 时，字节映射的空间不到堆大小的 1%。

字节标记方案的最大优点是其速度。
存储检查在实际存储之外仅需 3 条 SPARC 指令。

### Write Barrier

我们的新写屏障通过放宽 card marking 方案维护的不变量，改进了标准的 card marking。
标准 card marking 维护的不变量是

> 位或字节 i 被标记 <--> card i 可能包含从老年代到年轻代的指针

我们方案的放宽不变量是

> 位或字节 i 被标记 <--> card i..i+l 可能包含从老年代到年轻代的指针，其中 l 是一个小常量（当前实现中为 1）

本质上，l 给存储检查在选择标记哪个字节时提供了一些灵活性——被标记的字节可能距离"正确"字节最多 l 个字节（向较低地址方向）。
放宽的不变量使我们可以省略计算更新字的确切地址：只要更新字的偏移量（即它与对象开头的距离）小于 $l*2^k$，
我们就可以标记对象地址对应的字节，而不是更新字段对应的字节。
因此，常见情况下的存储检查仅需两条指令。

扫描 card 时，垃圾回收器只需确保 card 中的最后一个对象被完整扫描，即使它只有一部分属于该 card。
换句话说，收集器继续扫描 card 最后一个字之后的内容，直到遇到下一个对象头。
但对于非常大的对象，此方案可能导致较高的扫描成本，因为扫描量不再受固定最大灵活性限制，而仅受最后一个对象的大小限制。
幸运的是，通过对数组的存储标记确切的 card，可以缓解此问题；这样，如果 card 中开始的最后一个对象是数组，收集器就不需要继续扫描到下一个 card。
## Links

- [G1 枢纽页与知识地图](/docs/CS/Java/JDK/JVM/GC/G1.md)
- [G1 Concurrent Marking（写屏障驱动的 SATB）](/docs/CS/Java/JDK/JVM/GC/G1/ConcurrentMarking.md)
- [G1 RSet（双卡表 Refinement）](/docs/CS/Java/JDK/JVM/GC/G1/RSet.md)
- [CardTable](/docs/CS/Java/JDK/JVM/GC/CardTable.md)

## References

- [JEP 423: Region Pinning for G1](https://openjdk.org/jeps/423)
- [JEP 475: Late Barrier Expansion for G1](https://openjdk.org/jeps/475)
- [JEP 522: Dual Card Table for G1](https://openjdk.org/jeps/522)
