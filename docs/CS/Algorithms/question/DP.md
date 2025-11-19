





 

## Climbing Stairs

给定n 节台阶，每次可以走一步或走两步，求一共有多少种方式可以走完这些台阶

这是十分经典的斐波那契数列题。定义一个数组dp，dp[i] 表示走到第i 阶的方法数。因为

我们每次可以走一步或者两步，所以第i 阶可以从第i-1 或i-2 阶到达。换句话说，走到第i 阶的

方法数即为走到第i-1 阶的方法数加上走到第i-2 阶的方法数。这样我们就得到了状态转移方程

dp[i] = dp[i-1] + dp[i-2]。

 

House Robber (Easy)

 

假如你是一个劫匪，并且决定抢劫一条街上的房子，每个房子内的钱财数量各不相同。如果

你抢了两栋相邻的房子，则会触发警报机关。求在不触发机关的情况下最多可以抢劫多少钱。

输入输出样例

输入是一个一维数组nums[]，表示每个房子的钱财数量；输出是劫匪可以最多抢劫的钱财数量

 

定义一个数组dp，dp[i] 表示抢劫到第i 个房子时，可以抢劫的最大数量

d[i] = max(d[i-1] , nums[i-1] + d[i-2])

 


```cpp
int rob(int nums[]){

  if(nums[].length == 0)

     return;

 if(nums[].length == 1)

     return nums[0];

  int n = nums.length;

  int pre1 = 0;

  int pre2 = 0;

  int cur = 0;

  

  int[] dp = new int[n];

  for(int i = 0 ; i < n, ++i){

     cur = max(pre1, nums[i] + pre2);

     pre2 =pre1;

     pre1 = cur;

  }

  return dp;

 

}
```






Arithmetic Slices (Medium)

题目描述

给定一个数组，求这个数组中连续且等差的子数组一共有多少个

 

输入输出样例

输入是一个一维数组，输出是满足等差条件的连续字数组个数

 

要求是等差数列，可以很自然的想到子数组必定满足num[i] - num[i-1]

= num[i-1] - num[i-2]。然而由于我们对于dp 数组的定义通常为以i 结尾的，满足某些条件的子数

组数量，而等差子数组可以在任意一个位置终结，因此此题在最后需要对dp 数组求和。

 

d[i] = d[i-1] + 1

一段连续的等差数组

3，4，5，6.。。

1，2，3，4

总3，6，10

 

fn= sum(d[])

 

 

Minimum Path Sum (Medium)

题目描述

给定一个m Å~ n 大小的非负整数矩阵，求从左上角开始到右下角结束的、经过的数字的和最

小的路径。每次只能向右或者向下移动。

输入输出样例

输入是一个二维数组，输出是最优路径的数字



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



 

 

*Matrix (Medium)*

*题目描述*

*给定一个由**0* *和**1* *组成的二维矩阵，求每个位置到最近的**0* *的距离。*

*输入输出样例*

*输入是一个二维**0-1* *数组，输出是一个同样大小的非负整数数组，表示每个位置到最近的**0*

*的距离。*

 

*题解：*

*BFS* *将为**0**的元素加入队列 然后迭代队列 多次遍历矩阵* 

 

 

*Perfect Squares (Medium)*

*题目描述*

*给定一个正整数，求其最少可以由几个完全平方数相加构成*

*输入输出样例*

*输入是给定的正整数，输出也是一个正整数，表示输入的数字最少可以由几个完全平方数相*

*加构成。*

*Input: n =13*

*Output: 2*

*dp[i] = 1 + min(dp[i-1], dp[i-4], dp[i-9] · · · )**。*

*状态转移方程。*

 

*f[i]=1+ \min{j=1}^{[\sqrti]}f[i-j^2]*

 

*其中* *f[0]=0* *为边界条件，实际上我们无法表示数字* *0**，只是为了保证状态转移过程中遇到* *j* *恰为* 

*i*

 

 *的情况合法。*

 

*同时因为计算* *f[i]* *时所需要用到的状态仅有* *f[i−j* 

*2*

 *]**，必然小于* *i**，因此我们只需要从小到大地枚举* *i* *来计算* *f[i]* *即可。*

 

 

public class PerfectSquares {

  public static void main(String[] args) {

​     System.out.println(numSquares(15));

  }

 

  public static int numSquares(int n) {

​    int[] f = new int[n + 1];

​    for (int i = 1; i <= n; i++) {

​      int min = Integer.MAX_VALUE;

​      for (int j = 1; i - j * j >= 0; j++) {

​        min = Math.min(min, f[i - j * j] + 1);

​      }

​      f[i] = min;

​    }

​    return f[n];

  }

}

 

 

 

四平方和定理（Lagrange's Four-square Theorem），又称拉格朗日四平方和定理，是数论领域的重要定理。该定理指出每个正整数均可表示为4个整数的平方和，但不一定能用3个平方和表示（如7），这一结论属于费马多边形数定理与华林问题的特例

 

当且仅当 n=4 k ×(8m+7) 时，n 可以被表示为至多三个正整数的平方和。因此，当 n=4 k×(8m+7) 时，n 只能被表示为四个正整数的平方和。此时我们可以直接返回 4

 

 

给定 n 个非负整数表示每个宽度为 1 的柱子的高度图，计算按此排列的柱子，下雨之后能接多少雨水。

 

 

输入：height = [0,1,0,2,1,0,1,3,2,1,2,1]

输出：6

解释：上面是由数组 [0,1,0,2,1,0,1,3,2,1,2,1] 表示的高度图，在这种情况下，可以接 6 个单位的雨水（蓝色部分表示雨水）。

 

 

 

输入：height = [4,2,0,3,2,5]

输出：9

 

 

 

单调栈 记录下标 只有当右侧的高度>栈顶下标的高度时 出栈 以栈顶和当前位置下标差值 - 1为宽度 高度取当前高度与栈顶高度差值 新栈顶高度之间的最小值

 

双指针 储水的两边最高的高度先定义 Lmax 和 Rmax， 再通过两个指针 left 和 right 进行遍历

木桶原理 储水只取决于最短的板 所以 当 height[left]

 

 

 

 
```
public int trap(int[] height) {

​    int ans = 0;

​    int left = 0, right = height.length - 1;

​    int leftMax = 0, rightMax = 0;

​    while (left < right) {

​      leftMax = Math.max(leftMax, height[left]);

​      rightMax = Math.max(rightMax, height[right]);

​      if (height[left] < height[right]) {

​        ans += leftMax - height[left];

​        ++left;

​      } else {

​        ans += rightMax - height[right];

​        --right;

​      }

​    }

​    return ans;

  }
```
 




## Links

