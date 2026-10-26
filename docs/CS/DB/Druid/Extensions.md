## Introduction

Druid 把「数据库默认就该有的能力」拆成可插拔扩展：深存储、元数据库、安全认证、近似聚合函数、湖仓输入、监控 emitter——核心发行包里只有骨架。这套机制的直接后果是：**「Druid 支持 X 吗」这类问题，多数答案是「装哪个扩展」**。35.0.0 起 MSQ 任务引擎从扩展升格为核心能力，是这套机制演进的标志性事件；`druid-extensions.loadList` 里残留 `druid-multi-stage-query` 的集群必须删掉，否则未来版本无法启动。查询时函数类扩展的使用方式见 [Query_Engine](/docs/CS/DB/Druid/Query_Engine.md)，部署选型见 [Operations](/docs/CS/DB/Druid/Operations.md)。

## Extension Mechanics

- **两级体系**：**core extensions** 由 committer 维护、随发行包分发（在 `extensions/` 目录，按名字加进 `druid.extensions.loadList` 即可）；**contrib extensions** 社区维护，不在默认 tarball 里，需 `pull-deps` 拉取：
  ```shell
  java -cp "lib/*" -Ddruid.extensions.directory="extensions" \
    org.apache.druid.cli.Main tools pull-deps \
    -c "org.apache.druid.extensions.contrib:<EXTENSION_NAME>:<DRUID_VERSION>"
  ```
  再把名字加进 `loadList`。contrib 的 Maven groupId 几乎都是 `org.apache.druid.extensions.contrib`。
- **第三种加载方式是 classpath**：jar 直接放 classpath 也会被加载，但没有类加载器隔离，依赖冲突自己兜底。
- **加载是进程级的**：每个角色进程按自己的 `common.runtime.properties` 加载——Broker 不需要深存储扩展，Historical 不需要 kerberos，按角色最小化 `loadList`。

## Core Extensions

| 组 | 扩展 | 用途 |
| :--- | :--- | :--- |
| 深存储 | `druid-s3-extensions`、`druid-hdfs-storage`、`druid-azure-extensions`、`druid-google-extensions` | 分片文件放对象存储/HDFS |
| 元数据存储 | `mysql-metadata-storage`、`postgresql-metadata-storage` | 集群目录；MySQL 扩展因许可不含 JDBC 驱动需自备 |
| 流摄取 | `druid-kafka-indexing-service`、`druid-kinesis-indexing-service` | exactly-once supervisor |
| 文件格式 | `druid-parquet-extensions`（依赖 avro）、`druid-orc-extensions`、`druid-avro-extensions`、`druid-protobuf-extensions` | 输入格式 |
| 安全 | `druid-basic-security`、`druid-pac4j`、`druid-kerberos`、`simple-client-sslcontext` | 认证/授权/TLS |
| 查询时函数 | `druid-datasketches`、`druid-time-min-max`、`druid-bloom-filter`、`druid-stats` | 近似聚合、时间 min/max、Bloom 过滤、方差/标准差 |
| Lookup | `druid-lookups-cached-global`、`druid-lookups-cached-single`、`druid-kafka-extraction-namespace` | 维表查找 |
| 部署 | `druid-kubernetes-extensions`、`druid-kubernetes-overlord-extensions`、`druid-ec2-extensions` | K8s 部署/不经 MM 起 task/EC2 自动扩 MM |
| 其它 | `druid-catalog`、`druid-aws-rds-extensions` | 元数据目录管理、RDS 令牌认证 |

`druid-histogram`（近似直方图）**已废弃**，请用 `druid-datasketches` 的 quantiles 聚合器。

## Contrib Extensions

按用途分组，都不随 tarball 分发：

- **湖仓输入**：`druid-iceberg-extensions`（Iceberg 表摄取，31.0.0 增强，38.0.0 跟进 iceberg 1.10.0）、`druid-deltalake-extensions`（Delta Lake，31.0.0 起支持复杂类型与快照版本）。
- **深存储**：`druid-cassandra-storage`、`aliyun-oss-extensions`、`druid-cloudfiles-extensions`、`gce-extensions`。
- **元数据存储**：`sqlserver-metadata-storage`。
- **近似聚合**：`druid-ddsketch`（29.0.0 引入）、`druid-momentsketch`、`druid-tdigestsketch`、`druid-spectator-histogram`、`druid-distinctcount`、`druid-exact-count-bitmap`、`druid-compressed-bigdecimal`、`druid-moving-average-query`（窗口类移动平均）。
- **监控 emitter**：`prometheus-emitter`、`graphite-emitter`、`statsd-emitter`、`kafka-emitter`、`opentsdb-emitter`、`influxdb-emitter`、`ambari-metrics-emitter`、`openlineage-emitter`（38.0.0 引入，走 RequestLogger 把血缘发给 OpenLineage 兼容 API）。
- **安全与运维**：`druid-ranger-security`（接 Apache Ranger 做访问控制）、`druid-consul-extensions`（37.0.0 引入：Consul 做服务发现 + leader 选举，替掉 ZooKeeper，支持 ACL 与 TLS/mTLS）、`druid-rabbit-indexing-service`（RabbitMQ 摄取）、`druid-thrift-extensions`（37.0.0 起 Kafka/Kinesis 的 Thrift 输入格式）。

