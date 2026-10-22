## Introduction

TimescaleDB 是一个给 **PostgreSQL 加时序能力的 C 语言扩展**——它不从零造一个新数据库，而是把时序的存储、压缩、预聚合、生命周期管理以扩展（extension）的形式注入到 PostgreSQL 里。结果是：你写的所有 SQL 都是 PostgreSQL SQL，所有 PostgreSQL 的协议、类型、索引、扩展、BI 工具、JDBC 驱动、流复制高可用——全部直接可用，不加任何限制。

这种路线跟其他时序库有根本区别：其他时序库要么自己写存储引擎（InfluxDB、GreptimeDB、VictoriaMetrics、TDengine），要么是 PostgreSQL 兼容但独立实现（YugabyteDB、CockroachDB）。TimescaleDB 是**真正的 PostgreSQL + 真正的时序扩展**。

当前版本 TimescaleDB 2.x。开源版包含 hypertable/chunk、压缩、continuous aggregates、retention、多节点（parallel hypertable），企业版加入 HA 管理、备份、分片（multinode）等。

## Architecture

TimescaleDB 在 PostgreSQL 之上加了一层透明的时间分区 + 存储优化。用户看到的是一张普通的 `hypertable`（声明为主表），实际数据被拆成多个 `chunk`（子表），每个 chunk 是一张真正的 PostgreSQL 表、继承 hypertable 的 schema。

```
 hypertable (用户声明)
    │
    ├── chunk 1 (2026-10-01 ~ 2026-10-08)     ← 行存，正在写
    ├── chunk 2 (2026-10-08 ~ 2026-10-15)     ← 行存，正在写
    ├── chunk 3 (2026-09-24 ~ 2026-10-01)     ← 已列式压缩
    └── chunk N (2026-01-01 ~ 2026-01-08)     ← 已按 retention drop
```

用户对 hypertable 的所有 SQL 直接透传到各 chunk（加时间分区键过滤），TimescaleDB 在 PostgreSQL 的查询规划器层面做 **chunk exclusion**——时间范围查询时自动跳过不相关 chunk，效果等价于显式 `PARTITION BY RANGE` 分区但更灵活。

### Hypertable 与 Chunk

建表只需多调用一个 `create_hypertable()`：

```sql
CREATE TABLE sensor_readings (
    time          TIMESTAMPTZ NOT NULL,
    device_id     INTEGER NOT NULL,
    temperature   DOUBLE PRECISION,
    humidity      DOUBLE PRECISION,
    PRIMARY KEY (time, device_id)
);

SELECT create_hypertable('sensor_readings', 'time',
                         chunk_time_interval => INTERVAL '7 days');
```

执行后 TimescaleDB 做三件事：
1. 创建 `sensor_readings` 为主表（空表）。
2. 创建内部 schema `_timescaledb_internal`，里面存放所有元数据（chunk 定义、压缩状态、retention 策略等）。
3. 后台 worker 按 `chunk_time_interval`（默认 7 天）自动创建新 chunk、drop 过期 chunk。

chunk 内部是一张普通 PostgreSQL 表——有自己的 page、B-tree、MVCC、WAL。TimescaleDB 只是**透明地**做了时间分区和存储优化。

### Chunk Exclusion（时间范围剪枝）

PostgreSQL 的分区裁剪（partition pruning）机制在这里得到充分利用：hypertable 的分区键就是 `time`，所以查询 `WHERE time > NOW() - INTERVAL '1 day'` 时，PostgreSQL 规划器自动排除所有不在这个时间窗口内的 chunk。

TimescaleDB 的优化器还会进一步：
- 对 chunk 做 **constraint exclusion**：每个 chunk 的 CHECK 约束（`time >= '...' AND time < '...'`）明确边界，PostgreSQL 可以在规划阶段直接 drop 整个 chunk。
- 支持 **time_bucket** 函数：把任意时间戳落进固定窗口（`time_bucket('1 hour', time)`），这是 continuous aggregates 和常见时序查询的核心原语。

### Compression

PostgreSQL 的行存（heap）对时序数据很浪费——相邻时间戳的数值、整数在一个时间窗口内高度相似，而 row store 把一行的所有列交错存放。TimescaleDB 提供了**把旧 chunk 转成列式存储并压缩**的机制：

```sql
ALTER TABLE sensor_readings SET (
    timescaledb.compress,
    timescaledb.compress_segmentby = 'device_id'
);

SELECT add_compression_policy('sensor_readings',
                              compress_after => INTERVAL '3 days');
```

压缩后的 chunk：
- **列式布局**：同 column 的值连续存放，不再交错 row。
- **`segmentby` 列**：按 `device_id`（或你指定的任何维度）排序 chunk 内部数据，相同 device_id 的时间序列连续排列，利于压缩和过滤。
- **`orderby` 列**：默认是 time；让相邻时间戳聚合在一块，对 Gorilla XOR / delta-of-delta 效果最好。

压缩算法（每列独立）：

| 列类型 | 算法 |
| :-- | :-- |
| float / double | **Gorilla XOR** — 相邻值做 XOR，零值存 0，相等存 1 bit 标志 |
| timestamp / integer | **delta-of-delta** — 存差值的差值（二阶差分） |
| integer | **Simple-8b** — 8 bit 存 1 个整数，或更少 bit 存多个小整数 |
| string（低基数） | 字典编码 |
| 其它 | Run-Length Encoding |

生产报告显示 **90%+ 压缩率（原始体积的 1/10）** 是常态。

