## Object Allocation

```cpp
zaddress ZObjectAllocator::alloc_object(size_t size, ZAllocationFlags flags) {
  if (size <= ZObjectSizeLimitSmall) {
    // Small
    return alloc_small_object(size, flags);
  } else if (size <= ZObjectSizeLimitMedium) {
    // Medium
    return alloc_medium_object(size, flags);
  } else {
    // Large
    return alloc_large_object(size, flags);
  }
}
```

Small 对象分配走 shared page 路径：

```cpp
zaddress ZObjectAllocator::alloc_small_object(size_t size, ZAllocationFlags flags) {
  return alloc_object_in_shared_page(shared_small_page_addr(), ZPageType::small, ZPageSizeSmall, size, flags);
}

zaddress ZObjectAllocator::alloc_object_in_shared_page(ZPage** shared_page,
                                                       ZPageType page_type,
                                                       size_t page_size,
                                                       size_t size,
                                                       ZAllocationFlags flags) {
  zaddress addr = zaddress::null;
  ZPage* page = Atomic::load_acquire(shared_page);

  if (page != nullptr) {
    addr = page->alloc_object_atomic(size);
  }

  if (is_null(addr)) {
    // Allocate new page
    ZPage* const new_page = alloc_page(page_type, page_size, flags);
    if (new_page != nullptr) {
      // Allocate object before installing the new page
      addr = new_page->alloc_object(size);

    retry:
      // Install new page
      ZPage* const prev_page = Atomic::cmpxchg(shared_page, page, new_page);
      if (prev_page != page) {
        if (prev_page == nullptr) {
          // Previous page was retired, retry installing the new page
          page = prev_page;
          goto retry;
        }

        // Another page already installed, try allocation there first
        const zaddress prev_addr = prev_page->alloc_object_atomic(size);
        if (is_null(prev_addr)) {
          // Allocation failed, retry installing the new page
          page = prev_page;
          goto retry;
        }

        // Allocation succeeded in already installed page
        addr = prev_addr;

        // Undo new page allocation
        undo_alloc_page(new_page);
      }
    }
  }

  return addr;
}
```

- 在 page 中分配，如果成功则返回
- 如果失败，则调用 `alloc_page` 函数分配新 page
- JVM 参数 `-XX:+ZStallOnOutOfMemory`，控制空间不足时是否同步等待 GC 完成；`false` 表示立即抛出 OOM，默认为 `true`

大对象分配略有不同：对象 size 按 2 MB 对齐，分配专用 large page，在 large page 上分配对象。

```cpp
zaddress ZObjectAllocator::alloc_large_object(size_t size, ZAllocationFlags flags) {
  zaddress addr = zaddress::null;

  // Allocate new large page
  const size_t page_size = align_up(size, ZGranuleSize);
  ZPage* const page = alloc_page(ZPageType::large, page_size, flags);
  if (page != nullptr) {
    // Allocate the object
    addr = page->alloc_object(size);
  }

  return addr;
}
```

`alloc_page` 的调用链：`ZObjectAllocator::alloc_page` → `ZHeap::alloc_page` → `ZPageAllocator::alloc_page`，最终从 page cache 或物理内存管理器获取 page，并加入 page table。

```cpp
ZPage* ZObjectAllocator::alloc_page(ZPageType type, size_t size, ZAllocationFlags flags) {
  ZPage* const page = ZHeap::heap()->alloc_page(type, size, flags, _age);
  if (page != nullptr) {
    // Increment used bytes
    Atomic::add(_used.addr(), size);
  }

  return page;
}
```

```cpp
ZPage* ZHeap::alloc_page(ZPageType type, size_t size, ZAllocationFlags flags, ZPageAge age) {
  ZPage* const page = _page_allocator.alloc_page(type, size, flags, age);
  if (page != nullptr) {
    // Insert page table entry
    _page_table.insert(page);
  }

  return page;
}
```

