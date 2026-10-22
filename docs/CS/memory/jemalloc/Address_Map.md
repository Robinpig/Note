## Introduction

`free(p)` 只拿到一个指针。尺寸、是不是 slab、归哪个 arena、对应哪段 extent——全都不在指针里，必须从地址反推出来。这条反推链是 jemalloc 里唯一一条**每个分配都要走**的元数据路径，也因此是快慢路径真正的分界线：命中线程内缓存时它是一次比较，未命中时是两三级指针跳转加一把全局初始化锁。

本篇按"反推出来的东西 → 怎么定位 → 谁在什么时候写它 → 凭什么可以无锁读"的顺序讲四层：`edata_t`、`rtree`、`emap`，以及撑住这套读写的 TSD 分层与锁序证明。基线 jemalloc `5.4.0`，`路径:行号` 相对 jemalloc 仓库根。

## edata_t Is the Unit Being Mapped

`edata_t` 不是"元数据"的同义词，它是**一段页的所有者**：小对象的 slab、页分配器里的一段 extent、HPA 的 pageslab、乃至 base 内部自用的内存，都用同一个结构描述。区分它们的是 `e_bits` 里的字段组合，而不是类型标签（include/jemalloc/internal/edata.h:103-120）。这个结构的宽度被钉死在 128 字节，原因写在定义上方：

```c
/*
 * sizeof(edata_t) is 128 bytes on 64-bit architectures.  Ensure the alignment
 * to free up the low bits in the rtree leaf.
 */
#define EDATA_ALIGNMENT 128
```

（edata.h:21-25）。**这行注释是全篇的枢纽**：rtree 的叶元素是"一个指针宽度装下 edata 指针 + 元数据"，而元数据只能占用 edata 指针对不齐的那些低位。128 字节对齐给出 7 个低位，`slab`、`is_head`、`state`（3 位）刚好塞得下。

字段布局里有两处是刻意设计的：

- **`e_size_esn` 与 `e_bsize` 共用一块**（edata.h:233-249）。低 `LG_PAGE` 位不是尺寸的一部分，而是"关联到 edata 结构本身"的序号 `esn`，`EDATA_SIZE_MASK` 把它屏蔽掉。所以走这条路的尺寸必须是页的整数倍；base 内部那种不对齐页的尺寸改用 `e_bsize`。
- **后面两个 union 按生命周期复用**（edata.h:264-294）。active 时用 `ql_link_active`（arena 大对象链表或 `slabs_full`），inactive 时用配对堆/avail 链；第二个 union 更极端：inactive 链表、slab 位图元数据、大对象剖析信息三者共享同一块空间。**"这个 edata 现在是什么身份"决定了哪些字段有意义**，读错字段不会报错，只会读到别的身份留下的值。

`e_bits` 的位宽还有一道编译期保险：`#error "edata_t e_bits overflow"`（edata.h:229-231），字段一旦加多就直接编不过，而不是悄悄截断。

## The Map Is an rtree With a Single Init Lock

`emap_t` 本身没有第二个成员：

```c
struct emap_s {
	rtree_t rtree;
};
```

（include/jemalloc/internal/emap.h:17-20）。所有"地址 → edata"的知识都在这一棵基数树里，没有旁路索引。

树高不写死，而是由**有效虚拟地址位数**推出来（rtree.h:20-35）：`RTREE_NSB = LG_VADDR - LG_PAGE`，按 ≤10 / ≤36 / ≤52 分成 1 / 2 / 3 层。根节点是内嵌的定长数组（rtree.h:102-112），中间节点和叶节点则是**按需挂上去**的：某次写入第一次戳到某棵子树时，才在 `init_lock` 下向 base 申请一个节点（src/rtree.c:30-40、:42-93）。这些节点从不归还——base 的内存天然是 demand-zero（src/base.c:617-627、:644-656），所以多页稀疏结构只在真正被写过的叶子上消耗物理页。

