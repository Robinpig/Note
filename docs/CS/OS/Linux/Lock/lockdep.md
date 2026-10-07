## Introduction

`lockdep` 是内核里**运行时**的死锁检测器，不是静态分析。它不靠人去读代码，而是在每次加锁/解锁时，动态维护一张**锁之间的依赖关系图**，并在图上做可达性检查，提前几年（也许是几百万次执行里）把潜在死锁报成一条 "splat"。它只存在于 `CONFIG_PROVE_LOCKING` 开启的调试内核里，对运行时有可观开销（每个锁类、每次加锁都要查图），所以生产内核默认关掉。

与之相对的 `CONFIG_DEBUG_LOCKDEP` 是在 lockdep 之上的二次检查（验证 lockdep 自身数据结构的一致性），更慢，只在复现疑难问题时开。

本篇讲清 lockdep 的**三个核心抽象**（锁类、依赖图、每任务持锁栈）和它报的**四类经典问题**，最后给一份"怎么读一个 splat"的速查。

## Lock Classes and Lock Instances: Why Not by Address

lockdep 跟踪的单位是**锁类（lock class）**，不是某个具体的 `spinlock_t` 实例。一个 `struct lock_class` 由编译期嵌入的 `struct lockdep_map`（每个锁都有这个 `.dep_map` 字段）和它背后的 `struct lock_class_key` 标识。好处是：同一个 `kmalloc` 出来的 1000 把 spinlock，只要来源是同一段代码（`lockdep_map` 的 key 相同），它们**共享一个锁类**——否则内存耗爆、图也乱。

但同一个代码位置有时需要区分"这是外层锁还是内层锁"，于是有了 **subclass**（0~7，`MAX_LOCKDEP_SUBCLASSES = 8`）。比如文件系统对目录项加锁时，父目录和子目录都来自同一处代码，必须用 `lockdep_set_subclass()` 或带 subclass 的加锁宏把它们标记为不同的类，否则 lockdep 会把合法的层级加锁误判成递归死锁。`rwsem` 的 `down_read_nested` / `mutex_lock_nest_lock` 就是为此而生。

## Dependency Graph and Per-Task Held-Lock Stack

lockdep 维护两个东西：

1. **全局依赖图**：边 `A → B` 表示"在持有 A 的情况下曾获取过 B"。每次加锁 B 且当前已持有 A 时，`validate_chain()`（`kernel/locking/lockdep.c:3889`）就会检查图上是否**已经存在一条从 B 回到 A 的路径**——有则形成环（死锁）。
2. **每任务的持锁栈**：`current->held_locks[]` 记录当前任务此刻持有的所有锁及其上下文（hardirq 开/关、softirq 开/关、是否读锁）。加锁时把新锁压栈，解锁时出栈。

`__lock_acquire()`（`lockdep.c:5108`）是每次加锁的入口，它做：查/建锁类 → 检查与现有依赖边的环 → 更新锁类的**使用状态位**（见下）→ 维护 `held_locks`。图上的环检测用 BFS（`__bfs_forwards`，`print_circular_bug` 在 `lockdep.c:2033` 打印结果）。

关键点：**图是跨任务累积的全局知识**。一个 CPU 上先持有 A 再拿 B，另一个路径上若曾持有 B 再拿 A，哪怕两者从未在同一时刻同时发生，lockdep 也会报死锁——因为理论上那两个持锁窗口重叠就会锁死。这正是它能"提前"发现死锁的原因，也是它偶尔误报（需要 subclass 或 annotation 消解）的原因。

## Four Classic Problem Types

| 报错关键字 | 含义 | 机制 |
| :-- | :-- | :-- |
| `possible circular locking dependency detected` | 形成了锁依赖环（A→B 且 B→A） | 图上检测到已有 B→...→A 的路径 |
| `inconsistent lock state` / `possible irq lock inversion` | 同一把锁的**中断上下文使用不一致**：曾经在中断关时拿过，如今在中断开时拿（或反之），理论上可被中断路径反拿造成死锁 | 锁类的使用状态位（hardirq-safe / hardirq-unsafe / softirq-safe / softirq-unsafe）冲突 |
| `possible recursive locking` / `incorrect nesting` | 同一锁类未用 subclass 就重入，或嵌套层级不兼容 | subclass 检查失败 |
| `held lock freed!` / `suspicious RCU usage` | 持锁中释放了这把锁，或在 RCU 读侧临界区里做了禁止的事 | `lockdep_rcu_suspicious()`（`lockdep.c:6867`）等专门检查 |

