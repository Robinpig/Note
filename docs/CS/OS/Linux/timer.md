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



gettimeofday系统调用就是用来获取当前时间的，结果以timeval和timezone（时区）结构体的形式返回

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


```c
// include/linux/time.h
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




```c
// include/linux/hrtimer.h
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


## init_timers

```c
// kernel/time/timer.c
void __init init_timers(void)
{
	init_timer_cpus();
	posix_cputimers_init_work();
	open_softirq(TIMER_SOFTIRQ, run_timer_softirq);
}
```

open [softirq](/docs/CS/OS/Linux/Interrupt.md?id=softirq)

```c
static __latent_entropy void run_timer_softirq(struct softirq_action *h)
{
	struct timer_base *base = this_cpu_ptr(&timer_bases[BASE_STD]);

	__run_timers(base);
	if (IS_ENABLED(CONFIG_NO_HZ_COMMON))
		__run_timers(this_cpu_ptr(&timer_bases[BASE_DEF]));
}
```

## jiffies

The following defines establish the engineering parameters of the PLL model.
The HZ variable establishes the timer interrupt frequency, 100 Hz for the SunOS kernel, 256 Hz for the Ultrix kernel and 1024 Hz for the OSF/1 kernel.
The SHIFT_HZ define expresses the same value as the nearest power of two in order to avoid hardware multiply operations.

```c
// uapi/asm-generic/param.h
#ifndef HZ
#define HZ 100

```

```c
// linux/jiffies.h
#if HZ >= 12 && HZ < 24
# define SHIFT_HZ	4
#elif HZ >= 24 && HZ < 48
# define SHIFT_HZ	5
#elif HZ >= 48 && HZ < 96
# define SHIFT_HZ	6
#elif HZ >= 96 && HZ < 192
# define SHIFT_HZ	7
#elif HZ >= 192 && HZ < 384
# define SHIFT_HZ	8
#elif HZ >= 384 && HZ < 768
# define SHIFT_HZ	9
#elif HZ >= 768 && HZ < 1536
# define SHIFT_HZ	10
#elif HZ >= 1536 && HZ < 3072
# define SHIFT_HZ	11
#elif HZ >= 3072 && HZ < 6144
# define SHIFT_HZ	12
#elif HZ >= 6144 && HZ < 12288
# define SHIFT_HZ	13
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

Have the 32 bit jiffies value wrap 5 minutes after boot so jiffies wrap bugs show up earlier.

```c
#define INITIAL_JIFFIES ((unsigned long)(unsigned int) (-300*HZ))
```



## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)