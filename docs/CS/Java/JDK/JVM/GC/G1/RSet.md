## RSet Refinement: Concurrent Card Scanning

G1 的写屏障只做"标脏 card"——把引用发生的 card 加入 DirtyCardQueue，**不会立即扫描这个 card 里到底有哪些对象**。这些脏 card 被延迟处理，处理过程就是 **RSet refinement**。refinement 与 mutator 并发运行，由 `ConcurrentRefineThread` 驱动。

> [!NOTE]
> JEP 522 改变了 refinement 的工作方式。pre-JDK-26 用 DirtyCardQueueSet（DCQS）模式，写屏障 enqueue → refinement thread dequeue；JDK 26+ 的 dual card table 下，写屏障直接标脏 primary table，refinement 只需要扫描脏 card 列表。下文主要讲 **pre-JDK-26 的 DCQS 机制**——因为这是 G1 十年来的主力实现，原理在 dual table 下仍然成立。

### RSet 三级粒度：Coarse → Medium → Fine

RSet 不是单一结构，而是一个 **渐进式精确** 的三层存储。从粗到细，扫描成本递增但精确性也递增：

| 层级 | 数据结构 | 粒度 | 扫描成本 | 何时产生 |
| :--- | :--- | :--- | :--- | :--- |
| **Coarse** | per-region `_coarse_map` (bitmap) | 整个 region | 极高（整个 region 都要扫） | RSet 刚建立时默认 coarse；region 首次被引用 |
| **Medium** | per-region `_card_table` (bitmap, 512B 粒度) | 512B card | 中等 | refinement 扫描了 coarse region，标记了 card bitmap |
| **Fine** | per-region `_par_cards` + `_fine_region` list | 精确的对象引用地址 | 低 | medium 扫描后发现 card 内引用很少，值得精确记录 |

**refinement 的核心工作就是"把 coarse 变成 medium，把 medium 变成 fine"**。GC 时扫描 RSet 的顺序反过来：先扫 fine（最精确），再扫 medium，最后 coarse。每扫完一层，能跳过的范围就更大。

### ConcurrentRefineThread 调度模型

RSet refinement 由一个主线程 + N 个 worker 线程组成：

```
ConcurrentRefineThread
  │
  ├── _primary_thread (单线程)
  │     └── run() 循环：
  │           while (true) {
  │             wait_until_queue_over_threshold();
  │             drain_queue_until_empty_or_budget();
  │             update_periodic_logging();
  │           }
  │
  └── _secondary_threads[] (N worker 线程，G1ConcRefinementThreads)
        └── run() 循环：
              while (true) {
                wait_until_primary_signals_work();
                drain_queue_segment();
              }
```

关键参数：

| 选项 | 默认值 | 作用 |
| :--- | :--- | :--- |
| `-XX:G1ConcRefinementThreads` | 0（自动 = min(8, 并行GC线程数)） | refine worker 数 |
| `-XX:G1RefinementBudgetMs` | 10ms | 每次 refinement 循环的时间预算 |
| `-XX:G1DirtyCardQueueSizeThreshold` | 128 | DCQS 积压超过此阈值触发 refine |
| `-XX:G1MaxRefineQueueSize` | 256 × 并发 refinement 阈值 | 超过时 primary thread 也处理 |

### Refinement 主循环：CardQueue 消费 + RSet 更新

`ConcurrentRefineThread::run` 的核心循环：

```cpp
// src/hotspot/share/gc/g1/concurrentRefineThread.cpp
void ConcurrentRefineThread::run() {
  while (true) {
    // 1. 等待脏队列积压到一定程度
    _monitor.wait_for_completion();

    // 2. 从 DCQS 取出 completed buffer
    void* card_index = _dcqs.get_card();
    while (card_index != NULL) {
      CardIdx_t card = (CardIdx_t)(uintptr_t)card_index;
      
      // 3. 定位这个 card 属于哪个 region
      HeapRegion* hr = _g1h->heap_region_containing(card_to_addr(card));
      if (hr == NULL) continue;
      
      // 4. 定位引用者（card 里的老对象）和被引用者（card 外的对象）
      //    refinement 要把被引用者所在 region 加入 hr 的 RSet
      
      // 5. 扫描 card：找 card 内所有包含跨 region 引用的对象
      MemRegion card_mem = card->area();
      hr->rem_set()->update_references(card_mem);
      
      // 6. RSet 层级升级：从 coarse → medium → fine
      //    update_references 内部：
      //      a. 如果 RSet 还是 coarse bitmap → 先降级到 medium（card bitmap）
      //      b. 然后扫描 card，找到具体引用地址 → 加入 medium bitmap
      //      c. 如果 medium 中引用数很少 → 进一步降到 fine（精确地址 list）
      
      // 7. 检查时间预算
      if (elapsed > budget_ms) break;
      
      // 8. 取下一个 card
      card_index = _dcqs.get_card();
    }
    
    // 9. 通知 secondary thread 继续
    _secondary_monitor.notify_all();
  }
}
```

