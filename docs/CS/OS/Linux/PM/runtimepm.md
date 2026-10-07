## Introduction

runtime PM 管的是**单个设备的电源开关**，而且是"按需"的 —— 设备没人用了就自动断电，有人用了再自动通电。它与 [suspend](/docs/CS/OS/Linux/PM/suspend.md) 是两个层次：suspend 是**整机**睡眠，runtime PM 是**单个设备**在系统运行时进出省电状态。

它解决的问题很实际：PCIe 设备、PHY、eSATA 控制器、无线模块、音频 codec 这些东西即使不传输数据也在耗电。runtime PM 让它们"不用就关"，而不需要卸载驱动或断电重启。

版本基线 **v7.2**。

## Core Model: Reference Counting + State Machine

驱动通过一对调用表达"我要用"和"我用完了"：

```c
pm_runtime_get_sync(dev);   /* 我要用这个设备：引用计数 +1，并同步恢复 */
pm_runtime_put(dev);        /* 我用完了：引用计数 -1，归零则挂起 */
```

内核维护每个设备的 `usage_count`：

- 引用计数从 0 → 1：调用 `->runtime_resume()` 把设备恢复；
- 引用计数从 1 → 0：**不立即挂起**，而是走 autosuspend 判定（见下文）；
- 引用计数 > 1：什么都不做（设备本来就是醒的）。

这个"归零不立即挂起"的设计是 autosuspend 的基础 —— 否则每次 `get`/`put` 配对都会导致设备反复通断电，既费电又费时间。

## State Machine

```c
enum rpm_status {
	RPM_INVALID = -1,
	RPM_ACTIVE = 0,
	RPM_RESUMING,
	RPM_SUSPENDED,
	RPM_SUSPENDING,
	RPM_BLOCKED,
};
```

**v7.2 的重要变化**：`runtime_status` 是这个 **6 值枚举**，而旧资料里是位标志（`RPM_ACTIVE` / `RPM_SUSPENDED` / `RPM_ERROR` 等可按位或）。改成枚举后**不能再用位运算组合状态**。

各状态语义（源码注释原文）：

| 状态 | 含义 |
| :-- | :-- |
| `RPM_ACTIVE` | 完全可运行，`->runtime_resume()` 已成功完成 |
| `RPM_SUSPENDED` | `->runtime_suspend()` 已成功完成，设备被视为已挂起 |
| `RPM_RESUMING` | `->runtime_resume()` 正在执行 |
| `RPM_SUSPENDING` | `->runtime_suspend()` 正在执行 |
| `RPM_BLOCKED` | 恢复过程被阻塞（回调返回 `-EBUSY` 等） |

注释里有一句重要提醒：

```c
 * current status of a device with respect to the PM core operations.  They do
 * not reflect the actual power state of the device or its status as seen by
 * the driver.
```

**状态反映的是"PM 核心认为的状态"，不是设备的真实电源状态** —— 驱动可能没实现 `->runtime_suspend()`（此时状态照样变，但硬件没断电）。排查"设备为什么还耗电"时要看驱动是否真的实现了回调。

## Power State Structure

```c
	bool			idle_notification:1;
	bool			request_pending:1;
	bool			deferred_resume:1;
	bool			needs_force_resume:1;
	bool			runtime_auto:1;
	bool			ignore_children:1;
	bool			no_callbacks:1;
	bool			irq_safe:1;
	bool			use_autosuspend:1;
	bool			timer_autosuspends:1;
	bool			memalloc_noio:1;
	unsigned int		links_count;
	enum rpm_request	request;
	enum rpm_status		runtime_status;
	enum rpm_status		last_status;
	int			runtime_error;
	int			autosuspend_delay;
	u64			last_busy;
	u64			active_time;
	u64			suspended_time;
	u64			accounting_timestamp;
```

几个值得注意的字段：

- **`irq_safe:1`** —— 允许在**原子上下文/中断上下文**里做某些操作（早期是 `atomic` 位的替代）。
- **`memalloc_noio:1`** —— 挂起过程中允许分配内存（默认不允许，因为 `->runtime_suspend` 常在原子上下文执行）。
- **`autosuspend_delay` 是 `int`**（毫秒）—— 旧资料里的 `autosuspend_pending_ms` **不存在**。
- **`deferred_resume:1`** —— 设备在 `-EPROBE_DEFER` 状态下的特殊处理。
- `active_time` / `suspended_time` / `accounting_timestamp` 用于统计设备实际活跃/挂起时长。

## dev_pm_ops: Three Runtime Callbacks

```c
struct dev_pm_ops {
	int (*prepare)(struct device *dev);
	void (*complete)(struct device *dev);
	int (*suspend)(struct device *dev);
	int (*resume)(struct device *dev);
	...
	int (*runtime_suspend)(struct device *dev);
	int (*runtime_resume)(struct device *dev);
	int (*runtime_idle)(struct device *dev);
};
```

