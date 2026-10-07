## Introduction

mutex 是内核中"严格语义"的睡眠互斥锁：同一时刻只有一个持有者、只有持有者能解锁、不可递归，但**临界区内可以睡眠**。spinlock 忙等烧 CPU，只在临界区极短时划算；只要临界区可能阻塞（分配内存、拷贝数据、I/O），就必须用 mutex。理论视角见 [Semaphores](/docs/CS/OS/process.md?id=semaphores)。

mutex 的全部状态压缩在一个原子长字 `owner` 里，加锁路径按代价逐级降级：**快路径（一次 cmpxchg）→ 中速路径（乐观自旋，不睡）→ 慢路径（入队睡眠 + 交锁移交）**。三级结构的思想与用户态的 [futex 三态锁](/docs/CS/OS/Linux/Lock/futex.md?id=user-space-implementation-three-state-lock)完全一致，只是内核里多了"等锁移交（handoff）"这一层反饥饿机制。

## struct mutex and the Owner's Three Flag Bits

```c
context_lock_struct(mutex) {
	atomic_long_t		owner;
	raw_spinlock_t		wait_lock;
#ifdef CONFIG_MUTEX_SPIN_ON_OWNER
	struct optimistic_spin_queue osq; /* Spinner MCS lock */
#endif
	struct mutex_waiter	*first_waiter __guarded_by(&wait_lock);
#ifdef CONFIG_DEBUG_MUTEXES
	void			*magic;
#endif
#ifdef CONFIG_DEBUG_LOCK_ALLOC
	struct lockdep_map	dep_map;
#endif
};
```

（v7.2.7 里 `struct mutex` 通过 `context_lock_struct()` 宏定义——为了配合上下文锁分析，不再是字面的 `struct mutex {`。阅读源码时按 `struct mutex` 理解即可。）

`task_struct` 指针至少按 `L1_CACHE_BYTES` 对齐，所以 `owner` 的低位可以挪用做状态标志（`kernel/locking/mutex.h`）：

```c
/*
 * @owner: contains: 'struct task_struct *' to the current lock owner,
 * NULL means not owned. Since task_struct pointers are aligned at
 * at least L1_CACHE_BYTES, we have low bits to store extra state.
 *
 * Bit0 indicates a non-empty waiter list; unlock must issue a wakeup.
 * Bit1 indicates unlock needs to hand the lock to the top-waiter
 * Bit2 indicates handoff has been done and we're waiting for pickup.
 */
#define MUTEX_FLAG_WAITERS	0x01
#define MUTEX_FLAG_HANDOFF	0x02
#define MUTEX_FLAG_PICKUP	0x04

#define MUTEX_FLAGS		0x07
```

| 标志 | 谁设置 | 含义 |
| :-- | :-- | :-- |
| `WAITERS` | 第一个等待者入队时 | 有人睡在队列里，解锁方必须做唤醒/移交 |
| `HANDOFF` | 等待者等太久（或队首）时 | 锁已"许配"给队首，后来的竞争者不得再走快路径偷锁 |
| `PICKUP` | 移交方 `__mutex_handoff()` | 锁已经交给某人了，正等他来取；只有那个人能拿到 |

> [!NOTE]
>
> 较老的教程里 `struct mutex` 的等待队列是 `struct list_head wait_list`。v7.2.7 已经改成 `struct mutex_waiter *first_waiter`——队列是一条**环形链表**（`first_waiter` 指向队首，空表时初始化为自己的 list 头），判断"还有没有等待者"只需看指针是否为 NULL，不必再判 `list_empty()`。

等待者结构放在**等待者的内核栈上**：

```c
/*
 * This is the control structure for tasks blocked on mutex, which resides
 * on the blocked task's kernel stack:
 */
struct mutex_waiter {
	struct list_head	list;
	struct task_struct	*task;
	struct ww_acquire_ctx	*ww_ctx;
#ifdef CONFIG_DEBUG_MUTEXES
	void			*magic;
#endif
};
```

## Fast Path: Replacing 0 with current

```c
void __sched mutex_lock(struct mutex *lock)
{
	might_sleep();

	if (!__mutex_trylock_fast(lock))
		__mutex_lock_slowpath(lock);
}
```

