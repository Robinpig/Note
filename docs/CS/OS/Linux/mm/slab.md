## Introduction

在Linux中，[buddy allocator](/docs/CS/OS/Linux/mm/pm.md?id=buddy) 是以页为单位管理和分配内存
但在内核中的需求却以字节为单位（在内核中面临频繁的结构体内存分配问题）。假如我们需要动态申请一个内核结构体（占 20 字节），若仍然分配一页内存，这将严重浪费内存
slab分配器分配内存以字节为单位，基于伙伴分配器的大内存进一步细分成小内存分配。换句话说，slab 分配器仍然从 Buddy 分配器中申请内存，之后自己对申请来的内存细分管理

除了提供小内存外，slab 分配器的第二个任务是维护常用对象的缓存。对于内核中使用的许多结构，初始化对象所需的时间可等于或超过为其分配空间的成本
当创建一个新的slab 时，许多对象将被打包到其中并使用构造函数（如果有）进行初始化。释放对象后，它会保持其初始化状态，这样可以快速分配对象

> 举例来说, 为管理与进程关联的文件系统数据, 内核必须经常生成struct fs_struct的新实例. 此类型实例占据的内存块同样需要经常回收(在进程结束时)
> 换句话说, 内核趋向于非常有规律地分配并释放大小为sizeof(fs_struct)的内存块. slab分配器将释放的内存块保存在一个内部列表中. 并不马上返回给伙伴系统. 在请求为该类对象分配一个新实例时, 会使用最近释放的内存块
> 这有两个优点. 首先, 由于内核不必使用伙伴系统算法, 处理时间会变短. 其次, 由于该内存块仍然是”新”的，因此其仍然驻留在CPU硬件缓存的概率较高

SLAB分配器的最后一项任务是提高CPU硬件缓存的利用率。 如果将对象包装到SLAB中后仍有剩余空间，则将剩余空间用于为SLAB着色。 
SLAB着色是一种尝试使不同SLAB中的对象使用CPU硬件缓存中不同行的方案。
通过将对象放置在SLAB中的不同起始偏移处，对象可能会在CPU缓存中使用不同的行，从而有助于确保来自同一SLAB缓存的对象不太可能相互刷新。 通过这种方案，原本被浪费掉的空间可以实现一项新功能

slab 对象池的三种实现：slab，slub，slob

slab 的实现，最早是由 Sun 公司的 Jeff Bonwick 大神在 Solaris 2.4  系统中设计并实现的，由于 Jeff Bonwick 大神公开了 slab 的实现方法，
因此被 Linux 所借鉴并于 1996 年在 Linux 2.0 版本中引入了 slab，用于 Linux 内核早期的小内存分配场景

由于 slab 的实现非常复杂，slab 中拥有多种存储对象的队列，队列管理开销比较大，slab 元数据比较臃肿，对 NUMA 架构的支持臃肿繁杂（slab 引入时内核还没支持 NUMA），
这样导致 slab 内部为了维护这些自身元数据管理结构就得花费大量的内存空间，这在配置有超大容量内存的服务器上，内存的浪费是非常可观的

slub 简化了 slab 一些复杂的设计，同时保留了 slab 的基本思想，摒弃了 slab 众多管理队列的概念，并针对多处理器，NUMA 架构进行优化，放弃了效果不太明显的 slab 着色机制
**slub 与 slab 相比，提高了性能 吞吐量 并降低了内存的浪费 成为现在内核中常用的 slab 实现**


slob 的实现是在内核 2.6.16 版本（2006 年发布）引入的，它是专门为嵌入式小型机器小内存的场景设计的，所以实现上很精简，能在小型机器上提供很不错的性能

slab 对象池在内存管理系统中的架构层次是基于伙伴系统之上构建的，slab 对象池会一次性向伙伴系统申请一个或者多个完整的物理内存页，
在这些完整的内存页内在逐步划分出一小块一小块的内存块出来，而这些小内存块的尺寸就是 slab 对象池所管理的内核核心对象占用的内存大小


当我们使用 fork() 系统调用创建进程的时候，内核需要使用 task_struct 专属的 slab 对象池分配 task_struct 对象
为进程创建虚拟内存空间的时候，内核需要使用 mm_struct 专属的 slab 对象池分配  mm_struct 对象。
当我们向页高速缓存 page cache 查找对应的文件缓存页时，内核需要使用 struct page 专属的 slab 对象池分配  struct page 对象
当我们使用 open 系统调用打开一个文件时，内核需要使用 struct file专属的 slab 对象池分配 struct file 对象
当服务端网络应用程序使用 accpet 系统调用接收客户端的连接时，内核需要使用 struct socket 专属的 slab 对象池为新进来的客户端连接分配 socket 对象。
凡是需要被内核频繁使用的内核对象都需要被 slab 对象池所管理


```c
/* Reuses the bits in struct page */
struct slab {
	unsigned long __page_flags;

	struct kmem_cache *slab_cache;
	union {
		struct {
			union {
				struct list_head slab_list;
#ifdef CONFIG_SLUB_CPU_PARTIAL
				struct {
					struct slab *next;
					int slabs;	/* Nr of slabs left */
				};
#endif
			};
			/* Double-word boundary */
			union {
				struct {
					void *freelist;		/* first free object */
					union {
						unsigned long counters;
						struct {
							unsigned inuse:16;
							unsigned objects:15;
							/*
							 * If slab debugging is enabled then the
							 * frozen bit can be reused to indicate
							 * that the slab was corrupted
							 */
							unsigned frozen:1;
						};
					};
				};
#ifdef system_has_freelist_aba
				freelist_aba_t freelist_counter;
#endif
			};
		};
		struct rcu_head rcu_head;
	};

	unsigned int __page_type;
	atomic_t __page_refcount;
#ifdef CONFIG_SLAB_OBJ_EXT
	unsigned long obj_exts;
#endif
};
```

## kmem_cache

每一个slab都有一个管理结构，叫做 kmem_cache
kmem_cache将所有node上的slab连接起来，进行统一的调配。每个slab其实就是一个page结构体，对应着2^gfporder个连续页框
每个slab由根据需要，划分成多个object，每个object就是可以被进程使用的空间了
Linux通过slab_caches双端链表，将系统中所有kmem_cache链接起来


