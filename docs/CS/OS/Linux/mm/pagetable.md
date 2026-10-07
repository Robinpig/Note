## Introduction

前几篇笔记反复出现"建立页表""填 PTE""摘掉 pte 表"这类动作，但**页表本身**一直没有独立讲过。[vm.md](/docs/CS/OS/Linux/mm/vm.md) 讲的是 VMA——"这段虚拟地址是什么性质"的约定；[mmap.md](/docs/CS/OS/Linux/mm/mmap.md) 讲的是如何建立这份约定。而**约定如何被兑现成一次真实的地址翻译**，靠的是页表。

页表是内核维护的一张**多级树**，把虚拟地址逐段拆开做索引，最终落到一个物理页帧。本篇要讲清四件事：

1. **形状**：为什么必须是多级树而不是一张大表；x86-64 的 4 级/5 级布局与各级粒度。
2. **砖块**：一个表项（PTE/PDE/PUD entry）里放了什么位，硬件位与软件位如何共享同一条 64 位。
3. **生命周期**：页表页从哪里来（buddy）、如何构造（`ptdesc` + `pagetable_*_ctor`）、如何被惰性创建（缺页时逐级 alloc）、如何被回收（`free_pgtables` 递归下降）。
4. **一致性**：改了页表为什么必须让 TLB 失效；`mmu_gather` 如何把"摘除 → 失效 → 释放"三步批量拆开；页表页为什么不能用完就 `free_page()`。

本篇是 `mm/` 链路上**最底层的一环**——它不参与"策略"，只提供"翻译"这一基础能力，上层的 VMA、缺页、回收、迁移、KSM、GUP 全部建立在它之上。

> 本篇源码全部对照本机 `v7.2.7` 源码树核实。页表是内核里**跨架构差异最大**的子系统之一（x86/arm64/riscv 的层级数、位布局、flush 方式都不同），本篇以 **x86-64** 为主线，通用部分标出 `include/asm-generic/` 的实现。

## Why It Is Multi-Level

最朴素的方案是一张平铺的映射表：虚拟页号做下标，表项存物理页号。64 位机器上若支持 48 位虚拟地址（4 级页表的常见配置），虚拟页号有 `2^48 / 4096 = 2^36` 个，每项 8 字节：

```
2^36 × 8 B = 2^39 B = 512 GiB
```

**每个进程光页表就要 512 GiB**，而实际上一个进程真正用到的地址空间往往只有几 MB 到几百 MB。平铺表把"虚拟地址空间是稀疏的"这一事实完全忽略掉了。

多级树正是为稀疏性设计的：**把"整段连续下标"换成"按需分叉的指针树"**，只在实际被访问的分支上分配下一级表。一个只用了几 MB 的进程，其页表也只占几页到几十页。

代价是**一次翻译要多次访存**：4 级页表要 4 次内存访问才拿到物理页号（加上访问数据本身共 5 次）。这个代价交给 **TLB** 兜住——TLB 缓存的是最终翻译结果，命中时根本不会去走页表树。所以多级页表能成立的前提是"页表遍历很少真的发生"。

各级的"扇出"取 512（9 位）= `PAGE_SIZE / sizeof(entry) = 4096 / 8`——**一张表恰好占一页**。这是个刻意的设计：页表页可以像普通页一样从 buddy 分配、被换出、被回收，不需要任何特殊机制。

## The Hierarchical Layout of x86-64

4 级页表把 48 位虚拟地址切成 5 段（4 个索引 + 1 个页内偏移）：

| 段 | 位区间 | 宽度 | 索引的表 | 该层一项覆盖 |
|---|---|---|---|---|
| PGD index | [47:39] | 9 | PGD 表 | 512 GiB |
| PUD index | [38:30] | 9 | PUD 表 | 1 GiB |
| PMD index | [29:21] | 9 | PMD 表 | 2 MiB |
| PTE index | [20:12] | 9 | PTE 表 | 4 KiB |
| offset | [11:0] | 12 | — | 1 B |

5 级页表（Intel LA57）在 PGD 之下再插一层 P4D，地址宽度从 48 扩到 57 位：

| 段 | 位区间 | 宽度 | 该层一项覆盖 |
|---|---|---|---|
| PGD index | [56:48] | 9 | 256 TiB |
| P4D index | [47:39] | 9 | 512 GiB |
| PUD index | [38:30] | 9 | 1 GiB |
| PMD index | [29:21] | 9 | 2 MiB |
| PTE index | [20:12] | 9 | 4 KiB |
| offset | [11:0] | 12 | 1 B |

这些常量在 `arch/x86/include/asm/pgtable_64_types.h`：

```c
#define PGDIR_SHIFT	pgdir_shift
#define PTRS_PER_PGD	512

#define P4D_SHIFT		39
#define MAX_PTRS_PER_P4D	512
#define PTRS_PER_P4D		ptrs_per_p4d
#define P4D_SIZE		(_AC(1, UL) << P4D_SHIFT)

#define PUD_SHIFT	30
#define PTRS_PER_PUD	512

#define PMD_SHIFT	21
#define PTRS_PER_PMD	512

#define PTRS_PER_PTE	512
```

**注意 `PGDIR_SHIFT` 与 `PTRS_PER_P4D` 不是字面量，而是变量**——这是五级页表支持带来的直接后果：

```c
/* arch/x86/kernel/head64.c:56 */
unsigned int pgdir_shift __ro_after_init = 39;
unsigned int ptrs_per_p4d __ro_after_init = 1;
```

默认值是"4 级"形态（`pgdir_shift = 39`、`ptrs_per_p4d = 1`，`1` 意味着 P4D 层退化为空转）。检测到 CPU 支持 LA57 且内核开启 `CONFIG_X86_5LEVEL` 时，早启动代码把它们改写为 5 级形态：

```c
/* arch/x86/boot/compressed/pgtable_64.c:128 */
	pgdir_shift = 48;
	ptrs_per_p4d = 512;
```

两者都标了 `__ro_after_init`——**初始化完成后只读**，此后所有翻译路径读到的都是稳定的值，不会在运行期变化。用变量带来的一点间接寻址代价，换来"同一份内核镜像同时支持 4 级与 5 级"。这也是为什么 `PGDIR_SIZE`、`pgd_index()` 这类看起来该是常量的东西在 x86 上都是表达式。

`pgtable_l5_enabled()` 是判断当前形态的统一入口，早期启动用变量，之后用 CPU feature 位：

```c
/* arch/x86/include/asm/pgtable_64_types.h:36 */
#define pgtable_l5_enabled() cpu_feature_enabled(X86_FEATURE_LA57)
```

## Collapse: Non-Existent Levels

如果内核为每个架构都写一遍"4 级怎么走、5 级怎么走"，代码量会爆炸。Linux 的解法是**折叠（folding）**：把不存在的层抽象成"恒等映射"，让上层代码写同一份遍历逻辑。

三个折叠宏在 `include/asm-generic/` 下：

```c
/* include/asm-generic/pgtable-nop4d.h:7 */
#define __PAGETABLE_P4D_FOLDED 1
```

同理还有 `pgtable-nopud.h`、`pgtable-nopmd.h`。当某一层折叠时，`p4d_offset(pgd, addr)` 之类的函数直接返回上级指针——**该层的"表"就是上级的表**，层数在逻辑上减少一层，但代码路径不变。

折叠对代码的影响体现在各处条件定义：

```c
/* arch/x86/include/asm/pgtable.h:67 */
#ifndef __PAGETABLE_P4D_FOLDED
#define set_pgd(pgdp, pgd)		native_set_pgd(pgdp, pgd)
#define pgd_clear(pgd)			(pgtable_l5_enabled() ? native_pgd_clear(pgd) : 0)
#endif
...
#ifndef __PAGETABLE_PUD_FOLDED
#define p4d_clear(p4d)			native_p4d_clear(p4d)
#endif
```

`pgd_clear()` 的写法值得停下来看：**5 级时真的清 pgd 表项，4 级时直接返回 0**。为什么 4 级下不能清？

因为在 4 级形态下，`p4d_offset(pgd, addr)` 返回的就是 `pgd` 本身——PGD 表项和 P4D 表项是**内存中的同一个 64 位字**。而释放路径 `free_pud_range()` 的结尾已经有一步 `p4d_clear(p4d)`，它在 4 级时清掉的就是这个位置。若 `pgd_clear()` 再清一次，就是同一个字被清两遍（虽然无害，但语义混乱）。所以 x86 明确让它退化为 no-op。

x86-64 上三种折叠的实际状态：

| 层 | x86-64 | 说明 |
|---|---|---|
| P4D | **运行时可折叠** | 4 级时 `ptrs_per_p4d = 1`，层退化为空转；`__PAGETABLE_P4D_FOLDED` 在 x86 上**从未定义**（始终按 5 级结构编译），是否使用由 `pgtable_l5_enabled()` 决定 |
| PUD | 不折叠 | 64 位必有 PUD 层（1 GiB 粒度） |
| PMD | 不折叠 | 2 MiB 粒度是 THP 的基础 |

对比 32 位无 PAE 的 x86：只有两级，PUD 与 PMD 都折叠。这解释了为什么通用代码里到处是 `#ifndef __PAGETABLE_*_FOLDED`——**同一份 `mm/memory.c` 要同时服务 2、3、4、5 级页表的架构**。

## What Is Inside an Entry

一个页表项是 64 位，前 12 位是标志位（因为页对齐，低 12 位在物理地址中必然为 0，可以挪用），其余位存物理页帧号。

`arch/x86/include/asm/pgtable_types.h` 里的位分配：

