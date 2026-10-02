## Introduction


内存空间包含了多种存储，RAM只是其中一部分，还包含了某些外部l/0设备的空间，系统
会将它们映射到内存空间(Memory Mapped IO, MMlO) 。可以通过／ `proc/iomem` 文件来查看系统的内存空间布局。

`/proc/iomem` 文件可以显示系统中的内存，及各段内存的使用情况


设备的寄存器空间和它的内存(RAM)都可以成为MMIO的一部分， MMlO机制很大程度上提高了CPU访问外设的效率
在x86架构中， CPU访问MMIO与访问普通内存无异（并不是所有架构都可以如此）。
以显卡(G PU)为例， 一般它的寄存器空间和它自身的内存都会以 MMlO 的形式供CPU访问， CPU可以像访问指针一样访问它的寄存器和数据



内存管理，本质上是维护内存介质(RAM+ MMIO)、内存空间和虚拟三者的关系



物理内存是以页为单位管理的，内核提供了page 结构体与一页物理内存对应， 而一页物理内存的作用或者使用情况由它所在的区域(zone)决定，zone的分布则决定于它所处的结点(node)

> 实际的物理内存并不是一页页的， 页只是逻辑上的划分

结点(node)与NUMA(Non Uniform Memory Access, 非统一内存访问）架构有密切联系
传统的SMP架构中，所有的CPU共享系统总线， 限制了内存的访问能力
SMP架构比较直观清晰，但是当系统中CPU的数最增加到一定程度时，它们会竞争总线资源， 最终导致总线成为系统的瓶颈

Linux 支持 NUMA (Non Uniform Memory Access)。物理内存管理的第一个层次就是介质的管理，pg_data_t结构就描述了介质。
一般而言，我们的内存管理介质只有内存，并且它是均匀的，所以可以简单地认为系统中只有一个 pg_data_t 对象

> 可以通过 `lscpu` 来查看系统当前Socket 和节点的布局情况

在 NUMA 机器上，每个 NUMA 节点都会有一个 pg_data_t 来描述其内存布局。
在 UMA 机器上则只有一个 pglist_data 来描述整片内存。
内存统计信息与页回收（page reclaim）相关的数据结构都以 per-zone（按 zone）为单位维护。


## node

内核定义了 pglist_data 结构体与node 对应

```c
// include/linux/mmzone.h
typedef struct pglist_data {
    struct zone node_zones[MAX_NR_ZONES];

    struct zonelist node_zonelists[MAX_ZONELISTS];

    int nr_zones; /* number of populated zones in this node */
#ifdef CONFIG_FLAT_NODE_MEM_MAP /* means !SPARSEMEM */
    struct page *node_mem_map;
#ifdef CONFIG_PAGE_EXTENSION
    struct page_ext *node_page_ext;
#endif
#endif
#if defined(CONFIG_MEMORY_HOTPLUG) || defined(CONFIG_DEFERRED_STRUCT_PAGE_INIT)
    /*
     * Must be held any time you expect node_start_pfn,
     * node_present_pages, node_spanned_pages or nr_zones to stay constant.
     * Also synchronizes pgdat->first_deferred_pfn during deferred page
     * init.
     *
     * pgdat_resize_lock() and pgdat_resize_unlock() are provided to
     * manipulate node_size_lock without checking for CONFIG_MEMORY_HOTPLUG
     * or CONFIG_DEFERRED_STRUCT_PAGE_INIT.
     *
     * Nests above zone->lock and zone->span_seqlock
     */
    spinlock_t node_size_lock;
#endif
    unsigned long node_start_pfn;
    unsigned long node_present_pages; /* total number of physical pages */
    unsigned long node_spanned_pages; /* total size of physical page
                         range, including holes */
    int node_id;
    wait_queue_head_t kswapd_wait;
    wait_queue_head_t pfmemalloc_wait;
    struct task_struct *kswapd; /* Protected by
                       mem_hotplug_begin/end() */
    int kswapd_order;
    enum zone_type kswapd_highest_zoneidx;

    int kswapd_failures;        /* Number of 'reclaimed == 0' runs */

#ifdef CONFIG_COMPACTION
    int kcompactd_max_order;
    enum zone_type kcompactd_highest_zoneidx;
    wait_queue_head_t kcompactd_wait;
    struct task_struct *kcompactd;
#endif
    /*
     * This is a per-node reserve of pages that are not available
     * to userspace allocations.
     */
    unsigned long       totalreserve_pages;

#ifdef CONFIG_NUMA
    /*
     * node reclaim becomes active if more unmapped pages exist.
     */
    unsigned long       min_unmapped_pages;
    unsigned long       min_slab_pages;
#endif /* CONFIG_NUMA */

    /* Write-intensive fields used by page reclaim */
    ZONE_PADDING(_pad1_)

#ifdef CONFIG_DEFERRED_STRUCT_PAGE_INIT
    /*
     * If memory initialisation on large machines is deferred then this
     * is the first PFN that needs to be initialised.
     */
    unsigned long first_deferred_pfn;
#endif /* CONFIG_DEFERRED_STRUCT_PAGE_INIT */

#ifdef CONFIG_TRANSPARENT_HUGEPAGE
    struct deferred_split deferred_split_queue;
#endif

    /* Fields commonly accessed by the page reclaim scanner */

    /*
     * NOTE: THIS IS UNUSED IF MEMCG IS ENABLED.
     *
     * Use mem_cgroup_lruvec() to look up lruvecs.
     */
    struct lruvec       __lruvec;

    unsigned long       flags;

    ZONE_PADDING(_pad2_)

    /* Per-node vmstats */
    struct per_cpu_nodestat __percpu *per_cpu_nodestats;
    atomic_long_t       vm_stat[NR_VM_NODE_STAT_ITEMS];
} pg_data_t;
```

内存被划分为节点. 每个节点关联到系统中的一个处理器, 内核中表示为 pg_data_t 的实例.
系统中每个节点被链接到一个以NULL结尾的pgdat_list链表中<而其中的每个节点利用pg_data_tnode_next字段链接到下一节．而对于PC这种UMA结构的机器来说, 只使用了一个成为 contig_page_data 的静态pg_data_t结构.
各个节点又被划分为内存管理区域, 一个管理区域通过struct zone_struct描述, 其被定义为zone_t, 用以表示内存的某个范围, 低端范围的16MB被描述为ZONE_DMA, 某些工业标准体系结构中的(ISA)设备需要用到它, 然后是可直接映射到内核的普通内存域ZONE_NORMAL,最后是超出了内核段的物理地址域ZONE_HIGHMEM, 被称为高端内存. 是系统中预留的可用内存空间, 不能被内核直接映射

> 但是Linux内核又把各个物理内存节点分成个不同的管理区域zone, 这是为什么呢?
> 因为实际的计算机体系结构有硬件的诸多限制, 这限制了页框可以使用的方式. 尤其是, Linux内核必须处理80x86体系结构的两种硬件约束.
> - ISA总线的直接内存存储DMA处理器有一个严格的限制 : 他们只能对RAM的前16MB进行寻址
> - 在具有大容量RAM的现代32位计算机中, CPU不能直接访问所有的物理地址, 因为线性地址空间太小, 内核不可能直接映射所有物理内存到线性地址空间, 我们会在后面典型架构(x86)上内存区域划分详细讲解x86_32上的内存区域划分
> 因此Linux内核对不同区域的内存需要采用不同的管理方式和映射方式, 因此内核将物理地址或者成用zone_t表示的不同地址区域



同一个node 上同一种内存从访问效率上看， 应该是一样的，但是基于兼容性考虑， 内核不得不做进一步划分，将一个node 划分为不同的zone



## Zone

硬件常常会对不同物理内存区间的访问方式施加限制。
某些情况下，设备无法对所有可寻址内存执行 DMA。
另一些情况下，物理内存的大小超过了虚拟内存可寻址的上限，需要借助特殊手段才能访问其中一部分内存。
Linux 根据内存页可能的用途将它们划分为不同的 zone。
例如，ZONE_DMA 存放可供设备做 DMA 的内存；ZONE_HIGHMEM 存放没有永久映射到内核地址空间的内存；ZONE_NORMAL 存放按常规方式寻址的页。
zone 的实际布局依赖于具体硬件——并非所有架构都定义了全部 zone，而且不同平台对 DMA 的要求也不同。

许多多处理器机器是 NUMA（Non-Uniform Memory Access，非一致内存访问）系统。
在这类系统中，内存被划分成多个 bank，根据与处理器的“距离”不同而有不同的访问延迟。
每个 bank 称为一个 node，Linux 为每个 node 构建一套独立的内存管理子系统。
一个 node 拥有自己的一套 zone、空闲页与已用页链表，以及各种统计计数器。
关于 NUMA 的更多细节可参考《What is NUMA?》与《NUMA Memory Policy》。

### struct zone

zone 的核心数据结构是 `struct zone`（linux/mmzone.h）。每个 zone 管理一段连续的物理页区间，并维护自己的空闲链表、水位线与统计。下面列出与物理内存分配最直接相关的字段（完整定义见源码）：

```c
// linux/mmzone.h

#define ASYNC_AND_SYNC 2

struct zone {
	/* Read-mostly fields */

	/* zone watermarks, access with *_wmark_pages(zone) macros */
	unsigned long _watermark[NR_WMARK];
	unsigned long watermark_boost;

	unsigned long nr_reserved_highatomic;

	/*
	 * We don't know if the memory that we're going to allocate will be
	 * freeable or/and it will be released eventually, so to avoid totally
	 * wasting several GB of ram we must reserve some of the lower zone
	 * memory (otherwise we risk to run OOM on the lower zones despite
	 * there being tons of freeable ram on the higher zones).  This array is
	 * recalculated at runtime if the sysctl_lowmem_reserve_ratio sysctl
	 * changes.
	 */
	long lowmem_reserve[MAX_NR_ZONES];

#ifdef CONFIG_NUMA
	int node;
#endif
	struct pglist_data	*zone_pgdat;
	struct per_cpu_pageset __percpu *pageset;
	/*
	 * the high and batch values are copied to individual pagesets for
	 * faster access
	 */
	int pageset_high;
	int pageset_batch;

#ifndef CONFIG_SPARSEMEM
	/*
	 * Flags for a pageblock_nr_pages block. See pageblock-flags.h.
	 * In SPARSEMEM, this map is stored in struct mem_section
	 */
	unsigned long		*pageblock_flags;
#endif /* CONFIG_SPARSEMEM */

	/* zone_start_pfn == zone_start_paddr >> PAGE_SHIFT */
	unsigned long		zone_start_pfn;

	/*
	 * spanned_pages is the total pages spanned by the zone, including
	 * holes, which is calculated as:
	 * 	spanned_pages = zone_end_pfn - zone_start_pfn;
	 *
	 * present_pages is physical pages existing within the zone, which
	 * is calculated as:
	 *	present_pages = spanned_pages - absent_pages(pages in holes);
	 *
	 * managed_pages is present pages managed by the buddy system, which
	 * is calculated as (reserved_pages includes pages allocated by the
	 * bootmem allocator):
	 *	managed_pages = present_pages - reserved_pages;
	 *
	 * cma pages is present pages that are assigned for CMA use
	 * (MIGRATE_CMA).
	 *
	 * So present_pages may be used by memory hotplug or memory power
	 * management logic to figure out unmanaged pages by checking
	 * (present_pages - managed_pages). And managed_pages should be used
	 * by page allocator and vm scanner to calculate all kinds of watermarks
	 * and thresholds.
	 *
	 * Locking rules:
	 *
	 * zone_start_pfn and spanned_pages are protected by span_seqlock.
	 * It is a seqlock because it has to be read outside of zone->lock,
	 * and it is done in the main allocator path.  But, it is written
	 * quite infrequently.
	 *
	 * The span_seq lock is declared along with zone->lock because it is
	 * frequently read in proximity to zone->lock.  It's good to
	 * give them a chance of being in the same cacheline.
	 *
	 * Write access to present_pages at runtime should be protected by
	 * mem_hotplug_begin/end(). Any reader who can't tolerant drift of
	 * present_pages should get_online_mems() to get a stable value.
	 */
	atomic_long_t		managed_pages;
	unsigned long		spanned_pages;
	unsigned long		present_pages;
#ifdef CONFIG_CMA
	unsigned long		cma_pages;
#endif

	const char		*name;

#ifdef CONFIG_MEMORY_ISOLATION
	/*
	 * Number of isolated pageblock. It is used to solve incorrect
	 * freepage counting problem due to racy retrieving migratetype
	 * of pageblock. Protected by zone->lock.
	 */
	unsigned long		nr_isolate_pageblock;
#endif

#ifdef CONFIG_MEMORY_HOTPLUG
	/* see spanned/present_pages for more description */
	seqlock_t		span_seqlock;
#endif

	int initialized;

	/* Write-intensive fields used from the page allocator */
	ZONE_PADDING(_pad1_)

	/* free areas of different sizes */
	struct free_area	free_area[MAX_ORDER];

	/* zone flags, see below */
	unsigned long		flags;

	/* Primarily protects free_area */
	spinlock_t		lock;

	/* Write-intensive fields used by compaction and vmstats. */
	ZONE_PADDING(_pad2_)

	/*
	 * When free pages are below this point, additional steps are taken
	 * when reading the number of free pages to avoid per-cpu counter
	 * drift allowing watermarks to be breached
	 */
	unsigned long percpu_drift_mark;

#if defined CONFIG_COMPACTION || defined CONFIG_CMA
	/* pfn where compaction free scanner should start */
	unsigned long		compact_cached_free_pfn;
	/* pfn where compaction migration scanner should start */
	unsigned long		compact_cached_migrate_pfn[ASYNC_AND_SYNC];
	unsigned long		compact_init_migrate_pfn;
	unsigned long		compact_init_free_pfn;
#endif

#ifdef CONFIG_COMPACTION
	/*
	 * On compaction failure, 1<<compact_defer_shift compactions
	 * are skipped before trying again. The number attempted since
	 * last failure is tracked with compact_considered.
	 * compact_order_failed is the minimum compaction failed order.
	 */
	unsigned int		compact_considered;
	unsigned int		compact_defer_shift;
	int			compact_order_failed;
#endif

#if defined CONFIG_COMPACTION || defined CONFIG_CMA
	/* Set to true when the PG_migrate_skip bits should be cleared */
	bool			compact_blockskip_flush;
#endif

	bool			contiguous;

	ZONE_PADDING(_pad3_)
	/* Zone statistics */
	atomic_long_t		vm_stat[NR_VM_ZONE_STAT_ITEMS];
	atomic_long_t		vm_numa_stat[NR_VM_NUMA_STAT_ITEMS];
} ____cacheline_internodealigned_in_smp;
```
## Page cache

物理内存是易失的，把数据装进内存最常见的方式就是从文件读取。
每次读取文件时，数据都会被放进 page cache（页缓存），以避免后续读取时再付出昂贵的磁盘访问开销。
类似地，向文件写入时，数据也会先放进 page cache，最终才落盘到后端存储设备。
被写入的页会被标记为 dirty（脏页），当 Linux 决定把这些页另作他用时，会确保将设备上文件内容与更新后的数据同步。

## Anonymous Memory

anonymous memory（匿名内存）/ anonymous mappings（匿名映射）表示没有文件作为后端支撑的内存。
这类映射会隐式地为程序的栈和堆创建，也可以由显式调用 mmap(2) 系统调用创建。
通常，匿名映射只定义程序允许访问的虚拟内存区域。
读访问会创建一个页表项，指向一个填充为零的特殊物理页。
当程序执行写操作时，才会分配一个普通的物理页来存放写入的数据。
该页会被标记为脏页，如果内核决定回收它，这个脏页会被换出（swap out）。

## Reclaim

在系统的整个生命周期里，一个物理页可以用来存放不同类型的数据。
它可以存放内核内部数据结构、供设备驱动使用的 DMA 缓冲、从文件系统读取的数据、用户空间进程分配的内存等。
根据页的不同用途，Linux 内存管理对它们的处理方式也不同。
那些随时可以被释放的页——要么因为它们缓存了别处（例如硬盘上）已有的数据，要么因为它们可以被换出到硬盘——被称为可回收页（reclaimable）。
最典型的可回收页就是 page cache 与 anonymous memory。
大多数情况下，持有内核内部数据、用作 DMA 缓冲的页不能被挪作他用，它们会一直被钉住（pinned），直到使用者主动释放，这类页被称为不可回收页（unreclaimable）。
不过在某些情况下，即便装着内核数据结构的页也可以被回收。例如文件系统元数据的内存缓存可以从存储设备重新读回，因此在系统内存紧张时，可以把它们从主存中丢弃。
释放可回收的物理内存页并重新分配用途的过程，就是所谓的回收（reclaim）。
根据系统状态，Linux 可以异步或同步地进行回收。
系统空闲时，大部分内存是空闲的，分配请求会立即从空闲页供给中得到满足。
随着负载上升，空闲页数量下降，当降到某个阈值（low watermark，低水位线）时，一次分配请求会唤醒 kswapd 守护进程。
kswapd 会异步地扫描内存页：如果页中数据在别处有副本就直接释放，否则就将其回写到后端存储设备（还记得那些脏页吗？）。
当内存使用量进一步上升、触及另一个阈值——min watermark（最小水位线）时，分配会触发直接回收（direct reclaim）。
这种情况下，分配会被阻塞，直到回收出足够多的内存页来满足请求。

Compaction

随着系统运行，任务不断地分配和释放内存，内存会逐渐碎片化。
虽然借助虚拟内存可以把零散的物理页呈现为虚拟上连续的区间，但有时仍必须分配大片物理上连续的内存区域。
例如，当设备驱动需要一个大的 DMA 缓冲，或者 THP（透明大页）要分配一个 huge page 时，就会出现这种需求。
内存规整（memory compaction）正是用来解决碎片化问题的。
这一机制把 zone 下半部分已占用的页搬到上半部分的空闲页上；规整扫描结束后，空闲页会集中到 zone 的起始处，于是对大块物理连续内存的分配便成为可能。
和回收一样，规整既可以异步地发生在 kcompactd 守护进程中，也可以作为内存分配请求的结果同步发生。
## OOM killer

在负载较高的机器上，内存有可能被耗尽，内核无法回收出足够的内存以维持运转。
为了保全系统的其余部分，内核会调用 OOM killer（内存耗尽杀手）。
OOM killer 会挑选一个任务作为牺牲品，以保全整个系统的健康。
被选中的任务会被杀死，期望它退出后能释放足够内存，使系统恢复正常运转。

触发时机、`select_bad_process` / `oom_badness` 打分、`oom_kill_process` 与 `oom_reaper` 异步收割、memcg 局部 OOM 与 `oom_score_adj` 的完整展开，见独立笔记 [OOM killer](/docs/CS/OS/Linux/mm/oom.md)。

## memory model


内核中如何组织管理这些物理内存页的方式我们称之为做物理内存模型
Linux 目前支持这三种内存模型 内核编译构建时只能选择一种
这三种内存模型的区别在于对page的管理方式和 page 与 pfn 的转换不同

- FLATMEM 扁平内存模型
- DISCONTIGMEM 非连续内存模型
- SPARSEMEM 稀疏内存模型

在 NUMA 架构下，只有 DISCONTIGMEM 非连续内存模型和 SPARSEMEM 稀疏内存模型是可用的。而 UMA 架构下，前面介绍的三种内存模型都可以配置使用。



```c
// include/asm-generic/memory_model.h
#if defined(CONFIG_FLATMEM)

#define __pfn_to_page(pfn)  (mem_map + ((pfn) - ARCH_PFN_OFFSET))
#define __page_to_pfn(page) ((unsigned long)((page) - mem_map) + \
                 ARCH_PFN_OFFSET)
#elif defined(CONFIG_DISCONTIGMEM)

#define __pfn_to_page(pfn)          \
({  unsigned long __pfn = (pfn);        \
    unsigned long __nid = arch_pfn_to_nid(__pfn);  \
    NODE_DATA(__nid)->node_mem_map + arch_local_page_offset(__pfn, __nid);\
})

#define __page_to_pfn(pg)                       \
({  const struct page *__pg = (pg);                 \
    struct pglist_data *__pgdat = NODE_DATA(page_to_nid(__pg)); \
    (unsigned long)(__pg - __pgdat->node_mem_map) +         \
     __pgdat->node_start_pfn;                   \
})

#elif defined(CONFIG_SPARSEMEM_VMEMMAP)

/* memmap is virtually contiguous.  */
#define __pfn_to_page(pfn)  (vmemmap + (pfn))
#define __page_to_pfn(page) (unsigned long)((page) - vmemmap)

#elif defined(CONFIG_SPARSEMEM)
/*
 * Note: section's mem_map is encoded to reflect its start_pfn.
 * section[i].section_mem_map == mem_map's address - start_pfn;
 */
#define __page_to_pfn(pg)                   \
({  const struct page *__pg = (pg);             \
    int __sec = page_to_section(__pg);          \
    (unsigned long)(__pg - __section_mem_map_addr(__nr_to_section(__sec))); \
})

#define __pfn_to_page(pfn)              \
({  unsigned long __pfn = (pfn);            \
    struct mem_section *__sec = __pfn_to_section(__pfn);    \
    __section_mem_map_addr(__sec) + __pfn;      \
})
#endif /* CONFIG_FLATMEM/DISCONTIGMEM/SPARSEMEM */
```


2008年以后，SPARSEMEM_VMEMMAP 成为 x86-64 唯一支持的内存模型

PFN 即 page frame number 物理页框号，是针对物理内存而言的，将物理内存分成由每个page size页框构成的区域，并给每个page 编号，这个编号就是 PFN。假设物理内存从0地址开始，那么PFN等于0的那个页帧就是0地址（物理地址）开始的那个page。假设物理内存从x地址开始，那么第一个页帧号码就是（x>>PAGE_SHIFT）。
但是由于物理内存映射的关系，物理内存的0地址对应到到系统上不一定是物理地址的0，如果由物理内存基地址（取决于物理内存映射）的话，在系统中 pfn的值 应该等于 （physical address - memory base address） >> 12 

```c
// include/linux/pfn.h
/*
 * pfn_t: encapsulates a page-frame number that is optionally backed
 * by memmap (struct page).  Whether a pfn_t has a 'struct page'
 * backing is indicated by flags in the high bits of the value.
 */
typedef struct {
    u64 val;
} pfn_t;
#endif

#define PFN_ALIGN(x)    (((unsigned long)(x) + (PAGE_SIZE - 1)) & PAGE_MASK)
#define PFN_UP(x)   (((x) + PAGE_SIZE-1) >> PAGE_SHIFT)
#define PFN_DOWN(x) ((x) >> PAGE_SHIFT)
#define PFN_PHYS(x) ((phys_addr_t)(x) << PAGE_SHIFT)
#define PHYS_PFN(x) ((unsigned long)((x) >> PAGE_SHIFT))
```
### FLATMEM

平坦内存模型：把内存看作是连续的 即时中间有空洞也是会算作page 由一个全局数组mem_map 存储 struct page，直接线性映射到实际的物理内存
mem_map 全局数组的下标就是相应物理页对应的 PFN 。

在平坦内存模型下 ，page_to_pfn 与 pfn_to_page 的计算逻辑就非常简单，本质就是基于 mem_map 数组进行偏移操作



申请足够存储所有page对象的内存 然后将地址赋值给 `pgdat -> node_mem_map`

```c
#ifdef CONFIG_FLATMEM
static void __init alloc_node_mem_map(struct pglist_data *pgdat)
{
	unsigned long __maybe_unused start = 0;
	unsigned long __maybe_unused offset = 0;

	start = pgdat->node_start_pfn & ~(MAX_ORDER_NR_PAGES - 1);
	offset = pgdat->node_start_pfn - start;
	/* ia64 gets its own node_mem_map, before this, without bootmem */
	if (!pgdat->node_mem_map) {
		unsigned long size, end;
		struct page *map;

		/*
		 * The zone's endpoints aren't required to be MAX_ORDER
		 * aligned but the node_mem_map endpoints must be in order
		 * for the buddy allocator to function correctly.
		 */
		end = pgdat_end_pfn(pgdat);
		end = ALIGN(end, MAX_ORDER_NR_PAGES);
		size =  (end - start) * sizeof(struct page);
		map = memmap_alloc(size, SMP_CACHE_BYTES, MEMBLOCK_LOW_LIMIT,
				   pgdat->node_id, false);
		if (!map)
			panic("Failed to allocate %ld bytes for node %d memory map\n",
			      size, pgdat->node_id);
		pgdat->node_mem_map = map + offset;
	}

#ifndef CONFIG_NUMA
	/*
	 * With no DISCONTIG, the global mem_map is just set as node 0's
	 */
	if (pgdat == NODE_DATA(0)) {
		mem_map = NODE_DATA(0)->node_mem_map;
		if (page_to_pfn(mem_map) != pgdat->node_start_pfn)
			mem_map -= offset;
	}
#endif
}
#else
static inline void alloc_node_mem_map(struct pglist_data *pgdat) { }
#endif /* CONFIG_FLATMEM */
```



### DISCONTIGMEM

FLATMEM 平坦内存模型只适合管理一整块连续的物理内存，而对于多块非连续的物理内存来说使用 FLATMEM 平坦内存模型进行管理则会造成很大的内存空间浪费

在 DISCONTIGMEM 非连续内存模型中，内核将物理内存从宏观上划分成了一个一个的节点 node （微观上还是一页一页的物理页），每个 node 节点管理一块连续的物理内存
这样一来这些连续的物理内存页均被划归到了对应的 node 节点中管理，就避免了内存空洞造成的空间浪费

> ARM 在2010年已移除对 DISCONTIGMEM 内存模型的支持


### SPARSEMEM

SPARSEMEM_VMEMMAP是虚拟映射，走页表
SPARSEMEM 稀疏内存模型的核心思想就是对粒度更小的连续内存块进行精细的管理，用于管理连续内存块的单元被称作 section 。
物理页大小为 4k 的情况下， section 的大小为 128M ，物理页大小为 16k 的情况下， section 的大小为 512M

在内核中用 struct mem_section 结构体表示 SPARSEMEM 模型中的 section

将所有的mem_section中page 都抽象到一个虚拟数组vmemmap，这样在进行struct page 和 pfn 转换时，之间使用vmemmap数组即可，如下转换（位于include\asm-generic\memory_model.h)


