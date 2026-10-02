## Introduction

Bloom Filter（布隆过滤器）是一种**空间效率极高**的概率型集合，用来回答「某元素**可能存在**还是**一定不存在**」。
它不存储元素本身，只维护一个长度为 m 的位数组和 k 个哈希函数：插入时把元素经 k 个哈希映射到的位全部置 1，查询时这些位全为 1 才报「可能存在」。

- 任一对应位为 0 → **一定不存在**（无假阴性，false negative 为 0）；
- 所有位都为 1 → **可能存在**，但可能是多个其它元素恰好把这些位填满了（假阳性，false positive）。

## Operations

```
add(x):   for i in 1..k: bit[ h_i(x) mod m ] = 1
maybe(x): all bit[ h_i(x) mod m ] == 1 ?
```

标准 Bloom Filter 不支持删除（置 0 会误伤共享该位的其它元素）。需要删除可用 **Counting Bloom Filter**（位换成小计数器），代价是数倍空间。

## Parameters

设插入元素数为 n、位数组长度为 m、哈希函数个数为 k，假阳性率近似为：

```
p ≈ (1 − e^(−k·n/m))^k
```

工程取舍：

- m 越大、k 适中，假阳性越低；但 k 过大会让位很快被填满，假阳性反而升高。
- 对给定的 n 与目标 p，最优参数为 `m = −n·ln p / (ln 2)²`、`k = (m/n)·ln 2`。
- 直观记忆：每个元素约用 10 bit、k≈7 时，假阳性率约 1%。

Guava 的 `BloomFilter.create(funnel, expectedInsertions, fpp)` 会按预期容量和目标假阳性率自动算好 m、k。

## Use Cases

- **缓存穿透防护**：在查 [Redis](https://redis.io)/DB 前先用 Bloom Filter 拦截对不存在 key 的请求，避免大量恶意/随机 key 直接打到底层存储；判「一定不存在」直接返回。
- 大数据去重：爬虫 URL 去重、HBase/[Lucene](/docs/CS/Framework/ES/Lucene.md) 类系统判断某条目/段是否可能存在。
- LSM 存储里判断一个 key 是否可能在某个 SSTable 中，减少无效磁盘读取，见 [LSM](/docs/CS/Algorithms/tree/LSM.md)。
- 分布式成员/黑名单、弱一致的「见过吗」判断，能容忍极小误判率即可。

## Trade-offs

| 维度 | Bloom Filter | HashSet/完整存储 |
| --- | --- | --- |
| 空间 | 每位/每元素极省 | 存整个对象，大 |
| 误判 | 有假阳性、无假阴性 | 精确 |
| 删除 | 标准版不支持 | 支持 |
| 取值 | 只能判存在性，不能取回元素 | 可取回 |
| 扩展 | 容量需预估，超容量误判率上升；动态扩容用 Scalable/可伸缩变体 | 动态 |

## Links

- [Structure](/docs/CS/Algorithms/struct/Structure.md)
- [LSM Tree](/docs/CS/Algorithms/tree/LSM.md) — 用 Bloom Filter 跳过不含 key 的 SSTable
- [Algorithm Analysis](/docs/CS/Algorithms/Algorithms.md?id=algorithm-analysis)

## References

1. [Bloom Filter Calculator](https://krisives.github.io/bloom-calculator/)
2. [Bloom filter - Wikipedia](https://en.wikipedia.org/wiki/Bloom_filter)
