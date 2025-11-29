## Introduction

动态规划 (*dynamic programming)* 与分治方法相似，都是通过组合子问题的解来求解原问题（在这里， "programmin旷指的是一种表格法，并非编写计算机程序）

分治方法将问题划分为互不相交的子问题，递归地求解子问题，再将它们的解组合起来，求出原问题的解
与之相反，动态规划应用于子问题重叠的情况，即不同的子问题具有公共的子子问题（子问题的求解是递归进行的，将其划分为更小的子子问题）。
在这种情况下，分治算法会做许多不必要的工作，它会反复地求解那些公共子子问题
而动态规划算法对每个子子问题只求解一次，将其解保存在一个表格中，从而无需每次求解一个子子问题时都重新计算，避免了这种不必要的计算工作。

动态规划方法通常用来求解最优化问题 (*optimization problem)* 
这类问题可以有很多可行解，每个解都有一个值，我们希望寻找具有最优值（最小值或最大值）的解。我们称这样的解为问题的一个最优解(an optimal solution), 而不是最优解 (the optimal solution) , 因为可能有多个解都达到最优值

我们通常按如下 4 个步骤来设计一个动态规划算法：

1. 刻画一个最优解的结构特征
2. 递归地定义最优解的值
3. 计算最优解的值，通常采用自底向上的方法
4. 利用计算出的信息构造一个最优解

步骤 1~3 是动态规划算法求解问题的基础。如果我们仅仅需要一个最优解的值，而非解本身，可以忽略步骤 4 
如果确实要做步骤 4, 有时就需要在执行步骤 3 的过程中维护一些额外信息，以便用来构造一个最优解



朴素递归算法之所以效率很低，是因为它反复求解相同的子问题。
因此，动态规划方法仔细安排求解顺序，对每个子问题只求解一次，并将结果保存下来
如果随后再次需要此子问题的解，只需查找保存的结果，而不必重新计算。

因此，动态规划方法是付出额外的内存空间来节省计算时间，是典型的时空权衡 (*time-memory trade-off*) 的例子
而时间上的节省可能是非常巨大的：可能将一个指数时间的解转化为一个多项式时间的解。
如果子问题的数量是输入规模的多项式函数，而我们可以在多项式时间内求解出每个子间题，那么动态规划方法的总运行时间就是多项式阶的。



动态规划有两种等价的实现方法，下面以钢条切割问题为例展示这两种方法

第一种方法称为带备忘的自顶向下法 (*top-down with memoization*) 
此方法仍按自然的递归形式编写过程，但过程会保存每个子问题的解（通常保存在一个数组或散列表中）
当需要一个子问题的解时，过程首先检查是否已经保存过此解
如果是，则直接返回保存的值，从而节省了计算时间；否则，按通常方式计算这个子问题。
我们称这个递归过程是带备忘的 (memoized), 因为它“记住”了之前已经计算出的结果。



第二种方法称为自底向上法 (*bottom-up method*) 
这种方法一般需要恰当定义子问题”规模" 的概念，使得任何子问题的求解都只依赖于“更小的“子问题的求解。
因而我们可以将子问题按规模排序，按由小至大的顺序进行求解。当求解某个子问题时，它所依赖的那些更小的子间题都已求解完毕，结果已经保存。
每个子问题只需求解一次，当我们求解它（也是第一次遇到它）时，它的所有前提子问题都已求解完成



两种方法得到的算法具有相同的渐近运行时间，仅有的差异是在某些特殊情况下，自顶向下方法并未真正递归地考察所有可能的子问题。
由于没有频繁的递归函数调用的开销，自底向上方法的时间复杂性函数通常具有更小的系数。

### Subproblem

当思考一个动态规划问题时，我们应该弄清所涉及的子问题及子问题之间的依赖关系。

问题的子问题图准确地表达了这些信息
它是一个有向图，每个顶点唯一地对应一个子问题
若求子问题 x 的最优解时需要直接用到子问题 y 的最优解，那么在子问题图中就会有一条从子问题 x 的顶点到子问题 y 的顶点的有向边
例如，如果自顶向下过程在求解 x 时需要直接递归调用自身来求解 y, 那么子问题图就包含从 x 到 y 的一条有向边
我们可以将子问题图看做自顶向下递归调用树的“简化版”或“收缩版“，因为树中所有对应相同子问题的结点合并为图中的单一顶点，相关的所有边都从父结点指向子节点

