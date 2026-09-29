## Introduction

决策树（Decision Tree）是一种模拟"**逐层提问**"过程的树形分类/回归模型：内部节点对应一次特征判断（如"年龄 > 30 ？"），分支对应判断结果，叶子节点对应最终的类别或数值。

它解决的问题是：当你需要**可解释**的模型——不仅要预测对，还要说清"为什么这么预测"时，决策树是最直接的选择，其结构可以直接翻译成 if-then 规则。

## Key Concepts

决策树学习的关键在于：**每次分裂选哪个特征？** 好的特征应该让分裂后的子集"更纯"。衡量纯度的工具有信息熵、信息增益和基尼指数。

### 信息熵 Entropy

熵度量一个随机变量的不确定性，越纯的集合熵越小。数据集 D 中第 k 类样本占比为 $p_k$ 时：

$$
H(D)=-\sum_{k=1}^{K}p_k\log_2 p_k
$$

- 所有样本同类时 $H(D)=0$（最纯）
- 各类均匀分布时熵最大

### 信息增益 Information Gain

用特征 A 划分数据集 D 后熵下降的幅度，ID3 算法以它为选择标准：

$$
g(D,A)=H(D)-H(D\mid A)
$$

其中条件熵 $H(D\mid A)=\sum_{i}\frac{|D_i|}{|D|}H(D_i)$，$D_i$ 是 D 中特征 A 取第 i 个值的子集。

**缺点**：信息增益偏向取值数目多的特征（极端地，用"编号"做特征会把每个子集切到最纯，增益最大却毫无泛化能力）。

### 信息增益比 Gain Ratio

C4.5 算法对上述偏好的修正——用特征自身的取值熵做惩罚项：

$$
g_R(D,A)=\frac{g(D,A)}{H_A(D)},\qquad
H_A(D)=-\sum_{i=1}^{n}\frac{|D_i|}{|D|}\log_2\frac{|D_i|}{|D|}
$$

### 基尼指数 Gini Index

CART 算法的分裂标准，含义是"随机抽两个样本类别不同的概率"，越小越纯：

$$
\mathrm{Gini}(D)=1-\sum_{k=1}^{K}p_k^2
$$

## Algorithms

| 算法 | 分裂标准 | 树结构 | 支持任务 | 备注 |
| ------ | ---------- | -------- | ---------- | ------ |
| ID3 | 信息增益 | 多叉 | 分类 | 只处理离散特征，不能回归 |
| C4.5 | 信息增益比 | 多叉 | 分类 | 支持连续特征，用增益比纠偏 |
| CART | 基尼指数 / 平方误差 | 二叉 | 分类+回归 | sklearn 的默认实现 |

三个算法都采用**贪心**的自顶向下递归划分：每次选当前最优特征分裂，直到子集足够纯（或无特征可用）为止。

- **连续特征处理**（C4.5/CART）：把取值排序，取相邻值的中点做候选切分点，按二分法处理
- **缺失值处理**：C4.5 把样本按概率分配到各个子节点

## Pruning

不加限制的决策树会一路分裂到每个叶子只剩一个样本——训练集 100% 正确，但这是典型的**过拟合**。剪枝（Pruning）通过砍掉分支来简化模型：

- **预剪枝（Pre-pruning）**：生长过程中提前停止，如限制最大深度 `max_depth`、节点最少样本数 `min_samples_split`、分裂最小增益。快，但有"目光短浅"的风险，可能砍掉后续才有价值的分支
- **后剪枝（Post-pruning）**：先生长成完整树，再自底向上把验证集上表现无提升（或损失函数加正则项后更优）的子树替换为叶节点。通常泛化更好，代价是训练开销大

## Pros and Cons

- **优点**：可解释性强，能输出白盒规则；无需归一化；天然处理类别与数值特征；对缺失值不敏感（C4.5）
- **缺点**：单棵树容易过拟合、不稳定（数据微小扰动可能导致完全不同的树）；贪心搜索不保证全局最优；对类别数目多的特征有偏好（ID3）

单棵树不稳的问题正是集成方法（随机森林、GBDT）的出发点——用多棵树投票/加权把方差降下来，详见 [EnsembleLearning](/docs/CS/AI/ML/EnsembleLearning.md)。

## Practice

```python
from sklearn.tree import DecisionTreeClassifier, export_text

tree = DecisionTreeClassifier(
    criterion="gini",     # 或 "entropy"
    max_depth=4,          # 预剪枝：限制深度
    min_samples_leaf=5
)
tree.fit(X_train, y_train)
print(export_text(tree, feature_names=feature_names))  # 导出白盒规则
```

## Links

- [ML](/docs/CS/AI/ML/ML.md)
- [SVM](/docs/CS/AI/ML/SVM.md)
- [KNN](/docs/CS/AI/ML/KNN.md)
- [EnsembleLearning](/docs/CS/AI/ML/EnsembleLearning.md)

## References

1. [机器学习（西瓜书）第4章 决策树-豆瓣](https://book.douban.com/subject/26708119/)
2. [统计学习方法（第2版）第5章 决策树-豆瓣](https://book.douban.com/subject/33437381/)
3. [sklearn 决策树官方文档](https://scikit-learn.org/stable/modules/tree.html)
