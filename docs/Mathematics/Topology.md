## Introduction

拓扑学研究在**连续变形（拉伸、弯曲，但不撕裂、不粘连）**下保持不变的性质：连通性、紧性、同胚。它常被称作「橡皮泥几何」——一个咖啡杯与一个甜甜圈在拓扑上等价（都有一个「洞」）。

本笔记给出拓扑的 CS 视角；它与几何的区别在于「不关心距离，只关心粘连与连通」；连续与极限的语言见 [数学分析](/docs/Mathematics/Real_Analysis.md)，离散结构见 [离散数学](/docs/Mathematics/Discrete_Math.md)。

## Core Concepts

| 概念 | 直观 |
| --- | --- |
| 拓扑空间 | 用「开集」定义邻近关系，不必有距离 |
| 连续映射 | 开集的原像仍是开集（保邻近） |
| 同胚 homeomorphism | 双向连续的一一对应；拓扑等价 |
| 紧性 compactness | 「有限覆盖性质」；有界闭集的推广 |
| 连通性 connectedness | 不能拆成两个不相交非空开集 |

拓扑不关心「多长」，只关心「是否连在一起、有没有洞」。因此球面与立方体同胚，但它们都与环面不同胚（洞数不同）。

## Topology vs Geometry

几何需要度量（距离、角度），拓扑不需要。几何问「这两边相等吗」，拓扑问「这块区域被分成几块」。两者是互补视角：几何给局部精确形状，拓扑给全局不变结构。

## Point-Set Topology and Algebraic Topology

- **点集拓扑**：研究开集、闭集、紧、连通、分离公理，是分析学的基石（[数学分析](/docs/Mathematics/Real_Analysis.md) 中的极限与连续都建立在拓扑直觉上）。
- **代数拓扑**：用群等代数不变量（同伦群、同调群）区分空间——把「形状」翻译成「代数结构」，是 [代数](/docs/Mathematics/Algebra.md) 与拓扑的交叉。

## Applications in CS

- **数据流与网络拓扑**：这里的「拓扑」常指连接结构（图），虽是图论而非点集拓扑，但共享「只关心连接、不关心几何距离」的精神，见 [离散数学](/docs/Mathematics/Discrete_Math.md)。
- **机器学习**：流形学习假设数据分布在低维流形上；拓扑数据分析（TDA）用持续同调刻画数据结构。
- **芯片与电路**：布局布线中的平面性与连通性。
- **分布式系统**：网络的连通性决定故障传播与分区容错，见 [分布式系统](/docs/CS/Distributed/Distributed.md)。

## Links

- [Mathematics](/docs/Mathematics/Mathematics.md)
- [Geometry](/docs/Mathematics/Geometry.md)
- [Real Analysis](/docs/Mathematics/Real_Analysis.md)
- [Discrete Math](/docs/Mathematics/Discrete_Math.md)

## References

1. [Topology (Wikipedia)](https://en.wikipedia.org/wiki/Topology)