slab改动
mm: Remove slab from struct page


每个zone有一个lru链表



通过内核提供的virt_to_phys()可以实现该虚拟地址到真实的内核物理地址之间的转换


```c
// arch/x86/include/asm/io.h
static inline phys_addr_t virt_to_phys(volatile void *address)
{
    return __pa(address);
}
#define virt_to_phys virt_to_phys
```

### memory map

管理内存映射的方式取决于内存模型
- FLATMEM: 全局指针变量 *mem_map 管理单个连续内存 其指向 struct page 类型数组的首地址
- DISCONTIGMEM: 全局数组 node_data[] 管理所有节点的内存, CONFIG_NODES_SHIFT 配置选项决定数组的容量
  数组的每个元素是指向 pglist_data 实例的指针 struct pglist_data 的 node_mem_map 字段指向 struct page 类型数组的首地址
- SPARSEMEM: 全局数组 mem_section[] 管理分散稀疏的内存
  struct mem_section 的 section_mem_map 字段指向 struct page 类型数组的首地址

## allocator


内核在不同的阶段采用的内存管理方式也不同，主要分为 memblock 和buddy系统两种

memblock 是内存管理的第一个阶段，也是初级阶段，buddy系统会接替它的工作继续内存管 理。
它与buddy系统交接是在 [mem_init]() 函数中完成的，标志为 after_bootmem 变量置为1
mem_init函数会调用 set_highmem_pages_init 和 memblock_free_ all 分别释放highmem和lowmem到 buddy 系统


