## Introduction

内存回收（reclaim）回答的问题是：**当空闲内存不够时，哪些页可以拿回来、按什么顺序拿、拿的时候怎么保证不丢数据**。它是分配器慢路径的必经环节——空闲页降到 low 水位就唤醒后台 kswapd，掉到 min 水位则分配者自己同步回收（direct reclaim），两条路都走不通才轮到 [OOM killer](/docs/CS/OS/Linux/mm/oom.md)。

需要回收的根本原因是页分两类：

- **可回收页**（reclaimable）：数据在别处有副本（文件页、page cache），或者能换出到磁盘（匿名页）。前者直接丢弃，后者先换出（见 [Swap](/docs/CS/OS/Linux/Swap.md)）。
- **不可回收页**（unreclaimable）：内核数据结构、DMA 缓冲等，被钉住（pinned），只能由使用者主动释放。少数例外是文件系统元数据缓存（dcache/icache），可从存储重新读回，所以也能回收。

回收的顺序由 **LRU 链表**表达，回收的动作由 **vmscan**（`mm/vmscan.c`）执行。本篇覆盖：水位线与 kswapd 唤醒 → LRU 老化 → `scan_control` 与回收入口 → 扫描主干 → 逐页决策（`shrink_folio_list`）→ shrinker（slab 回收）→ memcg 回收 → 调优。

## Watermarks and kswapd

每个 zone 维护三条水位线，全部以 **页**为单位，定义在 `struct zone` 的 `_watermark[NR_WMARK]` 里（[struct zone](/docs/CS/OS/Linux/mm/pm.md?id=zone)）：

```c
/* mm/page_alloc.c：水位线取用宏 */
#define min_wmark_pages(z) (z->_watermark[WMARK_MIN] + z->watermark_boost)
#define low_wmark_pages(z) (z->_watermark[WMARK_LOW] + z->watermark_boost)
#define high_wmark_pages(z) (z->_watermark[WMARK_HIGH] + z->watermark_boost)
```

- **WMARK_MIN**：分配路径的硬底线。空闲页低于它，分配就得自己动手回收（direct reclaim），不能再等 kswapd；
- **WMARK_LOW**：唤醒 kswapd 的门槛。空闲页跌到 low，说明压力在积累，叫醒后台线程回收；
- **WMARK_HIGH**：kswapd 的收工线。回收到 high 水位，kswapd 回去睡觉。

三条线不是随便定的：`WMARK_MIN` 由 `vm.min_free_kbytes` 折算，内核在启动时按物理内存比例自动推算（`__setup_per_zone_wmarks`），low/high 则在 min 之上各留一段余量——余量取 `min/4` 与 `watermark_scale_factor`（默认 10，即 zone 容量的 0.1%）折算值中的较大者，high 的余量再加倍。所以调 `watermark_scale_factor` 等价于调大 low/high 与 min 的间距，让 kswapd 更早、更从容地工作。

分配路径上的检查就落在这三条线上：快速路径 `zone_watermark_fast()` 只看常见情形，慢路径用 `zone_watermark_ok()` 逐条比对。**空闲页 ≥ low** 直接分配；**落在 low 与 min 之间**时分配仍成功，但慢路径开头的 `wake_all_kswapds()` 会经由 `wakeup_kswapd()` 叫醒后台线程去补。

`wakeup_kswapd()` 每个 NUMA node 唤醒一个 kswapd 线程——线程句柄与等待队列就挂在 `pg_data_t` 上（`kswapd` / `kswapd_wait`，见 [node](/docs/CS/OS/Linux/mm/pm.md?id=node)），由 `kswapd_init()` 在启动时为每个 node 拉起。kswapd 一醒就进入 `balance_pgdat()`，按 `DEF_PRIORITY`（12）往下逐级扫描，直到 zone 回到 high 水位或实在回收不出东西（`kswapd_failures` 计数，用于后续要不要进入更激进模式）。

> `watermark_boost` 是给"需要大块连续内存"的场景预留的（比如 THP、大 order 分配）：临时抬高水位线，逼 kswapd 多回收一些，避免大页分配反复失败。

## LRU List and Page Aging

回收要知道"先拿谁"。内核把可回收页挂在 **LRU 链表**上，按 **两个维度**切分：