### Continuous Aggregates

TimescaleDB 的 continuous aggregate 是一种**增量刷新的物化视图**——只有时间桶（time bucket）里**有新写入或修改**的部分才重算：

```sql
CREATE MATERIALIZED VIEW sensor_1h
WITH (timescaledb.continuous) AS
SELECT
    device_id,
    time_bucket('1 hour', time) AS bucket,
    avg(temperature)           AS avg_temp,
    max(temperature)           AS max_temp,
    avg(humidity)               AS avg_humidity
FROM sensor_readings
GROUP BY device_id, bucket;

SELECT add_continuous_aggregate_policy('sensor_1h',
    start_offset => INTERVAL '1 week',
    end_offset   => INTERVAL '5 minutes',
    schedule_interval => INTERVAL '1 minute');
```

刷新机制：
- TimescaleDB 在内部追踪每个 chunk 的写入进度（`watermark`），只有 `[上次刷新 watermark, 当前 watermark]` 区间内的数据才参与重算。
- 刷新粒度是 `time_bucket` —— 如果桶内任何一个 chunk 有新数据，整个桶重算。
- **只有过去的 bucket 会刷新**——`end_offset` 控制"离 now 多近的 bucket 不刷新"（避免正在写入的桶抖动）。

continuous aggregate 让仪表板和告警读的是预先聚合好的数据，而不是每次扫描 raw data 再算一遍。

## High Availability

TimescaleDB 不自带分布式或 HA 功能——它**完全复用 PostgreSQL 的高可用**：

- **单主 + 同步复制**：PostgreSQL 流复制 + 同步副本，RPO = 0。
- **异步多副本**：RPO > 0，failover 可能丢最后一段。
- **云版 TimescaleDB**：Timescale Cloud 提供托管的 HA + 自动快照 + 多节点并行 hypertable。
- **Multinode（企业版）**：把 hypertable 的不同 chunk 分片到不同 PostgreSQL 节点上。

所以高可用策略就是 PostgreSQL 的高可用策略——TimescaleDB 不引入新组件。

## 与典型时序库的区别

| 维度 | TimescaleDB | InfluxDB 3.x | GreptimeDB | VictoriaMetrics |
| :-- | :-- | :-- | :-- | :-- |
| 存储引擎 | PostgreSQL + 扩展（行存 + 列式压缩） | Arrow + Parquet + DataFusion | Mito LSM + Parquet SST | 自研 LSM part |
| 数据库 | 扩展关系库 | 独立 TSDB | 独立 TSDB | 独立 TSDB |
| 查询 | **完整 PostgreSQL SQL** | SQL + InfluxQL | SQL + PromQL | MetricsQL |
| 写入协议 | PostgreSQL wire | Influx LP + OTLP + Prom RW | Prom RW + OTLP + MySQL/PG | Prom RW + Influx LP |
| 集群 | 靠 PG 复制 | 分布式版 | 原生存算分离 | vminsert + vmstorage + vmselect |
| 存算分离 | ❌ | ✅ | ✅ | ❌ |
| 多信号 | ❌（纯时序） | metrics + logs + traces | metrics + logs + traces | metrics only |
| SQL JOIN | ✅ 完整 | ✅ DataFusion | ✅ | ❌ |
| PostgreSQL 生态 | ✅ 全部 | ❌ | ❌ | ❌ |

TimescaleDB 最适合：**你需要时序能力，但也需要 PostgreSQL 的全部关系能力**——比如 IoT 场景里既要按时间聚合传感器读数、又要 JOIN 关系表（设备清单、固件版本、告警规则），或者金融场景里既要存市场 tick 又要做复杂交易分析。这是其他任何时序库都做不到的。

代价是：TimescaleDB 做不到 VictoriaMetrics 的无 WAL 极致吞吐，做不到 GreptimeDB 的原生对象存储存算分离，做不到 InfluxDB 3.x 的 metrics+logs+traces 一体化——它只做时序，而且深度绑定 PostgreSQL。

## Links

- [DataBases](/docs/CS/DB/DB.md)
- [Timeseries](/docs/CS/DB/Timeseries.md)
- [PostgreSQL](/docs/CS/DB/PostgreSQL/PostgreSQL.md)
- [InfluxDB](/docs/CS/DB/InfluxDB.md)
- [GreptimeDB](/docs/CS/DB/GreptimeDB.md)
- [VictoriaMetrics](/docs/CS/DB/VictoriaMetrics.md)
- [QuestDB](/docs/CS/DB/QuestDB.md)
- [IoTDB](/docs/CS/DB/IoTDB.md)
- [OpenTSDB](/docs/CS/DB/OpenTSDB.md)
- [WAL](/docs/CS/DB/WAL.md)
- [MVCC](/docs/CS/DB/PostgreSQL/MVCC.md)

## References

1. [TimescaleDB 官方文档](https://docs.timescale.com/)
2. [Timescale Architecture for Real-time Analytics](https://assets.timescale.com/docs/downloads/Timescale_Architecture_for_Real-time_Analytics.pdf)
3. [Hypertable 和 Chunk 内部机制](https://docs.timescale.com/timescaledb/latest/how-to-guides/hypertables/create-hypertables/)
4. [Compression 工作原理](https://docs.timescale.com/timescaledb/latest/overview/core-concepts/compression/)
5. [Continuous Aggregates](https://docs.timescale.com/timescaledb/latest/how-to-guides/continuous-aggregates/)
