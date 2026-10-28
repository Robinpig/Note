## Introduction

Druid 的生态位可以这样理解：**它不是数据湖格式，而是一个「被查询的服务」**——数据经它进来、由它服务查询，外部世界通过客户端、BI 工具、查询引擎三种方式与它交互。这决定了它的生态形状：写入侧靠 Kafka/Kinesis 原生 supervisor + SQL 摄取兜住一切，读取侧靠 JDBC/SQL 通用接口 + 各 BI 的专用连接器，跨引擎共享则要显式导出（或走 Iceberg/Delta 扩展）。本页按「进、出、连、比」四条线展开。

## Getting Data In

- **流摄取原生路径**：Apache Kafka 与 Amazon Kinesis 的 indexing service 是官方一等公民（exactly-once），这是 Druid「实时」口碑的来源；RabbitMQ 有 contrib 的 indexing service。
- **批摄取兜底一切**：任何能落到 S3/HDFS/GCS/Azure/HTTP 的文件（CSV/JSON/Parquet/ORC/Avro/Protobuf）都可以 native batch 或 SQL `INSERT ... SELECT`（`EXTERN()` 函数直接读外部文件）入湖。
- **湖仓直读**：`druid-iceberg-extensions` 与 `druid-deltalake-extensions` 支持把 Iceberg/Delta 表摄取进 Druid（31.0.0 起两者都增强过）。
- **上游加工层**：Spark/Flink/CDC（如 canal）通常把结果写 Kafka 或对象存储，再由 Druid 摄取——Druid 不试图取代流处理框架，它消费它们的输出。
- **Web 控制台数据加载向导**：分步生成摄取规格，支持 S3/GCS/Azure/Kafka/Kinesis 源；38.0.0 起可把流 supervisor 一键转成 SQL 摄取（「Convert supervisor to SQL」）。

## Querying From Outside

| 形态 | 说明 |
| :--- | :--- |
| 原生 JSON API | `/druid/v2/` 下的 POST 查询，六种查询类型，灵活性最高 |
| SQL API | `/druid/v2/sql`，与 JSON API 同权；MSQ/Dart 也走这个入口 |
| JDBC 驱动 | Druid 官方 JDBC driver，BI 工具的标准接法 |
| 多语言客户端 | Python `pydruid` 等社区客户端；R/Go/Node 各有绑定 |
| 系统表 | `sys.segments` / `sys.servers` / `sys.tasks` / `sys.supervisor` / `sys.queries`（Dart，实验性）用 SQL 查集群自身状态 |

38.0.0 起 `bin/run-java` 会优先读 `DRUID_JAVA_HOME`/`JAVA_HOME`，容器镜像里换 JDK 不必改脚本。

## BI and Visualization

- **Apache Superset**：与 Druid 血缘最深的开源 BI（同社区推动），原生 Druid 连接器，是把 Druid 当看板后端的默认选择。
- **Grafana**：经 JSON 数据源或社区插件连 Druid，运维/指标看板常见组合。
- **Metabase / Tableau**：都有 Druid 驱动/连接器；Tableau 侧 29.0.0 专门改过 INNER JOIN 规划以适配它的查询形状（任意连接条件下推为 join 后过滤）。
- **Imply Pivot / Polaris**：Druid 创始团队的公司提供的商业 UI 与全托管云，是「不想自己运维集群」的路线；与自建 Apache Druid 共享同一引擎。
- **Druid Web 控制台**：自带查询/数据加载/集群管理界面（由 Router 托管），不做重可视化，但足够运维与调试。

## Querying Druid From Other Engines

反向集成同样存在，用于「Druid 是数仓一域」的组织：

- **Trino / Presto**：官方 `druid` 连接器把 Druid 数据源当外表联邦查询——数仓团队用一套 SQL 横跨 Hive/Iceberg/Druid。
- **Apache Flink**：社区 `flink-connector-druid` 做流写。
- **Spark**：读写都有社区方案，但生产里更常见的是「Spark 写 Parquet/Kafka → Druid 摄取」的间接路线。

联邦查询的代价是下推能力有限：Druid 侧能推的只有时间过滤与简单投影，重聚合仍在引擎侧发生。

## Positioning Against Neighbors

| 对比 | 关键差异 |
| :--- | :--- |
| vs [ClickHouse](/docs/CS/DB/ClickHouse.md) | Druid：多角色集群 + 松耦合摄取，实时摄取与弹性是卖点；ClickHouse：单体极致扫描性能 + 极简部署 |
| vs Apache Pinot | 架构最近亲（都是实时 OLAP + 段存储）；Pinot 与 Kafka 耦合更深、部署面更窄 |
| vs [Timeseries](/docs/CS/DB/Concept/Timeseries.md) 系（InfluxDB/GreptimeDB 等） | Druid 是通用事件 OLAP，时序只是其一种数据；TSDB 在时序函数与压缩上更专 |
| vs [Presto](/docs/CS/DB/Presto.md) / Trino | Presto 不存数据只做联邦；Druid 存算一体、为固定形状高 QPS 查询优化 |
| vs [DuckDB](/docs/CS/DB/DuckDB/DuckDB.md) | DuckDB 是进程内单机分析；Druid 是分布式服务 |
| vs [Doris](/docs/CS/DB/Doris.md) | Doris 是兼容 MySQL 协议的 MPP 数仓、Join 能力强；Druid 是时序分区 OLAP、摄取实时性强 |

## Links

- [Druid](/docs/CS/DB/Druid/Druid.md)
- [Ingestion](/docs/CS/DB/Druid/Ingestion.md)
- [Query Engine](/docs/CS/DB/Druid/Query_Engine.md)
- [Kafka](/docs/CS/MQ/Kafka/Kafka.md)
- [SQL Engine](/docs/CS/BigData/SQL_Engine.md)

## References

1. [Apache Superset](https://superset.apache.org/)
2. [Druid SQL API](https://druid.apache.org/docs/latest/querying/sql/)
3. [Trino Druid Connector](https://trino.io/docs/current/connector/druid.html)
4. [Imply](https://imply.io/)
