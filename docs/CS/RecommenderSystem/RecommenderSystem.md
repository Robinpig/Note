## Introduction

Recommendation systems, often known as recommender systems, are a type of information filtering system that attempts to forecast the "rating" or "preference" that a user would assign to an item.

推荐系统的目的是找出人与其它之间的连接 人即是用户 连接可以是用户和商品 也可以是用户和内容 用户和用户 暂且将其它统称为物品 即用户和物品之间的连接

要实现推荐需要预测用户评分和偏好 通常实现的方式是机器推荐和人工推荐。预测问题模式主要有两大类：

- **评分预测**：预测连接强度
- **行为预测**：预测是否会产生连接

推荐系统主要是由数据、算法、架构三个方面组成

- **数据提供了信息**。数据储存了信息，包括用户与内容的属性，用户的行为偏好例如对新闻的点击、玩过的英雄、购买的物品等等。这些数据特征非常关键，甚至可以说它们决定了一个算法的上限。
- **算法提供了逻辑**。数据通过不断的积累，存储了巨量的信息。在巨大的数据量与数据维度下，人已经无法通过人工策略进行分析干预，因此需要基于一套复杂的信息处理逻辑，基于逻辑返回推荐的内容或服务。
- **架构解放了双手**。架构保证整个推荐自动化、实时性的运行。架构包含了接收用户请求，收集、处理，存储用户数据，推荐算法计算，返回推荐结果等。
  有了架构之后算法不再依赖于手动计算，可以进行实时化、自动化的运行。
  例如在淘宝推荐中，对于数据实时性的处理，就保证了用户在点击一个物品后，后续返回的推荐结果就可以立刻根据该点击而改变。
  一个推荐系统的实时性要求越高、访问量越大那么这个推荐系统的架构就会越复杂

推荐的框架主要有以下几个模块：

- **协议调度**：请求的发送和结果的回传。在请求中，用户会发送自己的 ID，地理位置等信息。结果回传中会返回推荐系统给用户推荐的结果。
- **推荐算法**：算法按照一定的逻辑为用户产生最终的推荐结果。不同的推荐算法基于不同的逻辑与数据运算过程。
- **消息队列**：数据的上报与处理。根据用户的 ID，拉取例如用户的性别、之前的点击、收藏等用户信息。而用户在 APP 中产生的新行为，例如新的点击会储存在存储单元里面。
- **存储单元**：不同的数据类型和用途会储存在不同的存储单元中，例如内容标签与内容的索引存储在 mysql 里，实时性数据存储在 redis 里，需要进行数据统计的数据存储在 TDW 里

## Service Architecture

从在线服务的组件拆分视角，推荐系统架构包括：

- 业务流量入口
- 在线投放服务
- 特征与画像服务
- 召回与索引服务
- 在线存储服务
- 在线预估服务
- 排序策略服务

三要素加上"为谁做"与"怎么算成功"，展开为本目录的子篇：

| 侧面 | 展开为 | 关心什么 |
| ------ | ------ | ------ |
| 场景 | [Scenario](/docs/CS/RecommenderSystem/Scenario.md)、[Advertising](/docs/CS/RecommenderSystem/Advertising.md) | 不同业务里目标函数与约束长什么样，什么时候根本不该做推荐；广告作为同一套底座上的机制层 |
| 数据 | [UserProfile](/docs/CS/RecommenderSystem/UserProfile.md)、[ContentProfile](/docs/CS/RecommenderSystem/ContentProfile.md)、[DataEngineering](/docs/CS/RecommenderSystem/DataEngineering.md) | 标签与画像的生产链路，以及埋点、日志分层、特征一致性与样本构造 |
| 算法 | [Pipeline](/docs/CS/RecommenderSystem/Pipeline.md)、[CollaborativeFiltering](/docs/CS/RecommenderSystem/CollaborativeFiltering.md)、[Recall](/docs/CS/RecommenderSystem/Recall.md)、[Ranking](/docs/CS/RecommenderSystem/Ranking.md) | 链路的组织方式，以及召回与排序两级各自的原理与实现 |
| 评估 | [Evaluation](/docs/CS/RecommenderSystem/Evaluation.md)、[Debiasing](/docs/CS/RecommenderSystem/Debiasing.md) | 离线指标、在线实验、离在线为何背离；偏差从哪来、怎么度量与被谁付账 |
| 架构 | [Architecture](/docs/CS/RecommenderSystem/Architecture.md)、本节 Service Architecture、[TPP](/docs/CS/RecommenderSystem/TPP.md) | 组件如何拆分，延迟预算与一致性怎么保，算法如何以在线服务的形式被编排、压测、降级 |

## Development Timeline

理解现在的技术选择，需要知道每一步是被什么问题逼出来的：

