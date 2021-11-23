## Introduction

Garbage Collection 

## When an instance is dead？ 
#### 引用计数算法：

   为对象添加一个引用计数器，当对象增加一个引用时计数器加 1，
        引用失效时计数器减 1。引用计数为 0 的对象可被回收，
        但存在循环引用而无法回收问题，已不再适用。



#### 可达性分析算法：

  以 GC Roots 为起始点进行搜索，可达的对象都是存活的，不可达的对象可被回收。
  Java 虚拟机使用该算法来判断对象是否可被回收，GC Roots 一般包含以下内容：



**GC Roots:**

- `ClassLoaderDataGraph::roots_cld_do()`

  - 虚拟机栈中局部变量表中引用的对象
  - 本地方法栈中 JNI 中引用的对象 包括global handles和local handles
  - 方法区中类静态属性引用的对象
  - 方法区中的常量引用的对象
  - 所有当前被加载的Java类
  - JVM内部数据结构的一些引用，比如`sun.jvm.hotspot.memory.Universe`类
  - 用于同步的监控对象，比如调用了对象的`wait()`方法



### Recycle

Copying

Mark-Sweep

Mark-Compact

分代

interceptor and JIT use Write Barrier to maintain Card Table

Premature Promotion

Promotion Failure

[Reference](/docs/CS/Java/JDK/Basic/Ref.md)


gcCause.cpp




### Young GC 问题

```
-XX:+UsePSAdaptiveSurvivorSizePolicy

-XX:SurvivorRatio

-XX:TargetSurvivorRatio
```

Card Table

write barrier
```
CARD_TABLE [this address >> 9] = DIRTY;
```
-XX:+UseCondCardMark



####  YGC耗时异常 

- toot对象扫描+标记时间过长                
- 存活对象copy耗时较大                
- 等待各线程到达安全点时间较长                
- GC日志对GC时间的影响                
- 操作系统活动影响（内存swap等）                

### Full GC 问题

 FGC频次异常 

- 老年代空间不足                
- 内存碎片化                
- 永久代/元空间 空间不足                
- 对象预估和担保                
- 堆大小动态调整          





![GC Collector](../images/GC-collector.png)



1. collection_attempt_is_safe
2. young_process_roots

```cpp
void DefNewGeneration::collect(bool   full,
                               bool   clear_all_soft_refs,
                               size_t size,
                               bool   is_tlab) {
...
  _old_gen = heap->old_gen();

  // If the next generation is too full to accommodate promotion
  // from this generation, pass on collection; let the next generation
  // do it.
  if (!collection_attempt_is_safe()) {
    log_trace(gc)(":: Collection attempt not safe ::");
    heap->set_incremental_collection_failed(); // Slight lie: we did not even attempt one
    return;
  }

  heap->trace_heap_before_gc(&gc_tracer);

  // These can be shared for all code paths
  IsAliveClosure is_alive(this);
  ScanWeakRefClosure scan_weak_ref(this);

  age_table()->clear();
  to()->clear(SpaceDecorator::Mangle);
  // The preserved marks should be empty at the start of the GC.
  _preserved_marks_set.init(1);

  heap->rem_set()->prepare_for_younger_refs_iterate(false);

  FastScanClosure fsc_with_no_gc_barrier(this, false);
  FastScanClosure fsc_with_gc_barrier(this, true);

  CLDScanClosure cld_scan_closure(&fsc_with_no_gc_barrier,
                                  heap->rem_set()->cld_rem_set()->accumulate_modified_oops());

  set_promo_failure_scan_stack_closure(&fsc_with_no_gc_barrier);
  FastEvacuateFollowersClosure evacuate_followers(heap,
                                                  &fsc_with_no_gc_barrier,
                                                  &fsc_with_gc_barrier);
  {
    // DefNew needs to run with n_threads == 0, to make sure the serial
    // version of the card table scanning code is used.
    // See: CardTableRS::non_clean_card_iterate_possibly_parallel.
    StrongRootsScope srs(0);

    heap->young_process_roots(&srs,
                              &fsc_with_no_gc_barrier,
                              &fsc_with_gc_barrier,
                              &cld_scan_closure);
  }

  // "evacuate followers".
  evacuate_followers.do_void();

  FastKeepAliveClosure keep_alive(this, &scan_weak_ref);
  ReferenceProcessor* rp = ref_processor();
  rp->setup_policy(clear_all_soft_refs);
  ReferenceProcessorPhaseTimes pt(_gc_timer, rp->max_num_queues());
  const ReferenceProcessorStats& stats =
  rp->process_discovered_references(&is_alive, &keep_alive, &evacuate_followers,
                                    NULL, &pt);
  gc_tracer.report_gc_reference_stats(stats);
  gc_tracer.report_tenuring_threshold(tenuring_threshold());
  pt.print_all_references();

  WeakProcessor::weak_oops_do(&is_alive, &keep_alive);

  if (!_promotion_failed) {
    // Swap the survivor spaces.
    eden()->clear(SpaceDecorator::Mangle);
    from()->clear(SpaceDecorator::Mangle);
    if (ZapUnusedHeapArea) {
      // This is now done here because of the piece-meal mangling which
      // can check for valid mangling at intermediate points in the
      // collection(s).  When a young collection fails to collect
      // sufficient space resizing of the young generation can occur
      // an redistribute the spaces in the young generation.  Mangle
      // here so that unzapped regions don't get distributed to
      // other spaces.
      to()->mangle_unused_area();
    }
    swap_spaces();

    adjust_desired_tenuring_threshold();

    // A successful scavenge should restart the GC time limit count which is
    // for full GC's.
    AdaptiveSizePolicy* size_policy = heap->size_policy();
    size_policy->reset_gc_overhead_limit_count();
    assert(!heap->incremental_collection_failed(), "Should be clear");
  } else {
    _promo_failure_scan_stack.clear(true); // Clear cached segments.

    remove_forwarding_pointers();
    log_info(gc, promotion)("Promotion failed");
    // Add to-space to the list of space to compact
    // when a promotion failure has occurred.  In that
    // case there can be live objects in to-space
    // as a result of a partial evacuation of eden
    // and from-space.
    swap_spaces();   // For uniformity wrt ParNewGeneration.
    from()->set_next_compaction_space(to());
    heap->set_incremental_collection_failed();

    // Inform the next generation that a promotion failure occurred.
    _old_gen->promotion_failure_occurred();
    gc_tracer.report_promotion_failed(_promotion_failed_info);

    // Reset the PromotionFailureALot counters.
    NOT_PRODUCT(heap->reset_promotion_should_fail();)
  }
  // We should have processed and cleared all the preserved marks.
  _preserved_marks_set.reclaim();
  // set new iteration safe limit for the survivor spaces
  from()->set_concurrent_iteration_safe_limit(from()->top());
  to()->set_concurrent_iteration_safe_limit(to()->top());

  // We need to use a monotonically non-decreasing time in ms
  // or we will see time-warp warnings and os::javaTimeMillis()
  // does not guarantee monotonicity.
  jlong now = os::javaTimeNanos() / NANOSECS_PER_MILLISEC;
  update_time_of_last_gc(now);

  heap->trace_heap_after_gc(&gc_tracer);

  _gc_timer->register_gc_end();

  gc_tracer.report_gc_end(_gc_timer->gc_end(), _gc_timer->time_partitions());
}
```



