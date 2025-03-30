## Introduction


linux 支持 NUMA (Non Uniform Memory Access)。物理内存管理的第一个层次就是介质的管理，pg_data_t结构就描述了介质。一般而言，我们的内存管理介质只有内存，并且它是均匀的，所以可以简单地认为系统中只有一个 pg_data_t 对象

On NUMA machines, each NUMA node would have a pg_data_t to describe it's memory layout. On UMA machines there is a single pglist_data which describes the whole memory.
Memory statistics and page replacement data structures are maintained on a per-zone basis.

linux系统中可以用numactl命令来查看系统node信息


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

内存被划分为节点. 每个节点关联到系统中的一个处理器, 内核中表示为pg_data_t的实例. 系统中每个节点被链接到一个以NULL结尾的pgdat_list链表中<而其中的每个节点利用pg_data_tnode_next字段链接到下一节．而对于PC这种UMA结构的机器来说, 只使用了一个成为contig_page_data的静态pg_data_t结构.
各个节点又被划分为内存管理区域, 一个管理区域通过struct zone_struct描述, 其被定义为zone_t, 用以表示内存的某个范围, 低端范围的16MB被描述为ZONE_DMA, 某些工业标准体系结构中的(ISA)设备需要用到它, 然后是可直接映射到内核的普通内存域ZONE_NORMAL,最后是超出了内核段的物理地址域ZONE_HIGHMEM, 被称为高端内存. 是系统中预留的可用内存空间, 不能被内核直接映射

> 但是Linux内核又把各个物理内存节点分成个不同的管理区域zone, 这是为什么呢?
> 因为实际的计算机体系结构有硬件的诸多限制, 这限制了页框可以使用的方式. 尤其是, Linux内核必须处理80x86体系结构的两种硬件约束.
> - ISA总线的直接内存存储DMA处理器有一个严格的限制 : 他们只能对RAM的前16MB进行寻址
> - 在具有大容量RAM的现代32位计算机中, CPU不能直接访问所有的物理地址, 因为线性地址空间太小, 内核不可能直接映射所有物理内存到线性地址空间, 我们会在后面典型架构(x86)上内存区域划分详细讲解x86_32上的内存区域划分
> 因此Linux内核对不同区域的内存需要采用不同的管理方式和映射方式, 因此内核将物理地址或者成用zone_t表示的不同地址区域





## Zone

Often hardware poses restrictions on how different physical memory ranges can be accessed. 
In some cases, devices cannot perform DMA to all the addressable memory. 
In other cases, the size of the physical memory exceeds the maximal addressable size of virtual memory and special actions are required to access portions of the memory.
Linux groups memory pages into zones according to their possible usage.
For example, ZONE_DMA will contain memory that can be used by devices for DMA, ZONE_HIGHMEM will contain memory that is not permanently mapped into kernel’s address space and ZONE_NORMAL will contain normally addressed pages.
The actual layout of the memory zones is hardware dependent as not all architectures define all zones, and requirements for DMA are different for different platforms.


