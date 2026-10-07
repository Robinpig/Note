## Introduction

**图论（graph theory）** 是数学的一个分支，图是它的主要研究对象。图（*graph*）是一种非线性数据结构，由顶点（vertex）与边（edge）组成，通常写作二元组 $G = (V, E)$，其中 $V$ 是非空顶点集。与顶点 $v$ 关联的边数称为该顶点的**度**（degree），记作 $d(v)$；特别地，自环 $(v,v)$ 对 $d(v)$ 贡献 2。在有向图中，以 $v$ 为起点的边数称为**出度** $d^+(v)$，以 $v$ 为终点的边数称为**入度** $d^-(v)$，显然 $d^+(v) + d^-(v) = d(v)$。

图论的力量在于它是大量现实系统的**共同骨架**：社交关系、路由表、任务依赖、状态机跳转、引用关系，都可以抽象成「顶点 + 边」再问一个结构性问题。本页是算法域中图论部分的枢纽，先讲图的表示与遍历这两块地基，再按「连通性 → 路径 → 树 → 二分图 → 流」递进，最后收中心性这类分析型算法。

## Graph Classification
按**边是否有方向**：

- **无向图**（undirected graph）：边表示双向连接，如微信/QQ 的好友关系。
- **有向图**（directed graph）：$A \to B$ 与 $A \leftarrow B$ 两条边相互独立，如微博的「关注 / 被关注」。

按**连通性**：

- **连通图**：从某顶点出发可到达其余任意顶点；否则为**非连通图**，其连通分量数为 $c$。

按**边是否带权**：给边附加权重变量即得**有权图**（weighted graph），路径的长度按权值累加而非按边数。

其他重要类型：**有向无环图（DAG）** 无有向环，是拓扑排序的前提；**树**是无环连通图；**完全图**中任意两顶点间均有边。

## Graph Representation
两种标准表示法，各有适用区间。

### Adjacency List
邻接表用 $n$ 个链表表示图，第 $i$ 个链表对应顶点 $i$，存储其所有邻接顶点。空间复杂度 $O(|V| + |E|)$，**只存实际存在的边**，因此在稀疏图（$|E| \ll |V|^2$）上远比邻接矩阵紧凑，是通常的选择。

代价是查边需要遍历链表，效率不如邻接矩阵。其结构与哈希表的「链式地址」高度相似，所以同样有优化手段：链表较长时可转为 AVL 树或红黑树，把查边从 $O(n)$ 降到 $O(\log n)$；链表很短时甚至可直接转哈希表降到 $O(1)$。

### Adjacency Matrix
邻接矩阵用 $n \times n$ 矩阵表示图，每行（列）对应一个顶点，元素表示边是否存在（无向图则关于主对角线对称；简单图中主对角线无意义；把 0/1 换成权值即表示有权图）。

特点是**增删查改均为 $O(1)$**——可直接按下标访问，代价是空间 $O(n^2)$。因此它适用于两种场景：稠密图（$|E|$ 接近 $|V|^2$），或需要频繁判断「任意两点是否相邻」的操作（如 Floyd、图的传递闭包）。

经验分工：**稀疏图用邻接表，稠密图或需 $O(1)$ 判边用邻接矩阵**。

### Basic Operations
图的基础操作分为对边的操作与对顶点的操作（添加/删除边、添加/删除顶点），在两种表示法下实现方式不同：邻接表加边是往链表头插结点（$O(1)$），删边需先定位（$O(\deg)$）；邻接矩阵则直接改矩阵元素。

## Traversal
图的搜索是系统化地跟随边访问每个顶点。**图的搜索技巧是整个图算法领域的核心**——多数图算法都先通过搜索获取图的结构，另一些则是对基本搜索的优化。

### BFS

广度优先搜索按层扩展：先访问距离起点 1 的所有顶点，再访问距离 2 的……用**队列**实现。

其最重要性质是：**无权图上 BFS 的访问顺序即最短距离顺序**——顶点 $v$ 首次被访问时的层数就是 $d(s,v)$。因此一遍 BFS 即可求出单源最短路，复杂度 $O(V+E)$。反过来说，「BFS 在无权图上就是最短路算法」不是巧合，而是层数即距离的直接推论。

BFS 还可用于求连通分量、以及判断二分图（见下）。

### DFS

深度优先搜索沿一条路径走到底再回溯，用**递归**或显式栈实现，复杂度同为 $O(V+E)$。

