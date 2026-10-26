## Introduction

TDengine 的数据模型可以一句话概括：**用一张超级表声明同类采集点的共享 schema，每个具体采集点落成一张子表，静态属性做标签（tag）、动态读数做度量列（metric）、每行必带主时间戳**。这套"一设备一表"是 TDengine 所有存储与查询优化的地基——列式压缩以子表数据块为单位、聚合查询以子表集合为扇出单位、compaction 边界也长在子表边界上。

本页讲三类列的角色分工、建模的正确姿势、自动建表、标签基数陷阱、schema 演进限制和 3.4 引入的虚拟表（vtable）。

## Three Roles of a Column

| 角色 | 关键字 | 语义 | 物理存储 |
| :-- | :-- | :--- | :--- |
| **timestamp** | 第一列，`TIMESTAMP` 类型 | 主时间戳，行的排序键 | 与 metric 同处 TSDB，差分压缩 |
| **metric** | 普通列 | 动态采集值，每次采样都变 | TSDB 列式存储，按列压缩 |
| **tag** | `TAGS (...)` 子句 | 静态属性，采集时确定、不变 | tag 列与 metric 物理分离存储，独立索引 |

```sql
-- 1. 超级表：1000 块电表的共享 schema + 标签模板
CREATE STABLE meters (
    ts        TIMESTAMP,
    current   FLOAT,      -- metric
    voltage   FLOAT        -- metric
) TAGS (
    groupid   INT,        -- tag：安装时确定
    location  BINARY(64)  -- tag
);

-- 2. 每个电表一张子表，自动继承 schema
CREATE TABLE meters_001 USING meters TAGS (groupid=1, location='北京');
CREATE TABLE meters_002 USING meters TAGS (groupid=1, location='上海');
```

对比其它时序库的模型分野（详见 [Timeseries](/docs/CS/DB/Timeseries.md)）：InfluxDB 用一个 measurement 存全部设备、靠 tag 组合区分序列；TDengine 是**真的多张物理表**，标签不同就是不同子表；GreptimeDB 则反过来把标签做成关系表的 PRIMARY KEY。

## Why One Table per Device

这套设计换来四样东西，代价也不是没有：

**收益**：

- **零写入协调**：每个子表独立追加写，没有全局序列分配器，写入路径极短。
- **天然负载隔离**：热设备的写压不会拖累冷设备。
- **聚合查询免费并发**：查超级表时 TDengine 自动向所有子表扇出、各自本地预聚合再全局合并，应用层不需要 `UNION ALL`。
- **tag 分离存储**：聚合查询先在内存里过滤 tag 确定参与的子表集合，再只扫 metric 列——扫描体积远小于宽列模型。tag 数据与时序数据分开存储是官方明确的查询优化前提。

**代价**：

- **子表数量可以到百万级**，元数据（TDB B+Tree）压力、`SHOW` 类操作和 taosc 元数据缓存都要按这个规模设计。
- **跨设备 JOIN 贵**：设备间关联查询要走 JOIN（3.3.0.0 起才完整），不如关系库自然。
- **schema 变更影响整张超级表**：加列对所有子表生效，没有 InfluxDB field 那种"写到就有"的宽松度。

## Modeling Practice

**tag 的选择是建模的核心决策**。tag 值确定一条序列的静态身份，参与过滤与分组：

- 适合做 tag：设备型号、安装区域、所属线路、设备分组——取值有限、查询时按它过滤。
- 不适合做 tag：每次采样都变的值（那是 metric）；取值几乎唯一的值（如设备序列号如果每设备一张子表，放子表名即可，不必再进 tag）；基数会随时间膨胀的维度（用户 ID、请求 ID）。
- tag cardinality（基数）直接决定子表数量上限和元数据开销，这是 TDengine 版的高基数陷阱。

**命名与组织**：数据库 → 超级表 → 子表三级；子表命名建议带业务前缀便于按名前缀批量管理（`SELECT` 支持子表名通配风格的批量操作）。同一超级表下子表数量巨大时，写频率低的场景要关注 stt 文件策略（见 [Storage_Engine](/docs/CS/DB/TDengine/Storage_Engine.md)）。

**自动建表**：写入侧可以按标签组合自动建子表——`INSERT INTO meters USING meters TAGS (...) VALUES (...)` 带 `USING` 子句即可，子表不存在时自动创建。这是 schemaless 线路（Line Protocol / CSV）背后的同一个机制，采集端不需要先建表。

## Schema Evolution

TDengine 的 schema 演进能力比关系库弱、比 InfluxDB 强：

- **加列**：`ALTER TABLE` / `ALTER STABLE` 给超级表加 metric 列，对所有子表生效；已写入数据的列值按类型补默认值。
- **删列**：受支持但有限制，删超级表列影响全部子表。
- **改类型/改 tag**：基本要走建新表迁移。
- **列数上限**：schema 定义可以到数千列，但实际每行有值的列很少时（稀疏场景），存储格式会退化到 Key-Value 编码（见 [Storage_Engine](/docs/CS/DB/TDengine/Storage_Engine.md)），访问速度换空间。

## Virtual Tables

3.4 引入的**虚拟表（vtable）**是在物理超级表/子表之上的一层逻辑视图，支持把多张表、计算结果、外部数据统一成一张表查询，查询优化器对虚拟表的投影、聚合、选择函数和窗口查询做了专门优化。它解决的是"报表维度 ≠ 存储维度"的问题——按区域汇总、跨表对齐这类需求不必再靠应用层拼 SQL。虚拟表查询的内部优化（聚合下推与窗口两阶段拆分）在官方技术内幕有专页。

## Links

- [TDengine](/docs/CS/DB/TDengine.md)
- [Storage_Engine](/docs/CS/DB/TDengine/Storage_Engine.md)
- [SQL](/docs/CS/DB/TDengine/SQL.md)
- [Timeseries](/docs/CS/DB/Timeseries.md)
- [InfluxDB](/docs/CS/DB/InfluxDB.md)
- [GreptimeDB](/docs/CS/DB/GreptimeDB.md)

## References

1. [超级表数据建模](https://docs.taosdata.com/tdengine-sql/ddl/stable/)
2. [技术内幕：虚拟表查询](https://docs.tdengine.com/internals/vtable-query/)
3. [技术内幕：整体架构（vnode 与表分布）](https://docs.taosdata.com/internals/arch/)
