## Introduction

离散数学研究**可数、分立的对象**——整数、图、逻辑命题、有限集合——与处理连续对象的 [数学分析](/docs/Mathematics/Real_Analysis.md) 相对。它是计算机科学的理论核心：几乎所有 CS 子领域都建立在集合、逻辑、图与组合之上。

本笔记给出离散数学的总览；计数见 [组合数学](/docs/Mathematics/Combinatorics.md)，整数结构见 [数论](/docs/Mathematics/Number_Theory.md)，形式系统见 [集合论与数理逻辑](/docs/Mathematics/Set_Theory_Logic.md)。

## Why CS Needs Discrete Mathematics

计算机是离散的：比特非 0 即 1，状态有限，时间是分步的。连续数学描述「物理量如何平滑变化」，离散数学描述「有限结构如何组合与推导」——后者直接对应程序、数据与算法。

## Main Subfields

| 子领域 | 研究什么 | CS 落点 |
| --- | --- | --- |
| 集合论与逻辑 | 对象、关系、证明 | 类型系统、形式验证 |
| 图论 | 顶点与边 | 网络、依赖、最短路径 |
| 组合数学 | 计数与安排 | 算法复杂度、存在性 |
| 数论 | 整数性质 | 密码学 |
| 离散概率 | 有限样本空间 | 随机算法、哈希 |

## Contrast with Continuous Mathematics

- **对象**：离散（整数、图）vs 连续（实数、函数）。
- **工具**：归纳、组合、图算法 vs 极限、导数、积分。
- **典型问题**：「是否存在」「有多少种」「能否在多项式时间求解」vs「收敛到多少」「变化率多大」。

## Applications in CS

- **算法**：正确性证明用归纳；复杂度用组合计数，见 [算法](/docs/CS/Algorithms/Algorithms.md)。
- **数据库**：关系模型即集合与笛卡尔积；SQL 是关系代数。
- **编译原理**：自动机与形式语言是离散结构。
- **密码学**：[数论](/docs/Mathematics/Number_Theory.md) 提供单向函数。
- **分布式**：共识与容错依赖图论与组合，见 [分布式系统](/docs/CS/Distributed/Distributed.md)。

## Links

- [Mathematics](/docs/Mathematics/Mathematics.md)
- [Combinatorics](/docs/Mathematics/Combinatorics.md)
- [Number Theory](/docs/Mathematics/Number_Theory.md)
- [Set Theory Logic](/docs/Mathematics/Set_Theory_Logic.md)
- [Algorithms](/docs/CS/Algorithms/Algorithms.md)

## References

1. [Discrete Mathematics (Wikipedia)](https://en.wikipedia.org/wiki/Discrete_mathematics)
