## Introduction

jemalloc 的 `malloc()` 在最好情况下只做三件事：**一次移位加一次查表**拿到尺寸类与 usize，**一次减法比较**判断有没有事件要处理，**一次栈指针移动**取走一个缓存好的对象。没有锁、没有系统调用、没有元数据查询。`free()` 多一步：它必须从指针反推出尺寸类。

本篇讲的就是这三步各自"为什么可以省"，以及省不掉的那三种情况（大尺寸、未初始化的 TSD、被采样或有特殊对齐的指针）是如何被统一到一个分支里送进慢路径的。基线 jemalloc `5.4.0`，`路径:行号` 相对 jemalloc 仓库根。

## Entry Points

`je_malloc` 只有一行实质代码——把 `malloc_default` 当 fallback 交给 `imalloc_fastpath`（src/jemalloc.c:807-813）。`je_free` 同理，交给 `je_free_impl`（src/jemalloc.c:1100-1107；`je_free_impl` 在 `include/jemalloc/internal/jemalloc_internal_inlines_c.h:574-579`）。带尺寸的 C23 变体走同一层：`je_free_sized` → `je_sdallocx_noflags`（src/jemalloc.c:1109-1126；inlines_c.h:560-565），`je_free_aligned_sized` → `je_sdallocx_impl` 并带上 `MALLOCX_ALIGN(alignment)`（src/jemalloc.c:1128-1140；inlines_c.h:567-572）。

`imalloc_fastpath` 的定义位置有讲究：它在头文件里而不是 `jemalloc.c`，注释说明是为了能内联进 `operator new`——在分配密集的 C++ 程序里，一次函数调用的开销占比不可忽略（inlines_c.h:268-275）。同一个注释还解释了两条设计：

- fallback 的签名与 `malloc` / `operator new` 一致，因此**可以尾调用**，省掉建立调用帧和保存 callee-saved 寄存器（inlines_c.h:272-277、283-285）。
- fallback 是参数而不是写死 `malloc_default`，因为 `malloc` 可以返回 NULL、`operator new` 不可以，两者需要不同的慢路径收尾（inlines_c.h:270-272）。

`malloc_default` 自己也带一条注释：它只在退出处打 logging hook，入口那句由 `je_malloc` 打（src/jemalloc.c:771-780）。

## Three Ways Out of the Fast Path

`imalloc_fastpath` 开头两个分支就把"不属于快路径"的请求全部踢走：

1. `tsd_get_allocates()` 为真且尚未初始化时直接 fallback（inlines_c.h:288-290）。
2. `size > SC_LOOKUP_MAXCLASS || tsd == NULL` —— 一条分支同时管大尺寸和没有 TSD 的线程（inlines_c.h:292-295）。

第三条更精巧。拿到 ind/usize 之后（inlines_c.h:312），读两个数：本线程累计分配量 `allocated` 与下一个事件阈值 `threshold`，然后

```c
if (unlikely(allocated_after >= threshold)) {
    return fallback_alloc(size);
}
```

注释逐字写着："Check for events and tsd non-nominal (fast_threshold will be set to 0) in a single branch"（inlines_c.h:334-338）。**一次比较同时回答三件事**：有没有线程事件到期、TSD 是否处于非 nominal 状态、`malloc_init()` 是否还没跑完。后两者之所以能被折进来，是因为它们都会把 fast threshold 写成 0：`te_next_event_fast_set_non_nominal()` 把 alloc 与 dalloc 两个阈值都清零（`include/jemalloc/internal/thread_event.h:145-152`），而未初始化时同理（inlines_c.h:296-303、322-333 的 assert 组把这条不变式钉住）。

阈值取自 TSD 里的"fast"影子变量，用的是 **unsafe getter**，注释解释正是为了允许 tsd 非 nominal 时读到 0（thread_event.h:85-104）。

## One Subtraction, Not Two Comparisons

慢路径的事件判定在 `te_event_advance()` 里，那是一条带溢出隐患的减法：

```c
/* The subtraction is intentionally susceptible to underflow. */
if (likely(usize < te_ctx_next_event_get(&ctx) - bytes_before)) {
```

