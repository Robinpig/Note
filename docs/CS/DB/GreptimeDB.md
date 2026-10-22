## Introduction

GreptimeDB 是开源可观测数据库，把 metrics、logs、traces 三种信号放进同一个列式引擎与共享 SQL 层。它既可以单机运行在本地存储上，也可以分布式部署、持久化到对象存储（S3、GCS、Azure Blob、OSS），把计算与存储按相互独立的规模伸缩。GreptimeDB 不是通用事务数据库——它的存储、索引、TTL、查询路径从一开始就是为 append-heavy、time-indexed 的负载（可观测性、IoT、时序分析）设计的。

当前稳定版本是 **1.2**（2026 年 10 月）。

> [!NOTE]
> GreptimeDB 的「统一」发生在引擎、存储、查询层，**不是**强迫 metrics、logs、traces 共享同一张表、同一个 schema。每种信号仍然可以用独立的表——各自拥有不同的主键、索引、TTL、compaction 策略和存储位置。

## Architecture

GreptimeDB 采用 client/server 模型。单机模式下一个进程承担全部数据库职责；分布式模式拆成四个组件：

| 组件 | 职责 |
| :-- | :-- |
| **Metasrv** | 管理 catalog、schema、table、Region 路由、procedure 与调度元数据。单机模式用本地元数据代替。 |
| **Frontend** | 接受客户端协议请求、鉴权、规划分布式查询，基于 Metasrv 的元数据把读写路由到对应 Datanode。 |
| **Datanode** | 托管 Region、执行读写、记录 WAL、跑 compaction，把数据文件持久化到本地或对象存储。 |
| **Flownode**（可选） | 运行 Flow 计算任务——连续聚合并物化到 sink 表。 |

### Write Path

1. 客户端通过受支持的摄入协议发送数据（Prometheus remote write、OTLP、Loki、ES Bulk、MySQL/PG SQL、HTTP/gRPC）。
2. Frontend 从 Metasrv 解析目标表与 Region 路由。
3. Frontend 把请求拆片，逐行转发到持有目标 Region 的 Datanode。
4. Datanode 写入内存 memtable 与 WAL，后续 flush 把不可变 SST 文件落到配置的存储后端。

### Query Path

1. 客户端提交 SQL、PromQL 或 Jaeger 兼容 API 查询。
2. Frontend 规划查询并分发到持有相关 Region 的 Datanode。
3. Datanode 读内存数据与持久文件，本地缓存命中则走缓存，同时应用时间范围剪枝、row-group 统计剪枝与索引过滤，返回局部结果。
4. Frontend 汇总结果并返回客户端。

### Flow Path（可选）

Flow 把 source 表上的流式计算结果物化到 sink 表。根据模式不同，Frontend 要么把写入 mirror 到 Flownode（streaming），要么 Flownode 自己回查 source 表（batching）。sink 表拥有独立的 schema、TTL、索引和存储位置——Flow 只负责计算，不改变任何表的存储策略。

## Data Model

GreptimeDB 用带时间索引的关系表做统一可观测数据模型。表中每列的角色分为三类：

| 角色 | 声明方式 | 语义 |
| :-- | :-- | :-- |
| **Tag** | `PRIMARY KEY (...)` | 参与主键、把相关行分组。对 metrics 来说就是 label；允许为 NULL；可选（append-only 日志表可以没有主键列）。 |
| **Timestamp** | `TIME INDEX (col)` | 每张表必须且只能有一个时间索引。记录事件或采样时间，帮助按时间组织数据、支持高效时间范围查询。非空。 |
| **Field** | 剩余列 | 存测量值、日志内容、trace 属性或其他值。支持 numeric、string、JSON、timestamp 等类型，允许 NULL。 |

数据在持久化时按 `(primary key, timestamp)` 排序——同一组 tag 上的多个时间戳连续存放，利于局部性与压缩。append-only 表禁用去重与删除标记，没有主键时按 timestamp 排序。

```sql
-- Metrics 表：host 资源指标
CREATE TABLE system_metrics (
    host     STRING,
    idc      STRING,
    cpu_util   DOUBLE,
    memory_util DOUBLE,
    disk_util  DOUBLE,
    ts          TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY(host, idc),
    TIME INDEX(ts)
);

-- Logs 表：append-only、无主键
CREATE TABLE access_logs (
    access_time TIMESTAMP TIME INDEX,
    remote_addr STRING,
    http_status STRING,
    http_method STRING,
    request     STRING
) WITH ('append_mode' = 'true');
```