这里有一条容易忽略的可见性约定：节点指针以 `ATOMIC_RELEASE` 发布，但**后来者可能不持锁**，所以非 dependent 的读用 `ACQUIRE`，dependent 的读才允许 `RELAXED`（rtree.c:46-63、:105-119）。另一条是不变式：`init_missing=false` 的读**允许直接返回 NULL**（rtree.c:214-216）——查表不代表树已经存在，调用方必须能处理"这片地址从没被登记过"。

## One Pointer Width per Leaf Element

叶元素是整套设计里最紧的一处。开启 `RTREE_LEAF_COMPACT` 时（门槛是 `RTREE_NHIB >= LG_CEIL(SC_NSIZES)`，rtree.h:36-39），一个 `atomic_p_t` 同时装四样东西（rtree.h:65-81）：

```
00000000 xxxxxxxx eeeeeeee [...] eeeeeeee e00ssshb
```

`szind` 放在**虚拟地址位宽之上**的高位，edata 指针放在低位，低 3 位依次是 `slab`、`is_head`、`state`（`RTREE_LEAF_STATE_SHIFT` 为 2，宽度直接借用 `EDATA_BITS_STATE_WIDTH`，rtree.h:60-63）。编码时用 `assert((edata_bits & metadata_bits) == 0)` 把"字段不重叠"钉住（rtree.h:190-206）；解码时还要处理一个有架构差异的细节——x86-64 要把高位符号扩展回来，aarch64 则是清零（rtree.h:209-241）。**同一份位布局，两边用不同的掩码复原指针**。

反过来，`RTREE_NHIB` 不够大时退回两个原子字段：`le_edata` 与 `le_metadata`，写入顺序是**先元数据、后 edata**，因为"edata 非 NULL"就是元素有效的判据（rtree.h:294-311）。这条顺序在 compact 模式下自然消失——只剩一个字，写就是原子的。

状态迁移不必重写整个元素：`rtree_leaf_elm_state_update` 在 compact 模式下做一次读-改-写，只替换 state 那三位（rtree.h:317-343）。页分配器每次把 extent 从 dirty 改成 merging 走的都是这条路，所以状态变更本身比重新登记便宜得多。

## dependent Is a Memory Model Contract

`dependent` 不是一个性能提示，而是一份**调用方担保**：

> dependent: Reading a value on behalf of a pointer to a valid allocation is guaranteed to be a clean read even without synchronization, because the rtree update became visible in memory before the pointer came into existence.

（rtree.h:171-180）。理由很简洁：如果这个指针是被 malloc 返回的，那么 rtree 的写入必然发生在指针交给用户之前，中间已有足够的同步；此时用 `RELAXED` 读不会读到半成品。反之，**任意地址**（比如 `ivsalloc` 要判断某个野指针是否合法）没有这层保障，必须 `ACQUIRE`。

这条区分直接落在两个函数上：`free` 快路径查缓存用 dependent（emap.h:312-338），"这个地址可能根本不是我们的"用 `rtree_read_independent`（emap.h:290-310）。**担保错了不会崩，只会读到过期的 edata 指针**，所以它只能靠代码审查和 debug assert 守。

## The Two-Level Per-Thread Cache

每个线程带一份 leaf 缓存：16 项直接映射的 L1，加 8 项 LRU 的 L2（include/jemalloc/internal/rtree_tsd.h:23-24、:53-65）。键是 `leafkey`——把地址里"叶内偏移"以下的位全部剥掉，`rtree_cache_direct_map` 再取中间的几位定槽位（rtree.h:141-160）。L1 命中就是一次比较加一次数组寻址（rtree.h:350-370）。

