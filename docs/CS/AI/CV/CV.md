## Introduction

计算机视觉（Computer Vision，CV）研究**让机器从图像和视频中提取信息、理解世界**，是深度学习最早取得突破、落地最广的领域。安防、工业质检、自动驾驶、医疗影像、内容生产——凡是人用眼睛做的判断，都在这条技术线的射程内。

本页是 CV 子树的枢纽。与相邻笔记的分工：[CNN](/docs/CS/AI/CNN.md) 讲"网络怎么设计"（卷积、残差、感受野），本页讲"视觉问题有哪些、各自用什么范式求解"，九个分册把每个问题展开到可动手的程度。

## Task Landscape

视觉任务按输出粒度递进：**分类**（图中有什么）→ **检测**（在哪、是什么）→ **分割**（每个像素属于什么）→ **跟踪**（跨帧持续在哪）。输出结构从固定长度标签，变成数量不定的框集合，再变成与输入同尺寸的掩码图，最后加上帧间身份——每一步都引入新机制，也淘汰旧假设。

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

平行任务里，人脸识别走「分类 → 度量学习」路线，姿态估计是分类思想在关键点上的复用，OCR 是检测 + 序列识别的组合，深度与光流撑起三维与运动理解，生成式模型（GAN → 扩散模型 → DiT）则把 CV 从理解推向合成。

## Chapter Map

分册按「任务 → 方法 → 工程」三层组织，阅读顺序也大致如此。

**任务层四篇**，各对应一种输出结构。[Classification](/docs/CS/AI/CV/Classification.md) 是起点：最经典的任务，也是所有骨干预训练的来源，讲基准协议、迁移配方与长尾——它本身简单，但下游全建立在它的表示之上。[Detection](/docs/CS/AI/CV/Detection.md) 是工程密度最高的一篇：候选区域、锚点、标签分配、NMS、DETR 家族逐条讲，因为检测的机制最庞杂。[Segmentation](/docs/CS/AI/CV/Segmentation.md) 把粒度推到像素，重点是语义/实例/全景三档的统一，以及 SAM 把分割重构成可提示基础模型后范式如何改变。[Tracking](/docs/CS/AI/CV/Tracking.md) 处理时间维：检测给框、关联给 ID，两段式链路与端到端 Transformer 跟踪并存。

**方法层三篇**回答"模型凭什么工作"。[Traditional CV](/docs/CS/AI/CV/Traditional_CV.md) 是深度学习之前的手工特征范式，今天仍在 SLAM、拼接、工业质检服役，也是理解卷积与多尺度的思想源头。[Representation Learning](/docs/CS/AI/CV/Representation_Learning.md) 讲特征如何从数据中学出来：对比学习、掩码重建、自蒸馏三条自监督路线，到 CLIP 的图文对齐与 VLM，是预训练—微调范式的理论底座。[Metrics](/docs/CS/AI/CV/Metrics.md) 讲 IoU 与 mAP 的口径——指标塑造了检测器的演化史，读论文数字前先读它。

**工程层两篇**管落地。[Data and Preprocessing](/docs/CS/AI/CV/Data_and_Preprocessing.md) 从张量表示讲到标注格式与类别不平衡，数据管线决定精度上限。[Deployment](/docs/CS/AI/CV/Deployment.md) 讲导出、量化、蒸馏、运行时选型，以及 AGPL 许可证这类非技术但致命的陷阱。

## From Tasks to Foundation Models

一条清晰的收敛曲线：早期每个任务一个专用模型，2017 年后 Transformer 统一架构，2023 年起基础模型把任务边界也抹平了——**SAM 3**（2025-11）一个模型同时做检测、分割、跟踪，用文本或示例提示词指定概念；CLIP 系让分类变成"造句"；DINOv3 的冻结特征被 RT-DETRv4 直接蒸馏进实时检测器。视觉的终局不是某个任务的更高精度，而是**一个可提示的视觉基础模型 + 下游轻量任务头**的分层生态。

## Practice

torchvision 提供预训练模型，分类任务几行即可推理；权重与预处理绑定，避免手工对齐均值方差的坑：

```python
from torchvision.models import resnet50, ResNet50_Weights

weights = ResNet50_Weights.IMAGENET1K_V2
model = resnet50(weights=weights).eval()
preprocess = weights.transforms()
# preds = model(preprocess(img).unsqueeze(0))
```

检测 / 分割同理：`torchvision.models.detection.fasterrcnn_resnet50_fpn`、`maskrcnn_resnet50_fpn` 开箱即用；追求实时与边缘部署走 Ultralytics 线（YOLO26），链路见 [Deployment](/docs/CS/AI/CV/Deployment.md)。

## Links

- [CNN](/docs/CS/AI/CNN.md)
- [Detection](/docs/CS/AI/CV/Detection.md)
- [Segmentation](/docs/CS/AI/CV/Segmentation.md)
- [Representation Learning](/docs/CS/AI/CV/Representation_Learning.md)
- [Metrics](/docs/CS/AI/CV/Metrics.md)
- [Deployment](/docs/CS/AI/CV/Deployment.md)

## References

1. [Faster R-CNN: Towards Real-Time Object Detection](https://arxiv.org/abs/1506.01497)
2. [You Only Look Once: Unified, Real-Time Object Detection-YOLO](https://pjreddie.com/darknet/yolo/)
3. [U-Net: Convolutional Networks for Biomedical Image Segmentation](https://arxiv.org/abs/1505.04597)
4. [Mask R-CNN](https://arxiv.org/abs/1703.06870)
5. [Segment Anything](https://arxiv.org/abs/2304.02643)
6. [SAM 3: Segment Anything with Concepts](https://arxiv.org/abs/2511.16719)
7. [Learning Transferable Visual Models From Natural Language Supervision-CLIP](https://arxiv.org/abs/2103.00020)
8. [torchvision 官方文档](https://pytorch.org/vision/stable/index.html)
