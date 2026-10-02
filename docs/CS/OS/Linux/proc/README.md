## Introduction

Linux 不区分进程与线程，内核用统一的 `task_struct` 把一切执行上下文表示为**任务**（task）：单线程进程对应一个 task，多线程进程的每个用户线程各有一个 task，内核线程（kernel thread）同样如此。本页是 `proc/` 目录的**链路总图**，沿一个任务的一生来组织——它如何被**创建**、内核用什么结构**表示**它、怎样**装载**新程序、如何被**调度**上 CPU、等待资源时如何**睡眠与唤醒**、异步事件如何用**信号**打断它、最终又如何**退出并被回收**。

理解这条链的钥匙是两个视角的叠加：`task_struct` 是**静态快照**（一个任务此刻持有什么），而 fork / exec / schedule / signal / exit 是**动态事件**（任务的状态如何迁移）。需要细节时再进入对应笔记，全部内容以 Linux 6.x 内核源码阅读为主。

## 起点：0 号进程与进程树

一切任务都从一棵层级树里长出来。系统启动后先有手工构造的 **0 号进程**（[init task](/docs/CS/OS/Linux/proc/process.md?id=init-task)），它是所有任务的根：由它衍生出内核线程，也衍生出 1 号 `init` 进程，再由 init 逐层 fork 出用户空间的一切。这解释了两个事实：每个任务都有父任务（层级关系字段在 `task_struct` 里），而 fork/exec 正是这棵树不断分叉的机制。用户态可用 `pstree` / `ps -fax` 直观看到这棵树。

## 诞生：fork 与 copy_process

一个新任务几乎总是由 **fork**（[fork](/docs/CS/OS/Linux/proc/process.md?id=fork)）创建。用户态的 `fork`/`clone`/`pthread_create` 最终都进入 `kernel_clone()`（[kernel_clone](/docs/CS/OS/Linux/proc/process.md?id=kernel_clone)），核心工作交给 `copy_process()`（[copy_process](/docs/CS/OS/Linux/proc/process.md?id=copy_process)）：复制（或共享）父任务的各类资源、分配新的 `task_struct` 与 pid、把它挂入进程树与调度器，最后才唤醒它。

fork 的高效来自**写时复制（copy on write）**：子任务并不真的复制父任务的内存，父子先共享同一批只读物理页；任一方写入页面时触发缺页，内核才复制那一页。这把"复制整个地址空间"的代价摊到了真正发生修改的页上，也让 fork 后立刻 exec 的常见场景几乎不做无用的内存复制——内存与缺页机制详见 [内存管理知识地图](/docs/CS/OS/Linux/mm/README.md)。

> 创建一个**线程**本质是 fork 时选择共享而非复制：传入 `CLONE_VM | CLONE_FILES | CLONE_SIGHAND` 等标志，新 task 与父 task 共享地址空间、文件表、信号处理。这条分支见 [thread](/docs/CS/OS/Linux/proc/process.md?id=thread) 与 [Threads](/docs/CS/OS/Linux/proc/process.md?id=threads)。

## 表示：task_struct 与 pid

任务被创建后，内核用 [task_struct](/docs/CS/OS/Linux/proc/process.md?id=task-struct) 完整描述它。这是进程管理的中心数据结构，把一个任务持有的一切聚在一起：

- **状态**：`TASK_RUNNING` / `TASK_INTERRUPTIBLE` / `TASK_UNINTERRUPTIBLE` / `TASK_STOPPED` / 僵尸等——状态决定一个任务此刻能否被调度、能否被信号打断；
- **调度信息**：静态/动态优先级，以及分属各调度类的调度实体（`se` / `rt` / `dl`），调度器通过它们而非整个结构体操作任务；
- **资源封装**：`mm`（地址空间）、`files`（文件表）、`fs`、`signal` / `sighand`（信号）、`namespace`（视图隔离）等指针，fork 时这些资源可以复制也可以共享。

任务的身份由 [pid](/docs/CS/OS/Linux/proc/process.md?id=pid) 相关字段表达，关键是 **pid 与 tgid 之分**：每个 task 有独立 pid，而同一线程组共享 tgid（即用户看到的"进程号"）——这正是"内核只见 task、用户态区分进程与线程"的落地点。

