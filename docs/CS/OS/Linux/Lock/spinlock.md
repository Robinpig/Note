## Introduction

自旋锁（spinlock）是内核中最基础的忙等锁：拿不到锁就原地空转，直到持有者释放。它成立的前提是**临界区极短**——等待时间小于两次上下文切换的开销，否则空转就是纯粹的浪费。

自旋锁在单核（UP）上的语义与 SMP 不同：UP 上它退化为"关抢占"（`CONFIG_SMP=n` 时 `spin_lock` 只关抢占，因为不存在真正的并行竞争者），这也是很多驱动代码在 UP 上"看起来没问题"、一上 SMP 就出 bug 的原因。

x86 与 arm64 上的默认实现是 **qspinlock**（queued spinlock），代码在 `kernel/locking/qspinlock.c` 与 `include/asm-generic/qspinlock.h`。它是一个"塞进 4 个字节里的 MCS 队列锁"——既要保留 `spinlock_t` 只有 4 字节的历史 ABI，又想拿到 MCS 锁"每个等待者自旋自己的变量"的可扩展性。本文按源码的四级结构展开：**快速路径 → pending 位 → MCS 队列 → PV 让出**。

## 使用规则

> [!WARNING]
>
> Spin Locks Are Not Recursive!

- **不可递归**：同一 CPU 再次获取同一把锁会永久自旋（nobody releases it）；
- **持有期间不可睡眠**：睡眠意味着调度走，而锁仍被持有——其他 CPU 会一直自旋；如果锁用于中断，甚至可能被自己打断造成死锁；
- **临界区越短越好**：慢路径会退化为自旋 + 让出（`CONFIG_DEBUG_SPINLOCK` 下还有额外的检查开销）。

> The configure option CONFIG_DEBUG_SPINLOCK enables a handful of debugging checks in the spin lock code.

配合 `lockdep`（`CONFIG_PROVE_LOCKING`）可以检测锁顺序倒置等死锁风险，见 [死锁与调试](/docs/CS/OS/Linux/Lock/README.md?id=死锁与调试)。

## 中断与 API 选择

自旋锁最大的坑是**中断打断持锁者**：如果中断处理程序也要获取同一把锁，那么中断发生在持锁期间时，中断里会自旋等到天荒地老——因为持锁者永远不会被调度回来。因此 API 按"要不要关中断/关下半部"分成一组：

| API | 关抢占 | 关中断 | 关软中断 | 使用场景 |
| :-- | :--: | :--: | :--: | :-- |
| `spin_lock()` | 是 | 否 | 否 | 进程上下文，锁不会被中断获取 |
| `spin_lock_bh()` | 是 | 否 | 是 | 锁会被下半部（软中断/tasklet）获取 |
| `spin_lock_irq()` | 是 | 是 | 是 | 锁会被中断处理程序获取，且明确知道中断是开着的 |
| `spin_lock_irqsave()` | 是 | 是 | 是 | 同上，但保存并恢复中断状态（最安全，最常用） |

`spin_lock_irqsave()` 保存中断状态是必要的：调用者可能本身就运行在关中断的上下文里，无条件开中断（`spin_unlock_irq`）会破坏外层假设。

内核实现（`include/linux/spinlock.h`）：

```c
/*
 * If lockdep is enabled then we use the non-preemption spin-ops
 * even on CONFIG_PREEMPTION, because lockdep assumes that interrupts are
 * not re-enabled during lock-acquire (which the preempt-spin-ops do):
 */
#if !defined(CONFIG_GENERIC_LOCKBREAK) || defined(CONFIG_DEBUG_LOCK_ALLOC)

static inline unsigned long __raw_spin_lock_irqsave(raw_spinlock_t *lock)
{
	unsigned long flags;

	local_irq_save(flags);
	preempt_disable();
	spin_acquire(&lock->dep_map, 0, 0, _RET_IP_);
	/*
	 * On lockdep we dont want the hand-coded irq-enable of
	 * do_raw_spin_lock_flags() code, because lockdep assumes
	 * that interrupts are not re-enabled during lock-acquire:
	 */
#ifdef CONFIG_LOCKDEP
	LOCK_CONTENDED(lock, do_raw_spin_trylock, do_raw_spin_lock);
#else
	do_raw_spin_lock_flags(lock, &flags);
#endif
	return flags;
}
```

disable local irq：

```c
static inline void __raw_spin_lock_irq(raw_spinlock_t *lock)
{
	local_irq_disable();
	preempt_disable();
	spin_acquire(&lock->dep_map, 0, 0, _RET_IP_);
	LOCK_CONTENDED(lock, do_raw_spin_trylock, do_raw_spin_lock);
}
```

释放侧恢复抢占（中断由 `irqrestore` 或 `local_irq_enable` 恢复）：

