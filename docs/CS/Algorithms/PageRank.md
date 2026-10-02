## Introduction

PageRank 是 Google 早期用来衡量网页重要性的图算法（Page & Brin, 1998）。核心思想是：**一个网页的权重不只取决于有多少网页链接到它，
还取决于这些来源网页自身有多重要**——被重要页面链接的页面也更重要。它把整个 Web 抽象为一张有向图（页面是节点、超链接是边），
在图上定义一个随机游走模型并迭代求出每个节点的稳定概率。

## Random Surfer Model

设想一个「随机冲浪者」：

- 以较大概率从当前页面沿出链均匀随机地跳到某个页面；
- 以较小概率（damping factor，通常 d=0.85 沿链，1−d=0.15）随机跳到任意页面。

设 PR(p_i) 为页面 i 的 PageRank，M(i) 为所有链接到 i 的页面集合，L(j) 为页面 j 的出链数，N 为总页面数，则：

```
PR(p_i) = (1 − d)/N + d · Σ_{j ∈ M(i)} PR(p_j) / L(j)
```

含义：i 的得分 = 随机跳转贡献的基础分 + 所有链入页面把自己的权重**按出链数均分**后传给 i 的部分。一个页面出链越多，每条链分到的权重越少。

写成矩阵形式：令 A 为按出度归一化的邻接矩阵（列随机），R 为 PageRank 向量，

```
R = (1 − d)/N · 1 + d · Aᵀ R
```

这是马尔可夫链的平稳分布方程，R 即该随机过程的平稳分布（随机冲浪者长期停留在各页面的概率）。

## Why Damping

纯沿链接走会有两个问题：

- **出度为 0 的页面（sink / dangling node）**会吞掉所有权重，随机游走卡死；
- 页面可能形成封闭子图，分布无法收敛到唯一解。

随机跳转项（1−d）保证转移矩阵每个位置都为正、不可约且非周期，由 Perron–Frobenius 定理保证平稳分布**唯一存在**且与初值无关；
工程上 dangling node 通常先把它的权重均分给所有页面再迭代。

## Computation

直接解线性方程/求主特征向量代价高，实践用**幂迭代（power iteration）**：

```
初始化每个页面 PR = 1/N
重复:
    对每个页面 i，用上一轮的 PR 按公式计算新值
    归一化（使总和为 1）
直到所有页面变化量之和 < ε 收敛
```

- 每次迭代 O(E)（E 为边数），通常几十轮即可收敛，可用 [MapReduce](/docs/CS/Distributed/MapReduce.md) / 分布式矩阵计算处理数十亿页面；
- 收敛速度与 d 有关，d 越接近 1 收敛越慢。

## Applications and Variants

- 搜索引擎排序（作为众多信号之一，已非唯一依据）；
- 社交网络用户影响力、论文引用网络、推荐系统中的节点重要性；
- TrustRank（从可信种子出发）、主题敏感 PageRank（按主题多向量）、Personalized PageRank（个性化随机跳转向量）；
- 与 [HITS](https://en.wikipedia.org/wiki/HITS_algorithm)（hub/authority 双分数）同属链接分析算法。

PageRank 属于在[图](/docs/CS/Algorithms/graph/graph.md)上做随机游走/线性代数计算的代表，与最短路径、最小生成树等组合型图算法思路不同。

## Links

- [algorithm analysis](/docs/CS/Algorithms/Algorithms.md?id=algorithm-analysis)
- [graph](/docs/CS/Algorithms/graph/graph.md)

## References

1. [The PageRank Citation Ranking: Bringing Order to the Web](http://ilpubs.stanford.edu:8090/422/)
2. [PageRank - Wikipedia](https://en.wikipedia.org/wiki/PageRank)