```c
#define _PAGE_BIT_PRESENT	0	/* is present */
#define _PAGE_BIT_RW		1	/* writeable */
#define _PAGE_BIT_USER		2	/* userspace addressable */
#define _PAGE_BIT_PWT		3	/* page write through */
#define _PAGE_BIT_PCD		4	/* page cache disabled */
#define _PAGE_BIT_ACCESSED	5	/* was accessed (raised by CPU) */
#define _PAGE_BIT_DIRTY		6	/* was written to (raised by CPU) */
#define _PAGE_BIT_PSE		7	/* 4 MB (or 2MB) page */
#define _PAGE_BIT_PAT		7	/* on 4KB pages */
#define _PAGE_BIT_GLOBAL	8	/* Global TLB entry PPro+ */
#define _PAGE_BIT_SOFTW1	9	/* available for programmer */
#define _PAGE_BIT_SOFTW2	10	/* " */
#define _PAGE_BIT_SOFTW3	11	/* " */
#define _PAGE_BIT_PAT_LARGE	12	/* On 2MB or 1GB pages */
#define _PAGE_BIT_SOFTW4	57	/* available for programmer */
#define _PAGE_BIT_SOFTW5	58	/* available for programmer */
#define _PAGE_BIT_PKEY_BIT0	59	/* Protection Keys, bit 1/4 */
...
#define _PAGE_BIT_NX		63	/* No execute: only valid after cpuid check */
```

几个必须记住的点：

**bit 7 有两个含义。** `_PAGE_BIT_PSE` 与 `_PAGE_BIT_PAT` 是同一个 bit。在非叶子层（PDE）里它表示"这是一个大页"（Page Size Extension）；在叶子 PTE 里它参与 PAT（页属性表）索引。同一 bit 因层级不同而语义不同——这是硬件规定，不是内核的选择。

**软件位是共享的稀缺资源。** 硬件只定义了上面那些，内核要记的额外状态（soft dirty、userfaultfd 写保护、special 映射……）只能挤进 `SOFTW1`~`SOFTW5`：

```c
#define _PAGE_BIT_SPECIAL	_PAGE_BIT_SOFTW1
#define _PAGE_BIT_CPA_TEST	_PAGE_BIT_SOFTW1
#define _PAGE_BIT_UFFD_WP	_PAGE_BIT_SOFTW2 /* userfaultfd wrprotected */
#define _PAGE_BIT_SOFT_DIRTY	_PAGE_BIT_SOFTW3 /* software dirty tracking */
#define _PAGE_BIT_KERNEL_4K	_PAGE_BIT_SOFTW3 /* page must not be converted to large */

#ifdef CONFIG_X86_64
#define _PAGE_BIT_SAVED_DIRTY	_PAGE_BIT_SOFTW5 /* Saved Dirty bit (leaf) */
#define _PAGE_BIT_NOPTISHADOW	_PAGE_BIT_SOFTW5 /* No PTI shadow (root PGD) */
#else
#define _PAGE_BIT_SAVED_DIRTY	_PAGE_BIT_SOFTW2 /* Saved Dirty bit (leaf) */
#define _PAGE_BIT_NOPTISHADOW	_PAGE_BIT_SOFTW2 /* No PTI shadow (root PGD) */
#endif
```

同一个 bit 可以给多个用途**共用**，条件是它们不会同时出现在同一个表项里。`SOFT_DIRTY` 与 `KERNEL_4K` 共用 bit 11（前者用于用户 PTE，后者约束内核映射不得合并为大页）；`SAVED_DIRTY` 与 `NOPTISHADOW` 共用 bit 58（前者用于叶子 PTE，后者只出现在根 PGD）。这种复用是页表位空间逼出来的精确记账，改动任何一处都要检查全部共存场景。

**PROTNONE 借了 GLOBAL 的位。**

```c
/* If _PAGE_BIT_PRESENT is clear, we use these: */
#define _PAGE_BIT_PROTNONE	_PAGE_BIT_GLOBAL
```

`mprotect(PROT_NONE)` 需要让访问触发缺页，但又要区别于"这个地址没映射"。做法是**把 PRESENT 位清掉**（这样一定会缺页），同时用 bit 8 标记"这不是空洞，是被 PROT_NONE 保护的映射"。bit 8 在 PRESENT=1 时是 GLOBAL（不随 CR3 切换刷新的 TLB 项），在 PRESENT=0 时是 PROTNONE——两个语义永不同时出现。

**"只读但脏"的 PTE：SAVED_DIRTY。** 这是 CET（Control-flow Enforcement）shadow stack 带来的新约束：

```c
/*
 * The hardware requires shadow stack to be Write=0,Dirty=1. However,
 * there are valid cases where the kernel might create read-only PTEs that
 * are dirty (e.g., fork(), mprotect(), uffd-wp(), soft-dirty tracking). In
 * this case, the _PAGE_SAVED_DIRTY bit is used instead of the HW-dirty bit,
 * to avoid creating a wrong "shadow stack" PTEs.
 */
#define _PAGE_SAVED_DIRTY	(_AT(pteval_t, 1) << _PAGE_BIT_SAVED_DIRTY)

#define _PAGE_DIRTY_BITS (_PAGE_DIRTY | _PAGE_SAVED_DIRTY)
```

硬件把 `Write=0, Dirty=1` 这个组合规定为"shadow stack 页"。但内核有很多正当场景需要造出"只读但脏"的 PTE（fork 后写保护、mprotect 收紧、userfaultfd-wp、soft-dirty 追踪）。于是内核改用软件位 `SAVED_DIRTY` 来记脏，硬件 dirty 位留 0——`_PAGE_DIRTY_BITS` 这个"两位置其一的合并视图"就是给上层查询用的。这是一个**硬件语义污染了软件抽象**，再用软件位把语义拿回来的典型例子。

**中间层表项必须可写。** 这一点最容易踩坑：

```c
/*
 * Page tables needs to have Write=1 in order for any lower PTEs to be
 * writable. This includes shadow stack memory (Write=0, Dirty=1)
 */
#define _KERNPG_TABLE_NOENC	 (__PP|__RW|   0|___A|   0|___D|   0|   0)
#define _PAGE_TABLE_NOENC	 (__PP|__RW|_USR|___A|   0|___D|   0|   0)
```

PGD/P4D/PUD/PMD 层指向下一级表的表项**必须置 RW**，否则它下面所有 PTE 都无法可写——硬件在翻译时会沿着路径与权限，任何一层不可写，最终页也就不可写。所以"把某一层设成只读"不能用来实现范围保护。

**swap 与迁移项的位借用。** PTE 的 PRESENT 为 0 时不表示"没映射"，而可能是一个 swap 项、迁移项、device-private 项。这些编码在有限的非存在位里挤：

```c
/*
 * Tracking soft dirty bit when a page goes to a swap is tricky.
 * ... On x86 bits 1-4 are *not* involved into swap entry computation,
 * but bit 7 is used for thp migration, so we borrow bit 1 for soft dirty tracking.
 */
#define _PAGE_SWP_SOFT_DIRTY	_PAGE_RW
#define _PAGE_SWP_UFFD_WP	_PAGE_USER
#define _PAGE_SWP_EXCLUSIVE	_PAGE_PWT
```

bit 1 在 swap 项里表示"该页被换出时是脏的"，而它在别处又表示 RW，所以取用时必须先判 `present == 0`。这套编码与 [Swap](/docs/CS/OS/Linux/Swap.md) 的 `swp_entry_t` 共同构成了非存在 PTE 的完整语义空间。

## Page Table Pages Are Special Pages: ptdesc

页表页本身也是从 buddy 分配的一页，但在内核里的"身份"与普通页不同。早期内核直接复用 `struct page` 的 union 字段描述页表页，代码里到处是"这个 page 其实是页表"的隐含约定。6.4 起引入 `struct ptdesc` 把它显式化：

```c
/*
 * This struct overlays struct page for now. Do not modify without a good
 * understanding of the issues.
 */
struct ptdesc {
	memdesc_flags_t pt_flags;

	union {
		struct rcu_head pt_rcu_head;
		struct list_head pt_list;
		struct {
			unsigned long _pt_pad_1;
			pgtable_t pmd_huge_pte;
		};
	};
	unsigned long __page_mapping;

	union {
		pgoff_t pt_index;
		struct mm_struct *pt_mm;
		atomic_t pt_frag_refcount;
#ifdef CONFIG_HUGETLB_PMD_PAGE_TABLE_SHARING
		atomic_t pt_share_count;
#endif
	};

	union {
		unsigned long _pt_pad_2;
#if ALLOC_SPLIT_PTLOCKS
		spinlock_t *ptl;
#else
		spinlock_t ptl;
#endif
	};
	unsigned int __page_type;
	atomic_t __page_refcount;
#ifdef CONFIG_MEMCG
	unsigned long pt_memcg_data;
#endif
};
```

**它是 `struct page` 的 overlay，不是替代品**——靠一组 `static_assert` 强制逐字段偏移对齐：

```c
#define TABLE_MATCH(pg, pt)						\
	static_assert(offsetof(struct page, pg) == offsetof(struct ptdesc, pt))
TABLE_MATCH(flags, pt_flags);
TABLE_MATCH(compound_info, pt_list);
TABLE_MATCH(mapping, __page_mapping);
TABLE_MATCH(__folio_index, pt_index);
TABLE_MATCH(rcu_head, pt_rcu_head);
...
static_assert(sizeof(struct ptdesc) <= sizeof(struct page));
```

