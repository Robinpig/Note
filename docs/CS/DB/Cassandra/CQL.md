## Introduction

**CQL（Cassandra Query Language）** 是用户与 Cassandra 交互的接口，表面像 SQL，但语义受宽列模型与“无 join、无跨 partition 事务”约束。写操作最终落到带 timestamp 的 cell mutation，读操作按主键选择单 partition 或 token range；理解这两个落点，才能正确使用 TTL、batch、LWT 和过滤。建模方法见 [Data Model](/docs/CS/DB/Cassandra/DataModel.md)。

> 基线：Cassandra 5.0.9。5.0 新增数学函数、动态数据脱敏等能力，但 CQL 的分布式事务边界并未因此改变。

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
  AND default_time_to_live = 864000;
```

- `PRIMARY KEY ((pk), ck1, ck2)`：内层为 partition key，可复合；外层为 clustering key，只负责分区内排序。
- `CLUSTERING ORDER` 改变 clustering comparator 的方向，决定磁盘顺序与范围扫描方向。
- 表级 `default_time_to_live` 是默认值，单条 `INSERT`/`UPDATE` 的 `USING TTL` 可以覆盖它；它与 TWCS 的时间窗配合使用，详见 [Compaction](/docs/CS/DB/Cassandra/Compaction.md)。
- `STATIC` 列在 partition 内共享，`frozen<>` 把集合或 UDT 压成单 cell；这些选项直接改变存储模型，应结合 [Data Model](/docs/CS/DB/Cassandra/DataModel.md) 设计。

## DML and Conditionals

```sql
INSERT INTO events (device_id, bucket, ts, payload)
  VALUES (?, ?, ?, ?) USING TTL 3600;

UPDATE accounts SET balance = balance - 100
  WHERE id = ? IF balance >= 100;

DELETE FROM events
  WHERE device_id = ? AND bucket = ? AND ts < ?;
```

- `INSERT` 和 `UPDATE` 都是 upsert：没有关系数据库式的“先读再写”，普通写入直接生成新的 cell mutation。
- `IF` / `IF EXISTS` 触发 **LWT**，只作用于单个 partition。默认 Paxos v1 的写路径约 4 次往返、读路径约 3 次；v2 将写路径降至约 2 次、读路径降至 1~2 次，详见 [Consistency](/docs/CS/DB/Cassandra/Consistency.md)。
- `USING TTL` 以秒设置存活时间；`USING TIMESTAMP` 以微秒指定写入时间戳。手动 timestamp 可以修复客户端时钟，也可以让未来写入压制正常写入，或让旧写入立即输给已有值。
- TTL 到期后 cell 在读取时表现为删除，但可 purge 的 tombstone 还要满足 `gc_grace_seconds` 等回收条件。TTL 不是事务超时，也不是 replica 间的传播超时。

## Write Conflict Resolution

Cassandra 的普通写是 LWW，但“最后写入胜出”只准确描述了**不同 timestamp**。相同 timestamp 的冲突由 `Cells.reconcile` 确定性处理：

| 冲突条件 | cell 级合并结果 |
| --- | --- |
| timestamp 不同 | timestamp 较大者胜出 |
| timestamp 相同，一方是 tombstone/expiring cell，另一方是 live cell | tombstone/expiring 一方胜出 |
| 两者都是 tombstone/expiring cell | 纯 tombstone 优先于 expiring cell；同类先比较 `localDeletionTime`，较大者胜出 |
| 两者都 expiring 且 `localDeletionTime` 相同 | 较短 TTL 胜出 |
| 两者都是普通 live cell | 按 value bytes 做确定性比较，不依赖到达顺序 |
| counter cell | 使用 counter context 合并，不是普通 LWW |

这解释了为什么并发写入、时间戳回拨和客户端重试可能产生“看似旧值覆盖新值”的结果。批量写默认共享 batch timestamp，除非语句显式覆盖；相同 timestamp 冲突不会简单取决于哪个 replica 最后收到。

## BATCH

```sql
BEGIN BATCH
  INSERT INTO t1 ...;
  INSERT INTO t2 ...;
APPLY BATCH;
```

| 类型 | 语义 | 主要成本 |
| --- | --- | --- |
| `LOGGED`（默认） | coordinator 写 batchlog；故障后由 `BatchlogManager` 重放未完成的 mutation | 额外 batchlog 写入、恢复流量、单 coordinator 压力 |
| `UNLOGGED` | 不写 batchlog，仅合并客户端往返 | 失败时可能只应用部分 mutation，跨 partition 会触发告警 |

logged batch 提供的是**故障恢复意义上的 batch 原子性**：保证一组 mutation 不会因 coordinator 崩溃而永久丢失，并由 batchlog 补齐；它不是跨分区 2PC，也不提供关系数据库式的隔离或可回滚事务。

执行路径还有两个容易忽略的优化：

- 同一 keyspace、同一 `DecoratedKey` 的语句先合并为一个 `Mutation`；仅有一个 Mutation 时走普通单分区写路径，不写 batchlog。
- 多个 partition 会产生多个 Mutation，所有 mutation 仍经同一 coordinator 发起，因此**不要用 batch 伪装高吞吐批量导入**；大批次还会触发 `batch_size_warn_threshold_in_kb` / `batch_size_fail_threshold_in_kb`。

## SELECT and Pagination

```sql
SELECT * FROM events
  WHERE device_id = ? AND bucket = ? AND ts > ? AND ts < ?
  ORDER BY ts DESC
  LIMIT 100;
