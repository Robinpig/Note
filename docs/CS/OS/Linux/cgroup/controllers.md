## Introduction

上一篇 [cgroup 知识地图](/docs/CS/OS/Linux/cgroup/README.md) 讲了统一层级与 no-internal-process 规则，本文逐个过一遍**控制器暴露给用户的文件与语义**。所有文件名、字段名、默认值都在 **v7.2** 源码核实（注意：不少字段名与旧资料不同，最明显的例子是 `cpu.max.burst` 而不是 `cpu.burst`）。

先说一条贯穿全部控制器的机制：**v7.2 的控制器注册已从动态 API 改为编译期静态表**。

## 控制器如何注册

`cgroup_subsys_register()` / `DEFINE_CGROUP_SUBSYS` 在 v7.2 **都不存在**。取而代之的是 `kernel/cgroup/cgroup.c` 里的一张静态数组：

```c
#define SUBSYS(_x) [_x ## _cgrp_id] = &_x ## _cgrp_subsys,
static struct cgroup_subsys *cgroup_subsys[] = { ... };
```

各控制器在自己的文件末尾直接实例化导出的全局符号：

| 控制器 | 符号 | 文件 |
| :-- | :-- | :-- |
| cpu | `cpu_cgrp_subsys` | `kernel/sched/core.c`（**不是** `kernel/sched/cpu.c`，后者已 404） |
| cpuset | `cpuset_cgrp_subsys` | `kernel/cgroup/cpuset.c` |
| memory | `memory_cgrp_subsys` | `mm/memcontrol.c` |
| pids | `pids_cgrp_subsys` | `kernel/cgroup/pids.c` |
| misc | `misc_cgrp_subsys` | `kernel/cgroup/misc.c` |
| rdma | `rdmacg_subsys` | `kernel/cgroup/rdma.c` |
| dmem | `dmem_cgrp_subsys` | `kernel/cgroup/dmem.c` |

初始化是遍历式的（`cgroup_init_subsys()`，被 `subsys_initcall` 调用），`early_init` 位的控制器会更早初始化。

### CFTYPE 标志：控制文件出现在哪、谁能写

每个 cgroup 目录下的文件由 `struct cftype` 描述，标志位决定它的可见性与权限。**v7.2 的标志名与旧资料出入很大**：

```c
/* cftype->flags */
enum {
	CFTYPE_ONLY_ON_ROOT	= (1 << 0),	/* only create on root cgrp */
	CFTYPE_NOT_ON_ROOT	= (1 << 1),	/* don't create on root cgrp */
	CFTYPE_NS_DELEGATABLE	= (1 << 2),	/* writeable beyond delegation boundaries */

	CFTYPE_NO_PREFIX	= (1 << 3),	/* (DON'T USE FOR NEW FILES) no subsys prefix */
	CFTYPE_WORLD_WRITABLE	= (1 << 4),	/* (DON'T USE FOR NEW FILES) S_IWUGO */
	CFTYPE_DEBUG		= (1 << 5),	/* create when cgroup_debug */

	/* internal flags, do not use outside cgroup core proper */
	__CFTYPE_ONLY_ON_DFL	= (1 << 16),	/* only on default hierarchy */
	__CFTYPE_NOT_ON_DFL	= (1 << 17),	/* not on default hierarchy */
	__CFTYPE_ADDED		= (1 << 18),
};
```

`CFTYPE_ONLY_ON_DFL`（无下划线）这类**旧名在 v7.2 全部不存在**，语义已由前两个标志 + 内部两个 `__CFTYPE_*` 承担。两个带 `DON'T USE` 注释的是历史包袱。

`CFTYPE_NS_DELEGATABLE` 值得单独说：带这个标志的文件**可以跨委派边界写**。容器内大多数 cgroup 文件没这个标志，所以即使文件看起来可写，写下去也会被委派边界拦住。

## cpu 控制器

CPU 控制器的实现藏在调度器核心里（`kernel/sched/core.c`），因为它和 fair 调度器共享记账代码。

