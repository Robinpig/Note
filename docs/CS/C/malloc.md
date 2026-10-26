## Introduction

`malloc` 是 C 程序在堆上申请内存的标准接口，但它**不是一个系统调用**——内核根本不认识 `malloc`。它是 libc（Linux 上主要是 glibc，其分配器叫 **ptmalloc**）在用户态实现的一层"堆管理器"。理解 malloc 的关键是建立分层意识：

```
应用程序
  |  malloc / free        ← 用户态接口（libc）
ptmalloc：tcache / chunk / arena / bin，缓存与切分
  |  brk / mmap           ← 真正的系统调用（内核）
Linux 内核：VMA、缺页、物理页分配
```

内核只负责把一整段虚拟内存区域（VMA）交给进程，并**不立即分配物理页**；ptmalloc 则把从内核批量拿到的大段内存，切成应用想要的各种小块、缓存复用，避免每次申请都陷入内核。本页沿这条链路自上而下展开：先看堆块 chunk 的真实结构，再看 arena 与各种 bin 如何组织空闲块，然后是 tcache、malloc/free 的完整流程、`brk` 与 `mmap` 两条取内存路径、安全加固，最后分析"内存站岗"问题、调优接口与分配器选型。

本篇基线是 glibc `2.42`，`路径:行号` 一律相对 glibc 仓库根，可回 tag `glibc-2.42` 复核。

## chunk: The Smallest Unit of the Heap

ptmalloc 管理的每个块都是一个 `malloc_chunk`（`malloc/malloc.c:1144-1155`）。注意**返回给用户的指针并不指向 chunk 开头**，而是跳过头部两个字长：

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

- `mchunk_size` 记录整个 chunk 的大小（含头部），它的**低 3 位被借用作标志位**——因为 chunk 总是按 16 字节对齐，低 3 位恒为 0，可以复用（`malloc/malloc.c:1362-1379`）：

```c
#define PREV_INUSE 0x1
#define IS_MMAPPED 0x2
#define NON_MAIN_ARENA 0x4
```

- **P（PREV_INUSE）**：前一个 chunk 是否在使用；**M（IS_MMAPPED）**：这个 chunk 是否由 mmap 单独取得；**A（NON_MAIN_ARENA）**：是否属于非主 arena。
- `fd` / `bk` 只在 chunk 空闲时有意义，用来把空闲块串进双向链表；块被分配后这块区域就归用户当数据用——这是 ptmalloc 省内存的手法：**空闲元数据复用用户数据区**。tcache 更进一步，在用户区头 16 字节里同时放 `next` 和检测重复释放的 `key`（`malloc/malloc.c:3114-3119`）。

这种"前后都记录大小和状态"的设计叫 **boundary tag（边界标签）**：空闲块的大小既存在块头、也隐式存在相邻块的 `mchunk_prev_size` 里，因此 free 时能 O(1) 找到前后相邻块并立即合并，无需遍历。

尺寸口径值得单独记清楚，因为三个名字经常被混用：

| 符号 | 含义 | 64 位取值 |
| :--- | :--- | :--- |
| `SIZE_SZ` | 一个指针的字节数 | 8 |
| `CHUNK_HDR_SZ` | `2 * SIZE_SZ`，chunk 头长度 | 16 |
| `MALLOC_ALIGNMENT` | 用户指针对齐 | 16 |
| `MINSIZE` | 最小的 chunk 大小 | 32 |

`request2size` 把请求补成 chunk 大小（`malloc/malloc.c:1319-1322`）：

```c
#define request2size(req)                                         \
  (((req) + SIZE_SZ + MALLOC_ALIGN_MASK < MINSIZE)  ?             \
   MINSIZE :                                                      \
   ((req) + SIZE_SZ + MALLOC_ALIGN_MASK) & ~MALLOC_ALIGN_MASK)
```