内核收到的内存信息是由BlOS给出的，主要包括各内存段的区间和使用情况，这些区间是 Linux可见的所有内存
只有用途为usable的内存区间才属千内核直接管理(MMIO 除外），但并不是所有的usable部分内存都直接归内核管理

除了memblock和buddy系统外，还有一个更高的级别是启动程序
比如grub, grub可以通过参数（比如mem = 2048MB)来限制内核可以管理的内存的上限， 也就是说高于2048MB的部分不归内核(mcmblock和buddy)管理
同样， memblock也可以扣留一部分内存，剩下的部分才轮到buddy系统管理

## memblock


memblock 是内存管理的第一个阶段，也是初级阶段，buddy系统会接替它的工作继续内存管理
它与buddy系统交接是在mem_init函数中完成的，标志为 after_bootmem 变量置为1
mem_init函数会调用set_highmem_pages_init和memblock_free_ all 分别释放highmem和lowmem到buddy 系统

> memblock 有个前任 bootmem, 不过后者已经“ 退休＂

block这个词意味着内存被分为一块块的，内核以memblock_region结构体表示一块， 它的 base和size字段分别表示块的起始地址和大小。
块以数组的形式进行管理，该数组由 memblock_type 结构体的regions字段表示
内核共有两个memblock_type对象（也可以理解为有两个由内存块组成的数组），一个表示可用的内存，一个表示被预留的内存，分别由memblock结构体的 memory和reserved字段表示


