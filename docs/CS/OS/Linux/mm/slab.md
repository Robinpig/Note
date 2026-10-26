## Introduction

在 Linux 中，[buddy allocator](/docs/CS/OS/Linux/mm/pm.md?id=buddy) 以**页**为单位管理和分配内存，但内核里的需求往往以**字节**为单位——为一个 20 字节的 `task_struct` 分配一整页是灾难。slab 分配器分配内存以字节为单位，基于伙伴分配器的大内存进一步细分成小内存块：它仍然从 buddy 申请整页，再对申请来的页做细分管理。

除了"切小内存"，slab 还承担两项职责：

1. **维护常用对象的缓存**：许多内核结构初始化的开销可能接近甚至超过分配本身。新建 slab 时，若干对象被一并打包并用构造函数（若有）初始化；对象释放后保持初始化状态，下次分配可直接复用，省掉重复构造。
2. **提高 CPU 硬件缓存利用率（slab 着色）**：若对象在 slab 里包装后仍有剩余空间，剩余空间被用来给 slab **着色**——通过调整对象在 slab 内的起始偏移，让不同 slab 里的对象落到 CPU cache 的不同 cache line，降低同一缓存组里的互相刷新。

> 举例：管理与进程关联的文件系统时，内核经常生成 `struct fs_struct` 新实例、又在进程结束时回收。slab 把释放的块留在内部列表、不立即还给伙伴系统；下次请求同类对象时复用最近释放的块。好处有二：一是绕过伙伴算法、处理更快；二是该内存块仍是"新"的，驻留在 CPU 硬件缓存的概率更高。

### History and the Current State of the Three Implementations

slab 的概念最早由 Sun 的 **Jeff Bonwick** 在 Solaris 2.4 中设计并公开，Linux 于 **2.0（1996）** 借鉴引入。随后内核里长期并存过三套实现，但到主线 7.x 时格局已彻底改变：

| 实现 | 引入 | 特点 | 现状 |
| :--- | :--- | :--- | :--- |
| **SLAB** | Linux 2.0（移植自 Solaris） | 经典 Bonwick 设计：每 CPU 队列 + 每节点共享队列 + alien 队列三级结构，元数据臃肿、对 NUMA 支持繁杂 | **已于 v6.8 从主线移除**（v6.5 弃用）。历史上 `mm/slab.c` 的实现，如今是死代码 |
| **SLUB** | Linux 2.6.23（Christoph Lameter） | 去掉所有队列，对象留在原页上，用 per-CPU freelist 的 `cmpxchg` 实现无锁快路径；元数据少、锁少、碎片低 | **自 2.6.23 起默认，目前主线唯一实现**（`mm/slub.c`） |
| **SLOB** | Linux 2.6.16 | 极简 first-fit，面向无 MMU / 极小内存的嵌入式 | **已于 v6.4 从主线移除** |

> [!WARNING]
> 本文里凡是标注来自 `mm/slab.c` 的代码（如 `__kmem_cache_create` 里的 `CFLGS_OFF_SLAB`、`SLAB_RED_ZONE` 处理逻辑、`__cache_free` 等）都是**历史 SLAB 分配器**的实现，在主线程 7.x 中已不存在。它们仅用于理解原始设计，现行代码路径全部在 `mm/slub.c`。SLUB 同样支持 debug（通过 `slub_debug=` 而非旧的 `SLAB_*` 标志），下文会区分说明。

