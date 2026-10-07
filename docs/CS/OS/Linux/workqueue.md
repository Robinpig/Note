## Introduction

中断处理要快，但很多后续工作不快：要拿 mutex、要做 I/O、要分配可能触发回收的内存。
这些**不能睡眠**的活没法在中断上下文里干，于是内核需要一种"把工作推后到进程上下文执行"的通用机制，
这就是 **workqueue**。

它的形态是：调用方把一个**工作项**（`work_struct`）挂到某个**工作队列**（`workqueue_struct`）上，
内核用**内核线程**（`kworker`，见 ps 里那些 `kworker/N:H` 任务）把它跑完。
调用方只管提交，不关心谁跑、什么时候跑、几个线程在跑。

与 [softirq 和 tasklet](/docs/CS/OS/Linux/Interrupt.md?id=softirq) 相比，workqueue 的唯一本质区别是
**运行在进程上下文，因此可以睡眠**。代价是它有线程调度开销，不适合高频、极低延迟的场景。

## The Bottom-half Trio

Linux 的"下半部"其实有三套机制，它们不是替代关系，而是按**能否睡眠**分层：

| | softirq | tasklet | workqueue |
|---|---|---|---|
| 执行上下文 | 中断上下文（关中断下半） | 中断上下文（基于 softirq） | **进程上下文**（内核线程） |
| 能否睡眠 | 不能 | 不能 | **能** |
| 并发 | 同类型可并发在多个 CPU | 同一 tasklet 串行（不跨 CPU） | 由 `max_active` 控制，默认充分并发 |
| 绑定 CPU | 提交者所在 CPU | 提交者所在 CPU | per-cpu 或 unbound 可选 |
| 动态创建 | 编译期静态枚举 | 运行时但数量有限 | 运行时随意创建 |
| 典型用途 | 网络收包、块设备完成、timer | 驱动里轻量延迟处理 | 任何需要睡眠/阻塞/长时间的工作 |

选择规则很直接：**不睡眠且极高频**用 softirq/tasklet；**要睡眠、要拿锁、要跑很久**就用 workqueue。
驱动里 90% 的场景其实该用 workqueue，只是因为历史习惯，tasklet 常被误用。

6.12 还新增了 **BH workqueue**（`WQ_BH`），它在 softirq 上下文执行、开销接近 tasklet，
但复用 workqueue 的 API 与并发管理——相当于补上了"不睡眠但要简单接口"这一档。

## Five-layer Data Structures

workqueue 的实现把"队列"拆成了五层，理解它们的分工是读懂源码的前提：

**① `work_struct`——工作项本身**，意外地简洁（`include/linux/workqueue_types.h`）：

```c
struct work_struct {
	atomic_long_t data;
	struct list_head entry;
	work_func_t func;
#ifdef CONFIG_LOCKDEP
	struct lockdep_map lockdep_map;
#endif
};
```

`data` 是一个"打包字段"：低位放标志（`WORK_STRUCT_PENDING` 等），高位要么指向所属的
`pool_workqueue`（在队列里时），要么记录最后所在的 pool ID 与 disable 深度（不在队列里时）。
这样省下一个指针的代价是读写都要位运算。

需要延后执行或要等 RCU 宽限期的，用包了一层的变体：

```c
struct delayed_work {
	struct work_struct work;
	struct timer_list timer;

	/* target workqueue and CPU ->timer uses to queue ->work */
	struct workqueue_struct *wq;
	int cpu;
};

struct rcu_work {
	struct work_struct work;
	struct rcu_head rcu;

	/* target workqueue ->rcu uses to queue ->work */
	struct workqueue_struct *wq;
};
```

`delayed_work` 只是"工作项 + [定时器](/docs/CS/OS/Linux/timer.md)"——到期后由定时器回调把内部的
`work` 真正入队，本身不引入新的执行机制。

**② `workqueue_struct`——对外暴露的队列**，由 `alloc_workqueue()` 创建：

