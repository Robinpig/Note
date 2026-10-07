## Introduction

读多写少的场景下，互斥锁把并发读也串行化了，非常浪费。内核提供三种读写分离的原语，区别在于**读侧的开销**与**能否睡眠**：

| 原语 | 读侧 | 写侧 | 能否睡眠 | 写者饥饿 |
| :-- | :-- | :-- | :--: | :-- |
| rwlock（qrwlock） | 一次原子加 | 独占忙等 | 否 | 不会（排队公平） |
| rwsem | 原子加 + 乐观自旋 | 独占，等待队列 | 是 | 不会（handoff 保证） |
| seqlock | **无锁**（只读序号） | 独占，写时递增序号 | 否 | 不适用 |

三者按"读侧开销"递增排列的选择顺序是反的：seqlock 读侧最便宜但要能重读，rwsem 读侧最贵（可能睡眠）但语义最完整。

## rwlock and qrwlock

rwlock 在本质上是 spinlock 的一种，在 spinlock 之上增加了一个类似信号量的读计数器：读操作增加引用计数，写操作需要引用计数为 0 且拿到锁，从而获得独占。

x86/arm64 上的实现是 **qrwlock**（`kernel/locking/qrwlock.c`），它的结构里**内嵌了一把 spinlock 作为排队锁**：

```c
typedef struct qrwlock {
	union {
		atomic_t cnts;
		struct {
#ifdef __LITTLE_ENDIAN
			u8 wlocked;	/* Locked for write? */
			u8 __lstate[3];
#else
			u8 __lstate[3];
			u8 wlocked;	/* Locked for write? */
#endif
		};
	};
	arch_spinlock_t		wait_lock;
} arch_rwlock_t;
```

`cnts` 的低 9 位给写者（`_QW_LOCKED` 0x0ff / `_QW_WAITING` 0x100），第 9 位往上给读者计数（`_QR_BIAS = 1<<9`）。

> [!NOTE]
>
> 常见资料说"rwlock 会造成写饥饿"——对**经典 rwlock** 成立，但对当代的 qrwlock **不成立**。写者进不去锁时会先置 `_QW_WAITING` 再排队：
>
> ```c
> 	/* Put the writer into the wait queue */
> 	arch_spin_lock(&lock->wait_lock);
>
> 	/* Try to acquire the lock directly if no reader is present */
> 	if (!(cnts = atomic_read(&lock->cnts)) &&
> 	    atomic_try_cmpxchg_acquire(&lock->cnts, &cnts, _QW_LOCKED))
> 		goto unlock;
>
> 	/* Set the waiting flag to notify readers that a writer is pending */
> 	atomic_or(_QW_WAITING, &lock->cnts);
> ```
>
> 而读者的快路径 `queued_read_trylock()` 检查的是 `_QW_WMASK`（包含 `_QW_WAITING`），所以**只要写者在等，新读者就走不了快路径**，必须进慢路径在 `wait_lock` 上排队——排在写者后面。这就是 "queued" 的含义：读者不再能无限插队。

读者慢路径有个例外：**中断上下文不排队**，而是直接自旋：

```c
	if (unlikely(in_interrupt())) {
		/*
		 * Readers in interrupt context will get the lock immediately
		 * if the writer is just waiting (not holding the lock yet),
		 * so spin with ACQUIRE semantics until the lock is available
		 * without waiting in the queue.
		 */
		atomic_cond_read_acquire(&lock->cnts, !(VAL & _QW_LOCKED));
		return;
	}
	atomic_sub(_QR_BIAS, &lock->cnts);
	...
	arch_spin_lock(&lock->wait_lock);
```

因为中断上下文不能参与可能造成死锁的排队（它打断的正是持锁者的可能性），只能赌一把自旋。这也是"中断里用 read_lock 仍可能插队"的由来。

rwlock 的总体结论没变：**临界区极短且读远多于写**才划算，更多老代码已经迁到 RCU 或 rwsem。

## rwsem Data Structures

