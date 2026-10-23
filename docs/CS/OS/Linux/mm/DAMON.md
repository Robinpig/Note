# DAMON

## Introduction

DAMON（Data Access Monitor）是内核里一个**轻量、可观测、可自动操作**的数据访问监控框架。它回答的不是"这块内存现在被谁占着"（那是 `/proc/<pid>/smaps` 的活），而是"这块内存在一段时间里**被访问了多少次、访问模式是什么样**"——并进一步允许你按访问模式自动施加操作（回收冷页、把热页提权、迁移到合适的 NUMA tier 等）。

它和本目录下其他机制的关系是**正交且可叠加**的：MGLRU 用"代"重排 LRU 老化顺序、Reclaim 在压力下逐页决策，而 DAMON 用**采样 + 自适应区域**的方式独立观察访问热度，并通过 DAMOS 把"观察"直接变成"动作"。它既不替代 Reclaim，也不替代 AutoNUMA，而是给它们一个更精确的冷热信号源，甚至能在压力到来**之前**主动回收。

## Monitoring Model: Sampling plus Adaptive Regions

DAMON 的监控建立在三个核心思想上，都不依赖 page fault 或传统 LRU：

- **采样（sampling）**：每个 `sample_interval` 对一个 region 的访问位做一次检查，而不是每次访问都计数。
- **自适应区域（adaptive regions）**：监控目标地址空间被切成若干变长的 `struct damon_region`，访问多的区域自动拆细、访问少的区域自动合并，从而把采样精度集中在真正有变化的地址范围。
- **判定靠 Accessed 位**：无论监控虚拟地址还是物理地址，最终都是通过 PTE/PMD 的 Accessed 位判断"这段时间内有没有被访问"，而非插桩每次访存。

### Core Data Structures

`include/linux/damon.h` 是类型中枢：

- `struct damon_ctx`（`damon.h:852+`）：一次监控会话的顶层上下文，持有 `attrs`（节奏参数）、`adaptive_targets`（被监控的 `damon_target` 链表）、`schemes`（DAMOS 操作列表）。
- `struct damon_target`（`damon.h:104`）：一个被监控对象，虚拟地址监控下通常对应一个 `pid` 的地址空间，物理地址监控下一个 target 覆盖整段物理区间；它挂着一串 `regions_list`。
- `struct damon_region`（`damon.h:74`）：核心监控单元，记录 `ar`（地址区间 `struct damon_addr_range`）、`nr_accesses` / `nr_accesses_bp`（访问次数，basis-point 形式）、`age`（连续未被访问/已访问的轮数）、`probe_hits[DAMON_MAX_PROBES]`（v7.2 新增的 probes 机制，`damon.h:19` 定义 `DAMON_MAX_PROBES=4`）。注意区域大小过滤**不是** `region` 的字段，而是通过 `struct damos_access_pattern` 的 `min_sz_region/max_sz_region`（`damon.h:493`）在 scheme 匹配时筛选。
- `struct damon_attrs`（`damon.h:802`）：`sample_interval`、`aggr_interval`、`ops_update_interval`、`min_nr_regions`、`max_nr_regions`——决定采样/聚合节奏与区域数量边界。

### Monitor Ops: vaddr and paddr

监控的实际"怎么读 Accessed 位"由两个 `struct damon_operations`（`damon.h:671`，注意不是旧名 `damon_ops`）实例提供：

- **`damon_va_ops`（DAMON_OPS_VADDR，`vaddr.c:940`）**：直接 walk 目标进程的页表，`damon_va_mkold` / `damon_va_young`（`vaddr.c:267-540`）清/读 `pte_young` / `pmd_young`。它知道地址空间语义（哪个进程、哪段 VMA），但只能监控有 `mm` 的用户进程。
- **`damon_pa_ops`（DAMON_OPS_PADDR）**：不依赖任何进程，直接对所有物理页做监控。`damon_pa_young`（`paddr.c:68`）→ `damon_folio_young`（`ops-common.c:236`），后者经 rmap（`page_vma_mapped_walk`）反查 PTE/PMD 的 Accessed 位，并借助 `folio_test_idle` / `mmu_notifier_test_young` 判定。它能覆盖内核页、多映射页，但拿不到"是哪个进程访问的"语义。v7.2 还有 `DAMON_OPS_FVADDR`（固定虚拟地址区间监控）增加灵活性。

