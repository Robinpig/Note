## Introduction

Just allocate, do not collect garbage.

Epsilon 是**只分配、不回收**的空收集器：它实现了完整的分配路径，但完全不回收垃圾，堆耗尽时直接失败退出。

## 版本基线

> [!NOTE]
> **版本口径**：Epsilon 由 [JEP 318](https://openjdk.org/jeps/318) 引入（Release **11**），JEP 状态为 **Experimental**，启用需要 `-XX:+UnlockExperimentalVMOptions`。它**至今仍在 OpenJDK 主干**（`src/hotspot/share/gc/epsilon/`），未被移除，也未被提升为 product 特性。
>
> 依赖 [JEP 304](https://openjdk.org/jeps/304)（GC Interface，Release 10）——Epsilon 的 BarrierSet 全是 no-op 实现，正是对 GC 接口抽象是否够用的一个证明。
>
> 同一代的可选项：[ZGC](https://openjdk.org/jeps/377) 也在 Release 11 引入，但它是**需要回收**的低延迟收集器，与 Epsilon 方向相反。参见 [GC 总览](/docs/CS/Java/JDK/JVM/JVM.md?id=版本基线)。

## 为什么需要「什么都不做」的收集器

听起来没有实用价值，但它是**差分性能分析**的基准线。跑真实 GC 时，性能损耗里混着多种来源：GC 线程调度、GC 屏障开销、周期恰好在最坏的时刻触发、内存布局变化……Epsilon 把这些**全部消掉**，剩下的就是「代码 + 运行时 + 分配器」的本底开销。

由此可以得到两类实用结论：

1. **测出延迟的本底**（latency baseline）——延迟敏感场景想知道「去掉 GC 因素后能有多快」，用 Epsilon 跑一遍即可。
2. **过滤 GC 引入的伪影**——某个性能异常究竟是 GC 引起的，还是代码本身慢？对比 Epsilon 与真实 GC 的差值即可判断。

## 典型用例

| 场景 | 做法 |
| :-- | :-- |
| **性能测试** | 用 Epsilon 跑基线，剥离 GC 屏障与回收周期的影响，定位真实热点 |
| **内存压力测试** | 配 `-Xmx1g`，让程序在分配超限时**确定性地** OOM 崩溃（可配 `-XX:+HeapDumpOnOutOfMemoryError` 留现场），从而断言「这段逻辑最多分配 1GB」这类不变量 |
| **VM 接口测试** | 验证 VM-GC 接口的最小可用集——Epsilon 是「什么都能不做」的下界 |
| **超短生命周期任务** | 一次性任务退出时堆本来就会被 OS 回收，跑一次 GC 纯属浪费；Epsilon 直接省掉 |

```bash
# 启用（experimental，需解锁）
java -XX:+UnlockExperimentalVMOptions -XX:+UseEpsilonGC -Xmx2g -Xlog:gc -version
```

输出会直接告诉你堆的初始/可扩容量与 TLAB 配置：

```text
[0.006s][info][gc] Initialized with 2009M heap, resizeable to up to 30718M heap with 128M steps
[0.006s][info][gc] Using TLAB allocation; min: 2K, max: 4096K
[0.006s][info][gc] Using Epsilon GC
```

## 关键设计

Epsilon 看起来「什么都不做」，实现上并不简单，它把 GC 该做的事**简化到极限**：

- **线性分配**：在一块连续内存上做指针碰撞（bump pointer）分配，无需空闲链表或空闲表；
- **零屏障**：`BarrierSet` 全部是 no-op 实现。既然不标记、不复制对象图，就完全不需要写屏障/读屏障——这既省掉屏障开销，也顺带证明 GC 接口可以做到零成本；
- **无锁 TLAB**：因为分配是线性的，TLAB 的发放退化为无锁操作，直接复用 VM 已有的 within-TLAB 分配路径；
- **堆按需增长**：分配失败时在 `Heap_lock` 下尝试批量扩容，扩到 `max_capacity()` 还不够就返回 `NULL`（即分配失败）。

> [!WARNING]
> **Epsilon 不做压缩（compaction）**，对象始终保持分配顺序。这意味着**空间局部性取决于你的分配模式**：随机分配或产生大量稀疏垃圾的应用会明显掉吞吐。这是所有非移动 GC 的通病，不是 Epsilon 的 bug。

## 堆耗尽时发生什么

Epsilon 没有回收逻辑，所以失败是**唯一出口**，行为与其它 GC 保持一致：

- 抛出带描述信息的 `OutOfMemoryError`；
- 可通过 `-XX:+HeapDumpOnOutOfMemoryError` 自动 dump 现场；
- 可用 `-XX:OnOutOfMemoryError=...` 触发外部动作（拉起调试器、通知监控系统）。

另外，`System.gc()` 在 Epsilon 下**无事可做**（没有回收代码），实现上可能打印一条警告，提示这次强制回收是徒劳的。

## 源码：分配主路径

入口 `mem_allocate` 只是转发到 `allocate_work`；后者是真正的分配循环——先无锁尝试，失败再加锁重试并尝试扩容：

### mem_allocate

```cpp
HeapWord* EpsilonHeap::mem_allocate(size_t size, bool *gc_overhead_limit_was_exceeded) {
  *gc_overhead_limit_was_exceeded = false;
  return allocate_work(size);
}


HeapWord* EpsilonHeap::allocate_work(size_t size, bool verbose) {
  assert(is_object_aligned(size), "Allocation size should be aligned: " SIZE_FORMAT, size);

  HeapWord* res = NULL;
  while (true) {
    // Try to allocate, assume space is available
    res = _space->par_allocate(size);
    if (res != NULL) {
      break;
    }

    // Allocation failed, attempt expansion, and retry:
    {
      MutexLocker ml(Heap_lock);

      // Try to allocate under the lock, assume another thread was able to expand
      res = _space->par_allocate(size);
      if (res != NULL) {
        break;
      }

      // Expand and loop back if space is available
      size_t space_left = max_capacity() - capacity();
      size_t want_space = MAX2(size, EpsilonMinHeapExpand);

      if (want_space < space_left) {
        // Enough space to expand in bulk:
        bool expand = _virtual_space.expand_by(want_space);
        assert(expand, "Should be able to expand");
      } else if (size < space_left) {
        // No space to expand in bulk, and this allocation is still possible,
        // take all the remaining space:
        bool expand = _virtual_space.expand_by(space_left);
        assert(expand, "Should be able to expand");
      } else {
        // No space left:
        return NULL;
      }

      _space->set_end((HeapWord *) _virtual_space.high());
    }
  }

  size_t used = _space->used();

  // Allocation successful, update counters
  if (verbose) {
    size_t last = _last_counter_update;
    if ((used - last >= _step_counter_update) && Atomic::cmpxchg(&_last_counter_update, last, used) == last) {
      _monitoring_support->update_counters();
    }
  }

  // ...and print the occupancy line, if needed
  if (verbose) {
    size_t last = _last_heap_print;
    if ((used - last >= _step_heap_print) && Atomic::cmpxchg(&_last_heap_print, last, used) == last) {
      print_heap_info(used);
      print_metaspace_info();
    }
  }

  assert(is_object_aligned(res), "Object should be aligned: " PTR_FORMAT, p2i(res));
  return res;
}
```

## Links

- [Garbage Collection](/docs/CS/Java/JDK/JVM/GC/GC.md)
- [CardTable](/docs/CS/Java/JDK/JVM/GC/CardTable.md)
- [ZGC](/docs/CS/Java/JDK/JVM/GC/ZGC.md)