## 换身：exec 装载新程序

fork 只造出一个与父任务相同的副本，要运行另一个程序得靠 **exec**（[exec](/docs/CS/OS/Linux/proc/process.md?id=exec)）。它进入 `bprm_execve()`（[bprm_execve](/docs/CS/OS/Linux/proc/process.md?id=bprm_execve)）：打开可执行文件、识别格式（ELF / 脚本）、清空当前地址空间里旧程序的映射、装入新程序的代码数据与参数环境，最后设置新的执行起点。

注意 exec **不创建新任务、也不换 pid**——同一个 task 的"身体"（地址空间内容）被整体替换。fork + exec 因此分工清晰：fork 负责"再要一个执行流"，exec 负责"让它跑另一个程序"。任务加载新程序时如何建立初始 VMA 布局，见 [虚拟内存](/docs/CS/OS/Linux/mm/vm.md?id=load-binary)。

## 上 CPU：调度器

任务就绪后并不立刻运行，而是被放入运行队列，由调度器决定"何时、在哪个 CPU 上运行"。这是进程链中最庞大的一环，分三个层次：

**① 调度框架**（[sche](/docs/CS/OS/Linux/proc/sche.md)）：每个 CPU 一个 [run queue](/docs/CS/OS/Linux/proc/sche.md?id=run-queue)，主切换函数是 [schedule()](/docs/CS/OS/Linux/proc/sche.md?id=schedule)——它通过 [sched_class](/docs/CS/OS/Linux/proc/sche.md?id=sched_class) 的回调，按优先级顺序向各调度类要下一个任务（[pick_next_task](/docs/CS/OS/Linux/proc/sche.md?id=pick_next_task)），再做 [context switch](/docs/CS/OS/Linux/proc/sche.md?id=context-switch) 切换地址空间与寄存器。进程通过 [policy](/docs/CS/OS/Linux/proc/sche.md?id=policy) 选择调度策略，通过 [affinity](/docs/CS/OS/Linux/proc/sche.md?id=affinity) 限定能在哪些 CPU 上跑。

**② 普通任务调度器**（[fair](/docs/CS/OS/Linux/proc/fair.md)）：这是绝大多数进程走的类。它按 [vruntime 与权重](/docs/CS/OS/Linux/proc/fair.md?id=vruntime-与权重)公平分配 CPU，nice 值映射为权重；6.6+ 调度核心是 [EEVDF](/docs/CS/OS/Linux/proc/fair.md?id=eevdf)，用 lag 记账、virtual deadline 兼顾响应性，由 [pick_next_entity](/docs/CS/OS/Linux/proc/fair.md?id=pick_next_entity) 选任务，唤醒时的抢占判断见 [check_preempt_wakeup](/docs/CS/OS/Linux/proc/fair.md?id=check_preempt_wakeup)，[CFS 带宽控制](/docs/CS/OS/Linux/proc/fair.md?id=cfs-带宽控制)则限制一个组在周期内最多占用多少 CPU。

**③ 实时与其他调度器**：[rt](/docs/CS/OS/Linux/proc/rt.md) 处理 [实时策略](/docs/CS/OS/Linux/proc/rt.md?id=实时策略) SCHED_FIFO/RR，配合 [RT throttling](/docs/CS/OS/Linux/proc/rt.md?id=rt-throttling) 防止实时任务独占系统；sche.md 还介绍了 [dl](/docs/CS/OS/Linux/proc/sche.md?id=dl)（Deadline）、[idle](/docs/CS/OS/Linux/proc/sche.md?id=idle) 两类。

**④ 可编程调度**（[sched_ext](/docs/CS/OS/Linux/proc/sched_ext.md)）：6.12 起可以用 BPF 程序自己实现调度策略并在线装载——内核只提供可扩展调度类与兜底，选谁运行交给 BPF 决定。它排在类链表中 fair 之后、idle 之前，实时类仍在其上；调度器卡死会被看门狗检出并自动卸载回落。这是"不改内核换调度器"的出口。

## 何时切换：抢占

