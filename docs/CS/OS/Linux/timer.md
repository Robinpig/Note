## Introduction

Linux 时间子系统是管理和维护系统时间的软件和硬件组件集合，对计算机系统运行和应用程序至关重要
Linux 时间子系统包括时钟驱动程序、时钟中断处理程序、系统时间管理程序、时钟同步协议等
其中，RTC（Real Time Clock，实时时钟）子系统是 Linux 内核中的一个重要部分，用于管理和操作硬件上的实时时钟
实时时钟通常是一块独立的硬件设备，即使系统处于关机状态也能保持运行，为系统提供精确的时间信息

Linux 内核提供了一组 API，让用户空间程序可以与 RTC 子系统进行交互，包括打开和关闭 RTC 设备文件、读取和设置当前时间、设置闹钟等
在 Linux 中，RTC 子系统通常通过 I2C、SPI 或 ACPI 等总线进行与硬件的通信，具体的硬件细节和支持的功能取决于系统架构和所使用的硬件平台

Linux 系统的晶振时间指的是系统时钟的精确度和准确性。它由硬件时钟提供，通常是一个晶体振荡器，用于提供稳定的时钟信号
晶振时间与系统时间紧密相关，影响着系统中所有命令和函数的时间计算
Linux系统以1970年1月1日0点0分0秒（UTC）为参考点，计算机更喜欢使用从当前时间点到这个参考点的秒数来表示时间
因此，Linux 系统的晶振时间要确保系统时钟与这个参考点的时间保持一致，并提供秒级的精度

上面是这条链路"对外的一面"。真正要理解它，得先分清它内部在回答**两个完全不同的问题**：

1. **现在几点？**——需要一个可靠的、单调的时间读数。
2. **到某个时刻叫醒我**——需要在时间轴上预约一个未来事件。

第一个由 **timekeeping** 回答（配合 clocksource 硬件），第二个由**定时器**（`timer_list` 与 `hrtimer`）回答。
两者是分开的：timekeeping 只在被动累加"已经流逝了多少"，定时器则要主动在某个时刻制造一次中断。

最容易误解的一点是：**内核里没有一个叫"时钟"的东西**。有的是若干个**单调递增的硬件计数器**（clocksource）、
一套把计数器读数换算成纳秒的**定点算术**、一份维护多个"时间轴偏移量"的**记账结构**（timekeeper），
外加几个能"到点产生中断"的**可编程设备**（clockevent）。所谓"系统时间"是这几样东西**算出来**的，
而不是读出来的——这解释了为什么改系统时间不需要动硬件，也解释了为什么 `CLOCK_MONOTONIC` 不会被 NTP 拖慢。

`kernel/time/` 目录就是这条链路的全部实现，约 60 个文件、两万余行：

| 文件 | 职责 |
|---|---|
| `timekeeping.c` | 时间基准：timekeeper 结构、cycles→ns 换算、`ktime_get` 家族 |
| `clocksource.c` / `clockevents.c` | 两类硬件的注册、择优与看门狗 |
| `hrtimer.c` | 高精度定时器（红黑树 + 独立中断） |
| `timer.c` | 低精度定时器（`timer_list` + 九层时间轮） |
| `tick-*.c` | 节拍：`tick-common` / `tick-sched`（NO_HZ）/ `tick-broadcast` / `tick-oneshot` |
| `timer_migration.c` | 空闲 CPU 上的全局定时器迁移 |
| `ntp.c` / `time.c` | NTP 校正注入与 `adjtimex` 系统调用 |
| `posix-timers.c` / `itimer.c` / `alarmtimer.c` | 用户态定时器接口 |
| `namespace.c` | time namespace（时钟虚拟化） |

## 三类硬件：clocksource / clockevent / RTC

这三者的分工必须先分清，否则后面所有机制都会绕晕：

| | clocksource | clockevent | RTC |
|---|---|---|---|
| 方向 | 读取"已经过了多久" | 编程"多久后叫我" | 断电后继续走 |
| 典型硬件 | TSC、HPET、ACPI_PM、arm 的 arch_timer | 本地 APIC timer、arm arch_timer 的中断侧 | CMOS RTC |
| 是否可逆 | 只能单调递增 | 可反复编程 | 可持续计时（带电池） |
| 内核里的角色 | 供 timekeeping 换算 | 供 tick / hrtimer 触发 | **仅 suspend / resume 时使用** |

一个关键事实：**同一块硬件（如 x86 的 TSC、arm 的 arch_timer）往往同时注册为 clocksource 和 clockevent**，
因为"计数器"和"比较器"本来就是同一块硅片的两个寄存器。但内核对它们的评价是独立的，
一个设备可以是优秀的 clocksource 却是普通的 clockevent。

RTC 在整条链路里的存在感极低——日常运行时内核完全不碰它，只在 `timekeeping_suspend` 时读一次、
在 `timekeeping_resume` 时把睡眠时长补进 `offs_boot`。前文提到"RTC 子系统可以设置闹钟"，
那套接口（`/dev/rtc`、`alarmtimer`）确实是单独一条路径，但它的定位是"让系统从挂起中醒来"，
而不是"让进程定时"——后者从来不用 RTC。

## 内核怎么知道"现在"：timekeeping

### 从 cycles 到纳秒：mult/shift

`gettimeofday`系统调用就是用来获取当前时间的，结果以timeval和timezone（时区）结构体的形式返回

gettimeofday调用ktime_get_real_ts64获得以timespec64表示的当前时间然后转化为timeval形式

```c
void ktime_get_real_ts64(struct timespec64 *ts)
{
	struct timekeeper *tk = &tk_core.timekeeper;
	unsigned int seq;
	u64 nsecs;

	WARN_ON(timekeeping_suspended);

	do {
		seq = read_seqcount_begin(&tk_core.seq);

		ts->tv_sec = tk->xtime_sec;
		nsecs = timekeeping_get_ns(&tk->tkr_mono);

	} while (read_seqcount_retry(&tk_core.seq, seq));

	ts->tv_nsec = 0;
	timespec64_add_ns(ts, nsecs);
}
EXPORT_SYMBOL(ktime_get_real_ts64);
```



timekeeping_get_ns

```c
static __always_inline u64 timekeeping_get_ns(const struct tk_read_base *tkr)
{
	return timekeeping_cycles_to_ns(tkr, tk_clock_read(tkr));
}

static inline u64 timekeeping_cycles_to_ns(const struct tk_read_base *tkr, u64 cycles)
{
	/* Calculate the delta since the last update_wall_time() */
	u64 mask = tkr->mask, delta = (cycles - tkr->cycle_last) & mask;

	/*
	 * This detects both negative motion and the case where the delta
	 * overflows the multiplication with tkr->mult.
	 */
	if (unlikely(delta > tkr->clock->max_cycles)) {
		/*
		 * Handle clocksource inconsistency between CPUs to prevent
		 * time from going backwards by checking for the MSB of the
		 * mask being set in the delta.
		 */
		if (delta & ~(mask >> 1))
			return tkr->xtime_nsec >> tkr->shift;

		return delta_to_ns_safe(tkr, delta);
	}

	return ((delta * tkr->mult) + tkr->xtime_nsec) >> tkr->shift;
}
```

