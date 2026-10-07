## Introduction

线性判别分析（Linear Discriminant Analysis，LDA）是一种**有监督**的降维与分类方法，思想来自 Fisher 判别：找一个投影方向，让样本投影后**同类聚得尽量近（类内散度小），异类离得尽量远（类间散度大）**。

它与主成分分析（[PCA](/docs/CS/AI/ML/PCA.md)）同为经典降维手段，但出发点相反：PCA 无监督、追求方差最大；LDA 有监督、追求判别信息最大。

> [!WARNING]
> NLP 里的主题模型 LDA 指的是 Latent Dirichlet Allocation（潜在狄利克雷分配），与本篇的 Linear Discriminant Analysis 只是缩写相同，完全是两个东西。

## Math

### Binary Classification: Fisher Discriminant

设两类样本的均值向量为 $\mu_0,\mu_1$。投影方向为 $w$，目标是投影后类内距离小、类间距离大，即最大化广义瑞利商：

$$
J(w)=\frac{w^T S_b w}{w^T S_w w}
$$

其中：

- **类内散度矩阵（within-class）**：$\displaystyle S_w=\sum_{i\in 0,1}\sum_{x\in X_i}(x-\mu_i)(x-\mu_i)^T$
- **类间散度矩阵（between-class）**：$\displaystyle S_b=(\mu_0-\mu_1)(\mu_0-\mu_1)^T$

由于 $S_b$ 是秩 1 矩阵，最优方向有闭式解：

$$
w^*=S_w^{-1}(\mu_0-\mu_1)
$$

### Multi-class Classification

C 类情形下 $S_b$ 的秩为 C-1，$S_w$ 秩亏，通过广义特征值问题 $S_b w=\lambda S_w w$ 取前 k 个广义特征向量组成 $W$。**这也决定了 LDA 降维的维度上限是 C-1**——想把 10 类数据降到 5 维做不到。

新样本直接按投影点与各类投影中心的距离分类，也可把降维结果交给其它分类器。

## PCA vs LDA

| | PCA | LDA |
| ------ | ------ | ------ |
| 监督 | 无监督 | 有监督（用标签） |
| 优化目标 | 投影方差最大 | 类间/类内散度比最大 |
| 降维上限 | 最多 min(n-1, d) 维 | 最多 C-1 维（C 为类别数） |
| 适用 | 无标签、重构、可视化 | 分类前的特征压缩 |

实践中常把两者当互补手段：样本无标签只能 PCA；有标签时先 LDA 压到 C-1 维往往比 PCA 更利于分类。

## Pros and Cons

- **优点**：利用标签信息，降维结果对分类更友好；有闭式解，训练快；天然附带一个线性分类器
- **缺点**：降维上限 C-1，不适合深度压缩；只能捕获线性判别结构；依赖"各类协方差近似相同"的隐含假设（强异方差时效果差）；对类不平衡与离群点敏感

## Practice

```python
from sklearn.discriminant_analysis import LinearDiscriminantAnalysis
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

lda = make_pipeline(
    StandardScaler(),
    LinearDiscriminantAnalysis(n_components=2)  # 最多 C-1 维
)
Z = lda.fit_transform(X, y)                     # 有监督，必须传 y
print(lda.predict(X_test))                      # 也可直接当分类器用
```

## Links

- [ML](/docs/CS/AI/ML/ML.md)
- [PCA](/docs/CS/AI/ML/PCA.md)
- [SVM](/docs/CS/AI/ML/SVM.md)

## References

1. [机器学习（西瓜书）第3章 线性模型（3.4 LDA）-豆瓣](https://book.douban.com/subject/26708119/)
2. [sklearn LDA 官方文档](https://scikit-learn.org/stable/modules/generated/sklearn.discriminant_analysis.LinearDiscriminantAnalysis.html)
