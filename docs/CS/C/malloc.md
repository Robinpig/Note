## Introduction

`malloc` 是 C 程序在堆上申请内存的标准接口，但它**不是一个系统调用**——内核根本不认识 `malloc`。它是 libc（Linux 上主要是 glibc，其分配器叫 **ptmalloc**）在用户态实现的一层"堆管理器"。理解 malloc 的关键是建立分层意识：

```
应用程序
  |  malloc / free        ← 用户态接口（libc）
ptmalloc：chunk / arena / bin，缓存与切分
  |  brk / mmap           ← 真正的系统调用（内核）
Linux 内核：VMA、缺页、物理页分配
```

内核只负责把一整段虚拟内存区域（VMA）交给进程，并**不立即分配物理页**；ptmalloc 则把从内核批量拿到的大段内存，切成应用想要的各种小块、缓存复用，避免每次申请都陷入内核。本页沿这条链路自上而下展开：先看堆块 chunk 的真实结构，再看 arena 与各种 bin 如何组织空闲块，然后是 malloc/free 的完整流程、`brk` 与 `mmap` 两条取内存路径，最后分析著名的"内存站岗"问题与分配器选型。

## chunk: The Smallest Unit of the Heap

ptmalloc 管理的每个块都是一个 `malloc_chunk`（glibc `malloc/malloc.c`）。注意**返回给用户的指针并不指向 chunk 开头**，而是跳过头部两个字段：

```c
struct malloc_chunk {

  INTERNAL_SIZE_T      mchunk_prev_size;  /* Size of previous chunk (if free).  */
  INTERNAL_SIZE_T      mchunk_size;       /* Size in bytes, including overhead. */

  struct malloc_chunk* fd;         /* double links -- used only if free. */
  struct malloc_chunk* bk;

  /* Only used for large blocks: pointer to next larger size.  */
  struct malloc_chunk* fd_nextsize; /* double links -- used only if free. */
  struct malloc_chunk* bk_nextsize;
};
```

- `mchunk_size` 记录整个 chunk 的大小（含头部），它的**低 3 位被借用作标志位**——因为 chunk 总是按 16 字节对齐，低 3 位恒为 0，可以复用：

```c
#define PREV_INUSE 0x1
#define IS_MMAPPED 0x2
#define NON_MAIN_ARENA 0x4
```

- **P（PREV_INUSE）**：前一个 chunk 是否在使用；**M（IS_MMAPPED）**：这个 chunk 是否由 mmap 单独取得；**A（NON_MAIN_ARENA）**：是否属于非主 arena。
- `fd` / `bk` 只在 chunk 空闲时有意义，用来把空闲块串进双向链表；块被分配后这块区域就归用户当数据用——这是 ptmalloc 省内存的手法：**空闲元数据复用用户数据区**。

这种"前后都记录大小和状态"的设计叫 **boundary tag（边界标签）**：空闲块的大小既存在块头、也隐式存在相邻块的 `mchunk_prev_size` 里，因此 free 时能 O(1) 找到前后相邻块并立即合并，无需遍历。

## arena: Allocation Arena and Multithreading

为了多线程下不被一把全局锁卡死，ptmalloc 引入 **arena（分配区）**。每个 arena 是一套独立的堆管理结构 + 锁，即 `struct malloc_state`：

```c
struct malloc_state
{
  /* Serialize access.  */
  __libc_lock_define (, mutex);
  int flags;
  int have_fastchunks;

  /* Fastbins */
  mfastbinptr fastbinsY[NFASTBINS];

  /* Base of the topmost chunk -- not otherwise kept in a bin */
  mchunkptr top;

  /* The remainder from the most recent split of a small request */
  mchunkptr last_remainder;

  /* Normal bins packed as described above */
  mchunkptr bins[NBINS * 2 - 2];

  /* Bitmap of bins */
  unsigned int binmap[BINMAPSIZE];

  struct malloc_state *next;
  struct malloc_state *next_free;
  INTERNAL_SIZE_T attached_threads;

  INTERNAL_SIZE_T system_mem;
  INTERNAL_SIZE_T max_system_mem;
};
```

- **main arena（主分配区）**：只有一个，用 `brk` 扩展堆，其空闲块顶端就是 `top` chunk；
- **non-main arena（非主分配区）**：按需创建，用一个或多个 `mmap` 出来的 heap 模拟主分配区；
- 线程数超过 arena 数时会复用 arena——arena 数量上限大约是 `8 × CPU 核数`（64 位），并不是"一线程一 arena"。

