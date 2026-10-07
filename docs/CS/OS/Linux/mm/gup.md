## Introduction

内核要读写用户内存，通常只需把用户虚拟地址当参数传给 `copy_from_user()` 之类的接口，函数内部走一遍页表就能拿到物理页。这个过程是瞬时的：拿到页、拷完、放掉，中间不做别的事。

但有一类需求不是瞬时的。网卡要做 DMA，它需要的是**物理地址**，而且这个物理地址在整段 I/O 完成之前不能变；RDMA 要把用户缓冲注册进硬件，可能几天都不释放；`io_uring` 的注册缓冲、`VFIO` 直通设备、`process_vm_readv`、`ptrace` 读写目标进程内存，都属于这一类。它们共同的要求是：**把"用户虚拟地址 → 物理页"这个映射冻结一段时间**。

这就是 GUP（get_user_pages）与 pin 页要解决的问题。它比"走一遍页表"多出来的部分，全在**后果**上：

- 页被 pin 住了，回收器就不能回收它；
- 页被 pin 住了，迁移就可能失败（因为 pin 者拿的是旧 PFN）；
- 页被 pin 住了，COW 就不能随便分裂它（分裂后 pin 者手里的页不再是页表里那个页）；
- 页被 pin 住了，fork 的写保护、KSM 的合并、soft-dirty 追踪都要绕开它。

所以这篇笔记的主线是三条：

1. **怎么走** —— GUP 的慢路径与快路径，以及 fast GUP 为什么必须关中断（这条直接接在 [pagetable.md](/docs/CS/OS/Linux/mm/pagetable.md?id=mmu_gather-batch-tlb-invalidation) 的延迟释放协议上）；
2. **计数放哪** —— `GUP_PIN_COUNTING_BIAS` 如何把"pin 了几次"编进 refcount 的高位；
3. **谁必须让路** —— pin 成立之后，mm 里哪些路径要先检查 `folio_maybe_dma_pinned()`。

对应内核版本 **v7.2.7**（源码树 `/Users/robin/Tools/linux-7.2.7`），主干集中在 `mm/gup.c`（3563 行）、`mm/internal.h` 的 FOLL 内部标志段、`include/linux/mm.h` 的 pin 计数段。

## Why "Walking the Page Table Once" Is Not Enough

用户页与内核页的差别，不在于能不能拿到物理地址，而在于**这个物理地址的有效期**。

内核自己 `kmalloc` 出来的页是稳定的：物理页不会被换出（内核内存不可换页）、不会被迁移到别处（除非显式做内存热插拔）、refcount 归零前不会被复用。所以内核想长期持有它，加一次 refcount 就够了。

用户页不是这样。它同时受三个机制的摆布：

| 机制 | 对"物理页身份"的影响 | 谁触发 |
|---|---|---|
| 换出 / 回收 | 物理页被回收，PTE 变成 swap entry —— 根本没有物理页了 | 内存压力、`madvise(MADV_PAGEOUT)` |
| 页迁移 | 内容被搬到另一个 PFN，PTE 改写指向新页 | 内存规整、NUMA 平衡、CMA、热插拔 |
| 写时复制 | 一个页被多个映射共享，写操作会分裂成两个页 | fork 后的写、KSM 页的写 |
| `munmap` / 进程退出 | 映射消失，页被释放 | 用户空间 |

四个机制里，前三个都可能**在"物理页身份"不变的情况下悄悄换掉背后那个页**。设备拿的还是老 PFN：迁移之后它写的是已经没人看的旧页；COW 分裂之后它写的是那个只读共享副本；换出之后老 PFN 甚至已经被别的数据占用。

`pin` 就是针对这一点的：**提高 folio 的 refcount（让回收器和迁移都看见"还有人在用"），并额外记录一次"这是 pin 不是普通引用"**。前者让物理页活下来，后者让内核能区分"普通引用"（随时可以放）和"pin 引用"（必须等外部设备用完）。

两个层面都必须有，缺一不可：

- 只有 refcount 没有 pin 计数 → 内核无法判断"这页是不是被 DMA 借走了"，也就无法知道 fork / 迁移 / soft-dirty 该不该绕开它；
- 只有 pin 计数没有 refcount → 页仍然可能被回收，计数挂在已经释放的页上。

## Two API Families

内核提供两套接口，**语义不同、释放方式不同、绝对不能混用**：

| 家族 | 典型函数 | 对应释放 | 语义 |
|---|---|---|---|
| `get_user_pages*()` | `get_user_pages()` / `get_user_pages_fast()` / `get_user_pages_remote()` | `put_page()` | 借一个普通引用，用于短期访问 |
| `pin_user_pages*()` | `pin_user_pages()` / `pin_user_pages_fast()` / `pin_user_pages_remote()` | `unpin_user_page()` / `unpin_user_pages()` | 建立 pin，用于把页交给外部（DMA、RDMA、VFIO） |

两套底层用的是同一套 FOLL 标志，区别只在 `FOLL_GET` 与 `FOLL_PIN` 这对互斥位。释放时必须配对：`gup_put_folio()` 里那个 `flags & FOLL_PIN` 分支就是分岔点，走错分支的后果是计数错乱（`mm/gup.c:102`）。

v7.2.7 的公开接口全貌（`include/linux/mm.h:3229-3285`）：

```c
long get_user_pages_remote(struct mm_struct *mm,
			   unsigned long start, unsigned long nr_pages,
			   unsigned int gup_flags, struct page **pages,
			   int *locked);
long pin_user_pages_remote(struct mm_struct *mm,
			   unsigned long start, unsigned long nr_pages,
			   unsigned int gup_flags, struct page **pages,
			   int *locked);
long get_user_pages(unsigned long start, unsigned long nr_pages,
		    unsigned int gup_flags, struct page **pages);
long pin_user_pages(unsigned long start, unsigned long nr_pages,
		    unsigned int gup_flags, struct page **pages);
long get_user_pages_unlocked(unsigned long start, unsigned long nr_pages,
		    struct page **pages, unsigned int gup_flags);
long pin_user_pages_unlocked(unsigned long start, unsigned long nr_pages,
		    struct page **pages, unsigned int gup_flags);
long memfd_pin_folios(struct file *memfd, loff_t start, loff_t end,
		      struct folio **folios, unsigned int max_folios,
		      pgoff_t *offset);
int folio_add_pins(struct folio *folio, unsigned int pins);
int get_user_pages_fast(unsigned long start, int nr_pages,
			unsigned int gup_flags, struct page **pages);
int pin_user_pages_fast(unsigned long start, int nr_pages,
			unsigned int gup_flags, struct page **pages);
void folio_add_pin(struct folio *folio);
```

几个值得单独指出的点：

- **`memfd_pin_folios()`** 是 folio 粒度的新接口，专给 memfd + 大 folio 的场景用（RDMA 注册大页缓冲、udmabuf 之类）。它返回的是 `struct folio **` 而不是 `struct page **`，因为调用者需要知道每个 folio 覆盖多大范围；配合的释放接口是 `unpin_folio()` / `unpin_folios()`。
- **`get_user_pages_fast_only()`**（`include/linux/mm.h:3333`）是"只准走快路径"的版本，失败不回落慢路径。futex 需要它——`get_futex_key()` 想在 THP tail page 上定位 futex，必须能 pin 页，但又不允许在缺页路径里睡眠。
- **`vmas` 输出参数已经彻底消失**。老版本的 `get_user_pages_remote()` 有一个 `struct vm_area_struct **vmas` 参数，一次调用同时输出每个页所属的 VMA。v7.2.7 的签名里没有它了，需要 VMA 的场景改用单页接口 `get_user_page_vma_remote()`，它内部用 `vma_lookup()` 单独取：

```c
static inline struct page *get_user_page_vma_remote(struct mm_struct *mm,
						    unsigned long addr,
						    int gup_flags,
						    struct vm_area_struct **vmap)
{
	struct page *page;
	struct vm_area_struct *vma;
	int got;

	if (WARN_ON_ONCE(unlikely(gup_flags & FOLL_NOWAIT)))
		return ERR_PTR(-EINVAL);

	got = get_user_pages_remote(mm, addr, 1, gup_flags, &page, NULL);

	if (got < 0)
		return ERR_PTR(got);

	vma = vma_lookup(mm, addr);
	if (WARN_ON_ONCE(!vma)) {
		put_page(page);
		return ERR_PTR(-EINVAL);
	}

	*vmap = vma;
	return page;
}
```

这个改动的动机很实际：每页都记录 VMA 会让快路径的批量输出变复杂，而绝大多数调用者根本不需要。现在只在真正需要时多取一次 maple tree。

### Callers of the Pin Interface

`pin_user_pages*()` 的调用者集中在"要把页交给硬件或长期持有"的地方，可以在源码里直接看到这层：

- `drivers/infiniband/` —— RDMA 内存注册（`ib_umem`）；
- `drivers/vfio/` —— 设备直通，把 guest 内存交给物理设备；
- `drivers/gpu/`、`drm/` —— GPU 显存共享（`hmm_range_fault` 走的另一条路）；
- `block/`、`fs/` 的 Direct I/O 路径 —— 部分实现会对齐到 pin；
- `io_uring` 的 `IORING_REGISTER_BUFFERS` —— 固定缓冲，见 [io_uring](/docs/CS/OS/Linux/IO/io_uring.md)。

**`FOLL_PIN` 不允许由调用者直接指定**，必须由 `pin_user_pages*()` 家族内部设置。这是 `is_valid_gup_args()` 检查 `INTERNAL_GUP_FLAGS` 的原因之一——手工混用会导致释放时配错接口。

## FOLL Flags

标志分两组：一组对外可见（调用者可以传），一组只用在内核内部。

### Externally Visible Flags

v7.2.7 把它们定义成了 `enum`，而不是老的 `#define`——这是个小但容易踩的版本差异，老代码里 `#ifdef FOLL_WRITE` 这种写法本来就不可能成立，但搜索 `^#define FOLL_` 会一无所获（`include/linux/mm_types.h:1872`）：

