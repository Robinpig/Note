## Introduction

计算机算术研究"如何用有限的二进制位和硬件电路，正确地完成整数与浮点的加、减、乘、除"。它上接[数据表示](/docs/CS/CO/CO.md)（补码、IEEE 754），下连[数据通路](/docs/CS/CO/datapath.md)（ALU、寄存器、乘法器/除法器单元）与[流水线](/docs/CS/CO/pipeline.md)（多周期运算如何与流水级配合）。本章聚焦**运算原理与硬件实现**，与[汇编](/docs/CS/assembly/assembly.md)的指令语义互为表里。

## 整数的机器表示

现代计算机一律用**补码（two's complement）**表示有符号整数：第 $n-1$ 位是符号位，值为 $-2^{n-1}$；其余位是权重 $2^i$。补码的好处是**加减法统一**（减法 = 加负数 = 取反加一），且 0 唯一、无 +0/-0 歧义。

- 取负：$-x = \overline{x} + 1$（按位取反再加一）。
- 溢出（overflow）：**同号相加得异号**时发生，即最高位进位 $c_{in}$ 与进位输出 $c_{out}$ 不等（$V = c_{in} \oplus c_{out}$）；仅发生在有符号运算中。
- 反码（ones' complement）、原码（sign-magnitude）已被淘汰，仅见于历史教材。

## 加法器：从行波到超前进位

### 行波进位加法器（RCA）

一位全加器（full adder）输出 $S_i = A_i \oplus B_i \oplus C_i$，$C_{i+1} = A_i B_i + C_i(A_i \oplus B_i)$。把 $n$ 个全加器串起来，进位从低位"波浪式"传到高位，因此**最长路径延迟 = $n \times t_{carry}$**，位宽越大越慢。

### 超前进位加法器（CLA）

核心思想：预先算出每一位的"生成（generate）"与"传播（propagate）"：

$$G_i = A_i B_i, \qquad P_i = A_i \oplus B_i$$

进位可并行展开：

$$C_{i+1} = G_i + P_i C_i = G_i + P_i(G_{i-1} + P_{i-1}C_{i-1}) = \cdots$$

展开到 $C_4$ 只需常数级门延迟，与位宽无关（实际按 4/16 位分组级联）。CLA 把 $n$ 位加法延迟从 $O(n)$ 降到 $O(\log n)$ 级别，是 CPU ALU 加法的标准实现。减法复用同一加法器：对 $B$ 取反并将最低进位 $C_0$ 置 1 即可做 $A - B$。

## ALU 与标志位

算术逻辑单元（ALU）是一个**受控制信号选择的多功能运算器**：用多路选择器（MUX）按 `ALUop` 选 加/减/与/或/异或/比较 等结果，再经零检测、符号检测、溢出检测电路输出**标志位（flags）**：

- `ZF`（zero）：结果为 0；
- `SF`（sign / negative）：最高位为 1；
- `CF`（carry）：无符号运算的进位/借位；
- `OF`（overflow）：有符号溢出。

这些标志位直接喂给[流水线](/docs/CS/CO/pipeline.md)中的条件分支与[数据通路](/docs/CS/CO/datapath.md)的 PC 选择逻辑。

## 乘法

### 无符号：移位-加法

最朴素的做法是"被乘数按乘数位**左移**、部分积**右移累加**"，每轮处理一个比特，需要 $n$ 个时钟周期。硬件上用三个寄存器（被乘数、乘数、乘积）即可实现，是[多周期数据通路](/docs/CS/CO/datapath.md)的典型部件。

### Booth 编码（基 4 / Radix-4）

Booth 算法把"连续 1 串"变成一次加减 + 移位，对**有符号数天然正确**且减少部分积数量。Radix-4 每轮看乘数的 3 位（含前一位），据 `0 1` / `1 0` 模式决定加/减/跳，迭代次数减半。现代乘法器多采用 **Booth 编码 + Wallace/部分积累加树（Dadda tree）**，在 $O(\log n)$ 级内完成 $n\times n$ 乘法，而非朴素 $O(n)$。

## 除法

### 恢复余数（Restoring）

每次试减，若余数为负则加回（恢复），再移位。最坏每轮两次操作。

### 不恢复余数（Non-restoring）

若上次余数为负，下次直接加被除数而非减——省掉恢复步骤，平均更快。SRT 算法（含基 4/基 8）进一步查表加速。除法比乘法慢得多，且**不能流水**（商依赖上一位余数），是[流水线阻塞](/docs/CS/CO/pipeline.md)的常见来源，现代 CPU 往往把它放到专用非流水单元或靠软件/乘法倒数近似。

## 浮点算术（IEEE 754）

浮点数按"符号 $S$ / 阶码 $E$（带偏置 bias） / 尾数 $M$（规格化隐含前导 1）"三段编码，详见[数据表示](/docs/CS/CO/CO.md)。其加减法步骤与整数截然不同：

1. **对阶**：小阶向大阶对齐，尾数右移（可能**阶码下溢**丢失低位）；
2. **尾数加减**：对齐后按定点加减；
3. **规格化**：结果左移/右移使隐含前导 1 归位，同时调整阶码（可能**上溢**）；
4. **舍入**：向最近偶数（round-to-nearest-even，默认）、向零、向 $+\infty$、向 $-\infty$；
5. **例外处理**：产生 NaN、±∞、非规格化数（denormal）、溢出、下溢。

乘除相对简单：阶码相加减、尾数相乘除、再规格化舍入。由于对齐移位与舍入，**浮点加法不满足严格结合律**（$a+b+c$ 的求和顺序会影响结果），这正是[并行计算](/docs/CS/OS/Parallel.md)中浮点规约需小心的原因。

## Links

- [Computer Organization（组成原理枢纽）](/docs/CS/CO/CO.md)
- [数据通路与控制](/docs/CS/CO/datapath.md)
- [流水线](/docs/CS/CO/pipeline.md)
- [汇编](/docs/CS/assembly/assembly.md)

## References

1. [Computer Organization and Design（Patterson & Hennessy）](https://www.elsevier.com/books/computer-organization-and-design/patterson/978-0-12-820331-6)
2. [IEEE 754-2019 Standard for Floating-Point Arithmetic](https://ieeexplore.ieee.org/document/8766229)
3. [Booth's Multiplication Algorithm（Wikipedia）](https://en.wikipedia.org/wiki/Booth%27s_multiplication_algorithm)