`top` chunk 是 arena 里最顶层的大块空闲区，**不属于任何 bin**：所有 bin 都没有合适块时就切 top，top 不够才向内核要内存。

## bin: Classified Cache of Free Blocks

free 回来的块不是立即还给内核，而是按大小放进不同的 **bin（空闲链表）**，malloc 时优先从这里取。从 glibc 2.26 起还增加了每线程的 tcache。按速度和大小分几层：

| 类型 | 大小范围 | 组织方式 | 特点 |
| --- | --- | --- | --- |
| **tcache** | 小块，64 个档 | 每线程、单链表 | 2.26+，无锁，最先查 |
| **fast bin** | ≤ 128B（64 位，`DEFAULT_MXFAST`） | 单链表，每档一条 | 不合并、最快，临时缓存 |
| **unsorted bin** | 各种大小 | 一个双向链表 | 释放块的"中转站"，先放这里 |
| **small bin** | < 1024B | 双向链表，64 档 | 同档等大，精确匹配 |
| **large bin** | ≥ 1024B | 双向链表 + nextsize 链 | 同档不等大，按尺寸排序 |

关键常量都在 `malloc.c` 中：

```c
#define DEFAULT_MXFAST     (64 * SIZE_SZ / 4)
#define DEFAULT_TRIM_THRESHOLD (128 * 1024)
#define DEFAULT_MMAP_THRESHOLD_MIN (128 * 1024)
#define DEFAULT_MMAP_THRESHOLD DEFAULT_MMAP_THRESHOLD_MIN
#define TCACHE_MAX_BINS        64
#define NBINS             128
#define NSMALLBINS         64
```

free 的块先进 unsorted bin，malloc 时若在 unsorted bin 没被用掉，ptmalloc 会在适当时候把它们整理（sort）进 small/large bin；fast bin 为了高频小块不立即合并，只在堆需要大块、触发 malloc_consolidate 时才统一合并。

## malloc Flow

一次 `malloc(n)` 的查找顺序，命中任意一步即返回：

1. 把请求大小 n 加上头部、向上对齐成 chunk size（`request2size`）；
2. 取（或等待分配）一个 arena 并加锁；
3. **tcache**：按尺寸档查本线程 tcache，命中直接弹出；
4. **fast bin / small bin**：精确尺寸档命中即用；
5. 否则把 **unsorted bin** 里的块逐个取出：恰好满足就返回，其余边整理进 small/large bin；
6. 查 **large bin**（用 binmap 快速定位非空档），可对较大块做切分；
7. 仍没有 → 切 **top chunk**，把大块切一块、剩一块作为新的 last_remainder；
8. top 也不够 → 经 `sysmalloc` 用 **brk 或 mmap 向内核要新内存**，再切。

分配 chunk 时会设置 `mchunk_size`、按需清 P 位，返回 chunk 开头 + 2 个字长处的地址给用户。

## free Flow and Coalescing

`free(p)` 时先由用户指针减头部偏移还原 chunk，读出大小与标志：

1. **mmap 来的大块**（M 位）直接 `munmap` 还给内核；
2. 小且满足条件 → 放进 **tcache**；很小的块放进 **fast bin**，**暂不合并**；
3. 其余块放进 **unsorted bin**，同时检查物理相邻块：
   - 前一块空闲（P 位为 0）→ 用 `mchunk_prev_size` 找到并向前合并；
   - 后一块空闲 → 向后合并；
   - 后一块是 top → 直接并入 top；
4. 合并靠 boundary tag 在 O(1) 完成，目的是抑制外部碎片。

## brk and mmap: Two Ways to Request Memory from the Kernel

ptmalloc 向内核取内存只有两种方式，分界是 **mmap threshold，默认 128KB**：

- **小块（默认主 arena）走 `brk`**：移动程序堆段的 program break。内核 `brk` 系统调用（`mm/mmap.c`）本质是扩展/收缩一段以 `start_brk` 起始的 VMA：

```c
SYSCALL_DEFINE1(brk, unsigned long, brk)
{
	unsigned long newbrk, oldbrk, origbrk;
    ...
	newbrk = PAGE_ALIGN(brk);
	oldbrk = PAGE_ALIGN(mm->brk);
    ...
	if (do_brk_flags(&vmi, brkvma, oldbrk, newbrk - oldbrk, 0) < 0) {
    ...
	mm->brk = brk;
    ...
}
```

