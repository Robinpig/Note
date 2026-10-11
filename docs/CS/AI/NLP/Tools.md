## Introduction

[NLP](/docs/CS/AI/NLP/NLP.md) 讲任务版图，[Tokenization](/docs/CS/AI/NLP/Tokenization.md) 讲切分策略，[Representation](/docs/CS/AI/NLP/Representation.md) 讲表示方法。这一篇换成工程视角：手上有一个具体任务时，该用哪件工具。

工具版图按用途大致分四层。教学科研层以 NLTK 为代表，算法齐全、可读性强，适合理解原理与做语料实验；工业流水线层以 spaCy、Stanford CoreNLP 为代表，关注吞吐、部署形态与稳定的 API；中文工具层有 jieba、HanLP 等，处理分词、词性标注、命名实体这些中文特有的问题；模型与数据生态层则由 Hugging Face 系提供模型的取用、训练与分发方式。

四层不是替代关系。一个典型项目可能用 transformers 取模型、用 spaCy 做服务封装、用 sacrebleu 做评测——选型的依据是需求，不是工具的知名度。默认「新工具一定更好」是常见误区：教学场景用 spaCy 会让人看不见算法本身，小规模实验强行上重型框架则是另一种浪费。

## General-Purpose Pipelines

通用流水线的分水岭是「面向学习」还是「面向生产」：同一件事，前者关心算法怎么实现，后者关心每秒能处理多少文档、服务怎么部署、升级会不会破坏下游。下面五个工具正好覆盖这条光谱。

NLTK 是这一领域的教科书级工具。分词、词干提取、词形还原、词性标注、句法分析、语料库接口一应俱全，配套的教程与书籍让它成为 NLP 教学的事实标准。但它的工程性能弱——纯 Python 实现、API 偏学术、没有面向生产的模型管理，处理大语料时速度是明显的瓶颈。它适合课程作业、算法原理演示、语料统计这几类场景，不适合直接进生产链路。

spaCy 是工业侧的默认选择。Cython 实现带来数量级的速度优势，`nlp(text)` 一行完成分词、词性、依存、命名实体与词向量，模型和流水线打包在一起，加载即用。它的设计哲学是「只做够用的事、做到快而稳」，不追求覆盖所有研究型任务。生产环境的英文流水线，默认从它开始。

Stanford CoreNLP 代表另一种路线：Java 生态，语言学分析深厚，句法树与指代消解这类分析都在其中，学术传统长，且至今仍在活跃维护。后端是 Java 或者需要深度句法分析时选它；若只是要 Python 里的快速流水线，它就显得重。

Stanza 是 Stanford 的 Python 多语言神经流水线：覆盖数十种语言，模型由神经方法驱动，与 CoreNLP 同源但接口是现代 Python 风格。多语言处理、需要神经句法分析时用它。

Flair 则定位在序列标注的研究框架：嵌入组合灵活，适合做命名实体识别、词性标注方向的原型与论文实验，而不是追求吞吐的生产服务。

选择逻辑可以压缩成一张对照表：

| 需求 | 首选 |
| :--- | :--- |
| 教学演示、语料库实验 | NLTK |
| 生产英文流水线 | spaCy |
| 多语言神经分析 | Stanza |
| Java 后端集成、深度句法 | CoreNLP |
| 序列标注研究 | Flair |

还要注意组合使用：Stanza 与 CoreNLP 同源，可以在「Java 后端 + Python 前端」的架构里各取所长；spaCy 也支持把外部模型作为组件挂进流水线，不必非此即彼。

## Chinese Tools

中文工具的特殊性在于分词。词与词的边界不像英文那样由空白天然划分，分词粒度会直接影响下游的词性、实体与检索效果，因此这一层工具天然带有更多「策略」成分。

jieba 是使用最广的中文分词库：基于 DAG 与 HMM 的混合切分，支持自定义词典与多种分词模式，接入成本极低，几行代码就能跑起来。但要留意维护状态——0.42.1 版本在 2020 年之后未再发版，新项目用它应评估长期维护风险，尤其是依赖新版本 Python 或需要持续更新词表的场景。

