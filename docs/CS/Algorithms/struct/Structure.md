## Introduction

array and linked table are basic structures.

邻接表就是链表，邻接矩阵就是二维数组。邻接矩阵判断连通性迅速，并可以进行矩阵运算解决一些问题，但是如果图比较稀疏的话很耗费空间。邻接表比较节省空间，但是很多操作的效率上肯定比不过邻接矩阵



散列表」就是通过散列函数把键映射到一个大数组里。而且对于解决散列冲突的方法，拉链法需要链表特性，操作简单，但需要额外的空间存储指针；线性探查法就需要数组特性，以便连续寻址，不需要指针的存储空间，但操作稍微复杂些。



「树」，用数组实现就是「堆」，因为「堆」是一个完全二叉树，用数组存储不需要节点指针，操作也比较简单；用链表实现就是很常见的那种「树」，因为不一定是完全二叉树，所以不适合用数组存储。为此，在这种链表「树」结构之上，又衍生出各种巧妙的设计，比如二叉搜索树、AVL 树、红黑树、区间树、B 树等等，以应对不同的问题。



link: Redis 在存储实现时数据少尽量数组，多再考虑链表。



迭代与递归

树 图 递归遍历

## Links

- [Algorithms](/docs/CS/Algorithms/Algorithms.md)
- [array](/docs/CS/Algorithms/struct/array.md)
- [linked-list](/docs/CS/Algorithms/struct/linked-list.md)
- [stack](/docs/CS/Algorithms/struct/stack.md)
- [queue](/docs/CS/Algorithms/struct/queue.md)
- [heap](/docs/CS/Algorithms/struct/heap.md)
- [skip list](/docs/CS/Algorithms/struct/skiplist.md)
- [Fenwick Tree](/docs/CS/Algorithms/struct/Fenwick-Tree.md)
- [Bloom Filter](/docs/CS/Algorithms/struct/BloomFilter.md)

## References

1. [数据结构 - OI Wiki](https://oi-wiki.org/ds/)
2. [哈希表 - OI Wiki](https://oi-wiki.org/ds/hash/)
3. [树的基本概念 - OI Wiki](https://oi-wiki.org/graph/tree-basic/)
