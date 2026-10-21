## Introduction

堆剖析要同时解决三道彼此无关的难题，jemalloc 把三道题拆在了不同地方，这是读懂 `prof_*.c` 六个文件的前提：

1. **决定"这一次要不要采样"必须比分配本身更便宜**。判据是"累计分配字节数是否跨过阈值"，而这在 `malloc()` 还不知道返回指针之前就该定下来——否则 backtrace 会带上分配器自己的栈帧。
2. **记下来的计数要能被上千个线程无全局锁地累加，又要能按堆栈聚合**。单靠一棵全局堆栈树必然成为瓶颈，单靠每线程表则 dump 时无从聚合。
3. **dump 期间堆还在变**。一次快照既不能冻结分配，也不能报出从未同时存在过的计数。

三问分别对应**采样入口**（`jemalloc.c` + `prof.c`）、**数据结构**（`prof_data.c`）、**两趟快照**（`prof_dump_prep` / `prof_dump_impl`）。另有三个把同一套数据换种形态吐出去的出口：`.heap` 文本、`prof.log` 的 JSON、`prof_recent` 的 last-N 环形表。

基线 jemalloc `5.4.0`，`路径:行号` 相对 jemalloc 仓库根。剖析默认**整体关闭**（`opt_prof = false`，src/prof.c:30），且整块实现被 `JEMALLOC_PROF` 条件编译包住——注释说明连浮点代码都可以完全编不出去，以绕开某些 glibc 在 lazy symbol loading 期间不保存浮点寄存器的问题，并顺带要求 `-mno-sse`（src/prof.c:239-251）。

## The Sampling Decision Is Made Before the Allocation

判据函数是 `prof_sample_lookahead()`，注释就是设计说明：

> Check whether the next allocation would trip the prof sampler without advancing the event counter -- the counter only advances at the end of the alloc/dalloc call. Lets the allocation path pre-compute the prof context before committing.

（src/jemalloc.c:143-148）

实现只有四行可看点（src/jemalloc.c:150-158）：非 nominal TSD 或重入中直接返回 false；否则把"**本次若成功分配会累计到的字节数**"算出来——`tsd_thread_allocated_get(tsd) + usize - tsd_thread_allocated_last_event_get(tsd)`，注释特意标明"the subtraction is intentionally susceptible to underflow"（无符号回绕在这里正是想要的：跨阈值时差值变大）——再和下一次等待阈值比较。

因为事件计数器只在调用结束时推进，所以"提前预演"是必需的：**不推进计数器地算一次累加**。拿到 `sample_event` 后交给 `prof_alloc_prep()`，它三态返回（include/jemalloc/internal/prof_inlines.h:162-174）：`PROF_TCTX_SENTINEL`（未采样，哨兵是指针值 1，prof.h:106-107）、真正的 `tctx`、或 `NULL`（失败）。分配路径据此分流（src/jemalloc.c:619-643）：哨兵走 `imalloc_no_sample` 并可继续用线程缓存，采样走 `imalloc_sample` 且强制 `alloc_ctx.slab = false`。

等待阈值本身来自[线程事件](/docs/CS/memory/jemalloc/Fastpath.md)那套机制，槽位是 `te_alloc_prof_sample`——它排在事件注册表枚举的第一位（include/jemalloc/internal/thread_event_registry.h:10-13）。间隔是**几何分布**随机变量，均值 `2^lg_prof_sample`，公式与出处逐字写在注释里（Devroye《Non-Uniform Random Variate Generation》, Springer-Verlag 1986, pp 500）：

```
                      __        __
                      |  log(u)  |                     1
bytes_until_sample = | -------- |, where p = ---------------
                      | log(1-p) |             lg_prof_sample
                                              2
```

（src/prof.c:259-267）

实现里两处偏离教科书写法，注释都解释了（src/prof.c:277-283）：随机数为 0 时把 `u` 取 1.0 以避免 `log(0)`，于是 `u` 实际均匀分布于 `(0, 1]`；取 **floor 再 +1** 而不是 ceil，否则 `u` 恰为 1.0 时间隔会算成 0。`lg_prof_sample == 0` 时直接返回 `TE_MIN_START_WAIT`，即每个对象都采。

还有一条容易被跳过的偏置修复：`te_base_cb_t prof_sample_te_handler` 把 `postponed_event_wait` 也指向 `prof_sample_new_event_wait`，而不是像其它事件那样顺延到下一次分配，注释给出理由——否则"紧随重入之后的那次分配"总来自同一栈，会产生采样偏置（src/prof.c:332-340）。

`xallocx` 是这套提前决策的唯一别扭处：`extra` 非零时真实 `usize` 要等 `ixalloc()` 返回才知道，于是先用 `usize_max`（越界则取 `SC_LARGE_MAXCLASS`）做 lookahead，事后在 `prof_realloc()` 里用真实 `usize` 重判（src/jemalloc.c:1707-1725、:1753-1761）。若真实值不够，就回滚一个**已经抓好的 backtrace**：

