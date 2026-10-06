## Introduction

suspend 是**整机级**的电源管理：把 CPU、内存、设备全部切到低功耗态，等待唤醒事件后恢复。相比 [runtime PM](/docs/CS/OS/Linux/PM/runtimepm.md) 的"按需关单个设备"，suspend 是"整机睡"，恢复后上下文继续。

它的实现是一条**极其严格的顺序链** —— 顺序错了就是 crash 或数据损坏。本文按源码实际调用顺序讲这条链，所有函数名在 **v7.2** 核实。

## 睡眠状态

```c
typedef int __bitwise suspend_state_t;

#define PM_SUSPEND_ON		((__force suspend_state_t) 0)
#define PM_SUSPEND_TO_IDLE	((__force suspend_state_t) 1)
#define PM_SUSPEND_STANDBY	((__force suspend_state_t) 2)
#define PM_SUSPEND_MEM		((__force suspend_state_t) 3)
#define PM_SUSPEND_MIN		PM_SUSPEND_TO_IDLE
#define PM_SUSPEND_MAX		((__force suspend_state_t) 4)
```

三种实际可用的状态，**省电程度递增**：

| 常量 | `/sys/power/state` 名 | 省电 | 依赖 |
| :-- | :-- | :-- | :-- |
| `PM_SUSPEND_TO_IDLE` | `freeze` | 最小 | 仅 CPU 空闲 + 设备 runtime suspend，**内存不断电** |
| `PM_SUSPEND_STANDBY` | `standby` | 中 | 平台相关（STR 需固件支持） |
| `PM_SUSPEND_MEM` | `mem` | 最大 | 内存进入自刷新，**上下文保留在内存里** |

这里有个命名陷阱值得记住：`PM_SUSPEND_TO_IDLE` 在 `/sys/power/state` 里叫 **`freeze`**。这是历史遗留 —— 它最初就是"冻结进程"的意思（不涉及电源），后来才演变成 s2idle。

### /sys/power/mem_sleep：s2idle / shallow / deep

`/sys/power/state` 里的 `mem` 对应 `/sys/power/mem_sleep` 里的 `deep`。同一批状态在两个 sysfs 文件里用了不同命名：

```c
const char * const pm_labels[] = {
	[PM_SUSPEND_TO_IDLE] = "freeze",
	[PM_SUSPEND_STANDBY] = "standby",
	[PM_SUSPEND_MEM] = "mem",
};
const char *pm_states[PM_SUSPEND_MAX];
static const char * const mem_sleep_labels[] = {
	[PM_SUSPEND_TO_IDLE] = "s2idle",
	[PM_SUSPEND_STANDBY] = "shallow",
	[PM_SUSPEND_MEM] = "deep",
};
const char *mem_sleep_states[PM_SUSPEND_MAX];
```

而 `mem_sleep_labels` **只在 mem 状态被支持时才赋值**（因为只有 `mem` 才有多档深度可选）：

```c
	/* "mem" and "freeze" are always present in /sys/power/state. */
```

所以**只有 `mem` 状态存在 `/sys/power/mem_sleep` 文件**，`freeze` 和 `standby` 没有对应的深度选择。

当前状态与默认值：

```c
suspend_state_t mem_sleep_current = PM_SUSPEND_TO_IDLE;
suspend_state_t mem_sleep_default = PM_SUSPEND_MAX;
```

**`mem_sleep_default` 初值是 `PM_SUSPEND_MAX`（无效标记）**，表示"尚未确定默认深度"，由平台或用户设置。

判断是否默认走 s2idle：

```c
/**
 * pm_suspend_default_s2idle - Check if suspend-to-idle is the default suspend.
 *
 * Return 'true' if suspend-to-idle has been selected as the default system
 * suspend method.
 */
bool pm_suspend_default_s2idle(void)
{
	return mem_sleep_current == PM_SUSPEND_TO_IDLE;
}
```

这个函数被 `firmware/` 下的电源管理代码用来决定"要不要用 s2idle 而非平台睡眠"。

## 平台回调：platform_suspend_ops

