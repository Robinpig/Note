## Introduction

[流水线](/docs/CS/CO/pipeline.md)榨取的是**指令级并行**（同时执行多条不同指令），而当处理对象本身就是一批同构数据（像素、向量、矩阵）时，还有另一大维度可挖——**数据级并行（Data-Level Parallelism）**：一条指令同时作用于多个数据元素。本页讲这条线索上的三代技术：CPU 里的 **SIMD 向量指令**（MMX→AVX→SVE→RVV）、GPU 的 **SIMT 大规模并行**，以及为矩阵运算而生的**领域专用架构**（TPU 脉动阵列）。它与[数据表示](/docs/CS/CO/datarep.md)的低精度格式、[性能评价](/docs/CS/CO/perf.md)的能效观、[主存组织](/docs/CS/CO/memory.md)的 HBM 互为表里——今天 AI 计算的硬件底座就是这三页的合流。

## 数据并行的三种形态

| 形态 | 并行方式 | 典型载体 |
|------|----------|----------|
| SIMD（单指令多数据） | 一条指令作用于整个向量寄存器 | SSE / AVX / SVE / RVV |
| SIMT（单指令多线程） | 成千上万个线程执行同一份 kernel，硬件按 32/64 线程一组调度 | GPU（NVIDIA CUDA / AMD RDNA） |
| 数据流 / 脉动阵列 | 数据在阵列节点间流动，每个节点只做乘加 | TPU / NPU / DSP |

区别在控制与数据的比重：SIMD 的并行宽度写在指令里（编译期决定）；SIMT 把宽度藏进硬件（线程块可开几千个，硬件动态分组）；脉动阵列则把"程序"烧成固定数据通路，只有数据在动。

## SIMD：向量指令的三十年

### x86：从 MMX 到 AVX10

- **MMX（1997）**：64 位向量，借道浮点寄存器，证明市场有需求；
- **SSE / SSE2（1999–2001）**：128 位 XMM 独立寄存器，成为此后二十年 SIMD 的基本盘；
- **AVX / AVX2（2011–2013）**：256 位 YMM，三操作数非破坏性编码（VEX 前缀），并引入 gather/scatter；
- **AVX-512（2016，Xeon Phi / Skylake-SP）**：512 位 ZMM、32 个向量寄存器、8 个 mask 寄存器（k0–k7 做逐元素谓词）、嵌入式舍入。它同时踩了两个坑：**特性碎片化**（F/CD/VL/DQ/BW/VNNI 等一堆 CPUID 位组合）与**混合架构冲突**；
- **Alder Lake 起消费级禁用**：Intel 2021 年推 P/E 大小核，E 核不支持 512 位，而 OS 可能在两种核间迁移任务——为免任务漂移到 E 核触发 #UD，Intel 干脆把消费级 AVX-512 全关（P 核硬件其实有）。AMD 走了另一条路：Zen 4 用**双 256 位泵**拼出 512 位（吞吐折半），Zen 5 桌面才实现全宽 512 位；
- **AVX10（收敛方案）**：2023 年提出，用线性版本号取代特性位迷宫，统一 128/256/512 位执行模型。**AVX10.1 首发于服务器 Granite Rapids（2024）**；**AVX10.2 规划随 Nova Lake 把完整 512 位带回消费级**（2025 年底 Intel 架构扩展编程参考已列入路线图，但社区对 Nova Lake 是否真支持存在分歧报道）。宽向量对 AI 推理、媒体转码、科学计算的收益是数量级级的，"消费级有没有"直接影响这批负载的平台选择。

### ARM：NEON → SVE → SME

- **NEON（Advanced SIMD）**：128 位，移动与嵌入式的老功臣；
- **SVE / SVE2**：**向量长可选 128–2048 位、程序不感知具体宽度**——同一份二进制在不同实现上自动用满硬件，开发者不再为"换芯片重编 SIMD"发愁。SVE（v8.2 引入）面向 HPC/ML，SVE2 随 **Armv9-A** 覆盖通用数据处理，2025 架构扩展已推进到 SVE2p3；
- **SME（可扩展矩阵扩展）**：新增 **ZA 矩阵存储寄存器**与外积指令，专攻矩阵乘加——把 GEMM 的累加放寄存器、减少数据移动，是 Arm 对 AI 负载的正面回应，移动端已见于旗舰 SoC。

### RISC-V：RVV 的"长度无关"哲学

RISC-V 向量扩展（RVV）**1.0 于 2021 年底 ratified**，设计信条是 **vector-length agnostic（向量长度无关）**：指令集不规定 VLEN 多宽，软件用 `vsetvli` 按硬件实际宽度取"本批处理多少元素"，同一份代码在 128 位 MCU 与 2048 位加速器上都跑且自动伸缩——比 SVE 更彻底。配套机制：

- 32 个可编程向量寄存器，**LMUL** 允许寄存器分组拼出更长向量；
- mask 寄存器做逐元素谓词（与 AVX-512 的 k 寄存器同思路）；
- 指令集约百条量级（对比 packed-SIMD 的指令膨胀），代码密度与能效占优；
- 生态现状：SiFive X280/P270 等商用 IP、PULP Ara 开源实现、Linux RISE 项目在把 pixman 等库向量化。

