## Introduction

推荐算法其实本质上是一种信息处理逻辑，当获取了用户与内容的信息之后，按照一定的逻辑处理信息后，产生推荐结果。

热度排行榜就是最简单的一种推荐方法，它依赖的逻辑就是当一个内容被大多数用户喜欢，那大概率其他用户也会喜欢。但是基于粗放的推荐往往会不够精确，想要挖掘用户个性化的、小众化的兴趣，需要制定复杂的规则运算逻辑，并由机器完成。

## 推荐算法的主要步骤

- **召回**：当用户以及内容量比较大的时候，往往先通过召回策略，将百万量级的内容先缩小到百量级。
- **过滤**：对于内容不可重复消费的领域，例如实时性比较强的新闻等，在用户已经曝光和点击后不会再推送到用户面前。
- **精排**：对于召回并过滤后的内容进行排序，将百量级的内容并按照顺序推送。
- **混排**：为避免内容越推越窄，将精排后的推荐结果进行一定修改，例如控制某一类型的频次。
- **强规则**：根据业务规则进行修改，例如在活动时将某些文章置顶

## 漏斗的真实形状

上面五步在工业系统里通常还要再插一层**粗排**（pre-ranking）：召回与精排之间，用极轻的模型（双塔点积、蒸馏出的小模型）先把万级候选压到千级，好让精排的深度网络在预算内跑得完。完整的漏斗是"逐级截断"，而**截断即信息损失**——上游没捞上来的物品，下游再强也救不回来。

下面是一张典型的量级与延迟预算表。数字随业务差别很大（短视频与电商的候选规模可差两个数量级），它的价值不在具体数值，而在于说明**预算是分配出来的，不是等来的**：

| 阶段 | 候选量级 | 常见延迟预算 | 这一层真正优化的目标 | 典型失败模式 |
| ------ | ------ | ------ | ------ | ------ |
| 请求解析与触发 | 1 | 几毫秒 | 拿到可用上下文与画像 | 画像服务超时，退化成非个性化 |
| 多路召回 | $10^{6\sim9} \to 10^{3\sim4}$ | 10–40 ms | **不漏**（覆盖率） | 单路依赖、索引与模型版本错配、召回为空 |
| 过滤 | $\to 10^{3}$ | 几毫秒 | 满足硬约束（在架、时效、已曝光） | 过滤过严致空结果；过松则白占下游配额 |
| 粗排 | $\to 10^{2\sim3}$ | 10–30 ms | 与精排尽量一致的序 | 蒸馏目标错位，把精排想推的排到后面 |
| 精排 | $\to 10^{2}$ | 50–150 ms | 预估准确（含校准） | 特征拉取成瓶颈、超时后走兜底分数 |
| 重排/混排 | $\to 10^{1}$ | 5–20 ms | 整列价值与多样性 | 规则彼此冲突、频控层层叠加后无解 |
| 强规则 | 覆盖少数位置 | 近零 | 业务意志 | 静默覆盖模型结果，让归因失真 |

链路总响应一般压在几百毫秒内，其中相当一部分不是模型计算，而是**数据搬运**。这决定了两件常被忽视的事：

- 加一级模型容易，减一次远程调用才是提速的主要手段（并发扇出与批量拉取的做法见 [TPP](/docs/CS/RecommenderSystem/TPP.md)，分层与预算的完整讨论见 [Architecture](/docs/CS/RecommenderSystem/Architecture.md)）
- 每多一级截断，整体误差就会跨级放大：召回用相似度、粗排用小模型、精排用大模型，三者的目标并不完全一致，**级间一致性**（上游是否给下游留了正确答案）比单级指标的绝对值更值得监控

## 样本回流与训练闭环

链路不只是在线打分，它同时是数据的生产者。一条完整闭环的口径必须事先约定：

- **三类日志**：请求日志（当时有哪些候选、各在哪一位置）、曝光日志（真正进入可见区域的）、行为日志（点击/时长/转化）。缺任何一类，位置偏差与反事实评估就无从下手（见 [Evaluation](/docs/CS/RecommenderSystem/Evaluation.md)）
- **特征快照**：训练时的特征值必须来自**曝光那一刻**的状态，而不是重跑时的当前状态。用离线重算的特征去训练，线上会学到一套不存在的因果
- **拼接窗口**：正样本要等到标签落地（转化可能滞后数天），窗口太短会低估、太长会牺牲新鲜度
- **过滤与去重**：反作弊、误点击、爬虫、重复曝光要先剔除，否则模型学的是攻击流量
- **更新节奏**：全量重训 + 增量/在线学习是常见组合。快反馈场景（短视频）小时级甚至分钟级，慢反馈场景（电商成交）天级

离在线一致性问题的常见来源，按排查顺序：特征口径不同（在线取实时值、离线取日级值）、特征穿越（统计量窗口包含未来）、缺失值处理不一致、模型与索引版本错配、上游过滤与频控改变了实际曝光分布。这一段只讲链路上的必要环节，埋点口径、日志分层、流式乱序与迟到、特征平台与样本表的落地细节见 [DataEngineering](/docs/CS/RecommenderSystem/DataEngineering.md)，偏差的系统处理见 [Debiasing](/docs/CS/RecommenderSystem/Debiasing.md)。