```c
enum {
	/* check pte is writable */
	FOLL_WRITE = 1 << 0,
	/* do get_page on page */
	FOLL_GET = 1 << 1,
	/* give error on hole if it would be zero */
	FOLL_DUMP = 1 << 2,
	/* get_user_pages read/write w/o permission */
	FOLL_FORCE = 1 << 3,
	/*
	 * if a disk transfer is needed, start the IO and return without waiting
	 * upon it
	 */
	FOLL_NOWAIT = 1 << 4,
	/* do not fault in pages */
	FOLL_NOFAULT = 1 << 5,
	/* check page is hwpoisoned */
	FOLL_HWPOISON = 1 << 6,
	/* don't do file mappings */
	FOLL_ANON = 1 << 7,
	/*
	 * FOLL_LONGTERM indicates that the page will be held for an indefinite
	 * time period _often_ under userspace control.  This is in contrast to
	 * iov_iter_get_pages(), whose usages are transient.
	 */
	FOLL_LONGTERM = 1 << 8,
	/* split huge pmd before returning */
	FOLL_SPLIT_PMD = 1 << 9,
	/* allow returning PCI P2PDMA pages */
	FOLL_PCI_P2PDMA = 1 << 10,
	/* allow interrupts from generic signals */
	FOLL_INTERRUPTIBLE = 1 << 11,
	/*
	 * Always honor (trigger) NUMA hinting faults.
	 *
	 * FOLL_WRITE implicitly honors NUMA hinting faults because a
	 * PROT_NONE-mapped page is not writable (exceptions with FOLL_FORCE
	 * apply). get_user_pages_fast_only() always implicitly honors NUMA
	 * hinting faults.
	 */
	FOLL_HONOR_NUMA_FAULT = 1 << 12,

	/* See also internal only FOLL flags in mm/internal.h */
};
```

逐个说人话：

| 标志 | 作用 | 典型用户 |
|---|---|---|
| `FOLL_WRITE` | 要求 PTE 可写；PTE 只读时触发一次写缺页（含 break COW） | Direct I/O 写入、`process_vm_writev` |
| `FOLL_GET` | 走"普通引用"路径，配 `put_page()` | 绝大多数老代码 |
| `FOLL_DUMP` | coredump 用：**遇到空洞直接返错，不分配页也不建页表** | `ELF_CORE` 的 `get_dump_page()` |
| `FOLL_FORCE` | 无视 VMA 权限位，可写只读映射 | `ptrace` 打断点（写 `.text`） |
| `FOLL_NOWAIT` | 需要磁盘 I/O 时不等待，直接返回 | O_DIRECT 的异步路径 |
| `FOLL_NOFAULT` | 完全不触发缺页，页不在就返回 `-EFAULT` | `get_user_pages_fast_only()` |
| `FOLL_HWPOISON` | 检查页是否被 hwpoison 标记 | 内存故障注入 / 隔离 |
| `FOLL_ANON` | 只要匿名映射 | `MADV_POPULATE` 的部分场景 |
| `FOLL_LONGTERM` | **声明"要长期持有"**，触发落点合规检查 | RDMA、VFIO、io_uring 固定缓冲 |
| `FOLL_SPLIT_PMD` | 返回前先拆 PMD 级大页 | 需要页粒度 PTE 的调用者 |
| `FOLL_PCI_P2PDMA` | 允许返回 PCI P2P DMA 页 | P2P DMA 场景 |
| `FOLL_INTERRUPTIBLE` | 允许被普通信号（不只是致命信号）打断 | 可能长时间运行的可中断路径 |
| `FOLL_HONOR_NUMA_FAULT` | 强制触发 NUMA hinting fault | 需要 NUMA 统计准确的场景 |

`FOLL_HONOR_NUMA_FAULT` 是**从 `FOLL_NUMA` 改名来的**。老资料里 `FOLL_NUMA` 这个名字已经不存在了，慢路径里也不再是简单地"没设 FORCE 就加上 NUMA"——语义收窄成了"显式要求触发 NUMA hinting fault"。

### Internal Flags

另一半在 `mm/internal.h:1630-1652`，外部传入会被 `is_valid_gup_args()` 拒绝：

```c
	/* ... internal only, see below */
	FOLL_TOUCH = 1 << 16,
	/* ... */
	FOLL_TRIED = 1 << 17,
	/* we are working on non-current tsk/mm */
	FOLL_REMOTE = 1 << 18,
	/* pages must be released via unpin_user_page */
	FOLL_PIN = 1 << 19,
	/* gup_fast: prevent fall-back to slow gup */
	FOLL_FAST_ONLY = 1 << 20,
	/* allow unlocking the mmap lock */
	FOLL_UNLOCKABLE = 1 << 21,
	/* VMA lookup+checks compatible with MADV_POPULATE_(READ|WRITE) */
	FOLL_MADV_POPULATE = 1 << 22,
};

#define INTERNAL_GUP_FLAGS (FOLL_TOUCH | FOLL_TRIED | FOLL_REMOTE | FOLL_PIN | \
			    FOLL_FAST_ONLY | FOLL_UNLOCKABLE | \
			    FOLL_MADV_POPULATE)
```

其中 `FOLL_PIN` 虽然语义上是"外部概念"，实现上却是内部标志——它由 `pin_user_pages*()` 家族设置，不由调用者直接传。

### Parameter Invariants

`is_valid_gup_args()`（`mm/gup.c:2506`）是所有这些标志的守门人，四条硬约束：

```c
	/*
	 * These flags not allowed to be specified externally to the gup
	 * interfaces:
	 * - FOLL_TOUCH/FOLL_PIN/FOLL_TRIED/FOLL_FAST_ONLY are internal only
	 * - FOLL_REMOTE is internal only, set in (get|pin)_user_pages_remote()
	 * - FOLL_UNLOCKABLE is internal only and used if locked is !NULL
	 */
	if (WARN_ON_ONCE(gup_flags & INTERNAL_GUP_FLAGS))
		return false;

	gup_flags |= to_set;
	if (locked) {
		/* At the external interface locked must be set */
		if (WARN_ON_ONCE(*locked != 1))
			return false;

		gup_flags |= FOLL_UNLOCKABLE;
	}

	/* FOLL_GET and FOLL_PIN are mutually exclusive. */
	if (WARN_ON_ONCE((gup_flags & (FOLL_PIN | FOLL_GET)) ==
			 (FOLL_PIN | FOLL_GET)))
		return false;

	/* LONGTERM can only be specified when pinning */
	if (WARN_ON_ONCE(!(gup_flags & FOLL_PIN) && (gup_flags & FOLL_LONGTERM)))
		return false;

	/* Pages input must be given if using GET/PIN */
	if (WARN_ON_ONCE((gup_flags & (FOLL_GET | FOLL_PIN)) && !pages))
		return false;

	/* We want to allow the pgmap to be hot-unplugged at all times */
	if (WARN_ON_ONCE((gup_flags & FOLL_LONGTERM) &&
			 (gup_flags & FOLL_PCI_P2PDMA)))
		return false;
```

四条约束分别对应四种真实 bug：

1. **`FOLL_GET` 与 `FOLL_PIN` 互斥** —— 同时设置意味着"这页既是普通引用又是 pin"，释放时无法判断该走哪条路。
2. **`FOLL_LONGTERM` 必须配 `FOLL_PIN`** —— 长期持有却没走 pin 路径，等于绕过了所有落点检查（下一节会看到这有多危险）。这条约束是硬性的：想长期持有就必须 pin。
3. **`FOLL_LONGTERM` 与 `FOLL_PCI_P2PDMA` 互斥** —— P2P DMA 页来自设备内存的 `dev_pagemap`，而 `dev_pagemap` 必须支持热拔。长期 pin 住它会让热拔永远等不到。
4. **`INTERNAL_GUP_FLAGS` 外部不可指定** —— 手工传 `FOLL_TOUCH` 会改变 dirty/accessed 的副作用，传 `FOLL_UNLOCKABLE` 则会绕过 mmap_lock 的契约。

`gup_fast()` 入口处还有一张更细的白名单（`mm/gup.c:3189`），快路径只接受这几个标志的组合：

```c
	if (WARN_ON_ONCE(gup_flags & ~(FOLL_WRITE | FOLL_LONGTERM |
				       FOLL_FORCE | FOLL_PIN | FOLL_GET |
				       FOLL_FAST_ONLY | FOLL_NOFAULT |
				       FOLL_PCI_P2PDMA | FOLL_HONOR_NUMA_FAULT)))
		return -EINVAL;
```

注意这里**放行 `FOLL_PIN` 与 `FOLL_GET`**——它们最终会在 `try_grab_folio_fast()` 里被再次分流。

## Slow Path: Following the Page Table, Faulting When Stuck

### Main Loop

慢路径的骨架是 `__get_user_pages()`（`mm/gup.c:1354`）里那个 `do { } while` 循环：

```c
	do {
		struct page *page;
		unsigned int foll_flags = gup_flags;
		unsigned int page_increm;

		/* first iteration or cross vma bound */
		if (!vma || start >= vma->vm_end) {
			vma = gup_vma_lookup(mm, start);
			if (!vma && in_gate_area(mm, start)) {
				...
			}
			...
```

每一页的处理逻辑是"先看页表里有没有，没有就造一个缺页，然后重试"：

```c
retry:
		...
		page = follow_page_mask(vma, start, foll_flags, &ctx);
		if (!page) {
			ret = faultin_page(vma, start, &foll_flags, locked);
			switch (ret) {
			case 0:
				goto retry;
			case -EBUSY:
				ret = 0;
				fallthrough;
```

这个 `retry:` 标签是理解整个慢路径的钥匙：**GUP 自己不建页表、不读文件、不做 COW，它只是反复问"页表里现在有页了吗"，没有就调一次缺页，然后再问一遍**。真正的建页表逻辑全在缺页路径里，也就是 [pagetable.md](/docs/CS/OS/Linux/mm/pagetable.md?id=lazy-growth-building-tables-level-by-level-on-page-fault) 讲的 `__handle_mm_fault()` 逐级 `*_alloc`。

`-EBUSY` 对应"缺页处理过程中释放了 mmap_lock"，此时 GUP 返回 0（不是错误），调用者看到的是"这次一个都没拿到，重试吧"。

### The Hierarchical Descent of follow_page_mask

`follow_page_mask()` 是缺页路径 `__handle_mm_fault()` 的镜像版本：同样从 pgd 往下走四级，但**只读不写**，遇到不存在就返回 NULL（`mm/gup.c:1007`）：

```
follow_page_mask → follow_p4d_mask → follow_pud_mask → follow_pmd_mask → follow_page_pte
```

每一级的职责与缺页路径对应：

| 层级 | 缺页路径做什么 | GUP 路径做什么 |
|---|---|---|
| p4d / pud / pmd | `p4d_alloc` / `pud_alloc` / `pmd_alloc` 逐级分配 | 只 `*_offset` 取下一级表项，不存在就返回 NULL |
| pmd 是叶子 | 处理 THP（`do_huge_pmd_anonymous_page`） | `follow_huge_pmd()` 直接取大页 |
| pte | 分配页表页 + 填表项 | `follow_page_pte()` 读表项取页 |