现代内核常用实现是 **SLUB**。SLUB 之上，6.18 又引入了 **per-CPU sheaves**（见 [Allocation](#allocation)）作为可选的对象缓存层，进一步降低快路径的原子开销。

### Architecture

slab 对象池建在伙伴系统之上：一次性向 buddy 申请一个或多个完整物理页，再在这些页内逐步切出小块（即对象）。凡是被内核频繁创建/销毁的对象都由专属 slab 管理，例如：

- `fork()` 创建进程时，用 `task_struct` 专属 cache 分配 `task_struct`；
- 建立进程虚拟地址空间时，用 `mm_struct` 专属 cache 分配 `mm_struct`；
- 页高速缓存查找文件缓存页时，用 `struct page` 专属 cache 分配 `struct page`；
- `open()` 打开文件时，用 `struct file` 专属 cache 分配 `struct file`；
- 服务端 `accept()` 接收连接时，用 `struct socket` 专属 cache 分配 `socket`。

SLUB 复用 `struct page` 的字段来描述一个 slab（单个 slab 即 2^order 个连续页框），每个 slab 切成多个等长对象：

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

每个对象类型对应一个 **`kmem_cache`**（缓存描述符），它把所有 node 上的 slab 统一调配起来。内核通过 `slab_caches` 双向链表把所有 `kmem_cache` 串起来。

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
	unsigned int cpu_partial;	/* per cpu partial objects to keep */
	unsigned int cpu_partial_slabs;/* per cpu partial slabs to keep */
#endif
	struct kmem_cache_order_objects oo;   /* 快路径用的 order+objects */
	struct kmem_cache_order_objects min;  /* 慢路径兜底的最小配置 */
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
	unsigned int remote_node_defrag_ratio;/* 远程 node 借对象的比例 */
#endif
#ifdef CONFIG_SLAB_FREELIST_RANDOM
	unsigned int *random_seq;
#endif
#ifdef CONFIG_HARDENED_USERCOPY
	unsigned int useroffset;	/* Usercopy region offset */
	unsigned int usersize;		/* Usercopy region size */
#endif
	struct kmem_cache_node *node[MAX_NUMNODES];
};
```

### kmem_cache_node and the Partial/Full Lists

SLUB 里每个 NUMA node 一个 `kmem_cache_node`，用链表管理该 node 上的 slab。注意 SLUB **只有 partial 与 full 两类链表**（原始 SLAB 还有 slabs_free；SLUB 认为"完全空"的 slab 直接还给 buddy，不长期留着）：

```c
struct kmem_cache_node {
    spinlock_t list_lock;
#ifdef CONFIG_SLAB
    struct list_head slabs_partial;
    struct list_head slabs_full;
    struct list_head slabs_free;
    unsigned long total_slabs;
    unsigned long free_slabs;
    unsigned long free_objects;
    unsigned int free_limit;
    unsigned int colour_next;   /* Per-node cache coloring */
    struct array_cache *shared;
    struct alien_cache **alien;
    unsigned long next_reap;
    int free_touched;
#else  /* SLUB */
    struct list_head  partial;  /* 部分分配的 slab（有空闲也有占用） */
#ifdef CONFIG_SLUB_DEBUG
    struct list_head  full;     /* 仅 debug 时存在：全满的 slab */
#endif
    unsigned long  nr_partial;  /* partial 链表上的 slab 数 */
    unsigned long  nr_slabs;    /* 该 node 上总 slab 数 */
    unsigned long  total_objects;
    unsigned long  cpu_partial;  /* 期望保留的 per-cpu partial 对象数 */
#endif
};
```

- `partial`：部分分配的 slab（既有空闲对象也有在用对象）；
- `full`：全部分配完的 slab（SLUB 仅在 `CONFIG_SLUB_DEBUG` 时维护，用于调试统计）。

单个 slab 会在链表间移动——例如一个 `partial` slab 被分配满后，从 `partial` 摘除；其对象全部释放后，若超过 `min_partial` 则直接 `discard_slab` 还给 buddy。

### order_objects: oo and min

`oo`（`kmem_cache_order_objects`）同时编码一个 slab 占多少页（order）和能切出多少个对象。`min` 是慢路径兜底时允许的最小配置：

```c
struct kmem_cache_order_objects {
	unsigned int x;
};
/* 高位存 order，低位存 objects，例如 oo = (order << 16) | objects */
```

`calculate_order()`（SLUB）在创建 cache 时决定 order：在 `slub_min_order`~`slub_max_order` 之间尽量让单 slab 的**浪费比例 ≤ 1/16**，同时满足"每 CPU 至少能摊到若干个对象"。浪费过大（如 64 字节对象若只用 8KB 页只能放 128 个、内部碎片低）就升 order，但 order 上限受 `MAX_OBJS_PER_PAGE` 与 `slub_max_order` 约束。

### Coloring

SLUB 放弃了原始 SLAB 那种效果有限的着色机制（现代 CPU cache 关联度已高），但 `struct kmem_cache` 仍保留 `align` 与 `red_left_pad` 等字段。原始 SLAB 的着色逻辑是：

- `colour_off = cache_line_size()`：每个着色步长至少一个 cache line；
- `colour_next`：每分配一个新 slab 就递增着色编号，让对象起始地址错开 cache line；
- 着色空间来自"对象大小向上对齐后剩余的那点 padding"，不额外耗内存。

由于 SLUB 默认不做着色，这里仅作历史沿革记录，避免读老资料时误以为现行内核仍有显著着色行为。

## kmalloc

`kmalloc()` 是通用小内存入口，背后是一组**按尺寸预建**的通用 cache（`kmalloc-8`/`kmalloc-16`/…）。`kmalloc_info[]` 让 `slub_debug=,kmalloc-xx` 这类启动参数能工作；`kmalloc_index()` 支持到 2^26 = 64MB，所以表尾是 `kmalloc-67108864`。

index = 1 与 index = 2 是例外：内核单独支持 **`kmalloc-96`** 与 **`kmalloc-192`** 两个通用 cache。因为内核大部分申请落在 96 或 192 字节附近——若不单独支持，64~96 字节之间的请求会落到 `kmalloc-128`，造成可观的内部碎片。

kmalloc 支持的最小块由 `KMALLOC_SHIFT_LOW` 决定（SLUB 下 = 3，即 8 字节），最大块由 `KMALLOC_SHIFT_HIGH` 决定（SLUB 下 = 13，即 **8KB = 两个页**）。超过 8KB 的请求走 `kmalloc_large()` → buddy 直接整页分配，不再走 slab cache：

| kmalloc cache | 对象尺寸 | 说明 |
| :--- | :--- | :--- |
| kmalloc-8 | 8 B | 最小块（≤8 字节请求落此） |
| kmalloc-16 | 16 B | |
| kmalloc-32 | 32 B | |
| kmalloc-64 | 64 B | |
| kmalloc-96 | 96 B | **非 2 的幂，专门补充** |
| kmalloc-128 | 128 B | |
| kmalloc-192 | 192 B | **非 2 的幂，专门补充** |
| kmalloc-256 | 256 B | |
| kmalloc-512 | 512 B | |
| kmalloc-1k | 1024 B | |
| kmalloc-2k | 2 KB | |
| kmalloc-4k | 4 KB | |
| kmalloc-8k | 8 KB | SLUB 下最大 slab cache；更大走 buddy |

```c
/*
 * Figure out which kmalloc slab an allocation of a certain size belongs to.
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
	if (size <=   2 * 1024) return 10;
	if (size <=   4 * 1024) return 11;
	if (size <=   8 * 1024) return 12;   /* SLUB 最大 slab cache */
	/* 大于 8K：kmalloc_large() 直接走 buddy（下面继续到 64MB 索引） */
	if (size <=  16 * 1024) return 13;
	/* ... 一直到 index 26 = 64MB，但均经 kmalloc_large -> alloc_pages ... */
	BUG();
	return -1;
}
```

`kmalloc()` 分配所得内存**物理地址与虚拟地址都连续**（因为它最终落在一个 slab 页或 buddy 整页里）。

## Cache Lifecycle

### kmem_cache_init (bootstrap)

系统启动时，`kmem_cache_init()` 先用自己的 boot 版结构 `boot_kmem_cache` / `boot_kmem_cache_node` 给自己（即 `kmem_cache` 这个 cache 本身）分配内存，再 `bootstrap()` 切换成正式 cache，然后建好所有 kmalloc 通用 cache：

```c
void __init kmem_cache_init(void)
{
	static __initdata struct kmem_cache boot_kmem_cache, boot_kmem_cache_node;
	int node;

	if (debug_guardpage_minorder())
		slub_max_order = 0;

	if (__slub_debug_enabled())
		no_hash_pointers_enable(NULL);

	kmem_cache_node = &boot_kmem_cache_node;
	kmem_cache = &boot_kmem_cache;

	for_each_node_state(node, N_NORMAL_MEMORY)
		node_set(node, slab_nodes);

	create_boot_cache(kmem_cache_node, "kmem_cache_node",
			sizeof(struct kmem_cache_node),
			SLAB_HWCACHE_ALIGN | SLAB_NO_OBJ_EXT, 0, 0);
	hotplug_memory_notifier(slab_memory_callback, SLAB_CALLBACK_PRI);
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

	init_freelist_randomization();
	cpuhp_setup_state_nocalls(CPUHP_SLUB_DEAD, "slub:dead", NULL, slub_cpu_dead);
}
```

`create_kmalloc_caches()` 按 `KMALLOC_MIN_SIZE` 与 `KMALLOC_SHIFT_LOW..HIGH` 把每个尺寸的通用 cache 建出来；其中 size ≤ 32/64 时额外补 `kmalloc-96`/`kmalloc-192`：

```c
void __init create_kmalloc_caches(void)
{
	int i;
	enum kmalloc_cache_type type;

	for (type = KMALLOC_NORMAL; type < NR_KMALLOC_TYPES; type++) {
		if (KMALLOC_MIN_SIZE <= 32)
			new_kmalloc_cache(1, type);   /* kmalloc-96 */
		if (KMALLOC_MIN_SIZE <= 64)
			new_kmalloc_cache(2, type);   /* kmalloc-192 */

		for (i = KMALLOC_SHIFT_LOW; i <= KMALLOC_SHIFT_HIGH; i++)
			new_kmalloc_cache(i, type);   /* 2 的幂尺寸 */
	}
	slab_state = UP;   /* Kmalloc array is now usable */
}
```

### kmem_cache_create / kmem_cache_create_usercopy

内核子系统用 `kmem_cache_create()` 为自己频繁使用的对象建立专属 cache（如 `task_struct`、`inode`）。它会先尝试**合并**到已有的等价 cache（size/align/flags/ctor 相同则复用，省元数据），失败才新建：

```c
struct kmem_cache *
kmem_cache_create(const char *name, unsigned int size, unsigned int align,
		slab_flags_t flags, void (*ctor)(void *))
{
	return kmem_cache_create_usercopy(name, size, align, flags, 0, 0, ctor);
}
```

`kmem_cache_create_usercopy()` 是真正入口，额外带 `useroffset`/`usersize` 描述"允许被 `copy_to_user` 拷贝"的对象区间（用于 `HARDENED_USERCOPY` 防护越界拷贝）：

```c
struct kmem_cache *
kmem_cache_create_usercopy(const char *name, unsigned int size, unsigned int align,
		slab_flags_t flags, unsigned int useroffset, unsigned int usersize,
		void (*ctor)(void *))
{
	struct kmem_cache *s = NULL;
	const char *cache_name;
	int err;

	mutex_lock(&slab_mutex);
	err = kmem_cache_sanity_check(name, size);
	if (err) goto out_unlock;
	if (flags & ~SLAB_FLAGS_PERMITTED) { err = -EINVAL; goto out_unlock; }

	flags &= CACHE_CREATE_MASK;

	/* Fail closed on bad usersize of useroffset values. */
	if (WARN_ON(!usersize && useroffset) ||
	    WARN_ON(size < usersize || size - usersize < useroffset))
		usersize = useroffset = 0;

	if (!usersize)
		s = __kmem_cache_alias(name, size, align, flags, ctor);  /* 先尝试合并 */
	if (s) goto out_unlock;

	cache_name = kstrdup_const(name, GFP_KERNEL);
	if (!cache_name) { err = -ENOMEM; goto out_unlock; }

	s = create_cache(cache_name, size, calculate_alignment(flags, align, size),
			 flags, useroffset, usersize, ctor, NULL);
	/* ... */
out_unlock:
	mutex_unlock(&slab_mutex);
	if (err) {
		if (flags & SLAB_PANIC)
			panic("kmem_cache_create: Failed to create slab '%s'. Error %d\n", name, err);
		else { pr_warn("kmem_cache_create(%s) failed with error %d\n", name, err); dump_stack(); }
		return NULL;
	}
	return s;
}
```

> 查看不同尺寸的 slab cache 实时占用：`cat /proc/slabinfo` 或 `slabtop`。

### kmem_cache_destroy

引用计数归零后才真正关闭 cache；若 cache 里还有存活对象，`shutdown_cache()` 返回 `-EBUSY` 并报错。`SLAB_TYPESAFE_BY_RCU` 的 cache 不能立即释放，要延迟到 RCU 宽限期之后（见 [Allocation](#allocation)）：

```c
void kmem_cache_destroy(struct kmem_cache *s)
{
	int err;
	if (unlikely(!s)) return;
	mutex_lock(&slab_mutex);
	s->refcount--;
	if (s->refcount) goto out_unlock;
	err = shutdown_cache(s);
	if (err) { pr_err("kmem_cache_destroy %s: Slab cache still has objects\n", s->name); dump_stack(); }
out_unlock:
	mutex_unlock(&slab_mutex);
}
EXPORT_SYMBOL(kmem_cache_destroy);
```

> [!NOTE]
> 下面是**历史 SLAB 分配器**（`mm/slab.c`，v6.8 已移除）的 `__kmem_cache_create` 片段，仅用于对照理解原始设计里的 off-slab freelist、redzone、poison 处理。现行 SLUB 的路径不同（见 [Object Layout and Metadata](#object-layout-and-metadata)）。
>
> ```c
> int __kmem_cache_create(struct kmem_cache *cachep, slab_flags_t flags)
> {
> 	/* ... 对齐与 redzone/poison 处理 ... */
> 	if (set_objfreelist_slab_cache(cachep, size, flags)) { flags |= CFLGS_OBJFREELIST_SLAB; goto done; }
> 	if (set_off_slab_cache(cachep, size, flags))        { flags |= CFLGS_OFF_SLAB;       goto done; }
> 	if (set_on_slab_cache(cachep, size, flags))         { goto done; }
> 	return -E2BIG;
> done:
> 	if (OFF_SLAB(cachep))
> 		cachep->freelist_cache = kmalloc_slab(cachep->freelist_size, 0u);
> 	err = setup_cpu_cache(cachep, gfp);
> 	if (err) { __kmem_cache_release(cachep); return err; }
> 	return 0;
> }
> ```

## Allocation

### kmalloc

`kmalloc()` 先按 `kmalloc_index()` 选 cache，再走 `slab_alloc()`；超过 8KB 由 `kmalloc_large()` → `kmalloc_order()` → `__get_free_pages()` 直接走 buddy：

```c
static __always_inline void *__do_kmalloc(size_t size, gfp_t flags, unsigned long caller)
{
	struct kmem_cache *cachep;
	void *ret;

	if (unlikely(size > KMALLOC_MAX_CACHE_SIZE))
		return NULL;
	cachep = kmalloc_slab(size, flags);          /* 选 kmalloc-<size> cache */
	if (unlikely(ZERO_OR_NULL_PTR(cachep)))
		return cachep;
	ret = slab_alloc(cachep, flags, size, caller);
	ret = kasan_kmalloc(cachep, ret, size, flags);
	trace_kmalloc(caller, ret, size, cachep->size, flags);
	return ret;
}
```

### kmem_cache_alloc / kmem_cache_alloc_node

专属 cache 的分配入口。`kmem_cache_alloc_node()` 可指定 NUMA node 以贴近数据，提升本地内存访问性能；不指定时填 `NUMA_NO_NODE`：

```c
void *kmem_cache_alloc_noprof(struct kmem_cache *s, gfp_t gfpflags)
{
	void *ret;
	const struct slab_alloc_context ac = {
		.caller_addr = _RET_IP_,
		.orig_size = s->object_size,
		.alloc_flags = SLAB_ALLOC_DEFAULT,
	};
	ret = slab_alloc_node(s, gfpflags, NUMA_NO_NODE, &ac);
	trace_kmem_cache_alloc(_RET_IP_, ret, s, gfpflags, NUMA_NO_NODE);
	return ret;
}
EXPORT_SYMBOL(kmem_cache_alloc_noprof);
```

### SLUB Fast Path

在 6.18 之前（以及未启用 sheaves 的 cache），SLUB 快路径依赖每 CPU 的 `kmem_cache_cpu`：它持有当前活跃 slab 的 `freelist`（空闲对象链表头）与 `tid`（事务 ID）。分配时**无锁**地用 `this_cpu_cmpxchg_double` 把 `freelist` 与 `tid` 一起原子更新；若 freelist 为空或 cmpxchg 失败（被抢占/迁移到别的 CPU），才退化到慢路径。freelist 指针存放在**对象自身内部**（`offset` 处），分配出去时被真实数据覆盖——因此不额外占内存。

慢路径 `__slab_alloc` 负责：从 node 的 `partial` 链表取一个 slab、必要时向 buddy 申请新页并切出对象、处理 debug 钩子。这一"CPU 本地 → node partial → 向 buddy 要新 slab"的三级回退是 SLUB 多年来的稳定骨架。

### Per-CPU Sheaves (since 6.18)

6.18 起，SLUB 引入了可选的 **per-CPU sheaves** 缓存层（`struct slub_percpu_sheaves`，挂在 `kmem_cache->cpu_sheaves` 上），作为对经典 per-CPU freelist 的替代与优化。每个 CPU 持有一主一备两个 "sheaf"（数组），分配优先从 `main` sheaf 取，空了再换 `spare` 或从 per-node 的 "barn" 取满 sheaf：

```c
void *alloc_from_pcs(struct kmem_cache *s, gfp_t gfp, unsigned int alloc_flags, int node)
{
	struct slub_percpu_sheaves *pcs;
	bool node_requested;
	void *object;

	if (!local_trylock(&s->cpu_sheaves->lock))
		return NULL;

	pcs = this_cpu_ptr(s->cpu_sheaves);
	if (unlikely(pcs->main->size == 0))
		pcs = __pcs_replace_empty_main(s, pcs, gfp, alloc_flags);
	if (unlikely(!pcs))
		return NULL;

	object = pcs->main->objects[pcs->main->size - 1];
	/* NUMA 受限分配会绕过 sheaves，校验对象确实来自目标 node */
	if (unlikely(node_requested) &&
	    page_to_nid(virt_to_page(object)) != node) {
		local_unlock(&s->cpu_sheaves->lock);
		stat(s, ALLOC_NODE_MISMATCH);
		return NULL;
	}
	pcs->main->size--;
	local_unlock(&s->cpu_sheaves->lock);
	stat(s, ALLOC_FASTPATH);
	return object;
}
```

sheaves 带来的变化：**快路径从"本地双 cmpxchg"变成"`preempt_disable()` + 无原子操作"**，分配/释放都更便宜；还顺带优化了 `kfree_rcu()` 的批处理与回收（整 sheaf 提交给 `call_rcu()`，宽限期后整体复用）。需要注意：

- sheaves 是 **opt-in**（创建 cache 时通过 `struct kmem_cache_args` 的 `sheaf_capacity` 字段开启），并非所有 cache 都启用；
- 启用 `slub_debug` 或 `CONFIG_SLUB_TINY` 时**不创建 per-CPU sheaves**，以保留原有 node partial 慢路径上的调试钩子；
- NUMA 受限分配（`strict_numa`、指定 node）会绕过 sheaves。

概念上，sheaves 只是把"CPU 本地对象缓存"做得更轻量，[三级回退](#slub-fast-path)（本地 → node partial → 新 slab）的层次关系不变。

### SLAB_TYPESAFE_BY_RCU

这是个特殊 flag：带它的 cache 允许对象在**仍可能被 RCU 读者并发访问**时被分配/释放。典型例子是 `struct sock`/`struct file` 这类通过 RCU 查找的对象。其语义是：

- 释放对象不立即清零/回收，而是等 RCU 宽限期后才真正复用内存；
- 读者在 RCU 读侧临界区里拿到一个指针后，即便对象被"释放"也可能仍指向有效内存，但**对象内容可能已被新所有者改写**——读者必须自己做一致性校验（如比对 key），不能假设字段不变。

所以 `kmem_cache_destroy` 对这类 cache 走 `slab_caches_to_rcu_destroy` 延迟释放（`shutdown_cache()` 片段已体现）。

## Free

释放前先通过 `virt_to_head_page()` 找到对象所在页，再用 `page->slab_cache` 确认它属于哪个 cache（`cache_from_obj`），防止误释放到错误 cache。

> [!NOTE]
> 下面 `do_slab_free` / `__slab_free` 是**经典 SLUB**（per-CPU freelist 模型）的代码，对应未启用 sheaves 的 cache；启用 sheaves 后释放优先走 per-CPU sheaf 的入栈路径。

```c
void kmem_cache_free(struct kmem_cache *s, void *x)
{
	s = cache_from_obj(s, x);
	if (!s) return;
	slab_free(s, virt_to_head_page(x), x, NULL, 1, _RET_IP_);
	trace_kmem_cache_free(_RET_IP_, x, s->name);
}
EXPORT_SYMBOL(kmem_cache_free);

