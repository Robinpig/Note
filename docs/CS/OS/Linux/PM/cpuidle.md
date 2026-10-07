## Introduction

cpuidle 管的是**"CPU 没事做的时候能停多久"**。当每个 CPU 上的任务都进入不可调度状态，调度器不会让 CPU 空转（那是 HUZZLE 的活），而是走进 `cpuidle_enter()` 问驱动："现在能省多少电？"

省电的代价是**唤醒延迟**：进得越深，恢复执行要的时间越长。cpuidle 的全部机制就是在"省多少"和"忍多久"之间取平衡。

版本基线 **v7.2**（本文所有函数名与常量均在该版本核实）。

## Differences Between C-state and P-state

| | C-state（cpuidle） | P-state（cpufreq） |
| :-- | :-- | :-- |
| 触发时机 | **没有任务可运行** | **有任务要运行** |
| 省的是 | 静态功耗（漏电） | 动态功耗（$CV^2f$） |
| 档位命名 | C0（运行）、C1/C2/C3… | P0（最高频）、P1… |
| 恢复代价 | 唤醒延迟 | 调频时间 |
| 本文 | 本篇 | [cpufreq](/docs/CS/OS/Linux/PM/cpufreq.md) |

C0 是"运行态"不算空闲态，C1 及以后才是真正的省电档。**功耗构成**上，动态功耗（$C V^2 f$）随频率平方增长、随电压降低而快速下降，所以 C-state 省的是与频率无关的那部分漏电 + 驱动功耗。

## Data Structures

### struct cpuidle_state: A C-state

```c
struct cpuidle_state {
	char		name[CPUIDLE_NAME_LEN];
	char		desc[CPUIDLE_DESC_LEN];

	s64		exit_latency_ns;
	s64		target_residency_ns;
	unsigned int	flags;
	unsigned int	exit_latency; /* in US */
	int		power_usage; /* in mW */
	unsigned int	target_residency; /* in US */

	int (*enter)	(struct cpuidle_device *dev,
			struct cpuidle_driver *drv,
			int index);

	void (*enter_dead) (struct cpuidle_device *dev, int index);
	...
	int (*enter_s2idle)(struct cpuidle_device *dev,
			    struct cpuidle_driver *drv,
			    int index);
};
```

**v7.2 特有的双轨字段**：`exit_latency_ns` / `target_residency_ns`（纳秒）与 `exit_latency` / `target_residency`（微秒）**同时存在**。新代码用 ns 版，老驱动仍可填 us 版。这是 v7.x 正在做的单位统一迁移，遇到不认识的字段时先看有没有 us 后缀的孪生字段。

`enter_s2idle` 的注释说明了它的特殊约束：

```c
	/*
	 * CPUs execute ->enter_s2idle with the local tick or entire timekeeping
	 * suspended, so it must not re-enable interrupts at any point (even
	 * temporarily) or attempt to change states of clock event devices.
	 *
	 * This callback may point to the same function as ->enter if all of
	 * the above requirements are met by it.
	 */
```

s2idle（suspend-to-idle）路径**禁止在回调里重开中断**（哪怕是临时的），因为整机正在用它作为睡眠目标。它可以与 `->enter` 指向同一函数。

### struct cpuidle_driver: A Platform Idle Implementation

```c
struct cpuidle_driver {
	const char		*name;
	struct module 		*owner;

        /* used by the cpuidle framework to setup the broadcast timer */
	unsigned int            bctimer:1;
	/* states array must be ordered in decreasing power consumption */
	struct cpuidle_state	states[CPUIDLE_STATE_MAX];
	int			state_count;
	int			safe_state_index;

	/* the driver handles the cpus in cpumask */
	struct cpumask		*cpumask;

	/* preferred governor to switch at register time */
	const char		*governor;
};
```

两条关键约束写在注释里：

- **`states` 数组必须按功耗递减排序** —— governor 依赖这个顺序做区间搜索，乱序会导致选错档。
- `governor` 是**注册时指定的优先 governor**，cpuidle 框架会用它。

## Selection Workflow

### cpuidle_select: Handing Off to the Governor

```c
int cpuidle_select(struct cpuidle_driver *drv, struct cpuidle_device *dev,
		   bool *stop_tick)
{
	return cpuidle_curr_governor->select(drv, dev, stop_tick);
}
```

