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

## References

1. []()
2. [The Opposite of a Bloom Filter](https://www.somethingsimilar.com/2012/05/21/the-opposite-of-a-bloom-filter/)