DFS 比 BFS 更擅长「沿结构走到底」的问题：环检测、连通分量、割点桥、强连通分量（Tarjan 系列）几乎都建立在 DFS 之上——原因是 DFS 会为每个顶点形成一个**嵌套的递归调用栈**，这个栈结构天然编码了「谁能到达谁」的信息，而 BFS 的队列是平的、不携带这种层级关系。

实现上有两点值得留意：一是**递归深度可能达到 $V$**，在深图上有爆栈风险，需改用显式栈的迭代版；二是无向图的 DFS 只需判断「邻接点是否为已访问的**父节点**」，而非简单跳过所有已访问点。

### Cycle Detection and Topological Sort
无向图判环：DFS 中若遇到一个**已访问且不是父节点**的邻接点，即存在环。有向图判环稍复杂：需区分「指向已完成的顶点」（交叉边，成环）与「指向栈中顶点」（回边，成环），最简单的判法是直接做一次拓扑排序，若输出的顶点数少于 $V$ 则有环。

拓扑排序只适用于**有向无环图（DAG）**：把顶点排成线性序列，使任意有向边 $u \to v$ 中 $u$ 都排在 $v$ 之前。它等价于在 DAG 上求一个**线性扩展**，实现是反复从入度为 0 的顶点中任选一个输出并删除其出边，复杂度 $O(V+E)$；若某步找不到入度为 0 的顶点，说明剩余部分含环。基于它还能求 AOE 网络的**关键路径**，即决定项目总工期的最长依赖链——详见 [Topological Sort](/docs/CS/Algorithms/graph/Topological_Sort.md)。

## Connectivity: SCC, Articulation Points and Bridges
这一族问题共享同一个技术内核：**Tarjan 算法**，用一次 DFS + `dfn`/`low` 两个数组 + 一个栈同时解决。详见 [Tarjan](/docs/CS/Algorithms/graph/Tarjan.md)。

- **强连通分量（SCC）**：有向图中「互相可达」的顶点极大集合。缩点后必为 DAG，这是许多有向图问题（如「最少加几条边使其强连通」）的前提。
- **割点（articulation point）**：删掉它会使连通分量数增加的无向图顶点。它对应现实系统中的单点故障。
- **桥（cut edge）**：删掉它会使连通分量数增加的无向图边，等价于二分图中跨越两个连通块的边。

判定均基于 `low` 值与栈：SCC 用强连通分量栈，割点桥用「子树能否回到祖先」的 `low` 值比较。

## Path Problems
### Shortest Paths
- **无权图**：BFS，$O(V+E)$。
- **非负权图**：Dijkstra（贪心 + 优先队列，$O((V+E)\log V)$）。BFS 把「固定步长 1」换成「按累计权值取最小」，即得 Dijkstra——它本质是 BFS 在带权图上的推广。
- **存在负权边**：Bellman-Ford 逐轮松弛，$O(VE)$，并借最后一次松弛是否仍在发生来判断**负环**；Johnson 算法用势函数把带负权图转成非负权从而套用 Dijkstra（$O(V^2\log V + VE)$）。
- **所有点对最短路**：Floyd-Warshall，$O(V^3)$，基于「中转点」枚举的 $k$ 层 DP。

Dijkstra、A*、Johnson 与负环判定的完整推导见 [Shortest-Path](/docs/CS/Algorithms/question/Shortest-Path.md)。

### Eulerian Circuits
欧拉路径（Eulerian path）是经过每条边**恰好一次**的路径，回到起点则为欧拉回路（Eulerian circuit）。连通图中三个条件等价：存在欧拉回路 / 所有顶点度数为偶数 / 可分解为若干不共边回路的并；存在欧拉路径的条件是恰有 0 个或 2 个奇度顶点。判定与构造见 [Eulerian Graph](/docs/CS/Algorithms/graph/Eulerian_Graph.md)。

## Trees and Spanning Trees
### Minimum Spanning Tree
无向连通图中边权和最小的生成树称为**最小生成树**（*minimum spanning tree, MST*）。它一定恰有 $n-1$ 条边、连通且无环，且**形态可能不唯一但权值唯一**，同时还是「瓶颈最小」的：对任意两点，MST 上连接它们的路径是所有路径中最大边权最小的那个。

求解有两个互补的贪心算法：**Kruskal** 把全部边按权值升序扫一遍、用并查集拒绝成环，$O(E\log E)$；**Prim** 从任一顶点出发、每轮取当前割 $(S, V-S)$ 上权值最小的跨割边，用堆做到 $O(E\log V)$、用邻接矩阵做到 $O(V^2)$。二者正确性都归结为**割性质**与**环性质**，工程上因此有「稠密图用 Prim、稀疏图用 Kruskal」的经验分工。详见 [Minimum Spanning Tree](/docs/CS/Algorithms/graph/Minimum_Spanning_Tree.md)。

