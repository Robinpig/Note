## Introduction

Windows NT 是理解整个 Windows 家族的地基：从 1993 年的 NT 3.1，到今天的 Windows 11 与 Windows Server 2025，中间换过无数次界面、无数次市场定位，底层那套架构始终没有被推倒重来。一句 `dir` 从 Windows 95 敲到今天还是同一个字母序列，背后却是两套不同的东西：Windows 95 那一支是套在 DOS 外面的图形壳，NT 这一支从第一天就是独立设计的 32 位内核。

NT 的设计有三个一以贯之的想法，后面每个子系统都能追溯到其中之一：

1. **可移植性优先**：内核不直接碰硬件，硬件差异被收拢到硬件抽象层（Hardware Abstraction Layer，HAL）。同一份内核源码要在 x86、Alpha、MIPS、PowerPC、IA-64、x64、ARM64 上跑，就得先把"怎么开一个中断控制器""怎么刷 TLB"这类问题抽成一层接口。
2. **统一对象模型**：进程、线程、文件、事件、互斥量、区段（section，即共享内存）、注册表键——全部是"内核对象"，由同一个对象管理器（Object Manager）负责命名、引用计数、权限校验与生命周期。
3. **子系统与接口分层**：Win32 不是唯一的 API 世界。NT 允许多个环境子系统并存，各自实现自己的 API 语义，再翻译成 NT 的原生服务。

理解这三条，剩下的结构问题就都有了答案：**执行体为什么分成那么多彼此独立的服务？** 因为它们共享的对象规则由对象管理器统一提供，彼此之间只要走内部接口；**为什么驱动生态和 Linux 差别这么大？** 因为设备栈从上到下由 I/O 管理器统一组织，见 [Windows I/O](/docs/CS/OS/Windows/IO.md)；**为什么配置散落在注册表而不是文本文件？** 这是第三条设计在配置面的投影，见下文「Configuration Plane」。

本文按从外到内的顺序推进：先看**分层与边界跨越**，再看用户态的**系统进程拼图**，接着是内核态的**执行体与微内核**，然后是贯穿两者的**对象管理器与句柄**、**注册表 hive**、**系统调用路径**，最后与 Linux 做一张结构对照。

---

## Layering: User Mode and Kernel Mode

NT 的分层不像 OSI 那样严格垂直，更像是"三层加一个必经隘口"：

| 层次 | 主要组件 | 特权 | 说明 |
| :-- | :-- | :-- | :-- |
| 用户态进程 | 应用、服务（svchost、services.exe） | Ring 3 | 各自独立地址空间，通过子系统 DLL 调 API |
| 子系统 DLL | kernel32.dll、user32.dll、advapi32.dll | Ring 3 | 实现 Win32 / WinRT / CRT 语义，是**文档化的 ABI 边界** |
| 原生接口 DLL | ntdll.dll | Ring 3 | 未文档化的 NT 原生存根，最后一段用户态代码 |
| 内核态执行体 | ntoskrnl.exe（Executive 部分） | Ring 0 | 对象管理器、进程与线程、内存、I/O、缓存、安全等执行服务 |
| 内核（微内核） | ntoskrnl.exe（Kernel 部分） | Ring 0 | 线程调度、中断与异常分发、同步原语、DPC |
| 设备驱动 | .sys，WDM / WDF | Ring 0 | 见 [Windows I/O](/docs/CS/OS/Windows/IO.md) |
| HAL | hal.dll | Ring 0 | 屏蔽中断控制器、定时器、DMA、缓存一致性等硬件差异 |

ntdll.dll 是最后的隘口：`NtCreateFile` 这类函数体通常只有三五条指令——把系统调用号放进寄存器，执行 `syscall`（x64）或 `svc`（ARM64）陷入内核。上面那些子系统 DLL 提供的是全部的语义包裹：**Win32 的路径分隔符转换、ANSI 与宽字符转换、NTSTATUS 到 `GetLastError()` 的翻译**都发生在这一层，内核内部并没有"Win32"这个概念。

> [!NOTE]
>
> **API 边界不等于系统调用边界**
>
> `CreateFileW` 不是系统调用，它是 kernel32 提供的、承诺长期稳定的 ABI。内核看到的只有 `NtCreateFile`。微软可以重构 kernel32 的内部实现而不破坏任何应用，却几乎永远不会改动 ntdll 存根的编号顺序。
>
> 这也是 Wine 与 ReactOS 这类项目能够存在的原因：它们的任务是重新实现上面那三层 DLL 的语义，而不是复刻内核。

---

## User-Mode Side: The System Process Puzzle

