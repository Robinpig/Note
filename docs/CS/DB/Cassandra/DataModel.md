## Introduction

Cassandra 的数据模型是**多维 map**：`Keyspace → Table（Column Family）→ Partition → Row → Cell（name/value/timestamp）`，属于 BigTable 谱系的宽列模型。建模的核心原则是**「按查询建表」**——先列出访问路径，再决定 partition key、clustering key 和冗余表，而不是先建实体模型再靠 join 补救。CQL 是这层模型的操作接口，详见 [CQL](/docs/CS/DB/Cassandra/CQL.md)。

> 基线：Cassandra 5.0.9。本文讨论的“原子性”严格区分单节点存储操作、单 partition LWT 与跨 partition 事务，不能互相替代。

## Keyspace

Keyspace 是表的最外层容器，主要声明**复制策略**与**复制因子（RF）**：

```sql
CREATE KEYSPACE IF NOT EXISTS myks WITH REPLICATION = {
  'class': 'NetworkTopologyStrategy',
  'dc1': 3, 'dc2': 3
};
```

| 策略 | 放置方式 | 适用边界 |
| --- | --- | --- |
| `SimpleStrategy` | 在单 token 环上顺序取 N 个 replica | 单 DC 开发验证；生产环境在扩缩容和拓扑变化时容易产生放置偏差 |
| `NetworkTopologyStrategy` | 按 DC 分配 RF，再在 DC 内优先跨 rack 放置 | 多 DC、多机架生产环境的标准选择 |

复制因子不是表属性，而是 keyspace 级策略；增加 RF 后既有数据不会自动补齐，需要执行 full repair，详见 [Replication](/docs/CS/DB/Cassandra/Replication.md)。

## Table and Primary Key

CQL 的「表」在内部仍是宽列存储，但对外暴露为带 schema 的二维表。`PRIMARY KEY` 同时决定数据分布、分区内顺序和可执行的查询形状：

```sql
CREATE TABLE events (
  device_id  uuid,
  bucket     date,
  event_time timestamp,
  payload    text,
  PRIMARY KEY ((device_id, bucket), event_time)
) WITH CLUSTERING ORDER BY (event_time DESC);
```

### Partition Key and Token Routing

- **Partition Key** 是括号内层，可以是单列或复合列 `(a, b)`。复合 key 的各分量按类型序列化，再组成规范化的 composite key。
- `Murmur3Partitioner` 对**序列化后的 key bytes**做 Murmur3 哈希，得到 64-bit signed `LongToken`；节点按 token 环和 vnode ownership 查找 replica。这里**不是对 key 取模**，也不是直接哈希 CQL 文本表示。
- token 只用于路由。`DecoratedKey` 同时保存 token 和原始 key bytes；不同 key 即使 hash 相同，也不会在存储层合并成一个 partition。
- 同一 partition key 的所有行落在同一组 replica 上，并在各 replica 上构成独立的宽分区。这里的“相邻”是存储局部性，不表示它们只存在于一个节点。

### Clustering Key and Local Ordering

- **Clustering Key** 是外层的一个或多个列，只在 partition 内排序，**不参与 token 计算**。
- 序列化后的 clustering prefix 由 `ClusteringComparator` 按列类型和 `CLUSTERING ORDER` 比较；因此排序不是逻辑查询时才发生的临时操作，而是读路径可以利用的物理顺序。
- 范围扫描必须从 clustering key 的完整前缀开始。例如 `PRIMARY KEY ((device, day), hour, minute)` 可以高效扫 `hour = ?` 及其前缀范围，不能任意跳过 `hour` 只按 `minute` 定位。
- 没有 clustering key 时，partition key 唯一确定一行；有 clustering key 时，一个 partition 可以包含大量共享静态信息的动态行。

### Query Shape Comes First

同一实体通常需要多张查询表。例如“按设备查时间线”和“按用户查最近事件”应分别设计 partition key；把同一份 payload 写进多张表是显式的反范式成本，而不是 Cassandra 自动完成的 join。

| 查询 | 推荐主键 | 冗余方式 |
| --- | --- | --- |
| 某设备某天的事件 | `((device_id, bucket), event_time)` | 设备事件主表 |
| 某用户最近事件 | `((user_id, bucket), event_time)` | 写入时额外维护用户事件表 |
| 全局按 token 离线扫描 | `(partition_key, clustering_key)` | 不新增表，用 `token()` 分段 |

## Static Columns

`STATIC` 列在**整个 partition** 内共享一份，不随 clustering 行重复存储，适合设备元信息这类“每个分区只有一个值”的字段：

```sql
CREATE TABLE device_metrics (
  device_id uuid,
  owner     text STATIC,
  ts        timestamp,
  value     double,
  PRIMARY KEY (device_id, ts)
);
```

- 静态值存放在 partition 的 static row 中，clustering key 不参与其身份。
- 插入静态列不要求同时存在 clustering row；只含静态行的 partition 也可以存在。
- 查询普通 clustering 行时可以返回该 partition 的静态值，但不能把静态列当作 clustering 维度过滤或排序。
- 修改静态列影响该 partition 的共享视图，因此并发写入仍需考虑 Cassandra 的 cell 冲突规则，而不是关系数据库式的行锁。

