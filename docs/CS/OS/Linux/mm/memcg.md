## Introduction

前面几篇讲的都是**系统整体**的内存：`pm.md` 讲物理页怎么组织与分配，`Reclaim.md` 讲空闲页不够时怎么回收，`oom.md` 讲实在回收不出来时杀谁。它们回答的是"这台机器内存怎么管"。

但现代部署里内存不是被单个进程吃光的，而是被**一组进程**吃光的——一个容器、一个 systemd 服务、一次 CI 构建。这时需要的是把内存**按组切开记账、按组设限额、按组回收**。这是 cgroup memory controller（内核里叫 **memcg**）的职责。

需要分清两件事：

- **cgroup core** 负责"把进程分组"这件事本身（层级、`cgroup.procs`、controller 的挂载），属于通用机制，见 [cgroup](/docs/CS/OS/Linux/cgroup.md)；
- **memory controller** 只是挂在 cgroup core 上的一个**控制器**，负责"这个组用了多少内存、能不能再要"。

本篇只讲后者，且只讲内核侧机制：账记在谁头上、限额怎么表达、超限之后走哪条路。用户态接口与 K8s 的映射放在后文。memcg 的隔离效果最终体现在两个出口上——**回收时只动自己的页**（[内存回收](/docs/CS/OS/Linux/mm/Reclaim.md)）与 **OOM 时只杀自己的进程**（[OOM killer](/docs/CS/OS/Linux/mm/oom.md)），这两条是本文与那两篇的接缝。

> 一个容易忽略的前提：memcg **记账的对象是页（folio），不是进程**。进程只是"当前正在替哪个组要内存"的上下文。理解这一点，才能明白为什么页迁移、页缓存、slab 对象都需要各自处理 memcg 归属。

## memcg 在 mm 里的落点

memcg 不是一个漂浮在内存子系统之外的模块，它改写了内存管理的三个基本事实：

**第一，页有了归属。** `struct page` 里多了一个字段记录它记在哪个 memcg 上（完整结构定义见 [struct page](/docs/CS/OS/Linux/mm/memory.md?id=page)）：

```c
#ifdef CONFIG_MEMCG
	unsigned long memcg_data;
#endif
```

