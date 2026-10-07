## Introduction


分治（Divide and Conquer），字面上的解释是「分而治之」，就是把一个复杂的问题分成两个或更多的相同或相似的子问题，
直到最后子问题可以简单的直接求解，原问题的解即子问题的解的合并


Divide and conquer algorithms consist of two parts:

- *Divide:* Smaller problems are solved recursively (except, of course, base cases).
- *Conquer:* The solution to the original problem is then formed from the solutions to the subproblems.





## 递归树与主定理 Master Theorem

分治的复杂度分析几乎都能归约成一条递推式：把「规模怎么缩小」和「每层额外干多少活」分开写，最常见的形式是

$$
T(n) = a\,T\left(\frac{n}{b}\right) + O(n^d), \qquad a \ge 1,\ b > 1
$$

$a$ 是每层分出的子问题个数，$b$ 是规模缩小的比例，$O(n^d)$ 是分解与合并（非递归部分）的代价。三个参数分别对应算法的不同阶段：$a$ 决定分治的宽度，$b$ 决定递归树的深度，$d$ 决定每个节点除递归之外还要干多少活。

主定理（Master Theorem）就是判断这三者组合的胜负手。

### 递归树求和

把递推式展开 $k$ 层：第 $i$ 层有 $a^i$ 个节点，每个节点规模 $n/b^i$，每个节点的本地代价 $O((n/b^i)^d)$，所以第 $i$ 层的**总**代价是

$$
a^i \cdot O\left(\left(\frac{n}{b^i}\right)^{d}\right) = O\left(n^d \left(\frac{a}{b^d}\right)^{i}\right)
$$

整棵递归树的代价就是这个等比数列的求和，再加上叶子层的代价 $a^{\log_b n}$：

$$
T(n) = O\left(\sum_{i=0}^{\log_b n} n^d \left(\frac{a}{b^d}\right)^{i}\right) + O\left(a^{\log_b n}\right)
$$

所有结论都只取决于**公比 $a/b^d$ 与 $1$ 的大小关系**，三种情形如下。

**情形一：$d > \log_b a$（等价于 $b^d > a$，公比小于 1）**

等比数列收敛，求和被根节点那一项支配，$T(n) = O(n^d)$。直观上分治的「宽度增长」追不上「每层代价的衰减」，总代价由最上面一层决定。

**情形二：$d = \log_b a$（公比等于 1）**

每层代价都恰好是 $n^d$，一共有 $\log_b n$ 层，所以 $T(n) = O(n^d \log n)$。

**情形三：$d < \log_b a$（公比大于 1）**

越往下代价越大，求和被叶子层支配，$T(n) = O(a^{\log_b n}) = O(n^{\log_b a})$。直观上分治「变出子问题」的能力超过了每层省下的代价。

几个常用递推式按这三种情形对号入座：

| 递推式 | $a$ | $b$ | $d$ | 与 $\log_b a$ 的关系 | 结论 | 典型算法 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| $T(n)=2T(n/2)+O(n)$ | 2 | 2 | 1 | $d = \log_2 2 = 1$ | $O(n\log n)$ | 归并排序 |
| $T(n)=4T(n/2)+O(n)$ | 4 | 2 | 1 | $1 < \log_2 4 = 2$ | $O(n^2)$ | 朴素矩阵乘法 |
| $T(n)=7T(n/2)+O(n^2)$ | 7 | 2 | 2 | $2 < \log_2 7 \approx 2.807$ | $O(n^{\log_2 7})$ | Strassen |
| $T(n)=T(n/2)+O(1)$ | 1 | 2 | 0 | $0 = \log_2 1 = 0$ | $O(\log n)$ | 二分查找 |

### 主定理不适用的情形

主定理要求三个前提同时成立：每层子问题个数固定为 $a$、规模按固定比例 $b$ 缩小、本地代价是 $n$ 的多项式。三者任一不满足就不能套。

**$T(n) = T(n-1) + O(n)$**：$b = 1$，规模根本没有缩小，违反 $b > 1$。改用**完全展开**：

$$
T(n) = T(n-1) + n = T(n-2) + (n-1) + n = \cdots = \sum_{k=2}^{n} k + T(1) = \Theta(n^2)
$$