```c
/*
 * Optimistic trylock that only works in the uncontended case. Make sure to
 * follow with a __mutex_trylock() before failing.
 */
static __always_inline bool __mutex_trylock_fast(struct mutex *lock)
	__cond_acquires(true, lock)
{
	unsigned long curr = (unsigned long)current;
	unsigned long zero = 0UL;

	MUTEX_WARN_ON(lock->magic != lock);

	if (atomic_long_try_cmpxchg_acquire(&lock->owner, &zero, curr))
		return true;

	return false;
}
```

解锁的快路径对称：把 `owner` 从 `current` 换回 0，成功就返回——**没有等待者时解锁是一次原子操作**，连 `wait_lock` 都不用碰。

```c
static __always_inline bool __mutex_unlock_fast(struct mutex *lock)
	__cond_releases(true, lock)
{
	unsigned long curr = (unsigned long)current;

	return atomic_long_try_cmpxchg_release(&lock->owner, &curr, 0UL);
}
```

注意它用的是 `try_cmpxchg`：如果 `owner` 上带了 `WAITERS`/`HANDOFF` 标志，值就不是纯 `current`，快路径失败，落到 `__mutex_unlock_slowpath()`。

## Medium Path: Optimistic Spinning

为什么需要这一级？如果快路径失败就直接睡，那么"持锁者马上就要释放"的常见场景会白白付出两次上下文切换（睡下 + 唤醒）。乐观自旋的赌注很小：**只要持锁者还在 CPU 上运行，就大概率很快释放**。

```c
/*
 * Optimistic spinning.
 *
 * We try to spin for acquisition when we find that the lock owner
 * is currently running on a (different) CPU and while we don't
 * need to reschedule. The rationale is that if the lock owner is
 * running, it is likely to release the lock soon.
 *
 * The mutex spinners are queued up using MCS lock so that only one
 * spinner can compete for the mutex. However, if mutex spinning isn't
 * going to happen, there is no point in going through the lock/unlock
 * overhead.
 */
static __always_inline bool
mutex_optimistic_spin(struct mutex *lock, struct ww_acquire_ctx *ww_ctx,
		      struct mutex_waiter *waiter)
{
	if (!waiter) {
		if (!mutex_can_spin_on_owner(lock))
			goto fail;

		/*
		 * In order to avoid a stampede of mutex spinners trying to
		 * acquire the mutex all at once, the spinners need to take a
		 * MCS (queued) lock first before spinning on the owner field.
		 */
		if (!osq_lock(&lock->osq))
			goto fail;
	}

	for (;;) {
		struct task_struct *owner;

		/* Try to acquire the mutex... */
		owner = __mutex_trylock_or_owner(lock);
		if (!owner)
			break;

		/*
		 * There's an owner, wait for it to either
		 * release the lock or go to sleep.
		 */
		if (!mutex_spin_on_owner(lock, owner, ww_ctx, waiter))
			goto fail_unlock;

		cpu_relax();
	}

	if (!waiter)
		osq_unlock(&lock->osq);

	return true;
```

**`osq`（optimistic spin queue）是防止"惊群"的关键**：所有乐观自旋者先用 MCS 队列排好队（机制见 [qspinlock 的 MCS 队列](/docs/CS/OS/Linux/Lock/spinlock.md?id=slow-path-mcs-queue)），**只有队首**去竞争 mutex 本身，其余人在自己的 per-CPU 节点上等。否则 N 个自旋者会同时在同一个 `owner` 字上 cmpxchg，重演 test-and-set 的 cache line 抖动。

自旋随时可以放弃，三个退出条件：

```c
	while (__mutex_owner(lock) == owner) {
		/*
		 * Ensure we emit the owner->on_cpu, dereference _after_
		 * checking lock->owner still matches owner. And we already
		 * disabled preemption which is equal to the RCU read-side
		 * crital section in optimistic spinning code. Thus the
		 * task_strcut structure won't go away during the spinning
		 * period
		 */
		barrier();

		/*
		 * Use vcpu_is_preempted to detect lock holder preemption issue.
		 */
		if (!owner_on_cpu(owner) || need_resched()) {
			ret = false;
			break;
		}
		...
	}
```

