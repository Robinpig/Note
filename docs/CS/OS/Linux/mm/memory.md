## Introduction

内核的正式入口是 start_kernel, 前面的讨论基本都发生在 start_kernel 之后，但实际上在它之 前我们就需要访问内存了， 那么首先要做的就是识别系统中的内存， 由 detect_memo-1 y实现。
根据硬件和BIOS的配置，detect_memo1-y依次调用detect_memory_e820、 cletect_memo1-y_e801 和 cletect_memm-y_88, 最终哪一个函数起作用取决于硬件和 BIOS 的配置。 后二者作为兼容老机器 存在， 此处主要以现代计算机中的 cletect_memor y_e820 为主进行分析。
三者都是通过与 BIOS 通信实现的， 给 BIOS 发送 OxlS 中断， 根据 BIOS 反馈的信息提取内存 信息。 以detect_memory_e820为例，每一条有效的信息都被存储在boot_params.e820_table数组中
(类型为boot_e820_entr y)。
boot_e820_entl-y有3 个字段， addr和size字段分别表示一段内存的起始地址和大小，type字段表示这段内存的用途。



## init

Set up kernel memory allocators
called by [start_kernel](/docs/CS/OS/Linux/init.md?id=start_kernel)
```c
// init/main.c
static void __init mm_init(void)
{
	/*
	 * page_ext requires contiguous pages,
	 * bigger than MAX_ORDER unless SPARSEMEM.
	 */
	page_ext_init_flatmem();
	init_mem_debugging_and_hardening();
	kfence_alloc_pool();
	report_meminit();
	stack_depot_init();
```
mem init
```
	mem_init();
	mem_init_print_info();
	/* page_owner must be initialized after buddy is ready */
	page_ext_init_flatmem_late();
	kmem_cache_init();
	kmemleak_init();
	pgtable_init();
	debug_objects_mem_init();
	vmalloc_init();
	/* Should be run before the first non-init thread is created */
	init_espfix_bsp();
	/* Should be run after espfix64 is set up. */
	pti_init();
}
```

setup_arch -> paging_init

```c
// arch/x86/mm/init_64.c
void __init paging_init(void)
{
	sparse_init();

	/*
	 * clear the default setting with node 0
	 * note: don't use nodes_clear here, that is really clearing when
	 *	 numa support is not compiled in, and later node_set_state
	 *	 will not set it back.
	 */
	node_clear_state(0, N_MEMORY);
	node_clear_state(0, N_NORMAL_MEMORY);

	zone_sizes_init();
}
```


On NUMA machines, each NUMA node would have a pg_data_t to describe it's memory layout. On UMA machines there is a single pglist_data which describes the whole memory.

Memory statistics and page replacement data structures are maintained on a per-zone basis.

```c
typedef struct pglist_data {
	/*
	 * node_zones contains just the zones for THIS node. Not all of the
	 * zones may be populated, but it is the full list. It is referenced by
	 * this node's node_zonelists as well as other node's node_zonelists.
	 */
	struct zone node_zones[MAX_NR_ZONES];

	/*
	 * node_zonelists contains references to all zones in all nodes.
	 * Generally the first zones will be references to this node's
	 * node_zones.
	 */
	struct zonelist node_zonelists[MAX_ZONELISTS];

    int nr_zones; /* number of populated zones in this node */
    
    unsigned long node_start_pfn;
	unsigned long node_present_pages; /* total number of physical pages */
	unsigned long node_spanned_pages; /* total size of physical page
					     range, including holes */
	int node_id;
	wait_queue_head_t kswapd_wait;
	wait_queue_head_t pfmemalloc_wait;
	struct task_struct *kswapd;	/* Protected by
					   mem_hotplug_begin/end() */
	int kswapd_order;
	enum zone_type kswapd_highest_zoneidx;

	int kswapd_failures;		/* Number of 'reclaimed == 0' runs */
	
	/* Fields commonly accessed by the page reclaim scanner */

	/*
	 * NOTE: THIS IS UNUSED IF MEMCG IS ENABLED.
	 *
	 * Use mem_cgroup_lruvec() to look up lruvecs.
	 */
	struct lruvec		__lruvec;

	unsigned long		flags;

	ZONE_PADDING(_pad2_)

	/* Per-node vmstats */
	struct per_cpu_nodestat __percpu *per_cpu_nodestats;
	atomic_long_t		vm_stat[NR_VM_NODE_STAT_ITEMS];
} pg_data_t;
```