这样做的原因很实际：页表页进了 buddy、进了 LRU 统计、可能被回收，所有这些路径处理的都是 `struct page *`；如果 `ptdesc` 是与 `page` 不同的对象，就得在每条路径上分叉。overlay 让它**零成本转换**：

```c
#define ptdesc_page(pt)		(_Generic((pt),				\
	const struct ptdesc *:		(const struct page *)(pt),	\
	struct ptdesc *:		(struct page *)(pt)))

static inline struct ptdesc *virt_to_ptdesc(const void *x)
{
	return page_ptdesc(virt_to_page(x));
}
```

那个 union 的含义按**页表页所处的生命周期阶段**展开：

| 字段 | 何时有效 |
|---|---|
| `pt_rcu_head` | 页表页被 RCU 延迟释放时挂着 |
| `pt_list` | 在 `pgd_list` 或延迟释放链表上排队时 |
| `pmd_huge_pte` | THP 场景，pmd 下挂的 pte 表指针 |
| `pt_index` | s390 gmap 用 |
| `pt_mm` | x86 的 PGD 页用来记住归属的 mm |
| `pt_frag_refcount` | powerpc 的碎片页表计数 |
| `pt_share_count` | HugeTLB PMD 页表共享计数 |

这正是 overlay 的代价：**同一个 64 位位置在不同阶段表述完全不同的东西**，读错阶段就会得到垃圾。所以 `ptdesc` 的注释写得格外严厉——"没有充分理解这些问题就不要改"。

`pt_flags` 也不是自有位空间，而是**借用 page flags 的位编号**：

```c
/* include/linux/mm.h:3606 */
enum pt_flags {
	PT_kernel = PG_referenced,
	PT_reserved = PG_reserved,
	/* High bits are used for zone/node/section */
};
```

页表页靠 `PT_kernel` 区分"内核页表"与"用户页表"，这个区别在释放路径上导致完全不同的行为（见下节）。

## Allocation and Construction

分配一个页表页就是分配一个复合页，然后把它当作 ptdesc 看：

```c
static inline struct ptdesc *pagetable_alloc_noprof(gfp_t gfp, unsigned int order)
{
	struct page *page = alloc_pages_noprof(gfp | __GFP_COMP, order);

	return page_ptdesc(page);
}
```

`__GFP_COMP` 说明页表页被视为**复合页**——因为构造/析构走的是 folio 接口：

```c
static inline void __pagetable_ctor(struct ptdesc *ptdesc)
{
	struct folio *folio = ptdesc_folio(ptdesc);

	__folio_set_pgtable(folio);
	lruvec_stat_add_folio(folio, NR_PAGETABLE);
}
```

`NR_PAGETABLE` 是关键的一笔账：**所有页表页都计入这个统计**，最终出现在 `/proc/meminfo` 的 `PageTables` 行。排查"内存不知去哪了"时，这一行往往能解释掉相当一部分——尤其是大量 `mmap`/`munmap` 抖动过的长跑进程。

各层的构造器是**分层递进**的，每层在公共部分之上加自己的东西：

| 构造器 | 额外动作 |
|---|---|
| `pagetable_pgd_ctor` / `pagetable_p4d_ctor` / `pagetable_pud_ctor` | 仅 `__pagetable_ctor` |
| `pagetable_pmd_ctor` | `pmd_ptlock_init`（含 `pmd_huge_pte` 初始化）+ `ptdesc_pmd_pts_init`（HugeTLB 共享计数） |
| `pagetable_pte_ctor` | `ptlock_init`（页表锁） |

```c
static inline bool pagetable_pte_ctor(struct mm_struct *mm,
				      struct ptdesc *ptdesc)
{
	if (mm != &init_mm && !ptlock_init(ptdesc))
		return false;
	__pagetable_ctor(ptdesc);
	return true;
}
```

注意 `mm != &init_mm` 这个判断：内核页表（`init_mm`）的 PTE 页不加锁，因为内核地址空间不并发修改用户 PTE。这是页表锁配置的第一处分叉。

### Three Configurations of the Page Table Lock

页表的并发保护不是一件简单的事。`include/linux/mm.h` 里的三档配置：

```c
#if defined(CONFIG_SPLIT_PTE_PTLOCKS)
#if ALLOC_SPLIT_PTLOCKS
static inline spinlock_t *ptlock_ptr(struct ptdesc *ptdesc)
{
	return ptdesc->ptl;              /* 指向动态分配的 spinlock */
}
#else /* ALLOC_SPLIT_PTLOCKS */
static inline spinlock_t *ptlock_ptr(struct ptdesc *ptdesc)
{
	return &ptdesc->ptl;             /* ptdesc 内嵌 spinlock */
}
#endif
#else	/* !defined(CONFIG_SPLIT_PTE_PTLOCKS) */
/* We use mm->page_table_lock to guard all pagetable pages of the mm. */
static inline spinlock_t *pte_lockptr(struct mm_struct *mm, pmd_t *pmd)
{
	return &mm->page_table_lock;     /* 全 mm 一把锁 */
}
#endif
```

| 配置 | 锁粒度 | 代价 |
|---|---|---|
| 无 `SPLIT_PTE_PTLOCKS` | 整个 mm 一把 `page_table_lock` | 所有缺页/回收在页表上串行 |
| `SPLIT_PTE_PTLOCKS` | **每个 PTE 表一把锁** | 锁存在 ptdesc 里 |
| `+ ALLOC_SPLIT_PTLOCKS` | 每个 PTE 表一把锁 | 锁动态分配（`ptlock_alloc`），省 ptdesc 空间但多一次分配 |

从中拿到锁的路径是一条"表项 → 页 → 锁"的反查：

```c
static inline spinlock_t *pte_lockptr(struct mm_struct *mm, pmd_t *pmd)
{
	return ptlock_ptr(page_ptdesc(pmd_page(*pmd)));
}
```

**从 pmd 表项里取出 pte 表页，再从该页的 ptdesc 里取锁**。这就是为什么 `pte_offset_map_lock()` 必须把 `ptl` 一起返回（而不是让调用者事后自己算）——见下节。

split ptlock 是并行缺页性能的关键。没有它，多线程进程的缺页会全部卡在 `mm->page_table_lock` 上。

### Lazy Growth: Building Tables Level by Level on Page Fault

进程启动时页表几乎是空的。**页表是随着地址空间被访问而逐步长出来的**，这个"长"的过程就在缺页路径里：

```c
static vm_fault_t __handle_mm_fault(struct vm_area_struct *vma,
		unsigned long address, unsigned int flags)
{
	...
	pgd = pgd_offset(mm, address);
	p4d = p4d_alloc(mm, pgd, address);
	if (!p4d)
		return VM_FAULT_OOM;

	vmf.pud = pud_alloc(mm, p4d, address);
	if (!vmf.pud)
		return VM_FAULT_OOM;
retry_pud:
	if (pud_none(*vmf.pud) &&
	    thp_vma_allowable_order(vma, vm_flags, TVA_PAGEFAULT, PUD_ORDER)) {
		ret = create_huge_pud(&vmf);
		if (!(ret & VM_FAULT_FALLBACK))
			return ret;
	} else {
		...
	}

	vmf.pmd = pmd_alloc(mm, vmf.pud, address);
	if (!vmf.pmd)
		return VM_FAULT_OOM;

	/* Huge pud page fault raced with pmd_alloc? */
	if (pud_trans_unstable(vmf.pud))
		goto retry_pud;
	...
fallback:
	return handle_pte_fault(&vmf);
}
```

三个要点：

**PGD 不分配，只取指针。** `pgd_offset(mm, address)` 直接算——`mm->pgd` 在进程创建时就分配好了，且永不回收。它必须一直存在，因为进程切换只换 CR3 根指针。

**`*_alloc` 是"需要才建"。** 三层 `p4d_alloc` / `pud_alloc` / `pmd_alloc` 的语义完全一致：

```c
static inline pud_t *pud_alloc(struct mm_struct *mm, p4d_t *p4d,
		unsigned long address)
{
	return (unlikely(p4d_none(*p4d)) && __pud_alloc(mm, p4d, address)) ?
		NULL : pud_offset(p4d, address);
}
```

三段式：**父项为空才走慢路径分配**（`unlikely` 表明绝大多数缺页时该层已存在），分配失败返回 NULL（上层转 `VM_FAULT_OOM`），成功则返回偏移。这个模式在 `p4d_alloc` / `pud_alloc` / `pmd_alloc` 上是逐字重复的。

**`retry_pud` 是 THP 竞争的产物。** `create_huge_pud` 与 `pmd_alloc` 可能并发在同一 pud 项上动作，`pud_trans_unstable()` 检测到中间态就重试整段。

### Race Handling and Write Barriers

真正干活的 `__pud_alloc` 展示了页表分配的标准竞态模式：

```c
int __pud_alloc(struct mm_struct *mm, p4d_t *p4d, unsigned long address)
{
	pud_t *new = pud_alloc_one(mm, address);
	if (!new)
		return -ENOMEM;

	spin_lock(&mm->page_table_lock);
	if (!p4d_present(*p4d)) {
		mm_inc_nr_puds(mm);
		smp_wmb(); /* See comment in pmd_install() */
		p4d_populate(mm, p4d, new);
	} else	/* Another has populated it */
		pud_free(mm, new);
	spin_unlock(&mm->page_table_lock);
	return 0;
}
```

**先在锁外分配，再在锁内检查竞态**——赢了就挂上，输了就把自己多分配的释放掉。这是"乐观分配"的经典写法：把可能睡眠的分配（`pud_alloc_one` 会调 buddy）放在临界区之外，锁内只做几次判断和一次指针写入。

