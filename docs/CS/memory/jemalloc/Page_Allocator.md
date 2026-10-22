## Introduction

从 `malloc` 走到页这一层，结构不是一棵树，而是**一次分派加两条策略完全不同的阶梯**：`pa_alloc` 先问 HPA（hugepage allocator），再问 PAC（page allocator classic），PAC 内部再按代价从缓存一路走到系统调用。判据不是"哪个更快"，而是**一次 miss 能不能被摊成一批**——HPA 能，PAC 明确不能。

本篇讲这个分派与两条阶梯，以及它们共用的三个缓存件：ecache、SEC、retained 增长序列。每一步都对照 jemalloc `5.4.0` 的 `路径:行号`。

## One Entry, Two Backends

`pa.h` 的文件头已经把 5.4 的结构写明：页分配器"把每个页级请求直接调用 `pac_*()` / `hpa_*()` 分派给两个后端之一"（`include/jemalloc/internal/pa.h:15-20`）。5.4 之前这里是一张 `pai_t` vtable；`ChangeLog:78-81` 记着把它换成了直接调用、删掉 `pai_t`/`pai.h`，并把 deferred-work 与 decay 编排移出 arena。

入口本身很短（`src/pa.c:132-143`）：

```c
edata_t *edata = NULL;
if (!guarded && pa_shard_uses_hpa(shard)) {
	edata = hpa_alloc(tsdn, &shard->hpa, size, alignment,
	    zero, /* guarded */ false, slab, deferred_work_generated);
}
if (edata == NULL) {
	edata = pac_alloc(tsdn, &shard->pac, size, alignment, zero,
	    guarded, slab, deferred_work_generated);
}
```

两个观察：

- HPA 只处理非 guarded 请求；guarded 一律落到 PAC（`src/pa.c:133-136`）。
- 传给 HPA 的 `frequent_reuse` 就是上层传下来的 `slab` 参数（`src/pa.c:134-135`），语义是"这批内存要切成 slab"；后文会看到它专用来绕过一个尺寸上限。

分配成功后有两件事在 PA 层统一做，而不在后端做（`src/pa.c:145-155`）：`emap_remap` 改写地址到元数据的映射并写入 `szind` 与 slab 位；若这是 slab 且尺寸大于两页，还要对内部每一页登记同一个 szind（`emap_register_interior`）。所以"这块地址属于哪个 size class"是 PA 记账的结果，不是分配器返回时自带的。

释放则按 extent 自己的位分派（`src/pa.c:219-237`）：`edata_pai_get(edata)` 是 HPA 就还 HPA，否则还 PAC。这里有一条容易漏掉的语义，`include/jemalloc/internal/pa.h:78-85` 写得很清楚：`use_hpa` 可以从真改假（例如装上自定义 extent hooks），但**已经由 HPA 分配的地址仍然还回 HPA**。因此一个 arena 的常驻内存可以是两个后端的混合体，统计也只能分别看。`pa_dalloc` 还故意不清 slab 位（`src/pa.c:223-229`），注释说实现方可能用它做缓存决策——这是 5.4 删掉 pai 抽象后残留的接口语义，不要当成 bug。

## Defaults Decide Which Ladder You Are On

在 `src/jemalloc.c` 的三个全局量里，两个后端都是**默认关闭**的：

```c
bool             opt_hpa = false;                       /* :197 */
hpa_shard_opts_t opt_hpa_opts = HPA_SHARD_OPTS_DEFAULT; /* :198 */
sec_opts_t       opt_hpa_sec_opts = SEC_OPTS_DEFAULT;   /* :199 */
sec_opts_t       opt_pac_sec_opts = {0, ...};           /* :200-202 */
```

`opt_pac_sec_opts.nshards = 0` 意味着 PAC 的 SEC 默认不启用；打开它的 malloc_conf 键叫 `experimental_pac_sec_nshards`（`src/conf.c:917-919`）。HPA 由 `opt.hpa` 打开，打开后每个新 arena 在创建时启用（`src/arena.c:1560-1574`），arena 0 因为 boot 阶段背景线程状态还没确定，延到初始化收尾时补启用（`src/jemalloc_init.c:570-583`）。