```c
struct memblock {
	bool bottom_up;  /* is bottom up direction? */
	phys_addr_t current_limit;
	struct memblock_type memory;
	struct memblock_type reserved;
};
```

memblock_type 数据结构
```c
struct memblock_type {
	unsigned long cnt;
	unsigned long max;
	phys_addr_t total_size;
	struct memblock_region *regions;
	char *name;
};
```

块被加入reserve数组的时候并未从memory数组删除，只有在memory数组中，且不在reserve 数组中的块(for_each_free_mem_range )才会进入buddy系统。
与grub 一样，被预留的内存块也是给预留内存块的模块使用的，模块自行负责内存的映射。
所以，buddy系统管理的内存是经过 grub和memblock “ 克扣” 后剩下的部分

```c
// 获取非reserved的 
#define for_each_free_mem_range(i, nid, flags, p_start, p_end, p_nid)	\
	__for_each_mem_range(i, &memblock.memory, &memblock.reserved,	\
			     nid, flags, p_start, p_end, p_nid)
```





## buddy

zone的空闲页帧由buddy allocator管理

伙伴系统会将它所属物理内存区 zone 里的空闲内存划分成不同尺寸的物理内存块，这里的尺寸必须是 2 的次幂，物理内存块可以是由 1 个 page 组成，也可以是 2 个 page，4 个 page ........ 1024 个 page 组成。
内核将这些相同尺寸的内存块用一个内核数据结构 struct free_area 中的双向链表 free_list 串联组织起来




```c
/* Free memory management - zoned buddy allocator.  */
#ifndef CONFIG_FORCE_MAX_ZONEORDER
#define MAX_ORDER 11
#else
#define MAX_ORDER CONFIG_FORCE_MAX_ZONEORDER
#endif
#define MAX_ORDER_NR_PAGES (1 << (MAX_ORDER - 1))
```


```c
// include/linux/mmzone.h
struct free_area {
    struct list_head    free_list[MIGRATE_TYPES];
    unsigned long       nr_free;
};
```


```c
enum migratetype {
    MIGRATE_UNMOVABLE,
    MIGRATE_MOVABLE,
    MIGRATE_RECLAIMABLE,
    MIGRATE_PCPTYPES,   /* the number of types on the pcp lists */
    MIGRATE_HIGHATOMIC = MIGRATE_PCPTYPES,
#ifdef CONFIG_CMA
    /*
     * MIGRATE_CMA migration type is designed to mimic the way
     * ZONE_MOVABLE works.  Only movable pages can be allocated
     * from MIGRATE_CMA pageblocks and page allocator never
     * implicitly change migration type of MIGRATE_CMA pageblock.
     *
     * The way to use it is to change migratetype of a range of
     * pageblocks to MIGRATE_CMA which can be done by
     * __free_pageblock_cma() function.  What is important though
     * is that a range of pageblocks must be aligned to
     * MAX_ORDER_NR_PAGES should biggest page be bigger then
     * a single pageblock.
     */
    MIGRATE_CMA,
#endif
#ifdef CONFIG_MEMORY_ISOLATION
    MIGRATE_ISOLATE,    /* can't allocate from here */
#endif
    MIGRATE_TYPES
};
```

将可回收页和不可移动页分开，这样虽然在不可移动页的区域当中无法分配大块的连续内存，但是可回收页的区域却没有受其影响，可以分配大块的连续内存
ree_area 结构并非只有一个链表，而是多个链表 依次为2^index的数量page 的链表
右侧各列数字代表0~10order 空闲区间页帧的数量

