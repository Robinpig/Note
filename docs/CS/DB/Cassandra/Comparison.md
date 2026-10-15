## Introduction

Cassandra 不是「万能数据库」，选它意味着接受其设计权衡。本页把它与相近系统横向对比，并给出选型判断框架，帮助决定「何时用、何时换」。

> 基线：Cassandra 5.0。对照项含 HBase、MongoDB、DynamoDB、ScyllaDB、TiDB/CockroachDB。

## Cassandra vs HBase

| 维度 | Cassandra | HBase |
| --- | --- | --- |
| 架构 | 无主 P2P | HMaster + RegionServer（有主） |
| 外部依赖 | 自带 | 强依赖 HDFS + ZooKeeper |
| 一致性 | 可调（最终 ~ quorum 强） | 行级强一致 |
| 多 DC | 内建、一等公民 | 外部复制、较繁琐 |
| 读写模型 | LSM、LWW | LSM、LWW |
| 运维复杂度 | 中（节点对等） | 高（组件多） |
| 适用 | 写多、多地域、AP | 强一致、Hadoop 生态内 |

两者都是 LSM + LWW 的宽列存储，但 HBase 把「强一致 + 生态」做到极致，Cassandra 把「去中心 + 多 DC + 易扩展」做到极致。

## Cassandra vs MongoDB

- MongoDB 是**文档模型**（嵌套 JSON、灵活 schema、聚合管道），Cassandra 是**宽列 + 按查询建表**。
- MongoDB 4.0+ 有**多文档 ACID 事务**；Cassandra 直到 6.0(Accord) 前都只有单行 LWT，跨文档/跨分区事务缺失。
- 选 MongoDB：需要灵活文档、复杂查询、事务；选 Cassandra：需要**线性写扩展、多 DC、极致可用**。

## Cassandra vs DynamoDB

- DynamoDB 是 AWS 托管、按容量/按请求计费的「Cassandra 精神续作」：同样的哈希主键 + 可调一致性 + 多 AZ。
- 区别在于：DynamoDB 免运维但**锁云、成本模型不同、单 item 大小/吞吐受限**；Cassandra 自建可控、无单 item 上限压力、可跨云/混合。许多团队从 DynamoDB 迁 Cassandra（或反之）往往是因为成本/锁定/规模拐点。

## Cassandra vs ScyllaDB

- **ScyllaDB** 是 Cassandra 的 **C++ / Seastar 重写**，API 兼容，但用 shard-per-core、无 GC 的架构拿到显著更低的尾延迟与更高吞吐。
- 代价：生态/工具差异、商业版特性。若现有 Cassandra 受 GC 尾延迟或堆压力困扰，ScyllaDB 是直接对标的解法。

## Cassandra vs Distributed SQL (TiDB / CockroachDB)

- TiDB / CockroachDB 提供**分布式 SQL + 跨 region ACID**（CockroachDB 基于 TrueTime 类机制、TiDB 基于 Percolator），牺牲部分写扩展换「强一致 + 标准 SQL + join」。
- 选分布式 SQL：需要事务与 SQL 表达力优先；选 Cassandra：写吞吐、多 DC 可用性与简单 KV/宽列访问优先。

## Modernization Note (5.0+)

5.0 的一系列改动**削弱了多条旧经验法则**，评估 Cassandra 时应以新版本为准：

- **「避免二级索引」**——SAI（CEP-7）在空间/性能/能力上远优于旧本地索引与 SASI，适度使用可接受，但**仍不消除跨 partition 广播**，分区建模仍是根本（见 [Indexing](/docs/CS/DB/Cassandra/Indexing.md)）。
- **「LWT 慢就别用」**——Paxos 改进（CEP-14）降低了 prepare 风暴，但仍单 partition、四轮往返；高频争用场景仍应换设计（见 [Consistency](/docs/CS/DB/Cassandra/Consistency.md)）。
- **「compaction 策略选错难回头」**——UCS（CEP-26）把 STCS/LCS/TWCS 统一到一个连续谱，且可在线调参，降低了选错成本（见 [Compaction](/docs/CS/DB/Cassandra/Compaction.md)）。
- `storage_compatibility_mode`（CASSANDRA_4 / UPGRADING / NONE）在升级期**门控新格式**（Trie memtable/SSTable、SAI 等）的写入，确保滚动升级安全；旧格式仍可互读。

## Selection Framework

**倾向选 Cassandra 当**：写多读少或读写均衡、需要多数据中心容灾、追求线性扩展与「节点对等易运维」、能接受按查询建表、不需要跨分区事务/复杂 join。

**不应选 Cassandra 当**：需要复杂 ad-hoc 查询/聚合、需要跨行 ACID 事务（6.0 Accord 前）、团队不愿做「反范式建模」、数据量小到单机就能扛（此时引入分布式只增复杂度）。

## Links

- [Cassandra](/docs/CS/DB/Cassandra.md)
- [Architecture](/docs/CS/DB/Cassandra/Architecture.md)
- [Consistency](/docs/CS/DB/Cassandra/Consistency.md)
- [HBase](/docs/CS/DB/HBase.md)

## References

- [Apache Cassandra (官方站点)](https://cassandra.apache.org/)
- [Cassandra vs Others (官方 Use Cases)](https://cassandra.apache.org/_/use-cases/)
