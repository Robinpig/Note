## Introduction

可计算性理论（computability theory）回答一个**先于效率**的问题：哪些问题原则上可以被程序解决。它把「算法」这个直觉概念形式化为图灵机，用 Church-Turing 论题给出「有效可计算」的判定标准，再用停机问题划出不可逾越的边界。

这条线索是计算机科学的理论基石：**先确定能不能算，再讨论算得快不快**。资源与效率的分层（P、NP、NP-complete）发生在可判定问题的内部，见 [NP-complete](/docs/CS/Algorithms/NP.md)。

## The Turing Machine

图灵机由三个部件构成：**胶带（tape）**、**控制器（controller）** 与 **读写头（read/write head）**。

- **胶带**：分成离散格子的无限存储，每格承载一个符号，充当存储与输入输出的唯一介质。
- **控制器**：中央处理器（CPU）的理论对应物，一个**有限状态自动机**——状态的数目预先固定，任一时刻恰处于其中一个状态，并按「当前状态 + 读到的符号」决定下一步动作。
- **读写头**：读当前格、写回新符号、向左或向右移动一格。

整台机器由一张状态转移表完全决定，控制器的有限状态与胶带的无限容量分别对应**有穷的控制逻辑**与**无上限的存储**。把「程序」本身编码成胶带上的数据，一台机器便能模拟所有机器，这是通用图灵机，也是「存储程序」架构的理论原型。

在理论计算机科学中，会给某种特定语言中能写出的**每一个程序**分配一个无符号数，通常称为 **Gödel 数**（以奥地利数学家 Kurt Gödel 命名）。程序与数据因此可以在同一根胶带上一视同仁地读写——现代编译器把源码当输入、把字节码当数据，正是这一编码的直接后裔。

## Church-Turing Thesis

> [!NOTE]
>
> **Church-Turing 论题**：若存在完成某个符号操作任务的算法，则必存在完成该任务的图灵机。

依据这一论断，凡是能写出算法来完成的符号操作任务，都可以由图灵机完成。注意它**只是论题（thesis），不是定理（theorem）**：定理可以被数学证明，论题不能。虽然它大概永远无法被证明，但支持它的论据很强：

- 至今没有找到任何**不能**用图灵机模拟的算法。
- 所有已被数学严格刻画过的计算模型（λ 演算、一般递归函数、Post 对应系统等）都被证明与图灵机模型**等价**。

工程上的推论是**图灵完备性**：只要一个语言或系统能模拟通用图灵机，它在「能解哪些问题」上就与任何其他图灵完备系统完全等价，差异只落在效率、表达力与工程约束上。这也是 [编程语言横向对比](/docs/CS/Languages.md) 里各语言可以只比生态与运行特性、而不比计算能力的原因。

## Halting Problem

> [!WARNING]
>
> **停机问题是不可判定的**：不存在一个程序，能对任意输入判定「这段程序最终会停机还是永远运行」。

标准证明是对角线反证：假设有判定器 `H(P, x)` 能判定程序 `P` 在输入 `x` 上是否停机，就可以构造 `D(P)`——当 `H(P, P)` 判定「停机」时它故意进入死循环，判定「不停机」时立刻退出；再问 `D` 以自己为输入时输出什么，两种答案互相矛盾，故 `H` 不存在。

需要区分两个层次：**可识别**（半可判定，运行者若停机就能给出「是」的结论）弱于**可判定**（是与否都必须给出答案）。停机问题属于前者而不属于后者——这正是「存在写不出来的程序」的严格含义，也是计算的边界。

这条边界在实践中无处不在：

- **静态分析与编译器**无法完美判定死循环、空指针或程序等价性，只能做**保守近似**——可靠性与完备性不可兼得，报出的告警必然有漏报或误报。
- 程序优化的正确性前提（两个程序是否语义相同）本身就不可判定，见 [编译器](/docs/CS/Compiler/Compiler.md)。
- 形式系统的**不完备性**与计算的不可判定性同源，见 [集合论与数理逻辑](/docs/Mathematics/Set_Theory_Logic.md)。

## Complexity of Solvable Problems

在可判定的问题内部，按所需资源（时间、空间）继续分层：

- **多项式问题**：存在 $O(n^k)$ 算法，通常视为「易解」（tractable）。
- **非多项式问题**：只有指数级及以上算法时视为「难解」（intractable）；$P$ 与 $NP$ 是否相等是自 1971 年提出以来最深的未解问题之一，见 [NP-complete](/docs/CS/Algorithms/NP.md)。

资源度量的前提是**计算模型**：精确复杂度必须在某个抽象机上定义（通常取随机访问机或图灵机），否则「一条指令耗时多少」无从谈起了，见 [Algorithm Analysis](/docs/CS/Algorithms/Algorithms.md?id=algorithm-analysis)。

## Links

- [Algorithms](/docs/CS/Algorithms/Algorithms.md)
- [NP-complete](/docs/CS/Algorithms/NP.md)
- [CS](/docs/CS/CS.md)
- [Set Theory and Logic](/docs/Mathematics/Set_Theory_Logic.md)

## References

1. [Turing machine](https://en.wikipedia.org/wiki/Turing_machine)
2. [Halting problem](https://en.wikipedia.org/wiki/Halting_problem)
3. [Church–Turing thesis](https://en.wikipedia.org/wiki/Church%E2%80%93Turing_thesis)
4. Computer Science: An Overview