**这个对称性很重要**：GUP 从不主动建页表，这是"GUP 不该产生副作用"这一设计原则的体现。反过来说，一次 GUP 调用可能触发大量缺页，从而分配页、建页表、读磁盘——`FOLL_NOFAULT` 存在的意义就是让某些调用者（如 futex）能说"别给我搞这套"。

### follow_page_pte Line by Line

这是慢路径取到页的最后一站（`mm/gup.c:802`）：

```c
static struct page *follow_page_pte(struct vm_area_struct *vma,
		unsigned long address, pmd_t *pmd, unsigned int flags)
{
	struct mm_struct *mm = vma->vm_mm;
	struct folio *folio;
	struct page *page;
	spinlock_t *ptl;
	pte_t *ptep, pte;
	int ret;

	ptep = pte_offset_map_lock(mm, pmd, address, &ptl);
	if (!ptep)
		return no_page_table(vma, flags, address);
	pte = ptep_get(ptep);
	if (!pte_present(pte))
		goto no_page;
	if (pte_protnone(pte) && !gup_can_follow_protnone(vma, flags))
		goto no_page;

	page = vm_normal_page(vma, address, pte);
```

到 `vm_normal_page()` 为止都在做"这个 PTE 指向的是不是一个正常的 struct page"。接下来是 FOLL_WRITE 的核心检查：

```c
	/*
	 * We only care about anon pages in can_follow_write_pte().
	 */
	if ((flags & FOLL_WRITE) &&
	    !can_follow_write_pte(pte, page, vma, flags)) {
		page = NULL;
		goto out;
	}
```

`page = NULL` 而不是返回错误，意味着调用者会把它当成"页不在"，进而 `faultin_page()` 触发一次**写缺页**——这正是 break COW 的触发方式。

然后处理没有 struct page 的特殊映射：

```c
	if (unlikely(!page)) {
		if (flags & FOLL_DUMP) {
			/* Avoid special (like zero) pages in core dumps */
			page = ERR_PTR(-EFAULT);
			goto out;
		}

		if (is_zero_pfn(pte_pfn(pte))) {
			page = pte_page(pte);
		} else {
			ret = follow_pfn_pte(vma, address, ptep, flags);
			page = ERR_PTR(ret);
			goto out;
		}
	}
```

零页是唯一被允许放进 `pages[]` 的无 struct page 页（它不走 pin 计数，见后文），其它特殊 PTE 交给 `follow_pfn_pte()`，后者返回 `-EEXIST` 并在注释里说明原因（`mm/gup.c:763`）：

```c
	/* Proper page table entry exists, but no corresponding struct page */
	return -EEXIST;
```

接下来两条是 pin 语义的关键：

```c
	if (!pte_write(pte) && gup_must_unshare(vma, flags, page)) {
		page = ERR_PTR(-EMLINK);
		goto out;
	}

	VM_WARN_ON_ONCE_PAGE((flags & FOLL_PIN) && PageAnon(page) &&
			     !PageAnonExclusive(page), page);
```

`-EMLINK` 这个错误码看着奇怪，但含义明确：**要 pin 一个只读的匿名页，而这个页还不是独占的**（`PageAnonExclusive` 为假），此时 pin 的页与页表里的页可能因为后续写操作而分家，所以必须让调用者走缺页路径去 unshare。错误码本身只是"逼调用者重试"的载体。

`PageAnonExclusive` 那条断言是整个 pin 机制的**不变式**：

> 一个被 pin 的匿名页，必须是独占的。

理由在 `mm/gup.c:32` 的注释里说得最清楚：

```c
	/*
	 * We only pin anonymous pages if they are exclusive. Once pinned, we
	 * can no longer turn them possibly shared and PageAnonExclusive() will
	 * stick around until the page is freed.
```

页一旦被 pin，就永远不能再变成"可能共享"——否则 KSM 会把它合并掉，或者 COW 会让它分裂，pin 者手里的页与页表里的页就断了。

最后是真正的"抓住"这个页：

```c
	/* try_grab_folio() does nothing unless FOLL_GET or FOLL_PIN is set. */
	ret = try_grab_folio(folio, 1, flags);
	if (unlikely(ret)) {
		page = ERR_PTR(ret);
		goto out;
	}

	/*
	 * We need to make the page accessible if and only if we are going
	 * to access its content (the FOLL_PIN case).  Please see
	 * Documentation/core-api/pin_user_pages.rst for details.
	 */
	if (flags & FOLL_PIN) {
		ret = arch_make_folio_accessible(folio);
		if (ret) {
			unpin_user_page(page);
			page = ERR_PTR(ret);
			goto out;
		}
	}
	if (flags & FOLL_TOUCH) {
		if ((flags & FOLL_WRITE) &&
		    !pte_dirty(pte) && !folio_test_dirty(folio))
			folio_mark_dirty(folio);
		/*
		 * pte_mkyoung() would be more correct here, but atomic care
		 * is needed to avoid losing the dirty bit: it is easier to use
		 * folio_mark_accessed().
		 */
		folio_mark_accessed(folio);
	}
```

`arch_make_folio_accessible()` 是**机密计算**相关的钩子：通用实现是空函数（`include/linux/mm.h:2971`），只有 s390 定义了自己的版本（`arch/s390/kernel/uv.c:376`），用于"把页解密给设备可见"。它的注释也解释了为什么只在 `FOLL_PIN` 时调用——只有 pin 才会把页交给**外部**设备去读，普通 GUP 是内核自己访问，不需要这个动作。

### The Boundary between can_follow_write_pte and FOLL_FORCE

`can_follow_write_pte()`（`mm/gup.c:785`）处理"PTE 只读但我想写"的情况，先看 PTE 本身可写就直接通过，否则落到 `can_follow_write_common()`：

```c
static inline bool can_follow_write_common(struct page *page,
		struct vm_area_struct *vma, unsigned int flags)
{
	/* Maybe FOLL_FORCE is set to override it? */
	if (!(flags & FOLL_FORCE))
		return false;

	/* But FOLL_FORCE has no effect on shared mappings */
	if (vma->vm_flags & (VM_MAYSHARE | VM_SHARED))
		return false;

	/* ... or read-only private ones */
	if (!(vma->vm_flags & VM_MAYWRITE))
		return false;

	/* ... or already writable ones that just need to take a write fault */
	if (vma->vm_flags & VM_WRITE)
		return false;

	/*
	 * See can_change_pte_writable(): we broke COW and could map the page
	 * writable if we have an exclusive anonymous page ...
	 */
	return page && PageAnon(page) && PageAnonExclusive(page);
}
```

四个 `return false` 把这个后门收得很紧：`FOLL_FORCE`（也就是 `ptrace`）只能写**私有、可写、但当前只读**的匿名页——就是 COW 之后本该变成可写的那种页。这正好覆盖"往 `.text` 里打断点"的场景，同时挡住了"往共享映射写"这种会污染文件的操作。

`FOLL_FORCE` 的完整检查在 `check_vma_flags()` 里还有一层，其中 `VM_SHADOW_STACK`（CET 影子栈）也被显式拒绝写：

```c
	if (vm_flags & (VM_IO | VM_PFNMAP))
		return -EFAULT;
	...
	if (vma_is_secretmem(vma))
		return -EFAULT;

	if (write) {
		if (!vma_anon &&
		    !writable_file_mapping_allowed(vma, gup_flags))
			return -EFAULT;

		if (!(vm_flags & VM_WRITE) || (vm_flags & VM_SHADOW_STACK)) {
			if (!(gup_flags & FOLL_FORCE))
				return -EFAULT;
			/*
			 * We used to let the write,force case do COW in a
			 * VM_MAYWRITE VM_SHARED !VM_WRITE vma, so ptrace could
			 * set a breakpoint in a read-only mapping of an
			 * executable, without corrupting the file (yet only
			 * when that file had been opened for writing!).
			 * Anon pages in shared mappings are surprising: now
			 * just reject it.
			 */
			if (!is_cow_mapping(vm_flags))
				return -EFAULT;
		}
	} else if (!(vm_flags & VM_READ)) {
```

注意开头那两行：**`VM_IO` 与 `VM_PFNMAP` 直接被拒**。这两类映射（设备 mmap、`remap_pfn_range`）背后根本没有 struct page，GUP 拿不到可引用的对象，所以第一道防线就挡住了。

`check_vma_flags()` 里还有两条针对 LONGTERM 的拒绝，价值很高：

```c
	if ((gup_flags & FOLL_LONGTERM) && vma_is_fsdax(vma))
		return -EOPNOTSUPP;

	if ((gup_flags & FOLL_SPLIT_PMD) && is_vm_hugetlb_page(vma))
		return -EOPNOTSUPP;
```

**fsdax 不允许长期 pin**——文件系统 DAX 依赖能随时 truncate / hole-punch 收回块，长期 pin 会让这些操作无限期阻塞。

### faultin_page: Translating FOLL into FAULT_FLAG

`faultin_page()`（`mm/gup.c:1087`）是一张翻译表，把 GUP 的标志翻译成缺页处理的标志：

```c
	unsigned int fault_flags = 0;

	if (flags & FOLL_NOFAULT)
		return -EFAULT;
	if (flags & FOLL_WRITE)
		fault_flags |= FAULT_FLAG_WRITE;
	if (flags & FOLL_REMOTE)
		fault_flags |= FAULT_FLAG_REMOTE;
	if (flags & FOLL_UNLOCKABLE) {
		fault_flags |= FAULT_FLAG_ALLOW_RETRY | FAULT_FLAG_KILLABLE;
		/*
		 * FAULT_FLAG_INTERRUPTIBLE is opt-in. GUP callers must set
		 * FOLL_INTERRUPTIBLE to enable FAULT_FLAG_INTERRUPTIBLE.
		 * That's because some callers may not be prepared to
		 * handle early exits caused by non-fatal signals.
		 */
		if (flags & FOLL_INTERRUPTIBLE)
			fault_flags |= FAULT_FLAG_INTERRUPTIBLE;
	}
	if (flags & FOLL_NOWAIT)
		fault_flags |= FAULT_FLAG_ALLOW_RETRY | FAULT_FLAG_RETRY_NOWAIT;
	if (flags & FOLL_TRIED) {
		/*
		 * Note: FAULT_FLAG_ALLOW_RETRY and FAULT_FLAG_TRIED
		 * can co-exist
		 */
		fault_flags |= FAULT_FLAG_TRIED;
	}
	if (unshare) {
		fault_flags |= FAULT_FLAG_UNSHARE;
		/* FAULT_FLAG_WRITE and FAULT_FLAG_UNSHARE are incompatible */
		VM_WARN_ON_ONCE(fault_flags & FAULT_FLAG_WRITE);
	}

	ret = handle_mm_fault(vma, address, fault_flags, NULL);
```

