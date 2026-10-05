## Introduction

futex（Fast Userspace muTEX，`futex(2)`）是**用户态同步与内核同步的接口**：它让"无竞争时纯用户态原子操作、有竞争时才进入内核睡眠"成为可能。所有上层同步原语——pthread mutex/cond、Java 的 `Parker`/AQS、Go 的 `sync.Mutex` 慢路径——最终都走它。

如果没有 futex，用户态互斥只能用系统调用（每次加锁都陷入内核，开销巨大）或纯自旋（浪费 CPU）；futex 把两者结合起来，是 Linux 上高并发用户态同步的性能基础。内核侧的基石是 [原子操作](/docs/CS/OS/Linux/Lock/atomic.md)与[等待队列](/docs/CS/OS/Linux/proc/thundering_herd.md?id=wait)。

## 工作原理

futex 是一块**用户态分配、由内核协助**的 32 位内存：

- **快速路径**：`cmpxchg` 之类的原子指令在用户态完成加锁/解锁，**不产生任何系统调用**；
- **慢路径**：只有当发现锁已被占用（需要睡眠），才调用 `futex(FUTEX_WAIT, uaddr, expected)` 进入内核——内核先重新检查 `*uaddr == expected`（避免"刚调用就被释放"的竞态），一致才把任务挂到等待队列；解锁方用 `FUTEX_WAKE` 唤醒。

```c
/* 内核侧接口（简化） */
futex_wait(uaddr, val);      /* 若 *uaddr == val 则睡眠，否则返回 EAGAIN */
futex_wake(uaddr, nr);       /* 唤醒最多 nr 个等待者 */
```

关键点：**futex 的地址不是"系统调用对象"**，内核用 `(mm, 虚拟地址)` 作为键在哈希表中找到对应的等待队列（跨进程共享内存场景用文件/inode + 偏移）。因此：

- futex 只在调用期间有意义，不会被"注册"；
- 匿名内存必须用 `FUTEX_PRIVATE_FLAG`（标记为进程私有），内核可以走共享 futex 哈希的私有分支，避免全局哈希桶竞争；
- 内存被 `munmap` 后再 futex 操作会 `EFAULT`。

## 相关操作

| 操作 | 用途 |
| :-- | :-- |
| `FUTEX_WAIT` | 条件成立则睡眠 |
| `FUTEX_WAKE` | 唤醒 N 个等待者 |
| `FUTEX_REQUEUE` / `FUTEX_CMP_REQUEUE` | 把等待者**搬到另一个 futex** 上——条件变量避免惊群的关键 |
| `FUTEX_WAIT_BITSET` / `WAKE_BITSET` | 位掩码，只唤醒关心的等待者 |
| `FUTEX_LOCK_PI` / `UNLOCK_PI` / `TRYLOCK_PI` | 优先级继承 futex，缓解优先级反转 |
| `FUTEX_WAIT_REQUEUE_PI` | 与 PI 配合的等待 |

**requeue 与惊群**：`pthread_cond_broadcast` 若单纯 `FUTEX_WAKE` 唤醒所有等待者，被唤醒者会争抢 mutex，失败者又睡回去——即[惊群](/docs/CS/OS/Linux/proc/thundering_herd.md)。`FUTEX_REQUEUE` 把等待者直接转移到 mutex 的 futex 等待队列，让它们在正确的队列上按序醒来，避免了这一轮无效唤醒。

**PI futex 与优先级继承**：低优先级的锁持有者被中优先级任务抢占时，高优先级的等待者会无限等待（优先级反转）。`FUTEX_LOCK_PI` 让内核把持有者的优先级临时提升到等待者水平，等释放后再恢复；内核中由 `rt_mutex` 承接（见 [mutex](/docs/CS/OS/Linux/Lock/mutex.md)），Java 的 `ReentrantLock(true)` 与 RT 应用都用得到。

## 用户态实现：三态锁

以 glibc 的 pthread mutex 为例，锁字有三个状态：

- `0` 未加锁 → `1`：原子 `cmpxchg` 直接成功（**零系统调用**）；
- `1` 已加锁无等待者 → `2`：竞争时 CAS 置 2，再 `FUTEX_WAIT`；
- `2` 解锁：`xchg` 归还 0 后必须 `FUTEX_WAKE` 唤醒等待者。

"先改状态再进内核"的顺序是关键：它保证解锁方**总能观察到有人等待**，不会漏掉唤醒（否则会出现"刚判断无人等待 → 对面已入睡 → 永久睡眠"的丢唤醒）。

## 上层语言对照

| 语言/库 | 同步对象 | 与 futex 的关系 |
| :-- | :-- | :-- |
| pthread | mutex / cond | 直接基于 futex（见 [pthread](/docs/CS/OS/Linux/proc/pthread.md)） |
| Java | `synchronized`、`LockSupport.park` | ObjectMonitor / [Parker](/docs/CS/Java/JDK/Concurrency/Parker.md) 基于 pthread mutex+cond，即 futex |
| Go | `sync.Mutex` 慢路径 | runtime 自研 semaphore 直接调 `futex`；**channel 的 `gopark` 不走 futex**（纯用户态） |
| nginx | `ngx_shmtx_t`（跨 worker 共享内存锁） | **不走 futex**：原子 CAS + 指数退避自旋（`spin = 2048`、`ngx_cpu_pause`）+ POSIX 信号量睡眠（`sem_wait` / `sem_post`），见 [Nginx Memory](/docs/CS/CN/nginx/memory.md) |
| 用户态工具 | `futex(2)`、`FUTEX_WAITV` | 多地址批量等待，用于多锁/多事件场景 |

对照细节见 [语言运行时与内核任务](/docs/CS/OS/Linux/proc/runtime.md?id=阻塞与唤醒：futex-是桥梁)。

## 观测与调试

- `strace -e futex` 可以看到进程的睡眠/唤醒行为（`FUTEX_WAIT` 阻塞、`FUTEX_WAKE` 唤醒）；数量激增通常意味着锁竞争加剧；
- `perf trace -e futex`、`bpftrace` 统计每次等待的时长（延迟分析）；
- 大量 `FUTEX_WAIT_PRIVATE` 是正常的（私有 futex）；出现 `_PI` 变体说明程序在使用优先级继承锁。

## Links

- [Lock](/docs/CS/OS/Linux/Lock/README.md)
- [原子操作与内存屏障](/docs/CS/OS/Linux/Lock/atomic.md)
- [等待队列与惊群](/docs/CS/OS/Linux/proc/thundering_herd.md)
- [pthread](/docs/CS/OS/Linux/proc/pthread.md)
- [跨进程同步](/docs/CS/OS/Linux/Lock/ipc-sync.md) — 跨进程 futex / robust mutex / PI 的应用场景
- [Futexs（理论）](/docs/CS/OS/process.md?id=futexs)
