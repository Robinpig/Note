## Introduction

> 标准与版本口径（2026-10 核实）：浮点以 **IEEE 754-2019** 为准；PCIe 最新已批准规范为 **7.0**（2025-06-11 发布，128.0 GT/s，x16 单向约 242 GB/s、双向最高 512 GB/s；8.0 已立项、计划 2028）；RISC-V 手册以 **20260120** 版为准（B/V 等扩展已 Ratified，P 仍 Draft）；NVMe 基础规范以 **2.4**（2026-07-31 Ratified）为准。读到旧代际表述（如"PCIe 6.0 是最新""CXL 基于 PCIe 5.0"）时，以本口径为准。

计算机组成原理（Computer Organization and Architecture）研究"程序如何在硬件上真正跑起来"：从**数据如何用二进制表示**、**指令如何编码与执行**，到 **CPU 内部的数据通路、控制与流水线**，再到 **存储层次**与**总线 I/O**，最后延伸到**数据并行的加速器**。它是连接[汇编](/docs/CS/assembly/assembly.md)、[操作系统](/docs/CS/OS/OS.md)与[计算机网络](/docs/CS/CN/CN.md)的硬件底座。

本页是组成原理的**总纲**：把各主题串成一条主线并落到专门的子页。学习路径建议：**性能与功耗 → 数据表示 → 指令系统与 ISA → 计算机算术 → 数据通路与控制 → 流水线 → 存储层次 → 总线与 I/O → 数据并行与加速器**，最后用 [RISC-V](/docs/CS/CO/RISC-V.md) 把前述概念在一个真实 ISA 上收口。

> 经典教材以 Hennessy & Patterson 的 *Computer Architecture: A Quantitative Approach* 与 *Computer Organization and Design* 为权威；本库涉及寄存器/缓存/内存层级的事实以源码与手册为准，不凭记忆写默认值。

## 零、性能与功耗

拆开任何部件之前，先造尺子：**CPU 时间 = 指令条数 × CPI × 时钟周期**，三个因子分别归因于软件、微架构与工艺；**Amdahl 定律**给出任何局部优化的整体加速上限，是"先优化什么"的裁决者；2005 年前后**功耗墙**终结频率竞赛，多核、大小核、异构加速器皆是其后果——今天评价硬件的货币是每瓦性能。这把尺子独立成页：[性能评价与功耗](/docs/CS/CO/perf.md)。

## 一、数据表示

硬件只认二进制。整数一律用**补码**（加减统一、零唯一，详见[计算机算术](/docs/CS/CO/arithmetic.md)）；浮点遵循 **IEEE 754-2019**，把一个数拆成**符号位 S**、**偏置阶码 E**（实际指数加偏置，单精度 bias = 127）、**规格化尾数 M**（隐含前导 1）三段，单精度 32 位（1+8+23）、双精度 64 位（1+11+52）。由于对齐移位与舍入，**浮点加法不满足结合律**，是[并行规约](/docs/CS/OS/Parallel.md)需小心之处。三种有符号编码对比、754 特殊值与舍入模式、大小端与字符编码独立成页：[数据表示](/docs/CS/CO/datarep.md)。

## 二、指令系统与 ISA

指令集架构（ISA）是软硬件接口：规定有哪些指令、寄存器、寻址方式、特权层级。**CISC（x86，变长、微码）vs RISC（ARM、RISC-V，定长规整、load/store）**的取舍贯穿[数据通路](/docs/CS/CO/datapath.md)与[流水线](/docs/CS/CO/pipeline.md)；具体编码见 [RISC-V 的六种格式](/docs/CS/CO/RISC-V.md)与[汇编](/docs/CS/assembly/assembly.md)。指令格式、寻址方式谱系、特权层级与 ABI 的系统对比独立成页：[指令系统与 ISA](/docs/CS/CO/isa.md)。

## 三、计算机算术

加法器（行波 vs 超前进位）、ALU 与标志位、移位-加法与 Booth 乘法、恢复/不恢复余数除法、IEEE 754 浮点加减与舍入——这些电路是数据通路的运算核心，独立成页：[计算机算术](/docs/CS/CO/arithmetic.md)。

## 四、数据通路与控制

CPU = 数据通路（寄存器堆、ALU、存储器、MUX 及其连线）+ 控制（产生每拍控制信号）。经典对比：

- **单周期**：每条指令一个长时钟，CPI=1 但被最慢指令拖死；
- **多周期**：指令拆成多拍，功能部件分时复用；
- **控制实现**：RISC 多用**硬布线**，CISC 多用**微程序（微码）**；现代 x86 把 CISC 译码成内部 µop 再走硬布线乱序核心。

详见[数据通路与控制](/docs/CS/CO/datapath.md)。

## 五、流水线

把执行拆成 IF/ID/EX/MEM/WB 五级，多条指令不同阶段重叠，提升**吞吐率**。设 $k$ 段、$n$ 条指令：加速比 $S = \dfrac{nk}{k+n-1}$，当 $n\gg k$ 时 $S\to k$（上限等于段数）。阻碍全速的是三类冒险：

