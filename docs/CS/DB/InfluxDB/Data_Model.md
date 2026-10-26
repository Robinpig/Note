## Introduction

InfluxDB 的数据模型基于 **measurement + tags + fields + timestamp** 四元组，写入用 Influx Line Protocol（ILP）文本格式。3.x 延续了 1.x 的模型——这是 InfluxDB 少数没有推倒重来的部分，老数据能原样迁过来。本页讲四元素的角色分工、ILP 语法、3.x 引入的 column family 概念，以及 schema 演进上的硬限制。

## Data Model

```
measurement_name,tag_k1=tag_v1,tag_k2=tag_v2 field_k1=field_v1,field_k2=field_v2 timestamp_ns
```

| 元素 | 类型 | 语义 |
| :-- | :-- | :-- |
| **measurement** | string | 一类采集点的集合（`cpu`、`http_requests`），相当于表名 |
| **tag** | string → string | 维度，用于过滤与分组。**tag 集合 + timestamp 构成主键**——相同 measurement、相同 tag 组合、相同时间戳只允许一个值 |
| **field** | float / int / uint / string / bool | 采集值。**一次采样可以带多个 field**（CPU 同时记录 user / system / idle） |
| **timestamp** | ns 精度 | 采样时间，可省略（服务端接收时间补） |

行存的实例：

```
cpu,host=server01,region=us-east usage_user=12.5,usage_system=2.1 1713715200000000000
cpu,host=server02,region=us-west usage_user=8.3,usage_system=1.8  1713715200000000000
```

选 tag 还是 field 是建模的核心决策，3.x 的官方指引很直接：**只有行的唯一标识信息才放进 tag，其余一律用 field**。原因是 tag 决定主键，cardinality（基数）无限增长最终撑爆的是 tag 侧——3.x 把"无限基数"作为卖点，但前提是基数长在 field 上而不是 tag 组合上。

## Line Protocol Rules

ILP 的几条硬规则，写错会被入口 validation 直接拒绝：

- **转义**：measurement 名、tag key/value、field key 中的空格、逗号、等号用反斜杠转义；字符串 field 值用双引号包裹，内部双引号再转义。
- **类型后缀**：`i` 表示整数（`1i`），`u` 无符号整数，`t`/`T`/`TRUE`/`FALSE` 布尔，`"str"` 字符串，裸数字是 float。`usage=100` 与 `usage=100i` 落库类型不同。
- **重复 key 拒绝**：同一行重复 tag key 或 field key 都会在写入时报错（3.x 起 tag 侧与 field 侧一视同仁）。
- **时间戳上限**：超过 2262-04-11T23:39:59.999999999Z 的 ns 时间戳返回 400。
- **精度**：默认 ns；也支持 s / ms / us，在 API 层用 `precision` 参数指定，缺省按 ns 解释。

## Column Families

3.x 在 ILP 里用 `::` 双冒号分隔符把 field 显式分族：

```
cpu::usage_user=45.2,cpu::usage_system=12.1,mem::free=2048 1713715200000000000
```

`cpu::usage_user` 与 `mem::free` 落进两个不同 column family，物理上分块存放。查询只碰 `mem::free` 时只读 mem 块，其余块连读都不读——一张表几百个 field 时，这是"读一个切片"与"读整个文件"的区别。不写 `::` 的 field 进默认族。这个机制是 Enterprise 列式存储剪枝的关键输入，详见 [Storage_Engine](/docs/CS/DB/InfluxDB/Storage_Engine.md) 的 field family pruning。

## Schema Evolution

3.x 的 schema 演进规则与 1.x/2.x 不同，这是迁移时最容易踩的坑：

| 变更 | 是否支持 | 说明 |
| :-- | :-- | :-- |
| 新增 field | 支持 | 任意时刻直接写新 field 即可 |
| 新增 tag 列 | 不支持 | 建表后不允许，tag 集合是主键的一部分 |
| 修改 field 类型 | 不支持 | 需要换列 |
| 表数量 | 有限制 | Core 5 个 database / 2000 张表，Enterprise 100 / 4000（限制 snapshot 时对象存储文件数） |

结论：**建表时把 tag 集合一次设计对**。这正是官方"只把唯一标识信息放 tag"的另一半理由——可枚举、有界、不随时间新增的列才配做 tag。

## Cross-Product Model Mapping

| 产品 | 等价概念 | 关键差异 |
| :-- | :-- | :-- |
| GreptimeDB | `PRIMARY KEY(tag, ...)` + `TIME INDEX(ts)` + Field | 用关系表 DDL 声明，底层机制一致 |
| TDengine | supertable + tag 列 + metric 列 | 一设备一表的物理边界是关键差异 |
| Prometheus / VictoriaMetrics | metric_name + labels | 一个序列只存一个 float，没有 field 多值概念 |
| TimescaleDB | hypertable + JSONB/宽列 | 关系模型，没有 tag/field 分工 |

InfluxDB 模型在"多值序列"上最灵活：一个 measurement 一次采样可同时存多个 field 共享同一时间戳；Prometheus 模型更纯粹，但同一时间点的多指标要拆成多个序列表达。

## Links

- [InfluxDB 枢纽](/docs/CS/DB/InfluxDB/InfluxDB.md)
- [Architecture](/docs/CS/DB/InfluxDB/Architecture.md)
- [Storage_Engine](/docs/CS/DB/InfluxDB/Storage_Engine.md)
- [Timeseries](/docs/CS/DB/Concept/Timeseries.md)
- [GreptimeDB](/docs/CS/DB/Timeseries/GreptimeDB.md)

## References

1. [Influx Line Protocol Reference](https://docs.influxdata.com/influxdb3/core/reference/syntax/line-protocol/)
2. [InfluxDB 3 Core and Enterprise GA](https://www.influxdata.com/blog/influxdb-3-oss-ga)
3. [Architecture Overview of InfluxDB 3](https://www.influxdata.com/learn/architecture-overview-of-influxdb-3)
