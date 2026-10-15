## Young Collect

Eden 区满 G1 会根据停顿预测模型计算当前 Eden 区 GC 大概耗时。如果回收时间远小于 `-XX:MaxGCPauseMillis` 则分配空闲分区加入 Eden 区；如果时间接近则触发一次 Young GC。年轻代初始占堆 5% 最多不超过 60%。

GC 并行任务包括根扫描、更新 RSet、对象复制，主要逻辑在 `g1CollectedHeap.cpp` 的 `G1ParTask::work` 中调用。以下完整展开 evacuation 内部机制的调用链。

### Evacuation Call Chain: Object Copy 四步闭环

G1 的 evacuation 本质是 **Cheney 复制算法**——从 CSet 根出发，把存活对象复制到 survivor 或 old gen，并调整所有引用。与 Parallel GC 不同的是，G1 的 evacuation 同时维护 RSet 和更新 SATB 标记状态。

#### 完整调用链

```
并行工作线程启动
  → G1ParTask::work()
  → G1ParEvacuateFollowersClosure::do_void()
  → G1ParScanThreadState::trim_queue_to_threshold()     // 核心循环
      ├── dequeue() 取出待处理的 oop
      ├── G1ParCopyClosure::do_oop_work()              // 步骤 1：判定 + 复制
      │     ├── state.is_in_cset()?  ← 不在 CSet → 跳过
      │     ├── m.is_marked()?       ← 已转发 → decode_pointer()
      │     └── copy_to_survivor_space()               // 步骤 2：真正复制
      │           ├── should_promote? (age ≥ tenuring)
      │           │     └── 分配 old gen region
      │           └── PLAB / Region 分配策略
      ├── oop_store(p, forwardee)                      // 步骤 3：更新引用
      ├── update_rem_set(p, forwardee)                 // 步骤 4：更新 RSet
      └── follow_obj()                                 // 递归处理子引用
            └── 把子引用入队 trim_queue，循环直到队列空
```

#### 步骤 1：判定 + 转发状态检查（`G1ParCopyClosure::do_oop_work`）

这是每次处理一个引用字段 `p` 时的入口。关键逻辑：

```cpp
// src/hotspot/share/gc/g1/g1ParCopyClosure.hpp
void G1ParCopyClosure::do_oop_work(T* p) {
  oop obj = CompressedOops::decode_not_null(RawAccess<>::oop_load(p));

  // 1.1 判定对象是否在 CSet 中
  if (state.is_in_cset()) {
    markWord m = obj->mark();
    if (m.is_marked()) {
      // 1.2a 已转发（mark-word 存了转发指针）
      forwardee = cast_to_oop(m.decode_pointer());
    } else {
      // 1.2b 尚未转发 → 执行真正的复制
      forwardee = _par_scan_state->copy_to_survivor_space(state, obj, m);
    }
    RawAccess<IS_NOT_NULL>::oop_store(p, forwardee);  // 步骤 3：更新引用
  }
}
```

**机制**：G1 用 mark-word 的最低两位编码转发状态——正常对象的 lock 是 `01`（unlocked），转发后改成 `11`（marked），剩余位存转发指针。所以 `m.is_marked()` 实际上是检查 lock bits 是否为 `11`，**常量时间**判断是否已复制。

#### 步骤 2：PLAB 分配与 age promotion（`copy_to_survivor_space`）

这是 evacuation 中最复杂的函数，决定对象搬到哪里、如何避免竞争、以及 age 如何处理：

```
G1ParScanThreadState::copy_to_survivor_space(state, obj, mark)
  │
  ├── should_promote = (obj->age() >= _max_tenuring_threshold)
  │                     || survivor 区空间不足
  │
  ├── 选择分配目标：
  │   should_promote 是 → _old_gen_alloc_region
  │   should_promote 否 → _young_gen_alloc_region（survivor）
  │
  ├── 尝试 PLAB 分配：
  │   plab = _survivor_plab / _old_plab[thread_id]
  │   new_addr = plab.allocate(obj_size)
  │   if (new_addr != NULL) goto copy_done
  │
  ├── PLAB 满了 → 申请新 PLAB：
  │   plab.retire()                 // 旧 PLAB 尾部填 dummy int[]
  │   new_plab = _allocator.new_plab(target_size)
  │   if (new_plab.allocate → goto copy_done
  │
  ├── PLAB 也申请不到 → 直接在 region 中分配：
  │   region = alloc_region()        // 从 free list 取 region
  │   new_addr = region.par_allocate(obj_size)
  │   // par_allocate 用 CAS 竞争 top 指针
  │
  └── copy_done:
      ├── Copy::aligned_disjoint_words(new_addr, obj, obj_size)
      ├── new_obj->set_age(obj->age() + 1)   // age 递增
      │   // 注意：mark-word 的 age 位在轻量级锁/重量级锁状态下
      │   // 被锁指针覆盖，需要特殊恢复：
      │   if (mark.has_monitor()) {
      │     // 从 locker 记录里找 age
      │   }
      ├── new_obj->set_mark(markWord::prototype())
      └── obj->forward_to(new_obj)            // 旧对象 mark-word 存转发指针
```