所以默认配置真正跑的是"PAC 无 SEC"的简化阶梯。本篇仍把完整阶梯讲全，但每一级都标出它在默认值下是否存在。

## The PAC Ladder Is Ordered by Cost

`pac_alloc_real` 的尝试顺序（`src/pac.c:155-267`）：

| 顺序 | 来源 | 进入条件 |
| :--- | :--- | :--- |
| 1 | SEC | 非 guarded、不要求清零、`alignment <= PAGE`、`size <= sec_max_alloc`（:163-164） |
| 2 | `ecache_pinned` | 非 guarded、`has_pinned` 且池非空（:185-189） |
| 3 | `ecache_dirty` | 无条件尝试（:191-194） |
| 4 | `ecache_muzzy` | `muzzy_decay_ms != 0`（:196-199，判定见 :125-128） |
| 5 | `ecache_retained` 批量增长 | 大 size class 被禁用且 `maps_coalesce \|\| opt_retain`（:201-250） |
| 6 | `ecache_retained` 常规增长 | 以上全 miss（:252-259） |

SEC 那一行的 `sec_max_alloc` 有两个关闭条件，`pac_init` 写得很直白：SEC 未配置，或 `dirty_decay_ms == 0`，都把它置 0（`src/pac.c:112-120`）。后者是策略耦合而非实现细节——**dirty decay 被设成立即归还时，SEC 缓存的脏 extent 就没有意义**，于是整条第一级被摘掉。

剩下几级的排序理由不是命中率，而是"越靠后越接近系统调用"：前四级只碰缓存自己的锁，第五、六级要拿 `grow_mtx` 并且可能 `mmap`。第 5 级与第 6 级的区别不在尺寸，而在**要不要顺手多拿一点**：当大对象不按 size class 向上取整时，同样大小的连续分配无法复用同一块 extent，代码于是额外映射一块可合并的 extent，把多余部分切下来放回 dirty（`src/pac.c:201-245`）。这段在 `maps_coalesce` 与 `opt_retain` 都关掉时跳过，注释解释是"那时 VM 不便宜，而且只能合并同一 `VirtualAlloc` 来的区间"（:211-219）。

guard 有一个前置捷径：非频繁复用的 guarded 请求根本不进这条阶梯，直接去造一块新的（`src/pac.c:303-317`），因为"不常复用的 guarded extent 从不进 ecache"。新造时的做法是先按 `size + 两侧 guard 页` 分配普通 extent，再现场加 guard 页（:269-294）。

## What Lives in the Four Ecaches, and Why Coalescing Is Deferred

`ecache_t` 只有五个字段（`include/jemalloc/internal/ecache.h:10-23`）：一把锁、一个 `eset`、一个 `guarded_eset`、状态、以及 `delay_coalesce`。guarded extent 走独立集合，因为切分 guarded extent 不被支持，所以 guarded 只做精确匹配（`src/extent.c:459-467`）。四个池的 RSS/VSZ 语义与 decay 曲线见 [Memory Reclaim and Decay](/docs/CS/memory/jemalloc/Decay_and_Purge.md)，这里只看合并时机：

| 池 | `delay_coalesce` | 代码注释给出的理由 |
| :--- | :--- | :--- |
| dirty | true | 缓存很可能马上被复用，而合并/切分代价不低（`src/pac.c:54-63`） |
| muzzy | false | 不在关键路径上，直接合并（`src/pac.c:64-71`） |
| retained | false | 永远不会被驱逐，没有"延迟到驱逐时合并"的机会（`src/pac.c:72-81`） |
| pinned | true | 不参与 decay，按延迟合并处理（`src/pac.c:82-86`） |

