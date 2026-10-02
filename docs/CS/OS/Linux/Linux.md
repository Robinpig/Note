## Introduction

Linux is the kernel: the program in the system that allocates the machine's resources to the other programs that you run.
The kernel is an essential part of an operating system, but useless by itself; it can only function in the context of a complete operating system.
Linux is normally used in combination with the GNU operating system: the whole system is basically GNU with Linux added, or GNU/Linux.
All the so-called “Linux” distributions are really distributions of GNU/Linux.

On a purely technical level, the kernel is an intermediary layer between the hardware and the software.
Its purpose is to pass application requests to the hardware and to act as a low-level driver to address the devices and components of the system.

Linux系统诞生于1991年10月5日

常见Linux发行版

- Red Hat Linux
  - Red Hat Enterprise Linux
  - [Fedora](/docs/CS/OS/Linux/Distribution/Fedora.md)
  - [CentOS](/docs/CS/OS/Linux/Distribution/CentOS.md)
- Debian Linux
  - [Ubuntu](/docs/CS/OS/Linux/Distribution/Ubuntu.md)
- SuSE Linux
- Arch Linux
- Kali Linux
- [OpenSuse]()
- [Android](/docs/CS/OS/Android/Android.md)

跨平台在其它OS下使用Linux

- [Docker](/docs/CS/Container/Docker/Docker.md)
- [VM](/docs/CS/OS/VM.md)

Windows下使用Linux

- [WSL](/docs/CS/OS/Windows/WSL.md)

> [!TIP]
>
> 常见的一些[使用经验](/docs/CS/OS/Linux/Experience.md)



一个基于Linux内核的操作系统， 一般应该包含以下部分。

1. bootloader, 比如 GRUB 和 SYSLlNUX , 它负责将内核加载进内存，系统上电或者 BIOS 初始化完成后执行
2. init 程序，负责启动系统的服务和操作系统的核心程序
3. 必要的软件卉（比如加载el f文件的1小linux.so), 支持C程序的库（比如GNU CLibrary,简称glibc), And roid的B ionic
4. 必要的命令和丁具， 比如shell命令和GNU coreutils中等。 coreutils是GNU下的一个 软件包，提供常用的命令， 比如ls等



Linux在最初是宏内核架构 同时也逐渐融入了微内核的精华 如模块化设计 抢占式内核 动态加载内核模块等

模块是被编译的目标文件 可以在运行时的内核中动态加载和卸载 和微内核实现的模块化不同 它们不是作为独立模块执行的 而是和静态编译的内核函数一样 运行在内核态中 模块的引入带来了不少的有点

- 内核的功能和设备驱动可以编译成动态加载/卸载的模块 驱动开发者需要遵守API来访问内核核心 提高开发效率
- 内核模块可以设计成平台无关的
- 相比微内核 具有宏内核的性能优势




## Kernel

内核源码的获取、阅读与构建单独成篇：怎么装源码包、用 ctags / bootlin 读代码、`.config` 配置、`make` 构建与 `bzImage` 的拼接机制，见 [内核构建](/docs/CS/OS/Linux/build.md)。

想读一份**读得完的 Linux**，可以看 0.11 版本 [Linux 0.11](/docs/CS/OS/Linux/0.11.md)：1991 年的内核源码展开后仅 325KB，却已具备进程调度、信号、块设备与文件系统的雏形，用 [Bochs](/docs/CS/OS/Bochs.md) 就能跑起来。它和 xv6 / rCore 那类**教学内核**不是一回事——0.11 是 Linux 自己的早期版本，是现代内核的直系祖先，不是为教学另写的简化系统。它的启动部分（`boot/bootsect.s` → `setup.s` → `head.S` 三段接力）与现代差异极大，正好和下面的启动链对照着看这套机制是怎么演化过来的。

## Boot

镜像编出来之后怎么跑起来，是 [启动链](/docs/CS/OS/Linux/boot/README.md) 的主题：上电 → BootLoader → 内核解压 → `start_kernel` → init → systemd。这是 `Linux/` 下唯一一条严格单向的时间轴，[init](/docs/CS/OS/Linux/boot/init.md) 讲用户态第一号进程与运行级，[U-Boot](/docs/CS/OS/Linux/boot/U-Boot.md) 与 [arm](/docs/CS/OS/Linux/boot/arm.md) 覆盖嵌入式侧的引导器与架构差异。

## 内核协同链路