（thread_event.h:210-211）。之所以敢让减法回绕，是因为 `TE_NEXT_EVENT_FAST_MAX` 的定义把上界钉在 `UINT64_MAX - SC_LOOKUP_MAXCLASS + 1`（thread_event.h:16-20），注释说这样"malloc 快路径里不必检查溢出"。计数器一旦接近上界，就改写成非 fast 路径并退回 0（thread_event.h:24-31 说明 `TE_MAX_INTERVAL` 与回绕的关系）。

这条把"要不要处理事件"压成一条无分支代价比较的关键，同时决定了 [Size Classes](/docs/CS/memory/jemalloc/Size_Classes.md) 里那条 `assert(SC_LARGE_MAXCLASS < SSIZE_MAX)`（src/sc.c:245-252）。

## The Two-Step Pop

取对象这一步被刻意写成两次调用：先 `cache_bin_alloc_easy`，失败再 `cache_bin_alloc`（inlines_c.h:347-365）。注释给了理由："这样拆是为了让多余的低水位计算不必发生在（更常见的）不碰低水位的场合，编译器自己不会做这份重复"（inlines_c.h:347-351）。两者都转发到同一个 `cache_bin_alloc_impl(bin, success, adjust_low_water)`，差别就是那个布尔参数（`include/jemalloc/internal/cache_bin.h:426-443`）。

`cache_bin_alloc_impl` 里有两个值得记的优化（cache_bin.h:382-424）：

- **返回值不判 NULL，改判 `success`**。注释逐字："避免检查 (ret == NULL) 是因为 avail 栈上从来不会存 null（编译器不知道这一点），而 eagerly checking ret 会造成流水线停顿（等待 cacheline）"（cache_bin.h:383-389）。也就是说先读出的 `ret` 可能还在等内存，而 `low_bits != low_bits_low_water` 这个比较不依赖它，于是分支先走、数据后到。
- **允许从 empty 位置读一次**。"This may read from the empty position; however the loaded value won't be used. It's safe because the stack has one more slot reserved."（cache_bin.h:391-394）——栈尾多留一格槽位，就是为了让这次无害的越界读不必加判断。

成功收尾只做两件事：写回 `thread_allocated`，以及在 `config_stats` 下给这个 bin 的 `nrequests` 加一（inlines_c.h:258-266）。

## free Has to Reverse-Map the Pointer

`free` 的麻烦在于它手里只有指针。`free_fastpath` 因此分成两个入口（inlines_c.h:467-558）：

- **无尺寸提示**（`free()`）：调 `emap_alloc_ctx_try_lookup_fast()`（inlines_c.h:484-485）。这是 rtree 的 L1 缓存版本，命中即 O(1) 拿到 `{szind, slab, usize}`；未命中或拿到 `!alloc_ctx.slab` 就返回 false 走慢路径。注意 `alloc_ctx` 初始化成 `{0, 0, false}`（inlines_c.h:481）——`usize` 是 5.4 才进这个结构的字段，5.3 时代只有 `{szind, slab}`。
- **有尺寸提示**（`sdallocx` / `free_sized`）：跳过元数据查询，直接用 `sz_size2index_usize_fastpath(size, ...)`（inlines_c.h:506）。代价是要先检查 `size > SC_LOOKUP_MAXCLASS`。

两个分支之后都有一条 `assert(alloc_ctx.slab)`，注释解释："Currently the fastpath only handles small sizes. The branch on SC_LOOKUP_MAXCLASS makes sure of it. This lets us avoid checking tcache szind upper limit (i.e. tcache_max) as well."（inlines_c.h:509-515）。**快路径不需要知道 tcache 能缓存多大**——因为查表上界已经比 small 上界小，这条不变式来自 [Size Classes](/docs/CS/memory/jemalloc/Size_Classes.md) 里那句 `#error "Lookup table sizes must be small"`（sc.h:262-265）。

