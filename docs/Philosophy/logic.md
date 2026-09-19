## Introduction

逻辑学研究**有效推理的形式**：什么样的论证，在其前提为真时**必然**保证结论为真？它不关心前提事实上是否为真，只关心前提与结论之间的**保真结构**。因此逻辑既是哲学的分支，也是数学与计算机科学的公共地基——布尔代数、类型论、程序验证、SAT 求解都建立在它之上。

它是 [认识论](/docs/Philosophy/Epistemology.md) 的姊妹：认识论问「我们如何获得证成」，逻辑问「证成如何传递」。

## 演绎与归纳

| 类型 | 特征 | 结论的地位 |
| --- | --- | --- |
| 演绎（deduction） | 前提真则结论必然真 | 结论被前提**蕴含**，不超出前提范围 |
| 归纳（induction） | 前提使结论**可能**为真 | 结论超出前提，有增益但不保真 |

## 三大思维规律

传统逻辑（源自亚里士多德，经中世纪与莱布尼茨整理）把最基本的推理规则概括为三条：

- The law of identity: P is P.（同一律）
- The law of noncontradiction: P is not non-P.（矛盾律）
- The law of the excluded middle: Either P or non-P.（排中律）

三者构成经典逻辑的骨架。注意**直觉主义逻辑**拒绝排中律——在构造性数学中，「P 或非 P」只有在能构造出其中一个的证明时才成立。

## 三段论（Syllogism）

亚里士多德的三段论是最早的形式化推理系统：由**大前提、小前提**推出**结论**，如「所有人都会死；苏格拉底是人；故苏格拉底会死」。三段论的「格」与「式」是形式化研究的最早范式，其精神一直延续到弗雷格的谓词逻辑。

## 现代逻辑的分支

| 系统 | 关注 |
| --- | --- |
| 命题逻辑 | 联结词（且、或、非、蕴含）的组合规律 |
| 一阶谓词逻辑 | 引入量词（∀、∃）与谓词，可表达数学命题 |
| 模态逻辑 | 必然与可能，语义基于可能世界 |
| 直觉主义逻辑 | 构造性证明，拒绝排中律 |
| 非经典逻辑 | 多值、模糊、相关逻辑等，处理经典框架失效的场景 |

一阶逻辑的**不可判定性**（Church–Turing）：不存在算法能判定任意一阶公式是否普遍有效——这把逻辑与可计算性理论绑在一起，见 [集合论与数理逻辑](/docs/Mathematics/Set_Theory_Logic.md)。

## 逻辑与计算

- **布尔代数 → 数字电路**：与、或、非直接对应门电路，图灵机与可计算性的形式化与逻辑同源。
- **类型 ↔ 命题（Curry–Howard 对应）**：程序即证明，类型即命题，这使程序验证成为逻辑的应用。
- **形式化方法**：模型检验、定理证明器被用于验证硬件协议与安全关键软件。

## Links

- [哲学总纲](/docs/Philosophy/Philosophy.md)
- [认识论](/docs/Philosophy/Epistemology.md)
- [语言哲学](/docs/Philosophy/Philosophy_of_Language.md)
- [集合论与数理逻辑](/docs/Mathematics/Set_Theory_Logic.md)

## References

1. [Stanford Encyclopedia of Philosophy — Classical Logic](https://plato.stanford.edu/entries/logic-classical/)
2. [Induction vs. Deduction](https://www.msubillings.edu/asc/resources/writing/pdf/Induction%20vs%20Deduction.pdf)
