## Introduction

[ClickHouse](https://clickhouse.com) 是面向 OLAP 的**列式（column-oriented）** DBMS，由 Yandex 开源。核心是向量化执行引擎 + 列式存储，单机即可达到千万级/秒的写入与亚秒级聚合查询。

## Columnar Storage vs Row

- 行式（MySQL/PostgreSQL）：整行连续存放，事务/点查友好，分析型全表扫描需读大量无用列。
- 列式：同列连续存放，分析查询只读取所需列；列内数据类型一致 → 压缩率高（LZ4/ZSTD/Delta）、可按列批量向量化处理。

## Table Engines

### MergeTree Family

默认引擎，支持主键（稀疏索引）、分区、TTL、副本与采样。

- **MergeTree**：基础。数据按 `ORDER BY` 排序后切成 part，后台异步 merge 成有序大 part（类 LSM 但偏向读优化）。
- **ReplacingMergeTree**：merge 时按主键去重（保留最后版本），最终一致性去重。
- **SummingMergeTree / AggregatingMergeTree**：merge 时预聚合（pre-aggregation），物化聚合结果。
- **CollapsingMergeTree**：用 sign 行标记删除/更新，折叠抵消。
- **ReplicatedMergeTree**：基于 ZooKeeper/Keeper 的副本，分摊读写。

### Other Engines

- **Log 家族**（TinyLog/StripeLog）：简单无索引，适合小表/临时数据。
- **Distributed**：不存数据，把查询路由到集群各分片并汇总（sharding + 分布式聚合）。
- **外部表引擎**（MySQL/PostgreSQL/Kafka/Dictionary）：直接映射外部源，联邦查询。

## Key Features

- **稀疏主键索引**：每 `index_granularity`（默认 8192）行记一个 mark，定位 part 内数据块，并非每行索引。
- **分区（PARTITION BY）**：按天/租户切分，支持分区级 TTL 与 drop，查询时剪枝。
- **TTL**：列级（自动转冷/清列）与表级（行过期删除）。
- **物化视图 / Projection**：预计算加速。
- **向量化执行**：按列批量（Block）在 CPU 寄存器内处理，避免行级虚函数开销。

## Links

- [DataBases](/docs/CS/DB/DB.md?id=mysql)
- [Druid](/docs/CS/DB/Druid.md)
- [RocksDB](/docs/CS/DB/RocksDB/RocksDB.md)

## References

- [ClickHouse Documentation](https://clickhouse.com/docs)
- [The MergeTree Engine Family](https://clickhouse.com/docs/engines/table-engines/mergetree-family/mergetree)
