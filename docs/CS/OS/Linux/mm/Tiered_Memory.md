# Tiered and Heterogeneous Memory

## Introduction

NUMA 把内存切成 node，是因为跨 socket 的远端访问比本地慢；而 PMem、CXL.mem 这类介质的出现，让"机器上同时存在快但贵、慢但便宜"的内存成了常态。于是内核不再把各 node 当成同速的平面，而是按**速度**把它们排成若干 **tier（层）**：最快的 DRAM 在顶层，慢速的大容量介质在底层。

分层内存解决的，是"回收但不丢数据"的更轻路径——冷匿名页不必立刻换出到磁盘，可以先 **demote（降级）** 到下层 node 保留；再次变热时再 **promote（提升）** 回上层。它一头接在 [Reclaim](/docs/CS/OS/Linux/mm/Reclaim.md) 的回收决策之后，一头接在 [Numa](/docs/CS/OS/Linux/mm/Numa.md) 的 AutoNUMA 平衡之上，是冷热分层在 NUMA 维度的完整展开。

本篇讲清三件事：tier 是什么、demote/promote 两条流向怎么走、tier 的速度信息又从硬件（HMAT / CXL）怎么来。

## Memory Tiers: the Abstraction

分层的核心是 **abstract distance（adistance，抽象距离）**——一个把"多快"量化的整数。tier 编号由 adistance 推导，而非写死的枚举：

```c
// include/linux/memory-tiers.h
#define MEMTIER_CHUNK_BITS        7
#define MEMTIER_CHUNK_SIZE        (1 << MEMTIER_CHUNK_BITS)   // 128
#define MEMTIER_ADISTANCE_DRAM    ((4L * MEMTIER_CHUNK_SIZE) + (MEMTIER_CHUNK_SIZE >> 1))  // = 576
// tier 编号 = adistance >> MEMTIER_CHUNK_BITS
```

语义很直接：**adistance 越小越快，tier 数字越小越靠上**。`MEMTIER_ADISTANCE_DRAM=576` 经过 `adistance >> 7` 落进 **tier 4**，这是 DRAM 的默认归宿。DAX/kmem 无 HMAT/CDAT 覆盖时默认 `MEMTIER_DEFAULT_DAX_ADISTANCE = 576 * 5 = 2880` → **tier 22**，是比 DRAM 慢得多的底层。CXL.mem 不被写死，按 CDAT 实测性能落在 4 与 22 之间。

> v7.2 里**已没有 `MEMORY_TIER_*` 枚举宏**，tier 完全由 adistance 推导（`new_memtier->dev.id = adistance >> MEMTIER_CHUNK_BITS`），也没有独立的 `rank` 接口——tier 命名全靠 adistance。

`mm/memory-tiers.c` 维护这套结构：`set_node_memory_tier()` 给 node 算 tier、`establish_demotion_targets()` 构建 `lower_tier_mask`。只有 **toptier**（adistance ≤ `top_tier_adistance`，即 DRAM 所在层）节点会**发起** demote，目标指向更低 tier。

**用户侧**：`/sys/devices/virtual/memory_tiering/memory_tierN/nodelist` 列出每层包含哪些 node（注意路径是 `virtual/memory_tiering`，且只有 `nodelist`，**没有** `max_tier`/`rank`）。node 自己目录下只有 `access0`/`access1`，没有 `tier` 文件。

**使能开关**：由 `CONFIG_NUMA` + `CONFIG_NUMA_MIGRATION` 决定（**没有** `CONFIG_MEMORY_TIERING` 这个 Kconfig）。demote 全局开关 `numa_demotion_enabled` 默认 **false**，需 `echo 1 > /sys/kernel/mm/numa/demotion_enabled` 才生效（`memory-tiers.c:939`）。

## demote: Cold Pages Flow Down

demote 的入口在回收侧。`shrink_folio_list()` 走完主循环、处理完所有候选之后，在末尾统一把收集到的降级候选迁移走：