也就是说 64 位上一个 1 字节的请求也会拿到 `MINSIZE = 32` 字节的 chunk，用户可见 24 字节。**"申请 41 字节给几个字节"的答案永远是 16 的倍数加 16**，没有更细的尺寸类——这正是它与 [jemalloc 的 size class 代数](/docs/CS/memory/jemalloc/Size_Classes.md)最大的结构差异。另外 `checked_request2size` 在换算前先拒绝大于 `PTRDIFF_MAX` 的请求（`malloc/malloc.c:1334-1335`），避免补对齐时溢出。

## arena: Allocation Arena and Multithreading

为了多线程下不被一把全局锁卡死，ptmalloc 引入 **arena（分配区）**。每个 arena 是一套独立的堆管理结构 + 锁，即 `struct malloc_state`（`malloc/malloc.c:1820-1862`）：

```c
struct malloc_state
{
  /* Serialize access.  */
  __libc_lock_define (, mutex);

  /* Flags (formerly in max_fast).  */
  int flags;

  /* Set if the fastbin chunks contain recently inserted free blocks.  */
  /* Note this is a bool but not all targets support atomics on booleans.  */
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

  /* Linked list */
  struct malloc_state *next;

  /* Linked list for free arenas.  Access to this field is serialized
     by free_list_lock in arena.c.  */
  struct malloc_state *next_free;

  /* Number of threads attached to this arena.  0 if the arena is on
     the free list.  Access to this field is serialized by
     free_list_lock in arena.c.  */
  INTERNAL_SIZE_T attached_threads;

  /* Memory allocated from the system in this arena.  */
  INTERNAL_SIZE_T system_mem;
  INTERNAL_SIZE_T max_system_mem;
};
```

- **main arena（主分配区）**：只有一个，用 `brk` 扩展堆，其空闲块顶端就是 `top` chunk；
- **non-main arena（非主分配区）**：按需创建，用一个或多个 `mmap` 出来的 heap 模拟主分配区。

线程与 arena 的关系比"一线程一 arena"更省：

1. 每个线程有一个 TLS 指针 `thread_arena`（`malloc/arena.c:89`）。分配时 `arena_get` 直接锁这个 arena，不做任何扫描（`malloc/arena.c:127-137`）。
2. 只有 `thread_arena` 还是 `NULL`（线程首次分配，或线程退出清理之后）时，才走 `arena_get2`：先看 free list，再决定新建还是复用（`malloc/arena.c:802-849`）。
3. 复用由 `reused_arena` 完成：从 `next_to_use` 开始轮转 trylock，全忙时阻塞在下一个 arena 上；选中后 `attached_threads` 加一（`malloc/arena.c:741-799`）。
4. 线程退出时把 arena 放回 free list，`attached_threads` 归零。**一个线程在生命周期内不会因为锁竞争而迁移 arena**——迁移只会发生在线程销毁或首次分配这两处。

数量上限不是"CPU 核数"，而是分两段决定（`malloc/malloc.c:1929`、`malloc/arena.c:812-846`）：先允许创建 `arena_test` 个 arena（64 位默认 8，即 `NARENAS_FROM_NCORES(1)`）；超过之后才按 `NARENAS_FROM_NCORES(核数)` 算出上限，64 位是 **8 × 核数**、32 位是 **2 × 核数**。`glibc.malloc.arena_max` 一旦设置，就直接取代这个公式。

非主 arena 的 heap 有两个约束（`malloc/arena.c:28-32`、`malloc/arena.c:141-151`）：每个 heap 最大 `HEAP_MAX_SIZE = 2 * DEFAULT_MMAP_THRESHOLD_MAX`（64 位上是 64 MiB），且地址按这个值对齐。于是 `arena_for_chunk` 只需看 A 位，再用 `heap_for_ptr` 向下对齐就能找到 heap 头：

```c
static __always_inline struct malloc_state *
arena_for_chunk (mchunkptr ptr)
{
  return chunk_main_arena (ptr) ? &main_arena : heap_for_ptr (ptr)->ar_ptr;
}
```

