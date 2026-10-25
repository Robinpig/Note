## Introduction

指标不只是评测工具——**检测器的设计是被指标塑造的**。mAP 惩罚重复框，催生了 NMS；NMS 在密集场景误杀难例，催生了免 NMS 的一对一匹配；mAP@0.5 太宽松，COCO 改用 0.5:0.95 十档平均。看不懂指标就读不懂论文里的数字。

本篇按任务组织：检测（IoU 与 mAP）、分割（mIoU 与 Dice）、跟踪（HOTA）、姿态（OKS）。分类指标（accuracy、precision/recall/F1）见 [ML](/docs/CS/AI/ML/ML.md)，分类任务的基准与报告口径见 [Classification](/docs/CS/AI/CV/Classification.md)。

## IoU and Its Variants

**交并比（Intersection over Union）**是定位质量的基本度量：

$$
\mathrm{IoU}=\frac{|A\cap B|}{|A\cup B|}
$$

IoU = 1 完全重合，0 不相交。它同时是指标（多大算检出成功）与损失（回归优化的目标）：

| 变体 | 形式 | 解决的问题 |
| ------ | ------ | ------ |
| IoU loss | $-\log\mathrm{IoU}$ | 直接优化指标，但两框不交时梯度消失 |
| GIoU | 加最小闭包项 | 不交时有梯度，收敛方向仍不准 |
| DIoU | 叠中心距项 | 加速收敛、包围更紧 |
| CIoU | 再叠长宽比一致项 | YOLO 系常用回归损失 |

注意区分**度量用的 IoU**（阈值判定，常取 0.5）和**回归损失**（CIoU 一类可微形式）——两者用途不同，别混用。

## Detection Metrics

### From Confidence Ranking to AP

检测输出每个框一个置信度。按分数降序排列，逐个判定：与某真值 IoU 超过阈值（COCO 取 0.5 起算）记为 TP，否则 FP；漏检的真值记 FN。随阈值滑动得到 PR 曲线，**AP = PR 曲线下面积**。

COCO 采用全点插值（不取 11 个等差点），并对 80 类取平均：

- **mAP@0.5**：宽松口径，看"大致框住"
- **mAP@0.5:0.95**：从 0.5 到 0.95 每 0.05 一档共 10 档再平均——定位不准会被高档位惩罚，是当前论文标准口径
- **AP-S / AP-M / AP-L**：按真值框面积分小（<32²）、中、大（>96²）——小目标 AP 通常是全场洼地，见 [Detection](/docs/CS/AI/CV/Detection.md) 的增强策略

细节陷阱：每图最多计 100 个检测（COCO 协议）、重复框会被 FP 惩罚（这正是 NMS 存在的原因）、类别间 AP 平均而非样本平均。

### Tracking-Aware

跟踪的指标多一层身份：**MOTA**（漏检/误检/ID 跳变合成一数）、**MOTP**（平均定位误差）、**IDF1**（身份匹配占比）、**HOTA**（DetA × AssA，把检测与关联分开归因）。HOTA 是当前推荐主指标，详见 [Tracking](/docs/CS/AI/CV/Tracking.md)。

## Segmentation Metrics

- **mIoU**：逐类算 IoU 再平均。类不平衡时注意是"逐类平均"还是"逐样本平均"——医学场景常按样本算 Dice 再平均
- **Dice 系数**：$\mathrm{Dice}=\frac{2|A\cap B|}{|A|+|B|}$，与 IoU 单调相关（$\mathrm{Dice}=\frac{2\mathrm{IoU}}{1+\mathrm{IoU}}$），数值上更"乐观"，医学论文惯用
- **Boundary F-score**：只看边界带内的匹配，衡量边缘质量——mIoU 高但边缘糊的模型会被它揪出来

## Pose Metrics

关键点检测用 **OKS（Object Keypoint Similarity）**：以真值关键点尺度归一化的预测距离，尺度因子随关键点类型变化（人脸权重高、四肢宽松）。PCK/PCKh 是另一族（阈值内命中率）。OKS 上的 AP 即 COCO keypoints 主指标，见 [Tracking](/docs/CS/AI/CV/Tracking.md) 与 [Segmentation](/docs/CS/AI/CV/Segmentation.md) 的并列任务。

## Statistical Hygiene

- **小验证集**：几百张图上 1 个 AP 的差异可能纯噪声；报数字带 bootstrap 置信区间，或至少说明集大小
- **测试集调参即污染**：COCO test-dev 提交次数有限就是为这个
- **口径一致性**：同一表格里混 mAP@0.5 与 mAP@0.5:0.95 是最常见的误导

## Links

- [CV](/docs/CS/AI/CV.md)
- [Detection](/docs/CS/AI/CV/Detection.md)
- [Segmentation](/docs/CS/AI/CV/Segmentation.md)
- [Tracking](/docs/CS/AI/CV/Tracking.md)
- [ML](/docs/CS/AI/ML/ML.md)

## References

1. [The PASCAL Visual Object Classes Challenge (VOC) 评测口径](http://host.robots.ox.ac.uk/pascal/VOC/)
2. [Microsoft COCO: Common Objects in Context](https://arxiv.org/abs/1405.0312)
3. [HOTA: A Higher Order Metric for Evaluating Multi-Object Tracking](https://arxiv.org/abs/2009.07736)
4. [Distance-IoU Loss: Faster and Better Learning for Bounding Box Regression (DIoU/CIoU)](https://arxiv.org/abs/1911.08287)
