## Introduction

PyTorch 是 Meta AI（原 FAIR）2017 年开源的深度学习框架，凭借 **define-by-run 动态图**、彻底 Pythonic 的 API 和与 NumPy 近乎一致的张量体验，在 2018 年后成为学术研究的事实标准，并通过 TorchServe、TorchScript/`torch.compile`、分布式训练等能力补齐工业部署，当前大模型生态（Hugging Face Transformers、vLLM、Megatron 等）基本都以 PyTorch 为底座。

## Core Abstraction

- **Tensor**：类似 `numpy.ndarray` 的多维数组，额外具备 GPU 设备放置与自动微分能力。
- **autograd**：张量设置 `requires_grad=True` 后，前向运算构建动态计算图（由 `Function` 节点组成），调用 `loss.backward()` 沿链式法则反向传播，梯度累积到 `.grad`。
- **nn.Module**：所有模型/层的基类，`__init__` 声明子模块与参数，`forward` 描述计算；模块可任意嵌套，`parameters()` 递归收集权重供优化器使用。
- **Optimizer**：`torch.optim.SGD/AdamW`，按 `zero_grad() → backward() → step()` 三步更新。
- **DataLoader / Dataset**：Dataset 定义如何取单条样本，DataLoader 负责批处理、shuffle、多进程预取（`num_workers`）、collate。

```python
import torch
from torch import nn

device = "cuda" if torch.cuda.is_available() else "cpu"
model = nn.Sequential(nn.Linear(784, 128), nn.ReLU(), nn.Linear(128, 10)).to(device)
opt = torch.optim.AdamW(model.parameters(), lr=1e-3)
loss_fn = nn.CrossEntropyLoss()

for x, y in train_loader:                      # x: [B,784], y: [B]
    x, y = x.to(device), y.to(device)
    opt.zero_grad()
    logits = model(x)
    loss = loss_fn(logits, y)
    loss.backward()                            # autograd 反传
    opt.step()
```

### Significance of Dynamic Graphs

每次 `forward` 都是用普通 Python 重新跑一遍、即时建图，因此可以自由使用 `if/for/while`、按输入长度改变网络结构（这对 NLP 中变长序列至关重要），出错时栈帧就是普通 Python 调用栈，可直接 pdb 断点。对照 [TensorFlow](/docs/CS/AI/TensorFlow.md) 1.x 的静态图：先声明后执行、调试困难但部署优化空间大。

## Tensor Creation and Data Copying

| 共享数据（浅拷贝，改一个另一个也变） | 拷贝数据 |
|--------------------------------------|---------|
| `torch.as_tensor()`、`torch.from_numpy()` | `torch.tensor()`、`torch.Tensor()` |

其余常用点：`view/reshape` 改形状（前者要求内存连续）、`permute/transpose` 换轴、`squeeze/unsqueeze` 增减维度、`cat/stack` 拼接、广播（broadcasting）规则、`argmax(dim=...)` 指定归约轴（NumPy 里叫 axis）。卷积权重 `weight.shape = [out_channels, in_channels, kH, kW]`，具体层输出 shape 推导见 [DL](/docs/CS/AI/DL/DL.md)。

## Ecosystem

| 组件 | 用途 |
|------|------|
| torchvision / torchaudio | 图像/音频的数据集、预训练模型、变换 |
| torch.nn.functional (F) | 函数式算子（relu/conv2d/cross_entropy），无状态调用 |
| TorchScript / torch.compile | TorchScript 是早期图序列化方案；2.0 的 `torch.compile`（Dynamo+Inductor）通过图捕获与算子融合提速 |
| DistributedDataParallel (DDP) | 多卡训练主流：每卡一个进程，反向时 all-reduce 梯度；对比老式 DataLoader 并行的 DP 更高效 |
| FSDP / DeepSpeed / Megatron | 大模型训练：参数/优化器状态/激活的分片、张量并行、流水线并行 |
| AMP (`torch.cuda.amp`) | 混合精度：FP16/BF16 前向 + FP32 主权重，省显存且常能提速 |
| TorchServe / ONNX / libtorch | 生产服务化、跨框架交换格式、C++ 推理 |

## Common Pitfalls in Training

- **忘记 `zero_grad()`**：梯度默认累加（RNN 截断反传时才需要这种行为），普通训练每个 step 必须清零。
- **训练/推理模式忘记切换**：`model.train()` / `model.eval()` 影响 Dropout 与 BatchNorm；推理还应包 `torch.no_grad()` 关闭建图省显存。
- **`.item()`/`.cpu()` 用在循环里**：强制 GPU 同步，显著拖慢训练；日志打印才取值。
- **in-place 操作与 autograd 冲突**：会报 "a leaf Variable ... used in-place"，尤其在改写张量数据时。
- DataLoader 用 Python list 收整个数据集会爆内存，用 tensor 或流式 Dataset；多进程下数据切分用 `DistributedSampler`。

## Links

- [TensorFlow](/docs/CS/AI/TensorFlow.md)
- [DL](/docs/CS/AI/DL/DL.md)
- [CNN](/docs/CS/AI/CNN.md)
- [NLP](/docs/CS/AI/NLP/NLP.md)
- [Scikit-Learn](/docs/CS/AI/Scikit-Learn.md)

## References

1. [PyTorch](https://pytorch.ac.cn/)
2. [PyTorch 官方教程：Learning PyTorch](https://pytorch.org/tutorials/beginner/basics/intro.html)