**RSet 层级升级的具体逻辑**（`HeapRegionRemSet::update_references`）：

```
update_references(card_mem)
  │
  ├── 检查 RSet 当前层级：
  │   current_level = hr->rem_set()->get_level()  // coarse / medium / fine
  │
  ├── 如果是 coarse：
  │   → 创建 medium card bitmap（全 1，表示"所有 card 都可能有引用"）
  │   → 立即降级到 medium
  │
  ├── 如果是 medium：
  │   → 扫描 card_mem 内所有对象
  │   → 对每个对象的每个引用字段：
  │       if (ref->region() != hr)  // 跨 region
  │         medium_map.mark(card_of(ref))  // 标记 medium bitmap
  │
  └── 如果是 fine：
      → 直接把 ref 地址加入 fine_region 的精确引用 list
```

### JEP 522 对 Refinement 的影响

JDK 26+（dual card table）下 refinement 的工作方式简化了：

| 方面 | pre-JDK-26 | JDK 26+ |
| :--- | :--- | :--- |
| 写屏障 | `enqueue(card)` 到 DCQS，缓冲区满了才进全局队列 | 直接标脏 primary table，原子可见 |
| Refinement 触发 | DCQS 积压到阈值才启动 thread | 定期扫描 primary table 找脏 card |
| 同步成本 | DCQS 需要 CAS 完成 buffer 队列 | 全局原子指针 `_primary` 无锁读 |
| Memory overhead | DCQS buffer ≈ 2×card size × CPU cores | dual table = 2 × ~0.2% heap |

dual table 的 refinement thread **不再需要处理 queue 积压问题**——直接遍历 `_primary` 的 dirty bits 即可。这是因为 primary table 是全局原子可见的，refinement thread 和 mutator 写屏障之间没有生产者-消费者关系，而是共享同一个 dirty 标记。

### Refinement 暂停的保护机制

refinement 不能无限并发消耗 CPU，G1 有三道保护：

1. **时间预算**：每次循环 `G1RefinementBudgetMs`（默认 10ms），到点就 yield 给 mutator。如果 mutator 分配压力大，refinement 暂停可以延长。

2. **分配阈值**：当 young gen 总分配速度超过 `G1RefinementTopPriorityRatio`（默认 1.5）× 预测回收速度时，refinement 完全让步。

3. **GC 内 refinement**：如果 refinement 跟不上，**evacuation pause 内会同步处理 RSet**（`G1ParTask::work` 中的 `update_rem_set`）。这会增加 pause time 但保证 correctness。

### 监控与调优

```bash
# 用 G1PrintRefinementStats 观察 refinement 效率
java -XX:+UnlockDiagnosticVMOptions -XX:+G1PrintRefinementStats -jar app.jar

# 关键日志字段：
# - Concurrent refinement thread time spent
# - RSet level distribution（多少 coarse / medium / fine）
# - Cards processed per refinement iteration
```

常用调优：

```
G1ConcRefinementThreads=4     # 固定 refine worker 数
G1RefinementBudgetMs=20       # 放宽 refinement 时间预算 → 更及时的 RSet 更新
G1DirtyCardQueueSizeThreshold=256  # 积压更久才触发 → 写屏障 overhead 更低
```

## G1CollectedHeap

```c

class G1CollectedHeap : public CollectedHeap {
  
  G1CollectorPolicy* _collector_policy;
  G1CardTable* _card_table;

  SoftRefPolicy      _soft_ref_policy;

  // These sets keep track of old, archive and humongous regions respectively.
  HeapRegionSet _old_set;
  HeapRegionSet _archive_set;
  HeapRegionSet _humongous_set;

  // The sequence of all heap regions in the heap.
  HeapRegionManager* _hrm;

  // Manages all allocations with regions except humongous object allocations.
  G1Allocator* _allocator;

  // The young region list.
  G1EdenRegions _eden;
  G1SurvivorRegions _survivor;

  // The current policy object for the collector.
  G1Policy* _g1_policy;
  G1HeapSizingPolicy* _heap_sizing_policy;

  G1CollectionSet _collection_set;
}
```

#### HeapRegionManager

```cpp

HeapRegionManager* HeapRegionManager::create_manager(G1CollectedHeap* heap, G1CollectorPolicy* policy) {
  if (policy->is_hetero_heap()) {
    return new HeterogeneousHeapRegionManager((uint)(policy->max_heap_byte_size() / HeapRegion::GrainBytes) /*heap size as num of regions*/);
  }
  return new HeapRegionManager();
}
```

