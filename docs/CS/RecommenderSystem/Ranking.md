## Introduction

精排做的事很窄：给定一个已经过滤过的候选集，为每个 $(u,i)$ 输出一个可比较的分数并排序。工业界的主流形态是**点击率（CTR）预估**——一个带极多类别特征的二分类问题。

难点不在模型结构，而在三件模型之外的事：**样本从哪来**（曝光即负样本，于是样本分布被上一版系统决定）、**特征是否离在线一致**（同一份统计量，训练时点与打分时点算出来的值必须同口径）、**分数是否可信**（广告与混排要的是概率值本身，不是序）。这三个问题里任何一个出错，换更复杂的模型只会把错误放大得更快。

## Samples and Labels

- **正样本**：点击、加购、完播、购买——按业务目标选，选错等于优化错东西
- **负样本**：曝光未点击。这隐含一个强假设"曝光=给用户看过且他拒绝了"，但真实曝光里包含大量根本没被看到的（位置靠下、页面未滑到），因此**位置是必须建模的偏差而不是特征噪声**
- **延迟反馈**：转化可能在点击后数小时到数天发生，训练窗口关闭时标签还没落地。处理方式要么等标签（牺牲新鲜度）、要么把未转化的正样本按概率提前计入、要么用重要性加权校正——三种做法都会引入偏差，只有幅度不同
- **时间切分**：训练集必须严格早于测试集（按事件时间而非随机划分），否则未来信息泄漏会把离线指标抬到不可信的高度
- **反作弊与过滤**：爬虫、刷量、误点击要在进样本前剔除，否则模型学到的是攻击者的偏好

## Feature System

| 类别 | 例子 | 关键注意点 |
| ------ | ------ | ------ |
| 用户侧 | 画像标签、活跃度、历史行为序列 | 序列既提供兴趣也泄露了曝光策略，注意与标签时间的关系 |
| 物品侧 | 类目、品牌、价格、多窗口统计 CTR | 统计特征极易穿越：算 $\mathrm{CTR}_i$ 的窗口必须早于该样本的曝光时间 |
| 上下文 | 时间、位置、网络、页面、设备 | 位置和页面是强偏差来源，训练与在线都要带 |
| 交叉 | 用户类目 × 物品类目、年龄 × 品类 | 交叉维度爆炸，靠模型自动学（见 FM 一节）比手工枚举更可维护 |
| 实时 | 最近 N 次点击、本次会话已看内容 | 特征获取是链路里最慢的一段，直接决定打分耗时 |

稀疏统计量必须平滑，否则小曝光物品的经验 CTR 毫无意义（曝光 1 次点击 1 次 = 100%）：

$$
\mathrm{CTR}_{\text{smooth}} = \frac{c + \alpha}{e + \alpha + \beta}
$$

即以 Beta 先验做收缩（$c$ 点击数、$e$ 曝光数）。另一个常用写法是 Wilson 下界，它同时给出置信水平。特征加工方法的总体脉络见 [FeatureEngineering](/docs/CS/AI/ML/FeatureEngineering.md)。

## Model Lineage

一条主线是**如何得到特征交叉**：人工枚举 → 隐向量学二阶 → 树路径自动组合 → 深度网络端到端学高阶。

**LR**：可解释、易上线，但交叉全靠人工，效果上限被特征工程卡死（见 [LinearModel](/docs/CS/AI/ML/LinearModel.md)）。

**FM（Factorization Machine）**：给每个特征分配隐向量，用内积参数化两两交叉权重：

$$
\hat{y} = w_0 + \sum_{i=1}^{n} w_i x_i + \sum_{i=1}^{n}\sum_{j=i+1}^{n} \langle v_i, v_j \rangle x_i x_j
$$

关键在于化简。二阶项可以按隐向量维度重排成平方差形式：

$$
\sum_{i}\sum_{j>i} \langle v_i, v_j \rangle x_i x_j
= \frac{1}{2}\sum_{f=1}^{k}\left[ \left( \sum_{i=1}^{n} v_{if} x_i \right)^2 - \sum_{i=1}^{n} v_{if}^2 x_i^2 \right]
$$