```c
struct workqueue_struct {
	struct list_head	pwqs;		/* WR: all pwqs of this wq */
	struct list_head	list;		/* PR: list of all workqueues */

	struct mutex		mutex;		/* protects this wq */
	int			work_color;	/* WQ: current work color */
	int			flush_color;	/* WQ: current flush color */
	atomic_t		nr_pwqs_to_flush; /* flush in progress */
	struct wq_flusher	*first_flusher;	/* WQ: first flusher */
	struct list_head	flusher_queue;	/* WQ: flush waiters */
	struct list_head	flusher_overflow; /* WQ: flush overflow list */

	struct list_head	maydays;	/* MD: pwqs requesting rescue */
	struct worker		*rescuer;	/* MD: rescue worker */

	int			nr_drainers;	/* WQ: drain in progress */

	int			max_active;	/* WO: max active works */
	int			min_active;	/* WO: min active works */
	int			saved_max_active; /* WQ: saved max_active */
	int			saved_min_active; /* WQ: saved min_active */

	struct workqueue_attrs	*unbound_attrs;	/* PW: only for unbound wqs */
	struct pool_workqueue __rcu *dfl_pwq;   /* PW: only for unbound wqs */

	char			name[WQ_NAME_LEN]; /* I: workqueue name */

	unsigned int		flags ____cacheline_aligned; /* WQ: WQ_* flags */
	struct pool_workqueue __rcu * __percpu *cpu_pwq; /* I: per-cpu pwqs */
	struct wq_node_nr_active *node_nr_active[]; /* I: per-node nr_active */
};
```

注意它**不持有任何工作项**，只负责记账（颜色、flush 状态）和"该用哪个 pwq"的路由。

**③ `pool_workqueue`（pwq）——工作队列与线程池的交汇点**，一个 (workqueue, pool) 二元组。
它才是 `max_active` 真正生效的地方：

```c
struct pool_workqueue {
	struct worker_pool	*pool;		/* I: the associated pool */
	struct workqueue_struct *wq;		/* I: the owning workqueue */
	int			work_color;	/* L: current color */
	int			flush_color;	/* L: flushing color */
	int			refcnt;		/* L: reference count */
	int			nr_in_flight[WORK_NR_COLORS];
						/* L: nr of in_flight works */
	bool			plugged;	/* L: execution suspended */

	int			nr_active;	/* L: nr of active works */
	struct list_head	inactive_works;	/* L: inactive works */
	struct list_head	pending_node;	/* LN: node on wq_node_nr_active->pending_pwqs */
	struct list_head	pwqs_node;	/* WR: node on wq->pwqs */
	struct list_head	mayday_node;	/* MD: node on wq->maydays */

	u64			stats[PWQ_NR_STATS];
	struct kthread_work	release_work;
	struct rcu_head		rcu;
} __aligned(1 << WORK_STRUCT_PWQ_SHIFT);
```

`inactive_works` 是关键：超过 `max_active` 的工作项不是丢掉，而是排在这里等着。

**④ `worker_pool`——真正的线程池**，持有待办链表和一群 worker：

```c
struct worker_pool {
	raw_spinlock_t		lock;		/* the pool lock */
	int			cpu;		/* I: the associated cpu */
	int			node;		/* I: the associated node ID */
	int			id;		/* I: pool ID */
	unsigned int		flags;		/* L: flags */

	unsigned long		watchdog_ts;	/* L: watchdog timestamp */
	bool			cpu_stall;	/* WD: stalled cpu bound pool */

	int			nr_running;

	struct list_head	worklist;	/* L: list of pending works */

	int			nr_workers;	/* L: total number of workers */
	int			nr_idle;	/* L: currently idle workers */

	struct list_head	idle_list;	/* L: list of idle workers */
	struct timer_list	idle_timer;	/* L: worker idle timeout */
	struct work_struct      idle_cull_work; /* L: worker idle cleanup */

	struct timer_list	mayday_timer;	  /* L: SOS timer for workers */

	DECLARE_HASHTABLE(busy_hash, BUSY_WORKER_HASH_ORDER);

	struct worker		*manager;	/* L: purely informational */
	struct list_head	workers;	/* A: attached workers */

	struct ida		worker_ida;	/* worker IDs for task name */

	struct workqueue_attrs	*attrs;		/* I: worker attributes */
	struct hlist_node	hash_node;	/* PL: unbound_pool_hash node */
	int			refcnt;		/* PL: refcnt for unbound pools */
	struct rcu_head		rcu;
};
```

