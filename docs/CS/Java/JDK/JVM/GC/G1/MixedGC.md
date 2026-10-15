## Mixed GC: Old Gen Incremental Reclamation

G1 的标志性特性。**Young GC 只回收 young regions，Mixed GC 则在回收 young regions 的同时，选择性地回收部分 old gen regions**——把存活对象疏散到其他 free regions，然后把空出来的 old regions 放还 free list。这就是 G1 "Garbage-First" 名字的由来：**优先回收垃圾最多的 regions**。

Mixed GC 本身不是一个新的 GC 类型，而是 **Young GC 的超集**：执行流程几乎一样（根扫描 → RSet 更新 → evacuation → 对象晋升），唯一的区别是 **CSet（Collection Set）里多了 old gen regions**。

### Mixed GC 的触发时机

Mixed GC 触发需要**两个前置条件**，按顺序满足：

```
条件 1：并发标记周期完成
  → Initial Mark → Concurrent Mark → Remark → Cleanup 全部跑完
  → Cleanup 阶段选择了哪些 old regions 是候选（G1MixedGCLiveThresholdPercent）
  → 设置 collector_state = MixedPhase
  → 所有后续的 Young GC 都会自动变成 Mixed GC

条件 2：Heap 可回收空间足够
  → G1Policy::next_gc_should_be_mixed() 检查：
    reclaimable_bytes = sum(candidate_old_regions)
    if (reclaimable_bytes / heap_capacity >= G1HeapWastePercent)
      → 执行 Mixed GC
    else
      → 继续纯 Young GC（说明 old gen 垃圾太少，回收收益不划算）
```

关键参数：

| 选项 | 默认值 | 作用 |
| :--- | :--- | :--- |
| `-XX:G1MixedGCLiveThresholdPercent` | 85 | old region 存活对象占比 < 此值才纳入 CSet 候选（越低越积极回收） |
| `-XX:G1OldCSetRegionThresholdPercent` | 10 | 单次 Mixed GC 最多纳入的 old regions 数占 heap 总 region 数的 % |
| `-XX:G1HeapWastePercent` | 5 | old gen 可回收空间占比必须 ≥ 此值才启动 Mixed GC |
| `-XX:G1MixedGCCountTarget` | 8 | 一次标记周期预计的 Mixed GC 次数（影响每次 CSet 大小） |
| `-XX:G1MixedGCLiveThresholdPercent` | 85 | 单个 region 存活对象占比 < 此阈值才回收 |

### CSet 候选选择算法

并发标记 Cleanup 阶段（`G1Policy::record_concurrent_mark_cleanup_end`）完成后，G1 为每个 old region 记录了**存活字节数**（`G1HeapRegion::live_bytes()`）。候选选择就是从所有 old regions 中挑出存活对象最少的：

```cpp
// src/hotspot/share/gc/g1/g1Policy.cpp（简化）
void G1Policy::record_concurrent_mark_cleanup_end() {
  // 1. 筛选候选
  _candidate_old_cset_length = 0;
  for (HeapRegion* hr : old_regions) {
    size_t live_pct = hr->live_bytes() * 100 / hr->used();
    if (live_pct < G1MixedGCLiveThresholdPercent) {
      // 存活对象占比低于阈值 → 候选
      _free_candidate_old_regions.push_back(hr);
      _candidate_old_cset_length++;
    }
  }
  
  // 2. 按存活字节数升序排序（最垃圾的排最前）
  sort_by_live_bytes_asc(_free_candidate_old_regions);
}
```

然后**每次 Mixed GC 从候选池里取前 N 个**加入 CSet：

```cpp
// 每次 Mixed GC 开始时
void G1Policy::choose_initial_cset_max_length() {
  // next_collection_size() 在 Pause-Time Prediction 章节展开过
  // 它返回当前停顿预算下能容纳的 CSet 总字节数
  size_t max_cset_bytes = next_collection_size();
  size_t cset_bytes = 0;
  
  // 先加 young regions（必须全加）
  cset_bytes += _eden_used + _survivor_used;
  
  // 从候选池里按存活少→多 依次加 old regions
  while (!_free_candidate_old_regions.empty() 
         && cset_bytes < max_cset_bytes) {
    HeapRegion* hr = _free_candidate_old_regions.front();
    cset_bytes += hr->used();
    _collection_set.add(hr);
    _free_candidate_old_regions.pop_front();
  }
  
  // 达到 G1OldCSetRegionThresholdPercent 的 region 数上限也停止
}
```

