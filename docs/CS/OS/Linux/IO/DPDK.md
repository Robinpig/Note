## Introduction

**DPDK**（Data Plane Development Kit）是一组**用户态库和驱动**，用于绕开内核网络栈、在用户空间直接高速收发与处理数据包。它由 Intel 发起，现托管于 Linux Foundation，目标是把通用 CPU 上的包处理从内核协议栈的"通用、公平、可中断"模型，改造成**轮询、零拷贝、核绑定、无共享队列**的数据面模型，从而把小包吞吐从每秒几十万包提升到**线速（line rate，千万~上亿 pps）**，广泛用于虚拟交换机（OVS-DPDK）、NFV、软件负载均衡、5G UPF、SDN 网关等。

要理解 DPDK，先要理解它在对抗什么。常规路径中，一个包要经过：网卡硬中断 → 驱动 → 软中断（NAPI 轮询）→ 内核协议栈（[网络子系统的收发包路径](/docs/CS/OS/Linux/net/network.md)）→ `sk_buff` 分配、多次拷贝、系统调用、上下文切换，最后经 [socket](/docs/CS/OS/Linux/net/socket.md) 交给用户态。这条通用路径功能完备、与协议栈/VFS 深度集成，但每包的中断、拷贝、缓存失效和系统调用开销，在高 pps 场景成为瓶颈。

## Bypass the Kernel

DPDK 从四个方面绕开/重构这条路径：

1. **用户态驱动（PMD + UIO/VFIO）**：把网卡寄存器和描述符队列 mmap 到用户空间。早期用 **UIO**，现在推荐 **VFIO**（`vfio-pci`），在 IOMMU 保护下安全地让用户态直接操作设备，网卡不再走内核网卡驱动（或由内核驱动绑定后剥离给 vfio-pci）。
2. **轮询取代中断（PMD，Poll Mode Driver）**：用户态死循环不断从接收描述符环取包，没有硬中断、没有上下文切换。为让 PMD 100% 占用一个核，需用 CPU 亲和性把它绑核并隔离。
3. **零拷贝 / 大包缓冲池**：预先在大页（hugepage）上分配好固定大小的 `rte_mbuf` 内存池（mempool），收发只在描述符环里传递指针，避免运行时分配和数据拷贝。
4. **核亲和与无锁队列**：每个物理核跑一个 PMD，独占自己的收发队列（RSS 把流哈希到不同队列），核间用无锁 ring 通信，避免共享与锁。

## EAL

**EAL（Environment Abstraction Layer，环境抽象层）** 是 DPDK 的运行时核心，负责对底层硬件/OS 抽象初始化：

- 大页内存初始化（通过 hugepage TLB 命中率，减少页表开销）；
- PCI 设备枚举与绑定（配合 UIO/VFIO）；
- **lcore**（逻辑核）抽象与线程亲和（`rte_eal_remote_launch` 在指定核跑函数）；
- 内存段、DMA 物理地址映射（mbuf 要能被网卡 DMA）；
- 时钟、原子操作、per-lcore 变量等。

典型初始化 `rte_eal_init(argc, argv)`，通过 `-l`（核列表）、`-n`（内存通道）、`--huge-dir`、`-m` 等参数配置。

## PMD and Queues

- **PMD（Poll Mode Driver）**：`rte_eth_rx_burst(port, queue, mbufs[], nb)` / `rte_eth_tx_burst(...)` 一次突发（burst）批量收/发多个包，摊薄单次调用成本。
- **描述符环（descriptor ring）**：每个网卡队列是一组环形描述符，PMD 与网卡硬件通过环首尾指针交接 mbuf，DMA 直接在 mbuf 与网线之间搬运。
- **RSS / 多队列**：网卡按五元组哈希把不同流分发到多个硬件队列，每个队列由一个 lcore 上的 PMD 独占处理，天然水平扩展到多核。
- **mempool + mbuf**：`rte_pktmbuf_pool_create` 在大页上建对象池，mbuf 之间可用 `next` 指针串联支持 jumbo frame。