> ⚠️ **v7.2 的重要变化**：旧资料里的 `struct suspend_ops` **已不存在**，改为 **`struct platform_suspend_ops`**。更关键的是**成员完全不同** —— 不是 `prepare`/`prepare_late`/`enter_noirq` 那套，而是：

```c
struct platform_suspend_ops {
	int (*valid)(suspend_state_t state);
	int (*begin)(suspend_state_t state);
	int (*prepare)(void);
	int (*prepare_late)(void);
	int (*enter)(suspend_state_t state);
	void (*wake)(void);
	void (*finish)(void);
	bool (*suspend_again)(void);
	void (*end)(void);
	void (*recover)(void);
};
```

十个成员，按睡眠/唤醒两侧对称分布：

| 阶段 | 成员 | 说明 |
| :-- | :-- | :-- |
| 睡眠前 | `valid` | 该状态是否支持（决定是否出现在 `/sys/power/state`） |
| | `begin` / `end` | 睡眠开始前/结束后的平台准备 |
| | `prepare` / `prepare_late` | 设备 suspend 之前 |
| | `enter` | **真正进入睡眠（关电源）** |
| 唤醒后 | `wake` | 唤醒第一时间 |
| | `finish` | 收尾 |
| | `recover` | **睡眠失败后的恢复** |
| | `suspend_again` | 询问是否需要再次进入睡眠（见下） |

`suspend_again` 是新机制 —— 允许平台在 resume 后发现"其实还需要再睡一次"（比如唤醒只是瞬时事件）。

注册用 `suspend_set_ops()`：

```c
void suspend_set_ops(const struct platform_suspend_ops *ops)
{
	...
	suspend_ops = ops;
}
```

s2idle 有独立的 `struct platform_s2idle_ops`（`s2idle_set_ops()`），与平台睡眠分开。

### s2idle 绕过平台回调

值得注意的是 s2idle 路径**不需要 `suspend_ops`**：

```c
	/* Suspend-to-idle should be supported even without any suspend_ops, */
```

以及调用时的条件判断：

```c
	return state != PM_SUSPEND_TO_IDLE && suspend_ops->prepare ? ...
```

即 **`prepare` / `prepare_late` / `finish` / `recover` 在 s2idle 路径下全部被跳过**。这就是为什么 s2idle 能在没有平台支持的系统上工作 —— 它本质是"把所有 CPU 挂进深 C-state"，依赖的是 [cpuidle](/docs/CS/OS/Linux/PM/cpuidle.md) 而非平台电源管理。

## suspend_enter：完整的顺序链

这是本文的核心。`suspend_enter()` 严格按固定顺序推进，**任何一步失败都要逆序回滚**：

```c
static int suspend_enter(suspend_state_t state, bool *wakeup)
{
	int error;

	error = platform_suspend_prepare(state);
	if (error)
		goto Platform_finish;

	error = dpm_suspend_late(PMSG_SUSPEND);
	if (error) {
		pr_err("late suspend of devices failed\n");
		goto Platform_finish;
	}
	error = platform_suspend_prepare_late(state);
	if (error)
		goto Devices_early_resume;

	error = dpm_suspend_noirq(PMSG_SUSPEND);
	if (error) {
		pr_err("noirq suspend of devices failed\n");
		goto Platform_early_resume;
	}
	error = platform_suspend_prepare_noirq(state);
	if (error)
		goto Platform_wake;

	if (suspend_test(TEST_PLATFORM))
		goto Platform_wake;

	if (state == PM_SUSPEND_TO_IDLE) {
		s2idle_loop();
		goto Platform_wake;
	}

	error = pm_sleep_disable_secondary_cpus();
	if (error || suspend_test(TEST_CPUS))
		goto Enable_cpus;

	arch_suspend_disable_irqs();
	BUG_ON(!irqs_disabled());

	system_state = SYSTEM_SUSPEND;

	error = syscore_suspend();
	if (!error) {
		*wakeup = pm_wakeup_pending();
		if (!(suspend_test(TEST_CORE) || *wakeup)) {
			trace_suspend_resume(TPS("machine_suspend"),
				state, true);
			error = suspend_ops->enter(state);
			trace_suspend_resume(TPS("machine_suspend"),
				state, false);
		} else if (*wakeup) {
			error = -EBUSY;
		}
		syscore_resume();
	}

	system_state = SYSTEM_RUNNING;

	arch_suspend_enable_irqs();
	BUG_ON(!irqs_disabled());

 Enable_cpus:
	pm_sleep_enable_secondary_cpus();

 Platform_wake:
	platform_resume_noirq(state);
	dpm_resume_noirq(PMSG_RESUME);

 Platform_early_resume:
	platform_resume_early(state);

 Devices_early_resume:
	dpm_resume_early(PMSG_RESUME);

 Platform_finish:
	platform_resume_finish(state);
	return error;
}
```