Windows 用户态没有"一个 init 进程"这样的单点，而是一组分工明确的系统进程。Linux 里 PID 1 是一个诚实的起点，Windows 上要从 **session** 说起：开机后第一批进程运行在 **Session 0**（服务会话），用户登录后才创建 Session 1、2……这套结构源于 Windows Vista 的服务强化，是 [Windows 安全模型](/docs/CS/OS/Windows/Security.md) 的一部分。

| 进程 | 所在会话 | 职责 |
| :-- | :-- | :-- |
| `smss.exe` | Session 0 | Session Manager：最早的**用户态**进程，建立会话、加载其余子系统进程、初始化 registry hive |
| `csrss.exe` | 每个会话一个 | Client/Server Runtime Subsystem：Win32 环境的用户态服务端，管理控制台窗口、进程与线程表的用户态副本、关机流程 |
| `wininit.exe` | Session 0 | 拉起 `services.exe`、`lsass.exe`、`winlogon.exe`，掌管 Session 0 的整体生命周期 |
| `services.exe` | Session 0 | 服务控制管理器（Service Control Manager，SCM）：持有服务数据库，负责启动、依赖排序、失败重启 |
| `lsass.exe` | Session 0 | Local Security Authority：认证、令牌签发、本地安全策略；也是 Credential Guard 这类 VBS 方案的保护目标 |
| `winlogon.exe` | 每个交互会话 | 处理 SAS（Ctrl+Alt+Del）、驱动凭证 provider、创建用户会话 |
| `explorer.exe` | 每个交互会话 | Shell。它是可被替换的：换一个 Shell 并不需要改内核 |

`svchost.exe` 值得单独说一句：它不是某一种服务，而是**承载 DLL 形式服务的宿主进程**。十几个同名的 `svchost.exe` 各自加载一组 DLL，按服务组分桶隔离。这条设计的目的不是性能，而是**故障与权限隔离**——某个服务崩溃不必拖垮同类，也不必让每个服务独占一份进程开销。

### Environment Subsystems: Then and Now

NT 最早同时提供四个环境子系统：Win32、OS/2、POSIX 以及安全子系统。它们各自暴露一套 API，内核并不知道"Win32 长什么样"。这条设计的命运很能说明 Windows 的路径取舍：

- **OS/2 子系统**随微软与 IBM 的分道扬镳而消失；
- **Microsoft POSIX subsystem**只实现 1990 年版 POSIX.1（不含线程与 socket），后被 Interix 与 Windows Services for UNIX（SFU）接替；
- 更名后的 **SUA**（Subsystem for UNIX-based Applications）在 Windows Server 2012 被弃用、Server 2012 R2 起移除，官方迁移建议是 Hyper-V 虚拟化、Cygwin，或 MinGW 原生移植；
- 今天补位的是 [WSL](/docs/CS/OS/Windows/WSL.md)——WSL 2 直接在一个托管虚拟机里跑真正的 Linux 内核，不再做"API 翻译"这件事。

这条线索是 Windows 对「抽象 vs. 能力」的最终回答：**与其维护一个永远追不上 Linux 内核的翻译层，不如把 Linux 内核本身跑起来。**

---

## Kernel-Mode Side: Executive and Kernel

Windows 常被描述为"混合内核"：它借鉴了 Mach 式的微内核理念（一个小内核处理调度与 IPC，其余做成服务），但在实现上把文件系统、网络栈、设备驱动、图形子系统这些性能关键组件放进了 Ring 0。这不是理论不彻底，而是明确的工程取舍，对照见 [OS](/docs/CS/OS/OS.md) 里宏内核与微内核一节。

`ntoskrnl.exe` 这个单一映像内部清楚地分成两块：

### Executive: The Service Layer

执行体是"NT 实际的操作系统"，由一组相对独立、互相只通过内部接口通信的组件构成：

| 组件 | 职责 |
| :-- | :-- |
| 对象管理器 | 内核对象的命名、句柄、引用计数、ACL 校验（下文专节） |
| 进程与线程管理器 | EPROCESS/KPROCESS、ETHREAD/KTHREAD 的创建与销毁，见 [进程与线程](/docs/CS/OS/Windows/Process_Thread.md) |
| 内存管理器 | 地址空间、工作集、提交与页文件，见 [Windows 内存管理](/docs/CS/OS/Windows/Memory.md) |
| I/O 管理器 | 设备栈、IRP、驱动模型，见 [Windows I/O](/docs/CS/OS/Windows/IO.md) |
| 缓存管理器 | 基于文件的统一缓存，与进程地址的最新管理共用同一套物理页账本 |
| 配置管理器 | 实现注册表，见下文 |
| 安全引用监视器（SRM） | 内核态的访问控制执行点，是"这个操作到底有没有权限"的唯一答案所在，见 [Windows 安全](/docs/CS/OS/Windows/Security.md) |
| 即插即用管理器 / 电源管理器 | 设备枚举、驱动装载排序、ACPI 电源状态转换 |
| ALPC | 本机过程调用，进程之间的高速消息通道，见 [IPC](/docs/CS/OS/Windows/IPC.md) |
| Win32k | 窗口管理与图形系统的内核部分（窗口对象、GDI 对象、DirectX 内核通道） |

