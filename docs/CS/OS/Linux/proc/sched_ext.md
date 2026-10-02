## Introduction

Linux 的调度策略长期只有一条迭代路径：改 CFS、说服上游、重编内核。这条路对数据中心、桌面交互、游戏、
异构大小核这些诉求截然不同的场景一样低效——每种场景都想要自己的调度器，但内核只能装一个。

**sched_ext**（6.12 合入，`CONFIG_SCHED_CLASS_EXT`）给出另一条路：把调度策略本身搬到 BPF 程序里。
内核提供一个**可扩展调度类**，只负责安全地调用回调、记账、兜底；"下一个该谁跑"完全交给用户态加载的
BPF 程序决定。策略可以在线替换、崩溃自动回退，而实时类、deadline 类的语义完全不动。

它接的是 [调度器演进主线](/docs/CS/OS/Linux/proc/sche.md?id=scheduler) 的最后一棒：O(n) → O(1) → CFS →
**EEVDF** → 再到此处——前四代都是"内核里写死一个更好的通用策略"，sched_ext 则干脆把策略交出去，
让 [fair](/docs/CS/OS/Linux/proc/fair.md) 与自研策略可以并存切换。

## Motivation

为什么非得做成 BPF 调度类，而不是又一个内核调度器：

| 诉求 | 写死在内核里 | sched_ext |
|---|---|---|
| 上线一个新策略 | 改 `kernel/sched/`、全量重编、重启 | 编译一个 BPF 对象，加载即生效 |
| 策略有 bug | 整机卡死，只能重启 | 看门狗检测 stall → 自动卸载 → 回落内置策略 |
| 多种场景共存 | 只能留一套妥协方案 | 按机器角色装载不同调度器，秒级切换 |
| 安全保证 | 靠 review | BPF verifier 静态校验 + 内核兜底回退 |
| 迭代实验 | 每次都要发内核补丁 | 用户态仓库独立演进（如 `scx` 项目） |

代价是抽象层开销与 verifier 的表达限制，所以它的定位不是"取代 CFS"，而是**让 CFS 之外的策略有活路**。

## Class placement

理解 sched_ext 最容易踩坑的一点：**ext 类在调度类链表里的位置比 fair 低**，不是比 fair 高。
调度类由 `DEFINE_SCHED_CLASS()` 放进各自的 section，再由链接脚本**逆序**排布：

```c
/* kernel/sched/sched.h */
#define DEFINE_SCHED_CLASS(name) \
const struct sched_class name##_sched_class \
	__aligned(__alignof__(struct sched_class)) \
	__section("__" #name "_sched_class")
```

排布结果是 `rt → fair → ext → idle`。ext 之所以能接管普通任务，靠的是遍历时的**条件跳过**：

```c
/*
 * Iterate only active classes. SCX can take over all fair tasks or be
 * completely disabled. If the former, skip fair. If the latter, skip SCX.
 */
static inline const struct sched_class *next_active_class(const struct sched_class *class)
{
	class++;
#ifdef CONFIG_SCHED_CLASS_EXT
	if (scx_switched_all() && class == &fair_sched_class)
		class++;
	if (!scx_enabled() && class == &ext_sched_class)
		class++;
#endif
	return class;
}
```

两个 static key 决定了遍历行为：

```c
DECLARE_STATIC_KEY_FALSE(__scx_ops_enabled);	/* SCX BPF scheduler loaded */
DECLARE_STATIC_KEY_FALSE(__scx_switched_all);	/* all fair class tasks on SCX */

#define scx_enabled()		static_branch_unlikely(&__scx_ops_enabled)
#define scx_switched_all()	static_branch_unlikely(&__scx_switched_all)
```

- 没装载 BPF 调度器时 `scx_enabled()` 为假，遍历直接跳过 ext，等于它不存在——**零开销**；
- 装载且所有普通任务切过去后 `scx_switched_all()` 为真，遍历跳过 fair，普通任务全走 ext。