```c
static inline void __raw_spin_unlock(raw_spinlock_t *lock)
{
	spin_release(&lock->dep_map, _RET_IP_);
	do_raw_spin_unlock(lock);
	preempt_enable();
}
```

注意 `spin_lock()`/`spin_unlock()` 在可抢占内核中隐含了 `preempt_disable()`/`preempt_enable()`：不仅防止其他 CPU 竞争，也防止本 CPU 上切换到另一个想拿同一把锁的任务。

## 为什么锁要排队：TAS → ticket → MCS

自旋锁的性能瓶颈不在"自旋"本身，而在**自旋时访问了什么**。

1. **test-and-set（TAS）**：所有等待者反复对同一个 `lock->lock` 字做原子写。每次写都会让其他所有 CPU 上该 cache line 的副本失效，于是 N 个等待者制造 N² 级别的 cache line 抖动（cacheline ping-pong）。
2. **ticket spinlock**：进门取号、出门叫号（`owner`/`next` 两个计数器），解决了公平性（先到先得，不再有饥饿），但**所有等待者仍在同一个 counter 上自旋**，抖动没解决，只是从"写"降级成了"读"。
3. **MCS 锁**（Mellor-Crummey & Scott）：把等待者组织成链表，**每个 CPU 只自旋自己的 `node->locked`**，锁的交接是"前驱写后继的一个私有字节"。cache line 流量从 O(N²) 降到 O(N)。

MCS 锁的代价是**锁字变成了指针**（8 字节），而且调用者必须自带一个 node、并在解锁时把它传回去——这与 `spinlock_t` 是 4 字节、API 只有 `spin_lock(lock)` 的历史约定直接冲突。

qspinlock 的全部技巧，就是如何在 **4 字节**里既塞下 MCS 的排队语义，又不用把 node 从加锁传到解锁。

## qspinlock 的 4 字节布局

`include/asm-generic/qspinlock_types.h`：

```c
typedef struct qspinlock {
	union {
		atomic_t val;

		/*
		 * By using the whole 2nd least significant byte for the
		 * pending bit, we can allow better optimization of the lock
		 * acquisition for the pending bit holder.
		 */
#ifdef __LITTLE_ENDIAN
		struct {
			u8	locked;
			u8	pending;
		};
		struct {
			u16	locked_pending;
			u16	tail;
		};
#else
		struct {
			u16	tail;
			u16	locked_pending;
		};
		struct {
			u8	reserved[2];
			u8	pending;
			u8	locked;
		};
#endif
	};
} arch_spinlock_t;
```

32 位被切成三段（`NR_CPUS < 16K` 时）：

```
 31                        18 17 16              8 7       0
+----------------------------+-----+--------------+--------+
|      tail cpu (+1)         | idx |  pending     | locked |
+----------------------------+-----+--------------+--------+
```

| 字段 | 位宽 | 含义 |
| :-- | :-- | :-- |
| `locked` | 8 位 | 锁是否被持有。虽然只需 1 位，但**占用整个字节**：支持原子字节写的架构（x86）可以用单条 `movb` 完成解锁，不必做 read-modify-write |
| `pending` | 8 位（默认） | "已有人排在第一位、正在等锁被释放"。同样是 8 位而非 1 位，好让 pending 持有者能一次性把 `locked_pending` 这个 16 位字写完 |
| `tail` | 16 位 | 队尾编码：2 位 `idx`（嵌套层级）+ 14 位 `cpu+1` |

当 `NR_CPUS >= 16K` 时位宽会重排（`_Q_PENDING_BITS` 从 8 缩到 1，把位让给 tail），走另一套 `clear_pending` / `xchg_tail` 实现（用 `atomic_andnot` 与 cmpxchg 循环替代字节/半字写）。

`tail` 里的 CPU 编号要 **+1** 再存，源码给了理由：必须能区分"没有 tail"和"tail 恰好是 cpu0 idx0"，否则 `old & _Q_TAIL_MASK` 判不出有没有前驱。

```c
/*
 * We must be able to distinguish between no-tail and the tail at 0:0,
 * therefore increment the cpu number by one.
 */

static inline __pure u32 encode_tail(int cpu, int idx)
{
	u32 tail;

	tail  = (cpu + 1) << _Q_TAIL_CPU_OFFSET;
	tail |= idx << _Q_TAIL_IDX_OFFSET; /* assume < 4 */

	return tail;
}
```

## 快速路径：一个 cmpxchg 与一个字节写

加锁的快路径就是"把 0 换成 1"（`include/asm-generic/qspinlock.h`）：

