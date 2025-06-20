## Introduction



Go语言采用现代内存分配TCMalloc算法的思想来进行内存分配，将对象分为微小对象、小对象、大对象，使用三级管理结构mcache、mcentral、mheap用于管理、缓存加速span对象的访问和分配，使用精准的位图管理已分配的和未分配的对象及对象的大小。


内存管理一般包含三个不同的组件，分别是用户程序（Mutator）、分配器（Allocator）和收集器（Collector），当用户程序申请内存时，它会通过内存分配器申请新的内存，而分配器会负责从堆中初始化相应的内存区域



线程缓存分配（Thread-Caching Malloc，TCMalloc）是用于分配内存的的机制，它比 glibc 中的 malloc 函数还要快很多2。Go 语言的内存分配器就借鉴了 TCMalloc 的设计实现高速的内存分配，它的核心理念是使用多级缓存根据将对象根据大小分类，并按照类别实施不同的分配策略。

Go 语言的内存分配器会根据申请分配的内存大小选择不同的处理逻辑，运行时根据对象的大小将对象分成微对象、小对象和大对象三种

类别	大小
微对象	(0, 16B)
小对象	[16B, 32KB]
大对象	(32KB, +∞)

因为程序中的绝大多数对象的大小都在 32KB 以下，而申请的内存大小影响 Go 语言运行时分配内存的过程和开销，所以分别处理大对象和小对象有利于提高内存分配器的性能。
多级缓存
内存分配器不仅会区别对待大小不同的对象，还会将内存分成不同的级别分别管理，TCMalloc 和 Go 运行时分配器都会引入线程缓存（Thread Cache）、中心缓存（Central Cache）和页堆（Page Heap）三个组件分级管理内存：


线程缓存属于每一个独立的线程，它能够满足线程上绝大多数的内存分配需求，因为不涉及多线程，所以也不需要使用互斥锁来保护内存，这能够减少锁竞争带来的性能损耗。当线程缓存不能满足需求时，就会使用中心缓存作为补充解决小对象的内存分配问题；在遇到 32KB 以上的对象时，内存分配器就会选择页堆直接分配大量的内存。
这种多层级的内存分配设计与计算机操作系统中的多级缓存也有些类似，因为多数的对象都是小对象，我们可以通过线程缓存和中心缓存提供足够的内存空间，发现资源不足时就从上一级组件中获取更多的内存资源


在 Go 语言 1.10 以前的版本，堆区的内存空间都是连续的；但是在 1.11 版本，Go 团队使用稀疏的堆内存空间替代了连续的内存，解决了连续内存带来的限制以及在特殊场景下可能出现的问题

Go 语言程序的 1.10 版本在启动时会初始化整片虚拟内存区域，如下所示的三个区域 spans、bitmap 和 arena 分别预留了 512MB、16GB 以及 512GB 的内存空间，这些内存并不是真正存在的物理内存，而是虚拟内存
- spans 区域存储了指向内存管理单元 runtime.mspan 的指针，每个内存单元会管理几页的内存空间，每页大小为 8KB；
- bitmap 用于标识 arena 区域中的那些地址保存了对象，位图中的每个字节都会表示堆区中的 32 字节是否包含空闲；
- arena 区域是真正的堆区，运行时会将 8KB 看做一页，这些内存页中存储了所有在堆上初始化的对象；

对于任意一个地址，我们都可以根据 arena 的基地址计算该地址所在的页数并通过 spans 数组获得管理该片内存的管理单元 runtime.mspan，spans 数组中多个连续的位置可能对应同一个 runtime.mspan。


Go 语言在垃圾回收时会根据指针的地址判断对象是否在堆中，并通过上一段中介绍的过程找到管理该对象的 runtime.mspan。这些都建立在堆区的内存是连续的这一假设上。这种设计虽然简单并且方便，但是在 C 和 Go 混合使用时会导致程序崩溃：
1. 分配的内存地址会发生冲突，导致堆的初始化和扩容失败3；
2. 没有被预留的大块内存可能会被分配给 C 语言的二进制，导致扩容后的堆不连续4；
   线性的堆内存需要预留大块的内存空间，但是申请大块的内存空间而不使用是不切实际的，不预留内存空间却会在特殊场景下造成程序崩溃。虽然连续内存的实现比较简单，但是这些问题我们也没有办法忽略



