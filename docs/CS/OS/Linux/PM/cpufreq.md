## Introduction

cpufreq 管的是**"CPU 有活干时跑多快"**。与 [cpuidle](/docs/CS/OS/Linux/PM/cpuidle.md) 相反 —— cpuidle 在没事做时省电，cpufreq 在有事做时省电，而后者是**系统功耗的大头**（动态功耗 $\propto C V^2 f$）。

它的核心命题是一个权衡：**性能与功耗不是线性关系**。降频省电但降性能，且降得越多每单位性能省得越少（$V^2$ 关系）—— 所以最优频率既不是最高也不是最低，而是一个由工作负载决定的点。governor 的职责就是估算这个点。

版本基线 **v7.2**。⚠️ **本篇开头就有一处重要重构**：v7.2 的 `struct cpufreq_driver` 与旧资料差异很大，`set_freq` / `correct_target` 已消失，取而代之的是 `setpolicy` / `fast_switch` / `adjust_perf`。

## 结构：policy 才是主角

理解 cpufreq 的关键是把 **policy**（策略）放在第一位，而不是"某个 CPU 的频率"。

```c
struct cpufreq_policy {
	/* CPUs sharing clock, require sw coordination */
	cpumask_var_t		cpus;	/* Online CPUs only */
	cpumask_var_t		related_cpus; /* Online + Offline CPUs */
	cpumask_var_t		real_cpus; /* Related and present */

	unsigned int		shared_type; /* ACPI: ANY or ALL affected CPUs
						should set cpufreq */
	unsigned int		cpu;    /* cpu managing this policy, must be online */

	struct clk		*clk;
	struct cpufreq_cpuinfo	cpuinfo;/* see above */

	unsigned int		min;    /* in kHz */
	unsigned int		max;    /* in kHz */
	unsigned int		cur;    /* in kHz, only needed if cpufreq
					 * governors are used */
	unsigned int		suspend_freq; /* freq to set during suspend */
	...
	/* CPUs sharing clock, require sw coordination */
	...
	bool			fast_switch_possible;
	bool			fast_switch_enabled;
	bool			strict_target;
	bool			efficiencies_available;
```

**一个 policy 可以管多个 CPU**：注释 `/* CPUs sharing clock, require sw coordination */` 说明了原因 —— 共享同一时钟的 CPU 不能各自调频，必须软件协调。所以 cpufreq 的"当前频率"是 **policy 级**的，不是 per-CPU 的。

三个 cpumask 的分工：

| 字段 | 含义 | 用途 |
| :-- | :-- | :-- |
| `cpus` | 在线 CPU | 遍历当前活跃成员 |
| `related_cpus` | 在线 + 离线 | 拓扑相关（含 SMT 兄弟、共享时钟域） |
| `real_cpus` | 相关且实际存在 | 热插拔时区分"拔掉了"与"不存在" |

> ⚠️ **v7.2 的变化**：`struct cpufreq_policy` **没有** `jiffies` / `policy_cpu` / `rcu` / `arch_hook` / `target_freq` 字段。`cpu` 字段的注释说明它现在专指"管理该 policy 的那个 CPU，必须在线"。

### 三个标志位的含义

```c
	/*
	 * Fast switch flags:
	 * - fast_switch_possible should be set by the driver if it can
	 * guarantee that frequency can be changed on any CPU sharing the
	 * policy and that the change will affect all of the policy CPUs then.
	 * - fast_switch_enabled is to be set by governors that support fast
	 * frequency switching with the help of cpufreq_enable_fast_switch().
	 */
	bool			fast_switch_possible;
	bool			fast_switch_enabled;
```

- `fast_switch_possible` —— 驱动声明"我能改任意一个 policy CPU 的频率，且会影响全组"。**硬件直写寄存器**（如 x86 的 MSR/Intel_pstate）才有这个能力。
- `fast_switch_enabled` —— governor 声明"我支持免通知的快速切换"。
- `strict_target` —— 对应 governor 设置了 `CPUFREQ_GOV_STRICT_TARGET`。
- `efficiencies_available` —— 频率表里有"不高效"的频率点。注释说明了它的实际后果：**"This indicates if the relation flag CPUFREQ_RELATION_E can be honored"** —— 关系标记 `E` 能否被兑现。

