## Introduction

**CQL（Cassandra Query Language）** 是用户与 Cassandra 交互的接口，表面像 SQL，但语义受宽列模型与「无 join、无跨 partition 事务」约束。理解 CQL 的能做什么、不能做什么，是正确建模与避免反模式的前提（建模见 [Data Model](/docs/CS/DB/Cassandra/DataModel.md)）。

> 基线：Cassandra 5.0。5.0 新增数学函数（abs/exp/log/log10/round）、集合/UDT 上的 TTL 与 writetime、动态数据脱敏等。

## DDL

```sql
CREATE KEYSPACE myks WITH REPLICATION =
  {'class':'NetworkTopologyStrategy','dc1':3,'dc2':3};

CREATE TABLE events (
  device_id uuid,
  bucket    date,
  ts        timestamp,
  payload   text,
  PRIMARY KEY ((device_id, bucket), ts)
) WITH CLUSTERING ORDER BY (ts DESC)
  AND default_time_to_live = 864000;   -- 10 天 TTL
```

- `PRIMARY KEY ((pk), ck1, ck2)`：内层为 partition key（可复合），外层为 clustering key。
- `CLUSTERING ORDER` 影响磁盘物理顺序与范围扫描方向。
- 表级 `default_time_to_live` 可让数据自动过期（配合 TWCS 见 [Compaction](/docs/CS/DB/Cassandra/Compaction.md)）。

## DML and Conditionals

```sql
INSERT INTO events (device_id, bucket, ts, payload)
  VALUES (..., ...) USING TTL 3600;            -- 单行 TTL

UPDATE accounts SET balance = balance - 100
  WHERE id = ? IF balance >= 100;              -- LWT（Paxos，慢）

DELETE FROM events WHERE device_id=? AND bucket=? AND ts < ?;  -- 按聚类键范围删
```

- `IF` / `IF EXISTS` 触发 **LWT（SERIAL CL，Paxos 四轮）**——高频慎用（见 [Consistency](/docs/CS/DB/Cassandra/Consistency.md)）。
- `USING TTL` / `USING TIMESTAMP` 可精确控制存活时间与写入时间戳（手动 timestamp 是双刃剑，易引发 LWW 乱序）。

## BATCH

```sql
BEGIN BATCH
  INSERT INTO t1 ...;
  INSERT INTO t2 ...;
APPLY BATCH;
```

- **LOGGED BATCH（默认）**：原子地跨 partition 写，但代价是 coordinator 写「batch log」、且若 batch 含不同 partition key 会**放大协调开销**——**不要用 batch 单纯「批量插入不同分区」，那会砸向单个 coordinator**。
- **UNLOGGED BATCH**：不保证原子，仅减少往返，适合同一 partition 的多写。

## SELECT and Pagination

```sql
SELECT * FROM events
  WHERE device_id=? AND bucket=? AND ts > ? AND ts < ?
  ORDER BY ts DESC
  LIMIT 100;                       -- 配合 paging state 翻页
```

- 必须**带 partition key**（除非 `ALLOW FILTERING`，但那是全集群扫描，生产禁用）。
- 跨分区排序/聚合不支持；范围扫描只能发生在 clustering key 上。
- 客户端驱动用 **paging state** 做高效翻页，避免一次拉全表。
- `token()` 函数可做跨分区范围扫描（按 token 切分），用于离线全表遍历。

## Materialized Views (慎用)

MV 让 Cassandra 自动维护「以另一列作主键」的冗余表。但实现上 MV 有已知的一致性与性能陷阱（更新可见性、可用性依赖 base+view 双写、重建昂贵），4.0+ 文档已明确**不推荐**在新设计中使用。新系统应改用手动维护的去规范化表或 **SAI**（见 [Indexing](/docs/CS/DB/Cassandra/Indexing.md)）。

## Functions and UDF/UDA

- 内置标量/聚合函数；5.0 新增 `abs/exp/log/log10/round` 等数学函数。
- `CREATE FUNCTION` / `CREATE AGGREGATE` 可定义 UDF/UDA（需在 `cassandra.yaml` 开启 `enable_user_defined_functions`，且默认禁止非纯函数以策安全）。

## CQL vs SQL

| 能力 | SQL | CQL |
| --- | --- | --- |
| JOIN | 支持 | **不支持** |
| 子查询 | 支持 | 不支持 |
| 跨行事务 | ACID | 仅单行 LWT；跨分区 6.0 Accord |
| 外键 | 支持 | 无 |
| 二级索引 | 普遍 | 受限（见 Indexing） |
| 主键建模 | 范式化 | 反范式、按查询建表 |

## Source-Level Classes

- **解析 / 执行**：`cql3.QueryProcessor`（编译缓存 + 执行）、`cql3.statements.{ModificationStatement, SelectStatement, BatchStatement}`；`QueryHandler` / `QueryState` 贯穿一次交互。`ALLOW FILTERING` 在 `SelectStatement` 内被标记为全集群扫描，生产应禁用。
- **写 / 读命令**：`db.Mutation` / `db.partitions.PartitionUpdate`（写），`db.ReadCommand` / `db.SinglePartitionReadCommand` / `db.PartitionRangeReadCommand`（读，含 `DataRange` 描述扫描区间）。
- **LWT / Paxos**：`service.paxos` 包（`PaxosState` / `Prepare` / `Propose` / `Commit` / `CASRequest`），LWT 经 `SERIAL`/`LOCAL_SERIAL` CL 触发；6.0 Accord 下 `BEGIN TRANSACTION` 走 `service.accord`（CEP-15）。
- **Batch**：`BatchStatement` 区分 `LOGGED`（写 batch log，跨 partition 原子但放大 coordinator 开销）与 `UNLOGGED`（仅减往返）。logged batch 的 batch log 写到 `system.batches`。
- **MV**：`db.view.{View, MaterializedView}`；base→view 异步更新（`ViewBuilder` / `ViewManager`）是一致性陷阱来源，4.0+ 文档不推荐新设计。
- **UDF / UDA**：`cql3.functions.{UDFunction, UDAggregate}`，默认禁止非纯函数（`enable_user_defined_functions`）。

## Links

- [Cassandra](/docs/CS/DB/Cassandra/Cassandra.md)
- [Data Model](/docs/CS/DB/Cassandra/DataModel.md)
- [Indexing](/docs/CS/DB/Cassandra/Indexing.md)
- [Consistency](/docs/CS/DB/Cassandra/Consistency.md)

## References

- [Cassandra CQL Reference (官方文档)](https://cassandra.apache.org/doc/latest/cassandra/cql/)
