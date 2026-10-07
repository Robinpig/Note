## Introduction

推荐的评估难在三处，而这三处都无法靠"再多算一个指标"绕开：

1. **反事实不可见**：只曝光了 Top-K，第 K+1 名的物品到底是好是坏，日志里没有证据
2. **数据有偏**：观测到的行为由上一版系统的曝光策略生成，样本本身就带选择偏差（下称 SSB，sample selection bias）
3. **真正的目标不可直接观测**：平台要的是长期留存与生态健康，能拿到的只有本次点击

于是评估分三层：离线指标做**筛选**（快速否掉明显更差的方案），在线实验做**判决**（因果意义上的增量），人工与生态指标做**体检**（防止前两层集体失明）。三者是不同用途，不能互相替代。

## Offline Metrics

**评分预测类**（显式评分场景）：

$$
\mathrm{RMSE} = \sqrt{\frac{1}{N}\sum_{k}\left( \hat{r}_k - r_k \right)^2}, \qquad
\mathrm{MAE} = \frac{1}{N}\sum_{k}\left| \hat{r}_k - r_k \right|
$$

只在**观测到的**评分上算，因此天然只代表"系统在自己见过的分布上准不准"。RMSE 降到很低也可能推荐得很烂：它惩罚的是分值误差，而 Top-K 排序只需要相对次序正确。

**Top-K 列表类**（更接近真实业务）：记前 $K$ 位中的命中数为 $h_K$，用户 $u$ 的真实正例集合为 $\mathcal{P}_u$，则

$$
\mathrm{Precision}_{K} = \frac{h_K}{K}, \qquad
\mathrm{Recall}_{K} = \frac{h_K}{|\mathcal{P}_u|}, \qquad
\mathrm{HitRate}_{K} = \mathbf{1}\left[ h_K > 0 \right]
$$

这三式即常说的 Precision@K、Recall@K、HitRate@K（下标换成位置截断记法）。三者侧重不同：Precision 看"推出去的有没有用"，Recall 看"该推的漏了多少"，HitRate 则是最贴近业务体感的口径（一屏里只要中一个就算赢）。

$$
\mathrm{MRR} = \frac{1}{|Q|}\sum_{q}\frac{1}{\mathrm{rank}_q}
$$

NDCG 把"位置有价值"写进公式：第 $j$ 位的贡献按对数折损，命中越靠前得分越高：

$$
\mathrm{DCG}_{K} = \sum_{j=1}^{K} \frac{2^{rel_j} - 1}{\log_2 (j+1)}, \qquad
\mathrm{NDCG}_{K} = \frac{\mathrm{DCG}_{K}}{\mathrm{IDCG}_{K}}
$$

这就是常说的 DCG@K 与 NDCG@K。分母 $\mathrm{IDCG}_{K}$ 是把同一批真值按理想顺序排列时的 $\mathrm{DCG}_{K}$，作用是**消除列表长度与命中数量的差异**，让不同用户的分数可以平均。增益取 $2^{rel}-1$ 会放越高相关项，取 $rel$ 则更线性——换定义会改变结论，所以对外报数必须同时报定义。

**排序能力与概率可信度是两件事**：

$$
\mathrm{AUC} = P\left( s_{\text{pos}} > s_{\text{neg}} \right)
$$

即随机取一正一负，模型给正例更高分的概率（可用秩和统计量高效算出）。它只看序、完全不管分值是否等于真实点击率，因此 AUC 与校准必须分开看（校准见 [Ranking](/docs/CS/RecommenderSystem/Ranking.md)）。更贴近业务的是 **GAUC**：按用户分组算 AUC 再加权平均，因为推荐真正要赢的是"同一个用户内部的次序"，全局 AUC 会被跨用户的尺度差异虚高：

$$
\mathrm{GAUC} = \frac{\sum_u w_u \, \mathrm{AUC}_u}{\sum_u w_u}
$$

权重 $w_u$ 常取用户 $u$ 的曝光数或点击数。

**生态与体验类**（不看准确性，看系统健康）：

