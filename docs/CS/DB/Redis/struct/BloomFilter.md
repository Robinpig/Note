# Redis Bloom Filter: Source Deep Dive

## Introduction

Bloom filter（布隆过滤器）用极小空间回答「一个元素是否在集合中」，代价是存在假阳性、且传统实现难以删除。Redis 从 **8.0 起**通过 `BF.*` 命令提供布隆过滤器能力。

> 版本基线：Redis 8.10.2（commit 498ecd0d）。8.0.0 起 Bloom 随 Redis 发行版提供。

最容易写错的一点（也是本页旧版的错误）：

- **旧口径「Redis 本体不提供，必须外挂 RedisBloom module」只在 8.0 以前成立**。8.0.0 官方 release notes 原文：*“Stand alone RediSearch, RedisJSON, RedisTimeSeries, and RedisBloom modules are no longer needed as they are now part of Redis.”*、*“Redis Query Engine and 8 new data structures are now an integral part of Redis 8 … These nine components are included in all binary distributions.”*
- **准确表述**：这些组件是**随二进制发行版捆绑、由新增的 `redis-full.conf` 加载的内建能力**——不是「编译进 `redis-server` 核心」。它们作为独立 module 构建、随发行版一起分发；因此在 redis/redis 主仓库的 `src/commands.def` 里**搜不到 `BF.*` 命令**（8.10.2 已核实为 0 条）。8.0 起应表述为「作为 Redis 8 发行版内建组件提供，不再需要单独安装/加载 RedisBloom」。
- 随发行版新增的 ACL 类别包括 `@search`、`@json`、`@timeseries`、`@bloom`、`@cuckoo`、`@cms`、`@topk`、`@tdigest`（同样随组件提供，不在核心 `acl.c` 中）。

## Bloom Filter

A Bloom filter is a data structure that may report it contains an item that it does not (a false positive), but is guaranteed to report correctly if it contains the item (“no false negatives”).

核心是 bit array + 多个 hash 函数：

- memory size m
- hash function number k
- entity number n

最优哈希函数个数（给定 m/n）：

$$
k=m/n\ln2
$$

## Commands（8.x 内建，随发行版提供）

8.0 起 `BF.*` 由发行版组件提供，常用命令：`BF.RESERVE`（建过滤器，指定容量与错误率）、`BF.ADD` / `BF.MADD`（加元素）、`BF.EXISTS` / `BF.MEXISTS`（查存在性）、`BF.CARD`、`BF.INFO`。同一发行版还捆绑 Cuckoo filter（`CF.*`）、Count-min sketch（`CMS.*`）、Top-K（`TOPK.*`）、t-digest（`TDIGEST.*`）等新数据结构。

历史用法（8.0 以前）：需要自行编译 RedisBloom 并 `--loadmodule` 加载：

```shell
git clone https://github.com/RedisBloom/RedisBloom.git
cd RedisBloom && make
./redis-server redis.conf --loadmodule ./redisbloom.so
```

> [!NOTE]
> 上面这段 `--loadmodule` 仅作历史留档；8.0+ 二进制发行版已捆绑该组件并用 `redis-full.conf` 加载，无需手动编译/加载。

经典使用场景：垃圾邮件过滤、爬虫 URL 去重、判断一个元素是否在亿级数据中。

## Opposite of a Bloom Filter

The opposite of a Bloom filter is a data structure that may report a false negative, but can never report a false positive. That is, it may claim that it has not seen an item when it has, but will never claim to have seen an item it has not.

## Links

- [HyperLogLog](/docs/CS/DB/Redis/struct/HyperLogLog.md)
- [bitmap](/docs/CS/DB/Redis/struct/bitmap.md)
- [Redis Struct 总纲](/docs/CS/DB/Redis/struct/struct.md)
- [RediSearch（Query Engine）](/docs/CS/DB/Redis/RediSearch.md)

## References

- <https://github.com/redis/redis/tree/8.10.2>
- <https://redis.io/docs/latest/operate/oss_and_stack/stack-with-enterprise/release-notes/redisce/redisos-8.0-release-notes>
- <https://github.com/RedisBloom/RedisBloom>（历史独立模块）
