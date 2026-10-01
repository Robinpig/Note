## Introduction

隐马尔可夫模型（Hidden Markov Model，HMM）是描述"**由隐藏状态序列生成可观测序列**"的统计模型。它的经典用途是 NLP（分词、词性标注、命名实体识别）和语音识别——在这些任务里，我们能"看到"的只有观测（词序列、音频帧），真正关心的状态（标签、音素）却是隐藏的。

从模型谱系上看，HMM 属于动态模型（Dynamic Model）一族，同族还有 Kalman Filter（线性高斯、连续状态）与 Particle Filter（非线性、采样近似）：

- 有向图模型：Bayesian Network（贝叶斯网络）
- 无向图模型：Markov Random Field（马尔可夫随机场，又称 Markov Network）
- 动态模型：HMM、Kalman Filter、Particle Filter

## Definition

HMM 由隐藏状态序列 $I=(i_1,\dots,i_T)$ 生成观测序列 $O=(o_1,\dots,o_T)$，全部参数记为 $\lambda=(A,B,\pi)$：

| 参数 | 含义 | 矩阵维度 |
| ------ | ------ | ---------- |
| $\pi$ | 初始状态概率分布 | N 维向量 |
| $A$ | 状态转移概率矩阵 $a_{ij}=P(i_{t+1}=q_j\mid i_t=q_i)$ | N×N |
| $B$ | 观测（发射）概率矩阵 $b_j(k)=P(o_t=v_k\mid i_t=q_j)$ | N×M |

它建立在两个假设之上：

1. **齐次马尔可夫性假设**：下一时刻的状态只依赖当前状态，与更早的历史无关
2. **观测独立性假设**：任一时刻的观测只依赖当前时刻的状态

## Three Problems

HMM 的实际使用归结为三个基本问题：

### 概率计算：前向-后向算法

给定模型 λ，求观测序列 $O$ 出现的概率 $P(O\mid\lambda)$。直接枚举所有状态路径是指数级的，**前向算法**用动态规划把复杂度降到 $O(NT^2)$，递推定义前向概率：

$$
\alpha_t(i)=P(o_1,o_2,\dots,o_t,\ i_t=q_i\mid\lambda)
$$

$$
\alpha_{t+1}(i)=\left[\sum_{j=1}^{N}\alpha_t(j)\,a_{ji}\right]b_i(o_{t+1})
$$

后向算法对称地从序列末尾向前递推，两者结合可算任意时刻状态的边际概率。

### 学习：Baum-Welch 算法

只有观测序列、没有状态标注时，用 **Baum-Welch 算法**（EM 算法在 HMM 上的实例）估计参数 λ：

- E 步：用当前参数推算各时刻状态的后验期望（前向-后向概率）
- M 步：按期望频数重新估计 $\pi, A, B$，迭代至收敛

若有状态标注数据（监督学习），直接用极大似然按频率统计即可。

### 预测：Viterbi 算法

给定模型 λ 和观测序列 $O$，求最可能的隐藏状态序列。**Viterbi 算法**同样是动态规划，把前向算法的"求和"换成"取最大"，并回溯记录路径：

$$
\delta_{t+1}(i)=\max_{1\le j\le N}\left[\delta_t(j)\,a_{ji}\right]b_i(o_{t+1})
$$

## Applications

- **中文分词**：把 B（词首）/M（词中）/E（词尾）/S（单字词）当作隐藏状态，字是观测，用 Viterbi 找最优标注序列
- **词性标注**：词性是隐藏状态，单词是观测
- **语音识别**：音素是隐藏状态，音频特征帧是观测（GMM-HMM 时代的主流框架）
- 其它：基因序列分析、股票隐含状态推断等

> [!TIP]
> 状态转移 + 发射观测 + 动态规划求解的套路同样出现在 CRF、Seq2Seq 解码等后续模型中，HMM 是理解序列标注问题的起点。

## Pros and Cons

- **优点**：结构清晰、训练与解码算法成熟；对小数据集也能训练；天然建模序列的时序依赖
- **缺点**：齐次马尔可夫与观测独立两个假设过强；观测之间不能直接相互依赖；状态数需预设；长距离依赖无法表达（这也是后来 CRF、RNN 取代它在 NLP 主流地位的原因）

## Links

- [ML](/docs/CS/AI/ML/ML.md)
- [NLP](/docs/CS/AI/NLP/NLP.md)
- [Clustering](/docs/CS/AI/ML/Clustering.md)

## References

1. [统计学习方法（第2版）第10章 隐马尔可夫模型-豆瓣](https://book.douban.com/subject/33437381/)
2. [Hidden Markov model-Wikipedia](https://en.wikipedia.org/wiki/Hidden_Markov_model)