这些组件之间没有内存保护——它们共享同一个内核地址空间，一次越界写入就是 BSOD。这是 Windows 用可靠性换性能的那枚硬币的另一面。

### Kernel: Scheduling and Dispatching

真正被称为 Kernel 的那部分要小得多，职责集中在三条：**线程调度与上下文切换**、**中断与异常分发**、**同步原语与延迟机制**（自旋锁、分发器对象、DPC）。

NT 里 **IRQL**（Interrupt Request Level）是这套机制的骨架：同一条 CPU 上谁先执行，先不看线程优先级，先看 IRQL。只要 IRQL 达到 DISPATCH_LEVEL，线程调度就不会发生。这条规则决定了内核里"什么代码绝对不能做什么"——在 DISPATCH_LEVEL 及以上不能等待、不能触碰分页内存、不能访问用户态地址。IRQL 与 APC、DPC 的完整展开见 [进程与线程](/docs/CS/OS/Windows/Process_Thread.md)。

### HAL: The Portability Seam

HAL（`hal.dll`）把中断控制器、系统时钟、DMA 一致性、多处理器启动这些与机器强相关的操作收成一组内核可调用的接口。它的存在是 NT 早年能横跨 Alpha、MIPS、PowerPC、IA-64 的原因；今天 ARM64 上 Windows 能跑，同样归功于这层接缝。

不过现代 Windows 里，HAL 已经不是"给新机器写一份 HAL"那条原始设想那么简单了：它与 `ntoskrnl.exe` 构成一套配套发布的映像对，硬件支持更多通过 ACPI 表、驱动与 UEFI 接口扩展进来。

---

## Object Manager and Handles

对象管理器是 NT 最有标识性的设计。Linux 里"文件描述符、PID、System V IPC key、pthread 句柄"是四套互不相干的命名方式；NT 里它们全部归一：

- **每个对象都有类型（Type object）**，类型定义这个对象支持的操作集、可否等待、可否跨进程继承、计费配额与默认 ACL；
- **对象管理器维护一棵命名空间树**，根是 `\`，下有 `\ObjectTypes`、`\Global??`、`\Device`、`\Driver`、`\BaseNamedObjects` 等目录。磁盘上的文件也经由它进入——`C:` 只是符号链接，最终指向 `\Device\HarddiskVolumeN`；
- **句柄是 per-process 句柄表的索引**。同一个对象在不同进程里索引值可能不同；把句柄交给别的进程只有三条合法路径：继承、`DuplicateHandle` 显式复制，或由服务代为打开；
- **对象由引用计数保活**，引用来自两处：内核指针与用户句柄。句柄关了但内核指针还在，对象就不销毁——这正是许多"文件删不掉、DLL 卸不下来"的根因。

从内核视角看，打开 `C:\Windows\System32\drivers\etc\hosts` 这类路径的完整形态是：

```text
\Global??\C:\Windows\System32\drivers\etc\hosts
```

`\??` 是 `\Global??` 的历史别名，后者把盘符 `C:` 指向某个 `\Device\HarddiskVolumeN`。用 Sysinternals 的 WinObj 可以直接看到这棵树，这是理解 Windows 命名体系最快的方式。

---

## Configuration Plane: Registry Hives

Windows 把系统配置放进一个专用的**数据库**而不是散落的文本文件。Linux 那边 `/etc` 下是几百个格式互异的文件，Windows 这边是若干 **hive（配置单元）**：一个 hive 是一组键、子键与值的逻辑集合，由一组对应的支持文件作为 backing store，在系统启动或用户登录时载入内存。

| 根键 | 缩写 | 内容 |
| :-- | :-- | :-- |
| `HKEY_LOCAL_MACHINE` | HKLM | 整机范围的配置，含 SAM、SECURITY、SOFTWARE、SYSTEM 四个子 hive |
| `HKEY_CURRENT_USER` | HKCU | 当前用户配置，实为 `HKEY_USERS\<SID>` 的链接 |
| `HKEY_USERS` | HKU | 所有已加载的用户 profile hive，外加 `.DEFAULT` |
| `HKEY_CLASSES_ROOT` | HKCR | COM 类注册与文件关联，由 HKLM\Software\Classes 与 HKCU\Software\Classes 合并生成 |
| `HKEY_CURRENT_CONFIG` | HKCC | 当前硬件配置，指向 HKLM\SYSTEM 下的硬件配置文件 |

hive 文件本身位于 `%SystemRoot%\System32\Config`（SYSTEM、SOFTWARE、SAM、SECURITY、DEFAULT），用户 hive 则是各自 profile 下的 `Ntuser.dat`。每个 hive 伴随一组日志与备份文件，扩展名含义如下：

| 扩展名 | 含义 |
| :-- | :-- |
| 无扩展名 | hive 数据的完整副本 |
| `.alt` | `HKEY_LOCAL_MACHINE\System` 的关键备份，只有 System 这一项有 |
| `.log` | hive 变更的事务日志 |
| `.sav` | hive 的备份副本 |

> [!WARNING]
>
> **注册表不只是"Windows 的 /etc"**
>
> 配置管理器是**内核组件**，注册表访问走系统调用而非文件读取；hive 的加载与卸载有专门的内核 API。因此"离线编辑另一台机器的注册表"必须先用 `reg load` 显式把 hive 挂进来，直接改写 `%SystemRoot%\System32\Config` 下那几个文件是行不通的——它们在运行中的系统上通常被内核独占打开。

---

## System Call Path

把上面这些拼起来，一次 `CreateFileW` 的完整路径是：

```text
应用 → kernel32!CreateFileW（路径规范化、参数校验）
     → ntdll!NtCreateFile（存根，系统调用号进寄存器）
     → syscall 指令：Ring 3 陷入 Ring 0，切到内核栈
     → 分发器按号查系统服务表 SSDT，进入 IoCreateFile
     → 对象管理器（名字解析 + ACL 校验）
     → 文件系统驱动 → 磁盘类驱动 → 磁盘小端口驱动
     → 返回 NTSTATUS → ntdll 翻译成 BOOL 与 GetLastError