```c
static __always_inline void timespec64_add_ns(struct timespec64 *a, u64 ns)
{
	a->tv_sec += __iter_div_u64_rem(a->tv_nsec + ns, NSEC_PER_SEC, &ns);
	a->tv_nsec = ns;
}
```

上面这段代码（`kernel/time/timekeeping.c:940`）在 v7.2.7 上**仍然成立**，一个字没变。它本身就是这套设计的说明书：

- `timekeeping_cycles_to_ns()` 的核心是最后一行 **`((delta * tkr->mult) + tkr->xtime_nsec) >> tkr->shift`**。
  为什么写成定点乘法加移位，而不是 `delta / freq * NSEC_PER_SEC`？
  因为**除法在每秒被调用上亿次的时间读数路径上太贵**，定点乘法加移位只要两条指令。
  `mult` 与 `shift` 由 `clocks_calc_mult_shift()`（`clocksource.c:61`）在注册时算好，
  它枚举移位量直到 `(to << sft) / from` 不溢出，从而在精度与范围之间取平衡。
- `max_cycles` 是防溢出的护栏：`clocks_calc_max_nsecs()`（`clocksource.c:1043`）用
  `do_div(max_cycles, mult + maxadj)` 反推出"多大的 cycles 差还能安全乘进 64 位"。
  一旦超过，说明计数器异常跳变（或发生了负数走），此时按情况退回 `xtime_nsec >> shift` 或 `delta_to_ns_safe()`。
- `delta = (cycles - tkr->cycle_last) & mask` 里的按位与，是利用**无符号环绕**自动处理计数器回绕——
  这一招与 jiffies 的 `time_after()` 是同一思路（见下文「jiffies：粗粒度的时间货币」）。

### 五个"现在"与 ktime_get 家族

timekeeper 内部维护的不是一个时间，而是**一组共享同一硬件计数器、但偏移量不同的时间轴**：

| 时钟 | 语义 | 睡眠期间 | NTP 可调 |
|---|---|---|---|
| `CLOCK_REALTIME` | 墙上时间（1970 起） | 不走 | 可（可被 settimeofday 跳变） |
| `CLOCK_MONOTONIC` | 单调递增，起点是开机 | **冻结** | 不可（只可能变慢，绝不会变小） |
| `CLOCK_BOOTTIME` | 同 MONOTONIC，但**包含** suspend 时长 | 走 | 不可 |
| `CLOCK_MONOTONIC_RAW` | 未经 NTP 校正的原始计数 | 冻结 | 完全不可 |
| `CLOCK_TAI` | 国际原子时（无闰秒） | 冻结 | 可 |

它们之间的差异实现上**只是几个 offset**：`offs_real`、`offs_boot`、`offs_tai`，都相对 MONOTONIC。
所以"`CLOCK_MONOTONIC` 睡眠期间冻结"，在源码里体现为"睡眠时不推进 mono 的 base，
而是把时长加进 `offs_boot`"。

对外 API 家族（`kernel/time/timekeeping.c`）：

| API | 用途 | 可在 NMI 调用 |
|---|---|---|
| `ktime_get()` / `ktime_get_ts64()` | 读 MONOTONIC | 否 |
| `ktime_get_real_ts64()` | 读 REALTIME | 否 |
| `ktime_get_boottime_ts64()` | 读 BOOTTIME | 否 |
| `ktime_get_raw()` | 读 RAW | 否 |
| `ktime_get_coarse*()` | 粗粒度版本，精度 = 1 tick | 否 |
| `ktime_get_mono_fast_ns()` 等 `_fast_ns` 系列 | 同语义，**NMI 安全** | **是** |

`coarse` 版本快的原因很直白：它在每个 tick 的 `update_wall_time()` 里就把结果算好存进
`tk_xtime_coarse`（`tk_update_coarse_nsecs()`，`timekeeping.c:230`），读的时候直接取，
既不读硬件也不做乘法——代价是精度退化到一个 tick。

### 读侧为什么不用锁：shadow 与 latch seqcount

时间读数每秒被调用上百万次，如果每次都抢锁，整个系统都会被拖垮。内核用了两层技巧让读侧**完全无锁**。

**第一层是 shadow timekeeper。** `struct tk_data` 里有两份 timekeeper：

```c
/* kernel/time/timekeeping.c:48 */
struct tk_data {
	seqcount_raw_spinlock_t	seq;
	struct timekeeper	timekeeper;
	struct timekeeper	shadow_timekeeper;
	raw_spinlock_t		lock;
} ____cacheline_aligned;
```

所有更新都先在 `shadow_timekeeper` 上改，改完在 `timekeeping_update_from_shadow()`
（`timekeeping.c:789`）里一把 `memcpy` 提交。源码注释（`timekeeping.c:827`）解释了为什么用 memcpy 而不是换指针：
换指针会破坏读者侧的缓存行布局（正式结构与读侧共享同一 cacheline），还多一次间接寻址。

**第二层是 latch seqcount。** 给 NMI 用的快路径走的是另一份数据：

```c
/* kernel/time/timekeeping.c:105 */
struct tk_fast {
	seqcount_latch_t	seq;
	struct tk_read_base	base[2];
};
```

latch 的语义是：写者交替改 `base[0]` / `base[1]`，读者按 `seq & 0x01` 选当前稳定的那一半：

```c
/* kernel/time/timekeeping.c:499 */
do {
	seq = read_seqcount_latch(&tkf->seq);
	tkr = tkf->base + (seq & 0x01);
	now = ktime_to_ns(tkr->base);
	now += timekeeping_get_ns(tkr);
} while (read_seqcount_latch_retry(&tkf->seq, seq));
```

即使 NMI 在写者改到一半时打进来，它也只会读到另一半**完整的旧副本**，绝不会读到撕裂的中间态。
而普通 `ktime_get()` 用的是 `tk_core.seq`（`seqcount_raw_spinlock_t`）——它同样不阻塞读者，
但 NMI 若恰好打断写者会导致读者自旋等待，**这就是 NMI 里必须用 `_fast_ns` 系列的唯一原因**。

### 看门狗：识别撒谎的时钟源

clocksource 是硬件，会坏、会被虚拟化环境伪造、会因固件 bug 频率漂移。内核的应对是
**拿两个时钟源互相对表**：`clocksource_watchdog`（`clocksource.c:643`）每 `HZ/2` 跑一次，
比较主时钟源与看门狗时钟源在同一时间窗内走过的 cycles 数。

v7.2.7 的判定阈值已经不再是老版本的单一 `WATCHDOG_THRESHOLD`，而是按**频率偏差**分级：

```c
/* kernel/time/clocksource.c:150 */
/* Shift values to calculate the approximate $N ppm of a given delta. */
#define SHIFT_500PPM			11
#define SHIFT_4000PPM			8

/* Number of attempts to read the watchdog */
#define WATCHDOG_FREQ_RETRIES		3

/* Five reads local and remote for inter CPU skew detection */
#define WATCHDOG_REMOTE_MAX_SEQ		10
```

