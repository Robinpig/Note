## Introduction

Serial收集器是单线程的串行收集器，其源代码实现相对其他收集器来说比较简单
可以指定-XX:+UseSerialGC选项使用Serial（年轻代）+Serial Old（老年代）组合进行垃圾回收

Serial收集器只负责年轻代的垃圾回收，触发YGC时一般都是由此收集器负责垃圾回收
Serial Old收集器也是一个单线程收集器，使用“标记-整理”算法
Serial Old收集器不但会回收老年代的内存垃圾，也会回收年轻代的内存垃圾，因此一般触发FGC时都是由此收集器负责回收的


for Serial and ParNew
```cpp
    // gc-globals.hpp
  product(size_t, PretenureSizeThreshold, 0,                                \
          "Maximum size in bytes of objects allocated in DefNew "           \
          "generation; zero means no maximum")                              \
          range(0, max_uintx)                                               \
```


为了支持高频率的新生代回收，HotSpot VM使用了一种叫作卡表（Card Table）的数据结构。卡表是一个字节的集合，每一个字节可以用来表示老年代某一区域中的所有对象是否持有新生代对象的引用。我们可以根据卡表将堆空间划分为一系列2次幂大小的卡页（Card Page），卡表用于标记卡页的状态，每个卡表项对应一个卡页，HotSpot VM的卡页（Card Page）大小为512字节，卡表为一个简单的字节数组，即卡表的每个标记项为1个字节。
当老年代中的某个卡页持有了新生代对象的引用时，HotSpot VM就把这个卡页对应的卡表项标记为dirty。这样在进行YGC时，可以不用全量扫描所有老年代对象或不用全量标记所有活跃对象来确定对年轻代对象的引用关系，只需要扫描卡表项为dirty的对应卡页，而卡表项为非dirty的区域一定不包含对新生代的引用。这样可以提高扫描效率，减少YGC的停顿时间。

HotSpot VM使用CardTable类实现卡表的功能，其定义如下



```cpp
class CardTable: public CHeapObj<mtGC> {
  friend class VMStructs;
public:
  typedef uint8_t CardValue;

  // All code generators assume that the size of a card table entry is one byte.
  // They need to be updated to reflect any change to this.
  // This code can typically be found by searching for the byte_map_base() method.
  STATIC_ASSERT(sizeof(CardValue) == 1);

protected:
  // The declaration order of these const fields is important; see the
  // constructor before changing.
  const MemRegion _whole_heap;       // the region covered by the card table
  const size_t    _page_size;        // page size used when mapping _byte_map
  size_t          _byte_map_size;    // in bytes
  CardValue*      _byte_map;         // the card marking array
  CardValue*      _byte_map_base;

  // Some barrier sets create tables whose elements correspond to parts of
  // the heap; the CardTableBarrierSet is an example.  Such barrier sets will
  // normally reserve space for such tables, and commit parts of the table
  // "covering" parts of the heap that are committed. At most one covered
  // region per generation is needed.
  static constexpr int max_covered_regions = 2;

  // The covered regions should be in address order.
  MemRegion _covered[max_covered_regions];

  // The last card is a guard card; never committed.
  MemRegion _guard_region;

  inline size_t compute_byte_map_size(size_t num_bytes);
};
```


This RemSet uses a card table both as shared data structure for a mod ref barrier set and for the rem set information.