```c
static __always_inline void queued_spin_lock(struct qspinlock *lock)
{
	int val = 0;

	if (likely(atomic_try_cmpxchg_acquire(&lock->val, &val, _Q_LOCKED_VAL)))
		return;

	queued_spin_lock_slowpath(lock, val);
}
```

`atomic_try_cmpxchg_acquire()` 失败时会把**当前值**写回 `val`，所以慢路径入口拿到的 `val` 是"失败那一刻看到的锁状态"——后面所有分支都基于这个观察值，避免再读一次。

解锁更简单，**只写一个字节**：

```c
static __always_inline void queued_spin_unlock(struct qspinlock *lock)
{
	/*
	 * unlock() needs release semantics:
	 */
	smp_store_release(&lock->locked, 0);
}
```

注意这里不做原子 RMW：因为 `locked` 独占一个字节，写 0 是原子的（架构保证单字节访问不对齐撕裂），`smp_store_release` 提供 release 语义即可。**这是 locked 字段占满 8 位的直接收益**——解锁路径上没有 `lock` 前缀指令。

## pending 位：两级自旋的第一级

qspinlock 保留了"队首者在锁字上自旋"的行为。源码注释里那张状态机图就是全部逻辑：

```c
 * (queue tail, pending bit, lock value)
 *
 *              fast     :    slow                                  :    unlock
 *                       :                                          :
 * uncontended  (0,0,0) -:--> (0,0,1) ------------------------------:--> (*,*,0)
 *                       :       | ^--------.------.             /  :
 *                       :       v           \      \            |  :
 * pending               :    (0,1,1) +--> (0,1,0)   \           |  :
 *                       :       | ^--'              |           |  :
 *                       :       v                   |           |  :
 * uncontended           :    (n,x,y) +--> (n,0,0) --'           |  :
 *   queue               :       | ^--'                          |  :
 *                       :       v                               |  :
 * contended             :    (*,x,y) +--> (*,0,0) ---> (*,0,1) -'  :
 *   queue               :         ^--'                             :
```

pending 的存在是为了处理**只有两个参与者**的常见场景：一个人持锁、一个人来抢。这时如果直接进 MCS 队列，就要初始化 node、做 `xchg_tail`、链接链表——为两个人的竞争付出全套排队开销。pending 位提供了一条"轻量中间态"：第二个人只要置上 pending，然后自旋等 locked 清零即可。

```c
	/*
	 * If we observe any contention; queue.
	 */
	if (val & ~_Q_LOCKED_MASK)
		goto queue;

	/*
	 * trylock || pending
	 *
	 * 0,0,* -> 0,1,* -> 0,0,1 pending, trylock
	 */
	val = queued_fetch_set_pending_acquire(lock);

	/*
	 * If we observe contention, there is a concurrent locker.
	 *
	 * Undo and queue; our setting of PENDING might have made the
	 * n,0,0 -> 0,0,0 transition fail and it will now be waiting
	 * on @next to become !NULL.
	 */
	if (unlikely(val & ~_Q_LOCKED_MASK)) {

		/* Undo PENDING if we set it. */
		if (!(val & _Q_PENDING_MASK))
			clear_pending(lock);

		goto queue;
	}

	/*
	 * We're pending, wait for the owner to go away.
	 *
	 * 0,1,1 -> *,1,0
	 *
	 * this wait loop must be a load-acquire such that we match the
	 * store-release that clears the locked bit and create lock
	 * sequentiality; this is because not all
	 * clear_pending_set_locked() implementations imply full
	 * barriers.
	 */
	if (val & _Q_LOCKED_MASK)
		smp_cond_load_acquire(&lock->locked, !VAL);

	/*
	 * take ownership and clear the pending bit.
	 *
	 * 0,1,0 -> 0,0,1
	 */
	clear_pending_set_locked(lock);
	lockevent_inc(lock_pending);
	return;
```

几个容易看漏的点：

- **pending 是"乐观"的**：置位之后要再检查一次是不是真的没人排队（`val & ~_Q_LOCKED_MASK`），如果有人就得撤销（只撤销自己置的那一位）并转去排队。
- **`(0,1,0)` 是危险的中间态**：持锁者刚释放（locked=0）、pending 者还没接管。此时若有第三者进来，它会看到 pending 已置位而去排队，但 pending 者马上就要接管了——队列里的第四者会等一个"已经不在队列里"的人。源码对这种情况做了**有界自旋**而不是无限等待：

```c
	/*
	 * Wait for in-progress pending->locked hand-overs with a bounded
	 * number of spins so that we guarantee forward progress.
	 *
	 * 0,1,0 -> 0,0,1
	 */
	if (val == _Q_PENDING_VAL) {
		int cnt = _Q_PENDING_LOOPS;
		val = atomic_cond_read_relaxed(&lock->val,
					       (VAL != _Q_PENDING_VAL) || !cnt--);
	}
```

