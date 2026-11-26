## Introduction

Cassandra 不是“万能数据库”，选它意味着接受其设计权衡。本页把它与相近系统横向对比，并给出选型判断框架，帮助决定“何时用、何时换”。

> 基线：Cassandra 5.0.9。对照项含 HBase、MongoDB、DynamoDB、ScyllaDB、TiDB/CockroachDB。

## Cassandra vs HBase

| 维度 | Cassandra | HBase |
| --- | --- | --- |
| 架构 | 无主 P2P | HMaster + RegionServer（有主） |
| 外部依赖 | 自带 | 强依赖 HDFS + ZooKeeper |
| 一致性 | 可调；quorum + read repair，LWT 单分区线性一致 | 行级强一致 |
| 多 DC | 内建、一等公民 | 外部复制、较繁琐 |
| 读写模型 | LSM、cell timestamp / LWW | LSM、LWW |
| 运维复杂度 | 中（节点对等） | 高（组件多） |
| 适用 | 写多、多地域、AP | 强一致、Hadoop 生态内 |

两者都是 LSM + LWW 的宽列存储，但 HBase 把“强一致 + 生态”做到极致，Cassandra 把“去中心 + 多 DC + 易扩展”做到极致。这里的“一致”都不能脱离 CL、拓扑和故障窗口理解。

## Cassandra vs MongoDB

- MongoDB 是**文档模型**（嵌套 JSON、灵活 schema、聚合管道），Cassandra 是**宽列 + 按查询建表**。
- MongoDB 4.0+ 有**多文档 ACID 事务**；Cassandra 5.0.9 只有单 partition LWT，logged batch 提供 batchlog 恢复，不是跨文档/跨分区 ACID。
- 选 MongoDB：需要灵活文档、复杂查询、事务；选 Cassandra：需要线性写扩展、多 DC、极致可用。

## Cassandra vs DynamoDB

- DynamoDB 是 AWS 托管、按容量/按请求计费的“Cassandra 精神续作”：同样以哈希主键定位，提供可调一致性与多 AZ。
- 区别在于 DynamoDB 免运维但锁定云、成本模型不同，并受 service/item/partition 配额约束；Cassandra 自建可控、可跨云/混合，但 partition、mutation 与 compaction 仍有自身保护阈值，并非“没有大小上限”。
- 许多团队在两者间迁移，拐点通常是成本、云锁定、吞吐模型、运维能力或查询建模，而不是单纯性能数字。

## Cassandra vs ScyllaDB

- **ScyllaDB** 是 Cassandra 的 **C++ / Seastar 重写**，保持 CQL/协议兼容路线，用 shard-per-core、无 GC 的架构争取更低尾延迟与更高吞吐。
- 代价是生态/工具差异、商业版特性，以及不同版本对 SAI、Vector、Trie/BTI 等新能力的兼容进度。
- 若现有 Cassandra 受 GC 尾延迟或堆压力困扰，ScyllaDB 是直接对标的解法，但迁移前必须按目标版本逐项验证 schema、驱动、工具链和运维流程。

## Cassandra vs Distributed SQL

- TiDB / CockroachDB 提供**分布式 SQL + 跨 region ACID**（CockroachDB 使用 TrueTime/HLC 类机制，TiDB 基于 Percolator），牺牲部分写扩展换“强一致 + 标准 SQL + join”。
- 选分布式 SQL：需要事务与 SQL 表达力优先；选 Cassandra：写吞吐、多 DC 可用性与简单 KV/宽列访问优先。

## Modernization Note

5.0 削弱了多条旧经验法则，但新能力仍有边界：

- **SAI 不是万能索引**——它支持标量等值/范围、集合包含、索引列 `AND`/`OR`/`IN` 与实验性 ANN，不支持 `LIKE`，也不消除无 partition 约束时的 fan-out，见 [Indexing](/docs/CS/DB/Cassandra/Indexing.md)。
- **LWT 延迟降低但语义未变**——Paxos v2 将写路径从默认 v1 的约四轮往返降至约两轮；仍是单 partition CAS，不是跨分区事务，见 [Consistency](/docs/CS/DB/Cassandra/Consistency.md)。
- **UCS 统一 compaction 参数空间**——CEP-26 让 STCS/LCS/TWCS 的选择更连续，但标准 profile 默认仍是 STCS；采用 `cassandra_latest.yaml` 或表级配置才会默认使用 UCS，见 [Compaction](/docs/CS/DB/Cassandra/Compaction.md)。
- **Trie/BTI 不是版本号自动解锁**——Trie memtable 由 profile/表选项选择，BTI 由全局 `sstable.selected_format` 选择；滚动升级还要核对 `storage_compatibility_mode`，该模式不统一门控 SAI。
- **Vector Search 仍 experimental**——5.0.9 ANN 限制 CL、分页、聚合、过滤与数据目录布局，不能按成熟向量数据库评估。

## Selection Framework

**倾向选 Cassandra 当**：写多读少或读写均衡、需要多数据中心容灾、追求线性扩展与节点对等运维、能接受按查询建表、不需要跨分区事务/复杂 join。

**不应选 Cassandra 当**：需要复杂 ad-hoc 查询/聚合、需要跨行 ACID 事务、团队不愿做反范式建模、数据量小到单机就能扛，或需要成熟的分词全文/向量检索。

## Links

- [Cassandra](/docs/CS/DB/Cassandra/Cassandra.md)
- [HBase](/docs/CS/DB/HBase/HBase.md)

## References

- [Apache Cassandra](https://cassandra.apache.org/)
- [Cassandra Case Studies](https://cassandra.apache.org/_/case-studies.html)
- [Cassandra 5.0.9 Source](https://github.com/apache/cassandra/tree/cassandra-5.0.9)