想先看"进程 × 内存 × 网络 × 中断如何协同完成一件事"，见横向贯通枢纽 [内核协同链路](/docs/CS/OS/Linux/Architecture.md)——以 Nginx 一次请求为锚，端到端串联各子系统。下面各章为按子系统组织的纵向笔记。

## Processes

Linux 进程管理的链路总图见 [Processes](/docs/CS/OS/Linux/proc/README.md)（创建 fork → 表示 task_struct → 装载 exec → 调度 EEVDF/RT → 睡眠唤醒 → 信号 → 退出回收）。

跨进程观测与控制由 [ptrace](/docs/CS/OS/Linux/proc/ptrace.md) 承担：它建立 tracer / tracee 关系，让 tracee 在系统调用边界、信号投递、fork/exec/exit 等事件上停下，tracer 再读写其内存与寄存器——[strace](/docs/CS/OS/Linux/Tools/strace.md) 与 GDB 都建立在其上。

Applications, servers, and other programs running under Unix are traditionally referred to as [processes](/docs/CS/OS/Linux/proc/process.md).
Each process is assigned address space in the virtual memory of the CPU.
The address spaces of the individual processes are totally independent so that the processes are unaware of each other — as far as each process is concerned, it has the impression of being the only process in the system.
If processes want to communicate to exchange data, for example, then special kernel mechanisms must be used.

Because Linux is a multitasking system, it supports what appears to be concurrent execution of several processes.
Since only as many processes as there are CPUs in the system can really run at the same time, the kernel switches (unnoticed by users) between the processes at short intervals to give them the impression of simultaneous processing.
Here, there are two problem areas:

1. The kernel, with the help of the CPU, is responsible for the technical details of task switching.
   Each individual process must be given the illusion that the CPU is always available.
   This is achieved by saving all state-dependent elements of the process before CPU resources are withdrawn and the process is placed in an idle state.
   When the process is reactivated, the exact saved state is restored. Switching between processes is known as task switching.
2. The kernel must also decide how CPU time is shared between the existing processes. Important processes are given a larger share of CPU time, less important processes a smaller share.
   The decision as to which process runs for how long is known as [scheduling](/docs/CS/OS/Linux/proc/sche.md).

### Spurious wakeup

A spurious wakeup happens when a thread wakes up from waiting on a condition variable that's been signaled, only to discover that the condition it was waiting for isn't satisfied.

It's called spurious because the thread has seemingly been awakened for no reason. But spurious wakeups don't happen for no reason:

- they usually happen because, in between the time when the condition variable was signaled and when the waiting thread finally ran, another thread ran and changed the condition.
  There was a race condition between the threads, with the typical result that sometimes, the thread waking up on the condition variable runs first, winning the race, and sometimes it runs second, losing the race.
- On many systems, especially multiprocessor systems, the problem of spurious wakeups is exacerbated because if there are several threads waiting on the condition variable when it's signaled,
  the system may decide to wake them all up, treating every signal() to wake one thread as a broadcast( ) to wake all of them, thus breaking any possibly expected 1:1 relationship between signals and wakeups.
  If there are ten threads waiting, only one will win and the other nine will experience spurious wakeups.
- To allow for implementation flexibility in dealing with error conditions and races inside the operating system, condition variables may also be allowed to return from a wait even if not signaled, though it is not clear how many implementations actually do that.
  In the Solaris implementation of condition variables, a spurious wakeup may occur without the condition being signaled if the process is signaled; the wait system call aborts and returns EINTR.
  **The Linux pthread implementation of condition variables guarantees it will not do that.**