## Algorithm Families

按**信号来源**分，推荐算法可归为四类。同一个业务里四者常同时存在，差别在于拿什么当依据：

- **基于关系**：不理解物品本身，只看"谁和谁的行为相似"。协同过滤是这一类的代表，UserCF/ItemCF 两条路、相似度度量与热门惩罚见 [CollaborativeFiltering](/docs/CS/RecommenderSystem/CollaborativeFiltering.md)
- **基于行为**：把点击、停留、收藏按时间累积成用户行为序列，用统计或序列模型预测下一个动作，与 [HMM](/docs/CS/AI/ML/HMM.md)、[ReinforcementLearning](/docs/CS/AI/ML/ReinforcementLearning.md) 一脉相通
- **基于内容**：靠标签与向量刻画物品，用画像匹配代替行为共现，是新用户/新物品冷启动阶段唯一可用的依据（加工链路见 [UserProfile](/docs/CS/RecommenderSystem/UserProfile.md)、[ContentProfile](/docs/CS/RecommenderSystem/ContentProfile.md)）
- **基于模型**：把以上信号统一喂给一个可训练的打分模型，从矩阵分解走到梯度提升树再到深度模型，是当前精排环节的主流形态

## Model Evolution

精排模型的演进主线（由浅到深），逐个模型的推导与取舍见 [Ranking](/docs/CS/RecommenderSystem/Ranking.md)：

- **GBDT-LR**：[GBDT](/docs/CS/AI/ML/EnsembleLearning.md) 自动学习特征组合，输出作为 [逻辑回归](/docs/CS/AI/ML/LinearModel.md) 的输入——大规模 CTR 预估的起点
- **FM / FFM**：为每个特征学习隐向量，二阶交叉不再依赖人工设计（隐向量本身与矩阵分解同源，见 [CollaborativeFiltering](/docs/CS/RecommenderSystem/CollaborativeFiltering.md)）
- **Wide&Deep / DeepFM**：记忆与泛化两路结合的深度模型，端到端学习高阶交叉
- **发展趋势**：注意力机制建模行为序列（DIN）、多任务多目标联合建模，以及与强化学习结合的序列决策优化（见 [ReinforcementLearning](/docs/CS/AI/ML/ReinforcementLearning.md)）

## 召回与精排的模型视角

- **召回**讲多样性：多路并行——热门召回、协同过滤（"喜欢 A 的人也喜欢 B"，原理与实现见 [CollaborativeFiltering](/docs/CS/RecommenderSystem/CollaborativeFiltering.md)）、向量召回（用户与内容各编码成向量，近邻检索，距离度量见 [KNN](/docs/CS/AI/ML/KNN.md)）。多路如何配额、双塔怎么训练、ANN 索引怎么选，见 [Recall](/docs/CS/RecommenderSystem/Recall.md)
- **精排**本质是点击率（CTR）预估——一个典型的二分类问题：早期用[逻辑回归](/docs/CS/AI/ML/LinearModel.md) + 大规模特征交叉，主流换成[梯度提升树](/docs/CS/AI/ML/EnsembleLearning.md)与深度模型；特征质量决定上限，[特征工程](/docs/CS/AI/ML/FeatureEngineering.md)在搜推广行业是第一生产力。样本、校准与重排的完整链条见 [Ranking](/docs/CS/RecommenderSystem/Ranking.md)
- **评估**：离线看 AUC/F1（见 [ML](/docs/CS/AI/ML/ML.md) 评价指标），在线看 CTR、停留时长、留存，以 A/B 实验为准。为什么离线与在线经常背离、实验要怎么做，见 [Evaluation](/docs/CS/RecommenderSystem/Evaluation.md)

## Links

- [推荐系统](/docs/CS/RecommenderSystem/RecommenderSystem.md)
- [Scenario](/docs/CS/RecommenderSystem/Scenario.md)
- [CollaborativeFiltering](/docs/CS/RecommenderSystem/CollaborativeFiltering.md)
- [Recall](/docs/CS/RecommenderSystem/Recall.md)
- [Ranking](/docs/CS/RecommenderSystem/Ranking.md)
- [Evaluation](/docs/CS/RecommenderSystem/Evaluation.md)
- [Architecture](/docs/CS/RecommenderSystem/Architecture.md)
- [DataEngineering](/docs/CS/RecommenderSystem/DataEngineering.md)
- [Advertising](/docs/CS/RecommenderSystem/Advertising.md)
- [UserProfile](/docs/CS/RecommenderSystem/UserProfile.md)
- [ContentProfile](/docs/CS/RecommenderSystem/ContentProfile.md)
- [TPP](/docs/CS/RecommenderSystem/TPP.md)

## References

1. [从零开始了解推荐系统全貌-微信公众号](https://mp.weixin.qq.com/s/n1PB5LGppaxlfRWx8WxhLg)
1. [DeepFM: A Factorization-Machine based Neural Network for CTR Prediction-arXiv](https://arxiv.org/abs/1703.04247)
1. [Wide & Deep Learning for Recommender Systems-arXiv](https://arxiv.org/abs/1606.07792)
1. [推荐系统实践-豆瓣](https://book.douban.com/subject/10769749/)
