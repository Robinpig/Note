## Introduction

Linux内核社区的一位传奇人物Con Kolivas 提出了楼梯调度算法来实现公平性，在社区的一番争论之后，Red Hat公司的Ingo Molnar借鉴楼梯调度算法的思想提出了CFS算法


https://www.kernel.org/doc/Documentation/scheduler/sched-design-CFS.txt

进程创建时，会基于原进程的 vruntime 附加惩罚时间来初始化现有进程的 vruntime。
进程唤醒时，会以睡眠时间和优先级无关的延迟常数对 vruntime 进行补偿（减小）。
进程调度时，除去挑选 leftmost vruntime 以外，还需考虑 gran 和 buddy 机制。





### vruntime 与权重

CFS/EEVDF 的核心量是 **vruntime**（虚拟运行时间）：实际运行时间按权重归一化后的值。权重由 nice 值决定（`sched_prio_to_weight` 表），nice 每低 1 级权重大约 ×1.25；权重越大的实体 vruntime 增长越慢，从而分到更多 CPU 时间。

```c
// kernel/sched/fair.c: 权重不为 NICE_0_LOAD 时按比例折算
static inline u64 calc_delta_fair(u64 delta, struct sched_entity *se)
{
	if (unlikely(se->load.weight != NICE_0_LOAD))
		delta = __calc_delta(delta, NICE_0_LOAD, &se->load);

	return delta;
}
```

| nice    | -20   | -10  | 0    | 10  | 19 |
| ------- | ----- | ---- | ---- | --- | -- |
| weight  | 88761 | 9548 | 1024 | 110 | 15 |

`cfs_rq->min_vruntime` 是单调递增的基线：入队/唤醒的实体以它为下限修正 vruntime，既防止休眠已久的任务回来后凭过小的 vruntime 独占 CPU，也防止新任务拿到过小的 vruntime 而饿死别人。

### update_curr

所有路径（时钟节拍、入队、出队、pick）都会先经 `update_curr()` 把当前实体的账算清楚：累计 `delta_exec`、按权重折算 vruntime、推进 min_vruntime；EEVDF 中同时消耗 `se->deadline`（`vd = ve + slice/weight` 折算），slice 用尽即触发抢占。

### EEVDF

6.6 起经典 CFS 被 EEVDF 取代。经典 CFS 只追求“公平”（理想公平时间 S 与实际运行时间 s 之差最小）；EEVDF 在此之上引入延迟维度：

- **lag**（滞后量）：`lag = S - s`，正值代表被“亏欠”，负值代表“透支”。EEVDF 的选取目标是让系统的加权平均 lag 趋近 0。
- **eligible**：`vruntime >= ve`（虚拟开始时间）的实体才有资格运行，防止透支（lag 为负）的任务插队。
- **virtual deadline**：`vd = ve + slice / weight`，在所有 eligible 实体中挑 deadline 最早者：
  - `se->slice`（默认 `sysctl_sched_base_slice`）越小 → deadline 越早 → 响应越快（取代旧 CFS 的低延迟启发式）；
  - weight 越大 → 同样 slice 折算的虚拟时间增量越小 → 更早到期，高权重获得更多时间。

