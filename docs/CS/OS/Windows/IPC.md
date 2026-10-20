## Introduction

进程间通信（IPC）在 Windows 上比 Linux 更"多"：Linux 那套 pipe / SysV 消息队列 / 共享内存 / socket 的组合已经算混乱了，Windows 还要加上 ALPC、COM、命名管道、邮件槽、窗口消息这几套各自成熟、各自有正当理由存在的机制。

为什么会这样？因为 Windows 的 IPC 不是一个"统一的、供两个进程互发数据的接口"，而是**四件不同的事被塞在了同一个词下面**：

1. 本机两块内存之间的数据共享（共享内存）；
2. 本机可信边界内的功能调用（ALPC/RPC/COM）；
3. 跨机器的远程调用（RPC/SMB/Sockets）；
4. 桌面 UI 语义上的协作（窗口消息、剪贴板、DDE）。

本文按微软官方给出的清单逐类看过一遍：先从**共享内存**这条最快的路径，再到**管道、邮件槽、RPC/COM、窗口消息、socket**，最后补上那条几乎所有 Windows 服务都在用、但几乎没人手写过的 **ALPC**，以及一张选型对照表。

---

## Nine Mechanisms at a Glance

微软官方把 Windows 支持的 IPC 机制列为九类：

| 机制 | 一句话用途 |
| :-- | :-- |
| Clipboard（剪贴板） | 交换格式协商的数据，最松耦合 |
| COM（组件对象模型） | 跨进程/线程的对象调用，OLE 的基础 |
| Data Copy（`WM_COPYDATA`） | 用窗口消息带一小段数据过去 |
| DDE（动态数据交换） | 老牌 IPC，已成历史包袱 |
| File Mapping（文件映射） | 多进程共享同一块内存，最快的本机共享 |
| Mailslots（邮件槽） | 单向、可做域内广播的短消息 |
| Pipes（管道） | 匿名管道（亲属进程）+ 命名管道（任意进程，可跨机经 SMB） |
| RPC（远程过程调用） | 函数级远程调用，兼容 OSF/DCE |
| Windows Sockets | 协议无关的网络接口，含本机与跨机 |

这张表本身就说明了问题：**"最合适"取决于你要的是哪一种 IPC**。想要速度选共享内存；想跨机器选 RPC 或 socket；想在一个谁也不认识谁的环境里被轻易找到，选命名管道。

---

## File Mapping: The Fastest Path

文件映射（file mapping）是 Windows 版的"把文件或页文件-backed 的一段 memory 映射到多个进程"。这就接上了 [内存管理](/docs/CS/OS/Windows/Memory.md) 里的区段对象：**共享内存与文件映射是同一个东西**。

- 映射到**系统页文件**的 section → 纯粹的 anonymous 共享内存；
- 映射到**磁盘上的文件** → 内存映射文件。

两个或多个进程用同一个名字打开同一个 file-mapping object，各自 `MapViewOfFile` 到自己的地址空间，物理页由管理器统一维护。

> [!WARNING]
>
> **它快，但没有任何同步语义**
>
> 文件映射给你的是裸内存。官方文档在这一点上说得毫不犹豫：多个进程访问同一个映射时必须自己用信标/互斥量之类的同步对象来防止数据竞争。
>
> 换句话说：**Windows 不会替你保证生产者/消费者顺序**。这类并发原语的讨论见 [并发与锁](/docs/CS/OS/Linux/Lock/README.md)。

### Pipe vs File Mapping

| 维度 | 文件映射 | 命名管道 |
| :-- | :-- | :-- |
| 数据方向 | 任意读写，双方都能改同一块内存 | 字节流或消息流，半双工/全双工取决于创建参数 |
| 通知 | 无，需额外同步对象 | 内建于读写语义（连接、读、写都可阻塞） |
| 跨机器 | **不能**（官方明确：只能本机） | 可以（经 SMB） |
| 典型场景 | 高频大数据交换、IPC 版 `mmap` | 服务与客户端的请求—响应、命名服务 |

