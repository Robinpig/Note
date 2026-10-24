## Introduction

MongoDB 是最流行的**文档型 NoSQL 数据库**（2009 起，SSPL/商业双协议），以 BSON（Binary JSON）文档为存储单位：一个文档相当于关系库里的一行，但字段可以嵌套对象与数组，同一 collection 内不要求统一 schema（schema-on-read）。它面向"数据天然是对象树、读写通常以整篇文档为单位、结构演进频繁"的场景，例如内容管理、用户画像、物联网设备数据、订单快照。

与关系库的概念映射：

| MongoDB | 关系数据库 |
| :--- | :--- |
| database | database |
| collection | table |
| document（BSON） | row |
| field | column |
| index | index |
| `$lookup`（聚合管道） | join |
| embedded document / array | 一对多（预关联） |

本文是枢纽页：定位、版本与导航。具体机制拆到 `MongoDB/` 下的专题笔记，按下面的顺序读即可。

## Version Notes

| 版本 | 发布 | 关键特性 |
| :--- | :--- | :--- |
| 5.0 | 2021-07 | 时间序列集合、在线 resharding、`$setWindowFields`、版本化 API |
| 6.0 | 2022-07 | Change Streams 前后镜像、时间序列增强、Queryable Encryption 预览 |
| 7.0 | 2023-08 | Queryable Encryption 等值查询 GA、SBE 成为默认执行引擎、OIDC、AutoMerger |
| 8.0 | 2024-10 | 读写性能提升、`bulkWrite`、config shard、`moveCollection` / `unshardCollection`、QE 范围查询、per-CPU TCMalloc、`w:majority` 语义变化 |
| 8.2 | 2025-09 | 改为 Major / Minor 双轨发布；Minor 版也开始面向本地部署的特定场景 |
| 9.0 | 2026-09 | QE 前缀/后缀/子串查询 GA、单操作内存上限、事务并发上限、`$queryStats` 默认采样、时间序列单命名空间存储 |

> 本文基线 **MongoDB 8.0**（Major Release，五年生命周期）。8.2 / 9.0 的差异在各专题里单独标注。

## Data Model

建模决策是 MongoDB 的核心，也是"前期很爽、后期还债"的分水岭：

- **嵌入（embedded）**：一对多且从属对象总是随父文档一起读（订单 + 订单项），一次 IO 取全、单文档原子更新；代价是 16MB 文档上限与文档膨胀。
- **引用（reference）**：多对多、对象被多处共享、从属数量无界时，存 `userId` 或 `{ "$ref": ... }`，应用层二次查询或聚合 `$lookup` 拼装。

经验法则：先按**查询模式**（读什么、写什么、是否总一起访问）建模，而不是先做 ER 图；数组要有明确上界，否则用分桶或独立集合。BSON 类型、ObjectId、schema 校验与九种设计模式见 [Data Model](/docs/CS/DB/MongoDB/DataModel.md)。

## Query, Aggregation, and Index

查询语言是 MQL：`find` 负责过滤与分页，聚合管道负责变换与统计。真正决定性能的是**索引是否能同时支撑过滤与排序**——复合索引按 E-S-R（Equality、Sort、Range）排列，覆盖查询可以完全避免回表。

- 查询语义、游标、`explain` 与查询计划： [Query](/docs/CS/DB/MongoDB/Query.md)
- 聚合管道、`$lookup`、窗口函数与 Change Streams 的关系： [Aggregation](/docs/CS/DB/MongoDB/Aggregation.md)
- 索引类型、复合索引、TTL/文本/多键与索引构建： [Index](/docs/CS/DB/MongoDB/Index.md)

## Storage and Transactions

WiredTiger 是唯一的生产存储引擎（MMAPv1 已在 4.2 移除）。它的关键设计是**更新不原地修改**：每次写生成新版本挂到更新链，journal（默认 100ms）保证崩溃恢复，checkpoint（60 秒）提供一致落盘点，后台淘汰把合并后的页重新压缩写回。读靠快照与 hazard pointer，不阻塞写。

