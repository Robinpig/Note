## Introduction

A *tree* can be defined in several ways. One natural way to define a tree is recursively.
A tree is a collection of nodes. The collection can be empty, which is sometimes denoted as A.
Otherwise, a tree consists of a distinguished node r, called the root, and zero or more (sub)trees T1, T2, . . . , Tk, each of whose roots are connected by a directed edge to r.

The root of each subtree is said to be a child of r, and r is the parent of each subtree root.

![Generic Tree](./images/Generic-Tree.png)

From the recursive definition, we find that a tree is a collection of n nodes, one of which is the root, and n - 1 edges.
That there are n - 1 edges follows from the fact that each edge connects some node to its parent, and every node except the root has one parent.

![A Tree](./images/tree.png)

Each node may have an arbitrary number of children, possibly zero.

- Nodes with no children are known as leaves.
- Nodes with the same parent are siblings.
- Grandparent and grandchild relations can be defined in a similar manner.

> [!NOTE]
>
> Notice that in a tree there is exactly one path from the root to each node.

For any node ni, the depth of ni is the length of the unique path from the root to ni.
Thus, the root is at depth 0. The height of ni is the longest path from ni to a leaf.
Thus all leaves are at height 0.
The height of a tree is equal to the height of the root.
The depth of a tree is equal to the depth of the deepest leaf; this is always equal to the height of the tree.

If there is a path from n1 to n2, then n1 is an ancestor of n2 and n2 is a descendant of n1.
If n1 != n2, then n1 is a proper ancestor of n2 and n2 is a proper descendant of n1.

## Implementation

The typical declaration: keep the children of each node in a linked list of tree nodes.

```c
typedef struct tree_node *tree_ptr;

struct tree_node
{
    element_type element;
    tree_ptr first_child;
    tree_ptr next_sibling;
};
```

### Tree Traversals

> [!NOTE]
>
> The UNIX file system is not a tree, but is treelike.

- In a preorder traversal, work at a node is performed before (pre) its children are processed.
- In a postorder traversal, the work at a node is performed after (post) its children are evaluated.

## Binary Trees

A binary tree is a tree in which no node can have more than two children.

A property of a binary tree that is sometimes important is that the depth of an average binary tree is considerably smaller than n.
An analysis shows that the average depth is $\sqrt{N}$, and that for a special type of binary tree, namely the binary search tree, the average value of the depth is O(log n).
Unfortunately, the depth can be as large as n -1.

### Implementation

Because a binary tree has at most two children, we can keep direct pointers to them.
The declaration of tree nodes is similar in structure to that for doubly linked lists, in that a node is a structure consisting of the *key* information plus two pointers (*left* and  *right* ) to other nodes.

```c
typedef struct tree_node *tree_ptr;
struct tree_node

{
    element_type element;
    tree_ptr left;
    tree_ptr right;

};

typedef tree_ptr TREE;
```

We could draw the binary trees using the rectangular boxes that are customary for linked lists, but trees are generally drawn as circles connected by lines, because they are actually graphs. We also do not explicitly draw *NULL* pointers when referring to trees, because every binary tree with *n* nodes would require *n + *1* NULL* pointers.

This general strattegy ( left, node, right ) is known as an *inorder* traversal.

## Binary Search Tree

An important application of binary trees is their use in searching.

The property that makes a binary tree into a binary search tree is that for every node,  *X* ,
in the tree, the values of all the keys in the left subtree are smaller than the key value in  *X* , and the values of all the keys in the right subtree are larger than the key value in  *X* .
Notice that this implies that all the elements in the tree can be ordered in some consistent manner.

In below figure, the tree on the left is a binary search tree, but the tree on the right is not.
The tree on the right has a node with key 7 in the left subtree of a node with key 6 (which happens to be the root).

![Binary Search Tree](./images/Binary-Search-Tree.png)

Because the average depth of a binary search tree is O(log n), we generally do not need to worry about running out of stack space.


## Links

- [data structures](/docs/CS/Algorithms/Algorithms.md?id=data-structures)
