## Introduction

本篇汇集动态规划（dynamic programming, DP）的典型题解，涵盖状态转移方程的建立与边界处理。动态规划适用于**子问题重叠**的最优化与计数问题：与分治不同，DP 对每个子问题只求解一次并把结果存入表格，避免重复计算。题目按难度排列，每题给出「题目描述 → 输入输出 → 状态转移方程 → 实现」的完整链路。

DP 的统一套路是：定义状态 → 写状态转移方程 → 定边界条件 → 按依赖顺序（小到大 / 由外到内）递推。状态定义是否贴切决定了转移能否写出来，这是 DP 的主要难点。

## Climbing Stairs
给定 $n$ 节台阶，每次可以走一步或走两步，求一共有多少种方式可以走完这些台阶。

这是十分经典的斐波那契数列题。定义数组 `dp`，`dp[i]` 表示走到第 $i$ 阶的方法数。因为每次可以走一步或两步，所以第 $i$ 阶只能从第 $i-1$ 或 $i-2$ 阶到达，即方法数等于前两阶方法数之和，得到状态转移方程：

$$
dp[i] = dp[i-1] + dp[i-2]
$$

## House Robber (Easy)
**题目描述**：假如你是一个劫匪，决定抢劫一条街上的房子，每个房子内的钱财数量各不相同。如果你抢了两栋相邻的房子，则会触发警报机关。求在不触发机关的情况下最多可以抢劫多少钱。

**输入输出样例**：输入是一维数组 `nums[]`，表示每个房子的钱财数量；输出是劫匪可以最多抢劫的钱财数量。

定义 `dp[i]` 表示抢劫到第 $i$ 个房子时可以抢劫的最大数量。考虑第 $i$ 间的两种选择：要么不抢第 $i$ 间（得到 `dp[i-1]`），要么抢第 $i$ 间（则第 $i-1$ 间不能抢，得到 `nums[i-1] + dp[i-2]`）：

$$
dp[i] = \max\big(dp[i-1],\ nums[i-1] + dp[i-2]\big)
$$

因为只依赖前两项，可以用两个变量滚动递推，把空间降到 $O(1)$：

```java
public int rob(int[] nums) {
    if (nums == null || nums.length == 0) return 0;
    if (nums.length == 1) return nums[0];
    int pre2 = 0, pre1 = nums[0];
    for (int i = 1; i < nums.length; i++) {
        int cur = Math.max(pre1, nums[i] + pre2);
        pre2 = pre1;
        pre1 = cur;
    }
    return pre1;
}
```

## Arithmetic Slices (Medium)
**题目描述**：给定一个数组，求这个数组中连续且等差的子数组一共有多少个。

**输入输出样例**：输入是一维数组，输出是满足等差条件的连续子数组个数。

要求是等差数列，可以很自然地想到子数组必定满足 $\text{num}[i] - \text{num}[i-1] = \text{num}[i-1] - \text{num}[i-2]$。然而由于我们通常把 `dp` 定义为「以 $i$ 结尾的子数组数量」，而等差子数组可以在任意一个位置终结，因此此题最后需要对 `dp` 数组求和：

$$
dp[i] = dp[i-1] + 1, \qquad \text{ans} = \sum_i dp[i]
$$

例如连续等差段 $3,4,5,6,\dots$ 中长度 $1,2,3$ 的段各贡献一个，总计 $3 + 6 + 10$（按不同右端点累计）。

## Minimum Path Sum (Medium)
**题目描述**：给定一个 $m \times n$ 大小的非负整数矩阵，求从左上角开始到右下角结束的、经过的数字之和最小的路径。每次只能向右或者向下移动。

**输入输出样例**：输入是一个二维数组，输出是最优路径的数字。

用一维滚动数组即可做到 $O(mn)$ 时间、$O(n)$ 空间：

```go
func MinimumPathSum() {
    array := [3][3]int{{1, 3, 2}, {1, 2, 4}, {4, 3, 1}}
    min := dp(array)
    fmt.Println(min)
}

func dp(array [3][3]int) int {
    var dp [3]int
    for i, val := range array {
        for j, val2 := range val {
            if i == 0 && j == 0 {
                dp[j] = val2
            } else if i == 0 {
                dp[j] = dp[j-1] + val2
            } else if j == 0 {
                dp[j] = dp[j] + val2
            } else {
                dp[j] = min(dp[j-1], dp[j]) + val2
            }
        }
    }
    return dp[2]
}
```