| GUP 侧 | 缺页侧 | 含义 |
|---|---|---|
| `FOLL_WRITE` | `FAULT_FLAG_WRITE` | 走写缺页（会 break COW） |
| `FOLL_REMOTE` | `FAULT_FLAG_REMOTE` | 目标不是当前进程的 mm |
| `FOLL_UNLOCKABLE` | `ALLOW_RETRY \| KILLABLE` | 允许释放 mmap_lock，允许被致命信号打断 |
| `FOLL_INTERRUPTIBLE` | `FAULT_FLAG_INTERRUPTIBLE` | 进一步允许被普通信号打断 |
| `FOLL_NOWAIT` | `ALLOW_RETRY \| RETRY_NOWAIT` | 需要 I/O 时立刻返回，不等待 |
| `FOLL_TRIED` | `FAULT_FLAG_TRIED` | 这是重试，文件系统可以走慢路径 |
| `unshare` | `FAULT_FLAG_UNSHARE` | **只拆共享，不写** |

最后一行是重点。`unshare` 参数由调用者根据 `gup_must_unshare()` 的结果传入，如果为真，用的是一个**专门的缺页标志** `FAULT_FLAG_UNSHARE`——不是 `FAULT_FLAG_WRITE`，源码注释明确说两者不兼容：

> `FAULT_FLAG_WRITE and FAULT_FLAG_UNSHARE are incompatible`

原因是两者的语义不同。`FAULT_FLAG_WRITE` 是"我要写这个页"，处理后页表变成可写、页变脏。而 `FAULT_FLAG_UNSHARE` 是"我要让这个页变成独占的，但**我不写**"——典型场景是 R/O 的长期 pin：

进程 A、B 通过 fork 共享一个匿名页（`PageAnonExclusive` 为假，PTE 只读）。A 要 R/O 长期 pin 这个页。如果什么都不做，之后 B 写这个页会触发 COW，B 拿到一个新页，而 A pin 的仍是老页——但 A 的语义是"观察到进程页表里的内容"，两边就脱节了。所以这里用 `UNSHARE` 提前把这个页变成 A 独占：**拆开共享关系，但不写、不弄脏**。

`gup_must_unshare()` 的完整判定（`mm/internal.h:1678`）：

```c
static inline bool gup_must_unshare(struct vm_area_struct *vma,
				    unsigned int flags, struct page *page)
{
	/*
	 * FOLL_WRITE is implicitly handled correctly as the page table entry
	 * has to be writable -- and if it references (part of) an anonymous
	 * folio, that part is required to be marked exclusive.
	 */
	if ((flags & (FOLL_WRITE | FOLL_PIN)) != FOLL_PIN)
		return false;
	/*
	 * Note: PageAnon(page) is stable until the page is actually getting
	 * freed.
	 */
	if (!PageAnon(page)) {
		/*
		 * We only care about R/O long-term pining: R/O short-term
		 * pinning does not have the semantics to observe successive
		 * changes through the process page tables.
		 */
		if (!(flags & FOLL_LONGTERM))
			return false;

		/* We really need the vma ... */
		if (!vma)
			return true;

		/*
		 * ... because we only care about writable private ("COW")
		 * mappings where we have to break COW early.
		 */
		return is_cow_mapping(vma->vm_flags);
	}

	/* Paired with a memory barrier in folio_try_share_anon_rmap_*(). */
	if (IS_ENABLED(CONFIG_HAVE_GUP_FAST))
		smp_rmb();

	/*
	 * Note that KSM pages cannot be exclusive, and consequently,
	 * cannot get pinned.
	 */
	return !PageAnonExclusive(page);
}
```

三条判定串起来看：

1. **只有 `FOLL_PIN` 且不带 `FOLL_WRITE`** 才需要 unshare。带了 `FOLL_WRITE` 不用管——写缺页本身就会 break COW，页表里的页必然会变成独占的。
2. **文件页只在 R/O 长期 pin 时**才需要（`FOLL_LONGTERM`）。短期 R/O pin 没有"观察页表变化"的语义承诺，不需要拆。
3. **匿名页看 `PageAnonExclusive`**。并且这里有一对微妙的内存屏障：`smp_rmb()` 与 `folio_try_share_anon_rmap_*()` 里的屏障配对，用于对抗 fast GUP 与 KSM / 临时解除映射（swap、migration）的并发。

第三条还顺带解释了**为什么 KSM 页不能被 pin**：KSM 合并的前提就是"这页不是独占的"，而 pin 的前提是"必须独占"，两者天然互斥。所以 KSM 只合并 `PageAnonExclusive` 为假的页，也就是从未被 pin 过的页。

### Why GUP Writing to File Mappings Is a "Fundamental Corruption"

`writable_file_mapping_allowed()`（`mm/gup.c:1182`）前面有一段长注释，值得整段抄下来，因为它解释了整个 pin 机制存在的历史动因：

```c
/*
 * Writing to file-backed mappings which require folio dirty tracking using GUP
 * is a fundamentally broken operation, as kernel write access to GUP mappings
 * do not adhere to the semantics expected by a file system.
 *
 * Consider the following scenario:-
 *
 * 1. A folio is written to via GUP which write-faults the memory, notifying
 *    the file system and dirtying the folio.
 * 2. Later, writeback is triggered, resulting in the folio being cleaned and
 *    the PTE being marked read-only.
 * 3. The GUP caller writes to the folio, as it is mapped read/write via the
 *    direct mapping.
 * 4. The GUP caller, now done with the page, unpins it and sets it dirty
 *    (though it does not have to).
 *
 * This results in both data being written to a folio without writenotify, and
 * the folio being dirtied unexpectedly (if the caller decides to do so).
 */
```

四步场景拆开看，问题出在第 3 步：**writeback 已经把 PTE 改成只读了，但 GUP 调用者手里有物理页地址，它绕过页表直接写**。文件系统完全不知道这次写发生——`page_mkwrite()` 没被调用、dirty 位没被设。等 GUP 调用者 unpin 时再补标脏，时机已经错过了（回写可能已经完成、buffer_head 可能已经被释放）。

这正是 2018 年 LWN 上那场讨论的主题（见 References）——当时 RDMA 在文件映射内存上做 DMA 会稳定触发 `BUG_ON(!PagePrivate(page))`。后来演变成今天的设计：

- 想要 `FOLL_WRITE` + 长期持有？先过 `writable_file_mapping_allowed()`；
- 只允许 **shmem**（tmpfs）的写 pin。

## Fast Path: Disabling Interrupts, Lockless Page Table Walk

慢路径一次要拿页表锁、可能还要触发缺页，对 `io_uring`、`futex`、`process_vm_readv` 这种高频调用太贵。所以内核还有一条 `get_user_pages_fast()` 路径：**不拿页表锁、不关页表变更，靠"事后验证"来保证正确性**。

### Why local_irq_save Instead of rcu_read_lock

```c
	/*
	 * Disable interrupts. The nested form is used, in order to allow full,
	 * general purpose use of this routine.
	 *
	 * With interrupts disabled, we block page table pages from being freed
	 * from under us. See struct mmu_table_batch comments in
	 * include/asm-generic/tlb.h for more details.
	 *
	 * We do not adopt an rcu_read_lock() here as we also want to block IPIs
	 * that come from callers of tlb_remove_table_sync_one().
	 */
	local_irq_save(flags);
	gup_fast_pgd_range(start, end, gup_flags, pages, &nr_pinned);
	local_irq_restore(flags);
```

**这段注释是整篇笔记与 [pagetable.md](/docs/CS/OS/Linux/mm/pagetable.md?id=deferred-release-of-page-table-pages) 的接口。** 三层意思：

1. **关中断能阻止页表页被释放** —— 释放页表页不是直接 `free_page()`，而是走 mmu_gather 的延迟释放队列，最后需要一次 IPI 同步（`tlb_remove_table_sync_one()`）或 RCU 宽限期。关中断让本 CPU 收不到 IPI，释放方就得等——这正是延迟释放机制的设计前提。
2. **为什么不用 `rcu_read_lock()`** —— 因为 RCU 只能挡住 RCU 回调释放的那条路，挡不住 IPI 那条路，而页表页释放两条路都会用。关中断是更强的约束。
3. **"nested form"** —— `local_irq_save/restore` 保存并恢复标志位，允许这个函数在已经关中断的上下文里被嵌套调用。

代价也是真实的：**整段快路径遍历期间本 CPU 不响应外部中断**。所以 `gup_fast()` 有长度限制——遍历范围太大时调用者会切片处理，避免单次关中断时间过长。

对比一下 pagetable.md 里讲的三种无锁页表访问手段：

| 机制 | 用什么挡住页表页释放 | 用在哪 |
|---|---|---|
| `rcu_read_lock()` | RCU 宽限期 | `pte_offset_map()` 失败返回 NULL 的路径 |
| `local_irq_disable()` | 同时挡住 IPI 与 RCU | **fast GUP** |
| per-VMA lock | VMA 级锁 + `ptl` 的替代 | `pte_offset_map_ro_nolock()` 等变体 |

### Bidirectional Protocol

这是 fast GUP 最精妙的地方，源码注释（`mm/gup.c:2816`）把它写成了一份协议：

```c
/*
 * GUP-fast relies on pte change detection to avoid concurrent pgtable
 * operations.
 *
 * To pin the page, GUP-fast needs to do below in order:
 * (1) pin the page (by prefetching pte), then (2) check pte not changed.
 *
 * For the rest of pgtable operations where pgtable updates can be racy
 * with GUP-fast, we need to do (1) clear pte, then (2) check whether page
 * is pinned.
 *
 * Above will work for all pte-level operations, including THP split.
 *
 * For THP collapse, it's a bit more complicated because GUP-fast may be
 * walking a pgtable page that is being freed (pte is still valid but pmd
 * can be cleared already).  To avoid race in such condition, we need to
 * also check pmd here to make sure pmd doesn't change (corresponds to
 * pmdp_collapse_flush() in the THP collapse code path).
 */
```

拆成两半看：

**GUP-fast 一侧**：先抓住页（让 refcount 涨上去），**然后**再读一次 PTE 确认没变。顺序不能反——如果先验证再抓，验证通过到抓住之间的窗口里页面可能已经被换掉。