### 睡眠方向（自上而下）

```
platform_suspend_prepare()          ← 平台准备
dpm_suspend_late()                  ← 设备 late suspend
platform_suspend_prepare_late()     ← 平台 late 准备
dpm_suspend_noirq()                 ← 设备 noirq suspend（关中断）
platform_suspend_prepare_noirq()    ← 平台 noirq 准备
[TEST_PLATFORM] ──────────────────→ 提前退出点
[if s2idle: s2idle_loop() + 退出]  ← s2idle 到此为止
pm_sleep_disable_secondary_cpus()   ← 停非主 CPU
[TEST_CPUS] ─────────────────────→ 提前退出点
arch_suspend_disable_irqs()         ← 关本地中断
syscore_suspend()                  ← 核心状态切换
pm_wakeup_pending() 检查
suspend_ops->enter(state)          ← 真正断电（永不返回直到唤醒）
```

**`dpm_suspend_noirq()` 必须在 `arch_suspend_disable_irqs()` 之前** —— 设备的 noirq suspend 回调里通常还要操作自己的寄存器，此时中断仍开着。一旦关中断再去 suspend 设备，竞态下会丢中断。

### 唤醒方向（自下而上）

```
syscore_resume()
arch_suspend_enable_irqs()
pm_sleep_enable_secondary_cpus()
platform_resume_noirq()
dpm_resume_noirq()                  ← 设备 noirq resume（仍在关中断）
platform_resume_early()
dpm_resume_early()                  ← 设备 early resume
platform_resume_finish()            ← 平台收尾
```

**noirq 阶段的中断状态是"关着"的**（那两行 `BUG_ON(!irqs_disabled())` 就是断言这个），设备 resume 回调必须能在无中断环境下完成寄存器恢复。

### 三个提前退出点

`suspend_test()` 提供测试钩子（详见下文），可在指定阶段主动放弃睡眠：

| 测试点 | 退出到 | 意义 |
| :-- | :-- | :-- |
| `TEST_PLATFORM` | `Platform_wake` | 平台准备完成后不睡（只测设备 suspend/resume） |
| `TEST_CPUS` | `Enable_cpus` | 停完 CPU 后不睡 |
| `TEST_CORE` | 不调 `enter` | syscore 切换后不睡 |

`TEST_CORE` 分支的处理有个细节：

```c
		if (!(suspend_test(TEST_CORE) || *wakeup)) {
			...
			error = suspend_ops->enter(state);
			...
		} else if (*wakeup) {
			error = -EBUSY;
		}
```

**唤醒事件已挂起时返回 `-EBUSY`**（有人在 `suspend_ops->begin()` 里触发了唤醒），而不是进入睡眠。

### s2idle 的短路

```c
	if (state == PM_SUSPEND_TO_IDLE) {
		s2idle_loop();
		goto Platform_wake;
	}
```

s2idle **在平台 noirq 准备之后就直接进 `s2idle_loop()`** —— 不停次要 CPU、不关中断、不切 syscore。原因就是前面说的：s2idle 靠 CPU 挂进深 C-state 实现，"整机断电"是由此触发的。

## 冻结进程

睡眠的第一步是**冻结用户态进程**（`kernel/power/process.c`）：

