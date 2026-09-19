## Introduction

心理测量学（Psychometrics）研究**心理属性的量化与测量**：如何把智力、人格、态度等不可直接观测的**潜变量（latent variable）**转变成可信、可比的分数。它是心理学最接近工程学的分支——一切关于「测出来准不准」的问题都归它管。

它有两个绕不开的追问：**信度**（测测得稳不稳）与**效度**（测的到底是不是它想测的）。任何心理测验的合法性都由这两条支撑，缺一即不可用。

## 测量的两大基石

| 维度 | 问题 | 常见指标 |
| --- | --- | --- |
| 信度（Reliability） | 重复测量是否稳定一致 | 重测信度、内部一致性（Cronbach's α）、评分者一致性 |
| 效度（Validity） | 是否真测到了目标构念 | 内容效度、效标效度、结构效度、区分/聚合效度 |

关键关系：**信度是效度的必要非充分条件**。测不准（低信度）一定测不对，但测得很稳（高信度）也可能一直在测错东西。

## 经典测验理论（CTT）与项目反应理论（IRT）

- **CTT**：把观测分数拆为「真分数 + 误差」，假设误差随机。直观但依赖样本，题目难度与被试能力难以分离。
- **IRT**：用题目参数（难度、区分度、猜测率）与被试能力共同建模，使不同测验之间可比，是现代大型测验（如 GRE）的主流方法。它本质上是把测验视为概率模型，与机器学习的**潜变量模型**同源。

## 智力的测量与争议

- **历史脉络**：Binet 的比奈量表（用于识别需帮助的儿童）→ Stanford-Binet 引入 IQ 概念 → Wechsler 量表（分言语与操作）。
- **IQ 的定义**：最初为「心理年龄 / 实际年龄 × 100」，现在多采用**离差智商**（相对同龄群体的正态位置，均值 100、标准差 15）。
- **因子结构**：Spearman 的 g 因子（一般智力）vs Thurstone 的多基本能力 vs Gardner 的多元智能。g 在统计上稳健，但「智力是否单一」仍有争论。
- **Flynn 效应**：全球 IQ 分数逐代上升，说明智力表现强烈受环境与教育影响，而非纯遗传决定。
- **测量偏差**：测验若偏向特定文化或语言，会产生系统性不公平——这是 IQ 用于社会决策时最敏感的问题。

## 心理测量与其它分支

人格的量化依赖测量工具（大五量表、HEXACO），见 [人格心理学](/docs/Psychology/Personality_Psychology.md)；临床诊断依赖标准化评估量表，见 [临床与异常心理学](/docs/Psychology/Clinical_Psychology.md)；统计推断与因素分析则是测量学的数学底座。

## Links

- [心理学总纲](/docs/Psychology/Psychology.md)
- [人格心理学](/docs/Psychology/Personality_Psychology.md)
- [临床与异常心理学](/docs/Psychology/Clinical_Psychology.md)
- [概率论与数理统计](/docs/Mathematics/Probability_Statistics.md)

## References

1. [Noba Project — Intelligence and IQ Testing](https://nobaproject.com/modules/intelligence)
2. [Intelligence quotient](https://en.wikipedia.org/wiki/Intelligence_quotient)
3. [American Psychological Association — Testing and Assessment](https://www.apa.org/topics/testing-assessment-measurement)
