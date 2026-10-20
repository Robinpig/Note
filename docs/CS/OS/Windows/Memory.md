## Introduction

Windows 的内存管理与 Linux 面对的是同一个硬件问题——**把有限的物理内存变成每个进程看得见的、巨大而私有的连续地址空间**——但两边的账单记法完全不同。Linux 习惯用"缺页成长 +页回收被动触发"那条思路；Windows 更强调**配额与账本**：先把每个进程能承诺多少、物理内存如何在六个链表之间周转讲清楚，剩下的查找逻辑才有意义。

本文按从大到小的顺序推进：先看**地址空间的尺寸限制**（这决定了所有上层设计的天花板），再看 64 位与 32 位的**布局差异**、以及可选的 **5 级分页**，然后是 Windows 特有的三样东西——**VAD 树**、**提交账目（commit charge）**、**工作集**，最后落到**两个实践上总要碰的面**：堆与共享内存，以及物理页的六个链表。

---

## Address Space Limits

先看天花板。按 Microsoft 的官方内存限制文档，x64 Windows 上 64 位进程的限制如下：

| 限制项 | Windows 8 / Server 2012 或更早 | Windows 8.1 / Server 2012 R2 起 |
| :-- | :-- | :-- |
| 64 位进程的用户态虚拟地址空间 | 8 TB | **128 TB** |
| 内核态虚拟地址空间 | 8 TB | **128 TB** |
| 32 位进程的用户态空间（默认） | 2 GB | 2 GB |
| 32 位进程（带 `IMAGE_FILE_LARGE_ADDRESS_AWARE`） | 4 GB | 4 GB |

注意这里的星号：128 TB 的默认值依赖于 PE 文件头里的 **`IMAGE_FILE_LARGE_ADDRESS_AWARE` 标志**。64 位进程默认是置位的，所以默认就能拿到 128 TB；一旦清掉这个标志，地址空间回落到 **2 GB**——这是给那些"我保证只用 32 位指针"的老应用留的逃生舱。

对比之下：Windows 8.1 之前 x64 只有 8 TB 用户态。这条限制在今天听起来很荒唐，但在当年是硬件级数的事——它对应 48 位虚拟地址里可用的那一段，而 Windows 8 及更早版本只用了其中的一部分。

---

## Layout of a 64-bit Address Space

x64 上 AMD/Intel 要求虚拟地址满足 **canonical form**：高 16 位必须是第 47 位的符号扩展，中间那段巨大的空洞不可用。Windows 由此把 256 TB 的总空间一分为二：

```text
0x0000000000000000 ─ 0x00007FFF'FFFFFFFF   用户态 128 TB
                                           ↑ canonical hole（不可用的巨大空洞）
0xFFFF8000'00000000 ─ 0xFFFFFFFF'FFFFFFFF  系统空间 128 TB
```

系统空间（内核态）这一段在整个机器上只有一份，由所有进程共享地映射同一些物理页——这与 Linux 的高半内核映射是同一件事。它里面装着：

- **系统 PTE 区域**：给内核动态映射用（比如某个驱动想临时看一块物理内存）；
- **分页池与非分页池**：前者可换出，后者永远驻留；
- **系统缓存**：缓存管理器为文件数据准备的区域；
- **会话空间**：每个 session 一份的那个窗口子系统数据；
- **页表自身的映射区**：那个著名的 `0xFFFFEA00'00000000` 起点。

最后一项很值得留意：**Windows 把页表本身放在虚拟地址空间里**。因此"查询某虚拟地址对应的 PTE 在哪"变成了一次算术而不是一次物理地址计算，这就是内核里的 `MiGetPteAddress`。

### 32-bit Processes on a 64-bit Kernel: WOW64

32 位 Windows 应用在 64 位 Windows 上跑在 **WOW64** 层：进程被装入 4 GB 以内的那个 sub-space，系统调用经过一层 thunk 转成 64 位原生调用。这里有两个每天都碰到的细节：

- 文件系统重定向：`%SystemRoot%\System32` 被悄悄换成 `SysWOW64`，因此 32 位进程里的 `System32` 实际指的是 32 位 DLL 目录；
- 注册表重定向：32 位视图被重映射到 `Wow6432Node` 子树。

这就是为什么"我明明改了注册表没生效"往往不是 bug，而是你和一个 32 位进程在写两棵不同的树。

---

## Five-Level Paging: Beyond 48-bit Addresses

