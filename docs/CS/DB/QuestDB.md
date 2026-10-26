## Introduction

QuestDB 是一个追求**极致低延迟**的时序数据库——设计目标场景是交易地板（trading floors）、任务控制（mission control）、高频采集这些"丢一条记录就有后果"的地方。它用 **zero-GC Java + C++ + Rust 混合**实现，靠三层存储引擎和向量化执行把摄入延迟压到微秒级、查询最新状态压到毫秒级。

QuestDB 当前稳定版本 **10.0**（2026-08 发布），最大亮点是推出了 **QWP（QuestDB Wire Protocol）**——自研二进制列式协议，替代多年来用 Influx Line Protocol 写 + HTTP 查的"双协议"形态。

QuestDB 的定位很独特：它不是可观测一体化（不做 logs/traces），不是关系扩展（不绑定 PG），不是宽列（不做 supertable），而是**纯 SQL-first 的时序引擎**——用普通 SQL 查时序数据、用 Influx Line Protocol / Prometheus Remote Write / QWP 写入。

## Architecture

QuestDB 单机部署就是一个 `questdb.jar` 进程。集群版（Enterprise）叫 QuestDB Enterprise，增加了分布式和冷存储编排。

```
                写入协议（ILP / Prom RW / QWP）
                        │
                        ▼
              ┌──────────────────────┐
              │  Tier 1: WAL          │   保护 durability + 缓冲 out-of-order
              │  (log storage)        │   数据到达 WAL 后立即可查
              └──────────┬───────────┘
                         │ 按 symbol hash 路由
                         ▼
              ┌──────────────────────┐
              │  Tier 2: 本地列式分区 │   热层，向量化执行核心
              │  (time-partitioned,   │   每个 partition 是目录
              │   per-symbol files)   │   列独立文件、按 symbol 分片
              └──────────┬───────────┘
                         │ 冷分区自动转换
                         ▼
              ┌──────────────────────┐
              │  Tier 3: Parquet      │   冷存储，对象存储兼容
              │  (object storage,     │   分析友好、跨引擎可读
              │   columnar)           │
              └──────────────────────┘
```

三层存储是 QuestDB 的核心架构决策：

| Tier | 格式 | 位置 | 作用 |
| :-- | :-- | :-- | :-- |
| **Tier 1: WAL** | 自研日志格式 | 本地磁盘 | ① durability 保证；② 缓冲 out-of-order 数据、WAL 内部排序后再 commit 到 Tier 2。**WAL 内数据已可查**（查询时 Tier 1 + Tier 2 合并返回） |
| **Tier 2: 本地列式分区** | 自研列式格式 | 本地磁盘 | 热查询层。表按时间（`PARTITION BY DAY` 默认）分区，**每个 partition 目录内部按 symbol hash 分片**（避免单 symbol 的时间轴文件过大）。每列一个独立文件，向量化执行直接扫列 |
| **Tier 3: Parquet** | Apache Parquet | 对象存储（S3/GCS/Azure）或本地 | 冷存储。旧 partition 自动转换成 Parquet，跨引擎可读。Enterprise 版支持把冷分区直接放对象存储、热分区留本地 |

> Tier 1 → Tier 2 → Tier 3 的迁移是 **单向、自动、无停机** 的——后台线程定时检查 partition 年龄，满足条件就异步启动转换，转换完成后新查询自动切到新格式，老 partition 文件异步删。

### Symbol Sharding

QuestDB 的关键数据布局：

```
PARTITION (time_bucket)
  │
  ├── symbol_0/     ← 按 symbol hash 分 256 个分片
  │   ├── col_timestamp
  │   ├── col_open
  │   ├── col_close
  │   └── col_volume
  ├── symbol_1/
  └── ... symbol_255/
```

一个 partition 内按 symbol 哈希成 256 个目录——每个目录存放该 symbol 分片的全部列文件。**查询某个 symbol 的时间范围时只需打开一个分片目录**，定位极快。同时跨 symbol 的聚合查询（`SELECT avg(price) FROM trades WHERE ts > ...`）可以并行扫全部 256 个分片。

### Out-of-Order Buffer

QuestDB 的 WAL 内置一个 out-of-order buffer：如果写入数据的时间戳落在"当前 WAL 窗口"之后（乱序到达），先在 buffer 里等几毫秒再排序 commit——避免乱序数据在 Tier 2 里产生大量小文件。buffer 默认 5 秒窗口、可配置。

## Query

QuestDB 用**普通 SQL**，加了一组时序扩展：

```sql
-- 基本采样
SELECT ts, price FROM trades WHERE symbol = 'AAPL' AND ts > '2026-10-20'::TIMESTAMP;

-- 时间桶（window）
SELECT ts, avg(price), sum(volume)
FROM trades
WHERE symbol = 'AAPL'
SAMPLE BY 1m FILL(NULL);  -- 1 分钟桶 + 无数据填 NULL

-- asof join（时序 join 新范式）
SELECT t.ts, t.symbol, t.price, c.volume
FROM trades t ASOF JOIN candles c
ON t.symbol = c.symbol AND t.ts >= c.ts;
-- 找每个 trade 之前最近的 candle，普通 SQL JOIN 会产生笛卡尔积
```

