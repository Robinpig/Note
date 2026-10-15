## Full GC: Parallel Mark-Sweep-Compact

G1 的最终兜底回收器。**晋升失败、evacuation failure、大对象分配失败**都可能触发 Full GC。JDK 10 起（JEP 307）变成**并行**——用 `ParallelGCThreads` 个 worker 同时执行四个阶段。

Full GC 的算法是 **mark-sweep-compact**，与 evacuation 有本质区别：

| 特性 | Evacuation (Young/Mixed GC) | Full GC |
| :--- | :--- | :--- |
| 时机 | 每次 GC 都执行 | 兜底，只在 evacuation 失败后 |
| 压缩粒度 | **按对象**（边扫边复制） | **按 region**（先算地址，再统一移动） |
| 暂停时间 | 与 CSet 大小成正比 | 与整个堆存活对象成正比 |
| 引用更新 | evacuation 时边复制边更新 | 独立 Phase 3 统一更新所有引用 |

### 四阶段总览

```cpp
// src/hotspot/share/gc/g1/g1FullCollector.cpp
void G1FullCollector::collect() {
  phase1_mark_live_objects();   // STW 并行标记
  phase2_prepare_compaction();  // 计算 forwarding pointers
  phase3_adjust_pointers();     // 更新所有引用到新地址
  phase4_do_compaction();       // 按计算的地址搬运对象
}
```

### Phase 1: STW 并行标记

与 SATB 并发标记不同——Full GC 标记是**纯 STW**（没有 mutator 干扰），所以不需要写屏障记录。直接用多 worker 做三色标记。同时还处理弱引用（`ReferenceProcessor`）和类卸载（`SystemDictionary::do_unloading`）——这些是 Full GC 独有的工作。

```cpp
inline void G1FullGCMarker::follow_object(oop obj) {
  assert(_bitmap->is_marked(obj), "should be marked");
  if (obj->is_objArray()) {
    // Handle object arrays explicitly to allow them to
    // be split into chunks if needed.
    follow_array((objArrayOop)obj);
  } else {
    obj->oop_iterate(mark_closure());
  }
}
```
这里转到[Klass::oop_oop_iterate](/docs/CS/Java/JDK/JVM/Oop-Klass.md?id=oop_oop_iterate)



