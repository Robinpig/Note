## Introduction

A randomized algorithm is an algorithm that employs a degree of randomness as part of its logic or procedure. 
The algorithm typically uses uniformly random "Uniform distribution (discrete)") bits as an auxiliary input to guide its behavior,
in the hope of achieving good performance in the "average case" over all possible choices of random determined by the random bits;
thus either the running time, or the output (or both) are random variables.

There is a distinction between algorithms that use the random input so that they always terminate with the correct answer, 
but where the expected running time is finite (Las Vegas algorithms, for example Quicksort), and algorithms which have a chance of producing an incorrect result 
(Monte Carlo algorithms, for example the Monte Carlo algorithm for the MFAS problem) or fail to produce a result either by signaling a failure or failing to terminate. 
In some cases, probabilistic algorithms are the only practical means of solving a problem.

In common practice, randomized algorithms are approximated using a pseudorandom number generator in place of a true source of random bits;
such an implementation may deviate from the expected theoretical behavior and mathematical guarantees which may depend on the existence of an ideal true random number generator.


## 两类随机化算法的判据

两类随机化算法的分界线不在于「用没用随机数」，而在于随机性落在哪里：只落在**运行时间**上，还是也落在**输出结果**上。

| 维度 | Las Vegas 算法 | Monte Carlo 算法 |
| :--- | :--- | :--- |
| 随机性的作用 | 仅影响运行时间 | 运行时间与输出结果都是随机变量 |
| 是否必然终止 | 是，一定终止并给出正确结果 | 可能给出错误结果，也可能报告失败 |
| 结果正确性 | 永远正确 | 单侧错误，概率可控 |
| 错误概率 | 恒为 $0$ | 可设计为 $p \le 1/2$、$1/3$ 等常数 |
| 复杂度保证 | 期望复杂度有限，但最坏情况可退化 | 单次运行复杂度确定，错误概率有界 |
| 典型代表 | Quicksort（随机 pivot）、Cuckoo Hashing | Miller–Rabin 素性测试、Freivalds 矩阵验证 |

两者的取舍很直接：Las Vegas 把不确定性全部压在时间维度上，答案可信但最坏情况可能很慢（随机 pivot 的 Quicksort 最坏仍是 $\Theta(n^2)$）；Monte Carlo 用极小的概率换取确定的运行时间，工程上更常用。

## 随机化为什么有用

### 规避对抗性输入

确定性算法的最坏情况一旦被构造出来就固定存在，而随机化算法让「最坏情况」这件事失去意义——攻击者无法针对一个连自己都不知道的随机种子做优化。

以 Quicksort 为例。若固定取第一个元素作 pivot，攻击者只要预先构造一个「升序数组」，每次划分都极度不平衡，递推式退化为 $T(n)=T(n-1)+O(n)=\Theta(n^2)$。改用均匀随机 pivot 后，期望递推式是

$$
E[T(n)] = \frac{2(n-1)}{n}E[T(n-1)] + O(n)
$$

解得 $E[T(n)] = O(n\log n)$。关键在于随机性保证了**任意固定输入**的期望代价都是 $O(n\log n)$，输入再刁难也无用——这是确定性算法给不了的保证。

### 用空间换时间

哈希表是这一思路的极致：用 $O(n)$ 空间把查找从 $O(n)$ 降到期望 $O(1)$。更进一步，「随机哈希 + 近似」这一族结构干脆放弃精确性，用远小于精确结构的常驻空间换取可接受的误差：

- [BloomFilter](/docs/CS/Algorithms/struct/BloomFilter.md)：用 $m$ 个 bit 的位数组加 $k$ 个哈希函数判断「元素是否可能存在」，有假阳性（说存在实际不存在）但无假阴性，空间只需 $O(n \log(1/\delta))$ bit。
- [HyperLogLog](/docs/CS/Algorithms/HyperLogLog.md)：用极小空间估计基数（distinct 元素个数），标准误差约 $1.04/\sqrt{m}$，把「精确去重计数」压缩成近似估计。
- Count-Min Sketch 一类的结构用多个哈希桶计数器估计频次，代价是单侧高估。