Many multi-processor machines are NUMA - Non-Uniform Memory Access - systems. 
In such systems the memory is arranged into banks that have different access latency depending on the “distance” from the processor. 
Each bank is referred to as a node and for each node Linux constructs an independent memory management subsystem.
A node has its own set of zones, lists of free and used pages and various statistics counters.
You can find more details about NUMA in What is NUMA?` and in NUMA Memory Policy.

## Page cache

The physical memory is volatile and the common case for getting data into the memory is to read it from files.
Whenever a file is read, the data is put into the page cache to avoid expensive disk access on the subsequent reads.
Similarly, when one writes to a file, the data is placed in the page cache and eventually gets into the backing storage device. 
The written pages are marked as dirty and when Linux decides to reuse them for other purposes, it makes sure to synchronize the file contents on the device with the updated data.

## Anonymous Memory

The anonymous memory or anonymous mappings represent memory that is not backed by a filesystem. 
Such mappings are implicitly created for program’s stack and heap or by explicit calls to mmap(2) system call. 
Usually, the anonymous mappings only define virtual memory areas that the program is allowed to access. 
The read accesses will result in creation of a page table entry that references a special physical page filled with zeroes.
When the program performs a write, a regular physical page will be allocated to hold the written data. 
The page will be marked dirty and if the kernel decides to repurpose it, the dirty page will be swapped out.

## Reclaim

Throughout the system lifetime, a physical page can be used for storing different types of data. 
It can be kernel internal data structures, DMA’able buffers for device drivers use, data read from a filesystem, memory allocated by user space processes etc.

Depending on the page usage it is treated differently by the Linux memory management. 
The pages that can be freed at any time, either because they cache the data available elsewhere, for instance, on a hard disk, or because they can be swapped out, again, to the hard disk, are called reclaimable. 
The most notable categories of the reclaimable pages are page cache and anonymous memory.
In most cases, the pages holding internal kernel data and used as DMA buffers cannot be repurposed, and they remain pinned until freed by their user. Such pages are called unreclaimable. 
However, in certain circumstances, even pages occupied with kernel data structures can be reclaimed. For instance, in-memory caches of filesystem metadata can be re-read from the storage device and therefore it is possible to discard them from the main memory when system is under memory pressure.
The process of freeing the reclaimable physical memory pages and repurposing them is called (surprise!) reclaim. 
Linux can reclaim pages either asynchronously or synchronously, depending on the state of the system. 
When the system is not loaded, most of the memory is free and allocation requests will be satisfied immediately from the free pages supply. 
As the load increases, the amount of the free pages goes down and when it reaches a certain threshold (low watermark), an allocation request will awaken the kswapd daemon. 
It will asynchronously scan memory pages and either just free them if the data they contain is available elsewhere, or evict to the backing storage device (remember those dirty pages?). 
As memory usage increases even more and reaches another threshold - min watermark - an allocation will trigger direct reclaim. 
In this case allocation is stalled until enough memory pages are reclaimed to satisfy the request.

Compaction

As the system runs, tasks allocate and free the memory and it becomes fragmented. 
Although with virtual memory it is possible to present scattered physical pages as virtually contiguous range, sometimes it is necessary to allocate large physically contiguous memory areas.
Such need may arise, for instance, when a device driver requires a large buffer for DMA, or when THP allocates a huge page. 
Memory compaction addresses the fragmentation issue.
This mechanism moves occupied pages from the lower part of a memory zone to free pages in the upper part of the zone. When a compaction scan is finished free pages are grouped together at the beginning of the zone and allocations of large physically contiguous areas become possible.
Like reclaim, the compaction may happen asynchronously in the kcompactd daemon or synchronously as a result of a memory allocation request.
## OOM killer
It is possible that on a loaded machine memory will be exhausted and the kernel will be unable to reclaim enough memory to continue to operate. 
In order to save the rest of the system, it invokes the OOM killer.
The OOM killer selects a task to sacrifice for the sake of the overall system health. 
The selected task is killed in a hope that after it exits enough memory will be freed to continue normal operation.

## memory model


内核中如何组织管理这些物理内存页 struct page 的方式我们称之为做物理内存模型
- FLATMEM
- DISCONTIGMEM
- SPARSEMEM


这三种内存模型的区别在于对page的管理方式和page与pfn的转换不同


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


### SPARSEMEM

SPARSEMEM_VMEMMAP是虚拟映射，走页表
SPARSEMEM 稀疏内存模型的核心思想就是对粒度更小的连续内存块进行精细的管理，用于管理连续内存块的单元被称作 section 。物理页大小为 4k 的情况下， section 的大小为 128M ，物理页大小为 16k 的情况下， section 的大小为 512M

在内核中用 struct mem_section 结构体表示 SPARSEMEM 模型中的 section

将所有的mem_section中page 都抽象到一个虚拟数组vmemmap，这样在进行struct page *和pfn转换时，之间使用vmemmap数组即可，如下转换（位于include\asm-generic\memory_model.h)


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

Allocate a page from the given zone. Use pcplists for order-0 allocations.


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
Lock and remove page from the per-cpu list

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

Go through the free lists for the given migratetype and remove the smallest available page from the freelists


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

内存降到 WMARK_LOW 后进入slowpath

__alloc_pages_slowpath
  - wake_all_kswapds
  - __alloc_pages_direct_compact
  - __gfp_pfmemalloc_flags
  - get_page_from_freelist
  - __alloc_pages_direct_reclaim - __perform_reclaim - try_to_free_pages - shrink_zones - shrink_node
    - prepare_scan_count
    - shrink_node_memcgs
      - shrink_lruvec
        - get_scan_count
        - shrink_list
          - shrink_inactive_list
          - lru_add_drain
          - isolate_lru_follos
          - shrink_follo_list
          - follo_check_references
          - add_to_swap
          - try_to_unmap
          - pageout
          - free_unref_page_list
          - move_follos_to_lru
          - free_unref_page_list
        - shrink_active_list
          - lru_add_drain
          - islate_lr_follos
          - follo_referenced
          - move_follos_to_lru
          - free_unref_page_list
      - shrink_slab


当进入_alloc_pages_slowpath时，往往意味着伙伴系统中可用的连续内存不足，可能有多种情况。
第1种情况，空闲内存足够，但内存碎片过多，找不到连续的大段内存  此时需要进行compact _alloc_pages_direct_compact 			
第2种情况，空闲内存不足， 需要释放一些已经被占用的内存，这就是内存回收，也就是reclaim

内存释放之前需要保证现有内存内容不丢失 一种方法是对被换出的部分进行落盘 需要时再加载回来



#### try_to_free_pages

某一次内存回收过程中扫描哪些node、 过程中可以进行哪些操作以及退出条件等控制了整个 扫描过程。这些由scan_control结构体定义，调用栈中 try_to_free_pages函数为它赋值

```c
unsigned long try_to_free_pages(struct zonelist *zonelist, int order,
                                gfp_t gfp_mask, nodemask_t *nodemask)
{
    unsigned long nr_reclaimed;
    struct scan_control sc = {
        .nr_to_reclaim = SWAP_CLUSTER_MAX,
        .gfp_mask = current_gfp_context(gfp_mask),
        .reclaim_idx = gfp_zone(gfp_mask),
        .order = order,
        .nodemask = nodemask,
        .priority = DEF_PRIORITY,
        .may_writepage = !laptop_mode,
        .may_unmap = 1,
        .may_swap = 1,
    };

    /*
	 * scan_control uses s8 fields for order, priority, and reclaim_idx.
	 * Confirm they are large enough for max values.
	 */
    BUILD_BUG_ON(MAX_PAGE_ORDER >= S8_MAX);
    BUILD_BUG_ON(DEF_PRIORITY > S8_MAX);
    BUILD_BUG_ON(MAX_NR_ZONES > S8_MAX);

    /*
	 * Do not enter reclaim if fatal signal was delivered while throttled.
	 * 1 is returned so that the page allocator does not OOM kill at this
	 * point.
	 */
    if (throttle_direct_reclaim(sc.gfp_mask, zonelist, nodemask))
        return 1;

    set_task_reclaim_state(current, &sc.reclaim_state);
    trace_mm_vmscan_direct_reclaim_begin(order, sc.gfp_mask);

    nr_reclaimed = do_try_to_free_pages(zonelist, &sc);

    trace_mm_vmscan_direct_reclaim_end(nr_reclaimed);
    set_task_reclaim_state(current, NULL);

    return nr_reclaimed;
}
```


```c
struct scan_control {
    /* How many pages shrink_list() should reclaim */
    unsigned long nr_to_reclaim;

