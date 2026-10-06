## Introduction

[物理内存主线](/docs/CS/OS/Linux/mm/pm.md)把内存按 NUMA 切成了 node，并强调一个事实：**本地内存与远端内存的访问延迟不等价**——跨 socket 访问可能慢一倍以上。但切完 node 只是"有了位置概念"，紧接着的问题是：进程和它访问的页，初始未必待在同一个 node 上。调度器把任务放到哪个 CPU、fork 后内存落在哪个 node、内存被多个 node 上的任务共享——这些都会造成大量"远端访问"。

NUMA 平衡（NUMA balancing）回答的就是"**让任务和它的数据尽量待在同一个 node 上**"。它由两套互补的机制组成：一套是内核自动进行的 **AutoNUMA**（扫描页表制造 hinting fault，按需迁移页），另一套是用户通过 **mempolicy** 显式表达的放置策略；而 `zone_reclaim_mode` 则控制分配失败时"先本地回收还是直接用远端内存"。本篇按这条顺序展开。

## AutoNUMA：用 hinting fault 探测访问模式

内核不可能知道进程"逻辑上属于哪个 node"，只能在运行中观测。AutoNUMA 的思路很巧妙：周期性地把进程页表项标记为 **PROT_NONE**（但映射本身保留），这样任务一旦真正访问该页，就会触发一次专门的 **NUMA hinting fault**——fault 不是错误，而是一次"我在这个 CPU 上、访问了这个 node 上的页"的采样信号。

扫描由调度器驱动：`task_tick_numa()` 累计时间，到达阈值后通过 `task_numa_work()` 走查该任务的地址空间，分批调用 `change_prot_numa()` 把下一批 PTE 改为不可访问。相关开关与节流参数都在 `/proc/sys/kernel/numa_balancing*` 下（如 `numa_balancing_scan_delay_ms` / `scan_period_max_ms`），可通过 `set_numabalancing_state()` 整体启停。

## hinting fault 处理：迁移到当前 node

任务访问被标记的页、陷入 fault 后，内核进入 `do_numa_page()` 处理（`mm/memory.c`）。主干逻辑：

```c
target_nid = numa_migrate_check(folio, vmf, vmf->address, &flags,
                                writable, &last_cpupid);
if (target_nid == NUMA_NO_NODE)
    goto out_map;
if (migrate_misplaced_folio_prepare(folio, vma, target_nid)) {
    flags |= TNF_MIGRATE_FAIL;
    goto out_map;
}
/* Migrate to the requested node */
if (!migrate_misplaced_folio(folio, vma, target_nid)) {
    nid = target_nid;
    flags |= TNF_MIGRATED;
    task_numa_fault(last_cpupid, nid, nr_pages, flags);
    return 0;
}
```

三步走：`numa_migrate_check()` 判断"这个页是不是该搬到当前 CPU 所在 node、值不值得搬"；`migrate_misplaced_folio_prepare()` 先把页隔离出来（防止迁移期间被他人改动）；`migrate_misplaced_folio()` 真正把数据复制到目标 node 的新页、再建立映射。值得注意的是**不迁移也要收尾**——`out_map` 路径会把 PTE 恢复为正常可访问（`numa_rebuild_single_mapping`），下次访问就不再陷 fault，避免反复触发。

> 共享页是个特例：多个 node 上的任务都在访问同一块内存时，迁移过去反而可能损害另一个任务，所以扫描阶段就有 `NUMAB_SKIP_SHARED_RO` 等理由直接跳过（见 `enum numa_vmaskip_reason`）。

## 任务放置：task_numa_fault 与评分

页会迁移，任务本身也该被搬到数据所在的 node。每次 hinting fault 处理结束都会调用 `task_numa_fault()`（接口声明在 `include/linux/sched/numa_balancing.h`），把"这个任务在某个 node 上访问了多少页、是否迁移成功"记到任务的统计里：

```c
#define TNF_MIGRATED	0x01
#define TNF_NO_GROUP	0x02
#define TNF_SHARED	0x04
#define TNF_FAULT_LOCAL	0x08
#define TNF_MIGRATE_FAIL 0x10

extern void task_numa_fault(int last_node, int node, int pages, int flags);
```

调度器周期性地用这些统计做 **task placement**：比较任务在各 node 上的"私有页 + 共享页加权"得分，若当前 node 明显劣于某个候选 node，就触发任务迁移（配合任务组的 group 统计，保证线程协同的进程整体靠拢同一个 node）。这样就形成闭环：**页向任务迁移、任务也向页迁移**，双向收敛到局部性最优的位置。是否迁移某块内存的最终判断由 `should_numa_migrate_memory()` 把关。