`nr_running` 是并发管理的核心变量，下一节会讲它怎么算。

**⑤ `worker`——干活的线程本体**（在 `kernel/workqueue_internal.h`，不对外暴露）：

```c
struct worker {
	/* on idle list while idle, on busy hash table while busy */
	union {
		struct list_head	entry;	/* L: while idle */
		struct hlist_node	hentry;	/* L: while busy */
	};

	struct work_struct	*current_work;	/* K: work being processed and its */
	work_func_t		current_func;	/* K: function */
	struct pool_workqueue	*current_pwq;	/* K: pwq */
	u64			current_at;	/* K: runtime at start or last wakeup */
	unsigned int		current_color;	/* K: color */

	int			sleeping;	/* S: is worker sleeping? */

	work_func_t		last_func;	/* K: last work's fn */

	struct list_head	scheduled;	/* L: scheduled works */

	struct task_struct	*task;		/* I: worker task */
	struct worker_pool	*pool;		/* A: the associated pool */

	unsigned long		last_active;	/* K: last active timestamp */
	unsigned int		flags;		/* L: flags */
	int			id;		/* I: worker id */

	char			desc[WORKER_DESC_LEN];

	struct workqueue_struct	*rescue_wq;	/* I: the workqueue to rescue */
};
```

`current_work` / `current_func` 让内核能反查"某个 work 现在正被谁执行"——这正是
**非重入保证**（同一个 work 不会在多个 CPU 上同时跑）的实现基础。

关系可以这么记：**workqueue 决定用哪个 pwq，pwq 决定去哪个 pool，pool 手里有一群 worker，
worker 是真正的 kworker 线程**。多个 workqueue 可以共享同一个 pool，pool 里的 worker
不挑队列，来什么活干什么活。

## Three Classes of worker pool

**per-CPU pool（默认）**：每个 CPU 两个标准池（`NR_STD_WORKER_POOLS = 2`，普通与高优先级）。
好处是缓存局部性好；坏处是它会**打破 CPU 的空闲状态**——从中断里提交一个工作项，
就会强制这个刚空闲的 CPU 起来干活，不利于省电。

**unbound pool**：不绑 CPU，按属性（nice、cpumask、NUMA 节点）哈希共享，可在 CPU 间迁移，
适合长跑或 CPU 密集的工作。代价是丢失缓存局部性。

**BH pool（6.12 新增）**：per-CPU 的 `bh_worker_pools`，工作在 **softirq 上下文**通过
`irq_work` 触发，因此**不能睡眠**。它给 tasklet 提供了一个现代化的替代接口：

```c
/*
 * We don't want to trap softirq for too long. See MAX_SOFTIRQ_TIME and
 * MAX_SOFTIRQ_RESTART in kernel/softirq.c. These are macros because
 * msecs_to_jiffies() can't be an initializer.
 */
#define BH_WORKER_JIFFIES	msecs_to_jiffies(2)
#define BH_WORKER_RESTARTS	10
```

系统因此多出两个预置队列：`system_bh_wq` 与 `system_bh_highpri_wq`，注释里写得很明白——
"convenience interface to softirq"。

## Creating workqueue

```c
__printf(1, 4) struct workqueue_struct *
alloc_workqueue(const char *fmt, unsigned int flags, int max_active, ...);
```

标志位决定行为：

