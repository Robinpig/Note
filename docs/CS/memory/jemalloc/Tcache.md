## Introduction

线程缓存是 jemalloc 可扩展性的第一道，也是最便宜的一道：命中它就不必碰任何锁。但它同时是 RSS 的头号来源——每个线程每个尺寸类都留一小叠对象，线程数一多就还不清。

5.3 之前这道题的答案是静态的：每个 bin 固定给若干个槽，填满了就按固定比例刷回。5.4 把它换成了**按实测需求自适应**：每个 bin 自己维护"下次该填几个"（`bin_nfill`）和"这次该留几个"（`bin_nretain`），并在刷回时**优先丢远端指针**。这是 5.4 唯一一条标为"incompatible"的行为变更（ChangeLog:32-41），也是本篇的主线。基线 jemalloc `5.4.0`，`路径:行号` 相对 jemalloc 仓库根。

## The cache_bin Stack

一个 bin 就是一个向下生长的指针栈（`include/jemalloc/internal/cache_bin.h:81-86`）：

```
(low addr)                                                  (high addr)
|------stashed------|------available------|------cached-----|
^                   ^                     ^                 ^
low_bound(derived)  low_bits_full         stack_head        low_bits_empty
```

元数据只有一个真指针：`stack_head`。其余边界只存**低 16 位**（`typedef uint16_t cache_bin_sz_t`，cache_bin.h:24），注释给出成立条件："单个栈所占空间不会超过 2^16 字节，而且这些低位只做相等比较"（cache_bin.h:76-81）。由此一个 bin 最多缓存 `CACHE_BIN_NCACHED_MAX == (1 << 16) / sizeof(void *) - 1` 个对象，即 8191 个（cache_bin.h:44-49）——200 的默认上限离它很远，但这个上界才是 `uint8_t` 索引之类"想当然"的约束真正的来源。快路径上那次比较就是 `low_bits != bin->low_bits_low_water`（cache_bin.h:403）。

结构体字段顺序也是设计：`stack_head` 与 `tstats` 紧挨着，注释说"两者都被频繁修改，放在一起更可能落在同一条 cacheline，从而少写回"（cache_bin.h:96-101）。栈顶空时 `stack_head` 指向"所属数组再过去一格"，因此读取空位是安全的——数组多留了一格（[Allocation Fast Path](/docs/CS/memory/jemalloc/Fastpath.md) 里那条注释的出处）。

`low_bits_full` 只在 stash 时被调整（cache_bin.h:114-124），`low_bits_empty` 初始化后不变（cache_bin.h:126-131）。禁用 bin 用一个哨兵栈 `disabled_bin`，判据是 `bin->stack_head == cache_bin_disabled_bin_stack()`（cache_bin.h:39、182-198），因此"启用/禁用"不依赖 `ncached_max` 是否为 0。

## A Documented Undefined Behavior

`cache_bin_ncached_get_internal()` 读 `stack_head` 两次算差值，注释直说这里是 UB：

> We have undefined behavior here; if this function is called from the arena stats updating code, then stack_head could change from the first line to the next one. Morally, these loads should be atomic, but compilers won't currently generate comparisons with in-memory operands against atomics, and these variables get accessed on the fast paths. This should still be "safe" in the sense of generating the correct assembly for the foreseeable future, though.

（cache_bin.h:252-261）

这是一处**明知故犯**：统计路径可能与持有线程并发改 `stack_head`，而把快路径变量改成原子会让编译出的比较变贵。读的时候要知道：这条依赖的是"当前编译器行为"，不是语言保证。同文件另有 `_local` 版本（cache_bin.h:264-274），要求调用方确认无并发修改——自适应策略全部走 `_local`。

## ncached_max Is a Ceiling, Not a Target

每个 bin 的容量上限由 `tcache_ncached_max_compute()` 算出：small 类取 `bin_infos[szind].nregs << TCACHE_LG_NSLOTS_MUL`（即 region 数的 2 倍，tcache.h:57），强制为偶数（注释："需要候选值为偶数——我们假定除以 2 之后仍是正数，例如刷回时"，src/tcache.c:726-731），再夹到 `[TCACHE_NSLOTS_SMALL_MIN, TCACHE_NSLOTS_SMALL_MAX]` = `[20, 200]`（tcache.h:54-55；src/tcache.c:710-715、732-738）。large 类固定 20（tcache.h:56、src/tcache.c:719-721）。