```c
context_lock_struct(rw_semaphore) {
	atomic_long_t count;
	/*
	 * Write owner or one of the read owners as well flags regarding
	 * the current state of the rwsem. Can be used as a speculative
	 * check to see if the write owner is running on the cpu.
	 */
	atomic_long_t owner;
#ifdef CONFIG_RWSEM_SPIN_ON_OWNER
	struct optimistic_spin_queue osq; /* spinner MCS lock */
#endif
	raw_spinlock_t wait_lock;
	struct rwsem_waiter *first_waiter __guarded_by(&wait_lock);
#ifdef CONFIG_DEBUG_RWSEMS
	void *magic;
#endif
#ifdef CONFIG_DEBUG_LOCK_ALLOC
	struct lockdep_map	dep_map;
#endif
};
```

`count` 与 `owner` 刻意相邻——无竞争时只有这两个字段被碰，希望它们落在同一条 cache line 上。而 `owner` 是竞争时最热的字段（乐观自旋者都盯着它），所以**嵌入 rwsem 的结构体应把其他高频字段放远一点**（源码注释明确建议），避免伪共享。

## Bit Layout of count

```
 63         8 7   3  2    1     0
+------------+-----+--+----+----+
| reader cnt | res |HD|WTR |WRT |
+------------+-----+--+----+----+
   Bits 8-62  3-7   2   1    0   （64 位）
   Bits 8-30  3-7   2   1    0   （32 位）
```

```c
/*
 * On 64-bit architectures, the bit definitions of the count are:
 *
 * Bit  0    - writer locked bit
 * Bit  1    - waiters present bit
 * Bit  2    - lock handoff bit
 * Bits 3-7  - reserved
 * Bits 8-62 - 55-bit reader count
 * Bit  63   - read fail bit
 */
#define RWSEM_WRITER_LOCKED	(1UL << 0)
#define RWSEM_FLAG_WAITERS	(1UL << 1)
#define RWSEM_FLAG_HANDOFF	(1UL << 2)
#define RWSEM_FLAG_READFAIL	(1UL << (BITS_PER_LONG - 1))

#define RWSEM_READER_SHIFT	8
#define RWSEM_READER_BIAS	(1UL << RWSEM_READER_SHIFT)
#define RWSEM_READER_MASK	(~(RWSEM_READER_BIAS - 1))
#define RWSEM_WRITER_MASK	RWSEM_WRITER_LOCKED
#define RWSEM_LOCK_MASK		(RWSEM_WRITER_MASK|RWSEM_READER_MASK)
#define RWSEM_READ_FAILED_MASK	(RWSEM_WRITER_MASK|RWSEM_FLAG_WAITERS|\
				 RWSEM_FLAG_HANDOFF|RWSEM_FLAG_READFAIL)
```

读者计数从第 8 位开始，一个读者就是 `+RWSEM_READER_BIAS`（+256），所以"数读者"是 `count >> RWSEM_READER_SHIFT`。

`RWSEM_READ_FAILED_MASK` 是读侧快路径的判据：只要有写者持有、有等待者、有 handoff、或读计数溢出（`READFAIL`），快路径就不成立。

## The Owner's Two Flag Bits

```c
/*
 * The least significant 2 bits of the owner value has the following
 * meanings when set.
 *  - Bit 0: RWSEM_READER_OWNED - rwsem may be owned by readers (just a hint)
 *  - Bit 1: RWSEM_NONSPINNABLE - Cannot spin on a reader-owned lock
 */
#define RWSEM_READER_OWNED	(1UL << 0)
#define RWSEM_NONSPINNABLE	(1UL << 1)
```

`owner` 存的是**写者**的 `task_struct`，或者**最后一个拿到读锁的读者**（带 `READER_OWNED` 位）。读锁解锁时不清理 `owner`，所以对于一个空闲或读者持有的 rwsem，`owner` 里可能残留着"上一个读者"的信息——源码注释说得很清楚：这只是调试线索，**可能已经不是真正的所有者**。

这个残留值的用途是乐观自旋：写者想知道"能不能自旋等"，先看 `owner` 是不是个正在 CPU 上跑的写者。

