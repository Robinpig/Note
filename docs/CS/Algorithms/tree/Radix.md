## Introduction

In computer science, a radix tree (also radix trie or compact prefix tree or compressed trie)
is a data structure that represents a space-optimized [trie (prefix tree)](/docs/CS/Algorithms/tree/Trie.md) in which each node that is the only child is merged with its parent.

The result is that the number of children of every internal node is at most the radix r of the radix tree, where r = 2^x for some integer x ≥ 1. 
Unlike regular trees, edges can be labeled with sequences of elements as well as single elements.
This makes radix trees much more efficient for small sets (especially if the strings are long) and for sets of strings that share long prefixes.

![](https://upload.wikimedia.org/wikipedia/commons/thumb/a/ae/Patricia_trie.svg/2880px-Patricia_trie.svg.png)







基数树是对字典树的压缩，因此基本操作和字典树基本一致，只是多了节点的合并和分裂操作









golang web 框架 gin 在 route 搜索上使用了该数据结构



Linux 的基数树实现在 `lib/radix-tree.c` 中，Linux 并不是对一个字符串进行存储，而是一个无符号长整型名为 index 的值









## Links

- [Trees](/docs/CS/Algorithms/tree/tree.md?id=Radix)
- [Trie](/docs/CS/Algorithms/tree/Trie.md)