由此得出与相邻类的关系：**实时类与 deadline 类永远在 ext 之上**（见 [rt](/docs/CS/OS/Linux/proc/rt.md)），
FIFO/RR/DEADLINE 任务照旧绝对优先，SCX 只接管 `SCHED_NORMAL` 这一档。这也解释了为什么 SCX 调度器写坏了
不至于让 `sshd` 之外的一切都停摆——rt 任务仍然能被调度。

## sched_ext_entity

每个受 SCX 调度的任务，`task_struct` 里嵌一个 `sched_ext_entity`（`include/linux/sched/ext.h`）：

```c
/*
 * The following is embedded in task_struct and contains all fields necessary
 * for a task to be scheduled by SCX.
 */
struct sched_ext_entity {
	struct scx_dispatch_q	*dsq;
	struct scx_dsq_list_node dsq_list;	/* dispatch order */
	struct rb_node		dsq_priq;	/* p->scx.dsq_vtime order */
	u32			dsq_seq;
	u32			dsq_flags;	/* protected by DSQ lock */
	u32			flags;		/* protected by rq lock */
	u32			weight;
	s32			sticky_cpu;
	s32			holding_cpu;
	u32			kf_mask;	/* see scx_kf_mask above */
	struct task_struct	*kf_tasks[2];	/* see SCX_CALL_OP_TASK() */
	atomic_long_t		ops_state;

	struct list_head	runnable_node;	/* rq->scx.runnable_list */
	unsigned long		runnable_at;

	u64			ddsp_dsq_id;
	u64			ddsp_enq_flags;

	/* BPF scheduler modifiable fields */
	u64			slice;
	u64			dsq_vtime;
	bool			disallow;	/* reject switching into SCX */
	struct list_head	tasks_node;
};
```

其中几项是理解调度器的钥匙：

- **`slice`**：本轮可运行的纳秒预算，内核随执行递减，耗尽则触发一次调度；置 `SCX_SLICE_INF`（`U64_MAX`）
  表示永不过期，调度器必须自己 `scx_bpf_kick_cpu()` 踢一下。默认 `SCX_SLICE_DFL` 是 20ms。
- **`dsq_vtime`**：派发到 vtime 优先队列时的排序键，按 `time_before64()` 比较（会绕回）。
- **`weight`**：由内核在 `ops.enable()` 之前按 `static_prio` 换算好，BPF 侧只读取或响应 `ops.set_weight()`。
- **`runnable_at`**：进入可运行态的时刻，看门狗靠它判断任务是不是"饿了太久"。
- **`disallow`**：在 `ops.init_task()` 里置位，可以拒绝某个任务再被 `sched_setscheduler()` 切进 SCX。

任务在 SCX 里的状态由 `flags` 的高位承载，是一台小状态机：

```c
enum scx_task_state {
	SCX_TASK_NONE,		/* ops.init_task() not called yet */
	SCX_TASK_INIT,		/* ops.init_task() succeeded, but task can be cancelled */
	SCX_TASK_READY,		/* fully initialized, but not in sched_ext */
	SCX_TASK_ENABLED,	/* fully initialized and in sched_ext */
	SCX_TASK_NR_STATES,
};
```

`scx_ops_enable_task()` 在设置好 weight 后调用 `ops.enable()`，随后才把状态置为 `SCX_TASK_ENABLED`：
先让 BPF 侧看到一致的 weight，再交出调度权。

## scx_rq and DSQ

每个 runqueue 有一份 SCX 私有状态（`kernel/sched/sched.h`）：

