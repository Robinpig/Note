## Introduction

二叉搜索树（BST）的查找/插入/删除效率完全取决于树高：随机数据下期望 $O(\log n)$，但**有序插入会让它退化成链表**，最坏 $O(n)$。平衡树用旋转在局部调整形状，把高度始终压在 $O(\log n)$。

两种经典平衡树：

- **AVL 树**（1962，Adelson-Velsky & Landis）：严格要求任意节点左右子树高差不超过 1，是**严格平衡**。树更矮、查找更快，但插入删除时恢复平衡的旋转更多。
- **红黑树**（1978 命名，Guibas & Sedgewick）：放松平衡条件为「路径上的黑节点数相同」，是**弱平衡**。旋转次数更少，插入删除更快，是工程界的默认选择。

红黑树的正确理解入口是 **2-3-4 树**：1972 年 Bayer 提出的对称二叉 B 树中，一个节点可有 2、3 或 4 个孩子。把 3/4 节点「压」成二叉形式时，多出来的那条边染成红色，就得到了红黑树。红黑树的所有规则与操作，都能翻译回 2-3-4 树的节点分裂来理解。

## The 2-3-4 Tree Background

2-3-4 树是 B 树的特例，节点分三种：

| 节点 | 键数 | 孩子数 | 说明 |
| :-- | :-- | :-- | :-- |
| 2-node | 1 | 2 | 普通二叉树节点 |
| 3-node | 2 | 3 | 两个键把区间分三段 |
| 4-node | 3 | 4 | 三个键把区间分四段 |

所有叶子在同一深度，树高 $O(\log n)$。插入时若落进 4-node 就**先分裂再下降**（把中间键上提），这保证不会有节点超容。

把 2-3-4 树表示为纯二叉树：2-node 就是黑节点；3-node 画成黑节点挂一个红孩子；4-node 画成黑节点挂两个红孩子。**红边即「3/4 节点内部的链接」**，黑边才是普通父子边——这是解读红黑树全部规则的钥匙。

## Rules

一棵红黑树满足五条性质：

1. 每个节点要么是**红色**，要么是**黑色**。
2. **根是黑色**。
3. 所有叶子哨兵（NIL 叶子，空节点）都是**黑色**。
4. **红节点的两个孩子都是黑色**（不存在两个相邻的红节点，即红节点的父节点必为黑）。
5. 从任一节点到其全部后代 NIL 叶子的每条路径上，**黑色节点数目相同**（黑高 black-height 一致）。

> [!NOTE]
>
> 性质 3 里的 NIL 哨兵是实现细节：逻辑上红黑树在每个空孩子处挂一个黑色空节点，使「每条路径终点相同」，性质 5 才有意义。代码实现中通常只用一个共享的 `nil` 对象。

## Why the Rules Imply Balance

设节点 $x$ 的黑高为 $bh(x)$（不含 $x$ 自身）。由性质 4，红节点不相邻，故任意路径上红节点不超过黑节点：

$$
\text{树高 } h \le 2 \cdot bh(\text{root})
$$

而由性质 5 可归纳证明：以 $x$ 为根的子树至少有 $2^{bh(x)} - 1$ 个内部节点，于是

$$
n \ge 2^{bh(\text{root})} - 1 \;\Rightarrow\; h \le 2\log_2(n+1)
$$

即**树高恒为 $O(\log n)$**。换成 2-3-4 树的语言：红边占比至多一半，所以「最长路径不超过最短路径的 2 倍」——这正是红黑树放松 AVL 的「1 倍」后得到的性质，也是它插入删除旋转更少的根本原因。

## Insertion and Fixup

新节点**染成红色**插入（染红不会破坏性质 5，只可能违反性质 4 的双红、以及根变红）。若父节点是黑色，插入即告完成；否则按**叔父节点（uncle）的颜色**分三种情况修复：

| 情况 | 形态 | 处理 |
| :-- | :-- | :-- |
| Case 1 | 叔父为红 | 父与叔父染黑、祖父染红，视角上移到祖父，递归处理 |
| Case 2 | 叔父为黑，新节点是「内孙」（zig-zag） | 对父节点旋转，转化为 Case 3 |
| Case 3 | 叔父为黑，新节点是「外孙」（zig-zig） | 祖父旋转 + 父与祖父换色，结束 |

