## Introduction

问答（question answering, QA）要回答的是信息需求的最后一公里：搜索引擎返回十个「可能相关」的页面，问答系统要直接给出答案本身。评价标准因此完全不同——检索看「答案所在的页面有没有排进前 k」，问答看「答案对不对」。

这决定了问答是信息检索与自然语言处理（NLP）的交汇点：它既需要检索系统的召回能力，也需要语言模型的理解与组织能力。本篇先给出分类框架，再沿「阅读理解、开放域、知识库」三条线展开，最后讨论评估方法与 LLM 时代的形态变化。

问答的难处还在于它同时考验「读」与「知道」两件事：理解问句可以从标注数据里学，世界知识却必须先存在于某个载体——模型参数、文档集合或知识图谱。后文的两条主线，正是模型能力的演进与外部知识的接入方式。

## Taxonomy

问答的定义看来简单——给一个问题、要一个答案——内部的形态差异却极大。至少有两维可以切分：答案以什么形式存在，以及知识从哪里来。

### By Answer Form

| 类型 | 答案形态 | 典型场景 | 代表方法 |
| :--- | :--- | :--- | :--- |
| 抽取式（extractive QA） | 从给定文本中截出的连续 span | 阅读理解、单文档问答 | BERT 式起止位置打分 |
| 生成式（generative QA） | 模型自己组织语言作答 | 对话助手、综述式回答 | 序列到序列生成、LLM |
| 知识库问答（KBQA） | 结构化查询返回的实体、关系或数值 | 企业知识图谱、智能客服 | 语义解析、检索式排序 |

抽取式的监督信号最直接——答案的位置本身就是标注——却被「必须能从原文抄」这一假设框住；生成式最接近用户体验，评估却最难；KBQA 的输出可执行、可验证，代价是依赖已经结构化的知识。

### By Knowledge Scope

| 范围 | 知识来源 | 主要难点 |
| :--- | :--- | :--- |
| 单文档阅读理解 | 题目自带的材料 | 理解问句与定位证据 |
| 多文档 / 开放域 | 从海量语料中先召回证据再作答 | 检索召回率与证据筛选 |
| 多跳（multi-hop） | 答案要靠多条事实串联 | 推理链规划与跨文档聚合 |

这三个范围大致对应三轮技术浪潮：单文档把任务做标准，开放域把检索拉进流水线，多跳把「一次作答」变成「多步调查」。

一句话概括这个领域的地位：问答是信息需求的终极接口，是搜索框的下一站。用户最终想要的从来不是相关文档，而是答案。

## Reading Comprehension Milestones

### SQuAD and the Standard Benchmark

SQuAD 之前，阅读理解数据集普遍规模小、题目手写、答案多为选择题，模型的基本形态是滑动窗口加手工特征，对每个候选窗口做分类。SQuAD（2016）改变了游戏规则：用众包在维基百科段落上生成十万量级的问句，答案固定为原文中的一段 span，让「读一段、答一题」第一次有了大规模、可自动评分的统一基准（EM / F1）。阅读理解从此从多选题变成序列标注式的问题。

模型侧的演化同样清晰：预训练编码器（[Transformer](/docs/CS/AI/Transformer.md) 结构上的 BERT 系）出现后，把问题与段落拼接编码、直接预测答案的起止位置，取代了滑动窗口与特征工程；此后约两年，模型成绩就已超过人工基线。阅读理解从「拼特征」进入「微调」时代。

### SQuAD 2.0 and Unanswerable Questions

SQuAD 的高分建立在一个隐藏假设上：每道题在材料里一定有答案。模型学会了这个捷径——无论问什么，都从段落里截出最像答案的一段文本，从不承认「不知道」。SQuAD 2.0（2018）用五万余条不可回答的问题堵住这条捷径：模型必须先判断材料是否支撑答案，无法回答时输出「no answer」。

这个修补的意义超出基准本身。在真实管线里，检索出来的多数段落本来就不含答案，「学会不回答」比「答对可回答的题」更贴近生产环境的需求。

## Open-Domain Question Answering

