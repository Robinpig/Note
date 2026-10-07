## Introduction

支持向量机（Support Vector Machine，SVM）是一种强大的监督学习算法，可用于 classification 和回归（SVR）。它的核心思想是：在所有能把两类分开的超平面中，找出**离两类样本都最远**的那一个——间隔最大的决策边界泛化能力最好。

它解决的问题是：中小规模、高维特征下的分类任务（如文本分类），以及在特征不可分时通过核函数低成本地引入非线性能力。

## Linear Separable

当两类样本**线性可分（Linear Separable）**时，存在无数个能正确划分它们的超平面（hyperplane）：

$$
w^T x + b = 0
$$

SVM 从中选出间隔最大化的那个。样本点 $(x_i,y_i)$ 到超平面的**几何间隔**为：

$$
\gamma_i = \frac{y_i(w^T x_i + b)}{\lVert w \rVert},\qquad
\gamma = \min_{1\le i\le N}\gamma_i
$$

距离超平面最近、使 $\gamma_i=\gamma$ 的那几个样本决定了间隔边界，它们被称为**支持向量（Support Vector）**——删掉其它样本、只保留支持向量，最优超平面不变，这正是名字的由来。

## Optimization

求最大间隔超平面可以写成凸优化问题（原始问题）：

$$
\min_{w,b}\ \frac{1}{2}\lVert w\rVert^2
\qquad
\text{s.t.}\quad y_i(w^T x_i+b)\ge 1,\ i=1,\dots,N
$$

直接解二次规划代价高，标准做法是构造拉格朗日函数转到**对偶（dual）**问题——它规模相同但解起来更方便，而且天然为核函数铺路。

### Lagrangian and Dual Problem

给每条不等式约束配一个拉格朗日乘子 $\alpha_i\ge 0$：

$$
L(w,b,\alpha)=\frac{1}{2}\lVert w\rVert^2-\sum_{i=1}^{N}\alpha_i\left[y_i(w^T x_i+b)-1\right]
$$

对 $L$ 求偏导并令其为零：

$$
\frac{\partial L}{\partial w}=0\ \Rightarrow\ w=\sum_{i=1}^{N}\alpha_i y_i x_i,\qquad
\frac{\partial L}{\partial b}=0\ \Rightarrow\ \sum_{i=1}^{N}\alpha_i y_i=0
$$

把结果代回 $L$ 消去 $w,b$，得到只含 $\alpha$ 的对偶问题：

$$
\max_{\alpha}\ \sum_{i=1}^{N}\alpha_i-\frac{1}{2}\sum_{i=1}^{N}\sum_{j=1}^{N}\alpha_i\alpha_j y_i y_j\, x_i^T x_j
\qquad
\text{s.t.}\quad \sum_{i=1}^{N}\alpha_i y_i=0,\ \alpha_i\ge 0
$$

解出 $\alpha$ 后，$w^*=\sum_i\alpha_i y_i x_i$，任意取一个支持向量 $(x_s,y_s)$ 可恢复 $b^*=y_s-\sum_i\alpha_i y_i x_i^T x_s$（实践中对所有 $0<\alpha_i<C$ 的支持向量取平均，数值更稳）。

原问题是凸二次规划且约束为仿射函数，强对偶成立——对偶问题的最优值就等于原始问题的最优值，且 $w^*,b^*$ 可由 $\alpha^*$ 唯一恢复。

### KKT Conditions

KKT 条件是该问题最优解的充要条件，其中最关键的是**互补松弛（complementary slackness）**：

$$
\alpha_i\left[y_i(w^Tx_i+b)-1\right]=0,\qquad i=1,\dots,N
$$

两项至少一项为零，于是每个样本只有两种身份：

- $\alpha_i=0$：间隔边界之外，对模型**毫无贡献**（这正是"大多数样本不参与决策"的来源）
- $\alpha_i>0$：必有 $y_i(w^Tx_i+b)=1$，恰落在间隔边界上——即**支持向量**

