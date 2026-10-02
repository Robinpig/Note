## Introduction

前几篇枢纽分别给出了三条纵向链路——[进程管理](/docs/CS/OS/Linux/proc/README.md)（任务的一生）、[内存管理](/docs/CS/OS/Linux/mm/README.md)（页从探测到回收）、[网络](/docs/CS/OS/Linux/net/README.md)（数据从网卡到 socket）。它们各自完整，但内核真正运行时并非三套独立系统，而是被同一件事反复串起来。本页是 `Linux/` 目录的**横向贯通枢纽**：跟一个具体事件——**Nginx worker 处理一次 HTTP 请求**——看这三条链如何咬合、共享哪些数据结构、在哪些点互相唤醒或阻塞。

选 Nginx 是因为它是项目里最完整的跨域样本：[proc/README](/docs/CS/OS/Linux/proc/README.md?id=内核机制-×-nginx) 已建立了内核机制到 Nginx 的对照。需要记住的主线只有一句：**一切始于中断、终于中断；进程是执行者，内存是载体，网络是来源与去处，中断是节拍器**。

## 阶段 0：进程是怎么就位的

请求到来之前，执行环境要先准备好。Nginx master 读配置、绑端口后 fork 出多个 worker——这里走的是[进程生命周期](/docs/CS/OS/Linux/proc/process.md?id=fork)：`kernel_clone` → `copy_process` 复制 task，靠**写时复制**共享 master 的内存页，子进程各自持有独立的 `task_struct` 但先共享地址空间，直到任一方写页触发[缺页](/docs/CS/OS/Linux/mm/vm.md?id=page-fault)才真正复制。master 与 worker 的运行靠**信号**协调（`SIGHUP` reload、`SIGQUIT` 优雅退出），信号的产生与取用见 [signal](/docs/CS/OS/Linux/proc/signal.md)。

每个 worker 被[调度器](/docs/CS/OS/Linux/proc/sche.md)分配到某个 CPU，进入 epoll 事件循环，然后——关键的一步——调用 `epoll_wait` 发现此刻没有连接，便经**等待队列**把自己置为睡眠、从运行队列摘下，让出 CPU。此时系统里没有任何线程在忙等，一切静候外部事件。

## 阶段 1：报文从网卡进来——硬中断打节拍

客户端的 SYN/数据包到达网卡，网卡通过 DMA 把数据写进内核预先准备好的接收缓冲（这些缓冲是网络驱动申请的可移动页，最终来自 [buddy](/docs/CS/OS/Linux/mm/pm.md?id=buddy)），随后向 CPU 发出**硬中断**。这是整条链的"发令枪"，中断处理见 [Interrupt](/docs/CS/OS/Linux/Interrupt.md)。

硬中断的处理极短：它不做协议解析，只把"哪些缓冲有数据"记下来、关闭该网卡后续中断（避免一个包一次中断），然后触发一个 **NET_RX 软中断**（softirq）就返回。这就是"中断上半部 / 下半部"分工——把耗时活推迟到软中断，让 CPU 尽快从硬中断上下文脱身。

## 阶段 2：软中断里的协议栈与 NAPI

软中断在中断返回前后执行，这里跑真正的接收主干（[network Ingress](/docs/CS/OS/Linux/net/network.md?id=ingress)）。核心是 **NAPI**：网卡通过 **NAPI 轮询机制**一次性把已经到达的多个包批量取走，而不是每包一中断——这是高 PPS 下的关键优化。每个包被封装成一个 `sk_buff`（SKB），沿协议栈向上：

- 经 IP 层处理（查路由决定本机接收还是转发，见 [IP](/docs/CS/OS/Linux/net/IP.md) 与 [Route](/docs/CS/OS/Linux/net/Route.md)）；
- 若是 TCP，进入 TCP 层处理序号、ACK、拥塞控制（[TCP](/docs/CS/OS/Linux/net/TCP/TCP.md)，首次建连的三次握手见 [Connection Setup](/docs/CS/OS/Linux/net/TCP/Connection_Setup.md)）；
- 最终根据四元组找到该连接对应的 socket，把 SKB 挂到 socket 的接收队列。

这一段要注意**数据始终在内存里流动、没有拷贝到用户态**——SKB 指向的正是网卡 DMA 写入的那些物理页。

## 阶段 3：唤醒 worker——睡眠与唤醒接合

数据进了 socket 队列，还要让对应的 worker 知道。epoll 在注册这个连接时，已让 socket 的等待队列挂上了 epoll 的回调。于是协议栈处理完数据后触发唤醒：经 `try_to_wake_up` 把正睡在 `epoll_wait` 上的那个 worker 重新置为 `TASK_RUNNING`、放回运行队列。这是**网络子系统与进程子系统的关键接合点**，睡眠唤醒机制见 [wait/wake](/docs/CS/OS/Linux/proc/thundering_herd.md?id=wake)。

为避免多个 worker 被同时唤醒争抢一个连接（**惊群**），Nginx 用 accept mutex、内核侧用 `EPOLLEXCLUSIVE` 保证只唤醒一个等待者，原理见 [thundering herd](/docs/CS/OS/Linux/proc/thundering_herd.md?id=epoll) 与 [epoll](/docs/CS/OS/Linux/IO/epoll.md)。被唤醒的任务并不会立刻运行，而是等[调度器](/docs/CS/OS/Linux/proc/sche.md?id=schedule)在合适的时机切到它，经上下文切换恢复执行现场，`epoll_wait` 返回就绪事件列表。

