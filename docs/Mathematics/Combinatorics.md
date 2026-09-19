## Introduction

组合数学研究**计数、安排与结构**：一个集合有多少种排列方式、能否按某种规则安排、某种结构是否必然存在。它是离散数学中最「组合」的一部分，也是算法复杂度与存在性证明的工具箱。

本笔记给出组合的 CS 视角；存在性证明的鸽巢原理见例题 [鸽巢原理](/docs/Mathematics/Pigeonhole%20Principle.md)，计数与离散基础见 [离散数学](/docs/Mathematics/Discrete_Math.md)。

## 基本计数原理

| 原理 | 公式 | 含义 |
| --- | --- | --- |
| 乘法原理 | $|A|\times|B|$ | 分步相乘 |
| 排列 | $P(n,k)=n!/(n-k)!$ | 有序取 k |
| 组合 | $C(n,k)=\binom{n}{k}$ | 无序取 k |
| 容斥原理 | 交并计数修正 | 处理重叠 |
| 生成函数 | 级数编码序列 | 把计数变代数 |

## 鸽巢原理

若把 $m$ 个对象放入 $n$ 个盒子且 $m>n$，则某盒至少含两个对象。朴素却强大：它只证「存在」，不构造具体解，是存在性证明的利器。完整说明见例题 [鸽巢原理](/docs/Mathematics/Pigeonhole%20Principle.md)。

## 图论入口

图（顶点+边）是组合的核心结构：握手定理、欧拉回路、树、平面性都属组合范畴。图论独立成庞大领域，是网络、依赖分析与最短路径的基础，见 [离散数学](/docs/Mathematics/Discrete_Math.md) 与其在 CS 的落点。

## 在 CS 中的落点

- **算法复杂度**：计数下界证明某问题至少多少步，见 [算法](/docs/CS/Algorithms/Algorithms.md)。
- **密码学**：组合设计用于密钥分发与哈希。
- **概率算法**：组合结构上的随机化（如随机图）。
- **存在性**：用鸽巢原理证明哈希必冲突、编码必冗余。

## Links

- [Mathematics](/docs/Mathematics/Mathematics.md)
- [Discrete Math](/docs/Mathematics/Discrete_Math.md)
- [Probability Statistics](/docs/Mathematics/Probability_Statistics.md)
- [Pigeonhole Principle](/docs/Mathematics/Pigeonhole%20Principle.md)

## References

1. [Combinatorics (Wikipedia)](https://en.wikipedia.org/wiki/Combinatorics)