```c
/*
 * Slab cache management.
 */
struct kmem_cache {
#ifndef CONFIG_SLUB_TINY
	struct kmem_cache_cpu __percpu *cpu_slab;
#endif
	/* Used for retrieving partial slabs, etc. */
	slab_flags_t flags;
	unsigned long min_partial;
	unsigned int size;		/* Object size including metadata */
	unsigned int object_size;	/* Object size without metadata */
	struct reciprocal_value reciprocal_size;
	unsigned int offset;		/* Free pointer offset */
#ifdef CONFIG_SLUB_CPU_PARTIAL
	/* Number of per cpu partial objects to keep around */
	unsigned int cpu_partial;
	/* Number of per cpu partial slabs to keep around */
	unsigned int cpu_partial_slabs;
#endif
	struct kmem_cache_order_objects oo;

	/* Allocation and freeing of slabs */
	struct kmem_cache_order_objects min;
	gfp_t allocflags;		/* gfp flags to use on each alloc */
	int refcount;			/* Refcount for slab cache destroy */
	void (*ctor)(void *object);	/* Object constructor */
	unsigned int inuse;		/* Offset to metadata */
	unsigned int align;		/* Alignment */
	unsigned int red_left_pad;	/* Left redzone padding size */
	const char *name;		/* Name (only for display!) */
	struct list_head list;		/* List of slab caches */
#ifdef CONFIG_SYSFS
	struct kobject kobj;		/* For sysfs */
#endif
#ifdef CONFIG_SLAB_FREELIST_HARDENED
	unsigned long random;
#endif

#ifdef CONFIG_NUMA
	/*
	 * Defragmentation by allocating from a remote node.
	 */
	unsigned int remote_node_defrag_ratio;
#endif

#ifdef CONFIG_SLAB_FREELIST_RANDOM
	unsigned int *random_seq;
#endif

#ifdef CONFIG_KASAN_GENERIC
	struct kasan_cache kasan_info;
#endif

#ifdef CONFIG_HARDENED_USERCOPY
	unsigned int useroffset;	/* Usercopy region offset */
	unsigned int usersize;		/* Usercopy region size */
#endif

	struct kmem_cache_node *node[MAX_NUMNODES];
};
```

SLAB分配器由可变数量的缓存组成，这些缓存由称为“缓存链”的双向循环链表链接在一起
链表的头结点指针保存在 struct kmem_cache 结构的 list 中



```c
struct kmem_cache_node {
    spinlock_t list_lock;

#ifdef CONFIG_SLAB
    struct list_head slabs_partial; /* partial list first, better asm code */
    struct list_head slabs_full;
    struct list_head slabs_free;
    unsigned long total_slabs;  /* length of all slab lists */
    unsigned long free_slabs;   /* length of free slab list only */
    unsigned long free_objects;
    unsigned int free_limit;
    unsigned int colour_next;   /* Per-node cache coloring */
    struct array_cache *shared; /* shared per node */
    struct alien_cache **alien; /* on other nodes */
    unsigned long next_reap;    /* updated without locking */
    int free_touched;       /* updated without locking */
#endif
...
};
```
`kmem_cache_node` 记录了3种slab

- slabs_full: 已经完全分配的 slab
- slabs_partial: 部分分配的slab
- slabs_free: 空slab，或者没有对象被分配

kmalloc_info[] is to make slub_debug=,kmalloc-xx option work at boot time. kmalloc_index() supports up to 2^26=64MB, so the final entry of the table is kmalloc-67108864.
index = 1 和 index = 2 是个例外，内核单独支持了 kmalloc-96 和 kmalloc-192 这两个通用 slab cache。
因为在内核中，对于内存块的申请需求大部分情况下都在 96 字节或者 192 字节附近，如果内核不单独支持这两个尺寸的通用 slab cache。那么当内核申请一个尺寸在 64 字节到 96 字节之间的内存块时，内核会直接从 kmalloc-128 中分配一个 128 字节大小的内存块，这样就导致了内存块内部碎片比较大，浪费宝贵的内存资源



kmalloc 体系所支持的内存块尺寸与 slab allocator 体系的实现有关，在 Linux 内核中 slab allocator 体系的实现分为三种：slab 实现，slub 实现，slob 实现。
而在被大规模运用的服务器 Linux 操作系统中，slab allocator 体系采用的是 slub 实现

kmalloc 体系所能支持的内存块尺寸范围由 KMALLOC_SHIFT_LOW 和 KMALLOC_SHIFT_HIGH 决定，它们被定义在 /include/linux/slab.h 文件中：
其中 kmalloc 支持的最小内存块尺寸为：2^KMALLOC_SHIFT_LOW，在 slub 实现中 KMALLOC_SHIFT_LOW = 3，kmalloc 支持的最小内存块尺寸为 8 字节大小。

kmalloc 支持的最大内存块尺寸为：2^KMALLOC_SHIFT_HIGH，在 slub 实现中 KMALLOC_SHIFT_HIGH = 13，kmalloc 支持的最大内存块尺寸为 8K ，也就是两个内存页大小

```c
/* A table of kmalloc cache names and sizes */

extern const struct kmalloc_info_struct {
    const char *name[NR_KMALLOC_TYPES];
    unsigned int size;
} kmalloc_info[];
```


Linux kernel 使用 struct page 来描述一个slab
单个slab可以在slab链表之间移动，例如如果一个半满slab被分配了对象后变满了，就要从 slabs_partial 中被删除，同时插入到 slabs_full 中去

```c
struct page {
    unsigned long flags;        /* Atomic flags, some possibly
                     * updated asynchronously */
    union {
        struct {    /* slab, slob and slub */
            union {
                struct list_head slab_list;
                struct {    /* Partial pages */
                    struct page *next;
#ifdef CONFIG_64BIT
                    int pages;  /* Nr of pages left */
                    int pobjects;   /* Approximate count */
#else
                    short int pages;
                    short int pobjects;
#endif
                };
            };
            struct kmem_cache *slab_cache; /* not slob */
            /* Double-word boundary */
            void *freelist;     /* first free object */
            union {
                void *s_mem;    /* slab: first object */
                unsigned long counters;     /* SLUB */
                ...
            };
        }; 
        ...
    };
    ...
} _struct_page_alignment;
```
操作系统启动创建kmem_cache完成后，这三个链表都为空，只有在申请对象时发现没有可用的 slab 时才会创建一个新的SLAB，并加入到这三个链表中的一个中

```c
// include/linux/mmzone.h
struct free_area {
	struct list_head	free_list[MIGRATE_TYPES];
	unsigned long		nr_free;
};
```




Create a cache.