二者**本质都依赖 PTE/PMD 的 Accessed 位**——所谓"物理页 Accessed"是 paddr 经反向映射触达 PTE 的一种简化说法，并非独立的硬件路径。

### Aggregation Cadence

`kdamond_fn`（`core.c:3506`）是后台内核线程主体：每 `sample_interval`（默认 5000us，`core.c:716`）做一次 `prepare_access_checks` + 等待 + `check_accesses`；每 `aggr_interval`（默认 100000us，`core.c:717`）做 `kdamond_merge_regions` / `kdamond_split_regions`（`core.c:3120` / `core.c:3276`），更新每个 region 的 `nr_accesses` 与 `age`。默认值即"5ms 采样、100ms 聚合"的轻量节奏。

## DAMOS: Operation Schemes

光监控还不够，DAMON 的真正杠杆是 **DAMOS（DAMON-based Operation Schemes）**：用一组匹配条件筛出"符合某访问模式的 region"，对其施加一个动作。

### struct damos and Access Pattern

`struct damos`（`damon.h:570`）由三部分组成：

- `pattern`（`struct damos_access_pattern`，`damon.h:493`）：匹配条件，按**尺寸**（`min_sz_region/max_sz_region`）、**访问频次**（`min_nr_accesses/max_nr_accesses`）、**age**（`min_age_region/max_age_region`）三维区间筛选。例如"尺寸 >64KiB 且最近几乎没被访问"就命中冷页模式。
- `action`（`enum damos_action`）：对命中 region 做什么。
- `quota` / `wmarks` / `*_filters`：配额上限、水位线触发、过滤条件（按地址/类型等）。v7.2 还引入 `apply_interval_us`（`damon.h:573`，取代旧 `apply_interval`）与 **quota auto-tuning goals**（基于 PSI 反馈自动调配额，`enum damos_quota_goal_metric`，`damon.h:167`）。

### Action Enumeration

`enum damos_action`（`damon.h:135`）在 v7.2.7 真实包含的完整集：

| Action | 语义 |
| --- | --- |
| `DAMOS_WILLNEED` | 提示即将访问，预热到 active LRU |
| `DAMOS_COLD` | 降级到 inactive LRU |
| `DAMOS_PAGEOUT` | 主动回写/换出（落点与 Reclaim 的 pageout 同一条） |
| `DAMOS_HUGEPAGE` | `madvise(MADV_HUGEPAGE)` 促大页 |
| `DAMOS_NOHUGEPAGE` | `madvise(MADV_NOHUGEPAGE)` |
| `DAMOS_COLLAPSE` | `madvise(MADV_COLLAPSE)` 立即折叠大页（`damon.h:121`，v7.2 新增） |
| `DAMOS_LRU_PRIO` | 提到 LRU 头部（辅助老化） |
| `DAMOS_LRU_DEPRIO` | 推到 LRU 尾部 |
| `DAMOS_MIGRATE_HOT` | 按热度把 region 迁到更优 node |
| `DAMOS_MIGRATE_COLD` | 按冷度把 region 迁到下层 node |
| `DAMOS_STAT` | 仅统计、不施加动作（`damon.h:146`） |

注意 `DAMOS_LRU_PRIO` / `DAMOS_LRU_DEPRIO` 中间**没有**下划线，是 v7.2 的正式符号。

### DAMOS_MIGRATE and Tiered Memory

