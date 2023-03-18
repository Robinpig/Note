## Overview

The parallel collector (also referred to here as the throughput collector) is a generational collector similar to the serial collector; 
the primary difference is that multiple threads are used to speed up garbage collection.
The parallel collector is enabled with the command-line option -XX:+UseParallelGC. 
By default, with this option, both minor and major collections are executed in parallel to further reduce garbage collection overhead.

On a machine with N hardware threads where N is greater than 8, the parallel collector uses a fixed fraction of N as the number of garbage collector threads.
The fraction is approximately 5/8 for large values of N. At values of N below 8, the number used is N. On selected platforms, the fraction drops to 5/16. 
The specific number of garbage collector threads can be adjusted with a command-line option (which is described later). 
On a host with one processor, the parallel collector will likely not perform as well as the serial collector because of the overhead required for parallel execution (for example, synchronization). 
However, when running applications with medium-sized to large-sized heaps, it generally outperforms the serial collector by a modest amount on machines with two processors,
and usually performs significantly better than the serial collector when more than two processors are available.

The number of garbage collector threads can be controlled with the command-line option `-XX:ParallelGCThreads=<N>`. 
If explicit tuning of the heap is being done with command-line options, then the size of the heap needed for good performance with the parallel collector is the same as needed with the serial collector. 
However, enabling the parallel collector should make the collection pauses shorter.
Because multiple garbage collector threads are participating in a minor collection, some fragmentation is possible due to promotions from the young generation to the tenured generation during the collection.
Each garbage collection thread involved in a minor collection reserves a part of the tenured generation for promotions and the division of the available space into these "promotion buffers" can cause a fragmentation effect.
Reducing the number of garbage collector threads and increasing the size of the tenured generation will reduce this fragmentation effect.

### invoke

This method should contain all heap-specific policy for invoking a full collection.
invoke_no_policy() will only attempt to compact the heap; it will do nothing further.
If we need to bail out for policy reasons, scavenge before full gc, or any other specialized behavior, it needs to be added here.

Note that this method should only be called from the vm_thread while at a safepoint.

Note that the all_soft_refs_clear flag in the soft ref policy
may be true because this method can be called without intervening activity.
For example when the heap space is tight and full measure are being taken to free space.

```cpp
void PSParallelCompact::invoke(bool maximum_heap_compaction) {
  assert(SafepointSynchronize::is_at_safepoint(), "should be at safepoint");
  assert(Thread::current() == (Thread*)VMThread::vm_thread(),
         "should be in vm thread");

  ParallelScavengeHeap* heap = ParallelScavengeHeap::heap();
  GCCause::Cause gc_cause = heap->gc_cause();
  assert(!heap->is_gc_active(), "not reentrant");

  PSAdaptiveSizePolicy* policy = heap->size_policy();
  IsGCActiveMark mark;

  if (ScavengeBeforeFullGC) {
    PSScavenge::invoke_no_policy();
  }

  const bool clear_all_soft_refs =
    heap->soft_ref_policy()->should_clear_all_soft_refs();

  PSParallelCompact::invoke_no_policy(clear_all_soft_refs ||
                                      maximum_heap_compaction);
}
```

#### invoke_no_policy

This method contains no policy. You should probably be calling invoke() instead.

