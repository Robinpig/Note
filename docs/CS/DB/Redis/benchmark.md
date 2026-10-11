## Introduction

redis-benchmark 是官方自带的性能测试工具，随 Redis 源码一起编译（`src/redis-benchmark.c`）。

> [!NOTE]
> 版本基线 Redis 8.10.2。默认值取自 `src/redis-benchmark.c:1724-1757`，，网上多数资料不写这些，直接列几个容易踩的：

| 选项 | 默认值 | 说明 |
| :-- | :-- | :-- |
| `-c` | **50** | 并发连接数 |
| `-n` | **100000** | 每测试的请求总数 |
| `-d` | **3** | value 字节数（被夹在 1 ~ 1GB 之间，`:1443-1444`） |
| `-P` | **1** | pipeline 深度 |
| `-t` | 全部 | 只跑指定测试（如 `-t set,get`） |
| `--threads` | **0**（单线程模式） | 多线程压测；上限 `MAX_THREADS = 500`（`:47`） |
| `-k` | 1 | keepalive |
| 连接 | `127.0.0.1:6379` | `-h` / `-p` / `-s` / `-u` / `--tls` |

两个已失效的旧选项：**`-e` 现在无效**（`:1468-1471` 明确打印「-e option has no effect，出错即退出以避免假结果」）；`-l` 是 loop 模式而非别的意思。

另有两个压测相关的旗标容易漏：`--enable-tracking`（测客户端缓存，见父页Client side caching 段）与 `--cluster`（集群模式；此模式下 `--threads` 为 0 时会自动取节点数，`:1811-1812`）。

### pipeline

pipeline 深度是吞吐提升最明显的单一选项——它把 RTT 摊薄到多个命令上：

```shell
> redis-benchmark -t set -q
SET: 106382.98 requests per second

> redis-benchmark -t set -q -P 2
SET: 206247.42 requests per second

> redis-benchmark -t set -q -P 3
SET: 305871.56 requests per second
```

> [!WARNING]
> 这组数字**不能当作性能指标引用**：机器、`value` 大小、是否开持久化、是否开 IO 线程、是否 TLS 都会显著影响结果。它只说明一个定性规律 —— pipeline 深度增加接近线性地提升吞吐（2→约 2 倍，3→约 3 倍），因为同样的并发数下减少了网络往返次数。
>
> 真要评估容量，请固定上述变量后用 `--csv` 导出，并在同机同配置下与被测版本对比。

## Links

- [Cache](/docs/CS/DB/Redis/Cache.md)
- [Redis](/docs/CS/DB/Redis/Redis.md)

## References

1. [Redis 性能测试](https://www.runoob.com/redis/redis-benchmarks.html)