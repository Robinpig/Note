## Introduction

[Valkey](https://github.com/valkey-io/valkey) 是 Redis 的分支：基于 Redis 7.2.4 继续开发，采用 **BSD 3-clause** 开源许可（2024 年 Redis 改闭源/SSPL 许可后，由社区与 Linux 基金会发起）。定位仍是高性能内存数据结构服务器，承载 KV/缓存/消息等负载。

## Relationship with Redis

- 代码同源 7.2.4，协议/命令/数据结构高度兼容，客户端可平滑迁移。
- 治理转向 **Linux Foundation** 中立社区，多厂商（AWS/Akamai/Google/Oracle 等）共建。
- 许可差异是分叉主因：Valkey 保持真正开源，Redis 7.4+ 转向 RSALv2/SSPLv2。

## Architecture Evolution

- **多线程 I/O**：network read/write 与命令执行解耦（类似 Redis 6 的 I/O threads 并持续增强），单线程命令执行保证无锁语义。
- **Cluster**：无中心分片（16384 slot），Gossip 维护拓扑，支持 reshard/replica。
- **数据结构**：string/hash/list/set/zset/stream 等，RDB/AOF 持久化，pub-sub、Lua 脚本。

## Links

- [Redis](/docs/CS/DB/Redis/Redis.md)
- [DataBases](/docs/CS/DB/DB.md)

## References

- [Valkey GitHub](https://github.com/valkey-io/valkey)
- [Valkey: A New In-Memory Data Store](https://valkey.io/)