- **`clear_pending_set_locked()` 在所有字段都就位时是一条 16 位写**：

```c
static __always_inline void clear_pending_set_locked(struct qspinlock *lock)
{
	WRITE_ONCE(lock->locked_pending, _Q_LOCKED_VAL);
}
```

  这正是"pending 占一整个字节"换来的优化——清 pending 与置 locked 是一个写操作，中间不存在"两者都为 0"的窗口。

- **`_Q_PENDING_LOOPS` 是架构可调的**：generic 版本只有 `1`，x86 定义为 `1 << 9`（512）。x86 的 `queued_fetch_set_pending_acquire()` 用 `btsl` 单指令实现，等待成本足够低，值得多等一会儿再去做昂贵的排队；generic 版本走 `atomic_fetch_or_acquire()`，退化成 cmpxchg 循环的架构上不划算，所以只等一次。

x86 的实现（`arch/x86/include/asm/qspinlock.h`）：

```c
#define _Q_PENDING_LOOPS	(1 << 9)

#define queued_fetch_set_pending_acquire queued_fetch_set_pending_acquire
static __always_inline u32 queued_fetch_set_pending_acquire(struct qspinlock *lock)
{
	u32 val;

	/*
	 * We can't use GEN_BINARY_RMWcc() inside an if() stmt because asm goto
	 * and CONFIG_PROFILE_ALL_BRANCHES=y results in a label inside a
	 * statement expression, which GCC doesn't like.
	 */
	val = GEN_BINARY_RMWcc(LOCK_PREFIX "btsl", lock->val.counter, c,
			       "I", _Q_PENDING_OFFSET) * _Q_PENDING_VAL;
	val |= atomic_read(&lock->val) & ~_Q_PENDING_MASK;

	return val;
}
```

`btsl`（bit test and set）返回的是"位的旧值"，乘上 `_Q_PENDING_VAL` 还原成"我是否设置了它"，再或上其余字段。

## 慢路径：MCS 队列

真正的排队从 `queue:` 标签开始。

```c
queue:
	lockevent_inc(lock_slowpath);
pv_queue:
	node = this_cpu_ptr(&qnodes[0].mcs);
	idx = node->count++;
	tail = encode_tail(smp_processor_id(), idx);

	trace_contention_begin(lock, LCB_F_SPIN);
```

**每个 CPU 有 4 个节点**（`_Q_MAX_NODES`），因为内核里能嵌套抢锁的上下文最多 4 层：task、softirq、hardirq、NMI。同一 CPU 在不同嵌套层级抢同一把锁（不同锁，或 NMI 抢别的锁）时各用各的 node，互不覆盖。

```c
	/*
	 * 4 nodes are allocated based on the assumption that there will
	 * not be nested NMIs taking spinlocks. That may not be true in
	 * some architectures even though the chance of needing more than
	 * 4 nodes will still be extremely unlikely. When that happens,
	 * we fall back to spinning on the lock directly without using
	 * any MCS node. This is not the most elegant solution, but is
	 * simple enough.
	 */
	if (unlikely(idx >= _Q_MAX_NODES)) {
		lockevent_inc(lock_no_node);
		while (!queued_spin_trylock(lock))
			cpu_relax();
		goto release;
	}

	node = grab_mcs_node(node, idx);
```

注意"4 个节点"**不是**给递归加锁用的——同一把锁递归依然是死循环。它是给"同一个 CPU 在嵌套上下文里等待**不同的**锁"用的。超过 4 层（极端 NMI 嵌套）时退化成不排队的纯 trylock 自旋：不公平，但至少不会写坏别人的 node。

节点初始化与入队：

```c
	/*
	 * Ensure that we increment the head node->count before initialising
	 * the actual node. If the compiler is kind enough to reorder these
	 * stores, then an IRQ could overwrite our assignments.
	 */
	barrier();

	node->locked = 0;
	node->next = NULL;
	pv_init_node(node);

	/*
	 * We touched a (possibly) cold cacheline in the per-cpu queue node;
	 * attempt the trylock once more in the hope someone let go while we
	 * weren't watching.
	 */
	if (queued_spin_trylock(lock))
		goto release;

	/*
	 * Ensure that the initialisation of @node is complete before we
	 * publish the updated tail via xchg_tail() and potentially link
	 * @node into the waitqueue via WRITE_ONCE(prev->next, node) below.
	 */
	smp_wmb();

	/*
	 * Publish the updated tail.
	 * We have already touched the queueing cacheline; don't bother with
	 * pending stuff.
	 *
	 * p,*,* -> n,*,*
	 */
	old = xchg_tail(lock, tail);
	next = NULL;
```

两个细节值得记住：

