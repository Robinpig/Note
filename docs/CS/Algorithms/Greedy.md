## Introduction

贪心算法 (greedy algorithm) 在每一步都做出当时看起来最佳的选择。也就是说，它总是做出局部最优的选择，寄希望这样的选择能导致全局最优解
贪心算法并不保证得到最优解，但对很多问题确实可以求得最优解

贪心方法是一种强有力的算法设计方法，可以很好地解决很多问题。例如最小生成树 (minimum-spanning-tree) 算法、单源最短路径的 Dijkstra 算法，以及集合覆盖问题的 Chvatal 贪心启发式算法

Greedy algorithms work in phases. 
In each phase, a decision is made that appears to be good, without regard for future consequences. Generally, this means that some `local optimum` is chosen.  This "take what you can get now" strategy is the source of the name for this class of algorithms. 

When the algorithm terminates, we hope that the `local optimum` is equal to the `global optimum`. If this is the case, then the algorithm is correct; otherwise, the algorithm has produced a suboptimal solution. If the absolute best answer is not required, then simple greedy algorithms are sometimes used to generate approximate answers, rather than using the more complicated algorithms generally required to generate an exact answer.



We have already seen three greedy algorithms: Dijkstra's, Prim's, and Kruskal's algorithms.

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

We are given jobs *j*1, *j*2, . . . , *jn*, all with known running times *t*1, *t*2, . . . , *tn*, respectively. We have a single processor. What is the best way to schedule these jobs in order to minimize the average completion time?

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