    /*
	 * Nodemask of nodes allowed by the caller. If NULL, all nodes
	 * are scanned.
	 */
    nodemask_t	*nodemask;

    /*
	 * The memory cgroup that hit its limit and as a result is the
	 * primary target of this reclaim invocation.
	 */
    struct mem_cgroup *target_mem_cgroup;

    /*
	 * Scan pressure balancing between anon and file LRUs
	 */
    unsigned long	anon_cost;
    unsigned long	file_cost;

    /* Can active folios be deactivated as part of reclaim? */
    #define DEACTIVATE_ANON 1
    #define DEACTIVATE_FILE 2
    unsigned int may_deactivate:2;
    unsigned int force_deactivate:1;
    unsigned int skipped_deactivate:1;

    /* Writepage batching in laptop mode; RECLAIM_WRITE */
    unsigned int may_writepage:1;

    /* Can mapped folios be reclaimed? */
    unsigned int may_unmap:1;

    /* Can folios be swapped as part of reclaim? */
    unsigned int may_swap:1;

    /* Not allow cache_trim_mode to be turned on as part of reclaim? */
    unsigned int no_cache_trim_mode:1;

    /* Has cache_trim_mode failed at least once? */
    unsigned int cache_trim_mode_failed:1;

    /* Proactive reclaim invoked by userspace through memory.reclaim */
    unsigned int proactive:1;

    /*
	 * Cgroup memory below memory.low is protected as long as we
	 * don't threaten to OOM. If any cgroup is reclaimed at
	 * reduced force or passed over entirely due to its memory.low
	 * setting (memcg_low_skipped), and nothing is reclaimed as a
	 * result, then go back for one more cycle that reclaims the protected
	 * memory (memcg_low_reclaim) to avert OOM.
	 */
    unsigned int memcg_low_reclaim:1;
    unsigned int memcg_low_skipped:1;

    unsigned int hibernation_mode:1;

    /* One of the zones is ready for compaction */
    unsigned int compaction_ready:1;

    /* There is easily reclaimable cold cache in the current node */
    unsigned int cache_trim_mode:1;

    /* The file folios on the current node are dangerously low */
    unsigned int file_is_tiny:1;

    /* Always discard instead of demoting to lower tier memory */
    unsigned int no_demotion:1;

    /* Allocation order */
    s8 order;

    /* Scan (total_size >> priority) pages at once */
    s8 priority;

    /* The highest zone to isolate folios for reclaim from */
    s8 reclaim_idx;

    /* This context's GFP mask */
    gfp_t gfp_mask;

    /* Incremented by the number of inactive pages that were scanned */
    unsigned long nr_scanned;

    /* Number of pages freed so far during a call to shrink_zones() */
    unsigned long nr_reclaimed;

    struct {
        unsigned int dirty;
        unsigned int unqueued_dirty;
        unsigned int congested;
        unsigned int writeback;
        unsigned int immediate;
        unsigned int file_taken;
        unsigned int taken;
    } nr;

    /* for recording the reclaimed slab by now */
    struct reclaim_state reclaim_state;
};
```





## free

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

- [Linux Memory](/docs/CS/OS/Linux/mm/memory.md)

## References

1. [一步一图带你深入理解 Linux 物理内存管理](https://mp.weixin.qq.com/s?__biz=Mzg2MzU3Mjc3Ng==&mid=2247486879&idx=1&sn=0bcc59a306d59e5199a11d1ca5313743&chksm=ce77cbd8f90042ce06f5086b1c976d1d2daa57bc5b768bac15f10ee3dc85874bbeddcd649d88&cur_album_id=2559805446807928833&scene=189#wechat_redirect)