```c
struct scx_rq {
	struct scx_dispatch_q	local_dsq;
	struct list_head	runnable_list;		/* runnable tasks on this rq */
	struct list_head	ddsp_deferred_locals;	/* deferred ddsps from enq */
	unsigned long		ops_qseq;
	u64			extra_enq_flags;	/* see move_task_to_local_dsq() */
	u32			nr_running;
	u32			flags;
	u32			cpuperf_target;		/* [0, SCHED_CAPACITY_SCALE] */
	bool			cpu_released;
	cpumask_var_t		cpus_to_kick;
	cpumask_var_t		cpus_to_kick_if_idle;
	cpumask_var_t		cpus_to_preempt;
	cpumask_var_t		cpus_to_wait;
	unsigned long		pnt_seq;
	struct balance_callback	deferred_bal_cb;
	struct irq_work		deferred_irq_work;
	struct irq_work		kick_cpus_irq_work;
};
```

真正装任务的是 **DSQ（dispatch queue）**，它是内核与 BPF 调度器之间的缓冲层：

```c
struct scx_dispatch_q {
	raw_spinlock_t		lock;
	struct list_head	list;	/* tasks in dispatch order */
	struct rb_root		priq;	/* used to order by p->scx.dsq_vtime */
	u32			nr;
	u32			seq;	/* used by BPF iter */
	u64			id;
	struct rhash_head	hash_node;
	struct llist_node	free_node;
	struct rcu_head		rcu;
};
```

一个 DSQ 同时具备**两种顺序**：`list` 是 FIFO，`priq` 是按 `dsq_vtime` 排序的红黑树；
内建 DSQ 恒为 FIFO，vtime 排序只对 BPF 自建 DSQ 有意义（`scx_bpf_dispatch_vtime()`）。

DSQ 的 ID 是一个 64 位编码，高位区分内建与自建：

```c
enum scx_dsq_id_flags {
	SCX_DSQ_FLAG_BUILTIN	= 1LLU << 63,
	SCX_DSQ_FLAG_LOCAL_ON	= 1LLU << 62,

	SCX_DSQ_INVALID		= SCX_DSQ_FLAG_BUILTIN | 0,
	SCX_DSQ_GLOBAL		= SCX_DSQ_FLAG_BUILTIN | 1,
	SCX_DSQ_LOCAL		= SCX_DSQ_FLAG_BUILTIN | 2,
	SCX_DSQ_LOCAL_ON	= SCX_DSQ_FLAG_BUILTIN | SCX_DSQ_FLAG_LOCAL_ON,
	SCX_DSQ_LOCAL_CPU_MASK	= 0xffffffffLLU,
};
```

- `SCX_DSQ_LOCAL`：派发到**当前** CPU 的本地 DSQ，最常见的快速路径；
- `SCX_DSQ_LOCAL_ON | cpu`：派发到**指定** CPU 的本地 DSQ；
- `SCX_DSQ_GLOBAL`：全局 FIFO，所有 CPU 都能消费，适合做兜底；
- 其余 ID 由 `scx_bpf_create_dsq()` 自建，可指定 NUMA 节点。

于是形成两层派发结构：**BPF 调度器持有任务**（它自己的 map / 列表）→ 需要时 `scx_bpf_dispatch()`
投进某个 DSQ → CPU 本地 DSQ 为空时触发 `ops.dispatch()` → 从 DSQ 里挑任务执行。
本地 DSQ 的存在让"选谁"与"谁跑"解耦，BPF 侧批量派发、内核侧逐个消费。

## sched_ext_ops

BPF 调度器的全部能力就是一张回调表 `struct sched_ext_ops`（定义在 `kernel/sched/ext.c`，
通过 BTF 暴露为 BPF `struct_ops`）。按用途分组：