```c
/**
 * freeze_processes - Signal user space processes to enter the refrigerator.
 * The current thread will not be frozen.  The same process that calls
 * freeze_processes must later call thaw_processes.
 *
 * On success, returns 0.  On failure, -errno and system is fully thawed.
 */
int freeze_processes(void)
{
	int error;

	error = __usermodehelper_disable(UMH_FREEZING);
	if (error)
		return error;

	/* Make sure this task doesn't get frozen */
	current->flags |= PF_SUSPEND_TASK;
	...
}
```

三个要点：

1. **当前线程不被冻结**（`PF_SUSPEND_TASK`）—— 执行冻结的那个线程当然要能继续干活。
2. **必须成对**：`freeze_processes()` 的调用者必须稍后调 `thaw_processes()`。
3. **失败时系统已完全解冻** —— 返回 `-errno` 而非半冻结状态。

### 重试策略：指数退避

冻结是"请求"而非"命令"，进程可能正忙而无法立即进入冷冻。内核的重试策略：

```c
		/*
		 * We need to retry, but first give the freezing tasks some
		 * time to enter the refrigerator.  Start with an initial
		 * 1 ms sleep followed by exponential backoff until 8 ms.
		 */
		usleep_range(sleep_usecs / 2, sleep_usecs);
		if (sleep_usecs < 8 * USEC_PER_MSEC)
			sleep_usecs *= 2;
```

**1 ms 起步，指数退避到 8 ms 封顶**。同时每轮检查 `pm_wakeup_pending()` —— 有人请求唤醒就放弃冻结（睡眠本来就没必要了）。

冻结失败时的诊断输出很有用：

```c
	if (todo) {
		pr_err("Freezing %s %s after %d.%03d seconds "
		       "(%d tasks refusing to freeze, wq_busy=%d):\n", what,
		       wakeup ? "aborted" : "failed",
		       elapsed_msecs / 1000, elapsed_msecs % 1000,
		       todo - wq_busy, wq_busy);

		if (wq_busy)
			show_freezable_workqueues();
		...
	}
```

**打印"多少任务拒绝冻结"并逐个 `sched_show_task()`** —— 定位不配合冻结的进程（常见于用户态没处理信号、或进程卡在内核态）最快的手段。

`todo` 里区分两类：`wq_busy` 是**可冻结工作队列**没冻结（`freeze_workqueues_busy()` 统计），其余是任务拒绝。内核线程不参与冻结统计（它们在 PF_SUSPEND_TASK 逻辑里被排除）。

## 调试：pm_test

> ⚠️ **v7.2 的变化**：旧的 `pm_debug_mask` / `PM_DEBUG_*` 标志位**已被 `pm_test_level` 取代**。

```c
int pm_test_level = TEST_NONE;
static const char * const pm_tests[__TEST_AFTER_LAST] = {
	[TEST_NONE] = "none",
	[TEST_CORE] = "core",
	[TEST_CPUS] = "processors",
	[TEST_PLATFORM] = "platform",
	[TEST_DEVICES] = "devices",
	[TEST_FREEZER] = "freezer",
};
```

五个可注入故障的测试档位（外加 `none`）：

| 档位 | 注入点 |
| :-- | :-- |
| `freezer` | 冻结阶段 |
| `devices` | 设备 suspend/resume |
| `platform` | 平台 prepare 完成后（`TEST_PLATFORM`） |
| `processors` | 停完次要 CPU 后（`TEST_CPUS`） |
| `core` | syscore 切换后，不进 `enter`（`TEST_CORE`） |

用法：

```shell
echo core > /sys/power/pm_test
echo mem  > /sys/power/state     # 走到 core 就返回
dmesg | tail -30                 # 观察哪些回调真的被调用了
```

**这是验证设备 suspend 回调是否完整调用的标准手段** —— 逐步推进到更深阶段，看 dmesg 里哪些设备的 `suspend`/`resume` 没出现。

## 与 cpufreq 的交互

睡眠期间不能动态调频，policy 里有专门的字段：

```c
	unsigned int		suspend_freq; /* freq to set during suspend */
```

`struct cpufreq_driver` 的 `->suspend()` / `->resume()` 回调负责：

