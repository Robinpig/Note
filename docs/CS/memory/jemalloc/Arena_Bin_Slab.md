## Introduction

线程缓存没命中时，请求落到 arena 的某个 bin 上。bin 看起来只是"一组同尺寸的空闲对象"，但真正难的不是切出一个 region，而是**管住一批 slab 的生死**：哪些还有空位、哪些刚满、哪些刚空、释放整块 slab 时锁该怎么放。

jemalloc 把这份账目拆成三处：一个专用指针 `slabcur`、一个按顺序排的非满堆、一个满链表。三者的关系由注释钉死——"`slabcur` 与 `slabs_{nonfull,full}` 无关；一旦 `slabcur` 被改指，原来的 slab 必须被释放或插进后两者之一"（`include/jemalloc/internal/bin.h:33-38`）。围绕这条不变式，本章的主线是：**bin 是 slab 的四种状态加一套锁协议，而这套协议里最难的部分是"在哪里放锁"**。基线 jemalloc `5.4.0`，`路径:行号` 相对 jemalloc 仓库根。

## Geometry Is Decided Once at Boot

每个 bin 的几何形状只算一次，存在只读的 `bin_infos[]` 里（`bin_info_t`，`include/jemalloc/internal/bin_info.h:26-45`），全体 arena 共享同一份——注释给的理由是省内存与避免 cacheline 伪共享（bin_info.h:7-11）。三个量（`src/bin_info.c:14-18`）：

```c
bin_info->reg_size = ((size_t)1U << sc->lg_base)
    + ((size_t)sc->ndelta << sc->lg_delta);
bin_info->slab_size = (sc->pgs << LG_PAGE);
bin_info->nregs = (uint32_t)(bin_info->slab_size / bin_info->reg_size);
```

`reg_size` 的表达式与 [Size Classes](/docs/CS/memory/jemalloc/Size_Classes.md) 里 `sc_t` 的定义逐字一致（`include/jemalloc/internal/sc.h:315-337`），`pgs` 就是该 size class 的"每 slab 页数"（sc.h:333-334）。于是 **slab 大小不是全局常量，而是跟着 size class 走的**：小对象用小 slab，大一点的 small class 用更多页，`nregs` 是两者相除的结果。

整块 slab 被当成 `nregs` 个首尾相接的 region（bin_info.h:12-25 的示意图）。每个 slab 的元数据只有一个位图，没有别的：

```c
struct slab_data_s {
	/* Per region allocated/deallocated bitmap. */
	bitmap_t bitmap[BITMAP_GROUPS_MAX];
};
```

（`include/jemalloc/internal/slab_data.h:7-11`）

"哪几个 region 空着"全部由这一张图承载，`nfree` 则被塞进 `edata_t.e_bits` 的位域里（`include/jemalloc/internal/edata.h:206-209`、:427-430），与 `binshard` 共用一个 64 位字（edata.h:211-219）。本节不写任何绝对数字：`PAGE`、`SC_LG_SLAB_MAXREGS` 都来自构建期生成的 `jemalloc_internal_defs.h`，本机构建失败、没有这份头文件，`slab_size` / `nregs` 的具体值无从谈起。

## A Slab Lives in Four Places

一个 slab 的 edata 可能出现在四个地方，理解 bin 就是理解这四者的迁移（`src/bin.c`，`bin_t` 定义见 `include/jemalloc/internal/bin.h:23-50`）：

| 位置 | 容器 | 含义 |
| :--- | :--- | :--- |
| `bin->slabcur` | 单个指针 | 当前分配目标。空闲 region 用光后仍会停留（`nfree == 0`），直到下次 refill 才被移走 |
| `bin->slabs_nonfull` | `edata_heap_t` | 还有空位的 slab，按 (sn, addr) 排序 |
| `bin->slabs_full` | `edata_list_active_t` | 一个空位都没有的 slab |
| 栈上 `fresh_slab` | 局部变量 | 刚从 `arena_slab_alloc()` 拿到、尚未挂进任何集合 |

`slabcur` 可以暂时"满着"这件事有直接证据：`bin_refill_slabcur_no_fresh_slab()` 的前置断言是 `bin->slabcur == NULL || edata_nfree_get(bin->slabcur) == 0`，随后才把满的 slabcur 挂进 `slabs_full`（src/bin.c:288-303）；`bin_lower_slab()` 里也按 `edata_nfree_get(bin->slabcur) > 0` 分流处理（src/bin.c:223-227）。所以不要把 `slabcur` 读成"非满 slab 的缓存"，它只是一个**许可**：允许从它里面切区域，切完就作废。

