## Introduction

**标签是我们对多维事物的降维理解，抽象出事物更具有代表性的特点。**
我们永远无法完全的了解一个人，所以我们只能够通过一个一个标签的来刻画他，所有的标签最终会构建为一个立体的画像，一个详尽的用户画像可以帮助我们更加好的理解用户。

用户画像的生产链路：原始数据 → 事实标签 → 模型标签，信息逐层加工、逐层提纯。

## Raw Data

原始数据一共包含四个方面：

- **用户数据：** 例如用户的性别、年龄、渠道、注册时间、手机机型等。
- **内容数据：** 例如游戏的品类，对游戏描述、评论的爬虫之后得到的关键词、标签等。
- **用户与内容的交互：** 基于用户的行为，了解了什么样的用户喜欢什么样的游戏品类、关键词、标签等。
- **外部数据：** 单一的产品只能描述用户的某一类喜好，例如游戏的喜好、视频的喜好，外部数据标签可以让用户更加的立体

## Factual Tags

事实标签可以分为静态画像和动态画像：

- **静态画像：** 用户独立于产品场景之外的属性，例如用户的自然属性，这类信息比较稳定，具有统计性意义。
- **动态画像：** 用户在场景中所产生的显示行为或隐式行为。
- **显示行为**：用户明确的表达了自己的喜好，例如点赞、分享、关注、评分等。（评论的处理更加复杂，需要通过 NLP 的方式来判断用户的感情是正向、负向、中性）。
- **隐式行为**：用户没有明确表达自己的喜好，但"口嫌体正直"，用户会用实际行动，例如点击、停留时长等隐性的行为表达自己的喜好。

隐式行为的权重往往不会有显示行为大，但是在实际业务中，用户的显示行为都是比较稀疏的，所以需要依赖大量的隐式行为。

## Model Tags

模型标签是由事实标签通过加权计算或是聚类分析所得。通过一层加工处理后，标签所包含的信息量得到提升，在推荐过程中效果更好。

- **聚类分析：** 例如按照用户的活跃度进行聚类，将用户分为高活跃-中活跃-低活跃三类。（无监督聚类方法见 [Clustering](/docs/CS/AI/ML/Clustering.md)）
- **加权计算：** 根据用户的行为将用户的标签加权计算，得到每一个标签的分数，用于之后推荐算法的计算

画像分数最终服务于哪一步，取决于算法链路的设计：作为召回依据时它参与相似度计算，作为特征时它进入精排模型。前者见 [CollaborativeFiltering](/docs/CS/RecommenderSystem/CollaborativeFiltering.md)，后者见 [Pipeline](/docs/CS/RecommenderSystem/Pipeline.md)。

## Hierarchy of the Tag System

工程上通常把标签按"离原始数据多远"分四层，越往下越依赖推断、也越需要置信度：

| 层 | 例子 | 生产方式 | 可验证性 |
| ------ | ------ | ------ | ------ |
| 事实标签 | 性别、注册渠道、机型、下单次数 | 直接落库或简单统计 | 高，可核对 |
| 规则标签 | 近 30 天母婴类目下单 ≥ 2 次、周末活跃 | 阈值 + 时间窗口聚合 | 高，口径明确 |
| 模型标签 | 价格敏感度、潜在流失、品类偏好强度 | 有监督模型或聚类 | 需要抽检与线上验证 |
| 意图标签 | 本次会话在比价、刚搬家 | 短序列实时推断 | 最难验证，衰减最快 |

一个标签要能用进链路，必须同时带三件元数据：**口径定义**（含时间窗与去重规则）、**更新时间**、**置信度**。缺置信度就无法在召回侧做截断，也无法在排序侧判断"这个特征值此刻是否可信"。

生产方法的几条主路：多窗口统计聚合；有监督分类（有正样本可标的属性）；无监督聚类（分群，方法见 [Clustering](/docs/CS/AI/ML/Clustering.md)）；从搜索词与评论内容里做 NLP 抽取（见 [NLP](/docs/CS/AI/NLP/NLP.md)）；图上传播（共同购买、社交邻居，适合关系类标签）。

