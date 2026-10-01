## Introduction

协同过滤（Collaborative Filtering，CF）解决的是这样一个问题：系统并不真正理解物品（不知道一首歌的调性、一件衣服的材质），但掌握了**大量用户与物品的交互记录**。既然"和你口味相近的人还买了什么"是可统计的，就可以用**他人的行为**来填补你对未知物品的偏好空白——这就是"协同"二字的含义。

它是推荐系统里最经典的算法族，也是 Pipeline 中"基于关系/基于行为"两类算法的主要承载者。与基于内容的推荐（依赖 [ContentProfile](/docs/CS/RecommenderSystem/ContentProfile.md) 里的画像与标签）互补：CF 擅长发现"意料之外但情理之中"的兴趣，代价是需要数据积累，冷启动困难。

一切从**用户-物品评分矩阵** $R \in \mathbb{R}^{m \times n}$ 出发，$r_{u,i}$ 表示用户 $u$ 对物品 $i$ 的评分。这个矩阵的现实形态是：千万用户 × 千万物品，非空元素占比往往只有千分之一到百分之一量级。稀疏性决定了后面所有工程设计的形状。

按求解路径分成两大流派：

- **基于内存**（Memory-based / Neighborhood）：直接算相似度、做加权平均，无可训练参数，在线查表
- **基于模型**（Model-based）：把评分矩阵压成低秩隐向量，训练后再预测，可上线做向量检索

## Memory-based CF

**UserCF**：先找与目标用户最像的 $K$ 个邻居，再用邻居对物品 $i$ 的评分做加权平均。均值中心化是必须的，否则评分习惯（有人习惯打 5 分，有人习惯打 3 分）会污染相似度。

$$
\hat{r}_{u,i} = \bar{r}_u + \frac{\sum_{v \in N(u,i)} \mathrm{sim}(u, v) \left( r_{v,i} - \bar{r}_v \right)}{\sum_{v \in N(u,i)} \left| \mathrm{sim}(u, v) \right|}
$$

其中 $N(u,i)$ 是邻居中评过物品 $i$ 的用户集合。

**ItemCF**：先算物品之间的相似度，再用该用户历史评分过的相似物品加权。

$$
\hat{r}_{u,i} = \frac{\sum_{j \in S(i,u)} \mathrm{sim}(i, j) \, r_{u,j}}{\sum_{j \in S(i,u)} \left| \mathrm{sim}(i, j) \right|}
$$

两者的差别不是精度，而是**稳定性与业务适配**：

| 维度 | UserCF | ItemCF |
| ------ | ------ | ------ |
| 推荐解释 | "和你相似的人也喜欢" | "因为你买过 A" |
| 兴趣漂移 | 敏感，适合兴趣易变的场景（新闻、短视频） | 稳定，适合物品长期不变的场景（电商、图书） |
| 物品侧计算 | 物品相似度不需要，但用户邻居在线变化 | 物品相似度可离线预计算并长期缓存 |
| 用户规模敏感 | 用户相似度矩阵随 $m^2$ 膨胀 | 物品相似度矩阵随 $n^2$ 膨胀，商品数远小于用户数时更划算 |

相似度度量的选择：

- **余弦相似度**：把共同行为当作向量夹角，天然适合隐式反馈（只有"点过/没点过"）
- **Pearson 相关系数**：余弦之前先对每个用户/物品减去自身均值，专门修正评分尺度偏移
- **修正余弦（Adjusted Cosine）**：减去该物品的全局平均分再算用户相似度，缓解同一用户评过的物品少、重叠维度过低的问题
- **Jaccard / 共现次数**：只有二值行为时使用，分母取并集可抑制"热门物品和谁都相似"

热门惩罚是隐式反馈下几乎必做的一步：共现次数要除以 $\sqrt{\text{len}(i) \cdot \text{len}(j)}$ 之类的人群规模项，否则排行榜热品会淹没一切长尾兴趣。

工程上真正的瓶颈是"两两相似度"算不动。标准做法是**倒排表**：不再遍历物品对，而是按"每个用户喜欢过哪些物品"展开，只在共同点过该物品的用户对之间累加分母，把复杂度从物品数的平方降到 $\sum_u \binom{|I_u|}{2}$。相似度矩阵离线批量算好、每个物品只保留 Top-K 个近邻，线上只做查表与合并——这条"离线预计算 + 在线截断"的路子，和 [KNN](/docs/CS/AI/ML/KNN.md) 的检索式近似是完全一样的思路。

## Matrix Factorization

**基本假设**：评分低秩。存在用户隐向量 $p_u \in \mathbb{R}^k$ 与物品隐向量 $q_i \in \mathbb{R}^k$，使 $\hat{r}_{u,i} = p_u^{\top} q_i$。$k$ 维隐空间不再由人定义，而是训练中自己涌现出"近似题材/风格"的方向。

带正则的最小二乘目标（只对**观测到的**评分求和，这是它与 PCA/NMF 的关键区别）：

$$
\min_{P, Q} \sum_{(u,i) \in \kappa} \left( r_{u,i} - p_u^{\top} q_i \right)^2 + \lambda \left( \| p_u \|^2 + \| q_i \|^2 \right)
$$

对 $p_u$ 求偏导并令其为零，得到固定 $Q$ 下的最小二乘解：

$$
p_u = \left( \sum_{i \in \kappa_u} q_i q_i^{\top} + \lambda I \right)^{-1} \sum_{i \in \kappa_u} r_{u,i} q_i
$$

