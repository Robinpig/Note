## Introduction

指令集架构（Instruction Set Architecture，ISA）是软硬件之间的**契约**：软件看到的所有"机器能力"——有哪些指令、多少个寄存器、怎么寻址、特权怎么分层——都由它规定；契约之下怎么实现（几级流水、乱序还是顺序、缓存多大）是微架构的自由。本页把 ISA 的各个侧面系统对比：CISC 与 RISC 的哲学分歧、指令格式与编码、寻址方式谱系、特权层级与异常模型、ABI 与调用约定。具体的活样例见 [RISC-V](/docs/CS/CO/RISC-V.md)，指令的语义落地见[汇编](/docs/CS/assembly/assembly.md)。

## ISA 规定什么

- **指令集**：操作码语义（算术/访存/分支/系统指令）；
- **架构寄存器**：通用寄存器、PC、状态寄存器——注意只有"架构可见"的寄存器属于 ISA，物理寄存器堆、重命名表是实现细节；
- **寻址方式与数据类型**：支持哪些宽度、对齐要求；
- **特权与异常模型**：特权层级、异常/中断向量、系统调用入口；
- **内存模型**：load/store 的可见性与顺序保证（弱序还是强序，见[缓存一致性与内存序](/docs/CS/CO/coherence.md)）。

ISA 与微架构的分界是兼容性的根：同一 ISA 可以有不同的微架构实现（x86-64 从 Pentium 到现代乱序核），软件无需重编；而换 ISA 必须重编译甚至重写。

## CISC vs RISC

| 维度 | CISC（x86） | RISC（ARM / RISC-V / MIPS） |
|------|-------------|------------------------------|
| 指令长度 | 变长（1~15 字节） | 定长（4 字节；RISC-V C 扩展另有 2 字节短指令） |
| 单条指令功能 | 复杂（一条字符串拷贝可含寻址+循环） | 简单（load/store + 寄存器运算） |
| 访存 | 运算可直接读内存操作数 | **load/store 架构**，ALU 只碰寄存器 |
| 寻址方式 | 丰富（十余种） | 极少（基址+偏移、PC 相对） |
| 控制实现 | 微程序（微码）+ 译码成 µop | 硬布线为主 |
| 译码复杂度 | 高（变长边界探测是吞吐瓶颈之一） | 低（定长规整，取指即知边界） |
| 代码密度 | 高（变长编码省空间） | 低（靠压缩指令扩展补） |

这场持续四十年的辩论没有纯粹赢家：现代 x86 前端把 CISC 译码成 µop 后走硬布线乱序核，"CISC 的壳、RISC 的芯"；ARM 则用 Thumb-2（16/32 混合）补代码密度。真正的分水岭是**指令能否被快速并行译码**——这直接决定[流水线](/docs/CS/CO/pipeline.md)能开多宽。

## 指令格式与编码

一条指令 = **操作码 + 操作数字段**，但字段怎么切，各家差别巨大：

- **x86**：`[前缀] 操作码 [ModRM] [SIB] [位移] [立即数]`。ModRM 字段时间寄存器/内存操作数组合，SIB 处理"基址+变址×比例+位移"的复杂寻址；前缀（REX、VEX、EVEX）一位位扩展寄存器号与向量宽度——**译码器要先数前缀才能确定指令边界**，这是变长编码的固有代价；
- **ARM AArch64**：回到**定长 32 位**，条件执行从 ARMv7 的每条指令带条件位改为条件码 + 少数条件选择指令；
- **RISC-V**：定长 32 位、**六种格式**（R/I/S/B/U/J），立即数按格式分散在不同比特位、硬件译码时拼接重组——具体字段切法见 [RISC-V](/docs/CS/CO/RISC-V.md)。

立即数编码是"格式规整性"与"表示能力"的权衡：RISC-V 的 I 型只带 12 位立即数，大常量要靠 `lui + addi` 两条拼；x86 的立即数字段长度可变，但同样增加译码歧义。

