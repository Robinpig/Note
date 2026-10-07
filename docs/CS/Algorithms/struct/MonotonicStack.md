## Introduction

单调栈是一种特殊的[栈](/docs/CS/Algorithms/struct/stack.md)数据结构，元素按递增或递减顺序保持。主要理念是在推动和弹出元素的同时保持这种秩序，这有助于高效解决各种问题。

Monotonic Stacks can be broadly classified into two types:

- Monotonic Increasing Stack
- Monotonic Decreasing Stack

将一个元素插入单调栈时，为了维护栈的单调性，需要在保证将该元素插入到栈顶后整个栈满足单调性的前提下弹出最少的元素

### 核心不变量

单调栈 = 一个普通栈 + 一条**排序不变量**：从栈底到栈顶，元素始终保持递增（或始终保持递减）。

插入新元素 $x$ 的动作固定为「先弹后压」：

1. 只要栈非空，且栈顶与 $x$ **不合序**（即破坏单调性的那一侧），就弹出栈顶；
2. 循环结束后压入 $x$。

「不合序」的方向由想要的单调性决定，这是最容易搞反的地方：

| 想要的单调性 | 弹栈条件 | 直觉 |
| --- | --- | --- |
| 递增（栈底→栈顶越来越大） | `stack.top() > x` | $x$ 比栈顶小，栈顶不再有存在价值 |
| 递减（栈底→栈顶越来越小） | `stack.top() < x` | $x$ 比栈顶大，同上|

单调栈成立的**前提**是：元素**只从一端进出**。一旦需要随机删除中间元素，栈顶弹出的顺序就不再受控，不变量立刻失效 —— 这正是它与单调队列的分界（见下文）。

### 单调递增 vs 单调递减栈

| 维度 | 单调递增栈 | 单调递减栈 |
| --- | --- | --- |
| 栈内顺序（栈底→栈顶） | 元素递增 | 元素递减 |
| 弹栈触发条件 | 新元素小于栈顶 | 新元素大于栈顶 |
| 栈顶代表什么 | 当前窗口/扫描位置的**最小**候选 | 当前窗口/扫描位置的**最大**候选 |
| 栈存值还是下标 | 多数题存下标（要算宽度/距离） | 多数题存下标 |
| 典型题型 | 柱状图最大矩形、接雨水 | 下一个更大元素、滑动窗口最大值 |
| 同构写法 | 维护"比它小"的那些元素 | 把不等号对调即为递减栈 |

两种栈的算法骨架完全一样，差异仅在比较方向与栈顶语义：**很多题目把`<` 改成 `>` 就从一个栈翻转到另一个栈**，不需要换整体思路。

### 为什么有效

核心不是"栈"这个容器，而是**每个元素至多入栈一次、出栈一次**。

虽然 `while` 循环嵌在 `for` 里，看起来是 $O(n^2)$，但总弹出次数不超过总压入次数，而压入次数恰好是 $n$：

$$\text{总代价} = \sum (\text{压入次数} + \text{弹出次数}) \le n + n = O(n)$$

这属于[均摊分析](/docs/CS/Algorithms/Amortized.md) 的经典范式：把「单次很贵」的操作摊到所有操作上，得到摊还代价是常数。单调栈是**均摊分析跑得最漂亮的例子之一**。

真正的价值在于对比：朴素做法（如"对每个元素向右扫到末尾"）是每个元素各自付 $O(n)$，总代价 $O(n^2)$。而单调栈通过「一旦发现某个元素永远不可能再成为答案，就立刻丢弃」，把重复劳动彻底消掉。栈里能留下来的元素，都是**还悬而未决、等着被未来某个元素结算**的候选。

顺带一提，栈中元素个数始终不超过 $n$，所以空间复杂度是 $O(n)$。

### 经典例题

#### 柱状图中最大的矩形

单调递增栈存**下标**（存值就失去了计算宽度的能力）。从左往右遍历，遇到更矮的柱子时结算被弹出柱子的最优宽度：

```java
int largestRectangleArea(int[] heights) {
    Deque<Integer> stack = new Deque<>();   // 栈底→栈顶递增，存下标
    int best = 0;
    for (int i = 0; i <= heights.length; i++) {
        int h = (i == heights.length) ? 0 : heights[i];   // 末尾补 0 哨兵，强制清空栈
        while (!stack.isEmpty() && heights[stack.peek()] >= h) {
            int top = stack.pop();
            // 弹出后新的栈顶就是左边界（不含），i - 1 是右边界（不含）
            int width = stack.isEmpty() ? i : i - stack.peek() - 1;
            best = Math.max(best, heights[top] * width);
        }
        stack.push(i);
    }
    return best;
}
```

宽度公式 `i - stack.peek() - 1` 的来历：右边界是 `i - 1`（因为 `heights[i] < heights[top]`，不能延伸到 `i`），左边界是弹出后的新栈顶 `+1`（它比 `heights[top]` 更矮），故宽度 $= (i-1) - (peek+1) + 1 = i - peek - 1$。栈空时左边界为 $-1$，宽度退化为 $i$。

时间 $O(n)$，空间 $O(n)$。

#### 下一个更大元素（Next Greater Element）

单调递减栈，从左往右一次扫描，答案是"每个位置右侧第一个严格大于它的元素"。

```java
int[] nextGreater(int[] nums) {
    int[] ans = new int[nums.length];
    Arrays.fill(ans, -1);
    Deque<Integer> stack = new Deque<>();   // 存下标，对应值递减
    for (int i = 0; i < nums.length; i++) {
        while (!stack.isEmpty() && nums[stack.peek()] < nums[i]) {
            ans[stack.pop()] = nums[i];     // nums[i] 就是被弹出位置的答案
        }
        stack.push(i);
    }
    return ans;
}
```