**关键点**：候选池一次标记周期只建一个，后续每次 Mixed GC 从池里消费（取完了就只能等下个标记周期）。这就是为什么一个标记周期内会有多次 Mixed GC——**分段回收 old gen**，每次只取一部分候选。

### Mixed GC 的 Evacuation 与 Young GC 的区别

Evacuation 逻辑完全复用 Young GC 的 `G1ParTask::work` → `trim_queue_to_threshold` → `copy_to_survivor_space` 调用链，只有三个差异：

**差异 1：CSet 里有 old regions**

```
Young GC CSet = { all eden regions, all survivor regions }
Mixed GC CSet = { all eden regions, all survivor regions, + N candidate old regions }
```

Evacuation 把 CSet 里所有 region 的存活对象搬到 free regions，不管是 young 还是 old。

**差异 2：晋升目标不同**

Young GC 里，存活对象要么留在 survivor（age < MaxTenuringThreshold），要么晋升到 old gen。Mixed GC 里：

```
eden survivor → 存活 → survivor（age+1）→ 老 survivor 晋升 old
candidate old → 存活 → 新 old region（疏散，age 不变）
```

**注意**：从 candidate old gen 疏散出来的对象是**重新分配到新的 old region**，不是直接原地搬。新 old region 的 top/prev_top/next_tams 都从零开始，旧 candidate region 清空后释放回 free list。

**差异 3：Evacuation 期间维护 Marking Bitmap**

如果 Mixed GC 触发时并发标记还没完全结束（yields 给 evacuation pause），evacuation 时需要正确处理正在被标记的对象。这就是 `G1ParCopyClosure::do_oop_work` 中 `should_mark` 参数的意义——下面的代码块展示了完整的带 marking 交互的 closure。

### Evacuation 与 Marking 的并发交互（Mixed GC 特有）

在 evacuation pause 开始前，标记线程会先 `yield`（`G1ConcurrentMark::do_yield_check`）。evacuation pause 中，GC worker 需要：

1. **先 join 标记的 terminator**：让所有标记 worker 暂停在 yield point
2. **标记栈（mark stack）作为额外的 GC Root**：如果 evacuation 时 mark stack 里还有对象（标记还没结束但被 pause 中断了），这些对象也要参与 evacuation
3. **Evacuation 后更新 TAMS**：evacuation 搬迁对象到新 region，`top` 变化后需要同步到 `next_tams`

Evacuation pause 结束后，标记线程恢复，基于新的堆位置继续标记。

### Mixed GC 中的 G1ParCopyClosure（带 should_mark 参数）

下面是 Mixed GC evacuation 时实际运行的 closure——与 Young GC 的 closure 唯一区别是 `should_mark` 分支：

```cpp
// src/hotspot/share/gc/g1/g1ParCopyClosure.hpp
// should_mark = true 时表示当前 closure 同时是标记工作的一部分
// （通常是 Initial Mark pause 或者 Mixed GC evacuation 中）
void G1ParCopyClosure<barrier, should_mark>::do_oop_work(T* p) {
  T heap_oop = RawAccess<>::oop_load(p);
  if (CompressedOops::is_null(heap_oop)) return;

  oop obj = CompressedOops::decode_not_null(heap_oop);
  const G1HeapRegionAttr state = _g1h->region_attr(obj);

  if (state.is_in_cset()) {
    // 在 CSet 里 → 需要 evacuation（与 Young GC 逻辑相同）
    oop forwardee;
    markWord m = obj->mark();
    if (m.is_marked()) {
      forwardee = cast_to_oop(m.decode_pointer());
    } else {
      forwardee = _par_scan_state->copy_to_survivor_space(state, obj, m);
    }
    RawAccess<IS_NOT_NULL>::oop_store(p, forwardee);
  } else {
    // 不在 CSet 里 → 不复制，但可能需要标记
    if (state.is_humongous()) {
      _g1h->set_humongous_is_live(obj);
    }
    // should_mark = true 时（Initial Mark pause）：
    // 这个 closure 同时是标记工作，把遇到的对象加到标记 bitmap
    if (should_mark) {
      mark_object(obj);
    }
  }
}
```

### need_to_start_conc_mark：IHOP 判定入口

何时启动下一次并发标记由 `G1Policy::need_to_start_conc_mark` 决定。它在**每次分配请求**（eden region 或 humongous 对象分配）时被调用：