注意内核按**页**对齐、只扩展 VMA，**此时并不分配物理页**——真正物理页要等进程第一次写时由缺页（demand paging）分配。
- **大块（≥ 128KB）或非主 arena 走 `mmap`**：直接映射一段独立匿名内存，释放时可整体 `munmap`，不必经过堆段。

动态阈值机制：如果大块频繁申请释放，ptmalloc 会**动态调高** mmap threshold（最高到 `DEFAULT_MMAP_THRESHOLD_MAX`，64 位 32MB），让更多块改走 brk 堆以复用。

## Memory Hoarding (Heap Not Returned)

ptmalloc 的设计目标是服务**短生命周期**的分配，它什么时候把内存还给内核？默认规则是：当 **top chunk 超过 trim threshold（128KB）** 才把 top 的一部分还给内核。这就引出了实际工程中常见的 [glibc 内存站岗](/docs/CS/C/glibc.md)问题：

> 如果释放的空闲块**没有与 top 相邻**——中间隔着仍在使用的块——它们就无法并入 top，即使累计空闲达几十 GB，也无法归还内核。进程的 RSS 居高不下。

这不是 bug，而是边界标签合并规则与"只从 top 归还"策略的直接结果。常见应对：

- 用 `malloc_trim` 主动归还；
- 避免持有夹在中间的长生命周期小块、或把它们迁出主堆；
- 直接换用 **jemalloc / tcmalloc**，它们以更小的 span 为单位管理，站岗概率和粒度都小得多。

## Allocator Selection: ptmalloc / jemalloc / tcmalloc

| 维度 | ptmalloc (glibc) | jemalloc | tcmalloc (gperftools) |
| --- | --- | --- | --- |
| 多线程 | 多 arena，arena 内加锁 | arena + thread cache | thread cache + central heap |
| 碎片控制 | 中（站岗问题明显） | 强，重点优化碎片 | 较强 |
| 规模来源 | 多分配区 | 多级 size class | 小 span + 线程缓存 |
| 典型场景 | 默认、通用 | FreeBSD / Redis / 浏览器 / Facebook | Google 系、很多服务后端 |
| 特色工具 | malloc_trim / mallinfo | heap profiling、监控钩子 | heap profiler |

[jemalloc](/docs/CS/memory/jemalloc.md) 同样按申请大小把分配分成 small / large / huge，并针对 false sharing 做优化；选型时碎片敏感、长期运行的服务更倾向 jemalloc/tcmalloc，简单通用场景用默认 ptmalloc 即可。

## Interaction with Other Subsystems

- **虚拟内存**：malloc 拿到的是 [vm](/docs/CS/OS/Linux/mm/vm.md) 里的匿名 VMA，物理页经缺页才分配。
- **mmap**：大块与文件映射的机制见 [mmap](/docs/CS/OS/Linux/mm/mmap.md)。
- **物理分配**：缺页最终落到 [buddy/slab](/docs/CS/OS/Linux/mm/README.md)。
- **语言运行时**：Java 的 [Direct Buffer](/docs/CS/Java/JDK/IO/Direct_Buffer.md)、Go 的 [memory](/docs/CS/Go/memory.md)、Netty 的 [堆外内存](/docs/CS/Framework/Netty/memory.md)都建立在同一套 mmap/分配原语之上。

## Links

- [C](/docs/CS/C/C.md)
- [glibc 内存站岗](/docs/CS/C/glibc.md)
- [jemalloc](/docs/CS/memory/jemalloc.md)
- [vm 虚拟内存](/docs/CS/OS/Linux/mm/vm.md)
- [mmap](/docs/CS/OS/Linux/mm/mmap.md)
- [Memory](/docs/CS/Python/Memory.md)

## References

1. [glibc: malloc/malloc.c — sourceware.org](https://sourceware.org/git/?p=glibc.git;a=blob;f=malloc/malloc.c)
2. [MallocInternals — glibc wiki](https://sourceware.org/glibc/wiki/MallocInternals)
3. [A Scalable Concurrent malloc(3) Implementation for FreeBSD](https://people.freebsd.org/~jasone/jemalloc/bsdcan2006/jemalloc.pdf)
