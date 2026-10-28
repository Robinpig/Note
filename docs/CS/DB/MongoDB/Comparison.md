## Introduction

MongoDB 的定位是**通用文档数据库**：比关系库灵活、比宽列库查询能力强、比搜索引擎更适合做系统 of record。它不是"所有场景都更好"，而是在"数据结构多变、读写以文档为单位、需要水平扩展"的区间里性价比最高。下面按对手逐项对照，最后给选型表。

## vs Relational (MySQL / PostgreSQL)

| 维度 | MongoDB | 关系库 |
| :--- | :--- | :--- |
| 模式 | schema-on-read，可选 `$jsonSchema` 校验 | schema-on-write，DDL 演进 |
| 关系 | 嵌入/引用，`$lookup` 有限 join | 原生 join、外键、范式化 |
| 事务 | 单文档原子 + 4.0+ 多文档事务 | 完整 ACID、隔离级别成熟 |
| 扩展 | 原生分片 | 主要纵向；分库分表/Citus 等外挂 |
| 分析 | 聚合管道，复杂报表偏弱 | 窗口函数、CTE、优化器成熟 |

**选关系库**：强事务的账务/库存核心、复杂多表报表、数据高度规范化、团队 SQL 能力强。
**选 MongoDB**：内容/商品/用户画像这类结构频繁变化的实体、读写以整篇文档为单位、需要按业务键水平扩展。

## vs PostgreSQL JSONB

PostgreSQL 的 `JSONB` 让关系库也能存半结构化数据，两者的边界因此变得模糊：

- PG 的优势：JSONB 与关系表可以在同一事务里 join；GIN 索引支持 containment 查询；SQL 生态与扩展丰富；单机内强一致。
- MongoDB 的优势：文档是原生模型（不是"塞进一列"），二级索引/聚合/分片/Change Streams 围绕文档设计；更新可以只改文档内的一个字段，而 JSONB 更新通常重写整个值。
- 规模：PG 主要靠垂直扩展，分片需 Citus 等方案；MongoDB 的分片是内建能力，但 shard key 选型成本高。

经验判断：**数据关系复杂、需要大量 join → PG**；**文档边界清晰、按实体水平扩展 → MongoDB**。

## vs Cassandra / HBase

| 维度 | MongoDB | Cassandra / HBase |
| :--- | :--- | :--- |
| 模型 | 文档（嵌套 + 数组） | 宽列（按查询建表） |
| 一致性 | 主从复制 + 多数派 | 可调一致性 / 强一致单行 |
| 写入扩展 | 分片，每 shard 一个主 | 无主/Region 分裂，写扩展更强 |
| 查询 | 二级索引、聚合、join | 受限于主键设计，复杂查询弱 |
| 事务 | 多文档事务 | 单行/单分区（Cassandra 6.0 Accord 仍 pre-GA） |

**选 Cassandra/HBase**：写入量极大、多地域、查询模式固定、可接受最终一致。
**选 MongoDB**：需要灵活查询、二级索引、事务与聚合，写入量在分片可承载范围内。

## vs Elasticsearch

Elasticsearch 的核心是倒排索引与近实时搜索；MongoDB 的核心是事务型文档存储。常见架构是"MongoDB 做主库，ES 做搜索副本"，用 Change Streams 同步。MongoDB Atlas 提供 Atlas Search（Lucene 集成）与 Vector Search，可以在库内做全文/向量检索，减少一套同步链路，但搜索能力深度仍不如专用 ES 集群。

## vs Redis

Redis 是内存数据结构服务，强在缓存、计数、排行榜、分布式锁；持久化与查询能力弱于 MongoDB。RedisJSON + RediSearch 让它能覆盖一部分文档场景，但数据量受内存成本约束。典型组合：Redis 做热数据缓存，MongoDB 做持久化主库。

## vs ClickHouse / OLAP

ClickHouse 列式存储、压缩率高、聚合极快，适合日志与报表；弱点是点更新、事务与高并发小写入。MongoDB 的时间序列集合能承接一部分指标场景，但大规模分析仍应下沉到 ClickHouse / Doris 等 OLAP 引擎。

## vs Time Series Databases

InfluxDB、TimescaleDB、TDengine 在压缩、降采样、保留策略上更专业。MongoDB 时间序列集合的优势是**与业务数据同库、同查询语言、同事务/权限体系**；如果系统已经有大量 MongoDB 业务数据，且指标规模不极端，内置时间序列集合能省掉一套技术栈。

## Decision Table

| 需求 | 首选 |
| :--- | :--- |
| 强事务、复杂 join、报表 | PostgreSQL / MySQL |
| 结构多变的实体、快速迭代 | MongoDB |
| 海量写入、多 DC、固定查询 | Cassandra / HBase |
| 全文检索、日志搜索 | Elasticsearch / OpenSearch |
| 缓存、会话、排行榜 | Redis / Valkey |
| 大规模 OLAP、日志分析 | ClickHouse / Doris |
| 指标/传感器、保留期明确 | 专用 TSDB 或 MongoDB Time Series |
| 向量检索 | 专用向量库或 MongoDB Atlas Vector Search |

## Migration Notes

从关系库迁移到 MongoDB 不是"表改名 collection"：需要先梳理**访问模式**，把 join 关系转成嵌入/引用，重新设计索引与 shard key。MongoDB 提供 Relational Migrator 辅助 schema 映射，但业务代码里的查询重写无法自动化。反向迁移（MongoDB → 关系库）同样要处理嵌套文档的展开与 schema 收敛。

## Links

- [MongoDB](/docs/CS/DB/MongoDB/MongoDB.md)
- [Data Model](/docs/CS/DB/MongoDB/DataModel.md)
- [Sharding](/docs/CS/DB/MongoDB/Sharding.md)
- [Cassandra](/docs/CS/DB/Cassandra/Cassandra.md)
- [HBase](/docs/CS/DB/HBase/HBase.md)
- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)

## References

- [MongoDB vs Relational Databases](https://www.mongodb.com/resources/compare/relational-vs-non-relational-databases)
- [PostgreSQL JSON Types](https://www.postgresql.org/docs/current/datatype-json.html)
- [Atlas Search](https://www.mongodb.com/docs/atlas/atlas-search/)
- [Relational Migrator](https://www.mongodb.com/docs/relational-migrator/)