```c
		folio = try_grab_folio_fast(page, 1, flags);
		if (!folio)
			goto pte_unmap;

		if (unlikely(pmd_val(pmd) != pmd_val(pmdp_get_lockless(pmdp))) ||
		    unlikely(pte_val(pte) != pte_val(ptep_get_lockless(ptep)))) {
			gup_put_folio(folio, 1, flags);
			goto pte_unmap;
		}
```

注意这里**同时验证了 pmd 和 pte**。验证 pmd 是 THP collapse 场景的要求：collapse 时 pte 表所在的页表页可能正在被释放，PTE 本身还是合法的，但 pmd 已经被清掉了——只验证 pte 会漏掉这种"整张表都要没了"的情况。

**页表操作一侧**：任何可能破坏"页表里那个页就是 GUP 拿到的那个页"的操作，都必须**先清掉 PTE，再检查这个页有没有被 pin 过**。如果发现被 pin 了，就得退回重来或等待。这两半合起来才闭环——只做一半，无论哪一半，都会留下窗口。

`gup_fast_pte_range()` 完整循环见 `mm/gup.c:2835`，其中还有几个拒绝点：

```c
		/*
		 * Always fallback to ordinary GUP on PROT_NONE-mapped pages:
		 * pte_access_permitted() better should reject these pages
		 * either way: otherwise, GUP-fast might succeed in
		 * cases where ordinary GUP would fail due to VMA access
		 * permissions.
		 */
		if (pte_protnone(pte))
			goto pte_unmap;

		if (!pte_access_permitted(pte, flags & FOLL_WRITE))
			goto pte_unmap;

		if (pte_special(pte))
			goto pte_unmap;
```

`pte_protnone` 的拒绝理由是**一致性**：同样的地址，快路径该失败的和慢路径该失败的必须一样，否则调用者看到的行为会随路径而变。`PROT_NONE` 在快路径里没有 VMA 可查（快路径不持有 mmap_lock），所以干脆退回慢路径去查。

### Conditions for Fast-Path Rejection

`try_grab_folio_fast()`（`mm/gup.c:517`）里有几条"抓不住就退回慢路径"的判断：

```c
	/*
	 * Can't do FOLL_LONGTERM + FOLL_PIN gup fast path if not in a
	 * right zone, so fail and let the caller fall back to the slow
	 * path.
	 */
	if (unlikely((flags & FOLL_LONGTERM) &&
		     !folio_is_longterm_pinnable(folio))) {
		folio_put_refs(folio, refs);
		return NULL;
	}
```

这个页在一个不能长期 pin 的 zone（CMA / ZONE_MOVABLE 等，见后文），快路径不做迁移，直接放弃，让慢路径去处理——慢路径有能力迁移这个页（`check_and_migrate_movable_folios()`）。

还有 `gup_fast_folio_allowed()`（`mm/gup.c:2744`），做文件系统层面的合规检查：

```c
	/*
	 * If we aren't pinning then no problematic write can occur. A long term
	 * pin is the most egregious case so this is the one we disallow.
	 */
	if ((flags & (FOLL_PIN | FOLL_LONGTERM | FOLL_WRITE)) ==
	    (FOLL_PIN | FOLL_LONGTERM | FOLL_WRITE))
		reject_file_backed = true;
	...
	/*
	 * GUP-fast disables IRQs. When IRQS are disabled, RCU grace periods
	 * cannot proceed, which means no actions performed under RCU can
	 * proceed either.
	 *
	 * inodes and thus their mappings are freed under RCU, which means the
	 * mapping cannot be freed beneath us and thus we can safely dereference
	 * it.
	 */
	lockdep_assert_irqs_disabled();

	/*
	 * However, there may be operations which _alter_ the mapping, so ensure
	 * we read it once and only once.
	 */
	mapping = READ_ONCE(folio->mapping);
	...
	/* Anonymous folios pose no problem. */
	mapping_flags = (unsigned long)mapping & FOLIO_MAPPING_FLAGS;
	if (mapping_flags)
		return mapping_flags & FOLIO_MAPPING_ANON;
	...
	if (check_secretmem && secretmem_mapping(mapping))
		return false;
	/* The only remaining allowed file system is shmem. */
	return !reject_file_backed || shmem_mapping(mapping);
```

这段把"关中断"的另一个作用讲透了：**关中断还顺便让 RCU 宽限期无法推进，从而保证 `address_space` 不会被释放**——因为 inode 及其 mapping 是在 RCU 回调里释放的。这是"一个机制、两个作用"的典型。

最后一行是结论：**唯一允许"写 + 长期 pin"的文件系统是 shmem**。这正好对上前面 `writable_file_mapping_allowed()` 的那段"根本性破坏"注释——shmem 是 RAM 文件系统，没有真正的回写与 buffer_head，绕过了整个问题。

### The Race between write_protect_seq and fork

fast GUP 还要防一个对手：**fork**。`copy_page_range()` 会把父进程的 PTE 全部写保护（建立 COW），如果 fast GUP 在这期间抓到了页，pin 的语义就被破坏了。

```c
	if (gup_flags & FOLL_PIN) {
		if (!raw_seqcount_try_begin(&current->mm->write_protect_seq, seq))
			return 0;
	}
	...
	/*
	 * When pinning pages for DMA there could be a concurrent write protect
	 * from fork() via copy_page_range(), in this case always fail GUP-fast.
	 */
	if (gup_flags & FOLL_PIN) {
		if (read_seqcount_retry(&current->mm->write_protect_seq, seq)) {
			gup_fast_unpin_user_pages(pages, nr_pinned);
			return 0;
		} else {
			sanity_check_pinned_pages(pages, nr_pinned);
		}
	}
```

这用的是标准的 seqcount 模式：进临界区前取序号（`try_begin` 而不是 `begin`——如果写者正在持锁，直接放弃，不等待），出来后检查序号是否变过。变过就**把已经 pin 的页全部 unpin 再返回 0**，一个都不留。

注意 `write_protect_seq` 只在 `FOLL_PIN` 时使用。原因回到 `gup_must_unshare()`：只有 pin 才要求"pin 的页与页表里的页永远一致"，普通 `FOLL_GET` 引用没有这个承诺。

### Choice between Fast and Slow Paths

`gup_fast_fallback()`（`mm/gup.c:3181`）是调度者：先试快路径，`nr_pinned` 不够就补慢路径。

```
gup_fast_fallback()
  ├── gup_fast()            关中断、无锁遍历，成功几个算几个
  └── 不足的部分 → __gup_longterm_locked() / __get_user_pages_locked()  慢路径补齐
```

`FOLL_FAST_ONLY` 就是用来**禁止这个回落**的：设了它，`gup_fast()` 拿不到就是失败，不会去走慢路径。futex 需要它，因为 futex 的调用点可能在不允许睡眠的上下文里。

## Where the Pin Count Lives

### Two Layouts

`struct folio` 里有两个不同的地方可以放 pin 计数，取决于 folio 大小（`include/linux/mm.h:2630`）：

```c
static inline bool folio_has_pincount(const struct folio *folio)
{
	if (IS_ENABLED(CONFIG_64BIT))
		return folio_test_large(folio);
	return folio_order(folio) > 1;
}
```

| 布局 | 适用 | 计数位置 | 精度 |
|---|---|---|---|
| 复用 refcount 高位 | 64 位下的小 folio（order-0）；32 位下 order ≤ 1 | `folio_ref_count()` 的高位 | 模糊（只能判断"可能有"） |
| 独立 `_pincount` 字段 | 64 位下的大 folio；32 位下 order > 1 | `folio->_pincount` | 精确 |

这个设计是个妥协：`struct page` / `struct folio` 空间紧张，小 folio（也就是绝大多数页）已经没有空位放额外的计数器了，只能挤在 refcount 的高位里。而大 folio 恰好有空位（原本给 `_entire_mapcount` 那片 union 有富余），所以能用精确计数。

`_pincount` 在 union 里的位置（`include/linux/mm_types.h:455-489`）：

```c
					atomic_t _large_mapcount;
					atomic_t _nr_pages_mapped;
#ifdef CONFIG_64BIT
					atomic_t _entire_mapcount;
					atomic_t _pincount;
#endif /* CONFIG_64BIT */
					mm_id_mapcount_t _mm_id_mapcount[2];
```

注意 `_pincount` 与 `_entire_mapcount` 相邻，且在 32 位下被挪到另一个 union 分支里——这就是为什么 `folio_has_pincount()` 要分 64/32 位判断。

### GUP_PIN_COUNTING_BIAS

小 folio 的编码方案是：**每次 pin 不是给 refcount 加 1，而是加 1024**（`include/linux/mm.h:2226`）：

```c
#define GUP_PIN_COUNTING_BIAS (1U << 10)
```

设计注释解释了为什么选 2 的幂（`include/linux/mm.h:2196`）：

```c
/*
 * GUP_PIN_COUNTING_BIAS, and the associated functions that use it, overload
 * the page's refcount so that two separate items are tracked: the original page
 * reference count, and also a new count of how many pin_user_pages() calls were
 * made against the page. ("gup-pinned" is another term for the latter).
 *
 * With this scheme, pin_user_pages() becomes special: such pages are marked as
 * distinct from normal pages. As such, the unpin_user_page() call (and its
 * variants) must be used in order to release gup-pinned pages.
 *
 * Choice of value:
 *
 * By making GUP_PIN_COUNTING_BIAS a power of two, debugging of page reference
 * counts with respect to pin_user_pages() and unpin_user_page() becomes
 * simpler, due to the fact that adding an even power of two to the page
 * refcount has the effect of using only the upper N bits, for the code that
 * counts up using the bias value. This means that the lower bits are left for
 * the exclusive use of the original code that increments and decrements by one
 * (or at least, by much smaller values than the bias value).
 *
 * Of course, once the lower bits overflow into the upper bits (and this is
 * OK, because subtraction recovers the original values), then visual inspection
 * no longer suffices to directly view the separate counts. However, for normal
 * applications that don't have huge page reference counts, this won't be an
 * issue.
 *
 * Locking: the lockless algorithm described in folio_try_get_rcu()
 * provides safe operation for get_user_pages(), folio_mkclean() and
 * other calls that race to set up page table entries.
 */
```

一句话概括这个"高位/低位分离"方案：**低 10 位留给普通引用计数，第 10 位以上是 pin 计数**。这样 `cat /proc/kpagecount`（或内核调试时看 refcount）就能一眼看出"低位是普通引用、高位是 pin 次数"。

增量方向有个容易看错的细节。`try_grab_folio()`（慢路径，`mm/gup.c:140`）直接加满一个 BIAS：

