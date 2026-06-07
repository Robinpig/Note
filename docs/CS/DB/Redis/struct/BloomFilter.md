## 布隆过滤器

布隆过滤器是一种数据结构，它可能报告包含实际上不存在的元素（假阳性），但保证正确报告包含的元素（**无假阴性**）。

位数组和哈希函数

不能删除元素

- 内存大小 m
- 哈希函数数量 k
- 元素数量 n

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

### 布隆过滤器的对立面

布隆过滤器的对立面是一种可能报告假阴性但永远不会报告假阳性的数据结构。
也就是说，它可能声称没有见过某个元素（实际上见过），但绝不会声称见过一个实际上不存在的元素。

## 参考

1. []()
2. [The Opposite of a Bloom Filter](https://www.somethingsimilar.com/2012/05/21/the-opposite-of-a-bloom-filter/)