```cpp
// 

class CardTableRS : public CardTable {
  friend class VMStructs;
  // Below are private classes used in impl.
  friend class VerifyCTSpaceClosure;
  friend class ClearNoncleanCardWrapper;

  void verify_space(Space* s, HeapWord* gen_start);

public:
  CardTableRS(MemRegion whole_heap);

  void younger_refs_in_space_iterate(TenuredSpace* sp, OopIterateClosure* cl);

  virtual void verify_used_region_at_save_marks(Space* sp) const NOT_DEBUG_RETURN;

  void inline_write_ref_field_gc(void* field) {
    CardValue* byte = byte_for(field);
    *byte = dirty_card_val();
  }

  bool is_aligned(HeapWord* addr) {
    return is_card_aligned(addr);
  }

  void verify();

  // Update old gen cards to maintain old-to-young-pointer invariant: Clear
  // the old generation card table completely if the young generation had been
  // completely evacuated, otherwise dirties the whole old generation to
  // conservatively not loose any old-to-young pointer.
  void maintain_old_to_young_invariant(Generation* old_gen, bool is_young_gen_empty);

  // Iterate over the portion of the card-table which covers the given
  // region mr in the given space and apply cl to any dirty sub-regions
  // of mr. Clears the dirty cards as they are processed.
  void non_clean_card_iterate(TenuredSpace* sp,
                              MemRegion mr,
                              OopIterateClosure* cl,
                              CardTableRS* ct);

  bool is_in_young(const void* p) const override;
};
```


```cpp
CardTableRS::CardTableRS(MemRegion whole_heap) :
  CardTable(whole_heap) { }

CardTable::CardTable(MemRegion whole_heap) :
  _whole_heap(whole_heap),
  _page_size(os::vm_page_size()),
  _byte_map_size(0),
  _byte_map(nullptr),
  _byte_map_base(nullptr),
  _guard_region()
{
  assert((uintptr_t(_whole_heap.start())  & (_card_size - 1))  == 0, "heap must start at card boundary");
  assert((uintptr_t(_whole_heap.end()) & (_card_size - 1))  == 0, "heap must end at card boundary");
}
```

卡表只能粗粒度地表示某个对象中引用域地址所在的卡页，并不能通过卡表完成卡页中引用域的遍历，因此在实际情况下只能描述整个卡页中包含的对象，然后扫描对象中的引用域


