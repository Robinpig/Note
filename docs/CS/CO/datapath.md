## Introduction

CPU 由两大部分组成：**数据通路（datapath）**——承载数据流动的部件（寄存器堆、ALU、存储器、总线、多路选择器）及其连线；**控制（control）**——根据当前指令产生每个部件的控制信号（"什么时候读寄存器、ALU 做加还是减、结果写回哪里"）。[流水线](/docs/CS/CO/pipeline.md)是数据通路的一种组织方式，而[计算机算术](/docs/CS/CO/arithmetic.md)单元（ALU、乘除法器）就坐落在数据通路之中。本章对比单周期、多周期两种经典数据通路，并剖析"硬布线 vs 微程序"两种控制实现。

## 寄存器堆（Register File）

通用寄存器是数据通路的中枢：典型实现有 **两个读端口 + 一个写端口**（读 RS、RT，写 RD），在一个时钟内可同时读出两个源操作数、并把上一条指令的结果写回。写操作通常在时钟上升沿发生，需配合**转发**避免读-写同址冲突（见[流水线](/docs/CS/CO/pipeline.md)的数据冒险）。

## 单周期数据通路（Single-Cycle）

每条指令都用**一个长时钟周期**走完全部操作：取指 → 译码 → ALU → 访存 → 写回串成一条通路，CPI = 1。

- 优点：控制极简，每条指令行为直观；
- 致命缺点：**时钟周期由最慢指令（如访存或乘法）决定**，一条 `lw` 拖慢整机的 `add`。资源无法复用，面积与功耗浪费严重。

## 多周期数据通路（Multi-Cycle）

把执行拆成**多个较短的时钟周期**，一条指令占若干周期（CPI > 1），但各级功能部件（ALU、寄存器、存储器）**分时复用**，不再为每个指令各建一套硬件：

- 周期长度由"单步操作"而非"整条指令"决定，时钟可显著加快；
- 用少量内部寄存器（如 ALU 输出锁存）在周期之间暂存中间结果；
- 代价是控制更复杂（需状态机决定下一步走哪条微操作路径）。

## 控制：硬布线 vs 微程序

### 硬布线控制（Hardwired）

控制信号由**组合逻辑电路**直接由（操作码 + 当前状态）译出，速度快、无额外存储，但一旦指令集改动就要改电路。RISC 指令规整、控制简单，通常采用硬布线；现代 x86 的前端译码后也走硬布线的乱序引擎。

### 微程序控制（Microprogrammed）

把每条机器指令的"控制步骤"写成**微指令（microinstruction）**，存于**控制存储器（微码 ROM）**；一条机器指令 = 一串微指令序列，由**微程序计数器（µPC）+ 微定序器**驱动。

- 微指令字段常采用"水平/垂直"编码，或用**微操作（µop）**抽象；
- 优点：**改指令集只需改微码**，适合 CISC（x86 的复杂指令、小数端、字符串操作都靠微码实现），也便于修复硬件 bug（微码更新）；
- 代价：多一层存储与取指延迟。历史上曾用微程序实现整个 CPU 控制。

### 现代演变

今天两者边界已模糊：x86 把 CISC 指令**翻译（decode）成内部 µop**，再交给硬布线的乱序执行核心；RISC 也常把少数复杂操作（如乘除法、原子指令）下沉到微码或固件辅助。µop 缓存（µop cache）、分支预测都建立在数据通路之上，详见[流水线](/docs/CS/CO/pipeline.md)。

## Links

- [Computer Organization（组成原理枢纽）](/docs/CS/CO/CO.md)
- [流水线](/docs/CS/CO/pipeline.md)
- [计算机算术](/docs/CS/CO/arithmetic.md)
- [RISC-V（微程序 vs 硬布线对照）](/docs/CS/CO/RISC-V.md)
- [汇编（指令编码与数据通路对应）](/docs/CS/assembly/assembly.md)

## References

1. [Computer Organization and Design（Patterson & Hennessy）](https://www.elsevier.com/books/computer-organization-and-design/patterson/978-0-12-820331-6)
2. [Microcode（Wikipedia）](https://en.wikipedia.org/wiki/Microcode)
3. [x86 Microcode（osdev wiki）](https://wiki.osdev.org/Microcode)
