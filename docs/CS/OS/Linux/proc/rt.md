## Introduction 

sched_rt_entity 结构体充当 rq 和 task_struct 的媒介

### 实时策略

实时调度类覆盖 `SCHED_FIFO` 与 `SCHED_RR`（外加 `SCHED_DEADLINE`，见 [DL](/docs/CS/OS/Linux/proc/sche.md?id=dl)）：

- **SCHED_FIFO**：没有时间片概念，同优先级先进先出，一直运行到阻塞、主动让出或被更高优先级抢占。
- **SCHED_RR**：同优先级按时间片轮转，默认 100ms（`sched_rr_timeslice`，可通过 `/proc/sys/kernel/sched_rr_timeslice_ms` 调整），片用尽后排到同优先级队尾。

无论哪种策略，只要存在可运行的实时任务，它就绝对先于 fair/idle 类运行。

### 实时优先级

实时优先级 `rt_priority` 取值 1~99（`chrt -f 99 pid`），内核换算为 prio 0~98（数值越小优先级越高）；普通任务的 nice 映射到 100~139。每个 CPU 的 rt_rq 内部用 `rt_prio_array` 组织：100 个链表 + 一张位图，`sched_find_first_bit` 一步定位最高优先级队列，查找 O(1)——这正是从 O(1) 调度器继承的数据结构。

### RT throttling

实时任务无限运行会把整个系统拖死（包括看门狗、ssh），因此内核默认限制实时任务每 `sched_rt_period_us`（1s）内最多运行 `sched_rt_runtime_us`（950ms），即 95% 的 CPU 时间；剩余 5% 留给普通任务。耗尽后 `sched_rt_runtime_exceeded()` 将 rt_rq 打上 throttle 并 `resched_curr`，下个周期由 `do_start_rt_bandwidth` 启动的定时器补充带宽。下面的 `update_curr_rt` 就是这个检查的实现。关闭方式：`sysctl -w kernel.sched_rt_runtime_us=-1`。




### task_tick_rt

task_tick_rt 在时钟中断时被调用

```c
static void task_tick_rt(struct rq *rq, struct task_struct *p, int queued)
{
	struct sched_rt_entity *rt_se = &p->rt;

	update_curr_rt(rq);
	update_rt_rq_load_avg(rq_clock_pelt(rq), rq, 1);

	watchdog(rq, p);

	/*
	 * RR tasks need a special form of time-slice management.
	 * FIFO tasks have no timeslices.
	 */
	if (p->policy != SCHED_RR)
		return;

	if (--p->rt.time_slice)
		return;

	p->rt.time_slice = sched_rr_timeslice;

	/*
	 * Requeue to the end of queue if we (and all of our ancestors) are not
	 * the only element on the queue
	 */
	for_each_sched_rt_entity(rt_se) {
		if (rt_se->run_list.prev != rt_se->run_list.next) {
			requeue_task_rt(rq, p, 0);
			resched_curr(rq);
			return;
		}
	}
}
```

#### update_curr_rt

```c
static void update_curr_rt(struct rq *rq)
{
	struct task_struct *donor = rq->donor;
	s64 delta_exec;

	if (donor->sched_class != &rt_sched_class)
		return;

	delta_exec = update_curr_common(rq);
	if (unlikely(delta_exec <= 0))
		return;

#ifdef CONFIG_RT_GROUP_SCHED
	struct sched_rt_entity *rt_se = &donor->rt;

	if (!rt_bandwidth_enabled())
		return;

	for_each_sched_rt_entity(rt_se) {
		struct rt_rq *rt_rq = rt_rq_of_se(rt_se);
		int exceeded;

		if (sched_rt_runtime(rt_rq) != RUNTIME_INF) {
			raw_spin_lock(&rt_rq->rt_runtime_lock);
			rt_rq->rt_time += delta_exec;
			exceeded = sched_rt_runtime_exceeded(rt_rq);
			if (exceeded)
				resched_curr(rq);
			raw_spin_unlock(&rt_rq->rt_runtime_lock);
			if (exceeded)
				do_start_rt_bandwidth(sched_rt_bandwidth(rt_rq));
		}
	}
#endif
}
```





## Links

- [sched](/docs/CS/OS/Linux/proc/sche.md)
- [fair](/docs/CS/OS/Linux/proc/fair.md)
- [Scheduling 理论](/docs/CS/OS/scheduling.md)
- [Processes 知识地图](/docs/CS/OS/Linux/proc/README.md)