- `barrier()`（编译器屏障，不是内存屏障）是为了防编译器把 `count++` 挪到 node 初始化之后——本 CPU 上若被中断打断，中断里抢锁会复用同一个 `qnodes[0]`，顺序错了就会覆盖。
- **入队之后又 trylock 一次**：初始化 node 意味着刚碰过一条很可能是冷的 cache line，这段时间里持锁者可能已经释放了，与其排队不如再试一次。

链接到前驱并自旋自己的节点：

```c
	if (old & _Q_TAIL_MASK) {
		prev = decode_tail(old, qnodes);

		/* Link @node into the waitqueue. */
		WRITE_ONCE(prev->next, node);

		pv_wait_node(node, prev);
		arch_mcs_spin_lock_contended(&node->locked);

		/*
		 * While waiting for the MCS lock, the next pointer may have
		 * been set by another lock waiter. We optimistically load
		 * the next pointer & prefetch the cacheline for writing
		 * to reduce latency in the upcoming MCS unlock operation.
		 */
		next = READ_ONCE(node->next);
		if (next)
			prefetchw(next);
	}
```

**这里是 MCS 的核心**：等待者只对 `node->locked`（自己 CPU 上的 per-CPU 变量）做 `smp_cond_load_acquire`，不再碰共享的锁字。同时"乐观预取"后继节点——等下解锁时要写 `next->locked`，先 `prefetchw` 把它拉进本 CPU 的 cache 且置于可写态，省掉一次 cache 一致性事务。

`arch_mcs_spin_lock_contended()` 默认就是 `smp_cond_load_acquire(l, VAL)`，架构可覆盖（arm 用自己的实现，arm64 借 `smp_cond_load_acquire` 拿到 WFE 低功耗自旋）。

### 队首为什么自旋锁字而不是自己的节点

经典 MCS 锁里，**队首**也是自旋自己的 node。qspinlock 改成了让队首自旋共享的锁字：

```c
	/*
	 * we're at the head of the waitqueue, wait for the owner & pending to
	 * go away.
	 *
	 * *,x,y -> *,0,0
	 *
	 * this wait loop must use a load-acquire such that we match the
	 * store-release that clears the locked bit and create lock
	 * sequentiality; this is because the set_locked() function below
	 * does not imply a full barrier.
	 */
	val = atomic_cond_read_acquire(&lock->val, !(VAL & _Q_LOCKED_PENDING_MASK));
```

源码开头的注释解释了动机：

> We also change the first spinner to spin on the lock bit instead of its node; whereby avoiding the need to carry a node from lock to unlock, and preserving existing lock API. This also makes the unlock code simpler and faster.

代价是队首（只有队首）会造成锁字的 cache line 竞争——但队首只有一个，抖动是 O(1) 而非 O(N)。收益是 **`spin_unlock()` 不需要知道谁在等、不需要传递 node**，API 保持不变。

### 退出：一次 cmpxchg 完成"接管 + 清空队列"

拿到锁之后，如果后面没人排队，可以一步到位把整个锁字清成 `_Q_LOCKED_VAL`：

```c
locked:
	/*
	 * claim the lock:
	 *
	 * n,0,0 -> 0,0,1 : lock, uncontended
	 * *,*,0 -> *,*,1 : lock, contended
	 *
	 * If the queue head is the only one in the queue (lock value == tail)
	 * and nobody is pending, clear the tail code and grab the lock.
	 * Otherwise, we only need to grab the lock.
	 */
	if ((val & _Q_TAIL_MASK) == tail) {
		if (atomic_try_cmpxchg_relaxed(&lock->val, &val, _Q_LOCKED_VAL))
			goto release; /* No contention */
	}

	/*
	 * Either somebody is queued behind us or _Q_PENDING_VAL got set
	 * which will then detect the remaining tail and queue behind us
	 * ensuring we'll see a @next.
	 */
	set_locked(lock);

	/*
	 * contended path; wait for next if not observed yet, release.
	 */
	if (!next)
		next = smp_cond_load_relaxed(&node->next, (VAL));

	arch_mcs_spin_unlock_contended(&next->locked);
	pv_kick_node(lock, next);

release:
	trace_contention_end(lock, 0);

	/*
	 * release the node
	 */
	__this_cpu_dec(qnodes[0].mcs.count);
}
```

判定"只有我一个人"的条件是 `(val & _Q_TAIL_MASK) == tail`——tail 字段等于我刚写进去的编码，说明我既是队首也是队尾。

否则走交接：`set_locked(lock)`（写 `locked` 字节）之后，等 `node->next` 出现（可能是刚入队还没来得及写指针的竞争者），然后写 `next->locked = 1` 把锁传下去。

## pvqspinlock：把自旋换成 halt

