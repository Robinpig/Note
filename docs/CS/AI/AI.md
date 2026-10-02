## Introduction

AI（人工智能）是研究如何让机器表现出感知、推理、学习与决策能力的学科总称。本目录按方法层级组织：传统机器学习（[ML](/docs/CS/AI/ML/ML.md)）→ 深度学习（[DL](/docs/CS/AI/DL/DL.md)）→ 大语言模型（[LLM](/docs/CS/AI/LLM/LLM.md)），并横向覆盖 [NLP](/docs/CS/AI/NLP/NLP.md)、[CV](/docs/CS/AI/CV.md)、[推荐系统](/docs/CS/RecommenderSystem/RecommenderSystem.md)等应用方向，以及 [PyTorch](/docs/CS/AI/PyTorch.md)、[TensorFlow](/docs/CS/AI/TensorFlow.md)、[Scikit-Learn](/docs/CS/AI/Scikit-Learn.md) 等工具。

现代 AI 的分水岭是 2017 年 NeurIPS 上 Google 论文《Attention Is All You Need》提出的 **Transformer**（见 [Transformer](/docs/CS/AI/Transformer.md)）：它用 self-attention 取代 RNN 的顺序递推，使训练可大规模并行、规模可扩展。基于 Transformer 的 [LLM](/docs/CS/AI/LLM/LLM.md)（BERT/GPT 及后续模型）把 NLP、CV（ViT）、多模态乃至 Agent 统一到同一套预训练范式下。

## 学科地图

```
AI
├── 机器学习 ML（从数据中学规律，不需显式编程）
│   ├── 监督学习：分类 / 回归（[SVM]、逻辑回归、树模型、kNN、朴素贝叶斯）
│   ├── 无监督学习：聚类（k-means、DBSCAN）、降维（PCA、LDA）
│   └── 强化学习：智能体与环境交互最大化累计回报
├── 深度学习 DL（多层神经网络 + 表示学习）
│   ├── CNN → 图像 [CV]
│   ├── RNN/LSTM → 序列（已被 Transformer 取代）
│   ├── [Transformer](/docs/CS/AI/Transformer.md) / 注意力机制 → [LLM]
│   └── GAN / Diffusion → 生成式模型
├── 应用方向
│   ├── [NLP]：分类、NER、翻译、摘要、对话、语义检索
│   ├── [CV]：分类、检测、分割、OCR、视频理解、图像生成
│   ├── 推荐系统、语音识别、搜索排序
│   └── [RAG]：检索增强生成，连接私域知识与 LLM
└── Agent 化：LLM + 工具 + 记忆 + 规划（见 LLM/Agent、MCP、A2A）
    └── 落地形态：[LLM 应用开发平台](/docs/CS/AI/LLM/Platform.md)（Dify、Coze 等，见 LLM/ 目录）
```

## 三范式对比

| 维度 | 传统机器学习 | 深度学习 | 大模型（Foundation Model） |
|------|-------------|----------|------------------------------|
| 特征 | 人工特征工程 | 自动表示学习（端到端） | 预训练知识 + 上下文/指令 |
| 数据规模 | 千～十万样本 | 十万～千万标注 | 万亿 token 无标注语料 |
| 硬件 | CPU 即可 | GPU | GPU/TPU 集群 |
| 适配方式 | 每个任务单独训练 | 预训练 + 微调 | prompt / 少样本 / LoRA 轻量微调 |
| 代表算法 | [SVM](/docs/CS/AI/ML/SVM.md)、随机森林、GBDT | [CNN](/docs/CS/AI/CNN.md)、ResNet | GPT、BERT、扩散模型 |
| 工具 | [Scikit-Learn](/docs/CS/AI/Scikit-Learn.md)、XGBoost | [PyTorch](/docs/CS/AI/PyTorch.md)、[TensorFlow](/docs/CS/AI/TensorFlow.md) | Transformers、vLLM、推理框架 |

## 关键概念脉络

- **偏差-方差权衡**：模型误差 = 偏差（欠拟合）+ 方差（过拟合）+ 不可约噪声；正则化、交叉验证、集成学习都在管理这对矛盾（见 [ML](/docs/CS/AI/ML/ML.md)）。
- **优化**：梯度下降及其变体（SGD+momentum、Adam/AdamW）、学习率调度、损失函数（交叉熵、Hinge、MSE）。
- **泛化**：训练/验证/测试集划分、交叉验证、数据增强、early stopping、正则化（L1/L2、Dropout、权重衰减）。
- **表示学习**：从手工特征到嵌入（embedding），文本/图像/用户最终都表示为可计算相似度的向量——这是语义检索与推荐的共同底座。
- **规模定律（Scaling Law）**：模型能力随参数、数据、算力的幂律提升，是 LLM 路线成立的经验依据；同时带来涌现能力与对齐问题（RLHF）。

## Links

- [ML](/docs/CS/AI/ML/ML.md)
- [DL](/docs/CS/AI/DL/DL.md)
- [Transformer](/docs/CS/AI/Transformer.md)
- [LLM](/docs/CS/AI/LLM/LLM.md)
- [NLP](/docs/CS/AI/NLP/NLP.md)
- [CV](/docs/CS/AI/CV.md)
- [CNN](/docs/CS/AI/CNN.md)
- [SVM](/docs/CS/AI/ML/SVM.md)
- [PyTorch](/docs/CS/AI/PyTorch.md)
- [TensorFlow](/docs/CS/AI/TensorFlow.md)
- [Scikit-Learn](/docs/CS/AI/Scikit-Learn.md)
- [RAG](/docs/CS/AI/RAG.md)

## References

1. [Attention Is All You Need](https://arxiv.org/abs/1706.03762)