### cpu.max：配额与周期

格式是 `<quota> <period>`，quota 写 `max` 表示不限。默认周期由 `default_bw_period_us()` 给出：

```c
/* default period for group bandwidth. default: 0.1s, units: microseconds */
static inline u64 default_bw_period_us(void) { return 100000ULL; }
```

**100000 微秒 = 100 ms**。写 `cpu.max` 时如果只给一个值，period 就取这个默认值。约束常量为 period ∈ [1 ms, 1 s]。

> 旧资料里的 `CFS_QUOTA_PERIOD_US` / `sysctl_cfs_period_us` 在 v7.2 已不存在，只有 `sched_cfs_bandwidth_slice_us`（默认 5000 µs）还在。

### cpu.max.burst：突发额度

**文件真名是 `cpu.max.burst`，不是 `cpu.burst`**（`core.c:10533`）：

```c
			.name = "max.burst",
			.flags = CFTYPE_NOT_ON_ROOT,
			.read_u64 = cpu_burst_read_u64,
			.write_u64 = cpu_burst_write_u64
```

单位是**微秒**。它解决的问题是：`cpu.max` 是长期均值限流，但一个突发请求可能立刻超限被杀；`max.burst` 允许短期超支而不触发 throttling。

### cpu.stat 与 cpu.stat.local

v2 的字段是六个（都在 `cpu_extra_stat_show` 里）：

```
nr_periods      周期数
nr_throttled    被限流的周期数
throttled_usec  累计限流时间（微秒）
nr_bursts       触发的突发数
burst_usec      累计突发时间（微秒）
```

`cpu.stat.local` 只有 `throttled_usec` 一项（统计本节点而非层级合计）。

> ⚠️ **`throttled_time` 不在 v2 的 `cpu.stat` 里** —— 它是 v1 的字段名。`nr_decayed` / `decay_ms` 在 v7.2 也不存在。

### cpu.weight 与 nice 值

```
cpu.weight       1 .. 10000，默认 100
cpu.weight.nice  对应 nice 值，范围与 nice 一致
```

常量在 `include/linux/cgroup.h`：

```c
#define CGROUP_WEIGHT_MIN   1
#define CGROUP_WEIGHT_DFL   100
#define CGROUP_WEIGHT_MAX   10000
```

头文件的注释解释了为什么默认值取 100：**"default value is the logarithmic center of MIN and MAX and allows 100x to be expressed in both directions"** —— 以对数刻度看，100 正好在 1 与 10000 的中间，向两边各能表达 100 倍的差距。写越界返回 `-ERANGE`。

`cpu.weight.nice` 是给不想算权重的人用的：直接写 nice 值（`sched_prio_to_weight[]` 反查）。

### cpu.idle 与 uclamp

v7.2 新增了 `cpu.idle`（`CONFIG_GROUP_SCHED_WEIGHT` 下）、`cpu.uclamp.min` / `cpu.uclamp.max`（`CONFIG_UCLAMP_TASK_GROUP`）。uclamp 是**利用率钳制**——限制这个 cgroup 的调度实体最高能用多少 CPU，从而隔离延迟敏感型负载。

### cpuset：CPU 与 NUMA 绑定

cpuset 是 v2 里唯一支持**在非根 cgroup 上**存在的核心控制器（因为它标记了 `threaded = true`）。v2 的文件全集（`cpuset.c` 的 `dfl_files[]`）：

| 文件 | 可写 | 说明 |
| :-- | :-- | :-- |
| `cpuset.cpus` | ✓ | 本组允许的 CPU（请求值） |
| `cpuset.mems` | ✓ | 本组允许的 NUMA 节点 |
| `cpuset.cpus.effective` | ✗ | 实际生效值（= 请求值 ∩ 父组） |
| `cpuset.mems.effective` | ✗ | 同上 |
| `cpuset.cpus.partition` | ✓ | 根分区类型 |
| `cpuset.cpus.exclusive` | ✓ | 独占的 CPU |
| `cpuset.cpus.exclusive.effective` | ✗ | 实际独占值 |
| `cpuset.cpus.subpartitions` | ✗ | 仅根 cgroup + debug |
| `cpuset.cpus.isolated` | ✗ | 仅根 cgroup |