#### alloc_pages

```c
static inline struct page *alloc_pages(gfp_t gfp_mask, unsigned int order)
{
	return alloc_pages_node(numa_node_id(), gfp_mask, order);
}
```
This is the 'heart' of the zoned buddy allocator.

```c
struct page *__alloc_pages(gfp_t gfp, unsigned int order, int preferred_nid,
							nodemask_t *nodemask)
{
	struct page *page;
	unsigned int alloc_flags = ALLOC_WMARK_LOW;
	gfp_t alloc_gfp; /* The gfp_t that was actually used for allocation */
	struct alloc_context ac = { };

	/*
	 * There are several places where we assume that the order value is sane
	 * so bail out early if the request is out of bound.
	 */
	if (unlikely(order >= MAX_ORDER)) {
		WARN_ON_ONCE(!(gfp & __GFP_NOWARN));
		return NULL;
	}

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
	alloc_flags |= alloc_flags_nofragment(ac.preferred_zoneref->zone, gfp);

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
	if (memcg_kmem_enabled() && (gfp & __GFP_ACCOUNT) && page &&
	    unlikely(__memcg_kmem_charge_page(page, gfp, order) != 0)) {
		__free_pages(page, order);
		page = NULL;
	}

	trace_mm_page_alloc(page, order, alloc_gfp, ac.migratetype);

	return page;
}
```

#### free_pages

Free pages allocated with alloc_pages().

- page: The page pointer returned from alloc_pages().
- order: The order of the allocation.

This function can free multi-page allocations that are not compound
pages.  It does not check that the @order passed in matches that of
the allocation, so it is easy to leak memory.  Freeing more memory
than was allocated will probably emit a warning.

If the last reference to this page is speculative, it will be released
by put_page() which only frees the first page of a non-compound
allocation.  

To prevent the remaining pages from being leaked, we free
the subsequent pages here.  If you want to use the page's reference
count to decide when to free the allocation, you should allocate a
compound page, and use put_page() instead of __free_pages().

Context: May be called in interrupt context or while holding a normal
spinlock, but not in NMI context or while holding a raw spinlock.
```c

void __free_pages(struct page *page, unsigned int order)
{
	if (put_page_testzero(page))
		free_the_page(page, order);
	else if (!PageHead(page))
		while (order-- > 0)
			free_the_page(page + (1 << order), order);
}
```


Check memory

```shell
cat /proc/meminfo 

slabtop
```






### page

The kernel treats physical pages as the basic unit of memory management.

Each physical page in the system has a struct page associated with it to keep track of whatever it is we are using the page for at the moment. 
Note that we have no way to track which tasks are using a page, though if it is a pagecache page, rmap structures can tell us who is mapping it.

If you allocate the page using alloc_pages(), you can use some of the space in struct page for your own purposes.  The five words in the main union are available, except for bit 0 of the first word which must be kept clear.  
Many users use this word to store a pointer to an object which is guaranteed to be aligned.  If you use the same storage as page->mapping, you must restore it to NULL before freeing the page.

If your page will not be mapped to userspace, you can also use the four bytes in the mapcount union, but you must call page_mapcount_reset() before freeing it.

If you want to use the refcount field, it must be used in such a way that other CPUs temporarily incrementing and then decrementing the refcount does not cause problems.  
On receiving the page from alloc_pages(), the refcount will be positive.

If you allocate pages of order > 0, you can use some of the fields in each subpage, but you may need to restore some of their values afterwards.

SLUB uses cmpxchg_double() to atomically update its freelist and counters.  That requires that freelist & counters be adjacent and double-word aligned.
We align all struct pages to double-word boundaries, and ensure that 'freelist' is aligned within the struct.