非满堆的排序键是 `edata_snad_comp()`：先比 `sn`，相同再比地址（`include/jemalloc/internal/edata.h:777-827`）。`sn` 来自 `extent_sn_next()` 的原子自增（`src/extent.c:66-69`），extent 合并时取两者较小值（extent.c:1448-1450），因此 **sn 小 = 更早从页分配器拿到 = 更老**，注释所说的"oldest/lowest in memory"（bin.h:41-46）由此成立。排序的目的不是优雅，而是让空位先被老 slab 吃掉，好让新 slab 整体空出来归还——这是 slab 层面的"先老后新"，与 [Memory Reclaim and Decay](/docs/CS/memory/jemalloc/Decay_and_Purge.md) 的回收意愿对齐。

`bin_lower_slab()` 负责维持"slabcur 不比任何非满 slab 更新"（src/bin.c:211-235）：若新空出来的 slab 更老，就把旧 slabcur 按空满分别塞回堆或链表，再让新 slab 接任；否则新 slab 直接进堆。注释坦白这不是强不变式——"把 `slabcur` 置空、而不是主动让它指向最老的非满 slab 是可以的"（bin.c:215-220），下一次 refill 自然会从堆顶取最老的。

### Auto Arenas Do Not Track Full Slabs

`bin_slabs_full_insert()` 的第一件事是 `if (is_auto) return;`（src/bin.c:168-179），注释写明原因：追踪 extent 是 `arena_reset` 需要的，而 auto arena 不允许 reset，于是干脆跳过这次链表操作，避免碰 edata 的链表指针造成的 cache miss。`bin_slabs_full_remove()` 同样对 auto 早返回（bin.c:181-187）。这条限制在 API 层也成立：`arena.<i>.reset` 的入口明确拒绝 auto arena（`src/ctl.c:2766-2768`）。

结果是：**auto arena 里"满"只体现在 `nfree == 0` 这个数字上，不在任何集合里**。它不影响正确性——释放路径判断空满只看 `nfree`——但意味着靠遍历 `slabs_full` 统计状态的代码（如 [Heap Profiling](/docs/CS/memory/jemalloc/Heap_Profiling.md) 之外的调试/统计路径）在 auto arena 上看不到满 slab。

## The Bitmap Runs Backwards

位图的位语义与它自己的函数名相反，源码在初始化函数里就挑明了：

```c
/*
 * Bits are actually inverted with regard to the external bitmap
 * interface.
 */
```

（`src/bitmap.c:52-55`）

具体表现是一串反着来的约定：

| 操作 | 位怎么变 | 业务含义 |
| :--- | :--- | :--- |
| `bitmap_init(..., fill=false)` | 全置 1（`src/bitmap.c:63-69`） | 全空闲 |
| `bitmap_sfu` | 找第一个 **1** 并把它清 0（`include/jemalloc/internal/bitmap.h:309-338`） | 分配一个 region |
| `bitmap_set` | 清位（bitmap.h:211-244） | 标记已分配 |
| `bitmap_unset` | 置位（bitmap.h:340-377） | 标记空闲 |
| `bitmap_get` | 返回 `!(g & mask)`（bitmap.h:200-209） | **true = 已分配** |
| `bitmap_full` | 树形模式下根组 `== 0`（bitmap.h:181-198） | 没有 1 了 = 满 |

所以 `bitmap_sfu`（"set first unset"）实际做的是"找到并清掉第一个置位的 bit"，`ffs_lu(g)` 找的正是那个 1（`include/jemalloc/internal/bit_util.h:27-30`）；批量路径用的 `cfs_lu()` 也是"找第一个 1 并清掉"（bit_util.h:289-294），两者在同一套倒置语义下才说得通。

树形位图不是无条件启用的：只有当 `LG_BITMAP_MAXBITS - LG_BITMAP_GROUP_NBITS > 3`（即暴力线性搜索要调 `ffs_lu()` 超过 8 次）才建树（bitmap.h:26-33）。建树后每次分配要自根向下走若干级、并在"整组被占满/被放空"时向上传播状态（`bitmap_set` / `bitmap_unset` 里的 propagate 循环）。这解释了为什么 slab 的位图是**分层**结构而不是简单的位数组：`nregs` 可以很大，线性扫太慢。