**请求值与生效值分离**是 v2 的设计要点：写 `cpuset.cpus` 是"我要这些"，实际拿到的是 `effective`。上层 cgroup 收缩时，子 cgroup 的请求值不变但生效值跟着变 —— 所以**永远读 `.effective`**。

#### cpuset.cpus.partition 的四个取值

```c
#define PRS_MEMBER		0	// 非 partition root
#define PRS_ROOT		1	// partition root
#define PRS_ISOLATED		2	// partition root 但不参与负载均衡
#define PRS_INVALID_ROOT	-1
#define PRS_INVALID_ISOLATED	-2
```

写入接受三个字符串：

| 字符串 | 含义 |
| :-- | :-- |
| `root` | 建一个分区根，其子 cpuset 各自独占父的 CPU |
| `isolated` | 同上，但该分区不参与负载均衡（`new_lb = (new_prs != PRS_ISOLATED)`） |
| `member` | 取消分区根身份 |

> ⚠️ 第三态是 **`member`**，不是 `delegated` —— 后者在 v7.2 不存在。

partition 根的强制约束：父必须是有效 partition root，否则返回 `PERR_NOTPART` / `PERR_INVPARENT`；建分区根时**强制置 `CS_CPU_EXCLUSIVE`** 标志，失败返回 `PERR_NOTEXCL`。local partition 与 remote partition 的祖先链规则不同（`update_parent_effective_cpumask()`）。

## memory 控制器

实现是 `mm/memcontrol.c`（6000+ 行），本 KB 有独立的 [memcg](/docs/CS/OS/Linux/mm/memcg.md) 笔记讲回收与记账机制，这里只列接口。

### 文件全集

| 文件 | 读 | 写 | 说明 |
| :-- | :-: | :-: | :-- |
| `memory.current` | ✓ | ✗ | 当前用量 |
| `memory.peak` | ✓ | ✓ | 用量峰值（写入可重置） |
| `memory.min` | ✓ | ✓ | 硬保护下限，回收时不可动用 |
| `memory.low` | ✓ | ✓ | 软保护，优先回收它而非 OOM |
| `memory.high` | ✓ | ✓ | 超过则触发直接回收 + 节流 |
| `memory.max` | ✓ | ✓ | 硬上限，超过触发 OOM |
| `memory.events` | ✓ | ✗ | 各级触发计数 |
| `memory.events.local` | ✓ | ✗ | 本节点计数 |
| `memory.stat` | ✓ | ✗ | 按页类型细分 |
| `memory.numa_stat` | ✓ | ✗ | 按 NUMA 节点细分（需 `CONFIG_NUMA`） |
| `memory.oom.group` | ✓ | ✓ | OOM 时是否整组杀 |
| `memory.reclaim` | ✗ | ✓ | 主动回收 |

swap 与 zswap 子树：

```
memory.swap.current   memory.swap.peak
memory.swap.high      memory.swap.max
memory.swap.events
memory.zswap.current  memory.zswap.max   memory.zswap.writeback
```

**v7.2 的 peak 系列是新增的**：`memory.peak`、`memory.swap.peak`、`pids.peak`、`rdma.peak`、`misc.peak` 都存在，且带 `open`/`release` 钩子（意味着可以写 0 重置峰值）。

### memory.events 的七个字段

```c
	low            MEMCG_LOW
	high           MEMCG_HIGH
	max            MEMCG_MAX
	oom            MEMCG_OOM
	oom_kill       MEMCG_OOM_KILL
	oom_group_kill MEMCG_OOM_GROUP_KILL
	sock_throttled MEMCG_SOCK_THROTTLED
```