Much more compelling reason for introducing concept of spurious wakeups is provided in [this answer at SO](https://stackoverflow.com/a/1051816/839601) that is based on additional details provided in an (older version) of that very article:

> The Wikipedia article on spurious wakeups has this tidbit:
>
> The function in Linux is implemented using the system call.
> Each blocking system call on Linux returns abruptly with when the process receives a signal.
> ... can't restart the waiting because it may miss a real wakeup in the little time it was outside the system call
> ...pthread_cond_wait() futex EINTR pthread_cond_wait() futex

Just think of it... like any code, thread scheduler may experience temporary blackout due to something abnormal happening in underlying hardware / software.
Of course, care should be taken for this to happen as rare as possible,
but since there's no such thing as 100% robust software it is reasonable to assume this can happen and take care on the graceful recovery in case if scheduler detects this (eg by observing missing heartbeats).

Now, how could scheduler recover, taking into account that during blackout it could miss some signals intended to notify waiting threads?
If scheduler does nothing, mentioned "unlucky" threads will just hang, waiting forever - to avoid this, scheduler would simply send a signal to all the waiting threads.

This makes it necessary to establish a "contract" that waiting thread can be notified without a reason.
To be precise, there would be a reason - scheduler blackout - but since thread is designed (for a good reason) to be oblivious to scheduler internal implementation details, this reason is likely better to present as "spurious".

From thread perspective, this somewhat resembles a Postel's law (aka robustness principle),

> be conservative in what you do, be liberal in what you accept from others

Assumption of spurious wakeups forces thread to be conservative in what it does: set condition when notifying other threads, and liberal in what it accepts:
check the condition upon any return from wait and repeat wait if it's not there yet.

Because spurious wakeups can happen whenever there's a race and possibly even in the absence of a race or a signal, when a thread wakes on a condition variable, it should always check that the condition it sought is satisfied.
If it's not, it should go back to sleeping on the condition variable, waiting for another opportunity.

### thundering herd

[thundering herd](/docs/CS/OS/Linux/proc/thundering_herd.md)

## Lock

内核同步原语笔记集中在 [Lock/](/docs/CS/OS/Linux/Lock/README.md) 目录下：

- [Lock 总览](/docs/CS/OS/Linux/Lock/README.md) — 分类、对比表与选型（目录首页）
- [原子操作与内存屏障](/docs/CS/OS/Linux/Lock/atomic.md) — 所有锁的实现基石
- [spinlock](/docs/CS/OS/Linux/Lock/spinlock.md) — 忙等锁与中断相关的 API 矩阵
- [mutex](/docs/CS/OS/Linux/Lock/mutex.md)
- [rwlock / rwsem / seqlock](/docs/CS/OS/Linux/Lock/rwsem.md)
- [semaphore / completion](/docs/CS/OS/Linux/Lock/semaphore.md)
- [RCU](/docs/CS/OS/Linux/Lock/RCU.md)
- [futex](/docs/CS/OS/Linux/Lock/futex.md)
- [per-CPU 变量](/docs/CS/OS/Linux/Lock/percpu.md) — 以数据隔离代替同步
- [跨进程同步](/docs/CS/OS/Linux/Lock/ipc-sync.md) — 信号量/文件锁/process-shared mutex

## Interrupt

- [Interrupt](/docs/CS/OS/Linux/Interrupt.md)
- [System calls](/docs/CS/OS/Linux/Calls.md)
- [workqueue](/docs/CS/OS/Linux/workqueue.md) — 把工作推后到进程上下文由 kworker 执行，下半部里唯一可睡眠的一档
- [timer 时间子系统](/docs/CS/OS/Linux/timer.md) — 时钟源与 timekeeping、jiffies 与 NO_HZ 节拍、时间轮与 hrtimer、vDSO 与 POSIX 定时器

## Device Driver

设备驱动（设备模型、bus 上的 match/probe 绑定、字符/块/网络三类接口、sysfs/udev 用户侧管理）的链路总图见 [设备驱动](/docs/CS/OS/Linux/dev/README.md)：

- [设备模型 device](/docs/CS/OS/Linux/dev/device.md) — kobject/kset/ktype、cdev、device tree
- [字符设备驱动 char](/docs/CS/OS/Linux/dev/char.md) — dev_t 设备号、chrdevs/cdev_map 三层映射、chrdev_open 换 fops、miscdevice
- [块设备驱动 block](/docs/CS/OS/Linux/dev/block.md) — gendisk/request_queue、bio→request、blk-mq 多队列
- [udev](/docs/CS/OS/Linux/dev/udev.md) — 用户态设备管理、uevent、稳定命名、自动加载
- [input](/docs/CS/OS/Linux/dev/input.md) — 输入设备子系统

## memory

- [内存管理知识地图](/docs/CS/OS/Linux/mm/README.md) — boot探测→物理内存→slab/虚拟内存→页缓存→回收→OOM，memcg 横切的链路总图
- [物理内存 pm](/docs/CS/OS/Linux/mm/pm.md) — node/zone/内存模型/memblock/buddy/alloc/free
- [虚拟内存 vm](/docs/CS/OS/Linux/mm/vm.md) — mm_struct/VMA/page fault/vmalloc
- [页表 pagetable](/docs/CS/OS/Linux/mm/pagetable.md) — 多级布局与层级折叠、表项位与软件位复用、ptdesc 页表页、缺页时逐级惰性生长、free_pgtables 递归下降、mmu_gather 批量 TLB 失效与页表页延迟释放
- [GUP 与 pin 页](/docs/CS/OS/Linux/mm/gup.md) — 慢路径 follow_page_mask/faultin_page、快路径关中断无锁遍历与"先 pin 再验证 PTE"协议、GUP_PIN_COUNTING_BIAS 编码、pin 对迁移/回收/COW/soft-dirty 的反作用、FOLL_LONGTERM 落点合规
- [maple tree](/docs/CS/OS/Linux/mm/maple_tree.md) — 替换 VMA 红黑树的 RCU 安全区间树：节点形态与位编码、ma_state 游标、九种 store 分类、gap 空洞记账
- [slab](/docs/CS/OS/Linux/mm/slab.md) — buddy 之上的小对象分配器
- [mmap](/docs/CS/OS/Linux/mm/mmap.md)
- [PageCache](/docs/CS/OS/Linux/mm/PageCache.md)
- [内存回收 Reclaim](/docs/CS/OS/Linux/mm/Reclaim.md) — 水位线/kswapd/LRU 老化/shrinker/memcg 回收
- [多代 LRU MGLRU](/docs/CS/OS/Linux/mm/MGLRU.md) — 多代组织、页表 accessed 位老化，替代传统 LRU
- [内存压缩 Compaction](/docs/CS/OS/Linux/mm/Compaction.md) — 双扫描器、kcompactd、主动压缩，整理物理连续块
- [NUMA 平衡](/docs/CS/OS/Linux/mm/Numa.md) — AutoNUMA hinting fault 迁移、mempolicy、zone_reclaim_mode
- [OOM killer](/docs/CS/OS/Linux/mm/oom.md) — oom_badness 打分、oom_reaper 收割、memcg 局部 OOM
- [mempool](/docs/CS/OS/Linux/mm/mempool.md) — 紧急内存池
- [cgroup 内存控制 memcg](/docs/CS/OS/Linux/mm/memcg.md) — 按 cgroup 层级记账、限额、局部回收与 OOM
- [内核启动与内存初始化 memory](/docs/CS/OS/Linux/mm/memory.md) — boot 流程，非总入口

## fs

Linux 文件管理（"一切皆文件"、VFS 四大对象 super_block/inode/dentry/file、注册与挂载、路径查找、读写经 PageCache 到块层）的链路总图见 [文件管理机制](/docs/CS/OS/Linux/fs/README.md)：

- [VFS 详解 fs](/docs/CS/OS/Linux/fs/fs.md)
- [ext4](/docs/CS/OS/Linux/fs/ext4.md)、[XFS](/docs/CS/OS/Linux/fs/xfs.md) — 分配组并行、B+ 树家族、逻辑日志与 CIL/AIL
- [Minix](/docs/CS/OS/Linux/fs/Minix.md)
- [jbd2 日志](/docs/CS/OS/Linux/fs/jbd2.md) — 事务/commit 六阶段/checkpoint/恢复三趟扫描
- [overlayfs](/docs/CS/OS/Linux/fs/overlayfs.md) — 联合挂载：lower/upper 分层、whiteout、copy-up
- [proc](/docs/CS/OS/Linux/fs/proc.md)、[sysfs](/docs/CS/OS/Linux/fs/sysfs.md)

## IO

Linux I/O 机制（两阶段、五种 I/O 模型、select→poll→epoll 多路复用演进、ET/LT 与 Reactor、io_uring 真异步、DPDK 内核旁路）的链路总图见 [I/O 与多路复用](/docs/CS/OS/Linux/IO/README.md)：

- [IO](/docs/CS/OS/Linux/IO/IO.md)
- [multiplexing](/docs/CS/OS/Linux/IO/multiplexing.md)、[epoll](/docs/CS/OS/Linux/IO/epoll.md)
- [io_uring](/docs/CS/OS/Linux/IO/io_uring.md)
- [DPDK](/docs/CS/OS/Linux/IO/DPDK.md)
- [零拷贝 ZeroCopy](/docs/CS/OS/Linux/ZeroCopy.md) — `sendfile`/`mmap`/`splice` 等绕过内核↔用户态拷贝的接口与适用边界

## Network

Linux 网络子系统（socket 抽象、协议栈收发、NAPI 软中断、TCP 建连与拥塞）的结构与笔记导航见 [网络知识地图](/docs/CS/OS/Linux/net/README.md)：

- [network](/docs/CS/OS/Linux/net/network.md)、[socket](/docs/CS/OS/Linux/net/socket.md)、[IP](/docs/CS/OS/Linux/net/IP.md)
- [TCP](/docs/CS/OS/Linux/net/TCP/README.md) 子目录按连接生命周期组织：[TCP 实现详解](/docs/CS/OS/Linux/net/TCP/TCP.md)、[建连](/docs/CS/OS/Linux/net/TCP/Connection_Setup.md)、[丢包与重传](/docs/CS/OS/Linux/net/TCP/Retransmission.md)、[拥塞控制框架](/docs/CS/OS/Linux/net/TCP/Congestion.md)、[BBR](/docs/CS/OS/Linux/net/TCP/BBR.md)、[缓冲内存](/docs/CS/OS/Linux/net/TCP/Buffer.md)、[UDP](/docs/CS/OS/Linux/net/UDP.md)
- [netfilter](/docs/CS/OS/Linux/net/netfilter.md)（conntrack / NAT / iptables·nftables）
- [Route](/docs/CS/OS/Linux/net/Route.md)（FIB / 策略路由 / ECMP）、[Neighbor](/docs/CS/OS/Linux/net/Neighbor.md)（NUD 状态机 / ARP / hh_cache）
- [netlink](/docs/CS/OS/Linux/net/netlink.md)（rtnetlink / generic netlink，内核↔用户态配置通道）
- [Qdisc](/docs/CS/OS/Linux/net/Qdisc.md)（fq_codel / HTB / TBF，队列调度与整形）、[Virtual](/docs/CS/OS/Linux/net/Virtual.md)（bridge / veth / bonding / VXLAN 虚拟设备）
- [NAPI](/docs/CS/OS/Linux/net/NAPI.md)（收包主线：napi_struct 状态机、net_rx_action 与 budget、GRO、backlog/RPS）
- [IPv6](/docs/CS/OS/Linux/net/IPv6.md)（fib6 / NDP / SLAAC）、[ICMP](/docs/CS/OS/Linux/net/ICMP.md)（ping / PMTU / 差错反馈）

## Virtualization

- [KVM](/docs/CS/OS/Linux/KVM.md) — 三个 fd 模型、vCPU 运行循环与 fastpath、VMX 双模式、EPT 二维页表、irqfd/ioeventfd

## Data structures

内核自己实现的通用容器集中在 [struct](/docs/CS/OS/Linux/struct/README.md)：[list](/docs/CS/OS/Linux/struct/list.md)（双向循环链表，内核最基础的容器）、[hlist](/docs/CS/OS/Linux/struct/hlist.md)（省掉头指针的哈希表桶链）、[xarray](/docs/CS/OS/Linux/struct/xarray.md)（替代 radix tree 的稀疏数组）、[llist](/docs/CS/OS/Linux/struct/struct.md)（无锁单向栈；文件名叫 `struct.md` 但只讲 llist，是历史命名错位）。它们被各子系统反复复用，选型差异见该目录首页。

## Loadable kernel module

模块把驱动与功能做成可运行时装卸的目标文件：[LKM](/docs/CS/OS/Linux/module/LKM.md) 讲加载/卸载与符号导出，[模块开发](/docs/CS/OS/Linux/module/module.md) 讲 Makefile 与调试。编进内核时 `module_init` 会落到 `device_initcall`，与启动链的 initcall 阶段是同一套机制——两篇的分工见 [module](/docs/CS/OS/Linux/module/README.md)。

## Distribution

发行版 = 内核 + 用户态工具 + 包管理的完整打包，谱系与选型见 [发行版知识地图](/docs/CS/OS/Linux/Distribution/README.md)：

- [Debian](/docs/CS/OS/Linux/Distribution/Debian.md)、[Ubuntu](/docs/CS/OS/Linux/Distribution/Ubuntu.md)、[Kali](/docs/CS/OS/Linux/Distribution/Kali.md)、[Raspberry Pi OS](/docs/CS/OS/Linux/Distribution/Rasp.md)
- [Fedora](/docs/CS/OS/Linux/Distribution/Fedora.md)、[CentOS](/docs/CS/OS/Linux/Distribution/CentOS.md)、[Rocky Linux](/docs/CS/OS/Linux/Distribution/Rocky.md)
- [Arch](/docs/CS/OS/Linux/Distribution/Arch.md)、[Omarchy](/docs/CS/OS/Linux/Distribution/Omarchy.md)、[NixOS](/docs/CS/OS/Linux/Distribution/NixOS.md)

## Performance

线上问题往往不是"不知道机制"，而是**指标读错了**。[性能排查](/docs/CS/OS/Linux/performance.md) 从最容易被误读的 **load average** 切入：它统计的不只是可运行任务，还包括处在**不可中断睡眠**（D 状态）的任务——所以磁盘 I/O 阻塞会把 load 推高，而此时 CPU 可能很闲，照着 CPU 使用率排查会完全跑偏。笔记顺着 `scheduler_tick` 与 `/proc/loadavg` 讲清这三个数是怎么算出来的，另含 CPU 侧的观测口径。

## Commands

命令行速查与工具笔记都在 [Tools](/docs/CS/OS/Linux/Tools/README.md)：目录首页按用途串起 16 篇工具笔记——[perf](/docs/CS/OS/Linux/Tools/Perf.md) 与 [ftrace](/docs/CS/OS/Linux/Tools/ftrace.md) 做性能剖析与追踪、[eBPF](/docs/CS/OS/Linux/Tools/eBPF.md) 做动态插桩、[strace](/docs/CS/OS/Linux/Tools/strace.md) 看系统调用、[Debug](/docs/CS/OS/Linux/Tools/Debug.md) 收调试手段。

要注意目录里的 [Tools.md](/docs/CS/OS/Linux/Tools/Tools.md) 与首页**不是一回事**：它是命令速查表（按功能罗列常用命令与参数），不链任何笔记；首页才是笔记导航。查命令用法看前者，查某个工具的机制原理看后者。

命令用法也可以直接 man，或用 [Linux命令搜索](https://wangchujiang.com/linux-command/)。

## Links

- [Operating Systems](/docs/CS/OS/OS.md)
- [Security](/docs/CS/OS/Security.md)
- [SELinux](/docs/CS/OS/Linux/SELinux.md)
- [namespace](/docs/CS/OS/Linux/namespace.md)
- [cgroup](/docs/CS/OS/Linux/cgroup.md)
- [LXC](/docs/CS/OS/Linux/LXC.md)
- [LKM](/docs/CS/OS/Linux/module/LKM.md)
- [module development](/docs/CS/OS/Linux/module/module.md)
- [sysfs](/docs/CS/OS/Linux/fs/sysfs.md)
- [ext4](/docs/CS/OS/Linux/fs/ext4.md)
- [udev](/docs/CS/OS/Linux/dev/udev.md)
- [Swap](/docs/CS/OS/Linux/Swap.md)

## 参考书籍


| 书名                                           | Desc | 
| ---------------------------------------------- | ---- |
| Linux Performance and Tuning Guidelines        |      |      
| Linux内核源码剖析 - TCP/IP实现                 |      |      
| Linux内核源代码情景分析                        |      |      
| Linux内核设计与实现                            |      |      
| 深入理解计算机系统                             |      |      
| UNIX网络编程                                   |      |      
| UNIX环境高级编程                               |      |      
| 图解TCP/IP                                     |      |      
| 网络是怎样连接的                               |      |      
| Linnux内核完全注释                             |      |      
| 支撑处理器的技术                               |      |      
| An Introduction to GCC                         |      |      
| Linkers and Loaders                            |      |      
| Linux设备驱动程序                              |      |      
| 深入理解Linux内核                              |      |      
| 深入理解Linux虚拟内存管理                      |      |      
| Systems Performance : Enterprise and the Cloud |      |      
| TCP/IP Architecture, Design and Implementation in Linux | |  
| TCP/IP Illustrated, Volume 1: The Protocols |  |  
| The Design and Implementation of the FreeBSD Operating System |  |  
| Debug Hacks : 深入调试的技术和工具 |  |  
| [鸟哥的Linux私房菜](https://linux.vbird.org/) |  |  







## References

1. [Experience with Processes and Monitors in Mesa](https://people.eecs.berkeley.edu/~brewer/cs262/Mesa.pdf)
2. [Linux核心概念详解](https://s3.shizhz.me/)
3. [linux-insides](https://0xax.gitbooks.io/linux-insides/content/)
4. [Linux0.11源码解析](https://zhuanlan.zhihu.com/c_1094189343643652096)
5. [The Linux Kernel documentation](https://www.kernel.org/doc/)
6. [Linux Weekly News](https://lwn.net/)
7. [최신 ARM 리눅스 커널 5.x/6.x 분석 블로그](http://jake.dothome.co.kr/)