`smp_wmb()` 的位置很关键。它的作用在 `pmd_install()` 的注释里说得很完整：

```c
void pmd_install(struct mm_struct *mm, pmd_t *pmd, pgtable_t *pte)
{
	spinlock_t *ptl = pmd_lock(mm, pmd);

	if (likely(pmd_none(*pmd))) {	/* Has another populated it ? */
		mm_inc_nr_ptes(mm);
		/*
		 * Ensure all pte setup (eg. pte page lock and page clearing) are
		 * visible before the pte is made visible to other CPUs by being
		 * put into page tables.
		 *
		 * The other side of the story is the pointer chasing in the page
		 * table walking code (when walking the page table without locking;
		 * ie. most of the time). Fortunately, these data accesses consist
		 * of a chain of data-dependent loads, meaning most CPUs (alpha
		 * being the notable exception) will already guarantee loads are
		 * seen in-order. See the alpha page table accessors for the
		 * smp_rmb() barriers in page table walking code.
		 */
		smp_wmb(); /* Could be smp_wmb__xxx(before|after)_spin_lock */
		pmd_populate(mm, pmd, *pte);
		*pte = NULL;
	}
	spin_unlock(ptl);
}
```

写侧要说的是：**新表页的初始化（清空、加锁）必须在它被挂进页表树之前对其他 CPU 可见**，否则另一个 CPU 可能通过新挂上的表项读到未初始化的内容。读侧之所以大多不需要屏障，是因为页表遍历是**指针追逐（pointer chasing）**——每次加载的地址依赖上一次加载的结果，这种数据依赖链本身就保证了顺序（alpha 是唯一已知的例外，所以它的实现里显式加了 `smp_rmb()`）。

顺带一个源码内部的不一致：`__p4d_alloc()` 把判断写成了反的——

```c
	if (pgd_present(*pgd)) {	/* Another has populated it */
		p4d_free(mm, new);
	} else {
		smp_wmb(); /* See comment in pmd_install() */
		pgd_populate(mm, pgd, new);
	}
```

语义与 `__pud_alloc`/`__pmd_alloc` 完全等价，只是先写了竞态输的分支。另外它没有 `mm_inc_nr_*` 调用——因为 **`mm_struct` 里根本没有 `nr_p4ds` 计数器**（只有 `nr_ptes` / `nr_pmds` / `nr_puds`）。P4D 层的表数量在 5 级下也很少，不值得单独记账。

### Kernel Page Tables and the PTI Shadow

新进程的 PGD 不是凭空建的，它要从"内核模板"复制内核那一半：

```c
static void pgd_ctor(struct mm_struct *mm, pgd_t *pgd)
{
	/* PAE preallocates all its PMDs.  No cloning needed. */
	if (!IS_ENABLED(CONFIG_X86_PAE))
		clone_pgd_range(pgd + KERNEL_PGD_BOUNDARY,
				swapper_pg_dir + KERNEL_PGD_BOUNDARY,
				KERNEL_PGD_PTRS);

	/* List used to sync kernel mapping updates */
	pgd_set_mm(pgd, mm);
	pgd_list_add(pgd);
}
```

**只复制内核那一半**：`KERNEL_PGD_BOUNDARY` 之上的项来自 `swapper_pg_dir`（内核的模板 PGD），之下（用户空间地址范围）保持空。原因是所有进程共享同一份内核地址空间映射，只有用户部分是各自的。

为什么每个进程都要**各自持有一份内核映射的副本**，而不是共享一个 PGD？因为进程切换只换 CR3 的根指针，整棵页表树跟着根走；如果内核映射只存在于某一个 PGD 里，其他进程一旦进了内核就会缺页。所以内核映射必须在每个进程的 PGD 里都可寻址。

代价是**内核映射变更时需要同步所有进程**，这就是 `pgd_list` 的用途（注释 "List used to sync kernel mapping updates"）：

```c
static inline void pgd_list_add(pgd_t *pgd)
{
	struct ptdesc *ptdesc = virt_to_ptdesc(pgd);

	list_add(&ptdesc->pt_list, &pgd_list);
}
```

注意它用的正是 ptdesc 的 `pt_list` 字段，而归属的 mm 存在 `pt_mm`：

```c
static void pgd_set_mm(pgd_t *pgd, struct mm_struct *mm)
{
	virt_to_ptdesc(pgd)->pt_mm = mm;
}
```

这两个字段就是 ptdesc union 里"x86 的 PGD 专用"的那两个槽位。

PTI（页表隔离，Meltdown 缓解）在这里又叠了一层：用户态执行时 CR3 指向的是**只含用户映射的影子页表**，进入内核才切到完整页表。x86 为此需要给每个进程准备两份顶层结构，并在影子页表里为 per-process 的 LDT 预留单独的 PMD：

```c
/*
 * "USER_PMDS" are the PMDs for the user copy of the page tables when
 * PTI is enabled. They do not exist when PTI is disabled. ...
 * We allocate separate PMDs for the kernel part of the user page-table
 * when PTI is enabled. We need them to map the per-process LDT into the
 * user-space page-table.
 */
```

### Release: Asynchronous Path for Kernel Page Tables

释放是分配的反向操作，但多了一条分叉：

```c
static inline void pagetable_free(struct ptdesc *pt)
{
	if (ptdesc_test_kernel(pt)) {
		ptdesc_clear_kernel(pt);
		pagetable_free_kernel(pt);
	} else {
		__pagetable_free(pt);
	}
}
```

内核页表释放走 `pagetable_free_kernel()`，在开启 `CONFIG_ASYNC_KERNEL_PGTABLE_FREE` 时是**异步**的：

```c
void pagetable_free_kernel(struct ptdesc *pt)
{
	spin_lock(&kernel_pgtable_work.lock);
	list_add(&pt->pt_list, &kernel_pgtable_work.list);
	spin_unlock(&kernel_pgtable_work.lock);

	schedule_work(&kernel_pgtable_work.work);
}
```

工作线程在真正释放前还要先做一次 IOMMU 侧的失效：

```c
static void kernel_pgtable_work_func(struct work_struct *work)
{
	...
	iommu_sva_invalidate_kva_range(PAGE_OFFSET, TLB_FLUSH_ALL);
	list_for_each_entry_safe(pt, next, &page_list, pt_list)
		__pagetable_free(pt);
}
```

这与 SVA（Shared Virtual Addressing）有关：设备可以拿到与 CPU 相同的虚拟地址空间视图，其 IOMMU 侧也有翻译缓存。内核页表被释放时，必须确保设备侧的翻译也失效。把这件事从同步路径挪到 workqueue，是为了不把 IOMMU 的失效延迟压在调用者身上。

## Traversal and Concurrency

### Pure Arithmetic Offsets

前三层的遍历就是加法与掩码，没有任何内存访问：

```c
pgd = pgd_offset(mm, address);          /* 从 mm->pgd 取 */
p4d = p4d_offset(pgd, address);
pud = pud_offset(p4d, address);
pmd = pmd_offset(pud, address);
```

每一级都是"取表项里的物理地址 → 转成内核虚拟地址 → 加上本层索引"。直到最后一级才有真正的"页表页遍历"语义。

### The pte_offset_map Family: Semantics Changed after v6.11

拿到 pmd 之后访问 PTE 表，是页表并发里最微妙的一步。现代内核的接口不是"算个指针"，而是一个**可能失败的映射操作**：

```c
pte_t *__pte_offset_map(pmd_t *pmd, unsigned long addr, pmd_t *pmdvalp)
{
	unsigned long irqflags;
	pmd_t pmdval;

	rcu_read_lock();
	irqflags = pmdp_get_lockless_start();
	pmdval = pmdp_get_lockless(pmd);
	pmdp_get_lockless_end(irqflags);

	if (pmdvalp)
		*pmdvalp = pmdval;
	if (unlikely(pmd_none(pmdval) || !pmd_present(pmdval)))
		goto nomap;
	if (unlikely(pmd_trans_huge(pmdval)))
		goto nomap;
	if (unlikely(pmd_bad(pmdval))) {
		pmd_clear_bad(pmd);
		goto nomap;
	}
	return __pte_map(&pmdval, addr);
nomap:
	rcu_read_unlock();
	return NULL;
}
```

三个失败条件是关键：

- `pmd_none` / `!pmd_present`：这张 pte 表刚被撤掉；
- `pmd_trans_huge`：该 pmd 项已经**变成一个大页**（THP），下面根本没有 pte 表；
- `pmd_bad`：表项内容非法（通常是内核 bug 或内存损坏），报告并清掉。

**失败路径会 `rcu_read_unlock()` 并返回 NULL；成功路径不解锁**，解锁责任交给后面的 `pte_unmap()`。所以调用者必须处理 NULL——这在 v6.11 之前是不需要的（那时 `pte_offset_map()` 只是指针算术，永不失败）。现代内核里看到 `if (!pte) return;` 这类判断，都是这次语义变更留下的印记。

持 RCU 读锁的意义在注释里说清了：

```c
 * ... But it does take rcu_read_lock(): so
 * that even when page table is racily removed, it remains a valid though empty
 * and disconnected table.  Until pte_unmap(pte) unmaps and rcu_read_unlock()s
 * afterwards.
```

**即使页表被并发摘除，在 RCU 临界区内它仍然是一张有效（虽已清空、已脱离）的表**。这能成立的前提正是页表页的释放也是 RCU 延迟的（见下节），两者配对才构成完整的无锁读协议。

那个 `pmdp_get_lockless_start/end` 是包在 `CONFIG_GUP_GET_PXX_LOW_HIGH` 下的：

