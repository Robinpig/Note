## Introduction

流水线（pipelining）是把一条指令的执行拆成多个阶段、让**多条指令的不同阶段重叠执行**的技术，是提升 CPU 吞吐率（throughput）而非单条延迟（latency）的核心手段。它建立在[数据通路](/docs/CS/CO/datapath.md)与[计算机算术](/docs/CS/CO/arithmetic.md)之上：阶段划分越细、重叠越好，单位时间完成的指令越多。本章从经典 5 级流水讲起，推导加速比，再系统分析三类冒险及其化解办法，最后扩展到乱序执行与超标量。

## 经典 5 级流水线

以 MIPS 为代表的精简指令集，把执行切成 5 级：

| 阶段 | 名称 | 工作 |
|------|------|------|
| IF | Instruction Fetch | 取指，PC + 4 |
| ID | Instruction Decode | 译码 + 读寄存器堆 |
| EX | Execute | ALU 运算 / 有效地址计算 |
| MEM | Memory | 访存（load/store） |
| WB | Write Back | 结果写回寄存器堆 |

理想情况下每周期流出一条指令（CPI = 1），各指令像工厂传送带一样错开前进。

## 吞吐率与加速比

设一条指令被切成 $k$ 段、每段耗时 $t$，共处理 $n$ 条指令：

- 非流水总时间：$T_{no pipe} = n \cdot k \cdot t$
- 流水总时间：$T_{pipe} = (k + n - 1) \cdot t$
- 加速比：$S = \dfrac{T_{no pipe}}{T_{pipe}} = \dfrac{nk}{k + n - 1}$

当指令数 $n \gg k$ 时 $S \to k$，即**最大加速比等于流水段数**。注意原枢纽页中"$i$ 条操作、$n$ 段"的公式写反且符号错乱，此处为正确推导。流水提升的是吞吐率，单条指令的延迟仍是 $k\cdot t$ 量级（深流水线反而会因段间寄存器和时钟偏移增大单条延迟）。

## 冒险（Hazards）

流水线靠"后面指令不依赖前面结果"才能全速，违反即产生冒险，需停顿（stall / bubble）或旁路化解。

### 结构冒险（Structural）

硬件资源冲突——例如指令与数据共用同一存储器，IF 与 MEM 同时访存会撞车。化解：**指令/数据分离缓存**（Harvard 化）、增加功能单元（乘除独立单元）。

### 数据冒险（Data）

后续指令用到前面尚未写回的结果（RAW，最普遍；另有 WAR/WAW，多见于乱序机）。两种解法：

- **转发 / 旁路（forwarding / bypassing）**：把 EX 或 MEM 阶段的中间结果直接喂给下一条指令的 EX 输入，免去写回再读；
- **停顿**：转发无法覆盖时（典型如 `load` 后紧跟使用其结果的指令，存在**load-use 冒险**）插入 1 个气泡等待。

编译器调度（把无关指令插到依赖之间）也能静态消解部分数据冒险。

### 控制冒险（Control）

分支指令改变 PC，而 PC 在 ID/EX 后才确定，导致后面已被取出的指令可能该被丢弃。化解手段按代价递增：

1. **冻结 / 预测不跳转**：简单但吞吐损失大；
2. **延迟槽（delay slot）**：MIPS 早期做法，紧邻分支的指令**总是执行**，编译器填有用指令；
3. **静态预测**：按分支方向（向后循环多预测跳、向前多预测不跳）；
4. **动态预测**：用**2 位饱和计数器**（强不跳→弱不跳→弱跳→强跳，需连续两次错才翻转），准确率高；配合 **BTB（Branch Target Buffer）**缓存分支目标地址，省去重新取指。

## 高级流水：乱序、超标量、推测

基础流水仍是**顺序发射、顺序完成**，瓶颈明显。现代 CPU 进一步突破：

- **动态调度（Tomasulo）**：通过**寄存器重命名**消除 WAR/WAW 假依赖，指令在算子就绪即可**乱序执行（out-of-order）**，再按原序**退休（retire / commit）**；
- **推测执行（speculation）**：分支预测成功后提前执行后继，若预测错则清空流水（pipeline flush），代价是一整段气泡；
- **超标量（superscalar）**：每个周期从**指令窗口**取出多条、分发到多个并行执行端口（整数/浮点/访存各自成流水），宽度即每周期发射数；
- **VLIW / EPIC**：把并行性交给编译器在指令字里显式编码（Intel Itanium 路线），硬件更简单但代码依赖具体机型；
- **SMT（同时多线程）**：一个物理核的多个硬件线程共享执行单元，用线程级并行掩盖冒险停顿（Intel 超线程）。

深层流水线（十几到二十级）提高频率但放大预测失败的惩罚；当代设计在频率、段数与预测准确率之间权衡。

## Links

- [Computer Organization（组成原理枢纽）](/docs/CS/CO/CO.md)
- [数据通路与控制](/docs/CS/CO/datapath.md)
- [计算机算术](/docs/CS/CO/arithmetic.md)
- [RISC-V](/docs/CS/CO/RISC-V.md)
- [并行与伪共享](/docs/CS/OS/Parallel.md)

## References

1. [Computer Architecture: A Quantitative Approach（Hennessy & Patterson）](https://shop.elsevier.com/books/computer-architecture/hennessy/978-0-12-811905-1)
2. [Tomasulo's algorithm（Wikipedia）](https://en.wikipedia.org/wiki/Tomasulo_algorithm)
3. [Branch predictor（Wikipedia）](https://en.wikipedia.org/wiki/Branch_predictor)