## GPU：SIMT 与大规模并行

GPU 把 SIMD 推到一万倍量级，代价是换一套编程模型：

- **SM（流式多处理器）/ CU**：GPU 的基本计算单元，内含整数/浮点流水线与 **Tensor Core**（2017 年 Volta 引入，专做混合精度矩阵乘加）；
- **warp（线程束）**：32 个线程一组，共享一个 PC——SIMT 的"单指令"即 warp 级。**分支分化（divergence）**：warp 内线程走不同分支时串行执行各分支，是最常见的性能陷阱；
- **访存合并（coalescing）**：warp 的 32 个线程应访问连续地址，硬件合并成少数宽事务，否则带宽利用率崩塌——与 CPU [缓存行](/docs/CS/CO/Cache.md)思想同源但更严格；
- **存储层次**：寄存器（每线程私有）→ shared memory / L1（线程块内共享）→ L2（全局）→ **HBM**（超高带宽、[DRAM 组织的极端形态](/docs/CS/CO/memory.md)）；
- **occupancy（占用率）**：驻留 warp 数 / 最大 warp 数，寄存器与 shared memory 用量是主要制约，是 kernel 调优的核心指标。

代际速度极快：H100（2022）→ B200/GB200（2024，双 die、2080 亿晶体管）→ **Vera Rubin（2026-03 GTC 发布：3nm、双 die 3360 亿晶体管、288 GB HBM4、约 22 TB/s 内存带宽、224 SM、896 Tensor Core、FP4 推理 50 PFLOPS）**，Rubin Ultra 规划 2027。驱动这一切的是[能效](/docs/CS/CO/perf.md)：每瓦 token 成本成为第一指标，液冷从选配变为强制。

## TPU 与脉动阵列

谷歌 TPU 走了与 GPU 不同的路：把神经网络的核心操作——**矩阵乘加**——直接烧成数据通路。**脉动阵列（systolic array，Kung & Leiserson 1982）**由一排排乘加单元（MAC）组成，权重与激活数据像血液一样按节拍流过阵列，每个时钟每个 MAC 完成一次乘加并部分和传递——**数据流动即计算，中间结果不落地**，把内存访问压到极限。

- 架构上 TPU 是"确定性"的：无 warp 调度、无分支，靠编译器把模型映射到固定数据通路；
- 代际：v1（2015 推理专用）→ v4/v5 → **v7 Ironwood（2025-04 发布，2026-03 GA）**：FP8 4614 TFLOPS、192 GB HBM3e、约 7.4 TB/s、第三代 SparseCore、9216 芯片 pod 达 42.5 EFLOPS FP8——单芯片功耗近千瓦，100% 液冷；
- 这一页所有内容的共同宿命：**专用架构用灵活性换能效**。模型结构一变（如注意力机制演进），数据通路可能部分作废；GPU 的通用性因此仍是训练侧主流，DSA 在推理侧扩大地盘。LLM 推理侧的工程视角见 [推理优化](/docs/CS/AI/LLM/Model/Inference.md)。

## Roofline：数据并行的体检表

所有上述架构都撞同一堵墙——**算力可以堆，带宽不能**。Roofline 模型（Williams et al., 2009）用两条线给一架机器定性：

- 屋顶 = 峰值算力（FLOPS）；
- 斜线 = 内存带宽限制，** attainable 算力 = 算术强度（AI，FLOP/Byte）× 带宽**；
- 交点即"平衡点"，左侧是带宽受限（多数通用负载），右侧是算力受限（GEMM 等）。

实践含义：先测程序的算术强度再谈优化——强度低于交点的，换再宽的向量指令也白搭，该做的是**数据复用**（分块、融合、提高 cache 命中）。这与[缓存层次](/docs/CS/CO/Cache.md)的局部性原理是同一件事的两种说法。

## Links

- [Computer Organization（组成原理枢纽）](/docs/CS/CO/CO.md)
- [数据表示（低精度格式）](/docs/CS/CO/datarep.md)
- [指令系统与 ISA](/docs/CS/CO/isa.md)
- [性能评价与功耗](/docs/CS/CO/perf.md)
- [多处理器内存（HBM）](/docs/CS/CO/memory.md)
- [RISC-V（RVV）](/docs/CS/CO/RISC-V.md)
- [推理优化](/docs/CS/AI/LLM/Model/Inference.md)

## References

1. [Computer Architecture: A Quantitative Approach（Hennessy & Patterson）](https://shop.elsevier.com/books/computer-architecture/hennessy/978-0-12-811905-1)
2. [Roofline: An Insightful Visual Performance Model（Williams et al., 2009）](https://dl.acm.org/doi/10.1145/1498765.1498785)
3. [Intel® AVX10 Technical Paper（2025-03, Rev 3.0）](http://cdrdv2-public.intel.com/849709/356368-003-intel-avx10-technical-paper.pdf)
4. [NVIDIA Vera Rubin 平台（GTC 2026）](https://www.nvidia.com/en-us/data-center/rubin/)
5. [Google Cloud — TPU Ironwood](https://cloud.google.com/tpu/docs/ironwood)