**第二，LRU 不再是全局一套。** 回收顺序由 LRU 链表表达，而 memcg 让每条 LRU 变成 **per-node、per-memcg** 一份——这就是"回收只动某个 cgroup 的页"的物质基础（结构见下文 [per-memcg lruvec](#per-memcg-lruvec)）。

**第三，分配路径多了一道关卡。** `alloc_pages()` 成功之后、返回之前，若带 `__GFP_ACCOUNT` 就要向 memcg 报到，记不上账就把页还回去：

```c
	page = __alloc_pages_slowpath(alloc_gfp, order, &ac);

out:
	if (memcg_kmem_online() && (gfp & __GFP_ACCOUNT) && page &&
	    unlikely(__memcg_kmem_charge_page(page, gfp, order) != 0)) {
		__free_pages(page, order);
		page = NULL;
	}
```

这段来自 [alloc_pages](/docs/CS/OS/Linux/mm/pm.md?id=alloc_pages) 的尾部——**分配失败不一定是没内存，也可能是 memcg 配额到顶**。这是排障时最容易被误判的一类"内存充足但分配失败"。

## struct mem_cgroup

memcg 的核心结构（v6.12 `include/linux/memcontrol.h`）。它本身是一个 `cgroup_subsys_state`，挂在 cgroup 层级上，同级的 `cpu` 子系统挂的是 `task_group`（对照见 [cgroup](/docs/CS/OS/Linux/cgroup.md?id=introduction)）：

```c
struct mem_cgroup {
	struct cgroup_subsys_state css;

	/* Private memcg ID. Used to ID objects that outlive the cgroup */
	struct mem_cgroup_id id;

	/* Accounted resources */
	struct page_counter memory;		/* Both v1 & v2 */

	union {
		struct page_counter swap;	/* v2 only */
		struct page_counter memsw;	/* v1 only */
	};

	/* registered local peak watchers */
	struct list_head memory_peaks;
	struct list_head swap_peaks;
	spinlock_t	 peaks_lock;

	/* Range enforcement for interrupt charges */
	struct work_struct high_work;

#ifdef CONFIG_ZSWAP
	unsigned long zswap_max;

	/*
	 * Prevent pages from this memcg from being written back from zswap to
	 * swap, and from being swapped out on zswap store failures.
	 */
	bool zswap_writeback;
#endif

	/* vmpressure notifications */
	struct vmpressure vmpressure;

	/*
	 * Should the OOM killer kill all belonging tasks, had it kill one?
	 */
	bool oom_group;

	int swappiness;

	/* memory.events and memory.events.local */
	struct cgroup_file events_file;
	struct cgroup_file events_local_file;

	/* handle for "memory.swap.events" */
	struct cgroup_file swap_events_file;

	/* memory.stat */
	struct memcg_vmstats	*vmstats;

	/* memory.events */
	atomic_long_t		memory_events[MEMCG_NR_MEMORY_EVENTS];
	atomic_long_t		memory_events_local[MEMCG_NR_MEMORY_EVENTS];

	/*
	 * Hint of reclaim pressure for socket memroy management. Note
	 * that this indicator should NOT be used in legacy cgroup mode
	 * where socket memory is accounted/charged separately.
	 */
	unsigned long		socket_pressure;

	int kmemcg_id;
	/*
	 * memcg->objcg is wiped out as a part of the objcg repaprenting
	 * process. memcg->orig_objcg preserves a pointer (and a reference)
	 * to the original objcg until the end of live of memcg.
	 */
	struct obj_cgroup __rcu	*objcg;
	struct obj_cgroup	*orig_objcg;
	/* list of inherited objcgs, protected by objcg_lock */
	struct list_head objcg_list;

	struct memcg_vmstats_percpu __percpu *vmstats_percpu;

#ifdef CONFIG_CGROUP_WRITEBACK
	struct list_head cgwb_list;
	struct wb_domain cgwb_domain;
	struct memcg_cgwb_frn cgwb_frn[MEMCG_CGWB_FRN_CNT];
#endif

#ifdef CONFIG_TRANSPARENT_HUGEPAGE
	struct deferred_split deferred_split_queue;
#endif

#ifdef CONFIG_LRU_GEN_WALKS_MMU
	/* per-memcg mm_struct list */
	struct lru_gen_mm_list mm_list;
#endif

	struct mem_cgroup_per_node *nodeinfo[];
};
```

（上面刻意略去了被 `#ifdef CONFIG_MEMCG_V1` 包裹的 v1 专属字段——`kmem` / `tcpmem` / `soft_limit` / `oom_lock` / `thresholds` 等约二十个。**v6.12 起这些字段由 CONFIG_MEMCG_V1 决定是否编译**，是 memcg v1 逐步退场的一个信号。）

几个关键字段：

| 字段 | 作用 |
| :-- | :-- |
| `css` | 与 cgroup 层级的挂接点；memcg 首先是"一个 cgroup 节点" |
| `memory` / `swap` | 用量计数器 `page_counter`，**层级累加**——父组的 `memory.current` 含所有子组 |
| `memory_events` / `memory_events_local` | 对应 `memory.events` 与 `memory.events.local`，前者层级化、后者只看本地 |
| `vmstats` | `memory.stat` 的数据源，per-CPU 累加避免竞争 |
| `high_work` | `memory.high` 超限后的**异步节流**工作项，与 `mem_cgroup_handle_over_high()` 配合 |
| `oom_group` | 对应 `memory.oom.group`：整个组要么全杀、要么都不杀 |
| `swappiness` | per-memcg 的回收倾向，覆盖全局 `vm.swappiness` |
| `objcg` | 内核对象（slab）记账的入口，见下文 |
| `cgwb_list` / `cgwb_domain` | 回写限流的 per-memcg 域，页缓存脏页限速要同时看全局与 memcg 两级（见 [PageCache](/docs/CS/OS/Linux/mm/PageCache.md)） |
| `nodeinfo[]` | 柔性数组，每个 NUMA node 一项 `mem_cgroup_per_node` |
| `memory_peaks` / `swap_peaks` | 支撑 `memory.peak` / `memory.swap.peak` 的峰值记录 |

## per-memcg lruvec

`nodeinfo[]` 指向的结构决定了"每个组每个 node 各有一套 LRU"：

```c
struct mem_cgroup_per_node {
	/* Keep the read-only fields at the start */
	struct mem_cgroup	*memcg;		/* Back pointer, we cannot */
						/* use container_of	   */

	struct lruvec_stats_percpu __percpu	*lruvec_stats_percpu;
	struct lruvec_stats			*lruvec_stats;
	struct shrinker_info __rcu		*shrinker_info;

	/* Fields which get updated often at the end. */
	struct lruvec		lruvec;
	CACHELINE_PADDING(_pad2_);
	unsigned long		lru_zone_size[MAX_NR_ZONES][NR_LRU_LISTS];
	struct mem_cgroup_reclaim_iter	iter;
};
```

关键在于 `struct lruvec lruvec`：anon/file × active/inactive 五条链表（外加 unevictable）不是全局一份，而是 **per-node × per-memcg** 一份。回收时的遍历顺序因此变成三层——`shrink_node()` 遍历 node，node 内再 `shrink_node_memcgs()` 逐个 memcg 回收各自的 lruvec：

```
shrink_node()
  └─ shrink_node_memcgs()      ← 逐 memcg（含根 memcg）
       └─ shrink_lruvec()      ← 针对某个 memcg 的 lruvec
```

`iter`（`mem_cgroup_reclaim_iter`）记录"上次扫到哪"，避免每次都从头扫。当 `scan_control.target_mem_cgroup` 非空时（即 `memory.max` 超限触发的局部回收），遍历被限制在目标 memcg 及其子树内——**这就是容器超限时不会去动别的容器的页的原因**，细节见 [内存回收](/docs/CS/OS/Linux/mm/Reclaim.md?id=memcg-回收)。

## 记账：页与内核对象

memcg 有两条记账路径，对应两类资源。

### 页记账（page charge）

页记账发生在页**被某个 memcg 首次使用**的时刻，而不是分配时刻：

- 匿名页缺页分配后，由缺页路径调用 charge；
- 页缓存页在加入 page cache 时 charge 到"触发这次文件访问的 memcg"；
- shmem/tmpfs 页同样计入（`memory.stat` 的 `shmem`）。

入口是内联封装，真正的实现在 `mm/memcontrol.c`：

```c
static inline int mem_cgroup_charge(struct folio *folio, struct mm_struct *mm,
				    gfp_t gfp)
{
	if (mem_cgroup_disabled())
		return 0;
	return __mem_cgroup_charge(folio, mm, gfp);
}

static inline void mem_cgroup_uncharge(struct folio *folio)
{
	if (mem_cgroup_disabled())
		return;
	__mem_cgroup_uncharge(folio);
}
```

（缺页路径里的调用点见 [vm](/docs/CS/OS/Linux/mm/vm.md)；页缓存侧的记账见 [PageCache](/docs/CS/OS/Linux/mm/PageCache.md)。）

内部流程的核心是 `try_charge_memcg()`：把用量加上 `nr_pages`，然后逐级检查当前 memcg 及其祖先是否越过边界——**先看 `memory.high` 决定是否节流，再看 `memory.max` 决定是否回收或 OOM**。charge 失败时调用方必须回滚（`uncharge`），页迁移时记账要跟着页走。

### 对象记账（kmem charge）

slab 里的内核对象（`kmalloc`、`kmem_cache_alloc`）也能算到 memcg 头上，前提是分配时带 `__GFP_ACCOUNT` 且该 cache 被标记为需要记账。路径与页不同，走的是 `obj_cgroup`：

```c
int obj_cgroup_charge(struct obj_cgroup *objcg, gfp_t gfp, size_t size);
void obj_cgroup_uncharge(struct obj_cgroup *objcg, size_t size);
```

之所以要单独一套 `obj_cgroup`，是因为一个 slab 页里可能混着**不同 memcg** 的对象——页级记账粒度太粗，只能做到**对象级**。slab 分配/释放钩子因此要成对出现（见 [slab](/docs/CS/OS/Linux/mm/slab.md)）：

```c
	memcg_slab_free_hook(s, &head, 1);
```

`__GFP_ACCOUNT` 还影响 kmalloc 的"隐式记账"：内核为带 `SLAB_ACCOUNT` 的 cache 建了 `kmalloc-cg-*` 系列，使 `kmalloc(__GFP_ACCOUNT)` 落到专门的池子里。**这也是容器内 slab 用量能被独立统计的原因**——`memory.stat` 的 `slab_reclaimable` / `slab_unreclaimable` 才有意义。

## 限额接口（cgroup v2）

memcg 的用户态视图是一组文件。v2 把它们统一放在 `<cgroup>/memory.*`（v1 的对应名见 [cgroup v1 与 v2](/docs/CS/OS/Linux/cgroup.md?id=cgroup-v1-与-v2)）。

| 接口 | 读写 | 语义 | 默认 |
| :-- | :-- | :-- | :-- |
| `memory.current` | ro | 本组**及所有子孙**当前占用总量 | — |
| `memory.peak` | ro | 历史峰值（支撑"容器内存水位"观测） | — |
| `memory.max` | rw | **硬限制**。到达且收不回来 → 本组内触发 OOM killer | `max` |
| `memory.high` | rw | **节流限制**。超过则本组进程被节流并施加重度回收压力；**绝不触发 OOM** | `max` |
| `memory.low` | rw | **尽力而为保护**。用量在有效 low 边界内，只有在无保护的组里收不出内存时才会被回收 | `0` |
| `memory.min` | rw | **硬保护**。在有效 min 边界内**任何情况下都不回收** | `0` |
| `memory.swap.current` | ro | 本组及子孙当前 swap 占用 | — |
| `memory.swap.max` | rw | swap 硬限制，到达后匿名内存不再换出 | `max` |
| `memory.reclaim` | wo | 主动回收指定量，如 `echo 1G > memory.reclaim`。支持嵌套键 `swappiness` | — |
| `memory.oom.group` | rw | 设为 `1` 时 OOM 把本组（含子孙）当**不可分割负载**整体处理 | `0` |
| `memory.events` | ro | 层级化事件计数（见下） | — |
| `memory.stat` | ro | 内存足迹分解（见下） | — |
| `memory.pressure` | rw | 本组的 PSI 压力停顿信息 | — |
| `memory.numa_stat` | ro | 按 node 拆分的用量 | — |

`memory.high` 与 `memory.max` 可以带 `O_NONBLOCK` 打开，此时**同步回收（和 max 时的 OOM kill）被绕过**：管理员进程改限额不会让自己的 CPU 卡在回收上，代价是目标组要等到下一次 charge 请求才真正受约束——这也意味着用量可能在限额下方"滞留"一段时间。

## 超限之后：三条路径

这是 memcg 最需要分清的一点——**同一个"内存超了"，走哪条路取决于越过的是哪条线**：

```
                        charge 请求（try_charge_memcg）
                                  │
              ┌───────────────────┼───────────────────┐
              ▼                   ▼                   ▼
        用量 ≤ low/min      越过 memory.high      越过 memory.max
        （受保护区间）              │                   │
              │                     ▼                   ▼
              │            节流 + 重回收压力      局部直接回收
              │                     │                   │
              │                     │            收得回来 ──▶ 分配继续
              │                     │                   │
              │            绝不 OOM ─┘            收不回来 ──▶ memcg OOM
              ▼                                          │
       从别的组回收                              （只在目标 memcg 子树内选 victim）
```

- **`memory.high` 是"软墙"**：进程被节流（throttled）并被置于重度回收压力下，但**永远不会因此被杀**。文档明确它的定位是"配合外部监控进程使用"——管理agent 观察到 high 频繁触发，可以扩容或迁移，而不是等 OOM 兜底。
- **`memory.max` 是"硬墙"**：先做**局部**直接回收（只扫目标 memcg 的 lruvec）；收不回来就进 OOM state，在**该 memcg 的进程集合**里挑 victim——`is_memcg_oom()` 为真，`select_bad_process()` 走 `mem_cgroup_scan_tasks()` 只遍历本组，所以杀出的必然是容器自己的进程。完整打分与收割见 [memcg OOM](/docs/CS/OS/Linux/mm/oom.md?id=memcg-oom)。
- **`memory.low` / `memory.min` 是"盾"**：既不是墙也不是杀器，而是让回收器**优先去别处找内存**。

注意文档强调的一点：**默认配置下，普通 0 阶分配总会成功**，除非 OOM killer 恰好选中了当前任务。反之，有些分配**不会**触发 OOM——调用方可能改成返回 `-ENOMEM`（用户态可见）或静默失败（如磁盘预读）。

## 层级保护：low / min 的有效边界

`memory.low` / `memory.min` 不是绝对数值，而是**相对于回收目标**生效的——这是最容易配错的地方。

文档给的例子：

```
root - ... - A - B - C
             \    ` D
              ` E
```

给 B 配置的保护值，在"以 A 为目标的回收"（比如 B 与兄弟 E 竞争）中**原样生效**；但如果回收目标是 A 的祖先，B 的有效保护会被 A 的配置**封顶**。

当子组的保护值之和超过父组所能提供的（**protection overcommit**）时，每个子组按自己**低于保护值的实际用量比例**分到父组保护的一部分——不是简单均分。

两个实践结论：

1. **保护值不是越大越好**。`memory.min` 配得过高会把内存"锁死"，连本该被回收的冷页也动不了；一旦所有组都受保护、一点内存都收不回来，内核只剩下 OOM 一条路——这正是文档里"会导致持续 OOM"的警告。
2. 想表达"不在乎兄弟间谁先被回收"时，用 `memory_recursiveprot` 挂载选项，而不是给所有后代都配一个有限值（后者会污染 `memory.events:low` 的语义）。

## memory.stat 与 memory.events：排障口径

### memory.stat

`memory.stat` 把用量按类型拆开，是判断"容器内存花在哪"的第一手数据。**先记住它的两类口径**：

- **type-based**（按页的类型）：`anon`、`file`、`shmem`、`slab`、`kernel_stack`、`pagetables`……
- **list-based**（按该页当前挂在哪条 LRU 上）：`active_anon`、`inactive_anon`、`active_file`、`inactive_file`、`unevictable`。

**两者并不相等**——文档明确说明 `inactive_foo + active_foo ≠ foo`，因为 shmem 页属于 type 上的 `shmem`，却挂在 anon 的 LRU 上。排障时拿这个等式去对账会得到错误结论。

常用条目：

| 分组 | 条目 | 含义 |
| :-- | :-- | :-- |
| 构成 | `anon` | 匿名映射（`brk`/`mmap(MAP_ANONYMOUS)`） |
| | `file` | 文件缓存，含 tmpfs 与共享内存 |
| | `shmem` | swap-backed 的缓存数据（tmpfs、shm、共享匿名映射） |
| | `kernel` / `kernel_stack` / `pagetables` / `percpu` / `vmalloc` | 内核侧占用（`kernel` 是它们的总和，**非 per-node**） |
| | `slab_reclaimable` / `slab_unreclaimable` | 可分回收（dentry/inode）与不可回收的 slab |
| | `sock` | 网络发送缓冲（**非 per-node**） |
| 回写 | `file_dirty` / `file_writeback` | 已改待回写 / 正在回写 |
| | `file_mapped` | 通过 mmap 映射的缓存页 |
| swap | `swapcached` | 页被换出后又被读回、尚在 swap cache 中的部分（**内存与 swap 双侧都计**） |
| | `zswap` / `zswapped` | zswap 压缩池占用 / 换进 zswap 的应用内存 |
| | `pswpin` / `pswpout` | 换入/换出页数（**非 per-node**） |
| 回收 | `pgscan` / `pgsteal` | 扫描页数 / 实际回收页数 |
| | `pgscan_direct` / `pgsteal_direct` | 其中由**直接回收**完成的部分——**这两个高说明已经在挨打了** |
| | `pgscan_kswapd` / `pgsteal_kswapd` | 后台 kswapd 完成的部分 |
| | `pgscan_proactive` / `pgsteal_proactive` | 由 `memory.reclaim` 主动回收触发的部分 |
| | `pglazyfree` / `pglazyfreed` | 延迟到内存压力时才释放 / 已回收的延迟释放页 |
| refault | `workingset_refault_anon` / `_file` | 刚被回收就被重新读入的次数——**反抖动的关键信号**，对应 [Reclaim](/docs/CS/OS/Linux/mm/Reclaim.md?id=lru-链表与页面老化) 的 workingset |
| | `workingset_activate_anon` / `_file` | refault 后直接被判定为工作集活动页、重新激活 |
| THP | `anon_thp` / `file_thp` / `shmem_thp` | 各类 THP 占用 |
| | `thp_fault_alloc` / `thp_collapse_alloc` | 缺页直接分配 / 折叠产生的 THP |
| NUMA | `numa_pages_migrated` / `numa_pte_updates` / `numa_hint_faults` | NUMA balancing 的迁移与 hint fault 计数 |
| 降级 | `pgdemote_*` | kswapd/direct/khugepaged/proactive 触发的页降级（demotion） |

标了"非 per-node"的条目不会出现在 `memory.numa_stat` 里。条目的**顺序不稳定**（新条目可能插在中间），解析时按 key 查、不要按下标取。

### memory.events

`memory.events` 回答"这个组到底撞过哪条线"，是区分"配额打满"与"全局内存压力"的关键：

| 字段 | 含义 |
| :-- | :-- |
| `low` | 用量在 low 边界内却仍被回收的次数——**通常说明 low 保护被超额配置了** |
| `high` | 越过 high 被节流并转入直接回收的次数 |
| `max` | 用量**将要**越过 max 的次数；若直接回收压不下来，本组进入 OOM state |
| `oom` | 用量达上限、分配即将失败的次数。（OOM 不作为选项时不计数，如高阶分配失败或调用方要求不重试） |
| `oom_kill` | 被**任意** OOM killer 杀掉的、属于本组的进程数 |
| `oom_group_kill` | 触发 `memory.oom.group` 整组杀的次数 |
| `sock_throttled` | 本组关联 socket 被限流的次数 |

注意 `memory.events` 的**所有字段都是层级累加**的——子组发生的事件会反映到父组。只想看本组自身时用 `memory.events.local`。

一个实用判据：**`oom_kill` 有值但 `max` 很小**，说明是全局内存压力下被全局 OOM 波及；**`max` 与 `oom` 同步增长**，才是 memcg 限额自己触发的局部 OOM。

## 与 K8s / 容器的映射

memcg 是容器内存隔离的全部内核基础，K8s 层的字段最终都落到上面这些文件上：

| K8s / 容器 | memcg 落点 |
| :-- | :-- |
| `resources.limits.memory` | `memory.max`（v2） / `memory.limit_in_bytes`（v1） |
| `resources.requests.memory` | `memory.low`（kubelet 的 MemoryQoS 特性，cgroup v2）——让节点回收时优先动超过 request 的部分 |
| Pod QoS 等级 | `oom_score_adj`：Guaranteed 设 `-997`、BestEffort 设 `1000`、Burstable 按 `min(max(2, 1000 - memoryRequestBytes/memoryLimitBytes*1000), 999)` 计算（对照表见 [Pod](/docs/CS/Container/k8s/Pod.md?id=资源与-qos)） |
| 容器被杀、退出码 137 | memcg 局部 OOM 触发 `SIGKILL` → `OOMKilled`（排障路径见 [Issues](/docs/CS/Container/k8s/Issues.md)） |
| 容器内 `free`/`top` 显示宿主机数据 | `/proc` 不感知 cgroup（v2 也未根治），生产用 lxcfs 修正 |

一个常见误解值得点破：**QoS 等级（`oom_score_adj`）管的是"全局 OOM 时先杀谁"，`memory.max` 管的是"这个容器能不能超限"**——两套机制，两个出口。Guaranteed Pod 在节点全局 OOM 时最后被杀，但如果它自己的 `memory.max` 到顶，照样在容器内被 OOM。

## 调优与陷阱

- **别用 `memory.stat` 的等式对账**：`inactive_foo + active_foo ≠ foo`（口径不同），`kernel` / `sock` / `pswp*` / `pgscan*` 等标注非 per-node 的条目不进 `memory.numa_stat`。
- **`memory.high` 才该是日常旋钮**：它节流但不杀，给了管理侧反应时间；`memory.max` 是最后防线。文档的建议是——high 可以超额配置（high 之和 > 可用内存），让全局内存压力按实际用量去分配。
- **`memory.min` 慎用**：硬保护，配过头会把内存锁死、逼出持续 OOM；`memory.low` 的软保护通常够用。
- **`memory.reclaim` 主动回收可能欠收**：回收量少于指定值时返回 `-EAGAIN`（内核可能多收也可能少收）。另外这种主动回收**不代表内存压力**，因此不会触发网络层的 socket 内存适配。
- **`memory.swap.max` 与全局 swap 是两层**：容器 swap 到顶不代表宿主机 swap 到顶，反之亦然。
- **v1 的对应关系要成对记**：`memory.limit_in_bytes`↔`memory.max`、`memory.soft_limit_in_bytes`↔（v2 无直接等价，由 `high`/`low` 分担）、`memory.memsw.limit_in_bytes`↔`memory.swap.max`。v1 无 `memory.high` 这一档，**v1 下没有"只节流不杀"的选项**。

## Links

- [内存管理知识地图（mm 枢纽）](/docs/CS/OS/Linux/mm/README.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)

## References

1. [Control Group v2 — Memory Controller (kernel.org)](https://docs.kernel.org/admin-guide/cgroup-v2.html)
2. [mm/memcontrol.c — Linux v6.12 (Bootlin Elixir)](https://elixir.bootlin.com/linux/v6.12/source/mm/memcontrol.c)
3. [include/linux/memcontrol.h — Linux v6.12 (Bootlin Elixir)](https://elixir.bootlin.com/linux/v6.12/source/include/linux/memcontrol.h)
4. [Pressure Stall Information — kernel.org documentation](https://docs.kernel.org/accounting/psi.html)