L2 命中时做的是**冒泡而不是删除**：把命中项往上挪一格，原来的槽位空出来（rtree.h:386-424，宏 `RTREE_CACHE_CHECK_L2`）。真未命中（hard lookup）时的替换策略写在 rtree.c 里：整个 L2 右移一格丢掉最末项，把 L1 里发生冲突的那一项下沉到 `l2_cache[0]`，再用新叶填 L1（rtree.c:206-232）。debug 构建里还有一条反向 assert——hard lookup 入口断言这个 `leafkey` 在两级缓存里都不存在（rtree.c:174-182），等于把"hard 只会在真 miss 时到达"写成了可执行的不变式。

这份缓存挂在 `TSD_DATA_SLOW` 层（include/jemalloc/internal/tsd_internals.h:67-90），并且**用静态初始化器预置成无效**，原因是 `free` 快路径可能在 TSD 完整初始化之前就来访问它（rtree_tsd.h:45-52 的注释逐字说明了这一点）。这也解释了 [Fastpath](/docs/CS/memory/jemalloc/Fastpath.md) 里那句"未初始化时把阈值清零"的必要性：反推路径必须能在半初始化的线程上安全空转。

## Boundaries, Interiors and the Ownership Invariant

emap 的登记是分层的，因为**只有 slab 需要页内每个地址都能反查**：

- `emap_register_boundary` 只写首、末两页，写入前断言这两个元素目前是空的（src/emap.c:159-181）。
- `emap_register_interior` 只对 slab 且尺寸大于 2 页时调用，范围严格是 `base+PAGE .. last-PAGE`（emap.c:183-219）。它**不会失败**：边界已经把那两个叶子节点建出来了，内部填充只是往已有节点里写字（emap.h:90-93）。
- 大对象但非 slab 的 extent 只登记首地址，因为查表只会在释放时打到头；`emap_remap` 因此只在 active↔inactive 迁移时改 `szind`/`slab`，末页映射只在 slab 场合顺手改（emap.c:253-287，emap.h:115-119）。

并发这边的关键不是 rtree，而是 **edata 的归属**。ecache 的锁是**按状态分的**，只保护同一状态的 edata，所以想去摸邻居之前必须先确认它当前的状态：

```c
rtree_contents_t neighbor_contents = rtree_leaf_elm_read(
    tsdn, &emap->rtree, elm, /* dependent */ false);
if (!extent_can_acquire_neighbor(edata, neighbor_contents, pai,
        expected_state, forward, expanding)) {
	return NULL;
}
```

（emap.c:80-96）。确认之后把它改成 `merging`，从这一刻起别的线程即使在 rtree 里看得见这个 edata，也不会再去碰它的字段（emap.h:45-59 的注释把这条不变式写全了：**要么持有对应状态锁，要么 edata 处于 acquired 状态**）。

split / merge 被拆成 prepare 与 commit 两半，也是同一条思路的延伸：prepare 只做能在非独占访问下完成的查叶，commit 才在独占访问下改映射；四个函数里只有 `emap_split_prepare` 会失败（emap.h:121-125，emap.c:289-368）。

## Ordering Extents by Serial Number Then Address

页分配器要回答"哪一段最老"和"哪一段地址最低"，但 jemalloc 没有全局时钟。它用**(序列号, 地址)** 的字典序代替：

- `e_sn` 标识那段地址空间，split 之后两个 edata **共享同一个 sn**（edata.h:258-262），所以 sn 不唯一。
- `e_size_esn` 低 `LG_PAGE` 位里的 `esn` 绑定的是 **edata 结构本身**（edata.h:236-249），用来在地址比较也打平时区分被回收复用的结构。
- `edata_cmp_summary_get` 把两者打包成 `{sn, addr}`；有 128 位整数时一次编码比较，否则用"2 倍 sn 差值加 addr 差值"的无分支写法，注释说明这份改写快约 30%（edata.h:777-819）。`edata_esnead_comp` 同理，只是把 sn 换成 esn（edata.h:829-835）。

这套顺序在 [Page_Allocator](/docs/CS/memory/jemalloc/Page_Allocator.md) 里被反复用到：eset 的"最低地址优先"、HPA 的候选排序，都建立在这两个比较函数上。