前六项是常见认知里的全部，**第七项 `sock_throttled` 是 socket 内存回收限流事件**，容易被漏掉。

### memory.stat 的字段

无条件字段约 40 个，常用分组：

| 类别 | 字段 |
| :-- | :-- |
| 匿名/文件 | `anon` / `file` / `shmem` / `file_mapped` |
| 内核占用 | `kernel` / `kernel_stack` / `pagetables` / `sec_pagetables` / `percpu` / `sock` / `vmalloc` |
| slab | `slab_reclaimable` / `slab_unreclaimable` |
| 活跃度 | `active_anon` / `inactive_anon` / `active_file` / `inactive_file` / `unevictable` |
| 脏页 | `file_dirty` / `file_writeback` |
| workingset | `workingset_refault_anon` / `_file`、`workingset_activate_*`、`workingset_restore_*`、`workingset_nodereclaim` |
| 迁移/回收 | `pgdemote_*` / `pgsteal_*` / `pgscan_*` / `pgrefill`（各 4 个来源 + refill） |

条件编译字段：`swapcached`（`CONFIG_SWAP`）、`anon_thp`/`file_thp`/`shmem_thp`（`CONFIG_TRANSPARENT_HUGEPAGE`）、`hugetlb`（`CONFIG_HUGETLB_PAGE`）、`zswap`/`zswapped`/`zswap_incomp`（`CONFIG_ZSWAP`）、`pgpromote_success`（`CONFIG_NUMA_BALANCING`）。

> **folio 化不影响 `memory.stat` 的 key 名**。key 是硬编码字符串字面量（`"anon"`、`"file"`…），与内核内部 `page`→`folio` 的类型重命名解耦。所以看到 `VM_BUG_ON_FOLIO(...)` 这类新宏不必奇怪 —— 用户可见的接口是稳定的。

### memory.reclaim：主动回收

写一个字符串（**单位是页数**），内核按参数执行主动回收。实现在 `mm/vmscan.c` 的 `user_proactive_reclaim()`。

第一个字段是回收目标页数，之后可选 key：

```shell
echo "1024" > memory.reclaim                    # 回收 1024 页
echo "1024 swappiness=0" > memory.reclaim        # 只回收页缓存，不换出
echo "1024 swappiness=max" > memory.reclaim      # SWAPPINESS_ANON_ONLY
```

`swappiness` 范围校验用 `MIN_SWAPPINESS..MAX_SWAPPINESS`。memcg 分支的回收选项是 `MEMCG_RECLAIM_MAY_SWAP | MEMCG_RECLAIM_PROACTIVE` —— **默认允许 swap 回收**；要严格避免 swap 就显式写 `swappiness=0`。

还有两个值得知道的细节：它会检查 `signal_pending()` 返回 `-ERESTARTSYS`（freezer 场景下可中断）；循环用 `batch_size = (nr_to_reclaim - nr_reclaimed) / 4` 分批推进，耗尽重试次数后调 `lru_add_drain_all()`。

### memory.oom.group

`0`（默认）表示只杀超出配额的进程；`1` 表示把整个 cgroup 一起杀。写 `1` 时该文件带 `CFTYPE_NS_DELEGATABLE`，可以跨委派边界写。

## pids 控制器

实现极简（`kernel/cgroup/pids.c` 只有 460 行），因为它只做一件事：限制进程/线程数。

```
pids.max              上限，max = 不限
pids.current          当前数
pids.peak             峰值（v7.2 新增）
pids.events           只有一个字段：max
pids.events.local     同上，本节点
```

内部结构用 64 位原子量，注释说明了原因：**"使用 64 位类型以便安全表示 `max`"** —— `max` 的实际值是 `PID_MAX_LIMIT + 1`，超出 32 位。

`pids.events` 只有一个 `max` 字段，记录因超限导致的 fork 失败次数：

```c
	seq_printf(sf, "max %lld\n", (s64)atomic64_read(&events[pe]));
```

