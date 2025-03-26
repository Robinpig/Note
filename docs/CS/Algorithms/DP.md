## Introduction

Dynamic programming, like the divide-and-conquer method, solves problems by combining the solutions to subproblems. 
(“Programming” in this context refers to a tabular method, not to writing computer code.)

Divide-and-conquer algorithms partition the problem into disjoint subproblems, solve the subproblems recursively, and then combine their solutions to solve the original problem. 
In contrast, dynamic programming applies when the subproblems overlap—that is, when subproblems share subsubproblems.
In this context, a divide-and-conquer algorithm does more work than necessary, repeatedly solving the common subsubproblems. 
A dynamic-programming algorithm solves each subsubproblem just once and then saves its answer in a table, thereby avoiding the work of recomputing the answer every time it solves each subsubproblem.

We typically apply dynamic programming to **optimization problems**. Such problems can have many possible solutions. 
Each solution has a value, and we wish to find a solution with the optimal (minimum or maximum) value. 
We call such a solution an optimal solution to the problem, as opposed to the optimal solution, since there may be several solutions that achieve the optimal value.

When developing a dynamic-programming algorithm, we follow a sequence of four steps:
1. Characterize the structure of an optimal solution.
2. Recursively define the value of an optimal solution.
3. Compute the value of an optimal solution, typically in a bottom-up fashion.
4. Construct an optimal solution from computed information.

Steps 1–3 form the basis of a dynamic-programming solution to a problem. 
If we need only the value of an optimal solution, and not the solution itself, then we can omit step 4. 
When we do perform step 4, we sometimes maintain additional information during step 3 so that we can easily construct an optimal solution.

The dynamic-programming method works as follows.
Having observed that a naive recursive solution is inefficient because it solves the same subproblems repeatedly, 
we arrange for each subproblem to be solved only once, saving its solution. 
If we need to refer to this subproblem’s solution again later, we can just look it up, rather than recompute it. 
Dynamic programming thus uses additional memory to save computation time; it serves an example of a **time-memory trade-off**. 
The savings may be dramatic: an exponential-time solution may be transformed into a polynomial-time solution. 
A dynamic-programming approach runs in polynomial time when the number of distinct subproblems involved is polynomial in the input size and we can solve each such subproblem in polynomial time。

There are usually two equivalent ways to implement a dynamic-programming approach. 

The first approach is **top-down with memoization**.
In this approach, we write the procedure recursively in a natural manner, but modified to save the result of each subproblem (usually in an array or hash table). 
The procedure now first checks to see whether it has previously solved this subproblem. 
If so, it returns the saved value, saving further computation at this level; if not, the procedure computes the value in the usual manner. 
We say that the recursive procedure has been memoized; it “remembers” what results it has computed previously.

The second approach is the **bottom-up method**. 
This approach typically depends on some natural notion of the “size” of a subproblem, such that solving any particular subproblem depends only on solving “smaller” subproblems. 
We sort the subproblems by size and solve them in size order, smallest first. 
When solving a particular subproblem, we have already solved all of the smaller subproblems its solution depends upon, and we have saved their solutions. 
We solve each subproblem only once, and when we first see it, we have already solved all of its prerequisite subproblems.

These two approaches yield algorithms with the same asymptotic running time,
except in unusual circumstances where the top-down approach does not actually recurse to examine all possible subproblems. 
The bottom-up approach often has much better constant factors, since it has less overhead for procedure calls.


### Subproblem graphs
When we think about a dynamic-programming problem, we should understand the set of subproblems involved and how subproblems depend on one another.

The subproblem graph for the problem embodies exactly this information.
The bottom-up method for dynamic programming considers the vertices of the subproblem graph in such an order that 
we solve the subproblems y adjacent to a given subproblem x before we solve subproblem x. (The adjacency relation is not necessarily symmetric.) 
In a bottom-up dynamic-programming algorithm, we consider the vertices of the subproblem graph in an order that is a “reverse topological sort”, 
or a “topological sort of the transpose” of the subproblem graph. 
In other words, no subproblem is considered until all of the subproblems it depends upon have been solved. 
Similarly, using notions from the same chapter, we can view the top-down method (with memoization) for dynamic programming as a “depth-first search” of the subproblem graph.

## Elements of dynamic programming 
We examine the two key ingredients that an optimization problem must have in order for dynamic programming to apply: optimal substructure and overlapping subproblems. 
We also revisit and discuss more fully how memoization might help us take advantage of the overlapping-subproblems property in a top-down recursive approach.

### Optimal substructure
The first step in solving an optimization problem by dynamic programming is to characterize the structure of an optimal solution. 
A problem exhibits optimal substructure if an optimal solution to the problem contains within it optimal solutions to subproblems. 
Whenever a problem exhibits optimal substructure, we have a good clue that dynamic programming might apply. 
In dynamic programming, we build an optimal solution to the problem from optimal solutions to subproblems. 
Consequently, we must take care to ensure that the range of subproblems we consider includes those used in an optimal solution

Dynamic programming often uses optimal substructure in a bottom-up fashion.
That is, we first find optimal solutions to subproblems and, having solved the subproblems, we find an optimal solution to the problem. 
Finding an optimal solution to the problem entails making a choice among subproblems as to which we will use in solving the problem. 
The cost of the problem solution is usually the subproblem costs plus a cost that is directly attributable to the choice itself.

In particular, problems to which [greedy algorithms](/docs/CS/Algorithms/Greedy.md) apply have optimal substructure. 
One major difference between greedy algorithms and dynamic programming is that instead of first finding optimal solutions to subproblems and then making an informed choice, 
greedy algorithms first make a “greedy” choice—the choice that looks best at the time—and then solve a resulting subproblem, without bothering to solve all possible related smaller subproblems.

