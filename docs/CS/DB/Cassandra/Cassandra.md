## Introduction

[Apache Cassandra](https://cassandra.apache.org/) 是去中心化的**宽列（wide-column）分布式存储**，源自 Amazon Dynamo（最终一致、P2P）与 Google BigTable（列族数据模型）。为高写入、多数据中心、无单点故障的场景设计。

## Version Notes

| 版本 | 发布 | 关键特性 |
| --- | --- | --- |
| 4.0 | 2021-07 | 全量测试重写、zero-copy streaming、Audit Logging、backpressure |
| 4.1 | 2022-12 | Guardrails Framework、JDK 17 |
| 5.0 | 2024-09 | SAI(CEP-7)、Vector Search(CEP-30)、Trie Memtable(CEP-19)/SSTable(CEP-25)、Unified Compaction(CEP-26)、Dynamic Data Masking(CEP-20)、**Transactional Cluster Metadata(CEP-21)**、JDK 17 |
| 5.0.9 | 2026-08 | 5.0 最新补丁（最新 GA） |
| 6.0 | pre-GA | Accord 跨分区事务 (CEP-15)、Auto Repair (CEP-37)、Constraints Framework (CEP-42)、JDK 21 + Generational ZGC |

> 本文基线 **Cassandra 5.0**。4.0.x / 4.1.x 仍受支持；6.0 尚未 GA。下文机制章节已拆为专题，按主题阅读。

## Architecture and Positioning

Cassandra 的骨架是**无主 P2P**：每个节点角色完全相同，都能接收读写，故障容忍来自冗余而非选举。数据按 partition key 经 Murmur3 哈希落入 token 环，借助 vnode（默认 256 区间）实现平滑负载均衡与线性扩展；多 DC 容灾是其一等公民能力。与有主的 [HBase](/docs/CS/DB/HBase/HBase.md) 相比，Cassandra 把「去中心 + 多 DC + 易运维」做到极致，代价是放弃跨分区事务与复杂查询。详见 [Architecture](/docs/CS/DB/Cassandra/Architecture.md) 与 [Comparison](/docs/CS/DB/Cassandra/Comparison.md)。

## Core Mechanisms

- **数据模型**：宽列多维 map，按查询建表，partition key 决定分布、clustering key 决定分区内排序——[Data Model](/docs/CS/DB/Cassandra/DataModel.md)。
- **可调一致性**：每条读写可独立指定 CL，用 NRW 模型在一致性与延迟间权衡；配合 read-repair、hinted handoff、LWT(Paxos) 收敛——[Consistency](/docs/CS/DB/Cassandra/Consistency.md)。
- **复制与拓扑**：RF + NetworkTopologyStrategy + snitch 把副本散布到跨机架/DC，多 DC 异步冗余——[Replication](/docs/CS/DB/Cassandra/Replication.md)。
- **存储引擎**：LSM 谱系，CommitLog(WAL) → Memtable → SSTable，读路径 LWW 合并 + Bloom 过滤；5.0 引入 Trie Memtable/SSTable——[Storage Engine](/docs/CS/DB/Cassandra/StorageEngine.md)。
- **Compaction**：STCS/LCS/TWCS 各有所长，5.0 的 UCS 统一调参模型——[Compaction](/docs/CS/DB/Cassandra/Compaction.md)。
- **分布式机制**：gossip 发现与 Phi-accrual 故障检测、partitioner/token ring/vnode、基于 Merkle 树的 repair、4.0+ zero-copy streaming、5.0 TCM（CEP-21）——[Distributed](/docs/CS/DB/Cassandra/Distributed.md)。

## Interface and Indexing

- **CQL**：类 SQL 但无 join、无跨分区事务，必须按查询建表——[CQL](/docs/CS/DB/Cassandra/CQL.md)。
- **索引**：经典本地二级索引读放大随节点数增长；5.0 的 SAI 是官方推荐（标量 + 向量），SASI 已被取代——[Indexing](/docs/CS/DB/Cassandra/Indexing.md)。

## Operations and Security

- **运维监控**：部署、关键配置、JMX/Prometheus 指标、调优、扩缩容、备份恢复与常见坑——[Operations](/docs/CS/DB/Cassandra/Operations.md)。
- **安全**：认证/授权(RBAC)、TLS、TDE、审计、5.0 动态脱敏与 CIDR 授权——[Security](/docs/CS/DB/Cassandra/Security.md)。

## Links

- [Architecture](/docs/CS/DB/Cassandra/Architecture.md)
- [Data Model](/docs/CS/DB/Cassandra/DataModel.md)
- [Consistency](/docs/CS/DB/Cassandra/Consistency.md)
- [Storage Engine](/docs/CS/DB/Cassandra/StorageEngine.md)
- [Operations](/docs/CS/DB/Cassandra/Operations.md)
- [HBase](/docs/CS/DB/HBase/HBase.md)

## References

- [Cassandra - A Decentralized Structured Storage System](https://citeseerx.ist.psu.edu/viewdoc/download?doi=10.1.1.161.6751&rep=rep1&type=pdf)
- [Apache Cassandra Documentation](https://cassandra.apache.org/doc/latest/)