## Soft Margin

现实数据往往有噪声、不完全线性可分，硬间隔会把边界扭曲得厉害。软间隔（Soft Margin）引入松弛变量 $\xi_i\ge 0$，允许少量样本"违反"间隔约束：

$$
\min_{w,b,\xi}\ \frac{1}{2}\lVert w\rVert^2 + C\sum_{i=1}^{N}\xi_i
\qquad
\text{s.t.}\quad y_i(w^T x_i+b)\ge 1-\xi_i,\ \xi_i\ge 0
$$

惩罚系数 **C** 平衡"间隔大"与"分类错得少"：

- C 大：对误分类惩罚重，趋向硬间隔，容易过拟合
- C 小：容忍更多错误，间隔更宽，泛化更稳

对偶形式与硬间隔几乎相同，只是乘子被"装进盒子"：$0\le\alpha_i\le C$。此时 KKT 把样本分成三类：

| 乘子 | 位置 | 含义 |
| ------ | ------ | ------ |
| $\alpha_i=0$ | $y_if(x_i)\ge 1$ | 间隔外，非支持向量 |
| $0<\alpha_i<C$ | $y_if(x_i)=1$ | 恰在间隔边界上 |
| $\alpha_i=C$ | $y_if(x_i)\le 1$ | 间隔内或被错分（$\xi_i>0$） |

## SMO

对偶问题规模为 N，通用二次规划求解器太慢。SMO（Sequential Minimal Optimization）的思路是**每次只选两个变量**做解析求解，反复迭代直到收敛——之所以必须两个，是因为等式约束 $\sum_i\alpha_iy_i=0$ 固定其它变量后只剩两个自由度，只优化一个会破坏约束。

### Variable Selection

- **第一个变量**（外层循环）：挑选违反 KKT 条件最严重的 $\alpha_1$，交替在"全部样本"与"非边界样本（$0<\alpha_i<C$）"中扫描
- **第二个变量**（内层循环）：选使 $|E_1-E_2|$ 最大的 $\alpha_2$，其中 $E_i=f(x_i)-y_i$ 为预测误差（启发式：两个误差差得越远，一步走得越远）

### Closed-form Solution of Subproblems

固定其余变量后，$\alpha_2$ 的更新有闭式解：

$$
\alpha_2^{new,unclipped}=\alpha_2^{old}+\frac{y_2(E_1-E_2)}{\eta},\qquad
\eta=K_{11}+K_{22}-2K_{12}
$$

其中 $K_{ij}=x_i^Tx_j$。再按约束把 $\alpha_2$ **截断（clip）**到允许区间 $[L,H]$：

$$
y_1\ne y_2:\ L=\max(0,\alpha_2-\alpha_1),\ H=\min(C,\,C+\alpha_2-\alpha_1)
$$

$$
y_1 = y_2:\ L=\max(0,\alpha_1+\alpha_2-C),\ H=\min(C,\,\alpha_1+\alpha_2)
$$

$\alpha_1$ 随后按 $\alpha_1^{new}=\alpha_1^{old}+y_1y_2(\alpha_2^{old}-\alpha_2^{new})$ 联动更新，$b$ 用 $E_1,E_2$ 修正。外层持续扫描直到所有样本在容忍度 $\epsilon$ 内满足 KKT 条件。由于每步都是解析解且无需存储完整核矩阵，SMO 把大规模 SVM 变得可行。

## Kernel Function

当数据线性不可分时，把样本映射到高维空间 $\phi(x)$ 使其在高维中线性可分。对偶问题中只出现内积 $x_i^Tx_j$，于是可以用**核函数（kernel function）**直接代替高维内积，避免显式计算高维映射（核技巧，kernel trick）：

$$
K(x_i,x_j)=\phi(x_i)^T\phi(x_j)
$$

常用核函数：