框架不自己选档，只**转发给当前 governor**。`stop_tick` 是输出参数 —— governor 通过它告诉框架"进这个档之前要不要停 tick"。

> ⚠️ **v7.2 的重要变化**：旧资料里的 `cpuidle_go_billiard()`（进空闲前的兜底/看门狗逻辑）**已被删除**。取而代之的是 `cpuidle_poll_time()`（`drivers/cpuidle/poll_state.c`），用于 POLL_IDLE 模式。写"进 idle 前先自旋一会等中断"的逻辑现在走 poll_state 而不是 go_billiard。

### cpuidle_enter: Actually Entering the State

```c
int cpuidle_enter(struct cpuidle_driver *drv, struct cpuidle_device *dev,
		  int index)
{
	int ret = 0;

	/*
	 * Store the next hrtimer, which becomes either next tick or the next
	 * timer event, whatever expires first. Additionally, to make this data
	 * useful for consumers outside cpuidle, we rely on that the governor's
	 * ->select() callback have decided, whether to stop the tick or not.
	 */
	WRITE_ONCE(dev->next_hrtimer, tick_nohz_get_next_hrtimer());

	if (cpuidle_state_is_coupled(drv, index))
		ret = cpuidle_enter_state_coupled(dev, drv, index);
	else
		ret = cpuidle_enter_state(dev, drv, index);

	WRITE_ONCE(dev->next_hrtimer, 0);
	return ret;
}
```

**进档前先记下"下一个 hrtimer 到期时间"**，这是 governor 做预测的核心输入。tick 被停时它就是下一个 tick，停不掉时它就是下一个定时器事件 —— 无论哪种，都是"预计多久后会有事发生"。

`cpuidle_state_is_coupled()` 是个分叉：**coupled C-state** 要求一组 CPU（通常是同一物理核的 SMT 兄弟或共享时钟域的核）**同时**空闲才能进入，否则省不了电。`cpuidle_enter_state_coupled()` 会等待同组其他 CPU 也到达空闲。

### Statistics: What the rejected Count Reveals

`cpuidle_enter_state()` 里对每档维护两组计数：

```c
	} else {
		dev->last_residency_ns = 0;
		dev->states_usage[index].rejected++;
	}
```

**`rejected` 增长意味着 governor 选的档太深**（进了但没待够时间就被唤醒，退出成本白付了）。排查"为什么这么费电"时，`/sys/devices/system/cpu/cpuidle/stats` 里的 `rejected` 计数比 `usage` 更有诊断价值：

```shell
grep -E "^(usage|rejected|total)" /sys/devices/system/cpu/cpuidle/stats
```

`rejected` 高 → governor 过于激进，考虑换 `teo` 或调 `target_residency`；`usage` 高但 `rejected` 也高 → C-state 本身不省电（可能是驱动实现问题或芯片特性）。

## menu governor

menu 是最常用的 governor（也是其他 governor 的参考实现）。它的算法头部注释写得非常清楚：

```c
/*
 * Concepts and ideas behind the menu governor
 *
 * For the menu governor, there are 2 decision factors for picking a C
 * state:
 * 1) Energy break even point
 * 2) Latency tolerance (from pmqos infrastructure)
 * These two factors are treated independently.
 */
```

**两个决策因素相互独立**：

### Factor One: Energy Break-even Point

```c
 * C state entry and exit have an energy cost, and a certain amount of time in
 * the  C state is required to actually break even on this cost. CPUIDLE
 * provides us this duration in the "target_residency" field. So all that we
 * need is a good prediction of how long we'll be idle.
```

进出 C-state 本身耗电，只有在状态里待够 `target_residency` 才划算。所以问题归结为**预测空闲时长**。

menu 用下一个定时器事件做预测，但知道这偏乐观（中断随时会来），于是用**修正因子**补偿：

```c
 * Since there are other source of wakeups (interrupts for example) than
 * the next timer event, this estimation is rather optimistic. To get a
 * more realistic estimate, a correction factor is applied to the estimate,
 * that is based on historic behavior. For example, if in the past the actual
 * duration always was 50% of the next timer tick, the correction factor will
 * be 0.5.
```

**关键设计：修正因子不是一个标量，而是一组按数量级分桶的因子**：