这也解释了跨线程释放：`free(p)` 不看当前线程绑定了哪个 arena，而是由 `p` 自己（A 位 + heap 地址）决定要锁哪一把。

`top` chunk 是 arena 里最顶层的大块空闲区，**不属于任何 bin**：所有 bin 都没有合适块时就切 top，top 不够才向内核要内存。

## bin: Classified Cache of Free Blocks

free 回来的块不是立即还给内核，而是按大小放进不同的 **bin（空闲链表）**，malloc 时优先从这里取。从 glibc 2.26 起还增加了每线程的 tcache。按速度和大小的层次：

| 类型 | 尺寸（chunk 字节） | 组织方式 | 特点 |
| --- | --- | --- | --- |
| **tcache** | 默认 ≤ 1024 | 每线程、单链表数组 | 2.26+，不加 arena 锁，最先查 |
| **fast bin** | ≤ 128（`DEFAULT_MXFAST`） | 单链表数组，10 档 | 不合并、最快，临时缓存 |
| **unsorted bin** | 各种大小 | 一个双向循环链表（bin 1） | 释放块的"中转站"，先放这里 |
| **small bin** | < 1024 | 双向循环链表，每档等大 | 精确匹配 |
| **large bin** | ≥ 1024 | 双向链表 + `fd_nextsize` 链 | 同档不等大，按尺寸排序 |

关键常量与索引函数都在 `malloc.c` 中（`malloc/malloc.c:842`、`:1566-1577`、`:1598-1609`、`:1707`、`:1737-1744`）：

```c
#define DEFAULT_MXFAST     (64 * SIZE_SZ / 4)

#define NBINS             128
#define NSMALLBINS         64
#define SMALLBIN_WIDTH    MALLOC_ALIGNMENT
#define SMALLBIN_CORRECTION (MALLOC_ALIGNMENT > CHUNK_HDR_SZ)
#define MIN_LARGE_SIZE    ((NSMALLBINS - SMALLBIN_CORRECTION) * SMALLBIN_WIDTH)

#define BINMAPSIZE       (NBINS / BITSPERMAP)
```

- `NBINS = 128` 里 bin 0 不用、bin 1 固定是 unsorted；64 位下 `SMALLBIN_CORRECTION == 0`，所以 small/large 的分界正好是 `64 * 16 = 1024`。
- `binmap` 是"哪些 bin 非空"的四级位图，查 large bin 时用 `mark_bin` / `unmark_bin` / `get_binmap` 直接跳到非空档（`malloc/malloc.c:1697-1714`），不必逐档遍历。
- fastbin 的档位由 `fastbin_index` 用移位算出（`:1737-1738`），默认上限 `DEFAULT_MXFAST` 是 128 字节的 chunk，`MAX_FAST_SIZE` 允许调到 160（`:1742-1744`）；`malloc_init_state` 在初始化时写死 `set_max_fast (DEFAULT_MXFAST)`（`:1965`）。

free 的块先进 unsorted bin，malloc 时若在 unsorted bin 没被用掉，ptmalloc 会在适当时候把它们整理（sort）进 small/large bin；fast bin 为了高频小块不立即合并，只在堆需要大块、触发 `malloc_consolidate` 时才统一合并。

## tcache: Small Bins, Large Bins and a Key

tcache 是每条线程私有的缓存，结构只有两行数组（`malloc/malloc.c:3127-3134`）：

```c
typedef struct tcache_perthread_struct
{
  uint16_t num_slots[TCACHE_MAX_BINS];
  tcache_entry *entries[TCACHE_MAX_BINS];
} tcache_perthread_struct;

static __thread bool tcache_shutting_down = false;
static __thread tcache_perthread_struct *tcache = NULL;
```