虚拟机里自旋是纯粹的浪费：持锁者可能是一个**被宿主机调度出去的 vCPU**，它根本没在跑，等待者空转几百微秒也等不到锁释放，还白白占着一个物理核。

`CONFIG_PARAVIRT_SPINLOCKS` 下，qspinlock 换成 pvqspinlock，依赖两个 hypercall：

```
 *   pv_wait(u8 *ptr, u8 val) -- suspends the vcpu if *ptr == val
 *   pv_kick(cpu)             -- wakes a suspended vcpu
```

思路是"先自旋一小会儿，不行就 halt"：`SPIN_THRESHOLD` 在 x86 上是 `1 << 15`（32768）次循环。

pv 把 `mcs_spinlock` 扩展成 `pv_node`，多带 CPU 号与状态：

```c
/*
 * Queue Node Adaptive Spinning
 *
 * A queue node vCPU will stop spinning if the vCPU in the previous node is
 * not running. The one lock stealing attempt allowed at slowpath entry
 * mitigates the slight slowdown for non-overcommitted guest with this
 * aggressive wait-early mechanism.
 *
 * The status of the previous node will be checked at fixed interval
 * controlled by PV_PREV_CHECK_MASK. This is to ensure that we won't
 * pound on the cacheline of the previous node too heavily.
 */
#define PV_PREV_CHECK_MASK	0xff

/*
 * Queue node uses: VCPU_RUNNING & VCPU_HALTED.
 * Queue head uses: VCPU_RUNNING & VCPU_HASHED.
 */
enum vcpu_state {
	VCPU_RUNNING = 0,
	VCPU_HALTED,		/* Used only in pv_wait_node */
	VCPU_HASHED,		/* = pv_hash'ed + VCPU_HALTED */
};

struct pv_node {
	struct mcs_spinlock	mcs;
	int			cpu;
	u8			state;
};
```

三个状态对应三件事：`RUNNING`（在跑，正常自旋）、`HALTED`（已 halt，靠 `pv_wait` 挂起）、`HASHED`（已登记到锁的哈希表，unlock 时会被查表唤醒）。

### wait-early：前驱没在跑就别等了

```c
	for (;;) {
		for (wait_early = false, loop = SPIN_THRESHOLD; loop; loop--) {
			if (READ_ONCE(node->locked))
				return;
			if (pv_wait_early(pp, loop)) {
				wait_early = true;
				break;
			}
			cpu_relax();
		}

		/*
		 * Order pn->state vs pn->locked thusly:
		 *
		 * [S] pn->state = VCPU_HALTED	  [S] next->locked = 1
		 *     MB			      MB
		 * [L] pn->locked		[RmW] pn->state = VCPU_HASHED
		 *
		 * Matches the cmpxchg() from pv_kick_node().
		 */
		smp_store_mb(pn->state, VCPU_HALTED);

		if (!READ_ONCE(node->locked)) {
			lockevent_inc(pv_wait_node);
			lockevent_cond_inc(pv_wait_early, wait_early);
			pv_wait(&pn->state, VCPU_HALTED);
		}
```

`pv_wait_early()` 检查**前驱节点的 vCPU 是否在运行**（通过 `vcpu_is_preempted()`），如果不运行就提前 halt——因为等一个被抢占的 vCPU 释放锁是毫无意义的。检查按 `PV_PREV_CHECK_MASK` 节流（每 256 次循环查一次），避免频繁读前驱的 cache line。

### kick 不唤醒，而是"推进状态"

常规实现里，解锁者要唤醒后继（wake/sleep 一次往返）。pv 版做了个优化：不唤醒，而是把后继的 state 从 `HALTED` 改成 `HASHED`，并把它要等的锁登记进哈希表：

```c
/*
 * Called after setting next->locked = 1 when we're the lock owner.
 *
 * Instead of waking the waiters stuck in pv_wait_node() advance their state
 * such that they're waiting in pv_wait_head_or_lock(), this avoids a
 * wake/sleep cycle.
 */
static void pv_kick_node(struct qspinlock *lock, struct mcs_spinlock *node)
{
	struct pv_node *pn = (struct pv_node *)node;
	u8 old = VCPU_HALTED;
	/*
	 * If the vCPU is indeed halted, advance its state to match that of
	 * pv_wait_node(). If OTOH this fails, the vCPU was running and will
	 * observe its next->locked value and advance itself.
	 */
	smp_mb__before_atomic();
	if (!try_cmpxchg_relaxed(&pn->state, &old, VCPU_HASHED))
		return;

	/*
	 * Put the lock into the hash table and set the _Q_SLOW_VAL.
	 *
	 * As this is the same vCPU that will check the _Q_SLOW_VAL value and
	 * the hash table later on at unlock time, no atomic instruction is
	 * needed.
	 */
	WRITE_ONCE(lock->locked, _Q_SLOW_VAL);
	(void)pv_hash(lock, pn);
}
```

