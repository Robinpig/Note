## Introduction

数学分析以**极限**为基石，严格研究实数、函数、级数、连续与微积分。它是把「无穷小」「面积」「斜率」这些直觉变成可证明结论的学科——[微积分](/docs/Mathematics/Calculus.md) 是它最直观的应用入口，而分析的严格性保证了 ML 优化与数值方法的可靠性。

本笔记给出分析的 CS 视角；连续的语言也是 [拓扑学](/docs/Mathematics/Topology.md) 的来源，集合语言见 [集合论与数理逻辑](/docs/Mathematics/Set_Theory_Logic.md)。

## Real Number System

实数系 ℝ 的关键性质是**完备性**（任一有上界的非空集合有最小上界）。这是分析得以成立的根本：没有完备性，极限可能「跑出」数系。有理数 ℚ 不完备，因此必须在 ℝ 上做分析。

## Limits and Continuity

$$
\lim_{x\to a} f(x)=L \iff \forall\varepsilon>0,\exists\delta>0,\ |x-a|<\delta\Rightarrow|f(x)-L|<\varepsilon
$$

- **连续**：极限等于函数值；连续函数的复合仍连续。
- **一致连续**：δ 只依赖 ε，不依赖点——数值方法中关心它以保证全局误差可控。

## Series and Convergence

无穷级数 $\sum a_n$ 的研究围绕「收敛还是发散」：绝对收敛、条件收敛、幂级数、傅里叶级数。收敛性决定了算法（如迭代、梯度下降）是否会稳定到一个值。

## Metric Space

把「距离」抽象为度量 $d(x,y)$，连续性、收敛、紧性都可在任意度量空间定义。这是从 ℝ 推广到高维与函数空间（如神经网络的参数空间）的关键一步，也是 [拓扑学](/docs/Mathematics/Topology.md) 的雏形。

## Relationship with Calculus

[微积分](/docs/Mathematics/Calculus.md) 提供求导、积分的工具与直觉；[数学分析](/docs/Mathematics/Real_Analysis.md) 为这些工具补上严格的极限定义、收敛条件与定理（中值定理、一致收敛）。工程中常用微积分，但在证明「算法一定收敛」「估计有界」时离不开分析。

## Applications in CS

- **机器学习**：损失函数的连续可微性、梯度下降的收敛性、泛化界的证明。
- **数值分析**：误差界与稳定性依赖级数收敛与一致连续，见 [数值分析](/docs/Mathematics/Numerical_Analysis.md)。
- **信号处理**：傅里叶级数与变换。
- **理论 CS**：可计算性与实数计算复杂度。

## Links

- [Mathematics](/docs/Mathematics/Mathematics.md)
- [Calculus](/docs/Mathematics/Calculus.md)
- [Topology](/docs/Mathematics/Topology.md)
- [Numerical Analysis](/docs/Mathematics/Numerical_Analysis.md)

## References

1. [Real Analysis (Wikipedia)](https://en.wikipedia.org/wiki/Real_analysis)