x64 默认 48 位虚拟地址、四级页表（PML4 → PDPT → PD → PT）。Windows Server 2022 起支持 **5 级分页**（LA57），把虚拟地址从 48 位扩到 57 位，可寻址空间从 256 TB 涨到 **128 PB**。

| 项目 | 4 级分页 | 5 级分页 |
| :-- | :-- | :-- |
| 线性地址宽度 | 48 位 | 57 位 |
| 虚拟寻址空间 | 256 TB | 128 PB |
| PTE 中的 PFN 位宽 | bit 12~47 | bit 12~56 |
| PTE 映射基址（WinDbg 实测） | `FFFFEA00'00000000` | `FF2D0000'00000000` |
| 内核映像 | `ntoskrnl.exe` | 专门的 LA57 内核映像 |

启用需要固件与 BCD 两端同时操作：UEFI 里要先关掉"把 CPU 物理地址限制为 46 位"那一类选项，Windows 侧则是

```powershell
bcdedit /set linearaddress57 optin
```

设置生效后 `bcdedit` 的输出里会出现 `linearaddress57 OptIn`，重启后真正进入 5 级分页模式。

> [!WARNING]
>
> **存在 ≠ 生效**
>
> 前面那张官方内存限制表里给的最高依然是 128 TB。5 级分页是一个**可选的、需要固件与 OS 同时打开的特性**，它不会自动把每一个进程的地址空间放宽——因此写"Windows x64 最多 128 TB"与写"Windows Server 2022 支持 128 PB"这两句话可以同时为真。判断某台机器当前的实际行为，要看 BCD 里的 `linearaddress57` 与 UEFI 设置，而不能只看版本。

---

## VAD Tree: How the Manager Remembers Regions

Linux 用一棵 VMA（`vm_area_struct`）的红黑树记住"这段虚拟地址属于哪个映射"；Windows 用的是 **VAD（Virtual Address Descriptor）树**——每个进程一棵 AVL 树，节点记录一段已保留（reserved）或已提交（committed）的虚拟地址区间的属性：保护位、是否写时复制、是否为映像或区段映射、是否可共享。

VAD 的作用回答了一个在 Linux 语境下常被忽略的问题：**你怎么知道某个虚拟地址"是谁的"？** 答案是查这棵树。这也顺带解释了两个现象：

- 地址空间的**碎片**是真实存在的。频繁 reserve/commit/free 会让 VAD 树变深、可用连续区间变短，同一个进程跑久了之后申请大块连续内存失败的概率会上升；
- `VirtualQuery` / Sysinternals VMMap 看到的那些"Committed: 8 KB / Reserved: 1 MB"的行，就是 VAD 节点的直接呈现。

---

## Commit Charge: NT's Accounting System

这是 Windows 内存管理里最容易被误解的一块。**提交额度（commit charge）**是内核对"如果现在所有人都把脏数据写下去，我一共需要多少后备存储"的记账。

```text
系统提交上限 ≈ 物理内存 + 页文件大小总和
```

- `VirtualAlloc(MEM_COMMIT)` 会增加提交计数，但不立即分配物理页；
- 真正触碰那一页时才触发缺页、由管理器把物理页挂上去；
- 当提交总数逼近上限，Windows 会提示"虚拟内存不足"——**即使此时还有大量空闲物理内存**。

因此"我的服务器明明还有 20 GB 空闲内存，为什么程序申请不到内存"的答案是：这不是物理内存不足，而是账本上的提交额度用完了，请检查页文件大小与 commit limit。

> [!TIP]
>
> 任务管理器里"已提交 x / y GB"那一行就是这张账本。观察它的长期趋势比观察"可用内存"更能预测 OOM——Windows 上真正的 OOM 往往发生在 commit 撞到上限 y 的时候。

---

## Working Sets: What Resides Where

**工作集（working set）**是进程在物理内存里实际持有的页集合，或者说"如果不发生缺页就能直接访问的那些页"。每个进程有：

| 属性 | 含义 |
| :-- | :-- |
| Minimum WS | 系统承诺尽量保住的下限 |
| Maximum WS | 超过就要开始裁剪（trimming） |
| Current WS | 当前实际驻留量 |

平衡集管理器（Balance Set Manager）周期性扫描，把一段时间没被引用的页从工作集里移出。被移出的页**不立即丢弃**，而是进入后面的页链表——它们是下次被再次访问时的第一优先来源。