## TSD Tiers and Lock Ranks

TSD 按"热不热"分三层（tsd_internals.h:28-52）：`FAST` 是每次分配都要碰的，`SLOW` 是半慢路径（tcache 命中但需要尺寸查询之类），`SLOWER` 只在 test/debug 或几乎不用。排布顺序刻意是 SLOW → FAST → SLOWER，让 tcache 数组横跨 FAST 与 SLOWER 的交界，从而让常用的小 bin 和前一层数据落在同一条缓存行附近。**rtree 缓存属于 SLOW 而不是 FAST**，因为只有 `free` 的快路径会查它，`malloc` 快路径不碰。

锁序不是口头约定，而是一个单调的枚举：rank 值越大越晚获取（include/jemalloc/internal/witness.h:12-17）。`WITNESS_RANK_LEAF = 0x1000` 把 bin 锁等"叶子锁"抬到所有结构锁之上（witness.h:68-81），于是 `WITNESS_RANK_CORE` 有了第二个用途：作为 `witness_assert_depth_to_rank()` 的**闭区间下界**，用来断言"除了 rank 低于 CORE 的外围锁，其余一把都没持"（witness.h:38-45、:275-288）。

`emap_update_edata_state` 用的则是它的正向版本：`witness_assert_positive_depth_to_rank(..., WITNESS_RANK_CORE)`（emap.c:18-23），含义是"**至少**持有一把 CORE 或更高 rank 的锁"——SEC 的 shard 锁、ecache 锁、rtree 的 init 锁随便哪一把都算数（witness.h:300-309）。这一条断言就足以挡掉"改状态却什么锁都没拿"这种最难查的竞态。

## Version and Verification Notes

- 所有 `路径:行号` 均按 jemalloc `5.4.0` 本地树核对。本机该树只有单个 graft 提交、且 autoconf 生成物缺失（`jemalloc_internal_defs.h` 不存在），因此 `PAGE`、`LG_VADDR`、`SC_NSIZES`、`RTREE_HEIGHT` 的**实际取值**无法在本机复现，本篇一律用符号关系表述。
- 可写成字面量的只有源码里硬编码的常量：`EDATA_ALIGNMENT == 128`、`ESET_ENUMERATE_MAX_NUM == 32`、`RTREE_CTX_NCACHE == 16`、`RTREE_CTX_NCACHE_L2 == 8`、`RTREE_LEAF_STATE_SHIFT == 2`、`WITNESS_RANK_LEAF == 0x1000`。
- "每片叶子覆盖 1 GiB 虚拟地址"不是推算，而是 rtree.h:493-498 的原文注释（它成立的前提是 48 位有效 VA）；换到其他 VA 位宽需要重算。
- `RTREE_LEAF_COMPACT` 是否生效取决于 `RTREE_NHIB >= LG_CEIL(SC_NSIZES)`，不是"64 位就一定开"。非 compact 分支的写入顺序（元数据先、edata 后）在本机没有对应构建产物可验证，仅按源码阅读记录。
- 本篇未涉及版本间差异：本机没有旧版本树，任何"5.3 时代是……"的说法都属于无法核对的记忆，故不写。

## Links

- [jemalloc](/docs/CS/memory/jemalloc/jemalloc.md)
- [Size Classes](/docs/CS/memory/jemalloc/Size_Classes.md)
- [Fastpath](/docs/CS/memory/jemalloc/Fastpath.md)
- [Tcache](/docs/CS/memory/jemalloc/Tcache.md)
- [Arena Bin and Slab](/docs/CS/memory/jemalloc/Arena_Bin_Slab.md)
- [Page Allocator](/docs/CS/memory/jemalloc/Page_Allocator.md)

## References

- [jemalloc](https://jemalloc.net/)
- [jemalloc source repository](https://github.com/jemalloc/jemalloc)
- [jemalloc 5.4.0 ChangeLog](https://github.com/jemalloc/jemalloc/blob/dev/ChangeLog)