```c
 * menu uses a running average for this correction factor, but it uses a set of
 * factors, not just a single factor. This stems from the realization that the
 * ratio is dependent on the order of magnitude of the expected duration; if we
 * expect 500 milliseconds of idle time the likelihood of getting an interrupt
 * very early is much higher than if we expect 50 micro seconds of idle time.
 * For this reason, menu keeps an array of 6 independent factors, that gets
 * indexed based on the magnitude of the expected duration.
```

```c
#define BUCKETS 6
```

**6 个 bucket 按预期空闲时长的数量级分档** —— 空闲 500 ms 时被提前打断的概率远高于空闲 50 µs 时，所以两者的修正因子必须不同。

per-CPU 状态：

```c
struct menu_device {
	int             needs_update;
	int             tick_wakeup;

	u64		next_timer_ns;
	unsigned int	bucket;
	unsigned int	correction_factor[BUCKETS];
	unsigned int	intervals[INTERVALS];
	int		interval_ptr;
};
```

### Factor Two: Recurrence Interval Detector

```c
 * Repeatable-interval-detector
 * ----------------------------
 * There are some cases where "next timer" is a completely unusable predictor:
 * Those cases where the interval is fixed, for example due to hardware
 * interrupt mitigation, but also due to fixed transfer rate devices like mice.
 * For this, we use a different predictor: We track the duration of the last 8
 * intervals and use them to estimate the duration of the next one.
 */
```

有些场景"下一个定时器"完全不可用：**周期性中断**（比如硬件中断缓解、鼠标的固定速率报告）。这时 menu 改用另一个预测器 —— **跟踪最近 8 个间隔**来估计下一个：

```c
#define INTERVAL_SHIFT 3
#define INTERVALS (1UL << INTERVAL_SHIFT)   /* = 8 */
```

配合的常量还有：

```c
#define RESOLUTION 1024
#define DECAY 8
#define MAX_INTERESTING (50000 * NSEC_PER_USEC)   /* 50 ms */
```

`MAX_INTERESTING` = 50 ms 是"有意义的最大空闲时长"上界 —— 超过这个值的预测精度不值得关注。

### Decision

`menu_select()` 里的选档逻辑分两层：先按修正因子算出 `predicted_ns`（预测的实际空闲时长），再用它去和每档的 `target_residency_ns` 比较：

```c
		if (s->target_residency_ns <= predicted_ns) {
			...
			    s->target_residency_ns < RESIDENCY_THRESHOLD_NS &&
			    s->target_residency_ns <= data->next_timer_ns &&
			...
			    predicted_ns = s->target_residency_ns;
```

`RESIDENCY_THRESHOLD_NS` 把"浅"档和"深"档分开处理 —— 浅档不受 tick 时长限制，深档需要。它定义在 `drivers/cpuidle/governors/gov.h`（governor 公共头）：

```c
/*
 * Idle state target residency threshold used for deciding whether or not to
 * check the time till the closest expected timer event.
 */
#define RESIDENCY_THRESHOLD_NS	(15 * NSEC_PER_USEC)
```

**15 微秒** 是"是否值得去看下一个定时器"的阈值。同一头文件里还有一个：

```c
/*
 * If the closest timer is in this range, the governor idle state selection need
 * not be adjusted after the scheduler tick has been stopped.
 */
#define SAFE_TIMER_RANGE_NS	(2 * TICK_NSEC)
```

即**最近定时器在 2 个 tick 周期内时，选档结果在停 tick 后不需要重算** —— 省掉停 tick 后的重复决策。

tick 相关的两处判断：

```c
		if (drv->states[idx].target_residency_ns < TICK_NSEC &&
		    s->target_residency_ns <= delta_tick)
		...
		if (idx > 0 && drv->states[idx].target_residency_ns > delta_tick) {
```

**只在目标驻留时间短于一个 tick 时才值得停 tick**（停 tick 有成本，若空闲时长本来就小于 tick 周期，停它不划算）。

> **v7.2 的变化**：menu 只有**单一** `menu_select()` 入口，没有旧资料里的 `menu_get_next_idx()` / `menu_select_state()` 两段式接口。

## Coupling with tick

cpuidle 与 NO_HZ tickless 的耦合点在 `cpuidle_enter()` 开头：

```c
	WRITE_ONCE(dev->next_hrtimer, tick_nohz_get_next_hrtimer());
```

框架取"下一个 hrtimer"，这个值同时供 governor 预测和 tick 停启决策使用。注释说明了这种共用的用意：