One implementation of "BlockOffsetTable," the BlockOffsetArray, divides the covered region into "N"-word subregions (where "N" = 2^"LogN".  An array with an entry for each such subregion indicates how far back one must go to find the start of the chunk that includes the first word of the subregion.

Each BlockOffsetArray is owned by a Space.  However, the actual array may be shared by several BlockOffsetArrays; this is useful when a single resizable area (such as a generation) is divided up into several spaces in which contiguous allocation takes place.  (Consider, for example, the garbage-first generation.)

```cpp
class BlockOffsetSharedArray: public CHeapObj<mtGC> {
 private:
  bool _init_to_zero;

  // The reserved region covered by the shared array.
  MemRegion _reserved;

  // End of the current committed region.
  HeapWord* _end;

  // Array for keeping offsets for retrieving object start fast given an
  // address.
  VirtualSpace _vs;
  u_char* _offset_array;          // byte array keeping backwards offsets

  void fill_range(size_t start, size_t num_cards, u_char offset) {
    void* start_ptr = &_offset_array[start];
    // If collector is concurrent, special handling may be needed.
    G1GC_ONLY(assert(!UseG1GC, "Shouldn't be here when using G1");)
    memset(start_ptr, offset, num_cards);
  }
};
```



## New collect

1. collection_attempt_is_safe
2. young_process_roots

```cpp
void DefNewGeneration::collect(bool   full,
                               bool   clear_all_soft_refs,
                               size_t size,
                               bool   is_tlab) {
...
  _old_gen = heap->old_gen();
```
If the next generation is too full to accommodate promotion from this generation, pass on collection;
let the next generation do it.
```cpp
  if (!collection_attempt_is_safe()) {
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
```
DefNew needs to run with n_threads == 0(STW), to make sure the serial version of the card table scanning code is used.

See: CardTableRS::non_clean_card_iterate_possibly_parallel.
```cpp
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
```
Swap the survivor spaces.
```cpp
  if (!_promotion_failed) {
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

#### collection_attempt_is_safe

```cpp
inline void FastScanClosure<Derived>::do_oop_work(T* p) {
  T heap_oop = RawAccess<>::oop_load(p);
  // Should we copy the obj?
  if (!CompressedOops::is_null(heap_oop)) {
    oop obj = CompressedOops::decode_not_null(heap_oop);
    if (cast_from_oop<HeapWord*>(obj) < _young_gen_end) {
      assert(!_young_gen->to()->is_in_reserved(obj), "Scanning field twice?");
      oop new_obj = obj->is_forwarded() ? obj->forwardee()
                                        : _young_gen->copy_to_survivor_space(obj);
      RawAccess<IS_NOT_NULL>::oop_store(p, new_obj);

      static_cast<Derived*>(this)->barrier(p);
    }
  }
}
```

```cpp
bool DefNewGeneration::collection_attempt_is_safe() {
  if (!to()->is_empty()) {
    log_trace(gc)(":: to is not empty ::");
    return false;
  }
  if (_old_gen == NULL) {
    GenCollectedHeap* gch = GenCollectedHeap::heap();
    _old_gen = gch->old_gen();
  }
  return _old_gen->promotion_attempt_is_safe(used());
}
```

#### copy_to_survivor_space

```cpp
// share/gc/serial/defNewGeneration.cpp
oop DefNewGeneration::copy_to_survivor_space(oop old) {
  assert(is_in_reserved(old) && !old->is_forwarded(),
         "shouldn't be scavenging this oop");
  size_t s = old->size();
  oop obj = NULL;
```
Try allocating obj in to-space (unless too old)
```cpp
  if (old->age() < tenuring_threshold()) {
    obj = cast_to_oop(to()->allocate(s));
  }

  bool new_obj_is_tenured = false;
```
try allocating obj tenured
```cpp
  if (obj == NULL) {
    obj = _old_gen->promote(old, s);
    if (obj == NULL) {
      handle_promotion_failure(old);
      return old;
    }
    new_obj_is_tenured = true;
  } 
```
Copy obj
```cpp
  else {
    // Prefetch beyond obj
    const intx interval = PrefetchCopyIntervalInBytes;
    Prefetch::write(obj, interval);

    Copy::aligned_disjoint_words(cast_from_oop<HeapWord*>(old), cast_from_oop<HeapWord*>(obj), s);
```
Increment age if obj still in new generation
```cpp
    obj->incr_age();
    age_table()->add(obj, s);
  }
```
Done, insert forward pointer to obj in this header
```cpp
  old->forward_to(obj);

  if (SerialStringDedup::is_candidate_from_evacuation(obj, new_obj_is_tenured)) {
    // Record old; request adds a new weak reference, which reference
    // processing expects to refer to a from-space object.
    _string_dedup_requests.add(old);
  }
  return obj;
}
```


#### collection_attempt_is_safe
Handle Promotion

```cpp
// tenuredGeneration.hpp
bool TenuredGeneration::promotion_attempt_is_safe(size_t max_promotion_in_bytes) const {
  size_t available = max_contiguous_available();
  size_t av_promo  = (size_t)gc_stats()->avg_promoted()->padded_average();
  bool   res = (available >= av_promo) || (available >= max_promotion_in_bytes);

  log_trace(gc)("Tenured: promo attempt is%s safe: available(" SIZE_FORMAT ") %s av_promo(" SIZE_FORMAT "), max_promo(" SIZE_FORMAT ")",
    res? "":" not", available, res? ">=":"<", av_promo, max_promotion_in_bytes);

  return res;
}
```

## Tenured collect

```cpp

void TenuredGeneration::collect(bool   full,
                                bool   clear_all_soft_refs,
                                size_t size,
                                bool   is_tlab) {
  GenCollectedHeap* gch = GenCollectedHeap::heap();

  // Temporarily expand the span of our ref processor, so
  // refs discovery is over the entire heap, not just this generation
  ReferenceProcessorSpanMutator
    x(ref_processor(), gch->reserved_region());

  STWGCTimer* gc_timer = GenMarkSweep::gc_timer();
  gc_timer->register_gc_start();

  SerialOldTracer* gc_tracer = GenMarkSweep::gc_tracer();
  gc_tracer->report_gc_start(gch->gc_cause(), gc_timer->gc_start());

  gch->pre_full_gc_dump(gc_timer);
```
Invoke [Full collect](/docs/CS/Java/JDK/JVM/GC/Serial.md.md?id=Full-collect)
```cpp
  GenMarkSweep::invoke_at_safepoint(ref_processor(), clear_all_soft_refs);

  gch->post_full_gc_dump(gc_timer);

  gc_timer->register_gc_end();

  gc_tracer->report_gc_end(gc_timer->gc_end(), gc_timer->time_partitions());
}
```

## Full collect

```cpp
void GenMarkSweep::invoke_at_safepoint(ReferenceProcessor* rp, bool clear_all_softrefs) {
  assert(SafepointSynchronize::is_at_safepoint(), "must be at a safepoint");

  GenCollectedHeap* gch = GenCollectedHeap::heap();
  #ifdef ASSERT
  if (gch->soft_ref_policy()->should_clear_all_soft_refs()) {
    assert(clear_all_softrefs, "Policy should have been checked earlier");
  }
  #endif

  // hook up weak ref data so it can be used during Mark-Sweep
  assert(ref_processor() == NULL, "no stomping");
  assert(rp != NULL, "should be non-NULL");
  set_ref_processor(rp);

  gch->trace_heap_before_gc(_gc_tracer);

  // Increment the invocation count
  _total_invocations++;

  // Capture used regions for each generation that will be
  // subject to collection, so that card table adjustments can
  // be made intelligently (see clear / invalidate further below).
  gch->save_used_regions();

  allocate_stacks();

  mark_sweep_phase1(clear_all_softrefs);

  mark_sweep_phase2();

  // Don't add any more derived pointers during phase3
  #if COMPILER2_OR_JVMCI
  assert(DerivedPointerTable::is_active(), "Sanity");
  DerivedPointerTable::set_active(false);
  #endif

  mark_sweep_phase3();

  mark_sweep_phase4();

  restore_marks();

  // Set saved marks for allocation profiler (and other things? -- dld)
  // (Should this be in general part?)
  gch->save_marks();

  deallocate_stacks();

  MarkSweep::_string_dedup_requests->flush();

  // If compaction completely evacuated the young generation then we
  // can clear the card table.  Otherwise, we must invalidate
  // it (consider all cards dirty).  In the future, we might consider doing
  // compaction within generations only, and doing card-table sliding.
  CardTableRS* rs = gch->rem_set();
  Generation* old_gen = gch->old_gen();

  // Clear/invalidate below make use of the "prev_used_regions" saved earlier.
  if (gch->young_gen()->used() == 0) {
    // We've evacuated the young generation.
    rs->clear_into_younger(old_gen);
  } else {
    // Invalidate the cards corresponding to the currently used
    // region and clear those corresponding to the evacuated region.
    rs->invalidate_or_clear(old_gen);
  }

  gch->prune_scavengable_nmethods();

  // refs processing: clean slate
  set_ref_processor(NULL);

  // Update heap occupancy information which is used as
  // input to soft ref clearing policy at the next gc.
  Universe::heap()->update_capacity_and_used_at_gc();

  // Signal that we have completed a visit to all live objects.
  Universe::heap()->record_whole_heap_examined_timestamp();

  gch->trace_heap_after_gc(_gc_tracer);
}
```

### follow_root

```cpp

template <class T> inline void MarkSweep::follow_root(T* p) {
  assert(!Universe::heap()->is_in(p),
         "roots shouldn't be things within the heap");
  T heap_oop = RawAccess<>::oop_load(p);
  if (!CompressedOops::is_null(heap_oop)) {
    oop obj = CompressedOops::decode_not_null(heap_oop);
    if (!obj->mark().is_marked()) {
      mark_object(obj);
      follow_object(obj);
    }
  }
  follow_stack();
}
```

#### follow_stack
```cpp

void MarkSweep::follow_stack() {
  do {
    while (!_marking_stack.is_empty()) {
      oop obj = _marking_stack.pop();
      assert (obj->is_gc_marked(), "p must be marked");
      follow_object(obj);
    }
    // Process ObjArrays one at a time to avoid marking stack bloat.
    if (!_objarray_stack.is_empty()) {
      ObjArrayTask task = _objarray_stack.pop();
      follow_array_chunk(objArrayOop(task.obj()), task.index());
    }
  } while (!_marking_stack.is_empty() || !_objarray_stack.is_empty());
}
```

#### follow_object

```cpp

inline void MarkSweep::follow_object(oop obj) {
  assert(obj->is_gc_marked(), "should be marked");
  if (obj->is_objArray()) {
    // Handle object arrays explicitly to allow them to
    // be split into chunks if needed.
    MarkSweep::follow_array((objArrayOop)obj);
  } else {
    obj->oop_iterate(&mark_and_push_closure);
  }
}


inline void MarkSweep::follow_array(objArrayOop array) {
  MarkSweep::follow_klass(array->klass());
  // Don't push empty arrays to avoid unnecessary work.
  if (array->length() > 0) {
    MarkSweep::push_objarray(array, 0);
  }
}
```

```cpp

void MarkSweep::push_objarray(oop obj, size_t index) {
  ObjArrayTask task(obj, index);
  assert(task.is_valid(), "bad ObjArrayTask");
  _objarray_stack.push(task);
}
```


```cpp

template <class T> inline void MarkSweep::mark_and_push(T* p) {
  T heap_oop = RawAccess<>::oop_load(p);
  if (!CompressedOops::is_null(heap_oop)) {
    oop obj = CompressedOops::decode_not_null(heap_oop);
    if (!obj->mark().is_marked()) {
      mark_object(obj);
      _marking_stack.push(obj);
    }
  }
}
```
#### mark_object
```cpp
inline void MarkSweep::mark_object(oop obj) {
  if (StringDedup::is_enabled() &&
      java_lang_String::is_instance(obj) &&
      SerialStringDedup::is_candidate_from_mark(obj)) {
    _string_dedup_requests->add(obj);
  }

  // some marks may contain information we need to preserve so we store them away
  // and overwrite the mark.  We'll restore it at the end of markSweep.
  markWord mark = obj->mark();
  obj->set_mark(markWord::prototype().set_marked());

  if (obj->mark_must_be_preserved(mark)) {
    preserve_mark(obj, mark);
  }
}
```


### mark_sweep_phase1

```cpp

void GenMarkSweep::mark_sweep_phase1(bool clear_all_softrefs) {
  // Recursively traverse all live objects and mark them
  GCTraceTime(Info, gc, phases) tm("Phase 1: Mark live objects", _gc_timer);

  GenCollectedHeap* gch = GenCollectedHeap::heap();

  // Need new claim bits before marking starts.
  ClassLoaderDataGraph::clear_claimed_marks();

  {
    StrongRootsScope srs(0);

    gch->full_process_roots(false, // not the adjust phase
                            GenCollectedHeap::SO_None,
                            ClassUnloading, // only strong roots if ClassUnloading
                                            // is enabled
                            &follow_root_closure,
                            &follow_cld_closure);
  }

  // Process reference objects found during marking
  {
    GCTraceTime(Debug, gc, phases) tm_m("Reference Processing", gc_timer());

    ReferenceProcessorPhaseTimes pt(_gc_timer, ref_processor()->max_num_queues());
    SerialGCRefProcProxyTask task(is_alive, keep_alive, follow_stack_closure);
    const ReferenceProcessorStats& stats = ref_processor()->process_discovered_references(task, pt);
    pt.print_all_references();
    gc_tracer()->report_gc_reference_stats(stats);
  }

  // This is the point where the entire marking should have completed.
  assert(_marking_stack.is_empty(), "Marking should have completed");

  {
    GCTraceTime(Debug, gc, phases) tm_m("Weak Processing", gc_timer());
    WeakProcessor::weak_oops_do(&is_alive, &do_nothing_cl);
  }

  {
    GCTraceTime(Debug, gc, phases) tm_m("Class Unloading", gc_timer());

    // Unload classes and purge the SystemDictionary.
    bool purged_class = SystemDictionary::do_unloading(gc_timer());

    // Unload nmethods.
    CodeCache::do_unloading(&is_alive, purged_class);

    // Prune dead klasses from subklass/sibling/implementor lists.
    Klass::clean_weak_klass_links(purged_class);

    // Clean JVMCI metadata handles.
    JVMCI_ONLY(JVMCI::do_unloading(purged_class));
  }

  gc_tracer()->report_object_count_after_gc(&is_alive);
}
```

### mark_sweep_phase2
```cpp

void GenMarkSweep::mark_sweep_phase2() {
  // Now all live objects are marked, compute the new object addresses.

  // It is not required that we traverse spaces in the same order in
  // phase2, phase3 and phase4, but the ValidateMarkSweep live oops
  // tracking expects us to do so. See comment under phase4.

  GenCollectedHeap* gch = GenCollectedHeap::heap();

  GCTraceTime(Info, gc, phases) tm("Phase 2: Compute new object addresses", _gc_timer);

  gch->prepare_for_compaction();
}
```


### mark_sweep_phase3


```cpp

void GenMarkSweep::mark_sweep_phase3() {
  GenCollectedHeap* gch = GenCollectedHeap::heap();

  // Adjust the pointers to reflect the new locations
  GCTraceTime(Info, gc, phases) tm("Phase 3: Adjust pointers", gc_timer());

  // Need new claim bits for the pointer adjustment tracing.
  ClassLoaderDataGraph::clear_claimed_marks();

  {
    StrongRootsScope srs(0);

    gch->full_process_roots(true,  // this is the adjust phase
                            GenCollectedHeap::SO_AllCodeCache,
                            false, // all roots
                            &adjust_pointer_closure,
                            &adjust_cld_closure);
  }

  gch->gen_process_weak_roots(&adjust_pointer_closure);

  adjust_marks();
  GenAdjustPointersClosure blk;
  gch->generation_iterate(&blk, true);
}
```

#### GenAdjustPointersClosure

```cpp
class GenAdjustPointersClosure: public GenCollectedHeap::GenClosure {
public:
  void do_generation(Generation* gen) {
    gen->adjust_pointers();
  }
};
```

### mark_sweep_phase4

```cpp

void GenMarkSweep::mark_sweep_phase4() {
  // All pointers are now adjusted, move objects accordingly

  // It is imperative that we traverse perm_gen first in phase4. All
  // classes must be allocated earlier than their instances, and traversing
  // perm_gen first makes sure that all Klass*s have moved to their new
  // location before any instance does a dispatch through it's klass!

  // The ValidateMarkSweep live oops tracking expects us to traverse spaces
  // in the same order in phase2, phase3 and phase4. We don't quite do that
  // here (perm_gen first rather than last), so we tell the validate code
  // to use a higher index (saved from phase2) when verifying perm_gen.
  GenCollectedHeap* gch = GenCollectedHeap::heap();

  GCTraceTime(Info, gc, phases) tm("Phase 4: Move objects", _gc_timer);

  GenCompactClosure blk;
  gch->generation_iterate(&blk, true);
}
```


#### GenCompactClosure
```cpp

class GenCompactClosure: public GenCollectedHeap::GenClosure {
public:
  void do_generation(Generation* gen) {
    gen->compact();
  }
};
```


## Links

- [Garbage Collection](/docs/CS/Java/JDK/JVM/GC/GC.md)