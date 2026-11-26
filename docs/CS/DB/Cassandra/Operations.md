## Introduction

Cassandra 以“节点对等、线性扩展”著称，但“易扩展”不等于“免运维”。本页覆盖部署、关键配置、监控、调优、扩缩容、备份恢复与常见坑，目标是把“按架构能跑”变成“生产稳跑”。

> 基线：Cassandra 5.0.9，支持 Java 11 与 Java 17。4.0 引入 Audit Logging，4.1 引入 Guardrails；Auto Repair 在 6.0 引入并 backport 到 5.0.8。

## Deployment

- **拓扑**：生产使用 `NetworkTopologyStrategy` + `GossipingPropertyFileSnitch`，每台机器声明 `dc`/`rack`（`cassandra-rackdc.properties`）。
- **单 DC / 多 DC**：多 DC 在 keyspace 中分别配置 RF；普通写默认只等待声明 CL 覆盖的 replica，跨 DC 不会自动形成全局同步写。需要跨 DC 等待时显式使用 `EACH_QUORUM` 等 CL，并接受可用性代价。
- **Kubernetes**：cass-operator 管理 bootstrap、seed、StatefulSet/PVC 和备份集成；`num_tokens`、PVC 容量与故障域必须按集群规模规划。
- **JVM**：5.0.9 的 `java.supported` 为 `11,17`，默认构建 JDK 为 11；不是“必须 JDK 17”。GC 仍是运维重点，G1 为主，超大堆需同时评估指针压缩、off-heap 与暂停时间。
- **配置 profile**：标准 `cassandra.yaml` 仍是 BIG SSTable + SkipList memtable + STCS；Trie memtable 与 UCS 可由 profile/表配置选择，BTI 由全局 `sstable.selected_format: bti` 显式选择。三者都不是版本号自动解锁的默认值。

## Key Configuration

| 配置 | 5.0.9 基线 / 说明 |
| --- | --- |
| `seeds` | 初始发现用的 seed 节点列表，不是永久单点 |
| `listen_address` / `rpc_address` | internode / 客户端监听地址 |
| `num_tokens` | 每节点 vnode 数，标准默认 **16** |
| `concurrent_reads` / `concurrent_writes` | 读写并发，按核、内存和磁盘调 |
| `memtable_flush_writers` / `memtable_heap_space` | flush 并发与 memtable 预算 |
| `compaction_throughput` | compaction 总限速，默认 **64MiB/s**；旧 `compaction_throughput_mb_per_sec` 已弃用 |
| `commitlog_sync` / `commitlog_sync_period_in_ms` | CommitLog 持久性模式；`periodic` 默认周期 10000ms |
| `hinted_handoff_enabled` / `max_hint_window` | hint 开关与保留窗口 |
| `authenticator` / `authorizer` | 认证/授权，见 [Security](/docs/CS/DB/Cassandra/Security.md) |
| `auto_repair.enabled` | 5.0.8+ 调度开关；启用前还需 JVM property 创建 schema |

`storage_compatibility_mode` 控制存储与消息格式兼容，不统一门控 SAI；滚动升级时要分别核对 SSTable/memtable 格式、索引和消息版本。

## Monitoring

- **JMX / MBeans** 是核心：读延迟、写延迟、pending compaction、hinted handoff、tombstone scan、thread pool 阻塞等。
- 生产常用 **cassandra-exporter + Prometheus + Grafana** 采集。除 p99 延迟外，还应覆盖：
  - `ReadLatency` / `WriteLatency`：分别看 coordinator、table 和 percentile；
  - `PendingCompactions` / `CompactionBytes`：积压预示读放大和 disk 压力；
  - `TombstoneScannedHistogram`：墓碑过多会拖垮读；
  - `HintedHandoffPending` / transient replication pending：长期不可用 replica 的积压；
  - CommitLog sync lag / waiting-on-sync：`periodic` 模式落盘滞后；
  - `MemtablePool.BlockedOnAllocation`：flush 跟不上写入；
  - streaming / repair 进度与 anticompaction：扩容和反熵期间的 IO 峰值；
  - GC pause、heap/off-heap、磁盘队列与 saturation：解释尾延迟根因；
  - `TimeoutException` / `UnavailableException` / `ReadTimeoutException`：区分慢、副本不足和超时。