`DAMOS_MIGRATE_HOT` / `DAMOS_MIGRATE_COLD` 是 AutoNUMA promote/demote 之外**另一条迁移触发源**：paddr 侧 `damon_pa_apply_scheme`（`paddr.c:396`）对这两个动作调 `damon_pa_migrate` → `damon_migrate_pages(&folio_list, s->target_nid)`（`ops-common.c:387`）。

**但有一个关键事实必须讲清**：DAMON 只做**冷热分类**（用 `damon_hot_score` / `damon_cold_score` 给 region 打分，`paddr.c:408`），**迁移的目标 NUMA node 是用户态显式配置的**——通过 scheme 的 `target_nid`（`sysfs-schemes.c:2626`）或 `dests/` 多目标加权（`sysfs-schemes.c:2156`）。DAMON 本身**不会**从内存层级（tier 拓扑）自动推断 promote/demote 目标，节点选择通常由 `damo` 工具或 tiering 守护进程按 `memory_tiering` 信息填入。因此它和 [分层内存 Tiered_Memory](/docs/CS/OS/Linux/mm/Tiered_Memory.md) 是"信号源 vs 目标决策"的分工关系，而非互相替代。

## Built-in Modules

DAMON 自带几个把监控+操作封装成"开箱即用策略"的内核模块（v7.2 下都平铺为顶层文件，不再有 `modules/` 子目录）：

### damon_reclaim

`mm/damon/reclaim.c` 是 **proactive reclaim 的 DAMON 实现**：周期性跑一个监控 context，把"长期（>min_age）未被访问"的页用 `DAMOS_PAGEOUT` 主动回收，比 kswapd 更主动、目标更精确（按采样冷度而非全局压力）。

主要参数（v7.2 真实存在）：`enabled`（`reclaim.c:28,419`）、`min_age`（`reclaim.c:47`，冷页年龄阈值）、`quota_mem_pressure_us`（`reclaim.c:75`，PSI 反馈式配额上限）、`quota_autotune_feedback`（`reclaim.c:90`）、`skip_anon`（`reclaim.c:158`）、`monitor_region_start/end`、`commit_inputs`、`kdamond_pid`。注意旧的 `target_reclaim`/字节 `quota` 命名已被 **PSI 反馈式 auto-tuning 配额**取代（`reclaim.c:50,245`）——这是 damon_reclaim 与 [内存回收 Reclaim](/docs/CS/OS/Linux/mm/Reclaim.md) 的 proactive compaction 是**不同机制**（前者走回收、后者走碎片整理）的又一佐证。

### damon_lru_sort

`mm/damon/lru_sort.c` 用 DAMON 把"一直热"的页 `DAMOS_LRU_PRIO`、"一直冷"的页 `DAMOS_LRU_DEPRIO`，直接改写 LRU 链表顺序，辅助老化。参数含 `hot_thres_access_freq`（`lru_sort.c:92`）、`cold_min_age`（`lru_sort.c:104`）、`active_mem_bp`（配额目标）。

与 [MGLRU 多代 LRU](/docs/CS/OS/Linux/mm/MGLRU.md) 的关系：**竞争点**是"谁主导回收顺序"——MGLRU 用"代"重定义老化、lru_sort 用采样结果直接挪 LRU 位置；**互补点**是 lru_sort 不动回收算法本身，可与 MGLRU 或传统 LRU 共存，但同一份 LRU 上两机制会互相影响，实践中通常择一为主。

### damon_stat

`mm/damon/stat.c`（v7.2 新增，`Kconfig:108`）是一个纯统计子系统：跑 DAMON 并用 `DAMOS_STAT` 暴露简单访问指标，默认随 `DAMON_STAT` 开启。

## User Interface

### sysfs: /sys/kernel/mm/damon/admin

