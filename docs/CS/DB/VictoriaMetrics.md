## Introduction

VictoriaMetrics 是 Go 写的轻量时序数据库，目标场景是**给 Prometheus 生态提供长期存储和集群化**。它完全兼容 Prometheus 的 metric + labels + timestamp 数据模型，写入侧接受 Prometheus Remote Write（还有 InfluxDB Line Protocol、OpenTSDB、JSON、Graphite 等多种摄入协议），查询侧用 MetricsQL——PromQL 的一个严格超集。

VictoriaMetrics 有两种部署形态：

| 形态 | 组件 | 适用 |
| :-- | :-- | :-- |
| **单机（single）** | 一个 `victoriametrics` 进程，内置摄入、存储、查询全部逻辑 | 小规模，≤ 百万活跃时间序列 |
| **集群** | 四个独立服务：`vminsert`、`vmstorage`、`vmselect`、`vmalert` | 大规模，≥ 千万活跃序列、需要独立伸缩和高可用 |

> VictoriaMetrics 当前稳定版本 v1.154.0（2026-10）。社区版（VM）和企业版（VME）在开源版本基础上增加了 HA、多租户、K8s 部署、S3 备份等特性。

## Architecture

VictoriaMetrics 的集群采用**无共享（shared-nothing）**架构，四个组件各自独立伸缩、之间只有网络通信。每个组件内部是典型的 Go 微服务风格：

```
            ┌─────────┐
 Prometheus │ vminsert │────── consistent hashing ──────┐
 Remote Write └────┬────┘                                   │
                   │                                        ▼
                   │  月分区 × LSM parts               ┌──────────┐
                   │  自研列式压缩                     │ vmstorage │× N
                   └────────────────────────────────▶ │          │
                                                      │          │
 PromQL ───────────▶ ┌─────────┐     ┌──────────┐    └────┬─────┘
                     │vmselect │◀──── │ vmstorage │◀───────┘
                     └────┬────┘     └──────────┘        原始数据
                          │
                          ▼
                      聚合/排序/返回
```

### vminsert

接受摄入数据（Prometheus Remote Write 是最常用的入口），根据 metric name + 全部 label 计算一致性哈希，把每条样本发送到负责该哈希范围的 `vmstorage`。vminsert **无状态**——挂了不丢数据，Prometheus 的 remote write 有重试和队列。

### vmstorage

VictoriaMetrics 的核心存储组件，负责：

1. **按时间顺序落盘**：把 vminsert 发来的样本先放到内存 buffer（raw-row shard），大小超过阈值（约 120 MB）就 flush 成不可变 LSM part。
2. **按月分区**：数据先按时间戳路由到 `YYYY_MM` 月目录，再在月内做 LSM 合并。这是 VictoriaMetrics 的关键设计——**月分区本身就是最大的时间桶**，跨月查询不需要打开前一个月的文件。
3. **合并小 parts 为大 parts**：定期 compaction 把多个小 LSM part 合并成一个大 part，同时做去重（同一时间戳同一 metric 的多行只保留最新）和 retention（超过保留期的 part 直接 drop）。
4. **服务 vmselect 的查询请求**：按 label filters + 时间范围返回原始 sample 或预聚合结果。

### vmselect

接收 PromQL / MetricsQL 查询，解析后并行地向所有 vmstorage 节点拉取相关样本，在内存中聚合、排序、计算函数结果，最后返回给客户端。vmselect 维护一个**全量 metric name + label 组合的索引**（indexdb），用来快速确定"哪些 series 匹配 label 过滤器"而不用扫全部数据。

### vmalert（可选）

独立的告警规则引擎——跟 Prometheus Alertmanager 功能类似但跟 VictoriaMetrics 原生集成，避免 Prometheus → VM → Alertmanager 的多次跳转。

## Write Path

vmstorage 的摄入路径是一个**极简版 LSM Tree**——没有 WAL、没有 SSTable、没有 Bloom Filter，核心思路就是「永远不修改已落盘的数据，只追加和合并」：

```
   vminsert
      │ compress + route
      ▼
 raw-row shard (vmstorage 内存)
      │  size ≥ 120 MB
      ▼
 LSM part 1 (磁盘)          LSM part 2
      │                        │
      └──── compaction ────────┘
                  │
                  ▼
          Merged LSM part
          (去重 + retention)
```

关键设计：

- **无 WAL**：VictoriaMetrics 故意不写预写日志。好处是写入路径最短（buffer满→直接flush）、无磁盘双写、数据格式极简；代价是 **crash 时内存 buffer 里的未 flush 数据会丢**——对监控场景这通常可接受（下一个采集周期会覆盖）。
- **按月分区是一级路由**：月目录是最高效的剪枝——查"过去 24 小时"只需要打开当月目录，查"2025-01 月数据"完全不碰其他月。
- **LSM part 是列式的**：一个 part 内按 `(series_id, timestamp)` 排序，value 列独立存储、用 Gorilla XOR 压缩，比传统行存紧凑 5-10 倍。

## Query Path

vmselect 处理一条 MetricsQL 分四步：

