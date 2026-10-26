## Introduction

时序数据库（Time Series Database, TSDB）是为**按时间索引的观测数据**优化的数据库。观测数据本身无处不在：一个采样点每隔几秒采一个 float、一个事件每次发生记一条结构化日志、一个 span 描述一次分布式调用——这些数据都自带时间戳，写入模式是 append-only 重、随机写少、批量范围查询多、过期清理硬要求。

时序数据库与通用关系数据库的根本差异来自"时间索引是一等公民"：

- **高基数（high cardinality）**：一条指标的 label/tag 组合会指数级膨胀序列数（`api_requests_total{method="GET", path="/users/{id}"}` 里的 `{id}` 如果是用户 ID，基数会爆炸）。TSDB 的存储与压缩必须按"标签 × 时间戳 × 采样值"的三维结构设计，而通用 B+Tree 只擅长一维有序。
- **写多读少、时间连续**：大量写入集中在最新时间窗口，读查询集中在最近几小时/几天的范围扫描。存储路径倾向 LSM Tree 或列式 append。
- **压缩优先级极高**：相邻时间戳的浮点值、整数通常很相近——Gorilla XOR（浮点）、delta-of-delta（整数/时间戳）、Simple-8b（整数压缩）这类算法能轻松把时序数据压到原始体积的 5% 甚至更低。
- **自动数据生命周期（TTL）**：超过保留策略的块直接 drop partition 或 delete chunk，而不是逐条删。
- **预聚合 / Continuous Aggregates**：仪表板和告警只需要固定窗口的聚合（每分钟/每小时 sum/avg/count），TSDB 通常提供查询时聚合之外的**写入侧预聚合**（recording rules、continuous aggregates、Flow），避免每次查询重算。
- **降采样（downsampling）**：长时间跨度趋势查询不需要 15 秒粒度的数据。TSDB 会自动从 raw data 生成粗粒度副本供长窗口查询。

## Data Model

时序数据的基本抽象是：

```
series_key  ──▶  (timestamp, value)  的有序流
```

其中 `series_key` 是该序列的唯一标识。不同产品对这个 key 和 value 的定义不同：

| 产品 | 序列 key | 一条采样的 value | 备注 |
| :-- | :-- | :-- | :-- |
| **Prometheus** | `metric_name{label_k="label_v", ...}` | 单个 float64 + 毫秒精度 timestamp | 最纯粹的单值模型 |
| **InfluxDB** | `measurement + (tag_k="tag_v", ...)` | 一组 field 列（不同类型）+ timestamp | 多值模型：一个点一行，多个 field 共享一个时间戳 |
| **GreptimeDB** | `PRIMARY KEY(tag_k, ...) + TIME INDEX(ts)` | 一组 Field 列 | 与 InfluxDB 类似但用关系表语法声明 |
| **VictoriaMetrics** | `metric_name{label_k="label_v", ...}` | 单个 float64 | 与 Prometheus 完全一致 |
| **TimescaleDB** | 关系表的主键 + time column | 任意 PostgreSQL 列类型 | 没有特殊 TSDB 语法，hypertable 是透明分区 |
| **TDengine** | `supertable + subtable_id + tag_k` | 一组 metric 列 | 一设备一表是核心设计 |

> 关键分歧在 **单值模型 vs 多值模型**：Prometheus/VictoriaMetrics 每个序列只存一个 float64；InfluxDB/GreptimeDB/TDengine 允许一条采样同时记录多个字段（CPU、内存、磁盘……），共享同一个时间戳。多值模型在存储上更省点开销、查询同一时间戳多指标时更快，但 schema 设计自由度不如单值。

## Storage Engine Routes

时序数据库的存储引擎主要有三条路线，各自权衡"从零设计 vs 复用现有 DB"：

### Route 1：独立 LSM 变体

专门从底层为时序设计的存储引擎，数据格式、压缩算法、查询剪枝全部围绕时间索引优化。

| 产品 | 引擎 | 核心设计 |
| :-- | :-- | :-- |
| [InfluxDB](/docs/CS/DB/InfluxDB.md) | 自研（Rust），底层用 Apache Arrow + Parquet + DataFusion | 3.x 把 TSDB 定位为实时缓冲 + Parquet 落盘；SQL 和 InfluxQL 双查询 |
| [GreptimeDB](/docs/CS/DB/GreptimeDB.md) | **Mito**（Rust），LSM + Parquet SST + TWCS compaction | Tag + Timestamp + Field 模型；Region 路由；时间范围 / row-group 统计 / 索引三层 scan pruning |
| [VictoriaMetrics](/docs/CS/DB/VictoriaMetrics.md) | 自研（Go），按月分区 LSM + 自研压缩格式 | 轻量、PromQL 兼容、无 WAL；vminsert/vmstorage/vmselect 三组件 |
| [TDengine](/docs/CS/DB/TDengine.md) | 自研（C），列式 LSM + 每列独立压缩 | Supertable/subtable 两级表模型；一设备一表 |