## 01 Matrix (Medium)
**题目描述**：给定一个由 0 和 1 组成的二维矩阵，求每个位置到最近的 0 的距离。

**输入输出样例**：输入是一个二维 0-1 数组，输出是一个同样大小的非负整数数组，表示每个位置到最近的 0 的距离。

**题解**：BFS。将所有值为 0 的元素加入队列作为多源起点，然后迭代队列、多次遍历矩阵。本质是「到多源起点的最短路」，而无权图多源最短路正是 BFS 的典型应用（参见 [graph](/docs/CS/Algorithms/graph/graph.md) 的遍历一节）。

## Perfect Squares (Medium)
**题目描述**：给定一个正整数，求其最少可以由几个完全平方数相加构成。

**输入输出样例**：输入正整数 $n$，输出表示 $n$ 最少能由几个完全平方数相加构成。

- Input: $n = 13$
- Output: 2

**状态转移方程**：令 $f[i]$ 表示 $i$ 最少需要的完全平方数个数，则

$$
f[i] = 1 + \min_{j=1}^{\lfloor\sqrt{i}\rfloor} f[i - j^2]
$$

其中 $f[0] = 0$ 为边界条件。之所以设 $f[0] = 0$（尽管 0 本身无需任何平方数），是为了保证状态转移过程中遇到 $j^2$ 恰为 $i$ 时仍然合法。由于计算 $f[i]$ 所依赖的状态 $f[i - j^2]$ 必然小于 $i$，因此只需从小到大枚举 $i$ 即可。

```java
public class PerfectSquares {

  public static void main(String[] args) {
      System.out.println(numSquares(15));
  }

  public static int numSquares(int n) {
     int[] f = new int[n + 1];
     for (int i = 1; i <= n; i++) {
       int min = Integer.MAX_VALUE;
       for (int j = 1; i - j * j >= 0; j++) {
         min = Math.min(min, f[i - j * j] + 1);
       }
       f[i] = min;
     }
     return f[n];
  }
}
```

**四平方和定理**（Lagrange's Four-square Theorem）给出了上界：每个正整数均可表示为 4 个整数的平方和，但不一定能用 3 个表示（如 7）。更精确地，当且仅当 $n = 4^k \times (8m+7)$ 时，$n$ 不能表示为至多三个正整数的平方和，此时可直接返回 4。

## Trapping Rain Water
**题目描述**：给定 $n$ 个非负整数表示每个宽度为 1 的柱子的高度图，计算按此排列的柱子下雨之后能接多少雨水。

- Input: `height = [0,1,0,2,1,0,1,3,2,1,2,1]`
- Output: 6

因为每根柱子左右两边的最高高度中较低的一侧决定了该柱子上能积多少水（木桶原理），所以可以用：

- **单调栈**：记录下标，只有当右侧的高度大于栈顶下标的高度时才出栈；以「栈顶下标与当前位置下标之差 $- 1$」为宽度，高度取当前高度与栈顶高度的较小值。
- **双指针**：先定义 `leftMax` 与 `rightMax` 为已遍历部分两侧的最高高度，再令 `left`、`right` 两个指针相向而行。

```java
public int trap(int[] height) {
    int ans = 0;
    int left = 0, right = height.length - 1;
    int leftMax = 0, rightMax = 0;
    while (left < right) {
        leftMax = Math.max(leftMax, height[left]);
        rightMax = Math.max(rightMax, height[right]);
        if (height[left] < height[right]) {
            ans += leftMax - height[left];
            ++left;
        } else {
            ans += rightMax - height[right];
            --right;
        }
    }
    return ans;
}
```

## Links

- [Dynamic Programming](/docs/CS/Algorithms/DP/DP.md)
- [Recursion](/docs/CS/Algorithms/Recursion.md)
- [Monotonic Stack](/docs/CS/Algorithms/struct/MonotonicStack.md)