1. **解析 + 语义检查**：拆成 series selector + 函数 + 聚合。
2. **indexdb 查 series**：从 vmstorage 索引里拿到匹配 label 过滤器的全部 series_id。
3. **向 vmstorage 拉 sample**：并行向 N 个 vmstorage 请求 `series_id ∩ time_range` 的 raw sample，并行下载。
4. **计算 + 聚合 + 排序**：vmselect 自己执行函数（rate、avg_over_time、histogram_quantile 等）和聚合（sum by (...)），然后把结果回给客户端。

## MetricsQL

MetricsQL 是 PromQL 的严格超集，加了一批监控场景的常用函数和语法：

| 特性 | 示例 | PromQL 有没有 |
| :-- | :-- | :-- |
| **窗口内多状态** | `prometheus_simple_table_over_time(..., "none")` | ❌ |
| **rollup（多时间粒度）** | `rollup(m, "1h", "1m")` | ❌ |
| **tstart / tstop** | `qrange(m, 30*60, 5*60, 15)` | ❌（PromQL 的 step 只支持秒） |
| **downsampling 原语** | `default_rollup_expr` | ❌ |
| **额外函数** | `clamp_max`、`clamp_min`、`safe_div`、`union`、`alias` | 其中部分在 PromQL 逐步加入 |
| **Query Log** | 查询级统计 | ❌ |

> MetricsQL 对兼容 PromQL 很严肃——**所有合法的 PromQL 查询在 MetricsQL 里运行结果一致**。额外函数都以不冲突的名字加上。

## Retention, Compaction, Deduplication

VictoriaMetrics 的数据生命周期完全由 compaction 驱动：

1. **Compaction 合并**：两个或多个小 LSM part 被重写成一个大 part，过程中自动执行三件事：
   - **去重**（deduplication）：同一 `(series_id, timestamp)` 上如果有多个 value（可能重复摄入或多节点写入冲突），按写入时序选最新值。
   - **Retention 删除**：part 的时间范围超出配置的保留期（默认无限），整个 part 直接 drop。
   - **时间重排**：把 part 内的 row 按 `(series_id, timestamp)` 排序——新 flush 的 raw-row shard 是按 vminsert 到达顺序乱序的，compaction 时统一整理。
2. **合并窗口限制**：vmstorage 不会合并跨越月分区的 part——按月分区作为隔离边界。

## Comparison

| 维度 | VictoriaMetrics | Prometheus | InfluxDB 3.x | GreptimeDB |
| :-- | :-- | :-- | :-- | :-- |
| 写入协议 | Prom RW + Influx LP + OpenTSDB + JSON | 自己 scrape / remote write | Influx LP + OTLP + Prom RW | Prom RW + OTLP + MySQL/PG |
| 查询语言 | MetricsQL（PromQL 超集） | PromQL | SQL + InfluxQL | SQL + PromQL |
| 集群组件 | vminsert + vmstorage + vmselect | 无（单节点） | 分布式版 | Metasrv + Frontend + Datanode |
| WAL | ❌ | ✅ | ✅（可关） | ✅（多种模式） |
| 持久化 | 本地磁盘 | 本地磁盘 | 对象存储 / 本地 | 对象存储 / 本地 |
| 存算分离 | ❌ | ❌ | ✅ | ✅ 原生 |
| 多信号 | metrics only | metrics only | metrics + logs + traces | metrics + logs + traces |
| SQL | ❌ | ❌ | ✅ | ✅ |
| 连续聚合 | vmalert | recording rules | continuous queries | Flow |

选 VictoriaMetrics 的典型场景：已经有 Prometheus 采集体系、只关心 metrics 存储、想把 retention 从 15 天拉到几百天或无限、想集群化但不想切换采集管道或查询语言。

## Links

- [DataBases](/docs/CS/DB/DB.md)
- [Timeseries](/docs/CS/DB/Timeseries.md)
- [InfluxDB](/docs/CS/DB/InfluxDB.md)
- [GreptimeDB](/docs/CS/DB/GreptimeDB.md)
- [Prometheus](/docs/CS/Distributed/Tracing/Prometheus/Prometheus.md)
- [QuestDB](/docs/CS/DB/QuestDB.md)
- [IoTDB](/docs/CS/DB/IoTDB.md)
- [OpenTSDB](/docs/CS/DB/OpenTSDB.md)
- [LSM Tree](/docs/CS/Algorithms/tree/LSM.md)
- [WAL](/docs/CS/DB/WAL.md)

## References

1. [VictoriaMetrics 官方文档](https://docs.victoriametrics.com/)
2. [vmstorage: Retention, Merging, Deduplication](https://victoriametrics.com/blog/vmstorage-retention-merging-deduplication/)
3. [The Life of a Metric](https://victoriametrics.com/blog/the-life-of-a-metric/) — 一条 metric 从采集到持久化的完整旅程
4. [Cluster Architecture](https://docs.victoriametrics.com/cluster-victoriametrics/)
5. [VictoriaMetrics Enterprise vs Community](https://docs.victoriametrics.com/enterprise/overview/)