### 频率约束：三个 freq_qos

```c
	struct freq_constraints	constraints;
	struct freq_qos_request	min_freq_req;
	struct freq_qos_request	max_freq_req;
	struct freq_qos_request	boost_freq_req;
```

`min` / `max` 由 PM QoS 的频率约束部分维护 —— **用户态写 `scaling_min_freq` 走的就是这条路**。`boost_freq_req` 是 boost 的独立通道。

## 驱动接口：v7.2 的重构

```c
struct cpufreq_driver {
	char		name[CPUFREQ_NAME_LEN];
	u16		flags;
	void		*driver_data;

	/* needed by all drivers */
	int		(*init)(struct cpufreq_policy *policy);
	int		(*verify)(struct cpufreq_policy_data *policy);

	/* define one out of two */
	int		(*setpolicy)(struct cpufreq_policy *policy);

	int		(*target)(struct cpufreq_policy *policy,
				  unsigned int target_freq,
				  unsigned int relation);	/* Deprecated */
	int		(*target_index)(struct cpufreq_policy *policy,
					unsigned int index);
	unsigned int	(*fast_switch)(struct cpufreq_policy *policy,
				       unsigned int target_freq);
	/*
	 * ->fast_switch() replacement for drivers that use an internal
	 * representation of performance levels and can pass hints other than
	 * the target performance level to the hardware. This can only be set
	 * if ->fast_switch is set too, because in those cases (under specific
	 * conditions) scale invariance can be disabled, which causes the
	 * schedutil governor to fall back to the latter.
	 */
	void		(*adjust_perf)(struct cpufreq_policy *policy,
				       unsigned long min_perf,
				       unsigned long target_perf,
				       unsigned long capacity);
	...
	/* should be defined, if possible, return 0 on error */
	unsigned int	(*get)(unsigned int cpu);

	/* Called to update policy limits on firmware notifications. */
	void		(*update_limits)(struct cpufreq_policy *policy);

	/* optional */
	int		(*bios_limit)(int cpu, unsigned int *limit);

	int		(*online)(struct cpufreq_policy *policy);
	int		(*offline)(struct cpufreq_policy *policy);
	void		(*exit)(struct cpufreq_policy *policy);
	int		(*suspend)(struct cpufreq_policy *policy);
	int		(*resume)(struct cpufreq_policy *policy);

	/* Will be called after the driver is fully initialized */
	void		(*ready)(struct cpufreq_policy *policy);

	struct freq_attr **attr;

	/* platform specific boost support code */
	bool		boost_enabled;
	int		(*set_boost)(struct cpufreq_policy *policy, int state);

	/*
	 * Set by drivers that want to register with the energy model after the
	 * policy is properly initialized, but before the governor is started.
	 */
	void		(*register_em)(struct cpufreq_policy *policy);
};
```

### 值得注意的几点

**① `name` 是定长数组，不是函数指针**

```c
	char		name[CPUFREQ_NAME_LEN];
```

旧资料里 `name` 是 `unsigned int (*name)(void)`（返回策略名）。**v7.2 改成了字符串**。这个变化波及所有读 policy 名的代码。

**② `setpolicy` 与 `target` 是二选一**

```c
	/* define one out of two */
	int		(*setpolicy)(struct cpufreq_policy *policy);

	int		(*target)(struct cpufreq_policy *policy,
				  unsigned int target_freq,
				  unsigned int relation);	/* Deprecated */
```

`setpolicy` 让**驱动自己决定频率**（策略驱动模式，如 Intel_pstate、AMD P-state），`target` 是传统模式（内核算出目标频率，驱动去设）。**`target` 已标注 Deprecated**。

**③ `adjust_perf` 是 `fast_switch` 的替代品**

注释写得很关键：

```c
	/*
	 * ->fast_switch() replacement for drivers that use an internal
	 * representation of performance levels and can pass hints other than
	 * the target performance level to the hardware. This can only be set
	 * if ->fast_switch is set too, because in those cases (under specific
	 * conditions) scale invariance can be disabled, which causes the
	 * schedutil governor to fall back to the latter.
	 */
```

新式驱动用**性能等级（perf level）**而不是频率作内部表示，可以把 min / target / **capacity** 三个提示一起传给硬件 —— 硬件据此自行选档。这是"scale invariance"（比例不变性）机制：同一 util 在不同频率下应得到相同性能。