## Reader Fast Path and "Reader Stealing the Lock"

```c
static inline int __down_read_trylock(struct rw_semaphore *sem)
{
	int ret = 0;
	long tmp;

	preempt_disable();
	tmp = atomic_long_read(&sem->count);
	while (!(tmp & RWSEM_READ_FAILED_MASK)) {
		if (atomic_long_try_cmpxchg_acquire(&sem->count, &tmp,
						    tmp + RWSEM_READER_BIAS)) {
			rwsem_set_reader_owned(sem);
			ret = 1;
			break;
		}
	}
	preempt_enable();
	return ret;
}
```

无竞争时一次 `cmpxchg` 就拿到读锁。注意 `RWSEM_READ_FAILED_MASK` 里有 `WAITERS` 位——**只要有人在等，新读者就不能走快路径**，这正是防写饥饿的第一道闸门。

但慢路径里还有个"读者偷锁"的口子：

```c
	/*
	 * To prevent a constant stream of readers from starving a sleeping
	 * writer, don't attempt optimistic lock stealing if the lock is
	 * very likely owned by readers.
	 */
	if ((atomic_long_read(&sem->owner) & RWSEM_READER_OWNED) &&
	    (rcnt > 1) && !(count & RWSEM_WRITER_LOCKED))
		goto queue;

	/*
	 * Reader optimistic lock stealing.
	 */
	if (!(count & (RWSEM_WRITER_LOCKED | RWSEM_FLAG_HANDOFF))) {
		rwsem_set_reader_owned(sem);
		lockevent_inc(rwsem_rlock_steal);
		...
		return sem;
	}
```

逻辑可以读成：如果锁**显然**被多个读者持有（读者流不停），就老实排队；否则（比如只是有 `WAITERS` 位但没有实质持有者）允许偷——反正没人真的拿着锁，不偷白不偷。`HANDOFF` 位一旦设置就绝对不许偷，和 mutex 一样。

## Writer Fast Path and Optimistic Spinning

写者的快路径要求 `count` 完全为 0（`RWSEM_WRITER_LOCKED` 之外没有任何位）。失败后进乐观自旋，套路与 [mutex 的中速路径](/docs/CS/OS/Linux/Lock/mutex.md?id=medium-path-optimistic-spinning) 一样：先用 `osq_lock()` 排队，再盯 `owner`。

区别在于**写者自旋有额外的时间限制**，因为 rwsem 上可能挂着一大群读者：

```c
/*
 * Calculate reader-owned rwsem spinning threshold for writer
 *
 * The more readers own the rwsem, the longer it will take for them to
 * wind down and free the rwsem. So the empirical formula used to
 * determine the actual spinning time limit here is:
 *
 *   Spinning threshold = (10 + nr_readers/2)us
 *
 * The limit is capped to a maximum of 25us (30 readers). This is just
 * a heuristic and is subjected to change in the future.
 */
static inline u64 rwsem_rspin_threshold(struct rw_semaphore *sem)
{
	long count = atomic_long_read(&sem->count);
	int readers = count >> RWSEM_READER_SHIFT;
	u64 delta;

	if (readers > 30)
		readers = 30;
	delta = (20 + readers) * NSEC_PER_USEC / 2;

	return sched_clock() + delta;
}
```

读者越多，等他们全部退出所需时间越长，所以阈值随读者数线性增长，上限 25us（30 个读者）。判定开销也要控制——每 16 次循环才调一次 `sched_clock()`：

```c
		if (owner_state == OWNER_READER) {
			if (prev_owner_state != OWNER_READER) {
				if (rwsem_test_oflags(sem, RWSEM_NONSPINNABLE))
					break;
				rspin_threshold = rwsem_rspin_threshold(sem);
				loop = 0;
			}

			/*
			 * Check time threshold once every 16 iterations to
			 * avoid calling sched_clock() too frequently so
			 * as to reduce the average latency between the times
			 * when the lock becomes free and when the spinner
			 * is ready to do a trylock.
			 */
			else if (!(++loop & 0xf) && (sched_clock() > rspin_threshold)) {
				rwsem_set_nonspinnable(sem);
				lockevent_inc(rwsem_opt_nospin);
				break;
			}
		}
```