单文档更新天然原子；多文档事务 4.0（副本集）/ 4.2（分片）补齐，默认快照隔离，写冲突以 `TransientTransactionError` 的形式要求重试。机制细节：

- [Storage Engine](/docs/CS/DB/MongoDB/StorageEngine.md)
- [Transaction](/docs/CS/DB/MongoDB/Transaction.md)

## Replication and Sharding

**副本集**是一主多从 + 多数派选举：oplog 记录幂等写操作，`w: "majority"` 决定写确认，`readConcern: "majority"` 决定读可见性，`priority` 与 PV1 协议决定谁当选。8.0 把 majority 确认从"多数派应用完成"改为"多数派写入 oplog"，这是从节点读一致性的一个重要分界。

**分片**把集合按 shard key 切成 128MB 的 chunk，`mongos` 定向或广播路由，config server 存元数据，balancer 在后台迁移。shard key 的基数、频率、单调性决定是否热点；5.0 起可在线 reshard，8.0 起可搬移未分片集合或退回未分片状态。

- [Replication](/docs/CS/DB/MongoDB/Replication.md)
- [Sharding](/docs/CS/DB/MongoDB/Sharding.md)
- [Architecture](/docs/CS/DB/MongoDB/Architecture.md)

## Specialized Workloads

时间序列集合（5.0）把同源、相邻时间的数据压进列式桶，适合指标与传感器数据，支持 TTL 自动过期；它与业务文档同库同语言，省掉一套时序栈。见 [Time Series](/docs/CS/DB/MongoDB/TimeSeries.md)。

实时变更订阅用 Change Streams：建在聚合框架上、读 oplog、带 resume token，6.0 起支持前后镜像。它的续读能力受 oplog 窗口约束，机制见 [Replication](/docs/CS/DB/MongoDB/Replication.md)。

## Operations and Security

生产上真正需要长期关注的是**工作集与 WT 缓存、oplog 窗口、索引与 shard key** 三件事；备份、监控、升级与容量规划见 [Operations](/docs/CS/DB/MongoDB/Operations.md)。安全侧按认证、RBAC、TLS、静态加密、客户端字段级加密、审计六层收紧，见 [Security](/docs/CS/DB/MongoDB/Security.md)。

## Applicable Boundaries

适合：schema 多变、聚合结构数据、高写入吞吐、需要水平扩展的场景；不适合：强事务跨实体（银行核心账务）、大量复杂 ad-hoc join、严格范式化报表分析（这类更适合关系库或 [ClickHouse](/docs/CS/DB/ClickHouse.md)）。与 PostgreSQL JSONB、Cassandra、HBase、Elasticsearch、Redis 的逐项对照见 [Comparison](/docs/CS/DB/MongoDB/Comparison.md)。

## Install

Docker：

```shell
docker run -d -p 27017:27017 --name mongodb mongodb/mongodb-community-server:latest
```

IDEA 可以安装 plugin Mongo DB Browser；命令行用 `mongosh`（新版 shell）连接，老版 `mongo` 已废弃。

## Links

- [Architecture](/docs/CS/DB/MongoDB/Architecture.md)
- [Data Model](/docs/CS/DB/MongoDB/DataModel.md)
- [Query](/docs/CS/DB/MongoDB/Query.md)
- [Index](/docs/CS/DB/MongoDB/Index.md)
- [Replication](/docs/CS/DB/MongoDB/Replication.md)
- [Sharding](/docs/CS/DB/MongoDB/Sharding.md)

## References

- [MongoDB Manual](https://www.mongodb.com/docs/manual/)
- [MongoDB Versioning](https://www.mongodb.com/docs/manual/reference/versioning/)
- [Release Notes for MongoDB 8.0](https://www.mongodb.com/docs/manual/release-notes/8.0/)
- [Release Notes for MongoDB 9.0](https://www.mongodb.com/docs/manual/release-notes/9.0/)
- [BSON Specification](https://bsonspec.org/)