除频率偏差外，还有一类更隐蔽的失效：**跨 CPU 读取不一致**（不同核读同一 counter 得到不同值），
判据是 `delta > cs->max_raw_delta`（`clocksource.c:1083`，约 `0.875 × mask`）。

一旦判定不可靠，`clocksource_mark_unstable()`（`clocksource.c:226`）会清掉
`CLOCK_SOURCE_VALID_FOR_HRES` 与看门狗标志、置上 `CLOCK_SOURCE_UNSTABLE`，
随后 `clocksource_select_fallback()` 把主时钟源降级——**现实中 TSC 在部分虚拟机与固件上是重灾区**，
被降级后系统退回 HPET 或 ACPI_PM，典型表现是"某台虚拟机里 `clock_gettime` 变慢且抖动变大"。

### aux clocks

v7.2.7 有一个此前没有的结构：**多个 timekeeper**。

```c
/* kernel/time/timekeeping.c:55 */
static struct tk_data timekeeper_data[TIMEKEEPERS_MAX];

/* The core timekeeper */
#define tk_core		(timekeeper_data[TIMEKEEPER_CORE])
```

`enum timekeeper_ids`（`include/linux/timekeeper_internal.h:17-27`）在 `TIMEKEEPER_CORE` 之后
还留了 `TIMEKEEPER_AUX_FIRST` 到 `TIMEKEEPER_AUX_LAST` 一段，由 `CONFIG_POSIX_AUX_CLOCKS` 控制，
`tk_is_aux()`（`timekeeping.c:66`）判断一个 timekeeper 是否属于 aux。

它把 **PTP 硬件时钟之类的独立时间源**作为独立 POSIX 时钟暴露给用户态（`CLOCK_AUX + n`），
而对 aux 的校准只动它自己的 `offs_aux`（`tk_update_aux_offs()`，`timekeeping.c:87`），
**不会影响 core 时钟源的单调性**。这是个很年轻的设计，排障时看到 `aux` 字样不必惊讶。

## 节拍：jiffies 与 tick

### jiffies：粗粒度的时间货币

The following defines establish the engineering parameters of the PLL model.
The HZ variable establishes the timer interrupt frequency, 100 Hz for the SunOS kernel, 256 Hz for the Ultrix kernel and 1024 Hz for the OSF/1 kernel.
The SHIFT_HZ define expresses the same value as the nearest power of two in order to avoid hardware multiply operations.

```c
// uapi/asm-generic/param.h
#ifndef HZ
#define HZ 100

```

上面是用户态可见的 `HZ`（`include/uapi/asm-generic/param.h`，实际定义为 `__USER_HZ = 100`）——
它之所以必须是 100，是因为 `sysconf(_SC_CLK_TCK)` 等老接口把它暴露给了用户态，**不能随内核配置变**。
内核自己的节拍频率是另一个配置项：

```
kernel/Kconfig.hz:8:	default HZ_250
```

候选为 `HZ_100 / HZ_250 / HZ_300 / HZ_1000`，**默认 250**，即一个 jiffy 是 4ms。
提高 HZ 并不会让细粒度定时变准（那是 hrtimer 的活），只会增加中断开销——帮助文本里明确写着
100Hz 对 NUMA 服务器更友好。

`SHIFT_HZ` 这张表在 v7.2.7 里仍然存在（`include/linux/jiffies.h`），作用是把 `HZ` 取成最接近的 2 的幂，
好在换算时用移位代替乘法：

```c
// linux/jiffies.h
#if HZ >= 12 && HZ < 24
# define SHIFT_HZ	4
#elif HZ >= 24 && HZ < 48
# define SHIFT_HZ	5
/* ... 逐级放大，到 6144~12288 为 13 ... */
#else
# error Invalid value of HZ.
#endif
```

The 64-bit value is not atomic - you MUST NOT read it without sampling the sequence number in jiffies_lock. get_jiffies_64() will do this for you as appropriate.

```c
extern u64 __cacheline_aligned_in_smp jiffies_64;
extern unsigned long volatile __cacheline_aligned_in_smp __jiffy_arch_data jiffies;

#if (BITS_PER_LONG < 64)
u64 get_jiffies_64(void);
#else
static inline u64 get_jiffies_64(void)
{
	return (u64)jiffies;
}
#endif


__visible u64 jiffies_64 __cacheline_aligned_in_smp = INITIAL_JIFFIES;
```

32 位平台上 `jiffies` 与 `jiffies_64` **低 32 位共享同一地址**（`jiffies.h:75-79`），
所以要原子读 64 位就得靠 seqlock（`jiffies.c:42-58`）；64 位平台直接别名即可。

Have the 32 bit jiffies value wrap 5 minutes after boot so jiffies wrap bugs show up earlier.

```c
#define INITIAL_JIFFIES ((unsigned long)(unsigned int) (-300*HZ))
```

**初值是负数，开机 5 分钟就让 32 位 jiffies 回绕一次**——这是故意的，让所有忘记处理回绕的代码在启动阶段就暴露。

所以比较两个 jiffies 必须用环绕语义的宏，不能直接写 `a > b`：

```c
/* include/linux/jiffies.h:123 */
#define time_after(a,b)		\
	(typecheck(unsigned long, a) && \
	 typecheck(unsigned long, b) && \
	 ((long)((b) - (a)) < 0))
```

转成有符号做差，就能在模 2³² 的环上正确判序。

### tick 中断与 tick 设备

每个 CPU 有一个 tick 设备，由 `tick_check_new_device()`（`tick-common.c:326`）从注册的 clockevent 里挑：
优先支持 oneshot 的、其次 rating 高的、且本 CPU 本地的优于非本地的。

周期模式下每个 tick 走 `tick_periodic()`（`tick-common.c:86`），它做三件事：
`do_timer(1)` 推进 jiffies、`update_wall_time()` 推进时间基准、`update_process_times()` 更新进程记账。
而 `do_timer()` 如今已经非常轻：

```c
/* kernel/time/timekeeping.c:2785 */
void do_timer(unsigned long ticks)
{
	jiffies_64 += ticks;
	calc_global_load();
}
```

**这里有历史包袱要看清楚**：`update_wall_time()` 与 `update_process_times()` 已经从 `do_timer` 里拆出去了。
推进 jiffies 的逻辑也独立成了 `tick_do_update_jiffies64()`（`tick-sched.c:57`），
它把"推进 jiffies 的职责"与"哪个 CPU 的 tick 在跑"**解耦**：职责 CPU（`tick_do_timer_cpu`）失联后
任意 CPU 都能接管；若某 CPU 的 tick 卡住，`tick_limited_update_jiffies64()` 会配合
`MAX_STALLED_JIFFIES = 5` 强制补推进，避免 jiffies 长期停滞。

### NO_HZ：什么时候能停