- **覆盖率**：一段时间内被推荐过的物品 / 全库物品
- **新颖度**：常用自信息 $-\log_2 \mathrm{pop}(i)$ 衡量"推给用户的东西有多出人意料"
- **列表内多样性**：同一屏物品两两相似度的均值
- **基尼系数/流量集中度**：头部供给拿走了多少曝光

**一套最小可信的离线协议**（缺任何一条，数字都不作数）：

- 按**事件时间**切分训练/测试，禁止随机划分（防未来信息泄漏）
- 特征快照与标签时间对齐，统计窗口早于曝光时刻
- 候选池限制为"该时刻真实可推荐"的物品集合（在架、未过期、未曝光）
- 按用户分组统计显著性，长尾用户样本极少，全局平均会被头部用户绑架
- 同时报准确性与生态指标，防止"只推热门"刷出高分

## Why Offline and Online Diverge

这是推荐系统最频繁的事故来源，原因是结构性的：

- **曝光偏差**：离线只在历史曝光上评估，而新方案会把从未曝光过的物品推上来——它们没有标签，评估要么忽略（低估收益），要么当作负例（惩罚创新）
- **候选分布变了**：线上实际曝光 ≠ 模型 Top-K。过滤、频控、打散、保量、缓存与超时降级都会改写最终列表，模型侧的提升可能在下游环节被抹平
- **反馈延迟**：转化类指标需要更长观察窗，离线窗口截断会低估或高估收益
- **短期指标与长期价值错配**：单次会话的 CTR 提升可能伴随留存下降
- **新奇效应**：界面或策略变化本身带来短期指标波动，实验结束后回落
- **分母漂移**：推荐位曝光占比、活跃用户结构变化会让人均指标不可比——同一个数字，不同分母
- **线上耦合**：RT 变长会同时降低所有下游指标；性能问题常被误读成效果问题

结论是：离线指标只能用来**否证**（明显变差就不必上线），不能用来**证明**收益。

## Online Experiments

A/B 实验是在线判决的唯一常规手段，前提是分流与统计都成立。

**分流单元**决定因果解释是否干净：

- 按**用户**分流：同一用户体验一致，是默认选择
- 按**请求/曝光**分流：样本量利用率高，但同一用户在两组间来回切换，个体内互相污染，只适合无状态策略
- 存在网络效应或共享资源时（社交关系、库存、预算、主播流量池），用户级分流也会互相泄漏，需要集群分流或时间片轮转（switchback）

**先验证实验本身可信**，再看指标：

- **AA 实验**：两组用同一策略，指标应无显著差异；有差异说明分流或方差估计有问题
- **SRM（样本比例失配）**：用卡方检验比较实际流量与预期比例，一旦显著偏离，本次所有结论作废——最常见的成因是埋点、超时或某一组崩溃导致掉量
- **护栏先于收益**：性能（超时率、RT）、投诉、留存、供给公平都要一起看

**样本量与功效**。比例的绝对差 $\delta$、基线 $p$、双侧 $\alpha = 0.05$、功效 $1-\beta = 0.8$ 时，每组所需样本量近似：

$$
n \approx \frac{2\left( z_{1-\alpha/2} + z_{1-\beta} \right)^2 p(1-p)}{\delta^2} \approx \frac{16\, p(1-p)}{\delta^2}
$$

这条式子的实际含义是：**基线越接近 0.5 越难测，MDE 减半需要 4 倍样本**。指标本身高度右偏（人均时长、GMV）时方差远大于比例假设，因此要按经验方差代入，或用方差缩减（如以实验前同指标为协变量的 CUPED）来降低所需样本。

**并行实验的组织**：同一层内实验互斥（避免策略互相干扰），不同层正交（同一用户可同时在多层被命中）。层数与流量分配是治理问题：正交层之间理论上无交互，实际会相互污染，所以要定期把可疑组合单独拆一层验证。

**指标体系与决策**：北极星指标（一个）+ 护栏指标（若干，触发即停）+ 诊断指标（解释为什么）。多指标同时看必然出现偶然显著，需要事先约定主指标与校正方式（多重比较、或固定的观察时长而非提前偷看），并把放量节奏（如 1% → 5% → 20% → 50%）与回滚阈值写进实验设计。