```cpp
bool PSParallelCompact::invoke_no_policy(bool maximum_heap_compaction) {
  assert(SafepointSynchronize::is_at_safepoint(), "must be at a safepoint");
  assert(ref_processor() != NULL, "Sanity");

  if (GCLocker::check_active_before_gc()) {
    return false;
  }

  ParallelScavengeHeap* heap = ParallelScavengeHeap::heap();

  GCIdMark gc_id_mark;
  _gc_timer.register_gc_start();
  _gc_tracer.report_gc_start(heap->gc_cause(), _gc_timer.gc_start());

  TimeStamp marking_start;
  TimeStamp compaction_start;
  TimeStamp collection_exit;

  GCCause::Cause gc_cause = heap->gc_cause();
  PSYoungGen* young_gen = heap->young_gen();
  PSOldGen* old_gen = heap->old_gen();
  PSAdaptiveSizePolicy* size_policy = heap->size_policy();

  // The scope of casr should end after code that can change
  // SoftRefPolicy::_should_clear_all_soft_refs.
  ClearedAllSoftRefs casr(maximum_heap_compaction,
                          heap->soft_ref_policy());

  if (ZapUnusedHeapArea) {
    // Save information needed to minimize mangling
    heap->record_gen_tops_before_GC();
  }

  // Make sure data structures are sane, make the heap parsable, and do other
  // miscellaneous bookkeeping.
  pre_compact();

  const PreGenGCValues pre_gc_values = heap->get_pre_gc_values();

  // Get the compaction manager reserved for the VM thread.
  ParCompactionManager* const vmthread_cm = ParCompactionManager::get_vmthread_cm();

  {
    const uint active_workers =
      WorkerPolicy::calc_active_workers(ParallelScavengeHeap::heap()->workers().max_workers(),
                                        ParallelScavengeHeap::heap()->workers().active_workers(),
                                        Threads::number_of_non_daemon_threads());
    ParallelScavengeHeap::heap()->workers().set_active_workers(active_workers);

    GCTraceCPUTime tcpu;
    GCTraceTime(Info, gc) tm("Pause Full", NULL, gc_cause, true);

    heap->pre_full_gc_dump(&_gc_timer);

    TraceCollectorStats tcs(counters());
    TraceMemoryManagerStats tms(heap->old_gc_manager(), gc_cause);

    if (log_is_enabled(Debug, gc, heap, exit)) {
      accumulated_time()->start();
    }

    // Let the size policy know we're starting
    size_policy->major_collection_begin();

    #if COMPILER2_OR_JVMCI
    DerivedPointerTable::clear();
    #endif

    ref_processor()->start_discovery(maximum_heap_compaction);

    marking_start.update();
    marking_phase(vmthread_cm, &_gc_tracer);

    bool max_on_system_gc = UseMaximumCompactionOnSystemGC
      && GCCause::is_user_requested_gc(gc_cause);
    summary_phase(vmthread_cm, maximum_heap_compaction || max_on_system_gc);

    #if COMPILER2_OR_JVMCI
    assert(DerivedPointerTable::is_active(), "Sanity");
    DerivedPointerTable::set_active(false);
    #endif

    // adjust_roots() updates Universe::_intArrayKlassObj which is
    // needed by the compaction for filling holes in the dense prefix.
    adjust_roots();

    compaction_start.update();
    compact();

    ParCompactionManager::verify_all_region_stack_empty();

    // Reset the mark bitmap, summary data, and do other bookkeeping.  Must be
    // done before resizing.
    post_compact();

    // Let the size policy know we're done
    size_policy->major_collection_end(old_gen->used_in_bytes(), gc_cause);

    if (UseAdaptiveSizePolicy) {
      log_debug(gc, ergo)("AdaptiveSizeStart: collection: %d ", heap->total_collections());
      log_trace(gc, ergo)("old_gen_capacity: " SIZE_FORMAT " young_gen_capacity: " SIZE_FORMAT,
                          old_gen->capacity_in_bytes(), young_gen->capacity_in_bytes());

      // Don't check if the size_policy is ready here.  Let
      // the size_policy check that internally.
      if (UseAdaptiveGenerationSizePolicyAtMajorCollection &&
          AdaptiveSizePolicy::should_update_promo_stats(gc_cause)) {
        // Swap the survivor spaces if from_space is empty. The
        // resize_young_gen() called below is normally used after
        // a successful young GC and swapping of survivor spaces;
        // otherwise, it will fail to resize the young gen with
        // the current implementation.
        if (young_gen->from_space()->is_empty()) {
          young_gen->from_space()->clear(SpaceDecorator::Mangle);
          young_gen->swap_spaces();
        }

        // Calculate optimal free space amounts
        assert(young_gen->max_gen_size() >
          young_gen->from_space()->capacity_in_bytes() +
          young_gen->to_space()->capacity_in_bytes(),
          "Sizes of space in young gen are out-of-bounds");

        size_t young_live = young_gen->used_in_bytes();
        size_t eden_live = young_gen->eden_space()->used_in_bytes();
        size_t old_live = old_gen->used_in_bytes();
        size_t cur_eden = young_gen->eden_space()->capacity_in_bytes();
        size_t max_old_gen_size = old_gen->max_gen_size();
        size_t max_eden_size = young_gen->max_gen_size() -
          young_gen->from_space()->capacity_in_bytes() -
          young_gen->to_space()->capacity_in_bytes();

        // Used for diagnostics
        size_policy->clear_generation_free_space_flags();

        size_policy->compute_generations_free_space(young_live,
                                                    eden_live,
                                                    old_live,
                                                    cur_eden,
                                                    max_old_gen_size,
                                                    max_eden_size,
                                                    true /* full gc*/);

        size_policy->check_gc_overhead_limit(eden_live,
                                             max_old_gen_size,
                                             max_eden_size,
                                             true /* full gc*/,
                                             gc_cause,
                                             heap->soft_ref_policy());

        size_policy->decay_supplemental_growth(true /* full gc*/);

        heap->resize_old_gen(
          size_policy->calculated_old_free_size_in_bytes());

        heap->resize_young_gen(size_policy->calculated_eden_size_in_bytes(),
                               size_policy->calculated_survivor_size_in_bytes());
      }

      log_debug(gc, ergo)("AdaptiveSizeStop: collection: %d ", heap->total_collections());
    }

    if (UsePerfData) {
      PSGCAdaptivePolicyCounters* const counters = heap->gc_policy_counters();
      counters->update_counters();
      counters->update_old_capacity(old_gen->capacity_in_bytes());
      counters->update_young_capacity(young_gen->capacity_in_bytes());
    }

    heap->resize_all_tlabs();

    // Resize the metaspace capacity after a collection
    MetaspaceGC::compute_new_size();

    if (log_is_enabled(Debug, gc, heap, exit)) {
      accumulated_time()->stop();
    }

    heap->print_heap_change(pre_gc_values);

    // Track memory usage and detect low memory
    MemoryService::track_memory_usage();
    heap->update_counters();

    heap->post_full_gc_dump(&_gc_timer);
  }

  if (VerifyAfterGC && heap->total_collections() >= VerifyGCStartAt) {
    Universe::verify("After GC");
  }

  // Re-verify object start arrays
  if (VerifyObjectStartArray &&
      VerifyAfterGC) {
    old_gen->verify_object_start_array();
  }

  if (ZapUnusedHeapArea) {
    old_gen->object_space()->check_mangled_unused_area_complete();
  }

  collection_exit.update();

  heap->print_heap_after_gc();
  heap->trace_heap_after_gc(&_gc_tracer);

  log_debug(gc, task, time)("VM-Thread " JLONG_FORMAT " " JLONG_FORMAT " " JLONG_FORMAT,
                         marking_start.ticks(), compaction_start.ticks(),
                         collection_exit.ticks());

  AdaptiveSizePolicyOutput::print(size_policy, heap->total_collections());

  _gc_timer.register_gc_end();

  _gc_tracer.report_dense_prefix(dense_prefix(old_space_id));
  _gc_tracer.report_gc_end(_gc_timer.gc_end(), _gc_timer.time_partitions());

  return true;
}
```

