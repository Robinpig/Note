## Introduction

MongoDB 是最流行的**文档型 NoSQL 数据库**（2009 起，SSPL/商业双协议），以 BSON（Binary JSON）文档为存储单位：一个文档相当于关系库里的一行，但字段可以嵌套对象与数组，同一 collection 内不要求统一 schema（schema-on-read）。它面向"数据天然是对象树、读写通常以整篇文档为单位、结构演进频繁"的场景，例如内容管理、用户画像、物联网设备数据、订单快照。

与关系库的概念映射：

| MongoDB | 关系数据库 |
|---------|-----------|
| database | database |
| collection | table |
| document（BSON） | row |
| field | column |
| index | index |
| `$lookup`（聚合管道） | join |
| embedded document / array | 一对多（预关联） |

## Data Model: Embedding vs Reference

建模决策是 MongoDB 的核心：

- **嵌入（embedded）**：一对多且从属对象总是随父文档一起读（订单 + 订单项），一次 IO 取全、原子更新，但文档上限 16MB、文档越大重写代价越高（BSON 原地更新要求编码后不超长）；
- **引用（reference，手动外键）**：多对多、对象被多处共享、从属数量无界时，存 `{ "$ref": ... }` 或直接存 `userId`，应用层二次查询（或聚合 `$lookup`）拼装。

经验法则：先按查询模式（读什么、写什么、一起访问的频率）建模，而不是先做 ER 图；文档保持小而集中，避免无限增长的数组。

## Query and Aggregation

```javascript
// 条件 + 投影
db.users.find({ age: { $gte: 18 }, city: "BJ" }, { name: 1, _id: 0 }).sort({ age: -1 }).limit(10)
// 更新：操作符修改，避免整文档重写
db.orders.updateOne({ _id: 1 }, { $set: { status: "PAID" }, $inc: { version: 1 } })
// upsert / 数组操作
db.carts.updateOne({ uid: 7 }, { $addToSet: { items: "sku_1" } }, { upsert: true })
```

复杂分析用**聚合管道**：`$match → $group → $lookup → $project → $sort/$limit`，等价于 SQL 的 WHERE/GROUP BY/JOIN/SELECT/ORDER BY 的流式组合。MongoDB 4.2+ 也支持部分 join、事务、视图。

索引方面支持 B+Tree 二级索引、复合索引（同样遵循最左前缀）、多键索引（数组字段自动多键）、文本索引、地理空间索引（2dsphere）；执行计划用 `explain('executionStats')` 看是否 IXSCAN、docsExamined 与键数。

## Storage Engine and Transaction

- **WiredTiger**（3.2 起默认）：文档级并发控制（乐观并发 + 文档级 latch）、MVCC 快照、按 checkpoint 落盘；写先记 WAL（journal，对应 redo log）保证崩溃恢复，原理可对照 [WAL](/docs/CS/DB/WAL.md) 与 [MySQL redo](/docs/CS/DB/MySQL/redolog.md)。
- 早期 MMAPv1 已移除，其整库锁/内存映射时代结束。
- 单文档原子性由引擎天然保证；4.0 支持副本集多文档事务、4.2 支持分片事务，但跨文档事务有性能与超时代价，官方仍建议优先用文档嵌入建模把一致性收敛到单文档内。

## High Availability and Horizontal Scaling

- **副本集（Replica Set）**：一主多从，oplog（幂等的操作日志，本质 capped collection）驱动异步复制，心跳 + Raft-like 选举自动故障转移，多数派写关注 `w: majority` 配合 `j: true` 保证已提交不丢；多数派原则与 [Redis Sentinel](/docs/CS/DB/Redis/sentinel.md) 的异步主从相比安全性更高。
- **分片（Sharding）**：数据按 shard key 分布到多个副本集，mongos 路由 + config server 存元数据；支持范围分片与哈希分片，shard key 一旦选定几乎无法改，必须在建库初期按基数、写均匀度、查询亲和性谨慎选择（热点写入是最大坑）。

## Applicable Boundaries

适合：schema 多变、聚合结构数据、高写入吞吐、需要水平扩展的场景；不适合：强事务跨实体（银行核心账务）、大量复杂 ad-hoc join、严格范式化报表分析（这类更适合关系库或 [ClickHouse](/docs/CS/DB/ClickHouse.md)）。

## Install

Docker：

```shell
docker run -d -p 27017:27017 --name mongodb mongodb/mongodb-community-server:latest
```

IDEA 可以安装 plugin Mongo DB Browser；命令行用 `mongosh`（新版 shell）连接，老版 `mongo` 已废弃。

## Links

- [DataBases](/docs/CS/DB/DB.md)
- [WAL](/docs/CS/DB/WAL.md)
- [Redis](/docs/CS/DB/Redis/Redis.md)
- [HBase](/docs/CS/DB/HBase.md)
- [Cassandra](/docs/CS/DB/Cassandra.md)

## References

1. [MongoDB 中文网](https://mongodb.net.cn/)
2. [MongoDB Manual（官方手册）](https://www.mongodb.com/docs/manual/)
