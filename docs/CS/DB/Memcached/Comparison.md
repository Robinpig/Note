## Introduction

Memcached 常和 Redis、Dragonfly 放在一起对比——三者都是内存键值存储，但**设计哲学从根本上不同**。Memcached 诞生于 2003 年，定位就是「最轻量的纯缓存」；Redis 诞生于 2009 年，定位是「数据结构服务器」；Dragonfly 诞生于 2020 年，定位是「垂直扩展的 Redis/Memcached 兼容替代」。它们不是替代品，而是解决不同问题的三件工具。

## Head-to-Head

| 维度 | Memcached 1.6.x | Redis 8.x / 7.x | Dragonfly |
| :-- | :-- | :-- | :-- |
| 定位 | 纯缓存 | 内存数据结构服务器 | 垂直扩展缓存 |
| 核心数据类型 | KV only | String / Hash / List / Set / ZSet / Stream / Bitmap / HyperLogLog / BloomFilter 等 | 兼容 Redis 的所有类型 |
| value 语义 | **不透明字节串** | 强类型、可遍历、可部分修改 | 强类型（Redis 协议层） |
| 持久化 | **无** | RDB + AOF（可选） | RDB + AOF（兼容 Redis 格式） |
| 过期方式 | TTL 秒数 | TTL 秒数 / Unix 绝对时间 | 同 Redis |
| 服务端分片 | **无**（客户端分片） | Redis Cluster（16384 CRC16 槽） | Shared-nothing thread-per-core |
| 多线程 | **Worker 线程池**（默认 4，各独立 event loop） | **主事件循环单线程 + 可选 IO 线程 + 后台线程**（数据操作仍串行） | **Thread-per-core**（每个 shard 独占线程） |
| CPU 扩展 | 读密集近乎线性到 48 核 | 数据操作单线程，靠 Cluster 横向扩展 | 单实例吃满所有核心 |
| 单机 QPS | 百万级（读） | ~100 万（单线程），靠 Cluster 加 N 倍 | 千万级（单实例） |
| 协议 | 文本 / 二进制 / Meta | RESP2 / RESP3 | RESP2 / RESP3 + Memcached 文本 + HTTP |
| 事务 | CAS（单 key 条件写） | MULTI/EXEC（有限隔离） + Lua | Lua 脚本（单 shard 原子） |
| 发布订阅 | 无 | 原生 Pub/Sub + Stream Consumer Group | 兼容 Redis Pub/Sub |
| 许可证 | BSD-3-Clause | RSALv2 + SSPLv1 + AGPLv3（8.x） / BSD（≤ 7.2.x） | BSL 1.1（商业使用免费，4 年后 Apache 2.0） |
| 典型部署 | 多节点集群 + 客户端一致性哈希 | 主从哨兵 / Cluster | 单实例大机器（32+ 核、数百 GB 内存） |

## Key Differences Explained

### Opaque Value vs. Typed Value

这是三者最本质的区别：

- **Memcached**：`set foo 0 3600 5\r\nhello\r\n` 里的 value 是原始字节 `hello`，服务端完全不知道它是字符串、JSON 还是整数。`incr` 只在 value 恰好是可解析的数字串时有效（属于偶然特性，不是设计特性）。
- **Redis**：`HSET user:1 name alice age 30` 里服务端知道这是一个 Hash 结构，可以单独修改字段（`HSET user:1 age 31`），也可以按字段查询（`HGET user:1 name`）。
- **Dragonfly**：在 Redis 协议之下实现了 thread-per-core，但对客户端暴露的是完整的 Redis 类型语义。

**选型要点**：如果你的 value 本身就是一个序列化好的 blob（比如 protobuf 对象、序列化后的 JSON），Memcached 的不透明反而性能更高——因为省掉了类型解析的开销。但如果你需要在缓存内部做 `HGETALL`、`ZRANGE` 这样的部分操作，Redis/Dragonfly 是唯一选择。

### No Persistence vs. Persistence

Memcached **完全不写磁盘**，进程重启数据全丢。

