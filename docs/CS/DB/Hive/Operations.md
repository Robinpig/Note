# Hive Operations

## Introduction

生产上 Hive 的可运维性集中在三件事：选对**部署模式**、配好**高可用**、踩准**升级与 JDK 红线**。Hive 4.1 起 HMS 可 standalone 部署，进一步把「元数据服务」与「查询服务」解耦。本页汇总运维要点，不替代发行版（CDP / HDP / 社区 tarball）的部署手册。

## Deployment Modes

Hive 有三种 metastore 部署模式：

1. **Embedded**：metastore 跑在 HS2 同一 JVM 内，用内嵌 Derby 做后端。仅限单机试玩，不可多客户端并发。
2. **Local**：metastore 仍在同一 JVM，但后端换成本地/远程 RDBMS（MySQL / PostgreSQL / Oracle）。比 embedded 强，但 metastore 与 HS2 耦合。
3. **Remote（生产标准）**：`hive --service metastore` 作为独立进程，后端连 RDBMS，HS2 通过 `hive.metastore.uris` 远程访问。多 HS2、多 metastore 解耦，是生产默认。

## HMS Standalone (4.1)

4.1.0 起 Hive Metastore 作为 **standalone 组件**发布——提供独立 binary 与 Docker 镜像，可脱离 HS2 单独部署与升级，后端仍落到关系库。这让「把 HMS 当湖仓共享 catalog」的部署更轻：Spark / Impala / Trino 直接连 standalone HMS，不必随之升级 HS2。

## Metastore HA

多个 HMS 实例以 **active/active** 运行，共享同一后端 RDBMS；客户端经 `hive.metastore.uris` 配置 URI 列表，`hive.metastore.uri.selection`（RANDOM 默认 / SEQUENTIAL）决定故障切换时如何挑选实例。Kerberos 集群把 delegation token store 设为 `org.apache.hadoop.hive.thrift.DBTokenStore`。

## HS2 HA

HiveServer2 经 **ZooKeeper 动态服务发现**实现高可用，关键配置：

- `hive.server2.support.dynamic.service.discovery=true`
- `hive.server2.zookeeper.namespace=hiveserver2`
- `hive.zookeeper.quorum=zk1:2181,zk2:2181,zk3:2181`
- `hive.server2.active.passive.ha.enable=true`

HS2 启动后自动在 ZK 注册，客户端（Beeline / JDBC）通过 ZK 拿到可用实例，单个 HS2 宕机不影响服务。

## JDK Floor

| Hive 线 | 最低 JDK |
| :--- | :--- |
| 3.x | 8 |
| 4.0 / 4.1 | 17 |
| 4.2.x | 21 |

每个为旧 JDK 编译的 UDF jar、SerDe、自定义 hook 都要随 JDK floor 重编重测。想停在 JDK 17 就把上限锁在 4.1 线——4.2 要求 JDK 21 在 HS2、metastore、嵌入 Hive 库的客户端**无处不在**。

## Upgrade 3.x to 4.x

升级的主要工作量不在数据，而在兼容性断点：

- **metadata-only upgrade**：用 `schematool -upgradeSchema` 升级 HMS 后端 schema，通常无需重写数据文件。
- **统计信息**：4.x CBO 依赖统计，升级后重跑 `ANALYZE TABLE`。
- **compaction 迁移**：旧 MR-based compaction 作业要迁到 query-based。
- **脚本迁移**：把所有 `hive.execution.engine=mr|spark` 改掉（见 [Execution Engines](/docs/CS/DB/Hive/Execution_Engines.md)），旧 Hive CLI 调用改 Beeline。
- **JDK**：见上表，提前重编自定义代码。

## Monitoring

- **HS2 / HMS Web UI**：查看会话、查询、compaction 队列。
- **Metrics / JMX**：HS2、HMS、LLAP 均暴露 JMX 指标，可接 Prometheus / Grafana 监控并发、compaction 积压、LLAP 缓存命中。
- **审计日志**：Ranger / HS2 操作日志提供访问审计。

## Interop Configuration

- **HWC（Hive Warehouse Connector）**：Spark 以完整事务语义读写 Hive ACID / Iceberg 表的桥；不通过 HWC 时 Spark 走兼容层会绕过 ACID 语义。
- **Iceberg catalog**：Hive 可用自带 HiveCatalog 或 4.2 的 REST Catalog client 对接共享 catalog 服务（见 [Iceberg Integration](/docs/CS/DB/Hive/Iceberg_Integration.md)）。

## Links

- [Hive](/docs/CS/DB/Hive/Hive.md)
- [Architecture](/docs/CS/DB/Hive/Architecture.md)
- [Security and Governance](/docs/CS/DB/Hive/Security_and_Governance.md)
- [Execution Engines](/docs/CS/DB/Hive/Execution_Engines.md)

## References

1. [Hive 4.0 - Overview of Major Changes](https://hive.apache.org/docs/latest/overview-of-major-changes/)
2. [Hive 3 to Hive 4 upgrade and end-of-life](https://www.osseva.io/blog/hive-3-to-4-upgrade)
3. [Apache Hive](https://hive.apache.org/)
4. [Hive 4 Key Features, in depth](https://www.aicassindra.com/blogs/hive_impala/hive_4_features.html)
