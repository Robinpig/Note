## Introduction

Scikit-Learn 是 Python 生态最流行的经典机器学习库：建立在 NumPy / SciPy 之上，把常见算法（[线性模型](/docs/CS/AI/ML/LinearModel.md)、[SVM](/docs/CS/AI/ML/SVM.md)、[决策树](/docs/CS/AI/ML/DecisionTree.md)、[聚类](/docs/CS/AI/ML/Clustering.md)等）和配套工具（预处理、交叉验证、调参、评估）收敛到**一套统一接口**之下。

它解决的问题不是"算法新"，而是"流程顺"：换模型只改一行代码，预处理与建模无缝拼装，实验可以快速复现。深度学习场景（GPU、自动微分、动态网络）则交给 [PyTorch](/docs/CS/AI/PyTorch.md)、[TensorFlow](/docs/CS/AI/TensorFlow.md)——两者定位互补而非替代。

它的设计哲学值得单独点出：**约定优于配置**。所有对象共享同一组方法名（`fit` / `predict` / `transform`）、同一套参数管理机制（`get_params` / `set_params`）、同一套校验工具（`check_array` / `check_is_fitted`）。这套约定让"把某个算法换成另一个"成为纯粹的对象替换，而把"把流程调对"变成写一条 `Pipeline`。本篇按这个约定逐层展开：先看接口契约，再看模块地图，然后是评估、调参、流水线，最后落到工程落地最常被忽略的几块——数据互操作、自定义 Estimator、持久化、可解释性与陷阱。

## Version Baseline

当前稳定版为 **1.9.1**（2026-09-11 发布），BSD-3 许可，由 NumFOCUS 基金会托管。几个影响工程决策的硬事实：

| 项目 | 事实 |
| ------ | ------ |
| 稳定版本 | 1.9.1（1.9.0 于 2026-06 发布） |
| Python 要求 | 自 1.8.0 起要求 **Python ≥ 3.11** |
| 依赖 | NumPy、SciPy、joblib、threadpoolctl；绘图另需 matplotlib |
| 许可 | BSD-3-Clause（可商用、闭源友好） |
| 维护节奏 | 约每半年一个 minor（1.7 → 1.8 → 1.9），minor 之间穿插 patch 修复 |

版本号本身不是重点，**升级时哪些行为会变**才是。1.9 里值得记的几件事：

- **Callbacks API** 新增（`sklearn.callback.ProgressBar`、`ScoringMonitor`），可挂到 `Pipeline`、`GridSearchCV`、`LogisticRegression(solver="lbfgs")` 等对象上观察训练过程。官方明确标注它**仍是实验性**，不走常规弃用周期。
- **稀疏接口可切换**：`sklearn.set_config(sparse_interface="sparray")` 让相关函数返回 SciPy 稀疏**数组**而非稀疏**矩阵**。当前默认值仍是 `"spmatrix"`，官方计划未来改默认值——依赖 `spmatrix` 具体行为的代码升级时要注意。
- **DataFrame 支持换底层**：1.9 引入轻量依赖 **narwhals** 统一处理 `set_output` 下的 pandas 与 **Polars** DataFrame 输入输出（此前依赖的 `__dataframe__` 协议已被 Polars 弃用）。
- **元数据路由大幅增强**（详见后文 Metadata Routing），1.9.1 修复了一批复合估计器静默丢弃 `sample_weight` 的问题。
- **面向 1.11 的弃用预告**：`LogisticRegressionCV` 的默认 `scoring` 将从 `None`（准确率）改为 `"neg_log_loss"`；`TargetEncoder` 的 `shuffle` / `random_state`、`SVC` / `NuSVC` 的 `probability` 均已弃用并计划在 1.11 移除。

> [!WARNING]
> 这些弃用项不是"未来某天会变"，而是**现在就要按新写法写**。`SVC(probability=True)` 的替代方案是 `CalibratedClassifierCV(estimator, ensemble=False)`；`TargetEncoder` 的随机性改由 `cv` 参数传入的交叉验证生成器控制。

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

两个容易忽略的细节：

