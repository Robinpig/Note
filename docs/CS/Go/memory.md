## Introduction



Go语言采用现代内存分配TCMalloc算法的思想来进行内存分配，将对象分为微小对象、小对象、大对象，使用三级管理结构mcache、mcentral、mheap用于管理、缓存加速span对象的访问和分配，使用精准的位图管理已分配的和未分配的对象及对象的大小。


内存管理一般包含三个不同的组件，分别是用户程序（Mutator）、分配器（Allocator）和收集器（Collector）1，当用户程序申请内存时，它会通过内存分配器申请新的内存，而分配器会负责从堆中初始化相应的内存区域



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
● spans 区域存储了指向内存管理单元 runtime.mspan 的指针，每个内存单元会管理几页的内存空间，每页大小为 8KB；
● bitmap 用于标识 arena 区域中的那些地址保存了对象，位图中的每个字节都会表示堆区中的 32 字节是否包含空闲；
● arena 区域是真正的堆区，运行时会将 8KB 看做一页，这些内存页中存储了所有在堆上初始化的对象；
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
● runtime: use sparse mappings for the heap
● runtime: fix various contiguous bitmap assumptions
● runtime: make the heap bitmap sparse
● runtime: abstract remaining mheap.spans access
● runtime: make span map sparse
● runtime: eliminate most uses of mheap_.arena_*
● runtime: remove non-reserved heap logic
● runtime: move comment about address space sizes to malloc.go


由于内存的管理变得更加复杂，上述改动对垃圾回收稍有影响，大约会增加 1% 的垃圾回收开销，不过这也是我们为了解决已有问题必须付出的成本

Go 语言的内存分配器包含内存管理单元、线程缓存、中心缓存和页堆几个重要组件，本节将介绍这几种最重要组件对应的数据结构 runtime.mspan、runtime.mcache、runtime.mcentral 和 runtime.mheap，
所有的 Go 语言程序都会在启动时初始化如上图所示的内存布局，每一个处理器都会被分配一个线程缓存 runtime.mcache 用于处理微对象和小对象的分配，它们会持有内存管理单元 runtime.mspan。
每个类型的内存管理单元都会管理特定大小的对象，当内存管理单元中不存在空闲对象时，它们会从 runtime.mheap 持有的 134 个中心缓存 runtime.mcentral 中获取新的内存单元，中心缓存属于全局的堆结构体 runtime.mheap，它会从操作系统中申请内存。

在 amd64 的 Linux 操作系统上，runtime.mheap 会持有 4,194,304 runtime.heapArena，每一个 runtime.heapArena 都会管理 64MB 的内存，单个 Go 语言程序的内存上限也就是 256TB。


runtime.mspan 是 Go 语言内存管理的基本单元，该结构体中包含 next 和 prev 两个字段，它们分别指向了前一个和后一个 runtime.mspan：


```go
type mspan struct {
    next *mspan
    prev *mspan
    ...
}
```
串联后的上述结构体会构成如下双向链表，运行时会使用 runtime.mSpanList 存储双向链表的头结点和尾节点并在线程缓存以及中心缓存中使用







## Links

