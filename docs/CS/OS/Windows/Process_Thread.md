## Introduction

Linux 里"进程"是分配器与调度器共享的中心词，线程是不拥有地址空间的特殊进程；Windows 里这个关系反了过来——**NT 的调度单位从一开始就是线程，进程只是一个容器**。这条差别决定了后面所有东西：为什么 Windows 上一个"什么都不干"的进程也有不少固有开销，为什么 `CreateProcess` 比 `fork` + `exec` 慢那么多，为什么 Windows 给线程准备了一整套自己的同步与等待机制。

本文按一条从结构到行为的链推进：先看**进程与线程在内核里是什么**（四层数据结构），再看**线程状态机与 32 级优先级模型**，然后是**量子与前台提升**、**多处理器下的处理器组**、**等待与分发器对象**，最后是 NT 特有的两个异步执行载体 **APC 与 DPC**、以及它们之上的 **IRQL**。规模相关的部分（作业对象、会话与服务）放在最后。

---

## Four Data Structures: EPROCESS, KPROCESS, ETHREAD, KTHREAD

Windows 内核里每个进程有两个结构体、每个线程也有两个，分工非常干净：

| 结构体 | 所属层 | 内容举例 |
| :-- | :-- | :-- |
| `KPROCESS` | Kernel（微内核） | 分发器需要的东西：就绪线程链表、基优先级、量子重置值、亲和掩码、进程页目录基址 |
| `EPROCESS` | Executive | 执行体需要的东西：句柄表指针、VAD 树根、工作集、令牌、PEB 地址、作业对象指针、进程 id |
| `KTHREAD` | Kernel | 调度与等待需要的东西：内核栈、TEB 地址、等待块、APC 队列、当前/基优先级、量子剩余、CPU 状态存档 |
| `ETHREAD` | Executive | 附着在上面：所属进程指针、I/O 请求链路、安全上下文、创建/退出时间 |

`KPROCESS` 嵌在 `EPROCESS` 头部、`KTHREAD` 嵌在 `ETHREAD` 头部，所以"要不要穿过执行体"只是个偏移量问题。这个设计的意义在于：**内核自己在切换线程时只需要碰 KTHREAD/KPROCESS 那部分字段**，执行体的那些字段（句柄表、VAD、令牌）不会因为调度而被频繁触碰。类比到 Linux，`task_struct` 是把这两层混在一起的。

### Process Creation: CreateProcess in Nine Steps

1. 定位并打开可执行文件映像，校验它是合法的 PE；
2. 创建 `EPROCESS`/`KPROCESS`；
3. 创建初始线程（`ETHREAD`/`KTHREAD`）；
4. 创建新的地址空间，映射映像与其依赖的 DLL；
5. 建立初始线程的栈与上下文；
6. 通知子系统（Win32 路径上通常是 `csrss.exe`）有新进程诞生；
7. 插入伪装：先创建进程对象，再由执行体接手完成剩下的初始化；
8. 首线程开始执行 `ntdll` 的初始化，然后跳到映像入口；
9. 完成 "process clone/exec" 语义——注意 **Windows 没有 `fork`**。`CreateProcess` 一次性给出"一个新进程 + 一个主映像 + 一个主线程的初始上下文"，进程树没有"复制一份自己然后再换掉"那个模型。

> [!NOTE]
>
> **为什么没有 fork**
>
> `fork` 需要"进程复制"这件事便宜到可以随手用，这要求页表写时复制与 mm_struct 复制足够快。NT 选择不复制：进程创建就是一次完整的"从零建立"，因此 `CreateProcess` 的绝对成本高于 `fork`，但语义简单、且天然适合 [WSL](/docs/CS/OS/Windows/WSL.md) 之外那种"一个可执行文件就是一个进程"的模型。
>
> 这也是为什么 Windows 上"多进程分摊任务"的收益曲线与 Linux 不同——起进程的门槛更高，所以 Windows 应用更倾向线程池（thread pool）+ 异步 I/O。

---

## Thread States

NT 的线程状态机比"就绪/运行/阻塞"三态更细：