- `fit` 学到的东西一律放在**下划线后缀属性**里，与构造时传入的超参数区分开：`clf.feature_importances_`、`pca.components_`、`scaler.mean_`
- 输入形状约定：`X` 一律二维 `[n_samples, n_features]`，`y` 为 `[n_samples]`；类别标签不必是整数

### Parameter Management

超参数管理有两个层次，靠**命名空间**分隔：

- 构造参数：`SVC(C=10, kernel="rbf")` 里的 `C`、`kernel`，存在普通属性上，可读可改
- 学习结果：`SVC` 拟合后多出的 `support_`、`dual_coef_`、`n_support_`，带下划线后缀

`get_params(deep=True)` 会递归取出嵌套估计器的参数，键用**双下划线**分隔步骤：

```python
pipe = Pipeline([("scaler", StandardScaler()), ("clf", SVC())])
pipe.get_params()["clf__C"]        # → SVC 的 C
pipe.set_params(clf__C=10)         # → 定位到 Pipeline 的第二步
```

这正是 `GridSearchCV` 能在 `Pipeline` 上搜索 `clf__C` 的机制基础——不是特殊逻辑，而是同一套参数命名空间规则的自然结果。

`clone(estimator)` 则按这套参数造一个**未拟合的同参副本**，交叉验证与搜索内部对每个候选都靠它拿干净副本，避免状态在折与折之间渗透。

### Validation Primitives

自建 Estimator 或做防御性编程时，别手写 `if X.shape[1] != self.n_features_in_: raise ...`，用官方校验原语：

```python
from sklearn.utils.validation import check_array, check_is_fitted

X = check_array(X, ensure_2d=True, dtype="numeric")   # 形状/类型/NaN 检查
check_is_fitted(self)                                  # 确认已 fit，否则抛 NotFittedError
```

`check_is_fitted` 默认检查实例上是否存在带下划线后缀的属性；自定义 Estimator 若想让判定语义不同，可实现 `sklearn_is_fitted()` 覆盖它。

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
| `feature_selection` | RFE、`SelectFromModel`、`SequentialFeatureSelector` | FeatureEngineering |
| `metrics` | 准确率、F1、AUC、MSE、轮廓系数 | [ML 评价指标](/docs/CS/AI/ML/ML.md) |
| `inspection` | 排列重要性、部分依赖 | 下文 Inspection |
| `pipeline` / `compose` | 流水线、ColumnTransformer | [特征工程·泄漏防范](/docs/CS/AI/ML/FeatureEngineering.md) |
| `dataset` | 内置小数据集、OpenML 拉取 | — |
| `exceptions` | `NotFittedError` 等 | — |

## Data Interop

### DataFrame In, DataFrame Out

Scikit-Learn 的输入本就是"表格语义"，不是"裸 ndarray 语义"。它认识 pandas DataFrame，并且**默认不破坏表格结构**——`fit` 时记住列名，变换后列名跟着走：

```python
from sklearn.preprocessing import StandardScaler
import pandas as pd

df = pd.DataFrame({"age": [20, 30], "income": [5000, 9000]})
scaler = StandardScaler().fit(df)
scaler.feature_names_in_      # → array(['age', 'income'], dtype=object)
```

`set_output(transform="pandas")` 则更进一步，把**输出**也变成 DataFrame：

```python
scaler.set_output(transform="pandas")
scaler.transform(df)           # → DataFrame，列名 age / income
```

> [!NOTE]
> `set_output` 是 **1.2 引入**的（SLEP018），现已被所有 transformer 采纳，`Pipeline` 和 `ColumnTransformer` 这类复合对象也支持。它把"输出是 ndarray 还是 DataFrame"从各 transformer 的个体差异变成了**全局统一开关**。

`get_feature_names_out()` 是配套的读取接口，返回变换后的列名；自建 transformer 时实现它，才能享受 `set_output` 的自动包装。

1.2 同期还有一处改名：`OneHotEncoder(sparse=False)` 改为 `OneHotEncoder(sparse_output=False)`，旧参数在 1.4 已移除。