```c
		if (folio_has_pincount(folio)) {
			folio_ref_add(folio, refs);
			atomic_add(refs, &folio->_pincount);
		} else {
			folio_ref_add(folio, refs * GUP_PIN_COUNTING_BIAS);
		}
```

而 `try_grab_folio_fast()`（`mm/gup.c:517`）加的是 `BIAS - 1`：

```c
	/*
	 * When pinning a large folio, use an exact count to track it.
	 *
	 * However, be sure to *also* increment the normal folio
	 * refcount field at least once, so that the folio really
	 * is pinned.  That's why the refcount from the earlier
	 * try_get_folio() is left intact.
	 */
	if (folio_has_pincount(folio))
		atomic_add(refs, &folio->_pincount);
	else
		folio_ref_add(folio,
				refs * (GUP_PIN_COUNTING_BIAS - 1));
	/*
	 * Adjust the pincount before re-checking the PTE for changes.
	 * This is essentially a smp_mb() and is paired with a memory
	 * barrier in folio_try_share_anon_rmap_*().
	 */
	smp_mb__after_atomic();
```

差 1 的原因在注释里：快路径前面已经调过 `try_get_folio()`，refcount 已经加了 1，所以再补 `BIAS - 1` 就凑够一个完整的 BIAS。**这是一个必须靠读代码才能发现的细节**——单看任一个函数都可能算错。

`smp_mb__after_atomic()` 也不可少：它保证 pincount 的更新对随后读 PTE 的代码可见，并与 `folio_try_share_anon_rmap_*()` 里的屏障配对——也就是前面 `gup_must_unshare()` 里那个 `smp_rmb()` 的对面。**"先加 pincount 再验证 PTE"这条顺序需要屏障来保证对其它 CPU 可见。**

### folio_maybe_dma_pinned

查询接口（`include/linux/mm.h:2662`）：

```c
static inline bool folio_maybe_dma_pinned(struct folio *folio)
{
	if (folio_has_pincount(folio))
		return atomic_read(&folio->_pincount) > 0;

	/*
	 * folio_ref_count() is signed. If that refcount overflows, then
	 * folio_ref_count() returns a negative value, and callers will avoid
	 * further incrementing the refcount.
	 *
	 * Here, for that overflow case, use the sign bit to count a little
	 * bit higher via unsigned math, and thus still get an accurate result.
	 */
	return ((unsigned int)folio_ref_count(folio)) >=
		GUP_PIN_COUNTING_BIAS;
}
```

函数名的 `maybe` 是认真的，注释把模糊的方向与容忍它的理由都写清了（`include/linux/mm.h:2637`）：

```c
/**
 * folio_maybe_dma_pinned - Report if a folio may be pinned for DMA.
 * @folio: The folio.
 *
 * This function checks if a folio has been pinned via a call to
 * a function in the pin_user_pages() family.
 *
 * For small folios, the return value is partially fuzzy: false is not fuzzy,
 * because it means "definitely not pinned for DMA", but true means "probably
 * pinned for DMA, but possibly a false positive due to having at least
 * GUP_PIN_COUNTING_BIAS worth of normal folio references".
 *
 * False positives are OK, because: a) it's unlikely for a folio to
 * get that many refcounts, and b) all the callers of this routine are
 * expected to be able to deal gracefully with a false positive.
 *
 * For most large folios, the result will be exactly correct. That's because
 * we have more tracking data available: the _pincount field is used
 * instead of the GUP_PIN_COUNTING_BIAS scheme.
 *
 * For more information, please see Documentation/core-api/pin_user_pages.rst.
 *
 * Return: True, if it is likely that the folio has been "dma-pinned".
 * False, if the folio is definitely not dma-pinned.
 */
```

三个结论：**false 绝不模糊**（refcount 不到 1024，必然没被 pin）；**true 可能误报**（普通引用也可能堆过 1024）；**误报是可接受的**，因为所有调用者都被要求"能优雅处理误报"——这正是前面那张"让路清单"里每一条都能 `return false` 提前跳过的设计依据。对大 folio 而言结果则是精确的，因为走的是 `_pincount` 而不是这套编码。

那个 `(unsigned int)` 强转也有讲究：refcount 是带符号的 `atomic_t`，溢出后会变负；转成无符号后符号位变成了最大的那一位，正好继续参与 `>= BIAS` 的比较，让溢出情况下依然给出正确的 `true`。

### The Special Treatment of the Zero Page

零页（`ZERO_PAGE`）是所有"读未写过匿名映射"共享的那一个只读页，用得太频繁，pin 它会让计数爆掉且毫无意义。所以它在多处被显式跳过：

```c
		/*
		 * Don't take a pin on the zero page - it's not going anywhere
		 * and it is used in a *lot* of places.
		 */
		if (is_zero_folio(folio))
			return 0;
```

（`mm/gup.c:152`，慢路径；快路径 `mm/gup.c:540` 有对应的 `is_zero_page()` 版本。）

对应地，释放时也不减计数（`mm/gup.c:102`）：

```c
static void gup_put_folio(struct folio *folio, int refs, unsigned int flags)
{
	if (flags & FOLL_PIN) {
		if (is_zero_folio(folio))
			return;
		node_stat_mod_folio(folio, NR_FOLL_PIN_RELEASED, refs);
		if (folio_has_pincount(folio))
			atomic_sub(refs, &folio->_pincount);
		else
			refs *= GUP_PIN_COUNTING_BIAS;
	}

	folio_put_refs(folio, refs);
}
```

注意这里的 `refs *= GUP_PIN_COUNTING_BIAS`：小 folio 释放时要把 `refs` 乘回一个 BIAS，与 grab 时的 `* BIAS` 对称。而**零页是唯一"抓时返回 0、放时直接 return"的例外**——抓和放都不记账，所以平衡。这也意味着零页永远不会显示为 pinned，`folio_maybe_dma_pinned()` 对它无意义。

## The Side Effect of Pin: Who Must Yield

pin 成立之后，mm 里多处路径都要先问一句"这页被 pin 了吗"。这是理解 pin 成本的另一半——**pin 不是一个孤立的计数，而是会向下传导到所有内存管理决策**。

### fork: Breaking COW Early

```c
static inline bool folio_needs_cow_for_dma(struct vm_area_struct *vma,
					  struct folio *folio)
{
	VM_BUG_ON(!(raw_read_seqcount(&vma->vm_mm->write_protect_seq) & 1));

	if (!mm_flags_test(MMF_HAS_PINNED, vma->vm_mm))
		return false;

	return folio_maybe_dma_pinned(folio);
}
```

（`include/linux/mm.h:2685`。）fork 时本来应该"写保护、延迟到写时再 COW"。但如果源进程里有 pin 过的页，且这个页恰好被 pin 了，就必须**立刻**把 COW 拆开——否则父子共享的页会一直保持共享状态，而 pin 的前提是"独占"。

`MMF_HAS_PINNED` 是个**宁可误报也不漏报**的优化位（`include/linux/mm_types.h:1965`）：

```c
/*
 * MMF_HAS_PINNED: Whether this mm has pinned any pages.  This can be either
 * replaced in the future by mm.pinned_vm when it becomes stable, or grow into
 * a counter on its own. We're aggresive on this bit for now: even if the
 * pinned pages were unpinned later on, we'll still keep this bit set for the
 * lifecycle of this mm, just for simplicity.
 */
#define MMF_HAS_PINNED		27	/* FOLL_PIN has run, never cleared */
```

**"never cleared"**——一旦这个 mm 执行过 FOLL_PIN，这个位就永远为 1。这样 fork 路径可以用一个廉价的位测试跳过绝大多数进程（`likely(!mm_flags_test(...))`），只在确实 pin 过的进程上才去逐页检查；代价是 pin 过又 unpin 的进程会继续"多检查"，但这个开销只落在真正用过 pin 的进程上。

### Migration: pin as a Stumbling Block

迁移需要独占页——内容搬走时，页表里所有指向它的 PTE 都要改写。但 pin 者手里拿的是**旧 PFN**，内核无法改写它。所以迁移代码会检查 `folio_maybe_dma_pinned()`，为真就放弃这次迁移。

这条约束解释了为什么 LD 说"pin 会让内存碎片化"：pin 的页无法迁移，也就无法归整。

### Reclaim: Multiple Protections

`folio_maybe_dma_pinned()` 为真时页不会被回收，这一层保护来自两处：refcount 本身（回收路径的 `folio_ref_count()` 检查）与显式的 pin 检查。这也是 pin 泄漏最直接的后果——**进程退出后，被 pin 的页依然留在内存里，直到驱动 unpin**。

### KSM: Pinned Pages Are Not Merged

如前所述，KSM 只合并 `PageAnonExclusive` 为假的页，而 pin 要求独占，两者互斥。

### soft-dirty / CRIU: Write Protection Skipped

这是最容易被忽略的一条。`fs/proc/task_mmu.c` 里的 `pte_is_pinned()`（`fs/proc/task_mmu.c:1687`）：

```c
static inline bool pte_is_pinned(struct vm_area_struct *vma, unsigned long addr, pte_t pte)
{
	struct folio *folio;

	if (!pte_write(pte))
		return false;
	if (!is_cow_mapping(vma->vm_flags))
		return false;
	if (likely(!mm_flags_test(MMF_HAS_PINNED, vma->vm_mm)))
		return false;
	folio = vm_normal_folio(vma, addr, pte);
	if (!folio)
		return false;
	return folio_maybe_dma_pinned(folio);
}
```

它在 `clear_soft_dirty()` 里被用来**跳过写保护**：

```c
	if (pte_present(ptent)) {
		pte_t old_pte;

		if (pte_is_pinned(vma, addr, ptent))
			return;
		old_pte = ptep_modify_prot_start(vma, addr, pte);
		ptent = pte_wprotect(old_pte);
		ptent = pte_clear_soft_dirty(ptent);
		ptep_modify_prot_commit(vma, addr, pte, old_pte, ptent);
	} else {
```

逻辑链是：soft-dirty 追踪的原理是**把 PTE 改成只读**，这样用户一写就触发缺页，缺页处理里把"脏"记下来。但如果这个页被 pin 了（比如正在做 DMA），写保护会让 DMA 写入走 COW 分裂——设备写的是老页，页表里换成了新页，两边分家。

**后果**：有 pin 的进程，soft-dirty 追踪不完整 → `CRIU` 这类依赖 soft-dirty 的检查点工具可能丢页。这是一个很实际的排障知识点：容器里跑 RDMA/GPU 负载时做检查点，要注意这个交互。

### Summary: The Yield List

