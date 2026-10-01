## Introduction

特征工程（Feature Engineering）是**把原始数据变换成更能表达问题、模型更容易消化的特征**的过程：清洗脏数据、统一量纲、编码类别、构造新变量、筛选有用子集。业界常说"数据和特征决定了模型的上限，算法只是在逼近这个上限"——同一份数据换一套特征，往往比换一个模型提升大得多。

它解决的问题：原始数据通常**脏**（缺失、异常）、**异构**（数值、类别、文本混杂）、**尺度不一**、**含大量无关与冗余信息**，而多数模型只吃规整的数值矩阵。

## Data Cleaning

### 缺失值

| 策略 | 做法 | 适用 |
| ------ | ------ | ------ |
| 删除 | 丢行（缺失率高的样本）或丢列（缺失率极高的特征） | 缺失占比小且随机 |
| 统计量填充 | 均值 / 中位数 / 众数 | 快速基线；中位数抗离群 |
| 模型填充 | KNN Imputer、用其它特征回归预测 | 缺失模式复杂 |
| 标记缺失 | 把"是否缺失"本身做成一列 | 缺失本身有业务含义（如"拒填收入"） |

### 异常值

- **3σ 原则**：正态假设下超出 $\mu\pm3\sigma$ 的点
- **箱线图 IQR 法**：低于 $Q_1-1.5\,\mathrm{IQR}$ 或高于 $Q_3+1.5\,\mathrm{IQR}$ 视为可疑
- 处理：核实业务真伪后删除、盖帽（截断到分位数）、或分箱稀释

## Feature Scaling

多数基于距离或梯度的模型对特征尺度极其敏感——"年龄 0~100"和"年收入 0~1,000,000"放进 [KNN](/docs/CS/AI/ML/KNN.md) 或 [SVM](/docs/CS/AI/ML/SVM.md)，后者会主导距离计算。两种标准做法：

$$
\text{Min-Max 归一化：}\ x'=\frac{x-x_{\min}}{x_{\max}-x_{\min}}\in[0,1]
\qquad
\text{Z-score 标准化：}\ x'=\frac{x-\mu}{\sigma}
$$

- **Min-Max**：压缩到固定区间，受离群点影响大，适合有明确边界的场景（图像像素）
- **Z-score**：均值 0 方差 1，对离群更稳，是逻辑回归、SVM、神经网络、[PCA](/docs/CS/AI/ML/PCA.md) 的默认选择
- 离群点多时可用 **RobustScaler**（中位数 + IQR）
- **树模型不需要缩放**——分裂只看阈值与顺序，与尺度无关

## Categorical Encoding

类别特征必须转成数值，但要按**类别是否有序**选方法：

- **One-Hot 编码**：每个取值变成一列 0/1。适合无序类别（颜色、城市）；缺点是维度膨胀，高基数特征（如用户 ID）会爆炸，稀疏矩阵可缓解
- **有序编码（Ordinal）**：把有序类别（小/中/大）映射成 1/2/3，保留序信息；用在无序类别上会引入假序
- **目标编码（Target Encoding）**：用该类别对应标签的均值替换类别值，表达能力极强，但**必须用交叉验证内的统计量**，否则直接泄漏标签
- 高基数场景：频率编码、哈希编码

## Feature Construction

从现有特征出发造新特征，最依赖业务直觉的一步：

- **组合**：比率（客单价 = 金额/订单数）、差值（距今天数）、交叉（年龄段 × 城市）
- **分箱（Binning）**：等距 / 等频把连续变量切成离散段，抗噪声、引入非线性，也为 One-Hot 做准备
- **时间窗统计**：近 7 天点击数、环比增长率等滑窗聚合
- **文本**：词频-逆文档频率（TF-IDF）、n-gram

## Feature Selection

特征不是越多越好：冗余与噪声特征会放大过拟合、拖慢训练、稀释可解释性。三种选法：

- **过滤（Filter）**：先按统计量筛再训练——方差阈值（近常量特征剔除）、与标签的相关系数 / 互信息 / 卡方检验。快，但不看模型反馈
- **包裹（Wrapper）**：用模型表现当准则搜索子集，如递归特征消除（RFE）。效果好但开销大
- **嵌入（Embedded）**：训练过程顺带完成筛选——[Lasso 的 L1 稀疏](/docs/CS/AI/ML/LinearModel.md)、[树模型的特征重要性](/docs/CS/AI/ML/EnsembleLearning.md)，是最常用的折中

维度太高且想要"新维度"而非"选子集"时，转向降维（[PCA](/docs/CS/AI/ML/PCA.md)、[LDA](/docs/CS/AI/ML/LDA.md)）。

## Data Leakage

> [!WARNING]
> 数据泄漏（Data Leakage）是特征工程最常见也最隐蔽的错误：任何用到"全数据集统计量"的变换——缩放的均值方差、填充的中位数、目标编码的均值——都必须**只在训练集上计算**，再应用到验证/测试集。否则测试集信息提前渗入训练，离线指标虚高、上线即跳水。

时间序列任务里还有更隐蔽的泄漏：用 t 时刻之后的信息构造 t 时刻的特征。防御手段是把所有变换装进 Pipeline，让 fit 与 transform 严格分离（见下）。

## Practice

用 `ColumnTransformer` + `Pipeline` 把数值列与类别列各自的处理串起来——fit 只发生在训练数据上，从机制上杜绝泄漏：

```python
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression

num = make_pipeline(SimpleImputer(strategy="median"), StandardScaler())
cat = make_pipeline(SimpleImputer(strategy="most_frequent"),
                    OneHotEncoder(handle_unknown="ignore"))
prep = ColumnTransformer([("num", num, num_cols), ("cat", cat, cat_cols)])

model = make_pipeline(prep, LogisticRegression())
model.fit(X_train, y_train)      # 所有统计量只在 train 上 fit
```

## Links

- [ML](/docs/CS/AI/ML/ML.md)
- [Scikit-Learn](/docs/CS/AI/Scikit-Learn.md)
- [PCA](/docs/CS/AI/ML/PCA.md)
- [LinearModel](/docs/CS/AI/ML/LinearModel.md)
- [EnsembleLearning](/docs/CS/AI/ML/EnsembleLearning.md)

## References

1. [sklearn Preprocessing 官方文档](https://scikit-learn.org/stable/modules/preprocessing.html)
2. [sklearn Imputation of missing values 官方文档](https://scikit-learn.org/stable/modules/impute.html)
3. [sklearn Feature selection 官方文档](https://scikit-learn.org/stable/modules/feature_selection.html)
