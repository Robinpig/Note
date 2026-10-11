## Introduction

模型不认识文字，只认识数字。无论下游任务是分类、检索还是生成，第一步都是把文本变成一组固定维度的向量——这就是文本表示（text representation）。它与 [Tokenization](/docs/CS/AI/NLP/Tokenization.md) 是前后衔接的两件事：分词决定「把文本切成什么单位」，表示决定「每个单位变成什么数」，两者拼起来才是模型真正看到的输入。

这条演化线有四站：稀疏的符号表示（one-hot、词袋、n-gram）→ TF-IDF 加权 → 稠密静态词向量（Word2Vec / GloVe / FastText）→ 上下文相关表示（ELMo / BERT）→ 句子与文档嵌入。每一代都在回答上一代留下的一个具体难题：相似度算不出来、语序丢了、一词多义没法表达、整句语义无处安放。

也值得先记住一个定位：表示层是 NLP 栈里迁移学习的接口——预训练模型真正沉淀下来、可以被反复复用的资产，正是它学到的表示；下游换任务、换数据，换的都是表示之上的那一小截。

本篇沿着这条线讲清每一步为什么发生。

## Sparse Representations

### One-Hot and the Curse of Dimensionality

最朴素的表示是 one-hot：词表里第 i 个词就是长度为词表大小的向量，第 i 位是 1，其余全 0。它带来两个立刻致命的问题。

第一是**相似度消失**。任意两个不同词的向量内积为 0——它们正交，余弦相似度恒为 0，模型完全无法从表示本身看出「猫」和「狗」比「猫」和「利率」更接近。每个词都是一座孤岛，语言里最重要的「词与词的距离」在表示里根本不存在。

第二是**维度灾难**（curse of dimensionality）。中文词表动辄十万量级，一篇短文只点亮其中几十个坐标，其余全零。输入极度稀疏，线性模型既慢又容易过拟合，而要让统计规律覆盖如此大的空间，需要的数据量不可承受。

### Bag of Words and the Loss of Order

把一篇文档里所有词的 one-hot 加起来（按出现次数加权），就是词袋（bag of words）：整段文本压缩成与词表等长的计数向量。代价是丢掉全部语序与位置信息——「我打他」和「他打我」的表示完全相同，否定、修饰、主宾关系都不再可辨。

词袋也并非一无是处：在主题分类、垃圾邮件过滤这类「词出现与否比顺序更重要」的任务上，它便宜、稳定、意外地好用。但只要语义落在组合结构上，它就会立刻失效——这划出了后续所有方法要跨过的那道线。

### N-Gram Features

保住局部语序的直接做法是 n-gram：把连续 n 个词（或字）当成一个整体特征，bigram 记住「不 + 好」，trigram 记住更长的搭配。代价是特征空间随 n 急剧膨胀——50 万词表的 bigram 理论上有约 2500 亿种组合；且绝大多数组合在语料里从未出现。

于是 n-gram 撞上数据稀疏：模型对没见过的搭配毫无泛化能力，见过的组合也只覆盖真实语言极小的角落。它是「局部语序」与「可承受的维度」之间的一次折中，在统计机器翻译和语音识别里支撑了很多年，直到神经网络表示接棒。

## Term Weighting with TF-IDF

词袋的计数还有一层隐含问题：出现多的词未必重要。「的」「是」「在」这类停用词（stop words）几乎每篇文档都高频出现，却几乎不携带区分信息；而一个罕见、只出现在少数文档里的词，恰恰是辨别主题的关键。

TF-IDF 用一个乘积同时表达这两件事：

```tex
\mathrm{tfidf}(t,d) = \mathrm{tf}(t,d) \times \log \frac{N}{\mathrm{df}(t)}
```

其中 $\mathrm{tf}(t,d)$ 是词 t 在文档 d 中的频率，衡量局部重要性；$\mathrm{df}(t)$ 是包含 t 的文档数，$N/\mathrm{df}(t)$ 取对数就是逆文档频率（inverse document frequency），衡量全局稀有性。

它的巧妙之处在于：停用词的 df 极高，IDF 趋近于 0，权重被自动压低——**停用词表不需要人工维护，统计量自己完成了这件事**。区分能力靠语料统计自动分配，而不是靠先验清单，这是它比「手写停用词表」更经久的原因。

实践中，[Scikit-Learn](/docs/CS/AI/Scikit-Learn.md) 的 `TfidfVectorizer` 一行就能得到加权矩阵，配合 [FeatureEngineering](/docs/CS/AI/ML/FeatureEngineering.md) 里的管道（pipeline）思路，是文本分类最稳固的经典基线；即便在深度学习时代，TF-IDF 加线性模型仍常被用作快速对照。

