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

## 一致性协议的两种工程实现

MESI 是协议逻辑，落地有两种拓扑：

- **总线嗅探（snooping）**：所有请求广播到总线，各缓存监听并响应。简单、延迟低，但广播流量随核数快速增长，适合片内少核场景；
- **目录（directory）**：集中或分布式的目录记录每行"谁持有、什么状态"，请求点对点转发、精准作废。可扩展到数百核，今天多路服务器与 CXL 内存扩展都建立在目录协议之上。

状态机也有变体：**MOESI**（加 Owned 态，脏数据可在核间直接转发、省一次内存回写）、**MESIF**（Intel，加 Forward 态指定唯一响应者，避免多缓存同时应答）。协议消息与状态迁移的完整展开见[缓存一致性与内存序](/docs/CS/CO/coherence.md)。

## ccNUMA 与内存交织

- **ccNUMA（cache-coherent NUMA）**：今天多路 x86/ARM 服务器基本都是 ccNUMA——各节点缓存在硬件层面维持全局一致，NUMA 对软件暴露为"延迟不均的单一地址空间"，靠 first-touch 与绑核优化局部性；
- **内存交织（memory interleaving）**：把连续物理地址分散到多个内存控制器/通道，抬高聚合带宽。BIOS 里的通道交织 / NUMA 开关配的就是它：合并节点换来的简单模型会牺牲局部性，数据库与大内存实例通常反向操作（显式分节点）。

## 主存：DRAM 组织

NUMA 讲的是"内存放在哪"，DRAM 讲的是"内存本身怎么造、怎么算时间"。作为[存储层次](/docs/CS/CO/CO.md)中 DRAM 级的硬件展开，它与[缓存层次](/docs/CS/CO/Cache.md)构成一对：SRAM 缓存快而贵，DRAM 用一位一电容的结构换来高密度，代价是**会漏、要刷新、按行访问**。

### 从 cell 到 DIMM

- **cell（存储单元）**：1 个晶体管 + 1 个电容（1T1C），电容充电表示 1，电荷几十毫秒内漏光——这是所有 DRAM 行为的根源；
- **bank（存储阵列）**：cell 排成二维阵列，一行 × 一列。**每 bank 一个行缓冲（row buffer）**，读一行先整行读入行缓冲，再在缓冲内选列；
- **rank / channel / DIMM**：多个 bank 组成 rank（可并行），多个 rank 共享一条 64 位通道，插在主板上的模块即 DIMM（服务器另有 RDIMM/LRDIMM 加寄存器/缓冲）。

### 行式访问与三段时延

DRAM 不是随机寻址存储器，而是**面向行的**。一次读的完整时序：

1. **ACT（activate）**：打开指定 bank 的指定行，整行读入行缓冲——最慢的一步（$t_{RCD}$，约十几纳秒）；
2. **READ/WRITE**：在行缓冲内按列访问，突发长度（burst length）决定一次传多少；
3. **PRE（precharge）**：关闭行，准备下一次 ACT。

由此产生 **open-page vs close-page** 策略与 **bank 级并行**：多个 bank 交替 ACT，可以互相掩盖时序；访存局部性好（行命中）时走 open-page 直接命中行缓冲。控制器调度（FR-FCFS 等）就是在这里做文章。

### DDR：双倍数据速率与代际

**SDRAM 在时钟上升沿传一次，DDR（Double Data Rate）在上升/下降沿各传一次**，等效速率翻倍——"DDR5-6400"的 6400 是 MT/s（每秒百万次传输），不是时钟频率。单通道带宽

$$\text{Bandwidth} = \text{传输速率（MT/s）} \times \text{通道位宽（B）}$$

DDR5-6400 单 DIMM：6400 × 8 B = **51.2 GB/s**。代际沿革：