之后同样是那条折叠分支（inlines_c.h:520-534）、取 bin（inlines_c.h:540-542）、`cache_bin_dalloc_easy`（inlines_c.h:551-553），最后才写回 `thread_deallocated`（inlines_c.h:555）。中间还有一句 `assert(!opt_junk_free)`：能走到这里说明一定在快路径上，因此 junk 填充不可能发生（inlines_c.h:547-549）。

## Escaping by Alignment

有两类指针必须逃出新路径，jemalloc 用的标记是**对齐**而不是额外元数据（inlines_c.h:429-459）：

- 被 heap profiling 采样的对象强制页对齐：`prof_sample_aligned()` 就是 `((uintptr_t)ptr & PROF_SAMPLE_ALIGNMENT_MASK) == 0`（inlines_c.h:424-428）。
- UAF 检测采样过的对象被 stash 进 cache_bin 的 stash 区，也带非快路径对齐（`cache_bin_nonfast_aligned`）。

注释逐字："free_fastpath do not handle two uncommon cases: 1) sampled profiled objects and 2) sampled junk & stash for use-after-free detection. Both have special alignments which are used to escape the fastpath."（inlines_c.h:432-438），并接着说明"prof_sample 是页对齐的，两者同时开启时它覆盖了 UAF 检查"——因此最多一条运行时分支。

同一个技巧在慢路径反向使用：`isfree()` 拿到调用者给的 usize 后，如果指针**不是**页对齐，就信任 usize 直接构造 alloc_ctx，**跳过 rtree 查询**；只有页对齐（可能是采样对象）才回查元数据（src/jemalloc.c:969-985）。

## The Sized-Dealloc Consistency Check

`maybe_check_alloc_ctx()` 只在 `config_opt_size_checks` 编译期开启时存在（inlines_c.h:399-421）：它再查一次真实 alloc_ctx，比较 `szind` 与 `slab`，不一致分别报 `safety_check_fail_sized_dealloc` 与 `"Internal heap corruption detected: mismatch in slab bit"`，然后**返回 true 表示这次 free 已被消费**。快路径上那句 `/* See the comment in isfree. */`（inlines_c.h:534-537）指向慢路径 `isfree()` 里同样的判定（src/jemalloc.c:988-1000）。

这一路是 5.3.1 引入、5.4 保留的 double-free / 错尺寸释放检测族（ChangeLog:120-158），开关是运行期 `opt.debug_double_free_max_scan` 与编译期 `config.opt_safety_checks`（src/conf.c:754-757、src/ctl.c:484）。

## Slow Path Shape

慢路径的中心是 `imalloc_body()`（src/jemalloc.c:552-727），参数拆成 `static_opts_t`（行为：是否 NULL-out、是否设 errno、OOM 文案）与 `dynamic_opts_t`（本次请求：num_items / item_size / result）。几个值得记的点：

- 重入状态（`tsd_reentrancy_level_get() != 0`）下强制 `TCACHE_IND_NONE` 且**只用 arena 0**，理由是"我们知道 arena 0 已经初始化过了"——分配器内部自己的分配不能再去碰尚未就绪的 arena 表。
- prof 分支会先问"这次分配会不会跨过采样点"：`prof_sample_lookahead()` 用 TSD 里的累计量与采样等待量比较（src/jemalloc.c:149-158），据此在 `imalloc_no_sample`（src/jemalloc.c:457）与 `imalloc_sample`（src/jemalloc.c:479）之间选路。
- 结尾统一调 `thread_alloc_event(tsd, usize)`（thread_event.h:223-226）推进事件计数——**慢路径也要推进**，否则 decay / tcache GC 会被饿死。

`ifree()`（src/jemalloc.c:918-948）反过来：它**总是**做 `emap_alloc_ctx_lookup`，因为快路径已经把这个成本付过一次并且失败了；slow_path 参数只决定 junk 填充与是否断言 fast。

## Late Frees Without a TSD