为什么正确：新元素 $x$ 到达时，所有比它小的栈顶元素，其"右侧第一个更大元素"就此确定为 $x$，可以立即结算并出栈；留在栈里的都是还没等到答案的。扫描结束仍未被弹出的，答案保持 $-1$。

时间 $O(n)$，空间 $O(n)$ —— 对比朴素的逐位置向右扫描是 $O(n^2)$。

#### 接雨水

同样用单调递减栈存下标。本质是逐层横向填水：每弹出一个"坑底"下标 `bottom`，若栈还非空，则 `stack.peek()` 是左侧挡板，宽度 $i - peek - 1$，水深 $\min(左侧高, 当前高) - heights[bottom]$：

```java
int trap(int[] height) {
    Deque<Integer> stack = new Deque<>();   // 存下标，对应值递减
    int water = 0;
    for (int i = 0; i < height.length; i++) {
        while (!stack.isEmpty() && height[stack.peek()] < height[i]) {
            int bottom = stack.pop();
            if (stack.isEmpty()) break;     // 左边没有挡板，蓄不住水
            int left = stack.peek();
            int width = i - left - 1;
            int depth = Math.min(height[left], height[i]) - height[bottom];
            water += width * depth;
        }
        stack.push(i);
    }
    return water;
}
```

注意与最大矩形不同的两点：弹栈条件是**严格小于**（相等的柱子不构成新挡板），且弹栈后可能栈空、需提前退出（左边没有墙）。时间 $O(n)$，空间 $O(n)$。

#### 滑动窗口最大值

这是**单调队列**（用双端队列实现），不是单调栈，但常被混为一谈，见下一节。

```java
int[] maxSlidingWindow(int[] nums, int k) {
    int[] out = new int[nums.length - k + 1];
    Deque<Integer> dq = new Deque<>();     // 存下标，对应值递减
    for (int i = 0; i < nums.length; i++) {
        while (!dq.isEmpty() && dq.peekFirst() <= i - k) dq.pollFirst();   // 队首滑出窗口
        while (!dq.isEmpty() && nums[dq.peekLast()] < nums[i]) dq.pollLast();
        dq.addLast(i);
        if (i >= k - 1) out[i - k + 1] = nums[dq.peekFirst()];
    }
    return out;
}
```

队首永远保持窗口内最大值的下标。时间 $O(n)$ —— 每个下标进出各至多一次。

### 与单调队列的区分

一句话：**栈只能一端进出，队列两端都能进出**，这个结构差异决定了适用题型。

| 维度 | 单调栈 | 单调队列 |
| --- | --- | --- |
| 数据结构 | 栈（单端） | 双端队列（两端） |
| 元素进出 | 只在栈顶 | 两端都可 |
| 典型实现 | 数组 / `Stack` / `Deque` | `ArrayDeque` / 双端队列 |
| 被弹出的元素 | **已彻底结算**，不再需要 | 从**队尾**弹出被新元素支配者 |
| 淘汰"过期"元素 | 做不到（只能弹栈顶） | 队首直接按窗口边界淘汰 |
| 适用问题 | 逐个元素找"下一个更大/更小"（答案不依赖滑动边界） | 固定大小窗口内的最值（答案依赖窗口左右边界） |
| 能否做滑动窗口 | 不能 | 能 |

**为什么栈做不了滑动窗口**：滑动窗口要求把「已经滑出窗口左边界的元素」从候选集合中除掉。这个元素在栈里可能是**中间位置**，而栈只能弹栈顶。若强行为了淘汰它而把上面的元素全弹掉，就破坏了不变量、丢失了后续仍需要的候选。队列则可以把过期下标从**队首**（另一端）干净地踢掉，因此天然适配窗口两端同时滑动的场景。

一个常见误解是"滑动窗口最大值也能用单调栈做"。实际上可以，但需要额外维护窗口起点、并在插入时做判断剪枝，最终仍要 $O(n)$ 且代码更复杂；直接用单调队列是标准解。

### 易错点

**栈空判定**。`while (stack.peek() ...)` 之前必须先判空，否则取栈顶直接抛异常。上面代码统一写成 `!stack.isEmpty() && ...`，短路求值保证安全。

**存下标还是存值**。要计算宽度、距离、或要回头修改答案数组时，**存下标**：柱状图最大矩形（要算宽度）、下一个更大元素（要写回 `ans[下标]`）都必须存下标。存值只在纯"求当前极值"时才够用。存下标还带来一个好处：比较时用 `heights[stack.peek()]` 间接访问，避免了重复读取。

**宽度公式的边界**。`i - peek - 1` 里的 `-1` 与空栈特判最容易漏。三个易错点：
- 忘记末尾补哨兵，导致全递增的输入（如 `[1,2,3]`）算不出最后一段宽度；
- 用 `>` 还是 `>=` 决定是否合并等高柱子，要与题意匹配（求"严格更大"时用 `>=` 会误吞等高元素）；
- 求雨水时栈空要 `break` 而不能继续算，否则把没有左墙的位置也算成蓄水。

**存成"值"而非"下标"导致无法算宽度**：这是初学最常见的结构性错误，一旦写错就很难自己看出来，建议默认一律存下标。

**单调方向选反**：记不住就用一条准则定锚——先问自己"我要找的是比我大的，还是比我小的"，然后栈里放"等着被结算的相反方向"。多写两遍比背结论可靠。

## Links

- [数据结构](/docs/CS/Algorithms/Algorithms.md?id=数据结构)
- [stack](/docs/CS/Algorithms/struct/stack.md)
- [queue](/docs/CS/Algorithms/struct/queue.md)

## References

1. [单调栈 - OI Wiki](https://oi-wiki.org/ds/monotonic-stack/)