```shell
cat /proc/buddyinfo 
# Node 0, zone      DMA   1750   1449   1219    954    647    407    181     56     14    103    349 
# Node 0, zone   Normal  76763  72352  43128  14603   4780   1558    504    117     43    510    356 
```

cat /proc/pagetypeinfo



#### vmap_range_noflush

```c
static int vmap_range_noflush(unsigned long addr, unsigned long end,
			phys_addr_t phys_addr, pgprot_t prot,
			unsigned int max_page_shift)
{
	pgd_t *pgd;
	unsigned long start;
	unsigned long next;
	int err;
	pgtbl_mod_mask mask = 0;

	might_sleep();
	BUG_ON(addr >= end);

	start = addr;
	pgd = pgd_offset_k(addr);
	do {
		next = pgd_addr_end(addr, end);
		err = vmap_p4d_range(pgd, addr, next, phys_addr, prot,
					max_page_shift, &mask);
		if (err)
			break;
	} while (pgd++, phys_addr += (next - addr), addr = next, addr != end);

	if (mask & ARCH_PAGE_TABLE_SYNC_MASK)
		arch_sync_kernel_mappings(start, end);

	return err;
}
```


## alloc


### alloc_pages

```c
#define __alloc_pages(...)			alloc_hooks(__alloc_pages_noprof(__VA_ARGS__))
```

这是分 zone 伙伴分配器（zoned buddy allocator）的“心脏”。
```c
struct page *__alloc_pages_noprof(gfp_t gfp, unsigned int order,
                                  int preferred_nid, nodemask_t *nodemask)
{
    struct page *page;
    unsigned int alloc_flags = ALLOC_WMARK_LOW;
    gfp_t alloc_gfp; /* The gfp_t that was actually used for allocation */
    struct alloc_context ac = { };

    /*
	 * There are several places where we assume that the order value is sane
	 * so bail out early if the request is out of bound.
	 */
    if (WARN_ON_ONCE_GFP(order > MAX_PAGE_ORDER, gfp))
        return NULL;

    gfp &= gfp_allowed_mask;
    /*
	 * Apply scoped allocation constraints. This is mainly about GFP_NOFS
	 * resp. GFP_NOIO which has to be inherited for all allocation requests
	 * from a particular context which has been marked by
	 * memalloc_no{fs,io}_{save,restore}. And PF_MEMALLOC_PIN which ensures
	 * movable zones are not used during allocation.
	 */
    gfp = current_gfp_context(gfp);
    alloc_gfp = gfp;
    if (!prepare_alloc_pages(gfp, order, preferred_nid, nodemask, &ac,
                             &alloc_gfp, &alloc_flags))
        return NULL;

    /*
	 * Forbid the first pass from falling back to types that fragment
	 * memory until all local zones are considered.
	 */
    alloc_flags |= alloc_flags_nofragment(zonelist_zone(ac.preferred_zoneref), gfp);

    /* First allocation attempt */
    page = get_page_from_freelist(alloc_gfp, order, alloc_flags, &ac);
    if (likely(page))
        goto out;

    alloc_gfp = gfp;
    ac.spread_dirty_pages = false;

    /*
	 * Restore the original nodemask if it was potentially replaced with
	 * &cpuset_current_mems_allowed to optimize the fast-path attempt.
	 */
    ac.nodemask = nodemask;

    page = __alloc_pages_slowpath(alloc_gfp, order, &ac);

    out:
    if (memcg_kmem_online() && (gfp & __GFP_ACCOUNT) && page &&
        unlikely(__memcg_kmem_charge_page(page, gfp, order) != 0)) {
        __free_pages(page, order);
        page = NULL;
    }

    trace_mm_page_alloc(page, order, alloc_gfp, ac.migratetype);
    kmsan_alloc_page(page, order, alloc_gfp);

    return page;
}
EXPORT_SYMBOL(__alloc_pages_noprof);
```

上面 `out:` 段的 `__memcg_kmem_charge_page()` 是 memcg 给内核对象记账的关卡：带 `__GFP_ACCOUNT` 的分配要向 memcg 报账，记不上账就把已经拿到的页还回去。所以 `alloc_pages()` 返回 NULL 未必是系统没内存，也可能是 **memcg 配额到顶**——这是容器里"内存明明还有却分配失败"的常见来路（见 [cgroup 内存控制（memcg）](/docs/CS/OS/Linux/mm/memcg.md)）。

```c
// include/linux/gfp.h
static inline struct page *
__alloc_pages(gfp_t gfp_mask, unsigned int order, int preferred_nid)
{
	return __alloc_pages_nodemask(gfp_mask, order, preferred_nid, NULL);
}

// mm/page_alloc.c
struct page *
__alloc_pages_nodemask(gfp_t gfp_mask, unsigned int order, int preferred_nid,
                            nodemask_t *nodemask)
{
    struct page *page;
    unsigned int alloc_flags = ALLOC_WMARK_LOW;
    gfp_t alloc_mask; /* The gfp_t that was actually used for allocation */
    struct alloc_context ac = { };

    /*
     * There are several places where we assume that the order value is sane
     * so bail out early if the request is out of bound.
     */
    if (unlikely(order >= MAX_ORDER)) {
        WARN_ON_ONCE(!(gfp_mask & __GFP_NOWARN));
        return NULL;
    }

    gfp_mask &= gfp_allowed_mask;
    alloc_mask = gfp_mask;
    if (!prepare_alloc_pages(gfp_mask, order, preferred_nid, nodemask, &ac, &alloc_mask, &alloc_flags))
        return NULL;

    /*
     * Forbid the first pass from falling back to types that fragment
     * memory until all local zones are considered.
     */
    alloc_flags |= alloc_flags_nofragment(ac.preferred_zoneref->zone, gfp_mask);

    /* First allocation attempt */
    page = get_page_from_freelist(alloc_mask, order, alloc_flags, &ac);
    if (likely(page))
        goto out;

    /*
     * Apply scoped allocation constraints. This is mainly about GFP_NOFS
     * resp. GFP_NOIO which has to be inherited for all allocation requests
     * from a particular context which has been marked by
     * memalloc_no{fs,io}_{save,restore}.
     */
    alloc_mask = current_gfp_context(gfp_mask);
    ac.spread_dirty_pages = false;

    /*
     * Restore the original nodemask if it was potentially replaced with
     * &cpuset_current_mems_allowed to optimize the fast-path attempt.
     */
    ac.nodemask = nodemask;

    page = __alloc_pages_slowpath(alloc_mask, order, &ac);

out:
    if (memcg_kmem_enabled() && (gfp_mask & __GFP_ACCOUNT) && page &&
        unlikely(__memcg_kmem_charge_page(page, gfp_mask, order) != 0)) {
        __free_pages(page, order);
        page = NULL;
    }

    return page;
}
EXPORT_SYMBOL(__alloc_pages_nodemask);
```

#### prepare_alloc_pages

```c

static inline bool prepare_alloc_pages(gfp_t gfp_mask, unsigned int order,
		int preferred_nid, nodemask_t *nodemask,
		struct alloc_context *ac, gfp_t *alloc_gfp,
		unsigned int *alloc_flags)
{
	ac->highest_zoneidx = gfp_zone(gfp_mask);
	ac->zonelist = node_zonelist(preferred_nid, gfp_mask);
	ac->nodemask = nodemask;
	ac->migratetype = gfp_migratetype(gfp_mask);

	if (cpusets_enabled()) {
		*alloc_gfp |= __GFP_HARDWALL;
		/*
		 * When we are in the interrupt context, it is irrelevant
		 * to the current task context. It means that any node ok.
		 */
		if (in_task() && !ac->nodemask)
			ac->nodemask = &cpuset_current_mems_allowed;
		else
			*alloc_flags |= ALLOC_CPUSET;
	}

	might_alloc(gfp_mask);

	if (should_fail_alloc_page(gfp_mask, order))
		return false;

	*alloc_flags = gfp_to_alloc_flags_cma(gfp_mask, *alloc_flags);

	/* Dirty zone balancing only done in the fast path */
	ac->spread_dirty_pages = (gfp_mask & __GFP_WRITE);

	/*
	 * The preferred zone is used for statistics but crucially it is
	 * also used as the starting point for the zonelist iterator. It
	 * may get reset for allocations that ignore memory policies.
	 */
	ac->preferred_zoneref = first_zones_zonelist(ac->zonelist,
					ac->highest_zoneidx, ac->nodemask);

	return true;
}
```