| 模式 | 行为 | 依赖 |
|---|---|---|
| `NO_HZ_IDLE`（默认） | 只在 CPU 空闲时停 tick | 无额外要求 |
| `NO_HZ_FULL` | 运行时也尝试停 tick | SMP、context tracking，通常配 `nohz_full=` 与 CPU 隔离 |

停 tick 的判据分别是 `can_stop_idle_tick()`（`tick-sched.c:1097`）与 `can_stop_full_tick()`（`:381`），
前者要求无 `need_resched()`、无待处理的 idle softirq，且**不能是 do_timer 职责 CPU**：

```c
/* kernel/time/tick-sched.c:1110 */
if (tick_nohz_full_enabled()) {
	int tick_cpu = READ_ONCE(tick_do_timer_cpu);

	/*
	 * Keep the tick alive to guarantee timekeeping progression
	 * if there are full dynticks CPUs around
	 */
	if (tick_cpu == cpu)
		return false;
	...
}
```

也就是说：**即使所有 CPU 都进了 dynticks，也必须留一颗 CPU 保持周期 tick 来推进 jiffies。**

### 停掉之后：hrtimer 模拟 tick

tick 停了，"再过 4ms 推进 jiffies"这件事由谁保证？答案是用一个 per-CPU 的 hrtimer 顶替：

```c
/* kernel/time/tick-sched.c:1495 */
void tick_setup_sched_timer(bool hrtimer)
{
	struct tick_sched *ts = this_cpu_ptr(&tick_cpu_sched);

	/* Emulate tick processing via per-CPU hrtimers: */
	hrtimer_setup(&ts->sched_timer, tick_nohz_handler, CLOCK_MONOTONIC, HRTIMER_MODE_ABS_HARD);

	if (IS_ENABLED(CONFIG_HIGH_RES_TIMERS) && hrtimer)
		tick_sched_flag_set(ts, TS_FLAG_HIGHRES);

	/* Get the next period (per-CPU) */
	hrtimer_set_expires(&ts->sched_timer, tick_init_jiffy_update());

	/* Offset the tick to avert 'jiffies_lock' contention. */
	if (sched_skew_tick) {
		u64 offset = TICK_NSEC >> 1;
```

两个细节值得注意：mode 是 **`HRTIMER_MODE_ABS_HARD`**（tick 是整套时间体系的底座，
不能被推到软中断去，否则时间推进会延迟）；`sched_skew_tick` 把各 CPU 的 tick 错开半个周期，
**专门用来避免所有 CPU 抢同一把 `jiffies_lock`**。

停 tick 之后由谁唤醒，交给 `tick_nohz_next_event()`（`tick-sched.c:820`）配合
`get_next_timer_interrupt()`（`timer.c:2291`）算出"最近一个将到期的定时器或调度时刻"，
再把本地 clockevent 编程到那一刻。

### 定时器迁移与 tick broadcast

tick 停下会带来两个新问题。

**问题一：空闲 CPU 上的全局定时器谁来管？** 定时器可以挂在任意 CPU 上，但如果那颗 CPU 已经进入深空闲，
它的定时器就没人触发了。`timer_migration.c` 解决这个：它维护一棵 `tmigr_group` / `tmigr_cpu` 的层级树
（每层最多 `TMIGR_CHILDREN_PER_GROUP = 8` 个子节点，`timer_migration.h:6` 要求必须是 2 的幂），
CPU 进入空闲时调 `tmigr_cpu_deactivate()` 把本 CPU 的最近到期事件向上层传播，
由仍在运行的 CPU 代为触发（`run_timer_softirq` 里的 `tmigr_handle_remote()` 就是接手点）。

**注意：这个特性在本树里没有对应的 Kconfig 条目**——遍查 `kernel/time/Kconfig` 与全树 `Kconfig*`
都找不到 `config TIMER_MIGRATION`，只有 `!CONFIG_TIMER_MIGRATION` 下的空桩（`timer_migration.h:163`）。
也就是说它**默认编入**、无法通过配置关掉，只能用 `tmigr_exclude_isolated` 这个 static key
（`timer_migration.c:436`，默认关）控制"是否排除隔离 CPU"。

**问题二：深空闲时本地 timer 直接断电了（`CLOCK_EVT_FEAT_C3STOP`），谁来叫醒？**
这是 tick broadcast 的职责：由一颗共享广播设备统一编程，到点向相关 CPU 发中断。
`tick-broadcast-hrtimer.c` 还实现了一个"假广播设备"——用 `struct hrtimer bctimer` 顶替
（rating 为 0、带 `CLOCK_EVT_FEAT_HRTIMER`），在没有独立广播硬件时兜底。

### tick 依赖：谁有权说"别停"

停 tick 不是无条件的。任何子系统都可以声明"我现在需要 tick"，机制是四层掩码
（全局 `tick_dep_mask`、per-CPU `ts->tick_dep_mask`、per-task、per-signal）：

```c
/* include/linux/tick.h:111 */
enum tick_dep_bits {
	TICK_DEP_BIT_POSIX_TIMER	= 0,
	TICK_DEP_BIT_PERF_EVENTS	= 1,
	TICK_DEP_BIT_SCHED		= 2,
	TICK_DEP_BIT_CLOCK_UNSTABLE	= 3,
	TICK_DEP_BIT_RCU		= 4,
	TICK_DEP_BIT_RCU_EXP		= 5
};
```

`check_tick_dependency()`（`tick-sched.c:341`）在 `can_stop_full_tick()` 里把这四层全查一遍，
**任何一层置位就禁止停 tick**。其中 `TICK_DEP_BIT_POSIX_TIMER` 的存在尤其说明问题：
CPU 时钟定时器（见后文）依赖 tick 推进，只要有人在用它，tick 就不能停。

## 预约未来时刻：两类定时器

### init_timers

原文这一节从初始化入口讲起。**注意函数已经改名**：

```c
// kernel/time/timer.c —— 旧版本
void __init init_timers(void)
{
	init_timer_cpus();
	posix_cputimers_init_work();
	open_softirq(TIMER_SOFTIRQ, run_timer_softirq);
}
```

v7.2.7 里这个函数叫 **`timers_init()`**（`timer.c:2575`），内容不变：

```c
void __init timers_init(void)
{
	init_timer_cpus();
	posix_cputimers_init_work();
	open_softirq(TIMER_SOFTIRQ, run_timer_softirq);
}
```

open [softirq](/docs/CS/OS/Linux/Interrupt.md?id=softirq)

软中断处理函数同样有两处变化——**base 从两个变成三个，且 softirq 回调不再接收参数**：

```c
// kernel/time/timer.c:2401（v7.2.7）
static __latent_entropy void run_timer_softirq(void)
{
	run_timer_base(BASE_LOCAL);
	if (IS_ENABLED(CONFIG_NO_HZ_COMMON)) {
		run_timer_base(BASE_GLOBAL);
		run_timer_base(BASE_DEF);

		if (is_timers_nohz_active())
			tmigr_handle_remote();
	}
}
```

对比旧版本：

