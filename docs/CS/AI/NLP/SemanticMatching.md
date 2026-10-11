## Introduction

语义匹配（semantic matching）研究的是「两段文本之间的关系」。它在方法谱系上处在分类与生成之间：不像分类那样给单条文本贴标签，也不像生成那样产出新的文本——输入永远是一个句对（sentence pair），输出是「它们有多像」「后一句能否由前一句推出」「是不是同一个意思的两种说法」。

这个看似狭窄的任务族，是「语义」从学术概念变成工程组件的地方：搜索的召回与排序、检索增强生成（retrieval-augmented generation，RAG）里的文档筛选、问答系统的答案匹配、推荐系统的物品相似度、去重与聚类的判定，背后调用的都是同一类模型。本篇按「任务族盘点 → 方法演进 → 双塔与交叉编码器的架构权衡 → NLI 的训练价值 → 评估」的顺序展开，最后回到它作为工程组件的形态。

## The Sentence Pair Task Family

句对任务的输出空间各不相同，输入形态却完全一致，盘点一圈能看清它们之间的亲缘关系：

- 语义相似度（semantic textual similarity，STS）：给两句话打一个连续的相似度分，是对称任务；
- 自然语言推理（natural language inference，NLI）：判断前提（premise）与假设（hypothesis）之间是蕴含（entailment）、中立（neutral）还是矛盾（contradiction），三分类且方向明确；
- 复述识别（paraphrase identification）：二分类判断两句话是否同义，可以看成相似度任务在阈值上的离散化；
- 问答匹配：判断问题与候选答案、候选证据段落是否相关，是问答流水线中的一环（细节见 [QuestionAnswering](/docs/CS/AI/NLP/QuestionAnswering.md)）；
- 检索排序：给查询与文档打相关性分，是搜索引擎与向量检索的核心动作。

把这几项并排放，会发现它们要求的监督信号是同一种东西——带关系标注的句对。由此派生出这个领域反复出现的现象：某个任务攒下的数据，常被借去训练另一个任务的模型，最早的例子就是 NLI 数据哺育句表示，后面会专门讲。

从建模角度看，这些任务都归结为同一个函数：输入是两条文本，输出是它们之间的关系。输出是标量还是类别并不改变模型面对的输入结构，真正决定架构分岔的在于——两条文本在什么位置发生交互。

### Similarity Is Not Entailment

两个概念最容易被混为一谈，值得单独厘清。**相似度是标量且对称**：a 与 b 的相似度等于 b 与 a 的相似度。**蕴含是方向性关系**：a 蕴含 b 并不意味着 b 蕴含 a。

字面相似与语义蕴含更不等价：「一个人在遛狗」与「一个人没有在遛狗」字面高度重合，语义却完全对立；「一个人在遛狗」与「有动物在被牵着走」字面差得远，后者却由前者推出。多数学术定义把相似度视为双向蕴含加信息量对等的特例，但工程直觉上要记住：相似度是「距离」，蕴含是「推理」，一个对称一个带方向。

训练信号的差异会直接体现在模型行为上：用 NLI 监督出来的编码器对方向敏感，用 STS 监督出来的只关心远近。这也是同一个句对数据集里三种任务常被混用时，效果时好时坏的根源。

## From Lexical Overlap to Learned Encoders

方法演进有一条清晰的主线：字符串 → 词的集合 → 词向量的集合 → 上下文表示 → 句向量。每往前一步，「比较」发生的位置就向后移一点——从比字符串、比词表，一直到比模型算出的表示。

### Lexical Baselines

严格的字面方法不需要任何训练：词重叠率（overlap）、编辑距离（Levenshtein distance）、以及把句子当词袋的 TF-IDF 余弦相似度。

编辑距离是典型的动态规划问题，自底向上填表求解（见 [DP](/docs/CS/Algorithms/DP/DP.md)）；TF-IDF 余弦则把句子先变成稀疏向量再比较夹角，已经隐含「先把文本表示为向量、再在向量空间里比较」的思路（见 [Representation](/docs/CS/AI/NLP/Representation.md)）。

它们共同的天花板是只能识别词形重合：同义替换、语序调整、否定翻转都会让分数失真——「好」与「棒」字面上毫无关系，「好」与「不好」却字面高度重合。但只要语料规模小、领域窄，这些基线仍然可用；正式模型上线前跑一个字面基线（lexical baseline）是值得的，它给出的低线让后续模型的增益变得可信。

### Averaged Word Vectors and Siamese Networks

分布式词向量（word2vec、GloVe）出现后，最直接的句表示做法是把句中所有词向量平均，或按词频加权平均（如 SIF 加权），再算余弦。相比词袋，它抓到了同义与近义，但丢掉了词序——「狗咬人」与「人咬狗」的词集合完全相同，做不到区分。

更关键的变化发生在结构上：孪生网络（siamese network，也就是后来所称的双塔）让两个句对共享同一个编码器，各自独立编码后在末端比较。编码器共享意味着「编码方式」与「比较方式」解耦——改比较规则不必重训编码器；两条分支互不交互则意味着编码结果可以缓存，这个性质后来变成了整个检索架构的地基。