- 这意味着启动极快（从不需要从磁盘加载状态），内存也可以全部用来存 item，不浪费 RDB/AOF 的 buffer 空间。
- 代价是重启后必须从源头（数据库、API）重新填充缓存，这叫「冷启动」——在高并发场景下可能压垮后端。

Redis 和 Dragonfly 都有 RDB/AOF，但 Redis 的 AOF fsync 策略（everysec / always / no）影响延迟，Dragonfly 宣称在保持 Redis 兼容的前提下用更高效的 IO 路径把 RDB/AOF 的开销降到可以忽略。

**选型要点**：如果你的缓存**允许冷启动**（比如热数据会在几秒内自然回流），Memcached 更轻量；如果你的缓存**承载了不能丢失的数据**（比如计数器、排行榜实时状态），Redis/Dragonfly 更安全。

### Client-Side vs. Server-Side Distribution

| | 客户端分片 | 服务端分片 |
| :-- | :-- | :-- |
| 代表 | Memcached + 一致性哈希客户端 | Redis Cluster、Codis、Dragonfly |
| 分片感知者 | 客户端应用 | 服务端内部协调 |
| 多 key 操作 | 跨节点需要 scatter-gather | 跨 slot 失败（Redis Cluster）/ 跨 shard 有事务开销 |
| 故障恢复 | 客户端切换到备选节点 | 服务端自动 slot/shard 迁移 |
| 运维复杂度 | 客户端需要配置节点列表 | 服务端需要配置集群 |

**选型要点**：应用可以改客户端 → Memcached 客户端分片最轻量；应用不想改客户端 → Redis Cluster / Dragonfly 的服务端分片更省心。

## When to Choose Which

### Choose Memcached When

- value 是序列化 blob，不需要类型语义。
- 缓存**允许冷启动**（重启后从数据库/API 回源填充）。
- 应用愿意用支持一致性哈希的客户端（Twemcache、libmemcached）。
- 需要最大化 QPS、最小化 CPU 和内存开销。
- 不需要发布订阅、事务、Lua 脚本、Pipeline 以外的复杂操作。

### Choose Redis When

- value 有类型语义（Hash、ZSet、Stream 等）。
- 需要持久化（RDB/AOF）。
- 需要服务端分片（Cluster）而不想改客户端。
- 需要发布订阅、Lua、事务、Pipeline 等丰富特性。
- 数据同时承担「缓存 + 轻量数据库」双重角色。

### Choose Dragonfly When

- 想**直接替换 Redis**（协议完全兼容，应用改连接串即可）。
- 单机器有 32+ 核心、数百 GB 内存。
- 不想维护 Redis Cluster 的分片和故障转移。
- 商业使用、BSL 许可可接受。

## Memory Efficiency

三者都在内存里跑，内存效率是关键。

- **Memcached**：Segmented LRU + LRU Crawler + Slab Automover 的组合大幅降低了死内存占比；Slab 机制避免了碎片。实测在相同内存上限下，Memcached 的「有效 item 数」约比 Redis Cluster 多 15%~30%（取决于 value 大小分布）。
- **Redis**：8.x 的 Compact Hash 让 Hash 字段名共享存储，内存进一步下降；但 Redis 的全局大对象（dict、skiplist）在极端碎片场景下可能浪费更多内存。
- **Dragonfly**：DashTable（分片哈希表）+ LFRU 淘汰算法，宣称相同 QPS 下内存比 Redis 低 30%。

## Links

- [Memcached](/docs/CS/DB/Memcached.md)
- [Redis](/docs/CS/DB/Redis/Redis.md)
- [Dragonfly](/docs/CS/DB/Dragonfly.md)
- [Memory Allocation](/docs/CS/DB/Memcached/Memory_Allocation.md)
- [Eviction](/docs/CS/DB/Memcached/Eviction.md)
- [Distributed](/docs/CS/DB/Memcached/Distributed.md)

## References

1. [Redis vs Memcached: Which is Best for Caching?](https://redis.io/docs/manual/keyspace/) — Redis 官方对比
2. [Dragonfly vs Redis Performance](https://dragonflydb.io/blog/benchmarks) — Dragonfly 基准测试
3. [Memcached GitHub — doc/](https://github.com/memcached/memcached/tree/master/doc) — 官方协议和特性文档
