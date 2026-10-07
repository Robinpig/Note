## Introduction

数值分析研究**如何用有限精度算出近似解**：给定一个问题（方程、积分、线性系统），设计算法、分析误差与稳定性，并在计算机上跑出可靠结果。它架在 [数学分析](/docs/Mathematics/Real_Analysis.md) 与 [线性代数](/docs/Mathematics/Linear_Algebra.md) 之上，是「连续数学」通往「可运行代码」的最后一公里。

本笔记给出数值分析的 CS 视角；求导与积分的工具见 [微积分](/docs/Mathematics/Calculus.md)，矩阵分解见 [Linear Algebra](/docs/Mathematics/Linear_Algebra.md)。

## Sources of Error

| 误差类型 | 来源 | 例子 |
| --- | --- | --- |
| 截断误差 | 用有限过程近似无限过程 | 泰勒展开截断、数值积分 |
| 舍入误差 | 浮点有限精度 | 大数吃小数、catastrophic cancellation |
| 迭代误差 | 迭代中误差累积放大 | 病态矩阵 |

数值方法的评价标准：**精度**（误差多小）、**稳定性**（误差是否放大）、**复杂度**（时间/空间）。

## Numerical Solutions of Linear Systems

- **直接法**：高斯消元 → LU 分解，精确（忽略舍入）但 $O(n^3)$。
- **迭代法**：Jacobi/Gauss-Seidel/共轭梯度，适合稀疏大矩阵（图、有限元）。

[Linear Algebra](/docs/Mathematics/Linear_Algebra.md) 的分解（LU/QR/SVD）是这些方法的结构基础；[MATLAB](/docs/CS/Tool/MATLAB.md) 的 `A\b` 会按矩阵结构自动选型。

## Root-Finding

牛顿法（Newton's method）用切线逼近零点：

$$
x_{k+1}=x_k-\frac{f(x_k)}{f'(x_k)}
$$

收敛快但依赖初值与导数；割线法免去导数。求根是优化（梯度下降的特例）与方程求解的通用范式。

## Interpolation and Fitting

- **插值**：构造曲线严格过给定点（拉格朗日、样条）。
- **拟合/最小二乘**：不过点，只在整体上最接近——无解线性系统时找列空间最近投影，见 [Linear Algebra](/docs/Mathematics/Linear_Algebra.md)。

## Applications in CS

- **图形学与仿真**：物理引擎、有限元、光线追踪都依赖数值解微分方程。
- **机器学习**：反向传播本质是链式法则的数值实现；优化器是数值分析的迭代法。
- **科学计算**：[MATLAB](/docs/CS/Tool/MATLAB.md)、NumPy/LAPACK 底层即数值线性代数。

## Links

- [Mathematics](/docs/Mathematics/Mathematics.md)
- [Calculus](/docs/Mathematics/Calculus.md)
- [Linear Algebra](/docs/Mathematics/Linear_Algebra.md)
- [Real Analysis](/docs/Mathematics/Real_Analysis.md)

## References

1. [Numerical Analysis (Wikipedia)](https://en.wikipedia.org/wiki/Numerical_analysis)