读这段代码最容易犯的错是凭函数名推断语义。`bitmap_get` 返回 true 的断言出现在释放路径上——"释放一个未分配指针会导致断言失败"（`include/jemalloc/internal/bin_inlines.h:85-86`），初看像是反的，实际正是"该位为 0（已分配）"。

## Allocation: One Region or a Batch

单点分配只有三行有效代码（`src/bin.c:72-86`）：`bitmap_sfu` 拿到 region 号，`addr + reg_size * regind` 算出地址，`nfree` 减一。没有除法（见下节），没有分配，没有统计更新。

批量分配（`bin_slab_reg_alloc_batch`，src/bin.c:88-135）有两条实现，由 `#if (!defined JEMALLOC_INTERNAL_POPCOUNTL) || (defined BITMAP_USE_TREE)` 选择：

- **默认路径**：循环调用 `bitmap_sfu`，每次一个。
- **快速路径**（有 `popcount` 且位图非树形）：先 `popcount_lu` 数出本组还剩几个 1，再以 `cfs_lu` 逐个取，把 `edata_addr_get()` 与 `reg_size` 提到热循环外只读一次（注释："Load from memory locations only once, outside the hot loop below."，bin.c:117-122）。

两条路径最后都只做一次 `edata_nfree_sub(slab, cnt)`（bin.c:134）——这正是批量接口存在的意义：`nfree` 是位域字段，逐个改要反复读改写同一个 64 位字。

谁来调用批量接口？[Tcache](/docs/CS/memory/jemalloc/Tcache.md) 的填充。`arena_ptr_array_fill_small()` 先用 `slabcur` 批量填，一次"把 slabcur 抽干"，除非会超过本次的 `nfill_max` 才退化为只填 `nfill_min`（`src/arena.c:788-807`）。这个"抽干"策略把锁的持有次数压到最低，代价是单次可能多拿走几个对象——tcache 那边注释也承认这是有意为之。

## The Bin Lock Is a Leaf

bin 锁的 witness rank 是 `WITNESS_RANK_BIN = WITNESS_RANK_LEAF = 0x1000`（`include/jemalloc/internal/witness.h:68-69`；锁在 `bin_init()` 里以此 rank 初始化，src/bin.c:43-47）。叶子锁意味着**持有它时不能再获取任何更高 rank 的锁**，于是所有会拿页分配器锁的动作都必须发生在 bin 锁之外。

这条规则在代码里不是靠约定，而是靠断言：`arena_slab_alloc()` 一进门就 `witness_assert_depth_to_rank(..., WITNESS_RANK_CORE, 0)`（src/arena.c:714-719），`pa_alloc()` 同样断言深度为 0（src/pa.c:128-129）。因此"在 bin 锁里顺手分配一块新 slab"在这套代码里会直接触发断言。

三处放锁的方式各不相同：

1. **单对象路径**（`arena_malloc_small`，src/arena.c:875-923）：先在锁内试一次，失败就解锁、分配新 slab、再上锁重试。注释只有一句 "Retry since the lock was dropped."（arena.c:894）——重试是必须的，因为放锁期间别的线程可能已经把空位填上；此时若手里那块新 slab 没用上，就在锁外还回去（arena.c:914-916）。
2. **批量填充路径**（`arena_ptr_array_fill_small`，src/arena.c:744-873）：这是整章最值得读的一段注释。它用 `goto label_refill` 把"上锁—填充—放锁—分配"做成一个循环，注释解释这是为了 **flat combining**，并给出一个明确的三步终止论证：

   > the loop will only terminate early (i.e. stop with filled < nfill) after going through the three steps: a) bin local exhausted, b) unlock and slab_alloc returns null, c) re-lock and bin local fails again.

   （src/arena.c:772-776）

   代码里的 `made_progress` 就是这条论证的载体：初始为 true（第一次允许分配），每次真的填到东西就置 true，分配完新 slab 后置 false（arena.c:777、:804、:858）。于是"分配一次新 slab"的次数被"期间是否有过进展"闸住，防止在内存紧张时无限重试。唯一的 OOM 出口在 `made_progress == false` 之后（arena.c:832-836）。