## Time Decay and Score Composition

偏好必须遗忘，否则老兴趣会永久占据画像。指数衰减是最常用的写法：

$$
w(\Delta t) = e^{-\lambda \Delta t}, \qquad \lambda = \frac{\ln 2}{T_{1/2}}
$$

半衰期 $T_{1/2}$ 是业务参数：资讯场景以小时计，电商以月计。同一批行为换个半衰期会得出不同的用户分群，所以它属于**标签口径的一部分**，必须写进元数据，而不是散落在各段 SQL 里。

标签分数的合成通常是"行为权重 × 时间衰减"的累加：

$$
s(u, t) = \sum_{k} \alpha_k \, w(\Delta t_k) \, \mathbf{1}\left[ t \in \mathcal{T}_k \right]
$$

其中 $\mathcal{T}_k$ 是第 $k$ 次行为产生的标签集合，$\alpha_k$ 是该行为类型的权重。行为权重按承诺程度递增（浏览 < 点击 < 收藏/加购 < 购买 < 复购），而**负反馈权重要显著大于任何正反馈**——"不感兴趣""举报""快速划走"是最强的信号，却最常被漏接或漏配权重。

## Storage and Serving

画像同时被离线训练与在线打分读取，两条路的诉求相反（吞吐 vs 点查延迟），因此常见双链路：

- **离线全量**：T+1 批计算，落到分析型存储，供训练取特征与做人群分析
- **实时增量**：行为经消息队列由流式作业更新，供在线读（链路做法见 [Flink](/docs/CS/Framework/Flink/Flink.md)）
- **在线读**：按 uid 点查，KV 存储（见 [Redis](/docs/CS/DB/Redis/Redis.md)）；标签量极大时按命名空间分列，只拉本次请求需要的字段，否则网络传输会成为打分瓶颈

画像服务与特征服务经常被合并成一个组件，但**口径必须统一**：训练用的是离线快照、在线用的是实时值，两者不一致就是离在线不一致问题的第一现场（排查顺序见 [Pipeline](/docs/CS/RecommenderSystem/Pipeline.md)）。

## Quality and Compliance

- **覆盖率**：有多少比例的用户带这个标签。低覆盖标签进模型只会变成噪声
- **准确率**：抽检标注或与后续真实行为对齐（预测"近期购买母婴"的用户，之后是否真的购买）
- **时效**：更新延迟与衰减是否匹配业务的兴趣变化速度
- **合规**：画像属于个人信息处理范畴。中国《互联网信息服务算法推荐管理规定》要求提供"不针对其个人特征的选项"或便捷的关闭入口，且用户关闭后应立即停止——这意味着**非个性化兜底链路必须真实存在并可测试**。数据侧则遵循最小必要：只为已声明的推荐目的采集与加工，关闭后不再用于个性化（原文见 Scenario 的 References）

## Links

- [推荐系统](/docs/CS/RecommenderSystem/RecommenderSystem.md)
- [Scenario](/docs/CS/RecommenderSystem/Scenario.md)
- [ContentProfile](/docs/CS/RecommenderSystem/ContentProfile.md)
- [CollaborativeFiltering](/docs/CS/RecommenderSystem/CollaborativeFiltering.md)
- [Recall](/docs/CS/RecommenderSystem/Recall.md)
- [Ranking](/docs/CS/RecommenderSystem/Ranking.md)
- [Pipeline](/docs/CS/RecommenderSystem/Pipeline.md)
- [Clustering](/docs/CS/AI/ML/Clustering.md)
- [NLP](/docs/CS/AI/NLP/NLP.md)
- [Flink](/docs/CS/Framework/Flink/Flink.md)

## References

1. [从零开始了解推荐系统全貌-微信公众号](https://mp.weixin.qq.com/s/n1PB5LGppaxlfRWx8WxhLg)
1. [互联网信息服务算法推荐管理规定-中国政府网](https://www.gov.cn/zhengce/zhengceku/2022-01/04/content_5666429.htm)
