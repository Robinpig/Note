## Introduction

Cassandra 的主访问路径靠 **partition key** 直接定位。当查询条件落在非主键列，或 clustering 前缀不完整时，二级索引可以提供候选 row，但不会把 Cassandra 变成全局索引数据库。理解索引的本地性、fan-out、一致性和写放大，才能判断该建索引、改主键，还是外挂检索系统。

> 基线：Cassandra 5.0.9。SAI 是 5.0 的主推新实现；SASI 仍存在，但 experimental 且默认关闭。ANN 向量索引同样 experimental。

## Secondary Index Model

| 实现 | 索引生命周期 | 主要能力 | 5.0.9 状态 |
| --- | --- | --- | --- |
| 经典 local secondary index | 本地隐藏表 / 节点内索引 | 等值、有限范围 | 可用，标准配置的默认实现 |
| SASI | SSTable-attached | 等值、范围、`LIKE` 前缀/包含/后缀 | experimental，默认关闭 |
| SAI | memtable + per-SSTable 组件 | 标量等值/范围、集合包含、向量 ANN | 5.0 主推；ANN experimental |

所有实现都要面对同一个分布式事实：**索引不是一张全局 B+Tree**。coordinator 通常要向相关 token range 的 replica 发查询，再汇总候选；没有 partition 约束时，fan-out 会随 ring 规模增长。

## Local Secondary Index

经典索引在**每个节点本地**保存“被索引值 → 本节点 row”的映射。查询计划把索引限制转成普通读请求，coordinator 仍需覆盖可能包含匹配值的 replica。

- 有 partition key 约束时，可以先把搜索限制在少量 replica，再在本地索引过滤。
- 无 partition key 约束时，需要覆盖所有 token range；节点越多、网络越慢，尾延迟越高。
- 索引与 base data 是两条写路径，更新可见性和 repair 需要分别考虑。
- 它适合基数适中、访问频率高且能带 partition 约束的列；不适合把所有 ad-hoc 查询都寄希望于本地索引。

## SASI

SASI 从 3.x 引入，把索引结构挂在 SSTable 上。5.0.9 并未删除它，但 `cassandra.yaml:1992` 的 `sasi_indexes_enabled` 默认为 `false`，并明确标注 experimental。

```sql
CREATE CUSTOM INDEX ON myks.users (name)
  USING 'org.apache.cassandra.index.sasi.SASIIndex'
  WITH OPTIONS = {
    'mode': 'PREFIX',
    'analyzer_class': 'org.apache.cassandra.index.sasi.analyzer.NonTokenizingAnalyzer',
    'case_sensitive': 'false'
  };
```

- `mode` 支持 `PREFIX`、`CONTAINS`、`SPARSE`；`PREFIX` 是默认模式。
- `NonTokenizingAnalyzer` 不对文本分词，只保留用于匹配的规范化 term。
- SASI 支持 `LIKE` 的前缀、包含和后缀搜索，这是它与 SAI 当前能力的重要差异。
- 范围和大结果集仍可能扫描大量 posting；内存、compaction 与查询开销没有因为“挂在 SSTable 上”而消失。

新集群不应把 SASI 当作默认生产索引，但“5.0 已删除/取代 SASI”也是错误说法。

## SAI

SAI（Storage-Attached Index，CEP-7）把索引组件与 SSTable 生命周期绑定，同时在 memtable 阶段维护内存索引。写入、flush、compaction 和删除都进入同一套索引维护路径。

### Scalar and Collection Queries

`Expression.IndexOperator` 的逻辑算子是：

```java
public enum IndexOperator
{
    EQ, RANGE, CONTAINS_KEY, CONTAINS_VALUE, ANN;
}
```

- `EQ`：标量等值。
- `RANGE`：数值、时间、UUID 等有序类型的范围。
- `CONTAINS_KEY` / `CONTAINS_VALUE`：map key/value 与集合元素匹配；CQL 中体现为 `CONTAINS` / `CONTAINS KEY`。
- `ANN`：向量近似最近邻，见下文。

