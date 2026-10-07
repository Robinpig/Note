## Introduction

RCU（Read Copy Update）是内核中唯一"读侧零原子操作开销"的同步机制，专门解决**读多写极少**的场景（链表遍历、路由表、dentry 缓存、`struct file` 查找……）。

它的核心思想是**用空间与时间换取读侧的零开销**：

- 写者不原地修改数据，而是**先复制（copy）、修改副本、再原子替换指针（update）**；
- 旧数据不能立即释放——可能还有读者正在访问，必须等到**所有在替换前就进入读侧临界区的读者都退出**（这段时间称为**宽限期 grace period**），才真正回收。

读侧因此可以做到：`rcu_read_lock()` 不产生任何原子指令，在非抢占内核里甚至是"零代码"（只是编译屏障）。

本篇先在概念层讲清宽限期的含义，再落到 v7.2.7 源码看 Tree RCU 是怎么**用一把全局序列号（gp_seq）驱动整个宽限期状态机**、**把每个 CPU 的静止状态收拢到一棵 rcu_node 树**、以及**回调如何被分批执行**的。最后覆盖 SRCU（可睡眠读侧）、RCU Tasks 家族、以及 kvfree_rcu / RCU_LAZY 这些工程化的变体。

## Reader-Side and Writer-Side API

```c
/* 读侧：进入/退出临界区 */
rcu_read_lock();
p = rcu_dereference(global_ptr);   /* 带依赖顺序的指针读取 */
if (p)
        use(p->field);             /* 临界区内对象不会被释放 */
rcu_read_unlock();

/* 写侧：发布新版本 */
new = kmalloc(...);
*new = *old;                       /* 复制 */
new->field = 42;                   /* 修改副本 */
rcu_assign_pointer(global_ptr, new);   /* 原子发布（含 release 语义） */

/* 等宽限期结束后再回收旧数据 */
synchronize_rcu();                 /* 阻塞等待：仅能用于可睡眠上下文 */
kfree(old);

/* 或者异步回收：立刻返回，宽限期结束后在回调上下文执行 */
call_rcu(&old->rcu, my_free_cb);
kfree_rcu(old, rcu);               /* 语法糖，等价于 call_rcu + kfree */
```

- `rcu_dereference()`/`rcu_assign_pointer()` 不只是"访问指针"，它们携带 [acquire/release 语义](/docs/CS/OS/Linux/Lock/atomic.md?id=smp-memory-barriers)，保证读者看到新指针时一定能看到已初始化的内容；
- **读侧限制**：临界区内不能睡眠（否则宽限期永远无法结束——除非用 SRCU），也不能"把指针带出临界区使用"；需要睡眠读者要用 SRCU；
- **写侧限制**：`synchronize_rcu()` 可以睡眠，但不能在中断/原子上下文中调用；写侧之间仍需自己的互斥（RCU 只协调读侧）。

## How the Grace Period Is Calculated

宽限期 = "所有 CPU 都至少经历过一次静止状态（quiescent state）"的时间。静止状态指"确定不再持有任何读侧临界区"的时点：

- 上下文切换（发生过调度）；
- 从内核态返回用户态；
- CPU 进入 idle（dyntick-idle）。

`synchronize_rcu()` 的延迟通常是**毫秒级**（取决于是否有人处在长临界区或 dyntick-idle），这也是"RCU 的旧数据何时真正释放"的常见疑问来源。

Tree RCU 用 per-CPU 的状态机跟踪这些事件，配合 `CONFIG_NO_HZ`（无滴答）与 `CONFIG_RCU_NOCB_CPU`（把回调搬到专门的 offload 线程，避免软中断抖动）做优化。下面看内核怎么用**一把全局序列号**把这一切串起来。

## Grace Period State Machine: gp_seq and Two-Phase Bit

Tree RCU 用一个 64 位全局计数器 `rcu_state.gp_seq` 标识"当前在第几个宽限期、以及它处于什么阶段"。其位布局定义在 `kernel/rcu/rcu.h`：

> 最低 **2 位**是控制标志（state，`RCU_SEQ_STATE_MASK`），高位是宽限期序号计数器（`RCU_SEQ_CTR_SHIFT = 2`）。当两段控制位都为 0 → 没有宽限期在进行；任一为非零 → 宽限期已开始并正在进行；宽限期完成时控制位清零、高位序号 +1。

`rcu_seq_start()` / `rcu_seq_end()` / `rcu_seq_snap()` 是操作它的三个原语：