**PLAB（Parallel Labor Allocation Buffer）机制**：每个 GC worker 线程拥有自己的 PLAB——一个从 survivor region 划出的连续小块。复制对象优先在自己的 PLAB 里做 bump-pointer 分配（**零同步**），只有 PLAB 满了才竞争 region。这避免了多线程 evacuate 时频繁 CAS 同一个 region 的 top 指针。

**Age Promotion（晋升）**：对象每经历一次 Young GC age +1，当 age ≥ `-XX:MaxTenuringThreshold`（默认 15）时晋升到 old gen。另一种晋升触发条件是 survivor region 总空间不足——G1 有一个动态 tenuring 阈值，通过 `_desired_survivor_size` 控制 survivor region 总容量占 young gen 的比例。

**大数组特殊处理**：当数组长度超过 `ParGCArrayScanChunk`（默认 50 个对象引用）时，`trim_queue_to_threshold` 不会把它递归展开，而是整个入队 `_partial_array_queue`。下次循环时用 `do_oop_partial_array` 分块处理——防止递归栈溢出。

#### 步骤 3 & 4：引用更新 + RSet 维护

`G1ParCopyClosure::do_oop_work` 中 `RawAccess<IS_NOT_NULL>::oop_store(p, forwardee)` 把调用者的引用字段从旧地址改到新地址。

然后 `update_rem_set(p, forwardee)` 判断：
- 如果 `p`（引用者）所在 region 不在 young gen → 这是一个 old → old 或 old → young 跨 region 引用
- 调用 `heap_region_rem_set()->add_reference(p)` 把脏 card 加入 RSet 的写入队列

这个 add_reference 不会触发实时扫描——pre-JEP 522 通过 DCQS（DirtyCardQueueSet）队列异步处理，JDK 26+（JEP 522）则直接标脏 primary card table（见 [G1 Barrier: Region Pinning + Dual Card Table](/docs/CS/Java/JDK/JVM/GC/G1/Barrier.md) 与 [G1 RSet Refinement](/docs/CS/Java/JDK/JVM/GC/G1/RSet.md)）。

#### Evacuation Failure 处理

当 G1 找不到足够的空 region 来容纳所有存活对象时（通常发生在分配压力特别大的应用），evacuation failure 发生：

```cpp
G1ParScanThreadState::copy_to_survivor_space(...) {
  new_addr = plab.allocate(obj_size);
  if (new_addr == NULL) {
    new_addr = alloc_region()->par_allocate(...);
    if (new_addr == NULL) {
      // 标记当前 region 为 evacuation_failed
      _region->set_evacuation_failed(true);
      // 让 _par_scan_state 就地处理：不复制，就地调整引用
      return obj;  // 假装复制成功，返回原地址
    }
  }
}
```

evacuation failure region 会被 **就地晋升到 old gen**（年轻代的 evacuation failure 等价于 promotion），下次 Mixed GC 时如果存活度下降了还能再试。如果大部分 young regions 都 evacuation failure，G1 会升级到 Full GC。