```cpp
ZPage* ZPageAllocator::alloc_page(ZPageType type, size_t size, ZAllocationFlags flags, ZPageAge age) {
  EventZPageAllocation event;

retry:
  ZPageAllocation allocation(type, size, flags);

  // Allocate one or more pages from the page cache. If the allocation
  // succeeds but the returned pages don't cover the complete allocation,
  // then finalize phase is allowed to allocate the remaining memory
  // directly from the physical memory manager. Note that this call might
  // block in a safepoint if the non-blocking flag is not set.
  if (!alloc_page_or_stall(&allocation)) {
    // Out of memory
    return nullptr;
  }

  ZPage* const page = alloc_page_finalize(&allocation);
  if (page == nullptr) {
    // Failed to commit or map. Clean up and retry, in the hope that
    // we can still allocate by flushing the page cache (more aggressively).
    free_pages_alloc_failed(&allocation);
    goto retry;
  }

  // The generation's used is tracked here when the page is handed out
  // to the allocating thread. The overall heap "used" is tracked in
  // the lower-level allocation code.
  const ZGenerationId id = age == ZPageAge::old ? ZGenerationId::old : ZGenerationId::young;
  increase_used_generation(id, size);

  // Reset page. This updates the page's sequence number and must
  // be done after we potentially blocked in a safepoint (stalled)
  // where the global sequence number was updated.
  page->reset(age, ZPageResetType::Allocation);

  // Update allocation statistics. Exclude gc relocations to avoid
  // artificial inflation of the allocation rate during relocation.
  if (!flags.gc_relocation() && is_init_completed()) {
    // Note that there are two allocation rate counters, which have
    // different purposes and are sampled at different frequencies.
    ZStatInc(ZCounterMutatorAllocationRate, size);
    ZStatMutatorAllocRate::sample_allocation(size);
  }

  // Send event
  event.commit((u8)type, size, allocation.flushed(), allocation.committed(),
               page->physical_memory().nsegments(), flags.non_blocking());

  return page;
}
```

`alloc_page_or_stall` 在 page cache / 容量不足时会 stall（阻塞等待 GC），而 `alloc_page_common_inner` 先尝试 page cache、再尝试扩堆、最后 flush cache：

```cpp
bool ZPageAllocator::alloc_page_or_stall(ZPageAllocation* allocation) {
  {
    ZLocker<ZLock> locker(&_lock);

    if (alloc_page_common(allocation)) {
      // Success
      return true;
    }

    // Failed
    if (allocation->flags().non_blocking()) {
      // Don't stall
      return false;
    }

    // Enqueue allocation request
    _stalled.insert_last(allocation);
  }

  // Stall
  return alloc_page_stall(allocation);
}
```

```cpp
bool ZPageAllocator::alloc_page_common(ZPageAllocation* allocation) {
  const ZPageType type = allocation->type();
  const size_t size = allocation->size();
  const ZAllocationFlags flags = allocation->flags();
  ZList<ZPage>* const pages = allocation->pages();

  if (!alloc_page_common_inner(type, size, pages)) {
    // Out of memory
    return false;
  }

  // Updated used statistics
  increase_used(size);

  // Success
  return true;
}

bool ZPageAllocator::alloc_page_common_inner(ZPageType type, size_t size, ZList<ZPage>* pages) {
  if (!is_alloc_allowed(size)) {
    // Out of memory
    return false;
  }

  // Try allocate from the page cache
  ZPage* const page = _cache.alloc_page(type, size);
  if (page != nullptr) {
    // Success
    pages->insert_last(page);
    return true;
  }

  // Try increase capacity
  const size_t increased = increase_capacity(size);
  if (increased < size) {
    // Could not increase capacity enough to satisfy the allocation
    // completely. Flush the page cache to satisfy the remainder.
    const size_t remaining = size - increased;
    _cache.flush_for_allocation(remaining, pages);
  }

  // Success
  return true;
}
```

## Links

- [ZGC Hub](/docs/CS/Java/JDK/JVM/GC/ZGC.md)
- [Collection Cycle](/docs/CS/Java/JDK/JVM/GC/ZGC/CollectionCycle.md)
- [TLAB](/docs/CS/Java/JDK/JVM/TLAB.md)

## References

1. [OpenJDK16 ZGC 详细源码分析 - heapdump.cn](https://heapdump.cn/article/3473288)
2. [ZGC source: zObjectAllocator.cpp](https://github.com/openjdk/jdk/blob/master/src/hotspot/share/gc/z/zObjectAllocator.cpp)
3. [ZGC source: zPageAllocator.cpp](https://github.com/openjdk/jdk/blob/master/src/hotspot/share/gc/z/zPageAllocator.cpp)