### Directed Trees and Arborescences
有向图上的生成树有两个方向：指向根的**内向树**（in-arborescence）与背离根的外向树（out-arborescence）。最小内向树即 Edmonds 算法所求，是最小生成树在有向图上的推广——有向图上不再有「割性质」的简单形式，朴素做法（按边权排序后忽略成环边）并不正确。

## Bipartite Graphs
**二分图**（bipartite graph）指顶点可二染色使每条边两端异色的图，等价于**不含奇环**的图。判定极简：对图做一次 BFS/DFS 染色，若相邻顶点同色则不是二分图。

它的价值在于**两侧可二分**这个性质把匹配问题变成结构化的可解问题，也天然对应现实中的「资源-需求」「账户-交易」双边市场。核心问题是**二分图匹配**（最大匹配、增广路、匈牙利算法、Hopcroft-Karp），详见 [Matching](/docs/CS/Algorithms/graph/Matching.md)；由 König 定理，最大匹配数等于最小点覆盖数，由此衍生出「用最少点覆盖所有边」的一类应用。

## Network Flow
把「容量」引入边、把「守恒」引入顶点，就得到网络流模型。它把许多看起来无关的问题——「最小割」「最大匹配」「最小费用调度」——统一成一个「求最大流」的子问题，而最大流又有高效的组合算法（Dinic 等）。这是图论中抽象能力最强的一支，详见 [Network Flow](/docs/CS/Algorithms/Network_Flow.md)。

## Centrality Algorithms
用于衡量图中顶点重要程度和影响力的算法：

- **度中心性（degree centrality）**：直接取顶点的度数。最简单也最粗糙：无法区分「连到很多边缘顶点」和「连到很多枢纽顶点」，因此在星形图上会把所有叶子判为同等重要。
- **介数中心性（betweenness centrality）**：顶点 $v$ 的介数定义为所有「最短路经过 $v$」的顶点对 $(s,t)$ 所占的比例。衡量「**必经之路**」式的控制力，适合刻画交易撮合节点、跨社群桥梁，但朴素计算需枚举所有点对并跑单源最短路，代价高昂。
- **接近中心性（closeness centrality）**：以 $v$ 到其它所有顶点最短距离之和的倒数衡量，$C(v) = \frac{n-1}{\sum_{u \ne v} d(v,u)}$。偏好「处在网络中心」而非「连接众多邻居」的节点，但遇到孤立点或极端枢纽会被不可达顶点严重干扰，实践中常用 **Wasserman–Faust 归一化**修正。
- **特征向量中心性（eigenvector centrality）**：令邻接矩阵为 $A$，取其**主特征向量**的分量作为各顶点分数，即解 $Ax = \lambda_{\max} x$。关键洞察是只有与「度大」的顶点相连才能获得高 centrality，因此天然偏好**连接枢纽的枢纽**，弥补了度中心性的短板。

**PageRank 本质上就是带转移概率矩阵的特征向量中心性**：把网页看作顶点、超链接看作有向边，在其转移概率矩阵上求主特征向量（主特征值为 1），各分量即全网重要性排序。这也解释了 PageRank 与 eigenscore 共享的「链接投票」直觉，以及 PageRank 能捕捉度中心性与介数中心性都抓不到的结构——一个被高 centrality 站点链接的普通页面，排名会随之上升。详见 [PageRank](/docs/CS/Algorithms/PageRank.md)。

## Links

- [数据结构](/docs/CS/Algorithms/Algorithms.md?id=data-structures)
- [复杂度分析](/docs/CS/Algorithms/Algorithms.md?id=algorithm-analysis)
- [Tarjan](/docs/CS/Algorithms/graph/Tarjan.md)
- [Matching](/docs/CS/Algorithms/graph/Matching.md)
- [Network Flow](/docs/CS/Algorithms/Network_Flow.md)
- [Eulerian Graph](/docs/CS/Algorithms/graph/Eulerian_Graph.md)
- [Shortest Path](/docs/CS/Algorithms/question/Shortest-Path.md)

## References

1. [图论相关概念 - OI Wiki](https://oi-wiki.org/graph/concept/)
2. [图的遍历 - OI Wiki](https://oi-wiki.org/graph/bfs/)
3. [强连通分量 - OI Wiki](https://oi-wiki.org/graph/scc/)
4. [拓扑排序 - OI Wiki](https://oi-wiki.org/graph/topo/)
5. [最小生成树 - OI Wiki](https://oi-wiki.org/graph/mst/)