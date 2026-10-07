## Introduction

聚类（Clustering）是**无监督学习**的代表任务：在没有标签的情况下，把样本按相似度分成若干簇（cluster），目标是"**簇内相似度高，簇间相似度低**"。典型应用是用户分群、图像分割、新闻主题归组。

它与分类的根本区别：分类是"照着答案学"（有监督），聚类是"自己找结构"（无监督），因此聚类的"好坏"也没有唯一标准，需结合评价指标与业务含义判断。

按划分思路，常用算法分三类：原型聚类（k-means）、层次聚类（Hierarchical）、密度聚类（DBSCAN）。

## k-means

k-means 是最经典的**原型聚类**算法，用 k 个簇中心（质心 μ）代表 k 个簇。目标是最小化簇内平方误差和（SSE）：

$$
J=\sum_{k=1}^{K}\sum_{x\in C_k}\lVert x-\mu_k\rVert^2
$$

Lloyd 迭代（交替优化）的流程：

1. 随机选 k 个样本作为初始质心
2. **分配**：把每个样本划给距离最近的质心，形成 k 个簇
3. **更新**：把每个簇的均值作为新质心，$\mu_k=\frac{1}{|C_k|}\sum_{x\in C_k}x$
4. 重复 2-3，直到质心不再变化（或达到最大迭代次数）

k-means 本质上是对上式的坐标下降，保证收敛到局部最优（不保证全局最优）。

### Selection of K

- **肘部法（Elbow Method）**：画出 SSE 随 K 的下降曲线，取"拐点"（再增大 K 收益骤减处）
- **轮廓系数（Silhouette Coefficient）**：对样本 i，a 为簇内平均距离、b 为最近其它簇的平均距离，$s(i)=\frac{b-a}{\max(a,b)}\in[-1,1]$，取全数据集平均轮廓系数最高的 K
- 业务先验：如运营本来就规划了 5 类用户

### Pros and Cons and Improvements

- **优点**：简单高效，O(n·k·t)，大数据集上速度快，是最常用的聚类基线
- **缺点**：必须预设 K；对初始质心敏感、只能收敛到局部最优；只能发现"球形"簇，对非凸/大小悬殊的簇失效；对离群点敏感（均值被拉偏）

常见改进：

- **k-means++**：初始质心彼此尽量远（按距离平方加权采样），显著改善结果与收敛速度
- **Mini-Batch k-means**：每次用小批量样本更新质心，牺牲少量精度换大幅提速

## Hierarchical Clustering

层次聚类构建一棵**树状图（dendrogram）**，无需预设 K，最后按高度切一刀得到任意层数的簇：

- **凝聚法（Agglomerative，自底向上）**：每个样本自成一簇，每轮合并距离最近的两个簇，直到只剩一个。簇间距离可取最短（single，易链式）、最长（complete，紧凑）、平均（average）或 Ward（方差增量，sklearn 默认）
- **分裂法（Divisive，自顶向下）**：从一个大簇开始逐层拆分，计算量大，较少使用

优点是结构直观、可展示层级关系；缺点是复杂度约 O(n²)~O(n³)，大数据集跑不动。

## DBSCAN

DBSCAN（Density-Based Spatial Clustering of Applications with Noise）用**密度**定义簇：由密度可达的样本连成簇，能挖出任意形状的簇，并把稀疏点标为噪声。

两个参数：

- **ε（eps）**：邻域半径
- **MinPts（min_samples）**：核心点在 ε 邻域内至少要有多少邻居

样本分三类：核心点（邻域内样本数 ≥ MinPts）、边界点（落在核心点邻域内但自己不够密）、噪声点（其余）。

- **优点**：不需预设簇数；能发现任意形状的簇；对离群点鲁棒（直接标噪声）
- **缺点**：对 ε 与 MinPts 敏感；样本密度不均时效果差；高维下距离度量失效（维数灾难）

## Evaluation

- **内部指标**（无真值）：轮廓系数、DB 指数（Davies-Bouldin，簇间距离/簇内直径，越小越好）、SSE（肘部法）
- **外部指标**（有真值参照）：ARI（调整兰德指数）、NMI（标准化互信息），衡量与已知划分的一致性

## Practice

```python
from sklearn.cluster import KMeans
from sklearn.metrics import silhouette_score
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

Xs = StandardScaler().fit_transform(X)   # 聚类同样要先归一化
for k in range(2, 9):
    labels = KMeans(n_clusters=k, n_init="auto").fit_predict(Xs)
    print(k, silhouette_score(Xs, labels))   # 取轮廓系数最高的 k
```

## Links

- [ML](/docs/CS/AI/ML/ML.md)
- [KNN](/docs/CS/AI/ML/KNN.md)
- [PCA](/docs/CS/AI/ML/PCA.md)

## References

1. [机器学习（西瓜书）第9章 聚类-豆瓣](https://book.douban.com/subject/26708119/)
2. [统计学习方法（第2版）-豆瓣](https://book.douban.com/subject/33437973/)
3. [sklearn Clustering 官方文档](https://scikit-learn.org/stable/modules/clustering.html)
