## Introduction

devfreq 管的是**"非 CPU 的设备该跑多快"** —— 内存控制器（DDR/DRAM）、总线带宽（AXI/CCI）、GPU、核间互联、模组时钟……凡是"频率变了算力就变"的设备都可以挂进来。

它与 [cpufreq](/docs/CS/OS/Linux/PM/cpufreq.md) 的区别在定位：cpufreq 服务 CPU（有调度器给它 util 信号），devfreq 服务设备（**没有调度器，负载必须由设备自己报告**）。这个差异决定了两套框架的接口形态差异。

版本基线 **v7.2**。⚠️ **一处重要重命名**：旧资料里的 `struct devfreq_devinfo` 在 v7.2 已改为 **`struct devfreq_dev_profile`**，且字段大幅精简。

## 三个回调

```c
struct devfreq_dev_profile {
	unsigned long initial_freq;
	unsigned int polling_ms;
	enum devfreq_timer timer;

	int (*target)(struct device *dev, unsigned long *freq, u32 flags);
	int (*get_dev_status)(struct device *dev,
			      struct devfreq_dev_status *stat);
	int (*get_cur_freq)(struct device *dev, unsigned long *freq);
	void (*exit)(struct device *dev);

	unsigned long *freq_table;
	unsigned int max_state;

	bool is_cooling_device;

	const struct attribute_group **dev_groups;
};
```

**`->target()` 是唯一必须实现的**，语义在注释里写得很精确：

```c
 * @target:		The device should set its operating frequency at
 *			freq or lowest-upper-than-freq value. If freq is
 *			higher than any operable frequency, set maximum.
 *			Before returning, target function should set
 *			freq at the current frequency.
```

三个关键点：**① 请求值可以向上取整到最近的可用频率**（"lowest-upper-than"）；**② 超过最高档就设最高**；**③ 返回前要把 `*freq` 改写成实际生效的频率** —— 这一点最容易写错，governor 靠它读回真实值。

`->get_dev_status()` 报告负载。注释特别提醒了 governor 该怎么用：

```c
 * @get_dev_status:	The device should provide the current performance
 *			status to devfreq. Governors are recommended not to
 *			use this directly. Instead, governors are recommended
 *			to use devfreq_update_stats() along with
 *			devfreq.last_status.
```

**推荐 governor 用 `devfreq_update_stats()` + `devfreq.last_status`**，而不是每轮直接调 `get_dev_status()`。前者会保存历史供 governor 做趋势分析（见下文 simple_ondemand 的 `devfreq_get_dev_status` 模式）。

> ⚠️ 旧结构名 `devfreq_devinfo` 及其中的 `frequency` / `min_freq` / `max_freq` / `trans_bufsize` / `bus_width` / `target_freq` / `profile` 字段**在 v7.2 全部不存在**。频率范围改为由 `freq_table` 表达。

## polling_ms 与 timer 类型

```c
	unsigned int polling_ms;		/* The polling interval in ms. 0 disables polling. */
	enum devfreq_timer timer;		/* Timer type is either deferrable or delayed timer. */
```

**`polling_ms = 0` 关闭轮询**，此时设备改用 `devfreq_update_stats()` 主动上报（事件驱动模式）。这省掉了轮询开销，但要设备自己在负载变化时调用上报 —— GPU 那种"没有明确负载信号但可以算 busy 时间"的设备适合这种模式。

`timer` 类型选 **deferrable**（可推迟的 timer）能让 devfreq 的周期任务避开 CPU 深度空闲期，间接省电。

## governor 清单

`drivers/devfreq/Makefile` 的完整列表：

| 文件 | governor | 行为 |
| :-- | :-- | :-- |
| `governor_simpleondemand.o` | `simple_ondemand` | 按负载调频 |
| `governor_performance.o` | `performance` | 恒最高 |
| `governor_powersave.o` | `powersave` | 恒最低 |
| `governor_userspace.o` | `userspace` | 用户写 |
| `governor_passive.o` | **`passive`** | **不自己调，只上报建议** |

宏定义在头文件里：

```c
#define DEVFREQ_GOV_SIMPLE_ONDEMAND	"simple_ondemand"
#define DEVFREQ_GOV_PERFORMANCE		"performance"
#define DEVFREQ_GOV_POWERSAVE		"powersave"
#define DEVFREQ_GOV_USERSPACE		"userspace"
#define DEVFREQ_GOV_PASSIVE		"passive"
```

`passive` 是最特别的一个 —— **它不设频率，只把自己的 `devfreq_set_freq()` 调用当作"建议"转发给 thermal 框架**。真正的决策由 thermal governor 做出。这是"性能需求由温度决定"的架构：设备说"我需要这么快"，thermal 说"现在太热，我只能给这么快"。

> 旧资料里的 `simple_ondemand_sqrt` / `simple_dvfs` 在 v7.2 **不存在**。