于是复杂度从 $O(n^2 k)$ 降到 $O(nk)$——这是 FM 能在十亿级特征上跑起来的唯一原因。另一个常被忽略的性质：即使 $x_i x_j$ 这一组合在训练集里从未出现，只要两个特征各自与别的特征共现过，权重也能被学出来，**稀疏场景下的泛化正是靠这个**。

**FFM**：让同一个特征在不同 field 下使用不同隐向量，表达力更强，代价是参数量与训练成本按 field 数倍增。

**GBDT + LR**：用树自动挑出有效的特征组合，把样本落在哪个叶子编码成 one-hot 再喂给 LR。工程价值在于把"交叉"这件事外包给树模型，但需要定期重训以对齐特征分布（见 [EnsembleLearning](/docs/CS/AI/ML/EnsembleLearning.md)）。

**Wide & Deep**：wide 侧负责记忆（历史上一起出现过），deep 侧负责泛化（没共现过也能推），两路联合训练。要点是 deep 侧的 embedding 维度过高会**记住噪声**——论文里的经验取向是用较小维度并把正则做强。

**DeepFM**：用同一个 embedding 层同时服务 FM 的二阶项与 DNN 的高阶项，wide 侧不再需要人工特征组合。

**DIN**：用户兴趣不是固定的，而是**随候选物品变化**——给他看球鞋才该激活球鞋相关的历史行为。若用 sum/average pooling 把行为序列压成定长向量，这种依赖就丢了。DIN 用 target-aware attention 让序列表示随候选而变：

$$
\mathbf{u}(i) = \sum_{j=1}^{H} a\!\left( \mathbf{e}_i,\, \mathbf{e}_{j} \right) \mathbf{e}_{j}
$$

其中 $a(\cdot)$ 是把（候选 embedding，历史行为 embedding）拼接后过一个小 MLP 得到的权重，常见实现里不额外做 softmax 归一化，好让兴趣的**强度**体现在求和结果上。

**多目标与多任务**：真实业务要同时优化点击、时长、转化、互动。单模型多输出的共享底座（MMoE 一类，用门控为每个任务选专家）与 ESMM 的全空间建模是两条常见路线。ESMM 解决的痛点很具体：CVR 只能从"点击后"的样本学，而线上要的是"曝光后转化"，两者分布不同（样本选择偏差）；它的做法是把 CVR 作为中间变量，用
$\mathrm{pCTCVR} = \mathrm{pCTR} \times \mathrm{pCVR}$
在**全曝光空间**上监督，让 CVR 塔通过共享 embedding 间接学习。

多目标之间的分数融合通常是加权形式 $\mathrm{score} = \prod_i p_i^{w_i}$（或线性加权），权重靠线上实验逼近业务期望——它是一个**决策变量**而不是可以推导出来的量。趋势上，序列生成式建模与用大模型补语义理解正在进入这一层，但工程与成本代价尚未收敛。

## Engineering Constraints of the Scoring Pipeline

精排的候选规模（千级）乘以单条打分成本，直接决定这一层能不能上线：

- **特征拉取才是瓶颈，不是推理**：千级候选意味着成千上万次画像/统计特征读取，必须批量与并发扇出，链路总预算里它常占一半以上（阿里把这套编排做成图化框架的动机正是如此，见 [TPP](/docs/CS/RecommenderSystem/TPP.md)）
- **模型侧加速**：embedding 查表放 PS 或本地缓存、dense 部分做 batch 推理、量化与蒸馏（把大模型蒸给粗排用，是"多级排序"存在的成本原因）
- **降级路径**：模型超时要有兜底分数（统计 CTR 或召回分数），否则整页空白，稳定性与效果的权衡在这里最直白

## Probability Calibration

排序只需要序，但广告计费、多目标融合、混排需要**值可信**。AUC 高完全可能与校准差同时存在——AUC 只看序。