```c
/* include/linux/mmzone.h */
enum lru_list {
	LRU_INACTIVE_ANON = LRU_BASE,      /* 不活跃匿名页：换出的首选 */
	LRU_ACTIVE_ANON = LRU_BASE + LRU_ACTIVE,
	LRU_INACTIVE_FILE = LRU_BASE + LRU_FILE,  /* 不活跃文件页：直接丢弃 */
	LRU_ACTIVE_FILE = LRU_BASE + LRU_FILE + LRU_ACTIVE,
	LRU_UNEVICTABLE,                   /* mlock 等被钉住的页，不参与回收 */
	NR_LRU_LISTS
};
```

- **anon vs file**：两类页"归还"的代价不同——文件页有磁盘副本，干净的直接丢；匿名页必须先写 swap（或 zswap/zram 压缩）才能丢。代价不同，扫描时的比例就得动态平衡；
- **active vs inactive**：粗略的"热度"两档。新页先进 inactive 尾部（`folio_add_lru`），被访问过就带上 `PG_referenced`，扫描时凭它与 `PG_active` 决定升级到 active 还是留在原地等待淘汰。这就是 **二次机会（second chance）**——不给新页立刻判死刑。

active 链表不是只进不出：当 inactive 太少（`inactive_is_low`），会调用 `shrink_active_list()` 把 active 尾部批量降级回 inactive，补充"待淘汰"的池子。`shrink_lruvec()` 末尾那段逻辑就是在干这件事。

还有一个反抖动的机制叫 **refault**：文件页被回收后，内核在页缓存里留一条 shadow entry 记录它。如果这页很快又被访问、从磁盘重新读回，内核判定发生了一次 refault——说明刚才是"误杀"，于是把它直接放进 active 链表、计入 workingset，避免"回收—重读—再回收"的往复。`folio_check_refault()` 就是这条判定的落点，也是 page cache 抖动（thrashing）分析的核心指标（`/proc/vmstat` 的 `workingset_refault`）。

在多 memcg 场景下，每条 LRU 不是全局一条，而是 per-node、per-memcg 一个 `lruvec`——回收才可能做到"只动某个 cgroup 的页"（见下文 [memcg 回收](?id=memcg-reclaim)）。

## Reclaim Entry: scan_control and try_to_free_pages

一次回收要回答三个问题：**扫哪些 node、过程中允许做哪些动作、什么时候退出**。这三个问题由 `scan_control` 结构体描述，由入口函数 `try_to_free_pages()` 赋值——direct reclaim 走的就是它；kswapd 则在 `balance_pgdat()` 里构造自己的 `scan_control`，主干一致、取向不同（kswapd 可以更从容地回写与扫描）。

### try_to_free_pages

```c
unsigned long try_to_free_pages(struct zonelist *zonelist, int order,
                                gfp_t gfp_mask, nodemask_t *nodemask)
{
    unsigned long nr_reclaimed;
    struct scan_control sc = {
        .nr_to_reclaim = SWAP_CLUSTER_MAX,
        .gfp_mask = current_gfp_context(gfp_mask),
        .reclaim_idx = gfp_zone(gfp_mask),
        .order = order,
        .nodemask = nodemask,
        .priority = DEF_PRIORITY,
        .may_writepage = !laptop_mode,
        .may_unmap = 1,
        .may_swap = 1,
    };

    /*
	 * scan_control uses s8 fields for order, priority, and reclaim_idx.
	 * Confirm they are large enough for max values.
	 */
    BUILD_BUG_ON(MAX_PAGE_ORDER >= S8_MAX);
    BUILD_BUG_ON(DEF_PRIORITY > S8_MAX);
    BUILD_BUG_ON(MAX_NR_ZONES > S8_MAX);

    /*
	 * Do not enter reclaim if fatal signal was delivered while throttled.
	 * 1 is returned so that the page allocator does not OOM kill at this
	 * point.
	 */
    if (throttle_direct_reclaim(sc.gfp_mask, zonelist, nodemask))
        return 1;

    set_task_reclaim_state(current, &sc.reclaim_state);
    trace_mm_vmscan_direct_reclaim_begin(order, sc.gfp_mask);

    nr_reclaimed = do_try_to_free_pages(zonelist, &sc);

    trace_mm_vmscan_direct_reclaim_end(nr_reclaimed);
    set_task_reclaim_state(current, NULL);

    return nr_reclaimed;
}
```


