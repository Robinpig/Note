## Introduction

`Lock/` 目录里那些"大块头"（spinlock / mutex / rwsem / RCU）之外，还有一批**为特定场景量身定做的小原语**：它们要么是为了省内存（把锁塞进一个字的某个 bit）、要么是为了把"关本地中断"这种隐式临界区变成 lockdep 可追踪的对象、要么是为某种极端的读写比做特殊优化。本篇逐个过一遍，重点讲清"它解决了什么、代价是什么、在哪用"。

> seqlock 的源码级细节见 [rwlock / rwsem / seqlock](/docs/CS/OS/Linux/Lock/rwsem.md)；lockdep 死锁检测见 [lockdep](/docs/CS/OS/Linux/Lock/lockdep.md)。

## qrwlock: Fair Queued Reader-Writer Lock

`rwlock_t` 在现代 x86/arm64 上早已不是经典的自旋读写锁，而是 **qrwlock（queued rwlock）**（`kernel/locking/qrwlock.c` + `include/asm-generic/qrwlock.h`）。它用一个原子字记录状态：低字节的读者计数 + `_QW_WAITING`（有写者在等）+ `_QW_LOCKED`（写者持有）。

关键不变量（也是纠正"rwlock 必然写饥饿"老说法的地方）：**写者一旦设上 `_QW_WAITING`，新读者就进不了快路径**，必须到 `wait_lock` 上排队；而读者慢路径同样要在 `wait_lock` 上排队（`queued_read_lock_slowpath`）。所以 qrwlock 是**公平**的——读者不能无限挡住写者，写者也不能无限挡住读者。

适用：需要"多个读者或一个写者"语义、且临界区很短、不能睡眠的场景（中断上下文、底半部）。代价是比 spinlock 复杂、写者要等所有当前读者退出。

## bit_spin_lock: Using a Single Bit as a Lock

`bit_spin_lock(bitnum, addr)`（`include/linux/bit_spinlock.h`）把某个字的某一位当成一把自旋锁：先 `preempt_disable()`，再 `test_and_set_bit_lock()` 抢位，抢不到就 `cpu_relax()` 忙等。它**不持有一把独立的 `spinlock_t`**，所以省内存——代价是没有 ticket/MCS 排队、且无法在持锁时睡眠。

适用：对象多到塞一把完整 spinlock 太浪费的地方，典型是 buffer head、某些文件系统的块位图。注释自己也提醒："Don't use this unless you really need to: spin_lock() ... are significantly faster." lockdep 通过 `__bitlock(bitnum, addr)` 这个合成 token 给每个 (bit, addr) 一个独立锁类，所以 bit 锁也能被死锁检测覆盖。

## local_lock: Turning "Disable Local Interrupts" into a Trackable Lock

`local_lock()` / `local_lock_irq()` / `local_lock_irqsave()`（`include/linux/local_lock.h`）在**非 RT 内核**上基本就是 `preempt_disable()`（或叠加 `local_irq_disable()`），即"标记一段当前 CPU 上的本地临界区"——等价于过去手写 `local_irq_save()`。它的价值在于：

1. **让 lockdep 能追踪**：过去 `local_irq_disable()` 是隐式的、lockdep 看不见；现在用 `local_lock` 包裹后，它有一个 `lockdep_map`，可以参与依赖图；
2. **在 `PREEMPT_RT` 下变成真锁**：RT 内核不允许关中断里持锁，于是 `local_lock_t` 在 RT 配置下被实现为 **per-CPU 的 `spinlock_t`**，既保留了"同一 CPU 上互斥"的语义，又不破坏 RT 的抢占性。

适用：原本需要 `local_irq_disable()` + `preempt_disable()` 保护的 per-CPU 数据，改成 `local_lock` 既清晰又能被验证。还有 `local_lock_nested_bh()` 变体，对应软中断上下文的本地临界区。

## lockref: Fusing "Spinlock + Reference Count"