## mempolicy：用户显式指定放置策略

AutoNUMA 是"内核猜"，但数据库等 workload 往往更清楚自己的访问模式，于是允许用户用 **mempolicy**（内存策略）显式指定页该落在哪些 node。策略模式定义在 `include/uapi/linux/mempolicy.h`：

| 模式 | 语义 |
| --- | --- |
| `MPOL_DEFAULT` | 回退到继承（默认本地分配） |
| `MPOL_PREFERRED` | 优先从指定 node 分配，失败再 fallback |
| `MPOL_BIND` | 严格限定只能在给定 node 集合分配 |
| `MPOL_INTERLEAVE` | 在多个 node 间轮询交错分配，打散热点 |
| `MPOL_LOCAL` | 强制本地分配 |
| `MPOL_PREFERRED_MANY` | 优先多个 node（6.x） |
| `MPOL_WEIGHTED_INTERLEAVE` | 按权重交错（6.x，面向性能不对称的 node） |

策略有三个作用层级：**进程默认**（`set_mempolicy`）、**单段 VMA**（`mbind`，`VMA` 上挂 `vm_policy`）、**单次分配**（`alloc_pages` 的 `MPOL_F_ADDR` 查 VMA 策略）。`mbind` 还能带 `MPOL_MF_MOVE` / `MPOL_MF_MOVE_ALL` 标志，把**已经分配**的页也迁到新策略指定的 node。带 `MPOL_F_NUMA_BALANCING` 的策略则表示"允许内核再用 AutoNUMA 优化"，是显式策略与自动平衡的衔接点。

## 分配时的取舍：zonelist fallback 与 zone_reclaim_mode

当首选 node 空闲不足，分配有两条路：一是沿 **zonelist** 向后 fallback 到其他 node（拿到的就是远端内存）；二是先在**本地 node 回收**出一些页再分配。这个选择由 `zone_reclaim_mode` 控制。

- `zone_reclaim_mode = 0`（多数现代发行版默认）：本地不足就**直接用远端内存**，避免为了局部性去触发回收。
- `zone_reclaim_mode != 0`：先尝试在本地 node 回收（可叠加是否回收匿名页/拷贝页的位），可能让进程陷入 direct reclaim。

这个旋钮是经典的事故来源：[Reclaim](/docs/CS/OS/Linux/mm/Reclaim.md) 和 [PageCache](/docs/CS/OS/Linux/mm/PageCache.md) 都记录过——系统还有近一半 free 内存，却因为开启了它而频繁 direct reclaim、业务抖动。教训是：**在内存充裕的机器上，"用一点远端内存"几乎总是比"卡在本地回收"划算**，没有明确的延迟敏感性证据不要开启。

## 回收侧的 demote 与 promote

NUMA 还重塑了回收的去向。分层内存（如配了慢速但大容量的持久内存 node）上，回收冷页不必直接丢弃或写 swap，可以 **demote**（降级）到更便宜的下层 node，再次访问时再 **promote**（提升）回快速 node。这与 `MPOL_WEIGHTED_INTERLEAVE` 面向异构 node 的思路一致，是冷热分层在 NUMA 维度的延伸。

## 调优与观察

| 接口 / 指标 | 用途 |
| --- | --- |
| `/proc/sys/kernel/numa_balancing` | 0/1 全局启停 AutoNUMA |
| `/proc/sys/kernel/numa_balancing_scan_*` | 扫描延迟、周期、每批内存大小 |
| `numactl --hardview` / `numastat` | 查看 node 拓扑与各进程的本地/远端命中 |
| `/proc/<pid>/numa_maps` | 查看各 VMA 的策略与页分布 |
| `vmstat` 的 `numa_hint_faults` / `numa_pages_migrated` | hinting fault 与迁移计数 |

排障口径：若 `numa_hint_faults` 与 `numa_hint_faults_local` 差距大，说明大量访问被判定为远端、迁移频繁，可能是任务跨 node 漂移或策略设置不当；迁移本身有复制开销，抖动型负载下有时反而要关掉 AutoNUMA。

## Links

- [内存管理知识地图](/docs/CS/OS/Linux/mm/README.md)
- [虚拟内存](/docs/CS/OS/Linux/mm/vm.md)

## References

1. [NUMA Memory Policy — kernel.org documentation](https://www.kernel.org/doc/html/latest/mm/numa_memory_policy.html)
2. [NUMA balancing — kernel.org documentation](https://www.kernel.org/doc/html/latest/admin-guide/sysctl/kernel.html)
3. [Automatic NUMA Balancing — lwn.net](https://lwn.net/Articles/507038/)