## NONSPINNABLE: Spin Limit When a Reader Holds the Lock

超时之后不是简单放弃，而是**给这把锁打上 `NONSPINNABLE` 标记**：

```c
/*
 * When the rwsem is reader-owned and a spinning writer has timed out,
 * the nonspinnable bit will be set to disable optimistic spinning.
 */
```

这个位会一直保留到读者计数归零（`clear_nonspinnable()`），期间所有后来的写者都**不再尝试自旋**，直接进慢路径睡眠。这么做的原因是：读者持有的锁什么时候释放无法预测（读者可能睡着做 I/O），一群写者围着空转纯属浪费；而且写者自旋本身会拖慢读者退出，形成负反馈。

反过来说，如果锁是被**写者**持有，自旋就非常划算（写者临界区短且不会睡），所以只在 `OWNER_WRITER` 时无条件自旋：

```c
static inline enum owner_state
rwsem_owner_state(struct task_struct *owner, unsigned long flags)
{
	if (flags & RWSEM_NONSPINNABLE)
		return OWNER_NONSPINNABLE;

	if (flags & RWSEM_READER_OWNED)
		return OWNER_READER;

	return owner ? OWNER_WRITER : OWNER_NULL;
}
```

四个状态的语义（`rwsem_spin_on_owner()` 的返回值）：

| 状态 | 含义 | 自旋者的下一步 |
| :-- | :-- | :-- |
| `OWNER_NULL` | owner 为空 | 立即 trylock |
| `OWNER_WRITER` | 写者持有 | 继续自旋，直到 owner 变化 |
| `OWNER_READER` | （可能是）读者持有 | 受时间阈值约束地自旋 |
| `OWNER_NONSPINNABLE` | 不可自旋 | 退出，进慢路径 |

## Reader Slow Path

```c
queue:
	waiter.task = current;
	waiter.type = RWSEM_WAITING_FOR_READ;
	waiter.timeout = jiffies + RWSEM_WAIT_TIMEOUT;
	waiter.handoff_set = false;

	raw_spin_lock_irq(&sem->wait_lock);
	first = sem->first_waiter;
	if (!first) {
		/*
		 * In case the wait queue is empty and the lock isn't owned
		 * by a writer, this reader can exit the slowpath and return
		 * immediately as its RWSEM_READER_BIAS has already been set
		 * in the count.
		 */
		if (!(atomic_long_read(&sem->count) & RWSEM_WRITER_MASK)) {
			/* Provide lock ACQUIRE */
			smp_acquire__after_ctrl_dep();
			raw_spin_unlock_irq(&sem->wait_lock);
			rwsem_set_reader_owned(sem);
			lockevent_inc(rwsem_rlock_fast);
			return sem;
		}
		adjustment += RWSEM_FLAG_WAITERS;
		...
	}
```

注意读者的 `RWSEM_READER_BIAS` 在进入慢路径**之前**就已经加到 `count` 上了（快路径的 `atomic_long_add_return`），所以慢路径里"如果队列空且没有写者"可以直接返回——bias 已经加过了，不需要再加。

等待循环靠 `waiter.task` 被清空来判定"被唤醒并授予了锁"：

```c
	/* wait to be given the lock */
	for (;;) {
		if (!smp_load_acquire(&waiter.task)) {
			/* Matches rwsem_mark_wake()'s smp_store_release(). */
			break;
		}
		if (signal_pending_state(state, current)) {
			...
		}
		schedule_preempt_disabled();
		lockevent_inc(rwsem_sleep_reader);
		set_current_state(state);
	}
```

`rwsem_mark_wake()` 把 `waiter.task` 置 NULL 就是用 `smp_store_release()`，这里用 `smp_load_acquire()` 配对。

## Writer Slow Path and handoff

写者的慢路径先做一次乐观自旋（`rwsem_can_spin_on_owner()` + `rwsem_optimistic_spin()`），失败才入队。入队后的核心是 `rwsem_try_write_lock()`：

