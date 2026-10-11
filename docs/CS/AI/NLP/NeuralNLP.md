## Introduction

2013 到 2018 年，自然语言处理（natural language processing, NLP）完成了一次范式更替：统计时代的手工特征流水线被神经网络取代，随后「预训练 + 微调」又重新定义了几乎所有任务的解法。回看这段演进，可以把它归结为对四个问题的连续回答——怎么建模序列、怎么对齐两个序列、怎么并行训练、怎么用上无标注语料（预训练）。

本篇按时间顺序梳理这条架构主线：从词向量出发，经过 RNN / LSTM / GRU、TextCNN、Seq2Seq 与注意力，到 Transformer，最后落在预训练范式的确立。语言模型本身的原理（n-gram、困惑度、自回归分解）在 [LanguageModeling](/docs/CS/AI/NLP/LanguageModeling.md) 单独展开，本篇只把它当作预训练目标来使用；Transformer 的内部机制在 [Transformer](/docs/CS/AI/Transformer.md) 逐层拆解，本篇只交代它在历史坐标上的位置。

## From Handcrafted Features to Word Vectors

神经网络之前，NLP 系统的主干是一条手工特征流水线：分词、词形还原、词性标注、依存句法分析，再由领域专家设计特征模板，喂给线性分类器或条件随机场（CRF）。每个环节都要单独维护，误差逐级累积，换一种语言或领域几乎要重新来过。

2013 年前后，word2vec 让局面开始转向：把词映射为稠密向量，使「语义相近」在向量空间里表现为「距离相近」，并且这些向量可以用大规模无标注文本上的预测任务（用中心词预测上下文，或用上下文预测中心词）自监督地学出来。结合 [Representation](/docs/CS/AI/NLP/Representation.md) 可以看到，静态词向量仍有明显局限，但它完成了最关键的一步：词不再是离散符号，而是可微、可训练的表示。

词向量 + 神经网络 = 端到端表示学习。模型不再需要「先解析句法再分类」，而是直接从词序列中学出任务所需的中间表示，特征工程的位置被网络层取代。这是后续一切架构的地基。

### The Gap Static Vectors Left

静态词向量还有一个结构性缺陷：同一个词在所有句子里拿到同一个向量，而「苹果」在「吃苹果」和「苹果发布会」里含义并不相同——一词多义无法区分。把上下文纳入表示（contextualized representation）于是成为下一个课题，这也正是几年后 ELMo 要回答的问题。而在那个时点，主流解法是先把词向量当固定输入，再用序列模型在它之上补出上下文的缺失——这正是下一节的故事。

## Sequence Modeling: RNN, LSTM, GRU

语言天然是序列，而 RNN 的动机非常直接：按顺序读入每个词，把「已经读到哪里」压进一个隐状态（hidden state），每一步用当前词与上一步隐状态算出新的隐状态和输出。同一组参数在时间上反复复用，因此参数量与句长无关，也能处理任意长度的输入——这两点让 RNN 成为序列建模的默认起点。网络内部结构（激活函数、门、梯度流）的速查见 [Neurons](/docs/CS/AI/DL/Neurons.md)。

### RNN as a Language Model

RNN 最先证明价值的场景之一就是语言建模：每一步预测下一个词，整句的概率等于各步条件概率的连乘，顺序结构天然匹配「从左到右读句子」的过程，因而逐步取代 n-gram 成为语言模型的主力架构。机器翻译、摘要等生成任务的解码器，后来都是在 RNN 语言模型的基础上加条件输入演化而来——序列建模与语言建模从此交织在一起。

### Why Gating Saved the RNN

朴素 RNN 的致命伤是梯度消失与爆炸：误差沿时间反向传播时连乘雅可比矩阵，长距离依赖的梯度指数级衰减，模型实际上只记得最近几步。LSTM（long short-term memory）用门控解决这一点：遗忘门、输入门、输出门共同决定「什么写入记忆、什么保留、什么读出」，细胞状态（cell state）上另有一条近似线性的梯度通路，让梯度能跨很多时间步稳定流动。GRU 是 LSTM 的简化版本，门减到两个，参数更少，在小数据上往往不差。

门控的本质是让网络自己学习「该记多久」，而不是依赖固定的时间窗口。句子开头的主语与句末的谓语之间因此可以建立有效联系，机器翻译与语言建模的指标随之明显跃升。

### Bidirectional Encoding

单向 RNN 只看得到左侧上下文，而词性标注、命名实体识别（named entity recognition, NER）这类任务里，右侧上下文同样重要。双向 RNN（BiRNN）用两个方向的 RNN 分别编码再拼接，等价于每个位置同时获得左右两侧信息。这是「双向编码」思想最早、最朴素的形态，也是后来 BERT 名字里 bidirectional 的历史来源。

