## Introduction

召回（Retrieval / Matching）解决的问题是：候选集太大，精排模型打分打不动。百万到十亿级物品，逐条过一遍深度网络在延迟与算力上都不成立，于是先用**极廉价**的方法把候选压到千级。

这一层的成功标准与精排相反——召回要的是**不漏**，不是准。评价召回只看一件事：用户最终会喜欢（以及精排会选中）的那批物品，有多少被这一层捞进来了。宁可多带十倍噪声候选交给下游过滤，也不能让物品根本没进候选池——它一旦没被召回，后面的模型再强也追不回来。这也解释了为什么线上永远是多路并行，而不是一路做到极致。

## 多路召回

每一路是一种不同的"可能性假设"，彼此互补：

| 召回路 | 假设 | 强项 | 失效场景 |
| ------ | ------ | ------ | ------ |
| 热度/榜单 | 大多数人的选择对个体也成立 | 零冷启动、稳定兜底 | 毫无个性化，加剧马太效应 |
| 标签/属性倒排 | 画像标签命中即相关 | 可解释、可控、支持业务强约束 | 标签体系粗糙时召回质量差 |
| ItemCF 共现 | 共同出现的物品可互相替代 | 精度高、天然发现关联 | 稀疏与长尾物品进不去（见 [CollaborativeFiltering](/docs/CS/RecommenderSystem/CollaborativeFiltering.md)） |
| 向量召回 | 用户与物品可嵌入同一空间 | 泛化好、能召回没共现过的物品 | 需要大量数据与训练，解释性弱 |
| 内容/多模态 | 图文音视频特征相似即相关 | 新物品唯一可用的一路 | 语义相似不等于用户想要 |
| 探索/随机 | 未知即价值 | 打破反馈回路、给新物品机会 | 短期指标难看，必须单独配额 |

融合环节有三个坑：

- **分数不可比**：各路输出的量纲完全不同（共现次数、余弦相似度、模型 logit），直接混排会让某一路吞掉全部位置。常见做法是按路配额（每路固定 Top-N）或做名次/分位数归一化，把"跨路可比"这个问题绕开而不是解决
- **去重时机**：同一物品被多路命中时，保留最高名次即可；但去重前必须先做业务过滤（下架、无库存、已曝光），否则配额被无效候选占满
- **总量控制**：召回合并后的规模直接决定下游成本，粗排/精排预算都是按候选条数算的

## 倒排召回

非向量召回的主力是**倒排索引**：把"物品 → 词条"翻转为"词条 → 物品列表"，查询时用用户侧的词条集合去并/交物品列表（搜索引擎侧的实现见 [ES](/docs/CS/Framework/ES/ES.md?id=inverted-index)）。

$$
\mathrm{Posting}(t) = [\, i_1, i_2, \dots, i_{n_t} \,]
$$

即倒排链保存所有带词条 $t$ 的物品。用户画像里的标签、近期行为物品的类目与关键词、人群包 ID 都可以作为查询词条。三个工程要点：

- **词典大小决定成本**：高频词条（"手机壳"）的倒排链可能上千万长，必须截断（按质量分取 Top-K）或分层（先按类目分区再检索）
- **约束过滤要下推**：在架、可售、时效、地域这类硬条件应在倒排阶段就与布尔位求交，而不是等打分后再过滤，否则召回出来的全是无效候选
- **实时性靠增量**：新物品的词条要能秒级进索引，靠的是"全量索引 + 增量段 + 定期合并"，和搜索引擎的 segment 思路一致（LSM 结构与布隆过滤器的取舍见 [BloomFilter](/docs/CS/DB/LevelDB/BloomFilter.md)）

## 双塔向量召回

**结构**：用户塔 $f_u$ 吃用户特征（画像标签、行为序列、上下文），物品塔 $g_i$ 吃物品特征（ID embedding、类目、文本、统计量），各自输出一个 $k$ 维向量，打分用内积或余弦：