```cpp

void G1YoungCollector::collect() {
  // Do timing/tracing/statistics/pre- and post-logging/verification work not
  // directly related to the collection. They should not be accounted for in
  // collection work timing.

  // The G1YoungGCTraceTime message depends on collector state, so must come after
  // determining collector state.
  G1YoungGCTraceTime tm(this, _gc_cause);

  // JFR
  G1YoungGCJFRTracerMark jtm(gc_timer_stw(), gc_tracer_stw(), _gc_cause);
  // JStat/MXBeans
  G1MonitoringScope ms(monitoring_support(),
                       false /* full_gc */,
                       collector_state()->in_mixed_phase() /* all_memory_pools_affected */);
  // Create the heap printer before internal pause timing to have
  // heap information printed as last part of detailed GC log.
  G1HeapPrinterMark hpm(_g1h);
  // Young GC internal pause timing
  G1YoungGCNotifyPauseMark npm(this);

  // Verification may use the workers, so they must be set up before.
  // Individual parallel phases may override this.
  set_young_collection_default_active_worker_threads();

  // Wait for root region scan here to make sure that it is done before any
  // use of the STW workers to maximize cpu use (i.e. all cores are available
  // just to do that).
  wait_for_root_region_scanning();

  G1YoungGCVerifierMark vm(this);
  {
    // Actual collection work starts and is executed (only) in this scope.

    // Young GC internal collection timing. The elapsed time recorded in the
    // policy for the collection deliberately elides verification (and some
    // other trivial setup above).
    policy()->record_young_collection_start();

    calculate_collection_set(jtm.evacuation_info(), _target_pause_time_ms);

    G1RedirtyCardsQueueSet rdcqs(G1BarrierSet::dirty_card_queue_set().allocator());
    G1PreservedMarksSet preserved_marks_set(workers()->active_workers());
    G1ParScanThreadStateSet per_thread_states(_g1h,
                                              &rdcqs,
                                              &preserved_marks_set,
                                              workers()->active_workers(),
                                              collection_set()->young_region_length(),
                                              collection_set()->optional_region_length(),
                                              &_evac_failure_regions);

    pre_evacuate_collection_set(jtm.evacuation_info(), &per_thread_states);

    bool may_do_optional_evacuation = collection_set()->optional_region_length() != 0;
    // Actually do the work...
    evacuate_initial_collection_set(&per_thread_states, may_do_optional_evacuation);

    if (may_do_optional_evacuation) {
      evacuate_optional_collection_set(&per_thread_states);
    }
    post_evacuate_collection_set(jtm.evacuation_info(), &per_thread_states);

    // Refine the type of a concurrent mark operation now that we did the
    // evacuation, eventually aborting it.
    _concurrent_operation_is_full_mark = policy()->concurrent_operation_is_full_mark("Revise IHOP");

    // Need to report the collection pause now since record_collection_pause_end()
    // modifies it to the next state.
    jtm.report_pause_type(collector_state()->young_gc_pause_type(_concurrent_operation_is_full_mark));

    policy()->record_young_collection_end(_concurrent_operation_is_full_mark, evacuation_failed());
  }
  TASKQUEUE_STATS_ONLY(print_taskqueue_stats());
  TASKQUEUE_STATS_ONLY(reset_taskqueue_stats());
}
```

### wait_for_root_region_scanning

```cpp


void G1YoungCollector::wait_for_root_region_scanning() {
  Ticks start = Ticks::now();
  // We have to wait until the CM threads finish scanning the
  // root regions as it's the only way to ensure that all the
  // objects on them have been correctly scanned before we start
  // moving them during the GC.
  bool waited = concurrent_mark()->root_regions()->wait_until_scan_finished();
  Tickspan wait_time;
  if (waited) {
    wait_time = (Ticks::now() - start);
  }
  phase_times()->record_root_region_scan_wait_time(wait_time.seconds() * MILLIUNITS);
}

```

### evacuate_initial_collection_set

```cpp

void G1YoungCollector::evacuate_initial_collection_set(G1ParScanThreadStateSet* per_thread_states,
                                                      bool has_optional_evacuation_work) {
  G1GCPhaseTimes* p = phase_times();

  {
    Ticks start = Ticks::now();
    rem_set()->merge_heap_roots(true /* initial_evacuation */);
    p->record_merge_heap_roots_time((Ticks::now() - start).seconds() * 1000.0);
  }

  Tickspan task_time;
  const uint num_workers = workers()->active_workers();

  Ticks start_processing = Ticks::now();
  {
    G1RootProcessor root_processor(_g1h, num_workers);
    G1EvacuateRegionsTask g1_par_task(_g1h,
                                      per_thread_states,
                                      task_queues(),
                                      &root_processor,
                                      num_workers,
                                      has_optional_evacuation_work);
    task_time = run_task_timed(&g1_par_task);
    // Closing the inner scope will execute the destructor for the
    // G1RootProcessor object. By subtracting the WorkerThreads task from the total
    // time of this scope, we get the "NMethod List Cleanup" time. This list is
    // constructed during "STW two-phase nmethod root processing", see more in
    // nmethod.hpp
  }
  Tickspan total_processing = Ticks::now() - start_processing;

  p->record_initial_evac_time(task_time.seconds() * 1000.0);
  p->record_or_add_nmethod_list_cleanup_time((total_processing - task_time).seconds() * 1000.0);

  rem_set()->complete_evac_phase(has_optional_evacuation_work);
}

```
## Links

- [G1 枢纽页与知识地图](/docs/CS/Java/JDK/JVM/GC/G1.md)
- [G1 RSet（evacuation pause 内的 RSet 扫描）](/docs/CS/Java/JDK/JVM/GC/G1/RSet.md)
- [G1 Mixed GC（相同 evacuate 流程 + should_mark 参数）](/docs/CS/Java/JDK/JVM/GC/G1/MixedGC.md)
- [G1 Concurrent Marking（evacuation 与 marking 并发交互）](/docs/CS/Java/JDK/JVM/GC/G1/ConcurrentMarking.md)
- [G1 Full GC（Full GC 四阶段压缩，非 evacuation）](/docs/CS/Java/JDK/JVM/GC/G1/FullGC.md)

## References

- [G1ParCopyClosure Source (openjdk.org)](https://github.com/openjdk/jdk/blob/master/src/hotspot/share/gc/g1/g1ParCopyClosure.hpp)