稀疏内存是 Go 语言在 1.11 中提出的方案，使用稀疏的内存布局不仅能移除堆大小的上限，还能解决 C 和 Go 混合使用时的地址空间冲突问题。不过因为基于稀疏内存的内存管理失去了内存的连续性这一假设，这也使内存管理变得更加复杂

运行时使用二维的 runtime.heapArena 数组管理所有的内存，每个单元都会管理 64MB 的内存空间

```go
type heapArena struct {
_ sys.NotInHeap

    spans [pagesPerArena]*mspan

    pageInUse [pagesPerArena / 8]uint8

    pageMarks [pagesPerArena / 8]uint8

    pageSpecials [pagesPerArena / 8]uint8

    checkmarks *checkmarksMap

    zeroedBase uintptr
}
```

该结构体中的 bitmap 和 spans 与线性内存中的 bitmap 和 spans 区域一一对应，zeroedBase 字段指向了该结构体管理的内存的基地址。这种设计将原有的连续大内存切分成稀疏的小内存，而用于管理这些内存的元信息也被切分成了小块。
不同平台和架构的二维数组大小可能完全不同，如果我们的 Go 语言服务在 Linux 的 x86-64 架构上运行，二维数组的一维大小会是 1，而二维大小是 4,194,304，因为每一个指针占用 8 字节的内存空间，所以元信息的总大小为 32MB。由于每个 runtime.heapArena 都会管理 64MB 的内存，整个堆区最多可以管理 256TB 的内存，这比之前的 512GB 多好几个数量级

Go 语言团队在 1.11 版本中通过以下几个提交将线性内存变成稀疏内存，移除了 512GB 的内存上限以及堆区内存连续性的假设：
- runtime: use sparse mappings for the heap
- runtime: fix various contiguous bitmap assumptions
- runtime: make the heap bitmap sparse
- runtime: abstract remaining mheap.spans access
- runtime: make span map sparse
- runtime: eliminate most uses of mheap_.arena_*
- runtime: remove non-reserved heap logic
- runtime: move comment about address space sizes to malloc.go


由于内存的管理变得更加复杂，上述改动对垃圾回收稍有影响，大约会增加 1% 的垃圾回收开销，不过这也是我们为了解决已有问题必须付出的成本

Go 语言的内存分配器包含内存管理单元、线程缓存、中心缓存和页堆几个重要组件，本节将介绍这几种最重要组件对应的数据结构 runtime.mspan、runtime.mcache、runtime.mcentral 和 runtime.mheap，
所有的 Go 语言程序都会在启动时初始化如上图所示的内存布局，每一个处理器都会被分配一个线程缓存 runtime.mcache 用于处理微对象和小对象的分配，它们会持有内存管理单元 runtime.mspan。
每个类型的内存管理单元都会管理特定大小的对象，当内存管理单元中不存在空闲对象时，它们会从 runtime.mheap 持有的 134 个中心缓存 runtime.mcentral 中获取新的内存单元，中心缓存属于全局的堆结构体 runtime.mheap，它会从操作系统中申请内存。

在 amd64 的 Linux 操作系统上，runtime.mheap 会持有 4,194,304 runtime.heapArena，每一个 runtime.heapArena 都会管理 64MB 的内存，单个 Go 语言程序的内存上限也就是 256TB。



#### span


runtime.mspan 是 Go 语言内存管理的基本单元，该结构体中包含 next 和 prev 两个字段，它们分别指向了前一个和后一个 runtime.mspan：


```go
type mspan struct {
    next *mspan
    prev *mspan
    ...
}
```
串联后的上述结构体会构成如下双向链表，运行时会使用 runtime.mSpanList 存储双向链表的头结点和尾节点并在线程缓存以及中心缓存中使用



```go

// Central list of free objects of a given size.
type mcentral struct {
	_         sys.NotInHeap
	spanclass spanClass
	partial [2]spanSet // list of spans with a free object
	full    [2]spanSet // list of spans with no free objects
}
```



