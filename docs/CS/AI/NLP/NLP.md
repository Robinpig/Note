## Introduction

自然语言处理（Natural Language Processing，NLP）研究**让机器理解、处理和生成人类语言**，是人工智能与语言学的交叉领域。任务大体分两族：**自然语言理解（NLU）**——分类、抽取、匹配；**自然语言生成（NLG）**——翻译、摘要、对话。

它的困难根源在于语言本身：**歧义**（「苹果」是水果还是公司）、**上下文依赖**（同一句话换个场景意思全变）、**常识缺口**（「把瓶子倒空再倒满」谁知道先做哪个）。NLP 技术的全部演进史，就是表示语言、消解歧义的方法史，方法范式历经四代：**规则与专家系统（1950s–1980s）→ 统计机器学习（1990s–2010，n-gram、HMM、CRF）→ 神经网络（2013–2017，Word2Vec、RNN/LSTM、Seq2Seq + Attention）→ 预训练大模型（2018 至今，Transformer、BERT、GPT）**。

到今天，多数独立任务已被 LLM 统一为「上下文学习 / 指令」形态，传统方法则在低资源、低延迟、可解释与端侧场景继续发挥价值。本子树按「**文本如何变成模型能算的东西 → 方法如何演进 → 任务各家族怎么解 → 怎么评估、用什么工具**」四条线组织——这一页是入口与导航。

## From Text to Vectors

模型不认识文字，只认识数字。把文本变成可计算形式是一切开端，工序分两步：**先切，再表示**。

切分的问题在中文里最直观：英文靠空格，中文的「南京市长江大桥」却必须由模型决定切成「南京市 / 长江大桥」还是「南京 / 市长 / 江大桥」。[Tokenization](/docs/CS/AI/NLP/Tokenization.md) 梳理从词典规则、统计分词（jieba 这一代）到子词（BPE / WordPiece / Unigram / SentencePiece）的演进，并解释为什么大模型时代分词重新变得关键——它直接决定 token 计费口径、中文的上下文消耗、以及罕见词与多语言的覆盖方式。

表示的问题则贯穿整部 NLP 史。词袋与 TF-IDF 把文本当「词的集合」，Word2Vec / GloVe / FastText 让语义相近的词在向量空间里靠近，ELMo 与 BERT 让同一个词的表示随上下文动态变化，Sentence-BERT、bge、E5 这类模型再把它推到句子与文档级。[Representation](/docs/CS/AI/NLP/Representation.md) 讲的就是这条「符号 → 稠密向量 → 上下文向量 → 句向量」的完整链条——它同时也是语义检索与 [RAG](/docs/CS/AI/RAG.md) 的向量底座。

## The Method Arc

切分与表示之外的第二个问题：**模型怎么用这些表示算出答案**。四代范式各有自己的主力方法。

神经网络之前是四十年的积累，收在 [ClassicalMethods](/docs/CS/AI/NLP/ClassicalMethods.md)：从 ELIZA 式模式匹配与手写语法，到朴素贝叶斯、最大熵、HMM、CRF 构成的统计流水线。别把它当遗迹——CRF 加词典特征至今仍是低资源、强约束场景的可靠基线，理解它也是理解「为什么后来者能赢」的前提。

语言模型是贯穿全程的那条主线，[LanguageModeling](/docs/CS/AI/NLP/LanguageModeling.md) 单独成篇：从数 n-gram 频次的马尔可夫模型与平滑技术，到神经网络化（NNLM、RNN LM），再到预训练目标的分野（GPT 的因果语言模型、BERT 的掩码语言模型、T5 的文本到文本）——「目标怎么设计决定模型擅长什么」，这是本子树通往 [LLM](/docs/CS/AI/LLM/LLM.md) 的接口。

架构的演进收在 [NeuralNLP](/docs/CS/AI/NLP/NeuralNLP.md)：RNN/LSTM 记住词序，[TextCNN](/docs/CS/AI/NLP/NeuralNLP.md) 试过卷句子，Seq2Seq + Attention 打通翻译，之后 Transformer 用自注意力一步统一（机制细节见 [Transformer](/docs/CS/AI/Transformer.md)），而 BERT/GPT 确立的「预训练 + 微调」范式把 NLP 从「每个任务训一个模型」变成「一个模型适配多任务」。

## Task Families

任务按语言层级由浅入深排列，方法则层层叠加：