$$
s(u, i) = \left\langle f_u(x_u),\; g_i(x_i) \right\rangle, \qquad \hat{y}_{u,i} = \sigma\!\left( s(u,i) / \tau \right)
$$

**为什么必须是双塔**：不是为了"简单"，而是为了让物品侧的计算**与用户无关**，从而可以离线批量算全量物品向量、预先建成 ANN 索引；在线只需算一次用户向量。任何把用户与物品特征交叉到网络深层的模型（如 DIN 那类）都无法预先建索引，只能给候选打分——这正是"召回模型"与"排序模型"结构差异的根本原因，而不是效果差异。

**训练目标**：从"点击/正样本 vs 随机负样本"的二分类，等价的更稳形式是 sampled softmax——把正样本与采样出的负样本组成一组，最大化正样本在这组里的概率：

$$
P(i^{+} \mid u) = \frac{\exp\left( s(u, i^{+}) / \tau \right)}{\exp\left( s(u, i^{+}) / \tau \right) + \sum_{j \in \mathcal{N}} \exp\left( s(u, j) / \tau \right)}
$$

几个必须显式管理的细节：

- **负样本决定一切**：全量 softmax 算不动，实际从某个分布 $Q(j)$ 里采若干个物品当负样本。用**流行度分布**采会让模型把"没见过"和"不重要"混为一谈，热门物品被过度压制；因此常用 $\log Q$ 修正——把采样概率从 logit 里减掉，即 $s(u,j) \leftarrow s(u,j) - \log Q(j)$。Batch 内负样本（同一批其他样本的正例当负例）实现最省事，但它的 $Q$ 就是流行度，修正几乎是必需的
- **温度 $\tau$**：越小，概率分布越尖锐、越强调难负例，也越容易训崩。向量检索里内积的尺度还直接影响 ANN 索引的距离分布，通常配合 L2 归一化把打分约束在 $[-1,1]$
- **难负例**：只用随机负例会让模型只学会"分清毫不相关"，线上区分度不足。加入"曝光未点击"或"同簇不同 item"的难负例能显著提升排序质量，但比例过高会伤害召回率
- **ID 稀疏**：新物品没有 ID embedding。做法是走内容侧特征，或让 ID embedding 与内容 embedding 相加，保证新物品也能被检索到

一个最小训练骨架（batch 内负样本 + 温度）：

```python
# user_emb: [B, k]  item_emb: [B, k]  对角线为正样本，同批其他物品为负样本
def in_batch_softmax_loss(user_emb, item_emb, tau=0.05):
    u = F.normalize(user_emb, dim=-1)
    i = F.normalize(item_emb, dim=-1)
    logits = u @ i.t() / tau                 # [B, B]，相似度矩阵
    targets = torch.arange(logits.size(0))   # 第 b 行第 b 列是正样本
    loss = F.cross_entropy(logits, targets)
    # 若负样本按流行度采样，需要 logits[b, j] -= logQ[j] 修正
    return loss
```

工程上还会让 ID embedding 单独走参数服务器而 dense 层走常规同步训练——两侧参数量差几个数量级，这是工业实现的常见分工。

## ANN 向量检索

拿到 $10^6 \sim 10^9$ 个向量后，精确最近邻要求每次查询与全部物品算距离，延迟与内存都不可接受，于是改用**近似最近邻**（Approximate Nearest Neighbor，ANN）：牺牲一点召回率换数量级的加速。

三类主流方案：

- **HNSW（分层可导航小世界图）**：把点组织成多层图，上层稀疏、下层稠密，查询从顶层贪心走到底层，像跳表一样逐层缩小搜索范围。关键参数是每点邻居数 $M$、建图搜索宽度 `efConstruction`、查询搜索宽度 `efSearch`。特点是召回率-延迟曲线优秀、支持增量插入，代价是**内存占用高**（要存图）
- **IVF（倒排文件聚类）**：先用 k-means 把向量分成 $n_{\mathrm{list}}$ 个簇，查询时只扫最近的 $n_{\mathrm{probe}}$ 个簇。天然适合与属性过滤结合（同簇同分区），但簇边界上的点会被漏掉
- **PQ（乘积量化）**：把 $d$ 维向量切成 $m$ 段，每段在一个 256 元质心码本里找最近的一个，用 1 字节编码——向量压缩到 $m$ 字节。距离计算变成查表累加（ADC），内存与算力同时下降，精度损失靠残差量化补偿