延迟合并的直接后果在 `extent_record`（`src/extent.c:1032-1105`）：非延迟池当场合并；延迟池只对 `>= SC_LARGE_MINCLASS` 的 extent 立即合并，且合并后的尺寸上限被 `1 << opt_lg_extent_max_active_fit` 卡住，小块原样入池、等驱逐时再合。guarded extent 直接跳过合并（:1043-1045）。

因此"dirty 池里有相邻空闲 extent 却没合并"是设计预期，不是泄漏。它与下一节的 fit 规则是一对：**入池时少合并，出池时不过度切分**，共同限制碎片。

## Fit Is a Bitmap Scan With an Anti-Fragmentation Cap

ecache 的索引不是链表，而是 `eset`：按页尺寸索引（pszind）分桶，每桶一个堆，桶级存在位图里。查找从 `size` 向上量化到的桶开始，用 `fb_ffs` 跳过空桶（`src/eset.c:344-347`），在候选桶里取"最老/最低"的 extent（比较规则见 [Address to Metadata Mapping](/docs/CS/memory/jemalloc/Address_Map.md) 对 sn 与地址的说明）。

关键的一行是循环里的提前退出：

```c
if ((sz_pind2sz(i) >> lg_max_fit) > size) {
	break;
}
```

（`src/eset.c:349-359`。）也就是"要切的 extent 不能比请求大出 `2^lg_max_fit` 倍以上"。取值按池区分（`src/extent.c:442-457`）：

| 池 | `lg_max_fit` | 附加规则 |
| :--- | :--- | :--- |
| dirty（延迟合并） | `opt_lg_extent_max_active_fit`，默认 6（`include/jemalloc/internal/extent.h:17-22`） | — |
| pinned | `SC_PTR_BITS`，等于不设上限 | `prefer_small`：命中第一个装得下的桶就返回（`src/eset.c:378-380`） |
| muzzy / retained | `SC_PTR_BITS` | — |

原因就写在 `src/extent.c:442-452`：延迟合并下，一块大 extent 被切小之后，小块释放时不会与大块合并回去，大块于是再也满足不了原来的尺寸；给可切分尺寸设上限就是为了限制这种"一次切小、永久变小"的损耗。pinned 豁免，因为它永远不会被 purge，切小了也没有后续归还问题；反过来它用 `prefer_small`，避免为一个中等请求拆掉大块 pinned 区域。

还有一个开关会改变行为：若不允许切分与合并（`!maps_coalesce && !opt_retain`，典型是未开 retain 的 Windows）或请求是 guarded，则只做精确匹配（`src/extent.c:467`，理由在 :459-466）。这解释了为什么同一份代码在 Linux 与 Windows 上的碎片形态不同。

## Growing the Retained Pool Is One Serialized Ladder

retained 池的增长不是每次按请求大小 `mmap`，而是走一条几何级数。`exp_grow_t` 只有一个游标和一个上限（`include/jemalloc/internal/exp_grow.h:7-21`）：`exp_grow_size_prepare` 从游标开始找第一个够大的尺寸（:23-37），成功后 `exp_grow_size_commit` 把游标向前推（:39-46）。于是同一 arena 连续增长会拿到越来越大的块，减少互不相邻的 VM 区间。

整条增长路径由每个 PAC 一把 `grow_mtx` 串起来：`extent_alloc_retained` 先拿锁、先在 retained 池里回收，回收失败且允许 retain 时才真正增长（`src/extent.c:876-903`）。增长本身要先把对齐余量算进去（`alloc_size_min = size + PAGE_CEILING(alignment) - PAGE`，:736-740），再按 `exp_grow` 取尺寸、调 `ehooks_alloc`、切出请求部分；前后余料经 `pac_record_grown` 进入 retained 或 pinned 池（:785-800）。

一个容易写错的细节：pinned 的那次增长**不推进游标**（`src/extent.c:841-849`），注释说"pinned 是有限资源，超大余料只会浪费它"。`exp_grow.limit` 暴露成 `retain_grow_limit` mallctl，只影响"没有请求逼着它长"的情形（`include/jemalloc/internal/pac.h:277-287`）。

