## Introduction

Apache Hive 是构建在 [Hadoop](/docs/CS/Framework/Hadoop/Hadoop.md) 之上的**分布式、容错的数据仓库系统**，用类 SQL 的方言 HiveQL 读、写、管理驻留在分布式存储（HDFS / S3 / Ozone / ADLS / GCS）上的 PB 级数据。它把「分析师熟悉的 SQL」翻译成分布式执行计划，让不懂 MapReduce 的人也能在大数据上做分析——这是它 2007 年由 Facebook 发起、2010 年成为 Apache 顶级项目的初衷。

和 [HBase](/docs/CS/DB/HBase.md) 的对比最能说明定位：HBase 是低延迟在线点查的**宽表数据库引擎**，Hive 是高延迟离线的**数据仓库 / 批处理 SQL**。两者常见组合是 Hive 把 HBase 当外部表（`STORED BY 'org.apache.hadoop.hive.hbase.HBaseStorageHandler'`）——HBase 存明细并提供点查，Hive 出 SQL 做批量分析。

> [!NOTE]
> **2026 年的角色判断**：近十年不断有人预言 Hive「死了」，结论是「半对」。越来越少的新项目在 HiveServer2 上开交互式分析——[Spark SQL](/docs/CS/Framework/Spark/SQL.md)、[Trino](/docs/CS/DB/Presto.md)、Impala 接管了大部分曾经走 HS2 的查询。但**几乎所有这些引擎仍通过 Hive Metastore（HMS）找表**，大量夜间 ETL 仍以 HiveQL on Tez 运行。所以 Hive 实际的未来是「一分为三、命运分化」：**查询引擎（HS2 + Tez + LLAP）份额在缩，HMS 作为湖仓互操作层在扩张，ACID ORC / Iceberg 表格式继续存在**。给 Hive 选型时，先分清你要的是哪一个。

版本口径：本页基线 **Hive 4.x**（4.2.1 为最新稳定，2026-08 发布；4.0.0 是 2024-03 的重大版）。**3.x 线已于 2024-10-08 EOL**（最终 3.1.3），1.x / 2.x 线也已 EOL，生产上应直接上 4.x。

## Architecture

```
Client(Beeline/JDBC/ODBC) --> HiveServer2(HS2)
                                 |-- Compiler + CBO(Apache Calcite)
                                 |-- 提交执行到 YARN
                                        |
                                        v
                                   Tez DAG (+ LLAP daemons) --> HDFS / S3 / Ozone
                                        |
                                        v  (旁路元数据)
                                   Hive Metastore(HMS, Thrift API) <-- Spark / Impala / Trino / Flink 也来读
```

- **HiveServer2 (HS2)**：接受 HiveQL 的 JDBC / ODBC 服务，把查询编译成逻辑计划、经 CBO 优化后提交到 YARN 执行。多租户、支持并发会话与会话级隔离，是 BI 工具接入的入口。**4.0 起 HS2 支持 SAML 2.0 / JWT 认证、Kerberos 与 LDAP 可并行开启、支持 Thrift over HTTP（JWT 认证）与优雅关闭**。
- **Hive Metastore (HMS)**：整个 Hadoop 生态的**中央 schema 注册表**，存 database / table / partition / column 定义、SerDe 信息、表统计、Iceberg 属性。它暴露 Thrift API，被 Hive、Spark、Impala、Trino 等消费，是现代湖仓事实上的**互操作层**。**4.1.0 起 HMS 作为 standalone 组件发布（binary + Docker 镜像）**，后端仍落到关系库（MySQL / PostgreSQL / Oracle）；4.0 还加了基于 ZooKeeper 的服务发现与 Thrift over HTTP。
- **执行引擎**：4.x 里 **Tez 是唯一受支持的执行引擎**（默认）。Tez 是 DAG 框架，消除 MR 阶段间写 HDFS 的步骤、中间数据存内存或本地盘、复用 JVM 容器，典型分析查询比 MapReduce 快 2~10 倍。
- **LLAP**（Low Latency Analytical Processing）：常驻守护进程 + 优化的数据缓存，提供亚秒级交互查询；持久化查询基础设施让热数据不必每次从存储拉起。
- **Beeline**：官方 JDBC 客户端，取代老 `hive` CLI。**4.0 起旧 Hive CLI 已被弃用**——它把编译器跑在客户端进程里，绕过 HS2 的认证与授权。
- **HWC（Hive Warehouse Connector）**：让 Spark 应用以完整事务语义读写 Hive ACID / Iceberg 表的桥；不通过 HWC 时 Spark 走兼容层、会绕过 ACID 语义。