| 路径 | 检查点 | 让路方式 |
|---|---|---|
| fork 拆 COW | `folio_needs_cow_for_dma()` | 立即拆，不等写时 |
| 页迁移 | `folio_maybe_dma_pinned()` | 放弃迁移 |
| 回收 | refcount + pin 检查 | 跳过这个页 |
| KSM 合并 | `PageAnonExclusive` | 不合并 |
| COW 分裂 | `gup_must_unshare()` | 反向：要求 GUP 先 unshare |
| soft-dirty 写保护 | `pte_is_pinned()` | 跳过写保护 |
| LONGTERM pin | `folio_is_longterm_pinnable()` | 迁移到合规 zone 后重试 |

## The Cost of LONGTERM

`FOLL_LONGTERM` 与普通 pin 的差别不在"pin 多久"，而在**落点合规**：声明长期持有之后，内核要求这个页所在的内存位置必须是"可以长期占着而不影响系统能力"的。

### folio_is_longterm_pinnable

```c
static inline bool folio_is_longterm_pinnable(struct folio *folio)
{
#ifdef CONFIG_CMA
	int mt = folio_migratetype(folio);

	if (mt == MIGRATE_CMA || mt == MIGRATE_ISOLATE)
		return false;
#endif
	/* The zero page can be "pinned" but gets special handling. */
	if (is_zero_folio(folio))
		return true;

	/* Coherent device memory must always allow eviction. */
	if (folio_is_device_coherent(folio))
		return false;

	/*
	 * Filesystems can only tolerate transient delays to truncate and
	 * hole-punch operations
	 */
	if (folio_is_fsdax(folio))
		return false;

	/* Otherwise, non-movable zone folios can be pinned. */
	return !folio_is_zone_movable(folio);
}
```

（`include/linux/mm.h:2720`。）四类拒绝，每一类都对应一个会被长期 pin 破坏的系统能力：

| 拒绝对象 | 为什么 |
|---|---|
| `MIGRATE_CMA` / `MIGRATE_ISOLATE` | CMA 区是给需要连续物理内存的设备预留的，被 pin 住就再也凑不出大块连续内存 |
| device coherent（设备内存） | 必须支持热拔，长期 pin 会让热拔等待无限期 |
| fsdax | 文件系统要能随时 truncate / hole-punch 收回块，见前面 `check_vma_flags()` 那条 `-EOPNOTSUPP` |
| `ZONE_MOVABLE` | 这个 zone 存在的目的就是**可迁移**（内存热插拔、动态内存），任何不可迁移的页都会让它名不副实 |

最后一行 `return !folio_is_zone_movable(folio)` 是总纲：**非 movable zone 的页才允许长期 pin**。

### Migration Retry Contract

落点不合规时，慢路径不是失败返回，而是"**迁移它，然后让调用者重来**"。契约写在 `check_and_migrate_movable_folios()` 的注释里（`mm/gup.c:2405`）：

```c
/*
 * Check whether all folios are *allowed* to be pinned indefinitely (long term).
 * Rather confusingly, all folios in the range are required to be pinned via
 * FOLL_PIN, before calling this routine.
 *
 * Return values:
 *
 * 0: if everything is OK and all folios in the range are allowed to be pinned,
 * then this routine leaves all folios pinned and returns zero for success.
 *
 * -EAGAIN: if any folios in the range are not allowed to be pinned, then this
 * routine will migrate those folios away, unpin all the folios in the range. If
 * migration of the entire set of folios succeeds, then -EAGAIN is returned. The
 * caller should re-pin the entire range with FOLL_PIN and then call this
 * routine again.
 *
 * -ENOMEM, or any other -errno: if an error *other* than -EAGAIN occurs, this
 * indicates a migration failure. The caller should give up, and propagate the
 * error back up the call stack. The caller does not need to unpin any folios in
 * that case, because this routine will do the unpinning.
 */
```

三个返回值的分工很清晰，注意 `-EAGAIN` 那条里的关键设计：**迁移会把整个范围的页全部 unpin，调用者必须从头重新 pin**。为什么要全 unpin 而不是只处理不合规的那几个？因为迁移过程中页的身份变了（PFN 换了），已经 pin 住的页里若有任何一个被迁移，pin 就失效了。全量重做是唯一能保证一致的做法。

代价也就清楚了：**长期 pin 一个 CMA 区的页，会反复触发迁移**。`collect_longterm_unpinnable_folios()`（`mm/gup.c:2265`）在迁移前还要处理 LRU 的麻烦——为了让 `folio_isolate_lru()` 成功，得先把页从 per-CPU 的 LRU 缓存里刷出来：

```c
		/*
		 * We drain not only to make the folio_isolate_lru() succeed,
		 * but also to remove any other folio references from LRU
		 * caches.
		 */
		if (drained == 0 && folio_may_be_lru_cached(folio) &&
				folio_ref_count(folio) !=
				folio_expected_ref_count(folio) + pin_refs) {
			lru_add_drain();
			drained = 1;
		}
		if (drained == 1 && folio_may_be_lru_cached(folio) &&
				folio_ref_count(folio) !=
				folio_expected_ref_count(folio) + pin_refs) {
			lru_add_drain_all();
			drained = 2;
		}
```

两级 drain（先本地、再全局）配合 refcount 的精确比对：`folio_expected_ref_count() + pin_refs` 是"如果只有 pin 这一个额外引用"时的期望值，不等就说明还有别的地方拿着引用（LRU 缓存、页表映射、PG_private 等），需要把 LRU 缓存清掉。**这是 Linux 内存管理里"要隔离一个页有多难"的一个具体样本**。

## Release

### The Unpin Family

| 接口 | 用途 |
|---|---|
| `unpin_user_page()` | 释放单页 |
| `unpin_user_pages()` | 释放一组页（内部按 folio 分组批量处理） |
| `unpin_user_pages_dirty_lock()` | 释放并标脏（GUP 写过的页） |
| `unpin_user_page_range_dirty_lock()` | 释放一段**物理连续**的范围并标脏 |
| `unpin_folio()` / `unpin_folios()` | `memfd_pin_folios()` 的配对释放 |

批量接口内部会做 folio 分组：一个数组里连续的多个 `struct page *` 如果属于同一个 folio，就一次性减计数，而不是逐页操作。`gup_folio_next()` / `gup_folio_range_next()` 就是这个分组的实现（`mm/gup.c:232`、`mm/gup.c:247`）。

### Race Analysis in unpin_user_pages_dirty_lock

为什么需要"释放并标脏"的专用接口？因为 GUP 调用者拿到的页可能被自己写过（比如驱动填充了用户缓冲），此时页表可能还是只读的、页也没标脏，需要有人补上。这中间的竞态分析很值得读（`mm/gup.c:284`）：

```c
	sanity_check_pinned_pages(pages, npages);
	for (i = 0; i < npages; i += nr) {
		folio = gup_folio_next(pages, npages, i, &nr);
		/*
		 * Checking PageDirty at this point may race with
		 * clear_page_dirty_for_io(), but that's OK. Two key
		 * cases:
		 *
		 * 1) This code sees the page as already dirty, so it
		 * skips the call to set_page_dirty(). That could happen
		 * because clear_page_dirty_for_io() called
		 * folio_mkclean(), followed by set_page_dirty().
		 * However, now the page is going to get written back,
		 * which meets the original intention of setting it
		 * dirty, so all is well: clear_page_dirty_for_io() goes
		 * on to call TestClearPageDirty(), and write the page
		 * back.
		 *
		 * 2) This code sees the page as clean, so it calls
		 * set_page_dirty(). The page stays dirty, despite being
		 * written back, so it gets written back again in the
		 * next writeback cycle. This is harmless.
		 */
		if (!folio_test_dirty(folio)) {
			folio_lock(folio);
			folio_mark_dirty(folio);
			folio_unlock(folio);
		}
		gup_put_folio(folio, nr, FOLL_PIN);
	}
```

两种竞态都被论证为"无害"：

1. **看到已脏 → 跳过**：可能是回写刚清完脏又被别人标脏，此时页即将被回写，符合本意；
2. **看到干净 → 标脏**：可能刚好与回写并发，页被多写一次盘，无害。

为什么标脏要拿 `folio_lock`？因为 `set_page_dirty()` 涉及 `address_space` 的脏页基数统计与 radix tree 标记，需要与回写路径互斥。这类"先判断、再拿锁、再标脏"的模式（判断时不上锁）就是靠上面这两条论证来保证安全的。

### sanity_check_pinned_pages

DEBUG_VM 配置下会做一组额外断言（`mm/gup.c:31`），核心是**匿名页必须 exclusive**：

```c
	/*
	 * We only pin anonymous pages if they are exclusive. Once pinned, we
	 * can no longer turn them possibly shared and PageAnonExclusive() will
	 * stick around until the page is freed.
```

这组检查在 fast GUP 之后也会主动调用一次（见前面 `gup_fast()` 的 `read_seqcount_retry` 分支），用来把"关中断窗口里发生的违规"尽早抓出来。

### Statistics

`/proc/vmstat` 里有两个全局计数（`mm/vmstat.c:1256`、`include/linux/mmzone.h:276`）：

| 字段 | 含义 |
|---|---|
| `nr_foll_pin_acquired` | 通过 `pin_user_page*()` / `FOLL_PIN` 抓取的次数 |
| `nr_foll_pin_released` | 通过 `unpin_user_page*()` 释放的次数 |

**这两个数不相等就说明有 pin 泄漏**，差值就是当前挂着的 pin 数量。这是排查"内存莫名不释放"时最直接的工具：

```bash
grep -E 'nr_foll_pin' /proc/vmstat
```

注意名字里是 `foll`（FOLL 的标志名）而不是 `pin`——照着 `pin` 去 grep 会一无所获。

## Special Mappings

### VM_IO / VM_PFNMAP / VM_MIXEDMAP

设备寄存器映射、`remap_pfn_range()` 建立的内存，背后没有 `struct page`（或者有 page 但不受内存管理），GUP 对它们的态度是分级拒绝：

| 映射类型 | GUP 行为 | 代码位置 |
|---|---|---|
| `VM_IO` / `VM_PFNMAP` | 直接 `-EFAULT` | `check_vma_flags()` 开头 |
| secretmem | 直接 `-EFAULT` | `check_vma_flags()` |
| PTE 存在但无 struct page（`pte_special`） | `-EEXIST`（慢路径） | `follow_pfn_pte()` |
| PCI P2PDMA | 需显式 `FOLL_PCI_P2PDMA` | `try_grab_folio()` |
| 零页 | 唯一的例外，放行且不计数 | `follow_page_pte()` |