Returns a ptr to the cache on success, NULL on failure.
Cannot be called within a int, but can be interrupted.
The @ctor is run when new pages are allocated by the cache.
```c
int __kmem_cache_create(struct kmem_cache *cachep, slab_flags_t flags)
{
	size_t ralign = BYTES_PER_WORD;
	gfp_t gfp;
	int err;
	unsigned int size = cachep->size;

#if DEBUG
#if FORCED_DEBUG
	/*
	 * Enable redzoning and last user accounting, except for caches with
	 * large objects, if the increased size would increase the object size
	 * above the next power of two: caches with object sizes just above a
	 * power of two have a significant amount of internal fragmentation.
	 */
	if (size < 4096 || fls(size - 1) == fls(size-1 + REDZONE_ALIGN +
						2 * sizeof(unsigned long long)))
		flags |= SLAB_RED_ZONE | SLAB_STORE_USER;
	if (!(flags & SLAB_TYPESAFE_BY_RCU))
		flags |= SLAB_POISON;
#endif
#endif

	/*
	 * Check that size is in terms of words.  This is needed to avoid
	 * unaligned accesses for some archs when redzoning is used, and makes
	 * sure any on-slab bufctl's are also correctly aligned.
	 */
	size = ALIGN(size, BYTES_PER_WORD);

	if (flags & SLAB_RED_ZONE) {
		ralign = REDZONE_ALIGN;
		/* If redzoning, ensure that the second redzone is suitably
		 * aligned, by adjusting the object size accordingly. */
		size = ALIGN(size, REDZONE_ALIGN);
	}

	/* 3) caller mandated alignment */
	if (ralign < cachep->align) {
		ralign = cachep->align;
	}
	/* disable debug if necessary */
	if (ralign > __alignof__(unsigned long long))
		flags &= ~(SLAB_RED_ZONE | SLAB_STORE_USER);
	/*
	 * 4) Store it.
	 */
	cachep->align = ralign;
	cachep->colour_off = cache_line_size();
	/* Offset must be a multiple of the alignment. */
	if (cachep->colour_off < cachep->align)
		cachep->colour_off = cachep->align;

	if (slab_is_available())
		gfp = GFP_KERNEL;
	else
		gfp = GFP_NOWAIT;

#if DEBUG

	/*
	 * Both debugging options require word-alignment which is calculated
	 * into align above.
	 */
	if (flags & SLAB_RED_ZONE) {
		/* add space for red zone words */
		cachep->obj_offset += sizeof(unsigned long long);
		size += 2 * sizeof(unsigned long long);
	}
	if (flags & SLAB_STORE_USER) {
		/* user store requires one word storage behind the end of
		 * the real object. But if the second red zone needs to be
		 * aligned to 64 bits, we must allow that much space.
		 */
		if (flags & SLAB_RED_ZONE)
			size += REDZONE_ALIGN;
		else
			size += BYTES_PER_WORD;
	}
#endif

	kasan_cache_create(cachep, &size, &flags);

	size = ALIGN(size, cachep->align);
	/*
	 * We should restrict the number of objects in a slab to implement
	 * byte sized index. Refer comment on SLAB_OBJ_MIN_SIZE definition.
	 */
	if (FREELIST_BYTE_INDEX && size < SLAB_OBJ_MIN_SIZE)
		size = ALIGN(SLAB_OBJ_MIN_SIZE, cachep->align);

#if DEBUG
	/*
	 * To activate debug pagealloc, off-slab management is necessary
	 * requirement. In early phase of initialization, small sized slab
	 * doesn't get initialized so it would not be possible. So, we need
	 * to check size >= 256. It guarantees that all necessary small
	 * sized slab is initialized in current slab initialization sequence.
	 */
	if (debug_pagealloc_enabled_static() && (flags & SLAB_POISON) &&
		size >= 256 && cachep->object_size > cache_line_size()) {
		if (size < PAGE_SIZE || size % PAGE_SIZE == 0) {
			size_t tmp_size = ALIGN(size, PAGE_SIZE);

			if (set_off_slab_cache(cachep, tmp_size, flags)) {
				flags |= CFLGS_OFF_SLAB;
				cachep->obj_offset += tmp_size - size;
				size = tmp_size;
				goto done;
			}
		}
	}
#endif

	if (set_objfreelist_slab_cache(cachep, size, flags)) {
		flags |= CFLGS_OBJFREELIST_SLAB;
		goto done;
	}

	if (set_off_slab_cache(cachep, size, flags)) {
		flags |= CFLGS_OFF_SLAB;
		goto done;
	}

	if (set_on_slab_cache(cachep, size, flags))
		goto done;

	return -E2BIG;

done:
	cachep->freelist_size = cachep->num * sizeof(freelist_idx_t);
	cachep->flags = flags;
	cachep->allocflags = __GFP_COMP;
	if (flags & SLAB_CACHE_DMA)
		cachep->allocflags |= GFP_DMA;
	if (flags & SLAB_CACHE_DMA32)
		cachep->allocflags |= GFP_DMA32;
	if (flags & SLAB_RECLAIM_ACCOUNT)
		cachep->allocflags |= __GFP_RECLAIMABLE;
	cachep->size = size;
	cachep->reciprocal_buffer_size = reciprocal_value(size);

#if DEBUG
	/*
	 * If we're going to use the generic kernel_map_pages()
	 * poisoning, then it's going to smash the contents of
	 * the redzone and userword anyhow, so switch them off.
	 */
	if (IS_ENABLED(CONFIG_PAGE_POISONING) &&
		(cachep->flags & SLAB_POISON) &&
		is_debug_pagealloc_cache(cachep))
		cachep->flags &= ~(SLAB_RED_ZONE | SLAB_STORE_USER);
#endif

	if (OFF_SLAB(cachep)) {
		cachep->freelist_cache =
			kmalloc_slab(cachep->freelist_size, 0u);
	}

	err = setup_cpu_cache(cachep, gfp);
	if (err) {
		__kmem_cache_release(cachep);
		return err;
	}

	return 0;
}
```

#### kmem_cache_init

