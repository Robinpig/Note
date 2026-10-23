# PSI

## Introduction

PSI（Pressure Stall Information，压力失速信息）记录的是**资源已经稀缺到任务开始排队等待**的那段时间，而不是传统的"利用率"。它的核心洞察是：一个 CPU 跑满 100% 不代表系统卡（可能正是你想要的批处理），但"有任务因为等内存回收而**无法运行**"才是真正的失速信号。

PSI 对每个资源（CPU / 内存 / IO，以及可选的 IRQ）分别统计两种停顿：

- **some**：至少有一个任务因等待该资源而被阻塞。
- **full**：该资源上**所有非空闲任务**都被同一资源阻塞（即 CPU 完全被这种失速占满，没有有产出的任务在跑）。

`full` 比 `some` 更危险——它意味着系统在这个维度上"名义上在线、实际上什么都干不了"。对排障而言，PSI 比看 `free` 内存更灵敏：内存可能看着还有，但分配早已卡在 direct reclaim 里，此时 `memory PSI` 早已飙升。

## Recording Mechanism

### Data Structures

类型集中在 `include/linux/psi_types.h`（注意不是 `psi.h`，`psi.h` 只放外部接口声明；调度器侧的包裹函数在 `kernel/sched/stats.h`）：

- `struct psi_group`（`psi_types.h:160`）：系统级与每个 cgroup 各持一个。关键字段 `pcpu`（`psi_group_cpu __percpu *`，per-CPU 采样状态）、`avg[][3]`（10/60/300s 的 EWMA）、`total[][]`（累计 stall 纳秒）。系统级实例为全局 `psi_system`（`psi.c:175`）。
- `struct psi_group_cpu`（`psi_types.h:84`）：每 CPU 的采样桶，持有 `tasks[NR_PSI_TASK_COUNTS]`（任务计数数组）、`state_mask`、`times[NR_PSI_STATES]`、`state_start`。

注意计数**不是** `nr_running` / `nr_memstall` 这类命名字段，而是一个数组 `groupc->tasks[]`，索引为 `enum psi_task_count`（`psi_types.h:14`）：`NR_IOWAIT=0`、`NR_MEMSTALL=1`、`NR_RUNNING=2`、`NR_MEMSTALL_RUNNING=3`。`NR_MEMSTALL_RUNNING` 的引入是为了区分"正在做内存回收的 task（无产出）"与"正常 running 的 task"，这是 `full` 判定准确性的关键。

### Scheduler Trigger Points

PSI 由调度器在任务状态变迁时驱动。v7.2.7 里 `kernel/sched/core.c` 不再直接调 `psi_task_change`，而是经一组包裹函数（定义于 `kernel/sched/stats.h`，内部再调 `psi_task_change` / `psi_task_switch`）：

- `psi_enqueue()`（`stats.h:123`）→ `core.c:2197` 的 enqueue 路径
- `psi_dequeue()`（`stats.h:162`）→ `core.c:2220`
- `psi_ttwu_dequeue()`（`stats.h:192`）→ `core.c:4418` 的 try_to_wake_up 迁移
- `psi_sched_switch()`（`stats.h:211`）→ `core.c:7267` 的上下文切换

真实定义 `psi_task_change()`（`psi.c:909`）、`psi_task_switch()`（`psi.c:926`）。

### Memory Stall Sources

内存维度的失速由一对标记 `psi_memstall_enter()`（`psi.c:1056`）/ `psi_memstall_leave()`（`psi.c:1087`）包裹。内核对下列**阻塞路径**调用它（文件:行号经本地树核实）：

- `mm/page_alloc.c:4482` — `__alloc_pages_direct_reclaim()`，**direct reclaim** 阻塞（注释明确 "The really slow allocator path where we enter direct reclaim"）
- `mm/page_alloc.c:4177` — `__alloc_pages_direct_compact()`，**同步 compaction** 阻塞
- `mm/vmscan.c:7074` — `balance_pgdat()`，**kswapd 后台回收**也标记 memstall（注意语义见下）
- `mm/vmscan.c:7744` — `__node_reclaim()`，节点本地回收
- `mm/compaction.c:3222` — 同步 compaction 路径
- `mm/page_io.c:680` — `swap_read_folio()`，**swap 读（refault 等待）** 阻塞，对应 PSI_MEM 而非 PSI_IO

配对的 `psi_memstall_leave` 分别在 `page_alloc.c:4502`、`vmscan.c:7263/7768`、`compaction.c:3224`、`page_io.c:706`。

**kswapd 标记 memstall 的微妙处**：kswapd 本身在 CPU 上跑却代表 stall，因此统计时用 `NR_MEMSTALL_RUNNING` 而非普通 `NR_RUNNING`。只有当"所有 running 任务都是 reclaim-type"时，才计入 `MEM_FULL`——这正解释了为什么要有 `NR_MEMSTALL_RUNNING` 这个独立计数。

## Resource Dimensions

`enum psi_res`（实际写在 `psi_types.h:41`）为：`PSI_IO`、`PSI_MEM`、`PSI_CPU`，在 `CONFIG_IRQ_TIME_ACCOUNTING` 下还多一个 `PSI_IRQ`，结尾是 `NR_PSI_RESOURCES`（不是 `PSI_NRES`）。三种资源共用同一个 `psi_group`，只是 `res` 维度不同。

聚合器的枚举是 `enum psi_aggregators { PSI_AVGS=0, PSI_POLL }`（`psi_types.h:78`，不是独立宏）。`PSI_NONIDLE`（`psi_types.h:68`）仅用于 per-CPU 层面做全局平均加权。所有这些与 `cpuacct` 无关，是 PSI 独立机制。