这条路线的共同语言是 [LSM Tree](/docs/CS/Algorithms/tree/LSM.md)，但每个产品在以下两点做出了不同选择：

- **分区粒度**：按时间（按月 / 按 2 小时块 / 按 chunk interval）还是按主键（Region / subtable）。
- **存储格式**：Apache Parquet（成熟、跨引擎可用）、自研列式格式（极致压缩）、宽列存储（Cassandra 风格）。

### Route 2：现有 DB 扩展

不去做一个新的数据库，而是**在一个成熟关系库上加一个扩展**，把时序特性以语法/存储/查询优化的形式注入。

| 产品 | 宿主 DB | 扩展方式 |
| :-- | :-- | :-- |
| [TimescaleDB](/docs/CS/DB/TimescaleDB.md) | **PostgreSQL** | C 语言扩展。`create_hypertable()` 把普通表自动按时间分 `chunk`（分区）；列式压缩把旧 chunk 转成列存；continuous aggregates 是增量刷新的物化视图 |

这条路的优势是**完整复用宿主生态**——所有 PostgreSQL 协议、类型、索引、SQL 都直接可用；代价是无法突破宿主 DB 的存储引擎基本假设（比如不能去掉 MVCC overhead、不能随意改 page format）。

### Route 3：通用列式 OLAP 引擎

不专门做时序，但列式布局 + 压缩 + 向量化执行天生擅长处理"大范围扫描 + 按时间范围过滤 + 聚合"。

| 产品 | 说明 |
| :-- | :-- |
| [ClickHouse](/docs/CS/DB/ClickHouse.md) | MergeTree 按时间排序主键 + 分区 + 数据跳过索引，被大量拿来做时序分析 |
| [Doris](/docs/CS/DB/Doris.md) | 同理 |

这条路的定位是"时序只是 OLAP 的一个负载"，**没有自动 TTL、没有连续聚合、没有原生 PromQL**——如果你的数据既要做时序分析又要做复杂 JOIN 和跨业务分析，这条路最顺。

## Query Language

时序数据的查询有两种典型路径：

| 查询类型 | 代表 | 使用者 |
| :-- | :-- | :-- |
| **Metrics-only 查询** | PromQL、MetricsQL、InfluxQL | 监控团队、告警规则、仪表板 |
| **任意结构化数据查询** | SQL | 运维、排障、长期分析 |

目前没有哪个 TSDB 只提供一种——主流产品都走向"SQL + metrics-specific DSL"双通道：

| 产品 | SQL | Metrics DSL | 备注 |
| :-- | :-- | :-- | :-- |
| Prometheus | ❌ | PromQL | 纯 metrics-only |
| VictoriaMetrics | ❌ | MetricsQL（PromQL 超集） | 无 SQL |
| InfluxDB | ✅（DataFusion 后端） | InfluxQL | 3.x 把 SQL 作为一等公民 |
| GreptimeDB | ✅（MySQL/PG wire） | PromQL | 最完整的双通道 |
| TimescaleDB | ✅（完整 PostgreSQL SQL） | ❌ | 只有 SQL |
| TDengine | ✅（类 MySQL SQL） | ❌ | 自定义 SQL 方言 |
| QuestDB | ✅（普通 SQL + SAMPLE BY + ASOF JOIN） | ❌ | SQL-first、极致低延迟、Parquet 冷层 |
| IoTDB | ✅（类 SQL，双模型语法不同） | ❌ | Apache 顶级、TsFile 自研、IoT 友好 |
| OpenTSDB | ❌（metric expression string） | 自定义 DSL | 2010 年开源、HBase 之上、legacy 产品 |

## 产品总览

按架构路线和定位聚类：

| 产品 | 架构路线 | 核心模型 | 查询 | 典型场景 | 笔记 |
| :-- | :-- | :-- | :-- | :-- | :-- |
| **Prometheus** | 内置 TSDB（Go） | metric + labels + timestamp | PromQL | 监控采集、短期存储 | [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md) |
| **VictoriaMetrics** | 独立 LSM 集群（Go） | metric + labels（Prom 兼容） | MetricsQL | Prometheus 生态长保留、集群化 | [VictoriaMetrics](/docs/CS/DB/VictoriaMetrics.md) |
| **InfluxDB** | 独立引擎（Rust，Arrow/Parquet/DataFusion） | measurement + tags + fields | SQL + InfluxQL | metrics/logs/traces 一体化 | [InfluxDB](/docs/CS/DB/InfluxDB.md) |
| **GreptimeDB** | 独立引擎（Rust，Mito LSM） | Tag + Timestamp + Field | SQL + PromQL | 可观测 metrics/logs/traces 统一 + 对象存储 + Flow | [GreptimeDB](/docs/CS/DB/GreptimeDB.md) |
| **TimescaleDB** | PostgreSQL C 扩展 | hypertable + chunk 分区 | PostgreSQL SQL | 需要关系能力 + 时序能力混合的 IoT / 金融 | [TimescaleDB](/docs/CS/DB/TimescaleDB.md) |
| **TDengine** | 独立引擎（C，列式 LSM） | supertable + subtable（一设备一表） | TDengine SQL | 国内 IoT、工业物联网、电力场景 | [TDengine](/docs/CS/DB/TDengine.md) |
| **QuestDB** | 独立引擎（Java+C+++Rust，WAL+本地列式+Parquet 冷层） | symbol + timestamp + 多列 | 普通 SQL + SAMPLE BY + ASOF JOIN | 交易地板、任务控制、极致低延迟 | [QuestDB](/docs/CS/DB/QuestDB.md) |
| **Apache IoTDB** | 独立引擎（Java，列式 LSM + Apache TsFile） | 双模型：tree（路径）+ table（TAG/FIELD） | 类 SQL | Apache 顶级、工业 IoT、百万设备 | [IoTDB](/docs/CS/DB/IoTDB.md) |
| **OpenTSDB（legacy）** | HBase 之上（Java，AsyncHBase 客户端） | metric + uid + timestamp + tag | metric expression string | 2010 年开源、理解时序库基础设计范式 | [OpenTSDB](/docs/CS/DB/OpenTSDB.md) |

