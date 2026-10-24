## Introduction

MQL（MongoDB Query Language）是面向文档的查询语言：`find` 负责点查与过滤，聚合管道负责变换与统计。它看起来像 JavaScript 对象字面量，但语义上有不少与 SQL 不同的地方——数组匹配、null 与缺失字段、类型括号、排序方向，这些细节决定查询是走索引还是全表扫描。

## CRUD

```javascript
// 插入
db.users.insertOne({ _id: 1, name: "Ada", tags: ["math", "cs"], age: 36 });

// 查询 + 投影（1 包含，0 排除，_id 默认包含）
db.users.find(
  { age: { $gte: 18 }, tags: "cs" },
  { name: 1, age: 1, _id: 0 }
).sort({ age: -1 }).limit(20);

// 更新：只改指定字段
db.users.updateOne(
  { _id: 1 },
  { $inc: { age: 1 }, $addToSet: { tags: "ai" } }
);

// upsert：不存在则按过滤条件 + 更新操作插入
db.carts.updateOne(
  { uid: 7 },
  { $setOnInsert: { createdAt: new Date() }, $addToSet: { items: "sku_1" } },
  { upsert: true }
);

// 原子读改写
db.counters.findOneAndUpdate(
  { _id: "order" },
  { $inc: { seq: 1 } },
  { returnDocument: "after", upsert: true }
);
```

## Operators

| 类别 | 常用操作符 |
| :--- | :--- |
| 比较 | `$eq` `$ne` `$gt` `$gte` `$lt` `$lte` `$in` `$nin` |
| 逻辑 | `$and` `$or` `$nor` `$not` |
| 元素 | `$exists` `$type` |
| 求值 | `$expr` `$regex` `$mod` `$text` `$where` |
| 数组 | `$all` `$elemMatch` `$size` |
| 更新 | `$set` `$unset` `$inc` `$mul` `$min` `$max` `$rename` `$currentDate` `$push` `$addToSet` `$pop` `$pull` `$pullAll` |
| 数组更新 | `$`（首个匹配）、`$[]`（全部）、`$[<ident>]` + `arrayFilters` |

`$where` 与 `$function`/`$accumulator` 在 8.0 被标记废弃，9.0 换用 WASM 沙箱后重新启用；生产环境仍应优先用原生操作符，服务端 JS 无法走索引且难以审计。

## Semantics Traps

- **数组字段的隐式展开**：`{ tags: "cs" }` 命中 `tags` 数组中任意一个元素；要同时约束同一个元素的多条件，必须用 `$elemMatch`。
- **null 匹配缺失字段**：`{ a: null }` 同时匹配 `a` 不存在与 `a` 为 null 的文档；只要存在性用 `$exists`。
- **类型括号**：`{ age: 36 }` 只匹配 int32/long/double 中数值相等的值，但 `{ age: "36" }` 不匹配数字；数组与标量的匹配规则也不对称。
- **点号路径**：`"address.city"` 可进入嵌套文档与数组内部；路径中的数字索引不保证稳定。
- **正则**：非锚定 `$regex` 无法有效利用索引；前缀锚定 `^abc` 可以，大小写不敏感仍需 collation 索引。

## Cursor and Pagination

`find()` 返回游标，服务端按批返回：首批最多 101 个文档或 16MB（取先到者），之后由 `getMore` 拉取。游标默认空闲 10 分钟超时（`cursorTimeoutMillis`）。

分页要避免深度 `skip`：

```javascript
// 差：越往后越慢，skip 仍要扫描并丢弃
db.events.find().sort({ _id: 1 }).skip(100000).limit(20);

// 好：基于上一页最后一个键做范围查询
db.events.find({ _id: { $gt: lastId } }).sort({ _id: 1 }).limit(20);
```

排序在内存中默认受 32MB 限制，超限报错；要么建支撑排序的索引，要么显式允许落盘（聚合用 `allowDiskUse`）。

## Query Planner and Execution

查询进入服务端后：

1. **规范化查询形状**（query shape）并查 plan cache；
2. 未命中时进入 multi-planner，各候选计划试跑一小段，胜出者缓存；
3. 7.0 起优先交给 **SBE** 执行，不支持的形状回退 classic 引擎；
4. 执行阶段从 WiredTiger 取文档，必要时回表（FETCH）。

索引是否被用上，看 `explain("executionStats")`：

```javascript
db.users.find({ city: "BJ", age: { $gte: 18 } }).explain("executionStats")
```

关键字段：

| 字段 | 关注点 |
| :--- | :--- |
| `winningPlan.stage` | `IXSCAN` 正常；`COLLSCAN` 全表扫描；`SORT` 内存排序 |
| `keysExamined` | 扫描的索引键数 |
| `docsExamined` | 回表的文档数，越接近 `nReturned` 越好 |
| `nReturned` | 实际返回数 |
| `totalKeysExamined / totalDocsExamined` | 多计划试跑后的总量 |

**覆盖查询**（covered query）指查询与投影涉及的字段全在索引里，不需要回表，`docsExamined` 为 0。复合索引的设计规则见 [Index](/docs/CS/DB/MongoDB/Index.md)。

8.0 引入按查询形状的 **query settings**（`setQuerySettings`），可以对某类查询固定索引、设置 `maxTimeMS`；9.0 进一步支持在单次命令里传 `querySettings` 与 `queryKnobs`，并让 `$queryStats` 默认按 1% 采样统计读写查询。

## Read Path Options

查询的可见性与路由由两套选项控制，细节在 [Replication](/docs/CS/DB/MongoDB/Replication.md)：

- **read preference**：`primary` / `primaryPreferred` / `secondary` / `secondaryPreferred` / `nearest`，决定读发给谁；
- **read concern**：`local` / `available` / `majority` / `linearizable` / `snapshot`，决定读到多"新"的数据。

两者正交：从 secondary 读 + `local` 可能读到会被回滚的数据；要"读到自己刚写"需因果一致会话。

## Links

- [MongoDB](/docs/CS/DB/MongoDB.md)
- [Aggregation](/docs/CS/DB/MongoDB/Aggregation.md)
- [Index](/docs/CS/DB/MongoDB/Index.md)
- [Data Model](/docs/CS/DB/MongoDB/DataModel.md)
- [Transaction](/docs/CS/DB/MongoDB/Transaction.md)

## References

- [MongoDB Query Documents](https://www.mongodb.com/docs/manual/tutorial/query-documents/)
- [Query Optimization](https://www.mongodb.com/docs/manual/core/query-optimization/)
- [Explain Results](https://www.mongodb.com/docs/manual/reference/explain-results/)
- [Query Settings](https://www.mongodb.com/docs/manual/reference/command/setQuerySettings/)