```c
static unsigned long pmdp_get_lockless_start(void)
{
	unsigned long irqflags;
	local_irq_save(irqflags);
	return irqflags;
}
```

它关中断的原因在注释里：某些配置下 pmd 分高低两半读，屏障无法保证两次读来自同一个版本；但**关中断能阻止其间的 TLB flush**，从而保证匹配。这又是"用关中断换取读一致性"的老手法，与 GUP-fast 的做法同源。

### Locked Version and Retry

需要修改 PTE 的路径用带锁版本：

```c
pte_t *pte_offset_map_lock(struct mm_struct *mm, pmd_t *pmd,
			   unsigned long addr, spinlock_t **ptlp)
{
	spinlock_t *ptl;
	pmd_t pmdval;
	pte_t *pte;
again:
	pte = __pte_offset_map(pmd, addr, &pmdval);
	if (unlikely(!pte))
		return pte;
	ptl = pte_lockptr(mm, &pmdval);
	spin_lock(ptl);
	if (likely(pmd_same(pmdval, pmdp_get_lockless(pmd)))) {
		*ptlp = ptl;
		return pte;
	}
	pte_unmap_unlock(pte, ptl);
	goto again;
}
```

**`again:` 循环是必须的**：从映射到拿到锁之间存在窗口，期间页表可能被撤掉或替换为大页。所以拿锁之后必须重新读 pmd 与之前保存的 `pmdval` 比对，不一致就解锁重来。

两个 `_nolock` 变体是为 **per-VMA lock** 准备的：

```c
pte_t *pte_offset_map_ro_nolock(struct mm_struct *mm, pmd_t *pmd,
				unsigned long addr, spinlock_t **ptlp);
pte_t *pte_offset_map_rw_nolock(struct mm_struct *mm, pmd_t *pmd,
				unsigned long addr, pmd_t *pmdvalp,
				spinlock_t **ptlp);
```

语义差别在源码注释里写得很细，值得完整记住：

| 接口 | 返回 | 是否加锁 | 适用场景 |
|---|---|---|---|
| `pte_offset_map` | pte 指针 | 否（持 RCU） | **只读**且不需要稳定快照 |
| `pte_offset_map_lock` | pte + ptl | **加锁**，带 `again` 重试 | 常规读写，锁由 mm 语义保护 |
| `pte_offset_map_ro_nolock` | pte + ptl 指针 | **不加锁** | 调用者已持 VMA 读锁，且只读 |
| `pte_offset_map_rw_nolock` | pte + pmdval + ptl | **不加锁** | 调用者已持 VMA 锁，且会写 |

`ro_nolock` 存在的理由很实际：

```c
 * ... This helps
 * the caller to avoid a later pte_lockptr(mm, *pmd), which might by that time
 * act on a changed *pmd: pte_offset_map_ro_nolock() provides the correct spinlock
 * pointer for the page table that it returns.
```

**如果让调用者稍后自己算 `pte_lockptr(mm, *pmd)`，那时的 pmd 可能已经变了**，算出来的是另一张表的锁。所以必须在映射成功的那一刻就把正确的锁指针交出来。

`rw_nolock` 多返回一个 `pmdval`，因为写操作前必须自证稳定：

```c
 * But the users should make sure the page table is stable like checking pte_same()
 * or checking pmd_same() by using the output pmdval before performing the write
 * operations.
```

最后一条注释是最该记住的一句警告：

```c
 * Note that free_pgtables(), used after unmapping detached vmas, or when
 * exiting the whole mm, does not take page table lock before freeing a page
 * table, and may not use RCU at all: "outsiders" like khugepaged should avoid
 * pte_offset_map() and co once the vma is detached from mm or mm_users is zero.
```

`free_pgtables()` **不拿页表锁就释放页表**，也可能完全不用 RCU。所以像 khugepaged 这样的"局外人"，在 VMA 已经从 mm 摘除、或 `mm_users` 已归零之后，**绝对不能**再用 `pte_offset_map()` 系列去碰它。

## Releasing Page Tables: Recursive Descent

页表的释放是一条自顶向下的递归链：

```
free_pgtables()  →  free_pgd_range()  →  free_p4d_range()
                 →  free_pud_range()  →  free_pmd_range()  →  free_pte_range()
```

最底层最直白：

```c
static void free_pte_range(struct mmu_gather *tlb, pmd_t *pmd,
			   unsigned long addr)
{
	pgtable_t token = pmd_pgtable(*pmd);
	pmd_clear(pmd);
	pte_free_tlb(tlb, token, addr);
	mm_dec_nr_ptes(tlb->mm);
}
```

**先 `pmd_clear()` 摘除表项，再 `pte_free_tlb()` 把页交出去**——注意它不是 `free_page()`。这个顺序不能反，也不能立即释放，原因在下一节。上一层的 `free_pmd_range()` 同理（`pud_clear` → `pmd_free_tlb` → `mm_dec_nr_pmds`）。

每一层的最后都有一个"是否该回收这一层表"的判断，靠 `floor` / `ceiling` 与向下取整：

```c
	start = addr;
	pmd = pmd_offset(pud, addr);
	do {
		...
	} while (pmd++, addr = next, addr != end);

	start &= PUD_MASK;
	if (start < floor)
		return;
	if (ceiling) {
		ceiling &= PUD_MASK;
		if (!ceiling)
			return;
	}
	if (end - 1 > ceiling - 1)
		return;

	pmd = pmd_offset(pud, start);
	pud_clear(pud);
	pmd_free_tlb(tlb, pmd, start);
	mm_dec_nr_pmds(tlb->mm);
```

含义是：**把本次要释放的地址范围向下对齐到本层粒度后，如果它还没越过 floor、也没超出 ceiling，说明这一层表里没有别的 VMA 还在用，可以整层回收**。

`floor` / `ceiling` 是相邻 VMA 的边界（`prev->vm_end` 与 `next->vm_start`）。这段逻辑源码作者专门写了长注释"给我们带来过很多痛苦"：

```c
	/*
	 * Why all these "- 1"s?  Because 0 represents both the bottom
	 * of the address space and the top of it (using -1 for the
	 * top wouldn't help much: the masks would do the wrong thing).
	 * The rule is that addr 0 and floor 0 refer to the bottom of
	 * the address space, but end 0 and ceiling 0 refer to the top
	 * ...
	 */
```

`0` 在地址空间里既是"最底"（`addr`/`floor`）又是"最顶"（`end`/`ceiling` 用 0 表示 2^64），所以比较一律要用 `end - 1` / `ceiling - 1`。

### Entry: The New Signature of free_pgtables

v7.2.7 的入口签名与老版本完全不同：

```c
void free_pgtables(struct mmu_gather *tlb, struct unmap_desc *unmap)
{
	struct unlink_vma_file_batch vb;
	struct ma_state *mas = unmap->mas;
	struct vm_area_struct *vma = unmap->first;
	...
	tlb_free_vmas(tlb);

	do {
		unsigned long addr = vma->vm_start;
		struct vm_area_struct *next;

		next = mas_find(mas, unmap->tree_end - 1);

		/*
		 * Hide vma from rmap and truncate_pagecache before freeing
		 * pgtables
		 */
		if (unmap->mm_wr_locked)
			vma_start_write(vma);
		unlink_anon_vmas(vma);
		...
		free_pgd_range(tlb, addr, vma->vm_end, unmap->pg_start,
			       next ? next->vm_start : unmap->pg_end);
		vma = next;
	} while (vma);
}
```

三处都是近期内核的成果：

- 参数从 `(tlb, vma, floor, ceiling)` 变成 `struct unmap_desc *`——把"这次 unmap 的上下文"打包成一个结构；
- 用 **`mas_find()` 遍历 VMA**——maple tree 的游标接口，见 [maple_tree.md](/docs/CS/OS/Linux/mm/maple_tree.md)；
- 用 **`vma_start_write(vma)`** 拿 per-VMA 写锁，而不是老的 `mmap_lock`。

`unlink_anon_vmas()` 的调用位置也有讲究，注释写明：**在释放页表之前必须先把 VMA 从 rmap 和 truncate 路径上摘除**，否则回收器可能通过 rmap 找到一张正在被拆的 VMA。

## mmu_gather: Batch TLB Invalidation

### Core Invariants

页表改完，TLB 里的旧翻译就成了谎言。但"改一个 PTE 立刻刷一次 TLB"是不可行的——一次 `munmap` 可能撤销几十万个页，每个都发一条 IPI 会让系统瘫痪。

`include/asm-generic/tlb.h` 开头把整件事的目标说清了：

```c
/*
 * The mmu_gather data structure is used by the mm code to implement the
 * correct and efficient ordering of freeing pages and TLB invalidations.
 *
 * This correct ordering is:
 *
 *  1) unhook page
 *  2) TLB invalidate page
 *  3) free page
 *
 * That is, we must never free a page before we have ensured there are no live
 * translations left to it. Otherwise it might be possible to observe (or
 * worse, change) the page content after it has been reused.
 */
```

**① 摘除（改页表）→ ② 使 TLB 失效 → ③ 才能释放页**。第三步的紧迫性在于：页一旦回到 buddy 被重新分配，任何残留的 TLB 项都意味着**一个进程能读到、甚至写到别人的数据**。

`mmu_gather` 就是把这三步**在时间上拉开、在空间上批量**的载体。

### Structure

