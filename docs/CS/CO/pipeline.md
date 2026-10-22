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

当指令数 $n \gg k$ 时 $S \to k$，即**最大加速比等于流水段数**。流水提升的是吞吐率，单条指令的延迟仍是 $k\cdot t$ 量级（深流水线反而会因段间寄存器和时钟偏移增大单条延迟）。

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

## 分支预测的现代形态

2 位饱和计数器只是起点。现代预测器在**历史长度**与**表容量**上做文章：

- **TAGE 类预测器**：同时维护多张不同历史长度的预测表，按当前历史哈希动态选用最匹配的表项——长历史抓全局模式、短历史抓局部模式，各取其长；
- **感知机 / 神经网络预测器**：把历史位做加权和直接预测跳/不跳，容量大、能学习特征交互（O-GEHL 是代表思路之一）；
- **间接跳转预测器**：BTB 表项带历史，区分同一个 `jmp *rax` 的多个目标（虚函数调用、switch 跳表）；
- 具体实现属商业机密，只能通过微基准（如针对预测器冲突构造的代码）侧面推断。

## 异常、中断与流水冲刷

指令在流水深处出错（页错误、非法指令、设备中断）时，CPU 必须给出**精确异常**：异常点之前的指令全部退休、之后的全部冲刷丢弃，软件看到的状态与"逐条顺序执行到出错指令"完全一致。乱序机靠 ROB 在退休点统一提交天然满足；顺序机则要保证异常指令之后不再有指令改变状态（多周期机常靠状态机回滚）。中断同理——流水排空后转向量表，返回时重取被中断的指令。

## Cache 与流水的交互

流水线模型假设每级一个周期，真实 stall 的大头来自**缓存缺失**：一次 L1 miss 到 DRAM 约百个周期，等于流水线停摆百余拍。硬件用非阻塞缓存（miss 后继续执行无关指令、同时维持多个 outstanding miss）把停顿藏起来，软件则靠预取与数据布局减少 miss——缺失分类与对策见[缓存层次](/docs/CS/CO/Cache.md)。

## 瞬态执行：推测的代价

[推测执行](/docs/CS/CO/datapath.md)让分支预测成功后的指令提前跑，失败则整段作废、架构状态回滚——**软件永远看不到被作废的指令**。这个"看不见"在 2018 年被证明是个幻觉：被作废的**瞬态指令（transient instructions）**虽然不改变寄存器与内存，却在缓存里留下足迹，而缓存足迹可以用时间差测出来。侧信道就此打通，CPU 安全进入新纪元。

### Meltdown 与 Spectre（2018-01 披露）

- **Meltdown（CVE-2017-5754，rogue data cache load）**：利用乱序机的[内存消歧](/docs/CS/CO/datapath.md)，用户态瞬态地读取本无权访问的内核内存，再经缓存侧信道逐字节读出。Intel x86 中招，**AMD 与 ARM 因不违反权限模型基本免疫**——Linux 用 **KPTI**（内核页表隔离）把内核页表从用户地址空间拿走，代价是系统调用的额外 TLB 开销；
- **Spectre v1（CVE-2017-5753，bounds check bypass）**：欺骗分支预测越过数组边界检查，瞬态读到界外数据——**所有支持推测的架构通吃**；
- **Spectre v2（CVE-2017-5715，branch target injection）**：毒化间接跳转的 BTB 预测目标，让受害代码瞬态跳到攻击者选中的 gadget。缓解是 **retpoline**（用 return 指令序列把间接跳转"困"在预测不到的路径）+ **IBPB**（跨上下文刷新分支预测器）。

### 之后：一场没打完的军备竞赛

retpoline 不是终点，而是一连串漏洞的起点：

- **Retbleed（2022）**：命中返回栈缓冲下溢（return stack buffer underflow）时预测器会退化到可被训练的其他结构——证明"retpoline 万用"的假设不成立，需微码/IBRS 兜底；
- **Zenbleed（2023，AMD Zen 2）**：跨核泄漏向量寄存器存量数据，微码修复；
- **Downfall（2023，Intel 6–11 代 Core）**：AVX gather 指令把内部物理寄存器的陈旧数据瞬态转发，微码修复，实测性能损失 0–50% 因负载而异；
- **Inception / SRSO（2023，AMD Zen 3/4）**：再次攻击返回栈预测。

模式很清晰：**每一种预测结构（分支目标、返回栈、内存消歧、gather 数据通路）都会被单独研究**，而缓解手段分层——新硬件逐代在硅内修复（Intel 第 9 代起硬件修 Meltdown、第 10 代修 MDS/LVI），老硬件靠微码 + OS 组合拳（KPTI、retpoline、IBPB、STIBP、SSBD）。**SMT（超线程）始终是重灾区**：两个安全域共享一套预测结构与 L1，云厂商因此引入 core scheduling（把同物理核的超线程分配给同一租户）。内核态的实现细节见 [KVM](/docs/CS/OS/Linux/KVM.md) 与[系统崩溃分析](/docs/CS/OS/Linux/boot/crash.md)。

### 组成原理视角的总结

- 推测执行不是 bug，是[流水线](/docs/CS/CO/pipeline.md)与控制冒险博弈的必然选择——没有它 CPI 公式里的停顿项会爆炸；
- 真正的问题是**微架构状态（cache、预测器、缓冲）成了架构状态的影子**，而侧信道把这个影子变成了信息通道；
- 硬件、OS、编译器三层都在收紧：Intel/AMD 逐代修复 + `core scheduling` + 常量时间编程。安全不是某一层的属性，而是整条栈的契约。

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