| 组 | 回调 | 作用 |
|---|---|---|
| 放置与派发 | `select_cpu` | 唤醒时挑目标 CPU，可直接派发 |
| | `enqueue` / `dequeue` | 任务进出 BPF 调度器 |
| | `dispatch` | 本地 DSQ 空时补货（派发或消费用户 DSQ） |
| 状态通知 | `runnable` / `running` / `stopping` / `quiescent` | 任务状态迁移的四段通知 |
| 周期性 | `tick` | 每 1/HZ 触发，可把 `slice` 置 0 强制重调度 |
| | `yield` / `core_sched_before` | 让出 CPU；core scheduling 排序 |
| 属性变更 | `set_weight` / `set_cpumask` / `update_idle` | 权重、亲和、空闲跟踪 |
| CPU 生命周期 | `cpu_acquire` / `cpu_release` / `cpu_online` / `cpu_offline` | CPU 被抢占、归还、热插拔 |
| 任务生命周期 | `init_task` / `exit_task` / `enable` / `disable` | 初始化、退出、进出 SCX |
| cgroup（`CONFIG_EXT_GROUP_SCHED`） | `cgroup_init` / `cgroup_exit` / `cgroup_prep_move` / `cgroup_move` / `cgroup_cancel_move` / `cgroup_set_weight` | cgroup 感知的调度 |
| 调试 | `dump` / `dump_cpu` / `dump_task` | 出错时导出调度器内部状态 |
| 装载 | `init` / `exit` | 调度器自身初始化与清理 |

表尾还有几个标量字段：

```c
	/**
	 * dispatch_max_batch - Max nr of tasks that dispatch() can dispatch
	 */
	u32 dispatch_max_batch;

	/**
	 * flags - %SCX_OPS_* flags
	 */
	u64 flags;

	/**
	 * timeout_ms - The maximum amount of time, in milliseconds, that a
	 * runnable task should be able to wait before being scheduled. The
	 * maximum timeout may not exceed the default timeout of 30 seconds.
	 *
	 * Defaults to the maximum allowed timeout value of 30 seconds.
	 */
	u32 timeout_ms;
	u32 exit_dump_len;
	u64 hotplug_seq;
	char name[SCX_OPS_NAME_LEN];
};
```

`timeout_ms` 是调度器对内核的**承诺**：任何可运行任务最多等这么久；默认 30 秒，上限也是 30 秒。
它直接喂给下面的看门狗。

`name` 会成为这个调度器的标识，`SCX_OPS_NAME_LEN` 为 128。

## 生命周期

一个普通任务从诞生到退场，SCX 侧的调用序列是：

1. **fork** → `scx_pre_fork()` / `scx_fork()` / `scx_post_fork()`，其中调用 `ops.init_task()`。
   这一步**可能阻塞**（可用作分配），失败会直接中止该次 fork。
2. **唤醒** → `ops.select_cpu(p, prev_cpu, wake_flags)`。这里返回空闲 CPU 会顺带把该 CPU 踢醒；
   也可以直接 `scx_bpf_dispatch()` 派发——一旦在此处派发，随后的 `ops.enqueue()` 会被跳过。
3. **入队** → 若未在上一步派发，调用 `ops.enqueue(p, enq_flags)`。此时任务归 BPF 调度器所有，
   **它若始终不派发，任务就饿着**——这正是看门狗要盯的事。
4. **派发** → CPU 的本地 DSQ 空时调用 `ops.dispatch(cpu, prev)`，调度器用 `scx_bpf_dispatch()`
   投任务，或用 `scx_bpf_consume()` 把用户 DSQ 里的任务搬进本地 DSQ。
   单次最多派发 `dispatch_max_batch` 个，`consume` 会刷新计数。
5. **运行** → `ops.running(p)`；运行期间 `ops.tick(p)` 每 tick 一次；被抢占或时间片耗尽时
   `ops.stopping(p, runnable)`；彻底不跑时 `ops.quiescent(p, deq_flags)`。
6. **退出** → `ops.disable(p)`（离开 SCX 或调度器卸载）与 `ops.exit_task(p)`。

注意 `runnable/enqueue` 与 `quiescent/dequeue` 是**相关但不耦合**的两组：前者通知状态迁移，后者管理
调度器内部的队列归属。任务可能被 `enqueue` 而没有先 `runnable`（时间片耗尽后重新入队），也可能
`runnable` 之后没有 `enqueue`（派发到远端 CPU）。

## kfunc

BPF 侧不能随意调内核函数，只能调 SCX 显式导出的 kfunc。常用的几类：