G1 当前的 Full GC 实现使用单线程的 mark-sweep-compact 算法。
[JEP 307: Parallel Full GC for G1](https://openjdk.java.net/jeps/307)

```
-XX:ParallelGCThreads
```

```cpp

bool G1CollectedHeap::do_full_collection(bool explicit_gc,
                                         bool clear_all_soft_refs,
                                         bool do_maximum_compaction) {
  assert_at_safepoint_on_vm_thread();

  if (GCLocker::check_active_before_gc()) {
    // Full GC was not completed.
    return false;
  }

  const bool do_clear_all_soft_refs = clear_all_soft_refs ||
      soft_ref_policy()->should_clear_all_soft_refs();

  G1FullGCMark gc_mark;
  GCTraceTime(Info, gc) tm("Pause Full", NULL, gc_cause(), true);
  G1FullCollector collector(this, explicit_gc, do_clear_all_soft_refs, do_maximum_compaction);

  collector.prepare_collection();
  collector.collect();
  collector.complete_collection();

  // Full collection was successfully completed.
  return true;
}
```

### prepare_collection
prepare_collection
- Full GC应当清理软引用
- 由于Full GC过程中，永久代（元空间）中的方法可能被移动，需要保存bcp字节码指针数据或者转化为bci字节码索引
- 保存轻量级锁和重量级锁的对象头
- 清理和处理对象的派生关系

```cpp

void G1FullCollector::prepare_collection() {
  _heap->policy()->record_full_collection_start();

  _heap->abort_concurrent_cycle();
  _heap->verify_before_full_collection(scope()->is_explicit_gc());

  _heap->gc_prologue(true);
  _heap->retire_tlabs();
  _heap->prepare_heap_for_full_collection();

  PrepareRegionsClosure cl(this);
  _heap->heap_region_iterate(&cl);

  reference_processor()->start_discovery(scope()->should_clear_soft_refs());

  // Clear and activate derived pointer collection.
  clear_and_activate_derived_pointers();
}
```

### G1FullCollector::collect

```cpp
// g1FullCollector.cpp
void G1FullCollector::collect() {
  phase1_mark_live_objects();
  verify_after_marking();

  // Don't add any more derived pointers during later phases
  deactivate_derived_pointers();

  phase2_prepare_compaction();

  phase3_adjust_pointers();

  phase4_do_compaction();
}
```

### phase1_mark_live_objects

- 标记对象，具体逻辑见下方 G1FullGCMarkTask 源码参考
- 清理弱引用
- 卸载类的元数据（complete_cleaning）或仅清理字符串（partial_cleaning）
- 清理字符串会清理StringTable和字符串去重（JEP 192: String Deduplication in G1）
```cpp
void G1FullCollector::phase1_mark_live_objects() {
  // Recursively traverse all live objects and mark them.
  GCTraceTime(Info, gc, phases) info("Phase 1: Mark live objects", scope()->timer());

    G1FullGCMarkTask marking_task(this);
    run_task(&marking_task);

    uint old_active_mt_degree = reference_processor()->num_queues();
    reference_processor()->set_active_mt_degree(workers());
    GCTraceTime(Debug, gc, phases) debug("Phase 1: Reference Processing", scope()->timer());
    // Process reference objects found during marking.
    ReferenceProcessorPhaseTimes pt(scope()->timer(), reference_processor()->max_num_queues());
    G1FullGCRefProcProxyTask task(*this, reference_processor()->max_num_queues());
    const ReferenceProcessorStats& stats = reference_processor()->process_discovered_references(task, pt);
    scope()->tracer()->report_gc_reference_stats(stats);
    pt.print_all_references();
    assert(marker(0)->oop_stack()->is_empty(), "Should be no oops on the stack");

    reference_processor()->set_active_mt_degree(old_active_mt_degree);
  }

    GCTraceTime(Debug, gc, phases) debug("Phase 1: Weak Processing", scope()->timer());
    WeakProcessor::weak_oops_do(_heap->workers(), &_is_alive, &do_nothing_cl, 1);

  if (ClassUnloading) {
    GCTraceTime(Debug, gc, phases) debug("Phase 1: Class Unloading and Cleanup", scope()->timer());
    // Unload classes and purge the SystemDictionary.
    bool purged_class = SystemDictionary::do_unloading(scope()->timer());
    _heap->complete_cleaning(&_is_alive, purged_class);

  scope()->tracer()->report_object_count_after_gc(&_is_alive);
}
```

#### G1FullGCMarkTask
- 如果允许卸载类的元数据，则调用process_strong_roots；否则调用process_all_roots_no_string_table
- process_strong_roots的GC roots仅强根
- process_all_roots_no_string_table的GC roots包括弱根、强根，但是不含StringTable
- 遍历标记栈中的所有对象
```cpp
void G1FullGCMarkTask::work(uint worker_id) {
  Ticks start = Ticks::now();
  ResourceMark rm;
  G1FullGCMarker* marker = collector()->marker(worker_id);
  MarkingCodeBlobClosure code_closure(marker->mark_closure(), !CodeBlobToOopClosure::FixRelocations);

  if (ClassUnloading) {
    _root_processor.process_strong_roots(marker->mark_closure(),
                                         marker->cld_closure(),
                                         &code_closure);
  } else {
    _root_processor.process_all_roots(marker->mark_closure(),
                                      marker->cld_closure(),
                                      &code_closure);
  }

  // Mark stack is populated, now process and drain it.
  marker->complete_marking(collector()->oop_queue_set(), collector()->array_queue_set(), &_terminator);
  marker->flush_mark_stats_cache();

  // This is the point where the entire marking should have completed.
  assert(marker->oop_stack()->is_empty(), "Marking should have completed");
  assert(marker->objarray_stack()->is_empty(), "Array marking should have completed");
  log_task("Marking task", worker_id, start);
}
```

### Phase 2: Prepare Compaction — 计算所有对象的新地址

Full GC 最关键的阶段——为堆中**每个存活对象**计算压缩后的新位置，写入其 mark-word 作为 forwarding pointer。与 evacuation "边扫边复制" 不同，Full GC 先算完所有地址，再统一搬运。

#### 核心设计：Compaction Point

每个 worker 维护自己的 compaction point（一个"源→目标"的 region 映射列表），避免多线程同时写一个 region：

```
G1FullGCCompactionPoint (per worker)
  ├── _input_regions[]   // 源 region（要被压缩的 region）
  ├── _output_regions[]  // 目标 region（接收压缩对象的空 region）
  └── _forwarding        // 当前目标 region 的 bump-pointer
```

遍历 region 时，对每个存活对象做 `new_addr = output_region.par_allocate(obj_size)`，然后 `obj->set_mark(encode_pointer_as_mark(new_addr))`。**对象还没动**——现在只是在算"搬到哪里"。

#### 串行压缩兜底

Phase 2 末尾如果没有释放出足够的空 region（极端碎片），`prepare_serial_compaction()` 把所有线程的最后一个 region 合并，单线程硬压缩一次——避免 OOM。

#### phase2_prepare_compaction 源码

```cpp
void G1FullCollector::phase2_prepare_compaction() {
  GCTraceTime(Info, gc, phases) info("Phase 2: Prepare for compaction", scope()->timer());
  G1FullGCPrepareTask task(this);
  run_task(&task);

  // To avoid OOM when there is memory left.
  if (!task.has_freed_regions()) {
    task.prepare_serial_compaction();
  }
}
```

#### G1FullGCPrepareTask

```cpp

void G1FullGCPrepareTask::work(uint worker_id) {
  Ticks start = Ticks::now();
  G1FullGCCompactionPoint* compaction_point = collector()->compaction_point(worker_id);
  G1CalculatePointersClosure closure(collector(), compaction_point);
  G1CollectedHeap::heap()->heap_region_par_iterate_from_start(&closure, &_hrclaimer);

  compaction_point->update();

  // Check if any regions was freed by this worker and store in task.
  if (closure.freed_regions()) {
    set_freed_regions();
  }
  log_task("Prepare compaction task", worker_id, start);
}
```

### Phase 3: Adjust Pointers — 更新所有引用

Phase 2 计算完 forwarding pointers 后，堆中所有引用字段还指向旧地址。Phase 3 按**有依赖的顺序**统一更新：

```
1. preserved marks（轻量级锁/重量级锁保护的对象）→ 必须先调
2. weak roots（Soft/Weak/PhantomReference 的 referent）
3. GC roots（线程栈、JNI handles、Universe、StringTable、CLDG）
4. region by region 遍历所有对象的字段引用
```

为什么 roots 在堆内字段之前？调整 roots 时需要读取对象——如果对象地址变了但 roots 还指向旧地址，就是 use-after-free。**先从 roots 开始，保证遍历始终从新地址出发**。

#### phase3_adjust_pointers 源码

```cpp
void G1FullCollector::phase3_adjust_pointers() {
  // Adjust the pointers to reflect the new locations
  GCTraceTime(Info, gc, phases) info("Phase 3: Adjust pointers", scope()->timer());

  G1FullGCAdjustTask task(this);
  run_task(&task);
}
```

#### G1FullGCAdjustTask

```cpp

void G1FullGCAdjustTask::work(uint worker_id) {
  Ticks start = Ticks::now();
  ResourceMark rm;

  // Adjust preserved marks first since they are not balanced.
  G1FullGCMarker* marker = collector()->marker(worker_id);
  marker->preserved_stack()->adjust_during_full_gc();

  {
    // Adjust the weak roots.
    AlwaysTrueClosure always_alive;
    _weak_proc_task.work(worker_id, &always_alive, &_adjust);
  }

  CLDToOopClosure adjust_cld(&_adjust, ClassLoaderData::_claim_strong);
  CodeBlobToOopClosure adjust_code(&_adjust, CodeBlobToOopClosure::FixRelocations);
  _root_processor.process_all_roots(&_adjust, &adjust_cld, &adjust_code);

  // Now adjust pointers region by region
  G1AdjustRegionClosure blk(collector(), worker_id);
  G1CollectedHeap::heap()->heap_region_par_iterate_from_worker_offset(&blk, &_hrclaimer, worker_id);
  log_task("Adjust task", worker_id, start);
}
```

### Phase 4: Do Compaction — 搬运对象

有了 forwarding pointers（Phase 2 写的）和更新过的引用（Phase 3 调的），Phase 4 只需按 Phase 2 规划好的顺序把对象搬到新位置：

```
G1FullGCCompactTask::work(worker_id)
  → G1CompactRegionClosure
    └── 对每个存活对象：
          forwardee = obj->forwardee()   // 读 Phase 2 写的 forwarding pointer
          Copy::aligned_disjoint_words(forwardee, obj, obj_size)
```

搬完之后所有源 region 通过 Phase 2 标记的 `freed_regions` 列表释放回 free list。

#### phase4_do_compaction 源码

```cpp

void G1FullCollector::phase4_do_compaction() {
  // Compact the heap using the compaction queues created in phase 2.
  GCTraceTime(Info, gc, phases) info("Phase 4: Compact heap", scope()->timer());
  G1FullGCCompactTask task(this);
  run_task(&task);

  // Serial compact to avoid OOM when very few free regions.
  if (serial_compaction_point()->has_regions()) {
    task.serial_compaction();
  }
}
```

#### G1FullGCCompactTask

```cpp

void G1FullGCCompactTask::work(uint worker_id) {
  Ticks start = Ticks::now();
  GrowableArray<HeapRegion*>* compaction_queue = collector()->compaction_point(worker_id)->regions();
  for (GrowableArrayIterator<HeapRegion*> it = compaction_queue->begin();
       it != compaction_queue->end();
       ++it) {
    compact_region(*it);
  }

  G1ResetSkipCompactingClosure hc(collector());
  G1CollectedHeap::heap()->heap_region_par_iterate_from_worker_offset(&hc, &_claimer, worker_id);
  log_task("Compaction task", worker_id, start);
}
```

### complete_collection

```cpp

void G1FullCollector::complete_collection() {
  // Restore all marks.
  restore_marks();

  // When the pointers have been adjusted and moved, we can
  // update the derived pointer table.
  update_derived_pointers();

  _heap->concurrent_mark()->swap_mark_bitmaps();
  // Prepare the bitmap for the next (potentially concurrent) marking.
  _heap->concurrent_mark()->clear_next_bitmap(_heap->workers());

  _heap->prepare_heap_for_mutators();

  _heap->resize_all_tlabs();

  _heap->policy()->record_full_collection_end();
  _heap->gc_epilogue(true);

  _heap->verify_after_full_collection();
}
```

### Improvement

[JEP 307: Parallel Full GC for G1](https://openjdk.org/jeps/307) 


## Development

G1 is still under active development. Each JDK release sees several improvements to throughput, startup, pause times, and memory footprint.

* [Refactoring of remembered sets](https://bugs.openjdk.org/browse/JDK-8017163), which provided a significant memory footprint improvement
* [Increasing max region size](https://bugs.openjdk.org/browse/JDK-8275056)
* [Region pinning](https://openjdk.org/jeps/423)

### Comparison to Other Collectors

以下是 G1 与其他收集器的主要差异总结：

Parallel GC 只能作为一个整体对老年代进行压缩和空间回收。G1 将此工作增量式分布在多个更短的回收中。这显著缩短了停顿时间，代价是吞吐量可能降低。
G1 并发执行部分老年代空间回收工作。
G1 由于其并发特性，可能比上述收集器表现出更高的开销，影响吞吐量。
ZGC 面向非常大的堆，旨在以进一步降低吞吐量为代价提供显著更小的停顿时间。
由于其工作原理，G1 具有一些独特机制来提高垃圾回收效率：

G1 可以在任何回收期间回收老年代中一些完全为空的大区域。这可以避免许多本不必要的垃圾回收，以较小代价释放大量空间。
G1 可以可选地尝试并发去重 Java 堆上的重复字符串。
从老年代回收空的大对象始终启用。可以使用 -XX:-G1EagerReclaimHumongousObjects 选项禁用此功能。字符串去重默认禁用，可使用 -XX:+G1EnableStringDeduplication 启用。

## Tuning

> 很多应用在升级JDK11，出现容器和Java进程内存整体变高的现象，主要源自Heap的使用率差异。
> CMS的Old generation为非移动式，由 CMSInitiatingOccupancyFraction 来控制使用比例来触发gc，因此应用启动后短时间内，heap old区使用率不会上升。
> 而G1的heap region是松散管理，整体利用heap，所以显得内存使用率高。本质是一个heap利用率的问题，cms初始留着部分heap不用。这个问题可以通过调低Xmx来解决

**一般建议是使用 G1 的默认设置**，
如需最终设置不同的停顿时间目标和最大 Java 堆大小，可使用 -Xmx。

G1 的默认值与其他收集器的平衡方式不同。
G1 默认配置的目标既不是最大吞吐量也不是最低延迟，而是在高吞吐量下提供相对较小且均匀的停顿。
但 G1 增量式回收堆空间的机制和停顿时间控制会在应用线程和空间回收效率方面带来一些开销。

如果偏好高吞吐量，则通过 -XX:MaxGCPauseMillis 放宽停顿时间目标或提供更大的堆。
如果延迟是主要需求，则修改停顿时间目标。
避免使用 -Xmn、-XX:NewRatio 等选项将年轻代大小限制为特定值，因为年轻代大小是 G1 用来满足停顿时间目标的主要手段。
**将年轻代大小设置为单个值会覆盖并实际上禁用停顿时间控制。**

通常，从其他收集器（特别是 Concurrent Mark Sweep 收集器）迁移到 G1 时，首先移除所有影响垃圾回收的选项，只使用 -Xmx 和可选的 -Xms 设置停顿时间目标和整体堆大小。
许多对其他收集器有用的特定选项，对 G1 要么完全不起作用，要么甚至会降低吞吐量和满足停顿时间目标的可能性。

出于诊断目的，G1 提供了全面的日志。
一个好的起点是使用 -Xlog:gc*=debug 选项，然后根据需要优化输出。
日志在停顿期间和停顿之外提供关于垃圾回收活动的详细概览。
这包括回收类型和停顿特定阶段花费时间的细分。

### Observing Full Garbage Collections

全堆垃圾回收（Full GC）通常非常耗时。由老年代堆占用过高引起的 Full GC 可以通过在日志中找到 "Pause Full (G1 Compaction Pause)" 字样来识别。Full GC 之前通常会发生遇到疏散失败的垃圾回收，由 "(Evacuation Failure)" 标记指示。

发生 Full GC 的原因是应用分配了过多无法足够快回收的对象。通常并发标记未能及时完成以启动空间回收阶段。分配许多大对象会加剧遇到 Full GC 的可能性。由于 G1 分配这些对象的方式，它们可能占用比预期多得多的内存。

目标应该是确保并发标记按时完成。这可以通过降低老年代的分配率，或给予并发标记更多完成时间来实现。

G1 提供了几个选项来更好地处理这种情况：

- 可以使用 gc+heap=info 日志确定 Java 堆上大对象占用的 region 数量。
  "Humongous regions: X->Y" 行中的 Y 给出了大对象占用的 region 数量。
  如果此数量相对于 old region 数量较高，最好尝试减少此类对象的数量。`To-space exhausted` 错误请检查 GC 日志中是否有过多 `Pause Young (Concurrent Start) (G1 Humongous Allocation)`。
  可以通过使用 -XX:G1HeapRegionSize 选项增加 region 大小来实现。8-32M
  当前选中的 heap region 大小会在日志开头打印。
- 增加 Java 堆大小。这通常会增加标记完成所需的时间。
- 通过显式设置 -XX:ConcGCThreads 增加并发标记线程数量。
- 强制 G1 更早启动标记。G1 根据之前的应用行为自动确定 IHOP 阈值。
  如果应用行为改变，这些预测可能不准确。
  有两个选项：通过修改 -XX:G1ReservePercent 增加自适应 IHOP 计算中使用的缓冲来降低启动空间回收的目标占用；
  或者通过使用 -XX:-G1UseAdaptiveIHOP 和 -XX:InitiatingHeapOccupancyPercent 手动设置来禁用 IHOP 的自适应计算。

Full GC 除 Allocation Failure 之外的其他原因通常表明应用或某些外部工具导致了全堆回收。
如果原因是 System.gc()，且无法修改应用源码，则可以通过 -XX:+ExplicitGCInvokesConcurrent 缓解 Full GC 的影响，或通过设置 -XX:+DisableExplicitGC 让 VM 完全忽略它们。外部工具仍可能强制 Full GC；只能通过不请求它们来消除。

### Humongous Object Fragmentation

在所有 Java 堆内存耗尽之前，可能因为需要为大对象找到连续的 region 集合而触发 Full GC。这种情况下的潜在解决方案是通过使用 -XX:G1HeapRegionSize 选项增加 heap region 大小来减少大对象数量，或增加堆大小。极端情况下，即使可用内存显示足够，G1 也可能没有足够的连续空间来分配对象。如果 Full GC 无法回收足够的连续空间，这将导致 VM 退出。因此，除了如前所述减少大对象分配数量或增加堆大小之外，没有其他选项。

### Tuning for Latency

#### Unusual System or Real-Time Usage

对于每次垃圾回收停顿，gc+cpu=info 日志输出包含一行来自操作系统的信息，细分了停顿时间花在哪里。
此类输出示例为 User=0.19s Sys=0.00s Real=0.01s。

User 时间是 VM 代码中花费的时间，system 时间是操作系统中花费的时间，real 时间是停顿期间经过的绝对时间。
如果 system 时间相对较高，通常环境是原因。

system 时间高的常见已知原因包括：

- VM 从操作系统分配或释放内存可能导致不必要的延迟。
  使用 -Xms 和 -Xmx 将最小和最大堆大小设置为相同值，并使用 -XX:+AlwaysPreTouch 预触摸所有内存以将此工作移到 VM 启动阶段，可以避免延迟。
- 特别是在 Linux 中，Transparent Huge Pages（THP）功能将小页面合并为大页面，往往会导致随机进程停滞，而不仅仅在停顿期间。
  由于 VM 分配和维护大量内存，VM 成为长时间停滞进程的风险比平时更高。请参考操作系统文档了解如何禁用 Transparent Huge Pages 功能。
- 写入日志输出可能会因为某些后台任务间歇性占用日志所在硬盘的所有 I/O 带宽而停滞一段时间。
  考虑为日志使用单独磁盘或其他存储，例如内存文件系统以避免此问题。

另一个需要注意的情况是 real time 比其他时间之和大得多——这可能表明 VM 在可能过载的机器上没有获得足够的 CPU 时间。

#### Reference Object Processing Takes Too Long

Reference Objects 处理花费的时间信息显示在 Reference Processing 阶段。
在 Reference Processing 阶段，G1 根据特定类型 Reference Object 的要求更新它们的 referents。
默认情况下，G1 尝试使用以下启发式方法将 Reference Processing 的子阶段并行化：每处理 -XX:ReferencesPerThread 个 Reference Objects 启动一个线程，线程数量以 -XX:ParallelGCThreads 中的值为上限。
可以通过将 -XX:ReferencesPerThread 设置为 0 来禁用此启发式方法，默认使用所有可用线程，或通过 -XX:-ParallelRefProcEnabled 完全禁用并行化。

#### Young-Only Collections Within the Young-Only Phase Take Too Long

普通 young collection 以及一般任何 young collection，时间大致与年轻代大小成正比，或更具体地说，与 collection set 中需要复制的存活对象数量成正比。
如果 Evacuate Collection Set 阶段（特别是 Object Copy 子阶段）耗时过长，则降低 -XX:G1NewSizePercent。这会降低年轻代的最小大小，可能允许更短的停顿。

另一个与年轻代大小相关的问题可能在应用性能变化时发生，特别是在回收后存活对象数量突然变化时。
这可能导致垃圾回收停顿时间尖峰。使用 -XX:G1MaxNewSizePercent 降低年轻代最大大小可能有用。
这会限制年轻代的最大大小，从而限制停顿期间需要处理的对象数量。

#### Mixed Collections Take Too Long

Mixed young collection 用于回收老年代空间。Mixed collection 的 collection set 包含年轻代和老年代 region。
可以通过启用 gc+ergo+cset=debug 日志输出来获取年轻代或老年代 region 的疏散对停顿时间贡献多少的信息。
## Links

- [G1 枢纽页与知识地图](/docs/CS/Java/JDK/JVM/GC/G1.md)
- [G1 Evacuation（evacuation vs compaction 对比）](/docs/CS/Java/JDK/JVM/GC/G1/Evacuation.md)
- [G1 Mixed GC（Mixed GC 比 Full GC 更细粒度的分段回收）](/docs/CS/Java/JDK/JVM/GC/G1/MixedGC.md)
- [Parallel GC（同为并行收集器，对比）](/docs/CS/Java/JDK/JVM/GC/Parallel.md)

## References

- [JEP 307: Parallel Full GC for G1](https://openjdk.org/jeps/307)
- [G1FullCollector Source (openjdk.org)](https://github.com/openjdk/jdk/blob/master/src/hotspot/share/gc/g1/g1FullCollector.cpp)
