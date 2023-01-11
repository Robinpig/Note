## Introduction

A priority queue is a data structure that allows at least the following two operations:  *insert* , which does the obvious thing, and  *delete_min* , which finds, returns and removes the minimum element in the heap.
The *insert* operation is the equivalent of  *enqueue* , and *delete_min* is the priority queue equivalent of the queue's *dequeue* operation.

Priority queues are also important in the implementation of  [*greedy algorithms*](/docs/CS/Algorithms/Greedy.md) , which operate by repeatedly finding a minimum.

## Simple Implementations

There are several obvious ways to implement a priority queue. We could use a simple linked list, performing insertions at the front in  *O* (1) and traversing the list, which requires  *O* ( *n* ) time, to delete the minimum.
Alternatively, we could insist that the list be always kept sorted; this makes insertions expensive ( *O* ( *n* )) and *delete_mins* cheap ( *O* (1)).
The former is probably the better idea of the two, based on the fact that there are never more *delete_mins* than insertions.

Another way of implementing priority queues would be to use a binary search tree. This gives an  *O* (log  *n* ) average running time for both operations.
This is true in spite of the fact that although the insertions are random, the deletions are not. Recall that the only element we ever delete is the minimum.
Repeatedly removing a node that is in the left subtree would seem to hurt the balance of the tree by making the right subtree heavy. However, the right subtree is random.
In the worst case, where the *delete_mins* have depleted the left subtree, the right subtree would have at most twice as many elements as it should.
This adds only a small constant to its expected depth. Notice that the bound can be made into a worst-case bound by using a balanced tree; this protects one against bad insertion sequences.

We will refer to binary heaps as merely  *heaps* . Like binary search trees, heaps have two properties, namely, a structure property and a heap order property.
As with AVL trees, an operation on a heap can destroy one of the properties, so a heap operation must not terminate until all heap properties are in order.

## Binary Heap

A heap is a binary tree that is completely filled, with the possible exception of the bottom level, which is filled from left to right. Such a tree is known as a  *complete binary tree*.

It is easy to show that a complete binary tree of height *h* has between 2*^h^* and 2 *^h^* +1 - 1 nodes. This implies that the height of a complete binary tree is log *n*, which is clearly  *O* (log  *n* ).

An important observation is that because a complete binary tree is so regular, it can be represented in an array and no pointers are necessary.

For any element in array position  *i* , the left child is in position 2 *i* , the right child is in the cell after the left child (2*i* + 1), and the parent is in position i/2.
Thus not only are pointers not required, but the operations required to traverse the tree are extremely simple and likely to be very fast on most computers.
The only problem with this implementation is that an estimate of the maximum heap size is required in advance.

A heap data structure will, then, consist of an array (of whatever type the key is) and integers representing the maximum 2nd current heap size.

## d-Heaps

Binary heaps are so simple that they are almost always used when priority queues are needed.
A simple generalization is a  *d-heap* , which is exactly like a binary heap except that all nodes have *d *children (thus, a binary heap is a 2-heap).

## Leftist Heaps

## Skew Heaps

A *skew heap* is a self-adjusting version of a leftist heap that is incredibly simple to implement.
The relationship of skew heaps to leftist heaps is analogous to the relation between splay trees and AVL trees.
Skew heaps are binary trees with heap order, but there is no structural constraint on these trees.
Unlike leftist heaps, no information is maintained about the null path length of any node.
The right path of a skew heap can be arbitrarily long at any time, so the worst-case running time of all operations is  *O* ( *n* ).
However, as with splay trees, it can be shown that for any *m* consecutive operations, the total worst-case running time is  *O* (*m *log  *n* ).
Thus, skew heaps have  *O* (log  *n* ) amortized cost per operation.

As with leftist heaps, the fundamental operation on skew heaps is merging.

## Binomial Queues

## Summary

The standard binary heap implementation is elegant because of its simplicity and speed. It requires no pointers and only a constant amount of extra space, yet supports the priority queue operations efficiently.

We considered the additional *merge* operation and developed three implementations, each of which is unique in its own way.
The leftist heap is a wonderful example of the power of recursion. The skew heap represents a remarkable data structure because of the lack of balance criteria.
The binomial queue shows how a simple idea can be used to achieve a good time bound.

## Links

- [data structures](/docs/CS/Algorithms/Algorithms.md?id=data-structures)

## References
