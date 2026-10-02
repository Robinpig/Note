## Introduction

内核只认识 [task_struct](/docs/CS/OS/Linux/proc/process.md?id=task-struct) 表示的任务，它并不知道 Java 的 Thread 或 Go 的 goroutine。这些语言级并发实体都是**运行时概念**，最终以某种方式落到 `clone` 出来的内核任务上。按语言实体与内核任务的比例分三种模型：

- **1:1**：每个语言线程对应一个内核任务（Java 平台线程、C/C++ pthread）；
- **N:1**：所有用户线程复用一个内核任务（早期绿色线程，已淘汰）；
- **M:N**：M 个用户协程复用 N 个内核任务（Go goroutine、Java 虚拟线程、Kotlin 协程等）。

## 模型总览

| 语言实体 | 模型 | 运行载体 | 内核视角 |
| :-- | :-- | :-- | :-- |
| Java 平台线程 | 1:1 | pthread | 每个 Thread 一个 task |
| Java 虚拟线程 | M:N | carrier 线程（ForkJoinPool） | 数百万虚拟线程对少量 task |
| Go goroutine | M:N | M（内核线程）+ P（逻辑处理器） | 内核只调度 M，看不见 G |

## 线程的创建：clone 而非 fork

用户态线程通过 glibc 的 `pthread_create` 创建，底层是 `clone3` 系统调用，但 flags 与 [fork](/docs/CS/OS/Linux/proc/process.md?id=fork) 完全不同——不复制而是**共享**：

```c
CLONE_VM | CLONE_FS | CLONE_FILES | CLONE_SIGHAND | CLONE_THREAD
| CLONE_SYSVSEM | CLONE_SETTLS | CLONE_PARENT_SETTID | CLONE_CHILD_CLEARTID
```

共享 `mm`/`fs`/`files`/`sighand` 意味着同一进程的线程共用地址空间与打开文件表。这也是 [task_struct](/docs/CS/OS/Linux/proc/process.md?id=pid) 中 `tgid` 与 `pid` 之分的来源：同一线程组内所有任务 `getpid()` 返回同一个 tgid，而 `gettid()` 才是内核里各自的 pid。

- **Java**：JVM 通过 `os::create_thread` → `pthread_create` 创建，`JavaThread`/`OSThread` 在内核任务之上包装；JVM 自身的 VMThread、GC 线程等也是同样的内核任务，见 [JVM Thread](/docs/CS/Java/JDK/JVM/Thread.md)。
- **Go**：`runtime.newosproc` 用内嵌汇编直接发起 raw clone（绕过 glibc，避免信号掩码等副作用），由此得到 M；GOMAXPROCS 限制的是 P 的数量而非 M——阻塞在 syscall 里的 M 会让 M 的数量远超 P，见 [Goroutine](/docs/CS/Go/Concurrency/Goroutine.md?id=gmp)。

## 调度：内核调度器之上

- **Java 平台线程**：调度完全交给内核。`Thread.setPriority(1~10)` 经 JVM `os::set_priority` 映射为 nice 值，最终作用于 [EEVDF 的权重](/docs/CS/OS/Linux/proc/fair.md?id=vruntime-与权重)——与 nice 一样只影响分时比例，不影响绝对优先级。
- **Go**：内核只见 M 并按普通任务调度；G 的调度在用户态由 runtime 完成（[GMP 模型](/docs/CS/Go/Concurrency/Goroutine.md?id=gmp)）：`findRunnable` 选 G ≈ 内核的 `pick_next_task`，`gogo`/`gopark` ≈ 上下文切换。1.14+ 的异步抢占用 `SIGURG` 打断运行中的 G，思想上是内核 [TIF_NEED_RESCHED 两阶段抢占](/docs/CS/OS/Linux/proc/sche.md?id=preemption)的应用层翻版。
- **Java 虚拟线程**：carrier 线程由 ForkJoinPool（FIFO 模式）管理；虚拟线程阻塞时 unmount（栈换出到堆），carrier 立刻跑别的虚拟线程，全程不进内核，见 [Virtual Thread](/docs/CS/Java/JDK/Concurrency/VirtualThread.md)。

