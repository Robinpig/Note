## Introduction

Cassandra 的数据模型是**多维 map**：`Keyspace → Table（Column Family）→ Partition → Row → Cell（name/value/timestamp）`，属于 BigTable 谱系的宽列模型。建模的核心原则是**「按查询建表」**——表结构由访问模式反推，而非先有实体再 join。

> 基线：Cassandra 5.0。CQL（Cassandra Query Language）是用户与模型交互的接口，详见 [CQL](/docs/CS/DB/Cassandra/CQL.md)。

## Keyspace

Keyspace 是表的最外层容器，主要声明**复制策略**与**复制因子（RF）**：

```sql
CREATE KEYSPACE IF NOT EXISTS myks WITH REPLICATION = {
  'class': 'NetworkTopologyStrategy',
  'dc1': 3, 'dc2': 3
};
```

- `SimpleStrategy`：仅单 DC，按 token 环顺序取 N 个连续 replica——**生产不可用**（扩缩容/拓扑变化会错位）。
- `NetworkTopologyStrategy`：按 DC 分别指定 RF，配合 snitch 把 replica 放不同机架——**生产标准**。

## Table and Primary Key

CQL 的「表」在内部仍是宽列存储，但对外暴露为带 schema 的二维表。`PRIMARY KEY` 决定数据分布与排序：

```sql
CREATE TABLE events (
  device_id  uuid,
  bucket     date,
  event_time timestamp,
  payload    text,
  PRIMARY KEY ((device_id, bucket), event_time)
) WITH CLUSTERING ORDER BY (event_time DESC);
```

- **Partition Key**（括号内层，可复合 `(a, b)`）：决定行落在哪个节点（对 `token(partition_key)` 取模）。**同一 partition key 的所有行物理相邻**，构成「宽行 / 宽分区」。
- **Clustering Key**（外层）：分区**内**的排序键，支持 `ASC/DESC`。没有 clustering key 时，每行就是一个独立「窄」行。
- 只有 partition key 被哈希；clustering key 仅用于分区内有序拼接——这正是 Cassandra 既支持哈希分布、又支持分区内范围扫描的折中（与 Dynamo 纯哈希、BigTable 纯有序不同）。

## Static Columns

`STATIC` 列的值在**整个 partition** 内共享一份，不随 clustering 行重复存储，适合「设备元信息」这类每分区只有一个值的字段：

```sql
CREATE TABLE device_metrics (
  device_id uuid,
  owner     text STATIC,
  ts       timestamp,
  value    double,
  PRIMARY KEY (device_id, ts)
);
```

## Collections and UDT

- **集合类型**：`list`（有序可重复）、`set`（去重）、`map`（kv）。适合「一个 partition 内少量、增长可控」的多值属性。
- **UDT（User-Defined Type）**：把结构化子对象封装成类型；`frozen<>` 表示整体序列化、不可单独更新其中字段。
- 坑：集合过大或频繁 append 会造成**超大单元（oversized cell）**，触发 4.0+ 的 `cqlsh` 警告与 `large_cells` 监控。

## Wide-Row Modeling

宽列模型的杀手锏是「一个 partition key 下挂海量动态列 / 海量 clustering 行」，天然适配：

- **时序数据**：`(device, day)` 作 partition，`event_time` 作 clustering，单天数据连续存放、按时间范围扫。
- **物化视图式去规范化**：把「一个用户的全部订单」「一个话题的全部帖子」放一个 partition，一次读取拿到全部。

建模反模式（务必规避）：

1. **热点 partition / 超大分区**：单 partition 行数或体积过大（百万级行、数十 GB）会导致读写放大多、compaction 卡死、GC 压力。用「桶化（bucketing）」把热点 key 拆成多个子 partition（如 `device_id || day`）。
2. **无界宽行**：clustering 行永不删除且无 TTL，分区无限增长。
3. **用二级索引兜低基数字段**：见 [Indexing](/docs/CS/DB/Cassandra/Indexing.md)。
4. **把 MySQL 的 join/外键思维搬过来**：Cassandra **不支持 join、不支持跨 partition 事务**（跨 partition 事务要到 6.0 的 Accord 才有，5.0 仍只有单 partition LWT），必须预先 join 进表。

## Source-Level Classes

- **Schema 元数据**：`schema.{KeyspaceMetadata, TableMetadata, ColumnMetadata}`，`TableMetadata` 持有 `partitionKeyColumns` / `clusteringColumns` / `regularColumns` 与 `ClusteringOrder`；列的 `ColumnMetadata.Kind` 区分 `PARTITION_KEY` / `CLUSTERING` / `STATIC` / `REGULAR`。
- **分区 / 行 / 单元格**：`db.partitions.{Partition, AtomicBTreePartition}`——**partition 是存储与原子性的基本单位**（整 partition 以 BTree 原子可见）；`db.rows.{Row, BTreeRow, Cell, Clustering}` 表示分区内按 clustering 排序的行与单元格；`db.partitions.PartitionUpdate` 是单分区变更。
- **类型与比较器**：`db.marshal.AbstractType`（CQL 类型体系，如 `UTF8Type` / `UUIDType` / `CompositeType`）；clustering 的排序由 `db.marshal.ClusteringComparator` 强制——`CLUSTERING ORDER` 最终落到比较器，而非仅逻辑声明。
- **DDL 编译**：`cql3.statements.CreateTableStatement` / `AlterTableStatement` 把 CQL DDL 编译成对 `schema` 的变更；legacy thrift 接口在 4.0 已移除，CQL 是唯一入口。
- **MV**：`db.view.{View, MaterializedView, ViewBuilder}`；base→view 异步维护是一致性陷阱来源（见 [CQL](/docs/CS/DB/Cassandra/CQL.md)）。

## Links

- [Cassandra](/docs/CS/DB/Cassandra/Cassandra.md)
- [CQL](/docs/CS/DB/Cassandra/CQL.md)
- [Indexing](/docs/CS/DB/Cassandra/Indexing.md)
- [Storage Engine](/docs/CS/DB/Cassandra/StorageEngine.md)

## References

- [Cassandra Data Modeling (官方文档)](https://cassandra.apache.org/doc/latest/cassandra/data_modeling/)
- [Cassandra CQL Reference](https://cassandra.apache.org/doc/latest/cassandra/cql/)
