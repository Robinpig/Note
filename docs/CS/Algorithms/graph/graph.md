## Introduction

图（graph）是一种非线性数据结构，由顶点（vertex）和边（edge）组成。我们可以将图 G 抽象地表示为一组顶点 V 和一组边 E 的集合

常用 `G=(V,E)` 表示图

### 图分类

根据边是否具有方向，可分为无向图（undirected graph）和有向图（directed graph

- 在无向图中，边表示两顶点之间的“双向”连接关系，例如微信或 QQ 中的“好友关系”。
- 在有向图中，边具有方向性，即 A→B 和 A←B 两个方向的边是相互独立的，例如微博或抖音上的“关注”与“被关注”关系



根据所有顶点是否连通，可分为连通图（connected graph）和非连通图（disconnected graph）对于连通图，从某个顶点出发，可以到达其余任意顶点

可以为边添加“权重”变量，从而得到如图 9-4 所示的有权图（weighted graph）



### 图结构

图数据结构包含以下常用术语

- 邻接（adjacency）：当两顶点之间存在边相连时，称这两顶点“邻接”。在图 9-4 中，顶点 1 的邻接顶点为顶点 2、3、5。
- 路径（path）：从顶点 A 到顶点 B 经过的边构成的序列被称为从 A 到 B 的“路径”。在图 9-4 中，边序列 1-5-2-4 是顶点 1 到顶点 4 的一条路径。
- 度（degree）：一个顶点拥有的边数。对于有向图，入度（in-degree）表示有多少条边指向该顶点，出度（out-degree）表示有多少条边从该顶点指出





图的常用表示方式包括“邻接矩阵”和“邻接表”

邻接矩阵

设图的顶点数量为 n ，邻接矩阵（adjacency matrix）使用一个 n×n 大小的矩阵来表示图，每一行（列）代表一个顶点，矩阵元素代表边，用 1 或 0 表示两个顶点之间是否存在边

邻接矩阵具有以下特性。

- 在简单图中，顶点不能与自身相连，此时邻接矩阵主对角线元素没有意义。
- 对于无向图，两个方向的边等价，此时邻接矩阵关于主对角线对称。
- 将邻接矩阵的元素从 1 和 0 替换为权重，则可表示有权图。

使用邻接矩阵表示图时，我们可以直接访问矩阵元素以获取边，因此增删查改操作的效率很高，时间复杂度均为 O(1) 。然而，矩阵的空间复杂度为 O(n2) ，内存占用较多



邻接表（adjacency list）使用 n 个链表来表示图，链表节点表示顶点。第 i 个链表对应顶点 i ，其中存储了该顶点的所有邻接顶点（与该顶点相连的顶点）



邻接表仅存储实际存在的边，而边的总数通常远小于 n2 ，因此它更加节省空间。然而，在邻接表中需要通过遍历链表来查找边，因此其时间效率不如邻接矩阵。

邻接表结构与哈希表中的“链式地址”非常相似，因此我们也可以采用类似的方法来优化效率。比如当链表较长时，可以将链表转化为 AVL 树或红黑树，从而将时间效率从 $O(n)$ 优化至 $O(log⁡n)$ ；还可以把链表转换为哈希表，从而将时间复杂度降至 $O(1) $



## Basic Ops

图的基础操作可分为对“边”的操作和对“顶点”的操作

- 添加/删除边
- 添加/删除顶点

在“邻接矩阵”和“邻接表”两种表示方法下，实现方式有所不同









## Representation of Graphs

One simple way to represent a graph is to use a two-dimensional array. This is known as an *adjacency* *matrix* representation.

If the graph is  *sparse* , a better solution is an *adjacency list* representation. For each vertex, we keep a list of all adjacent vertices. The space requirement is then  *O|E| + |* V|).

## Topological Sort

## Shortest-Path Algorithms

### Unweighted Shortest Paths

### Dijkstra's Algorithm



Dijkstra 算法是用于计算一个顶点到其它顶点的最短路径算法 

基本思想是: 设置两个顶点集 S 和 T, S 中存放已确定最短路径的顶点, T 中存放待确定最短路径的顶点

初始时 S 中仅有一个起始的节点, T 中包含除起始顶点之外的其余顶点



Dijkstra 是一种贪心算法 每一步都做出局部最优的选择 最终达到全局最优的结果 该算法只适用于权重非负的图 
如果图中包含负权重的边 Dijkstra 可能无法正确计算最短路径 在包含负权重的情况下 通常使用 `Bellman-Ford` 算法



```c++
class Solution {
    public:
    int networkDelayTime(vector<vector<int>>& times, int n, int k) {
        // 标记未被探索的节点距离
        const int inf = INT
        _
        MAX / 2;
        // 邻接表
        vector<vector<int>> g(n, vector<int>(n, inf));
        // 构图
        for (auto time: times) {
        g[time[0] - 1][time[1] - 1] = time[2];
        }
        vector<int> dist(n, inf); // 所有节点未被探索时距离都初始化为无穷
        vector<bool> used(n, false); // 标记是否已经被加入树中
        dist[k - 1] = 0; // 记录原点距离为0
        for (int i = 0; i < n; ++i) {
        int x = -1;
        // 找出候选集中到S距离最短的节点
        for (int y = 0; y < n; ++y) {
            if (!used[y] && (x == -1 || dist[y] < dist[x])) {
            x = y;
            }
            }
            // 加入树中
            used[x] = true;
            // 基于x 对所有x的邻节点进行松弛操作
            for (int y = 0; y < n; ++y) {
                dist[y] = min(dist[y], dist[x] + g[x][y]);
            }
        }
        // 取出最短路中的最大值
        int ans = *max

        element(dist.begin(), dist.end());
        return ans == inf ? -1 : ans;
    }
};
```

Dijkstra 算法是逐步构建最短路径树，树中的节点的最短距离不依赖于树外节点，这样才可以一个节点加入最短路径树之后，距离不再改变。负权节点的存在会让加入最短路径树的节点的真实最短路径会因为不在树中的节点而改变，整个算法也就无效了


动态路由算法中基于 Dijkstra 算法的链路状态算法，核心思路就是通过节点间的通信，获得每个节点到邻居的链路成本信息，进而在每个节点里都各自独立地绘制出全局路由图，之后就可以基于Dijkstra 算法构建出路由表了

#### Bellman-Ford

和 Dijkstra 用到的贪心思想不同，Bellman-Ford 算法采用的是动态规划的思想

Bellman-Ford 的整体时间复杂度是 $O(V*E)$，大部分实际场景下，边的数量比节点数量大的多，所以时间复杂度要比 Dijkstra 算法差很多。当然好处在于可以处理图中有负边的情况



全点对最短路径算法用于计算图中所有顶点两两之间的最短路径 常见算法有 `Floyd-Warshall` 算法和 `Jonson's` 算法

`Floyd-Warshall` 算法适用于稠密图 时间复杂度为 $O(V^3)$ 核心思想为动态规划

`Jonson's` 算法适用于稀疏图 时间复杂度近似为 $O(V^3logV+VE)$ 是Dijkstra算法的变种 利用重新加权的技巧 允许在可能存在负权重边的图上使用 Dijkstra 算法





## Minimum Spanning Tree

最小生成树



中心性算法



用于衡量图中顶点重要程度和影响力的算法



## Links

- [data structures](/docs/CS/Algorithms/Algorithms.md?id=data-structures)
- [algorithm analysis](/docs/CS/Algorithms/Algorithms.md?id=algorithm-analysis)