- `->suspend()`：把 CPU 切到 `suspend_freq`（通常是最低或某个固定值）；
- `->resume()`：恢复到正常调频。

**这条链发生在 syscore 阶段**，所以它的失败会走 `suspend_again` / `recover` 路径。

## 与 crash dump 的接缝

睡眠失败或唤醒失败时若 panic，走的是 [boot/crash](/docs/CS/OS/Linux/boot/crash.md) 那条链。注意 `pm_wakeup_pending()` 的含义 —— **有唤醒事件待处理时内核不会进入睡眠**，返回 `-EBUSY`。这个检查正是为了避免"刚要睡就被唤醒，白折腾一趟还可能出问题"。

## 与其它子系统的接缝

- **cpuidle**：s2idle 靠 CPU 挂进深 C-state 实现，见 [cpuidle](/docs/CS/OS/Linux/PM/cpuidle.md)。
- **cpufreq**：睡眠前切固定频率，见 [cpufreq](/docs/CS/OS/Linux/PM/cpufreq.md)。
- **runtime PM**：系统 suspend 期间所有设备都要挂起，resume 后仍保持挂起，见 [runtime PM](/docs/CS/OS/Linux/PM/runtimepm.md)。
- **freezer**：内核态的冻结（cgroup.freeze）与这里的用户态冻结是两套，见 [cgroup 控制器接口](/docs/CS/OS/Linux/cgroup/controllers.md?id=freezer-冻结与终止)。
- **设备模型**：`dpm_suspend_*` 系列回调的分发见 [设备模型 device](/docs/CS/OS/Linux/dev/device.md)。
- **崩溃转储**：睡眠链上的 panic 走 [boot/crash](/docs/CS/OS/Linux/boot/crash.md)。

## 排障速查

```shell
# 可用状态
cat /sys/power/state              # freeze standby mem（内容取决于平台）
cat /sys/power/mem_sleep          # s2idle shallow deep（仅当支持 mem）
cat /sys/power/mem_sleep_default  # 开机默认深度
cat /sys/power/disk               # 关机时磁盘策略（可设 never）

# 休眠统计（写 /sys/power/state 后可读）
cat /sys/power/meminfo
cat /sys/power/suspend_stats/mem_suspend_count
cat /sys/power/suspend_stats/mem_suspend_secs

# 逐步测试
echo none > /sys/power/pm_test
echo freezer > /sys/power/pm_test && echo mem > /sys/power/state
echo devices > /sys/power/pm_test && echo mem > /sys/power/state
echo platform > /sys/power/pm_test && echo mem > /sys/power/state   # 最深仍不睡
echo processors > /sys/power/pm_test && echo mem > /sys/power/state
echo core > /sys/power/pm_test && echo mem > /sys/power/state

# 设置默认深度
echo deep > /sys/power/mem_sleep_default

# 触发
echo mem > /sys/power/state
echo freeze > /sys/power/state

# 唤醒后看是否有失败
dmesg | grep -iE "suspend|resume|freeze|PM: " | tail -40
```

## Links

- [电源管理知识地图](/docs/CS/OS/Linux/PM/README.md)
- [cpuidle 空闲挂起](/docs/CS/OS/Linux/PM/cpuidle.md)
- [cpufreq 频率调节](/docs/CS/OS/Linux/PM/cpufreq.md)
- [runtime PM 设备省电](/docs/CS/OS/Linux/PM/runtimepm.md)
- [cgroup 控制器接口（freezer）](/docs/CS/OS/Linux/cgroup/controllers.md?id=freezer-冻结与终止)
- [设备模型 device](/docs/CS/OS/Linux/dev/device.md)
- [boot/crash](/docs/CS/OS/Linux/boot/crash.md)

## References

1. [Linux Kernel Documentation — System Suspend](https://docs.kernel.org/power/suspend-and-hibernate.html)
2. [Linux Kernel Documentation — s2idle](https://docs.kernel.org/power/s2idle.html)
3. [Documentation/admin-guide/pm/suspend-howto.rst](https://docs.kernel.org/admin-guide/pm/suspend-howto.html)