```

这里有两个容易忽略但很要紧的事实：

- **返回值是 NTSTATUS**（如 `STATUS_ACCESS_DENIED`），Win32 层才会翻译成 `ERROR_*` 与布尔值。调试系统调用级问题时看到的那些十六进制状态码就是它；
- **名字解析在对象管理器里完成，而不是在文件系统里**。这意味着路径规范化、符号链接、`..` 的处理规则与 POSIX 那一套并不完全等价，跨 [WSL](/docs/CS/OS/Windows/WSL.md) 或经网络重定向器时尤其容易踩到差异。

---

## Comparison with Linux

| 维度 | Windows NT | Linux |
| :-- | :-- | :-- |
| 内核形态 | 混合内核：微内核的分层 + 宏内核的实现 | 宏内核 + 可加载模块 |
| 命名机制 | 统一对象管理器 + per-process 句柄表 | 多套并存的 id：fd / PID / IPC key / pthread_t |
| 配置存储 | 注册表（内核管理的事务化 hive） | `/etc` 下的纯文本文件 |
| 稳定边界 | 用户态 DLL（Win32）作为稳定 ABI，**系统调用号不承诺稳定** | glibc 之上的库符号长期稳定，**系统调用语义也不承诺** |
| 子系统扩展 | 环境子系统（历史上 OS/2、POSIX、SUA），现走 WSL 真内核 | namespace + syscall ABI |
| 纵向切面 | HAL → 微内核 → 执行体 → 驱动 → 子系统 DLL | arch/ → 核心 → 子系统 → glibc |

两边最终都走到同一个地方：**给用户一个稳定的库边界，内核内部可以随便改**。差别只是边界划在哪一层——Linux 划在系统调用之上，Windows 划在 Win32 DLL 之上。

---

## Links

- [Windows 进程与线程](/docs/CS/OS/Windows/Process_Thread.md)
- [Windows 内存管理](/docs/CS/OS/Windows/Memory.md)
- [Windows I/O 子系统](/docs/CS/OS/Windows/IO.md)
- [Windows 文件系统](/docs/CS/OS/Windows/FileSystem.md)
- [Windows IPC](/docs/CS/OS/Windows/IPC.md)
- [Windows 安全模型](/docs/CS/OS/Windows/Security.md)

---

## References

1. [Windows Server release information](https://learn.microsoft.com/en-us/windows-server/get-started/windows-server-release-info)
2. [Registry Hives](https://learn.microsoft.com/en-us/windows/win32/sysinfo/registry-hives)
3. [Predefined Keys](https://learn.microsoft.com/en-us/windows/win32/sysinfo/predefined-keys)
4. [Hyper-V virtualization in Windows Server and Windows](https://learn.microsoft.com/en-us/virtualization/hyper-v-on-windows/about/)
5. [Features deprecated starting with Windows Server 2012 R2](https://learn.microsoft.com/en-us/previous-versions/windows/it-pro/windows-server-2012-R2-and-2012/dn303411(v=ws.11))
6. [Windows Subsystem for Linux Documentation](https://learn.microsoft.com/en-us/windows/wsl/about)