每次只剥掉一个元素，递归树退化成一条长为 $n$ 的链。同理 $T(n)=T(n-1)+O(1)$ 是 $\Theta(n)$，而不是主定理会让人误以为的 $O(1)$。

**$T(n) = T(\sqrt{n}) + O(n)$**：子问题规模不是 $n/b$ 的形式（这里「$b$」等于 $\sqrt n$，依赖 $n$ 本身），且 $a=1$。改用**代换法**：递归深度是 $\log_2 \log_2 n$，每层代价都是 $n$，故 $T(n) = O(n\log\log n)$。

**$T(n) = 2T(n/2) + O(n\log n)$**：本地代价 $n\log n$ 不是 $n$ 的多项式，直接套不了。改用 **Akra–Bazzi 定理**——主定理的推广，它把 $a,b,d$ 换成 $b_1,\ldots,b_k$ 和一个任意函数 $g(n)$，并要求解出 $p$ 使 $\sum_{i} a_i / b_i^{p} = 1$，然后

$$
T(n) = \Theta\left(n^{p}\left(1 + \int_{1}^{n} \frac{g(t)}{t^{p+1}}\,dt\right)\right)
$$

本例中 $2 \cdot (1/2)^p = 1$ 给出 $p=1$，$g(n)=n\log n$，于是

$$
T(n) = \Theta\left(n\left(1 + \int_{1}^{n} \frac{\log t}{t}\,dt\right)\right) = \Theta(n\log^{2} n)
$$

Akra–Bazzi 也能处理 $T(n) = T(n/4) + T(n/2) + O(n)$ 这类子问题个数不同、缩小比例不同的情况。

## 递归展开 unfolding 与代换法

**递归展开**（unfolding，又称 recursion tree）是把递推式按层拆开、直到触及 base case，然后逐层加回；**代换法**（substitution method）是猜一个上界再用数学归纳法证明它成立。两者配合使用：展开负责发现规律，代换负责把猜测变成定理。

以归并排序的递推式为例，展开时每一步都会多出一个常数倍：

$$
\begin{aligned}
T(n) &= 2T(n/2) + cn \\
&= 2\left(2T(n/4) + c\frac{n}{2}\right) + cn = 4T(n/4) + 2cn \\
&= 4\left(2T(n/8) + c\frac{n}{4}\right) + 2cn = 8T(n/8) + 3cn \\
&= \cdots \\
&= 2^{k}T(n/2^{k}) + kcn
\end{aligned}
$$

最后一式就是递归树的求和表达：$2^{k}$ 个节点、每个规模 $n/2^{k}$，本地代价共 $kcn$。取 $k = \log_2 n$ 让子问题触底，得到

$$
T(n) = n\,T(1) + cn\log_2 n = \Theta(n\log n)
$$

叶子层贡献 $O(n)$，内部各层合计贡献 $O(n\log n)$，后者是主导项。

**用代换法验证**。猜 $T(n) \le c' n\log_2 n$（这里用 $c'$ 避免与本地代价常数 $c$ 混淆），归纳假设对 $n/2$ 成立：

$$
T(n) = 2T(n/2) + cn \le 2\cdot c'\frac{n}{2}\log_2\frac{n}{2} + cn = c'n\log_2 n - c'n + cn
$$

只要 $c \le c'$，右端就 $\le c'n\log_2 n$，归纳闭合。上界成立。下界同理取 $T(n) \ge c''n\log_2 n$（要求 $c'' > 0$）即可证明，故 $T(n) = \Theta(n\log n)$。

递归展开退化成一条链时（每次只切掉常数个元素），展开式本身就已经给出了准确答案，不需要归纳法。

## 经典例题

### 归并排序 Merge Sort

递推式 $T(n) = 2T(n/2) + O(n)$：把 $n$ 个元素分成 $n/2$ 与 $n/2$ 两半各自排好，再线性合并。$a=b=2,\ d=1=\log_2 2$，落在情形二，$T(n) = \Theta(n\log n)$。递推式的 $O(n)$ 项就是 merge 的代价，而 merge 必须是线性的——一旦 merge 写成往有序数组里逐个插入，就退化成 $O(n^2)$，整个算法跟着变成 $O(n^2)$。排序的稳定性也来自 merge 时相等元素优先取左半。详见 [sort](/docs/CS/Algorithms/sort.md)。