```c
static inline void rcu_seq_start(unsigned long *sp) {
    WRITE_ONCE(*sp, *sp + 1);   /* 把 state 位置成 01，标记"宽限期开始" */
    smp_mb();
}
static inline unsigned long rcu_seq_endval(unsigned long *sp) {
    return (*sp | RCU_SEQ_STATE_MASK) + 1;  /* state 归零、序号进位 */
}
/* 返回"再过一个完整宽限期后"的快照值，供调用方判断自己的回调是否可跑 */
static inline unsigned long rcu_seq_snap(unsigned long *sp) {
    unsigned long s;
    s = (READ_ONCE(*sp) + 2 * RCU_SEQ_STATE_MASK + 1) & ~RCU_SEQ_STATE_MASK;
    smp_mb();
    return s;
}
```

整个宽限期由 **`rcu_gp_kthread`** 这个内核线程驱动，它就是一个 `init → fqs_loop → cleanup` 的大循环（`kernel/rcu/tree.c:2299`）：

1. **`rcu_gp_init()`**（`tree.c:1832`）：清 `gp_flags`，先 `rcu_seq_start(&rcu_state.gp_seq)` 推进序列号、把根 `rcu_node` 的 `qsmask` 置成"所有子节点都还没上报静止态"，再扫描各 CPU 初始化本轮状态。关键顺序：序列号推进**必须**发生在 CPU 热插拔扫描之前，否则可能漏掉新上线的 CPU 造成 UAF。
2. **`rcu_gp_fqs_loop()`**（`tree.c:2092`）：反复等待 `jiffies_till_first_fqs`（默认毫秒级）后调用 `rcu_gp_fqs()` **主动强制**各 CPU 上报静止态（force quiescent state）。每一轮检查根 `rnp->qsmask` 是否为 0 且 `rcu_preempt_blocked_readers_cgp` 为空——两者都满足就跳出循环，宽限期结束。
3. **`rcu_gp_cleanup()`**（`tree.c:2178`）：把本轮完成的回调推进到"就绪"队列，唤醒 `rcu_do_batch` 去执行，并启动下一轮（如果还有排队的回调）。

也就是说，**宽限期不是靠"计时器到点"结束的，而是靠"所有 rcu_node 的 qsmask 都被清零"结束的**——延迟取决于最后一个拖沓的 CPU。

## Quiescent State Reporting: From CPU to the rcu_node Tree

`rcu_node` 是一棵 radix 树：叶子节点管一组 CPU（`grpmask` 标识各自的 bit），根节点汇总。每个 CPU 有自己的一份 `rcu_data`（简称 rdp），记录"我有没有为当前宽限期上报过静止态"。

当某 CPU 发生上下文切换 / 返回用户态 / 进入 idle 时，调度路径会调用 `rcu_report_qs_rdp()`（`tree.c:2471`）：

```c
static void rcu_report_qs_rdp(struct rcu_data *rdp) {
    ...
    if (rdp->cpu_no_qs.b.norm || rdp->gp_seq != rnp->gp_seq || rdp->gpwrap) {
        /* 这个静止态属于已结束的宽限期，忽略，等下一个 */
        rdp->cpu_no_qs.b.norm = true;
        return;
    }
    mask = rdp->grpmask;
    ...
    rcu_report_qs_rnp(mask, rnp, rnp->gp_seq, flags);  /* 把 clear 位向上传 */
}
```

`rcu_report_qs_rnp()` 把该 CPU 在所属 `rcu_node` 上的 `qsmask` bit 清掉，并在父节点上做同样的事，直到根节点——**根节点 `qsmask` 全清，就是"所有 CPU 都静止过"的判据**，对应上面 `rcu_gp_fqs_loop` 的跳出条件。`rcu_check_quiescent_state()`（`tree.c:2526`）则是每个 CPU 在每个 tick / 调度点检查"当前宽限期我是否还需要上报"。

> dyntick-idle（CONFIG_NO_HZ）的 CPU 可能长时间不调度，内核通过 EQS（extended quiescent state）记账：进入 idle 时主动把自己标成"已静止"，无需等它醒来。

## Callback Queue: Segmented Linked List and Batching

`call_rcu` 注册的回调并不立刻进就绪队列，而是挂在 per-CPU 的 `rcu_data.cblist` 上，用**四段式分段链表（segmented callback list）**管理（`include/linux/rcu_segcblist.h`）：

| 段 | 宏 | 含义 |
| :-- | :-- | :-- |
| 0 | `RCU_DONE_TAIL` | 宽限期已结束，**可以立即调用** |
| 1 | `RCU_WAIT_TAIL` | 等当前这个宽限期结束 |
| 2 | `RCU_NEXT_READY_TAIL` | 等下一个宽限期 |
| 3 | `RCU_NEXT_TAIL` | 刚入队，还没分给任何宽限期 |

宽限期推进时，`rcu_do_batch()`（`tree.c:2568`）把 `RCU_DONE_TAIL` 里的回调**整段抽出**到一个临时链表再逐个执行。两个节流点值得记：

