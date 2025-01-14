## Introduction

In computer science, a radix tree (also radix trie or compact prefix tree or compressed trie)
is a data structure that represents a space-optimized trie (prefix tree) in which each node that is the only child is merged with its parent.

The result is that the number of children of every internal node is at most the radix r of the radix tree, where r = 2^x for some integer x ≥ 1. 
Unlike regular trees, edges can be labeled with sequences of elements as well as single elements.
This makes radix trees much more efficient for small sets (especially if the strings are long) and for sets of strings that share long prefixes.

![](https://upload.wikimedia.org/wikipedia/commons/thumb/a/ae/Patricia_trie.svg/2880px-Patricia_trie.svg.png)



















## Links

- [Trees](/docs/CS/Algorithms/tree/tree.md?id=Radix)
- [Trie](/docs/CS/Algorithms/tree/Trie.md)