自底向上的动态规划方法处理子问题图中顶点的顺序为：对于一个给定的子问题 x, 在求解它之前求解邻接至它的子问题 y( 邻接关系不一定是对称的）
自底向上动态规划算法是按“逆拓扑序" (*reverse topological sort)* 或“反序的拓扑序" (*topological sort of the transpose)* 来处理子问题图中的顶点
换句话说，对千任何子问题，直至它依赖的所有子问题均已求解完成，才会求解它。
类似地，我们可以用术语“深度优先搜索" (*depth-first search)* 来描述（带备忘机制的）自顶向下动态规划算法处理子问题图的顺序



问题图 $G=(V, E)$ 的规模可以帮助我们确定动态规划算法的运行时间。由于每个子问题只求解一次，因此算法运行时间等千每个子问题求解时间之和。
通常，一个子问题的求解时间与子问题图中对应顶点的度（出射边的数目）成正比，而子问题的数目等千子问题图的顶点数。
因此，通常情况下，动态规划算法的运行时间与顶点和边的数量呈线性关系



## 原理

适合应用动态规划方法求解的最优化问题应该具备的两个要素：最优子结构和子问题重叠

### Optimal substructure

用动态规划方法求解最优化问题的第一步就是刻画最优解的结构。如前文所述，如果一个问题的最优解包含其子问题的最优解，我们就称此问题具有最优子结构性质
因此，某个问题是否适合应用动态规划算法，它是否具有最优子结构性质是一个好线索（当然，具有最优子结构性质也可能意味着适合应用贪心策略
使用动态规划方法时，我们用子问题的最优解来构造原问题的最优解。因此，我们必须小心确保考察了最优解中用到的所有子问题

发掘最优子结构性质的过程中，实际上遵循了如下的通用模式：

1. 证明问题最优解的第一个组成部分是做出一个选择，例如，选择钢条第一次切割位置，选择矩阵链的划分位置等。做出这次选择会产生一个或多个待解的子问题。
2. 对于一个给定问题，在其可能的第一步选择中，你假定已经知道哪种选择才会得到最优解。你现在并不关心这种选择具体是如何得到的，只是假定已经知道了这种选择。
3. 给定可获得最优解的选择后，你确定这次选择会产生哪些子问题，以及如何最好地刻画子问题空间。
4. 利用“剪切—粘贴" (cut-and-paste) 技术证明：作为构成原问题最优解的组成部分，每个子问题的解就是它本身的最优解。证明这一点是利用反证法：假定子问题的解不是其自身的最优解，那么我们就可以从原问题的解中“剪切＂掉这些非最优解，将最优解＂粘贴”进去，从而得到原困囡 问题一个更优的解，这与最初的解是原问题最优解的前提假设矛盾。如果原问题的最优解包含多个子问题，通常它们都很相似，我们可以将针对一个子问题的＂剪切—粘贴“论证方法稍加修改，用于其他子问题。

一个刻画子问题空间的好经验是：保持子问题空间尽可能简单，只在必要时才扩展它

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

> [!TIP]
>
> 能够应用贪心算法的问题也必须具有最优子结构性质。贪心算法和动态规划最大的不同在于，它并不是首先寻找子问题的最优解，然后在其中进行选择，而是首先做出一次“贪心”选择—一在当时（局部）看来最优的选择 然后求解选出的子问题，从而不必费心求解所有可能相关的子问题

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


## LCS

最长公共子序列（Longest Common Subsequence，LCS）是动态规划中的经典问题，顾名思义，即求两个序列最长的公共子序列（可以不连续）

它的解法是典型的二维动态规划，大部分比较困难的字符串问题都和这个问题一个套路，比如说编辑距离。而且，这个算法稍加改造就可以用于解决其他问题

因为子序列类型的问题，穷举出所有可能的结果都不容易，而动态规划算法做的就是穷举 + 剪枝，它俩天生一对儿。所以可以说只要涉及子序列问题，十有八九都需要动态规划来解决

我们规定用 s[-1] 表示序列 s 的最后一个元素，用 s[:1] 表示 s 去掉最后一个元素后的子序列，
LCS[s1,s2] 表示s1和s2的LCS的长度。现在，假如我们有 abdcbab 和 bdcbabb 两个字符串，记为 s1 和 s2，我们要如何求它们的LCS呢

对于字符串 s1 和 s2，一般来说都要构造一个这样的 DP table：

 

为了方便理解此表，我们暂时认为索引是从 1 开始的，待会的代码中只要稍作调整即可。其中，dp[i][j] 的含义是：对于 s1[1..i] 和 s2[1..j]，它们的 LCS 长度是 dp[i][j]。

比如上图的例子，d[2][4] 的含义就是：对于 "ac" 和 "babc"，它们的 LCS 长度是 2。我们最终想得到的答案应该是 dp[3][6]。

 

用两个指针 i 和 j 从后往前遍历 s1 和 s2，如果 s1[i]==s2[j]，那么这个字符一定在 lcs 中；否则的话，s1[i] 和 s2[j] 这两个字符至少有一个不在 lcs 中，需要丢弃一个

 

 


```
class Solution {

  public int longestCommonSubsequence(String text1, String text2) {

​    int M = text1.length();

​    int N = text2.length();

​    int[][] dp = new int[M + 1][N + 1];

​    for (int i = 1; i <= M; ++i) {

​      for (int j = 1; j <= N; ++j) {

​        if (text1.charAt(i - 1) == text2.charAt(j - 1)) {

​          dp[i][j] = dp[i - 1][j - 1] + 1;

​        } else {

​          dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);

​        }

​      }

​    }

​    return dp[M][N];

  }

}
```





 LCS 算法，我们完全可以去掉表 b 。每个 c[i, j] 项只依赖千表 c 中的其他三项：

c[i 一 1, j] 、 c[i, j-1] 和心 -1, j-1] 。给定 c[i, j] 的值，我们可以在 0(1) 时间内判断出在计算心， j] 时使用了这三项中的哪一项





子串和子序列的区别在于，子串必须是连续的。求最长公共子串的长度和求最长公共子序列的长度的方法几乎一样

## Links

- [Algorithm Analysis](/docs/CS/Algorithms/Algorithms.md?id=algorithm-analysis)