```c

void __init kmem_cache_init(void)
{
	static __initdata struct kmem_cache boot_kmem_cache,
		boot_kmem_cache_node;
	int node;

	if (debug_guardpage_minorder())
		slub_max_order = 0;

	/* Print slub debugging pointers without hashing */
	if (__slub_debug_enabled())
		no_hash_pointers_enable(NULL);

	kmem_cache_node = &boot_kmem_cache_node;
	kmem_cache = &boot_kmem_cache;

	/*
	 * Initialize the nodemask for which we will allocate per node
	 * structures. Here we don't need taking slab_mutex yet.
	 */
	for_each_node_state(node, N_NORMAL_MEMORY)
		node_set(node, slab_nodes);

	create_boot_cache(kmem_cache_node, "kmem_cache_node",
			sizeof(struct kmem_cache_node),
			SLAB_HWCACHE_ALIGN | SLAB_NO_OBJ_EXT, 0, 0);

	hotplug_memory_notifier(slab_memory_callback, SLAB_CALLBACK_PRI);

	/* Able to allocate the per node structures */
	slab_state = PARTIAL;

	create_boot_cache(kmem_cache, "kmem_cache",
			offsetof(struct kmem_cache, node) +
				nr_node_ids * sizeof(struct kmem_cache_node *),
			SLAB_HWCACHE_ALIGN | SLAB_NO_OBJ_EXT, 0, 0);

	kmem_cache = bootstrap(&boot_kmem_cache);
	kmem_cache_node = bootstrap(&boot_kmem_cache_node);

	/* Now we can use the kmem_cache to allocate kmalloc slabs */
	setup_kmalloc_cache_index_table();
	create_kmalloc_caches();

	/* Setup random freelists for each cache */
	init_freelist_randomization();

	cpuhp_setup_state_nocalls(CPUHP_SLUB_DEAD, "slub:dead", NULL,
				  slub_cpu_dead);
}
```

create_boot_cache

```c
/* Create a cache during boot when no slab services are available yet */
void __init create_boot_cache(struct kmem_cache *s, const char *name,
		unsigned int size, slab_flags_t flags,
		unsigned int useroffset, unsigned int usersize)
{
	int err;
	unsigned int align = ARCH_KMALLOC_MINALIGN;
	struct kmem_cache_args kmem_args = {};

	/*
	 * kmalloc caches guarantee alignment of at least the largest
	 * power-of-two divisor of the size. For power-of-two sizes,
	 * it is the size itself.
	 */
	if (flags & SLAB_KMALLOC)
		align = max(align, 1U << (ffs(size) - 1));
	kmem_args.align = calculate_alignment(flags, align, size);

#ifdef CONFIG_HARDENED_USERCOPY
	kmem_args.useroffset = useroffset;
	kmem_args.usersize = usersize;
#endif

	err = do_kmem_cache_create(s, name, size, &kmem_args, flags);

	if (err)
		panic("Creation of kmalloc slab %s size=%u failed. Reason %d\n",
					name, size, err);

	s->refcount = -1;	/* Exempt from merging for now */
}
```

create_kmalloc_cache

```c
static struct kmem_cache *__init create_kmalloc_cache(const char *name,
						      unsigned int size,
						      slab_flags_t flags)
{
	struct kmem_cache *s = kmem_cache_zalloc(kmem_cache, GFP_NOWAIT);

	if (!s)
		panic("Out of memory when creating slab %s\n", name);

	create_boot_cache(s, name, size, flags | SLAB_KMALLOC, 0, size);
	list_add(&s->list, &slab_caches);
	s->refcount = 1;
	return s;
}
```

create_kmalloc_caches

Create the kmalloc array. Some of the regular kmalloc arrays may already have been created because they were needed to enable allocations for slab creation.
```c
void __init create_kmalloc_caches(void)
{
	int i;
	enum kmalloc_cache_type type;

	/*
	 * Including KMALLOC_CGROUP if CONFIG_MEMCG defined
	 */
	for (type = KMALLOC_NORMAL; type < NR_KMALLOC_TYPES; type++) {
		/* Caches that are NOT of the two-to-the-power-of size. */
		if (KMALLOC_MIN_SIZE <= 32)
			new_kmalloc_cache(1, type);
		if (KMALLOC_MIN_SIZE <= 64)
			new_kmalloc_cache(2, type);

		/* Caches that are of the two-to-the-power-of size. */
		for (i = KMALLOC_SHIFT_LOW; i <= KMALLOC_SHIFT_HIGH; i++)
			new_kmalloc_cache(i, type);
	}
#ifdef CONFIG_RANDOM_KMALLOC_CACHES
	random_kmalloc_seed = get_random_u64();
#endif

	/* Kmalloc array is now usable */
	slab_state = UP;

	if (IS_ENABLED(CONFIG_SLAB_BUCKETS))
		kmem_buckets_cache = kmem_cache_create("kmalloc_buckets",
						       sizeof(kmem_buckets),
						       0, SLAB_NO_MERGE, NULL);
}
```





#### kmem_cache_create

- Create a cache.
- name: A string which is used in /proc/slabinfo to identify this cache.
- size: The size of objects to be created in this cache.
- align: The required alignment for the objects.
- flags: SLAB flags
- ctor: A constructor for the objects.
  
Cannot be called within a interrupt, but can be interrupted.

The @ctor is run when new pages are allocated by the cache.

The flags are
- %SLAB_POISON - Poison the slab with a known test pattern (a5a5a5a5)
to catch references to uninitialised memory.
- %SLAB_RED_ZONE - Insert `Red` zones around the allocated memory to check
for buffer overruns.
- %SLAB_HWCACHE_ALIGN - Align the objects in this cache to a hardware
cacheline.  This can be beneficial if you're counting cycles as closely
as davem.

Return: a pointer to the cache on success, NULL on failure.
```c
//
struct kmem_cache *
kmem_cache_create(const char *name, unsigned int size, unsigned int align,
		slab_flags_t flags, void (*ctor)(void *))
{
	return kmem_cache_create_usercopy(name, size, align, flags, 0, 0,
					  ctor);
}
```

> 查看不同尺寸的slab cache cat /proc/slabinfo


kmem_cache_create_usercopy - Create a cache with a region suitable for copying to userspace
- name: A string which is used in /proc/slabinfo to identify this cache.
- size: The size of objects to be created in this cache.
- align: The required alignment for the objects.
- flags: SLAB flags
- useroffset: Usercopy region offset
- usersize: Usercopy region size
- ctor: A constructor for the objects.

