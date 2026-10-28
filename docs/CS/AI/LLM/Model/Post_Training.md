## Introduction

预训练交出来的是一个 **base model**：会续写文本，不认识"指令"是什么，你问它问题它可能继续提问。[模型总览](/docs/CS/AI/LLM/Model/Overview.md) 里那些能对话、能调工具、有拒答边界的模型，都是 base model 再经过**后训练（post-training）**的产物。本页讲这一层：SFT、偏好优化、PEFT 与蒸馏分别解决什么问题、代价是什么，以及一条典型流水线长什么样。

后训练的全部动机可以压成一句：**预训练买到的是知识与语言能力，后训练买到的是"按你要的格式、守你定的边界做事"**。两者训练的损失函数形式相同（都是下一词预测或它的变体），不同的是数据形状与评判标准——前者是海量无标注文本，后者是人工构造的"什么算好"。

## Supervised Fine-Tuning

SFT 是在精选的 (指令, 回答)  pair 上继续做下一词预测。它教的不是知识，而是**交互格式**：什么时候该直接回答、什么时候该先澄清、工具调用长什么样、代码块怎么围、长什么样算"答完了"。一个只会续写的 base model 经过几万条高质量样本就能学会这套格式。

三个反复被验证的结论：

- **数据质量远比数量重要。** LIMA 用约一千条精标样本就把 base model 调成了可用的助手，作者的结论是"对齐教的是格式，知识预训练已经给够了"。堆十万条噪声样本的收益远低于一万条干净的。
- **要防灾难性遗忘。** 全量 SFT 容易把预训练学到的东西冲掉，通行做法是在 SFT 数据里混入一定比例的通用语料，并监控通用基准不掉点。
- **prompt 部分要 mask 掉损失。** 只在回答 token 上计算损失，否则模型会把"出好问题"也当成优化目标。

## Preference Optimization: From RLHF to DPO

SFT 教得会格式，但"哪个回答更好"这种偏好没法用下一词预测直接表达——你手里只有"回答 A 比 B 好"的成对比较。这一层的经典解法是 RLHF，现代主流是它的闭式简化版 DPO，以及为推理模型让位的 GRPO。

### RLHF: The Original Pipeline

InstructGPT 确立的三段式：SFT 之后，用人工标注的成对比较训练一个**奖励模型**（reward model），再用 PPO 策略梯度把策略模型推到奖励模型高分的方向，同时用 KL 惩罚拴住它别离 SFT 模型太远。

它的账单是：同时驻留四个模型（策略、参考、奖励、价值/critic），PPO 训练不稳定、超参敏感，采样-训练循环让工程复杂度陡增。效果确实好，但除大厂之外很少有人独立复现这套流程。

### DPO: The Closed Form

DPO 的关键观察是：**在 KL 约束下最优的策略，可以用奖励模型和参考模型解析地写出来**。把这个最优策略代回去，PPO 那个最大化问题就塌缩成一个简单的分类损失——直接对" chosen 回答的对数概率高于 rejected 回答"做梯度下降即可。于是不需要奖励模型、不需要在线采样、不需要 PPO，一个标准的监督训练循环就能跑。参考模型仍然需要（KL 项），但可以冻结、可以用 LoRA 只训策略。

这一条把偏好优化的门槛从"一个强化学习团队"降到"一个训练脚本"，此后绝大多数开源模型的对齐阶段都是 DPO 或其变体。

### The Family: What Each Variant Removes

| 方法 | 去掉的东西 | 数据形状 | 备注 |
| :--- | :--- | :--- | :--- |
| DPO | 奖励模型 + PPO + 在线采样 | 成对偏好 | 仍要参考模型 |
| ORPO | 参考模型（把 SFT 与偏好合成一步） | 成对偏好 | 一个阶段同时学格式与偏好 |
| SimPO | 参考模型 + 长度归一化问题 | 成对偏好 | 奖励用平均对数概率，免参考 |
| KTO | 成对数据（只要单条好坏信号） | 二值好坏 | 基于前景理论，标注更廉价 |
| GRPO | 价值网络 / critic | 一组采样 + 可验证奖励 | 组内归一化优势，推理 RL 的事实标准 |

GRPO 值得单独说：它对同一 prompt 采一组（通常 8~64 个）回答，用**组内平均奖励**作为基线计算优势，因此不需要单独训练价值网络；奖励可以来自奖励模型，也可以来自**可验证信号**（数学答案对错、单测是否通过、编译是否成功）。这条"用规则当裁判"的路线是 2024 年后推理能力提升的主力，数学与代码方向的进步大多源于此。

## PEFT: LoRA and QLoRA

全量微调一个百亿参数模型的显存账单（参数 + 梯度 + Adam 二阶动量，fp16 约 16 字节/参数）让多数团队望而却步，参数高效微调（PEFT）因此成为默认答案，其中 **LoRA** 是绝对主流。

做法是冻结原权重 $W$，只训练它的低秩分解 $W + BA$（$A \in \mathbb{R}^{r \times d}$，$B \in \mathbb{R}^{d \times r}$，秩 $r$ 通常取 8~64），推理时把 $BA$ 加回 $W$——**合并后零推理开销**。可训练参数降到千分之几，优化器状态同比例缩小，且不同任务的 LoRA 可以热插拔。

