## Introduction

树状数组（Fenwick Tree / Binary Indexed Tree，BIT）是一种支持**单点修改**与**前缀和查询**的紧凑数据结构，
代码量极小，两个核心操作都只需 O(log n)。它用「下标的二进制低位」把数组划分成若干区间，使一次前缀和只需累加少数几个节点。

下标从 1 开始。关键操作是 lowbit：`lowbit(i) = i & -i`，即 i 的二进制中最低位的 1 所对应的值：

```
i       二进制   lowbit
1       0001     1
2       0010     2
3       0011     1
4       0100     4
6       0110     2
8       1000     8
```

## Update / Query

- `tree[i]` 维护的区间长度是 `lowbit(i)`，即覆盖原数组 `[i-lowbit(i)+1, i]` 的和。
- **单点加**（给 i 位置加 delta）：沿 `i += lowbit(i)` 向上更新所有包含它的节点。
- **前缀和**（求 1..i 的和）：沿 `i -= lowbit(i)` 向下，把经过的区间块相加。

```java
void add(int i, long delta) {
    for (; i <= n; i += i & -i) tree[i] += delta;
}
long prefixSum(int i) {
    long s = 0;
    for (; i > 0; i -= i & -i) s += tree[i];
    return s;
}
```

由于每一步都消/进一个低位的 1，循环次数恰为下标的二进制位数，即 O(log n)。

## Range Query

树状数组原生只给前缀和，**区间和 [l, r] = prefixSum(r) − prefixSum(l−1)**。配合差分思想还能做区间更新、单点查询：
把差分数组 D 上的「区间加」转成两个单点修改。更高阶的用法（区间加 + 区间求和）用两个 BIT 维护差分及其加权项。

## Fenwick vs Segment Tree

| 维度 | Fenwick Tree | [Segment Tree](/docs/CS/Algorithms/tree/Segment-Tree.md) |
| --- | --- | --- |
| 适用运算 | 可逆的前缀聚合（和为主，也可前缀积/异或） | 任意可结合运算（min/max/gcd/区间最值/复杂合并） |
| 单点/区间 | 单点改 + 前缀/区间和；差分后可区间改 | 点改、区间改、区间查都直接支持 |
| 常数/代码 | 极小，约 10 行，数组 n+1 | 较大，通常 4n 空间，递归/懒标记 |
| 扩展性 | 弱（强依赖「前缀差分」） | 强，可挂懒标记、持久化、线段树合并 |

选型：只需要点改 + 区间和（如计数、逆序对、动态排名）优先 Fenwick，简单且常数小；
一旦查询是区间最值、需要复杂合并或懒更新，用 Segment Tree。

经典应用：求逆序对（离散化后从右往左，查询已出现中比当前小的数量）、动态维护频率与第 k 小、流式计数。

## Links

- [Segment Tree](/docs/CS/Algorithms/tree/Segment-Tree.md)
- [array](/docs/CS/Algorithms/struct/array.md)
- [Structure](/docs/CS/Algorithms/struct/Structure.md)

## References

1. [Fenwick tree - Wikipedia](https://en.wikipedia.org/wiki/Fenwick_tree)
