## Introduction

A *tree* can be defined in several ways. One natural way to define a tree is recursively.
A tree is a collection of nodes. The collection can be empty, which is sometimes denoted as A. 
Otherwise, a tree consists of a distinguished node r, called the root, and zero or more (sub)trees T1, T2, . . . , Tk, each of whose roots are connected by a directed edge to r.

![Generic Tree](./images/Generic-Tree.png)

The root of each subtree is said to be a child of r, and r is the parent of each subtree root.

Each node may have an arbitrary number of children, possibly zero. 

![A Tree](./images/tree.png)
- Nodes with no children are known as leaves.
- Nodes with the same parent are siblings.
- Grandparent and grandchild relations can be defined in a similar manner.


> [!NOTE]
> 
> Notice that in a tree there is exactly one path from the root to each node.



## Links
- [data structures](/docs/CS/Algorithms/Algorithms.md?id=data-structures)