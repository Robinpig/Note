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









## References

1. [Redis 性能测试](https://www.runoob.com/redis/redis-benchmarks.html)