对 $q_i$ 对称。由此引出两条求解路径：

- **ALS（交替最小二乘）**：固定一边解另一边，闭式解、无学习率、易并行，适合离线批量重训
- **SGD（随机梯度下降）**：沿梯度 $e_{u,i} q_i$、$e_{u,i} p_u$ 更新，天然支持增量与新样本在线吸收，但对学习率和迭代次序敏感

**偏置项**不能被省略。只用 $p_u^{\top}q_i$ 会把"整体打分习惯"这类系统性偏差留给隐向量硬拟合，显式拆出全局均值与用户、物品偏置之后，误差才有明显下降（这也是 Netflix Prize 期间被反复验证的经验）：

$$
\hat{r}_{u,i} = \mu + b_u + b_i + p_u^{\top} q_i
$$

这一项也正好对应 [线性模型](/docs/CS/AI/ML/LinearModel.md)里的截距思想；SVD++ 再把用户"隐式反馈过的物品向量"并入 $p_u$，等于用行为记录扩充用户向量的估计依据，在评分稀疏时更稳。

与经典机器学习算法的关系：

- 与 [PCA](/docs/CS/AI/ML/PCA.md)、NMF 同属**低秩近似**，但 PCA 要求完整矩阵、NMF 通常把缺失当 0 参与分解，而 CF 的矩阵分解**只在观测元素上拟合**，再用正则控制自由度
- 分解得到的 $q_i$ 就是物品向量。线上不再算两两相似度，而是把 $p_u$ 丢进近似最近邻（ANN）索引做检索——这正是 [Pipeline](/docs/CS/RecommenderSystem/Pipeline.md) 里"向量召回"一路的由来
- 隐向量继续往上叠深度网络、与内容特征拼接，就走到 FM/DeepFM 那一支（见 Pipeline 的 Model Evolution）

## Cold Start and Long Tail

CF 的原罪是"没有交互就没有一切"，按缺口位置分三类处理：

| 冷启动类型 | 缺什么 | 常用兜底 |
| ------ | ------ | ------ |
| 用户冷启动 | 新用户无行为 | 注册属性、引导选兴趣、热门与多样性打散，逐步收敛到个性化 |
| 物品冷启动 | 新物品无交互 | 基于内容的推荐补位（[ContentProfile](/docs/CS/RecommenderSystem/ContentProfile.md)）、相似物品迁移、探索性流量扶持 |
| 系统冷启动 | 数据整体稀疏 | 先用规则与运营精选池，边积累边切 CF |

另外三个必须显式管理的效应：

- **流行度偏差**：热门物品更容易被观察到，于是更容易被推荐，形成自我强化。缓解手段是相似度分母做热门惩罚、混排阶段控制品类与热度配比
- **信息茧房**：一味贴合历史兴趣会让推荐越来越窄。需要在召回里保留探索路（随机/新类目/社交关系），这也是 Pipeline 中"混排"存在的理由
- **数据稀疏**：真实系统的评分密度极低，邻居数常常不足。做法是降维（隐向量）、跨域借数据（内容/知识图谱特征），或把 [特征工程](/docs/CS/AI/ML/FeatureEngineering.md) 产出的统计特征喂给排序模型

## Evaluation

协同过滤的原始形态是**评分预测**（显式打分），而今天多数业务做的是**Top-K 推荐**（隐式行为），两套指标不能混着谈：前者用 RMSE、MAE 衡量分值误差，后者用 Precision@K / Recall@K / NDCG 衡量列表命中，生态侧还要看覆盖率与多样性。

需要提醒的一点是：RMSE 很低并不等于推荐好用——它只在**已观测的**评分上计算，而推荐真正关心的是没被观测过的那部分物品的**相对次序**。指标定义、为什么离线与在线经常背离、实验怎么设计，统一见 [Evaluation](/docs/CS/RecommenderSystem/Evaluation.md)（基础定义亦见 [ML](/docs/CS/AI/ML/ML.md)）。

## Links

- [推荐系统](/docs/CS/RecommenderSystem/RecommenderSystem.md)
- [Scenario](/docs/CS/RecommenderSystem/Scenario.md)
- [Pipeline](/docs/CS/RecommenderSystem/Pipeline.md)
- [Recall](/docs/CS/RecommenderSystem/Recall.md)
- [Ranking](/docs/CS/RecommenderSystem/Ranking.md)
- [Evaluation](/docs/CS/RecommenderSystem/Evaluation.md)
- [Architecture](/docs/CS/RecommenderSystem/Architecture.md)
- [UserProfile](/docs/CS/RecommenderSystem/UserProfile.md)
- [ContentProfile](/docs/CS/RecommenderSystem/ContentProfile.md)
- [KNN](/docs/CS/AI/ML/KNN.md)
- [PCA](/docs/CS/AI/ML/PCA.md)
- [Clustering](/docs/CS/AI/ML/Clustering.md)
- [LinearModel](/docs/CS/AI/ML/LinearModel.md)
- [FeatureEngineering](/docs/CS/AI/ML/FeatureEngineering.md)
- [ML](/docs/CS/AI/ML/ML.md)

## References

1. [推荐系统实践-豆瓣](https://book.douban.com/subject/10769749/)
2. [矩阵分解与降维模块文档-scikit-learn](https://scikit-learn.org/stable/modules/decomposition.html)
3. [从零开始了解推荐系统全貌-微信公众号](https://mp.weixin.qq.com/s/n1PB5LGppaxlfRWx8WxhLg)