## Static Word Embeddings

静态词向量（static word embeddings）的共同承诺是：每个词映射一个固定向量，与它出现的句子无关；向量稠密（典型 100～300 维）、相似度可计算、可以当特征喂给任何模型。2013 年之后的一批方法用不同路径兑现了这个承诺，差异主要在「怎么算出来」。

### Word2Vec: CBOW and Skip-Gram

Word2Vec 换掉了整条思路：不再用「词表有多大就多少维」的符号表示，而是通过「用上下文预测词」的训练任务，让共现频繁的词在空间里彼此靠近。最著名的一句结论是 king − man + woman ≈ queen——表示第一次带上了「可做算术的语义」，性别、单复数这类关系变成空间中的固定方向。

两套架构互为镜像：CBOW 用上下文词预测中心词，训练快、对高频词更友好；Skip-gram 反过来用中心词预测上下文，对低频词与生僻用法更健壮，代价是计算量更大。两者共享同一个直觉：上下文共现是语义的窗口。

### Negative Sampling

直接对全词表做 softmax 意味着每一步都要在几十万类上归一化，训练几乎不可承受。负采样（negative sampling）把任务改成二分类：正样本是语料里真实出现的上下文词，负样本按噪声分布随机抽 5～20 个词，只判断「这对词是否真的共现」。

每步计算量从 O(V) 降到 O(k)，且被证明等价于对一种简化目标的学习——这是 Word2Vec 能在大语料上实用化的关键工程选择，也让「巨大的词表软归一化」在后来的表示学习里反复以新形式出现。

### GloVe

Word2Vec 是「预测式」的，通过局部窗口的预测任务间接学到向量；GloVe 换了一条路：先统计整个语料的全局共现矩阵（co-occurrence matrix），再对它做加权最小二乘分解，让词向量的内积去拟合共现次数的对数。

两条路径殊途同归：只做局部预测和只做全局统计，得到的向量空间结构高度相似。但 GloVe 的显式目标让「用共现统计刻画语义」这一直觉表达得更直接，也让表示学习与矩阵分解这两条传统线接上了头。

### Design Knobs: Window Size and Dimension

静态向量还有几个必须知道的调节项。窗口大小直接决定学到的「相似」是哪种相似：窗口小（2～3），邻居偏句法——学到的近邻是可以在句子里替换的词；窗口大（5～10），邻居偏主题——近邻变成同一话题里的词。维度则要与语料规模匹配：语料越大能支撑的维度越高，小语料配高维度只会放大噪声。

这些旋钮提醒一件事：静态向量里的「语义」，本质是共现统计的投影；调参调的不是模型，而是你想让统计量回答哪个问题。

### FastText

以上方法都给每个词学**一个**向量；FastText 把词拆成字符级子词（subword）n-gram，词向量是这些子词向量的和。好处有二：形态学信息进入表示（前缀、词根、时态共享统计强度），未登录词（OOV, out-of-vocabulary）可以用子词拼出近似表示，显著缓解低频词与拼写变体问题。中文这类无空格语言、德语这类复合词语言受益尤其明显。

这些经典模型在 gensim 里都有现成实现，几行代码即可复现——它们的更大价值是作为基线，标定后续方法到底涨了多少。

### The Ceiling of Static Vectors

不论是预测式还是分解式，静态向量都止步于同一个事实：每个词只有一个固定向量，一词多义（polysemy）无法表达。bank 在「河岸」与「银行」里共享同一向量，模型只能取折中；「苹果」在水果与公司语境中同样分享一个表示。无论把窗口调大还是调小，都是在两个缺点之间换一个位置——查表式表示的这一根本限制，把研究推向下一阶段。

## Contextual Representations

如果表示不是查出来的，而是**读着这句话算出来的**，多义问题就有了出路：让同一个词的向量随上下文变化。这就是上下文相关表示（contextual representations），它分两步兑现。

### ELMo

ELMo（embeddings from language models）用双向 LSTM 语言模型在句子上现场计算每个词的表示——拼接该位置的前向与后向隐状态，再把不同层的表示加权求和。同一个词在不同句子里得到不同向量，token 的表示第一次成为上下文的函数，而不是固定查询结果。它的用法仍是「把表示当特征喂给下游任务」，但特征本身已经带上了句子级信息。

### BERT

BERT 把双向 LSTM 换成深层 [Transformer](/docs/CS/AI/Transformer.md) 编码器，用掩码语言模型（masked language model）大规模预训练，每个位置的输出向量都融合了全句信息。至此「词的表示从查表变成按上下文算出来」正式完成。

