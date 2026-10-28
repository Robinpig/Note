## Introduction

OpenTSDB 是**最老的分布式时序数据库之一**——2010 年由 StumbleUpon 开源，核心设计是"把 HBase 改造成时序引擎"。它的时代是 2010 年代前中期——当时 Prometheus 还没诞生（2016）、InfluxDB 还是 Go 重写前的版本、VictoriaMetrics 不存在、GreptimeDB 不存在。在那个年代，OpenTSDB 是唯一能做到"百万序列 / 秒摄入 + 线性扩容 + 毫秒级读"的开源选择。

当前稳定版本 **2.4**（最新发布），社区活跃但已不是新用户的首选。它的价值更多在于理解"时序数据库的基础设计范式"——怎么把通用 KV 存储（HBase）硬套进时序的行列模型，以及这种做法在高基数 / 新查询模式下的天然缺陷。

## Architecture

OpenTSDB 的架构非常简单：

```
  tcollector（采集 agent，可选）
         │
         ▼
     ┌──────────┐     ┌──────────┐
     │   TSD 1  │     │   TSD 2  │  ← Time Series Daemon，OpenTSDB 核心
     └────┬─────┘     └────┬─────┘          Java 进程，负责摄入 + 查询
          │                │
          ▼                ▼
     ┌──────────────────────────┐
     │        HBase 集群         │  ← 持久化存储，用 AsyncHBase 客户端
     │  (tsdb table + tsdb-uid)  │     行键设计是 OpenTSDB 的核心发明
     └──────────────────────────┘
```

| 组件 | 语言 | 职责 |
| :-- | :-- | :-- |
| **TSD（Time Series Daemon）** | Java | OpenTSDB 的核心进程——接收写入、处理查询、做 rollup、读 HBase、处理 uid 映射。多个 TSD 实例水平扩展 |
| **tcollector** | Python | 采集 agent（可选），负责从 hosts / metrics 源采集、批量推送到 TSD。可用 OpenTSDB 自己的 Python 脚本，也可用任何 HTTP 客户端 |
| **HBase** | C + Java | 持久化存储。OpenTSDB 用 AsyncHBase（自研异步客户端）做非阻塞访问 |
| **Grafana / OpenTSDB Web UI** | — | 查询可视化前端 |

> AsyncHBase 是 OpenTSDB 的关键依赖——它用纯异步、non-blocking 的方式访问 HBase，让单个 TSD 进程能扛住**百万级写入 / 秒**而不被 HBase RPC 阻塞。AsyncHBase 后来反哺了 HBase 社区。

## HBase Row Key Design

OpenTSDB 把时序数据映射到 HBase，最关键的发明是**行键设计**：

```
  Metrics Row Key = [metric_name][base_timestamp][uid_0][uid_1]...[uid_n-1]
                     ↑ 4 bytes    ↑ 4 bytes          ↑ 3 bytes each
                     UTF-8 字符串  Unix epoch 秒        每个 tag 的 uid
```

其中 `uid` 是 OpenTSDB 的**uid table** 给每个 metric name 和 tag 值分配的 3 字节整数——把长字符串压缩成定长数字，**大幅缩短 row key、加速 HBase scan**。

时间戳部分只存 **base timestamp**（精确到小时的 Unix 秒），精确的毫秒时间戳作为 **column qualifier** 存。一行就是一个时间序列在**一个小时内的所有采样点**：

```
ROW KEY: cpu.util|4470196800|abc|def|ghi
  col: 4470196800123 → value: 0.42
  col: 4470196800500 → value: 0.47
  col: 4470196801100 → value: 0.45
  ...
  col: 4470197999999 → value: 0.52
```

这种设计让同一时间序列的所有采样点**在 HBase 上物理连续**——扫描一个小时的数据只要打开一行。

### Rollup（预聚合）

OpenTSDB 内置 rollup——定期对原始时序做时间窗口聚合、写入另一张表：

```
  原始数据（15 秒采样）     Rollup（1 小时聚合）
  ┌───────────────────┐    ┌───────────────────┐
  │ cpu.util ... col: │    │ cpu.util ... col: │
  │ 4470196800015 ... │    │ 44701968003600   │   ← 时间桶起点
  │ 4470196800030 ... │    │   value: {avg,   │
  │ ...               │    │           max}  │
  └───────────────────┘    └───────────────────┘
```

查询"过去一周 cpu.util 平均值"时 TSD 直接读 rollup 表，不需要扫原始数据再聚合。

## UID Table

OpenTSDB 用一张独立的 `tsdb-uid` 表维护"字符串 → 3 字节整数"的映射：

| 字符串类型 | 例子 | uid |
| :-- | :-- | :-- |
| metric | `cpu.util` | `abc` |
| tag key | `host` | `123` |
| tag value | `server01` | `456` |

写入流程：
1. TSD 收到写入（带完整 metric name + tag string）。
2. 查 uid table 拿到各字符串的 3 字节 uid（不存在则分配新 uid）。
3. 用 uid 组装 row key 和 column qualifier。
4. 写入 HBase。