```c
//
struct kmem_cache *
kmem_cache_create_usercopy(const char *name,
		  unsigned int size, unsigned int align,
		  slab_flags_t flags,
		  unsigned int useroffset, unsigned int usersize,
		  void (*ctor)(void *))
{
	struct kmem_cache *s = NULL;
	const char *cache_name;
	int err;

#ifdef CONFIG_SLUB_DEBUG
	/*
	 * If no slub_debug was enabled globally, the static key is not yet
	 * enabled by setup_slub_debug(). Enable it if the cache is being
	 * created with any of the debugging flags passed explicitly.
	 */
	if (flags & SLAB_DEBUG_FLAGS)
		static_branch_enable(&slub_debug_enabled);
#endif

	mutex_lock(&slab_mutex);

	err = kmem_cache_sanity_check(name, size);
	if (err) {
		goto out_unlock;
	}

	/* Refuse requests with allocator specific flags */
	if (flags & ~SLAB_FLAGS_PERMITTED) {
		err = -EINVAL;
		goto out_unlock;
	}

	/*
	 * Some allocators will constraint the set of valid flags to a subset
	 * of all flags. We expect them to define CACHE_CREATE_MASK in this
	 * case, and we'll just provide them with a sanitized version of the
	 * passed flags.
	 */
	flags &= CACHE_CREATE_MASK;

	/* Fail closed on bad usersize of useroffset values. */
	if (WARN_ON(!usersize && useroffset) ||
	    WARN_ON(size < usersize || size - usersize < useroffset))
		usersize = useroffset = 0;

	if (!usersize)
		s = __kmem_cache_alias(name, size, align, flags, ctor);
	if (s)
		goto out_unlock;

	cache_name = kstrdup_const(name, GFP_KERNEL);
	if (!cache_name) {
		err = -ENOMEM;
		goto out_unlock;
	}

	s = create_cache(cache_name, size,
			 calculate_alignment(flags, align, size),
			 flags, useroffset, usersize, ctor, NULL);
	if (IS_ERR(s)) {
		err = PTR_ERR(s);
		kfree_const(cache_name);
	}

out_unlock:
	mutex_unlock(&slab_mutex);

	if (err) {
		if (flags & SLAB_PANIC)
			panic("kmem_cache_create: Failed to create slab '%s'. Error %d\n",
				name, err);
		else {
			pr_warn("kmem_cache_create(%s) failed with error %d\n",
				name, err);
			dump_stack();
		}
		return NULL;
	}
	return s;
}
```

#### kmem_cache_destroy
```c
// mm/slab_common.c
void kmem_cache_destroy(struct kmem_cache *s)
{
    int err;

    if (unlikely(!s))
        return;

    mutex_lock(&slab_mutex);

    s->refcount--;
    if (s->refcount)
        goto out_unlock;

    err = shutdown_cache(s);
    if (err) {
        pr_err("kmem_cache_destroy %s: Slab cache still has objects\n",
               s->name);
        dump_stack();
    }
out_unlock:
    mutex_unlock(&slab_mutex);
}
EXPORT_SYMBOL(kmem_cache_destroy);


static int shutdown_cache(struct kmem_cache *s)
{
	/* free asan quarantined objects */
	kasan_cache_shutdown(s);

	if (__kmem_cache_shutdown(s) != 0)
		return -EBUSY;

	list_del(&s->list);

	if (s->flags & SLAB_TYPESAFE_BY_RCU) {
#ifdef SLAB_SUPPORTS_SYSFS
		sysfs_slab_unlink(s);
#endif
		list_add_tail(&s->list, &slab_caches_to_rcu_destroy);
		schedule_work(&slab_caches_to_rcu_destroy_work);
	} else {
		kfence_shutdown_cache(s);
#ifdef SLAB_SUPPORTS_SYSFS
		sysfs_slab_unlink(s);
		sysfs_slab_release(s);
#else
		slab_kmem_cache_release(s);
#endif
	}

	return 0;
}
```


```c
int __kmem_cache_shutdown(struct kmem_cache *cachep)
{
    return __kmem_cache_shrink(cachep);
}

int __kmem_cache_shrink(struct kmem_cache *cachep)
{
	int ret = 0;
	int node;
	struct kmem_cache_node *n;

	drain_cpu_caches(cachep);

	check_irq_on();
	for_each_kmem_cache_node(cachep, node, n) {
		drain_freelist(cachep, n, INT_MAX);

		ret += !list_empty(&n->slabs_full) ||
			!list_empty(&n->slabs_partial);
	}
	return (ret ? 1 : 0);
}
```

## free

在开始释放内存块 x 之前，内核需要首先通过 cache_from_obj 函数确认内存块 x 是否真正属于我们指定的 slab cache


virt_to_cache 函数首先会通过释放对象的虚拟内存地址找到其所在的物理内存页 page，然后通过 struct page 结构中的 slab_cache 指针找到 page 所属的 slab cache。


```c
// slub.c
void kmem_cache_free(struct kmem_cache *s, void *x)
{
    s = cache_from_obj(s, x);
    if (!s)
        return;
    slab_free(s, virt_to_head_page(x), x, NULL, 1, _RET_IP_);
    trace_kmem_cache_free(_RET_IP_, x, s->name);
}
EXPORT_SYMBOL(kmem_cache_free);
```


```c
static __always_inline void slab_free(struct kmem_cache *s, struct page *page,
                      void *head, void *tail, int cnt,
                      unsigned long addr)
{
    /*
     * With KASAN enabled slab_free_freelist_hook modifies the freelist
     * to remove objects, whose reuse must be delayed.
     */
    if (slab_free_freelist_hook(s, &head, &tail))
        do_slab_free(s, page, head, tail, cnt, addr);
}
```


```c
/*
 * Fastpath with forced inlining to produce a kfree and kmem_cache_free that
 * can perform fastpath freeing without additional function calls.
 *
 * The fastpath is only possible if we are freeing to the current cpu slab
 * of this processor. This typically the case if we have just allocated
 * the item before.
 *
 * If fastpath is not possible then fall back to __slab_free where we deal
 * with all sorts of special processing.
 *
 * Bulk free of a freelist with several objects (all pointing to the
 * same page) possible by specifying head and tail ptr, plus objects
 * count (cnt). Bulk free indicated by tail pointer being set.
 */
static __always_inline void do_slab_free(struct kmem_cache *s,
                struct page *page, void *head, void *tail,
                int cnt, unsigned long addr)
{
    void *tail_obj = tail ? : head;
    struct kmem_cache_cpu *c;
    unsigned long tid;

    memcg_slab_free_hook(s, &head, 1);
redo:
    /*
     * Determine the currently cpus per cpu slab.
     * The cpu may change afterward. However that does not matter since
     * data is retrieved via this pointer. If we are on the same cpu
     * during the cmpxchg then the free will succeed.
     */
    do {
        tid = this_cpu_read(s->cpu_slab->tid);
        c = raw_cpu_ptr(s->cpu_slab);
    } while (IS_ENABLED(CONFIG_PREEMPTION) &&
         unlikely(tid != READ_ONCE(c->tid)));

    /* Same with comment on barrier() in slab_alloc_node() */
    barrier();

    if (likely(page == c->page)) {
        void **freelist = READ_ONCE(c->freelist);

        set_freepointer(s, tail_obj, freelist);

        if (unlikely(!this_cpu_cmpxchg_double(
                s->cpu_slab->freelist, s->cpu_slab->tid,
                freelist, tid,
                head, next_tid(tid)))) {

            note_cmpxchg_failure("slab_free", s, tid);
            goto redo;
        }
        stat(s, FREE_FASTPATH);
    } else
        __slab_free(s, page, head, tail_obj, cnt, addr);

}
```



