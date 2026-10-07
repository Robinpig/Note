## Introduction

摊还分析（Amortized Analysis）用于评价「一系列操作」的平均代价，而不是单个操作的最坏情况。
某些数据结构偶尔会执行一次很贵的操作（如动态数组扩容、并查集路径压缩），但这种贵操作很少发生，
被其它大量廉价操作摊薄后，**每个操作的平均（摊还）代价仍然很低**。摊还分析给出的是有保证的上界，不依赖概率，这与「平均情况分析」（对输入分布取期望）不同。

三种经典方法：聚合分析、核算法（记账法）、势能法。

## 聚合分析
聚合分析直接求 n 次操作的总代价 T(n)，则每个操作摊还代价为 T(n)/n。

**动态数组（ArrayList/vector）append**：容量满时把数组翻倍扩容并拷贝全部元素。设从 1 开始：

```
扩容拷贝量: 1 + 2 + 4 + ... + 2^k < 2·2^k ≤ 2n
n 次 append 总代价 = 正常写入 n + 拷贝 < 3n
```

拷贝代价构成等比级数，总和不到 2n，所以 n 次 append 总代价 O(n)，**单次摊还 O(1)**。
尽管某一次 append 触发扩容是 O(n)，但不可能每次都触发，不能据此说平均是 O(n)。

## 记账法
核算法给每种操作指定一个「摊还费用」，提前为将来的贵操作存款：

- 一次 append 收费 3：1 付当场写入，1 预付自己将来被拷贝，1 预付某个旧元素被拷贝；扩容时用存款支付拷贝，不再额外计费。
- 关键约束：对任意操作序列，**存款余额始终非负**（总摊还费用必须始终覆盖总实际代价），否则说明费用定得太低。

## 势能法
势能法把「存款」表示为整个数据结构状态的函数 Φ(D_i)：

```
摊还代价 ĉ_i = 实际代价 c_i + Φ(D_i) − Φ(D_{i−1})
```

- 势能在廉价操作中积累（ΔΦ>0），在贵操作中释放（ΔΦ<0）来支付高代价；
- 只要 Φ(D_n) ≥ Φ(D_0)（通常取 Φ(D_0)=0），总摊还代价就是总实际代价的上界。

动态数组取 Φ = 2·(元素数 − 容量/2)，扩容瞬间势能正好支付搬迁，可同样证出 append 摊还 O(1)。

## 示例
| 数据结构/操作 | 单次最坏 | 摊还 | 说明 |
| --- | --- | --- | --- |
| 动态数组 append | O(n) | O(1) | 翻倍扩容，[array](/docs/CS/Algorithms/struct/array.md) |
| Stack 多弹（multipop） | O(n) | O(1) | 每个元素至多 push/pop 各一次 |
| 二进制计数器 +1 | O(k)（进位连锁） | O(1) | 第 i 位翻转 n/2^i 次，总和 < 2n |
| Splay Tree 操作 | O(n) | O(log n) | 势能 = 节点秩之和 |
| [并查集](/docs/CS/Algorithms/tree/Disjoint_Set.md) union/find | 接近 O(log n) | α(n) 反阿克曼 | 按秩合并 + 路径压缩，近乎常数 |

## 均摊与平均的区别
- **平均/期望分析**：对输入分布或随机算法求期望（如快速排序平均 O(n log n)），给定一个「坏输入」仍可能很慢。
- **摊还分析**：对**任意**操作序列保证 n 次总代价的上界，是确定性的最坏情况保证，只是把代价在时间上摊开。

## Links

- [Algorithms](/docs/CS/Algorithms/Algorithms.md)
- [Randomized](/docs/CS/Algorithms/Randomized.md)
- [array](/docs/CS/Algorithms/struct/array.md)
- [Disjoint Set](/docs/CS/Algorithms/tree/Disjoint_Set.md)

## References

1. [Introduction to Algorithms, Ch.17 Amortized Analysis](https://mitpress.mit.edu/9780262046305/introduction-to-algorithms/)
2. [Amortized analysis - Wikipedia](https://en.wikipedia.org/wiki/Amortized_analysis)
