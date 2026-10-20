## Introduction

如果说 NT 架构里有一处最能体现"统一"这个词的代价与收益，那就是 I/O。Linux 把 I/O 分成三拨 API：`read/write`、`mmap`、`io_uring`，驱动作者面对 bio、request、`net_device` 等好几套互不相干的模型；Windows 则坚持三件事：

1. **一切 I/O 都对着某个"文件对象"发生**。键盘、磁盘、命名管道、网络 socket、[邮件槽](/docs/CS/OS/Windows/IPC.md)，在 I/O 管理器眼里都是可以被 `ReadFile`/`WriteFile` 操作的对象。因此 `DeviceIoctrlControl` 这个通用逃生舱承担了所有没法塞进读写的语义；
2. **一切 I/O 默认可以被异步化**。请求装入 IRP（I/O Request Packet），沿设备栈向下流经各层驱动，完成后回落。同步读写只是"发起后立刻等待"的特例；
3. **驱动程序按栈组织，而不是按"子系统"组织**。过滤驱动可以挂在任意一层之间，这是杀毒、数据加密、快照、容器存储的实现基础。

本文按请求的生命周期推进：先看**设备栈怎么搭起来**，再看 **IRP 如何流动**，然后是 Windows 的四种异步模型（重点是 I/O 完成端口），接着是**驱动模型的发展脉络**、**即插即用与电源**，最后落到**内核缓存管理器**——它决定了"我到底碰到了磁盘没有"。

---

## Device Objects, Driver Objects, File Objects

三个 `OBJECT_HEADER` 后面的对象构成了 Windows 设备管理的骨架：

| 对象 | 创建者 | 含义 |
| :-- | :-- | :-- |
| Driver Object（驱动对象） | I/O 管理器，加载驱动时 | 一个已加载驱动的实例，其最主要的内容是**一个分派函数指针数组**（对应 `IRP_MJ_*` 各功能码） |
| Device Object（设备对象） | 驱动自己调用 `IoCreateDevice` | 驱动对外暴露的一个 I/O 目标，可以是物理设备、逻辑卷，也可以纯软件 |
| File Object（文件对象） | 对象管理器在打开时创建 | 一次打开的实例：读写偏移、同步状态、与之绑定的完成端口都在这里 |

这三者的关系解释了 Windows 的一个常见困惑：**同一个磁盘设备上可以有成百上千个文件对象**，每个持有各自的偏移与访问权限；而设备对象只有一个栈。

多个设备对象可以**垂直堆叠**成设备栈：`\Device\HarddiskVolume1` 的栈自上而下可能依次是 volume manager → disk class driver → disk miniport driver → bus driver。上层的设备对象通过堆叠关系把 IRP 交给下层，一层层 `IoCallDriver` 下去。

> [!NOTE]
>
> **为什么要"堆叠"而不是"调用"**
>
> 因为在 Windows 里，**插入一层过滤驱动不需要下层知情**。一个加密过滤驱动挂在这条栈中间，上下都不知道它的存在。这就是 BitLocker、杀毒软件实时扫描、卷影复制（VSS）的实现方式，也是 Windows 上"某个过滤驱动出问题，整个磁盘不工作"的根因——它挡在所有 IRP 的必经之路上。

---

## IRP: The Unit of Work

**I/O Request Packet（IRP）**是一个内核结构体，代表"一件事"。它的旅程如下：

```text
应用 CreateFile/ReadFile
  → I/O 管理器分配 IRP，填入主功能码（IRP_MJ_READ 等）
  → 顶层设备对象的 DriverObject 分派函数被调用
  → 该层驱动调用 IoCallDriver 交给下层（或自行完成）
  → …… 一直到最底层的真实驱动
  → 真实驱动通常不在这里等待，而是排队给设备并立即返回 STATUS_PENDING
  → 设备中断 → ISR → DPC（见进程与线程篇）
  → 调用 IoCompleteRequest，逐层调用各层注册的完成例程
  → 最终由 I/O 管理器把结果写回发起者的 OVERLAPPED 结构、释放 IRP
```

