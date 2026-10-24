## Introduction

Memcached **服务节点之间不通信**，集群能力完全由**客户端库**实现。这是它和 Redis Cluster、Codis、Dragonfly 等的根本区别——后者都有某种形式的服务端协调层。客户端分片的好处是服务端实现简单、单节点故障影响小；代价是**客户端需要知道整个集群的拓扑并自己维护路由**，节点增删时客户端要同步更新。

## Client-Side Sharding

客户端库（Twemcache、libmemcached、SpyMemcached 等）维护一份**静态的 Memcached 节点列表**。每次命令请求到 key 时：

1. 对 key 做 hash。
2. 用 hash 值在节点列表里找目标节点。
3. 直接连到目标节点发命令。

多个客户端用**相同的 hash 算法和节点列表**，保证同一个 key 总会被路由到同一个节点。这使得整个集群看起来像一个大缓存，其实每个节点是独立的小缓存。

### Hash Functions

客户端 hash 函数需要有足够的**均匀性**——理想情况下每个节点分到的 key 数量差不多。常用选择：

- **CRC32**：简单且快，但对节点数量敏感。
- **FNV-1a**：更好的 avalanche effect。
- **MD5 / SHA1**：分布最均匀但太慢，一般不用于分片路由。
- **一致性哈希（Consistent Hashing）**：ketama 环，节点增删时只有相邻节点的 key 受影响。

### Ketama Ring（一致性哈希的实现）

一致性哈希把节点均匀散布在一个 32 位 hash 环上，key 的 hash 值落到哪两个节点之间就归顺时针方向那个节点。Twemcache 和多数现代 Memcached 客户端都用 ketama 环。

ketama 环为**每个物理节点生成 100+ 个虚拟节点**（虚拟节点是对物理节点的 hash），散布在环上。这样即使只有 3~4 个物理节点，每个物理节点也有几百个环上位置，key 的分布可以非常均匀。

### Failover

客户端的分片逻辑里通常带**容错机制**：

- 如果目标节点超时或连接失败，客户端可以配置一个「备选节点」列表或 hash 环上的下一个节点，把请求临时发给它。
- 但这只适用于「读取」——写入到备选节点会破坏 key 的主从一致性（数据会分裂在两个节点上）。所以 failover 写入通常要么放弃、要么同步写入主节点和备选节点（写放大）。

## Node Topology Management

### Static List vs. Service Discovery

传统客户端用硬编码的节点列表，运维需要在应用配置里维护。现代做法：

1. **Consul / ZooKeeper / etcd**：节点注册自己，客户端订阅节点变化，动态更新 ketama 环。
2. **Kubernetes StatefulSet**：每个 Memcached 节点有稳定 DNS 名（memcached-0, memcached-1, ...），客户端按顺序解析后组成节点列表。
3. **内建 Proxy**（1.6.0+）：Lua 脚本里直接 `mcp.pool({ backends = ... })`，拓扑由 proxy 统一管理，对应用透明。

### Twemcache

Twemcache 是 Twitter 开源的 Memcached 客户端库（Python / Go / Java 都有实现），特点：

- 实现了 ketama 环一致性哈希。
- 支持从 ZooKeeper 动态获取节点列表。
- 有 pipeline 批处理和连接池。
- 是大规模 Memcached 集群的事实标准客户端。

### libmemcached

C 实现的 Memcached 客户端，支持一致性哈希、多线程、二进制协议，是其他语言客户端（Python 的 `python-memcached`、Ruby 的 `memcache` gem）的底层依赖。

## Proxy as Alternative

1.6.0 起的内建 Proxy 为「客户端分片」提供了一个服务端替代：

- 应用只连一个 proxy 实例（或 proxy 实例的 LB）。
- proxy 的 Lua 脚本里配置好后端 pool 和路由规则。
- 后端节点增删时只改 proxy 的 Lua 配置，应用无感。

这把「客户端分片」的复杂度转移到了服务端，代价是多了一跳网络和 Lua hook 的微秒级延迟。适合不想改客户端但需要灵活路由的场景。

## Comparison with Server-Side Distribution

| 维度 | Memcached 客户端分片 | Redis Cluster | Dragonfly |
| :-- | :-- | :-- | :-- |
| 分片位置 | 客户端 | 服务端（CRC16 槽） | 服务端（thread-per-core shards） |
| 节点协调 | 无 | 有（集群总线） | 无（shared-nothing） |
| 故障恢复 | 客户端 failover + 节点重加入自动 rehash | Gossip + slot 迁移 | 依赖 K8s 重建 pod |
| 写分裂 | 可能（failover 写） | 不会（slot 唯一归属） | 不会（shard 唯一归属） |
| 多 key 操作 | 跨节点需要 scatter-gather | 跨 slot 失败（除非 hash tag） | 跨 shard 有事务开销 |

## Links

- [Memcached](/docs/CS/DB/Memcached.md)
- [Proxy](/docs/CS/DB/Memcached/Proxy.md)
- [Redis](/docs/CS/DB/Redis/Redis.md)
- [Dragonfly](/docs/CS/DB/Dragonfly.md)

## References

1. [Scaling Memcached at Facebook](https://www.usenix.org/system/files/conference/nsdi13/nsdi13-final170_update.pdf) — Facebook 的大规模客户端分片实践
2. [Twemcache (Go)](https://github.com/twitter/twemcache) — 一致性哈希实现参考
3. [libmemcached](https://libmemcached.org/) — C 客户端