```c

// linux/mm_types.h
#ifdef CONFIG_HAVE_ALIGNED_STRUCT_PAGE
#define _struct_page_alignment	__aligned(2 * sizeof(unsigned long))
#else
#define _struct_page_alignment
#endif


struct page {
	unsigned long flags;		/* Atomic flags, some possibly
					 * updated asynchronously */
	/*
	 * Five words (20/40 bytes) are available in this union.
	 * WARNING: bit 0 of the first word is used for PageTail(). That
	 * means the other users of this union MUST NOT use the bit to
	 * avoid collision and false-positive PageTail().
	 */
	union {
		struct {	/* Page cache and anonymous pages */
			/**
			 * @lru: Pageout list, eg. active_list protected by
			 * lruvec->lru_lock.  Sometimes used as a generic list
			 * by the page owner.
			 */
			struct list_head lru;
			/* See page-flags.h for PAGE_MAPPING_FLAGS */
			struct address_space *mapping;
			pgoff_t index;		/* Our offset within mapping. */
			/**
			 * @private: Mapping-private opaque data.
			 * Usually used for buffer_heads if PagePrivate.
			 * Used for swp_entry_t if PageSwapCache.
			 * Indicates order in the buddy system if PageBuddy.
			 */
			unsigned long private;
		};
		struct {	/* page_pool used by netstack */
			/**
			 * @dma_addr: might require a 64-bit value on
			 * 32-bit architectures.
			 */
			unsigned long dma_addr[2];
		};
		struct {	/* slab, slob and slub */
			union {
				struct list_head slab_list;
				struct {	/* Partial pages */
					struct page *next;
#ifdef CONFIG_64BIT
					int pages;	/* Nr of pages left */
					int pobjects;	/* Approximate count */
#else
					short int pages;
					short int pobjects;
#endif
				};
			};
			struct kmem_cache *slab_cache; /* not slob */
			/* Double-word boundary */
			void *freelist;		/* first free object */
			union {
				void *s_mem;	/* slab: first object */
				unsigned long counters;		/* SLUB */
				struct {			/* SLUB */
					unsigned inuse:16;
					unsigned objects:15;
					unsigned frozen:1;
				};
			};
		};
		struct {	/* Tail pages of compound page */
			unsigned long compound_head;	/* Bit zero is set */

			/* First tail page only */
			unsigned char compound_dtor;
			unsigned char compound_order;
			atomic_t compound_mapcount;
			unsigned int compound_nr; /* 1 << compound_order */
		};
		struct {	/* Second tail page of compound page */
			unsigned long _compound_pad_1;	/* compound_head */
			atomic_t hpage_pinned_refcount;
			/* For both global and memcg */
			struct list_head deferred_list;
		};
		struct {	/* Page table pages */
			unsigned long _pt_pad_1;	/* compound_head */
			pgtable_t pmd_huge_pte; /* protected by page->ptl */
			unsigned long _pt_pad_2;	/* mapping */
			union {
				struct mm_struct *pt_mm; /* x86 pgds only */
				atomic_t pt_frag_refcount; /* powerpc */
			};
#if ALLOC_SPLIT_PTLOCKS
			spinlock_t *ptl;
#else
			spinlock_t ptl;
#endif
		};
		struct {	/* ZONE_DEVICE pages */
			/** @pgmap: Points to the hosting device page map. */
			struct dev_pagemap *pgmap;
			void *zone_device_data;
			/*
			 * ZONE_DEVICE private pages are counted as being
			 * mapped so the next 3 words hold the mapping, index,
			 * and private fields from the source anonymous or
			 * page cache page while the page is migrated to device
			 * private memory.
			 * ZONE_DEVICE MEMORY_DEVICE_FS_DAX pages also
			 * use the mapping, index, and private fields when
			 * pmem backed DAX files are mapped.
			 */
		};

		/** @rcu_head: You can use this to free a page by RCU. */
		struct rcu_head rcu_head;
	};

	union {		/* This union is 4 bytes in size. */
		/*
		 * If the page can be mapped to userspace, encodes the number
		 * of times this page is referenced by a page table.
		 */
		atomic_t _mapcount;

		/*
		 * If the page is neither PageSlab nor mappable to userspace,
		 * the value stored here may help determine what this page
		 * is used for.  See page-flags.h for a list of page types
		 * which are currently stored here.
		 */
		unsigned int page_type;

		unsigned int active;		/* SLAB */
		int units;			/* SLOB */
	};

	/* Usage count. *DO NOT USE DIRECTLY*. See page_ref.h */
	atomic_t _refcount;

#ifdef CONFIG_MEMCG
	unsigned long memcg_data;
#endif

	/*
	 * On machines where all RAM is mapped into kernel address space,
	 * we can simply calculate the virtual address. On machines with
	 * highmem some memory is mapped into kernel virtual memory
	 * dynamically, so we need a place to store that address.
	 * Note that this field could be 16 bits on x86 ... ;)
	 *
	 * Architectures with slow multiplication can define
	 * WANT_PAGE_VIRTUAL in asm/page.h
	 */
#if defined(WANT_PAGE_VIRTUAL)
	void *virtual;			/* Kernel virtual address (NULL if
					   not kmapped, ie. highmem) */
#endif /* WANT_PAGE_VIRTUAL */

#ifdef LAST_CPUPID_NOT_IN_PAGE_FLAGS
	int _last_cpupid;
#endif
} _struct_page_alignment;

```

