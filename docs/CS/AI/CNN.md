## Introduction

卷积神经网络（Convolutional Neural Network，CNN）是专为**网格状数据（图像、语音频谱）**设计的神经网络。它用三个先验对抗全连接网络的缺陷：**局部感受野**（像素的邻域才相关）、**权值共享**（同一特征检测器在整张图上复用）、**平移不变性**（猫在左上角和右下角都是猫）。

它解决的问题：一张 1000×1000 的彩色图过全连接层需要 $10^6\times10^6$ 量级的参数，既训不动又极易过拟合——卷积把参数量压到与**核大小**而非图像大小相关。

## Convolution

卷积层用一个小核（kernel/filter）在输入上滑动做加权求和，输出**特征图（feature map）**。三个超参数控制滑动方式：

- **核大小 K**：常见 3×3、5×5
- **步幅 S（stride）**：每次滑几格
- **填充 P（padding）**：边缘补零，控制输出尺寸、保留边缘信息

输出尺寸公式：

$$
O=\frac{W-K+2P}{S}+1
$$

例如 28×28 输入、5×5 核、无填充时输出 24×24——这正是 [Tensor](/docs/CS/AI/DL/Tensor.md) 里 LeNet 那张逐层尺寸表的开头（28→24→12→8→4）。

**多通道卷积**：核的深度必须等于输入通道数，一组核产出一张特征图，卷积层的参数量为：

$$
(K\times K\times C_{in}+1)\times C_{out}
$$

（+1 是每个核的偏置；权重的四维形状含义见 [Tensor](/docs/CS/AI/DL/Tensor.md) 的 weight.shape 一节。）

## Pooling

池化（pooling）对特征图做下采样：**Max Pooling** 取窗口最大值（保留最强响应，最常用）、**Average Pooling** 取均值。作用：缩小尺寸降计算量、扩大感受野、带来小幅平移不变性。池化无可学习参数。现代架构也常用**步幅为 2 的卷积**替代池化。

## Activation and Normalization

- **ReLU**（$\max(0,x)$）：计算便宜、缓解梯度消失，是默认激活；变体 LeakyReLU、GELU（Transformer 系常用）
- **Batch Normalization**：按 batch 对每个通道做均值方差归一化，再学习缩放平移。它允许更大学习率、对初始化不敏感，并带轻微正则效果；副作用是训练/推理行为不同、依赖 batch 统计量，后续演化出 LayerNorm（NLP 主流）、GroupNorm 等

## Receptive Field

**感受野（receptive field）**指某层的一个神经元能"看到"的原始输入区域，随层数加深而扩大：两层 3×3 卷积的感受野等于一层 5×5，但参数更少（2×9+通道 < 25×通道）且多了两层非线性——这是 VGG 用小核堆深度的核心逻辑。

## Classic Architectures

| 网络 | 年份 | 关键贡献 |
| ------ | ------ | ------ |
| LeNet-5 | 1998 | CNN 鼻祖，手写数字识别，卷积+池化+全连接的经典范式 |
| AlexNet | 2012 | ImageNet 冠军引爆深度学习：ReLU、Dropout、GPU 训练、数据增强 |
| VGG | 2014 | 全部用 3×3 小核堆到 19 层，证明"深度=表达力" |
| GoogLeNet | 2014 | Inception 模块多尺度并行（1×1/3×3/5×5 同层拼接），1×1 降维省参数 |
| ResNet | 2015 | 残差连接，突破百层训练瓶颈 |
| EfficientNet | 2019 | 复合缩放（深度/宽度/分辨率统一配比），用少得多的参数达到 SOTA |
| ViT | 2020 | 把图像切成 patch 序列交给 Transformer，卷积被 self-attention 取代 |

## ResNet

网络加深本应更强，实验却发现五十多层比二十层**训练误差还高**——不是过拟合，是优化困难（退化问题）。ResNet（残差网络）给每个块加一条"捷径"：

$$
y=F(x,\{W_i\})+x
$$

让块只需学习**残差** $F(x)=y-x$：最坏情形学成恒等映射（$F=0$）即可不劣于浅层网络，梯度也能经捷径直达浅层。这一结构成为后来几乎所有深度网络（含 [Transformer](/docs/CS/AI/LLM/LLM.md) 时代模型）的标配组件。

## Depthwise Separable Convolution

MobileNet 的核心构件：把标准卷积拆成两步——**深度卷积（depthwise）**对每个输入通道单独做空间卷积、**逐点卷积（pointwise，1×1）**做跨通道线性组合，把参数量与计算量降约一个数量级，代价是精度略降，是端侧推理的默认选择。

## 训练要点

- 优化器 SGD + momentum / Adam；分类头接 softmax + 交叉熵
- **数据增强**：随机裁剪、翻转、颜色抖动、Mixup / CutMix、RandAugment——CNN 的泛化很大程度依赖增强
- **迁移学习**：加载 ImageNet 预训练骨干，冻结浅层（边缘/纹理特征通用），只微调后面的 block 与分类头，是小数据集上的标准做法
- **可视化**：卷积核学到的特征呈边缘 → 纹理 → 部件 → 物体的层次；CAM / Grad-CAM 可显示分类时关注的图像区域

## Practice

PyTorch 搭一个 MNIST 规模的 CNN（详见 [PyTorch](/docs/CS/AI/PyTorch.md)）：

```python
import torch.nn as nn

cnn = nn.Sequential(
    nn.Conv2d(1, 32, kernel_size=3, padding=1),   # 1×28×28 → 32×28×28
    nn.ReLU(),
    nn.MaxPool2d(2),                              # → 32×14×14
    nn.Conv2d(32, 64, kernel_size=3, padding=1),  # → 64×14×14
    nn.ReLU(),
    nn.MaxPool2d(2),                              # → 64×7×7
    nn.Flatten(),
    nn.Linear(64 * 7 * 7, 10)                     # 10 类输出
)
```

训练流程（取 batch、前向、损失、反向、更新）见 [Training](/docs/CS/AI/DL/Training.md)。CNN 的应用面——分类、检测、分割——见 [CV](/docs/CS/AI/CV.md)。

## 适用边界与替代

CNN 的归纳偏置（局部性、平移等变）适合图像与局部相关信号，但卷积感受野增长慢、难以建模全局关系。**Vision Transformer（ViT）** 用 self-attention 直接获得全局感受野，在大数据/大模型设定下反超 CNN；当前实用趋势是二者混合——**ConvNeXt** 证明补上现代化训练技巧后纯卷积也能追平 ViT。

## Links

- [AI](/docs/CS/AI/AI.md)
- [CV](/docs/CS/AI/CV.md)
- [DL](/docs/CS/AI/DL/DL.md)
- [PyTorch](/docs/CS/AI/PyTorch.md)
- [ML](/docs/CS/AI/ML/ML.md)

## References

1. [CNN Explainer-Polo Club](https://poloclub.github.io/cnn-explainer/)
2. [CS231n: Deep Learning for Computer Vision-Stanford](https://cs231n.github.io/)
3. [Deep Residual Learning for Image Recognition-ResNet](https://arxiv.org/abs/1512.03385)
4. [Very Deep Convolutional Networks (VGG)](https://arxiv.org/abs/1409.1556)
5. [Batch Normalization](https://arxiv.org/abs/1502.03167)
6. [MobileNets: Efficient Convolutional Neural Networks for Mobile Vision Applications](https://arxiv.org/abs/1704.04861)
7. [torch.nn.Conv2d-PyTorch 官方文档](https://pytorch.org/docs/stable/generated/torch.nn.Conv2d.html)
