## Introduction

我们学过的算法几乎都是**多项式时间算法**：输入规模为 $n$ 时，最坏运行时间 $O(n^k)$（$k$ 为常数）。多项式时间被视为**可解（tractable）**，超多项式时间被视为**难解（intractable）**。但「可解」的边界到底画在哪里，并不是显然的事——有些问题原则上不可计算（停机问题），有些问题可计算但没有人知道是否存在多项式算法。

复杂性理论回答的正是这个问题：把判定问题按「需要多少资源」分层。核心类是 **P** 与 **NP**，而连接两者的 **P vs NP 问题**自 1971 年提出至今未解，是 Clay 数学研究所七个千禧年大奖难题之一（悬赏一百万美元）。

判定问题（decision problem）的输入实例回答「是/否」；优化问题（如最短路径长度、最小顶点覆盖）通常可改写成等价的判定问题（「是否存在长度 ≤ L 的路径」），因此以下讨论都以判定问题为准。

## The Classes

- **P**：存在确定性算法在多项式时间内求解的判定问题。排序、最短路径、最小生成树、二分图匹配、线性规划都在 P。
- **NP**（nondeterministic polynomial time）：解可以在多项式时间内**验证**的问题。等价地，可用非确定性图灵机在多项式时间内「猜出并验证」一个解。所有 P 问题都在 NP 中（猜不需要，直接验证即可）。
- **co-NP**：补问题在 NP 中的问题。例如「该公式不可满足」（UNSAT）是 coNP-complete。
- **NP-hard**：至少和 NP 中最难的问题一样难——每个 NP 问题都能多项式归约到它。NP-hard 问题不一定在 NP 中（甚至不一定是判定问题）。
- **NP-complete**：既在 NP 中、又是 NP-hard 的问题。它是 NP 类里「最难的一档」：其中任何一个找到多项式算法，整个 NP 就都塌进 P。

形式化的图灵机定义、Church-Turing 论题与停机问题的对角线证明，见 [Computability](/docs/CS/Algorithms/Computability.md)。

## Reductions and the Cook-Levin Theorem

把问题 A 归约到问题 B（$A \le_p B$）指：给出一个多项式时间的转换，把 A 的每个实例变成 B 的实例，使答案保持一致。于是「B 容易 ⇒ A 容易」，反过来说「B 难 ⇒ A 至少一样难」。归约是复杂性理论的比较工具，也是后续所有 NP-complete 结论的证明方式。

- **Cook-Levin 定理**（Cook 1971，Levin 1973 独立证明）：布尔可满足性问题 **SAT 是 NP-complete**。这是第一个被证明 NP-complete 的问题——证明不靠归约，而是直接论证「任何非确定性图灵机的计算过程都可以编码成一个布尔公式」。
- **Karp 1972** 沿着这条思路给出 **21 个 NP-complete 问题**（团、顶点覆盖、哈密顿回路、3-染色、划分问题……），奠定了整个学科。此后已知的 NP-complete 问题数以千计。

常见问题归类：

| 问题 | 类别 |
| :-- | :-- |
| 2-SAT | P（SCC 判定，每步 $O(n+m)$） |
| SAT / 3-SAT | NP-complete |
| 最短路径、MST | P |
| 哈密顿路径 / 哈密顿回路 | NP-complete |
| 团（Clique）、顶点覆盖（Vertex Cover） | NP-complete |
| 图 3-染色 | NP-complete |
| 子集和（Subset Sum） | NP-complete（伪多项式 DP，见 [DP](/docs/CS/Algorithms/DP/DP.md)） |
| 旅行商问题（判定版） | NP-complete；优化版 NP-hard |
| 整数线性规划 | NP-hard（0-1 变量时 NP-complete） |
| 停机问题 | 不可判定（比 NP 更难） |

## Class Inclusions

已知的包含链（是否真包含是开放问题）：

$$
\text{P} \subseteq \text{NP} \subseteq \text{PSPACE} \subseteq \text{EXPTIME}
$$

- $\text{P} \ne \text{EXPTIME}$ 可由**时间层级定理**证明，因此链上至少有一处严格包含，但不知道是哪处。
- **Savitch 定理**：$\text{NPSPACE} = \text{PSPACE}$，即空间上非确定性不增加能力。
- 主流猜想 $\text{P} \ne \text{NP}$：数千个 NP-complete 问题被研究了数十年，无一找到多项式算法；但证明本身极端困难，现有技术（对角化、自然证明屏障）都被认为不足以解决它。

## What to Do With NP-hard Problems

判定了 NP-hard 不等于放弃。工程上按精度需求分四条路线：

1. **精确算法**：回溯 + 强剪枝、分支限界、整数规划求解器。现代 CDCL SAT 求解器能处理工业界百万变量级的实例——「指数最坏情况」与「实例上跑不动」是两件事。
2. **近似算法**：牺牲最优性换多项式时间。如度量 TSP 的 Christofides 算法近似比 $3/2$；顶点覆盖的极大匹配近似比 $2$；集合覆盖的贪心近似比 $O(\ln n)$。反过来，**PCP 定理**给出不可近似性下界（例如一般 TSP 不存在任意常数的多项式近似，除非 P = NP）。
3. **参数化算法**：复杂度写成 $f(k) \cdot n^{O(1)}$，其中 $k$ 是小参数。如顶点覆盖的 $O(2^k \cdot n)$ FPT 算法——$k$ 小时完全可用。
4. **启发式与局部搜索**：模拟退火、遗传算法、禁忌搜索等，不保证最优与时间上界，但对大规模实例常能快速给出够用的解，见 [Randomized](/docs/CS/Algorithms/paradigm/Randomized.md)。

## Links

- [Algorithms](/docs/CS/Algorithms/Algorithms.md)
- [Computability](/docs/CS/Algorithms/Computability.md)
- [Dynamic Programming](/docs/CS/Algorithms/DP/DP.md)
- [Backtracking](/docs/CS/Algorithms/paradigm/Backtracking.md)

## References

1. [P vs NP Problem - Clay Mathematics Institute](https://www.claymath.org/millennium/p-vs-np/)
2. [Complexity Zoo](https://complexityzoo.net/Complexity_Zoo)
3. [Theory of Computation, MIT OpenCourseWare 18.404J](https://ocw.mit.edu/courses/18-404j-theory-of-computation-fall-2020/)
