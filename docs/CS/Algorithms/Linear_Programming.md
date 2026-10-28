## Introduction

线性规划（Linear Programming, LP）研究在线性等式 / 不等式约束下极小化或极大化一个线性目标函数的问题。它是「最优化」问题形态里少有的、能在多项式时间内精确求解的大类，也是近似算法、网络流、博弈论等诸多算法的理论基座。

一个 LP 实例由 $m$ 个约束、$n$ 个决策变量组成：

```tex
maximize    cᵀx
subject to  Ax ≤ b,  x ≥ 0
```

其中 $A\in\mathbb{R}^{m\times n}$、$\mathbf{b}\in\mathbb{R}^m$、$\mathbf{c}\in\mathbb{R}^n$。可行域是 $n$ 维空间中的一个（可能为空、可能有界的）凸多面体；因为目标函数线性，**最优解若存在，必在某个极点（vertex）取到**——这是单纯形法可行性的根本依据。

## Standard Form and Simplex

任意 LP 都可规约为**标准形式**（全为等式约束、变量非负）：对 $x_j$ 无符号限制时拆成 $x_j^+-x_j^-$；对 $\le$ 约束引入松弛变量，对 $\ge$ 约束引入剩余变量加人工变量（两阶段法或大 M 法）。

单纯形法（Simplex）从多面体一个极点出发，沿使目标改善的边走到相邻极点，直到无改善方向：

- 用 **Bland 规则（总选下标最小的进 / 出基变量）** 可避免循环（cycling），保证有限步终止。
- 最坏时间复杂度是指数级（Klee–Minty 立方体构造），但实践中极快，是商业求解器（CPLEX、Gurobi、GLPK）的主力。
- 进基变量选择（Dantzig 最负 reduced cost 规则）决定实际效率；退化（degenerate）情况下可能多次访问同一极点。

## Duality

每个 LP（原问题 P）都有唯一的**对偶问题（D）**，二者系数互译：P 的约束对应 D 的变量，P 的目标系数变成 D 的右端。三条核心结论：

- **弱对偶定理**：任意可行解 $\mathbf{x},\mathbf{y}$ 满足 $\mathbf{c}^\top\mathbf{x}\le\mathbf{b}^\top\mathbf{y}$，因此 P 的最大值 $\le$ D 的最小值。
- **强对偶定理**：若 P 有有界最优解，则 D 也有，且二者最优值相等（LP 强对偶恒成立，不像某些整数规划）。
- **互补松弛性（complementary slackness）**：最优解处，一侧约束严格不等 $\Rightarrow$ 另一侧对应变量为 0；是构造性证明与算法设计的利器。

一个常被忽视的事实：**最大流最小割定理是线性规划强对偶的特例**——把最大流写成 LP，其对偶正是最小割，见 [Network_Flow](/docs/CS/Algorithms/graph/Network_Flow.md)。

## Interior Point Methods

1979 年 Khachiyan 用椭球法证明 LP $\in$ P；1984 年 Karmarkar 提出**内点法**，在多项式时间 $O(n^{3.5}L)$（$L$ 为输入位数长）内求解，且大规模稀疏问题上常优于单纯形。内点法沿可行域*内部*朝最优面逼近，与单纯形沿边界走形成互补；现代求解器多采用「单纯形 + 内点」双引擎。

## Integer Programming and Relaxation

当变量被限定为整数（ILP / MILP），问题一般变为 NP-hard。常用手法：

- **LP 松弛（relaxation）**：放宽整数约束求 LP 上 / 下界，再分支定界（branch and bound）或割平面（cutting plane）。
- **整合到近似算法**：许多 NP-hard 最小化问题的近似方案先解 LP 松弛，再*取整*得到可行解并证明近似比，见 [Approximate](/docs/CS/Algorithms/Approximate.md)。

## Links

- [Algorithmic Game Theory](/docs/CS/Algorithms/Algorithmic_Game_Theory.md)
- [Algorithms](/docs/CS/Algorithms/Algorithms.md)
- [Mathematics](/docs/Mathematics/Mathematics.md)

## References

1. Cormen, T. H. et al. *Introduction to Algorithms* (3rd ed.), Ch. 29.
2. Bertsimas, D. & Tsitsiklis, J. N. *Introduction to Linear Optimization*.
3. Vanderbei, R. J. *Linear Programming: Foundations and Extensions*.
