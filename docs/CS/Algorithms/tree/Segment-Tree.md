## Introduction

线段树是一种用于高效处理区间查询和区间修改的二叉树结构。它将一个区间不断二分，每个节点管理一个区间，叶子节点对应单个元素，内部节点则代表其子区间的合并结果。
线段树可以在 $O(logn)$ 的时间复杂度内实现单点修改、区间修改、区间查询（区间求和，求区间最大值，求区间最小值)等操作



线段树将每个长度不为 1![1](data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7) 的区间划分成左右两个区间递归求解，把整个线段划分为一个树形结构，通过合并左右两区间信息来求得该区间的信息．这种数据结构可以方便的进行大部分的区间操作









## Links


- [Trees](/docs/CS/Algorithms/tree/tree.md?id=LSM)



## References

1. [线段树基础 OI Wiki](https://oi-wiki.org/ds/seg/)