```c
	/*
	 * Store the next hrtimer, which becomes either next tick or the next
	 * timer event, whatever expires first. Additionally, to make this data
	 * useful for consumers outside cpuidle, we rely on that the governor's
	 * ->select() callback have decided, whether to stop the tick or not.
	 */
```

停掉 tick 后由 hrtimer 模拟出 tick，这就是 [timer](/docs/CS/OS/Linux/timer.md) 里 NO_HZ 的 "停掉之后：hrtimer 模拟 tick" 一节。**停 tick 的决策权在 governor 手上**（通过 `stop_tick` 输出参数），不在 cpuidle 框架。

## PM QoS: Constraining C-state Depth

用户态延迟约束通过 PM QoS 进入，governor 读它作为"因素二"。效果是：**有实时任务时，governor 不会选深度 C-state**。

> ⚠️ **v7.2 的变化**：旧的 `cpuidle_latency_limit` / `cpuidle_latency_requirement` 两个 sysfs 节点**已删除**，语义完全由 PM QoS 承担。旧脚本写 `/sys/devices/system/cpu/cpuidle/cpuidle_latency_limit` 会失败。

## Seams with Other Subsystems

- **timer**：停 tick 与 hrtimer 模拟见 [timer](/docs/CS/OS/Linux/timer.md)；`cpuidle_enter()` 直接依赖 `tick_nohz_get_next_hrtimer()`。
- **调度器**：进入 cpuidle 的前置条件是所有任务都不可调度，路径见 [sche](/docs/CS/OS/Linux/proc/sche.md) 的空闲部分。
- **中断**：`enter_dead` 回调是"关中断时直接进最深档"的路径。
- **cpufreq**：C-state 出节电、P-state 出性能，两者的预测输入同源，见 [cpufreq](/docs/CS/OS/Linux/PM/cpufreq.md)。
- **runtime PM**：进 C-state 前的设备 suspend 与 PM QoS 交互见 [runtime PM](/docs/CS/OS/Linux/PM/runtimepm.md)。

## Troubleshooting Quick Reference

```shell
# 当前 governor 与 driver
cat /sys/devices/system/cpu/cpuidle/current_governor
cat /sys/devices/system/cpu/cpuidle/current_driver
cat /sys/devices/system/cpu/cpuidle/current_governor_khz

# 逐档信息（名字/退出延迟/目标驻留）
for d in /sys/devices/system/cpu/cpu0/cpuidle/state*; do
  echo "$(cat $d/name): exit=$(cat $d/latency)us residency=$(cat $d/residency)us disable=$(cat $d/disable)"
done

# 临时禁用某档（1 = 禁用）
echo 1 | tee /sys/devices/system/cpu/cpu0/cpuidle/state3/disable
echo 0 | tee /sys/devices/system/cpu/cpu0/cpuidle/state3/disable

# 统计：rejected 高说明选档过深
cat /sys/devices/system/cpu/cpuidle/stats
# 字段：usage / rejected / total / name

# 换 governor
echo teo | tee /sys/devices/system/cpu/cpuidle/current_governor

# 禁用 cpuidle（排查对比用）
echo "cpuidle.poll=0"  # 或用 grub 的 idle=poll
cat /sys/devices/system/cpu/cpu0/cpuidle/state1/disable   # 浅档全禁
```

## Links

- [电源管理知识地图](/docs/CS/OS/Linux/PM/README.md)
- [cpufreq 频率调节](/docs/CS/OS/Linux/PM/cpufreq.md)
- [timer 时间子系统](/docs/CS/OS/Linux/timer.md)
- [进程调度 sche](/docs/CS/OS/Linux/proc/sche.md)
- [runtime PM 设备省电](/docs/CS/OS/Linux/PM/runtimepm.md)
- [中断与 softirq](/docs/CS/OS/Linux/Interrupt.md)

## References

1. [Linux Kernel Documentation — CPU Idle](https://docs.kernel.org/admin-guide/pm/cpuidle.html)
2. [Linux Kernel Documentation — PM QoS Interface](https://docs.kernel.org/power/pm_qos_interface.html)
3. [CPU Frequency Scaling — menu governor](https://docs.kernel.org/admin-guide/pm/cpufreq.html)
4. [Documentation/arch/x86/pm/intel_pstate.rst](https://docs.kernel.org/arch/x86/pm/intel_pstate.html)