- **数量上限 `bl`**：`bl = max(rdp->blimit, pending >> rcu_divisor)`，避免一次耗尽 CPU；
- **时间上限 `tlimit`**：在软中断里跑时，每 32 个回调用 `local_clock()` 检查是否超过 `rcu_resched_ns`（默认毫秒级），超时即 `break` 让出，下次软中断继续——**保证 RCU 回调不会饿死其他软中断向量**。

`CONFIG_RCU_NOCB_CPU` 开启时，回调的执行从软中断搬到了专门的 `rcuoc` 内核线程（`tree_plugin.h`），进一步隔离抖动，常用于实时/低延迟场景。

## kvfree_rcu / kfree_rcu: Bulk Reclamation

`kfree_rcu` / `kvfree_rcu`（两参数形式 `kvfree_rcu(p, rcu)`，把 `rcu` 成员偏移编码进头）在 **v7.2.7 已从 `kernel/rcu/tree.c` 搬到 `mm/slab_common.c`**（`kvfree_call_rcu`）。两种编译形态：

- **未开 `CONFIG_KVFREE_RCU_BATCHED`**：单参数形式 `kvfree_rcu(p)` 直接 `synchronize_rcu(); kvfree(p)`——**会睡眠**；双参数形式走 `call_rcu(head, kvfree_rcu_cb)` 不睡眠。
- **开启 `CONFIG_KVFREE_RCU_BATCHED`（默认）**：每个 CPU 有一个 `struct kfree_rcu_cpu`，把待释放指针攒进 per-CPU 的 **bulk list**（每块约一页大小，由 `KVFREE_BULK_MAX_ENTR` 决定单块条数），后台 `monitor_work` 在 `KFREE_DRAIN_JIFFIES = 5*HZ` 后统一刷出，一次宽限期回收一大批。**批量回收能显著降低高 kfree_rcu 负载下的宽限期数量**。

> 工程提醒：依赖"kfree_rcu 绝不睡眠"的老印象已经不稳——单参数 kvfree_rcu 在未开批处理的内核里会 `synchronize_rcu()` 睡眠。可睡眠上下文且不想引入 RCU 头时，单参数形式才是合适的；原子上下文务必用双参数 `kfree_rcu(p, member)`。

## RCU_LAZY: Deferring Grace Period Startup to Save Power

`CONFIG_RCU_LAZY` 下，**`call_rcu()` 默认是"lazy"的**：回调先被藏起来、不立刻触发宽限期，攒一批再统一启动（`enable_rcu_lazy` 模块参数控制，除非 `CONFIG_RCU_LAZY_DEFAULT_OFF`）。这对低负载/电池设备能显著省电，但代价是释放延迟从毫秒级变成可能数秒。

延迟敏感的代码应改用 `call_rcu_hurry()`（`tree.c:3211`），它把 `lazy` 标志设成 false，行为与旧版 `call_rcu` 一致、立刻启动宽限期。

## Expedited Grace Period (Expedited GP)

普通宽限期要等自然静止态，延迟不可控。`synchronize_rcu_expedited()` 走另一条路：通过 **IPI 强制**每个 CPU 立刻上报静止态，而不是干等。源码在 `kernel/rcu/tree_exp.h`：

```c
/* IPI the remaining CPUs for expedited quiescent state. */
ret = smp_call_function_single(cpu, rcu_exp_handler, NULL, 0);
/* The CPU will report the QS in response to the IPI. */
```

`rcu_exp_handler` 在目标 CPU 上直接做静止态上报，几乎瞬间结束宽限期。代价是**给所有 CPU 发 IPI 的侵入性开销**，所以内核里有 `rcu_expedited` 系列 sysctl 与 `synchronize_rcu_expedited` 的速率限制（防止互相踩踏）。`synchronize_net()`（修改路由/filter 时常用）内部就优先走 expedited。

## SRCU: Sleepable Reader-Side

普通 RCU 读侧不能睡眠，因为睡眠会把宽限期无限拖长。**SRCU（Sleepable RCU）** 通过三个设计解除这个限制：

1. **多个独立的域**：每个 `srcu_struct` 有自己的宽限期追踪，互不干扰（不像全局唯一的 `rcu_state.gp_seq`）；
2. **两段 per-CPU 计数**：读侧不靠"上下文静止"判断，而是显式计数。读侧 `srcu_read_lock()` 在 `idx`（0 或 1）对应的 per-CPU `srcu_locks` 上 `+1`，`smp_mb()`（注释标 B）后返回 `idx`；解锁时 `smp_mb()`（C）后在 `srcu_unlocks[idx]` 上 `+1`；
3. **flip 机制**：写侧 `synchronize_srcu()` 先扫 `idx` 段确认没有遗留读者（`srcu_readers_active_idx_check`，配合 `smp_mb()` A），再 `srcu_flip()` 翻转活动索引、扫另一端（`SRCU_STATE_SCAN1` → `SRCU_STATE_SCAN2`）。

