## Introduction

机器学习（Machine Learning，ML）研究如何让计算机**从数据中自动学习规律，并对没见过的新数据做出预测**，而无需为每条规则手工编程。
它是人工智能（AI）的核心分支：传统机器学习靠人工设计特征 + 统计模型，深度学习（[DL](/docs/CS/AI/DL/DL.md)）则用神经网络自动学习特征，大语言模型（[LLM](/docs/CS/AI/LLM/LLM.md)）是深度学习在大规模文本上的延伸。

一个经典定义来自 Tom Mitchell（1997）：

> 若程序在任务 T 上的性能 P 随经验 E 而提高，则称该程序从经验 E 中学习。

## Paradigms

按训练数据是否带标签、反馈形式如何，机器学习通常分为三大范式：

| 范式 | 数据特点 | 典型任务 | 代表算法 |
| ------ | ---------- | ---------- | ---------- |
| 监督学习 Supervised | 有特征 X + 标签 y | 分类、回归 | KNN、决策树、SVM、[LinearModel](/docs/CS/AI/ML/LinearModel.md)、[EnsembleLearning](/docs/CS/AI/ML/EnsembleLearning.md) |
| 无监督学习 Unsupervised | 只有特征 X | 聚类、降维、密度估计 | k-means、PCA、层次聚类 |
| 强化学习 Reinforcement | 智能体与环境交互，只有奖励信号 | 游戏、机器人控制、推荐 | [ReinforcementLearning](/docs/CS/AI/ML/ReinforcementLearning.md)、Q-Learning、DQN、PPO |

介于两者之间还有半监督学习（少量标注 + 大量未标注）和自监督学习（从数据自身构造监督信号，LLM 预训练即是典型）。

### 分类与回归

监督学习的两大任务，区别在输出的形态：

- **分类（Classification）**：输出离散类别。二分类（垃圾邮件识别）、多分类（手写数字 0-9）
- **回归（Regression）**：输出连续数值。房价预测、气温预测

同一个模型往往两者都能做：决策树、SVM、KNN 既可以输出类别也可以输出数值。

### 聚类与降维

无监督学习的两大任务：

- **聚类（Clustering）**：把样本按相似度分组，如用户分群。详见 [Clustering](/docs/CS/AI/ML/Clustering.md)
- **降维（Dimensionality Reduction）**：把高维特征压缩到低维同时保留主要信息，代表方法 [PCA](/docs/CS/AI/ML/PCA.md)、[LDA](/docs/CS/AI/ML/LDA.md)

## Basic Concepts

### 特征、标签与数据划分

- **特征（Feature）**：描述样本的属性向量 x
- **标签（Label）**：要预测的目标 y
- **训练集 / 测试集**：模型在训练集上学习参数，在测试集上评估泛化能力；常按 8:2 或 7:3 划分，另划验证集做调参
- **交叉验证（Cross Validation）**：k 折交叉验证把数据分成 k 份轮流做验证，对小数据集的评估更稳定

### 损失函数 Loss Function

损失函数度量"预测值与真实值的差距"，训练过程就是最小化它。常用的有：

- **0-1 损失**：预测对为 0、错为 1，理想但不连续不可导，多用于理论分析（KNN 的多数表决等价于最小化 0-1 损失）
- **绝对值损失（Absolute Loss）**：$L(y,\hat{y})=|y-\hat{y}|$，对异常值不敏感
- **平方损失（MSE）**：$L(y,\hat{y})=(y-\hat{y})^2$，回归最常用，处处可导但对离群点敏感
- **Hinge 损失**：$L(y,\hat{y})=\max(0,\ 1-y\hat{y})$，SVM 的标准损失
- **对数损失（交叉熵）**：分类 + 概率输出（[逻辑回归](/docs/CS/AI/ML/LinearModel.md)、神经网络）的标准损失

### 偏差与方差 Bias & Variance

模型泛化误差可以分解为偏差、方差与噪声三部分：

| | 偏差 Bias | 方差 Variance |
| ------ | ---------------- | ------------------ |
| 直觉 | 预测期望与真实值的偏离程度 | 预测值随数据扰动的离散度 |
| 来源 | 模型太简单，假设空间表达力不足 | 模型太复杂，对训练数据过度敏感 |
| 表现 | 欠拟合 Underfitting | 过拟合 Overfitting |

- 欠拟合：训练集和测试集都差 → 提高模型复杂度、加特征
- 过拟合：训练集很好、测试集差 → 增加数据、正则化、剪枝、Dropout

### 梯度下降 Gradient Descent

参数优化的基础方法：沿损失函数梯度的反方向小步更新参数 $\theta \leftarrow \theta - \eta \nabla L(\theta)$，学习率 $\eta$ 控制步长。变体有批量（BGD）、随机（SGD）、小批量（Mini-batch）三种。

### 评价指标

分类指标基于混淆矩阵（TP / FP / FN / TN）：

$$
\text{Accuracy}=\frac{TP+TN}{TP+TN+FP+FN},\quad
\text{Precision}=\frac{TP}{TP+FP},\quad
\text{Recall}=\frac{TP}{TP+FN},\quad
F_1=\frac{2PR}{P+R}
$$

- 类别不平衡时看 Precision / Recall / F1，不要只看 Accuracy
- ROC 曲线下的面积 AUC 越接近 1，排序能力越强

回归常用 MSE、RMSE、MAE 和决定系数 $R^2$。

## Workflow

一个完整的机器学习项目大致是：

1. 明确问题与收集数据
2. 数据清洗与[特征工程](/docs/CS/AI/ML/FeatureEngineering.md)（缺失值、归一化、编码）
3. 选择模型并训练（最小化损失函数）
4. 用验证集 / 交叉验证调超参数
5. 测试集评估泛化性能，部署上线并监控

工程上最常用的入门工具库是 [Scikit-Learn](/docs/CS/AI/Scikit-Learn.md)，统一了 `fit / predict` 接口；深度学习则用 [PyTorch](/docs/CS/AI/PyTorch.md)、[TensorFlow](/docs/CS/AI/TensorFlow.md)。

## Links

- [AI](/docs/CS/AI/AI.md)
- [DL](/docs/CS/AI/DL/DL.md)
- [Scikit-Learn](/docs/CS/AI/Scikit-Learn.md)
- [KNN](/docs/CS/AI/ML/KNN.md)
- [DecisionTree](/docs/CS/AI/ML/DecisionTree.md)
- [SVM](/docs/CS/AI/ML/SVM.md)
- [Clustering](/docs/CS/AI/ML/Clustering.md)
- [HMM](/docs/CS/AI/ML/HMM.md)
- [PCA](/docs/CS/AI/ML/PCA.md)
- [LDA](/docs/CS/AI/ML/LDA.md)
- [ReinforcementLearning](/docs/CS/AI/ML/ReinforcementLearning.md)
- [EnsembleLearning](/docs/CS/AI/ML/EnsembleLearning.md)
- [LinearModel](/docs/CS/AI/ML/LinearModel.md)
- [FeatureEngineering](/docs/CS/AI/ML/FeatureEngineering.md)

## References

1. [机器学习（西瓜书）-豆瓣](https://book.douban.com/subject/26708119/)
2. [统计学习方法（第2版）-豆瓣](https://book.douban.com/subject/33437381/)
3. [Machine Learning Specialization-Coursera](https://www.coursera.org/learn/machine-learning)
4. [scikit-learn 官方文档](https://scikit-learn.org/stable/)