- **分桶校准 / Isotonic**：按预测值分桶，统计每桶真实 CTR，拟合一条映射把预测拉到对角线上
- **降采样后的还原**：为了平衡正负比例对负样本按 $w$ 保留，模型输出会系统性偏高，闭式还原为

$$
p_{\text{true}} = \frac{w\,\hat{p}}{1 - \hat{p} + w\,\hat{p}}
$$

- **温度缩放**：单参数调整 softmax/logistic 的陡峭程度，代价最小
- **监控**：$\mathrm{pCTR}/\mathrm{CTR}$ 比值（PCoC）偏离 1 说明线上分布已漂移，此时模型没变但结论已错

## Re-Ranking and Diversity

精排给出的是"各自最优"，重排处理的是"整列放在一起是否仍然好"——同一类内容刷屏会让逐条分数最高的组合整体变差。

**MMR（最大边际相关）**：每选一个，就惩罚它与已选集合的相似度：

$$
\arg\max_{i \in \mathcal{R} \setminus \mathcal{S}} \left[ \lambda\, \mathrm{Rel}(i \mid u) - (1 - \lambda)\max_{j \in \mathcal{S}} \mathrm{Sim}(i, j) \right]
$$

$\lambda$ 即相关性/多样性的显式折中，代价是相似度只与已选集合比较，容易反复选到同一簇外的边缘物品。

**DPP（行列式点过程）**：用质量与相似度的核矩阵，让"整体相似"而不是"两两相似"受惩罚，几何直觉是选出的向量张成的体积越大越好。贪心 MAP 推断的复杂度可控，因此能在毫秒级链路里用。

规则层的打散（同类目窗口频次、同作者不连续、广告位置间隔）依然是绝大多数业务的主力，因为可控、可解释、可归因。

> [!NOTE]
> listwise/pairwise 损失（以整列或物品对为单位优化）在理论上更贴合排序目标，工业实践中常作为辅助损失。是否值得，取决于业务里"整列效应"到底有多大——强互斥的列表（一屏内容彼此替代）收益明显，弱互斥的（电商长列表）收益有限。

## Links

- [推荐系统](/docs/CS/RecommenderSystem/RecommenderSystem.md)
- [Pipeline](/docs/CS/RecommenderSystem/Pipeline.md)
- [Recall](/docs/CS/RecommenderSystem/Recall.md)
- [CollaborativeFiltering](/docs/CS/RecommenderSystem/CollaborativeFiltering.md)
- [Evaluation](/docs/CS/RecommenderSystem/Evaluation.md)
- [Architecture](/docs/CS/RecommenderSystem/Architecture.md)
- [Advertising](/docs/CS/RecommenderSystem/Advertising.md)
- [DataEngineering](/docs/CS/RecommenderSystem/DataEngineering.md)
- [Debiasing](/docs/CS/RecommenderSystem/Debiasing.md)
- [UserProfile](/docs/CS/RecommenderSystem/UserProfile.md)
- [ContentProfile](/docs/CS/RecommenderSystem/ContentProfile.md)
- [LinearModel](/docs/CS/AI/ML/LinearModel.md)
- [EnsembleLearning](/docs/CS/AI/ML/EnsembleLearning.md)
- [FeatureEngineering](/docs/CS/AI/ML/FeatureEngineering.md)
- [TPP](/docs/CS/RecommenderSystem/TPP.md)

## References

1. [Wide & Deep Learning for Recommender Systems-arXiv](https://arxiv.org/abs/1606.07792)
1. [DeepFM: A Factorization-Machine based Neural Network for CTR Prediction-arXiv](https://arxiv.org/abs/1703.04247)
1. [Deep Interest Network for Click-Through Rate Prediction-arXiv](https://arxiv.org/abs/1706.06978)
1. [Entire Space Multi-Task Model-arXiv](https://arxiv.org/abs/1804.07931)
1. [Fast Greedy MAP Inference for DPP to Improve Recommendation Diversity-arXiv](https://arxiv.org/abs/1709.05135)