## SEC Is a Lock Strip, Not a Cache of Bytes

SEC（small extent cache）不是按字节缓存，而是按**（shard, pszind）切出来的锁条**。`sec_bin_pick` 直接算 `shard * npsizes + pszind` 下标（`src/sec.c:100-106`）；`sec_alloc` 从本线程固定的 shard 起做 trylock 轮转，任一桶命中即返回；全部轮完仍未命中，才回到本线程的桶上加阻塞锁取一次，并且只有到这一步才记 miss（`src/sec.c:163-229`）。线程的 shard 用 Lemire 的乘高位取模选定，而不是 `%`（`src/sec.c:83-98`）。

取出与放回都发生在表头：`sec_bin_alloc_locked` 取 `freelist` 第一个（`src/sec.c:141-144`），`sec_bin_dalloc_locked` 也 `prepend` 到表头（:244）。超过 `max_bytes` 时从表尾（最老的）开始回落到 `max_bytes - max_bytes/4`，即一次冲掉约四分之一（:251-273）。

HPA 的 SEC 与 PAC 的 SEC 有一个本质差别：**只有 HPA 会在 miss 后往里填**。`sec_fill` 在 HPA 批量分配有富余时把多出来的 extent 塞进 SEC（`src/hpa.c:949-963`；填不满时的溢出回滚在 `src/sec.c:345-396`）。PAC 一侧的注释则明说"与 HPA 不同，PAC 没有批量分配原语，我们有意不在 miss 时回填 SEC；extent 只通过 dalloc 路径进入缓存"（`src/pac.c:174-178`）。所以看到 PAC 的 SEC 命中率低时不必急着调参：它本来就不做预取。

默认值只对 HPA 的 SEC 生效：`nshards = 2`、`max_alloc = max(32 KiB, PAGE)`、`max_bytes = max(256 KiB, 4 * max_alloc)`（`include/jemalloc/internal/sec_opts.h:32-37`）。PAC 的 SEC 默认 `nshards = 0`，见上一节。

## HPA Amortizes a Miss

HPA 的 `hpa_alloc` 在入口挡回两类请求：**要求对齐大于一页，或要求清零**（`src/hpa.c:912-915`）。这不是能力缺失而是分工：对齐余量会破坏"整页"假设，清零应当交给 `mmap` 的 demand-zero 才划算，两种请求由 PA 回落到 PAC。随后 `slab_max_alloc` 限制单次分配上限，但 `frequent_reuse && size <= HUGEPAGE` 可以绕过（`src/hpa.c:917-930`）。理由在注释里：这些请求来自 arena bin、会被整块切成 slab，不存在巨大页内部的松弛，绕过后也不增加内部碎片。

命中路径与 PAC 类似——先查 SEC（`src/hpa.c:931-938`），不中才批量分配。批量由 `hpa_alloc_batch_psset` 完成（`src/hpa.c:812-876`）：先在 `shard->mtx` 下尝试不增长的分配；不够且未 OOM 才拿 `grow_mtx`，**再查一次**以化解与其他线程的增长竞争（:831-844），然后在**不持有 `shard->mtx`** 的情况下向 central 要一个 pageslab（:846-856，注释解释此时小对象分配与释放仍可继续），最后插回 psset 并补足（:863-871）。

批量做几份由 `sec_calc_nallocs_for_size` 决定（`src/sec.c:108-135`）：目标是填满 SEC 的 `1/SEC_MAX_BYTES_DIV`，即 `max_bytes / size / 4`，下限 2、上限 8（`include/jemalloc/internal/sec.h:108-114`）。注意这个函数先看 `sec_size_supported`：**SEC 关掉或尺寸超过 `max_alloc` 时，min/max 都退回 1，批量退化为单次**。所以 HPA 的"摊销"不是无条件的，它恰好与 SEC 的适用范围同界——一次 miss 代价至多摊到 8 个 extent 上，剩下的顺手成为 SEC 库存，这正是 PAC 不做的那一件事。