5.0.9 的 SAI **不支持 `LIKE`**，但官方明确支持索引列的 `AND`/`OR` 与 `IN`（数值、文本类型）；`StatementRestrictions` 仍拒绝“主键 `IN` + 索引列限制”的组合。默认 `NonTokenizingAnalyzer` 不把文本拆成倒排词项，因此 SAI 也不是 Elasticsearch 式的分词全文索引。文本选项 `case_sensitive`、`normalize` 和 `ascii` 只改变 term 的规范化方式，不新增 `LIKE` 语义。

创建标量索引时应显式指定实现，避免依赖各 profile 的默认值：

```sql
CREATE CUSTOM INDEX IF NOT EXISTS ON myks.users (email)
  USING 'StorageAttachedIndex';
```

### SAI Internals

SAI 的磁盘索引按 column、SSTable 和 segment 组织，核心类位于 `org.apache.cassandra.index.sai`：

- **字符串 / 标量 term**：`TERMS_DATA` 使用 trie 保存压缩后的 term 字典；`POSTING_LISTS` 保存 term 到 rowId 的倒排；`BALANCED_TREE` 提供 term→rowId 的平衡树访问。
- **数值范围**：范围索引使用 k-d tree / balanced tree 结构，减少等值点查退化为全 posting 扫描的成本。
- **row 映射**：`ROW_TO_TOKEN` / `ROW_TO_PARTITION` / `PARTITION_TO_SIZE` 在 rowId、token、partition 和大小之间建立映射，供 candidate 回查 base SSTable。
- **内存阶段**：flush 前由 memtable index 接收写入；标量索引维护内存倒排，向量索引维护图结构。flush 时构建对应 SSTable 的索引组件，compaction 时对输出 SSTable 重建，而不是无限拼接旧索引。
- **读路径**：coordinator 选择可用的限制构造 SAI query plan，各 replica 在本地 SSTable 与 memtable 中查 candidate，再用 rowId 回表并按普通读路径合并、去重和过滤。

SAI 降低的是**每个节点内部查找 candidate 的成本**；无 partition 约束时仍需 fan-out。Guardrail `non_partition_restricted_index_query_enabled` 默认 `true`，允许这类查询；它是 enable flag，关闭时拒绝执行，但默认开启时不会自动告警。

### Vector Search and ANN

5.0 的 `VECTOR` 类型与 SAI ANN 由 CEP-30 引入。内存端使用 jvector 的 `GraphIndexBuilder` 构建 HNSW 风格图；磁盘端 `DiskAnn` 使用 jvector 的 `OnDiskGraphIndex` 与 Product Quantization 压缩向量。5.0 文档将其概括为“受 DiskANN 启发的磁盘图”，不要简单等同于原生 DiskANN 库。

```sql
CREATE TABLE myks.docs (
  id        uuid PRIMARY KEY,
  embedding vector<float, 3>
);

CREATE CUSTOM INDEX ON myks.docs (embedding)
  USING 'StorageAttachedIndex'
  WITH OPTIONS = {'similarity_function': 'COSINE'};

SELECT id FROM myks.docs
  ORDER BY embedding ANN OF [0.1, 0.2, 0.3]
  LIMIT 10;
```

`similarity_function` 支持 `COSINE`、`EUCLIDEAN`、`DOT_PRODUCT`，默认 `COSINE`；选项名不是 `similarity`。

ANN 在 5.0.9 有明确实验性限制：

- 只支持 float element vector；一维 vector 不支持 cosine；多数据目录不支持 ANN。
- CL 只支持 `ONE` / `LOCAL_ONE`，查询必须带 `LIMIT`，默认 top-k 上限为 1000。
- 不支持 paging、`PER PARTITION LIMIT`、`GROUP BY`、聚合函数，以及未建 SAI 索引的列上的过滤。
- ANN 返回近似结果，不支持 least-similar 搜索；频繁覆盖或删除 vector 列会降低查询效率。

## Query Planning and Fan-out

| 查询形态 | 候选范围 | 主要风险 |
| --- | --- | --- |
| `partition_key = ? AND indexed_col = ?` | 单个 partition 的 replica | 索引写放大、本地 posting 大小 |
| `partition_key IN (...) AND indexed_col = ?` | **不支持该组合** | `StatementRestrictions` 拒绝主键 `IN` 与索引列限制 |
| 仅 `indexed_col = ?` | 所有 token range | coordinator fan-out 与尾延迟 |
| 多索引组合 | 每个 replica 上求交/并集 | 算力、内存与 query plan 选择 |
| ANN + 非 SAI 索引列过滤 | **不支持** | `VECTOR_USAGE_WARNING` 明确排除该查询 |