影响不止于表示本身：预训练加微调（pretrain-then-finetune）成为 NLP 的标准流程——表示从「喂给浅层模型的特征」升级为「端到端微调的起点」，NLP 的工程范式随之整体改写。

### What the Layers Encode

有研究逐层探测（probing）BERT 的内部表示（BERT Rediscovers the Classical NLP Pipeline），发现低层最像词法与形态特征，中层最像句法（依存、成分结构），高层最像语义与指代。

这一层级分工与经典 NLP 流水线（词法 → 句法 → 语义）惊人地对应，也解释了一个工程现象：取哪一层的输出做下游任务会显著影响效果，选层（layer selection）自此成为惯例。它同时说明 BERT 的每一层都留着可用的表示，只是各自的「抽象层级」不同。

## Sentence and Document Embeddings

很多任务要的其实是整句甚至整篇的向量：检索要比较 query 与文档，聚类要比较样本，推荐要比较内容画像。词级表示之后，句级表示（sentence embeddings）成为新的工程焦点。

### The Limits of Averaging

最省事的方案是取平均（或 TF-IDF 加权平均）：把词向量加起来就得到句子向量。简单平均在短句上尚可，长文本上会稀释信息——关键短语被大量功能词摊平。

更根本的问题是各向异性（anisotropy）：直接拿 BERT 的词向量求平均，得到的句子向量分布在一个狭窄锥形区域里，任意两个句子的余弦相似度都偏高，相似度失去了区分度。表示空间的这种「塌缩」说明：会算词向量，不等于会算句子向量。

### SBERT and SimCSE

SBERT（Sentence-BERT）把孪生网络（siamese network）搬进 BERT：两个共享权重的编码器分别编码句子，用对比目标把语义相近的拉近、无关的推远；推理时句子只需一次前向，比较退化成向量运算。它把「句子对打分」的重计算变成了检索友好的编码加距离。

SimCSE 进一步把对比学习简化到极致——同一句话过两次编码器，只靠 dropout 制造正样本，用「自己」当正例，效果却超过复杂的数据增强，说明关键不在增强的花样，而在对比目标本身，以及半监督的 NLI 数据提供的负例质量。

### Open-Weight Models

工程上更常见的做法是直接用开放权重的句向量模型：bge、E5 等在弱监督对比预训练下覆盖中英文多语言，开箱即用。它们的角色是向量底座：[RAG](/docs/CS/AI/RAG.md) 的召回端把文档切块后编码成向量，检索时用同一模型编码 query，两边落在同一语义空间里才谈得上相似度。

推荐系统的内容理解（[ContentProfile](/docs/CS/RecommenderSystem/ContentProfile.md)）同样靠这些模型把标题、正文、标签映射成可比较的向量——文本侧的内容画像与 RAG 的召回索引，本质是同一类底座的不同消费方式。

选型惯例是参考 MTEB 榜单，但模型迭代很快，排名请以最新评测为准；上线前还要在自己的语料分布上复测，不要只信公开分数。

## Summary

表示质量决定任务上限：表示阶段丢了语序、丢了义项、丢了领域语义，后面的模型再大也补不回来。这也是为什么预训练范式每次换代（Word2Vec → ELMo → BERT）本质都是表示方式的换代，而不是简单的模型变大。

与分词一篇的分工也在此收束：分词划定单位与信息边界，表示决定单位如何数值化，二者共同构成整个 NLP 栈的地基，之后的一切（注意力、检索、生成）都建筑在它上面。

## Links

- [NLP](/docs/CS/AI/NLP/NLP.md)
- [Tokenization](/docs/CS/AI/NLP/Tokenization.md)
- [Transformer](/docs/CS/AI/Transformer.md)
- [RAG](/docs/CS/AI/RAG.md)
- [LLM](/docs/CS/AI/LLM/LLM.md)

## References

- [Efficient Estimation of Word Representations in Vector Space-Word2Vec](https://arxiv.org/abs/1301.3781)
- [GloVe: Global Vectors for Word Representation](https://aclanthology.org/D14-1162/)
- [Enriching Word Vectors with Subword Information-fastText](https://arxiv.org/abs/1607.04606)
- [Deep contextualized word representations-ELMo](https://arxiv.org/abs/1802.05365)
- [BERT Rediscovers the Classical NLP Pipeline](https://arxiv.org/abs/1905.05950)
- [Sentence-BERT: Sentence Embeddings using Siamese BERT-Networks](https://arxiv.org/abs/1908.10084)
- [C-Pack: Packed Resources For General Chinese Embeddings-bge](https://arxiv.org/abs/2309.07597)
