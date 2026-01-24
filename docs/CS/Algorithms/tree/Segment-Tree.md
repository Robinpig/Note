## Introduction

一种用于高效处理区间查询和区间修改的二叉树结构。它将一个区间不断二分，每个节点管理一个区间，叶子节点对应单个元素，内部节点则代表其子区间的合并结果。
这样可以在 $O(logn)$ 时间内完成区间相关操作



## Links


- [Trees](/docs/CS/Algorithms/tree/tree.md?id=LSM)