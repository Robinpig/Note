## Introduction

I/O（输入输出）是进程与外界交换数据的机制：读磁盘、读写网卡、访问设备。理解 Linux I/O 的钥匙是先把一次读操作拆成**两个阶段**——

- **阶段① 数据准备**：数据从网卡/磁盘到达内核缓冲区（socket 接收队列或 PageCache），可能要等网络包到达、等磁盘寻址；
- **阶段② 数据拷贝**：数据从内核缓冲区拷到用户空间缓冲区，之后应用才能用。

"阻塞 vs 非阻塞"看阶段①：数据没就绪时，阻塞 I/O 让线程睡眠、非阻塞 I/O 立即返回 `EWOULDBLOCK`。"同步 vs 异步"看阶段②：拷贝由用户线程自己在内核态完成就是同步；两阶段都交给内核、完成后再通知才是异步。

真正的工程难题是 **C10K**：一台服务器同时维持上万连接，若一连接一个线程去阻塞等待，线程的内存与调度开销会压垮系统；若让少量线程不停轮询所有连接，轮询本身又是密集的系统调用。Linux 的解法沿一条清晰的演进路线展开：先把"等待多个 fd"**批量化**（select → poll → epoll，即 I/O 多路复用），再把整个 I/O 变成内核侧的**真异步**（io_uring），极端高性能场景则干脆**绕过内核**（DPDK）。本页是 `IO/` 目录的链路总图，按这条因果线串联各篇笔记。

## 五种 I/O 模型

| 模型 | 阶段① 数据准备 | 阶段② 数据拷贝 | 典型实现 |
| --- | --- | --- | --- |
| 阻塞 IO (BIO) | 阻塞等待、线程睡眠 | 阻塞拷贝 | 传统 socket read |
| 非阻塞 IO (NIO) | 立即返回 EWOULDBLOCK | 阻塞拷贝 | O_NONBLOCK |
| I/O 多路复用 | 一个系统调用批量等多个 fd | 阻塞拷贝 | select / poll / epoll |
| 信号驱动 IO | SIGIO 通知就绪 | 阻塞拷贝 | sigaction（TCP 少用、UDP 可用） |
| 异步 IO (AIO) | 内核完成 | 内核完成并通知 | Windows IOCP、Linux io_uring |

阻塞读让线程在等待队列上睡眠、数据就绪再唤醒的内核机制，见 [Socket 阻塞读与唤醒](/docs/CS/OS/Linux/proc/thundering_herd.md?id=socket-阻塞读与唤醒)。各模型的完整源码与 Direct I/O 说明见 [IO 总览](/docs/CS/OS/Linux/IO/IO.md)。

## 多路复用的演进：select → poll → epoll

多路复用的核心问题是：**怎么用一个系统调用，同时等待大量 fd 中的任意一个就绪？** 三代接口对这个问题给出了越来越优的答案。完整机制与源码见 [multiplexing](/docs/CS/OS/Linux/IO/multiplexing.md)。

**select —— 固定位图，全量往返**。调用方把关心的 fd 填进三个固定大小的位图（读/写/异常），内核返回后位图被改成就绪集合，应用再遍历。它有三个先天缺陷：

1. fd 数量硬上限 **1024**（`FD_SETSIZE`），改它要重编译；
2. 每次调用都要把整个 fd 集合**从用户态拷进内核、再拷回**；
3. 返回后应用要 **O(n) 遍历**全部 fd 才知道谁就绪。

**poll —— 去掉数量上限，仍全量遍历**。poll 改用 `pollfd` 数组（事件与结果分开存放，无需每次重填），没有了 1024 上限，但"全量拷贝 + 返回后 O(n) 遍历"两个开销原样保留，连接数大时依然慢。

**epoll —— 注册一次、只收就绪**。epoll 把"维护关注集合"和"等待就绪"拆成三个系统调用，从根本上消除上述开销：

- `epoll_create`：在内核建一个 `eventpoll`；
- `epoll_ctl`：把 fd **注册一次**进内核的数据结构，之后不必每次重传；
- `epoll_wait`：只返回**当前已就绪**的 fd。

epoll 高性能靠三个内核结构支撑，完整字段与流程见 [epoll](/docs/CS/OS/Linux/IO/epoll.md)：

- **红黑树**管理所有被关注的 fd —— 支持 O(log n) 增删，且集合常驻内核，免去每次全量拷贝；
- **就绪链表 rdllist** —— 只链当前就绪的 fd，`epoll_wait` 直接抄这张表，**无需遍历全部 fd**；
- **就绪回调 `ep_poll_callback`** —— fd 在协议栈里就绪时（如数据到达 socket）由回调主动把自己加进就绪链表，**内核不必轮询任何 fd**。

三代接口的对照：

| 维度 | select | poll | epoll |
| --- | --- | --- | --- |
| fd 上限 | 1024 硬限 | 无 | 无 |
| fd 集合传递 | 每次全量拷贝 | 每次全量拷贝 | 注册一次、常驻内核 |
| 就绪后复杂度 | O(n) 遍历 | O(n) 遍历 | O(就绪数) |
| 数据结构 | 位图 | pollfd 数组 | 红黑树 + 就绪链表 |
| 适用连接规模 | 小 | 小 | 大（万级） |
| 触发模式 | 水平 | 水平 | 水平 LT + 边沿 ET |

## ET 与 LT：epoll 的两种触发