### zone

Because of hardware limitations, the kernel cannot treat all pages as identical. Some pages, because of their physical address in memory, cannot be used for certain tasks. 
Because of this limitation, the kernel divides pages into different *zones*.

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

### kmalloc

```c
// linux/slab.h
/**
 * kmalloc - allocate memory
 * @size: how many bytes of memory are required.
 * @flags: the type of memory to allocate.
 *
 * kmalloc is the normal method of allocating memory
 * for objects smaller than page size in the kernel.
 *
 * The allocated object address is aligned to at least ARCH_KMALLOC_MINALIGN
 * bytes. For @size of power of two bytes, the alignment is also guaranteed
 * to be at least to the size.
 *
 * The @flags argument may be one of the GFP flags defined at
 * include/linux/gfp.h and described at
 * :ref:`Documentation/core-api/mm-api.rst <mm-api-gfp-flags>`
 *
 * The recommended usage of the @flags is described at
 * :ref:`Documentation/core-api/memory-allocation.rst <memory_allocation>`
 *
 * Below is a brief outline of the most useful GFP flags
 *
 * %GFP_KERNEL
 *	Allocate normal kernel ram. May sleep.
 *
 * %GFP_NOWAIT
 *	Allocation will not sleep.
 *
 * %GFP_ATOMIC
 *	Allocation will not sleep.  May use emergency pools.
 *
 * %GFP_HIGHUSER
 *	Allocate memory from high memory on behalf of user.
 *
 * Also it is possible to set different flags by OR'ing
 * in one or more of the following additional @flags:
 *
 * %__GFP_HIGH
 *	This allocation has high priority and may use emergency pools.
 *
 * %__GFP_NOFAIL
 *	Indicate that this allocation is in no way allowed to fail
 *	(think twice before using).
 *
 * %__GFP_NORETRY
 *	If memory is not immediately available,
 *	then give up at once.
 *
 * %__GFP_NOWARN
 *	If allocation fails, don't issue any warnings.
 *
 * %__GFP_RETRY_MAYFAIL
 *	Try really hard to succeed the allocation but fail
 *	eventually.
 */
static __always_inline void *kmalloc(size_t size, gfp_t flags)
{
	if (__builtin_constant_p(size)) {
#ifndef CONFIG_SLOB
		unsigned int index;
#endif
		if (size > KMALLOC_MAX_CACHE_SIZE)
			return kmalloc_large(size, flags);
#ifndef CONFIG_SLOB
		index = kmalloc_index(size);

		if (!index)
			return ZERO_SIZE_PTR;

		return kmem_cache_alloc_trace(
				kmalloc_caches[kmalloc_type(flags)][index],
				flags, size);
#endif
	}
	return __kmalloc(size, flags);
}
```