这里 Windows 给出一个 Linux 那侧没有的明确区分：**专用工作集（private working set）**指只有本进程在用、换出后必然影响它自己的那些页；**可共享工作集（shareable working set）**则是 DLL 代码段、映射视图这些可以与别人共用物理页的部分。看内存占用时只盯前者会低估，只盯"工作集"总量又会偏高——因为后者把整份系统 DLL 都算进去了。

---

## Physical Memory: The Six Lists

物理页在 Windows 上不是在"空闲"和"已用"两个状态之间跳，而是在六个链表之间周转：

| 链表 | 内容 |
| :-- | :-- |
| Zeroed | 已清零，可立即分配（大部分安全分配从这里来） |
| Free | 空闲但未清零，分配时需要先清零 |
| Standby | 已离开某个工作集、内容仍在页框里，可被二次收养，也可被丢弃 |
| Modified | 已离开工作集且内容被改过，需要写回后备存储才能再用 |
| Modified no-write | 与上面类似但不需要写回 |
| Bad | 硬件报出来的坏页，永不使用 |

**Standby 与 Modified 是理解"Windows 内存占用为什么看起来总是很高"的关键**：它们技术上已经不属于任何进程的工作集，但内容还留在内存里作为缓存。任务管理器的"备用"一项就是它。

零页线程（跑到优先级 0 的那个线程）在空闲时把 Free 页清零搬到 Zeroed 列表，让后续的分配不用临时跑一遍清零——这是调度系统与内存系统的一次小协作，见 [进程与线程](/docs/CS/OS/Windows/Process_Thread.md)。

---

## Two Practical Surfaces: Heaps and Shared Memory

### Heap vs VirtualAlloc

用户态分配有三层：

1. **`VirtualAlloc`**：以页为单位、直接与管理器对话。large allocations 从这里走；
2. **Windows Heap Manager**（`RtlHeap*` / `HeapAlloc`）：进程默认堆与自定义堆，用于小块频繁分配。Windows 10 起默认引入 **Segment Heap**，按分配大小分档管理，改善了原本 LFH（低碎片堆）在多线程场景下的表现；
3. **CRT heap**（`malloc`）：多数情况下只是包在 Windows 堆外面的一层。

选择哪一层不是 Perf 玄学：**频繁小块走 HeapAlloc、大块且生命周期清晰走 VirtualAlloc**。反过来用会遇到两种典型的失败——每个小对象占一整页、或者堆自身成为写瓶颈。

### Sections: Windows's Answer to Shared Memory

NT 里共享内存与文件映射是**同一个东西**：区段对象（section object）。

- 由页文件支撑的区段 → 纯粹的共享内存（等价于 POSIX 的 `shm_open` + `mmap`）；
- 由磁盘上的文件支撑的区段 → 内存映射文件。

两者走的是同一套上手操作：多个进程各自 `MapViewOfFile` 把区段映射到自己的地址空间，物理页由管理器统一管理与回收。这也是 [IPC](/docs/CS/OS/Windows/IPC.md) 里最快的一条路径的实现方式。

### Large Pages and AWE

Windows 支持 2 MB / 1 GB 大页，用来降低 TLB 压力（同样的问题在 [Linux 内存管理](/docs/CS/OS/Linux/mm/README.md) 里有对应讨论）。代价是大页内存不可换出、需要连续的物理内存、且要求进程持有 **Lock Pages in Memory** 权限。

---

## Links

- [Windows 架构](/docs/CS/OS/Windows/Architecture.md)
- [Windows 进程与线程](/docs/CS/OS/Windows/Process_Thread.md)
- [Windows IPC](/docs/CS/OS/Windows/IPC.md)
- [Windows 文件系统](/docs/CS/OS/Windows/FileSystem.md)
- [WSL](/docs/CS/OS/Windows/WSL.md)
- [虚拟内存](/docs/CS/OS/memory.md)

---

## References

1. [Memory Limits for Windows and Windows Server Releases](https://learn.microsoft.com/en-us/windows/win32/memory/memory-limits-for-windows-releases)
2. [Virtual Address Space and Physical Storage](https://learn.microsoft.com/en-us/windows/win32/memory/virtual-address-space-and-physical-storage)
3. [Enabling the 5-Level Paging Feature of Windows Server 2022 on Lenovo ThinkSystem Servers](https://lenovopress.lenovo.com/lp1911-enabling-5-level-paging-windows-server-2022)
4. [Memory Management Functions](https://learn.microsoft.com/en-us/windows/win32/memory/memory-management-functions)
5. [Working Set](https://learn.microsoft.com/en-us/windows/win32/memory/working-set)