两个字段的语义容易读反：`entries` 是链表头，`num_slots` 记的是**还能再放几个**，不是已经放了几个——放一个减一、取一个加一（`malloc/malloc.c:3193`、`:3217`），初始值统一写成 `mp_.tcache_count`（`:3397`）。注释直接点明 "can be disabled by initializing 'num_slots' to zero"（`:3123-3126`）。

档位不是"64 档"这么简单（`malloc/malloc.c:293-297`）：

```c
# define TCACHE_SMALL_BINS		64
# define TCACHE_LARGE_BINS		12 /* Up to 4M chunks */
# define TCACHE_MAX_BINS	(TCACHE_SMALL_BINS + TCACHE_LARGE_BINS)
# define MAX_TCACHE_SMALL_SIZE	tidx2usize (TCACHE_SMALL_BINS-1)
```

- 前 64 档按 16 字节等距覆盖小块，`csize2tidx(x) = (x - MINSIZE) / MALLOC_ALIGNMENT`（`:303`）。
- 后 12 档按 2 的幂粗分大块，`large_csize2tidx` 用 `__builtin_clz` 算索引（`:3163-3170`），桶内按大小**升序**排列，取的时候线性找到第一个够大的（`tcache_location_large`，`:3235-3249`）。
- 默认 `mp_.tcache_max_bytes = MAX_TCACHE_SMALL_SIZE`（`:1935`），即默认不启用后面 12 个大对象档；把 `glibc.malloc.tcache_max` 调大才会启用（`do_set_tcache_max`，`:5588-5612`）。
- 每档默认最多 7 个（`TCACHE_FILL_COUNT`，`:315`），上限 65535（`MAX_TCACHE_COUNT`，`:319`）。

tcache 的值不在"存得多"，而在**命中时完全不用锁 arena**：`__libc_malloc` 先查 tcache，命中就直接返回（`malloc/malloc.c:3464-3492`），只有不命中才进入 `arena_get`。这是 ptmalloc 在 2.26 之后最重要的一次性能改造。此外还有两处细节：

- **预填**：不命中后进入 `_int_malloc`，从 fastbin / smallbin / unsorted 取块时会把多余的块批量塞进 tcache（`:4055-4076`、`:4115-4133`、`:4259-4261`），所以第一次 miss 往往顺带把缓存填满。
- **线程退出时归还**：`tcache_thread_shutdown` 把全部缓存块 `__libc_free` 回 arena 并释放 tcache 自身（`:3345-3375`），避免线程结束后的内存滞留。

最后是一个安全设计：chunk 放进 tcache 时会在用户区写一个进程级随机数 `tcache_key`（`:3136-3161`），`free` 时若发现 `e->key == tcache_key`，说明这个地址**可能**已经在某个 tcache 里，于是进入慢速的全档扫描确认（`:3318-3343`）。它不是完整的重复释放检测：跨线程的重复释放、以及 key 被用户数据恰好撞上的情况都不覆盖，源码注释对此写得很直白（`:3139-3147`）。

## malloc Flow

`malloc(n)` 可以拆成两层：**外层只看 tcache**，**内层 `_int_malloc` 才碰 arena**。

外层（`malloc/malloc.c:3464-3496`）：

1. `checked_request2size` 把 `n` 换算成 chunk 大小 `nb`，溢出或超过 `PTRDIFF_MAX` 直接返回 NULL；
2. `nb < tcache_max_bytes` 时按档查本线程 tcache，命中即弹出——**这一步不取任何 arena 锁**；
3. 不命中才进 `__libc_malloc2`：`arena_get` 锁住本线程的 arena，调 `_int_malloc`；失败且拿到过 arena 时，用 `arena_get_retry` 换一个 arena 再试一次（`:3441-3451`）。

内层 `_int_malloc`（`malloc/malloc.c:3961` 起）按以下顺序找块，命中任意一步即返回：