### scan_control

`scan_control` 的字段可以分三类：**目标量**（`nr_to_reclaim`——本次要回收多少页）、**能力开关**（`may_writepage` / `may_unmap` / `may_swap` / `may_deactivate`，决定这次允许做哪些动作；例如 `laptop_mode` 下就不允许直接回写）、**进度与统计**（`priority` 控制扫描力度，`nr_scanned` / `nr_reclaimed` 与内嵌 `nr` 结构里的脏页、回写、拥塞计数）。

它还通过 `set_task_reclaim_state(current, &sc.reclaim_state)` 挂进当前任务——所以回收过程中任何一层都能知道"此刻是否在回收、力度多大"，分配器据此决定"继续等回收"还是"进入下一步"。

```c
struct scan_control {
    /* How many pages shrink_list() should reclaim */
    unsigned long nr_to_reclaim;

    /*
	 * Nodemask of nodes allowed by the caller. If NULL, all nodes
	 * are scanned.
	 */
    nodemask_t	*nodemask;

    /*
	 * The memory cgroup that hit its limit and as a result is the
	 * primary target of this reclaim invocation.
	 */
    struct mem_cgroup *target_mem_cgroup;

    /*
	 * Scan pressure balancing between anon and file LRUs
	 */
    unsigned long	anon_cost;
    unsigned long	file_cost;

    /* Can active folios be deactivated as part of reclaim? */
    #define DEACTIVATE_ANON 1
    #define DEACTIVATE_FILE 2
    unsigned int may_deactivate:2;
    unsigned int force_deactivate:1;
    unsigned int skipped_deactivate:1;

    /* Writepage batching in laptop mode; RECLAIM_WRITE */
    unsigned int may_writepage:1;

    /* Can mapped folios be reclaimed? */
    unsigned int may_unmap:1;

    /* Can folios be swapped as part of reclaim? */
    unsigned int may_swap:1;

    /* Not allow cache_trim_mode to be turned on as part of reclaim? */
    unsigned int no_cache_trim_mode:1;

    /* Has cache_trim_mode failed at least once? */
    unsigned int cache_trim_mode_failed:1;

    /* Proactive reclaim invoked by userspace through memory.reclaim */
    unsigned int proactive:1;

    /*
	 * Cgroup memory below memory.low is protected as long as we
	 * don't threaten to OOM. If any cgroup is reclaimed at
	 * reduced force or passed over entirely due to its memory.low
	 * setting (memcg_low_skipped), and nothing is reclaimed as a
	 * result, then go back for one more cycle that reclaims the protected
	 * memory (memcg_low_reclaim) to avert OOM.
	 */
    unsigned int memcg_low_reclaim:1;
    unsigned int memcg_low_skipped:1;

    unsigned int hibernation_mode:1;

    /* One of the zones is ready for compaction */
    unsigned int compaction_ready:1;

    /* There is easily reclaimable cold cache in the current node */
    unsigned int cache_trim_mode:1;

    /* The file folios on the current node are dangerously low */
    unsigned int file_is_tiny:1;

    /* Always discard instead of demoting to lower tier memory */
    unsigned int no_demotion:1;

    /* Allocation order */
    s8 order;

    /* Scan (total_size >> priority) pages at once */
    s8 priority;

    /* The highest zone to isolate folios for reclaim from */
    s8 reclaim_idx;

    /* This context's GFP mask */
    gfp_t gfp_mask;

    /* Incremented by the number of inactive pages that were scanned */
    unsigned long nr_scanned;

    /* Number of pages freed so far during a call to shrink_zones() */
    unsigned long nr_reclaimed;

    struct {
        unsigned int dirty;
        unsigned int unqueued_dirty;
        unsigned int congested;
        unsigned int writeback;
        unsigned int immediate;
        unsigned int file_taken;
        unsigned int taken;
    } nr;

    /* for recording the reclaimed slab by now */
    struct reclaim_state reclaim_state;
};
```