下文 [place_entity](#place-entity) 的代码正是 EEVDF 的放置策略：唤醒时按 lag 放置（`se->vruntime = vruntime - lag`），并设置 `se->deadline = se->vruntime + vslice`。

### pick_next_entity

经典 CFS 直接取红黑树最左节点（vruntime 最小）；EEVDF 在按虚拟时间排序的红黑树上做增强——每个节点缓存子树中最小的 virtual deadline，从根往下走时可以整棵跳过不可能更优的子树，在 eligible 候选（含 curr 与 next/last buddy）中取 virtual deadline 最早者。整体仍是 O(log n)。

### check_preempt_wakeup

唤醒是抢占的主要来源：[try_to_wake_up](/docs/CS/OS/Linux/proc/thundering_herd.md?id=try_to_wake_up) 选好 CPU、enqueue 之后，通过调度类回调 `check_preempt_curr` 判断被唤醒任务能否抢占当前任务。fair 类中若唤醒实体的 virtual deadline 早于当前实体，则 `set_next_buddy` 并 `resched_curr`；真正的切换发生在最近的安全点（见 [preemption](/docs/CS/OS/Linux/proc/sche.md?id=preemption)）。

### task_tick_fair

`task_tick_fair`（sched_class->task_tick）在每个时钟节拍被调用：update_curr 刷新账目、检查 CFS 带宽是否耗尽；EEVDF 下若当前实体 `vruntime >= deadline`（slice 用尽）则 `resched_curr` 请求重新调度——旧 CFS 的 gran/buddy 启发式被 deadline 自然取代。

fork 时 `task_fork_fair` 为新实体初始化调度参数（旧内核中在此为新实体放置 vruntime 并均分父进程 slice，防止新进程立刻抢占全队列）：

```c
static void task_fork_fair(struct task_struct *p)
{
	set_task_max_allowed_capacity(p);
}
```

### enqueue_entity

如果进程睡眠了很久 进程的 vruntime很久没有修改过而比较低 
完全公平调度器会在 enqueue_entity 中修改其 vruntime以保持整体的公平性

When enqueuing a sched_entity, we must:
  - Update loads to have both entity and cfs_rq synced with now.
  - For group_entity, update its runnable_weight to reflect the new
    h_nr_running of its group cfs_rq.
  - For group_entity, update its weight to reflect the new share of
    its group cfs_rq
  - Add its new weight to cfs_rq->load.weight


```c
// kernel/sched/fair.c
static void
enqueue_entity(struct cfs_rq *cfs_rq, struct sched_entity *se, int flags)
{
	bool curr = cfs_rq->curr == se;

	/*
	 * If we're the current task, we must renormalise before calling
	 * update_curr().
	 */
	if (curr)
		place_entity(cfs_rq, se, flags);

	update_curr(cfs_rq);

	update_load_avg(cfs_rq, se, UPDATE_TG | DO_ATTACH);
	se_update_runnable(se);

	update_cfs_group(se);

	if (!curr)
		place_entity(cfs_rq, se, flags);

	account_entity_enqueue(cfs_rq, se);

	/* Entity has migrated, no longer consider this task hot */
	if (flags & ENQUEUE_MIGRATED)
		se->exec_start = 0;

	check_schedstat_required();
	update_stats_enqueue_fair(cfs_rq, se, flags);
	if (!curr)
		__enqueue_entity(cfs_rq, se);
	se->on_rq = 1;

	if (cfs_rq->nr_running == 1) {
		check_enqueue_throttle(cfs_rq);
		if (!throttled_hierarchy(cfs_rq)) {
			list_add_leaf_cfs_rq(cfs_rq);
		} else {
#ifdef CONFIG_CFS_BANDWIDTH
			struct rq *rq = rq_of(cfs_rq);

			if (cfs_rq_throttled(cfs_rq) && !cfs_rq->throttled_clock)
				cfs_rq->throttled_clock = rq_clock(rq);
			if (!cfs_rq->throttled_clock_self)
				cfs_rq->throttled_clock_self = rq_clock(rq);
#endif
		}
	}
}
```


### place_entity

```c

static void
place_entity(struct cfs_rq *cfs_rq, struct sched_entity *se, int flags)
{
	u64 vslice, vruntime = avg_vruntime(cfs_rq);
	s64 lag = 0;

	if (!se->custom_slice)
		se->slice = sysctl_sched_base_slice;
	vslice = calc_delta_fair(se->slice, se);

	/*
	 * Due to how V is constructed as the weighted average of entities,
	 * adding tasks with positive lag, or removing tasks with negative lag
	 * will move 'time' backwards, this can screw around with the lag of
	 * other tasks.
	 *
	 * EEVDF: placement strategy #1 / #2
	 */
	if (sched_feat(PLACE_LAG) && cfs_rq->nr_running && se->vlag) {
		struct sched_entity *curr = cfs_rq->curr;
		unsigned long load;

		lag = se->vlag;

		/*
		 * If we want to place a task and preserve lag, we have to
		 * consider the effect of the new entity on the weighted
		 * average and compensate for this, otherwise lag can quickly
		 * evaporate.
		 *
		 * Lag is defined as:
		 *
		 *   lag_i = S - s_i = w_i * (V - v_i)
		 *
		 * To avoid the 'w_i' term all over the place, we only track
		 * the virtual lag:
		 *
		 *   vl_i = V - v_i <=> v_i = V - vl_i
		 *
		 * And we take V to be the weighted average of all v:
		 *
		 *   V = (\Sum w_j*v_j) / W
		 *
		 * Where W is: \Sum w_j
		 *
		 * Then, the weighted average after adding an entity with lag
		 * vl_i is given by:
		 *
		 *   V' = (\Sum w_j*v_j + w_i*v_i) / (W + w_i)
		 *      = (W*V + w_i*(V - vl_i)) / (W + w_i)
		 *      = (W*V + w_i*V - w_i*vl_i) / (W + w_i)
		 *      = (V*(W + w_i) - w_i*l) / (W + w_i)
		 *      = V - w_i*vl_i / (W + w_i)
		 *
		 * And the actual lag after adding an entity with vl_i is:
		 *
		 *   vl'_i = V' - v_i
		 *         = V - w_i*vl_i / (W + w_i) - (V - vl_i)
		 *         = vl_i - w_i*vl_i / (W + w_i)
		 *
		 * Which is strictly less than vl_i. So in order to preserve lag
		 * we should inflate the lag before placement such that the
		 * effective lag after placement comes out right.
		 *
		 * As such, invert the above relation for vl'_i to get the vl_i
		 * we need to use such that the lag after placement is the lag
		 * we computed before dequeue.
		 *
		 *   vl'_i = vl_i - w_i*vl_i / (W + w_i)
		 *         = ((W + w_i)*vl_i - w_i*vl_i) / (W + w_i)
		 *
		 *   (W + w_i)*vl'_i = (W + w_i)*vl_i - w_i*vl_i
		 *                   = W*vl_i
		 *
		 *   vl_i = (W + w_i)*vl'_i / W
		 */
		load = cfs_rq->avg_load;
		if (curr && curr->on_rq)
			load += scale_load_down(curr->load.weight);

		lag *= load + scale_load_down(se->load.weight);
		if (WARN_ON_ONCE(!load))
			load = 1;
		lag = div_s64(lag, load);
	}

	se->vruntime = vruntime - lag;

	if (se->rel_deadline) {
		se->deadline += se->vruntime;
		se->rel_deadline = 0;
		return;
	}

	/*
	 * When joining the competition; the existing tasks will be,
	 * on average, halfway through their slice, as such start tasks
	 * off with half a slice to ease into the competition.
	 */
	if (sched_feat(PLACE_DEADLINE_INITIAL) && (flags & ENQUEUE_INITIAL))
		vslice /= 2;

	/*
	 * EEVDF: vd_i = ve_i + r_i/w_i
	 */
	se->deadline = se->vruntime + vslice;
}
```

### CFS 带宽控制

cgroup 层面对普通任务也有配额：`cpu.cfs_quota_us` / `cpu.cfs_period_us`（如 200000/1000000 = 0.2 个 CPU）。每个周期内 runtime 耗尽后 `check_cfs_rq_runtime()` 触发 throttle，cfs_rq 被整体出队，任务进入 throttled 状态直到下个周期补充配额——容器 CPU 限流的根源就在这里（[cgroup](/docs/CS/OS/Linux/cgroup.md)）。上文 enqueue_entity 中的 `check_enqueue_throttle` 与 rq 里的 `cfsb_*` 字段即相关实现。

## Links

- [sched](/docs/CS/OS/Linux/proc/sche.md)
- [rt](/docs/CS/OS/Linux/proc/rt.md)
- [Scheduling 理论](/docs/CS/OS/scheduling.md)
- [Processes 知识地图](/docs/CS/OS/Linux/proc/README.md)