3. **整 bin 清空**（`arena_bin_reset`，src/arena.c:455-485）：每取出一块 slab 就 `unlock → arena_slab_dalloc → lock`，三个集合各写一遍同样的模式。这是 `arena_reset` 的组成部分，5.4 的 ChangeLog 明确修过这里的"潜在死锁"（`ChangeLog:59`）。

释放方向同理。`bin_dalloc_locked_step()` 的返回值契约是"**若返回 true，调用方必须在锁外对 slab 调 `arena_slab_dalloc()`**"（`include/jemalloc/internal/bin_inlines.h:68-75`），实现里 `bin_dalloc_locked_handle_newly_empty()` 只做解绑与统计，不释放（src/bin.c:247-252）；`arena_dalloc_bin()` 则在 `malloc_mutex_unlock` 之后才判断 `ret`（src/arena.c:951-961）。

## Freeing: Two Transitions and One Deferred Slab

释放一个 region 的有效代码不到十行，但两个分支各自对应一次状态迁移（`include/jemalloc/internal/bin_inlines.h:88-104`）：

```c
bitmap_unset(slab_data->bitmap, &bin_info->bitmap_info, regind);
edata_nfree_inc(slab);
...
unsigned nfree = edata_nfree_get(slab);
if (nfree == bin_info->nregs) {
	bin_dalloc_locked_handle_newly_empty(tsdn, is_auto, slab, bin);
	return true;
} else if (nfree == 1 && slab != bin->slabcur) {
	bin_dalloc_locked_handle_newly_nonempty(tsdn, is_auto, slab, bin);
}
```

**刚变空**（`nfree == nregs`）：解绑（`bin_dissociate_slab`）后返回 true，整块 slab 交给调用方在锁外释放。解绑时若这个 slab 正是 `slabcur`，只把 `slabcur` 置空；否则按 `nregs` 是否等于 1 决定从哪个集合移除（src/bin.c:189-209）。`nregs == 1` 的那个特判有清晰来源：只有一个 region 的 slab 永远进不了非满堆（它一被填满就直接进满链表），所以移除时必须找 `slabs_full`，代码注释也是这么写的（bin.c:198-202）。

**刚变非空**（`nfree == 1 && slab != slabcur`）：说明这块 slab 之前是满的，现在有了第一个空位。于是先按 auto/manual 从满链表摘掉，再交给 `bin_lower_slab()` 决定是否接任 `slabcur`（src/bin.c:254-259、:211-235）。判据里那个 `slab != bin->slabcur` 不能省：若它就是 `slabcur`，释放只是让它多一个空位，不需要任何迁移。

还有一个顺序细节：`bin_dalloc_slab_prepare()` 断言 `slab != bin->slabcur`（src/bin.c:237-245），而它总是紧跟 `bin_dissociate_slab()` 被调用。**解绑必须先把 `slabcur` 置空，这条断言才可能通过**——两行代码的先后顺序是被断言锁死的，不是风格问题。

`bin_dalloc_locked_finish()` 才更新 `ndalloc` / `curregs`，注释说明这是为了"让运行中的计数留在寄存器里"（bin_inlines.h:107-115）；中间批量释放时，`bin_dalloc_locked_info_t` 只带一个 `div_info`、`nregs` 和累加的 `ndalloc`（`include/jemalloc/internal/bin.h:101-106`），`div_info` 在 begin 时一次性拷进去（src/arena.c:50-56）。

## Region Index Without Division

释放时拿到的是一个裸指针，要算出它是这块 slab 的第几个 region：`diff = ptr - slab_addr`，然后 `diff / reg_size`。除数在编译期未知，于是 jemalloc 预先算好一个魔数，用乘法代替除法：

```c
size_t i = ((uint64_t)n * (uint64_t)div_info->magic) >> 32;
```

（`include/jemalloc/internal/div.h:26-33`）

成立条件是 `n < 2^32` 且 `d` 整除 `n`（div.h:9-14）。`div.c` 的注释给出了完整推导：取 `k = 32`、`magic = ceil(2^32 / d)`，则 `floor(magic * n / 2^32) = n / d`，因为余数项 `(r/d) * (n/2^32) < 1`（`src/div.c:7-27`）。`d == 1` 被显式拒绝——那会让 `magic` 恰好等于 `2^32`，装不进 `uint32_t`（div.c:33-38）。debug 构建里 `div_info_t` 会多存一个 `d`，每次计算后断言 `i * d == n`（div.h:20-25、:35-37）。

