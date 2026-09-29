## Introduction

深度学习（Deep Learning，DL）是机器学习（[ML](/docs/CS/AI/ML/ML.md)）的分支：用**多层神经网络**自动从数据中学习特征表示，取代人工特征工程——网络越深，能表达的抽象层次越高。

它解决的问题是：图像、语音、文本这类原始数据难以手工定义特征（什么是"猫耳朵"的像素规则？），让网络端到端地自己学。三大网络家族分别匹配三类数据结构：

- **CNN**（卷积）：网格数据（图像），见 [CNN](/docs/CS/AI/CNN.md)
- **RNN/LSTM**（循环）：序列数据（文本、语音），应用见 [NLP](/docs/CS/AI/NLP/NLP.md)
- **Transformer**（注意力）：并行建模长程依赖，统一了以上场景，是 [LLM](/docs/CS/AI/LLM/LLM.md) 的底座

工具链上 PyTorch 与 TensorFlow 双雄并立（见 [PyTorch](/docs/CS/AI/PyTorch.md)、[TensorFlow](/docs/CS/AI/TensorFlow.md)），本目录示例用 PyTorch 语法。网络结构全景速查见 [Neurons](/docs/CS/AI/DL/Neurons.md)。

## Activation Functions

没有非线性激活，多层网络等价于一个线性变换。**Rectified Linear Unit（ReLU）修正函数**是最常用的选择，同族对比：

| 激活函数 | 公式 | 特点 |
| -------- | -------- | -------- |
| Sigmoid | $\sigma(x)=\frac{1}{1+e^{-x}}$ | 输出 (0,1)，两端饱和致梯度消失 |
| Tanh | $\tanh(x)$ | 输出 (-1,1)，零中心，同样有饱和区 |
| ReLU | $\max(0,x)$ | 计算极快、正区不饱和；负区"神经元死亡" |
| GELU | 平滑版 ReLU | Transformer 标配 |

## Links

- [AI](/docs/CS/AI/AI.md)
- [ML](/docs/CS/AI/ML/ML.md)
- [Tensor](/docs/CS/AI/DL/Tensor.md)
- [Training](/docs/CS/AI/DL/Training.md)
- [Neurons](/docs/CS/AI/DL/Neurons.md)
- [Regularization](/docs/CS/AI/DL/Regularization.md)
- [CNN](/docs/CS/AI/CNN.md)
- [PyTorch](/docs/CS/AI/PyTorch.md)
- [TensorFlow](/docs/CS/AI/TensorFlow.md)

## References

1. [Deep Learning-Goodfellow 花书](https://www.deeplearningbook.org/)
2. [动手学深度学习-D2L 中文版](https://zh.d2l.ai/)
3. [PyTorch 官方教程](https://pytorch.org/tutorials/)
4. [Neural Networks 系列-3Blue1Brown](https://www.3blue1brown.com/topics/neural-networks)