## Collections and UDT

- `list` 有序可重复，`set` 去重，`map` 保存 key/value；它们适合一个 partition 内少量、增长可控的多值属性。
- **非 frozen 集合是多 cell 结构**：每个元素使用同一个 complex column name，再用元素 key 区分 cell。`list` 用索引，`set`/`map` 用元素值或 map key 的序列化结果。
- **frozen 集合被序列化为一个普通 cell**，更新时整体替换；frozen UDT 同样以一个 cell 保存完整结构。
- 非 frozen UDT 可以按字段维护，frozen UDT 则只能整体读写。选择 frozen 不是“性能开关”，而是在多 cell 局部更新和单 cell 原子替换之间做取舍。
- 集合过大或频繁 append 会产生 oversized cell 和大量 complex cell，触发保护阈值、`large_cells` 指标和 compaction/GC 压力；集合也不应承载无界增长的历史列表。

## Wide-Row Modeling

宽列模型的杀手锏是“一个 partition key 下挂大量 clustering 行”，天然适配时序和按实体聚合的访问：

- **时序数据**：`(device, day)` 作 partition，`event_time` 作 clustering，单天数据连续存放，按时间范围扫。
- **实体时间线**：把“一个用户的全部订单”或“一个话题的全部帖子”放进一个 partition，一次读取获得有序结果。
- **桶化**：当单实体写入量或数据量过大时，增加 hash bucket、小时或天等维度，把逻辑实体拆成多个物理 partition。

建模反模式：

1. **热点或超大 partition**：单一 key 承载过多写入或数据，会使一个 replica 组成为瓶颈，并放大 compaction、tombstone scan、repair 和堆压力。阈值必须结合实际行宽和 SSTable 形态，不能只看“百万行”这类粗略数字。
2. **无界宽行**：clustering 行永不删除且无 TTL，partition 会持续增长，读路径和 compaction 成本随之累积。
3. **靠二级索引兜住全部访问路径**：索引不消除无 partition 约束时的 fan-out；优先把高频访问路径编码进主键，见 [Indexing](/docs/CS/DB/Cassandra/Indexing.md)。
4. **把 join/外键思维搬过来**：Cassandra 5.0.9 没有 join，也没有跨 partition ACID 事务；只有单 partition LWT，logged batch 也不是 2PC，详见 [Consistency](/docs/CS/DB/Cassandra/Consistency.md)。
5. **认为原子性会跨副本自动成立**：副本之间通过 consistency level、read repair 和 repair 收敛，单节点存储原子性不能替代分布式一致性设计。

## Source-Level Classes

- **Schema 元数据**：`schema.{KeyspaceMetadata, TableMetadata, ColumnMetadata}`；`TableMetadata` 持有 `partitionKeyColumns` / `clusteringColumns` / `regularColumns` 与 `ClusteringOrder`；`ColumnMetadata.Kind` 区分 `PARTITION_KEY` / `CLUSTERING` / `STATIC` / `REGULAR`。
- **Key 与 token**：`ClusteringPrefix` 负责 composite/clustering key 的序列化，`CompositeType` 编码各分量，`Murmur3Partitioner` 生成 token，`DecoratedKey` 保留 token 与原始 key；`ClusteringComparator` 决定分区内排序。
- **分区 / 行 / cell**：`db.partitions.{Partition, AtomicBTreePartition}`、`db.rows.{Row, BTreeRow, Cell, Clustering}`、`db.partitions.PartitionUpdate`。`AtomicBTreePartition` 通过 CAS 发布合并后的 BTree，保证单节点 memtable 中一次 `PartitionUpdate` 的合并不会被并发读看到“只应用了一半”；它不是跨副本事务。
- **多 cell 值**：`db.rows.ComplexColumnData` 及 `Lists` / `Sets` / `Maps` 把集合元素组织为 complex cell；frozen 值则走普通单 cell 序列化路径。
- **DDL 编译**：`cql3.statements.CreateTableStatement` / `AlterTableStatement` 把 CQL DDL 编译为 schema 变更；legacy thrift 接口在 4.0 已移除。
- **MV**：`db.view.{View, MaterializedView, ViewBuilder}`；5.0.9 中 MV 仍是 experimental 且默认关闭，base→view 的异步维护与重建是主要风险来源。

## Links

- [Cassandra](/docs/CS/DB/Cassandra/Cassandra.md)
- [Storage Engine](/docs/CS/DB/Cassandra/StorageEngine.md)

## References

- [Cassandra Data Modeling](https://cassandra.apache.org/doc/5.0/cassandra/developing/data-modeling/index.html)
- [Cassandra CQL Reference](https://cassandra.apache.org/doc/5.0/cassandra/developing/cql/index.html)
- [Cassandra 5.0.9 Source](https://github.com/apache/cassandra/tree/cassandra-5.0.9)