## Scan Backbone: shrink_zones -> shrink_node -> shrink_node_memcgs

一次回收的目标是"扫哪几个 node、能动哪些页、什么时候停"，这完全由 `scan_control` 描述（见下一节）。主干是：

```
do_try_to_free_pages(zonelist, sc)
  → shrink_zones(zonelist, sc)      ← 遍历 allowed zonelist 里的 zone
    → shrink_node(pgdat, sc)        ← 按 node 回收
      → prepare_scan_count()        ← 统计各类页、算 anon/file 扫描配比
      → shrink_node_memcgs()        ← 逐 memcg（含根）回收各自的 lruvec
        → shrink_lruvec()           ← 真正扫 LRU
        → shrink_slab()             ← 顺带回收 slab 缓存
```

`priority` 是这条链的"力度旋钮"：从 `DEF_PRIORITY`（12）开始，每轮回扫不出目标量就把 priority 减 1，即扫描量按 `total_size >> priority` 指数级放大——priority 越小越激进，减到 0 还没有回收出足够内存，就只能靠更上层（compaction / OOM）收场。kswapd 与 direct reclaim 走的是同一套主干，差别只在 `scan_control` 的取值与谁在等待。

## shrink_lruvec and shrink_list

### shrink_lruvec
```c
static void shrink_lruvec(struct lruvec *lruvec, struct scan_control *sc)
{
	unsigned long nr[NR_LRU_LISTS];
	unsigned long targets[NR_LRU_LISTS];
	unsigned long nr_to_scan;
	enum lru_list lru;
	unsigned long nr_reclaimed = 0;
	unsigned long nr_to_reclaim = sc->nr_to_reclaim;
	bool proportional_reclaim;
	struct blk_plug plug;

	get_scan_count(lruvec, sc, nr);
	memcpy(targets, nr, sizeof(nr));

	proportional_reclaim = (!cgroup_reclaim(sc) && !current_is_kswapd() &&
				sc->priority == DEF_PRIORITY);

	blk_start_plug(&plug);
	while (nr[LRU_INACTIVE_ANON] || nr[LRU_ACTIVE_FILE] ||
					nr[LRU_INACTIVE_FILE]) {
		unsigned long nr_anon, nr_file, percentage;
		unsigned long nr_scanned;

		for_each_evictable_lru(lru) {
			if (nr[lru]) {
				nr_to_scan = min(nr[lru], SWAP_CLUSTER_MAX);
				nr[lru] -= nr_to_scan;

				nr_reclaimed += shrink_list(lru, nr_to_scan,
							    lruvec, sc);
			}
		}

		cond_resched();

		if (nr_reclaimed < nr_to_reclaim || proportional_reclaim)
			continue;

		nr_file = nr[LRU_INACTIVE_FILE] + nr[LRU_ACTIVE_FILE];
		nr_anon = nr[LRU_INACTIVE_ANON] + nr[LRU_ACTIVE_ANON];

		if (!nr_file || !nr_anon)
			break;

		if (nr_file > nr_anon) {
			unsigned long scan_target = targets[LRU_INACTIVE_ANON] +
						targets[LRU_ACTIVE_ANON] + 1;
			lru = LRU_BASE;
			percentage = nr_anon * 100 / scan_target;
		} else {
			unsigned long scan_target = targets[LRU_INACTIVE_FILE] +
						targets[LRU_ACTIVE_FILE] + 1;
			lru = LRU_FILE;
			percentage = nr_file * 100 / scan_target;
		}

		/* Stop scanning the smaller of the LRU */
		nr[lru] = 0;
		nr[lru + LRU_ACTIVE] = 0;


		lru = (lru == LRU_FILE) ? LRU_BASE : LRU_FILE;
		nr_scanned = targets[lru] - nr[lru];
		nr[lru] = targets[lru] * (100 - percentage) / 100;
		nr[lru] -= min(nr[lru], nr_scanned);

		lru += LRU_ACTIVE;
		nr_scanned = targets[lru] - nr[lru];
		nr[lru] = targets[lru] * (100 - percentage) / 100;
		nr[lru] -= min(nr[lru], nr_scanned);
	}
	blk_finish_plug(&plug);
	sc->nr_reclaimed += nr_reclaimed;

	if (can_age_anon_pages(lruvec_pgdat(lruvec), sc) &&
	    inactive_is_low(lruvec, LRU_INACTIVE_ANON))
		shrink_active_list(SWAP_CLUSTER_MAX, lruvec,
				   sc, LRU_ACTIVE_ANON);
}
```