```cpp

// This method contains no policy. You should probably
// be calling invoke() instead.
bool PSScavenge::invoke_no_policy() {
  assert(SafepointSynchronize::is_at_safepoint(), "should be at safepoint");
  assert(Thread::current() == (Thread*)VMThread::vm_thread(), "should be in vm thread");

  _gc_timer.register_gc_start();

  TimeStamp scavenge_entry;
  TimeStamp scavenge_midpoint;
  TimeStamp scavenge_exit;

  scavenge_entry.update();

  if (GCLocker::check_active_before_gc()) {
    return false;
  }

  ParallelScavengeHeap* heap = ParallelScavengeHeap::heap();
  GCCause::Cause gc_cause = heap->gc_cause();

  // Check for potential problems.
  if (!should_attempt_scavenge()) {
    return false;
  }

  GCIdMark gc_id_mark;
  _gc_tracer.report_gc_start(heap->gc_cause(), _gc_timer.gc_start());

  bool promotion_failure_occurred = false;

  PSYoungGen* young_gen = heap->young_gen();
  PSOldGen* old_gen = heap->old_gen();
  PSAdaptiveSizePolicy* size_policy = heap->size_policy();

  heap->increment_total_collections();

  if (AdaptiveSizePolicy::should_update_eden_stats(gc_cause)) {
    // Gather the feedback data for eden occupancy.
    young_gen->eden_space()->accumulate_statistics();
  }

  heap->print_heap_before_gc();
  heap->trace_heap_before_gc(&_gc_tracer);

  assert(!NeverTenure || _tenuring_threshold == markWord::max_age + 1, "Sanity");
  assert(!AlwaysTenure || _tenuring_threshold == 0, "Sanity");

  // Fill in TLABs
  heap->ensure_parsability(true);  // retire TLABs

  if (VerifyBeforeGC && heap->total_collections() >= VerifyGCStartAt) {
    Universe::verify("Before GC");
  }

  {
    ResourceMark rm;

    GCTraceCPUTime tcpu;
    GCTraceTime(Info, gc) tm("Pause Young", NULL, gc_cause, true);
    TraceCollectorStats tcs(counters());
    TraceMemoryManagerStats tms(heap->young_gc_manager(), gc_cause);

    if (log_is_enabled(Debug, gc, heap, exit)) {
      accumulated_time()->start();
    }

    // Let the size policy know we're starting
    size_policy->minor_collection_begin();

    // Verify the object start arrays.
    if (VerifyObjectStartArray &&
        VerifyBeforeGC) {
      old_gen->verify_object_start_array();
    }

    // Verify no unmarked old->young roots
    if (VerifyRememberedSets) {
      heap->card_table()->verify_all_young_refs_imprecise();
    }

    assert(young_gen->to_space()->is_empty(),
           "Attempt to scavenge with live objects in to_space");
    young_gen->to_space()->clear(SpaceDecorator::Mangle);

    save_to_space_top_before_gc();

    #if COMPILER2_OR_JVMCI
    DerivedPointerTable::clear();
    #endif

    reference_processor()->start_discovery(false /* always_clear */);

    const PreGenGCValues pre_gc_values = heap->get_pre_gc_values();

    // Reset our survivor overflow.
    set_survivor_overflow(false);

    // We need to save the old top values before
    // creating the promotion_manager. We pass the top
    // values to the card_table, to prevent it from
    // straying into the promotion labs.
    HeapWord* old_top = old_gen->object_space()->top();

    const uint active_workers =
      WorkerPolicy::calc_active_workers(ParallelScavengeHeap::heap()->workers().max_workers(),
                                        ParallelScavengeHeap::heap()->workers().active_workers(),
                                        Threads::number_of_non_daemon_threads());
    ParallelScavengeHeap::heap()->workers().set_active_workers(active_workers);

    PSPromotionManager::pre_scavenge();

    // We'll use the promotion manager again later.
    PSPromotionManager* promotion_manager = PSPromotionManager::vm_thread_promotion_manager();
    {
      GCTraceTime(Debug, gc, phases) tm("Scavenge", &_gc_timer);

      ScavengeRootsTask task(old_gen, old_top, active_workers, old_gen->object_space()->is_empty());
      ParallelScavengeHeap::heap()->workers().run_task(&task);
    }

    scavenge_midpoint.update();

    // Process reference objects discovered during scavenge
    {
      GCTraceTime(Debug, gc, phases) tm("Reference Processing", &_gc_timer);

      reference_processor()->set_active_mt_degree(active_workers);
      ReferenceProcessorStats stats;
      ReferenceProcessorPhaseTimes pt(&_gc_timer, reference_processor()->max_num_queues());

      ParallelScavengeRefProcProxyTask task(reference_processor()->max_num_queues());
      stats = reference_processor()->process_discovered_references(task, pt);

      _gc_tracer.report_gc_reference_stats(stats);
      pt.print_all_references();
    }

    assert(promotion_manager->stacks_empty(),"stacks should be empty at this point");

    {
      GCTraceTime(Debug, gc, phases) tm("Weak Processing", &_gc_timer);
      PSAdjustWeakRootsClosure root_closure;
      WeakProcessor::weak_oops_do(&ParallelScavengeHeap::heap()->workers(), &_is_alive_closure, &root_closure, 1);
    }

    // Verify that usage of root_closure didn't copy any objects.
    assert(promotion_manager->stacks_empty(),"stacks should be empty at this point");

    // Finally, flush the promotion_manager's labs, and deallocate its stacks.
    promotion_failure_occurred = PSPromotionManager::post_scavenge(_gc_tracer);
    if (promotion_failure_occurred) {
      clean_up_failed_promotion();
      log_info(gc, promotion)("Promotion failed");
    }

    _gc_tracer.report_tenuring_threshold(tenuring_threshold());

    // Let the size policy know we're done.  Note that we count promotion
    // failure cleanup time as part of the collection (otherwise, we're
    // implicitly saying it's mutator time).
    size_policy->minor_collection_end(gc_cause);

    if (!promotion_failure_occurred) {
      // Swap the survivor spaces.
      young_gen->eden_space()->clear(SpaceDecorator::Mangle);
      young_gen->from_space()->clear(SpaceDecorator::Mangle);
      young_gen->swap_spaces();

      size_t survived = young_gen->from_space()->used_in_bytes();
      size_t promoted = old_gen->used_in_bytes() - pre_gc_values.old_gen_used();
      size_policy->update_averages(_survivor_overflow, survived, promoted);

      // A successful scavenge should restart the GC time limit count which is
      // for full GC's.
      size_policy->reset_gc_overhead_limit_count();
      if (UseAdaptiveSizePolicy) {
        // Calculate the new survivor size and tenuring threshold

        log_debug(gc, ergo)("AdaptiveSizeStart:  collection: %d ", heap->total_collections());
        log_trace(gc, ergo)("old_gen_capacity: " SIZE_FORMAT " young_gen_capacity: " SIZE_FORMAT,
                            old_gen->capacity_in_bytes(), young_gen->capacity_in_bytes());

        if (UsePerfData) {
          PSGCAdaptivePolicyCounters* counters = heap->gc_policy_counters();
          counters->update_old_eden_size(
            size_policy->calculated_eden_size_in_bytes());
          counters->update_old_promo_size(
            size_policy->calculated_promo_size_in_bytes());
          counters->update_old_capacity(old_gen->capacity_in_bytes());
          counters->update_young_capacity(young_gen->capacity_in_bytes());
          counters->update_survived(survived);
          counters->update_promoted(promoted);
          counters->update_survivor_overflowed(_survivor_overflow);
        }

        size_t max_young_size = young_gen->max_gen_size();

        // Deciding a free ratio in the young generation is tricky, so if
        // MinHeapFreeRatio or MaxHeapFreeRatio are in use (implicating
        // that the old generation size may have been limited because of them) we
        // should then limit our young generation size using NewRatio to have it
        // follow the old generation size.
        if (MinHeapFreeRatio != 0 || MaxHeapFreeRatio != 100) {
          max_young_size = MIN2(old_gen->capacity_in_bytes() / NewRatio,
                                young_gen->max_gen_size());
        }

        size_t survivor_limit =
          size_policy->max_survivor_size(max_young_size);
        _tenuring_threshold =
          size_policy->compute_survivor_space_size_and_threshold(
                                                           _survivor_overflow,
                                                           _tenuring_threshold,
                                                           survivor_limit);

       log_debug(gc, age)("Desired survivor size " SIZE_FORMAT " bytes, new threshold %u (max threshold " UINTX_FORMAT ")",
                          size_policy->calculated_survivor_size_in_bytes(),
                          _tenuring_threshold, MaxTenuringThreshold);

        if (UsePerfData) {
          PSGCAdaptivePolicyCounters* counters = heap->gc_policy_counters();
          counters->update_tenuring_threshold(_tenuring_threshold);
          counters->update_survivor_size_counters();
        }

        // Do call at minor collections?
        // Don't check if the size_policy is ready at this
        // level.  Let the size_policy check that internally.
        if (UseAdaptiveGenerationSizePolicyAtMinorCollection &&
            AdaptiveSizePolicy::should_update_eden_stats(gc_cause)) {
          // Calculate optimal free space amounts
          assert(young_gen->max_gen_size() >
                 young_gen->from_space()->capacity_in_bytes() +
                 young_gen->to_space()->capacity_in_bytes(),
                 "Sizes of space in young gen are out-of-bounds");

          size_t young_live = young_gen->used_in_bytes();
          size_t eden_live = young_gen->eden_space()->used_in_bytes();
          size_t cur_eden = young_gen->eden_space()->capacity_in_bytes();
          size_t max_old_gen_size = old_gen->max_gen_size();
          size_t max_eden_size = max_young_size -
            young_gen->from_space()->capacity_in_bytes() -
            young_gen->to_space()->capacity_in_bytes();

          // Used for diagnostics
          size_policy->clear_generation_free_space_flags();

          size_policy->compute_eden_space_size(young_live,
                                               eden_live,
                                               cur_eden,
                                               max_eden_size,
                                               false /* not full gc*/);

          size_policy->check_gc_overhead_limit(eden_live,
                                               max_old_gen_size,
                                               max_eden_size,
                                               false /* not full gc*/,
                                               gc_cause,
                                               heap->soft_ref_policy());

          size_policy->decay_supplemental_growth(false /* not full gc*/);
        }
        // Resize the young generation at every collection
        // even if new sizes have not been calculated.  This is
        // to allow resizes that may have been inhibited by the
        // relative location of the "to" and "from" spaces.

        // Resizing the old gen at young collections can cause increases
        // that don't feed back to the generation sizing policy until
        // a full collection.  Don't resize the old gen here.

        heap->resize_young_gen(size_policy->calculated_eden_size_in_bytes(),
                        size_policy->calculated_survivor_size_in_bytes());

        log_debug(gc, ergo)("AdaptiveSizeStop: collection: %d ", heap->total_collections());
      }

      // Update the structure of the eden. With NUMA-eden CPU hotplugging or offlining can
      // cause the change of the heap layout. Make sure eden is reshaped if that's the case.
      // Also update() will case adaptive NUMA chunk resizing.
      assert(young_gen->eden_space()->is_empty(), "eden space should be empty now");
      young_gen->eden_space()->update();

      heap->gc_policy_counters()->update_counters();

      heap->resize_all_tlabs();

      assert(young_gen->to_space()->is_empty(), "to space should be empty now");
    }

    #if COMPILER2_OR_JVMCI
    DerivedPointerTable::update_pointers();
    #endif

    // Re-verify object start arrays
    if (VerifyObjectStartArray &&
        VerifyAfterGC) {
      old_gen->verify_object_start_array();
    }

    // Verify all old -> young cards are now precise
    if (VerifyRememberedSets) {
      // Precise verification will give false positives. Until this is fixed,
      // use imprecise verification.
      // heap->card_table()->verify_all_young_refs_precise();
      heap->card_table()->verify_all_young_refs_imprecise();
    }

    if (log_is_enabled(Debug, gc, heap, exit)) {
      accumulated_time()->stop();
    }

    heap->print_heap_change(pre_gc_values);

    // Track memory usage and detect low memory
    MemoryService::track_memory_usage();
    heap->update_counters();
  }

  if (VerifyAfterGC && heap->total_collections() >= VerifyGCStartAt) {
    Universe::verify("After GC");
  }

  heap->print_heap_after_gc();
  heap->trace_heap_after_gc(&_gc_tracer);

  scavenge_exit.update();

  log_debug(gc, task, time)("VM-Thread " JLONG_FORMAT " " JLONG_FORMAT " " JLONG_FORMAT,
                            scavenge_entry.ticks(), scavenge_midpoint.ticks(),
                            scavenge_exit.ticks());

  AdaptiveSizePolicyOutput::print(size_policy, heap->total_collections());

  _gc_timer.register_gc_end();

  _gc_tracer.report_gc_end(_gc_timer.gc_end(), _gc_timer.time_partitions());

  return !promotion_failure_occurred;
}
```

## References

1. [Optimizing best-of-2 work stealing queue selection](https://bugs.openjdk.org/browse/JDK-8205921)
2. [Characterizing and Optimizing Hotspot Parallel Garbage Collection on Multicore Systems](https://ranger.uta.edu/~jrao/papers/EuroSys18.pdf)
3. [Understanding and improving JVM GC work stealing at the data center scale](https://dl.acm.org/doi/pdf/10.1145/3241624.2926706)