#### get_page_from_freelist

内核通过 get_page_from_freelist 函数，挨个遍历检查各个 NUMA 节点中的物理内存区域是否有足够的空闲内存可以满足本次的内存分配要求，
当找到符合内存分配标准的物理内存区域 zone 之后，接下来就会通过 rmqueue 函数进入到该物理内存区域 zone 对应的伙伴系统中分配物理内存
如果失败，调用＿alloc_ pagcs_slow pat 

```c
static struct page *
get_page_from_freelist(gfp_t gfp_mask, unsigned int order, int alloc_flags,
                        const struct alloc_context *ac)
{
    struct zoneref *z;
    struct zone *zone;
    struct pglist_data *last_pgdat_dirty_limit = NULL;
    bool no_fallback;

retry:
    /*
     * Scan zonelist, looking for a zone with enough free.
     * See also __cpuset_node_allowed() comment in kernel/cpuset.c.
     */
    no_fallback = alloc_flags & ALLOC_NOFRAGMENT;
    z = ac->preferred_zoneref;
    for_next_zone_zonelist_nodemask(zone, z, ac->highest_zoneidx,
                    ac->nodemask) {
        struct page *page;
        unsigned long mark;

        if (cpusets_enabled() &&
            (alloc_flags & ALLOC_CPUSET) &&
            !__cpuset_zone_allowed(zone, gfp_mask))
                continue;
        /*
         * When allocating a page cache page for writing, we
         * want to get it from a node that is within its dirty
         * limit, such that no single node holds more than its
         * proportional share of globally allowed dirty pages.
         * The dirty limits take into account the node's
         * lowmem reserves and high watermark so that kswapd
         * should be able to balance it without having to
         * write pages from its LRU list.
         *
         * XXX: For now, allow allocations to potentially
         * exceed the per-node dirty limit in the slowpath
         * (spread_dirty_pages unset) before going into reclaim,
         * which is important when on a NUMA setup the allowed
         * nodes are together not big enough to reach the
         * global limit.  The proper fix for these situations
         * will require awareness of nodes in the
         * dirty-throttling and the flusher threads.
         */
        if (ac->spread_dirty_pages) {
            if (last_pgdat_dirty_limit == zone->zone_pgdat)
                continue;

            if (!node_dirty_ok(zone->zone_pgdat)) {
                last_pgdat_dirty_limit = zone->zone_pgdat;
                continue;
            }
        }

        if (no_fallback && nr_online_nodes > 1 &&
            zone != ac->preferred_zoneref->zone) {
            int local_nid;

            /*
             * If moving to a remote node, retry but allow
             * fragmenting fallbacks. Locality is more important
             * than fragmentation avoidance.
             */
            local_nid = zone_to_nid(ac->preferred_zoneref->zone);
            if (zone_to_nid(zone) != local_nid) {
                alloc_flags &= ~ALLOC_NOFRAGMENT;
                goto retry;
            }
        }

        mark = wmark_pages(zone, alloc_flags & ALLOC_WMARK_MASK);
        if (!zone_watermark_fast(zone, order, mark,
                       ac->highest_zoneidx, alloc_flags,
                       gfp_mask)) {
            int ret;

#ifdef CONFIG_DEFERRED_STRUCT_PAGE_INIT
            /*
             * Watermark failed for this zone, but see if we can
             * grow this zone if it contains deferred pages.
             */
            if (static_branch_unlikely(&deferred_pages)) {
                if (_deferred_grow_zone(zone, order))
                    goto try_this_zone;
            }
#endif
            /* Checked here to keep the fast path fast */
            BUILD_BUG_ON(ALLOC_NO_WATERMARKS < NR_WMARK);
            if (alloc_flags & ALLOC_NO_WATERMARKS)
                goto try_this_zone;

            if (node_reclaim_mode == 0 ||
                !zone_allows_reclaim(ac->preferred_zoneref->zone, zone))
                continue;

            ret = node_reclaim(zone->zone_pgdat, gfp_mask, order);
            switch (ret) {
            case NODE_RECLAIM_NOSCAN:
                /* did not scan */
                continue;
            case NODE_RECLAIM_FULL:
                /* scanned but unreclaimable */
                continue;
            default:
                /* did we reclaim enough */
                if (zone_watermark_ok(zone, order, mark,
                    ac->highest_zoneidx, alloc_flags))
                    goto try_this_zone;

                continue;
            }
        }

try_this_zone:
        page = rmqueue(ac->preferred_zoneref->zone, zone, order,
                gfp_mask, alloc_flags, ac->migratetype);
        if (page) {
            prep_new_page(page, order, gfp_mask, alloc_flags);

            /*
             * If this is a high-order atomic allocation then check
             * if the pageblock should be reserved for the future
             */
            if (unlikely(order && (alloc_flags & ALLOC_HARDER)))
                reserve_highatomic_pageblock(page, zone, order);

            return page;
        } else {
#ifdef CONFIG_DEFERRED_STRUCT_PAGE_INIT
            /* Try again if zone has deferred pages */
            if (static_branch_unlikely(&deferred_pages)) {
                if (_deferred_grow_zone(zone, order))
                    goto try_this_zone;
            }
#endif
        }
    }

    /*
     * It's possible on a UMA machine to get through all zones that are
     * fragmented. If avoiding fragmentation, reset and try again.
     */
    if (no_fallback) {
        alloc_flags &= ~ALLOC_NOFRAGMENT;
        goto retry;
    }

    return NULL;
}
```

从指定的 zone 分配一个页。对于 order-0 的分配使用 per-CPU 空闲链表（pcplist）。


```c
// mm/page_alloc.c
static inline
struct page *rmqueue(struct zone *preferred_zone,
            struct zone *zone, unsigned int order,
            gfp_t gfp_flags, unsigned int alloc_flags,
            int migratetype)
{
    unsigned long flags;
    struct page *page;

    if (likely(order == 0)) {
        /*
         * MIGRATE_MOVABLE pcplist could have the pages on CMA area and
         * we need to skip it when CMA area isn't allowed.
         */
        if (!IS_ENABLED(CONFIG_CMA) || alloc_flags & ALLOC_CMA ||
                migratetype != MIGRATE_MOVABLE) {
            page = rmqueue_pcplist(preferred_zone, zone, gfp_flags,
                    migratetype, alloc_flags);
            goto out;
        }
    }

    /*
     * We most definitely don't want callers attempting to
     * allocate greater than order-1 page units with __GFP_NOFAIL.
     */
    WARN_ON_ONCE((gfp_flags & __GFP_NOFAIL) && (order > 1));
    spin_lock_irqsave(&zone->lock, flags);

    do {
        page = NULL;
        /*
         * order-0 request can reach here when the pcplist is skipped
         * due to non-CMA allocation context. HIGHATOMIC area is
         * reserved for high-order atomic allocation, so order-0
         * request should skip it.
         */
        if (order > 0 && alloc_flags & ALLOC_HARDER) {
            page = __rmqueue_smallest(zone, order, MIGRATE_HIGHATOMIC);
            if (page)
                trace_mm_page_alloc_zone_locked(page, order, migratetype);
        }
        if (!page)
            page = __rmqueue(zone, order, migratetype, alloc_flags);
    } while (page && check_new_pages(page, order));
    spin_unlock(&zone->lock);
    if (!page)
        goto failed;
    __mod_zone_freepage_state(zone, -(1 << order),
                  get_pcppage_migratetype(page));

    __count_zid_vm_events(PGALLOC, page_zonenum(page), 1 << order);
    zone_statistics(preferred_zone, zone);
    local_irq_restore(flags);

out:
    /* Separate test+clear to avoid unnecessary atomics */
    if (test_bit(ZONE_BOOSTED_WATERMARK, &zone->flags)) {
        clear_bit(ZONE_BOOSTED_WATERMARK, &zone->flags);
        wakeup_kswapd(zone, 0, 0, zone_idx(zone));
    }

    VM_BUG_ON_PAGE(page && bad_range(zone, page), page);
    return page;

failed:
    local_irq_restore(flags);
    return NULL;
}
```
加锁并从 per-CPU 链表（pcp list）中摘下页。

