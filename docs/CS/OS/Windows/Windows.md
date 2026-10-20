## Introduction

Windows 不是一个操作系统，而是**两条不同支线在一次合并之后的一大家子**。第一条支线从 MS-DOS 出发，Windows 1.0（1985 年 11 月 20 日）最初只是套在 DOS 外面的图形界面壳，Windows 95/98/ME 一路把它加厚；第二条支线是 1993 年从零开发的 **Windows NT**（NT 即 New Technology），一开始就没打算跑在 DOS 上面。两条线在 2001 年的 Windows XP 那里合流——此后的 Windows 全部是 NT。

理解这条历史很有必要，因为它解释了一件事：**为什么 Windows 上今天还能见到盘符、`con`/`nul` 这些设备名、`\\.\pipe\` 这种路径写法、以及那些既不 Unix 也不 DOS 的古怪约定**。它们不是设计出来的冗余，而是两套世界观在同一台机器上共存留下的接缝。

本节的目标是给 Windows 子树做一张导航地图：先摆出**版本时间线**（这是所有 Windows 文档里最容易写错的部分），再看 **NT 的整体结构**那一张纵向切面，然后按"结构 → 进程线程 → 内存 → 启动 → I/O → 存储 → IPC → 安全"这条顺序把全部笔记串起来，最后给出 Windows 的开源参照实现与日常工具。

---

## Version Timeline: The Number That Matters

Windows 的市场名（Windows 11）与内核版本号（NT 10.0）是两个不同的东西。这里给出核实过的对应关系：

| 发布 / 产品 | NT 版本 | OS build | 年份 |
| :-- | :-- | :-- | :-- |
| Windows NT 3.1 | 3.1 | — | 1993 |
| Windows NT 3.5 / 3.51 | 3.5 / 3.51 | — | 1994 / 1995 |
| Windows NT 4.0 | 4.0 | — | 1996 |
| Windows 2000 | 5.0 | — | 1999 |
| Windows XP | 5.1 | — | 2001 |
| Windows Server 2003 / XP x64 | 5.2 | — | 2003 |
| Windows Vista / Server 2008 | 6.0 | — | 2006 |
| Windows 7 / Server 2008 R2 | 6.1 | — | 2009 |
| Windows 8 / Server 2012 | 6.2 | — | 2012 |
| Windows 8.1 / Server 2012 R2 | 6.3 | — | 2013 |
| Windows Server 2016 | 10.0 | 14393 | 2016 |
| Windows Server 2019 | 10.0 | 17763 | 2018 |
| Windows Server 2022 | 10.0 | 20348 | 2021 |
| Windows Server 2025（当前 LTSC） | 10.0 | 26100 | 2024 |
| Windows 11 24H2 | 10.0 | 26100 | 2024 |
| Windows 11 25H2 | 10.0 | 26200 | 2025 |
| Windows 11 26H2 | 10.0 | 26300 | 2026 |

> [!NOTE]
>
> **两条通道可以并存**
>
> Windows Server 有 LTSC（长期服务通道）与 Annual Channel（年度通道）两条发布线，桌面侧也有 26H1（OS build 28000）与 26H2（OS build 26300）这样的并行存在。判断某台机器的实际版本，**请以 `winver` 与 [release health](https://learn.microsoft.com/en-us/windows/release-health/windows11-release-information) 页面为准，而不是猜 Windows 支线名**。

Windows NT 之后的版本号本身不再用于市场营销，只在 API（`GetVersionEx`、`RtlGetVersion`）与驱动 INF 里可见。INF 里的 `NTMajorVersion`/`NTMinorVersion` 使用的正是上表那两个数字的组合。

---

## The NT Shape: One Vertical Slice

NT 的纵向结构可以用一句话说完：**硬件抽象层之上是微内核，微内核之上是执行体，旁边挂着一整片设备驱动，以及与 API 的那个边界在用户态的子系统 DLL 上面。**

更精确的表述是：

- 微软在 HAL（硬件抽象层，Hardware Abstraction Layer）之上定义了一个**小内核（Kernel）**，它只负责 CPU 上的三件事：**线程调度、中断与异常分发、同步与延迟机制**；
- HAL 存在的意义是**换硬件不必改内核**：只要为某个平台提供对应的 HAL，同一套 NT 内核就能跑起来，这是 NT 早年能横跨 x86、Alpha、MIPS、PowerPC、IA-64 的原因，也是今天 ARM64 上的 Windows 能存在的前提；
- 小内核之上是各种内核组件，微软称之为**执行体（Executive）**：进程与线程管理、内存管理、配置管理、I/O 与文件缓存、即插即用、电源、安全等服务各成一块；
- 执行体各端之间**互相独立**，只对外提供接口，其它组件必须通过内核模式可调用接口请求其服务——它们之间不是可以随意互调内部结构的那种关系；
- 所有的设备驱动和文件系统都由 **I/O 管理器**统一管理：驱动可以堆叠成 **I/O 设备栈**，功能请求被封装成 **IRP**，在栈中一层层流动处理。Windows 引以为傲的图形子系统（窗口管理器与 GDI）历史上也处在内核中。

这就是 Windows 常被称为**混合内核**的原因：它借鉴了 Mach 式"微内核 + 用户态服务"的分层理念，却把文件系统、网络栈、图形、驱动这些性能敏感的组件全部放进了 Ring 0。这条取舍的完整讨论见 [OS](/docs/CS/OS/OS.md)。

---

## Map of This Section

下面按一条由里到外的阅读顺序把这节的笔记串起来。它同样也是 NT 的自下而上构造顺序：先把机制搭起来，再回答它们的分派问题——谁跑、分给谁多少资源、按什么次序。

### Structure First

[Windows 架构](/docs/CS/OS/Windows/Architecture.md) 是入口。它回答"为什么要有 HAL"、"统一对象管理器是什么"、"[注册表](/docs/CS/OS/Windows/Architecture.md) 为什么是 hive 而不是文本文件"、以及一次 `CreateFileW` 从 kernel32 到 SSD 的完整路径。读完它，剩下的每一篇都能找到自己的位置。

### Execution: Processes, Threads and Their Cost

有了 executive 之后，第一件事是把"谁可以跑"搞清楚。[进程与线程](/docs/CS/OS/Windows/Process_Thread.md) 讲 NT 的 32 级优先级模型、量子与前台提升、处理器组、APC/DPC、以及 IRQL 这条比线程优先级更硬的规则。它是理解"为什么我的程序在 Windows 上比 Linux 上更不响应"的基础。

### Address Space and Its Ledger

[Windows 内存管理](/docs/CS/OS/Windows/Memory.md) 讲两个 Windows 味很重的东西：**VAD 树**与**提交额度（commit charge）**。前者是 Windows 版的 VMA 描述符树，后者解释了"明明还有 20 GB 空闲内存却申请不到"这个经典现象。

### Getting There: Boot

把上面这些机制全部串起来的机会只有一次，就是开机。[Windows 启动流程](/docs/CS/OS/Windows/Boot.md) 按阶段走一遍 UEFI/BIOS → bootmgr → winload → ntoskrnl → smss → csrss/wininit → services/lsass/winlogon。它也解释 **BCD** 为什么是一个 registry hive，以及为什么 Secure Boot 是 Windows 安全体系的真正起点。

### I/O, Storage and the Stack

Windows 的 I/O 主张一切都对着某个"文件对象"发生，一切都默认可以异步：[Windows I/O 子系统](/docs/CS/OS/Windows/IO.md) 讲设备栈、IRP、四种异步模型与 I/O 完成端口（IOCP）——后者是 Windows 高并发的答案，也是理解 IOCP 与 epoll 差异的关键。

顺着 IRP 往下就是存储。[Windows 文件系统](/docs/CS/OS/Windows/FileSystem.md) 讲 NTFS 的 MFT 与元数据文件、四种链接/重解析点的区别、USN 日志与机会锁，以及 NTFS 与 ReFS 的官方边界——包括那条最要紧的限制：**Windows 系统卷目前仍必须是 NTFS**。

### Two Programs Talking

沟通的部分集中在 [Windows IPC](/docs/CS/OS/Windows/IPC.md)：共享内存、命名管道、邮件槽（正在被弃用）、RPC/COM、窗口消息、AF_UNIX，以及那条几乎没人手写但所有人都在用的 **ALPC**。

### Who May Do It

最后是所有判断汇总的地方：[Windows 安全模型](/docs/CS/OS/Windows/Security.md)。它讲 SID/令牌/安全描述符/DACL/SACL 这套**统一模型**，以及 UAC 的令牌分裂、强制完整性控制（MIC）、还有依赖 [Hyper-V](/docs/CS/OS/Windows/Architecture.md) 建立隔离环境的 VBS 家族。

### Working with Windows Every Day

要真正把这套系统用起来，还需要：命令行与 PowerShell（[CMD](/docs/CS/OS/Windows/CMD.md)）、这里的工具链与调试/观察装备（[Tools](/docs/CS/OS/Windows/Tools.md)）、以及与 Linux 共存的那套东西（[WSL](/docs/CS/OS/Windows/WSL.md)）。

---

## If You Want to Read It in Source

Windows 不开源，但有两个可以把上述绝大部分读出来的地方：

- **ReactOS** 是一个从零实现的、以二进制兼容 Windows 为目标的开源操作系统。它的自我介绍很朴素：能够运行 Windows 软件、能够运行 Windows 驱动、看起来像 Windows、并且自由且开源。因此它实际上是 Windows 内部机制最好的可公开阅读的参照实现。
- **Windows Research Kernel（WRK）** 与 **Sysinternals**（Process Explorer、Process Monitor、VMMap、`sigcheck` 等）是从外部观察那套机制的工具。

---

## Links

- [Windows 架构](/docs/CS/OS/Windows/Architecture.md)
- [Windows 进程与线程](/docs/CS/OS/Windows/Process_Thread.md)
- [Windows I/O 子系统](/docs/CS/OS/Windows/IO.md)
- [Linux](/docs/CS/OS/Linux/Linux.md)
- [操作系统总纲](/docs/CS/OS/OS.md)
- [macOS / Darwin](/docs/CS/OS/mac/mac.md)

---

## References

1. [Windows 11 release information](https://learn.microsoft.com/en-us/windows/release-health/windows11-release-information)
2. [Windows Server release information](https://learn.microsoft.com/en-us/windows-server/get-started/windows-server-release-info)
3. [Operating System Version](https://learn.microsoft.com/en-us/windows/win32/sysinfo/operating-system-version)
4. [ReactOS](https://reactos.org/what-is-reactos/)
5. [Windows Internals（7th Edition）Parts 1 & 2](https://learn.microsoft.com/en-us/sysinternals/resources/windows-internals)
