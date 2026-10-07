## Introduction

线性代数研究**向量空间、线性映射与有限维线性方程组**。它是把「一堆数之间的线性关系」变成可计算对象的数学，也是计算机科学中应用密度最高的数学分支：图形学的变换、机器学习的特征与权重、推荐系统的矩阵分解、搜索引擎的向量检索，底层都是同一套对象——矩阵。

本笔记给出 CS 视角的核心骨架；与微积分的关系见 [Calculus](/docs/Mathematics/Calculus.md)，应用见 [CNN](/docs/CS/AI/CNN.md)（卷积/张量）与 [MATLAB](/docs/CS/Tool/MATLAB.md)（矩阵运算工程化）。

## Core Objects

| 对象 | 直观含义 |
| --- | --- |
| 向量 | 空间中的一个点/一个箭头，也是一列有序特征 |
| 矩阵 | 一张数表；几何上是一个**线性变换** |
| 线性方程组 Ax=b | 「哪个向量 x 经变换 A 后得到 b」 |
| 线性无关 / 基 / 维数 | 一组向量能否张成空间、最少需要几个 |
| 秩 rank | 变换后空间的真实维数（行/列空间维数） |
| 行列式 det | 变换对体积的**缩放因子**（为 0 表示塌缩到低维） |
| 特征值/特征向量 | 变换方向不变只伸缩的轴：Av=λv |

行列式的几何意义在 [Mathematics](/docs/Mathematics/Mathematics.md) 笔记已有图示：`det = ad-bc`，为 0 表示向量被压到同一平面/直线/点，负值表示空间定向翻转。

## Three Perspectives: Systems of Equations / Matrix / Linear Transformations

同一个问题的三种视角，是理解线代的关键：

1. **方程组视角**：求 m 个线性方程的公共解，用高斯消元（行变换 → 行阶梯形）。
2. **矩阵视角**：关注秩、逆、矩阵分解，研究「这张表的结构」。
3. **变换/几何视角**：矩阵是对空间的旋转、缩放、投影；理解特征值、相似对角化、SVD 的入口。

例如 `Ax=b`，方程视角是「解线性系统」，几何视角是「变换 A 把哪个向量送到 b」。当 A 不可逆（秩亏、det=0）时解可能不存在或不唯一——这正是最小二乘要解决的问题：无解时在列空间上找最近投影 $A\hat{x}\approx b$。

## Key Decomposition

| 分解 | 形式 | 用途 |
| --- | --- | --- |
| LU 分解 | A=LU | 反复解不同右端项，加速高斯消元 |
| QR 分解 | A=QR | 最小二乘、数值稳定 |
| 特征分解 | A=PDP⁻¹ | 可对角化时看主方向、算矩阵幂 |
| **SVD** | A=UΣVᵀ | **任意矩阵**都可做；降维、PCA、推荐、压缩、伪逆 |

SVD 是工程上最重要的分解：它把任意线性变换拆成「旋转 → 沿坐标轴缩放 → 再旋转」，奇异值衡量各方向的信息量，截断小奇异值即得低秩近似（PCA 的另一种表述）。

## Applications in CS

- **图形学**：模型/视图/投影矩阵把三维点一路变换到屏幕像素；四元数处理旋转。
- **机器学习/深度学习**：数据是特征向量、权重是矩阵、全连接层就是 `y=Wx+b`；反向传播依赖多元微积分 + 张量运算，见 [CNN](/docs/CS/AI/CNN.md)。
- **信息检索/推荐**：文档-词项矩阵 + SVD（潜在语义分析）、协同过滤。
- **数值计算**：[MATLAB](/docs/CS/Tool/MATLAB.md) 以反斜杠 `A\b` 根据矩阵结构自动选择求解算法。
- **图论/随机过程**：邻接矩阵、转移矩阵的特征值刻画网络性质（PageRank）。

## Links

- [Mathematics](/docs/Mathematics/Mathematics.md)
- [Algebra](/docs/Mathematics/Algebra.md)
- [Calculus](/docs/Mathematics/Calculus.md)
- [CNN](/docs/CS/AI/CNN.md)
- [MATLAB](/docs/CS/Tool/MATLAB.md)

## References