End of slob allocator proper. Begin kmem_cache_alloc and kmalloc frontend.
```c

void *__kmalloc(size_t size, gfp_t gfp)
{
	return __do_kmalloc_node(size, gfp, NUMA_NO_NODE, _RET_IP_);
}

static __always_inline void *
__do_kmalloc_node(size_t size, gfp_t gfp, int node, unsigned long caller)
{
	unsigned int *m;
	int minalign = max_t(size_t, ARCH_KMALLOC_MINALIGN, ARCH_SLAB_MINALIGN);
	void *ret;

	gfp &= gfp_allowed_mask;

	might_alloc(gfp);

	if (size < PAGE_SIZE - minalign) {
		int align = minalign;

		/*
		 * For power of two sizes, guarantee natural alignment for
		 * kmalloc()'d objects.
		 */
		if (is_power_of_2(size))
			align = max(minalign, (int) size);

		if (!size)
			return ZERO_SIZE_PTR;

		m = slob_alloc(size + minalign, gfp, align, node, minalign);

		if (!m)
			return NULL;
		*m = size;
		ret = (void *)m + minalign;

		trace_kmalloc_node(caller, ret,
				   size, size + minalign, gfp, node);
	} else {
		unsigned int order = get_order(size);

		if (likely(order))
			gfp |= __GFP_COMP;
		ret = slob_new_pages(gfp, order, node);

		trace_kmalloc_node(caller, ret,
				   size, PAGE_SIZE << order, gfp, node);
	}

	kmemleak_alloc(ret, size, 1, gfp);
	return ret;
}
```
### mm_struct

