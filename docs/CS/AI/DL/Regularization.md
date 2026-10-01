## Introduction

深度网络参数动辄百万量级，而训练数据有限——**过拟合**（训练集很好、测试集差，见 [ML](/docs/CS/AI/ML/ML.md) 偏差-方差一节）是常态而非意外。本篇汇总深度学习压住过拟合的五类主力手段。

## Dropout

训练时以概率 p 随机把部分神经元输出置零，迫使网络不依赖任何特定通路、等效于同时训练海量子网络；推理时关闭 Dropout。注意训练/推理行为差异——PyTorch 里 `model.train()` 与 `model.eval()` 切换的就是这类层的状态。

## Batch Normalization

对每层的输入按当前 mini-batch 做归一化（减均值除标准差，再学缩放与偏移）：

- 缓解内部协变量偏移，让每层"看到"更稳定的分布
- 加速收敛、允许更大学习率，自带轻微正则效果
- 同样有训练/推理两套统计量（推理用滑动平均）

## Early Stopping

监控验证集损失，不再下降（或开始回升）就停止训练——最便宜的正则化，几乎零成本。与学习率调度联用时注意区分"调度性下降"与"真收敛"。

## Data Augmentation

不新增采集成本，从变换空间造数据：图像的翻转、裁剪、色彩抖动；文本的同义替换、回译；语音的加噪、变速。本质是向模型注入"这些变化不改变标签"的先验。

## Weight Decay

在损失函数上加 L2 惩罚项抑制过大权重，与 [Ridge](/docs/CS/AI/ML/LinearModel.md) 同源；在 Adam 类优化器中，权重衰减与 L2 正则并不等价，AdamW（解耦权重衰减）是当前更标准的做法。

## Links

- [DL](/docs/CS/AI/DL/DL.md)
- [Training](/docs/CS/AI/DL/Training.md)
- [ML](/docs/CS/AI/ML/ML.md)
- [LinearModel](/docs/CS/AI/ML/LinearModel.md)

## References

1. [Dropout: A Simple Way to Prevent Neural Networks from Overfitting](https://arxiv.org/abs/1207.0580)
2. [Batch Normalization: Accelerating Deep Network Training](https://arxiv.org/abs/1502.03167)