魔数在 `arena_boot()` 里按 size class 预计算（`src/arena.c:1699-1703`），存在全局数组 `arena_binind_div_info[SC_NBINS]`（arena.c:48）。释放路径再把对应项拷进 `bin_dalloc_locked_info_t`，一次批量释放只算一次。

只有"精确落在 region 边界上"的指针才合法，这一点由三个断言兜住：指针必须在 `[slab_addr, slab_past)` 内、偏移必须是 `reg_size` 的整数倍、结果 `regind < nregs`（`include/jemalloc/internal/bin_inlines.h:44-56`）。最后那条断言同时是魔数算法正确性的现成检查。

## Sharding Multiplies the Bins

多线程抢同一个 bin 的锁仍会打满，jemalloc 的办法是**把同一个 size class 的 bin 复制若干份**：

- 上限 `BIN_SHARDS_MAX = 1 << EDATA_BITS_BINSHARD_WIDTH`，而 `EDATA_BITS_BINSHARD_WIDTH` 硬编码为 6（`include/jemalloc/internal/bin.h:15`；`include/jemalloc/internal/edata.h:211`），所以上限是 64——这个数字不依赖构建期宏，可以直接写。
- 默认 `N_BIN_SHARDS_DEFAULT = 1`（bin.h:16），即默认不分片，一个 size class 一个 bin。
- 运行期配置 `bin_shards`（`src/conf.c:632-653`）的语法由 `multi_setting_parse_next()` 规定：`start-end:nshards`，以 `|` 分隔多段（`src/util.c:8-48`）。`bin_update_shard_size()` 校验 `nshards` 不为 0 且不超过上限，把 `end` 截到 `SC_SMALL_MAXCLASS`，`start` 超过小对象上限就整段忽略，然后按 `sz_size2index_compute()` 把区间内的 size class 逐个赋值（`src/bin.c:10-32`）。注意它用的是 `_compute` 版本，注释说"这可能发生在 size class 初始化之前"（bin.c:24）。

分片落在每个线程身上：线程绑定 arena 时用 `atomic_fetch_add(&arena->binshard_next, 1)` 取一个种子，再对每个 size class 取模得到该线程在各 bin 上的分片号，存进 tsd 的 `binshard[]` 数组（`src/arenas_management.c:176-186`；断言 `0 < n_shards <= BIN_SHARDS_MAX`）。取用时若没有 tsd 或线程还没绑 arena，退化为 0 号分片（`bin_choose()`，`src/bin.c:319-333`）。

分片号也被写进 edata 的 `e_bits`（`edata_nfree_binshard_set()`，`include/jemalloc/internal/edata.h:599-606`），因为 `free()` 只拿到指针，必须能找回**同一个分片**的 bin——`arena_dalloc_bin()` 正是这么做的：`edata_binshard_get(edata) → arena_get_bin(arena, binind, binshard)`（src/arena.c:945-949）。

物理布局上，所有分片被拍平成 arena 尾部的一段连续数组 `all_bins[]`（柔性数组成员，`include/jemalloc/internal/arena.h:159-173`），`arena_bin_offsets[binind]` 给出该 size class 首个分片的字节偏移，`nbins_total` 是所有分片数之和——两者都在 `arena_boot()` 的同一个循环里算好（src/arena.c:1705-1711）。取 bin 就是一次指针加法（`include/jemalloc/internal/arena_inlines.h:394-398`）：

```c
bin_t *shard0 = (bin_t *)((byte_t *)arena + arena_bin_offsets[binind]);
return shard0 + binshard;
```

按 shard 切分而不是按 size class 切分，说明这里要解决的是**同一尺寸类上的锁竞争**，而不是尺寸类之间的隔离；后者由不同 bin 天然提供。

## The Batched Free Partitions Instead of Looking Up

tcache 刷回时，一批指针可能属于不同 arena、不同分片。`arena_ptr_array_flush_impl_small()` 的做法不是建哈希表，而是**原地分区**（src/arena.c:1005-1090）：