1. `!owner_on_cpu(owner)`——持锁者不在 CPU 上（睡了、或被抢占了），再等下去没意义；
2. `need_resched()`——我自己该被调度了；
3. ww_mutex 语境下的额外检查（见后文）。

其中 `owner_on_cpu()` 在虚拟化下会走 `vcpu_is_preempted()`：持锁的 vCPU 被宿主机调度出去时，`on_cpu` 仍为真但实际没在跑，靠 paravirt 接口才能识破。

`osq_lock()` 自己也带退出条件——注意它自旋时同时检查 `need_resched()` 与前驱是否被抢占：

```c
	if (smp_cond_load_relaxed(&node->locked, VAL || need_resched() ||
				  vcpu_is_preempted(node_cpu(node->prev))))
		return true;
```

失败退队要走三步（稳定 prev → 稳定 next → unlink），`osq_lock()` 里的注释画得很清楚，原因和 qspinlock 的 MCS 交接是同一套并发问题。

## Slow Path: Queue and Sleep

乐观自旋失败后进入 `__mutex_lock_common()`——所有 `mutex_lock*` 变体的公共底：

```c
	preempt_disable();
	mutex_acquire_nest(&lock->dep_map, subclass, 0, nest_lock, ip);

	trace_contention_begin(lock, LCB_F_MUTEX | LCB_F_SPIN);
	if (__mutex_trylock(lock) ||
	    mutex_optimistic_spin(lock, ww_ctx, NULL)) {
		/* got the lock, yay! */
		lock_acquired(&lock->dep_map, ip);
		if (ww_ctx)
			ww_mutex_set_context_fastpath(ww, ww_ctx);
		trace_contention_end(lock, 0);
		preempt_enable();
		return 0;
	}

	raw_spin_lock_irqsave(&lock->wait_lock, flags);
	/*
	 * After waiting to acquire the wait_lock, try again.
	 */
	if (__mutex_trylock(lock)) {
		if (ww_ctx)
			__ww_mutex_check_waiters(lock, ww_ctx, &wake_q);

		goto skip_wait;
	}
```

注意"再试一次"出现了两次：乐观自旋前一次、拿到 `wait_lock` 后又一次。因为拿 `wait_lock` 本身可能等了很久，这期间锁很可能已经释放。

入队后进入主循环：

```c
	for (;;) {
		bool first;

		/*
		 * Once we hold wait_lock, we're serialized against
		 * mutex_unlock() handing the lock off to us, do a trylock
		 * before testing the error conditions to make sure we pick up
		 * the handoff.
		 */
		if (__mutex_trylock(lock))
			break;

		raw_spin_unlock(&current->blocked_lock);
		/*
		 * Check for signals and kill conditions while holding
		 * wait_lock. This ensures the lock cancellation is ordered
		 * against mutex_unlock() and wake-ups do not go missing.
		 */
		if (signal_pending_state(state, current)) {
			ret = -EINTR;
			goto err;
		}
		...
		schedule_preempt_disabled();

		first = lock->first_waiter == &waiter;

		raw_spin_lock_irqsave(&lock->wait_lock, flags);
		...
		if (__mutex_trylock_or_handoff(lock, first))
			break;

		if (first) {
			bool opt_acquired;
			...
			opt_acquired = mutex_optimistic_spin(lock, ww_ctx, &waiter);
			...
		}
	}
```

两个值得注意的点：

- **信号检查必须在持有 `wait_lock` 时做**，否则"我决定退出"与"对方唤醒我"会竞态丢事件（唤醒丢失 → 永久睡眠）。
- **`first` 决定要不要设置 handoff**：`__mutex_trylock_or_handoff(lock, first)` 在 `first` 为真时顺手把 `MUTEX_FLAG_HANDOFF` 置上——队首等待者等得够久了，开始要求"锁是我的"。

## handoff: Handing Off the Lock Instead of Waking

mutex 的公平性由 handoff 保证。普通的"解锁 + 唤醒"存在漏洞：解锁方释放锁之后、被唤醒者真正上 CPU 之前，可能有新的竞争者从快路径直接 cmpxchg 拿走锁。如果这样的新竞争者源源不断（临界区短 + 高并发），队首等待者会一直饿死。

handoff 的做法是**不真正释放锁**，而是把它直接"许配"给队首：