```c
// mm/vmscan.c  shrink_folio_list()
/* 'folio_list' is always empty here */
/* Migrate folios selected for demotion */
nr_demoted = demote_folio_list(&demote_folios, pgdat, memcg);   // vmscan.c:1543
nr_reclaimed += nr_demoted;
/* Folios that could not be demoted are still in @demote_folios */
if (!list_empty(&demote_folios)) {
    list_splice_init(&demote_folios, folio_list);   // 降级失败 → 回到回收列表走 swap
    ...
}
```

候选来自主循环里被选中的冷匿名页；`struct scan_control` 上的 `no_demotion` 标志决定"直接丢弃还是尝试降级"（[Reclaim](/docs/CS/OS/Linux/mm/Reclaim.md) 里 `/* Always discard instead of demoting to lower tier memory */`，`Reclaim.md:188`）。降级本身由 `alloc_demote_folio()` 选目标 node（`next_demotion_node()`，`vmscan.c:957/1016`），底层走 `migrate_pages()`。

demote 比换出便宜：页只是**迁移**到同机另一块慢内存，数据不丢、无磁盘 IO；源码注释明确点出偏好——"Reclaiming directly from top tier nodes is not often desired … memory should be reclaimed from lower tier nodes and demoted from top tier nodes"。但前提是 `numa_demotion_enabled` 为真，否则 `next_demotion_node` 一类前置检查直接返回（vmscan.c:323 `if (!pgdat || !numa_demotion_enabled)`），冷页就老老实实走 swap。

可见性：`/proc/vmstat` 的 `pgdemote_kswapd` / `pgdemote_direct` 统计降级页数。

## promote: Hot Pages Flow Up

promote 是 demote 的反向，落点和 [Numa](/docs/CS/OS/Linux/mm/Numa.md) 的 AutoNUMA 是同一处：hinting fault 触发 `migrate_misplaced_folio()` 把热页搬到当前 CPU 所在（更快）node。

但**分层 promote 默认是关的**。AutoNUMA 的总开关 `numa_balancing` 默认 1，可它只是基础平衡；是否做"跨 tier 的提升"还要看 `sysctl_numa_balancing_mode` 里的 `NUMA_BALANCING_MEMORY_TIERING` 位（`0x2`，`include/linux/sched/sysctl.h:24`）——该位**默认未置**，所以默认不会把页从慢 tier 主动提升回 DRAM。开启方式：`echo 2 > /proc/sys/kernel/numa_balancing`（在基础模式上加 tiering 位）。

promote 有速率上限，避免瞬间把大量页搬回快 node 抖动：

```c
// kernel/sched/fair.c
static unsigned int sysctl_numa_balancing_promote_rate_limit = 65536;   // fair.c:130
// /proc/sys/kernel/numa_balancing_promote_rate_limit_MBps  (fair.c:147)
rate_limit = MB_TO_PAGES(sysctl_numa_balancing_promote_rate_limit);     // fair.c:2716
```

demote 与 promote 共用 `migrate_pages()` / `migrate_folio()` 这套迁移基础设施，区别只在触发源（回收侧 vs 平衡侧）与目标方向（下层 vs 上层）。

## Hardware Sources: HMAT and CXL

demote 能否发生、目标落在哪层，取决于硬件喂给内核的"速度"信息。这条因果链的起点是固件/设备。

### HMAT (ACPI Heterogeneous Memory Attribute Table)

`drivers/acpi/numa/hmat.c` 的 `hmat_init()` 以 `subsys_initcall` 注册（hmat.c:1040），先解析 SRAT 的 Memory Affinity 与 **Generic Port Affinity**（hmat.c:1053/1059），再逐 subtable 解析 HMAT，给出 **initiator（CPU/GPU）→ target（内存 node）的延迟与带宽坐标**，以及 memory side cache 信息。它把这些信息沉淀进 node 的 access 属性，并在 `hmat_calculate_adistance()`（hmat.c:972）里注册为 adistance 计算回调（`register_mt_adistance_algorithm`，hmat.c:1096，priority 100）。