1. 取区间首元素确定当前组 `(arena_ind, binshard)`，`flush_start` 前进一格。
2. 扫描剩余元素，凡属于同一组的就与 `flush_start` 位置交换，然后 `flush_start++`。
3. 循环结束时 `[prev_flush_start, flush_start)` 恰好是本组全部元素，注释称之为不变式："all edatas yet to be flushed are contained in the half-open range [flush_start, flush_end)"（arena.c:1022-1027）。
4. 对这一组**只上一次锁**：先合并 tcache 统计（"刷到同 arena 的任一分片即可，统计不按分片暴露"，arena.c:1095-1107），再逐个 `bin_dalloc_locked_step()`。

代价是 O(n × 组数) 的比较，好处是不分配内存、不破坏指针数组的存放位置。debug 构建里分区后会再扫两遍，分别验证"组内全同"与"组外全不同"（arena.c:1073-1090）。

释放整块 slab 也被推迟：`bin_dalloc_locked_step()` 返回 true 时只把 edata 记进 `dalloc_slabs[]`（`VARIABLE_ARRAY`，长度 `nflush + 1`），等所有组都处理完、所有 bin 锁都放掉之后才统一 `arena_slab_dalloc()`（arena.c:1015-1016、:1113-1123、:1133-1137）。这是叶子锁规则在批量路径上的同一个投影：**锁内只记账，锁外才动页分配器**。

若整轮下来没有一组命中线程自己的 arena，统计合并会在收尾时补做一次（arena.c:1139-1151），保证 `nflushes` / `nrequests` 不丢。

## Version and Verification Notes

- 本篇的 5.4 证据来自 `ChangeLog:7-110` 的原文，以及 5.4 树内的存在性核对。与本章直接相关的四条：`arena_reset` 潜在死锁修复（`ChangeLog:59`）、size class 数值溢出检查修复（:47，`reg_size` 表达式所在）、前端模块化把 arena 管理从 `jemalloc.c` 拆出（:64-68）、`arena_s` 改用柔性数组成员 `bin_t all_bins[]`（:94-95，即上节那段偏移算术的由来）。本地是单提交浅历史、只有 `5.4.0` 一个 tag，**没有 5.3 源码可 diff**，因此不写任何"5.3 时期如何"的具体断言。
- **绝对数字只给了两个**：`BIN_SHARDS_MAX == 64`（由硬编码的 `EDATA_BITS_BINSHARD_WIDTH 6` 推得）与 `N_BIN_SHARDS_DEFAULT == 1`（字面量）。`slab_size`、`nregs`、`SC_LG_SLAB_MAXREGS`、`PAGE`、`SC_NBINS` 都来自构建期宏，本机因 `autom4te` 环境问题无法生成 `jemalloc_internal_defs.h`，这些量一律以符号形式出现，不写数值。
- 位图是否为树形（`BITMAP_USE_TREE`）取决于 `LG_BITMAP_MAXBITS - LG_BITMAP_GROUP_NBITS > 3`，而这又取决于 `SC_LG_SLAB_MAXREGS` 与 `SC_NSIZES` 的构建期取值——所以本章对"批量分配走哪条路径"只给条件，不给结论。树形模式下 `BITMAP_MAX_LEVELS` 被硬编码为 5（`include/jemalloc/internal/bitmap.h:105`），注释解释了为何不用按位宽算出的公式。
- `bin_slabs_full_insert` 对 auto arena 早返回，本文的推论（"auto arena 不追踪满 slab"）由该早返回 + `ctl.c:2766` 的 reset 拒绝共同支撑，但没有跑过 auto arena 的实测来验证可观测差异。
- `extent_sn_next` 的"单调递增"是**每个 pac 一个计数器**（`src/extent.c:67-68`），因此跨 pac 的 slab 之间 sn 不可比。同一 arena 的 slab 来自同一 pac，所以非满堆的排序在单个 bin 内是良定义的；本文没有反过来说"全局地址序"。

## Links

- [Tcache](/docs/CS/memory/jemalloc/Tcache.md)
- [Allocation Fast Path](/docs/CS/memory/jemalloc/Fastpath.md)
- [Size Classes](/docs/CS/memory/jemalloc/Size_Classes.md)
- [Memory Reclaim and Decay](/docs/CS/memory/jemalloc/Decay_and_Purge.md)
- [Heap Profiling](/docs/CS/memory/jemalloc/Heap_Profiling.md)
- [jemalloc](/docs/CS/memory/jemalloc/jemalloc.md)

## References

- [jemalloc: concurrent memory allocator](https://jemalloc.net/)
- [jemalloc GitHub 仓库](https://github.com/jemalloc/jemalloc)