| 核函数 | 表达式 | 适用场景 |
| -------- | -------- | ---------- |
| 线性核 | $x_i^Tx_j$ | 特征多、样本大（文本分类） |
| 多项式核 | $(\gamma\,x_i^Tx_j+r)^d$ | 需要适度非线性 |
| RBF / 高斯核 | $\exp(-\gamma\lVert x_i-x_j\rVert^2)$ | 默认首选，通用性最强 |

不是任意函数都能当核——必须满足 Mercer 条件（对应某 Hilbert 空间的内积）。

> [!NOTE]
> Hinge 损失 $\max(0,\ 1-y\hat{y})$ 是 SVM 损失的另一种表述：软间隔 SVM 等价于最小化 "Hinge 损失 + L2 正则"，与[逻辑回归](/docs/CS/AI/ML/LinearModel.md)（交叉熵损失）只有损失函数之差。

## SVR

SVM 也能做回归——支持向量回归（Support Vector Regression，SVR）的出发点是：**容忍预测与真实值之间有 $\epsilon$ 的偏差**，只有偏差超过 $\epsilon$ 才计损失，这就是 $\epsilon$-不敏感损失（$\epsilon$-insensitive loss）：

$$
L_\epsilon(y,f(x))=\max\left(0,\ |y-f(x)|-\epsilon\right)
$$

几何上相当于在拟合函数 $f(x)=w^Tx+b$ 两侧铺一条宽 $2\epsilon$ 的"间隔带"，落在带内的样本损失为零。优化问题为：

$$
\min_{w,b,\xi,\xi^*}\ \frac{1}{2}\lVert w\rVert^2+C\sum_{i=1}^{N}(\xi_i+\xi_i^*)
\qquad
\text{s.t.}\ \begin{cases}f(x_i)-y_i\le\epsilon+\xi_i^*\\ y_i-f(x_i)\le\epsilon+\xi_i\\ \xi_i,\xi_i^*\ge 0\end{cases}
$$

对偶化后同样可以换核。它的漂亮之处在于**稀疏性**：只有落在间隔带之外的样本才对应非零乘子（才是"支持向量"），预测函数只由这些点决定——这与普通最小二乘"每个样本都有残差、都参与解"形成鲜明对比。

## Pros and Cons

- **优点**：间隔最大化带来良好的泛化能力；核技巧处理非线性；决策只依赖支持向量，结果稳健；高维空间表现好（文本分类经典强基线）
- **缺点**：大规模样本训练慢（对偶问题 O(n²)~O(n³)，工程上改用线性 SVM 或换树模型）；对缺失数据、超参数（C、γ）敏感；天然输出的是间隔而非概率（需要额外校准，如 Platt Scaling）；多分类需要 one-vs-one / one-vs-rest 拆分

## Practice

```python
from sklearn.svm import SVC, SVR
from sklearn.preprocessing import StandardScaler
from sklearn.pipeline import make_pipeline

svm = make_pipeline(
    StandardScaler(),                    # SVM 对特征尺度敏感，必须归一化
    SVC(kernel="rbf", C=1.0, gamma="scale")
)
svm.fit(X_train, y_train)
print(svm.predict(X_test), svm.support_vectors_.shape)   # 支持向量规模

svr = make_pipeline(StandardScaler(), SVR(kernel="rbf", C=1.0, epsilon=0.1))
svr.fit(X_train, y_train)                                # epsilon 即间隔带半宽
```

## Links

- [ML](/docs/CS/AI/ML/ML.md)
- [KNN](/docs/CS/AI/ML/KNN.md)
- [DecisionTree](/docs/CS/AI/ML/DecisionTree.md)

## References

1. [统计学习方法（第2版）第7章 支持向量机-豆瓣](https://book.douban.com/subject/33437381/)
2. [机器学习（西瓜书）第6章 支持向量机-豆瓣](https://book.douban.com/subject/26708119/)
3. [sklearn SVC 官方文档](https://scikit-learn.org/stable/modules/generated/sklearn.svm.SVC.html)
4. [sklearn SVR 官方文档](https://scikit-learn.org/stable/modules/generated/sklearn.svm.SVR.html)