> **没有 `correct_target`**：旧驱动用 `correct_target()` 修正内核算出的目标频率，v7.2 里该回调已删除。

**④ `register_em`：接入 energy model 的时机**

```c
	/*
	 * Set by drivers that want to register with the energy model after the
	 * policy is properly initialized, but before the governor is started.
	 */
	void		(*register_em)(struct cpufreq_policy *policy);
```

时机要求很精确：**policy 初始化完成后、governor 启动前**。energy model 需要 policy 的频率表和 OPP 数据来建立"性能 ↔ 功耗"曲线，governor 依赖它做决策 —— 顺序反了就拿不到。

## 频率表

```c
struct cpufreq_frequency_table {
	unsigned int cpu;
	unsigned int freq;
	...
};
```

查找函数按表的排序方式分派：

```c
	if (policy->freq_table_sorted == CPUFREQ_TABLE_SORTED_ASCENDING)
		return cpufreq_table_find_index_al(policy, target_freq, relation);
	else
		return cpufreq_table_find_index_dl(policy, target_freq, relation);
```

（`al` = ascending linear，`dl` = descending linear。）

`relation` 参数取 `CPUFREQ_RELATION_L` / `E` / `G`（大于/小于/最近）—— 但前面 `efficiencies_available` 那个标志说了，**`E` 不一定能兑现**。

**调频请求的解析**走 `cpufreq_driver_resolve_freq()` → `__resolve_freq()`，它先钳位再查表：

```c
	target_freq = clamp_val(target_freq, min, max);
	...
	idx = cpufreq_frequency_table_target(policy, target_freq, min, max, relation);
```

## governor 清单

`drivers/cpufreq/Makefile` 里的完整列表（v7.2 governor 全部平铺在该目录，**没有 `governors/` 子目录**）：

| 文件 | governor | 类型 |
| :-- | :-- | :-- |
| `cpufreq_performance.o` | performance | 恒最高频 |
| `cpufreq_powersave.o` | powersave | 恒最低频 |
| `cpufreq_userspace.o` | userspace | 用户直接写 |
| `cpufreq_ondemand.o` | ondemand | 按 util 突增提频 |
| `cpufreq_conservative.o` | conservative | 按 util 渐增提频 |
| `cpufreq_governor.o` | — | **公共层**（抽象出 `sugov_*` 框架） |
| `cpufreq_governor_attr_set.o` | — | 通用属性导出层 |

**schedutil 不在此列表** —— 它已搬到 `kernel/sched/cpufreq_schedutil.c`（950 行），因为它需要与调度器共享 util 数据结构。

另有两个非 governor 的平台实现：`cpufreq-dt.o`（设备树）、`virtual-cpufreq.o`（虚拟 CPU）。

### ondemand 与 conservative 的差别

两者的区别只在**升频策略**：ondemand 一次性跳到最高，`conservative` 每次只加一档。前者响应快但功耗尖峰明显，后者平缓。

`userspace` 是最简单也最可控的 —— 完全由用户态决定，写 `scaling_cur_freq` 直接生效，不看负载。固定频率跑的机器（高频游戏、视频转码、某些延迟敏感服务）常用它避开调频抖动。

## schedutil：与调度器直接对话

schedutil 是现代内核的默认 governor。它的特殊之处在于**不自己算 util，而是直接向调度器要**。

### 取 util 的路径

```c
static void sugov_get_util(struct sugov_cpu *sg_cpu, unsigned long boost)
{
	unsigned long min, max, util = scx_cpuperf_target(sg_cpu->cpu);

	if (!scx_switched_all())
		util += cpu_util_cfs_boost(sg_cpu->cpu);
	util = effective_cpu_util(sg_cpu->cpu, util, &min, &max);
	util = max(util, boost);
	sg_cpu->bw_min = min;
	sg_cpu->util = sugov_effective_cpu_perf(sg_cpu->cpu, util, min, max);
}
```

三层叠加：