static __always_inline void do_slab_free(struct kmem_cache *s, struct page *page,
		void *head, void *tail, int cnt, unsigned long addr)
{
	void *tail_obj = tail ? : head;
	struct kmem_cache_cpu *c;
	unsigned long tid;

	/* 快路径：对象刚在本 CPU 的活跃 slab 上分配，直接 cmpxchg 回 freelist */
redo:
	do {
		tid = this_cpu_read(s->cpu_slab->tid);
		c = raw_cpu_ptr(s->cpu_slab);
	} while (IS_ENABLED(CONFIG_PREEMPTION) &&
		 unlikely(tid != READ_ONCE(c->tid)));
	barrier();

	if (likely(page == c->page)) {
		void **freelist = READ_ONCE(c->freelist);
		set_freepointer(s, tail_obj, freelist);
		if (unlikely(!this_cpu_cmpxchg_double(
				s->cpu_slab->freelist, s->cpu_slab->tid,
				freelist, tid, head, next_tid(tid)))) {
			note_cmpxchg_failure("slab_free", s, tid);
			goto redo;
		}
		stat(s, FREE_FASTPATH);
	} else
		__slab_free(s, page, head, tail_obj, cnt, addr);   /* 慢路径 */
}
```

`__slab_free` 慢路径处理对象不在本 CPU 活跃 slab 的情况：必要时加 node 锁，把 slab 在 full/partial 间迁移；若 slab 完全变空且 node 的 `nr_partial` 已超过 `min_partial`，则 `discard_slab()` 把整页还给 buddy：

```c
static void __slab_free(struct kmem_cache *s, struct page *page,
		void *head, void *tail, int cnt, unsigned long addr)
{
	void *prior;
	int was_frozen;
	struct page new;
	unsigned long counters;
	struct kmem_cache_node *n = NULL;
	unsigned long flags;
	/* ... */
	do {
		prior = page->freelist;
		counters = page->counters;
		set_freepointer(s, tail, prior);
		new.counters = counters;
		was_frozen = new.frozen;
		new.inuse -= cnt;
		if ((!new.inuse || !prior) && !was_frozen) {
			if (kmem_cache_has_cpu_partial(s) && !prior)
				new.frozen = 1;            /* 冻结，延迟入 partial 链表 */
			else {
				n = get_node(s, page_to_nid(page));
				spin_lock_irqsave(&n->list_lock, flags);
			}
		}
	} while (!cmpxchg_double_slab(s, page, prior, counters, head, new.counters, "__slab_free"));

	if (unlikely(!new.inuse && n->nr_partial >= s->min_partial))
		goto slab_empty;       /* 空闲过多，整 slab 回收 */
	/* ... 否则加入 node 的 partial 链表 ... */
slab_empty:
	/* 从 partial/full 摘除并 discard_slab 还给 buddy */
	spin_unlock_irqrestore(&n->list_lock, flags);
	stat(s, FREE_SLAB);
	discard_slab(s, page);
}
```

> [!NOTE]
> 下面 `kmem_cache_free` / `__cache_free` 来自**历史 SLAB 分配器**（`mm/slab.c`，v6.8 已移除），仅作对照，现行内核走上面 SLUB 的路径：
>
> ```c
> void kmem_cache_free(struct kmem_cache *cachep, void *objp)
> {
> 	unsigned long flags;
> 	cachep = cache_from_obj(cachep, objp);
> 	if (!cachep) return;
> 	local_irq_save(flags);
> 	debug_check_no_locks_freed(objp, cachep->object_size);
> 	if (!(cachep->flags & SLAB_DEBUG_OBJECTS))
> 		debug_check_no_obj_freed(objp, cachep->object_size);
> 	__cache_free(cachep, objp, _RET_IP_);
> 	local_irq_restore(flags);
> 	trace_kmem_cache_free(_RET_IP_, objp, cachep->name);
> }
> EXPORT_SYMBOL(kmem_cache_free);
> ```

### kfree

`kfree()` 与 `kmem_cache_free()` 同源：对空/null 直接返回；通过 `virt_to_cache()` 找到所属 cache；若页面本身不是 slab 管理的（例如 `kmalloc_large` 走 buddy 的大块），则走页级释放并附带 memcg 处理（对象级记账见 [cgroup 内存控制（memcg）](/docs/CS/OS/Linux/mm/memcg.md)：一个 slab 页里可能混着不同 memcg 的对象，所以 kmem 记账走 `obj_cgroup` 而非页级，分配与释放钩子必须成对出现）。

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
	if (!c) { local_irq_restore(flags); return; }
	debug_check_no_locks_freed(objp, c->object_size);
	debug_check_no_obj_freed(objp, c->object_size);
	__cache_free(c, (void *)objp, _RET_IP_);
	local_irq_restore(flags);
}
```