### Sparse and Dense

输入支持三种形态：NumPy 稠密数组、pandas DataFrame、SciPy 稀疏矩阵。稀疏矩阵用于**高维稀疏**场景（文本 TF-IDF、独热编码后的大表），内存占用远小于稠密。但不是所有估计器都接受稀疏输入——线性模型、树模型、聚类大多可以，`SVC` / `TfidfVectorizer` 之外的某些估计器会显式报 `TypeError`，这一点由 1.6 起公开的 **Tags** 机制声明（见下文 Custom Estimator）。

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

复现性与切分要点：所有带随机性的 estimator 都要显式传 `random_state`；类别不平衡时 `train_test_split(..., stratify=y)` 必加，保证各折类别比例一致；训练时用 `class_weight="balanced"` 让少数类获得更高权重，比过采样更省事的起点。

### Learning and Validation Curves

单看一个分数不知道该往哪调。学习曲线（样本量 × 训练/验证得分）告诉你**是欠拟合还是过拟合**：两条线收敛到低位是欠拟合，该加模型复杂度；训练分高而验证分低是过拟合，该加数据或正则化。

```python
from sklearn.model_selection import learning_curve

train_sizes, train_scores, val_scores = learning_curve(
    model, X_tr, y_tr, cv=5, scoring="f1_macro"
)
```

验证曲线（`validation_curve`）则沿**单个超参数**扫描取值并画出得分曲线，用来选超参数的合理区间——先扫出量级再进 `GridSearchCV`，比盲目搜索省一个数量级的算力。

### Metric Selection

指标的选择由**业务代价**决定，不由"哪个数字好看"决定：漏诊代价远高于误诊时看召回，误报打扰用户时看精确率，类别极不平衡时 Accuracy 会失真（全部预测多数类也能有 95% 准确率）。`make_scorer` 可把自定义代价函数包装成评分器：

```python
from sklearn.metrics import make_scorer

def cost_fn(y_true, y_pred):
    return np.mean(np.abs(y_true - y_pred))     # 业务自定义损失

scorer = make_scorer(cost_fn, greater_is_better=False)
cross_val_score(model, X, y, cv=5, scoring=scorer)
```

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

`param_grid` 还可以写成**字典列表**，让不同参数组合各自带一组固定值（如 SVM 的 `C` 与 `gamma` 需配对）：

```python
param_grid = [
    {"C": [1, 10, 100], "kernel": ["linear"]},
    {"C": [1, 10], "kernel": ["rbf"], "gamma": [0.1, 1.0]},
]
```

### Successive Halving

`HalvingGridSearchCV` / `HalvingRandomSearchCV` 用**连续减半**（successive halving）策略替代穷举：第一轮所有候选都只给少量资源（默认资源是**训练样本数**，也可设为 `n_estimators` 这类整数参数），只保留表现最好的一部分进入下一轮并追加资源，逐轮收敛：

$$
n_{\text{resources}}^{(i)} = \text{factor}^{i} \cdot \text{min\_resources},
\qquad
n_{\text{candidates}}^{(i)} = \Big\lfloor \frac{n_{\text{candidates}}}{\text{factor}^{i}} \Big\rfloor
$$

`factor` 默认 3，意味着每轮资源翻三倍、候选砍到三分之一。代价是**结果带随机性**（早轮资源少，偶然性影响更大），且在 1.9.1 中**仍是实验性**——必须显式导入开关：

```python
from sklearn.experimental import enable_halving_search_cv   # noqa: F401
from sklearn.model_selection import HalvingRandomSearchCV
```

> [!WARNING]
> 该功能自 0.24 引入至今始终标记为实验性，官方注明"预测结果与 API 可能不经弃用周期直接变更"。生产用需谨慎。另外 `resource` 参数**不能**指定为 `param_grid` 里正在搜索的那个参数。

### Nested Cross Validation

调参与交叉验证同时做时，**外层评估的分数会偏乐观**——因为选超参数这件事本身也消耗了同一份验证数据的信息。严格做法是嵌套交叉验证：外层折只做评估，内层折做调参，代价是算力翻数倍。实践中的折中：内层 CV 调参 → 用全部训练数据重训 → 独立测试集做一次最终评估。