```c
struct mm_struct {
	struct {
		struct vm_area_struct *mmap;		/* list of VMAs */
		struct rb_root mm_rb;
		u64 vmacache_seqnum;                   /* per-thread vmacache */
#ifdef CONFIG_MMU
		unsigned long (*get_unmapped_area) (struct file *filp,
				unsigned long addr, unsigned long len,
				unsigned long pgoff, unsigned long flags);
#endif
		unsigned long mmap_base;	/* base of mmap area */
		unsigned long mmap_legacy_base;	/* base of mmap area in bottom-up allocations */
#ifdef CONFIG_HAVE_ARCH_COMPAT_MMAP_BASES
		/* Base adresses for compatible mmap() */
		unsigned long mmap_compat_base;
		unsigned long mmap_compat_legacy_base;
#endif
		unsigned long task_size;	/* size of task vm space */
		unsigned long highest_vm_end;	/* highest vma end address */
		pgd_t * pgd;

#ifdef CONFIG_MEMBARRIER
		/**
		 * @membarrier_state: Flags controlling membarrier behavior.
		 *
		 * This field is close to @pgd to hopefully fit in the same
		 * cache-line, which needs to be touched by switch_mm().
		 */
		atomic_t membarrier_state;
#endif

		/**
		 * @mm_users: The number of users including userspace.
		 *
		 * Use mmget()/mmget_not_zero()/mmput() to modify. When this
		 * drops to 0 (i.e. when the task exits and there are no other
		 * temporary reference holders), we also release a reference on
		 * @mm_count (which may then free the &struct mm_struct if
		 * @mm_count also drops to 0).
		 */
		atomic_t mm_users;

		/**
		 * @mm_count: The number of references to &struct mm_struct
		 * (@mm_users count as 1).
		 *
		 * Use mmgrab()/mmdrop() to modify. When this drops to 0, the
		 * &struct mm_struct is freed.
		 */
		atomic_t mm_count;

		/**
		 * @has_pinned: Whether this mm has pinned any pages.  This can
		 * be either replaced in the future by @pinned_vm when it
		 * becomes stable, or grow into a counter on its own. We're
		 * aggresive on this bit now - even if the pinned pages were
		 * unpinned later on, we'll still keep this bit set for the
		 * lifecycle of this mm just for simplicity.
		 */
		atomic_t has_pinned;

#ifdef CONFIG_MMU
		atomic_long_t pgtables_bytes;	/* PTE page table pages */
#endif
		int map_count;			/* number of VMAs */

		spinlock_t page_table_lock; /* Protects page tables and some
					     * counters
					     */
		/*
		 * With some kernel config, the current mmap_lock's offset
		 * inside 'mm_struct' is at 0x120, which is very optimal, as
		 * its two hot fields 'count' and 'owner' sit in 2 different
		 * cachelines,  and when mmap_lock is highly contended, both
		 * of the 2 fields will be accessed frequently, current layout
		 * will help to reduce cache bouncing.
		 *
		 * So please be careful with adding new fields before
		 * mmap_lock, which can easily push the 2 fields into one
		 * cacheline.
		 */
		struct rw_semaphore mmap_lock;

		struct list_head mmlist; /* List of maybe swapped mm's.	These
					  * are globally strung together off
					  * init_mm.mmlist, and are protected
					  * by mmlist_lock
					  */


		unsigned long hiwater_rss; /* High-watermark of RSS usage */
		unsigned long hiwater_vm;  /* High-water virtual memory usage */

		unsigned long total_vm;	   /* Total pages mapped */
		unsigned long locked_vm;   /* Pages that have PG_mlocked set */
		atomic64_t    pinned_vm;   /* Refcount permanently increased */
		unsigned long data_vm;	   /* VM_WRITE & ~VM_SHARED & ~VM_STACK */
		unsigned long exec_vm;	   /* VM_EXEC & ~VM_WRITE & ~VM_STACK */
		unsigned long stack_vm;	   /* VM_STACK */
		unsigned long def_flags;

		/**
		 * @write_protect_seq: Locked when any thread is write
		 * protecting pages mapped by this mm to enforce a later COW,
		 * for instance during page table copying for fork().
		 */
		seqcount_t write_protect_seq;

		spinlock_t arg_lock; /* protect the below fields */

		unsigned long start_code, end_code, start_data, end_data;
		unsigned long start_brk, brk, start_stack;
		unsigned long arg_start, arg_end, env_start, env_end;

		unsigned long saved_auxv[AT_VECTOR_SIZE]; /* for /proc/PID/auxv */

		/*
		 * Special counters, in some configurations protected by the
		 * page_table_lock, in other configurations by being atomic.
		 */
		struct mm_rss_stat rss_stat;

		struct linux_binfmt *binfmt;

		/* Architecture-specific MM context */
		mm_context_t context;

		unsigned long flags; /* Must use atomic bitops to access */

		struct core_state *core_state; /* coredumping support */

#ifdef CONFIG_MEMCG
		/*
		 * "owner" points to a task that is regarded as the canonical
		 * user/owner of this mm. All of the following must be true in
		 * order for it to be changed:
		 *
		 * current == mm->owner
		 * current->mm != mm
		 * new_owner->mm == mm
		 * new_owner->alloc_lock is held
		 */
		struct task_struct __rcu *owner;
#endif
		struct user_namespace *user_ns;

		/* store ref to file /proc/<pid>/exe symlink points to */
		struct file __rcu *exe_file;
#ifdef CONFIG_MMU_NOTIFIER
		struct mmu_notifier_subscriptions *notifier_subscriptions;
#endif
#if defined(CONFIG_TRANSPARENT_HUGEPAGE) && !USE_SPLIT_PMD_PTLOCKS
		pgtable_t pmd_huge_pte; /* protected by page_table_lock */
#endif
#ifdef CONFIG_NUMA_BALANCING
		/*
		 * numa_next_scan is the next time that the PTEs will be marked
		 * pte_numa. NUMA hinting faults will gather statistics and
		 * migrate pages to new nodes if necessary.
		 */
		unsigned long numa_next_scan;

		/* Restart point for scanning and setting pte_numa */
		unsigned long numa_scan_offset;

		/* numa_scan_seq prevents two threads setting pte_numa */
		int numa_scan_seq;
#endif
		/*
		 * An operation with batched TLB flushing is going on. Anything
		 * that can move process memory needs to flush the TLB when
		 * moving a PROT_NONE or PROT_NUMA mapped page.
		 */
		atomic_t tlb_flush_pending;
#ifdef CONFIG_ARCH_WANT_BATCHED_UNMAP_TLB_FLUSH
		/* See flush_tlb_batched_pending() */
		bool tlb_flush_batched;
#endif
		struct uprobes_state uprobes_state;
#ifdef CONFIG_HUGETLB_PAGE
		atomic_long_t hugetlb_usage;
#endif
		struct work_struct async_put_work;

#ifdef CONFIG_IOMMU_SUPPORT
		u32 pasid;
#endif
	} __randomize_layout;

	/*
	 * The mm_cpumask needs to be at the end of mm_struct, because it
	 * is dynamically sized based on nr_cpu_ids.
	 */
	unsigned long cpu_bitmap[];
};
```