## Object Layout and Metadata

一个对象的真实占用 = `object_size`（用户数据）+ 元数据。SLUB 的元数据布局由几个字段决定：

- **free pointer（`offset`）**：空闲对象里在 `offset` 处存"下一个空闲对象"的指针；对象分配出去后这段被用户数据覆盖。所以 freelist 不另占内存。
- **`red_left_pad` / 红区（redzone）**：开启 debug 时，在对象左侧（及右侧）填充特殊字节，用于检测**缓冲区溢出/下溢**。
- **poison（染色）**：开启 debug 时，释放的对象体填 `POISON_FREE = 0x6b`（捕获 use-after-free），尚未初始化的对象填 `POISON_INUSE = 0x5a`（捕获未初始化读）。注意这与旧 SLAB 的 `a5a5a5a5` 不同。

```c
/* include/linux/poison.h */
#define POISON_INUSE  0x5a  /* 分配但未初始化时的染色 */
#define POISON_FREE   0x6b  /* 释放后的染色（捕获 use-after-free） */
```

- **`HARDENED_USERCOPY` 用户区**：`useroffset`/`usersize` 限定对象里允许被 `copy_to_user` 拷贝的区间，越界拷贝会被拦截（防御内核对象泄漏/越界读写）。
- **`SLAB_FREELIST_HARDENED`**：freelist 指针与 `random` 做混淆（`ptr ^ random ^ ptr_addr`），对抗 freelist 劫持类堆利用。
- **`SLAB_FREELIST_RANDOM`**：cache 创建时按 `random_seq` 打乱空闲对象顺序，增加堆喷（heap spray）预测难度。