```c
struct mmu_gather {
	struct mm_struct	*mm;

#ifdef CONFIG_MMU_GATHER_TABLE_FREE
	struct mmu_table_batch	*batch;
#endif

	unsigned long		start;
	unsigned long		end;
	unsigned int		fullmm : 1;
	unsigned int		need_flush_all : 1;
	unsigned int		freed_tables : 1;
	unsigned int		delayed_rmap : 1;
	unsigned int		cleared_ptes : 1;
	unsigned int		cleared_pmds : 1;
	unsigned int		cleared_puds : 1;
	unsigned int		cleared_p4ds : 1;
	unsigned int		vma_exec : 1;
	unsigned int		vma_huge : 1;
	unsigned int		vma_pfn  : 1;
	unsigned int		unshared_tables : 1;
	unsigned int		fully_unshared_tables : 1;

	unsigned int		batch_count;

#ifndef CONFIG_MMU_GATHER_NO_GATHER
	struct mmu_gather_batch *active;
	struct mmu_gather_batch	local;
	struct page		*__pages[MMU_GATHER_BUNDLE];
	...
#endif
};
```

`start` / `end` 累积"这次要刷的地址范围"，**把离散的页合并成尽量少的连续区间**。`cleared_ptes` 等四个位记录"在哪些层级清过表项"，它们决定刷新的最小粒度：

```c
static inline unsigned long tlb_get_unmap_shift(struct mmu_gather *tlb)
{
	if (tlb->cleared_ptes)
		return PAGE_SHIFT;
	if (tlb->cleared_pmds)
		return PMD_SHIFT;
	if (tlb->cleared_puds)
		return PUD_SHIFT;
	if (tlb->cleared_p4ds)
		return P4D_SHIFT;

	return PAGE_SHIFT;
}
```

这不只是优化。有些架构（arm64）的 TLB 失效指令**必须指定层级**，且"刷 4K"与"刷 2M"是不同的指令。若只清了 pmd 项却按 PAGE 粒度去刷，某些硬件的翻译缓存不会失效。x86 不需要这种精确性，但通用代码必须为所有架构负责。

### Batching and Two Upper Bounds

页释放也批量化。指针数组就地放在结构里，用一段"借用后续空间"的技巧：

```c
struct mmu_gather_batch {
	struct mmu_gather_batch	*next;
	unsigned int		nr;
	unsigned int		max;
	struct encoded_page	*encoded_pages[];
};

#define MAX_GATHER_BATCH	\
	((PAGE_SIZE - sizeof(struct mmu_gather_batch)) / sizeof(void *))
```

`local` 是内嵌的 batch，`max` 设为 `ARRAY_SIZE(tlb->__pages)` = `MMU_GATHER_BUNDLE` = 8——**先用手上这 8 个槽，装满了才去申请一整页做批**（`tlb_next_batch()` 里的 `__get_free_page(GFP_NOWAIT)`）。这样小规模 unmap 完全不产生额外内存分配。

两处上限都值得注意：

```c
#define MAX_GATHER_BATCH_COUNT	(10000UL/MAX_GATHER_BATCH)
```

```c
	if (tlb->batch_count == MAX_GATHER_BATCH_COUNT)
		return false;
```

它是"**单次 gather 最多攒的批数**"，换算下来相当于限制一次释放约 10000 个页。注释说明了动机：

```c
/*
 * Limit the maximum number of mmu_gather batches to reduce a risk of soft
 * lockups for non-preemptible kernels on huge machines when a lot of memory
 * is zapped during unmapping.
 * 10K pages freed at once should be safe even without a preemption point.
 */
```

非抢占内核上，一次性释放过多页会导致 soft lockup。这个上限与 `__tlb_batch_free_encoded_pages()` 里每 512 个 folio 一次的 `cond_resched()` 一起，保证长 unmap 不会独占 CPU。

页指针还用低位编码塞了标志：

```c
	bool __tlb_remove_folio_pages(struct mmu_gather *tlb, struct page *page,
			unsigned int nr_pages, bool delay_rmap);
```

`encode_page(page, flags)` / `encoded_page_flags()` / `encode_nr_pages()`——因为 `struct page` 指针天然对齐，低位空闲，正好用来记 `ENCODED_PAGE_BIT_DELAY_RMAP` 和"后面还跟一个 nr_pages 项"。这与 [list.md](/docs/CS/OS/Linux/struct/list.md) 里 `hlist` 借用低位的思路同源：**在指针里抠位**是不增加任何存储的元数据方案。

### Hierarchical Correspondence of the Four-Level Free Macros

下面这组宏最容易记错对应关系：

```c
#ifndef pte_free_tlb
#define pte_free_tlb(tlb, ptep, address)			\
	do {							\
		tlb_flush_pmd_range(tlb, address, PAGE_SIZE);	\
		tlb->freed_tables = 1;				\
		__pte_free_tlb(tlb, ptep, address);		\
	} while (0)
#endif

#ifndef pmd_free_tlb
#define pmd_free_tlb(tlb, pmdp, address)			\
	do {							\
		tlb_flush_pud_range(tlb, address, PAGE_SIZE);	\
		tlb->freed_tables = 1;				\
		__pmd_free_tlb(tlb, pmdp, address);		\
	} while (0)
#endif
```

**释放 PTE 表要刷 PMD 范围，释放 PMD 表要刷 PUD 范围**——因为一级表的失效由它的**父层表项**决定：

| 释放的表 | 刷新的范围调用 | 理由 |
|---|---|---|
| PTE 表 | `tlb_flush_pmd_range` | 对应 pmd 项（父层） |
| PMD 表 | `tlb_flush_pud_range` | 对应 pud 项 |
| PUD 表 | `tlb_flush_p4d_range` | 对应 p4d 项 |
| P4D 表 | `__tlb_adjust_range` | 对应 pgd 项 |

三个宏都会置 `tlb->freed_tables = 1`，它让 `tlb_flush_mmu_tlbonly()` 知道"有表结构被拆了，必须真刷"，也是 `tlb_finish_mmu()` 里触发全量刷新的条件之一。

### Lifecycle

```c
tlb_gather_mmu(tlb, mm)        /* 或 fullmm 版本 / vma 版本 */
  ↓  tlb_start_vma / tlb_end_vma（标记 VMA 边界）
  ↓  tlb_remove_tlb_entry(s)     记录 TLB 失效范围
  ↓  tlb_remove_page / __tlb_remove_folio_pages   排队释放页
  ↓  tlb_remove_table                             排队释放页表页
tlb_finish_mmu(tlb)            /* 最后一次 flush + 释放全部排队对象 */
```

初始化时有一个容易被忽略的动作：

```c
static void __tlb_gather_mmu(struct mmu_gather *tlb, struct mm_struct *mm, bool fullmm)
{
	...
	inc_tlb_flush_pending(tlb->mm);
}
```

`inc_tlb_flush_pending` 的配对位置在 `tlb_finish_mmu()`。这个计数器的用途：**GUP-fast 等无锁遍历者可以据此判断"这个 mm 是否有未完成的 TLB 失效"**，从而决定是否需要退避。

`fullmm` 是整 mm 销毁（`exit` / `execve`）时的优化开关：

```c
/**
 * tlb_gather_mmu_fullmm - initialize an mmu_gather structure for page-table tear-down
 * ...
 * In this case, @mm is without users and we're going to destroy the
 * full address space (exit/execve).
 */
```

既然整个地址空间都要拆，就不用维护精确范围了——`__tlb_reset_range()` 里 `tlb->start = tlb->end = ~0`，`tlb_start_vma()` / `tlb_end_vma()` 直接返回，最后刷一次全 TLB 即可。用 ASID 的（RISC）架构甚至可以**只换个 ASID 就作废全部翻译**，连刷都不用：

```c
 *    - (RISC) architectures that use ASIDs can cycle to a new ASID
 *      and delay the invalidation until ASID space runs out.
```

这是 fullmm 优化最大的收益点。

收尾时还有一道针对并发的处理：

```c
void tlb_finish_mmu(struct mmu_gather *tlb)
{
	VM_WARN_ON_ONCE(tlb->fully_unshared_tables);

	/*
	 * If there are parallel threads are doing PTE changes on same range
	 * under non-exclusive lock (e.g., mmap_lock read-side) but defer TLB
	 * flush by batching, one thread may end up seeing inconsistent PTEs
	 * and result in having stale TLB entries.  So flush TLB forcefully
	 * if we detect parallel PTE batching threads.
	 * ...
	 */
	if (mm_tlb_flush_nested(tlb->mm)) {
		tlb->fullmm = 1;
		__tlb_reset_range(tlb);
		tlb->freed_tables = 1;
	}

	tlb_flush_mmu(tlb);
	...
	dec_tlb_flush_pending(tlb->mm);
}
```

`mm_tlb_flush_nested()` 检测到**有别的线程也在做批处理式的 PTE 修改**时，直接升级为 fullmm 全量刷。原因是两个线程各自攒批、各自延迟失效，交错起来可能让对方的失效被"吞掉"，宁可暴力刷一遍。

## Deferred Release of Page Table Pages

页表页不能用完就 `free_page()`，这是与普通页最本质的区别。原因在注释里：

```c
/*
 * Semi RCU freeing of the page directories.
 *
 * This is needed by some architectures to implement software pagetable walkers.
 *
 * gup_fast() and other software pagetable walkers do a lockless page-table
 * walk and therefore needs some synchronization with the freeing of the page
 * directories. The chosen means to accomplish that is by disabling IRQs over
 * the walk.
 *
 * Architectures that use IPIs to flush TLBs will then automagically DTRT,
 * since we unlink the page, flush TLBs, free the page. Since the disabling of
 * IRQs delays the completion of the TLB flush we can never observe an already
 * freed page.
 *
 * Not all systems IPI every CPU for this purpose:
 *
 * - Some architectures have HW support for cross-CPU synchronisation of TLB
 *   flushes, so there's no IPI at all.
 *
 * - Paravirt guests can do this TLB flushing in the hypervisor, or coordinate
 *   with the hypervisor to defer flushing on preempted vCPUs.
 *
 * Such systems need to delay the freeing by some other means, this is that
 * means.
 *
 * What we do is batch the freed directory pages (tables) and RCU free them.
 * We use the sched RCU variant, as that guarantees that IRQ/preempt disabling
 * holds off grace periods.
 */
```