选型决策点：

1. 你已经有 Prometheus 了吗？**有** → 先看 VictoriaMetrics（远程写入 + 集群化）或 Mimir / Thanos；**没有** → 直接选 GreptimeDB / InfluxDB 这种统一方案。
2. 数据量是不是大到需要独立存算？是 → 选 GreptimeDB（对象存储原生）或 InfluxDB 3.x；否 → 单机 VictoriaMetrics、QuestDB 或 TimescaleDB 都够。
3. 需要 SQL 做任意维度查询吗？需要 → GreptimeDB / InfluxDB 3.x / TimescaleDB / QuestDB；不需要 → Prometheus / VictoriaMetrics 最轻便。
4. 需要多信号（metrics + logs + traces）一体化吗？需要 → GreptimeDB 最直接；不需要（只存 metrics）→ VictoriaMetrics / Prometheus。
5. 需要与现有 PostgreSQL 共享生态（extensions、UDFs、BI 工具）吗？需要 → TimescaleDB。
6. 极致低延迟（交易地板、任务控制、微秒级摄入 + 毫秒级查询最新状态）是第一优先级吗？是 → **QuestDB**（zero-GC + 三层存储 + ASOF JOIN）。
7. 工业物联网 / 电力 / 百万设备层级树场景吗？是 → **IoTDB**（Apache TsFile + 双模型）或 **TDengine**（一设备一表，国内生态最强）。
8. 评估 legacy OpenTSDB 迁移路径吗？是 → 直接上 Prometheus（简单迁移）或 VictoriaMetrics（Prom 协议兼容）。

## Links

- [DataBases](/docs/CS/DB/DB.md)
- [LSM Tree](/docs/CS/Algorithms/tree/LSM.md)
- [WAL](/docs/CS/DB/WAL.md)
- [InfluxDB](/docs/CS/DB/InfluxDB.md)
- [GreptimeDB](/docs/CS/DB/GreptimeDB.md)
- [VictoriaMetrics](/docs/CS/DB/VictoriaMetrics.md)
- [TimescaleDB](/docs/CS/DB/TimescaleDB.md)
- [TDengine](/docs/CS/DB/TDengine.md)
- [QuestDB](/docs/CS/DB/QuestDB.md)
- [IoTDB](/docs/CS/DB/IoTDB.md)
- [OpenTSDB](/docs/CS/DB/OpenTSDB.md)
- [ClickHouse](/docs/CS/DB/ClickHouse.md)
- [Cassandra](/docs/CS/DB/Cassandra.md)
- [HBase](/docs/CS/DB/HBase.md)

## References

1. [Prometheus 官方文档](https://prometheus.io/docs/introduction/overview/)
2. [VictoriaMetrics Architecture](https://docs.victoriametrics.com/architecture/)
3. [TimescaleDB Architecture Whitepaper](https://assets.timescale.com/docs/downloads/Timescale_Architecture_for_Real-time_Analytics.pdf)
4. [InfluxDB 3.x Overview](https://www.influxdata.com/products/influxdb/)
5. [GreptimeDB Data Model](https://docs.greptime.com/user-guide/concepts/data-model/)
6. [TDengine Architecture](https://tdengine.com/tsdb-architecture-core-technology-explained/)
7. [QuestDB vs TimescaleDB Benchmark 2026](https://questdb.com/blog/timescaledb-vs-questdb-comparison/)
8. [Apache IoTDB Introduction](https://iotdb.apache.org/UserGuide/latest/IoTDB-Introduction/IoTDB-Introduction_apache.html)
9. [OpenTSDB Documentation](https://opentsdb.net/docs/)
10. [Gorilla: A Fast, Efficient, In-Memory Time Series Database](https://dl.acm.org/doi/10.1145/3092663) — Facebook 时序压缩算法
