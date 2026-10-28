## Introduction

MongoDB 的索引是 WiredTiger 上的 B-tree：叶子节点存"索引键 → 记录位置"，通过记录位置回表取文档。没有索引的查询就是全集合扫描（`COLLSCAN`），在千万级集合上通常不可接受。索引设计的目标很单纯——**让 `$match` 与 `$sort` 都能由同一个索引支撑，且回表的文档数接近返回数**。

## Index Anatomy

- 每个集合默认有 `_id` 索引，`_id` 唯一性由它保证。
- 二级索引的叶子项指向文档的内部记录 ID；回表（`FETCH`）是额外的一次读取。
- 索引键默认做**前缀压缩**，长字符串公共前缀不会重复存储。
- 复合索引按键顺序排列，查询只能使用**最左前缀**。
- 一个集合最多 64 个索引，复合索引最多 32 个字段，单个索引键上限 1024 字节（4.2+）。

## Index Types

| 类型 | 用途 | 注意 |
| :--- | :--- | :--- |
| 单字段 | 等值/范围过滤 | 最基础 |
| 复合 | 多条件 + 排序 | 字段顺序决定可用性 |
| 多键（Multikey） | 数组字段 | 每个元素一条索引项，不能覆盖查询 |
| 唯一 | 业务唯一约束 | 字段缺失视为 null，只允许一条 |
| 稀疏（Sparse） | 只索引存在的字段 | 与 `$exists: false` 查询不兼容 |
| 部分（Partial） | 只索引满足过滤条件的文档 | 更适合"只查活跃数据" |
| TTL | 过期自动删除 | 单字段 Date；后台约每 60 秒清理一次 |
| 文本（Text） | 分词检索 | 每集合最多一个；大小写不敏感 |
| 通配（Wildcard） | 字段名不固定 | `$**`；写入放大明显 |
| 地理（2dsphere / 2d） | 位置查询 | 2dsphere 支持 GeoJSON 与球面计算 |
| Hashed | 哈希分片 | 只支持等值，不支持范围 |
| 隐藏（Hidden，4.4+） | 保留索引但不被规划器使用 | 先隐藏观察，再决定删除 |
| 聚簇（Clustered，5.3+） | 文档按 `_id` 物理聚簇 | 每集合仅一个，利于 `_id` 范围扫描 |

## Compound Index and ESR

复合索引字段顺序按 **E-S-R** 排列：

1. **Equality**：等值过滤字段；
2. **Sort**：排序字段；
3. **Range**：范围过滤字段。

```javascript
// 查询：status = "PAID" 且 createdAt >= ...，按 createdAt 排序
db.orders.createIndex({ status: 1, createdAt: 1 })
```

理由：等值字段定死一个前缀后，排序字段在索引中保持有序，范围字段放最后只做扫描裁剪。如果反过来把范围字段放中间，后续字段的排序就失去索引顺序。

排序方向：单字段索引可双向扫描；复合索引只有在**所有排序字段方向一致或整体取反**时才可直接使用，混合方向（`{a:1, b:-1}`）需要匹配索引定义。

覆盖查询：当查询过滤与投影字段都在索引中时，无需回表。

```javascript
db.orders.createIndex({ status: 1, total: 1 })
db.orders.find({ status: "PAID" }, { total: 1, _id: 0 })
// docsExamined = 0，keysExamined = nReturned
```

## Multikey Index

数组字段会为每个元素生成一条索引项，因此：

- 查询数组元素走的是同一套 B-tree，`{ tags: "cs" }` 可用 `tags` 索引；
- 一个复合索引里**最多只有一个数组字段**（并行数组无法笛卡尔展开）；
- 多键索引不能覆盖查询（返回的数组需要重新组装）；
- `$elemMatch` 能把多个条件约束到同一个数组元素上。

## Index Selection

规划器候选计划来自规则（前缀匹配、排序能否利用）与代价估算。常见现象：

- 两个索引都能用 → multi-planner 试跑后选扫描量小的；
- `$or` 可能触发**索引交集**（`INDEX_AND`），但通常不如一个合适的复合索引；
- 排序无法由索引满足 → 内存 `SORT`，默认 32MB 上限；
- 统计信息过期可能导致选错，可用 `hint()` 固定，但长期应修正索引设计。

`$indexStats` 能看每个索引的使用次数，是清理无用索引的依据：

```javascript
db.orders.aggregate([{ $indexStats: {} }])
```

## Build and Maintenance

4.2 起索引构建默认是 **hybrid build**：先扫描集合生成键，再在构建期间应用增量写入，减少对读写的影响（不再需要 `background: true`，该选项已被忽略）。

```javascript
// 先建隐藏索引，观察规划器与写入影响，再决定是否"转正"
db.orders.createIndex({ createdAt: 1 }, { hidden: true })
db.orders.collMod("orders", "index", "createdAt_1", { hidden: false })
```

要点：

- 构建需要额外磁盘空间，磁盘不足会导致构建失败；
- 唯一索引在大集合上构建期间仍会阻塞冲突写入；
- 删除索引前先隐藏，确认没有查询依赖它；
- 8.0 改进了索引构建流程，减少了构建期间的内存与 IO 压力。

## Explain Checklist

| 现象 | 含义 | 处理 |
| :--- | :--- | :--- |
| `COLLSCAN` | 无可用索引 | 按查询形状补索引 |
| `IXSCAN` + 高 `docsExamined` | 索引选择性差 | 调整复合索引顺序或加字段 |
| `SORT` stage | 排序未走索引 | 把排序字段纳入复合索引 |
| `SORT_KEY_GENERATOR` + `SORT_MERGE` | 分片归并排序 | 正常，但注意 shard 数放大的成本 |
| `FETCH` 次数远大于 `nReturned` | 回表放大 | 考虑覆盖索引或更精确的过滤 |
| 多个 `IXSCAN` + `AND_SORTED` | 索引交集 | 通常可合并为复合索引 |

## Links

- [MongoDB](/docs/CS/DB/MongoDB/MongoDB.md)
- [Query](/docs/CS/DB/MongoDB/Query.md)
- [Aggregation](/docs/CS/DB/MongoDB/Aggregation.md)
- [Storage Engine](/docs/CS/DB/MongoDB/StorageEngine.md)
- [BLink-Tree](/docs/CS/DB/Concept/BLink-Tree.md)

## References

- [MongoDB Indexes](https://www.mongodb.com/docs/manual/indexes/)
- [Compound Indexes](https://www.mongodb.com/docs/manual/core/indexes/index-types/index-compound/)
- [Multikey Indexes](https://www.mongodb.com/docs/manual/core/indexes/index-types/index-multikey/)
- [Index Builds](https://www.mongodb.com/docs/manual/core/index-creation/)
