## Introduction

OOM（Out-Of-Memory）是页分配器慢路径的**最后手段**：kswapd 异步回收、直接回收（direct reclaim）、内存压缩（compaction）都救不回来、连 min 水位都无法满足分配时，内核只能杀掉一个进程来释放内存。这条链的起点在 [alloc_pages_slowpath](/docs/CS/OS/Linux/mm/pm.md?id=alloc_pages_slowpath)，而回收这条链本身的展开见 [内存回收（Reclaim）](/docs/CS/OS/Linux/mm/Reclaim.md)。

为什么不能"分配失败就返回 NULL"了事？因为很多内存分配发生在**不能失败、也不能 sleep** 的上下文里（中断、持锁、内核关键路径），如果放任失败，内核会挂死；OOM killer 的本质是**用确定性的一击换取系统整体的前向进展**——挑一个"坏账"最大的进程杀掉，释放它的全部内存。

理解 OOM killer 的三个核心问题：

1. **什么时候触发**——`out_of_memory()` 的调用时机与前置检查；
2. **杀谁**——`select_bad_process()` 遍历进程、`oom_badness()` 打分；
3. **怎么杀**——`oom_kill_process()` 发 SIGKILL、`oom_reaper` 异步收割匿名页。

## Trigger Paths

分配慢路径里，回收与压缩都失败后进入 `__alloc_pages_may_oom()`，最终调用 `out_of_memory()`：

```c
// mm/page_alloc.c（慢路径骨架）
	/* Retry machine, anything before this point has failed */
	...
	page = __alloc_pages_may_oom(gfp_mask, order, preferred_nid,
				     nodemask, &did_some_progress);
```

```c
// mm/page_alloc.c
static inline struct page *
__alloc_pages_may_oom(gfp_t gfp_mask, unsigned int order,
	int preferred_nid, const nodemask_t *nodemask, bool *did_some_progress)
{
	struct oom_control oc = {
		.totalpages = 0,
		.gfp_mask = gfp_mask,
		.order = order,
		.nodemask = nodemask,
	};
	...
	*did_some_progress = out_of_memory(&oc);
	...
}
```

注意触发是有门槛的：`should_reclaim_retry()` 会反复评估"回收 + 压缩 + 更高水位重试"是否还有希望，只有**确定无望**才走 OOM；频繁触发 OOM 通常意味着回收链路（[Reclaim](/docs/CS/OS/Linux/mm/pm.md?id=reclaim)、[Swap](/docs/CS/OS/Linux/Swap.md)）已经被打穿。

## out_of_memory

```c
// mm/oom_kill.c
bool out_of_memory(struct oom_control *oc)
{
	if (oom_killer_disabled)
		return false;

	/* If the OOM killer is disabled, bail out */
	oc->totalpages = totalram_pages() + total_swap_pages;

	mutex_lock(&oom_lock);

	if (!is_memcg_oom(oc)) {
		check_panic_on_oom(oc);

		/* Running out of memory in the middle of a kernel oops isn't fun */
		if (oops_in_progress)
			goto unlock;
	}

	/* Sysrq+o 或 oom_kill_allocating_task：直接杀当前触发分配的任务 */
	if (is_sysrq_oom(oc) || oom_kill_allocating_task || !oc->task) {
		oc->chosen_task = current;
		goto out_of_memory;
	}

	select_bad_process(oc);

out_of_memory:
	if (oc->chosen_task && oc->chosen_task != INALLOC_PROGRESS) {
		/* Give ourself a chance to die gracefully */
		if (oc->chosen_task == current)
			...
		oom_kill_process(oc, "Out of memory");
	}
	...
unlock:
	mutex_unlock(&oom_lock);
	return !!oc->chosen_task;
}
```

入口处的几个分支值得注意：

- `check_panic_on_oom`：`vm.panic_on_oom=1` 时不挑选、直接内核 panic（对可用性要求极高的系统宁可重启也不让 OOM killer 随机杀进程）；
- **task_will_free_mem(current)**：如果触发分配的进程自己正在退出（收到 SIGKILL 等），直接选中它——让它快点退出释放内存，不必连累别人；
- `is_memcg_oom`：memcg 限额触发的 OOM 只在**该 cgroup 的进程集合里**挑选，见下文 [memcg OOM](?id=memcg-oom)。

## select_bad_process and oom_badness

选victim 的逻辑：遍历所有进程，对每个进程调用 `oom_badness()` 打分，取分最高者。

```c
// mm/oom_kill.c
static void select_bad_process(struct oom_control *oc)
{
	oc->chosen_points = LONG_MIN;

	if (is_memcg_oom(oc))
		mem_cgroup_scan_tasks(oc->memcg, oom_evaluate_task, oc);
	else {
		struct task_struct *p;

		rcu_read_lock();
		for_each_process(p)
			if (oom_evaluate_task(p, oc))
				break; /* 找到了，提前结束 */
		rcu_read_unlock();
	}
}
```

打分公式是 OOM killer 的核心——**谁占内存多、谁该死**：

