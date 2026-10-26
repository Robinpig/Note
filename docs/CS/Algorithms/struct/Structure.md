## Introduction

数据结构的世界看似纷繁——数组、链表、栈、队列、树、图、哈希表——但拆到底只有两种**基本结构**：数组（一块连续内存，按下标寻址）和链表（节点靠指针串联）。其余结构都是这两者的组合、变形或叠加约束后的产物。理解这一点，选型时就有了统一的判断框架：**先问访问模式，再选存储形态，最后才考虑具体结构。**

## Array and Linked List: The Fundamental Trade-off

两种基本结构的核心差异可以归结为一句话：**数组用「连续」换来随机访问，链表用「指针」换来廉价插入**。

- 数组按下标一步算出地址，访问第 $i$ 个元素 $O(1)$；但插入/删除要搬移后续元素保持连续，$O(n)$。
- 链表插入/删除只改指针，已知位置时 $O(1)$；但访问第 $i$ 个元素必须从头遍历，$O(n)$，且每个节点额外付出指针空间，缓存也不友好。

具体实现与复杂度对比见 [array](/docs/CS/Algorithms/struct/array.md) 与 [linked-list](/docs/CS/Algorithms/struct/linked-list.md)，逻辑层面的抽象见 [list](/docs/CS/Algorithms/struct/list.md)。

## Everything Else Is a Combination

把两种基本结构组合起来，就能「造」出常见结构：

- **邻接矩阵就是二维数组，邻接表就是链表**。邻接矩阵判断两点是否相连 $O(1)$、可做矩阵运算，但稀疏图浪费空间（$O(n^2)$）；邻接表省空间（$O(n+m)$），但判连通要遍历。图论枢纽见 [graph](/docs/CS/Algorithms/graph/graph.md)。
- **散列表就是数组 + 链表/探测**：用散列函数把键映射到大数组。冲突处理的两条路线各自依赖一种基本结构——拉链法需要链表存同桶元素，操作简单但费指针空间；开放寻址法需要数组连续寻址，省空间但聚集敏感，见 [hash](/docs/CS/Algorithms/struct/hash.md)。
- **树用数组实现就是堆**：完全二叉树的形状规则，用数组存储不需要任何节点指针，`parent(i) = (i-1)/2` 一步算出，见 [heap](/docs/CS/Algorithms/struct/heap.md)。非完全二叉树不适合数组，于是用指针树，并在其上叠加约束得到 BST、AVL、[红黑树](/docs/CS/Algorithms/tree/Red-Black-Tree.md)、B 树等平衡家族。
- **跳表 = 链表 + 多级索引**：本质是有序链表加上「快速通道」，用概率平衡替代严格旋转，见 [skiplist](/docs/CS/Algorithms/struct/skiplist.md)。
- **位数组 + 多个哈希 = 布隆过滤器**：放弃精确换取空间，见 [BloomFilter](/docs/CS/Algorithms/struct/BloomFilter.md)。

## A Selection Guide

没有「最好的数据结构」，只有「对这批操作最好的数据结构」。按主导操作查表：

| 主导操作 | 推荐结构 | 原因 |
| :-- | :-- | :-- |
| 按下标随机访问 | 数组 | 唯一 $O(1)$ |
| 频繁头插/头删 | 链表、双端队列 | 数组要搬移全表 |
| 已知节点摘除 | 双向链表 | 改指针即完成 |
| 按序访问 + 区间操作 | 数组 + 前缀和、树状数组、线段树 | 预处理换查询 |
| 键值查找 | 哈希表 | 期望 $O(1)$ |
| 键值查找且需有序 | 平衡树、跳表 | 保序 + $O(\log n)$ |
| 优先取最大/最小 | 堆 | $O(\log n)$ 调整 |
| 判存在性、空间敏感 | 布隆过滤器 | 位图 + 多哈希 |
| 稀疏二维关系 | 稀疏数组 / CSR | 跳过默认值 |

一个真实例子：Redis 的集合类编码正是按规模切换——元素少时用连续数组（紧凑、缓存友好、遍历快），元素多后再切换为哈希表或跳表，兼顾小对象的空间与大对象的性能。

## Iteration and Recursion

数组与链表也决定了遍历的写法差异：

- **数组**天然适合迭代，`for` 下标递增即可，深度无关。
- **树与图**的遍历天然是递归定义，但递归深度等于树高/图深，最坏 $O(n)$ 时会**栈溢出**。工程解法是改成显式栈的迭代（DFS）或显式队列的迭代（BFS），见 [Recursion](/docs/CS/Algorithms/paradigm/Recursion.md) 与 [Divide-and-Conquer](/docs/CS/Algorithms/paradigm/Divide-and-Conquer.md)。
- 递归转迭代不总是可行：需要「回溯现场」的搜索（如 [Backtracking](/docs/CS/Algorithms/paradigm/Backtracking.md)）本质是递归，用显式栈模拟时代码复杂度显著上升，通常不如限制深度 + 尾递归优化。

## Links

- [Algorithms](/docs/CS/Algorithms/Algorithms.md)
- [Array](/docs/CS/Algorithms/struct/array.md)
- [Linked List](/docs/CS/Algorithms/struct/linked-list.md)
- [Heap](/docs/CS/Algorithms/struct/heap.md)
- [Skip List](/docs/CS/Algorithms/struct/skiplist.md)
- [Fenwick Tree](/docs/CS/Algorithms/struct/Fenwick-Tree.md)

## References

1. [数据结构 - OI Wiki](https://oi-wiki.org/ds/)
2. [哈希表 - OI Wiki](https://oi-wiki.org/ds/hash/)
3. [树的基本概念 - OI Wiki](https://oi-wiki.org/graph/tree-basic/)