```c
	count = atomic_long_read(&sem->count);
	do {
		bool has_handoff = !!(count & RWSEM_FLAG_HANDOFF);

		if (has_handoff) {
			/*
			 * Honor handoff bit and yield only when the first
			 * waiter is the one that set it. Otherwisee, we
			 * still try to acquire the rwsem.
			 */
			if (first->handoff_set && (waiter != first))
				return false;
		}

		new = count;

		if (count & RWSEM_LOCK_MASK) {
			/*
			 * A waiter (first or not) can set the handoff bit
			 * if it is an RT task or wait in the wait queue
			 * for too long.
			 */
			if (has_handoff || (!rt_or_dl_task(waiter->task) &&
					    !time_after(jiffies, waiter->timeout)))
				return false;

			new |= RWSEM_FLAG_HANDOFF;
		} else {
			new |= RWSEM_WRITER_LOCKED;
			new &= ~RWSEM_FLAG_HANDOFF;
			...
		}
	} while (!atomic_long_try_cmpxchg_acquire(&sem->count, &count, new));
```

**handoff 位的设置条件**（这是 rwsem 公平性的关键）：

1. 等待者是 RT/DL 任务——实时任务不该被普通任务无限挡住；
2. 等太久：`time_after(jiffies, waiter->timeout)`，超时阈值 `RWSEM_WAIT_TIMEOUT`：

```c
/*
 * The typical HZ value is either 250 or 1000. So set the minimum waiting
 * time to at least 4ms or 1 jiffy (if it is higher than 4ms) in the wait
 * queue before initiating the handoff protocol.
 */
#define RWSEM_WAIT_TIMEOUT	DIV_ROUND_UP(HZ, 250)
```

一旦 handoff 置位，`HANDOFF` 会挡住所有"偷锁"（读者慢路径检查它、写者 `rwsem_try_write_lock_unqueued()` 也检查它），锁就只能交给队首。此外，置过 handoff 的等待者醒来后会**再自旋一次**加速交接：

```c
		if (waiter.handoff_set) {
			enum owner_state owner_state;

			owner_state = rwsem_spin_on_owner(sem);
			if (owner_state == OWNER_NULL)
				goto trylock_again;
		}
```

## rwsem_mark_wake: Waking Readers in Bulk

解锁时不是一个个唤醒读者，而是一次唤醒一批：

```c
/*
 * Magic number to batch-wakeup waiting readers, even when writers are
 * also present in the queue. This both limits the amount of work the
 * waking thread must do and also prevents any potential counter overflow,
 * however unlikely.
 */
#define MAX_READERS_WAKEUP	0x100
```

批量唤醒有两个理由：限制唤醒者的工作量；防止 reader count 溢出（`READFAIL` 位就是为溢出准备的）。

唤醒策略还分三种（`enum rwsem_wake_type`）：

| 类型 | 场景 | 行为 |
| :-- | :-- | :-- |
| `RWSEM_WAKE_ANY` | `up_write()` / `up_read()` | 队首是写者就只唤醒它；否则批量唤醒读者 |
| `RWSEM_WAKE_READERS` | 写者释放 | 只唤醒读者 |
| `RWSEM_WAKE_READ_OWNED` | 唤醒者自己持有读锁（`downgrade_write`、偷锁成功） | 唤醒读者，但保持读锁持有状态 |

队首是写者时的处理有个细节：写者被加入 wake_q 后**还没真正醒来上 CPU**，期间其他写者仍可偷锁，但读者会因为有排队写者而阻塞——

```c
	if (waiter->type == RWSEM_WAITING_FOR_WRITE) {
		if (wake_type == RWSEM_WAKE_ANY) {
			/*
			 * Mark writer at the front of the queue for wakeup.
			 * Until the task is actually later awoken later by
			 * the caller, other writers are able to steal it.
			 * Readers, on the other hand, will block as they
			 * will notice the queued writer.
			 */
			wake_q_add(wake_q, waiter->task);
			lockevent_inc(rwsem_wake_writer);
		}

		return;
	}
```