| 类别 | kfunc |
|---|---|
| 派发 | `scx_bpf_dispatch`、`scx_bpf_dispatch_vtime`、`scx_bpf_dispatch_from_dsq`、`scx_bpf_consume` |
| DSQ 管理 | `scx_bpf_create_dsq`、`scx_bpf_destroy_dsq`、`scx_bpf_dsq_nr_queued` |
| CPU 选择 | `scx_bpf_select_cpu_dfl`、`scx_bpf_pick_idle_cpu`、`scx_bpf_pick_any_cpu`、`scx_bpf_test_and_clear_cpu_idle` |
| 唤醒控制 | `scx_bpf_kick_cpu` |
| 拓扑与 cpumask | `scx_bpf_nr_cpu_ids`、`scx_bpf_get_possible_cpumask`、`scx_bpf_get_online_cpumask`、`scx_bpf_get_idle_cpumask`、`scx_bpf_get_idle_smtmask` |
| 性能域 | `scx_bpf_cpuperf_cap`、`scx_bpf_cpuperf_cur`、`scx_bpf_cpuperf_set` |
| 中止与调试 | `scx_bpf_exit_bstr`、`scx_bpf_error_bstr`、`scx_bpf_dump_bstr` |

派发函数的语义值得单独说清楚：

```c
/**
 * scx_bpf_dispatch - Dispatch a task into the FIFO queue of a DSQ
 * @p: task_struct to dispatch
 * @dsq_id: DSQ to dispatch to
 * @slice: duration @p can run for in nsecs, 0 to keep the current value
 * @enq_flags: SCX_ENQ_*
 *
 * Dispatch @p into the FIFO queue of the DSQ identified by @dsq_id. It is safe
 * to call this function spuriously. Can be called from ops.enqueue(),
 * ops.select_cpu(), and ops.dispatch().
 *
 * When called from ops.select_cpu() or ops.enqueue(), it's for direct dispatch
 * and @p must match the task being enqueued. Also, %SCX_DSQ_LOCAL_ON can't be
 * used to target the local DSQ of a CPU other than the enqueueing one. Use
 * ops.select_cpu() to be on the target CPU in the first place.
 *
 * When called from ops.dispatch(), there are no restrictions on @p or @dsq_id
 * and this function can be called upto ops.dispatch_max_batch times to dispatch
 * multiple tasks. scx_bpf_dispatch_nr_slots() returns the number of the
 * remaining slots. scx_bpf_consume() flushes the batch and resets the counter.
 *
 * @p is allowed to run for @slice. The scheduling path is triggered on slice
 * exhaustion. If zero, the current residual slice is maintained. If
 * %SCX_SLICE_INF, @p never expires and the BPF scheduler must kick the CPU with
 * scx_bpf_kick_cpu() to trigger scheduling.
 */
__bpf_kfunc void scx_bpf_dispatch(struct task_struct *p, u64 dsq_id, u64 slice,
				  u64 enq_flags)
```

关键约束有三条：**同一回调里能调什么 kfunc 是受限的**（`ops.dispatch()` 里最自由）、
**直接派发时目标必须是当前入队任务**、`slice` 为 0 表示保留剩余额度。

这个上下文限制由 `scx_entity.kf_mask` 跟踪，内核把 kfunc 分成几组：

```c
enum scx_kf_mask {
	SCX_KF_UNLOCKED		= 0,	  /* sleepable and not rq locked */
	/* ENQUEUE and DISPATCH may be nested inside CPU_RELEASE */
	SCX_KF_CPU_RELEASE	= 1 << 0, /* ops.cpu_release() */
	SCX_KF_DISPATCH		= 1 << 1, /* ops.dispatch() */
	SCX_KF_ENQUEUE		= 1 << 2, /* ops.enqueue() and ops.select_cpu() */
	SCX_KF_SELECT_CPU	= 1 << 3, /* ops.select_cpu() */
	SCX_KF_REST		= 1 << 4, /* other rq-locked operations */
};
```

## 安全网

