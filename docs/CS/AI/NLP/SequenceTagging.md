## Introduction

序列标注（sequence labeling）是自然语言处理中最古老也最持久的一类任务形态：给定一个 token 序列，为每个 token 输出一个标签。分词、词性标注（part-of-speech tagging，POS）、命名实体识别（named entity recognition，NER）、组块分析（chunking）在建模上是同一件事，差别只在标签空间与标注口径。这种统一并不牵强：它们共享同一套语料形态（逐 token 标注）、同一批解码算法（Viterbi 式动态规划贯穿始终）和同一类评估难题（边界与对齐）。

本篇讲这个统一框架本身。把这一族任务放在一起看，方法论的主线才完整：生成式统计模型、判别式模型、神经网络、预训练表示、生成式大模型，几乎每一步都最先在序列标注这类任务上得到验证；NER 作为最重要、也最贴近信息抽取的实例在此展开，关系抽取与事件抽取的组织方式见 [InformationExtraction](/docs/CS/AI/NLP/InformationExtraction.md)。

## Task Definition

输入是长度为 n 的 token 序列，输出是等长的标签序列，标签取自预先定义的标签集。等长对齐是它与另外两类主流任务的核心区别：

| 任务形态 | 输入输出关系 | 例子 |
| :--- | :--- | :--- |
| 文本分类 | 变长到一元 | 情感极性、主题分类 |
| 序列标注 | 等长、逐位置对齐 | 分词、POS、NER |
| Seq2Seq | 变长到变长 | 翻译、摘要 |

对齐到 token 意味着单步决策可以是局部的，但标签之间并不独立：词性的语法合理性取决于相邻词性，BIO 串必须满足结构约束——I-X 不能出现在 O 或 B-Y 之后，BIOES 还要求 B 与 E 成对出现。**能否显式建模标签间依赖，是区分各代方法的一条暗线**：HMM 与 CRF 把它写进模型，纯 BiLSTM 只靠输出层隐式学习，BiLSTM-CRF 又把它请回来。

## Tagging Schemes

标签体系决定标签空间的大小，也决定模型能表达多细的结构。抽掉标签体系，序列标注剩下的只是「逐位置分类」这个空壳。

### BIO and BIOES

边界标签是把「span 抽取」化归为「逐 token 分类」的关键发明：

- **BIO**：B-X 表示实体开始，I-X 表示实体内部，O 表示非实体；
- **BIOES**：在 BIO 之上增加 E-X（实体结束）与 S-X（单 token 实体）。

两者差别在边界表达力：BIO 无法区分「多 token 实体的中间位置」与「紧邻另一个同类实体的开始」，相邻同类实体只能退化为 B-X 接 B-X 才不歧义；BIOES 显式给出结束位置，边界信息更完整，代价是标签空间扩大、低频标签更稀疏，小语料上更容易欠拟合。

| 体系 | 每类标签数 | 边界信息 | 典型使用 |
| :--- | :--- | :--- | :--- |
| BIO | 3 | 只有开始位置 | 通用 NER，CoNLL 风格数据 |
| BIOES | 5 | 开始与结束位置 | 边界敏感的抽取任务 |
| B/M/E/S | 4 | 字级词边界 | 中文分词、未登录词分析 |

### Boundary Semantics

标签体系不是纯实现细节，它直接决定评估口径：实体级评估按 span 起止完全匹配计分，标签体系表达不出的边界，评估就永远无法把它算对。这也是序列标注里「标签设计」与「指标设计」必须一起谈的原因——换标签体系，往往要重新对齐历史结果的比较基准。

### Character-Level Schemes

分词把同一套思路下沉到字：B/M/E/S 分别表示词首、词中、词尾、单字词，与 BIOES 在结构上同构，只是决策单位从词变成字符，非法转移约束也更强。中文任务里位置标签还常与词性标签组合（如 B-NR 表示人名首字），这套组合式标签空间是中文序列标注的显著特色。

## Method Evolution

下面按代际梳理谱系。重点不是各自的公式，而是它们对两个问题的回答：上下文表示从哪里来，标签间依赖怎么处理。

### HMM

