# 深度学习

| Share Data        | Copy Data      |
| ----------------- | -------------- |
| torch.as_tensor() | torch.Tensor() |
| torch.from_numpy  | torch.tensor() |

tensor 

ArgMax dim axis

**weight.shape**

- the first axis number of filters
- the second axis depth of each filter == input channels
- the third axis height of each filter
- the fourth axis width of each filter



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

### The Training Process

1. Get batch from the training set
2. Pass batch to the network
3. Calculate the loss(difference between the predicted values and the true values)
4. Calculate the gradient of the loss function w.r.t the network's weights
5. Update the weights using the gradients to reduce the loss
6. Repeat steps 1-5 until one epoch is completed
7. Repeat steps 1-6 for as many epochs required to obtain the desired level of accuracy

##### Entropy

$$
H_i=-\sum_{k=1}^n{p_{i,k}log(p_{i,k})}
 (p_{i,k}!=0)
$$



神经元



|                           |                                                    |                                                              |
| ------------------------- | -------------------------------------------------- | ------------------------------------------------------------ |
| 基本神经网络元            | Basic Neural Network Cells                         | weight*x+bias                                                |
| 卷积神经元                | Convolutional Cells                                |                                                              |
| 解卷积神经元              |                                                    |                                                              |
| 池化神经元/插值神经元     | Pooling And Interpolating Cells                    |                                                              |
| 均值神经元/标准方差神经元 | Mean And Standard Deviation Cells                  |                                                              |
| 循环神经元                | Recurrent Cells                                    | 存储当前和先前值两个状态                                     |
| 长短期记忆神经元          | Long Shart Term Memory Cells                       | LSTM是一个逻辑回路，可存储输入和记忆神经元当前和先前值共四种状态，拥有三个门 |
| 门控循环神经元            | Gated Recurrent Cells                              | LSTM的变体，只有更新门和重置门，合并输出遗忘为更新门         |
| 神经细胞层                | Layers                                             |                                                              |
| 卷积连接层                | Convolutional Connexted Layers                     |                                                              |
| 时间滞后连接              | Time Delayed Connextions                           |                                                              |
| 前馈神经网络              | Feed Forward Neural Networks                       |                                                              |
| 径向基神经网络            | Radial Basic Function                              |                                                              |
| 霍普菲尔网络              | Hopfied Network                                    |                                                              |
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
| 生成式对抗网络            | Generayive adversarial Networks                    |                                                              |
| 循环神经网络              | Recurrent Neural Networks                          |                                                              |
| 神经图灵机                | Neural Turing Machines                             |                                                              |
|                           | BiRNN/BiLSTM/BiGRU                                 |                                                              |
| 深度残差网络              | Deep Residual Networks                             |                                                              |
| 回声状态网络              | Echo State Networks                                |                                                              |
| Kohonen 网络              |                                                    |                                                              |
| 支持向量机                | SVM                                                |                                                              |
| 液态机                    | LSM                                                |                                                              |
| 极限学习机                | Extreme Learning Machines                          | 随机连接的FFNN，不使用反向传播，函数拟合能力较弱             |

 **Rectified Linear Unit**  ReLU	修正函数