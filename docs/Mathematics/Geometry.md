## Introduction

几何研究**形状、大小、相对位置与变换**。它是最古老的数学分支之一，从丈量土地到描述时空，贯穿工程与物理。对 CS 而言，几何在图形学、GIS、机器人运动规划与机器学习流形中不可或缺。

本笔记给出几何的 CS 视角骨架；变换的代数化见 [Linear Algebra](/docs/Mathematics/Linear_Algebra.md)，整体形状的研究见 [拓扑学](/docs/Mathematics/Topology.md)，变化率见 [微积分](/docs/Mathematics/Calculus.md)。

## Plane and Solid Geometry

- **点**：无维度的位置，用大写字母标记。
- **线**：一维，由两个不重合点确定唯一一条。
- **面/平面**：二维无限延展的平坦表面，由三个不共线点命名。
- **体**：三维实体，分为多面体（面为多边形）与非多面体（含曲面，如球、柱）。

这是欧几里得几何的直观对象，也是图形学中「顶点—边—面」网格的源头。

## Analytic Geometry

解析几何（坐标几何）用代数与坐标系研究几何：把点写成坐标、把曲线写成方程，从而把几何问题转化为代数运算。它是工程师与物理学家最常用的几何分支——[Linear Algebra](/docs/Mathematics/Linear_Algebra.md) 中的变换矩阵正是解析几何的运算化。

## Euclidean and Non-Euclidean Geometry

| 类型 | 平行公设 | 典型空间 |
| --- | --- | --- |
| 欧氏几何 | 过直线外一点有且仅有一条平行线 | 平面 |
| 球面几何 | 不存在平行线（大圆必交） | 球面 |
| 双曲几何 | 有无穷多条平行线 | 伪球面 |

非欧几何把「平行公设」换成别的版本，得到完全不同的空间——这正是广义相对论中时空模型的数学背景，也说明几何结论依赖于所选公理，与 [集合论与数理逻辑](/docs/Mathematics/Set_Theory_Logic.md) 中「公理决定真理」一致。

## Differential Geometry

微分几何用微积分研究弯曲空间（流形）：在每一点的切空间上做局部线性近似，再用拓扑粘起来。它是计算机图形学（曲面参数化）、机器人学（位形空间）与深度学习（流形学习、信息几何）的工具。

## Applications in CS

- **计算机图形学**：模型矩阵、视图矩阵、投影矩阵把三维点变换到屏幕；四元数处理旋转避免万向锁。
- **GIS 与计算几何**：点定位、凸包、最近点对、路径规划。
- **机器学习**：流形假设（高维数据近似低维流形）、信息几何。
- **机器人**：运动学中的位形空间与避障。

## Links

- [Mathematics](/docs/Mathematics/Mathematics.md)
- [Linear Algebra](/docs/Mathematics/Linear_Algebra.md)
- [Topology](/docs/Mathematics/Topology.md)
- [Calculus](/docs/Mathematics/Calculus.md)

## References

1. [Euclidean Geometry (Wikipedia)](https://en.wikipedia.org/wiki/Euclidean_geometry)