```

- 高效查询应带完整 partition key，并满足 clustering 前缀约束。缺少 partition key 时通常需要 `ALLOW FILTERING` 或 `token()` 范围扫描。
- `ALLOW FILTERING` **不等于必然全集群扫描**：它可能只过滤某个 partition 或 token range；真正危险的是未约束 partition 的广播，以及 Guardrails 配置允许的大范围过滤。生产中应把它当作例外并限制扫描规模。
- 跨 partition 的全局 `ORDER BY` 不支持；聚合只针对查询实际读取的行，不等于经过优化的分布式 SQL 聚合。
- 客户端驱动用 **paging state** 翻页；它是绑定查询的 opaque 状态，不是 `OFFSET`，应避免一次拉全表。
- `token(partition_key)` 可把全表拆成 token range 做离线扫描。即使分段，也要同时考虑并发、超时和 tombstone 成本。

## Materialized Views

MV 让 Cassandra 自动维护“以另一列作主键”的冗余表。5.0.9 中它仍是 **experimental 且默认关闭**；实现上存在更新可见性、base/view 可用性耦合和昂贵重建等风险。

新系统优先手动维护去规范化表；若访问模式只是等值或范围过滤，可以评估 SAI，但它不是 MV 的完全替代品，详见 [Indexing](/docs/CS/DB/Cassandra/Indexing.md)。

## Functions and UDF/UDA

- 内置标量/聚合函数；5.0 增加 `abs` / `exp` / `log` / `log10` / `round` 等数学函数。
- `CREATE FUNCTION` / `CREATE AGGREGATE` 可定义 UDF/UDA，需要把 `user_defined_functions_enabled` 设为 `true`；默认关闭用户函数，开启后仍受 sandbox 约束，`allow_insecure_udfs` 默认也是 `false`。
- 动态数据脱敏属于查询执行与权限边界，不等同于静态加密；具体语义见 [Security](/docs/CS/DB/Cassandra/Security.md)。

## CQL vs SQL

| 能力 | SQL | CQL 5.0.9 |
| --- | --- | --- |
| JOIN | 支持 | **不支持** |
| 子查询 | 支持 | 不支持 |
| 跨行/跨分区事务 | ACID | 仅单 partition LWT；logged batch 不是 ACID |
| 外键 | 支持 | 无 |
| 普通写入 | 可依赖行锁和约束 | upsert + cell timestamp |
| 二级索引 | 由数据库统一优化 | 本地索引与 fan-out，查询建模仍是根本 |
| 主键建模 | 范式化实体 | 反范式、按查询建表 |

## Source-Level Classes

- **解析 / 执行**：`cql3.QueryProcessor` 负责编译缓存与执行，`cql3.statements.{ModificationStatement, SelectStatement, BatchStatement}` 描述语句；`QueryHandler` / `QueryState` 贯穿一次交互。
- **写 / 读命令**：`db.Mutation` / `db.partitions.PartitionUpdate` 表示写入，`db.ReadCommand` / `db.SinglePartitionReadCommand` / `db.PartitionRangeReadCommand` 表示读取，`DataRange` 描述 token 与 clustering 扫描区间。
- **冲突合并**：`db.rows.Cells.reconcile` 处理 cell timestamp、tombstone/expiring 与 value 的确定性合并；`UpdateParameters` / `DeletionTime` / `LivenessInfo` 生成 timestamp、TTL 和过期信息。
- **LWT / Paxos**：`service.paxos` 包包含 `PaxosState` / `Prepare` / `Propose` / `Commit` / `CASRequest`；LWT 使用 `SERIAL` / `LOCAL_SERIAL`，普通写仍使用声明的 consistency level。
- **Batch**：`BatchStatement` 选择 logged/unlogged 路径，`BatchUpdatesCollector` 按 keyspace + `DecoratedKey` 合并 Mutation，`StorageProxy.mutateWithTriggers` 执行写入，`BatchlogManager` 负责 batchlog 与恢复。
- **过滤 / 分页**：`StatementRestrictions` 构造 partition/clustering 限制，`SelectStatement` 生成 `ReadCommand` 和 paging；Guardrails 对表数量、分区大小和查询复杂度施加限制。
- **MV**：`db.view.{View, MaterializedView, ViewBuilder, ViewManager}` 负责异步维护；5.0.9 默认不启用。
- **UDF / UDA**：`cql3.functions.{UDFunction, UDAggregate}`；`user_defined_functions_enabled` 默认关闭用户函数，`allow_insecure_udfs` 默认禁止不安全 UDF。

## Links

- [Cassandra](/docs/CS/DB/Cassandra/Cassandra.md)
- [Storage Engine](/docs/CS/DB/Cassandra/StorageEngine.md)
- [Replication](/docs/CS/DB/Cassandra/Replication.md)
- [Operations](/docs/CS/DB/Cassandra/Operations.md)

## References

- [Cassandra CQL Reference](https://cassandra.apache.org/doc/5.0/cassandra/developing/cql/index.html)
- [Cassandra 5.0.9 Source](https://github.com/apache/cassandra/tree/cassandra-5.0.9)