```c
static struct page *rmqueue_pcplist(struct zone *preferred_zone,
            struct zone *zone, gfp_t gfp_flags,
            int migratetype, unsigned int alloc_flags)
{
    struct per_cpu_pages *pcp;
    struct list_head *list;
    struct page *page;
    unsigned long flags;

    local_irq_save(flags);
    pcp = &this_cpu_ptr(zone->pageset)->pcp;
    list = &pcp->lists[migratetype];
    page = __rmqueue_pcplist(zone,  migratetype, alloc_flags, pcp, list);
    if (page) {
        __count_zid_vm_events(PGALLOC, page_zonenum(page), 1);
        zone_statistics(preferred_zone, zone);
    }
    local_irq_restore(flags);
    return page;
}
```


```c

/* Remove page from the per-cpu list, caller must protect the list */
static struct page *__rmqueue_pcplist(struct zone *zone, int migratetype,
			unsigned int alloc_flags,
			struct per_cpu_pages *pcp,
			struct list_head *list)
{
	struct page *page;

	do {
		if (list_empty(list)) {
			pcp->count += rmqueue_bulk(zone, 0,
					READ_ONCE(pcp->batch), list,
					migratetype, alloc_flags);
			if (unlikely(list_empty(list)))
				return NULL;
		}

		page = list_first_entry(list, struct page, lru);
		list_del(&page->lru);
		pcp->count--;
	} while (check_new_pcp(page));

	return page;
}

/*
 * Obtain a specified number of elements from the buddy allocator, all under
 * a single hold of the lock, for efficiency.  Add them to the supplied list.
 * Returns the number of new pages which were placed at *list.
 */
static int rmqueue_bulk(struct zone *zone, unsigned int order,
            unsigned long count, struct list_head *list,
            int migratetype, unsigned int alloc_flags)
{
    int i, alloced = 0;

    spin_lock(&zone->lock);
    for (i = 0; i < count; ++i) {
        struct page *page = __rmqueue(zone, order, migratetype,
                                alloc_flags);
        if (unlikely(page == NULL))
            break;

        if (unlikely(check_pcp_refill(page)))
            continue;

        /*
         * Split buddy pages returned by expand() are received here in
         * physical page order. The page is added to the tail of
         * caller's list. From the callers perspective, the linked list
         * is ordered by page number under some conditions. This is
         * useful for IO devices that can forward direction from the
         * head, thus also in the physical page order. This is useful
         * for IO devices that can merge IO requests if the physical
         * pages are ordered properly.
         */
        list_add_tail(&page->lru, list);
        alloced++;
        if (is_migrate_cma(get_pcppage_migratetype(page)))
            __mod_zone_page_state(zone, NR_FREE_CMA_PAGES,
                          -(1 << order));
    }

    /*
     * i pages were removed from the buddy list even if some leak due
     * to check_pcp_refill failing so adjust NR_FREE_PAGES based
     * on i. Do not confuse with 'alloced' which is the number of
     * pages added to the pcp list.
     */
    __mod_zone_page_state(zone, NR_FREE_PAGES, -(i << order));
    spin_unlock(&zone->lock);
    return alloced;
}
```

遍历指定 migratetype 的空闲链表，从 freelist 中取出可用的最小页。


```c
static __always_inline
struct page *__rmqueue_smallest(struct zone *zone, unsigned int order,
                        int migratetype)
{
    unsigned int current_order;
    struct free_area *area;
    struct page *page;

    /* Find a page of the appropriate size in the preferred list */
    for (current_order = order; current_order < MAX_ORDER; ++current_order) {
        area = &(zone->free_area[current_order]);
        page = get_page_from_free_area(area, migratetype);
        if (!page)
            continue;
        del_page_from_free_list(page, zone, current_order);
        expand(zone, page, order, current_order, migratetype);
        set_pcppage_migratetype(page, migratetype);
        return page;
    }

    return NULL;
}
```

```c
/*
 * Do the hard work of removing an element from the buddy allocator.
 * Call me with the zone->lock already held.
 */
static __always_inline struct page *
__rmqueue(struct zone *zone, unsigned int order, int migratetype,
                        unsigned int alloc_flags)
{
    struct page *page;

    if (IS_ENABLED(CONFIG_CMA)) {
        /*
         * Balance movable allocations between regular and CMA areas by
         * allocating from CMA when over half of the zone's free memory
         * is in the CMA area.
         */
        if (alloc_flags & ALLOC_CMA &&
            zone_page_state(zone, NR_FREE_CMA_PAGES) >
            zone_page_state(zone, NR_FREE_PAGES) / 2) {
            page = __rmqueue_cma_fallback(zone, order);
            if (page)
                goto out;
        }
    }
retry:
    page = __rmqueue_smallest(zone, order, migratetype);
    if (unlikely(!page)) {
        if (alloc_flags & ALLOC_CMA)
            page = __rmqueue_cma_fallback(zone, order);

        if (!page && __rmqueue_fallback(zone, order, migratetype,
                                alloc_flags))
            goto retry;
    }
out:
    if (page)
        trace_mm_page_alloc_zone_locked(page, order, migratetype);
    return page;
}
```


### alloc_pages_slowpath

当进入 `__alloc_pages_slowpath` 时，往往意味着伙伴系统中可用的连续内存不足，可能有多种情况：

- **空闲内存够、但碎片太多**：找不到连续的大块内存，需要内存压缩（`__alloc_pages_direct_compact`）；
- **空闲内存不足**：需要把已占用的内存释放出来，这就是内存回收（reclaim）。

回收有个前提——不能丢数据。可回收页要么在别处有副本（如文件页），要么能被换出到磁盘、需要时再换回来（如匿名页），所以回收之前要先保证这些内容有去处。

`__alloc_pages_slowpath` 的主干调用链：

```
__alloc_pages_slowpath
  - wake_all_kswapds
  - get_page_from_freelist
  - __alloc_pages_direct_compact
  - __gfp_pfmemalloc_flags
  - __alloc_pages_direct_reclaim → __perform_reclaim → try_to_free_pages → shrink_zones → shrink_node
      - prepare_scan_count
      - shrink_node_memcgs
        - shrink_lruvec
          - get_scan_count
          - shrink_list
            - shrink_inactive_list
              - lru_add_drain
              - isolate_lru_folios
              - shrink_folio_list
                - folio_check_references
                - add_to_swap
                - try_to_unmap
                - pageout
                - move_folios_to_lru
                - free_unref_page_list
            - shrink_active_list
        - shrink_slab
  - __alloc_pages_may_oom → out_of_memory
```

回收这条链本身已足够复杂：水位线与 kswapd 的唤醒时机、LRU 链表如何老化、`scan_control` 怎么决定扫描范围、`shrink_folio_list` 如何逐页判去留、shrinker 与 memcg 回收——都已独立成篇，见 [内存回收（Reclaim）](/docs/CS/OS/Linux/mm/Reclaim.md)。分配彻底失败后退化到 OOM killer 的终局见 [OOM killer](/docs/CS/OS/Linux/mm/oom.md)。

## free

释放由 alloc_pages() 分配的页。
- page：由 alloc_pages() 返回的页指针。
- order：分配的阶（order）。

该函数可以释放非复合页（non-compound）的多页分配。它不会检查传入的 @order 是否与分配时的 order 一致，因此很容易造成内存泄漏。释放超过已分配大小的内存大概率会触发告警。

如果该页最后一次引用是投机性的（speculative），它会由 put_page() 释放，而 put_page() 只会释放非复合分配中的第一页。

为了防止剩余的页被泄漏，这里会释放后续各页。如果你想用页的引用计数来决定何时释放这次分配，应当分配一个复合页（compound page），并使用 put_page() 而非 __free_pages()。

调用上下文（Context）：可以在中断上下文或持有普通自旋锁时调用，但不能在 NMI 上下文或持有 raw spinlock 时调用。

```c
void __free_pages(struct page *page, unsigned int order)
{
	if (put_page_testzero(page))
		free_the_page(page, order);
	else if (!PageHead(page))
		while (order-- > 0)
			free_the_page(page + (1 << order), order);
}
EXPORT_SYMBOL(__free_pages);
```


```c
static inline void free_the_page(struct page *page, unsigned int order)
{
    if (order == 0)     /* Via pcp? */
        free_unref_page(page);
    else
        __free_pages_ok(page, order, FPI_NONE);
}
```

### free_unref_page