```c
static __latent_entropy void run_timer_softirq(struct softirq_action *h)
{
	struct timer_base *base = this_cpu_ptr(&timer_bases[BASE_STD]);

	__run_timers(base);
	if (IS_ENABLED(CONFIG_NO_HZ_COMMON))
		__run_timers(this_cpu_ptr(&timer_bases[BASE_DEF]));
}
```

三处差异值得记：

| | 旧版本 | v7.2.7 |
|---|---|---|
| 回调签名 | `void f(struct softirq_action *h)` | **`void f(void)`**，`open_softirq` 声明为 `void (*action)(void)`（`interrupt.h:607`） |
| timer base | `BASE_STD` / `BASE_DEF` 两个 | **`BASE_LOCAL` / `BASE_GLOBAL` / `BASE_DEF` 三个**（`timer.c:194-197`） |
| 迁移接入 | 无 | `tmigr_handle_remote()` 直接在这里接手远端定时器 |

三个 base 的分派规则在 `timer.c:916-930`：
**`TIMER_PINNED` 的进 `BASE_LOCAL`（绑 CPU）、deferrable 的进 `BASE_DEF`、其余默认进 `BASE_GLOBAL`**。
`BASE_GLOBAL` 是新增的一档——它存在的意义正是配合定时器迁移：非 pinned 的定时器允许被别的 CPU 代跑，
所以可以和 `BASE_LOCAL` 分开管理，迁移时只动 global 那一份。

数据结构本身没变（只是从 `include/linux/timer.h` 挪到了 `include/linux/timer_types.h`）：

```c
// include/linux/timer_types.h
struct timer_list {
	/*
	 * All fields that change during normal runtime grouped to the
	 * same cacheline
	 */
	struct hlist_node	entry;
	unsigned long		expires;
	void			(*function)(struct timer_list *);
	u32			flags;

#ifdef CONFIG_LOCKDEP
	struct lockdep_map	lockdep_map;
#endif
};
```

它的索引结构是**时间轮**，定义在 `kernel/time/timer.c` 顶部（不是 `include/linux/timer.h`）：

```c
/* kernel/time/timer.c:167 */
#define LVL_BITS	6
#define LVL_SIZE	(1UL << LVL_BITS)
#define LVL_MASK	(LVL_SIZE - 1)
#define LVL_OFFS(n)	((n) * LVL_SIZE)
...
# define LVL_DEPTH	9
...
#define WHEEL_TIMEOUT_CUTOFF	(LVL_START(LVL_DEPTH))
#define WHEEL_TIMEOUT_MAX	(WHEEL_TIMEOUT_CUTOFF - LVL_GRAN(LVL_DEPTH - 1))
```

每层 64 个桶、共 9 层，**层与层之间的粒度按 `LVL_CLK_SHIFT` 逐级放大**。
这解决了经典时间轮的根本痛点：超长超时不需要级联重排——第 n 层的每个桶本身就代表一个指数级放大的时间跨度，
`LVL_DEPTH = 9` 那一层单桶跨度已是几十天量级，`WHEEL_TIMEOUT_MAX` 之上直接钳到最大值。

关键链路：`calc_index()`（`:524`）算桶位 → `internal_add_timer()`（`:639`）入桶 →
`forward_timer_base()`（`:971`）推进基准（**只前不后**，因为时间不能倒流）→
`collect_expired_timers()`（`:1807`）收集到期 → `expire_timers()`（`:1766`）执行回调。

这个接口的局限很明确：**精度只有 jiffy，且所有定时器共用一个软中断上下文**——
所以需要毫秒以下精度或精度隔离的场景必须用 hrtimer。

### 高精度：hrtimer

hrtimer 的核心是**每个 CPU 每个时钟基一棵红黑树**：

```c
/* include/linux/hrtimer_defs.h:38 */
enum hrtimer_base_type {
	HRTIMER_BASE_MONOTONIC,
	HRTIMER_BASE_REALTIME,
	HRTIMER_BASE_BOOTTIME,
	HRTIMER_BASE_TAI,
	HRTIMER_BASE_MONOTONIC_SOFT,
	HRTIMER_BASE_REALTIME_SOFT,
	HRTIMER_BASE_BOOTTIME_SOFT,
	HRTIMER_BASE_TAI_SOFT,
	HRTIMER_MAX_CLOCK_BASES
};
```

**基础数是 8 不是 4**：`HRTIMER_MAX_CLOCK_BASES` 是枚举末项、值为 8——四个"硬基"加四个"软基"。
软基不是额外的时钟，而是**同一批时钟在软中断上下文里的副本**，初始化时靠除半定位：

```c
/* kernel/time/hrtimer.c:1901 */
base = softtimer ? HRTIMER_MAX_CLOCK_BASES / 2 : 0;
base += hrtimer_clockid_to_base(clock_id);
```

原文的结构定义已经过期了：

```c
// include/linux/hrtimer.h —— 旧版本
struct hrtimer {
	struct timerqueue_node		node;
	ktime_t				_softexpires;
	enum hrtimer_restart		(*function)(struct hrtimer *);
	struct hrtimer_clock_base	*base;
	u8				state;
	u8				is_rel;
	u8				is_soft;
	u8				is_hard;
};
```

v7.2.7 的现状（`include/linux/hrtimer_types.h:41`）：

```c
struct hrtimer {
	struct timerqueue_linked_node	node;
	struct hrtimer_clock_base	*base;
	bool				is_queued;
	bool				is_rel;
	bool				is_soft;
	bool				is_hard;
	bool				is_lazy;
	ktime_t				_softexpires;
	enum hrtimer_restart		(*__private function)(struct hrtimer *);
};
```

四处差异，其中一处是理解上的关键：

| | 旧版本 | v7.2.7 |
|---|---|---|
| 树节点类型 | `struct timerqueue_node` | **`struct timerqueue_linked_node`**（带父指针，删除时不必从根搜索） |
| 状态表示 | `u8 state` 位掩码 | **`bool is_queued`**，其余拆成独立 bool |
| 新增字段 | — | `is_lazy`（对应 `HRTIMER_MODE_LAZY_REARM`） |
| "运行中"状态 | 在 `state` 里 | **不在 hrtimer 上，而是 base 的 `running` 指针**（`hrtimer_defs.h:33`） |

最后一行是要点：在新结构里 **"运行中"不是定时器自身的属性，而是它所属 base 的一个指针**。

### SOFT 与 HARD

回调在什么上下文执行，由 mode 决定：

```c
/* include/linux/hrtimer.h:35 */
	HRTIMER_MODE_ABS	= 0x00,
	HRTIMER_MODE_REL	= 0x01,
	HRTIMER_MODE_PINNED	= 0x02,
	HRTIMER_MODE_SOFT	= 0x04,
	HRTIMER_MODE_HARD	= 0x08,
	HRTIMER_MODE_LAZY_REARM	= 0x10,
```

默认行为取决于内核是否开了 `PREEMPT_RT`：

```c
/* kernel/time/hrtimer.c:1886 */
if (IS_ENABLED(CONFIG_PREEMPT_RT) && !(mode & HRTIMER_MODE_HARD))
	softtimer = true;
```

