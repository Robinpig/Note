## Introduction

Cassandra 的主访问路径是靠 **partition key** 直接定位。当查询条件落在非主键列（或 clustering 前缀缺失）时，就需要**二级索引**。但 Cassandra 的索引实现与传统关系型数据库截然不同，理解其代价模型才能用对、不踩坑。

> 基线：Cassandra 5.0。SAI（Storage-Attached Index, CEP-7）是 5.0 的官方推荐索引；SASI 已被取代；经典本地二级索引仍可用但受限。

## Local Secondary Index (经典)

- 二级索引在**每个节点本地**为「被索引列值 → 本节点持有的 row」建倒排，是**本地索引**而非全局索引。
- 查询时 coordinator 必须把请求**广播到所有持有该列潜在副本的节点**再汇总——**读放大随节点数线性增长**，节点越多越慢。
- 适合：基数适中、且查询能先约束到某个 partition（`WHERE partition_key = ? AND indexed_col = ?`）的列。
- 不适合：高基数列（如 user_id）、无 partition 约束的全表索引扫描。

## SASI (SSTable-Attached Secondary Index, 3.x)

- 3.x 时代为支持 `LIKE`、范围、文本检索而引入，挂在 SSTable 上。
- 问题：`CONTAINS`/范围查询易扫大量数据、内存与 compaction 开销大、长期不稳定。**5.0 起被 SAI 取代，不应在新集群使用。**

## SAI (Storage-Attached Index, 5.0, CEP-7)

- 5.0 的**官方推荐索引**，把索引与 SSTable 生命周期绑定、与存储层协同，性能和资源效率显著优于 SASI 与经典本地索引。
- 同时支持**标量索引**与 **Vector（向量）索引**（为 AI/相似度检索而生，配合 5.0 的 `VECTOR` 类型与 `ANN` 近似最近邻查询）。
- 仍遵循 Cassandra「索引不保证全局强一致、写入有额外开销」的基调，但运维友好度与查询能力大幅提升。
- 创建示例：

```sql
CREATE CUSTOM INDEX IF NOT EXISTS ON myks.users (email)
  USING 'StorageAttachedIndex';

CREATE CUSTOM INDEX IF NOT EXISTS ON myks.docs (embedding)
  USING 'StorageAttachedIndex' WITH OPTIONS = {'similarity': 'cosine'};
```

### SAI Internals (CEP-7, 5.0)

SAI 把索引组件**贴在每张 SSTable 旁**、随 flush/compaction 一起构建与合并，索引与数据永远同步。核心类在 `org.apache.cassandra.index.sai`：

- **磁盘组件（per-SSTable）**：`disk.format.IndexComponent` 枚举列出全部组件——`TERMS_DATA`（TrieTermsDictionaryWriter 写 term 字典）、`POSTING_LISTS`（PostingsWriter 写倒排）、`BALANCED_TREE`（BlockBalancedTreeWriter 写 term→rowId 的平衡树）、`ROW_TO_TOKEN` / `ROW_TO_PARTITION` / `PARTITION_TO_SIZE`（rowId↔token/partition 映射）、`COMPRESSED_VECTORS`（Product Quantization 压缩向量，向量索引用）、`GROUP_META` / `GROUP_COMPLETION_MARKER` 等。
- **内存索引**：flush 前更新驻留 JVM 对象的 memtable 索引（文本用内存倒排、向量用 `VectorMemoryIndex` 存 HNSW 图导航结构）；达到 flush 阈值时 SAI 直接把 memtable 索引落盘，**不再额外建内存表示**。
- **读路径**：coordinator 的 SAI 协调器先挑**最选择性**的索引最小化过滤空间，各 SSTable 的索引组件并行查 posting，再用 rowId 在 base SSTable 取数据；compaction 时对输出 SSTable **重建**索引组件（而非拼接旧图）。
- **标量 + 向量**：标量支持等值/范围/多列组合谓词；向量（`VECTOR` 类型 + `similarity_cosine/euclidean/dot_product`）经 `ORDER BY ... ANN OF` 做近似最近邻（底层 jvector 库的 HNSW/DiskANN 类图，CEP-30）。
- **限制不变**：查询若不约束 partition key，仍要广播到整个 ring 的所有 token range（fan-out 没消除）；SAI 降低的是「每节点索引查找成本」，不是把 Cassandra 变成关系型 ad-hoc 查询引擎。

### SASI vs SAI (源码对照)

SASI（`index.sasi`）仍有 `OnDiskIndex(Builder)` / `IndexMemtable`（管理 `TrieMemIndex` / `SkipListMemIndex`）/ `TokenTree(Builder)`（B+ 树变体）/ `QueryPlan`（含 `RangeUnionIterator` / `RangeIntersectionIterator`）。它**在 5.0 仍可用但已被 SAI 取代**，且 `cassandra_latest.yaml` 让 `CREATE INDEX` 默认走 SAI。新集群应直接用 SAI。

## When (Not) to Use

| 场景 | 建议 |
| --- | --- |
| 查询总能带 partition key | 直接主键访问，无需索引 |
| 高基数列、需按值查 | 重新建模（把该列并入 partition key）或 SAI |
| 全文/模糊/向量检索 | SAI（5.0+） |
| 多列组合过滤 | 考虑 SAI 或多套去规范化表 |
| 无 partition 约束的全表索引 | **避免**（读放大灾难） |

## Global Indexing Alternatives

Cassandra 本身不提供「全局二级索引」这种零读放大方案。需要强索引语义时，常见做法是：

- 在应用层维护**去规范化表**（同一份数据按不同主键存多份）；
- 或把索引/检索需求外挂到 Elasticsearch / Solr（Cassandra 作系统 of record）。

## Source-Level Classes

- **经典本地二级索引**：`index.SecondaryIndex` / `index.internal.InternalIndex`；索引是「每节点本地、被索引值 → 本节点 row」的倒排，广播读放大。
- **SAI**：`index.sai` 包（见上）。
- **选择语法**：`CREATE CUSTOM INDEX ... USING 'StorageAttachedIndex'`（SAI）或 `USING 'org.apache.cassandra.index.sasi.SASIIndex'`（SASI，遗留）。

## Links

- [Cassandra](/docs/CS/DB/Cassandra/Cassandra.md)
- [Data Model](/docs/CS/DB/Cassandra/DataModel.md)
- [CQL](/docs/CS/DB/Cassandra/CQL.md)
- [Storage Engine](/docs/CS/DB/Cassandra/StorageEngine.md)

## References

- [CEP-7 Storage-Attached Indexes](https://cassandra.apache.org/doc/latest/cassandra/architecture/sai.html)
- [Cassandra Secondary Indexes (官方文档)](https://cassandra.apache.org/doc/latest/cassandra/architecture/indexing.html)