这类结构牺牲了确定性答案，换来的是在流式数据、海量去重、指标聚合场景下确定性算法根本无法承受的空间开销——精确去重要 $O(n)$ 内存且必须存全量数据，近似结构只要常数大小的计数器。

### 用概率突破确定性算法的规模极限

有些问题的确定性算法是 $O(n^3)$ 甚至更差，但只需一个常数概率的近似答案就足以支撑决策。素性测试就是最好的例子：确定性 Miller–Rabin 需要完整的乘法同态结构而代价高昂，随机化版本只需对底数做 $O(k\log n)$ 的模幂运算，重复几轮就能把错误率压到任意小。这类场景下概率化不是「更快的近似」，而是**唯一可行的工程方案**。

## 期望复杂度分析

### Quicksort 的期望递推

随机选 pivot 时，pivot 落在下标 $k$ 上的概率是 $1/n$，左右两边的规模分别是 $k-1$ 和 $n-k$：

$$
E[T(n)] = \frac{1}{n}\sum_{k=1}^{n}\left(E[T(k-1)] + E[T(n-k)]\right) + O(n) = \frac{2(n-1)}{n}E[T(n-1)] + O(n)
$$

求解这个非齐次递推的技巧是**消去系数**：令 $F(n) = E[T(n)] / (n-1)$（对 $n \ge 2$），代入后 $E[T(n-1)]$ 的系数恰好被约掉，得到

$$
F(n) = F(n-1) + \frac{O(n)}{n-1}
$$

于是 $E[T(n)] = O\left(n\sum_{k=2}^{n}\frac{1}{k-1}\right) = O(n\log n)$。

**每一层代价的直观解释**可以用指示变量。设 $X_{j,k}$ 表示下标为 $j$ 的元素在第 $k$ 层是否还在参与划分。第 $k$ 层有 $2^k$ 个子问题，但每个元素在每一层只会被计入一次，所以第 $k$ 层的总代价不超过 $O(n)$；而深度为 $\log n$（期望意义下），两者相乘即得 $O(n\log n)$。

另一个更精细的视角是看最大元素：每个元素被选作 pivot 的次数期望为 $O(1)$，而每次划分一个规模为 $m$ 的子问题代价是 $O(m)$。当 pivot 是子问题最大元素时，该子问题立即结束——最大元素作为 pivot 的概率恰为 $1/m$，这一项贡献是 $O(m) \cdot \frac{1}{m} = O(1)$，可与 $O(m)$ 的划分成本合并计算，不改变量级。

### 哈希表期望 $O(1)$ 的由来

设负载因子 $\alpha = n/m$（$n$ 个元素、$m$ 个槽位）。在**均匀散列**（universal hashing）假设下，任何两个不同键落在同一槽的概率是 $1/m$；这保证了链长度的期望是 $\alpha$ 而非 $n$。

查找失败时，期望只需检查 $1 + \alpha$ 个结点（链表期望长度 $\alpha$ 加上最坏遍历到链尾）；查找成功时只需检查 $1 + \alpha/2$ 个。因此：

$$
E[\text{查找代价}] = O(1 + \alpha)
$$

只要维持 $\alpha = O(1)$（即 $m = \Theta(n)$，装填因子保持常数），期望代价就是 $O(1)$。这个结论的两个前提都要强调：**均匀散列**（否则构造性输入可以让所有键碰撞，退化到 $O(n)$）与**常数负载因子**（否则 $\alpha$ 增长会线性劣化）。

均匀性要求本身也不是自动满足的——朴素地取 `hash(k) = k % m` 时，攻击者只要构造 $k, k+m, k+2m, \ldots$ 就让所有键落入同一槽。这也是[随机化哈希](/docs/CS/Algorithms/hash.md)的意义所在。

## 概率放大 error amplification

