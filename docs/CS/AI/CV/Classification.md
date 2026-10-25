## Introduction

图像分类是最经典的视觉任务：给整图输出一个类别标签。它本身早已不是学术前沿，但地位不可替代——**分类骨干是一切视觉任务的起手式**：检测、分割、跟踪都加载在 ImageNet 预训练的分类网络上，分类准不准直接决定下游天花板。

网络结构原理（卷积、残差、感受野、经典架构演进）属于 [CNN](/docs/CS/AI/CNN.md) 的范畴，本篇只讲**任务本身**：基准、协议、训练配方与迁移方法。

## Benchmark and Protocols

**ImageNet-1K** 是分类的事实基准：1000 类、约 128 万训练图。两个报告口径：**top-1**（预测概率最大的类别是否命中）与 **top-5**（前五是否含真值）；top-5 更宽容，早期论文常用，现在主流报告 top-1。

更现代的评测关注两个薄弱面：**分布外泛化**（ImageNetV2、ObjectNet 换分布后掉点明显）与**长尾**（真实数据类别极不均衡，ImageNet 是均匀采样的理想情形）。报告精度时应说明测试集与预处理，否则数字不可比。

## Transfer Learning

「预训练骨干 + 换头微调」几乎覆盖全部落地场景：

1. 加载 ImageNet 预训练权重，去掉原分类头，接上新任务的头
2. **冻结策略**：小数据集冻结全部或大部分骨干只训头；数据量中等解冻后几层；大数据全网络微调
3. **学习率**：骨干用小一个量级的学习率（预训练特征已经很好，暴力大学习率会破坏它），新头用常规学习率；discriminative learning rate 按层分组设置

**线性探测（linear probe）** 是评估表示质量的标准协议：冻结骨干，只训一个线性分类器——它度量的是"特征本身有多可分离"，与微调精度分离，见 [Representation Learning](/docs/CS/AI/CV/Representation_Learning.md)。

## Training Recipe

- **数据增强**：RandomResizedCrop（随机尺度裁剪，scale 常取 0.08–1.0）、水平翻转、颜色抖动、RandAugment / TrivialAugment（自动搜增强策略）；检测任务的增强必须同步变换标注框，见 [Data and Preprocessing](/docs/CS/AI/CV/Data_and_Preprocessing.md)
- **正则**：weight decay、Dropout、标签平滑（label smoothing，把 one-hot 软化成 0.9/0.05，防过度自信）
- **混合增强**：Mixup 按比例线性插值两张图及其标签 $x=\lambda x_i+(1-\lambda)x_j$；CutMix 把一块区域贴过去、标签按面积混合——都被证明提升泛化与鲁棒性
- **优化**：SGD + momentum（0.9）或 AdamW，配 warmup + 余弦退火；大 batch 下 LARS/LAMB 一类分层学习率缩放更稳
- **测试期**：TTA（测试时增强，多次裁剪/翻转取平均）能换 1% 上下精度，代价是推理时间倍增，只适合离线评测

## Long-Tail and Specialized Settings

真实场景类别极不均衡（如工业缺陷、医疗罕见病），直接训练会被头部类主导：

- **重采样**：过采样尾部类 / 欠采样头部类 / class-balanced sampler（按有效样本数设定采样概率）
- **损失层**：focal loss 思想同样适用分类；LDAM 按类别频率施加 margin
- **两阶段**：先训表示再重训分类头

另外两个常见变体：**细粒度分类**（区分鸟的品种、车型年份——需要局部部件注意力，双线性网络或 part-based 模型）、**小样本分类**（每类几张图，度量学习或预训练 + 轻调）。

## Practice

torchvision 的权重与预处理绑定，省去手工对齐均值方差的坑：

```python
from torchvision.models import resnet50, ResNet50_Weights

weights = ResNet50_Weights.IMAGENET1K_V2
model = resnet50(weights=weights).eval()
preprocess = weights.transforms()          # resize/center-crop/归一化一体
# preds = model(preprocess(img).unsqueeze(0))
```

## Links

- [CV](/docs/CS/AI/CV.md)
- [CNN](/docs/CS/AI/CNN.md)
- [Representation Learning](/docs/CS/AI/CV/Representation_Learning.md)
- [Data and Preprocessing](/docs/CS/AI/CV/Data_and_Preprocessing.md)
- [ML](/docs/CS/AI/ML/ML.md)

## References

1. [ImageNet Large Scale Visual Recognition Challenge](https://arxiv.org/abs/1409.0575)
2. [Deep Residual Learning for Image Recognition (ResNet)](https://arxiv.org/abs/1512.03385)
3. [RandAugment: Practical automated data augmentation](https://arxiv.org/abs/1909.13719)
4. [mixup: Beyond Empirical Risk Minimization](https://arxiv.org/abs/1710.09412)
5. [CutMix: Regularization Strategy to Train Strong Classifiers](https://arxiv.org/abs/1905.04899)
6. [Learning Imbalanced Datasets with Label-Distribution-Aware Margin Loss](https://arxiv.org/abs/1906.07413)
7. [torchvision 官方文档](https://pytorch.org/vision/stable/index.html)