```cpp
// src/hotspot/share/gc/g1/g1Policy.cpp
bool G1Policy::need_to_start_conc_mark(const char* source,
                                        size_t alloc_word_size) {
  // 已经在 Mixed phase 中就不需要了（标记周期应该已经在跑）
  if (about_to_start_mixed_phase()) {
    return false;
  }

  // IHOP threshold（可能是静态 IHOP=45%，也可能是 adaptive 自适应值）
  size_t threshold = _ihop_control->get_conc_mark_start_threshold();

  size_t cur_used = _g1h->non_young_capacity_bytes();
  size_t alloc_bytes = alloc_word_size * HeapWordSize;
  size_t after_alloc = cur_used + alloc_bytes;

  bool should_start = after_alloc > threshold
                      && collector_state()->in_young_only_phase();

  log_debug(gc, ergo, ihop)
    ("%s occupancy: " SIZE_FORMAT "B threshold: " SIZE_FORMAT "B (%1.2f%%)",
     should_start ? "Request concurrent cycle" : "Skip",
     after_alloc, threshold,
     (double) threshold / _g1h->capacity() * 100);

  return should_start;
}
```

**adaptive IHOP** 的更新发生在每次并发标记周期结束后。`G1AdaptiveIHOPControl` 根据上次标记的实际时间 + 同时期的分配率，计算下次启动阈值。公式见 [Pause-Time Prediction](/docs/CS/Java/JDK/JVM/GC/G1/Predictions.md)。

### G1ConcurrentMarkThread 的生命周期

```cpp
// src/hotspot/share/gc/g1/g1ConcurrentMarkThread.cpp
void G1ConcurrentMarkThread::run_service() {
  while (wait_for_next_cycle()) {
    concurrent_cycle_start();
    
    if (_state == FullMark) {
      concurrent_mark_cycle_do();   // 标准 Full Mark
    } else {
      concurrent_undo_cycle_do();   // 可选的 Undo Mark（用于类卸载优化）
    }
    
    concurrent_cycle_end(_state == FullMark && !_cm->has_aborted());
    _vtime_accum = (os::elapsedVTime() - _vtime_start);
  }
  _cm->root_regions()->cancel_scan();
}
```

`wait_for_next_cycle()` 等待的信号就是 `need_to_start_conc_mark` 返回 true 后 GC policy 通知的。线程启动后，首先跑 Initial Mark pause（通过 JVMThread 协调 GC 线程），然后进入并发标记的 `phase_mark_loop`。

### concurrent_mark_cycle_do 主循环

```cpp
// src/hotspot/share/gc/g1/g1ConcurrentMark.cpp
void G1ConcurrentMark::concurrent_mark_cycle_do() {
  // Initial Mark pause（由外部触发）
  phase_clear_cld_claimed_marks();       // 1. 清理残留
  phase_scan_root_regions();              // 2. 扫 survivor roots（并行）
  phase_mark_loop();                      // 3. 主标记循环（并发，do_marking_step）
  phase_rebuild_remembered_sets();        // 4. 重建 RSet
  phase_delay_to_keep_mmu_before_cleanup(); // 5. MMU 节流
  phase_cleanup();                        // 6. STW：选 CSet 候选
  phase_clear_bitmap_for_next_mark();     // 7. 为下次标记交换 bitmap
}
```

每个阶段的详细机制见 [G1 Concurrent Marking](/docs/CS/Java/JDK/JVM/GC/G1/ConcurrentMarking.md) 与 [G1 RSet Refinement](/docs/CS/Java/JDK/JVM/GC/G1/RSet.md)。

#### concurrent_mark_cycle_do 源码参考

```cpp
void G1ConcurrentMarkThread::concurrent_mark_cycle_do() {
  HandleMark hm(Thread::current());
  ResourceMark rm;

  // Phase 1: Clear CLD claimed marks.
  phase_clear_cld_claimed_marks();

  // We have to ensure that we finish scanning the root regions
  // before the next GC takes place. To ensure this we have to
  // make sure that we do not join the STS until the root regions
  // have been scanned. If we did then it's possible that a
  // subsequent GC could block us from joining the STS and proceed
  // without the root regions have been scanned which would be a
  // correctness issue.
  //
  // So do not return before the scan root regions phase as a GC waits for a
  // notification from it.
  //
  // For the same reason ConcurrentGCBreakpoints (in the phase methods) before
  // here risk deadlock, because a young GC must wait for root region scanning.
  //
  // We can not easily abort before root region scan either because of the
  // reasons mentioned in G1CollectedHeap::abort_concurrent_cycle().

  // Phase 2: Scan root regions.
  if (phase_scan_root_regions()) return;

  // Phase 3: Actual mark loop.
  if (phase_mark_loop()) return;

  // Phase 4: Rebuild remembered sets.
  if (phase_rebuild_remembered_sets()) return;

  // Phase 5: Wait for Cleanup.
  if (phase_delay_to_keep_mmu_before_cleanup()) return;

  // Phase 6: Cleanup pause
  if (phase_cleanup()) return;

  // Phase 7: Clear bitmap for next mark.
  phase_clear_bitmap_for_next_mark();
}
```

