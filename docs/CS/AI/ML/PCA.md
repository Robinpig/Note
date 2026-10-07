## Introduction

主成分分析（Principal Component Analysis，PCA）是最经典的**无监督**降维方法：把原始高维特征投影到少数几个"最重要"的正交方向上，用更少的维度尽量保留数据的信息。它解决的问题是：高维数据的**冗余与噪声**（特征间高度相关、维数灾难）以及**可视化**（把几十维压到二维看结构）。

"重要"的衡量标准是**方差**：PCA 寻找让投影后方差最大的方向——方差大意味着数据在这个方向上差异大、信息多。

## Idea

对同一目标有两种等价的理解，推导出的结果相同：

- **最大方差视角**：找一个方向，把数据投影上去后方差最大；第二个主成分在与第一个正交的方向中方差最大，依此类推
- **最小重构误差视角**：找一个低维子空间，使数据投影回原空间后的重建误差最小

两者都指向同一个答案：**协方差矩阵的特征向量**。

## Math

设样本矩阵 $X\in\mathbb{R}^{n\times d}$（n 个样本，d 个特征），PCA 的求解过程：

1. **中心化**：每个特征减去均值，$\tilde{X}=X-\bar{x}$（PCA 对尺度敏感，通常再做标准化）
2. **求协方差矩阵**：

$$
\Sigma=\frac{1}{n}\tilde{X}^T\tilde{X}
$$

3. **特征值分解**：

$$
\Sigma = W\Lambda W^T
$$

其中 $W$ 的列是特征向量（主成分方向），$\Lambda$ 对角线上是对应特征值（各方向上的方差）。

4. **投影**：取特征值最大的前 k 个特征向量 $W_k$，降维结果为：

$$
Z=\tilde{X}\,W_k
$$

第一主成分正是约束优化问题的解——最大化投影方差：

$$
w_1=\arg\max_{\lVert w\rVert=1} w^T\Sigma w
$$

由瑞利商性质，其解为 $\Sigma$ 最大特征值对应的特征向量。

### How Many Dimensions to Retain

- **方差解释率（explained variance ratio）**：前 k 个特征值之和占总特征值的比例，通常累计到 85%~95% 即可
- **碎石图（Scree Plot）**：画特征值递减曲线，取"拐点"
- 直接指定 k 用于可视化（k=2、3）或下游模型

> [!NOTE]
> PCA 与矩阵奇异值分解（SVD）紧密相关：对中心化后的 $\tilde{X}$ 做 SVD，右奇异向量即主成分方向，工程实现多用 SVD 以避免显式构造协方差矩阵。

## Pros and Cons

- **优点**：无监督、无需标签；正交主成分消除特征相关性；有严格的方差最大化最优性；计算高效（SVD）
- **缺点**：只捕获**线性**结构（非线性流形要用核 PCA、t-SNE、UMAP）；方差大 ≠ 对下游任务有判别力（可能把判别方向压掉）；主成分是原特征的线性组合，可解释性下降；对特征尺度与离群点敏感，必须先标准化

## Practice

```python
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

pca = make_pipeline(
    StandardScaler(),          # PCA 前必须标准化
    PCA(n_components=0.95)     # 保留 95% 方差，或直接给整数 k
)
Z = pca.fit_transform(X)
print(pca.named_steps["pca"].explained_variance_ratio_)
```

## Links

- [ML](/docs/CS/AI/ML/ML.md)
- [LDA](/docs/CS/AI/ML/LDA.md)
- [Clustering](/docs/CS/AI/ML/Clustering.md)

## References

1. [机器学习（西瓜书）第10章 降维与度量学习-豆瓣](https://book.douban.com/subject/26708119/)
2. [sklearn PCA 官方文档](https://scikit-learn.org/stable/modules/generated/sklearn.decomposition.PCA.html)