逻辑链条是：

1. **[GUP-fast](/docs/CS/OS/Linux/mm/gup.md?id=fast-path-disabling-interrupts-lockless-page-table-walk) 之类的软件遍历器是无锁的**，只靠"遍历期间关中断"防身（见前文 `pmdp_get_lockless_start`）；
2. 靠 IPI 做 TLB 失效的架构上，"摘除 → 刷 TLB → 释放"的顺序**天然**与关中断的遍历者同步——因为关中断会推迟 TLB flush 的完成，遍历者不可能看到已释放的页；
3. 但**不用 IPI 的架构**（硬件跨 CPU 同步、或半虚拟化交给 hypervisor）没有这个副作用，必须显式延迟释放；
4. 手段就是**批量 + `call_rcu`**，选用 sched RCU 变体，因为"关中断/关抢占同时也阻塞了 RCU 宽限期"。

对应的实现：

```c
void tlb_remove_table(struct mmu_gather *tlb, void *table)
{
	struct mmu_table_batch **batch = &tlb->batch;

	if (*batch == NULL) {
		*batch = (struct mmu_table_batch *)__get_free_page(GFP_NOWAIT);
		if (*batch == NULL) {
			tlb_table_invalidate(tlb);
			tlb_remove_table_one(table);
			return;
		}
		(*batch)->nr = 0;
	}

	(*batch)->tables[(*batch)->nr++] = table;
	if ((*batch)->nr == MAX_TABLE_BATCH)
		tlb_table_flush(tlb);
}
```

注意那个**降级路径**：批的存储本身也要申请一页，而这段代码"深陷在 mm 里，很容易在内存压力下失败"。为了保证前向进展，申请失败时退化为**单表释放**（`tlb_remove_table_one`），而不是报错返回。这与 [mempool.md](/docs/CS/OS/Linux/mm/mempool.md) 的"预留担保保证前向进展"是同一种设计哲学——**内核里"绝不失败"的路径必须显式安排降级**。

v7.2.7 在这里新增了一个接口：

```c
/**
 * tlb_remove_table_sync_rcu - synchronize with software page-table walkers
 *
 * Like tlb_remove_table_sync_one() but uses RCU grace period instead of IPI
 * broadcast. Use in slow paths where sleeping is acceptable.
 * ...
 * Do not use for freeing memory. Use RCU callbacks instead to avoid latency
 * spikes.
 */
void tlb_remove_table_sync_rcu(void)
{
	synchronize_rcu();
}
```

老接口 `tlb_remove_table_sync_one()` 是 `smp_call_function()` 向所有 CPU 广播一个空 IPI——达到同步目的，代价是打断全部 CPU。新接口用 `synchronize_rcu()` 达到同样效果（因为关中断本身就是 RCU 读侧临界区），**只适用于可以睡眠的慢路径**。注释最后一句是使用约束：**不要用它来释放内存**，那应该走 RCU 回调，否则会制造延迟尖峰。

还有两处配置相关：

```c
#ifdef CONFIG_PT_RECLAIM
static inline void __tlb_remove_table_one_rcu(struct rcu_head *head)
{
	struct ptdesc *ptdesc;

	ptdesc = container_of(head, struct ptdesc, pt_rcu_head);
	__tlb_remove_table(ptdesc);
}
```

`ptdesc->pt_rcu_head` 正是前文 union 里那个 `pt_rcu_head` 槽位——页表页被 RCU 延迟时，链表头就存在这里。THP 场景另有一条独立路径：

```c
void pte_free_defer(struct mm_struct *mm, pgtable_t pgtable)
{
	struct page *page;

	page = pgtable;
	call_rcu(&page->rcu_head, pte_free_now);
}
```

## TLB and Shootdown

TLB 是 MMU 内部的一张缓存表，缓存"虚拟页号 → 物理页帧 + 权限"的最近翻译结果。一次翻译命中 TLB 时，MMU **根本不读页表**——这意味着**改了页表但没刷 TLB，新的翻译不会生效**。

失效的粒度从粗到细：

| 手段 | 范围 | 代价 |
|---|---|---|
| CR3 重载 | 全 TLB | 最贵，但一次搞定 |
| `INVLPG` | 单个地址 | 便宜，但每页一条 |
| `INVPCID` | 按 PCID 选择 | 现代方案，可指定地址或全集 |

**跨 CPU 的失效必须靠 IPI**（shootdown）：本 CPU 改了页表，其他 CPU 的 TLB 里可能还留着旧项，必须让它们各自失效。这是 `mmu_gather` 攒批的根本动机——**一次 IPI 的开销是微秒级，而一次 `munmap` 可能涉及十万个页**，逐页 IPI 与批量 IPI 差着好几个数量级。

批量的做法是累积一个地址范围（`tlb->start` / `tlb->end`），最后一次性 `flush_tlb_range()`。范围有可能大于实际改动的页（中间有空洞），这是**用一点多余的失效换取 IPI 次数的大幅下降**。`tlb_end_vma()` 在 VMA 边界主动刷一次，就是为了避免范围跨越 VMA 之间的大空洞而过份膨胀：

```c
static inline void tlb_end_vma(struct mmu_gather *tlb, struct vm_area_struct *vma)
{
	if (tlb->fullmm || IS_ENABLED(CONFIG_MMU_GATHER_MERGE_VMAS))
		return;

	/*
	 * Do a TLB flush and reset the range at VMA boundaries; this avoids
	 * the ranges growing with the unused space between consecutive VMAs,
	 * but also the mmu_gather::vma_* flags from tlb_start_vma() rely on
	 * this.
	 */
	tlb_flush_mmu_tlbonly(tlb);
}
```

`tlb_start_vma()` 还要顺手记下 VMA 的两个属性，因为它们影响刷新的正确性：

```c
	tlb->vma_huge = is_vm_hugetlb_page(vma);
	tlb->vma_exec = !!(vma->vm_flags & VM_EXEC);
	...
	tlb->vma_pfn |= !!(vma->vm_flags & (VM_PFNMAP|VM_MIXEDMAP));
```

`vma_exec` 有 VMA 需要刷指令 TLB（I-TLB 与 D-TLB 在部分架构上是分开的）；`vma_huge` 用于只刷大页的实现；`vma_pfn` 更微妙，它关系到一条真实的竞态：

```c
/*
 * Specifically() there is a race between munmap() and
 * unmap_mapping_range(), where munmap() will unlink the VMA, such
 * that unmap_mapping_range() will no longer observe the VMA and
 * no-op, without observing the TLBI, returning prematurely.
 */
```

`VM_PFNMAP` / `VM_MIXEDMAP`（直接映射设备内存或原始 PFN 的 VMA）没有页帧可追踪，`munmap` 与 `unmap_mapping_range` 之间可能出现"TLBI 尚未生效但 VMA 已摘除"的窗口，导致后者提前返回。所以对这类 VMA，`tlb_free_vmas()` 会在 unlink 前**强制先刷一遍**。

## delayed_rmap: Ordering between TLB and rmap

这是 v7.2.7 里一个精妙的顺序约束。回看前文 zap 路径的五步，其中第四步在有条件时会被**推迟**：

```c
static __always_inline void zap_present_folio_ptes(...)
{
	...
	if (!folio_test_anon(folio)) {
		ptent = get_and_clear_full_ptes(mm, addr, pte, nr, tlb->fullmm);
		if (pte_dirty(ptent)) {
			folio_mark_dirty(folio);
			if (tlb_delay_rmap(tlb)) {
				delay_rmap = true;
				*force_flush = true;
			}
		}
		...
	}
	...
	tlb_remove_tlb_entries(tlb, pte, nr, addr);
	...
	if (!delay_rmap) {
		folio_remove_rmap_ptes(folio, page, nr, vma);

		if (unlikely(folio_mapcount(folio) < 0))
			print_bad_pte(vma, addr, ptent, page);
	}
	if (unlikely(__tlb_remove_folio_pages(tlb, page, nr, delay_rmap))) {
		*force_flush = true;
		*force_break = true;
	}
}
```

触发条件是 **`!folio_test_anon` 且 `pte_dirty`**——即"文件页且被写过"。此时 `folio_mark_dirty()` 之后不能立刻移除 rmap，因为**别的 CPU 的 TLB 里可能还有这个页的可写翻译**；若先摘 rmap 再刷 TLB，中间窗口里那个 CPU 仍能写入，而内核已经认为该页不再被映射。

所以把 rmap 移除挂到 `tlb->delayed_rmap` 上，等 TLB 刷完再做：

```c
void tlb_flush_rmaps(struct mmu_gather *tlb, struct vm_area_struct *vma)
{
	if (!tlb->delayed_rmap)
		return;

	tlb_flush_rmap_batch(&tlb->local, vma);
	if (tlb->active != &tlb->local)
		tlb_flush_rmap_batch(tlb->active, vma);
	tlb->delayed_rmap = 0;
}
```

调用点严格在 `pte_unmap_unlock()` **之前**：