一个进程有多个 mcentral 管理这些 mcentral实例的是mheap的结构体实例

### mallocgc
Go 申请内存的入口函数是 `runtime.mallocgc`
```go
//go:linkname mallocgc
func mallocgc(size uintptr, typ *_type, needzero bool) unsafe.Pointer {
	if doubleCheckMalloc {
		if gcphase == _GCmarktermination {
			throw("mallocgc called with gcphase == _GCmarktermination")
		}
	}

	// Short-circuit zero-sized allocation requests.
	if size == 0 {
		return unsafe.Pointer(&zerobase)
	}

	// It's possible for any malloc to trigger sweeping, which may in
	// turn queue finalizers. Record this dynamic lock edge.
	// N.B. Compiled away if lockrank experiment is not enabled.
	lockRankMayQueueFinalizer()

	// Pre-malloc debug hooks.
	if debug.malloc {
		if x := preMallocgcDebug(size, typ); x != nil {
			return x
		}
	}

	// For ASAN, we allocate extra memory around each allocation called the "redzone."
	// These "redzones" are marked as unaddressable.
	var asanRZ uintptr
	if asanenabled {
		asanRZ = redZoneSize(size)
		size += asanRZ
	}

	// Assist the GC if needed.
	if gcBlackenEnabled != 0 {
		deductAssistCredit(size)
	}

	// Actually do the allocation.
	var x unsafe.Pointer
	var elemsize uintptr
	if size <= maxSmallSize-mallocHeaderSize {
		if typ == nil || !typ.Pointers() {
			if size < maxTinySize {
				x, elemsize = mallocgcTiny(size, typ, needzero)
			} else {
				x, elemsize = mallocgcSmallNoscan(size, typ, needzero)
			}
		} else if heapBitsInSpan(size) {
			x, elemsize = mallocgcSmallScanNoHeader(size, typ, needzero)
		} else {
			x, elemsize = mallocgcSmallScanHeader(size, typ, needzero)
		}
	} else {
		x, elemsize = mallocgcLarge(size, typ, needzero)
	}

	// Notify sanitizers, if enabled.
	if raceenabled {
		racemalloc(x, size-asanRZ)
	}
	if msanenabled {
		msanmalloc(x, size-asanRZ)
	}
	if asanenabled {
		// Poison the space between the end of the requested size of x
		// and the end of the slot. Unpoison the requested allocation.
		frag := elemsize - size
		if typ != nil && typ.Pointers() && !heapBitsInSpan(elemsize) && size <= maxSmallSize-mallocHeaderSize {
			frag -= mallocHeaderSize
		}
		asanpoison(unsafe.Add(x, size-asanRZ), asanRZ)
		asanunpoison(x, size-asanRZ)
	}

	// Adjust our GC assist debt to account for internal fragmentation.
	if gcBlackenEnabled != 0 && elemsize != 0 {
		if assistG := getg().m.curg; assistG != nil {
			assistG.gcAssistBytes -= int64(elemsize - size)
		}
	}

	// Post-malloc debug hooks.
	if debug.malloc {
		postMallocgcDebug(x, elemsize, typ)
	}
	return x
}
```


### heap

Main malloc heap.
The heap itself is the "free" and "scav" treaps, but all the other global data is here too.