几个实践要点：

- **目标模块**：至少覆盖注意力的 q/k/v/o 投影；再带上 MLP 两个投影通常更好；嵌入层与 LM head 一般不动。
- **QLoRA** 在 LoRA 之上再把 base 权重压到 4-bit（NF4 + 双重量化），让 65B 模型的微调落进单张 48GB 显卡。显存受限时的标准解，训练稳定性略差于 16-bit base。
- **LoRA 不是万能的**：注入全新知识、大幅改变输出分布的任务上，它与全量微调仍有差距；它擅长的是"在既有能力上贴一层行为"。

## Distillation

蒸馏换的是钱，不是能力上限：用一个大模型的输出来训练一个小模型，让小模型在特定任务上逼近大模型。Hinton 的原始版本让小模型拟合大模型的**软标签**（带温度的类分布），软标签里的类间相似度（"这张 2 有几分像 7"）是 one-hot 标签丢失的暗知识；现代实践更常简化为"用强模型生成 SFT 数据，再喂给小模型"。

它是"便宜复刻"的标准路线：选型、领域适配、降本都成立。两条边界要记住：**蒸馏不创造新能力**（上限由教师决定，多教师集成可以略高），以及**许可证**——很多模型的输出条款限制用其输出来训练竞品，商业使用前必须读条款。

## Alignment Beyond Human Labels: RLAIF and Constitutional AI

RLHF 的隐性成本是让人类标注员大量接触有害内容。Constitutional AI 的思路是把人撤出这个回路：模型按一部成文的原则（"宪法"）自我批评与修正，AI 反馈（RLAIF）替代人工比较标注。它没有消除对齐问题，但把"规模化的有害内容暴露"换成了"一部可审计的原则清单"——原则本身的制定仍然是人做的决定。

## A Typical Recipe

把上面各段拼成 2026 年的常见流水线：

| 阶段 | 数据 | 产出 | 计算画像 |
| :--- | :--- | :--- | :--- |
| 继续预训 / 中训 | 领域无标注语料 | 注入领域知识 | 最贵，多卡长跑 |
| SFT | 精标 (指令, 回答)，常掺通用数据 | 学会格式与对话 | 中等，LoRA 可覆盖 |
| 偏好优化 | 成对比较（DPO 系）或 可验证奖励（GRPO） | 对齐偏好 / 推理能力 | 中到重 |
| 蒸馏 | 强模型生成的数据 | 小模型 / 降本 | 便宜 |

不是每家都走全链：小团队常见做法是"开源 base + SFT + DPO"；推理模型的增量几乎全在 GRPO + 可验证奖励；蒸馏多发生在模型选型与降本阶段，而不是研究阶段。

## Failure Modes Worth Knowing

- **奖励黑客（reward hacking）**：策略找到了奖励模型的高分漏洞而非真的变好。GRPO 用可验证奖励正是为了绕开"奖励模型可被钻"这个结构性弱点。
- **冗长偏见**：人工标注员倾向于给长回答打高分，DPO 之后模型会变啰嗦；数据侧要控制长度配比。
- **对齐税**：对齐后的模型在某些通用基准上掉点，是格式约束与分布偏移的代价，靠混通用数据缓解。
- **评估污染**：后训练数据里混进测试集题目，榜单分数虚高——这也是为什么自建评估集越来越被强调。

## Links

- [Model Overview：模型总览与选型](/docs/CS/AI/LLM/Model/Overview.md)
- [Inference：本地部署与推理引擎](/docs/CS/AI/LLM/Model/Inference.md)
- [LLM：模型总纲](/docs/CS/AI/LLM/LLM.md)
- [Transformer：架构根因](/docs/CS/AI/Transformer.md)

## References

1. [Training language models to follow instructions with human feedback（InstructGPT / RLHF）](https://arxiv.org/abs/2203.02155)
2. [Direct Preference Optimization: Your Language Model is Secretly a Reward Model（DPO）](https://arxiv.org/abs/2305.18290)
3. [DeepSeekMath: Pushing the Limits of Mathematical Reasoning in Open Language Models（GRPO）](https://arxiv.org/abs/2402.03300)
4. [LoRA: Low-Rank Adaptation of Large Language Models](https://arxiv.org/abs/2106.09685)
5. [QLoRA: Efficient Finetuning of Quantized LLMs](https://arxiv.org/abs/2305.14314)
6. [LIMA: Less Is More for Alignment](https://arxiv.org/abs/2305.11206)
7. [KTO: Model Alignment as Prospect Theoretic Optimization](https://arxiv.org/abs/2402.01306)
8. [ORPO: Monolithic Preference Optimization without Reference Model](https://arxiv.org/abs/2403.07691)
9. [SimPO: Simple Preference Optimization with a Reference-Free Reward](https://arxiv.org/abs/2405.14734)
10. [Constitutional AI: Harmlessness from AI Feedback](https://arxiv.org/abs/2212.08073)
11. [Distilling the Knowledge in a Neural Network](https://arxiv.org/abs/1503.02531)
