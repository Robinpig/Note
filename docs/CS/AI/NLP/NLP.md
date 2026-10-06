## Introduction

自然语言处理（Natural Language Processing，NLP）研究**让机器理解、处理和生成人类语言**，是人工智能与语言学的交叉领域。任务大体分两族：**自然语言理解（NLU）**——分类、抽取、匹配；**自然语言生成（NLG）**——翻译、摘要、对话。

它的困难根源在于语言本身：**歧义**（"苹果"是水果还是公司）、**上下文依赖**（同一句话换个场景意思全变）、**常识缺口**（"把瓶子倒空再倒满"谁知道先做哪个）。NLP 技术的全部演进史，就是表示语言、消解歧义的方法史。

方法范式历经四代：**规则/专家系统（1950s–1980s）→ 统计机器学习（1990s–2010，n-gram、HMM、CRF）→ 神经网络（2013–2017，Word2Vec、RNN/LSTM、Seq2Seq+Attention）→ 预训练大模型（2018 至今，Transformer、BERT、GPT）**。当前多数独立任务已被 LLM 统一为"上下文学习 / 指令"形态，传统方法仍在低资源、低延迟、可解释的边缘场景有价值。

## Tasks

| 任务类型 | 代表任务 | 输入 → 输出 |
| ------ | ------ | ------ |
| 文本分类 | 情感分析、垃圾邮件过滤 | 文本 → 类别 |
| 序列标注 | 中文分词、词性标注、命名实体识别（NER） | 词序列 → 标签序列 |
| 语义匹配 | 文本相似度、信息检索、复述判断 | 两段文本 → 相似度 |
| 机器翻译 | 端到端翻译 | 源语言 → 目标语言 |
| 摘要与生成 | 自动摘要、对话、写作 | 文本/提示 → 新文本 |
| 问答 | 阅读理解、开放域问答 | 问题 + 文档 → 答案 |

其中序列标注是理解经典方法的好入口——[HMM](/docs/CS/AI/ML/HMM.md) 的 Viterbi 解码正是中文分词 B/M/E/S 标注的经典解法。

按语言层级由浅入深看，各层任务的方法演进大体是"神经 → 预训练 → LLM"的层层叠加：

| 层级 | 任务 | 方法演进 |
| ------ | ------ | ------ |
| 分词/形态 | 中文分词、POS、NER | 词典 + HMM/CRF → BiLSTM-CRF → BERT 序列标注 |
| 句子级 | 文本分类、情感分析 | TF-IDF + SVM/LR → TextCNN/BiLSTM → BERT → LLM |
| 结构级 | 句法/依存分析、关系抽取 | shift-reduce parser、图算法 |
| 句对级 | 语义相似度、NLI、复述 | Siamese 网络、交叉编码器 |
| 生成级 | 机器翻译、摘要、对话 | Seq2Seq + attention → Transformer → GPT/T5 |
| 篇章级 | 共指消解、文档理解、RAG | 文档图、检索增强（见 [RAG](/docs/CS/AI/RAG.md)） |

## Text Representation

怎么把一段文字变成模型能算的东西？这条主线经历了四代：

### 词袋与 One-Hot

把文档看成词的集合，不考虑顺序：每个词一维，出现记 1 或计次数。简单、稀疏、丢语序（"我打他"与"他打我"相同）。

### TF-IDF

词袋的加权改良：**词频高且文档间稀有**的词更重要：

$$
\mathrm{tfidf}(t,d)=\mathrm{tf}(t,d)\times\log\frac{N}{\mathrm{df}(t)}
$$

其中 $N$ 是文档总数、$\mathrm{df}(t)$ 是包含词 t 的文档数。停用词（"的、了"）被自动压低。sklearn 的 `TfidfVectorizer` 一行可用（见 [Scikit-Learn](/docs/CS/AI/Scikit-Learn.md)），文本特征工程的更多套路见 [FeatureEngineering](/docs/CS/AI/ML/FeatureEngineering.md)。

### 词向量 Word Embedding

One-Hot 向量互相正交、表达不了"猫和狗相似"。Word2Vec（2013）在**稠密低维空间**里让语义相近的词彼此靠近——"king − man + woman ≈ queen" 是它的标志性结果。两套架构：CBOW（上下文预测中心词）与 Skip-gram（中心词预测上下文），配合负采样训练。同代还有基于共现矩阵分解的 GloVe、引入子词的 FastText。

静态词向量的局限：**一词多义无法处理**——"苹果"在任何句子里都是同一个向量。

### 上下文相关表示

ELMo、BERT 开始，每个词的表示随上下文动态生成，歧义消解从"规则和统计"变成"从海量文本中学"。这就是预训练语言模型的起点，通往 [LLM](/docs/CS/AI/LLM/LLM.md)。

### 子词切分 Subword

开放词表问题用**子词切分**解决：BPE（字节对编码，从字符出发逐步合并最高频相邻对）、WordPiece（BERT 用，合并能使似然增益最大的对）、SentencePiece（T5 用，直接在原始文本上操作、不依赖预分词）。罕见词被拆成片段，词表压到 3–10 万，兼顾未登录词覆盖与序列长度。

## Classical Pipeline

神经网络之前，NLP 任务的典型流水线：