#### scan_root_regions

```cpp
void G1ConcurrentMark::scan_root_regions() {
  // scan_in_progress() will have been set to true only if there was
  // at least one root region to scan. So, if it's false, we
  // should not attempt to do any further work.
  if (root_regions()->scan_in_progress()) {
    assert(!has_aborted(), "Aborting before root region scanning is finished not supported.");

    _num_concurrent_workers = MIN2(calc_active_marking_workers(),
                                   // We distribute work on a per-region basis, so starting
                                   // more threads than that is useless.
                                   root_regions()->num_root_regions());

    G1CMRootRegionScanTask task(this);
    log_debug(gc, ergo)("Running %s using %u workers for %u work units.",
                        task.name(), _num_concurrent_workers, root_regions()->num_root_regions());
    _concurrent_workers->run_task(&task, _num_concurrent_workers);

    // It's possible that has_aborted() is true here without actually
    // aborting the survivor scan earlier. This is OK as it's
    // mainly used for sanity checking.
    root_regions()->scan_finished();
  }
}
```

scan_finished 通知可以进行下一次 Young GC

```cpp
void G1CMRootMemRegions::scan_finished() {

  if (!_should_abort) {
    assert(_claimed_root_regions >= num_root_regions(),
           "we should have claimed all root regions, claimed " SIZE_FORMAT ", length = %u",
           _claimed_root_regions, num_root_regions());
  }

  notify_scan_done();
}
```

### cleanup

```cpp
bool G1ConcurrentMarkThread::phase_cleanup() {
  CMCleanup cl(_cm);
  VM_G1Concurrent op(&cl, "Pause Cleanup");
  VMThread::execute(&op);
  return _cm->has_aborted();
}
```

```cpp

void G1ConcurrentMark::cleanup() {
  assert_at_safepoint_on_vm_thread();

  // If a full collection has happened, we shouldn't do this.
  if (has_aborted()) {
    return;
  }

  G1Policy* policy = _g1h->policy();
  policy->record_concurrent_mark_cleanup_start();

  double start = os::elapsedTime();

  verify_during_pause(G1HeapVerifier::G1VerifyCleanup, VerifyOption_G1UsePrevMarking, "Cleanup before");

  if (needs_remembered_set_rebuild()) {
    GCTraceTime(Debug, gc, phases) debug("Update Remembered Set Tracking After Rebuild", _gc_timer_cm);
    G1UpdateRemSetTrackingAfterRebuild cl(_g1h);
    _g1h->heap_region_iterate(&cl);
  } else {
    log_debug(gc, phases)("No Remembered Sets to update after rebuild");
  }

  verify_during_pause(G1HeapVerifier::G1VerifyCleanup, VerifyOption_G1UsePrevMarking, "Cleanup after");

  // We need to make this be a "collection" so any collection pause that
  // races with it goes around and waits for Cleanup to finish.
  _g1h->increment_total_collections();

  // Local statistics
  double recent_cleanup_time = (os::elapsedTime() - start);
  _total_cleanup_time += recent_cleanup_time;
  _cleanup_times.add(recent_cleanup_time);

  {
    GCTraceTime(Debug, gc, phases) debug("Finalize Concurrent Mark Cleanup", _gc_timer_cm);
    policy->record_concurrent_mark_cleanup_end(needs_remembered_set_rebuild());
  }
}
```
## Links

- [G1 枢纽页与知识地图](/docs/CS/Java/JDK/JVM/GC/G1.md)
- [G1 Predictions（CSet 尺寸 + 停顿预算）](/docs/CS/Java/JDK/JVM/GC/G1/Predictions.md)
- [G1 Concurrent Marking（SATB + do_marking_step 核心）](/docs/CS/Java/JDK/JVM/GC/G1/ConcurrentMarking.md)
- [G1 Evacuation（Young GC 复用的 evacuate 流程）](/docs/CS/Java/JDK/JVM/GC/G1/Evacuation.md)
- [G1 Full GC（Full GC 与 Mixed GC 的区别）](/docs/CS/Java/JDK/JVM/GC/G1/FullGC.md)

## References

- [G1Policy Source (openjdk.org)](https://github.com/openjdk/jdk/blob/master/src/hotspot/share/gc/g1/g1Policy.cpp)
