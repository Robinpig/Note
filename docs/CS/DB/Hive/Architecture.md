# Hive Architecture

## Introduction

Hive 的运行时由两半组成：**HiveServer2（HS2）** 把 HiveQL 编译、优化、提交到执行引擎；**Hive Metastore（HMS）** 是中央 schema 注册表，被 Hive 及 Spark / Impala / Trino 共同消费。两者通过 Thrift 通信，执行层落在 YARN 之上的 Tez DAG（叠加 LLAP 常驻缓存）。理解 Hive 先看组件边界，再看 HS2 内部编译管线与 HMS 的后端/高可用，最后看 4.x 的收敛点。

## Components

```
Client(Beeline/JDBC/ODBC/HWC) --> HiveServer2(HS2)
                                 |-- Compiler + CBO(Apache Calcite)
                                 |-- 提交执行到 YARN
                                        |
                                        v
                                   Tez DAG (+ LLAP daemons) --> HDFS / S3 / Ozone
                                        |
                                        v  (旁路元数据)
                                   Hive Metastore(HMS, Thrift API) <-- Spark / Impala / Trino / Flink 也来读
```

- **HiveServer2 (HS2)**：接受 HiveQL 的 JDBC / ODBC 服务，多租户、支持并发会话与会话级隔离，是 BI 工具接入入口。**4.0 起 HS2 支持 SAML 2.0 / JWT 认证、Kerberos 与 LDAP 可并行开启、支持 Thrift over HTTP（JWT 认证）与优雅关闭**。
- **Hive Metastore (HMS)**：整个 Hadoop 生态的中央 schema 注册表，存 database / table / partition / column 定义、SerDe 信息、表统计、Iceberg 属性；暴露 Thrift API，后端落到关系库（MySQL / PostgreSQL / Oracle）。**4.1.0 起 HMS 作为 standalone 组件发布（binary + Docker 镜像）**；4.0 还加了基于 ZooKeeper 的服务发现与 Thrift over HTTP。
- **Tez**：4.x 唯一受支持的执行引擎（默认），DAG 框架，消除 MR 阶段间写 HDFS 的步骤。详见 [Execution Engines](/docs/CS/DB/Hive/Execution_Engines.md)。
- **LLAP**（Low Latency Analytical Processing）：常驻守护进程 + 优化数据缓存，亚秒级交互查询，持久化查询基础设施让热数据不必每次冷启动。
- **Beeline**：官方 JDBC 客户端，取代旧 `hive` CLI（4.0 起旧 CLI 弃用——它在客户端进程跑编译器、绕过 HS2 认证授权）。
- **HWC（Hive Warehouse Connector）**：让 Spark 应用以完整事务语义读写 Hive ACID / Iceberg 表的桥；不通过 HWC 时 Spark 走兼容层会绕过 ACID 语义。

## HS2 Compilation Pipeline

一条 HiveQL 在 HS2 内部走「编译 → 优化 → 执行」管线，关键阶段：

1. **Parse**：词法/语法分析，生成抽象语法树（AST）。
2. **Semantic Analyze**：绑定元数据（查 HMS 拿到表/列/分区定义）、做类型检查与语义校验，产出查询块（QB）。
3. **Logical Plan**：把 QB 转成逻辑算子树（Operator Tree，如 TableScan / Filter / Join / GroupBy）。
4. **CBO Optimize**：基于 Apache Calcite 的成本优化器重写——join 重排、列裁剪、谓词下推、把符合条件的查询重写成物化视图；4.0 升 Calcite 1.25、4.1 升 1.33。统计信息（`ANALYZE TABLE ... COMPUTE STATISTICS`）是 CBO 的命门。
5. **Physical Plan**：把逻辑计划转成 Tez DAG 的物理任务，决定 container / shuffle / 文件格式。
6. **Execute on Tez**：提交到 YARN，Tez 调度 DAG 任务，读 HDFS/S3 上的数据，结果经 HS2 返回客户端。

## Hive Metastore

HMS 的元数据存储在后端关系库中，核心表包括 `DBS`（库）、`TBLS`（表）、`PARTITIONS`（分区）、`SDS`（存储描述）、`COLUMNS_V2`（列）、以及 ACID 事务表 `txns` / `txn_components` / `completed_txn_components`。HMS 同时提供服务发现（4.0 起基于 ZooKeeper）与 Thrift over HTTP 接口。

**高可用**：多个 HMS 实例以 active/active 运行，共享同一后端 RDBMS；客户端通过 `hive.metastore.uris` 配置 URI 列表，`hive.metastore.uri.selection`（RANDOM 默认 / SEQUENTIAL）决定故障切换时如何挑选实例。Kerberos 集群需把 delegation token store 设为 `org.apache.hadoop.hive.thrift.DBTokenStore`。

## 4.x Removals and Deprecations

> [!WARNING]
> 4.x 的三处移除 / 弃用是升级的主要工作量来源：
> 1. **Hive on Spark 已移除**——`SET hive.execution.engine=spark` 在 4.x 直接不工作，这类作业全部迁到 Tez 或改用 Spark SQL 读同一批 metastore 表。
> 2. **Hive on MapReduce 已弃用**——还在但不再做性能投入，部分新特性（如 rebalance compaction）只以 query-based compaction 跑，应视作迁移目标而非回退项。
> 3. **JDK floor 从 8 跳到 21**（3.x → 4.2.x）——每个为 Java 8 编译的 UDF jar、SerDe、自定义 hook 都要重编重测。想停在 JDK 17 就把上限锁在 4.1 线。

## Links

- [Hive](/docs/CS/DB/Hive.md)
- [Data Model](/docs/CS/DB/Hive/Data_Model.md)
- [Execution Engines](/docs/CS/DB/Hive/Execution_Engines.md)
- [Security and Governance](/docs/CS/DB/Hive/Security_and_Governance.md)
- [Operations](/docs/CS/DB/Hive/Operations.md)

## References

1. [Apache Hive](https://hive.apache.org/)
2. [Hive 4.0 - Overview of Major Changes](https://hive.apache.org/docs/latest/overview-of-major-changes/)
3. [Hive LanguageManual Authorization](https://hive.apache.org/docs/latest/language/languagemanual-authorization/)
4. [Apache Hive Overview (ODP, ships Hive 4.0.1)](https://www.opensourcedataplatform.com/docs/1.3.1.0/concepts/hive-overview)
