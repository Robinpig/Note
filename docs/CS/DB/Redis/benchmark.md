## Introduction







### pipeline

```shell
> redis-benchmark -t set -q
SET: 106382.98 requests per second

> redis-benchmark -t set -q -P 2
SET: 206247.42 requests per second

> redis-benchmark -t set -q -P 3
SET: 305871.56 requests per second
```









## Links

- [Introduction](/docs/CS/DB/Redis/Cache.md)
- [Introduction](/docs/CS/DB/Redis/Concurrency.md)
- [Introduction](/docs/CS/DB/Redis/Jedis.md)
- [Introduction](/docs/CS/DB/Redis/Lettuce.md)
- [Introduction](/docs/CS/DB/Redis/Lock.md)
- [Introduction](/docs/CS/DB/Redis/Lua.md)

## References

1. [Redis 性能测试](https://www.runoob.com/redis/redis-benchmarks.html)