### 平台驱动

Makefile 里还有一批 SoC 专属驱动，都带 `_DEVFREQ` 后缀：

```
exynos-bus  hisi_uncore_freq  imx-bus  imx8m-ddrc
mtk-cci-devfreq  rk3399_dmc  sun8i-a33-mbus  tegra30-devfreq
```

从名字能看出覆盖范围：**内存控制器**（`imx8m-ddrc`、`rk3399_dmc`）、**总线/互联**（`imx-bus`、`sun8i-a33-mbus`、`mtk-cci`）、**uncore**（`hisi_uncore_freq`）、**GPU**（`tegra30-devfreq`）。移动 SoC 是 devfreq 的主战场 —— 手机的功耗预算远比服务器紧张。

## thermal 集成

`is_cooling_device` 标志把设备接入 thermal 框架：

```c
	bool is_cooling_device;
```

标记为 true 后，devfreq 会向 thermal 注册成一个 cooling device，thermal 的 governor（`step_wise` / `power_allocator` / `fair` 等）可以通过降低这个"冷却设备"来间接降频。`passive` governor 走的是同一条链路，只是方向相反。

## 注册与 sysfs

```c
struct devfreq *devm_devfreq_add_device(struct device *dev,
					struct devfreq_dev_profile *profile,
					struct devfreq *devfreq_devfreq);
```

`devm_` 前缀版本在设备解绑时自动清理。注册后得到 sysfs 目录：

```
/sys/devices/platform/<dev>/devfreq/
├── governor              # 可写切换
├── cur_freq              # 当前频率
├── min_freq / max_freq   # 频率范围（由 freq_table 导出）
├── trans_stat            # 切换次数
├── load                  # 负载（%）
├── total_time            # 累计运行时间
├── busy_time             # 累计忙碌时间
└── governor_trans_stat   # 各 governor 的切换次数
```

`/proc/interrupts` 里的 devfreq 定时器中断频率是判断"polling_ms 是否合理"的最直接方法 —— 过高说明轮询太频繁白烧电。

## 与其它子系统的接缝

- **cpufreq**：框架形态相似（policy vs devfreq），但负载来源不同，见 [cpufreq](/docs/CS/OS/Linux/PM/cpufreq.md)。
- **runtime PM**：devfreq 可以挂在 power domain 下由 PM 核心管电源，性能请求经 `->set_performance_state()` 传入，见 [runtime PM](/docs/CS/OS/Linux/PM/runtimepm.md)。
- **thermal**：cooling device 接入与 `passive` governor 的反向控制，见 [PM 知识地图](/docs/CS/OS/Linux/PM/README.md)。
- **设备模型**：devfreq 是设备的一个可选能力框架，注册失败通常不阻塞 probe，见 [设备模型 device](/docs/CS/OS/Linux/dev/device.md)。

## 排障速查

```shell
# 全局：有哪些 devfreq 设备
ls /sys/devices/platform/*/devfreq/ 2>/dev/null
find /sys/devices -name devfreq -type d 2>/dev/null

# 逐个诊断
D=/sys/devices/platform/xxx/devfreq
cat $D/governor $D/cur_freq $D/min_freq $D/max_freq
cat $D/load $D/total_time $D/busy_time      # busy/total 决定真实利用率
cat $D/trans_stat                           # 切换次数，突增说明 governor 抖动

# 固定频率（禁用动态调频）
echo performance | tee $D/governor
echo userspace   | tee $D/governor
echo <freq>      | tee $D/cur_freq

# 确认是否作为 cooling device 接入 thermal
ls /sys/class/thermal/cooling_device*/ 2>/dev/null
cat /sys/class/thermal/cooling_device*/type | grep devfreq

# 轮询开销检查：devfreq 定时器中断次数
grep -i devfreq /proc/interrupts
awk -F: '/devfreq/ {s+=$2} END {print "devfreq 中断/秒参考:", s}'

# 温度是否在压制频率
cat /sys/class/thermal/thermal_zone*/temp
cat /sys/class/thermal/cooling_device*/cur_state
```

## Links

- [电源管理知识地图](/docs/CS/OS/Linux/PM/README.md)
- [cpufreq 频率调节](/docs/CS/OS/Linux/PM/cpufreq.md)
- [runtime PM 设备省电](/docs/CS/OS/Linux/PM/runtimepm.md)
- [设备模型 device](/docs/CS/OS/Linux/dev/device.md)

## References

1. [Linux Kernel Documentation — devfreq](https://docs.kernel.org/power/devfreq.html)
2. [Linux Kernel Documentation — devfreq-cooling](https://docs.kernel.org/power/devfreq-cooling.html)
3. [Linux Kernel Documentation — cpufreq energy model](https://docs.kernel.org/power/cpufreq-energy-model.html)