| 状态 | 含义 |
| :-- | :-- |
| Initialized | 对象已创建但尚未启动（未就绪） |
| Ready | 已经进入某个 CPU 的就绪队列，等待被调度 |
| Running | 正在某个 CPU 上执行 |
| Standby | 已被选为某个 CPU 的下一个线程，等待上下文切换完成 |
| Waiting | 正在等待某个分发器对象（锁、I/O、定时器等） |
| Transition | 已满足等待条件但内核栈还没换入物理内存，等待换入后进入 Ready |
| Deferred Ready | 已被置为就绪但还没落到具体的 CPU 上 |
| Terminated | 执行完毕，等待被删除 |

**Transition** 是这张表里最容易让人困惑的一项：它对应的是"线程已经可以跑了，但它的内核栈还在磁盘上"。这提醒我们一件事——**Windows 的内核栈可以被换出到页文件**。这条规则一旦与后文的 IRQL 组合，就变成了驱动开发者必须记住的铁律。

---

## The 32-Level Priority Model

NT 的调度是**优先级驱动的抢占式调度**，32 个优先级分成三个带：

| 优先级 | 类别 | 说明 |
| :-- | :-- | :-- |
| 0 | 系统 / 零页线程 | 只有一个零页线程（Zero Page Thread）在空闲时清零备用页用 |
| 1 ~ 15 | 动态（Variable） | 普通应用线程的活动范围，会被内核提升与衰减 |
| 16 ~ 31 | 实时（Real-time） | 从不提升、从不衰减，也不会因缺页而被"照顾" |

每个线程有两个优先级：**基优先级（base priority）**与**当前优先级（current priority）**。前者由进程的优先级类（Idle、Below Normal、Normal、Above Normal、High、Realtime）与线程的相对优先级（如 `THREAD_PRIORITY_HIGHEST`）组合算出，后者是调度器实际看到的那个值，会被内核动态调整。

> [!WARNING]
>
> **实时优先级带是非常危险的工具**
>
> 优先级 16~31 的线程永不衰减。一个跑死循环的实时优先级线程可以把同一个 CPU 上所有其他线程饿死，而这种优先级即便管理员也不一定能挽回——包括那个登录进程。**「我需要更快」通常应该用 I/O 完成端口（见 [Windows I/O](/docs/CS/OS/Windows/IO.md)）而不是把线程提到实时带。**

### Priority Boosts

处在动态带（1~15）的线程不会因为长期占用 CPU 而受罚，反而会因为**等待得当**而受奖。调度器在下述事件发生时提升当前优先级，然后随 CPU 消耗逐步衰减回基优先级：

| 触发事件 | 提升幅度 |
| :-- | :-- |
| I/O 完成（键盘、鼠标） | +6 |
| I/O 完成（磁盘、网络） | +1 |
| 等待的执行体事件被满足 | +1 |
| 前台进程拥有线程拥有的窗口 | 由 `PsPrioritySeparation` 决定（默认 +2） |
| 饥饿避免（Balance Set Manager） | 至多提到 15，持续一个量子 |

这套机制的设计意图与 Unix 的"nice + CFS 虚拟运行时间"完全不同：**Windows 主动给"刚完成 I/O 的线程"加码**，因为它认为这种线程大概率马上要跑一小段然后把 CPU 还回来。这在桌面交互场景下效果很好，代价是 CPU 密集的计算型负载在同一台机器上可能被反复推迟。

### Quantum: How Long a Turn Lasts

量子（quantum）是线程在被考虑换出之前允许占用的时间长度。NT 在这里给了两个不同的世界：

| 设置 | 默认方 | 量子长度 |
| :-- | :-- | :-- |
| 短、可变 | 客户端（Windows 11 等） | 约 2 个时钟周期，前台进程可放大到 3 倍 |
| 长、固定 | 服务器（Windows Server 等） | 约 12 个时钟周期 |

两个字段由注册表项 `HKLM\SYSTEM\CurrentControlSet\Control\PriorityControl\Win32PrioritySeparation` 的低 6 位控制，分成三个 2-bit 字段：短 vs 长、可变 vs 固定、以及优先级分隔（`PsPrioritySeparation`）。把窗口切到前台时，前景进程的线程获得额外量子：前台优先级分离默认设为 2，也就是前台线程拿到两份额外量子，合计三份。