`dealloc_no_tsd()`（src/jemalloc.c:1028-1057）是 5.4 一处值得单独记的生命周期修复。在通用 `pthread_getspecific()` TSD 实现上，释放可能发生在该线程 TSD 已拆除之后；此时若用 `tsd_fetch_min()` 会**分配并发布一个全新的 TSD 包装**，把刚释放的 teardown 状态又复活——这正是它修的崩溃。改法是直接把对象经 `idalloctm(TSDN_NULL, ...)` 交回它的 arena，并显式列出跳过的四项簿记：prof 注销、junk 填充、sized-dealloc 安全检查、线程事件推进。注释强调"内存本身仍然正确归还给 arena"，代价都发生在罕见的 teardown-time free 上。

`free_default()` 另一处细节是 errno：进门先存、两处出口恢复（src/jemalloc.c:1063-1090），对应 ChangeLog 的 "Preserve `errno` across `free`, `free_sized`, and `free_aligned_sized`"（ChangeLog:43-45）。同一函数还有条注释解释为什么 free 不该触发 TSD 的"最小→完整"升级：free 可能发生在线程退出、TLS 已释放之后，若某线程在此之前从未分配过，完整 TSD 将无法被正确析构（src/jemalloc.c:1072-1078）。

`je_free_sized` 里那句 NULL 检查也是同类细节：`free_sized(NULL, size)` 必须像 `free(NULL)` 一样是 no-op，但**不能**交给 `je_free_impl` 兜底——有尺寸提示时快路径会跳过 emap 查询而直接落到 `sdallocx_default()`，那里期待非 NULL 指针（src/jemalloc.c:1112-1122）。

## malloc_dispatch Is a Naming Layer

5.4 把分发逻辑从 `jemalloc.c` 抽成了 `malloc_dispatch.h` / `malloc_dispatch_inlines.h`。它**不是函数指针表也不是 hook**：只有三个 out-of-line 声明（`malloc_dispatch_palloc`、`malloc_dispatch_dalloc_promoted`、`malloc_dispatch_ralloc`），其余全是 inline 命名层（`malloc_dispatch_malloc` 在 `include/jemalloc/internal/malloc_dispatch_inlines.h:18-36`，`_dalloc` 在 :135，`_sdalloc` 在 :220，`_dalloc_small_safety_check` 在 :108）。这对应 ChangeLog 的 "extracting arena management, initialization, fork orchestration, and allocation dispatch from `jemalloc.c`"（ChangeLog:63-68）。

分发层里也埋了一条 5.4 的注释值得引用：`malloc_dispatch_dalloc_large_no_tcache` 指出 "szind both classifies small vs large and validates the extent -- inactive extents have szind == SC_NSIZES"（malloc_dispatch_inlines.h:39-43）——**分类和有效性校验共用同一个字段**，不必额外查状态。

## Version and Verification Notes

- 本篇的行号与引文全部直接读自本地 `5.4.0` 树，可回 tag 复核。
- "快路径只有三个动作"是对 `imalloc_fastpath` 成功分支的描述，不是对生成代码的实测：本机无法构建，没有反汇编可核。
- 5.4 相对 5.3 在这条链上的差异（`malloc_dispatch` 抽出、`emap_alloc_ctx_t` 加 `usize`、`dealloc_no_tsd` 新增）依据是 `ChangeLog:7-110` 的原文与 5.4 树内证据；本地是浅历史（单提交、只有 `5.4.0` 一个 tag），**没做过逐行 diff**，因此不许写"某行为在 5.3 是怎样的"这类断言。

## Links

- [Size Classes](/docs/CS/memory/jemalloc/Size_Classes.md)
- [Thread Cache](/docs/CS/memory/jemalloc/Tcache.md)
- [Address to Metadata Mapping](/docs/CS/memory/jemalloc/Address_Map.md)
- [Arena, Bin and Slab](/docs/CS/memory/jemalloc/Arena_Bin_Slab.md)
- [Configuration and the mallctl Surface](/docs/CS/memory/jemalloc/Config_and_API.md)
- [Memory Allocation](/docs/CS/memory/memory.md)

## References

- [jemalloc: concurrent memory allocator](https://jemalloc.net/)
- [jemalloc GitHub 仓库](https://github.com/jemalloc/jemalloc)
- [A Scalable Concurrent malloc(3) Implementation for FreeBSD](https://people.freebsd.org/~jasone/jemalloc/bsdcan2006/jemalloc.pdf)