---

## Pipes

### Anonymous Pipes

匿名管道只能用在**有亲缘关系的进程**之间（父进程创建子进程时把句柄传下去）。它的优点是便携：一句 `CreatePipe` 就能把两个进程的标准输入输出接起来；缺点是没有名字，因此无法用于"我不知道对方在哪"的场景。

### Named Pipes

命名管道是 Windows 上真正意义上的"本地 IPC 主力"：它有名字（`\\.\pipe\<name>`），因此素不相识的进程也能找到彼此。三个特性让它特别适合服务场景：

- 可以创建多个实例，让并发客户端各自享有一条连接；
- 支持**消息模式**（不再是无边际的字节流，一次读写就是一条消息）；
- 名字可以通过 SMB 走网络（这也是 SQL Server 那类本地 & 远端兼有的服务喜欢它的原因）。

它与实践联系最紧的一点：**命名管道是 Windows 服务与本机客户端通信的默认选择**，因为它天生带 [访问控制](/docs/CS/OS/Windows/Security.md)——创建时给出的安全描述符决定了谁能连。

---

## Mailslots and Their Sunset

邮件槽（mailslot）提供一个极简模型：单向、追加写入、把消息攒着等服务端读。它有一个别的机制做不到的能力——**向网络域里所有同名邮件槽广播**，代价是这种广播消息不能超过 **400 字节**（点对点单发则受服务端创建时指定的最大长度限制）。

但要注意它的命运：**从 Windows 11 Insider Preview Build 25314 与 Windows Server Preview Build 25314 起，Remote Mailslot 协议默认被禁用**，微软明确这是走向弃用与最终移除的第一步。

> [!NOTE]
>
> 写新代码时不要选邮件槽。它还能用，但已经被划进"历史区"——它的生态位置基本被 RPC 与命名管道接管。

---

## RPC, COM and Component Models

**RPC** 是 Windows 上"函数级"IPC 的通用答案：它由 IDL（接口定义语言）描述接口，编译器生成 stub，跨机器/跨架构时自动做字节序与数据表示转换。Windows 自带的 RPC 兼容 OSF/DCE，因此可以与其它支持 DCE 的系统互操作。

操作系统自己在这件事上是重度用户——**Windows 内部大量组件之间就用 RPC**（如服务管理、远程注册表、打印后台处理），因此它的性能与安全性是被啃透的。

**COM** 在它之上又加了一层"对象"语义：`<接口集>` 作为访问对象数据的固定入口，分布式扩展为 DCOM。COM 是 OLE（复合文档、嵌入/链接对象）、ActiveX、乃至现代 WinRT 的历史前身。今天写新代码通常不再直接手写 COM 对象，但你每天都在用它的结果——剪贴板格式协商、Shell 扩展、Windows Shell 自身的整套结构都是它的投影。

| 层 | 抽象 | 使用者 |
| :-- | :-- | :-- |
| ALPC | 消息传递（下层） | RPC、部分内核/用户态协作 |
| RPC | 函数/接口调用 | 系统服务、跨机器调用 |
| COM / DCOM / WinRT | 对象 + 接口 | 应用级组件、Shell、UI 框架 |

---

## Windows Messages and WM_COPYDATA

桌面应用这一支走的是完全不一样的通道：**窗口消息**。

- 每个窗口/线程有一个消息队列，`SendMessage` 是同步交付、`PostMessage` 是异步投递；
- **`WM_COPYDATA`** 是一条被专门设计出来的 IPC 消息：发送方把一段数据交给接收方，跨进程拷贝由内核完成。**它的限制很硬**：发送方不能传指针，接收方必须知道数据格式并能识别发送者；
- 若 UI 线程要同时等待内核对象与窗口消息，得用 `MsgWaitForMultipleObjects`，见 [进程与线程](/docs/CS/OS/Windows/Process_Thread.md)。

这条路径的价值在于**它天然就是桌面的协作模型**：不需要事先约定端口或管道名，只要有一个窗口句柄就能交流。代价是它不具备服务端语义（没有连接管理、不能跨会话可靠工作）。