## expand and shrink Belong to PAC

`pa_expand` / `pa_shrink` 只对 PAC 有效：HPA 的同名操作是桩，PA 在调用前就按 `edata_pai_get` 直接返回失败（`src/pa.c:170-176`，:200-206）；guarded extent 也一律拒绝（:165-167，:195-197）。这不是临时缺口，而是接口保留——上层 `rallocx` 会据此退化成"分配新块 + 拷贝"。

PAC 的扩张顺序与分配阶梯同构：pinned extent 只从 pinned 池找邻居（`src/pac.c:336-351`，注释解释只有 pinned 池可能持有可合并的 pinned 邻居，且不应为了原地增长去问 hooks）；普通 extent 依次试 dirty、muzzy、retained 增长（:351-368）。找到邻居后必须 pinned 属性一致才能合并（:369-371）。收缩则是切出尾部，按属性放回对应池（`src/pac.c:391-415`）。

## Version and Verification Notes

- 本篇的跨版本判断只有一条：5.4.0 用直接调用替换 PAI vtable 并删除 `pai_t`/`pai.h`，依据 `ChangeLog:78-81`。本地是**单提交浅历史、只有 `5.4.0` tag**，没有 5.3 源码树，因此不写任何"5.3 里某函数如何"的断言。
- 本机 jemalloc 构建失败（`autom4te` 的 perl 解释器失效），`jemalloc_internal_defs.h` 不存在，`PAGE`、`SC_LARGE_MINCLASS`、`SC_PTR_BITS`、`HUGEPAGE` 都没有本地数值。因此凡依赖它们的具体字节数一律不写；文中的 32 KiB / 64 KiB / 256 KiB 都是源码字面量（`src/jemalloc.c:200-202`、`include/jemalloc/internal/hpa_opts.h:153-155`、`include/jemalloc/internal/sec_opts.h:32-37`），可直接核对。
- **PAC 的 SEC 默认关闭**（`opt_pac_sec_opts.nshards = 0`，`src/jemalloc.c:200-202`），**HPA 默认关闭**（`src/jemalloc.c:197`）。不少二手描述把 SEC 当成默认路径，本篇按源码把两者分开写。
- HPA 的 `hpa_shard_opts` 全部自称实验性，注释明确说随时可能被弃用（`include/jemalloc/internal/hpa_opts.h:11-15`）；本篇只引用默认值，不当作稳定契约。
- `SEC_MIN_NALLOCS = 2`、`SEC_MAX_NALLOCS = 8`、`SEC_MAX_BYTES_DIV = 4` 是源码字面量（`include/jemalloc/internal/sec.h:108-114`）。
- `lg_max_fit` 的默认值 6 是源码字面量（`include/jemalloc/internal/extent.h:21`），但 6 代表的是"最多切大 64 倍"，不是字节数。
- 未做任何性能测量（无法构建、未跑 benchmark），本篇不给命中率、延迟或内存收益数字。

## Links

- [jemalloc](/docs/CS/memory/jemalloc/jemalloc.md)
- [Memory Reclaim and Decay](/docs/CS/memory/jemalloc/Decay_and_Purge.md)
- [Arena, Bin and Slab](/docs/CS/memory/jemalloc/Arena_Bin_Slab.md)
- [Address to Metadata Mapping](/docs/CS/memory/jemalloc/Address_Map.md)
- [Size Classes](/docs/CS/memory/jemalloc/Size_Classes.md)
- [Allocation Fast Path](/docs/CS/memory/jemalloc/Fastpath.md)

## References

- [jemalloc: concurrent memory allocator](https://jemalloc.net/)
- [jemalloc GitHub 仓库](https://github.com/jemalloc/jemalloc)
- [mmap(2)](https://man7.org/linux/man-pages/man2/mmap.2.html)