`epoll_wait` 通知就绪的时机有两种，决定了上层怎么写循环，详见 [epoll 的 ET & LT](/docs/CS/OS/Linux/IO/epoll.md?id=et--lt)：

- **LT（水平触发，默认）**：只要 fd 的数据没被读完，每次 `epoll_wait` 都还会通知它。编程简单、不易漏事件，但可能重复通知；
- **ET（边沿触发）**：只在状态"从无到有"变化时通知一次，之后即使没读完也不再通知。必须把 fd 设为非阻塞、用循环一次性 read 到 `EWOULDBLOCK`，否则会丢事件。ET 减少了通知次数、配合非阻塞读写性能更高，是高性能框架的主流选择。

## 从 epoll 到 Reactor

多路复用本身只是"等事件"，把它组织成事件循环就是 **Reactor 模式**：一个或少量线程跑 `epoll_wait`，事件到达后分派给预先注册的处理器（accept / read / decode / write），从而用少量线程承载海量连接。这正是 Nginx、Redis（LT）、Netty（ET）共同的骨架。上层线程模型的结构与 Netty 落地见 [Reactor 线程模型](/docs/CS/Framework/Netty/EventLoop.md?id=reactor-线程模型)。

注意 epoll 仍是**同步**模型：它只通知"数据已在内核就绪"，之后应用仍要自己调 `read` 把数据拷出来（阶段②由用户线程做）。要真正连拷贝都交给内核，需要异步 I/O。

## 真异步：io_uring

传统 Linux Native AIO（libaio）只支持 Direct I/O、一直不温不火。**io_uring**（Linux 5.1+，Jens Axboe）用应用与内核**共享的两个环形队列**提交和收割 I/O，把真正的异步带上了 Linux：

- 应用把 SQE（提交项：读/写/接受/连接等操作）写入 **submission queue**；
- 内核执行后把 CQE（完成项）放入 **completion queue**，应用收割即可；
- 可选 SQPOLL 内核线程帮忙轮询提交队列，连提交都不必每次系统调用（`IORING_SETUP_SQPOLL`）。

io_uring 让阶段①、阶段②都由内核完成、完成后再通知，是 Linux 上最接近 Windows IOCP 的真异步接口；它还能与 io-wq、固定文件/缓冲注册等结合减少拷贝。完整结构与提交链路见 [io_uring](/docs/CS/OS/Linux/IO/io_uring.md)。

## 内核旁路：DPDK

追求极限小包吞吐（千万~上亿 pps）时，连内核协议栈的中断、`sk_buff` 分配、多次拷贝和系统调用都成了瓶颈。**DPDK** 直接在用户态重构整条数据面，见 [DPDK](/docs/CS/OS/Linux/IO/DPDK.md)：

- 用户态驱动（PMD + VFIO/UIO）把网卡寄存器与描述符环 mmap 进用户空间；
- 轮询取代中断，PMD 死循环取包、绑核独占；
- 大页上预分配 `rte_mbuf` 内存池，收发只传指针、零拷贝；
- 每核独占收发队列、核间无锁 ring 通信。

DPDK 与内核栈是两条取向相反的路：内核栈胜在通用、完整、与 VFS/协议栈集成；DPDK 胜在专用、可控、线速，典型用于 OVS-DPDK、NFV、5G UPF、软件负载均衡。

## I/O 与其它子系统的边界

- **PageCache / 块层**：缓冲读写经 [PageCache](/docs/CS/OS/Linux/mm/PageCache.md)，回写以 bio 进入 [块设备层](/docs/CS/OS/Linux/dev/block.md)；多路复用等的是"fd 就绪"，磁盘 I/O 等的是"块完成"。
- **零拷贝**：减少阶段②拷贝的技术（sendfile、splice、mmap）见 [ZeroCopy](/docs/CS/OS/Linux/ZeroCopy.md)。
- **进程 / 调度**：阻塞读睡眠在等待队列、超时由 [hrtimer](/docs/CS/OS/Linux/timer.md) 驱动唤醒，见 [进程链路](/docs/CS/OS/Linux/proc/README.md)。
- **网络协议栈**：socket 数据何时算"就绪"由协议栈决定，见 [网络知识地图](/docs/CS/OS/Linux/net/README.md)。
- **内核协同全景**：一次网络请求如何串起进程、内存、网络与中断，见 [内核协同链路](/docs/CS/OS/Linux/Architecture.md)。
- **工程落地**：本文这套「等待批量化 + 事件驱动」的标准答案是 [Nginx Event](/docs/CS/CN/nginx/event.md)——多 worker + epoll 事件循环、连接池、accept 惊群规避；`sendfile` / `aio` / `directio` 怎么选也直接决定它的静态文件与代理路径（见 [ZeroCopy](/docs/CS/OS/Linux/ZeroCopy.md)）。

## Links

- [IO 总览（五种模型）](/docs/CS/OS/Linux/IO/IO.md)
- [multiplexing（select/poll/epoll）](/docs/CS/OS/Linux/IO/multiplexing.md)
- [epoll 详解](/docs/CS/OS/Linux/IO/epoll.md)
- [io_uring](/docs/CS/OS/Linux/IO/io_uring.md)
- [DPDK](/docs/CS/OS/Linux/IO/DPDK.md)

## References

1. [The C10K problem — Dan Kegel](http://www.kegel.com/c10k.html)
2. [epoll(7) — Linux manual page](https://man7.org/linux/man-pages/man7/epoll.7.html)
3. [io_uring — kernel.org documentation](https://www.kernel.org/doc/html/latest/io_uring/index.html)
