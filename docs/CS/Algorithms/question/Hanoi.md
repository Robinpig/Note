## Introduction

在经典汉诺塔问题中，有 3 根柱子(A、B、C) 及 N个不同大小的穿孔圆盘，盘子可以滑入任意一根柱子
一开始，所有盘子自上而下按升序依次套在第一根柱子(A)上（即每一个盘子只能放在更大的盘子上面） 目的是将这些盘子移动到其它柱子上(C) 并保证它们的原有顺序不变
移动圆盘时受到以下限制：

1. 每次只能移动一个盘子；
2. 盘子只能从柱子顶端滑出移到下一根柱子；
3. 盘子只能叠在比它大的盘子上。



## Recursion

我们将规模为 i 的汉诺塔问题记作 $f(i)$ 例如 $f(3)$ 代表将 3 个圆盘从 A 移动至 C 的汉诺塔问题。

- 对于问题 $f(1)$，即当只有一个圆盘时，我们将它直接从 A 移动至 C 即可
- 对于问题 $f(2)$，即当有两个圆盘时，由于要时刻满足小圆盘在大圆盘之上，因此需要借助 B 来完成移动

对于问题 $f(3)$，即当有三个圆盘时，情况变得稍微复杂了一些
因为已知 $f(1)$ 和 $f(2)$ 的解，所以我们可从分治角度思考，将 A 顶部的两个圆盘看作一个整体，这样三个圆盘就被顺利地从 A 移至 C 了

1. 令 B 为目标柱、C 为缓冲柱，将两个圆盘从 A 移至 B
2. 将 A 中剩余的一个圆盘从 A 直接移动至 C
3. 令 C 为目标柱、A 为缓冲柱，将两个圆盘从 B 移至 C

这样 $f(3)$ 就被分解成了两个子问题 $f(2)$ 和一个子问题 $f(1)$

可以得出解决汉诺塔问题的分治策略：将原问题 $f(n)$ 划分为两个子问题 $f(n-1)$ 和一个子问题 $f(1)$，并按照以下顺序解决这三个子问题

- 将 n-1 个圆盘借助 C 从 A 移至 B
- 将剩余 1 个圆盘从 A 直接移至 C
- 将 n-1 个圆盘借助 A 从 B 移至 C



$$
f(n) = 2f(n-1) + f(n)
$$

```java
/* 移动一个圆盘 */
void move(List<Integer> src, List<Integer> tar) {
    // 从 src 顶部拿出一个圆盘
    Integer pan = src.remove(src.size() - 1);
    // 将圆盘放入 tar 顶部
    tar.add(pan);
}

/* 求解汉诺塔问题 f(i) */
void dfs(int i, List<Integer> src, List<Integer> buf, List<Integer> tar) {
    // 若 src 只剩下一个圆盘，则直接将其移到 tar
    if (i == 1) {
        move(src, tar);
        return;
    }
    // 子问题 f(i-1) ：将 src 顶部 i-1 个圆盘借助 tar 移到 buf
    dfs(i - 1, src, tar, buf);
    // 子问题 f(1) ：将 src 剩余一个圆盘移到 tar
    move(src, tar);
    // 子问题 f(i-1) ：将 buf 顶部 i-1 个圆盘借助 src 移到 tar
    dfs(i - 1, buf, src, tar);
}

/* 求解汉诺塔问题 */
void solveHanota(List<Integer> A, List<Integer> B, List<Integer> C) {
    int n = A.size();
    // 将 A 顶部 n 个圆盘借助 B 移到 C
    dfs(n, A, B, C);
}
```

汉诺塔问题形成一棵高度为 n 的递归树，每个节点代表一个子问题，对应一个开启的 dfs() 函数，因此时间复杂度为 $O(z^n)$ ，空间复杂度为 $O(n)$



## Iterator





## Links

- [algorithm analysis](/docs/CS/Algorithms/Algorithms.md?id=algorithm-analysis)
