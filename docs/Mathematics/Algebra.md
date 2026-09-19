## Introduction

代数把算术从「具体数字」推广到「符号与结构」：它不再只问 2+3 等于多少，而问「满足某些运算律的对象整体有什么性质」。沿着这条线，代数从解方程走向研究抽象的代数系统——群、环、域，它们统一了对称、编码与密码背后的结构。

本笔记给出 CS 视角的代数骨架；与向量空间的关系见 [Linear Algebra](/docs/Mathematics/Linear_Algebra.md)，整数结构见 [数论](/docs/Mathematics/Number_Theory.md)，数学的语言基础见 [集合论与数理逻辑](/docs/Mathematics/Set_Theory_Logic.md)。

## 初等代数 → 抽象代数

| 层次 | 关注点 | 例子 |
| --- | --- | --- |
| 初等代数 | 用符号表示未知量、解方程 | 一元二次、多项式因式分解 |
| 线性代数 | 向量空间与线性映射 | 矩阵、特征值 |
| 抽象代数 | 带运算律的集合（代数结构） | 群、环、域 |

抽象代数的核心问题是：**一个集合配上若干运算，满足哪些公理，就能推出哪些结论？** 这套「先定公理、再推导性质」的方法，正是 [集合论与数理逻辑](/docs/Mathematics/Set_Theory_Logic.md) 中形式化思想的体现。

## 三大代数结构

| 结构 | 运算 | 额外公理 | CS 落点 |
| --- | --- | --- | --- |
| 群 Group | 一个二元运算 | 结合律、单位元、逆元 | 对称性、椭圆曲线密码 |
| 环 Ring | 加法 + 乘法 | 加法群、乘法结合、分配律 | 多项式、有限域 |
| 域 Field | 加 + 乘均可逆 | 环 + 非零元乘法群 | 有限域 GF(2ⁿ) 用于编码与 AES |

群描述「对称」：旋转、置换、模运算都是群。环和域在此基础上加入第二种运算，从而能研究多项式与方程根——这是 [数论](/docs/Mathematics/Number_Theory.md) 与现代密码学的共同语言。

## 多项式

多项式是最自然的「可计算函数」：加法、乘法、带余除法都封闭。多项式插值在数值分析、纠错码（Reed-Solomon）与秘密分享中反复出现。多项式环上的因式分解，是理解有限域构造的钥匙。

## 在 CS 中的落点

- **密码学**：有限域（GF(p)、GF(2ᵐ)）支撑 RSA、Diffie-Hellman、椭圆曲线与 AES；群论描述攻击面（如子群冲突）。
- **编码理论**：环与域上的代数结构构造纠错码。
- **符号计算**：计算机代数系统（Mathematica、SymPy）本质是多项式环上的算法。
- **对称性分析**：群论用于晶格、网络与分子结构的对称性刻画。

## Links

- [Mathematics](/docs/Mathematics/Mathematics.md)
- [Linear Algebra](/docs/Mathematics/Linear_Algebra.md)
- [Number Theory](/docs/Mathematics/Number_Theory.md)
- [Set Theory Logic](/docs/Mathematics/Set_Theory_Logic.md)

## References

1. [Abstract Algebra (Wikibooks)](https://en.wikibooks.org/wiki/Abstract_Algebra)
