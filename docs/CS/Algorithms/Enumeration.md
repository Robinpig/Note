## Introduction

枚举（Enumeration / Brute Force，穷举/暴力法）是最朴素的算法策略：把问题所有可能的候选解**逐一列出并检验**，
满足条件者即为答案。它不依赖巧妙的数学性质，正确性最容易论证（只要候选空间覆盖完整、判定无误），
缺点是时间通常随规模指数或阶乘增长，只适合候选数量可控或作为其它方法的基线。

枚举的两个核心动作：**生成（generation）**所有候选，**判定（validation/filter）**候选是否合法或最优。

## 常见形式
- **线性枚举**：遍历数组/区间求最值、计数、求和，O(n)，是最常见形态。
- **子集枚举**：n 个元素的子集共 2^n 个。常用**位掩码**表示，第 i 位为 1 表示选取第 i 个元素：

```java
for (int mask = 0; mask < (1 << n); mask++) {   // 枚举全部 2^n 个子集
    for (int i = 0; i < n; i++)
        if ((mask >> i & 1) == 1) { /* 选了 i */ }
}
```

- **排列/组合枚举**：排列 n! 个、组合 C(n,k) 个，用 [回溯](/docs/CS/Algorithms/Backtracking.md) 系统地构造并剪枝。
- **笛卡尔积/多重循环**：嵌套 for 枚举多维选择（如两数之和的 O(n²) 暴力配对）。
- **状态/日期/网格枚举**：枚举所有坐标、所有日期、所有可能取值（如答案是整数且范围已知，直接枚举答案再验证，即「枚举答案」）。

## 优化
裸枚举常常超时，常见降复杂度手段：

- **剪枝（pruning）**：一旦部分候选已不可能合法/更优，立即放弃该分支——这正是从枚举过渡到 [回溯](/docs/CS/Algorithms/Backtracking.md)。
- **预处理/哈希**：[两数之和](https://leetcode.cn/problems/two-sum/) 用 [hash](/docs/CS/Algorithms/hash.md) 表把 O(n²) 配对降到 O(n)，本质是避免重复枚举已见过的候选。
- **排序 + [双指针](/docs/CS/Algorithms/Two-Pointers.md)**：有序后用单调性收缩枚举范围。
- **单调栈/队列、前缀和、[二分](/docs/CS/Algorithms/search.md)**：把「枚举每个候选逐一检查」换成更大步进。
- **折半枚举（meet-in-the-middle）**：把 n 拆成两半各 2^(n/2)，再合并，把 2^n 降到约 2^(n/2)·n。

## 适用场景
- 数据规模小（如 n ≤ 20～30 的子集/排列问题，2^20 ≈ 1e6 可接受）。
- 需要一个**绝对正确的基准解**去对拍、验证更复杂算法。
- 解空间本身就要求列出全部方案（如所有子集、所有排列、所有合法括号组合），此时枚举不是「慢方法」而是问题要求。
- 答案取值范围有限且可快速判定时，枚举答案 + 判定往往比直接求解更简单。

## Links

- [复杂度分析](/docs/CS/Algorithms/Algorithms.md?id=复杂度分析)
- [Backtracking](/docs/CS/Algorithms/Backtracking.md)
- [hash](/docs/CS/Algorithms/hash.md)
- [Two Pointers](/docs/CS/Algorithms/Two-Pointers.md)
- [search](/docs/CS/Algorithms/search.md)

## References

1. [Brute-force search - Wikipedia](https://en.wikipedia.org/wiki/Brute-force_search)