| 标志 | 含义 |
|---|---|
| `WQ_UNBOUND` | 不绑定 CPU，用 unbound pool |
| `WQ_HIGHPRI` | 高优先级池，worker 的 nice 为 `MIN_NICE`（-20） |
| `WQ_FREEZABLE` | 系统挂起时冻结 |
| `WQ_MEM_RECLAIM` | 可能用于内存回收路径，**会分配 rescuer 线程** |
| `WQ_CPU_INTENSIVE` | CPU 密集，不参与并发管理，交给调度器 |
| `WQ_POWER_EFFICIENT` | 默认 per-cpu，开了 `workqueue.power_efficient` 时转为 unbound |
| `WQ_SYSFS` | 在 sysfs 中可见 |
| `WQ_BH` | 在 softirq 上下文执行，不能睡眠 |

`max_active` 的语义**随队列类型变化**，这点最容易踩坑：

```c
 * For a per-cpu workqueue, @max_active limits the number of in-flight work
 * items for each CPU. e.g. @max_active of 1 indicates that each CPU can be
 * executing at most one work item for the workqueue.
 *
 * For unbound workqueues, @max_active limits the number of in-flight work items
 * for the whole system. e.g. @max_active of 16 indicates that that there can be
 * at most 16 work items executing for the workqueue in the whole system.
 *
 * As sharing the same active counter for an unbound workqueue across multiple
 * NUMA nodes can be expensive, @max_active is distributed to each NUMA node
 * according to the proportion of the number of online CPUs and enforced
 * independently.
 *
 * Depending on online CPU distribution, a node may end up with per-node
 * max_active which is significantly lower than @max_active, which can lead to
 * deadlocks if the per-node concurrency limit is lower than the maximum number
 * of interdependent work items for the workqueue.
```

最后一段是重要的警告：unbound 队列的 `max_active` 会按节点拆分，如果工作项之间**相互依赖**
（A 等工作项等 B 完成），某个节点分到的额度太小就可能自锁。这也是 `min_active`
（默认 `WQ_DFL_MIN_ACTIVE = 8`）存在的原因——它保证一个下限，避免动态调整把并发压到危险区间。

常量上限是 `WQ_MAX_ACTIVE = 512`，默认 `WQ_DFL_ACTIVE = 256`；传 0 即取默认。

常见的几种封装：

```c
#define alloc_ordered_workqueue(fmt, flags, args...)			\
	alloc_workqueue(fmt, WQ_UNBOUND | __WQ_ORDERED | (flags), 1, ##args)

#define create_workqueue(name)						\
	alloc_workqueue("%s", __WQ_LEGACY | WQ_MEM_RECLAIM, 1, (name))
#define create_singlethread_workqueue(name)				\
	alloc_ordered_workqueue("%s", __WQ_LEGACY | WQ_MEM_RECLAIM, name)
```

`alloc_ordered_workqueue()` 就是 `max_active = 1` 的 unbound 队列——**严格串行、按提交顺序执行**，
需要顺序保证时用它。

多数情况其实不必自己建队列，直接用系统预置的：

| 队列 | 用途 |
|---|---|
| `system_wq` | `schedule_work()` 默认用的，多 CPU 多线程 |
| `system_highpri_wq` | 同上但高优先级 |
| `system_long_wq` | 可跑长时间工作（flush 会很慢） |
| `system_unbound_wq` | 不绑 CPU、不做并发管理，有资源就立刻跑 |
| `system_freezable_wq` | 挂起时冻结 |
| `system_power_efficient_wq` | 省电倾向 |
| `system_bh_wq` / `system_bh_highpri_wq` | softirq 上下文执行，不能睡眠 |

`schedule_work()` 就是往 `system_wq` 上提交——所以别往它上面挂长跑任务，
文档明确说"Don't queue works which can run for too long"。

## Submission: From queue_work to worklist

所有提交 API 最终都汇到 `__queue_work()`：

