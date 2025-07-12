## Introduction



偶发线上访问超时

- 较早Linux 内核版本 SYN 重传时间为3s 较长 当 SYN队列溢出默认丢弃后需要等客户端重传多次后结束

## cpu

CPU 负载激增 甚至100%
- 是否是版本更新导致


## load average

let's talk about the load averages.

Load averages are an industry-critical metric – my company spends millions auto-scaling cloud instances based on them and other metrics – but on Linux there's some mystery around them. 
Linux load averages track not just runnable tasks, but also tasks in the uninterruptible sleep state.

Linux load averages are "system load averages" that show the running thread (task) demand on the system as an average number of running plus waiting threads. This measures demand, which can be greater than what the system is currently processing. Most tools show three averages, for 1, 5, and 15 minutes:
```shell
uptime

top

cat /proc/loadavg
```

Some interpretations:

- If the averages are 0.0, then your system is idle.
- If the 1 minute average is higher than the 5 or 15 minute averages, then load is increasing.
- If the 1 minute average is lower than the 5 or 15 minute averages, then load is decreasing.
- If they are higher than your CPU count, then you might have a performance problem (it depends).

```c
// fs/proc/loadavg.c
static int __init proc_loadavg_init(void)
{
struct proc_dir_entry *pde;
pde = proc_create_single("loadavg", 0, NULL, loadavg_proc_show);

return 0;
}
```


```c
// fs/proc/loadavg.c
static int loadavg_proc_show(struct seq_file *m, void *v)
{
unsigned long avnrun[3];

get_avenrun(avnrun, FIXED_1/200, 0);

seq_printf(m, "%lu.%02lu %lu.%02lu %lu.%02lu %u/%d %d\n",

LOAD_INT(avnrun[0]), LOAD_FRAC(avnrun[0]),
LOAD_INT(avnrun[1]), LOAD_FRAC(avnrun[1]),
LOAD_INT(avnrun[2]), LOAD_FRAC(avnrun[2]),

nr_running(), nr_threads,

idr_get_cursor(&task_active_pid_ns(current)->idr) - 1);

return 0;
}

// kernel/sched/loadavg.c
void get_avenrun(unsigned long *loads, unsigned long offset, int shift)
{
	loads[0] = (avenrun[0] + offset) << shift;
	loads[1] = (avenrun[1] + offset) << shift;
	loads[2] = (avenrun[2] + offset) << shift;
}
```

set sched_timer.function = tick_nohz_handler
```c
void tick_setup_sched_timer(bool hrtimer)
{
	struct tick_sched *ts = this_cpu_ptr(&tick_cpu_sched);

	/* Emulate tick processing via per-CPU hrtimers: */
	hrtimer_init(&ts->sched_timer, CLOCK_MONOTONIC, HRTIMER_MODE_ABS_HARD);

	if (IS_ENABLED(CONFIG_HIGH_RES_TIMERS) && hrtimer) {
		tick_sched_flag_set(ts, TS_FLAG_HIGHRES);
		ts->sched_timer.function = tick_nohz_handler;
	}

	/* Get the next period (per-CPU) */
	hrtimer_set_expires(&ts->sched_timer, tick_init_jiffy_update());

	/* Offset the tick to avert 'jiffies_lock' contention. */
	if (sched_skew_tick) {
		u64 offset = TICK_NSEC >> 1;
		do_div(offset, num_possible_cpus());
		offset *= smp_processor_id();
		hrtimer_add_expires_ns(&ts->sched_timer, offset);
	}

	hrtimer_forward_now(&ts->sched_timer, TICK_NSEC);
	if (IS_ENABLED(CONFIG_HIGH_RES_TIMERS) && hrtimer)
		hrtimer_start_expires(&ts->sched_timer, HRTIMER_MODE_ABS_PINNED_HARD);
	else
		tick_program_event(hrtimer_get_expires(&ts->sched_timer), 1);
	tick_nohz_activate(ts);
}
```