隐马尔可夫模型（hidden Markov model）是生成式路线的代表：对联合概率建模，由状态转移概率与发射概率相乘，再用 Viterbi 算法做全局最优解码。标签依赖天然存在于转移矩阵中，代价是观测独立假设——每个 token 只依赖当前标签，可用特征只有当前 token 本身，无法利用前后窗口、词形与词典信息。它的完整推导与解码细节见 [HMM](/docs/CS/AI/ML/HMM.md)。

### CRF

条件随机场（conditional random field）换成判别式路线：直接建模条件概率，全局归一化，允许使用任意重叠的输入特征（前后窗口的词、词形、前后缀、词典命中……）。它为什么能修正局部错误？因为解码是序列级最优：若某位置单独看更像 I-X，但前一个标签是 O，全局归一化后的最优路径会绕开这条非法路径。手工特征时代的序列标注基本等于「设计特征加训 CRF」，特征工程的天花板也就是这一代方法的天花板。

### BiLSTM-CRF

神经网络把特征工程替换成表示学习，但并没有立刻丢掉标签约束。2016 年前后三篇工作几乎同时把结构定型：Huang 等用 BiLSTM 加 CRF 层做通用序列标注；Lample 等面向 NER，在字符级与词级表示之上再叠 CRF；Ma 与 Hovy 用 CNN 抽字符形态特征、BiLSTM 编码上下文、CRF 输出层加序列约束，给出端到端方案。它们的共同分工值得记住：**上下文表示交给网络，标签间约束留给 CRF**——网络负责「看得懂」，CRF 负责「不出格」。此时 CRF 已不是完整的概率模型，而是一个可微的约束解码层。

### Pretrained Encoders

预训练编码器（BERT 一系）把上下文表示推到更强的起点：预训练加一层分类头就能超过精心设计的 BiLSTM-CRF，且对低资源场景更友好。此时 CRF 层变成可选项——表示足够强时，标签约束可以靠微调隐式吸收；但在数据稀少、标签间约束强（如中文分词 B/M/E/S 的合法转移）时，加上 CRF 仍有稳定收益。

### Generative Models and LLMs

大语言模型把标注任务改写为生成任务：提示模型直接输出 JSON 或标注串，用自然语言指令描述标签体系，靠零样本、少样本完成抽取，吸引力在于免训练、标签体系可现场改写。

它的边界也很清楚：长文本上的位置对齐不可靠、输出格式与标注一致性需要校验、同一段文本多次推理可能给出不同标注，而且逐 token 概率无法像 CRF 那样保证合法解码。工程上常见的折中是「LLM 做候选与冷启动，判别式模型做规模化推理」，这类取舍更多是系统与成本问题。

把主线收进一张表：

| 代际 | 建模视角 | 标签依赖 | 主要局限 |
| :--- | :--- | :--- | :--- |
| HMM | 生成式，联合概率 | 转移矩阵显式建模 | 观测独立假设，特征贫弱 |
| CRF | 判别式，条件概率 | 全局归一化显式建模 | 依赖手工特征 |
| BiLSTM-CRF | 神经表示加序列约束 | 由 CRF 层显式保留 | 结构固定，需任务数据 |
| 预训练编码器 | 表示学习加分类头 | 隐式，可按需加 CRF | 领域迁移仍要标注 |
| LLM 生成式抽取 | 条件生成 | 无显式约束 | 对齐与一致性不可靠 |

## Part-of-Speech Tagging

词性标注是序列标注中最「干净」的任务：标签集封闭、歧义主要来自兼类词，局部上下文即可消解大部分歧义。英文事实标准是 Penn Treebank 标签集（NN、VB、JJ、IN 等），中文常用 PKU、CTB 等语料各自的标签集。

词性的价值主要在下游：名词短语边界、动词论元结构、实体识别的前置特征都依赖词性序列。信息抽取流水线里，词性往往是最廉价、最通用的中间表示之一——即使端到端神经模型可以跳过它，可解释性与特征复用场景仍常把它显式保留。

## Named Entity Recognition

NER 把实体的 span 与类型一起标出，通用领域通常分四类：人名（PER）、地名（LOC）、机构（ORG）、其他专名（MISC）。它是序列标注最直接的应用，也是信息抽取的第一级台阶。

实体识别之后才有实体链接、关系抽取与知识库构建，因此它的标注质量会沿流水线向下游放大，这也解释了为什么 NER 长期是序列标注里投入最集中的任务。

