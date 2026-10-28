## Introduction

在线算法（Online Algorithm）面对**逐步到达**的输入：每到一个请求必须即时决策，且无法预知未来。这与离线算法（已知全部输入）和随机化算法（已知分布）都不同——在线算法工作在最严苛的*对抗*模型下。

本页承接 [Algorithms in Systems](/docs/CS/Algorithms/Algorithms.md) 里 `systems/` 子目录的缓存与定时器主题（[LRU](/docs/CS/Algorithms/systems/LRU.md)、[The_Five_Minute_Rule](/docs/CS/Algorithms/systems/The_Five_Minute_Rule.md)、[TimingWheel](/docs/CS/Algorithms/systems/TimingWheel.md)），把"系统里的近似最优决策"上升到统一的竞争分析框架。

## Competitive Analysis

在线算法的黄金标准是**竞争比（competitive ratio）**。设算法 $\mathcal{A}$ 在输入序列 $\sigma$ 上的代价为 $\mathcal{A}(\sigma)$，最优离线算法为 $OPT(\sigma)$（已知全部未来），则 $\mathcal{A}$ 是 **$c$-竞争**（$c\ge 1$）若：

```tex
∀σ:  A(σ) ≤ c · OPT(σ) + b      （确定性）
```

对随机化算法，右边换成 $\mathbb{E}[A(\sigma)]$。$c$ 越小越好；$c=1$ 即离线最优。竞争分析用"最坏情况对抗"替代分布假设，给出与输入无关的可证明界。

## Classic Problems

- **Paging / 缓存替换**：内存 $k$ 页、发生缺页时须淘汰一页。任意确定性算法最坏竞争比 $k$；**LRU 与 FIFO 均为 $k/(k-1)$-竞争**，而 **Markov 算法（marking）可达最优的 $k$-竞争**（Sleator & Tarjan, 1985）。
- **k-server 问题**：$k$ 个服务器在度量空间中移动服务请求，最小化总移动距离；$(2k-1)$-竞争算法已知，=$k$ 是否为下界仍是著名 open problem。
- **负载均衡（List Scheduling）**：贪心把任务分给当前最轻机，竞争比 $2-1/m$；结合排序可得 $4/3-1/(3m)$。
- **滑雪租赁（Ski-Rental）**：租 $1$ 或买 $B$，最优确定性竞争比 $B/(B-1)\approx 2$ 的"租到第 $B$ 次再买"策略。

## Adversarial vs Stochastic

纯对抗模型有时过于悲观。实际系统常混合**随机化竞争分析**（对手不知随机种子）与**平均/平滑分析**（Smoothed Analysis），以更贴近真实负载——这与 [Randomized](/docs/CS/Algorithms/paradigm/Randomized.md) 的视角互补。

## Links

- [Algorithms](/docs/CS/Algorithms/Algorithms.md)
- [Mathematics](/docs/Mathematics/Mathematics.md)

## References

1. Borodin, A. & El-Yaniv, R. *Online Computation and Competitive Analysis*.
2. Sleator, D. D. & Tarjan, R. E. *Amortized Efficiency of List Update and Paging Rules*, CACM 1985.
3. Albers, S. *Online Algorithms: A Survey*, MFCS 2003.