- **Guardrails（4.1+）**：可配置表数量、分区大小、查询复杂度、无 partition 索引查询等软硬限制，提前拦截危险操作。

### Key nodetool Commands

| 命令 | 用途 |
| --- | --- |
| `nodetool status` / `info` | 拓扑、状态、负载、heap 与 token |
| `nodetool gossipinfo` / `describecluster` | gossip endpoint state 与集群元数据 |
| `nodetool compactionstats` / `tablestats` / `tablehistograms` | compaction 积压、表级统计与分布 |
| `nodetool repair` | 手动反熵 repair，详见 [Distributed](/docs/CS/DB/Cassandra/Distributed.md) |
| `nodetool snapshot` / `clearsnapshot` | 一致快照（硬链接）与清理 |
| `nodetool rebuild` | 从其它 DC 拉数据重建本节点 |
| `nodetool bootstrap resume` / `decommission` / `removenode` | 恢复中断的 bootstrap、拓扑变更与数据流式迁移 |
| `nodetool upgradesstables` | 重写旧版本 SSTable；`-a` 包含当前版本文件 |
| `nodetool verify` | 校验 SSTable 完整性，适合排查磁盘/文件损坏 |

**虚拟表（4.0+）**：`system_views.*` / `system.*` 把运维指标、节点状态甚至日志暴露成可查询的 CQL 表（如 `system_views.metrics`、`system_views.pending_compactions`、`system_views.system_logs`），便于监控集成；`StorageServiceMBean` / `StorageProxyMBean` 仍是 JMX 核心接口。

## Auto Repair

5.0.8 backport 的 Auto Repair 采用两阶段启用：

1. 启动前添加 JVM property `-Dcassandra.autorepair.enable=true`。它创建 `auto_repair` schema 列以及 `auto_repair_history` / `auto_repair_priority` 表，**该 property 不可逆**。
2. 再在 `cassandra.yaml` 设置 `auto_repair.enabled: true`，或通过 JMX 动态启用调度。只完成第一步不会自动开始调度。

- Full repair 默认 `min_repair_interval` 为 `24h`；incremental repair 默认关闭。
- 在已有大型集群首次启用 incremental repair 前，应先完成一轮 full repair，并评估 anticompaction 与 SSTable overlap；不要把“标记为 repaired”当作强一致需求的替代品。
- incremental repair 启用后要持续运行，否则 repaired/unrepaired SSTable 分离会扩大后续 anticompaction 成本。
- Auto Repair 不是“永不积压”的保证；仍需监控 repair session、assignment 大小、compaction 与 streaming 资源。

## Tuning

- **堆与 GC**：避免盲目扩大堆；超过约 31GiB 会失去 compressed oops 优势。off-heap 结构可缓解堆压力，但不能消除 GC 与容量规划。
- **CommitLog**：`periodic` 用吞吐换持久性窗口，`batch`/`group` 用延迟换更强确认语义。调优前先确认 RPO，不能只看写入 p99。
- **Compaction**：按表选策略，详见 [Compaction](/docs/CS/DB/Cassandra/Compaction.md)；同时观察 pending、写放大和 tombstone purge。提高 throughput 会增加前台 IO 争用。
- **读写并发**：`concurrent_*` 与磁盘数/核数对齐；客户端连接数由驱动连接池控制，不要靠无限增大线程池解决。
- **大分区**：用桶化打散，见 [Data Model](/docs/CS/DB/Cassandra/DataModel.md)；否则 compaction、tombstone scan 与 GC 会相互放大。
- **修复**：repair 周期必须短于 `gc_grace_seconds`，避免墓碑被 purge 后旧值复活。5.0.8+ 可启用 Auto Repair，但不能取消监控。