G1HeapRegionTable

```cpp
class HeapRegionManager: public CHeapObj<mtGC> {
G1HeapRegionTable _regions;
G1RegionToSpaceMapper* _heap_mapper;
G1RegionToSpaceMapper* _prev_bitmap_mapper;
G1RegionToSpaceMapper* _next_bitmap_mapper;
FreeRegionList _free_list;
}
```

```cpp

class G1HeapRegionTable : public G1BiasedMappedArray<HeapRegion*> {
 protected:
  virtual HeapRegion* default_value() const { return NULL; }
};

```


G1MonitoringSupport 用于监控 G1 中的逻辑空间。
它为 G1 的 jstat 计数器以及 G1 的内存池提供数据。


G1将堆划分为堆区域，每个堆区域属于以下类别之一
* eden      : 自上次 GC 以来分配的 region
* survivors : 包含在上几次 GC 中存活下来对象的 region
* old       : 长期存活的非大对象 region
* humongous : 大对象 region
* free      : 空闲 region

#### HeapRegion

```cpp
class HeapRegion: public G1ContiguousSpace {
  private:
  // The remembered set for this region.
  // (Might want to make this "inline" later, to avoid some alloc failure
  // issues.)
  HeapRegionRemSet* _rem_set;

  protected:
  // The index of this region in the heap region sequence.
  uint  _hrm_index;

  HeapRegionType _type;

  // For a humongous region, region in which it starts.
  HeapRegion* _humongous_start_region;

  // True iff an attempt to evacuate an object in the region failed.
  bool _evacuation_failed;

  // Fields used by the HeapRegionSetBase class and subclasses.
  HeapRegion* _next;
  HeapRegion* _prev;
  
  // The index in the optional regions array, if this region
  // is considered optional during a mixed collections.
  uint _index_in_opt_cset;
  int  _young_index_in_cset;
  SurvRateGroup* _surv_rate_group;
  int  _age_index;
}
```

#### mem_allocate

当TLAB分配失败时，进入慢速分配阶段。慢速分配首先需要尝试对Heap加锁，加锁成功后在TLAB外的YHR或HHR分配

如果需要gc，则触发gc，gc成功后，回到加锁逻辑，重新开始分配直到成功，或者gc重试次数大于GCLockerRetryAllocationCount

G1ContiguousSpace::par_allocate_impl
使用CAS操作分配，如果可用空间大于对象容量则持续重试，否则退出重新选择HR或触发GC


```c
// share/gc/g1/g1CollectedHeap.cpp
HeapWord* G1CollectedHeap::mem_allocate(size_t word_size,
                              bool*  gc_overhead_limit_was_exceeded) {
  assert_heap_not_locked_and_not_at_safepoint();

  if (is_humongous(word_size)) {
    return attempt_allocation_humongous(word_size);
  }
  size_t dummy = 0;
  return attempt_allocation(word_size, word_size, &dummy);
}
```

```cpp
class G1Allocator : public CHeapObj<mtGC> {

}
```

## Root Scanning

```cpp

void G1RootProcessor::process_all_roots(OopClosure* oops,
                                        CLDClosure* clds,
                                        CodeBlobClosure* blobs) {
  AllRootsClosures closures(oops, clds);

  process_java_roots(&closures, NULL, 0);
  process_vm_roots(&closures, NULL, 0);

  process_code_cache_roots(blobs, NULL, 0);

  // refProcessor is not needed since we are inside a safe point
  _process_strong_tasks.all_tasks_claimed(G1RP_PS_refProcessor_oops_do);
}
```

### process_java_roots

```cpp

void G1RootProcessor::process_java_roots(G1RootClosures* closures,
                                         G1GCPhaseTimes* phase_times,
                                         uint worker_i) {
  // Iterating over the CLDG and the Threads are done early to allow us to
  // first process the strong CLDs and nmethods and then, after a barrier,
  // let the thread process the weak CLDs and nmethods.
  {
    G1GCParPhaseTimesTracker x(phase_times, G1GCPhaseTimes::CLDGRoots, worker_i);
    if (_process_strong_tasks.try_claim_task(G1RP_PS_ClassLoaderDataGraph_oops_do)) {
      ClassLoaderDataGraph::roots_cld_do(closures->strong_clds(), closures->weak_clds());
    }
  }

  {
    G1GCParPhaseTimesTracker x(phase_times, G1GCPhaseTimes::ThreadRoots, worker_i);
    bool is_par = n_workers() > 1;
```

`Threads::possibly_parallel_oops_do`

