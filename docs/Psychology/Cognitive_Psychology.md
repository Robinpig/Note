## Introduction

认知心理学（Cognitive Psychology）把心智当作**信息加工系统**来研究：人如何注意、编码、存储、提取与操作信息。它诞生于 20 世纪 50—60 年代的**认知革命（cognitive revolution）**，取代行为主义「只研究可观测行为」的立场，转而用反应时（RT）、错误率、眼动与脑成像等**可测量指标**去推断看不见的内部机制。

一句话概括它与相邻分支的关系：行为主义研究「刺激—反应」的外部联结，认知心理学打开中间的黑箱，而 [生理心理学](/docs/Psychology/Biological_Psychology.md) 追问这个黑箱的硬件实现。

## Information-Processing Model of Mind

认知心理学的基本隐喻是**计算机**：输入 → 编码 → 存储 → 加工 → 输出。这一隐喻直接来自信息论与控制论，也解释了它为何与计算机科学高度互通——两者共享「表征（representation）与加工（process）」的框架。

| 加工阶段 | 关注问题 | 关键概念 |
| --- | --- | --- |
| 注意 | 哪些信息能进入加工 | 选择性注意、注意资源 |
| 编码 | 信息以什么形式被表征 | 感觉编码、语义编码 |
| 存储 | 信息如何保持 | 记忆系统、巩固 |
| 提取 | 信息如何被取回 | 线索、提取练习 |
| 执行 | 信息如何被调度决策 | 工作记忆、认知控制 |

## Attention

- **选择性注意**：同一时刻只有少量信息能进入深加工。Broadbent 的**过滤器模型**主张早期筛选，Treisman 的**衰减模型**则允许未被注意的通道以弱化形式通过——这解释了「鸡尾酒会效应」（在嘈杂中仍能听见自己的名字）。
- **注意资源与认知负荷**：Sweller 的认知负荷理论指出工作记忆容量有限，学习与界面设计都应减少无关负荷。这与计算机里的「带宽有限」是同一类约束。
- **注意与 AI 的呼应**：Transformer 的注意力机制借用了「对相关信息选择性加权」的隐喻，但它是可微分的全局加权，与人类串行的注意瓶颈有本质差异，类比时需谨慎。

## Memory

记忆不是一个单一仓库，而是多系统协作：

| 系统 | 容量 / 时长 | 编码特点 |
| --- | --- | --- |
| 感觉记忆 | 极短（毫秒—秒级） | 视觉/听觉原样暂存 |
| 工作记忆 | 约 4±1 个组块 | 容量极有限，加工与暂存合一 |
| 长时记忆 | 近乎无限、可长期保持 | 以语义为主，需多次提取才稳固 |

- **遗忘曲线**（Ebbinghaus）：遗忘先快后慢，间隔重复（spaced repetition）显著优于集中学习。
- **编码特异性**：提取效果取决于提取线索与编码情境的匹配度。
- **提取练习效应**：主动回忆比反复阅读更能巩固记忆——这也是 Anki 类工具的理论依据。

## Thinking, Language, and Decision-Making

- **双加工理论**（dual-process）：System 1 快速、自动、直觉；System 2 缓慢、受控、需要工作记忆。多数认知偏差源于 System 1 的启发式在 System 2 来不及介入时接管判断。
- **语言**：Chomsky 的生成语法主张语言能力是先天的、规则驱动的，直接挑战了行为主义「语言是强化习得」的解释，是认知革命的关键战场。
- **问题解决**：定势（set）与功能固着会阻碍创造性解法。

## Intersection with Computer Science

- **认知架构**：ACT-R、SOAR 试图用统一的计算框架模拟人类认知，是符号主义 AI 的重要遗产。
- **符号 vs 联结**：认知心理学的「表征之争」与 AI 的符号/神经网络之争同构。
- **人机交互**：认知负荷、注意瓶颈、记忆限制是界面设计与交互反馈的底层约束。

## Links

- [心理学总纲](/docs/Psychology/Psychology.md)
- [认知偏差](/docs/Psychology/Cognitive_Bias.md)
- [生理心理学](/docs/Psychology/Biological_Psychology.md)
- [行为主义与学习](/docs/Psychology/Behaviorism.md)

## References

1. [American Psychological Association](https://www.apa.org/)
2. [Noba Project — Cognition and Perception](https://nobaproject.com/modules/cognition-and-perception)
3. [Simply Psychology — Cognitive Psychology](https://www.simplypsychology.org/cognitive-psychology.html)
