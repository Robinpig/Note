## Introduction

计算机视觉（Computer Vision，CV）研究**让机器从图像和视频中提取信息、理解世界**，是深度学习最早取得突破、落地最广的领域。它与模型层的分工：[CNN](/docs/CS/AI/CNN.md) 讲"网络怎么设计"，本篇讲"视觉问题有哪些、各自用什么范式求解"。

## Tasks

视觉任务按输出粒度递进：**分类**（图中有什么）→ **检测**（在哪、是什么）→ **分割**（每个像素属于什么）→ **跟踪**（跨帧持续在哪）。除这四项外还有若干平行任务：

| 任务 | 输出 | 典型方法 |
| ------ | ------ | ------ |
| Image Classification 图像分类 | 类别标签 | ResNet、ViT |
| Object Detection 目标检测 | 框 + 类别 | 两阶段：R-CNN / Faster R-CNN；单阶段：YOLO、SSD、RetinaNet |
| Semantic Segmentation 语义分割 | 逐像素类别（不区分实例） | FCN、U-Net、DeepLab |
| Instance / Panoptic Segmentation | 逐像素且区分实例 | Mask R-CNN、Mask2Former |
| Keypoint / Pose 关键点姿态 | 人体/人脸关键点 | OpenPose、MediaPipe |
| OCR | 文本区域 + 文字内容 | 检测 DBNet + 识别 CRNN 两阶段 |
| Depth / Optical Flow | 深度图、逐像素运动 | 立体匹配、RAFT、单目深度估计 |
| Tracking 多目标跟踪 | 帧间同一目标 ID | 检测 + 卡尔曼滤波 + 匈牙利匹配（SORT / DeepSORT） |
| Generation 生成 | 图像/视频 | GAN、Diffusion（Stable Diffusion）、DiT |

### Image Classification

输出整图类别。CNN 的主战场，基准是 ImageNet（1000 类）；常见预训练骨干 ResNet、VGG、EfficientNet，迁移学习用"预训练骨干 + 换头微调"几乎是一切视觉任务的起手式。

### Object Detection

输出多个**边界框 + 类别 + 置信度**。两大流派：

- **两阶段（two-stage）**：先产生候选区域（Region Proposal）再分类回归——R-CNN → Fast R-CNN → **Faster R-CNN**（区域建议网络 RPN 端到端）。精度高、速度慢
- **单阶段（one-stage）**：一次前向直接出框——**YOLO** 系列（把检测当回归问题，实时）、SSD。速度快，小目标精度历来略逊；**RetinaNet** 用 Focal Loss 压住海量易分负样本的损失权重，把单阶段精度拉回两阶段水平

### Segmentation

- **语义分割（Semantic Segmentation）**：逐像素分类，同类不区分个体——FCN 开创全卷积路数，**U-Net**（对称编码器-解码器 + 跳跃连接）是医学影像与通用分割的常青结构
- **实例分割（Instance Segmentation）**：逐像素 + 区分个体——**Mask R-CNN** 在 Faster R-CNN 上加一条掩码分支
- 全景分割（Panoptic）= 语义 + 实例的合并任务
- **SAM**（Segment Anything）把分割重构成**以点/框/文本为 prompt 的零样本基础模型**任务：在超大规模掩码数据上预训练，无需针对新类别训练即可分割任意物体

### Other Tasks

人脸识别（分类 → 度量学习）、OCR（检测 DBNet + 识别 CRNN 两阶段）、姿态估计（OpenPose、MediaPipe）、深度与光流（立体匹配、RAFT、单目深度估计）、图像生成（GAN、扩散模型、DiT）与多模态理解（图文对齐，通往 [LLM](/docs/CS/AI/LLM/LLM.md) 的视觉-语言模型）。

**视频跟踪**（SORT / DeepSORT）是"检测 + 关联"两段式：逐帧检测出框，再用卡尔曼滤波预测运动、匈牙利算法做帧间匹配；DeepSORT 额外引入外观特征（ReID）应对遮挡与交叉。

## Traditional CV

深度学习之前的主流范式，仍在工程中广泛服役：

- **边缘检测**：Canny 算子
- **局部特征**：SIFT/SURF 关键点 + 描述子，特征匹配、图像拼接
- **形状分析**：霍夫变换找直线/圆
- **手工特征 + 分类器**：HOG 特征 + [SVM](/docs/CS/AI/ML/SVM.md) 做行人检测，是深度学习时代的经典基线

传统特征（SIFT/ORB 的尺度不变关键点与描述子）在 SLAM、图像拼接中仍在服役，优势是可解释、无需训练数据。

## Representation Learning

深度学习带来的根本转变是**特征由数据学出来**，而非人手工设计：

- **自监督**：不依赖人工标注，用代理任务学表示——对比学习（SimCLR、MoCo：拉近同图的不同增强、推开异图）、掩码重建（MAE：遮住部分像素再还原）
- **多模态对齐**：CLIP 用 4 亿图文对把图像与文本映射到同一向量空间，支持零样本分类与"文搜图"；BLIP、LLaVA 等视觉语言模型（VLM）进一步支持图文对话

## Metrics

检测与分割的核心指标建立在 **IoU（交并比）**上：

$$
\mathrm{IoU}=\frac{|A\cap B|}{|A\cup B|}
$$

IoU 超过阈值（常取 0.5）才算检出成功。**mAP（mean Average Precision）**：对每个类别算 PR 曲线下的 AP，再对类别取平均——mAP@0.5、mAP@0.5:0.95 是检测论文的标准报告口径。分割的 Dice 系数与 IoU 高度相关。分类指标见 [ML](/docs/CS/AI/ML/ML.md) 的评价指标一节。

## Data and Preprocessing

图像在进入网络前是张量：RGB 三通道、像素值 0–255；常见预处理是 resize / center-crop、归一化到均值 0 方差 1。视频多一个时间维，用 3D 卷积或抽帧后走 2D 网络。图像压缩原理（YCbCr、DCT、量化、Huffman）见 [JPEG](/docs/CS/Algorithms/JPEG.md)。

## Practice

torchvision 提供预训练模型，分类任务几行即可推理：

```python
from torchvision.models import resnet50, ResNet50_Weights

weights = ResNet50_Weights.IMAGENET1K_V2          # 权重与预处理绑定
model = resnet50(weights=weights).eval()
# preds = model(preprocess(img).unsqueeze(0))     # top-1 类别 + 概率
```

检测 / 分割同理：`torchvision.models.detection.fasterrcnn_resnet50_fpn`、`maskrcnn_resnet50_fpn` 开箱即用（文档见下）。

## Engineering Practice

- 数据是主战场：采集与标注规范、类别不平衡（过采样 / Focal Loss）、分辨率与长宽比处理、增强策略（Mosaic、Copy-Paste）
- 部署：模型量化（INT8）、蒸馏、TensorRT / ONNX Runtime 加速；端侧用 MobileNet、YOLO-nano 一类轻量结构
- 视频链路通常是**抽帧 → 检测 → 跟踪（ReID 特征关联）→ 事件聚合**，而不是逐帧独立识别

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
5. [Segment Anything](https://arxiv.org/abs/2304.02643)
6. [Learning Transferable Visual Models From Natural Language Supervision-CLIP](https://arxiv.org/abs/2103.00020)
7. [torchvision 官方文档](https://pytorch.org/vision/stable/index.html)