### 二分查找 Binary Search

递推式 $T(n) = T(n/2) + O(1)$：$a=1,\ b=2,\ d=0=\log_2 1$，情形二，$T(n) = \Theta(\log n)$。

关键在于**每次比较都把候选集砍掉一半**，问题规模随递归深度以 2 为底衰减，深度是 $\log n$。如果每次只排除一个候选（如无序数组里的线性查找），规模只减少常数，深度是 $n$，复杂度就是 $\Theta(n)$——两者相差一个数量级，而这唯一的区别就是「规模按什么比例缩小」。二分的前提是数据已有序，否则「排除一半」这个动作根本无从判断。详见 [search](/docs/CS/Algorithms/search.md)。

### 快速排序 Quicksort

递推式依赖 pivot 的选择位置。最坏情况是每次 pivot 都取到最小（或最大）元素，退化成 $T(n)=T(n-1)+O(n)=\Theta(n^2)$。随机选 pivot 后期望递推式为

$$
E[T(n)] = \frac{2(n-1)}{n}E[T(n-1)] + O(n)
$$

期望解为 $O(n\log n)$，推导见 [Randomized](/docs/CS/Algorithms/Randomized.md)。

### Strassen 矩阵乘法

朴素做法把 $n\times n$ 矩阵分四块，块乘法共 $2^3=8$ 次，规模减半，$T(n)=8T(n/2)+O(n^2)$，得 $O(n^3)$。Strassen 重新安排那 18 次加减法，把块乘法降到 7 次：

$$
T(n) = 7T(n/2) + O(n^2)
$$

$d=2 < \log_2 7 \approx 2.807$，情形三，$T(n) = O(n^{\log_2 7}) \approx O(n^{2.807})$。它说明了主定理情形三的价值：指数由 $\log_b a$ 单独决定，与 $d$ 无关，所以哪怕多付出大量加法，只要能把块乘法次数从 8 压到 7，指数就真的降下来了。代价是常数极大，实际库实现仍以 BLAS/LAPACK 为主。

### 快速傅里叶变换 FFT

朴素多项式乘法是 $\Theta(n^2)$。分治把一个 $n$ 阶线性卷积拆成两个 $n/2$ 阶卷积，再借助单位根 $\omega = e^{2\pi i/n}$ 做旋转，把「多项式求值」这个整体问题拆成偶数次项、奇数次项两个半长问题，各自递归：

$$
T(n) = 2T(n/2) + O(n)
$$

$d=1=\log_2 2$，情形二，$T(n) = \Theta(n\log n)$，这是卷积能用于多项式乘法、循环卷积、大整数乘法的根基。蝶形网络共 $\log_2 n$ 层、每层 $O(n)$ 次运算，所以「$n\log n$」这个复杂度在实现上是**层数 × 每层宽度**的直观形状。

### 最近点对 Closest Pair

平面直角坐标系下求最近点对，暴力枚举是 $\Theta(n^2)$。分治做法：按 $x$ 坐标排序取中位数画分割线，递归求左右两侧的最近距离 $\delta$，再处理跨越分割线的点对。关键在于合并步只检查分割线两侧各 7 个点——把每侧 $2\delta$ 宽、$\delta$ 高的带状区域内的点按 $y$ 排序后做带状扫描，可证任一点的最近邻必落在常数个候选内（由「$\delta \times \delta$ 方框内不含其他点」的空圆论证得出）。

$$
T(n) = 2T(n/2) + O(n)
$$

合并步是 $O(n)$ 的扫描而非 $O(n^2)$ 的枚举，结果仍为 $\Theta(n\log n)$。这个例子的示范价值在于：**分治的收益往往不在递推式里，而在合并步的工程细节里**。

## 分治与动态规划的边界

分治和动态规划都是「把大问题拆成小问题再合并」，区别有三条可操作的判据。

