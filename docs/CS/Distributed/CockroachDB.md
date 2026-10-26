# CockroachDB

## Introduction

CockroachDB 是一个**云原生分布式 SQL 数据库**，对外兼容 **PostgreSQL 线协议与语法**，对内把数据自动分片、用 Raft 复制、用 **HLC（混合逻辑时钟，见 [Time（时钟与同步）](/docs/CS/Distributed/Time.md)）** 做 MVCC 时间戳。其设计目标是"像 PostgreSQL 一样易用、像 KV 存储一样可水平扩展、像云一样可地理分布"，2014 年起步，SIGMOD 2020 论文系统公开架构。它是 [Distributed Storage](/docs/CS/Distributed/Distributed_Storage.md) 枢纽点名的"强一致在线业务"代表方案之一。

## Architecture

自顶向下分三层：

- **SQL 层（无状态）**：解析 SQL、生成分布式查询计划、把表 / 索引操作翻译成 KV 读写。兼容 PG 协议，可直接用 psql / JDBC 驱动。
- **分布式 KV / 事务层**：把 SQL 的 KV 操作路由到对应 range；每个 range 是一个有序 KV 区间，用 **Raft** 复制到多个节点，leader 处理读写。
- **存储层（Pebble / RocksDB）**：节点本地 LSM 引擎持久化 KV。

## Key Mechanisms

- **Range 自动分片**：表按主键范围切成 range（默认 64MB ~ 512MB），热点 range 自动分裂、冷 range 合并，集群自动 rebalance。
- **Raft 复制**：每个 range 独立 Raft group，默认 3 或 5 副本跨故障域；副本放置遵守 locality 约束（如按机架 / 可用区）。
- **HLC 时间戳 + MVCC**：所有写用 HLC 打时间戳，读用某个时间戳的快照；HLC 保证因果有序且贴近物理时间，无需 TrueTime 硬件（见 [Time（时钟与同步）](/docs/CS/Distributed/Time.md)）。
- **分布式事务**：跨 range 事务用两阶段提交（受 Google Percolator 启发），锁信息也存于 KV；lease 机制减少事务协调开销。
- **Geo-distribution**：locality 配置让数据靠近用户，读本地副本、写走共识，支持"跟随工作负载"（follow-the-workload）的数据放置。

## Relation to Other Topics

- 与 [TiDB / TiKV](/docs/CS/DB/TiDB/TiDB.md)：两者都是"分布式 SQL + 存储计算分离 + Raft + 兼容 MySQL / PG"，但 TiDB 用 Percolator 式 MVCC 与 PD 调度、TiKV 基于 Raft；CockroachDB 自包含、用 HLC 而非 PD。
- 与 [F1](/docs/CS/Distributed/F1.md)：F1 把 SQL 架在 Spanner 之上（解耦），CockroachDB 自包含存储 + SQL；路线相反。
- 与 Distributed Storage：是"强一致在线业务"的代表方案之一（与 TiKV 并列）。

## Links

- [Distributed Storage](/docs/CS/Distributed/Distributed_Storage.md)
- [TiDB / TiKV](/docs/CS/DB/TiDB/TiDB.md)
- [Time（时钟与同步）](/docs/CS/Distributed/Time.md)
- [F1](/docs/CS/Distributed/F1.md)
- [Replica](/docs/CS/Distributed/Replica.md)

## References

- CockroachDB: The Resilient Geo-Distributed SQL Database (Taft et al., SIGMOD 2020)