```c
static enum hrtimer_restart tick_nohz_handler(struct hrtimer *timer)
{
	struct tick_sched *ts =	container_of(timer, struct tick_sched, sched_timer);
	struct pt_regs *regs = get_irq_regs();
	ktime_t now = ktime_get();

	tick_sched_do_timer(ts, now);

	// ...
	tick_sched_handle(ts, regs);

	if (unlikely(tick_sched_flag_test(ts, TS_FLAG_STOPPED)))
		return HRTIMER_NORESTART;

	hrtimer_forward(timer, now, TICK_NSEC);

	return HRTIMER_RESTART;
}
```
#### scheduler_tick
tick_sched_handle -> update_process_times -> scheduler_tick
```c
void scheduler_tick(void)
{
	int cpu = smp_processor_id();
	struct rq *rq = cpu_rq(cpu);
	struct task_struct *curr = rq->curr;
	struct rq_flags rf;
	unsigned long thermal_pressure;
	u64 resched_latency;

	if (housekeeping_cpu(cpu, HK_TYPE_TICK))
		arch_scale_freq_tick();

	sched_clock_tick();

	rq_lock(rq, &rf);

	update_rq_clock(rq);
	thermal_pressure = arch_scale_thermal_pressure(cpu_of(rq));
	update_thermal_load_avg(rq_clock_thermal(rq), rq, thermal_pressure);
	curr->sched_class->task_tick(rq, curr, 0);
	if (sched_feat(LATENCY_WARN))
		resched_latency = cpu_resched_latency(rq);
	calc_global_load_tick(rq);
	sched_core_tick(rq);
	task_tick_mm_cid(rq, curr);

	rq_unlock(rq, &rf);

	if (sched_feat(LATENCY_WARN) && resched_latency)
		resched_latency_warn(cpu, resched_latency);

	perf_event_task_tick();

	if (curr->flags & PF_WQ_WORKER)
		wq_worker_tick(curr);
}
```
calc both running and uninterruptible
```c
void calc_global_load_tick(struct rq *this_rq)
{
	long delta;

	if (time_before(jiffies, this_rq->calc_load_update))
		return;

	delta  = calc_load_fold_active(this_rq, 0);
	if (delta)
		atomic_long_add(delta, &calc_load_tasks);

	this_rq->calc_load_update += LOAD_FREQ;
}

long calc_load_fold_active(struct rq *this_rq, long adjust)
{
	long nr_active, delta = 0;

	nr_active = this_rq->nr_running - adjust;
	nr_active += (int)this_rq->nr_uninterruptible;

	if (nr_active != this_rq->calc_load_active) {
		delta = nr_active - this_rq->calc_load_active;
		this_rq->calc_load_active = nr_active;
	}

	return delta;
}
```

`Exponential Weighted Moving Average`

```c
void do_timer(unsigned long ticks)
{
	jiffies_64 += ticks;
	calc_global_load();
}


void calc_global_load(void)
{
	unsigned long sample_window;
	long active, delta;

	sample_window = READ_ONCE(calc_load_update);
	if (time_before(jiffies, sample_window + 10))
		return;

	/*
	 * Fold the 'old' NO_HZ-delta to include all NO_HZ CPUs.
	 */
	delta = calc_load_nohz_read();
	if (delta)
		atomic_long_add(delta, &calc_load_tasks);

	active = atomic_long_read(&calc_load_tasks);
	active = active > 0 ? active * FIXED_1 : 0;

	avenrun[0] = calc_load(avenrun[0], EXP_1, active);
	avenrun[1] = calc_load(avenrun[1], EXP_5, active);
	avenrun[2] = calc_load(avenrun[2], EXP_15, active);

	WRITE_ONCE(calc_load_update, sample_window + LOAD_FREQ);

	/*
	 * In case we went to NO_HZ for multiple LOAD_FREQ intervals
	 * catch up in bulk.
	 */
	calc_global_nohz();
}
```

## References
1. [Linux Load Averages: Solving the Mystery](https://www.brendangregg.com/blog/2017-08-08/linux-load-averages.html)