`VM_MIXEDMAP` 特殊一点：允许 VMA 里混合普通页与特殊页，所以它**不被整体拒绝**，而是在逐页检查时按 PTE 是否 special 分别处理。

### pte_special and the Fast Path

`CONFIG_ARCH_HAS_PTE_SPECIAL` 决定快路径能不能处理 PTE 级映射（`mm/gup.c:2815`）。不支持这个配置的架构上，`gup_fast_pte_range()` 直接退化成返回 0：

```c
/*
 * If we can't determine whether or not a pte is special, then fail immediately
 * for ptes. Note, we can still pin HugeTLB and THP as these are guaranteed not
 * to be special.
 *
 * For a futex to be placed on a THP tail page, get_futex_key requires a
 * get_user_pages_fast_only implementation that can pin pages. Thus it's still
 * useful to have gup_fast_pmd_leaf even if we can't operate on ptes.
 */
```

注释里再次提到 futex——它是快路径最敏感的消费者，连"THP tail page 上放 futex"这种细节都要照顾到。

### hugetlb: Merged from a Standalone Path into the Generic Path

早期内核里 hugetlb 的 GUP 有一条完全独立的实现 `follow_hugetlb_page()`（在 `mm/hugetlb.c`）。**v7.2.7 里这个函数已经彻底不存在了**——全树 grep 无任何匹配，`__get_user_pages()` 里那个 `is_vm_hugetlb_page()` 分支也一并删掉了。hugetlb 现在统一走通用路径：它在 pmd 级就是叶子，于是 `follow_page_mask()` → `follow_pmd_mask()` → `follow_huge_pmd()` 自然覆盖了它。

`follow_huge_pmd()`（`mm/gup.c:701`）确实不区分 THP 与 hugetlb：

```c
static struct page *follow_huge_pmd(struct vm_area_struct *vma,
				    unsigned long addr, pmd_t *pmd,
				    unsigned int flags,
				    unsigned long *page_mask)
{
	struct mm_struct *mm = vma->vm_mm;
	pmd_t pmdval = *pmd;
	struct page *page;
	int ret;

	assert_spin_locked(pmd_lockptr(mm, pmd));

	page = pmd_page(pmdval);
	if ((flags & FOLL_WRITE) &&
	    !can_follow_write_pmd(pmdval, page, vma, flags))
		return NULL;

	/* Avoid dumping huge zero page */
	if ((flags & FOLL_DUMP) && is_huge_zero_pmd(pmdval))
		return ERR_PTR(-EFAULT);
	...
	page += (addr & ~HPAGE_PMD_MASK) >> PAGE_SHIFT;
	*page_mask = HPAGE_PMD_NR - 1;

	return page;
}
```

`pmd_trans_huge()` 只在 `FOLL_TOUCH` 的 dirty/young 处理里出现（包在 `CONFIG_TRANSPARENT_HUGEPAGE` 下），hugetlb 直接跳过——因为它不需要 dirty tracking。这一点在 `gup_fast_folio_allowed()` 里也有对应的提前放行（`mm/gup.c:2771`）：

```c
	/* hugetlb neither requires dirty-tracking nor can be secretmem. */
	if (folio_test_hugetlb(folio))
		return true;
```

唯一保留的 hugetlb 特判是 `check_vma_flags()` 里那条拒绝（`mm/gup.c:1216`）：

```c
	if ((gup_flags & FOLL_SPLIT_PMD) && is_vm_hugetlb_page(vma))
		return -EOPNOTSUPP;
```

原因很直白——**hugetlb 不能被拆分**。它的大小由预留的 hstate 决定，不是 THP 那种能拆回 4K 的大页，所以"先拆再返回页粒度 PTE"这个请求对它无意义。

顺带说，这也让 `page_mask` 的作用更清楚了：`follow_huge_pmd()` 返回的是 `*page_mask = HPAGE_PMD_NR - 1`，调用者据此知道"这一批连续的页表项共用同一个大页"，从而一次推进一整页而不是一页一页走。

## Observation and Troubleshooting

### Available Observation Points

| 观测点 | 内容 |
|---|---|
| `/proc/vmstat` 的 `nr_foll_pin_acquired` / `nr_foll_pin_released` | 全局 pin 获取/释放次数，差值即泄漏量 |
| `MMF_HAS_PINNED` | 只在内核里可查，可用 `crash` / `drgn` 读 `mm->flags` 的第 27 位 |
| `folio_maybe_dma_pinned()` | 内核调试接口，`crash` 里可调用 |
| `sanity_check_pinned_pages()` | 需 `CONFIG_DEBUG_VM`，违规时直接报错 |

**没有** `/proc/<pid>/status` 里的 "VmPin" 字段——不像 `VmLck` 有专门的 mlock 计数，pin 的**按进程**统计一直没有落地（`MMF_HAS_PINNED` 的注释里也提到"未来可能由 `mm.pinned_vm` 取代，或长成独立计数器"，但目前还只是一个位）。要按进程统计只能靠内核调试工具。

### Common Failure Modes

| 现象 | 可能原因 |
|---|---|
| 内存不释放、`slab` 与匿名页长期不降 | pin 泄漏：驱动/用户态忘了 unpin，页永远不可回收 |
| 进程退出后 RSS 归零但物理内存不降 | 同上——页的 refcount 还挂着 |
| `fork()` 变慢 | 该 mm 有 `MMF_HAS_PINNED`，fork 要逐页查 `folio_maybe_dma_pinned()` |
| CMA 分配失败 | 区里的页被长期 pin 住，凑不出连续内存 |
| 内存热插拔卡住 | `ZONE_MOVABLE` 的页被 pin，无法迁移 |
| CRIU 检查点丢页 | soft-dirty 写保护被 `pte_is_pinned()` 跳过 |
| `-EOPNOTSUPP` / `-EFAULT` | **不是 bug**：映射类型不允许 pin（fsdax、`VM_PFNMAP` 等） |
| RDMA 注册大缓冲时反复重试 | LONGTERM pin 触发迁移，`-EAGAIN` 后全量重做 |

### Related Configuration

| 配置 | 影响 |
|---|---|
| `CONFIG_HAVE_GUP_FAST` | 是否有 fast GUP（架构相关） |
| `CONFIG_ARCH_HAS_PTE_SPECIAL` | 快路径能否处理 PTE 级映射 |
| `CONFIG_MIGRATION` | 关掉则 LONGTERM 不迁移（`check_and_migrate_movable_pages()` 退化为返回 0） |
| `CONFIG_CMA` | 影响 `folio_is_longterm_pinnable()` 的 MIGRATE_CMA 检查 |
| `CONFIG_SECRETMEM` | 影响 `gup_fast_folio_allowed()` 的 secretmem 检查 |
| `CONFIG_DEBUG_VM` | 是否启用 `sanity_check_pinned_pages()` |
| `CONFIG_HAVE_ARCH_MAKE_FOLIO_ACCESSIBLE` | 机密计算下的 pin 前解密（目前只有 s390） |

## Interaction with Other Subsystems

**与页表（[pagetable.md](/docs/CS/OS/Linux/mm/pagetable.md)）**：fast GUP 是"无锁遍历页表"的第二个消费者，与 `pte_offset_map()` 的 RCU 方案并列。两者的关键差别是**用什么挡住页表页的释放**：RCU 只挡 RCU 回调那条路，而 fast GUP 要的是更强的"连 IPI 都收不到"，所以用 `local_irq_save()`。这也解释了 `mmu_gather` 为什么要把页表页释放推迟到 TLB flush 之后——它必须给 fast GUP 留出"关中断窗口"的安全边界。

**与缺页（[vm.md](/docs/CS/OS/Linux/mm/vm.md?id=page-fault)）**：GUP 不自己处理缺页，而是反复调用 `faultin_page()` 让缺页路径去做。但 GUP 引入了一个缺页侧没有的概念——`FAULT_FLAG_UNSHARE`：**只拆共享、不写**。这是 pin 语义独有的需求，普通缺页用不到。

**与回收（[Reclaim.md](/docs/CS/OS/Linux/mm/Reclaim.md)）**：pin 的页回收器碰不得，而 pin 泄漏的表现就是"回收怎么扫都扫不下来"。`folio_maybe_dma_pinned()` 是回收路径上的一道额外闸门。

**与 mmap / mlock（[mmap.md](/docs/CS/OS/Linux/mm/mmap.md)）**：`mlock()` 与 `MADV_POPULATE_READ` 内部都走 GUP 的 `populate_vma_page_range()`，只是不带 `FOLL_PIN`——它们要的是"页先到位"，不是"把页交给外部"。这个区别体现为 `FOLL_TOUCH`（要预读、要标记 accessed）与 `FOLL_PIN` 的不同组合。

**与 KVM（[KVM.md](/docs/CS/OS/Linux/KVM.md)）**：guest 内存的 HVA→PFN 翻译走 `get_user_pages()`，所以 guest 的"物理内存"实际是 QEMU 进程的普通匿名页，同样受换出/回收/THP 影响。KVM 的 `hva_to_pfn()` 没有用 `FOLL_LONGTERM`，这正是"guest 内存可以被 host 换出"的实现依据。

**与零拷贝 I/O（[io_uring](/docs/CS/OS/Linux/IO/io_uring.md)）**：`IORING_REGISTER_BUFFERS` 用 `pin_user_pages` 把缓冲长期 pin 住（配 `FOLL_LONGTERM`），换来每次 I/O 不再重复 pin/unpin。它的坑也来自 LONGTERM 的落点检查：注册的缓冲如果落在 CMA / ZONE_MOVABLE 上，会触发迁移重试。

**与 RDMA**：`ib_umem_get()` 是 `pin_user_pages` 的最大用户，也是整个 pin 机制的起源——2018 年那轮重构就是为了修 RDMA 在文件映射内存上做 DMA 触发的 `BUG_ON(!PagePrivate(page))`。

## Links

- [页表](/docs/CS/OS/Linux/mm/pagetable.md)
- [虚拟内存](/docs/CS/OS/Linux/mm/vm.md)
- [mmap](/docs/CS/OS/Linux/mm/mmap.md)
- [内存回收](/docs/CS/OS/Linux/mm/Reclaim.md)
- [KVM](/docs/CS/OS/Linux/KVM.md)
- [io_uring](/docs/CS/OS/Linux/IO/io_uring.md)

## References

- [pin_user_pages() and related calls](https://docs.kernel.org/core-api/pin_user_pages.html)
- [The Trouble with get_user_pages()](https://lwn.net/Articles/753027/)
- [DMA and get_user_pages()](https://lwn.net/Articles/774411/)