### shrink_list

```c
static unsigned long shrink_list(enum lru_list lru, unsigned long nr_to_scan,
				 struct lruvec *lruvec, struct scan_control *sc)
{
	if (is_active_lru(lru)) {
		if (sc->may_deactivate & (1 << is_file_lru(lru)))
			shrink_active_list(nr_to_scan, lruvec, sc, lru);
		else
			sc->skipped_deactivate = 1;
		return 0;
	}

	return shrink_inactive_list(nr_to_scan, lruvec, sc, lru);
}
```

### shrink_inactive_list
```c
static unsigned long shrink_inactive_list(unsigned long nr_to_scan,
		struct lruvec *lruvec, struct scan_control *sc,
		enum lru_list lru)
{
	LIST_HEAD(folio_list);
	unsigned long nr_scanned;
	unsigned int nr_reclaimed = 0;
	unsigned long nr_taken;
	struct reclaim_stat stat;
	bool file = is_file_lru(lru);
	enum vm_event_item item;
	struct pglist_data *pgdat = lruvec_pgdat(lruvec);
	bool stalled = false;

	while (unlikely(too_many_isolated(pgdat, file, sc))) {
		if (stalled)
			return 0;

		/* wait a bit for the reclaimer. */
		stalled = true;
		reclaim_throttle(pgdat, VMSCAN_THROTTLE_ISOLATED);

		/* We are about to die and free our memory. Return now. */
		if (fatal_signal_pending(current))
			return SWAP_CLUSTER_MAX;
	}

	lru_add_drain();

	spin_lock_irq(&lruvec->lru_lock);

	nr_taken = isolate_lru_folios(nr_to_scan, lruvec, &folio_list,
				     &nr_scanned, sc, lru);

	__mod_node_page_state(pgdat, NR_ISOLATED_ANON + file, nr_taken);
	item = PGSCAN_KSWAPD + reclaimer_offset();
	if (!cgroup_reclaim(sc))
		__count_vm_events(item, nr_scanned);
	__count_memcg_events(lruvec_memcg(lruvec), item, nr_scanned);
	__count_vm_events(PGSCAN_ANON + file, nr_scanned);

	spin_unlock_irq(&lruvec->lru_lock);

	if (nr_taken == 0)
		return 0;

	nr_reclaimed = shrink_folio_list(&folio_list, pgdat, sc, &stat, false);

	spin_lock_irq(&lruvec->lru_lock);
	move_folios_to_lru(lruvec, &folio_list);

	__mod_lruvec_state(lruvec, PGDEMOTE_KSWAPD + reclaimer_offset(),
					stat.nr_demoted);
	__mod_node_page_state(pgdat, NR_ISOLATED_ANON + file, -nr_taken);
	item = PGSTEAL_KSWAPD + reclaimer_offset();
	if (!cgroup_reclaim(sc))
		__count_vm_events(item, nr_reclaimed);
	__count_memcg_events(lruvec_memcg(lruvec), item, nr_reclaimed);
	__count_vm_events(PGSTEAL_ANON + file, nr_reclaimed);
	spin_unlock_irq(&lruvec->lru_lock);

	lru_note_cost(lruvec, file, stat.nr_pageout, nr_scanned - nr_reclaimed);

	/*
	 * If dirty folios are scanned that are not queued for IO, it
	 * implies that flushers are not doing their job. This can
	 * happen when memory pressure pushes dirty folios to the end of
	 * the LRU before the dirty limits are breached and the dirty
	 * data has expired. It can also happen when the proportion of
	 * dirty folios grows not through writes but through memory
	 * pressure reclaiming all the clean cache. And in some cases,
	 * the flushers simply cannot keep up with the allocation
	 * rate. Nudge the flusher threads in case they are asleep.
	 */
	if (stat.nr_unqueued_dirty == nr_taken) {
		wakeup_flusher_threads(WB_REASON_VMSCAN);
		/*
		 * For cgroupv1 dirty throttling is achieved by waking up
		 * the kernel flusher here and later waiting on folios
		 * which are in writeback to finish (see shrink_folio_list()).
		 *
		 * Flusher may not be able to issue writeback quickly
		 * enough for cgroupv1 writeback throttling to work
		 * on a large system.
		 */
		if (!writeback_throttling_sane(sc))
			reclaim_throttle(pgdat, VMSCAN_THROTTLE_WRITEBACK);
	}

	sc->nr.dirty += stat.nr_dirty;
	sc->nr.congested += stat.nr_congested;
	sc->nr.unqueued_dirty += stat.nr_unqueued_dirty;
	sc->nr.writeback += stat.nr_writeback;
	sc->nr.immediate += stat.nr_immediate;
	sc->nr.taken += nr_taken;
	if (file)
		sc->nr.file_taken += nr_taken;

	trace_mm_vmscan_lru_shrink_inactive(pgdat->node_id,
			nr_scanned, nr_reclaimed, &stat, sc->priority, file);
	return nr_reclaimed;
}
```