任务不会主动让出 CPU 也能被切换——内核在时钟 tick、唤醒更高优先级任务等时机，给当前 CPU 置上 `TIF_NEED_RESCHED` 标志，在中断返回、内核代码安全点等位置检查它并触发调度，这就是**两阶段抢占**（[preemption](/docs/CS/OS/Linux/proc/sche.md?id=preemption)）。"何时允许抢占"由 PREEMPT_NONE / VOLUNTARY / PREEMPT 等配置决定，直接影响吞吐与延迟的取舍。调度框架与算法的对照见 [Scheduling](/docs/CS/OS/scheduling.md)。

## 等待资源：睡眠、唤醒与惊群

任务常常要等某件事——等磁盘数据、等锁、等网络连接。此时它不该占着 CPU，而是进入睡眠：经等待队列把状态置为可/不可中断睡眠并从运行队列摘下（[wait](/docs/CS/OS/Linux/proc/thundering_herd.md?id=wait)）；条件满足时由 `wake_up` / `try_to_wake_up` 把它重新置为就绪、放回运行队列（[wake](/docs/CS/OS/Linux/proc/thundering_herd.md?id=wake)）。这一环是**调度器与各类 I/O、同步机制的接合点**，与 futex 等待队列共用同一套睡眠唤醒逻辑。

唤醒是一对多的：一个事件可能唤醒一群等待者，造成"**惊群**"——大批任务被唤醒、争抢同一资源、只有一个成功，其余白跑一趟。这是服务端编程的经典问题，[thundering herd](/docs/CS/OS/Linux/proc/thundering_herd.md) 给出两处典型：多进程竞争 [accept](/docs/CS/OS/Linux/proc/thundering_herd.md?id=accept) 新连接，以及 [epoll](/docs/CS/OS/Linux/proc/thundering_herd.md?id=epoll) 事件分发；解决手段是 `EPOLLEXCLUSIVE` 等只唤醒一个等待者，[Nginx](/docs/CS/OS/Linux/proc/thundering_herd.md?id=nginx) 的 accept mutex 则在应用层规避。

## 异步通知：信号

信号让内核（或其他进程）能**异步**打断一个任务，通知它发生了某事件（终止、挂起、定时器到期、I/O 就绪等），它和"睡眠唤醒"互补——后者是任务主动等条件，信号是外部主动插话。信号链分三步（[signal](/docs/CS/OS/Linux/proc/signal.md)）：

1. **产生**：[send_signal](/docs/CS/OS/Linux/proc/signal.md?id=send_signal) 把信号加入任务（或线程组）的挂起队列 pending；
2. **注册处理方式**：[do_sigaction](/docs/CS/OS/Linux/proc/signal.md?id=do_sigaction) 决定信号是默认动作（终止/忽略/暂停）、忽略还是执行用户安装的处理函数；
3. **取用与处理**：任务在返回用户态的路上经 [get_signal](/docs/CS/OS/Linux/proc/signal.md?id=get_signal) 取出待处理信号，若有用户处理函数则搭建信号栈帧、转去执行，再由 `rt_sigreturn` 回到原执行点。

## 退场：exit、僵尸与回收

任务完成工作后经 [exit](/docs/CS/OS/Linux/proc/process.md?id=exit) 退出：释放大部分资源（地址空间、文件、信号等），但**不会立刻清掉自己的 task_struct**——它进入**僵尸（zombie）**状态，保留退出码等信息，等待父任务来"收尸"。父任务通过 wait 系列调用获知子任务的退出状态（[termination](/docs/CS/OS/Linux/proc/process.md?id=termination)），内核才彻底回收这个 task。

这一设计解释了两个常见现象：父任务不 wait，子任务就会变成僵尸占着 pid；父任务若先退出，孤儿任务会被托管给 init，由 init 负责回收。至此任务的一生闭环——**从进程树中 fork 出来，最终又回到这棵树里被回收**。

## 三条支线

主链之外，三组笔记承接更具体的话题：

