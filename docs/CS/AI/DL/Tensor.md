## Introduction

张量（tensor）是深度学习框架的基本数据单元——**多维数组**：标量、向量、矩阵分别是 0/1/2 维张量，卷积权重是 4 维张量。PyTorch 的一切计算都建立在张量之上（框架定位见 [PyTorch](/docs/CS/AI/PyTorch.md)）。

## Share and Copy

PyTorch 与 NumPy 数组互转有两种语义，选错会引发"改了 A、B 也变了"的隐蔽问题：

| Share Data（共享内存） | Copy Data（复制数据） |
| ----------------- | -------------- |
| torch.as_tensor() | torch.Tensor() |
| torch.from_numpy  | torch.tensor() |

## Common Operations

`argmax(dim)` 沿指定轴取最大值索引：axis 与 dim 同义——TensorFlow 惯用 axis，PyTorch 惯用 dim。

### weight.shape

卷积层权重张量的四轴含义：

- the first axis number of filters（第一轴 = 卷积核个数）
- the second axis depth of each filter == input channels（第二轴 = 每个核的深度，等于输入通道数）
- the third axis height of each filter（第三轴 = 核的高）
- the fourth axis width of each filter（第四轴 = 核的宽）

## Shape Trace Example

以 [LeNet](/docs/CS/AI/CNN.md) 处理 MNIST 为例，一次前向的形状流转——追踪 shape 是调试网络的第一技能：

| Operation             | Output Shape            |
| --------------------- | ----------------------- |
| Identity function     | torch.Size([1,1,28,28]) |
| Convolution(5*5)      | torch.Size([1,6,24,24]) |
| Max pooling(2*2)      | torch.Size([1,6,12,12]) |
| Convolution(5*5)      | torch.Size([1,12,8,8])  |
| Max pooling(2*2)      | torch.Size([1,12,4,4])  |
| Flatten(reshape)      | torch.Size([1,192])     |
| Linear transformation | torch.Size([1,120])     |
| Linear transformation | torch.Size([1,60])      |
| Linear transformation | torch.Size([1,10])      |

## Links

- [DL](/docs/CS/AI/DL/DL.md)
- [Training](/docs/CS/AI/DL/Training.md)
- [PyTorch](/docs/CS/AI/PyTorch.md)

## References

1. [torch.Tensor-PyTorch 官方文档](https://pytorch.org/docs/stable/tensors.html)
