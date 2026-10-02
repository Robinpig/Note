## Introduction

mutex 只能"一个持锁者"，也没有跨上下文的能力。内核还需要两类更通用的睡眠同步原语：

- **信号量（semaphore）**：计数型资源信号量，允许 N 个持有者，且 `up()` 可以在中断上下文调用；
- **completion**：一次性事件等待，最轻量的"等某件事发生"。

两者都会睡眠，因此只能在进程上下文（获取侧）使用，语义与用户态的 POSIX 信号量/条件变量同源，理论部分见 [Semaphores](/docs/CS/OS/process.md?id=semaphores)。

## 信号量

```c
DEFINE_SEMAPHORE(sem);            /* 计数为 1，同一时刻一个持有者 */

down(&sem);                       /* 不可中断地获取，睡眠等待 */
down_interruptible(&sem);         /* 可被信号打断，返回 -EINTR；驱动中最常用 */
down_trylock(&sem);               /* 不睡眠，立即返回结果 */
up(&sem);                         /* 释放 / 唤醒一个等待者，可在中断上下文调用 */

sema_init(&sem, 4);               /* 计数为 4：允许 4 个并发持有者 */
```

与 mutex 的关键差异：

| | mutex | semaphore |
| :-- | :-- | :-- |
| 持有者数量 | 1 | 1..N（由初值决定） |
| 所有权 | 有（只有 owner 能 unlock） | 无（任何上下文都能 `up()`） |
| 能用于中断上下文 | 不能获取也不能释放 | 不能 `down()`，但**可以 `up()`** |
| 典型用途 | 互斥保护临界区 | 生产者-消费者、事件通知、限流 |

**"中断里 up、进程里 down"是信号量的经典用法**：驱动在中断处理程序中 `up()` 唤醒等待数据的进程。这也是它无法被 mutex 取代的地方（mutex 不允许在中断中释放，因为 mutex 有 owner 概念而中断没有 task 身份）。

其他变体：读优先的 `down_read_trylock` 语义见 [rwsem](/docs/CS/OS/Linux/Lock/rwsem.md)；`rt_mutex` 是支持优先级继承的 mutex，可显著缓解优先级反转（见 [mutex](/docs/CS/OS/Linux/Lock/mutex.md)）。

## completion

completion 是"一次性信号量"的特化：专门表达"等一件事完成"，语义更清晰、开销更小。

```c
/* 初始化 */
struct completion done;
init_completion(&done);            /* 或 DECLARE_COMPLETION(done) */

/* 等待侧（进程上下文） */
wait_for_completion(&done);                    /* 不可中断 */
wait_for_completion_interruptible(&done);      /* 可被信号打断 */
wait_for_completion_timeout(&done, HZ);        /* 带超时 */

/* 完成侧（任意上下文，包括中断） */
complete(&done);                   /* 唤醒一个等待者 */
complete_all(&done);               /* 唤醒所有等待者（用于"事件永远成立"） */
```

- `complete()` 唤醒**一个**等待者，`complete_all()` 唤醒全部；
- 重复等待同一个 completion 需要 `reinit_completion()` 重置计数；
- 典型场景：驱动 probe 等待设备初始化完成、模块加载等待依赖就绪、`kthread` 启动握手（等线程真正跑起来）。

## 等待队列：更底层的通用设施

completion 和信号量的睡眠最终都落到**等待队列**（wait queue）上：

```c
DEFINE_WAIT(wait);                 /* 或用 wait_event 系列宏 */
wait_event(wq, condition);                     /* 不可中断 */
wait_event_interruptible(wq, condition);       /* 可中断 */
wait_event_timeout(wq, condition, timeout);
wake_up(&wq);
wake_up_interruptible(&wq);
```

`wait_event` 宏内部就是"设置状态 → 入队 → 检查条件 → 睡眠 → 循环"的经典模式；`up()`/`complete()` 的内核实现同样是 `wake_up` 等待队列。等待队列的睡眠与唤醒路径（含惊群问题）详见 [thundering herd](/docs/CS/OS/Linux/proc/thundering_herd.md?id=wait)。

## 选择建议

- 只有"一个持锁者"且需要所有权语义 → [mutex](/docs/CS/OS/Linux/Lock/mutex.md)；
- 需要计数、或必须在中断中唤醒 → **semaphore**；
- 只是"等某个事件发生" → **completion**（比信号量更直观）；
- 等条件成立（可重试判断） → **wait_event 系列**；
- 用户态跨进程互斥 → [futex](/docs/CS/OS/Linux/Lock/futex.md)。

## Links

- [Lock](/docs/CS/OS/Linux/Lock/README.md)
- [mutex](/docs/CS/OS/Linux/Lock/mutex.md)
- [thundering herd（等待队列）](/docs/CS/OS/Linux/proc/thundering_herd.md)
- [Semaphores（理论）](/docs/CS/OS/process.md?id=semaphores)