开放域问答去掉了「题目自带材料」的前提：问题只有一句话，证据要自己从百万级文档里找。可行的工程形态是两段式——检索器（retriever）先召回若干候选段落，阅读器（reader）再从中抽取或生成答案。

### The Retriever-Reader Pipeline

DrQA（2017）是这套管线的早期样板：TF-IDF 在维基百科上召回段落，神经网络阅读器负责定位答案 span。它确立了一条工程直觉：检索质量决定上限，阅读器只是优化命中之后的体验——证据没被召回，阅读器再强也无从作答。MS MARCO 这类基于真实搜索查询的数据集随后把「问题不保证可回答、答案不保证是原文片段」带进基准，推动检索与阅读两端同时进化。

### Dense Retrieval

检索端从稀疏走向稠密。DPR（2020）用双编码器（dual-encoder）把问题和段落分别编码成向量，检索退化为向量空间中的最近邻搜索；训练依靠批内负例与 BM25 挖掘的难负例，不需要人工标注段落级相关性。这条稠密检索路线与句向量、双塔模型共享同一套思想，细节见 [SemanticMatching](/docs/CS/AI/NLP/SemanticMatching.md)。

### Generative Reading

阅读端则经历了生成化改造。FiD（2020）不再要求答案出现在某一个段落里：它把检索到的每个段落分别编码，再让解码器在拼接后的多段落表示上做 cross-attention，直接生成答案。多段证据在生成阶段才汇总，「每条候选都不完整、合起来才构成答案」的情形由此成为可能。

### Joint Retrieval and Generation

再进一步是 RAG（2020）：检索器与生成器联合训练，检索结果作为潜变量参与生成，端到端优化「取什么证据」与「怎么作答」这两件事。RAG 是开放域问答通往后来的大模型应用的桥梁，本库另有专篇 [RAG](/docs/CS/AI/RAG.md) 展开。

### Multi-hop Questions

两段式管线回答「一次检索就够」的问题很顺，但许多问题需要串联多条事实：「某位物理学家的导师出生在哪个城市」，要先找到导师是谁，再查出生地。多跳问答（multi-hop QA）把单次「检索—阅读」变成一条推理链，每一步的答案成为下一步的查询线索。

工程上常用迭代式检索——检索、阅读、生成下一个问题，循环往复；难点在于错误沿链条传播：第一步找错实体，后面全盘皆错，所以每一步都需要验证或回溯。这条线与 LLM 时代的 agentic search 一脉相承。

## Knowledge Base Question Answering

KBQA 的答案不在自由文本里，而在结构化知识库（知识图谱）中：问题问「姚明的身高」，答案是图谱里某个实体某个属性的值。回答过程因此拆成两步——实体链接（entity linking）把问句里出现的名字映射到图中的节点，关系路径负责找到从实体出发、能回答问题的那些边。

技术路线有两条：语义解析（semantic parsing）把问句翻译成可执行查询（如 SPARQL），交给图数据库执行；信息检索式（IR-based）先定位候选实体，再对候选关系路径排序打分。前者可解释、可复用，后者对噪声与口语化问法更鲁棒。KBQA 可以看作语义解析最务实的一支：schema 边界清晰，评测天然客观——看执行结果即可。

LLM 与工具调用（tool use）改写了这条流水线的形态：把 schema 写进提示，让模型直接输出查询语句，执行后根据报错修正，多轮迭代。「自然语言转结构化查询」由此从训练专用解析器，变成提示工程加执行反馈的问题，延伸阅读见 [LLM](/docs/CS/AI/LLM/LLM.md)。代价是模型可能编造不存在的实体与关系，需要执行器兜底。

## Evaluation

问答的评估指标随答案形态而变，每一类都有自己的系统性偏差。

| 任务形态 | 常用指标 | 主要问题 |
| :--- | :--- | :--- |
| 抽取式 | EM（精确匹配）、F1（词级重叠） | 与人类判断错位：冠词、词形变化、同义改写都会被判错 |
| 开放域管线 | 检索 Recall@k、阅读器精度、端到端准确率 | 必须拆开评：端到端分数低时，不知道是召回不足还是阅读出错 |
| 生成式答案 | ROUGE / BLEU、人工评测、模型裁判 | 答案语义正确但措辞不同，词重叠指标会严重低估 |

