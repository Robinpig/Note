## Introduction

视觉项目的精度天花板往往由数据决定，不是模型。标注质量、类别分布、预处理一致性——这三件事各能偷掉 5 个点以上。本篇按「张量表示 → 归一化 → 尺寸策略 → 增强 → 标注格式 → 不平衡」的顺序把数据管线过一遍，配套训练配方见 [Classification](/docs/CS/AI/CV/Classification.md)、[Detection](/docs/CS/AI/CV/Detection.md)。

## Tensor Representation

图像进网络前是张量：**NCHW**（PyTorch 约定，batch × 通道 × 高 × 宽）或 **NHWC**（TensorFlow/TensorRT 部分场景）。像素 uint8 0–255 转 float 后归一化：

- **通道序**：OpenCV 读入是 **BGR**，PIL/PyTorch 是 **RGB**——混用库是最常见的静默 bug，症状是精度莫名掉几个点
- **归一化**：按数据集均值方差归到零均值单位方差，ImageNet 口径 mean=[0.485, 0.456, 0.406]、std=[0.229, 0.224, 0.225]；torchvision 把预处理与权重绑定（`weights.transforms()`），能规避大部分不一致

## Resize and Pad Strategies

网络输入尺寸固定，原图长宽比五花八门，两条路：

| 策略 | 做法 | 代价 |
| ------ | ------ | ------ |
| 直接 resize | 拉伸/压缩到目标 | 物体形变，圆变椭圆 |
| letterbox | 等比缩放 + 补边 | 引入无效像素，计算浪费 |
| 等比 + crop | 缩放后裁剪 | 丢边缘内容 |

YOLO 默认 letterbox；分类惯用"随机尺度裁剪"当增强。**补边值也有讲究**：补 114（数据集均值近似）比补 0 更稳。小目标场景可以直接放大输入分辨率，但计算量平方增长，[Deployment](/docs/CS/AI/CV/Deployment.md) 的切片推理是另一种解法。

## Augmentation

增强是视觉独有的正则主力，但**任务不同规则不同**：分类（见 [Classification](/docs/CS/AI/CV/Classification.md)）只动图，检测/分割必须同步变换标注。

- **分类**：RandomResizedCrop（scale 0.08–1.0）、水平翻转（注意文本/方向敏感数据别翻）、颜色抖动、RandAugment/TrivialAugment、Mixup/CutMix（见 [Classification](/docs/CS/AI/CV/Classification.md)）
- **检测**：几何变换必须把框一起变换（仿射矩阵同时作用于像素与框坐标）；**Mosaic**（四图拼接，YOLO 系招牌，逼模型学小目标与上下文）、**Copy-Paste**（把实例连同掩码贴到别处，专治实例不足）
- **分割**：裁剪 + 掩码同步；弹性形变（医学常用，模拟组织形变）
- **视频**：时间维采样（均匀抽帧、关键帧优先）、时序一致性增强

调参经验：增强强度与数据集大小正相关——小数据集需要更强的增强防过拟合，大数据集过强的增强反而拖慢收敛。

## Annotation Formats

三种主流格式，概念都是「图 → 若干标注」：

```json
// COCO JSON：images / annotations / categories 三段
{"images": [{"id": 1, "file_name": "a.jpg", "width": 640, "height": 480}],
 "annotations": [{"image_id": 1, "category_id": 3, "bbox": [x, y, w, h], "area": 1234, "iscrowd": 0}],
 "categories": [{"id": 3, "name": "car"}]}
```

- **COCO JSON**：bbox 是 `[x, y, w, h]` 左上角 + 宽高，含 `iscrowd` 区分密集人群
- **Pascal VOC XML**：`[xmin, ymax, xmax, ymax]`，老格式但存量数据多
- **YOLO txt**：每行 `class cx cy w h`，全部归一化到 0–1——最轻，丢了原图尺寸信息

转换时最容易错的是坐标语义（角点 vs 中心、绝对 vs 归一化）和宽高顺序，转换后必须抽样可视化核对。

## Class Imbalance

真实数据长尾严重：头部类占 90%+，尾部类几张图。手段分三层：**数据层**（过采样尾部、欠采样头部、class-balanced sampler 按 $n^{-1/4}$ 定采样概率）、**损失层**（focal loss、LDAM margin，见 [Detection](/docs/CS/AI/CV/Detection.md)）、**后处理层**（按类别调阈值）。

工业缺陷检测还常见另一个极端：**只有正例的异常检测**——把所有异常当未知类，用自监督或异常分数（PatchCore 一类）而不是常规检测器。

## Annotation Economics

标注成本常是项目主成本。降本的常见手段：

- **模型预标注**：SAM 一类基础模型先跑一遍，人工只改错（见 [Segmentation](/docs/CS/AI/CV/Segmentation.md)）
- **主动学习**：用模型不确定性挑最难样本送标
- **伪标签**：高置信预测回灌训练集，注意确认偏差（错标会自我强化）

## Links

- [CV](/docs/CS/AI/CV.md)
- [Classification](/docs/CS/AI/CV/Classification.md)
- [Detection](/docs/CS/AI/CV/Detection.md)
- [Deployment](/docs/CS/AI/CV/Deployment.md)
- [Segmentation](/docs/CS/AI/CV/Segmentation.md)

## References

1. [Microsoft COCO: Common Objects in Context](https://arxiv.org/abs/1405.0312)
2. [CutMix: Regularization Strategy to Train Strong Classifiers](https://arxiv.org/abs/1905.04899)
3. [Simple Copy-Paste is a Strong Data Augmentation Method for Instance Segmentation](https://arxiv.org/abs/2012.07177)
4. [COCO 数据集官网](https://cocodataset.org/)
5. [YOLO 数据格式说明（Ultralytics）](https://docs.ultralytics.com/datasets/detect/)