## Lookups in Detail

lookup 是「查询时维表」的标准机制，与 join 引擎平行存在：

- **配置面**：经 Coordinator API 管理（`/druid/coordinator/v1/lookups/{tier}/{id}`），首次使用先 POST 一个空 `{}` 初始化；配置改动由 Coordinator 周期性下推给 tier 内所有节点，删除失败不重试（节点宕机时可能残留）。
- **tier 语义独立于 Historical tier**：lookup tier 决定「哪些节点拿到这份 lookup」——流任务的 Peon 可按数据源归属不同 tier，Historical 可全放 `__default`。
- **实现**：`cached-global`（JVM 全局缓存 + JDBC/URI 取数）、`cached-single`（按 lookup 隔离缓存）、`kafka-extraction-namespace`（从 Kafka topic 增量更新维表，需要 `druid-kafka-extraction-namespace` + 命名空间 lookup 扩展配合）。

## Kubernetes Extensions

K8s 是 Druid 云上部署的主线，有三条并存的路：

1. **Druid Operator**：37.0.0 起迁出主仓，独立仓库 `apache/druid-operator` 维护，经 CRD 管理集群生命周期。
2. **`druid-kubernetes-overlord-extensions`**（37.0.0 GA）：不经 MiddleManager，由 Overlord 直接起 task pod；36.0.0 加了实验性的 fabric8 SharedInformers 客户端模式（`druid.indexer.runner.useK8sSharedInformers=true`）大幅降低对 API server 的流量；38.0.0 支持按名选择 podTemplate（`druid.indexer.runner.allowTaskPodTemplateSelection`，默认 false）。
3. **`druid-kubernetes-extensions`**：面向「不部署 ZooKeeper 的 K8s 集群」的整体部署方案。

选型上：要完整生命周期管理用 operator，只要「弹性跑 task」用 overlord 扩展即可；`druid-ec2-extensions` 是 AWS 上自动扩 MiddleManager 的老路。

## Security Extensions

- **`druid-basic-security`**：HTTP Basic 认证 + RBAC。权限模型是「资源类型 × 动作」：DATASOURCE / CONFIG / STATE / EXTERNAL 各有 READ/WRITE；MSQ 读外部数据要 `EXTERNAL READ`（24.0.0 引入，配 basic-security 时走 roles API 授予）。37.0.0 新增 `ReadOnly` authorizer——Druid 第一个全局 authorizer，一刀切禁掉所有非 READ 操作（已知坑：`GET /druid/indexer/v1/supervisor` 这类只读端点也要求 WRITE，会失败）。
- **`druid-pac4j`**：OpenID Connect 等第三方认证（35.0.0 pac4j 4→5，滚动升级期间会话序列化变化可能登出用户；Kerberos 场景 `cookieSignatureSecret` 变必填）。
- **`druid-kerberos`** + **`simple-client-sslcontext`**：Kerberos 认证与进程间 TLS。
- **审计**：`druid.audit.manager.type` 设 `log` 或 `sql`（29.0.0 引入），覆盖 Coordinator/Overlord 与 basic-security 的操作。

## Links

- [Druid](/docs/CS/DB/Druid.md)
- [Query Engine](/docs/CS/DB/Druid/Query_Engine.md)
- [Operations](/docs/CS/DB/Druid/Operations.md)
- [Data Management](/docs/CS/DB/Druid/Data_Management.md)
- [ZooKeeper](/docs/CS/Framework/ZooKeeper/ZooKeeper.md)

## References

1. [Druid Extensions](https://druid.apache.org/docs/latest/development/extensions/)
2. [Druid Lookups](https://druid.apache.org/docs/latest/querying/lookups)
3. [Druid Security Overview](https://druid.apache.org/docs/latest/operations/security-overview.html)
4. [Druid 35.0.0 Release Notes (MSQ becomes core)](https://druid.apache.org/docs/35.0.0/release-info/release-notes)
