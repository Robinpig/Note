## 简介

HyperLogLog 是一种用于解决**基数计数**问题的概率数据结构，即使在输入元素的数量或体积非常大的情况下。
内存使用量是固定的，对于使用 Redis 实现的每个 HyperLogLog，使用**最多 12 KB**，标准误差为 **0.81%**。
使用的算法已从原始 HyperLogLog 算法进行了改进，使用了 [Flajolet 等人的《HyperLogLog: the analysis of a near-optimal cardinality estimation algorithm》](http://algo.inria.fr/flajolet/Publications/FlajoletFGM07.pdf) 中描述的思想以及原始论文中未描述的新方法。

计算集合中唯一元素的数量，就像获得 `SCARD` 的结果一样。

如果我们使用 `SADD`，它将保存所有元素，消耗大量内存；如果我们使用 HyperLogLog，它将消耗很少的内存。

HyperLogLog 的主要命令是 [PFADD](https://redis.io/commands/pfadd)、[PFCOUNT](https://redis.io/commands/pfcount) 和 [PFMERGE](https://redis.io/commands/pfmerge)。

- [PFADD](https://redis.io/commands/pfadd) 添加计数。
- [PFCOUNT](https://redis.io/commands/pfcount) 获取计数值。
- [PFMERGE](https://redis.io/commands/pfmerge) 合并。

PFADD 和 PFCOUNT 在概念上类似于集合的 SADD 和 SCARD。

```c
struct hllhdr {
    char magic[4];      /* "HLL" 的魔术字符串 */
    uint8_t encoding;   /* HLL_DENSE 或 HLL_SPARSE. */
    uint8_t notused[3]; /* 保留，未来使用，初始化为 0 */
    uint8_t card[8];    /* 缓存的基数，小端序，如果尚未缓存则为 0。 */
    uint8_t registers[]; /* 数据字节。 */
};
```

## 算法

### 伯努利过程

HyperLogLog 的底层实现使用了概率论中的 **伯努利过程**。

对于伯努利过程，在一次实验中，将硬币 A 和 B 抛掷，设 k 为在首次成功（正面）之前需要投掷的次数。

如果最大值为 k_max，则根据概率计算，实验次数大约为 $2^{k_max}$。

一旦集合中的数据量足够大，就可以近似出数据集中的唯一值数量。

举一个简单的例子来便于理解：

我们生成大量整数，并使用位序列中前导零的数量来估计唯一元素的数量。

例如，整数 4（二进制 100）在最低有效位中有 2 个前导零（假设位从右开始编号，从 0 开始），整数 10（二进制 1010）只有 1 个前导零。

如果我们从整数集合中看到的最大前导零数是 3，那么该集合中唯一整数的数量大约是 $2^3=8$。

### 分桶平均

为了减少误差，HyperLogLog 使用分桶平均，即通过将数据划分为 m 个桶，分别计算每个桶的估算值并取平均。

HyperLogLog 标准的误差公式为 $1.04 / \sqrt{m}$。

对于 Redis 的实现，m = 16384。

### 偏差修正

Redis 的 HyperLogLog 实现包括对小基数和大基数的偏差修正。

## 参考

1. [Redis 新数据类型——HyperLogLog](https://www.cnblogs.com/taojietaoge/p/16478371.html)