- **普通内核**：不指定 mode 就是硬中断上下文（保守、延迟最低）。
- **PREEMPT_RT**：不指定就一律挪到软中断（RT 上即软中断线程）——注释写明了理由：
  "for latency reasons and because the callbacks can invoke functions which might sleep on RT"。
  只有显式标 `HRTIMER_MODE_HARD` 的（如 tick 的 `sched_timer`）才留在硬中断。

`HRTIMER_MODE_LAZY_REARM` 值得单独记，源码注释把动机讲得很清楚：

> Avoid reprogramming if the timer was the first expiring timer and is moved into the future.
> Special mode for the HRTICK timer to avoid extensive reprogramming of the hardware,
> which is expensive in virtual machines. Risks a pointless expiry, but that's better than
> reprogramming on every context switch.

这是**为虚拟机优化的"懒得重编程"模式**——宁可多一次空到期，也不要在每次上下文切换时都敲硬件。
唯一使用者是调度器的 HRTICK（见 [调度](/docs/CS/OS/Linux/proc/sche.md)）。

### 一次到期的完整路径

硬中断侧入口是 `hrtimer_interrupt()`（`hrtimer.c:2192`）：

```c
retry:
	cpu_base->deferred_rearm = true;
	/*
	 * Set expires_next to KTIME_MAX, which prevents that remote CPUs queue
	 * timers while __hrtimer_run_queues() is expiring the clock bases.
	 * Timers which are re/enqueued on the local CPU are not affected by
	 * this.
	 */
	cpu_base->expires_next = KTIME_MAX;

	if (!ktime_before(now, cpu_base->softirq_expires_next)) {
		cpu_base->softirq_expires_next = KTIME_MAX;
		cpu_base->softirq_activated = true;
		raise_timer_softirq(HRTIMER_SOFTIRQ);
	}

	__hrtimer_run_queues(cpu_base, now, flags, HRTIMER_ACTIVE_HARD);
```

两个设计值得注意：

1. **`deferred_rearm` + `expires_next = KTIME_MAX`**：跑回调期间**主动禁止远端 CPU 往这棵树上排队**，
   避免边遍历边被插入带来的复杂度；本地 CPU 自己的重排不受影响。
2. **软基定时器在这里只是被"举手"**：满足条件就 `raise_timer_softirq(HRTIMER_SOFTIRQ)`，
   真正执行交给 `hrtimer_run_softirq()`（`hrtimer.c:2110`）。

然后是防死循环：

```c
/* kernel/time/hrtimer.c:2230 */
	/*
	 * We need to prevent that we loop forever in the hrtiner interrupt
	 * routine. We give it 3 attempts to avoid overreacting on some
	 * spurious event.
	 */
	now = hrtimer_update_base(cpu_base);
	expires_next = hrtimer_update_next_event(cpu_base);
	cpu_base->hang_detected = false;
	if (expires_next < now) {
		if (++retries < 3) {
			cpu_base->nr_retries++;
			goto retry;
		}
		/* ... nr_hangs++; hang_detected = true; ... */
	}
```

**只重试 3 次**。超过就认定发生 hang（通常是回调太长，或在虚拟机里被调度出去了），
置上 `hang_detected` 后放弃本轮，剩余工作留给下一次中断。代价是被跳过的定时器晚一个周期执行，
收益是不会在中断里死循环。

回调执行在 `__run_hrtimer()`（`:1997`）：先把自己挂到 `base->running`，**然后放下 base 锁**再执行回调，
所以回调里可以安全地 `hrtimer_start()` 重排自己乃至同一棵树上的其它定时器。
走完回调后，只有"返回 `HRTIMER_RESTART` 且当前未重新入队"才重新插入（`:2054`）——
这道判断正是用来兜住"回调里已经自己重排过"的情况。

### 时钟被改之后：clock_was_set

`settimeofday` 把 REALTIME 向前跳了一小时，那些按**绝对 REALTIME** 排的定时器就会立刻全部到期——
这显然不对。处理机制是 `clock_was_set()`（`hrtimer.c:975`）：重算各基 offset，
并让每个 CPU 重新评估最早到期定时器。由于这件事不能在中断上下文做，
另有 `clock_was_set_delayed()`（`:1018`）把它丢给 workqueue。

成本优化在 `update_needs_ipi()`（`:902`）：先读每个 CPU 的 `clock_was_set_seq`，
若已跟上说明远端处理过了，**省掉一次 IPI**；只对真正需要重编程的 CPU 发 `retrigger_next_event`。

### 睡眠是怎么实现的

`nanosleep` 不是单独一套机制，它就是"建一个 hrtimer 把自己唤醒"：

```c
struct hrtimer_sleeper t;
hrtimer_init_sleeper_on_stack(&t, clock_id, mode);
hrtimer_set_expires_range_ns(&t.timer, *expires, delta);
hrtimer_sleeper_start_expires(&t, mode);
...
hrtimer_cancel(&t.timer);
destroy_hrtimer_on_stack(&t.timer);
```

`sleeper->task` 指向当前任务，`hrtimer_wakeup()`（`:2295`）到点在回调里 `wake_up_process()`。
这套代码在 v7.x 位于 `kernel/time/sleep_timeout.c`（`schedule_hrtimeout_range*`，`:189`），
**不在 `kernel/sched/core.c`**——用 `schedule_timeout` 去找会找错地方。

两个常被问到的细节：

- **绝对定时器被打断后不重启**：`hrtimer_nanosleep()` 对绝对时间返回 `-ERESTARTNOHAND`（`hrtimer.c:2458`），
  因为绝对时刻已过，重启没有意义；只有相对时间才设 restart block。
- **栈上的 hrtimer 必须 `hrtimer_cancel` 后再 `destroy_hrtimer_on_stack`**，
  否则栈帧返回后定时器若还挂着，回调就会踩到已失效的栈内存。

`slack`（`hrtimer_set_expires_range_ns` 的 `delta` 参数）用于**合并唤醒**：
把到期时刻放到 `[expires, expires+slack]` 区间内任意一点，让相近的定时器一起醒来，
CPU 因而能多睡一会儿。`usleep_range()` 的区间参数最终就是落到这里。

## 用户态看到的接口

原文列出的三个结构体是这一层的"数据契约"，v7.2.7 与它们完全一致：

```c
// include/uapi/linux/time.h
#ifndef __KERNEL__
#ifndef _STRUCT_TIMESPEC
#define _STRUCT_TIMESPEC
struct timespec {
	__kernel_old_time_t	tv_sec;		/* seconds */
	long			tv_nsec;	/* nanoseconds */
};
#endif

struct timeval {
	__kernel_old_time_t	tv_sec;		/* seconds */
	__kernel_suseconds_t	tv_usec;	/* microseconds */
};

struct itimerspec {
	struct timespec it_interval;/* timer period */
	struct timespec it_value;	/* timer expiration */
};

struct itimerval {
	struct timeval it_interval;/* timer interval */
	struct timeval it_value;	/* current value */
};
#endif

struct timezone {
	int	tz_minuteswest;	/* minutes west of Greenwich */
	int	tz_dsttime;	/* type of dst correction */
};
```