用户可见形态是 `/sys/devices/system/node/nodeN/access0/`（本地 initiator 访问类 `ACCESS_COORDINATE_LOCAL`）与 `access1/`（CPU 访问类 `ACCESS_COORDINATE_CPU`），其下 `initiators/`、`read_latency`、`read_bandwidth` 等由 HMAT 写入。

### abstract distance and the Notifier Chain

adistance 不是 HMAT 私有的——它是一个**可插拔的通知链**框架，让不同硬件源各自贡献自己的距离算法：

```c
// mm/memory-tiers.c
BLOCKING_NOTIFIER_HEAD(mt_adistance_algorithms);                  // memory-tiers.c:134
int mt_calc_adistance(int node, int *adist) {                    // :875
    return blocking_notifier_call_chain(&mt_adistance_algorithms, node, adist);
}
int register_mt_adistance_algorithm(struct notifier_block *nb);  // :847
```

HMAT（`hmat_calculate_adistance`）与 CXL（`cxl_region_calculate_adistance`）都注册到这条链，各自用 `mt_perf_to_adistance()` 以**默认 DRAM 性能为基准**换算：延迟正比、带宽反比。最终 `set_node_memory_tier()` 用该 adistance 经 `find_create_memory_tier` 得到 `tier N = adistance >> 7`。

### CXL.mem

CXL 设备经 **CDAT（CXL Device Attribute Table）** 通过 DOE 读取延迟/带宽（解析在 `drivers/cxl/core/cdat.c`），由 `cxl_region_calculate_adistance()`（`drivers/cxl/core/region.c:4186`）注册到 adistance 链（priority 100），性能坐标来自 `cxlr->coord[ACCESS_COORDINATE_CPU]`。节点本身由 ACPI SRAT Generic Port 建立，CXL 驱动（`drivers/cxl/acpi.c`、`drivers/cxl/mem.c`）把它枚举为 CXL port/endpoint。

关键一步是把这块硬件**变成可用 RAM**：`drivers/dax/kmem.c` 的 `dev_dax_kmem_probe()` 调 `add_memory_driver_managed()`（kmem.c:177）把 device-DAX 区域注册为 "System RAM (kmem)"，成为普通 NUMA node；再经 `mt_calc_adistance()` + `init_node_memory_type()` 归入对应 tier。`drivers/dax/hmem/hmem.c`（`DEV_DAX_HMEM`）则负责把平台/ACPI 描述的 "specific purpose" 内存（EFI_MEMORY_SP）暴露为 platform device，再交给 kmem 真正 online——hmem 暴露资源、kmem 真正接管。

### From Hardware to Tier: the Causal Chain

完整链路：

```
硬件/固件给性能坐标
   ├─ HMAT (ACPI)：SRAT + HMAT → 延迟/带宽
   └─ CXL.mem：CDAT (DOE) → 延迟/带宽
        │
        ▼
mt_calc_adistance(node) 遍历 notifier 链
   ├─ hmat_calculate_adistance()        (priority 100)
   └─ cxl_region_calculate_adistance()  (priority 100)
        │  mt_perf_to_adistance() 以 DRAM=576 为基准换算
        ▼
adistance ──(>> 7)──► tier N   (DRAM=4, kmem 默认=22, CXL 居中)
        │
        ▼
establish_demotion_targets() 建 lower_tier_mask
        │
        ▼
shrink_folio_list() 把冷页 demote 到更低 tier 的 CXL/PMem node
（而非写 swap）
```

**结论**：是 HMAT/CXL 经 adistance 把慢介质放到比 DRAM 更低的 tier，才使它们成为 demote 目标；而这一切的前提是 kmem 已把硬件 online 为一个 NUMA node。

## Coupling with the MM Subsystem

