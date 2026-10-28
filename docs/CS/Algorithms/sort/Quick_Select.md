## Introduction

**选择问题**（selection problem）：给定 $n$ 个可比较元素，找出第 $k$ 小的元素（kth order statistic）。$k=1$ 是最小值，$k=n$ 是最大值，$k=\lceil n/2 \rceil$ 是中位数；「Top-K」（最大的 $k$ 个）也可以由选择问题拼接而来。

直觉上，选择比排序便宜：排序必须理清**全部**元素的相对次序，比较次数下界 $n\log n$；而选择只需要识别出「第 $k$ 个是谁」，大量元素之间谁大谁小无关紧要。这个直觉是对的——选择问题存在**线性时间**算法，且这正是「排序不是万物基础」的经典案例。

复杂度下界：比较模型下找出最大值至少要 $n-1$ 次比较；中位数的精确比较次数下界仍是活跃课题，已知落在 $2n \sim 3n$ 次之间。

## Quickselect

**快速选择**（Hoare, 1961）是快速排序的「只走一边」版本：

1. 任选一个 pivot，把数组划分成 `< pivot`、`= pivot`、`> pivot` 三部分；
2. 记 `<` 部分大小为 $s$。若 $k \le s$，答案在左半，只递归左半；若 $k > s + (\text{= 部分大小})$，只递归右半；否则 pivot 就是答案；
3. 每次划分把候选范围缩到一侧，与快速排序「两边都递归」形成关键区别。

复杂度：

- **平均 $O(n)$**：设第 $i$ 轮处理规模为 $n_i$，则 $n_{i+1}$ 的期望约为 $n_i$ 的一半量级（pivot 均匀落在各区间的概率相同），构成期望线性递减的几何级数，$\sum n_i = O(n)$；
- **最坏 $O(n^2)$**：每次 pivot 都取到极值（如已排序数组 + 固定取首元素）时，每轮只缩小 1 个元素；
- **随机化 pivot** 消除对输入顺序的依赖，任意输入下期望 $O(n)$，见 [Randomized](/docs/CS/Algorithms/paradigm/Randomized.md)。

实现要点与 [sort](/docs/CS/Algorithms/sort/sort.md) 的划分章节同源：Lomuto 划分写法简单但相等元素多次交换，Hoare 划分交换更少；**大量重复元素时用三路划分**（Dutch national flag），否则退化成平方级——这是快速选择与快速排序共同的最常见性能陷阱。

## Worst-Case Linear: BFPRT

**中位数的中位数**（median-of-medians，Blum, Floyd, Pratt, Rivest & Tarjan, 1973）给出了最坏情况 $O(n)$ 的保证：

1. 把 $n$ 个元素每 5 个一组，组内求中位数（常数次比较）；
2. 递归求这些中位数的中位数，记为 $m$；
3. 用 $m$ 作 pivot 划分。可以证明：$\ge 3n/10$ 个元素 $\le m$、$\ge 3n/10$ 个元素 $\ge m$，因此 $m$ 的排名落在 $[3n/10, 7n/10]$，两半都不可能太大；
4. 只在含答案的一侧递归。

递推式 $T(n) \le T(n/5) + T(7n/10) + O(n)$，由主定理的推广可解出 $T(n) = O(n)$。缺点是常数大、cache 不友好，实践中几乎不用它跑全程。

## In Practice

| 算法 | 平均 | 最坏 | 用途 |
| :-- | :-- | :-- | :-- |
| Quickselect | $O(n)$ | $O(n^2)$ | 默认选择 |
| 随机化 quickselect | $O(n)$（期望） | $O(n^2)$ | 消除输入依赖 |
| BFPRT | $O(n)$ | $O(n)$ | 理论保证 |
| Floyd–Rivest | 接近 $n$ 次比较 | 概率性 | 采样选 pivot，常数最小 |
| 堆（Top-K） | $O(n \log k)$ | $O(n \log k)$ | 流式/超大规模 |

- **Introselect**（Musser, 1997）：先用快速选择跑，递归深度超过阈值（如 $2\log n$）后退回 BFPRT，从而兼得线性平均与线性最坏。C++ `std::nth_element` 的主流实现即此方案；它只保证第 $k$ 个元素就位、不保证区间有序。
- **Top-K** 还有一条独立路线：维护一个大小为 $k$ 的小顶堆，扫过全表，比堆顶大就替换并下沉，复杂度 $O(n \log k)$。它不需要随机访问全表，适合**流式数据**与 $k \ll n$ 的场景；$k$ 接近 $n$ 时直接排序通常反而更快（常数优势）。堆细节见 [heap](/docs/CS/Algorithms/struct/heap.md)。
- **重复中位数/流式近似**：数据流中无法重扫时，用采样（reservoir sampling）估计分位数，见 [Randomized](/docs/CS/Algorithms/paradigm/Randomized.md)。

## Links

- [Sort](/docs/CS/Algorithms/sort/sort.md)
- [Heap](/docs/CS/Algorithms/struct/heap.md)
- [Randomized](/docs/CS/Algorithms/paradigm/Randomized.md)
- [Divide and Conquer](/docs/CS/Algorithms/paradigm/Divide-and-Conquer.md)
- [Algorithms](/docs/CS/Algorithms/Algorithms.md?id=classic-algorithm-topics)

## References

1. [快速选择 - OI Wiki](https://oi-wiki.org/basic/quick-select/)
2. [Time Bounds for Selection (Blum, Floyd, Pratt, Rivest, Tarjan, 1973)](https://people.csail.mit.edu/rivest/pubs/BFPRT73.pdf)