> Don't sample. The usize passed to prof_alloc_prep() was larger than what actually got allocated, so a backtrace was captured for this allocation, even though its actual usize was insufficient to cross the sample threshold.

（include/jemalloc/internal/prof_inlines.h:201-209）

## Page Alignment Is the Escape Hatch

采样对象带一个不变式，全模块靠它做逆向判断（include/jemalloc/internal/prof.h:98-104）：

> Minimum required alignment for sampled allocations. Over-aligning sampled allocations allows us to quickly identify them on the dalloc path without resorting to metadata lookup.

`PROF_SAMPLE_ALIGNMENT` 与 `PROF_SAMPLE_ALIGNMENT_MASK` 分别是 `PAGE` 与 `PAGE_MASK`——**这里陈述的是符号恒等，不是数值**（本机 `jemalloc_internal_defs.h` 未生成，见文末）。

代价落在分配路径：`imalloc_sample()` 先把对齐抬到页（src/jemalloc.c:483），若该尺寸本来能上 slab，就额外做三件事——把 `tcache_ind` 设成 `TCACHE_IND_NONE`、按 `sz_sa2u(usize, align)` 抬到 bumped_usize 并以 `slab = false` 单独占一个 extent、最后 `arena_prof_promote()` 把元数据里的 szind **改回原小尺寸类**（src/jemalloc.c:489-499；include/jemalloc/internal/prof_inlines.h:249-260）。抬对齐的条件本身也是判据：只有请求对齐小于页、且"本可用 slab 或开了 `opt_cache_oblivious`"时才抬。

promote 之后，这个对象的元数据是**故意不一致的**：extent 不在 slab 上，szind 却指向 small 类。释放路径正是靠这一对矛盾识别它——走 large dalloc 分支却发现 `szind < SC_NBINS`，即 `is_sample_promoted`（include/jemalloc/internal/malloc_dispatch_inlines.h:85-91、:45-46），再 `arena_prof_demote()` 把 szind 恢复成 bumped 值、校验 `PAGE_CEILING(bumped_usize) == bumped_usize`，然后当大对象释放（src/arena.c:507-534、src/malloc_dispatch.c:17-33）。`arena_reset()` 的 large 循环里同样有这条分支（src/arena.c:574-576）。

对齐还兼作**逃出 free 快路径的暗号**（include/jemalloc/internal/jemalloc_internal_inlines_c.h:424-462）：

> free_fastpath do not handle two uncommon cases: 1) sampled profiled objects and 2) sampled junk & stash for use-after-free detection. Both have special alignments which are used to escape the fastpath.
>
> prof_sample is page-aligned, which covers the UAF check when both are enabled (the assertion below). Avoiding redundant checks since this is on the fastpath -- at most one runtime branch from this.

也就是说剖析与 UAF 检测两套机制**共用一次位与**，`prof_sample_aligned(ptr)` 成立就直接放弃快路径；`config_debug` 下还有 assert 保证 cache_bin 的非快路径对齐必然也被页对齐覆盖。这与 [Thread Cache](/docs/CS/memory/jemalloc/Tcache.md) 里 stash 那段是同一件事的两端。

`config_opt_safety_checks` 打开时，promote 会在 `[usize, bumped_usize)` 之间设 redzone、demote 时校验（src/arena.c:494-496、:525-531）——注释明确"Currently, we only do redzoning for small sampled allocations"。

## Three Columns and Two Grouped Views

数据模型写在文件头，值得整段引用（src/prof_data.c:17-31）：