```c
/*
 * Give up ownership to a specific task, when @task = NULL, this is equivalent
 * to a regular unlock. Sets PICKUP on a handoff, clears HANDOFF, preserves
 * WAITERS. Provides RELEASE semantics like a regular unlock, the
 * __mutex_trylock() provides a matching ACQUIRE semantics for the handoff.
 */
static void __mutex_handoff(struct mutex *lock, struct task_struct *task)
{
	unsigned long owner = atomic_long_read(&lock->owner);

	for (;;) {
		unsigned long new;

		MUTEX_WARN_ON(__owner_task(owner) != current);
		MUTEX_WARN_ON(owner & MUTEX_FLAG_PICKUP);

		new = (owner & MUTEX_FLAG_WAITERS);
		new |= (unsigned long)task;
		if (task)
			new |= MUTEX_FLAG_PICKUP;

		if (atomic_long_try_cmpxchg_release(&lock->owner, &owner, new))
			break;
	}
}
```

`PICKUP` 位的语义是"锁已经写上你的名字了"。此时 `owner` 非 NULL（锁仍"被持有"），其他人的快路径 cmpxchg 会失败；而 `PICKUP` 让**且仅让**指定的那个人能取走锁：

```c
	for (;;) { /* must loop, can race against a flag */
		unsigned long flags = __owner_flags(owner);
		unsigned long task = owner & ~MUTEX_FLAGS;

		if (task) {
			if (flags & MUTEX_FLAG_PICKUP) {
				if (task != curr)
					break;
				flags &= ~MUTEX_FLAG_PICKUP;
			} else if (handoff) {
				if (flags & MUTEX_FLAG_HANDOFF)
					break;
				flags |= MUTEX_FLAG_HANDOFF;
			} else {
				break;
			}
		} else {
			MUTEX_WARN_ON(flags & (MUTEX_FLAG_HANDOFF | MUTEX_FLAG_PICKUP));
			task = curr;
		}

		if (atomic_long_try_cmpxchg_acquire(&lock->owner, &owner, task | flags)) {
			if (task == curr)
				return NULL;
			break;
		}
	}
```

这段是 mutex 的核心状态机，值得逐行读：`PICKUP` 时**只有名字匹配的人**能继续（清掉 PICKUP 变成自己的持有），其他所有人直接 `break` 返回失败。

## waiter-spinner: The First Waiter Can Also Spin

一个反直觉的设计：进入睡眠队列**之后**，队首等待者还会再做一次乐观自旋。

```c
		if (first) {
			bool opt_acquired;

			/*
			 * mutex_optimistic_spin() can call schedule(), so
			 * we need to release these locks before calling it,
			 * and clear blocked on so we don't become unselectable
			 * to run.
			 */
			__clear_task_blocked_on(current, lock);
			raw_spin_unlock(&current->blocked_lock);
			raw_spin_unlock_irqrestore(&lock->wait_lock, flags);

			trace_contention_begin(lock, LCB_F_MUTEX | LCB_F_SPIN);
			opt_acquired = mutex_optimistic_spin(lock, ww_ctx, &waiter);
			...
		}
```

注意传给 `mutex_optimistic_spin()` 的 `waiter` 参数非空，于是它**跳过 `osq_lock()`**——因为队首等待者已经是唯一有资格抢锁的人，不需要再和别的自旋者排队（源码注释：waiter-spinner 直接和 osq 队首并发抢，直到 owner 变成自己）。这既保留了"睡下前最后再赌一次"的机会，又不会破坏 osq 的串行化。

## Unlock Path

```c
	/*
	 * Release the lock before (potentially) taking the spinlock such that
	 * other contenders can get on with things ASAP.
	 *
	 * Except when HANDOFF, in that case we must not clear the owner field,
	 * but instead set it to the top waiter.
	 */
	owner = atomic_long_read(&lock->owner);
	for (;;) {
		MUTEX_WARN_ON(__owner_task(owner) != current);
		MUTEX_WARN_ON(owner & MUTEX_FLAG_PICKUP);

		if (owner & MUTEX_FLAG_HANDOFF)
			break;

		if (atomic_long_try_cmpxchg_release(&lock->owner, &owner, __owner_flags(owner))) {
			if (owner & MUTEX_FLAG_WAITERS)
				break;

			return;
		}
	}
```