1. `nb <= get_max_fast()`：查对应 fast bin，从链表头摘一个（`:4030`）；
2. small bin 范围：查精确尺寸档，同档多余的块顺带塞进 tcache（`:4095-4141`）；
3. 请求属于 large bin 时，若 arena 有未合并的 fastbin（`have_fastchunks`），先 `malloc_consolidate` 把它们合并进 normal bin（`:4155-4160`）——small 请求不走这一步；
4. **unsorted bin**：从尾部逐个取出，恰好满足就返回，其余边整理进 small/large bin；tcache 有空间时顺带填充（`:4182-4360`）；
5. 查 **large bin**：用 binmap 快速定位非空档，找最小的够用块，必要时切分（`:4454-4519`）；
6. 仍没有 → 切 **top chunk**，剩下一块作为新的 last_remainder（`:4564-4583`）；
7. top 也不够 → 经 `sysmalloc` 用 **brk 或 mmap 向内核要新内存**，再切（`:4602`）。

分配 chunk 时会设置 `mchunk_size`、按需清 P 位，返回 chunk 开头 + 2 个字长处的地址给用户。

`calloc` 走同一套路径，但多一步清零：tcache 命中时按档清零，`_int_malloc` 拿到的块若是 mmap 来的或刚由 sbrk 扩展出来的 top，则可以跳过清零（`malloc/malloc.c:3881-3899`、`:3902-3953`）。

## free Flow and Coalescing

`free(p)` 先用 `mem2chunk` 把用户指针减 16 字节还原成 chunk，读出大小与标志（`malloc/malloc.c:3500-3517`），然后：

1. **tcache**：`size < tcache_max_bytes` 且本线程有 tcache 时，先做 key 检查，再看 `num_slots` 是否有空位，有就直接挂进 tcache（`:3524-3548`）——**这一步同样不锁 arena**；
2. 剩下的交给 `_int_free_chunk`（`:4618`）：
   - chunk 大小 ≤ max_fast → 进 **fast bin**，**暂不合并**，链接时对 `fd` 做 safe-linking（`:4627-4688`）；
   - **mmap 来的大块**（M 位）→ 先看是否需要动态调高 mmap/threshold，然后 `munmap_chunk` 直接还给内核（`:4725-4745`）；
   - 其余块加 arena 锁后进入合并（`:4702-4720`）：前一块空闲（P 位为 0）就用 `mchunk_prev_size` 向前合并，后一块空闲就向后合并，后一块是 top 就直接并入 top（`_int_free_merge_chunk`，`:4751` 起）；
3. 合并完成后，如果这次释放的 chunk 本身 **≥ `FASTBIN_CONSOLIDATION_THRESHOLD`（64 KiB）**，才触发后续动作：有 fastbin 就先整体合并，主 arena 检查是否该 `systrim`，非主 arena 尝试 `heap_trim`（`:4868-4901`）。

第 3 步是理解"内存站岗"的关键：**普通小块释放不会触发任何归还检查**，只有释放的大块达到 64 KiB 才会去问 top 要不要缩。

合并靠 boundary tag 在 O(1) 完成，目的是抑制外部碎片；而"不合并"的两种块（fast bin、tcache）正是碎片与速度的交换。

## brk and mmap: Two Ways to Request Memory from the Kernel

ptmalloc 向内核取内存只有两种方式，分界是 **mmap threshold，默认 128KB**（比较的是对齐后的 chunk 大小，`malloc/malloc.c:2571-2573`）：

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
- **大块（≥ 128KB）或非主 arena 走 `mmap`**：直接映射一段独立匿名内存，释放时可整体 `munmap`，不必经过堆段。`sysmalloc` 在 `nb >= mmap_threshold` 且当前 mmap 块数未达 `n_mmaps_max`（默认 65536）时优先走这条路（`:2571-2588`）；非主 arena 的 heap 也是 mmap 出来的。