把调度策略交给第三方代码，最大的风险是**调度器写错导致整机停摆**。sched_ext 用两层兜底化解：
看门狗负责发现，卸载路径负责恢复。

看门狗盯着每个 rq 的 `runnable_list`，比较 `p->scx.runnable_at` 与 `scx_watchdog_timeout`
（来自 `ops.timeout_ms`）：

```c
static bool check_rq_for_timeouts(struct rq *rq)
{
	struct task_struct *p;
	struct rq_flags rf;
	bool timed_out = false;

	rq_lock_irqsave(rq, &rf);
	list_for_each_entry(p, &rq->scx.runnable_list, scx.runnable_node) {
		unsigned long last_runnable = p->scx.runnable_at;

		if (unlikely(time_after(jiffies,
					last_runnable + scx_watchdog_timeout))) {
			u32 dur_ms = jiffies_to_msecs(jiffies - last_runnable);

			scx_ops_error_kind(SCX_EXIT_ERROR_STALL,
					   "%s[%d] failed to run for %u.%03us",
					   p->comm, p->pid,
					   dur_ms / 1000, dur_ms % 1000);
			timed_out = true;
			break;
		}
	}
	rq_unlock_irqrestore(rq, &rf);

	return timed_out;
}
```

它由 `scx_watchdog_workfn()` 挂在 `system_unbound_wq` 上定期跑（`scx_watchdog_timeout / 2` 一次）。
此外 `scx_tick()` 还会检查**看门狗自己**有没有按时打卡——避免看门狗本身被饿死而失效：

```c
void scx_tick(struct rq *rq)
{
	unsigned long last_check;

	if (!scx_enabled())
		return;

	last_check = READ_ONCE(scx_watchdog_timestamp);
	if (unlikely(time_after(jiffies,
				last_check + READ_ONCE(scx_watchdog_timeout)))) {
		u32 dur_ms = jiffies_to_msecs(jiffies - last_check);

		scx_ops_error_kind(SCX_EXIT_ERROR_STALL,
				   "watchdog failed to check in for %u.%03us",
				   dur_ms / 1000, dur_ms % 1000);
	}

	update_other_load_avgs(rq);
}
```

一旦触发，整个 BPF 调度器被卸载，退出原因记录在 `enum scx_exit_kind`：

```c
enum scx_exit_kind {
	SCX_EXIT_NONE,
	SCX_EXIT_DONE,

	SCX_EXIT_UNREG = 64,	/* user-space initiated unregistration */
	SCX_EXIT_UNREG_BPF,	/* BPF-initiated unregistration */
	SCX_EXIT_UNREG_KERN,	/* kernel-initiated unregistration */
	SCX_EXIT_SYSRQ,		/* requested by 'S' sysrq */

	SCX_EXIT_ERROR = 1024,	/* runtime error, error msg contains details */
	SCX_EXIT_ERROR_BPF,	/* ERROR but triggered through scx_bpf_error() */
	SCX_EXIT_ERROR_STALL,	/* watchdog detected stalled runnable tasks */
};
```

前四类是**正常退出**（用户态主动卸载、sysrq-S 强制卸载），后三类是**出错退出**。
无论哪种，卸载过程都走同一条路：进入 bypass 状态，让所有 SCX 任务尽快回到内置
[fair](/docs/CS/OS/Linux/proc/fair.md) 类。bypass 期间内核不再信任 BPF 侧的 slice 管理，
直接把时间片清零逼出调度点：

```c
static void task_tick_scx(struct rq *rq, struct task_struct *curr, int queued)
{
	update_curr_scx(rq);

	/*
	 * While disabling, always resched and refresh core-sched timestamp as
	 * we can't trust the slice management or ops.core_sched_before().
	 */
	if (scx_rq_bypassing(rq)) {
		curr->scx.slice = 0;
		touch_core_sched(rq, curr);
	} else if (SCX_HAS_OP(tick)) {
		SCX_CALL_OP(SCX_KF_REST, tick, curr);
	}

	if (!curr->scx.slice)
		resched_curr(rq);
}
```