**先释放锁，再拿 `wait_lock`**——这样其他竞争者不必等解锁方完成唤醒流程就能开始抢。只有在 `HANDOFF` 已置位时才跳过"清零 owner"，改由后面的 `__mutex_handoff()` 直接写上新主人的名字。

随后从等待队列挑下一个持有者并唤醒：

```c
	waiter = lock->first_waiter;
	if (!next && waiter) {
		next = get_task_struct(waiter->task);
		...
	}

	if (owner & MUTEX_FLAG_HANDOFF)
		__mutex_handoff(lock, next);

	raw_spin_unlock(&current->blocked_lock);
	raw_spin_unlock_irqrestore(&lock->wait_lock, flags);
	if (next) {
		wake_up_process(next);
		put_task_struct(next);
	}
```

## proxy execution: Handing the Lock to Whoever Is Boosting Me

v7.2.7 的 mutex 里出现了一块较新的逻辑——**proxy execution**（`CONFIG_SCHED_PROXY_EXEC`）。它的动机是：如果任务 A 阻塞在 mutex 上，而 A 的 CPU 正在执行别人，调度器可以把 A 的"运行权"借给锁的持有者，让持有者尽快跑完临界区（相当于让等待者间接推进）。

在这个模式下，解锁方不是随便挑队首，而是优先交给**正在 boost 自己的那个任务**：

```c
	if (sched_proxy_exec()) {
		/*
		 * If we have a task boosting current, and that task was boosting
		 * current through this lock, hand the lock to that task, as that
		 * is the highest waiter, as selected by the scheduling function.
		 */
		donor = current->blocked_donor;
		if (donor) {
			struct mutex *next_lock;

			raw_spin_lock_nested(&donor->blocked_lock, SINGLE_DEPTH_NESTING);
			next_lock = __get_task_blocked_on(donor);
			if (next_lock == lock) {
				next = get_task_struct(donor);
				__clear_task_blocked_on(next, lock);
				current->blocked_donor = NULL;
			}
			raw_spin_unlock(&donor->blocked_lock);
		}
	}
```

此外，持有 `blocked_donor` 的一方在解锁时**强制走 handoff**：

```c
		if (sched_proxy_exec() && current->blocked_donor) {
			/* force handoff if we have a blocked_donor */
			owner = MUTEX_FLAG_HANDOFF;
			break;
		}
```

配套的还有 `current->blocked_lock` / `__set_task_blocked_on()` 这套"任务正阻塞在哪把锁上"的记账——它同时也是 hung task 检测与调试接口的数据来源。

> [!NOTE]
>
> proxy execution 是 2025 年前后仍在演进的特性。读这段代码时注意两点：① 它只影响"挑谁来接锁"和"是否强制 handoff"，不改变 mutex 的核心状态机；② 只有在 `sched_proxy_exec()` 为真时才生效，默认内核仍是普通的队首优先。

## ww_mutex: Deadlock Avoidance When Acquiring Multiple Locks

`ww_mutex`（wound/wait mutex）用于"必须同时持有同一族的多把锁"的场景——典型是 DRM/GPU 的 buffer 管理：一次提交可能涉及几十个 BO，逐个加锁。若两个任务按相反顺序申请，就是教科书式的 ABBA 死锁。

ww_mutex 给每个**获取上下文**（`ww_acquire_ctx`）发一个单调递增的时间戳 `stamp`，然后二选一：

```
/*
 * Wait-Die:
 *   The newer transactions are killed when:
 *     It (the new transaction) makes a request for a lock being held
 *     by an older transaction.
 *
 * Wound-Wait:
 *   The newer transactions are wounded when:
 *     An older transaction makes a request for a lock being held by
 *     the newer transaction.
 */
```

- **wait-die**（`is_wait_die`）：年轻者遇到年长者持锁 → 年轻者**自杀**（返回 `-EDEADLK`）；
- **wound-wait**（默认）：年长者遇到年轻者持锁 → **伤害**（wound）年轻者，让它自杀重试。

两者都保证"总是年轻的一方退让"，从而打破循环等待。判定新老就是比 stamp（RT 任务还会先比优先级）：