主功能码决定请求类型，`IRP_MJ_*` 里最常用的几个：

| 功能码 | 用途 |
| :-- | :-- |
| `IRP_MJ_CREATE` / `CLOSE` | 打开、关闭文件对象 |
| `IRP_MJ_READ` / `WRITE` | 数据读写 |
| `IRP_MJ_DEVICE_CONTROL` | 设备私有命令（`DeviceIoControl` 的内核形态） |
| `IRP_MJ_INTERNAL_DEVICE_CONTROL` | 驱动之间的私有命令 |
| `IRP_MJ_PNP` / `IRP_MJ_POWER` | 即插即用与电源 |

**要点：IRP 流动的方向与完成的方向是相反的。** 向下驱动们做"准备"工作（例如把地址转换成分区偏移），向上完成例程做"收尾"工作（例如累加统计、把 I/O 完成投递到发起线程）。写驱动时最容易出错的正是这个双向流程。

除了 IRP，还有一条旁路值得一提：**Fast I/O** 允许文件系统在缓存已命中时跳过 IRP 分配、直接完成请求。这是"抽象与性能之争"在驱动内部的具体表现——见 [OS](/docs/CS/OS/OS.md) 里的第一条设计张力。

---

## Four Asynchronous Models

Windows 提供四种组合，复杂度与能力递增：

| 模型 | 发起方式 | 等待方式 | 适用规模 |
| :-- | :-- | :-- | :-- |
| 同步等待 | `ReadFile(h, ...)` | 调用线程阻塞 | 单个流、脚本、命令行工具 |
| 重叠 I/O + 事件 | `ReadFile(h, &ov, ...)`，ov.hEvent 有值 | `WaitForSingleObject(ov.hEvent)` | 少量并发操作 |
| 重叠 I/O + 完成例程 | `ReadFileEx`，传回调 | 线程进入**可警告等待**后由 APC 调用回调 | 中等并发，不想自己管线程池 |
| I/O 完成端口 | 句柄关联到完成端口 | `GetQueuedCompletionStatus` | 高并发服务器（数千连接） |

第三种的完成例程是靠 [APC](/docs/CS/OS/Windows/Process_Thread.md) 投递的——这解释了为什么它要求线程处在**可警告等待**状态（`SleepEx`/`WaitForSingleObjectEx` 且最后一个参数为 TRUE）：不给 APC 插入点，回调就永远不会被执行。

### I/O Completion Ports in Detail

完成端口（IOCP）是 Windows 对高并发的回答，也是 NT 里设计得最干净的东西之一。关键在于它**把"有几条 wait 队列"这件事从每个句柄变成了每个进程一个**：

1. `CreateIoCompletionPort(FileHandle, ExistingCompletionPort, CompletionKey, NumberOfConcurrentThreads)`：既创建端口、又把某个支持 overlapped 的句柄关联上去（`CompletionKey` 通常用来标识这条连接属于谁）；
2. 关联的句柄发起异步操作完成时，一个完成包以 **FIFO 顺序**入队；
3. 线程调用 `GetQueuedCompletionStatus` 取包。**等待线程被唤醒的顺序是 LIFO**——最近才等待的那个线程先拿到包，这样可以让刚跑完、缓存还热的线程继续干活，减少上下文切换；
4. `NumberOfConcurrentThreads` 限制的是**同时可运行的线程数**：达到上限后，多余的线程即使有包也不会被放行，直到运行中的线程再次进入等待。

两条实践里的经验值来自官方文档：并发值取 **CPU 数量**通常最优；线程池里的线程数至少是 CPU 数的**两倍**——因为某个处理线程可能因为别的原因被挂起，需要别人顶上。