## NUMA

NUMA 下分配优先在**本地 node** 取 slab，减少跨 socket 远端访问。`kmem_cache` 的 `remote_node_defrag_ratio` 控制"本地不足时从远程 node 借对象"的比例（0=绝不借，100=积极借）。指定 node 的分配（`kmem_cache_alloc_node`）会严格走目标 node 的 `kmem_cache_node`；在 `strict_numa` 模式下即便本地紧张也不降级到远端。启用 sheaves 后，**NUMA 受限分配会绕过 per-CPU sheaves**，退回到 node partial 慢路径以保证 locality。

## Debugging and Hardening

SLUB 的调试通过 **`slub_debug=` 启动参数**或 `CONFIG_SLUB_DEBUG` 打开，选项字母含义：

| 选项 | 含义 |
| :--- | :--- |
| `F` | Sanity checks，分配/释放时校验 slab 元数据一致性（代价高） |
| `Z` | Red zones，对象前后填充红区，检测溢出/下溢 |
| `P` | Poisoning，填充 `0x6b`/`0x5a` 捕获 use-after-free / 未初始化读 |
| `U` | User tracking，记录每个对象的分配/释放调用栈（可经 sysfs 查看） |
| `T` | Trace，跟踪所有 alloc/free |
| `A` | 等价于 `F+Z+P+U` 全开 |
| `O` | 对匹配到的 cache 关闭调试 |