mheap must not be heap-allocated because it contains mSpanLists, which must not be heap-allocated.
```go
type mheap struct {
	_ sys.NotInHeap

	// lock must only be acquired on the system stack, otherwise a g
	// could self-deadlock if its stack grows with the lock held.
	lock mutex

	pages pageAlloc // page allocation data structure

	sweepgen uint32 // sweep generation, see comment in mspan; written during STW

	// allspans is a slice of all mspans ever created. Each mspan
	// appears exactly once.
	//
	// The memory for allspans is manually managed and can be
	// reallocated and move as the heap grows.
	//
	// In general, allspans is protected by mheap_.lock, which
	// prevents concurrent access as well as freeing the backing
	// store. Accesses during STW might not hold the lock, but
	// must ensure that allocation cannot happen around the
	// access (since that may free the backing store).
	allspans []*mspan // all spans out there

	// Proportional sweep
	//
	// These parameters represent a linear function from gcController.heapLive
	// to page sweep count. The proportional sweep system works to
	// stay in the black by keeping the current page sweep count
	// above this line at the current gcController.heapLive.
	//
	// The line has slope sweepPagesPerByte and passes through a
	// basis point at (sweepHeapLiveBasis, pagesSweptBasis). At
	// any given time, the system is at (gcController.heapLive,
	// pagesSwept) in this space.
	//
	// It is important that the line pass through a point we
	// control rather than simply starting at a 0,0 origin
	// because that lets us adjust sweep pacing at any time while
	// accounting for current progress. If we could only adjust
	// the slope, it would create a discontinuity in debt if any
	// progress has already been made.
	pagesInUse         atomic.Uintptr // pages of spans in stats mSpanInUse
	pagesSwept         atomic.Uint64  // pages swept this cycle
	pagesSweptBasis    atomic.Uint64  // pagesSwept to use as the origin of the sweep ratio
	sweepHeapLiveBasis uint64         // value of gcController.heapLive to use as the origin of sweep ratio; written with lock, read without
	sweepPagesPerByte  float64        // proportional sweep ratio; written with lock, read without

	// Page reclaimer state

	// reclaimIndex is the page index in allArenas of next page to
	// reclaim. Specifically, it refers to page (i %
	// pagesPerArena) of arena allArenas[i / pagesPerArena].
	//
	// If this is >= 1<<63, the page reclaimer is done scanning
	// the page marks.
	reclaimIndex atomic.Uint64

	// reclaimCredit is spare credit for extra pages swept. Since
	// the page reclaimer works in large chunks, it may reclaim
	// more than requested. Any spare pages released go to this
	// credit pool.
	reclaimCredit atomic.Uintptr

	_ cpu.CacheLinePad // prevents false-sharing between arenas and preceding variables

	// arenas is the heap arena map. It points to the metadata for
	// the heap for every arena frame of the entire usable virtual
	// address space.
	//
	// Use arenaIndex to compute indexes into this array.
	//
	// For regions of the address space that are not backed by the
	// Go heap, the arena map contains nil.
	//
	// Modifications are protected by mheap_.lock. Reads can be
	// performed without locking; however, a given entry can
	// transition from nil to non-nil at any time when the lock
	// isn't held. (Entries never transitions back to nil.)
	//
	// In general, this is a two-level mapping consisting of an L1
	// map and possibly many L2 maps. This saves space when there
	// are a huge number of arena frames. However, on many
	// platforms (even 64-bit), arenaL1Bits is 0, making this
	// effectively a single-level map. In this case, arenas[0]
	// will never be nil.
	arenas [1 << arenaL1Bits]*[1 << arenaL2Bits]*heapArena

	// arenasHugePages indicates whether arenas' L2 entries are eligible
	// to be backed by huge pages.
	arenasHugePages bool

	// heapArenaAlloc is pre-reserved space for allocating heapArena
	// objects. This is only used on 32-bit, where we pre-reserve
	// this space to avoid interleaving it with the heap itself.
	heapArenaAlloc linearAlloc

	// arenaHints is a list of addresses at which to attempt to
	// add more heap arenas. This is initially populated with a
	// set of general hint addresses, and grown with the bounds of
	// actual heap arena ranges.
	arenaHints *arenaHint

	// arena is a pre-reserved space for allocating heap arenas
	// (the actual arenas). This is only used on 32-bit.
	arena linearAlloc

	// allArenas is the arenaIndex of every mapped arena. This can
	// be used to iterate through the address space.
	//
	// Access is protected by mheap_.lock. However, since this is
	// append-only and old backing arrays are never freed, it is
	// safe to acquire mheap_.lock, copy the slice header, and
	// then release mheap_.lock.
	allArenas []arenaIdx

	// sweepArenas is a snapshot of allArenas taken at the
	// beginning of the sweep cycle. This can be read safely by
	// simply blocking GC (by disabling preemption).
	sweepArenas []arenaIdx

	// markArenas is a snapshot of allArenas taken at the beginning
	// of the mark cycle. Because allArenas is append-only, neither
	// this slice nor its contents will change during the mark, so
	// it can be read safely.
	markArenas []arenaIdx

	// curArena is the arena that the heap is currently growing
	// into. This should always be physPageSize-aligned.
	curArena struct {
		base, end uintptr
	}

	// central free lists for small size classes.
	// the padding makes sure that the mcentrals are
	// spaced CacheLinePadSize bytes apart, so that each mcentral.lock
	// gets its own cache line.
	// central is indexed by spanClass.
	central [numSpanClasses]struct {
		mcentral mcentral
		pad      [(cpu.CacheLinePadSize - unsafe.Sizeof(mcentral{})%cpu.CacheLinePadSize) % cpu.CacheLinePadSize]byte
	}

	spanalloc              fixalloc // allocator for span*
	cachealloc             fixalloc // allocator for mcache*
	specialfinalizeralloc  fixalloc // allocator for specialfinalizer*
	specialCleanupAlloc    fixalloc // allocator for specialcleanup*
	specialprofilealloc    fixalloc // allocator for specialprofile*
	specialReachableAlloc  fixalloc // allocator for specialReachable
	specialPinCounterAlloc fixalloc // allocator for specialPinCounter
	specialWeakHandleAlloc fixalloc // allocator for specialWeakHandle
	speciallock            mutex    // lock for special record allocators.
	arenaHintAlloc         fixalloc // allocator for arenaHints

	// User arena state.
	//
	// Protected by mheap_.lock.
	userArena struct {
		// arenaHints is a list of addresses at which to attempt to
		// add more heap arenas for user arena chunks. This is initially
		// populated with a set of general hint addresses, and grown with
		// the bounds of actual heap arena ranges.
		arenaHints *arenaHint

		// quarantineList is a list of user arena spans that have been set to fault, but
		// are waiting for all pointers into them to go away. Sweeping handles
		// identifying when this is true, and moves the span to the ready list.
		quarantineList mSpanList

		// readyList is a list of empty user arena spans that are ready for reuse.
		readyList mSpanList
	}

	// cleanupID is a counter which is incremented each time a cleanup special is added
	// to a span. It's used to create globally unique identifiers for individual cleanup.
	// cleanupID is protected by mheap_.lock. It should only be incremented while holding
	// the lock.
	cleanupID uint64

	unused *specialfinalizer // never set, just here to force the specialfinalizer type into DWARF
}
```