查询时做反向映射——把 row key 里的 uid 还原成字符串，返回给客户端。

## Write and Query Path

### Write Path

```
  客户端 / tcollector
       │ POST /api/put  (batch, HTTP)
       ▼
  TSD 进程
   ├── 解析 metric + tags + timestamp + value
   ├── uid lookup（查 tsdb-uid）
   ├── 组装 HBase row key + column qualifier
   ├── push 到 AsyncHBase write buffer（异步、批量）
   └── 返回 204 OK（不等 HBase 落盘）
```

### Query Path

```
  客户端
   │ GET /api/query?start=...&end=...&m=avg:5m-avg-zero:cpu.util{host=*}
   ▼
  TSD 进程
   ├── 解析查询（metrics、时间范围、过滤器、聚合、downsample）
   ├── uid lookup（反查 metric + tag 的 uid）
   ├── 组装 HBase scan（row key range + time column qualifier 范围）
   ├── 并行向所有匹配 row key 的 Region 发 scan（AsyncHBase）
   ├── 合并所有 Region 返回的 row，按时间排序
   ├── 做 downsample（5 分钟 avg）和聚合
   └── 返回 JSON
```

查询语法是 OpenTSDB 特有的 **metric expression string**——不像 PromQL 或 SQL，但表达力很强：

```
  avg:5m-avg-zero:cpu.util{host=server01,region=us-east}
  │     │              │              │
  │     │              │              └── tag 过滤器
  │     │              └── metric name
  │     └── downsample（时间窗口 + 聚合 + zero 填充）
  └── 聚合器（跨 tag 组合）
```

## 局限

OpenTSDB 的设计在 2010 年代非常聪明，但在今天有明确的局限——理解这些局限帮助理解后来的时序库为什么走向不同路线：

| 局限 | 原因 | 替代方案 |
| :-- | :-- | :-- |
| **高基数 tag value 爆炸 uid 表** | 3 字节 uid 只有 16M 种组合；新 uid 分配后不会重用；uid 表无限膨胀 | Prometheus 去掉 uid 映射，让 label 直接做序列身份 |
| **没有 SQL** | 查询是自定义 metric expression string，表达力有限、学习曲线陡峭 | InfluxDB 3.x / GreptimeDB / TimescaleDB 都提供完整 SQL |
| **只有 metrics** | 没有 logs、traces、events | InfluxDB 3.x、GreptimeDB 统一三信号 |
| **必须依赖 HBase** | 运维复杂度极高（HBase 集群 + ZK 集群 + OpenTSDB 集群） | VictoriaMetrics、QuestDB、TDengine、IoTDB 都自带存储 |
| **行是按小时分块的** | 跨小时查询需要 scan 多行、客户端做合并 | 更现代的 TSDB 用 LSM 列式格式，跨时间范围查询只需扫列 |
| **AsyncHBase 维护成本高** | 已不是 HBase 社区主线 | 现代 TSDB 直接用自己的存储引擎 |

## Status

OpenTSDB 2.4 仍是最新稳定版。社区活跃，但**新用户基本不再选择它**——Prometheus（简单、原生 metrics、生态广）、VictoriaMetrics（Prometheus 兼容 + 集群）、InfluxDB 3.x（SQL + 多信号）、GreptimeDB（统一 + 对象存储）、QuestDB（极致低延迟）在各自定位上都更强。

OpenTSDB 的历史贡献：**证明了时序数据按 metric + timestamp + tag 建模的正确性、证明了 HBase row key 设计可以让时序 scan 极快、发明了 rollup 预聚合范式**——这些思想被后来的所有时序库吸收。

## Links

- [DataBases](/docs/CS/DB/DB.md)
- [Timeseries](/docs/CS/DB/Concept/Timeseries.md)
- [InfluxDB](/docs/CS/DB/InfluxDB/InfluxDB.md)
- [VictoriaMetrics](/docs/CS/DB/Timeseries/VictoriaMetrics.md)
- [GreptimeDB](/docs/CS/DB/Timeseries/GreptimeDB.md)
- [TimescaleDB](/docs/CS/DB/Timeseries/TimescaleDB.md)
- [TDengine](/docs/CS/DB/TDengine/TDengine.md)
- [QuestDB](/docs/CS/DB/Timeseries/QuestDB.md)
- [IoTDB](/docs/CS/DB/Timeseries/IoTDB.md)
- [Cassandra](/docs/CS/DB/Cassandra/Cassandra.md)
- [HBase](/docs/CS/DB/HBase/HBase.md)

## References

1. [OpenTSDB 官方文档](https://opentsdb.net/docs/)
2. [OpenTSDB Architecture](http://opentsdb.net/misc/opentsdb-oscon.pdf) — OSCON 2013 演讲，原始设计
3. [AsyncHBase](https://github.com/OpenTSDB/async-hbase)
4. [TSDB Row Key Design Explained](https://opentsdb.net/docs/build/html/user_guide/writing/index.html)
5. [Comparing OpenTSDB, Prometheus, VictoriaMetrics](https://opentsdb.net/alternative-to-opentsdb.html) — OpenTSDB 自己的迁移指南