这套设计让"试一个新调度器"的代价上限变得可接受：最坏情况是卡 `timeout_ms` 毫秒后自动回落。

## 实例：scx_simple

内核自带的 `tools/sched_ext/scx_simple.bpf.c` 是最短的完整范例——默认实现**全局加权 vtime 公平调度**，
也可切到 FIFO。先看骨架：

```c
/*
 * Built-in DSQs such as SCX_DSQ_GLOBAL cannot be used as priority queues
 * (meaning, cannot be dispatched to with scx_bpf_dispatch_vtime()). We
 * therefore create a separate DSQ with ID 0 that we dispatch to and consume
 * from. If scx_simple only supported global FIFO scheduling, then we could
 * just use SCX_DSQ_GLOBAL.
 */
#define SHARED_DSQ 0

s32 BPF_STRUCT_OPS(simple_select_cpu, struct task_struct *p, s32 prev_cpu, u64 wake_flags)
{
	bool is_idle = false;
	s32 cpu;

	cpu = scx_bpf_select_cpu_dfl(p, prev_cpu, wake_flags, &is_idle);
	if (is_idle) {
		stat_inc(0);	/* count local queueing */
		scx_bpf_dispatch(p, SCX_DSQ_LOCAL, SCX_SLICE_DFL, 0);
	}

	return cpu;
}
```

唤醒路径上：先用内核默认策略挑 CPU，若挑到的是**空闲 CPU**，就地直接派发到本地 DSQ
（`ops.enqueue()` 随之被跳过）。这是最常见的快速路径——大部分唤醒都能就地消化。

否则走全局队列，按 FIFO 或 vtime 两种模式派发：

```c
void BPF_STRUCT_OPS(simple_enqueue, struct task_struct *p, u64 enq_flags)
{
	stat_inc(1);	/* count global queueing */

	if (fifo_sched) {
		scx_bpf_dispatch(p, SHARED_DSQ, SCX_SLICE_DFL, enq_flags);
	} else {
		u64 vtime = p->scx.dsq_vtime;

		/*
		 * Limit the amount of budget that an idling task can accumulate
		 * to one slice.
		 */
		if (vtime_before(vtime, vtime_now - SCX_SLICE_DFL))
			vtime = vtime_now - SCX_SLICE_DFL;

		scx_bpf_dispatch_vtime(p, SHARED_DSQ, SCX_SLICE_DFL, vtime,
				       enq_flags);
	}
}

void BPF_STRUCT_OPS(simple_dispatch, s32 cpu, struct task_struct *prev)
{
	scx_bpf_consume(SHARED_DSQ);
}
```

公平性靠"全局 vtime 推进 + 按权重反向计费"实现，只有十几行：

```c
void BPF_STRUCT_OPS(simple_running, struct task_struct *p)
{
	if (fifo_sched)
		return;

	/*
	 * Global vtime always progresses forward as tasks start executing. The
	 * test and update can be performed concurrently from multiple CPUs and
	 * thus racy. Any error should be contained and temporary. Let's just
	 * live with it.
	 */
	if (vtime_before(vtime_now, p->scx.dsq_vtime))
		vtime_now = p->scx.dsq_vtime;
}

void BPF_STRUCT_OPS(simple_stopping, struct task_struct *p, bool runnable)
{
	if (fifo_sched)
		return;

	/*
	 * Scale the execution time by the inverse of the weight and charge.
	 */
	p->scx.dsq_vtime += (SCX_SLICE_DFL - p->scx.slice) * 100 / p->scx.weight;
}

void BPF_STRUCT_OPS(simple_enable, struct task_struct *p)
{
	p->scx.dsq_vtime = vtime_now;
}
```

`stopping` 里那一行就是全部公平逻辑：消耗的时间除以权重累加到 `dsq_vtime`，
于是高权重任务 vtime 涨得慢、排在队前。`enable` 把新加入的任务对齐到当前 vtime，
防止它带着一个远古 vtime 插队饿死别人；`enqueue` 里那段裁剪则是防止一个睡了很久的
任务攒出巨大负 vtime 后长期霸占 CPU。

