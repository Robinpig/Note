## Introduction

搜索问题



## Binary Search

二分搜索适用于有序数组 相比于线性查找 可以在每次查询时成倍缩小查询范围 将时间复杂度降低到 $O(logN)$

Kafka 的 索引文件



## BFS and DFS

常见的暴力搜索方式主要有 BFS 和 DFS 两种 无差别地去遍历搜索空间的每一种情况

BFS 是从源点向外逐层推进 没遍历一层都需要使用上一层的节点 所以需要使用一个容器存储上一层的元素用来依次遍历 通常是使用一个FIFO的队列

这样的方式适合于树的层序遍历 如果有特殊的搜索退出条件 例如最短路径问题时 并不需要遍历所有的路径

对元素判重复能防止重复的搜索 同时在图搜时能避免搜索无法结束(图有环)



DFS 天然符合回溯法的使用场景 常规做法是使用递归来实现

二者的时间复杂度没有太大差别 假设有个图 G(V, E) BFS 需要对顶点出入队一次 复杂度是 $O(V+E)$ DFS 是 $O(E)$ 实际复杂网络中 一般 V 远小于 E  两者都近似为 $O((E)$

两者在实际的适用场景还是有些区别的 在求最短路径时 例如迷宫 BFS 最早搜索到终点时就是最短路径 可以提前结束 而DFS需要递归完整个搜索空间 找出所有可能路径进行比较 若已知搜索空间很大 搜索路径不会特别长时 BFS 可能会比 DFS 更快一些

DFS 实现起来比 BFS 更简单，且由于递归栈的存在，让我们可以很方便地在递归函数的参数中记录路径，所以需要输出路径的题目用 DFS 会比较合适



## Links

- [data structures](/docs/CS/Algorithms/Algorithms.md?id=data-structures)
- [algorithm analysis](/docs/CS/Algorithms/Algorithms.md?id=algorithm-analysis)