## User Interface

### /proc/pressure

由 `psi_proc_init()`（`psi.c:1710`）注册，v7.2.7 真实文件：

- `pressure/io`（0666，`psi.c:1714`）、`pressure/memory`（`:1715`）、`pressure/cpu`（`:1716`）
- `pressure/irq`（`:1718`，仅 `CONFIG_IRQ_TIME_ACCOUNTING`）

读取经 `psi_show()`（`psi.c:1251`）输出 `some` 与 `full` 两块，格式：

```
some avg10=0.00 avg60=0.00 avg300=0.00 total=0
full avg10=0.00 avg60=0.00 avg300=0.00 total=0
```

例外：系统级 `cpu` 文件的 `full` 块被抑制（`psi.c:1283` 注释 "CPU FULL is undefined at the system level"），只有 `some`。写权限（0666）用于注册 poll trigger，不改统计值。

### cgroup v2: memory.pressure

`kernel/cgroup/cgroup.c` 注册了 `io.pressure`（`:5552`）、`memory.pressure`（`:5560`）、`cpu.pressure`（`:5568`）、`irq.pressure`（`:5577`），以及根级 `cgroup.pressure`（`:5586`）。每个都有 `.seq_show`（读统计）**与 `.write`**（注册 trigger）。

**重要**：`memory.pressure` 确实带 `.write`（`cgroup.c:5563`），即接口是 **rw**——但"写"仅用于设置 poll trigger，不能改统计值。这与本库 [memcg](/docs/CS/OS/Linux/mm/memcg.md) 第 265 行记为 `rw` 一致。它与 `/proc/pressure/memory` 的关系是**作用域不同**：proc 的是整机聚合（`psi_system`），cgroup 的是该分组内任务的聚合（`cgroup_psi()` 取 `cgrp->psi`）。

## Aggregation: some vs full and EWMA

采样周期由 `#define PSI_FREQ (2*HZ+1) /* 2 sec intervals */`（`psi.c:161`）定义，运行时 `psi_period = jiffies_to_nsecs(PSI_FREQ)`（`psi.c:239`），即默认约 2s。

per-CPU → 全局的聚合：

1. `get_recent_times()`（`psi.c:271`）快照某 CPU 的 `times[]`，对仍活跃的状态补上 `now - state_start`。
2. `collect_percpu_times()`（`psi.c:362`）遍历所有 CPU，**按各 CPU 的 non-idle 时间加权**累加，写 `group->total[PSI_AVGS][s]`（即 `total=` 累计 stall 纳秒）。
3. `calc_avgs()`（`psi.c:342`）用内核标准 EWMA（`EXP_10s/EXP_60s/EXP_300s`）更新 `group->avg[][3]`，得出 `avg10/avg60/avg300`。

**some vs full 的判定**（`test_states()`，`psi.c:243`）是核心难点：

- **SOME**：该资源有任务被阻塞即置位（`tasks[NR_MEMSTALL] → PSI_MEM_SOME`）。
- **FULL**：
  - IO：`!tasks[NR_RUNNING]`（无运行任务即 full，`psi.c:250`）
  - MEM：`tasks[NR_RUNNING] == tasks[NR_MEMSTALL_RUNNING]`（`psi.c:255`）——必须排除正在回收的 task，只有"所有 running 都是 reclaim-type"才算 MEM_FULL。
  - CPU：`tasks[NR_RUNNING] && !oncpu`（`psi.c:262`）。

因此 `full` 不是字面的"所有任务都阻塞"，对内存而言是"**没有有产出的任务在跑**"。

## Coupling with Existing Subsystems

- **与 [内存回收 Reclaim](/docs/CS/OS/Linux/mm/Reclaim.md)**：PSI memory 的升高**直接来自** direct reclaim、同步 compaction、swap 读这些阻塞路径。它是"内存压力已让用户态卡住"的可观测信号，比 `free` 更前置。调优回收策略（如调 `vm.watermark_scale_factor`、开 MGLRU）后，看 `memory PSI` 的 `full/avg300` 是否下降即可验证效果。
- **与 [memcg](/docs/CS/OS/Linux/mm/memcg.md)**：cgroup 的 `memory.pressure` 把压力细化到组，是 K8s 判断 Pod 是否内存受迫的**前置信号**——早于 OOMKilled，能在容器配额将满时预警。
- **与 [MGLRU 多代 LRU](/docs/CS/OS/Linux/mm/MGLRU.md) / [分层内存 Tiered_Memory](/docs/CS/OS/Linux/mm/Tiered_Memory.md)**：PSI 是这些优化机制的**效果观测器**，而非参与者。它本身不驱动回收或迁移，只忠实记录"任务因此卡了多久"。

## Links

- [Linux 内核总览](/docs/CS/OS/Linux/Linux.md)
- [内存回收 Reclaim](/docs/CS/OS/Linux/mm/Reclaim.md)
- [memcg](/docs/CS/OS/Linux/mm/memcg.md)
- [cgroup](/docs/CS/OS/Linux/cgroup.md)
- [DAMON 访问监控](/docs/CS/OS/Linux/mm/DAMON.md) — `damon_reclaim` 用 PSI 反馈自动调配额

## References

1. 本地文档 `<linux-7.2.7>/Documentation/accounting/psi.rst`（已确认存在，权威说明 SOME/FULL 与接口格式）
2. LWN — "Pressure stall information"（Johannes Weiner 概述）：https://lwn.net/Articles/759423/
3. LWN — "Pressure stall information II: the user-space side"：https://lwn.net/Articles/762992/
4. LWN — "PSI: pressure stall information"（最终合并综述）：https://lwn.net/Articles/777164/
