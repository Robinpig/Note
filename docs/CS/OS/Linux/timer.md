
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