- 变色（Case 1）可能沿路径上传 $O(\log n)$ 次，但**旋转至多 2 次**（Case 2、3 各一次）。
- 若修复后根变红，最后一步把根染黑（恢复性质 2）。
- 翻译回 2-3-4 树：Case 1 就是 4-node 分裂的染色版，Case 2/3 的旋转等价于重新选择 3/4 节点的表示形态。

## Deletion and Fixup

删除比插入复杂：删黑色节点会破坏性质 5，被删位置产生**双重黑（double-black）**，需要向兄弟子树「借」一个黑色。按兄弟的颜色与兄弟孩子的颜色分四种情况处理（旋转 + 换色），至多 3 次旋转。删除的具体分支在实现中容易写错，因此实践中常采用结构更规整的等价变体——例如**左倾红黑树（LLRB，Sedgewick）**，把红黑树约束到与 2-3 树一一对应，插入删除都归结为同一套旋转。

## Complexity

| 操作 | 平均 | 最坏 |
| :-- | :-- | :-- |
| 查找 | $O(\log n)$ | $O(\log n)$ |
| 插入 | $O(\log n)$ | $O(\log n)$（旋转 $\le 2$） |
| 删除 | $O(\log n)$ | $O(\log n)$（旋转 $\le 3$） |
| 空间 | $O(n)$ | 每节点仅多存 1 bit 颜色 |

## Comparison with Other Balanced Trees

| 维度 | AVL 树 | 红黑树 | B 树 |
| :-- | :-- | :-- | :-- |
| 平衡强度 | 严格（高差 $\le 1$） | 弱（最长路径 $\le 2$ 倍） | m 路扇出，高度极低 |
| 查找 | 最快（树最矮） | 略慢 | 慢，但磁盘页友好 |
| 插入/删除 | 旋转多 | 旋转少 | 节点分裂/合并 |
| 定位 | 内存中的全序结构 | 内存中的全序结构 | 外存/索引结构 |
| 典型场景 | 读多写少 | 通用 | 数据库索引、文件系统 |

## In Practice

- **C++** `std::map` / `std::set` / `std::multimap` 默认以红黑树实现；**Java** `TreeMap` / `TreeSet` 也是红黑树。
- **Linux 内核**大量使用红黑树：CFS 调度器用 `sched_entity` 上的 `rb_node` 组织就绪队列（按虚拟时间排序）；`epoll` 用红黑树（按 fd + file 索引）管理被监视的文件描述符，O(log n) 增删、事件就绪时摘到就绪链表。注意内核 VMA 管理在 6.1 起已从红黑树换成 maple tree。
- **Redis 有序集合**没有用红黑树，而是[跳表](/docs/CS/Algorithms/struct/skiplist.md)：范围查询实现更直观，且插入删除的旋转更少，见 skiplist 与红黑树的对比一节。
- **PostgreSQL** 的 B-Tree 索引用 B-Link-Tree（L&Y）方案做并发控制，与红黑树是两条技术路线，见 [B_Link_Tree](/docs/CS/Algorithms/tree/B_Link_Tree.md)。

## Links

- [Binary Tree](/docs/CS/Algorithms/tree/Binary-Tree.md)
- [B-tree](/docs/CS/Algorithms/tree/B-tree.md)
- [Tree](/docs/CS/Algorithms/tree/tree.md)
- [Skip List](/docs/CS/Algorithms/struct/skiplist.md)

## References

1. [红黑树 - OI Wiki](https://oi-wiki.org/ds/rbtree/)
2. [Red-Black Trees (Eternally Confuzzled tutorial)](http://eternallyconfuzzled.com/tuts/datastructures/jsw_tut_rbtree.aspx)
3. [Left-Leaning Red-Black Trees (Sedgewick)](https://www.cs.princeton.edu/~rs/talks/LLRB/LLRB.pdf)