### Overlapping subproblems
The second ingredient that an optimization problem must have for dynamic programming to apply is that the space of subproblems must be “small” in the sense
that a recursive algorithm for the problem solves the same subproblems over and over, rather than always generating new subproblems. 
Typically, the total number of distinct subproblems is a polynomial in the input size. 
When a recursive algorithm revisits the same problem repeatedly, we say that the optimization problem has overlapping subproblems. 
In contrast, a problem for which a divide-andconquer approach is suitable usually generates brand-new problems at each step of the recursion. 
Dynamic-programming algorithms typically take advantage of overlapping subproblems by solving each subproblem once and then 
storing the solution in a table where it can be looked up when needed, using constant time per lookup.




- 分治算法递归地将原问题划分为多个相互独立的子问题，直至最小子问题，并在回溯中合并子问题的解，最终得到原问题的解。
- 动态规划也对问题进行递归分解，但与分治算法的主要区别是，动态规划中的子问题是相互依赖的，在分解过程中会出现许多重叠子问题。
- 回溯算法在尝试和回退中穷举所有可能的解，并通过剪枝避免不必要的搜索分支。原问题的解由一系列决策步骤构成，我们可以将每个决策步骤之前的子序列看作一个子问题。
实际上，动态规划常用来求解最优化问题，它们不仅包含重叠子问题，还具有另外两大特性：最优子结构、无后效性。


无后效性是动态规划能够有效解决问题的重要特性之一，其定义为：给定一个确定的状态，它的未来发展只与当前状态有关，而与过去经历的所有状态无关。

最大方案


```java
  public static long climbingStairsDP(int n) {
        if (n == 1 || n == 2) {
            return n;
        }
        // 初始化 dp 表，用于存储子问题的解
        long[] dp = new long[n + 1];
        // 初始状态：预设最小子问题的解
        dp[1] = 1;
        dp[2] = 2;
        // 状态转移：从较小子问题逐步求解较大子问题
        for (int i = 3; i <= n; i++) {
            dp[i] = dp[i - 1] + dp[i - 2];
        }
        return dp[n];
    }
```
最小代价

```java
  static   long climbingStairsDPComp(int n) {
        if (n == 1 || n == 2) {
            return n;
        }
        long a = 1, b = 2;
        for (int i = 3; i <= n; i++) {
            long tmp = b;
            b = a + b;
            a = tmp;
        }
        return b;
    }
```

给定一个共有 n 阶的楼梯，你每步可以上 1 阶或者 2 阶，但不能连续两轮跳 1 阶，请问有多少种方案可以爬到楼顶？


```java
int climbingStairsConstraintDP(int n) {
    if (n == 1 || n == 2) {
        return 1;
    }
    // 初始化 dp 表，用于存储子问题的解
    int[][] dp = new int[n + 1][3];
    // 初始状态：预设最小子问题的解
    dp[1][1] = 1;
    dp[1][2] = 0;
    dp[2][1] = 0;
    dp[2][2] = 1;
    // 状态转移：从较小子问题逐步求解较大子问题
    for (int i = 3; i <= n; i++) {
        dp[i][1] = dp[i - 1][2];
        dp[i][2] = dp[i - 2][1] + dp[i - 2][2];
    }
    return dp[n][1] + dp[n][2];
}
```


在上面的案例中，由于仅需多考虑前面一个状态，因此我们仍然可以通过扩展状态定义，使得问题重新满足无后效性。然而，某些问题具有非常严重的“有后效性”。

爬楼梯与障碍生成
给定一个共有 n 阶的楼梯，你每步可以上 1 阶或者 2 阶。规定当爬到第 i 阶时，系统自动会在第 2i 阶上放上障碍物，之后所有轮都不允许跳到第 2i 阶上。例如，前两轮分别跳到了第 2、3 阶上，则之后就不能跳到第 4、6 阶上。请问有多少种方案可以爬到楼顶？

在这个问题中，下次跳跃依赖过去所有的状态，因为每一次跳跃都会在更高的阶梯上设置障碍，并影响未来的跳跃。对于这类问题，动态规划往往难以解决。

实际上，许多复杂的组合优化问题（例如旅行商问题）不满足无后效性。对于这类问题，我们通常会选择使用其他方法，例如启发式搜索、遗传算法、强化学习等，从而在有限时间内得到可用的局部最优解。

总的来说，如果一个问题包含重叠子问题、最优子结构，并满足无后效性，那么它通常适合用动态规划求解。然而，我们很难从问题描述中直接提取出这些特性。因此我们通常会放宽条件，先观察问题是否适合使用回溯（穷举）解决。

适合用回溯解决的问题通常满足“决策树模型”，这种问题可以使用树形结构来描述，其中每一个节点代表一个决策，每一条路径代表一个决策序列。

换句话说，如果问题包含明确的决策概念，并且解是通过一系列决策产生的，那么它就满足决策树模型，通常可以使用回溯来解决。

在此基础上，动态规划问题还有一些判断的“加分项”。

问题包含最大（小）或最多（少）等最优化描述。
问题的状态能够使用一个列表、多维矩阵或树来表示，并且一个状态与其周围的状态存在递推关系。

相应地，也存在一些“减分项”。
问题的目标是找出所有可能的解决方案，而不是找出最优解。
问题描述中有明显的排列组合的特征，需要返回具体的多个方案。

如果一个问题满足决策树模型，并具有较为明显的“加分项”，我们就可以假设它是一个动态规划问题，并在求解过程中验证它。


## Links

- [Algorithm Analysis](/docs/CS/Algorithms/Algorithms.md?id=algorithm-analysis)