InferSent 是这条路线上的关键证据：它用 NLI 数据监督训练句表示，再迁移到其他句对任务，第一次系统性地说明「为某个句对任务训练的表示」可以充当通用句子编码器；Universal Sentence Encoder（USE）把这一思路做成开箱可用的通用编码器，一套多任务训练支撑多种相似度需求。

不过早期方案共享一个局限：表示能力受限于「词向量的池化」——语序、结构、否定等都无法表达。行业的思路因此开始转向——从「设计一种距离」变成「让模型学会距离」。

### Cross-Encoders

Transformer 带来了另一条路：把两句话用分隔符（如 [SEP]）拼成一条序列送进模型，让注意力机制在两层文本之间充分交互，输出层再做一个分类或回归头。这就是交叉编码器（cross-encoder），也叫句对分类器（sentence-pair classifier）。

在 GLUE 系列的 NLI、STS 任务上，交叉编码器长期占据精度最高一档：因为每个 token 都能「看到」另一句话的每个 token，细微的否定、数量、方向差异都能被捕捉。

代价也直接到近乎残酷：每一对文本都要过一次完整模型，文本之间没有任何可以预计算、复用的部分。一个查询对一百万个候选打分，就是一百万次前向推理；为文档预先建索引、让多个查询共享计算，都无从谈起。**「算力随候选数线性增长」这个约束，是此后整个领域架构演化的主线。**

所以交叉编码器的定位从一开始就不是「检索器」而是「判官」——它把精度上限撑到最高，却只能对少量候选行使这个上限。

### Sentence Embeddings and Contrastive Learning

SBERT（Sentence-BERT）把孪生 BERT 与池化接起来，其核心贡献是认真解决了「句向量怎么训练才适合算余弦」：在 NLI 与 STS 数据上用回归与分类目标微调，使余弦相似度与人工语义相似度对齐。同样是一万句两两比较的相似度矩阵，交叉编码器以小时计，SBERT 降到秒级——双塔由此复兴。

之后对比学习（contrastive learning）成为主干手段。SimCSE 展示了最简洁的形式：同一句话过两次编码器（不同的 dropout 掩码）当作正例，批内其他句子当作负例，完全无监督就能训出很强的句向量；有监督版本则用 NLI 的蕴含对做正例、矛盾对做硬负例（hard negative）。

E5 等模型把对比预训练扩大到大规模弱监督配对语料，成为文本检索的默认骨干之一。至此「先各自编码、再算余弦」的路线彻底站稳：训练目标负责把语义结构压进向量空间，推理时全部计算只有一次编码加一次内积。

这条路线对数据的使用方式与直觉相反：模型不是用人工标注的「相似度分数」学会比较的，而是被训练目标「安排」进一个余弦距离恰好代理语义关系的空间——学习发生在目标函数里，而不在推理时的比较动作里。

### Instruction-Following LLMs

大模型把配对任务收编进了指令形态：直接要求模型输出「蕴含/矛盾/中立」，或给出相似度判断和理由。优势是零样本泛化（新任务只需改提示）与可解释（可以要求写出推理链）；短板同样鲜明——成本高、分数校准（calibration）差（模型给出 0.8 分并不对应 80% 的概率）、批量场景下稳定性不足。

因此现实系统里它更常以混合形态出现：LLM 作为教师模型蒸馏（distillation）出小型双塔编码器，或只对双塔召回、精排之后的少量候选做最终裁决。

配对任务没有被 LLM 取代，而是被更深地封装进流水线——它变成了大模型工具箱里的一个函数调用，而不是一个独立的模型品类。

## Bi-Encoders versus Cross-Encoders

两条路线的差异可以一句话概括：**交互发生在什么位置**。双塔把交互推迟到最终的向量比较，交叉编码器让交互贯穿编码全过程。

| 维度 | 双塔 bi-encoder | 交叉编码器 cross-encoder |
| ------ | ------ | ------ |
| 编码方式 | 两句各自独立编码 | 拼接为一条序列联合编码 |
| 跨句交互 | 只在末尾比较向量 | 注意力层全程交互 |
| 文档向量能否预计算 | 能，离线编码并建索引 | 不能，每对实时计算 |
| 单个查询成本 | 一次编码 + 向量检索 | 与候选数成正比的前向推理 |
| 精度 | 有损失，靠训练目标弥补 | 最高一档 |
| 可支撑规模 | 亿级候选 | 百级候选 |
| 典型角色 | 召回 recall | 精排 rerank |

不存在全面胜出的一方：交叉编码器精度高但吞吐差，双塔吞吐好但精度有损。工程答案不是二选一，而是让两者各做擅长的一段——这也是「模型能力」与「系统能力」在 NLP 里第一次明确分开。

### Two-Stage Retrieval

标准形态叫两阶段检索（two-stage retrieval）：**双塔召回、交叉编码器精排**。双塔把查询与全部文档映射到同一向量空间，用近似最近邻（approximate nearest neighbor，ANN）检索在毫秒级取回 top-k（几百到几千个候选）；交叉编码器再对这 k 个候选逐一打分重排，产出最终 top-n。检索增强生成的检索端就是这一结构，精排模型也由此获得独立代号——reranker（见 [RAG](/docs/CS/AI/RAG.md)）。

