## Introduction

Cassandra 以「节点对等、线性扩展」著称，但「易扩展」不等于「免运维」。本页覆盖部署、关键配置、监控、调优、扩缩容、备份恢复与常见坑，目标是把「按架构能跑」变成「生产稳跑」。

> 基线：Cassandra 5.0（JDK 17）。4.0 引入 Audit Logging，4.1 引入 Guardrails，5.0.8+ 有 Auto Repair。

## Deployment

- **拓扑**：生产用 `NetworkTopologyStrategy` + `GossipingPropertyFileSnitch`，每台机声明 `dc`/`rack`（`cassandra-rackdc.properties`）。
- **单 DC / 多 DC**：多 DC 只需在 keyspace 加 DC 维度 RF，节点间跨 DC 异步，写入仍只等本地 quorum。
- **Kubernetes**：官方生态有 **cass-operator**（K8ssandra 栈），把 bootstrap、seed 管理、备份集成进 Operator；注意 StatefulSet 的 PVC 与 `num_tokens` 规划。
- **JVM**：5.0 要求 JDK 17；GC 仍是运维重点（G1 为主，超大堆考虑 Shenandoah/ZGC）。

## Key Configuration (cassandra.yaml)

| 配置 | 说明 |
| --- | --- |
| `seeds` | 初始发现用的 seed 节点列表 |
| `listen_address` / `rpc_address` | 节点间 / 客户端 监听地址 |
| `num_tokens` | 每节点 vnode 数（默认 256） |
| `concurrent_reads` / `concurrent_writes` | 读写并发（按核/磁盘调） |
| `memtable_flush_writers` / `memtable_heap_space` | Memtable 刷盘阈值 |
| `compaction_throughput_mb_per_sec` | compaction 限速（默认 16） |
| `hinted_handoff_enabled` / `max_hint_window` | hinted handoff 开关与窗口 |
| `authenticator` / `authorizer` | 认证/授权（见 Security） |

## Monitoring

- **JMX / MBeans** 是核心：读延迟、写延迟、pending compaction、hinted handoff、tombstone 扫描数、thread pool 阻塞等。
- 生产常用 **cassandra-exporter + Prometheus + Grafana** 采集；关键指标：
  - `ReadLatency` / `WriteLatency`（p99 比平均更有意义）；
  - `PendingCompactions` / `CompactionBytes`——积压预示读劣化；
  - `TombstoneScannedPerQuery`——墓碑过多会拖垮读；
  - `HintedHandoffPending`——hint 堆积说明有副本长期宕机；
  - `ClientRequest` 各类异常（`TimeoutException` / `UnavailableException`）。
- **Guardrails（4.1+）**：可配置「表数量、分区大小、查询复杂度」等软硬限制，提前拦截危险操作而非等宕机。

### Key nodetool Commands

| 命令 | 用途 |
| --- | --- |
| `nodetool status` / `info` | 集群拓扑、各节点状态/负载/heap/token |
| `nodetool compactionstats` / `tblestats` | compaction 积压、表级统计（pending 预示读劣化） |
| `nodetool repair` | 反熵 repair（务必定期跑，见 [Distributed](/docs/CS/DB/Cassandra/Distributed.md)）；5.0.8+ 可 Auto Repair |
| `nodetool snapshot` / `clearsnapshot` | 一致快照（硬链接）与清理 |
| `nodetool rebuild` | 从其它 DC 拉数据重建本节点（多 DC 扩容后常用） |
| `nodetool bootstrap` / `decommission` / `removenode` | 拓扑变更与数据流式迁移（[Distributed](/docs/CS/DB/Cassandra/Distributed.md)） |
| `nodetool upgradesstables` | 升级 SSTable 格式（如切到 BTI，见 [Storage Engine](/docs/CS/DB/Cassandra/StorageEngine.md)） |

**虚拟表（4.0+）**：`system_views.*` / `system.*` 把运维指标、节点状态甚至日志暴露成可查询的 CQL 表（如 `system_views.metrics`、`system_views.pending_compactions`、`system.logs`），比纯 JMX 更易集成。`StorageServiceMBean` / `StorageProxyMBean` 等仍是 JMX 核心接口。

## Tuning

- **堆与 GC**：避免过大堆（> 31GB 指针压缩失效）；off-heap 缓存缓解。
- **Compaction**：按表选策略（见 [Compaction](/docs/CS/DB/Cassandra/Compaction.md)），调 `compaction_throughput`。
- **读写并发**：`concurrent_*` 与磁盘数/核数对齐；连接数靠驱动连接池。
- **大分区**：用桶化打散（见 [Data Model](/docs/CS/DB/Cassandra/DataModel.md)），否则 compaction 与 GC 会雪崩。
- **修复**：务必**定期 repair**（在 `gc_grace_seconds` 内），5.0.8+ 可开 Auto Repair。

## Scale (Add / Remove)

- **加节点**：新节点 `bootstrap`，从现有 replica 经 **streaming**（4.0+ zero-copy，见 [Distributed](/docs/CS/DB/Cassandra/Distributed.md)）拷贝其 range；TokenAware 驱动自动把流量迁过来。
- **减节点**：`nodetool decommission`（把本节点 range 迁走后下线）或 `removenode`（节点已不在时）。
- 扩容无需停机，但会短期抬升集群 IO（streaming + 受影响 replica 的读放大）。

## Backup / Restore

- **快照**：`nodetool snapshot` 对各表做**硬链接**式一致快照（几乎零成本），配合 `snapshot` + 增量（`incremental_backups`）拷贝到对象存储。
- **工具**：Medusa（社区）、或自研「snapshot + `sstableloader` 恢复」。
- **恢复**：把 SSTable 放回对应目录或 `sstableloader` 导入；注意恢复后需 repair 对齐副本。
- **演练**：恢复流程必须**定期演练**，否则备份只是心理安慰。

## Common Pitfalls

- 用 `ALLOW FILTERING` 做全表扫（生产禁用）。
- 超大/无界分区（建模反模式）。
- 长期不 repair → 墓碑复活、副本分歧。
- 把 LWT 当普通事务高频用（Paxos 四轮极慢）。
- 用 Materialized View 做核心链路（4.0+ 不推荐，见 [CQL](/docs/CS/DB/Cassandra/CQL.md)）。
- `ALL`/`EACH_QUORUM` 写导致一节点抖动就超时。

## Links

- [Cassandra](/docs/CS/DB/Cassandra/Cassandra.md)
- [Compaction](/docs/CS/DB/Cassandra/Compaction.md)
- [Distributed](/docs/CS/DB/Cassandra/Distributed.md)
- [Security](/docs/CS/DB/Cassandra/Security.md)

## References

- [Cassandra Operations (官方文档)](https://cassandra.apache.org/doc/latest/cassandra/operations/)
- [Cassandra Monitoring (官方文档)](https://cassandra.apache.org/doc/latest/cassandra/operating/metrics.html)