```c
static void __queue_work(int cpu, struct workqueue_struct *wq,
			 struct work_struct *work)
{
	struct pool_workqueue *pwq;
	struct worker_pool *last_pool, *pool;
	unsigned int work_flags;
	unsigned int req_cpu = cpu;

	...
retry:
	/* pwq which will be used unless @work is executing elsewhere */
	if (req_cpu == WORK_CPU_UNBOUND) {
		if (wq->flags & WQ_UNBOUND)
			cpu = wq_select_unbound_cpu(raw_smp_processor_id());
		else
			cpu = raw_smp_processor_id();
	}

	pwq = rcu_dereference(*per_cpu_ptr(wq->cpu_pwq, cpu));
	pool = pwq->pool;

	/*
	 * If @work was previously on a different pool, it might still be
	 * running there, in which case the work needs to be queued on that
	 * pool to guarantee non-reentrancy.
	 *
	 * For ordered workqueue, work items must be queued on the newest pwq
	 * for accurate order management.  Guaranteed order also guarantees
	 * non-reentrancy.  See the comments above unplug_oldest_pwq().
	 */
	last_pool = get_work_pool(work);
	if (last_pool && last_pool != pool && !(wq->flags & __WQ_ORDERED)) {
		struct worker *worker;

		raw_spin_lock(&last_pool->lock);

		worker = find_worker_executing_work(last_pool, work);

		if (worker && worker->current_pwq->wq == wq) {
			pwq = worker->current_pwq;
			pool = pwq->pool;
			WARN_ON_ONCE(pool != last_pool);
		} else {
			/* meh... not running there, queue here */
			raw_spin_unlock(&last_pool->lock);
			raw_spin_lock(&pool->lock);
		}
	} else {
		raw_spin_lock(&pool->lock);
	}
	...
```

中间这段是**非重入保证**：如果这个 work 之前在别的 pool 且**此刻正在被执行**，
就把它排回那个 pool，而不是当前选中的 pool。否则同一个 work 可能在两个 CPU 上同时运行，
那对"一个 work 对应一份数据"的用法来说是灾难。

（注意它对 `__WQ_ORDERED` 队列跳过这段——因为有序队列靠"最新 pwq"就能同时保证顺序与非重入。）

最后是入队与并发额度判定：

```c
	pwq->nr_in_flight[pwq->work_color]++;
	work_flags = work_color_to_flags(pwq->work_color);

	/*
	 * Limit the number of concurrently active work items to max_active.
	 * @work must also queue behind existing inactive work items to maintain
	 * ordering when max_active changes. See wq_adjust_max_active().
	 */
	if (list_empty(&pwq->inactive_works) && pwq_tryinc_nr_active(pwq, false)) {
		if (list_empty(&pool->worklist))
			pool->watchdog_ts = jiffies;

		trace_workqueue_activate_work(work);
		insert_work(pwq, work, &pool->worklist, work_flags);
		kick_pool(pool);
	} else {
		work_flags |= WORK_STRUCT_INACTIVE;
		insert_work(pwq, work, &pwq->inactive_works, work_flags);
	}
```

两条去路很清楚：

- **额度够**（`pwq_tryinc_nr_active()` 成功且没有积压的 inactive 项）→ 插进 `pool->worklist`
  并 `kick_pool()` 唤醒 worker；
- **额度满** → 插进 `pwq->inactive_works` 并打上 `WORK_STRUCT_INACTIVE` 标记，
  等有工作项完成腾出额度后再被激活。

先看 `inactive_works` 是否为空，是为了在 `max_active` 变化时不打乱提交顺序。

## Execution: The Main Loop of worker Threads

worker 就是一个内核线程，主循环在 `worker_thread()`：

```c
static int worker_thread(void *__worker)
{
	struct worker *worker = __worker;
	struct worker_pool *pool = worker->pool;

	/* tell the scheduler that this is a workqueue worker */
	set_pf_worker(true);
woke_up:
	raw_spin_lock_irq(&pool->lock);

	/* am I supposed to die? */
	if (unlikely(worker->flags & WORKER_DIE)) {
		raw_spin_unlock_irq(&pool->lock);
		set_pf_worker(false);
		worker->pool = NULL;
		ida_free(&pool->worker_ida, worker->id);
		return 0;
	}

	worker_leave_idle(worker);
recheck:
	/* no more worker necessary? */
	if (!need_more_worker(pool))
		goto sleep;

	/* do we need to manage? */
	if (unlikely(!may_start_working(pool)) && manage_workers(worker))
		goto recheck;
	...
```

