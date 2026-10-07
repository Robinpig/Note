## Introduction

Binary Tree（二叉树）是每个节点最多有两个孩子（left / right）的 [tree](/docs/CS/Algorithms/tree/tree.md)。
它是非线性的层级结构，与线性的 [linked-list](/docs/CS/Algorithms/struct/linked-list.md) 同源（节点靠指针相连），但一个节点指向两个后继，天然适合表达二分与递归结构。

```
        1
      /   \
     2     3
    / \     \
   4   5     6
```

## Terms
- 度（degree）：节点的孩子数，二叉树中为 0/1/2；叶子（leaf）度为 0。
- 深度（depth）：从根到该节点的边数；高度（height）：该节点到最远叶子的边数。
- 满二叉树（full/proper）：每个节点度为 0 或 2；完全二叉树（complete）：除最后一层外全满，最后一层节点靠左连续；
  完美二叉树（perfect）：所有叶子同层且内部节点都有两个孩子。

## Special Forms
- **BST（Binary Search Tree）**：对任意节点有 `left 值 < 节点值 < right 值`，中序遍历得到有序序列。查找/插入/删除平均 O(log n)，但退化成链时最坏 O(n)，因此需要平衡树（[Red-Black-Tree](/docs/CS/Algorithms/tree/Red-Black-Tree.md)、AVL）来约束高度。
- **Heap（二叉堆）**：一棵满足堆序的完全二叉树（父节点 ≤/≥ 孩子），用数组紧凑存储，节点 i 的孩子在 2i+1、2i+2；实现见 [heap](/docs/CS/Algorithms/struct/heap.md)。
- **Huffman Tree**：带权路径长度最小的二叉树，用于前缀编码，见 [Huffman-Tree](/docs/CS/Algorithms/tree/Huffman-Tree.md)。
- 多路/磁盘导向的推广是 [B-tree](/docs/CS/Algorithms/tree/B-tree.md)（数据库索引）与 [LSM](/docs/CS/Algorithms/tree/LSM.md)。

## Traversals
遍历是二叉树大多数算法的基础。深度优先（DFS）按访问根的时机分三种：

- Pre-order（根-左-右）：`1 2 4 5 3 6`
- In-order（左-根-右）：`4 2 5 1 3 6`，BST 下即排序输出
- Post-order（左-右-根）：`4 5 2 6 3 1`，适合先处理孩子再汇总（求值表达式、释放树）

广度优先（BFS / level-order）借助 [queue](/docs/CS/Algorithms/struct/queue.md) 逐层访问：`1 2 3 4 5 6`。
DFS 可用递归或显式 [stack](/docs/CS/Algorithms/struct/stack.md) 实现，二者等价（递归本就依赖调用栈）。

## Recurrence
二叉树问题几乎都可以递归分解为「处理当前节点 + 递归左右子树」：

```
maxDepth(node) = 0, node 为空
               = 1 + max(maxDepth(left), maxDepth(right))
```

典型题目族：求深度/直径、判断平衡/对称/相同、最近公共祖先（LCA）、路径和、序列化反序列化、由「前序+中序」重建二叉树。
n 个节点的二叉树形态数是第 n 个 Catalan 数。

## Links

- [Tree](/docs/CS/Algorithms/tree/tree.md)
- [Red-Black-Tree](/docs/CS/Algorithms/tree/Red-Black-Tree.md)
- [B-tree](/docs/CS/Algorithms/tree/B-tree.md)
- [Huffman-Tree](/docs/CS/Algorithms/tree/Huffman-Tree.md)
- [heap](/docs/CS/Algorithms/struct/heap.md)
- [linked-list](/docs/CS/Algorithms/struct/linked-list.md)

## References

1. [Binary tree - Wikipedia](https://en.wikipedia.org/wiki/Binary_tree)