| 代际 | 标准 | 商用速率 | 电压 | 要点 |
|------|------|----------|------|------|
| DDR4 | JESD79-4 | 1600–3200 MT/s | 1.2 V | 长期主流，2026 年起陆续停产 |
| DDR5 | JESD79-5（2020） | 4800 起步，**6400 成服务器主流**，7200–8800 规划中 | 1.1 V | **PMIC 上 DIMM、on-die ECC 标配**、两个 32 位子通道、行锤缓解 |
| LPDDR5 / 5X | JESD209-5 / -5B（2021） | 6400 / **8533 MT/s**（5C 提到 9600） | ~1.05 V | 16 位窄通道、BGA 焊死、多通道并行（Apple M 系列 64 通道），移动与统一内存首选 |
| HBM | JESD235 | HBM3 单堆栈 819 GB/s，HBM3E 900+ GB/s | — | TSV 垂直堆叠 + 1024/2048 位超宽总线，[GPU/AI 加速器](/docs/CS/CO/simd.md)的标配 |

LPDDR 与 DDR 的区别全在"cell 之外"：封装、电压、通道宽度——同样的 DRAM 核心，LPDDR 靠"窄通道 + 多通道 + 近距焊接"换取能效。

### 刷新（Refresh）

电容漏电要求每行在 **64 ms** 内（高温 > 85 °C 时 32 ms）至少刷新一次。控制器周期性地对所有 bank 发 REF 命令，DDR5 一条 REF 覆盖每 bank 8 行。刷新期间相关 bank 不可访问，形成周期性抖动——实时系统与延迟敏感型服务（高频交易、数据库）要把刷新调度纳入延迟预算。DDR5 新增**自适应刷新管理**，允许控制器根据温度/漏电情况调整刷新频率。

### 纠错：on-die ECC 与 chipkill

DRAM 位翻转有软错误（宇宙射线）与硬错误（制造缺陷/老化）两类来源，防护分几层：

- **on-die ECC**：DDR5 起 JEDEC 标准强制，每 128 位数据配 8 位校验，修正**单粒子翻转（SEU）**，对控制器透明；
- **link ECC**：在总线上传输时保护，防的是链路错误而非存储错误；
- **chipkill**：条带化跨多颗 DRAM 芯片，允许**整颗芯片失效仍可纠正**——服务器 RDIMM 的标配能力；
- **内存 scrub**：后台周期性读-纠-写，把累积的单错在变成双错前修掉；
- 不可纠正错误（UE）最终以 **MCA（Machine Check Architecture，x86）/ RAS 错误记录**上报，Linux 侧由 EDAC 子系统暴露到 `dmesg` 与 sysfs，见[系统崩溃分析](/docs/CS/OS/Linux/boot/crash.md)。

### 行锤（Row Hammer）

反复激活同一行会让相邻行的电容感应充放电而翻转（2014 年 Google 论证）。DDR5 起标准内置缓解（TRR 刷新管理），控制器侧还有目标行刷新（TRR）与频率限制。

## Hierarchy Review

完整存储层级：寄存器 → L1（~1ns，核私有）→ L2（数 ns，核私有）→ L3（十余 ns，socket 共享）→ 本地 DRAM（~80–100ns）→ 远程 NUMA DRAM（更慢）→ SSD/磁盘。越往下容量越大、越慢，详见 [Cache](/docs/CS/CO/Cache.md)、[存储设备](/docs/CS/CO/disk.md) 与 OS 的 [内存管理](/docs/CS/OS/Linux/mm/memory.md) 笔记。

## Links

- [Computer Organization（组成原理枢纽）](/docs/CS/CO/CO.md)
- [Cache](/docs/CS/CO/Cache.md)
- [SIMD / GPU / 领域专用架构（HBM 视角）](/docs/CS/CO/simd.md)
- [Parallel（伪共享/NUMA 扩展）](/docs/CS/OS/Parallel.md)
- [Linux NUMA 内存分配策略](/docs/CS/OS/Linux/mm/Numa.md)
- [RISC-V](/docs/CS/CO/RISC-V.md)

## References

1. [Computer Architecture: A Quantitative Approach（Hennessy & Patterson）](https://shop.elsevier.com/books/computer-architecture/hennessy/978-0-12-811905-1)
2. [JEDEC DDR5 SDRAM Standard（JESD79-5）](https://www.jedec.org/standards-documents/docs/jesd79-5d)
3. [Linux Documentation - NUMA](https://docs.kernel.org/mm/numa.html)
4. [Linux EDAC（Error Detection and Correction）子系统文档](https://docs.kernel.org/driver-api/edac.html)
