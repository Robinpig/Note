## Introduction

Memcached 的配置分为**启动参数**（启动时一次性）和**运行时调优**（通过 `stats` 或 `lru` 命令在线改）。绝大多数场景下，默认参数已经够用，但在极端负载或特殊部署模式下，了解参数含义有助于压测和调优。

## Startup Parameters

所有参数以 `-flag value` 的形式传给 `memcached` 进程。常用的：

### 核心资源

| 参数 | 默认 | 含义 |
| :-- | :-- | :-- |
| `-m N` | 64 | 总内存上限（MB），包含本地缓存 + proxy 开销 |
| `-t N` | 4 | worker 线程数，建议等于 CPU 核心数 |
| `-c N` | 1024 | 最大同时连接数 |
| `-P path` | 无 | PID 文件路径 |

### 网络

| 参数 | 默认 | 含义 |
| :-- | :-- | :-- |
| `-p N` | 11211 | 监听端口 |
| `-l addr` | 0.0.0.0 | 监听地址（只绑 localhost 可以降低安全风险） |
| `-U N` | 11211 | UDP 端口（0 = 关闭） |

### Slab Allocation

| 参数 | 默认 | 含义 |
| :-- | :-- | :-- |
| `-f factor` | 1.25 | 增长因子，相邻 slabclass 的 chunk size 比率 |
| `-n bytes` | 48 | 最小 chunk 大小（8 字节对齐后是 96 字节） |
| `-I bytes` | 1MB | 单个 value 的最大尺寸 |
| `-M` | 无 | 内存耗尽时**不做淘汰**，返回错误（默认会淘汰） |

### 高级 / Modern LRU

| 参数 | 默认 | 含义 |
| :-- | :-- | :-- |
| `-o modern` | 已废弃（1.5.0 起默认开启） | 启用 modern LRU |
| `-o max-hot-percent=X` | 20 | HOT 占比上限 |
| `-o max-warm-percent=X` | 30 | WARM 占比上限 |
| `-o max-hot-age=X` | 0.1 | HOT 尾部年龄相对 COLD 尾部年龄倍数 |
| `-o max-warm-age=X` | 2.0 | WARM 尾部年龄相对 COLD 尾部年龄倍数 |
| `-o temp_ttl=X` | -1（关闭） | TEMP LRU 的 TTL 阈值（秒） |
| `-o lru_crawler` | 已废弃（默认开启） | 启用 LRU Crawler |
| `-o slab_automover` | 已废弃（1.6.6 起默认开启） | 启用 slab 自动搬运 |
| `-o hashtable=multi_queue` | queue | 哈希表模式：`queue`（单队列）/ `multi_queue`（16 队列，降低锁争用） |

### Proxy

| 参数 | 默认 | 含义 |
| :-- | :-- | :-- |
| `-e file` | 无 | Lua 配置文件路径，启用内建 proxy |

### 安全

| 参数 | 默认 | 含义 |
| :-- | :-- | :-- |
| `-S` | 无 | Unix socket 路径（更安全，仅限本机访问） |
| `-U 0` | — | 关闭 UDP（某些旧版本 Memcached 有 UDP 放大攻击风险） |

## Runtime Tuning

### `lru` Command

```
lru mode flat|segmented       # 切换 LRU 模式
lru tune hot% warm% hot_age warm_age   # 在线调 HOT/WARM 配额
lru temp_ttl 60               # 在线设置 TEMP LRU 阈值
lru maintainer sleep 10       # 设置 LRU Maintainer 休眠毫秒数
```

调优的典型场景：

- 发现 HOT 队列长期超过 20% 但命中率没变化 → 可以调小 `max-hot-percent`，让更多 item 尽快流到 WARM。
- WARM 尾部有很多过期 item → 调小 `max-warm-age`，加速老化到 COLD。
- 有大量 TTL < 30 秒的临时 item → 开启 TEMP LRU。

### Slab Management

```
slabs reassign 3 5            # 手动把 slabclass 3 的 slab 移到 slabclass 5
slabs automover slab_balance 1.5   # slab automover 平衡系数
```

通常 Slab Automover（1.6.6+ 默认开启）已经够用，手动 reassignment 是给运维在极端情况下应急用的。

### `stats` 命令解读

调优的前提是看懂 `stats` 的输出。常用字段：

| 字段 | 含义 |
| :-- | :-- |
| `get_hits` / `get_misses` | 命中/未命中次数，计算命中率 |
| `evictions` | 主动淘汰次数（持续增长说明内存不够或数据量大） |
| `reclaimed` | LRU Crawler 主动回收的过期 item 数 |
| `bytes` | 当前缓存使用的内存（不包括未分配的 slab） |
| `bytes_total` | 总内存上限 `-m` |
| `curr_items` | 当前 item 总数 |
| `curr_connections` | 当前连接数 |
| `cmd_get` / `cmd_set` | GET/SET 命令次数 |
| `lru_hits` | LRU 子队列的命中分布（帮助判断分段是否合理） |

### `stats slabs`

查看各 slabclass 的分布，用于调 `-f` 增长因子：

```
stats slabs
STAT 1:chunk_size 96
STAT 1:chunks_per_page 10922
STAT 1:total_pages 1
STAT 1:total_chunks 10922
STAT 1:used_chunks 5123
STAT 1:free_chunks 5799
STAT 2:chunk_size 120
STAT 2:chunks_per_page 8738
...
```

如果某个 slabclass 的 `used_chunks` 长期接近 `total_chunks`，说明该 size 区间的 item 特别多，增长因子可能需要调大让相邻 slabclass 覆盖更宽的范围。

## Typical Tuning Scenarios

### Web Application Cache（默认够用）

通常 `-m 2048 -t 4` 就够了：2GB 内存、4 个 worker 线程。连接数 `-c 4096` 可以支撑几千个并发连接。

### High Concurrency（多核机器）

如果压测发现 worker 线程饱和（`stats` 里的 `threads` 字段显示 `busy`），调 `-t` 到 CPU 核心数。注意哈希表的锁争用在 `-t > 8` 后才会成为瓶颈，可以配合 `-o hashtable=multi_queue`。

### Small TTL Items（TEMP LRU）

如果业务有大量 `expire < 60s` 的临时 item，开启 `-o temp_ttl=30`，让它们进 TEMP LRU 被 Crawler 快速回收，不要占 HOT/WARM 的位置。

## Links

- [Memcached](/docs/CS/DB/Memcached.md)
- [Architecture](/docs/CS/DB/Memcached/Architecture.md)
- [Eviction](/docs/CS/DB/Memcached/Eviction.md)
- [Commands](/docs/CS/DB/Memcached/Commands.md)
- [Proxy](/docs/CS/DB/Memcached/Proxy.md)

## References

1. `man memcached` — 每个参数的官方说明
2. [Memcached GitHub — doc/protocol.txt](https://github.com/memcached/memcached/blob/master/doc/protocol.txt) — `stats` / `lru` / `slabs` 管理命令的完整输出字段