## Collector

### Epsilon
[JEP 318: Epsilon: A No-Op Garbage Collector](https://openjdk.java.net/jeps/318)
Develop a GC that handles memory allocation but does not implement any actual memory reclamation mechanism. Once the available Java heap is exhausted, the JVM will shut down.
### serial


### parallel

- GCTimeRatio                               = 99
- MaxGCPauseMillis                          = 18446744073709551615


- UseParallelGC                            := true
- UseParallelOldGC                          = true
- UseAdaptiveGCBoundary                     = false

### Concurrent
The mostly concurrent collector trades processor resources (which would otherwise be available to the application) for shorter major collection pause times. The most visible overhead is the use of one or more processors during the concurrent parts of the collection. On an N processor system, the concurrent part of the collection will use K/N of the available processors, where 1<=K<=ceiling{N/4}. (Note that the precise choice of and bounds on K are subject to change.) In addition to the use of processors during concurrent phases, additional overhead is incurred to enable concurrency. Thus while garbage collection pauses are typically much shorter with the concurrent collector, application throughput also tends to be slightly lower than with the other collectors.

On a machine with more than one processing core, processors are available for application threads during the concurrent part of the collection, so the concurrent garbage collector thread does not "pause" the application. This usually results in shorter pauses, but again fewer processor resources are available to the application and some slowdown should be expected, especially if the application uses all of the processing cores maximally. As N increases, the reduction in processor resources due to concurrent garbage collection becomes smaller, and the benefit from concurrent collection increases. The section Concurrent Mode Failure in Concurrent Mark Sweep (CMS) Collector discusses potential limits to such scaling.

Because at least one processor is used for garbage collection during the concurrent phases, the concurrent collectors do not normally provide any benefit on a uniprocessor (single-core) machine. However, there is a separate mode available for CMS (not G1) that can achieve low pauses on systems with only one or two processors; see Incremental Mode in Concurrent Mark Sweep (CMS) Collector for details. This feature is being deprecated in Java SE 8 and may be removed in a later major release.

### cms

### g1

### shenandoah

### z

### 










## References
1. [Unnecessary GCLocker-initiated young GCs](https://bugs.openjdk.java.net/browse/JDK-8048556)
2. [Exploiting the Weak Generational Hypothesis for Write Reduction and Object Recycling](https://openscholarship.wustl.edu/eng_etds/169/)
3. [Java Platform, Standard Edition HotSpot Virtual Machine Garbage Collection Tuning Guide](https://docs.oracle.com/javase/8/docs/technotes/guides/vm/gctuning/toc.html)
4. [Our Collectors](https://blogs.oracle.com/jonthecollector/our-collectors)