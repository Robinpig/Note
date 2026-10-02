## Introduction

偏差（bias）在这里的含义很具体：**你观测到的分布，不等于你想优化的分布**。用户点击了，不代表他更喜欢；物品没被点，可能根本没被看到；某类内容供给少，可能只是上一版系统没给它曝光。

偏差不是随机噪声，加数据量消不掉——它是系统性的，而且会随"用观测数据训练并再次上线"这个闭环被**放大**。所以去偏的正确姿势不是找一个万能正则项，而是：先说清偏差从哪来（谱系），再决定在哪一层处理（数据、机制、估计、评估），最后用能扛住偏差的口径去度量效果。

## 偏差谱系

| 偏差 | 生成机制 | 直接后果 | 常在哪一层处理 |
| ------ | ------ | ------ | ------ |
| 样本选择偏差（SSB） | 只有被曝光的物品才有标签 | 模型只在"上一版系统认为值得看"的子分布上训练 | 建模结构（全空间）、估计（加权） |
| 位置偏差 | 靠前的位置天然被看得更多 | 把"排得靠前"误学成"更好" | 特征与倾向建模 |
| 可见性偏差 | 下发不等于被看到 | 未看见被当成"拒绝"，CTR 口径失真 | 埋点口径（见 [DataEngineering](/docs/CS/RecommenderSystem/DataEngineering.md)） |
| 流行度偏差 | 行为本身幂律分布 + 系统自我强化 | 长尾物品学不到表示，覆盖率坍塌 | 采样与目标设计 |
| 一致性偏差 | 模型自信度高 → 更多曝光 → 数据更支持该判断 | 反馈回路锁死，探索不足 | 探索流量与损失设计 |
| 新鲜度偏差 | 新物品缺少历史统计特征 | 冷启动阶段被系统性低估 | 特征结构与初始化（见 [ContentProfile](/docs/CS/RecommenderSystem/ContentProfile.md)） |
| 人群与设备偏差 | 不同人群的行为口径不同（活跃度、埋点缺失率） | 整体指标掩盖局部恶化 | 分组评估 |
| 归因偏差 | 多触点下功劳分配规则影响标签 | 优化了标签而非用户价值 | 标签定义 |

## 反馈回路为什么会锁死

一个简化的循环：模型给出排序 → 排在前面的得到曝光 → 曝光产生点击数据 → 数据被当成偏好去训练下一版模型。如果链路里没有任何"随机性"，这条回路只会把已有信念不断加固，即使最初的排序带有噪声。这就是为什么"我们数据很多"和"我们的数据很丰富"是两件事——**量大但都来自同一个策略，信息量并不高**。

打破它的唯一办法是主动注入不确定性：留出一部分流量做随机或近似随机（$\epsilon$-greedy、UCB、Thompson 采样，机制见 [ReinforcementLearning](/docs/CS/AI/ML/ReinforcementLearning.md)）。这部分流量的短期指标通常会变差，它的价值体现在两个别处买不到的用途上：为反事实估计提供**已知倾向概率**的样本，以及提供一个"没有被当前策略污染"的评估基准。

## 倾向与位置偏差建模

位置偏差的标准分析框架是检验模型（examination hypothesis）：点击需要同时满足"被看到"和"确实相关"，于是

$$
P\left( \mathrm{click} = 1 \mid u, i, p \right) = P\left( \mathrm{examine} = 1 \mid p \right) \cdot P\left( \mathrm{rel} = 1 \mid u, i \right)
$$

位置 $p$ 只进入第一项，因此 $\mathrm{examine}(\cdot)$ 就是这一位置的**倾向**。估计它有三条路，可信度与成本不同：

- **随机化实验**：把同一批结果在不同位置间打乱投放，用观测到的点击率曲线直接反推倾向。这是金标准，也是唯一能被质疑者接受的数据，代价是让出一部分流量
- **联合建模**：把位置作为特征训练模型，推理时对所有候选固定为同一个位置取值，从而比较"位置之外"的差异。实现简单，但容易把位置效应与其他共现因素混在一起
- **迭代估计（EM 一类）**：在"相关性与倾向相乘"的假设下交替估计两个因子。不需要额外流量，但假设一旦不成立，结果会稳定地错

有了倾向，就能给样本加权重：位置越靠后（被看到的概率越低）的点击，权重越高。这也解释了为什么"点击即正例、曝光未点即负例"这种朴素标签会系统性地偏袒排在前面的一小撮物品。

## 重要性加权家族

设日志由旧策略 $\pi_0$ 生成，想评估新策略 $\pi$ 的期望收益。记 $w_k = \pi(a_k \mid x_k) / \pi_0(a_k \mid x_k)$：

$$
\hat{V}_{\mathrm{IPS}} = \frac{1}{n}\sum_{k=1}^{n} w_k \, r_k, \qquad
\hat{V}_{\mathrm{SNIPS}} = \frac{\sum_{k} w_k r_k}{\sum_{k} w_k}
$$

- **IPS**：无偏，但方差可能极大（旧策略几乎没走过某个动作时，一次纠正权重就能吞掉整个估计）
- **SNIPS**（自归一化）：用权重和做分母，方差显著更小，代价是引入一点偏。多数工程场景选它
- **DR**（双重稳健）：混入一个结果预测模型 $\hat{r}$ 做残差修正

$$
\hat{V}_{\mathrm{DR}} = \frac{1}{n}\sum_{k=1}^{n}\left[ \hat{r}(x_k, a_k) + w_k \left( r_k - \hat{r}(x_k, a_k) \right) \right]
$$

  倾向模型或结果模型**只要有一个准**，估计就无偏，实践中也比纯 IPS 稳

