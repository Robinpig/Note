## Introduction

机器翻译（machine translation，MT）是自然语言处理里最古老的任务，也是最纯粹的一个：输入一种语言的句子，输出另一种语言的句子，
中间没有可以回旋的余地——没有分类标签可以蒙，也没有检索结果可以拼，模型必须逐词把整句重写一遍。
正因如此，它成了每一代 NLP 方法的试炼场：规则系统、统计模型、神经网络、大语言模型，无一例外都在这个任务上留下了代表作。

翻译也是「对齐」（alignment）问题的发源地。源语言的一个词未必对应目标语言的一个词，语序、时态、量词、冠词都可能错位，
把两种语言中指同一件事的成分对应起来，是翻译最核心的困难，也是后来注意力机制、跨语言表示等大量工作的源头。
本篇按四代范式的演进讲这个任务，评估与低资源问题各自单独成节。

## From Rules to Statistics

### Rule-Based Machine Translation

第一代是规则式机器翻译（rule-based machine translation，RBMT）：语言学家手工编写语法与转换规则，配上双语词典，逐句做句法分析与结构转换。
它的优点是可解释、可控；缺点同样明显——规则要靠人工穷举，覆盖一种语言的日常表达就已经极其昂贵，换一个领域或换一个语言对几乎要重来一遍。
质量的上限不是算力，而是写规则的人。

### Statistical Machine Translation

第二代把问题从「写规则」变成「估概率」。统计机器翻译（statistical machine translation，SMT）的出发点是：在所有可能的译文中，找概率最大的那句。
这一思路最早由 IBM 的词对齐模型奠定，它把句子级概率分解到词一级，用 EM 算法在平行语料上估计源词与目标词互译的概率。
词对齐是这一代的核心产物——「哪些词彼此对应」第一次成为可以从数据里学出来的东西。

真正把 SMT 推上生产的是短语式翻译（phrase-based translation）：不再以词为单位，而是以频繁共现的短语对为单位做翻译，再由语言模型对候选译文重排序。
这套系统有固定分工：翻译模型负责选词，语言模型负责把词连成通顺的目标语言句子，调序模型负责处理语序差异。
系统表现取决于三个部件各自的质量与它们之间的配合，每改进一点都要分别调参，工程复杂度很高。

## Neural Machine Translation

### End-to-End Learning

神经机器翻译（neural machine translation，NMT）用单个神经网络取代整条流水线：编码器读入源句，解码器逐词生成译文，中间不再有对齐、短语表、调序这些显式模块。
[NeuralNLP](/docs/CS/AI/NLP/NeuralNLP.md) 里的 RNN Seq2Seq 架构是这条路的起点，但最初的版本把全部源句信息压进一个固定长度的向量，句子一长就丢信息。

注意力机制改变了这一点：解码的每一步都回头查看编码器的全部状态，按相关度加权取用。
这个机制的本意就是翻译里的对齐——它让模型自己学出「当前要译的词对应源句的哪几个词」，把过去靠统计对齐表做的事情变成可微、可学习的部分。
注意力随后成为整个深度学习的通用组件，Transformer 更把它作为唯一的结构基础，翻译因此既是注意力的出生地，也是它最早的受益者。

谷歌的 GNMT 系统把这一代技术工程化到生产规模：深层 LSTM、残差连接、注意力、词表切分与量化推理的组合，让 NMT 第一次在真实产品里全面取代 SMT。

### Transformer and Subwords

Transformer 的出现让 NMT 的训练可以充分并行，深层大模型随之可行，主流语言对上的翻译质量全面超过统计时代。
与此同等重要的是一处容易被忽略的工程细节：子词切分。翻译的词表天然面对开放词表问题，人名、新词、形态变化无穷无尽；
切分成子词（如 BPE）之后，未登录词可以拆成已知片段翻译，稀有词共享表示，这是 NMT 质量能稳定超过 SMT 的关键一环，
细节见 [Tokenization](/docs/CS/AI/NLP/Tokenization.md)。

## Evaluation

翻译是 NLP 里评估方法最成熟的任务，指标的演进本身就是一段值得单独讲的线索。

### BLEU

BLEU 用 n-gram 精度衡量译文与参考译文的字面重合，再乘一个长度惩罚，防止模型靠输出短句刷精度。
它计算极快、无需人工，因此成为沿用二十余年的标准指标。
但它的局限同样清楚：只看词面重合，对词序变化与语义改写不敏感——同一句话换个说法、意思完全一致，分数可能很低；
多句一平均，句子级的质量差异也被抹平。它本质上是一个「快而有偏」的代理指标，适合系统间比较，不适合判断单句好坏。

### sacreBLEU

BLEU 还引出一层复现性危机：分词方式、大小写处理、平滑策略的细微差别都会改变分数，论文之间报告的 BLEU 常常不可比。
sacreBLEU 把预处理流程固定下来，并要求随分数一起记录，让同一测试集上的 BLEU 重新有了可比性，此后成为报告 BLEU 的通行做法。

### COMET and chrF