选择上的实际折中：

| 目标 | 常选 | 原因 |
| ------ | ------ | ------ |
| 高召回低延迟、内存充裕 | HNSW | 图结构导航效率高 |
| 十亿级、内存受限 | IVF + PQ | 压缩比可达数十倍 |
| 需要按属性过滤 | IVF 系 + 分区 | 粗量化器天然可做分区裁剪 |
| 高频更新的小库 | 倒排 + 少量向量路 | 图索引重建成本被摊薄 |

三个线上必须盯住的点：**索引版本与模型版本必须一致**（换了 embedding 模型却查旧索引，等于随机召回）；**增量与全量的合并节奏**决定新物品多久可被召回；**归一化一致性**——训练与检索时 L2 归一化的有无会改变距离分布，让参数全部失效。专用向量库的索引选型与部署实践见 [Milvus](/docs/CS/DB/Milvus/Milvus.md)；数据量不算极端、希望少一个组件时，关系库的向量扩展也够用（如 [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md) 的 pgvector），代价是高并发下的性能与索引种类受限。

## 召回层怎么评估

不能用精排的指标评召回，否则会得到误导性的结论：

- **Recall@K / 命中率**：以"精排 top 结果"或"真实点击物品"为真值，看召回是否把它捞进候选。这是召回最核心的离线指标，且必须**分路统计**——总量达标但某一路长期为 0 是常见的隐性故障
- **覆盖率**：召回能触达的物品占全库比例，衡量长尾是否根本没机会
- **与精排的一致性**：召回结果的精排平均分（或 top 命中率）比绝对分数更稳，用它判断某路是否退化
- **线上口径**：各路配额与实际曝光来源占比、超时率、兜底触发比例。召回退化往往不体现在 AUC 上，而体现在"曝光来源结构变了"

> [!WARNING]
> 离线 Recall@K 用全库做候选时，热门物品会天然占优；正确做法是按时间切分、按用户分组，并把候选池限制在该时刻真实可推荐的物品集合上，否则评估结果无法复现在线表现（详见 [Evaluation](/docs/CS/RecommenderSystem/Evaluation.md)）。

## Links

- [推荐系统](/docs/CS/RecommenderSystem/RecommenderSystem.md)
- [Pipeline](/docs/CS/RecommenderSystem/Pipeline.md)
- [CollaborativeFiltering](/docs/CS/RecommenderSystem/CollaborativeFiltering.md)
- [Ranking](/docs/CS/RecommenderSystem/Ranking.md)
- [ContentProfile](/docs/CS/RecommenderSystem/ContentProfile.md)
- [UserProfile](/docs/CS/RecommenderSystem/UserProfile.md)
- [KNN](/docs/CS/AI/ML/KNN.md)
- [Milvus](/docs/CS/DB/Milvus/Milvus.md)
- [ES](/docs/CS/Framework/ES/ES.md?id=inverted-index)
- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)
- [LevelDB-BloomFilter](/docs/CS/DB/LevelDB/BloomFilter.md)
- [Architecture](/docs/CS/RecommenderSystem/Architecture.md)
- [Debiasing](/docs/CS/RecommenderSystem/Debiasing.md)

## References

1. [Deep Learning Recommendation Model for Personalization and Recommendation Systems-arXiv](https://arxiv.org/abs/1906.00091)
1. [Efficient and robust approximate nearest neighbor search using HNSW graphs-arXiv](https://arxiv.org/abs/1603.09320)
1. [Faiss: 相似检索与向量聚类库官方文档](https://faiss.ai/)
1. [推荐系统实践-豆瓣](https://book.douban.com/subject/10769749/)