1. **分词（Tokenization）**：英文按空格+规则；**中文没有天然空格**，需要专门模型（jieba、HMM/CRF 分词器）——是中文 NLP 的第一道工序
2. **清洗与归一化**：去停用词、词干化（stemming）/ 词形还原（lemmatization）
3. **特征化**：TF-IDF、n-gram
4. **模型**：朴素贝叶斯、[SVM](/docs/CS/AI/ML/SVM.md)、HMM、CRF

**n-gram 语言模型**用马尔可夫假设建模"下一个词"：$P(w_t\mid w_1\dots w_{t-1})\approx P(w_t\mid w_{t-n+1}\dots w_{t-1})$——与 [HMM](/docs/CS/AI/ML/HMM.md) 同源的"只看最近历史"思想，加上平滑技术支撑了早期输入法、拼音转汉字与机器翻译。

## Neural NLP

神经网络把表示学习接了进来：

- **RNN / LSTM / GRU**：按词序逐个读入、隐状态记忆历史；LSTM 用门控缓解长序列的梯度消失（见 [Neurons](/docs/CS/AI/DL/Neurons.md) 的结构速查表）
- **Seq2Seq + Attention**：编码器压缩源句、解码器生成目标句，机器翻译的主流框架；Attention 让解码器"回看"源句所有位置，突破单一瓶颈向量
- **Transformer**：《Attention Is All You Need》（2017）用**自注意力**彻底取代循环结构——全并行、长程依赖一步直达，成为 NLP 的统一底座（详见 [Transformer](/docs/CS/AI/Transformer.md)）
- **预训练范式**：BERT（双向、掩码语言模型 MLM，擅长理解类任务）与 GPT（单向自回归，擅长生成）两派分立，微调小数据即可迁移——再往后就是规模驱动的 [LLM](/docs/CS/AI/LLM/LLM.md) 时代

预训练 + 下游微调（pretrain–fine-tune）把 NLP 从"每个任务单独训一个模型"变成"一个模型适配多任务"，代表模型按用法分四类：

| 模型 | 结构 | 预训练目标 | 典型用法 |
| ------ | ------ | ------ | ------ |
| BERT（2018） | 双向 encoder | MLM 掩码预测 + NSP | 理解类：分类 / NER / 检索 rerank |
| GPT 系列 | 单向 decoder | 下一个 token 预测 | 生成类；规模到一定程度后涌现 ICL / CoT |
| T5 / BART | encoder-decoder | 文本到文本 / 去噪 | 翻译、摘要等 seq2seq 任务 |
| Embedding 模型（Sentence-BERT、E5、bge） | 双塔 encoder | 对比学习 | 句/文档编码为向量做语义检索，是 [RAG](/docs/CS/AI/RAG.md) 的检索端 |

## LLM 时代的任务形态

- 分类 / NER 等判别任务：少样本提示或指令微调，必要时用约束解码 / function calling 输出结构化 JSON
- 知识密集任务：[RAG](/docs/CS/AI/RAG.md)（检索增强生成）= 向量检索相关段落 + LLM 基于段落生成，缓解幻觉与知识时效问题
- 长文档：分块（chunking）、滑窗、重排序（reranker）、上下文压缩
- 评估从准确率 / F1 扩展到 LLM-as-judge、忠实度、引用归因
- Agent 化：模型通过工具调用与环境交互完成多步任务，见 [Agent](/docs/CS/AI/LLM/Agent/Theory/Agent.md)

## 评估与工程常识

- 分类指标：accuracy 之外，不平衡场景看 precision/recall/F1、宏平均/微平均；检索看 MRR、nDCG、Recall@k
- BLEU（n-gram 重叠）评翻译、ROUGE（召回向）评摘要——都是表层指标，与人的判断相关性有限，正逐步被 LLM 评审替代
- token 计费 / 上下文限制以 tokenizer 切分后的 token 数计，中文通常一字接近 1–2 token

## Tools

| 工具 | 语言/生态 | 定位 |
| ------ | ------ | ------ |
| [jieba](https://pypi.org/project/jieba/) | Python | 中文分词事实标准，支持自定义词典 |
| [spaCy](https://spacy.io/) | Python | 工业级流水线：分词、NER、词性，速度快 |
| [NLTK](https://www.nltk.org/) | Python | 教学与科研经典，语料库丰富 |
| Hugging Face Transformers | Python | 预训练模型生态：BERT/GPT 等模型即取即用 |
| sklearn `CountVectorizer` / `TfidfVectorizer` | Python | 文本特征化基线（见 [Scikit-Learn](/docs/CS/AI/Scikit-Learn.md)） |

## Links

- [AI](/docs/CS/AI/AI.md)
- [LLM](/docs/CS/AI/LLM/LLM.md)
- [ML](/docs/CS/AI/ML/ML.md)
- [HMM](/docs/CS/AI/ML/HMM.md)
- [FeatureEngineering](/docs/CS/AI/ML/FeatureEngineering.md)

## References

1. [Speech and Language Processing (3rd ed. draft)-Jurafsky & Martin](https://web.stanford.edu/~jurafsky/slp3/)
2. [Efficient Estimation of Word Representations in Vector Space-Word2Vec](https://arxiv.org/abs/1301.3781)
3. [Attention Is All You Need-Transformer](https://arxiv.org/abs/1706.03762)
4. [BERT: Pre-training of Deep Bidirectional Transformers](https://arxiv.org/abs/1810.04805)
5. [jieba-PyPI](https://pypi.org/project/jieba/)
6. [spaCy 官网](https://spacy.io/)