新一代评估走向神经化。COMET 用多语言预训练模型编码源句、译文与参考译文，直接回归一个质量分数，
建模的是译文与参考译文在语义空间里的距离，因此对同义改写友好得多，与人工判断的相关性也明显高于 BLEU。
chrF 从字符级 n-gram 出发，对形态丰富的语言和中文（对分词边界敏感）比词级 BLEU 更稳健。
三者常一起报告：BLEU 提供历史可比性，COMET 提供语义视角，chrF 兜底形态与切分差异。
自动化指标之外的评估方法讨论见 [Evaluation](/docs/CS/AI/NLP/Evaluation.md)。WMT 系列评测赛事是这套指标体系长期的推动者与检验场。

## Low-Resource and Multilingual Translation

主流语言对之间的翻译已经足够好，翻译研究的难点集中在另一端：世界上绝大多数语言既没有平行语料，也没有足够多的单语数据。
这些语言的使用者加起来占全球人口的大多数，翻译在这里不是锦上添花的需求，而是获取信息的前提。

一个几乎零成本的技巧是回译（back-translation）：用已有模型把目标语言单语数据翻回源语言，
构造合成平行句对再反过来训练，相当于把大量单语语料变成训练信号。
更系统的做法是把翻译建模成多语言任务，让一个模型在多种语言间共享参数，
高资源语言的知识因此可以迁移到低资源方向，甚至做到零资源（zero-shot）翻译——两个都没有平行数据的语言之间直接互译。

Meta 的 NLLB 把这一方向推到 200 多种语言，并发布 FLORES-200 评测集，让大量此前没有基准的语言第一次可以被量化比较；
它同时也验证了大规模多语言模型并不会明显牺牲高资源方向的质量。低资源语言是翻译研究里最有人文意义的一块：
它决定的是信息获取机会的分配，而不只是榜单上的数字。

## Translation in the LLM Era

大语言模型改变了翻译的使用方式。对主流语言对，通用模型的译文质量已与专门的 NMT 系统相当甚至更好，
而且不再需要为每个语言对训练专用模型——一个模型靠提示词就能覆盖多方向翻译。
更关键的是控制能力：术语表、语气风格、受众设定、哪些内容保留不译，都可以写进提示里；
文档级上下文也第一次变得自然，指代与术语能在整篇内保持一致。
代价是推理成本更高、延迟更难压制，规模化场景仍然常用专门模型；翻译的工作重心也从「训练一个模型」转向了「写好一段提示」。

翻译是被 [LLM](/docs/CS/AI/LLM/LLM.md) 覆盖得最彻底的任务之一，也因此最能暴露质量差异的细颗粒度：
主流语言对人人都能做，难的是长句、习语、专业领域与低资源方向，这些地方才是区分度所在。
同声传译式的流式翻译是另一个正在被改写的前沿——从「等一句话说完再翻」转向边听边译，
延迟与质量之间的取舍成为核心问题，而这恰恰是通用模型不擅长、仍需专门工程的地方。

## Chinese-Related Challenges

中英方向是本库读者最常遇到的方向，也是困难较多的一对。
双语数据规模远小于欧洲语言之间；语言结构差异大——中文少形态变化而重语序与虚词，英语有冠词、单复数与时态，一对多的对应比比皆是；
中文还需要分词，连续汉字之间没有天然词边界，这一点与空格分隔的英语完全不同（见 [ChineseNLP](/docs/CS/AI/NLP/ChineseNLP.md)）。
这些结构差异在中英翻译里直接表现为两类高频错误：漏译或错译冠词、单复数这类「小词」，以及长句里修饰语归属的调序错误；
它们也是评估时最容易被 BLEU 这类词面指标掩盖的地方。这些特点决定了中英翻译对子词切分、语言模型质量与调序能力都更敏感。

## Conclusion

回看这个任务，四代范式各有代表作：规则系统的语法转换、统计时代的 IBM 词对齐与短语模型、
神经时代的 Seq2Seq 与注意力、以及通用大模型的直接生成。
翻译既是 NLP 最古老的任务，也是方法演进的录像带——新方法问世时最常被拿来的，就是先翻一句句子看看效果。
也正因为对齐、评估、低资源这些翻译里的老问题在每一代都要重新回答一遍，读懂这个任务，就等于读懂了大半个 NLP 的方法史。

## Links

- [NLP](/docs/CS/AI/NLP/NLP.md)
- [Transformer](/docs/CS/AI/Transformer.md)
- [NeuralNLP](/docs/CS/AI/NLP/NeuralNLP.md)
- [Tokenization](/docs/CS/AI/NLP/Tokenization.md)
- [Evaluation](/docs/CS/AI/NLP/Evaluation.md)
- [LLM](/docs/CS/AI/LLM/LLM.md)

## References

- [Sequence to Sequence Learning with Neural Networks](https://arxiv.org/abs/1409.3215)
- [Neural Machine Translation by Jointly Learning to Align and Translate-Bahdanau Attention](https://arxiv.org/abs/1409.0473)
- [Google's Neural Machine Translation System-GNMT](https://arxiv.org/abs/1609.08144)
- [BLEU: a Method for Automatic Evaluation of Machine Translation](https://aclanthology.org/P02-1040/)
- [A Call for Clarity in Reporting BLEU Scores-sacreBLEU](https://arxiv.org/abs/1804.08771)
- [COMET: A Neural Framework for MT Evaluation](https://arxiv.org/abs/2009.09025)
- [No Language Left Behind: Scaling Human-Centered Machine Translation](https://arxiv.org/abs/2207.04672)