> [!WARNING]
> **4.x 的三处移除 / 弃用是升级的主要工作量来源**：
> 1. **Hive on Spark 已移除**——`SET hive.execution.engine=spark` 在 4.x 直接不工作，这类作业全部迁到 Tez 或改用 Spark SQL 读同一批 metastore 表。
> 2. **Hive on MapReduce 已弃用**——还在但不再做性能投入，部分新特性（如 rebalance compaction）只以 query-based compaction 跑，应视作迁移目标而非回退项。
> 3. **JDK floor 从 8 跳到 21**（3.x → 4.2.x）——每个为 Java 8 编译的 UDF jar、SerDe、自定义 hook 都要重编重测。想停在 JDK 17 就把上限锁在 4.1 线，4.2 要求 JDK 21 无处不在（HS2、metastore、嵌入 Hive 库的客户端）。

## Data Model

Hive 的数据模型是「数据库 → 表 → 分区 → 分桶 → 行」的层级，落盘结构是「HDFS 目录即分区」。

- **Database / Schema**：命名空间，默认 `default`。
- **Managed Table（内部表）vs External Table（外部表）**：核心差异在 `DROP`。Managed 表 `DROP` 同时删元数据**和**数据；External 表（`EXTERNAL` 关键字，`LOCATION` 指向已有数据）`DROP` 只删元数据、数据原样保留——外部表常用来把 HBase、已存在的 HDFS 目录「映射」进 Hive。
- **Partition（分区）**：按某列（通常是日期 / 地域）切分，每张分区是 HDFS 上一个子目录。查询带分区谓词时走**分区裁剪（partition pruning）**，跳过无关目录，是 Hive 最大的提速手段之一。分区可静态 / 动态（`hive.exec.dynamic.partition`）。
- **Bucket（分桶 / Clustering）**：对列做哈希、把数据分成固定数量的桶文件（`CLUSTERED BY ... INTO N BUCKETS`），用于采样、map-side join 与更细的分布控制。
- **SerDe（Serializer / Deserializer）**：决定行如何与文件字节互转。内置 `LazySimpleSerDe`（文本）、`AvroSerDe`、`ORCSerDe`、`ParquetHiveSerDe`、`OpenCSVSerDe`、`RegexSerDe`、JSON 处理等；4.2.1 修了 Avro SerDe schema URL 处理的安全漏洞（不要信任用户提供的 schema URL）。
- **StorageHandler**：把非原生存储（如 HBase、Iceberg、Kafka）挂成 Hive 表——`STORED BY` 后面跟 Handler 类。

## Storage Formats

| 格式 | 特点 | 适用 |
| :--- | :--- | :--- |
| **ORC** | Hive 原生列存，自带轻量索引、谓词下推、**ACID 事务必需** | Hive 托管表、ACID、向量化读 |
| **Parquet** | 跨引擎通用列存（Spark / Impala / Trino 一等公民） | 多引擎共享、湖仓 |
| **TextFile** | 默认但最慢，无压缩 / 无列裁剪优势 | 临时导入、方便人类读 |
| **Avro** | 行存、schema 演化友好 | 数据交换、流式 |
| **RCFile / SequenceFile** | 早期格式，基本被 ORC / Parquet 取代 | 历史兼容 |

ORC 与 Parquet 的取舍：ORC 与 Hive 生态（ACID、向量化执行、统计信息）绑定更深，是 Hive 托管表的默认选择；Parquet 在 Spark / Impala 侧更通用，是多引擎 lakehouse 的公约数。两者都是列存 + 块级压缩 + 谓词下推，和「宽列存储（BigTable / HBase 那种列族内行存）」不是一回事——列存把同列跨行压在一起面向扫描聚合，见 [DataBases](/docs/CS/DB/DB.md) 的 Row Versus Column-Oriented。

## HiveQL

HiveQL 是「接近 SQL 但为 Hadoop 重新设计」的方言，由编译器翻译成 Tez DAG 执行。与标准 SQL 的关键差异：

- **DDL 表达力更强**：`PARTITIONED BY`、`CLUSTERED BY ... SORTED BY ... INTO N BUCKETS`、`STORED AS <fmt>`、`STORED BY <handler>`（Iceberg / HBase）、`LOCATION`。
- **DML 的 ACID 前提**：`UPDATE` / `DELETE` / `MERGE`（upsert）**只对 ACID 表（ORC + 事务属性）可用**；非 ACID 表仍只能 `INSERT`（含 `INSERT OVERWRITE`）、`LOAD DATA`。这是早期 Hive「只支持导入和查询」说法的来源，但 3.0+ 重写后已不再是硬限制。
- **分析能力**：CTE（`WITH`）、窗口函数（`OVER (PARTITION BY ... ORDER BY ...)`）、`LATERAL VIEW` 展开、UDF / UDAF / UDTF 三类自定义函数、`HPL/SQL`（存储过程方言）。
- **CBO 驱动的重写**：基于 Apache Calcite 的成本优化器（4.0 升到 Calcite 1.25，4.1 升到 1.33）会自动把符合条件的查询重写成物化视图、做 join 重排与列裁剪；`ANALYZE TABLE ... COMPUTE STATISTICS` 喂给优化器的统计信息是性能命门。