## Scale

- **加节点**：新节点 `bootstrap`，从现有 replica 经 streaming 拷贝其 range；TokenAware 驱动会把后续请求路由到新 replica。增加 RF 后还要执行 full repair 补齐既有数据。
- **减节点**：`nodetool decommission` 会迁移本节点 range 后下线；`removenode` 用于节点已不在的场景，不能随意互换。
- **zero-copy**：4.0+ streaming 可对完整 coverage 的 SSTable 使用 whole-file zero-copy；legacy counter shards、pre-4.0 Bloom filter 等不满足条件时会回退。TLS 路径使用 64KiB 缓冲复制，不等于 zero-copy。
- 扩缩容无需停机，但短期会抬升 streaming、compaction 与 replica 读放大；应限制后台任务并发并观察磁盘 saturation。

## Backup and Restore

- **快照**：`nodetool snapshot` 对各表生成硬链接式一致快照，创建成本低，但必须把数据、schema 与配置复制到节点外，硬链接本身不是异地备份。
- **增量**：`incremental_backups` 配合 snapshot 和对象存储，可降低备份窗口；要验证保留策略与实际可恢复点。
- **工具**：Medusa（社区），或自研“snapshot + `sstableloader` 恢复”。恢复前确认 Cassandra 版本、partitioner、schema 与 SSTable 格式兼容。
- **恢复后**：用 repair 对齐副本，并检查 tombstone、TTL、repair history 与索引状态。恢复流程必须定期演练，否则备份只是心理安慰。

## Common Pitfalls

- 用 `ALLOW FILTERING` 做无界过滤；它不一定全集群扫描，但仍可能产生大范围广播。
- 超大/无界 partition，或用集合承载无界历史。
- 长期不 repair，导致墓碑 purge 后旧值复活、副本分歧。
- 把 LWT 当普通事务高频使用；Paxos v1 写约四轮往返，v2 虽减少往返仍是单 partition CAS。
- 用 Materialized View 做核心链路；5.0.9 中 experimental 且默认关闭，见 [CQL](/docs/CS/DB/Cassandra/CQL.md)。
- 把 logged batch 当成跨分区 ACID；它依赖 batchlog 恢复，不是 2PC。
- `ALL` / `EACH_QUORUM` 写导致一个 replica 抖动就超时。
- 假设所有 streaming 都 zero-copy，或假设 TLS 也走零拷贝。
- 只升级版本号而不核对 standard/latest profile、`storage_compatibility_mode` 与滚动升级约束。

## Source Map

| 机制 | 5.0.9 落点 |
| --- | --- |
| JDK 支持 | `build.xml:41-48` |
| vnode 默认 | `conf/cassandra.yaml:42` |
| compaction throughput | `conf/cassandra.yaml:1251`、`Config.java:335-337` |
| MV / SASI 默认关闭 | `conf/cassandra.yaml:1979-1992` |
| Auto Repair 两阶段启用 | `doc/modules/cassandra/pages/managing/operating/auto_repair.adoc:39-50` |
| storage compatibility | `utils/StorageCompatibilityMode.java` |

## Links

- [Cassandra](/docs/CS/DB/Cassandra/Cassandra.md)
- [Replication](/docs/CS/DB/Cassandra/Replication.md)
- [Consistency](/docs/CS/DB/Cassandra/Consistency.md)

## References

- [Cassandra Managing](https://cassandra.apache.org/doc/5.0/cassandra/managing/index.html)
- [Cassandra Metrics](https://cassandra.apache.org/doc/5.0/cassandra/managing/operating/metrics.html)
- [Cassandra Auto Repair](https://cassandra.apache.org/doc/5.0/cassandra/managing/operating/auto_repair.html)
- [Cassandra 5.0.9 Source](https://github.com/apache/cassandra/tree/cassandra-5.0.9)
