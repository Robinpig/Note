## Introduction

[SSDB](https://github.com/ideawu/ssdb) 是国人开发的开源（BSD）NoSQL 数据库，定位是"**磁盘版 Redis 替代**"：网络协议和客户端 API 与 Redis 高度兼容（支持 redis-cli、大多数语言的 Redis 客户端直连），但底层用 [LevelDB](/docs/CS/DB/LevelDB/LevelDB.md)（LSM-Tree）做主存储，数据落在磁盘上，单机可以承载远超内存容量的数据。适合"想用 Redis 的数据结构和协议、但数据量大到放内存不划算、且能接受磁盘延迟"的场景。

## Architecture

- 网络层自研 NIO 框架，兼容 Redis 协议（RESP），也有私有协议；
- 存储引擎是改造过的 LevelDB：内存 memtable（SkipList）+ 后台 compaction 落到 SSTable，顺序写、LSM 结构（LSM 原理见 [LSM](/docs/CS/Algorithms/tree/LSM.md)）；
- 支持 KV、hash、zset、list、set 等 Redis 常见结构，以及 TTL 过期；
- 主从复制（异步）通过 binlog（commit log）同步，支持多主复制拓扑。

## SSDB vs Redis

| 维度 | Redis | SSDB |
|------|-------|------|
| 主存储 | 内存（RDB/AOF 仅持久化手段） | 磁盘 LSM（LevelDB） |
| 容量 | 受内存限制，成本高 | 可达内存的数十倍，成本低 |
| 延迟 | 亚毫秒级 | 内存命中快，落盘读毫秒级，P99 抖动受 compaction 影响 |
| 数据结构 | 丰富（stream/geo/hyperloglog 等） | 常用五种 + TTL，新特性基本不跟进 |
| 集群 | Redis Cluster、Sentinel | 主从 + 客户端分区，无官方 Cluster |
| 生态/活跃度 | 事实标准、生态活跃 | 社区小众、更新缓慢 |

## Applicability and Pitfalls

- 适合：海量中小 KV 的读写（标签、计数器历史、用户关系冷数据），预算敏感、容量优先于延迟；
- 不适合：不能容忍 compaction 写放大与读放大抖动的链路、依赖 Redis 新特性（Lua 完整版、stream、ACL）、需要成熟集群运维方案的场景；
- 定位上它更接近同类的 [Pika](/docs/CS/DB/Pika.md)（360 开源、同样是 Redis 协议 + RocksDB 的磁盘方案，社区更活跃）和 [Dragonfly](/docs/CS/DB/Dragonfly.md)（内存路线，目标是高性能替代），选型时三者应一起比较。

## Links

- [Redis](/docs/CS/DB/Redis/Redis.md)
- [Pika](/docs/CS/DB/Pika.md)
- [Dragonfly](/docs/CS/DB/Dragonfly.md)
- [LevelDB](/docs/CS/DB/LevelDB/LevelDB.md)
- [DataBases](/docs/CS/DB/DB.md)

## References

1. [SSDB GitHub](https://github.com/ideawu/ssdb)
2. [SSDB 官方文档](https://ssdb.io/docs/)