**前面一大半都是系统睡眠用的**（`prepare`/`suspend`/`suspend_late`/`suspend_noirq` 及各自的 resume 变体，还有 freeze/thaw/poweroff/restore 系列），runtime PM 只用到最后三个。

`->runtime_idle()` 是**可选**的：设备空闲但不一定要断电时用它做轻量的部分省电（如降低链路速率、关 PLL 但保持寄存器）。

> ⚠️ **v7.2 的变化**：`struct dev_pm_ops` **没有** `def_runtime_resume` / `power_state_name` 字段；`DEFINE_FLEXOS_CLEANUP` 宏也不存在（改用 `DEFINE_GUARD` / `DEFINE_FREE`）。

### Macro System

```c
#define RUNTIME_PM_OPS(suspend_fn, resume_fn, idle_fn) \
	.runtime_suspend = suspend_fn, \
	.runtime_resume = resume_fn, \
	.runtime_idle = idle_fn,
```

`DEFINE_RUNTIME_DEV_PM_OPS()` 是推荐的定义方式：

```c
#define DEFINE_RUNTIME_DEV_PM_OPS(name, suspend_fn, resume_fn, idle_fn) \
	_DEFINE_DEV_PM_OPS(name, pm_runtime_force_suspend, \
			   pm_runtime_force_resume, suspend_fn, \
			   resume_fn, idle_fn)
```

注意它给系统睡眠填的是 `pm_runtime_force_suspend` / `pm_runtime_force_resume` —— 注释解释了与旧宏的区别：

```c
 * Note that the behaviour differs from the deprecated UNIVERSAL_DEV_PM_OPS()
 * macro, which uses the provided callbacks for both runtime PM and system
 * sleep, while DEFINE_RUNTIME_DEV_PM_OPS() uses pm_runtime_force_suspend()
 * and pm_runtime_force_resume() for its system sleep callbacks.
```

即：**只实现 runtime 回调，系统睡眠路径由 PM 核心用通用实现兜底**。若需要自定义睡眠行为，得用 `SYSTEM_SLEEP_PM_OPS` 系列宏。

## Three Variants of get

```c
extern void __pm_runtime_use_autosuspend(struct device *dev, bool use);
extern void pm_runtime_set_autosuspend_delay(struct device *dev, int delay);
...
extern int devm_pm_runtime_set_active_enabled(struct device *dev);
extern int devm_pm_runtime_get_noresume(struct device *dev);
```

| API | 语义 |
| :-- | :-- |
| `pm_runtime_get_sync()` | 计数 +1 并**同步**恢复到 `RPM_ACTIVE`。最常用 |
| `pm_runtime_get_noresume()` | 只加计数，**不恢复**。设备已在活动状态时用（省一次恢复） |
| `devm_pm_runtime_get_noresume()` | 同上，但设备解绑时自动 put |
| `pm_runtime_get_sync()` 失败 | 返回 `-EAGAIN` 等，**此时计数已加**，调用者必须处理 |

`get_noresume()` 的价值：一个"在设备已经醒着时也要标记我在用"的场景，用 `get_sync` 会触发一次不必要的恢复检查（虽然状态已经是 ACTIVE 时是廉价的，但仍有原子操作开销）。

### RPM Flag Parameters

```c
#define RPM_ASYNC		0x01	/* Request is asynchronous */
#define RPM_NOWAIT		0x02	/* Don't wait for concurrent
					    state change */
#define RPM_GET_PUT		0x04	/* Increment/decrement the
					    usage_count */
#define RPM_AUTO		0x08	/* Use autosuspend_delay */
#define RPM_TRANSPARENT		0x10	/* Succeed if runtime PM is disabled */
```

`RPM_TRANSPARENT` 用于"runtime PM 没开也要成功"的场景 —— 适合那些"能省电就省电，但驱动不强制要求"的调用点。

## put and Autosuspend

```c
extern void pm_runtime_put(struct device *dev);
...
extern void pm_runtime_mark_last_busy(struct device *dev);
```

`pm_runtime_put()` 的注释说明了它做的事：

```c
 * pm_runtime_put - Drop device usage counter and queue up "idle check" if 0.
```

**只"排队 idle 检查"，不立即挂起**。真正的判定在 autosuspend 路径。

### Two Conditions for Autosuspend

设备实际进入 autosuspend 需要**同时**满足：

1. 引用计数为 0；
2. **`use_autosuspend` 为真且 `autosuspend_delay` 已设置**（否则直接 suspend，不延迟）。

```c
extern void __pm_runtime_use_autosuspend(struct device *dev, bool use);
extern void pm_runtime_set_autosuspend_delay(struct device *dev, int delay);
```

