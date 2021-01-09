# 机器学习

## 1.KNN

K-Nearest Neighbor 懒惰学习



| 偏差           | 方差             |
| -------------- | ---------------- |
| 数据和标准数据 | 数据之间的离散度 |

### 常用距离度量

#### 1.Euclidean Distance

$$
d(p,q)=\sqrt{\sum_{i=1}^n\left(q_i-p_i\right)^2}
$$ {Euclidean Distance}

​																	*1.1 Euclidean Distance*

#### 2.Chebyshev Distance

二维平面
$$
\max(|x1-x2|),|y1-y2|)
$$
n维平面
$$
d=\lim_{k\to\infty}(\sum_{i=1}^n|x_i-x_i|^{1/k})
$$

#### 3.Manhattan Distance



#### 4.Minkowski Distance

$$
d=\sqrt[p]{\sum_{k=1}^n|x_k-x_2k|^p}
$$



- p=1时，为Manhattan Distance
- p=2时，为Euclidean Distance
- p →∞ 时，为Chebyshev Distance



#### 5.Mahalanobis Distance



#### 6.Bhattacharyya Distance



#### 7.Hamming Distance

#### 8.Cosine

#### 9.Jaccard Similarity Coefficient

#### 10.Pearson Correlation Coefficient



### kNN算法的优缺点

#### 优点

- 简单好用，容易理解，精度高，理论成熟，既可以用来做分类也可以用来做回归；
- 可用于数值型数据和离散型数据；
- 训练时间复杂度为O(n)；无数据输入假定；
- 对异常值不敏感

#### 缺点

- 计算复杂性高；空间复杂性高；
- 样本不平衡问题（即有些类别的样本数量很多，而其它样本的数量很少）；
- 一般数值很大的时候不用这个，计算量太大。但是单个样本又不能太少，否则容易发生误分。
- 最大的缺点是无法给出数据的内在含义。

## 2.决策树



## 4.SVM

SVM(Support Virtual Machine)可用于classification，

optimization

kernel function

hyperplane

## 5.HMM

Hidden Markov Model

用途：NLP和语音识别

概率图：

- 有向 Bayesion Network
- 无向 Markov Random Field（Markov Network）

Dynamic Model：

- HMM
- Kalman Filter
- Particle Filter