| 阶段 | 关键工作 | 它真正解决的问题 |
| ------ | ------ | ------ |
| 1992 | Tapestry：邮件流的协同过滤 | 用"人的标注"代替人工筛选，首次提出"协同"信号 |
| 1994 | GroupLens：新闻组评分预测 | 把推荐形式化为**评分预测**，自动化不依赖专家标注 |
| 2001 | Item-based CF；矩阵分解引入 | 用户相似度算不动 → 物品更稳定；稀疏矩阵降维 |
| 2006–2009 | Netflix Prize | 确立"以 RMSE 为唯一裁判"的评测范式与模型融合工程做法 |
| 2010 | FM | 大规模稀疏特征下的**自动二阶交叉**，且能算得动（$O(nk)$） |
| 2014 | GBDT + LR | 把交叉搜索外包给树模型，CTR 预估工业化 |
| 2016–2019 | Wide&Deep、DeepFM、DIN、多任务（MMoE/ESMM）、DLRM | embedding 与深度结构成为主流；兴趣随候选变化；多目标共享底座 |
| 2016 起普及 | HNSW / IVF-PQ 等 ANN 索引被主流库纳入 | 十亿级**向量召回**才真正上线成为标准件 |
| 近年 | 序列生成式建模、以语言模型补物品语义理解 | 冷启动与跨域语义泛化；成本与收益尚在收敛中 |

一条主线贯穿始终：**交叉与表示的学习不断从人工转向模型，而候选规模与延迟的约束从未放松**——所以链路（而不是单个模型）才是推荐系统的真实形态。

## How to Read

由浅入深的顺序，也是本目录的组织逻辑：

1. 本篇：它解决什么问题、由哪些部件组成
2. [Scenario](/docs/CS/RecommenderSystem/Scenario.md)：应用场景与业务形态，为什么不同场景做法不同、什么时候不该做推荐
3. [Advertising](/docs/CS/RecommenderSystem/Advertising.md)：同一套预估底座之上的机制层（拍卖、计费、预算）
4. [Pipeline](/docs/CS/RecommenderSystem/Pipeline.md)：召回 → 粗排 → 精排 → 重排的漏斗，各级的规模、延迟与失败模式
5. [CollaborativeFiltering](/docs/CS/RecommenderSystem/CollaborativeFiltering.md)：最经典的一族算法，原理与冷启动
6. [Recall](/docs/CS/RecommenderSystem/Recall.md)：多路召回、双塔模型与向量检索
7. [Ranking](/docs/CS/RecommenderSystem/Ranking.md)：CTR 建模谱系、样本与特征、校准与重排
8. [Evaluation](/docs/CS/RecommenderSystem/Evaluation.md)：离线指标、离在线背离、A/B 实验与反事实评估
9. [Debiasing](/docs/CS/RecommenderSystem/Debiasing.md)：偏差谱系、位置与倾向建模、IPS/SNIPS/DR、增量效应与生态代价
10. [DataEngineering](/docs/CS/RecommenderSystem/DataEngineering.md)：埋点口径、日志分层、特征一致性、样本构造与公开数据集的局限
11. [Architecture](/docs/CS/RecommenderSystem/Architecture.md)：厂商中立的在线服务体系——延迟预算、一致性、降级与成本
12. [UserProfile](/docs/CS/RecommenderSystem/UserProfile.md) / [ContentProfile](/docs/CS/RecommenderSystem/ContentProfile.md)：数据侧的标签与画像怎么造
13. [TPP](/docs/CS/RecommenderSystem/TPP.md)：上述架构在阿里搜推广的具体产品形态

## Common Pitfalls

- 把它当"算法项目"而不是产品机制——目标函数由业务决定，算法只是执行
- 迷信离线指标：离线只能否证，不能证明收益（见 [Evaluation](/docs/CS/RecommenderSystem/Evaluation.md)）
- 只调模型结构，不管样本时间口径与特征一致性——大多数"效果不涨"来自这两处
- 只留一路自认最强的召回，覆盖率与生态随之坍塌
- 不留探索流量，日志被上一版策略锁死，越训越窄
- 忽视位置偏差、延迟预算与合规要求，它们往往是决定可行解集的第一约束

## Links

- [CS](/docs/CS/CS.md)
- [Scenario](/docs/CS/RecommenderSystem/Scenario.md)
- [Advertising](/docs/CS/RecommenderSystem/Advertising.md)
- [UserProfile](/docs/CS/RecommenderSystem/UserProfile.md)
- [ContentProfile](/docs/CS/RecommenderSystem/ContentProfile.md)
- [CollaborativeFiltering](/docs/CS/RecommenderSystem/CollaborativeFiltering.md)
- [Pipeline](/docs/CS/RecommenderSystem/Pipeline.md)
- [Recall](/docs/CS/RecommenderSystem/Recall.md)
- [Ranking](/docs/CS/RecommenderSystem/Ranking.md)
- [Evaluation](/docs/CS/RecommenderSystem/Evaluation.md)
- [Debiasing](/docs/CS/RecommenderSystem/Debiasing.md)
- [DataEngineering](/docs/CS/RecommenderSystem/DataEngineering.md)
- [Architecture](/docs/CS/RecommenderSystem/Architecture.md)
- [TPP](/docs/CS/RecommenderSystem/TPP.md)
- [Feed](/docs/CS/SE/Feed.md)

## References

1. [从零开始了解推荐系统全貌-微信公众号](https://mp.weixin.qq.com/s/n1PB5LGppaxlfRWx8WxhLg)