```c
// mm/oom_kill.c
long oom_badness(struct task_struct *p, unsigned long totalpages)
{
	long points;
	long adj;

	if (oom_unkillable_task(p))
		return LONG_MIN;

	p = find_lock_task_mm(p);
	if (!p)
		return LONG_MIN;

	adj = (long)p->signal->oom_score_adj;
	if (adj == OOM_SCORE_ADJ_MIN ||		/* -1000：永不杀 */
			test_bit(MMF_OOM_SKIP, &p->mm->flags) ||
			in_vfork(p)) {
		task_unlock(p);
		return LONG_MIN;
	}

	/*
	 * The baseline for the badness score is the proportion of RAM that each
	 * task's rss, pagetable and swap space use.
	 */
	points = get_mm_rss(p->mm) + get_mm_counter(p->mm, MM_SWAPENTS) +
		mm_pgtables_bytes(p->mm) / PAGE_SIZE;
	task_unlock(p);

	/* Normalize to oom_score_adj units */
	adj *= totalpages / 1000;
	points += adj;

	return points;
}
```

拆解这个公式：

- **基线分** = RSS（常驻匿名页 + 文件页）+ 已换出的 swap 条目数 + 页表占用（按页折算）。即**这个进程实际占用的全部内存足迹**，而不是虚拟内存大小；
- **`oom_score_adj`** 是唯一的用户态干预旋钮，取值 `[-1000, 1000]`：`-1000`（`OOM_SCORE_ADJ_MIN`）直接免疫 OOM；正值增加被选概率。换算成"页数单位"叠加到基线上——`+1000` 约等于把全系统内存都算到它头上，必被选中；
- 返回 `LONG_MIN` 的进程（免疫、`MMF_OOM_SKIP` 已杀过、vfork 中）不参与评选。

用户态可见的 `/proc/<pid>/oom_score` 就是这个分数（归一化后），`oom_score_adj` 可读写。典型用法：Redis 源码里的 `oom_score_adj_values` 配置（见 [Redis server](/docs/CS/DB/Redis/server.md)）、sshd 等关键守护进程设为 `-1000`。

## oom_kill_process

选定 victim 后，`oom_kill_process()` 执行处决：

- 向 victim 进程组发 `SIGKILL`（不可被捕获、不可被忽略——这是唯一能保证"一定会退出"的信号）；
- **优先杀子进程**：如果 victim 有合适的子进程可分担（`oom_unkillable` 之外、且能释放足够内存），内核可能转而牺牲子进程并保留父进程（`dump_tasks` 前的 `find_allocating_task` / sacrifice 分支）；
- 记录 OOM 报告（`dump_header`：内存/swap 水位、各进程 badness 排名——`dmesg` 里看到的 OOM 报告就是它）。

## oom_reaper

杀掉进程不等于内存立刻可用：victim 从收到 SIGKILL 到真正退出，中间还要经历退出路径（释放文件、IPC、等待锁等）。如果 victim 卡在不可中断的路径上，内存就迟迟还不上。**oom_reaper** 内核线程解决这个问题：

```c
// mm/oom_kill.c（骨架）
static int oom_reaper(void *unused)
{
	while (true) {
		struct task_struct *tsk = wait_event_interruptible(...);
		/* 异步收割：不等进程退出，直接拆它的匿名页映射 */
		__oom_reap_task_mm(tsk);
	}
}
```

reaper 拿 victim 的 `mm`，**不需要 mmap_write_lock**（只需读锁 + 逐 VMA trylock），把匿名页和 swap 条目逐个 unmap、释放——相当于抢先回收了 victim 的私有内存，被回收后 victim 剩下的只是一具空壳。`queue_oom_reaper()` 在 `mark_oom_victim()` 时就把 victim 挂上收割队列。

## memcg OOM

cgroup v2 的 `memory.max` 超限时，触发的是**memcg 局部 OOM**：`is_memcg_oom()` 为真，`select_bad_process()` 只遍历**该 memcg 的进程**（`mem_cgroup_scan_tasks`），杀出的进程必然是容器自己的——这就是"容器 OOM 不殃及宿主机"的机制保证，也是 K8s `OOMKilled`（退出码 137）的内核来路。memcg 侧的记账、限额与"high 只节流不杀"的对照见 [cgroup 内存控制（memcg）](/docs/CS/OS/Linux/mm/memcg.md)。

K8s 层面的 QoS 等级正是通过 `oom_score_adj` 落地的：Guaranteed Pod 设 `-997`，BestEffort 设 `1000`，Burstable 按 `min(max(2, 1000 - memoryRequestBytes/memoryLimitBytes*1000), 999)` 计算——节点级 OOM 时 BestEffort 最先被杀，Guaranteed 最后。对照表见 [Pod 资源与 QoS](/docs/CS/Container/k8s/Pod.md?id=resources-and-qos)。

## Links

- [物理内存地图（mm 枢纽）](/docs/CS/OS/Linux/mm/README.md)

## References

1. [Taming the OOM killer](https://lwn.net/Articles/317814/)
2. [OOM killer — kernel.org documentation](https://www.kernel.org/doc/html/latest/admin-guide/mm/concepts.html#out-of-memory-management)
3. [mm/oom_kill.c — Linux source (Bootlin Elixir)](https://elixir.bootlin.com/linux/latest/source/mm/oom_kill.c)