也就是说**小 size class 缓存得少、大 size class 缓存得多**，直到 200 封顶；`nregs` 本身来自 slab 大小，所以这条上限把 [Size Classes](/docs/CS/memory/jemalloc/Size_Classes.md) 的 slab 代数直接传导到了缓存策略上。

偶数要求与 `[20,200]` 区间都由编译期钉住：`#error "Bad default tcache slot counts"` 检查非零/偶/严格有序，一条 typedef 数组尺寸检查 `TCACHE_NSLOTS_SMALL_MAX <= CACHE_BIN_NCACHED_MAX`（src/tcache.c:705-715）。

运行期只有 `malloc_conf` 的 `tcache_ncached_max` 还能改这个上限（src/tcache.c:745-756 的 `tcache_get_default_ncached_max()` 分支；解析在 src/conf.c:655-661）——它是 5.3.1 引入、**5.4 唯一保留的旧式旋钮**（ChangeLog:36-41）。

## Low Water Makes Adaptation Possible

自适应需要一个观测量：上一轮 GC 到这一轮之间，这个 bin **实际被取走了几个**。`low_bits_low_water` 记的就是"自上次 GC 以来未被用过的第一个位置"，即期间达到的最小缓存量（cache_bin.h:103-111）。`cache_bin_alloc_impl` 在跨过水位时把它下调（cache_bin.h:403-420），`cache_bin_low_water_get` 则把"低水位到空"的距离算成期间用量（cache_bin.h:344）。

于是 `used_since_gc = ncached - low_water` 就是这段时间的真实需求，**六个调整函数全部围绕它展开**。

## The Six Adjustment Rules

`tcache_ncached_target.h` 整文件只有这 8 个 inline 函数（不含 min/max 两个边界），全部是纯位运算，没有除法也没有历史窗口：

| 函数 | 规则 | 位置 |
| :--- | :--- | :--- |
| `..._target_min` | `ncached_max < 2 ? ncached_max : 2` | tcache_ncached_target.h:6-10 |
| `..._target_max` | `max(ncached_max >> 1, min)` | :12-17 |
| `fill_after_refill` | 填完就 `nfill << 1`，封顶 `target_max` | :19-26 |
| `fill_after_underuse` | 没用满就 `nfill >> 1`，保底 `target_min` | :28-35 |
| `retain_after_refill` | 目标 = `nfilled > ncached_max>>1 ? ncached_max : nfilled<<1`，只增不减 | :37-46 |
| `retain_after_gc` | `used + max(used>>2, 1)`，超过 `ncached_max - headroom` 则取满；`used == 0` 时直接降到最低 | :48-66 |
| `retain_after_overflow` | 装不下就 `nretain >> 1` | :68-79 |
| `flush_remain` | `nretain < max ? nretain : max - 1` | :81-89 |

三条值得单独说的性质：

- **乘性增减、有上下界**。填的时候翻倍、闲的时候减半，配合 `target_min`/`target_max` 把每个 bin 限制在 `[2, ncached_max/2]` 次幂步长的格点上，因此策略收敛但不会震荡到 0。
- **`retain_after_gc` 留 1/4 余量**（`headroom = used >> 2`，至少 1）。缓存"上次用的量 + 一点富余"，而不是"上次剩下的量"——这是把突发流量算进去的方式。
- **`flush_remain` 那句注释是整章最实用的一行**：`Leave room for the allocation whose dalloc detected the overflow.`（tcache_ncached_target.h:85）。也就是说触发溢出而被迫刷回的那一次，**本次要放进去的对象必须还有位置**，所以保留数是 `ncached_max - 1` 而不是 `ncached_max`。少写这一格就会立刻再溢出、无限刷回。

## Where the Three Counters Update

`bin_nfill` 与 `bin_nretain` 都存在 `tcache_slow_t` 里（`include/jemalloc/internal/tcache.h:94-95`，两个 `cache_bin_sz_t[SC_NBINS]` 数组），只有三个更新点：