## shrink_folio_list: Decision Tree for Keeping or Evicting a Single Page

`shrink_inactive_list()` 把一批页从 LRU 摘下来（`isolate_lru_folios`）后，交给 `shrink_folio_list()` 逐页做去留判断。判断的依据依次是**引用计数、页表映射、脏不脏、能不能换出**：

1. **还有人用吗**：`folio_check_references()` 看页是否近期被访问（rmap 反查）。近期访问过的新页放回 active，给一次机会；没有引用且没有映射的页才是候选。
2. **映射着吗**（`mapcount`）：有页表映射就要先 `try_to_unmap()` 断开——这一步依赖反向映射（rmap）找到所有引用它的进程页表。
3. **匿名的先换出**：`add_to_swap()` 把匿名页写进 swap（或 zswap 压缩池），成功后才能释放原页；没有 swap 可用就只能保留（这也是"没 swap 的机器更早 OOM"的原因）。
4. **文件脏的先回写**：脏文件页走 `pageout()` → `writepage`；若页正在回写中（`PG_writeback`），不阻塞等待，先放回 LRU 等下次；回写压力过大触发节流（`reclaim_throttle(..., VMSCAN_THROTTLE_WRITEBACK)`）。
5. **钉住的跳过**：`mlock`、`PG_unevictable`、被驱动 pin 住的页（`GUP` 长期持有）不动，归入 `LRU_UNEVICTABLE`。

判断通过、确实能释放的页，最后经 `free_unref_page_list()` 归还伙伴系统（[free](/docs/CS/OS/Linux/mm/pm.md?id=free)）；没能释放的经 `move_folios_to_lru()` 放回相应 LRU，等下轮 priority 更激进时再扫。

## shrink_slab and shrinker

内存里不只有 page 和 page cache，还有大量 **slab 缓存**——dentry（dcache）、inode（icache）、各种子系统自己的对象池。它们同样占着物理页，同样能被回收，但"怎么回收"只有各自的子系统知道。内核因此提供 **shrinker** 回调机制：

```c
/* include/linux/shrinker.h（骨架） */
struct shrinker {
	unsigned long (*count_objects)(struct shrinker *shrinker,
				       struct shrink_control *sc);
	unsigned long (*scan_objects)(struct shrinker *shrinker,
				      struct shrink_control *sc);
	long batch;	/* 每批扫描对象数 */
	int seeks;	/* 寻找被回收对象的难度 */
	...
};
```

子系统通过 `shrinker_register()` 注册自己的回收器（`count_objects` 报"有多少可回收"，`scan_objects` 执行回收），`shrink_slab()` 在每次 node 回收时按 reclaim 的压力调用它们。最典型的是文件系统注册的 `super_cache_scan`——它回收 dentry 与 inode 缓存，扫描力度由 `vm.vfs_cache_pressure` 调节（默认 100，调大则更积极回收元数据缓存、更少回收 page cache）。这解释了为什么"内存压力下 `slab` 里的 `dentry` 会掉"：那是 shrinker 在工作。

## memcg Reclaim