`ALLOW FILTERING` 只表示允许在读取后过滤，不表示一定扫描全集群；同样，使用 SAI 也不表示查询自动变成全局强一致索引。索引结果最终仍要回到 base data 和一致性路径。

## When (Not) to Use

| 场景 | 建议 |
| --- | --- |
| 查询总能带 partition key | 直接主键访问，无需索引 |
| 高频等值/范围过滤且能限制 partition | SAI，或把访问路径建模进主键 |
| 高基数列、无 partition 约束 | 优先反范式表；全局索引 fan-out 很难消失 |
| 分词全文、模糊搜索 | 外挂 Elasticsearch/Solr；SAI 不支持 `LIKE` |
| 确需 `LIKE` 前缀/包含/后缀 | 可评估 experimental SASI，但先确认生产风险 |
| 多列组合过滤 | SAI 组合计划或多套去规范化表 |
| 向量检索 | 仅在 5.0.9 ANN 限制可接受时使用 SAI ANN |
| 无 partition 约束的全表索引 | 避免；通过 Guardrail 和建模限制 |

## Global Indexing Alternatives

Cassandra 不提供“零 fan-out 的全局二级索引”。需要更强检索语义时，常见做法是：

- 应用层维护**去规范化表**，按不同主键保存同一份逻辑数据；
- 把检索需求外挂到 Elasticsearch / Solr / 专用向量库，Cassandra 作为 system of record；
- 接受 CDC/双写的一致性窗口，并用 repair、对账或回填流程补偿。

## Source-Level Classes

- **经典本地索引**：`index.SecondaryIndex` / `index.internal.InternalIndex`，节点内维护索引并与 base write 路径协作。
- **SASI**：`index.sasi.{SASIIndex, OnDiskIndex, IndexMemtable, TokenTree}`；`PREFIX` / `CONTAINS` / `SPARSE` 由 analyzer 与 mode 决定。
- **SAI 协调**：`index.sai.StorageAttachedIndex`、`StorageAttachedIndexQueryPlan`、`cql3.restrictions.SingleColumnRestriction`。
- **SAI 磁盘**：`index.sai.disk.format.IndexComponent`、`disk.v1.{IndexWriterConfig, PerColumnIndexFiles}`、`disk.v1.vector.{OnHeapGraph, DiskAnn}`。
- **向量内存索引**：`index.sai.memory.VectorMemoryIndex` 使用 `OnHeapGraph`；jvector 提供图构建、磁盘图和 Product Quantization。
- **默认与保护**：`cassandra.yaml` 的 `default_secondary_index`、`non_partition_restricted_index_query_enabled`、`sai_sstable_indexes_per_query_*` 控制实现选择与查询保护。

## Links

- [Cassandra](/docs/CS/DB/Cassandra/Cassandra.md)
- [CQL](/docs/CS/DB/Cassandra/CQL.md)
- [Storage Engine](/docs/CS/DB/Cassandra/StorageEngine.md)
- [Consistency](/docs/CS/DB/Cassandra/Consistency.md)

## References

- [Storage-Attached Indexing Overview](https://cassandra.apache.org/doc/5.0/cassandra/developing/cql/indexing/sai/sai-overview.html)
- [Storage-Attached Indexing Concepts](https://cassandra.apache.org/doc/5.0/cassandra/developing/cql/indexing/sai/sai-concepts.html)
- [Cassandra Indexing Concepts](https://cassandra.apache.org/doc/5.0/cassandra/developing/cql/indexing/indexing-concepts.html)
- [Cassandra SASI](https://cassandra.apache.org/doc/5.0/cassandra/developing/cql/SASI.html)
- [Cassandra Vector Search](https://cassandra.apache.org/doc/5.0/cassandra/vector-search/overview.html)
- [Cassandra 5.0.9 Source](https://github.com/apache/cassandra/tree/cassandra-5.0.9)
