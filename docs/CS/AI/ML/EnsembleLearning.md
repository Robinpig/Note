## Introduction

集成学习（Ensemble Learning）通过**构建并结合多个学习器来完成学习任务**，也就是俗话说的"三个臭皮匠，顶个诸葛亮"。它解决的问题正是[决策树](/docs/CS/AI/ML/DecisionTree.md)这样的单模型的痛点：不稳定、容易过拟合——用多棵树投票/加权，把方差或偏差降下来。

集成里的个体学习器通常称为基学习器（base learner）。集成的效果取决于两个条件：个体要"**好**"（有一定的准确度），而且要"**不同**"（有多样性，犯错的地方互相错开）。

按个体学习器的生成方式，三大流派：

- **Bagging**：并行训练，个体互相独立，靠"平均"降方差
- **Boosting**：串行训练，后一个模型重点纠正前一个的错误，靠"累加"降偏差
- **Stacking**：分层组合，用一个学习器去学习"怎么组合"其它学习器

## Bagging

Bagging（Bootstrap AGGregatING）对训练集做 T 次**自助采样（Bootstrap）**——有放回地抽 n 个样本，得到 T 个不同的子集，各训练一个基学习器，最后分类用投票、回归取平均。

每个子集约包含 63.2% 的原样本（1-1/e），没被抽到的样本叫**包外（Out-of-Bag，OOB）样本**，可直接用 OOB 估计泛化误差，省去交叉验证。

### Random Forest

随机森林（Random Forest，RF）= Bagging + 决策树，并在每个节点分裂时再加一层随机：只从**随机抽取的部分特征**（分类通常 $\sqrt{d}$ 个）中选最优分裂。

- 样本随机 + 特征随机的"双重随机"，让树与树之间差异更大，方差降得更狠
- 天然支持并行训练、给出特征重要性

## Boosting

Boosting 的串行逻辑：先训练一个基学习器，看它在哪些样本上错了，下一个学习器就**重点关注这些错误**，如此迭代，最后把所有学习器加权结合。从偏差-方差视角看，Boosting 主要降低**偏差**（Bagging 主要降低**方差**）。

### AdaBoost

AdaBoost（Adaptive Boosting）用**重赋权**实现"关注错误"：每一轮提高被错分样本的权重、降低分对样本的权重；错分率越低的学习器，在最终表决中的话语权越大：

$$
\alpha_t=\frac{1}{2}\ln\frac{1-\epsilon_t}{\epsilon_t}
$$

其中 $\epsilon_t$ 是第 t 个基学习器的加权错分率，$\alpha_t$ 是其结合系数。

### GBDT

梯度提升树（Gradient Boosting Decision Tree，GBDT）把"关注错误"推广成**拟合损失函数的负梯度**：每一轮新树去拟合当前模型的残差近似（回归下就是拟合残差），逐步累加：

$$
F_T(x)=\sum_{t=1}^{T}\nu\, h_t(x),\qquad \nu\in(0,1] \text{ 为学习率}
$$

在此基础上：

- **XGBoost** 在目标函数中引入二阶泰勒展开与正则化项，工程上支持列采样、缺失值处理，是竞赛与工业界的常青树
- **LightGBM** 用直方图算法与叶子优先（leaf-wise）生长进一步提速，适合大数据集

## Stacking

Stacking（分层集成）训练**两层**学习器：第一层多个基学习器先用**交叉验证**产生预测（避免用训练数据自预测造成信息泄漏），把它们的输出作为新特征；第二层的**元学习器（meta learner）**再基于这些特征学习最终组合方式。

优点是能自动学到"谁擅长哪块"，常用于把异质模型（树模型 + 线性模型 + KNN）组合起来；缺点是流程复杂、易过拟合，且推理开销是各层之和。

## Bagging vs Boosting

| | Bagging | Boosting |
| ------ | ------ | ------ |
| 训练方式 | 并行，个体独立 | 串行，前后依赖 |
| 关注点 | 降低方差 | 降低偏差 |
| 样本使用 | Bootstrap 重采样 | 全量数据，权重/梯度调整 |
| 结合方式 | 投票/平均 | 加权累加 |
| 代表 | 随机森林 | AdaBoost、GBDT、XGBoost |
| 基学习器偏好 | 强而复杂的模型（深树） | 弱学习器（浅树） |

## Pros and Cons

- **优点**：竞赛与表格数据任务的第一梯队，泛化能力显著优于单模型；随机森林并行易用，GBDT 系精度天花板高；能输出特征重要性
- **缺点**：可解释性不如单棵树（需借助 SHAP 等工具）；Boosting 系串行训练、推理开销大；超参数多、调参成本高；在超大稀疏特征（如大规模推荐特征）上不一定打得过深度模型或线性模型

## Practice

```python
from sklearn.ensemble import RandomForestClassifier, GradientBoostingClassifier

rf = RandomForestClassifier(n_estimators=300, n_jobs=-1, oob_score=True)
rf.fit(X_train, y_train)
print(rf.oob_score_, rf.feature_importances_)   # OOB 评估 + 特征重要性

gbdt = GradientBoostingClassifier(n_estimators=200, learning_rate=0.1, max_depth=3)
gbdt.fit(X_train, y_train)
```

> [!TIP]
> 生产中精度要求高首选 XGBoost / LightGBM；追求开箱即用与并行，先用随机森林拿基线。

## Links

- [ML](/docs/CS/AI/ML/ML.md)
- [DecisionTree](/docs/CS/AI/ML/DecisionTree.md)
- [SVM](/docs/CS/AI/ML/SVM.md)

## References

1. [机器学习（西瓜书）第8章 集成学习-豆瓣](https://book.douban.com/subject/26708119/)
2. [sklearn Ensemble methods 官方文档](https://scikit-learn.org/stable/modules/ensemble.html)
3. [XGBoost 官方文档](https://xgboost.readthedocs.io/en/stable/)
4. [LightGBM 官方文档](https://lightgbm.readthedocs.io/en/stable/)