- **与 [Reclaim](/docs/CS/OS/Linux/mm/Reclaim.md)**：demote 在 `shrink_folio_list` 主循环之后触发，是换出之前的"软着陆"；`no_demotion` 标志决定降级还是直接丢。把它当成匿名页回收去向的第三种（次于保留、先于 swap）。
- **与 [Numa](/docs/CS/OS/Linux/mm/Numa.md)**：promote 是 AutoNUMA 的"升级"面，demote 是回收侧的"降级"面，二者合起来构成冷热分层。
- **与 [MGLRU](/docs/CS/OS/Linux/mm/MGLRU.md)**：MGLRU 的 `evict_folios()` 也复用 `shrink_folio_list()` 的 demote 路径，多代 LRU 的冷页同样能落到下层 tier。
- **与 memcg**：`shrink_folio_list()` 把 `sc->target_mem_cgroup` 透传给 `demote_folio_list()`，demote 按 cgroup 限流，压缩占用与迁移都纳入容器视角（见 [memcg](/docs/CS/OS/Linux/mm/memcg.md) 的记账与限额）。
- **与 [DAMON](/docs/CS/OS/Linux/mm/DAMON.md)**：DAMON 的 `DAMOS_MIGRATE_HOT/COLD` 是 AutoNUMA 之外的另一条迁移触发源，但它只做**冷热分类**——迁移的目标 node 由用户态按 `memory_tiering` 显式填入 scheme 的 `target_nid`，DAMON 自身不推断 tier 拓扑。二者是"信号源 vs 目标决策"的分工。

## Tuning and Observation

| 接口 | 用途 |
| --- | --- |
| `/sys/kernel/mm/numa/demotion_enabled` | 0/1 全局启停 demote（默认 0 关闭） |
| `/proc/sys/kernel/numa_balancing` | 0 关 / 1 基础平衡 / 2 叠加 `NUMA_BALANCING_MEMORY_TIERING`（promote 分层） |
| `/proc/sys/kernel/numa_balancing_promote_rate_limit_MBps` | promote 速率上限（默认 65536 MB/s） |
| `/sys/devices/virtual/memory_tiering/memory_tierN/nodelist` | 各 tier 包含的 NUMA node |
| `/sys/devices/system/node/nodeN/access{0,1}/{read_latency,read_bandwidth}` | HMAT 给出的该 node 性能坐标 |
| `/proc/vmstat` 的 `pgdemote_kswapd` / `pgdemote_direct` | 降级页数统计 |
| `numastat` / `numactl -H` | node 拓扑与本地/远端命中 |

## Links

- [NUMA 平衡 Numa](/docs/CS/OS/Linux/mm/Numa.md) — promote 落点（AutoNUMA hinting fault）与 demote/promote 概念入口
- [内存回收 Reclaim](/docs/CS/OS/Linux/mm/Reclaim.md) — demote 在 `shrink_folio_list` 之后的触发位置与 `no_demotion`
- [多代 LRU MGLRU](/docs/CS/OS/Linux/mm/MGLRU.md) — `evict_folios` 复用 demote 路径
- [cgroup](/docs/CS/OS/Linux/cgroup.md) — 容器视角下 demote/migration 的限额与记账
- [DAMON 访问监控](/docs/CS/OS/Linux/mm/DAMON.md) — 另一条迁移触发源，目标 node 由用户态按 tier 配置
- [Page Migration 页迁移](/docs/CS/OS/Linux/mm/Page_Migration.md) — demote/promote 都是本引擎的 MR_DEMOTION/MR_NUMA_MISPLACED 调用方

## References

1. LWN.net — "The memory tiering subsystem" 系列报道：https://lwn.net/Articles/?q=memory+tiering （已实测可访问）
2. 本地内核文档 `Documentation/ABI/testing/sysfs-kernel-mm-numa` — 内存分层 sysfs ABI（`demotion_enabled` 等接口定义）
3. 本地内核文档 `Documentation/admin-guide/sysctl/kernel.rst` — `numa_balancing_promote_rate_limit_MBps` 说明
4. 本地内核文档 `Documentation/driver-api/cxl/` — CXL 驱动 API 与设备属性