### The Limits That Motivated What Followed

RNN 有两个绕不过去的限制。第一是顺序计算：第 t 步依赖第 t-1 步，无法在时间维度并行，训练耗时随句长线性增长——这是后来 Transformer 最直接的动机。第二是信息瓶颈：无论源句多长，全部上下文都要挤进一个固定维度的隐状态，长距依赖只是被缓解、并未真正消除。这两点决定了 2017 年之后循环结构被逐步淘汰。

## TextCNN: Convolution over Sentences

在 RNN 成为主流的同时，另一条思路把卷积网络（CNN）搬到了句子上。TextCNN（Kim, 2014）的做法是：每个词先查词向量，得到「句长 × 词向量维度」的矩阵；用若干不同宽度的卷积核在该矩阵上滑动，每个卷积核负责抓一种 n-gram 级别的局部模式；再做最大池化取每个核最强的响应，最后接全连接层分类。

它不建模严格的顺序结构，但「局部 n-gram 特征 + 池化」的组合意外地有效，而且计算高度并行、训练极快。在句子分类（情感分析、主题分类）上，TextCNN 长期是一个难以超越的强基线——它也提醒人们：并非所有 NLP 任务都需要显式的序列结构。

与 RNN 相比，TextCNN 的代价是感受野受限：每个卷积核只覆盖几个连续的词，句子的整体结构（否定、转折、指代）它看不见。这划出了它的适用边界——在短文本分类上高效且强，在需要建模长距离与强顺序的解析类任务上则不如循环结构。

## Seq2Seq and the Attention Turn

### The Encoder-Decoder Skeleton

2014 年的 Seq2Seq 把「变长输入 → 变长输出」这一类任务（机器翻译、文本摘要、对话）统一进一个骨架：编码器 RNN 把源句读成一个定长向量，解码器 RNN 从该向量出发逐词生成目标句，训练时以最大似然为目标。它第一次让翻译系统摆脱短语切分与对齐表，端到端即可训练。

但骨架里藏着一个瓶颈：源句的全部信息必须挤进编码器最后一个隐状态。句子一长，这个固定向量装不下，翻译质量断崖式下跌。

### Why the Skeleton Generalized

编码器-解码器一旦抽象出「读入一个序列、生成另一个序列」，适用面就远超翻译：摘要、对话、语音识别、语法纠错都能塞进同一个框架，区别只在数据与解码策略。这种任务无关的骨架是后来「预训练 + 微调」能够统一所有任务的结构前提——没有它，每个任务都得拥有一套定制网络。

### Attention: Alignment Becomes Learnable

Bahdanau 等人给出了解法：让解码器每一步都「回看」源句的所有位置，按一组可学习的权重（注意力分布）加权求和，而不是只看一个压缩向量。权重由解码器当前状态与编码器各位置状态的相关性算出，这就是加性注意力（additive attention）。Luong 等人随后提出乘性注意力（multiplicative attention），用点积实现同样的思路，计算更省。

注意力最初是为解决对齐问题而生的。在统计机器翻译时代，源词与目标词的对齐靠 IBM Model 之类的硬规则和对齐表；注意力让对齐变成一个随训练自动学习的软分布。这个让步顺带解决了长距依赖——任意两个位置之间只隔一次加权求和。到 Google 的 GNMT 系统，多层 BiLSTM 编码器 + 注意力解码器 + 残差连接 + 集束搜索被整合为工业级翻译系统，注意力从此成为序列到序列模型的标准件。

值得注意的是：注意力在 2014 年的定位只是 RNN 之上的补丁，没有人预见三年后它会反过来取代 RNN 本身。

## Transformer: Retiring the Recurrence

2017 年的《Attention Is All You Need》做了一个激进的决定：把循环彻底删掉，只留自注意力（self-attention）——每个位置直接与所有位置计算相关性，任意距离一步直达，并且所有位置可以同时计算。这一刀同时解决了 RNN 的两个顽疾：训练可以在时间维度并行（这是它能在 GPU 上规模化的前提），长程依赖不再随距离衰减。

Transformer 的机制细节——多头注意力、位置编码、残差连接与层归一化、前馈网络——在 [Transformer](/docs/CS/AI/Transformer.md) 有完整拆解。这里只需要记住它的历史坐标：它是循环结构被淘汰的判决书，也是预训练范式唯一的底座——没有并行训练，就没有后来在数千亿 token 上训练的可行性。

更深远的影响是架构的「可堆叠」：既然没有时间维度上的依赖，加深、加宽、加大数据都只是工程问题。BERT 与 GPT 分别在它之上保留 encoder 或 decoder，一年之内就接过了接力棒——预训练所需要的规模，只有这种可并行、可堆叠的架构才供得起。

## Pretraining and Fine-tuning: A New Paradigm

### Three Steps of the Idea