### Merge Modes

有主键的表可以配置 merge mode，决定同一 `(primary key, timestamp)` 上多行怎么合并：

- `last_row`（默认）—— 保留最新一行（按写入顺序）。
- `last_value` —— 对每个 field 独立保留最新值。
- 其他模式（`overwrite`, `ignore` 等）用于特定场景。

append-only 表不适用 merge mode——写入就是追加，不做去重。

## Mito Storage Engine

Mito 是 GreptimeDB 默认的存储引擎，一个**面向时序负载的 [LSM Tree](/docs/CS/Algorithms/tree/LSM.md)** 变体，不是通用嵌入式存储库。它与 Cassandra 风格的宽列存储类似，但在数据模型、SST 格式和 compaction 策略上有时序化设计。

### Engine Architecture

```
  WAL          Memtables          SST Files (Parquet)     Manifest
  ┌─┐         ┌────────────┐      ┌────┐ ┌────┐        ┌───────┐
  │ │──flush──▶ │ mutable  │─────▶│ SST│ │ SST│ ───────▶│ meta  │
  │ │           │  frozen  │      └────┘ └────┘        └───────┘
  └─┘           └────────────┘
                   ▲                  ▲
                   └─ compactor ──────┘
                     合并小 SST
```

组件说明：

- **WAL** —— 保证尚未 flush 的数据耐久性。基于 `Log Store` API 实现，底层可以是本地磁盘、也可以是远程 Kafka（remote WAL）。还支持 Noop WAL（不保留、耐久性最弱）。通用机制见 [WAL](/docs/CS/DB/WAL.md)。
- **Memtables** —— 按时间索引路由到 mutable memtable；flush 时冻结旧 memtable、安装新的 mutable 集，把冻结集写成 SST。
- **SST** —— 不可变 memtable flush 后落到持久存储，每行按 `(primary key, timestamp)` 排序。
- **Compactor** —— 用 [TWCS](https://cassandra.apache.org/doc/latest/cassandra/operating/compaction/twcs.html) 策略（Time-Windowed Compaction Strategy），按时间窗口分组 SST、配合 TTL 清理过期数据。
- **Manifest** —— 记录 SST 元数据：文件级时间范围、行数、row-group 数、可用索引、主键范围。

### Region

数据以 **Region** 为逻辑隔离单元——一个 Region 内所有行共享同一个 schema。一张表的数据分布在一个或多个 Region 上；Metasrv 维护表到 Region 的路由。

### SST Data Layout

SST 文件底层使用 **Apache Parquet** 列式格式。除了用户声明的列，Mito 在每个 SST 里还额外维护三列内部元数据，供多读合并、去重、删除时使用：

| 内部列 | 含义 |
| :-- | :-- |
| `__primary_key` | 编码后的主键（tag 列） |
| `__sequence` | 行的序列号 |
| `__op_type` | 行的操作类型（put / delete） |

Parquet 的 row group 是独立读/跳过的最小单位，每个 row group 带列级 min/max 与 null count。Mito 还记录文件级统计——这些统计驱动 scan pruning（见下文）。

SST 格式有两种：`flat`（新表默认，适合各种主键基数，包括高基数）与 `primary_key`（兼容旧表的 legacy 格式）。

### Scan Pruning

Mito 在读取时避免打开不可能匹配查询的数据，按从粗到细的顺序执行三层剪枝：

1. **时间范围剪枝** —— 文件与 memtable 的时间范围不与查询时间窗相交则跳过。对时序查询来说最便宜、也最有效。
2. **Row-group 统计剪枝** —— row group 的 min/max 统计能证明无行匹配则整组跳过。
3. **索引剪枝** —— 倒排索引、skipping index、全文索引提供更细粒度过滤，处理统计无法判定的谓词。

## Storage Location

GreptimeDB 的存储后端与引擎选择正交：Mito Engine 定义数据如何组织，local filesystem 或 object storage 只决定数据文件**落到哪里**。

| 状态类型 | 典型位置 | 持久性边界 |
| :-- | :-- | :-- |
| 持久数据文件（SST + 索引） | 本地文件系统 或 对象存储 | 对象存储需配版本控制/复制；本地文件需备份 |
| WAL | 本地 WAL / remote WAL / Noop | 接受但未 flush 的写入全靠 WAL 保护 |
| 元数据 | 单机本地 / Metasrv 集群 | 重建数据库状态必需，须持久化或复制 |
| 本地缓存 | Datanode 本地盘 | 随时可从持久数据重建，不算 durability 边界 |

**存算分离**是分布式部署的关键设计：SST 文件放到对象存储，Datanode 负责写入、compaction 与查询，本地磁盘只做缓存。计算与对象存储可以独立伸缩——扩容 Datanode 不需要搬迁任何持久数据文件。

支持的对象存储：Amazon S3 与 S3 兼容（MinIO、DigitalOcean Spaces、腾讯云 COS、百度 BOS）、Google Cloud Storage、Azure Blob Storage、阿里云 OSS。一张表可以通过 `storage` 选项选择配置好的 provider，实现冷/热数据分层（例如冷归档表落到便宜的 archive bucket）。

## Flow Computation

Flow 引擎让实时计算可以在写入数据流上连续执行，并把结果物化到 sink 表。它解决的典型问题：

- 仪表板与告警需要**现成聚合**，不想每次都扫原始 events。
- 数据降采样（downsampling），用 average pooling 等方式压缩存储体积。

### Programming Model

```
  source 表 ──▶ Flow 引擎 ──▶ sink 表
  (原始数据)    (EVAL INTERVAL)  (物化结果)
```

Flow 定义的核心是一条 `CREATE FLOW` SQL：source 表 → SQL 计算逻辑 → sink 表 + `EVAL INTERVAL`。source 与 sink 都是 GreptimeDB 内部的时序表，各自独立维护 schema、TTL、索引与存储位置。

```sql
CREATE FLOW http_status_count
SINK TO status_metrics
EVAL INTERVAL '10s'
AS
SELECT
    status_code,
    COUNT(*) AS count,
    date_bin('1 minute'::INTERVAL, timestamp) AS time_window
FROM access_logs
GROUP BY status_code, time_window;
```

1. source 表上的新写入被镜像（streaming）或定期拉取（batching）到 Flow 引擎。
2. Flow 执行 SQL 聚合，把结果写到 sink 表。
3. 查询仪表板时读 sink 表即可，不必再扫描原始 access_logs。

### Modes

- **Batching**（默认）—— 按 `EVAL INTERVAL` 定期从 source 表拉取并计算，适合聚合与 TQL 负载。
- **Streaming** —— 每条写入都镜像到 Flownode，适合简单、低延迟的非聚合转换。新负载不推荐。

生产案例：OceanBase Cloud 用 80+ 个 GreptimeDB 集群承载 300 TB 日志，Poizon 用 Flow 维持 10s/1m/10m 三级 rollup，把 P99 查询延迟从秒级压到毫秒级。

## Ingestion and Query Protocols

GreptimeDB 没有强迫用户替换采集 agent 或仪表板——它在写入侧兼容多个成熟协议、在读侧保留对应的查询接口：

| 方向 | 协议 / API | 说明 |
| :-- | :-- | :-- |
| **写入** | Prometheus Remote Write | metrics，客户端不需要改 |
| | OpenTelemetry OTLP/HTTP | metrics、logs、traces 全覆盖 |
| | Loki Push API | logs（写入兼容，但不提供 LogQL 查询） |
| | Elasticsearch Bulk API | 文档摄入（Bulk 接口，非完整 Query DSL） |
| | InfluxDB Line Protocol | 与 InfluxDB 写入格式兼容 |
| | MySQL / PostgreSQL wire | 标准 SQL |
| | GreptimeDB gRPC / HTTP | 原生接口 |
| **查询** | SQL | 跨所有信号类型 |
| | PromQL | 只对 metrics |
| | Jaeger-compatible API | traces |
| | HTTP API | 原生查询与管理 |

Grafana 仪表板可以直接用 MySQL 数据源接 GreptimeDB，不需要额外的 datasource plugin。

## Observability 2.0 and Wide Events

GreptimeDB 的数据模型原生支持三种信号，但并不强制你按 pillars 拆分。**Observability 2.0** 是 GreptimeDB 主推的一种可观测性范式——在采集时保留完整宽事件（wide event），而不是预先决定每个字段怎么用。一次业务操作的完整上下文（用户 ID、trace_id、HTTP 属性、DB 查询、缓存操作、结果、耗时）都存成一张表的一行：

```
{
  "timestamp":  "2026-08-12T08:15:30Z",
  "method":     "POST",
  "path":       "/articles",
  "service":    "articles",
  "user_id":    "fdc4ddd4-...",
  "trace_id":   "4bf92f3577b34da6a3ce929d0e0e4736",
  "status_code": 201,
  "duration":   268,
  "db_query":   "INSERT INTO articles (...)"
}
```

事后分析时可以用 SQL 任意切片，也可以用 Flow 从同一批宽事件派生出仪表板需要的 metrics——这样就不需要提前决定「哪些字段要进哪个 pillar」。

宽事件 approach 的代价：更多字段 = 更大数据量、高基数（user_id、session_id）+ 长保留 = 更高成本。所以 GreptimeDB 允许原生 metrics/logs/traces 和宽事件并存——在成本和灵活性之间按场景选择。

## Comparison

| 维度 | GreptimeDB | InfluxDB 3.x | VictoriaMetrics | Prometheus + Loki |
| :-- | :-- | :-- | :-- | :-- |
| 信号覆盖 | metrics + logs + traces + 宽事件 | metrics + logs + traces | metrics only | metrics 单独 + logs 单独 |
| 存储引擎 | Mito（LSM + Parquet） | 自研 | 自研 LSM | 各自独立 |
| 持久化 | 对象存储 / 本地 | 对象存储 / 本地 | 本地 | 各自独立 |
| 存算分离 | ✅ 原生 | ✅ | ❌ | 视部署 |
| 连续聚合 | Flow | Continuous Query | 无 | recording rules |
| 查询语言 | SQL + PromQL | SQL + InfluxQL | MetricsQL | PromQL + LogQL |
| 部署组件 | Metasrv + Frontend + Datanode + Flownode | 单进程 / 分布式 | 单进程 | 多组件 |

与 [InfluxDB](/docs/CS/DB/InfluxDB.md) 对比：两者都是时序 / 可观测性方向，但 InfluxDB 是**专用 TSDB 扩展**路径，GreptimeDB 是**从头按统一可观测设计**的单列式引擎；GreptimeDB 的对象存储原生支持和 Flow 计算是 InfluxDB 3.x 有对应但工程路径不同的特性。

## Links

- [DataBases](/docs/CS/DB/DB.md)
- [Timeseries](/docs/CS/DB/Timeseries.md)
- [InfluxDB](/docs/CS/DB/InfluxDB.md)
- [ClickHouse](/docs/CS/DB/ClickHouse.md)
- [Cassandra](/docs/CS/DB/Cassandra.md)
- [QuestDB](/docs/CS/DB/QuestDB.md)
- [IoTDB](/docs/CS/DB/IoTDB.md)
- [OpenTSDB](/docs/CS/DB/OpenTSDB.md)
- [LSM Tree](/docs/CS/Algorithms/tree/LSM.md)
- [WAL](/docs/CS/DB/WAL.md)

## References

1. [GreptimeDB Official Documentation (v1.2)](https://docs.greptime.com/)
2. [GreptimeDB Contributor Guide](https://docs.greptime.com/contributor-guide/overview/)
3. [GreptimeDB 中文文档](https://docs.greptime.cn/)
4. [Why GreptimeDB](https://docs.greptime.com/user-guide/concepts/why-greptimedb/)
5. [OceanBase Cloud: GreptimeDB 300 TB 日志存储](https://greptime.com/blogs/2025-07-22-user-case-obcloud-log-management-greptimedb)
6. [Poizon: Flow 连续聚合实战](https://greptime.com/blogs/2025-05-06-poizon-observability-greptimedb-monitoring-use-case)
7. [Agent RCA Bench](https://rca-bench.greptime.com/) — 六模型对比 GreptimeDB vs Prometheus+Loki+Tempo