Monte Carlo 算法的错误率通常设计成 $p$（常数，如 $1/2$）。若单次错误率偏大，**独立重复 $k$ 次**会把总错误率降到 $p^{k}$——因为只有每次都错才会整体错，这个乘法关系正是独立性的直接结果。

要让总错误率不超过 $\delta$，取

$$
k = O\left(\log \frac{1}{\delta}\right)
$$

就够。一个实用推论是：**置信度的提升是对数代价的**。从 $50\%$ 提到 $99.9\%$ 需要常数次重复，但从 $99.9\%$ 提到 $99.9999999\%$ 只需要再乘几倍——想用重复次数换指数级的置信度增益不现实，这也解释了为什么工程上更常用「随机选一个底数 + 多轮验证」而不是无限加轮数。

### Freivalds 矩阵乘法验证

验证矩阵乘积 $AB = C$ 的直接做法是算出 $AB$ 再逐项比较，代价 $O(n^3)$。Freivalds 的思路是引入随机向量 $r \in \{0,1\}^n$ 检验

$$
A(Br) \stackrel{?}{=} Cr
$$

矩阵乘向量是 $O(n^2)$，两次共 $O(n^2)$——但关键在于**若 $AB = C$ 必然通过，若 $AB \ne C$ 则只有常数概率通过**。

错误概率界来自一个反证：设 $D = AB - C \ne 0$，取 $D$ 的某个非零元素 $D_{ij}$，选定 $r_j = 1$ 后，$D_{ij}$ 贡献的偏移量无法被其余各行抵消（否则那一行全零，与 $D_{ij} \ne 0$ 矛盾）。所以 $(Dr)_i \ne 0$ 的概率至少是 $1/2$，故

$$
\Pr[ABr = Cr] \le \frac{1}{2}
$$

重复 $k$ 次独立验证，全通过才判定正确，单侧错误概率至多 $2^{-k}$。取 $k=3$ 时错误率降到 $1/8$；需要 $2^{-32}$ 量级的置信度时取 $k=32$。这个方法的价值在于它把验证代价从 $O(n^3)$ 降到了 $O(n^2)$，代价只是把确定性保证换成高置信度——这类「方向性错误」（只会说相等、不会谎报不相等）让它特别适合做一致性校验。

## 随机数来源的工程问题

理论上随机化算法假设有一个理想的均匀随机位源，工程中用 PRNG（伪随机数生成器）替代，这一步引入了与算法正确性无关的**实现风险**。

主要问题有三类：

1. **序列会重复**。PRNG 是确定性的，状态空间有限，输出必然周期化。周期内的比特相关性可能非随机；经典反例是线性同余发生器（LCG）的低位比特周期极短，直接取模使用会得到肉眼可见的规律（时间戳作种子的 `rand()` 就栽在这里）。
2. **种子可预测**。攻击者一旦猜到或反推出种子，就能预知全部随机选择，从而构造出针对具体实现的对抗输入——这正好抵消了随机化「规避对抗输入」的初衷。参见[哈希表退化攻击](/docs/CS/Algorithms/hash.md)一节。
3. **统计性质不等于独立均匀**。仅通过 $\chi^2$ 一类的统计检验并不能保证高维相关性符合理论假设，而算法的期望复杂度推导依赖的正是严格独立均匀。

因此**安全场景必须用 CSPRNG**（密码学安全随机数发生器），如 `/dev/urandom`、ChaCha20、以及各语言标准库提供的加密级随机源；哈希表散列、密码学 nonce、协议中的随机字段都应走这条路。判断标准很实际：**这个随机数会不会被攻击者观测或反推？** 会，就换 CSPRNG；只是用来打乱自己数据的顺序，普通 PRNG 才够用。

## 常见的误用

**把「随机化」当成「复杂度一定更低」。** 随机化是**降低某个维度**的代价，不是全维度下界。随机 Quicksort 的期望 $O(n\log n)$ 完全正确，但最坏情况仍是 $\Theta(n^2)$，不比确定性版本更差；Monte Carlo 素性测试再快，输出的也不是精确答案。评估随机化算法时必须同时问：期望代价是多少、最坏代价是多少、错误概率多大——三者要分别报告。

