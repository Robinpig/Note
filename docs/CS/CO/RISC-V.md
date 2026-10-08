## Introduction

RISC-V 是 2010 年起由 UC Berkeley 发起的**开放、免费、模块化**指令集架构（ISA），区别于需授权的 x86 / ARM。它把"组成原理"里讲的设计哲学（精简、规整、便于[流水线](/docs/CS/CO/pipeline.md)与[硬布线控制](/docs/CS/CO/datapath.md)）落到了一个真实可用的 ISA 上，因此既是教学首选，也是[组成原理枢纽](/docs/CS/CO/CO.md)里 RISC 一脉的活样例。本节在原有"三种启动模式"基础上，补齐寄存器、指令格式、扩展集与特权层级。

## 设计哲学

- **开源免费**：无授权费、无晶体管道墙，任何人可实现；
- **模块化**：一个**强制基整数 ISA** + 若干可选扩展，按需裁剪；
- **简洁规整**：指令定长（基础 32 位）、少量寻址模式、load/store 架构，天然适合高主频与深流水。

## 特权模式（Privilege Modes）

| 模式 | 名称 | 用途 |
|------|------|------|
| M | Machine | 最高特权，加电后 CPU 在此模式启动，运行固件/引导与可信代码 |
| S | Supervisor | 操作系统内核（如 Linux）运行于此 |
| U | User | 普通应用程序 |
| HS/HU（可选） | Hypervisor / 虚拟化 | 虚拟机监控器与 guest |

系统加电复位后处于 **M-mode**，由固件（如 OpenSBI）完成后初始化再切换到 S-mode 交予内核。这与 x86 的 ring 0/3、ARM 的 EL0–EL3 概念对应。

## 寄存器文件

- 32 个整数通用寄存器 **x0–x31**，其中 **x0 恒为 0**（写它无效），pc 单独存在；
- 调用约定约定 `x1`(ra, 返回地址)、`x2`(sp, 栈指针)、`x5–x7/x28–x31` 临时、`x10–x17` 参数与返回值等；
- 可选浮点扩展提供 **f0–f31**（F 单精度 / D 双精度），与整数寄存器分开。

## 基整数 ISA 与指令格式

- **RV32I / RV64I / RV128I**：分别操作 32 / 64 / 128 位字长，现代 Linux 多用 RV64I；
- 所有基础指令**定长 32 位、小端**，六种格式：

| 格式 | 用途 |
|------|------|
| R | 寄存器-寄存器运算（add, sll, …） |
| I | 立即数运算 / 访存 load / jalr |
| S | 访存 store |
| B | 条件分支（拿 12 位立即数做 ±偏移） |
| U | 取高位立即数（lui, auipc） |
| J | 无条件跳转 jal |

立即数按格式分散在各比特位，硬件译码时**拼接重组**（这是组成原理里"指令格式"的典型考点）。

## 扩展集

| 扩展 | 含义 | 说明 |
|------|------|------|
| I | 整数（Integer） | 必备基集 |
| M | 乘除法（Mul/Div） | 整数 `mul/div/rem` |
| A | 原子（Atomic） | LR/SC、AMO，支撑[并行同步](/docs/CS/OS/Parallel.md) |
| F / D | 单/双浮点 | 需配套 f 寄存器 |
| C | 压缩（Compressed） | 16 位短指令，省代码体积 |
| G | = IMAFD | "通用"组合，编译器默认目标 |

此外还有 B（位操作）、V（向量，RVV）、Zicsr（CSR 访问）等。与 x86（CISC，变长指令、微码翻译）和 ARM（RISC，但有条件执行、变长 Thumb）相比，RISC-V 最"纯"：无延迟槽、无条件执行、格式最少。

## 与组成原理的对应

- 定长规整指令 → [数据通路](/docs/CS/CO/datapath.md)取指译码简单、利于[流水线](/docs/CS/CO/pipeline.md)高主频；
- load/store 架构 → ALU 只处理寄存器，访存集中到 MEM 阶段；
- 扩展可选 → 一个核可裁剪到只有 RV32I（MCU）或扩展到 GCV（服务器），体现"模块化硬件"。
- 启动从 M-mode 逐级降权，对应[多处理器内存](/docs/CS/CO/memory.md)里 OS 接管前的固件阶段。

## Links

- [Computer Organization（组成原理枢纽）](/docs/CS/CO/CO.md)
- [数据通路与控制](/docs/CS/CO/datapath.md)
- [流水线](/docs/CS/CO/pipeline.md)
- [多处理器内存（UMA/NUMA）](/docs/CS/CO/memory.md)
- [汇编](/docs/CS/assembly/assembly.md)

## References

1. [The RISC-V Instruction Set Manual, Volume I: Unprivileged ISA](https://riscv.org/specifications/isa-manual/)
2. [The RISC-V Instruction Set Manual, Volume II: Privileged Architecture](https://riscv.org/specifications/isa-manual/)
3. [RISC-V International](https://riscv.org/)
