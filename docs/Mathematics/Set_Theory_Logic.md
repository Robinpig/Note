## Introduction

集合论提供数学的**通用语言**（集合、关系、函数）；数理逻辑研究**形式系统与可证明性**（命题、量词、可计算性）。两者是「数学能说什么、怎么证明」的根基，也是程序语言类型系统与可计算性理论的来源。

本笔记给出集合与逻辑的 CS 视角；代数结构见 [代数](/docs/Mathematics/Algebra.md)，连续基础见 [数学分析](/docs/Mathematics/Real_Analysis.md)。

## 集合、关系与函数

- **集合**：无序、互异的元素总体；并、交、补、幂集。
- **关系**：笛卡尔积的子集；等价关系（自反/对称/传递）划分集合。
- **函数**：单值映射；单射/满射/双射决定可否求逆。

数据库的关系模型、类型系统的子类型，本质都是集合与关系，见 [离散数学](/docs/Mathematics/Discrete_Math.md)。

## 命题与一阶逻辑

- **命题逻辑**：用 ∧ ∨ ¬ → 组合原子命题，真值表与推理规则。
- **一阶逻辑**：加入量词 ∀ ∃ 与谓词，可表达「对所有 x 存在 y…」。
- **证明**：自然演绎、归结原理——自动定理证明与形式验证的基础。

## 可计算性

- **图灵机**：tape + 控制器 + 读写头，形式化「算法」；详见 [CS 总纲的图灵机](/docs/CS/CS.md?id=the-turing-machine)。
- **丘奇-图灵论题**：凡算法可做的，图灵机都能做（是论题非定理）。
- **停机问题**：不可判定——存在「无法写出程序判断」的问题，划定计算的边界。

## 在 CS 中的落点

- **类型系统**：类型即集合，子类型即子集；Curry-Howard 同构把「程序」与「证明」对应。
- **形式验证**：用逻辑证明程序正确，见 [软件工程](/docs/CS/SE/Engineering.md)。
- **数据库**：关系代数是集合运算。
- **可计算性理论**：界定什么能算、什么不能算。

## Links

- [Mathematics](/docs/Mathematics/Mathematics.md)
- [Discrete Math](/docs/Mathematics/Discrete_Math.md)
- [Algebra](/docs/Mathematics/Algebra.md)
- [Real Analysis](/docs/Mathematics/Real_Analysis.md)

## References

1. [Set Theory (Wikipedia)](https://en.wikipedia.org/wiki/Set_theory)