v7.2 的**唯一官方接口**是 sysfs，层级为 `admin/` → `kdamonds/` → 每个 kdamond → `contexts/` → 每个 context → `monitoring_attrs/` + `targets/`（含 `regions/` 的 `init_regions`）+ `schemes/`。每个 scheme 下含 `access_pattern/{sz,nr_accesses,age}`（`sysfs-schemes.c:1997`）、`target_nid`、`dests/`、`apply_interval`、quota、wmarks、filters，以及新增的 `probes/` 目录（`sysfs.c:1118`）。

### debugfs removed

`/sys/kernel/debug/damon/` 在 v7.2.7 **已完全移除**——`mm/damon/` 下无 `dbgfs.c`、`Kconfig` 无 `CONFIG_DAMON_DEBUGFS`。sysfs 取代 debugfs 的过程在 v7.2 已 100% 完成，旧文档里基于 debugfs 的用法全部作废。

### Kconfig and defaults

`mm/damon/Kconfig` 下：`DAMON` 为 `bool` 且**无 default → 默认关**；`DAMON_VADDR` / `DAMON_PADDR` / `DAMON_SYSFS` 均 `default DAMON`（即跟随 DAMON，默认关），分别 `select PAGE_IDLE_FLAG` 并依赖 `MMU`；`DAMON_RECLAIM` / `DAMON_LRU_SORT` / `DAMON_STAT` 都 `depends on DAMON_PADDR` 且无 default → **默认不构建**。也就是说，发行版若没显式打开 `CONFIG_DAMON`，以上能力全不可用。

## Coupling with Existing Subsystems

把 DAMON 放进 `mm/` 的因果链里：

- **与 MGLRU**：都追求"更精确的冷热判定"，但 MGLRU 只改回收顺序、不回收；DAMON 通过 DAMOS 能直接触发 `PAGEOUT/LRU_PRIO/MIGRATE` 等操作。`damon_lru_sort` 与 MGLRU 在同一 LRU 上可能竞争，通常以其一为主。
- **与 Reclaim**：`damon_reclaim` 的 proactive reclaim 比 kswapd 更前置、更精准；`DAMOS_PAGEOUT` 最终经 `damon_pa_pageout`（`paddr.c:388`）走与 `shrink_folio_list` 相同的回收落点。
- **与 Tiered Memory / NUMA**：`DAMOS_MIGRATE_HOT/COLD` 是 AutoNUMA hinting-fault promote 之外的另一条迁移触发源，但目标 node 由用户态按 tier 信息配置，DAMON 自身不做 tier 拓扑推断。
- **与 pagetable**：vaddr/paddr 这两个 monitor ops 的底层都是读/清 PTE/PMD 的 Accessed 位（`pte_young` / `pmd_young`），因此 DAMON 的监控精度直接受 [页表 pagetable](/docs/CS/OS/Linux/mm/pagetable.md) 的 Accessed 位语义影响。

## Links

- [Linux 内核总览](/docs/CS/OS/Linux/Linux.md)
- [内存回收 Reclaim](/docs/CS/OS/Linux/mm/Reclaim.md)
- [MGLRU 多代 LRU](/docs/CS/OS/Linux/mm/MGLRU.md)
- [分层内存 Tiered_Memory](/docs/CS/OS/Linux/mm/Tiered_Memory.md)
- [PSI 压力失速](/docs/CS/OS/Linux/mm/PSI.md) — `damon_reclaim` 的配额由 PSI 反馈自动调节

## References

1. 本地文档 `<linux-7.2.7>/Documentation/admin-guide/mm/damon/`（含 index/start/usage/reclaim/lru_sort/stat.rst，与 v7.2.7 一一对应，最可靠）
2. 本地文档 `<linux-7.2.7>/Documentation/mm/damon/design.rst`（`damon.h:130` 注释引用的设计说明，含各 action 的 ops 支持状态）
3. LWN — "Pressure stall information" 系列（DAMON 的 reclaim 模块用 PSI 做配额反馈，见上文）：https://lwn.net/Articles/759423/
4. LWN — DAMON 内核索引页（持续跟踪 DAMON 系列文章）：https://lwn.net/Kernel/Index/#DAMON
