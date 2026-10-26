# Apache Hive

## Introduction

Apache Hive 是构建在 [Hadoop](/docs/CS/Framework/Hadoop/Hadoop.md) 之上的**分布式、容错的数据仓库系统**，用类 SQL 的方言 HiveQL 读、写、管理驻留在分布式存储（HDFS / S3 / Ozone / ADLS / GCS）上的 PB 级数据。它把「分析师熟悉的 SQL」翻译成分布式执行计划，让不懂 MapReduce 的人也能在大数据上做分析——这是它 2007 年由 Facebook 发起、2010 年成为 Apache 顶级项目的初衷。

和 [HBase](/docs/CS/DB/HBase/HBase.md) 的对比最能说明定位：HBase 是低延迟在线点查的**宽表数据库引擎**，Hive 是高延迟离线的**数据仓库 / 批处理 SQL**。两者常见组合是 Hive 把 HBase 当外部表（`STORED BY 'org.apache.hadoop.hive.hbase.HBaseStorageHandler'`）——HBase 存明细并提供点查，Hive 出 SQL 做批量分析。

> [!NOTE]
> **2026 年的角色判断**：近十年不断有人预言 Hive「死了」，结论是「半对」。越来越少的新项目在 HiveServer2 上开交互式分析——[Spark SQL](/docs/CS/Framework/Spark/SQL.md)、[Trino](/docs/CS/DB/Presto.md)、Impala 接管了大部分曾经走 HS2 的查询。但**几乎所有这些引擎仍通过 Hive Metastore（HMS）找表**，大量夜间 ETL 仍以 HiveQL on Tez 运行。所以 Hive 实际的未来是「一分为三、命运分化」：**查询引擎（HS2 + Tez + LLAP）份额在缩，HMS 作为湖仓互操作层在扩张，ACID ORC / Iceberg 表格式继续存在**。给 Hive 选型时，先分清你要的是哪一个。HMS 为何能扩张成湖仓的互操作层、以及数据湖 → 数仓 → 湖仓这条演进线的完整叙述见 [Lakehouse](/docs/CS/BigData/Lakehouse.md)；Iceberg / Delta Lake / Hudi 三强表格式的横向对比与选型见 [Table Format](/docs/CS/BigData/Table_Format.md)。

## Version Notes

本页基线 **Hive 4.x**：4.2.1 为最新稳定（2026-08-25 发布，纯安全修复版），4.2.0（2025-11）、4.1.0（2025-07，独立 HMS + JDK 17）、4.0.0（2024-03）是 4.x 主要里程碑。**3.x 线已于 2024-10-08 EOL**（最终 3.1.3），1.x / 2.x 线也已 EOL，生产上应直接上 4.x。

4.x 相对 3.x 的关键断点（升级的主要工作量来源，详见 [Architecture](/docs/CS/DB/Hive/Architecture.md) 与 [Operations](/docs/CS/DB/Hive/Operations.md)）：

- **Hive on Spark 已移除**——`SET hive.execution.engine=spark` 在 4.x 直接不工作。
- **Hive on MapReduce 已弃用**——还在但不再投入性能，部分新特性只以 query-based compaction 跑。
- **旧 Hive CLI 已弃用**——编译器跑在客户端进程里、绕过 HS2 认证授权，被 Beeline 取代。
- **执行引擎收敛为 Tez 唯一**（详见 [Execution Engines](/docs/CS/DB/Hive/Execution_Engines.md)）。
- **JDK floor 从 8 跳到 21**（3.x → 4.2.x）；想停在 JDK 17 就锁 4.1 线。
- **Iceberg 成为一等公民表格式**（详见 [Iceberg Integration](/docs/CS/DB/Hive/Iceberg_Integration.md)）。
- **HMS 作为 standalone 组件发布**（4.1.0 起，binary + Docker 镜像）。

## Architecture and Components

Hive 的运行时由两半组成：**HiveServer2（HS2）** 负责把 HiveQL 编译、优化、提交到执行引擎；**Hive Metastore（HMS）** 是整个 Hadoop 生态的中央 schema 注册表，被 Hive、Spark、Impala、Trino 等共同消费，是现代湖仓事实上的互操作层。HS2 内部走「Parse → Semantic Analyze → Logical Plan → CBO Optimize → Physical Plan → Tez」的编译管线，执行层叠加 Tez DAG 与 LLAP 常驻缓存，客户端经 Beeline / JDBC 接入，Spark 侧通过 HWC 桥做事务读写。组件拓扑、编译流程、HMS 后端与高可用、4.x 三处移除/弃用的完整展开见 [Architecture](/docs/CS/DB/Hive/Architecture.md)。