1. **基线**：`scx_cpuperf_target()` —— **sched_ext（BPF 调度器）设置的 per-CPU 性能需求**。这是 v7.x 的新能力：BPF 调度器能直接告诉 cpufreq "我需要多少性能"。
2. **boost**：`cpu_util_cfs_boost()` —— fair 调度器记录的 boost（I/O 等待唤醒等场景）。
3. **钳制**：`effective_cpu_util()` 施加 min/max 约束（来自 cgroup 的 `cpu.min`/`cpu.max`、PM QoS）。

`scx_switched_all()` 是个状态判断 —— **如果系统全面切到 sched_ext，就不再叠加 fair 的 boost**（两者语义会冲突）。

### 算目标频率

```c
static unsigned int get_next_freq(struct sugov_policy *sg_policy,
				  unsigned long util, unsigned long max)
{
	struct cpufreq_policy *policy = sg_policy->policy;
	unsigned int freq;

	freq = get_capacity_ref_freq(policy);
	freq = map_util_freq(util, freq, max);

	if (freq == sg_policy->cached_raw_freq && !sg_policy->need_freq_update)
		return sg_policy->next_freq;

	sg_policy->cached_raw_freq = freq;
	return cpufreq_driver_resolve_freq(policy, freq);
}
```

`map_util_freq(util, ref_freq, max)` 就是那个"性能与频率不是线性"的映射 —— **util 映射到频率不是线性的**（因为 $V^2$ 关系），所以不能用 `util * max / 1024` 这种简单算法。

`get_capacity_ref_freq()` 拿到的是"容量参考频率"，在支持 scale invariance 的平台上，参考频率对应的 util 比例对所有频率都成立 —— 这是上面 `adjust_perf` 注释里提到的机制。

### 一个优化：缓存

```c
	if (freq == sg_policy->cached_raw_freq && !sg_policy->need_freq_update)
		return sg_policy->next_freq;
```

util 没变就复用上次结果，**不重新查频率表**。调频本身有代价（可能触发电压切换），所以避免无谓的重新解析很重要。

### IO boost 的特殊处理

```c
/**
 * sugov_iowait_reset() - Reset the IO boost status of a CPU.
 ...
 * The IO wait boost of a task is disabled after a tick since the last update
 * of a CPU. If a new IO wait boost is requested after more then a tick, then
 * we enable the boost starting from IOWAIT_BOOST_MIN, which improves energy
 * efficiency by ignoring sporadic wakeups from IO.
 */
```

**I/O boost 的衰减机制**：I/O 唤醒的 boost 只保留一个 tick；隔超过一个 tick 才有新 boost 请求时，**从 `IOWAIT_BOOST_MIN` 起步而不是全量**。注释说明了理由 —— "ignoring sporadic wakeups from IO"，避免被零星的 I/O 唤醒推高频率，浪费能量。

## 与 cgroup 的交互

`cpu.max` 的限流与 cpufreq 的关系是双向的：

1. **限流导致 throttle 时不该提频** —— 已经用掉配额了，提到最高也没用。schedutil 通过 `sg_cpu->bw_min` 感知带宽约束。
2. **uclamp 约束** —— cgroup 的 `cpu.uclamp.min` / `cpu.uclamp.max` 直接钳制 util 范围（`effective_cpu_util()` 里的 min/max）。
3. **weight 影响分布** —— cgroup 的 `cpu.weight` 决定各组 vruntime 比例，间接决定各组 util 高低，从而影响各组实际频率。

详见 [cgroup 控制器接口](/docs/CS/OS/Linux/cgroup/controllers.md) 的 cpu 控制器一节。

## 与 suspend 的交互

policy 里有专门的 suspend 频率：

```c
	unsigned int		suspend_freq; /* freq to set during suspend */
```

`->suspend()` / `->resume()` 回调负责在睡眠前切到固定频率、睡眠后恢复 —— 因为睡眠期间不能动态调频。详见 [suspend](/docs/CS/OS/Linux/PM/suspend.md)。

`->bios_limit()` 则是让 BIOS 报告的功率上限生效（thermal 限制导致的降频）。

## sysfs 接口