安全加固相关的配置：`CONFIG_SLAB_FREELIST_HARDENED`、`CONFIG_SLAB_FREELIST_RANDOM`、`CONFIG_HARDENED_USERCOPY`；内存错误检测另有 `CONFIG_KASAN`（运行时检测越界/use-after-free）与 `CONFIG_KFENCE`（低开销采样式检测）。`CONFIG_SLUB_TINY` 是面向极小内存设备的精简版（关掉部分 per-CPU 机制与 debug 钩子）。

## Observability

- **`/proc/slabinfo`**：所有 cache 的对象数、活跃数、页占用等统计；`slabtop`（procps 工具）是其实时可视化。
- **`/sys/kernel/slab/<cache>/`**：每个 cache 一个目录，可读 `object_size`、`size`、`align`、`order`、`slabs`、`partial`、`objects`、`cpu_slabs`、`free` 等，debug 开启时还有 `red_zone`、`poison`、`sanity_checks`、`trace` 等开关与统计。
- **`/sys/kernel/debug/slab`**（需 `CONFIG_DEBUG_SLUB`）：全局 slab 调试信息。

这些接口是排障"内核内存去哪了"的第一手数据——比如某子系统泄漏，会在对应 `kmalloc-*` 或专属 cache 的 `active_objs` 上持续涨、不回落。