### Extractive Metrics

EM / F1 是 SQuAD 的遗产：EM 要求与标注答案完全一致，F1 看词级重叠。它们精确、可复现，代价是只奖励「一字不差」——冠词、词形变化、同义改写都会被判错，与人类判断存在系统性错位。这个错位不影响基准内部排序，却提醒我们：分数涨了不等于用户体验同步变好。

### Evaluating the Pipeline

开放域必须分层评估——检索端看 Recall@k，衡量证据有没有进候选；阅读端只看命中样本上的表现，衡量拿到证据后答得对不对；两者相乘才是端到端上限。只报端到端准确率，低分时无法区分「召回不足」与「阅读器犯错」，也就无从决定该优化哪一端。

### Generative Answers

生成式评估至今没有银弹：措辞不同但语义正确的答案可能拿到很低的 ROUGE，也可能被模型裁判误判，指标选择本身就是方法的一部分。评估方法的系统讨论见 [Evaluation](/docs/CS/AI/NLP/Evaluation.md)。

## Question Answering in the LLM Era

大模型改写了问答的两个前提。其一，材料不必再提前筛好：长上下文模型可以一次装入几十篇文档甚至整本书，把「检索器加阅读器」压缩成「全部塞给模型」。其二，多跳不必一次完成：模型可以在多轮交互里补齐证据。但被压缩掉的不只是组件，还有组件带来的控制力。

### Long Context versus Retrieval

长上下文的张力在三件事上：上下文越长成本越高，权重冻结意味着知识停在训练截止日期，「大海捞针」式的召回率还会随上下文长度明显衰减。因此在时效、成本与可归因性上，检索增强依然不可替代。长上下文与检索并非替代关系，而是按场景分配「把什么材料放进窗口」。

### Agentic Search

agentic search 把检索变成工具调用：模型自己分解问题、决定下一步查什么、读到证据后再决定是否继续，直到能作答。多跳问题从「一条预设的推理链」变成「一轮检索规划」，问答与搜索代理的边界由此消失。

### Attribution and Hallucination

落地的主要风险也随之改变：不再是抽取错 span，而是幻觉（hallucination）与归因（attribution）——答案流畅却无证据支撑，或引用的来源根本不存在。可信的问答系统要把「答案加证据」作为整体交付，让用户能一键核对。

## From Research to Product

回看整条线索：SQuAD 把阅读理解变成标准任务，开放域把检索拉进流水线，KBQA 把答案接到结构化知识上，LLM 又把前面几步揉进同一个模型。问答大概是 NLP 任务里最接近产品的一支——搜索的答案卡片、智能客服、编辑器里的 Copilot，都是它的变体。接口会从搜索框变成对话，内核循环不变：理解问题、找到证据、给出答案。

## Links

- [NLP](/docs/CS/AI/NLP/NLP.md)
- [Transformer](/docs/CS/AI/Transformer.md)
- [SemanticMatching](/docs/CS/AI/NLP/SemanticMatching.md)
- [RAG](/docs/CS/AI/RAG.md)
- [Evaluation](/docs/CS/AI/NLP/Evaluation.md)
- [LLM](/docs/CS/AI/LLM/LLM.md)

## References

- [SQuAD: 100,000+ Questions for Machine Comprehension of Text](https://arxiv.org/abs/1606.05250)
- [Know What You Don't Know: Unanswerable Questions for SQuAD](https://arxiv.org/abs/1806.03822)
- [MS MARCO: A Human Generated MAchine Reading COmprehension Dataset](https://arxiv.org/abs/1611.09268)
- [Reading Wikipedia to Answer Open-Domain Questions-DrQA](https://arxiv.org/abs/1704.00051)
- [Dense Passage Retrieval for Open-Domain Question Answering](https://arxiv.org/abs/2004.04906)
- [Leveraging Passage Retrieval with Generative Models for Open Domain Question Answering-FiD](https://arxiv.org/abs/2007.01282)
- [Retrieval-Augmented Generation for Knowledge-Intensive NLP Tasks](https://arxiv.org/abs/2005.11401)