**判据一：子问题是否重叠。** 分治成立的隐含前提是各子问题相互独立、不包含公共子问题，否则公共部分会被重复求解。斐波那契 $F(n)=F(n-1)+F(n-2)$ 是典型反例：两个子问题都依赖重叠的 $F(n-2)$，纯分治是 $O(\varphi^n)$，而加上记忆化（见 [DP](/docs/CS/Algorithms/DP/DP.md)）后是 $O(n)$。

**判据二：规模是否按固定比例缩小。** 分治要形成深度 $O(\log n)$ 的递归树，必须每次切掉固定比例。上面的 $T(n)=T(n-1)+O(n)$ 就因为只切掉一个元素而退化成深度 $O(n)$ 的链，此时应该考虑 DP（带记忆化）而不是硬套主定理。

**判据三：合并是否需要额外的状态。** 分治的合并是纯结构性的（把子问题的解拼起来），DP 则必须定义状态与转移方程，显式记录「到达同一状态的路径」的累积信息，因此 DP 额外需要一个状态表的空间开销 $O(\text{状态数})$。

一个实用口诀：**能用「规模减半」描述就优先想分治；发现同一个子问题被反复求解就想 DP。** 例如 0-1 背包若按物品做分治，容量维度会被反复重算，改成 DP 的 $O(n \cdot V)$ 才合适。同理，编辑距离的区间 DP、大量区间查询的稀疏表预处理，都是因为子问题重叠才必须走 DP 路线。

## 尾递归与主定理的关系

尾递归指递归调用是函数体的最后一步，返回后不再有其它计算。此时主定理的 $a=1$，递归树退化成一条链，层数等于规模本身——所以**尾递归不改变渐进复杂度**。

具体地说，$T(n) = T(n-1) + O(1)$ 是 $\Theta(n)$，把尾调用改写成循环后仍是 $\Theta(n)$，变的只是栈空间从 $O(n)$ 降到 $O(1)$。这一点对读代码很关键：看到递推式里的 $T(n-1)$ 不要指望它会自动变成 $O(1)$，能变的是空间，不是时间。

需要注意的是「尾递归 ⇒ 不改复杂度」并不等于「有尾递归就没有栈溢出风险」：C++ 标准并未对所有实现强制尾调用优化（GCC/Clang 通常在开启优化后能做，但 `-O0` 下不会），递归层数很大时仍可能爆栈；Python 干脆禁止尾递归优化。

## Links

- [数据结构](/docs/CS/Algorithms/Algorithms.md?id=数据结构)
- [复杂度分析](/docs/CS/Algorithms/Algorithms.md?id=复杂度分析)
- [Algorithms](/docs/CS/Algorithms/Algorithms.md)
- [Greedy](/docs/CS/Algorithms/Greedy.md)
- [Backtracking](/docs/CS/Algorithms/Backtracking.md)
- [Amortized Analysis](/docs/CS/Algorithms/Amortized.md)

## References

[OI Wiki 递归 & 分治](https://oi-wiki.org/basic/divide-and-conquer/)
[OI Wiki 动态规划部分简介](https://oi-wiki.org/dp/)
[Wikipedia — Divide and conquer algorithm](https://en.wikipedia.org/wiki/Divide_and_conquer)
[Wikipedia — Master theorem](https://en.wikipedia.org/wiki/Master_theorem)
[Wikipedia — Akra–Bazzi theorem](https://en.wikipedia.org/wiki/Akra%E2%80%93Bazzi_theorem)
[Wikipedia — Quicksort](https://en.wikipedia.org/wiki/Quicksort)
[Wikipedia — Strassen algorithm](https://en.wikipedia.org/wiki/Strassen_algorithm)
[Wikipedia — Fast Fourier transform](https://en.wikipedia.org/wiki/Fast_Fourier_transform)
[Thomas H. Cormen, Charles E. Leiserson, Ronald L. Rivest, Clifford Stein — Introduction to Algorithms (CLRS)](https://en.wikipedia.org/wiki/Introduction_to_Algorithms)
[Thomas H. Cormen, Sarit Halvorsen, Shmuel Winograd, Michael Molloy — The Design and Analysis of Algorithms](https://en.wikipedia.org/wiki/Design_and_Analysis_of_Algorithms)