```c
/*
 * Slow path handling. This may still be called frequently since objects
 * have a longer lifetime than the cpu slabs in most processing loads.
 *
 * So we still attempt to reduce cache line usage. Just take the slab
 * lock and free the item. If there is no additional partial page
 * handling required then we can return immediately.
 */
static void __slab_free(struct kmem_cache *s, struct page *page,
            void *head, void *tail, int cnt,
            unsigned long addr)

{
    void *prior;
    int was_frozen;
    struct page new;
    unsigned long counters;
    struct kmem_cache_node *n = NULL;
    unsigned long flags;

    stat(s, FREE_SLOWPATH);

    if (kfence_free(head))
        return;

    if (kmem_cache_debug(s) &&
        !free_debug_processing(s, page, head, tail, cnt, addr))
        return;

    do {
        if (unlikely(n)) {
            spin_unlock_irqrestore(&n->list_lock, flags);
            n = NULL;
        }
        prior = page->freelist;
        counters = page->counters;
        set_freepointer(s, tail, prior);
        new.counters = counters;
        was_frozen = new.frozen;
        new.inuse -= cnt;
        if ((!new.inuse || !prior) && !was_frozen) {

            if (kmem_cache_has_cpu_partial(s) && !prior) {

                /*
                 * Slab was on no list before and will be
                 * partially empty
                 * We can defer the list move and instead
                 * freeze it.
                 */
                new.frozen = 1;

            } else { /* Needs to be taken off a list */

                n = get_node(s, page_to_nid(page));
                /*
                 * Speculatively acquire the list_lock.
                 * If the cmpxchg does not succeed then we may
                 * drop the list_lock without any processing.
                 *
                 * Otherwise the list_lock will synchronize with
                 * other processors updating the list of slabs.
                 */
                spin_lock_irqsave(&n->list_lock, flags);

            }
        }

    } while (!cmpxchg_double_slab(s, page,
        prior, counters,
        head, new.counters,
        "__slab_free"));

    if (likely(!n)) {

        if (likely(was_frozen)) {
            /*
             * The list lock was not taken therefore no list
             * activity can be necessary.
             */
            stat(s, FREE_FROZEN);
        } else if (new.frozen) {
            /*
             * If we just froze the page then put it onto the
             * per cpu partial list.
             */
            put_cpu_partial(s, page, 1);
            stat(s, CPU_PARTIAL_FREE);
        }

        return;
    }

    if (unlikely(!new.inuse && n->nr_partial >= s->min_partial))
        goto slab_empty;

    /*
     * Objects left in the slab. If it was not on the partial list before
     * then add it.
     */
    if (!kmem_cache_has_cpu_partial(s) && unlikely(!prior)) {
        remove_full(s, n, page);
        add_partial(n, page, DEACTIVATE_TO_TAIL);
        stat(s, FREE_ADD_PARTIAL);
    }
    spin_unlock_irqrestore(&n->list_lock, flags);
    return;

slab_empty:
    if (prior) {
        /*
         * Slab on the partial list.
         */
        remove_partial(n, page);
        stat(s, FREE_REMOVE_PARTIAL);
    } else {
        /* Slab must be on the full list */
        remove_full(s, n, page);
    }

    spin_unlock_irqrestore(&n->list_lock, flags);
    stat(s, FREE_SLAB);
    discard_slab(s, page);
}
```


```c
// slab.c
void kmem_cache_free(struct kmem_cache *cachep, void *objp)
{
    unsigned long flags;
    cachep = cache_from_obj(cachep, objp);
    if (!cachep)
        return;

    local_irq_save(flags);
    debug_check_no_locks_freed(objp, cachep->object_size);
    if (!(cachep->flags & SLAB_DEBUG_OBJECTS))
        debug_check_no_obj_freed(objp, cachep->object_size);
    __cache_free(cachep, objp, _RET_IP_);
    local_irq_restore(flags);

    trace_kmem_cache_free(_RET_IP_, objp, cachep->name);
}
EXPORT_SYMBOL(kmem_cache_free);
```

```c
/*
 * Release an obj back to its cache. If the obj has a constructed state, it must
 * be in this state _before_ it is released.  Called with disabled ints.
 */
static __always_inline void __cache_free(struct kmem_cache *cachep, void *objp,
                     unsigned long caller)
{
    if (is_kfence_address(objp)) {
        kmemleak_free_recursive(objp, cachep->flags);
        __kfence_free(objp);
        return;
    }

    if (unlikely(slab_want_init_on_free(cachep)))
        memset(objp, 0, cachep->object_size);

    /* Put the object into the quarantine, don't touch it for now. */
    if (kasan_slab_free(cachep, objp))
        return;

    /* Use KCSAN to help debug racy use-after-free. */
    if (!(cachep->flags & SLAB_TYPESAFE_BY_RCU))
        __kcsan_check_access(objp, cachep->object_size,
                     KCSAN_ACCESS_WRITE | KCSAN_ACCESS_ASSERT);

    ___cache_free(cachep, objp, caller);
}
```


最终调用到 alloc_pages
```c
// include/linux/gfp.h
#define __get_free_page(gfp_mask) \
		__get_free_pages((gfp_mask), 0)

#define __get_dma_pages(gfp_mask, order) \
		__get_free_pages((gfp_mask) | GFP_DMA, (order))

// mm/page_alloc.c
unsigned long get_zeroed_page(gfp_t gfp_mask)
{
    return __get_free_pages(gfp_mask | __GFP_ZERO, 0);
}
EXPORT_SYMBOL(get_zeroed_page);

unsigned long __get_free_pages(gfp_t gfp_mask, unsigned int order)
{
	struct page *page;

	page = alloc_pages(gfp_mask & ~__GFP_HIGHMEM, order);
	if (!page)
		return 0;
	return (unsigned long) page_address(page);
}
```

Slab 分配器提供的 API 为 kmalloc()和 kfree()

## kmalloc

kmalloc is the normal method of allocating memory for objects smaller than page size in the kernel.
The allocated object address is aligned to at least ARCH_KMALLOC_MINALIGN bytes.
For @size of power of two bytes, the alignment is also guaranteed to be at least to the size.
For other sizes, the alignment is guaranteed to be at least the largest power-of-two divisor of @size.