DPR（Dense Passage Retrieval）是这一形态在开放域问答上的代表作：查询编码器与段落编码器分开训练，用问题-段落对与批内负例优化内积检索，把「稠密检索」从实验推成默认方案。

ColBERT 提出迟交互（late interaction）作为折中：双塔各自编码，但保留每个 token 的向量；打分时用查询与文档 token 向量的最大相似度求和（MaxSim）。它既保留了「文档侧可预计算」，又恢复了词级细粒度匹配，中间地带由此有了名字。

推荐系统与检索是同构的：用户塔与物品塔各自编码、内积近似兴趣度、再用更重的模型精排。「双塔召回 + 轻量交互打分」这套模式，成了所有「从海量候选里找相关项」问题的通用解。

## NLI as a Training Signal

NLI 的价值不止于任务本身。SNLI 以约 57 万条人工标注句对确立了规模标准，MultiNLI 把覆盖扩展到多体裁的书面语与口语，两者合起来成了句对研究的基础训练集。

更重要的是它作为训练信号的「形状」：蕴含 / 中立 / 矛盾三分类，恰好要求模型区分「同义改写」「无关」「对立」三种关系——而这正是句向量需要内化的结构。InferSent 用它训练通用句表示，SBERT 用它的蕴含对与矛盾对构造训练目标，SimCSE 的有监督版本沿用同一套构造——「用 NLI 数据训练句子表示」从一条经验发现变成了默认路线。

但也别把两者等同。前面讲过，蕴含是有方向的，相似度是对称的；在 NLI 上监督出来的表示，若不重新设计训练目标，做对称相似度任务时并不天然对齐。SBERT 要在 NLI 之外补 STS 回归目标、SimCSE 要另设对比目标，都是在同一个缝隙上打的补丁。

还有一层工程启示：NLI 数据名义上是「推理数据」，实践中最大的用途反而是表示学习——一个有明确标注规范的推理数据集，意外成了通用语义空间的建材。这类「数据用途偏离设计初衷」的例子，在 NLP 史上反复出现。

## Evaluation

STS 任务的标准评测是秩相关：把模型打分与人工打分分别排序，计算 Spearman 相关系数，STS Benchmark 是各篇论文通用的基准。NLI 简单一些，直接看三分类准确率。

评估噪声在这类任务上尤其明显：相似度标注本身主观，同一对句子该打 3.5 分还是 4 分因人而异，标注者间一致性（inter-annotator agreement）构成模型分数的实际上限；Spearman 相差一两个点通常并不构成显著差异，论文里的「反超」需要看方差与多次采样。

指标细节、统计检验与各类任务的评估陷阱，集中收在 [Evaluation](/docs/CS/AI/NLP/Evaluation.md)。

## Semantic Matching as a Component

回看整条演进线：任务形态几乎没有变过——始终是「给两段文本判关系」，改变的是把它做成什么组件。字面与词向量时代，它是一个算法；交叉编码器时代，它是一类高精度但昂贵的模型；对比学习之后，它收缩为一个可索引的向量接口；而在大模型系统里，它被进一步封装——检索端是双塔加索引，重排端是交叉编码器或大模型，用户看不到模型，只看到一个相似度 API。

检索、去重、聚类、推荐调用的都是这个接口，这正是「语义」从学术概念变成工程组件的地方：不再追问「模型是否真的理解」，而是问「向量空间里的距离能否稳定代理语义关系」。RAG 与向量数据库把这套接口推成默认基础设施，也反过来不断给双塔提出新要求——多语言、长文本、指令感知、领域适配。

## Links

- [NLP](/docs/CS/AI/NLP/NLP.md)
- [Representation](/docs/CS/AI/NLP/Representation.md)
- [QuestionAnswering](/docs/CS/AI/NLP/QuestionAnswering.md)
- [RAG](/docs/CS/AI/RAG.md)
- [Evaluation](/docs/CS/AI/NLP/Evaluation.md)
- [LLM](/docs/CS/AI/LLM/LLM.md)

## References

- [A large annotated corpus for learning natural language inference-SNLI](https://arxiv.org/abs/1508.05326)
- [A Broad-Coverage Challenge Corpus for Sentence Understanding through Inference-MultiNLI](https://arxiv.org/abs/1704.05426)
- [Supervised Learning of Universal Sentence Representations from Natural Language Inference Data-InferSent](https://arxiv.org/abs/1705.02364)
- [Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks](https://arxiv.org/abs/1908.10084)
- [SimCSE: Simple Contrastive Learning of Sentence Embeddings](https://arxiv.org/abs/2104.08821)
- [ColBERT: Efficient and Effective Passage Search via Contextualized Late Interaction over BERT](https://arxiv.org/abs/2004.12832)
- [Dense Passage Retrieval for Open-Domain Question Answering](https://arxiv.org/abs/2004.04906)