三个必做的工程细节：权重截断（clip，控制最坏方差）、把 $\pi_0$ 显式落进日志（否则事后无法还原，探索流量白留）、以及在离线指标与 IPS 估计同时看——两者不一致时，通常是评估协议而不是模型出了问题。

## 建模结构层面的去偏

有些偏差用结构解决比用权重解决更划算：

- **全空间建模**：CVR 类任务只在点击后的样本上有标签，但线上要决策的是曝光环节。把 $\mathrm{pCTCVR} = \mathrm{pCTR} \times \mathrm{pCVR}$ 作为监督目标，就能在整个曝光空间上训练，绕开 SSB（ESMM 一脉，见 [Ranking](/docs/CS/RecommenderSystem/Ranking.md)）
- **采样偏差修正**：双塔召回用流行度分布采负样本时，从 logit 里减掉 $\log Q$，避免模型学到"热门即无关"（见 [Recall](/docs/CS/RecommenderSystem/Recall.md)）
- **多目标解耦**：把热度与相关性分开建模，热度作为可控项参与融合，而不是让它藏在 CTR 里；配合生态类目标（覆盖率、供给公平）进入优化目标，见 [Scenario](/docs/CS/RecommenderSystem/Scenario.md)
- **表征与初始化**：新物品用内容侧向量初始化，避免"没有历史 → 分数低 → 更没有历史"。这类结构性做法的效果通常比事后加权更持久

## 因果视角与增量建模

相关的问题("用户会点吗")与因果的问题("因为推了他才点吗")在预算分配上会给出完全不同的答案。用潜在结果记号：

$$
\tau(x) = \mathbb{E}\left[ Y(1) - Y(0) \mid X = x \right]
$$

$\tau(x)$ 是干预带来的**增量**（uplift），而不是响应概率。差别在运营与广告补贴场景里最刺眼：响应模型会优先挑出"本来就会买的人"发券，因为他们的 $P(Y=1)$ 最高；而真正值得花预算的是"发券才买、不发就不买"的人。用 $\hat{r}(x)$ 与 $\hat{r}(x) + \hat{\tau}(x)$ 的差别决定动作，才是增量决策。

工程上常用两个模型相减（T-learner）或单模型带干预特征（S-learner）来估增量，两者都依赖"干预分配近似随机"这一前提；若流量由旧策略决定，就要回到倾向加权或工具类方法。这一片仍是研究活跃区，落地时的合理期待是：**能把明显错配的预算决策纠正过来，但不要指望它给出精确到个体的因果效应**。

## 生态侧偏差与代价

去偏不止是"把用户偏好估得更准"，还包括两类常被忽略的对象：

- **供给者侧**：新作者与小商家的历史行为稀薄，模型对它们的估计方差大，排序在不确定时倾向保守，于是它们更难拿到第一次曝光。处理方式是显式扶持位、按人群/供给分层的配额，或对新物品使用乐观估计（不确定性加成）
- **人群侧**：整体指标提升可能伴随某个人群体验下降，必须分组看指标，而不是只看均值

还要坦白代价：随机探索、多样性约束与扶持配额都会让**短期核心指标变差**。这是一次用可量化的短期损失换取长期信息与生态健康的交换，应当作为业务决策被明确批准，而不是藏在算法的默认参数里——否则它会在下一次指标复盘时被无声地关掉。

## 怎么判断去偏有效

三件事必须同时成立，缺一个结论都不牢：

- **有未污染的标尺**：留出随机曝光流量作为无偏测试集，或在公开数据上用带随机曝光的子集（如 KuaiRand，见 [DataEngineering](/docs/CS/RecommenderSystem/DataEngineering.md)）
- **离线与估计量一起看**：常规指标 + IPS/SNIPS/DR 估计，两套口径同向才叫改善；只有常规指标改善，很可能只是把偏差学得更像
- **线上交叉验证**：去偏策略的效果差异常常在小数点后几位，需要足量样本与完整观察周期（实验设计见 [Evaluation](/docs/CS/RecommenderSystem/Evaluation.md)）

偏差不能被消除，只能被度量、被约束、被显式管理。一个健康的系统不是"没有偏差"，而是**知道自己在哪几处有偏、幅度多大、以及谁在为它付账**。

## Links

- [推荐系统](/docs/CS/RecommenderSystem/RecommenderSystem.md)
- [DataEngineering](/docs/CS/RecommenderSystem/DataEngineering.md)
- [Evaluation](/docs/CS/RecommenderSystem/Evaluation.md)
- [Ranking](/docs/CS/RecommenderSystem/Ranking.md)
- [Recall](/docs/CS/RecommenderSystem/Recall.md)
- [Scenario](/docs/CS/RecommenderSystem/Scenario.md)
- [ContentProfile](/docs/CS/RecommenderSystem/ContentProfile.md)
- [ReinforcementLearning](/docs/CS/AI/ML/ReinforcementLearning.md)

## References

1. [Recommendations as Treatments: Debiasing Learning and Evaluation-arXiv](https://arxiv.org/abs/1602.05352)
2. [Counterfactual Risk Minimization: Learning from Logged Bandit Feedback-arXiv](https://arxiv.org/abs/1502.02362)
3. [KuaiRand: An Unbiased Sequential Recommendation Dataset with Randomly Exposed Videos-arXiv](https://arxiv.org/abs/2208.08696)