三个判断构成循环骨架：**还有活吗**（`need_more_worker`）、**能开工吗**（`may_start_working`）、
**要不要先当经理去招人**（`manage_workers`）。`set_pf_worker(true)` 给线程打上
`PF_WQ_WORKER` 标志，调度器据此识别它。

真正执行单个工作项的是 `process_one_work()`，它承担了记账、同步与调用：

```c
static void process_one_work(struct worker *worker, struct work_struct *work)
__releases(&pool->lock)
__acquires(&pool->lock)
{
	struct pool_workqueue *pwq = get_work_pwq(work);
	struct worker_pool *pool = worker->pool;
	...
	/* claim and dequeue */
	debug_work_deactivate(work);
	hash_add(pool->busy_hash, &worker->hentry, (unsigned long)work);
	worker->current_work = work;
	worker->current_func = work->func;
	worker->current_pwq = pwq;
	if (worker->task)
		worker->current_at = worker->task->se.sum_exec_runtime;
	work_data = *work_data_bits(work);
	worker->current_color = get_work_color(work_data);

	list_del_init(&work->entry);

	/*
	 * CPU intensive works don't participate in concurrency management.
	 * They're the scheduler's responsibility.  This takes @worker out
	 * of concurrency management and the next code block will chain
	 * execution of the pending work items.
	 */
	if (unlikely(pwq->wq->flags & WQ_CPU_INTENSIVE))
		worker_set_flags(worker, WORKER_CPU_INTENSIVE);

	kick_pool(pool);

	set_work_pool_and_clear_pending(work, pool->id, pool_offq_flags(pool));

	pwq->stats[PWQ_STAT_STARTED]++;
	raw_spin_unlock_irq(&pool->lock);
	...
	trace_workqueue_execute_start(work);
	worker->current_func(work);
	trace_workqueue_execute_end(work, worker->current_func);
	pwq->stats[PWQ_STAT_COMPLETED]++;
	...
```

顺序值得留意：先把 worker 挂进 `busy_hash`（让 `find_worker_executing_work()` 能找到它，
从而保证非重入），再**释放 pool 锁**后才调用工作函数——因此工作函数可以睡眠。
`clear_pending` 在持锁、关中断下完成，保证 PENDING 位与入队状态不会被竞争撕裂。

一个 worker 可能一次被派发多个工作项（在 `worker->scheduled` 链表上），由
`process_scheduled_works()` 逐个跑完：

```c
static void process_scheduled_works(struct worker *worker)
{
	struct work_struct *work;
	bool first = true;

	while ((work = list_first_entry_or_null(&worker->scheduled,
						struct work_struct, entry))) {
		if (first) {
			worker->pool->watchdog_ts = jiffies;
			first = false;
		}
		process_one_work(worker, work);
	}
}
```

## Concurrency Management CMWQ

"需要几个线程"是 workqueue 最核心的设计问题。早期实现是每个队列固定几个线程，
结果要么不够用、要么浪费。现代内核用 **CMWQ（Concurrency Managed Workqueue）**：
**按需创建 worker，谁睡了就补一个**，全部由一组策略函数决定。

```c
/*
 * Policy functions.  These define the policies on how the global worker
 * pools are managed.  Unless noted otherwise, these functions assume that
 * they're being called with pool->lock held.
 */

/*
 * Need to wake up a worker?  Called from anything but currently
 * running workers.
 *
 * Note that, because unbound workers never contribute to nr_running, this
 * function will always return %true for unbound pools as long as the
 * worklist isn't empty.
 */
static bool need_more_worker(struct worker_pool *pool)
{
	return !list_empty(&pool->worklist) && !pool->nr_running;
}

/* Can I start working?  Called from busy but !running workers. */
static bool may_start_working(struct worker_pool *pool)
{
	return pool->nr_idle;
}

/* Do I need to keep working?  Called from currently running workers. */
static bool keep_working(struct worker_pool *pool)
{
	return !list_empty(&pool->worklist) && (pool->nr_running <= 1);
}

/* Do we need a new worker?  Called from manager. */
static bool need_to_create_worker(struct worker_pool *pool)
{
	return need_more_worker(pool) && !may_start_working(pool);
}

/* Do we have too many workers and should some go away? */
static bool too_many_workers(struct worker_pool *pool)
{
	bool managing = pool->flags & POOL_MANAGER_ACTIVE;
	int nr_idle = pool->nr_idle + managing; /* manager is considered idle */
	int nr_busy = pool->nr_workers - nr_idle;

	return nr_idle > 2 && (nr_idle - 2) * MAX_IDLE_WORKERS_RATIO >= nr_busy;
}
```