`pm_runtime_set_autosuspend_delay()` 内部会**自动打开 `use_autosuspend`** —— 所以只调它就够了，不必先调 `use_autosuspend(true)`。

延迟计时的起点是 `pm_runtime_mark_last_busy()` 记录的时间戳：

```c
static inline void pm_runtime_mark_last_busy(struct device *dev)
```

**最后一次访问设备后延迟指定毫秒才挂起**。这是"避免突发小操作导致设备反复通断电"的核心机制 —— 比如键盘敲几个键就挂网卡显然不合理。

### Request Types

```c
enum rpm_request {
	RPM_REQ_NONE,		/* Do nothing. */
	RPM_REQ_IDLE,		/* Run the device bus type's ->runtime_idle() callback */
	RPM_REQ_SUSPEND,	/* Run the device bus type's ->runtime_suspend() callback */
	RPM_REQ_AUTOSUSPEND,	/* Same as RPM_REQ_SUSPEND, but not until the device has
				   been inactive for as long as power.autosuspend_delay */
};
```

这个枚举说明了 autosuspend 的本质：**`RPM_REQ_AUTOSUSPEND` 就是"延后执行的 `RPM_REQ_SUSPEND`"**，延迟条件由 `power.autosuspend_delay` 给定。

`runtime_idle` 与 `runtime_suspend` 的区别在 `RPM_REQ_IDLE` vs `RPM_REQ_SUSPEND` 里体现：前者是"轻量省电"，后者是"完全断电"。

## Power Domain: Cross-device Power Domain

```c
struct dev_pm_domain {
	struct dev_pm_ops	ops;
	int (*start)(struct device *dev);
	void (*detach)(struct device *dev, bool power_off);
	int (*activate)(struct device *dev);
	void (*sync)(struct device *dev);
	void (*dismiss)(struct device *dev);
	int (*set_performance_state)(struct device *dev, unsigned int state);
};
```

**power domain 是比设备更高一层抽象**：多个设备共享一个电源域（如 SoC 的电源域、PCIe switch 的供电域），域可以整体上下电。注释说明了它的调用时机：

```c
 * Power domains provide callbacks that are executed during system suspend,
 * hibernation, system resume and during runtime PM transitions instead of
 * subsystem-level and driver-level callbacks.
```

注意注释用的词是 "**instead of**" —— 域的回调**取代**了子系统级/驱动级回调。设备有 `pm_domain` 时，PM 核心走域的 ops，而不是设备自己的 `dev_pm_ops`。

`->set_performance_state()` 值得注意：它把 [devfreq](/docs/CS/OS/Linux/PM/devfreq.md) 的性能状态请求**接入 PM 核心**，实现设备性能与电源的统一管理。

## Parent-child Dependencies: supplier/consumer

设备间有依赖关系（一个设备供电给另一个），runtime PM 核心通过 **supplier/consumer** 模型处理：consumer 恢复前先恢复 supplier。

```c
extern void pm_runtime_put_suppliers(struct device *dev);
```

设备模型里的 `DL_FLAG_RPM_ACTIVE` 用于"建立设备链接时对 supplier 执行 `pm_runtime_get_sync()`"：

```c
 * RPM_ACTIVE: Run pm_runtime_get_sync() on the supplier during link creation.
#define DL_FLAG_RPM_ACTIVE		BIT(3)
```

这解释了一个常见现象：**HDMI/PCIe 这类"消费者"设备的 runtime PM 依赖"供应者"（PHY、时钟、电源域）**，只对消费者调 get 而不管供应者会在某些配置下出问题。

## Relationship with Other PM Types

| 机制 | 粒度 | 触发 | 设备回调 |
| :-- | :-- | :-- | :-- |
| runtime PM | 单设备 | 引用计数归零 | `->runtime_suspend/resume/idle` |
| 系统 suspend | 整机 | 用户写 `/sys/power/state` | `->suspend` 系列 |
| PM domain | 设备组 | 上述两者 | `pm_domain->ops` |
| cpuidle | CPU | 无任务可运行 | `->enter` |
| cpufreq | CPU | util 变化 | `->fast_switch` / `->setpolicy` |

runtime PM 与系统 suspend 有一个重要区别：**系统 suspend 期间所有设备都该挂起，而 runtime PM 只挂起"当前没人用"的设备**。因此系统 resume 后，runtime PM 挂起的设备仍是挂起状态，需要新的 get 才恢复。

## sysfs and Debugging

每个设备的 PM 目录：

