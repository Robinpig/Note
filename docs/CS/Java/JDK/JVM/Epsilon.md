## Introduction

Just allocate, do not collect garbage.



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