## Data Model and Storage

Hive 的数据模型是「数据库 → 表 → 分区 → 分桶 → 行」的层级，落盘即「HDFS 目录即分区」。核心决策是 Managed 表 vs External 表（`DROP` 是否带数据）、分区裁剪、分桶与 SerDe 映射；存储格式则决定列存效率与是否支持 ACID——ORC 是 Hive 原生列存且 ACID 必需，Parquet 是跨引擎公约数。模型语义、分区/分桶/约束、StorageHandler，以及 ORC / Parquet 的内部结构与取舍，分别见 [Data Model](/docs/CS/DB/Hive/Data_Model.md) 与 [Storage Formats](/docs/CS/DB/Hive/Storage_Formats.md)。

## Query Language

HiveQL 是「接近 SQL、为 Hadoop 重新设计」的方言：DDL 表达力集中在 `PARTITIONED BY` / `CLUSTERED BY` / `STORED AS` / `STORED BY`；DML 里 `UPDATE` / `DELETE` / `MERGE` 只对 ACID 表可用；分析侧有 CTE、窗口函数、`LATERAL VIEW`、UDF / UDAF / UDTF 与 HPL/SQL；性能命门是 Apache Calcite 驱动的 CBO（4.0 升 1.25、4.1 升 1.33）与 `ANALYZE TABLE` 喂入的统计信息。语法细节、复杂类型与 MERGE 写法见 [HiveQL](/docs/CS/DB/Hive/HiveQL.md)。

## Transactions and Table Formats

Hive 3.0 重写的 ACID 2.0（4.x 延续）让 ORC 表支持 full ACID（MVCC + delta 文件 + 事务元数据落 HMS 后端），代价是 delta 堆积必须靠 minor / major / rebalance compaction 收敛，且 compaction 在 4.x 演进出 query-based 实现、池化调度与零等待读。另一边，Iceberg 作为开放表格式在 4.0 成为一等公民，使 Spark / Impala / Trino 无需格式转换即可读 Hive 写的 Iceberg 表——这是多引擎 lakehouse 的前提。两者机制与取舍见 [ACID and Transactions](/docs/CS/DB/Hive/ACID_and_Transactions.md) 与 [Iceberg Integration](/docs/CS/DB/Hive/Iceberg_Integration.md)。

## Execution Engines

HiveQL 的执行后端在 4.x 收敛为 **Tez 唯一**：Tez 用 DAG 取代 MR 的固定 map→reduce 阶段、容器跨 task 复用，典型查询比 MR 快 2~10 倍；LLAP 在其上叠加常驻执行 + 缓存守护进程把交互查询压到亚秒级。Spark 引擎在 4.0 被移除、MR 被弃用——迁移脚本必须确认 `hive.execution.engine` 不再被设成 `mr` / `spark`。引擎演进与对比见 [Execution Engines](/docs/CS/DB/Hive/Execution_Engines.md)。

## Security and Governance

认证侧 Kerberos 为主，4.0 起 HS2 / HMS 支持 SAML 2.0 / JWT（走 Thrift over HTTP）、Kerberos 与 LDAP 可并行开启；授权有三套模式——Metastore 上的 Storage Based Authorization、HS2 上的 SQL Standard Authorization、以及生产事实标准的 Apache Ranger（细粒度行列 masking + 审计）。4.2.1 是一次纯安全修复版，修了三个 CVE（HMS direct-SQL 注入、HS2 SAML bearer 绕过、Avro SerDe SSRF）。完整威胁面与防护见 [Security and Governance](/docs/CS/DB/Hive/Security_and_Governance.md)。

## Operations and Deployment

生产上 Hive 有三档部署模式（embedded / local / remote metastore），remote 是标准；HMS 与 HS2 各自可高可用（多 HMS active/active 共享后端 RDBMS、HS2 经 ZooKeeper 动态服务发现）。4.1 起 HMS 有 standalone binary + Docker 镜像，可独立于 HS2 部署。升级 3.x → 4.x 要处理 metadata-only upgrade、统计信息、compaction 与 on-spark/on-mr 脚本迁移，并留意 JDK floor（4.2 要求 JDK 21 无处不在）。部署、HA、升级与监控见 [Operations](/docs/CS/DB/Hive/Operations.md)。

## Hive and HBase

