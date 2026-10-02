## Introduction

[buddy 伙伴系统](pm.md?id=buddy)用 2 的幂次空闲块缓解外部碎片，但它无法**消除**碎片——随着系统长期运行、页不断分配释放，空闲页会逐渐以 order-0 的形式散落各处。于是出现一种尴尬：系统空闲页总量还很多，却凑不出一块物理上连续的高阶内存。

这类需求真实存在：驱动要大的 DMA 缓冲、THP（透明大页）要一个 2MB 的 huge page、内核要分配高阶的连续页表结构。**内存压缩（memory compaction，也译内存规整）** 解决的就是"有内存、但不连续"——它把 zone 一端占用的**可移动页**搬到另一端的空闲页上，搬运完成后空闲页就在 zone 的某一端聚集出连续大块。本篇讲清双扫描器模型、迁移主干、kcompactd 与主动压缩。

> 注意 compaction 与 [Reclaim](Reclaim.md) 的区别：回收是"**减少**占用、把页释放掉"，压缩是"**挪动**占用、页的数据一页不少"。压缩不增加空闲页总量，只改变它们的物理排布。

## 双扫描器模型

compaction 在一个 zone 上启动两个方向相反的扫描器，这是它最核心的设计：

- **迁移扫描器（migrate scanner）**：从 zone 的**低地址**开始向高地址走，找出其中**已占用但可移动**的页，把它们隔离（isolate）到 `cc->migratepages` 链表；
- **空闲扫描器（free scanner）**：从 zone 的**高地址**开始向低地址走，找出其中的**空闲页**，把它们隔离到 `cc->freepages` 链表，作为搬运的目的地。

然后把迁移扫描器找到的页，逐一搬到空闲扫描器提供的目标页上。两个扫描器不断相向推进，**一旦相遇（compact_scanners_met）就说明整个 zone 已规整完毕**，本轮结束：

```c
/* Compaction run completes if the migrate and free scanner meet */
if (compact_scanners_met(cc)) {
    reset_cached_positions(cc->zone);
    if (cc->whole_zone)
        return COMPACT_COMPLETE;
    else
        return COMPACT_PARTIAL_SKIPPED;
}
```

两个扫描器的位置会缓存到 `struct zone` 里（`compact_cached_migrate_pfn[]` / `compact_cached_free_pfn`），下次压缩可以从上次的位置继续，不必每次从头扫。

## 什么样的页能搬：movable 是前提

压缩只能搬**可移动（movable）**的页——移动一个页意味着把数据复制到新物理页、再改所有映射它的页表项。用户态的匿名页、page cache 文件页都可移动；但持有内核内部数据、被 pin 住、或正在写回的页无法安全移动，扫描时直接跳过（异步模式下脏页/写回页也会被跳过）。

这也解释了 buddy 为什么要给空闲块标注 migratetype：可移动页被尽量集中在同一类 pageblock 里，压缩时才能成片地搬；不可移动页造成的"空洞"是压缩也救不回来的根本碎片。

## compact_zone 主干

`compact_zone()` 是规整一个 zone 的主循环（`mm/compaction.c`）。每轮先判断是否结束，再隔离一批源页、迁移到目标页：

```c
while ((ret = compact_finished(cc)) == COMPACT_CONTINUE) {
    ...
    switch (isolate_migratepages(cc)) {
    case ISOLATE_ABORT:
        ret = COMPACT_CONTENDED;
        putback_movable_pages(&cc->migratepages);
        goto out;
    case ISOLATE_NONE:
        goto check_drain;
    case ISOLATE_SUCCESS:
        ...
    }

    err = migrate_pages(&cc->migratepages, compaction_alloc,
            compaction_free, (unsigned long)cc, cc->mode,
            MR_COMPACTION, &nr_succeeded);
    ...
}
```

关键在 `migrate_pages()` 的两个回调：`compaction_alloc` 每搬一个源页，就从空闲扫描器已隔离的 `cc->freepages` 里取一个目标页；没有现成目标页时，它会推动空闲扫描器再向前隔离一批。迁移失败、没搬成的页由 `putback_movable_pages()` 放回，不丢数据。

## 压缩力度：compact_priority

压缩能"多坚持地搬"由 `enum compact_priority` 决定，值越小力度越大（与回收 priority 类似）：

```c
enum compact_priority {
    COMPACT_PRIO_SYNC_FULL,                    /* 最彻底，可等待/写回 */
    MIN_COMPACT_PRIORITY = COMPACT_PRIO_SYNC_FULL,
    COMPACT_PRIO_SYNC_LIGHT,                   /* 同步但跳过部分难搬页 */
    MIN_COMPACT_COSTLY_PRIORITY = COMPACT_PRIO_SYNC_LIGHT,
    DEF_COMPACT_PRIORITY = COMPACT_PRIO_SYNC_LIGHT,
    COMPACT_PRIO_ASYNC,                        /* 异步，不阻塞、遇阻即走 */
    INIT_COMPACT_PRIORITY = COMPACT_PRIO_ASYNC
};
```

异步（ASYNC）用于后台守护、不能阻塞，遇到锁争抢或脏页就跳过；直接压缩默认 SYNC_LIGHT；只有极难满足的分配才升级到 SYNC_FULL。