装载与收尾只需三段：

```c
s32 BPF_STRUCT_OPS_SLEEPABLE(simple_init)
{
	return scx_bpf_create_dsq(SHARED_DSQ, -1);
}

void BPF_STRUCT_OPS(simple_exit, struct scx_exit_info *ei)
{
	UEI_RECORD(uei, ei);
}

SCX_OPS_DEFINE(simple_ops,
	       .select_cpu		= (void *)simple_select_cpu,
	       .enqueue			= (void *)simple_enqueue,
	       .dispatch		= (void *)simple_dispatch,
	       .running			= (void *)simple_running,
	       .stopping		= (void *)simple_stopping,
	       .enable			= (void *)simple_enable,
	       .init			= (void *)simple_init,
	       .exit			= (void *)simple_exit,
	       .name			= "simple");
```

对照这张表回看 ops 全景：一个能跑的调度器最少只需 `enqueue` + `dispatch`，
其余都是可选的优化与钩子。`init` 标为 `SLEEPABLE`，因为创建 DSQ 需要分配。

## 与其它子系统的边界

- **cgroup**：`CONFIG_EXT_GROUP_SCHED` 打开后，cgroup 的创建/销毁/迁移/权重变更都会回调 BPF 侧
  （`cgroup_init`、`cgroup_prep_move`、`cgroup_move`、`cgroup_set_weight` 等），
  调度器可以据此做按组隔离。通用机制见 [cgroup](/docs/CS/OS/Linux/cgroup.md)。
- **core scheduling**：`ops.core_sched_before()` 决定同一物理核上两个任务的先后，
  用于应对 SMT 侧信道；`sched_ext_entity` 里的 `core_sched_at` 字段即服务于此。
- **cpufreq / schedutil**：`rq->scx.cpuperf_target` 让 BPF 调度器能表达对 CPU 性能档位的需求，
  配合 `scx_bpf_cpuperf_set()` 直接影响调频决策。
- **实时类**：始终在 ext 之上，SCX 调度器看不见也管不了 RT/DEADLINE 任务，
  这既是限制也是安全边界——见 [rt](/docs/CS/OS/Linux/proc/rt.md)。
- **BPF 基础设施**：整个机制建立在 BPF `struct_ops` 之上，verifier 负责校验安全性，
  见 [eBPF](/docs/CS/OS/Linux/Tools/eBPF.md)。

## 编译、装载与观测

开启 `CONFIG_SCHED_CLASS_EXT` 并打开 BPF 支持后，内核侧就位。调度器本身是普通 BPF 对象，
由用户态程序（如 `scx_simple`、`scx_lavd`）通过 libbpf 的 `struct_ops` 接口加载；
进程一退出，调度器随之卸载，系统自动回落到内置调度类——这也是日常实验最安全的用法。

想强制卸载可以按 sysrq-S（对应 `SCX_EXIT_SYSRQ`）。排障口径有两处：
`/sys/kernel/debug/sched_ext` 下的统计（如 `nr_rejected`，记录被 `p->scx.disallow`
挡下的切换次数），以及调度器自己通过 `UEI_RECORD` 回传的用户态退出信息——
它携带 `exit_code`、消息文本与可选的调用栈缓冲（`SCX_EXIT_MSG_LEN` 1024 字节）。

## Links

- [进程链路总览](/docs/CS/OS/Linux/proc/README.md)
- [task_struct 与进程表示](/docs/CS/OS/Linux/proc/process.md)
- [Linux 内核总览](/docs/CS/OS/Linux/Linux.md)

## References

1. [sched-ext documentation — The Linux Kernel documentation](https://www.kernel.org/doc/html/latest/scheduler/sched-ext.html)
2. [sched_ext schedulers and tools](https://github.com/sched-ext/scx)