### clock_gettime 为什么不进内核

因为内核把算"现在"所需的那几个数**直接映射进了用户地址空间**（VVAR 页）：
`update_vsyscall`（`kernel/time/vsyscall.c:18`）把 `tkr_mono` / `tkr_raw` 的
`cycle_last` / `mask` / `mult` / `shift` 拷进 vDSO 数据页。用户态用同一套
`(delta * mult) >> shift` 公式、读取**同一个硬件计数器**（TSC 可从用户态直接 `rdtsc`），
再套上内核写进页里的 seqlock 保护，就得到了时间——**全程零系统调用**。

但这条快路径有明确边界：

- **支持的 clockid**（`include/vdso/datapage.h:35`）：REALTIME、MONOTONIC、BOOTTIME、TAI
  及它们的 COARSE 变体、MONOTONIC_RAW、以及 aux clocks。
- **必然回退到系统调用的**：`CLOCK_PROCESS_CPUTIME_ID` / `CLOCK_THREAD_CPUTIME_ID`（CPU 时钟）、
  `CLOCK_*_ALARM`（alarmtimer）、动态 POSIX 时钟（PTP）。
- **时钟源不支持时也回退**：当 `clock_mode == VDSO_CLOCKMODE_NONE`（例如时钟源被看门狗降级成 HPET）时，
  用户态读不到可用的计数器，只能进内核。

所以"`clock_gettime` 永不进内核"是错的，**它的开销取决于当前时钟源**。
现在 `getrandom` 也走了 vDSO（`__vdso_getrandom`）。

### 四种定时唤醒接口

| 接口 | 载体 | 精度 | 到期动作 | 适用 |
|---|---|---|---|---|
| `setitimer` | `signal_struct` 内 | REAL 高 / VIRT、PROF 受 tick 限制 | 信号（SIGALRM / SIGVTALRM / SIGPROF） | 老代码，每进程仅 3 个 |
| POSIX `timer_create` | `k_itimer` 哈希表 | hrtimer 级 | 信号或 `SIGEV_NONE` | 每进程多个、可选时钟 |
| `timerfd` | fd + 等待队列 | hrtimer 级 | **fd 可读** | 事件循环超时（无信号） |
| `alarmtimer` | `/dev/alarm` | hrtimer 级 | 可唤醒 suspend | Android、RTC 唤醒 |

**itimer 其实是两套实现**：`ITIMER_REAL` 建一个 hrtimer（`signal->real_timer`），
而 `ITIMER_VIRTUAL` / `ITIMER_PROF` 走 CPU 时间记账（`set_cpu_itimer()`），精度直接受 tick 限制——
所以前者的精度可达微秒，后者的抖动是一个 tick 量级。

**timerfd 是给事件循环用的**，它的到期处理很简洁：

```c
/* fs/timerfd.c:58 */
static void __timerfd_triggered(struct timerfd_ctx *ctx)
{
	lockdep_assert_held(&ctx->wqh.lock);

	ctx->expired = 1;
	ctx->ticks++;
	wake_up_locked_poll(&ctx->wqh, EPOLLIN);
}
```

**`ticks` 只增不减，只有 `read()` 才清零**——所以"用户一直不 read 导致 tick 丢失"不会发生，
丢的只是"次数被合并显示"。另外这个函数**不重新装载定时器**（注释在 `:67`），
重装推迟到下一次被访问时，这是一处省开销的惰性设计。

**POSIX timer 的到期**发生在 hrtimer 回调里（注释在 `posix-timers.c:370` 特意说明
"the HRTIMER interrupt (soft interrupt on RT kernels)"）：

```c
/* kernel/time/posix-timers.c:375 */
static enum hrtimer_restart posix_timer_fn(struct hrtimer *timer)
{
	struct k_itimer *timr = container_of(timer, struct k_itimer, it.real.timer);

	guard(spinlock_irqsave)(&timr->it_lock);
	posix_timer_queue_signal(timr);
	return HRTIMER_NORESTART;
}
```

`SIGEV_THREAD` 并不是内核起的线程——**内核只投递信号，线程由 glibc 在用户态创建**。

### CPU 时钟：基于记账而非墙上时间

`CLOCK_PROCESS_CPUTIME_ID` / `CLOCK_THREAD_CPUTIME_ID` 以及 `ITIMER_VIRTUAL` / `ITIMER_PROF`
的基础**不是时间，而是 CPU 时间记账**（utime / stime 的累加）。几个直接后果：

- 检查过期只能发生在**记账更新的时刻**，也就是 tick。
- 为了不让"停 tick"破坏这个语义，用它会置上 `TICK_DEP_BIT_POSIX_TIMER`（见前文 tick 依赖）。
- 信号投递不直接在 tick 里做，而是用 task_work（`posix_cpu_timers_work`，`TWA_RESUME`）
  推迟到**返回用户态之前**——避免在中断上下文里发信号。

所以 CPU 时钟的精度边界就是一个 tick 加一次返回用户态的延迟，与墙上时间定时器完全不同。

### time namespace

`unshare(CLONE_NEWTIME)` 能虚拟化的时钟**只有两个**：

```c
/* kernel/time/namespace.c:30 */
	switch (clockid) {
	case CLOCK_MONOTONIC:
		offset = timespec64_to_ktime(ns_offsets->monotonic);
		break;
	case CLOCK_BOOTTIME:
	case CLOCK_BOOTTIME_ALARM:
		offset = timespec64_to_ktime(ns_offsets->boottime);
		break;
	default:
		return tim;
	}
```

**REALTIME 与 TAI 不可虚拟化**（它们对全系统必须是同一个值）。
因为 vDSO 不走系统调用，namespace 的 offset 也必须写进用户页——所以每个 ns 会额外分配一个 vvar 页，
并把 `clock_mode` 标成 `VDSO_CLOCKMODE_TIMENS`（`namespace_vdso.c:55`）。

两个坑：offset 必须在有任务进入该 ns **之前**设好；一旦有任务进入就被冻结，
再写 `/proc/self/timens_offsets` 返回 `-EACCES`（`namespace.c:312`）。

## 与其它子系统的接缝

这条链路几乎被所有异步机制复用，几处主要在：

- **调度**：CFS 的 HRTICK 用 `hrtick_timer`，就是 `HRTIMER_MODE_LAZY_REARM` 的唯一使用者；
  内核抢占检查也由 tick 驱动（见 [进程知识地图](/docs/CS/OS/Linux/proc/README.md)）。
- **网络**：NAPI 的 watchdog 是个 hrtimer（`hrtimer_init(&napi->timer, CLOCK_MONOTONIC, HRTIMER_MODE_REL_PINNED)`），
  用来兜住"忙轮询一直不结束"的情况（见 [NAPI](/docs/CS/OS/Linux/net/NAPI.md)）。
