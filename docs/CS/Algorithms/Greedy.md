## Introduction

贪心算法 (greedy algorithm) 在每一步都做出当时看起来最佳的选择。也就是说，它总是做出局部最优的选择，寄希望这样的选择能导致全局最优解
贪心算法并不保证得到最优解，但对很多问题确实可以求得最优解

贪心方法是一种强有力的算法设计方法，可以很好地解决很多问题。例如最小生成树 (minimum-spanning-tree) 算法、单源最短路径的 Dijkstra 算法，以及集合覆盖问题的 Chvatal 贪心启发式算法

通常，能用贪心算法解决的问题需同时满足两个条件：

1. 贪心选择性质
2. 最优子结构

贪心算法分阶段进行。在每个阶段，会做出一个看起来不错的决策，而不考虑未来的后果。通常，这意味着选择某个“局部最优”。这种“先取当前可得之物”的策略正是这一类算法名称的由来 这种“尽可能及时获取”的策略就是这类算法名称的来源

> 贪心算法与动态规划的不同在于它对每个子问题的解决方案都做出选择，不能回退。动态规划则会保存以前的运算结果，并根据以前的结果对当前进行选择，有回退功能

当算法终止时，我们希望“局部最优”等于“全局最优”。
如果是这样，那么算法就是正确的；否则，算法就产生了次优解。
如果不需要绝对最优答案，那么有时会使用简单的贪婪算法来生成近似答案，而不是使用通常需要的更复杂的算法来生成精确答案。



常见的三种贪心算法：Dijkstra 算法、Prim 算法和 Kruskal 算法

There are several real-life examples of greedy algorithms. 
The most obvious is the coin-changing problem.
Traffic problems provide an example where making locally optimal choices does not always work. 

The **0-1 knapsack problem** is the following. 
A thief robbing a store finds n items. The $i$th item is worth $\nu_i$ dollars and weighs $\omega_i$ pounds, where $$\nu_i$$ and $\omega_i$ are integers. 
The thief wants to take as valuable a load as possible, but he can carry at most W pounds in his knapsack, for some integer W . 
Which items should he take?
(We call this the 0-1 knapsack problem because for each item, the thief must either take it or leave it behind; 
he cannot take a fractional amount of an item or take an item more than once.)

In the **fractional knapsack problem**, the setup is the same, but the thief can take fractions of items, rather than having to make a binary (0-1) choice for each item.
You can think of an item in the 0-1 knapsack problem as being like a gold ingot and an item in the fractional knapsack problem as more like gold dust.

We can solve the fractional knapsack problem by a greedy strategy, but we cannot solve the 0-1 problem by such a strategy.



## Simple Scheduling Problem

Virtually all scheduling problems are either NP-complete (or of similar difficult complexity) or are solvable by a greedy algorithm.

We are given jobs *j*1, *j*2, . . . , *jn*, all with known running times *t*1, *t*2, . . . , *tn*, respectively. We have a single processor.
What is the best way to schedule these jobs in order to minimize the average completion time?

Let the jobs in the schedule be *ji*1, *ji*2, . . . , *jin*. The first job finishes in time *ti*1. The second job finishes after *ti*1 + *ti*2, and the third job finishes after *ti*1 + *ti*2 + *ti*3. 
From this, we see that the total cost, C, of the schedule is $C = \sum_{k=1}^{N}{(N - k + 1)t_{ik}}$, $C = (N+1)\sum_{k=1}^{N}{t_{ik}}-\sum_{k=1}^{N}{k*t_{ik}}$.




This result indicates the reason the operating system scheduler generally gives precedence to shorter jobs.



### The Multiprocessor Case





### Minimizing the Final Completion Time

Minimizing the final completion time is apparently much harder than minimizing the mean completion time. This new problem turns out to be *NP*-complete; it is just another way of phrasing the knapsack or bin-packing problems,





## Huffman Codes

*file compression*



Notice that if all the characters occur with the same frequency, then there are not likely to be any savings.








## Links

- [Algorithm Analysis](/docs/CS/Algorithms/Algorithms.md?id=algorithm-analysis)