读侧加解锁的完整配对（来自 `srcutree.c:790`）：

```c
int __srcu_read_lock(struct srcu_struct *ssp) {
    struct srcu_ctr __percpu *scp = READ_ONCE(ssp->srcu_ctrp);
    this_cpu_inc(scp->srcu_locks.counter);
    smp_mb(); /* B */
    return __srcu_ptr_to_ctr(ssp, scp);
}
void __srcu_read_unlock(struct srcu_struct *ssp, int idx) {
    smp_mb(); /* C */
    this_cpu_inc(__srcu_ctr_to_ptr(ssp, idx)->srcu_unlocks.counter);
}
```

因为读者是"数人头"而不是"等静止态"，**临界区内睡眠完全合法**——只要 `lock/unlock` 配对、且同一个 `srcu_struct` 域即可。这就是文件系统路径查找（可能 page fault 睡眠）使用 SRCU 的原因。还有 NMI-safe 变体 `__srcu_read_lock_nmisafe()`，用原子 RMW 而非 `this_cpu_inc`。

## RCU Tasks Family

普通 RCU 等待"CPU 静止"，但有些场景要等的是**"所有任务都发生了某种上下文切换"**——典型是更新 trampoline / ftrace / BPF 附着点。`kernel/rcu/tasks.h` 用 `DEFINE_RCU_TASKS` 宏定义了三种（都叫 synchronize_rcu_tasks_*）：

- **`rcu_tasks`**：等每个任务**自愿上下文切换**一次（或退出）。最常用于 trampoline 更新。`synchronize_rcu_tasks()`。
- **`rcu_tasks_rude`**：不等自愿切换，而是 `schedule_on_each_cpu()` **强制每个 CPU 切一次上下文**，用于那些根本不会自愿切换的紧循环。
- **`rcu_tasks_trace`**：tracing 变体，与 `rcu_tasks` 配合处理可抢占/可睡眠的追踪场景。

它们的宽限期判据不是"静止态"而是"任务状态翻转"，因此延迟模型与普通 RCU 完全不同，且开销更大，只在确实需要时用。

## Division of Labor with seqlock

两者的读侧都接近零开销，但：

- **seqlock**：读者可能读到不一致数据并重试；读侧**不能安全解引用可能被释放的内存**，适合小而简单的值；
- **RCU**：读者永远看到一致的版本（旧版本也是有效数据），可以安全遍历指针结构，代价是写侧要等宽限期。

需要"读时顺手拿到引用并带出临界区"时，配合 `kref_get_unless_zero()` 之类的引用计数；需要"读侧能睡眠"时用 SRCU。

## Usage Rules Summary

1. 读侧短小、不睡眠（除非 SRCU）；
2. 写侧串行化（`mutex`/`spinlock`）——RCU 不是互斥锁的替代品；
3. 替换指针必须用 `rcu_assign_pointer`，读取必须用 `rcu_dereference`；
4. 旧对象的释放在宽限期之后（`synchronize_rcu` / `call_rcu` / `kfree_rcu` / `kvfree_rcu`）；
5. 高 kfree_rcu 负载、原子上下文 → 用双参数 `kfree_rcu(p, member)`；低延迟/电池设备留意 `CONFIG_RCU_LAZY` 会让 `call_rcu` 变懒；
6. 需要"读时顺手拿到引用并带出临界区"时，配合引用计数。

## Links

- [Lock](/docs/CS/OS/Linux/Lock/README.md)
- [原子操作与内存屏障](/docs/CS/OS/Linux/Lock/atomic.md)
- [rwlock / rwsem / seqlock](/docs/CS/OS/Linux/Lock/rwsem.md)
- [spinlock](/docs/CS/OS/Linux/Lock/spinlock.md)
- [mutex](/docs/CS/OS/Linux/Lock/mutex.md)

## References

- [What is RCU? Part 1: Concepts (LWN)](https://lwn.net/Articles/262464/)
- [RCU part 2: Usage (LWN)](https://lwn.net/Articles/263130/)
- [What is RCU? (kernel.org, 含 SRCU/RU Tasks 等变体)](https://docs.kernel.org/RCU/whatisRCU.html)
- [TREE_RCU Expedited Grace Periods (设计文档)](https://docs.kernel.org/RCU/Design/Expedited-Grace-Periods/Expedited-Grace-Periods.html)
- [The RCU Documentation (kernel.org)](https://docs.kernel.org/RCU/)
- [Linux Kernel Source: kernel/rcu/tree.c](https://elixir.bootlin.com/linux/v7.2.7/source/kernel/rcu/tree.c)
- [Linux Kernel Source: kernel/rcu/srcutree.c](https://elixir.bootlin.com/linux/v7.2.7/source/kernel/rcu/srcutree.c)