被"推进"的 vCPU 醒来后不再睡第二次，而是直接进入队首逻辑（`pv_wait_head_or_lock`）自旋锁字。同时锁的 `locked` 字节被写成 `_Q_SLOW_VAL`（=3，一个非法值），作为"这把锁有人在哈希表里等"的标记，unlock 时据此决定要不要查表 kick。

### 混合公平/非公平：允许偷锁

pv 下还允许"偷锁"（lock stealing）——队列非空但队首还没准备好时，新来的等待者可以直接抢：

```c
#define queued_spin_trylock(l)	pv_hybrid_queued_unfair_trylock(l)
static inline bool pv_hybrid_queued_unfair_trylock(struct qspinlock *lock)
{
	/*
	 * Stay in unfair lock mode as long as queued mode waiters are
	 * present in the MCS wait queue but the pending bit isn't set.
	 */
	for (;;) {
		int val = atomic_read(&lock->val);
		u8 old = 0;

		if (!(val & _Q_LOCKED_PENDING_MASK) &&
		    try_cmpxchg_acquire(&lock->locked, &old, _Q_LOCKED_VAL)) {
			lockevent_inc(pv_lock_stealing);
			return true;
		}
		if (!(val & _Q_TAIL_MASK) || (val & _Q_PENDING_MASK))
			break;

		cpu_relax();
	}

	return false;
}
```

**pending 位在这里有了第二重语义**：队首 vCPU 一旦开始正式自旋（在 `pv_wait_head_or_lock()` 里 `set_pending`），就禁止别人偷锁。所以只要队列里的队首 vCPU 在跑，偷锁就不会造成饥饿——源码注释称之为 "hybrid PV queued/unfair lock"，兼顾非公平锁的性能与队列锁的无饥饿。

## PREEMPT_RT 下的 spinlock

`CONFIG_PREEMPT_RT` 下 `spinlock_t` 不再自旋，而是退化成可睡眠的 `rt_mutex_base`。v7.2.7 的实现（`kernel/locking/spinlock_rt.c`）：

```c
static __always_inline void __rt_spin_lock(spinlock_t *lock)
{
	rtlock_might_resched();
	rtlock_lock(&lock->lock);
	rcu_read_lock();
	migrate_disable();
}

void __sched rt_spin_lock(spinlock_t *lock) __acquires(RCU)
{
	spin_acquire(&lock->dep_map, 0, 0, _RET_IP_);
	__rt_spin_lock(lock);
}
```

三个副作用值得注意：

1. **获取 spinlock 会隐式持有 RCU 读锁**。因为临界区现在可以睡眠（等待 rt_mutex），传统上"spinlock 保护的数据就是 RCU 读侧临界区"的假设需要显式保证。解锁顺序也因此有讲究——`rcu_read_unlock()` 必须最后做：

```c
void __sched rt_spin_unlock(spinlock_t *lock) __releases(RCU)
{
	spin_release(&lock->dep_map, _RET_IP_);
	migrate_enable();

	if (unlikely(!rt_mutex_cmpxchg_release(&lock->lock, current, NULL)))
		rt_mutex_slowunlock(&lock->lock);

	/*
	 * This must be last to prevent the following UAF:
	 *
	 * T1					T2
	 * spin_lock(&p->lock);			rcu_read_lock();
	 * invalidate(p);			p = rcu_dereference(ptr);
	 * rcu_assign_pointer(ptr, NULL);	if (!p) return;
	 * spin_unlock(&p->lock);		spin_lock(&p->lock);
	 * kfree_rcu(p);			rcu_read_unlock();
	 *					....
	 *					spin_unlock(&p->lock)
	 *					  rcu_read_unlock(); // Ends grace period
	 * rcu_do_batch()
	 *   kfree(p);
	 *				    UAF ->  rt_mutex_cmpxchg_release(&p->lock.lock...)
	 */
	rcu_read_unlock();
}
```

2. **获取 spinlock 会 `migrate_disable()`**：RT 下锁是可迁移感知的，禁止迁移是为了让 per-CPU 数据访问仍然安全。
3. **`raw_spinlock_t` 保持真正的自旋**（永远不变成睡眠锁）。所以"RT 下 spinlock 可以睡眠"这句话只对 `spinlock_t` 成立，`raw_spinlock_t` 依旧禁止在临界区睡眠。

## 架构适配要求

qspinlock 不是随便能用的，源码头部的注释列了硬约束：

- **必须支持 8 位与 16 位的原子操作**。慢路径用了 `xchg16`（`xchg_tail`），LL/SC 架构往往得把半字操作实现成"32 位 and + or"才能满足 forward progress。
- **原子操作要按 RCsc 语义协同**（至少不弱于 RCtso），比普通 `atomic_t` 要求的 RCpc 更强。
- **混合尺寸原子操作的正确性**有专门论文讨论（见 References）。