```c
static __always_inline void *kmalloc(size_t size, gfp_t flags)
{
    // ...
	return __kmalloc(size, flags);
}
```

如果通过kmalloc_large()进行内存分配，将会经kmalloc_large()->kmalloc_order()->__get_free_pages()，最终通过Buddy伙伴算法申请所需内存

```c
// mm/slab.c
static __always_inline void *__do_kmalloc(size_t size, gfp_t flags,
					  unsigned long caller)
{
	struct kmem_cache *cachep;
	void *ret;

	if (unlikely(size > KMALLOC_MAX_CACHE_SIZE))
		return NULL;
	cachep = kmalloc_slab(size, flags);
	if (unlikely(ZERO_OR_NULL_PTR(cachep)))
		return cachep;
	ret = slab_alloc(cachep, flags, size, caller);

	ret = kasan_kmalloc(cachep, ret, size, flags);
	trace_kmalloc(caller, ret,
		      size, cachep->size, flags);

	return ret;
}
```
kmalloc()实现较为简单，起分配所得的内存不仅是虚拟地址上的连续存储空间，同时也是物理地址上的连续存储空间



### kmalloc_index
```c

/*
 * Figure out which kmalloc slab an allocation of a certain size
 * belongs to.
 * 0 = zero alloc
 * 1 =  65 .. 96 bytes
 * 2 = 129 .. 192 bytes
 * n = 2^(n-1)+1 .. 2^n
 */
static __always_inline unsigned int kmalloc_index(size_t size)
{
	if (!size)
		return 0;

	if (size <= KMALLOC_MIN_SIZE)
		return KMALLOC_SHIFT_LOW;

	if (KMALLOC_MIN_SIZE <= 32 && size > 64 && size <= 96)
		return 1;
	if (KMALLOC_MIN_SIZE <= 64 && size > 128 && size <= 192)
		return 2;
	if (size <=          8) return 3;
	if (size <=         16) return 4;
	if (size <=         32) return 5;
	if (size <=         64) return 6;
	if (size <=        128) return 7;
	if (size <=        256) return 8;
	if (size <=        512) return 9;
	if (size <=       1024) return 10;
	if (size <=   2 * 1024) return 11;
	if (size <=   4 * 1024) return 12;
	if (size <=   8 * 1024) return 13;
	if (size <=  16 * 1024) return 14;
	if (size <=  32 * 1024) return 15;
	if (size <=  64 * 1024) return 16;
	if (size <= 128 * 1024) return 17;
	if (size <= 256 * 1024) return 18;
	if (size <= 512 * 1024) return 19;
	if (size <= 1024 * 1024) return 20;
	if (size <=  2 * 1024 * 1024) return 21;
	if (size <=  4 * 1024 * 1024) return 22;
	if (size <=  8 * 1024 * 1024) return 23;
	if (size <=  16 * 1024 * 1024) return 24;
	if (size <=  32 * 1024 * 1024) return 25;
	if (size <=  64 * 1024 * 1024) return 26;
	BUG();

	/* Will never be reached. Needed because the compiler may complain */
	return -1;
}
```

### insert_vm_struct
```c

/* Insert vm structure into process list sorted by address
 * and into the inode's i_mmap tree.  If vm_file is non-NULL
 * then i_mmap_rwsem is taken here.
 */
int insert_vm_struct(struct mm_struct *mm, struct vm_area_struct *vma)
{
	struct vm_area_struct *prev;
	struct rb_node **rb_link, *rb_parent;

	if (find_vma_links(mm, vma->vm_start, vma->vm_end,
			   &prev, &rb_link, &rb_parent))
		return -ENOMEM;
	if ((vma->vm_flags & VM_ACCOUNT) &&
	     security_vm_enough_memory_mm(mm, vma_pages(vma)))
		return -ENOMEM;

	/*
	 * The vm_pgoff of a purely anonymous vma should be irrelevant
	 * until its first write fault, when page's anon_vma and index
	 * are set.  But now set the vm_pgoff it will almost certainly
	 * end up with (unless mremap moves it elsewhere before that
	 * first wfault), so /proc/pid/maps tells a consistent story.
	 *
	 * By setting it to reflect the virtual start address of the
	 * vma, merges and splits can happen in a seamless way, just
	 * using the existing file pgoff checks and manipulations.
	 * Similarly in do_mmap and in do_brk_flags.
	 */
	if (vma_is_anonymous(vma)) {
		BUG_ON(vma->anon_vma);
		vma->vm_pgoff = vma->vm_start >> PAGE_SHIFT;
	}

	vma_link(mm, vma, prev, rb_link, rb_parent);
	return 0;
}
```


### find_vma
Look up the first VMA which satisfies  addr < vm_end,  NULL if none.
```c
// mm/mmap.c
struct vm_area_struct *find_vma(struct mm_struct *mm, unsigned long addr)
{
	struct rb_node *rb_node;
	struct vm_area_struct *vma;

	/* Check the cache first. */
	vma = vmacache_find(mm, addr);
	if (likely(vma))
		return vma;

	rb_node = mm->mm_rb.rb_node;

	while (rb_node) {
		struct vm_area_struct *tmp;

		tmp = rb_entry(rb_node, struct vm_area_struct, vm_rb);

		if (tmp->vm_end > addr) {
			vma = tmp;
			if (tmp->vm_start <= addr)
				break;
			rb_node = rb_node->rb_left;
		} else
			rb_node = rb_node->rb_right;
	}

	if (vma)
		vmacache_update(addr, vma);
	return vma;
}
```

### mmap2

```c

asmlinkage long sys_mmap2(unsigned long addr, unsigned long len,
	unsigned long prot, unsigned long flags,
	unsigned long fd, unsigned long pgoff)
{
	/*
	 * The shift for mmap2 is constant, regardless of PAGE_SIZE
	 * setting.
	 */
	if (pgoff & ((1 << (PAGE_SHIFT - 12)) - 1))
		return -EINVAL;

	pgoff >>= PAGE_SHIFT - 12;

	return ksys_mmap_pgoff(addr, len, prot, flags, fd, pgoff);
}
```


