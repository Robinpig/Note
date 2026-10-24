## Introduction

[Dragonfly](https://dragonflydb.io/) 是一个为现代多核硬件从零设计的**内存数据存储**，完全兼容 Redis™ 与 Memcached 的客户端协议，可作为二者的**直接替换（drop-in replacement）**。它的核心设计目标是**垂直扩展**：用一套 shared-nothing 的多线程架构，在单台大规格机器上把全部 CPU 核心与内存用满，避免 Redis 单进程触达单核天花板后被迫上集群。

> [!NOTE]
>
> DashTable（核心哈希表）与缓存淘汰算法是两件独立的事，常被混淆：DashTable 是数据结构，源自持久内存可扩展哈希论文；缓存淘汰是基于 2Q 的 **LFRU** 策略，直接实现在 DashTable 的桶排序语义里。下文分两节说明。

## Positioning

Dragonfly 的定位不是又一个缓存，而是「把 Redis 集群压成一单个进程」：

- **协议兼容**：RESP2/RESP3 + Memcached 文本协议 + HTTP（管理控制台/metrics）共用同一个端口，应用改连接串即可，无需改代码。
- **垂直扩展优先**：一个进程吃满所有核心与内存，用单实例替代多节点 Redis 集群，省掉分片管理与集群故障转移编排。
- **自托管免费、但非 OSI 开源**：许可证为 **BSL 1.1**（Business Source License）。内部生产使用免费，**禁止把它当作托管服务（DBaaS）转售给第三方**；满 4 年后转为 Apache 2.0。由以色列 DragonflyDB Ltd. 商业背书。
- **可移植退出**：可将数据导出为 Redis 的 `.rdb` 快照，回退到任意 Redis 兼容引擎没有锁定风险。

## Architecture

### Shared-Nothing Sharding

Dragonfly 用 **thread-per-core** 取代 Redis 的单线程事件循环：

- 键空间被划分为 `N` 个 shard（`DbSlice`），`N` 通常 ≤ 线程数；每个 shard 由运行在专用 proactor 线程上的 `EngineShard` **独占**。
- 分片映射沿用 Redis Cluster 的 **16384 个 CRC16 槽**概念以便心智对齐；开启 `lock_on_hashtags` 时按 key 的 `{hashtag}` 部分映射，保证同一 hashtag 的 key 落在同一分片。
- **无跨线程锁**：单 key 命令直达所属分片的 fiber 队列，零锁零跨线程通信；只有跨分片的多 key 命令才进入事务子系统。
- 线程之间只通过**消息传递**协调，从不共享锁——这就是「shared-nothing」在本项目中的确切含义。

### Helio and Fibers

`helio` 是 Dragonfly 自研的 I/O 与线程库（仓库内以 git submodule 形式存在，**除非给 helio 贡献代码否则不要改**）：

- **I/O 引擎**：Linux 上基于 **io_uring**（5.1+ 内核，用用户态/内核共享内存环规避热路径系统调用），非 Linux 平台回退到 epoll/kqueue。
- **Fiber 协作式多任务**：每个线程内挂一个基于 Boost.Fiber 的 fiber 调度器，多个 fiber 在一個线程的事件循环上复用执行。fiber 在等待网络读时让出，调度器切到另一个可运行 fiber——既无 OS 级线程切换，也无异步回调的「回调地狱」。
- **100% 非阻塞**：长时间命令（快照落盘、Lua 脚本执行）也在 fiber 内让出，连接不会因此卡死。

### DashTable

Redis 用链式哈希表（`dict`，两数组增量 rehash），单线程下好用，但无法被多线程并发访问而不加外部锁。Dragonfly 用 **DashTable** 替代：

- 源自论文 *Dash: Scalable Hashing on Persistent Memory*（Oukid et al., VLDB 2016），是 extendible hashing 的并发演进。
- **段式开放寻址**：全局目录把 hash 前缀映射到固定大小的 segment；每个 segment 是一组固定大小桶的数组（56 个常规桶 + 4 个 stash 溢出桶 ≈ 840 个槽位）。段内满负荷时一分为二，目录更新指向两个新段。
- **无 stop-the-world rehash**：增量扩容，不需要一次性重散列。
- **无状态遍历**：支持与 Redis 类似的 stateless dictionary traversal（如 `SCAN`），但内存开销更低。
- 实测空闲态内存比 Redis 字典低约 **30%**。

### Memory Management

- 每个 shard 使用 **mimalloc** 作为分配器（不是 jemalloc，所以 Redis 的 `activedefrag` 不适用）。
- `--maxmemory` 默认 `0`，含义是「可用内存的 80%」，并读取容器 cgroup 限制；每个线程至少需要 256 MB，否则启动即退出。
- 2.0 重写了集合/有序集合/哈希的核心结构，并**移除了继承自 Redis 的独立过期表**，改用指针打标签（pointer tagging）把 TTL 元数据直接编入 key 编码——常见负载下比 1.0 再省 **30%~40%** 内存。

## Caching

开启 `--cache_mode=true` 后，Dragonfly 在逼近 `maxmemory` 时自动淘汰，且**零额外内存开销**。

### LFRU Eviction (2Q-based)

Dragonfly 的统一缓存淘汰策略叫 **LFRU**（Least-Frequently-Recently-Used，自适应），算法内核是 **2Q**（Karedla et al., 1994, *2Q: A Low Overhead High Performance Buffer Management Replacement Algorithm*）：

- 与 LRU 不同，它**抵抗近期流量抖动**，不依赖 Redis 那种全局随机抽样近似。
- **每个条目零元数据**，运行开销为极小 `O(1)`。
- 实现上利用 DashTable 的弱排序语义：桶内槽位带等级/优先级（最左槽位 = 最高，slot 0…9）。新条目进入段内「试用缓冲」（小占比桶），被再次访问后才晋升到「受保护」区；未晋升者先被淘汰。

### RSS Guard and STICK

- `STICK` 命令可把指定 key 钉在内存里、免于淘汰。
- **RSS OOM 守卫**：`--rss_oom_deny_ratio` 默认 `1.25`——当 RSS 超过 `maxmemory × 1.25` 时，标记 `DENYOOM` 的命令失败，主端口拒绝新连接。
- 后台/心跳淘汰默认开启（`--enable_heartbeat_eviction`、`--enable_heartbeat_rss_eviction`），每心跳默认最多淘汰 100 个键。

## Persistence

### Forkless Snapshot

- Dragonfly 用**无 fork 的快照**消除 Redis `BGSAVE` 的写时复制内存尖峰：数据已分片，每个 shard 可独立对自己那部分做快照，同时继续服务读写，不需要复制整个地址空间。
- 两种格式：**RDB**（与 Redis/Valkey 兼容，可被它们加载）与 **DFS**（Dragonfly 自有格式，默认写入）。
- **2.0 的流式序列化**：复制/快照大集合（如 8 GB 有序集）时内存占用可预测、**完全无尖峰**，不再需要为最坏情况过度预置内存。
- `--snapshot_cron` 支持按 cron 调度自动快照；正常退出时落 `.rdb` 便于迁移。

### Replication Journal

- 通过 **journal 流（类 AOF）** 做复制；提供 cluster emulation 模式以兼容客户端（原生复制协议仍在演进）。
- 2.0 起可加载 **Valkey 9 RDB**（含同时含持久与过期字段的 hash），复制 backlog 改为按「年龄 + 内存预算」双维度保留，废弃固定长度配置。

## Tiering

- `--tiering` 开启 **SSD 分层存储**：key 与元数据留在内存，大 value 溢出到本地 NVMe；有效容量最高可放大 **8×**。
- 这是**唯一在社区版就提供 SSD 分层**的 Redis 兼容技术（Dragonfly Cloud 也已提供）。

## Protocol Compatibility

连接初始化时服务器自动识别协议，**同一端口（默认 6379）上并存**：

| 协议 | 用途 |
| :--- | :--- |
| RESP2 / RESP3 | Redis 客户端兼容（2.0 修复了大量 RESP3 边界） |
| Memcached 文本协议 | 通过 `--memcached_port` 开启 |
| HTTP | 管理控制台 + Prometheus metrics，无需额外配置 |

2.0 新增了 vector/hybrid search、JSON、ACL、Geo（`GEOSEARCHSTORE`）、HyperLogLog、Bloom/CMS/TopK 等结构；命令数从 1.0 的 **206** 增长到 2.0 的 **308**。TLS、基于 Redis 兼容 ACL 的访问控制、Lua 5.4 脚本均为原生支持。

## Operations

### HTTP Console and Metrics

- 默认在 RESP 主端口上允许 HTTP 访问，直接打开浏览器即是管理控制台。
- Prometheus 指标原生暴露在同一端口，无需 sidecar 或额外 exporter。

### Key Configuration

```bash
# 以缓存模式启动（逼近上限自动 LFRU 淘汰），并开启 SSD 分层
docker run --network=host --rm dragonflydb/dragonfly \
  --cache_mode=true \
  --tiering=/dev/nvme0n1 \
  --snapshot_cron="0 0 * * *"   # 每天 0 点快照
  # --memcached_port=11211      # 同时暴露 Memcached 协议
  # --rss_oom_deny_ratio=1.25   # RSS 守卫，默认即此值
```

## Transaction Model

- `Transaction` 类负责跨分片多 key 操作；单分片操作走「single-hop」直执行，无锁。
- 跨分片协调通过**消息传递**（基于数据库研究的 **VLL，Virtual Lock Lists**）实现无锁协作，而非自旋锁。
- 整体为**非阻塞乐观事务**，对外保证多 key 操作的原子性。

## Comparison with Redis and Valkey

| 维度 | Dragonfly | Redis | Valkey |
| :--- | :--- | :--- | :--- |
| 执行模型 | 多线程 shared-nothing（thread-per-core） | 命令执行单线程（6.0+ I/O 多线程） | 同 Redis（Linux 基金会 fork） |
| 扩展方式 | 垂直扩单机核心/内存 | 水平：Redis Cluster 分片 | 水平：集群分片 |
| 默认淘汰 | 非 cache_mode 下 `noeviction`；cache_mode 下内置 LFRU | 默认 `noeviction`，10 种策略 | 默认 `noeviction`，8 种策略 |
| 分配器 | mimalloc（无 `activedefrag`） | jemalloc | jemalloc |
| 快照 | 无 fork、流式、无尖峰；RDB + DFS | `BGSAVE` 写时复制有尖峰；RDB | 同 Redis（RDB v80） |
| 许可证 | BSL 1.1（4 年后转 Apache 2.0） | RSALv2/SSPLv1（2024-03 起） | BSD-3（Linux 基金会） |
| SSD 分层 | 社区版即有 | 无 | 无 |

> [!WARNING]
>
> 三者内存模型不同，**不要把 Redis 的 `maxmemory`/淘汰/碎片整理配置照搬给 Dragonfly**：Dragonfly 的 `maxmemory=0` 表示可用内存 80%，且默认无淘汰策略（除非开 `cache_mode`），写满直接 `Out of memory`；碎片整理是阈值触发、自动运行，没有 `activedefrag` 开关。

## Links

- [DataBases](/docs/CS/DB/DB.md)
- [Redis](/docs/CS/DB/Redis/Redis.md)
- [Valkey](/docs/CS/DB/Valkey.md)
- [Memcached](/docs/CS/DB/Memcached.md)

## References

1. [Dragonfly 官网](https://dragonflydb.io/)
2. [Announcing Dragonfly 2.0](https://www.dragonflydb.io/blog/announcing-dragonfly-2-0)
3. [Dragonfly Cache Design（2Q / LFRU 原理）](https://www.dragonflydb.io/blog/dragonfly-cache-design)
4. [Developing with Dragonfly: Cache-Aside](https://www.dragonflydb.io/blog/developing-with-dragonfly-part-01-cache-aside)
5. [dragonflydb/dragonfly（GitHub 仓库）](https://github.com/dragonflydb/dragonfly)
