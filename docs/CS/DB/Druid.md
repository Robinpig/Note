## Introduction

[Apache Druid](https://druid.apache.org/) 是面向**实时分析（OLAP）**的分布式数据存储，为大规模事件数据上的低延迟切片（slice-and-dice）查询设计：亚秒级响应、高并发（每秒数百到十万次查询）、实时摄取与即席查询并存。它与「先建数仓、再跑报表」的路线相反——数据到达即可查，查询前不需要预定义或缓存查询本身。

三条常被忽略的底色：

- **不可变的分片（segment）是唯一存储单位**。数据按时间分区、按列组织、字典编码 + 位图倒排，写入后不再修改；更新靠生成新版本分片替换旧版本，天然形成一套基于分片版本的 MVCC。分片也是分发与复制的单位，这让「加机器 = 加分片副本」成为可能。
- **摄取与查询解耦，中间夹着一层深存储（deep storage）**。S3/HDFS/GCS/Azure 存放分片文件，MySQL/PostgreSQL 存放元数据，计算节点无状态地从深存储拉取分片。存算分离带来弹性，也带来「分片加载」这个 Druid 特有的运维面。
- **集群是一组松耦合角色，而不是一个单体**。Coordinator 管分配、Overlord 管任务、MiddleManager/Peon 干活、Historical 服务分片、Broker 做查询的 scatter/gather、Router 做统一入口。理解 Druid 的多数困惑，本质是没分清「哪个角色负责什么」。

版本锚点：**38.0.0（2026-10-01 GA）**，前一个主要版本 **37.0.0（2026-05-08）**。38 起要求 **Java 21 或 25（推荐 25），Java 17 支持已移除**。存储格式默认 **v9**，v10 自 36.0.0 起以 `druid.indexer.task.buildV10=true` 实验性启用、与旧版互不兼容。所有结论以 druid.apache.org 官方文档与发布公告为准。

## Map of This Section

Druid 的知识可以按「一个查询进来会发生什么、一批数据进来会发生什么、之后怎么管」切成八个方向，也对应使用 Druid 时八种不同的翻车方式：

- **[Architecture](/docs/CS/DB/Druid/Architecture.md)**——「集群到底是什么形状」。六类进程角色、摄取/服务/查询三条链路、ZooKeeper 职责的收缩史（25→30→38 三代迁移）、元数据存储与深存储的分工，以及 Dart 引擎如何把查询拓扑改成「Broker 当控制器、Historical 当工人」。理解所有其他分册的地图。
- **[Storage_Format](/docs/CS/DB/Druid/Storage_Format.md)**——「分片文件里到底有什么」。`datasource_interval_version_partitionNum` 的段 ID 规则、字典/列表/位图三件套、LZ4 与 Roaring 压缩、smoosh 文件与 mmap 的 2 GB 上限、null 与多值列的编码、格式版本 v9→v10 的单向门，以及实验性的 projections（预聚合视图）。
- **[Query_Engine](/docs/CS/DB/Druid/Query_Engine.md)**——「查询怎么跑」。原生查询六种类型、基于 Calcite 的 SQL 层、三套引擎（native / MSQ task / Dart）的分工与选型、scatter/gather 与结果缓存、join 的 broadcast 与 sortMerge 两条路、近似聚合（DataSketches）的精度换吞吐。
- **[Ingestion](/docs/CS/DB/Druid/Ingestion.md)**——「数据怎么进来」。摄取规格的五段结构、批摄取（native batch 与 SQL-based ingestion）、流摄取（Kafka/Kinesis supervisor 与 exactly-once）、输入源与输入格式矩阵、Hadoop 摄取在 37.0.0 的整体移除、自动 schema 发现与 rollup。
- **[Data_Management](/docs/CS/DB/Druid/Data_Management.md)**——「数据之后怎么管」。负载/淘汰规则、tier 与优先级、压实（compaction）从 coordinator-issued 到 compaction supervisor（37 GA）的换代、minor compaction 与 cascading reindexing、再均衡与分片加载，以及「更新 = 换版本分片」这条 immutable 铁律的下游后果。
- **[Extensions](/docs/CS/DB/Druid/Extensions.md)**——「能力从哪来」。core 与 contrib 两级扩展、`loadList` 与 `pull-deps` 加载机制、深存储/元数据存储/安全/查询时函数/湖仓/部署各组件的清单，以及哪些能力已经进核心（如 35.0.0 起 MSQ 不再是扩展）。
- **[Ecosystem](/docs/CS/DB/Druid/Ecosystem.md)**——「数据从哪来、到哪去」。客户端与 API（原生 JSON、SQL、JDBC）、BI 与可视化生态（Superset/Grafana/Metabase/Imply）、外部查询引擎经 Trino/Presto 连接器反查 Druid、以及 MQ/Spark/Flink 侧的入湖路径。
- **[Operations](/docs/CS/DB/Druid/Operations.md)**——「怎么部署、怎么排障」。micro-quickstart 到集群到 Kubernetes 三种形态、JVM 与直接内存的关键旋钮、监控与系统表、安全基线、滚动升级的顺序约束与常见故障的排查次序。

## Applicable Scenarios

Druid 的甜点区可以用一句话概括：**事件流数据、按时间切片查询、高并发即席分析、读取远多于更新**。

适合：

- **用户行为与运营分析**：点击流、埋点、A/B 实验看板——高基数维度（用户 ID、页面 URL）上的即席 groupBy 是它的招牌场景。
- **实时监控与可观测性**：指标与日志事件的近实时聚合，秒级延迟可查，支持高 QPS 的固定看板查询。
- **广告投放与风控**：曝光/点击计费的实时报表、风控信号的时序聚合。
- **IoT 遥测**：设备指标的按时间降采样查询。

不适合：

- **OLTP 事务**：没有行级更新与多表事务，写入即不可变；Druid 不是 MySQL 的替代品。
- **强一致的单行读写**：`SELECT * FROM t WHERE id = ?` 这类点查不是设计目标（可用 lookups 做星型维表关联，但那是另一回事）。
- **超大规模多表 join**：广播 join 要求维表足够小；大表 join 要靠 Dart/sortMerge，但仍不如专用 MPP 数仓通用。
- **当数据湖格式用**：分片是 Druid 私有格式，别指望 Spark/Flink 直接读；跨引擎共享要走 SQL 导出或 Iceberg/Delta 扩展入湖。

| 条件 | 选择 |
| :--- | :--- |
| 事件流实时摄取 + 亚秒级即席聚合 | Druid |
| 极速扫描、部署简单、批量为先 | [ClickHouse](/docs/CS/DB/ClickHouse.md) |
| 纯时序、开源生态优先 | [Timeseries](/docs/CS/DB/Timeseries.md) 各产品 |
| 联邦查询、不搬数据 | [Presto](/docs/CS/DB/Presto.md) |
| 单机/嵌入式分析 | [DuckDB](/docs/CS/DB/DuckDB.md) |

## Facts Worth Pinning Down

最容易被默认值与版本坑到的几条，完整清单散布在各分册：

1. **ZooKeeper 的职责被三代版本逐步掏空**：25.0.0 起分片发现与任务管理默认改走 HTTP（`druid.serverview.type=http`、`druid.indexer.runner.type=httpRemote`）；30.0.0 移除 ZK 段加载；38.0.0 连 ZK 段公告与 ZK RemoteTaskRunner 也删了，配置里残留旧属性直接启动失败。**38.0.0 里 ZK 只剩三件事**：Coordinator/Overlord leader 选举、节点服务发现、Overlord→MiddleManager 任务管理；想彻底去掉 ZK 可换 37.0.0 引入的 `druid-consul-extensions`。
2. **Hadoop 摄取已经没有了**：34.0.0 起需显式 opt-in，37.0.0 整体移除。老集群上的 MapReduce 入湖任务必须改写成 SQL-based ingestion 或外部预写 Parquet。
3. **流摄取的 `parser` 在 37.0.0 被移除**，Kafka/Kinesis supervisor 必须改用 `ioConfig` 上的 `inputSource`/`inputFormat`，`dataSchema` 不能再指定 parser。升级前不改，supervisor 起不来。
4. **MSQ 任务引擎自 35.0.0 起是核心能力而非扩展**——`druid.extensions.loadList` 里还写着 `druid-multi-stage-query` 的集群必须删掉，否则未来版本无法启动。窗口函数 31.0.0 GA，Dart 引擎 31.0.0 引入且**至今仍是实验性**。
5. **分片大小的甜点区是 300–700 MB**，`targetRowsPerSegment` 建议从 500 万行起调；超了要么调粗 `segmentGranularity`、要么加分区。分片太大直接拖慢加载与查询。
6. **压实（compaction）在 37.0.0 换代**：compaction supervisor 成为 GA 与推荐默认，任务前缀从 `coordinator-issued` 改为 `auto`；元数据侧新增 `druid_indexingStates` 表，段只存 `indexing_state_fingerprint` 引用。
7. **`druid-histogram` 扩展已废弃**，近似分位数请用 `druid-datasketches` 的 quantiles 聚合器；sketch 可以在摄取时直接落库（`finalizeAggregations=false`），查询时再终结。
8. **Web 控制台由 Router 托管**（依赖 `druid.router.managementProxy.enabled` 与 `druid.sql.enable`），引擎选择有 Auto / SQL native / SQL MSQ task / SQL Dart 四档；未开认证时控制台权限等于运行 Druid 的系统用户，生产必须配安全。
9. **Druid Operator 在 37.0.0 迁出主仓**，独立仓库 `apache/druid-operator` 维护；K8s 部署除了 operator 还有 `druid-kubernetes-overlord-extensions`（不经 MiddleManager 直接起 task pod，37 GA）这条路。
10. **38.0.0 弃用 legacy ZSTD 帧（v0.4–v0.7）**，这是最后一个支持读取这些帧的大版本—— ingestion 链路里用老 zstd 压缩的数据要在升级前排雷。

## Links

- [Doris](/docs/CS/DB/Doris.md)
- [DB](/docs/CS/DB/DB.md)
- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)
- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)
- [Table Format](/docs/CS/BigData/Table_Format.md)

## References

1. [Apache Druid Documentation](https://druid.apache.org/docs/)
2. [Apache Druid 38.0.0 Release Notes](https://github.com/apache/druid/releases/tag/druid-38.0.0)
3. [Apache Druid 37.0.0 Release Notes](https://github.com/apache/druid/releases/tag/druid-37.0.0)
4. [Druid: A Real-time Analytical Data Store (original paper, SIGMOD 2014)](https://dl.acm.org/doi/10.1145/2588555.2595631)
5. [Apache Druid Upgrade Notes](https://druid.apache.org/docs/latest/release-info/upgrade-notes)
