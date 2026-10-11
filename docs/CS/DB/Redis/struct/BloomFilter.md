## Introduction

Bloom filter（布隆过滤器）用极小的空间回答「一个元素是否在集合中」，代价是存在假阳性、且难以删除。Redis 本体不提供该结构，要靠 4.0 引入的 module 机制外挂 RedisBloom。本页讲原理、参数与典型用法，相关类型见 [HyperLogLog](/docs/CS/DB/Redis/struct/HyperLogLog.md) 与 [bitmap](/docs/CS/DB/Redis/struct/bitmap.md)。

## Bloom Filter

A Bloom filter is a data structure that may report it contains an item that it does not (a false positive), but is guaranteed to report correctly if it contains the item (“no false negatives”).

bit array and hash functions

cannot delete elements

- memory size m
- hash function number k
- entity number n


$$
k=m/n\ln2
$$









在 Redis 中不能直接使用布隆过滤器，但我们可以通过 Redis 4.0 版本之后提供的 modules（扩展模块）的方式引入

git clone https://github.com/RedisLabsModules/redisbloom.git cd redisbloom make # 编译redisbloom



\> ./src/redis-server redis.conf --loadmodule ./src/modules/RedisBloom-master/redisbloom.s



它的经典使用场景包括以下几个：

- 垃圾邮件过滤
- 爬虫里的 URL 去重
- 判断一个元素在亿级数据中是否存在







## Opposite of a Bloom Filter

The opposite of a Bloom filter is a data structure that may report a false negative, but can never report a false positive.
That is, it may claim that it has not seen an item when it has, but will never claim to have seen an item it has not.

## Links

- [HyperLogLog](/docs/CS/DB/Redis/struct/HyperLogLog.md)
- [SDS](/docs/CS/DB/Redis/struct/SDS.md)
- [Stream](/docs/CS/DB/Redis/struct/Stream.md)
- [bitmap](/docs/CS/DB/Redis/struct/bitmap.md)
- [geo](/docs/CS/DB/Redis/struct/geo.md)
- [hash](/docs/CS/DB/Redis/struct/hash.md)

## References

1. [RedisBloom](https://github.com/RedisBloom/RedisBloom)
2. [The Opposite of a Bloom Filter](https://www.somethingsimilar.com/2012/05/21/the-opposite-of-a-bloom-filter/)