```c

void free_unref_page(struct page *page)
{
	unsigned long flags;
	unsigned long pfn = page_to_pfn(page);

	if (!free_unref_page_prepare(page, pfn))
		return;

	local_irq_save(flags);
	free_unref_page_commit(page, pfn);
	local_irq_restore(flags);
}


static void free_unref_page_commit(struct page *page, unsigned long pfn)
{
	struct zone *zone = page_zone(page);
	struct per_cpu_pages *pcp;
	int migratetype;

	migratetype = get_pcppage_migratetype(page);
	__count_vm_event(PGFREE);

	/*
	 * We only track unmovable, reclaimable and movable on pcp lists.
	 * Free ISOLATE pages back to the allocator because they are being
	 * offlined but treat HIGHATOMIC as movable pages so we can get those
	 * areas back if necessary. Otherwise, we may have to free
	 * excessively into the page allocator
	 */
	if (migratetype >= MIGRATE_PCPTYPES) {
		if (unlikely(is_migrate_isolate(migratetype))) {
			free_one_page(zone, page, pfn, 0, migratetype,
				      FPI_NONE);
			return;
		}
		migratetype = MIGRATE_MOVABLE;
	}

	pcp = &this_cpu_ptr(zone->pageset)->pcp;
	list_add(&page->lru, &pcp->lists[migratetype]);
	pcp->count++;
	if (pcp->count >= READ_ONCE(pcp->high))
		free_pcppages_bulk(zone, READ_ONCE(pcp->batch), pcp);
}
```

### __free_pages_ok

```c

static void __free_pages_ok(struct page *page, unsigned int order,
			    fpi_t fpi_flags)
{
	unsigned long flags;
	int migratetype;
	unsigned long pfn = page_to_pfn(page);
	struct zone *zone = page_zone(page);

	if (!free_pages_prepare(page, order, true, fpi_flags))
		return;

	migratetype = get_pfnblock_migratetype(page, pfn);

	spin_lock_irqsave(&zone->lock, flags);
	if (unlikely(has_isolate_pageblock(zone) ||
		is_migrate_isolate(migratetype))) {
		migratetype = get_pfnblock_migratetype(page, pfn);
	}
	__free_one_page(page, pfn, zone, order, migratetype, fpi_flags);
	spin_unlock_irqrestore(&zone->lock, flags);

	__count_vm_events(PGFREE, 1 << order);
}
```

free_one_page
```c
static void free_one_page(struct zone *zone,
                struct page *page, unsigned long pfn,
                unsigned int order,
                int migratetype, fpi_t fpi_flags)
{
    spin_lock(&zone->lock);
    if (unlikely(has_isolate_pageblock(zone) ||
        is_migrate_isolate(migratetype))) {
        migratetype = get_pfnblock_migratetype(page, pfn);
    }
    __free_one_page(page, pfn, zone, order, migratetype, fpi_flags);
    spin_unlock(&zone->lock);
}
```

```c
/*
 * Freeing function for a buddy system allocator.
 *
 * The concept of a buddy system is to maintain direct-mapped table
 * (containing bit values) for memory blocks of various "orders".
 * The bottom level table contains the map for the smallest allocatable
 * units of memory (here, pages), and each level above it describes
 * pairs of units from the levels below, hence, "buddies".
 * At a high level, all that happens here is marking the table entry
 * at the bottom level available, and propagating the changes upward
 * as necessary, plus some accounting needed to play nicely with other
 * parts of the VM system.
 * At each level, we keep a list of pages, which are heads of continuous
 * free pages of length of (1 << order) and marked with PageBuddy.
 * Page's order is recorded in page_private(page) field.
 * So when we are allocating or freeing one, we can derive the state of the
 * other.  That is, if we allocate a small block, and both were
 * free, the remainder of the region must be split into blocks.
 * If a block is freed, and its buddy is also free, then this
 * triggers coalescing into a block of larger size.
 *
 * -- nyc
 */

static inline void __free_one_page(struct page *page,
        unsigned long pfn,
        struct zone *zone, unsigned int order,
        int migratetype, fpi_t fpi_flags)
{
    struct capture_control *capc = task_capc(zone);
    unsigned long buddy_pfn;
    unsigned long combined_pfn;
    unsigned int max_order;
    struct page *buddy;
    bool to_tail;

    max_order = min_t(unsigned int, MAX_ORDER - 1, pageblock_order);

    VM_BUG_ON(!zone_is_initialized(zone));
    VM_BUG_ON_PAGE(page->flags & PAGE_FLAGS_CHECK_AT_PREP, page);

    VM_BUG_ON(migratetype == -1);
    if (likely(!is_migrate_isolate(migratetype)))
        __mod_zone_freepage_state(zone, 1 << order, migratetype);

    VM_BUG_ON_PAGE(pfn & ((1 << order) - 1), page);
    VM_BUG_ON_PAGE(bad_range(zone, page), page);

continue_merging:
    while (order < max_order) {
        if (compaction_capture(capc, page, order, migratetype)) {
            __mod_zone_freepage_state(zone, -(1 << order),
                                migratetype);
            return;
        }
        buddy_pfn = __find_buddy_pfn(pfn, order);
        buddy = page + (buddy_pfn - pfn);

        if (!pfn_valid_within(buddy_pfn))
            goto done_merging;
        if (!page_is_buddy(page, buddy, order))
            goto done_merging;
        /*
         * Our buddy is free or it is CONFIG_DEBUG_PAGEALLOC guard page,
         * merge with it and move up one order.
         */
        if (page_is_guard(buddy))
            clear_page_guard(zone, buddy, order, migratetype);
        else
            del_page_from_free_list(buddy, zone, order);
        combined_pfn = buddy_pfn & pfn;
        page = page + (combined_pfn - pfn);
        pfn = combined_pfn;
        order++;
    }
    if (order < MAX_ORDER - 1) {
        /* If we are here, it means order is >= pageblock_order.
         * We want to prevent merge between freepages on isolate
         * pageblock and normal pageblock. Without this, pageblock
         * isolation could cause incorrect freepage or CMA accounting.
         *
         * We don't want to hit this code for the more frequent
         * low-order merging.
         */
        if (unlikely(has_isolate_pageblock(zone))) {
            int buddy_mt;

            buddy_pfn = __find_buddy_pfn(pfn, order);
            buddy = page + (buddy_pfn - pfn);
            buddy_mt = get_pageblock_migratetype(buddy);

            if (migratetype != buddy_mt
                    && (is_migrate_isolate(migratetype) ||
                        is_migrate_isolate(buddy_mt)))
                goto done_merging;
        }
        max_order = order + 1;
        goto continue_merging;
    }

done_merging:
    set_buddy_order(page, order);

    if (fpi_flags & FPI_TO_TAIL)
        to_tail = true;
    else if (is_shuffle_order(order))
        to_tail = shuffle_pick_tail();
    else
        to_tail = buddy_merge_likely(pfn, buddy_pfn, page, order);

    if (to_tail)
        add_to_free_list_tail(page, zone, order, migratetype);
    else
        add_to_free_list(page, zone, order, migratetype);

    /* Notify page reporting subsystem of freed page */
    if (!(fpi_flags & FPI_SKIP_REPORT_NOTIFY))
        page_reporting_notify_free(order);
}
```


free_pages_ok


```c
static void __free_pages_ok(struct page *page, unsigned int order,
                fpi_t fpi_flags)
{
    unsigned long flags;
    int migratetype;
    unsigned long pfn = page_to_pfn(page);

    if (!free_pages_prepare(page, order, true))
        return;

    migratetype = get_pfnblock_migratetype(page, pfn);
    local_irq_save(flags);
    __count_vm_events(PGFREE, 1 << order);
    free_one_page(page_zone(page), page, pfn, order, migratetype,
              fpi_flags);
    local_irq_restore(flags);
}
```



## Links

- [内存管理知识地图](/docs/CS/OS/Linux/mm/README.md)

## References

1. [一步一图带你深入理解 Linux 物理内存管理](https://mp.weixin.qq.com/s?__biz=Mzg2MzU3Mjc3Ng==&mid=2247486879&idx=1&sn=0bcc59a306d59e5199a11d1ca5313743&chksm=ce77cbd8f90042ce06f5086b1c976d1d2daa57bc5b768bac15f10ee3dc85874bbeddcd649d88&cur_album_id=2559805446807928833&scene=189#wechat_redirect)