动态阈值机制：如果大块频繁申请释放，ptmalloc 会在 **munmap 一块大小超过当前阈值的 chunk 时**把 `mmap_threshold` 提高到该大小，同时把 `trim_threshold` 设成两倍（`malloc/malloc.c:4730-4740`），上限 `DEFAULT_MMAP_THRESHOLD_MAX`（64 位 32 MiB）。阈值抬高后更多中等块改走 brk 堆以复用。一旦通过 `mallopt` 或 `glibc.malloc.mmap_threshold` / `trim_threshold` 显式设值，`no_dyn_threshold` 置位，动态调整永久关闭（`:5517-5552`）。

## Safe-Linking and Double-Free Detection

glibc 2.32 起，fast bin 与 tcache 的**单向链表 next 指针**被异或掩码保护（`malloc/malloc.c:322-333`）：

```c
#define PROTECT_PTR(pos, ptr) \
  ((__typeof (ptr)) ((((size_t) pos) >> 12) ^ ((size_t) ptr)))
#define REVEAL_PTR(ptr)  PROTECT_PTR (&ptr, ptr)
```

`pos` 是存放指针的位置，`pos >> 12` 借用了 ASLR 的页对齐随机性。注释同时说明它假设页大小至少 4 KiB，页更大时熵更少但机制仍然有效（`:328-330`）。取指针时会把链解开，并顺手检查对齐：

```c
      pp = REVEAL_PTR (victim->fd);                                     \
      if (__glibc_unlikely (pp != NULL && misaligned_chunk (pp)))       \
	malloc_printerr ("malloc(): unaligned fastbin chunk detected"); \
```

（`malloc/malloc.c:4023-4025`。）tcache 一侧还有一把随机 `tcache_key` 用来发现同线程重复释放，前面已述。这三件事——safe-linking、对齐校验、tcache key——只能提高利用门槛，**不能把 use-after-free 变成安全操作**：块一旦释放，用户区就被链表指针覆盖了。

## Memory Hoarding (Heap Not Returned)

ptmalloc 的设计目标是服务**短生命周期**的分配。它什么时候把内存还给内核？默认规则有两级门槛：一次释放的 chunk **≥ 64 KiB**，且此时 `top` 已经 **≥ trim threshold（默认 128KB）**，才会对主 arena 调 `systrim` 收缩 program break（`malloc/malloc.c:4868-4901`）。非主 arena 则走 `heap_trim`，空出来的 heap 可以整个 munmap。

这就引出了实际工程中常见的 [glibc 内存站岗](/docs/CS/C/glibc.md)问题：

> 如果释放的空闲块**没有与 top 相邻**——中间隔着仍在使用的块——它们就无法并入 top，即使累计空闲达几十 GB，也无法归还内核。进程的 RSS 居高不下。

这不是 bug，而是边界标签合并规则与"只看 top"策略的直接结果。常见应对：

- 用 `malloc_trim` 主动归还。它会对每个 arena 先 `malloc_consolidate`，再遍历 normal bin，把空闲 chunk 内部**整页的部分**用 `madvise(MADV_DONTNEED)` 丢掉，最后对主 arena 额外做一次 `systrim`（`malloc/malloc.c:5251-5306`、`:5309-5326`）——所以它能回收的并不只是 top；
- 避免持有夹在中间的长生命周期小块、或把它们迁出主堆；
- 直接换用 **jemalloc / tcmalloc**，它们以更小的 span / 页粒度管理，站岗概率和粒度都小得多；jemalloc 用页级 rtree 反查元数据（见 [Address to Metadata Mapping](/docs/CS/memory/jemalloc/Address_Map.md)），根本没有"从 top 归还"这一层约束。

## Tunables, mallopt and Observability

glibc 把 ptmalloc 的旋钮统一到 `glibc.malloc.*` tunable 命名空间，通过 `GLIBC_TUNABLES` 设置；`MALLOC_*` 环境变量是旧入口，两者等价（`manual/tunables.texi:120-294`）。常用项：

