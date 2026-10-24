## Introduction

时间序列集合（Time Series Collections）是 MongoDB 5.0 引入的原生能力，面向"按时间追加、按时间范围查询、很少更新"的数据：指标、传感器读数、行情、埋点。它不是简单地"按时间建个索引"，而是在存储层把同一来源、相邻时间的数据压进 **bucket 文档**，用列式布局降低索引与 IO 开销。

## Data Model

一条 measurement 文档由三部分组成：

```javascript
db.createCollection("weather", {
  timeseries: {
    timeField: "ts",            // 必需，必须是 Date
    metaField: "sensor",        // 可选，序列标识，创建后不可改
    granularity: "minutes"      // seconds | minutes | hours
  },
  expireAfterSeconds: 86400 * 30
})

db.weather.insertOne({
  ts: new Date("2026-10-23T08:00:00Z"),
  sensor: { id: "A1234", city: "BJ" },
  temperature: 21.5,
  humidity: 44
})
```

- **timeField**：时间戳，决定桶的时间范围与 TTL。
- **metaField**：序列元数据（设备 ID、区域），同一 meta 值的数据尽量落在同一桶；创建后不能新增 meta 字段。
- **度量字段**：其余字段被视为 value，允许不同文档字段不一致。

## Bucket Storage

时间序列集合在内部有一个 `system.buckets.<name>` 集合，桶文档大致长这样：

```javascript
{
  _id: { sensorId: "A1234", ts: ISODate("2026-10-23T08:00:00Z") },
  control: { min: {...}, max: {...}, count: 120 },
  data: { ts: [...], temperature: [...], humidity: [...] }
}
```

同一桶内按列存值，查询时按需解压列；这也是它比普通集合省空间、扫描快的原因。桶的时间跨度由 `granularity` 决定，6.3 起可用 `bucketMaxSpanSeconds` / `bucketRoundingSeconds` 精确控制（与 `granularity` 互斥）。

9.0 改变了存储形态：时间序列集合被实现为**单一命名空间内的桶存储**，不再表现为"可写的非物化视图"；`renameCollection` 也首次支持时间序列集合。

## Indexes

- 6.3 起，新建时间序列集合会自动创建 `{ metaField: 1, timeField: 1 }` 复合索引；
- 可以额外建普通二级索引（按度量字段过滤）；
- 常用模式是按 `metaField` 分片（zone sharding 把不同设备/地域的数据定向到 shard）；
- `distinct` 在时间序列上效率很低，去重统计改用 `$group`。

## Query

时间序列集合用普通 `find` / `aggregate` 查询，字段路径与普通集合一致：

```javascript
db.weather.aggregate([
  { $match: {
      "sensor.city": "BJ",
      ts: { $gte: ISODate("2026-10-23T00:00:00Z"), $lt: ISODate("2026-10-24T00:00:00Z") }
  } },
  { $group: { _id: { $dateTrunc: { date: "$ts", unit: "hour" } }, avgTemp: { $avg: "$temperature" } } },
  { $sort: { "_id": 1 } }
])
```

8.0 引入了**块处理（block processing）**：对时间序列的某些聚合按"块"而非逐值处理，官方称 `$group` 与分析型查询吞吐在部分场景提升超过 200%。窗口计算用 `$setWindowFields`（5.0 引入）。

## Retention

TTL 用 `expireAfterSeconds` 声明在 `timeField` 上，后台过期线程按桶粒度删除，而不是逐文档删除——这是时间序列集合适合"保留 N 天"场景的关键。

```javascript
db.runCommand({ collMod: "weather", expireAfterSeconds: 3600 * 24 * 90 })
```

TTL 线程约每 60 秒跑一轮，删除有延迟；对合规要求"到点必须删"的场景，不能只依赖 TTL。

## When to Use

**适合**

- 只追加、按时间范围读、按序列聚合；
- 数据量大且字段相对固定（指标名稳定）；
- 需要按时间自动过期。

**不适合**

- 频繁更新/删除单条记录（时间序列的更新能力受限，且会破坏桶压缩）；
- 需要大量二级索引或跨序列的即席 join；
- 需要强一致报表与复杂事务（更适合关系库或 OLAP 引擎）。

**已知限制**（见官方限制页）：不支持 Change Streams、Schema Validation、客户端字段级加密（CSFLE）；`$merge` 不能把其它集合的数据写入时间序列集合（反向可以），写入用 `$out`；`distinct` 效率低。

与专用时序库的对比见 [Comparison](/docs/CS/DB/MongoDB/Comparison.md)：InfluxDB/TimescaleDB 在压缩率与降采样上更专，MongoDB 的优势是"时序数据与业务文档同库、同查询语言、同事务边界"。

## Links

- [MongoDB](/docs/CS/DB/MongoDB.md)
- [Data Model](/docs/CS/DB/MongoDB/DataModel.md)
- [Aggregation](/docs/CS/DB/MongoDB/Aggregation.md)
- [Sharding](/docs/CS/DB/MongoDB/Sharding.md)
- [Timeseries](/docs/CS/DB/Timeseries.md)

## References

- [Time Series Collections](https://www.mongodb.com/docs/manual/core/timeseries-collections/)
- [Time Series Collection Limitations](https://www.mongodb.com/docs/manual/core/timeseries/timeseries-limitations/)
- [Time Series Indexes](https://www.mongodb.com/docs/manual/core/timeseries/timeseries-secondary-index/)
- [MongoDB 9.0 Release Notes](https://www.mongodb.com/docs/manual/release-notes/9.0/)
