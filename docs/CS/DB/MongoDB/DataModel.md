## Introduction

MongoDB 把一行数据存成一篇 **BSON 文档**：字段可以嵌套对象与数组，同一 collection 内的文档不要求结构一致。灵活性不是免费的——**建模决策直接决定查询能否走索引、单文档原子性够不够、文档会不会撞上 16MB 上限**。数据模型是 MongoDB 里最容易"前期很爽、后期还债"的部分。

## BSON Type System

BSON 是 JSON 的二进制扩展，保留 JSON 的对象/数组结构，同时补齐数值宽度、日期、二进制与 ObjectId。

| 类型 | 别名 | 说明 |
| :--- | :--- | :--- |
| Double | `double` | 默认浮点，所有数字字面量默认按 double 解析 |
| String | `string` | UTF-8 |
| Object / Array | `object` / `array` | 嵌套文档与数组 |
| Binary | `binData` | 带 subtype |
| ObjectId | `objectId` | 12 字节主键 |
| Boolean / Null | `bool` / `null` | |
| Date | `date` | 有符号 64 位毫秒时间戳 |
| 32 位整数 | `int` | |
| 64 位整数 | `long` | |
| Decimal128 | `decimal` | 十进制浮点，金额场景避免 double 误差 |
| Timestamp | `timestamp` | 内部用于 oplog，不是业务时间 |
| MinKey / MaxKey | | 分片与索引边界哨兵 |

几个容易踩的点：

- **数字类型有区分**：`NumberInt(1)`、`NumberLong(1)`、`1.0` 是三种类型，查询时默认按类型括号匹配（`1` 不匹配 `1.0`）。需要跨类型比较时用 `$type` 或显式转换。
- **文档等值比较对字段顺序敏感**：`{ a: 1, b: 2 }` 与 `{ b: 2, a: 1 }` 不相等。嵌入文档做整体匹配时要保持写入顺序稳定。
- **Date 没有时区**：统一存 UTC，展示时由应用转换。
- **BSON 文档上限 16 MiB**，嵌套最多 100 层。超过 16MB 的大对象用 GridFS 分块，而不是硬塞。

## _id and ObjectId

每个文档必须有 `_id`，在 collection 内唯一，默认由客户端生成 ObjectId。`_id` 可以是除数组、正则、`undefined` 之外的任意 BSON 类型；业务上常用订单号、租户+时间拼接值作为 `_id`，天然获得唯一索引与按主键路由。

ObjectId 的 12 字节构成：

```text
4 字节  Unix 时间戳（秒）
5 字节  每进程启动时的随机值
3 字节  进程内自增计数器（随机初值）
```

时间戳在高位，因此 ObjectId 大致按创建时间递增——这既让 `_id` 索引有局部性，也意味着**它不能当分布式严格单调序号用**（不同机器时钟不一致）。

## Embedding vs Referencing

这是文档建模的核心决策。

| 维度 | 嵌入（Embedded） | 引用（Reference） |
| :--- | :--- | :--- |
| 关系 | 一对少、从属、总是一起读 | 多对多、被多处共享、数量无界 |
| 读取 | 一次 IO 取全 | 应用二次查询或 `$lookup` |
| 写入 | 单文档原子更新 | 跨文档，需要事务或补偿 |
| 风险 | 文档膨胀、16MB 上限、数组无界增长 | 关联查询成本、一致性窗口 |

决策顺序建议：

1. 先列**访问模式**（哪些字段总一起读、写频率、增长上限），而不是先画 ER 图；
2. 能用一个文档表达且数组有明确上限 → 嵌入；
3. 子对象数量无界（评论、日志、传感器点）→ 引用或分桶；
4. 需要跨实体强一致 → 优先调整边界把一致性收敛到单文档，再考虑多文档事务。

## Schema Design Patterns

官方总结的一组可复用模式，解决的是"文档模型表达关系"的具体问题：

| 模式 | 用途 |
| :--- | :--- |
| Attribute Pattern | 字段名不固定的键值对，转成 `[{k, v}]` 数组便于统一索引 |
| Subset Pattern | 把热字段放主文档，冷字段拆到另一集合，控制工作集 |
| Computed Pattern | 预计算聚合值（计数、汇总），读多写少时省掉实时计算 |
| Bucket Pattern | 按时间窗口/数量分桶（如每小时一篇），避免无界数组 |
| Outlier Pattern | 绝大多数文档走常规结构，少数超大文档单独标记 |
| Extended Reference | 引用时冗余少量高频字段，避免每次 `$lookup` |
| Polymorphic Pattern | 同类但结构不同的实体放同一集合，用类型字段区分 |
| Tree Pattern | 层级数据：父引用、祖先数组、物化路径、嵌套集 |
| Approximation | 统计类数据允许近似（如 HyperLogLog），换性能 |

分桶模式与时间序列集合的关系值得注意：MongoDB 5.0 的 [Time Series](/docs/CS/DB/MongoDB/TimeSeries.md) 集合在引擎内部已经做了列式分桶，业务侧不必再手写 bucket 文档。

## Schema Validation

MongoDB 默认不校验结构。需要约束时用 `$jsonSchema`：

```javascript
db.createCollection("users", {
  validator: {
    $jsonSchema: {
      bsonType: "object",
      required: ["email", "createdAt"],
      properties: {
        email: { bsonType: "string", pattern: "^.+@.+$" },
        age: { bsonType: "int", minimum: 0 }
      }
    }
  },
  validationLevel: "strict",   // off | strict | moderate
  validationAction: "error"    // error | warn
})
```

校验只作用于插入与更新，不校验历史数据；`moderate` 允许已有不合规文档继续被更新。它是"边界护栏"，不能替代应用层校验。

## Anti-Patterns

- **无界数组**：把评论、日志直接 `$push` 进主文档，最终撞 16MB 且每次更新重写整篇。
- **超大文档**：字段多到只查一个也要搬整篇；应拆子集或用投影配合覆盖索引。
- **大小写不敏感查询用 `$regex`**：无法走普通索引；建 `collation` 索引或存归一化字段。
- **每个字段一个索引**：写入放大、内存浪费；按查询形状建复合索引。
- **用应用层 join 拼热点数据**：网络往返与一致性窗口都放大；必要时用扩展引用冗余。
- **把 BSON 当 blob 存**：大文件走 GridFS，图片/视频走对象存储。

## Links

- [MongoDB](/docs/CS/DB/MongoDB.md)
- [Query](/docs/CS/DB/MongoDB/Query.md)
- [Index](/docs/CS/DB/MongoDB/Index.md)
- [Time Series](/docs/CS/DB/MongoDB/TimeSeries.md)
- [Sharding](/docs/CS/DB/MongoDB/Sharding.md)

## References

- [MongoDB BSON Types](https://www.mongodb.com/docs/manual/reference/bson-types/)
- [Data Modeling Introduction](https://www.mongodb.com/docs/manual/core/data-modeling-introduction/)
- [Building with Patterns](https://www.mongodb.com/blog/post/building-with-patterns-a-summary)
- [Schema Validation](https://www.mongodb.com/docs/manual/core/schema-validation/)