HanLP 2.x 走多任务预训练路线：分词、词性、命名实体、依存等任务共用底层模型，是中文工具中维护最积极的一个。对交付期较长的新项目，它通常是更稳妥的默认项。

pkuseg、LAC、THULAC 出自学术团队：pkuseg 以领域自适应分词见长，LAC 来自百度、把词法分析做成一体，THULAC 出自清华、以词法分析效率著称。它们各有清晰的设计取向，但整体维护节奏已经放缓，选型时要接受「可能不再频繁更新」的现实。

还要区分「分词工具」与「词法分析工具」：前者只切词，后者把分词、词性、实体一路做完。多数新项目直接用后者，省掉自行拼装的成本。

因此中文工具选型有一条务实顺序：先看维护状态，再看精度——一个停止维护的高精度工具，往往不如一个仍在活跃迭代的次优选项。中文 NLP 的任务脉络见 [ChineseNLP](/docs/CS/AI/NLP/ChineseNLP.md)。

## Model and Data Ecosystem

Hugging Face 系改变了工具的边界：它不只是库，更是一种模型分发方式。围绕它有四件工具，各管一段。

transformers 负责模型的定义与取用：`from_pretrained()` 一行加载权重，模型、配置、分词器三者绑定分发，是整个生态的入口。v5 世代自 2025 年底起主打统一与简化，历史包袱在持续清理。

tokenizers 是 Rust 实现的高性能分词库：训练与编码速度远超纯 Python 实现，也是 transformers 内部的分词引擎，需要自己训练词表时直接用它。

datasets 解决数据侧的重复劳动：统一的内存映射存储、流式加载、与训练循环的对接，把「拿一个公开数据集开始训练」的成本降到很低。

sentence-transformers 是句向量与 reranker 的标准库：把句子与段落映射成可比较的向量，是 embedding 检索与语义相似场景的默认入口，与 [Representation](/docs/CS/AI/NLP/Representation.md) 里讨论的句级表示问题直接对应。

这一层的意义在于：模型与数据不再是某个项目的私有资产，而是可复制、可替换的公共组件——换模型时改动的是名字，不是整条链路。

## Vector and Subword Utilities

比流水线更底层的一类工具，负责向量、子词与编码这些基础构件，通常在整条链路里只出现一小段，却是绕不开的依赖。

gensim 是 Word2Vec 与 FastText 的经典实现，API 稳定、文档完整。静态词向量已不是主流，但小规模词向量实验、主题模型与相似度计算仍会用到它。

sentencepiece 是 Google 的通用子词工具：与语言无关，直接从原始文本训练词表，是许多多语言模型分词器的基础，细节见 [Tokenization](/docs/CS/AI/NLP/Tokenization.md)。

tiktoken 是 OpenAI 系模型的 BPE 编码实现：快、依赖少，计算 token 数与成本时常用。注意它只对应特定模型的词表，不要拿它去编码别的模型。

fastText 要带着历史视角看：词向量与文本分类时代的代表工具，官方仓库已在 2024 年归档。把它当作词向量时代的参考实现使用，新项目不应把长期维护押在它身上。

这一层工具的维护状态尤其分化：有的随模型厂商长期维护，有的在大规模预训练兴起后自然退役——引用它们之前先确认仓库是否还活着。

## Evaluation Tools

评估工具的价值在于「让分数可复现、可比较」——同一份输出用不同实现计算 BLEU，可能差出几个点，报告结果时才需要固定口径。

- sacrebleu：提供可复现的 BLEU，把分词与后处理固定下来，报告分数时不会因实现细节产生歧义。
- rouge-score：摘要任务的 ROUGE 系列实现，自动摘要对比的常用口径。
- bert-score：用语义相似度替代字面 n-gram 匹配，缓解同义改写被判低分的问题。
- seqeval：面向序列标注，按实体级别统计 precision、recall 与 F1，是命名实体识别汇报的默认口径。

若要在训练循环里挂指标，Hugging Face 的 evaluate 提供统一接口，把上述指标统一成 `compute()` 调用。各指标的定义、适用边界与陷阱见 [Evaluation](/docs/CS/AI/NLP/Evaluation.md)，这里不重复。