**超限时的返回码是 `-EAGAIN`**，文件头注释写得很明确："fork() will return -EAGAIN if forking ... violate a cgroup policy through fork()"。注意与 `pids_css_alloc()` 自身内存分配失败返回的 `-ENOMEM` 区分。

> `pids.events` 在 v1 下打印的 `max` 实际计的是 `PIDCG_FORKFAIL`，而 v2 才是真正的超限次数 —— 这是 v1/v2 语义不一致的一例。

## misc / rdma / dmem 三个小控制器

### misc：主机级稀缺资源配额

v7.2 的资源类型是三项：

```c
static const char *const misc_res_name[] = {
	"sev",		// AMD SEV ASIDs
	"sev_es",	// AMD SEV-ES ASIDs
	"tdx",		// Intel TDX HKIDs
};
```

对应虚拟机加密内存的 ASID（Address Space Identifier）—— 这类资源全机数量有限，是典型的"每个 VM 都要申请、申请多了就开不起来"的场景。

```
misc.capacity   全机总容量（只读，仅根 cgroup）
misc.max        本组上限
misc.current    本组用量
misc.peak       峰值
misc.events / .events.local
```

源码注释里有个重要语义：**"root_cg.max and capacity are independent of each other. root_cg.max can be more than the actual capacity."** —— 你可以把 `misc.max` 设得比 `misc.capacity` 大，不会有任何效果。

`misc.capacity` 标记了 `CFTYPE_ONLY_ON_ROOT`，且**只有 show 没有 write**。

### rdma：RDMA 资源上限

```
rdma.max       上限
rdma.current   用量
rdma.peak      峰值
rdma.events / .events.local
```

> 旧资料里的 `rdma.max_rdma_cm` 在 v7.2 **不存在**。改成了统一的资源框架：同一个 `rdmacg_resource_read` 服务 max/current/peak 三者，靠 `private` 字段区分读哪个（`RDMACG_RESOURCE_TYPE_MAX` / `_STAT` / `_PEAK`）。这是"用一套代码管多个资源维度"的典型写法。

### dmem：设备内存

```
dmem.capacity   总容量（只读，仅根）
dmem.current    用量
dmem.min / dmem.low / dmem.max
```

**`dmem` 没有 `.events`** —— 这是它与其他控制器的显著差异（pids/misc/rdma 都有成对的 events）。`dmem` 主要面向设备内存（DPU/GPU 类场景），由驱动通过 `dmem_cgroup_register_region()` 注册自定义 region。

## freezer 冻结与终止

### cgroup.freeze

写 `1` 冻结，写 `0` 解冻，**其他值返回 `-ERANGE`**。可以读（输出 0 或 1）。

v2 的冻结状态**内建于 `struct cgroup`**（`cgroup->freezer`），不是独立控制器。`struct cgroup_freezer_state` 的关键字段：

```c
	bool freeze;                    // 是否应冻结本组及后代
	bool e_freeze;                  // 是否实际已冻结
	int  nr_frozen_descendants;     // 已冻结后代数
	int  nr_frozen_tasks;           // frozen + SIGSTOPped + PTRACEd
	u64  freeze_start_nsec;
	u64  frozen_nsec;
```

**`freeze`（意图）与 `e_freeze`（实际）分离**是这套设计的要点：父 cgroup 冻结时子代的 `freeze` 仍可为 0，但 `e_freeze` 会是 1。

`cgroup_freeze()` 的传播有优化：子代 `e_freeze` 未变则**整棵子树跳过**（`css_rightmost_descendant()`），这就是大 cgroup 树冻结仍然快的原因。

状态在 `cgroup.events` 里可见：

```c
	seq_printf(seq, "frozen %d\n", test_bit(CGRP_FROZEN, &cgrp->flags));
```

### cgroup.kill

v7.2 已支持，写 **`1` 杀全部后代进程，其他值 `-ERANGE`**。与 freeze 的差异：