> [!TIP]
>
> 系统属性里那个"调整为最佳性能（程序 / 后台服务）"的单选项，本质上就是在改这个注册表项的低六位。把它切成"后台服务"，你会得到长而固定的量子——吞吐更好，但拖动窗口的手感会变钝。

---

## Multiprocessor: Affinity and Processor Groups

线程只在一个 CPU 上时 Windows 的行为很容易理解：就绪队列是 per-CPU 的 **32 个优先级链表**之一，再配一个 32 位的 `ReadySummary` 位图，选下一个线程就是从最高位的置位 bit 里取——**O(1) 的调度查找**。

多 CPU 之后出现了 NT 特有的历史包袱：**处理器组（processor group）**。

- 早期实现的每个组最多容纳 **64 个逻辑处理器**，组编号从 0 开始；少于 64 个逻辑处理器的机器永远只有一个组；
- 在 Windows 11 与 Windows Server 2022 之前，**进程默认被限制在单个组内**，于是多线程应用的并发度被钉死在 64；
- 从 **Windows 11 与 Windows Server 2022** 起，进程与其线程默认跨系统内所有处理器（跨多个组）；为了兼容旧的亲和 API，引入了 **primary group** 概念：每个进程创建时被分配一个主组，线程优先调度到主组内的处理器，但可以被调度到任意其他组；
- 现代写法应当用 **CPU Sets** 来跨越组设置亲和，而不是老式的 `SetProcessAffinityMask`。

这条历史很好地说明了「[OS](/docs/CS/OS/OS.md) 里三条张力」里的最后一条：这里没有"正确答案"，只有一个随硬件规模变化而被迫调整的实现——以及为兼容而留下的、直到今天还在生效的默认行为。

---

## Waits and Dispatcher Objects

等待在 NT 里不是"系统调用 + 轮询"，而是**对象和内核的协作**：凡是被内嵌了 `DISPATCHER_HEADER` 的内核对象都可以被等待，统称**分发器对象**。

| 对象 | 语义 |
| :-- | :-- |
| Event | 通知（非自动复位）或同步（自动复位）事件，最常用 |
| Mutex | 可重入的所有权语义，含优先级继承，跨进程可用 |
| Semaphore | 计数信标 |
| Waitable Timer | 定时器到时可等待 |
| Process / Thread | 等待对象退出 |
| File | 等待异步 I/O 完成 |
| Queue / Gate / Timer (timer object) | 线程池等内部结构用 |

等待本身有几条不多被人们提及但很重要的性质：

- `WaitForMultipleObjects` 支持等待"任一个"（`bWaitAll = FALSE`）或"全部"（`TRUE`），后者实现上依赖一系列等待块（wait block），不是简单的循环；
- **可警告等待（alertable wait）**是异步过程调用能被投递的前提；普通的等待不会给 APC 提供插入点；
- 需要同时等待内核对象与窗口消息时要用 `MsgWaitForMultipleObjects`，这也是 UI 线程既能响应界面消息、又不至于忙等的经典写法。

---

## APC, DPC and the IRQL Framework

Windows 的异步执行不走"中断上下文 vs 进程上下文"这种二分法，而是三个明确机制：

### Asynchronous Procedure Call (APC)

APC 是**针对某个特定线程**排队的例程。它有三种：

| 类型 | 执行条件 | 典型用途 |
| :-- | :-- | :-- |
| User APC | 线程进入可警告等待状态时执行 | `QueueUserAPC`、部分完成 |
| Normal Kernel APC | IRQL 降到 PASSIVE 且无人禁用 APC 时执行 | 异步 I/O 完成的参数解开 |
| Special Kernel APC | IRQ 更高条件下执行，不可被禁用 | `IoCompleteRequest` 等内核内部用 |

APC 之所以存在，是因为 Windows 需要一种"在某个确定的线程上下文里执行代码"的机制——异步 I/O 完成之后要把数据拷回发起者的地址空间，必须在正确的进程/线程上下文里做。这是 Linux 里通过 workqueue 或 io_uring 的 task_work 解决的问题，NT 用 APC 回答。

### Deferred Procedure Call (DPC)

