## Introduction

聚合管道是 MongoDB 的"查询编译器"：文档依次流过一串 stage，每个 stage 变换后交给下一个。它等价于 SQL 的 `WHERE → GROUP BY → JOIN → SELECT → ORDER BY → LIMIT`，但表达方式是数组而非声明式语句。复杂分析、报表、ETL 增量写入都靠它；Change Streams 也是建在聚合框架上的。

## Pipeline Model

```javascript
db.orders.aggregate([
  { $match: { status: "PAID", createdAt: { $gte: ISODate("2026-01-01") } } },
  { $unwind: "$items" },
  { $group: {
      _id: "$items.sku",
      qty: { $sum: "$items.qty" },
      revenue: { $sum: { $multiply: ["$items.qty", "$items.price"] } }
  } },
  { $sort: { revenue: -1 } },
  { $limit: 10 }
])
```

管道是流式的：文档进入后逐个 stage 处理，能流式输出的 stage（`$match`、`$project`、`$limit`）不需要把全集放内存；阻塞型 stage（`$group`、`$sort`、`$facet`）需要缓冲。

## Core Stages

| Stage | 作用 | 对应 SQL |
| :--- | :--- | :--- |
| `$match` | 过滤，尽量放最前 | WHERE |
| `$project` | 投影、重命名、计算字段 | SELECT |
| `$group` | 分组聚合（`$sum` `$avg` `$min` `$max` `$push` `$addToSet`） | GROUP BY |
| `$sort` / `$limit` / `$skip` | 排序与分页 | ORDER BY / LIMIT |
| `$unwind` | 数组展开成多行 | UNNEST |
| `$lookup` | 左外连接 | LEFT JOIN |
| `$facet` | 同一输入跑多条子管道 | 多次聚合 |
| `$bucket` / `$bucketAuto` | 按区间/自动分桶 | 直方图 |
| `$setWindowFields` | 窗口函数（5.0） | OVER (PARTITION BY ...) |
| `$graphLookup` | 递归图遍历 | 递归 CTE |
| `$merge` / `$out` | 结果写回集合 | INSERT ... SELECT |

`$lookup` 有两种形态：`localField`/`foreignField` 的等值连接，以及带 `pipeline` + `let` 的子查询形态。5.1 起可以在分片集合上执行 `$lookup`，但被连接集合若未按外键分片，仍可能退化为广播。

## Expression Operators

stage 内部用表达式操作符做计算：算术（`$add` `$multiply` `$divide`）、字符串（`$concat` `$substrCP` `$trim`）、数组（`$map` `$filter` `$reduce` `$slice`）、日期（`$dateTrunc` `$dateAdd` `$dateDiff`）、条件（`$cond` `$switch` `$ifNull`）、类型转换（`$convert` `$toInt` `$toDecimal`）。

```javascript
// 用 $expr 在 $match 里做字段间比较
{ $match: { $expr: { $gt: ["$paid", "$total"] } } }

// 窗口函数：按用户分区、按时间排序累计
{ $setWindowFields: {
    partitionBy: "$uid",
    sortBy: { ts: 1 },
    output: { runningTotal: { $sum: "$amount", window: { documents: ["unbounded", "current"] } } }
} }
```

## Optimization

1. **`$match` 越早越好**：放在管道首部才能利用索引；后续 stage 产生的 `$match` 不会自动下推（优化器会做有限的移动，但不要依赖）。
2. **`$sort` 紧跟索引**：`$match` + `$sort` 能由同一个复合索引支撑时，排序不占内存。
3. **`$project` 提前瘦身**：减少后续 stage 搬运的字段，尤其在 `$lookup` 与大文档场景。
4. **`$lookup` 的外键要有索引**：否则每篇输入文档都触发一次全集合扫描。
5. **`$group` 的 `_id` 基数**：基数过大时内存压力高，必要时先过滤或分片聚合。
6. **限制**：单个 stage 默认最多用 100MB 内存，超出需 `allowDiskUse: true` 落临时文件；9.0 起单个查询操作总量默认限制为 1GB 或进程可用内存的 20%（取较大者），超限报 `ExceededMemoryLimit`。

`explain` 对聚合同样有效，能看到 `$cursor` 阶段的索引使用与每个 stage 的 `nReturned`/`executionTimeMillisEstimate`。

## Sharded Execution

`mongos` 会把管道拆成两段：能在 shard 上并行执行的部分（过滤、局部聚合）下发到各 shard，再在 `mongos` 上做 merge、全局 `$sort`、`$group`、`$limit`。因此：

- 带 shard key 的 `$match` 能裁剪到单个 shard；
- 全局 `$group` 的数据量取决于各 shard 的局部输出，而不只是最终结果；
- `$out` / `$merge` 写入分片集合时由 `mongos` 协调。

## Change Streams

Change Streams 用 `db.collection.watch(pipeline)` 订阅变更，内部读取 oplog，天然支持 `$match` 过滤与 `$project` 变换。每个事件带 resume token，断线后可用 `resumeAfter` 续读；6.0 起支持 pre-image / post-image（需在集合上开启 `changeStreamPreAndPostImages`）。

它有硬依赖：**resume token 必须还在 oplog 窗口内**。oplog 被覆盖后无法续读，只能重新全量同步。细节见 [Replication](/docs/CS/DB/MongoDB/Replication.md)。

## Pipeline vs Map-Reduce

`mapReduce` 自 5.0 起废弃。聚合管道在大多数场景更快、可索引、可分布式执行；只有极少数需要任意 JS 逻辑的批处理才考虑 `$accumulator`（服务端 JS，8.0 曾废弃、9.0 用 WASM 恢复）。

## Links

- [MongoDB](/docs/CS/DB/MongoDB.md)
- [Query](/docs/CS/DB/MongoDB/Query.md)
- [Index](/docs/CS/DB/MongoDB/Index.md)
- [Replication](/docs/CS/DB/MongoDB/Replication.md)
- [Time Series](/docs/CS/DB/MongoDB/TimeSeries.md)

## References

- [Aggregation Pipeline](https://www.mongodb.com/docs/manual/core/aggregation-pipeline/)
- [Aggregation Pipeline Optimization](https://www.mongodb.com/docs/manual/core/aggregation-pipeline-optimization/)
- [Aggregation Pipeline Limits](https://www.mongodb.com/docs/manual/core/aggregation-pipeline-limits/)
- [Change Streams](https://www.mongodb.com/docs/manual/changestreams/)