| Tunable | 默认值（64 位） | 作用 |
| :--- | :--- | :--- |
| `glibc.malloc.arena_max` | 0（按核数） | arena 上限，取代 8 × 核数公式 |
| `glibc.malloc.arena_test` | 8 | 超过多少个 arena 后才检查上限 |
| `glibc.malloc.mmap_threshold` | 128 KiB（动态） | 大块走 mmap 的门槛；显式设置即关闭动态调整 |
| `glibc.malloc.trim_threshold` | 128 KiB（动态） | top 超过多少才归还；显式设置即关闭动态调整 |
| `glibc.malloc.mmap_max` | 65536 | 同时存在的 mmap chunk 上限，0 表示禁用 mmap |
| `glibc.malloc.top_pad` | 128 KiB | 扩展堆时多要的余量，收缩时保留的量 |
| `glibc.malloc.tcache_max` | 1032 | 可用 tcache 的最大请求尺寸 |
| `glibc.malloc.tcache_count` | 7 | 每档最多缓存几个，0 等于关闭 tcache |
| `glibc.malloc.tcache_unsorted_limit` | 0（不限） | miss 时最多从 unsorted 预填多少块 |
| `glibc.malloc.mxfast` | 128（chunk），可调到 160 | fastbin 的 chunk 上限 |
| `glibc.malloc.perturb` | 0 | 非零时用该值的低位填充分配/释放的内存，暴露未初始化读取 |
| `glibc.malloc.check` | 0 | 需预加载 `libc_malloc_debug`，启用容错分配器 |

`mallopt` 能在运行期改的是其中一部分：`M_MXFAST`、`M_TRIM_THRESHOLD`、`M_TOP_PAD`、`M_MMAP_THRESHOLD`、`M_MMAP_MAX`、`M_CHECK_ACTION`、`M_PERTURB`、`M_ARENA_TEST`、`M_ARENA_MAX`（`malloc/malloc.c:5686-5725`）。实现上它先对 main arena 做一次 `malloc_consolidate`，再在 main arena 锁内改参数（`:5672-5678`）——所以它改的是进程级策略，不是某个线程的行为。

观测接口各有用处：

- `mallinfo2` 返回 `struct mallinfo2`，用 `size_t` 而不是 `int`，避免了老 `mallinfo` 在超大堆上的溢出（`malloc/malloc.c:5424-5444`）；
- `malloc_stats` 打印到 stderr，适合快速看总量；
- `malloc_info` 输出 XML，能按 arena 看细节（声明见 `malloc/malloc.h:158`）；
- `malloc_usable_size` 给出指针实际可用的字节数（`malloc/malloc.c:5333-5353`），调试尺寸类假设时比猜更可靠。

## Hooks Were Removed

`__malloc_hook` / `__free_hook` / `__realloc_hook` / `__memalign_hook` 在 **glibc 2.34 已被移除**。现在 `malloc/hooks.c` 只剩下为旧二进制保留的 compat 符号，且用 `SHLIB_COMPAT (libc, GLIBC_2_0, GLIBC_2_34)` 包住。需要拦截分配时改用 `LD_PRELOAD` 包装、`glibc.malloc.check` + `libc_malloc_debug`、或者外部的 eBPF / uprobe 与 ASan 一类工具。

## Allocator Selection: ptmalloc / jemalloc / tcmalloc

| 维度 | ptmalloc (glibc) | jemalloc | tcmalloc (gperftools) |
| --- | --- | --- | --- |
| 多线程 | 多 arena，线程固定绑定 | arena + thread cache | thread cache + central heap |
| 碎片控制 | 中（站岗问题明显） | 强，重点优化碎片 | 较强 |
| 尺度结构 | 16 字节对齐 + boundary tag | 多级 size class + slab | 小 span + 线程缓存 |
| 归还粒度 | top 收缩 / mmap 块 | 页级 decay 曲线 | span 级 |
| 典型场景 | 默认、通用 | FreeBSD / Redis / 浏览器 / Facebook | Google 系、很多服务后端 |
| 特色工具 | malloc_trim / mallinfo2 | heap profiling、监控钩子 | heap profiler |

