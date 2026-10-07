## Introduction

这里讨论的是**组合博弈中的搜索算法**（algorithmic / combinatorial game theory），面向**零和、有限、确定性、信息完全**的双人对弈
（zero-sum finite deterministic perfect-information game），如井字棋、国际象棋、围棋。它与经济学意义上的
[博弈论](/docs/Economics/Game_Theory.md)（纳什均衡、策略式/扩展式博弈）侧重点不同：这里的核心是「在巨大的对弈树中高效选出最优着法」。

对弈被建模为一棵**博弈树（game tree）**：节点是局面，边是着法，双方轮流在 MAX 层（最大化己方收益）与 MIN 层（最小化对手收益）间切换。
目标是在搜索深度有限、局面数随深度指数爆炸的前提下，仍能近似找到最优解。

## Minimax
基础是 **Minimax**：自底向上对每个局面估值

- MAX 节点取子节点最大值，MIN 节点取子节点最小值；
- 叶节点用评估函数（evaluation function）打分；
- 完整搜索整棵树可得到最优策略，但分支因子 b、深度 d 时节点数为 O(b^d)，实际只能搜有限深度。

```
function minimax(node, depth, maximizing):
    if depth == 0 or terminal(node): return eval(node)
    if maximizing: return max(minimax(c, depth-1, false) for c in children)
    else:          return min(minimax(c, depth-1, true)  for c in children)
```

## Alpha-Beta Pruning
**α-β 剪枝**在不改变 Minimax 结果的前提下剪掉不可能影响决策的分支：

- α：当前 MAX 层已能保证的最好值（下界）；β：当前 MIN 层已能保证的最坏值（上界）；
- 一旦发现某子树使 **α ≥ β**，对手机关一定不会让局面走到这里，立即剪枝（beta cutoff / alpha cutoff）。

```
function alphabeta(node, depth, α, β, maximizing):
    if depth == 0 or terminal: return eval(node)
    if maximizing:
        for c in children:
            α = max(α, alphabeta(c, depth-1, α, β, false))
            if α >= β: break        # beta cut
        return α
    else:
        for c in children:
            β = min(β, alphabeta(c, depth-1, α, β, true))
            if α >= β: break        # alpha cut
        return β
```

剪枝本身不损失精确性，但效果依赖着法顺序——先搜「看起来好」的着法能更早触发剪枝；理想着法顺序下可访问约 O(b^(d/2)) 个节点，等效搜索深度翻倍。
常见增强：迭代加深（iterative deepening）、置换表（transposition table，本质是局面哈希缓存）、杀手着法/历史启发（move ordering）、quiescence search（静止期搜索，缓解水平线效应）。

## Principal Variation Search (PVS)
Principal Variation Search（PVS / NegaScout）在 α-β 基础上进一步假设：「上一着法仍是最佳着法，其余着法只会更差」。

- 先用完整窗口搜第一个（预期最佳）子节点，得到主变（principal variation）的值；
- 对后续子节点先用一个**零宽窗口（null window，α 与 β 仅差 1）**快速探测它是否可能超过当前最佳；
- 若空窗搜索证明它更差，就白赚一次便宜剪枝；若它其实更好（fail-high），再用完整窗口重搜（research）。

着法排序准确时 PVS 比朴素 α-β 节点更少；排序差、频繁 fail-high 重搜时优势缩小。

## Monte Carlo Tree Search
当**没有好的评估函数**（如围棋，局面难以静态估值）或分支因子极大时，转向 **MCTS（蒙特卡洛树搜索）**：不靠人工估值，而用大量随机模拟（rollout/playout）的胜率近似局面价值。每轮迭代四步：

1. **Selection**：从根沿树用选择策略下行（经典用 UCT）；
2. **Expansion**：在叶节点展开一个或多个子节点；
3. **Simulation**：从该节点随机/按策略快速模拟到终局；
4. **Backpropagation**：把胜负结果沿路径回传，更新每个节点的访问次数 N 与累计收益 W。

MCTS 是**任意时间算法（anytime）**：随时停止都能给出当前最优着法，时间越多越强；且价值由模拟得出，不依赖领域评估函数。

## UCT
UCB Apply to Trees（**UCT**）是 Selection 阶段平衡「利用与探索」的策略，对节点的子节点 c 取使下式最大者：

```
UCB1 = (W_c / N_c) + C · sqrt( ln(N_parent) / N_c )
        └── 平均胜率：利用 ──┘   └── 访问越少项越大：探索 ──┘
```

- 第一项偏好历史胜率高的子节点（exploitation）；
- 第二项给访问次数少的子节点加分（exploration），C 控制探索强度；
- 这保证在采样足够多时每个分支都会被探索，同时资源向高收益分支集中。AlphaGo/AlphaZero 用策略网络先验与价值网络替换纯随机 rollout，但树搜索骨架仍是 MCTS + PUCT（结合策略先验的 UCT）。

## Links

- [Algorithms](/docs/CS/Algorithms/Algorithms.md)
- [Game Theory (Economics)](/docs/Economics/Game_Theory.md)
- [Randomized Algorithms](/docs/CS/Algorithms/Randomized.md) — MCTS 依赖随机模拟
- [NP](/docs/CS/Algorithms/NP.md) — 大规模博弈树搜索的复杂度背景

## References

1. [A Survey of Monte Carlo Tree Search Methods](https://ieeexplore.ieee.org/document/6145622)
2. [Alpha-Beta Pruning - Wikipedia](https://en.wikipedia.org/wiki/Alpha%E2%80%93beta_pruning)
3. [Mastering the Game of Go with Deep Neural Networks and Tree Search](https://www.nature.com/articles/nature16961)