两者常被放到一起选，但边界清晰：

| | Hive | HBase |
| :--- | :--- | :--- |
| 类型 | 数据仓库 / 批处理 SQL | 宽表（列族）NoSQL 数据库 |
| 执行 | Tez（4.x 唯一），早期 MR | 自研 RegionServer 引擎 |
| 延迟 | 高（批） | 低（点查 / 范围扫描） |
| 写入模型 | 批量导入 + ACID（ORC） | 在线低延迟写、单行原子 |
| 读模型 | 全表 / 分区扫描、SQL 聚合 | 按 RowKey 点查与范围扫描 |
| 典型定位 | PB 级离线 ETL、报表 | 超宽画像 / 明细在线存 |

组合用法：Hive 用 `HBaseStorageHandler` 把 HBase 表映射为外部表，用 SQL 批量分析 HBase 里的明细；反过来，需要实时按主键取数时不该用 Hive，该直接用 HBase（或 HBase + Phoenix 拿 SQL 与二级索引）。把两者当同一件事替换，是选型阶段最常见的事故。

## Comparison with Other SQL Engines

| | Hive (Tez) | [Trino](/docs/CS/DB/Presto.md) / Presto | Spark SQL | Impala |
| :--- | :--- | :--- | :--- | :--- |
| 定位 | 批处理 ETL 主力 | 联邦查询（跨数据源） | ETL / ML | 交互式 BI（MPP，最低延迟） |
| 元数据 | 自有 HMS，也服务别人 | 经 HMS / 各 connector | 经 HMS / 自有 catalog | 经 HMS |
| 延迟 | 分钟级 ~ 小时级 | 秒级 ~ 分钟级 | 秒级 ~ 分钟级 | 亚秒 ~ 秒级 |
| 表格式亲密度 | ORC / Iceberg 最深 | 各 connector 通用 | Parquet / Iceberg 最深 | Parquet / Kudu |
| 典型场景 | 夜间 ETL、复杂变换、ACID 托管表 | 跨 RDBMS / 对象存储联邦 | 批 + 流 + ML 一体 | 预聚合上的交互仪表盘 |

一句话：**查询复杂度、ACID 保证、长时批处理 > 亚秒延迟时选 Hive；交互式 BI 选 Impala / Trino；既有 Spark 栈做 ETL / ML 选 Spark SQL。** 三者往往共存：Hive 管 schema 与批写，Trino / Impala 管交互读，Spark 管流与 ML。

## When to Use

适合：PB 级批量 ETL 与复杂转换、需要 ACID 的托管表、Hadoop 生态内已用 HMS 作 catalog、Hive-on-Tez 能覆盖的长时查询、需要 Iceberg 多引擎共享又想保留 Hive 写路径。

不适合：亚秒级交互查询（交给 Impala / Trino）、流式写入与实时计算（交给 Flink / Spark Streaming）、纯新项目且只要 OLAP——此时直接 Iceberg + Trino 的湖仓一体往往比再起一套 HiveServer2 更轻。

## Links

- [DataBases](/docs/CS/DB/DB.md)
- [HBase](/docs/CS/DB/HBase/HBase.md)
- [Cassandra](/docs/CS/DB/Cassandra/Cassandra.md)
- [MapReduce](/docs/CS/Framework/Hadoop/MapReduce.md)
- [Yarn](/docs/CS/Framework/Hadoop/Yarn.md)
- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)

## References

1. [Apache Hive](https://hive.apache.org/)
2. [Apache Hive Downloads / Release Notes](https://hive.apache.org/general/downloads)
3. [Hive 4.0 - Overview of Major Changes](https://hive.apache.org/docs/latest/overview-of-major-changes/)
4. [Apache Software Foundation Announces Apache Hive 4.0](https://news.apache.org/foundation/entry/apache-software-foundation-announces-apache-hive-4-0)
5. [Hive 4 Key Features (4.0 to 4.2), in depth](https://www.aicassindra.com/blogs/hive_impala/hive_4_features.html)
6. [Hive 3 to Hive 4 upgrade and end-of-life](https://www.osseva.io/blog/hive-3-to-4-upgrade)
7. [Apache Hive Overview (ODP, ships Hive 4.0.1)](https://www.opensourcedataplatform.com/docs/1.3.1.0/concepts/hive-overview)
8. [[ANNOUNCE] Apache Hive 4.2.1 Released](https://lists.apache.org/thread/pc3jr2mj1ycmnf0cod7424qzhz94447p)