```
/sys/devices/platform/<dev>/power/
├── control              # auto | on  ← 关键开关
├── runtime_status       # active | suspended | resuming | suspending | blocked
├── runtime_active_time      # 累计活跃时长（ms）
├── runtime_suspended_time    # 累计挂起时长（ms）
├── runtime_usage          # 当前引用计数
├── autosuspend_delay_ms    # autosuspend 延迟
├── autosuspend_delay_ms_show
├── wakeup                 # 是否允许远程唤醒
└── runtime_error         # 最近一次错误

/sys/devices/platform/<dev>/power/clock_control/  # 部分设备
```

**`control` 是最重要的开关**：

| 值 | 含义 |
| :-- | :-- |
| `auto` | 允许 runtime PM 自动挂起（默认值） |
| `on` | **禁止**挂起，设备保持 `RPM_ACTIVE` |

排查"设备不省电"时先看 `control` 和 `runtime_status`：

```shell
# 为什么这个设备一直不挂起？
cat /sys/devices/platform/xxx/power/control        # 是 on 吗？
cat /sys/devices/platform/xxx/power/runtime_status # 是 active 还是 suspended
cat /sys/devices/platform/xxx/power/runtime_usage # 引用计数是否 > 0
cat /sys/devices/platform/xxx/power/autosuspend_delay_ms   # 是 -1（未启用）？
cat /sys/devices/platform/xxx/power/runtime_error  # 有挂起失败过？
```

> **`autosuspend_delay_ms` 为 -1 表示 autosuspend 未启用** —— 此时引用计数归零会立即 suspend（而非延迟）。

`runtime_error` 记录最近的失败错误码。反复出现 `-EAGAIN` 或 `-EBUSY` 说明设备的 `->runtime_suspend` 拒绝了挂起。

## Seams with Other Subsystems

- **设备模型**：`struct device.power` 与设备 probe/remove 的时序配合见 [设备模型 device](/docs/CS/OS/Linux/dev/device.md)。
- **总线**：runtime PM 的回调最终由总线类型执行（PCI/USB/I2C 各自的 runtime_suspend），见 [dev 总线族](/docs/CS/OS/Linux/dev/bus.md)。
- **时钟框架**：设备省电常伴随时钟开关，见 [dev 总线族（clk）](/docs/CS/OS/Linux/dev/bus.md)。
- **suspend**：系统睡眠与 runtime PM 的分层关系见 [suspend](/docs/CS/OS/Linux/PM/suspend.md)。
- **devfreq**：设备动态频率通过 power domain 接入 PM 核心，见 [devfreq](/docs/CS/OS/Linux/PM/devfreq.md)。
- **中断**：设备挂起期间的 IRQ 处理约束（`irq_safe` 位的意义）。

## Troubleshooting Quick Reference

```shell
# 全局统计：谁在耗电
find /sys/devices -name power_control -o -name power 2>/dev/null | head
# 看挂起时长最长的设备
for d in /sys/devices/*/*/power; do
  [ -r "$d/runtime_suspended_time" ] && echo "$(cat $d/runtime_suspended_time) $d"
done | sort -rn | head

# 逐个设备诊断
P=/sys/devices/platform/soc/xxx
cat $P/power/control $P/power/runtime_status $P/power/runtime_usage
cat $P/power/autosuspend_delay_ms $P/power/runtime_error

# 强制关闭 runtime PM（对比排查）
echo on > $P/power/control
# 恢复
echo auto > $P/power/control

# 设置 autosuspend 延迟
echo 2000 > $P/power/autosuspend_delay_ms

# 全局默认延迟
cat /sys/module/usbcore/parameters/autosuspend        # USB
cat /sys/bus/pci/drivers/pcieport/power/control       # PCIe

# 监控 suspend/resume 是否真发生
cat /sys/kernel/debug/pm_genpd/pm_genpd_summary | grep -A5 xxx
```

## Links

- [电源管理知识地图](/docs/CS/OS/Linux/PM/README.md)
- [cpuidle 空闲挂起](/docs/CS/OS/Linux/PM/cpuidle.md)
- [cpufreq 频率调节](/docs/CS/OS/Linux/PM/cpufreq.md)
- [suspend 整机睡眠](/docs/CS/OS/Linux/PM/suspend.md)
- [devfreq 设备动态频率](/docs/CS/OS/Linux/PM/devfreq.md)
- [设备模型 device](/docs/CS/OS/Linux/dev/device.md)
- [dev 总线族](/docs/CS/OS/Linux/dev/bus.md)

## References

1. [Linux Kernel Documentation — Runtime PM](https://docs.kernel.org/power/runtime_pm.html)
2. [Linux Kernel Documentation — Power Domains](https://docs.kernel.org/power/pm_domains.html)
3. [Linux Kernel Documentation — Device PM QoS](https://docs.kernel.org/power/pm_qos_interface.html)
4. [Documentation/power/devices.txt](https://docs.kernel.org/power/devices.html)