> [!TIP]
>
> **IOCP 的三个常被忽略的细节**
>
> - `PostQueuedCompletionStatus` 允许往队列里塞自定义包。这使它不只是 I/O 机制，而是一个**通用的任务分发/唤醒原语**——很多 Windows 服务器框架的用户态任务队列就是用它实现的。
> - 完成端口**归属于创建它的进程，不跨进程共享**；同一个进程内的多个线程可以共享同一个句柄。
> - 一个线程第一次调用 `GetQueuedCompletionStatus` 之后就**永久与该端口绑定**，直到线程退出、改绑别的端口或关闭该端口。不能"借用"别的线程池的线程来取包。
>
> 因此 IOCP 与线程模型是强耦合的。现代写法通常直接用线程池 API（`CreateThreadpoolIo` / `StartThreadpoolIo`）——它们在内部使用 IOCP，但替你管线程生命周期。

与 Linux 的对照：

| 维度 | Windows IOCP | Linux epoll / io_uring |
| :-- | :-- | :-- |
| 通知内容 | 已完成的数据（completion based） | epoll：就绪通知（readiness based）；io_uring：完成模型 |
| 唤醒策略 | FIFO 队列 + LIFO 线程唤醒（保持缓存热度） | epoll 无内建线程管理；io_uring 视是否启用 SQPOLL 而定 |
| 并发控制 | 内建 `NumberOfConcurrentThreads` 上限 | 由应用层自己设计 |
| 自定义通知 | `PostQueuedCompletionStatus` | eventfd（epoll）/ 无（io_uring） |

这张表里最值得注意的区别是 **completion vs readiness**：Windows 从第一天起告诉你的就是"这件事已经干完了"，而 epoll 只是告诉你"现在可以开始干活"。这就是为什么 Windows 上的服务器代码往往比等价的 epoll 代码短——中间那一层"读到一半怎么办"的状态机由内核承担了。

---

## Driver Models: From WDM to WDF

写 Windows 驱动有三套并存的做法，务必分清：

| 模型 | 年代 | 特点 |
| :-- | :-- | :-- |
| **WDM**（Windows Driver Model） | 1990 年代起 | 直接面向 IRP：自己处理每个功能码、自己管 PnP 与电源 IRP、自己保证 IRQL 纪律。灵活但极易出错 |
| **WDF / KMDF**（内核态驱动框架） | Windows Vista 起 | 把 WDM 的那些样板封装成"对象 + 事件回调"模型：WDFDEVICE、WDFREQUEST、PnP/Power 状态机由框架托管。今天的推荐起点 |
| **UMDF**（用户态驱动框架） | Vista 起 | 驱动本体跑在**用户态**进程里，崩溃不会 BSOD。适合协议设备、生物识别、打印类不需要深 DMA 的设备 |

三条今天依然成立的共识：

- **PnP 与电源请交给框架**。手写这两个状态机是历史上 WDM 驱动 BSOD 的最大来源；
- **IRQL 纪律没有框架替你兜底**（复习 [进程与线程](/docs/CS/OS/Windows/Process_Thread.md) 里的 IRQL 一节）；
- 现代 Windows 要求驱动签名，Safe Boot / VBS 环境下还要满足 **HVCI**（基于虚拟化的代码完整性）的兼容要求。

### Filters and Where They Sit

| 过滤形态 | 位置 | 典型用途 |
| :-- | :-- | :-- |
| 文件系统 mini-filter | filter manager 之下 | 杀毒实时扫描、加密、快照、云分层存储 |
| 磁盘/卷类过滤 | 类驱动上下 | 镜像、差分磁盘、BitLocker |
| NDIS / WFP | 网络栈 | 防火墙、VPN、抓包过滤 |
| 注册表回调 | 配置管理器 | 行为监控、EDR |