### Nested and Overlapping Entities

BIO 体系一个位置只能有一个标签，「北京大学」中的「北京」（地名）与「北京大学」（机构）无法同时表达。解法要么分层解码（先粗后细），要么转向 span 级建模（指针网络、span 分类）——序列标注的标签空间在此碰到结构性上限，嵌套场景往往是任务从「标注」转向「抽取」的转折点。

### Domain NER

生物医学（基因、蛋白、药物）、电商（品牌、型号、属性）等领域实体形态完全不同，标注规范与词典都难以复用；专业文本里实体密度高、缩写多，通用模型直接迁移效果差。应对手段是小样本学习、词典与规则回补、远程监督自动标注，再辅以人工校验。

### Chinese NER and Segmentation

中文 NER 与分词边界纠缠：实体边界依赖词的切分，而分词本身有歧义，误差会级联。两条主要思路——先分词再标注，或直接在字符上标注（字符级表示避免分词错误，却丢掉了词的信息）。Lattice LSTM 是融合路线的代表：在字符序列上保留所有词典词的路径，用门控机制把词级信息动态汇入字符表示，让模型同时看到字与词的证据。分词本身的方法论见 [Tokenization](/docs/CS/AI/NLP/Tokenization.md)，中文任务的整体图景见 [ChineseNLP](/docs/CS/AI/NLP/ChineseNLP.md)。

## Data and Evaluation

常用基准：CoNLL-2003（英文与德文新闻，PER/LOC/ORG/MISC 四类）与 OntoNotes（多体裁、多实体类型，规模更大），中文常用 MSRA 与 OntoNotes 中文部分。它们既是模型对比的共同分母，也固化了四类实体的标注传统。

评估上最重要的一条：**序列标注必须按实体级 F1 计分，而非 token 级准确率**。原因是 O 标签占绝对多数，把全部 token 判成 O 也能拿到九成以上的准确率；且 token 级计分只看单点标签，B/I 错位会让部分正确的实体也被计入。实体级 F1 要求 span 起止与类型完全匹配才命中，工具链通常用 seqeval 这类库计算。

实践里还要注意两点：跨域评估比同域测试更接近真实价值，新闻上训练的模型直接用于医学文本往往大幅掉点；报告时应同时给出 micro 与 macro 视角，类别不平衡时 macro 才暴露长尾实体的真实表现。指标本身的取舍与置信区间问题属于 [Evaluation](/docs/CS/AI/NLP/Evaluation.md) 的范畴。

## Closing Observations

序列标注之所以值得单独成篇，是因为它是「经典统计、神经、预训练、生成式」全谱系最完整的观察窗口：每一代方法都在同一批任务、同一批基准上被检验，演进脉络比任何单点技术都清楚。它留下两笔同样持久的遗产：标签体系（BIO/BIOES/BMES）至今是所有 span 抽取任务的公共词汇表，实体级评估口径至今约束着模型能宣称什么。后续的信息抽取、槽位填充、事件论元标注，基本都在这个框子里继续做加法。

## Links

- [NLP](/docs/CS/AI/NLP/NLP.md)
- [Tokenization](/docs/CS/AI/NLP/Tokenization.md)
- [InformationExtraction](/docs/CS/AI/NLP/InformationExtraction.md)
- [Evaluation](/docs/CS/AI/NLP/Evaluation.md)
- [ChineseNLP](/docs/CS/AI/NLP/ChineseNLP.md)
- [LLM](/docs/CS/AI/LLM/LLM.md)

## References

- [Bidirectional LSTM-CRF Models for Sequence Tagging-Huang 2015](https://arxiv.org/abs/1508.01991)
- [Neural Architectures for Named Entity Recognition-Lample 2016](https://arxiv.org/abs/1603.01360)
- [End-to-end Sequence Labeling via Bi-directional LSTM-CNNs-CRF-Ma & Hovy](https://arxiv.org/abs/1603.01354)
- [A Survey on Deep Learning for Named Entity Recognition](https://arxiv.org/abs/1812.09449)
- [Chinese NER Using Lattice LSTM](https://arxiv.org/abs/1805.02023)
- [Neural Chinese Word Segmentation with Dictionary Knowledge](https://arxiv.org/abs/1807.05849)