关键在于 `nr_running` 统计的是**正在运行（未睡眠）的 worker 数**，不是"忙着的 worker 数"。
区分这两者是 CMWQ 的精髓：一个 worker 在等 I/O 睡眠了，它占着线程但没占 CPU，
这时**应该**再起一个 worker 去跑队列里的其他工作。

这个计数靠调度器回调维护——worker 睡下和起来时各通知一次：

```c
void wq_worker_sleeping(struct task_struct *task)
{
	struct worker *worker = kthread_data(task);
	struct worker_pool *pool;
	...
	WRITE_ONCE(worker->sleeping, 1);
	raw_spin_lock_irq(&pool->lock);
	...
	pool->nr_running--;
	if (kick_pool(pool))
		worker->current_pwq->stats[PWQ_STAT_CM_WAKEUP]++;

	raw_spin_unlock_irq(&pool->lock);
}
```

`nr_running--` 之后紧跟 `kick_pool()`——睡下一个就立刻补位。反向的 `wq_worker_running()`
在 worker 被唤醒回到 `schedule()` 之后把计数加回去。

所以完整的因果链是：**有活 + 没人真在跑 → `need_more_worker()` → 唤醒 idle worker
或新建 worker → 干活 → 谁睡了 `nr_running--` → 再补一个 → 队列空了 → worker 进 idle_list
→ 空闲超过 `IDLE_WORKER_TIMEOUT`（300 秒）或 `too_many_workers()` 成立 → 销毁回收。**

`too_many_workers()` 的判据是"空闲数超过 2，且（空闲数-2）× 4 ≥ 忙着的数"——
即空闲线程最多约为忙线程的 1/4（`MAX_IDLE_WORKERS_RATIO = 4`）。

还有一个自动保护：CPU 密集的工作项会拖死并发管理（它占着 worker 不睡，`nr_running` 不降），
所以内核会自己检测并把它划出去，交给调度器处理：

```c
void wq_worker_tick(struct task_struct *task)
{
	...
	pwq->stats[PWQ_STAT_CPU_TIME] += TICK_USEC;

	if (!wq_cpu_intensive_thresh_us)
		return;

	/*
	 * If the current worker is concurrency managed and hogged the CPU for
	 * longer than wq_cpu_intensive_thresh_us, it's automatically marked
	 * CPU_INTENSIVE to avoid stalling other concurrency-managed work items.
	 */
	...
}
```

## Fallback: rescuer and mayday

有一个场景会让 CMWQ 死锁：**内存回收路径要用到 workqueue**，但创建新 worker 本身
需要分配内存。内存紧张时"分配 worker → 要回收 → 回收要用 workqueue → 需要 worker"，
循环等待。`WQ_MEM_RECLAIM` 标志就是用来打破它的——带此标志的队列会额外配一个
**rescuer 线程**，它是队列创建时就建好的，不依赖运行时分配。

当某个 pwq 发现"有活但迟迟没人跑"时，会发求救信号：

```c
static void send_mayday(struct work_struct *work)
{
	...
	if (!wq->rescuer)
		return;

	/* mayday mayday mayday */
	if (list_empty(&pwq->mayday_node)) {
		...
		list_add_tail(&pwq->mayday_node, &wq->maydays);
		wake_up_process(wq->rescuer->task);
	}
}
```