## Pipeline

[Pipeline](/docs/CS/AI/ML/FeatureEngineering.md) 把多个 Transformer 与一个 Estimator 串成单一对象，带来两个关键收益：

1. **防泄漏**：`fit` 只在训练数据上执行，交叉验证每一折都独立重新 fit 预处理——统计量不会从验证折渗入训练折
2. **可移植**：整个"预处理 + 模型"一起 `save / load / deploy`，避免线上线下处理不一致

跨列异构处理用 `ColumnTransformer`（数值列缩放填充、类别列编码），完整示例见 [FeatureEngineering](/docs/CS/AI/ML/FeatureEngineering.md) 的 Practice。

`Pipeline` 本身也是 Estimator，因此 `get_params` / `set_params` / `clone` 全部适用，嵌套参数用 `步骤名__参数名` 寻址。它还能直接进 `GridSearchCV`——搜 `clf__C` 即可，搜索器会自动把中间步骤重新 fit 到每一折训练集上，这是"手写预处理 + 搜索"最容易漏掉的一环。

## Custom Estimator

自建 Estimator 是把业务逻辑接入 Scikit-Learn 生态的标准方式。最小骨架：

```python
from sklearn.base import BaseEstimator, ClassifierMixin

class MyClassifier(ClassifierMixin, BaseEstimator):
    def __init__(self, threshold=0.5, *, normalize=True):
        self.threshold = threshold
        self.normalize = normalize

    def fit(self, X, y):
        self.classes_ = np.unique(y)
        self.coef_ = ...
        return self

    def predict(self, X):
        return self.classes_[(self.decision_function(X) > self.threshold).astype(int)]
```

几条硬规矩，违反其中任何一条都会让 `clone`、搜索或交叉验证出问题：

- **`__init__` 只存参数，不做校验、不做计算、不改参数值**。参数校验属于 `fit`；`set_params` 依赖属性名与参数名一一对应
- **不用 `*args` / `**kwargs`**，所有参数写成显式关键字参数
- **`fit` 返回 `self`**，学到的状态一律挂**下划线后缀**属性
- **Mixin 放在 `BaseEstimator` 之前**（`ClassifierMixin` 在左），`super().__sklearn_tags__()` 依赖这个顺序

### Estimator Tags

1.6 起 Tags 机制被重写并**公开为公共 API**（此前是 0.21 引入的私有 `_more_tags`）。Tags 是估计器能力的声明式注解——是否支持稀疏矩阵、是否多输出、是否非确定性、允许哪些输入类型：

```python
class MyClassifier(ClassifierMixin, BaseEstimator):
    def __sklearn_tags__(self):
        tags = super().__sklearn_tags__()
        tags.non_deterministic = True
        tags.target_tags.single_output = False
        return tags
```

`is_regressor` / `is_classifier` 这类判定函数与 `check_estimator` 的通用测试都读 Tags。第三方库（如 Feature-Engine）若未实现 `__sklearn_tags__`，在 1.7+ 环境下会告警，未来版本将直接报错——这是自建或二次封装估计器时最值得提前对齐的一点。

### set_output Auto Wrapping

`set_output` 对自建 transformer 同样可用，条件是：继承 `TransformerMixin` 并实现 `get_feature_names_out`。辅助 Mixin 有两个——输入输出一一对应时用 `OneToOneFeatureMixin`（如 `StandardScaler`），需要自己生成列名时用 `ClassNamePrefixFeaturesOutMixin`（如 `PCA`）。想**退出** `set_output` 包装，声明时传 `auto_wrap_output_keys=None`。

## Inspection

模型训练完不等于能解释。可解释性工具集中在 `sklearn.inspection`：

```python
from sklearn.inspection import permutation_importance

result = permutation_importance(
    model, X_te, y_te, n_repeats=10, random_state=42, scoring="f1_macro"
)
print(result.importances_mean, result.importances_std)
```