**用固定种子冒充均匀分布。** 这是理论与实现之间最容易踩的坑。理论分析中「随机选取」隐含了「独立均匀」这个前提，把它写死成 `srand(42)` 或固定哈希种子后，所有理论保证都随之失效：得到的只有一个样本点，不构成对期望的估计。模拟实验里用固定种子求可复现性是可以的，但那是实验方法学，和算法的正确性保证是两回事。

**只跑一次就宣称高置信。** 单次错误率 $p$ 的算法跑一次，只得到 $p$ 这一级别的可靠性。想要 $1-\delta$ 的置信度必须显式重复 $k \approx \log(1/\delta)$ 次；Miller–Rabin 只跑一轮就宣称结果正确，本质上就是把 $50\%$ 的错误率当成了 $0$。另外，重复验证要求各轮**真正独立**——复用同一个随机向量不构成独立重复，错误率不会按 $p^k$ 衰减。

**混淆有放回抽样与无放回抽样。** 有放回（independent sampling with replacement）下重复抽到同一元素的概率不可忽略，样本量的有效值小于名义值；无放回（without replacement）保证样本互异。估计总量的经典公式在两种抽样下的无偏因子不同：放回抽样用 $\frac{n}{1}$ 修正，不放回抽样用 $\frac{n}{n-1}$ 修正，混用会带来系统性偏差（finite population correction）。设计抽样方案时必须先确认抽样框是否允许重复。

**误以为 Las Vegas 一定快。** Las Vegas 保证结果正确、期望时间有限，但**期望有限不等于有上界**——随机 pivot 的 Quicksort 最坏仍是 $\Theta(n^2)$。Cuckoo Hashing 也一样：插入可能失败需要重试，换哈希函数才终止。在实时系统或有硬 deadline 的场景下，「大概率很快」是不够的。

## Links

- [数据结构](/docs/CS/Algorithms/Algorithms.md?id=数据结构)
- [复杂度分析](/docs/CS/Algorithms/Algorithms.md?id=复杂度分析)
- [Algorithms](/docs/CS/Algorithms/Algorithms.md)
- [Sort](/docs/CS/Algorithms/sort.md)
- [DP](/docs/CS/Algorithms/DP/DP.md)
- [Divide and Conquer](/docs/CS/Algorithms/Divide-and-Conquer.md)

## References

[OI Wiki 递归 & 分治](https://oi-wiki.org/basic/divide-and-conquer/)
[OI Wiki 动态规划部分简介](https://oi-wiki.org/dp/)
[Wikipedia — Randomized algorithm](https://en.wikipedia.org/wiki/Randomized_algorithm)
[Wikipedia — Quicksort](https://en.wikipedia.org/wiki/Quicksort)
[Wikipedia — Miller–Rabin primality test](https://en.wikipedia.org/wiki/Miller%E2%80%93Rabin_algorithm)
[Wikipedia — Freivalds' algorithm](https://en.wikipedia.org/wiki/Freivalds%27_algorithm)
[Wikipedia — Cuckoo hashing](https://en.wikipedia.org/wiki/Cuckoo_hashing)
[Wikipedia — Bloom filter](https://en.wikipedia.org/wiki/Bloom_filter)
[Wikipedia — HyperLogLog](https://en.wikipedia.org/wiki/HyperLogLog)
[Wikipedia — Count–min sketch](https://en.wikipedia.org/wiki/Count%E2%80%93min_sketch)
[Wikipedia — Mersenne Twister](https://en.wikipedia.org/wiki/Mersenne_Twister)
[MIT 6.006 Introduction to Algorithms](https://ocw.mit.edu/courses/6-006-introduction-to-algorithms-fall-2011/)
[Thomas H. Cormen, Charles E. Leiserson, Ronald L. Rivest, Clifford Stein — Introduction to Algorithms (CLRS)](https://en.wikipedia.org/wiki/Introduction_to_algorithms)