| | `cgroup.freeze` | `cgroup.kill` |
| :-- | :-- | :-- |
| 接受值 | `0` / `1` | **仅 `1`** |
| 可读 | 是 | **否**（无 show 回调） |
| 语义 | 冻结（进程保持，可恢复） | 向所有后代 `send_sig(SIGKILL)` |
| threaded cgroup | 允许 | `-EOPNOTSUPP` |
| 内部标记 | `CGRP_FREEZE` / `CGRP_FROZEN` | `kill_seq` |

实现上有一个精巧的机制：写 `cgroup.kill` 并不直接发信号，只做 `cgrp->kill_seq++`；真正的发送发生在进程迁移路径的 `cgroup_can_attach()` 判断里：

```c
	kill = kargs->kill_seq != cgrp_kill_seq;
```

即**用序号比较代替遍历**。好处是"杀整个子树"变成 O(1) 操作 —— 遍历子树里每个任务要 O(n)，而序号只要不一致就顺手在退出/迁移时处理。

threaded cgroup 拒绝 `cgroup.kill` 的理由也写在源码注释里：threaded 模式按**进程组语义**整体终止，与线程级计费模型不兼容。

### v1 的 freezer 为什么不同

v1 的 `kernel/cgroup/legacy_freezer.c` 是独立子系统（`.legacy_cftypes` 有而 `.dfl_cftypes` 没有），状态是**单个位掩码**：

```c
CGROUP_FREEZER_ONLINE     = (1 << 0)
CGROUP_FREEZING_SELF      = (1 << 1)
CGROUP_FREEZING_PARENT    = (1 << 2)
CGROUP_FROZEN             = (1 << 3)
```

接口也是字符串而非整数：`freezer.state` 写 `"FROZEN"` / `"THAWED"`，读出 `"FREEZING"` / `"FROZEN"` / `"THAWED"`。另有只读的 `freezer.self_freezing` / `freezer.parent_freezing`。

**为什么 v1 需要独立子系统而 v2 不需要**：v2 的冻结状态必须被 cgroup **核心**读到 —— `cgroup.events` 的 `frozen` 位、fork/exit 路径的冻结判定都要 `test_bit(CGRP_FREEZE, ...)`。状态必须内建于 `struct cgroup`，藏不进独立控制器的 css 私有数据。v1 没有这个耦合，所以保留独立实现 + `CONFIG_CGROUP_FREEZER` 条件编译。

## PSI：压力 Stall 信息

四个资源（irq 需 `CONFIG_IRQ_TIME_ACCOUNTING`）：

```
cpu.pressure  io.pressure  memory.pressure  irq.pressure
```

每档输出格式：

```
some avg10=0.00 avg60=0.00 avg300=0.00 total=0
full avg10=0.00 avg60=0.00 avg300=0.00 total=0
```

**窗口恰好三个：10 / 60 / 300 秒**（源码里数组维度硬编码为 `avg[NR_PSI_STATES - 1][3]`）。`total` 单位是**微秒**。

`some` 与 `full` 的定义在 `psi_types.h` 的注释里：

```
SOME: Stalled tasks & working tasks
FULL: Stalled tasks & no working tasks
```

即 `full` 更严格 —— 不只是有任务被卡住，而是**卡住的同时没有任何任务在运行**。一个进程在等页、一个进程在跑，`some` 会计而 `full` 不计。

> **系统级 `cpu.pressure` 只有 `some` 档**。源码里有明确注释："CPU FULL is undefined at the system level"。

### PSI 的资源开销

`struct psi_group_cpu` 用了**两条 cacheline 分治**的布局：前一条由调度器侧更新（`tasks[]`、`state_mask`、`times[]`），后一条由聚合器侧更新（`times_prev[][]`）。这个 cacheline 对齐布局是 PSI 内存占用的主要来源 —— 每个 cgroup 都要 `alloc_percpu()` 一份。

压力阈值的校验有个易踩的约束：

```c
	if (threshold_us == 0 || threshold_us > window_us)
		return ERR_PTR(-EINVAL);
```

