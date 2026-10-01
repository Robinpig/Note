## Introduction

线性模型（Linear Model）是一类**用特征线性组合做预测**的模型，形式简单：

$$
f(\vec{x})=w^T\vec{x}+b
$$

它解决的问题是一切预测任务的"第一块基石"：参数少、训练快、系数可以直接当特征重要性解读，也是理解神经网络（每一层都是线性变换 + 非线性激活）与 [SVM](/docs/CS/AI/ML/SVM.md)、逻辑回归等方法的公共起点。

"简单"不等于"弱"：特征足够好时，线性模型仍是工业界大规模稀疏场景（广告、推荐粗排）的主力；它也是[集成学习](/docs/CS/AI/ML/EnsembleLearning.md)中 stacking 常用的元学习器。

## Linear Regression

线性回归（Linear Regression）用均方误差（MSE）衡量预测与真实的差距，基于最小化 MSE 的**最小二乘法（Least Square）**求解：

$$
J(w,b)=\frac{1}{2}\sum_{i=1}^{n}\left(w^T x_i+b-y_i\right)^2
$$

令偏导为零可得**闭式解**（矩阵形式）：

$$
w=(X^TX)^{-1}X^Ty
$$

几何上，最小二乘等价于在由各特征张成的空间里找 y 的正交投影。当特征数多于样本数或特征强相关时 $X^TX$ 不可逆，需要正则化兜底。

## Regularization

在损失函数上加惩罚项，抑制过大的系数，是线性模型对抗过拟合的标准手段：

| 方法 | 惩罚项 | 效果 |
| ------ | -------- | ------ |
| Ridge（L2） | $\lambda\lVert w\rVert_2^2$ | 系数整体收缩，仍保留全部特征，有闭式解 |
| Lasso（L1） | $\lambda\lVert w\rVert_1$ | 把部分系数压到 0，**自动特征选择（稀疏解）** |
| ElasticNet | L1 + L2 混合 | 兼顾收缩与稀疏，相关特征可成组保留 |

L1 产生稀疏解的原因：L1 在顶点处不可导，最优解容易落在坐标轴上（部分系数恰好为 0）。

## Logistic Regression

逻辑回归（Logistic Regression，对数几率回归）在线性输出上套一个 sigmoid，把任意实数映射到 (0,1) 当作概率——名字叫"回归"，实际是**分类**模型：

$$
P(y=1\mid x)=\sigma(w^Tx+b),\qquad \sigma(z)=\frac{1}{1+e^{-z}}
$$

训练用极大似然估计，对应交叉熵损失（见 [ML](/docs/CS/AI/ML/ML.md) 损失函数一节）：

$$
L=-\frac{1}{n}\sum_{i=1}^{n}\left[y_i\ln p_i+(1-y_i)\ln(1-p_i)\right]
$$

它是**线性分类器**：决策边界 $w^Tx+b=0$ 是超平面，与 SVM 的区别只在损失函数（交叉熵 vs Hinge）——逻辑回归输出概率、SVM 只输出间隔。

多分类时用 One-vs-Rest 拆成多个二分类器，或直接用 softmax 回归。

## Pros and Cons

- **优点**：训练快、可扩展到海量样本；系数即解释（+1 岁风险变多少），合规场景友好；输出概率便于设阈值；对内存要求低
- **缺点**：只能刻画线性关系，非线性需要手动做特征变换/交叉；对多重共线性敏感（Ridge 可缓解）；逻辑回归面对强非线性或高阶交互数据精度不敌树模型

## Practice

```python
from sklearn.linear_model import LinearRegression, Ridge, Lasso, LogisticRegression
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

reg = make_pipeline(StandardScaler(), Ridge(alpha=1.0))     # 或 Lasso / LinearRegression
reg.fit(X_train, y_train)

clf = make_pipeline(StandardScaler(), LogisticRegression(C=1.0))
clf.fit(X_train, y_train)
print(clf.predict_proba(X_test)[:3])                        # 输出概率
```

> [!NOTE]
> 系数大小受特征尺度影响，解读权重前先把特征标准化；Lasso 的稀疏性可用 `LassoCV` 自动选正则强度。

## Links

- [ML](/docs/CS/AI/ML/ML.md)
- [LDA](/docs/CS/AI/ML/LDA.md)
- [SVM](/docs/CS/AI/ML/SVM.md)

## References

1. [机器学习（西瓜书）第3章 线性模型-豆瓣](https://book.douban.com/subject/26708119/)
2. [sklearn Linear Models 官方文档](https://scikit-learn.org/stable/modules/linear_model.html)