1. **填充路径**：`tcache_alloc_small_hard()` 以当前 `nfill` 为**下限**、`target_max` 为上限请 arena 填一次（`arena_ptr_array_fill_small`），随后按实际填进的数量更新 `nretain`（`retain_after_refill`）并把 `nfill` 翻倍（src/tcache.c:422-455）。注释说明为何给 arena 留上界："Let the arena finish draining a slab beyond the adaptive minimum."（src/tcache.c:434）——一次 slab 抽干比按个数抠更省锁。
2. **GC 路径**：`tcache_gc_small()` 在 `low_water > 0`（期间确有取用）时先 `fill_after_underuse` 压低 `nfill`，再按 `retain_after_gc` 重设 `nretain`，最后把超出部分刷掉（src/tcache.c:227-250）。
3. **溢出路径**：`tcache_dalloc_small()` / `tcache_dalloc_large()` 在 `cache_bin_dalloc_easy` 失败时走 `retain_after_overflow` + `flush_remain`，刷完再放，并用 assert 保证一定放得下（`include/jemalloc/internal/tcache_inlines.h:189-222`、:227-247）。

大对象那条路径里 `retain_after_overflow(max, max)` 传的 nretain 就是 max——large bin 没有独立 `bin_nretain` 状态，直接用溢出规则现算（tcache_inlines.h:238-242）。

## GC Is Event-Driven, Time-Gated and Rotating

GC 不是独立线程，也不是每次 free 都跑，而是挂在[线程事件](/docs/CS/memory/jemalloc/Fastpath.md)上的一个 alloc 事件（`te_alloc_tcache_gc`），触发节奏由 `opt_tcache_gc_incr_bytes = 65536` 决定（src/tcache.c:35、:82；`tcache_gc_enabled()` 就是"这个增量 > 0"，src/tcache.c:1252）。

真正执行前还有两道闸（src/tcache.c:359-420）：

- **时间闸**：距上次 GC 不足 `TCACHE_GC_INTERVAL_NS`（10ms，tcache.h:46）就直接跳过本次事件。注释写得很白："time interval is too short, skip this event."
- **工作量闸**：一次事件最多处理 `TCACHE_GC_SMALL_NBINS_MAX` 个 small bin 与 `TCACHE_GC_LARGE_NBINS_MAX == 1` 个 large bin（tcache.h:47-48；small 那边是 `SC_NBINS >> 3`，默认设置下为 4）。游标 `next_gc_bin_small` / `next_gc_bin_large` 存在线程状态里（tcache.h:88-89），扫到末尾就回绕（src/tcache.c:388-418）。

三条合起来的含义：**每 64KB 分配量给一个 GC 机会，每 10ms 只允许真的做一次，每次只碰一小撮 bin**。这把"清缓存"的成本摊到不阻塞任何单次调用上，代价是空闲内存最多要等一整轮轮转才被归还。

`TCACHE_GC_INTERVAL_NS` 与轮转游标在 5.4 之前并不存在；旧的按 free 计数的 `gc_dalloc` 触发器在 5.4 树里已经查无此名（全树 grep 零命中），对应的就是 ChangeLog:32-41 那条"移除七个 legacy 旋钮"。

## Locality-Aware Flushing

同一尺寸类的对象可能来自不同 NUMA 节点、不同页范围。刷回时**丢哪一个**因此是有意义的，jemalloc 的做法是先问 arena 要一个"局部性锚点"：`arena_locality_hint(tsd_tsdn(tsd), tcache_slow->arena, szind)`（src/tcache.c:260）。拿到锚点后：