**排列重要性**（permutation importance）是模型无关的：随机打乱某个特征，看指标掉多少，掉得多说明该特征重要。它比 `feature_importances_`（树模型自带，偏向高基数/连续特征，且不考虑特征间交互）更可信，代价是多次重新预测。

**部分依赖**（partial dependence）刻画"单个特征从最小到最大时，预测值如何变化"，揭示模型学到的非线性关系：

```python
from sklearn.inspection import PartialDependenceDisplay

PartialDependenceDisplay.from_estimator(model, X_te, features=[0, 1])
```

`partial_dependence()` 返回一个 `Bunch`，`kind` 参数可取 `"average"`（平均效应，PDP）、`"individual"`（单样本效应，ICE）或 `"both"`。`method="recursion"` 依赖树模型结构因而快，但只支持 `kind="average"` 且仅适用于部分树集成模型；`method="brute"` 通用但慢。1.7 起支持 `custom_values` 字典指定自定义网格点。

> [!NOTE]
> `GradientBoostingClassifier` / `GradientBoostingRegressor` 用默认的 `"recursion"` 方法时**不会计入 `init` 预测器的影响**，若 `init` 不是常数估计器则结果不正确，应改用 `"brute"`。这一限制不适用于 `HistGradientBoosting*` 系列。

## Persistence

训练完的模型要落盘。选择哪种格式取决于**是否需要 Python 运行时**、**是否信任文件来源**、**是否在意加载速度**三个问题：

| 方式 | 优势 | 风险 |
| ------ | ------ | ------ |
| `ONNX` | 无需 Python 环境即可推理，训练与部署环境解耦，最安全 | 不支持所有模型；自定义估计器需额外适配；原始 Python 对象丢失 |
| `skops.io` | 比 pickle 系安全，可先查看可信类型再加载 | 不如 pickle 快；支持的类型较少 |
| `joblib` | 大模型与 numpy 数组上更省内存，支持 memory mapping | 基于 pickle 协议，加载可执行任意代码；需同版本环境 |
| `pickle` | Python 原生，什么都能序列化 | 加载可执行任意代码；不支持 memory mapping |
| `cloudpickle` | 能序列化 lambda、交互式定义的函数（`pickle` / `joblib` 不行） | 基于 pickle 协议；无前向兼容保证 |

常规选择：

```python
import joblib

joblib.dump(model, "model.joblib")        # 大模型首选
model = joblib.load("model.joblib")
```

> [!WARNING]
> **永远不要加载不可信来源的 pickle / joblib 文件**——反序列化可以执行任意代码，等同于执行一个未知脚本。ONNX 虽最安全，也建议放在沙箱环境里跑，因为 ONNX 同样能表达任意计算。

另一个常被忽略的约束：**没有任何受支持的方式加载用另一个 scikit-learn 版本训练出的模型**。跨版本可能"恰好能加载"，但官方明确不支持且不建议，可能得到不同结果甚至让进程崩溃。要在新版本复现，应同时保存：训练数据快照、生成模型的源码、scikit-learn 及各依赖的版本号、训练时的交叉验证分数。

## Metadata Routing

1.3 起引入的统一元数据传递机制，解决的是"除 `X` 和 `y` 之外的参数（如 `sample_weight`、`groups`）怎么穿过 `Pipeline` / `GridSearchCV` 传到真正用它的那个估计器"。

默认关闭，开启后：

```python
import sklearn
sklearn.set_config(enable_metadata_routing=True)

pipe = make_pipeline(SimpleImputer(), LogisticRegression())
pipe.set_fit_request(sample_weight=True)
cross_validate(pipe, X, y, cv=5, params={"sample_weight": w})
```

规则是"**消费方显式请求**"：估计器用 `set_fit_request(sample_weight=True)` 声明要用，scorer 用 `set_score_request(...)`，元估计器只做转发（router）。若传了元数据但没有任何对象明确请求或拒绝，路由器会抛 `UnsetMetadataPassedError` 提示你——这是刻意设计：宁可报错也不要静默丢弃权重（1.9.1 修复的正是 `RFE`、`SelectFromModel`、`IterativeImputer` 等作为 Pipeline 中间步骤时静默丢 `sample_weight` 的问题）。

