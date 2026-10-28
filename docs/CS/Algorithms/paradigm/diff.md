## Introduction

对于源文本 A 和目标文本 B，我们一定可以通过不断执行删除行和插入行两种操作，使得 A 转化成 B，这样的一系列插入和删除操作的序列就被称作编辑脚本

文本差分算法，可以定义为用于求出输入源文本和目标文本之间的编辑脚本的算法，广泛运用于各种需要进行文本对比的地方



如何评估一个文件差分算法

编辑脚本长度 求最短编辑长度(SES Shortest Edit Script) 长度越短越好

类似于多次求最长公共子序列(不唯一)

可读性 尽可能地保留整段文本 删除和插入操作减少交叉 同时通常删除操作在插入前面



git diff 的实现里，其实就内置有多个不同的 diff 算法

git diff 默认算法：Myers 差分算法

## The Myers Diff Algorithm

Myers 差分（1986）解决的问题是：**在 $O(ND)$ 时间内求出最短编辑脚本**，其中 $N$、$M$ 是两文件行数，$D$ 是最短编辑脚本的长度。朴素动态规划求 LCS 是 $O(NM)$；而 Myers 的关键观察是——两个相似文件的 $D$ 通常很小，此时 $O(ND)$ 接近线性，这正是版本控制场景（同源文件的小改动）的典型分布。

### The Edit Graph

把问题搬到一张有向图上：横轴 $x$ 是文件 A 的行号（$0 \dots N$），纵轴 $y$ 是文件 B 的行号（$0 \dots M$）。

- 向右一步 = 从 A 删除一行；
- 向下一步 = 向 B 插入一行；
- 对角线一步 = 两行相同（匹配），不产生编辑代价。

每条边权为 1（对角线为 0），于是**最短编辑脚本 = 从 $(0,0)$ 到 $(N,M)$ 的最短路径**，删除+插入的总步数即路径上的非对角步数。设 LCS 长度为 $L$，则 $D = N + M - 2L$——删除 LCS 之外 A 的 $N-L$ 行、插入 B 的 $M-L$ 行即可。

### D-Paths and the Greedy Core

Myers 不直接求 LCS，而是对 $D = 0, 1, 2, \dots$ 逐轮搜索**最远可达的 D-path**（恰好含 $D$ 条非对角边的路径）：

- $D=0$：从 $(0,0)$ 出发沿对角线尽可能远地走（这一段不耗步数的连续匹配称为 **snake**）；
- $D=k$：由 $D=k-1$ 的每个最远点各走一步（删除或插入），再沿对角线贪心走到底；
- 只需要记录每条对角线 $k = x - y$ 上的最远 $x$ 坐标（一个数组 $V$），每轮工作量 $O(D)$。

当某轮的路径越过终点 $(N,M)$ 时即得到最短脚本。总复杂度 $O(ND)$，最坏 $O(NM)$（两文件毫不相干时），但只要文件相似就接近线性——这是 Myers 论文标题 *An O(ND) Difference Algorithm* 的含义。

### Linear Space Refinement

上述算法要保存每一轮的最远点，空间 $O(D^2)$。Myers 论文的变体部分用**分治**把它压到 $O(N+M)$：先正向、反向各搜到中间相遇，确定穿过中点的「中间 snake」，把它作为分割点，对上下两半递归求子脚本。这与 LCS 的 Hirschberg 线性空间算法同源，也是 git 的 xdiff 库实际采用的方案。

### Diff Variants in Git

| 算法 | 思路 | 特点 |
| :-- | :-- | :-- |
| `myers`（默认） | 上述 O(ND) 最短脚本 | 保证编辑脚本最短；但「最短」不等于「最像人写的」 |
| `patience` | 先在两边都只出现一次的行里找锚点，分段递归 | 对代码块移动、大段重排更稳，diff 更贴近人类直觉 |
| `histogram` | patience + 出现频次淘汰机制（低重复行优先作锚） | patience 的改进版，工业代码库上效果更好 |
| `minimal` | Myers 的加强版，付出更长时间换更短脚本 | 与默认 myers 差异通常很小 |

无论哪种算法，最后都会做一次 **hunk 边界滑动**：把匹配的公共行在「删除块」与「插入块」之间左右挪，让改动看起来更成组（Myers 原文即讨论了这种可读性权衡）。

## Links

- [复杂度分析](/docs/CS/Algorithms/Algorithms.md?id=algorithm-analysis)
- [Divide and Conquer](/docs/CS/Algorithms/paradigm/Divide-and-Conquer.md)

## References

1. [An O(ND) Difference Algorithm and Its Variations (Myers, Algorithmica)](https://doi.org/10.1007/BF01840446)
2. [git-diff - Git 官方文档](https://git-scm.com/docs/git-diff)
3. [The Myers Diff Algorithm, Part 1 (James Coglan)](https://blog.jcoglan.com/2017/02/12/the-myers-diff-algorithm-part-1/)
4. [The Myers Diff Algorithm, Part 2 (James Coglan)](https://blog.jcoglan.com/2017/02/15/the-myers-diff-algorithm-part-2/)