- 两个候选判远范围：**slab 范围**（`[addr, addr + bin_infos[szind].slab_size)`）与**邻居范围**（`addr ± TCACHE_GC_NEIGHBOR_LIMIT`，即 ±2M，tcache.h:45）。后者之所以合理，注释解释是保留虚拟内存本身按指数增长、"从 2M 起，好让每个 shard 保留的互不连续的虚拟地址段数量受限"（src/tcache.c:103-107）。
- 一次遍历同时数出两个"远端指针"数量 `n_remote_slab` 与 `n_remote_neighbor`（src/tcache.c:115-125），然后**优先用邻居锚**当判远范围，条件是"非邻居指针数不少于本次打算刷掉的量 `nflush`"（src/tcache.c:136-142）；否则退回更严格的 slab 锚（src/tcache.c:143-149）。注释明确承认两者谁大没有保证，因为 slab 大小是动态的、可能超过 2M（src/tcache.c:126-130）。
- 判完远就 **shuffle**：`tcache_gc_small_bin_shuffle` 把非远端指针冒泡到栈顶、远端压到底部（栈顶才是分配端），保持非远端者之间的相对顺序不变，最后一段扫描把底部剩下的也换出去，收尾有三段 assert 验证洗牌正确（src/tcache.c:154-224）。注释说得很直白：既然底部这些反正要被刷掉，它们彼此之间的顺序无所谓（src/tcache.c:295-301）。
- 两个边界直接跳过洗牌：`nremote == 0`（全本地，没什么可挑）与 `nremote == ncached`（全远端，整栈刷掉）（src/tcache.c:289-291）；`nflush == ncached` 时更早跳到 flush（src/tcache.c:253-255）。

large bin 的 GC 刻意**不做**局部性处理，注释给出理由："large allocations have no slab locality to preserve, so just flush the bottom items, without any locality check."（src/tcache.c:315-320）——这一条正是 small/large 两套策略的分界，不是实现偷懒。

## Stash and Use-after-free Detection

`stashed` 区不是缓存，是给 UAF 检测用的隔离区。`tcache_dalloc_small` 里那条"不要标 unlikely"的注释值得引用：过了 `free_fastpath` 之后常见情况已处理完，走到这里常常就是少见情况（tcache_inlines.h:192-196）。判据是 `cache_bin_nonfast_aligned(ptr)`——被采样并 junk 过的指针带着特殊对齐；命中就先无条件 junk，再 `cache_bin_stash`，塞不下（bin 满）就 fall through 到溢出刷回分支（tcache_inlines.h:197-210）。

这些指针的存在也正是 [Allocation Fast Path](/docs/CS/memory/jemalloc/Fastpath.md) 里"用对齐逃出快路径"的另一半；`opt_debug_double_free_max_scan` 控制的重复释放扫描（cache_bin.h:455-475）同样只在 debug 构建里存在。

## Version and Verification Notes

- 本篇的 5.4 新增/删除判断依据两处：`ChangeLog:7-110` 原文，以及 5.4 树内的**存在性**证据（`bin_nfill` / `bin_nretain` / `arena_locality_hint` / `TCACHE_GC_*` 都在；旧名 `gc_dalloc` 全树 grep 零命中）。本地是浅历史（单提交、只有 `5.4.0` tag），**没有做过 5.3 源码 diff**，因此不许写"5.3 的某函数怎样"这类具体断言。
- `opt_tcache_max = 1 << 15`（32KB，src/tcache.c:29）与注释里的 `global_do_not_change_tcache_maxclass`（tcache.h:135-142、src/tcache.c:1210）是两处独立声明，前者的值是运行期可改的 boot 选项，后者是"不该在运行中被改变"的全局快照。
- `TCACHE_GC_SMALL_NBINS_MAX == 4` 是把 `SC_NBINS == 36` 代入公式得到的**推导值**，非实测；`SC_NBINS` 本身在别平台的取值见 [Size Classes](/docs/CS/memory/jemalloc/Size_Classes.md) 的推导表。
- 自适应策略的效果量级本机无法测（构建失败、没有跑过任何 benchmark），本篇只描述机制与代价结构，不给性能数字。

## Links

- [Allocation Fast Path](/docs/CS/memory/jemalloc/Fastpath.md)
- [Arena, Bin and Slab](/docs/CS/memory/jemalloc/Arena_Bin_Slab.md)
- [Size Classes](/docs/CS/memory/jemalloc/Size_Classes.md)
- [Memory Reclaim and Decay](/docs/CS/memory/jemalloc/Decay_and_Purge.md)
- [jemalloc](/docs/CS/memory/jemalloc/jemalloc.md)

## References

- [jemalloc: concurrent memory allocator](https://jemalloc.net/)
- [jemalloc GitHub 仓库](https://github.com/jemalloc/jemalloc)