```c
	/* FIFO order tie break -- bigger is younger */
	return (signed long)(a->stamp - b->stamp) > 0;
```

用法约定（源码里有大量 `DEBUG_LOCKS_WARN_ON` 在守着）：

1. `ww_acquire_init(&ctx, &ww_class)` 建立上下文；
2. 逐个 `ww_mutex_lock(&lock, &ctx)`；任意一次返回 `-EDEADLK` 时，**必须先释放本上下文已拿到的全部锁**，再从第一把开始重来（`ww_mutex_lock_slow()` 或手动重试）；
3. 全部拿完后 `ww_acquire_done(&ctx)`；
4. 解锁一律用 `ww_mutex_unlock()`，不能用 `mutex_unlock()`；
5. `ww_acquire_fini(&ctx)` 收尾。

收到 `-EDEADLK` 后"去拿一把不同的锁"是 bug，源码直接 `WARN_ON`：

```c
	if (ww_ctx->contending_lock) {
		/*
		 * After -EDEADLK you tried to
		 * acquire a different ww_mutex? Bad!
		 */
		DEBUG_LOCKS_WARN_ON(ww_ctx->contending_lock != ww);

		/*
		 * You called ww_mutex_lock after receiving -EDEADLK,
		 * but 'forgot' to unlock everything else first?
		 */
		DEBUG_LOCKS_WARN_ON(ww_ctx->acquired > 0);
		ww_ctx->contending_lock = NULL;
	}
```

还有个专门的测试开关 `CONFIG_DEBUG_WW_MUTEX_SLOWPATH`，会**故意注入死锁**（`ww_mutex_deadlock_injection()`，按指数增长的间隔随机返回 `-EDEADLK`），用来把"慢路径没测过"的 bug 逼出来。

ww_mutex 与乐观自旋不能随便共存：自旋期间不去检查 `ww->ctx` 会破坏 stamp 顺序，所以 `ww_mutex_spin_on_owner()` 在需要死锁检测时直接放弃自旋：

```c
	/*
	 * If ww->ctx is set the contents are undefined, only
	 * by acquiring wait_lock there is a guarantee that
	 * they are not invalid when reading.
	 *
	 * As such, when deadlock detection needs to be
	 * performed the optimistic spinning cannot be done.
	 *
	 * Check this in every inner iteration because we may
	 * be racing against another thread's ww_mutex_lock.
	 */
	if (ww_ctx->acquired > 0 && READ_ONCE(ww->ctx))
		return false;
```

## rt_mutex and Priority Inheritance

普通 mutex 没有 FIFO 公平之外的优先级概念。当高优先级任务等低优先级任务持有的锁、而低优先级又被中优先级任务抢占时，就发生**优先级反转**（Mars Pathfinder 事故的经典场景）。`rt_mutex` 通过 **PI（优先级继承）协议**解决：等待期间持有者临时继承所有等待者中最高的优先级，释放后恢复——内核里由 `kernel/locking/rtmutex.c` 实现链式传递（持锁者可能又在等下一把锁）。

rt_mutex 的两个主要入口：

- 用户态 PI futex：`FUTEX_LOCK_PI` 系列（见 [futex](/docs/CS/OS/Linux/Lock/futex.md)），`pthread` 的 `PTHREAD_PRIO_INHERIT` 也落到这里；
- `PREEMPT_RT` 内核：`spinlock_t` 变成可睡眠的 rt_mutex（`raw_spinlock_t` 保持不变），这正是 RT 补丁的核心改造。

## mutex Under PREEMPT_RT

`CONFIG_PREEMPT_RT` 下 `struct mutex` 换了个完全不同的实现：

```c
/*
 * Preempt-RT variant based on rtmutexes.
 */
context_lock_struct(mutex) {
	struct rt_mutex_base	rtmutex;
#ifdef CONFIG_DEBUG_LOCK_ALLOC
	struct lockdep_map	dep_map;
#endif
};
```

也就是说 **RT 下 mutex 就是 rt_mutex**，天生带优先级继承——RT 内核里"mutex 会不会优先级反转"这个问题自动消失了。`mutex.c` 里那一整套乐观自旋 / handoff 逻辑被 `#ifndef CONFIG_PREEMPT_RT` 整段跳过，改由 `rtmutex.c` 承担（见 [RT 下 spinlock 的同款改造](/docs/CS/OS/Linux/Lock/spinlock.md?id=spinlock-under-preempt_rt)）。