| 层级 | 代表任务 | 方法演进 |
| ------ | ------ | ------ |
| 词法级 | 分词、词性标注（POS）、命名实体识别（NER） | 词典 + HMM/CRF → BiLSTM-CRF → BERT 序列标注 → LLM 生成式抽取 |
| 句子级 | 文本分类、情感分析 | TF-IDF + 朴素贝叶斯/SVM → TextCNN/BiLSTM → BERT → LLM |
| 结构级 | 成分/依存句法分析 | shift-reduce、CKY/PCFG → 神经转移/图方法 → 预训练解析器 |
| 句对级 | 语义相似度、自然语言推理（NLI）、复述 | 词重叠 → Siamese 双塔 → SBERT/交叉编码器 → LLM |
| 生成级 | 机器翻译、摘要、问答、对话 | Seq2Seq + Attention → Transformer → 大模型统一 |
| 篇章级 | 共指消解、信息抽取、文档理解 | 规则与聚类 → 端到端神经 → 检索增强与长上下文 |

**词法与句子级**是最基础的两族：[SequenceTagging](/docs/CS/AI/NLP/SequenceTagging.md) 是词法任务的统一框架——分词、词性、NER 在建模上是同一件事（给每个 token 打标签），B/M/E/S 与 BIO 标注体系、CRF 解码、实体级评估都在这一篇；[TextClassification](/docs/CS/AI/NLP/TextClassification.md) 则应用面最广，情感分析、垃圾过滤、主题分类共享同一套「特征 + 分类器」骨架。

**结构级**的 [SyntacticParsing](/docs/CS/AI/NLP/SyntacticParsing.md) 讲两种句法观（成分树与依存弧）及其对下游的价值；[InformationExtraction](/docs/CS/AI/NLP/InformationExtraction.md) 把 NER 继续向外延伸出关系抽取与事件抽取，[CoreferenceResolution](/docs/CS/AI/NLP/CoreferenceResolution.md) 解决篇章里的指代链——它们共同的产物（实体、关系、事件）正是知识图谱的原料。

**匹配类**的 [SemanticMatching](/docs/CS/AI/NLP/SemanticMatching.md) 关心「两段文本有多近」：相似度、NLI、复述判断，以及双塔与交叉编码器这对经典的「速度换精度」架构——RAG 的检索端、推荐系统的内容理解都建在它上面。

**生成类**四篇按任务分工：[MachineTranslation](/docs/CS/AI/NLP/MachineTranslation.md)（含 BLEU/COMET 与低资源语言）、[Summarization](/docs/CS/AI/NLP/Summarization.md)（抽取式与生成式、长文档）、[QuestionAnswering](/docs/CS/AI/NLP/QuestionAnswering.md)（抽取式、开放域、检索增强）、[Dialogue](/docs/CS/AI/NLP/Dialogue.md)（任务型系统的四模块与 LLM 时代的统一）。它们的评估方式各异，但底层架构共享同一条 Transformer → 大模型的演进线。

## Evaluation and Engineering

指标不是附属品——BLEU、ROUGE、困惑度、BERTScore、以及 LLM-as-judge 各有各的失真方式，选错指标会把项目带向错误方向。[Evaluation](/docs/CS/AI/NLP/Evaluation.md) 集中讲这块，各任务篇只讲各自的专有指标。

中文是每个中文使用者的默认战场：无空格、字词粒度之争、简繁与字形信息、CLUE 基准与中文模型生态，[ChineseNLP](/docs/CS/AI/NLP/ChineseNLP.md) 单列一篇。

最后是 [Tools](/docs/CS/AI/NLP/Tools.md)：jieba / HanLP / spaCy / NLTK / Stanza / Flair 与 Hugging Face 系的横向对照与版本快照——按「教科书向、工业流水线向、中文向、模型生态向」选型，而不是按知名度。

## Links

- [AI](/docs/CS/AI/AI.md)
- [LLM](/docs/CS/AI/LLM/LLM.md)
- [Transformer](/docs/CS/AI/Transformer.md)
- [RAG](/docs/CS/AI/RAG.md)
- [ML](/docs/CS/AI/ML/ML.md)
- [DL](/docs/CS/AI/DL/DL.md)

## References

1. [Speech and Language Processing (3rd ed. draft)-Jurafsky & Martin](https://web.stanford.edu/~jurafsky/slp3/)
2. [Pre-trained Models for Natural Language Processing: A Survey](https://arxiv.org/abs/2003.08271)
3. [A Survey of Large Language Models](https://arxiv.org/abs/2303.18223)
4. [Efficient Estimation of Word Representations in Vector Space-Word2Vec](https://arxiv.org/abs/1301.3781)
5. [Attention Is All You Need-Transformer](https://arxiv.org/abs/1706.03762)
6. [BERT: Pre-training of Deep Bidirectional Transformers for Language Understanding](https://arxiv.org/abs/1810.04805)