**这是理解"为什么 Windows 上的安全软件比其他系统侵入性更强"的关键**：任何想看见系统里正在发生什么的程序，都只能把自己插到 IRP 的必经之路上。这条路径的可靠性因此直接影响整机稳定性，微软才会逐步把这类能力收进 VBS 与隔离用户模式（IUM）那样的受控通道，而不是继续让任意驱动自由堆叠。

---

## PnP and Power

即插即用管理器与电源管理器是与 I/O 管理器协作的一对执行体组件：

- **设备树（device tree）**：I/O 管理器看到的设备按总线关系组成一棵树，节点上的实例 ID 用于把注册表里的配置与具体硬件实例绑在一起；
- **PnP IRP**：设备的插入、拔出、资源再平衡都以 `IRP_MJ_PNP` 的形式流过设备栈，各层驱动负责释放或重新申请自己的资源；
- **电源 IRP**：系统状态（S0 工作、S3/S4 睡眠/休眠、S5 关机）与设备状态（D0 全速 … D3 关闭）之间有映射，驱动要做的是在收到降级请求时保存上下文并断电；
- **Modern Standby**：与传统 S3 不同，它保持联网、保持部分后台活动——本质上是"S0 低功耗"，对驱动的要求完全不同（不能假设 CPU 已停）。

---

## Cache Manager: Did I Really Hit the Disk?

缓存管理器替文件系统维护一张**按文件组织**的缓存，与 [内存管理](/docs/CS/OS/Windows/Memory.md) 共享同一套物理页账本。应用侧有三个日常必知的开关：

| 标志 | 含义 |
| :-- | :-- |
| 默认 | 读写经过缓存管理器，**可能**碰盘也可能不碰 |
| `FILE_FLAG_NO_BUFFERING` | 绕过缓存，直接下发到设备。要求缓冲区、偏移、长度都按扇区对齐 |
| `FILE_FLAG_WRITE_THROUGH` | 仍用缓存，但写操作在确认返回前必须落盘 |
| `FILE_FLAG_SEQUENTIAL_SCAN` / `RANDOM_ACCESS` | 给缓存管理器的预读提示 |

> [!WARNING]
>
> **`NO_BUFFERING` 是有对齐代价的**
>
> 它不只是"关掉缓存"那么简单：缓冲区起始地址、偏移、长度都必须对齐（通常按卷扇区大小，常见 512 B / 4 KB），否则 `ReadFile` 会以 `ERROR_INVALID_PARAMETER` 失败。数据库引擎往往自建缓冲池来管理这块内存——用它就等于自己接管页置换策略，同时也接管了全部对齐责任。

此外还有一条常被遗忘的通路：**内存映射文件的刷新**。用 `MapViewOfFile` 写过的页，要 `FlushViewOfFile` 之后再 `FlushFileBuffers` 才能保证持久化——只调后者是不够的。

---

## Links

- [Windows 架构](/docs/CS/OS/Windows/Architecture.md)
- [Windows 进程与线程](/docs/CS/OS/Windows/Process_Thread.md)
- [Windows 文件系统](/docs/CS/OS/Windows/FileSystem.md)
- [Windows IPC](/docs/CS/OS/Windows/IPC.md)
- [Windows 安全模型](/docs/CS/OS/Windows/Security.md)
- [I/O 多路复用](/docs/CS/OS/IO.md)

---

## References

1. [I/O Completion Ports](https://learn.microsoft.com/en-us/windows/win32/fileio/i-o-completion-ports)
2. [Synchronous and Asynchronous I/O](https://learn.microsoft.com/en-us/windows/win32/fileio/synchronous-and-asynchronous-i-o)
3. [File Caching](https://learn.microsoft.com/en-us/windows/win32/fileio/file-caching)
4. [Windows Driver Frameworks Documentation](https://learn.microsoft.com/en-us/windows-hardware/drivers/wdf/)
5. [Windows Filtering Platform](https://learn.microsoft.com/en-us/windows/win32/fwp/windows-filtering-platform-start-page)