`include/asm-generic/qspinlock.h` 开头甚至直接劝退：想找通用自旋锁的架构，应该先考虑 ticket lock，确认硬件在 qspinlock 上真的更快再来。

已适配的架构差异：

| 架构 | 差异 |
| :-- | :-- |
| x86 | `queued_fetch_set_pending_acquire()` 用 `LOCK_PREFIX "btsl"`；`_Q_PENDING_LOOPS = 1<<9`；`SPIN_THRESHOLD = 1<<15`；pvqspinlock 可用 |
| arm64 | 用标准的 `asm-generic/qspinlock_types.h`，等待走 `smp_cond_load_acquire()`（可映射为 WFE 低功耗自旋）；`vcpu_is_preempted()` 返回 false |
| arm32 | 提供自己的 `arch_mcs_spin_lock_contended()` |
| 不支持字节/半字原子的架构 | 只能用 ticket lock 或 `asm-generic/spinlock.h` |

> [!NOTE]
>
> `arch/arm64/include/asm/rqspinlock.h` 名字看着像 "arm64 版 qspinlock"，其实不是——**rqspinlock 是 BPF 子系统的 resilient spin lock**（实现在 `kernel/bpf/rqspinlock.c`，服务于 `bpf_res_spin_lock`），带超时检测与 AA/ABBA 死锁检查。arm64 的普通自旋锁仍是标准 qspinlock。

## 观测

内核自带锁事件计数器，由 `CONFIG_LOCK_EVENT_COUNTS` 开启，暴露在 debugfs 的 `lock_event_counts/` 目录下（每个事件一个文件，`.reset_counts` 可写清零）：

| 计数器 | 含义 |
| :-- | :-- |
| `lock_pending` | 走 pending 位拿到锁的次数（说明竞争只有两方） |
| `lock_slowpath` | 进 MCS 队列的次数 |
| `lock_use_node2` / `lock_use_node3` / `lock_use_node4` | 用到第 2/3/4 个 per-CPU 节点的次数（反映嵌套抢锁） |
| `lock_no_node` | 节点耗尽、退化为纯 trylock 自旋的次数 |
| `pv_lock_stealing` | pvqspinlock 下偷锁成功的次数 |
| `pv_wait_node` / `pv_wait_early` / `pv_spurious_wakeup` | pv 路径的 halt 次数、提前 halt 次数、虚假唤醒次数 |
| `pv_latency_kick` / `pv_latency_wake` | pv 下 kick 与唤醒的平均延迟（需换算） |

读数时有个经验判断：**`lock_slowpath` 相对 `lock_pending` 的比例**能看出锁竞争到底有多激烈——如果大量进入慢路径，说明这把锁上的并发已经超过"两个人抢"的规模，值得考虑拆分或 per-CPU 化。

## 其他注意点

- `spin_is_locked()` 只用于断言/调试，不能用作同步判断；
- `raw_spinlock_t` 与 `spinlock_t` 的差别在 RT 内核下才有意义：`raw_` 版本永不转换为睡眠锁；
- rwlock 是自旋锁的读写变体，见 [rwlock / rwsem / seqlock](/docs/CS/OS/Linux/Lock/rwsem.md)；需要读侧完全无锁的场景应改用 [RCU](/docs/CS/OS/Linux/Lock/RCU.md)；
- **"per-CPU 数据 + spinlock"不等于无锁**：如果临界区可以睡眠，RT 下 spinlock 会睡眠，`migrate_disable()` 保护的只是迁移安全，不是并发安全。

## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)
- [Lock](/docs/CS/OS/Linux/Lock/README.md)
- [原子操作与内存屏障](/docs/CS/OS/Linux/Lock/atomic.md)
- [mutex](/docs/CS/OS/Linux/Lock/mutex.md)
- [per-CPU 变量](/docs/CS/OS/Linux/Lock/percpu.md)
- [RCU](/docs/CS/OS/Linux/Lock/RCU.md)

## References

- [Mellor-Crummey and Scott, Algorithms for Scalable Synchronization on Shared-Memory Multiprocessors](https://bugzilla.kernel.org/show_bug.cgi?id=206115)
- [LWN: Ticket spinlocks](https://lwn.net/Articles/590243/)
- [Kernel docs: spinlocks](https://docs.kernel.org/locking/spinlocks.html)
- [Mixed-size Atomics (POPL 2017)](http://www.cl.cam.ac.uk/~pes20/popl17/mixed-size.pdf)
- [Kernel docs: locktorure](https://docs.kernel.org/locking/locktorture.html)