> Conceptually, profiling data can be imagined as a table with three columns: thread, stack trace, and current allocation size. (When prof_accum is on, there's one additional column which is the cumulative allocation size.)
>
> Implementation wise, each thread maintains a hash recording the stack trace to allocation size correspondences, which are basically the individual rows in the table. In addition, two global "indices" are built to make data aggregation efficient (for dumping): bt2gctx and tdatas, which are basically the "grouped by stack trace" and "grouped by thread" views of the same table, respectively. Note that the allocation size is only aggregated to the two indices at dumping time, so as to optimize for performance.

三句话对应三级结构：

| 层 | 身份 | 存放位置 | 保护 |
| :--- | :--- | :--- | :--- |
| `prof_gctx_t` | 一条堆栈 | 全局 `bt2gctx` 哈希（src/prof_data.c:57-61） | `gctx->lock`，从 1024 项锁表借 |
| `prof_tctx_t` | 一条堆栈 × 一个线程的计数 | `gctx->tctxs` 红黑树 + 本线程 `bt2tctx` 哈希 | `tdata->lock` |
| `prof_tdata_t` | 一个线程 | 全局 `tdatas` 红黑树（src/prof_data.c:63-67） | `tdata->lock`，从 256 项锁表借 |

**行存在线程里，索引只存在 dump 时**——这条分工是全部复杂度的来源：计数器更新只碰本线程的哈希（`prof_malloc_sample_object` 持 `tdata->lock` 做四次 `+=`，src/prof.c:133-155），聚合是 dump 时现算的。

锁表共享的理由在源码里说得很直白，两条各管一层（src/prof_data.c:39-55）：gctx 那边是"gctx's are **ephemeral**, and destroying mutexes causes complications for systems that allocate when creating/destroying mutexes"；tdata 那边是"no operations require holding multiple tdata locks"，但允许在持 tdata 锁时再取 gctx 锁。数量常量 `PROF_NCTX_LOCKS 1024` / `PROF_NTDATA_LOCKS 256`，注释还补一句"除非启用剖析否则不分配空间，所以 over-provision 没关系"（prof.h:73-83）。

排序规则也是两级：tctx 按 `thr_uid → thr_discrim → tctx_uid`（src/prof_data.c:75-93），gctx 按 backtrace 向量 `memcmp` 后再比长度（:100-109）。`tctx_uid` 为何存在，注释给了两种共存情形——dumper 把一个 tctx 留在 purgatory，以及同一 `thr_uid` 的多个 consumer 可以并发执行 `prof_tctx_destroy()` 的部分阶段（prof.h:170-183）。

## Lifetimes Are Refcounted Through Limbo

`nlimbo` 是这套生命周期协议的唯一契约，定义处就写清了四种来源与销毁条件（prof.h:218-228）：初始化本 gctx、初始化该 gctx 的每线程计数、准备销毁本 gctx、dump 到含本 gctx 的 profile 时置为 limbo；"**nlimbo must be 1 (single destroyer) in order to safely destroy the gctx**"。

四处加减各有明确目的：`prof_lookup_global()` 命中已有 gctx 时先 `nlimbo++` 再放锁，注释说是"to avoid a race condition with prof_tctx_destroy()/prof_gctx_try_destroy()"（src/prof_data.c:310-318）；tctx 插好后 `nlimbo--`（:397-401）；`prof_gctx_try_destroy()` 那侧的检查注释把三步竞态写成了编号列表——另一个线程可以"采样 → 释放 → 抢先成功销毁 gctx"，于是本线程释放 `gctx->lock` 期间对象就没了（src/prof_data.c:225-252；判据 `tctx_tree_empty && nlimbo == 1` 在 :235）。

`tctx` 的销毁判据是四个条件全过（src/prof_data.c:1318-1335）：`opt_prof_accum` 关（累加计数只增不减，因此开着就永不销毁）、`curobjs == 0`、`!prepared`、`recent_count == 0`。`prepared` 字段注释一句话点题："True during prof_alloc_prep()..prof_malloc_sample_object(), prevents sample vs destroy race"（prof.h:188-192）——`prof_lookup()` 一命中就把 `prepared = true`（src/prof_data.c:350-352），计数落零时若仍 prepared 就不销毁。`recent_count` 是下面 last-N 的"placeholder"（prof.h:158-162）。

`dumping → purgatory` 是整个协议里唯一的**责任移交**：想销毁 tctx 的线程发现它正被 dumper 使用，于是既不销毁 tctx 也不销毁 gctx，只把状态改掉，让 dumper 在后面的收尾趟里替它完成（src/prof_data.c:1404-1413）。收尾趟因此不能普通迭代——注释解释"as soon as we decrement gctx->nlimbo and unlock gctx, another thread can concurrently destroy it, which will corrupt the tree. Therefore, tear down the tree one node at a time during iteration"（src/prof_data.c:835-840），实现就是 `gctx_tree_first` + `gctx_tree_remove` 的循环，并在同处收集 purgatory 的 tctx 逐个 `idalloctm`（:841-863）。

`prof_enter()` / `prof_leave()` 是第三层保护：取 `bt2gctx_mtx` 的同时把 `tdata->enq` 置真，字段注释一句话点题："State used to avoid dumping while operating on prof internals"（prof.h:282-285），目的是防止本线程正在改剖析结构时自己触发一次 dump；`prof_leave()` 放锁后才检查并补做期间暂存的 `enq_idump` / `enq_gdump`（src/prof_data.c:156-193）。对应的拒绝侧在 `prof_idump()` 里：看到 `tdata->enq` 就只置 `enq_idump = true` 然后返回（src/prof.c:386-389）。

## A Dump Is Two Passes Over a Snapshot

`prof_dump_impl()` 五行就是整个流程（src/prof_data.c:1092-1108）：`prof_dump_prep` → `prof_dump_header` → 遍历 gctx 树输出 → `prof_gctx_finish` → 可选 leakcheck。

**第一趟**建快照（src/prof_data.c:1050-1090），三步各有含义：

1. 遍历 `bt2gctx` 的每个 gctx，`nlimbo++` 并插进本次 dump 专用的 `gctxs` 红黑树、清空 `cnt_summed`——注释："Put gctx's in limbo and clear their counters in preparation for summing."（:1061-1068，实现 :790-807）
2. 持 `tdatas_mtx` 遍历所有 tdata，把每个 tctx 的 `cnts` **memcpy 成 `dump_cnts`**，状态 `nominal → dumping`，并累加到 `tdata->cnt_summed` 与全局 `cnt_all`（:1070-1080 → `prof_tdata_merge_iter` :881-923 → `prof_tctx_merge_tdata` :652-689）。
3. 遍历 `gctxs`，把状态为 `dumping` 或 `purgatory` 的 tctx 的 `dump_cnts` 累加进 `gctx->cnt_summed`（:1082-1087 → `prof_gctx_merge_iter` :815-828 → `prof_tctx_merge_iter` :710-730 → `prof_tctx_merge_gctx` :691-708），顺带统计 `leak_ngctx`。

一致性就藏在这次 memcpy 与状态机里。快照之后新出现的 tctx 状态仍是 `nominal`，两趟都用同一句话把它排除：合并趟是"New since dumping started; ignore."（:717-719），输出趟是"Not captured by this dump."（:746-748）。反过来 `initializing` 状态在两趟都是 `not_reached()`——即一个 tctx 要么已完整进入计数，要么根本不进这次 dump。同一次 dump 里 tdata 用 `dumping` 标志位划界：非 expired 的置 true 并参与，expired 的显式置 false（:888-919），字段注释解释新线程的 tdata 该位初始化为 false，"so that they aren't accidentally included in later dump phases"（prof.h:287-293）。

**第二趟**只读 `dump_cnts` / `cnt_summed`，不再碰活的计数器，因此写侧只需 `tdata->lock` 与 `gctx->lock` 两把叶子锁。`.heap` 文本的每一行都由这趟产生：

```
heap_v2/<1 << lg_prof_sample>
  t*: <curobjs>: <curbytes> [<accumobjs>: <accumbytes>]
@ 0x41419b 0x428217 0x40b7e2 ...
  t*: <聚合值>
  t13: <该线程的 dump_cnts>
```

`heap_v2/` 后跟的是**采样周期本身**（`((uint64_t)1U << lg_prof_sample)`，src/prof_data.c:945-950）；`  t*: ` 表示聚合行，`@` 开头是 backtrace 向量、每个帧以 `" %#" FMTxPTR` 打印（:981-985）；每条堆栈下先一行 `t*:` 再逐线程 `  t%llu: `（:987-992、:739-761），按线程输出时还会带上线程名（`prof_tdata_dump_iter`，:925-943）。四个计数的打印格式 `c: b [a: b]` 出自 `prof_dump_print_cnts()`（:629-650）。

`prof_dump_gctx()` 开头有一处裁剪值得注意：不累计时 `curobjs == 0`、累计时 `accumobjs == 0` 的 gctx 直接跳过，注释"Avoid dumping such gctx's that have no useful data"；紧接着的 assert 组里**故意注释掉了 unbiased 那两条**，理由是"would not be correct -- see the comment on races"（:957-979）。也就是说"未偏差计数"被承认为可能是脏的。

三个出口共用这把 `prof_dump_mtx`，另有两种自动触发。间隔型：每次采样事件处理时把"距上次的分配字节数"喂给 `counter_accum`，积累到 `prof_interval` 就 `prof_idump()`（`prof_sample_event_handler`，src/prof.c:298-312；`prof_interval` 由 `1 << opt_lg_prof_interval` 算出，见 :668-672）。高水位型：`extent_gdump_add()` 在激活 extent 时累加驻留页数，若刷新了 `highpages` 且 `prof_gdump` 开着，就调 `prof_gdump()`（src/extent.c:310-334）——判据是**新高水位**，不是某个内存上限。`opt_prof_final` 则注册为退出时 dump（`prof_fdump()`，src/prof.c:344-358）。

`prof_leakcheck()` 是 dump 的副作用之一，注释里那条差异必须一起读："Scaling is equivalent AdjustSamples() in jeprof, but the result may differ slightly from what jeprof reports, because here we scale the summary values, whereas jeprof scales each context individually and reports the sums of the scaled values."（src/prof_data.c:1000-1007）。缩放因子 `1/(1-exp(-ratio))` 与 jeprof 同源；`opt_prof_leak_error` 时用 `_exit(1)` 而非 `exit()`，注释说明是为了避免 `atexit()` 再次进入 dump 形成死循环（:1031-1035）。

`prof.reset` 是这套状态机唯一的"改标尺"入口：持 `prof_dump_mtx` 与 `tdatas_mtx`，改 `lg_prof_sample`、重建 unbias 映射、把所有 tdata 置 expired 并尽量销毁（src/prof_data.c:1290-1316）。

## Unbiasing Solves for the Inputs

几何采样会把小块**采少**（一个 size class 的实际对象越小，跨过阈值的概率越低），因此报告前要还原真实量。jeprof 沿用了 pprof 的做法：**用该堆栈上的平均对象大小**去反推。这在同一堆栈分配尺寸不一时是错的，于是 jemalloc 内部同时维护正确的未偏差计数，但**不能直接输出**——输出格式和下游工具不变。解法是反着求输入（src/prof_data.c:556-597）。

jeprof 侧的变换直接取自源码注释（:568-569），**连它自己少写的那个右括号也一并保留**

```
c_out = c_in * 1/(1-exp(-s_in/c_in/R)
s_out = s_in * 1/(1-exp(-s_in/c_in/R)
```

换元 `x = s_in / c_in`、`y = s_in`、`k = 1/R` 后两条方程各自给出 `y`，相减即得

```
x = s_out / c_out
```

其余量全部由此展开（:566-590）。注释也交代了这么做换到什么："we don't break backwards compatibility with jeprof (and the various tools that have copied its unbiasing logic). Eventually, we anticipate a v3 heap profile dump format based on JSON, at which point I think much of this logic can get cleaned up"（:592-596）——**这是一块自知的临时构造，且有明确的退役条件**。

`prof_unbias_map_init()` 预计算每个 size class 的两张表：`prof_unbiased_sz[i] = round(sz / (1-exp(-sz/R)))`，以及 `prof_shifted_unbiased_cnt[i] = round(cnt_shift / (1-exp(-sz/R)))`（src/prof_data.c:517-554）。这里的 **shifted** 是关键工程折衷：真值 `1/(1-exp(-sz/R))` 是分数，但计数必须保持整数——注释写的是 "a variety of reasons"，随后列出两条："rounding errors could trigger asserts, and not all libcs can properly handle floating point arithmetic during malloc calls inside libc"；而直接取整在尺寸接近采样率时误差可超过 30%，于是乘一个常数把最大取整误差除以它；这个常数还不能让 `size_t` 求和溢出，"the largest safe constant we can pick is the size of the smallest allocation"，即 `cnt_shift = 1 << SC_LG_TINY_MIN`（:532-549）。`prof_do_unbias()` 收 `c_out_shifted` 时才除回去（:598-627）。

浮点转整用了一个 NaN-safe 写法，注释说明为何写成 `!(a < b)`（src/prof_data.c:502-514）：`UINT64_MAX + 1` 在所有支持平台上都能精确表示，因此反向比较天然处理 NaN。

开关 `opt_prof_unbias` 默认 **true**（src/prof.c:44）；偏差修正只在输出时做，累加时做两次整数加法（src/prof.c:146-155）。这里残留一处**明知未修的竞态**，注释值得引用（src/prof.c:134-143）：查表必须持 `tdata->lock`，因为 `prof_reset` 是"先改表再加锁"，但表内容本身仍是普通变量、没有原子化；结论是把风险降到"即使读到垃圾，`prof_reset` 也会在任何损坏输出被 dump 之前把我们的 tctx 标记为 expired"。同一段说明也解释了 `prof_free_sampled_object()` 里为何不能对 unbiased 字节做同样的 assert（:202-207）。

## Recent Allocations Are a Preallocated Ring

`opt_prof_recent_alloc_max` 默认 **0**，即关闭（prof.h:92-93、src/prof_recent.c:13）。它记录最近 N 笔分配，用于"崩溃前最后一刻是谁分配了这块"这类问题；`-1` 表示不设上限。

设计约束是：**这条路径上不能加锁顺序，也不能在稳态下分配内存**。三条实现决定都由此推出：

- **不持锁地问一句**。`prof_recent_alloc_prepare()` 先无锁读 `max == 0` 就立刻返回，注释说明这优化了两种场景：last-N 根本没开，以及正在 dump（dump 期间临时关掉，以免阻塞被采样的分配，src/prof_recent.c:74-83）。要记录时只在本线程锁内 `++tctx->recent_count`，注释称其为"**placeholder**"——真正的记录要另取 `prof_recent_alloc_mtx`（:85-92）。
- **释放锁去分配，再回来抢锁用**。这段注释自带一张 2×3 的 ASCII 场景表（"now" × "later"，(1)~(6) 六格），逐个说明哪些不可能发生、哪些是平凡情形，结论是：唯一有性能代价的是"(3) 本来需要节点、回来后发现不需要了"，"it happens very rarely, so the cost is relatively small compared to the gain of **not having to have the lock order of prof_recent_alloc_mtx above all the allocation locks**"（src/prof_recent.c:295-327）。节点固定从 arena 0 分配（:46-51）。
- **满员时不 free 也不 alloc，而是轮转复用**。达到上限时取 `ql_first`、记下旧节点的 alloc/dalloc tctx、`prof_recent_alloc_evict_edata()` 清掉 edata 上的反向指针，然后 `ql_rotate`，最后把内容写进 `ql_last`（:343-379）。**环形缓冲靠一次指针轮转实现**。被换出的两个 tctx 在**放掉 `prof_recent_alloc_mtx` 之后**才做引用递减，注释给出理由："no simultaneous holdings of prof_recent_alloc_mtx and tdata->lock … In the worst case this may delay the tctx release but it's better than holding prof_recent_alloc_mtx for longer."（:389-400）

释放侧的入口在 5.4 叫 `prof_recent_alloc_reset()`（include/jemalloc/internal/prof_recent.h:13），由 `prof_info_get_and_reset_recent()` 经 `arena_prof_info_get(..., reset=true)` 触发，注释把它称作"Reset the pointer on the recent allocation record, so that this allocation is recorded as released"（src/large.c:284-290）。它先无锁看记录是否还在，再造一个 `dalloc_tctx`（**这里会抓一条新 backtrace**），放锁后二重检查；若期间记录已被轮转走，则回滚刚建的 tctx——注释原文是" We lost the rase - the allocation record was gone."（:203-246，含源码自身的 `rase` 拼写）。

dump 侧同样为了不长期持锁：把整条链表 `ql_move` 出来、计数清零、放锁，输出完再把期间新插入的 `ql_concat` 回来、`prof_recent_alloc_restore_locked()` 处理 `max` 被调小的情况（:554-583）。JSON 是 compact 输出，顶层三个键 `sample_interval` / `recent_alloc_max` / `recent_alloc`（:563-574）。每笔记录的 `released` 字段不是存的布尔，而是现场判"edata 反向指针是否已为 NULL"（:499-500）——结构上不可能与真实状态漂移。分配侧写 `alloc_*` 四件套，释放侧补齐 `dalloc_*` 三件套与 `dalloc_trace`（:493-538）。

## Allocation Logs Pair Two Stacks

`prof.log` 回答的是另一类问题：**这块是谁分配的、又是谁释放的**，且两者可以不是同一线程。所以一条日志记录天然是两个栈的配对，也就只能在**释放时**写出。入口 `prof_try_log()` 带着 `JEMALLOC_COLD` 标注，调用点就在 `prof_free_sampled_object()` 递减计数之后（src/prof.c:213）。

状态机三态，语义注释逐条写明（src/prof_log.c:20-32）：`stopped`（从未 start，或上次 stop 已完成）、`started`（正在记录）、`dumping`（已调 stop 但还没写完，**此时不再采样**）。链表节点分三类：按名字去重的线程、按栈去重的 backtrace、以及实际的分配记录（:54-72、以及 `log_bt_index` / `log_thr_index` 两个递增游标 :49-51）。

`prof_try_log()` 里四处细节决定了它记到了什么（src/prof_log.c:207-283）：

- 拿不到 consumer 的 `cons_tdata` 就**放弃这条记录**，注释解释这只发生在线程处于"weird state (e.g. it's being destroyed)"时。
- 两张去重哈希表**懒初始化**，第一次真正记录时才 `ckh_new`。
- 记录节点自己用 `iallocztm(... arena_get(TSDN_NULL, 0, true), true)` 从 arena 0 分配。
- **生产栈不重新展开**：`prod_bt = &tctx->gctx->bt` 直接复用采样时抓好的那份，注释还补一句"We haven't destroyed tctx yet, so gctx should be good to read"；只有消费栈用 `bt_init` + `prof_backtrace()` 现场抓。

顶层四个键按 `info` → `threads` → `stack_traces` → `allocations` 的顺序写出（`prof_log_stop()` 里四次 emit 调用，src/prof_log.c:671-676），线程与堆栈都用索引引用以避免重复。每条 allocation 七个键——`alloc_thread` / `free_thread` / `alloc_trace` / `free_trace` 四个索引，`alloc_timestamp` / `free_timestamp` 两个纳秒值，加 `usize`（`prof_log_emit_allocs`，:550-587）。`info` 是唯一不是数组的那个键，里面有 `duration`（相对 `log_start_timestamp`）、`version`、`lg_sample_rate`、`prof_time_resolution` 与 pid（`prof_log_emit_metadata`，:589-613）。堆栈帧是用 `%p` 逐帧字符串化的，缓冲区大小按 `2 * sizeof(intptr_t) + 3` 算（`prof_log_emit_traces`，:526-540）。emit 时**边走边释放**节点（`idalloctm` 紧跟 `next`，:581-584），因此日志内存不会二次峰值。文件名带 `log_seq` 递增序号（:37-44）。

## Four Ways to Walk a Stack

`prof_backtrace()` 是一个薄壳：`pre_reentrancy()` → 函数指针 → `post_reentrancy()`，长度上限用 `opt_prof_bt_max`（src/prof_sys.c:426-435）。指针由 `prof_hooks_init()` 在启动时绑到编译期选中的 `prof_backtrace_impl`（:437-443），另两个 hook（`prof_sample_hook` / `prof_sample_free_hook`）默认 NULL，供外部注入。

四个后端是互斥的 `#elif` 链，各有硬性约束：

| 后端 | 位置 | 实现方式 |
| :--- | :--- | :--- |
| libunwind | src/prof_sys.c:54-69 | `unw_backtrace(vec, max_len)`，assert `max_len <= PROF_BT_MAX_LIMIT` |
| libgcc | :70-107 | `_Unwind_Backtrace(prof_unwind_callback, &data)`，回调数据结构见 prof.h:119-126 |
| GCC builtin | :108-417 | `BT_FRAME(i)` 宏手工展开 **256 帧**，每帧先查 `__builtin_frame_address(i)` 再取 `__builtin_return_address(i)` |
| 无 | :418-424 | `not_reached()` |

第三个后端的硬编码正是那个奇怪上限的来源，注释要求两者同步（prof.h:36-41）："The version of prof_backtrace() that is based on `__builtin_return_address()` necessarily has a hard-coded number of backtrace frame handlers, and should be kept in sync with this setting." 因此 `PROF_BT_MAX_LIMIT` 是 `#ifdef JEMALLOC_PROF_GCC` 时的 **256**、否则 **UINT_MAX**（:41-45），而运行期默认 `PROF_BT_MAX_DEFAULT = 128`（:46）。`__builtin_return_address` 的参数必须是编译期常量（src/prof_sys.c:113），这就是那 256 行重复宏存在的原因。

libgcc 后端还有一处反直觉的启动动作：`prof_unwind_init()` 在启用剖析前故意调用一次 `_Unwind_Backtrace`，只为让回溯机制**先把内部状态分配好**，避免在真正的采样路径里首次分配（src/prof_sys.c:445-454）。

backtrace 向量不是每次 malloc 出来的：`bt_init(&bt, tdata->vec)` 用的是 tdata 里的复用缓冲，字段注释即"Backtrace vector, used for calls to prof_backtrace()"（prof.h:307-308；`bt_init` 在 src/prof_sys.c:46-52），`prof_tctx_create()` 就走这条路（src/prof.c:222-237）。哈希则是把整个向量当字节串做 `hash(vec, len*sizeof(void*), 0x94122f33U, ...)`（src/prof_data.c:1127-1134）。

## Switches, Names and Per-thread Activity

`src/prof.c:30-44` 集中了剖析相关的全部 15 个 `opt_` 默认值（13 个 `opt_prof_*` 加 2 个 `opt_lg_prof_*`），其中几个默认取向和直觉相反：`opt_prof = false`（整体关）但 `opt_prof_active = true`、`opt_prof_thread_active_init = true`（打开之后默认就采），`opt_prof_accum = false`（默认只报当前驻留量、不报累计量），`opt_prof_unbias = true`，`opt_lg_prof_interval = -1`（不按间隔自动 dump），`opt_prof_gdump` / `opt_prof_final` / `opt_prof_leak` / `opt_prof_leak_error` 均 false，`opt_prof_sys_thread_name = false`。

`prof_active` 的读取是**无锁**的，注释同时声明了代价："No locking is used when reading prof_active in the fast path, so there are no guarantees regarding how long it will take for all threads to notice state changes."（include/jemalloc/internal/prof_inlines.h:24-32）。同文件还有一条不变式：`opt_prof` 关时 `prof_active` 必关（:15-19）。

线程级开关是第三层：`prof_sample_should_skip()` 在快路径只判 `!sample_event`（注释"Fastpath: no need to load tdata"，:142-144），慢路径才取出 tdata 并返回 `!tdata->active`（:154-159）。因此"采样"的判定顺序是**全局 opt → 全局 active → 本次是否跨阈值 → 本线程是否 active**，前三步都不需要碰锁。

线程名上限 16 字节（`PROF_THREAD_NAME_MAX_LEN`，prof.h:95-96），写入用 `strncpy` 后**显式补 `\0`**（src/prof_data.c:455-459）——这条正是 5.4 的移植性修复之一，为了消除 GCC 16 的 `-Wstringop-truncation`（ChangeLog:104-107）。设置时逐字符校验，非 graphic 且非 blank 的字符返回 `EINVAL`（:461-471），因为名字要原样进入 `.heap` 文本。`opt_prof_sys_thread_name` 打开时则从系统读（`pthread_getname_np` 或 `pthread_get_name_np`，都没有就 `ENOSYS`，src/prof_sys.c:456-466）。

文件名模板由 `prof_dump_filename()` 决定（src/prof_sys.c:662-697）：默认形态是 `<prefix>.<pid>.<seq>.v<vseq>.heap`，`opt_prof_pid_namespace`（src/prof.c:41，默认 false）打开则在最前面插一段 pid namespace 标识。字符 `v` 标出这次 dump 是哪一类触发——`'i'` 间隔、`'m'` 手动且未给文件名、`'u'` 驻留页数**刷新高水位**、`'f'` 进程退出（`prof_idump_impl` / `prof_mdump_impl` / `prof_gdump_impl` / `prof_fdump_impl`，:755-799、:716-724），前三类各自维护一个递增 `vseq`，唯独 `'f'` 传 `VSEQ_INVALID`（`UINT64_C(0xffffffffffffffff)`，:661）走无 vseq 的分支。另有一条独立路径 `prof_get_default_filename()` 生成 `.json` 后缀的名字，`prof_log` 用它（:699-713、src/prof_log.c:458）。

还有一条与剖析共享底座的默认值：`opt_disable_large_size_classes = true`（src/jemalloc.c:130-135，注释标明"mainly for debugging purposes and should not be tuned"）。`prof_unbias_map_init()` 里已承认这让 unbiased 计算在精细尺寸上不如从前准确（src/prof_data.c:521-527）——剖析结论会受这个全局开关影响，读的时候要知道两者耦合。

## Version and Verification Notes

- **没有做过任何跨版本源码 diff**。本机只有 `5.4.0` 单提交浅树，无 5.3.x 源码，因此本篇不写"5.3 的某函数怎样"。可核对的只有两处：ChangeLog 原文，以及 5.4 树内的存在性。`ChangeLog:7-110` 是 5.4.0 全部条目（`:111` 起是 5.3.1），其中与剖析直接相关的四条：`:60-61` "Fix a prof-sampling / guard-page interaction bug in the SAN."、`:85-89` 引入 OS 抽象层时把 **profiling** 与 time / atfork / virtual-memory 等一并移出核心（本篇 `src/prof_sys.c` 的分工即由此而来）、`:104-107` 线程名显式 NUL 终止、`:108-109` PID-namespace 符号链接解析改为不依赖 glibc 的 `strtok`/`atol` 并返回 `uint64_t`（对应 `opt_prof_pid_namespace` 拼进 dump 文件名，见 src/prof_sys.c:670-705）。`prof_sample_lookahead()` 本篇只写到"它在 5.4 里长这样"为止，依据是**它就在 `src/jemalloc.c:150`**；这不构成"旧版本没有它"的断言。
- `prof_recent_dalloc` 这个名字在 5.4 全树 grep 零命中；释放侧入口是 `prof_recent_alloc_reset`（include/jemalloc/internal/prof_recent.h:13）。这是存在性证据，据此**只描述当前 API，不断言它曾叫什么**。
- 后端选择宏（`JEMALLOC_PROF_LIBUNWIND` / `_LIBGCC` / `_GCC`）与 `PAGE`、`SC_LG_TINY_MIN`、`SC_NSIZES` 都来自 configure 生成的 `jemalloc_internal_defs.h`；本机 `autom4te` 因 `/usr/bin/perl5.30` 解释器损坏而**无法构建**，该文件不存在。因此本篇凡涉及这些量，一律写成符号恒等或条件分支，不给绝对数值，也不断言本机启用了哪个后端。
- `lg_prof_sample` 默认 19 是源码常量（prof.h:33）；"平均 2^19 字节采一次"是代入公式的推导，`512 KB` 这类换算值属**替换计算而非实测**。
- 本篇不给任何性能数字：采样开销、dump 停顿、unbias 误差的实际量级本机都测不了（无构建、无 benchmark）。源码里唯一的量化说法是"取整误差可超过 30%"（src/prof_data.c:538-540），那是注释自述，不是测量。
- `prof_idump` 的完整重入保护链（`prof_enter` / `prof_leave` 只是其中一段）、`prof_stats`（`opt_prof_stats`，实现在独立的 `src/prof_stats.c`，默认 false）与 `stats.arenas.*` 的关系本篇未展开，需要时回源码 `src/prof.c:367+` 与 `src/prof_stats.c` 核对后再补。

## Links

- [jemalloc](/docs/CS/memory/jemalloc/jemalloc.md)
- [Allocation Fast Path](/docs/CS/memory/jemalloc/Fastpath.md)
- [Thread Cache](/docs/CS/memory/jemalloc/Tcache.md)
- [Memory Reclaim and Decay](/docs/CS/memory/jemalloc/Decay_and_Purge.md)
- [Address to Metadata Mapping](/docs/CS/memory/jemalloc/Address_Map.md)
- [Configuration and the mallctl Surface](/docs/CS/memory/jemalloc/Config_and_API.md)

## References

- [jemalloc: concurrent memory allocator](https://jemalloc.net/)
- [jemalloc GitHub 仓库](https://github.com/jemalloc/jemalloc)
- [Non-Uniform Random Variate Generation, Luc Devroye, Springer-Verlag 1986](http://luc.devroye.org/rnbookindex.html)