## downgrade_write: Downgrading a Write Lock to a Read Lock

`downgrade_write()` 把写锁换成读锁而不放开，避免"释放 → 立刻被别人抢走"的窗口。实现上只是走一次 `RWSEM_WAKE_READ_OWNED` 唤醒：

```c
/*
 * downgrade a write lock into a read lock
 * - caller incremented waiting part of count and discovered it still negative
 * - just wake up any readers at the front of the queue
 */
static struct rw_semaphore *rwsem_downgrade_wake(struct rw_semaphore *sem)
{
	unsigned long flags;
	DEFINE_WAKE_Q(wake_q);

	raw_spin_lock_irqsave(&sem->wait_lock, flags);

	if (sem->first_waiter)
		rwsem_mark_wake(sem, RWSEM_WAKE_READ_OWNED, &wake_q);

	raw_spin_unlock_irqrestore(&sem->wait_lock, flags);
	wake_up_q(&wake_q);

	return sem;
}
```

典型用法："先以写锁查找并可能插入，然后降级为读锁继续持有"——避免中间被别人改掉。

## percpu-rwsem: Truly Contention-Free Reader Side

标准 rwsem 的读侧快路径仍是一次**共享的**原子加，高并发下那一条 cache line 就是瓶颈（想想 `mmap_lock` 被几百个线程同时读）。`percpu_rw_semaphore` 把读计数做成 per-CPU：

```c
static bool __percpu_down_read_trylock(struct percpu_rw_semaphore *sem)
{
	this_cpu_inc(*sem->read_count);
	...
	smp_mb(); /* A matches D */
	/*
	 * If !sem->block the critical section starts here, matched by the
	 * ...
	 */
```

- **读侧**：`this_cpu_inc()`，纯本地操作，不碰任何共享 cache line；
- **写侧**：置 `sem->block`，然后等**所有 CPU** 的计数归零。等待期间靠 `rcu_sync`（见 [RCU](/docs/CS/OS/Linux/Lock/RCU.md)）保证宽限期语义，用 `rcuwait` 睡等。

代价很清楚：**写侧从"原子操作"变成了"等 N 个 CPU"**，非常慢。所以它只用于"读侧极度频繁、写侧几乎不发生"的锁，典型是 `sb->s_writers`（文件系统冻结）、`cgroup` 的线程组锁。

per-CPU 化的思想本身见 [per-CPU 变量](/docs/CS/OS/Linux/Lock/percpu.md)。

## rwsem Under PREEMPT_RT

RT 下 `struct rw_semaphore` 换成 `rwbase_rt`：

```c
context_lock_struct(rw_semaphore) {
	struct rwbase_rt	rwbase;
#ifdef CONFIG_DEBUG_LOCK_ALLOC
	struct lockdep_map	dep_map;
#endif
};
```

与 mutex 换成 rt_mutex 同理，读写锁在 RT 下也走 `rwbase_rt.c` 的通用实现（可睡眠、带优先级继承）。乐观自旋那一整套在 RT 下没有意义——锁本身是睡眠锁了。

## seqlock

seqlock 的思路完全不同：**读侧完全不加锁**。

```c
/* 写侧 */
write_seqlock(&sl);
...修改数据...
write_sequnlock(&sl);      /* 进入/离开时各把 seq 加 1（使其变为奇数/偶数） */

/* 读侧 */
do {
        seq = read_seqbegin(&sl);   /* 取序号（奇数代表有写者） */
        ...读取数据...
} while (read_seqretry(&sl, seq));  /* 序号变了或当时是奇数 → 重读 */
```

底层是 `seqcount_t`——一个裸计数器，不提供任何写者互斥：

```c
/*
 * Sequence counters (seqcount_t)
 *
 * This is the raw counting mechanism, without any writer protection.
 *
 * Write side critical sections must be serialized and non-preemptible.
 * ...
 * This mechanism can't be used if the protected data contains pointers,
 * as the writer can invalidate a pointer that a reader is following.
 */
typedef struct seqcount {
	unsigned sequence;
#ifdef CONFIG_DEBUG_LOCK_ALLOC
	struct lockdep_map dep_map;
#endif
} seqcount_t;
```

