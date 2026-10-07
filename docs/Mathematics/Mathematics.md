## Introduction

数学研究**数量、结构、空间与变化**，是计算机科学的底层语言。本库从 CS 视角组织数学笔记：不追求纯数学的完备证明，而关注「哪些数学对象在哪些工程场景中被使用、它们之间如何相互支撑」。

本页是数学领域的**总纲与分支学科目录**：先给出分支学科清单，再逐门学科说明它研究什么、入口在哪。离散与连续两条主线贯穿始终，几篇以小见大的趣味例题（斐波那契、鸽巢、考拉兹）挂在对应分支下。

## Branches

<div class="kb-home">

### Main Branches

<div class="kb-grid kb-grid-sm">

<div class="kb-card">

### [Set Theory and Mathematical Logic](/docs/Mathematics/Set_Theory_Logic.md)

数学的通用语言与证明基础：集合、映射、形式系统与可计算性

</div>

<div class="kb-card">

### [Algebra](/docs/Mathematics/Algebra.md)

从算术到结构：群、环、域与多项式

</div>

<div class="kb-card">

### [Geometry](/docs/Mathematics/Geometry.md)

形状、大小、位置与变换：平面、解析、非欧与微分几何

</div>

<div class="kb-card">

### [Topology](/docs/Mathematics/Topology.md)

连续变形下不变的性质：连通、紧、同胚——「橡皮泥几何」

</div>

<div class="kb-card">

### [Mathematical Analysis](/docs/Mathematics/Real_Analysis.md)

以极限为基石，严格研究实数、函数、级数与连续

</div>

<div class="kb-card">

### [Numerical Analysis](/docs/Mathematics/Numerical_Analysis.md)

有限精度下的近似算法：误差、稳定性与数值解

</div>

<div class="kb-card">

### [Discrete Mathematics](/docs/Mathematics/Discrete_Math.md)

可数、分立的对象：CS 的理论核心

</div>

<div class="kb-card">

### [Combinatorics](/docs/Mathematics/Combinatorics.md)

计数、安排与结构：有多少、怎么排、存在吗

</div>

<div class="kb-card">

### [Number Theory](/docs/Mathematics/Number_Theory.md)

整数的性质：从同余到现代密码学

</div>

<div class="kb-card">

### [Probability and Statistics](/docs/Mathematics/Probability_Statistics.md)

随机现象模型与数据推断：ML 的数学地基

</div>

</div>

</div>

## Discrete and Continuous: Two Main Threads

数学通常被划分为**离散数学**与**连续数学**两条主线，本库的所有分支都可归位：

- **离散数学**研究分立、可数的对象（整数、图、逻辑命题）。它是计算机科学的理论底座：算法正确性、数据库关系模型、编译原理、密码学都建立在集合、逻辑、图论与组合之上。入口见 [离散数学](/docs/Mathematics/Discrete_Math.md)，子领域含 [组合数学](/docs/Mathematics/Combinatorics.md) 与 [数论](/docs/Mathematics/Number_Theory.md)。
- **连续数学**研究可无限细分的对象（实数、连续函数、流形）。它描述物理世界与信号，并为机器学习提供优化与概率工具：以 [集合论与数理逻辑](/docs/Mathematics/Set_Theory_Logic.md) 为语言，经 [代数](/docs/Mathematics/Algebra.md) 与 [几何](/docs/Mathematics/Geometry.md) 展开，在 [数学分析](/docs/Mathematics/Real_Analysis.md) 与 [微积分](/docs/Mathematics/Calculus.md) 中处理变化，在 [拓扑学](/docs/Mathematics/Topology.md) 中观察整体形状，最后由 [数值分析](/docs/Mathematics/Numerical_Analysis.md) 与 [概率论与数理统计](/docs/Mathematics/Probability_Statistics.md) 落地为可计算、可推断的工程方法。

两条主线并非割裂：[线性代数](/docs/Mathematics/Linear_Algebra.md) 既是代数的核心对象（向量空间），又是离散结构与连续空间的桥梁；[微积分](/docs/Mathematics/Calculus.md) 之于 [数学分析](/docs/Mathematics/Real_Analysis.md) 如同初等代数之于抽象代数——前者是直观入口，后者是严格框架。

## Interesting Examples

几篇以小见大的例题笔记，分别挂在对应分支下：

- [斐波那契数列](/docs/Mathematics/Fibonacii.md) —— 矩阵快速幂与黄金比，归入 [数论](/docs/Mathematics/Number_Theory.md)
- [鸽巢原理](/docs/Mathematics/Pigeonhole%20Principle.md) —— 存在性证明的利器，归入 [组合数学](/docs/Mathematics/Combinatorics.md)
- [考拉兹猜想](/docs/Mathematics/Callatz%20conjecture.md) —— 3n+1 的未解之谜，归入 [数论](/docs/Mathematics/Number_Theory.md)

## Links

- [Linear Algebra](/docs/Mathematics/Linear_Algebra.md)
- [Calculus](/docs/Mathematics/Calculus.md)
- [MATLAB](/docs/CS/Tool/MATLAB.md)

## References

1. [Mathematics Subject Classification (AMS)](https://mathscinet.ams.org/mathscinet/msc/msc2020.html)
2. [3Blue1Brown](https://www.3blue1brown.com/)
