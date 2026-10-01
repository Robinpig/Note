## Introduction

本篇把"训练一个深度网络"拆成三段：**前向算损失 → 反向传梯度 → 优化器更新**。前一环节的工程化（取 batch、拼 pipeline）见 [Tensor](/docs/CS/AI/DL/Tensor.md)；后一环节的泛化手段见 [Regularization](/docs/CS/AI/DL/Regularization.md)。

## The Training Process

一个 epoch 的标准循环：

1. Get batch from the training set
2. Pass batch to the network
3. Calculate the loss(difference between the predicted values and the true values)
4. Calculate the gradient of the loss function w.r.t the network's weights
5. Update the weights using the gradients to reduce the loss
6. Repeat steps 1-5 until one epoch is completed
7. Repeat steps 1-6 for as many epochs required to obtain the desired level of accuracy

第 3 步分类任务常用交叉熵——对单样本 one-hot 标签，即熵的形式：

$$
H_i=-\sum_{k=1}^n{p_{i,k}\log(p_{i,k})}\quad (p_{i,k}\ne 0)
$$

## Backpropagation

第 4 步"算梯度"靠**反向传播（Backpropagation）**：损失函数对参数的导数，沿计算图从输出层向输入层**链式法则**逐层回传：

$$
\frac{\partial L}{\partial w_1}=\frac{\partial L}{\partial a_n}\cdot\frac{\partial a_n}{\partial a_{n-1}}\cdots\frac{\partial a_1}{\partial w_1}
$$

连乘结构带来两个经典问题：

- **梯度消失**：每项 <1，梯度指数级衰减——Sigmoid 饱和区尤甚；LSTM 门控、ReLU、残差连接（见 [CNN](/docs/CS/AI/CNN.md) 的 ResNet 一节）都是对策
- **梯度爆炸**：每项 >1，梯度指数级增大——梯度裁剪（clipping）应对

第 5 步沿负梯度更新参数 $w\leftarrow w-\eta\,\nabla L$，$\eta$ 即学习率。

## Optimizers

| 优化器 | 更新思想 | 备注 |
| ------ | ------ | ------ |
| SGD | 沿负梯度小步更新 | 基线，大 batch 下稳定 |
| SGD + Momentum | 累积历史方向，冲过小坑 | 加速收敛、抑制震荡 |
| Adam | 自适应每个参数的学习率（一阶+二阶矩） | 深度学习默认首选，对学习率不敏感 |

学习率是最重要的超参数：常配**调度器**（warmup 后余弦退火/阶梯衰减）。批量策略上 Mini-batch 是标准折中：BGD 稳但慢，SGD 单样本噪声大。

## Links

- [DL](/docs/CS/AI/DL/DL.md)
- [Tensor](/docs/CS/AI/DL/Tensor.md)
- [Regularization](/docs/CS/AI/DL/Regularization.md)
- [CNN](/docs/CS/AI/CNN.md)
