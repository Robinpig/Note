# Amazon Aurora

## Introduction

Amazon Aurora 是 AWS 在 2017 年（SIGMOD）公开的**云原生关系数据库**，核心思想是**把数据库的计算层与存储层彻底分离**，并围绕"云的对象存储 + 多副本 quorum"重新设计 MySQL / PostgreSQL 的存储引擎，从而在云上获得数量级更高的吞吐与可用性，同时保持 SQL 兼容。它与 [Spanner](/docs/CS/Distributed/Spanner.md) / [F1](/docs/CS/Distributed/F1.md) 同属"云规模 SQL"，但走的是"改造传统引擎的存储"而非"重新设计全局强一致"的路线。

## Architecture: Compute-Storage Separation

传统主从库的写放大严重：主库把 redo log、binlog、double-write、页刷盘等层层下发，网络 IO 与写放大成为瓶颈。Aurora 的做法：

- **计算节点（DB instance）只把 redo log 发给存储层**——"log is the database"：存储层收到 redo 后，在后台异步把日志 apply 成数据页，计算节点不再刷脏页、不做 double-write。
- **存储层是分布式、自管理的**：数据按 10GB 为段（segment）切分，每个 10GB segment 再 6 副本跨 3 个可用区（AZ），每段一组复制。

## Quorum

Aurora 用 **(6 副本，写需 4，读需 3)** 的 quorum：

- 写：4 / 6 成功即可返回（容忍 2 个副本慢 / 失败），且 4 份中至少覆盖 3 个 AZ 中的 2 个，保证持久性。
- 读：3 / 6 即可（容忍 3 个副本不可用）。
- 段故障 / 重建在后台以 10GB 粒度快速完成，远超传统 TB 级卷恢复。

## Relation to Other Topics

- 与 Spanner / F1：都是"云 / 全球规模的 SQL"，但 Aurora 仍用传统 SQL 引擎 + 改造存储，Spanner / F1 用 TrueTime 做全球强一致；Aurora 的强项是单 region 内高可用与兼容生态。
- 与 [Distributed Storage](/docs/CS/Distributed/Distributed_Storage.md)：是"云原生把存储做进分布式层"的代表，快照存于对象存储。
- 与 [Replica](/docs/CS/Distributed/Replica.md)：6 副本跨 AZ 的 quorum 复制是副本策略的工业范例。

## Links

- [Spanner](/docs/CS/Distributed/Spanner.md)
- [F1](/docs/CS/Distributed/F1.md)
- [Distributed Storage](/docs/CS/Distributed/Distributed_Storage.md)
- [Replica](/docs/CS/Distributed/Replica.md)

## References

- Amazon Aurora: Design Considerations for High Throughput Cloud-Native Relational Databases (Verbitski et al., SIGMOD 2017)