## 结果与门槛：compact_result / compaction_suitable

`compact_zone()` / `try_to_compact_pages()` 返回 `enum compact_result`，区分这次规整的结局：

| 结果 | 含义 |
| --- | --- |
| `COMPACT_SKIPPED` | 未启动——不可能成功，或直接回收更合适 |
| `COMPACT_DEFERRED` | 因过去失败而被推迟 |
| `COMPACT_CONTINUE` | 内部状态：应继续扫下一个 pageblock |
| `COMPACT_COMPLETE` | 整个 zone 扫完但没能规整出目标页 |
| `COMPACT_PARTIAL_SKIPPED` | 只扫了部分 zone |
| `COMPACT_CONTENDED` | 因锁争抢提前终止 |
| `COMPACT_SUCCESS` | 判定目标分配现在应当能成功 |

是否值得启动压缩，先由 `compaction_suitable()` 按**水位线**把关：空闲页若低于一定余量，压缩缺少"搬运落脚"的目标页、纯属白费，此时 `COMPACT_SKIPPED`，转而走回收。这正对应慢路径里"先回收一点、再压缩"的常见组合。

## kcompactd：后台规整

和回收有 kswapd 一样，每个 node 有一个 **kcompactd** 守护线程（线程句柄与参数挂在 `pg_data_t` 上：`kcompactd` / `kcompactd_max_order` / `kcompactd_highest_zoneidx` / `kcompactd_wait`）。压缩由此分两种触发方式：

- **异步**：分配慢路径发现"碎片导致高阶紧张"时，通过 `wakeup_kcompactd()` 唤醒后台规整，不阻塞当前进程；
- **同步直接压缩**：慢路径里直接调 `__alloc_pages_direct_compact` → `try_to_compact_pages()`，由申请进程自己搬，搬完立即重试分配。

为避免"明知会失败还反复压缩"，zone 维护了一套**推迟（defer）**计数——`compact_considered` / `compact_defer_shift` / `compact_order_failed`，一次失败后会跳过随后若干次压缩请求，直到间隔足够或条件改变。

## 主动压缩：proactive compaction

除了被动等分配失败，内核还能在系统空闲时**提前**规整碎片，即主动压缩（5.14+），由 `/proc/sys/vm/compaction_proactiveness` 控制（范围 0–100，0 关闭，值越高越积极）。它周期性地给每个 zone 计算一个 **fragmentation score（碎片指数）**，分数高于阈值才唤醒 kcompactd：

```c
if (cc->proactive_compaction) {
    ...
    if (kswapd_is_running(pgdat))
        return COMPACT_PARTIAL_SKIPPED;
    score = fragmentation_score_zone(cc->zone);
    wmark_low = fragmentation_score_wmark(true);
    if (score > wmark_low)
        ret = COMPACT_CONTINUE;
    else
        ret = COMPACT_SUCCESS;
}
```

主动压缩刻意"点到为止"：kswapd 在跑就让路、碎片分数降到水位以下即收，避免在没人需要高阶页时白耗 CPU。主动压缩以 `order = -1` 调用，表示不是为某个具体阶服务、而是整体改善布局。

## 压缩与回收、OOM 的协作

compaction 处在 [alloc_pages_slowpath](pm.md?id=alloc_pages_slowpath) 链的中段，与前后环节咬合：

- 压缩**需要空闲页作落脚点**，所以水位不足时慢路径会先做一轮 direct reclaim 再压缩；回收还会把 pageblock 标记为 `PG_migrate_skip`，压缩据此跳过不值得搬的块（`compact_blockskip_flush` 控制何时清这些标记）。
- 压缩**成功**则高阶分配重试通过；压缩与回收都救不回来、连 min 水位都满足不了，才走到 [OOM killer](oom.md)。

## 调优与观察

| 接口 / 指标 | 用途 |
| --- | --- |
| `/proc/sys/vm/compaction_proactiveness` | 主动压缩积极度（0 关闭） |
| `/proc/sys/vm/extfrag_threshold` | 判断碎片是否"可压缩"的阈值 |
| `/proc/pagetypeinfo` | 各 migratetype / order 的空闲块分布 |
| `vmstat` 的 `compact_*` | 各模式成功/失败/推迟计数 |
| `/sys/kernel/debug/extfrag/extfrag_index` | 各 order 的碎片指数 |

排障口径：高阶分配频繁失败但 `compact_stall` 不高、`compact_fail` 高，往往是不可移动页太多、压缩无能为力；`compact_pagemigrate_failed` 高则说明源页难以搬离（脏页/锁/pin）。需要时也可手动 `echo 1 > /proc/sys/vm/compact_memory` 强制对所有 node 规整一次。

## Links

- [内存管理知识地图](/docs/CS/OS/Linux/mm/README.md)
- [Swap 交换](/docs/CS/OS/Linux/Swap.md)

## References

1. [Memory compaction — kernel.org documentation](https://www.kernel.org/doc/html/latest/mm/compaction.html)
2. [Proactive compaction — lwn.net](https://lwn.net/Articles/817994/)
3. [Linux Memory Management — kernel.org](https://www.kernel.org/doc/html/latest/mm/index.html)