```
/sys/devices/system/cpu/cpu0/cpufreq/
├── scaling_governor          # 当前 governor，可写切换
├── scaling_cur_freq           # 当前频率（只读，快）
├── scaling_min_freq           # 允许的最低频率，可写
├── scaling_max_freq           # 允许的最高频率，可写
├── scaling_available_frequencies   # 频率表全档
├── cpuinfo_min_freq / cpuinfo_max_freq
├── cpuinfo_transition_latency       # 切换延迟（ns）
├── affected_cpus                    # 受本 policy 影响的 CPU
├── related_cpus                     # policy 内全部 CPU
├── driver / driver_version
└── stats/                           # CONFIG_CPU_FREQ_STAT
    ├── time_in_state
    ├── trans_table
    └── total_trans
```

> ⚠️ **v7.2 的变化**：旧的 `cpuinfo_*` 与 `scaling_*` 分离已经不存在，`cpuinfo_transition_latency` 也没有。`trans_stat` 文件被 **`time_in_state` + `trans_table`** 取代。

读频率的两个接口有区别：`scaling_cur_freq` 是快路径（可能滞后），需要准确值时读 `cpuinfo_cur_freq`。

## 与其它子系统的接缝

- **调度器**：schedutil 直接取 util，见 [fair](/docs/CS/OS/Linux/proc/fair.md)；sched_ext 侧的 per-CPU 性能需求见 [sched_ext](/docs/CS/OS/Linux/proc/sched_ext.md)。
- **cgroup**：见 [cgroup 控制器接口](/docs/CS/OS/Linux/cgroup/controllers.md)。
- **cpuidle**：省电的两端，见 [cpuidle](/docs/CS/OS/Linux/PM/cpuidle.md)。
- **thermal**：过温时通过 `bios_limit` 或 thermal governor 强制降频，见 [PM 知识地图](/docs/CS/OS/Linux/PM/README.md)。
- **suspend**：睡眠前切固定频率，见 [suspend](/docs/CS/OS/Linux/PM/suspend.md)。
- **时钟框架**：`policy->clk` 由 CCF 管理，频率设置最终落到 clk 上，见 [dev 总线族](/docs/CS/OS/Linux/dev/bus.md)。

## 排障速查

```shell
# 当前状态
cat /sys/devices/system/cpu/cpufreq/policy*/scaling_governor
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq
cat /sys/devices/system/cpu/cpufreq/boost          # boost 剩余比例

# 频率表与延迟
cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_available_frequencies
cat /sys/devices/system/cpu/cpu0/cpufreq/cpuinfo_transition_latency

# 固定频率（禁用调频抖动）
echo performance | tee /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor
echo <freq_khz>   | tee /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq   # 需先切 userspace
echo userspace    | tee /sys/devices/system/cpu/cpu0/cpufreq/scaling_governor

# 统计：看实际落在哪些频率
cat /sys/devices/system/cpu/cpufreq/stats/time_in_state
cat /sys/devices/system/cpu/cpufreq/stats/total_trans
# 频率抖动排查：切换次数是否异常高

# policy 关系
cat /sys/devices/system/cpu/cpu0/cpufreq/related_cpus
ls /sys/devices/system/cpu/cpufreq/            # policy 数量

# 确认 schedutil 在用
cat /sys/devices/system/cpu/cpufreq/policy*/scaling_governor | grep -i schedutil
```

## Links

- [电源管理知识地图](/docs/CS/OS/Linux/PM/README.md)
- [cpuidle 空闲挂起](/docs/CS/OS/Linux/PM/cpuidle.md)
- [suspend 整机睡眠](/docs/CS/OS/Linux/PM/suspend.md)
- [进程调度 fair](/docs/CS/OS/Linux/proc/fair.md)
- [sched_ext](/docs/CS/OS/Linux/proc/sched_ext.md)
- [cgroup 控制器接口](/docs/CS/OS/Linux/cgroup/controllers.md)
- [dev 总线族（clk）](/docs/CS/OS/Linux/dev/bus.md)

## References

1. [Linux Kernel Documentation — CPU Frequency Scaling](https://docs.kernel.org/admin-guide/pm/cpufreq.html)
2. [Linux Kernel Documentation — cpufreq energy model](https://docs.kernel.org/power/cpufreq-energy-model.html)
3. [Linux Kernel Documentation — PM QoS Interface](https://docs.kernel.org/power/pm_qos_interface.html)
4. [Documentation/admin-guide/pm/intel_pstate.rst](https://docs.kernel.org/arch/x86/pm/intel_pstate.html)