Central list of free objects of a given size.
```go
type mcentral struct {
	_         sys.NotInHeap
	spanclass spanClass

	// partial and full contain two mspan sets: one of swept in-use
	// spans, and one of unswept in-use spans. These two trade
	// roles on each GC cycle. The unswept set is drained either by
	// allocation or by the background sweeper in every GC cycle,
	// so only two roles are necessary.
	//
	// sweepgen is increased by 2 on each GC cycle, so the swept
	// spans are in partial[sweepgen/2%2] and the unswept spans are in
	// partial[1-sweepgen/2%2]. Sweeping pops spans from the
	// unswept set and pushes spans that are still in-use on the
	// swept set. Likewise, allocating an in-use span pushes it
	// on the swept set.
	//
	// Some parts of the sweeper can sweep arbitrary spans, and hence
	// can't remove them from the unswept set, but will add the span
	// to the appropriate swept list. As a result, the parts of the
	// sweeper and mcentral that do consume from the unswept list may
	// encounter swept spans, and these should be ignored.
	partial [2]spanSet // list of spans with a free object
	full    [2]spanSet // list of spans with no free objects
}
```

## memory leak



Go 允许将局部变量的地址作为值返回给上层调用函数 或者将局部变量的值设置到全局变量中 存在内存逃逸
Go 会将该局部变量存储到堆内存中
在编译Go程序的时候 加上一些编译参数可以输出内存逃逸的情况

```shell
go build -gcflags '-N -m -m -l ' main.go
```

正常情况无需担心内存逃逸 gc会自动回收不再使用的对象









## Links

- [Golang](/docs/CS/Go/Go.md)