[jemalloc](/docs/CS/memory/jemalloc/jemalloc.md) 同样按申请大小把分配分成 small / large / huge，并针对 false sharing 做优化；选型时碎片敏感、长期运行的服务更倾向 jemalloc/tcmalloc，简单通用场景用默认 ptmalloc 即可。

## Interaction with Other Subsystems

- **虚拟内存**：malloc 拿到的是 [vm](/docs/CS/OS/Linux/mm/vm.md) 里的匿名 VMA，物理页经缺页才分配。
- **mmap**：大块与文件映射的机制见 [mmap](/docs/CS/OS/Linux/mm/mmap.md)。
- **物理分配**：缺页最终落到 [buddy/slab](/docs/CS/OS/Linux/mm/README.md)。
- **语言运行时**：Java 的 [Direct Buffer](/docs/CS/Java/JDK/IO/Direct_Buffer.md)、Go 的 [memory](/docs/CS/Go/memory.md)、Netty 的 [堆外内存](/docs/CS/Framework/Netty/memory.md)都建立在同一套 mmap/分配原语之上。

## Version and Verification Notes

本篇按 glibc `2.42` 的发布源码核对，`路径:行号` 相对 glibc 仓库根。所有具体字节数都按 x86-64 推导（`SIZE_SZ = 8`、`MALLOC_ALIGNMENT = 16`）；32 位下 `MINSIZE`、fastbin 上限、tcache 上限都要按源码公式重算，正文给的是公式而非结论。

源码没有直说、但读代码可以确定的两处细节：

- **tcache 默认上限有一格对齐差**：`mp_.tcache_max_bytes` 默认取 `MAX_TCACHE_SMALL_SIZE = tidx2usize(63) = 1032`，而 `__libc_malloc` / `__libc_free` 比较的是 **chunk 大小** `nb` 或 `size`，所以默认实际止于 chunk 1024（请求 1016）。只有显式设置 `glibc.malloc.tcache_max=1032` 时，`do_set_tcache_max` 才会把它换算成 chunk 1040 并启用第 64 档（`malloc/malloc.c:5588-5612`）。
- **fastbin 的"默认 128 / 最大 160"是 chunk 字节**：`DEFAULT_MXFAST = 64 * SIZE_SZ / 4`，`MAX_FAST_SIZE = 80 * SIZE_SZ / 4`，代码比较的都是 chunk 大小；用户可见载荷还要减 16 字节头。

本篇未在 Linux 运行时上实测，也没有验证各发行版 backport 是否改变了上述行为；需要现场值时用 `mallinfo2` / `malloc_info` 读取，不要照搬文章里的数字。

## Links

- [C](/docs/CS/C/C.md)
- [glibc 内存站岗](/docs/CS/C/glibc.md)
- [jemalloc](/docs/CS/memory/jemalloc/jemalloc.md)
- [vm 虚拟内存](/docs/CS/OS/Linux/mm/vm.md)
- [mmap](/docs/CS/OS/Linux/mm/mmap.md)
- [Memory](/docs/CS/Python/Memory.md)

## References

1. [glibc: malloc/malloc.c — sourceware.org](https://sourceware.org/git/?p=glibc.git;a=blob;f=malloc/malloc.c)
2. [MallocInternals — glibc wiki](https://sourceware.org/glibc/wiki/MallocInternals)
3. [Memory Allocation Tunables — glibc manual](https://www.gnu.org/software/libc/manual/html_node/Memory-Allocation-Tunables.html)
4. [mallopt(3) — Linux manual page](https://man7.org/linux/man-pages/man3/mallopt.3.html)
5. [A Scalable Concurrent malloc(3) Implementation for FreeBSD](https://people.freebsd.org/~jasone/jemalloc/bsdcan2006/jemalloc.pdf)
