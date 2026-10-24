## Introduction

基数树（radix tree，又称 radix trie、compact prefix tree、compressed trie）是对 [Trie](/docs/CS/Algorithms/tree/Trie.md) 的**空间优化**：Trie 中每个节点只存一个字符，一条只含独生节点的链会被基数树**压缩成一条边**——边的标签可以是一串字符（或一段子串的起止偏移），而不是单个字符。

压缩的效果：把 $m$ 个字符串存进 Trie 最坏需要 $O(\text{总长度})$ 个节点；若它们共享长前缀，基数树的节点数只取决于**分叉点**的数量，对「小集合 + 长字符串」或「大量共享前缀」的场景节省显著。

<div style="text-align: center;">

![](https://upload.wikimedia.org/wikipedia/commons/thumb/a/ae/Patricia_trie.svg/2880px-Patricia_trie.svg.png)

</div>

## PATRICIA Trie

当基数 $r = 2$（按位而非按字符分支）时，基数树称为 **PATRICIA trie**。它的经典用途是**路由表查找**与**整数索引**：键是一串比特，每条边标注「从第几位开始比较、跳过多少位」，查找时逐位跳过不相干的前缀，直接落到分叉处。

操作与 Trie 基本一致，只是多了节点的合并与分裂：

- **插入**：走到分叉点，把压缩边拆开，长出的部分成为新的内部节点；
- **删除**：若删除后某节点只剩一个孩子，就把它与孩子**合并**回一条压缩边，维持「无独生节点」不变式。

复杂度（设键长为 $k$）：查找/插入/删除均为 $O(k)$，与集合大小无关——这是 Trie 家族相对比较树的优势（平衡树是 $O(\log n)$，但 $k$ 通常远小于 $\log n$ 相关的字符比较代价）。

## Radix Tree in Systems

- **Linux 内核基数树**（`lib/radix-tree.c`）：注意它存的不是字符串，而是**无符号长整数 index**——页缓存（`address_space`）用它把页帧号映射到页描述符。实现按 6 位一层（每层 64 个槽）逐级间接寻址，树高随 index 范围动态增长；插入新 index 时按需扩展层数。它的现代继任者是 **XArray**（以及基于它的 IDR/IDA）。
- **Gin 的 HTTP 路由**：gin（及其前身 httprouter）用基数树组织路由。静态前缀压缩共享，同时支持 `:param` 与 `*wildcard` 两类通配，且规定**静态路由优先于通配路由**匹配。路由查找从根开始逐段（而不是逐字符）比较，段数远小于字符串长度，是 radix tree 在 Web 框架中最知名的落地。

## Trade-offs

| 维度 | 基数树 | 哈希表 | 平衡树 |
| :-- | :-- | :-- | :-- |
| 查找 | $O(k)$，$k$ 为键长 | 期望 $O(1)$ | $O(\log n)$ |
| 前缀查询 | 天然支持 | 不支持 | 需额外结构 |
| 有序遍历 | 支持（按字典序） | 无序 | 支持 |
| 空间 | 取决于分叉数 | 取决于负载因子 | 每节点多存平衡信息 |
| 适用 | 长键、共享前缀、路由/IP 查找 | 纯键值查找 | 需全序 |

## Links

- [Trie](/docs/CS/Algorithms/tree/Trie.md)
- [Tree](/docs/CS/Algorithms/tree/tree.md)
- [Hash](/docs/CS/Algorithms/hash.md)

## References

1. [字典树 - OI Wiki](https://oi-wiki.org/string/trie/)
2. [Radix tree - Wikipedia](https://en.wikipedia.org/wiki/Radix_tree)
3. [Patricia trie - Wikipedia](https://en.wikipedia.org/wiki/Patricia_trie)
4. [httprouter radix tree 实现（tree.go）](https://cdn.jsdelivr.net/gh/julienschmidt/httprouter@master/tree.go)