## Observation

| 手段 | 说明 |
| :-- | :-- |
| `CONFIG_LOCK_EVENT_COUNTS` | debugfs 的 `lock_event_counts/`，统计 mutex 各路径的进入次数 |
| `CONFIG_DEBUG_MUTEXES` | 符号名、获取点追踪、owner 追踪、自递归与循环死锁检测 |
| `CONFIG_PROVE_LOCKING`（lockdep） | 锁顺序图分析，报告潜在死锁 |
| `trace_contention_begin/end` | 锁竞争 tracepoint，`perf lock` 的数据来源 |
| hung task blocker | `mutex` 阻塞会被 hung task 检测识别，`/proc/<pid>/...` 可看到阻塞在哪把锁上 |

`perf lock` 是实际排查锁竞争最常用的工具，它直接消费 `contention_begin/contention_end` 两个 tracepoint，能给出"哪把锁上等了多久"。

## API

```c
DEFINE_MUTEX(m);                       /* 静态定义并初始化 */
mutex_init(&m);                        /* 动态初始化（不能 memset） */

mutex_lock(&m);                        /* 不可中断地睡眠等待 */
mutex_lock_interruptible(&m);          /* 可被信号打断，返回 -EINTR；驱动/可 kill 进程场景首选 */
mutex_lock_killable(&m);               /* 只响应致命信号 */
mutex_trylock(&m);                     /* 不睡眠，立即返回成败 */
mutex_lock_io(&m);                     /* 等待期间标记为 iowait，改善 IO 统计与调度 */
mutex_unlock(&m);
mutex_is_locked(&m);                   /* 是否被任何人持有 */
```

## Usage Rules

严格语义（`CONFIG_DEBUG_MUTEXES` 下逐条强制检查）：

- 同一时刻只有一个任务持有；**只有 owner 能解锁**，多次解锁不允许；
- **不可递归**：自己再锁自己 = 永久死锁（需要递归语义要自己实现或换设计）；
- 只能用于**进程上下文**：中断/tasklet/定时器里不允许获取（睡眠），也不允许释放；
- 持有期间任务**不能 exit**；持锁对象所在内存不能被释放；不能重复初始化已持有的锁；
- **`mutex_unlock()` 之后不能立刻认为对象还活着**——与 spinlock / refcount 不同，解锁可能让另一个任务立刻释放整个对象：

```c
 * The caller must ensure that the mutex stays alive until this function has
 * returned - mutex_unlock() can NOT directly be used to release an object such
 * that another concurrent task can free it.
 * Mutexes are different from spinlocks & refcounts in this aspect.
```

这条是 mutex 最容易踩的坑：想用"解锁 → 释放对象"实现生命周期管理时，必须额外配引用计数，不能靠 mutex 自己。

调试设施：`DEBUG_MUTEXES` 提供符号名、获取点追踪、owner 追踪、自递归与多任务循环死锁检测；`lockdep`（`CONFIG_PROVE_LOCKING`）在此基础上做锁顺序图分析，见 [死锁与调试](/docs/CS/OS/Linux/Lock/README.md?id=deadlocks-and-debugging)。

## Links

- [Linux Lock](/docs/CS/OS/Linux/Lock/README.md)
- [rwsem](/docs/CS/OS/Linux/Lock/rwsem.md) — 需要读写区分时
- [semaphore / completion](/docs/CS/OS/Linux/Lock/semaphore.md) — 计数与事件等待
- [futex](/docs/CS/OS/Linux/Lock/futex.md) — 用户态同款三段式；PI 由 rt_mutex 承接
- [原子操作与内存屏障](/docs/CS/OS/Linux/Lock/atomic.md)

## References

- [Kernel docs: mutex design](https://docs.kernel.org/locking/mutex-design.html)
- [Kernel docs: Wound/Wait deadlock-proof mutex design](https://docs.kernel.org/locking/ww-mutex-design.html)
- [LWN: Mutexes and semaphores](https://lwn.net/Articles/167034/)
- [LWN: Wound/wait mutexes](https://lwn.net/Articles/548909/)