- **结构冒险**：资源冲突 → 指令/数据缓存分离；
- **数据冒险**：结果未就绪 → 转发/旁路、必要时插入气泡（load-use 冒险必停 1 拍）；
- **控制冒险**：分支改变 PC → 延迟槽、静态/动态预测、BTB。

进一步可做到乱序执行、推测、超标量、SMT。完整展开见[流水线](/docs/CS/CO/pipeline.md)。

## 六、存储层次

速度、容量、成本不可能兼得，于是构成金字塔：寄存器 → L1（核私有，~1ns）→ L2（核私有）→ L3（socket 共享）→ DRAM（~100ns）→ 磁盘/SSD。越往下越慢越大。

- **地址翻译**：虚拟地址到物理地址的翻译靠 [TLB](/docs/CS/CO/tlb.md) 兜底——页表树走内存太慢，TLB 覆盖率（条目数 × 页大小）因此直接决定大页值与上下文切换成本；
- **缓存**：以缓存行（cache line）为单位在 CPU 与内存间搬运，映射 / 替换 / 写策略见[缓存层次](/docs/CS/CO/Cache.md)；多核靠 **MESI** 等一致性协议保持副本一致，并引出伪共享与内存屏障问题，见[缓存一致性与内存序](/docs/CS/CO/coherence.md)；
- **多处理器内存**：多核/多路下按访问延迟分 **UMA / NUMA**，NUMA 下"谁先 touch 内存在哪分配"直接影响多线程性能，见[多处理器内存](/docs/CS/CO/memory.md)；DRAM 本身的行式组织、DDR 代际与刷新在那里展开；
- **二级存储**：HDD 受寻道+旋转瓶颈，SSD 靠 FTL/磨损均衡/写放大，NVMe 走 PCIe 多队列，见[存储设备](/docs/CS/CO/disk.md)。

## 七、总线与 I/O

CPU 通过总线与外围设备通信。传统并行 **PCI** 已被点对点、全双工的 **PCIe** 取代，成为 GPU、NVMe、高速网卡的事实标准；其配置空间、BAR（MMIO）、DMA、MSI-X 与 IOMMU 是设备驱动与虚拟化的硬件基础，见[PCIe 总线](/docs/CS/CO/PCI.md)。

## 八、以 RISC-V 收口

[RISC-V](/docs/CS/CO/RISC-V.md) 把前述 RISC 设计哲学落到一个开源 ISA：定长规整指令利于流水、load/store 架构、模块化扩展（I/M/A/F/D/C/G）、M/S/U 特权模式逐级降权。它既是教学样例，也是把组成原理各章串起来的最好锚点。

## 九、数据并行与加速器

当数据成批同构（像素、向量、矩阵），指令级并行之外还有**数据级并行**这一大维度。三代技术接力：CPU 的 SIMD 向量指令（x86 AVX-512/AVX10、ARM SVE2/SME、RISC-V RVV）、GPU 的 SIMT 万核并行（warp、访存合并、Tensor Core）、以及 TPU 脉动阵列这类**领域专用架构**——它们共享同一条 roofline 约束：算力可以堆，带宽不能。见[数据并行与加速器](/docs/CS/CO/simd.md)。

## Links

- [性能评价与功耗](/docs/CS/CO/perf.md)
- [数据表示](/docs/CS/CO/datarep.md)
- [指令系统与 ISA](/docs/CS/CO/isa.md)
- [计算机算术](/docs/CS/CO/arithmetic.md)
- [数据通路与控制](/docs/CS/CO/datapath.md)
- [流水线](/docs/CS/CO/pipeline.md)
- [缓存层次](/docs/CS/CO/Cache.md)
- [TLB 与地址翻译](/docs/CS/CO/tlb.md)
- [缓存一致性与内存序](/docs/CS/CO/coherence.md)
- [多处理器内存（UMA/NUMA）](/docs/CS/CO/memory.md)
- [存储设备](/docs/CS/CO/disk.md)
- [PCIe 总线](/docs/CS/CO/PCI.md)
- [RISC-V](/docs/CS/CO/RISC-V.md)
- [数据并行与加速器](/docs/CS/CO/simd.md)

## References

1. [Computer Architecture: A Quantitative Approach（Hennessy & Patterson）](https://shop.elsevier.com/books/computer-architecture/hennessy/978-0-12-811905-1)
2. [Computer Organization and Design（Patterson & Hennessy）](https://www.elsevier.com/books/computer-organization-and-design/patterson/978-0-12-820331-6)
3. [IEEE 754-2019 Standard for Floating-Point Arithmetic](https://ieeexplore.ieee.org/document/8766229)
4. [Roofline: An Insightful Visual Performance Model（Williams et al., 2009）](https://dl.acm.org/doi/10.1145/1498765.1498785)
5. [SPEC — Standard Performance Evaluation Corporation](http://spec.org)
