## Introduction

许多最优化问题（如 TSP、顶点覆盖、集合覆盖、背包、最大独立集）是 NP-hard，在 P $\neq$ NP 假设下不存在多项式时间的精确算法。当精确解不可得，退而求其次追求**近似算法（approximation algorithm）**：在多项式时间内给出一个有*可证明质量保证*的解，而不是盲目启发式。

本页是「最优化」问题形态下「近似」这一支的枢纽；它与 [Greedy](/docs/CS/Algorithms/paradigm/Greedy.md)、[Dynamic Programming](/docs/CS/Algorithms/DP/DP.md)、[Linear Programming](/docs/CS/Algorithms/Linear_Programming.md) 关系密切——大量近似方案正是贪心、DP 或 LP 取整。

## Approximation Ratio

对最小化问题，算法 $\mathcal{A}$ 是 **$\alpha$-近似**（$\alpha\ge 1$）若对所有实例 $\sigma$ 有：

```tex
ALG(σ) ≤ α · OPT(σ)
```

最大化问题则要求 $ALG(\sigma)\ge \alpha\cdot OPT(\sigma)$（$0<\alpha\le 1$）。$\alpha$ 叫**近似比（approximation ratio）**，衡量最坏情况下与最优解的最大差距。$\alpha=1$ 即精确算法。

## PTAS and FPTAS

- **PTAS（Polynomial-Time Approximation Scheme）**：对每个固定 $\varepsilon>0$，存在 $(1+\varepsilon)$-近似算法，其时间对 $n$ 是多项式，但 $\varepsilon$ 出现在指数位（如 $O(n^{1/\varepsilon})$）。
- **FPTAS（Fully PTAS）**：时间同时是 $n$ 与 $1/\varepsilon$ 的多项式，如 $O(n^2/\varepsilon)$。这是近似里最强的保证，背包问题即有一例。

## Classic Examples

| 问题 | 近似比 | 思路 |
| :-- | :-- | :-- |
| 顶点覆盖（Vertex Cover） | $2$ | 每条边任取一端；对偶是最大匹配 |
| 集合覆盖（Set Cover） | $\ln n$ | 每轮选"覆盖最多未覆盖元素"的集合（贪心）；下界 $\ln n$ 除非 NP $\subseteq$ DTIME |
| 度量 TSP（Metric TSP） | $2$ | 求 MST $\to$ 前序遍历翻倍 $\to$  shortcuts（三角不等式保证不更差） |
| 背包（Knapsack） | $1+\varepsilon$（FPTAS） | 先解 LP 松弛，再对价值缩放 + DP |

## Hardness of Approximation

近似也存在下界：某些问题在 P $\neq$ NP 下**不存在常数近似**（如最大团 Maximum Clique），或近似比受特定假设限制（如标号覆盖 Unique Games 假设）。这类"不可近似性"与计算复杂性深度交织。

## Links

- [Randomized Algorithms](/docs/CS/Algorithms/paradigm/Randomized.md)
- [Algorithms](/docs/CS/Algorithms/Algorithms.md)
- [Mathematics](/docs/Mathematics/Mathematics.md)

## References

1. Cormen, T. H. et al. *Introduction to Algorithms* (3rd ed.), Ch. 35.
2. Williamson, D. P. & Shmoys, D. B. *The Design of Approximation Algorithms*.
3. Vazirani, V. V. *Approximation Algorithms*.