求救由定时器兜底触发（`pool->mayday_timer`，初始 10ms、之后每 100ms 重试一次），
对应常量 `MAYDAY_INITIAL_TIMEOUT` 与 `MAYDAY_INTERVAL`。rescuer 线程醒来后
亲自执行队首的工作项，把局面解开。它的 nice 是 `RESCUER_NICE_LEVEL`（即 `MIN_NICE`），
保证救援动作优先执行。

统计里有专门的 `PWQ_STAT_MAYDAY` 与 `PWQ_STAT_RESCUED` 两个计数——正常运行的系统里
它们应该始终为 0，非 0 说明发生过资源危机。

## Control and Observation

**等待与取消**是调用方最常用的操作：`flush_work()` 等某个工作项跑完，
`flush_workqueue()` 等队列清空，`cancel_work_sync()` / `cancel_delayed_work_sync()`
取消并等待已在运行的结束。它们靠 pwq 的**颜色机制**实现——`work_color` 与 `flush_color`
把工作项分批着色，flush 只需等某一批之前的全部排空，不必逐个追踪。

**观测**有几条路径：

- `pool_workqueue.stats[]` 是 per-pwq 的计数器数组（`PWQ_STAT_STARTED`、`COMPLETED`、
  `CPU_TIME`、`CPU_INTENSIVE`、`CM_WAKEUP`、`REPATRIATED`、`MAYDAY`、`RESCUED`），
  内核自带 `tools/workqueue/wq_monitor.py` 直接读它们；
- `WQ_SYSFS` 让队列在 sysfs 中可见；
- 开 `CONFIG_WQ_WATCHDOG` 后，`pool->watchdog_ts` 与 `pool->cpu_stall` 会记录
  "队列有活但长时间没人跑"的卡死情况；
- `CONFIG_DEBUG_OBJECTS_WORK` 与 lockdep 会校验 work 的生命周期与锁依赖，
  `process_one_work()` 末尾还会检查工作函数有没有泄漏 atomic/RCU/锁。

## Boundaries with Other Subsystems

- **中断与 softirq**：上半部提交工作是最典型用法；6.12 起 `WQ_BH` / `system_bh_wq`
  把工作放回 softirq 上下文，与 [softirq](/docs/CS/OS/Linux/Interrupt.md?id=softirq) 直接衔接。
- **调度器**：worker 就是普通任务，带 `PF_WQ_WORKER` 标志，受 [调度器](/docs/CS/OS/Linux/proc/sche.md)
  统一管理——包括 6.12 起若装载了 [sched_ext](/docs/CS/OS/Linux/proc/sched_ext.md) 调度器，
  kworker 也会被它接管。反过来，调度器通过 `wq_worker_running/sleeping/tick`
  三个钩子把睡眠事件回喂给 CMWQ，这是双向协作。
- **内核线程**：worker 由 kthread 创建，见 [进程表示与内核线程](/docs/CS/OS/Linux/proc/process.md)。
- **内存回收**：`WQ_MEM_RECLAIM` 是给 [内存回收](/docs/CS/OS/Linux/mm/Reclaim.md) 路径准备的，
  必须标，否则回收路径上新建 worker 可能自锁。
- **电源管理**：`WQ_FREEZABLE` 用于挂起冻结，`WQ_POWER_EFFICIENT` 让 per-cpu 队列在
  开启省电模式时转为 unbound，避免打断 CPU 空闲。
- **定时器**：`delayed_work` 依赖 [timer](/docs/CS/OS/Linux/timer.md) 实现延后提交。

## Links

- [Linux 内核总览](/docs/CS/OS/Linux/Linux.md)
- [进程链路总览](/docs/CS/OS/Linux/proc/README.md)

## References

1. [Concurrency Managed Workqueue — The Linux Kernel documentation](https://www.kernel.org/doc/html/latest/core-api/workqueue.html)
2. [kernel/workqueue.c — Linux source](https://git.kernel.org/pub/scm/linux/kernel/git/torvalds/linux.git/tree/kernel/workqueue.c)