```c
	/* Do the actual TLB flush before dropping ptl */
	if (force_flush) {
		tlb_flush_mmu_tlbonly(tlb);
		tlb_flush_rmaps(tlb, vma);
	}
	pte_unmap_unlock(start_pte, ptl);
```

**必须在持页表锁期间完成刷 TLB + 补 rmap**，否则锁一放，别的线程就可能拿到这张表做别的事。注释一句 "Do the actual TLB flush before dropping ptl" 就是这个意思。

`delayed_rmap` 只在该配置下存在，其余情况退化为 no-op：

```c
/*
 * We have a no-op version of the rmap removal that doesn't
 * delay anything. That is used on S390, which flushes remote
 * TLBs synchronously, and on UP, which doesn't have any
 * remote TLBs to flush and is not preemptible due to this
 * all happening under the page table lock.
 */
```

S390 同步刷远端 TLB、UP 根本没有远端 TLB——两者都不存在那个窗口，所以不需要延迟。

顺带看同一函数里的批量优化：大 folio 的连续 PTE 一次处理完，

```c
	if (unlikely(folio_test_large(folio) && max_nr != 1)) {
		nr = folio_pte_batch(folio, pte, ptent, max_nr);
		zap_present_folio_ptes(tlb, vma, folio, page, pte, ptent, nr, ...);
		return nr;
	}
	zap_present_folio_ptes(tlb, vma, folio, page, pte, ptent, 1, ...);
```

**小 folio 走单页路径、大 folio 走批量路径**，注释说明这是为了让"小 folio 这个最常见情况尽可能快"。`folio_pte_batch()` 检查连续的 PTE 是否属于同一个大 folio 且属性一致，是带 `max_nr` 上限的保守扫描。

## Page Table Reclaim

长跑进程有一个隐蔽的泄漏：反复 `mmap`/`munmap` 会把页表页堆起来。每一次新的映射可能触发新的 PTE 表分配，而 munmap 释放时若地址范围不满足"整层无其他 VMA"的条件，那一层表就留着了。空表本身不占多少，但数量会累积。

`CONFIG_PT_RECLAIM` 让 zap 路径有机会顺手回收空表：

```c
static bool pte_table_reclaim_possible(unsigned long start, unsigned long end,
		struct zap_details *details)
{
	if (!IS_ENABLED(CONFIG_PT_RECLAIM))
		return false;
	/* Only zap if we are allowed to and cover the full page table. */
	return details && details->reclaim_pt && (end - start >= PMD_SIZE);
}
```

条件很保守——**必须覆盖完整的一个 PMD 范围**（也就是整张 PTE 表都在本次 zap 范围内），否则检查"表是否为空"本身就没有意义。

真正的检查在 `zap_empty_pte_table()`：

```c
static bool zap_empty_pte_table(struct mm_struct *mm, pmd_t *pmd,
		spinlock_t *ptl, pmd_t *pmdval)
{
	spinlock_t *pml = pmd_lockptr(mm, pmd);

	if (ptl != pml && !spin_trylock(pml))
		return false;

	*pmdval = pmdp_get(pmd);
	pmd_clear(pmd);
	if (ptl != pml)
		spin_unlock(pml);
	return true;
}
```

**同时拿 pmd 锁与 pte 锁**（`ptl` 已由调用者持有，`pml` 是这一层的锁），且用 `spin_trylock` 而非 `spin_lock`——拿不到就放弃，避免与别处形成锁序死锁。两把锁都拿到才能安全地确认"整张表都是空的"并摘掉 pmd 项。

调用点在 `zap_pte_range()` 的收尾处，还有一个**快速路径判断**：

```c
	/*
	 * Fast path: try to hold the pmd lock and unmap the PTE page.
	 *
	 * If the pte lock was released midway (retry case), or if the attempt
	 * to hold the pmd lock failed, then we need to recheck all pte entries
	 * to ensure they are still none, thereby preventing the pte entries
	 * from being repopulated by another thread.
	 */
	if (can_reclaim_pt && direct_reclaim && addr == end)
		direct_reclaim = zap_empty_pte_table(mm, pmd, ptl, &pmdval);
```

`direct_reclaim` 会在两种情况下降级为 false：中途 `need_resched()` 让出 CPU（`direct_reclaim = false; break;`），或批满了需要 `force_break`。降级后走的是完整重查路径 `zap_pte_table_if_empty()`——**逐项重扫确认全空**才摘，防止在自己让出 CPU 期间别的线程又填了新 PTE 进来：

```c
	for (i = 0, pte = start_pte; i < PTRS_PER_PTE; i++, pte++) {
		if (!pte_none(ptep_get(pte)))
			goto out_ptl;
	}
	pte_unmap(start_pte);

	pmd_clear(pmd);
```

页表回收是个"锦上添花"的机制——不参与正确性，只在恰当的时候省下几页内存。所以它的每一步都以"拿不到锁就放弃""条件不满足就跳过"的方式退让，绝不阻塞主流程。

## Interaction with Other Subsystems

**与 VMA 的关系**：VMA 是"约定"，页表是"兑现"。VMA 记录"这段地址是文件映射、可写、可执行"；页表记录"这个 4K 页现在映射到哪个物理页帧"。缺页处理就是把前者的性质翻译成后者的具体表项。这也解释了为什么 `free_pgtables()` 必须先 `unlink_anon_vmas()`——拆页表之前得先把 VMA 从所有反向索引里摘掉。

**与物理内存管理**：页表页从 buddy 分配（order-0，`__GFP_COMP`），计入 `NR_PAGETABLE` 而非任何进程的 RSS。它与 [PageCache.md](/docs/CS/OS/Linux/mm/PageCache.md) 的页性质上都是"内核自己的内存开销"，但页表页**不可回收**（`CONFIG_PT_RECLAIM` 只是提前回收，不是压力下的回收），所以在内存核算里要单独看待。

**与 memcg**：`ptdesc` 有 `pt_memcg_data` 字段，页表页**按 memcg 记账**——这是很多容器里"进程 RSS 不大但 memcg 用量高"的原因之一。页表开销跟着进程的数万个 VMA 走。

**与 Swap**：swap 项就住在非存在 PTE 里，其编码与 `_PAGE_SWP_*` 位的借用共同构成完整的语义空间。换出时要写一个 swap 项进 PTE，换入时要读出来并恢复成正常映射。

**与 KVM**：[KVM.md](/docs/CS/OS/Linux/KVM.md) 讲的 EPT/NPT 是**第二级页表**——guest 的虚拟地址先经 guest 自己的页表翻译成 GPA，再由 EPT 把 GPA 翻译成 HPA。host 侧的页表与 guest 侧的页表叠成了两级翻译，这是虚拟机内存虚拟化的全部代价所在。`vcpu->mmu` 那套函数指针表在架构上与本文的 `pagetable_*` 抽象族是同一个设计思路：**用一层间接把架构差异挡在核心逻辑之外**。

**与锁子系统**：`ptl` 的三种配置（见前文表格）本身就是 [Lock](/docs/CS/OS/Linux/Lock/README.md) 里"锁粒度与争用"主题在页表上的具体化。而 `mmap_lock` → per-VMA lock 的演进（`vma_start_write`、`pte_offset_map_*_nolock`），是把一把大锁拆成细粒度锁之后，**迫使页表接口暴露新的"不加锁"变体**这一连锁反应的实例。

## Observation and Troubleshooting

| 手段 | 看什么 |
|---|---|
| `/proc/meminfo` 的 `PageTables` | 全系统页表内存总量 |
| `/proc/<pid>/status` 的 `VmPTE` | 单进程页表开销 |
| `/proc/<pid>/statm` | 第 4 个字段是页表页数 |
| `/sys/kernel/debug/kernel_page_tables` | 内核页表层级 dump（`ptdump`） |
| `perf` 的 `tlb_flush` 事件 | TLB shootdown 频率 |

几个典型症状与页表的关系：

- **`PageTables` 持续增长不回落**：很可能是 VMA 数量多的进程（如 JVM、大量 mmap 的数据库）。每个 VMA 在其覆盖范围内至少要有一串页表页，`CONFIG_PT_RECLAIM` 能缓解但不能根治。
- **`munmap` 延迟抖动**：一次大范围 unmap 会触发大量 TLB shootdown。`tlb_finish_mmu()` 里升级为 fullmm 的情况要特别留意——那意味着有并行 PTE 批处理。
- **多线程缺页慢**：检查是否开启了 `SPLIT_PTE_PTLOCKS`，否则所有缺页在 `mm->page_table_lock` 上串行。
- **进程 RSS 与实际占用不符**：页表页（`VmPTE`）不计入 `VmRSS`，memcg 里却算。

## Links

- [内存管理链路总图](/docs/CS/OS/Linux/mm/README.md)
- [虚拟内存与 VMA](/docs/CS/OS/Linux/mm/vm.md)
- [KVM 虚拟化](/docs/CS/OS/Linux/KVM.md)
- [Lock 同步原语](/docs/CS/OS/Linux/Lock/README.md)
- [Swap 交换](/docs/CS/OS/Linux/Swap.md)

## References

1. [Page tables — The Linux Kernel documentation](https://docs.kernel.org/mm/page_tables.html)
2. [Documentation/arch/x86/x86_64/mm.rst — Memory map](https://docs.kernel.org/arch/x86/x86_64/mm.html)
3. [Intel 64 and IA-32 Architectures Software Developer's Manual, Volume 3A, Chapter 4: Paging](https://www.intel.com/content/www/us/en/developer/articles/technical/intel-sdm.html)
4. [Examining the Linux page table manipulation interface (LWN)](https://lwn.net/Articles/993531/)