## Version Snapshot

下表是 2026-10 的版本快照，一张表回答「这个工具现在什么状态」：

| 工具 | 生态 | 定位 | 版本（2026-10 快照） |
| :--- | :--- | :--- | :--- |
| NLTK | Python | 教学与语料库经典 | 3.10.3 |
| spaCy | Python | 工业级流水线，生产默认 | 3.8.16（4.0 尚在预览通道） |
| Stanford CoreNLP | Java | 语言学分析深厚，维护活跃 | 4.x |
| Stanza | Python | 斯坦福多语言神经流水线 | 1.15.0 |
| Flair | Python | 序列标注研究框架 | 0.15.1 |
| jieba | Python | 使用最广的中文分词 | 0.42.1（2020 年后未再发版） |
| HanLP | Python / Java | 多任务预训练，中文维护最积极 | 2.1.5 |
| pkuseg | Python | 领域自适应分词 | 0.0.25 |
| LAC | Python | 百度词法分析工具 | 2.1.2 |
| THULAC | Python / C++ | 清华词法分析工具 | 0.2.2 |
| transformers | Python | 模型定义与取用 | 5.19.0（v5 世代） |
| tokenizers | Rust / Python | 高性能分词引擎 | 0.23.3 |
| datasets | Python | 数据加载与流式处理 | 5.1.0 |
| evaluate | Python | 指标统一接口 | 0.4.6 |
| sentence-transformers | Python | 句向量与 reranker 标准库 | 6.1.0 |
| sentencepiece | C++ / Python | 通用子词工具 | 0.2.2 |
| tiktoken | Rust / Python | OpenAI 系 BPE 编码 | 0.14.0 |
| gensim | Python | Word2Vec / FastText 经典实现 | 4.4.0 |
| fastText | C++ | 词向量时代遗产，仓库已归档 | 0.9.3 |
| sacrebleu | Python | 可复现 BLEU | 2.6.0 |
| rouge-score | Python | 摘要评估 | 0.1.2 |
| bert-score | Python | 语义相似评估 | 0.3.13 |
| seqeval | Python | 序列标注实体级 F1 | 1.2.2 |

读表要配合两条经验：版本号长期不动不一定是稳定，也可能是停更——判断维护状态要看仓库提交与 issue 响应，而不是版本号本身；大版本预览（如 spaCy 4.0）意味着 API 还会变化，生产选型应保守一档。

表中中文工具的版本号明显偏旧，这正是维护状态分化最直接的体现——工具层面对中文的投入，长期看取决于是否有活跃的工程团队承接。

## Maintenance Over Popularity

版本与维护状态都会变化，任何快照都只是某一时刻的切片——引入依赖前请以官方网站与仓库的当前状态为准。但工具背后沉淀的判断比版本号耐久：工具是观点的沉淀，NLTK 沉淀学术范式，spaCy 沉淀工程范式，Hugging Face 沉淀模型分发范式。理解这三套范式，换工具时就不会从头开始。

## Links

- [NLP](/docs/CS/AI/NLP/NLP.md)
- [Tokenization](/docs/CS/AI/NLP/Tokenization.md)
- [Representation](/docs/CS/AI/NLP/Representation.md)
- [Evaluation](/docs/CS/AI/NLP/Evaluation.md)
- [ChineseNLP](/docs/CS/AI/NLP/ChineseNLP.md)
- [LLM](/docs/CS/AI/LLM/LLM.md)

## References

- [NLTK](https://www.nltk.org/)
- [spaCy](https://spacy.io/)
- [Stanford CoreNLP](https://github.com/stanfordnlp/CoreNLP)
- [Stanza](https://stanfordnlp.github.io/stanza/)
- [Flair](https://github.com/flairNLP/flair)
- [HanLP](https://hanlp.hankcs.com/)
- [jieba](https://github.com/fxsjy/jieba)
- [Hugging Face Transformers](https://github.com/huggingface/transformers)
- [Hugging Face Tokenizers](https://github.com/huggingface/tokenizers)
- [Sentence Transformers](https://www.sbert.net/)