**中断反转（irq inversion）** 值得单独讲：一把锁若曾在 hardirq 上下文（关中断）下获取，lockdep 就给它打上 `hardirq-safe` 标记；若之后有人在**开中断**的普通上下文去拿同一把锁，而该锁在中断里可能被反方向获取，就构成"中断能在你持锁时抢占你并要同一把锁"的死锁窗口。这种问题普通压力测试很难触发，但 lockdep 一次就能抓到。

> 历史注记：老内核里还有 `RECLAIM_FS` 状态位（fs-reclaim 上下文），在约 5.x 的 reclaim lockdep 重构中已被移除；v7.2.7 的状态位只剩 **hardirq / softirq 两对 safe-unsafe**。帖子里的老 splat 若提 RECLAIM_FS，那是对旧版本的描述。

## How to Read a splat

一个典型的 circular 报告自上而下是：

1. **`WARNING: possible circular locking dependency detected`** + 触发时的 CPU / 进程；
2. **`Possible unsafe locking scenario` / `Circular dependency` 图**：画出 A→B→...→A 的环，这是最该看的部分；
3. **`the existing dependency led to this`**：已存在的边是怎么来的（哪两个调用栈曾分别持有 A 拿 B、持有 B 拿 A）；
4. **`other info that might help us debug this`**：当前任务的 `held_locks` 栈（标了每个锁的上下文位），以及是否 `hardirq-safe`/`softirq-safe`；
5. **`stack backtrace`**：触发这次加锁的调用栈。

排查顺序：**先看环本身（哪两把锁、谁嵌套谁）→ 再看两个历史调用栈确认哪条路径是"真会同时持锁" → 若是合法的层级嵌套，用 subclass/annotation 消解；若真是 bug，改加锁顺序**。

## Configuration, Overhead, and False-Positive Resolution

- **开启**：`CONFIG_PROVE_LOCKING`（默认选中会连带开 lockdep）。只调试内核用。
- **关闭/屏蔽**：运行时 `echo 0 > /proc/sys/kernel/prove_locking` 可整体关掉检测；单把锁可用 `__lockdep_no_validate__` 或 `lockdep_set_novalidate_class()` 跳过；整个子系统对 RT 内核会用 `raw_spinlock_t` 替代 `spinlock_t` 以绕过。
- **误报消解手段**：
  - `lockdep_set_class()` / `lockdep_set_subclass()`：给同代码来源的锁区分身份；
  - `mutex_lock_nest_lock()` / `down_read_nested()`：合法的嵌套；
  - `lockdep_off()` / `lockdep_on()`（谨慎）：临时关闭某段；
  - `might_sleep()` / `lockdep_assert_held()`：反向给 lockdep 提供"我此刻应持锁/可能睡眠"的断言，帮助它抓更隐蔽的违规。

> 经验：lockdep 报的"假死锁"绝大多数其实不是假，而是**加锁顺序在两条路径上不一致**。先假设它是对的，再去证明它是注解问题，通常省时间。

## Links

- [Lock](/docs/CS/OS/Linux/Lock/README.md)
- [spinlock](/docs/CS/OS/Linux/Lock/spinlock.md)
- [mutex](/docs/CS/OS/Linux/Lock/mutex.md)
- [rwlock / rwsem / seqlock](/docs/CS/OS/Linux/Lock/rwsem.md)
- [RCU](/docs/CS/OS/Linux/Lock/RCU.md)
- [原子操作与内存屏障](/docs/CS/OS/Linux/Lock/atomic.md)

## References

- [lockdep splat explainer (kernel.org)](https://docs.kernel.org/RCU/lockdep-splat.html)
- [The kernel lockdep implementation (LWN)](https://lwn.net/Articles/185666/)
- [Lockdep and the subtleties of kernel locking (LWN)](https://lwn.net/Articles/826978/)
- [Linux Kernel Source: kernel/locking/lockdep.c](https://elixir.bootlin.com/linux/v7.2.7/source/kernel/locking/lockdep.c)