**阈值必须小于窗口**。另：非特权用户只能用 **2 秒的整数倍**窗口，源码注释说明了原因——"so that averages aggregation work is used, and no RT threads need to be spawned"。窗口上限是 10 秒。

> 旧资料里的 `psi_threshold` 符号与"固定默认值"都不存在，阈值完全由用户态通过 trigger 接口传入。

## v1 独有接口

`kernel/cgroup/cgroup-v1.c` 有一组 v2 完全没有的核心文件：

| 文件 | v1 作用 |
| :-- | :-- |
| `cgroup.clone_children` | 创建子 cpuset 时克隆父的配置 |
| `cgroup.sane_behavior` | 只读，v1 的内存回收是否"理智" |
| `notify_on_release` | cgroup 空了之后通知用户态 |
| `release_agent` | 自定义收尸进程路径 |
| `tasks` | 线程级视图（v2 改名 `cgroup.threads`） |

控制器侧还有 `cpu.shares`（v2 是 `cpu.weight`）、`cpu.rt_period_us` / `cpu.rt_runtime_us`（v2 是 `cpu.max`），以及 `mm/memcontrol-v1.c` 与 `kernel/cgroup/cpuset-v1.c` 两个独立实现。

挂载机制也完全不同：v1 用 `cgroup1_get_tree()` + `cgroup1_parse_param()`，按 mount 参数里的名字（`cpu`、`memory`…）匹配 `ss->legacy_name`。**同一个控制器不能同时在 v1 和 v2 启用** —— 冲突时 `rebind_subsystems()` 返回 `-EBUSY`，但隐式控制器（`implicit_on_dfl`）例外，可以被"抢"到 v2。

## 排障速查

```shell
# 本 cgroup 能用哪些控制器
cat cgroup.controllers
# 已启用于子组（EBUSY 时先看这里和 cgroup.procs）
cat cgroup.subtree_control
cat cgroup.procs | head          # 有进程 = 不能加控制器

# CPU
cat cpu.max                      # "max 100000" = 不限，周期 100ms
cat cpu.max.burst                # 突发额度（微秒），不是 cpu.burst
cat cpu.weight cpu.weight.nice
cat cpu.stat cpu.stat.local      # v2 无 throttled_time

# 内存
cat memory.max memory.high memory.low memory.min
cat memory.current memory.peak
grep -E "^(oom|oom_kill|high|max|low) " memory.events   # 别漏 sock_throttled
cat memory.reclaim; echo "1024 swappiness=0" > memory.reclaim

# cpuset 永远读 effective
cat cpuset.cpus cpuset.cpus.effective cpuset.mems.effective
cat cpuset.cpus.partition        # root / member / isolated

# pids / PSI
cat pids.max pids.current pids.events
cat memory.pressure cpu.pressure

# 冻结与终止
echo 1 > cgroup.freeze; cat cgroup.events | grep frozen
echo 1 > cgroup.kill             # 只接受 1，且 threaded 组不支持
```

## Links

- [cgroup 知识地图](/docs/CS/OS/Linux/cgroup/README.md)
- [cgroup 委派与容器实践](/docs/CS/OS/Linux/cgroup/delegation.md)
- [cgroup memory 控制器 memcg](/docs/CS/OS/Linux/mm/memcg.md)
- [cgroup（旧笔记，v1 视角）](/docs/CS/OS/Linux/cgroup.md)
- [进程调度 fair](/docs/CS/OS/Linux/proc/fair.md)
- [namespace](/docs/CS/OS/Linux/namespace.md)

## References

1. [Linux Kernel Documentation — Control Group v2](https://docs.kernel.org/admin-guide/cgroup-v2.html)
2. [Linux Kernel Documentation — cgroup v1](https://docs.kernel.org/admin-guide/cgroup-v1/index.html)
3. [Linux Kernel Documentation — PSI](https://docs.kernel.org/accounting/psi.html)