- **线程与用户态**：[pthread](/docs/CS/OS/Linux/proc/pthread.md) 讲 NPTL 用户态编程，包括 [Mutex](/docs/CS/OS/Linux/proc/pthread.md?id=mutex) 与 [Condition Variable](/docs/CS/OS/Linux/proc/pthread.md?id=condition-variable)；内核侧线程即共享资源的 task。
- **进程间通信**：[IPC](/docs/CS/OS/Linux/proc/IPC.md) 总览 pipe / FIFO / 消息队列 / 共享内存 / 信号量 / socket 的选择，[pipe](/docs/CS/OS/Linux/proc/IPC.md?id=pipe) 为单向半双工；跨机通信走 socket，见 [socket 与跨机](/docs/CS/OS/Linux/proc/IPC.md?id=socket-与跨机)。内核内部同步原语（锁 / futex / RCU）见 [Lock 总览](/docs/CS/OS/Linux/Lock/README.md)。
- **语言运行时**：[runtime](/docs/CS/OS/Linux/proc/runtime.md) 讲 Java 线程、Go 协程如何最终落到 clone / futex / epoll / 调度器上，是内核任务模型与语言并发模型的对照。

## 内核机制 × Nginx

Nginx 是「多进程 + 事件驱动」服务端程序的典型样本，几乎每个进程环节都能在它身上找到落地：master 先读配置、绑端口，再 fork 出 worker；整个生命周期由 **信号**驱动（`SIGHUP` reload、`SIGQUIT` 优雅退出）；多 worker 间的 **accept 惊群**由 accept mutex 与 `EPOLLEXCLUSIVE` 规避；worker 用 **epoll** 事件循环非阻塞处理海量连接；平滑升级则借助 exec 换新映像。各点与内核笔记的完整对照见下方 References 所在目录的相关笔记，Nginx 侧笔记入口为 [nginx](/docs/CS/CN/nginx/nginx.md)。类似的 fork + COW 案例还有 Redis 的 RDB 持久化；容器化运行则叠加 [namespace](/docs/CS/OS/Linux/namespace.md) / [cgroup](/docs/CS/OS/Linux/cgroup.md) 的隔离与限制。

## 观察与调试

- [ptrace](/docs/CS/OS/Linux/proc/ptrace.md)：进程跟踪与调试的内核接口，strace / GDB 的底座（停止状态机、事件上报、系统调用拦截）；
- [strace](/docs/CS/OS/Linux/Tools/strace.md)：跟踪任务的系统调用（fork/execve/clone/signal）；
- [perf](/docs/CS/OS/Linux/Tools/Perf.md)、[ftrace](/docs/CS/OS/Linux/Tools/ftrace.md)、[eBPF](/docs/CS/OS/Linux/Tools/eBPF.md)：观测调度与唤醒行为；
- `/proc/sched_debug`、`ps`/`top`/`pstree`：运行队列与进程树快照。

## 学习路径

1. 先读 [process.md](/docs/CS/OS/Linux/proc/process.md)，建立 `task_struct` 与 fork → exec → exit 主线；
2. 进入 [sche.md](/docs/CS/OS/Linux/proc/sche.md)，按调度框架 → [fair/EEVDF](/docs/CS/OS/Linux/proc/fair.md) → [rt](/docs/CS/OS/Linux/proc/rt.md) 展开；
3. 补上睡眠唤醒与惊群 [thundering_herd](/docs/CS/OS/Linux/proc/thundering_herd.md)，再看 [signal](/docs/CS/OS/Linux/proc/signal.md)、[IPC](/docs/CS/OS/Linux/proc/IPC.md)；
4. 用 [runtime](/docs/CS/OS/Linux/proc/runtime.md) 把内核机制映射到 Java/Go，用 [xv6 proc](/docs/CS/OS/xv6/proc.md) 对照简化实现。

## Links

- [Linux 内核总览](/docs/CS/OS/Linux/Linux.md)
- [OS Process 理论](/docs/CS/OS/process.md)
- [Scheduling 算法](/docs/CS/OS/scheduling.md)
- [内存管理知识地图](/docs/CS/OS/Linux/mm/README.md)
- [timer 时间子系统](/docs/CS/OS/Linux/timer.md)

## References

1. [Linux Scheduler documentation — kernel.org](https://www.kernel.org/doc/html/latest/scheduler/index.html)
2. [Process — The Linux kernel documentation](https://www.kernel.org/doc/html/latest/process/index.html)