关键时序扩展：

| 扩展 | 含义 |
| :-- | :-- |
| `SAMPLE BY` | 时间桶分组（类似 PromQL 的 `[5m]`、TimescaleDB 的 `time_bucket`） |
| `ASOF JOIN` | 非精确 match 的时序 join——对每个左表行，匹配右表中 `ON` 条件满足的**最近**一行 |
| `LATEST BY` | 按分组选出最新值，类似 Prometheus 的 `timestamp()` |
| `INTERPOLATE` | 对 SAMPLE BY 的空桶做线性插值 |

**向量化执行**：QuestDB 的 SQL 引擎是向量化的——一次处理一整列数据，用 CPU SIMD 指令在内存寄存器里算聚合。这让"过去一小时 10 亿行求 avg"这种查询能在几十毫秒内返回。

## Ingestion Protocols

QuestDB 设计上兼容成熟协议，同时提供自研 QWP：

| 协议 | 类型 | 说明 |
| :-- | :-- | :-- |
| **QWP（QuestDB Wire Protocol）** | 自研二进制列式，WebSocket | QuestDB 10.0 推出，写入和查询走**同一个连接**、同一个驱动。二进制列式传输比 ILP 快 3.6x，查询结果以 Arrow 流式返回 |
| Influx Line Protocol | 文本 | 多年来的主入口，成熟、简单，但文本解析有开销 |
| Prometheus Remote Write | 写入 | 与 Prometheus 生态打通 |
| PostgreSQL wire | 查询 | 兼容 psql、pgx 等 |
| HTTP REST | 写 + 查 | 简单场景 |

## Comparison

| 维度 | QuestDB | VictoriaMetrics | InfluxDB 3.x | GreptimeDB | TimescaleDB | TDengine |
| :-- | :-- | :-- | :-- | :-- | :-- | :-- |
| 语言 | Java + C++ + Rust | Go | Rust | Rust | C（PG 扩展） | C |
| 定位 | SQL-first、极致低延迟 | Prometheus 生态集群化 | metrics+logs+traces 一体化 | metrics+logs+traces 一体化 + 对象存储 + Flow | PG 生态内时序 | IoT + 工业物联网（一设备一表） |
| 存储 | WAL（Tier 1）+ 本地列式分区（Tier 2）+ Parquet 冷层（Tier 3） | 按月分区 LSM + 自研压缩 | Arrow（内存）+ Parquet（落盘）+ DataFusion | Mito LSM + Parquet SST + TWCS | PG 行存 + 列式压缩 | 自研列式 LSM |
| WAL | ✅ Tier 1 核心 | ❌ | ✅ 可选 | ✅ 多模式 | ✅（PG 自带） | ✅ |
| SQL | ✅ 普通 SQL + SAMPLE BY + ASOF JOIN | ❌ | ✅ DataFusion | ✅ MySQL/PG wire | ✅ 完整 PG | 类 MySQL（无 JOIN） |
| PromQL | ❌ | ✅ MetricsQL | ✅ 兼容层 | ✅ | ❌ | ❌ |
| 多信号 | ❌（纯时序） | metrics only | ✅ | ✅ | ❌ | ❌ |
| 对象存储 | Tier 3 冷层 | ❌ | ✅ 原生 | ✅ 原生 | ❌ | ❌ |
| 存算分离 | ❌ | ❌ | ✅ | ✅ | ❌ | ❌ |
| 乱序处理 | WAL buffer 5s 排序 | compaction 去重 | Ingester buffer | merge mode | PG 自动合并 | 写入侧接受乱序 |
| 典型场景 | 交易、任务控制、超低延迟需求 | Prometheus 长保留、集群化 | 可观测统一 | 可观测统一 + 对象存储 | 关系 + 时序混合 | 国内 IoT、电力 |

选 QuestDB 的典型场景：写入速度要求极高（百万行/秒）、查询最新状态毫秒级返回、需要 SQL 而非 PromQL、数据最终要能转 Parquet 被其他引擎消费。

## Links

- [DataBases](/docs/CS/DB/DB.md)
- [Timeseries](/docs/CS/DB/Timeseries.md)
- [VictoriaMetrics](/docs/CS/DB/VictoriaMetrics.md)
- [InfluxDB](/docs/CS/DB/InfluxDB.md)
- [GreptimeDB](/docs/CS/DB/GreptimeDB.md)
- [TimescaleDB](/docs/CS/DB/TimescaleDB.md)
- [TDengine](/docs/CS/DB/TDengine.md)
- [LSM Tree](/docs/CS/Algorithms/tree/LSM.md)
- [WAL](/docs/CS/DB/WAL.md)

## References

1. [QuestDB 官方文档](https://questdb.com/docs/)
2. [TimescaleDB vs QuestDB: 2026 Benchmark](https://questdb.com/blog/timescaledb-vs-questdb-comparison/)
3. [QuestDB 10.0 Release — QWP](https://questdb.com/blog/questdb-10-release/)
4. [Parquet and Iceberg: QuestDB Tier 3](https://questdb.com/blog/parquet-and-iceberg-questdb/)
5. [ASOF JOIN 设计](https://questdb.com/docs/reference/sql/join/asof/)
