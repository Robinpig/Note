## Introduction

计算机视觉（Computer Vision，CV）研究**让机器从图像和视频中提取信息、理解世界**，是深度学习最早取得突破、落地最广的领域。它与模型层的分工：[CNN](/docs/CS/AI/CNN.md) 讲"网络怎么设计"，本篇讲"视觉问题有哪些、各自用什么范式求解"。

四大基础任务按输出粒度递进：**分类**（图中有什么）→ **检测**（在哪、是什么）→ **分割**（每个像素属于什么）→ **跟踪**（跨帧持续在哪）。

## Tasks

### Image Classification 图像分类

输出整图类别。CNN 的主战场，基准是 ImageNet（1000 类）；常见预训练骨干 ResNet、VGG、EfficientNet，迁移学习用"预训练骨干 + 换头微调"几乎是一切视觉任务的起手式。

### Object Detection 目标检测

输出多个**边界框 + 类别 + 置信度**。两大流派：

- **两阶段（two-stage）**：先产生候选区域（Region Proposal）再分类回归——R-CNN → Fast R-CNN → **Faster R-CNN**（区域建议网络 RPN 端到端）。精度高、速度慢
- **单阶段（one-stage）**：一次前向直接出框——**YOLO** 系列（把检测当回归问题，实时）、SSD。速度快，小目标精度历来略逊

### Segmentation 分割

- **语义分割（Semantic Segmentation）**：逐像素分类，同类不区分个体——FCN 开创全卷积路数，**U-Net**（对称编码器-解码器 + 跳跃连接）是医学影像与通用分割的常青结构
- **实例分割（Instance Segmentation）**：逐像素 + 区分个体——**Mask R-CNN** 在 Faster R-CNN 上加一条掩码分支
- 全景分割（Panoptic）= 语义 + 实例的合并任务

### 其它任务

人脸识别（分类 → 度量学习）、OCR、姿态估计、视频目标跟踪、图像生成（GAN、扩散模型）与多模态理解（图文对齐，通往 [LLM](/docs/CS/AI/LLM/LLM.md) 的视觉-语言模型）。

## Traditional CV

深度学习之前的主流范式，仍在工程中广泛服役：

- **边缘检测**：Canny 算子
- **局部特征**：SIFT/SURF 关键点 + 描述子，特征匹配、图像拼接
- **形状分析**：霍夫变换找直线/圆
- **手工特征 + 分类器**：HOG 特征 + [SVM](/docs/CS/AI/ML/SVM.md) 做行人检测，是深度学习时代的经典基线

## Metrics

检测与分割的核心指标建立在 **IoU（交并比）**上：

$$
\mathrm{IoU}=\frac{|A\cap B|}{|A\cup B|}
$$

IoU 超过阈值（常取 0.5）才算检出成功。**mAP（mean Average Precision）**：对每个类别算 PR 曲线下的 AP，再对类别取平均——mAP@0.5、mAP@0.5:0.95 是检测论文的标准报告口径。分割的 Dice 系数与 IoU 高度相关。分类指标见 [ML](/docs/CS/AI/ML/ML.md) 的评价指标一节。

## Practice

torchvision 提供预训练模型，分类任务几行即可推理：

```python
from torchvision.models import resnet50, ResNet50_Weights

weights = ResNet50_Weights.IMAGENET1K_V2          # 权重与预处理绑定
model = resnet50(weights=weights).eval()
# preds = model(preprocess(img).unsqueeze(0))     # top-1 类别 + 概率
```

检测 / 分割同理：`torchvision.models.detection.fasterrcnn_resnet50_fpn`、`maskrcnn_resnet50_fpn` 开箱即用（文档见下）。

## Links

- [AI](/docs/CS/AI/AI.md)
- [CNN](/docs/CS/AI/CNN.md)
- [DL](/docs/CS/AI/DL/DL.md)
- [PyTorch](/docs/CS/AI/PyTorch.md)
- [ML](/docs/CS/AI/ML/ML.md)

## References

1. [Faster R-CNN: Towards Real-Time Object Detection](https://arxiv.org/abs/1506.01497)
2. [You Only Look Once: Unified, Real-Time Object Detection-YOLO](https://pjreddie.com/darknet/yolo/)
3. [U-Net: Convolutional Networks for Biomedical Image Segmentation](https://arxiv.org/abs/1505.04597)
4. [Mask R-CNN](https://arxiv.org/abs/1703.06870)
5. [torchvision 官方文档](https://pytorch.org/vision/stable/index.html)
