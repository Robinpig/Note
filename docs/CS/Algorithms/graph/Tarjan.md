## Introduction

**Tarjan 算法**不是一个具体问题，而是解决「图的连通性」一族问题的**统一技术**：只跑**一次 DFS**，配合 `dfn`（访问次序）与 `low`（子树能回溯到的最早祖先）两个数组和一个栈，就能同时求出有向图的**强连通分量**、无向图的**割点**与**桥**，乃至 LCA 的离线解法。

它之所以能一箭双雕，靠的是 DFS 的**递归调用栈天然是嵌套的**：函数调用尚未返回时，其访问的顶点都还在「路径上」。这个嵌套结构正好编码了「谁能到达谁」的信息——`low` 值记录的就是「这棵子树的最深回溯能到多早的祖先」。

前置知识是 [graph](/docs/CS/Algorithms/graph/graph.md) 中的 DFS 与邻接表表示。

## Two Core Arrays
对每个顶点 $u$：

- `dfn[u]`：$u$ 在 DFS 中**首次被访问**的时间戳（全图唯一、严格递增）。
- `low[u]`：$u$ 及其 DFS 子树内的顶点，通过**树边向下**再通过**至多一条非树边**（指回祖先的边），所能到达的**最小 `dfn` 值**。

`low` 的转移是 Tarjan 的全部精髓。遍历 $u$ 的邻接点 $v$ 时：

- 若 $v$ 未访问：递归 DFS $v$ 之后，`low[u] = min(low[u], low[v])`——$v$ 的子树能回溯到的最深处，$u$ 也能享受。
- 若 $v$ 已访问且 $v \ne$ 父节点（**有向图中此处不排除任何已访问点**）：`low[u] = min(low[u], dfn[v])`——直接走到 $v$ 所在的位置。

初值 `low[u] = dfn[u]`。整个算法是 $O(V+E)$ 的，因为每个顶点、每条边只被处理常数次。

## Strongly Connected Components (SCC)
适用于**有向图**。在 DFS 过程中把「已访问但尚未归入某个 SCC」的顶点压入一个**栈**（注意：是无向图判割点时那个栈的翻版，用 `inStack` 标记）。

当遍历到 $u$ 时若发现 `low[u] == dfn[u]`，说明 $u$ 是其所在分量的「根」——此时把栈中顶点**弹出到 $u$ 为止**，这些顶点与 $u$ 共同构成一个强连通分量：

```
for each vertex u in V:
    if dfn[u] == 0:
        tarjan(u)

tarjan(u):
    dfn[u] = low[u] = ++timer
    S.push(u); inStack[u] = true
    for each neighbor v of u:
        if dfn[v] == 0:            // 未访问
            tarjan(v)
            low[u] = min(low[u], low[v])
        else if inStack[v]:        // 已访问且在栈中 → 指向栈内顶点
            low[u] = min(low[u], dfn[v])
    if low[u] == dfn[u]:          // u 是 SCC 根
        repeat:
            w = S.pop()
            inStack[w] = false
            add w to current SCC
        until w == u
```

这里 `inStack` 的条件是关键区别：若写成 `else if (已访问)`（不判 `inStack`），会把「指向已完成分量」的交叉边也算进来，得到错误的分量划分。

**性质与用途**：缩点后必然得到一张 DAG。强连通分量等价关系是**传递的**，因此可以缩点；许多有向图问题（「最少加几条边使图强连通」「缩点后求 DAG 最短路」）都以此为前提。

## Articulation Points and Bridges
适用于**无向图**。沿用 `dfn`/`low`，但不维护栈，直接用 `low` 做判断：

- **桥（cut edge）**：$u$ 与 DFS 子节点 $v$ 之间满足 `low[v] > dfn[u]`。含义是 $v$ 的子树**完全无法**回溯到 $u$ 或其祖先，因此这条边是连接两部分的唯一通道。欧拉图判定要求所有顶点度数为偶数，而**图中存在桥就不可能有欧拉回路**（可借 Tarjan 一并判断）。
- **割点（articulation point）**：非根顶点 $u$ 存在子节点 $v$ 满足 `low[v] >= dfn[u]` 时，$u$ 是割点；**DFS 根节点**则是「有至少两个子节点」即为割点（一条边无法分隔，故用 `>=` 而非 `>` 的差别正体现在根节点需单独判定）。

区分 `>` 与 `>=` 是这两个判定的全部差别所在：桥用严格大于（回溯不到 $u$ 本身），割点用大于等于（回不到 $u$ 之上，但能回到 $u$ 也已经断了——因为到 $u$ 的边正是要删的那条）。

现实意义：割点与桥就是网络中的**单点故障**与**单链路故障**，容灾设计、链路聚合、BFD 协议检测邻居链路失效，都在用同一套判定。

## Offline LCA
同一套 `dfn`/`low` 还能解决「多次询问最近公共祖先」：把询问挂在两个端点上，DFS 回溯时用并查集合并已访问的顶点，使 `find(x)` 始终返回 $x$ 所在集合中深度最小的那个顶点——DFS 刚离开的节点 $u$ 与 $v$ 的 LCA 正是 `find(v)`。

复杂度 $O((V + Q)\alpha(V))$，适合询问量大而图不变的场景；若询问在线且图会变化，则该用倍增 $O(\log V)$ 或树链剖分 $O(\log V)$。

## Implementation Notes
- **无向图必须判父节点**：跳过父亲，否则每条树边都会被当成回边，`low` 恒等于 `dfn`，桥与割点全部误判。
- **有向图不判父节点**：这是与无向图最本质的差别。
- 用**迭代写法**替代递归可避免深图爆栈，此时需要显式维护「当前顶点 + 邻接表游标」的栈帧来模拟递归返回时机。
- `dfn` 用全局递增计时器即可，无需墙钟时间。

## Links

- [graph](/docs/CS/Algorithms/graph/graph.md)
- [Union Find](/docs/CS/Algorithms/tree/Disjoint_Set.md)
- [Eulerian Graph](/docs/CS/Algorithms/graph/Eulerian_Graph.md)

## References

1. [强连通分量 - OI Wiki](https://oi-wiki.org/graph/scc/)
2. [割点 - OI Wiki](https://oi-wiki.org/graph/cut/)
3. [最近公共祖先 - OI Wiki](https://oi-wiki.org/graph/lca/)