## 阻塞与唤醒：futex 是桥梁

[futex](/docs/CS/OS/Linux/Lock/futex.md)（[理论](/docs/CS/OS/process.md?id=futexs)）的设计是"无竞争时纯用户态原子操作，竞争时才陷入内核挂到[等待队列](/docs/CS/OS/Linux/proc/thundering_herd.md?id=wait)"，两个运行时都重度依赖它：

- **Java**：`LockSupport.park` → [Parker](/docs/CS/Java/JDK/Concurrency/Parker.md)（`pthread_mutex`/`pthread_cond`，glibc 内部即 futex 实现）；`synchronized` 的 ObjectMonitor 与 [AQS](/docs/CS/Java/JDK/Concurrency/AQS.md) 队列同样落到 park。
- **Go**：runtime 自带的 semaphore 直接调用 `futex_wait`/`futex_wake`（`sync.Mutex` 慢路径）；而 channel 阻塞走 `gopark`，纯用户态挂起、**不进内核**——这是 Go 与 Java 阻塞语义的本质区别。

## IO：epoll 与 netpoller

线程/协程阻塞在 IO 上时的归宿：

- **Java**：BIO 会把整个平台线程（一个内核任务）挂起；NIO 的 [Selector](/docs/CS/Java/JDK/IO/NIO.md) 封装 [epoll](/docs/CS/OS/Linux/IO/epoll.md)，少量线程管理海量连接。
- **Go**：netpoller 把 fd 注册进 epoll，G 阻塞读时 `gopark` 挂起，fd 就绪后由 epoll 事件回调 `goready` 唤醒——"阻塞式 API"的表象下是同样的 epoll 事件循环。

## 信号

- **Go**：runtime 为每个 M 通过 `sigaltstack` 安装专用信号栈；`SIGURG` 用于异步抢占。
- **JVM**：为 `SIGSEGV` 等安装 handler，把硬件异常翻译成 `NullPointerException`；内部用 `SIGUSR1/2` 等做线程间通信；`-Xrs` 可关闭大部分信号处理。

## 栈与切换成本

| | Java 平台线程 | Java 虚拟线程 | Go goroutine |
| :-- | :-- | :-- | :-- |
| 栈 | `mmap` 固定大小（`-Xss`，默认约 1MB） | 堆上按需增长 | 2KB 起，`morestack`/`lessstack` 复制扩缩 |
| 切换 | 内核上下文切换（两次特权级切换 + 调度器 + 缓存污染，μs 级） | 用户态 mount/unmount（复制栈帧，百 ns 级） | 用户态 `gogo` 换寄存器与栈指针，无特权级切换（百 ns 级） |

协程的高并发能力正是来自"用户态切换 + 小栈"：百万级 goroutine 的内存与切换开销，用 1:1 线程模型不可想象。

## 观测

- 内核侧：`ps -T -p PID`、`top -H`、`/proc/PID/task/`（每个 tid 一个目录，见 [procfs](/docs/CS/OS/Linux/fs/proc.md)）——JVM 或 Go 程序的"线程"都如实出现在这里。
- Java：`jstack` / `jcmd Thread.print`（虚拟线程也会列出，挂在 carrier 上）。
- Go：`pprof` 的 goroutine profile 与 `GOTRACEBACK`，见 [pprof](/docs/CS/Go/pprof.md)。

## Links

- [Processes 知识地图](/docs/CS/OS/Linux/proc/README.md)
- [process](/docs/CS/OS/Linux/proc/process.md)
- [sche](/docs/CS/OS/Linux/proc/sche.md)
- [pthread](/docs/CS/OS/Linux/proc/pthread.md)
- [Goroutine（GMP）](/docs/CS/Go/Concurrency/Goroutine.md)
- [Java Thread](/docs/CS/Java/JDK/Concurrency/Thread.md)
- [Virtual Thread](/docs/CS/Java/JDK/Concurrency/VirtualThread.md)