别名机制允许**同一份元数据喂给不同消费者时用不同名字**，例如打分用 `scoring_weight`、拟合用 `fitting_weight`。

该机制在 1.9.1 中仍标注为**实验性**，且并非所有估计器都支持。

## Common Pitfalls

工程上反复出现的几类错误，多数不是"不会用 API"，而是**没意识到某个默认行为**：

- **预处理在切分之前做**。全量数据算均值方差再切分，就是泄漏。解法不是"记得小心"，而是把预处理放进 `Pipeline`，让交叉验证每一折自动重算
- **调参用了测试集**。测试集只能用一次，用来做最终报告
- **忘记 `random_state`**。所有含随机性的估计器（多数 tree 模型、k-means、划分）不传种子则结果不可复现
- **`OneHotEncoder` 遇到未见类别报错**。训练与推理的类别集合不一致时，需 `handle_unknown="ignore"`
- **在 `fit` 里做校验**。参数校验应在 `fit` 中，`__init__` 保持纯粹，否则 `clone` 与搜索会出问题
- **用 `predict` 而非 `predict_proba` 做阈值决策**。分类器输出概率时，阈值策略应在概率上做
- **默认 `scoring` 悄悄变化**。`LogisticRegressionCV` 在 1.11 起默认从准确率改为 `neg_log_loss`，跨版本对比分数时要注意口径
- **稀疏矩阵被 densify**。高维独热后 `.toarray()` 会让内存爆掉，优先确认估计器是否支持稀疏输入

## Pros and Cons

- **优点**：API 统一、上手快、文档质量高；覆盖经典 ML 全流程；Pipeline/ColumnTransformer 工程化成熟；社区生态（与 pandas、joblib、XGBoost 等无缝衔接）
- **缺点**：不做 GPU 加速与深度学习训练；对超大数据集（内存装不下的表）需要 Dask-ML 等扩展；强化学习、图学习等新范式不在其范围
- **选型边界**：样本千万级或特征极稀疏时改用 XGBoost / LightGBM；非结构化数据（图像/文本/语音）交给 [PyTorch](/docs/CS/AI/PyTorch.md) / [TensorFlow](/docs/CS/AI/TensorFlow.md)——不过 `TfidfVectorizer + LogisticRegression` 仍是文本分类极难超越的强基线

## Links

- [AI](/docs/CS/AI/AI.md)
- [NumPy](/docs/CS/Python/NumPy.md)
- [DL](/docs/CS/AI/DL/DL.md)
- [TextClassification](/docs/CS/AI/NLP/TextClassification.md)

## References

1. [scikit-learn Getting Started 官方文档](https://scikit-learn.org/stable/getting_started.html)
2. [scikit-learn User Guide 官方文档](https://scikit-learn.org/stable/user_guide.html)
3. [Cross-validation 官方文档](https://scikit-learn.org/stable/modules/cross_validation.html)
4. [Tuning the hyper-parameters 官方文档](https://scikit-learn.org/stable/modules/grid_search.html)
5. [scikit-learn 1.9 Release Highlights](https://scikit-learn.org/stable/whats_new/v1.9.html)
6. [Developing scikit-learn estimators 开发者指南](https://scikit-learn.org/stable/developers/develop.html)
7. [Model persistence 官方文档](https://scikit-learn.org/stable/modules/model_persistence.html)
8. [Metadata Routing 官方文档](https://scikit-learn.org/stable/metadata_routing.html)
9. [Common pitfalls and known issues](https://scikit-learn.org/stable/common_pitfalls.html)
10. [Model Inspection 官方文档](https://scikit-learn.org/stable/auto_examples/inspection/index.html)
11. [Pipeline 与 ColumnTransformer 官方文档](https://scikit-learn.org/stable/modules/compose.html)
12. [set_output 与 DataFrame 输出示例](https://scikit-learn.org/stable/auto_examples/miscellaneous/plot_set_output.html)