> [!NOTE]
> HiveQL 不追求完整实现 SQL 标准，它更在意「能把声明式查询翻译成分布式批处理」。需要标准 SQL 互操作、子查询完全兼容、存储过程体系时，应改用 Spark SQL / Trino，或至少确认目标语法的 Hive 支持矩阵——把 HiveQL 当成「SQL-ish 的 ETL 语言」比当成「关系库 SQL」更不容易踩坑。

## ACID and Transactions

Hive 3.0 对事务做了重写（ACID 2.0），4.x 延续并改进。要点：

- **范围**：**ORC 表支持 full ACID**（`INSERT` / `UPDATE` / `DELETE` / `MERGE`），其它格式仅 `insert-only` 事务；ACID 在 Hive 4 的 managed 表上默认开启。
- **机制**：`DbTxnManager` 管理事务、`LockManager` 管理锁；读走 **MVCC**（多版本并发控制），写产生 **delta 文件**（写时复制 COW 模式），读不阻塞写；事务元数据落在 HMS 后端的关系表里（`txns`、`txn_components`、`completed_txn_components`）。
- **Compaction**：delta 文件会不断堆积，必须靠 **minor compaction**（合 delta）/ **major compaction**（合 base + delta 并清墓碑）收敛，否则读放大失控——Hive 4 还加了 **rebalance compaction** 与 **compaction pooling / 优先级**（按池调度 compaction worker）。
- **代价**：小文件（delta）膨胀是结构性问题；ACID 表与非 ACID 表、managed 与 external 的语义差异要在建表时想清楚，混用会出现「删了数据还看得到」这类由未 compaction 的 tombstone 导致的困惑。

## Iceberg Integration

4.0 起 **Apache Iceberg 成为一等公民表格式**，是 Hive 4 最大的功能性变化：`STORED BY ICEBERG` 声明后，普通 HiveQL 即可对该表做行级 `DELETE` / `UPDATE` / `MERGE`，并支持向量化读写。

- **4.0 基础**：snapshot 管理、branches & tags、DML（含 COW / MOR）、partition 级操作、已有表就地迁移（`ALTER TABLE ... SET TBLPROPERTIES('table_type'='ICEBERG')`）、物化视图、Iceberg major compaction（`OPTIMIZE TABLE`）、time travel。
- **4.1 增强**：storage-partitioned joins、partition 级列统计、table compaction。
- **4.2 增强**：deletion vectors、auto compaction、**Iceberg REST Catalog client**（让 Hive 与 Spark / Trino / Flink 共用同一个 catalog 服务，而非各自指 metastore）、Z-ordering、variant type。
- **意义**：Iceberg 是开放表格式，Spark / Impala / Trino 可直接读 Hive 写的 Iceberg 表而**无需格式转换**，这是「多引擎 lakehouse」得以成立的前提——也是 Hive 在 2026 年仍能占据一席之地的核心底气。

## Execution Engines Evolution

```
MR (1.x/2.x 默认, 4.x 弃用) --> Tez (DAG, 4.x 唯一引擎, 默认)
   \--> Spark (2.x/3.x 可选, 4.x 移除)
LLAP: 常驻守护 + 缓存, 叠加在 Tez 之上做交互式加速
```

- **Tez**：用 DAG 取代 MR 的固定 map→reduce 阶段，阶段间数据留在内存 / 本地盘，JVM 容器跨 task 复用；典型查询比 MR 快 2~10 倍。
- **LLAP**：在 Tez 之上加一层常驻执行 + 缓存守护进程，把热数据与部分计算留在进程内，把交互式查询压到亚秒级。它不改变执行模型，只是把「每次都从存储冷启动」变成「热路径常驻」。
- **4.x 的收敛**：Spark 引擎被移除、MR 被弃用之后，**Tez 是 HiveQL 唯一剩下的执行后端**——迁移到 4.x 的脚本必须确认 `hive.execution.engine` 不再被设成 `mr` / `spark`。

## Security and Governance

- **认证**：Kerberos 为主；4.0 起 HS2 支持 SAML 2.0 / JWT（走 Thrift over HTTP）、Kerberos 与 LDAP 可并行开启；HMS 也有 JWT 认证。
- **授权与治理**：细粒度（库 / 表 / 列 / 行）访问控制通常交给 **Apache Ranger**，数据血缘与治理交给 **Apache Atlas**——这是生产 Hive 的事实标准组合。
- **审计**：HS2 操作日志可通过 Web UI 访问，企业安全套件覆盖「认证 → 授权 → 血缘 → 审计」全链。

> [!WARNING]
> 4.2.1 是一次**安全修复版**，修了三处漏洞：HMS direct-SQL 分区路径、HS2 SAML bearer-token 认证、Avro SerDe schema URL 处理。若你的 4.2.0 暴露了带 SAML 的 HS2、或允许用户输入 Avro schema URL，4.2.1 不是可选项。这再次说明：**Hive 的 4.x 线仍在积极安全维护，但 3.x 及更早线已无社区补丁**——跑老线等于跑一个不修 CVE 的系统。

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
- [HBase](/docs/CS/DB/HBase.md)
- [Cassandra](/docs/CS/DB/Cassandra.md)
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