在Linux内核中，虚拟内存是用过结构体 vm_area_struct 来管理的，通过 vm_area_struct 结构体可以把虚拟内存划分为多个用途不相同的内存区，
比如可以划分为数据段区、代码段区等等，vm_area_struct 结构体的定义如下：


每个进程都由 task_struct 结构进行管理，task_struct 结构中的 mm 成员指向了每个进程的内存管理结构 mm_struct，而 mm_struct 结构的 mmap 成员记录了进程虚拟内存空间各个内存区的 vm_area_struct 结构链表

<div style="text-align: center;">

![](./img/vm_area_struct.png)

</div>

<p style="text-align: center;">Fig.1. vm_area_struct</p>

当调用 mmap() 时，内核会创建一个 vm_area_struct 结构，并且把 vm_start 和 vm_end 指向虚拟内存空间的某个内存区，并且把 vm_file 字段指向映射的文件对象。然后调用文件对象的 mmap 接口来对 vm_area_struct 结构的 vm_ops 成员进行初始化，如 ext2 文件系统的文件对象会调用 generic_file_mmap() 函数进行初始化


vm_operations_struct 结构的 nopage 接口会在访问内存发生异常时被调用，上面指向的是 filemap_nopage() 函数，filemap_nopage() 函数的主要工作是：

- 把映射到虚拟内存区的文件内容读入到物理内存页中。
- 对访问发生异常的虚拟内存地址与物理内存地址进行映射


虚拟内存页m 映射到 物理内存页x，并且把映射的文件的内容读入到物理内存中，这样就把内存与文件的映射关系建立起来，对映射的内存区进行读写操作实际上就是对文件的读写操作。
一般来说，对映射的内存空间进行读写并不会实时写入到文件中，所以要对内存与文件进行同步时需要调用 msync() 函数来实现


> 像 read()/write() 这些系统调用，首先需要进行内核空间，然后把文件内容读入到缓存中，然后再对缓存进行读写操作，最后由内核定时同步到文件中

而调用 mmap() 系统调用对文件进行映射后，用户对映射后的内存进行读写实际上是对文件缓存的读写，所以减少了一次系统调用，从而加速了对文件读写的效率


## allocator

The kernel offers two mechanisms for allocating memory, both of which are built on top of the kernel's page allocator (zoned buddy allocator):
- page allocator (zoned buddy allocator): – [slab allocator](/docs/CS/OS/Linux/mm/slab.md) obtains physically contiguous memory in the kernel's own address space; this allocator is typically accessed via kmalloc(),
- vmalloc() returns memory in a separate address space; that memory will be virtually contiguous but may be physically scattered.


### slab


tcp 内存使用slab分配

dmidecode 查看CPU 内存信息
每个CPU和它直接相连的内存条组成Node

numactl --hardware
查看Node情况
Node划分为Zone

```shell
cat /proc/zoneinfo #查看zone信息
```

Zone包含Page 一般为4KB


```shell
cat /proc/slabinfo
slabtop
```

slab_def.h

mm/slab.h


### malloc


sys_brk() for the most part doesn't need the global kernel lock, except when an application is doing something nasty like trying to un-brk an area that has already been mapped to a regular file.  in this case, the unmapping will need to invoke file system routines that need the global lock.


```c
SYSCALL_DEFINE1(brk, unsigned long, brk)
{
    struct mm_struct *mm = current->mm;

    if (brk < mm->start_brk || brk > mm->context.end_brk)
        return mm->brk;

    if (mm->brk == brk)
        return mm->brk;

    /*
     * Always allow shrinking brk
     */
    if (brk <= mm->brk) {
        mm->brk = brk;
        return brk;
    }

    /*
     * Ok, looks good - let it rip.
     */
    flush_icache_user_range(mm->brk, brk);
    return mm->brk = brk;
}
```

## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. []()