## Links

- [内存管理知识地图（mm 枢纽）](/docs/CS/OS/Linux/mm/README.md)
- [物理内存与 buddy 分配器](/docs/CS/OS/Linux/mm/pm.md?id=buddy) — slab 的底层整页来源
- [mempool 紧急内存担保](/docs/CS/OS/Linux/mm/mempool.md) — slab 之上的"绝不能失败"层
- [cgroup 内存控制（memcg）](/docs/CS/OS/Linux/mm/memcg.md) — slab 对象级记账
- [Nginx Memory](/docs/CS/CN/nginx/memory.md) — 用户态自研内存池，以及共享内存里那套「按页 slab」的实现

## References

1. [The Slab Allocator: An Object-Caching Kernel Memory Allocator (Bonwick, 1994)](https://people.eecs.berkeley.edu/~kubitron/courses/cs194-24-S13/hand-outs/bonwick_slab.pdf)
2. [Linux 内核 | 内存管理——Slab 分配器](https://www.dingmos.com/index.php/archives/23/)
3. [Kernel documentation — SLUB](https://docs.kernel.org/mm/slub.html)
4. [LWN — The removal of the SLAB allocator (Linux 6.8)](https://lwn.net/Articles/984cd8/)
5. [KernelNewbies — Linux 6.18: slub sheaves（per-CPU sheaves 性能改进）](https://kernelnewbies.org/Linux_6.18)
6. [Lore — SLUB percpu sheaves patch series (V. Babka)](https://lore.kernel.org/lkml/aIJvOLqljFiN_VLR@pc636/T/)
