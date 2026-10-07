## Introduction

内核是多任务并发执行的：中断、软中断、系统调用、多 CPU 上的进程都可能同时访问同一份数据。**同步机制解决的是"共享数据的互斥访问"与"事件之间的先后顺序"两个问题**（理论视角见 [Synchronization](/docs/CS/OS/process.md)）。

锁的实现大多位于 `kernel/locking` 目录下。内核中的资源锁包括基于硬件总线的原子操作（spinlock、mutex、rwlock、seqlock、RCU 锁、信号量）以及对文件内容进行保护的文件锁。

内核同步比用户态同步多出几层约束：

- **上下文种类多**：进程上下文、中断上下文、软中断、原子上下文（已持自旋锁或关抢占）——中断上下文不能睡眠，因此不能使用会睡眠的锁；
- **SMP 内存序**：多核之间需要显式的内存屏障保证可见性与顺序（x86 强序、ARM 弱序）；
- **中断会打断持锁者**：同一把锁若同时被中断处理程序获取，就必须在获取时关中断。

本页是 `Lock/` 目录的索引：先看下面的分类与[对比表](#对比表)判断该用哪类原语，再进对应的笔记看实现。

## Categories

| 层次 | 原语 | 说明 |
| :-- | :-- | :-- |
| 基石 | [原子操作与内存屏障](/docs/CS/OS/Linux/Lock/atomic.md) | `atomic_t`、`cmpxchg`、`smp_store_release` 等，是所有锁的实现基础 |
| 忙等（不可睡眠） | [spinlock](/docs/CS/OS/Linux/Lock/spinlock.md) | 空转等待，适合极短临界区 |
| 忙等 | [rwlock / seqlock](/docs/CS/OS/Linux/Lock/rwsem.md) | 读多写少的忙等方案 |
| 睡眠锁 | [mutex](/docs/CS/OS/Linux/Lock/mutex.md) | 严格语义的互斥锁，只能用于进程上下文 |
| 睡眠锁 | [rwsem](/docs/CS/OS/Linux/Lock/rwsem.md) | 可睡眠的读写锁，写者不饥饿 |
| 睡眠锁 | [semaphore / completion](/docs/CS/OS/Linux/Lock/semaphore.md) | 计数信号量与一次性事件等待 |
| 免锁 | [RCU](/docs/CS/OS/Linux/Lock/RCU.md) | 读侧零开销，写侧延迟回收 |
| 免同步（数据隔离） | [per-CPU 变量](/docs/CS/OS/Linux/Lock/percpu.md) | 按 CPU 切分数据，写侧零竞争，读侧聚合 |
| 用户态 ↔ 内核 | [futex](/docs/CS/OS/Linux/Lock/futex.md) | 用户态原子操作 + 竞争时才进内核 |
| 进程间 | [跨进程同步](/docs/CS/OS/Linux/Lock/ipc-sync.md) | POSIX/SysV 信号量、文件锁、process-shared mutex |
| 小原语 | [小原语合集](/docs/CS/OS/Linux/Lock/SmallPrimitives.md) | qrwlock / bit_spin_lock / local_lock / lockref / percpu_rwsem |
| 调试 | [lockdep](/docs/CS/OS/Linux/Lock/lockdep.md) | 运行时死锁检测：锁依赖图 + 每任务持锁栈 |

## Origin of the Reader-Writer Lock Family

rwlock 在本质上是 spinlock 的一种，它在 spinlock 概念上增加了一个类似信号量的读计数器：读操作首先获得 spinlock，然后增加引用计数，最后释放 spinlock；写操作需要满足引用计数为 0 且获取到 spinlock，写操作获得 rwlock 后不会释放 spinlock，以此做到独占——但是 rwlock 容易造成写饥饿。

在允许睡眠的情况下可以使用 rwsem，在不允许睡眠的高响应要求下可以使用 seqlock。三者的权衡见 [rwlock / rwsem / seqlock](/docs/CS/OS/Linux/Lock/rwsem.md)。

## Comparison Table

| 原语 | 能否睡眠 | 可用上下文 | 典型场景 |
| :-- | :-- | :-- | :-- |
| atomic / 屏障 | 否 | 任意 | 计数器、标志位、无锁插入 |
| spinlock | 否（忙等） | 任意（含中断） | 极短临界区，如队列操作 |
| rwlock | 否（忙等） | 任意 | 读多写少但临界区极短 |
| seqlock | 读侧否 | 任意 | 读多写极少（如时间戳） |
| mutex | 是 | 仅进程上下文 | 临界区可能阻塞（如分配内存） |
| rt_mutex | 是 | 进程上下文 | 需要优先级继承防优先级反转 |
| rwsem | 是 | 仅进程上下文 | 读多写少且临界区可能阻塞（如 mmap_lock） |
| semaphore | 是 | 获取仅进程上下文，`up()` 可在中断 | 生产者-消费者、中断唤醒 |
| completion | 是 | 同上 | 一次性事件：等待初始化完成 |
| RCU | 读侧否 | 读侧任意 | 链表/路由表/缓存等读多写少结构 |

## Selection Guide

1. **临界区会不会睡眠？** 会 → 睡眠锁（mutex/rwsem/semaphore）；绝不会 → spinlock。
2. **同一把锁会被中断/软中断获取吗？** 会 → 必须用 `spin_lock_irqsave()` / `spin_lock_bh()`（见 [spinlock 的 API 矩阵](/docs/CS/OS/Linux/Lock/spinlock.md?id=interrupts-and-api-selection)）。
3. **读写比例悬殊吗？** 读多写少 → 可睡眠选 rwsem，不可睡眠选 rwlock/seqlock；读极多写极少且能接受延迟回收 → RCU。
4. **只是计数或单标志？** → 直接用原子操作；如果是**高频累加**，先考虑 [per-CPU 化](/docs/CS/OS/Linux/Lock/percpu.md)再考虑锁。
5. **跨进程共享数据？** → 见[跨进程同步](/docs/CS/OS/Linux/Lock/ipc-sync.md)（崩溃安全是首要考虑）；用户态线程间且无竞争是常态 → [futex](/docs/CS/OS/Linux/Lock/futex.md)。

## Deadlocks and Debugging

- 死锁的四个必要条件与避免策略见 [Deadlocks](/docs/CS/OS/Deadlocks.md)；内核中最常见的是**忘记关中断**与**锁顺序不一致**。
- **[lockdep](/docs/CS/OS/Linux/Lock/lockdep.md)**（`CONFIG_PROVE_LOCKING`）在运行时构建锁依赖图，报告"可能的循环锁序"；`CONFIG_DEBUG_SPINLOCK`、`CONFIG_DEBUG_MUTEXES` 校验各原语自身的使用规则。
- 通用规则：不可递归获取、自旋锁持有期间不睡眠、不在持锁时调用可能反向加锁的函数。

## User-Space Perspective

用户态同步（pthread mutex/cond、Java `synchronized`/AQS、Go `sync.Mutex`）的无竞争快速路径是纯用户态原子操作，竞争时才通过 [futex](/docs/CS/OS/Linux/Lock/futex.md) 进入内核等待队列——与内核 mutex 的"乐观自旋 + 等待队列"是同一思路在两个层次上的体现。详见 [pthread](/docs/CS/OS/Linux/proc/pthread.md) 与 [语言运行时与内核任务](/docs/CS/OS/Linux/proc/runtime.md)。

## Links

- [Linux](/docs/CS/OS/Linux/Linux.md)
- [原子操作与内存屏障](/docs/CS/OS/Linux/Lock/atomic.md)
- [spinlock](/docs/CS/OS/Linux/Lock/spinlock.md)
- [mutex](/docs/CS/OS/Linux/Lock/mutex.md)
- [rwlock / rwsem / seqlock](/docs/CS/OS/Linux/Lock/rwsem.md)
- [semaphore / completion](/docs/CS/OS/Linux/Lock/semaphore.md)
- [RCU](/docs/CS/OS/Linux/Lock/RCU.md)
- [futex](/docs/CS/OS/Linux/Lock/futex.md)
- [per-CPU 变量](/docs/CS/OS/Linux/Lock/percpu.md)
- [跨进程同步](/docs/CS/OS/Linux/Lock/ipc-sync.md)
- [lockdep](/docs/CS/OS/Linux/Lock/lockdep.md)
- [小原语合集](/docs/CS/OS/Linux/Lock/SmallPrimitives.md)
- [Deadlocks](/docs/CS/OS/Deadlocks.md)
