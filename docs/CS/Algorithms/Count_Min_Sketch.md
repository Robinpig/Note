## Introduction

**Count-Min Sketch**（Cormode 与 Muthukrishnan 提出）是数据流场景下的**频次估计**结构：给定一个可能无限长的元素流，用远小于元素种类数的内存，回答「某个元素大约出现了多少次」。

它与两位「近亲」同属概率型数据结构，但回答的问题不同：

| 结构 | 回答的问题 | 误差方向 |
| :-- | :-- | :-- |
| [Bloom Filter](/docs/CS/Algorithms/struct/BloomFilter.md) | 元素见过吗 | 假阳性 |
| [HyperLogLog](/docs/CS/Algorithms/HyperLogLog.md) | 有多少种不同元素 | 相对误差 $1.04/\sqrt{m}$ |
| **Count-Min Sketch** | 某元素出现多少次 | 单侧高估（只多不少） |

## Structure and Operations

结构是一个 $d \times w$ 的计数器矩阵加 $d$ 个两两独立的哈希函数 $h_1, \dots, h_d$（每行用不同的一个，都映射到 $[0, w)$）：

```
add(x):      for i in 1..d:  C[i][ h_i(x) ] += 1
query(x):    return min over i of C[i][ h_i(x) ]
```

直觉：每个元素在每行恰好占一列，**自己的计数器一定累计了自己的全部计数**，所以最小值不会低于真实频次（永不低估）；其它元素撞进同一列只会把数字抬高，因此误差总是向上。取 $d$ 行的最小值，是为了让「所有行都撞车」的概率尽量小——一行撞车已不易，$d$ 行同时撞车的概率随 $d$ 指数下降。

## Guarantees

设流长度为 $N$，取 $w = \lceil e/\varepsilon \rceil$、$d = \lceil \ln(1/\delta) \rceil$，则以至少 $1-\delta$ 的概率，对任意元素：

$$
\hat{c}(x) \le c(x) + \varepsilon N
$$

空间是 $O\left(\frac{1}{\varepsilon}\ln\frac{1}{\delta}\right)$ 个计数器——**与流长度 $N$ 无关**，这是它作为流式算法的全部意义所在。单次 `add` 与 `query` 都是 $O(d)$，$d$ 是常数，故视为 $O(1)$。

两条重要性质：

- **可合并**：两个 sketch 对应单元格相加，即得到两股流合并后的 sketch（分布式场景下各节点本地统计后上传汇总）。
- **不支持删除**：标准版假设只增不减。计数器被别人的流量抬高后无法区分是谁的贡献，减量会让下界保证失效；需要删除时改用 Count-Mean-Min Sketch 或计数型方案。

## Variants and Relatives

- **Count-Sketch**（Charikar 等，2002）：哈希带符号，查询取各行估计的**中位数**，误差是**双侧**的（可高可低），但支持内积估计，是降维与频次估计的另一条路线。
- **Heavy Hitters**：Count-Min 回答「给定元素查频次」；找「出现最频繁的 $k$ 个」常用 Misra-Gries 计数器或 Space Saving，它们能给出带保证的热点名单。
- **保守更新**：只在「加了之后不会使该行低于当前估计」的行执行 +1，可显著降低撞车带来的高估，代价是失去可合并性。

## In Practice

- **网络与运维**：流量矩阵、IP/端口频次、热点 Key 统计（缓存击穿定位、大 Key 分析）。
- **NLP 与日志**：大规模语料词频、日志模板计数。
- **可直接使用的实现**：Redis（RedisBloom 模块）的 `CMS.INITBYDIM` / `CMS.INCRBY` / `CMS.QUERY` 系列命令；Apache DataSketches Java 库的 `ItemsSketch` 系列（含频次、去重、分位数一整套 sketch）。

## Links

- [Bloom Filter](/docs/CS/Algorithms/struct/BloomFilter.md)
- [HyperLogLog](/docs/CS/Algorithms/HyperLogLog.md)
- [Hash](/docs/CS/Algorithms/struct/hash.md)
- [Randomized](/docs/CS/Algorithms/paradigm/Randomized.md)
- [Algorithms](/docs/CS/Algorithms/Algorithms.md?id=classic-algorithm-topics)

## References

1. [Apache DataSketches](https://datasketches.apache.org/)
2. [Redis Probabilistic Data Types 文档](https://redis.io/docs/latest/develop/data-types/probabilistic/)