cgroup v2 的 `memory.max` 超限时走的是**局部回收**：`scan_control` 带上 `target_mem_cgroup`，`shrink_node_memcgs()` 只遍历这个 memcg 及其子 cgroup 的 lruvec，不去动别的组的页——这是容器内存隔离的基础（memcg 侧的结构与限额见 [cgroup 内存控制（memcg）](/docs/CS/OS/Linux/mm/memcg.md)）。

三个配套机制：

- **`memory.high` 节流**：越过高边界的 charge 会让本组进程被**节流**并被置于重度回收压力下，但**绝不因此被杀**——它把"超了"这件事从"杀进程"降级成"变慢 + 挨回收"，给外部监控留出反应时间（`memory.events` 的 `high` 计数即由此产生）；
- **`memory.low` 保护**：低优先级回收会跳过受保护的 memcg（`memcg_low_skipped`）；只有当所有组都受保护、一点内存都收不回来时，才回头回收受保护内存（`memcg_low_reclaim`），目的是"宁可动保护内存，也别 OOM"；
- **主动回收**：用户态可以写 `memory.reclaim`（`scan_control.proactive`）主动触发一次回收，不必等到真的紧张——k8s 的内存驱逐、容器运行时的"提前瘦身"靠的就是它。

## Comparison between Background Reclaim and Direct Reclaim

| 维度 | kswapd（后台） | direct reclaim（直接） |
|---|---|---|
| 触发 | 空闲页跌破 low，被分配路径唤醒 | 空闲页跌破 min，或 `GFP_NO_KSWAPD` 类分配 |
| 执行者 | 每 node 一个内核线程 | 正在分配内存的进程自己 |
| 上下文 | 可睡眠、可回写、从容扫描 | 分配者原地阻塞，延迟直接叠加到业务 |
| 收工条件 | 回到 high 水位 / 回收无进展 | 回收够本次请求的量（`nr_to_reclaim`） |
| 主要危害 | CPU 与 I/O 争抢 | **延迟毛刺**——业务抖动最常见的内核原因 |

`throttle_direct_reclaim()` 负责给直接回收"限流"：多个进程同时撞上 min 水位时排队进入，避免一群进程一起扫 LRU 把系统拖垮（`reclaim_throttle` / `VMSCAN_THROTTLE_*`）。

## Tuning

`/proc/sys/vm` 下与回收直接相关的几个旋钮：

| 参数 | 作用 | 调大/调小的效果 |
|---|---|---|
| `min_free_kbytes` | `WMARK_MIN` 的来源 | 调大：空闲底线更高、更早回收，代价是可用内存变少 |
| `watermark_scale_factor` | min 与 low/high 的间距 | 调大：kswapd 更早启动、更少进入 direct reclaim（默认 10） |
| `swappiness` | 匿名页 vs 文件页回收倾向 | 调大：更愿意换出匿名页（0 附近基本只丢 page cache） |
| `vfs_cache_pressure` | shrinker 回收元数据缓存的力度 | 调大：更积极回收 dentry/inode（默认 100） |
| `zone_reclaim_mode` | NUMA 本地回收策略 | 非 0 时优先在本地 node 回收而非跨 node 分配——**设置不当会让"还有一半空闲内存"的机器频繁进入 direct reclaim**（[PageCache](/docs/CS/OS/Linux/mm/PageCache.md) 记录过这类生产事故） |

另外两个相关但更偏分配侧的旋钮：`overcommit_memory` 决定匿名映射是否严格记账，从而影响"回收与 OOM 谁先发生"；NUMA 平衡（`numa_balancing`）决定跨 node 访问的页要不要主动迁移，属于下一阶段的主题。

## Links

- [物理内存地图（mm 枢纽）](/docs/CS/OS/Linux/mm/README.md)

## References

1. [mm/vmscan.c — Linux source (Bootlin Elixir)](https://elixir.bootlin.com/linux/latest/source/mm/vmscan.c)
2. [Memory Management Concepts — kernel.org documentation](https://www.kernel.org/doc/html/latest/admin-guide/mm/concepts.html)
3. [Multi-Gen LRU — kernel.org documentation](https://www.kernel.org/doc/html/latest/admin-guide/mm/multigen_lru.html)
