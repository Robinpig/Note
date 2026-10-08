## Introduction

多处理器系统的核心设计问题之一是**内存如何组织与共享**。按照"处理器访问内存的延迟是否一致"，分为 UMA 与 NUMA 两大类；再叠加缓存一致性协议（MESI 等）构成完整的共享内存多处理机模型。这是理解现代多路服务器、CPU 亲和性与多线程性能差异的硬件背景。

## UMA（Uniform Memory Access）

UMA 即一致内存访问：所有处理器通过一条共享总线（或交叉开关）访问同一个集中式内存，**任意核心访问任意地址的延迟相同**。

```
     CPU0     CPU1     CPU2     CPU3
      │       │        │        │
      └───────┴──── 共享总线/交叉开关 ────────┘
                    │
            统一的主存储器 Memory
```

- 典型代表：早期的 SMP（Symmetric Multi-Processor，对称多处理），多核消费级 CPU（各核通过 ring/mesh 访问同一内存控制器，对软件近似 UMA）；
- 优点：编程模型简单，物理地址统一、延迟对称，OS 调度器在哪核运行任务差别不大；
- 瓶颈：总线带宽与单一内存控制器随核数增长成为上限，可扩展性通常到几十核。

## NUMA（Non-Uniform Memory Access）

多路服务器（2/4/8 路 CPU）中，每个 CPU socket 有自己的**本地内存控制器和本地内存**；CPU 访问本地内存快，访问挂在其他 socket 上的"远程内存"要经过 CPU 互连（Intel QPI/UPI、AMD Infinity Fabric），延迟显著更高（通常 1.5–2 倍）且占用互连带宽：

```
  Socket 0                      Socket 1
  Core0..CoreN                  Core0..CoreN
  L3 / 内存控制器 ◄──UPI/IF──►  L3 / 内存控制器
      │                             │
   本地内存(快)                  本地内存(对 S0 是远程、慢)
```

关键软件后果：

- OS 把物理内存按 **NUMA node** 划分，默认策略 `local`（first-touch）：**物理页在首次写入它的 CPU 所在节点分配**——所以"谁先 touch 内存在哪分配"，多线程程序要让 worker 绑定固定 node 并由它初始化数据；
- 工具：`numactl --hardware` 看拓扑、`numactl --cpunodebind=0 --membind=0 ./app` 绑定；`numastat` 看跨节点访问计数；
- Linux 的 NUMA 平衡（AutoNUMA）会自动迁移页面靠近访问它的任务，但迁移本身有成本，数据库常用 `numa=interleave` 或显式绑核避免抖动；
- JVM/数据库（MySQL、Redis 集群）在多路机器上常见的优化就是按 NUMA node 切分实例，避免远程访问。

## Cache Coherence: The Underlying Issue Shared by UMA/NUMA

每个核心有私有 L1/L2 和共享 L3，同一地址在多个 cache 中可能有副本，写操作必须让其他副本失效或更新——这由硬件**缓存一致性协议**保证（对软件透明）：

- **MESI**：缓存行四态 Modified / Exclusive / Shared / Invalid，通过总线嗅探（snooping）或目录（directory）传播失效；
- 写共享变量时的缓存行乒乓（cache line bouncing）是多核扩展的隐形杀手，与软件层面的**伪共享**（false sharing）直接相关，见 [Parallel 并行性能](/docs/CS/OS/Parallel.md)；
- 内存屏障（memory barrier）解决的是编译器/CPU 重排序的可见性问题，与缓存一致性是两层不同概念。

## Hierarchy Review

完整存储层级：寄存器 → L1（~1ns，核私有）→ L2（数 ns，核私有）→ L3（十余 ns，socket 共享）→ 本地 DRAM（~80–100ns）→ 远程 NUMA DRAM（更慢）→ SSD/磁盘。越往下容量越大、越慢，详见 [Cache](/docs/CS/CO/Cache.md)、[存储设备](/docs/CS/CO/disk.md) 与 OS 的 [内存管理](/docs/CS/OS/Linux/mm/memory.md) 笔记。

## Links

- [Computer Organization](/docs/CS/CO/CO.md)
- [Cache](/docs/CS/CO/Cache.md)
- [Parallel（伪共享/NUMA 扩展）](/docs/CS/OS/Parallel.md)
- [RISC-V](/docs/CS/CO/RISC-V.md)

## References

1. [Computer Architecture: A Quantitative Approach（Hennessy & Patterson）](https://shop.elsevier.com/books/computer-architecture/hennessy/978-0-12-811905-1)
2. [Linux NUMA 内存分配策略文档](https://docs.kernel.org/mm/numa.html)