---

## Sockets: Including AF_UNIX

Windows Sockets（Winsock）是协议无关的接口，Winsock 2 之后的 socket 句柄还可以被当作文件句柄用于标准文件 I/O 函数（也因此能挂到 [I/O 完成端口](/docs/CS/OS/Windows/IO.md) 上）。

一个 Windows 特有的补充：从 **Windows Insider Build 17063** 起支持 **AF_UNIX**（unix socket）地址族，用于本机 Win32 进程之间的 IPC。这填补了 Windows 上长期缺少的场景——**一套与 BSD socket API 同构的本机 IPC**，让跨平台代码不必为了本机通信再写一份命名管道。

---

## ALPC: The Backbone Nobody Writes

**ALPC（Advanced Local Procedure Call）**是 NT 本机 IPC 的下层设施：一组内核导出的、高效、带完整安全上下文传递能力的消息接口。它经历了两次演化：

```text
NT 4 时代的 LPC（同步、面向本机）
  → Windows Vista 起的 ALPC（异步、支持批量请求、可被 64 位大规模使用）
```

几乎所有 Windows 系统服务的通信底下都是它：`csrss` 与子系统 DLL、RPC 的本机传输（`ncalrpc`）、Win32k 与用户态服务之间的那些交互、乃至 `LsaLookup*` 这类来自 LSA 的调用路径。

它与应用层的关系类似 [Linux 的 Netlink](/docs/CS/OS/Linux/net/README.md) 之于内核与守护进程：**几乎每个人都在用，但极少有人直接写**。理由是它的 API 不是 Win32  ABI 的一部分——稳定性保证在 RPC/命名管道那一层。

---

## Choosing a Mechanism

| 需求 | 首选 | 替代 |
| :-- | :-- | :-- |
| 同机高频大数据交换 | 文件映射（共享内存）+ 自己的同步 | — |
| 本机服务—客户端请求应答 | 命名管道 | RPC（`ncalrpc`） |
| 同机且要求同步/通知语义 | 命名管道 | ALPC / RPC |
| 跨机器调用 | RPC / Windows Sockets | 命名管道（经 SMB） |
| Unix 代码移植、本机 socket 语义 | AF_UNIX | 命名管道 |
| 桌面应用之间少量数据 | `WM_COPYDATA` | 剪贴板（用户发起时） |
| 组件化的应用框架 | COM / WinRT | — |
| 广播短消息（遗留） | 邮件槽（已开始退出） | — |

> [!TIP]
>
> 选型时最实用的分界线其实只有两条：**要不要跨机器**、**要不要通知语义**。前者决定用 socket/RPC 阵营，后者会排除掉共享内存这个选项（它没有内建的同步语义）。剩下的差别大多是 ABI 稳定性与生态惯性的事。

---

## Links

- [Windows I/O 子系统](/docs/CS/OS/Windows/IO.md)
- [Windows 内存管理](/docs/CS/OS/Windows/Memory.md)
- [Windows 安全模型](/docs/CS/OS/Windows/Security.md)
- [Windows 进程与线程](/docs/CS/OS/Windows/Process_Thread.md)
- [Windows 架构](/docs/CS/OS/Windows/Architecture.md)
- [进程间通信](/docs/CS/OS/process.md)

---

## References

1. [Interprocess Communications](https://learn.microsoft.com/en-us/windows/win32/ipc/interprocess-communications)
2. [Pipes](https://learn.microsoft.com/en-us/windows/win32/ipc/pipes)
3. [File Mapping](https://learn.microsoft.com/en-us/windows/win32/memory/file-mapping)
4. [Creating a Child Process with Redirected Input and Output](https://learn.microsoft.com/en-us/windows/win32/procthread/creating-a-child-process-with-redirected-input-and-output)
5. [AF_UNIX comes to Windows](https://devblogs.microsoft.com/commandline/af_unix-comes-to-windows/)