`struct lockref`（`include/linux/lockref.h`）把 `spinlock_t` 和 `int count` 打包（甚至在支持 `CONFIG_ARCH_USE_CMPXCHG_LOCKREF` 且 spinlock ≤ 4 字节时，两者合成一个 64 位的 `lock_count` 用 `cmpxchg` 一次改）。语义是"**引用计数与它的保护锁原子地一起改**"：常见的 get/put 走 `cmpxchg` 快路径，**不需要真正拿自旋锁**；只有竞争或需要检查 "dead" 状态时才落锁。

适用：引用计数极高、且计数与锁紧密耦合的热点路径，内核里最典型的是 **dcache / 路径查找（namei）**。它把"拿锁→改计数→放锁"的两步合并成一次原子操作，热点上省下不少。

## percpu_rwsem: Readers Use per-CPU Counters, Writer Touches the Global Lock

`percpu_rw_semaphore`（`kernel/locking/percpu-rwsem.c`）是 `rw_semaphore` 的一个变体，专门优化"**读极多、写极少**"的情形。读者快路径 `__percpu_down_read_trylock()` 只是对**本 CPU 的一个 per-CPU 计数器做一次 `__this_cpu_inc`**——完全无全局锁、可睡眠但几乎零开销。写者 `percpu_down_write()` 则要先拿内嵌的 `rwsem`（全局互斥），再"冻结"所有 CPU 的读者，把后续读者逼到慢路径排队。

适用：读侧频率极高、但又必须能偶尔做排他写的地方，例如 CPU 热插拔、`freeze_super`（文件系统冻结）、cgroup 某些路径。注意它的写者开销比普通 rwsem 还大（要等所有 per-CPU 读者退出），所以是"用写者代价换读者代价"的取舍，不是 rwsem 的纯升级版。

## Quick Selection Reference

| 原语 | 解决什么 | 能睡眠 | 主要代价 |
| :-- | :-- | :-- | :-- |
| qrwlock (`rwlock_t`) | 短临界区多读/单写，中断上下文可用 | 否 | 比 spinlock 复杂，写者等读者 |
| bit_spin_lock | 省内存的位级自旋锁 | 否 | 无排队、不能睡眠 |
| local_lock | 把"关中断/抢占"变成可追踪的本地临界区 | 否 | RT 下变 per-CPU spinlock |
| lockref | 计数与锁焊死的引用计数热点 | 否 | 语义绑定锁+计数 |
| percpu_rwsem | 读极多写极少的读写信号量 | 读者可睡眠 | 写者代价大 |
| seqlock | 读多写少且读者容忍重试 | 读者否/写者否 | 写者独占，读者可能重试 |

## Links

- [Lock](/docs/CS/OS/Linux/Lock/README.md)
- [spinlock](/docs/CS/OS/Linux/Lock/spinlock.md)
- [rwlock / rwsem / seqlock](/docs/CS/OS/Linux/Lock/rwsem.md)
- [mutex](/docs/CS/OS/Linux/Lock/mutex.md)
- [RCU](/docs/CS/OS/Linux/Lock/RCU.md)
- [lockdep](/docs/CS/OS/Linux/Lock/lockdep.md)

## References

- [Queued spinlocks (LWN)](https://lwn.net/Articles/590243/)
- [The realtime patches and lockdep (LWN, 论 local_lock/RT 化)](https://lwn.net/Articles/829332/)
- [Linux Kernel Source: kernel/locking/qrwlock.c](https://elixir.bootlin.com/linux/v7.2.7/source/kernel/locking/qrwlock.c)
- [Linux Kernel Source: include/linux/local_lock.h](https://elixir.bootlin.com/linux/v7.2.7/source/include/linux/local_lock.h)
- [Linux Kernel Source: kernel/locking/percpu-rwsem.c](https://elixir.bootlin.com/linux/v7.2.7/source/kernel/locking/percpu-rwsem.c)
