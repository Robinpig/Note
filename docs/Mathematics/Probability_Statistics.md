## Introduction

概率论为**随机现象**建数学模型（样本空间、随机变量、分布）；统计学从**观测数据**反推模型与结论（估计、检验、回归）。两者共同构成机器学习与数据科学的数学地基——优化目标常是似然或风险，泛化靠大数定律与中心极限定理。

本笔记给出概率统计的 CS 视角；连续与极限见 [数学分析](/docs/Mathematics/Real_Analysis.md)，计数基础见 [组合数学](/docs/Mathematics/Combinatorics.md)，向量化见 [线性代数](/docs/Mathematics/Linear_Algebra.md)。

## 概率基础

| 概念 | 含义 |
| --- | --- |
| 样本空间 Ω | 所有可能结果 |
| 随机变量 X | 把结果映射到实数 |
| 分布 | X 取各值的概率规律（PMF/PDF/CDF） |
| 期望 E[X] | 加权平均 |
| 方差 Var(X) | 离散程度 |

常见分布：伯努利/二项（离散试验）、正态（中心极限）、泊松（稀有事件）、均匀。

## 大数定律与中心极限

- **大数定律**：样本均值随样本量增大收敛到期望——经验频率可信的理论依据。
- **中心极限定理**：大量独立随机变量之和近似正态——为何噪声常呈钟形，也是统计推断的基石。

## 统计推断

- **参数估计**：用数据估分布参数（极大似然 MLE、贝叶斯）。
- **假设检验**：判断观测是否显著（p 值、置信区间）。
- **回归**：建「输入→输出」关系（最小二乘见 [Linear Algebra](/docs/Mathematics/Linear_Algebra.md)）。

## 在 CS 中的落点

- **机器学习/深度学习**：损失=经验风险，优化=最小化期望风险，泛化由概率不等式（Hoeffding、VC 维）界定，见 [AI](/docs/CS/AI/AI.md)。
- **信息论**：熵、KL 散度源自概率，衡量不确定性与分布距离。
- **随机算法**：哈希、抽样、蒙特卡洛。
- **排队论与性能**：请求到达建模为泊松过程，见 [分布式系统](/docs/CS/Distributed/Distributed.md) 的可观测性。

## Links

- [Mathematics](/docs/Mathematics/Mathematics.md)
- [Discrete Math](/docs/Mathematics/Discrete_Math.md)
- [Calculus](/docs/Mathematics/Calculus.md)
- [Real Analysis](/docs/Mathematics/Real_Analysis.md)
- [Linear Algebra](/docs/Mathematics/Linear_Algebra.md)

## References

1. [Probability Theory (Wikipedia)](https://en.wikipedia.org/wiki/Probability_theory)