```c
/* 典型主循环骨架（省略错误处理） */
struct rte_mbuf *bufs[BURST];
for (;;) {
    unsigned n = rte_eth_rx_burst(port, 0, bufs, BURST);
    for (unsigned i = 0; i < n; i++) {
        /* 在用户态直接解析/改写包头，不经内核协议栈 */
        bufs[i]->ol_flags &= ~RTE_MBUF_F_RX_L4_CKSUM_GOOD;
    }
    rte_eth_tx_burst(port, 0, bufs, n);
}
```

## Hugepages and Affinity

性能关键配置：

```bash
# 预留大页并挂载
echo 1024 > /sys/kernel/mm/hugepages/hugepages-2048kB/nr_hugepages
mkdir -p /dev/hugepages && mount -t hugetlbfs nodev /dev/hugepages

# 把网卡从内核驱动解绑、交给 vfio-pci
dpdk-devbind.py --bind=vfio-pci 0000:81:00.0

# 启动时指定核与大页
./app -l 2-9 -n 4 --huge-dir=/dev/hugepages
```

配合内核参数 `isolcpus`/`nohz_full`/`rcu_nocbs` 把 DPDK 核从调度器抖动中隔离，`grub` 里关超分或谨慎使用，减少 cache miss 与尾延迟。

## DPDK vs Kernel Stack

| 维度 | 内核网络栈 | DPDK |
| --- | --- | --- |
| 收发模型 | 中断 + NAPI 软中断 | 纯轮询 PMD |
| 数据位置 | 内核 `sk_buff`，需拷贝到用户态 | 用户态 mbuf，零拷贝 |
| 系统调用 | send/recv、上下文切换 | 无（用户态轮询环） |
| CPU | 按需占用、公平调度 | 专用核 100% 忙轮询 |
| 协议 | 完整 TCP/IP、socket 生态 | 通常只做到 L2/L4，协议栈需另配 |
| 安全/可观测 | 经过 netfilter、tcpdump、conntrack | 默认绕过，需自行实现或用 XDP/eBPF |
| 适用 | 通用服务、连接型应用 | 固定高 pps 的网关/转发/虚拟交换 |

DPDK 用"**专用资源换确定性高性能**"：占满核、绕过内核意味着放弃了内核协议栈、netfilter、[tcpdump](/docs/CS/CN/Tools/tcpdump.md) 可见性与 socket API，因此不适合普通业务服务，只适合数据面。

## XDP as an Alternative

现代内核提供了中间道路 **XDP（eXpress Data Path）**：通过 [eBPF XDP](/docs/CS/OS/Linux/Tools/eBPF.md?id=xdp) 在网卡驱动**收包最早点**（甚至可在网卡 offload）运行可编程处理，做到接近 DPDK 的性能，同时仍在 Linux 内核框架内、能复用驱动与生态、不必把整个核交给忙轮询。选型上：

- 需要极致/完全控制转发平面、跨内核版本一致、做 vSwitch/虚拟网络功能，倾向 DPDK；
- 希望留在内核、按需加载、与 netfilter/栈协作、不独占 CPU，倾向 XDP；
- 两者也可组合（OVS 同时支持 kernel datapath、DPDK datapath 与 AF_XDP）。

## Links

- [IO Models](/docs/CS/OS/Linux/IO/IO.md)
- [Zero Copy](/docs/CS/OS/Linux/ZeroCopy.md)
- [io_uring](/docs/CS/OS/Linux/IO/io_uring.md)
- [epoll](/docs/CS/OS/Linux/IO/epoll.md)
- [network stack](/docs/CS/OS/Linux/net/network.md)
- [socket](/docs/CS/OS/Linux/net/socket.md)
- [eBPF](/docs/CS/OS/Linux/Tools/eBPF.md)

## References

1. [DPDK Documentation](https://doc.dpdk.org/guides/)
2. [DPDK Programmer's Guide — Environment Abstraction Layer](https://doc.dpdk.org/guides/prog_guide/env_abstraction_layer.html)
3. [DPDK Poll Mode Drivers](https://doc.dpdk.org/guides/prog_guide/poll_mode_drv.html)
4. [Linux Foundation DPDK project](https://www.dpdk.org/)