## 寻址方式谱系

| 寻址方式 | 操作数位置 | 典型使用者 |
|----------|-----------|-----------|
| 立即数（immediate） | 指令内常量 | 全部 |
| 寄存器（register） | 寄存器 | 全部 |
| 直接（direct） | 指令内绝对地址 | x86；RISC 大多没有 |
| 寄存器间接 | 寄存器存地址 | MIPS `jr` 类跳转；x86 |
| 基址 + 偏移（base+displacement） | 寄存器 + 常量偏移 | **全部现代 ISA**（栈帧、结构体成员的硬件基础） |
| 变址（indexed） | 基址寄存器 + 变址寄存器（可带比例） | x86（SIB 字节） |
| PC 相对 | PC + 偏移 | 全部（位置无关代码的基础） |
| 间接 | 内存中存地址再取 | x86；RISC 已淘汰 |

RISC 设计者刻意砍掉直接/间接寻址：访存只有"基址+偏移"一种，[数据通路](/docs/CS/CO/datapath.md)只需一个地址加法器，流水线各级延迟可预测。

## 特权层级与异常模型

ISA 的第二半契约是**特权**——用户代码不能直接动页表、关中断、配设备，硬件必须提供分级：

| 架构 | 层级 | 用途 |
|------|------|------|
| x86 | Ring 0~3（CPL） | 0 = 内核，3 = 用户；1/2 基本闲置 |
| ARMv8-A | EL0~EL3 | EL3 = 安全监控/固件，EL2 = Hypervisor，EL1 = 内核，EL0 = 用户 |
| RISC-V | M / S / U（+ H） | M = 机器态（固件），S = 内核，U = 用户，H = 虚拟化 |

配套的还有**异常与中断入口**：异常向量表（x86 IDT / ARM vector table / RISC-V `mtvec` 指向的陷阱向量）、系统调用指令（`syscall`/`svc`/`ecall`）、以及陷入时硬件自动保存的状态（PC、原因码）。异常必须在流水线中表现为**精确异常**——出错点之前的指令退休、之后的冲刷，这是[流水线](/docs/CS/CO/pipeline.md)与乱序执行的硬约束。

## ABI 与调用约定

ISA 之上还有一层软件契约——**应用二进制接口（ABI）**：参数放哪些寄存器、返回值放哪、栈怎么长、调用者/被调用者各自负责保存哪些寄存器。它不属于 ISA 但由 ISA 决定形态：x86-64 SysV 用 `rdi/rsi/rdx/rcx/r8/r9` 传参、返回 `rax`；RISC-V 用 `a0~a7` 传参、`a0/a1` 返回；ARM AAPCS 用 `x0~x7`。调用约定的细节是[汇编](/docs/CS/assembly/assembly.md)与编译器后端的必修课，也是跨语言 FFI 出问题的重灾区——System V 与 Win64 的寄存器划分、栈对齐与 red zone 的完整对照见 [调用约定与 ABI](/docs/CS/assembly/Calling_Convention.md)。

## Links

- [Computer Organization（组成原理枢纽）](/docs/CS/CO/CO.md)
- [RISC-V](/docs/CS/CO/RISC-V.md)
- [数据表示](/docs/CS/CO/datarep.md)
- [数据通路与控制](/docs/CS/CO/datapath.md)
- [流水线](/docs/CS/CO/pipeline.md)
- [数据并行与加速器（向量 ISA）](/docs/CS/CO/simd.md)
- [汇编](/docs/CS/assembly/assembly.md)

## References

1. [Computer Architecture: A Quantitative Approach（Hennessy & Patterson）](https://shop.elsevier.com/books/computer-architecture/hennessy/978-0-12-811905-1)
2. [Computer Organization and Design（Patterson & Hennessy）](https://www.elsevier.com/books/computer-organization-and-design/patterson/978-0-12-820331-6)
3. [The RISC-V Instruction Set Manual, Volume I: Unprivileged ISA](https://riscv.org/specifications/isa-manual/)