## Counterfactual Evaluation

在没有实验位可用时（新策略无法上线、或要评估还没跑过的模型），可以用旧日志做离线重放。带倾向概率的日志（$\epsilon$-greedy、Thompson 采样等探索策略留下的 $\pi_0$，见 [ReinforcementLearning](/docs/CS/AI/ML/ReinforcementLearning.md)）能支持重要性采样估计：

$$
\hat{V}_{\mathrm{IPS}}(\pi) = \frac{1}{n} \sum_{k=1}^{n} \frac{\pi(a_k \mid x_k)}{\pi_0(a_k \mid x_k)} \, r_k
$$

这一节只回答"评估怎么用日志重放"。偏差本身的谱系（选择、位置、可见性、流行度、一致性）、倾向如何估计、SNIPS 与双重稳健估计量的取舍、以及增量效应的建模，展开在 [Debiasing](/docs/CS/RecommenderSystem/Debiasing.md)。

实践要点：

- **自归一化版本**（SNIPS，除以权重之和）方差更低、偏差略增，通常更稳
- **权重截断**：单个样本权重可能大到吞掉整个估计，必须 clip
- **位置偏差**：倾向概率里要包含"该位置被看到的概率"，否则点击差异被误读为偏好差异
- 纯贪心上线的系统日志 $\pi_0$ 近似退化为 0/1，IPS 方差爆炸，此时**只能得到很粗的界**——这是不留探索流量的长期代价

偏差本身（选择偏差、位置偏差、流行度偏差、一致性偏差）如何系统分类、倾向怎么估计、双重稳健估计量与增量效应建模，展开在 [Debiasing](/docs/CS/RecommenderSystem/Debiasing.md)。

## Online Monitoring and Degradation Detection

模型没换但效果掉了，通常是某个环节先烂了。日常盯的清单：

- **PCoC**（$\sum \mathrm{pCTR} / \sum \mathrm{click}$，预估点击数与实际点击数之比）偏离 1 的幅度与方向
- **特征质量**：缺失率、异常值比例、上下线变更
- **分布漂移**：PSI $= \sum_i (p_i - q_i)\ln\frac{p_i}{q_i}$，对 pCTR 与关键特征分桶后逐日对比
- **召回结构**：各路配额、去重后规模、实际曝光来源占比
- **依赖与版本**：模型版本、索引版本、特征服务版本三者是否一致（错配是静默故障）
- **性能**：P99 RT、超时率、降级触发次数——它们先于业务指标恶化

## Links

- [推荐系统](/docs/CS/RecommenderSystem/RecommenderSystem.md)
- [Pipeline](/docs/CS/RecommenderSystem/Pipeline.md)
- [Ranking](/docs/CS/RecommenderSystem/Ranking.md)
- [Recall](/docs/CS/RecommenderSystem/Recall.md)
- [CollaborativeFiltering](/docs/CS/RecommenderSystem/CollaborativeFiltering.md)
- [Scenario](/docs/CS/RecommenderSystem/Scenario.md)
- [ML](/docs/CS/AI/ML/ML.md)
- [ReinforcementLearning](/docs/CS/AI/ML/ReinforcementLearning.md)
- [Architecture](/docs/CS/RecommenderSystem/Architecture.md)
- [Debiasing](/docs/CS/RecommenderSystem/Debiasing.md)
- [DataEngineering](/docs/CS/RecommenderSystem/DataEngineering.md)
- [TPP](/docs/CS/RecommenderSystem/TPP.md)

## References

1. [模型评估指标文档-scikit-learn](https://scikit-learn.org/stable/modules/model_evaluation.html)
1. [Recommendations as Treatments: Debiasing Learning and Evaluation-arXiv](https://arxiv.org/abs/1602.05352)
1. [推荐系统实践-豆瓣](https://book.douban.com/subject/10769749/)
1. [从零开始了解推荐系统全貌-微信公众号](https://mp.weixin.qq.com/s/n1PB5LGppaxlfRWx8WxhLg)
