## Introduction

深度学习给视觉带来的根本转变是**特征由数据学出来，而非人手工设计**。分类网络浅层学边缘、中层学纹理部件、深层学物体——层次是自动涌现的，换数据集只需重训末端。这一节把「学什么表示、怎么学、怎么评」讲清楚，它是理解预训练—微调范式和视觉基础模型的前提。

表示学习横跨所有任务：分类用、检测的分割骨干也用、多模态模型更以它为底座，见 [Classification](/docs/CS/AI/CV/Classification.md)、[Segmentation](/docs/CS/AI/CV/Segmentation.md)。

## What Makes a Good Representation

判断标准不是训练集精度，而是**可迁移性**：换任务、换数据分布后特征还好不好用（评测协议见文末表格，相关口径见 [Metrics](/docs/CS/AI/CV/Metrics.md)）。两个操作化指标：

- **线性可分性**：冻结特征后只训线性头，精度掉多少
- **域泛化**：换分布（不同相机、不同国家街景）后精度保持度

这解释了为什么"训练损失更低"的模型不一定表示更好——过拟合到训练集的特征反而难迁移。

## Self-Supervised Learning

不用人工标签，用数据自身构造监督信号（代理任务）：

### Contrastive Learning

对比学习把同一图像的不同增强视图当正样本对、其他图像当负样本，拉近正对、推开负对。核心损失是 InfoNCE：

$$
\mathcal{L}=-\log\frac{\exp(\mathrm{sim}(z_i,z_j)/\tau)}{\sum_k\exp(\mathrm{sim}(z_i,z_k)/\tau)}
$$

$\tau$ 是温度系数，分母里负样本数量直接决定效果：

| 方法 | 年份 | 负样本来源 |
| ------ | ------ | ------ |
| InstDisc | 2018 | 个体判别，每张图当一类 |
| MoCo | 2019/2020 | 动量编码器 + 队列，负样本规模与 batch 解耦 |
| SimCLR | 2020 | 大 batch + 投影头，工程简洁 |
| BYOL | 2020 | 不用负样本，在线/目标网络自举 |
| SwAV | 2020 | 在线聚类分配替代对比 |

MoCo 的洞察是**负样本越多表示越好，但显存装不下**——用动量更新的编码器维护一个大队列，让小 batch 也拿到海量负样本。

### Masked Reconstruction

把图切 patch 遮住一部分，让模型重建：

- **MAE**（2021）：遮 75%，只把剩余 patch 送编码器（算力省 4 倍），轻量解码器重建像素——非对称设计是高效关键
- **BEiT**：用离散视觉 tokenizer 当重建目标，把图像当"外语"学

掩码重建天然适合 ViT（没有卷积的局部先验，必须靠补全学结构），是视觉 Transformer 的预训练标配。

### Distillation Without Labels

**DINO**（2021）发现自蒸馏（学生网络匹配教师网络的输出分布）学出的注意力图**自动呈现出物体分割轮廓**——无任何分割标签。DINOv2（2023）靠数据工程（ curated 数据集 + 训练配方）把冻结特征推到通用水平；DINOv3（2025-08）进一步规模化。RT-DETRv4 直接把 DINOv3 当教师蒸馏检测器，见 [Detection](/docs/CS/AI/CV/Detection.md)。

## Multimodal Alignment

图文对齐把视觉表示接进语言空间：

- **CLIP**（2021）：4 亿图文对，图像编码器与文本编码器对比学习，落入同一向量空间——零样本分类（用类名造句当提示）与文搜图直接可用，成为后续大量模型的组件
- **MetaCLIP**（2023）：Meta 公开了可复现的数据 curation 配方，证明数据质量比规模更关键
- **BLIP**（2022）：capfilt（生成 Caption 再过滤）提升图文对质量
- **VLM**：LLaVA（2023）用视觉指令微调把图像特征接进 LLM，开启图文对话；后续把 SAM 3 一类视觉基础模型当工具挂进多模态系统做视觉接地（visual grounding）

SAM 3（2025-11）代表了另一条路：不把视觉压成一个向量，而是保留空间结构，用提示词直接产出掩码——视觉基础模型与多模态系统开始互补而非竞争。

## Evaluation Protocols

| 协议 | 做法 | 测什么 |
| ------ | ------ | ------ |
| 线性探测 | 冻结骨干 + 线性头 | 特征可分性 |
| 少样本微调 | 每类 1/10 张图微调 | 数据效率 |
| 全量微调 | 解冻全部 | 上限 |
| 零样本 | 直接文本提示分类 | 语义泛化 |
| 检索 | 文搜图/图搜图 Recall@K | 表示质量 |

## Links

- [CV](/docs/CS/AI/CV/CV.md)
- [Classification](/docs/CS/AI/CV/Classification.md)
- [Traditional CV](/docs/CS/AI/CV/Traditional_CV.md)
- [Detection](/docs/CS/AI/CV/Detection.md)
- [Transformer](/docs/CS/AI/Transformer.md)

## References

1. [Momentum Contrast for Unsupervised Visual Representation Learning (MoCo)](https://arxiv.org/abs/1911.05722)
2. [A Simple Framework for Contrastive Learning of Visual Representations (SimCLR)](https://arxiv.org/abs/2002.05709)
3. [Bootstrap Your Own Latent (BYOL)](https://arxiv.org/abs/2006.07733)
4. [Masked Autoencoders Are Scalable Vision Learners (MAE)](https://arxiv.org/abs/1911.05725)
5. [Emerging Properties in Self-Supervised Vision Transformers (DINO)](https://arxiv.org/abs/2104.14294)
6. [DINOv2: Learning Robust Visual Features without Supervision](https://arxiv.org/abs/2304.07193)
7. [DINOv3](https://arxiv.org/abs/2508.10104)
8. [Learning Transferable Visual Models From Natural Language Supervision (CLIP)](https://arxiv.org/abs/2103.00020)
9. [BLIP: Bootstrapping Language-Image Pre-training](https://arxiv.org/abs/2111.06377)
10. [Visual Instruction Tuning (LLaVA)](https://arxiv.org/abs/2304.01385)