## 阶段 4：worker 读请求、取数据

worker 醒来后从 socket 读 HTTP 请求——此时数据已在 socket 队列里，`read` 直接把 SKB 中的数据拷到用户态缓冲（一次拷贝）。解析出请求的文件路径后，worker 打开文件、读取内容：

- 文件内容若此前读过，很可能还在[页缓存 PageCache](/docs/CS/OS/Linux/mm/PageCache.md)里，直接命中内存、不碰磁盘；
- 若不在缓存，内核分配新页、向磁盘发起 I/O 填充（worker 可能为此短暂睡眠等待），该页同时进入页缓存供后续复用。

这一步把**文件子系统、内存、进程**三者接在一起：文件读路径最终落在 buddy 分配的物理页与 PageCache 上。worker 自己使用的 `task_struct`、打开文件的 `struct file` 等内核对象则由 [slab](/docs/CS/OS/Linux/mm/slab.md) 分配——同一台机器上，字节级对象和整页走的是不同层次的分配器。

## 阶段 5：响应发出去——下行与零拷贝

worker 组装好 HTTP 响应后写回 socket，数据走**下行发送链**：进 TCP 发送队列、IP 层、排队规则 qdisc，最终交给网卡驱动通过 DMA 发出（[network 收发主线](/docs/CS/OS/Linux/net/README.md?id=收发主线)）。发出后这些页不会立即释放——对端未 ACK 前要保留以便重传。

若是返回静态文件，Nginx 常用 `sendfile` **零拷贝**：让数据从 PageCache 直接到网卡，绕过"内核→用户→内核"的冗余拷贝，机制见 [ZeroCopy](/docs/CS/OS/Linux/ZeroCopy.md)。这是 PageCache 与网络 DMA 在内存层直接对接的典型。

## 阶段 6：压力下的同一条链

平时各环节顺畅，但高负载下三条链的耦合会变得尖锐，这正是理解协同的价值所在：

- 内存吃紧时，分配进入[慢路径](/docs/CS/OS/Linux/mm/pm.md?id=alloc_pages_slowpath)：唤醒 kswapd 回收、做内存压缩整理连续块；网络接收要用的页也可能因此分配受阻。
- 若空闲页多但碎，[compaction](/docs/CS/OS/Linux/mm/Compaction.md) 搬页整理出 DMA 缓冲，搬运依赖页可移动、会短暂改写映射。
- 跨 socket 访问远端内存有额外延迟，[NUMA 平衡](/docs/CS/OS/Linux/mm/Numa.md) 让任务和数据靠拢。
- 一切回收压缩都失败，才由 [OOM killer](/docs/CS/OS/Linux/mm/oom.md) 牺牲一个任务——被杀的通常就是占用最多内存的某个 worker，master 检测到子进程退出后再 fork 补一个，回到阶段 0。

容器化部署时，这条链还整体被 [namespace](/docs/CS/OS/Linux/namespace.md) 隔离视图、[cgroup](/docs/CS/OS/Linux/cgroup.md) 限额，内存超限触发的是 memcg 局部回收与局部 OOM（见 [memcg](/docs/CS/OS/Linux/mm/memcg.md)）。

## 贯穿全程的三个共享数据结构

各子系统能咬合，靠的是共享同一批核心对象，把它们记住就抓住了协同的骨架：

| 数据结构 | 归属 | 如何被各子系统共享 |
| --- | --- | --- |
| `task_struct` | 进程 | 调度器读其调度实体、内存经 `mm` 找到地址空间、信号挂其 pending、网络唤醒改其状态 |
| `struct page` / folio | 内存 | buddy 管理、slab 切分、PageCache 挂接、网络 DMA 作接收缓冲、回收压缩迁移 |
| `sk_buff` | 网络 | 网卡 DMA 填充、协议栈逐层处理、最终挂入 socket 队列；其载荷页与 PageCache 复用 |

## 观察这条端到端链

- `strace -f`：跟一个 worker，看 epoll_wait 睡眠 → read/write 的完整系统调用序列；
- `perf sched` + `/proc/interrupts`：同时观察调度切换、硬中断与软中断频率；
- `ss -ti` / `/proc/net/softnet_stat`：socket 队列与软中断丢包；
- eBPF / ftrace：可跨子系统挂点，把"硬中断 → 软中断 → 唤醒 → 调度 → read"画成一条时间线。

## Links

- [Linux 内核总览](/docs/CS/OS/Linux/Linux.md)
- [进程管理链路](/docs/CS/OS/Linux/proc/README.md)
- [内存管理链路](/docs/CS/OS/Linux/mm/README.md)
- [网络子系统链路](/docs/CS/OS/Linux/net/README.md)
- [Nginx](/docs/CS/CN/nginx/nginx.md)

## References

1. [Linux kernel documentation — kernel.org](https://www.kernel.org/doc/html/latest/index.html)
2. [The Linux Kernel Archives](https://www.kernel.org/)
