## Introduction

InfluxDB 是时序数据库里知名度最高的名字，**3.x 版本**（2024 GA，基线 **3.12.1**，2026-10-14）标志着四年半架构重构完成：Rust 重写，底层全部基于 FDAP 栈——Apache **Flight**（数据传输）+ Apache **DataFusion**（向量化查询引擎）+ Apache **Arrow**（内存列式）+ Apache **Parquet**（持久化列式）。1.x/2.x 是 Go 写的旧版本，已进入维护期，新负载一律建在 3.x 上。

3.x 的定位是**实时观测数据缓冲 + 对象存储落盘**：摄入侧同时吃 metrics、logs、traces 三种信号（OTLP / Prometheus Remote Write / Influx Line Protocol / Loki / Elasticsearch Bulk），查询侧主力是标准 SQL（DataFusion 全功能执行）并保留 InfluxQL 兼容层，持久化侧以 Parquet 落对象存储（diskless 架构，本地只做缓存和 WAL）。与 2.x 最痛的断裂是 **Flux 全线移除**，以及 Continuous Query / Task / Kapacitor 被库内嵌的 Python Processing Engine 取代。

产品线按部署形态分五条：**Core**（开源 MIT/Apache-2.0，单节点）、**Enterprise**（商业，单二进制多节点，HA / 读副本 / compaction）、**Clustered**（K8s，Router / Ingester / Querier 解耦）、**Cloud Serverless / Cloud Dedicated**（托管）。选型与迁移见 [Deployment](/docs/CS/DB/InfluxDB/Deployment.md)。

## Map of This Section

理解 InfluxDB 3 从**进程长什么样**开始。[Architecture](/docs/CS/DB/InfluxDB/Architecture.md) 拆开单二进制的内部世界：`serve` 进程按 mode 拆出 ingest / query / process / compact 子进程，写入沿 validation → write buffer → WAL → Parquet snapshot 四层流动，一秒持久化、验证即可查；四层缓存（queryable buffer、Parquet file cache、Last Value Cache、Distinct Value Cache）保证最近数据的查询不碰对象存储。

数据为什么这样放，要看模型。[Data_Model](/docs/CS/DB/InfluxDB/Data_Model.md) 讲 measurement + tag + field + timestamp 四元组与 Line Protocol 语法，核心决策是"只有唯一标识才配做 tag"——因为 tag 集合是主键，建表后不能再加 tag 列；`::` 分隔符的 column family 决定物理分块。

落盘格式是 FDAP 的落点。[Storage_Engine](/docs/CS/DB/InfluxDB/Storage_Engine.md) 对比 Core 的纯 Parquet 路线与 Enterprise 3.11 起默认的 upgraded storage engine（PachaTree）：两级 L1/L2 compaction、按数据类型选编码（delta-delta / Gorilla / dictionary）、文件级到 field family 的四层剪枝。

查询接口只有两种语言。[Query](/docs/CS/DB/InfluxDB/Query.md) 讲 SQL 与 InfluxQL 的分工、Flight SQL 传输、Flux 为何被砍以及迁移替代表；降采样没有 CQ 引擎，走 SQL 物化或 downsampler 插件。

库内计算是 3.x 最激进的一刀。[Processing_Engine](/docs/CS/DB/InfluxDB/Processing_Engine.md) 讲内嵌 Python VM：三种触发器（WAL flush / schedule / request）、插件 API、官方 downsampler / resampler 插件——CQ、Task、Kapacitor 的功能正式搬进数据库。

最后落到运维。[Deployment](/docs/CS/DB/InfluxDB/Deployment.md) 覆盖 Docker 最小部署、CLI / 环境变量 / catalog 三层配置、1.x/2.x 迁移路径与五条产品线的选型。

## Comparison

| 维度 | InfluxDB 3 | GreptimeDB | TimescaleDB | VictoriaMetrics | TDengine |
| :-- | :-- | :-- | :-- | :-- | :-- |
| 语言 | Rust | Rust | C（PG 扩展） | Go | C |
| FDAP 栈 | ✅ | ❌ | ❌ | ❌ | ❌ |
| 存储引擎 | Arrow + Parquet + DataFusion（Core）；upgraded engine（Enterprise） | Mito LSM + Parquet SST | PG + 列式压缩 | 自研 LSM part | 自研列式 LSM |
| 对象存储原生 | ✅ | ✅ | ❌ | ❌ | ❌ |
| 查询语言 | SQL + InfluxQL | SQL（MySQL/PG wire） | 完整 PG | MetricsQL / PromQL | 类 MySQL（无 JOIN） |
| 多信号 | metrics + logs + traces | metrics + logs + traces | ❌ | metrics only | ❌ |
| 存算分离 | ✅ | ✅ | ❌ | ❌ | ❌ |
| 库内计算 | Python Processing Engine | Flow | ❌ | ❌ | ❌ |
| 定位 | FDAP 最现代，但 2.x 迁移（尤其 Flux）代价重 | 保留时序专用引擎与 Flow，Rust 同代 | 绑定 PG 生态但无法独立伸缩 | 轻量，只做 metrics | 一设备一表，IoT 场景最优 |

## Links

- [DataBases](/docs/CS/DB/DB.md)
- [Timeseries](/docs/CS/DB/Timeseries.md)
- [GreptimeDB](/docs/CS/DB/GreptimeDB.md)
- [TDengine](/docs/CS/DB/TDengine.md)
- [VictoriaMetrics](/docs/CS/DB/VictoriaMetrics.md)
- [WAL](/docs/CS/DB/WAL.md)

## References

1. [InfluxDB 3 Documentation](https://docs.influxdata.com/influxdb3/)
2. [Which InfluxDB 3 should I use](https://docs.influxdata.com/influxdb3/which-influxdb-3/)
3. [InfluxDB 3 Core and Enterprise GA](https://www.influxdata.com/blog/influxdb-3-oss-ga)
4. [InfluxDB 3 Enterprise Release Notes](https://docs.influxdata.com/influxdb3/enterprise/release-notes/)
5. [Architecture Overview of InfluxDB 3](https://www.influxdata.com/learn/architecture-overview-of-influxdb-3)
6. [InfluxDB v3.12.1 Release](https://github.com/influxdata/influxdb/releases/tag/v3.12.1)
