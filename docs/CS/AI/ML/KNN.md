## Introduction

K 近邻（K-Nearest Neighbor，KNN）是一种基本的**懒惰学习（Lazy Learning）**算法：它不显式训练模型，而是把训练样本原样存下来，等预测时再临时计算。给定一个新样本，找出训练集中与它最近的 K 个邻居，用这 K 个邻居的多数类别（分类）或平均值（回归）作为预测结果。

它解决的问题是：当你没有一个清晰的数据分布假设，但相信"**物以类聚**"——相似的特征往往对应相似的标签时，KNN 是最直观的基线方法。

## Algorithm

KNN 的三个基本要素：

1. **K 值的选择**：邻居数量
2. **距离度量**：如何衡量样本间的相似度
3. **决策规则**：多数表决（分类）或平均值（回归）

预测流程：

1. 把新样本与训练集中每个样本计算距离
2. 取距离最小的 K 个训练样本
3. 分类：K 个邻居中票数最多的类别即为输出；回归：K 个邻居标签的平均值即为输出

### K 值的选择

- **K 太小**（如 K=1）：决策边界复杂，对噪声敏感，容易**过拟合**
- **K 太大**：远处不相关的样本也参与投票，决策边界过于平滑，容易**欠拟合**
- 实践中 K 取较小的奇数（避免平票），并通过交叉验证选取；K=N（样本总数）时永远输出众数类，完全欠拟合

> [!NOTE]
> 从损失函数角度看，KNN 的多数表决等价于经验风险最小化下的 0-1 损失；K 值越小，模型越复杂。

## Distance Metrics

距离度量决定了"近"的含义，以下 10 种是机器学习里最常用的（p、q 为两个 n 维样本向量）。

#### 1. Euclidean Distance 欧氏距离

最常用的直线距离，对应 L2 范数：

$$
d(p,q)=\sqrt{\sum_{i=1}^n\left(q_i-p_i\right)^2}
$$

#### 2. Chebyshev Distance 切比雪夫距离

各维度差的最大值，对应 L∞ 范数。国际象棋里王的走法就是切比雪夫距离：

二维平面上：

$$
d=\max\left(\left|x_1-x_2\right|,\left|y_1-y_2\right|\right)
$$

n 维空间中：

$$
d=\max_{1\le i\le n}\left|x_i-y_i\right|
$$

它也是闵可夫斯基距离在 p→∞ 时的极限：

$$
d=\lim_{k\to\infty}\left(\sum_{i=1}^n\left|x_i-y_i\right|^k\right)^{1/k}
$$

#### 3. Manhattan Distance 曼哈顿距离

各维度差的绝对值之和，对应 L1 范数。因纽约曼哈顿街区只能横平竖直地走而得名：

$$
d(p,q)=\sum_{i=1}^n\left|q_i-p_i\right|
$$

#### 4. Minkowski Distance 闵可夫斯基距离

欧氏、曼哈顿、切比雪夫距离的统一推广：

$$
d=\left(\sum_{i=1}^n\left|x_i-y_i\right|^p\right)^{1/p}
$$

- p=1 时，为 Manhattan Distance
- p=2 时，为 Euclidean Distance
- p→∞ 时，为 Chebyshev Distance

#### 5. Mahalanobis Distance 马氏距离

考虑特征间**协方差**的距离，能消除量纲和相关性影响：

$$
d(\vec{x},\vec{y})=\sqrt{(\vec{x}-\vec{y})^T\,\Sigma^{-1}\,(\vec{x}-\vec{y})}
$$

其中 $\Sigma$ 是数据的协方差矩阵。Σ 为单位阵时退化为欧氏距离。

#### 6. Bhattacharyya Distance 巴塔查里亚距离

度量两个**概率分布**的重叠程度，常用于分类特征选择、图像处理：

$$
D_B(p,q)=-\ln\sum_{i}\sqrt{p_i\,q_i}
$$

#### 7. Hamming Distance 汉明距离

两个**等长字符串/编码**在对应位置上不同字符的个数，用于纠错编码、DNA 序列比较。例如 `10101` 与 `10010` 的汉明距离为 2。

#### 8. Cosine 余弦相似度

用向量夹角衡量方向相似性，与向量长度无关，文本检索中最常用：

$$
\cos\theta=\frac{\sum_{i=1}^n x_i y_i}{\sqrt{\sum_{i=1}^n x_i^2}\ \sqrt{\sum_{i=1}^n y_i^2}}
$$

> [!TIP]
> 严格说余弦是**相似度**（越大越相似），取 1-cos 后才是距离。

#### 9. Jaccard Similarity Coefficient 杰卡德相似系数

两个**集合**的交集与并集之比，适合稀疏的布尔特征：

$$
J(A,B)=\frac{|A\cap B|}{|A\cup B|}
$$

#### 10. Pearson Correlation Coefficient 皮尔逊相关系数

协方差除以标准差之积，度量两个变量的**线性相关**程度，取值 [-1, 1]：

$$
\rho=\frac{\mathrm{cov}(X,Y)}{\sigma_X\sigma_Y}
$$

## Pros and Cons

### 优点

- 简单好用，容易理解，精度高，理论成熟，既可以用来做分类也可以用来做回归
- 可用于数值型数据和离散型数据
- 训练时间复杂度为 O(n)；无数据输入假定
- 对异常值不敏感

### 缺点

- 计算复杂性高；空间复杂性高
- 样本不平衡问题（即有些类别的样本数量很多，而其它样本的数量很少）
- 一般数值很大的时候不用这个，计算量太大。但是单个样本又不能太少，否则容易发生误分
- 最大的缺点是无法给出数据的内在含义

> [!WARNING]
> 用 KNN 前通常要对特征做**归一化**（如 Min-Max 或 Z-score，见 [FeatureEngineering](/docs/CS/AI/ML/FeatureEngineering.md)），否则取值范围大的特征会主导距离计算。

## Practice

暴力 KNN 预测要遍历全部训练样本，为 O(n·m)；低维数据可用 **KD-Tree / Ball Tree** 索引把查询降到近似 O(log n)，高维（维数灾难）时树结构会退化。

```python
from sklearn.neighbors import KNeighborsClassifier
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

knn = make_pipeline(
    StandardScaler(),                       # 先归一化
    KNeighborsClassifier(n_neighbors=5,     # K 取奇数，交叉验证调优
                         weights="distance") # 距离加权投票
)
knn.fit(X_train, y_train)
print(knn.predict(X_test))
```

## Links

- [ML](/docs/CS/AI/ML/ML.md)
- [SVM](/docs/CS/AI/ML/SVM.md)
- [DecisionTree](/docs/CS/AI/ML/DecisionTree.md)

## References

1. [统计学习方法（第2版）第3章 k 近邻法-豆瓣](https://book.douban.com/subject/33437381/)
2. [k-nearest neighbors algorithm-Wikipedia](https://en.wikipedia.org/wiki/K-nearest_neighbors_algorithm)
3. [sklearn.neighbors 官方文档](https://scikit-learn.org/stable/modules/neighbors.html)
