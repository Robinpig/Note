## Introduction

Scikit-Learn 是 Python 生态最流行的经典机器学习库：建立在 NumPy / SciPy 之上，把常见算法（[线性模型](/docs/CS/AI/ML/LinearModel.md)、[SVM](/docs/CS/AI/ML/SVM.md)、[决策树](/docs/CS/AI/ML/DecisionTree.md)、[聚类](/docs/CS/AI/ML/Clustering.md)等）和配套工具（预处理、交叉验证、调参、评估）收敛到**一套统一接口**之下。

它解决的问题不是"算法新"，而是"流程顺"：换模型只改一行代码，预处理与建模无缝拼装，实验可以快速复现。深度学习场景（GPU、自动微分、动态网络）则交给 [PyTorch](/docs/CS/AI/PyTorch.md)、[TensorFlow](/docs/CS/AI/TensorFlow.md)——两者定位互补而非替代。

## API Contract

Scikit-Learn 一切对象都遵循 Estimator 契约，学会一套 API 就会用整个库：

| 方法 | 作用 | 适用的对象 |
| ------ | ------ | ------ |
| `fit(X, y)` | 从数据学习参数 | 所有模型、预处理器 |
| `predict(X)` | 输出预测值 | 分类 / 回归模型 |
| `predict_proba(X)` | 输出类别概率 | 支持概率输出的分类器 |
| `transform(X)` | 变换数据 | 预处理器、降维 |
| `fit_transform(X)` | fit 后接 transform（常更高效） | 预处理器、降维 |

配套约定还有：`get_params() / set_params()` 支持程序化调参与克隆；模型对象即超参数的载体，构造时传参、fit 时才碰数据。按角色分三类：**Estimator**（模型）、**Transformer**（变换）、**Pipeline**（把前者串起来）。

## Module Map

按功能找模块，基本能覆盖经典机器学习全流程：

| 模块 | 内容 | 本库对应笔记 |
| ------ | ------ | ------ |
| `preprocessing` | 缩放、编码、分箱 | [FeatureEngineering](/docs/CS/AI/ML/FeatureEngineering.md) |
| `impute` | 缺失值填充 | [FeatureEngineering](/docs/CS/AI/ML/FeatureEngineering.md) |
| `model_selection` | 切分、交叉验证、网格搜索 | 下文 Evaluation / Tuning |
| `linear_model` | 线性回归、Ridge、Lasso、[逻辑回归](/docs/CS/AI/ML/LinearModel.md) | LinearModel |
| `neighbors` | [KNN](/docs/CS/AI/ML/KNN.md)、KD-Tree | KNN |
| `svm` | [SVC / SVR](/docs/CS/AI/ML/SVM.md) | SVM |
| `tree` / `ensemble` | [决策树](/docs/CS/AI/ML/DecisionTree.md)、[随机森林、GBDT](/docs/CS/AI/ML/EnsembleLearning.md) | DecisionTree / EnsembleLearning |
| `cluster` | [k-means、DBSCAN、层次聚类](/docs/CS/AI/ML/Clustering.md) | Clustering |
| `decomposition` | [PCA](/docs/CS/AI/ML/PCA.md)、NMF | PCA |
| `metrics` | 准确率、F1、AUC、MSE、轮廓系数 | [ML 评价指标](/docs/CS/AI/ML/ML.md) |
| `pipeline` / `compose` | 流水线、ColumnTransformer | [特征工程·泄漏防范](/docs/CS/AI/ML/FeatureEngineering.md) |

## Evaluation

模型评估的基础设施都集中在 `model_selection`：

```python
from sklearn.model_selection import train_test_split, cross_val_score

X_tr, X_te, y_tr, y_te = train_test_split(X, y, test_size=0.2, random_state=42)

scores = cross_val_score(model, X_tr, y_tr, cv=5, scoring="f1_macro")
print(scores.mean(), scores.std())     # 5 折交叉验证的均值与波动
```

- 分类指标：`accuracy_score`、`precision_score`、`recall_score`、`f1_score`、`roc_auc_score`
- 回归指标：`mean_squared_error`、`mean_absolute_error`、`r2_score`
- 聚类内部指标：`silhouette_score`（见 [Clustering](/docs/CS/AI/ML/Clustering.md) 评估一节）

> [!TIP]
> `cross_val_score` 只做评估；`cross_validate` 还能返回 fit/predict 耗时与多条指标，更常用于实验报告。

## Tuning

超参数搜索的两个标准工具：

```python
from sklearn.model_selection import GridSearchCV, RandomizedSearchCV

grid = GridSearchCV(
    estimator=SVC(),
    param_grid={"C": [0.1, 1, 10], "gamma": ["scale", 0.01, 0.1]},
    cv=5, n_jobs=-1
).fit(X_tr, y_tr)
print(grid.best_params_, grid.best_score_)
```

- **GridSearchCV**：穷举 `param_grid` 的笛卡尔积，小空间首选
- **RandomizedSearchCV**：按分布采样，大空间（尤其连续超参）性价比更高
- 搜索内部自带交叉验证，`best_estimator_` 可直接用于测试集；调参只能在验证层做，测试集留到最后碰

## Pipeline

[Pipeline](/docs/CS/AI/ML/FeatureEngineering.md) 把多个 Transformer 与一个 Estimator 串成单一对象，带来两个关键收益：

1. **防泄漏**：`fit` 只在训练数据上执行，交叉验证每一折都独立重新 fit 预处理——统计量不会从验证折渗入训练折
2. **可移植**：整个"预处理 + 模型"一起 `save / load / deploy`，避免线上线下处理不一致

跨列异构处理用 `ColumnTransformer`（数值列缩放填充、类别列编码），完整示例见 [FeatureEngineering](/docs/CS/AI/ML/FeatureEngineering.md) 的 Practice。

## Pros and Cons

- **优点**：API 统一、上手快、文档质量高；覆盖经典 ML 全流程；Pipeline/ColumnTransformer 工程化成熟；社区生态（与 pandas、joblib、XGBoost 等无缝衔接）
- **缺点**：不做 GPU 加速与深度学习训练；对超大数据集（内存装不下的表）需要 Dask-ML 等扩展；强化学习、图学习等新范式不在其范围

## Links

- [AI](/docs/CS/AI/AI.md)
- [ML](/docs/CS/AI/ML/ML.md)
- [PyTorch](/docs/CS/AI/PyTorch.md)
- [TensorFlow](/docs/CS/AI/TensorFlow.md)

## References

1. [scikit-learn Getting Started 官方文档](https://scikit-learn.org/stable/getting_started.html)
2. [scikit-learn User Guide 官方文档](https://scikit-learn.org/stable/user_guide.html)
3. [Cross-validation 官方文档](https://scikit-learn.org/stable/modules/cross_validation.html)
4. [Tuning the hyper-parameters 官方文档](https://scikit-learn.org/stable/modules/grid_search.html)