`seqlock_t` = `seqcount_t` + 一把 spinlock（由写侧持有，提供互斥）。`seqcount_spinlock_t` 这类变体则把计数器与"外部已有的锁"绑定。

读侧的 `read_seqbegin()` / `read_seqretry()` 只是对 `seqcount` 的包装（`include/linux/seqlock.h:835` / `:852`）。

必须记住的三条限制：

- **读侧不能解引用可能被释放的指针**：重试机制只能发现"数据被改过"，救不了 use-after-free。需要这种能力要用 RCU；
- **只保护"可重读的数据副本"**，不适合有副作用的操作（读时顺手修改统计量会被重复执行）；
- **写侧不可抢占**（RT 下写侧不能关抢占，所以 `seqcount_LOCKNAME_t` 在 RT 上改用"读者检测到写者进行中就拿一下锁"的技巧来避免活锁）。

典型用途：`jiffies` 与时间戳（`get_jiffies_64()`）、`xtime`、`vfsmount` 的部分字段。

## Choosing

- 临界区短 + 不需要睡眠 + 写不饥饿 → **rwlock**（内核新代码更倾向 RCU）；
- 临界区可能阻塞 → **rwsem**；
- 读侧要零开销、且对象生命周期能被延迟回收 → **seqlock**（简单数据）或 [RCU](/docs/CS/OS/Linux/Lock/RCU.md)（指针结构）；
- 读侧频率高到共享原子变量成为瓶颈、而写侧几乎不发生 → **percpu-rwsem**。

## Observation

`CONFIG_LOCK_EVENT_COUNTS` 下 debugfs 的 `lock_event_counts/` 里 rwsem 相关计数器最能说明问题：

| 计数器 | 含义 | 怎么读 |
| :-- | :-- | :-- |
| `rwsem_rlock_fast` / `rwsem_rlock_steal` | 读锁快路径 / 偷锁成功次数 | steal 很多说明等待队列常被"绕开" |
| `rwsem_rlock` / `rwsem_sleep_reader` | 读锁成功 / 读者入睡次数 | 比值高说明读者经常要睡 |
| `rwsem_wlock` / `rwsem_sleep_writer` | 写锁成功 / 写者入睡次数 | 同上 |
| `rwsem_wlock_handoff` | 写者触发 handoff 的次数 | 高说明写者被挡得久（>= 4ms） |
| `rwsem_opt_lock` / `rwsem_opt_fail` / `rwsem_opt_nospin` | 乐观自旋成功 / 失败 / 因 NONSPINNABLE 放弃 | `opt_nospin` 高 = 这把锁上读者太多，写者别指望自旋 |
| `rwsem_wake_writer` / `rwsem_wake_reader` | 唤醒写者 / 读者的次数 | 反映读写比例 |

另外 `CONFIG_DEBUG_RWSEMS` 会校验"读者解锁时确实是读者持有"这类语义；`CONFIG_DETECT_HUNG_TASK_BLOCKER` 能报出进程阻塞在哪把 rwsem 上。

## Links

- [Lock](/docs/CS/OS/Linux/Lock/README.md)
- [mutex](/docs/CS/OS/Linux/Lock/mutex.md) — 乐观自旋与 handoff 的同一套机制
- [per-CPU 变量](/docs/CS/OS/Linux/Lock/percpu.md) — percpu-rwsem 的基础
- [RCU](/docs/CS/OS/Linux/Lock/RCU.md) — 读侧真正免锁的替代
- [spinlock](/docs/CS/OS/Linux/Lock/spinlock.md) — osq 的来源

## References

- [Kernel docs: seqlock](https://docs.kernel.org/locking/seqlock.html)
- [LWN: R/W semaphores and priority inheritance](https://lwn.net/Articles/575460/)
- [LWN: The trouble with read-copy-update wait?](https://lwn.net/Articles/262464/)
- [Kernel docs: lockstat](https://docs.kernel.org/locking/lockstat.html)