```
    Threads::possibly_parallel_oops_do(is_par,
                                       closures->strong_oops(),
                                       closures->strong_codeblobs());
  }
}
```

process_vm_roots

```cpp
void G1RootProcessor::process_vm_roots(G1RootClosures* closures,
                                       G1GCPhaseTimes* phase_times,
                                       uint worker_i) {
  OopClosure* strong_roots = closures->strong_oops();

  {
    G1GCParPhaseTimesTracker x(phase_times, G1GCPhaseTimes::UniverseRoots, worker_i);
    if (_process_strong_tasks.try_claim_task(G1RP_PS_Universe_oops_do)) {
      Universe::oops_do(strong_roots);
    }
  }

  {
    G1GCParPhaseTimesTracker x(phase_times, G1GCPhaseTimes::JNIRoots, worker_i);
    if (_process_strong_tasks.try_claim_task(G1RP_PS_JNIHandles_oops_do)) {
      JNIHandles::oops_do(strong_roots);
    }
  }

  {
    G1GCParPhaseTimesTracker x(phase_times, G1GCPhaseTimes::ObjectSynchronizerRoots, worker_i);
    if (_process_strong_tasks.try_claim_task(G1RP_PS_ObjectSynchronizer_oops_do)) {
      ObjectSynchronizer::oops_do(strong_roots);
    }
  }

  {
    G1GCParPhaseTimesTracker x(phase_times, G1GCPhaseTimes::ManagementRoots, worker_i);
    if (_process_strong_tasks.try_claim_task(G1RP_PS_Management_oops_do)) {
      Management::oops_do(strong_roots);
    }
  }

  {
    G1GCParPhaseTimesTracker x(phase_times, G1GCPhaseTimes::JVMTIRoots, worker_i);
    if (_process_strong_tasks.try_claim_task(G1RP_PS_jvmti_oops_do)) {
      JvmtiExport::oops_do(strong_roots);
    }
  }

#if INCLUDE_AOT
  if (UseAOT) {
    G1GCParPhaseTimesTracker x(phase_times, G1GCPhase
```

## Collection Phases

G1 的外层 GC 分发逻辑在 `G1CollectedHeap::try_collect()`。它根据 `GCCause` 决定走哪条路：

```
try_collect(cause)
  │
  ├── should_do_concurrent_full_gc(cause) → try_collect_concurrently()  // 并发 Full GC（兜底）
  ├── GCLocker::should_discard(cause) → return false                     // 被锁竞争丢弃
  ├── _gc_locker / _wb_young_gc → VM_G1CollectForAllocation              // 标准 Evacuation Pause（Young/Mixed）
  └── else → VM_G1CollectFull                                            // 串行 Full GC
```

`should_do_concurrent_full_gc()` 在分配失败时判断是否启动并发 Full GC（不是 evacuation pause 里的 Young GC，而是**全堆并发 mark → compact** 的完整周期）。

```cpp
// share/gc/g1/g1CollectedHeap.cpp
void G1CollectedHeap::collect(GCCause::Cause cause) {
  try_collect(cause, collection_counters(this));
}

bool G1CollectedHeap::try_collect(GCCause::Cause cause,
                                  const G1GCCounters& counters_before) {
  if (should_do_concurrent_full_gc(cause)) {
    return try_collect_concurrently(cause,
                                    counters_before.total_collections(),
                                    counters_before.old_marking_cycles_started());
  } else if (GCLocker::should_discard(cause, counters_before.total_collections())) {
    return false;
  } else if (cause == GCCause::_gc_locker || cause == GCCause::_wb_young_gc
             DEBUG_ONLY(|| cause == GCCause::_scavenge_alot)) {
    VM_G1CollectForAllocation op(0, counters_before.total_collections(),
                                 cause, policy()->max_pause_time_ms());
    VMThread::execute(&op);
    return op.gc_succeeded();
  } else {
    VM_G1CollectFull op(counters_before.total_collections(),
                        counters_before.total_full_collections(),
                        cause);
    VMThread::execute(&op);
    return op.gc_succeeded();
  }
}
```
## Links

- [G1 枢纽页与知识地图](/docs/CS/Java/JDK/JVM/GC/G1.md)
- [G1 Barrier（双卡表 JEP 522）](/docs/CS/Java/JDK/JVM/GC/G1/Barrier.md)
- [G1 Evacuation（evacuation pause 内的 RSet 扫描）](/docs/CS/Java/JDK/JVM/GC/G1/Evacuation.md)
- [CardTable](/docs/CS/Java/JDK/JVM/GC/CardTable.md)

## References

- [HotSpot G1CardSet Source (openjdk.org)](https://github.com/openjdk/jdk/tree/master/src/hotspot/share/gc/g1)