```c

unsigned long ksys_mmap_pgoff(unsigned long addr, unsigned long len,
			      unsigned long prot, unsigned long flags,
			      unsigned long fd, unsigned long pgoff)
{
	struct file *file = NULL;
	unsigned long retval;

	if (!(flags & MAP_ANONYMOUS)) {
		audit_mmap_fd(fd, flags);
		file = fget(fd);
		if (!file)
			return -EBADF;
		if (is_file_hugepages(file)) {
			len = ALIGN(len, huge_page_size(hstate_file(file)));
		} else if (unlikely(flags & MAP_HUGETLB)) {
			retval = -EINVAL;
			goto out_fput;
		}
	} else if (flags & MAP_HUGETLB) {
		struct user_struct *user = NULL;
		struct hstate *hs;

		hs = hstate_sizelog((flags >> MAP_HUGE_SHIFT) & MAP_HUGE_MASK);
		if (!hs)
			return -EINVAL;

		len = ALIGN(len, huge_page_size(hs));
		/*
		 * VM_NORESERVE is used because the reservations will be
		 * taken when vm_ops->mmap() is called
		 * A dummy user value is used because we are not locking
		 * memory so no accounting is necessary
		 */
		file = hugetlb_file_setup(HUGETLB_ANON_FILE, len,
				VM_NORESERVE,
				&user, HUGETLB_ANONHUGE_INODE,
				(flags >> MAP_HUGE_SHIFT) & MAP_HUGE_MASK);
		if (IS_ERR(file))
			return PTR_ERR(file);
	}

	flags &= ~(MAP_EXECUTABLE | MAP_DENYWRITE);

	retval = vm_mmap_pgoff(file, addr, len, prot, flags, pgoff);
out_fput:
	if (file)
		fput(file);
	return retval;
}
```

### page_fault

```c
// arch/arc/mm/fault.c
void do_page_fault(unsigned long address, struct pt_regs *regs)
{
	struct vm_area_struct *vma = NULL;
	struct task_struct *tsk = current;
	struct mm_struct *mm = tsk->mm;
	int sig, si_code = SEGV_MAPERR;
	unsigned int write = 0, exec = 0, mask;
	vm_fault_t fault = VM_FAULT_SIGSEGV;	/* handle_mm_fault() output */
	unsigned int flags;			/* handle_mm_fault() input */

	/*
	 * NOTE! We MUST NOT take any locks for this case. We may
	 * be in an interrupt or a critical region, and should
	 * only copy the information from the master page table,
	 * nothing more.
	 */
	if (address >= VMALLOC_START && !user_mode(regs)) {
		if (unlikely(handle_kernel_vaddr_fault(address)))
			goto no_context;
		else
			return;
	}

	/*
	 * If we're in an interrupt or have no user
	 * context, we must not take the fault..
	 */
	if (faulthandler_disabled() || !mm)
		goto no_context;

	if (regs->ecr_cause & ECR_C_PROTV_STORE)	/* ST/EX */
		write = 1;
	else if ((regs->ecr_vec == ECR_V_PROTV) &&
	         (regs->ecr_cause == ECR_C_PROTV_INST_FETCH))
		exec = 1;

	flags = FAULT_FLAG_DEFAULT;
	if (user_mode(regs))
		flags |= FAULT_FLAG_USER;
	if (write)
		flags |= FAULT_FLAG_WRITE;

	perf_sw_event(PERF_COUNT_SW_PAGE_FAULTS, 1, regs, address);
retry:
	mmap_read_lock(mm);

	vma = find_vma(mm, address);
	if (!vma)
		goto bad_area;
	if (unlikely(address < vma->vm_start)) {
		if (!(vma->vm_flags & VM_GROWSDOWN) || expand_stack(vma, address))
			goto bad_area;
	}

	/*
	 * vm_area is good, now check permissions for this memory access
	 */
	mask = VM_READ;
	if (write)
		mask = VM_WRITE;
	if (exec)
		mask = VM_EXEC;

	if (!(vma->vm_flags & mask)) {
		si_code = SEGV_ACCERR;
		goto bad_area;
	}

	fault = handle_mm_fault(vma, address, flags, regs);

	/* Quick path to respond to signals */
	if (fault_signal_pending(fault, regs)) {
		if (!user_mode(regs))
			goto no_context;
		return;
	}

	/*
	 * Fault retry nuances, mmap_lock already relinquished by core mm
	 */
	if (unlikely((fault & VM_FAULT_RETRY) &&
		     (flags & FAULT_FLAG_ALLOW_RETRY))) {
		flags |= FAULT_FLAG_TRIED;
		goto retry;
	}

bad_area:
	mmap_read_unlock(mm);

	/*
	 * Major/minor page fault accounting
	 * (in case of retry we only land here once)
	 */
	if (likely(!(fault & VM_FAULT_ERROR)))
		/* Normal return path: fault Handled Gracefully */
		return;

	if (!user_mode(regs))
		goto no_context;

	if (fault & VM_FAULT_OOM) {
		pagefault_out_of_memory();
		return;
	}

	if (fault & VM_FAULT_SIGBUS) {
		sig = SIGBUS;
		si_code = BUS_ADRERR;
	}
	else {
		sig = SIGSEGV;
	}

	tsk->thread.fault_address = address;
	force_sig_fault(sig, si_code, (void __user *)address);
	return;

no_context:
	if (fixup_exception(regs))
		return;

	die("Oops", regs, address);
}
```


## kfree

kfree - free previously allocated memory

```c
void kfree(const void *objp)
{
	struct kmem_cache *c;
	unsigned long flags;

	trace_kfree(_RET_IP_, objp);

	if (unlikely(ZERO_OR_NULL_PTR(objp)))
		return;
	local_irq_save(flags);
	kfree_debugcheck(objp);
	c = virt_to_cache(objp);
	if (!c) {
		local_irq_restore(flags);
		return;
	}
	debug_check_no_locks_freed(objp, c->object_size);

	debug_check_no_obj_freed(objp, c->object_size);
	__cache_free(c, (void *)objp, _RET_IP_);
	local_irq_restore(flags);
}
```

if (unlikely(ZERO_OR_NULL_PTR(x)))对地址做非零判断，接着virt_to_head_page(x)将虚拟地址转换到页面；再是判断if (unlikely(!PageSlab(page)))判断该页面是否作为slab分配管理，如果是的话则转为通过slab_free()进行释放，否则将进入if分支中；在if分支中，将会kfree_hook()做释放前kmemleak处理（该函数主要是封装了kmemleak_free()），完了之后将会__free_memcg_kmem_pages()将页面释放，同时该函数内也将cgroup释放处理



## Links

- [Linux Memory](/docs/CS/OS/Linux/mm/memory.md)


## References

1. [The Slab Allocator: An Object-Caching Kernel Memory Allocator](https://people.eecs.berkeley.edu/~kubitron/courses/cs194-24-S13/hand-outs/bonwick_slab.pdf)
2. [Linux 内核 | 内存管理——Slab 分配器](https://www.dingmos.com/index.php/archives/23/)