DPC 是**只绑定到 CPU、不绑定线程**的机制。中断服务例程跑完它必须做的最小部分，剩下的部分排成一个 DPC 队列，等 IRQL 从硬件中断级降到 DISPATCH_LEVEL 时执行。

DPC 的重要意义在于它定义了 Windows 里最硬的纪律：**跑在 DPC 里的代码不能等待、不能触碰分页内存、不能访问用户态地址**。因为它不跟任何线程绑定，调度器无法把它换出去。

### IRQL: The Real Preemption Rule

把上面这些串起来的骨架是 **IRQL（Interrupt Request Level）**：

| IRQL | 名称 | 谁在这里跑 |
| :-- | :-- | :-- |
| 0 | PASSIVE_LEVEL | 普通线程，绝大多数代码 |
| 1 | APC_LEVEL | 发生 APC 时的标称级 |
| 2 | DISPATCH_LEVEL | 调度器、DPC、自旋锁持有者 |
| 3 ~ 11 | 设备 IRQL（DIRQL） | 各设备注册的中断级别 |
| 最高 | HIGH_LEVEL | 机器检查等不可屏蔽场景 |

**关键规则：同一 CPU 上谁先执行，先看 IRQL，不看线程优先级。** 一个优先级 31 的实时线程，也抢不过跑在 DISPATCH_LEVEL 上的一段代码。这条规则把"优先级这套机制生效的前提"说清楚了——它只在 IRQL < DISPATCH_LEVEL 的世界里成立。

> [!NOTE]
>
> **由此派生出两条驱动铁律**
>
> 1. 持有自旋锁时 IRQL 会被抬到 DISPATCH_LEVEL，因此**锁里不能做任何可能阻塞的操作**；
> 2. 分页内存只能在 IRQL < DISPATCH_LEVEL 时访问，因此 **DPC 与中断处理里的缓冲区必须来自非分页池**。

---

## Scale: Jobs, Sessions and Services

### Job Objects

作业对象（Job object）是 Windows 在进程之上加的一层管理单位，专为**一组进程**设计：CPU 时间上限、进程数上限、内存限额、UI 限制（禁止创建窗口、禁止切换桌面）、以及把整组进程一次性终结。Windows 侧的原生容器隔离详见 [Container](/docs/CS/Container/Container.md)，其下的 server silo 正是从这套原语生长出来的。

### Sessions and Session 0 Isolation

Windows Vista 起，服务与交互式用户**被分到不同会话**：服务跑到 Session 0，第一个登录的用户在 Session 1。会话隔离意味着服务不能再向用户桌面创建窗口、也不能再向用户/应用发送窗口消息——这是一次面向 Shatter Attack 的结构性修复。它同时也是排查"服务里启动的 UI 程序为什么看不见"时的第一答案。

### Services per se

服务（service）有两个对立的重要属性：**它可以没有用户登录就运行**（SCM 在系统启动时按需拉起）、以及它运行在 Session 0。DLL 形态的服务无法单独存在，必须挂在某个 `svchost.exe` 宿主进程里，详见 [Windows 架构](/docs/CS/OS/Windows/Architecture.md)。

---

## Links

- [Windows 架构](/docs/CS/OS/Windows/Architecture.md)
- [Windows 内存管理](/docs/CS/OS/Windows/Memory.md)
- [Windows I/O 子系统](/docs/CS/OS/Windows/IO.md)
- [Windows IPC](/docs/CS/OS/Windows/IPC.md)
- [WSL](/docs/CS/OS/Windows/WSL.md)
- [进程管理](/docs/CS/OS/process.md)

---

## References

1. [Processes and Threads](https://learn.microsoft.com/en-us/windows/win32/procthread/processes-and-threads)
2. [Processor Groups](https://learn.microsoft.com/en-us/windows/win32/procthread/processor-groups)
3. [Scheduling Priorities](https://learn.microsoft.com/en-us/windows/win32/procthread/scheduling-priorities)
4. [Waiting for Multiple Objects](https://learn.microsoft.com/en-us/windows/win32/sync/waiting-for-multiple-objects)
5. [About Services](https://learn.microsoft.com/en-us/windows/win32/services/about-services)
