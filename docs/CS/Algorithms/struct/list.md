## Introduction

显然，所有这些指令都可以仅通过使用数组来实现。
即使数组是动态分配的，也需要预估列表的最大大小。
通常这需要一个较高的估计值，这会浪费大量空间。
这可能是一个严重的限制，尤其是在有许多大小未知的列表时。

为了避免插入和删除的线性成本，我们需要确保列表不是连续存储的，否则整个部分都需要移动。

链表由一系列结构组成，这些结构在内存中不一定相邻。
每个结构包含元素和一个指向其后继结构的指针。

## Links

- [data structures](/docs/CS/Algorithms/Algorithms.md?id=data-structures)
- [stack](/docs/CS/Algorithms/struct/stack.md)
- [queue](/docs/CS/Algorithms/struct/queue.md)