预训练思想不是一步到位的，大致走了三步：

1. ELMo（2018）：用双向 LSTM 在大语料上训练语言模型，把各层隐状态加权组合成词表示，下游任务直接使用这套表示——它证明了「无监督预训练得到的表示可以迁移」。
2. ULMFiT（2018）：把「先在通用语料上预训练语言模型、再在目标任务上微调」明确为通用方法论，并提出判别式微调、斜三角学习率等稳定训练的技巧——预训练从此不只是取表示，而是整个模型一起微调。
3. BERT / GPT（2018）：把 Transformer 与预训练结合，下游不再需要为每个任务设计专门结构，微调同一个模型即可刷新多项基准。

从「每个任务训一个模型」到「一个预训练模型微调出所有任务」，是 NLP 工程方式的根本改变：标注数据的角色从「从零训练」降级为「适配」。

### Why Self-supervision Scales

预训练的关键在于把「标注」这一稀缺资源换成「文本」这一过剩资源：语言建模的目标（预测下一个词，或预测被掩掉的词）不需要任何人工标签，可以在任意规模的语料上自动生成训练信号。模型因此先把语言结构乃至部分世界知识压进参数，再以极小的标注代价适配具体任务——这是「预训练 + 微调」能席卷 NLP 的根本原因。

### The Four Families

预训练落地之后，模型按「结构 × 目标」分化成四类，各自的典型用法几乎不重叠：

| 模型 | 结构 | 预训练目标 | 典型用法 |
| :--- | :--- | :--- | :--- |
| BERT | 双向 encoder | 掩码语言模型（MLM）+ 下一句预测（NSP） | 理解类：分类、NER、抽取式问答、检索 |
| GPT 系列 | 单向 decoder | 下一 token 预测（自回归） | 生成类：续写、对话；规模上去后涌现上下文学习（in-context learning） |
| T5 / BART | encoder-decoder | 文本到文本转换 / 去噪重建 | 翻译、摘要等序列到序列任务，统一格式覆盖多任务 |
| Embedding 模型 | 双塔 encoder | 对比学习（正样本与负样本） | 语义检索、聚类，检索增强生成（RAG）的检索端 |

四类没有高下之分，结构与目标决定了能力侧重：双向 encoder 看得到两侧上下文，适合理解类任务，但生成不自然；单向 decoder 天生自回归，适合生成，并且可以扩展成通用接口；encoder-decoder 兼顾两者，代价是结构更重、训练更贵。

Embedding 模型是这套格局里最容易被忽视的一支。它与 BERT 同源（都是 encoder），但目标不同：训练时用对比学习把语义相近的句子对拉近、不相似的推远，推理时把句子独立编码成向量，检索只做向量最近邻。这种「双塔」结构牺牲了 query 与文档的细粒度交互，换来文档向量可以离线预计算、全库检索毫秒级完成，因此成为检索增强生成（RAG）流水线检索端的默认选择——问答侧如何组装这些向量，是 RAG 的主题。

## Closing: Architecture, Paradigm, Scale

把 2013 到 2018 年压缩成三段论：

- 架构创新：RNN → LSTM → Seq2Seq + Attention → Transformer，回答「模型能不能端到端学序列、能不能并行训练」。
- 范式创新：ELMo → ULMFiT → BERT / GPT，回答「如何把无标注语料的规模优势转成通用的下游能力」。
- 规模创新：模型与数据继续放大后，能力不再只来自微调——GPT-3 展示的上下文学习说明，规模越过某个阈值后，同一个模型不更新参数也能完成新任务。

三段并不互相取代：Transformer 是后两段的共同底座，预训练范式在 LLM 时代依然是基本流程，只是「微调」的权重逐渐让位于「提示与上下文学习」。这条主线的下一站，是从预训练走向大模型规模。

## Links

- [NLP](/docs/CS/AI/NLP/NLP.md)
- [DL](/docs/CS/AI/DL/DL.md)
- [LLM](/docs/CS/AI/LLM/LLM.md)
- [RAG](/docs/CS/AI/RAG.md)

## References

- [Convolutional Neural Networks for Sentence Classification-TextCNN](https://arxiv.org/abs/1408.5882)
- [Sequence to Sequence Learning with Neural Networks](https://arxiv.org/abs/1409.3215)
- [Neural Machine Translation by Jointly Learning to Align and Translate-Bahdanau Attention](https://arxiv.org/abs/1409.0473)
- [Effective Approaches to Attention-based Neural Machine Translation-Luong](https://arxiv.org/abs/1508.04025)
- [Attention Is All You Need-Transformer](https://arxiv.org/abs/1706.03762)
- [Deep contextualized word representations-ELMo](https://arxiv.org/abs/1802.05365)
- [BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding](https://arxiv.org/abs/1810.04805)