- **I/O**：`epoll` 的超时、`io_uring` 的 timeout 命令，底层都是 `hrtimer_sleeper` 或 hrtimer。
- **中断下半部**：`workqueue` 的延迟工作走 `timer_list`（见 [workqueue](/docs/CS/OS/Linux/workqueue.md)）。
- **虚拟化**：KVM 里 guest 的时间来自 host 的 TSC 与 kvm-clock，[KVM](/docs/CS/OS/Linux/KVM.md)
  的 `hva_to_pfn` 与 EPT 也决定了时间读数的开销。

## 反直觉清单

1. **`HRTIMER_MAX_CLOCK_BASES` 是 8 不是 4**——四个硬基加四个软基，初始化时靠 `MAX/2` 定位软基起点。
2. **`hrtimer_resolution` 的初值是 `LOW_RES_NSEC`，而 `LOW_RES_NSEC = TICK_NSEC`**
   （`include/vdso/ktime.h:13`）：没进高精度模式前，所谓"hrtimer 分辨率"就是一个 tick。
3. **高精度模式不是开机就开的**：由 `hrtimer_switch_to_hres()`（`hrtimer.c:771`）在 tick 切到 oneshot 时
   才升级，升级后才把 `hrtimer_resolution` 改成 `HIGH_RES_NSEC = 1`。
4. **普通内核里 hrtimer 回调默认跑在硬中断上下文**（不是软中断）；RT 内核才反过来，
   且可用 `HRTIMER_MODE_HARD` 单独要求留在硬中断。
5. **`hrtimer_interrupt` 只重试 3 次**就放弃并标记 `hang_detected`，被跳过的定时器晚一个周期。
6. **hrtimer 回调里可以重排自己**——执行前会放下 base 锁，靠 `base->running` 而非状态位标记"运行中"。
7. **`MAX_STALLED_JIFFIES = 5`**：某 CPU 的 tick 卡住 5 个 jiffy 后，其它 CPU 会强制补推进 jiffies。
8. **NO_HZ_FULL 下也一定有一颗 CPU 在跑周期 tick**，负责推进 jiffies，由 `tick_do_timer_cpu` 指定。
9. **`sched_skew_tick` 把各 CPU 的 tick 错开半个周期**，目的是避免抢 `jiffies_lock`。
10. **`timer_migration.c` 没有 Kconfig 条目**——默认编入，只能靠 static key 排除隔离 CPU。
11. **低精度时间轮的层数定义在 `.c` 里而不是 `.h` 里**（`kernel/time/timer.c:167` 的 `LVL_*` 一族）；
    同时 timer base 已从 2 个变成 3 个（`BASE_LOCAL` / `BASE_GLOBAL` / `BASE_DEF`）。
12. **`INITIAL_JIFFIES` 是负数**，故意让 32 位 jiffies 开机 5 分钟后回绕，尽早暴露回绕 bug。
13. **`jiffies` 与 `ktime_get` 不是两套独立时钟**：jiffies 由 `last_jiffies_update` 按 tick 周期累积，
    timekeeping 反灌对齐，两者基准一致、不会长期漂移；但 jiffies 只在 tick 跳变，瞬时滞后于 `ktime_get`。
14. **`CLOCK_MONOTONIC` 在 suspend 期间冻结**，含睡眠时长的是 `CLOCK_BOOTTIME`。
15. **NTP 不能让 MONOTONIC 变小**：相位校正只落到 REALTIME 的 offset，频率校正被 `maxadj`（约 11%）夹住，
    乘在单调递增的 cycles 上——所以 MONOTONIC 只会偶尔变慢，不会回退。
16. **看门狗阈值已改**：老版本的单一 `WATCHDOG_THRESHOLD` 在 v7.2.7 里不存在了，
    改为 PPM 分级（`SHIFT_500PPM = 11` / `SHIFT_4000PPM = 8`）加跨 CPU skew 检测。
17. **`clock_gettime` 可能慢**：时钟源被降级成 HPET 后 VDSO 快路径失效，必须进内核。
18. **`SIGEV_THREAD` 不是内核线程**，内核只发信号，线程由 glibc 建。
19. **`timerfd` 不会丢 tick**：`ticks` 累加，只有 `read()` 清零；重装还是惰性的。
20. **time namespace 只能虚拟化 MONOTONIC 与 BOOTTIME**，且 offset 一旦被任务使用就冻结。
21. **`init_timers()` 已改名 `timers_init()`**（`timer.c:2575`）；`open_softirq` 的回调签名
    也从 `void (*)(struct softirq_action *)` 变成了 **`void (*)(void)`**（`interrupt.h:607`）——
    照老书抄代码会编译不过。

## 排障速查

```bash
# 当前时钟源与候选（被看门狗降级时 current 会变）
cat /sys/devices/system/clocksource/clocksource0/current_clocksource
cat /sys/devices/system/clocksource/clocksource0/available_clocksource

# 每个 CPU 的定时器全景：hrtimer 树、下个到期时刻、tick 设备是否在跑
cat /proc/timer_list            # 需要 root（权限 0400）

# 时钟源被判定不稳 / 降级的痕迹
dmesg | grep -i -E "clocksource|switched to|unstable"

# 开机时间与运行时长
grep btime /proc/stat
cat /proc/uptime

# 观察定时器行为（配合 ftrace 的 timer 事件）
perf stat -e timer:hrtimer_expire_entry,timer:hrtimer_start -a sleep 1
```

判断口诀：

- **`clock_gettime` 突然变慢** → 先看 `current_clocksource` 是否被降级（TSC → HPET）。
- **`sleep` / `nanosleep` 精度差** → 看是否进了高精度模式；某些虚拟机里 clockevent 的 `min_delta` 会被抬高，
  `dmesg` 里会打印 `CE: ... increased min_delta_ns to ...`。
- **CPU 时钟定时器延迟** → 它依赖 tick，检查是否有停 tick 行为。
- **容器里时间不对** → time namespace 的 offset 只影响 MONOTONIC / BOOTTIME，且必须在进程进入前设好。
- **`timer_list` 里某 CPU 的 `next_event` 是 `ktime_max`** → 正常，说明该 CPU 已停 tick 且无待触发事件。

## Links

- [Linux 内核总览](/docs/CS/OS/Linux/Linux.md)
- [内核协同链路](/docs/CS/OS/Linux/Architecture.md)
- [cgroup](/docs/CS/OS/Linux/cgroup.md)
- [ftrace](/docs/CS/OS/Linux/Tools/ftrace.md)
- [性能观测](/docs/CS/OS/Linux/performance.md)

## References

1. [Timers — kernel.org documentation](https://www.kernel.org/doc/html/latest/timers/index.html)
2. [High-resolution timers — kernel.org documentation](https://www.kernel.org/doc/html/latest/timers/hrtimers.html)
3. [Timekeeping — kernel.org documentation](https://www.kernel.org/doc/html/latest/core-api/timekeeping.html)
4. [The high-resolution timer API — LWN](https://lwn.net/Articles/167897/)
5. [Toward a tickless kernel — LWN](https://lwn.net/Articles/369549/)
