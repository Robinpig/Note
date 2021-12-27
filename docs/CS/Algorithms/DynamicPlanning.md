## Introduction



Any recursive mathematical formula could be directly translated to a recursive algorithm, but the underlying reality is that often the compiler will not do justice to the recursive algorithm, and an inefficient program results.
When we suspect that this is likely to be the case, we must provide a little more help to the compiler, by rewriting the recursive algorithm as a nonrecursive algorithm that systematically records the answers to the subproblems in a table.
One technique that makes use of this approach is known as `dynamic programming`.


重叠子问题、最优子结构、状态转移方程



**递归算法的时间复杂度怎么计算？就是用子问题个数乘以解决一个子问题需要的时间**



mentor -> dp[]

array or  hash table


