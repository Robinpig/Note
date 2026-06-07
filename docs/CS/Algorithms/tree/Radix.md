## Introduction

在计算机科学中，基数树（也称为 radix trie 或紧凑前缀树或压缩字典树）
是一种数据结构，它表示空间优化的[字典树（前缀树）](/docs/CS/Algorithms/tree/Trie.md)，其中每个唯一子节点的节点都与其父节点合并。

结果是每个内部节点的子节点数量最多为基数树的分叉基数 r，其中 r = 2^x，x ≥ 1。
与常规树不同，边可以用元素序列以及单个元素来标记。
这使得基数树对于小集合（特别是当字符串很长时）以及共享长前缀的字符串集合更加高效。

![](https://upload.wikimedia.org/wikipedia/commons/thumb/a/ae/Patricia_trie.svg/2880px-Patricia_trie.svg.png)

基数树是对字典树的压缩，因此基本操作和字典树基本一致，只是多了节点的合并和分裂操作

golang web 框架 gin 在 route 搜索上使用了该数据结构

Linux 的基数树实现在 `lib/radix-tree.c` 中，Linux 并不是对一个字符串进行存储，而是一个无符号长整型名为 index 的值

## Links

- [Trees](/docs/CS/Algorithms/tree/tree.md?id=Radix)
- [Trie](/docs/CS/Algorithms/tree/Trie.md)
