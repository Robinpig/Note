## Introduction

一张速查表纵览各类神经元与网络结构：从基本神经元到门控循环，从自编码器到生成对抗网络。按家族理解——卷积系看 [CNN](/docs/CS/AI/CNN.md)，循环系的应用见 [NLP](/docs/CS/AI/NLP/NLP.md)，预训练与 Transformer 时代的演进见 [DL](/docs/CS/AI/DL/DL.md) 总览。

## Neurons and Networks

|                           |                                                    |                                                              |
| ------------------------- | -------------------------------------------------- | ------------------------------------------------------------ |
| 基本神经网络元            | Basic Neural Network Cells                         | weight*x+bias                                                |
| 卷积神经元                | Convolutional Cells                                |                                                              |
| 解卷积神经元              |                                                    |                                                              |
| 池化神经元/插值神经元     | Pooling And Interpolating Cells                    |                                                              |
| 均值神经元/标准方差神经元 | Mean And Standard Deviation Cells                  |                                                              |
| 循环神经元                | Recurrent Cells                                    | 存储当前和先前值两个状态                                     |
| 长短期记忆神经元          | Long Short Term Memory Cells                       | LSTM是一个逻辑回路，可存储输入和记忆神经元当前和先前值共四种状态，拥有三个门 |
| 门控循环神经元            | Gated Recurrent Cells                              | LSTM的变体，只有更新门和重置门，合并输出遗忘为更新门         |
| 神经细胞层                | Layers                                             |                                                              |
| 卷积连接层                | Convolutional Connected Layers                     |                                                              |
| 时间滞后连接              | Time Delayed Connections                           |                                                              |
| 前馈神经网络              | Feed Forward Neural Networks                       |                                                              |
| 径向基神经网络            | Radial Basic Function                              |                                                              |
| 霍普菲尔网络              | Hopfield Network                                   |                                                              |
| 马尔可夫链                | Markov Chain                                       |                                                              |
| 玻尔兹曼机                | Boltzmann Machines                                 |                                                              |
| 受限玻尔兹曼机            | Restricted Boltzmann Machines                      |                                                              |
| 自编码机                  | Autoencoders                                       |                                                              |
| 稀疏自编码机              | Sparse Autoencoders                                |                                                              |
| 变分自编码机              | Variational Autoencoders                           |                                                              |
| 去噪自编码机              | Denoising Autoencoders                             |                                                              |
| 深度信念网络              | Deep Belief Networks                               |                                                              |
| 卷积神经网络              | Convolutional Neural Networks                      |                                                              |
| 解卷积网络                | Deconvolutional Networks/Inverse Graphics Networks |                                                              |
| 深度卷积逆向图网络        | DCIGN                                              |                                                              |
| 生成式对抗网络            | Generative Adversarial Networks                    |                                                              |
| 循环神经网络              | Recurrent Neural Networks                          |                                                              |
| 神经图灵机                | Neural Turing Machines                             |                                                              |
|                           | BiRNN/BiLSTM/BiGRU                                 |                                                              |
| 深度残差网络              | Deep Residual Networks                             |                                                              |
| 回声状态网络              | Echo State Networks                                |                                                              |
| Kohonen 网络              |                                                    |                                                              |
| 支持向量机                | SVM                                                |                                                              |
| 液态机                    | LSM                                                |                                                              |
| 极限学习机                | Extreme Learning Machines                          | 随机连接的FFNN，不使用反向传播，函数拟合能力较弱             |

## Links

- [DL](/docs/CS/AI/DL/DL.md)
- [CNN](/docs/CS/AI/CNN.md)
- [NLP](/docs/CS/AI/NLP/NLP.md)
